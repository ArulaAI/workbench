"""GraphQL resolvers for per-spec claims.

Three mutations and one query, backed by per-spec `claim-{spec_type}.json`
files in the ceremony directory. Concurrent-claim serialization uses an
advisory file lock via `fcntl` — the lock is held only for the read-write
transaction, not for the duration of the request.

See: specs/tech/speed-define-ceremony-ownership.md § Data Model Changes
for the file shape and § Claim lifecycle for the state machine.
"""

from __future__ import annotations

import errno
import fcntl
import logging
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from ..paths import SpeedPaths, get_paths
from .ceremony_authz import CeremonyAbility, _parse_iso_utc, _read_stale_window_seconds
from .ceremony_types import (
    SpecClaim,
    SpecClaimInfo,
    get_current_actor,
    load_spec_claim,
    save_spec_claim,
)

log = logging.getLogger("speed.dashboard.ceremony.claims")


def _to_info(claim: SpecClaim) -> SpecClaimInfo:
    """Convert the on-disk dataclass to the GraphQL projection."""
    return SpecClaimInfo(
        spec_type=claim.spec_type,
        claimant=claim.claimant,
        claimant_email=claim.claimant_email,
        claimed_at=claim.claimed_at,
        last_activity_at=claim.last_activity_at,
        released_at=claim.released_at,
    )


_VALID_SPEC_TYPE_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789-")


