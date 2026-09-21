"""Landing page panel readers and orchestrator."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .landing_types import (
    EscalationResponseInput,
    EscalationResponseResult,
    LandingCompletedFeature,
    LandingCoverageTrend,
    LandingDecisionItem,
    LandingDefect,
    LandingDefinePanel,
    LandingDraftSpec,
    LandingEscalation,
    LandingEscalationTrend,
    LandingExecutePanel,
    LandingInsight,
    LandingJudgePanel,
    LandingLearnPanel,
    LandingQualityGate,
    LandingRecentFeature,
    LandingRunningFeature,
    LandingView,
)

log = logging.getLogger("speed.dashboard.landing")


_LLM_TIMEOUT_SECONDS = 5
_LLM_MAX_OUTPUT_TOKENS = 150

_NARRATIVE_PROMPT = (
    "You are a project status assistant. Given the following project summary, "
    "write 2-3 sentences describing the current state of this feature review. "
    "Be concise and actionable.\n\n{summary}"
)


# ── Orchestrator ──────────────────────────────────────────────────────────────


def get_landing_view(project_root: Path, conn: Any = None) -> LandingView:
    """Assemble the complete landing view from all panel readers.

    Args:
        project_root: Path to the project root directory.
        conn: Database connection (reserved for future use).
    """
    greeting = _compute_greeting()
    project_name = _read_project_name(project_root)
    branch = _read_branch(project_root)

    define = read_define_panel(project_root)
    judge = read_judge_panel(project_root)
    execute = read_execute_panel(project_root)
    learn = read_learn_panel(project_root)

    # Generate narrative for the most urgent pending feature
    narrative = None
    pending = [f for f in judge.completed_features if f.review_status == "pending"]
    if pending:
        narrative = _generate_narrative_for_feature(pending[0], project_name, execute)
        if narrative:
            pending[0] = LandingCompletedFeature(
                feature=pending[0].feature,
                completed_at=pending[0].completed_at,
                coverage_pct=pending[0].coverage_pct,
                criteria_passed=pending[0].criteria_passed,
                criteria_total=pending[0].criteria_total,
                guardian_verdict=pending[0].guardian_verdict,
                decisions_needed=pending[0].decisions_needed,
                decision_items=pending[0].decision_items,
                review_status=pending[0].review_status,
                summary=narrative,
            )

    return LandingView(
        greeting=greeting,
        project_name=project_name,
        branch=branch,
        narrative=narrative,
        define=define,
        judge=judge,
        execute=execute,
        learn=learn,
    )


def _compute_greeting() -> str:
    """Return a generic greeting. Time-of-day logic deferred to frontend (Phase 2)."""
    return "Good morning"


def _read_project_name(project_root: Path) -> str:
    """Read project name from speed.toml, falling back to directory name."""
    toml_path = project_root / "speed.toml"
    if toml_path.exists():
        try:
            data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
            # Try [project] name first, then top-level name
            project_section = data.get("project", {})
            if isinstance(project_section, dict):
                name = project_section.get("name")
                if name:
                    return str(name)
            name = data.get("name")
            if name:
                return str(name)
        except (OSError, tomllib.TOMLDecodeError):
            pass
    return project_root.name


def _read_branch(project_root: Path) -> str | None:
    """Read current git branch via subprocess. Returns None on failure."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            branch = result.stdout.strip()
            return branch if branch else None
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def _generate_narrative_for_feature(
    feature: LandingCompletedFeature, project_name: str, execute: LandingExecutePanel
) -> str | None:
    """Generate an LLM narrative for a completed feature.

    Calls provider_chat() with a 5-second timeout. Returns None on any failure.
    """
    summary_parts = [
        f"Project: {project_name}",
        f"Feature under review: {feature.feature}",
        f"Coverage: {feature.coverage_pct:.1f}%",
        f"Criteria passed: {feature.criteria_passed}/{feature.criteria_total}",
        f"Guardian verdict: {feature.guardian_verdict}",
        f"Decisions needed: {feature.decisions_needed}",
    ]
    if execute.running_features:
        summary_parts.append(f"Running features: {len(execute.running_features)}")
    if execute.escalations:
        summary_parts.append(f"Open escalations: {len(execute.escalations)}")

    summary_text = "\n".join(summary_parts)
    prompt = _NARRATIVE_PROMPT.format(summary=summary_text)

    if len(prompt) > 4000:
        prompt = prompt[:4000]

    try:
        from .provider import provider_chat  # type: ignore[import-not-found]

        response = provider_chat(
            prompt=prompt,
            max_tokens=_LLM_MAX_OUTPUT_TOKENS,
            timeout=_LLM_TIMEOUT_SECONDS,
        )
        return response if response else None
    except Exception:
        log.debug("LLM narrative generation unavailable or failed", exc_info=True)
        return None


