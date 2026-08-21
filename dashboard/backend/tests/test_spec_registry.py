"""Tests for dashboard/backend/spec_registry.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from dashboard.backend import db
from dashboard.backend.spec_registry import (
    GhostSpec,
    classify_spec_type,
    detect_ghosts,
    match_spec_to_feature,
    rebuild_registry,
    remove_spec,
    transition_lifecycle,
    update_spec,
)
from .test_helpers import _write_file


# ── Fixtures ────────────────────────────────────────────────────────────────


PRD = """\
# Feature Alpha

## Problem
Something is broken.

## Users
Engineers.

## User Stories
| ID | Story | Acceptance Criteria | Priority |
|----|-------|---------------------|----------|
| S1 | As a user, I want X | Given Y When Z Then W | Must |

## Scope
### In Scope
- Core feature

### Out of Scope (and why)
- Admin panel (deferred to Phase 2 because it needs role-based access)

## Success Criteria
- [ ] Response time < 200ms

## Security & Controls
Auth required.
"""

RFC = """\
# RFC: Feature Alpha

> See [product spec](../product/alpha.md) for product context.

## Basic Example
```python
alpha.run()
```

## Data Model
| Column | Type | Constraints |
|--------|------|-------------|
| id | INTEGER | PRIMARY KEY |

## API Surface
POST /api/alpha

