#!/usr/bin/env python3
"""Unit tests for Layer 3 (Assembly) and Verification modules.

Tests individual functions with synthetic inputs.
Covers: assembly, criteria_verify, decomposition_gate, failure_classify,
        contract_verify, spec_traceability.
"""

import os
import sys

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
# 3A: Assembly (assembly.py)
# ══════════════════════════════════════════════════════════════

print("\n=== 3A: Assembly ===")

from lib.context.assembly import (
    _truncate,
    _lang_for_path,
    _extract_diff_files,
    assemble_architect,
    assemble_verifier,
    assemble_developer,
    assemble_reviewer,
    assemble_coherence,
    assemble_debugger,
)

# -- _truncate --

short_text = "Hello world\n" * 10  # ~120 chars
result = _truncate(short_text, 1000)
check("truncate: short text unchanged", result == short_text)

long_text = "x = 1\n" * 50000  # ~300K chars, well over any budget
result = _truncate(long_text, 100, label="test")
check("truncate: long text truncated", len(result) < len(long_text))
check("truncate: has truncation notice", "[Truncated: test:" in result)

# -- _lang_for_path --

check("lang: .py → python", _lang_for_path("foo.py") == "python")
check("lang: .ts → typescript", _lang_for_path("bar.ts") == "typescript")
check("lang: .go → go", _lang_for_path("main.go") == "go")
check("lang: .sh → bash", _lang_for_path("run.sh") == "bash")
check("lang: unknown → empty", _lang_for_path("data.xyz") == "")
check("lang: .json → json", _lang_for_path("config.json") == "json")
check("lang: .md → markdown", _lang_for_path("README.md") == "markdown")

# -- _extract_diff_files --

diff_text = """\
diff --git a/lib/foo.py b/lib/foo.py
--- a/lib/foo.py
+++ b/lib/foo.py
@@ -1,3 +1,4 @@
 import os
+import sys
diff --git a/lib/bar.py b/lib/bar.py
--- /dev/null
+++ b/lib/bar.py
@@ -0,0 +1,5 @@
+class Bar:
+    pass
"""
files = _extract_diff_files(diff_text)
check("diff files: found foo.py", "lib/foo.py" in files)
check("diff files: found bar.py", "lib/bar.py" in files)
check("diff files: no /dev/null", "/dev/null" not in files)

empty_files = _extract_diff_files("")
check("diff files: empty diff → empty set", len(empty_files) == 0)

# -- assemble_architect --

pm = {
    "summary": {"total_files": 10, "total_lines": 1000, "by_language": {
        "python": {"files": 8, "lines": 800},
        "json": {"files": 2, "lines": 200},
    }},
    "directories": [
        {"path": "lib/", "file_count": 5, "total_lines": 500},
    ],
    "files": [],
}

csg_mini = {
    "nodes": [
        {"id": "lib/foo.py::Foo", "name": "Foo", "kind": "class",
         "file": "lib/foo.py", "line": 1,
         "impact": {"stability": "bridge", "blast_radius": 10, "centrality": 0.8, "dependents": 5}},
        {"id": "lib/foo.py::Bar", "name": "Bar", "kind": "class",
         "file": "lib/foo.py", "line": 20,
         "impact": {"stability": "stable", "blast_radius": 2, "centrality": 0.3, "dependents": 1}},
    ],
    "edges": [],
    "clusters": [
        {"id": "c0", "label": "core", "symbols": ["lib/foo.py::Foo", "lib/foo.py::Bar"],
         "files": ["lib/foo.py"], "cohesion": 0.9,
         "internal_refs": 5, "external_refs": 2},
    ],
    "cluster_edges": [],
}

arch_result = assemble_architect(pm, csg_mini)
check("architect: returns string", isinstance(arch_result, str))
check("architect: has project overview", "Project Overview" in arch_result)
check("architect: has file count", "10 files" in arch_result)
check("architect: has domain architecture", "Domain Architecture" in arch_result)
check("architect: has bridge symbols", "High-Impact Symbols" in arch_result)
check("architect: bridge symbol listed", "Foo" in arch_result)

# With spec alignment
sa = {
    "claims": [
        {"entity": "User", "status": "confirmed", "claim_text": "User model exists", "evidence": "Found"},
        {"entity": "Post", "status": "missing", "claim_text": "Post model needed"},
    ],
}
arch_with_sa = assemble_architect(pm, csg_mini, spec_alignment=sa)
check("architect: spec vs reality section", "Spec vs. Reality" in arch_with_sa)
check("architect: confirmed claims", "Confirmed" in arch_with_sa)
check("architect: missing claims", "Missing" in arch_with_sa)

# Without spec alignment
arch_no_sa = assemble_architect(pm, csg_mini, spec_alignment=None)
check("architect: no spec section when None", "Spec vs. Reality" not in arch_no_sa)

# -- assemble_verifier --

tasks_for_verifier = [
    {
        "id": "t1", "title": "Build models",
        "description": "Create the data models.",
        "acceptance_criteria": [
            {"criterion": "User model exists", "verify_by": "schema_check"},
        ],
        "depends_on": [],
        "files_touched": ["models/user.py"],
        "rationale": "Foundation for API.",
        "assumptions": ["PostgreSQL backend"],
        "spec_references": [{"spec": "spec.md", "section": "Data Model", "requirement": "User table"}],
    },
]
ver_result = assemble_verifier("# Product Spec\nBuild a user system.", tasks_for_verifier)
check("verifier: returns string", isinstance(ver_result, str))
check("verifier: has product spec", "Product Specification" in ver_result)
check("verifier: has task plan", "Task Plan" in ver_result)
check("verifier: has task title", "Build models" in ver_result)
check("verifier: has acceptance criteria", "Acceptance Criteria" in ver_result)
check("verifier: has rationale", "Foundation for API" in ver_result)
check("verifier: has assumptions", "PostgreSQL backend" in ver_result)
check("verifier: has spec references", "Spec References" in ver_result)

