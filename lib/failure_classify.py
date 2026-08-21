"""Failure Classification System.

Classifies task failures into pipeline vs. complexity categories
using budget.json, grounding gate results, and agent output patterns.

Six rules, first-match-wins:
  1. budget cuts + agent references cut files → pipeline: context_cut
  2. Agent used 80%+ turns with near-zero output → pipeline: exploration_death
  3. Undeclared files > declared files → pipeline: decomposition_error
  4. Agent reports blocked with ambiguous_spec/missing_dependency → pipeline: spec_gap
  5. Timeout after opus escalation → complexity: exceeded_capacity
  6. Quality gate failures → complexity: implementation_error

Output: {class, subclass, evidence} stored in task JSON.

Usage:
    from lib.failure_classify import classify_failure
    result = classify_failure(budget, gate_results, agent_output, task)

Tech spec: tech-spec-context-constructor.md → Verification § Failure Classification
"""

from __future__ import annotations

import re
from typing import Any


def classify_failure(
    budget: dict | None = None,
    gate_results: dict | None = None,
    agent_output: str = "",
    task: dict | None = None,
    escalated: bool = False,
    timed_out: bool = False,
) -> dict:
    """Classify a task failure.

    Runs 6 rules in priority order, first match wins.

    Args:
        budget: budget.json dict (from Layer 2)
        gate_results: grounding gate results dict
        agent_output: agent output log
        task: task dict (for files_touched)
        escalated: whether the task was escalated (e.g., to opus)
        timed_out: whether the task timed out

    Returns:
        Dict with class, subclass, evidence. Returns unclassified if no rule matches.
    """
    budget = budget or {}
    gate_results = gate_results or {}
    task = task or {}

    # Rule 1: Context cut → pipeline: context_cut
    result = _check_context_cut(budget, agent_output)
    if result:
        return result

    # Rule 2: Exploration death → pipeline: exploration_death
    result = _check_exploration_death(agent_output)
    if result:
        return result

    # Rule 3: Decomposition error → pipeline: decomposition_error
    result = _check_decomposition_error(gate_results, task)
    if result:
        return result

    # Rule 4: Spec gap → pipeline: spec_gap
    result = _check_spec_gap(agent_output)
    if result:
        return result

    # Rule 5: Exceeded capacity → complexity: exceeded_capacity
    result = _check_exceeded_capacity(escalated, timed_out)
    if result:
        return result

    # Rule 6: Implementation error → complexity: implementation_error
    result = _check_implementation_error(gate_results)
    if result:
        return result

    # No rule matched
    return {
        "class": "unclassified",
        "subclass": "unknown",
        "evidence": "No classification rule matched",
    }


# ── Rule 1: Context cut ──────────────────────────────────────


def _check_context_cut(budget: dict, agent_output: str) -> dict | None:
    """budget.json has cuts AND agent references cut files."""
    cuts = budget.get("cuts_made", [])
    if not cuts:
        return None

    cut_files = {c.get("file", "") for c in cuts}
    if not cut_files:
        return None

    # Check if agent output references any cut file
    referenced = []
    for f in cut_files:
        # Match filename (basename or path fragment)
        basename = f.rsplit("/", 1)[-1] if "/" in f else f
        if basename in agent_output or f in agent_output:
            referenced.append(f)

    if not referenced:
        return None

    return {
        "class": "pipeline",
        "subclass": "context_cut",
        "evidence": (
            f"Budget cut {len(cuts)} files. Agent referenced cut files: "
            f"{', '.join(referenced[:5])}"
        ),
    }


# ── Rule 2: Exploration death ─────────────────────────────────


def _check_exploration_death(agent_output: str) -> dict | None:
    """Agent used 80%+ turns with near-zero output."""
    if not agent_output:
        return None

    # Count tool invocations (Read, Grep, Glob, cat, ls patterns)
    exploration_patterns = [
        r"Read\s+file",
        r"Searching\s+for",
        r"Reading\s+file",
        r"Looking\s+at",
        r"Let me read",
        r"Let me check",
        r"Let me search",
        r"cat\s+",
        r"find\s+\.",
        r"grep\s+-",
        r"I need to find",
        r"I'll look at",
    ]

    # Count exploration-like lines
    lines = agent_output.splitlines()
    total_lines = len(lines)
    if total_lines < 10:
        return None

    exploration_count = 0
    for line in lines:
        for pattern in exploration_patterns:
            if re.search(pattern, line, re.IGNORECASE):
                exploration_count += 1
                break

    # Check for near-zero productive output
    # Look for code generation patterns
    code_patterns = [
        r"```",
        r"def\s+\w+",
        r"class\s+\w+",
        r"function\s+\w+",
        r"const\s+\w+",
        r"import\s+",
        r"Write\s+file",
        r"Edit\s+file",
    ]
    code_count = 0
    for line in lines:
        for pattern in code_patterns:
            if re.search(pattern, line, re.IGNORECASE):
                code_count += 1
                break

    # 80%+ exploration, <10% code output
    if total_lines > 0:
        exploration_ratio = exploration_count / total_lines
        code_ratio = code_count / total_lines
        if exploration_ratio > 0.8 and code_ratio < 0.1:
            return {
                "class": "pipeline",
                "subclass": "exploration_death",
                "evidence": (
                    f"Agent spent {exploration_ratio:.0%} of output on exploration "
                    f"({exploration_count}/{total_lines} lines), "
                    f"only {code_ratio:.0%} on code generation"
                ),
            }

    return None


