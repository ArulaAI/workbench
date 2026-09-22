"""Evidence normalization and durable feature finding decisions."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from lib.review_evidence import parse_clean_review_payload


SCHEMA_VERSION = 1
MAX_ARTIFACT_BYTES = 1024 * 1024
_FEATURE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,49}$")
_thread_lock = threading.RLock()


class FindingError(Exception):
    def __init__(self, code: str, message: str, field: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.field = field


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


def _redact_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Redact string fields that match the shared grounding secret scanner."""
    from lib.defect_reports import secret_fields

    strings: dict[str, str] = {}

    def collect(value: Any, path: str) -> None:
        if isinstance(value, str):
            strings[path] = value
        elif isinstance(value, dict):
            for key, child in value.items():
                collect(child, f"{path}.{key}" if path else str(key))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                collect(child, f"{path}[{index}]")

    collect(payload, "")
    flagged = secret_fields(strings)

    def redact(value: Any, path: str) -> Any:
        if isinstance(value, str):
            return "[redacted: source contains a credential pattern]" if path in flagged else value
        if isinstance(value, dict):
            return {key: redact(child, f"{path}.{key}" if path else str(key)) for key, child in value.items()}
        if isinstance(value, list):
            return [redact(child, f"{path}[{index}]") for index, child in enumerate(value)]
        return value

    return redact(payload, ""), sorted(flagged)


@contextmanager
def intake_lock(defects_dir: Path, timeout: float = 5.0) -> Iterator[None]:
    """Serialize intake writers across threads and local processes."""
    defects_dir.mkdir(parents=True, exist_ok=True)
    lock_path = defects_dir / ".intake.lock"
    with _thread_lock:
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
        deadline = time.monotonic() + timeout
        try:
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise FindingError("BUSY", "Defect intake is busy; retry shortly")
                    time.sleep(0.05)
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)


