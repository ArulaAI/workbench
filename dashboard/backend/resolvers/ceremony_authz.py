"""Authorization policy for the Define Ceremony.

Single source of truth for per-spec ownership rules. Every protected
mutation routes through `CeremonyAbility.authorize(action, spec_type)`
before any file write.

The policy is structured as a CanCan-style PDP with a flat `can()` method
that matches one-to-one with the authorization matrix in the RFC:

    specs/tech/speed-define-ceremony-ownership.md § Authorization Model

The three classical roles of an authorization pipeline — PEP, PDP, PIP —
are separated:

- PEP: each resolver calls `ability.authorize(action, spec_type)` and
  proceeds on success, raises on denial.
- PDP: `CeremonyAbility` itself; `can()` returns bool, no disk I/O.
- PIP: `CeremonyAbility.for_request(feature_name, spec_type)` loads the
  facts the PDP needs — actor, claim file, commit record (only for
  ratify), roster, and a single `now` timestamp so two checks in the
  same request cannot disagree about whether a claim is stale.

There is no solo-mode branch. A sole actor is `n = 1` in the same
multi-actor model: they claim each spec, pass `_is_active_claimant` as
the only roster member who could have written the claim, and commit
under the normal rules. The single functional difference — inline
auto-ratification at commit time — lives inside `commitSpec`, not here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..paths import SpeedPaths, get_paths
from .ceremony_types import (
    SpecClaim,
    _read_json,
    get_current_actor,
    load_spec_claim,
)


DEFAULT_STALE_WINDOW_SECONDS = 3600


def _read_stale_window_seconds() -> int:
    """Return the stale window in seconds from config or default.

    Mirrors the bash `OWNERSHIP_STALE_WINDOW` contract in lib/ownership.sh:
    prefer `TOML_MULTIPLAYER_STALE_WINDOW` env var (which config.sh sets
    from speed.toml), fall back to 3600 seconds (one hour).
    """
    raw = os.environ.get("TOML_MULTIPLAYER_STALE_WINDOW", "")
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return DEFAULT_STALE_WINDOW_SECONDS


def _parse_iso_utc(ts: str) -> datetime:
    """Parse an ISO 8601 timestamp into a timezone-aware UTC datetime.

    Tolerates both `...Z` suffix and `+00:00` offset. Any parse failure
    returns `datetime.min` in UTC so the caller treats the claim as
    infinitely old — this matches the bash behavior where an unparseable
    timestamp falls through to stale.
    """
    if not ts:
        return datetime.min.replace(tzinfo=timezone.utc)
    normalized = ts.replace("Z", "+00:00") if ts.endswith("Z") else ts
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass
class _Actor:
    name: str
    email: str


class CeremonyAbility:
    """Per-request authorization policy. Do not construct directly;
    use `CeremonyAbility.for_request(feature_name, spec_type)`.
    """

    def __init__(
        self,
        *,
        actor: _Actor,
        feature_name: str,
        spec_type: str | None,
        claim: SpecClaim | None,
        commit_record: dict[str, Any] | None,
        roster_emails: list[str],
        now: datetime,
        stale_window_seconds: int,
    ) -> None:
        self.actor = actor
        self.feature_name = feature_name
        self.spec_type = spec_type
        self._claim = claim
        self._commit_record = commit_record
        self._roster_emails = roster_emails
        self._now = now
        self._stale_window = stale_window_seconds

    # ── Public API ──────────────────────────────────────────────

    def can(self, action: str, spec_type: str | None = None) -> bool:
        """Return True iff the current actor is allowed to perform *action*.

        Matches the authorization matrix in the RFC row-for-row.
        """
        match action:
            case "declare":
                return True
            case "claim":
                return self._unclaimed_or_stale(spec_type)
            case "release":
                return self._is_active_claimant(spec_type)
            case "edit" | "resolve" | "commit":
                return self._is_active_claimant(spec_type)
            case "decompose":
                return (
                    self._is_active_claimant(spec_type)
                    and self._is_rfc_slot(spec_type)
                )
            case "suggest":
                return not self._is_active_claimant(spec_type)
            case "ratify":
                return not self._is_commit_author(spec_type)
            case "abandon":
                return self._is_active_claimant("prd")
            case _:
                return False

    def authorize(self, action: str, spec_type: str | None = None) -> None:
        """Raise `PermissionError` with a caller-facing message on deny."""
        if not self.can(action, spec_type):
            reason = self._deny_reason(action, spec_type)
            raise PermissionError(reason)

    # ── Helpers used from commit.py etc. (not from can()) ──────

    def has_eligible_ratifier(self, commit_author_email: str) -> bool:
        """Return True iff any current roster member is not the commit author.

        Called from `commitSpec` to decide whether to write the ratification
        inline. Not consulted by the authorization policy.
        """
        return any(email != commit_author_email for email in self._roster_emails)

    # ── Private predicates ─────────────────────────────────────

    def _is_active_claimant(self, spec_type: str | None) -> bool:
        if not spec_type:
            return False
        claim = self._claim_for(spec_type)
        if claim is None or claim.released_at is not None:
            return False
        if claim.claimant_email != self.actor.email:
            return False
        return not self._is_stale(claim)

    def _unclaimed_or_stale(self, spec_type: str | None) -> bool:
        if not spec_type:
            return False
        claim = self._claim_for(spec_type)
        if claim is None or claim.released_at is not None:
            return True
        return self._is_stale(claim)

    def _is_commit_author(self, spec_type: str | None) -> bool:
        if not spec_type:
            return False
        record = self._commit_record_for(spec_type)
        if record is None:
            # Nothing has been committed, so nothing can be ratified.
            # Returning False here means the ratify rule `not _is_commit_author`
            # would return True for an uncommitted spec; `submitRatification`
            # has a separate precondition that the commit file must exist,
            # so the order of checks at the resolver layer is: authorize,
            # then precondition check.
            return False
        return record.get("claimant_email") == self.actor.email

    @staticmethod
    def _is_rfc_slot(spec_type: str | None) -> bool:
        if not spec_type:
            return False
        return spec_type == "rfc" or spec_type.startswith("rfc-")

    def _is_stale(self, claim: SpecClaim) -> bool:
        last_activity = _parse_iso_utc(claim.last_activity_at)
        age_seconds = (self._now - last_activity).total_seconds()
        return age_seconds > self._stale_window

    def _claim_for(self, spec_type: str) -> SpecClaim | None:
        # The PIP loads the claim for the spec this request is acting on.
        # If the resolver needs to check a different spec_type (e.g., the
        # abandon rule checks PRD specifically), we fall through to disk.
        if self.spec_type == spec_type and self._claim is not None:
            return self._claim
        if self._claim is not None and self._claim.spec_type == spec_type:
            return self._claim
        # Fallback: load it on demand. Rare path; happens only for
        # cross-spec checks like `abandon` which always asks about "prd"
        # regardless of the request's primary spec_type.
        paths = get_paths(Path(os.environ.get("SPEED_PROJECT_ROOT", os.getcwd())))
        return load_spec_claim(paths.ceremony_claim(self.feature_name, spec_type))

    def _commit_record_for(self, spec_type: str) -> dict[str, Any] | None:
        # Mirror the same pattern as _claim_for.
        if self.spec_type == spec_type and self._commit_record is not None:
            return self._commit_record
        paths = get_paths(Path(os.environ.get("SPEED_PROJECT_ROOT", os.getcwd())))
        commit_path = paths.ceremony_commit_record(self.feature_name, spec_type)
        return _read_json(commit_path)

    def _deny_reason(self, action: str, spec_type: str | None) -> str:
        """Produce a user-facing denial message the UI can map to a caption."""
        target = spec_type or "ceremony"
        if action == "claim":
            claim = self._claim_for(spec_type) if spec_type else None
            if claim and claim.released_at is None and not self._is_stale(claim):
                return f"spec {target} is already claimed by {claim.claimant}"
            return f"cannot claim {target}"
        if action in ("edit", "resolve", "commit", "decompose", "release"):
            claim = self._claim_for(spec_type) if spec_type else None
            if claim and claim.claimant_email != self.actor.email:
                return f"only the claimant of {target} ({claim.claimant}) can {action}"
            if claim is None:
                return f"{target} is not claimed; claim it first before you can {action}"
            if claim.released_at is not None:
                return f"{target} claim has been released; re-claim it first"
            return f"cannot {action} on {target}"
        if action == "suggest":
            return f"you own {target}; you cannot suggest on your own spec"
        if action == "ratify":
            return f"cannot ratify own spec — you committed {target}"
        if action == "abandon":
            return "only the PRD claimant can abandon the ceremony"
        return f"{self.actor.email} cannot {action} on {target}"

    # ── PIP: factory method ─────────────────────────────────────

    @classmethod
    def for_request(
        cls,
        feature_name: str,
        spec_type: str | None = None,
        *,
        project_root: Path | None = None,
        needs_commit_record: bool = False,
    ) -> "CeremonyAbility":
        """Load the facts the PDP needs for this request.

        `needs_commit_record` is True only for the `ratify` path; every other
        action reads the live claim, not the commit record, so loading it
        unconditionally would be wasted disk I/O.
        """
        root = project_root or Path(
            os.environ.get("SPEED_PROJECT_ROOT", os.getcwd())
        )
        paths = get_paths(root)

        name, email = get_current_actor()
        actor = _Actor(name=name, email=email)

        claim: SpecClaim | None = None
        if spec_type:
            claim = load_spec_claim(paths.ceremony_claim(feature_name, spec_type))

        commit_record: dict[str, Any] | None = None
        if needs_commit_record and spec_type:
            commit_record = _read_json(
                paths.ceremony_commit_record(feature_name, spec_type)
            )

        roster_emails = _load_roster_emails(paths)

        now = datetime.now(timezone.utc)
        stale_window = _read_stale_window_seconds()

        return cls(
            actor=actor,
            feature_name=feature_name,
            spec_type=spec_type,
            claim=claim,
            commit_record=commit_record,
            roster_emails=roster_emails,
            now=now,
            stale_window_seconds=stale_window,
        )


def _load_roster_emails(paths: SpeedPaths) -> list[str]:
    """Return the list of roster member emails.

    In single-player mode (`.speed/shared/` absent) the roster is a
    synthetic list containing only the current actor, so every
    `has_eligible_ratifier` check in that mode returns False.
    """
    if not paths.mp_enabled or paths.roster_dir is None:
        _, email = get_current_actor()
        return [email]

    emails: list[str] = []
    if paths.roster_dir.is_dir():
        for f in sorted(paths.roster_dir.glob("*.json")):
            data = _read_json(f)
            if data and "email" in data:
                emails.append(data["email"])
    # Defensive: empty roster in MP mode falls back to single-player
    # semantics rather than a ceremony that can never advance.
    if not emails:
        _, email = get_current_actor()
        emails = [email]
    return emails
