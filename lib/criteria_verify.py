"""Criteria-Driven Verification — Verification System, Tier 2.

Executes `verify_by` hints from the Architect's structured acceptance
criteria. Bridges structured task output to automated checks.

verify_by implementations:
  schema_check — query CSG Layer A for entity/column existence. Fallback to grep.
  file_exists  — check filesystem against project map entries.
  test         — verify test file exists + run scoped test command.
  lint         — run configured linter on relevant files.
  manual       — emit status: "unverifiable", flag for human review.

Per-criterion output: status (pass/fail/unverifiable) + evidence.

Graceful degradation: never fails because infrastructure is missing —
degrades and reports what it couldn't check.

Usage:
    from lib.criteria_verify import verify_criteria
    results = verify_criteria(task, project_root, csg=csg, project_map=pm)

Tech spec: tech-spec-context-constructor.md → Verification System § 1.2
"""

from __future__ import annotations

import os
import subprocess
from typing import Any


# ── Main entry point ─────────────────────────────────────────


def verify_criteria(
    task: dict,
    project_root: str,
    csg: dict | None = None,
    project_map: dict | None = None,
    test_command: str | None = None,
    lint_command: str | None = None,
) -> dict:
    """Verify all acceptance criteria for a task.

    Args:
        task: task dict with acceptance_criteria array
        project_root: absolute path to project root
        csg: semantic-graph.json dict (or None — falls back to grep)
        project_map: project-map.json dict (or None — falls back to filesystem)
        test_command: test runner command template (e.g. "pytest {file}")
        lint_command: linter command template (e.g. "ruff check {file}")

    Returns:
        Dict with task_id, criteria_results[], and summary.
    """
    task_id = task.get("id", "unknown")
    criteria = task.get("acceptance_criteria", [])

    # Handle legacy string format (graceful degradation)
    if isinstance(criteria, str):
        criteria = [{"criterion": criteria, "verify_by": "manual"}]

    results = []
    for crit in criteria:
        # Handle list of strings (legacy) — auto-wrap as manual
        if isinstance(crit, str):
            crit = {"criterion": crit, "verify_by": "manual"}

        criterion_text = crit.get("criterion", "")
        verify_by = crit.get("verify_by", "manual")

        result = _verify_one(
            criterion_text,
            verify_by,
            task,
            project_root,
            csg=csg,
            project_map=project_map,
            test_command=test_command,
            lint_command=lint_command,
        )
        results.append(result)

    # Summary counts
    pass_count = sum(1 for r in results if r["status"] == "pass")
    fail_count = sum(1 for r in results if r["status"] == "fail")
    unverifiable_count = sum(1 for r in results if r["status"] == "unverifiable")

    return {
        "task_id": task_id,
        "criteria_results": results,
        "summary": {
            "pass": pass_count,
            "fail": fail_count,
            "unverifiable": unverifiable_count,
        },
    }


def _verify_one(
    criterion: str,
    verify_by: str,
    task: dict,
    project_root: str,
    **kwargs: Any,
) -> dict:
    """Verify a single criterion."""
    base = {
        "criterion": criterion,
        "verify_by": verify_by,
    }

    dispatch = {
        "schema_check": _verify_schema_check,
        "file_exists": _verify_file_exists,
        "test": _verify_test,
        "lint": _verify_lint,
        "manual": _verify_manual,
    }

    handler = dispatch.get(verify_by, _verify_manual)
    try:
        result = handler(criterion, task, project_root, **kwargs)
    except Exception as e:
        result = {
            "status": "unverifiable",
            "evidence": f"Verification error: {e}",
        }

    base.update(result)
    return base


# ── schema_check ─────────────────────────────────────────────


def _verify_schema_check(
    criterion: str,
    task: dict,
    project_root: str,
    csg: dict | None = None,
    **kwargs: Any,
) -> dict:
    """Verify a criterion against CSG Layer A. Fallback to grep.

    Heuristic: parse the criterion text for entity/column names and
    check if they exist in the CSG.
    """
    # Extract entity names from criterion text
    # Look for patterns: "X model", "X table", "X column", "X exists"
    import re
    entities = re.findall(r'["`]?([A-Z][a-zA-Z_]+)["`]?\s+(?:model|table|class|entity)', criterion)
    columns = re.findall(r'["`]?([a-z_]+)["`]?\s+column', criterion)
    # Also look for "has X, Y, Z columns"
    col_list = re.findall(r'(?:has|with)\s+([a-z_, ]+)\s+columns?', criterion)
    if col_list:
        for group in col_list:
            columns.extend(c.strip() for c in group.split(",") if c.strip())

    if csg:
        return _schema_check_via_csg(entities, columns, csg)

    # Fallback: grep-based search
    return _schema_check_via_grep(entities, columns, project_root, task)


