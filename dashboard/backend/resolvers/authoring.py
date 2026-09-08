"""Guided authoring resolvers.

Every field here is a projection of the helper's JSON result. The resolver
adds no question, option, gate, or default of its own; it selects flags, reads
the generated artifact from disk, and reports what the helper returned.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Optional

from .. import authoring_helper
from .. import authoring_planner
from ..paths import get_paths
from .ceremony_authz import CeremonyAbility
from .ceremony_claims import claim_spec
from .authoring_types import (
    AuthoringAction,
    AuthoringIntake,
    AuthoringProgress,
    AuthoringSession,
    AuthoringSessionList,
    AuthoringSessionSummary,
)

ACTION_FLAG = {
    AuthoringAction.ACCEPT: "--accept-suggestion",
    AuthoringAction.EDIT: "--edit-suggestion",
    AuthoringAction.REJECT: "--reject-suggestion",
    AuthoringAction.DEFER: "--defer",
}

_REPLAN_LOCKS: dict[tuple[str, str, str], threading.Lock] = {}
_REPLAN_LOCKS_GUARD = threading.Lock()


def _claim_for_start(project_root: Path, feature_name: str, artifact_type: str) -> None:
    """Make opening an authoring branch an explicit ownership action."""
    claim_spec(project_root, feature_name, artifact_type)


def _authorize_authoring_edit(
    project_root: Path, feature_name: str, artifact_type: str
) -> None:
    """Require the active artifact claim before changing guided state."""
    claim_path = get_paths(project_root).ceremony_claim(feature_name, artifact_type)
    if not claim_path.exists():
        # Compatibility for pre-ownership guided checkpoints: the first actor
        # to resume establishes the missing claim explicitly at this write.
        claim_spec(project_root, feature_name, artifact_type)
        return
    ability = CeremonyAbility.for_request(
        feature_name, artifact_type, project_root=project_root
    )
    ability.authorize("edit", artifact_type)
    # Refresh last_activity only after authorization succeeds. A stale or
    # foreign claim therefore cannot be taken over as a side effect of editing.
    claim_spec(project_root, feature_name, artifact_type)


def _replan_lock(
    project_root: Path, feature_name: str, artifact_type: str
) -> threading.Lock:
    """Coalesce automatic planning for one artifact inside this server."""
    key = (str(project_root.resolve()), feature_name, artifact_type)
    with _REPLAN_LOCKS_GUARD:
        return _REPLAN_LOCKS.setdefault(key, threading.Lock())


def _read_artifact(project_root: Path, artifact_path: Optional[str]) -> Optional[str]:
    if not artifact_path:
        return None
    path = Path(project_root) / artifact_path
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _session(project_root: Path, payload: dict[str, Any]) -> AuthoringSession:
    progress = payload.get("progress") or {}
    artifact_path = payload.get("artifact_path")
    artifact_content = _read_artifact(project_root, artifact_path)
    versions = payload.get("versions") or []
    if not versions and artifact_content and isinstance(payload.get("revision"), int):
        versions = [{
            "revision": payload["revision"],
            "content": artifact_content,
            "created_at": None,
            "source": "current",
        }]
    return AuthoringSession(
        status=str(payload.get("status") or "error"),
        feature_name=payload.get("feature_name"),
        feature_title=payload.get("feature_title"),
        artifact_type=payload.get("artifact_type"),
        question_bank_version=payload.get("question_bank_version"),
        revision=payload.get("revision"),
        message=str(payload.get("message") or ""),
        progress=AuthoringProgress(
            confirmed=int(progress.get("confirmed") or 0),
            total=int(progress.get("total") or 0),
            deferred=list(progress.get("deferred") or []),
        ),
        draft_available=bool(payload.get("draft_available")),
        artifact_path=artifact_path,
        artifact_content=artifact_content,
        dashboard_url=payload.get("dashboard_url"),
        authoring_url=payload.get("authoring_url"),
        helper_path=payload.get("helper_path"),
        interpreter=payload.get("interpreter"),
        current_question=payload.get("current_question"),
        coverage=payload.get("coverage"),
        sections=payload.get("sections"),
        intake=payload.get("intake"),
        interview=payload.get("interview"),
        self_review=payload.get("self_review"),
        resume_step=payload.get("resume_step"),
        upstream=payload.get("upstream"),
        implementation=payload.get("implementation"),
        planning=payload.get("planning"),
        review_comments=payload.get("review_comments"),
        versions=versions,
        published_revision=payload.get("published_revision"),
        publish_history=payload.get("publish_history"),
    )


def _replan_payload(
    project_root: Path,
    feature_name: str,
    artifact_type: str,
    payload: dict[str, Any],
    *,
    allow_questions: bool = True,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Analyze the current evidence with the configured model and persist its plan."""
    if artifact_type not in {"prd", "design", "rfc"} or payload.get("status") in {
        "error", "helper_unavailable", "revision_conflict", "not_started",
        "drafted", "drafted_with_open_questions", "published",
    }:
        return payload
    revision = payload.get("revision")
    if not isinstance(revision, int):
        return payload
    if conn is None:
        plan = authoring_planner.plan_authoring(project_root, payload)
    else:
        plan = authoring_planner.plan_authoring(project_root, payload, conn=conn)
    if not allow_questions and plan.get("mode") == "model":
        for question in plan.get("questions") or []:
            coverage_id = str(question.get("coverage_id") or question.get("id") or "")
            coverage = (plan.get("coverage") or {}).get(coverage_id)
            if isinstance(coverage, dict):
                coverage["confidence_label"] = "unresolved"
                coverage["resolved_value"] = None
        plan["questions"] = []
    return authoring_helper.run(
        project_root,
        artifact_type,
        feature_name,
        "--model-plan-json",
        json.dumps(plan),
        "--expected-revision",
        str(revision),
        *(["--canonicalize-feature"] if feature_name.startswith("draft-") else []),
        *(["--hold-generation"] if plan.get("mode") == "fallback" else []),
    )


