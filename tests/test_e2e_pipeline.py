#!/usr/bin/env python3
"""End-to-end test: Full pipeline — plan → run → review → verify.

Exercises every checkpoint in the pipeline:
  PLAN:  Layer 1 build → decomposition gate → assemble_architect → assemble_verifier
  RUN:   Layer 2 build → assemble_developer → criteria verify → failure classify
  REVIEW: assemble_reviewer → assemble_coherence
  VERIFY: spec traceability → assemble_debugger (for failed task)
"""

import json
import os
import shutil
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from lib.context.layer1 import build_layer1
from lib.context.layer2 import build_task_context_package, build_feature_cross_task
from lib.context.assembly import (
    assemble_architect, assemble_verifier, assemble_developer,
    assemble_reviewer, assemble_coherence, assemble_debugger,
)
from lib.context.utils import read_json, estimate_tokens_from_text
from lib.decomposition_gate import check_decomposition
from lib.criteria_verify import verify_criteria
from lib.spec_traceability import spec_to_task_check, format_uncovered_for_verifier
from lib.failure_classify import classify_failure, aggregate_classifications

CONTEXT_DIR = os.path.join(PROJECT_ROOT, ".speed", "context")
passed = 0
failed = 0
pipeline_log = []


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name} — {detail}")


def log_stage(stage, detail=""):
    pipeline_log.append((stage, detail))
    print(f"\n{'='*60}")
    print(f"  PIPELINE STAGE: {stage}")
    if detail:
        print(f"  {detail}")
    print(f"{'='*60}")


# ── Task DAG ─────────────────────────────────────────────────
# 3 tasks with dependencies, exercising all expanded schema fields

product_spec = """# Criteria Verification Feature

## Overview
The system MUST provide automated verification of structured acceptance criteria.
Each criterion MUST be checked using its verify_by hint (schema_check, file_exists, test, lint, manual).

## Requirements
- The verification engine shall support 5 verify_by types
- Each verification must produce a status (pass/fail/unverifiable) and evidence
- The system should gracefully degrade when CSG is unavailable
- Coverage metrics must be tracked per-task and per-feature
- The grounding gate shall fail if any non-manual criterion fails
- All verification results must be logged to .speed/ for debugging
"""

tasks = [
    {
        "id": "cv-1",
        "title": "Create criteria verification engine",
        "description": "Build lib/criteria_verify.py with 5 verify_by handlers: "
                       "schema_check, file_exists, test, lint, manual. Each returns "
                       "status + evidence.",
        "files_touched": ["lib/criteria_verify.py"],
        "depends_on": [],
        "acceptance_criteria": [
            {
                "criterion": "verify_criteria function exists in criteria_verify.py",
                "verify_by": "schema_check",
                "target": "lib/criteria_verify.py:verify_criteria",
            },
            {
                "criterion": "criteria_verify.py is importable",
                "verify_by": "file_exists",
                "target": "lib/criteria_verify.py",
            },
            {
                "criterion": "Manual review of error messages",
                "verify_by": "manual",
            },
        ],
        "spec_references": [
            {"spec": "product-spec.md", "section": "Requirements"},
        ],
        "rationale": "Engine must exist before grounding gate (cv-2) can call it. "
                     "Separated to keep each task focused on one concern.",
        "assumptions": ["CSG may not be available — grep fallback is required"],
        "cross_cutting_concerns": ["Token estimation from utils.py shared with budget module"],
    },
    {
        "id": "cv-2",
        "title": "Wire criteria verification into grounding gates",
        "description": "Add Check 8 to grounding.sh: call criteria_verify.py after "
                       "task completion. Hard failure for non-manual criteria failures.",
        "files_touched": ["lib/grounding.sh"],
        "depends_on": ["cv-1"],
        "acceptance_criteria": [
            {
                "criterion": "grounding_check_criteria function exists in grounding.sh",
                "verify_by": "schema_check",
                "target": "lib/grounding.sh:grounding_check_criteria",
            },
        ],
        "spec_references": [
            {"spec": "product-spec.md", "section": "Requirements"},
        ],
        "rationale": "Depends on cv-1 because the grounding gate calls the engine.",
        "assumptions": [],
        "cross_cutting_concerns": [],
    },
    {
        "id": "cv-3",
        "title": "Add spec traceability pre-check",
        "description": "Parse the product spec for requirements and check that each "
                       "is covered by at least one task's spec_references or description. "
                       "Feed uncovered requirements to the Plan Verifier.",
        "files_touched": ["lib/spec_traceability.py"],
        "depends_on": [],
        "acceptance_criteria": [
            {
                "criterion": "spec_traceability.py exists",
                "verify_by": "file_exists",
                "target": "lib/spec_traceability.py",
            },
            {
                "criterion": "Coverage ratio is computed correctly",
                "verify_by": "test",
                "target": "tests/test_traceability.py",
            },
        ],
        "spec_references": [
            {"spec": "product-spec.md", "section": "Overview"},
            {"spec": "product-spec.md", "section": "Requirements"},
        ],
        "rationale": "Independent of cv-1/cv-2 — traceability is a plan-time check, "
                     "not a runtime check.",
        "assumptions": ["Product spec follows markdown heading conventions"],
        "cross_cutting_concerns": [],
    },
]


