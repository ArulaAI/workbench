"""Deterministic defect previews and recoverable filing transactions."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lib.defect_findings import (
    FindingError,
    _atomic_json,
    _digest,
    _load_history,
    archive_legacy_evidence,
    intake_lock,
    read_findings,
)
from lib.defect_reports import (
    CLOSED_STATUSES,
    VALID_SEVERITIES,
    discover_defects,
    discover_feature_names,
    initial_defect_state,
    render_report,
    secret_fields,
    validate_report,
)


MAX_FIELD_BYTES = 16 * 1024
MAX_REPORT_BYTES = 128 * 1024
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True)
class DefectDraft:
    title: str
    severity: str | None
    severity_confirmed: bool
    related_features: tuple[str, ...]
    observed: str
    expected: str
    reproduction: str
    context: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _finding(view: dict[str, Any], finding_id: str) -> dict[str, Any]:
    for finding in view["findings"]:
        if finding["id"] == finding_id:
            return finding
    raise FindingError("NOT_FOUND", "Finding was not found", "findingId")


def _first_fact(evidence: list[dict[str, Any]], field: str) -> str:
    for item in evidence:
        value = str(item.get(field) or "").strip()
        if value and not value.casefold().startswith("[redacted:"):
            return value
    return ""


def _context(evidence: list[dict[str, Any]]) -> str:
    lines = ["Selected evidence:"]
    for item in evidence:
        producer = str(item.get("producer") or item.get("source") or "unknown")
        task = f" task {item['task_id']}" if item.get("task_id") else ""
        summary = str(item.get("summary") or "Evidence item").strip()
        path = str(item.get("artifact_path") or "unknown artifact")
        lines.append(f"- {producer}{task}: {summary} (source: `{path}`)")
    return "\n".join(lines)


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")
    if len(slug) > 80:
        boundary = slug.rfind("-", 0, 81)
        if boundary > 0:
            slug = slug[:boundary]
        else:
            digest = hashlib.sha256(title.encode()).hexdigest()[:12]
            slug = f"defect-{digest}"
    if not slug or not _SLUG_RE.fullmatch(slug):
        raise FindingError("INVALID_INPUT", "Title cannot produce a safe defect slug", "title")
    return slug


def _duplicates(paths: Any, title: str, finding_id: str) -> list[dict[str, Any]]:
    needle = re.sub(r"\W+", " ", title.casefold()).strip()
    candidates: list[dict[str, Any]] = []
    for row in discover_defects(Path(paths.root), Path(paths.defects_dir)):
        row_title = re.sub(r"\W+", " ", str(row.get("title") or "").casefold()).strip()
        if needle and row_title and (needle == row_title or needle in row_title or row_title in needle):
            candidates.append({
                "slug": row["slug"], "title": row["title"], "status": row["status"],
                "reason": "similar title", "canonical_path": row.get("canonical_path"),
            })
    return candidates


def preview_defect(paths: Any, feature: str, finding_id: str) -> dict[str, Any]:
    """Build a no-write defect draft from facts explicitly present in evidence."""
    view = read_findings(paths, feature)
    finding = _finding(view, finding_id)
    evidence = finding["evidence"]
    draft = DefectDraft(
        title=str(finding.get("title") or "Untitled defect")[:160],
        severity=None,
        severity_confirmed=False,
        related_features=(feature,),
        observed=_first_fact(evidence, "observed"),
        expected=_first_fact(evidence, "expected"),
        reproduction=_first_fact(evidence, "reproduction"),
        context=_context(evidence),
    )
    missing = [
        field for field in ("severity", "observed", "expected", "reproduction")
        if not getattr(draft, field)
    ]
    return {
        "draft": asdict(draft),
        "source_feature": feature,
        "finding_revision": finding["revision"],
        "decision_revision": view["decision_revision"],
        "provenance": {
            "finding_id": finding_id,
            "evidence_ids": [item["id"] for item in evidence],
            "evidence_paths": [item["artifact_path"] for item in evidence],
        },
        "missing_fields": missing,
        "duplicates": _duplicates(paths, draft.title, finding_id),
        "warnings": view.get("warnings") or [],
    }


def _draft_dict(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": str(value.get("title") or "").strip(),
        "severity": str(value.get("severity") or "").strip().upper() or None,
        "severity_confirmed": bool(value.get("severity_confirmed", value.get("severityConfirmed", False))),
        "related_features": list(value.get("related_features", value.get("relatedFeatures", [])) or []),
        "observed": str(value.get("observed") or "").strip(),
        "expected": str(value.get("expected") or "").strip(),
        "reproduction": str(value.get("reproduction") or "").strip(),
        "context": str(value.get("context") or "").strip(),
    }


def _validation_errors(paths: Any, draft: dict[str, Any], rationale: str) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    title = draft["title"]
    if not title or len(title) > 160:
        errors.append({"field": "title", "message": "Title must be 1-160 characters"})
    errors.extend(validate_report(draft, strict=True))
    if not draft["severity_confirmed"]:
        errors.append({"field": "severityConfirmed", "message": "Confirm the severity before filing"})
    known = set(discover_feature_names(Path(paths.root), Path(paths.features_dir)))
    unknown = [name for name in draft["related_features"] if name not in known]
    if unknown:
        errors.append({"field": "relatedFeatures", "message": f"Unknown feature: {unknown[0]}"})
    if not rationale.strip():
        errors.append({"field": "rationale", "message": "Rationale is required"})
    for field in ("title", "observed", "expected", "reproduction", "context"):
        if len(str(draft[field]).encode("utf-8")) > MAX_FIELD_BYTES:
            errors.append({"field": field, "message": "Must be 16 KiB or smaller"})
    return errors


def _branch_staleness(paths: Any, feature: str, evidence: list[dict[str, Any]]) -> str | None:
    """Return a stale message when a known task branch moved after inspection."""
    checked: set[tuple[str, str]] = set()
    for item in evidence:
        task_id = str(item.get("task_id") or "")
        inspected = str(item.get("commit") or "")
        if not task_id or not inspected or (task_id, inspected) in checked:
            continue
        checked.add((task_id, inspected))
        task_path = Path(paths.feature_shared(feature)) / "tasks" / f"{task_id}.json"
        try:
            task = json.loads(task_path.read_text(encoding="utf-8"))
            branch = str(task.get("branch") or "") if isinstance(task, dict) else ""
        except (OSError, json.JSONDecodeError):
            continue
        if not branch:
            continue
        current = subprocess.run(
            ["git", "-C", str(paths.root), "rev-parse", "--verify", branch],
            text=True, capture_output=True, check=False,
        )
        recorded = subprocess.run(
            ["git", "-C", str(paths.root), "rev-parse", "--verify", inspected],
            text=True, capture_output=True, check=False,
        )
        if current.returncode == 0 and recorded.returncode == 0 \
            and current.stdout.strip() != recorded.stdout.strip():
            return f"Task {task_id} branch {branch} changed after its evidence was produced"
    return None


def _write_exclusive(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(fd)


def _same_bytes(path: Path, data: bytes) -> bool:
    try:
        return path.read_bytes() == data
    except OSError:
        return False


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _manifest_result(manifest: dict[str, Any]) -> dict[str, Any]:
    result = dict(manifest["result"])
    result["replayed"] = True
    return result


def _publish_or_verify(path: Path, data: bytes, label: str) -> None:
    if path.exists():
        if not _same_bytes(path, data):
            raise FindingError("RECOVERY_CONFLICT", f"{label} was changed outside this intake request")
    else:
        _write_exclusive(path, data)
        _fsync_dir(path.parent)


def _stage_receipt(receipt_dir: Path, payloads: dict[str, bytes], manifest: dict[str, Any]) -> None:
    """Publish a complete staging receipt with one atomic directory rename."""
    receipt_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{receipt_dir.name}.", dir=receipt_dir.parent))
    try:
        for name, data in payloads.items():
            _write_exclusive(temporary / name, data)
        _atomic_json(temporary / "manifest.json", manifest)
        _fsync_dir(temporary)
        os.replace(temporary, receipt_dir)
        _fsync_dir(receipt_dir.parent)
    finally:
        if temporary.exists():
            for child in temporary.iterdir():
                if child.is_file():
                    child.unlink()
            temporary.rmdir()


def _complete_filing(paths: Any, receipt_dir: Path, manifest: dict[str, Any], replayed: bool) -> dict[str, Any]:
    """Roll a prepared, byte-identical transaction forward to its commit point."""
    slug = str(manifest.get("slug") or "")
    canonical_rel = str(manifest.get("canonical_path") or "")
    feature = str(manifest.get("feature") or "")
    if not _SLUG_RE.fullmatch(slug) or canonical_rel != f"specs/defects/{slug}.md":
        raise FindingError("REPAIR_REQUIRED", "Intake receipt contains unsafe destination paths")
    try:
        report_bytes = (receipt_dir / "report.md").read_bytes()
        state_bytes = (receipt_dir / "state.json").read_bytes()
        decision_bytes = (receipt_dir / "decision.json").read_bytes()
        decision = json.loads(decision_bytes)
    except (OSError, json.JSONDecodeError) as exc:
        raise FindingError("REPAIR_REQUIRED", f"Staged intake payload is unreadable: {exc}") from exc
    expected_hashes = {
        "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
        "state_sha256": hashlib.sha256(state_bytes).hexdigest(),
        "decision_sha256": hashlib.sha256(decision_bytes).hexdigest(),
    }
    if any(manifest.get(key) != value for key, value in expected_hashes.items()):
        raise FindingError("RECOVERY_CONFLICT", "Staged intake payload does not match its receipt")

    canonical_path = Path(paths.root) / canonical_rel
    final_dir = Path(paths.defects_dir) / slug
    try:
        _publish_or_verify(canonical_path, report_bytes, "Canonical report")
        final_dir.mkdir(parents=True, exist_ok=True)
        _publish_or_verify(final_dir / "report.md", report_bytes, "Pipeline report")
        _publish_or_verify(final_dir / "state.json", state_bytes, "Defect state")
        (final_dir / "logs").mkdir(exist_ok=True)

        history, warnings = _load_history(Path(paths.feature_shared(feature)))
        if warnings:
            raise FindingError("REPAIR_REQUIRED", warnings[0])
        existing = next((item for item in history["decisions"] if item.get("id") == decision.get("id")), None)
        if existing and existing.get("body_digest") != decision.get("body_digest"):
            raise FindingError("REQUEST_CONFLICT", "Decision request conflicts with the intake receipt")
        if not existing:
            history["decisions"].append(decision)
            history["revision"] = int(history["revision"]) + 1
            _atomic_json(Path(paths.feature_shared(feature)) / "findings.json", history)

        manifest["phase"] = "committed"
        manifest["committed_at"] = _utc_now()
        _atomic_json(receipt_dir / "manifest.json", manifest)
        result = dict(manifest["result"])
        result["replayed"] = replayed
        return result
    except FindingError:
        raise
    except OSError as exc:
        raise FindingError("WRITE_FAILED", f"Could not complete defect filing: {exc}") from exc


def file_defect(
    paths: Any, feature: str, finding_id: str, evidence_ids: list[str],
    finding_revision: str, decision_revision: int, request_id: str,
    draft: dict[str, Any], rationale: str, actor: tuple[str, str],
    duplicate_reason: str | None = None,
) -> dict[str, Any]:
    """File a canonical report and initial state using a recoverable journal."""
    try:
        uuid.UUID(request_id)
    except ValueError as exc:
        raise FindingError("INVALID_INPUT", "requestId must be a UUID", "requestId") from exc
    normalized = _draft_dict(draft)
    body = {
        "feature": feature, "finding_id": finding_id,
        "evidence_ids": sorted(evidence_ids), "draft": normalized,
        "rationale": rationale.strip(), "duplicate_reason": (duplicate_reason or "").strip(),
        "actor": list(actor),
    }
    body_digest = _digest(body)
    defects_dir = Path(paths.defects_dir)
    receipt_dir = defects_dir / ".intake" / request_id
    manifest_path = receipt_dir / "manifest.json"

    with intake_lock(defects_dir):
        manifest: dict[str, Any] | None = None
        if manifest_path.is_file():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise FindingError("REPAIR_REQUIRED", f"Intake receipt is unreadable: {exc}") from exc
            if manifest.get("body_digest") != body_digest:
                raise FindingError("REQUEST_CONFLICT", "requestId was already used with different input")
            if manifest.get("phase") == "committed":
                return _manifest_result(manifest)
            if manifest.get("phase") == "prepared":
                return _complete_filing(paths, receipt_dir, manifest, replayed=True)
            raise FindingError("REPAIR_REQUIRED", "Intake receipt has an unsupported phase")

        view = read_findings(paths, feature)
        finding = _finding(view, finding_id)
        current_evidence_ids = sorted(item["id"] for item in finding["evidence"])
        regression_of: str | None = None
        for prior in reversed(finding.get("history") or []):
            if prior.get("action") != "create_defect" or sorted(prior.get("evidence_ids") or []) != current_evidence_ids:
                continue
            prior_manifest = defects_dir / ".intake" / str(prior.get("id")) / "manifest.json"
            try:
                receipt = json.loads(prior_manifest.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if receipt.get("phase") == "committed" and prior.get("defect_slug"):
                prior_slug = str(prior["defect_slug"])
                try:
                    prior_state = json.loads((defects_dir / prior_slug / "state.json").read_text(encoding="utf-8"))
                    prior_status = str(prior_state.get("status") or "unknown")
                except (OSError, json.JSONDecodeError):
                    prior_status = "unknown"
                if prior_status not in CLOSED_STATUSES:
                    return {
                        "slug": prior_slug,
                        "canonical_path": f"specs/defects/{prior_slug}.md",
                        "decision_id": prior["id"], "replayed": True,
                    }
                regression_of = prior_slug
                break
        if view["decision_revision"] != decision_revision:
            raise FindingError("STALE_DECISION", "Finding decisions changed; refresh and try again")
        if finding["revision"] != finding_revision:
            raise FindingError("STALE_EVIDENCE", "Finding evidence changed; refresh and try again")
        if sorted(evidence_ids) != current_evidence_ids:
            raise FindingError("STALE_EVIDENCE", "Selected evidence no longer matches the finding", "evidenceIds")
        stale_build = _branch_staleness(paths, feature, finding["evidence"])
        if stale_build:
            raise FindingError("STALE_EVIDENCE", stale_build, "findingRevision")

        errors = _validation_errors(paths, normalized, rationale)
        if errors:
            error = FindingError("INVALID_INPUT", "Defect draft is incomplete", errors[0]["field"])
            error.errors = errors  # type: ignore[attr-defined]
            raise error
        slug = _slugify(normalized["title"])
        if regression_of == slug:
            raise FindingError(
                "INVALID_INPUT",
                "A regression needs a distinct title so the resolved defect remains unchanged",
                "title",
            )
        if (Path(paths.root) / "specs" / "defects" / f"{slug}.md").exists() \
            or (defects_dir / slug).exists():
            raise FindingError("DUPLICATE", "A defect already uses this title", "title")
        duplicates = _duplicates(paths, normalized["title"], finding_id)
        if duplicates and not (duplicate_reason or "").strip():
            error = FindingError("DUPLICATE", "A similar defect already exists", "duplicateReason")
            error.duplicates = duplicates  # type: ignore[attr-defined]
            raise error

        archive_legacy_evidence(paths, feature, finding["evidence"])
        archived_view = read_findings(paths, feature)
        archived_finding = _finding(archived_view, finding_id)
        archived_evidence_ids = sorted(item["id"] for item in archived_finding["evidence"])
        if archived_finding["revision"] != finding_revision or archived_evidence_ids != current_evidence_ids:
            raise FindingError("STALE_EVIDENCE", "Evidence changed while it was archived; refresh and try again")
        finding = archived_finding

        now = _utc_now()
        canonical_rel = f"specs/defects/{slug}.md"
        provenance = {
            "request_id": request_id, "source_feature": feature,
            "finding_id": finding_id,
            "evidence_paths": [item["artifact_path"] for item in finding["evidence"]],
            "actor_name": actor[0], "actor_email": actor[1], "filed_at": now,
        }
        report_text = render_report(normalized, provenance)
        report_bytes = report_text.encode("utf-8")
        if len(report_bytes) > MAX_REPORT_BYTES:
            raise FindingError("INVALID_INPUT", "Generated report exceeds 128 KiB", "context")
        flagged = secret_fields({"report": report_text})
        if flagged:
            raise FindingError("INVALID_INPUT", "Defect report contains a credential pattern", "context")

        state = initial_defect_state(canonical_rel, normalized["severity"], now)
        state.update({
            "related_features": normalized["related_features"], "source": "define",
            "source_feature": feature, "created_by": actor[1], "modified_by": actor[1],
            "intake": {"schema_version": 1, "request_id": request_id,
                       "finding_id": finding_id, "evidence_ids": current_evidence_ids},
        })
        if regression_of:
            state["regression_of"] = regression_of
        state_bytes = (json.dumps(state, indent=2, sort_keys=True) + "\n").encode()
        decision = {
            "id": request_id, "event_kind": "disposition", "finding_id": finding_id,
            "evidence_ids": current_evidence_ids, "action": "create_defect",
            "rationale": rationale.strip(), "actor_name": actor[0], "actor_email": actor[1],
            "at": now, "task_id": None, "defect_slug": slug,
            "duplicate_reason": (duplicate_reason or "").strip() or None,
            "regression_of": regression_of,
            "body_digest": body_digest,
        }
        decision_bytes = (json.dumps(decision, indent=2, sort_keys=True) + "\n").encode()
        result = {"slug": slug, "canonical_path": canonical_rel,
                  "decision_id": request_id, "replayed": False}
        expected_manifest = {
            "schema_version": 1, "request_id": request_id, "body_digest": body_digest,
            "feature": feature, "finding_id": finding_id, "slug": slug,
            "prepared_at": now,
            "canonical_path": canonical_rel,
            "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
            "state_sha256": hashlib.sha256(state_bytes).hexdigest(),
            "decision_sha256": hashlib.sha256(decision_bytes).hexdigest(),
            "phase": "prepared", "result": result,
        }
        _stage_receipt(receipt_dir, {
            "report.md": report_bytes, "state.json": state_bytes, "decision.json": decision_bytes,
        }, expected_manifest)
        return _complete_filing(paths, receipt_dir, expected_manifest, replayed=False)


def append_defect_evidence(
    paths: Any, feature: str, finding_id: str, defect_slug: str,
    finding_revision: str, decision_revision: int, request_id: str,
    rationale: str, actor: tuple[str, str],
) -> dict[str, Any]:
    """Append current finding references without rewriting the canonical report."""
    try:
        uuid.UUID(request_id)
    except ValueError as exc:
        raise FindingError("INVALID_INPUT", "requestId must be a UUID", "requestId") from exc
    if not rationale.strip():
        raise FindingError("INVALID_INPUT", "Rationale is required", "rationale")
    if not _SLUG_RE.fullmatch(defect_slug):
        raise FindingError("INVALID_INPUT", "Defect slug is invalid", "defectSlug")
    defects_dir = Path(paths.defects_dir)
    target = defects_dir / defect_slug
    receipt_dir = defects_dir / ".intake" / request_id
    manifest_path = receipt_dir / "manifest.json"
    body_digest = _digest({
        "feature": feature, "finding_id": finding_id, "defect_slug": defect_slug,
        "finding_revision": finding_revision, "rationale": rationale.strip(), "actor": list(actor),
    })

    def complete(manifest: dict[str, Any], replayed: bool) -> dict[str, Any]:
        try:
            entry_bytes = (receipt_dir / "evidence.json").read_bytes()
            decision_bytes = (receipt_dir / "decision.json").read_bytes()
            decision = json.loads(decision_bytes)
        except (OSError, json.JSONDecodeError) as exc:
            raise FindingError("REPAIR_REQUIRED", f"Staged evidence attachment is unreadable: {exc}") from exc
        if hashlib.sha256(entry_bytes).hexdigest() != manifest.get("evidence_sha256") \
            or hashlib.sha256(decision_bytes).hexdigest() != manifest.get("decision_sha256"):
            raise FindingError("RECOVERY_CONFLICT", "Staged evidence attachment changed")
        output = target / "evidence" / f"{request_id}.json"
        try:
            _publish_or_verify(output, entry_bytes, "Defect evidence entry")
            history, warnings = _load_history(Path(paths.feature_shared(feature)))
            if warnings:
                raise FindingError("REPAIR_REQUIRED", warnings[0])
            existing = next((item for item in history["decisions"] if item.get("id") == request_id), None)
            if existing and existing.get("body_digest") != decision.get("body_digest"):
                raise FindingError("REQUEST_CONFLICT", "Attachment decision conflicts with its receipt")
            if not existing:
                history["decisions"].append(decision)
                history["revision"] = int(history["revision"]) + 1
                _atomic_json(Path(paths.feature_shared(feature)) / "findings.json", history)
            manifest["phase"] = "committed"
            manifest["committed_at"] = _utc_now()
            _atomic_json(manifest_path, manifest)
            return {"path": str(output.relative_to(paths.root)), "decision_id": request_id, "replayed": replayed}
        except FindingError:
            raise
        except OSError as exc:
            raise FindingError("WRITE_FAILED", f"Could not attach defect evidence: {exc}") from exc

    with intake_lock(defects_dir):
        if manifest_path.is_file():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise FindingError("REPAIR_REQUIRED", f"Attachment receipt is unreadable: {exc}") from exc
            if manifest.get("body_digest") != body_digest or manifest.get("kind") != "evidence_attachment":
                raise FindingError("REQUEST_CONFLICT", "requestId was already used with different input")
            if manifest.get("phase") == "committed":
                result = dict(manifest["result"]); result["replayed"] = True
                return result
            if manifest.get("phase") == "prepared":
                return complete(manifest, True)
            raise FindingError("REPAIR_REQUIRED", "Attachment receipt has an unsupported phase")

        if not (target / "state.json").is_file():
            raise FindingError("NOT_FOUND", "Target defect was not found", "defectSlug")
        view = read_findings(paths, feature)
        finding = _finding(view, finding_id)
        if view["decision_revision"] != decision_revision:
            raise FindingError("STALE_DECISION", "Finding decisions changed; refresh and try again")
        if finding["revision"] != finding_revision:
            raise FindingError("STALE_EVIDENCE", "Finding changed; refresh and try again")
        archive_legacy_evidence(paths, feature, finding["evidence"])
        archived_view = read_findings(paths, feature)
        archived_finding = _finding(archived_view, finding_id)
        if archived_finding["revision"] != finding_revision:
            raise FindingError("STALE_EVIDENCE", "Evidence changed while it was archived; refresh and try again")
        finding = archived_finding
        now = _utc_now()
        entry = {
            "schema_version": 1, "request_id": request_id, "feature": feature,
            "finding_id": finding_id, "evidence_ids": [item["id"] for item in finding["evidence"]],
            "artifact_paths": [item["artifact_path"] for item in finding["evidence"]],
            "rationale": rationale.strip(), "actor_name": actor[0], "actor_email": actor[1], "at": now,
        }
        decision = {
            "id": request_id, "event_kind": "evidence_attachment", "finding_id": finding_id,
            "evidence_ids": entry["evidence_ids"], "action": None, "rationale": rationale.strip(),
            "actor_name": actor[0], "actor_email": actor[1], "at": now,
            "defect_slug": defect_slug, "body_digest": body_digest,
        }
        entry_bytes = (json.dumps(entry, indent=2, sort_keys=True) + "\n").encode()
        decision_bytes = (json.dumps(decision, indent=2, sort_keys=True) + "\n").encode()
        result = {"path": str((target / "evidence" / f"{request_id}.json").relative_to(paths.root)),
                  "decision_id": request_id, "replayed": False}
        manifest = {
            "schema_version": 1, "kind": "evidence_attachment", "phase": "prepared",
            "request_id": request_id, "body_digest": body_digest, "feature": feature,
            "finding_id": finding_id, "slug": defect_slug,
            "evidence_sha256": hashlib.sha256(entry_bytes).hexdigest(),
            "decision_sha256": hashlib.sha256(decision_bytes).hexdigest(), "result": result,
        }
        _stage_receipt(receipt_dir, {
            "evidence.json": entry_bytes, "decision.json": decision_bytes,
        }, manifest)
        return complete(manifest, False)