_SEVERITY_ORDER: dict[str, int] = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
_VALID_SEVERITIES = frozenset(_SEVERITY_ORDER)

# Lines starting with these strings are treated as template boilerplate,
# not substantive content, when deciding if overview.md is a placeholder.
_TEMPLATE_MARKERS = ("{{", "<!-- TODO", "[TODO]", "[PLACEHOLDER]", "TODO:", "<!-- FILL")


def read_define_panel(project_root: Path) -> LandingDefinePanel:
    """Compose the Define panel from filesystem artifacts.

    Reads:
      - specs/product/overview.md          (vision status)
      - specs/product/*.md                  (draft specs, excluding overview.md)
      - specs/tech/{name}.md               (technical spec presence per feature)
      - .speed/features/{name}/state.json  (feature planning state)
      - .speed/defects/*/state.json        (defect list)
    """
    defects = _read_defects(project_root)
    return LandingDefinePanel(
        vision_status=_read_vision_status(project_root),
        draft_specs=_read_draft_specs(project_root),
        defects=defects,
        defect_count=len(defects),
    )


# ── Vision status ──────────────────────────────────────────────────────────────


def _read_vision_status(project_root: Path) -> str:
    """Classify the product vision document at specs/product/overview.md.

    Returns:
        "missing"     — file does not exist or cannot be read
        "placeholder" — file is too short (<50 chars) or contains only
                        headings and template boilerplate
        "defined"     — file has substantive non-heading content
    """
    overview = project_root / "specs" / "product" / "overview.md"
    if not overview.exists():
        return "missing"

    try:
        content = overview.read_text(encoding="utf-8").strip()
    except OSError:
        return "missing"

    if len(content) < 50:
        return "placeholder"

    # Classify as placeholder when all non-empty content is structural boilerplate:
    # headings (#) or template marker lines.
    non_empty_lines = [line.strip() for line in content.splitlines() if line.strip()]
    substantive = [
        line
        for line in non_empty_lines
        if not line.startswith("#")
        and not any(line.startswith(marker) for marker in _TEMPLATE_MARKERS)
    ]
    if not substantive:
        return "placeholder"

    return "defined"


# ── Draft specs ────────────────────────────────────────────────────────────────


def _read_draft_specs(project_root: Path) -> list[LandingDraftSpec]:
    """Return specs in the Define stage — product specs not yet in execution.

    Globs specs/product/*.md (excluding overview.md) and checks for companion
    tech/design specs and a .speed/features/{name}/state.json. Features whose
    state is running, done, or completed belong to the Execute/Judge panels and
    are excluded. Features with no state file get status "unplanned"; all others
    get "writing".
    """
    from ..paths import get_paths
    paths = get_paths(project_root)

    product_dir = project_root / "specs" / "product"
    tech_dir = project_root / "specs" / "tech"
    design_dir = project_root / "specs" / "design"

    if not product_dir.is_dir():
        return []

    specs: list[LandingDraftSpec] = []
    for spec_file in sorted(product_dir.glob("*.md")):
        if spec_file.name == "overview.md":
            continue

        name = _feature_name(spec_file)
        spec_stem = spec_file.stem

        spec_types: list[str] = ["product"]
        if tech_dir.is_dir() and (tech_dir / f"{spec_stem}.md").exists():
            spec_types.append("technical")
        if design_dir.is_dir() and (design_dir / f"{spec_stem}.md").exists():
            spec_types.append("design")

        state_file = paths.feature_local(name) / "state.json"
        if not state_file.exists():
            status = "unplanned"
        else:
            state = _read_json(state_file)
            if state is None:
                status = "unplanned"
            elif state.get("status") in ("running", "done", "completed"):
                # Feature is executing or complete; it belongs to Execute/Judge panels.
                continue
            else:
                status = "writing"

        specs.append(LandingDraftSpec(name=name, spec_types=spec_types, status=status))

    return specs


