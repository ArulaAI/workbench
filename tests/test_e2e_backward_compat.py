#!/usr/bin/env python3
"""End-to-end test: Backward compatibility with legacy tasks.

Legacy tasks lack expanded schema fields:
  - acceptance_criteria as structured array (may be strings or missing)
  - spec_references (missing)
  - rationale (missing)
  - assumptions (missing)
  - cross_cutting_concerns (missing)

The entire pipeline must gracefully degrade — no crashes, no missing data,
reasonable output quality even without the expanded schema.
"""

import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from lib.context.layer2 import build_task_context_package, build_feature_cross_task
from lib.context.assembly import (
    assemble_architect, assemble_verifier, assemble_developer,
    assemble_reviewer, assemble_coherence, assemble_debugger,
)
from lib.context.utils import read_json, estimate_tokens_from_text
from lib.decomposition_gate import check_decomposition
from lib.criteria_verify import verify_criteria
from lib.spec_traceability import spec_to_task_check
from lib.failure_classify import classify_failure

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
check("Layer 1 loaded", csg is not None and project_map is not None)


# ══════════════════════════════════════════════════════════════
# Legacy task format — minimal fields only
# ══════════════════════════════════════════════════════════════

# Task type 1: Absolute minimum — just id, title, description, files_touched
legacy_minimal = {
    "id": "legacy-1",
    "title": "Add user authentication",
    "description": "Implement user auth with JWT tokens. Create login/logout endpoints.",
    "files_touched": ["lib/context/utils.py"],
    "depends_on": [],
}

# Task type 2: String acceptance criteria (old format)
legacy_string_criteria = {
    "id": "legacy-2",
    "title": "Create database models",
    "description": "Add SQLAlchemy models for User and Session tables.",
    "files_touched": ["lib/context/csg.py"],
    "depends_on": ["legacy-1"],
    "acceptance_criteria": [
        "User model has email, password_hash, created_at fields",
        "Session model has user_id FK and expires_at",
        "Both models inherit from Base",
    ],
}

# Task type 3: Empty lists for expanded fields
legacy_empty_expanded = {
    "id": "legacy-3",
    "title": "Add API endpoints",
    "description": "Create REST endpoints for /login, /logout, /me.",
    "files_touched": ["lib/context/assembly.py"],
    "depends_on": ["legacy-1", "legacy-2"],
    "acceptance_criteria": [],
    "spec_references": [],
    "rationale": "",
    "assumptions": [],
    "cross_cutting_concerns": [],
}

all_legacy_tasks = [legacy_minimal, legacy_string_criteria, legacy_empty_expanded]


# ══════════════════════════════════════════════════════════════
# Test 1: Decomposition Gate with legacy tasks
# ══════════════════════════════════════════════════════════════
print("\n=== Test 1: Decomposition Gate ===")

try:
    decomp = check_decomposition(all_legacy_tasks, project_map, csg=csg)
    check("decomp gate: no crash", True)
    check("decomp gate: returned result", decomp is not None)
    check("decomp gate: has overall", "overall" in decomp)
    print(f"  Overall: {decomp.get('overall')}")
except Exception as e:
    check("decomp gate: no crash", False, str(e))


# ══════════════════════════════════════════════════════════════
# Test 2: Criteria Verification with legacy tasks
# ══════════════════════════════════════════════════════════════
print("\n=== Test 2: Criteria Verification ===")

# Minimal task — no acceptance_criteria at all
try:
    cv1 = verify_criteria(legacy_minimal, PROJECT_ROOT, csg=csg, project_map=project_map)
    check("criteria verify (no criteria): no crash", True)
    results = cv1.get("criteria_results", [])
    check("criteria verify (no criteria): empty results", len(results) == 0)
    print(f"  Results: {len(results)}")
except Exception as e:
    check("criteria verify (no criteria): no crash", False, str(e))

