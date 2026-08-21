"""Tests for dashboard/backend/spec_parser.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from dashboard.backend.spec_parser import (
    TIER_MAP,
    ParsedSpec,
    SpecSection,
    extract_sections,
    extract_sections_from_content,
    parse_markdown_to_ast,
    run_checklist,
    score_spec_completeness,
    _get_tier,
)
from .test_helpers import _write_file


# ── Fixtures ────────────────────────────────────────────────────────────────


PRD_CONTENT = """\
# Feature X

> See [tech spec](../tech/feature-x.md) for technical context.
> Depends on: [Phase 1](feature-y.md)

## Problem

Users can't do the thing. This causes frustration and lost revenue.

## Users

### Persona A
Needs the thing for daily work.

## User Stories

| ID | Story | Acceptance Criteria | Priority |
|----|-------|---------------------|----------|
| S1 | As a user, I want X | Given Y When Z Then W | Must |

## User Flows

S1: User clicks button, sees result.

## Success Criteria

- [ ] Response time < 200ms for 95th percentile
- [ ] Error rate < 0.1%

## Scope

### In Scope
- Core feature implementation

### Out of Scope (and why)
- Admin panel (deferred to Phase 2 because it requires role-based access)

## Security & Controls

Authentication required for all endpoints. Rate limiting at 100 req/min.

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Data loss | High | Implement backups |

## Open Questions

- Which auth provider to use? Blocks integration testing.
"""

RFC_CONTENT = """\
# RFC: Feature X

> See [product spec](../product/feature-x.md) for product context.

## Basic Example

```python
result = feature_x.process(input_data)
```

## Data Model

| Column | Type | Constraints |
|--------|------|-------------|
| id | INTEGER | PRIMARY KEY |
| name | TEXT | NOT NULL |

## API Surface

`POST /api/feature-x` — Create a new entry.

## Testing

### Acceptance Criteria

- Processing completes in < 500ms
- Invalid input returns 400 with error details

## Security & Controls

Auth required. Input sanitization on all fields.
"""

DSN_CONTENT = """\
# Design: Feature X

## Design Intent

Clean, minimal interface for the feature.

## Layout Structure

Single-column layout with header and content area.

## Component Inventory

| ID | Component | Parent |
|----|-----------|--------|
| C1 | Header | Root |
| C2 | Content | Root |

## States

| Component | Empty | Loading | Populated | Error |
|-----------|-------|---------|-----------|-------|
| Content | "No data" | Spinner | Data grid | Error message |

## Color Application