# ══════════════════════════════════════════════════════════════
# PLAN PHASE
# ══════════════════════════════════════════════════════════════

log_stage("PLAN: Layer 1 Build")

t0 = time.time()
l1_result = build_layer1(PROJECT_ROOT, fresh=True)
t_l1 = time.time() - t0

check("Layer 1 built", l1_result["status"] == "built")
print(f"  Time: {t_l1:.3f}s")

csg = read_json(os.path.join(CONTEXT_DIR, "semantic-graph.json"))
project_map = read_json(os.path.join(CONTEXT_DIR, "project-map.json"))
check("CSG loaded", csg is not None)
check("Project map loaded", project_map is not None)


# ── Decomposition Gate ────────────────────────────────────────
log_stage("PLAN: Decomposition Gate")

t0 = time.time()
decomp_result = check_decomposition(tasks, project_map, csg=csg)
t_decomp = time.time() - t0

check("decomposition gate returned", decomp_result is not None)
overall = decomp_result.get("overall", "unknown")
check("decomposition passed", overall in ("pass", "warn"),
      f"overall={overall}")
print(f"  Overall: {overall}")
print(f"  Time: {t_decomp:.4f}s")

# Show per-task results
for entry in decomp_result.get("per_task", []):
    task_id = entry.get("task_id", "?")
    for c in entry.get("checks", []):
        v = c.get("verdict", "?")
        msg = c.get("message", "")[:80]
        print(f"  {task_id}: [{v}] {msg}")

warnings = decomp_result.get("warnings", [])
if warnings:
    print(f"  Warnings: {len(warnings)}")

# Check file ownership
ownership = decomp_result.get("file_ownership", {})
if ownership:
    violations = ownership.get("violations", [])
    check("no file ownership violations (unique files)",
          len(violations) == 0,
          f"{len(violations)} violations")


# ── Spec Traceability ────────────────────────────────────────
log_stage("PLAN: Spec Traceability")

t0 = time.time()
trace_result = spec_to_task_check(product_spec, tasks)
t_trace = time.time() - t0

total_reqs = trace_result.get("requirements_found", 0)
coverage = trace_result.get("coverage_ratio", 0)
uncovered = trace_result.get("uncovered", [])

check("requirements found", total_reqs > 0, f"found {total_reqs}")
check("coverage > 50%", coverage > 0.5, f"coverage={coverage}")
print(f"  Requirements: {total_reqs}, Coverage: {coverage:.0%}")
print(f"  Uncovered: {len(uncovered)}")
for u in uncovered[:3]:
    print(f"    - [{u.get('section', '?')}] {u.get('requirement', '')[:60]}...")

# Format for Plan Verifier
verifier_input = format_uncovered_for_verifier(trace_result)
if uncovered:
    check("verifier input non-empty", len(verifier_input) > 0)