# With cross-cutting concerns
ver_with_cc = assemble_verifier("spec", tasks_for_verifier,
                                 cross_cutting_concerns=["All models use UUID PKs"])
check("verifier: has cross-cutting", "Cross-Cutting Concerns" in ver_with_cc)
check("verifier: concern text present", "UUID PKs" in ver_with_cc)

# With decomposition result
decomp = {
    "checks": [
        {"check": "task_size", "status": "fail", "message": "Task too large"},
        {"check": "cross_cluster", "status": "warn", "message": "High coordination"},
    ],
}
ver_with_decomp = assemble_verifier("spec", tasks_for_verifier, decomposition_result=decomp)
check("verifier: has decomp results", "Decomposition Gate" in ver_with_decomp)

# -- assemble_developer --

task_dev = {
    "id": "t1", "title": "Build user model",
    "description": "Create User SQLAlchemy model.",
    "rationale": "Foundation for auth.",
    "acceptance_criteria": [
        {"criterion": "User class exists", "verify_by": "schema_check"},
    ],
    "assumptions": ["email is unique"],
    "files_touched": ["models/user.py"],
    "depends_on": [],
}
code_ctx = {
    "full_content": {
        "files_touched": [{"path": "models/user.py", "content": "class User:\n    pass\n"}],
        "one_hop": [{"path": "models/base.py", "content": "class Base:\n    pass\n", "relationship": "imports"}],
    },
    "skeleton": {"two_hop": [{"path": "lib/auth.py", "skeleton_content": "def login(): ...", "relationship": "uses"}]},
}
task_ctx = {
    "reasoning": {"rationale": "Foundation"},
    "upstream": [{"task_id": "t0", "title": "Setup DB", "files_modified": ["db.py"], "decisions": ["Use PostgreSQL"]}],
    "downstream": [{"task_id": "t2", "title": "Auth", "depends_on_me_for": "User model"}],
    "shared_scope_warnings": [],
}
spec_ctx = {
    "relevant_spec_sections": [{"source": {"spec": "spec.md", "section": "User"}, "content": "Users have email."}],
    "alignment_status": [{"claim": "User model", "status": "confirmed", "evidence": "Exists"}],
    "contract_excerpt": "",
}

dev_result = assemble_developer(task_dev, code_ctx, task_ctx, spec_ctx,
                                 branch_name="feat/user",
                                 worktree_path="/tmp/wt",
                                 feature_name="user-auth")
check("developer: returns string", isinstance(dev_result, str))
check("developer: has task title", "Build user model" in dev_result)
check("developer: has rationale", "Foundation for auth" in dev_result)
check("developer: has criteria", "User class exists" in dev_result)
check("developer: has assumptions", "email is unique" in dev_result)
check("developer: has files you'll modify", "Files You'll Modify" in dev_result)
check("developer: has related code", "Related Code" in dev_result)
check("developer: has nearby code", "Nearby Code" in dev_result)
check("developer: has upstream context", "Completed Dependencies" in dev_result)
check("developer: has downstream", "What Depends on You" in dev_result)
check("developer: has spec requirements", "Spec Requirements" in dev_result)
check("developer: has branch info", "feat/user" in dev_result)
check("developer: has worktree path", "/tmp/wt" in dev_result)
check("developer: has gate commands", "speed gates" in dev_result)
check("developer: gate uses feature name", "-f user-auth" in dev_result)

# Developer with cross-cutting concerns
dev_cc = assemble_developer(task_dev, code_ctx, task_ctx, spec_ctx,
                             cross_cutting_concerns=["Use UTC timestamps"])
check("developer: cross-cutting present", "UTC timestamps" in dev_cc)

# Developer with sibling-owned files
task_ctx_sibling = dict(task_ctx)
task_ctx_sibling["sibling_owned_files"] = {
    "models/post.py": "t3",
    "models/comment.py": "t3",
    "lib/auth.py": "t4",
}
dev_sibling = assemble_developer(task_dev, code_ctx, task_ctx_sibling, spec_ctx)
check("developer: sibling files section present", "Files Owned by Other Tasks" in dev_sibling)
check("developer: sibling warning text", "scope violation" in dev_sibling)
check("developer: sibling task reference", "Task t3" in dev_sibling)
check("developer: sibling file listed", "models/post.py" in dev_sibling)

# Developer with shared scope warnings
task_ctx_warn = dict(task_ctx)
task_ctx_warn["shared_scope_warnings"] = [
    {"symbol": "User", "also_modified_by": ["t3"], "impact": {"blast_radius": 5, "stability": "bridge"}, "warning": "Coordinate!"},
]
dev_warn = assemble_developer(task_dev, code_ctx, task_ctx_warn, spec_ctx)
check("developer: warnings present", "Warnings" in dev_warn)
check("developer: warning symbol", "User" in dev_warn)

# -- assemble_reviewer --

rev_result = assemble_reviewer(
    task_dev,
    diff="diff --git a/models/user.py b/models/user.py\n--- /dev/null\n+++ b/models/user.py\n+class User:\n+    pass",
    task_context=task_ctx,
    spec_context=spec_ctx,
    criteria_results=[
        {"criterion": "User class exists", "status": "pass", "evidence": "Found"},
    ],
    cross_cutting_concerns=["UTC timestamps"],
)
check("reviewer: returns string", isinstance(rev_result, str))
check("reviewer: has review header", "Review: Task t1" in rev_result)
check("reviewer: has criteria table", "Criterion" in rev_result)
check("reviewer: has verification results", "Automated Verification" in rev_result)
check("reviewer: has diff", "Git Diff" in rev_result)
check("reviewer: has spec requirements", "Spec Requirements" in rev_result)
check("reviewer: has cross-cutting", "Cross-Cutting Constraints" in rev_result)
check("reviewer: has instructions", "Instructions" in rev_result)

