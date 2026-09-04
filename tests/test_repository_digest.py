"""Unit tests for lib/context/repository_digest.py and its freshness/schema
helpers. See specs/tech/speed-repository-digest-dashboard.md > Testing.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from lib.context.repository_digest import (
    DigestInputError,
    attach_changes_history,
    attach_effective_state,
    build_repository_digest,
    load_repository_digest,
    load_repository_digest_with_status,
    project_digest_for_agent,
    repository_digest_input_paths,
)
from lib.context.repository_digest_freshness import (
    compute_digest_freshness,
    compute_fingerprint,
)
from lib.context.repository_digest_schema import (
    empty_digest_body,
    normalize_confidence,
    validate_digest,
)
from lib.context import command_discovery


# ── Fixtures ────────────────────────────────────────────────────


def write_project_map(root: Path, files: list[dict], by_language: dict | None = None) -> None:
    ctx = root / ".speed" / "context"
    ctx.mkdir(parents=True, exist_ok=True)
    total_lines = sum(f.get("lines", 0) for f in files)
    (ctx / "project-map.json").write_text(json.dumps({
        "generated_at": "2026-01-01T00:00:00Z",
        "git_head": "abc123",
        "project_root": str(root),
        "summary": {
            "total_files": len(files),
            "total_lines": total_lines,
            "by_language": by_language or {},
        },
        "files": files,
        "directories": [],
    }))


def write_semantic_graph(root: Path, nodes: list[dict], edges: list[dict] | None = None,
                          clusters: list[dict] | None = None, cluster_edges: list[dict] | None = None) -> None:
    ctx = root / ".speed" / "context"
    ctx.mkdir(parents=True, exist_ok=True)
    (ctx / "semantic-graph.json").write_text(json.dumps({
        "generated_at": "2026-01-01T00:00:00Z",
        "git_head": "abc123",
        "nodes": nodes,
        "edges": edges or [],
        "clusters": clusters or [],
        "cluster_edges": cluster_edges or [],
    }))


def make_node(id_, file="a.py", blast=0, dependents=0, centrality=0.0, stability="stable", line=1):
    return {
        "id": id_, "name": id_.split("::")[-1], "kind": "function", "file": file, "line": line,
        "impact": {"blast_radius": blast, "dependents": dependents, "centrality": centrality, "stability": stability},
    }


def minimal_repo(tmp_path: Path, n_files: int = 2) -> Path:
    files = [{"path": f"f{i}.py", "language": "python", "lines": 10, "category": "source"} for i in range(n_files)]
    write_project_map(tmp_path, files, by_language={"python": {"files": n_files, "lines": 10 * n_files}})
    return tmp_path


# ── Required project-map validation ──────────────────────────────


def test_missing_project_map_raises_digest_input_error(tmp_path):
    with pytest.raises(DigestInputError):
        build_repository_digest(str(tmp_path), config={})


def test_structurally_invalid_project_map_raises(tmp_path):
    ctx = tmp_path / ".speed" / "context"
    ctx.mkdir(parents=True)
    (ctx / "project-map.json").write_text(json.dumps({"not_files_or_summary": True}))
    with pytest.raises(DigestInputError):
        build_repository_digest(str(tmp_path), config={})


def test_project_map_files_wrong_type_raises(tmp_path):
    """'files' present but not a list — presence-only checking let this
    through and crashed generation downstream (review: 'malformed
    project-map member types crash generation')."""
    ctx = tmp_path / ".speed" / "context"
    ctx.mkdir(parents=True)
    (ctx / "project-map.json").write_text(json.dumps({"files": "not-a-list", "summary": {}}))
    with pytest.raises(DigestInputError):
        build_repository_digest(str(tmp_path), config={})


def test_project_map_summary_wrong_type_raises(tmp_path):
    ctx = tmp_path / ".speed" / "context"
    ctx.mkdir(parents=True)
    (ctx / "project-map.json").write_text(json.dumps({"files": [], "summary": "not-a-dict"}))
    with pytest.raises(DigestInputError):
        build_repository_digest(str(tmp_path), config={})


def test_project_map_with_non_object_file_entry_does_not_crash(tmp_path):
    """A file entry that isn't an object must be skipped, not crash the
    whole build — same input-isolation guarantee as an unavailable
    optional artifact."""
    ctx = tmp_path / ".speed" / "context"
    ctx.mkdir(parents=True)
    (ctx / "project-map.json").write_text(json.dumps({
        "files": [
            {"path": "f0.py", "language": "python", "lines": 10, "category": "source"},
            "not-an-object",
            42,
        ],
        "summary": {"total_files": 2, "total_lines": 10, "by_language": {"python": {"files": 1, "lines": 10}}},
    }))
    digest = build_repository_digest(str(tmp_path), config={})  # must not raise
    assert digest["status"] in ("partial", "complete")
    assert any("not an object" in w for w in digest["warnings"])


def test_minimum_valid_input_is_project_map_only(tmp_path):
    minimal_repo(tmp_path)
    digest = build_repository_digest(str(tmp_path), config={})
    assert digest["status"] == "partial"
    assert digest["footprint"]["file_count"] == 2
    assert digest["domains"] == []
    assert digest["hotspots"] == []


# ── Optional loader isolation ────────────────────────────────────


def test_invalid_conventions_do_not_remove_domains(tmp_path):
    write_project_map(tmp_path, [{"path": "a.py", "language": "python", "lines": 5, "category": "source"}])
    write_semantic_graph(
        tmp_path,
        nodes=[make_node("a.py::foo")],
        clusters=[{"id": "c0", "label": "Core", "symbols": ["a.py::foo"], "files": ["a.py"], "cohesion": 1.0}],
    )
    mem = tmp_path / ".speed" / "memory"
    mem.mkdir(parents=True)
    (mem / "conventions.json").write_text("{not-json")

    digest = build_repository_digest(str(tmp_path), config={})

    assert digest["status"] == "partial"
    assert digest["domains"]
    assert digest["conventions"] == []
    conv = [r for r in digest["readiness"] if r["capability"] == "conventions"][0]
    assert conv["status"] == "invalid"


def test_missing_semantic_graph_marks_unavailable_not_invalid(tmp_path):
    minimal_repo(tmp_path)
    digest = build_repository_digest(str(tmp_path), config={})
    csg_readiness = [r for r in digest["readiness"] if r["capability"] == "semantic_graph"][0]
    assert csg_readiness["status"] == "unavailable"
    assert digest["footprint"]["symbol_count"] is None
    assert digest["footprint"]["domain_count"] is None


# ── Footprint rollups ─────────────────────────────────────────────


def test_footprint_language_percentages_sum_reasonably(tmp_path):
    write_project_map(
        tmp_path,
        [{"path": "a.py", "language": "python", "lines": 60, "category": "source"},
         {"path": "b.ts", "language": "typescript", "lines": 40, "category": "source"}],
        by_language={"python": {"files": 1, "lines": 60}, "typescript": {"files": 1, "lines": 40}},
    )
    digest = build_repository_digest(str(tmp_path), config={})
    percents = {l["name"]: l["percent"] for l in digest["footprint"]["languages"]}
    assert percents["python"] == 60.0
    assert percents["typescript"] == 40.0


def test_footprint_zero_lines_does_not_divide_by_zero(tmp_path):
    write_project_map(tmp_path, [{"path": "a.bin", "language": None, "lines": 0, "category": "asset"}])
    digest = build_repository_digest(str(tmp_path), config={})
    assert digest["footprint"]["line_count"] == 0
    assert digest["footprint"]["asset_file_count"] == 1


# ── Domain ranking, tie-breaking, labeling ───────────────────────


def test_domain_ranking_is_deterministic_when_scores_tie(tmp_path):
    write_project_map(tmp_path, [{"path": "a.py", "language": "python", "lines": 10, "category": "source"}])
    nodes = [make_node(f"a.py::sym{i}", blast=3) for i in range(10)]
    write_semantic_graph(
        tmp_path, nodes=nodes,
        clusters=[
            {"id": "cluster-b", "label": "B", "symbols": [n["id"] for n in nodes[:5]], "files": ["a.py"] * 5, "cohesion": 0.5},
            {"id": "cluster-a", "label": "A", "symbols": [n["id"] for n in nodes[5:]], "files": ["a.py"] * 5, "cohesion": 0.5},
        ],
    )
    digest = build_repository_digest(str(tmp_path), config={})
    ranks = [(d["id"], d["rank"]) for d in digest["domains"]]
    assert ranks[0][1] == 1
    assert ranks[1][1] == 2


def test_domain_label_falls_back_to_unlabeled_with_unknown_confidence(tmp_path):
    write_project_map(tmp_path, [{"path": "src/util.py", "language": "python", "lines": 5, "category": "source"}])
    write_semantic_graph(
        tmp_path,
        nodes=[make_node("src/util.py::x")],
        clusters=[{"id": "c-17a2", "label": "", "symbols": ["src/util.py::x"],
                   "files": ["src/util.py", "src/common.py", "src/helpers.py"], "cohesion": 0.1}],
    )
    digest = build_repository_digest(str(tmp_path), config={})
    domain = digest["domains"][0]
    assert domain["confidence"] == "unknown"
    assert domain["label"].startswith("Unlabeled domain")
    assert any(g["type"] == "domain_label_unresolved" for g in digest["gaps"])


def test_existing_layer1_label_is_preferred(tmp_path):
    write_project_map(tmp_path, [{"path": "orders/checkout.py", "language": "python", "lines": 5, "category": "source"}])
    write_semantic_graph(
        tmp_path,
        nodes=[make_node("orders/checkout.py::checkout")],
        clusters=[{"id": "c0", "label": "Orders", "symbols": ["orders/checkout.py::checkout"],
                   "files": ["orders/checkout.py"], "cohesion": 0.9}],
    )
    digest = build_repository_digest(str(tmp_path), config={})
    assert digest["domains"][0]["label"] == "Orders"
    assert digest["domains"][0]["confidence"] == "derived"


# ── Hotspots ──────────────────────────────────────────────────────


def test_hotspot_ordering_blast_radius_then_dependents_then_centrality(tmp_path):
    write_project_map(tmp_path, [{"path": "a.py", "language": "python", "lines": 5, "category": "source"}])
    write_semantic_graph(tmp_path, nodes=[
        make_node("a.py::low", blast=1, dependents=1, centrality=0.1),
        make_node("a.py::high", blast=10, dependents=5, centrality=0.9),
    ])
    digest = build_repository_digest(str(tmp_path), config={})
    assert digest["hotspots"][0]["symbol_id"] == "a.py::high"


# ── Commands ────────────────────────────────────────────────────


def test_conflicting_root_commands_produce_gap_and_risk(tmp_path):
    minimal_repo(tmp_path)
    (tmp_path / "CLAUDE.md").write_text(
        "# Project\n\n## Test\n\n```bash\nnpm test\n```\n"
    )
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run"}}))
    digest = build_repository_digest(str(tmp_path), config={})
    test_commands = {c["command"] for c in digest["commands"] if c["purpose"] == "test" and c["working_directory"] == "."}
    assert len(test_commands) >= 2
    assert any(g["type"] == "conflicting_commands" for g in digest["gaps"])
    assert any(r["type"] == "conflicting_discovery" for r in digest["risks"])


def test_commands_never_include_the_word_subprocess_execution():
    # Commands are data, never executed. This is a static assertion that the
    # module doesn't call subprocess/os.system on discovered command text.
    import inspect
    from lib.context import command_discovery as cd
    source = inspect.getsource(cd)
    assert "subprocess.run" not in source
    assert "os.system" not in source


# ── Conventions confidence mapping ───────────────────────────────


def test_conventions_confidence_mapped_by_source(tmp_path):
    write_project_map(tmp_path, [{"path": "a.py", "language": "python", "lines": 5, "category": "source"}])
    mem = tmp_path / ".speed" / "memory"
    mem.mkdir(parents=True)
    (mem / "conventions.json").write_text(json.dumps({
        "conventions": [
            {"id": "conv-1", "convention": "Use ruff import ordering", "scope": ["lib/"], "source": "config", "canonical_example": "pyproject.toml"},
            {"id": "conv-2", "convention": "Use snake_case for functions", "scope": ["lib/"], "source": "discovered", "canonical_example": "lib/a.py:1"},
        ],
        "conflicts": [], "views": {},
    }))
    digest = build_repository_digest(str(tmp_path), config={})
    by_source = {c["text"]: c["confidence"] for c in digest["conventions"]}
    assert by_source["Use ruff import ordering"] == "confirmed"
    assert by_source["Use snake_case for functions"] == "derived"
    for c in digest["conventions"]:
        assert c["evidence"]


# ── Gap aggregation ───────────────────────────────────────────────


def test_gaps_aggregate_from_identity_domain_and_command_stages(tmp_path):
    write_project_map(tmp_path, [{"path": "src/x.py", "language": "python", "lines": 1, "category": "source"}])
    write_semantic_graph(
        tmp_path, nodes=[make_node("src/x.py::x")],
        clusters=[{"id": "c-unlabeled", "label": "", "symbols": ["src/x.py::x"], "files": ["src/util.py", "src/common.py", "src/helpers.py"], "cohesion": 0.1}],
    )
    digest = build_repository_digest(str(tmp_path), config={})
    gap_types = {g["type"] for g in digest["gaps"]}
    assert "purpose_not_discovered" in gap_types  # no README present
    assert "domain_label_unresolved" in gap_types


# ── Confidence assignment / evidence validation ──────────────────


def test_normalize_confidence_unknown_input_becomes_unknown():
    assert normalize_confidence("bogus") == "unknown"
    assert normalize_confidence("confirmed") == "confirmed"


def _minimal_valid_digest(**overrides):
    digest = {
        "schema_version": 1, "status": "partial",
        "generated_at": "2026-01-01T00:00:00Z",
        "generator": {"name": "speed-repository-digest", "version": "1"},
        "fingerprint": {},
        "identity": {"name": "demo", "summary": "", "evidence": []},
        "footprint": {"file_count": 0, "line_count": 0, "languages": []},
        **empty_digest_body(),
    }
    digest.update(overrides)
    return digest


def test_validate_digest_flags_missing_evidence():
    digest = _minimal_valid_digest(
        status="complete",
        identity={"name": "demo", "summary": "has no evidence", "evidence": []},
    )
    issues = validate_digest(digest)
    assert any("evidence" in i for i in issues)


def test_validate_digest_accepts_well_formed_empty_digest():
    assert validate_digest(_minimal_valid_digest()) == []


# ── validate_digest never raises, and rejects what previously crashed
# dashboard/backend/resolvers/repository_digest_types.py::to_repository_digest ──


def test_validate_digest_never_raises_on_completely_malformed_input():
    for bad in (None, [], "a string", 42, {}, {"domains": "not-a-list"}):
        issues = validate_digest(bad)
        assert isinstance(issues, list)
        assert issues  # every one of these is invalid


def test_validate_digest_rejects_missing_identity():
    digest = _minimal_valid_digest()
    del digest["identity"]
    issues = validate_digest(digest)
    assert any("identity" in i for i in issues)


def test_validate_digest_rejects_identity_wrong_type():
    digest = _minimal_valid_digest(identity="not-an-object")
    issues = validate_digest(digest)
    assert any("identity" in i for i in issues)


def test_validate_digest_rejects_identity_missing_name():
    digest = _minimal_valid_digest(identity={"summary": "", "evidence": []})
    issues = validate_digest(digest)
    assert any("identity.name" in i for i in issues)


def test_validate_digest_rejects_missing_footprint():
    digest = _minimal_valid_digest()
    del digest["footprint"]
    issues = validate_digest(digest)
    assert any("footprint" in i for i in issues)


def test_validate_digest_rejects_footprint_wrong_type():
    digest = _minimal_valid_digest(footprint="not-an-object")
    issues = validate_digest(digest)
    assert any("footprint" in i for i in issues)


def test_validate_digest_rejects_footprint_file_count_wrong_type():
    digest = _minimal_valid_digest(footprint={"file_count": "many", "line_count": 0})
    issues = validate_digest(digest)
    assert any("file_count" in i for i in issues)


def test_validate_digest_rejects_malformed_language_entry():
    digest = _minimal_valid_digest(
        footprint={"file_count": 1, "line_count": 1, "languages": [{"name": "python"}]}
    )
    issues = validate_digest(digest)
    assert any("languages" in i for i in issues)


def test_validate_digest_rejects_missing_generated_at():
    digest = _minimal_valid_digest()
    del digest["generated_at"]
    issues = validate_digest(digest)
    assert any("generated_at" in i for i in issues)


def test_validate_digest_rejects_non_object_domain_entry():
    digest = _minimal_valid_digest()
    digest["domains"] = ["not-an-object"]
    issues = validate_digest(digest)
    assert any("domains" in i for i in issues)


def test_validate_digest_rejects_non_object_command_entry():
    digest = _minimal_valid_digest()
    digest["commands"] = [42]
    issues = validate_digest(digest)
    assert any("commands" in i for i in issues)


def test_validate_digest_rejects_non_object_relationship_entry():
    digest = _minimal_valid_digest()
    digest["relationships"] = ["oops"]
    issues = validate_digest(digest)
    assert any("relationships" in i for i in issues)


def test_validate_digest_does_not_crash_on_domain_that_is_not_a_dict():
    """The exact shape the review confirmed passes validation and later
    crashes to_repository_digest() with KeyError/TypeError."""
    digest = _minimal_valid_digest()
    digest["domains"] = [None, 42, "a string", ["nested", "list"]]
    issues = validate_digest(digest)  # must not raise
    assert issues  # and must not silently accept it either


# ── Path normalization / security ────────────────────────────────


def test_sanitize_csg_drops_node_with_absolute_path_outside_root(tmp_path):
    """The exact scenario the review confirmed: /Users/example/.ssh/id_rsa
    surviving into representative_files / domain evidence / hotspot
    evidence."""
    from lib.context.repository_digest import _sanitize_csg
    csg = {
        "nodes": [
            {"id": "sym1", "file": "/Users/example/.ssh/id_rsa", "name": "leak"},
            {"id": "sym2", "file": "lib/real_file.py", "name": "real"},
        ],
    }
    warnings: list[str] = []
    _sanitize_csg(csg, tmp_path, warnings)
    files = {n["file"] for n in csg["nodes"]}
    assert "/Users/example/.ssh/id_rsa" not in files
    assert "lib/real_file.py" in files
    assert any("outside the repository root" in w for w in warnings)


def test_sanitize_csg_drops_node_with_traversal_path(tmp_path):
    from lib.context.repository_digest import _sanitize_csg
    csg = {"nodes": [{"id": "sym1", "file": "../../secret", "name": "leak"}]}
    warnings: list[str] = []
    _sanitize_csg(csg, tmp_path, warnings)
    assert csg["nodes"] == []


def test_sanitize_csg_drops_malformed_nodes_without_crashing(tmp_path):
    from lib.context.repository_digest import _sanitize_csg
    csg = {"nodes": [None, 42, "a string", {"no_id": True}, {"id": "ok", "file": "a.py"}]}
    warnings: list[str] = []
    _sanitize_csg(csg, tmp_path, warnings)  # must not raise
    assert [n["id"] for n in csg["nodes"]] == ["ok"]
    assert any("not valid objects" in w for w in warnings)


def test_sanitize_csg_filters_cluster_files_the_same_way(tmp_path):
    from lib.context.repository_digest import _sanitize_csg
    csg = {
        "nodes": [],
        "clusters": [{"id": "c1", "files": ["lib/real.py", "/etc/passwd", "../outside"]}],
    }
    _sanitize_csg(csg, tmp_path, [])
    assert csg["clusters"][0]["files"] == ["lib/real.py"]


def test_sanitize_csg_drops_a_cluster_repeating_an_earlier_id(tmp_path):
    """Architecture data-quality audit: a well-formed CSG never repeats a
    cluster id (Layer 1 assigns them from one enumeration), but a
    tampered/hand-edited/multiplayer-shared file could — every downstream
    consumer keys strictly by id, so two clusters sharing one would let
    the second silently shadow the first rather than surfacing as two
    domains or a clear error. The first one seen wins.
    """
    from lib.context.repository_digest import _sanitize_csg
    csg = {
        "nodes": [],
        "clusters": [
            {"id": "c1", "label": "first", "files": ["a.py"]},
            {"id": "c1", "label": "second", "files": ["b.py"]},
        ],
    }
    _sanitize_csg(csg, tmp_path, [])
    assert len(csg["clusters"]) == 1
    assert csg["clusters"][0]["label"] == "first"


def test_sanitize_csg_drops_a_cluster_edge_repeating_an_earlier_pair(tmp_path):
    """Same rationale as cluster-id dedup: a tampered file repeating a
    (from, to) cluster_edge pair would otherwise render as a visibly
    duplicated relationship on the Architecture screen.
    """
    from lib.context.repository_digest import _sanitize_csg
    csg = {
        "nodes": [],
        "cluster_edges": [
            {"from": "c1", "to": "c2", "edge_count": 3},
            {"from": "c1", "to": "c2", "edge_count": 99},
        ],
    }
    _sanitize_csg(csg, tmp_path, [])
    assert len(csg["cluster_edges"]) == 1
    assert csg["cluster_edges"][0]["edge_count"] == 3


def test_derive_domains_never_leaks_malicious_paths_after_sanitize(tmp_path):
    """End-to-end: the review's confirmed leak, through the actual
    _derive_domains derivation a real digest build uses."""
    from lib.context.repository_digest import _sanitize_csg, _derive_domains
    csg = {
        "nodes": [
            {"id": "s1", "file": "/Users/example/.ssh/id_rsa", "name": "leak1", "impact": {}},
            {"id": "s2", "file": "../../secret", "name": "leak2", "impact": {}},
            {"id": "s3", "file": "lib/real.py", "name": "real", "impact": {}},
        ],
        "clusters": [{"id": "c1", "symbols": ["s1", "s2", "s3"], "files": ["lib/real.py"]}],
        "cluster_edges": [],
    }
    _sanitize_csg(csg, tmp_path, [])
    domains = _derive_domains(csg, [])
    rendered = json.dumps(domains)
    assert "/Users/example/.ssh/id_rsa" not in rendered
    assert "../../secret" not in rendered
    assert "id_rsa" not in rendered


# ── Max-effort code review, P0/P1 crash-safety fixes ──────────────
# Each of these reproduces a crash the review confirmed by direct code
# inspection: a JSON key present with an explicit `null` value (not
# absent) defeats a `.get(key, default)` fallback, since the default
# only applies when the key itself is missing.


def test_sanitize_csg_normalizes_null_clusters_and_cluster_edges(tmp_path):
    """csg['clusters']/['cluster_edges'] present but JSON null (not
    absent) previously survived _sanitize_csg untouched — only the
    isinstance(x, list) branch ran — and crashed _derive_footprint's
    len(csg.get('clusters', [])) as len(None).
    """
    from lib.context.repository_digest import _sanitize_csg
    csg = {"nodes": [], "clusters": None, "cluster_edges": None, "edges": None}
    _sanitize_csg(csg, tmp_path, [])
    assert csg["clusters"] == []
    assert csg["cluster_edges"] == []
    assert csg["edges"] == []


def test_derive_footprint_does_not_crash_on_null_clusters():
    from lib.context.repository_digest import _derive_footprint, _sanitize_csg
    project_map = {"summary": {"total_files": 1, "total_lines": 10}, "files": []}
    csg = {"nodes": [], "clusters": None, "cluster_edges": None}
    _sanitize_csg(csg, Path("."), [])
    footprint = _derive_footprint(project_map, csg)  # must not raise
    assert footprint["domain_count"] == 0
    assert footprint["cross_domain_relationship_count"] == 0


def test_derive_domains_does_not_crash_on_null_impact():
    """A node with "impact": null (present, not absent) previously
    crashed the sort key with AttributeError: 'NoneType' object has no
    attribute 'get'.
    """
    from lib.context.repository_digest import _derive_domains
    csg = {
        "nodes": [{"id": "s1", "file": "a.py", "name": "Foo", "impact": None}],
        "clusters": [{"id": "c1", "symbols": ["s1"], "files": ["a.py"]}],
    }
    domains = _derive_domains(csg, [])  # must not raise
    assert len(domains) == 1


def test_derive_hotspots_does_not_crash_on_null_impact():
    from lib.context.repository_digest import _derive_hotspots
    csg = {"nodes": [{"id": "s1", "file": "a.py", "name": "Foo", "impact": None}]}
    hotspots = _derive_hotspots(csg, [], {})  # must not raise
    assert hotspots == []


def test_attach_changes_history_does_not_crash_on_malformed_previous_relationships(tmp_path):
    """The review's confirmed finding: a previous-snapshot digest whose
    'relationships' array contains a non-dict entry crashed dict(r)
    inside _remap, uncaught, in attach_changes_history — which is
    called from the *read* path (get_repository_digest), not just
    refresh, so simply viewing an existing digest could crash.
    """
    from lib.context.repository_digest import attach_changes_history, repository_digest_input_paths

    paths = repository_digest_input_paths(str(tmp_path))
    paths["digest_previous"].parent.mkdir(parents=True, exist_ok=True)
    previous = {
        "schema_version": 1, "domains": [], "relationships": ["not-an-object", 42],
        "commands": [], "entities": [], "readiness": [],
    }
    paths["digest_previous"].write_text(json.dumps(previous))

    current = {
        "schema_version": 1, "domains": [], "relationships": [],
        "commands": [], "entities": [], "readiness": [],
    }
    result = attach_changes_history(str(tmp_path), current)  # must not raise
    assert "_changes_history" in result


def test_annotate_domain_lanes_does_not_crash_on_domain_missing_id():
    from lib.context.repository_digest_architecture import annotate_domain_lanes
    domains = [{"lane": None}]  # no "id" key at all
    annotate_domain_lanes(domains, {"clusters": []})  # must not raise
    assert "lane" in domains[0]


def test_derive_annotated_tree_does_not_crash_on_missing_file_count():
    from lib.context.repository_digest_extras import derive_annotated_tree
    project_map = {
        "directories": [{"path": "lib"}],  # no "file_count" key at all
        "files": [{"path": "lib/a.py", "language": "python", "lines": 5, "category": "source"}],
    }
    tree = derive_annotated_tree(project_map, None, [])  # must not raise
    assert isinstance(tree, list)


def test_derive_relationships_falls_back_to_weight_when_edge_count_is_null():
    """edge.get("edge_count", fallback) only substitutes the fallback
    when the key is absent — an edge_count present but explicitly null
    (not just missing) must still fall back to "weight", not become a
    null weight in the persisted digest.
    """
    from lib.context.repository_digest import _derive_relationships
    csg = {"cluster_edges": [{"from": "c1", "to": "c2", "edge_count": None, "weight": 5}]}
    relationships = _derive_relationships(csg)
    assert relationships[0]["weight"] == 5


def test_derive_relationships_prefers_edge_count_when_present():
    from lib.context.repository_digest import _derive_relationships
    csg = {"cluster_edges": [{"from": "c1", "to": "c2", "edge_count": 3, "weight": 5}]}
    relationships = _derive_relationships(csg)
    assert relationships[0]["weight"] == 3


def test_evidence_paths_never_absolute_or_traversal(tmp_path):
    from lib.context.repository_digest import _relative
    root = tmp_path
    assert _relative("/etc/passwd", root) is None or not _relative("/etc/passwd", root).startswith("/")
    assert _relative("../../etc/passwd", root) is None
    assert _relative("lib/a.py", root) == "lib/a.py"


def test_supplemental_loader_rejects_credential_files(tmp_path):
    from lib.context.repository_digest import _safe_read_supplemental
    (tmp_path / ".env").write_text("SECRET=abc123")
    assert _safe_read_supplemental(tmp_path / ".env", tmp_path) is None
    (tmp_path / "id.pem").write_text("-----BEGIN-----")
    assert _safe_read_supplemental(tmp_path / "id.pem", tmp_path) is None


def test_supplemental_loader_rejects_symlink_escaping_root(tmp_path):
    from lib.context.repository_digest import _safe_read_supplemental
    outside = tmp_path.parent / f"outside-{tmp_path.name}.txt"
    outside.write_text("secret outside root")
    root = tmp_path / "project"
    root.mkdir()
    link = root / "escape.md"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks not supported in this environment")
    assert _safe_read_supplemental(link, root) is None
    outside.unlink(missing_ok=True)


def test_supplemental_loader_reads_normal_readme(tmp_path):
    from lib.context.repository_digest import _safe_read_supplemental
    (tmp_path / "README.md").write_text("# Hello\n\nA real project.")
    text = _safe_read_supplemental(tmp_path / "README.md", tmp_path)
    assert text is not None and "A real project" in text


# ── Canonical hashing / freshness ────────────────────────────────


def test_fingerprint_current_immediately_after_build(tmp_path):
    minimal_repo(tmp_path)
    digest = build_repository_digest(str(tmp_path), config={})
    freshness = compute_digest_freshness(str(tmp_path), digest, config={})
    assert freshness["state"] == "CURRENT"
    assert freshness["stale_reasons"] == []


def test_freshness_ignores_unrelated_config_changes(tmp_path):
    minimal_repo(tmp_path)
    digest = build_repository_digest(str(tmp_path), config={"agent": {"planning_model": "opus"}})
    freshness = compute_digest_freshness(
        str(tmp_path), digest, config={"agent": {"planning_model": "sonnet"}, "ui": {"theme": "colorblind"}}
    )
    assert freshness["state"] == "CURRENT"


def test_freshness_detects_project_map_change(tmp_path):
    minimal_repo(tmp_path)
    digest = build_repository_digest(str(tmp_path), config={})
    write_project_map(tmp_path, [{"path": "new.py", "language": "python", "lines": 1, "category": "source"}])
    freshness = compute_digest_freshness(str(tmp_path), digest, config={})
    assert freshness["state"] == "STALE"
    assert "project_map" in freshness["stale_reasons"]


def test_discovery_config_hash_excludes_agent_and_ui_settings():
    from lib.context.repository_digest_freshness import compute_discovery_config_sha256
    a = compute_discovery_config_sha256({"agent": {"planning_model": "opus"}, "ignore": ["node_modules"]})
    b = compute_discovery_config_sha256({"agent": {"planning_model": "sonnet"}, "ignore": ["node_modules"]})
    assert a == b


def test_discovery_config_hash_changes_with_ignore_patterns():
    from lib.context.repository_digest_freshness import compute_discovery_config_sha256
    a = compute_discovery_config_sha256({"ignore": ["node_modules"]})
    b = compute_discovery_config_sha256({"ignore": ["node_modules", "dist"]})
    assert a != b


# ── Atomic output ─────────────────────────────────────────────────


def test_atomic_write_leaves_no_temp_file_behind(tmp_path):
    minimal_repo(tmp_path)
    build_repository_digest(str(tmp_path), config={})
    ctx = tmp_path / ".speed" / "context"
    tmp_files = list(ctx.glob(".*.tmp-*"))
    assert tmp_files == []
    assert (ctx / "repository-digest.json").exists()


def test_load_repository_digest_returns_none_when_absent(tmp_path):
    minimal_repo(tmp_path)
    assert load_repository_digest(str(tmp_path)) is None


def test_load_repository_digest_roundtrips(tmp_path):
    minimal_repo(tmp_path)
    built = build_repository_digest(str(tmp_path), config={})
    loaded = load_repository_digest(str(tmp_path))
    assert loaded is not None
    assert loaded["schema_version"] == built["schema_version"]
    assert loaded["identity"]["name"] == built["identity"]["name"]


def test_load_repository_digest_returns_none_for_malformed_artifact(tmp_path):
    minimal_repo(tmp_path)
    build_repository_digest(str(tmp_path), config={})
    digest_path = repository_digest_input_paths(str(tmp_path))["digest"]
    digest_path.write_text("{not valid json")
    assert load_repository_digest(str(tmp_path)) is None


# ── Agent projection ──────────────────────────────────────────────


def test_agent_projection_never_exceeds_budget(tmp_path):
    write_project_map(tmp_path, [{"path": f"f{i}.py", "language": "python", "lines": 5, "category": "source"} for i in range(20)])
    nodes = [make_node(f"f{i}.py::x", file=f"f{i}.py", blast=i) for i in range(20)]
    clusters = [{"id": f"c{i}", "label": f"Domain{i}", "symbols": [f"f{i}.py::x"], "files": [f"f{i}.py"], "cohesion": 0.5} for i in range(20)]
    write_semantic_graph(tmp_path, nodes=nodes, clusters=clusters)
    digest = build_repository_digest(str(tmp_path), config={})

    from lib.context.utils import estimate_tokens_from_text
    for budget in (0, 1, 50, 500, 5000):
        projection = project_digest_for_agent(digest, token_budget=budget)
        assert estimate_tokens_from_text(projection) <= budget


def test_agent_projection_zero_budget_returns_short_truncation_notice(tmp_path):
    minimal_repo(tmp_path)
    digest = build_repository_digest(str(tmp_path), config={})
    projection = project_digest_for_agent(digest, token_budget=0)
    assert "truncated" in projection.lower() or len(projection) < 200


def test_agent_projection_prioritizes_identity_before_domains(tmp_path):
    write_project_map(tmp_path, [{"path": "a.py", "language": "python", "lines": 5, "category": "source"}])
    (tmp_path / "README.md").write_text("# Test\n\nThis is a test project for prioritization checks.")
    write_semantic_graph(
        tmp_path, nodes=[make_node("a.py::x")],
        clusters=[{"id": "c0", "label": "Core", "symbols": ["a.py::x"], "files": ["a.py"], "cohesion": 1.0}],
    )
    digest = build_repository_digest(str(tmp_path), config={})
    small = project_digest_for_agent(digest, token_budget=30)
    assert "test project" in small.lower() or "repository digest" in small.lower()


# ── Performance ────────────────────────────────────────────────────


def test_deterministic_generation_completes_quickly_on_this_repo():
    """Real project (this repo). Not the full 5,000-file/5s RFC benchmark
    fixture, but a real-scale smoke test that fails loudly if generation
    regresses to something pathological.
    """
    start = time.time()
    build_repository_digest(".", config={})
    elapsed = time.time() - start
    assert elapsed < 5.0


def test_deterministic_generation_completes_within_5s_for_5000_files(tmp_path):
    """The RFC's own literal benchmark target: <5s for <=5,000 indexed
    files, including a semantic graph sized to match. See Acceptance
    Criteria and Risks and Coverage > "Deterministic generation exceeds
    the 5-second/5,000-file performance target".
    """
    n = 5000
    files = [{"path": f"src/mod{i}/file{i}.py", "language": "python", "lines": 20, "category": "source"} for i in range(n)]
    write_project_map(tmp_path, files, by_language={"python": {"files": n, "lines": 20 * n}})

    nodes = [make_node(f"src/mod{i}/file{i}.py::fn{i}", file=f"src/mod{i}/file{i}.py", blast=i % 50, dependents=i % 10, centrality=(i % 100) / 100.0) for i in range(n)]
    clusters = [
        {"id": f"c{i}", "label": f"Domain{i}", "symbols": [f"src/mod{i}/file{i}.py::fn{i}"], "files": [f"src/mod{i}/file{i}.py"], "cohesion": 0.5}
        for i in range(n)
    ]
    write_semantic_graph(tmp_path, nodes=nodes, clusters=clusters)

    start = time.time()
    digest = build_repository_digest(str(tmp_path), config={})
    elapsed = time.time() - start

    assert digest["footprint"]["file_count"] == n
    assert elapsed < 5.0, f"generation took {elapsed:.2f}s for {n} files"


# ── Real git repositories (freshness against actual HEAD changes) ─


def _git(args: list[str], cwd: Path) -> None:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, env=env)


