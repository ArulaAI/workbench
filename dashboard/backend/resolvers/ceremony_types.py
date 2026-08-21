"""Shared types, state machine, and helpers for the Define Ceremony.

Every child RFC (context, editor, contributor, commit, bootstrap) imports
from this module.  See specs/tech/speed-define-ceremony.md for the full
specification and specs/tech/speed-define-ceremony-foundation.md for the
shared contract.
"""

from __future__ import annotations

import enum
import hashlib
import json
import logging
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import strawberry

from ..paths import get_paths

log = logging.getLogger("speed.dashboard.ceremony")

# ── Ceremony lifecycle ──────────────────────────────────────────


@strawberry.enum
class CeremonyStatus(enum.Enum):
    """Per-revision lifecycle state. Forward-only transitions."""

    DRAFTING = "drafting"
    COMMITTED = "committed"
    RATIFIED = "ratified"
    REJECTED = "rejected"
    ABANDONED = "abandoned"


@strawberry.type
class RevisionSummary:
    """One node in the revision chain."""

    revision_id: str
    parent_id: Optional[str]
    status: CeremonyStatus
    spec_content_hash: str
    context_package_hash: str
    validation_hash: str
    created_at: str
    reason: Optional[str]


@strawberry.type
class CeremonyInfo:
    """Top-level ceremony state returned by the ceremonyInfo query."""

    feature_name: str
    current_revision: RevisionSummary
    revision_count: int
    author: str
    author_email: str
    created_at: str
    is_multiplayer: bool


# ── Intent ──────────────────────────────────────────────────────


@strawberry.type
class Intent:
    """Maps to intent.json."""

    text: str
    author: str
    author_email: str
    created_at: str
    feature_name: str


# ── Context package ─────────────────────────────────────────────


@strawberry.type
class CodebaseItem:
    path: str
    description: str
    node_ids: list[str]


@strawberry.type
class LearningItem:
    text: str
    source_feature: str
    confidence: str  # "high" | "medium" | "low" | "locked"


@strawberry.type
class DefectItem:
    name: str
    severity: str  # "critical" | "major" | "minor"
    status: str  # "open" | "resolved" | "wont_fix"
    related_files: list[str]


@strawberry.type
class KnowledgeItem:
    text: str
    confidence: str  # "high" | "medium" | "low"
    source: str


@strawberry.type
class RelatedFeature:
    name: str
    state: str  # CeremonyStatus value
    overlap_files: list[str]


@strawberry.type
class AuditHistoryItem:
    feature_name: str
    finding: str
    severity: str  # "critical" | "major" | "minor" | "info"
    section: str


@strawberry.type
class ContextPackage:
    """Assembled from 7 sources by the context RFC."""

    intent: str
    feature_name: str
    scoped_area: list[str]
    codebase: list[CodebaseItem]
    learnings: list[LearningItem]
    defects: list[DefectItem]
    project_knowledge: list[KnowledgeItem]
    vision_status: str  # "available" | "missing" | "stale"
    vision_content: Optional[str]
    related_features: list[RelatedFeature]
    audit_history: list[AuditHistoryItem]
    assembled_at: str
    sources_status: strawberry.scalars.JSON
    scoping_method: str = "llm"  # "llm" | "keyword" | "full_graph"
    low_confidence: bool = False  # True when scope fell back to full graph or >40% matched
    bluf_summary: Optional[str] = None  # LLM-synthesized intelligence brief


# ── Validation ──────────────────────────────────────────────────


@strawberry.type
class ValidationIssue:
    id: str
    dimension: str
    severity: str  # "error" | "warning" | "info"
    message: str
    section: Optional[str]
    line: Optional[int]
    cross_ref_spec: Optional[str]
    cross_ref_section: Optional[str]


@strawberry.type
class ValidationDimension:
    name: str  # "template" | "structure" | "cross_spec" | "codebase" | "sizing" | "vision"
    status: str  # "pass" | "warn" | "fail" | "pending" | "stale"
    issues: list[ValidationIssue]
    checked_at: Optional[str]
    tier: int  # 1 or 2