# Reviewer with CSG impact
rev_impact = assemble_reviewer(
    task_dev,
    diff="diff --git a/lib/foo.py b/lib/foo.py\n--- a/lib/foo.py\n+++ b/lib/foo.py\n+modified",
    task_context=task_ctx,
    spec_context=spec_ctx,
    csg=csg_mini,
)
check("reviewer: has impact assessment", "Impact Assessment" in rev_impact)

# -- assemble_coherence --

cross_analysis = {
    "domain_overlap": [
        {"cluster": "core", "tasks_touching": ["t1", "t2"], "shared_symbols": ["Foo"], "risk": "high"},
    ],
    "interface_boundaries": [
        {"from_task": "t1", "to_task": "t2", "interface_symbols": [{"symbol": "Foo"}]},
    ],
    "high_impact_modifications": [
        {"symbol": "Foo", "modified_by": "t1", "blast_radius": 10, "centrality": 0.8, "stability": "bridge"},
    ],
}
coh_result = assemble_coherence(
    cross_analysis,
    completed_tasks=[task_dev],
    task_diffs={"t1": "+class User:\n+    pass"},
    product_spec="# Spec",
    contract={"entities": [{"name": "User", "type": "database"}]},
)
check("coherence: returns string", isinstance(coh_result, str))
check("coherence: has header", "Coherence Check" in coh_result)
check("coherence: has domain overlap", "Domain Overlap" in coh_result)
check("coherence: has interface boundaries", "Interface Boundaries" in coh_result)
check("coherence: has high impact", "High-Impact Modifications" in coh_result)
check("coherence: has task diffs", "All Task Diffs" in coh_result)
check("coherence: has product spec", "Product Specification" in coh_result)
check("coherence: has contract", "Data Model Contract" in coh_result)
check("coherence: has instructions", "Instructions" in coh_result)

# -- assemble_debugger --

budget = {
    "total_budget": 80000,
    "total_used": 60000,
    "allocated": {
        "code_context": {"used": 40000, "budget": 50000, "files_full": 3, "files_skeleton": 2, "files_dropped": 1},
    },
    "cuts_made": [{"file": "lib/big.py", "original_tier": "full", "downgraded_to": "skeleton", "reason": "over budget"}],
}
dbg_result = assemble_debugger(
    task_dev,
    budget=budget,
    agent_output="Read file lib/foo.py\nSearching for User\nI need to find the base class\n" * 10,
    diff="+class User:\n+    pass",
    code_context=code_ctx,
    failure_classification={"class": "pipeline", "subclass": "context_cut", "evidence": "Budget cuts"},
)
check("debugger: returns string", isinstance(dbg_result, str))
check("debugger: has failed task header", "Failed Task t1" in dbg_result)
check("debugger: has failure classification", "Failure Classification" in dbg_result)
check("debugger: shows class", "pipeline" in dbg_result)
check("debugger: has budget analysis", "Context Budget Analysis" in dbg_result)
check("debugger: shows cuts", "Context was cut" in dbg_result)
check("debugger: has task description", "Task Description" in dbg_result)
check("debugger: has agent output", "Agent Output" in dbg_result)
check("debugger: has git diff", "Git Diff" in dbg_result)
check("debugger: has relevant code", "Relevant Code Context" in dbg_result)

# Debugger minimal (no optional args)
dbg_min = assemble_debugger(task_dev, budget={"total_budget": 80000, "allocated": {}, "cuts_made": []})
check("debugger minimal: no crash", dbg_min is not None)
check("debugger minimal: has task header", "Failed Task" in dbg_min)


# ══════════════════════════════════════════════════════════════
# 4A: Criteria Verify (criteria_verify.py)
# ══════════════════════════════════════════════════════════════

print("\n=== 4A: Criteria Verify ===")

from lib.criteria_verify import verify_criteria

# Manual verification
task_manual = {
    "id": "cv-1",
    "acceptance_criteria": [
        {"criterion": "UI looks good", "verify_by": "manual"},
    ],
    "files_touched": [],
}
result = verify_criteria(task_manual, PROJECT_ROOT)
check("manual: returns dict", isinstance(result, dict))
check("manual: has task_id", result["task_id"] == "cv-1")
check("manual: has criteria_results", "criteria_results" in result)
check("manual: has summary", "summary" in result)
check("manual: status unverifiable", result["criteria_results"][0]["status"] == "unverifiable")
check("manual: summary counts", result["summary"]["unverifiable"] == 1)

# File exists verification
task_file = {
    "id": "cv-2",
    "acceptance_criteria": [
        {"criterion": 'File "lib/context/utils.py" exists in the project', "verify_by": "file_exists"},
    ],
    "files_touched": ["lib/context/utils.py"],
}
result_file = verify_criteria(task_file, PROJECT_ROOT)
check("file_exists: pass for real file", result_file["criteria_results"][0]["status"] == "pass")

# File not found
task_file_missing = {
    "id": "cv-3",
    "acceptance_criteria": [
        {"criterion": 'File "nonexistent_xyz.py" exists', "verify_by": "file_exists"},
    ],
    "files_touched": [],
}
result_missing = verify_criteria(task_file_missing, PROJECT_ROOT)
check("file_exists: fail for missing file", result_missing["criteria_results"][0]["status"] == "fail")

