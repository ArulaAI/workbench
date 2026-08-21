#!/usr/bin/env python3
"""Tests for Phase A convention extractors (A1–A4).

Covers _extract_comodification, _extract_imports_and_naming,
_extract_import_graph, and _extract_dependency_usage from
lib/learn/convention_extractors.py.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from lib.learn.convention_extractors import (
    _extract_comodification,
    _extract_dependency_usage,
    _extract_import_graph,
    _extract_imports_and_naming,
    _detect_naming_patterns,
    _detect_test_frameworks,
    _detect_import_style,
    _detect_test_file_naming,
)
from lib.learn.conventions import RawPattern

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
# Helper: build fake git log --numstat output
# ══════════════════════════════════════════════════════════════


def _make_git_numstat(commits: list[list[str]]) -> str:
    """Build fake ``git log --numstat --pretty=format:%H`` output.

    Each inner list is the set of files touched in one commit.
    """
    lines = []
    for i, files in enumerate(commits):
        sha = f"{i:040x}"
        lines.append(sha)
        lines.append("")
        for f in files:
            lines.append(f"1\t1\t{f}")
        lines.append("")
    return "\n".join(lines)


def _run_result(stdout: str, returncode: int = 0):
    """Build a fake subprocess.CompletedProcess."""
    return type("Result", (), {
        "stdout": stdout,
        "returncode": returncode,
        "stderr": "",
    })()


# ══════════════════════════════════════════════════════════════
# A1: Co-modification tests
# ══════════════════════════════════════════════════════════════

print("\n=== A1: Co-modification ===")

# ── Two files co-modified in 10/10 commits → 100% symmetric pair ──

commits_10_10 = [["src/a.py", "src/b.py"]] * 10

with patch("subprocess.run") as mock_run:
    mock_run.return_value = _run_result(_make_git_numstat(commits_10_10))
    patterns = _extract_comodification(Path("/fake"))

symmetric = [p for p in patterns if p.type == "comodification"
             and set(p.files) == {"src/a.py", "src/b.py"}]
check("10/10 symmetric pair detected", len(symmetric) == 1,
      f"got {len(symmetric)} patterns")
if symmetric:
    check("10/10 adherence is 1.0", symmetric[0].adherence == 1.0,
          f"adherence={symmetric[0].adherence}")

# ── Two files co-modified in 7/10 commits → below 80%, no symmetric ──

commits_7_10 = [["src/a.py", "src/b.py"]] * 7 + [["src/a.py"]] * 3
with patch("subprocess.run") as mock_run:
    mock_run.return_value = _run_result(_make_git_numstat(commits_7_10))
    patterns = _extract_comodification(Path("/fake"))

symmetric = [p for p in patterns if p.type == "comodification"
             and set(p.files) == {"src/a.py", "src/b.py"}]
check("7/10 NOT symmetric (below 80%)", len(symmetric) == 0,
      f"got {len(symmetric)}")

# ── Asymmetric pair: A touches B in 9/10, B touches A in 3/10 ──
# 9 commits with both, 1 commit with A only, 7 commits with B only.
# A appears in 10 commits total, B appears in 16 commits total.
# ratio_a = 9/10 = 90% (A's commits that also touch B)
# ratio_b = 9/16 = 56% (B's commits that also touch A) — below 80%

commits_asym = (
    [["src/a.py", "src/b.py"]] * 9
    + [["src/a.py"]] * 1
    + [["src/b.py"]] * 7
)
with patch("subprocess.run") as mock_run:
    mock_run.return_value = _run_result(_make_git_numstat(commits_asym))
    patterns = _extract_comodification(Path("/fake"))

asym = [p for p in patterns if p.type == "comodification_asymmetric"]
check("asymmetric pair detected", len(asym) >= 1,
      f"got {len(asym)} asymmetric patterns")
if asym:
    # The directional pair: a always touches b
    a_touches_b = [p for p in asym if p.files[0] == "src/a.py"]
    check("direction: a→b", len(a_touches_b) >= 1,
          f"files: {[p.files for p in asym]}")

# ── Empty git history → empty list ──

with patch("subprocess.run") as mock_run:
    mock_run.return_value = _run_result("")
    patterns = _extract_comodification(Path("/fake"))

check("empty history → empty list", patterns == [])

# ── Git not available → empty list ──

with patch("subprocess.run", side_effect=FileNotFoundError):
    patterns = _extract_comodification(Path("/fake"))

check("git unavailable → empty list", patterns == [])

# ── Single commit → no divide-by-zero ──

with patch("subprocess.run") as mock_run:
    mock_run.return_value = _run_result(
        _make_git_numstat([["src/a.py", "src/b.py"]])
    )
    patterns = _extract_comodification(Path("/fake"))

check("single commit no crash", isinstance(patterns, list))
# Single commit: both files appear once, co-occur once → 100% both ways
symmetric = [p for p in patterns if p.type == "comodification"]
check("single commit: symmetric 100%", len(symmetric) == 1,
      f"got {len(symmetric)}")

# ── Nonzero return code → empty list ──

with patch("subprocess.run") as mock_run:
    mock_run.return_value = _run_result("", returncode=128)
    patterns = _extract_comodification(Path("/fake"))

check("nonzero returncode → empty list", patterns == [])

# ── Timeout → empty list ──

with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 30)):
    patterns = _extract_comodification(Path("/fake"))

check("timeout → empty list", patterns == [])

# ── max_commits passed to subprocess ──

with patch("subprocess.run") as mock_run:
    mock_run.return_value = _run_result("")
    _extract_comodification(Path("/fake"), max_commits=750)

call_args = mock_run.call_args[0][0]
check("--max-count in git args",
      any("--max-count=750" in str(a) for a in call_args),
      f"args: {call_args}")

# ── Large commits skipped (>max_commit_files) ──

# One commit with 60 files (should be skipped at max_commit_files=50),
# plus 10 commits with a 2-file pair (should produce a symmetric pattern).
large_commit = [[f"bulk/f{i}.py" for i in range(60)]]
small_commits = [["src/x.py", "src/y.py"]] * 10
with patch("subprocess.run") as mock_run:
    mock_run.return_value = _run_result(
        _make_git_numstat(large_commit + small_commits))
    patterns = _extract_comodification(Path("/fake"), max_commit_files=50)

symmetric = [p for p in patterns if p.type == "comodification"
             and set(p.files) == {"src/x.py", "src/y.py"}]
check("small-commit pair detected", len(symmetric) == 1,
      f"got {len(symmetric)}")
bulk_patterns = [p for p in patterns if any("bulk/" in f for f in p.files)]
check("large commit skipped (no bulk patterns)", len(bulk_patterns) == 0,
      f"got {len(bulk_patterns)} bulk patterns")


# ══════════════════════════════════════════════════════════════
# A2: Import and naming tests
# ══════════════════════════════════════════════════════════════

print("\n=== A2: Import and naming ===")

# ── Test framework detection (pytest) ──

hits_pytest = {"pytest": 12}
patterns = _detect_test_frameworks(hits_pytest, Path("/project"))
check("pytest framework detected", len(patterns) == 1)
if patterns:
    check("pytest type is test_framework", patterns[0].type == "test_framework")
    check("pytest evidence mentions pytest", "pytest" in patterns[0].evidence)

# ── Test framework detection (vitest) ──

hits_vitest = {"vitest": 5}
patterns = _detect_test_frameworks(hits_vitest, Path("/project"))
check("vitest framework detected", len(patterns) == 1)
if patterns:
    check("vitest evidence mentions vitest", "vitest" in patterns[0].evidence)

# ── No framework hits → empty ──

patterns = _detect_test_frameworks({}, Path("/project"))
check("no framework hits → empty", patterns == [])

# ── Naming patterns: 8/10 snake_case → naming_snake at 80% ──

snake_defs = {
    "lib": [
        {"name": "get_user", "kind": "function", "file": "lib/a.py"},
        {"name": "set_value", "kind": "function", "file": "lib/a.py"},
        {"name": "load_data", "kind": "function", "file": "lib/b.py"},
        {"name": "save_config", "kind": "function", "file": "lib/b.py"},
        {"name": "parse_input", "kind": "function", "file": "lib/c.py"},
        {"name": "validate_form", "kind": "function", "file": "lib/c.py"},
        {"name": "create_record", "kind": "function", "file": "lib/d.py"},
        {"name": "delete_entry", "kind": "function", "file": "lib/d.py"},
        {"name": "badName", "kind": "function", "file": "lib/e.py"},
        {"name": "otherBad", "kind": "function", "file": "lib/e.py"},
    ]
}
patterns = _detect_naming_patterns(snake_defs)
snake = [p for p in patterns if p.type == "naming_snake"]
check("8/10 snake_case → naming_snake", len(snake) == 1,
      f"got {len(snake)}")
if snake:
    check("snake adherence 0.8", snake[0].adherence == 0.8,
          f"adherence={snake[0].adherence}")

# ── Naming patterns: 8/10 camelCase → naming_camel ──

camel_defs = {
    "src": [
        {"name": "getUser", "kind": "function", "file": "src/a.js"},
        {"name": "setValue", "kind": "function", "file": "src/a.js"},
        {"name": "loadData", "kind": "function", "file": "src/b.js"},
        {"name": "saveConfig", "kind": "function", "file": "src/b.js"},
        {"name": "parseInput", "kind": "function", "file": "src/c.js"},
        {"name": "validateForm", "kind": "function", "file": "src/c.js"},
        {"name": "createRecord", "kind": "function", "file": "src/d.js"},
        {"name": "deleteEntry", "kind": "function", "file": "src/d.js"},
        {"name": "bad_name", "kind": "function", "file": "src/e.js"},
        {"name": "other_bad", "kind": "function", "file": "src/e.js"},
    ]
}
patterns = _detect_naming_patterns(camel_defs)
camel = [p for p in patterns if p.type == "naming_camel"]
check("8/10 camelCase → naming_camel", len(camel) == 1,
      f"got {len(camel)}")
if camel:
    check("camel adherence 0.8", camel[0].adherence == 0.8,
          f"adherence={camel[0].adherence}")

# ── PascalCase class names detected ──

pascal_defs = {
    "models": [
        {"name": "UserModel", "kind": "class", "file": "models/user.py"},
        {"name": "OrderModel", "kind": "class", "file": "models/order.py"},
        {"name": "PaymentModel", "kind": "class", "file": "models/payment.py"},
        {"name": "bad_class", "kind": "class", "file": "models/odd.py"},
    ]
}
patterns = _detect_naming_patterns(pascal_defs)
pascal = [p for p in patterns if p.type == "naming_pascal"]
check("PascalCase classes detected", len(pascal) == 1,
      f"got {len(pascal)}")
if pascal:
    check("pascal adherence 0.75", pascal[0].adherence == 0.75,
          f"adherence={pascal[0].adherence}")

# ── Not enough functions → no naming pattern ──

few_defs = {
    "lib": [
        {"name": "get_user", "kind": "function", "file": "lib/a.py"},
        {"name": "set_val", "kind": "function", "file": "lib/a.py"},
    ]
}
patterns = _detect_naming_patterns(few_defs)
check("< 5 functions → no naming pattern", len(patterns) == 0,
      f"got {len(patterns)}")

# ── csg=None → tree-sitter-only path, no crash ──

with patch("lib.learn.convention_extractors._collect_treesitter_data"):
    patterns = _extract_imports_and_naming(Path("/fake"), csg=None)

check("csg=None → no crash", isinstance(patterns, list))

# ── Import style: relative ──

rel_imports = {
    "pkg": [
        {"module": ".utils", "file": "pkg/a.py", "is_relative": True},
        {"module": ".models", "file": "pkg/a.py", "is_relative": True},
        {"module": ".db", "file": "pkg/b.py", "is_relative": True},
        {"module": ".config", "file": "pkg/b.py", "is_relative": True},
        {"module": ".helpers", "file": "pkg/c.py", "is_relative": True},
        {"module": "os", "file": "pkg/c.py", "is_relative": False},
    ]
}
patterns = _detect_import_style(rel_imports)
rel = [p for p in patterns if p.type == "import_relative"]
check("relative import pattern detected", len(rel) == 1,
      f"got {len(rel)}")

# ── Import style: absolute ──

abs_imports = {
    "pkg": [
        {"module": "os", "file": "pkg/a.py", "is_relative": False},
        {"module": "sys", "file": "pkg/a.py", "is_relative": False},
        {"module": "json", "file": "pkg/b.py", "is_relative": False},
        {"module": "typing", "file": "pkg/b.py", "is_relative": False},
        {"module": "pathlib", "file": "pkg/c.py", "is_relative": False},
        {"module": ".local", "file": "pkg/c.py", "is_relative": True},
    ]
}
patterns = _detect_import_style(abs_imports)
abs_p = [p for p in patterns if p.type == "import_absolute"]
check("absolute import pattern detected", len(abs_p) == 1,
      f"got {len(abs_p)}")

# ── Test file naming: prefix ──

prefix_counts = {"prefix": 8, "suffix": 1}
patterns = _detect_test_file_naming(prefix_counts, Path("/project"))
check("test file prefix pattern", len(patterns) == 1 and patterns[0].type == "naming_test_prefix",
      f"got {[p.type for p in patterns]}")

# ── Test file naming: too few → no pattern ──

few_counts = {"prefix": 1, "suffix": 1}
patterns = _detect_test_file_naming(few_counts, Path("/project"))
check("too few test files → no pattern", patterns == [])


# ══════════════════════════════════════════════════════════════
# A3: Import graph tests
# ══════════════════════════════════════════════════════════════

print("\n=== A3: Import graph ===")

# ── csg=None → empty list ──

patterns = _extract_import_graph(Path("/fake"), csg=None)
check("csg=None → empty list", patterns == [])

# ── Cluster with all relative imports → import_relative ──

csg_relative = {
    "edges": [
        {"type": "imports", "source": "pkg/a.py", "target": "pkg/b.py", "label": ".b"},
        {"type": "imports", "source": "pkg/a.py", "target": "pkg/c.py", "label": ".c"},
        {"type": "imports", "source": "pkg/b.py", "target": "pkg/c.py", "label": ".c"},
        {"type": "imports", "source": "pkg/c.py", "target": "pkg/d.py", "label": ".d"},
        {"type": "imports", "source": "pkg/d.py", "target": "pkg/a.py", "label": ".a"},
    ],
    "clusters": [
        {"id": "cluster_pkg", "members": ["pkg/a.py", "pkg/b.py", "pkg/c.py", "pkg/d.py"]}
    ],
    "impact": {},
}
patterns = _extract_import_graph(Path("/fake"), csg=csg_relative)
rel = [p for p in patterns if p.type == "import_relative"]
check("all-relative cluster → import_relative", len(rel) == 1,
      f"got {len(rel)}")
if rel:
    check("scoped to cluster", "cluster_pkg" in rel[0].scope,
          f"scope={rel[0].scope}")

# ── Mixed imports (below threshold) → no pattern ──

csg_mixed = {
    "edges": [
        {"type": "imports", "source": "pkg/a.py", "target": "pkg/b.py", "label": ".b"},
        {"type": "imports", "source": "pkg/a.py", "target": "lib/c.py", "label": "lib.c"},
        {"type": "imports", "source": "pkg/b.py", "target": "lib/d.py", "label": "lib.d"},
        {"type": "imports", "source": "pkg/c.py", "target": "lib/e.py", "label": "lib.e"},
        {"type": "imports", "source": "pkg/d.py", "target": "pkg/e.py", "label": ".e"},
    ],
    "clusters": [
        {"id": "cluster_pkg", "members": ["pkg/a.py", "pkg/b.py", "pkg/c.py", "pkg/d.py"]}
    ],
    "impact": {},
}
patterns = _extract_import_graph(Path("/fake"), csg=csg_mixed)
import_patterns = [p for p in patterns if p.type in ("import_relative", "import_absolute")]
check("mixed imports → no pattern (below threshold)", len(import_patterns) == 0,
      f"got {len(import_patterns)}")

# ── Hub file detection from stability scores ──

csg_hub = {
    "edges": [],
    "clusters": [],
    "impact": {
        "stability": {
            "lib/core/db.py": 0.95,
            "lib/core/config.py": 0.85,
            "lib/utils/misc.py": 0.3,
        }
    },
}
patterns = _extract_import_graph(Path("/fake"), csg=csg_hub)
hubs = [p for p in patterns if p.type == "hub_file"]
check("hub files detected (score >= 0.8)", len(hubs) == 2,
      f"got {len(hubs)}")
if hubs:
    hub_files = [p.files[0] for p in hubs]
    check("db.py is hub", "lib/core/db.py" in hub_files, f"hubs: {hub_files}")
    check("config.py is hub", "lib/core/config.py" in hub_files, f"hubs: {hub_files}")
    check("misc.py NOT hub (0.3)", "lib/utils/misc.py" not in hub_files)

# ── Empty CSG (no edges, no clusters) → empty list ──

patterns = _extract_import_graph(Path("/fake"), csg={"edges": [], "clusters": [], "impact": {}})
check("empty CSG → empty list", patterns == [])

# ── Non-import edges ignored ──

csg_calls_only = {
    "edges": [
        {"type": "calls", "source": "a.py", "target": "b.py", "label": ""},
        {"type": "calls", "source": "b.py", "target": "c.py", "label": ""},
    ],
    "clusters": [{"id": "c1", "members": ["a.py", "b.py", "c.py"]}],
    "impact": {},
}
patterns = _extract_import_graph(Path("/fake"), csg=csg_calls_only)
import_patterns = [p for p in patterns if p.type in ("import_relative", "import_absolute")]
check("call edges → no import pattern", len(import_patterns) == 0)


# ══════════════════════════════════════════════════════════════
# A4: Dependency usage tests
# ══════════════════════════════════════════════════════════════

print("\n=== A4: Dependency usage ===")

# ── Missing lock files → empty dependency list, no error ──

with tempfile.TemporaryDirectory() as tmp:
    patterns = _extract_dependency_usage(Path(tmp))
    check("no lock files → empty list, no error", patterns == [])

# ── requirements.txt parsing ──

with tempfile.TemporaryDirectory() as tmp:
    req = Path(tmp) / "requirements.txt"
    req.write_text("httpx>=0.24\nrequests==2.31.0\n# comment\npydantic\n")
    # No source files → no wrappers, but parsing should succeed without error
    patterns = _extract_dependency_usage(Path(tmp))
    check("requirements.txt parsed without error", isinstance(patterns, list))

# ── package.json parsing ──

with tempfile.TemporaryDirectory() as tmp:
    pkg = Path(tmp) / "package.json"
    pkg.write_text(json.dumps({
        "dependencies": {"axios": "^1.0", "react": "^18"},
        "devDependencies": {"vitest": "^0.34"},
    }))
    patterns = _extract_dependency_usage(Path(tmp))
    check("package.json parsed without error", isinstance(patterns, list))

# ── Wrapper module detection: client.py imports httpx, others import client ──
# This test builds a mock project structure to exercise the wrapper detection
# logic. We mock the tree-sitter Extractor since it may not be installed.

with tempfile.TemporaryDirectory() as tmp:
    # Create requirements.txt
    req = Path(tmp) / "requirements.txt"
    req.write_text("httpx\n")

    # Create Python source files
    src = Path(tmp) / "src"
    src.mkdir()
    (src / "client.py").write_text("import httpx\n")
    (src / "api.py").write_text("from src import client\n")
    (src / "views.py").write_text("from src import client\n")
    (src / "admin.py").write_text("from src import client\n")

    # Mock the Extractor to return our synthetic import references
    mock_ref = type("Ref", (), {
        "kind": "import", "name": "", "module": "", "file": "", "line": 1,
        "symbols": [],
    })

    def make_ref(kind, module, file):
        r = MagicMock()
        r.kind = kind
        r.module = module
        r.name = module
        r.file = file
        r.line = 1
        r.symbols = []
        return r

    def make_result(file, refs):
        r = MagicMock()
        r.definitions = []
        r.references = refs
        r.skeleton_lines = []
        return r

    # Build the expected extraction results by file
    file_results = {
        "client.py": make_result("client.py", [make_ref("import", "httpx", "src/client.py")]),
        "api.py": make_result("api.py", [make_ref("import", "client", "src/api.py")]),
        "views.py": make_result("views.py", [make_ref("import", "client", "src/views.py")]),
        "admin.py": make_result("admin.py", [make_ref("import", "client", "src/admin.py")]),
    }

    mock_extractor = MagicMock()
    mock_extractor.can_parse.return_value = True
    mock_extractor.extract_file.side_effect = lambda path, lang, rel: file_results.get(
        os.path.basename(path), make_result("", [])
    )

    mock_registry = MagicMock()
    mock_registry.classify.return_value = ("source", "python")

    with patch("lib.context.treesitter_extract.Extractor", return_value=mock_extractor), \
         patch("lib.context.language_registry.registry", mock_registry):
        from lib.learn.convention_extractors import _detect_wrappers
        patterns = _detect_wrappers(Path(tmp), {"httpx": "requirements.txt"})

    wrappers = [p for p in patterns if p.type == "wrapper_module"]
    check("wrapper module detected", len(wrappers) >= 1,
          f"got {len(wrappers)} wrapper patterns")
    if wrappers:
        check("wrapper file is client.py",
              any("client.py" in p.files[0] for p in wrappers),
              f"files: {[p.files for p in wrappers]}")
        check("wrapper evidence mentions httpx",
              any("httpx" in p.evidence for p in wrappers),
              f"evidence: {[p.evidence for p in wrappers]}")

# ── No wrapper pattern when library imported directly by multiple files ──

with tempfile.TemporaryDirectory() as tmp:
    req = Path(tmp) / "requirements.txt"
    req.write_text("httpx\n")

    src = Path(tmp) / "src"
    src.mkdir()
    (src / "client.py").write_text("import httpx\n")
    (src / "api.py").write_text("import httpx\n")
    (src / "views.py").write_text("import httpx\n")

    file_results_direct = {
        "client.py": make_result("client.py", [make_ref("import", "httpx", "src/client.py")]),
        "api.py": make_result("api.py", [make_ref("import", "httpx", "src/api.py")]),
        "views.py": make_result("views.py", [make_ref("import", "httpx", "src/views.py")]),
    }

    mock_extractor2 = MagicMock()
    mock_extractor2.can_parse.return_value = True
    mock_extractor2.extract_file.side_effect = lambda path, lang, rel: file_results_direct.get(
        os.path.basename(path), make_result("", [])
    )

    with patch("lib.context.treesitter_extract.Extractor", return_value=mock_extractor2), \
         patch("lib.context.language_registry.registry", mock_registry):
        from lib.learn.convention_extractors import _detect_wrappers
        patterns = _detect_wrappers(Path(tmp), {"httpx": "requirements.txt"})

    wrappers = [p for p in patterns if p.type == "wrapper_module"]
    check("no wrapper when lib imported directly", len(wrappers) == 0,
          f"got {len(wrappers)}")


# ══════════════════════════════════════════════════════════════
# Results
# ══════════════════════════════════════════════════════════════

print(f"\n{'='*60}")
print(f"Results: {passed} passed, {failed} failed")
if failed:
    sys.exit(1)