def review_items(payload: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    result: list[tuple[str, dict[str, Any]]] = []
    for field in ("issues", "spec_verification", "missing_from_spec", "out_of_scope"):
        values = payload.get(field, [])
        if values is None:
            values = []
        if not isinstance(values, list):
            raise ValueError(f"{field} must be an array")
        for item in values:
            if isinstance(item, str):
                item = {"description": item}
            if not isinstance(item, dict):
                raise ValueError(f"{field} entries must be objects or strings")
            if field == "spec_verification" and item.get("satisfied") in (True, "true"):
                continue
            result.append((field, item))
    return result


def _item_key(field: str, item: dict[str, Any], occurrence: int) -> str:
    identity = dict(item)
    identity.pop("line", None)
    return f"{field}:{_digest(identity)[:20]}:{occurrence}"


def _review_evidence(
    *, payload: dict[str, Any], producer: str, task_id: str | None,
    artifact_path: str, content_hash: str, artifact_hash: str,
    attempt_id: str | None = None, commit: str | None = None,
    diff_hash: str | None = None,
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    occurrences: dict[str, int] = {}
    verdict = payload.get("verdict")
    for field, item in review_items(payload):
        basis = _digest({k: v for k, v in item.items() if k != "line"})
        occurrence = occurrences.get(f"{field}:{basis}", 0)
        occurrences[f"{field}:{basis}"] = occurrence + 1
        key = _item_key(field, item, occurrence)
        summary = str(item.get("message") or item.get("description") or item.get("spec_quote") or item.get("file") or "Review finding").strip()
        # A reviewer's conclusion is supporting context.  It only fills report
        # facts when the producer explicitly labels those facts in its payload.
        observed = str(item.get("observed") or item.get("actual") or "").strip() or None
        expected = str(item.get("expected") or "").strip() or None
        if not expected and field in {"spec_verification", "missing_from_spec"}:
            expected = str(item.get("spec_quote") or item.get("requirement") or "").strip() or None
        file_value = str(item.get("file") or "").strip()
        line_value = item.get("line")
        if file_value and isinstance(line_value, int) and line_value > 0:
            file_value = f"{file_value}:{line_value}"
        files = (file_value,) if file_value else ()
        evidence_id = _digest([producer, task_id, key, content_hash])
        severity = str(item.get("severity") or "").lower() or None
        recommended = "fix_scope" if field == "out_of_scope" else (
            "fix_in_feature" if severity in {"critical", "major"} or verdict == "request_changes" else "consider_defect"
        )
        evidence.append({
            "id": evidence_id,
            "source": "code_review",
            "producer": producer,
            "task_id": task_id,
            "item_key": key,
            "artifact_path": artifact_path,
            "artifact_hash": artifact_hash,
            "content_hash": content_hash,
            "summary": summary,
            "observed": observed,
            "expected": expected,
            "reproduction": str(item.get("reproduction") or item.get("repro") or "").strip() or None,
            "files": list(files),
            "requirement_ids": [],
            "issue_key": item.get("issue_key"),
            "commit": commit,
            "verdict": verdict,
            "severity": severity,
            "confidence": "interpreted",
            "attempt_id": attempt_id,
            "diff_hash": diff_hash,
            "recommended_action": recommended,
        })
    return evidence


def _diagnose_evidence(
    *, payload: dict[str, Any], artifact_path: str, content_hash: str,
    artifact_hash: str, attempt_id: str | None = None,
    commit: str | None = None, diff_hash: str | None = None,
) -> list[dict[str, Any]]:
    task_id = str(payload.get("task") or payload.get("task_id") or "") or None
    evidence: list[dict[str, Any]] = []
    for class_entry in payload.get("classes") or []:
        if not isinstance(class_entry, dict):
            continue
        class_id = str(class_entry.get("id") or "unknown")
        for occurrence, signal in enumerate(class_entry.get("signals") or []):
            if not isinstance(signal, dict):
                continue
            key = f"{class_id}:{_digest(signal)[:20]}:{occurrence}"
            evidence.append({
                "id": _digest(["diagnose", task_id, key, content_hash]),
                "source": "diagnose",
                "producer": "diagnose",
                "task_id": task_id,
                "item_key": key,
                "artifact_path": artifact_path,
                "artifact_hash": artifact_hash,
                "content_hash": content_hash,
                "summary": str(signal.get("observed") or class_entry.get("failureMode") or class_entry.get("title") or "Diagnose signal"),
                "observed": None,
                "expected": None,
                "reproduction": None,
                "files": [str(value) for value in signal.get("where") or []],
                "requirement_ids": [],
                "issue_key": signal.get("issue_key"),
                "commit": commit,
                "verdict": str(class_entry.get("plausible") or "undecided"),
                "severity": None,
                "confidence": "unjudged",
                "attempt_id": attempt_id,
                "diff_hash": diff_hash,
                "recommended_action": "investigate",
            })
    return evidence


def _relative(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except (OSError, ValueError):
        return str(path)


def _read_bounded(path: Path, root: Path | None = None) -> bytes:
    if root is not None:
        try:
            path.resolve().relative_to(root.resolve())
        except (OSError, ValueError) as exc:
            raise ValueError("artifact path escapes the project root") from exc
    if path.stat().st_size > MAX_ARTIFACT_BYTES:
        raise ValueError("artifact exceeds 1 MiB")
    return path.read_bytes()


def _read_json(path: Path, root: Path | None = None) -> Any:
    return json.loads(_read_bounded(path, root).decode("utf-8"))


def _read_yaml(path: Path, root: Path | None = None) -> Any:
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise ValueError("PyYAML is required to read Diagnose evidence") from exc
    return yaml.safe_load(_read_bounded(path, root).decode("utf-8"))


def _load_history(feature_dir: Path) -> tuple[dict[str, Any], list[str]]:
    path = feature_dir / "findings.json"
    if not path.exists():
        return {"schema_version": 1, "revision": 0, "groups": {}, "group_history": [], "decisions": [], "rework": {}}, []
    try:
        value = _read_json(path)
        if not isinstance(value, dict) or value.get("schema_version") != 1:
            raise ValueError("unsupported findings schema")
        value.setdefault("revision", 0)
        value.setdefault("groups", {})
        value.setdefault("group_history", [])
        value.setdefault("decisions", [])
        value.setdefault("rework", {})
        return value, []
    except Exception as exc:
        return {"schema_version": 1, "revision": 0, "groups": {}, "group_history": [], "decisions": [], "rework": {}}, [f"findings.json is unreadable: {exc}"]


def _artifact_evidence(
    paths: Any, feature: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[tuple[str, str | None], dict[str, Any]], list[str]]:
    root = Path(paths.root)
    shared = Path(paths.feature_shared(feature))
    local = Path(paths.feature_local(feature))
    evidence: list[dict[str, Any]] = []
    historical: list[dict[str, Any]] = []
    latest_states: dict[tuple[str, str | None], dict[str, Any]] = {}
    warnings: list[str] = []
    archived_keys: set[tuple[str, str | None]] = set()

    archive_dir = shared / "evidence"
    archive_candidates: dict[tuple[str, str | None], list[tuple[int, Path, dict[str, Any]]]] = {}
    for path in sorted(archive_dir.glob("*/*/*.json")) if archive_dir.is_dir() else []:
        try:
            archive = _read_json(path, root)
            if not isinstance(archive, dict) or archive.get("schema_version") != 1:
                raise ValueError("unsupported schema")
            producer = str(archive.get("producer") or "")
            task_id = str(archive.get("task_id")) if archive.get("task_id") is not None else None
            sequence = int(archive.get("sequence") or 0)
            archive_candidates.setdefault((producer, task_id), []).append((sequence, path, archive))
        except Exception as exc:
            warnings.append(f"Could not read {_relative(root, path)}: {exc}")

    for key, candidates in archive_candidates.items():
        producer, task_id = key
        archived_keys.add(key)
        greatest = max(item[0] for item in candidates)
        latest = [item for item in candidates if item[0] == greatest]
        if len(latest) != 1:
            warnings.append(
                f"Conflicting evidence sequence {greatest} for {producer}/{task_id or '_feature'}"
            )
            continue
        selected_path = latest[0][1]
        for _, path, archive in candidates:
            try:
                artifact_hash = hashlib.sha256(_read_bounded(path, root)).hexdigest()
                content_hash = str(archive.get("content_hash") or artifact_hash)
                common = dict(
                    artifact_path=_relative(root, path), content_hash=content_hash,
                    artifact_hash=artifact_hash, attempt_id=archive.get("attempt_id"),
                    commit=archive.get("commit"), diff_hash=archive.get("diff_hash"),
                )
                payload = archive.get("payload") or {}
                normalized: list[dict[str, Any]] = []
                stored_items = archive.get("items")
                if isinstance(stored_items, list):
                    for stored in stored_items:
                        if not isinstance(stored, dict) or not all(stored.get(field) for field in ("id", "producer", "item_key")):
                            raise ValueError("archive items are malformed")
                        normalized.append({**stored, **common})
                elif producer == "diagnose":
                    normalized = _diagnose_evidence(payload=payload, **common)
                elif producer in {"structured_review", "clean_review"} and isinstance(payload, dict):
                    normalized = _review_evidence(payload=payload, producer=producer, task_id=task_id, **common)
                if path == selected_path:
                    evidence.extend(normalized)
                    latest_states[key] = {"verdict": payload.get("verdict"), "artifact_path": _relative(root, path)}
                else:
                    historical.extend(normalized)
            except Exception as exc:
                warnings.append(f"Could not normalize {_relative(root, path)}: {exc}")

    # Legacy/current compatibility artifacts remain readable.  Once an archive
    # exists for a producer/task, do not double count its compatibility file.
    diagnose = shared / "risk-surface.yaml"
    if diagnose.is_file() and not any(key[0] == "diagnose" for key in archived_keys):
        try:
            raw = _read_bounded(diagnose, root)
            payload = _read_yaml(diagnose, root)
            if isinstance(payload, dict):
                digest = hashlib.sha256(raw).hexdigest()
                evidence.extend(_diagnose_evidence(
                    payload=payload, artifact_path=_relative(root, diagnose),
                    content_hash=digest, artifact_hash=digest,
                ))
                latest_states[("diagnose", str(payload.get("task")) if payload.get("task") is not None else None)] = {
                    "verdict": None, "artifact_path": _relative(root, diagnose),
                }
        except Exception as exc:
            warnings.append(f"Could not read {_relative(root, diagnose)}: {exc}")

    review_paths = list((local / "logs").glob("review-*.json")) if (local / "logs").is_dir() else []
    for path in sorted(review_paths):
        task_match = re.fullmatch(r"review-(.+)\.json", path.name)
        if not task_match or path.name == "review-nits.json":
            continue
        task_id = task_match.group(1)
        if ("structured_review", task_id) in archived_keys:
            continue
        try:
            raw = _read_bounded(path, root)
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("review JSON must be an object")
            digest = hashlib.sha256(raw).hexdigest()
            evidence.extend(_review_evidence(
                payload=payload, producer="structured_review", task_id=task_id,
                artifact_path=_relative(root, path), content_hash=digest,
                artifact_hash=digest,
            ))
            latest_states[("structured_review", task_id)] = {
                "verdict": payload.get("verdict"), "artifact_path": _relative(root, path),
            }
        except Exception as exc:
            warnings.append(f"Could not read {_relative(root, path)}: {exc}")

    clean_dir = shared / "reviews"
    for path in sorted(clean_dir.glob("task-*.review")) if clean_dir.is_dir() else []:
        task_id = path.name.removeprefix("task-").removesuffix(".review")
        if ("clean_review", task_id) in archived_keys:
            continue
        try:
            raw = _read_bounded(path, root)
            digest = hashlib.sha256(raw).hexdigest()
            text = raw.decode("utf-8")
            payload = parse_clean_review_payload(text, legacy=True)
            evidence.extend(_review_evidence(
                payload=payload, producer="clean_review", task_id=task_id,
                artifact_path=_relative(root, path), content_hash=digest,
                artifact_hash=digest,
            ))
            latest_states[("clean_review", task_id)] = {
                "verdict": payload.get("verdict"), "artifact_path": _relative(root, path),
            }
        except Exception as exc:
            warnings.append(f"Could not read {_relative(root, path)}: {exc}")
    return evidence, historical, latest_states, warnings


def _resolution(decision: dict[str, Any] | None, rework: dict[str, Any]) -> str:
    if not decision:
        return "unresolved"
    if decision.get("event_kind") == "evidence_attachment" and decision.get("defect_slug"):
        return "filed"
    action = decision.get("action")
    if action == "fix_in_feature":
        status = (rework.get(decision.get("id")) or {}).get("status", "queued")
        return {"queued": "rework_queued", "applied": "rework_applied", "blocked": "rework_blocked"}.get(status, "rework_queued")
    return {
        "create_defect": "filed",
        "needs_verification": "needs_verification",
        "accept_defer": "accepted_deferred",
        "false_positive": "false_positive",
        "duplicate": "duplicate",
    }.get(str(action), "unresolved")


def _decision_is_visible(paths: Any, decision: dict[str, Any]) -> bool:
    needs_receipt = decision.get("action") == "create_defect" \
        or decision.get("event_kind") == "evidence_attachment"
    if not needs_receipt:
        return True
    request_id = str(decision.get("id") or "")
    try:
        uuid.UUID(request_id)
    except ValueError:
        return False
    manifest_path = Path(paths.defects_dir) / ".intake" / request_id / "manifest.json"
    try:
        manifest = _read_json(manifest_path, Path(paths.root))
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    return isinstance(manifest, dict) and manifest.get("phase") == "committed"


def _read_findings_once(paths: Any, feature: str) -> dict[str, Any]:
    if not _FEATURE_RE.fullmatch(feature):
        raise FindingError("INVALID_INPUT", "Feature name is invalid", "featureName")
    shared = Path(paths.feature_shared(feature))
    evidence, historical_evidence, latest_states, warnings = _artifact_evidence(paths, feature)
    history, history_warnings = _load_history(shared)
    warnings.extend(history_warnings)
    by_identity = {f"{item['producer']}:{item.get('task_id') or '_feature'}:{item['item_key']}": item for item in evidence}
    grouped_ids: set[str] = set()
    groups: list[tuple[str, list[dict[str, Any]]]] = []
    for finding_id, identities in (history.get("groups") or {}).items():
        members = [by_identity[value] for value in identities if value in by_identity]
        if members:
            groups.append((str(finding_id), members))
            grouped_ids.update(member["id"] for member in members)

    issue_groups: dict[str, list[dict[str, Any]]] = {}
    for item in evidence:
        if item["id"] in grouped_ids:
            continue
        issue_key = item.get("issue_key")
        key = f"issue:{issue_key}" if issue_key else f"identity:{item['producer']}:{item.get('task_id') or '_feature'}:{item['item_key']}"
        issue_groups.setdefault(key, []).append(item)
    for key, members in issue_groups.items():
        groups.append((f"finding-{_digest([feature, key])[:16]}", members))

    decisions = history.get("decisions") or []
    present_group_ids = {finding_id for finding_id, _ in groups}
    historical_by_id = {item["id"]: item for item in historical_evidence}
    for decision in decisions:
        finding_id = str(decision.get("finding_id") or "")
        if not finding_id or finding_id in present_group_ids:
            continue
        members = [historical_by_id[value] for value in decision.get("evidence_ids") or [] if value in historical_by_id]
        if members:
            groups.append((finding_id, members))
            present_group_ids.add(finding_id)
    findings: list[dict[str, Any]] = []
    for finding_id, members in groups:
        evidence_ids = sorted(member["id"] for member in members)
        revision = _digest(evidence_ids)
        applicable = [d for d in decisions if d.get("finding_id") == finding_id]
        visible = [decision for decision in applicable if _decision_is_visible(paths, decision)]
        if len(visible) != len(applicable):
            warnings.append(f"Finding {finding_id} has an incomplete intake transaction; repair required")
        latest = visible[-1] if visible else None
        active_ids = {item["id"] for item in evidence}
        retired = not any(item["id"] in active_ids for item in members)
        stale = bool(latest and (sorted(latest.get("evidence_ids") or []) != evidence_ids or retired))
        recommendation_order = {"fix_in_feature": 0, "fix_scope": 1, "investigate": 2, "consider_defect": 3}
        recommendation = min(
            (str(member.get("recommended_action") or "investigate") for member in members),
            key=lambda value: recommendation_order.get(value, 9),
        )
        resolution = "unresolved" if stale else _resolution(latest, history.get("rework") or {})
        if retired and latest and latest.get("action") == "fix_in_feature":
            task_id = str(latest.get("task_id") or "") or None
            approved_source = any(
                state.get("verdict") == "approve"
                for (producer, source_task), state in latest_states.items()
                if source_task == task_id and producer in {"structured_review", "clean_review"}
            )
            task_state = None
            if task_id:
                task_path = Path(paths.feature_shared(feature)) / "tasks" / f"{task_id}.json"
                try:
                    value = _read_json(task_path)
                    task_state = value if isinstance(value, dict) else None
                except (OSError, ValueError, json.JSONDecodeError):
                    task_state = None
            if approved_source and task_state and task_state.get("review_verdict") == "approve":
                stale = False
                resolution = "resolved_by_rework"
            else:
                resolution = _resolution(latest, history.get("rework") or {})
        linked_defect_slug = latest.get("defect_slug") if latest else None
        allowed_actions = [
            "fix_in_feature", "create_defect", "needs_verification",
            "accept_defer", "false_positive", "duplicate",
        ]
        if stale and linked_defect_slug:
            allowed_actions.remove("create_defect")
        finding = {
            "id": finding_id,
            "revision": revision,
            "title": members[0]["summary"],
            "evidence": members,
            "decision_id": latest.get("id") if latest else None,
            "history": applicable,
            "stale": stale,
            "resolution": resolution,
            "recommended_action": recommendation,
            "allowed_actions": allowed_actions,
            "linked_defect_slug": linked_defect_slug,
        }
        findings.append(finding)
    findings.sort(key=lambda item: (item["resolution"] != "unresolved", item["title"].casefold(), item["id"]))
    return {
        "schema_version": 1,
        "feature": feature,
        "decision_revision": int(history.get("revision") or 0),
        "findings": findings,
        "warnings": warnings,
    }


def _read_revision_token(paths: Any, feature: str) -> tuple[tuple[str, int, int, int], ...]:
    shared = Path(paths.feature_shared(feature))
    local = Path(paths.feature_local(feature))
    candidates: set[Path] = set()
    for pattern in ("evidence/*/*/*.json", "reviews/task-*.review", "tasks/*.json"):
        candidates.update(shared.glob(pattern))
    candidates.update((local / "logs").glob("review-*.json") if (local / "logs").is_dir() else [])
    candidates.update(
        path for path in (
            shared / "risk-surface.yaml", shared / "findings.json",
        ) if path.exists() or path.is_symlink()
    )
    intake = Path(paths.defects_dir) / ".intake"
    candidates.update(intake.glob("*/manifest.json") if intake.is_dir() else [])
    token: list[tuple[str, int, int, int]] = []
    for path in candidates:
        try:
            stat = path.lstat()
            token.append((str(path), stat.st_mtime_ns, stat.st_size, stat.st_ino))
        except OSError:
            token.append((str(path), -1, -1, -1))
    return tuple(sorted(token))


def read_findings(paths: Any, feature: str) -> dict[str, Any]:
    """Assemble a no-write view from one stable filesystem revision."""
    if not _FEATURE_RE.fullmatch(feature):
        raise FindingError("INVALID_INPUT", "Feature name is invalid", "featureName")
    for _ in range(3):
        before = _read_revision_token(paths, feature)
        view = _read_findings_once(paths, feature)
        if before == _read_revision_token(paths, feature):
            return view
    raise FindingError("BUSY", "Finding evidence changed while it was being read; retry shortly")


def read_evidence_file(
    paths: Any, feature: str, finding_id: str, evidence_id: str, source_path: str,
) -> dict[str, Any]:
    """Read a bounded source excerpt only when the evidence declares the exact path."""
    root = Path(paths.root).resolve()
    view = read_findings(paths, feature)
    finding = _find(view, finding_id)
    evidence = next((item for item in finding["evidence"] if item["id"] == evidence_id), None)
    if evidence is None:
        raise FindingError("NOT_FOUND", "Evidence was not found", "evidenceId")
    if source_path not in evidence.get("files", []):
        raise FindingError("INVALID_INPUT", "Path is not declared by this evidence", "sourcePath")

    match = re.fullmatch(r"(.+?)(?::(\d+))?(?::(\d+))?", source_path)
    relative = (match.group(1) if match else source_path).strip()
    line = int(match.group(2)) if match and match.group(2) else None
    relative_path = Path(relative)
    if relative_path.is_absolute() or not relative or relative_path.name.startswith(".env"):
        raise FindingError("INVALID_INPUT", "Evidence source path is not viewable", "sourcePath")
    try:
        candidate = (root / relative_path).resolve(strict=True)
        candidate.relative_to(root)
    except FileNotFoundError as exc:
        raise FindingError("NOT_FOUND", "Evidence source file does not exist", "sourcePath") from exc
    except (OSError, ValueError) as exc:
        raise FindingError("INVALID_INPUT", "Evidence source path escapes the project", "sourcePath") from exc
    if not candidate.is_file() or ".git" in relative_path.parts:
        raise FindingError("INVALID_INPUT", "Evidence source path is not viewable", "sourcePath")
    try:
        if candidate.stat().st_size > MAX_ARTIFACT_BYTES:
            raise FindingError("INVALID_INPUT", "Evidence source file exceeds 1 MiB", "sourcePath")
        lines = candidate.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise FindingError("INVALID_INPUT", "Evidence source file is not UTF-8 text", "sourcePath") from exc
    except OSError as exc:
        raise FindingError("NOT_FOUND", f"Evidence source file could not be read: {exc}", "sourcePath") from exc

    if line is not None:
        start = max(1, line - 20)
        end = min(len(lines), line + 20)
        highlight = line if 1 <= line <= len(lines) else None
    else:
        start = 1
        end = min(len(lines), 200)
        highlight = None
    return {
        "path": source_path, "content": "\n".join(lines[start - 1:end]),
        "start_line": start, "end_line": end, "highlight_line": highlight,
        "truncated": start > 1 or end < len(lines),
    }


def _find(view: dict[str, Any], finding_id: str) -> dict[str, Any]:
    for finding in view["findings"]:
        if finding["id"] == finding_id:
            return finding
    raise FindingError("NOT_FOUND", "Finding was not found", "findingId")


def record_decision(
    paths: Any, feature: str, decision_revision: int, finding_revision: str,
    input: dict[str, Any], actor: tuple[str, str],
) -> dict[str, Any]:
    action = str(input.get("action") or "")
    if action not in {"fix_in_feature", "needs_verification", "accept_defer", "false_positive", "duplicate"}:
        raise FindingError("INVALID_INPUT", "Unsupported decision action", "action")
    rationale = str(input.get("rationale") or "").strip()
    if action not in {"false_positive", "duplicate"} and not rationale:
        raise FindingError("INVALID_INPUT", "Rationale is required", "rationale")
    task_id = str(input.get("task_id") or "")
    if action == "fix_in_feature":
        if not task_id or not (Path(paths.feature_shared(feature)) / "tasks" / f"{task_id}.json").is_file():
            raise FindingError("INVALID_INPUT", "Choose an existing task in this feature", "taskId")
    if action == "duplicate" and not str(input.get("duplicate_target") or "").strip():
        raise FindingError("INVALID_INPUT", "Choose an existing finding or defect", "duplicateTarget")
    request_id = str(input.get("request_id") or "")
    try:
        uuid.UUID(request_id)
    except ValueError as exc:
        raise FindingError("INVALID_INPUT", "requestId must be a UUID", "requestId") from exc
    with intake_lock(Path(paths.defects_dir)):
        view = read_findings(paths, feature)
        finding = _find(view, str(input.get("finding_id") or ""))
        history, warnings = _load_history(Path(paths.feature_shared(feature)))
        if warnings:
            raise FindingError("REPAIR_REQUIRED", warnings[0])
        body_digest = _digest({**input, "actor": actor})
        for decision in history["decisions"]:
            if decision.get("id") == request_id:
                if decision.get("body_digest") == body_digest:
                    return decision
                raise FindingError("REQUEST_CONFLICT", "requestId was already used with different input")
        if decision_revision != view["decision_revision"]:
            raise FindingError("STALE_DECISION", "Finding decisions changed; refresh and try again")
        if finding_revision != finding["revision"]:
            raise FindingError("STALE_EVIDENCE", "Finding evidence changed; refresh and try again")
        if action == "duplicate":
            target = str(input.get("duplicate_target") or "").strip()
            if target == finding["id"]:
                raise FindingError("INVALID_INPUT", "A finding cannot duplicate itself", "duplicateTarget")
            finding_ids = {item["id"] for item in view["findings"]}
            defect_exists = (
                (Path(paths.defects_dir) / target / "state.json").is_file()
                or (Path(paths.root) / "specs" / "defects" / f"{target}.md").is_file()
            )
            if target not in finding_ids and not defect_exists:
                raise FindingError("INVALID_INPUT", "Duplicate target was not found", "duplicateTarget")
            links = {
                str(item.get("finding_id")): str(item.get("duplicate_target"))
                for item in history["decisions"] if item.get("action") == "duplicate"
            }
            cursor = target
            visited = {finding["id"]}
            while cursor in links:
                if cursor in visited:
                    raise FindingError("INVALID_INPUT", "Duplicate link would create a cycle", "duplicateTarget")
                visited.add(cursor)
                cursor = links[cursor]
        archive_legacy_evidence(paths, feature, finding["evidence"])
        archived_view = read_findings(paths, feature)
        archived_finding = _find(archived_view, finding["id"])
        if archived_finding["revision"] != finding_revision:
            raise FindingError("STALE_EVIDENCE", "Evidence changed while it was archived; refresh and try again")
        finding = archived_finding
        decision = {
            "id": request_id,
            "event_kind": "disposition",
            "finding_id": finding["id"],
            "evidence_ids": sorted(item["id"] for item in finding["evidence"]),
            "action": action,
            "rationale": rationale,
            "actor_name": actor[0],
            "actor_email": actor[1],
            "at": _utc_now(),
            "task_id": task_id or None,
            "defect_slug": input.get("defect_slug"),
            "duplicate_target": input.get("duplicate_target"),
            "body_digest": body_digest,
        }
        history["decisions"].append(decision)
        history["revision"] = int(history["revision"]) + 1
        if action == "fix_in_feature":
            history["rework"][request_id] = {"task_id": task_id, "status": "queued", "error": None}
        _atomic_json(Path(paths.feature_shared(feature)) / "findings.json", history)
        return decision


def group_findings(
    paths: Any, feature: str, decision_revision: int,
    memberships: dict[str, list[str]], rationale: str,
    actor: tuple[str, str], request_id: str,
) -> dict[str, Any]:
    if not rationale.strip():
        raise FindingError("INVALID_INPUT", "Grouping rationale is required", "rationale")
    try:
        uuid.UUID(request_id)
    except ValueError as exc:
        raise FindingError("INVALID_INPUT", "requestId must be a UUID", "requestId") from exc
    with intake_lock(Path(paths.defects_dir)):
        history, warnings = _load_history(Path(paths.feature_shared(feature)))
        if warnings:
            raise FindingError("REPAIR_REQUIRED", warnings[0])
        body_digest = _digest({"memberships": memberships, "rationale": rationale, "actor": actor})
        for event in history["group_history"]:
            if event.get("id") == request_id:
                if event.get("body_digest") == body_digest:
                    return read_findings(paths, feature)
                raise FindingError("REQUEST_CONFLICT", "requestId was already used with different grouping input")
        view = read_findings(paths, feature)
        if view["decision_revision"] != decision_revision:
            raise FindingError("STALE_DECISION", "Finding groups changed; refresh and try again")
        identities = {
            f"{e['producer']}:{e.get('task_id') or '_feature'}:{e['item_key']}"
            for finding in view["findings"] for e in finding["evidence"]
        }
        flattened = [value for values in memberships.values() for value in values]
        if len(flattened) != len(set(flattened)) or set(flattened) != identities:
            raise FindingError("INVALID_INPUT", "Every group member must exist and belong to one group")
        filed_finding_ids = {
            str(decision.get("finding_id")) for decision in history["decisions"]
            if decision.get("action") == "create_defect" and decision.get("defect_slug")
        }
        missing_filed_group = filed_finding_ids.difference(memberships)
        if missing_filed_group:
            raise FindingError(
                "INVALID_INPUT",
                "A filed finding must retain its ID when findings are merged or split",
                "memberships",
            )
        archive_legacy_evidence(paths, feature, [
            evidence for finding in view["findings"] for evidence in finding["evidence"]
        ])
        previous = history["groups"]
        history["groups"] = memberships
        history["group_history"].append({
            "id": request_id, "previous": previous, "groups": memberships,
            "rationale": rationale, "actor_name": actor[0], "actor_email": actor[1], "at": _utc_now(),
            "body_digest": body_digest,
        })
        history["revision"] = int(history["revision"]) + 1
        _atomic_json(Path(paths.feature_shared(feature)) / "findings.json", history)
    return read_findings(paths, feature)


def _publish_attempt_locked(
    paths: Any, feature: str, producer: str, task_id: str | None,
    payload: dict[str, Any], content_hash: str | None = None,
    commit: str | None = None, diff_hash: str | None = None,
    source_event_log: str | None = None,
) -> Path:
    if producer not in {"diagnose", "structured_review", "clean_review"}:
        raise FindingError("INVALID_INPUT", "Unsupported evidence producer")
    raw_hash = content_hash or _digest(payload)
    attempt_id = str(uuid.uuid4())
    task_part = task_id or "_feature"
    common = {
        "artifact_path": "", "content_hash": raw_hash, "artifact_hash": "",
        "attempt_id": attempt_id, "commit": commit, "diff_hash": diff_hash,
    }
    if producer == "diagnose":
        items = _diagnose_evidence(payload=payload, **common)
    else:
        items = _review_evidence(payload=payload, producer=producer, task_id=task_id, **common)
    redacted_payload, payload_fields = _redact_payload(payload)
    redacted_items: list[dict[str, Any]] = []
    item_fields: list[str] = []
    for index, item in enumerate(items):
        redacted, fields = _redact_payload(item)
        redacted_items.append(redacted)
        item_fields.extend(f"items[{index}].{field}" for field in fields)
    base = Path(paths.feature_shared(feature)) / "evidence" / producer / task_part
    existing: list[int] = []
    for path in base.glob("*.json") if base.is_dir() else []:
        try:
            value = _read_json(path)
            existing.append(int(value.get("sequence") or 0))
        except Exception:
            continue
    archive = {
        "schema_version": 1, "feature": feature, "producer": producer,
        "task_id": task_id, "attempt_id": attempt_id,
        "sequence": max(existing, default=0) + 1,
        "created_at": _utc_now(), "commit": commit, "diff_hash": diff_hash,
        "content_hash": raw_hash, "payload": redacted_payload, "items": redacted_items,
        "source_event_log": source_event_log,
        "redacted_fields": [*(f"payload.{field}" for field in payload_fields), *item_fields],
    }
    path = base / f"{attempt_id}.json"
    _atomic_json(path, archive)
    return path


def publish_attempt(
    paths: Any, feature: str, producer: str, task_id: str | None,
    payload: dict[str, Any], content_hash: str | None = None,
    commit: str | None = None, diff_hash: str | None = None,
    source_event_log: str | None = None,
) -> Path:
    with intake_lock(Path(paths.defects_dir)):
        return _publish_attempt_locked(
            paths, feature, producer, task_id, payload, content_hash, commit, diff_hash,
            source_event_log,
        )


def archive_legacy_evidence(paths: Any, feature: str, evidence: list[dict[str, Any]]) -> None:
    """Freeze compatibility artifacts before a decision depends on them.

    The caller owns ``intake_lock``. Current source commands already publish
    archives, so only evidence without an attempt ID reaches this adapter.
    """
    root = Path(paths.root).resolve()
    pending = {
        (str(item.get("producer")), item.get("task_id"), str(item.get("artifact_path")))
        for item in evidence if not item.get("attempt_id")
    }
    for producer, task_value, relative in sorted(pending, key=lambda item: (item[0], str(item[1]), item[2])):
        source = (root / relative).resolve()
        try:
            source.relative_to(root)
        except ValueError as exc:
            raise FindingError("INVALID_SOURCE", "Evidence path escapes the project root") from exc
        try:
            raw = _read_bounded(source, root)
            if producer == "diagnose":
                payload = _read_yaml(source, root)
            else:
                text = raw.decode("utf-8")
                payload = parse_clean_review_payload(text, legacy=True) if producer == "clean_review" else json.loads(text)
            if not isinstance(payload, dict):
                raise ValueError("evidence root must be an object")
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            raise FindingError("INVALID_SOURCE", f"Could not archive {relative}: {exc}") from exc
        _publish_attempt_locked(
            paths, feature, producer, str(task_value) if task_value is not None else None,
            payload, hashlib.sha256(raw).hexdigest(),
        )
