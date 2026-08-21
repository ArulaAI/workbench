"""Tests for dashboard/backend/resolvers/topology.py.

Covers CSG absence, empty graphs, full topology parsing with cluster
summaries, single-cluster detail retrieval, missing-cluster handling,
and verification that path resolution goes through the paths module.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Add the dashboard/ directory so 'backend' resolves as a top-level package.
_DASHBOARD_DIR = Path(__file__).resolve().parent.parent.parent
if str(_DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(_DASHBOARD_DIR))

from backend.paths import _cache
from backend.resolvers.topology import get_codebase_topology, get_cluster_detail


# ── Fixtures ──────────────────────────────────────────────────────


CSG_FIXTURE: dict = {
    "generated_at": "2026-03-20T12:00:00Z",
    "git_head": "abc1234",
    "nodes": [
        {
            "id": "n1",
            "name": "foo",
            "kind": "function",
            "file": "lib/foo.py",
            "line": 10,
            "cluster": "c1",
            "impact": {"blast_radius": 3, "centrality": 0.5},
        },
        {
            "id": "n2",
            "name": "bar",
            "kind": "function",
            "file": "lib/bar.py",
            "line": 20,
            "cluster": "c1",
            "impact": {"blast_radius": 2, "centrality": 0.3},
        },
        {
            "id": "n3",
            "name": "Baz",
            "kind": "class",
            "file": "lib/baz.py",
            "line": 1,
            "cluster": "c2",
            "impact": {"blast_radius": 5, "centrality": 0.9},
        },
    ],
    "edges": [
        {"from": "n1", "to": "n2", "type": "calls"},
        {"from": "n3", "to": "n1", "type": "imports"},
    ],
    "clusters": [
        {
            "id": "c1",
            "label": "Core Utils",
            "files": ["lib/foo.py", "lib/bar.py"],
            "cohesion": 0.85,
        },
        {
            "id": "c2",
            "label": "Models",
            "files": ["lib/baz.py"],
            "cohesion": 0.70,
        },
    ],
}


@pytest.fixture(autouse=True)
def _clear_paths_cache():
    """Ensure the paths module cache is empty before and after each test."""
    _cache.clear()
    yield
    _cache.clear()


def _write_csg(root: Path, data: dict) -> Path:
    """Write a semantic-graph.json into the conventional .speed/context/ location."""
    ctx = root / ".speed" / "context"
    ctx.mkdir(parents=True, exist_ok=True)
    csg_path = ctx / "semantic-graph.json"
    csg_path.write_text(json.dumps(data), encoding="utf-8")
    return csg_path


# ── Tests ─────────────────────────────────────────────────────────


class TestNoCsgFile:
    """When semantic-graph.json does not exist, the resolver returns None."""

    def test_no_csg_file(self, tmp_path: Path) -> None:
        # No .speed/context/ at all
        result = get_codebase_topology(str(tmp_path))
        assert result is None

    def test_context_dir_exists_but_no_csg(self, tmp_path: Path) -> None:
        (tmp_path / ".speed" / "context").mkdir(parents=True)
        result = get_codebase_topology(str(tmp_path))
        assert result is None


class TestEmptyCsg:
    """Valid JSON but empty nodes/edges produces an empty topology, not None."""

    def test_empty_csg(self, tmp_path: Path) -> None:
        _write_csg(tmp_path, {"nodes": [], "edges": [], "clusters": []})
        result = get_codebase_topology(str(tmp_path))

        assert result is not None
        assert result["node_count"] == 0
        assert result["edge_count"] == 0
        assert result["cluster_count"] == 0
        assert result["nodes"] == []
        assert result["edges"] == []
        assert result["clusters"] == []
        assert result["cluster_edges"] == []

    def test_missing_keys_treated_as_empty(self, tmp_path: Path) -> None:
        """A CSG with no nodes/edges/clusters keys should default to empty lists."""
        _write_csg(tmp_path, {})
        result = get_codebase_topology(str(tmp_path))

        assert result is not None
        assert result["node_count"] == 0
        assert result["edge_count"] == 0


class TestBasicTopology:
    """Full CSG with nodes, edges, and clusters produces correct summaries."""

    def test_top_level_counts(self, tmp_path: Path) -> None:
        _write_csg(tmp_path, CSG_FIXTURE)
        result = get_codebase_topology(str(tmp_path))

        assert result is not None
        assert result["node_count"] == 3
        assert result["edge_count"] == 2
        assert result["cluster_count"] == 2

    def test_metadata_passed_through(self, tmp_path: Path) -> None:
        _write_csg(tmp_path, CSG_FIXTURE)
        result = get_codebase_topology(str(tmp_path))

        assert result["generated_at"] == "2026-03-20T12:00:00Z"
        assert result["git_head"] == "abc1234"

    def test_cluster_summaries(self, tmp_path: Path) -> None:
        _write_csg(tmp_path, CSG_FIXTURE)
        result = get_codebase_topology(str(tmp_path))

        clusters_by_id = {c["id"]: c for c in result["clusters"]}

        c1 = clusters_by_id["c1"]
        assert c1["symbol_count"] == 2
        assert c1["files"] == ["lib/bar.py", "lib/foo.py"]  # sorted
        assert c1["kinds"] == ["function"]
        # avg blast radius: (3 + 2) / 2 = 2.5
        assert c1["avg_blast_radius"] == pytest.approx(2.5)

        c2 = clusters_by_id["c2"]
        assert c2["symbol_count"] == 1
        assert c2["files"] == ["lib/baz.py"]
        assert c2["kinds"] == ["class"]
        assert c2["avg_blast_radius"] == pytest.approx(5.0)

    def test_edges_normalized(self, tmp_path: Path) -> None:
        """Edges in the output use source/target/type regardless of CSG keys."""
        _write_csg(tmp_path, CSG_FIXTURE)
        result = get_codebase_topology(str(tmp_path))

        edges = result["edges"]
        assert len(edges) == 2
        assert edges[0] == {"source": "n1", "target": "n2", "type": "calls"}
        assert edges[1] == {"source": "n3", "target": "n1", "type": "imports"}

    def test_cluster_edges(self, tmp_path: Path) -> None:
        """Cross-cluster edges should appear in cluster_edges."""
        _write_csg(tmp_path, CSG_FIXTURE)
        result = get_codebase_topology(str(tmp_path))

        # n3 (c2) -> n1 (c1) is the only cross-cluster edge
        assert len(result["cluster_edges"]) == 1
        assert result["cluster_edges"][0] == {"source": "c2", "target": "c1"}

    def test_no_intra_cluster_in_cluster_edges(self, tmp_path: Path) -> None:
        """Edges within the same cluster should NOT appear in cluster_edges."""
        _write_csg(tmp_path, CSG_FIXTURE)
        result = get_codebase_topology(str(tmp_path))

        # n1 -> n2 are both c1; should not appear
        for ce in result["cluster_edges"]:
            assert not (ce["source"] == "c1" and ce["target"] == "c1")


class TestClusterDetail:
    """Requesting a specific cluster returns its nodes and edges."""

    def test_cluster_detail(self, tmp_path: Path) -> None:
        _write_csg(tmp_path, CSG_FIXTURE)
        result = get_cluster_detail(str(tmp_path), "c1")

        assert result is not None
        assert result["cluster_id"] == "c1"

        node_ids = {n["id"] for n in result["nodes"]}
        assert node_ids == {"n1", "n2"}

        # n1 -> n2 is internal to c1
        assert len(result["internal_edges"]) == 1
        assert result["internal_edges"][0]["source"] == "n1"
        assert result["internal_edges"][0]["target"] == "n2"

        # n3 -> n1 crosses from c2 into c1
        assert len(result["external_edges"]) == 1
        assert result["external_edges"][0]["source"] == "n3"
        assert result["external_edges"][0]["target"] == "n1"

    def test_cluster_detail_single_node(self, tmp_path: Path) -> None:
        _write_csg(tmp_path, CSG_FIXTURE)
        result = get_cluster_detail(str(tmp_path), "c2")

        assert result is not None
        assert len(result["nodes"]) == 1
        assert result["nodes"][0]["id"] == "n3"
        assert result["internal_edges"] == []
        # n3 -> n1 is external from c2's perspective
        assert len(result["external_edges"]) == 1


class TestClusterDetailNotFound:
    """Requesting a non-existent cluster returns an empty result, not None."""

    def test_cluster_detail_not_found(self, tmp_path: Path) -> None:
        _write_csg(tmp_path, CSG_FIXTURE)
        result = get_cluster_detail(str(tmp_path), "nonexistent")

        # The function still returns a dict (with empty lists), not None,
        # because the CSG itself loaded fine; there are just no matching nodes.
        assert result is not None
        assert result["cluster_id"] == "nonexistent"
        assert result["nodes"] == []
        assert result["internal_edges"] == []
        assert result["external_edges"] == []

    def test_cluster_detail_no_csg(self, tmp_path: Path) -> None:
        """When the CSG file is missing, cluster detail returns None."""
        result = get_cluster_detail(str(tmp_path), "c1")
        assert result is None


class TestUsesPathsModule:
    """The resolver reads CSG via paths.context_dir, not a hardcoded path.

    Creating .speed/shared/ triggers multiplayer mode, which changes some
    paths (features, memory, etc.) but context_dir stays at .speed/context/.
    The CSG should still be found because context_dir is mode-independent.
    """

    def test_mp_mode_still_finds_csg(self, tmp_path: Path) -> None:
        # Create the shared dir to trigger MP mode
        (tmp_path / ".speed" / "shared").mkdir(parents=True)
        _write_csg(tmp_path, CSG_FIXTURE)

        result = get_codebase_topology(str(tmp_path))
        assert result is not None
        assert result["node_count"] == 3

    def test_context_dir_used_not_hardcoded(self, tmp_path: Path) -> None:
        """Place the CSG in .speed/context/ (where paths.context_dir points)
        and confirm it loads. If topology used a hardcoded path that differed
        from context_dir, this would fail."""
        _write_csg(tmp_path, CSG_FIXTURE)

        result = get_codebase_topology(str(tmp_path))
        assert result is not None

        # Verify the paths module was actually used by checking the cache
        # was populated for this project root.
        assert str(tmp_path) in _cache