# Test verification (test file finding)
task_test = {
    "id": "cv-4",
    "acceptance_criteria": [
        {"criterion": "Tests pass for utils", "verify_by": "test"},
    ],
    "files_touched": ["lib/context/utils.py"],
}
result_test = verify_criteria(task_test, PROJECT_ROOT)
# Should find tests/test_unit_layer1.py or similar — at minimum doesn't crash
check("test: no crash", result_test is not None)
check("test: has result", len(result_test["criteria_results"]) == 1)

# Lint without command → unverifiable
task_lint = {
    "id": "cv-5",
    "acceptance_criteria": [
        {"criterion": "No lint errors", "verify_by": "lint"},
    ],
    "files_touched": ["lib/context/utils.py"],
}
result_lint = verify_criteria(task_lint, PROJECT_ROOT)
check("lint: unverifiable without command",
      result_lint["criteria_results"][0]["status"] == "unverifiable")

# Schema check with CSG
from lib.context.utils import read_json
CONTEXT_DIR = os.path.join(PROJECT_ROOT, ".speed", "context")
csg_real = read_json(os.path.join(CONTEXT_DIR, "semantic-graph.json"))

task_schema = {
    "id": "cv-6",
    "acceptance_criteria": [
        {"criterion": "No parseable entity names here", "verify_by": "schema_check"},
    ],
    "files_touched": [],
}
result_schema = verify_criteria(task_schema, PROJECT_ROOT, csg=csg_real)
check("schema_check: no entities → unverifiable",
      result_schema["criteria_results"][0]["status"] == "unverifiable")

# String criteria (legacy format)
task_string = {
    "id": "cv-7",
    "acceptance_criteria": "Single string criterion",
}
result_string = verify_criteria(task_string, PROJECT_ROOT)
check("string criteria: no crash", result_string is not None)
check("string criteria: wrapped as manual",
      result_string["criteria_results"][0]["verify_by"] == "manual")

# List of strings (legacy format)
task_str_list = {
    "id": "cv-8",
    "acceptance_criteria": ["First criterion", "Second criterion"],
}
result_str_list = verify_criteria(task_str_list, PROJECT_ROOT)
check("string list: no crash", result_str_list is not None)
check("string list: two results", len(result_str_list["criteria_results"]) == 2)
check("string list: both manual",
      all(r["verify_by"] == "manual" for r in result_str_list["criteria_results"]))

# Empty criteria
task_empty = {"id": "cv-9", "acceptance_criteria": []}
result_empty = verify_criteria(task_empty, PROJECT_ROOT)
check("empty criteria: no crash", result_empty is not None)
check("empty criteria: zero results", len(result_empty["criteria_results"]) == 0)

# Multiple criteria mixed
task_mixed = {
    "id": "cv-10",
    "acceptance_criteria": [
        {"criterion": "File exists", "verify_by": "file_exists"},
        {"criterion": "Review UI", "verify_by": "manual"},
    ],
    "files_touched": ["lib/context/utils.py"],
}
result_mixed = verify_criteria(task_mixed, PROJECT_ROOT)
check("mixed: two results", len(result_mixed["criteria_results"]) == 2)
check("mixed: summary counts correct",
      result_mixed["summary"]["pass"] + result_mixed["summary"]["fail"]
      + result_mixed["summary"]["unverifiable"] == 2)

# No acceptance_criteria key at all
task_no_criteria = {"id": "cv-11", "files_touched": []}
result_no_criteria = verify_criteria(task_no_criteria, PROJECT_ROOT)
check("no criteria key: no crash", result_no_criteria is not None)
check("no criteria key: zero results", len(result_no_criteria["criteria_results"]) == 0)


# ══════════════════════════════════════════════════════════════
# 4B: Decomposition Gate (decomposition_gate.py)
# ══════════════════════════════════════════════════════════════

print("\n=== 4B: Decomposition Gate ===")

from lib.decomposition_gate import (
    check_decomposition,
    _check_task_size,
    _check_cross_cluster,
    _check_file_ownership,
    _build_dep_graph,
    TASK_SIZE_WARN,
    TASK_SIZE_FAIL,
    CROSS_CLUSTER_FAIL,
)

# -- _build_dep_graph --

tasks_dep = [
    {"id": "a", "depends_on": []},
    {"id": "b", "depends_on": ["a"]},
    {"id": "c", "depends_on": ["a", "b"]},
]
dep_graph = _build_dep_graph(tasks_dep)
check("dep_graph: a depended by b and c", dep_graph.get("a") == {"b", "c"})
check("dep_graph: b depended by c", dep_graph.get("b") == {"c"})
check("dep_graph: c not depended", "c" not in dep_graph)

# String depends_on (legacy)
tasks_str_dep = [
    {"id": "x", "depends_on": "y"},
    {"id": "y", "depends_on": []},
]
dep_graph_str = _build_dep_graph(tasks_str_dep)
check("dep_graph: string depends_on", dep_graph_str.get("y") == {"x"})

# -- _check_task_size --

pm_for_size = {
    "files": [
        {"path": "small.py", "lines": 100},
        {"path": "medium.py", "lines": 2000},
        {"path": "large.py", "lines": 4000},
        {"path": "huge.py", "lines": 6000},
    ],
}

# Pass: small task
size_pass = _check_task_size(
    {"id": "s1", "files_touched": ["small.py"]}, pm_for_size)
check("size: small → pass", size_pass["verdict"] == "pass")
check("size: small total lines", size_pass["total_lines"] == 100)

# Warn: medium task
size_warn = _check_task_size(
    {"id": "s2", "files_touched": ["medium.py", "large.py"]}, pm_for_size)