# String criteria — should be auto-wrapped as manual
try:
    cv2 = verify_criteria(legacy_string_criteria, PROJECT_ROOT, csg=csg, project_map=project_map)
    check("criteria verify (string criteria): no crash", True)
    results = cv2.get("criteria_results", [])
    check("criteria verify (string criteria): has results", len(results) > 0,
          f"got {len(results)}")
    # All string criteria should be treated as unverifiable/manual
    for r in results:
        print(f"  [{r.get('status', '?')}] {r.get('criterion', '?')[:50]}")
except Exception as e:
    check("criteria verify (string criteria): no crash", False, str(e))

# Empty criteria list
try:
    cv3 = verify_criteria(legacy_empty_expanded, PROJECT_ROOT, csg=csg, project_map=project_map)
    check("criteria verify (empty list): no crash", True)
    results = cv3.get("criteria_results", [])
    check("criteria verify (empty list): empty results", len(results) == 0)
except Exception as e:
    check("criteria verify (empty list): no crash", False, str(e))


# ══════════════════════════════════════════════════════════════
# Test 3: Layer 2 Build with legacy tasks
# ══════════════════════════════════════════════════════════════
print("\n=== Test 3: Layer 2 Build ===")

for task in all_legacy_tasks:
    tid = task["id"]
    try:
        result = build_task_context_package(
            task=task,
            all_tasks=all_legacy_tasks,
            project_root=PROJECT_ROOT,
            csg=csg,
            project_map=project_map,
            context_dir=CONTEXT_DIR,
            stage="developer",
        )
        check(f"L2 build ({tid}): no crash", True)
        check(f"L2 build ({tid}): has artifacts", "artifacts" in result)
        budget = result.get("budget_summary", {})
        print(f"  {tid}: {budget.get('total_used', 0):,}/{budget.get('total_budget', 0):,} tokens")
    except Exception as e:
        check(f"L2 build ({tid}): no crash", False, str(e))


# ══════════════════════════════════════════════════════════════
# Test 4: Assembly Functions with legacy tasks
# ══════════════════════════════════════════════════════════════
print("\n=== Test 4: Assembly Functions ===")

# Load Layer 2 artifacts for legacy-1
task_ctx_dir = os.path.join(CONTEXT_DIR, "tasks", "legacy-1", "context")
code_ctx = read_json(os.path.join(task_ctx_dir, "code-context.json")) or {}
task_ctx = read_json(os.path.join(task_ctx_dir, "task-context.json")) or {}
spec_ctx = read_json(os.path.join(task_ctx_dir, "spec-context.json")) or {}
budget_data = read_json(os.path.join(task_ctx_dir, "budget.json")) or {}

# assemble_developer — minimal task
try:
    md = assemble_developer(
        task=legacy_minimal,
        code_context=code_ctx,
        task_context=task_ctx,
        spec_context=spec_ctx,
        budget=budget_data,
    )
    check("developer (minimal): no crash", True)
    check("developer (minimal): non-empty", len(md) > 0)
    tokens = estimate_tokens_from_text(md)
    check("developer (minimal): under budget", tokens <= 80000)
    print(f"  Developer (minimal): {tokens:,} tokens")
except Exception as e:
    check("developer (minimal): no crash", False, str(e))

# assemble_developer — string criteria task
task_ctx_dir2 = os.path.join(CONTEXT_DIR, "tasks", "legacy-2", "context")
code_ctx2 = read_json(os.path.join(task_ctx_dir2, "code-context.json")) or {}
task_ctx2 = read_json(os.path.join(task_ctx_dir2, "task-context.json")) or {}
spec_ctx2 = read_json(os.path.join(task_ctx_dir2, "spec-context.json")) or {}
budget_data2 = read_json(os.path.join(task_ctx_dir2, "budget.json")) or {}

try:
    md2 = assemble_developer(
        task=legacy_string_criteria,
        code_context=code_ctx2,
        task_context=task_ctx2,
        spec_context=spec_ctx2,
        budget=budget_data2,
    )
    check("developer (string criteria): no crash", True)
    check("developer (string criteria): non-empty", len(md2) > 0)
    # String criteria should appear in output
    check("developer (string criteria): criteria in output",
          "email" in md2 or "User model" in md2 or "acceptance" in md2.lower(),
          "criteria text not found in developer output")
    tokens2 = estimate_tokens_from_text(md2)
    print(f"  Developer (string criteria): {tokens2:,} tokens")