def get_intake(project_root: str | Path, artifact_type: Optional[str]) -> AuthoringIntake:
    args = [artifact_type] if artifact_type else []
    payload = authoring_helper.run(project_root, *args)
    return AuthoringIntake(
        status=str(payload.get("status") or "error"),
        artifact_type=payload.get("artifact_type"),
        next_input=payload.get("next_input"),
        message=str(payload.get("message") or ""),
        implementation=payload.get("implementation"),
    )


def get_session(
    project_root: str | Path, feature_name: str, artifact_type: str
) -> AuthoringSession:
    """Read-only. Uses --peek so opening or polling never creates state.

    Single-player and multiplayer layouts both work: the helper resolves
    .speed paths through the same rule as dashboard/backend/paths.py.
    """
    root = Path(project_root)
    payload = authoring_helper.run(root, artifact_type, feature_name, "--peek")
    return _session(root, payload)


def list_sessions(
    project_root: str | Path, artifact_type: Optional[str] = "prd"
) -> AuthoringSessionList:
    """Read-only. Uses --list, which reads checkpoints and writes nothing."""
    args = [artifact_type] if artifact_type else []
    payload = authoring_helper.run(project_root, *args, "--list")
    sessions = []
    for entry in payload.get("sessions") or []:
        progress = entry.get("progress") or {}
        sessions.append(
            AuthoringSessionSummary(
                feature_name=str(entry.get("feature_name") or ""),
                feature_title=entry.get("feature_title"),
                artifact_type=str(entry.get("artifact_type") or ""),
                status=str(entry.get("status") or "error"),
                revision=entry.get("revision"),
                updated_at=entry.get("updated_at"),
                progress=AuthoringProgress(
                    confirmed=int(progress.get("confirmed") or 0),
                    total=int(progress.get("total") or 0),
                    deferred=list(progress.get("deferred") or []),
                ),
                draft_available=bool(entry.get("draft_available")),
                artifact_path=entry.get("artifact_path"),
                authoring_url=entry.get("authoring_url"),
                message=str(entry.get("message") or ""),
            )
        )
    return AuthoringSessionList(
        status=str(payload.get("status") or "error"),
        message=str(payload.get("message") or ""),
        sessions=sessions,
    )


def start(
    project_root: str | Path,
    feature_name: str,
    artifact_type: str,
    feature_title: Optional[str],
    feature_description: Optional[str],
) -> AuthoringSession:
    """Create the checkpoint quickly; the authoring route runs AI planning.

    Keeping the model out of this mutation lets the client navigate immediately
    and show explicit analysis progress instead of holding the intake form for
    the full CLI-model response time.
    """
    root = Path(project_root)
    args = [artifact_type, feature_name]
    if feature_title:
        args.extend(["--feature-title", feature_title])
    if feature_description:
        args.extend(["--feature-description", feature_description])
    payload = authoring_helper.run(root, *args)
    if payload.get("status") not in {"error", "helper_unavailable", "revision_conflict"}:
        _claim_for_start(root, str(payload.get("feature_name") or feature_name), artifact_type)
    return _session(root, payload)


