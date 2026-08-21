#!/usr/bin/env python3
"""Validation harness for Step 9: Success Observations.

Tests the proposed blocking logic and success detail against real data
from speed-defects, speed-security, f9-profile-completeness, f10-rich-feed,
and seed-onboarding-flag, plus synthetic edge cases.

Usage:
  python tests/validate_step9.py
"""

import json
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

# ---------------------------------------------------------------------------
# Minimal reproduction of extract.py types
# ---------------------------------------------------------------------------

@dataclass
class Observation:
    id: str
    feature: str
    stage: str
    task_id: str
    timestamp: str
    observation_type: str
    detail: dict
    weight: float

@dataclass
class ExtractResult:
    observations: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)

_WEIGHTS: dict[str, float] = {
    "retry": 3.0, "reviewer_finding": 1.5, "human_override": 2.5,
    "guardian_verdict": 2.0, "gate_failure": 2.0, "context_miss": 1.5,
    "context_waste": 0.5, "decomposition_miss": 2.0, "convention_violation": 1.5,
    "verify_finding": 2.0, "coherence_issue": 2.0, "security_finding": 1.5,
    "success": 0.5, "pattern_match": 2.0, "unattributed_changes": 1.0,
    "agent_concern": 1.0,
}

_NON_BLOCKING_TYPES = frozenset({
    "agent_concern", "context_miss", "context_waste",
    "decomposition_miss", "success",
})

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def observation_id(feature, task_id, stage, obs_type, detail) -> str:
    canonical = json.dumps({
        "feature": feature, "task_id": task_id, "stage": stage,
        "observation_type": obs_type, "detail": detail,
    }, sort_keys=True)
    return sha256(canonical.encode()).hexdigest()[:16]

def _make_obs(feature, stage, task_id, obs_type, detail, weight=None):
    w = weight if weight is not None else _WEIGHTS.get(obs_type, 1.0)
    return Observation(
        id=observation_id(feature, task_id, stage, obs_type, detail),
        feature=feature, stage=stage, task_id=task_id,
        timestamp=_now_iso(), observation_type=obs_type,
        detail=detail, weight=w,
    )

def _duration_seconds(task: dict):
    started = task.get("started_at")
    completed = task.get("completed_at")
    if not started or not completed:
        return None
    try:
        from datetime import datetime
        for fmt in ["%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ",
                    "%Y-%m-%dT%H:%M:%S%z"]:
            try:
                s = datetime.strptime(started, fmt)
                c = datetime.strptime(completed, fmt)
                return int((c - s).total_seconds())
            except ValueError:
                continue
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Proposed blocking logic
# ---------------------------------------------------------------------------

def build_task_issues(observations: list) -> set:
    task_issues: set[str] = set()
    for obs in observations:
        if obs.task_id == "*":
            continue
        if obs.observation_type in _NON_BLOCKING_TYPES:
            continue
        if obs.observation_type == "reviewer_finding":
            if obs.detail.get("severity", "") in ("nit", "positive"):
                continue
        task_issues.add(obs.task_id)
    return task_issues


# ---------------------------------------------------------------------------
# Proposed Step 9 implementation
# ---------------------------------------------------------------------------

def _step9_success_observations(feature: str, tasks: dict[str, dict],
                                  task_issues: set[str],
                                  plan: dict | None,
                                  result: ExtractResult) -> None:
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


# ---------------------------------------------------------------------------
# Architect plan loader (same as extract.py)
# ---------------------------------------------------------------------------

def _load_architect_plan(logs_dir: Path) -> dict | None:
    architect_files = sorted(logs_dir.glob("Architect-*.jsonl"))
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


# ---------------------------------------------------------------------------
# Test infrastructure
# ---------------------------------------------------------------------------

passed = 0
failed = 0

def check(label, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f"  ✓ {label}")
    else:
        failed += 1
        print(f"  ✗ {label}")


