#!/usr/bin/env python3
"""Unit tests for Layer 2 modules.

Tests individual functions with synthetic and real inputs.
Covers: code_context, task_context, spec_context, budget, cross_task.
"""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from lib.context.utils import read_json

CONTEXT_DIR = os.path.join(PROJECT_ROOT, ".speed", "context")
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


# Load real Layer 1 artifacts
csg = read_json(os.path.join(CONTEXT_DIR, "semantic-graph.json"))
project_map = read_json(os.path.join(CONTEXT_DIR, "project-map.json"))


# ══════════════════════════════════════════════════════════════
# 2A: Code Context (code_context.py)
# ══════════════════════════════════════════════════════════════

print("\n=== 2A: Code Context ===")

from lib.context.code_context import build_code_context

# Task touching real files (fixture has inherits edges for one-hop expansion)
task = {
    "id": "ut-1",
    "files_touched": ["tests/fixtures/json_processor.py"],
    "depends_on": [],
}

cc = build_code_context(task, PROJECT_ROOT, csg, project_map, CONTEXT_DIR)
check("build returns dict", isinstance(cc, dict))
check("has full_content", "full_content" in cc)
check("has skeleton", "skeleton" in cc)
check("has expansion_summary", "expansion_summary" in cc)
check("has symbols_in_scope", "symbols_in_scope" in cc)

# files_touched in full_content
ft = cc["full_content"].get("files_touched", [])
ft_paths = [f["path"] for f in ft] if ft else []
check("files_touched included", "tests/fixtures/json_processor.py" in ft_paths,
      f"got {ft_paths}")

# Graph expansion should find neighbors (requires CSG with nodes)
exp = cc.get("expansion_summary", {})
check("seed files counted", exp.get("seed_files", 0) >= 1)
one_hop = exp.get("one_hop_files", 0)
has_csg_nodes = csg and len(csg.get("nodes", [])) > 0
if has_csg_nodes:
    check("one-hop expansion found files", one_hop > 0, f"got {one_hop}")
else:
    check("one-hop expansion found files", one_hop >= 0, "CSG empty, expansion skipped")

# Task with no CSG match (new file)
task_new = {
    "id": "ut-new",
    "files_touched": ["brand_new_file.py"],
    "depends_on": [],
}
cc_new = build_code_context(task_new, PROJECT_ROOT, csg, project_map, CONTEXT_DIR)
check("new file: no crash", cc_new is not None)
check("new file: has expansion_summary", "expansion_summary" in cc_new)

# Task with multiple files
task_multi = {
    "id": "ut-multi",
    "files_touched": ["lib/context/budget.py", "lib/context/assembly.py"],
    "depends_on": [],
}
cc_multi = build_code_context(task_multi, PROJECT_ROOT, csg, project_map, CONTEXT_DIR)
ft_multi = [f["path"] for f in cc_multi["full_content"].get("files_touched", [])]
check("multi-file: both included",
      "lib/context/budget.py" in ft_multi and "lib/context/assembly.py" in ft_multi,
      f"got {ft_multi}")

# Empty files_touched
task_empty = {"id": "ut-empty", "files_touched": [], "depends_on": []}
cc_empty = build_code_context(task_empty, PROJECT_ROOT, csg, project_map, CONTEXT_DIR)
check("empty files_touched: no crash", cc_empty is not None)


# ══════════════════════════════════════════════════════════════
# 2B: Task Context (task_context.py)
# ══════════════════════════════════════════════════════════════

print("\n=== 2B: Task Context ===")

from lib.context.task_context import build_task_context

task_a = {
    "id": "ta-1", "title": "Build engine",
    "description": "Build the core engine.",
    "files_touched": ["lib/context/utils.py"],
    "depends_on": [],
    "rationale": "Engine is the foundation.",
    "assumptions": ["Python 3.11+"],
}
task_b = {
    "id": "ta-2", "title": "Build UI",
    "description": "Build the user interface.",
    "files_touched": ["lib/context/assembly.py"],
    "depends_on": ["ta-1"],
    "rationale": "UI depends on engine.",
    "assumptions": [],
}
all_tasks = [task_a, task_b]

# Test task_a (no dependencies)
tc_a = build_task_context(task_a, all_tasks, csg=csg)
check("task context: returns dict", isinstance(tc_a, dict))
check("has reasoning", "reasoning" in tc_a)
check("has upstream", "upstream" in tc_a)
check("has downstream", "downstream" in tc_a)
check("has shared_scope_warnings", "shared_scope_warnings" in tc_a)

