#!/usr/bin/env python3
"""Tests for Step 4: Verify Findings — against real extract.py.

Tests the actual _step4_verify_findings function from lib/learn/extract.py
using both synthetic fixtures and real plan-verification.log data from
speed-defects, speed-security, and find-your-tribe features.
"""

import json
import sys
import tempfile
from pathlib import Path

import pytest

# Add lib/ to path so we can import extract
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from learn.extract import (
    _step4_verify_findings,
    _make_obs,
    ExtractResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_step4(data: dict) -> ExtractResult:
    """Write data to temp file, run Step 4, return result."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        tmp = Path(f.name)
    result = ExtractResult()
    _step4_verify_findings("test-feature", tmp, result)
    tmp.unlink()
    return result


def obs_by_finding_type(result: ExtractResult) -> dict:
    """Group observations by detail.finding_type."""
    grouped = {}
    for o in result.observations:
        ft = o.detail["finding_type"]
        grouped.setdefault(ft, []).append(o)
    return grouped


# ---------------------------------------------------------------------------
# 1. spec_requirements: drifted
# ---------------------------------------------------------------------------

class TestDriftedRequirements:
    def test_drifted_produces_spec_drift(self):
        result = run_step4({
            "spec_requirements": [
                {"requirement": "R1", "status": "drifted",
                 "spec_section": "S1", "notes": "drifted away"}
            ]
        })
        assert len(result.observations) == 1
        obs = result.observations[0]
        assert obs.detail["finding_type"] == "spec_drift"
        assert obs.detail["status"] == "drifted"
        assert obs.detail["requirement"] == "R1"
        assert obs.detail["spec_location"] == "S1"
        assert obs.detail["analysis"] == "drifted away"

    def test_drifted_weight_is_2(self):
        result = run_step4({
            "spec_requirements": [
                {"requirement": "R1", "status": "drifted"}
            ]
        })
        assert result.observations[0].weight == 2.0

    def test_drifted_has_uncertain_field(self):
        result = run_step4({
            "spec_requirements": [
                {"requirement": "R1", "status": "drifted"}
            ]
        })
        assert result.observations[0].detail.get("uncertain") is False


# ---------------------------------------------------------------------------
# 2. spec_requirements: missing
# ---------------------------------------------------------------------------

class TestMissingRequirements:
    def test_missing_produces_missing_requirement(self):
        result = run_step4({
            "spec_requirements": [
                {"requirement": "R2", "status": "missing",
                 "spec_section": "S2", "notes": "not in plan"}
            ]
        })
        assert len(result.observations) == 1
        obs = result.observations[0]
        assert obs.detail["finding_type"] == "missing_requirement"
        assert obs.detail["status"] == "missing"

    def test_missing_weight_is_2(self):
        result = run_step4({
            "spec_requirements": [
                {"requirement": "R2", "status": "missing"}
            ]
        })
        assert result.observations[0].weight == 2.0


# ---------------------------------------------------------------------------
# 3. spec_requirements: partial
# ---------------------------------------------------------------------------

class TestPartialRequirements:
    def test_partial_produces_partial_requirement(self):
        result = run_step4({
            "spec_requirements": [
                {"requirement": "R3", "status": "partial",
                 "spec_section": "S3", "notes": "partially covered"}
            ]
        })
        assert len(result.observations) == 1
        obs = result.observations[0]
        assert obs.detail["finding_type"] == "partial_requirement"
        assert obs.detail["status"] == "partial"

    def test_partial_weight_is_1(self):
        result = run_step4({
            "spec_requirements": [
                {"requirement": "R3", "status": "partial"}
            ]
        })
        assert result.observations[0].weight == 1.0

    def test_partial_with_uncertain_true(self):
        result = run_step4({
            "spec_requirements": [
                {"requirement": "R3", "status": "partial", "uncertain": True,
                 "notes": "no measurement mechanism"}
            ]
        })
        obs = result.observations[0]
        assert obs.detail["uncertain"] is True

    def test_partial_without_uncertain_defaults_false(self):
        result = run_step4({
            "spec_requirements": [
                {"requirement": "R3", "status": "partial"}
            ]
        })
        assert result.observations[0].detail["uncertain"] is False


# ---------------------------------------------------------------------------
# 4. spec_requirements: covered (should produce nothing)
# ---------------------------------------------------------------------------

class TestCoveredRequirements:
    def test_covered_produces_nothing(self):
        result = run_step4({
            "spec_requirements": [
                {"requirement": "R4", "status": "covered",
                 "notes": "fully covered"}
            ]
        })
        assert len(result.observations) == 0

    def test_many_covered_produce_nothing(self):
        result = run_step4({
            "spec_requirements": [
                {"requirement": f"R{i}", "status": "covered"}
                for i in range(15)
            ]
        })
        assert len(result.observations) == 0


# ---------------------------------------------------------------------------
# 5. critical_failures
# ---------------------------------------------------------------------------

class TestCriticalFailures:
    def test_string_failure(self):
        result = run_step4({
            "critical_failures": ["Plan misses auth entirely"]
        })
        assert len(result.observations) == 1
        obs = result.observations[0]
        assert obs.detail["finding_type"] == "critical_failure"
        assert obs.detail["requirement"] == "Plan misses auth entirely"
        assert obs.weight == 2.0

    def test_dict_failure(self):
        result = run_step4({
            "critical_failures": [
                {"description": "No auth", "spec_section": "Security",
                 "analysis": "Missing entirely"}
            ]
        })
        obs = result.observations[0]
        assert obs.detail["finding_type"] == "critical_failure"
        assert obs.detail["requirement"] == "No auth"
        assert obs.detail["spec_location"] == "Security"

    def test_empty_failures(self):
        result = run_step4({"critical_failures": []})
        assert len(result.observations) == 0


# ---------------------------------------------------------------------------
# 6. semantic_drift
# ---------------------------------------------------------------------------

class TestSemanticDrift:
    def test_drift_produces_spec_drift(self):
        result = run_step4({
            "semantic_drift": [
                {"spec_term": "foo", "plan_term": "bar",
                 "risk": "naming mismatch"}
            ]
        })
        assert len(result.observations) == 1
        obs = result.observations[0]
        assert obs.detail["finding_type"] == "spec_drift"
        assert obs.detail["status"] == "drifted"
        assert obs.detail["analysis"] == "naming mismatch"
        assert obs.weight == 2.0

    def test_drift_uses_area_fallback(self):
        result = run_step4({
            "semantic_drift": [
                {"area": "auth module", "risk": "renamed"}
            ]
        })
        assert result.observations[0].detail["requirement"] == "auth module"


# ---------------------------------------------------------------------------
# 7. recommendations
# ---------------------------------------------------------------------------

class TestRecommendations:
    def test_string_recommendation(self):
        result = run_step4({
            "recommendations": ["Fix the template duplication"]
        })
        assert len(result.observations) == 1
        obs = result.observations[0]
        assert obs.detail["finding_type"] == "recommendation"
        assert obs.detail["status"] == "suggested"
        assert obs.detail["requirement"] == "Fix the template duplication"
        assert obs.weight == 1.0

    def test_multiple_recommendations(self):
        result = run_step4({
            "recommendations": ["Rec 1", "Rec 2", "Rec 3"]
        })
        assert len(result.observations) == 3
        assert all(o.weight == 1.0 for o in result.observations)

    def test_non_string_recommendation_skipped(self):
        result = run_step4({
            "recommendations": [{"text": "not a string"}, "valid rec"]
        })
        assert len(result.observations) == 1
        assert result.observations[0].detail["requirement"] == "valid rec"

    def test_empty_recommendations(self):
        result = run_step4({"recommendations": []})
        assert len(result.observations) == 0


# ---------------------------------------------------------------------------
# 8. contract_issues
# ---------------------------------------------------------------------------

class TestContractIssues:
    def test_dict_contract_issue(self):
        result = run_step4({
            "contract_issues": [
                {"type": "missing_function",
                 "description": "get_defect_dir undeclared"}
            ]
        })
        assert len(result.observations) == 1
        obs = result.observations[0]
        assert obs.detail["finding_type"] == "contract_issue"
        assert obs.detail["status"] == "missing_function"
        assert obs.detail["requirement"] == "get_defect_dir undeclared"
        assert obs.weight == 1.5

    def test_non_dict_contract_issue_skipped(self):
        result = run_step4({
            "contract_issues": ["just a string"]
        })
        assert len(result.observations) == 0

    def test_empty_contract_issues(self):
        result = run_step4({"contract_issues": []})
        assert len(result.observations) == 0


# ---------------------------------------------------------------------------
# 9. Common properties
# ---------------------------------------------------------------------------

class TestCommonProperties:
    def test_all_observations_have_star_task_id(self):
        result = run_step4({
            "spec_requirements": [{"requirement": "R1", "status": "drifted"}],
            "recommendations": ["Rec 1"],
            "contract_issues": [{"type": "t", "description": "d"}],
        })
        assert all(o.task_id == "*" for o in result.observations)

    def test_all_observations_have_verifier_source(self):
        result = run_step4({
            "spec_requirements": [{"requirement": "R1", "status": "missing"}],
            "semantic_drift": [{"area": "x", "risk": "y"}],
        })
        assert all(o.stage == "verifier" for o in result.observations)

    def test_all_observations_have_verify_finding_type(self):
        result = run_step4({
            "recommendations": ["Rec"],
            "contract_issues": [{"type": "t", "description": "d"}],
            "critical_failures": ["fail"],
        })
        assert all(o.observation_type == "verify_finding"
                    for o in result.observations)


# ---------------------------------------------------------------------------
# 10. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_none_path(self):
        result = ExtractResult()
        _step4_verify_findings("test", None, result)
        assert len(result.warnings) == 1
        assert len(result.observations) == 0

    def test_nonexistent_path(self):
        result = ExtractResult()
        _step4_verify_findings("test", Path("/nonexistent"), result)
        assert len(result.warnings) == 1
        assert len(result.observations) == 0

    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json",
                                         delete=False) as f:
            f.write("")
            tmp = Path(f.name)
        result = ExtractResult()
        _step4_verify_findings("test", tmp, result)
        tmp.unlink()
        assert len(result.warnings) == 1
        assert len(result.observations) == 0

    def test_all_empty_arrays(self):
        result = run_step4({
            "spec_requirements": [],
            "critical_failures": [],
            "semantic_drift": [],
            "recommendations": [],
            "contract_issues": [],
        })
        assert len(result.observations) == 0
        assert len(result.warnings) == 0

    def test_non_dict_spec_requirement_skipped(self):
        result = run_step4({
            "spec_requirements": ["not a dict", {"requirement": "R1", "status": "missing"}]
        })
        assert len(result.observations) == 1

    def test_idempotency(self):
        data = {
            "spec_requirements": [{"requirement": "R1", "status": "drifted"}],
            "recommendations": ["Rec 1"],
        }
        r1 = run_step4(data)
        r2 = run_step4(data)
        ids1 = [o.id for o in r1.observations]
        ids2 = [o.id for o in r2.observations]
        assert ids1 == ids2


# ---------------------------------------------------------------------------
# 11. Real data: speed-defects
# ---------------------------------------------------------------------------

class TestRealSpeedDefects:
    """Test against real speed-defects plan-verification.log."""

    @pytest.fixture
    def result(self):
        import re
        log = Path(".speed/features/speed-defects/logs/plan-verification.log")
        if not log.exists():
            pytest.skip("speed-defects log not available")
        text = log.read_text()
        m = re.search(r'```json\s*\n(.*?)\n```', text, re.DOTALL)
        data = json.loads(m.group(1))
        return run_step4(data)

    def test_total_observations(self, result):
        # 1 partial + 3 semantic_drift + 2 contract_issues + 6 recs = 12
        assert len(result.observations) == 12

    def test_partial_with_uncertain(self, result):
        partials = [o for o in result.observations
                    if o.detail["finding_type"] == "partial_requirement"]
        assert len(partials) == 1
        assert partials[0].detail["uncertain"] is True
        assert partials[0].weight == 1.0

    def test_recommendations_count(self, result):
        recs = [o for o in result.observations
                if o.detail["finding_type"] == "recommendation"]
        assert len(recs) == 6

    def test_contract_issues_count(self, result):
        cis = [o for o in result.observations
               if o.detail["finding_type"] == "contract_issue"]
        assert len(cis) == 2

    def test_semantic_drift_count(self, result):
        drifts = [o for o in result.observations
                  if o.detail["finding_type"] == "spec_drift"]
        assert len(drifts) == 3

    def test_no_critical_failures(self, result):
        cfs = [o for o in result.observations
               if o.detail["finding_type"] == "critical_failure"]
        assert len(cfs) == 0


# ---------------------------------------------------------------------------
# 12. Real data: speed-security
# ---------------------------------------------------------------------------

class TestRealSpeedSecurity:
    """Test against real speed-security plan-verification.log."""

    @pytest.fixture
    def result(self):
        import re
        log = Path(".speed/features/speed-security/logs/plan-verification.log")
        if not log.exists():
            pytest.skip("speed-security log not available")
        text = log.read_text()
        m = re.search(r'```json\s*\n(.*?)\n```', text, re.DOTALL)
        data = json.loads(m.group(1))
        return run_step4(data)

    def test_total_observations(self, result):
        # 1 drifted + 2 missing + 1 partial + 1 semantic_drift + 1 contract + 5 recs = 11
        assert len(result.observations) == 11

    def test_drifted_requirement(self, result):
        drifted = [o for o in result.observations
                   if o.detail.get("finding_type") == "spec_drift"
                   and o.detail.get("status") == "drifted"]
        # 1 from spec_requirements + 1 from semantic_drift = 2
        assert len(drifted) == 2

    def test_missing_requirements(self, result):
        missing = [o for o in result.observations
                   if o.detail["finding_type"] == "missing_requirement"]
        assert len(missing) == 2

    def test_partial_without_uncertain(self, result):
        partials = [o for o in result.observations
                    if o.detail["finding_type"] == "partial_requirement"]
        assert len(partials) == 1
        assert partials[0].detail["uncertain"] is False

    def test_recommendations_count(self, result):
        recs = [o for o in result.observations
                if o.detail["finding_type"] == "recommendation"]
        assert len(recs) == 5


# ---------------------------------------------------------------------------
# 13. Real data: find-your-tribe f10-rich-feed
# ---------------------------------------------------------------------------

class TestRealFytRichFeed:
    """Test against real f10-rich-feed plan-verification.log."""

    @pytest.fixture
    def result(self):
        import re
        fyt = Path("/Users/sanjay.kotagiri/Documents/code/tmp/find-your-tribe")
        log = fyt / ".speed/features/f10-rich-feed/logs/plan-verification.log"
        if not log.exists():
            pytest.skip("f10-rich-feed log not available")
        text = log.read_text()
        m = re.search(r'```json\s*\n(.*?)\n```', text, re.DOTALL)
        data = json.loads(m.group(1))
        return run_step4(data)

    def test_total_observations(self, result):
        # 0 non-covered reqs + 0 semantic_drift + 1 contract + 5 recs = 6
        assert len(result.observations) == 6

    def test_no_requirement_findings(self, result):
        req_types = {"spec_drift", "missing_requirement", "partial_requirement"}
        req_obs = [o for o in result.observations
                   if o.detail["finding_type"] in req_types]
        assert len(req_obs) == 0

    def test_recommendations_count(self, result):
        recs = [o for o in result.observations
                if o.detail["finding_type"] == "recommendation"]
        assert len(recs) == 5

    def test_contract_issue(self, result):
        cis = [o for o in result.observations
               if o.detail["finding_type"] == "contract_issue"]
        assert len(cis) == 1


# ---------------------------------------------------------------------------
# 14. Real data: find-your-tribe f9-profile-completeness
# ---------------------------------------------------------------------------

class TestRealFytProfileCompleteness:
    """Test against real f9-profile-completeness plan-verification.log."""

    @pytest.fixture
    def result(self):
        import re
        fyt = Path("/Users/sanjay.kotagiri/Documents/code/tmp/find-your-tribe")
        log = fyt / ".speed/features/f9-profile-completeness/logs/plan-verification.log"
        if not log.exists():
            pytest.skip("f9-profile-completeness log not available")
        text = log.read_text()
        m = re.search(r'```json\s*\n(.*?)\n```', text, re.DOTALL)
        data = json.loads(m.group(1))
        return run_step4(data)

    def test_total_observations(self, result):
        # 0 non-covered reqs + 0 semantic_drift + 1 contract + 2 recs = 3
        assert len(result.observations) == 3

    def test_recommendations_count(self, result):
        recs = [o for o in result.observations
                if o.detail["finding_type"] == "recommendation"]
        assert len(recs) == 2

    def test_contract_issue(self, result):
        cis = [o for o in result.observations
               if o.detail["finding_type"] == "contract_issue"]
        assert len(cis) == 1