# ── Rule 3: Decomposition error ───────────────────────────────


def _check_decomposition_error(gate_results: dict, task: dict) -> dict | None:
    """Ownership violations or undeclared files > declared files."""
    # Check for ownership violations first (higher priority)
    scope_result = gate_results.get("scope", {})
    ownership = scope_result.get("ownership_violations", [])
    if not ownership:
        checks = gate_results.get("checks", [])
        for check in checks:
            if check.get("name") == "scope" and check.get("status") == "fail":
                ownership = check.get("ownership_violations", [])
                break

    if ownership:
        return {
            "class": "pipeline",
            "subclass": "decomposition_error",
            "evidence": (
                f"Agent modified {len(ownership)} file(s) owned by other tasks: "
                f"{', '.join(str(v) for v in ownership[:5])}"
            ),
        }

    # Check undeclared files
    undeclared = scope_result.get("undeclared_files", [])
    declared = set(task.get("files_touched", []))

    if not undeclared:
        checks = gate_results.get("checks", [])
        for check in checks:
            if check.get("name") == "scope" and check.get("status") in ("fail", "warn"):
                undeclared = check.get("undeclared_files", [])
                break

    if len(undeclared) > len(declared) and len(undeclared) >= 3:
        return {
            "class": "pipeline",
            "subclass": "decomposition_error",
            "evidence": (
                f"Agent modified {len(undeclared)} undeclared files vs "
                f"{len(declared)} declared. Decomposition was likely wrong. "
                f"Undeclared: {', '.join(undeclared[:5])}"
            ),
        }

    return None


# ── Rule 4: Spec gap ─────────────────────────────────────────


def _check_spec_gap(agent_output: str) -> dict | None:
    """Agent reports blocked with ambiguous_spec or missing_dependency."""
    if not agent_output:
        return None

    gap_patterns = [
        (r"ambiguous.{0,20}spec", "ambiguous_spec"),
        (r"spec.{0,20}(unclear|ambiguous|missing|incomplete)", "ambiguous_spec"),
        (r"missing.{0,20}dependency", "missing_dependency"),
        (r"dependency.{0,20}(not|missing|absent)", "missing_dependency"),
        (r"I.{0,30}(can't|cannot|unable).{0,30}(determine|figure out|understand).{0,30}(spec|requirement)", "ambiguous_spec"),
        (r"blocked.{0,20}(by|on|waiting)", "missing_dependency"),
        (r"no.{0,20}(guidance|direction|specification).{0,20}(for|on|about)", "ambiguous_spec"),
    ]

    for pattern, subclass in gap_patterns:
        match = re.search(pattern, agent_output, re.IGNORECASE)
        if match:
            # Extract context around the match
            start = max(0, match.start() - 50)
            end = min(len(agent_output), match.end() + 50)
            context = agent_output[start:end].strip()
            return {
                "class": "pipeline",
                "subclass": subclass,
                "evidence": f"Agent reported: ...{context}...",
            }

    return None


# ── Rule 5: Exceeded capacity ─────────────────────────────────


def _check_exceeded_capacity(escalated: bool, timed_out: bool) -> dict | None:
    """Timeout after opus escalation."""
    if timed_out and escalated:
        return {
            "class": "complexity",
            "subclass": "exceeded_capacity",
            "evidence": "Task timed out even after escalation to higher-capability model",
        }

    if timed_out:
        return {
            "class": "complexity",
            "subclass": "exceeded_capacity",
            "evidence": "Task timed out",
        }

    return None


# ── Rule 6: Implementation error ──────────────────────────────


def _check_implementation_error(gate_results: dict) -> dict | None:
    """Quality gate failures (lint, typecheck, test)."""
    quality_failures = []

    # Check structured gate results
    checks = gate_results.get("checks", [])
    quality_gates = {"syntax", "lint", "typecheck", "test", "tests"}

    for check in checks:
        name = check.get("name", "")
        if name in quality_gates and check.get("status") == "fail":
            quality_failures.append(name)

    # Also check flat keys
    for gate in quality_gates:
        result = gate_results.get(gate, {})
        if isinstance(result, dict) and result.get("status") == "fail":
            quality_failures.append(gate)

    if quality_failures:
        return {
            "class": "complexity",
            "subclass": "implementation_error",
            "evidence": f"Quality gate failures: {', '.join(sorted(set(quality_failures)))}",
        }

    return None


# ── Aggregation ───────────────────────────────────────────────


def aggregate_classifications(
    classifications: list[dict],
) -> dict:
    """Aggregate failure classifications across multiple tasks.

    Args:
        classifications: list of classification dicts from classify_failure()

    Returns:
        Summary dict with counts per class/subclass, suitable for speed status.
    """
    from collections import Counter

    class_counts: Counter = Counter()
    subclass_counts: Counter = Counter()

    for c in classifications:
        cls = c.get("class", "unclassified")
        sub = c.get("subclass", "unknown")
        class_counts[cls] += 1
        subclass_counts[f"{cls}:{sub}"] += 1

    total = len(classifications)
    pipeline = class_counts.get("pipeline", 0)
    complexity = class_counts.get("complexity", 0)
    unclassified = class_counts.get("unclassified", 0)

    return {
        "total_failures": total,
        "pipeline_failures": pipeline,
        "complexity_failures": complexity,
        "unclassified": unclassified,
        "breakdown": dict(subclass_counts),
        "pipeline_ratio": round(pipeline / total, 2) if total else 0,
    }