def _feature_name(spec_file: Path) -> str:
    """Derive the feature directory name from a spec filename.

    Feature directories use the full spec stem (e.g. 'speed-dashboard-landing.md'
    maps to '.speed/features/speed-dashboard-landing/').
    """
    return spec_file.stem


# ── Defects ────────────────────────────────────────────────────────────────────


def _read_defects(project_root: Path) -> list[LandingDefect]:
    """Return all known defects, sorted by severity (P0 first).

    Sources:
    - .speed/defects/*/state.json — tracked defects with runtime state (severity
      and name read directly from JSON; unrecognized severity values clamped to P3)
    - specs/defects/*.md — defect specs with no state file yet (severity parsed
      from a "Severity: PX" line in the first 10 lines; defaults to P3)

    Deduplication is by name, with the state.json source taking precedence.
    """
    seen: set[str] = set()
    defects: list[LandingDefect] = []

    # .speed/defects/*/state.json — tracked defects with runtime state
    from ..paths import get_paths
    paths = get_paths(project_root)

    json_dir = paths.defects_dir
    if json_dir.is_dir():
        for state_file in json_dir.glob("*/state.json"):
            data = _read_json(state_file)
            if data is None:
                continue
            severity = data.get("severity", "P3")
            if severity not in _VALID_SEVERITIES:
                severity = "P3"
            name = data.get("name", state_file.parent.name)
            seen.add(name)
            defects.append(LandingDefect(severity=severity, name=name))

    # specs/defects/*.md — defect specs (severity parsed from body)
    specs_dir = project_root / "specs" / "defects"
    if specs_dir.is_dir():
        for md_file in sorted(specs_dir.glob("*.md")):
            name = md_file.stem
            if name in seen:
                continue
            severity = "P3"
            try:
                for line in md_file.read_text(encoding="utf-8").splitlines()[:10]:
                    if line.strip().lower().startswith("severity:"):
                        val = line.split(":", 1)[1].strip().upper()
                        if val in _VALID_SEVERITIES:
                            severity = val
                        break
            except OSError:
                pass
            defects.append(LandingDefect(severity=severity, name=name))

    defects.sort(key=lambda d: _SEVERITY_ORDER.get(d.severity, 3))
    return defects


# ── Judge Panel ────────────────────────────────────────────────────────────────


def read_judge_panel(project_root: Path) -> LandingJudgePanel:
    """Compose the Judge panel from all completed/done features.

    Returns an aggregate view: list of completed features with their
    criteria metrics, guardian verdict, and decision items.
    """
    from ..paths import get_paths
    paths = get_paths(project_root)

    if not paths.local_features_dir.is_dir():
        return LandingJudgePanel(completed_features=[], quality_gates=[], total_features=0, awaiting_review=0)

    completed: list[LandingCompletedFeature] = []

    for name in paths.feature_names():
        local = paths.feature_local(name)
        shared = paths.feature_shared(name)

        state_file = local / "state.json"
        if not state_file.exists():
            continue
        state = _read_json(state_file) or {}

        if state.get("status") not in ("done", "completed"):
            continue

        coverage_pct, criteria_passed, criteria_total, _ = _read_criteria_verify(
            shared
        )
        decision_items = _read_decision_items(shared, local, name)
        decisions_needed = len(decision_items)
        guardian_verdict = _read_guardian_verdict(local)

        review_file = shared / "review.json"
        if review_file.exists():
            review_data = _read_json(review_file) or {}
            review_status = "approved" if review_data.get("verdict") == "pass" else "rejected"
        else:
            review_status = "pending"

        completed.append(LandingCompletedFeature(
            feature=name,
            completed_at=state.get("completed_at"),
            coverage_pct=coverage_pct,
            criteria_passed=criteria_passed,
            criteria_total=criteria_total,
            guardian_verdict=guardian_verdict,
            decisions_needed=decisions_needed,
            decision_items=decision_items[:5],
            review_status=review_status,
            summary=None,
        ))

    # Sort: pending review first, then by completed_at descending
    completed.sort(key=lambda f: (
        0 if f.review_status == "pending" else 1,
        f.completed_at or "",
    ), reverse=False)
    # Reverse within each group so most recent comes first
    completed.sort(key=lambda f: f.completed_at or "", reverse=True)
    completed.sort(key=lambda f: 0 if f.review_status == "pending" else 1)

    awaiting = sum(1 for f in completed if f.review_status == "pending")

    quality_gates = _read_quality_gates(project_root)

    return LandingJudgePanel(
        completed_features=completed,
        quality_gates=quality_gates,
        total_features=len(completed),
        awaiting_review=awaiting,
    )


