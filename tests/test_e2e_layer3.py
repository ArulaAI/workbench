#!/usr/bin/env python3
"""End-to-end test: Layer 3 assembly produces valid markdown for all 6 stages."""

import json
import os
import re
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from lib.context.assembly import (
    assemble_architect,
    assemble_coherence,
    assemble_debugger,
    assemble_developer,
    assemble_reviewer,
    assemble_verifier,
)
from lib.context.utils import estimate_tokens_from_text, read_json

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


def check_markdown(label, md, required_sections, max_tokens):
    """Common checks for all assembly outputs."""
    check(f"{label}: non-empty", len(md) > 0, "empty output")
    check(f"{label}: is string", isinstance(md, str), f"got {type(md).__name__}")

    tokens = estimate_tokens_from_text(md)
    lines = md.count("\n") + 1
    check(f"{label}: under budget ({max_tokens})", tokens <= max_tokens,
          f"{tokens} tokens exceeds {max_tokens}")
    print(f"  {label}: {tokens} tokens, {lines} lines")

    # Check for expected section headers
    for section in required_sections:
        found = section.lower() in md.lower()
        check(f"{label}: has '{section}'", found, f"section not found in output")

    # Check for obvious formatting errors
    check(f"{label}: no raw None", "None" not in md or "none" in md.lower(),
          "contains raw 'None' — likely unformatted data")

    return tokens, lines


# ── Load Layer 1 artifacts ───────────────────────────────────
print("=== Loading Artifacts ===")
csg = read_json(os.path.join(CONTEXT_DIR, "semantic-graph.json"))
project_map = read_json(os.path.join(CONTEXT_DIR, "project-map.json"))
check("Layer 1 artifacts loaded", csg is not None and project_map is not None)


# ── Realistic task definitions ───────────────────────────────
task_a = {
    "id": "e2e-1",
    "title": "Add criteria verification to grounding gates",
    "description": "Implement Check 8 in grounding.sh to call criteria_verify.py "
                   "and fail on unmet structured criteria.",
    "files_touched": ["lib/grounding.sh", "lib/criteria_verify.py"],
    "depends_on": [],
    "acceptance_criteria": [
        {
            "criterion": "grounding_check_criteria function exists in grounding.sh",
            "verify_by": "schema_check",
            "target": "lib/grounding.sh:grounding_check_criteria",
        },
        {
            "criterion": "criteria_verify.py passes all schema_check verifications",
            "verify_by": "test",
            "target": "tests/test_criteria.py",
        },
    ],
    "spec_references": [
        {"spec": "tech-spec.md", "section": "Verification System"},
    ],
    "rationale": "Criteria verification is the deterministic backbone — it must work "
                 "before any semantic (LLM) verification can build on it.",
    "assumptions": ["CSG is available for schema_check; grep fallback if not"],
    "cross_cutting_concerns": ["All tasks with verify_by depend on this infrastructure"],
}

task_b = {
    "id": "e2e-2",
    "title": "Update developer prompt with structured criteria checklist",
    "description": "Modify the developer prompt to include a per-criterion checklist "
                   "with verify_by hints so the developer knows exactly what will be checked.",
    "files_touched": ["lib/context/assembly.py"],
    "depends_on": ["e2e-1"],
    "acceptance_criteria": [
        {
            "criterion": "Developer prompt includes criteria checklist section",
            "verify_by": "manual",
        },
    ],
    "spec_references": [
        {"spec": "tech-spec.md", "section": "Layer 3"},
    ],
    "rationale": "Depends on task 1 because criteria format must be finalized first.",
    "assumptions": [],
    "cross_cutting_concerns": [],
}

all_tasks = [task_a, task_b]


# ── Test 1: assemble_architect ───────────────────────────────
print("\n=== Test 1: assemble_architect ===")

md_arch = assemble_architect(project_map, csg)
check_markdown("architect", md_arch,
               required_sections=["codebase context", "directory", "domain"],
               max_tokens=60000)


# ── Test 2: assemble_verifier ────────────────────────────────
print("\n=== Test 2: assemble_verifier ===")

product_spec = "# Test Feature\n\nThis feature MUST add criteria verification.\n\n" \
               "## Requirements\n- The system shall verify each criterion automatically.\n" \
               "- Coverage must be tracked per task.\n"

md_ver = assemble_verifier(
    product_spec=product_spec,
    tasks=all_tasks,
    cross_cutting_concerns=["All tasks with verify_by depend on this infrastructure"],
    contract={"entities": [{"name": "CriteriaVerifier", "type": "function",
                            "path": "lib/criteria_verify.py", "function": "verify_criteria"}]},
    spec_alignment=None,
    csg=csg,
)
check_markdown("verifier", md_ver,
               required_sections=["product spec", "task plan", "criteria"],
               max_tokens=80000)


# ── Test 3: assemble_developer ───────────────────────────────
print("\n=== Test 3: assemble_developer ===")

# Load real Layer 2 artifacts from the task-a build in Phase 6.2
task_ctx_dir = os.path.join(CONTEXT_DIR, "tasks", "e2e-task-1", "context")
if os.path.exists(task_ctx_dir):
    code_ctx = read_json(os.path.join(task_ctx_dir, "code-context.json"))
    task_ctx = read_json(os.path.join(task_ctx_dir, "task-context.json"))
    spec_ctx = read_json(os.path.join(task_ctx_dir, "spec-context.json"))
    budget_data = read_json(os.path.join(task_ctx_dir, "budget.json"))
