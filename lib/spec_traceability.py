"""Spec Traceability — Verification System.

Two phases of spec coverage checking:

1. Spec-to-task (during `speed verify`): Parse spec for requirements,
   check each against union of all tasks' spec_references. Feeds
   uncovered requirements to the LLM Plan Verifier as structured input.

2. Code-to-spec (during `speed integrate`): Re-run criteria verification
   across all tasks against merged codebase + compute coverage metric.
   Informational, not blocking.

Usage:
    from lib.spec_traceability import spec_to_task_check, code_to_spec_check
    uncovered = spec_to_task_check(spec_content, tasks)
    coverage = code_to_spec_check(tasks, project_root, csg, project_map)

Tech spec: tech-spec-context-constructor.md → Verification § Spec Traceability
"""

from __future__ import annotations

import re
from typing import Any


# ══════════════════════════════════════════════════════════════
# 1. Spec-to-Task Pre-Check
# ══════════════════════════════════════════════════════════════


def spec_to_task_check(
    spec_content: str,
    tasks: list[dict],
) -> dict:
    """Check that the task plan covers the product spec.

    Parses spec for requirements (headings, bullets, MUST/SHALL keywords),
    then checks each against the union of all tasks' spec_references,
    descriptions, and files_touched.

    Args:
        spec_content: full product spec markdown
        tasks: all tasks in the DAG

    Returns:
        Dict with covered/uncovered requirements and coverage ratio.
    """
    # Extract requirements from spec
    requirements = _extract_requirements(spec_content)

    if not requirements:
        return {
            "requirements_found": 0,
            "covered": [],
            "uncovered": [],
            "coverage_ratio": 1.0,
            "note": "No structured requirements found in spec",
        }

    # Build coverage index from tasks
    coverage_index = _build_coverage_index(tasks)

    # Check each requirement
    covered = []
    uncovered = []

    for req in requirements:
        covering_tasks = _find_covering_tasks(req, coverage_index, tasks)
        if covering_tasks:
            covered.append({
                "requirement": req["text"],
                "section": req["section"],
                "covered_by": covering_tasks,
            })
        else:
            uncovered.append({
                "requirement": req["text"],
                "section": req["section"],
            })

    total = len(requirements)
    ratio = len(covered) / total if total > 0 else 1.0

    return {
        "requirements_found": total,
        "covered": covered,
        "uncovered": uncovered,
        "coverage_ratio": round(ratio, 2),
    }


def _extract_requirements(spec_content: str) -> list[dict]:
    """Extract structured requirements from spec markdown.

    Looks for:
    - Bullets under requirement headings
    - Lines containing MUST, SHALL, SHOULD, REQUIRED
    - Numbered lists with action verbs
    """
    requirements = []
    lines = spec_content.splitlines()
    current_section = ""

    # Keywords that signal a requirement
    requirement_keywords = re.compile(
        r"\b(MUST|SHALL|SHOULD|REQUIRED|must|shall|should|needs?\s+to|has\s+to)\b"
    )

    for i, line in enumerate(lines):
        # Track section headings
        heading = re.match(r"^(#{1,4})\s+(.+)", line)
        if heading:
            current_section = heading.group(2).strip()
            continue

        stripped = line.strip()
        if not stripped:
            continue

        # Bullet point requirements
        bullet_match = re.match(r"^[-*]\s+(.+)", stripped)
        if bullet_match:
            text = bullet_match.group(1).strip()
            # Require minimum length and either a keyword or an action verb
            if len(text) > 20 and (
                requirement_keywords.search(text)
                or re.match(r"^(The|A|An|Each|Every|All)\s+", text)
            ):
                requirements.append({
                    "text": text,
                    "section": current_section,
                    "line": i + 1,
                })

        # Non-bullet lines with requirement keywords
        elif requirement_keywords.search(stripped) and len(stripped) > 30:
            requirements.append({
                "text": stripped,
                "section": current_section,
                "line": i + 1,
            })

    return requirements


def _build_coverage_index(tasks: list[dict]) -> dict:
    """Build an index of what the task plan covers.

    Returns dict with:
    - spec_refs: set of (spec, section) tuples from spec_references
    - entities: set of entity names mentioned across all tasks
    - files: set of all files_touched
    - descriptions: concatenated description text
    """
    spec_refs: set[tuple[str, str]] = set()
    entities: set[str] = set()
    files: set[str] = set()
    desc_text = ""

    for task in tasks:
        # Collect spec references
        for ref in task.get("spec_references", []):
            spec_refs.add((ref.get("spec", ""), ref.get("section", "")))

        # Collect entity-like names from files_touched
        for f in task.get("files_touched", []):
            files.add(f)
            # Extract entity names from file paths (e.g., models/book.py → Book)
            basename = f.rsplit("/", 1)[-1] if "/" in f else f
            stem = basename.rsplit(".", 1)[0] if "." in basename else basename
            entities.add(stem.lower())
            # CamelCase version
            entities.add(stem.capitalize())

        # Accumulate descriptions
        desc_text += " " + task.get("description", "")
        desc_text += " " + task.get("title", "")

        # Collect acceptance criteria text
        _criteria = task.get("acceptance_criteria", [])
        if isinstance(_criteria, str):
            _criteria = [line.strip() for line in _criteria.split('\n') if line.strip()]
        for c in _criteria:
            if isinstance(c, dict):
                desc_text += " " + c.get("criterion", "")
            else:
                desc_text += " " + str(c)

    return {
        "spec_refs": spec_refs,
        "entities": entities,
        "files": files,
        "desc_text": desc_text.lower(),
    }