# ===========================================================================
# Scenario 1: Blocking logic — nit/positive don't block
# ===========================================================================

print("\n═══ Scenario 1: Nit/positive reviewer findings don't block ═══")

obs = [
    _make_obs("test", "reviewer", "1", "reviewer_finding",
              {"severity": "nit", "finding": "x"}),
    _make_obs("test", "reviewer", "1", "reviewer_finding",
              {"severity": "positive", "finding": "y"}),
    _make_obs("test", "reviewer", "2", "reviewer_finding",
              {"severity": "minor", "finding": "z"}),
]
issues = build_task_issues(obs)
check("Task 1 (nit+positive) NOT blocked", "1" not in issues)
check("Task 2 (minor) IS blocked", "2" in issues)


# ===========================================================================
# Scenario 2: Blocking logic — non-blocking types
# ===========================================================================

print("\n═══ Scenario 2: agent_concern, context_miss, etc don't block ═══")

obs = [
    _make_obs("test", "developer", "1", "agent_concern", {"concern": "x"}),
    _make_obs("test", "context", "2", "context_miss", {"file": "a.py"}),
    _make_obs("test", "context", "3", "context_waste", {"waste_ratio": 0.98}),
    _make_obs("test", "architect", "4", "decomposition_miss", {"issue": "scope_too_broad"}),
]
issues = build_task_issues(obs)
check("Task 1 (agent_concern) NOT blocked", "1" not in issues)
check("Task 2 (context_miss) NOT blocked", "2" not in issues)
check("Task 3 (context_waste) NOT blocked", "3" not in issues)
check("Task 4 (decomposition_miss) NOT blocked", "4" not in issues)


# ===========================================================================
# Scenario 3: Blocking logic — retry and gate_failure block
# ===========================================================================

print("\n═══ Scenario 3: retry and gate_failure DO block ═══")

obs = [
    _make_obs("test", "developer", "1", "retry", {"attempt": 2}),
    _make_obs("test", "developer", "2", "gate_failure", {"gate": "Tests"}),
    _make_obs("test", "guardian", "3", "guardian_verdict", {"verdict": "rejected"}),
]
issues = build_task_issues(obs)
check("Task 1 (retry) IS blocked", "1" in issues)
check("Task 2 (gate_failure) IS blocked", "2" in issues)
check("Task 3 (guardian_verdict) IS blocked", "3" in issues)


# ===========================================================================
# Scenario 4: Blocking logic — star task_id ignored
# ===========================================================================

print("\n═══ Scenario 4: Feature-level observations don't block tasks ═══")

obs = [
    _make_obs("test", "verifier", "*", "verify_finding", {"finding_type": "missing"}),
    _make_obs("test", "coherence", "*", "coherence_issue", {"issue_type": "critical"}),
]
issues = build_task_issues(obs)
check("No tasks blocked by feature-level obs", len(issues) == 0)


# ===========================================================================
# Scenario 5: Success detail — agent_model
# ===========================================================================

print("\n═══ Scenario 5: Success detail fields ═══")

tasks = {"1": {"status": "done", "agent_model": "sonnet",
               "files_touched": ["a.py", "b.py"],
               "started_at": "2026-03-01T10:00:00Z",
               "completed_at": "2026-03-01T10:05:00Z"}}
plan = {"tasks": [{"id": "1", "files_touched": ["a.py", "b.py", "c.py"]}]}
result = ExtractResult()
_step9_success_observations("test", tasks, set(), plan, result)

check("1 success observation", len(result.observations) == 1)
s = result.observations[0]
check("agent_model is 'sonnet'", s.detail["agent_model"] == "sonnet")
check("files_planned is 3 (from plan)", s.detail["files_planned"] == 3)
check("files_actual is 2", s.detail["files_actual"] == 2)
check("guardian is 'no_check'", s.detail["guardian"] == "no_check")
check("duration_seconds is 300", s.detail["duration_seconds"] == 300)
check("retry_count is 0", s.detail["retry_count"] == 0)
check("weight is 0.5", s.weight == 0.5)
check("stage is 'developer'", s.stage == "developer")
check("task_id is '1'", s.task_id == "1")