## Testing
### Acceptance Criteria
- Works correctly
"""


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """Create a project with specs and .speed/features/ dirs."""
    # Specs
    specs = tmp_path / "specs"
    (specs / "product").mkdir(parents=True)
    (specs / "tech").mkdir(parents=True)
    (specs / "design").mkdir(parents=True)
    (specs / "defects").mkdir(parents=True)

    _write_file(specs / "product" / "alpha.md", PRD)
    _write_file(specs / "tech" / "alpha.md", RFC)
    _write_file(specs / "design" / "alpha.md", "# Design: Alpha\n\n## Design Intent\nClean.\n")
    _write_file(specs / "defects" / "bug-123.md", "# Bug 123\n\n## Severity\nP2\n")

    # Feature with only one spec type (no cross-match, uses .speed/features)
    _write_file(specs / "product" / "beta.md", "# Beta\n\n## Problem\nBeta issue.\n")

    # .speed/features
    (tmp_path / ".speed" / "features" / "beta").mkdir(parents=True)
    (tmp_path / ".speed" / "features" / "beta" / "state.json").write_text(
        '{"status": "running"}'
    )

    return tmp_path


@pytest.fixture
def conn(project: Path):
    """Database connection with schema."""
    c = db.connect(str(project))
    db.migrate(c)
    yield c
    c.close()


# ── Type classification ─────────────────────────────────────────────────────


class TestClassifySpecType:
    def test_product_dir(self, project: Path):
        assert classify_spec_type(
            project / "specs" / "product" / "alpha.md", project
        ) == "prd"

    def test_tech_dir(self, project: Path):
        assert classify_spec_type(
            project / "specs" / "tech" / "alpha.md", project
        ) == "rfc"

    def test_design_dir(self, project: Path):
        assert classify_spec_type(
            project / "specs" / "design" / "alpha.md", project
        ) == "dsn"

    def test_defects_dir(self, project: Path):
        assert classify_spec_type(
            project / "specs" / "defects" / "bug-123.md", project
        ) == "defect"

    def test_content_fallback_rfc(self, tmp_path: Path):
        _write_file(tmp_path / "some.md", "# Title\n\n## Basic Example\nCode.\n")
        assert classify_spec_type(tmp_path / "some.md", tmp_path) == "rfc"

    def test_content_fallback_prd(self, tmp_path: Path):
        _write_file(tmp_path / "some.md", "# Title\n\n## Intro\nStuff.\n")
        assert classify_spec_type(tmp_path / "some.md", tmp_path) == "prd"


# ── Feature matching ───────────────────────────────────────────────────────


class TestMatchSpecToFeature:
    def test_match_via_features_dir(self, project: Path):
        # beta exists in .speed/features/
        assert match_spec_to_feature(
            project / "specs" / "product" / "beta.md", project
        ) == "beta"

    def test_cross_match_by_stem(self, project: Path):
        # alpha has product + tech + design specs, no .speed/features/ dir
        assert match_spec_to_feature(
            project / "specs" / "product" / "alpha.md", project
        ) == "alpha"

    def test_cross_match_tech(self, project: Path):
        assert match_spec_to_feature(
            project / "specs" / "tech" / "alpha.md", project
        ) == "alpha"

    def test_defect_no_match(self, project: Path):
        # Defect with unique name has no cross-match
        assert match_spec_to_feature(
            project / "specs" / "defects" / "bug-123.md", project
        ) is None

    def test_frontmatter_match(self, project: Path):
        _write_file(
            project / "specs" / "product" / "gamma.md",
            "---\nfeature: gamma-feature\n---\n\n# Gamma\n",
        )
        assert match_spec_to_feature(
            project / "specs" / "product" / "gamma.md", project
        ) == "gamma-feature"


# ── Registry operations ───────────────────────────────────────────────────


class TestRebuildRegistry:
    def test_indexes_all_specs(self, conn, project: Path):
        count = rebuild_registry(conn, project)
        assert count == 5  # alpha×3 + beta + bug-123

    def test_spec_index_populated(self, conn, project: Path):
        rebuild_registry(conn, project)
        rows = conn.execute("SELECT * FROM spec_index ORDER BY path").fetchall()
        paths = [r["path"] for r in rows]
        assert "specs/product/alpha.md" in paths
        assert "specs/tech/alpha.md" in paths
        assert "specs/design/alpha.md" in paths

    def test_feature_specs_junction(self, conn, project: Path):
        rebuild_registry(conn, project)
        rows = conn.execute(
            "SELECT feature, spec_type FROM feature_specs WHERE feature = 'alpha' ORDER BY spec_type"
        ).fetchall()
        types = [r["spec_type"] for r in rows]
        assert "dsn" in types
        assert "prd" in types
        assert "rfc" in types

    def test_sections_stored(self, conn, project: Path):
        rebuild_registry(conn, project)
        count = conn.execute("SELECT count(*) FROM spec_sections").fetchone()[0]
        assert count > 10  # Multiple sections across 5 specs

    def test_completeness_stored(self, conn, project: Path):
        rebuild_registry(conn, project)
        row = conn.execute(
            "SELECT completeness FROM spec_index WHERE path = 'specs/product/alpha.md'"
        ).fetchone()
        assert row["completeness"] is not None
        assert 0.0 <= row["completeness"] <= 1.0

    def test_no_specs_dir(self, tmp_path: Path):
        empty_root = tmp_path / "empty_project"
        empty_root.mkdir()
        c = db.connect(str(empty_root))
        db.migrate(c)
        count = rebuild_registry(c, empty_root)
        c.close()
        assert count == 0


class TestUpdateSpec:
    def test_incremental_update(self, conn, project: Path):
        rebuild_registry(conn, project)

        # Modify a spec
        spec = project / "specs" / "product" / "alpha.md"
        spec.write_text(PRD + "\n## New Section\n\nNew content.\n")

        update_spec(conn, spec, project)

        row = conn.execute(
            "SELECT section_count FROM spec_index WHERE path = 'specs/product/alpha.md'"
        ).fetchone()
        sections = conn.execute(
            "SELECT heading FROM spec_sections WHERE spec_path = 'specs/product/alpha.md'"
        ).fetchall()
        headings = [r["heading"] for r in sections]
        assert "New Section" in headings

    def test_no_op_on_unchanged(self, conn, project: Path):
        rebuild_registry(conn, project)

        row_before = conn.execute(
            "SELECT updated_at FROM spec_index WHERE path = 'specs/product/alpha.md'"
        ).fetchone()

        # Update without changing content
        update_spec(conn, project / "specs" / "product" / "alpha.md", project)

        row_after = conn.execute(
            "SELECT updated_at FROM spec_index WHERE path = 'specs/product/alpha.md'"
        ).fetchone()
        assert row_before["updated_at"] == row_after["updated_at"]


class TestRemoveSpec:
    def test_removes_from_all_tables(self, conn, project: Path):
        rebuild_registry(conn, project)
        spec = project / "specs" / "product" / "alpha.md"
        remove_spec(conn, spec, project)

        assert conn.execute(
            "SELECT count(*) FROM spec_index WHERE path = 'specs/product/alpha.md'"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT count(*) FROM feature_specs WHERE spec_path = 'specs/product/alpha.md'"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT count(*) FROM spec_sections WHERE spec_path = 'specs/product/alpha.md'"
        ).fetchone()[0] == 0


# ── Ghost detection ────────────────────────────────────────────────────────


class TestDetectGhosts:
    def test_beta_missing_types(self, conn, project: Path):
        rebuild_registry(conn, project)
        ghosts = detect_ghosts(conn)
        beta_ghost = next((g for g in ghosts if g.feature == "beta"), None)
        assert beta_ghost is not None
        # beta only has a PRD, missing rfc and dsn
        assert "rfc" in beta_ghost.missing_types
        assert "dsn" in beta_ghost.missing_types

    def test_alpha_no_ghost(self, conn, project: Path):
        rebuild_registry(conn, project)
        ghosts = detect_ghosts(conn)
        alpha_ghost = next((g for g in ghosts if g.feature == "alpha"), None)
        # alpha has all three types
        assert alpha_ghost is None


# ── Lifecycle ──────────────────────────────────────────────────────────────


class TestLifecycle:
    def test_draft_to_reviewed(self, conn, project: Path):
        rebuild_registry(conn, project)
        result = transition_lifecycle(conn, "specs/product/alpha.md", "reviewed")
        assert result is True
        row = conn.execute(
            "SELECT lifecycle_state FROM spec_index WHERE path = 'specs/product/alpha.md'"
        ).fetchone()
        assert row["lifecycle_state"] == "reviewed"

    def test_reviewed_to_approved(self, conn, project: Path):
        rebuild_registry(conn, project)
        transition_lifecycle(conn, "specs/product/alpha.md", "reviewed")
        result = transition_lifecycle(conn, "specs/product/alpha.md", "approved")
        assert result is True

    def test_draft_to_approved_rejected(self, conn, project: Path):
        rebuild_registry(conn, project)
        result = transition_lifecycle(conn, "specs/product/alpha.md", "approved")
        assert result is False

    def test_nonexistent_spec(self, conn, project: Path):
        result = transition_lifecycle(conn, "nonexistent.md", "reviewed")
        assert result is False