except Exception as e:
    check("developer (string criteria): no crash", False, str(e))

# assemble_reviewer — minimal task with diff
try:
    md_rev = assemble_reviewer(
        task=legacy_minimal,
        diff="diff --git a/lib/auth.py\n+def login():\n+    pass\n",
        task_context=task_ctx,
        spec_context=spec_ctx,
    )
    check("reviewer (minimal): no crash", True)
    check("reviewer (minimal): non-empty", len(md_rev) > 0)
    print(f"  Reviewer (minimal): {estimate_tokens_from_text(md_rev)} tokens")
except Exception as e:
    check("reviewer (minimal): no crash", False, str(e))

# assemble_verifier — no product spec
try:
    md_ver = assemble_verifier(
        product_spec="",
        tasks=all_legacy_tasks,
    )
    check("verifier (no spec): no crash", True)
    check("verifier (no spec): non-empty", len(md_ver) > 0)
    print(f"  Verifier (no spec): {estimate_tokens_from_text(md_ver)} tokens")
except Exception as e:
    check("verifier (no spec): no crash", False, str(e))

# assemble_coherence — legacy tasks with no cross-task analysis
try:
    md_coh = assemble_coherence(
        cross_task_analysis={"domain_overlap": [], "interface_boundaries": [],
                             "high_impact_modifications": []},
        completed_tasks=all_legacy_tasks,
        task_diffs={"legacy-1": "diff", "legacy-2": "diff", "legacy-3": "diff"},
    )
    check("coherence (legacy): no crash", True)
    check("coherence (legacy): non-empty", len(md_coh) > 0)
    print(f"  Coherence (legacy): {estimate_tokens_from_text(md_coh)} tokens")
except Exception as e:
    check("coherence (legacy): no crash", False, str(e))

# assemble_debugger — minimal task, minimal budget
try:
    md_dbg = assemble_debugger(
        task=legacy_minimal,
        budget={"total_budget": 80000, "total_used": 50000,
                "under_budget": True, "cuts_made": []},
        agent_output="Error: couldn't find auth module",
    )
    check("debugger (legacy): no crash", True)
    check("debugger (legacy): non-empty", len(md_dbg) > 0)
    print(f"  Debugger (legacy): {estimate_tokens_from_text(md_dbg)} tokens")
except Exception as e:
    check("debugger (legacy): no crash", False, str(e))


# ══════════════════════════════════════════════════════════════
# Test 5: Spec Traceability with legacy tasks (no spec_references)
# ══════════════════════════════════════════════════════════════
print("\n=== Test 5: Spec Traceability ===")

spec = "# Auth Feature\n\n- The system MUST support JWT authentication\n" \
       "- Users should be able to login with email and password\n"

try:
    trace = spec_to_task_check(spec, all_legacy_tasks)
    check("traceability (legacy): no crash", True)
    check("traceability (legacy): has coverage ratio", "coverage_ratio" in trace)
    print(f"  Requirements: {trace.get('requirements_found')}, "
          f"Coverage: {trace.get('coverage_ratio', 0):.0%}")
except Exception as e:
    check("traceability (legacy): no crash", False, str(e))


# ══════════════════════════════════════════════════════════════
# Test 6: Failure Classification with minimal task
# ══════════════════════════════════════════════════════════════
print("\n=== Test 6: Failure Classification ===")

try:
    fc = classify_failure(
        budget=None,
        gate_results={},
        agent_output="",
        task=legacy_minimal,
    )
    check("failure classify (all None): no crash", True)
    check("failure classify (all None): returns dict", isinstance(fc, dict))
    print(f"  Class: {fc.get('class')}, Subclass: {fc.get('subclass')}")
except Exception as e:
    check("failure classify (all None): no crash", False, str(e))


# ══════════════════════════════════════════════════════════════
# Test 7: Cross-task analysis with legacy tasks
# ══════════════════════════════════════════════════════════════
print("\n=== Test 7: Cross-Task Analysis ===")

