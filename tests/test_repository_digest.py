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


def test_validate_digest_flags_missing_evidence():
    digest = {
        "schema_version": 1, "status": "complete", **empty_digest_body(),
        "identity": {"summary": "has no evidence", "evidence": []},
    }
    issues = validate_digest(digest)
    assert any("evidence" in i for i in issues)


def test_validate_digest_accepts_well_formed_empty_digest():
    digest = {"schema_version": 1, "status": "partial", **empty_digest_body(), "identity": {"summary": "", "evidence": []}}
    assert validate_digest(digest) == []


# ── Path normalization / security ────────────────────────────────


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
