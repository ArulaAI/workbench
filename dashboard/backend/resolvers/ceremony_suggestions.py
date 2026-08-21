"""GraphQL resolver for contributor suggestions.

Handles CRUD on suggestions, resolution (accept/dismiss), and reply threads.
Suggestions are persisted per-feature in suggestions.json.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..paths import get_paths
from .ceremony_authz import CeremonyAbility
from .ceremony_types import (
    DismissedSummary,
    Suggestion,
    SuggestionHistory,
    SuggestionReply,
    SuggestionResolution,
    _load_ceremony_state,
    _read_json,
    _write_json,
    get_current_actor,
)

log = logging.getLogger("speed.dashboard.ceremony.suggestions")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_suggestions(project_root: Path, feature_name: str) -> list[dict]:
    paths = get_paths(project_root)
    data = _read_json(paths.ceremony_suggestions(feature_name))
    if data is None:
        return []
    return data if isinstance(data, list) else data.get("suggestions", [])


def _save_suggestions(
    project_root: Path, feature_name: str, suggestions: list[dict]
) -> None:
    paths = get_paths(project_root)
    _write_json(paths.ceremony_suggestions(feature_name), suggestions)


def _dict_to_suggestion(d: dict) -> Suggestion:
    resolution = None
    if d.get("resolution"):
        r = d["resolution"]
        resolution = SuggestionResolution(
            action=r["action"],
            resolved_by=r["resolved_by"],
            resolved_by_email=r["resolved_by_email"],
            resolved_at=r["resolved_at"],
            reason=r.get("reason"),
        )
    thread = [
        SuggestionReply(
            id=rep["id"],
            author=rep["author"],
            author_email=rep["author_email"],
            text=rep["text"],
            created_at=rep["created_at"],
        )
        for rep in d.get("thread", [])
    ]
    return Suggestion(
        id=d["id"],
        author=d["author"],
        author_email=d["author_email"],
        revision_id=d.get("revision_id", ""),
        section_id=d["section_id"],
        section_title=d["section_title"],
        section_content_hash=d.get("section_content_hash", ""),
        text=d["text"],
        status=d["status"],
        outdated=d.get("outdated", False),
        created_at=d["created_at"],
        updated_at=d.get("updated_at"),
        resolution=resolution,
        thread=thread,
        spec_type=d.get("spec_type", "prd"),
    )


def _suggestion_to_dict(s: Suggestion) -> dict:
    d: dict[str, Any] = {
        "id": s.id,
        "author": s.author,
        "author_email": s.author_email,
        "revision_id": s.revision_id,
        "section_id": s.section_id,
        "section_title": s.section_title,
        "section_content_hash": s.section_content_hash,
        "text": s.text,
        "status": s.status,
        "outdated": s.outdated,
        "created_at": s.created_at,
        "updated_at": s.updated_at,
        "spec_type": s.spec_type,
        "resolution": None,
        "thread": [
            {
                "id": r.id,
                "author": r.author,
                "author_email": r.author_email,
                "text": r.text,
                "created_at": r.created_at,
            }
            for r in s.thread
        ],
    }
    if s.resolution:
        d["resolution"] = {
            "action": s.resolution.action,
            "resolved_by": s.resolution.resolved_by,
            "resolved_by_email": s.resolution.resolved_by_email,
            "resolved_at": s.resolution.resolved_at,
            "reason": s.resolution.reason,
        }
    return d


# ── Queries ───────────────────────────────────────────────────────


def get_suggestions(
    project_root: Path, feature_name: str
) -> list[Suggestion]:
    raw = _load_suggestions(project_root, feature_name)
    return [_dict_to_suggestion(d) for d in raw]


def get_suggestion_history(
    project_root: Path,
    feature_name: str,
    *,
    spec_type: str | None = None,
) -> SuggestionHistory:
    """Return suggestion history, optionally filtered to one spec_type.

    When `spec_type` is provided (typically from `commit_spec`), the
    returned counts cover only suggestions on that spec. When omitted,
    the history aggregates across every spec in the ceremony.
    """
    raw = _load_suggestions(project_root, feature_name)
    if spec_type is not None:
        raw = [d for d in raw if d.get("spec_type", "prd") == spec_type]
    accepted = sum(1 for d in raw if d["status"] == "accepted")
    dismissed_items = [d for d in raw if d["status"] == "dismissed"]
    reasons = [
        d["resolution"]["reason"]
        for d in dismissed_items
        if d.get("resolution") and d["resolution"].get("reason")
    ]
    return SuggestionHistory(
        received=len(raw),
        accepted=accepted,
        dismissed=DismissedSummary(count=len(dismissed_items), reasons=reasons),
    )


# ── Mutations ─────────────────────────────────────────────────────


def create_suggestion(
    project_root: Path,
    feature_name: str,
    spec_type: str,
    section_id: str,
    section_title: str,
    text: str,
) -> Suggestion:
    """Create a suggestion on a spec.

    Authorization: the caller must NOT be the active claimant of
    `spec_type` (you cannot suggest on your own spec).
    """
    ability = CeremonyAbility.for_request(
        feature_name, spec_type, project_root=project_root
    )
    ability.authorize("suggest", spec_type)

    name, email = get_current_actor()
    suggestion = Suggestion(
        id=str(uuid.uuid4()),
        author=name,
        author_email=email,
        revision_id="",
        section_id=section_id,
        section_title=section_title,
        section_content_hash="",
        text=text,
        status="unresolved",
        outdated=False,
        created_at=_now_iso(),
        updated_at=None,
        resolution=None,
        thread=[],
        spec_type=spec_type,
    )
    raw = _load_suggestions(project_root, feature_name)
    raw.append(_suggestion_to_dict(suggestion))
    _save_suggestions(project_root, feature_name, raw)
    return suggestion


def edit_suggestion(
    project_root: Path,
    feature_name: str,
    suggestion_id: str,
    text: str,
) -> Suggestion:
    _, email = get_current_actor()
    raw = _load_suggestions(project_root, feature_name)
    for d in raw:
        if d["id"] == suggestion_id:
            if d["author_email"] != email:
                raise PermissionError("Only the suggestion author can edit")
            if d["status"] != "unresolved":
                raise ValueError("Cannot edit a resolved suggestion")
            d["text"] = text
            d["updated_at"] = _now_iso()
            _save_suggestions(project_root, feature_name, raw)
            return _dict_to_suggestion(d)
    raise FileNotFoundError(f"Suggestion {suggestion_id} not found")


def delete_suggestion(
    project_root: Path,
    feature_name: str,
    suggestion_id: str,
) -> bool:
    _, email = get_current_actor()
    raw = _load_suggestions(project_root, feature_name)
    for i, d in enumerate(raw):
        if d["id"] == suggestion_id:
            if d["author_email"] != email:
                raise PermissionError("Only the suggestion author can delete")
            raw.pop(i)
            _save_suggestions(project_root, feature_name, raw)
            return True
    raise FileNotFoundError(f"Suggestion {suggestion_id} not found")


def resolve_suggestion(
    project_root: Path,
    feature_name: str,
    suggestion_id: str,
    action: str,
    reason: str | None = None,
) -> Suggestion:
    """Resolve a suggestion as accept or dismiss.

    Authorization: the caller must be the active claimant of the
    suggestion's `spec_type`. The suggestion carries the spec_type on
    its record so routing is unambiguous even across child RFCs.
    """
    if action not in ("accept", "dismiss"):
        raise ValueError(f"Invalid action: {action}")
    if action == "dismiss" and not reason:
        raise ValueError("Dismiss requires a reason")

    raw = _load_suggestions(project_root, feature_name)
    target: dict | None = None
    for d in raw:
        if d["id"] == suggestion_id:
            target = d
            break
    if target is None:
        raise FileNotFoundError(f"Suggestion {suggestion_id} not found")
    if target["status"] != "unresolved":
        raise ValueError("Suggestion already resolved")

    spec_type = target.get("spec_type", "prd")
    ability = CeremonyAbility.for_request(
        feature_name, spec_type, project_root=project_root
    )
    ability.authorize("resolve", spec_type)

    target["status"] = "accepted" if action == "accept" else "dismissed"
    target["resolution"] = {
        "action": action,
        "resolved_by": ability.actor.name,
        "resolved_by_email": ability.actor.email,
        "resolved_at": _now_iso(),
        "reason": reason,
    }
    _save_suggestions(project_root, feature_name, raw)
    return _dict_to_suggestion(target)


def reply_suggestion(
    project_root: Path,
    feature_name: str,
    suggestion_id: str,
    text: str,
) -> SuggestionReply:
    name, email = get_current_actor()
    reply = SuggestionReply(
        id=str(uuid.uuid4()),
        author=name,
        author_email=email,
        text=text,
        created_at=_now_iso(),
    )
    raw = _load_suggestions(project_root, feature_name)
    for d in raw:
        if d["id"] == suggestion_id:
            d.setdefault("thread", []).append({
                "id": reply.id,
                "author": reply.author,
                "author_email": reply.author_email,
                "text": reply.text,
                "created_at": reply.created_at,
            })
            _save_suggestions(project_root, feature_name, raw)
            return reply
    raise FileNotFoundError(f"Suggestion {suggestion_id} not found")
