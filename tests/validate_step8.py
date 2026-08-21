#!/usr/bin/env python3
"""Validation harness for Step 8: Decomposition Quality.

Runs the proposed _load_architect_plan + existing comparison logic
against real data from speed-defects, f10-rich-feed, f9-profile-completeness,
and seed-onboarding-flag, plus synthetic edge cases.

Usage:
  python tests/validate_step8.py
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

def _read_json(path: Path) -> dict | list | None:
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


# ---------------------------------------------------------------------------
# Proposed _load_architect_plan helper
# ---------------------------------------------------------------------------

def _load_architect_plan(logs_dir: Path) -> dict | None:
    """Load the plan from the Architect agent's JSONL output."""
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
# Existing Step 8 comparison logic (unchanged from extract.py)
# ---------------------------------------------------------------------------

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
            continue

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

        issue = "boundary_mismatch"
        if missing and not extras:
            issue = "missing_dependency"
        elif extras and len(extras) > len(planned) * 0.5:
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
# Scenario 1: _load_architect_plan on real data
# ===========================================================================

print("\n═══ Scenario 1: _load_architect_plan loads real Architect JSONL ═══")

# speed-defects (3 Architect files, use newest)
logs = Path(".speed/features/speed-defects/logs")
if not list(logs.glob("Architect-*.jsonl")):
    print("  SKIP: speed-defects Architect JSONL not found")
else:
    plan = _load_architect_plan(logs)
    check("Plan loaded (not None)", plan is not None)
    check("Plan is a dict", isinstance(plan, dict))
    check("Plan has 'tasks' key", "tasks" in plan)
    check("Plan has 10 tasks", len(plan.get("tasks", [])) == 10)
    # Verify task structure
    t1 = plan["tasks"][0]
    check("Task 1 has 'id'", "id" in t1)
    check("Task 1 has 'files_touched'", "files_touched" in t1)
    check("Task 1 id is '1'", str(t1["id"]) == "1")

# fyt features
fyt = Path("/Users/sanjay.kotagiri/Documents/code/tmp/find-your-tribe")
for feat, expected_tasks in [("f10-rich-feed", 4), ("f9-profile-completeness", 7), ("seed-onboarding-flag", 1)]:
    print(f"\n═══ Scenario 1b: _load_architect_plan on {feat} ═══")
    logs = fyt / f".speed/features/{feat}/logs"
    if not list(logs.glob("Architect-*.jsonl")):
        print(f"  SKIP: {feat} Architect JSONL not found")
        continue
    plan = _load_architect_plan(logs)
    check(f"Plan loaded for {feat}", plan is not None)
    task_count = len(plan.get("tasks", []))
    check(f"Plan has {expected_tasks} tasks (got {task_count})",
          task_count >= expected_tasks)


# ===========================================================================
# Scenario 2: Step 8 on real data (expect zero decomposition_miss)
# ===========================================================================

print("\n═══ Scenario 2: Step 8 on speed-defects (all match → 0 observations) ═══")

logs = Path(".speed/features/speed-defects/logs")
tasks_dir = Path(".speed/features/speed-defects/tasks")
if not list(logs.glob("Architect-*.jsonl")):
    print("  SKIP: speed-defects Architect JSONL not found")
else:
    plan = _load_architect_plan(logs)
    # Load actual tasks
    tasks = {}
    for tf in sorted(tasks_dir.glob("*.json")):
        tasks[tf.stem] = json.loads(tf.read_text())

    result = ExtractResult()
    _step8_decomposition_quality("speed-defects", tasks, plan, result)

    check("Zero decomposition_miss observations", len(result.observations) == 0)
    check("No warnings", len(result.warnings) == 0)