def _schema_check_via_csg(
    entities: list[str],
    columns: list[str],
    csg: dict,
) -> dict:
    """Check entities and columns against CSG nodes."""
    # Build lookup
    nodes_by_name: dict[str, list[dict]] = {}
    for node in csg.get("nodes", []):
        name = node["name"]
        if name not in nodes_by_name:
            nodes_by_name[name] = []
        nodes_by_name[name].append(node)

    evidence_parts = []
    all_found = True

    for entity in entities:
        if entity in nodes_by_name:
            node = nodes_by_name[entity][0]
            evidence_parts.append(
                f"Entity '{entity}' found at {node['file']}:{node['line']}"
            )
            # Check columns if entity has schema
            schema = node.get("schema")
            if schema and columns:
                schema_cols = {c["name"] for c in schema.get("columns", [])}
                for col in columns:
                    if col in schema_cols:
                        evidence_parts.append(f"Column '{col}' exists in {entity}")
                    else:
                        evidence_parts.append(f"Column '{col}' NOT found in {entity}")
                        all_found = False
        else:
            evidence_parts.append(f"Entity '{entity}' not found in CSG")
            all_found = False

    # If no entities were extracted but columns were, check all ORM models
    if not entities and columns:
        found_cols = set()
        for node in csg.get("nodes", []):
            schema = node.get("schema")
            if schema:
                for col in schema.get("columns", []):
                    if col["name"] in columns:
                        found_cols.add(col["name"])
                        evidence_parts.append(
                            f"Column '{col['name']}' found in {node['name']}"
                        )

        missing = set(columns) - found_cols
        for col in missing:
            evidence_parts.append(f"Column '{col}' not found in any model")
            all_found = False

    if not entities and not columns:
        return {
            "status": "unverifiable",
            "evidence": "Could not extract entity/column names from criterion text",
        }

    return {
        "status": "pass" if all_found else "fail",
        "evidence": "; ".join(evidence_parts),
    }


def _schema_check_via_grep(
    entities: list[str],
    columns: list[str],
    project_root: str,
    task: dict,
) -> dict:
    """Fallback: grep for entity/column names in files_touched."""
    files_touched = task.get("files_touched", [])
    evidence_parts = []
    all_found = True

    for entity in entities:
        found = False
        for f in files_touched:
            abs_path = os.path.join(project_root, f)
            if os.path.isfile(abs_path):
                try:
                    with open(abs_path) as fh:
                        content = fh.read()
                    if f"class {entity}" in content or f"class {entity}(" in content:
                        evidence_parts.append(f"Entity '{entity}' found via grep in {f}")
                        found = True
                        break
                except OSError:
                    pass
        if not found:
            evidence_parts.append(f"Entity '{entity}' not found via grep (no CSG available)")
            all_found = False

    if not entities and not columns:
        return {
            "status": "unverifiable",
            "evidence": "No CSG available; could not extract entities from criterion",
        }

    return {
        "status": "pass" if all_found else "fail",
        "evidence": "; ".join(evidence_parts) + " (grep fallback — no CSG)",
    }


# ── file_exists ──────────────────────────────────────────────


def _verify_file_exists(
    criterion: str,
    task: dict,
    project_root: str,
    project_map: dict | None = None,
    **kwargs: Any,
) -> dict:
    """Verify that files mentioned in the criterion exist."""
    import re

    # Extract file paths from the criterion
    paths = re.findall(r'["`]([a-zA-Z0-9_/.-]+\.[a-zA-Z0-9]+)["`]', criterion)
    if not paths:
        # Try to find paths from files_touched
        paths = task.get("files_touched", [])

    if not paths:
        return {
            "status": "unverifiable",
            "evidence": "No file paths found in criterion text",
        }

    # Build project map file set
    pm_files: set[str] = set()
    if project_map:
        for f in project_map.get("files", []):
            pm_files.add(f["path"])

    evidence_parts = []
    all_found = True

    for path in paths:
        abs_path = os.path.join(project_root, path)
        if path in pm_files or os.path.isfile(abs_path):
            line_count = None
            if project_map:
                for f in project_map.get("files", []):
                    if f["path"] == path:
                        line_count = f.get("lines")
                        break
            ev = f"File '{path}' exists"
            if line_count is not None:
                ev += f" ({line_count} lines)"
            evidence_parts.append(ev)
        else:
            evidence_parts.append(f"File '{path}' not found")
            all_found = False

    return {
        "status": "pass" if all_found else "fail",
        "evidence": "; ".join(evidence_parts),
    }


# ── test ─────────────────────────────────────────────────────