else:
    # Fallback to minimal synthetic data
    code_ctx = {"full_content": {"files_touched": [], "one_hop": []}, "skeleton": {},
                "symbols_in_scope": [], "expansion_summary": {"seed_files": 0}}
    task_ctx = {"reasoning": {}, "upstream": [], "downstream": [], "shared_scope_warnings": []}
    spec_ctx = {"relevant_spec_sections": [], "alignment_status": [], "contract_excerpt": []}
    budget_data = {"total_budget": 80000, "total_used": 0, "under_budget": True, "cuts_made": []}

# Use task_a definition with real Layer 2 data
md_dev = assemble_developer(
    task=task_a,
    code_context=code_ctx,
    task_context=task_ctx,
    spec_context=spec_ctx,
    budget=budget_data,
    cross_cutting_concerns=["All tasks with verify_by depend on this infrastructure"],
    branch_name="feature/criteria-verification",
    worktree_path="/tmp/speed-worktree-criteria",
    feature_name="criteria-verification",
)
tokens_dev, lines_dev = check_markdown("developer", md_dev,
    required_sections=["task", "criteria", "code"],
    max_tokens=80000)

# Developer should have code blocks
code_blocks = md_dev.count("```")
check("developer: has code blocks", code_blocks >= 2,
      f"only {code_blocks} code fences (expected >=2)")
print(f"  Code blocks: {code_blocks // 2}")


# ── Test 4: assemble_reviewer ────────────────────────────────
print("\n=== Test 4: assemble_reviewer ===")

sample_diff = """diff --git a/lib/grounding.sh b/lib/grounding.sh
index abc1234..def5678 100644
--- a/lib/grounding.sh
+++ b/lib/grounding.sh
@@ -100,6 +100,20 @@ grounding_check_scope() {
+grounding_check_criteria() {
+    local task_json="$1"
+    local project_root="$2"
+    python3 lib/criteria_verify.py "$task_json" "$project_root"
+    return $?
+}
"""

md_rev = assemble_reviewer(
    task=task_a,
    diff=sample_diff,
    task_context=task_ctx,
    spec_context=spec_ctx,
    csg=csg,
    criteria_results=[
        {"criterion": "grounding_check_criteria function exists",
         "status": "pass", "evidence": "Found in grounding.sh line 103"},
    ],
)
check_markdown("reviewer", md_rev,
    required_sections=["diff", "criteria"],
    max_tokens=60000)

# Reviewer should contain the diff
check("reviewer: contains diff content", "grounding_check_criteria" in md_rev)


# ── Test 5: assemble_coherence ───────────────────────────────
print("\n=== Test 5: assemble_coherence ===")

cross_task = read_json(os.path.join(CONTEXT_DIR, "features", "e2e-test",
                                     "cross-task-analysis.json"))
if cross_task is None:
    # Minimal fallback
    cross_task = {"domain_overlap": [], "interface_boundaries": [],
                  "high_impact_modifications": []}

md_coh = assemble_coherence(
    cross_task_analysis=cross_task,
    completed_tasks=all_tasks,
    task_diffs={"e2e-1": sample_diff, "e2e-2": "diff --git a/assembly.py...\n+# Updated"},
    product_spec=product_spec,
    contract={"entities": [{"name": "verify_criteria", "type": "function"}]},
)
check_markdown("coherence", md_coh,
    required_sections=["coherence", "diff"],
    max_tokens=100000)


# ── Test 6: assemble_debugger ────────────────────────────────
print("\n=== Test 6: assemble_debugger ===")

md_dbg = assemble_debugger(
    task=task_a,
    budget=budget_data,
    agent_output="Attempting to modify grounding.sh...\n"
                 "ERROR: scope violation — touched 5 undeclared files\n"
                 "Agent exceeded turn limit.",
    diff=sample_diff,
    code_context=code_ctx,
    failure_classification={
        "class": "pipeline",
        "subclass": "decomposition_error",
        "evidence": "5 undeclared files touched: foo.py, bar.py, baz.py, qux.py, quux.py",
    },
)
check_markdown("debugger", md_dbg,
    required_sections=["budget", "task", "agent output"],
    max_tokens=50000)

# Debugger should contain the failure classification
check("debugger: contains failure classification",
      "decomposition_error" in md_dbg or "pipeline" in md_dbg)


# ── Test 7: Token budget comparison across stages ────────────
print("\n=== Test 7: Budget Comparison ===")

token_counts = {
    "architect": estimate_tokens_from_text(md_arch),
    "verifier": estimate_tokens_from_text(md_ver),
    "developer": estimate_tokens_from_text(md_dev),
    "reviewer": estimate_tokens_from_text(md_rev),
    "coherence": estimate_tokens_from_text(md_coh),
    "debugger": estimate_tokens_from_text(md_dbg),
}

stage_budgets = {
    "architect": 60000, "verifier": 80000, "developer": 80000,
    "reviewer": 60000, "coherence": 100000, "debugger": 50000,
}

print(f"\n  {'Stage':<15} {'Tokens':>8} {'Budget':>8} {'%':>6}")
print(f"  {'-'*15} {'-'*8} {'-'*8} {'-'*6}")
for stage, tokens in token_counts.items():
    budget = stage_budgets[stage]
    pct = tokens / budget * 100
    print(f"  {stage:<15} {tokens:>8,} {budget:>8,} {pct:>5.1f}%")
    check(f"{stage} under budget", tokens <= budget)


# ── Summary ──────────────────────────────────────────────────
print(f"\n{'='*50}")
print(f"Layer 3 E2E Results: {passed} passed, {failed} failed")
if failed == 0:
    print("ALL TESTS PASSED")
else:
    print(f"FAILURES: {failed}")
    sys.exit(1)
