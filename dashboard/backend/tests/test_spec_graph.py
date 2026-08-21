"""Tests for dashboard/backend/spec_graph.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from dashboard.backend import db
from dashboard.backend.spec_graph import (
    SpecEdge,
    parse_explicit_relationships,
    rebuild_edges,
)
from dashboard.backend.spec_registry import rebuild_registry
from .test_helpers import _write_file


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """Create a project with specs that have declared relationships."""
    specs = tmp_path / "specs"
    (specs / "product").mkdir(parents=True)
    (specs / "tech").mkdir(parents=True)
    (specs / "design").mkdir(parents=True)

    _write_file(specs / "product" / "alpha.md", """\
# Alpha PRD

## Problem
Something.

## Users
People.
""")

    _write_file(specs / "tech" / "alpha.md", """\
# RFC: Alpha

> See [product spec](../product/alpha.md) for product context.
> Depends on: [Foundation](beta.md), [Core](gamma.md)
> Parent RFC: [Umbrella](../umbrella.md)

## Basic Example
```python
alpha.run()
```

## Data Model
| Column | Type |
|--------|------|
| id | INTEGER |
""")

    _write_file(specs / "tech" / "beta.md", """\
# RFC: Beta

> See [product spec](../product/beta.md) for product context.

## Basic Example
Code.
""")

    _write_file(specs / "product" / "beta.md", """\
# Beta PRD

## Problem
Another thing.
""")

    _write_file(specs / "tech" / "gamma.md", """\
# RFC: Gamma

## Basic Example
Code.
""")

    _write_file(specs / "umbrella.md", """\
# Umbrella Spec

Overview of all specs.
""")

    return tmp_path


@pytest.fixture
def conn(project: Path):
    c = db.connect(str(project))
    db.migrate(c)
    yield c
    c.close()


# ── Explicit relationship parsing ──────────────────────────────────────────


class TestParseExplicitRelationships:
    def test_see_edge(self, project: Path):
        edges = parse_explicit_relationships(
            project / "specs" / "tech" / "alpha.md", project
        )
        see_edges = [e for e in edges if e.rel_type == "see"]
        assert len(see_edges) == 1
        assert see_edges[0].target == "specs/product/alpha.md"

    def test_depends_on_edges(self, project: Path):
        edges = parse_explicit_relationships(
            project / "specs" / "tech" / "alpha.md", project
        )
        dep_edges = [e for e in edges if e.rel_type == "depends_on"]
        assert len(dep_edges) == 2
        targets = {e.target for e in dep_edges}
        assert "specs/tech/beta.md" in targets
        assert "specs/tech/gamma.md" in targets

    def test_parent_rfc_edge(self, project: Path):
        edges = parse_explicit_relationships(
            project / "specs" / "tech" / "alpha.md", project
        )
        parent_edges = [e for e in edges if e.rel_type == "parent_rfc"]
        assert len(parent_edges) == 1
        assert parent_edges[0].target == "specs/umbrella.md"

    def test_all_edges_have_source(self, project: Path):
        edges = parse_explicit_relationships(
            project / "specs" / "tech" / "alpha.md", project
        )
        for e in edges:
            assert e.source == "specs/tech/alpha.md"

    def test_all_edges_have_evidence(self, project: Path):
        edges = parse_explicit_relationships(
            project / "specs" / "tech" / "alpha.md", project
        )
        for e in edges:
            assert e.evidence is not None
            assert len(e.evidence) > 0

    def test_no_relationships(self, project: Path):
        edges = parse_explicit_relationships(
            project / "specs" / "tech" / "gamma.md", project
        )
        assert edges == []

    def test_nonexistent_file(self, project: Path):
        edges = parse_explicit_relationships(
            project / "specs" / "nonexistent.md", project
        )
        assert edges == []

    def test_skips_non_md_targets(self, tmp_path: Path):
        _write_file(
            tmp_path / "specs" / "tech" / "test.md",
            "# Test\n\n> Depends on: code (`lib/foo.py`), [Spec](other.md)\n",
        )
        _write_file(tmp_path / "specs" / "tech" / "other.md", "# Other\n")
        edges = parse_explicit_relationships(
            tmp_path / "specs" / "tech" / "test.md", tmp_path
        )
        # Only the .md link should produce an edge
        assert len(edges) == 1
        assert edges[0].target == "specs/tech/other.md"

    def test_skips_http_links(self, tmp_path: Path):
        _write_file(
            tmp_path / "specs" / "tech" / "test.md",
            "# Test\n\n> See [docs](https://example.com/docs)\n",
        )
        edges = parse_explicit_relationships(
            tmp_path / "specs" / "tech" / "test.md", tmp_path
        )
        assert edges == []


# ── Path resolution ────────────────────────────────────────────────────────


class TestPathResolution:
    def test_relative_path_up(self, project: Path):
        """../product/alpha.md from specs/tech/ resolves to specs/product/alpha.md"""
        edges = parse_explicit_relationships(
            project / "specs" / "tech" / "alpha.md", project
        )
        see_edge = next(e for e in edges if e.rel_type == "see")
        assert see_edge.target == "specs/product/alpha.md"

    def test_same_directory_path(self, project: Path):
        """beta.md from specs/tech/ resolves to specs/tech/beta.md"""
        edges = parse_explicit_relationships(
            project / "specs" / "tech" / "alpha.md", project
        )
        dep_edges = [e for e in edges if e.rel_type == "depends_on"]
        beta_edge = next(e for e in dep_edges if "beta" in e.target)
        assert beta_edge.target == "specs/tech/beta.md"


# ── Full edge rebuild ──────────────────────────────────────────────────────


class TestRebuildEdges:
    def test_rebuilds_explicit_edges(self, conn, project: Path):
        rebuild_registry(conn, project)
        count = rebuild_edges(conn, project)
        assert count > 0

    def test_edges_in_database(self, conn, project: Path):
        rebuild_registry(conn, project)
        rebuild_edges(conn, project)

        rows = conn.execute(
            "SELECT source_spec, target_spec, rel_type FROM spec_edges ORDER BY source_spec, rel_type"
        ).fetchall()
        assert len(rows) > 0

        # Check for the known see edge
        see_edges = [r for r in rows if r["rel_type"] == "see"]
        assert any(
            r["source_spec"] == "specs/tech/alpha.md"
            and r["target_spec"] == "specs/product/alpha.md"
            for r in see_edges
        )

    def test_skips_edges_to_unknown_specs(self, conn, project: Path):
        """Edges to specs not in spec_index are not inserted."""
        rebuild_registry(conn, project)

        # Add a spec that references a nonexistent target
        _write_file(
            project / "specs" / "tech" / "orphan.md",
            "# Orphan\n\n> Depends on: [Missing](nonexistent.md)\n\n## Basic Example\nCode.\n",
        )
        rebuild_registry(conn, project)
        rebuild_edges(conn, project)

        orphan_edges = conn.execute(
            "SELECT * FROM spec_edges WHERE source_spec = 'specs/tech/orphan.md'"
        ).fetchall()
        # The edge to nonexistent.md should not exist
        for e in orphan_edges:
            assert e["target_spec"] != "specs/tech/nonexistent.md"

    def test_rebuild_idempotent(self, conn, project: Path):
        rebuild_registry(conn, project)
        count1 = rebuild_edges(conn, project)
        count2 = rebuild_edges(conn, project)
        assert count1 == count2

    def test_no_specs(self, conn, tmp_path: Path):
        count = rebuild_edges(conn, tmp_path)
        assert count == 0
