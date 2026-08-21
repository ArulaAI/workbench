"""Schema-level integration tests for specAlignment query.

Exercises the Strawberry schema's execute_sync() to verify that
specAlignment is wired correctly and produces valid GraphQL responses.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import sys

_BACKEND_DIR = Path(__file__).parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from schema import schema


# ── Helpers ───────────────────────────────────────────────────────────────────


def _write_json(path: Path, data: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _make_context(tmp_path: Path) -> dict:
    return {"project_root": tmp_path, "conn": MagicMock()}


# ── Queries ───────────────────────────────────────────────────────────────────

SPEC_ALIGNMENT_QUERY = """
query {
    specAlignment {
        totalClaims
        totalConfirmed
        totalMissing
        totalUnverifiable
        overallCoveragePct
        specs {
            specFile
            totalClaims
            confirmed
            coveragePct
            sections {
                section
                claimCount
                confirmed
                missing
                unverifiable
                coveragePct
                claims {
                    claimType
                    claimText
                    entity
                    status
                    evidence
                    divergence
                    source { specFile section line }
                }
            }
        }
    }
}
"""

SPEC_ALIGNMENT_FILTERED_QUERY = """
query SpecAlignmentFiltered($specFile: String) {
    specAlignment(specFile: $specFile) {
        totalClaims
        specs {
            specFile
            totalClaims
        }
    }
}
"""

_FIXTURE_CLAIMS = [
    {
        "source": {"spec_file": "specs/product/search.md", "section": "Overview", "line": 5},
        "claim_type": "functional",
        "claim_text": "System must support full-text search",
        "entity": "SearchService",
        "status": "confirmed",
        "evidence": "SearchService.search() at line 42",
        "divergence": None,
    },
    {
        "source": {"spec_file": "specs/product/search.md", "section": "Overview", "line": 10},
        "claim_type": "functional",
        "claim_text": "Results must be ranked by relevance",
        "entity": "SearchService",
        "status": "missing",
        "evidence": None,
        "divergence": None,
    },
    {
        "source": {"spec_file": "specs/product/auth.md", "section": "Security", "line": 3},
        "claim_type": "security",
        "claim_text": "Tokens must expire after 24 hours",
        "entity": "AuthService",
        "status": "confirmed",
        "evidence": "TokenManager.ttl == 86400",
        "divergence": None,
    },
]


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestSpecAlignmentQuery:
    """Verify specAlignment query executes through the compiled schema."""

    def test_returns_null_when_no_file(self, tmp_path: Path) -> None:
        result = schema.execute_sync(
            SPEC_ALIGNMENT_QUERY,
            context_value=_make_context(tmp_path),
        )
        assert result.errors is None, f"GraphQL errors: {result.errors}"
        assert result.data["specAlignment"] is None

    def test_returns_nested_data_when_fixture_exists(self, tmp_path: Path) -> None:
        _write_json(
            tmp_path / ".speed" / "context" / "spec-alignment.json",
            {"claims": _FIXTURE_CLAIMS},
        )

        result = schema.execute_sync(
            SPEC_ALIGNMENT_QUERY,
            context_value=_make_context(tmp_path),
        )
        assert result.errors is None, f"GraphQL errors: {result.errors}"

        data = result.data["specAlignment"]
        assert data is not None
        assert data["totalClaims"] == 3
        assert data["totalConfirmed"] == 2
        assert data["totalMissing"] == 1
        assert data["totalUnverifiable"] == 0
        assert data["overallCoveragePct"] == pytest.approx(66.7, abs=0.1)

        assert len(data["specs"]) == 2
        spec_files = {s["specFile"] for s in data["specs"]}
        assert "specs/product/search.md" in spec_files
        assert "specs/product/auth.md" in spec_files

    def test_nested_section_and_claim_fields(self, tmp_path: Path) -> None:
        _write_json(
            tmp_path / ".speed" / "context" / "spec-alignment.json",
            {"claims": _FIXTURE_CLAIMS},
        )

        result = schema.execute_sync(
            SPEC_ALIGNMENT_QUERY,
            context_value=_make_context(tmp_path),
        )
        assert result.errors is None, f"GraphQL errors: {result.errors}"

        specs_by_file = {s["specFile"]: s for s in result.data["specAlignment"]["specs"]}
        search_spec = specs_by_file["specs/product/search.md"]

        assert search_spec["totalClaims"] == 2
        assert search_spec["confirmed"] == 1
        assert len(search_spec["sections"]) == 1

        overview_section = search_spec["sections"][0]
        assert overview_section["section"] == "Overview"
        assert overview_section["claimCount"] == 2
        assert overview_section["confirmed"] == 1
        assert overview_section["missing"] == 1
        assert overview_section["unverifiable"] == 0
        assert len(overview_section["claims"]) == 2

        confirmed_claim = next(
            c for c in overview_section["claims"] if c["status"] == "confirmed"
        )
        assert confirmed_claim["claimType"] == "functional"
        assert confirmed_claim["entity"] == "SearchService"
        assert confirmed_claim["evidence"] == "SearchService.search() at line 42"
        assert confirmed_claim["source"]["specFile"] == "specs/product/search.md"
        assert confirmed_claim["source"]["section"] == "Overview"
        assert confirmed_claim["source"]["line"] == 5

    def test_spec_file_filter_narrows_results(self, tmp_path: Path) -> None:
        _write_json(
            tmp_path / ".speed" / "context" / "spec-alignment.json",
            {"claims": _FIXTURE_CLAIMS},
        )

        result = schema.execute_sync(
            SPEC_ALIGNMENT_FILTERED_QUERY,
            variable_values={"specFile": "auth.md"},
            context_value=_make_context(tmp_path),
        )
        assert result.errors is None, f"GraphQL errors: {result.errors}"

        data = result.data["specAlignment"]
        assert data is not None
        assert data["totalClaims"] == 1
        assert len(data["specs"]) == 1
        assert data["specs"][0]["specFile"] == "specs/product/auth.md"

    def test_empty_claims_array_returns_view_with_zeros(self, tmp_path: Path) -> None:
        _write_json(
            tmp_path / ".speed" / "context" / "spec-alignment.json",
            {"claims": []},
        )

        result = schema.execute_sync(
            SPEC_ALIGNMENT_QUERY,
            context_value=_make_context(tmp_path),
        )
        assert result.errors is None, f"GraphQL errors: {result.errors}"

        data = result.data["specAlignment"]
        assert data is not None
        assert data["totalClaims"] == 0
        assert data["totalConfirmed"] == 0
        assert data["overallCoveragePct"] == 0.0
        assert data["specs"] == []
