"""Observation extraction pipeline for SPEED's learning infrastructure.

Reads pipeline artifacts after each feature run, converts them into typed
observations, and stores them in append-only JSONL logs.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

ObservationType = Literal[
    "retry", "reviewer_finding", "human_override", "guardian_verdict",
    "gate_failure", "context_miss", "context_waste", "decomposition_miss",
    "convention_violation", "verify_finding", "coherence_issue",
    "security_finding", "success", "pattern_match", "unattributed_changes",
    "agent_concern", "human_approved",
]

Stage = Literal[
    "developer", "reviewer", "guardian", "verifier", "coherence",
    "security", "context", "architect", "meta", "human",
]

# Base weights per observation type (for synthesis prioritization)
_WEIGHTS: dict[str, float] = {
    "retry": 3.0,
    "reviewer_finding": 1.5,  # overridden to 0.5 if dismissed
    "human_override": 2.5,
    "guardian_verdict": 2.0,
    "gate_failure": 2.0,
    "context_miss": 1.5,
    "context_waste": 0.5,
    "decomposition_miss": 2.0,
    "convention_violation": 1.5,
    "verify_finding": 2.0,
    "coherence_issue": 2.0,
    "security_finding": 1.5,
    "success": 0.5,
    "pattern_match": 2.0,  # varies by severity in practice
    "unattributed_changes": 1.0,
    "agent_concern": 1.0,
    "human_approved": 0.5,
}

_NON_BLOCKING_TYPES = frozenset({
    "agent_concern", "context_miss", "context_waste",
    "decomposition_miss", "success",
})


@dataclass
class Observation:
    """Single observation from the extraction pipeline."""

    id: str                        # "sha256:<hex>" from observation_id()
    feature: str                   # feature name from .speed/features/<name>/
    stage: str                     # pipeline stage that produced the artifact
    task_id: str                   # task identifier, or "*" for feature-level
    timestamp: str                 # ISO 8601 — extraction time, not event time
    observation_type: str          # one of ObservationType
    detail: dict                   # type-specific fields
    weight: float                  # base weight for synthesis prioritization


@dataclass
class ExtractResult:
    """Output of the 10-step extraction pipeline."""

    observations: list[Observation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def by_type(self) -> dict[str, list[Observation]]:
        groups: dict[str, list[Observation]] = {}
        for obs in self.observations:
            groups.setdefault(obs.observation_type, []).append(obs)
        return groups

    def summary(self) -> str:
        counts = {t: len(obs) for t, obs in self.by_type().items()}
        parts = [f"{n} {t}" for t, n in sorted(counts.items(), key=lambda x: -x[1])]
        total = len(self.observations)
        return f"{total} observations ({', '.join(parts)})"


@dataclass
class WriteResult:
    """Output of write_observations()."""

    written: int = 0
    skipped: int = 0
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return f"{self.written} written, {self.skipped} skipped"


# ── ID generation ────────────────────────────────────────────────────

def observation_id(feature: str, task_id: str, stage: str,
                   obs_type: str, detail: dict) -> str:
    """Deterministic content-hash ID for an observation.

    Canonical JSON of detail is combined with the identity fields and
    SHA-256 hashed. Same inputs always produce the same ID.
    """
    canonical = json.dumps(detail, sort_keys=True, separators=(",", ":"))
    payload = f"{feature}\n{task_id}\n{stage}\n{obs_type}\n{canonical}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_obs(feature: str, stage: str, task_id: str,
              obs_type: str, detail: dict,
              weight: float | None = None) -> Observation:
    """Helper to build an Observation with computed ID and timestamp."""
    w = weight if weight is not None else _WEIGHTS.get(obs_type, 1.0)
    return Observation(
        id=observation_id(feature, task_id, stage, obs_type, detail),
        feature=feature,
        stage=stage,
        task_id=task_id,
        timestamp=_now_iso(),
        observation_type=obs_type,
        detail=detail,
        weight=w,
    )


# ── JSONL I/O ────────────────────────────────────────────────────────

def write_observations(observations: list[Observation],
                       output_path: Path) -> WriteResult:
    """Appends observations to a JSONL file, skipping duplicates.

    Creates parent directories if missing. Reads existing IDs before
    appending. Each line is written as compact JSON followed by newline.
    """
    result = WriteResult()

    output_path.parent.mkdir(parents=True, exist_ok=True)

    existing_ids: set[str] = set()
    if output_path.exists():
        with open(output_path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    existing_ids.add(obj["id"])
                except (json.JSONDecodeError, KeyError):
                    result.warnings.append(
                        f"Line {line_num}: unparseable, skipped"
                    )

    new_lines: list[str] = []
    for obs in observations:
        if obs.id in existing_ids:
            result.skipped += 1
            continue
        line = json.dumps(asdict(obs), separators=(",", ":"))
        new_lines.append(line + "\n")
        existing_ids.add(obs.id)
        result.written += 1

    if new_lines:
        fd = os.open(str(output_path),
                     os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            for line in new_lines:
                os.write(fd, line.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)

    return result


# ── Extraction pipeline ─────────────────────────────────────────────

def _read_json(path: Path) -> dict | list | None:
    """Read and parse a JSON or JSONL file. Returns None on failure.

    Review logs are multi-line JSONL where each line contains disjoint
    top-level keys. Merges all lines via dict.update() when the first
    line fails to parse as the entire file.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return None

    # Try standard JSON first
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # Fall back to JSONL merge (disjoint top-level keys)
    merged: dict = {}
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                merged.update(obj)
            else:
                return None  # Non-dict JSONL line — not a merge candidate
        except json.JSONDecodeError:
            return None
    return merged if merged else None


