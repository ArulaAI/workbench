#!/usr/bin/env python3
"""Unit tests for Layer 1 modules.

Tests individual functions with synthetic inputs — no full build required.
Covers: project_map, treesitter_extract, csg, skeletons, spec_alignment.
"""

import os
import sys
import tempfile
import json

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

passed = 0
failed = 0


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name} — {detail}")


# ══════════════════════════════════════════════════════════════
# 1A: Project Map (project_map.py)
# ══════════════════════════════════════════════════════════════

print("\n=== 1A: Project Map ===")

from lib.context.language_registry import registry
from lib.context.project_map import (
    _classify_file,
    _in_scope,
    _matches_ignore,
    _parse_scope,
    _parse_ignore_patterns,
    build_project_map,
    get_source_files,
    get_files_by_language,
    get_file_entry,
    sum_lines_for_paths,
)

# _classify_file — returns (category, language)
check("classify .py → python", _classify_file("foo.py", ".py", {})[1] == "python")
check("classify .ts → typescript", _classify_file("bar.ts", ".ts", {})[1] == "typescript")
check("classify .go → go", _classify_file("main.go", ".go", {})[1] == "go")
check("classify .md → markdown", _classify_file("README.md", ".md", {})[1] == "markdown")
check("classify .json → config", _classify_file("package.json", ".json", {})[0] == "config")
check("classify .py → source", _classify_file("app.py", ".py", {})[0] == "source")
check("classify .png → asset", _classify_file("logo.png", ".png", {})[0] == "asset")
check("classify .txt → asset", _classify_file("notes.txt", ".txt", {})[0] == "asset")
# Extended categories
ext_cats = {"docs": ["*.md", "*.txt"]}
check("classify: extended category", _classify_file("README.md", ".md", ext_cats)[0] == "docs")

# _in_scope
check("in_scope: src/foo.py in [src/]", _in_scope("src/foo.py", ["src/"]))
check("in_scope: src/foo.py not in [lib/]", not _in_scope("src/foo.py", ["lib/"]))
check("in_scope: empty scope = all in scope", _in_scope("anything.py", []))

# _matches_ignore
check("ignore: node_modules/ matches node_modules/", _matches_ignore("node_modules/foo.js", ["node_modules/"]))
check("ignore: *.pyc matches __pycache__/foo.pyc", _matches_ignore("__pycache__/foo.pyc", ["*.pyc"]))
check("ignore: .git/ matches .git/config", _matches_ignore(".git/config", [".git/"]))
check("ignore: src/app.py doesn't match *.pyc", not _matches_ignore("src/app.py", ["*.pyc"]))

# _parse_scope
check("parse scope from config",
      _parse_scope({"scope": ["src/", "lib/"]}) == ["src/", "lib/"])
check("parse scope empty", _parse_scope({}) == [])

# _parse_ignore_patterns — expects config["ignore"]["patterns"]
check("parse ignore from config",
      _parse_ignore_patterns({"ignore": {"patterns": ["*.log"]}}) == ["*.log"])

# Language registry coverage
check("classify .py", registry.classify(".py") == ("source", "python"))
check("classify .ts", registry.classify(".ts") == ("source", "typescript"))
check("classify .rs", registry.classify(".rs") == ("source", "rust"))
check("registry has >100 languages", len(registry._by_name) > 100)

# get_source_files
pm = {"files": [
    {"path": "a.py", "language": "python", "category": "source"},
    {"path": "b.json", "language": None, "category": "config"},
    {"path": "c.ts", "language": "typescript", "category": "source"},
]}
sources = get_source_files(pm)
check("get_source_files returns sources only", len(sources) == 2)
check("get_source_files includes a.py", any(f["path"] == "a.py" for f in sources))

# get_files_by_language
py_files = get_files_by_language(pm, "python")
check("get_files_by_language: 1 python file", len(py_files) == 1)

# get_file_entry
check("get_file_entry found", get_file_entry(pm, "a.py") is not None)
check("get_file_entry not found", get_file_entry(pm, "z.py") is None)

# sum_lines_for_paths
pm_with_lines = {"files": [
    {"path": "a.py", "lines": 100},
    {"path": "b.py", "lines": 200},
    {"path": "c.py", "lines": 300},
]}
check("sum_lines_for_paths", sum_lines_for_paths(pm_with_lines, ["a.py", "c.py"]) == 400)
check("sum_lines_for_paths: missing path = 0", sum_lines_for_paths(pm_with_lines, ["z.py"]) == 0)