def _init_git_repo_with_commit(tmp_path: Path) -> str:
    """A real temporary git repository with one commit. Returns the HEAD sha.
    Test Plan: "Use temporary git repositories with explicit commits for
    freshness tests. No test may depend on the SPEED repository's current
    working tree."
    """
    _git(["init", "-q"], tmp_path)
    (tmp_path / ".gitignore").write_text(".speed/\n")
    _git(["add", "-A"], tmp_path)
    _git(["commit", "-q", "-m", "initial"], tmp_path)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True,
    ).stdout.strip()


@pytest.fixture(autouse=False)
def _skip_if_no_git():
    if subprocess.run(["git", "--version"], capture_output=True).returncode != 0:
        pytest.skip("git binary not available")


class TestRealGitRepositoryFreshness:
    def test_fingerprint_records_real_git_head(self, tmp_path, _skip_if_no_git):
        head = _init_git_repo_with_commit(tmp_path)
        minimal_repo(tmp_path)
        digest = build_repository_digest(str(tmp_path), config={})
        assert digest["fingerprint"]["git_head"] == head

    def test_new_commit_marks_digest_stale_with_git_head_reason(self, tmp_path, _skip_if_no_git):
        minimal_repo(tmp_path)
        _init_git_repo_with_commit(tmp_path)
        digest = build_repository_digest(str(tmp_path), config={})

        (tmp_path / "new_file.txt").write_text("more content")
        _git(["add", "-A"], tmp_path)
        _git(["commit", "-q", "-m", "second commit"], tmp_path)

        freshness = compute_digest_freshness(str(tmp_path), digest, config={})
        assert freshness["state"] == "STALE"
        assert "git_head" in freshness["stale_reasons"]

    def test_refresh_after_commit_returns_to_current_with_new_head(self, tmp_path, _skip_if_no_git):
        minimal_repo(tmp_path)
        _init_git_repo_with_commit(tmp_path)
        build_repository_digest(str(tmp_path), config={})

        (tmp_path / "another.txt").write_text("x")
        _git(["add", "-A"], tmp_path)
        _git(["commit", "-q", "-m", "third commit"], tmp_path)
        new_head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True,
        ).stdout.strip()

        digest = build_repository_digest(str(tmp_path), config={})
        freshness = compute_digest_freshness(str(tmp_path), digest, config={})
        assert freshness["state"] == "CURRENT"
        assert digest["fingerprint"]["git_head"] == new_head


