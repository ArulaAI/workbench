#!/usr/bin/env python3
"""Tests for Step 5: Coherence Issues — against real extract.py.

Tests the actual _step5_coherence_issues function from lib/learn/extract.py
using synthetic fixtures and real coherence.log data from speed-security
(markdown) and f9-profile-completeness (JSON).
"""

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from learn.extract import (
    _step5_coherence_issues,
    _step5_coherence_markdown_fallback,
    ExtractResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_step5(data: dict) -> ExtractResult:
    """Write JSON data to temp file, run Step 5, return result."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        tmp = Path(f.name)
    result = ExtractResult()
    _step5_coherence_issues("test-feature", tmp, result)
    tmp.unlink()
    return result


def run_step5_raw(text: str) -> ExtractResult:
    """Write raw text to temp file, run Step 5, return result."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write(text)
        tmp = Path(f.name)
    result = ExtractResult()
    _step5_coherence_issues("test-feature", tmp, result)
    tmp.unlink()
    return result


def obs_by_issue_type(result: ExtractResult) -> dict:
    grouped = {}
    for o in result.observations:
        it = o.detail["issue_type"]
        grouped.setdefault(it, []).append(o)
    return grouped


# ---------------------------------------------------------------------------
# 1. interface_mismatches
# ---------------------------------------------------------------------------

class TestInterfaceMismatches:
    def test_produces_observation(self):
        result = run_step5({
            "interface_mismatches": [
                {"task_a": "1", "task_b": "3",
                 "location_a": "a.ts:10", "location_b": "b.ts:20",
                 "description": "Arg count mismatch", "severity": "critical"}
            ]
        })
        assert len(result.observations) == 1
        obs = result.observations[0]
        assert obs.detail["issue_type"] == "interface_mismatch"
        assert obs.detail["task_a"] == "1"
        assert obs.detail["task_b"] == "3"
        assert obs.weight == 2.0

    def test_empty_array(self):
        result = run_step5({"interface_mismatches": []})
        assert len(result.observations) == 0


# ---------------------------------------------------------------------------
# 2. schema_inconsistencies
# ---------------------------------------------------------------------------

class TestSchemaInconsistencies:
    def test_produces_observation(self):
        result = run_step5({
            "schema_inconsistencies": [
                {"description": "user_id vs owner_id",
                 "locations": ["a.py:1"], "severity": "major"}
            ]
        })
        assert len(result.observations) == 1
        assert result.observations[0].detail["issue_type"] == "schema_inconsistency"
        assert result.observations[0].weight == 2.0


# ---------------------------------------------------------------------------
# 3. missing_connections
# ---------------------------------------------------------------------------

class TestMissingConnections:
    def test_produces_observation(self):
        result = run_step5({
            "missing_connections": [
                {"description": "Model not in __init__",
                 "expected_in": "models/__init__.py", "severity": "major"}
            ]
        })
        assert len(result.observations) == 1
        assert result.observations[0].detail["issue_type"] == "missing_connection"
        assert result.observations[0].weight == 2.0


# ---------------------------------------------------------------------------
# 4. critical_issues
# ---------------------------------------------------------------------------

class TestCriticalIssues:
    def test_string_issue(self):
        result = run_step5({
            "critical_issues": ["Task 4 delivered nothing"]
        })
        assert len(result.observations) == 1
        obs = result.observations[0]
        assert obs.detail["issue_type"] == "critical_issue"
        assert obs.detail["severity"] == "critical"
        assert obs.weight == 2.5

    def test_multiple_issues(self):
        result = run_step5({
            "critical_issues": ["Issue 1", "Issue 2", "Issue 3"]
        })
        assert len(result.observations) == 3
        assert all(o.weight == 2.5 for o in result.observations)

    def test_non_string_skipped(self):
        result = run_step5({
            "critical_issues": [42, "", "Valid"]
        })
        assert len(result.observations) == 1
        assert result.observations[0].detail["description"] == "Valid"

    def test_empty_array(self):
        result = run_step5({"critical_issues": []})
        assert len(result.observations) == 0


# ---------------------------------------------------------------------------
# 5. contract_gaps
# ---------------------------------------------------------------------------

class TestContractGaps:
    def test_missing_gap(self):
        result = run_step5({
            "contract_gaps": [
                {"contract_item": "Auth middleware", "status": "missing",
                 "notes": "No task creates it"}
            ]
        })
        assert len(result.observations) == 1
        obs = result.observations[0]
        assert obs.detail["issue_type"] == "contract_gap"
        assert obs.detail["status"] == "missing"
        assert obs.detail["severity"] == "major"
        assert obs.weight == 2.0

    def test_partial_gap(self):
        result = run_step5({
            "contract_gaps": [
                {"contract_item": "Rate limiter", "status": "partial",
                 "notes": "Config only"}
            ]
        })
        obs = result.observations[0]
        assert obs.detail["status"] == "partial"
        assert obs.detail["severity"] == "minor"
        assert obs.weight == 2.0

    def test_satisfied_gap_ignored(self):
        result = run_step5({
            "contract_gaps": [
                {"contract_item": "User model", "status": "satisfied",
                 "notes": "Task 1"}
            ]
        })
        assert len(result.observations) == 0

    def test_mixed_statuses(self):
        result = run_step5({
            "contract_gaps": [
                {"contract_item": "A", "status": "satisfied"},
                {"contract_item": "B", "status": "missing"},
                {"contract_item": "C", "status": "satisfied"},
                {"contract_item": "D", "status": "partial"},
            ]
        })
        assert len(result.observations) == 2


# ---------------------------------------------------------------------------
# 6. duplicates
# ---------------------------------------------------------------------------

class TestDuplicates:
    def test_dict_duplicate(self):
        result = run_step5({
            "duplicates": [
                {"description": "formatDate in two files",
                 "locations": ["utils.ts:45", "helpers.ts:12"]}
            ]
        })
        assert len(result.observations) == 1
        obs = result.observations[0]
        assert obs.detail["issue_type"] == "duplicate"
        assert obs.detail["severity"] == "major"
        assert len(obs.detail["locations"]) == 2
        assert obs.weight == 2.0

    def test_empty_array(self):
        result = run_step5({"duplicates": []})
        assert len(result.observations) == 0


# ---------------------------------------------------------------------------
# 7. recommendations
# ---------------------------------------------------------------------------

class TestRecommendations:
    def test_string_recommendation(self):
        result = run_step5({
            "recommendations": ["Rename owner_id to user_id"]
        })
        assert len(result.observations) == 1
        obs = result.observations[0]
        assert obs.detail["issue_type"] == "recommendation"
        assert obs.detail["severity"] == "info"
        assert obs.weight == 1.0

    def test_empty_string_skipped(self):
        result = run_step5({
            "recommendations": ["", "  ", "Valid"]
        })
        assert len(result.observations) == 1

    def test_empty_array(self):
        result = run_step5({"recommendations": []})
        assert len(result.observations) == 0


# ---------------------------------------------------------------------------
# 8. Markdown fallback
# ---------------------------------------------------------------------------

class TestMarkdownFallback:
    def test_fail_with_table_rows(self):
        md = """## Summary

**Status: FAIL** (3 critical issues)

### Critical Issues

| # | Issue | Impact |
|---|-------|--------|
| 1 | Task 4 missing | Undelivered |
| 2 | Task 12 missing | No tests |
| 3 | grep -oP broken | macOS |

### Major Issues

| # | Issue | Location |
|---|-------|----------|
| 4 | Schema split | lib/security.sh |
| 5 | Config ignored | lib/grounding.sh |
"""
        result = run_step5_raw(md)
        assert len(result.observations) == 1
        obs = result.observations[0]
        assert obs.detail["issue_type"] == "markdown_summary"
        assert obs.detail["status"] == "fail"
        assert obs.detail["critical_count"] == 3
        assert obs.detail["major_count"] == 2
        assert obs.weight == 2.5

    def test_fail_with_numbered_lists(self):
        md = """## Verdict: **FAIL** — 3 critical issues

### What blocks integration

1. **Task 4 delivered nothing.**
2. **Task 12 delivered nothing.**
3. **grep -oP broken.**

### What works

Everything else.
"""
        result = run_step5_raw(md)
        assert len(result.observations) == 1
        obs = result.observations[0]
        assert obs.detail["status"] == "fail"
        assert obs.detail["critical_count"] == 3
        assert obs.weight == 2.5

    def test_pass_status(self):
        md = "## Summary\n\n**Status: PASS** (zero issues)\n"
        result = run_step5_raw(md)
        assert len(result.observations) == 1
        assert result.observations[0].detail["status"] == "pass"
        assert result.observations[0].weight == 1.0

    def test_unparseable_text(self):
        result = run_step5_raw("just random text with no structure")
        assert len(result.observations) == 0
        assert any("unparseable" in w.lower() for w in result.warnings)

    def test_warning_about_markdown(self):
        md = "**Status: FAIL** (1 issue)\n\n### Critical Issues\n\n| # | I |\n|---|---|\n| 1 | X |\n"
        result = run_step5_raw(md)
        assert any("markdown" in w.lower() for w in result.warnings)


# ---------------------------------------------------------------------------
# 9. Common properties
# ---------------------------------------------------------------------------

class TestCommonProperties:
    def test_all_star_task_id(self):
        result = run_step5({
            "schema_inconsistencies": [{"description": "x", "severity": "minor"}],
            "critical_issues": ["y"],
            "recommendations": ["z"],
        })
        assert all(o.task_id == "*" for o in result.observations)

    def test_all_coherence_source(self):
        result = run_step5({
            "missing_connections": [{"description": "x", "severity": "major"}],
            "contract_gaps": [{"contract_item": "A", "status": "missing"}],
        })
        assert all(o.stage == "coherence" for o in result.observations)

    def test_all_coherence_issue_type(self):
        result = run_step5({
            "duplicates": [{"description": "x", "locations": []}],
            "recommendations": ["y"],
        })
        assert all(o.observation_type == "coherence_issue"
                    for o in result.observations)


# ---------------------------------------------------------------------------
# 10. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_none_path(self):
        result = ExtractResult()
        _step5_coherence_issues("test", None, result)
        assert len(result.warnings) == 1
        assert len(result.observations) == 0

    def test_nonexistent_path(self):
        result = ExtractResult()
        _step5_coherence_issues("test", Path("/nonexistent"), result)
        assert len(result.warnings) == 1
        assert len(result.observations) == 0

    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json",
                                         delete=False) as f:
            f.write("")
            tmp = Path(f.name)
        result = ExtractResult()
        _step5_coherence_issues("test", tmp, result)
        tmp.unlink()
        assert len(result.warnings) == 1
        assert len(result.observations) == 0

    def test_all_empty_arrays(self):
        result = run_step5({
            "status": "pass", "summary": "Clean.",
            "interface_mismatches": [], "schema_inconsistencies": [],
            "missing_connections": [], "critical_issues": [],
            "contract_gaps": [], "duplicates": [], "recommendations": [],
        })
        assert len(result.observations) == 0
        assert len(result.warnings) == 0

    def test_idempotency(self):
        data = {
            "schema_inconsistencies": [
                {"description": "field mismatch", "severity": "minor"}
            ],
            "recommendations": ["Fix it"],
        }
        r1 = run_step5(data)
        r2 = run_step5(data)
        assert [o.id for o in r1.observations] == [o.id for o in r2.observations]


