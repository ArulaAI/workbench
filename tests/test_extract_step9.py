#!/usr/bin/env python3
"""Tests for Step 9: Success Observations — against real extract.py."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from learn.extract import (
    _step9_success_observations,
    _load_architect_plan,
    _NON_BLOCKING_TYPES,
    ExtractResult,
    Observation,
    _make_obs,
    extract_observations,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_obs(task_id, obs_type, detail=None, stage="reviewer"):
    return _make_obs("test", stage, task_id, obs_type, detail or {})


def build_task_issues(observations):
    """Reproduce the blocking logic from extract_observations."""
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


def run_step9(tasks, plan=None, prior_obs=None):
    task_issues = build_task_issues(prior_obs or [])
    result = ExtractResult()
    if prior_obs:
        result.observations = list(prior_obs)
    _step9_success_observations("test", tasks, task_issues, plan, result)
    return [o for o in result.observations if o.observation_type == "success"]


# ---------------------------------------------------------------------------
# 1. Blocking logic — non-blocking types
# ---------------------------------------------------------------------------

class TestBlockingNonBlocking:
    def test_nit_does_not_block(self):
        prior = [make_obs("1", "reviewer_finding", {"severity": "nit"})]
        tasks = {"1": {"status": "done", "files_touched": ["a.py"]}}
        successes = run_step9(tasks, prior_obs=prior)
        assert len(successes) == 1

    def test_positive_does_not_block(self):
        prior = [make_obs("1", "reviewer_finding", {"severity": "positive"})]
        tasks = {"1": {"status": "done", "files_touched": ["a.py"]}}
        successes = run_step9(tasks, prior_obs=prior)
        assert len(successes) == 1

    def test_agent_concern_does_not_block(self):
        prior = [make_obs("1", "agent_concern", {}, stage="developer")]
        tasks = {"1": {"status": "done", "files_touched": ["a.py"]}}
        successes = run_step9(tasks, prior_obs=prior)
        assert len(successes) == 1

    def test_context_miss_does_not_block(self):
        prior = [make_obs("1", "context_miss", {"file": "a.py"}, stage="context")]
        tasks = {"1": {"status": "done", "files_touched": ["a.py"]}}
        successes = run_step9(tasks, prior_obs=prior)
        assert len(successes) == 1

    def test_context_waste_does_not_block(self):
        prior = [make_obs("1", "context_waste", {}, stage="context")]
        tasks = {"1": {"status": "done", "files_touched": ["a.py"]}}
        successes = run_step9(tasks, prior_obs=prior)
        assert len(successes) == 1

    def test_decomposition_miss_does_not_block(self):
        prior = [make_obs("1", "decomposition_miss", {}, stage="architect")]
        tasks = {"1": {"status": "done", "files_touched": ["a.py"]}}
        successes = run_step9(tasks, prior_obs=prior)
        assert len(successes) == 1


# ---------------------------------------------------------------------------
# 2. Blocking logic — blocking types
# ---------------------------------------------------------------------------

class TestBlockingTypes:
    def test_retry_blocks(self):
        prior = [make_obs("1", "retry", {}, stage="developer")]
        tasks = {"1": {"status": "done", "files_touched": ["a.py"]}}
        successes = run_step9(tasks, prior_obs=prior)
        assert len(successes) == 0

    def test_gate_failure_blocks(self):
        prior = [make_obs("1", "gate_failure", {}, stage="developer")]
        tasks = {"1": {"status": "done", "files_touched": ["a.py"]}}
        successes = run_step9(tasks, prior_obs=prior)
        assert len(successes) == 0

    def test_guardian_verdict_blocks(self):
        prior = [make_obs("1", "guardian_verdict",
                          {"verdict": "rejected"}, stage="guardian")]
        tasks = {"1": {"status": "done", "files_touched": ["a.py"]}}
        successes = run_step9(tasks, prior_obs=prior)
        assert len(successes) == 0

    def test_minor_reviewer_finding_blocks(self):
        prior = [make_obs("1", "reviewer_finding", {"severity": "minor"})]
        tasks = {"1": {"status": "done", "files_touched": ["a.py"]}}
        successes = run_step9(tasks, prior_obs=prior)
        assert len(successes) == 0

    def test_major_reviewer_finding_blocks(self):
        prior = [make_obs("1", "reviewer_finding", {"severity": "major"})]
        tasks = {"1": {"status": "done", "files_touched": ["a.py"]}}
        successes = run_step9(tasks, prior_obs=prior)
        assert len(successes) == 0

    def test_star_task_id_does_not_block(self):
        prior = [make_obs("*", "verify_finding", {}, stage="verifier")]
        tasks = {"1": {"status": "done", "files_touched": ["a.py"]}}
        successes = run_step9(tasks, prior_obs=prior)
        assert len(successes) == 1


# ---------------------------------------------------------------------------
# 3. Success detail fields
# ---------------------------------------------------------------------------

class TestSuccessDetail:
    def test_agent_model(self):
        tasks = {"1": {"status": "done", "agent_model": "sonnet",
                       "files_touched": ["a.py"]}}
        successes = run_step9(tasks)
        assert successes[0].detail["agent_model"] == "sonnet"

    def test_agent_model_missing(self):
        tasks = {"1": {"status": "done", "files_touched": ["a.py"]}}
        successes = run_step9(tasks)
        assert successes[0].detail["agent_model"] == ""

    def test_files_planned_from_plan(self):
        tasks = {"1": {"status": "done", "files_touched": ["a.py", "b.py"]}}
        plan = {"tasks": [{"id": "1", "files_touched": ["a.py", "b.py", "c.py"]}]}
        successes = run_step9(tasks, plan=plan)
        assert successes[0].detail["files_planned"] == 3
        assert successes[0].detail["files_actual"] == 2

    def test_files_planned_fallback_no_plan(self):
        tasks = {"1": {"status": "done", "files_touched": ["a.py", "b.py"]}}
        successes = run_step9(tasks, plan=None)
        assert successes[0].detail["files_planned"] == 2

    def test_guardian_no_check(self):
        tasks = {"1": {"status": "done", "files_touched": ["a.py"]}}
        successes = run_step9(tasks)
        assert successes[0].detail["guardian"] == "no_check"

    def test_guardian_from_observations(self):
        prior = [make_obs("2", "guardian_verdict",
                          {"verdict": "aligned"}, stage="guardian")]
        tasks = {"1": {"status": "done", "files_touched": ["a.py"]},
                 "2": {"status": "done", "files_touched": ["b.py"]}}
        # Task 2 has guardian_verdict which blocks it
        successes = run_step9(tasks, prior_obs=prior)
        # Only task 1 succeeds (task 2 blocked by guardian_verdict)
        assert len(successes) == 1
        assert successes[0].task_id == "1"

    def test_duration(self):
        tasks = {"1": {"status": "done", "files_touched": ["a.py"],
                       "started_at": "2026-03-01T10:00:00Z",
                       "completed_at": "2026-03-01T10:05:00Z"}}
        successes = run_step9(tasks)
        assert successes[0].detail["duration_seconds"] == 300

    def test_retry_count_always_zero(self):
        tasks = {"1": {"status": "done", "files_touched": ["a.py"]}}
        successes = run_step9(tasks)
        assert successes[0].detail["retry_count"] == 0

    def test_no_fake_fields(self):
        tasks = {"1": {"status": "done", "files_touched": ["a.py"]}}
        successes = run_step9(tasks)
        d = successes[0].detail
        assert "context_misses" not in d
        assert "context_waste_count" not in d
        assert "verify_clean" not in d
        assert "coherence_clean" not in d
        assert "security_clean" not in d
        assert "conditions" not in d


# ---------------------------------------------------------------------------
# 4. Common properties
# ---------------------------------------------------------------------------

class TestCommonProperties:
    def test_stage_is_developer(self):
        tasks = {"1": {"status": "done", "files_touched": ["a.py"]}}
        successes = run_step9(tasks)
        assert all(s.stage == "developer" for s in successes)

    def test_weight_is_0_5(self):
        tasks = {"1": {"status": "done", "files_touched": ["a.py"]}}
        successes = run_step9(tasks)
        assert all(s.weight == 0.5 for s in successes)

    def test_observation_type(self):
        tasks = {"1": {"status": "done", "files_touched": ["a.py"]}}
        successes = run_step9(tasks)
        assert all(s.observation_type == "success" for s in successes)

    def test_per_task_id(self):
        tasks = {"3": {"status": "done", "files_touched": ["a.py"]}}
        successes = run_step9(tasks)
        assert successes[0].task_id == "3"


# ---------------------------------------------------------------------------
# 5. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_non_done_skipped(self):
        tasks = {"1": {"status": "error", "files_touched": []}}
        successes = run_step9(tasks)
        assert len(successes) == 0

    def test_empty_tasks(self):
        successes = run_step9({})
        assert len(successes) == 0

    def test_idempotency(self):
        tasks = {"1": {"status": "done", "agent_model": "sonnet",
                       "files_touched": ["a.py"]}}
        s1 = run_step9(tasks)
        s2 = run_step9(tasks)
        assert [o.id for o in s1] == [o.id for o in s2]

    def test_multi_task_mix(self):
        prior = [make_obs("2", "retry", {}, stage="developer")]
        tasks = {
            "1": {"status": "done", "files_touched": ["a.py"]},
            "2": {"status": "done", "files_touched": ["b.py"]},
            "3": {"status": "done", "files_touched": ["c.py"]},
        }
        successes = run_step9(tasks, prior_obs=prior)
        assert len(successes) == 2
        assert set(s.task_id for s in successes) == {"1", "3"}


# ---------------------------------------------------------------------------
# 6. Real data: speed-defects (5 successes)
# ---------------------------------------------------------------------------

class TestRealSpeedDefects:
    @pytest.fixture
    def successes(self):
        feat = Path(".speed/features/speed-defects")
        mem = Path(".speed/memory")
        if not feat.exists():
            pytest.skip("speed-defects not available")
        result = extract_observations(feat, mem)
        return [o for o in result.observations if o.observation_type == "success"]

    def test_count(self, successes):
        assert len(successes) == 5

    def test_expected_tasks(self, successes):
        ids = set(s.task_id for s in successes)
        assert ids == {"4", "5", "9", "10b", "10c"}

    def test_all_have_agent_model(self, successes):
        assert all(s.detail.get("agent_model", "") != "" for s in successes)

    def test_all_weight_0_5(self, successes):
        assert all(s.weight == 0.5 for s in successes)


# ---------------------------------------------------------------------------
# 7. Real data: f9-profile-completeness (4 successes)
# ---------------------------------------------------------------------------

class TestRealF9ProfileCompleteness:
    @pytest.fixture
    def successes(self):
        fyt = Path("/Users/sanjay.kotagiri/Documents/code/tmp/find-your-tribe")
        feat = fyt / ".speed/features/f9-profile-completeness"
        mem = fyt / ".speed/memory"
        if not feat.exists():
            pytest.skip("f9-profile-completeness not available")
        if not mem.exists():
            mem.mkdir(parents=True, exist_ok=True)
        result = extract_observations(feat, mem)
        return [o for o in result.observations if o.observation_type == "success"]

    def test_count(self, successes):
        assert len(successes) == 4

    def test_expected_tasks(self, successes):
        ids = set(s.task_id for s in successes)
        assert ids == {"2", "3", "5", "7"}

    def test_agent_model_is_sonnet(self, successes):
        assert all(s.detail["agent_model"] == "sonnet" for s in successes)

    def test_files_planned_from_plan(self, successes):
        # All f9 tasks have plan data
        for s in successes:
            assert s.detail["files_planned"] > 0


# ---------------------------------------------------------------------------
# 8. Real data: speed-security (1 success)
# ---------------------------------------------------------------------------

class TestRealSpeedSecurity:
    @pytest.fixture
    def successes(self):
        feat = Path(".speed/features/speed-security")
        mem = Path(".speed/memory")
        if not feat.exists():
            pytest.skip("speed-security not available")
        result = extract_observations(feat, mem)
        return [o for o in result.observations if o.observation_type == "success"]

    def test_count(self, successes):
        assert len(successes) == 1

    def test_task_11(self, successes):
        assert successes[0].task_id == "11"

    def test_files_planned_fallback(self, successes):
        # No architect plan for speed-security
        s = successes[0]
        assert s.detail["files_planned"] == s.detail["files_actual"]