# ── Cross-stage fingerprint recheck (mid-build input changes) ──────


def test_mid_build_project_map_change_writes_at_read_fingerprint_and_warns(tmp_path, monkeypatch):
    """Edge Cases: "Current git HEAD changes while generation is in
    progress... a mismatch writes the digest but immediately marks it
    stale." Simulated here via a project-map change between the builder's
    first (at-read) and second (at-write) fingerprint computation, since
    that's a cheaper, deterministic way to force the same code path a
    mid-build git-HEAD change would take.
    """
    minimal_repo(tmp_path)

    from lib.context import repository_digest as rd_mod

    original_compute_fingerprint = rd_mod.compute_fingerprint
    calls = {"n": 0}

    def _flaky_compute_fingerprint(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            # Simulate the project map changing between the read-time and
            # write-time fingerprint capture.
            write_project_map(tmp_path, [{"path": "changed.py", "language": "python", "lines": 1, "category": "source"}])
        return original_compute_fingerprint(*args, **kwargs)

    monkeypatch.setattr(rd_mod, "compute_fingerprint", _flaky_compute_fingerprint)
    digest = build_repository_digest(str(tmp_path), config={})

    assert any("changed while the digest was being generated" in w for w in digest["warnings"])
    # The persisted fingerprint must be immediately stale against current
    # state (the changed project map), not falsely CURRENT.
    freshness = compute_digest_freshness(str(tmp_path), digest, config={})
    assert freshness["state"] == "STALE"


# ── Domain reference validation ────────────────────────────────────


def test_dangling_domain_reference_is_dropped_with_warning(tmp_path):
    """Validation Rules > Domain references: "depends_on and used_by IDs
    must refer to stored domains; invalid references are dropped with a
    warning."
    """
    write_project_map(tmp_path, [{"path": "a.py", "language": "python", "lines": 5, "category": "source"}])
    write_semantic_graph(
        tmp_path,
        nodes=[make_node("a.py::x")],
        clusters=[{"id": "c0", "label": "Core", "symbols": ["a.py::x"], "files": ["a.py"], "cohesion": 1.0}],
        cluster_edges=[{"from": "c0", "to": "c-does-not-exist", "edge_count": 3}],
    )
    digest = build_repository_digest(str(tmp_path), config={})

    domain = digest["domains"][0]
    assert "c-does-not-exist" not in domain["depends_on"]
    assert any("c-does-not-exist" in w for w in digest["warnings"])


# ── Architecture: lane classification & relationship evidence ──────


def test_domain_gets_lane_from_full_cluster_file_list(tmp_path):
    """derive_domains only keeps 5 representative_files, but lane
    classification must consider every file in the cluster — a domain
    whose representative files are ambiguous but whose full file list has
    clear services-layer evidence must still classify as "services".
    """
    write_project_map(tmp_path, [
        {"path": "a/services/x.py", "language": "python", "lines": 5, "category": "source"},
        {"path": "a/services/y.py", "language": "python", "lines": 5, "category": "source"},
        {"path": "README.md", "language": None, "lines": 5, "category": "doc"},
    ])
    write_semantic_graph(
        tmp_path,
        nodes=[make_node("a/services/x.py::foo"), make_node("a/services/y.py::bar", file="a/services/y.py")],
        clusters=[{
            "id": "c0", "label": "Core", "symbols": ["a/services/x.py::foo", "a/services/y.py::bar"],
            "files": ["a/services/x.py", "a/services/y.py", "README.md"], "cohesion": 1.0,
        }],
    )
    digest = build_repository_digest(str(tmp_path), config={})
    assert digest["domains"][0]["lane"] == "services"


def test_domain_with_no_lane_evidence_is_other(tmp_path):
    write_project_map(tmp_path, [{"path": "README.md", "language": None, "lines": 5, "category": "doc"}])
    write_semantic_graph(
        tmp_path,
        nodes=[make_node("README.md::x")],
        clusters=[{"id": "c0", "label": "Docs", "symbols": ["README.md::x"], "files": ["README.md"], "cohesion": 1.0}],
    )
    digest = build_repository_digest(str(tmp_path), config={})
    assert digest["domains"][0]["lane"] == "other"


def test_relationship_carries_verified_evidence_and_sample_references(tmp_path):
    write_project_map(tmp_path, [
        {"path": "a/services/x.py", "language": "python", "lines": 5, "category": "source"},
        {"path": "a/models/y.py", "language": "python", "lines": 5, "category": "source"},
    ])
    write_semantic_graph(
        tmp_path,
        nodes=[make_node("a/services/x.py::foo"), make_node("a/models/y.py::bar", file="a/models/y.py")],
        clusters=[
            {"id": "c0", "label": "Services", "symbols": ["a/services/x.py::foo"], "files": ["a/services/x.py"], "cohesion": 1.0},
            {"id": "c1", "label": "Models", "symbols": ["a/models/y.py::bar"], "files": ["a/models/y.py"], "cohesion": 1.0},
        ],
        cluster_edges=[{
            "from": "c0", "to": "c1", "edge_count": 2,
            "symbols": [{"from": "a/services/x.py::foo", "to": "a/models/y.py::bar"}],
        }],
    )
    digest = build_repository_digest(str(tmp_path), config={})

    rel = digest["relationships"][0]
    assert rel["evidence_type"] == "verified"
    assert rel["sample_references"] == [{"from": "a/services/x.py::foo", "to": "a/models/y.py::bar"}]

    domains_by_id = {d["id"]: d for d in digest["domains"]}
    assert domains_by_id["c0"]["lane"] == "services"
    assert domains_by_id["c1"]["lane"] == "data"


# ── Auditability ────────────────────────────────────────────────────


class TestAuditabilityEvent:
    def test_successful_build_emits_generation_event(self, tmp_path, caplog):
        import logging
        minimal_repo(tmp_path)
        with caplog.at_level(logging.INFO, logger="speed.context.repository_digest"):
            build_repository_digest(str(tmp_path), config={}, narrative=False)

        events = [json.loads(r.message) for r in caplog.records if r.message.startswith("{")]
        assert len(events) == 1
        event = events[0]
        assert event["event"] == "repository_digest.generated"
        assert event["status"] in ("complete", "partial")
        assert "duration_seconds" in event
        assert event["narrative_requested"] is False
        assert "capabilities" in event and "project_map" in event["capabilities"]
        assert isinstance(event["warning_count"], int)
        # No source snippets, commands, or full evidence — just the
        # structural fields the RFC lists.
        assert "summary" not in event
        assert "commands" not in event

    def test_failed_build_emits_generation_event_with_failed_status(self, tmp_path, caplog):
        import logging
        with caplog.at_level(logging.INFO, logger="speed.context.repository_digest"):
            with pytest.raises(DigestInputError):
                build_repository_digest(str(tmp_path), config={})

        events = [json.loads(r.message) for r in caplog.records if r.message.startswith("{")]
        assert len(events) == 1
        assert events[0]["status"] == "failed"


# ── Manifests readiness reflects reality ───────────────────────────


def test_manifests_readiness_unavailable_when_none_present(tmp_path):
    minimal_repo(tmp_path)
    digest = build_repository_digest(str(tmp_path), config={})
    manifests = [r for r in digest["readiness"] if r["capability"] == "manifests"][0]
    assert manifests["status"] == "unavailable"


def test_manifests_readiness_available_when_package_json_present(tmp_path):
    minimal_repo(tmp_path)
    (tmp_path / "package.json").write_text(json.dumps({"name": "demo"}))
    # Manifests readiness reads project_map's file inventory, the same way
    # every other readiness capability does — not a live filesystem
    # re-scan — so the fixture's project map must know about the manifest
    # too, exactly as Layer 1 discovery would in a real build.
    write_project_map(tmp_path, [
        {"path": "f0.py", "language": "python", "lines": 10, "category": "source"},
        {"path": "f1.py", "language": "python", "lines": 10, "category": "source"},
        {"path": "package.json", "language": "json", "lines": 1, "category": "config"},
    ], by_language={"python": {"files": 2, "lines": 20}})
    digest = build_repository_digest(str(tmp_path), config={})
    manifests = [r for r in digest["readiness"] if r["capability"] == "manifests"][0]
    assert manifests["status"] == "available"


def test_manifests_readiness_available_for_nested_package_json(tmp_path):
    """The bug this guards against: a repository whose only manifest lives
    in a nested directory (e.g. a frontend under dashboard/) must not read
    as 'no manifests' just because there's nothing at the repository root.
    """
    nested = tmp_path / "dashboard" / "frontend"
    nested.mkdir(parents=True)
    (nested / "package.json").write_text(json.dumps({"name": "frontend"}))
    write_project_map(tmp_path, [
        {"path": "f0.py", "language": "python", "lines": 10, "category": "source"},
        {"path": "dashboard/frontend/package.json", "language": "json", "lines": 1, "category": "config"},
    ], by_language={"python": {"files": 1, "lines": 10}})
    digest = build_repository_digest(str(tmp_path), config={})
    manifests = [r for r in digest["readiness"] if r["capability"] == "manifests"][0]
    assert manifests["status"] == "available"


def test_manifests_readiness_available_for_maven_pom_xml(tmp_path):
    """PetClinic (Maven, root pom.xml, no package.json/pyproject.toml/
    Cargo.toml) reported 'manifests: unavailable' despite Java being a
    supported language elsewhere in SPEED."""
    minimal_repo(tmp_path)
    (tmp_path / "pom.xml").write_text("<project></project>")
    write_project_map(tmp_path, [
        {"path": "f0.py", "language": "python", "lines": 10, "category": "source"},
        {"path": "f1.py", "language": "python", "lines": 10, "category": "source"},
        {"path": "pom.xml", "language": "xml", "lines": 1, "category": "config"},
    ], by_language={"python": {"files": 2, "lines": 20}})
    digest = build_repository_digest(str(tmp_path), config={})
    manifests = [r for r in digest["readiness"] if r["capability"] == "manifests"][0]
    assert manifests["status"] == "available"


def test_manifests_readiness_available_for_gradle_build_file(tmp_path):
    minimal_repo(tmp_path)
    write_project_map(tmp_path, [
        {"path": "f0.py", "language": "python", "lines": 10, "category": "source"},
        {"path": "f1.py", "language": "python", "lines": 10, "category": "source"},
        {"path": "build.gradle.kts", "language": "kotlin", "lines": 1, "category": "config"},
    ], by_language={"python": {"files": 2, "lines": 20}})
    digest = build_repository_digest(str(tmp_path), config={})
    manifests = [r for r in digest["readiness"] if r["capability"] == "manifests"][0]
    assert manifests["status"] == "available"


# ── Repository identity: manifest-description fallback + name conflicts ──


def test_purpose_falls_back_to_manifest_description(tmp_path):
    minimal_repo(tmp_path)
    (tmp_path / "package.json").write_text(json.dumps({"name": "demo", "description": "A demo service for testing purpose fallback."}))
    digest = build_repository_digest(str(tmp_path), config={})
    assert "demo service" in digest["identity"]["summary"].lower()
    assert digest["identity"]["evidence"][0]["source"] == "manifest"


def test_conflicting_manifest_names_produce_a_warning(tmp_path):
    minimal_repo(tmp_path)
    (tmp_path / "package.json").write_text(json.dumps({"name": "name-from-package-json"}))
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "name-from-pyproject"\n')
    digest = build_repository_digest(str(tmp_path), config={})
    assert digest["identity"]["name"] == "name-from-package-json"  # priority order preserved
    assert any("multiple manifests declare different project names" in w for w in digest["warnings"])


# ── Total supplemental byte cap ─────────────────────────────────────


def test_supplemental_total_byte_cap_stops_further_reads(tmp_path):
    """Security & Controls > Content handling: "total supplemental text to
    2 MiB before normalization." Exercised directly against the budget
    helper rather than by writing a real 2 MiB fixture file.
    """
    from lib.context.repository_digest import _SupplementalBudget

    budget = _SupplementalBudget(total_max_bytes=100)
    assert budget.charge(60) is True
    assert budget.charge(60) is False  # would exceed the cap
    assert budget.remaining <= 40


# ── Evidence locator / confidence normalization on load ────────────


def test_validate_digest_flags_evidence_with_no_locator():
    digest = dict(empty_digest_body())
    digest.update({
        "schema_version": 1, "status": "partial", "generated_at": "2026-01-01T00:00:00Z",
        "generator": {"name": "x", "version": "1"}, "fingerprint": {},
        "identity": {"name": "x", "summary": "", "confidence": "unknown", "evidence": []},
        "footprint": {"file_count": 0, "line_count": 0},
    })
    digest["domains"] = [{
        "id": "c0", "label": "X", "summary": "", "confidence": "derived",
        "file_count": 1, "symbol_count": 1,
        "evidence": [{"source": "semantic_graph", "path": None, "line": None, "symbol": None, "artifact_key": None, "description": "no locator"}],
    }]
    issues = validate_digest(digest)
    assert any("no path, symbol, or artifact_key" in i for i in issues)


def test_load_repository_digest_with_status_normalizes_bad_confidence(tmp_path):
    minimal_repo(tmp_path)
    build_repository_digest(str(tmp_path), config={})
    paths = repository_digest_input_paths(str(tmp_path))
    data = json.loads(paths["digest"].read_text())
    data["identity"]["confidence"] = "extremely-sure"  # not a real value
    paths["digest"].write_text(json.dumps(data))

    status, digest, reason = load_repository_digest_with_status(str(tmp_path))
    assert status == "ok"
    assert digest["identity"]["confidence"] == "unknown"
    assert any("normalized to 'unknown'" in w for w in digest["warnings"])


# ── Malformed vs. missing distinction ───────────────────────────────


class TestLoadRepositoryDigestWithStatus:
    def test_missing_when_no_file(self, tmp_path):
        status, digest, reason = load_repository_digest_with_status(str(tmp_path))
        assert (status, digest, reason) == ("missing", None, None)

    def test_malformed_when_not_json(self, tmp_path):
        paths = repository_digest_input_paths(str(tmp_path))
        paths["digest"].parent.mkdir(parents=True, exist_ok=True)
        paths["digest"].write_text("{not valid json")
        status, digest, reason = load_repository_digest_with_status(str(tmp_path))
        assert status == "malformed"
        assert digest is None
        assert reason is not None

    def test_malformed_when_unsupported_schema_version(self, tmp_path):
        minimal_repo(tmp_path)
        build_repository_digest(str(tmp_path), config={})
        paths = repository_digest_input_paths(str(tmp_path))
        data = json.loads(paths["digest"].read_text())
        data["schema_version"] = 999
        paths["digest"].write_text(json.dumps(data))

        status, digest, reason = load_repository_digest_with_status(str(tmp_path))
        assert status == "malformed"
        assert "schema_version" in reason

    def test_ok_for_a_real_digest(self, tmp_path):
        minimal_repo(tmp_path)
        build_repository_digest(str(tmp_path), config={})
        status, digest, reason = load_repository_digest_with_status(str(tmp_path))
        assert status == "ok"
        assert digest is not None
        assert reason is None


# ── command_discovery: workspaces, Cargo.toml, CI corroboration ────


class TestCommandDiscoveryExtensions:
    def test_workspace_member_scripts_retain_their_own_working_directory(self, tmp_path):
        (tmp_path / "package.json").write_text(json.dumps({"name": "root", "workspaces": ["packages/*"]}))
        pkg_dir = tmp_path / "packages" / "api"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "package.json").write_text(json.dumps({"name": "api", "scripts": {"test": "vitest run"}}))

        commands = command_discovery.discover_commands(tmp_path)
        api_test = [c for c in commands if c["command"] == "npm run test" and c["working_directory"] == "packages/api"]
        assert len(api_test) == 1
        assert api_test[0]["purpose"] == "test"

    def test_root_and_workspace_same_script_name_different_directories(self, tmp_path):
        (tmp_path / "package.json").write_text(json.dumps({"name": "root", "scripts": {"test": "jest"}, "workspaces": ["packages/*"]}))
        pkg_dir = tmp_path / "packages" / "web"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "package.json").write_text(json.dumps({"name": "web", "scripts": {"test": "vitest run"}}))

        commands = command_discovery.discover_commands(tmp_path)
        dirs = {c["working_directory"] for c in commands if c["purpose"] == "test"}
        assert dirs == {".", "packages/web"}

    def test_cargo_toml_never_synthesizes_a_command(self, tmp_path):
        (tmp_path / "Cargo.toml").write_text('[package]\nname = "demo"\nversion = "0.1.0"\n')
        assert command_discovery.discover_from_cargo_toml(tmp_path) == []
        # And it doesn't leak into the merged registry either.
        commands = command_discovery.discover_commands(tmp_path)
        assert not any("cargo" in c["command"].lower() for c in commands)

    def test_ci_workflow_command_corroborates_existing_command(self, tmp_path):
        (tmp_path / "package.json").write_text(json.dumps({"name": "root", "scripts": {"test": "vitest run"}}))
        workflows = tmp_path / ".github" / "workflows"
        workflows.mkdir(parents=True)
        (workflows / "ci.yml").write_text(
            "jobs:\n  test:\n    steps:\n      - run: npm run test\n"
        )
        commands = command_discovery.discover_commands(tmp_path)
        match = [c for c in commands if c["command"] == "npm run test"]
        assert len(match) == 1
        sources = {ev["source"] for ev in match[0]["evidence"]}
        assert "manifest" in sources
        assert len(match[0]["evidence"]) >= 2  # package.json evidence + CI corroboration

    def test_ci_only_command_is_not_promoted_alone(self, tmp_path):
        workflows = tmp_path / ".github" / "workflows"
        workflows.mkdir(parents=True)
        (workflows / "ci.yml").write_text(
            "jobs:\n  deploy:\n    steps:\n      - run: ./deploy-with-ci-only-secrets.sh\n"
        )
        commands = command_discovery.discover_commands(tmp_path)
        assert not any("deploy-with-ci-only-secrets" in c["command"] for c in commands)

    def test_nested_package_json_discovered_via_project_map_without_root_manifest(self, tmp_path):
        """A repository with no root package.json at all (e.g. a Python
        project with a nested frontend) must still discover that nested
        manifest's scripts — driven by project_map, not a root-only check.
        """
        frontend = tmp_path / "dashboard" / "frontend"
        frontend.mkdir(parents=True)
        (frontend / "package.json").write_text(
            json.dumps({"name": "frontend", "scripts": {"dev": "next dev", "build": "next build"}})
        )
        project_map = {"files": [{"path": "dashboard/frontend/package.json"}]}

        commands = command_discovery.discover_commands(tmp_path, project_map)
        dev = [c for c in commands if c["command"] == "npm run dev"]
        assert len(dev) == 1
        assert dev[0]["working_directory"] == "dashboard/frontend"
        assert dev[0]["purpose"] == "develop"
        build = [c for c in commands if c["command"] == "npm run build"]
        assert len(build) == 1
        assert build[0]["working_directory"] == "dashboard/frontend"

    def test_discover_commands_without_project_map_ignores_nested_manifests(self, tmp_path):
        """Backward compatibility: callers that don't pass project_map keep
        the old root-only behavior — no surprise filesystem scan for
        nested manifests they never asked to be found.
        """
        frontend = tmp_path / "dashboard" / "frontend"
        frontend.mkdir(parents=True)
        (frontend / "package.json").write_text(json.dumps({"name": "frontend", "scripts": {"dev": "next dev"}}))

        commands = command_discovery.discover_commands(tmp_path)
        assert commands == []

    def test_nested_manifest_does_not_shadow_root_workspace_discovery(self, tmp_path):
        """A root package.json with declared workspaces still discovers its
        members the existing way — project_map-driven discovery only adds
        manifests not already covered by that walk, never duplicates them.
        """
        (tmp_path / "package.json").write_text(json.dumps({"name": "root", "workspaces": ["packages/*"]}))
        pkg_dir = tmp_path / "packages" / "api"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "package.json").write_text(json.dumps({"name": "api", "scripts": {"test": "vitest run"}}))
        project_map = {"files": [{"path": "package.json"}, {"path": "packages/api/package.json"}]}

        commands = command_discovery.discover_commands(tmp_path, project_map)
        api_test = [c for c in commands if c["command"] == "npm run test" and c["working_directory"] == "packages/api"]
        assert len(api_test) == 1


