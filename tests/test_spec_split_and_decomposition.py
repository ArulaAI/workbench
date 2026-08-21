"""Tests for spec_split.py and decomposition_gate.py — pure logic, no external deps."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.context.spec_split import (
    _extract_h2,
    _resolve_indices,
    split_spec_for_phase,
    verify_spec_split,
)
from lib.decomposition_gate import (
    _build_dep_graph,
    _check_bridge_symbols,
    _check_cross_cluster,
    _check_file_ownership,
    _check_task_size,
    _is_transitive_dependent,
    check_decomposition,
    TASK_SIZE_FAIL,
    TASK_SIZE_WARN,
    CROSS_CLUSTER_FAIL,
)

import pytest


# ══════════════════════════════════════════════════════════════════
# spec_split tests
# ══════════════════════════════════════════════════════════════════


class TestExtractH2:
    def test_basic(self):
        text = "# Title\n## Intro\ntext\n## Design\nmore\n## API\n"
        assert _extract_h2(text) == ["Intro", "Design", "API"]

    def test_empty(self):
        assert _extract_h2("") == []

    def test_no_h2(self):
        assert _extract_h2("# Title\nsome text\n### Subsection\n") == []

    def test_h3_not_included(self):
        text = "## Real\n### Not This\n## Also Real\n"
        assert _extract_h2(text) == ["Real", "Also Real"]

    def test_preserves_annotations(self):
        text = "## **[NEW]** Authentication\n## **[MODIFIED v2]** API\n"
        assert _extract_h2(text) == ["**[NEW]** Authentication", "**[MODIFIED v2]** API"]

    def test_strips_whitespace(self):
        text = "##   Padded Heading  \n"
        assert _extract_h2(text) == ["Padded Heading"]


class TestResolveIndices:
    SPEC = "# Title\n## A\n## B\n## C\n"

    def test_valid_indices(self):
        resolved, errors = _resolve_indices(self.SPEC, [0, 2])
        assert resolved == ["A", "C"]
        assert errors == []

    def test_out_of_range(self):
        resolved, errors = _resolve_indices(self.SPEC, [5])
        assert resolved == []
        assert len(errors) == 1
        assert "out of range" in errors[0]

    def test_negative_index(self):
        _, errors = _resolve_indices(self.SPEC, [-1])
        assert len(errors) == 1

    def test_empty_indices(self):
        resolved, errors = _resolve_indices(self.SPEC, [])
        assert resolved == []
        assert errors == []

    def test_mixed_valid_invalid(self):
        resolved, errors = _resolve_indices(self.SPEC, [0, 99, 1])
        assert resolved == ["A", "B"]
        assert len(errors) == 1


class TestSplitSpecForPhase:
    SPEC = "# Title\nPreamble text.\n## Auth\nAuth content.\n## API\nAPI content.\n## DB\nDB content.\n"

    def test_exclude_one_section(self):
        result = split_spec_for_phase(self.SPEC, [1])  # exclude API
        assert "Auth content." in result
        assert "DB content." in result
        assert "API content." not in result

    def test_exclude_nothing(self):
        result = split_spec_for_phase(self.SPEC, [])
        assert result == self.SPEC

    def test_preamble_always_preserved(self):
        result = split_spec_for_phase(self.SPEC, [0, 1, 2])
        assert "Preamble text." in result

    def test_invalid_index_raises(self):
        with pytest.raises(ValueError, match="out of range"):
            split_spec_for_phase(self.SPEC, [99])

    def test_exclude_multiple(self):
        result = split_spec_for_phase(self.SPEC, [0, 2])  # exclude Auth and DB
        assert "API content." in result
        assert "Auth content." not in result
        assert "DB content." not in result


class TestVerifySpecSplit:
    ORIGINAL = "# Title\n## A\nA content.\n## B\nB content.\n## C\nC content.\n"

    def test_good_split_passes(self):
        phase1 = "# Title\n## A\nA content.\n## B\nB content.\n"
        phase2 = "# Title\n## B\nB content.\n## C\nC content.\n"
        result = verify_spec_split(self.ORIGINAL, phase1, phase2, [0, 1], [1, 2])
        assert result["pass"] is True
        assert result["errors"] == []

    def test_missing_section_fails(self):
        phase1 = "# Title\n## A\nA content.\n"
        phase2 = "# Title\n## C\nC content.\n"
        result = verify_spec_split(self.ORIGINAL, phase1, phase2, [0], [2])
        assert result["pass"] is False
        assert any("B" in e for e in result["errors"])

    def test_size_warning(self):
        phase1 = "# Title\n## A\nA content.\n"
        phase2 = self.ORIGINAL
        result = verify_spec_split(self.ORIGINAL, phase1, phase2, [0], [0, 1, 2], min_size_pct=50.0)
        assert len(result["warnings"]) >= 1
        assert "Phase 1" in result["warnings"][0]

    def test_invalid_index_error(self):
        result = verify_spec_split(self.ORIGINAL, self.ORIGINAL, self.ORIGINAL, [99], [0])
        assert result["pass"] is False
        assert any("out of range" in e for e in result["errors"])

    def test_empty_original(self):
        result = verify_spec_split("", "", "", [], [])
        assert result["pass"] is True


# ══════════════════════════════════════════════════════════════════
# decomposition_gate tests
# ══════════════════════════════════════════════════════════════════


def _project_map(*files):
    """Helper: build a project_map dict from (path, lines) tuples."""
    return {"files": [{"path": p, "lines": l} for p, l in files]}


class TestBuildDepGraph:
    def test_basic(self):
        tasks = [
            {"id": "1", "depends_on": []},
            {"id": "2", "depends_on": ["1"]},
            {"id": "3", "depends_on": ["1"]},
        ]
        graph = _build_dep_graph(tasks)
        assert graph["1"] == {"2", "3"}
        assert "2" not in graph
        assert "3" not in graph

    def test_empty(self):
        assert _build_dep_graph([]) == {}

    def test_string_depends_on(self):
        tasks = [{"id": "1"}, {"id": "2", "depends_on": "1"}]
        graph = _build_dep_graph(tasks)
        assert graph["1"] == {"2"}

    def test_chain(self):
        tasks = [
            {"id": "1"},
            {"id": "2", "depends_on": ["1"]},
            {"id": "3", "depends_on": ["2"]},
        ]
        graph = _build_dep_graph(tasks)
        assert graph["1"] == {"2"}
        assert graph["2"] == {"3"}


class TestIsTransitiveDependent:
    def test_direct(self):
        graph = {"A": {"B"}}
        assert _is_transitive_dependent("A", "B", graph) is True

    def test_transitive(self):
        graph = {"A": {"B"}, "B": {"C"}}
        assert _is_transitive_dependent("A", "C", graph) is True

    def test_no_path(self):
        graph = {"A": {"B"}}
        assert _is_transitive_dependent("A", "C", graph) is False

    def test_reverse_direction(self):
        graph = {"A": {"B"}}
        assert _is_transitive_dependent("B", "A", graph) is False

    def test_empty_graph(self):
        assert _is_transitive_dependent("A", "B", {}) is False

    def test_cycle_terminates(self):
        graph = {"A": {"B"}, "B": {"A"}}
        assert _is_transitive_dependent("A", "C", graph) is False


class TestCheckTaskSize:
    def test_pass(self):
        task = {"id": "1", "files_touched": ["a.py", "b.py"]}
        pm = _project_map(("a.py", 100), ("b.py", 200))
        result = _check_task_size(task, pm)
        assert result["verdict"] == "pass"
        assert result["total_lines"] == 300

    def test_warn(self):
        task = {"id": "1", "files_touched": ["big.py"]}
        pm = _project_map(("big.py", TASK_SIZE_WARN + 1))
        result = _check_task_size(task, pm)
        assert result["verdict"] == "warn"

    def test_fail(self):
        task = {"id": "1", "files_touched": ["huge.py"]}
        pm = _project_map(("huge.py", TASK_SIZE_FAIL))
        result = _check_task_size(task, pm)
        assert result["verdict"] == "fail"

    def test_exactly_at_warn_is_pass(self):
        task = {"id": "1", "files_touched": ["x.py"]}
        pm = _project_map(("x.py", TASK_SIZE_WARN))
        result = _check_task_size(task, pm)
        assert result["verdict"] == "pass"

    def test_unknown_files_counted_as_zero(self):
        task = {"id": "1", "files_touched": ["new_file.py"]}
        pm = _project_map()
        result = _check_task_size(task, pm)
        assert result["verdict"] == "pass"
        assert result["total_lines"] == 0

    def test_no_files(self):
        task = {"id": "1", "files_touched": []}
        result = _check_task_size(task, _project_map())
        assert result["verdict"] == "pass"


class TestCheckCrossCluster:
    def _csg(self, clusters, cluster_edges=None):
        return {"clusters": clusters, "cluster_edges": cluster_edges or []}

    def test_single_cluster_passes(self):
        csg = self._csg([{"id": "c1", "files": ["a.py", "b.py"]}])
        task = {"id": "1", "files_touched": ["a.py", "b.py"]}
        result = _check_cross_cluster(task, csg)
        assert result["verdict"] == "pass"

    def test_two_clusters_low_edges_passes(self):
        csg = self._csg(
            [{"id": "c1", "files": ["a.py"]}, {"id": "c2", "files": ["b.py"]}],
            [{"from": "c1", "to": "c2", "edge_count": 5}],
        )
        task = {"id": "1", "files_touched": ["a.py", "b.py"]}
        result = _check_cross_cluster(task, csg)
        assert result["verdict"] == "pass"
        assert result["cross_cluster_edges"] == 5

    def test_high_cross_edges_fails(self):
        csg = self._csg(
            [{"id": "c1", "files": ["a.py"]}, {"id": "c2", "files": ["b.py"]}],
            [{"from": "c1", "to": "c2", "edge_count": CROSS_CLUSTER_FAIL + 1}],
        )
        task = {"id": "1", "files_touched": ["a.py", "b.py"]}
        result = _check_cross_cluster(task, csg)
        assert result["verdict"] == "fail"

    def test_file_not_in_any_cluster(self):
        csg = self._csg([{"id": "c1", "files": ["a.py"]}])
        task = {"id": "1", "files_touched": ["unknown.py"]}
        result = _check_cross_cluster(task, csg)
        assert result["verdict"] == "pass"
        assert result["clusters_touched"] == 0


class TestCheckFileOwnership:
    def test_no_overlap_passes(self):
        tasks = [
            {"id": "1", "files_touched": ["a.py"]},
            {"id": "2", "files_touched": ["b.py"]},
        ]
        result = _check_file_ownership(tasks, _build_dep_graph(tasks))
        assert result["violations"] == []

    def test_overlap_with_dependency_passes(self):
        tasks = [
            {"id": "1", "files_touched": ["shared.py"]},
            {"id": "2", "files_touched": ["shared.py"], "depends_on": ["1"]},
        ]
        result = _check_file_ownership(tasks, _build_dep_graph(tasks))
        assert result["violations"] == []

    def test_overlap_without_dependency_fails(self):
        tasks = [
            {"id": "1", "files_touched": ["shared.py"]},
            {"id": "2", "files_touched": ["shared.py"]},
        ]
        result = _check_file_ownership(tasks, _build_dep_graph(tasks))
        assert len(result["violations"]) == 1
        assert "shared.py" in result["violations"][0]["file"]

    def test_transitive_dependency_passes(self):
        tasks = [
            {"id": "1", "files_touched": ["shared.py"]},
            {"id": "2", "depends_on": ["1"]},
            {"id": "3", "files_touched": ["shared.py"], "depends_on": ["2"]},
        ]
        result = _check_file_ownership(tasks, _build_dep_graph(tasks))
        assert result["violations"] == []

    def test_three_tasks_one_file_partial_deps(self):
        tasks = [
            {"id": "1", "files_touched": ["x.py"]},
            {"id": "2", "files_touched": ["x.py"], "depends_on": ["1"]},
            {"id": "3", "files_touched": ["x.py"]},
        ]
        result = _check_file_ownership(tasks, _build_dep_graph(tasks))
        assert len(result["violations"]) >= 1


class TestCheckBridgeSymbols:
    def _csg_with_bridge(self):
        return {
            "nodes": [
                {"id": "sym1", "file": "lib/api.py", "impact": {"stability": "bridge"}},
                {"id": "sym2", "file": "app/handler.py"},
            ],
            "edges": [{"from": "sym2", "to": "sym1", "type": "calls"}],
            "clusters": [],
            "cluster_edges": [],
        }

    def test_no_bridge_symbols_passes(self):
        csg = {"nodes": [], "edges": [], "clusters": [], "cluster_edges": []}
        task = {"id": "1", "files_touched": ["a.py"]}
        result = _check_bridge_symbols(task, [task], csg, {})
        assert result["verdict"] == "pass"

    def test_bridge_with_dependency_passes(self):
        csg = self._csg_with_bridge()
        tasks = [
            {"id": "1", "files_touched": ["lib/api.py"]},
            {"id": "2", "files_touched": ["app/handler.py"], "depends_on": ["1"]},
        ]
        dep_graph = _build_dep_graph(tasks)
        result = _check_bridge_symbols(tasks[0], tasks, csg, dep_graph)
        assert result["verdict"] == "pass"

    def test_bridge_missing_dependency_fails(self):
        csg = self._csg_with_bridge()
        tasks = [
            {"id": "1", "files_touched": ["lib/api.py"]},
            {"id": "2", "files_touched": ["app/handler.py"]},
        ]
        dep_graph = _build_dep_graph(tasks)
        result = _check_bridge_symbols(tasks[0], tasks, csg, dep_graph)
        assert result["verdict"] == "fail"
        assert len(result["missing_dependencies"]) == 1


class TestCheckDecomposition:
    def test_all_pass_no_csg(self):
        tasks = [
            {"id": "1", "files_touched": ["a.py"]},
            {"id": "2", "files_touched": ["b.py"]},
        ]
        pm = _project_map(("a.py", 100), ("b.py", 200))
        result = check_decomposition(tasks, pm, csg=None)
        assert result["overall"] == "pass"

    def test_size_fail_propagates(self):
        tasks = [{"id": "1", "files_touched": ["huge.py"]}]
        pm = _project_map(("huge.py", TASK_SIZE_FAIL))
        result = check_decomposition(tasks, pm)
        assert result["overall"] == "fail"

    def test_ownership_fail_propagates(self):
        tasks = [
            {"id": "1", "files_touched": ["shared.py"]},
            {"id": "2", "files_touched": ["shared.py"]},
        ]
        pm = _project_map(("shared.py", 50))
        result = check_decomposition(tasks, pm)
        assert result["overall"] == "fail"
        assert len(result["file_ownership"]["violations"]) == 1

    def test_csg_skipped_checks_noted(self):
        tasks = [{"id": "1", "files_touched": ["a.py"]}]
        pm = _project_map(("a.py", 10))
        result = check_decomposition(tasks, pm, csg=None)
        checks = result["per_task"][0]["checks"]
        skipped = [c for c in checks if c["verdict"] == "skipped"]
        assert len(skipped) == 2