# ---------------------------------------------------------------------------
# 11. Real data: f9-profile-completeness (JSON)
# ---------------------------------------------------------------------------

class TestRealFytProfileCompleteness:
    @pytest.fixture
    def result(self):
        fyt = Path("/Users/sanjay.kotagiri/Documents/code/tmp/find-your-tribe")
        log = fyt / ".speed/features/f9-profile-completeness/logs/coherence.log"
        if not log.exists():
            pytest.skip("f9-profile-completeness coherence.log not available")
        data = json.loads(log.read_text())
        return run_step5(data)

    def test_total_observations(self, result):
        # 1 schema_inconsistency + 1 recommendation = 2
        assert len(result.observations) == 2

    def test_schema_inconsistency(self, result):
        by_type = obs_by_issue_type(result)
        assert len(by_type.get("schema_inconsistency", [])) == 1

    def test_recommendation(self, result):
        by_type = obs_by_issue_type(result)
        assert len(by_type.get("recommendation", [])) == 1
        assert by_type["recommendation"][0].weight == 1.0

    def test_satisfied_gaps_filtered(self, result):
        by_type = obs_by_issue_type(result)
        assert len(by_type.get("contract_gap", [])) == 0


# ---------------------------------------------------------------------------
# 12. Real data: speed-security coherence.log (markdown)
# ---------------------------------------------------------------------------