@strawberry.type
class ValidationState:
    dimensions: list[ValidationDimension]
    pass_count: int
    warn_count: int
    fail_count: int


# ── Spec draft ──────────────────────────────────────────────────


@strawberry.type
class SpecDraft:
    feature_name: str
    spec_type: str  # "prd" | "rfc" | "design"
    content: str
    file_path: str
    template_name: str
    generated_at: Optional[str]
    child_specs: list["SpecDraft"]


@strawberry.type
class GenerateDraftResult:
    """Returned by generateDraft mutation. Draft may be null while generating."""

    feature_name: str
    spec_type: str
    status: str  # "generating" | "complete" | "error"
    draft: Optional[SpecDraft] = None
    error: Optional[str] = None


@strawberry.input
class ChildRfcInput:
    """One child RFC in a decomposition plan."""

    name: str
    user_story_ids: list[str]
    depends_on: Optional[list[str]] = None


@strawberry.input
class DecompositionInput:
    """Accepted decomposition plan for child RFC generation."""

    children: list[ChildRfcInput]


@strawberry.type
class GenerateChildRfcsResult:
    """Returned by generateChildRfcs mutation."""

    feature_name: str
    status: str  # "generating" | "complete" | "error"
    drafts: list[SpecDraft]
    error: Optional[str] = None


# ── Suggestions ─────────────────────────────────────────────────


@strawberry.type
class SuggestionResolution:
    action: str  # "accept" | "dismiss"
    resolved_by: str
    resolved_by_email: str
    resolved_at: str
    reason: Optional[str]


@strawberry.type
class SuggestionReply:
    id: str
    author: str
    author_email: str
    text: str
    created_at: str


@strawberry.type
class Suggestion:
    id: str
    author: str
    author_email: str
    revision_id: str
    section_id: str
    section_title: str
    section_content_hash: str
    text: str
    status: str  # "unresolved" | "accepted" | "dismissed"
    outdated: bool
    created_at: str
    updated_at: Optional[str]
    resolution: Optional[SuggestionResolution]
    thread: list[SuggestionReply]
    spec_type: str = "prd"  # "prd" | "design" | "rfc" | "rfc-{slug}"


@strawberry.type
class DismissedSummary:
    count: int
    reasons: list[str]


@strawberry.type
class SuggestionHistory:
    received: int
    accepted: int
    dismissed: DismissedSummary


# ── Commit & ratification ──────────────────────────────────────


@strawberry.type
class CommitRecord:
    feature_name: str
    spec_type: str  # "prd" | "design" | "rfc" | "rfc-{slug}"
    revision_id: str
    claimant: str  # display name, snapshot at commit time
    claimant_email: str  # canonical identity, snapshot at commit time
    committed_at: str
    validation_state_ref: str
    context_package_ref: str  # context is still feature-level
    suggestion_history: SuggestionHistory  # filtered to this spec_type
    spec_path: str  # single file path; was spec_paths: list[str]
    decomposition_ref: Optional[str]  # None for non-RFC slots
    is_multiplayer: bool
    ratification_threshold: int
    ratification_status: str  # "pending" | "ratified" | "rejected"


@strawberry.type
class VerdictEntry:
    id: str
    revision_id: str
    actor: str
    actor_email: str
    verdict: str  # "approve" | "reject"
    comment: Optional[str]
    timestamp: str


@strawberry.type
class RatificationState:
    feature_name: str
    revision_id: str
    status: str  # "pending" | "ratified" | "rejected"
    ratification_count: int
    threshold: int
    verdicts: list[VerdictEntry]
    is_author: bool
    has_voted: bool


@strawberry.type
class SpecClaimInfo:
    """GraphQL projection of SpecClaim (the on-disk dataclass).

    Exposed by the `ceremonyClaims(featureName)` query and returned by
    the `claimSpec` / `releaseSpec` mutations. The tab bar and Progress
    Overview compose their display state on the client by combining
    this with per-spec filesystem reads (commit, ratification) — the
    RFC deliberately keeps this shape narrow.
    """

    spec_type: str
    claimant: str
    claimant_email: str
    claimed_at: str
    last_activity_at: str
    released_at: Optional[str]