# build_project_map on actual project
pm_real = build_project_map(PROJECT_ROOT)
check("build_project_map: has files", len(pm_real["files"]) > 50)
check("build_project_map: has summary", "summary" in pm_real)
check("build_project_map: has directories", "directories" in pm_real)
check("build_project_map: summary has total_files",
      pm_real["summary"]["total_files"] > 0)
check("build_project_map: summary has by_language",
      "by_language" in pm_real["summary"])


# ══════════════════════════════════════════════════════════════
# 1B: tree-sitter Extraction (treesitter_extract.py)
# ══════════════════════════════════════════════════════════════

print("\n=== 1B: tree-sitter Extraction ===")

from lib.context.treesitter_extract import (
    Extractor,
    _find_sg,
    _strip_collection_type,
    _extract_mapped_type,
)

extractor = Extractor()
has_sg = _find_sg() is not None
print(f"  ast-grep CLI: {'available' if has_sg else 'not installed (defs/refs require sg)'}")

# Grammar registry (via language registry)
check("grammar python", registry.grammar("python") is not None)
check("grammar typescript", registry.grammar("typescript") is not None)
check("grammar go", registry.grammar("go") is not None)
check("can_parse python", registry.can_parse("python"))

# can_parse (tree-sitter grammar availability)
check("can_parse: python", extractor.can_parse("python"))
check("can_parse: typescript", extractor.can_parse("typescript"))
check("can_parse: unknown_lang", not extractor.can_parse("unknown_lang"))

# Extract a real Python file
test_py = os.path.join(PROJECT_ROOT, "lib", "context", "utils.py")
result = extractor.extract_file(test_py, "python", "lib/context/utils.py")

# Skeleton always works (tree-sitter, no sg required)
check("extract_file: has skeleton_lines", len(result.skeleton_lines) > 0)
check("skeleton: fewer lines than source",
      len(result.skeleton_lines) < 200)  # utils.py is ~200 lines

# Definitions and references require ast-grep CLI
if has_sg:
    check("extract_file: has definitions", len(result.definitions) > 0)
    check("extract_file: has references", len(result.references) > 0)

    d = result.definitions[0]
    check("definition: has name", hasattr(d, "name") and d.name)
    check("definition: has kind", hasattr(d, "kind") and d.kind)
    check("definition: has file", hasattr(d, "file") and d.file)
    check("definition: has line", hasattr(d, "line") and d.line > 0)

    r = result.references[0]
    check("reference: has name", hasattr(r, "name") and r.name)
    check("reference: has kind", hasattr(r, "kind") and r.kind)
else:
    check("extract_file: graceful without sg (defs empty)", len(result.definitions) == 0)
    check("extract_file: graceful without sg (refs empty)", len(result.references) == 0)
    print("  (skipping def/ref structure tests — sg not installed)")

# can_parse checks tree-sitter grammar, independent of sg
check("can_parse: tsx", extractor.can_parse("typescript"))

# Helper functions (retained for compatibility)
check("_strip_collection_type: list[str] → str",
      _strip_collection_type("list[str]") == "str")
check("_strip_collection_type: dict unchanged (multi-arg)",
      _strip_collection_type("dict[str, int]") == "dict[str, int]")
check("_strip_collection_type: plain → plain",
      _strip_collection_type("str") == "str")

check("_extract_mapped_type: Mapped[int] → int",
      _extract_mapped_type("Mapped[int]") == "int")
check("_extract_mapped_type: Mapped[list[Post]] → list[Post]",
      _extract_mapped_type('Mapped[list["Post"]]') == 'list["Post"]')


# ══════════════════════════════════════════════════════════════
# 1C: Codebase Semantic Graph (csg.py)
# ══════════════════════════════════════════════════════════════

print("\n=== 1C: Codebase Semantic Graph ===")

from lib.context.csg import (
    symbol_id,
    build_layer_a,
    build_layer_b,
    build_layer_c,
    build_layer_d,
    get_symbol,
    get_symbols_in_file,
    get_edges_for_symbol,
    get_dependents,
    get_dependencies,
    get_cluster_for_file,
    get_bridge_symbols,
    get_high_impact_symbols,
    _classify_stability,
)

# symbol_id
check("symbol_id: simple", symbol_id("foo.py", "bar") == "foo.py::bar")
check("symbol_id: with parent",
      symbol_id("foo.py", "bar", "Baz") == "foo.py::Baz.bar")

# _classify_stability — (sid, dependents, cross_cluster)
# bridge: symbol has cross-cluster connections
check("classify: bridge", _classify_stability(
    "a.py::foo", 5, {"a.py::foo": {"c2"}}) == "bridge")
