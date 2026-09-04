"""Guided authoring resolvers.

Every field here is a projection of the helper's JSON result. The resolver
adds no question, option, gate, or default of its own; it selects flags, reads
the generated artifact from disk, and reports what the helper returned.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from .. import authoring_helper
from .authoring_types import (
    AuthoringAction,
    AuthoringIntake,
    AuthoringProgress,
    AuthoringSession,
)

ACTION_FLAG = {
    AuthoringAction.ACCEPT: "--accept-suggestion",
    AuthoringAction.EDIT: "--edit-suggestion",
    AuthoringAction.REJECT: "--reject-suggestion",
    AuthoringAction.DEFER: "--defer",
}

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
        artifact_content=_read_artifact(project_root, artifact_path),
        dashboard_url=payload.get("dashboard_url"),
        authoring_url=payload.get("authoring_url"),
        helper_path=payload.get("helper_path"),
        interpreter=payload.get("interpreter"),
        current_question=payload.get("current_question"),
        coverage=payload.get("coverage"),
        sections=payload.get("sections"),
        self_review=payload.get("self_review"),
        resume_step=payload.get("resume_step"),
        upstream=payload.get("upstream"),
        implementation=payload.get("implementation"),
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


def start(
    project_root: str | Path,
    feature_name: str,
    artifact_type: str,
    feature_title: Optional[str],
    feature_description: Optional[str],
) -> AuthoringSession:
    root = Path(project_root)
    args = [artifact_type, feature_name]
    if feature_title:
        args.extend(["--feature-title", feature_title])
    if feature_description:
        args.extend(["--feature-description", feature_description])
    return _session(root, authoring_helper.run(root, *args))


def submit_answer(
    project_root: str | Path,
    feature_name: str,
    artifact_type: str,
    answer: str,
    expected_revision: int,
) -> AuthoringSession:
    root = Path(project_root)
    payload = authoring_helper.run(
        root,
        artifact_type,
        feature_name,
        "--answer",
        answer,
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
    payload = authoring_helper.run(
        root,
        artifact_type,
        feature_name,
        ACTION_FLAG[action],
        "--expected-revision",
        str(expected_revision),
    )
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
