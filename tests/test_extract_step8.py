#!/usr/bin/env python3
"""Tests for Step 8: Decomposition Quality — against real extract.py."""

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from learn.extract import (
    _step8_decomposition_quality,
    _load_architect_plan,
    ExtractResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_plan(tasks: list[dict]) -> dict:
    """Build a minimal Architect plan dict."""
    return {"tasks": tasks}


def make_architect_jsonl(logs_dir: Path, plan: dict) -> None:
    """Write a fake Architect JSONL file into logs_dir."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    line = json.dumps({"type": "result", "structured_output": plan})
    (logs_dir / "Architect-100.jsonl").write_text(line + "\n")


# ---------------------------------------------------------------------------
# 1. _load_architect_plan
# ---------------------------------------------------------------------------

class TestLoadArchitectPlan:
    def test_loads_from_real_speed_defects(self):
        logs = Path(".speed/features/speed-defects/logs")
        if not list(logs.glob("Architect-*.jsonl")):
            pytest.skip("speed-defects Architect JSONL not found")
        plan = _load_architect_plan(logs)
        assert plan is not None
        assert "tasks" in plan
        assert len(plan["tasks"]) == 10

    def test_no_architect_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            assert _load_architect_plan(Path(tmpdir)) is None

    def test_empty_jsonl(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "Architect-123.jsonl").write_text("")
            assert _load_architect_plan(Path(tmpdir)) is None

    def test_no_structured_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "Architect-123.jsonl").write_text(
                json.dumps({"type": "result"}) + "\n")
            assert _load_architect_plan(Path(tmpdir)) is None

    def test_non_dict_structured_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "Architect-123.jsonl").write_text(
                json.dumps({"structured_output": "string"}) + "\n")
            assert _load_architect_plan(Path(tmpdir)) is None

    def test_uses_newest_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "Architect-100.jsonl").write_text(
                json.dumps({"structured_output": {"tasks": [{"id": "old"}]}})
                + "\n")
            (Path(tmpdir) / "Architect-200.jsonl").write_text(
                json.dumps({"structured_output": {"tasks": [{"id": "new"}]}})
                + "\n")
            plan = _load_architect_plan(Path(tmpdir))
            assert plan["tasks"][0]["id"] == "new"

    def test_malformed_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "Architect-123.jsonl").write_text("not json\n")
            assert _load_architect_plan(Path(tmpdir)) is None

    def test_multi_line_jsonl_uses_last(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lines = [
                json.dumps({"type": "init", "session_id": "abc"}),
                json.dumps({"type": "result",
                            "structured_output": {"tasks": [{"id": "1"}]}}),
            ]
            (Path(tmpdir) / "Architect-123.jsonl").write_text(
                "\n".join(lines) + "\n")
            plan = _load_architect_plan(Path(tmpdir))
            assert plan is not None
            assert plan["tasks"][0]["id"] == "1"


# ---------------------------------------------------------------------------
# 2. scope_too_broad
# ---------------------------------------------------------------------------

class TestScopeTooBroad:
    def test_extras_exceed_threshold(self):
        plan = make_plan([{"id": "1", "files_touched": ["a.py"]}])
        tasks = {"1": {"files_touched": ["a.py", "b.py", "c.py"]}}
        result = ExtractResult()
        _step8_decomposition_quality("test", tasks, plan, result)
        assert len(result.observations) == 1
        assert result.observations[0].detail["issue"] == "scope_too_broad"

    def test_weight_is_2(self):
        plan = make_plan([{"id": "1", "files_touched": ["a.py"]}])
        tasks = {"1": {"files_touched": ["a.py", "b.py", "c.py"]}}
        result = ExtractResult()
        _step8_decomposition_quality("test", tasks, plan, result)
        assert result.observations[0].weight == 2.0


# ---------------------------------------------------------------------------
# 3. missing_dependency
# ---------------------------------------------------------------------------

class TestMissingDependency:
    def test_missing_no_extras(self):
        plan = make_plan([{"id": "1",
                           "files_touched": ["a.py", "b.py"]}])
        tasks = {"1": {"files_touched": ["a.py"]}}
        result = ExtractResult()
        _step8_decomposition_quality("test", tasks, plan, result)
        assert len(result.observations) == 1
        assert result.observations[0].detail["issue"] == "missing_dependency"


# ---------------------------------------------------------------------------
# 4. boundary_mismatch
# ---------------------------------------------------------------------------

class TestBoundaryMismatch:
    def test_both_extras_and_missing(self):
        plan = make_plan([{"id": "1",
                           "files_touched": ["a.py", "b.py", "c.py"]}])
        tasks = {"1": {"files_touched": ["a.py", "d.py"]}}
        result = ExtractResult()
        _step8_decomposition_quality("test", tasks, plan, result)
        assert len(result.observations) == 1
        assert result.observations[0].detail["issue"] == "boundary_mismatch"

    def test_complete_swap_single_file(self):
        """planned=[a.py], actual=[b.py] — wrong file, not scope creep."""
        plan = make_plan([{"id": "1", "files_touched": ["a.py"]}])
        tasks = {"1": {"files_touched": ["b.py"]}}
        result = ExtractResult()
        _step8_decomposition_quality("test", tasks, plan, result)
        assert len(result.observations) == 1
        assert result.observations[0].detail["issue"] == "boundary_mismatch"

    def test_complete_swap_multiple_files(self):
        """planned=[a,b,c], actual=[d,e,f] — all different."""
        plan = make_plan([{"id": "1",
                           "files_touched": ["a.py", "b.py", "c.py"]}])
        tasks = {"1": {"files_touched": ["d.py", "e.py", "f.py"]}}
        result = ExtractResult()
        _step8_decomposition_quality("test", tasks, plan, result)
        assert len(result.observations) == 1
        assert result.observations[0].detail["issue"] == "boundary_mismatch"


# ---------------------------------------------------------------------------
# 5. Exact match → no observation
# ---------------------------------------------------------------------------

class TestExactMatch:
    def test_perfect_match(self):
        plan = make_plan([{"id": "1",
                           "files_touched": ["a.py", "b.py"]}])
        tasks = {"1": {"files_touched": ["a.py", "b.py"]}}
        result = ExtractResult()
        _step8_decomposition_quality("test", tasks, plan, result)
        assert len(result.observations) == 0
        assert len(result.warnings) == 0


# ---------------------------------------------------------------------------
# 6. Common properties
# ---------------------------------------------------------------------------

class TestCommonProperties:
    def test_stage_is_architect(self):
        plan = make_plan([{"id": "1", "files_touched": ["a.py"]}])
        tasks = {"1": {"files_touched": ["a.py", "b.py", "c.py"]}}
        result = ExtractResult()
        _step8_decomposition_quality("test", tasks, plan, result)
        assert all(o.stage == "architect" for o in result.observations)

    def test_task_id_is_per_task(self):
        plan = make_plan([{"id": "3", "files_touched": ["a.py"]}])
        tasks = {"3": {"files_touched": ["a.py", "b.py", "c.py"]}}
        result = ExtractResult()
        _step8_decomposition_quality("test", tasks, plan, result)
        assert all(o.task_id == "3" for o in result.observations)

    def test_observation_type(self):
        plan = make_plan([{"id": "1", "files_touched": ["a.py"]}])
        tasks = {"1": {"files_touched": ["a.py", "b.py", "c.py"]}}
        result = ExtractResult()
        _step8_decomposition_quality("test", tasks, plan, result)
        assert all(o.observation_type == "decomposition_miss"
                    for o in result.observations)

    def test_detail_has_planned_and_actual(self):
        plan = make_plan([{"id": "1", "files_touched": ["a.py"]}])
        tasks = {"1": {"files_touched": ["a.py", "b.py"]}}
        result = ExtractResult()
        _step8_decomposition_quality("test", tasks, plan, result)
        d = result.observations[0].detail
        assert "planned_files" in d
        assert "actual_files" in d
        assert "analysis" in d


# ---------------------------------------------------------------------------
# 7. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_no_plan(self):
        result = ExtractResult()
        _step8_decomposition_quality("test", {"1": {}}, None, result)
        assert len(result.warnings) == 1
        assert "no Architect plan" in result.warnings[0]
        assert len(result.observations) == 0

    def test_empty_tasks(self):
        plan = make_plan([{"id": "1", "files_touched": ["a.py"]}])
        result = ExtractResult()
        _step8_decomposition_quality("test", {}, plan, result)
        assert len(result.observations) == 0

    def test_task_not_in_plan(self):
        plan = make_plan([{"id": "1", "files_touched": ["a.py"]}])
        tasks = {"10a": {"files_touched": ["speed"]}}
        result = ExtractResult()
        _step8_decomposition_quality("test", tasks, plan, result)
        assert len(result.observations) == 0

    def test_both_empty_files(self):
        plan = make_plan([{"id": "1", "files_touched": []}])
        tasks = {"1": {"files_touched": []}}
        result = ExtractResult()
        _step8_decomposition_quality("test", tasks, plan, result)
        assert len(result.observations) == 0

    def test_idempotency(self):
        plan = make_plan([{"id": "1", "files_touched": ["a.py"]}])
        tasks = {"1": {"files_touched": ["a.py", "b.py", "c.py"]}}
        r1 = ExtractResult()
        _step8_decomposition_quality("test", tasks, plan, r1)
        r2 = ExtractResult()
        _step8_decomposition_quality("test", tasks, plan, r2)
        assert ([o.id for o in r1.observations]
                == [o.id for o in r2.observations])

    def test_multi_task_mix(self):
        plan = make_plan([
            {"id": "1", "files_touched": ["a.py"]},
            {"id": "2", "files_touched": ["b.py"]},
            {"id": "3", "files_touched": ["c.py"]},
        ])
        tasks = {
            "1": {"files_touched": ["a.py"]},          # match
            "2": {"files_touched": ["b.py", "d.py"]},  # scope_too_broad
            "3": {"files_touched": ["c.py"]},           # match
        }
        result = ExtractResult()
        _step8_decomposition_quality("test", tasks, plan, result)
        assert len(result.observations) == 1
        assert result.observations[0].task_id == "2"


# ---------------------------------------------------------------------------
# 8. Real data: speed-defects (all match → 0 observations)
# ---------------------------------------------------------------------------

class TestRealSpeedDefects:
    @pytest.fixture
    def result(self):
        logs = Path(".speed/features/speed-defects/logs")
        tasks_dir = Path(".speed/features/speed-defects/tasks")
        if not list(logs.glob("Architect-*.jsonl")):
            pytest.skip("speed-defects Architect JSONL not available")
        plan = _load_architect_plan(logs)
        tasks = {}
        for tf in sorted(tasks_dir.glob("*.json")):
            tasks[tf.stem] = json.loads(tf.read_text())
        result = ExtractResult()
        _step8_decomposition_quality("speed-defects", tasks, plan, result)
        return result

    def test_zero_observations(self, result):
        assert len(result.observations) == 0

    def test_no_warnings(self, result):
        assert len(result.warnings) == 0


# ---------------------------------------------------------------------------
# 9. Real data: find-your-tribe features
# ---------------------------------------------------------------------------

class TestRealFytRichFeed:
    @pytest.fixture
    def result(self):
        fyt = Path("/Users/sanjay.kotagiri/Documents/code/tmp/find-your-tribe")
        logs = fyt / ".speed/features/f10-rich-feed/logs"
        tasks_dir = fyt / ".speed/features/f10-rich-feed/tasks"
        if not list(logs.glob("Architect-*.jsonl")):
            pytest.skip("f10-rich-feed Architect JSONL not available")
        plan = _load_architect_plan(logs)
        tasks = {}
        for tf in sorted(tasks_dir.glob("*.json")):
            tasks[tf.stem] = json.loads(tf.read_text())
        result = ExtractResult()
        _step8_decomposition_quality("f10-rich-feed", tasks, plan, result)
        return result

    def test_zero_observations(self, result):
        assert len(result.observations) == 0


class TestRealFytProfileCompleteness:
    @pytest.fixture
    def result(self):
        fyt = Path("/Users/sanjay.kotagiri/Documents/code/tmp/find-your-tribe")
        logs = fyt / ".speed/features/f9-profile-completeness/logs"
        tasks_dir = fyt / ".speed/features/f9-profile-completeness/tasks"
        if not list(logs.glob("Architect-*.jsonl")):
            pytest.skip("f9-profile-completeness not available")
        plan = _load_architect_plan(logs)
        tasks = {}
        for tf in sorted(tasks_dir.glob("*.json")):
            tasks[tf.stem] = json.loads(tf.read_text())
        result = ExtractResult()
        _step8_decomposition_quality("f9-profile-completeness", tasks,
                                      plan, result)
        return result

    def test_zero_observations(self, result):
        assert len(result.observations) == 0


class TestRealFytSeedOnboarding:
    @pytest.fixture
    def result(self):
        fyt = Path("/Users/sanjay.kotagiri/Documents/code/tmp/find-your-tribe")
        logs = fyt / ".speed/features/seed-onboarding-flag/logs"
        tasks_dir = fyt / ".speed/features/seed-onboarding-flag/tasks"
        if not list(logs.glob("Architect-*.jsonl")):
            pytest.skip("seed-onboarding-flag not available")
        plan = _load_architect_plan(logs)
        tasks = {}
        for tf in sorted(tasks_dir.glob("*.json")):
            tasks[tf.stem] = json.loads(tf.read_text())
        result = ExtractResult()
        _step8_decomposition_quality("seed-onboarding-flag", tasks,
                                      plan, result)
        return result

    def test_zero_observations(self, result):
        assert len(result.observations) == 0


# ---------------------------------------------------------------------------
# 10. Real data: speed-security (no Architect JSONL → warning)
# ---------------------------------------------------------------------------

class TestRealSpeedSecurity:
    def test_no_architect_jsonl(self):
        logs = Path(".speed/features/speed-security/logs")
        plan = _load_architect_plan(logs)
        assert plan is None
        result = ExtractResult()
        _step8_decomposition_quality("speed-security", {}, plan, result)
        assert len(result.warnings) == 1
        assert len(result.observations) == 0