print(f"  Verifier input: {len(verifier_input)} chars")
print(f"  Time: {t_trace:.4f}s")


# ── Architect Assembly ────────────────────────────────────────
log_stage("PLAN: Architect Assembly")

t0 = time.time()
md_arch = assemble_architect(project_map, csg)
t_arch_asm = time.time() - t0

tokens_arch = estimate_tokens_from_text(md_arch)
check("architect markdown non-empty", len(md_arch) > 0)
check("architect under 60K tokens", tokens_arch <= 60000)
print(f"  Tokens: {tokens_arch}, Time: {t_arch_asm:.4f}s")


# ── Verifier Assembly ────────────────────────────────────────
log_stage("PLAN: Verifier Assembly")

t0 = time.time()
md_ver = assemble_verifier(
    product_spec=product_spec,
    tasks=tasks,
    cross_cutting_concerns=tasks[0].get("cross_cutting_concerns", []),
    spec_alignment=None,
    csg=csg,
    decomposition_result=decomp_result,
)
t_ver_asm = time.time() - t0

tokens_ver = estimate_tokens_from_text(md_ver)
check("verifier markdown non-empty", len(md_ver) > 0)
check("verifier under 80K tokens", tokens_ver <= 80000)
print(f"  Tokens: {tokens_ver}, Time: {t_ver_asm:.4f}s")


# ══════════════════════════════════════════════════════════════
# RUN PHASE (per task)
# ══════════════════════════════════════════════════════════════

completed_tasks = {}
task_diffs = {}
task_budgets = {}
task_code_contexts = {}

for task in tasks:
    tid = task["id"]
    log_stage(f"RUN: Task {tid} — {task['title'][:50]}")

    # ── Layer 2 Build ────────────────────────────────────
    t0 = time.time()
    l2_result = build_task_context_package(
        task=task,
        all_tasks=tasks,
        project_root=PROJECT_ROOT,
        csg=csg,
        project_map=project_map,
        context_dir=CONTEXT_DIR,
        completed_tasks=completed_tasks,
        stage="developer",
    )
    t_l2 = time.time() - t0

    check(f"{tid}: Layer 2 built", "artifacts" in l2_result)
    budget_summary = l2_result.get("budget_summary", {})
    print(f"  Layer 2: {t_l2:.3f}s, "
          f"budget: {budget_summary.get('total_used', 0):,}/{budget_summary.get('total_budget', 0):,} tokens")

    # Load artifacts
    task_ctx_dir = os.path.join(CONTEXT_DIR, "tasks", tid, "context")
    code_ctx = read_json(os.path.join(task_ctx_dir, "code-context.json")) or {}
    task_ctx = read_json(os.path.join(task_ctx_dir, "task-context.json")) or {}
    spec_ctx = read_json(os.path.join(task_ctx_dir, "spec-context.json")) or {}
    budget_data = read_json(os.path.join(task_ctx_dir, "budget.json")) or {}
    task_budgets[tid] = budget_data
    task_code_contexts[tid] = code_ctx

    # ── Developer Assembly ────────────────────────────────
    t0 = time.time()
    md_dev = assemble_developer(
        task=task,
        code_context=code_ctx,
        task_context=task_ctx,
        spec_context=spec_ctx,
        budget=budget_data,
        cross_cutting_concerns=task.get("cross_cutting_concerns"),
        branch_name=f"feature/cv/{tid}",
        feature_name="criteria-verification",
    )
    t_dev = time.time() - t0

    tokens_dev = estimate_tokens_from_text(md_dev)
    check(f"{tid}: developer markdown produced", len(md_dev) > 0)
    check(f"{tid}: developer under 80K", tokens_dev <= 80000,
          f"{tokens_dev} tokens")
    print(f"  Developer: {tokens_dev:,} tokens, {t_dev:.4f}s")

    # ── Simulate task completion ──────────────────────────
    # (In real pipeline, the LLM developer would produce code + diff)
    fake_diff = f"diff --git a/{task['files_touched'][0]}\n" \
                f"+++ b/{task['files_touched'][0]}\n" \
                f"@@ -1,3 +1,10 @@\n" \
                f"+# Implemented by {tid}\n" \
                f"+def new_function():\n" \
                f"+    pass\n"
    task_diffs[tid] = fake_diff

    # ── Criteria Verification ─────────────────────────────
    t0 = time.time()
    cv_result = verify_criteria(
        task=task,
        project_root=PROJECT_ROOT,
        csg=csg,
        project_map=project_map,
    )
    t_cv = time.time() - t0

    results = cv_result.get("criteria_results", [])
    summary = cv_result.get("summary", {})
    check(f"{tid}: criteria verified", len(results) > 0,
          f"no results")
    print(f"  Criteria: pass={summary.get('pass', 0)}, "
          f"fail={summary.get('fail', 0)}, "
          f"unverifiable={summary.get('unverifiable', 0)}, "
          f"time={t_cv:.4f}s")

    for r in results:
        status = r.get("status", "?")
        crit = r.get("criterion", "?")[:50]
        print(f"    [{status}] {crit}")

    # Mark as completed
    completed_tasks[tid] = {
        "status": "completed",
        "output": f"Task {tid} implemented successfully.",
        "criteria_results": results,
    }