def _validate_spec_type(spec_type: str) -> None:
    """Raise ValueError if spec_type doesn't match ^(prd|design|rfc|rfc-[a-z0-9-]+)$."""
    if not spec_type:
        raise ValueError("spec_type must not be empty")
    if spec_type in ("prd", "design", "rfc"):
        return
    if not spec_type.startswith("rfc-"):
        raise ValueError(f"invalid spec_type: {spec_type}")
    slug = spec_type[len("rfc-"):]
    if not slug:
        raise ValueError(f"invalid spec_type: {spec_type}")
    if not all(c in _VALID_SPEC_TYPE_CHARS for c in slug):
        raise ValueError(f"invalid spec_type: {spec_type}")
    if slug[0] == "-" or slug[-1] == "-":
        raise ValueError(f"invalid spec_type: {spec_type}")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _locked_claim_file(path: Path) -> Iterator[None]:
    """Advisory file lock around a claim-{spec_type}.json read-write cycle.

    Uses a sibling `.lock` file so we don't need the claim file itself
    to exist. The lock is released at the end of the context block.
    Concurrent attempts to claim the same spec serialize here — the
    loser sees the winner's claim on re-read and fails the precondition.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _is_stale(claim: SpecClaim, now: datetime, stale_window: int) -> bool:
    last_activity = _parse_iso_utc(claim.last_activity_at)
    return (now - last_activity).total_seconds() > stale_window


# ── Mutations ─────────────────────────────────────────────────────


def claim_spec(
    project_root: Path,
    feature_name: str,
    spec_type: str,
) -> SpecClaim:
    """Claim a spec. Fails if another actor holds an active claim.

    If the existing claim is released or stale, this call transitions it
    to released-via-stale and writes a fresh claim in one transaction.

    Per the RFC, every claim event is written to the multiplayer event
    stream so the claim history is reconstructable. The event write is
    a best-effort companion — its failure does not block the claim.
    """
    _validate_spec_type(spec_type)

    paths = get_paths(project_root)
    claim_path = paths.ceremony_claim(feature_name, spec_type)

    actor_name, actor_email = get_current_actor()
    now = datetime.now(timezone.utc)
    stale_window = _read_stale_window_seconds()

    with _locked_claim_file(claim_path):
        existing = load_spec_claim(claim_path)
        if existing is not None:
            if existing.released_at is None:
                if existing.claimant_email == actor_email:
                    # Reclaiming your own active claim is a no-op refresh.
                    existing.last_activity_at = now.isoformat()
                    save_spec_claim(claim_path, existing)
                    return existing
                if not _is_stale(existing, now, stale_window):
                    raise PermissionError(
                        f"spec {spec_type} is already claimed by {existing.claimant}"
                    )
                # Stale takeover: mark old claim released, then write new.
                existing.released_at = now.isoformat()
                save_spec_claim(claim_path, existing)
                _emit_event(
                    paths, feature_name, "claim_stale_takeover",
                    spec_type=spec_type,
                    previous_claimant=existing.claimant,
                    previous_claimant_email=existing.claimant_email,
                )

        new_claim = SpecClaim(
            spec_type=spec_type,
            claimant=actor_name,
            claimant_email=actor_email,
            claimed_at=now.isoformat(),
            last_activity_at=now.isoformat(),
            released_at=None,
        )
        save_spec_claim(claim_path, new_claim)

    _emit_event(
        paths, feature_name, "claim_started",
        spec_type=spec_type,
        claimant=actor_name,
        claimant_email=actor_email,
    )
    return new_claim


def release_spec(
    project_root: Path,
    feature_name: str,
    spec_type: str,
) -> SpecClaim:
    """Release own claim. No-op if already released."""
    _validate_spec_type(spec_type)

    paths = get_paths(project_root)
    claim_path = paths.ceremony_claim(feature_name, spec_type)

    actor_name, actor_email = get_current_actor()
    now = datetime.now(timezone.utc)

    with _locked_claim_file(claim_path):
        existing = load_spec_claim(claim_path)
        if existing is None:
            raise FileNotFoundError(
                f"no claim on {spec_type} to release"
            )
        if existing.claimant_email != actor_email:
            raise PermissionError(
                f"only the claimant of {spec_type} ({existing.claimant}) can release it"
            )
        if existing.released_at is not None:
            # Idempotent: releasing an already-released claim is a no-op.
            return existing

        existing.released_at = now.isoformat()
        existing.last_activity_at = now.isoformat()
        save_spec_claim(claim_path, existing)

    _emit_event(
        paths, feature_name, "claim_released",
        spec_type=spec_type,
        claimant=actor_name,
        claimant_email=actor_email,
    )
    return existing


# ── Query ─────────────────────────────────────────────────────────


def ceremony_claims(
    project_root: Path,
    feature_name: str,
) -> list[SpecClaim]:
    """Return every claim file on disk, including released entries.

    Enumerated by listing `claim-*.json` files in the ceremony directory
    and deserializing each. Order is alphabetical by spec_type for a
    stable display order.
    """
    paths = get_paths(project_root)
    ceremony_dir = paths.ceremony_dir(feature_name)
    if not ceremony_dir.is_dir():
        return []

    claims: list[SpecClaim] = []
    for f in sorted(ceremony_dir.glob("claim-*.json")):
        claim = load_spec_claim(f)
        if claim is not None:
            claims.append(claim)
    return claims


# ── Helpers ───────────────────────────────────────────────────────


def refresh_claim_activity(
    project_root: Path,
    feature_name: str,
    spec_type: str,
) -> None:
    """Update `last_activity_at` on the current actor's claim.

    Called from `update_draft`, `generate_draft`, `resolve_suggestion`,
    `decompose_draft`, and `commit_spec` so every mutation by the claimant
    resets the stale clock. No-op if the claim does not exist, is released,
    or is held by someone else — the caller has already passed
    authorization by the time this runs, so a missing/foreign claim at
    this point would be a race we silently accept.
    """
    paths = get_paths(project_root)
    claim_path = paths.ceremony_claim(feature_name, spec_type)

    _, actor_email = get_current_actor()
    now_iso = _now_iso()

    with _locked_claim_file(claim_path):
        claim = load_spec_claim(claim_path)
        if claim is None:
            return
        if claim.released_at is not None:
            return
        if claim.claimant_email != actor_email:
            return
        claim.last_activity_at = now_iso
        save_spec_claim(claim_path, claim)


def retire_claim_on_commit(
    project_root: Path,
    feature_name: str,
    spec_type: str,
    committed_at: str,
) -> None:
    """Set `released_at = committed_at` on the claim file.

    The claim file is retired, not deleted — the tab bar continues to
    display "committed by {name}" by reading this file directly without
    having to load the commit record for simple UI queries.
    """
    paths = get_paths(project_root)
    claim_path = paths.ceremony_claim(feature_name, spec_type)

    with _locked_claim_file(claim_path):
        claim = load_spec_claim(claim_path)
        if claim is None:
            return
        claim.released_at = committed_at
        claim.last_activity_at = committed_at
        save_spec_claim(claim_path, claim)


def _emit_event(
    paths: SpeedPaths,
    feature_name: str,
    kind: str,
    **payload: str,
) -> None:
    """Best-effort append to the multiplayer event stream.

    Silently swallows errors — the claim write has already committed by
    the time this is called; an event log failure does not invalidate
    the claim. In single-player mode the events dir is None so this is
    a no-op.
    """
    events_dir = paths.events_dir
    if events_dir is None:
        return
    try:
        events_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        actor = payload.get("claimant", payload.get("claimant_email", "unknown"))
        filename = f"{timestamp}_{actor}_{kind}_{feature_name}.jsonl"
        event_path = events_dir / filename
        import json as _json
        event_data = {
            "type": f"ceremony.{kind}",
            "feature": feature_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **payload,
        }
        event_path.write_text(_json.dumps(event_data) + "\n", encoding="utf-8")
    except OSError as exc:
        log.warning("Failed to write ceremony event %s: %s", kind, exc)