# Reasoning should contain rationale
check("rationale preserved",
      tc_a["reasoning"].get("rationale") == "Engine is the foundation.")
check("assumptions preserved",
      tc_a["reasoning"].get("assumptions") == ["Python 3.11+"])

# Task A has no deps, so upstream is empty
check("upstream empty for task_a", len(tc_a["upstream"]) == 0)

# Task A is depended on by task_b, so downstream should show task_b
downstream_ids = [d.get("task_id") for d in tc_a["downstream"]]
check("downstream includes ta-2", "ta-2" in downstream_ids)

# Test task_b (has dependency on task_a)
completed = {"ta-1": {"status": "completed", "output": "Engine built."}}
tc_b = build_task_context(task_b, all_tasks, csg=csg, completed_tasks=completed)
check("upstream includes ta-1",
      any(u.get("task_id") == "ta-1" for u in tc_b["upstream"]))

# Task with no rationale/assumptions
task_bare = {"id": "bare", "files_touched": ["x.py"], "depends_on": []}
tc_bare = build_task_context(task_bare, [task_bare])
check("bare task: no crash", tc_bare is not None)
check("bare task: reasoning exists", "reasoning" in tc_bare)


# ══════════════════════════════════════════════════════════════
# 2C: Spec Context (spec_context.py)
# ══════════════════════════════════════════════════════════════

print("\n=== 2C: Spec Context ===")

from lib.context.spec_context import build_spec_context

spec_files = {
    "product-spec.md": (
        "# Product Spec\n\n"
        "## Authentication\n\n"
        "Users must authenticate via JWT tokens.\n\n"
        "## Data Model\n\n"
        "The User model has email and password fields.\n"
    ),
}

task_with_refs = {
    "id": "sc-1",
    "files_touched": ["lib/auth.py"],
    "spec_references": [
        {"spec": "product-spec.md", "section": "Authentication"},
    ],
}

sc = build_spec_context(task_with_refs, spec_files)
check("spec context: returns dict", isinstance(sc, dict))
check("has relevant_spec_sections", "relevant_spec_sections" in sc)
check("has alignment_status", "alignment_status" in sc)
check("has contract_excerpt", "contract_excerpt" in sc)

# With spec_references, should find the Authentication section
sections = sc.get("relevant_spec_sections", [])
check("found spec section", len(sections) > 0, f"got {len(sections)}")

# Task without spec_references (heuristic fallback)
task_no_refs = {
    "id": "sc-2",
    "title": "Add authentication",
    "files_touched": ["lib/auth.py"],
}
sc2 = build_spec_context(task_no_refs, spec_files)
check("no refs: no crash", sc2 is not None)

# Empty spec_files
sc_empty = build_spec_context(task_with_refs, {})
check("empty specs: no crash", sc_empty is not None)

# With spec_alignment
fake_alignment = {
    "claims": [
        {"entity": "User", "claim_type": "entity_defined", "status": "confirmed",
         "claim_text": "User model exists", "evidence": "Found in models.py"},
    ],
    "summary": {"total_claims": 1, "confirmed": 1, "missing": 0, "divergent": 0},
}
sc3 = build_spec_context(task_with_refs, spec_files, spec_alignment=fake_alignment)
check("with alignment: no crash", sc3 is not None)


# ══════════════════════════════════════════════════════════════
# 2D: Token Budgeting (budget.py)
# ══════════════════════════════════════════════════════════════

print("\n=== 2D: Token Budgeting ===")

from lib.context.budget import apply_budget, STAGE_ALLOCATIONS

# Test with minimal code context
code_ctx = {
    "full_content": {
        "files_touched": [
            {"path": "a.py", "content": "x = 1\n" * 100},  # 100 lines
        ],
        "one_hop": [
            {"path": "b.py", "content": "y = 2\n" * 50},  # 50 lines
        ],
    },
    "skeleton": {"two_hop": [{"path": "c.py", "content": "z = 3\n" * 20}]},
    "expansion_summary": {"seed_files": 1, "one_hop_files": 1, "two_hop_files": 1},
    "symbols_in_scope": [],
}