for feat in ["f10-rich-feed", "f9-profile-completeness", "seed-onboarding-flag"]:
    print(f"\n═══ Scenario 2b: Step 8 on {feat} ═══")
    logs = fyt / f".speed/features/{feat}/logs"
    tasks_dir = fyt / f".speed/features/{feat}/tasks"
    if not list(logs.glob("Architect-*.jsonl")):
        print(f"  SKIP: {feat} not found")
        continue
    plan = _load_architect_plan(logs)
    tasks = {}
    for tf in sorted(tasks_dir.glob("*.json")):
        tasks[tf.stem] = json.loads(tf.read_text())
    result = ExtractResult()
    _step8_decomposition_quality(feat, tasks, plan, result)
    check(f"Zero decomposition_miss for {feat}", len(result.observations) == 0)
    check("No warnings", len(result.warnings) == 0)


# ===========================================================================
# Scenario 3: Step 8 on speed-security (no Architect JSONL → warning)
# ===========================================================================

print("\n═══ Scenario 3: No Architect JSONL → warning ═══")

logs = Path(".speed/features/speed-security/logs")
plan = _load_architect_plan(logs)
check("Plan is None for speed-security", plan is None)

result = ExtractResult()
_step8_decomposition_quality("speed-security", {}, plan, result)
check("Warning emitted", len(result.warnings) == 1)
check("Warning mentions 'no Architect plan'",
      "no Architect plan" in result.warnings[0])
check("Zero observations", len(result.observations) == 0)


# ===========================================================================
# Scenario 4: Synthetic — scope_too_broad
# ===========================================================================

print("\n═══ Scenario 4: Synthetic scope_too_broad ═══")

plan = {"tasks": [{"id": "1", "files_touched": ["a.py"]}]}
tasks = {"1": {"files_touched": ["a.py", "b.py", "c.py"], "status": "done"}}
result = ExtractResult()
_step8_decomposition_quality("test", tasks, plan, result)

check("1 decomposition_miss", len(result.observations) == 1)
obs = result.observations[0]
check("Issue is scope_too_broad", obs.detail["issue"] == "scope_too_broad")
check("Weight is 2.0", obs.weight == 2.0)
check("Stage is architect", obs.stage == "architect")
check("Task ID is '1'", obs.task_id == "1")
check("Extras are [b.py, c.py]",
      "b.py" in obs.detail["analysis"] and "c.py" in obs.detail["analysis"])


# ===========================================================================
# Scenario 5: Synthetic — missing_dependency
# ===========================================================================

print("\n═══ Scenario 5: Synthetic missing_dependency ═══")

plan = {"tasks": [{"id": "1", "files_touched": ["a.py", "b.py"]}]}
tasks = {"1": {"files_touched": ["a.py"], "status": "done"}}
result = ExtractResult()
_step8_decomposition_quality("test", tasks, plan, result)

check("1 decomposition_miss", len(result.observations) == 1)
check("Issue is missing_dependency",
      result.observations[0].detail["issue"] == "missing_dependency")


# ===========================================================================
# Scenario 6: Synthetic — boundary_mismatch
# ===========================================================================

print("\n═══ Scenario 6: Synthetic boundary_mismatch ═══")

# Need enough planned files that extras don't exceed 50% threshold
plan = {"tasks": [{"id": "1", "files_touched": ["a.py", "b.py", "c.py"]}]}
tasks = {"1": {"files_touched": ["a.py", "d.py"], "status": "done"}}
result = ExtractResult()
_step8_decomposition_quality("test", tasks, plan, result)

check("1 decomposition_miss", len(result.observations) == 1)
check("Issue is boundary_mismatch",
      result.observations[0].detail["issue"] == "boundary_mismatch")


# ===========================================================================
# Scenario 7: Synthetic — exact match → no observation
# ===========================================================================

print("\n═══ Scenario 7: Exact match → no observation ═══")

plan = {"tasks": [{"id": "1", "files_touched": ["a.py", "b.py"]}]}
tasks = {"1": {"files_touched": ["a.py", "b.py"], "status": "done"}}
result = ExtractResult()
_step8_decomposition_quality("test", tasks, plan, result)

check("Zero observations", len(result.observations) == 0)
check("No warnings", len(result.warnings) == 0)


# ===========================================================================
# Scenario 8: Synthetic — task not in plan → skipped
# ===========================================================================