def _read_quality_gates(project_root: Path) -> list[LandingQualityGate]:
    """Aggregate quality gate results across all completed features."""
    from ..paths import get_paths
    paths = get_paths(project_root)

    gates: list[LandingQualityGate] = []

    guardian_verdicts: list[str] = []
    coherence_statuses: list[tuple[str, int]] = []  # (status, critical_count)
    security_clean = True
    security_findings: list[str] = []

    for name in paths.feature_names():
        local = paths.feature_local(name)
        state_file = local / "state.json"
        if not state_file.exists():
            continue
        state = _read_json(state_file) or {}
        if state.get("status") not in ("done", "completed"):
            continue

        logs_dir = local / "logs"

        # Guardian
        verdict = _read_guardian_verdict(local)
        guardian_verdicts.append(verdict)

        # Coherence
        coherence_file = logs_dir / "coherence.log" if logs_dir.is_dir() else None
        if coherence_file and coherence_file.exists():
            cdata = _read_json(coherence_file)
            if cdata:
                cstatus = cdata.get("status", "unknown")
                criticals = len(cdata.get("critical_issues", []))
                coherence_statuses.append((cstatus, criticals))

        # Security (SAST findings)
        if logs_dir.is_dir():
            sast_file = logs_dir / "sast-findings.json"
            if sast_file.exists():
                findings = _read_json(sast_file)
                if isinstance(findings, list) and findings:
                    security_clean = False
                    security_findings.extend(
                        f.get("title", "finding") for f in findings if isinstance(f, dict)
                    )

    # Guardian aggregate
    approved = sum(1 for v in guardian_verdicts if v in ("approve", "pass"))
    flagged = sum(1 for v in guardian_verdicts if v == "flag")
    rejected = sum(1 for v in guardian_verdicts if v == "reject")
    unknown = sum(1 for v in guardian_verdicts if v in ("unknown", "error"))
    total = len(guardian_verdicts)
    fn = "feature" if total == 1 else "features"
    if total == 0:
        gates.append(LandingQualityGate(name="Guardian", status="warn", detail="Not yet run."))
    elif rejected > 0:
        gates.append(LandingQualityGate(name="Guardian", status="fail", detail=f"Rejected on {rejected} {fn}. Vision drift detected."))
    elif flagged > 0:
        gates.append(LandingQualityGate(name="Guardian", status="warn", detail=f"{flagged} {fn} flagged with warnings."))
    elif approved == total:
        gates.append(LandingQualityGate(name="Guardian", status="pass", detail=f"Approved across {total} {fn}."))
    elif unknown == total:
        gates.append(LandingQualityGate(name="Guardian", status="warn", detail=f"Not yet run on {total} {fn}."))
    else:
        gates.append(LandingQualityGate(name="Guardian", status="warn", detail=f"{approved} of {total} {fn} approved."))

    # Coherence aggregate
    cfn = "feature" if len(coherence_statuses) == 1 else "features"
    if not coherence_statuses:
        gates.append(LandingQualityGate(name="Coherence", status="warn", detail="Not yet run."))
    else:
        total_criticals = sum(c for _, c in coherence_statuses)
        total_checked = len(coherence_statuses)
        if total_criticals == 0:
            gates.append(LandingQualityGate(name="Coherence", status="pass", detail=f"Consistent across {total_checked} {cfn}."))
        else:
            gates.append(LandingQualityGate(
                name="Coherence",
                status="fail",
                detail=f"{total_criticals} critical issue{'s' if total_criticals != 1 else ''} across {total_checked} {cfn}.",
            ))

    # Security aggregate
    sfn = "feature" if total == 1 else "features"
    if security_clean:
        gates.append(LandingQualityGate(name="Security", status="pass", detail=f"Clean across {total} {sfn}."))
    else:
        gates.append(LandingQualityGate(
            name="Security",
            status="warn",
            detail=f"{len(security_findings)} finding{'s' if len(security_findings) != 1 else ''} across {total} {sfn}.",
        ))

    return gates