check("size: 6000 lines → fail", size_warn["verdict"] == "fail",
      f"got {size_warn['verdict']} for {size_warn['total_lines']}")

# Fail: huge task
size_fail = _check_task_size(
    {"id": "s3", "files_touched": ["huge.py"]}, pm_for_size)
check("size: 6000 → fail", size_fail["verdict"] == "fail")

# Warn threshold
size_warn_exact = _check_task_size(
    {"id": "s4", "files_touched": ["medium.py", "small.py"]}, pm_for_size)
# 2100 < 3000, so pass
check("size: 2100 → pass", size_warn_exact["verdict"] == "pass")

# -- _check_cross_cluster --

csg_clusters = {
    "nodes": [],
    "edges": [],
    "clusters": [
        {"id": "c0", "files": ["a.py", "b.py"], "symbols": []},
        {"id": "c1", "files": ["c.py", "d.py"], "symbols": []},
    ],
    "cluster_edges": [
        {"from": "c0", "to": "c1", "edge_count": 5},
    ],
}

# Task within one cluster
cc_pass = _check_cross_cluster(
    {"id": "cc1", "files_touched": ["a.py", "b.py"]}, csg_clusters)
check("cross_cluster: within one → pass", cc_pass["verdict"] == "pass")
check("cross_cluster: 1 cluster", cc_pass["clusters_touched"] == 1)

# Task across clusters, below threshold
cc_low = _check_cross_cluster(
    {"id": "cc2", "files_touched": ["a.py", "c.py"]}, csg_clusters)
check("cross_cluster: 5 edges → pass", cc_low["verdict"] == "pass")
check("cross_cluster: 2 clusters", cc_low["clusters_touched"] == 2)
check("cross_cluster: 5 edges counted", cc_low["cross_cluster_edges"] == 5)

# Task across clusters, above threshold
csg_many_edges = dict(csg_clusters)
csg_many_edges["cluster_edges"] = [{"from": "c0", "to": "c1", "edge_count": 20}]
cc_fail = _check_cross_cluster(
    {"id": "cc3", "files_touched": ["a.py", "c.py"]}, csg_many_edges)
check("cross_cluster: 20 edges → fail", cc_fail["verdict"] == "fail")

# -- _check_file_ownership --

tasks_overlap = [
    {"id": "o1", "files_touched": ["shared.py", "own1.py"], "depends_on": []},
    {"id": "o2", "files_touched": ["shared.py", "own2.py"], "depends_on": []},
]
dep_g = _build_dep_graph(tasks_overlap)
own = _check_file_ownership(tasks_overlap, dep_g)
check("ownership: violation found", len(own["violations"]) > 0)
check("ownership: shared.py in violation",
      any(v["file"] == "shared.py" for v in own["violations"]))

# With dependency → no violation
tasks_with_dep = [
    {"id": "d1", "files_touched": ["shared.py"], "depends_on": []},
    {"id": "d2", "files_touched": ["shared.py"], "depends_on": ["d1"]},
]
dep_g2 = _build_dep_graph(tasks_with_dep)
own2 = _check_file_ownership(tasks_with_dep, dep_g2)
check("ownership: with dep → no violation", len(own2["violations"]) == 0)

# Disjoint files → no violation
tasks_disjoint = [
    {"id": "j1", "files_touched": ["a.py"], "depends_on": []},
    {"id": "j2", "files_touched": ["b.py"], "depends_on": []},
]
own3 = _check_file_ownership(tasks_disjoint, _build_dep_graph(tasks_disjoint))
check("ownership: disjoint → no violation", len(own3["violations"]) == 0)

# -- check_decomposition (full) --

decomp_tasks = [
    {"id": "d1", "files_touched": ["small.py"], "depends_on": []},
    {"id": "d2", "files_touched": ["small.py"], "depends_on": ["d1"]},
]
decomp_result = check_decomposition(decomp_tasks, pm_for_size, csg=csg_clusters)
check("decomp: returns dict", isinstance(decomp_result, dict))
check("decomp: has overall", "overall" in decomp_result)
check("decomp: has per_task", "per_task" in decomp_result)
check("decomp: has file_ownership", "file_ownership" in decomp_result)
check("decomp: has warnings", "warnings" in decomp_result)

# Without CSG (degraded mode)
decomp_no_csg = check_decomposition(decomp_tasks, pm_for_size, csg=None)
check("decomp no CSG: no crash", decomp_no_csg is not None)
# Should have skipped checks in per_task
for pt in decomp_no_csg["per_task"]:
    skipped = [c for c in pt["checks"] if c.get("verdict") == "skipped"]
    check(f"decomp no CSG: task {pt['task_id']} has skipped checks",
          len(skipped) == 2, f"got {len(skipped)}")


# ══════════════════════════════════════════════════════════════
# 4C: Failure Classify (failure_classify.py)
# ══════════════════════════════════════════════════════════════

print("\n=== 4C: Failure Classify ===")

from lib.failure_classify import classify_failure, aggregate_classifications

# Rule 1: Context cut
fc1 = classify_failure(
    budget={"cuts_made": [{"file": "lib/big.py"}]},
    agent_output="I tried to read lib/big.py but it wasn't available",
)
check("fc rule1: context_cut", fc1["class"] == "pipeline")
check("fc rule1: subclass", fc1["subclass"] == "context_cut")

# Rule 1: cuts but no reference → skip
fc1_no_ref = classify_failure(
    budget={"cuts_made": [{"file": "lib/big.py"}]},
    agent_output="Everything went fine",
)
check("fc rule1: no reference → not context_cut",
      fc1_no_ref["subclass"] != "context_cut")