def replan(
    project_root: str | Path,
    feature_name: str,
    artifact_type: str,
    expected_revision: int,
    conn: sqlite3.Connection | None = None,
) -> AuthoringSession:
    """Upgrade or refresh an existing session using the configured model harness."""
    root = Path(project_root)
    _authorize_authoring_edit(root, feature_name, artifact_type)
    # React development remounts and fast route transitions can issue the same
    # automatic planning request twice. Serialize that expensive operation and
    # treat a completed current plan as the idempotent result for both callers.
    with _replan_lock(root, feature_name, artifact_type):
        payload = authoring_helper.run(root, artifact_type, feature_name, "--peek")
        planning = payload.get("planning") or {}
        if (
            planning.get("mode") == "model"
            and planning.get("planner_version")
            == authoring_planner.planner_version_for(artifact_type)
        ):
            return _session(root, payload)
        if payload.get("revision") != expected_revision:
            return _session(root, {
                **payload,
                "status": "revision_conflict",
                "message": (
                    f"Expected interview revision {expected_revision}, found "
                    f"{payload.get('revision')}. Reload before re-planning."
                ),
            })
        return _session(
            root,
            _replan_payload(root, feature_name, artifact_type, payload, conn=conn),
        )


def submit_answer(
    project_root: str | Path,
    feature_name: str,
    artifact_type: str,
    answer: str,
    expected_revision: int,
    question_id: Optional[str] = None,
) -> AuthoringSession:
    root = Path(project_root)
    _authorize_authoring_edit(root, feature_name, artifact_type)
    payload = authoring_helper.run(
        root,
        artifact_type,
        feature_name,
        "--answer",
        answer,
        *(["--question-id", question_id] if question_id else []),
        "--expected-revision",
        str(expected_revision),
    )
    return _session(root, payload)


def submit_answers(
    project_root: str | Path,
    feature_name: str,
    artifact_type: str,
    answers: list[dict[str, str]],
    expected_revision: int,
    conn: sqlite3.Connection | None = None,
) -> AuthoringSession:
    """Persist the prepared interview and synthesize without another model wait.

    The initial plan already validated template completeness and produced the
    entire question batch. Once every planned answer is present, the helper can
    compose and self-review directly from that evidence; asking the planner a
    second time only adds latency and can re-ask confirmed coverage.
    """
    root = Path(project_root)
    _authorize_authoring_edit(root, feature_name, artifact_type)
    payload = authoring_helper.run(
        root,
        artifact_type,
        feature_name,
        "--answers-json",
        json.dumps(answers),
        "--expected-revision",
        str(expected_revision),
    )
    return _session(root, payload)


def select_action(
    project_root: str | Path,
    feature_name: str,
    artifact_type: str,
    action: AuthoringAction,
    expected_revision: int,
) -> AuthoringSession:
    root = Path(project_root)
    _authorize_authoring_edit(root, feature_name, artifact_type)
    args = [
        artifact_type,
        feature_name,
        ACTION_FLAG[action],
        "--expected-revision",
        str(expected_revision),
    ]
    payload = authoring_helper.run(root, *args)
    return _session(root, payload)


def revise_coverage(
    project_root: str | Path,
    feature_name: str,
    artifact_type: str,
    coverage_id: str,
    answer: str,
    expected_revision: int,
) -> AuthoringSession:
    root = Path(project_root)
    _authorize_authoring_edit(root, feature_name, artifact_type)
    payload = authoring_helper.run(
        root,
        artifact_type,
        feature_name,
        "--update-coverage",
        coverage_id,
        "--answer",
        answer,
        "--expected-revision",
        str(expected_revision),
    )
    return _session(root, payload)


def revise_section(
    project_root: str | Path,
    feature_name: str,
    artifact_type: str,
    section_title: str,
    body: str,
    expected_revision: int,
) -> AuthoringSession:
    root = Path(project_root)
    _authorize_authoring_edit(root, feature_name, artifact_type)
    payload = authoring_helper.run(
        root,
        artifact_type,
        feature_name,
        "--update-section",
        section_title,
        "--answer",
        body,
        "--expected-revision",
        str(expected_revision),
    )
    return _session(root, payload)


def revise_document(
    project_root: str | Path,
    feature_name: str,
    artifact_type: str,
    content: str,
    expected_revision: int,
) -> AuthoringSession:
    """Save the embedded editor as one atomic authoring revision."""
    root = Path(project_root)
    _authorize_authoring_edit(root, feature_name, artifact_type)
    payload = authoring_helper.run(
        root,
        artifact_type,
        feature_name,
        "--update-document",
        "--answer",
        content,
        "--expected-revision",
        str(expected_revision),
    )
    return _session(root, payload)