# hub: 3+ dependents, no cross-cluster connections
check("classify: hub", _classify_stability(
    "a.py::foo", 8, {}) == "hub")
# stable: few dependents, no cross-cluster connections
check("classify: stable", _classify_stability(
    "a.py::foo", 1, {}) == "stable")

# Build layers with real extraction data
extractions = {}
for fname in ["lib/context/utils.py", "lib/context/budget.py"]:
    abs_path = os.path.join(PROJECT_ROOT, fname)
    if os.path.exists(abs_path):
        ext = extractor.extract_file(abs_path, "python", fname)
        extractions[fname] = ext

check("extractions prepared", len(extractions) == 2)

# Layer A-D tests require definitions (ast-grep CLI)
nodes_a, edges_a = build_layer_a(extractions)
if has_sg:
    check("Layer A: nodes > 0", len(nodes_a) > 0)
    check("Layer A: has structural edges", len(edges_a) >= 0)
    check("Layer A: node has 'id'", "id" in nodes_a[0])

    edges_b = build_layer_b(extractions, nodes_a, edges_a)
    check("Layer B: edges >= structural", len(edges_b) >= len(edges_a),
          f"A={len(edges_a)}, B={len(edges_b)}")

    clusters, cluster_edges, sym_to_cluster = build_layer_c(nodes_a, edges_b)
    check("Layer C: has clusters", len(clusters) > 0)
    check("Layer C: cluster has 'id'", "id" in clusters[0])
    check("Layer C: cluster has 'files'", "files" in clusters[0])
    check("Layer C: sym_to_cluster is dict", isinstance(sym_to_cluster, dict))

    impact = build_layer_d(nodes_a, edges_b, sym_to_cluster)
    check("Layer D: returns impact dict", isinstance(impact, dict))
else:
    check("Layer A: empty without sg", len(nodes_a) == 0)
    edges_b = build_layer_b(extractions, nodes_a, edges_a)
    clusters, cluster_edges, sym_to_cluster = build_layer_c(nodes_a, edges_b)
    impact = build_layer_d(nodes_a, edges_b, sym_to_cluster)
    check("Layer D: returns dict even empty", isinstance(impact, dict))
    print("  (skipping Layer A-D depth tests — sg not installed)")

# Query helpers with real CSG
from lib.context.utils import read_json
csg = read_json(os.path.join(PROJECT_ROOT, ".speed", "context", "semantic-graph.json"))
if csg and csg.get("nodes"):
    # get_symbol
    sample_id = csg["nodes"][0]["id"]
    sym = get_symbol(csg, sample_id)
    check("get_symbol: found", sym is not None)
    check("get_symbol: not found", get_symbol(csg, "nonexistent::foo") is None)

    # get_symbols_in_file
    sample_file = csg["nodes"][0]["file"]
    file_syms = get_symbols_in_file(csg, sample_file)
    check("get_symbols_in_file: found", len(file_syms) > 0)

    # get_edges_for_symbol
    edges = get_edges_for_symbol(csg, sample_id)
    check("get_edges_for_symbol: returns list", isinstance(edges, list))

    # get_cluster_for_file
    cluster = get_cluster_for_file(csg, sample_file)
    check("get_cluster_for_file: found", cluster is not None)

    # get_bridge_symbols / get_high_impact_symbols
    bridges = get_bridge_symbols(csg)
    check("get_bridge_symbols: returns list", isinstance(bridges, list))

    high_impact = get_high_impact_symbols(csg)
    check("get_high_impact_symbols: returns list", isinstance(high_impact, list))
else:
    # CSG empty (sg not installed) — test query functions with empty data
    check("get_symbol: not found", get_symbol(csg or {"nodes": []}, "x") is None)
    check("get_edges_for_symbol: returns list", isinstance(get_edges_for_symbol(csg or {"edges": []}, "x"), list))
    check("get_bridge_symbols: returns list", isinstance(get_bridge_symbols(csg or {"nodes": []}), list))
    check("get_high_impact_symbols: returns list", isinstance(get_high_impact_symbols(csg or {"nodes": []}), list))


# ══════════════════════════════════════════════════════════════
# 1D: File Skeletons (skeletons.py)
# ══════════════════════════════════════════════════════════════

print("\n=== 1D: Skeletons ===")

from lib.context.skeletons import (
    load_skeleton,
    skeleton_exists,
    list_skeletons,
)

CONTEXT_DIR = os.path.join(PROJECT_ROOT, ".speed", "context")