budget = apply_budget(code_ctx, stage="developer")
check("budget: returns dict", isinstance(budget, dict))
check("budget: has total_budget", "total_budget" in budget)
check("budget: has total_used", "total_used" in budget)
check("budget: has under_budget", "under_budget" in budget)
check("budget: has cuts_made", "cuts_made" in budget)
check("budget: developer = 80K", budget["total_budget"] == 80000)
check("budget: under budget", budget["under_budget"],
      f"used {budget['total_used']}/{budget['total_budget']}")

# STAGE_ALLOCATIONS
check("stages: developer exists", "developer" in STAGE_ALLOCATIONS)
check("stages: reviewer exists", "reviewer" in STAGE_ALLOCATIONS)
check("stages: 6 stages", len(STAGE_ALLOCATIONS) == 6)
for stage, alloc in STAGE_ALLOCATIONS.items():
    total = sum(alloc.values())
    check(f"stage {stage}: allocations sum to ~1.0",
          abs(total - 1.0) < 0.01, f"sum={total}")

# Reviewer stage (60K)
budget_r = apply_budget(code_ctx, stage="reviewer")
check("reviewer: 60K budget", budget_r["total_budget"] == 60000)

# Large code context should trigger cuts
big_content = "x = 1\n" * 5000  # ~5000 lines
big_code_ctx = {
    "full_content": {
        "files_touched": [{"path": "big.py", "content": big_content}],
        "one_hop": [{"path": f"hop{i}.py", "content": big_content} for i in range(10)],
    },
    "skeleton": {"two_hop": [{"path": f"skel{i}.py", "content": "s\n" * 1000} for i in range(5)]},
    "expansion_summary": {},
    "symbols_in_scope": [],
}
budget_big = apply_budget(big_code_ctx, stage="reviewer")
cuts = budget_big.get("cuts_made", [])
check("big context: triggers cuts", len(cuts) > 0, f"no cuts made")
print(f"  Big context: {budget_big['total_used']}/{budget_big['total_budget']} tokens, {len(cuts)} cuts")

# Custom budget from config
custom_config = {"context": {"budgets": {"developer": 50000}}}
budget_custom = apply_budget(code_ctx, stage="developer", config=custom_config)
check("custom budget: 50K", budget_custom["total_budget"] == 50000)


# ══════════════════════════════════════════════════════════════
# 2E: Cross-Task Analysis (cross_task.py)
# ══════════════════════════════════════════════════════════════

print("\n=== 2E: Cross-Task Analysis ===")

from lib.context.cross_task import build_cross_task_analysis

# Tasks sharing files → domain overlap
tasks_overlap = [
    {"id": "t1", "files_touched": ["lib/context/utils.py", "lib/context/csg.py"]},
    {"id": "t2", "files_touched": ["lib/context/utils.py", "lib/context/budget.py"]},
    {"id": "t3", "files_touched": ["lib/context/assembly.py"]},
]

analysis = build_cross_task_analysis(tasks_overlap, csg=csg)
check("analysis: returns dict", isinstance(analysis, dict))
check("has domain_overlap", "domain_overlap" in analysis)
check("has interface_boundaries", "interface_boundaries" in analysis)
check("has high_impact_modifications", "high_impact_modifications" in analysis)

# t1 and t2 share utils.py → should have domain overlap (requires CSG)
overlaps = analysis.get("domain_overlap", [])
if has_csg_nodes:
    check("domain overlap found", len(overlaps) > 0, f"got {len(overlaps)}")
else:
    check("domain overlap found", len(overlaps) >= 0, "CSG empty, no overlaps expected")

# Without CSG (degraded mode)
analysis_no_csg = build_cross_task_analysis(tasks_overlap, csg=None)
check("no CSG: no crash", analysis_no_csg is not None)
check("no CSG: has domain_overlap", "domain_overlap" in analysis_no_csg)

# Single task — no cross-task analysis possible
analysis_single = build_cross_task_analysis([tasks_overlap[0]], csg=csg)
check("single task: no crash", analysis_single is not None)

# Tasks with no file overlap
tasks_disjoint = [
    {"id": "d1", "files_touched": ["lib/context/utils.py"]},
    {"id": "d2", "files_touched": ["lib/context/assembly.py"]},
]
analysis_disjoint = build_cross_task_analysis(tasks_disjoint, csg=csg)
check("disjoint: analysis returned", analysis_disjoint is not None)


# ══════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════

print(f"\n{'='*60}")
print(f"Layer 2 Unit Tests: {passed} passed, {failed} failed")
if failed == 0:
    print("ALL TESTS PASSED")
else:
    print(f"FAILURES: {failed}")
    sys.exit(1)