def _find_covering_tasks(
    requirement: dict,
    coverage_index: dict,
    tasks: list[dict],
) -> list[str]:
    """Find tasks that cover a given requirement."""
    req_text = requirement["text"].lower()
    req_section = requirement.get("section", "")

    covering = []

    for task in tasks:
        tid = task.get("id", "?")

        # Check 1: Direct spec_reference match
        for ref in task.get("spec_references", []):
            if ref.get("section", "").lower() == req_section.lower():
                covering.append(tid)
                break
        else:
            # Check 2: Keyword overlap between requirement and task description
            task_text = (
                task.get("description", "") + " " +
                task.get("title", "")
            ).lower()

            # Extract meaningful words (4+ chars, not common)
            req_words = set(re.findall(r"\b[a-z]{4,}\b", req_text))
            task_words = set(re.findall(r"\b[a-z]{4,}\b", task_text))
            common_words = {"that", "this", "with", "from", "have", "will",
                           "each", "must", "shall", "should", "when", "where",
                           "they", "them", "than", "also", "into", "been"}
            req_words -= common_words
            task_words -= common_words

            overlap = req_words & task_words
            if len(overlap) >= 2:
                covering.append(tid)

    return covering


# ══════════════════════════════════════════════════════════════
# 2. Code-to-Spec Check (Integration Time)
# ══════════════════════════════════════════════════════════════


def code_to_spec_check(
    tasks: list[dict],
    project_root: str,
    csg: dict | None = None,
    project_map: dict | None = None,
) -> dict:
    """Re-run criteria verification across all tasks and compute coverage.

    Runs at integration time. Informational, not blocking.

    Args:
        tasks: all completed tasks
        project_root: absolute path to project root
        csg: semantic-graph.json dict
        project_map: project-map.json dict

    Returns:
        Coverage summary dict.
    """
    total_criteria = 0
    passed_criteria = 0
    failed_criteria = 0
    unverifiable_criteria = 0
    per_task = []

    try:
        from lib.criteria_verify import verify_criteria
    except ImportError:
        return {
            "status": "unavailable",
            "reason": "criteria_verify module not found",
        }

    for task in tasks:
        tid = task.get("id", "?")
        criteria = task.get("acceptance_criteria", [])

        if not criteria:
            continue

        verify_result = verify_criteria(
            task, project_root,
            csg=csg, project_map=project_map,
        )
        criteria_results = verify_result.get("criteria_results", [])

        task_pass = 0
        task_fail = 0
        task_unverifiable = 0

        for r in criteria_results:
            total_criteria += 1
            status = r.get("status", "unverifiable")
            if status == "pass":
                passed_criteria += 1
                task_pass += 1
            elif status == "fail":
                failed_criteria += 1
                task_fail += 1
            else:
                unverifiable_criteria += 1
                task_unverifiable += 1

        per_task.append({
            "task_id": tid,
            "total": len(criteria_results),
            "pass": task_pass,
            "fail": task_fail,
            "unverifiable": task_unverifiable,
        })

    verifiable = passed_criteria + failed_criteria
    coverage = round(passed_criteria / verifiable, 2) if verifiable > 0 else 0

    return {
        "total_criteria": total_criteria,
        "passed": passed_criteria,
        "failed": failed_criteria,
        "unverifiable": unverifiable_criteria,
        "coverage_ratio": coverage,
        "per_task": per_task,
    }


# ══════════════════════════════════════════════════════════════
# 3. Format for Plan Verifier
# ══════════════════════════════════════════════════════════════


def format_uncovered_for_verifier(traceability_result: dict) -> str:
    """Format uncovered requirements as structured input for the Plan Verifier.

    Args:
        traceability_result: output from spec_to_task_check()

    Returns:
        Markdown string to inject into the Plan Verifier prompt.
    """
    uncovered = traceability_result.get("uncovered", [])
    ratio = traceability_result.get("coverage_ratio", 1.0)
    total = traceability_result.get("requirements_found", 0)

    if not uncovered:
        return ""

    lines = [
        f"## Spec Coverage Analysis\n",
        f"**Coverage:** {ratio:.0%} ({total - len(uncovered)}/{total} requirements covered)\n",
        f"**Uncovered requirements ({len(uncovered)}):**\n",
    ]

    for req in uncovered:
        section = req.get("section", "")
        text = req.get("requirement", "")
        prefix = f"[{section}] " if section else ""
        lines.append(f"- {prefix}{text}")

    lines.append("")
    lines.append("These requirements from the product spec are not explicitly "
                 "covered by any task's spec_references or description. "
                 "Verify whether they are addressed implicitly or if the plan has gaps.\n")

    return "\n".join(lines)