# Rule 2: Exploration death
exploration_output = "\n".join([
    "Read file lib/a.py",
    "Searching for something",
    "Let me check another file",
    "Reading file lib/b.py",
    "I need to find the class",
    "Let me search for it",
    "Looking at lib/c.py",
    "Let me read this one",
    "Searching for patterns",
    "Read file lib/d.py",
    "I'll look at another",
    "Let me check lib/e.py",
])
fc2 = classify_failure(agent_output=exploration_output)
check("fc rule2: exploration_death", fc2["subclass"] == "exploration_death")

# Rule 3: Decomposition error
fc3 = classify_failure(
    gate_results={
        "scope": {"undeclared_files": ["a.py", "b.py", "c.py", "d.py"]},
    },
    task={"files_touched": ["x.py"]},
)
check("fc rule3: decomposition_error", fc3["class"] == "pipeline")
check("fc rule3: subclass", fc3["subclass"] == "decomposition_error")

# Rule 3: not enough undeclared → skip
fc3_small = classify_failure(
    gate_results={
        "scope": {"undeclared_files": ["a.py"]},
    },
    task={"files_touched": ["x.py", "y.py"]},
)
check("fc rule3: small undeclared → not decomp error",
      fc3_small["subclass"] != "decomposition_error")

# Rule 4: Spec gap
fc4 = classify_failure(
    agent_output="I cannot determine the spec requirement for this feature. The spec is unclear.",
)
check("fc rule4: spec_gap", fc4["subclass"] in ("ambiguous_spec", "missing_dependency"))

# Rule 4: missing dependency
fc4b = classify_failure(
    agent_output="This task is blocked by a missing dependency that hasn't been implemented yet.",
)
check("fc rule4b: missing_dependency", fc4b["subclass"] == "missing_dependency")

# Rule 5: Exceeded capacity (timeout + escalation)
fc5 = classify_failure(escalated=True, timed_out=True)
check("fc rule5: exceeded_capacity", fc5["class"] == "complexity")
check("fc rule5: subclass", fc5["subclass"] == "exceeded_capacity")
check("fc rule5: evidence mentions escalation", "escalation" in fc5["evidence"])

# Rule 5: timeout only
fc5b = classify_failure(timed_out=True)
check("fc rule5b: timeout only → exceeded_capacity", fc5b["subclass"] == "exceeded_capacity")

# Rule 6: Implementation error
fc6 = classify_failure(
    gate_results={
        "checks": [
            {"name": "lint", "status": "fail"},
            {"name": "test", "status": "fail"},
        ],
    },
)
check("fc rule6: implementation_error", fc6["class"] == "complexity")
check("fc rule6: subclass", fc6["subclass"] == "implementation_error")

# Rule 3b: Ownership violations → decomposition_error
fc3_own = classify_failure(
    gate_results={
        "scope": {"ownership_violations": ["src/panel.tsx (task 6)"]},
    },
    task={"files_touched": ["src/app.tsx"]},
)
check("fc rule3b: ownership → decomposition_error", fc3_own["class"] == "pipeline")
check("fc rule3b: subclass", fc3_own["subclass"] == "decomposition_error")
check("fc rule3b: evidence mentions owned", "owned by other tasks" in fc3_own["evidence"])

# Rule 3b via checks array (when scope is not in flat keys)
fc3_own_checks = classify_failure(
    gate_results={
        "checks": [
            {"name": "scope", "status": "fail",
             "ownership_violations": ["src/modal.tsx (task 7)", "src/utils.ts (task 2)"]},
        ],
    },
    task={"files_touched": ["src/app.tsx"]},
)
check("fc rule3b checks: decomposition_error", fc3_own_checks["subclass"] == "decomposition_error")
check("fc rule3b checks: evidence count", "2 file(s)" in fc3_own_checks["evidence"])

# Rule 3b takes priority over undeclared files
fc3_own_priority = classify_failure(
    gate_results={
        "scope": {
            "ownership_violations": ["src/panel.tsx (task 6)"],
            "undeclared_files": ["a.py", "b.py", "c.py", "d.py"],
        },
    },
    task={"files_touched": ["src/app.tsx"]},
)
check("fc rule3b priority: ownership over undeclared",
      "owned by other tasks" in fc3_own_priority["evidence"])

# No match → unclassified
fc_none = classify_failure()
check("fc no match: unclassified", fc_none["class"] == "unclassified")

# All args None/empty
fc_empty = classify_failure(budget=None, gate_results=None, agent_output="", task=None)
check("fc empty: no crash", fc_empty is not None)

# -- aggregate_classifications --

classifications = [
    {"class": "pipeline", "subclass": "context_cut"},
    {"class": "pipeline", "subclass": "decomposition_error"},
    {"class": "complexity", "subclass": "implementation_error"},
    {"class": "pipeline", "subclass": "context_cut"},
]
agg = aggregate_classifications(classifications)
check("agg: total_failures", agg["total_failures"] == 4)
check("agg: pipeline_failures", agg["pipeline_failures"] == 3)
check("agg: complexity_failures", agg["complexity_failures"] == 1)
check("agg: has breakdown", "pipeline:context_cut" in agg["breakdown"])
check("agg: context_cut count", agg["breakdown"]["pipeline:context_cut"] == 2)
check("agg: pipeline_ratio", agg["pipeline_ratio"] == 0.75)

# Empty list
agg_empty = aggregate_classifications([])
check("agg empty: total 0", agg_empty["total_failures"] == 0)
check("agg empty: ratio 0", agg_empty["pipeline_ratio"] == 0)