def submit_review_comments(
    project_root: str | Path,
    feature_name: str,
    artifact_type: str,
    comments: Any,
    expected_revision: int,
    conn: sqlite3.Connection | None = None,
) -> AuthoringSession:
    """Reconsider commented sections with the model, then regenerate once."""
    root = Path(project_root)
    _authorize_authoring_edit(root, feature_name, artifact_type)
    current = authoring_helper.run(root, artifact_type, feature_name, "--peek")
    if current.get("revision") != expected_revision:
        return _session(root, {
            **current,
            "status": "revision_conflict",
            "message": (
                f"Expected interview revision {expected_revision}, found "
                f"{current.get('revision')}. Reload before regenerating the draft."
            ),
        })
    artifact_content = _read_artifact(root, current.get("artifact_path"))
    if not artifact_content:
        return _session(root, {
            **current,
            "status": "error",
            "message": "Review comments require a readable generated artifact.",
        })
    try:
        if conn is None:
            review_plan = authoring_planner.revise_prd_from_comments(
                root, current, comments, artifact_content
            )
        else:
            review_plan = authoring_planner.revise_prd_from_comments(
                root, current, comments, artifact_content, conn=conn
            )
    except (RuntimeError, ValueError) as exc:
        return _session(root, {
            **current,
            "status": "error",
            "message": str(exc),
        })
    revised_titles = [
        str(item.get("section_title") or "")
        for item in review_plan.get("sections") or []
    ]
    applied_comments: list[dict[str, Any]] = []
    for item in comments if isinstance(comments, list) else []:
        title = str(item.get("section_title") or "").strip() if isinstance(item, dict) else ""
        targets = revised_titles if title in {"", "__document__"} else [title]
        for target in targets:
            applied_comments.append({**item, "section_title": target})
    payload = authoring_helper.run(
        root,
        artifact_type,
        feature_name,
        "--review-comments-json",
        json.dumps(applied_comments),
        "--review-plan-json",
        json.dumps(review_plan),
        "--expected-revision",
        str(expected_revision),
    )
    return _session(root, payload)


def add_review_comment(
    project_root: str | Path,
    feature_name: str,
    artifact_type: str,
    comment: Any,
    expected_revision: int,
) -> AuthoringSession:
    """Persist reviewer guidance immediately, before regeneration."""
    root = Path(project_root)
    payload = authoring_helper.run(
        root,
        artifact_type,
        feature_name,
        "--add-review-comment-json",
        json.dumps(comment),
        "--expected-revision",
        str(expected_revision),
    )
    return _session(root, payload)


def publish(
    project_root: str | Path,
    feature_name: str,
    artifact_type: str,
    expected_revision: int,
) -> AuthoringSession:
    """Publish the current draft as a versioned snapshot."""
    root = Path(project_root)
    _authorize_authoring_edit(root, feature_name, artifact_type)
    payload = authoring_helper.run(
        root,
        artifact_type,
        feature_name,
        "--publish",
        "--expected-revision",
        str(expected_revision),
    )
    return _session(root, payload)


def prepare_commit(
    project_root: str | Path,
    feature_name: str,
    artifact_type: str,
) -> AuthoringSession:
    """Make a completed guided draft available to the existing commit flow.

    Guided authoring creates the intent, context package, draft record, and spec,
    but older checkpoints may predate ceremony-state compatibility. The explicit
    Review & commit action is the correct place to add the missing ceremony and
    ownership records without turning read-only resume queries into writes.
    """
    root = Path(project_root)
    session = get_session(root, feature_name, artifact_type)
    if session.status not in {"drafted", "published"}:
        raise ValueError(
            f"Resolve every blocking self-review finding before reviewing and committing the {artifact_type.upper()}."
        )
    if (session.self_review or {}).get("status") != "passed":
        raise ValueError("The latest generated artifact has not passed self-review.")
    if any(
        not item.get("status") or item.get("status") == "open"
        for item in (session.review_comments or [])
    ):
        raise ValueError("Apply or resolve every open review comment before committing.")
    _authorize_authoring_edit(root, feature_name, artifact_type)

    from ..paths import get_paths
    from . import context as context_resolver

    paths = get_paths(root)
    if not paths.ceremony_state(feature_name).exists():
        intent_text = session.feature_title or feature_name
        try:
            intent_data = json.loads(
                paths.ceremony_intent(feature_name).read_text(encoding="utf-8")
            )
            intent_text = str(intent_data.get("text") or intent_text)
        except (OSError, ValueError, TypeError):
            pass
        context_resolver.create_ceremony(root, intent_text, feature_name)

    return session