class TestCommandDiscoverySafeReading:
    """Every command source now reads through repository_digest_schema's
    safe_read_text (root containment, symlink resolution, size cap,
    credential denylist) instead of a raw path.read_text() — see the
    review finding "Command loaders can read outside-root symlink
    targets." These lock in that a source outside the project root,
    reached either directly or via a symlink, is never read.
    """

    def test_claude_md_outside_root_via_symlink_is_not_read(self, tmp_path):
        outside = tmp_path.parent / f"outside-claude-{tmp_path.name}.md"
        outside.write_text("## Test\n```\nsecret-leaked-command\n```\n")
        root = tmp_path / "project"
        root.mkdir()
        try:
            (root / "CLAUDE.md").symlink_to(outside)
        except OSError:
            pytest.skip("symlinks not supported in this environment")
        try:
            commands = command_discovery.discover_from_project_instructions(root)
            assert not any("secret-leaked-command" in c["command"] for c in commands)
        finally:
            outside.unlink(missing_ok=True)

    def test_nested_package_json_via_project_map_symlink_escape_is_not_read(self, tmp_path):
        """The exact scenario the review is about: a nested manifest path
        discovered via project_map (not a hardcoded root-level filename)
        turning out to be a symlink pointing outside the project root.
        """
        outside = tmp_path.parent / f"outside-pkg-{tmp_path.name}.json"
        outside.write_text(json.dumps({"scripts": {"dev": "leak-outside-root"}}))
        root = tmp_path / "project"
        (root / "frontend").mkdir(parents=True)
        try:
            (root / "frontend" / "package.json").symlink_to(outside)
        except OSError:
            pytest.skip("symlinks not supported in this environment")
        try:
            project_map = {"files": [{"path": "frontend/package.json"}]}
            commands = command_discovery.discover_commands(root, project_map)
            assert not any("leak-outside-root" in c["command"] for c in commands)
        finally:
            outside.unlink(missing_ok=True)

    def test_makefile_outside_root_via_symlink_is_not_read(self, tmp_path):
        outside = tmp_path.parent / f"outside-makefile-{tmp_path.name}"
        outside.write_text("leak-target:\n\techo leaked\n")
        root = tmp_path / "project"
        root.mkdir()
        try:
            (root / "Makefile").symlink_to(outside)
        except OSError:
            pytest.skip("symlinks not supported in this environment")
        try:
            commands = command_discovery.discover_from_makefile(root)
            assert not any("leak-target" in c["command"] for c in commands)
        finally:
            outside.unlink(missing_ok=True)

    def test_ci_workflow_outside_root_via_symlink_is_not_read(self, tmp_path):
        outside = tmp_path.parent / f"outside-ci-{tmp_path.name}.yml"
        outside.write_text("jobs:\n  test:\n    steps:\n      - run: leak-ci-command\n")
        root = tmp_path / "project"
        (root / ".github" / "workflows").mkdir(parents=True)
        try:
            (root / ".github" / "workflows" / "ci.yml").symlink_to(outside)
        except OSError:
            pytest.skip("symlinks not supported in this environment")
        try:
            found = command_discovery.discover_from_ci_workflows(root)
            assert not any("leak-ci-command" in r["command"] for r in found)
        finally:
            outside.unlink(missing_ok=True)

    def test_package_json_over_size_cap_is_truncated_not_crashed(self, tmp_path):
        huge_scripts = {f"script{i}": f"echo {i}" for i in range(20000)}
        (tmp_path / "package.json").write_text(json.dumps({"scripts": huge_scripts}))
        assert (tmp_path / "package.json").stat().st_size > 256 * 1024
        # Truncated JSON fails to parse — this must degrade to "no scripts
        # found," never raise.
        commands = command_discovery.discover_from_package_json(tmp_path)
        assert isinstance(commands, list)