def _load_architect_plan(logs_dir: Path) -> dict | None:
    """Load the task plan from the Architect agent's JSONL output.

    Reads the last line of the newest Architect-*.jsonl file and extracts
    the structured_output field, which contains the task decomposition
    including files_touched per task.
    """
    architect_files = sorted(logs_dir.glob("Architect*.jsonl"))
    if not architect_files:
        return None
    try:
        with open(architect_files[-1], "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
        if not lines:
            return None
        last = json.loads(lines[-1])
        so = last.get("structured_output")
        return so if isinstance(so, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def _duration_seconds(task: dict) -> int | None:
    """Compute wall-clock duration from task timestamps."""
    started = task.get("started_at")
    completed = task.get("completed_at")
    if not started or not completed:
        return None
    try:
        fmt_patterns = [
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%S%z",
        ]
        t_start = t_end = None
        for fmt in fmt_patterns:
            try:
                t_start = datetime.strptime(started, fmt)
                break
            except ValueError:
                continue
        for fmt in fmt_patterns:
            try:
                t_end = datetime.strptime(completed, fmt)
                break
            except ValueError:
                continue
        if t_start and t_end:
            return max(0, int((t_end - t_start).total_seconds()))
    except (ValueError, TypeError):
        pass
    return None


def _get_retry_reason(task: dict) -> str:
    """One-line explanation of why this task was retried."""
    error = task.get("error", "")
    if error:
        return error
    verdict = task.get("review_verdict", "")
    if verdict == "request_changes":
        return "Reviewer requested changes"
    if verdict == "approve" and (task.get("retry_count", 0) or 0) > 0:
        return "Reviewer requested changes (resolved)"
    return "Retried"


def _find_gate_logs(task: dict,
                    logs_dir: Path) -> list[tuple[str, str, str, int]]:
    """Find gate logs within a task's time window.

    Returns list of (gate_name, error_summary, file, line) tuples.
    Gate logs are named gate-{Label}-{epoch}.log (written at lib/gates.sh:190).
    Passing gates contain "All checks passed!" or are empty.
    """
    started = task.get("started_at")
    completed = task.get("completed_at")
    if not started or not completed:
        return []
    try:
        t_start = datetime.fromisoformat(
            started.replace("Z", "+00:00")).timestamp()
        t_end = datetime.fromisoformat(
            completed.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return []

    gate_pattern = re.compile(r"^gate-(.+)-(\d+)\.log$")
    results: list[tuple[str, str, str, int]] = []

    for log_file in logs_dir.glob("gate-*.log"):
        m = gate_pattern.match(log_file.name)
        if not m:
            continue
        gate_name = m.group(1)
        log_epoch = int(m.group(2))
        if not (t_start - 60 <= log_epoch <= t_end + 60):
            continue

        content = log_file.read_text(
            encoding="utf-8", errors="replace").strip()
        if not content or content == "All checks passed!":
            continue

        file_path, line_num = "", 0
        eslint = re.search(
            r"^\s*(/?\S+\.\w+)\s+(\d+):\d+\s+(?:error|warning)\s",
            content, re.MULTILINE)
        if eslint:
            file_path, line_num = eslint.group(1), int(eslint.group(2))
        if not file_path:
            pytest_m = re.search(
                r"^FAILED\s+(\S+\.py)::", content, re.MULTILINE)
            if pytest_m:
                file_path = pytest_m.group(1)

        first_lines = [ln for ln in content.split("\n") if ln.strip()][:5]
        results.append(
            (gate_name, "\n".join(first_lines), file_path, line_num))

    return results


def _step1_task_outcomes(feature: str, tasks_dir: Path, logs_dir: Path,
                         result: ExtractResult) -> dict[str, dict]:
    """Step 1: Read task JSON files, produce retry/gate_failure/agent_concern observations.

    Returns a dict of task_id -> task_data for use by later steps.
    """
    tasks: dict[str, dict] = {}

    if not tasks_dir.is_dir():
        result.warnings.append("No tasks/ directory found")
        return tasks

    for task_file in sorted(tasks_dir.glob("*.json")):
        task = _read_json(task_file)
        if not isinstance(task, dict):
            result.errors.append(f"Malformed task JSON: {task_file.name}")
            continue

        task_id = str(task.get("id", task_file.stem))
        tasks[task_id] = task

        # ── Retry detection ──────────────────────────────────────
        retry_count = task.get("retry_count", 0) or 0
        timeout_count = task.get("timeout_count", 0) or 0
        has_explicit_retry = retry_count > 0
        has_implicit_retry = (
            task.get("review_verdict") == "request_changes"
            and task.get("status") in ("done", "pending")
        )
        if has_explicit_retry or has_implicit_retry:
            if not has_explicit_retry:
                retry_count = 1
            duration = _duration_seconds(task)
            evidence_parts = []
            if has_explicit_retry:
                evidence_parts.append(f"retry_count={retry_count}")
            if has_implicit_retry and not has_explicit_retry:
                evidence_parts.append("review_verdict=request_changes")
            if timeout_count > 0:
                evidence_parts.append(f"timeout_count={timeout_count}")
            detail = {
                "retry_count": retry_count,
                "timeout_count": timeout_count,
                "agent_model": task.get("agent_model", ""),
                "what_happened": _get_retry_reason(task),
                "resolution": f"status={task.get('status', 'unknown')}",
                "files_involved": task.get("files_touched", []),
                "duration_seconds": duration,
                "evidence": ", ".join(evidence_parts),
            }
            result.observations.append(
                _make_obs(feature, "developer", task_id, "retry", detail)
            )

        # ── Gate failure detection ───────────────────────────────
        # Scan gate logs for all tasks. Upstream doesn't reliably set
        # task.error, so we correlate gate logs by timestamp window
        # instead of gating on the error field.
        gate_logs = _find_gate_logs(task, logs_dir)
        for gate_name, error_summary, file_path, line_num in gate_logs:
            detail = {
                "gate": gate_name,
                "error_summary": error_summary[:500],
                "file": file_path,
                "line": line_num,
            }
            result.observations.append(
                _make_obs(feature, "developer", task_id,
                          "gate_failure", detail)
            )

        # ── Agent concerns ───────────────────────────────────────
        for concern in task.get("concerns", []):
            if not isinstance(concern, str) or not concern.strip():
                continue
            detail = {
                "concern": concern[:500],
                "agent_model": task.get("agent_model", ""),
                "task_status": task.get("status", ""),
                "review_verdict": task.get("review_verdict", ""),
                "predictive": task.get("review_verdict") == "request_changes",
            }
            result.observations.append(
                _make_obs(feature, "developer", task_id,
                          "agent_concern", detail)
            )

    return tasks


def _step1_unattributed_changes(feature: str, tasks: dict[str, dict],
                                 feature_dir: Path,
                                 result: ExtractResult) -> None:
    """Compare feature branch commits against task branch commits.

    Emits unattributed_changes if any commits exist on the feature branch
    that aren't reachable from any task branch.
    """
    project_root = feature_dir.parent.parent
    branches = [t.get("branch", "") for t in tasks.values() if t.get("branch")]
    if not branches:
        return

    def _git(*args: str) -> str | None:
        try:
            out = subprocess.run(
                ["git", "-C", str(project_root)] + list(args),
                capture_output=True, text=True, timeout=10,
            )
            return out.stdout.strip() if out.returncode == 0 else None
        except (subprocess.TimeoutExpired, OSError):
            return None

    main = (_git("rev-parse", "--verify", "main")
            or _git("rev-parse", "--verify", "master"))
    if not main:
        result.warnings.append(
            "Could not determine main branch for unattributed changes")
        return

    task_commits: set[str] = set()
    for branch in branches:
        log_out = _git("log", "--format=%H", f"main..{branch}")
        if log_out:
            task_commits.update(log_out.split("\n"))

    feature_branch = f"feature/{feature}"
    log_out = _git("log", "--format=%H", f"main..{feature_branch}")
    if log_out is None:
        log_out = _git("log", "--format=%H", "main..HEAD")
    if log_out is None:
        return

    unattributed = set(log_out.split("\n")) - task_commits - {""}
    if not unattributed:
        return

    files: set[str] = set()
    for sha in unattributed:
        diff_out = _git(
            "diff-tree", "--no-commit-id", "-r", "--name-only", sha)
        if diff_out:
            files.update(diff_out.split("\n"))
    files.discard("")

    detail = {
        "commits": sorted(unattributed),
        "files": sorted(files),
        "reason": (f"{len(unattributed)} commits on feature branch "
                   "not attributed to any task"),
    }
    result.observations.append(
        _make_obs(feature, "developer", "*", "unattributed_changes", detail)
    )


def _step2_review_findings(feature: str, logs_dir: Path,
                            tasks: dict[str, dict],
                            result: ExtractResult,
                            classify_fn=None) -> None:
    """Step 2: Read review JSON files, classify and produce reviewer_finding observations."""
    for task_id in tasks:
        review_path = logs_dir / f"review-{task_id}.json"
        if not review_path.exists():
            continue

        review = _read_json(review_path)
        if not isinstance(review, dict):
            result.warnings.append(f"Malformed review JSON: review-{task_id}.json")
            continue

        issues = review.get("issues", [])
        if not issues:
            continue

        task = tasks[task_id]
        retry_count = task.get("retry_count", 0) or 0
        review_verdict = task.get("review_verdict", "")

        for issue in issues:
            if not isinstance(issue, dict):
                continue

            finding_text = f"{issue.get('message', '')} {issue.get('suggestion', '')}"

            category = "unclassified"
            if classify_fn:
                try:
                    cr = classify_fn(finding_text)
                    category = cr.category
                except Exception:
                    pass

            confirmed = retry_count > 0 or review_verdict == "request_changes"
            led_to_retry = retry_count > 0
            weight = 1.5 if confirmed else 0.5

            detail = {
                "category": category,
                "finding": issue.get("message", ""),
                "confirmed": confirmed,
                "led_to_retry": led_to_retry,
                "severity": issue.get("severity", ""),
                "suggestion": issue.get("suggestion", "")[:500],
                "file": issue.get("file", ""),
                "line": issue.get("line", 0),
            }
            result.observations.append(
                _make_obs(feature, "reviewer", task_id,
                          "reviewer_finding", detail, weight=weight)
            )

        # ── Structured reviewer arrays ──────────────────────────────

        # spec_verification: only non-satisfied items, with evidence
        for item in review.get("spec_verification", []):
            if not isinstance(item, dict):
                continue
            satisfied = item.get("satisfied")
            if satisfied in (True, "true"):
                continue
            finding_text = item.get("spec_quote", item.get("requirement", item.get("description", "")))
            if not finding_text:
                continue
            detail = {
                "category": "spec_alignment",
                "finding": str(finding_text)[:500],
                "confirmed": confirmed,
                "led_to_retry": led_to_retry,
                "severity": "major" if satisfied is False else "minor",
                "suggestion": "",
                "file": "",
                "line": 0,
                "evidence": str(item.get("evidence", ""))[:500],
                "spec_section": item.get("spec_section", item.get("section", "")),
            }
            result.observations.append(
                _make_obs(feature, "reviewer", task_id,
                          "reviewer_finding", detail, weight=1.5)
            )

        # missing_from_spec: requirements the reviewer couldn't verify
        for item in review.get("missing_from_spec", []):
            if isinstance(item, str):
                finding_text = item
            elif isinstance(item, dict):
                finding_text = item.get("description", item.get("spec_quote", item.get("requirement", "")))
            else:
                continue
            if not finding_text:
                continue
            detail = {
                "category": "spec_alignment",
                "finding": str(finding_text)[:500],
                "confirmed": True,
                "led_to_retry": led_to_retry,
                "severity": "minor",
                "suggestion": "",
                "file": "",
                "line": 0,
            }
            result.observations.append(
                _make_obs(feature, "reviewer", task_id,
                          "reviewer_finding", detail, weight=1.5)
            )

        # out_of_scope: work beyond task boundaries
        for item in review.get("out_of_scope", []):
            if isinstance(item, str):
                finding_text = item
                file_path = ""
            elif isinstance(item, dict):
                finding_text = item.get("description", item.get("file", ""))
                file_path = item.get("file", "")
            else:
                continue
            if not finding_text:
                continue
            detail = {
                "category": "scope",
                "finding": str(finding_text)[:500],
                "confirmed": True,
                "led_to_retry": led_to_retry,
                "severity": "minor",
                "suggestion": "",
                "file": file_path,
                "line": item.get("line", 0) if isinstance(item, dict) else 0,
            }
            result.observations.append(
                _make_obs(feature, "reviewer", task_id,
                          "reviewer_finding", detail, weight=1.5)
            )

        # ── Strengths ───────────────────────────────────────────────
        for strength in review.get("strengths", []):
            if isinstance(strength, str):
                text = strength
            elif isinstance(strength, dict):
                text = strength.get("description", strength.get("text", ""))
            else:
                continue
            if not text:
                continue
            detail = {
                "category": "strength",
                "finding": text[:500],
                "confirmed": True,
                "led_to_retry": False,
                "severity": "positive",
                "suggestion": "",
                "file": "",
                "line": 0,
            }
            result.observations.append(
                _make_obs(feature, "reviewer", task_id,
                          "reviewer_finding", detail, weight=0.5)
            )


def _parse_check_type(filename: str) -> str:
    """Extract checkpoint type from guardian filename.

    guardian-pre-plan-1772438901.json     -> "pre-plan"
    guardian-post-review-1772439353.json  -> "post-review"
    guardian-post-integration-1772439500.json -> "post-integration"
    """
    stem = filename.replace("guardian-", "").rsplit("-", 1)[0]
    return stem


def _resolve_task_id(gfile: Path, check_type: str,
                     tasks: dict[str, dict]) -> str:
    """Map a post-review guardian file to its task ID.

    Guardian filenames use epoch seconds: guardian-post-review-1772439353.json.
    Task JSON stores ISO timestamps: reviewed_at, completed_at (set by
    task_set_reviewed() and task completion in lib/tasks.sh).

    Correlates the guardian epoch with the nearest task reviewed_at or
    completed_at timestamp. Returns "*" if no match.
    """
    try:
        guardian_epoch = int(gfile.stem.rsplit("-", 1)[-1])
    except (ValueError, IndexError):
        return "*"

    best_task = "*"
    best_delta = float("inf")
    for task_id, task in tasks.items():
        iso_ts = task.get("reviewed_at") or task.get("completed_at")
        if not iso_ts:
            continue
        try:
            task_epoch = datetime.fromisoformat(
                iso_ts.replace("Z", "+00:00")).timestamp()
        except (ValueError, AttributeError):
            continue
        delta = abs(task_epoch - guardian_epoch)
        if delta < best_delta:
            best_delta = delta
            best_task = task_id
    return best_task


def _step3_guardian_verdicts(feature: str, logs_dir: Path,
                              tasks: dict[str, dict],
                              result: ExtractResult) -> None:
    """Step 3: Extract guardian verdicts from guardian JSON files and task JSON."""

    # Primary source: guardian JSON files
    for gfile in sorted(logs_dir.glob("guardian-*.json")):
        data = _read_json(gfile)
        if not isinstance(data, dict):
            continue

        status = data.get("status", "unknown")
        check_type = _parse_check_type(gfile.name)
        task_id = (_resolve_task_id(gfile, check_type, tasks)
                   if check_type == "post-review" else "*")

        if status in ("flagged", "rejected", "misaligned"):
            behavioral = data.get("behavioral_test", {})
            scope_violations = data.get("scope_violations", [])
            flags = data.get("flags", [])
            diff_impact = data.get("differentiation_impact", {})

            detail = {
                "subtype": "verdict",
                "verdict": status,
                "summary": data.get("summary", ""),
                "behavioral_test": behavioral.get("verdict", ""),
                "behavioral_reasoning": behavioral.get("reasoning", ""),
                "scope_violation_count": len(scope_violations),
                "flag_count": len(flags),
                "differentiation_direction": diff_impact.get("direction", ""),
                "check_type": check_type,
                "source_file": gfile.name,
            }
            result.observations.append(
                _make_obs(feature, "guardian", task_id,
                          "guardian_verdict", detail, weight=1.0)
            )

            for sv in scope_violations:
                if not isinstance(sv, dict):
                    continue
                sv_detail = {
                    "subtype": "scope_violation",
                    "feature_name": sv.get("feature", ""),
                    "maps_to": sv.get("maps_to", ""),
                    "severity": sv.get("severity", ""),
                    "reasoning": sv.get("reasoning", ""),
                    "source_file": gfile.name,
                }
                result.observations.append(
                    _make_obs(feature, "guardian", task_id,
                              "guardian_verdict", sv_detail, weight=2.0)
                )

            for flag in flags:
                if not isinstance(flag, dict):
                    continue
                if flag.get("severity") not in ("warning", "critical"):
                    continue
                flag_detail = {
                    "subtype": "flag",
                    "severity": flag.get("severity", ""),
                    "description": flag.get("description", ""),
                    "vision_reference": flag.get("vision_reference", ""),
                    "recommendation": flag.get("recommendation", ""),
                    "source_file": gfile.name,
                }
                result.observations.append(
                    _make_obs(feature, "guardian", task_id,
                              "guardian_verdict", flag_detail, weight=1.5)
                )

            for pg in data.get("persona_grounding", []):
                if not isinstance(pg, dict):
                    continue
                if pg.get("served") is False:
                    pg_detail = {
                        "subtype": "persona_not_served",
                        "persona": pg.get("persona", ""),
                        "use_case": pg.get("use_case", ""),
                        "source_file": gfile.name,
                    }
                    result.observations.append(
                        _make_obs(feature, "guardian", task_id,
                                  "guardian_verdict", pg_detail, weight=1.0)
                    )

    # Secondary source: task JSON prefix check (for pruned guardian files)
    for task_id, task in tasks.items():
        feedback = task.get("review_feedback", "")
        if not isinstance(feedback, str):
            continue
        if not feedback.startswith("GUARDIAN REJECTED"):
            continue
        summary = feedback.replace(
            "GUARDIAN REJECTED: ", "", 1).replace(
            "GUARDIAN REJECTED:", "", 1).strip()
        detail = {
            "subtype": "verdict",
            "verdict": "rejected",
            "summary": summary,
            "task_final_status": task.get("status", "unknown"),
            "led_to_rerun": task.get("status") == "done",
            "source_file": "task_json",
        }
        result.observations.append(
            _make_obs(feature, "guardian", task_id,
                      "guardian_verdict", detail, weight=1.0)
        )

        if task.get("status") == "done":
            override_detail = {
                "original_rejection": feedback,
                "task_status": "done",
                "review_verdict": task.get("review_verdict", "unknown"),
                "retry_count": task.get("retry_count", 0),
            }
            result.observations.append(
                _make_obs(feature, "human", task_id,
                          "human_override", override_detail)
            )


def _step4_verify_findings(feature: str, verify_json_path: Path | None,
                            result: ExtractResult) -> None:
    """Step 4: Extract verify findings from pre-parsed plan-verification JSON."""
    if not verify_json_path or not verify_json_path.exists():
        result.warnings.append("No plan-verification data available")
        return

    data = _read_json(verify_json_path)
    if not isinstance(data, dict):
        result.warnings.append("Empty or invalid verify JSON")
        return

    # Process spec_requirements with drifted/missing/partial status
    for req in data.get("spec_requirements", []):
        if not isinstance(req, dict):
            continue
        status = req.get("status", "")
        if status in ("drifted", "missing", "partial"):
            if status == "partial":
                finding_type = "partial_requirement"
            elif status == "drifted":
                finding_type = "spec_drift"
            else:
                finding_type = "missing_requirement"

            detail = {
                "finding_type": finding_type,
                "requirement": req.get("requirement", req.get("spec_quote", "")),
                "status": status,
                "spec_location": req.get("spec_section", ""),
                "analysis": req.get("notes", req.get("evidence", "")),
                "uncertain": req.get("uncertain", False),
            }
            result.observations.append(
                _make_obs(feature, "verifier", "*",
                          "verify_finding", detail,
                          weight=1.0 if status == "partial" else None)
            )

    # Process critical_failures
    for failure in data.get("critical_failures", []):
        if isinstance(failure, str):
            detail = {
                "finding_type": "critical_failure",
                "requirement": failure,
                "status": "failed",
                "spec_location": "",
                "analysis": "",
            }
        elif isinstance(failure, dict):
            detail = {
                "finding_type": "critical_failure",
                "requirement": failure.get("requirement", failure.get("description", "")),
                "status": "failed",
                "spec_location": failure.get("spec_section", ""),
                "analysis": failure.get("analysis", failure.get("evidence", "")),
            }
        else:
            continue
        result.observations.append(
            _make_obs(feature, "verifier", "*",
                      "verify_finding", detail)
        )

    # Process semantic_drift
    for drift in data.get("semantic_drift", []):
        if not isinstance(drift, dict):
            continue
        detail = {
            "finding_type": "spec_drift",
            "requirement": drift.get("requirement", drift.get("area", "")),
            "status": "drifted",
            "spec_location": drift.get("spec_section", ""),
            "analysis": drift.get("risk", drift.get("analysis", "")),
        }
        result.observations.append(
            _make_obs(feature, "verifier", "*",
                      "verify_finding", detail)
        )

    # Process recommendations
    for rec in data.get("recommendations", []):
        if not isinstance(rec, str):
            continue
        detail = {
            "finding_type": "recommendation",
            "requirement": rec,
            "status": "suggested",
            "spec_location": "",
            "analysis": "",
        }
        result.observations.append(
            _make_obs(feature, "verifier", "*",
                      "verify_finding", detail, weight=1.0)
        )

    # Process contract_issues
    for issue in data.get("contract_issues", []):
        if not isinstance(issue, dict):
            continue
        detail = {
            "finding_type": "contract_issue",
            "requirement": issue.get("description", ""),
            "status": issue.get("type", "unknown"),
            "spec_location": "",
            "analysis": "",
        }
        result.observations.append(
            _make_obs(feature, "verifier", "*",
                      "verify_finding", detail, weight=1.5)
        )


def _step5_coherence_markdown_fallback(feature: str, raw: str,
                                       result: ExtractResult) -> None:
    """Extract minimal coherence signal from markdown when JSON parse fails."""
    status = "unknown"
    if "**Status: FAIL**" in raw or "Verdict: **FAIL**" in raw:
        status = "fail"
    elif "**Status: PASS**" in raw or "Verdict: **PASS**" in raw:
        status = "pass"

    critical_count = 0
    major_count = 0
    in_critical = False
    in_major = False
    for line in raw.splitlines():
        stripped = line.strip()
        if "Critical Issues" in line or "What blocks" in line:
            in_critical = True
            in_major = False
        elif "Major Issues" in line:
            in_major = True
            in_critical = False
        elif (stripped.startswith("###")
              or (stripped.startswith("##")
                  and "Issues" not in stripped
                  and "blocks" not in stripped.lower())):
            in_critical = False
            in_major = False
        elif (stripped.startswith("|")
              and not stripped.startswith("| #")
              and not stripped.startswith("|--")):
            if in_critical:
                critical_count += 1
            elif in_major:
                major_count += 1
        elif re.match(r'^\d+\.\s', stripped):
            if in_critical:
                critical_count += 1
            elif in_major:
                major_count += 1

    if status == "unknown" and critical_count == 0 and major_count == 0:
        result.warnings.append("Coherence output is non-JSON and unparseable")
        return

    detail = {
        "issue_type": "markdown_summary",
        "description": (f"Coherence checker produced markdown instead of JSON. "
                        f"Status: {status}, {critical_count} critical, "
                        f"{major_count} major issues detected."),
        "severity": "critical" if status == "fail" else "info",
        "critical_count": critical_count,
        "major_count": major_count,
        "status": status,
    }
    weight = 2.5 if status == "fail" else 1.0
    result.observations.append(
        _make_obs(feature, "coherence", "*",
                  "coherence_issue", detail, weight=weight)
    )
    result.warnings.append(
        "Coherence output was markdown, not JSON. Only summary extracted."
    )


def _step5_coherence_issues(feature: str, coherence_json_path: Path | None,
                              result: ExtractResult) -> None:
    """Step 5: Extract coherence issues from pre-parsed coherence JSON."""
    if not coherence_json_path or not coherence_json_path.exists():
        result.warnings.append("No coherence data available")
        return

    data = _read_json(coherence_json_path)
    if not isinstance(data, dict):
        raw = coherence_json_path.read_text().strip()
        if raw:
            _step5_coherence_markdown_fallback(feature, raw, result)
        else:
            result.warnings.append("Empty or invalid coherence JSON")
        return

    # ── Existing 3 arrays ──
    issue_sources = [
        ("interface_mismatches", "interface_mismatch"),
        ("schema_inconsistencies", "schema_inconsistency"),
        ("missing_connections", "missing_connection"),
    ]

    for json_key, issue_type in issue_sources:
        for item in data.get(json_key, []):
            if not isinstance(item, dict):
                continue
            detail = {
                "issue_type": issue_type,
                "task_a": str(item.get("task_a", item.get("tasks", [""])[0] if isinstance(item.get("tasks"), list) and item.get("tasks") else "")),
                "task_b": str(item.get("task_b", item.get("tasks", ["", ""])[1] if isinstance(item.get("tasks"), list) and len(item.get("tasks", [])) > 1 else "")),
                "location_a": item.get("location_a", item.get("location", "")),
                "location_b": item.get("location_b", ""),
                "description": item.get("description", item.get("issue", "")),
                "severity": item.get("severity", "warning"),
            }
            result.observations.append(
                _make_obs(feature, "coherence", "*",
                          "coherence_issue", detail)
            )

    # ── New: critical_issues ──
    for issue_text in data.get("critical_issues", []):
        if not isinstance(issue_text, str) or not issue_text.strip():
            continue
        detail = {
            "issue_type": "critical_issue",
            "description": issue_text,
            "severity": "critical",
        }
        result.observations.append(
            _make_obs(feature, "coherence", "*",
                      "coherence_issue", detail, weight=2.5)
        )

    # ── New: contract_gaps (only missing/partial) ──
    for gap in data.get("contract_gaps", []):
        if not isinstance(gap, dict):
            continue
        gap_status = gap.get("status", "")
        if gap_status in ("missing", "partial"):
            detail = {
                "issue_type": "contract_gap",
                "description": gap.get("contract_item", ""),
                "status": gap_status,
                "notes": gap.get("notes", ""),
                "severity": "major" if gap_status == "missing" else "minor",
            }
            result.observations.append(
                _make_obs(feature, "coherence", "*",
                          "coherence_issue", detail, weight=2.0)
            )

    # ── New: duplicates ──
    for dup in data.get("duplicates", []):
        if not isinstance(dup, dict):
            continue
        detail = {
            "issue_type": "duplicate",
            "description": dup.get("description", ""),
            "locations": dup.get("locations", []),
            "severity": "major",
        }
        result.observations.append(
            _make_obs(feature, "coherence", "*",
                      "coherence_issue", detail)
        )

    # ── New: recommendations ──
    for rec in data.get("recommendations", []):
        if not isinstance(rec, str) or not rec.strip():
            continue
        detail = {
            "issue_type": "recommendation",
            "description": rec,
            "severity": "info",
        }
        result.observations.append(
            _make_obs(feature, "coherence", "*",
                      "coherence_issue", detail, weight=1.0)
        )


def _step6_security_findings(feature: str, logs_dir: Path,
                               result: ExtractResult) -> None:
    """Step 6: Extract findings from validation-report.json and security-audit.json."""
    all_findings: list[dict] = []

    # Source 1: validation-report.json (from speed plan)
    vr_path = logs_dir / "validation-report.json"
    if vr_path.exists():
        vr_data = _read_json(vr_path)
        if isinstance(vr_data, list):
            all_findings.extend(f for f in vr_data if isinstance(f, dict))
        elif isinstance(vr_data, dict):
            all_findings.extend(
                f for f in vr_data.get("validation", vr_data.get("findings", []))
                if isinstance(f, dict)
            )

    # Source 2: security-audit.json (from speed security / security gate)
    sa_path = logs_dir / "security-audit.json"
    if sa_path.exists():
        sa_data = _read_json(sa_path)
        if isinstance(sa_data, dict):
            all_findings.extend(
                f for f in sa_data.get("validation", sa_data.get("findings", []))
                if isinstance(f, dict)
            )
        elif isinstance(sa_data, list):
            all_findings.extend(f for f in sa_data if isinstance(f, dict))

    if not all_findings:
        if not vr_path.exists() and not sa_path.exists():
            result.warnings.append(
                "No validation-report.json or security-audit.json found")
        else:
            result.warnings.append(
                "Security/validation files exist but contain no findings")
        return

    for i, finding in enumerate(all_findings):
        issue_text = finding.get("issue", "")
        finding_id = f"SEC-{i+1:03d}"
        severity = finding.get("severity", "note")
        title = issue_text

        # Parse "SEC-001 (medium): Title..." pattern from issue text
        sec_match = re.match(r"(SEC-\d+)\s*\((\w+)\):\s*(.*)", issue_text)
        if sec_match:
            finding_id = sec_match.group(1)
            severity = sec_match.group(2)
            title = sec_match.group(3)

        detail = {
            "finding_id": finding_id,
            "severity": severity,
            "title": title[:200] if title else "",
            "recommendation": finding.get("recommendation", ""),
            "product_requirement": finding.get("product_requirement", ""),
        }
        result.observations.append(
            _make_obs(feature, "security", "*",
                      "security_finding", detail)
        )


def _step7_context_effectiveness(feature: str, tasks: dict[str, dict],
                                   context_base: Path | None,
                                   result: ExtractResult) -> None:
    """Step 7: Context effectiveness (code-context.json vs git diff).

    Compares the pre-computed context package for each task against the
    files the developer actually touched.  Emits context_miss (weight 1.5)
    for files touched but not in context, and context_waste (weight 0.5)
    when >90 % of provided files (minimum 6) went unused.

    context_base should point to .speed/context/tasks/.
    """
    if not context_base or not context_base.exists():
        result.warnings.append(
            "Context effectiveness skipped: no context directory found"
        )
        return

    any_found = False
    for task_id, task in tasks.items():
        actual = set(task.get("files_touched", []))
        if not actual:
            continue

        cc_path = context_base / task_id / "context" / "code-context.json"
        if not cc_path.exists():
            continue
        cc = _read_json(cc_path)
        if not isinstance(cc, dict):
            continue

        any_found = True
        provided: set[str] = set()
        tiers: dict[str, str] = {}

        fc = cc.get("full_content", {})
        if isinstance(fc, dict):
            for f in fc.get("files_touched", []):
                p = f.get("path", "") if isinstance(f, dict) else str(f)
                if p:
                    provided.add(p)
                    tiers[p] = "seed"
            oh = fc.get("one_hop", {})
            if isinstance(oh, dict):
                for p in oh:
                    provided.add(p)
                    tiers[p] = "one_hop"
            elif isinstance(oh, list):
                for f in oh:
                    p = f.get("path", "") if isinstance(f, dict) else str(f)
                    if p:
                        provided.add(p)
                        tiers[p] = "one_hop"

        sk = cc.get("skeleton", {})
        if isinstance(sk, dict):
            for tier_val in sk.values():
                if isinstance(tier_val, list):
                    for f in tier_val:
                        p = f.get("path", "") if isinstance(f, dict) else str(f)
                        if p:
                            provided.add(p)
                            tiers[p] = "skeleton"
                elif isinstance(tier_val, dict):
                    for p in tier_val:
                        provided.add(p)
                        tiers[p] = "skeleton"

        if not provided:
            continue

        # Context misses: files touched but not provided
        misses = actual - provided
        for f in sorted(misses):
            result.observations.append(
                _make_obs(feature, "context", task_id, "context_miss", {
                    "file": f,
                    "reason": "Modified by developer but not in context package",
                    "task_files_declared": sorted(provided & actual),
                })
            )

        # Context waste: only when extreme (>90% unused, min 6 provided)
        waste_files = provided - actual
        waste_ratio = len(waste_files) / len(provided) if provided else 0
        summary = cc.get("expansion_summary", {})
        if waste_ratio > 0.9 and len(provided) > 5:
            result.observations.append(
                _make_obs(feature, "context", task_id, "context_waste", {
                    "waste_ratio": round(waste_ratio, 2),
                    "provided_count": len(provided),
                    "used_count": len(provided) - len(waste_files),
                    "total_tokens_estimate": summary.get(
                        "total_tokens_estimate", 0),
                    "reason": (f"{len(waste_files)} of {len(provided)} "
                               "context files unused"),
                })
            )

    if not any_found:
        result.warnings.append(
            "Context effectiveness skipped: "
            "no code-context.json files found for any task"
        )


def _step8_decomposition_quality(feature: str, tasks: dict[str, dict],
                                   plan: dict | None,
                                   result: ExtractResult) -> None:
    """Step 8: Compare planned vs actual files per task."""
    if not plan or not isinstance(plan, dict):
        result.warnings.append(
            "Decomposition quality skipped: no Architect plan found"
        )
        return

    plan_tasks = plan.get("tasks", [])
    plan_by_id: dict[str, list[str]] = {}
    for pt in plan_tasks:
        if isinstance(pt, dict):
            plan_by_id[str(pt.get("id", ""))] = pt.get("files_touched", [])

    for task_id, task in tasks.items():
        if task_id not in plan_by_id:
            continue  # Task not in plan — no comparison possible

        planned = set(plan_by_id[task_id])
        actual = set(task.get("files_touched", []))

        if not planned and not actual:
            continue
        if planned == actual:
            continue

        extras = sorted(actual - planned)
        missing = sorted(planned - actual)

        if not extras and not missing:
            continue

        if missing and extras:
            issue = "boundary_mismatch"
        elif missing:
            issue = "missing_dependency"
        else:
            issue = "scope_too_broad"

        detail = {
            "issue": issue,
            "planned_files": sorted(planned),
            "actual_files": sorted(actual),
            "analysis": f"Task touched {len(actual)} files instead of planned {len(planned)}. "
                        f"Extras: {extras}. Missing: {missing}.",
        }
        result.observations.append(
            _make_obs(feature, "architect", task_id,
                      "decomposition_miss", detail)
        )


def _step9_success_observations(feature: str, tasks: dict[str, dict],
                                  task_issues: set[str],
                                  plan: dict | None,
                                  result: ExtractResult) -> None:
    """Step 9: Record success observations for clean-pass tasks."""
    plan_by_id: dict[str, list[str]] = {}
    if plan and isinstance(plan, dict):
        for pt in plan.get("tasks", []):
            if isinstance(pt, dict):
                plan_by_id[str(pt.get("id", ""))] = pt.get("files_touched", [])

    guardian_status: dict[str, str] = {}
    for obs in result.observations:
        if obs.observation_type == "guardian_verdict" and obs.task_id != "*":
            guardian_status[obs.task_id] = obs.detail.get("verdict", "unknown")

    for task_id, task in tasks.items():
        if task_id in task_issues:
            continue
        if task.get("status") != "done":
            continue

        duration = _duration_seconds(task)
        files_touched = task.get("files_touched", [])
        planned = plan_by_id.get(task_id, [])

        detail = {
            "files_planned": len(planned) if planned else len(files_touched),
            "files_actual": len(files_touched),
            "agent_model": task.get("agent_model", ""),
            "retry_count": 0,
            "guardian": guardian_status.get(task_id, "no_check"),
            "duration_seconds": duration,
        }
        result.observations.append(
            _make_obs(feature, "developer", task_id, "success", detail)
        )


# ── Pattern detection ────────────────────────────────────────────────

def _obs_files_key(obs: Observation) -> tuple[str, ...]:
    """Extract a sorted tuple of files from an observation's detail."""
    files = obs.detail.get("files_involved", obs.detail.get("file", ""))
    if isinstance(files, list):
        return tuple(sorted(files))
    if isinstance(files, str) and files:
        return (files,)
    return ()


def _obs_category(obs: Observation) -> str:
    """Extract category from an observation's detail (fallback chain)."""
    return obs.detail.get("category", obs.detail.get("finding_type",
           obs.detail.get("issue_type", "")))


def _emit_pattern(
    obs_type: str,
    files_key: tuple[str, ...],
    category: str,
    obs_list: list[Observation],
    features_in_group: set[str],
    total_features: set[str],
    feature: str,
    patterns: list[Observation],
) -> None:
    """Build a pattern_match observation and append it to patterns."""
    severity = ("high" if len(features_in_group) >= 5
                else "medium" if len(features_in_group) >= 3 else "low")

    occurrences = [
        {"feature": o.feature, "task_id": o.task_id, "observation_id": o.id}
        for o in obs_list
    ]

    files_desc = ", ".join(files_key) if files_key else "various files"
    pattern_desc = f"{obs_type} on tasks touching {files_desc}"
    if category:
        pattern_desc += f" ({category})"

    detail = {
        "pattern": pattern_desc,
        "occurrences": occurrences,
        "frequency": f"{len(features_in_group)} of last {len(total_features)} features",
        "severity": severity,
    }

    weight = 3.0 if severity == "high" else 2.0 if severity == "medium" else 1.0
    patterns.append(
        _make_obs(feature, "meta", "*", "pattern_match", detail, weight=weight)
    )


def detect_patterns(current: list[Observation], prior_dir: Path,
                    min_features: int = 3) -> list[Observation]:
    """Find recurring patterns across feature runs.

    Two-pass grouping:
      Pass 1 — group by (type, files_key, category) for file-specific patterns.
      Pass 2 — group by (type, category) only, excluding observations already
               matched in Pass 1, for type-level patterns across different files.
    """
    # Collect all observations: prior + current
    all_obs: list[Observation] = list(current)
    total_features: set[str] = set()

    if prior_dir.is_dir():
        for jsonl_file in prior_dir.glob("*.jsonl"):
            try:
                with open(jsonl_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                            total_features.add(obj.get("feature", ""))
                            all_obs.append(Observation(**obj))
                        except (json.JSONDecodeError, TypeError):
                            continue
            except OSError:
                continue

    for obs in current:
        total_features.add(obs.feature)

    if len(total_features) < min_features:
        return []

    feature = current[0].feature if current else "unknown"
    _SKIP_TYPES = frozenset({"pattern_match", "success"})

    # --- Pass 1: file-specific patterns ---
    groups_file: dict[tuple, list[Observation]] = {}
    for obs in all_obs:
        if obs.observation_type in _SKIP_TYPES:
            continue
        key = (obs.observation_type, _obs_files_key(obs), _obs_category(obs))
        groups_file.setdefault(key, []).append(obs)

    patterns: list[Observation] = []
    covered_ids: set[str] = set()

    for key, obs_list in groups_file.items():
        features_in_group = {o.feature for o in obs_list}
        if len(features_in_group) < min_features:
            continue
        obs_type, files_key, category = key
        _emit_pattern(obs_type, files_key, category, obs_list,
                      features_in_group, total_features, feature, patterns)
        covered_ids.update(o.id for o in obs_list)

    # --- Pass 2: type-level patterns (skip already-covered) ---
    groups_type: dict[tuple, list[Observation]] = {}
    for obs in all_obs:
        if obs.observation_type in _SKIP_TYPES:
            continue
        if obs.id in covered_ids:
            continue
        key = (obs.observation_type, _obs_category(obs))
        groups_type.setdefault(key, []).append(obs)

    for key, obs_list in groups_type.items():
        features_in_group = {o.feature for o in obs_list}
        if len(features_in_group) < min_features:
            continue
        obs_type, category = key
        _emit_pattern(obs_type, (), category, obs_list,
                      features_in_group, total_features, feature, patterns)

    return patterns


# ── Main extraction entry point ──────────────────────────────────────

def extract_observations(feature_dir: Path, memory_dir: Path,
                         verify_json_path: Path | None = None,
                         coherence_json_path: Path | None = None,
                         classify_fn=None) -> ExtractResult:
    """Run the 10-step extraction pipeline on a completed feature.

    Args:
        feature_dir: Path to .speed/features/<name>/.
        memory_dir: Path to .speed/memory/.
        verify_json_path: Pre-parsed plan verification JSON (from bash bridge).
        coherence_json_path: Pre-parsed coherence JSON (from bash bridge).
        classify_fn: Optional classification function for review findings.
            Should accept a text string and return an object with .category.

    Never raises. Missing artifacts skip the step (warning). Malformed
    JSON skips the task (error).
    """
    result = ExtractResult()
    feature = feature_dir.name

    tasks_dir = feature_dir / "tasks"
    logs_dir = feature_dir / "logs"

    # Read the Architect's task plan from JSONL output
    plan = _load_architect_plan(logs_dir)

    # Step 1: Task outcomes
    tasks = _step1_task_outcomes(feature, tasks_dir, logs_dir, result)
    _step1_unattributed_changes(feature, tasks, feature_dir, result)

    # Step 2: Review findings
    _step2_review_findings(feature, logs_dir, tasks, result,
                           classify_fn=classify_fn)

    # Step 3: Guardian verdicts
    _step3_guardian_verdicts(feature, logs_dir, tasks, result)

    # Steps 4-6: Verify, coherence, security
    _step4_verify_findings(feature, verify_json_path, result)
    _step5_coherence_issues(feature, coherence_json_path, result)
    _step6_security_findings(feature, logs_dir, result)

    # Step 7: Context effectiveness
    context_base = feature_dir.parent.parent / "context" / "tasks"
    _step7_context_effectiveness(feature, tasks, context_base, result)

    # Step 8: Decomposition quality
    _step8_decomposition_quality(feature, tasks, plan, result)

    # Track which tasks had genuine issues (for Step 9)
    task_issues: set[str] = set()
    for obs in result.observations:
        if obs.task_id == "*":
            continue
        if obs.observation_type in _NON_BLOCKING_TYPES:
            continue
        if obs.observation_type == "reviewer_finding":
            if obs.detail.get("severity", "") in ("nit", "positive"):
                continue
        task_issues.add(obs.task_id)

    # Step 9: Success observations
    _step9_success_observations(feature, tasks, task_issues, plan, result)

    # Step 10: Pattern matching
    obs_dir = memory_dir / "observations"
    patterns = detect_patterns(result.observations, obs_dir)
    result.observations.extend(patterns)

    # Steps 11-14: Human correction signals (lib/learn/human_corrections.py)
    from .human_corrections import (
        step11_retry_guidance, step12_skip_flags,
        step13_forced_approvals, step14_defect_rejections,
    )
    task_dicts = list(tasks.values()) if tasks else []
    result.observations.extend(step11_retry_guidance(task_dicts, feature))
    result.observations.extend(step12_skip_flags(feature_dir, feature))
    result.observations.extend(step13_forced_approvals(
        task_dicts, feature, logs_dir,
    ))
    defects_dir = feature_dir.parent.parent / "defects"
    result.observations.extend(step14_defect_rejections(defects_dir, feature))

    return result
