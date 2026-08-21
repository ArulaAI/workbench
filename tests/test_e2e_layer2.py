#!/usr/bin/env python3
"""End-to-end test: Layer 2 build for a realistic task against real Layer 1 artifacts."""

import json
import os
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from lib.context.layer2 import build_task_context_package, build_feature_cross_task
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


# ── Load Layer 1 artifacts ───────────────────────────────────
print("=== Loading Layer 1 Artifacts ===")
csg = read_json(os.path.join(CONTEXT_DIR, "semantic-graph.json"))
project_map = read_json(os.path.join(CONTEXT_DIR, "project-map.json"))
check("CSG loaded", csg is not None and len(csg.get("nodes", [])) > 0)
check("project map loaded", project_map is not None and len(project_map.get("files", [])) > 0)


# ── Define a realistic task ──────────────────────────────────
# This task simulates modifying the budget module, which touches real files
task_a = {
    "id": "e2e-task-1",
    "title": "Enhance token budget allocation with per-section limits",
    "description": (
        "Add per-section budget allocation to the token budgeting system. "
        "Each section (code, task, spec) gets a proportional share of the "
        "total stage budget. Sections that don't use their allocation "
        "donate the remainder to other sections."
    ),
    "files_touched": [
        "lib/context/budget.py",
        "lib/context/utils.py",
    ],
    "depends_on": [],
    "acceptance_criteria": [
        {
            "criterion": "budget.py exports a per_section_allocate() function",
            "verify_by": "schema_check",
            "target": "lib/context/budget.py:per_section_allocate",
        },
        {
            "criterion": "Token estimation uses get_context_budgets() from utils",
            "verify_by": "file_exists",
            "target": "lib/context/utils.py",
        },
        {
            "criterion": "Developer stage budget is 80,000 tokens by default",
            "verify_by": "test",
            "target": "tests/test_budget.py",
        },
    ],
    "spec_references": [
        {"spec": "tech-spec-context-constructor.md", "section": "Token Budgeting"},
    ],
    "rationale": "Separated from assembly because budget logic is reusable across stages and testable independently.",
    "assumptions": ["Default budgets are sufficient for most projects"],
    "cross_cutting_concerns": ["Token limits affect all assembly functions"],
}

task_b = {
    "id": "e2e-task-2",
    "title": "Update assembly functions to use per-section budgets",
    "description": (
        "Modify all 6 assembly functions in assembly.py to respect the "
        "per-section budget limits from the enhanced budget module."
    ),
    "files_touched": [
        "lib/context/assembly.py",
    ],
    "depends_on": ["e2e-task-1"],
    "acceptance_criteria": [
        {
            "criterion": "assemble_developer respects per-section budget",
            "verify_by": "test",
            "target": "tests/test_assembly.py",
        },
    ],
    "spec_references": [
        {"spec": "tech-spec-context-constructor.md", "section": "Layer 3"},
    ],
    "rationale": "Depends on task 1 because assembly needs the budget API.",
    "assumptions": [],
    "cross_cutting_concerns": [],
}

all_tasks = [task_a, task_b]


# ── Test 1: Build Layer 2 for task_a ─────────────────────────
print("\n=== Test 1: Layer 2 Build for Task A ===")

t0 = time.time()
result_a = build_task_context_package(
    task=task_a,
    all_tasks=all_tasks,
    project_root=PROJECT_ROOT,
    csg=csg,
    project_map=project_map,
    context_dir=CONTEXT_DIR,
    stage="developer",
)
elapsed = time.time() - t0
print(f"  Build time: {elapsed:.3f}s")

check("task_id correct", result_a["task_id"] == "e2e-task-1")
check("timing present", "timing" in result_a)
check("artifacts present", "artifacts" in result_a)

# Check code-context.json
cc_path = result_a["artifacts"].get("code_context", "")
check("code-context.json created", os.path.exists(cc_path))
if os.path.exists(cc_path):
    cc = read_json(cc_path)
    full = cc.get("full_content", {})
    skel = cc.get("skeleton", {})
    # full_content has sub-keys: files_touched (list of {path, content}) and one_hop
    ft_list = full.get("files_touched", [])
    oh_list = full.get("one_hop", [])
    check("full_content has files_touched", len(ft_list) > 0, f"got {len(ft_list)}")
    # files_touched should contain our declared files
    ft_paths = [f["path"] for f in ft_list if isinstance(f, dict)]
    for ft in task_a["files_touched"]:
        check(f"files_touched '{ft}' in full_content", ft in ft_paths,
              f"missing; got {ft_paths}")
    # Should have expanded to neighboring files via one_hop
    total_files = len(ft_list) + len(oh_list) + len(skel if isinstance(skel, list) else skel.values() if isinstance(skel, dict) else [])
    check("graph expansion found neighbors", total_files > len(task_a["files_touched"]),
          f"only {total_files} files, expected > {len(task_a['files_touched'])}")
    print(f"  Code context: {len(full)} full, {len(skel)} skeleton")

    # Check expansion summary
    exp = cc.get("expansion_summary", {})
    check("expansion summary present", "seed_files" in exp)
    print(f"  Expansion: seed={exp.get('seed_files', 0)}, "
          f"1-hop={exp.get('one_hop_files', 0)}, "
          f"2-hop={exp.get('two_hop_files', 0)}")

# Check task-context.json
tc_path = result_a["artifacts"].get("task_context", "")
check("task-context.json created", os.path.exists(tc_path))
if os.path.exists(tc_path):
    tc = read_json(tc_path)
    check("reasoning present", "reasoning" in tc)
    check("rationale preserved", "Separated from assembly" in
          tc.get("reasoning", {}).get("rationale", ""))
    check("downstream present", "downstream" in tc)
    # Task B depends on Task A, so it should appear in downstream
    downstream = tc.get("downstream", [])
    downstream_ids = [d.get("task_id") for d in downstream]
    check("task B in downstream", "e2e-task-2" in downstream_ids,
          f"downstream ids: {downstream_ids}")
    check("shared_scope_warnings present", "shared_scope_warnings" in tc)