# ── Code-review fixes ────────────────────────────────────────────


def test_agent_projection_shows_freshness_line_via_attach_effective_state(tmp_path):
    """Code review: project_digest_for_agent() used to read a key
    (_freshness_state) nothing ever wrote, so the Freshness line never
    rendered. attach_effective_state() is the fix both real callers
    (dashboard resolver, speed digest CLI) now use.
    """
    minimal_repo(tmp_path)
    digest = build_repository_digest(str(tmp_path), config={})
    digest = attach_effective_state(str(tmp_path), digest, config={})
    assert digest["_effective_state"] == "CURRENT"

    projection = project_digest_for_agent(digest, token_budget=2000)
    assert "**Freshness:** CURRENT" in projection


def test_project_knowledge_readiness_has_exactly_one_record_with_drafts(tmp_path):
    """Code review: a pending draft used to append a *second*
    'project_knowledge' readiness record instead of updating the one
    record the Data Model requires per capability.
    """
    minimal_repo(tmp_path)
    memory_dir = tmp_path / ".speed" / "memory"
    memory_dir.mkdir(parents=True)
    (memory_dir / "project-knowledge.json").write_text(json.dumps({"entries": []}))
    (memory_dir / "project-knowledge-drafts.json").write_text(
        json.dumps([{"id": "d1"}, {"id": "d2"}])
    )

    digest = build_repository_digest(str(tmp_path), config={})
    pk_records = [r for r in digest["readiness"] if r["capability"] == "project_knowledge"]
    assert len(pk_records) == 1
    assert pk_records[0]["status"] == "partial"
    assert "2 draft entries" in pk_records[0]["reason"]