# ══════════════════════════════════════════════════════════════
# 4D: Contract Verify (contract_verify.py)
# ══════════════════════════════════════════════════════════════

print("\n=== 4D: Contract Verify ===")

from lib.contract_verify import (
    _infer_entity_type,
    verify_file_entity,
    verify_function_entity,
    verify_database_entity,
    verify_contract,
)

# -- _infer_entity_type --

check("infer type: explicit type", _infer_entity_type({"type": "file"}) == "file")
check("infer type: table with path", _infer_entity_type({"table": "lib/foo.py"}) == "file")
check("infer type: table with colon", _infer_entity_type({"table": "lib/foo.py:func"}) == "function")
check("infer type: plain table name", _infer_entity_type({"table": "users"}) == "database")
check("infer type: no table", _infer_entity_type({}) == "database")

# -- verify_file_entity --

# Real file
fe_real = verify_file_entity({"path": "lib/context/utils.py", "name": "utils"}, PROJECT_ROOT)
check("file entity: real file passes", fe_real[0]["passed"])

# Missing file
fe_missing = verify_file_entity({"path": "nonexistent_xyz.py", "name": "missing"}, PROJECT_ROOT)
check("file entity: missing file fails", not fe_missing[0]["passed"])

# Parameterized path
fe_param = verify_file_entity(
    {"path": "lib/<name>/utils.py", "name": "param"},
    PROJECT_ROOT,
)
check("file entity: param path checks parent", fe_param[0] is not None)
# lib/ exists, so parent should be found
check("file entity: param parent exists", fe_param[0]["passed"])

# No path
fe_no_path = verify_file_entity({"name": "no-path"}, PROJECT_ROOT)
check("file entity: no path fails", not fe_no_path[0]["passed"])

# -- verify_function_entity --

# Function in real file
fn_real = verify_function_entity(
    {"path": "lib/context/utils.py", "function": "read_json", "name": "read_json"},
    PROJECT_ROOT,
)
check("func entity: found symbol", fn_real[0]["passed"])

# Function not in file
fn_missing = verify_function_entity(
    {"path": "lib/context/utils.py", "function": "nonexistent_function_xyz", "name": "missing"},
    PROJECT_ROOT,
)
check("func entity: missing symbol", not fn_missing[0]["passed"])

# File doesn't exist
fn_no_file = verify_function_entity(
    {"path": "nonexistent.py", "function": "foo", "name": "missing"},
    PROJECT_ROOT,
)
check("func entity: missing file", not fn_no_file[0]["passed"])

# Legacy table:func format
fn_legacy = verify_function_entity(
    {"table": "lib/context/utils.py:read_json", "name": "legacy"},
    PROJECT_ROOT,
)
check("func entity: legacy format", fn_legacy[0]["passed"])

# -- verify_database_entity --

# With path (delegates to function entity)
db_with_path = verify_database_entity(
    {"path": "lib/context/utils.py", "name": "Utils", "function": "read_json"},
    PROJECT_ROOT,
)
check("db entity: with path", db_with_path[0]["passed"])

# Without path (legacy — always passes with advisory)
db_no_path = verify_database_entity(
    {"table": "users", "name": "User"},
    PROJECT_ROOT,
)
check("db entity: no path → passes", db_no_path[0]["passed"])
check("db entity: advisory message", "not verifiable" in db_no_path[0]["detail"])

# -- verify_contract --

# Empty entities → fail
contract_empty = {"entities": []}
cv_empty = verify_contract(contract_empty, PROJECT_ROOT)
check("contract: empty entities fails", not cv_empty[0]["passed"])

# Mixed entities
contract_mixed = {
    "entities": [
        {"name": "utils", "type": "file", "path": "lib/context/utils.py"},
        {"name": "read_json", "type": "function", "path": "lib/context/utils.py", "function": "read_json"},
        {"name": "User", "type": "database", "table": "users"},
    ],
}
cv_mixed = verify_contract(contract_mixed, PROJECT_ROOT)
check("contract: mixed has results", len(cv_mixed) >= 3)
check("contract: file entity passed", cv_mixed[0]["passed"])
check("contract: function entity passed", cv_mixed[1]["passed"])

# With CSG enhancement
csg_for_cv = {
    "nodes": [
        {"name": "read_json", "kind": "function", "file": "lib/context/utils.py", "line": 10},
        {"name": "User", "kind": "class", "file": "models/user.py", "line": 1,
         "schema": {"columns": [{"name": "id"}, {"name": "email"}]}},
    ],
}
contract_csg = {
    "entities": [
        {"name": "read_json", "type": "function", "path": "lib/context/utils.py", "function": "read_json"},
        {"name": "User", "type": "database", "path": "models/user.py",
         "key_fields": ["id", "email", "missing_field"]},
    ],
}
cv_csg = verify_contract(contract_csg, PROJECT_ROOT, csg=csg_for_cv)
check("contract CSG: has CSG results", len(cv_csg) > 2)
# Should have CSG symbol check for read_json
csg_checks = [r for r in cv_csg if "CSG" in r["check"]]
check("contract CSG: CSG checks present", len(csg_checks) > 0)

# CSG schema: id and email should pass, missing_field should fail
col_checks = [r for r in cv_csg if "CSG column" in r["check"]]
if col_checks:
    id_check = [r for r in col_checks if "id" in r["check"] and "missing" not in r["check"]]
    missing_check = [r for r in col_checks if "missing_field" in r["check"]]
    if id_check:
        check("contract CSG: id column passes", id_check[0]["passed"])
    if missing_check:
        check("contract CSG: missing_field fails", not missing_check[0]["passed"])


# ══════════════════════════════════════════════════════════════
# 4E: Spec Traceability (spec_traceability.py)
# ══════════════════════════════════════════════════════════════