# ===========================================================================
# Scenario 6: Guardian status derived from observations
# ===========================================================================

print("\n═══ Scenario 6: Guardian status from observations ═══")

result = ExtractResult()
result.observations.append(
    _make_obs("test", "guardian", "1", "guardian_verdict",
              {"verdict": "flagged", "subtype": "verdict"})
)
tasks = {"1": {"status": "done", "files_touched": ["a.py"]},
         "2": {"status": "done", "files_touched": ["b.py"]}}
# Task 1 has guardian verdict (but it's also in task_issues so won't get success)
# Task 2 has no guardian verdict
_step9_success_observations("test", tasks, {"1"}, None, result)

successes = [o for o in result.observations if o.observation_type == "success"]
check("Only task 2 gets success", len(successes) == 1)
check("Task 2 guardian is 'no_check'", successes[0].detail["guardian"] == "no_check")


# ===========================================================================
# Scenario 7: files_planned fallback when no plan
# ===========================================================================

print("\n═══ Scenario 7: files_planned fallback ═══")

tasks = {"1": {"status": "done", "files_touched": ["a.py", "b.py"]}}
result = ExtractResult()
_step9_success_observations("test", tasks, set(), None, result)

check("files_planned falls back to files_actual",
      result.observations[0].detail["files_planned"] == 2)


# ===========================================================================
# Scenario 8: Task not done → no success
# ===========================================================================

print("\n═══ Scenario 8: Non-done tasks skipped ═══")

tasks = {"1": {"status": "error", "files_touched": []},
         "2": {"status": "running", "files_touched": []}}
result = ExtractResult()
_step9_success_observations("test", tasks, set(), None, result)

check("Zero successes for non-done tasks", len(result.observations) == 0)


# ===========================================================================
# Scenario 9: Idempotency
# ===========================================================================

print("\n═══ Scenario 9: Idempotency ═══")

tasks = {"1": {"status": "done", "agent_model": "sonnet",
               "files_touched": ["a.py"]}}
r1 = ExtractResult()
_step9_success_observations("test", tasks, set(), None, r1)
r2 = ExtractResult()
_step9_success_observations("test", tasks, set(), None, r2)
check("Same IDs", [o.id for o in r1.observations] == [o.id for o in r2.observations])


# ===========================================================================
# Scenario 10: Real data — speed-defects (expect 5 successes)
# ===========================================================================

print("\n═══ Scenario 10: Real data — speed-defects ═══")

sys.path.insert(0, "lib")
from learn.extract import extract_observations as real_extract

feat = Path(".speed/features/speed-defects")
mem = Path(".speed/memory")
if feat.exists():
    real_result = real_extract(feat, mem)

    # Simulate fixed blocking logic on real observations
    task_issues = build_task_issues(real_result.observations)

    # Load tasks and plan
    tasks = {}
    for tf in sorted((feat / "tasks").glob("*.json")):
        tasks[tf.stem] = json.loads(tf.read_text())
    plan = _load_architect_plan(feat / "logs")

    result = ExtractResult()
    # Copy non-success observations for guardian status derivation
    result.observations = [o for o in real_result.observations
                           if o.observation_type != "success"]
    _step9_success_observations("speed-defects", tasks, task_issues, plan, result)

    successes = [o for o in result.observations if o.observation_type == "success"]
    eligible_ids = sorted([s.task_id for s in successes])
    check(f"5 success observations (got {len(successes)}): {eligible_ids}",
          len(successes) == 5)
    check("Expected tasks: 10b, 10c, 4, 5, 9",
          set(eligible_ids) == {"10b", "10c", "4", "5", "9"})

    # Check detail fields
    for s in successes:
        check(f"Task {s.task_id} has agent_model",
              s.detail.get("agent_model", "") != "")
        check(f"Task {s.task_id} weight is 0.5", s.weight == 0.5)
