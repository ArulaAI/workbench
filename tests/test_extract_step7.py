#!/usr/bin/env python3
"""Tests for Step 7: Context Effectiveness — against real extract.py."""

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from learn.extract import _step7_context_effectiveness, ExtractResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_context_dir(task_contexts: dict) -> Path:
    """Create a temp context base with code-context.json files per task.

    task_contexts: {task_id: code_context_dict}
    Returns the context_base path (.../tasks/).
    """
    tmpdir = Path(tempfile.mkdtemp())
    for task_id, cc_data in task_contexts.items():
        cc_dir = tmpdir / str(task_id) / "context"
        cc_dir.mkdir(parents=True)
        (cc_dir / "code-context.json").write_text(json.dumps(cc_data))
    return tmpdir


def make_cc(seed_files: list[str], one_hop: list[str] | None = None,
            two_hop: list[str] | None = None,
            total_tokens: int = 5000) -> dict:
    """Build a minimal code-context.json dict."""
    fc: dict = {
        "files_touched": [{"path": p} for p in seed_files],
    }
    if one_hop is not None:
        fc["one_hop"] = {p: "content" for p in one_hop}
    else:
        fc["one_hop"] = {}

    sk: dict = {}
    if two_hop is not None:
        sk["two_hop"] = [{"path": p} for p in two_hop]

    return {
        "full_content": fc,
        "skeleton": sk,
        "expansion_summary": {"total_tokens_estimate": total_tokens},
    }


def run_step7(tasks: dict[str, dict], task_contexts: dict) -> ExtractResult:
    """Run Step 7 with synthetic data."""
    context_base = make_context_dir(task_contexts)
    result = ExtractResult()
    _step7_context_effectiveness("test-feature", tasks, context_base, result)
    return result


# ---------------------------------------------------------------------------
# 1. Context misses
# ---------------------------------------------------------------------------

class TestContextMiss:
    def test_single_miss(self):
        tasks = {"1": {"files_touched": ["a.py", "b.py"], "status": "done"}}
        cc = make_cc(seed_files=["a.py"])
        result = run_step7(tasks, {"1": cc})
        misses = [o for o in result.observations
                  if o.observation_type == "context_miss"]
        assert len(misses) == 1
        assert misses[0].detail["file"] == "b.py"

    def test_no_miss_when_all_covered(self):
        tasks = {"1": {"files_touched": ["a.py", "b.py"], "status": "done"}}
        cc = make_cc(seed_files=["a.py"], one_hop=["b.py"])
        result = run_step7(tasks, {"1": cc})
        misses = [o for o in result.observations
                  if o.observation_type == "context_miss"]
        assert len(misses) == 0

    def test_multiple_misses(self):
        tasks = {"1": {"files_touched": ["a.py", "b.py", "c.py"],
                       "status": "done"}}
        cc = make_cc(seed_files=["a.py"])
        result = run_step7(tasks, {"1": cc})
        misses = [o for o in result.observations
                  if o.observation_type == "context_miss"]
        assert len(misses) == 2
        miss_files = {m.detail["file"] for m in misses}
        assert miss_files == {"b.py", "c.py"}

    def test_miss_has_task_files_declared(self):
        tasks = {"1": {"files_touched": ["a.py", "b.py"], "status": "done"}}
        cc = make_cc(seed_files=["a.py"])
        result = run_step7(tasks, {"1": cc})
        miss = [o for o in result.observations
                if o.observation_type == "context_miss"][0]
        assert miss.detail["task_files_declared"] == ["a.py"]

    def test_skeleton_tier_counts(self):
        """Two-hop skeleton files should count as provided."""
        tasks = {"1": {"files_touched": ["a.py", "b.py"], "status": "done"}}
        cc = make_cc(seed_files=["a.py"], two_hop=["b.py"])
        result = run_step7(tasks, {"1": cc})
        misses = [o for o in result.observations
                  if o.observation_type == "context_miss"]
        assert len(misses) == 0

    def test_weight_is_1_5(self):
        tasks = {"1": {"files_touched": ["a.py", "b.py"], "status": "done"}}
        cc = make_cc(seed_files=["a.py"])
        result = run_step7(tasks, {"1": cc})
        miss = [o for o in result.observations
                if o.observation_type == "context_miss"][0]
        assert miss.weight == 1.5


# ---------------------------------------------------------------------------
# 2. Context waste
# ---------------------------------------------------------------------------

