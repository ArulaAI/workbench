"""Tests for dashboard/backend/resolvers/spec_alignment.py.

Covers get_spec_alignment() with fixture JSON files written to tmp_path
simulating .speed/context/spec-alignment.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_BACKEND_DIR = Path(__file__).parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from resolvers.spec_alignment import get_spec_alignment, SpecAlignmentView


# ── Helpers ───────────────────────────────────────────────────────────────────


def _write_alignment(tmp_path: Path, data: dict) -> None:
    alignment_path = tmp_path / ".speed" / "context" / "spec-alignment.json"
    alignment_path.parent.mkdir(parents=True, exist_ok=True)
    alignment_path.write_text(json.dumps(data), encoding="utf-8")


def _make_claim(
    spec_file: str,
    section: str,
    status: str,
    line: int = 1,
    claim_type: str = "requirement",
    claim_text: str = "some claim",
    entity: str = "entity",
) -> dict:
    return {
        "source": {"spec_file": spec_file, "section": section, "line": line},
        "claim_type": claim_type,
        "claim_text": claim_text,
        "entity": entity,
        "status": status,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Missing / empty file cases
# ═══════════════════════════════════════════════════════════════════════════════


class TestMissingFile:
    def test_no_file_returns_none(self, tmp_path: Path) -> None:
        result = get_spec_alignment(tmp_path)
        assert result is None

    def test_empty_claims_returns_zero_totals(self, tmp_path: Path) -> None:
        _write_alignment(tmp_path, {"claims": []})
        result = get_spec_alignment(tmp_path)
        assert result is not None
        assert result.total_claims == 0
        assert result.total_confirmed == 0
        assert result.total_missing == 0
        assert result.total_unverifiable == 0
        assert result.overall_coverage_pct == 0.0
        assert result.specs == []


# ═══════════════════════════════════════════════════════════════════════════════
# Single spec / single section
# ═══════════════════════════════════════════════════════════════════════════════


class TestSingleSpec:
    def test_mixed_statuses_coverage_and_counts(self, tmp_path: Path) -> None:
        claims = [
            _make_claim("specs/product/auth.md", "Authentication", "confirmed"),
            _make_claim("specs/product/auth.md", "Authentication", "missing"),
            _make_claim("specs/product/auth.md", "Authentication", "divergent"),
        ]
        _write_alignment(tmp_path, {"claims": claims})

        result = get_spec_alignment(tmp_path)

        assert result is not None
        assert result.total_claims == 3
        assert result.total_confirmed == 1
        assert result.total_missing == 1
        assert result.total_unverifiable == 1
        assert result.overall_coverage_pct == pytest.approx(33.3, abs=0.1)

        assert len(result.specs) == 1
        spec = result.specs[0]
        assert spec.spec_file == "specs/product/auth.md"
        assert spec.total_claims == 3
        assert spec.confirmed == 1
        assert spec.coverage_pct == pytest.approx(33.3, abs=0.1)

    def test_all_confirmed_coverage_100(self, tmp_path: Path) -> None:
        claims = [
            _make_claim("specs/product/auth.md", "Sec", "confirmed"),
            _make_claim("specs/product/auth.md", "Sec", "confirmed"),
        ]
        _write_alignment(tmp_path, {"claims": claims})

        result = get_spec_alignment(tmp_path)

        assert result is not None
        assert result.overall_coverage_pct == 100.0
        assert result.specs[0].coverage_pct == 100.0

    def test_zero_valid_claims_coverage_zero(self, tmp_path: Path) -> None:
        # All claims are malformed — grand_total ends up 0
        _write_alignment(tmp_path, {"claims": [{"bad": "entry"}, {"also": "bad"}]})

        result = get_spec_alignment(tmp_path)

        assert result is not None
        assert result.total_claims == 0
        assert result.overall_coverage_pct == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# Multiple specs / multiple sections
# ═══════════════════════════════════════════════════════════════════════════════


class TestMultipleSpecs:
    def test_each_spec_gets_own_entry(self, tmp_path: Path) -> None:
        claims = [
            _make_claim("specs/product/auth.md", "Login", "confirmed"),
            _make_claim("specs/product/auth.md", "Login", "missing"),
            _make_claim("specs/product/billing.md", "Payments", "confirmed"),
            _make_claim("specs/product/billing.md", "Payments", "confirmed"),
        ]
        _write_alignment(tmp_path, {"claims": claims})

        result = get_spec_alignment(tmp_path)

        assert result is not None
        assert len(result.specs) == 2

        by_file = {s.spec_file: s for s in result.specs}

        auth = by_file["specs/product/auth.md"]
        assert auth.total_claims == 2
        assert auth.confirmed == 1
        assert auth.coverage_pct == pytest.approx(50.0)

        billing = by_file["specs/product/billing.md"]
        assert billing.total_claims == 2
        assert billing.confirmed == 2
        assert billing.coverage_pct == 100.0

    def test_overall_totals_aggregate_across_specs(self, tmp_path: Path) -> None:
        claims = [
            _make_claim("specs/product/auth.md", "Login", "confirmed"),
            _make_claim("specs/product/auth.md", "Login", "missing"),
            _make_claim("specs/product/billing.md", "Payments", "confirmed"),
            _make_claim("specs/product/billing.md", "Payments", "divergent"),
        ]
        _write_alignment(tmp_path, {"claims": claims})

        result = get_spec_alignment(tmp_path)

        assert result is not None
        assert result.total_claims == 4
        assert result.total_confirmed == 2
        assert result.total_missing == 1
        assert result.total_unverifiable == 1
        assert result.overall_coverage_pct == pytest.approx(50.0)

    def test_multiple_sections_within_one_spec(self, tmp_path: Path) -> None:
        claims = [
            _make_claim("specs/product/auth.md", "Login", "confirmed"),
            _make_claim("specs/product/auth.md", "Login", "missing"),
            _make_claim("specs/product/auth.md", "Logout", "confirmed"),
            _make_claim("specs/product/auth.md", "Logout", "confirmed"),
        ]
        _write_alignment(tmp_path, {"claims": claims})

        result = get_spec_alignment(tmp_path)

        assert result is not None
        assert len(result.specs) == 1

        spec = result.specs[0]
        assert len(spec.sections) == 2

        by_section = {s.section: s for s in spec.sections}

        login = by_section["Login"]
        assert login.claim_count == 2
        assert login.confirmed == 1
        assert login.missing == 1
        assert login.coverage_pct == pytest.approx(50.0)

        logout = by_section["Logout"]
        assert logout.claim_count == 2
        assert logout.confirmed == 2
        assert logout.coverage_pct == 100.0


# ═══════════════════════════════════════════════════════════════════════════════
# spec_file filter
# ═══════════════════════════════════════════════════════════════════════════════


class TestSpecFileFilter:
    def test_filter_matching_returns_only_that_spec(self, tmp_path: Path) -> None:
        claims = [
            _make_claim("specs/product/auth.md", "Login", "confirmed"),
            _make_claim("specs/product/billing.md", "Payments", "missing"),
        ]
        _write_alignment(tmp_path, {"claims": claims})

        result = get_spec_alignment(tmp_path, spec_file="auth.md")

        assert result is not None
        assert len(result.specs) == 1
        assert result.specs[0].spec_file == "specs/product/auth.md"
        assert result.total_claims == 1

    def test_filter_non_matching_returns_empty_specs(self, tmp_path: Path) -> None:
        claims = [
            _make_claim("specs/product/auth.md", "Login", "confirmed"),
        ]
        _write_alignment(tmp_path, {"claims": claims})

        result = get_spec_alignment(tmp_path, spec_file="nonexistent.md")

        assert result is not None
        assert result.specs == []
        assert result.total_claims == 0
        assert result.overall_coverage_pct == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# Malformed claims
# ═══════════════════════════════════════════════════════════════════════════════


class TestMalformedClaims:
    def test_missing_source_key_skipped(self, tmp_path: Path) -> None:
        claims = [
            {"status": "confirmed", "claim_text": "no source field"},
            _make_claim("specs/product/auth.md", "Login", "confirmed"),
        ]
        _write_alignment(tmp_path, {"claims": claims})

        result = get_spec_alignment(tmp_path)

        assert result is not None
        assert result.total_claims == 1
        assert result.total_confirmed == 1

    def test_missing_status_key_skipped(self, tmp_path: Path) -> None:
        claims = [
            {
                "source": {"spec_file": "specs/product/auth.md", "section": "Login", "line": 1},
                "claim_text": "no status field",
            },
            _make_claim("specs/product/auth.md", "Login", "confirmed"),
        ]
        _write_alignment(tmp_path, {"claims": claims})

        result = get_spec_alignment(tmp_path)

        assert result is not None
        assert result.total_claims == 1
        assert result.total_confirmed == 1

    def test_non_dict_claim_skipped(self, tmp_path: Path) -> None:
        claims = [
            "not a dict",
            _make_claim("specs/product/auth.md", "Login", "missing"),
        ]
        _write_alignment(tmp_path, {"claims": claims})

        result = get_spec_alignment(tmp_path)

        assert result is not None
        assert result.total_claims == 1
        assert result.total_missing == 1

    def test_malformed_skipped_valid_still_processed(self, tmp_path: Path) -> None:
        claims = [
            {"bad_key": "ignored"},
            _make_claim("specs/product/auth.md", "Sec", "confirmed"),
            _make_claim("specs/product/auth.md", "Sec", "confirmed"),
        ]
        _write_alignment(tmp_path, {"claims": claims})

        result = get_spec_alignment(tmp_path)

        assert result is not None
        assert result.total_claims == 2
        assert result.total_confirmed == 2
        assert result.overall_coverage_pct == 100.0