All colors reference design tokens from globals.css.
"""


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """Create a minimal project structure with spec files."""
    specs = tmp_path / "specs"
    (specs / "product").mkdir(parents=True)
    (specs / "tech").mkdir(parents=True)
    (specs / "design").mkdir(parents=True)

    _write_file(specs / "product" / "feature-x.md", PRD_CONTENT)
    _write_file(specs / "tech" / "feature-x.md", RFC_CONTENT)
    _write_file(specs / "design" / "feature-x.md", DSN_CONTENT)

    return tmp_path


# ── Section extraction ──────────────────────────────────────────────────────


class TestExtractSections:
    def test_prd_sections(self, project: Path):
        parsed = extract_sections(
            project / "specs" / "product" / "feature-x.md", project
        )
        assert parsed.path == "specs/product/feature-x.md"
        assert parsed.content_hash
        assert len(parsed.sections) > 0
        headings = [s.heading for s in parsed.sections]
        assert "Problem" in headings
        assert "Users" in headings
        assert "User Stories" in headings
        assert "Scope" in headings

    def test_header_lines_extracted(self, project: Path):
        parsed = extract_sections(
            project / "specs" / "product" / "feature-x.md", project
        )
        assert len(parsed.header_lines) == 2
        assert "See" in parsed.header_lines[0]
        assert "Depends on" in parsed.header_lines[1]

    def test_rfc_sections(self, project: Path):
        parsed = extract_sections(
            project / "specs" / "tech" / "feature-x.md", project
        )
        headings = [s.heading for s in parsed.sections]
        assert "Basic Example" in headings
        assert "Data Model" in headings
        assert "API Surface" in headings

    def test_nonexistent_file(self, project: Path):
        parsed = extract_sections(
            project / "specs" / "product" / "nonexistent.md", project
        )
        assert parsed.content_hash == ""
        assert parsed.sections == []

    def test_line_numbers_are_1_indexed(self, project: Path):
        parsed = extract_sections(
            project / "specs" / "product" / "feature-x.md", project
        )
        first = parsed.sections[0]
        assert first.line_start == 1
        assert first.line_end >= 1

    def test_sections_are_contiguous(self, project: Path):
        parsed = extract_sections(
            project / "specs" / "product" / "feature-x.md", project
        )
        for i in range(len(parsed.sections) - 1):
            # Next section starts after current section (possibly with blank lines)
            assert parsed.sections[i + 1].line_start > parsed.sections[i].line_start

    def test_content_hash_deterministic(self, project: Path):
        path = project / "specs" / "product" / "feature-x.md"
        p1 = extract_sections(path, project)
        p2 = extract_sections(path, project)
        assert p1.content_hash == p2.content_hash
        for s1, s2 in zip(p1.sections, p2.sections):
            assert s1.content_hash == s2.content_hash


class TestExtractSectionsFromContent:
    def test_returns_sections(self):
        sections = extract_sections_from_content(PRD_CONTENT)
        headings = [s.heading for s in sections]
        assert "Problem" in headings
        assert "Users" in headings

    def test_empty_content(self):
        sections = extract_sections_from_content("")
        assert sections == []


# ── Tier classification ─────────────────────────────────────────────────────


class TestTierClassification:
    def test_t1_sections(self):
        assert _get_tier("Problem") == "T1"
        assert _get_tier("Users") == "T1"
        assert _get_tier("Scope") == "T1"
        assert _get_tier("User Stories") == "T1"
        assert _get_tier("Basic Example") == "T1"
        assert _get_tier("Data Model") == "T1"
        assert _get_tier("API Surface") == "T1"

    def test_t2_sections(self):
        assert _get_tier("Success Criteria") == "T2"
        assert _get_tier("Security & Controls") == "T2"
        assert _get_tier("Testing") == "T2"
        assert _get_tier("Risks") == "T2"
        assert _get_tier("Open Questions") == "T2"

    def test_t3_default(self):
        assert _get_tier("Random Custom Heading") == "T3"
        assert _get_tier("Implementation Notes") == "T3"

    def test_t3_explicit(self):
        assert _get_tier("Drawbacks") == "T3"
        assert _get_tier("Migration Strategy") == "T3"

    def test_substring_match(self):
        # "Security & Controls" should match via "Security"
        assert _get_tier("Security & Controls") == "T2"

    def test_prd_sections_in_fixture(self, project: Path):
        parsed = extract_sections(
            project / "specs" / "product" / "feature-x.md", project
        )
        for s in parsed.sections:
            if s.heading == "Problem":
                assert s.tier == "T1"
            elif s.heading == "Success Criteria":
                assert s.tier == "T2"


# ── AST parsing ─────────────────────────────────────────────────────────────


class TestMarkdownToAst:
    def test_returns_list(self):
        ast = parse_markdown_to_ast("# Hello\n\nParagraph.")
        assert isinstance(ast, list)
        assert len(ast) > 0

    def test_heading_token(self):
        ast = parse_markdown_to_ast("## Heading\n\nText.")
        types = [t.get("type") for t in ast]
        assert "heading" in types

    def test_empty_content(self):
        ast = parse_markdown_to_ast("")
        assert isinstance(ast, list)


# ── Completeness scoring ───────────────────────────────────────────────────


class TestCompleteness:
    def test_prd_score(self, project: Path):
        parsed = extract_sections(
            project / "specs" / "product" / "feature-x.md", project
        )
        score = score_spec_completeness(parsed, "prd", project)
        assert 0.0 <= score <= 1.0
        # Well-structured PRD should score reasonably well
        assert score >= 0.5

    def test_rfc_score(self, project: Path):
        parsed = extract_sections(
            project / "specs" / "tech" / "feature-x.md", project
        )
        score = score_spec_completeness(parsed, "rfc", project)
        assert 0.0 <= score <= 1.0

    def test_empty_spec_scores_low(self, project: Path):
        _write_file(project / "specs" / "product" / "empty.md", "# Empty\n")
        parsed = extract_sections(
            project / "specs" / "product" / "empty.md", project
        )
        score = score_spec_completeness(parsed, "prd", project)
        assert score <= 0.5

    def test_run_checklist_returns_results(self, project: Path):
        parsed = extract_sections(
            project / "specs" / "product" / "feature-x.md", project
        )
        results = run_checklist(parsed, "prd", project)
        assert len(results) > 0
        for r in results:
            assert "check_id" in r
            assert "description" in r
            assert "dimension" in r
            assert "passed" in r
            assert isinstance(r["passed"], bool)

    def test_dsn_checks_tokens(self, project: Path):
        parsed = extract_sections(
            project / "specs" / "design" / "feature-x.md", project
        )
        results = run_checklist(parsed, "dsn", project)
        check_ids = [r["check_id"] for r in results]
        assert "token_traceability" in check_ids
        assert "state_completeness" in check_ids

    def test_defect_minimal_checks(self, project: Path):
        _write_file(
            project / "specs" / "defects" / "bug.md",
            "# Bug Report\n\n## Severity\n\nP2\n",
        )
        (project / "specs" / "defects").mkdir(parents=True, exist_ok=True)
        parsed = extract_sections(
            project / "specs" / "defects" / "bug.md", project
        )
        results = run_checklist(parsed, "defect", project)
        # Defects only have links_resolve check
        assert len(results) == 1
        assert results[0]["check_id"] == "links_resolve"


# ── Frontmatter ─────────────────────────────────────────────────────────────


class TestFrontmatter:
    def test_frontmatter_extracted(self, project: Path):
        content = "---\nfeature: speed-audit\ntype: prd\n---\n\n# Spec\n"
        _write_file(project / "specs" / "product" / "fm.md", content)
        parsed = extract_sections(
            project / "specs" / "product" / "fm.md", project
        )
        assert parsed.frontmatter["feature"] == "speed-audit"
        assert parsed.frontmatter["type"] == "prd"

    def test_no_frontmatter(self, project: Path):
        parsed = extract_sections(
            project / "specs" / "product" / "feature-x.md", project
        )
        assert parsed.frontmatter == {}