class TestContextWaste:
    def test_extreme_waste_emitted(self):
        """46 provided, 1 used → 98% waste, should emit."""
        one_hop = [f"file_{i}.py" for i in range(45)]
        tasks = {"1": {"files_touched": ["seed.py"], "status": "done"}}
        cc = make_cc(seed_files=["seed.py"], one_hop=one_hop,
                     total_tokens=97000)
        result = run_step7(tasks, {"1": cc})
        waste = [o for o in result.observations
                 if o.observation_type == "context_waste"]
        assert len(waste) == 1
        assert waste[0].detail["waste_ratio"] == 0.98
        assert waste[0].detail["provided_count"] == 46
        assert waste[0].detail["used_count"] == 1
        assert waste[0].detail["total_tokens_estimate"] == 97000

    def test_moderate_waste_not_emitted(self):
        """3 provided, 2 used → 33% waste, below threshold."""
        tasks = {"1": {"files_touched": ["a.py", "b.py"], "status": "done"}}
        cc = make_cc(seed_files=["a.py", "b.py"], one_hop=["c.py"])
        result = run_step7(tasks, {"1": cc})
        waste = [o for o in result.observations
                 if o.observation_type == "context_waste"]
        assert len(waste) == 0

    def test_small_set_high_ratio_not_emitted(self):
        """5 provided, 0 used → 100% waste but only 5 files, below min."""
        one_hop = [f"oh_{i}.py" for i in range(4)]
        tasks = {"1": {"files_touched": ["new.py"], "status": "done"}}
        cc = make_cc(seed_files=["seed.py"], one_hop=one_hop)
        result = run_step7(tasks, {"1": cc})
        waste = [o for o in result.observations
                 if o.observation_type == "context_waste"]
        assert len(waste) == 0

    def test_weight_is_0_5(self):
        one_hop = [f"file_{i}.py" for i in range(20)]
        tasks = {"1": {"files_touched": ["seed.py"], "status": "done"}}
        cc = make_cc(seed_files=["seed.py"], one_hop=one_hop)
        result = run_step7(tasks, {"1": cc})
        waste = [o for o in result.observations
                 if o.observation_type == "context_waste"]
        assert len(waste) == 1
        assert waste[0].weight == 0.5


# ---------------------------------------------------------------------------
# 3. Multi-task
# ---------------------------------------------------------------------------

class TestMultiTask:
    def test_independent_tasks(self):
        tasks = {
            "1": {"files_touched": ["a.py", "b.py"], "status": "done"},
            "2": {"files_touched": ["c.py", "d.py"], "status": "done"},
        }
        ccs = {
            "1": make_cc(seed_files=["a.py"]),
            "2": make_cc(seed_files=["c.py", "d.py"]),
        }
        result = run_step7(tasks, ccs)
        misses = [o for o in result.observations
                  if o.observation_type == "context_miss"]
        assert len(misses) == 1
        assert misses[0].detail["file"] == "b.py"
        assert misses[0].task_id == "1"

    def test_task_without_context_skipped(self):
        tasks = {
            "1": {"files_touched": ["a.py"], "status": "done"},
            "2": {"files_touched": ["b.py", "c.py"], "status": "done"},
        }
        # Only task 1 has context
        ccs = {"1": make_cc(seed_files=["a.py"])}
        result = run_step7(tasks, ccs)
        misses = [o for o in result.observations
                  if o.observation_type == "context_miss"]
        assert len(misses) == 0  # Task 2 skipped, task 1 fully covered


# ---------------------------------------------------------------------------
# 4. Common properties
# ---------------------------------------------------------------------------

class TestCommonProperties:
    def test_stage_is_context(self):
        tasks = {"1": {"files_touched": ["a.py", "b.py"], "status": "done"}}
        cc = make_cc(seed_files=["a.py"])
        result = run_step7(tasks, {"1": cc})
        assert all(o.stage == "context" for o in result.observations)

    def test_task_id_is_per_task(self):
        tasks = {"3": {"files_touched": ["a.py", "b.py"], "status": "done"}}
        cc = make_cc(seed_files=["a.py"])
        result = run_step7(tasks, {"3": cc})
        assert all(o.task_id == "3" for o in result.observations)

    def test_observation_types(self):
        one_hop = [f"f_{i}.py" for i in range(20)]
        tasks = {"1": {"files_touched": ["seed.py", "new.py"],
                       "status": "done"}}
        cc = make_cc(seed_files=["seed.py"], one_hop=one_hop)
        result = run_step7(tasks, {"1": cc})
        types = {o.observation_type for o in result.observations}
        assert types == {"context_miss", "context_waste"}