def test_project_knowledge_readiness_single_record_without_drafts(tmp_path):
    minimal_repo(tmp_path)
    memory_dir = tmp_path / ".speed" / "memory"
    memory_dir.mkdir(parents=True)
    (memory_dir / "project-knowledge.json").write_text(json.dumps({"entries": []}))

    digest = build_repository_digest(str(tmp_path), config={})
    pk_records = [r for r in digest["readiness"] if r["capability"] == "project_knowledge"]
    assert len(pk_records) == 1
    assert pk_records[0]["status"] == "available"


def test_validate_digest_flags_risk_with_no_evidence():
    digest = dict(empty_digest_body())
    digest.update({
        "schema_version": 1, "status": "partial", "generated_at": "2026-01-01T00:00:00Z",
        "generator": {"name": "x", "version": "1"}, "fingerprint": {},
        "identity": {"name": "x", "summary": "", "confidence": "unknown", "evidence": []},
        "footprint": {"file_count": 0, "line_count": 0},
    })
    digest["risks"] = [{"type": "high_blast_radius", "description": "no evidence attached", "evidence": []}]
    issues = validate_digest(digest)
    assert any("high_blast_radius" in i and "no evidence" in i for i in issues)


def test_conflicting_discovery_risk_has_a_valid_evidence_locator(tmp_path):
    """Code review: the conflicting_discovery risk shipped with a
    locator-less evidence entry, which validate_digest() didn't catch
    because it never checked risk evidence at all.
    """
    (tmp_path / "package.json").write_text(json.dumps({"name": "x", "scripts": {"test": "vitest run"}}))
    (tmp_path / "CLAUDE.md").write_text("## Test\n\n```bash\nnpm test\n```\n")
    minimal_repo(tmp_path)
    digest = build_repository_digest(str(tmp_path), config={})

    conflicts = [r for r in digest["risks"] if r["type"] == "conflicting_discovery"]
    assert conflicts, "expected a conflicting_discovery risk from mismatched test commands"
    for r in conflicts:
        assert r["evidence"], "conflicting_discovery risk must carry evidence"
        for ev in r["evidence"]:
            assert ev["path"] or ev["symbol"] or ev["artifact_key"], "evidence has no locator"
    # And validate_digest (called by build_repository_digest itself) didn't reject it.
    assert digest["status"] in ("complete", "partial")


def test_readme_multiline_paragraph_gets_correct_evidence_line_number(tmp_path):
    """Code review: joining a multi-line paragraph with spaces before
    searching for it in the original text meant `para in text` was always
    False for a wrapped paragraph, silently defaulting line_no to 1.
    """
    minimal_repo(tmp_path)
    (tmp_path / "README.md").write_text(
        "# Demo\n\n"
        "Acme is a multi-tenant\ncommerce platform for testing line numbers.\n"
    )
    digest = build_repository_digest(str(tmp_path), config={})
    assert digest["identity"]["evidence"][0]["line"] == 3


def test_badge_regex_does_not_skip_a_real_status_sentence(tmp_path):
    """Code review: _BADGE_LINE_RE matched any line starting with the bare
    word 'status', so a real descriptive sentence beginning with 'Status:'
    was wrongly treated as a badge and skipped.
    """
    minimal_repo(tmp_path)
    (tmp_path / "README.md").write_text(
        "# Demo\n\nStatus: production-ready, actively maintained by the SPEED team.\n"
    )
    digest = build_repository_digest(str(tmp_path), config={})
    assert "production-ready" in digest["identity"]["summary"]


def test_badge_regex_still_skips_a_short_status_label(tmp_path):
    """A genuine short badge/status label line is still skipped."""
    minimal_repo(tmp_path)
    (tmp_path / "README.md").write_text(
        "# Demo\n\nStatus: passing\n\nThe real purpose statement goes here for testing.\n"
    )
    digest = build_repository_digest(str(tmp_path), config={})
    assert "passing" not in digest["identity"]["summary"]
    assert "real purpose statement" in digest["identity"]["summary"]


def test_command_fence_accepts_non_allowlisted_language_tag(tmp_path):
    """Code review: _FENCE_RE only recognized a fixed set of fence
    languages, silently missing commands under e.g. a ```zsh fence.
    """
    (tmp_path / "CLAUDE.md").write_text("## Test\n\n```zsh\nnpm test\n```\n")
    commands = command_discovery.discover_from_project_instructions(tmp_path)
    assert any(c["command"] == "npm test" for c in commands)


def test_symbol_to_domain_computed_once_and_shared(tmp_path):
    """Code review: _derive_hotspots and _derive_risks each rebuilt an
    identical symbol_to_domain map from the same csg. Confirms the shared
    _build_symbol_to_domain() helper produces correct domain_id/cross-domain
    results for both consumers from one computation.
    """
    from lib.context.repository_digest import _build_symbol_to_domain

    write_project_map(tmp_path, [{"path": "a.py", "language": "python", "lines": 5, "category": "source"}])
    write_semantic_graph(
        tmp_path,
        nodes=[make_node("a.py::x", blast=100, dependents=20)],
        clusters=[{"id": "c0", "label": "Core", "symbols": ["a.py::x"], "files": ["a.py"], "cohesion": 1.0}],
    )
    digest = build_repository_digest(str(tmp_path), config={})
    assert digest["hotspots"][0]["domain_id"] == "c0"

    csg = {"clusters": [{"id": "c0", "symbols": ["a.py::x"]}]}
    assert _build_symbol_to_domain(csg) == {"a.py::x": "c0"}


def test_risk_domain_id_uses_full_cluster_membership_not_representative_files(tmp_path):
    """Architecture screen accuracy: the frontend's risk-to-domain
    association used to scan a risk's evidence path against
    domain.representativeFiles, which MAX_REPRESENTATIVE_FILES caps at 5
    — a risk symbol that isn't one of a domain's top-5-by-centrality
    files (the common case for a domain with several files) was silently
    invisible on the Architecture screen. domain_id is now computed here
    from the same full-membership symbol_to_domain map _derive_hotspots
    already uses, so it's correct regardless of which files happen to be
    chosen as "representative."

    Uses a cross_domain_hub risk (unlike high_blast_radius, its trigger —
    edges touching >=3 domains — is independent of the centrality/
    blast_radius ranking representative_files itself is sorted by, so a
    hub symbol can realistically rank outside the top 5 while still
    carrying a real risk).
    """
    files = [{"path": f"pkg/f{i}.py", "language": "python", "lines": 5, "category": "source"} for i in range(6)]
    write_project_map(tmp_path, files)
    # f0-f4 outrank f5 on centrality, so they fill representative_files'
    # 5 slots; the hub symbol's file (f5) is guaranteed excluded.
    c0_nodes = [make_node(f"pkg/f{i}.py::sym{i}", file=f"pkg/f{i}.py", centrality=0.9 - i * 0.1) for i in range(5)]
    hub_node = make_node("pkg/f5.py::hub", file="pkg/f5.py", centrality=0.0)
    other_nodes = [make_node(f"other{i}.py::x", file=f"other{i}.py") for i in range(3)]
    write_semantic_graph(
        tmp_path,
        nodes=c0_nodes + [hub_node] + other_nodes,
        edges=[{"from": "pkg/f5.py::hub", "to": n["id"], "type": "calls"} for n in other_nodes],
        clusters=[
            {"id": "c0", "label": "core", "symbols": [n["id"] for n in c0_nodes] + ["pkg/f5.py::hub"], "files": [f["path"] for f in files], "cohesion": 1.0},
            {"id": "c1", "label": "one", "symbols": ["other0.py::x"], "files": ["other0.py"], "cohesion": 1.0},
            {"id": "c2", "label": "two", "symbols": ["other1.py::x"], "files": ["other1.py"], "cohesion": 1.0},
            {"id": "c3", "label": "three", "symbols": ["other2.py::x"], "files": ["other2.py"], "cohesion": 1.0},
        ],
    )
    digest = build_repository_digest(str(tmp_path), config={})

    domain = next(d for d in digest["domains"] if d["id"] == "c0")
    assert "pkg/f5.py" not in domain["representative_files"]

    risk = next(r for r in digest["risks"] if r["type"] == "cross_domain_hub")
    assert risk["domain_id"] == "c0"