@strawberry.type
class CurrentActor:
    """GraphQL projection of the current viewer's identity.

    Resolved server-side via `get_current_actor()` — same chain as every
    ownership write. Exposed so the frontend can reliably decide
    "is this claim mine" without a heuristic.
    """

    name: str
    email: str


@strawberry.type
class SpecProgressInfo:
    """Per-spec progress snapshot.

    Returned as a list by `ceremonyProgress(featureName)` so the
    frontend can compose ClaimState variants + ProgressRow status pills
    in a single round trip instead of firing N parallel queries.

    Fields:
    - spec_type: the drafted spec slot ("prd"|"design"|"rfc"|"rfc-{slug}")
    - claim: the live claim (or None if unclaimed)
    - has_commit: True iff commit-{spec_type}.json exists
    - committer_email: None if no commit; set to the commit record's
      claimant_email otherwise — this drives the committed ClaimState
      variant and the RatifyControl "you committed this" disable
    - has_ratification: True iff ratification-{spec_type}.json exists
    - ratified: True iff the ratification file reports ratified
    - has_rejection: True iff any verdict is "reject"
    - approval_count: count of "approve" verdicts
    - has_voted: True iff the current actor has voted on this spec
    - ratification_threshold: from the commit record, or 1 as default
    """

    spec_type: str
    claim: Optional["SpecClaimInfo"]
    has_commit: bool
    committer: Optional[str]
    committer_email: Optional[str]
    has_ratification: bool
    ratified: bool
    has_rejection: bool
    approval_count: int
    has_voted: bool
    ratification_threshold: int


# ═══════════════════════════════════════════════════════════════
# On-disk dataclasses (not Strawberry — these map to ceremony.json)
# ═══════════════════════════════════════════════════════════════


@dataclass
class Revision:
    """Immutable once it reaches a terminal state."""

    revision_id: str
    parent_id: str | None
    status: CeremonyStatus
    spec_content_hash: str
    context_package_hash: str
    validation_hash: str
    created_at: str
    reason: str | None


@dataclass
class ReflogEntry:
    from_revision: str | None
    to_revision: str
    at: str
    actor: str
    actor_email: str
    reason: str


@dataclass
class CeremonyState:
    """On-disk schema for ceremony.json. One file per feature."""

    feature_name: str
    author: str
    author_email: str
    created_at: str
    is_multiplayer: bool
    current_revision: str
    revision_count: int
    revisions: dict[str, Revision] = field(default_factory=dict)
    reflog: list[ReflogEntry] = field(default_factory=list)


# ── Per-spec ownership (claim, verdict, ratification) ──────────


@dataclass
class SpecClaim:
    """On-disk schema for claim-{spec_type}.json.

    One file per claimed spec. A spec is unclaimed if the file does not
    exist, or if the file exists but `released_at` is populated.
    """

    spec_type: str              # "prd" | "design" | "rfc" | "rfc-{slug}"
    claimant: str               # display name from get_current_actor()
    claimant_email: str         # canonical identity
    claimed_at: str             # ISO 8601 UTC
    last_activity_at: str       # refreshed on any claimant mutation
    released_at: str | None = None  # None while active


@dataclass
class Verdict:
    """Single ratification verdict entry. Stored inside Ratification.verdicts."""

    actor: str                  # display name from get_current_actor()
    actor_email: str            # canonical identity, used for dedupe and has_voted
    verdict: str                # "approve" | "reject"
    comment: str | None         # required when verdict == "reject", optional otherwise
    submitted_at: str           # ISO 8601 UTC


@dataclass
class Ratification:
    """On-disk schema for ratification-{spec_type}.json.

    The `ratified` field is the ground truth for `ratified_specs` derivation.
    A spec is considered ratified when its file exists AND `ratified` is True.
    """

    spec_type: str                         # matches filename suffix
    revision_id: str                       # ceremony revision at commit time
    ratified: bool                         # gate flag
    verdicts: list[Verdict] = field(default_factory=list)
    source: str = "threshold-met"          # "threshold-met" | "no-eligible-ratifier"