# Check spec-context.json
sc_path = result_a["artifacts"].get("spec_context", "")
check("spec-context.json created", os.path.exists(sc_path))
if os.path.exists(sc_path):
    sc = read_json(sc_path)
    check("spec context has relevant_spec_sections",
          "relevant_spec_sections" in sc)
    check("spec context has alignment_status", "alignment_status" in sc)
    check("spec context has contract_excerpt", "contract_excerpt" in sc)

# Check budget.json
bud_path = result_a["artifacts"].get("budget", "")
check("budget.json created", os.path.exists(bud_path))
if os.path.exists(bud_path):
    bud = read_json(bud_path)
    check("total_budget present", "total_budget" in bud)
    check("total_used present", "total_used" in bud)
    check("under_budget", bud.get("under_budget", False),
          f"used {bud.get('total_used')}/{bud.get('total_budget')}")
    check("budget has developer stage (80K)", bud.get("total_budget", 0) == 80000,
          f"got {bud.get('total_budget')}")
    cuts = bud.get("cuts_made", [])
    print(f"  Budget: {bud.get('total_used', 0)}/{bud.get('total_budget', 0)} tokens, "
          f"{len(cuts)} cuts")


# ── Test 2: Build Layer 2 for task_b (with upstream dependency) ──
print("\n=== Test 2: Layer 2 Build for Task B (with upstream dep) ===")

# Simulate task_a completed with some output
completed_tasks = {
    "e2e-task-1": {
        "status": "completed",
        "output": "Added per_section_allocate function to budget.py. "
                  "Returns dict of section → token_limit.",
        "decisions": ["Used proportional allocation rather than fixed percentages"],
        "concerns": ["Assembly functions must handle zero-budget sections gracefully"],
    }
}

t0 = time.time()
result_b = build_task_context_package(
    task=task_b,
    all_tasks=all_tasks,
    project_root=PROJECT_ROOT,
    csg=csg,
    project_map=project_map,
    context_dir=CONTEXT_DIR,
    completed_tasks=completed_tasks,
    stage="developer",
)
elapsed = time.time() - t0
print(f"  Build time: {elapsed:.3f}s")

check("task_id correct", result_b["task_id"] == "e2e-task-2")

# Check upstream decisions are propagated
tc2_path = result_b["artifacts"].get("task_context", "")
if os.path.exists(tc2_path):
    tc2 = read_json(tc2_path)
    upstream = tc2.get("upstream", [])
    check("upstream present", len(upstream) > 0,
          f"expected upstream from e2e-task-1")
    if upstream:
        upstream_ids = [u.get("task_id") for u in upstream]
        check("e2e-task-1 in upstream", "e2e-task-1" in upstream_ids)


# ── Test 3: Different budget stage (reviewer = 60K) ──────────
print("\n=== Test 3: Reviewer Stage Budget (60K) ===")

result_reviewer = build_task_context_package(
    task=task_a,
    all_tasks=all_tasks,
    project_root=PROJECT_ROOT,
    csg=csg,
    project_map=project_map,
    context_dir=CONTEXT_DIR,
    stage="reviewer",
)

bud_r = read_json(result_reviewer["artifacts"]["budget"])
check("reviewer budget is 60K", bud_r.get("total_budget") == 60000,
      f"got {bud_r.get('total_budget')}")
print(f"  Reviewer budget: {bud_r.get('total_used', 0)}/{bud_r.get('total_budget', 0)} tokens, "
      f"{len(bud_r.get('cuts_made', []))} cuts")


# ── Test 4: Cross-task analysis ──────────────────────────────
print("\n=== Test 4: Cross-Task Analysis ===")

feature_dir = os.path.join(CONTEXT_DIR, "features", "e2e-test")
t0 = time.time()
cross = build_feature_cross_task(all_tasks, csg, feature_dir)
elapsed = time.time() - t0
print(f"  Build time: {elapsed:.3f}s")

check("cross-task analysis returned", cross is not None)
check("domain_overlap present", "domain_overlap" in cross)
check("interface_boundaries present", "interface_boundaries" in cross)
check("high_impact_modifications present", "high_impact_modifications" in cross)

overlaps = cross.get("domain_overlap", [])
boundaries = cross.get("interface_boundaries", [])
high_impact = cross.get("high_impact_modifications", [])
print(f"  Domain overlaps: {len(overlaps)}")
print(f"  Interface boundaries: {len(boundaries)}")
print(f"  High-impact modifications: {len(high_impact)}")

# Task A and B share the lib/context domain, so there should be overlap
# (They touch budget.py, utils.py, assembly.py which are in the same CSG cluster)
check("found some cross-task signals",
      len(overlaps) + len(boundaries) + len(high_impact) > 0,
      "no cross-task signals found")


# ── Test 5: Verify artifact file sizes are reasonable ────────
print("\n=== Test 5: Artifact Sizes ===")

for label, path in result_a["artifacts"].items():
    if os.path.exists(path):
        size = os.path.getsize(path)
        check(f"{label} non-empty", size > 0, f"size={size}")
        check(f"{label} under 5MB", size < 5_000_000, f"size={size}")
        print(f"  {label}: {size:,} bytes")


# ── Summary ──────────────────────────────────────────────────
print(f"\n{'='*50}")
print(f"Layer 2 E2E Results: {passed} passed, {failed} failed")
if failed == 0:
    print("ALL TESTS PASSED")
else:
    print(f"FAILURES: {failed}")
    sys.exit(1)