def _read_decision_items(
    shared_dir: Path, local_dir: Path, feature_name: str = ""
) -> list[LandingDecisionItem]:
    """Extract items that need human judgment across the full pipeline.

    Sources (in priority order):
    1. Spec traceability — uncovered requirements  (shared)
    2. Coherence — critical issues                 (local/logs)
    3. Task review — critical/major issues          (shared/tasks)
    """
    items: list[LandingDecisionItem] = []
    tag = feature_name or shared_dir.name

    # 1. Spec traceability: uncovered requirements
    trace_file = shared_dir / "spec-traceability.json"
    if trace_file.exists():
        data = _read_json(trace_file)
        if data:
            for req in data.get("uncovered", []):
                title = req.get("requirement", "")[:80]
                section = req.get("section", "")
                if title:
                    items.append(LandingDecisionItem(
                        title=title,
                        description=f"{tag} · uncovered — specified in {section}." if section else f"{tag} · specified but not covered.",
                    ))

    # 2. Coherence: critical issues
    coherence_file = local_dir / "logs" / "coherence.log"
    if coherence_file.exists():
        cdata = _read_json(coherence_file)
        if cdata:
            for issue in cdata.get("critical_issues", []):
                if isinstance(issue, str) and issue:
                    items.append(LandingDecisionItem(
                        title=issue[:80],
                        description=f"{tag} · coherence",
                    ))

    # 3. Task review: critical/major issues (skip diff-collapse false negatives)
    tasks_dir = shared_dir / "tasks"
    task_data = _read_task_files(tasks_dir)
    for task in task_data:
        if task.get("status") != "done":
            continue
        feedback_str = task.get("review_feedback", "")
        if not feedback_str:
            continue
        try:
            feedback = json.loads(feedback_str) if isinstance(feedback_str, str) else feedback_str
        except (json.JSONDecodeError, TypeError):
            continue
        for issue in feedback.get("issues", []):
            if issue.get("severity") not in ("critical", "major"):
                continue
            msg = issue.get("message", "")
            if "no diff" in msg.lower() or "diff is empty" in msg.lower():
                continue
            items.append(LandingDecisionItem(
                title=msg[:80],
                description=f"{tag} · review — task {task.get('id', '?')}",
            ))

    return items