def _spec_claim_to_dict(claim: SpecClaim) -> dict[str, Any]:
    return {
        "spec_type": claim.spec_type,
        "claimant": claim.claimant,
        "claimant_email": claim.claimant_email,
        "claimed_at": claim.claimed_at,
        "last_activity_at": claim.last_activity_at,
        "released_at": claim.released_at,
    }


def _parse_spec_claim(data: dict[str, Any]) -> SpecClaim:
    for fld in ("spec_type", "claimant", "claimant_email", "claimed_at", "last_activity_at"):
        if fld not in data:
            raise ValueError(f"Malformed SpecClaim: missing {fld}")
    return SpecClaim(
        spec_type=data["spec_type"],
        claimant=data["claimant"],
        claimant_email=data["claimant_email"],
        claimed_at=data["claimed_at"],
        last_activity_at=data["last_activity_at"],
        released_at=data.get("released_at"),
    )


def _verdict_to_dict(verdict: Verdict) -> dict[str, Any]:
    return {
        "actor": verdict.actor,
        "actor_email": verdict.actor_email,
        "verdict": verdict.verdict,
        "comment": verdict.comment,
        "submitted_at": verdict.submitted_at,
    }


def _parse_verdict(data: dict[str, Any]) -> Verdict:
    for fld in ("actor", "actor_email", "verdict", "submitted_at"):
        if fld not in data:
            raise ValueError(f"Malformed Verdict: missing {fld}")
    if data["verdict"] not in ("approve", "reject"):
        raise ValueError(f"Invalid verdict value: {data['verdict']}")
    return Verdict(
        actor=data["actor"],
        actor_email=data["actor_email"],
        verdict=data["verdict"],
        comment=data.get("comment"),
        submitted_at=data["submitted_at"],
    )


def _ratification_to_dict(ratification: Ratification) -> dict[str, Any]:
    return {
        "spec_type": ratification.spec_type,
        "revision_id": ratification.revision_id,
        "ratified": ratification.ratified,
        "verdicts": [_verdict_to_dict(v) for v in ratification.verdicts],
        "source": ratification.source,
    }


def _parse_ratification(data: dict[str, Any]) -> Ratification:
    for fld in ("spec_type", "revision_id", "ratified", "source"):
        if fld not in data:
            raise ValueError(f"Malformed Ratification: missing {fld}")
    if data["source"] not in ("threshold-met", "no-eligible-ratifier"):
        raise ValueError(f"Invalid ratification source: {data['source']}")
    verdicts = [_parse_verdict(v) for v in data.get("verdicts", [])]
    return Ratification(
        spec_type=data["spec_type"],
        revision_id=data["revision_id"],
        ratified=bool(data["ratified"]),
        verdicts=verdicts,
        source=data["source"],
    )


def load_spec_claim(path: Path) -> SpecClaim | None:
    """Read a claim-{spec_type}.json file. Returns None if missing or malformed."""
    data = _read_json(path)
    if data is None:
        return None
    try:
        return _parse_spec_claim(data)
    except ValueError:
        return None


def save_spec_claim(path: Path, claim: SpecClaim) -> None:
    """Write a claim-{spec_type}.json file."""
    _write_json(path, _spec_claim_to_dict(claim))


def load_ratification(path: Path) -> Ratification | None:
    """Read a ratification-{spec_type}.json file. Returns None if missing or malformed."""
    data = _read_json(path)
    if data is None:
        return None
    try:
        return _parse_ratification(data)
    except ValueError:
        return None


def save_ratification(path: Path, ratification: Ratification) -> None:
    """Write a ratification-{spec_type}.json file."""
    _write_json(path, _ratification_to_dict(ratification))


# ═══════════════════════════════════════════════════════════════
# State machine
# ═══════════════════════════════════════════════════════════════

VALID_TRANSITIONS: dict[CeremonyStatus, list[CeremonyStatus]] = {
    CeremonyStatus.DRAFTING: [CeremonyStatus.COMMITTED, CeremonyStatus.ABANDONED],
    CeremonyStatus.COMMITTED: [CeremonyStatus.RATIFIED, CeremonyStatus.REJECTED],
    CeremonyStatus.RATIFIED: [],
    CeremonyStatus.REJECTED: [],
    CeremonyStatus.ABANDONED: [],
}

