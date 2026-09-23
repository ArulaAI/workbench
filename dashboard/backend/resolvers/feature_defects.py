"""Thin GraphQL adapters for the shared Define defect core."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import sqlite3
from typing import Any

from lib.defect_findings import (
    FindingError,
    group_findings,
    read_evidence_file,
    read_findings,
    record_decision,
)
from lib.defect_intake import append_defect_evidence, file_defect, preview_defect
from lib.defect_reports import build_report_view, discover_defects, export_report

from ..paths import get_paths
from ..spec_registry import update_spec
from .ceremony_types import get_current_actor
from .feature_defect_types import (
    AppendDefectEvidenceInput,
    FileFindingDefectInput,
    FindingDecisionInput,
    GroupFindingsInput,
)


def _error(exc: FindingError) -> dict[str, Any]:
    errors = getattr(exc, "errors", None)
    if not errors:
        errors = [{"field": exc.field, "message": str(exc)}]
    result: dict[str, Any] = {"success": False, "code": exc.code, "errors": errors}
    duplicates = getattr(exc, "duplicates", None)
    if duplicates:
        result["duplicates"] = duplicates
    return result


def feature_findings(project_root: Path | str, feature_name: str) -> dict[str, Any]:
    return read_findings(get_paths(project_root), feature_name)


def evidence_file(
    project_root: Path | str, feature_name: str, finding_id: str,
    evidence_id: str, source_path: str,
) -> dict[str, Any]:
    try:
        result = read_evidence_file(
            get_paths(project_root), feature_name, finding_id, evidence_id, source_path,
        )
        return {"success": True, "code": "OK", "errors": [], **result}
    except FindingError as exc:
        return _error(exc)


def defect_draft(project_root: Path | str, feature_name: str, finding_id: str) -> dict[str, Any]:
    return preview_defect(get_paths(project_root), feature_name, finding_id)


def defect_report(project_root: Path | str, filters: dict[str, Any]) -> dict[str, Any]:
    paths = get_paths(project_root)
    return build_report_view(discover_defects(Path(project_root), paths.defects_dir), filters)


def defect_report_export(
    project_root: Path | str, filters: dict[str, Any], displayed_revision: str, format: str,
) -> dict[str, Any]:
    try:
        view = defect_report(project_root, filters)
        if view["revision"] != displayed_revision:
            raise FindingError("STALE_REPORT", "Defect files changed; refresh before exporting")
        return {"success": True, "code": "OK", "content": export_report(view, format), "errors": []}
    except FindingError as exc:
        return _error(exc)
    except ValueError as exc:
        return {"success": False, "code": "INVALID_INPUT", "content": None,
                "errors": [{"field": "format", "message": str(exc)}]}


def decide(project_root: Path | str, input: FindingDecisionInput) -> dict[str, Any]:
    paths = get_paths(project_root)
    try:
        decision = record_decision(
            paths, input.feature_name, input.decision_revision, input.finding_revision,
            {"finding_id": input.finding_id, "request_id": input.request_id,
             "action": input.action, "rationale": input.rationale,
             "task_id": input.task_id, "duplicate_target": input.duplicate_target},
            get_current_actor(),
        )
        return {"success": True, "code": "OK", "decision": decision, "errors": []}
    except FindingError as exc:
        return _error(exc)


def group(project_root: Path | str, input: GroupFindingsInput) -> dict[str, Any]:
    paths = get_paths(project_root)
    try:
        view = group_findings(
            paths, input.feature_name, input.decision_revision,
            {item.finding_id: item.evidence_identities for item in input.memberships},
            input.rationale, get_current_actor(), input.request_id,
        )
        return {"success": True, "code": "OK", "view": view, "errors": []}
    except FindingError as exc:
        return _error(exc)


def file(
    project_root: Path | str, input: FileFindingDefectInput,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    paths = get_paths(project_root)
    try:
        result = file_defect(
            paths, input.feature_name, input.finding_id, input.evidence_ids,
            input.finding_revision, input.decision_revision, input.request_id,
            asdict(input.draft), input.rationale, get_current_actor(), input.duplicate_reason,
        )
        warnings: list[str] = []
        if conn is not None:
            try:
                update_spec(conn, Path(project_root) / result["canonical_path"], project_root)
            except (OSError, sqlite3.Error, ValueError) as exc:
                warnings.append(f"Defect filed, but the editor index was not updated: {exc}")
        return {"success": True, "code": "OK", "errors": [], "warnings": warnings, **result}
    except FindingError as exc:
        return _error(exc)
    except (OSError, RuntimeError, ValueError) as exc:
        return {"success": False, "code": "WRITE_FAILED", "errors": [{"field": "", "message": str(exc)}]}


def append(project_root: Path | str, input: AppendDefectEvidenceInput) -> dict[str, Any]:
    paths = get_paths(project_root)
    try:
        result = append_defect_evidence(
            paths, input.feature_name, input.finding_id, input.defect_slug,
            input.finding_revision, input.decision_revision, input.request_id,
            input.rationale, get_current_actor(),
        )
        return {"success": True, "code": "OK", "errors": [], **result}
    except FindingError as exc:
        return _error(exc)