# ── Cross-Task Analysis ──────────────────────────────────────
log_stage("RUN: Cross-Task Analysis")

feature_dir = os.path.join(CONTEXT_DIR, "features", "pipeline-test")
t0 = time.time()
cross = build_feature_cross_task(tasks, csg, feature_dir)
t_cross = time.time() - t0

check("cross-task analysis built", cross is not None)
print(f"  Domain overlaps: {len(cross.get('domain_overlap', []))}")
print(f"  Interface boundaries: {len(cross.get('interface_boundaries', []))}")
print(f"  High-impact mods: {len(cross.get('high_impact_modifications', []))}")
print(f"  Time: {t_cross:.4f}s")


# ══════════════════════════════════════════════════════════════
# REVIEW PHASE
# ══════════════════════════════════════════════════════════════

log_stage("REVIEW: Reviewer Assembly (per task)")

for task in tasks:
    tid = task["id"]
    task_ctx_dir = os.path.join(CONTEXT_DIR, "tasks", tid, "context")
    task_ctx = read_json(os.path.join(task_ctx_dir, "task-context.json")) or {}
    spec_ctx = read_json(os.path.join(task_ctx_dir, "spec-context.json")) or {}

    md_rev = assemble_reviewer(
        task=task,
        diff=task_diffs.get(tid, ""),
        task_context=task_ctx,
        spec_context=spec_ctx,
        csg=csg,
        criteria_results=completed_tasks[tid].get("criteria_results"),
    )

    tokens_rev = estimate_tokens_from_text(md_rev)
    check(f"{tid}: reviewer markdown produced", len(md_rev) > 0)
    check(f"{tid}: reviewer under 60K", tokens_rev <= 60000)
    print(f"  {tid}: {tokens_rev} tokens")


# ── Coherence Assembly ────────────────────────────────────────
log_stage("REVIEW: Coherence Assembly")

t0 = time.time()
md_coh = assemble_coherence(
    cross_task_analysis=cross,
    completed_tasks=tasks,
    task_diffs=task_diffs,
    product_spec=product_spec,
    contract={"entities": [{"name": "verify_criteria", "type": "function",
                            "path": "lib/criteria_verify.py"}]},
)
t_coh = time.time() - t0

tokens_coh = estimate_tokens_from_text(md_coh)
check("coherence markdown produced", len(md_coh) > 0)
check("coherence under 100K", tokens_coh <= 100000)
print(f"  Tokens: {tokens_coh}, Time: {t_coh:.4f}s")


# ══════════════════════════════════════════════════════════════
# FAILURE SCENARIO (simulate cv-2 failing)
# ══════════════════════════════════════════════════════════════

log_stage("FAILURE: Simulate Task Failure + Classification")