_FEATURE_NAME_RE_STR = r"^[a-z0-9][a-z0-9-]*$"

# ── File helpers ────────────────────────────────────────────────


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


# ── Serialization ───────────────────────────────────────────────


def _revision_to_dict(rev: Revision) -> dict[str, Any]:
    return {
        "revision_id": rev.revision_id,
        "parent_id": rev.parent_id,
        "status": rev.status.value,
        "spec_content_hash": rev.spec_content_hash,
        "context_package_hash": rev.context_package_hash,
        "validation_hash": rev.validation_hash,
        "created_at": rev.created_at,
        "reason": rev.reason,
    }


def _reflog_entry_to_dict(entry: ReflogEntry) -> dict[str, Any]:
    return {
        "from_revision": entry.from_revision,
        "to_revision": entry.to_revision,
        "at": entry.at,
        "actor": entry.actor,
        "actor_email": entry.actor_email,
        "reason": entry.reason,
    }


def _ceremony_state_to_dict(state: CeremonyState) -> dict[str, Any]:
    return {
        "feature_name": state.feature_name,
        "author": state.author,
        "author_email": state.author_email,
        "created_at": state.created_at,
        "is_multiplayer": state.is_multiplayer,
        "current_revision": state.current_revision,
        "revision_count": state.revision_count,
        "revisions": {
            k: _revision_to_dict(v) for k, v in state.revisions.items()
        },
        "reflog": [_reflog_entry_to_dict(e) for e in state.reflog],
    }


def _parse_revision(rid: str, data: dict[str, Any]) -> Revision:
    try:
        status = CeremonyStatus(data["status"])
    except (KeyError, ValueError) as exc:
        raise ValueError(
            f"Invalid ceremony status '{data.get('status')}' in revision '{rid}'"
        ) from exc

    for fld in (
        "revision_id",
        "spec_content_hash",
        "context_package_hash",
        "validation_hash",
        "created_at",
    ):
        if fld not in data:
            raise ValueError(f"Malformed revision entry '{rid}': missing {fld}")

    return Revision(
        revision_id=data["revision_id"],
        parent_id=data.get("parent_id"),
        status=status,
        spec_content_hash=data["spec_content_hash"],
        context_package_hash=data["context_package_hash"],
        validation_hash=data["validation_hash"],
        created_at=data["created_at"],
        reason=data.get("reason"),
    )


def _parse_reflog_entry(idx: int, data: dict[str, Any]) -> ReflogEntry:
    for fld in ("to_revision", "at", "actor", "actor_email", "reason"):
        if fld not in data:
            raise ValueError(f"Malformed reflog entry at index {idx}")
    return ReflogEntry(
        from_revision=data.get("from_revision"),
        to_revision=data["to_revision"],
        at=data["at"],
        actor=data["actor"],
        actor_email=data["actor_email"],
        reason=data["reason"],
    )


def _load_ceremony_state(path: Path) -> CeremonyState:
    """Parse ceremony.json into CeremonyState. Raises on any schema issue."""
    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        raise ValueError(f"ceremony.json is empty: {path}")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"ceremony.json for '{path.parent.name}' is malformed: {exc}"
        ) from exc

    for fld in (
        "feature_name",
        "author",
        "author_email",
        "created_at",
        "is_multiplayer",
        "current_revision",
        "revision_count",
        "revisions",
        "reflog",
    ):
        if fld not in data:
            raise ValueError(
                f"ceremony.json for '{data.get('feature_name', path.parent.name)}' "
                f"is missing required field: {fld}"
            )

    import re

    fn = data["feature_name"]
    if not fn or len(fn) > 50 or not re.match(_FEATURE_NAME_RE_STR, fn):
        raise ValueError(
            "Feature name must be lowercase alphanumeric with hyphens, max 50 chars"
        )

    ae = data["author_email"]
    if not ae or "@" not in ae:
        raise ValueError("Invalid author email format")

    revisions: dict[str, Revision] = {}
    for rid, rdata in data["revisions"].items():
        revisions[rid] = _parse_revision(rid, rdata)

    cur = data["current_revision"]
    if cur not in revisions:
        raise ValueError(f"current_revision '{cur}' not found in revisions map")

    reflog_entries: list[ReflogEntry] = []
    for idx, entry in enumerate(data["reflog"]):
        reflog_entries.append(_parse_reflog_entry(idx, entry))

    return CeremonyState(
        feature_name=fn,
        author=data["author"],
        author_email=ae,
        created_at=data["created_at"],
        is_multiplayer=data["is_multiplayer"],
        current_revision=cur,
        revision_count=data["revision_count"],
        revisions=revisions,
        reflog=reflog_entries,
    )


