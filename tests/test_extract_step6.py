#!/usr/bin/env python3
"""Tests for Step 6: Security Findings — against real extract.py."""

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from learn.extract import _step6_security_findings, ExtractResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_logs(*files):
    """Create a temp dir with the given files. Returns (dir_path, cleanup_fn)."""
    tmpdir = tempfile.mkdtemp()
    for name, content in files:
        (Path(tmpdir) / name).write_text(
            json.dumps(content) if not isinstance(content, str) else content
        )
    return Path(tmpdir)


# ---------------------------------------------------------------------------
# 1. validation-report.json (bare array)
# ---------------------------------------------------------------------------

class TestValidationReport:
    def test_bare_array(self):
        logs = make_logs(("validation-report.json", [
            {"issue": "Problem 1", "severity": "warning",
             "recommendation": "Fix it", "product_requirement": "S1"},
            {"issue": "Problem 2", "severity": "note",
             "recommendation": "", "product_requirement": "S2"},
        ]))
        result = ExtractResult()
        _step6_security_findings("test", logs, result)
        assert len(result.observations) == 2
        assert result.observations[0].detail["title"] == "Problem 1"
        assert result.observations[1].detail["severity"] == "note"

    def test_product_requirement_preserved(self):
        logs = make_logs(("validation-report.json", [
            {"issue": "X", "severity": "note",
             "product_requirement": "S3 — must do Y"}
        ]))
        result = ExtractResult()
        _step6_security_findings("test", logs, result)
        assert result.observations[0].detail["product_requirement"] == "S3 — must do Y"


# ---------------------------------------------------------------------------
# 2. security-audit.json (dict with validation key)
# ---------------------------------------------------------------------------

class TestSecurityAudit:
    def test_dict_with_validation(self):
        logs = make_logs(("security-audit.json", {
            "validation": [
                {"issue": "SEC-001 (medium): Injection risk",
                 "severity": "warning", "recommendation": "Sanitize"}
            ],
            "tasks": []
        }))
        result = ExtractResult()
        _step6_security_findings("test", logs, result)
        assert len(result.observations) == 1

    def test_sec_pattern_parsing(self):
        logs = make_logs(("security-audit.json", {
            "validation": [
                {"issue": "SEC-007 (high): XSS in template",
                 "severity": "warning", "recommendation": "Escape"}
            ]
        }))
        result = ExtractResult()
        _step6_security_findings("test", logs, result)
        obs = result.observations[0]
        assert obs.detail["finding_id"] == "SEC-007"
        assert obs.detail["severity"] == "high"
        assert obs.detail["title"] == "XSS in template"


# ---------------------------------------------------------------------------
# 3. Both files present
# ---------------------------------------------------------------------------

class TestBothFiles:
    def test_combined(self):
        logs = make_logs(
            ("validation-report.json", [
                {"issue": "VR finding", "severity": "warning"},
            ]),
            ("security-audit.json", {
                "validation": [
                    {"issue": "SA finding", "severity": "note"},
                ]
            }),
        )
        result = ExtractResult()
        _step6_security_findings("test", logs, result)
        assert len(result.observations) == 2
        titles = [o.detail["title"] for o in result.observations]
        assert "VR finding" in titles
        assert "SA finding" in titles

    def test_no_dedup(self):
        # Same text in both files → both extracted
        finding = {"issue": "Same finding", "severity": "note"}
        logs = make_logs(
            ("validation-report.json", [finding]),
            ("security-audit.json", {"validation": [finding]}),
        )
        result = ExtractResult()
        _step6_security_findings("test", logs, result)
        assert len(result.observations) == 2


# ---------------------------------------------------------------------------
# 4. Common properties
# ---------------------------------------------------------------------------

class TestCommonProperties:
    def test_all_star_task_id(self):
        logs = make_logs(("validation-report.json", [
            {"issue": "A", "severity": "note"},
            {"issue": "B", "severity": "warning"},
        ]))
        result = ExtractResult()
        _step6_security_findings("test", logs, result)
        assert all(o.task_id == "*" for o in result.observations)

    def test_all_security_source(self):
        logs = make_logs(("validation-report.json", [
            {"issue": "A", "severity": "note"}
        ]))
        result = ExtractResult()
        _step6_security_findings("test", logs, result)
        assert all(o.stage == "security" for o in result.observations)

    def test_all_weight_1_5(self):
        logs = make_logs(("validation-report.json", [
            {"issue": "A", "severity": "note"},
            {"issue": "B", "severity": "warning"},
        ]))
        result = ExtractResult()
        _step6_security_findings("test", logs, result)
        assert all(o.weight == 1.5 for o in result.observations)

    def test_all_security_finding_type(self):
        logs = make_logs(("validation-report.json", [
            {"issue": "A", "severity": "note"}
        ]))
        result = ExtractResult()
        _step6_security_findings("test", logs, result)
        assert all(o.observation_type == "security_finding"
                    for o in result.observations)