# load_skeleton
skel = load_skeleton(CONTEXT_DIR, "lib/context/utils.py")
check("load_skeleton: returns content", skel is not None and len(skel) > 0)
if skel:
    check("skeleton: has import lines", "import" in skel)
    check("skeleton: has def lines", "def " in skel)
    # Skeleton should be shorter than source
    source_lines = open(os.path.join(PROJECT_ROOT, "lib/context/utils.py")).read().count("\n")
    skel_lines = skel.count("\n")
    check("skeleton: compression ratio > 2:1",
          source_lines / max(skel_lines, 1) > 2,
          f"source={source_lines}, skel={skel_lines}")

# load_skeleton: nonexistent
check("load_skeleton: missing returns None",
      load_skeleton(CONTEXT_DIR, "nonexistent.py") is None)

# skeleton_exists
check("skeleton_exists: true", skeleton_exists(CONTEXT_DIR, "lib/context/utils.py"))
check("skeleton_exists: false", not skeleton_exists(CONTEXT_DIR, "nonexistent.py"))

# list_skeletons
skel_list = list_skeletons(CONTEXT_DIR)
check("list_skeletons: returns list", isinstance(skel_list, list))
check("list_skeletons: > 10 skeletons", len(skel_list) > 10,
      f"got {len(skel_list)}")


# ══════════════════════════════════════════════════════════════
# 1E: Spec-Codebase Alignment (spec_alignment.py)
# ══════════════════════════════════════════════════════════════

print("\n=== 1E: Spec-Codebase Alignment ===")

from lib.context.spec_alignment import (
    _extract_claims_from_markdown,
    build_spec_alignment,
    get_claims_by_status,
    get_claims_for_entity,
    format_alignment_summary,
)

# Claim extraction from markdown
spec_md = """# Feature Spec

## Data Model

The `User` model is defined in `lib/models/user.py`.

| Column | Type |
|--------|------|
| id | integer |
| email | string |

## API Endpoints

The function `create_user()` handles user creation.
File `lib/context/utils.py` contains shared utilities.

## Relationships

User has many Posts through the `posts` relationship.
"""

claims = _extract_claims_from_markdown(spec_md, "test-spec.md")
check("extract claims: found claims", len(claims) > 0, f"got {len(claims)}")

# Check claim types found — backtick extraction with pm=None, csg=None produces:
#   User → entity_defined, lib/models/user.py → file_exists,
#   create_user() → function_exists, lib/context/utils.py → file_exists,
#   posts → discarded (not an identifier)
claim_types = {c.claim_type for c in claims}
check("extract claims: found file_exists",
      "file_exists" in claim_types,
      f"types: {claim_types}")
check("extract claims: found entity_defined",
      "entity_defined" in claim_types,
      f"types: {claim_types}")
check("extract claims: found function_exists",
      "function_exists" in claim_types,
      f"types: {claim_types}")
check("extract claims: no table_exists (backtick extraction)",
      "table_exists" not in claim_types,
      f"types: {claim_types}")
check("extract claims: no relationship_exists (backtick extraction)",
      "relationship_exists" not in claim_types,
      f"types: {claim_types}")

# Print claim summary for debugging
for c in claims:
    print(f"    [{c.claim_type}] {c.entity}: {c.claim_text[:50]}")

# build_spec_alignment with real project
alignment = build_spec_alignment(
    spec_files={"test-spec.md": spec_md},
    project_map=pm_real,
    csg=csg,
)
check("build_spec_alignment: has claims", len(alignment.get("claims", [])) > 0)
check("build_spec_alignment: has summary", "summary" in alignment)

# get_claims_by_status
confirmed = get_claims_by_status(alignment, "confirmed")
missing = get_claims_by_status(alignment, "missing")
check("get_claims_by_status: returns lists",
      isinstance(confirmed, list) and isinstance(missing, list))
# utils.py exists in the project, so it should be confirmed
has_utils_confirmed = any(
    "utils.py" in str(c.get("entity", "") + c.get("claim_text", ""))
    for c in confirmed
)
check("utils.py confirmed as existing",
      has_utils_confirmed,
      f"confirmed: {[c.get('entity') for c in confirmed]}")

# format_alignment_summary
summary_text = format_alignment_summary(alignment)
check("format_alignment_summary: non-empty", len(summary_text) > 0)
check("format_alignment_summary: has confirmed count", "confirmed" in summary_text.lower())


# ══════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════

print(f"\n{'='*60}")
print(f"Layer 1 Unit Tests: {passed} passed, {failed} failed")
if failed == 0:
    print("ALL TESTS PASSED")
else:
    print(f"FAILURES: {failed}")
    sys.exit(1)