print("\n=== 4E: Spec Traceability ===")

from lib.spec_traceability import (
    spec_to_task_check,
    _extract_requirements,
    _build_coverage_index,
    _find_covering_tasks,
    format_uncovered_for_verifier,
)

# -- _extract_requirements --

spec_text = """\
# Product Spec

## Authentication

- The system MUST support JWT-based authentication for all API endpoints
- Users must be able to reset their password via email
- Each session should expire after 30 minutes of inactivity

## Data Model

- The User model MUST have email, password_hash, and created_at fields
- A Book model shall have title, author, and ISBN fields

## API

Short bullet not a requirement.
The API MUST return proper HTTP status codes for all error responses.
"""

reqs = _extract_requirements(spec_text)
check("extract reqs: found requirements", len(reqs) > 0, f"got {len(reqs)}")
check("extract reqs: has section info",
      all(r.get("section") for r in reqs))

# Should find MUST/shall/should requirements
req_texts = [r["text"] for r in reqs]
check("extract reqs: JWT requirement found",
      any("JWT" in t for t in req_texts))
check("extract reqs: password reset found",
      any("password" in t.lower() for t in req_texts))
check("extract reqs: HTTP status codes found",
      any("HTTP status" in t for t in req_texts))

# Empty spec
reqs_empty = _extract_requirements("")
check("extract reqs: empty spec → empty", len(reqs_empty) == 0)

# -- _build_coverage_index --

index_tasks = [
    {
        "id": "t1",
        "description": "Create JWT authentication",
        "title": "Auth system",
        "spec_references": [{"spec": "spec.md", "section": "Authentication"}],
        "files_touched": ["lib/auth.py"],
        "acceptance_criteria": [
            {"criterion": "JWT tokens generated correctly", "verify_by": "test"},
        ],
    },
    {
        "id": "t2",
        "description": "Create User model with email and password_hash",
        "title": "User model",
        "spec_references": [{"spec": "spec.md", "section": "Data Model"}],
        "files_touched": ["models/user.py"],
        "acceptance_criteria": [],
    },
]
idx = _build_coverage_index(index_tasks)
check("coverage index: has spec_refs", len(idx["spec_refs"]) > 0)
check("coverage index: has files", "lib/auth.py" in idx["files"])
check("coverage index: has desc_text", "jwt" in idx["desc_text"])
check("coverage index: has entities", len(idx["entities"]) > 0)

# -- spec_to_task_check --

result = spec_to_task_check(spec_text, index_tasks)
check("spec_to_task: returns dict", isinstance(result, dict))
check("spec_to_task: has requirements_found", "requirements_found" in result)
check("spec_to_task: has covered", "covered" in result)
check("spec_to_task: has uncovered", "uncovered" in result)
check("spec_to_task: has coverage_ratio", "coverage_ratio" in result)
check("spec_to_task: some covered", len(result["covered"]) > 0,
      f"got {len(result['covered'])}")
check("spec_to_task: ratio between 0 and 1",
      0 <= result["coverage_ratio"] <= 1)

# Empty spec
result_empty = spec_to_task_check("", index_tasks)
check("spec_to_task: empty spec → ratio 1.0",
      result_empty["coverage_ratio"] == 1.0)

# No tasks
result_no_tasks = spec_to_task_check(spec_text, [])
check("spec_to_task: no tasks → has uncovered",
      len(result_no_tasks.get("uncovered", [])) > 0)

# -- format_uncovered_for_verifier --

trace_result = {
    "requirements_found": 5,
    "covered": [{"requirement": "r1"}],
    "uncovered": [
        {"requirement": "Book model needed", "section": "Data Model"},
        {"requirement": "API error codes", "section": "API"},
    ],
    "coverage_ratio": 0.60,
}
formatted = format_uncovered_for_verifier(trace_result)
check("format: returns string", isinstance(formatted, str))
check("format: has coverage section", "Spec Coverage Analysis" in formatted)
check("format: has ratio", "60%" in formatted)
check("format: has uncovered reqs", "Book model" in formatted)
check("format: has section prefix", "[Data Model]" in formatted)

# No uncovered
formatted_all = format_uncovered_for_verifier({"uncovered": [], "coverage_ratio": 1.0, "requirements_found": 5})
check("format: no uncovered → empty", formatted_all == "")

# -- code_to_spec_check (basic smoke test) --

from lib.spec_traceability import code_to_spec_check

# With real tasks that have structured criteria
tasks_for_c2s = [
    {
        "id": "c2s-1",
        "acceptance_criteria": [
            {"criterion": 'File "lib/context/utils.py" exists', "verify_by": "file_exists"},
            {"criterion": "Manual check needed", "verify_by": "manual"},
        ],
        "files_touched": ["lib/context/utils.py"],
    },
]
c2s = code_to_spec_check(tasks_for_c2s, PROJECT_ROOT)
check("code_to_spec: returns dict", isinstance(c2s, dict))
check("code_to_spec: has total_criteria", "total_criteria" in c2s)
check("code_to_spec: has per_task", "per_task" in c2s)
check("code_to_spec: has coverage_ratio", "coverage_ratio" in c2s)

# Tasks with no criteria
c2s_empty = code_to_spec_check([{"id": "x"}], PROJECT_ROOT)
check("code_to_spec: no criteria → 0 total", c2s_empty["total_criteria"] == 0)


# ══════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════

print(f"\n{'='*60}")
print(f"Layer 3 + Verification Unit Tests: {passed} passed, {failed} failed")
if failed == 0:
    print("ALL TESTS PASSED")
else:
    print(f"FAILURES: {failed}")
    sys.exit(1)