failed_task = tasks[1]  # cv-2
failed_budget = task_budgets.get("cv-2", {"total_budget": 80000, "total_used": 40000,
                                          "under_budget": True, "cuts_made": []})

# Simulate a lint failure — gate_results format uses "name" and "status" keys
fake_gate_results = {
    "checks": [
        {"name": "diff_non_empty", "status": "pass"},
        {"name": "scope", "status": "pass"},
        {"name": "lint", "status": "fail", "detail": "3 type errors in grounding.sh"},
    ],
}

fake_agent_output = (
    "Starting implementation of grounding_check_criteria...\n"
    "Modified lib/grounding.sh\n"
    "Running quality gates...\n"
    "FAIL: lint check found 3 type errors\n"
    "Attempting fix...\n"
    "FAIL: still 2 type errors\n"
)

t0 = time.time()
fc_result = classify_failure(
    budget=failed_budget,
    gate_results=fake_gate_results,
    agent_output=fake_agent_output,
    task=failed_task,
)
t_fc = time.time() - t0

check("failure classified", "class" in fc_result)
check("classified as implementation_error",
      fc_result.get("subclass") == "implementation_error",
      f"got {fc_result.get('subclass')}")
print(f"  Class: {fc_result.get('class')}, Subclass: {fc_result.get('subclass')}")
print(f"  Evidence: {fc_result.get('evidence', '')[:80]}")
print(f"  Time: {t_fc:.6f}s")


# ── Debugger Assembly ────────────────────────────────────────
log_stage("FAILURE: Debugger Assembly")

md_dbg = assemble_debugger(
    task=failed_task,
    budget=failed_budget,
    agent_output=fake_agent_output,
    diff=task_diffs.get("cv-2", ""),
    code_context=task_code_contexts.get("cv-2"),
    failure_classification=fc_result,
)

tokens_dbg = estimate_tokens_from_text(md_dbg)
check("debugger markdown produced", len(md_dbg) > 0)
check("debugger under 50K", tokens_dbg <= 50000)
check("debugger mentions failure class",
      "implementation_error" in md_dbg or "pipeline" in md_dbg or "complexity" in md_dbg)
print(f"  Tokens: {tokens_dbg}")


# ── Failure Aggregation ──────────────────────────────────────
log_stage("STATUS: Failure Aggregation")

classifications = [fc_result]  # Only 1 failure in our simulation
agg = aggregate_classifications(classifications)

check("aggregation returned", agg is not None)
check("aggregation total", agg.get("total_failures") == 1,
      f"got {agg.get('total_failures')}")
print(f"  Total: {agg.get('total_failures')}")
print(f"  Pipeline: {agg.get('pipeline_failures')}, Complexity: {agg.get('complexity_failures')}")
print(f"  Pipeline ratio: {agg.get('pipeline_ratio', 0):.0%}")
print(f"  Breakdown: {agg.get('breakdown', {})}")


# ══════════════════════════════════════════════════════════════
# PIPELINE SUMMARY
# ══════════════════════════════════════════════════════════════

print(f"\n{'='*60}")
print("  PIPELINE EXECUTION SUMMARY")
print(f"{'='*60}")
for stage, detail in pipeline_log:
    print(f"  {stage}")
print()
print(f"  Tasks: {len(tasks)}")
print(f"  Stages executed: {len(pipeline_log)}")

# Total token counts
print(f"\n  Token usage across pipeline:")
print(f"    Architect:  {estimate_tokens_from_text(md_arch):>8,}")
print(f"    Verifier:   {estimate_tokens_from_text(md_ver):>8,}")
print(f"    Coherence:  {estimate_tokens_from_text(md_coh):>8,}")
print(f"    Debugger:   {estimate_tokens_from_text(md_dbg):>8,}")

print(f"\n{'='*60}")
print(f"Full Pipeline E2E Results: {passed} passed, {failed} failed")
if failed == 0:
    print("ALL TESTS PASSED")
else:
    print(f"FAILURES: {failed}")
    sys.exit(1)
