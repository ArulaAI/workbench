"""GraphQL resolver for per-spec commitment and ratification.

Every committed spec has its own `commit-{spec_type}.json` file. The
ceremony state machine advances when every drafted spec has a matching
commit record; per-spec ratification advances each spec independently.

Inline auto-ratification: if no eligible ratifier exists at commit time
(i.e. every roster member is the commit author), `commitSpec` writes
`ratification-{spec_type}.json` directly with `source: "no-eligible-ratifier"`
and advances the ceremony in the same call. This replaces the old
solo-author exemption with a uniform rule that also covers multi-actor
rosters that have lost every non-author.

See: specs/tech/speed-define-ceremony-ownership.md § State Machine.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..paths import get_paths
from .ceremony_authz import CeremonyAbility
from .ceremony_claims import retire_claim_on_commit
from .ceremony_derive import derive_transition_sets, has_eligible_ratifier
from .ceremony_types import (
    CeremonyState,
    CeremonyStatus,
    CommitRecord,
    DismissedSummary,
    Ratification,
    RatificationState,
    SpecClaimInfo,
    SpecProgressInfo,
    SuggestionHistory,
    Verdict,
    VerdictEntry,
    _load_ceremony_state,
    _read_json,
    _write_json,
    get_current_actor,
    load_ratification,
    load_spec_claim,
    save_ratification,
    transition_ceremony_state,
)

log = logging.getLogger("speed.dashboard.ceremony.commitment")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_commit(project_root: Path, feature_name: str, spec_type: str) -> dict | None:
    paths = get_paths(project_root)
    return _read_json(paths.ceremony_commit_record(feature_name, spec_type))


def _save_commit(
    project_root: Path, feature_name: str, spec_type: str, data: dict
) -> None:
    paths = get_paths(project_root)
    _write_json(paths.ceremony_commit_record(feature_name, spec_type), data)


def _dict_to_commit_record(d: dict) -> CommitRecord:
    sh = d.get("suggestion_history", {})
    dm = sh.get("dismissed", {})
    return CommitRecord(
        feature_name=d["feature_name"],
        spec_type=d.get("spec_type", "prd"),
        revision_id=d.get("revision_id", ""),
        claimant=d["claimant"],
        claimant_email=d["claimant_email"],
        committed_at=d["committed_at"],
        validation_state_ref=d.get("validation_state_ref", ""),
        context_package_ref=d.get("context_package_ref", ""),
        suggestion_history=SuggestionHistory(
            received=sh.get("received", 0),
            accepted=sh.get("accepted", 0),
            dismissed=DismissedSummary(
                count=dm.get("count", 0),
                reasons=dm.get("reasons", []),
            ),
        ),
        spec_path=d.get("spec_path", ""),
        decomposition_ref=d.get("decomposition_ref"),
        is_multiplayer=d.get("is_multiplayer", False),
        ratification_threshold=d.get("ratification_threshold", 1),
        ratification_status=d.get("ratification_status", "pending"),
    )


def _verdict_dataclass_to_entry(v: Verdict) -> VerdictEntry:
    """Convert a Verdict dataclass to the strawberry VerdictEntry type."""
    return VerdictEntry(
        id="",  # ids are not stored on Verdict; generated at display time
        revision_id="",
        actor=v.actor,
        actor_email=v.actor_email,
        verdict=v.verdict,
        comment=v.comment,
        timestamp=v.submitted_at,
    )


# ── Queries ───────────────────────────────────────────────────────


def get_commit_record(
    project_root: Path, feature_name: str, spec_type: str
) -> CommitRecord | None:
    data = _load_commit(project_root, feature_name, spec_type)
    if data is None:
        return None
    return _dict_to_commit_record(data)


def get_ratification_state(
    project_root: Path, feature_name: str, spec_type: str
) -> RatificationState | None:
    paths = get_paths(project_root)
    ratification_path = paths.ceremony_ratification(feature_name, spec_type)
    ratification = load_ratification(ratification_path)

    commit_data = _load_commit(project_root, feature_name, spec_type)
    if commit_data is None and ratification is None:
        return None

    _, actor_email = get_current_actor()

    if ratification is None:
        # Commit exists but no ratification file yet. Return a pending shape.
        threshold = commit_data.get("ratification_threshold", 1) if commit_data else 1
        is_author = (
            commit_data is not None
            and commit_data.get("claimant_email") == actor_email
        )
        return RatificationState(
            feature_name=feature_name,
            revision_id=commit_data.get("revision_id", "") if commit_data else "",
            status="pending",
            ratification_count=0,
            threshold=threshold,
            verdicts=[],
            is_author=is_author,
            has_voted=False,
        )

    entries = [_verdict_dataclass_to_entry(v) for v in ratification.verdicts]
    approvals = sum(1 for v in ratification.verdicts if v.verdict == "approve")
    threshold = (
        commit_data.get("ratification_threshold", 1) if commit_data else 1
    )
    is_author = (
        commit_data is not None
        and commit_data.get("claimant_email") == actor_email
    )
    has_voted = any(v.actor_email == actor_email for v in ratification.verdicts)

    if ratification.ratified:
        status = "ratified"
    elif any(v.verdict == "reject" for v in ratification.verdicts):
        status = "rejected"
    else:
        status = "pending"

    return RatificationState(
        feature_name=feature_name,
        revision_id=ratification.revision_id,
        status=status,
        ratification_count=approvals,
        threshold=threshold,
        verdicts=entries,
        is_author=is_author,
        has_voted=has_voted,
    )


# ── Mutations ─────────────────────────────────────────────────────


def _compute_spec_hash(project_root: Path, feature_name: str, spec_type: str) -> str:
    """Hash just the spec being committed, not the aggregate."""
    from ..ceremony_generator import load_spec_draft

    draft = load_spec_draft(project_root, feature_name, spec_type)
    if draft is None:
        return ""
    return hashlib.sha256(draft.content.encode()).hexdigest()[:12]


def _context_package_reference(project_root: Path, feature_name: str) -> str:
    """Return a reproducible path-and-hash reference for the consumed context."""
    path = get_paths(project_root).ceremony_context_package(feature_name)
    if not path.is_file():
        return ""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    try:
        display = path.relative_to(project_root).as_posix()
    except ValueError:
        display = str(path)
    return f"{display}#sha256={digest}"


def commit_spec(
    project_root: Path, feature_name: str, spec_type: str
) -> CommitRecord:
    """Commit a single spec. Advances ceremony state when the gate clears.

    Flow:
    1. authorize("commit", spec_type) — caller must be the active claimant
    2. Validate: no failing Tier 2 dimensions on this spec
    3. Write commit-{spec_type}.json and retire claim-{spec_type}.json
    4. Re-derive transition sets. If committed == drafted, advance ceremony
       DRAFTING → COMMITTED.
    5. Check has_eligible_ratifier. If no eligible ratifier exists, write
       ratification-{spec_type}.json inline with source: "no-eligible-ratifier"
       and re-derive. If ratified == drafted, advance COMMITTED → RATIFIED.
    """
    ability = CeremonyAbility.for_request(
        feature_name, spec_type, project_root=project_root
    )
    ability.authorize("commit", spec_type)

    paths = get_paths(project_root)
    state_path = paths.ceremony_state(feature_name)
    state = _load_ceremony_state(state_path)

    # Validation gate: no fail-level validations on this spec_type.
    from ..ceremony_validator import load_validation_state

    vs = load_validation_state(project_root, feature_name, spec_type=spec_type)
    if vs:
        fails = [d for d in vs.dimensions if d.status == "fail"]
        if fails:
            dim_names = ", ".join(d.name for d in fails)
            raise ValueError(
                f"Failing validation(s) on {spec_type}: {dim_names}. "
                "Fix all failures before committing."
            )

    # Compute spec hash and load the draft for spec_path.
    from ..ceremony_generator import load_spec_draft

    draft = load_spec_draft(project_root, feature_name, spec_type)
    if draft is None:
        raise FileNotFoundError(
            f"No {spec_type} draft for feature '{feature_name}'"
        )

    content_hash = hashlib.sha256(draft.content.encode()).hexdigest()[:12]

    # Per-spec suggestion history (filter to this spec_type).
    from .ceremony_suggestions import get_suggestion_history

    sug_history = get_suggestion_history(
        project_root, feature_name, spec_type=spec_type
    )

    # Decomposition reference (only if an RFC slot and decomposition exists).
    # Check both the new per-spec path and the legacy unsuffixed path for
    # backward compatibility with pre-ownership ceremonies.
    decomposition_ref: str | None = None
    is_rfc_slot = spec_type == "rfc" or spec_type.startswith("rfc-")
    if is_rfc_slot:
        decomp_path = paths.ceremony_decomposition(feature_name, spec_type)
        if decomp_path.exists():
            decomposition_ref = decomp_path.name
        elif paths.ceremony_decomposition(feature_name, "").exists():
            decomposition_ref = paths.ceremony_decomposition(feature_name, "").name

    is_mp = paths.mp_enabled
    committed_at = _now_iso()

    commit_data: dict[str, Any] = {
        "feature_name": feature_name,
        "spec_type": spec_type,
        "revision_id": state.current_revision,
        "claimant": ability.actor.name,
        "claimant_email": ability.actor.email,
        "committed_at": committed_at,
        "validation_state_ref": content_hash,
        "context_package_ref": _context_package_reference(project_root, feature_name),
        "suggestion_history": {
            "received": sug_history.received,
            "accepted": sug_history.accepted,
            "dismissed": {
                "count": sug_history.dismissed.count,
                "reasons": sug_history.dismissed.reasons,
            },
        },
        "spec_path": draft.file_path,
        "decomposition_ref": decomposition_ref,
        "is_multiplayer": is_mp,
        "ratification_threshold": 1,
        "ratification_status": "pending",
    }

    _save_commit(project_root, feature_name, spec_type, commit_data)
    retire_claim_on_commit(project_root, feature_name, spec_type, committed_at)

    # Re-derive and advance ceremony state if the gate clears.
    drafted, committed, _ = derive_transition_sets(
        feature_name, project_root=project_root
    )
    if drafted and committed == drafted:
        current_status = _current_ceremony_status(state)
        if current_status == CeremonyStatus.DRAFTING:
            transition_ceremony_state(
                feature_name,
                CeremonyStatus.COMMITTED,
                project_root=project_root,
            )

    # Inline auto-ratification when no eligible ratifier exists.
    if not ability.has_eligible_ratifier(ability.actor.email):
        ratification = Ratification(
            spec_type=spec_type,
            revision_id=state.current_revision,
            ratified=True,
            verdicts=[],
            source="no-eligible-ratifier",
        )
        save_ratification(
            paths.ceremony_ratification(feature_name, spec_type), ratification
        )
        commit_data["ratification_status"] = "ratified"
        _save_commit(project_root, feature_name, spec_type, commit_data)

        # Re-derive and advance COMMITTED → RATIFIED if the gate clears.
        drafted, _, ratified = derive_transition_sets(
            feature_name, project_root=project_root
        )
        state = _load_ceremony_state(state_path)
        current_status = _current_ceremony_status(state)
        if (
            drafted
            and ratified == drafted
            and current_status == CeremonyStatus.COMMITTED
        ):
            transition_ceremony_state(
                feature_name,
                CeremonyStatus.RATIFIED,
                project_root=project_root,
            )

    return _dict_to_commit_record(commit_data)


def submit_ratification(
    project_root: Path,
    feature_name: str,
    spec_type: str,
    verdict: str,
    comment: str | None = None,
) -> RatificationState:
    """Submit a verdict on a committed spec.

    Rejects the caller if their email matches the commit record's
    claimant_email. No solo-actor exemption in this path — sole actors
    never reach `submitRatification` because `commitSpec` handles them
    inline via the no-eligible-ratifier branch.
    """
    if verdict not in ("approve", "reject"):
        raise ValueError(f"Invalid verdict: {verdict}")
    if verdict == "reject" and not comment:
        raise ValueError("Rejection requires a comment")

    ability = CeremonyAbility.for_request(
        feature_name,
        spec_type,
        project_root=project_root,
        needs_commit_record=True,
    )
    ability.authorize("ratify", spec_type)

    paths = get_paths(project_root)
    commit_data = _load_commit(project_root, feature_name, spec_type)
    if commit_data is None:
        raise FileNotFoundError(
            f"No commit record for '{feature_name}/{spec_type}'"
        )
    if commit_data.get("ratification_status") not in (None, "pending"):
        raise ValueError("Ratification already complete")

    ratification_path = paths.ceremony_ratification(feature_name, spec_type)
    ratification = load_ratification(ratification_path)
    if ratification is None:
        ratification = Ratification(
            spec_type=spec_type,
            revision_id=commit_data.get("revision_id", ""),
            ratified=False,
            verdicts=[],
            source="threshold-met",
        )

    # Dedupe on actor_email: re-submitting by the same actor overwrites.
    ratification.verdicts = [
        v for v in ratification.verdicts if v.actor_email != ability.actor.email
    ]
    ratification.verdicts.append(
        Verdict(
            actor=ability.actor.name,
            actor_email=ability.actor.email,
            verdict=verdict,
            comment=comment,
            submitted_at=_now_iso(),
        )
    )

    threshold = commit_data.get("ratification_threshold", 1)

    if verdict == "reject":
        ratification.ratified = False
        save_ratification(ratification_path, ratification)
        commit_data["ratification_status"] = "rejected"
        _save_commit(project_root, feature_name, spec_type, commit_data)
        try:
            transition_ceremony_state(
                feature_name,
                CeremonyStatus.REJECTED,
                project_root=project_root,
            )
        except ValueError:
            # Ceremony may already be in a terminal state from another spec.
            pass
    else:
        approvals = sum(
            1 for v in ratification.verdicts if v.verdict == "approve"
        )
        if approvals >= threshold:
            ratification.ratified = True
            save_ratification(ratification_path, ratification)
            commit_data["ratification_status"] = "ratified"
            _save_commit(project_root, feature_name, spec_type, commit_data)

            drafted, _, ratified = derive_transition_sets(
                feature_name, project_root=project_root
            )
            if drafted and ratified == drafted:
                state = _load_ceremony_state(paths.ceremony_state(feature_name))
                if _current_ceremony_status(state) == CeremonyStatus.COMMITTED:
                    transition_ceremony_state(
                        feature_name,
                        CeremonyStatus.RATIFIED,
                        project_root=project_root,
                    )
        else:
            save_ratification(ratification_path, ratification)

    return get_ratification_state(project_root, feature_name, spec_type)


def _current_ceremony_status(state: CeremonyState) -> CeremonyStatus:
    rev = state.revisions[state.current_revision]
    return rev.status


# ── Per-spec progress ─────────────────────────────────────────────


def get_ceremony_progress(
    project_root: Path, feature_name: str
) -> list[SpecProgressInfo]:
    """Return per-spec progress for every drafted spec in the ceremony.

    Reads the ceremony directory once and composes the full state each
    drafted spec is in — claim (if any), commit status, ratification
    verdicts. Exposed via GraphQL so the frontend can fetch the entire
    progress picture in a single round trip rather than firing N
    parallel per-spec queries.

    The result is ordered alphabetically by spec_type for stable display.
    """
    paths = get_paths(project_root)
    ceremony_dir = paths.ceremony_dir(feature_name)
    if not ceremony_dir.is_dir():
        return []

    # Every drafted spec gets a row. We mirror derive_transition_sets's
    # derivation — a spec is drafted iff `draft-{spec_type}.json` exists.
    drafted_specs = sorted(
        f.stem.removeprefix("draft-")
        for f in ceremony_dir.glob("draft-*.json")
    )

    _, actor_email = get_current_actor()
    result: list[SpecProgressInfo] = []

    for spec_type in drafted_specs:
        # Claim
        claim_path = paths.ceremony_claim(feature_name, spec_type)
        raw_claim = load_spec_claim(claim_path)
        claim_info: SpecClaimInfo | None = None
        if raw_claim is not None:
            claim_info = SpecClaimInfo(
                spec_type=raw_claim.spec_type,
                claimant=raw_claim.claimant,
                claimant_email=raw_claim.claimant_email,
                claimed_at=raw_claim.claimed_at,
                last_activity_at=raw_claim.last_activity_at,
                released_at=raw_claim.released_at,
            )

        # Commit record
        commit_data = _load_commit(project_root, feature_name, spec_type)
        has_commit = commit_data is not None
        committer: str | None = None
        committer_email: str | None = None
        threshold = 1
        if commit_data is not None:
            committer = commit_data.get("claimant")
            committer_email = commit_data.get("claimant_email")
            threshold = commit_data.get("ratification_threshold", 1)

        # Ratification
        ratification = load_ratification(
            paths.ceremony_ratification(feature_name, spec_type)
        )
        has_ratification = ratification is not None
        ratified = ratification.ratified if ratification else False
        has_rejection = False
        approval_count = 0
        has_voted = False
        if ratification is not None:
            approval_count = sum(
                1 for v in ratification.verdicts if v.verdict == "approve"
            )
            has_rejection = any(
                v.verdict == "reject" for v in ratification.verdicts
            )
            has_voted = any(
                v.actor_email == actor_email for v in ratification.verdicts
            )

        result.append(
            SpecProgressInfo(
                spec_type=spec_type,
                claim=claim_info,
                has_commit=has_commit,
                committer=committer,
                committer_email=committer_email,
                has_ratification=has_ratification,
                ratified=ratified,
                has_rejection=has_rejection,
                approval_count=approval_count,
                has_voted=has_voted,
                ratification_threshold=threshold,
            )
        )

    return result