# ═════════════════════════════════════════════════════════════════
# Phase 2: coverage, entrypoints, reading path, team knowledge
# ═════════════════════════════════════════════════════════════════


def test_coverage_stats_populated_from_build_summary(tmp_path):
    minimal_repo(tmp_path)
    ctx = tmp_path / ".speed" / "context"
    ctx.mkdir(parents=True, exist_ok=True)
    (ctx / "build-summary.json").write_text(json.dumps({
        "extraction_stats": {"files_parsed": 8, "source_files_total": 10, "total_definitions": 40, "total_references": 90},
    }))
    digest = build_repository_digest(str(tmp_path), config={})
    stats = digest["coverage_stats"]
    assert stats is not None
    assert stats["source_files_total"] == 10
    assert stats["source_files_parsed"] == 8
    assert stats["parse_coverage_pct"] == 80.0


def test_coverage_stats_absent_without_build_summary(tmp_path):
    minimal_repo(tmp_path)
    digest = build_repository_digest(str(tmp_path), config={})
    assert digest["coverage_stats"] is None


def test_coverage_stats_absent_for_old_build_summary_shape(tmp_path):
    """A build-summary.json written before source_files_total existed
    must not be misinterpreted — coverage_stats stays None, not a wrong
    percentage computed against the wrong denominator.
    """
    minimal_repo(tmp_path)
    ctx = tmp_path / ".speed" / "context"
    ctx.mkdir(parents=True, exist_ok=True)
    (ctx / "build-summary.json").write_text(json.dumps({
        "extraction_stats": {"files_parsed": 8, "total_definitions": 40, "total_references": 90},
    }))
    digest = build_repository_digest(str(tmp_path), config={})
    assert digest["coverage_stats"] is None


def test_entrypoints_populated_from_discovered_run_command(tmp_path):
    # write_project_map, not minimal_repo — the entrypoint has to actually
    # be listed in project-map.json's files, same as derive_entrypoints
    # requires of any real digest build.
    write_project_map(tmp_path, [{"path": "app.py", "language": "python", "lines": 5, "category": "source"}])
    (tmp_path / "app.py").write_text("print('hi')\n")
    (tmp_path / "CLAUDE.md").write_text("## Run\n\n```bash\npython app.py\n```\n")
    digest = build_repository_digest(str(tmp_path), config={})
    assert any(e["file"] == "app.py" and e["kind"] == "run" for e in digest["entrypoints"])


def test_entrypoints_empty_when_no_run_command_names_a_real_file(tmp_path):
    minimal_repo(tmp_path)
    digest = build_repository_digest(str(tmp_path), config={})
    assert digest["entrypoints"] == []


def test_reading_path_and_annotated_tree_present_for_a_normal_repo(tmp_path):
    minimal_repo(tmp_path)
    (tmp_path / "README.md").write_text("# Demo\n\nA real project used to test the reading path.\n")
    digest = build_repository_digest(str(tmp_path), config={})
    assert digest["reading_path"]
    assert digest["reading_path"][0]["file"] == "README.md"
    assert digest["annotated_tree"] == [] or all("path" in d for d in digest["annotated_tree"])


def test_approved_and_pending_knowledge_exposed(tmp_path):
    minimal_repo(tmp_path)
    memory = tmp_path / ".speed" / "memory"
    memory.mkdir(parents=True)
    (memory / "project-knowledge.json").write_text(json.dumps({
        "entries": [{"id": "pk-1", "knowledge": "Use profile X", "why_it_matters": "reason", "applies_to": ["lib/"], "last_verified": "2026-01-01", "staleness_flag": ""}],
    }))
    (memory / "project-knowledge-drafts.json").write_text(json.dumps([
        {"id": "pk-draft-1", "knowledge": "Draft Q", "why_it_matters": "reason", "applies_to": ["lib/"], "source": "seeded", "draft_reason": "seeded from comment"},
    ]))
    digest = build_repository_digest(str(tmp_path), config={})
    assert digest["approved_knowledge"] == [{"id": "pk-1", "knowledge": "Use profile X", "why_it_matters": "reason", "applies_to": ["lib/"], "last_verified": "2026-01-01", "staleness_flag": ""}]
    assert digest["pending_knowledge"] == [{"id": "pk-draft-1", "knowledge": "Draft Q", "why_it_matters": "reason", "applies_to": ["lib/"], "source": "seeded", "draft_reason": "seeded from comment"}]


def test_missing_knowledge_artifacts_produce_empty_lists_not_crash(tmp_path):
    minimal_repo(tmp_path)
    digest = build_repository_digest(str(tmp_path), config={})
    assert digest["approved_knowledge"] == []
    assert digest["pending_knowledge"] == []


def test_malformed_knowledge_artifacts_do_not_crash_the_build(tmp_path):
    minimal_repo(tmp_path)
    memory = tmp_path / ".speed" / "memory"
    memory.mkdir(parents=True)
    (memory / "project-knowledge.json").write_text("{not valid json")
    (memory / "project-knowledge-drafts.json").write_text("{not valid json")
    digest = build_repository_digest(str(tmp_path), config={})
    assert digest["approved_knowledge"] == []
    assert digest["pending_knowledge"] == []


def test_build_never_mutates_knowledge_artifacts(tmp_path):
    """This phase is read-only against .speed/memory/* — the digest
    builder must never write back to drafts/knowledge, unlike
    lib/learn's own detect_knowledge_gaps(), which does.
    """
    minimal_repo(tmp_path)
    memory = tmp_path / ".speed" / "memory"
    memory.mkdir(parents=True)
    drafts_path = memory / "project-knowledge-drafts.json"
    original_content = json.dumps([{"id": "pk-draft-1", "knowledge": "Q", "why_it_matters": "w", "applies_to": [], "source": "seeded", "draft_reason": "r"}])
    drafts_path.write_text(original_content)
    knowledge_path = memory / "project-knowledge.json"
    knowledge_path.write_text(json.dumps({"entries": []}))

    build_repository_digest(str(tmp_path), config={})

    assert drafts_path.read_text() == original_content
    assert knowledge_path.read_text() == json.dumps({"entries": []})


_PHASE2_KEYS = ("coverage_stats", "annotated_tree", "reading_path", "approved_knowledge", "pending_knowledge")
_PHASE4_KEYS = ("api_data", "cicd", "runtime_config")
_SECURITY_KEYS = ("security",)
# entrypoints is deliberately NOT in _PHASE2_KEYS — it predates Phase 2
# (always present, just always empty before now), so popping it wouldn't
# correctly simulate a pre-Phase-2 digest and would only prove something
# already true.


def _assert_phase2_defaults(result):
    assert result.coverage_stats is None
    assert result.entrypoints(limit=10) == []
    assert result.reading_path() == []
    assert result.approved_knowledge() == []
    assert result.pending_knowledge() == []


def _assert_phase4_defaults(result):
    assert result.api_data is None or (result.api_data.routes() == [] and result.api_data.entities() == [])
    assert result.cicd is None or result.cicd.workflows() == []
    assert result.runtime_config is None or result.runtime_config.runtimes() == []


def _assert_security_defaults(result):
    assert result.security is None


@pytest.mark.parametrize(
    "keys",
    [pytest.param(_PHASE2_KEYS, id="phase2"), pytest.param(_PHASE4_KEYS, id="phase4"), pytest.param(_SECURITY_KEYS, id="security")],
)
def test_old_digest_missing_fields_still_loads_ok(tmp_path, keys):
    """Backward compatibility: a repository-digest.json written before a
    given phase existed is missing that phase's top-level keys entirely.
    It must still load as 'ok', not 'malformed' — validate_digest() must
    never require them.
    """
    minimal_repo(tmp_path)
    paths = repository_digest_input_paths(str(tmp_path))
    old_digest = build_repository_digest(str(tmp_path), config={})
    for key in keys:
        old_digest.pop(key, None)
    paths["digest"].write_text(json.dumps(old_digest))

    status, loaded, reason = load_repository_digest_with_status(str(tmp_path))
    assert status == "ok", reason
    assert loaded is not None


@pytest.mark.parametrize(
    "keys, assert_defaults",
    [
        pytest.param(_PHASE2_KEYS, _assert_phase2_defaults, id="phase2"),
        pytest.param(_PHASE4_KEYS, _assert_phase4_defaults, id="phase4"),
        pytest.param(_SECURITY_KEYS, _assert_security_defaults, id="security"),
    ],
)
def test_old_digest_missing_fields_does_not_crash_graphql_layer(tmp_path, keys, assert_defaults):
    """The GraphQL conversion (to_repository_digest) must tolerate the
    same old-shape digest via its own .get(..., default) pattern.
    """
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "dashboard" / "backend"))
    from resolvers.repository_digest_types import to_repository_digest

    minimal_repo(tmp_path)
    old_digest = build_repository_digest(str(tmp_path), config={})
    for key in keys:
        old_digest.pop(key, None)
    old_digest["_effective_state"] = "CURRENT"
    old_digest["_freshness"] = {"state": "CURRENT", "indexed_git_head": None, "current_git_head": None, "stale_reasons": []}

    result = to_repository_digest(old_digest)
    assert_defaults(result)


def test_old_domain_missing_lane_still_loads_and_defaults_to_other(tmp_path):
    """Backward compatibility: a repository-digest.json written before
    Phase 3 has domain dicts with no "lane" key at all. It must still
    load as 'ok', and the GraphQL layer must default it to "other" —
    never a guess, never a crash.
    """
    write_project_map(tmp_path, [{"path": "a/services/x.py", "language": "python", "lines": 5, "category": "source"}])
    write_semantic_graph(
        tmp_path,
        nodes=[make_node("a/services/x.py::foo")],
        clusters=[{"id": "c0", "label": "Core", "symbols": ["a/services/x.py::foo"], "files": ["a/services/x.py"], "cohesion": 1.0}],
    )
    old_digest = build_repository_digest(str(tmp_path), config={})
    assert old_digest["domains"][0]["lane"] == "services"  # sanity: it was actually set
    old_digest["domains"][0].pop("lane", None)
    paths = repository_digest_input_paths(str(tmp_path))
    paths["digest"].write_text(json.dumps(old_digest))

    status, loaded, reason = load_repository_digest_with_status(str(tmp_path))
    assert status == "ok", reason

    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "dashboard" / "backend"))
    from resolvers.repository_digest_types import to_repository_digest

    loaded["_effective_state"] = "CURRENT"
    loaded["_freshness"] = {"state": "CURRENT", "indexed_git_head": None, "current_git_head": None, "stale_reasons": []}
    result = to_repository_digest(loaded)
    assert result.domains()[0].lane == "other"