class TestRealSpeedSecurityMarkdown:
    @pytest.fixture
    def result(self):
        log = Path(".speed/features/speed-security/logs/coherence.log")
        if not log.exists():
            pytest.skip("speed-security coherence.log not available")
        return run_step5_raw(log.read_text())

    def test_produces_summary(self, result):
        assert len(result.observations) == 1
        assert result.observations[0].detail["issue_type"] == "markdown_summary"

    def test_fail_status(self, result):
        assert result.observations[0].detail["status"] == "fail"

    def test_critical_count(self, result):
        assert result.observations[0].detail["critical_count"] == 3

    def test_major_count(self, result):
        assert result.observations[0].detail["major_count"] == 3

    def test_weight(self, result):
        assert result.observations[0].weight == 2.5


# ---------------------------------------------------------------------------
# 13. Real data: speed-security coherence-prev.json (markdown variant)
# ---------------------------------------------------------------------------

class TestRealSpeedSecurityPrev:
    @pytest.fixture
    def result(self):
        log = Path(".speed/features/speed-security/logs/coherence-prev.json")
        if not log.exists():
            pytest.skip("coherence-prev.json not available")
        return run_step5_raw(log.read_text())

    def test_produces_summary(self, result):
        assert len(result.observations) == 1

    def test_fail_status(self, result):
        assert result.observations[0].detail["status"] == "fail"

    def test_critical_count(self, result):
        assert result.observations[0].detail["critical_count"] == 3

    def test_weight(self, result):
        assert result.observations[0].weight == 2.5