def _save_ceremony_state(path: Path, state: CeremonyState) -> None:
    _write_json(path, _ceremony_state_to_dict(state))


# ── State transitions ───────────────────────────────────────────


def transition_ceremony_state(
    feature_name: str,
    target: CeremonyStatus,
    *,
    project_root: Path | None = None,
) -> CeremonyStatus:
    """Move the current revision to *target*. Returns the new status.

    Raises ValueError on invalid transition.
    Raises FileNotFoundError if ceremony.json doesn't exist.
    """
    root = project_root or Path(os.environ.get("SPEED_PROJECT_ROOT", os.getcwd()))
    paths = get_paths(root)
    state_path = paths.ceremony_state(feature_name)

    if not state_path.exists():
        raise FileNotFoundError(f"No ceremony.json for feature '{feature_name}'")

    state = _load_ceremony_state(state_path)
    rev = state.revisions[state.current_revision]
    current = rev.status

    if target not in VALID_TRANSITIONS.get(current, []):
        raise ValueError(
            f"Cannot transition from {current.value} to {target.value}"
        )

    rev.status = target
    _save_ceremony_state(state_path, state)
    return target


def create_revision(
    feature_name: str,
    reason: str,
    *,
    project_root: Path | None = None,
) -> Revision:
    """Create a new revision at DRAFTING and advance the ceremony ref.

    Raises PermissionError if caller is not the ceremony author.
    Raises ValueError if current revision is not in a terminal state.
    """
    root = project_root or Path(os.environ.get("SPEED_PROJECT_ROOT", os.getcwd()))
    paths = get_paths(root)
    state_path = paths.ceremony_state(feature_name)

    if not state_path.exists():
        raise FileNotFoundError(f"No ceremony.json for feature '{feature_name}'")

    state = _load_ceremony_state(state_path)
    name, email = get_current_actor()
    assert_ceremony_author(state, email)

    cur_rev = state.revisions[state.current_revision]
    terminal = {CeremonyStatus.RATIFIED, CeremonyStatus.REJECTED, CeremonyStatus.ABANDONED}
    if cur_rev.status not in terminal:
        raise ValueError(
            f"Cannot create new revision: current revision is still in {cur_rev.status.value}"
        )

    now = datetime.now(timezone.utc).isoformat()

    # Read current hashes (or zeros if artifacts don't exist yet)
    spec_hash = _file_hash(paths.ceremony_dir(feature_name))
    ctx_hash = _file_hash(paths.ceremony_context_package(feature_name))
    val_hash = _file_hash(paths.ceremony_validation_snapshot(feature_name))

    content = spec_hash + ctx_hash + val_hash + (cur_rev.revision_id or "")
    revision_id = hashlib.sha256(content.encode()).hexdigest()[:8]

    new_rev = Revision(
        revision_id=revision_id,
        parent_id=cur_rev.revision_id,
        status=CeremonyStatus.DRAFTING,
        spec_content_hash=spec_hash,
        context_package_hash=ctx_hash,
        validation_hash=val_hash,
        created_at=now,
        reason=reason,
    )

    state.revisions[revision_id] = new_rev
    state.reflog.append(
        ReflogEntry(
            from_revision=cur_rev.revision_id,
            to_revision=revision_id,
            at=now,
            actor=name,
            actor_email=email,
            reason=reason,
        )
    )
    state.current_revision = revision_id
    state.revision_count += 1

    # Mark suggestions on changed sections as outdated
    _mark_outdated_suggestions(paths, feature_name, cur_rev, new_rev)

    _save_ceremony_state(state_path, state)
    return new_rev