def _verify_test(
    criterion: str,
    task: dict,
    project_root: str,
    test_command: str | None = None,
    **kwargs: Any,
) -> dict:
    """Verify via test: check test file exists + optionally run test.

    Without a test command configured, only checks for test file existence.
    """
    files_touched = task.get("files_touched", [])

    # Find test files related to files_touched
    test_files = _find_test_files(files_touched, project_root)

    if not test_files:
        return {
            "status": "fail",
            "evidence": f"No test files found for files: {', '.join(files_touched[:3])}",
        }

    evidence_parts = [f"Test file(s) found: {', '.join(test_files[:3])}"]

    # Run tests if command is configured
    if test_command:
        for test_file in test_files[:5]:  # Limit to 5 test files
            abs_test = os.path.join(project_root, test_file)
            cmd = test_command.replace("{file}", abs_test)
            try:
                result = subprocess.run(
                    cmd, shell=True, capture_output=True, text=True,
                    cwd=project_root, timeout=60,
                )
                if result.returncode == 0:
                    evidence_parts.append(f"Tests pass: {test_file}")
                else:
                    evidence_parts.append(f"Tests FAIL: {test_file}")
                    return {
                        "status": "fail",
                        "evidence": "; ".join(evidence_parts),
                    }
            except (subprocess.TimeoutExpired, OSError) as e:
                evidence_parts.append(f"Test execution error: {e}")
                return {
                    "status": "unverifiable",
                    "evidence": "; ".join(evidence_parts),
                }
    else:
        evidence_parts.append("Test runner not configured — file existence only")

    return {
        "status": "pass",
        "evidence": "; ".join(evidence_parts),
    }


def _find_test_files(files_touched: list[str], project_root: str) -> list[str]:
    """Find test files corresponding to the files touched by a task."""
    test_files = []

    for f in files_touched:
        basename = os.path.basename(f)
        name_no_ext = os.path.splitext(basename)[0]
        dirname = os.path.dirname(f)

        # Common test file patterns
        candidates = [
            # Same directory: test_*.py
            os.path.join(dirname, f"test_{basename}"),
            # tests/ directory: test_*.py
            os.path.join("tests", f"test_{name_no_ext}.py"),
            os.path.join("tests", dirname, f"test_{name_no_ext}.py"),
            # __tests__/ directory (JS/TS)
            os.path.join(dirname, "__tests__", basename),
            # *.test.ts / *.spec.ts
            os.path.join(dirname, f"{name_no_ext}.test.ts"),
            os.path.join(dirname, f"{name_no_ext}.spec.ts"),
            os.path.join(dirname, f"{name_no_ext}.test.js"),
            # Shell tests
            os.path.join("tests", f"test_{name_no_ext}.sh"),
        ]

        for candidate in candidates:
            abs_candidate = os.path.join(project_root, candidate)
            if os.path.isfile(abs_candidate):
                test_files.append(candidate)

    return list(set(test_files))  # Deduplicate


# ── lint ─────────────────────────────────────────────────────


def _verify_lint(
    criterion: str,
    task: dict,
    project_root: str,
    lint_command: str | None = None,
    **kwargs: Any,
) -> dict:
    """Verify via linter: run configured linter on relevant files."""
    if not lint_command:
        return {
            "status": "unverifiable",
            "evidence": "Linter not configured in speed.toml",
        }

    files_touched = task.get("files_touched", [])
    if not files_touched:
        return {
            "status": "unverifiable",
            "evidence": "No files_touched to lint",
        }

    evidence_parts = []
    all_clean = True

    for f in files_touched:
        abs_path = os.path.join(project_root, f)
        if not os.path.isfile(abs_path):
            continue

        cmd = lint_command.replace("{file}", abs_path)
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                cwd=project_root, timeout=30,
            )
            if result.returncode == 0:
                evidence_parts.append(f"Lint clean: {f}")
            else:
                all_clean = False
                # Include first few lines of lint output
                output = result.stdout[:200] or result.stderr[:200]
                evidence_parts.append(f"Lint errors in {f}: {output}")
        except (subprocess.TimeoutExpired, OSError) as e:
            evidence_parts.append(f"Lint execution error for {f}: {e}")
            return {
                "status": "unverifiable",
                "evidence": "; ".join(evidence_parts),
            }

    if not evidence_parts:
        return {
            "status": "unverifiable",
            "evidence": "No files available to lint",
        }

    return {
        "status": "pass" if all_clean else "fail",
        "evidence": "; ".join(evidence_parts),
    }


# ── manual ───────────────────────────────────────────────────


def _verify_manual(
    criterion: str,
    task: dict,
    project_root: str,
    **kwargs: Any,
) -> dict:
    """Manual verification — always unverifiable, flags for human review."""
    return {
        "status": "unverifiable",
        "evidence": "Manual verification required — cannot be automated",
    }