# ---------------------------------------------------------------------------
# 5. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_no_context_base(self):
        result = ExtractResult()
        _step7_context_effectiveness("test", {"1": {}}, None, result)
        assert len(result.warnings) == 1
        assert "no context directory" in result.warnings[0]
        assert len(result.observations) == 0

    def test_nonexistent_context_base(self):
        result = ExtractResult()
        _step7_context_effectiveness("test", {"1": {}},
                                      Path("/nonexistent"), result)
        assert len(result.warnings) == 1
        assert len(result.observations) == 0

    def test_empty_context_base(self):
        tmpdir = Path(tempfile.mkdtemp())
        tasks = {"1": {"files_touched": ["a.py"], "status": "done"}}
        result = ExtractResult()
        _step7_context_effectiveness("test", tasks, tmpdir, result)
        assert len(result.warnings) == 1
        assert "no code-context.json" in result.warnings[0]
        assert len(result.observations) == 0

    def test_task_with_no_files_touched(self):
        tasks = {"1": {"files_touched": [], "status": "done"}}
        cc = make_cc(seed_files=["a.py"])
        result = run_step7(tasks, {"1": cc})
        assert len(result.observations) == 0

    def test_malformed_context_json(self):
        tmpdir = Path(tempfile.mkdtemp())
        cc_dir = tmpdir / "1" / "context"
        cc_dir.mkdir(parents=True)
        (cc_dir / "code-context.json").write_text("not json")
        tasks = {"1": {"files_touched": ["a.py"], "status": "done"}}
        result = ExtractResult()
        _step7_context_effectiveness("test", tasks, tmpdir, result)
        assert len(result.warnings) == 1
        assert len(result.observations) == 0

    def test_idempotency(self):
        tasks = {"1": {"files_touched": ["a.py", "b.py"], "status": "done"}}
        cc = make_cc(seed_files=["a.py"])
        r1 = run_step7(tasks, {"1": cc})
        r2 = run_step7(tasks, {"1": cc})
        assert ([o.id for o in r1.observations]
                == [o.id for o in r2.observations])

    def test_one_hop_as_list(self):
        """one_hop can be a list of dicts instead of a dict."""
        cc = {
            "full_content": {
                "files_touched": [{"path": "a.py"}],
                "one_hop": [{"path": "b.py"}, {"path": "c.py"}],
            },
            "skeleton": {},
            "expansion_summary": {},
        }
        tasks = {"1": {"files_touched": ["a.py", "b.py"], "status": "done"}}
        result = run_step7(tasks, {"1": cc})
        misses = [o for o in result.observations
                  if o.observation_type == "context_miss"]
        assert len(misses) == 0  # b.py covered by one_hop list

    def test_two_hop_as_dict(self):
        """skeleton.two_hop can be a dict instead of a list."""
        cc = {
            "full_content": {
                "files_touched": [{"path": "a.py"}],
                "one_hop": {},
            },
            "skeleton": {"two_hop": {"b.py": "skeleton content"}},
            "expansion_summary": {},
        }
        tasks = {"1": {"files_touched": ["a.py", "b.py"], "status": "done"}}
        result = run_step7(tasks, {"1": cc})
        misses = [o for o in result.observations
                  if o.observation_type == "context_miss"]
        assert len(misses) == 0


# ---------------------------------------------------------------------------
# 6. Real data: find-your-tribe seed-onboarding-flag task 1
# ---------------------------------------------------------------------------

class TestRealSeedOnboarding:
    @pytest.fixture
    def result(self):
        fyt = Path("/Users/sanjay.kotagiri/Documents/code/tmp/find-your-tribe")
        context_base = fyt / ".speed/context/tasks"
        task_path = fyt / ".speed/features/seed-onboarding-flag/tasks/1.json"
        if not task_path.exists() or not (context_base / "1/context/code-context.json").exists():
            pytest.skip("seed-onboarding-flag data not available")
        task = json.loads(task_path.read_text())
        tasks = {"1": task}
        result = ExtractResult()
        _step7_context_effectiveness("seed-onboarding-flag", tasks,
                                      context_base, result)
        return result

    def test_has_context_miss(self, result):
        misses = [o for o in result.observations
                  if o.observation_type == "context_miss"]
        assert len(misses) == 1
        assert "test_seed_users_onboarding" in misses[0].detail["file"]

    def test_has_context_waste(self, result):
        waste = [o for o in result.observations
                 if o.observation_type == "context_waste"]
        assert len(waste) == 1
        assert waste[0].detail["waste_ratio"] >= 0.95

    def test_total_observations(self, result):
        assert len(result.observations) == 2  # 1 miss + 1 waste


# ---------------------------------------------------------------------------
# 7. Real data: find-your-tribe f9-profile-completeness (tasks 5-7)
# ---------------------------------------------------------------------------

class TestRealF9ProfileCompleteness:
    @pytest.fixture
    def result(self):
        fyt = Path("/Users/sanjay.kotagiri/Documents/code/tmp/find-your-tribe")
        context_base = fyt / ".speed/context/tasks"
        feat_dir = fyt / ".speed/features/f9-profile-completeness"
        if not feat_dir.exists():
            pytest.skip("f9-profile-completeness not available")
        # Only tasks 5-7 have valid context (Feb 28 timestamps)
        tasks = {}
        for tid in ["5", "6", "7"]:
            tp = feat_dir / "tasks" / f"{tid}.json"
            cc = context_base / tid / "context" / "code-context.json"
            if tp.exists() and cc.exists():
                tasks[tid] = json.loads(tp.read_text())
        if not tasks:
            pytest.skip("No valid task+context pairs")
        result = ExtractResult()
        _step7_context_effectiveness("f9-profile-completeness", tasks,
                                      context_base, result)
        return result

    def test_has_one_miss(self, result):
        """Task 7 misses the test file."""
        misses = [o for o in result.observations
                  if o.observation_type == "context_miss"]
        assert len(misses) == 1
        assert misses[0].task_id == "7"

    def test_no_waste(self, result):
        """Tasks 5-7 have small context packages, no extreme waste."""
        waste = [o for o in result.observations
                 if o.observation_type == "context_waste"]
        assert len(waste) == 0