def _read_criteria_verify(feature_dir: Path) -> tuple[float, int, int, int]:
    """Aggregate criteria verification from task JSON files.

    Each task stores gate results in gate_results.checks[] (with a 'criteria'
    entry) and acceptance criteria as a text field. Aggregates pass/total
    across all done tasks to compute feature-level coverage.

    Falls back to criteria-verify.json if it exists (legacy path).
    """
    # Legacy path: standalone file
    criteria_file = feature_dir / "criteria-verify.json"
    if criteria_file.exists():
        try:
            raw = json.loads(criteria_file.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                entries = raw
                coverage_pct = 0.0
                criteria_passed = 0
                criteria_total = len(entries)
            else:
                raw_pct = raw.get("coverage_pct", 0.0)
                coverage_pct = float(raw_pct) if raw_pct is not None else 0.0
                criteria_passed = int(raw.get("criteria_passed", 0))
                criteria_total = int(raw.get("criteria_total", 0))
                entries = raw.get("criteria", [])
                if not isinstance(entries, list):
                    entries = []
            coverage_pct = max(0.0, min(100.0, coverage_pct))
            decisions_needed = sum(
                1 for e in entries if isinstance(e, dict) and e.get("needs_decision") is True
            )
            return coverage_pct, criteria_passed, criteria_total, decisions_needed
        except (json.JSONDecodeError, OSError):
            pass

    # Primary path: aggregate from task JSON files
    tasks_dir = feature_dir / "tasks"
    task_data = _read_task_files(tasks_dir)
    if not task_data:
        return 0.0, 0, 0, 0

    criteria_passed = 0
    criteria_total = 0
    decisions_needed = 0

    for task in task_data:
        if task.get("status") != "done":
            continue
        ac_text = task.get("acceptance_criteria", "")
        ac_items = [line for line in ac_text.split("\n") if line.strip().startswith("- ")]
        criteria_total += len(ac_items)

        checks = {c["name"]: c["status"] for c in task.get("gate_results", {}).get("checks", []) if "name" in c}
        criteria_status = checks.get("criteria", "")
        rv = task.get("review_verdict", "")

        if criteria_status in ("pass", "warn") and rv == "approve":
            criteria_passed += len(ac_items)

    coverage_pct = round((criteria_passed / criteria_total * 100), 1) if criteria_total > 0 else 0.0
    coverage_pct = max(0.0, min(100.0, coverage_pct))
    return coverage_pct, criteria_passed, criteria_total, decisions_needed


def _read_guardian_verdict(feature_dir: Path) -> str:
    """Read the Guardian verdict from logs or cache.

    Checks (in order):
      1. guardian-{type}-{timestamp}.json (pipeline log)
      2. Guardian-*.jsonl (legacy naming)
      3. cache/guardian.dat (cached exit code: 0=approve, 1=reject)

    Returns 'unknown' if no Guardian data exists.
    """
    logs_dir = feature_dir / "logs"

    # Try log files first
    if logs_dir.is_dir():
        guardian_logs = sorted(logs_dir.glob("guardian-*.json"))
        if not guardian_logs:
            guardian_logs = sorted(logs_dir.glob("Guardian-*.jsonl"))
        if guardian_logs:
            try:
                content = guardian_logs[-1].read_text(encoding="utf-8")
                data = json.loads(content)
                if isinstance(data, dict):
                    verdict = data.get("verdict") or data.get("status")
                    if verdict:
                        return verdict
            except (OSError, json.JSONDecodeError):
                pass

            # JSONL fallback
            try:
                content = guardian_logs[-1].read_text(encoding="utf-8")
                lines = [line for line in content.splitlines() if line.strip()]
                if lines:
                    last_entry = json.loads(lines[-1])
                    verdict = last_entry.get("verdict")
                    if verdict:
                        return verdict
            except (OSError, json.JSONDecodeError, AttributeError):
                pass

    # Fallback: cache/guardian.dat (exit code from cached run)
    # 0=approve, 1=reject, 2=flag (warnings), 3=unparseable
    cache_file = feature_dir / "cache" / "guardian.dat"
    if cache_file.exists():
        try:
            exit_code = cache_file.read_text(encoding="utf-8").strip()
            _GUARDIAN_EXIT_MAP = {"0": "approve", "1": "reject", "2": "flag", "3": "error"}
            return _GUARDIAN_EXIT_MAP.get(exit_code, "unknown")
        except OSError:
            pass

    return "unknown"


# ── Execute Panel ─────────────────────────────────────────────────────────────


_EXECUTE_MAX_FEATURES = 5


def read_execute_panel(project_root: Path) -> LandingExecutePanel:
    """Compose the Execute panel from filesystem artifacts.

    Shows running features first, then fills with recently completed
    features up to _EXECUTE_MAX_FEATURES total.
    """
    from ..paths import get_paths
    paths = get_paths(project_root)

    if not paths.local_features_dir.is_dir():
        return LandingExecutePanel(running_features=[], recent_features=[], escalations=[])

    running_features: list[LandingRunningFeature] = []
    recent_candidates: list[tuple[str, str, int, int, float]] = []  # (name, completed_at, done, total, pct)
    escalations: list[LandingEscalation] = []

    for feature_name in paths.feature_names():
        local = paths.feature_local(feature_name)
        shared = paths.feature_shared(feature_name)

        state_file = local / "state.json"
        if not state_file.exists():
            continue
        state = _read_json(state_file) or {}
        feature_status = state.get("status", "")

        tasks_dir = shared / "tasks"
        task_data = _read_task_files(tasks_dir)
        tasks_total = len(task_data)
        tasks_completed = sum(
            1 for t in task_data if t.get("status") in ("completed", "done")
        )

        if feature_status == "running":
            blocked_tasks = [t for t in task_data if t.get("status") == "blocked"]
            blocked_count = len(blocked_tasks)
            progress_pct = max(0.0, min(100.0, (tasks_completed / tasks_total) * 100)) if tasks_total else 0.0

            running_features.append(
                LandingRunningFeature(
                    name=feature_name,
                    progress_pct=progress_pct,
                    tasks_completed=tasks_completed,
                    tasks_total=tasks_total,
                    blocked_count=blocked_count,
                )
            )

            for task in blocked_tasks:
                question = task.get("escalation_question") or ""
                response = task.get("escalation_response") or ""
                if question and not response:
                    escalations.append(
                        LandingEscalation(
                            feature=feature_name,
                            task_id=task.get("id", ""),
                            task_title=task.get("title", ""),
                            question=question,
                        )
                    )

        elif feature_status in ("done", "completed"):
            completed_at = state.get("completed_at", "")
            coverage_pct = max(0.0, min(100.0, (tasks_completed / tasks_total) * 100)) if tasks_total else 0.0
            recent_candidates.append((feature_name, completed_at, tasks_completed, tasks_total, coverage_pct))

    running_features.sort(key=lambda f: f.blocked_count, reverse=True)
    escalations.sort(key=lambda e: (e.feature, e.task_id))

    # Fill remaining slots with recently completed features
    slots_remaining = _EXECUTE_MAX_FEATURES - len(running_features)
    recent_candidates.sort(key=lambda c: c[1], reverse=True)  # most recent first
    recent_features = [
        LandingRecentFeature(
            name=name,
            completed_at=completed_at or None,
            coverage_pct=coverage_pct,
            tasks_completed=done,
            tasks_total=total,
        )
        for name, completed_at, done, total, coverage_pct in recent_candidates[:max(0, slots_remaining)]
    ]

    return LandingExecutePanel(
        running_features=running_features,
        recent_features=recent_features,
        escalations=escalations,
    )


def _read_task_files(tasks_dir: Path) -> list[dict[str, Any]]:
    """Read all task JSON files from a feature's tasks directory."""
    if not tasks_dir.is_dir():
        return []
    tasks = []
    for task_file in tasks_dir.glob("*.json"):
        data = _read_json(task_file)
        if data is not None:
            tasks.append(data)
    return tasks


# ── Learn Panel ───────────────────────────────────────────────────────────────


def read_learn_panel(project_root: Path) -> LandingLearnPanel:
    """Compose the Learn panel from filesystem artifacts.

    Reads:
      - .speed/features/*/spec-traceability.json  (coverage trend, primary)
      - .speed/memory/observations/{feature}.jsonl (coverage trend, fallback)
      - .speed/memory/*-learnings.json            (insights)
      - .speed/features/{name}/tasks/*.json       (escalation trend)
    """
    coverage_trend = _read_coverage_trend(project_root)
    feature_names = [ct.feature for ct in coverage_trend]
    return LandingLearnPanel(
        coverage_trend=coverage_trend,
        insights=_read_insights(project_root),
        escalation_trend=_read_escalation_trend(project_root, feature_names),
    )


def _read_coverage_trend(project_root: Path) -> list[LandingCoverageTrend]:
    from ..paths import get_paths
    paths = get_paths(project_root)

    if not paths.features_dir.is_dir():
        return []

    # Primary: spec-traceability.json lives in the shared zone
    traceability_found = False
    result: list[LandingCoverageTrend] = []
    for name in paths.feature_names():
        tf = paths.feature_shared(name) / "spec-traceability.json"
        if not tf.exists():
            continue
        traceability_found = True
        data = _read_json(tf)
        if data is None:
            continue
        # coverage_ratio is 0.0-1.0, coverage_pct is 0-100
        raw_pct = data.get("coverage_pct") or data.get("coverage_ratio")
        pct = float(raw_pct) if raw_pct is not None else 0.0
        coverage_pct = max(0.0, min(100.0, pct * 100 if pct <= 1.0 else pct))
        result.append(LandingCoverageTrend(feature=name, coverage_pct=coverage_pct))
    if traceability_found:
        return result

    # Fallback: observations JSONL
    observations_dir = paths.observations_dir
    if not observations_dir.is_dir():
        return []

    result = []
    for name in paths.feature_names():
        obs_file = observations_dir / f"{name}.jsonl"
        if not obs_file.exists():
            continue
        coverage_pct = _latest_coverage_from_jsonl(obs_file)
        if coverage_pct is not None:
            result.append(LandingCoverageTrend(feature=name, coverage_pct=coverage_pct))
    return result


def _latest_coverage_from_jsonl(path: Path) -> float | None:
    """Read a JSONL file and return the coverage_pct from the last entry that has one."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    latest: float | None = None
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            if isinstance(entry, dict) and "coverage_pct" in entry:
                raw = entry["coverage_pct"]
                latest = max(0.0, min(100.0, float(raw) if raw is not None else 0.0))
        except (json.JSONDecodeError, ValueError, TypeError):
            continue
    return latest


def _read_insights(project_root: Path) -> list[LandingInsight]:
    from ..paths import get_paths
    paths = get_paths(project_root)

    memory_dir = paths.memory_dir
    if not memory_dir.is_dir():
        return []

    all_entries: list[tuple[float, str, str]] = []
    for learnings_file in memory_dir.glob("*-learnings.json"):
        try:
            raw = json.loads(learnings_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        if isinstance(raw, list):
            entries = raw
        elif isinstance(raw, dict):
            entries = raw.get("entries", [])
            if not isinstance(entries, list):
                entries = []
        else:
            continue

        for entry in entries:
            if not isinstance(entry, dict) or "weight" not in entry:
                continue
            insight_type = entry.get("type", "")
            if insight_type not in ("good", "warn"):
                continue
            text = entry.get("text", "")
            try:
                weight = float(entry["weight"])
            except (ValueError, TypeError):
                weight = 0.0
            all_entries.append((weight, insight_type, text))

    all_entries.sort(key=lambda x: x[0], reverse=True)
    return [LandingInsight(type=t, text=txt) for _, t, txt in all_entries[:5]]


def _read_escalation_trend(
    project_root: Path, feature_names: list[str]
) -> list[LandingEscalationTrend]:
    if not feature_names:
        return []

    from ..paths import get_paths
    paths = get_paths(project_root)

    if not paths.features_dir.is_dir():
        return []

    result: list[LandingEscalationTrend] = []
    for feature_name in feature_names:
        tasks_dir = paths.feature_shared(feature_name) / "tasks"
        task_data = _read_task_files(tasks_dir)
        count = sum(1 for t in task_data if t.get("escalation_question"))
        result.append(LandingEscalationTrend(feature=feature_name, count=count))
    return result


# ── Escalation response mutation ──────────────────────────────────────────────

_PATH_TRAVERSAL_FRAGMENTS = ("/", "..", "\x00")


def respond_to_escalation(
    project_root: Path, input: EscalationResponseInput
) -> EscalationResponseResult:
    """Write an escalation response to the task JSON file.

    Validates input, checks preconditions, then atomically writes
    escalation_response and escalation_responded_at to the task file.
    """
    # 1. Input validation
    if not input.response:
        return EscalationResponseResult(success=False, error="Response cannot be empty.")
    if len(input.response) > 2000:
        return EscalationResponseResult(success=False, error="Response exceeds 2000 characters.")
    for fragment in _PATH_TRAVERSAL_FRAGMENTS:
        if fragment in input.feature:
            return EscalationResponseResult(
                success=False, error="Invalid feature name: contains forbidden characters."
            )
        if fragment in input.task_id:
            return EscalationResponseResult(
                success=False, error="Invalid task_id: contains forbidden characters."
            )

    # 2. Path resolution
    from ..paths import get_paths
    paths = get_paths(project_root)

    shared_dir = paths.feature_shared(input.feature)
    if not shared_dir.is_dir():
        return EscalationResponseResult(
            success=False, error=f"Feature directory not found: {input.feature}"
        )

    task_file = shared_dir / "tasks" / f"{input.task_id}.json"
    if not task_file.exists():
        return EscalationResponseResult(
            success=False, error=f"Task file not found: {input.task_id}"
        )

    # 3. Precondition check
    task_data = _read_json(task_file)
    if task_data is None:
        return EscalationResponseResult(success=False, error="Failed to read task file.")
    if task_data.get("status") != "blocked":
        return EscalationResponseResult(success=False, error="Task is not in blocked status.")
    if not task_data.get("escalation_question"):
        return EscalationResponseResult(success=False, error="Task has no escalation question.")

    # 4. Atomic write
    task_data["escalation_response"] = input.response
    task_data["escalation_responded_at"] = datetime.now(timezone.utc).isoformat()

    tmp_file = task_file.with_suffix(".tmp")
    try:
        tmp_file.write_text(json.dumps(task_data, indent=2), encoding="utf-8")
        os.replace(tmp_file, task_file)
    except OSError as exc:
        try:
            tmp_file.unlink(missing_ok=True)
        except OSError:
            pass
        return EscalationResponseResult(success=False, error=f"Write failed: {exc}")

    return EscalationResponseResult(success=True, error=None)


# ── Shared helpers ─────────────────────────────────────────────────────────────


def _read_json(path: Path) -> dict[str, Any] | None:
    """Safely read a JSON file, returning None on any error."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