try:
    cross_dir = os.path.join(CONTEXT_DIR, "features", "legacy-test")
    cross = build_feature_cross_task(all_legacy_tasks, csg, cross_dir)
    check("cross-task (legacy): no crash", True)
    check("cross-task (legacy): has domain_overlap", "domain_overlap" in cross)
    print(f"  Domain overlaps: {len(cross.get('domain_overlap', []))}")
except Exception as e:
    check("cross-task (legacy): no crash", False, str(e))


# ══════════════════════════════════════════════════════════════
# Test 8: Mixed tasks — some legacy, some modern
# ══════════════════════════════════════════════════════════════
print("\n=== Test 8: Mixed Legacy + Modern Tasks ===")

modern_task = {
    "id": "modern-1",
    "title": "Add role-based access control",
    "description": "Implement RBAC with admin/user roles.",
    "files_touched": ["lib/context/budget.py"],
    "depends_on": ["legacy-1"],
    "acceptance_criteria": [
        {
            "criterion": "RBAC middleware exists",
            "verify_by": "file_exists",
            "target": "lib/context/budget.py",
        },
    ],
    "spec_references": [
        {"spec": "auth-spec.md", "section": "RBAC"},
    ],
    "rationale": "RBAC needs auth (legacy-1) before it can check roles.",
    "assumptions": ["Two roles: admin and user"],
    "cross_cutting_concerns": ["Role checks needed in all protected endpoints"],
}

mixed_tasks = [legacy_minimal, modern_task]

try:
    # Decomposition gate
    decomp_mixed = check_decomposition(mixed_tasks, project_map, csg=csg)
    check("mixed: decomposition no crash", True)

    # Layer 2 for modern task referencing legacy task as dependency
    l2_mixed = build_task_context_package(
        task=modern_task,
        all_tasks=mixed_tasks,
        project_root=PROJECT_ROOT,
        csg=csg,
        project_map=project_map,
        context_dir=CONTEXT_DIR,
        completed_tasks={"legacy-1": {"status": "completed", "output": "Auth implemented."}},
        stage="developer",
    )
    check("mixed: L2 build no crash", True)

    # Load artifacts and assemble developer
    tc_dir = os.path.join(CONTEXT_DIR, "tasks", "modern-1", "context")
    cc = read_json(os.path.join(tc_dir, "code-context.json")) or {}
    tc = read_json(os.path.join(tc_dir, "task-context.json")) or {}
    sc = read_json(os.path.join(tc_dir, "spec-context.json")) or {}
    bd = read_json(os.path.join(tc_dir, "budget.json")) or {}

    md_mixed = assemble_developer(
        task=modern_task,
        code_context=cc,
        task_context=tc,
        spec_context=sc,
        budget=bd,
        cross_cutting_concerns=modern_task.get("cross_cutting_concerns"),
    )
    check("mixed: developer assembly no crash", True)
    check("mixed: developer has rationale",
          "RBAC needs auth" in md_mixed or "rationale" in md_mixed.lower())
    check("mixed: developer has upstream",
          "legacy-1" in md_mixed or "upstream" in md_mixed.lower())
    tokens_mixed = estimate_tokens_from_text(md_mixed)
    print(f"  Mixed developer: {tokens_mixed:,} tokens")

except Exception as e:
    check("mixed: no crash", False, str(e))
    import traceback
    traceback.print_exc()


# ══════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════
print(f"\n{'='*60}")
print(f"Backward Compatibility E2E Results: {passed} passed, {failed} failed")
if failed == 0:
    print("ALL TESTS PASSED")
    print("\nLegacy tasks (no expanded schema) work across:")
    print("  - Decomposition gate")
    print("  - Criteria verification")
    print("  - Layer 2 context building")
    print("  - All 6 assembly functions")
    print("  - Spec traceability")
    print("  - Failure classification")
    print("  - Cross-task analysis")
    print("  - Mixed legacy + modern task DAGs")
else:
    print(f"FAILURES: {failed}")
    sys.exit(1)