def _file_hash(path: Path) -> str:
    """SHA-256 hex digest of a file, or zeros if missing."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return "0" * 64


def _mark_outdated_suggestions(
    paths: Any,
    feature_name: str,
    _old_rev: Revision,
    _new_rev: Revision,
) -> None:
    """Compare section hashes and mark changed suggestions as outdated.

    The full implementation lives in the contributor RFC. This stub reads
    suggestions.json and writes it back with outdated flags updated based
    on spec content hash changes between revisions.
    """
    sug_path = paths.ceremony_suggestions(feature_name)
    if not sug_path.exists():
        return

    data = _read_json(sug_path)
    if not data or "suggestions" not in data:
        return

    # If the overall spec content hash changed, all suggestions are outdated.
    # Section-level comparison is the contributor RFC's responsibility; here
    # we do a coarse-grained check.
    if _old_rev.spec_content_hash != _new_rev.spec_content_hash:
        for sug in data["suggestions"]:
            if sug.get("status") == "unresolved":
                sug["outdated"] = True
        _write_json(sug_path, data)


# ── Ownership enforcement ───────────────────────────────────────


def assert_ceremony_author(
    ceremony: CeremonyState, actor_email: str
) -> None:
    """Raise PermissionError if actor_email != ceremony.author_email."""
    if actor_email != ceremony.author_email:
        raise PermissionError(
            f"Only the ceremony author ({ceremony.author}) can perform this action"
        )


def assert_not_ceremony_author(
    ceremony: CeremonyState, actor_email: str
) -> None:
    """Raise PermissionError if actor_email == ceremony.author_email."""
    if actor_email == ceremony.author_email:
        raise PermissionError("Cannot perform this action on your own ceremony")


# ── Identity ────────────────────────────────────────────────────

_actor_cache: tuple[str, str] | None = None


def _reset_actor_cache() -> None:
    """Clear the cached actor. Used by tests."""
    global _actor_cache
    _actor_cache = None


def get_current_actor() -> tuple[str, str]:
    """Returns (name, email). Never raises.

    Resolution chain mirrors lib/actor.sh:
      Name:  $SPEED_ACTOR  -> git config user.name  -> whoami
      Email: $SPEED_ACTOR_EMAIL -> git config user.email -> {name}@local
    """
    global _actor_cache
    if _actor_cache is not None:
        return _actor_cache

    name = os.environ.get("SPEED_ACTOR", "")
    if not name:
        try:
            name = subprocess.check_output(
                ["git", "config", "user.name"],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass
    if not name:
        try:
            name = subprocess.check_output(
                ["whoami"], stderr=subprocess.DEVNULL, text=True
            ).strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            name = "unknown"

    email = os.environ.get("SPEED_ACTOR_EMAIL", "")
    if not email:
        try:
            email = subprocess.check_output(
                ["git", "config", "user.email"],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass
    if not email:
        email = f"{name}@local"

    _actor_cache = (name, email)
    return _actor_cache


# ── Query resolver ──────────────────────────────────────────────


def get_ceremony_info(
    project_root: Path, feature_name: str
) -> CeremonyInfo | None:
    """Read ceremony.json and return CeremonyInfo.

    Returns None if ceremony.json doesn't exist.
    Raises on malformed data.
    """
    if not feature_name:
        raise ValueError("featureName must not be empty")

    paths = get_paths(project_root)
    state_path = paths.ceremony_state(feature_name)

    if not state_path.exists():
        return None

    state = _load_ceremony_state(state_path)
    rev = state.revisions[state.current_revision]

    return CeremonyInfo(
        feature_name=state.feature_name,
        current_revision=RevisionSummary(
            revision_id=rev.revision_id,
            parent_id=rev.parent_id,
            status=rev.status,
            spec_content_hash=rev.spec_content_hash,
            context_package_hash=rev.context_package_hash,
            validation_hash=rev.validation_hash,
            created_at=rev.created_at,
            reason=rev.reason,
        ),
        revision_count=state.revision_count,
        author=state.author,
        author_email=state.author_email,
        created_at=state.created_at,
        is_multiplayer=state.is_multiplayer,
    )