print("\n═══ Scenario 8: Task not in plan → skipped ═══")

plan = {"tasks": [{"id": "1", "files_touched": ["a.py"]}]}
tasks = {"10a": {"files_touched": ["speed"], "status": "done"}}
result = ExtractResult()
_step8_decomposition_quality("test", tasks, plan, result)

check("Zero observations (task 10a not in plan)", len(result.observations) == 0)
check("No warnings", len(result.warnings) == 0)


# ===========================================================================
# Scenario 9: Edge — None plan
# ===========================================================================

print("\n═══ Scenario 9: None plan → warning ═══")

result = ExtractResult()
_step8_decomposition_quality("test", {}, None, result)

check("Warning emitted", len(result.warnings) == 1)
check("Zero observations", len(result.observations) == 0)


# ===========================================================================
# Scenario 10: Edge — empty tasks dict
# ===========================================================================

print("\n═══ Scenario 10: Empty tasks → no observations ═══")

plan = {"tasks": [{"id": "1", "files_touched": ["a.py"]}]}
result = ExtractResult()
_step8_decomposition_quality("test", {}, plan, result)

check("Zero observations", len(result.observations) == 0)
check("No warnings", len(result.warnings) == 0)


# ===========================================================================
# Scenario 11: Idempotency
# ===========================================================================

print("\n═══ Scenario 11: Idempotency ═══")

plan = {"tasks": [{"id": "1", "files_touched": ["a.py"]}]}
tasks = {"1": {"files_touched": ["a.py", "b.py", "c.py"], "status": "done"}}
r1 = ExtractResult()
_step8_decomposition_quality("test", tasks, plan, r1)
r2 = ExtractResult()
_step8_decomposition_quality("test", tasks, plan, r2)

check("Same IDs", [o.id for o in r1.observations] == [o.id for o in r2.observations])


# ===========================================================================
# Scenario 12: _load_architect_plan edge cases
# ===========================================================================

print("\n═══ Scenario 12: _load_architect_plan edge cases ═══")

# No Architect files
with tempfile.TemporaryDirectory() as tmpdir:
    plan = _load_architect_plan(Path(tmpdir))
    check("No Architect files → None", plan is None)

# Empty JSONL
with tempfile.TemporaryDirectory() as tmpdir:
    (Path(tmpdir) / "Architect-123.jsonl").write_text("")
    plan = _load_architect_plan(Path(tmpdir))
    check("Empty JSONL → None", plan is None)

# JSONL without structured_output
with tempfile.TemporaryDirectory() as tmpdir:
    (Path(tmpdir) / "Architect-123.jsonl").write_text(
        json.dumps({"type": "result", "result": "ok"}) + "\n")
    plan = _load_architect_plan(Path(tmpdir))
    check("No structured_output → None", plan is None)

# JSONL with non-dict structured_output
with tempfile.TemporaryDirectory() as tmpdir:
    (Path(tmpdir) / "Architect-123.jsonl").write_text(
        json.dumps({"type": "result", "structured_output": "string"}) + "\n")
    plan = _load_architect_plan(Path(tmpdir))
    check("Non-dict structured_output → None", plan is None)

# Multiple JSONL files — uses newest
with tempfile.TemporaryDirectory() as tmpdir:
    (Path(tmpdir) / "Architect-100.jsonl").write_text(
        json.dumps({"structured_output": {"tasks": [{"id": "old"}]}}) + "\n")
    (Path(tmpdir) / "Architect-200.jsonl").write_text(
        json.dumps({"structured_output": {"tasks": [{"id": "new"}]}}) + "\n")
    plan = _load_architect_plan(Path(tmpdir))
    check("Uses newest file", plan["tasks"][0]["id"] == "new")

# Malformed JSON
with tempfile.TemporaryDirectory() as tmpdir:
    (Path(tmpdir) / "Architect-123.jsonl").write_text("not json\n")
    plan = _load_architect_plan(Path(tmpdir))
    check("Malformed JSON → None", plan is None)


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