def test_old_relationship_missing_evidence_fields_still_loads_with_safe_defaults(tmp_path):
    """Same backward-compat contract for relationships: a pre-Phase-3
    relationship dict has no "evidence_type"/"sample_references" keys.
    """
    write_project_map(tmp_path, [
        {"path": "a/services/x.py", "language": "python", "lines": 5, "category": "source"},
        {"path": "a/models/y.py", "language": "python", "lines": 5, "category": "source"},
    ])
    write_semantic_graph(
        tmp_path,
        nodes=[make_node("a/services/x.py::foo"), make_node("a/models/y.py::bar", file="a/models/y.py")],
        clusters=[
            {"id": "c0", "label": "Services", "symbols": ["a/services/x.py::foo"], "files": ["a/services/x.py"], "cohesion": 1.0},
            {"id": "c1", "label": "Models", "symbols": ["a/models/y.py::bar"], "files": ["a/models/y.py"], "cohesion": 1.0},
        ],
        cluster_edges=[{"from": "c0", "to": "c1", "edge_count": 1, "symbols": [{"from": "a/services/x.py::foo", "to": "a/models/y.py::bar"}]}],
    )
    old_digest = build_repository_digest(str(tmp_path), config={})
    old_digest["relationships"][0].pop("evidence_type", None)
    old_digest["relationships"][0].pop("sample_references", None)

    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "dashboard" / "backend"))
    from resolvers.repository_digest_types import to_repository_digest

    old_digest["_effective_state"] = "CURRENT"
    old_digest["_freshness"] = {"state": "CURRENT", "indexed_git_head": None, "current_git_head": None, "stale_reasons": []}
    result = to_repository_digest(old_digest)
    rel = result.relationships()[0]
    assert rel.evidence_type == "unknown"
    assert rel.sample_references == []


# ── Phase 4: API & Data, CI/CD, Runtime & Configuration ─────────────


def test_api_data_populated_from_real_route_and_orm_source(tmp_path):
    minimal_repo(tmp_path, n_files=0)
    write_project_map(tmp_path, [
        {"path": "app.py", "language": "python", "lines": 5, "category": "source"},
        {"path": "models.py", "language": "python", "lines": 5, "category": "source"},
    ])
    (tmp_path / "app.py").write_text('@router.get("/users/{id}")\ndef get_user(id: int):\n    pass\n')
    (tmp_path / "models.py").write_text("class Owner:\n    pass\n")
    write_semantic_graph(
        tmp_path,
        nodes=[{
            "id": "models.py::Owner", "name": "Owner", "kind": "class", "file": "models.py", "line": 1,
            "impact": {"blast_radius": 0, "dependents": 0, "centrality": 0.0, "stability": "stable"},
            "schema": {"table_name": None, "columns": [], "foreign_keys": [], "relationships": []},
        }],
        clusters=[{"id": "c0", "label": "Core", "symbols": ["models.py::Owner"], "files": ["models.py"], "cohesion": 1.0}],
    )
    digest = build_repository_digest(str(tmp_path), config={})

    assert digest["api_data"]["routes"][0]["method"] == "GET"
    assert digest["api_data"]["routes"][0]["path"] == "/users/{id}"
    assert digest["api_data"]["entities"][0]["name"] == "Owner"
    assert digest["api_data"]["persistence_summary"]["entity_count"] == 1


def test_cicd_populated_from_real_github_actions_workflow(tmp_path):
    minimal_repo(tmp_path)
    workflows_dir = tmp_path / ".github" / "workflows"
    workflows_dir.mkdir(parents=True)
    (workflows_dir / "ci.yml").write_text("name: CI\non: push\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - run: pytest\n")
    digest = build_repository_digest(str(tmp_path), config={})

    assert digest["cicd"]["workflows"][0]["name"] == "CI"
    assert digest["cicd"]["workflows"][0]["jobs"][0]["commands"] == ["pytest"]


def test_runtime_config_populated_from_real_manifests(tmp_path):
    minimal_repo(tmp_path)
    (tmp_path / "Dockerfile").write_text("FROM python:3.12-slim\nENV DATABASE_URL=x\nARG OPENAI_API_KEY\n")
    digest = build_repository_digest(str(tmp_path), config={})

    runtimes = digest["runtime_config"]["runtimes"]
    assert any(r["language"] == "python" and r["version"] == "3.12-slim" for r in runtimes)
    env_names = {e["name"] for e in digest["runtime_config"]["environment_variables"]}
    assert env_names == {"DATABASE_URL", "OPENAI_API_KEY"}
    config_files = {c["file"] for c in digest["runtime_config"]["config_sources"]}
    assert "Dockerfile" in config_files


def test_no_secret_values_anywhere_in_built_digest(tmp_path):
    minimal_repo(tmp_path)
    (tmp_path / "Dockerfile").write_text("FROM python:3.12\nENV DATABASE_URL=postgres://user:supersecretvalue@host/db\n")
    digest = build_repository_digest(str(tmp_path), config={})
    blob = json.dumps(digest)
    assert "supersecretvalue" not in blob
    assert "postgres://user" not in blob


# ── Phase 5A: Security ──────────────────────────────────────────────


def test_security_populated_from_real_repo_evidence(tmp_path):
    write_project_map(tmp_path, [
        {"path": "config.py", "language": "python", "lines": 1, "category": "source"},
        {"path": "Dockerfile", "language": None, "lines": 2, "category": "config"},
    ])
    (tmp_path / "config.py").write_text('AWS_KEY = "AKIAIOSFODNN7EXAMPLE"\n')
    (tmp_path / "Dockerfile").write_text("FROM python:3.12\nCOPY . /app\n")

    digest = build_repository_digest(str(tmp_path), config={})

    secret_indicators = digest["security"]["secret_indicators"]
    assert any(i["pattern_type"] == "aws_access_key_id" for i in secret_indicators)
    sensitive_config = digest["security"]["sensitive_configuration"]
    assert any(c["category"] == "container_runs_as_root" for c in sensitive_config)


def test_no_secret_values_anywhere_in_security_section(tmp_path):
    write_project_map(tmp_path, [{"path": "config.py", "language": "python", "lines": 1, "category": "source"}])
    (tmp_path / "config.py").write_text('OPENAI_API_KEY = "sk-realsecretvaluethatmustneverleak123"\n')

    digest = build_repository_digest(str(tmp_path), config={})
    blob = json.dumps(digest)
    assert "sk-realsecretvaluethatmustneverleak123" not in blob




# ── Phase 5B: Changes History ────────────────────────────────────────


def test_first_build_never_creates_a_previous_snapshot_file(tmp_path):
    minimal_repo(tmp_path)
    paths = repository_digest_input_paths(str(tmp_path))
    build_repository_digest(str(tmp_path), config={})
    assert not paths["digest_previous"].is_file()


def test_second_successful_build_rotates_first_into_previous_snapshot(tmp_path):
    minimal_repo(tmp_path, n_files=2)
    paths = repository_digest_input_paths(str(tmp_path))
    first = build_repository_digest(str(tmp_path), config={})

    # A real content change between builds (not relying on generated_at's
    # 1-second resolution, which two builds in the same test can share).
    minimal_repo(tmp_path, n_files=4)
    second = build_repository_digest(str(tmp_path), config={})

    assert paths["digest_previous"].is_file()
    snapshotted = json.loads(paths["digest_previous"].read_text())
    assert snapshotted["footprint"]["file_count"] == first["footprint"]["file_count"] == 2
    current_on_disk = json.loads(paths["digest"].read_text())
    assert current_on_disk["footprint"]["file_count"] == second["footprint"]["file_count"] == 4


def test_third_build_rotates_second_not_first(tmp_path):
    minimal_repo(tmp_path)
    paths = repository_digest_input_paths(str(tmp_path))
    build_repository_digest(str(tmp_path), config={})
    second = build_repository_digest(str(tmp_path), config={})
    build_repository_digest(str(tmp_path), config={})

    snapshotted = json.loads(paths["digest_previous"].read_text())
    assert snapshotted["generated_at"] == second["generated_at"]


def test_failed_build_does_not_advance_or_corrupt_history(tmp_path):
    minimal_repo(tmp_path)
    paths = repository_digest_input_paths(str(tmp_path))
    first = build_repository_digest(str(tmp_path), config={})

    # Corrupt the project map so the *next* build fails before it ever
    # reaches the snapshot-rotation/write step.
    paths["project_map"].write_text(json.dumps({"not_files_or_summary": True}))
    with pytest.raises(DigestInputError):
        build_repository_digest(str(tmp_path), config={})

    # digest.json must be untouched (still build 1), and no previous
    # snapshot must have been created from a build that never completed.
    assert not paths["digest_previous"].is_file()
    current_on_disk = json.loads(paths["digest"].read_text())
    assert current_on_disk["generated_at"] == first["generated_at"]


def test_previous_snapshot_file_never_contains_its_own_changes_history(tmp_path):
    """Phase 5B History storage does not recursively contain history:
    the file on disk must never carry a _changes_history key — that's
    only ever attached in memory at read time.
    """
    minimal_repo(tmp_path)
    paths = repository_digest_input_paths(str(tmp_path))
    build_repository_digest(str(tmp_path), config={})
    build_repository_digest(str(tmp_path), config={})

    snapshotted = json.loads(paths["digest_previous"].read_text())
    assert "_changes_history" not in snapshotted
    assert "changes_history" not in snapshotted
    current_on_disk = json.loads(paths["digest"].read_text())
    assert "_changes_history" not in current_on_disk


def test_no_secret_values_survive_the_snapshot_rotation(tmp_path):
    write_project_map(tmp_path, [{"path": "config.py", "language": "python", "lines": 1, "category": "source"}])
    (tmp_path / "config.py").write_text('OPENAI_API_KEY = "sk-realsecretvaluethatmustneverleak456"\n')
    paths = repository_digest_input_paths(str(tmp_path))

    build_repository_digest(str(tmp_path), config={})
    build_repository_digest(str(tmp_path), config={})

    blob = paths["digest_previous"].read_text()
    assert "sk-realsecretvaluethatmustneverleak456" not in blob


def test_attach_changes_history_first_run_when_no_previous_snapshot_exists(tmp_path):
    minimal_repo(tmp_path)
    digest = build_repository_digest(str(tmp_path), config={})
    digest = attach_changes_history(str(tmp_path), digest)
    assert digest["_changes_history"]["status"] == "first_run"


def test_attach_changes_history_compares_after_a_second_build(tmp_path):
    minimal_repo(tmp_path)
    build_repository_digest(str(tmp_path), config={})
    second = build_repository_digest(str(tmp_path), config={})
    second = attach_changes_history(str(tmp_path), second)
    assert second["_changes_history"]["status"] == "compared"


def test_attach_changes_history_degrades_gracefully_on_corrupted_snapshot_file(tmp_path):
    minimal_repo(tmp_path)
    paths = repository_digest_input_paths(str(tmp_path))
    digest = build_repository_digest(str(tmp_path), config={})
    paths["digest_previous"].write_text("{not valid json")

    digest = attach_changes_history(str(tmp_path), digest)
    assert digest["_changes_history"]["status"] == "first_run"


def test_old_digest_missing_changes_history_field_does_not_crash_graphql_layer(tmp_path):
    """Backward compatibility: to_repository_digest() must tolerate a
    digest dict with no _changes_history key at all (e.g. loaded via a
    path that never called attach_changes_history).
    """
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "dashboard" / "backend"))
    from resolvers.repository_digest_types import to_repository_digest

    minimal_repo(tmp_path)
    old_digest = build_repository_digest(str(tmp_path), config={})
    old_digest["_effective_state"] = "CURRENT"
    old_digest["_freshness"] = {"state": "CURRENT", "indexed_git_head": None, "current_git_head": None, "stale_reasons": []}
    # deliberately no "_changes_history" key

    result = to_repository_digest(old_digest)
    assert result.changes_history is None or result.changes_history.status == "first_run"