else:
    print("  SKIP: speed-defects not found")


# ===========================================================================
# Scenario 11: Real data — f9-profile-completeness (expect 4 successes)
# ===========================================================================

print("\n═══ Scenario 11: Real data — f9-profile-completeness ═══")

fyt = Path("/Users/sanjay.kotagiri/Documents/code/tmp/find-your-tribe")
feat = fyt / ".speed/features/f9-profile-completeness"
mem = fyt / ".speed/memory"
if feat.exists():
    if not mem.exists():
        mem.mkdir(parents=True, exist_ok=True)
    real_result = real_extract(feat, mem)
    task_issues = build_task_issues(real_result.observations)

    tasks = {}
    for tf in sorted((feat / "tasks").glob("*.json")):
        tasks[tf.stem] = json.loads(tf.read_text())
    plan = _load_architect_plan(feat / "logs")

    result = ExtractResult()
    result.observations = [o for o in real_result.observations
                           if o.observation_type != "success"]
    _step9_success_observations("f9-profile-completeness", tasks,
                                task_issues, plan, result)

    successes = [o for o in result.observations if o.observation_type == "success"]
    eligible_ids = sorted([s.task_id for s in successes])
    check(f"4 success observations (got {len(successes)}): {eligible_ids}",
          len(successes) == 4)
    check("Expected tasks: 2, 3, 5, 7",
          set(eligible_ids) == {"2", "3", "5", "7"})

    # Check agent_model populated
    for s in successes:
        check(f"Task {s.task_id} agent_model is 'sonnet'",
              s.detail["agent_model"] == "sonnet")

    # Check files_planned uses plan data
    if plan:
        for s in successes:
            plan_files = []
            for pt in plan.get("tasks", []):
                if str(pt.get("id", "")) == s.task_id:
                    plan_files = pt.get("files_touched", [])
            if plan_files:
                check(f"Task {s.task_id} files_planned from plan ({len(plan_files)})",
                      s.detail["files_planned"] == len(plan_files))
else:
    print("  SKIP: f9-profile-completeness not found")


# ===========================================================================
# Scenario 12: Real data — speed-security (expect 1 success)
# ===========================================================================

print("\n═══ Scenario 12: Real data — speed-security ═══")

feat = Path(".speed/features/speed-security")
mem = Path(".speed/memory")
if feat.exists() and (feat / "tasks").exists():
    real_result = real_extract(feat, mem)
    task_issues = build_task_issues(real_result.observations)

    tasks = {}
    for tf in sorted((feat / "tasks").glob("*.json")):
        tasks[tf.stem] = json.loads(tf.read_text())
    plan = _load_architect_plan(feat / "logs")

    result = ExtractResult()
    result.observations = [o for o in real_result.observations
                           if o.observation_type != "success"]
    _step9_success_observations("speed-security", tasks, task_issues,
                                plan, result)

    successes = [o for o in result.observations if o.observation_type == "success"]
    eligible_ids = sorted([s.task_id for s in successes])
    check(f"1 success observation (got {len(successes)}): {eligible_ids}",
          len(successes) == 1)

    if successes:
        # No plan for speed-security, so files_planned falls back
        s = successes[0]
        check("files_planned == files_actual (no plan)",
              s.detail["files_planned"] == s.detail["files_actual"])
else:
    print("  SKIP: speed-security not found")


# ===========================================================================
# Summary
# ===========================================================================

print(f"\n{'═' * 50}")
print(f"Results: {passed} passed, {failed} failed out of {passed + failed}")
if failed > 0:
    print("FAIL")
    sys.exit(1)
else:
    print("ALL CHECKS PASSED")
    sys.exit(0)