# ---------------------------------------------------------------------------
# 5. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_no_files(self):
        logs = make_logs()
        result = ExtractResult()
        _step6_security_findings("test", logs, result)
        assert len(result.warnings) == 1
        assert "No validation-report" in result.warnings[0]
        assert len(result.observations) == 0

    def test_empty_array(self):
        logs = make_logs(("validation-report.json", []))
        result = ExtractResult()
        _step6_security_findings("test", logs, result)
        assert len(result.warnings) == 1
        assert len(result.observations) == 0

    def test_empty_validation_in_dict(self):
        logs = make_logs(("security-audit.json", {"validation": []}))
        result = ExtractResult()
        _step6_security_findings("test", logs, result)
        assert len(result.warnings) == 1
        assert len(result.observations) == 0

    def test_non_dict_items_skipped(self):
        logs = make_logs(("validation-report.json", [
            "not a dict",
            42,
            {"issue": "Valid", "severity": "note"},
        ]))
        result = ExtractResult()
        _step6_security_findings("test", logs, result)
        assert len(result.observations) == 1

    def test_idempotency(self):
        logs = make_logs(("validation-report.json", [
            {"issue": "Finding", "severity": "note"}
        ]))
        r1 = ExtractResult()
        _step6_security_findings("test", logs, r1)
        r2 = ExtractResult()
        _step6_security_findings("test", logs, r2)
        assert [o.id for o in r1.observations] == [o.id for o in r2.observations]

    def test_long_title_truncated(self):
        logs = make_logs(("validation-report.json", [
            {"issue": "X" * 300, "severity": "note"}
        ]))
        result = ExtractResult()
        _step6_security_findings("test", logs, result)
        assert len(result.observations[0].detail["title"]) == 200


# ---------------------------------------------------------------------------
# 6. Real data: speed-defects
# ---------------------------------------------------------------------------

class TestRealSpeedDefects:
    @pytest.fixture
    def result(self):
        logs = Path(".speed/features/speed-defects/logs")
        if not (logs / "validation-report.json").exists():
            pytest.skip("speed-defects validation-report.json not available")
        result = ExtractResult()
        _step6_security_findings("speed-defects", logs, result)
        return result

    def test_count(self, result):
        assert len(result.observations) == 7

    def test_all_have_product_requirement(self, result):
        assert all(o.detail.get("product_requirement", "") != ""
                    for o in result.observations)

    def test_weight(self, result):
        assert all(o.weight == 1.5 for o in result.observations)


# ---------------------------------------------------------------------------
# 7. Real data: speed-security
# ---------------------------------------------------------------------------

class TestRealSpeedSecurity:
    @pytest.fixture
    def result(self):
        logs = Path(".speed/features/speed-security/logs")
        if not (logs / "validation-report.json").exists():
            pytest.skip("speed-security files not available")
        result = ExtractResult()
        _step6_security_findings("speed-security", logs, result)
        return result

    def test_count(self, result):
        # 11 from validation-report + 6 from security-audit = 17
        assert len(result.observations) == 17

    def test_has_sec_pattern_findings(self, result):
        sec_findings = [o for o in result.observations
                        if o.detail["finding_id"].startswith("SEC-0")
                        and o.detail["severity"] not in ("warning", "note")]
        assert len(sec_findings) > 0


# ---------------------------------------------------------------------------
# 8. Real data: find-your-tribe features
# ---------------------------------------------------------------------------

class TestRealFytRichFeed:
    @pytest.fixture
    def result(self):
        fyt = Path("/Users/sanjay.kotagiri/Documents/code/tmp/find-your-tribe")
        logs = fyt / ".speed/features/f10-rich-feed/logs"
        if not (logs / "validation-report.json").exists():
            pytest.skip("f10-rich-feed not available")
        result = ExtractResult()
        _step6_security_findings("f10-rich-feed", logs, result)
        return result

    def test_count(self, result):
        assert len(result.observations) == 5


class TestRealFytProfileCompleteness:
    @pytest.fixture
    def result(self):
        fyt = Path("/Users/sanjay.kotagiri/Documents/code/tmp/find-your-tribe")
        logs = fyt / ".speed/features/f9-profile-completeness/logs"
        if not (logs / "validation-report.json").exists():
            pytest.skip("f9-profile-completeness not available")
        result = ExtractResult()
        _step6_security_findings("f9-profile-completeness", logs, result)
        return result

    def test_count(self, result):
        assert len(result.observations) == 4


class TestRealFytSeedOnboarding:
    @pytest.fixture
    def result(self):
        fyt = Path("/Users/sanjay.kotagiri/Documents/code/tmp/find-your-tribe")
        logs = fyt / ".speed/features/seed-onboarding-flag/logs"
        if not (logs / "validation-report.json").exists():
            pytest.skip("seed-onboarding-flag not available")
        result = ExtractResult()
        _step6_security_findings("seed-onboarding-flag", logs, result)
        return result

    def test_count(self, result):
        assert len(result.observations) == 2
