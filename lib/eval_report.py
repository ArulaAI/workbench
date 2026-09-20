"""Build the feature acceptance report from planned test scenarios.

Executable scenario evidence is authoritative. The optional evaluator output
may classify only semantic criteria that deterministic checks could not verify.
"""

from __future__ import annotations

import argparse
from collections import Counter
import html
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.criteria_verify import verify_criteria, _find_test_files
from lib.eval_criteria import criteria_items, criterion_ids, normalize_criteria as _structured_criteria
from lib.eval_execution import aggregate_status, commands_for_file, evidence_artifact, load_config, run_command
from lib.eval_runtime import build_snapshot, task_scenarios, read_object
from lib.test_spec import (coverage_gaps, parse_evaluation_gates,
                           parse_scenarios, parse_traceability)


# Required checks without a configured verifier remain unverifiable.
VALID_STATUSES = {"pass", "partial", "fail", "unverifiable", "not_applicable", "blocked_upstream"}
NON_BLOCKING_STATUSES = {"not_applicable"}


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name, dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2)
            handle.write("\n")
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name, dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _tasks(tasks_dir: Path) -> list[dict[str, Any]]:
    tasks = []
    for path in sorted(tasks_dir.glob("*.json")):
        task = _read_json(path, {})
        if isinstance(task, dict):
            tasks.append(task)
    return tasks


def _scenario_result(
    scenario: dict[str, str],
    owners: list[dict[str, Any]],
) -> dict[str, Any]:
    scenario_id = scenario["id"]
    if len(owners) != 1:
        # No mapping is a coverage gap, not a product defect: it blocks
        # acceptance as unverifiable without filing a defect. Conflicting
        # owners make the evidence ambiguous and are treated as a failure.
        if not owners:
            status = "unverifiable"
            reason = "No test mapped to this scenario"
        else:
            status = "fail"
            reason = "Scenario has multiple task owners"
        return {
            "id": scenario_id,
            "kind": "scenario",
            "area": scenario.get("area", ""),
            "title": scenario["scenario"],
            "expected": scenario["expected"],
            "level": scenario["level"],
            "task_id": None,
            "tier": "executable",
            "status": status,
            "evidence": reason,
            "command": "",
            "required": True,
        }

    owner = owners[0]
    evidence = next(
        (
            result
            for result in owner.get("scenario_results", [])
            if result.get("scenario_id") == scenario_id
        ),
        None,
    )
    if not evidence:
        status = "unverifiable"
        detail = "Planned scenario has not been executed on the integrated tree"
        command = ""
        executed_at = None
    else:
        raw_status = evidence.get("status", "unverifiable")
        status = raw_status if raw_status in VALID_STATUSES else "unverifiable"
        detail = evidence.get("evidence", "No execution evidence recorded")
        command = evidence.get("command", "")
        executed_at = evidence.get("executed_at")

    return {
        "id": scenario_id,
        "kind": "scenario",
        "area": scenario.get("area", ""),
        "title": scenario["scenario"],
        "expected": scenario["expected"],
        "level": scenario["level"],
        "task_id": str(owner.get("id", "")),
        "tier": "executable",
        "status": status,
        "evidence": detail,
        "command": command,
        "executed_at": executed_at,
        "required": True,
    }


def _mapped_scenario_result(
    scenario: dict[str, str],
    executed: dict[str, Any],
) -> dict[str, Any]:
    """Result for a scenario executed through the test-plan.json mapping."""
    raw_status = executed.get("status", "unverifiable")
    task_id = str(executed.get("task_id") or "") or None
    return {
        "id": scenario["id"],
        "kind": "scenario",
        "area": scenario.get("area", ""),
        "title": scenario["scenario"],
        "expected": scenario["expected"],
        "level": scenario["level"],
        "task_id": task_id,
        "tier": "executable",
        "status": raw_status if raw_status in VALID_STATUSES else "unverifiable",
        "evidence": executed.get("evidence", "No execution evidence recorded"),
        "command": executed.get("command", ""),
        "executed_at": executed.get("executed_at"),
        "required": True,
    }


def _present_files(files: Any, project_root: Path) -> list[str]:
    """Touched paths that still exist, selected the way _verify_lint selects them.

    A task that deleted or renamed a file it touched must not hand the vanished
    path to a linter. The linter would exit non-zero on the missing file, and
    the criterion would read as a product failure that no further work can clear.
    """
    if not isinstance(files, (list, tuple)):
        return []
    return [name for name in files
            if isinstance(name, str) and os.path.isfile(os.path.join(str(project_root), name))]


def _semantic_results(
    tasks: list[dict[str, Any]],
    project_root: Path,
    config: dict | None = None,
    evidence_dir: Path | None = None,
    selection: dict | None = None,
    scenario_results: list[dict] | None = None,
) -> list[dict[str, Any]]:
    config = config if config is not None else load_config(project_root)
    evidence_dir = evidence_dir or Path(tempfile.mkdtemp(prefix="speed-eval-criteria-"))
    results = []
    for task in tasks:
        criteria = _structured_criteria(task.get("acceptance_criteria", []))
        if isinstance(criteria, str):
            criteria = [{"criterion": criteria, "verify_by": "manual", "scenario_ids": []}]
        for index, item in enumerate(criteria, 1):
            criterion = item if isinstance(item, dict) else {"criterion": str(item), "verify_by": "manual"}
            # Mapped criteria are established by their scenarios, not a second
            # hidden invocation of the entire task's test suite.
            verify_by = criterion.get("verify_by", "manual")
            if criterion.get("scenario_ids") and verify_by != "test":
                # Preserve the legacy mapped non-test path; presenting test
                # criteria must not introduce additional verifier executions.
                continue
            outcome = {"status": "unverifiable", "evidence": "Manual review required", "command": ""}
            if verify_by == "test" and (selection is not None or criterion.get("scenario_ids")):
                mapped_ids = set((selection or {}).get("criterion_scenarios", {}).get(str(task["id"]), {}).get(
                    str(index), criterion_ids(criterion)))
                evidence = [r for r in scenario_results or [] if r["id"] in mapped_ids]
                if (selection or {}).get("source") == "task_criteria":
                    # A feature scenario may span several tasks. A criterion
                    # inherits only the executions owned by its own task.
                    evidence = [{**r, "executions": own,
                                 "status": aggregate_status(own)}
                                for r in evidence
                                for own in [[e for e in r.get("executions", [])
                                             if str(e.get("task_id")) == str(task["id"])]]]
                if evidence and {r["id"] for r in evidence} == mapped_ids:
                    outcome = {"status": aggregate_status(evidence), "command": "",
                               "evidence": "Reused declared criterion scenarios: " + ", ".join(sorted(mapped_ids)),
                               "executions": [e for r in evidence for e in r.get("executions", [])]}
                else:
                    outcome = {"status": "unverifiable", "command": "",
                               "evidence": "Test criterion has no explicit scenario association; include [SCENARIO-ID] in the task criterion and tag its individual test. "
                                           "A whole-file test run cannot establish criterion coverage."}
            elif verify_by in ("test", "lint"):
                touched = task.get("files_touched", [])
                files = (_find_test_files(touched, str(project_root))
                         if verify_by == "test" else _present_files(touched, project_root))
                files = sorted(set(files))
                if not files:
                    # Match the legacy verifier for a required test with no
                    # test files. Deleted lint targets remain unverifiable.
                    if verify_by == "test":
                        outcome["status"] = "fail"
                    outcome["evidence"] = f"No files found for the required {verify_by} criterion"
                elif any(not (project_root / name).resolve().is_relative_to(project_root.resolve()) for name in files):
                    outcome["evidence"] = "Criterion file leaves the project boundary"
                else:
                    executions = []
                    for name in files:
                        commands = commands_for_file(config, verify_by, task, name)
                        if not commands:
                            executions.append({"status": "unverifiable", "command": "",
                                               "evidence": f"No unambiguous configured {verify_by} command for {name}; "
                                                           "map the criterion to scenarios with explicit commands"})
                        for command in commands:
                            try:
                                executions.append(run_command(command, [str(project_root / name)], project_root,
                                                              evidence_dir, gate=verify_by))
                            except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
                                executions.append({"status": "unverifiable", "evidence": str(exc), "command": ""})
                    outcome = {"status": aggregate_status(executions),
                               "evidence": "; ".join(r["evidence"] for r in executions),
                               "command": "; ".join(r["command"] for r in executions),
                               "executions": executions}
            elif verify_by != "manual":
                verification = verify_criteria({**task, "acceptance_criteria": [criterion]}, str(project_root))
                outcome = verification["criteria_results"][0]
            results.append({
                "id": f"TASK-{task.get('id', 'unknown')}-CRIT-{index:02d}",
                "kind": "criterion", "area": "Task criteria", "title": criterion.get("criterion", ""),
                "expected": criterion.get("criterion", ""), "level": verify_by,
                "task_id": str(task.get("id", "")),
                "tier": "semantic" if verify_by == "manual" else "deterministic",
                "status": outcome["status"], "evidence": outcome["evidence"],
                "command": outcome.get("command", ""), "required": True,
                "executions": outcome.get("executions", []),
            })
    return results


def _counts(results: list[dict]) -> dict:
    counts = {status: sum(r["status"] == status for r in results)
              for status in ("pass", "partial", "fail", "unverifiable", "not_applicable", "blocked_upstream")}
    return {"total": len(results), **counts,
            "applicable": len(results) - counts["not_applicable"],
            "examined": len(results) - counts["unverifiable"],
            "not_examined": counts["unverifiable"]}


def _fold_criteria(results: list[dict], tasks: list[dict], selection: dict | None) -> list[dict]:
    """Present one-to-one test claims on their scenario without losing status."""
    associations = {}
    for task in tasks:
        for index, criterion in enumerate(criteria_items(task), 1):
            ids = (selection or {}).get("criterion_scenarios", {}).get(str(task["id"]), {}).get(
                str(index), criterion_ids(criterion))
            associations[f"TASK-{task['id']}-CRIT-{index:02d}"] = set(ids)
    scenarios = {r["id"]: r for r in results if r["kind"] == "scenario"}
    kept = []
    for result in results:
        ids = associations.get(result["id"], set())
        if result["kind"] == "criterion" and result["level"] == "test" and len(ids) == 1:
            scenario = scenarios.get(next(iter(ids)))
            if scenario is not None:
                # Full criterion evidence remains inspectable, including its
                # task-specific status when multiple tasks share a scenario.
                scenario.setdefault("criteria", []).append(result)
                continue
        kept.append(result)
    return kept


def _apply_judgment(
    results: list[dict[str, Any]],
    judgment: dict[str, Any] | None,
) -> None:
    if not isinstance(judgment, dict) or not isinstance(judgment.get("results"), list):
        return
    by_id = {
        item.get("id"): item
        for item in judgment.get("results", [])
        if isinstance(item, dict)
    }
    for result in results:
        judged = by_id.get(result["id"])
        if (
            result["tier"] != "semantic"
            or result["status"] != "unverifiable"
            or not judged
        ):
            continue
        status = judged.get("status")
        if status not in {"pass", "partial", "fail", "unverifiable"} or not judged.get("evidence"):
            continue
        result["status"] = status
        result["evidence"] = judged.get("evidence", result["evidence"])
        result["judged_by"] = "evaluator"


def _evidence_type(result: dict[str, Any]) -> str:
    """What a result can support, in the course's own words.

    An executed failure is a counterexample. An executed pass is statistical
    (this example passed), except a deterministic check such as file existence,
    a schema match or a clean lint run, which is proof within its ruleset. A
    judge's verdict is an opinion. No execution is silence.
    """
    status = result.get("status")
    if result.get("judged_by") or result.get("tier") == "manual":
        return "opinion"
    if status == "unverifiable":
        return "silence"
    if status == "not_applicable":
        return "none"
    if status in ("fail", "partial", "blocked_upstream"):
        return "counterexample"
    if result.get("kind") == "criterion" and result.get("level") in (
        "file_exists",
        "schema_check",
        "lint",
    ):
        return "proof"
    return "statistical"


def reclassify_blocked_upstream(
    results: list[dict[str, Any]], edges: dict[str, list[str]],
) -> list[dict[str, Any]]:
    """Annotate failed prerequisites without inferring causality or hiding failure.

    The compatibility name is retained for callers. A test that executed and
    failed remains failed, even in a dependency cycle.
    """
    statuses = {r["id"]: r.get("status") for r in results}
    for result in results:
        seen = {result["id"]}
        pending = list(edges.get(result["id"], []))
        failed = []
        while pending:
            node = pending.pop(0)
            if node in seen:
                continue
            seen.add(node)
            if statuses.get(node) == "fail":
                failed.append(node)
            pending.extend(edges.get(node, []))
        if failed and result.get("status") == "fail":
            result["failed_dependencies"] = failed
    return results


def _gate_result(name: str, evidence: str, status: str = "unverifiable") -> dict:
    return {"id": name, "kind": "gate", "area": "Acceptance gates", "title": evidence,
            "expected": evidence, "level": "gate", "task_id": None, "tier": "deterministic",
            "status": status, "evidence": evidence, "command": "", "required": True}


def build_report(
    feature: str,
    project_root: Path,
    tasks_dir: Path,
    test_spec_path: Path,
    judgment: dict[str, Any] | None = None,
    scenario_results: list[dict[str, Any]] | None = None,
    task_id: str | None = None,
    test_plan_path: Path | None = None,
    runner_config: dict | None = None,
    evidence_dir: Path | None = None,
    criteria_results: list[dict] | None = None,
    context: dict | None = None,
) -> dict[str, Any]:
    """Assemble the acceptance report.

    scenario_results holds per-scenario outcomes produced by running the
    test-plan.json mapping (speed eval writes them to scenario-results.json).
    All current sources contribute; executed failures cannot be overridden.

    task_id limits the report to one task: its criteria, and the scenarios it
    owns or that were executed for it. Feature-level unmapped scenarios are
    left out of a task-scoped report.
    """
    tasks = _tasks(tasks_dir)
    if task_id is not None:
        tasks = [task for task in tasks if str(task.get("id", "")) == str(task_id)]
    spec_text = test_spec_path.read_text(encoding="utf-8")
    scenarios = parse_scenarios(spec_text)
    traces = parse_traceability(spec_text)
    scenario_counts = Counter(scenario["id"] for scenario in scenarios)
    executed_by_id: dict[str, list[dict[str, Any]]] = {}
    for item in scenario_results or []:
        if isinstance(item, dict) and item.get("scenario_id"):
            executed_by_id.setdefault(str(item["scenario_id"]), []).append(item)
    results = []
    selection = (context or {}).get("selection")
    if task_id is not None and selection is None:
        selection = {"mode": "task", "task_id": task_id, "gaps": [],
                     "scenario_ids": sorted(set().union(*(task_scenarios(t) for t in tasks))) if tasks else []}
    selected_ids = set((selection or {}).get("scenario_ids", []))
    for scenario in scenarios:
        owners = [task for task in tasks if scenario["id"] in task_scenarios(task)]
        executions = list(executed_by_id.get(scenario["id"], []))
        # Direct report callers may supply task results as well as mappings.
        # Keep every distinct source, including non-passing execution evidence.
        for owner in owners:
            for execution in owner.get("scenario_results", []):
                if execution.get("scenario_id") == scenario["id"] and execution not in executions:
                    executions.append(execution)
        if task_id is not None and not owners and not executions and scenario["id"] not in selected_ids:
            continue
        if executions:
            combined = {"status": aggregate_status(executions),
                        "evidence": "; ".join(str(e.get("evidence", "No evidence")) for e in executions),
                        "command": "; ".join(e.get("command", "") for e in executions if e.get("command")),
                        "task_id": next((e.get("task_id") for e in executions if e.get("task_id")),
                                        str(owners[0]["id"]) if len(owners) == 1 else None),
                        "executed_at": max((e.get("executed_at") or "" for e in executions), default="")}
            result = _mapped_scenario_result(scenario, combined)
            result["executions"] = executions
        else:
            result = _scenario_result(scenario, owners)
        if scenario_counts[scenario["id"]] > 1:
            result["status"] = "fail"
            result["evidence"] = "Duplicate scenario ID in test spec"
        if len(owners) > 1 and (selection or {}).get("source") != "task_criteria":
            result["status"] = "fail"
            result["evidence"] += "; conflicting task owners"
        results.append(result)

    for index, gap in enumerate((selection or {}).get("gaps", []), 1):
        results.append(_gate_result(f"SELECTION-{index:02d}", gap))
    for task in tasks:
        criteria = _structured_criteria(task.get("acceptance_criteria", []))
        count = len(criteria) if isinstance(criteria, list) else int(bool(criteria))
        for index in (selection or {}).get("criterion_scenarios", {}).get(str(task["id"]), {}):
            if int(index) > count:
                results.append(_gate_result(f"CRITERION-{task['id']}-{index}",
                    f"Mapping references absent acceptance criterion {index} on task {task['id']}"))

    known = {s["id"] for s in scenarios}
    missing = set().union(*(task_scenarios(t) for t in tasks)) - known if tasks else set()
    for sid in sorted(missing):
        results.append(_gate_result(f"MISSING-{sid}", f"Required scenario {sid} is absent from the catalog"))
    gaps = coverage_gaps(spec_text) if task_id is None or not scenarios else []
    for index, gap in enumerate(gaps, 1):
        results.append(_gate_result(f"COVERAGE-{index:02d}", gap))
    # Feature-wide human/release gates do not change a task-only verdict.
    if task_id is None:
        for index, gate in enumerate(parse_evaluation_gates(spec_text), 1):
            status = gate["status"].lower()
            if status not in ("pass", "fail") or not gate["evidence"].strip():
                status = "unverifiable"
            result = _gate_result(f"GATE-{index:02d}", f"{gate['gate']}: {gate['evidence'] or 'No evidence'}", status)
            result["tier"] = "manual"
            results.append(result)

    if criteria_results is None:
        criteria_results = _semantic_results(tasks, project_root, runner_config, evidence_dir, selection, results)
    # Do not mutate the cached deterministic results while applying a judgment.
    results.extend(json.loads(json.dumps(criteria_results)))
    _apply_judgment(results, judgment)
    if test_plan_path is None:
        test_plan_path = tasks_dir.parent / "test-plan.json"
    edges: dict[str, list[str]] = {}
    if test_plan_path.exists():
        plan = read_object(test_plan_path)
        for case in plan.get("test_cases", []):
            sid = case.get("scenario_id")
            if sid:
                edges.setdefault(sid, []).extend(case.get("depends_on_scenarios") or [])
    reclassify_blocked_upstream(results, edges)

    build_after = build_snapshot(project_root)
    build = {"before": context.get("build_before") if context else build_after, "after": build_after}
    if context:
        before = build["before"] if isinstance(build["before"], dict) else None
        after = build_after if isinstance(build_after, dict) else None
        # An absent snapshot is not a clean one: nothing then establishes that
        # the tree the evidence came from is the tree being reported on.
        absent = [name for name, snapshot in (("build_before", before), ("build_after", after))
                  if snapshot is None]
        if absent:
            results.append(_gate_result(
                "BUILD-PROVENANCE",
                "Build provenance is unverifiable: the evaluation context carries no "
                + " or ".join(absent),
            ))
        elif not before.get("available") or before.get("fingerprint") != after.get("fingerprint"):
            results.append(_gate_result("BUILD-UNCHANGED", "The tested tree is unavailable or changed during evaluation"))
        if task_id is None:
            if before is not None and before.get("dirty"):
                results.append(_gate_result("BUILD-COMMITTED", "The tested working tree has uncommitted changes"))
            if not context.get("integration_verified"):
                results.append(_gate_result("BUILD-INTEGRATED", "Integration has not completed successfully for this feature"))

    for result in results:
        result["traces"] = traces.get(result["id"], []) if result["kind"] == "scenario" else []
        result["evidence_type"] = _evidence_type(result)
        # Evidence text may come from shared verifiers; keep the report free of
        # em-dashes so it can be quoted in course material as is.
        result["evidence"] = str(result.get("evidence", "")).replace(" \u2014 ", ", ").replace("\u2014", ",")

    # Unavailable required tools are coverage gaps and block acceptance.
    applicable = [
        result for result in results
        if result["status"] not in NON_BLOCKING_STATUSES
    ]
    accepted = bool(applicable) and all(
        result["status"] == "pass" for result in applicable
    )
    criteria = [r for r in results if r["kind"] == "criterion"]
    criteria_summary = {**_counts(criteria), "discharged": sum(r["status"] == "pass" for r in criteria),
                        "reused": sum(r["level"] == "test" and r["evidence"].startswith(
                            "Reused declared criterion scenarios:") for r in criteria)}
    results = _fold_criteria(results, tasks, selection)
    # Headline counts describe scenarios. The verdict still includes every
    # criterion and gate, without counting identical folded outcomes twice.
    checks = results + [c for r in results for c in r.get("criteria", []) if c["status"] != r["status"]]
    return {
        "feature": feature,
        "task_id": task_id,
        "commit": build_after["head_commit"] if not build_after["dirty"] else None,
        "build": build,
        "run_id": context.get("run_id") if context else None,
        "test_spec_sha256": context.get("test_spec_sha256") if context else None,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "test_spec": (context or {}).get("test_spec") or str(test_spec_path),
        "accepted": accepted,
        "summary": _counts([r for r in results if r["kind"] == "scenario"]),
        "criteria_summary": criteria_summary,
        "gate_summary": _counts([r for r in results if r["kind"] == "gate"]),
        "checks_summary": _counts(checks),
        "results": results,
        "criteria_results": criteria_results,
        "selection": selection,
    }


def _fingerprint(report: dict[str, Any]) -> str | None:
    """The tested tree's fingerprint, or None when no snapshot was recorded."""
    before = (report.get("build") or {}).get("before")
    return before.get("fingerprint") if isinstance(before, dict) else None


def _scenario_table(report: dict[str, Any]) -> list[str]:
    """Show the human-authored expectation beside actual runner evidence.

    A passing assertion is not an independent review of spec/test alignment.
    Do not invent actual application values that the runner never recorded.
    """
    def cell(value: Any) -> str:
        text = html.escape(str(value or ""), quote=False)
        text = re.sub(r"([\\`*_{}\[\]])", r"\\\1", text)
        return text.replace("|", "\\|").replace("\r", " ").replace("\n", "<br>")

    scenarios = [r for r in report["results"] if r.get("kind") == "scenario"]
    if not scenarios:
        return []
    lines = ["## Scenario results", "",
             "Expected behavior comes from the test spec. Evidence reports the selected tests' assertions; "
             "it does not independently verify that those assertions match the spec.", "",
             "| Scenario ID | Test cases in files and result | Expected behavior and execution evidence |",
             "|---|---|---|"]
    for result in scenarios:
        tests, evidence = [], []
        for execution in result.get("executions", []):
            selector = execution.get("selector", "")
            file = selector.split("::", 1)[0] or "File not recorded"
            records = execution.get("tests") or []
            # Jest/Vitest can include unrelated deselected tests in a report.
            # Their raw records remain available in JSON, not as this
            # scenario's tests in the user-facing table.
            if execution.get("test_name"):
                records = [t for t in records
                           if t.get("name", t.get("id")) == execution["test_name"]]
            for test in records:
                identity = test.get("name") or test.get("id") or execution.get("test_name") or selector
                tests.append(f"{cell(file)}: {cell(identity)}: **{cell(test.get('status', 'unverifiable').upper())}**")
            if not records and selector:
                identity = execution.get("test_name") or selector
                tests.append(f"{cell(identity)}: **{cell(execution.get('status', 'unverifiable').upper())}** (no individual test result)")
            detail = str(execution.get("evidence", ""))
            link = ""
            artifact = evidence_artifact(execution)
            if artifact:
                for label, name in (("log", "output.log"), ("evidence", "result.json")):
                    detail = detail.replace(f" ({label}: {Path(execution['artifact_dir']) / name})", "")
                link = f" [Execution evidence](<{quote(str(artifact), safe='/')}>)"
            if detail or link:
                evidence.append(cell(detail) + link)
        if not tests:
            tests = [f"No individual test result: **{cell(result['status'].upper())}**"]
        if not evidence:
            evidence = [cell(result.get("evidence", "No execution evidence recorded"))]
        expected = cell(result.get("expected") or "Not specified")
        lines.append("| " + cell(result["id"]) + " | **Scenario: " + cell(result['status'].upper())
                     + "**<br>" + "<br>".join(dict.fromkeys(tests))
                     + " | **Expected:** " + expected + "<br>**Evidence:** "
                     + "<br>".join(dict.fromkeys(evidence)) + " |")
    return [*lines, ""]


def _summary_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    checks = report.get("checks_summary", summary)
    failed = checks["fail"] + checks["partial"] + checks["blocked_upstream"]
    if report["accepted"]:
        outcome = "ACCEPTED for the declared scenarios, criteria, and recorded gates."
    else:
        parts = []
        if failed:
            parts.append(f"{failed} failed")
        if checks["not_examined"]:
            parts.append(f"{checks['not_examined']} never examined")
        outcome = "NOT ACCEPTED. " + ("; ".join(parts) or "nothing applicable was examined") + "."
    lines = [
        f"# Evaluation: {report['feature']}",
        "",
        f"**Outcome:** {outcome}",
        "",
        *([f"Task: `{report['task_id']}`", ""] if report.get("task_id") else []),
        f"Commit: `{report['commit'] or 'uncommitted working tree'}`",
        f"Build fingerprint: `{_fingerprint(report) or 'unavailable'}`",
        f"Attempt: `{report.get('run_id') or 'standalone report'}`",
        "",
        f"**Scenarios:** {summary['total']} scenarios, {summary['pass']} pass",
        *([f"**Criteria:** {report['criteria_summary']['discharged']} of {report['criteria_summary']['total']} criteria discharged"]
          if "criteria_summary" in report else []),
        *([f"**Gates:** {report['gate_summary']['total']} total, {report['gate_summary']['pass']} pass, "
           f"{report['gate_summary']['not_examined']} not examined"] if "gate_summary" in report else []),
        "",
        "| Scenarios | Examined | Pass | Fail | Partial | Blocked | Not examined | N/A |",
        "|------:|---------:|-----:|-----:|--------:|--------:|-------------:|----:|",
        (
            f"| {summary['total']} | {summary['examined']} | {summary['pass']} | "
            f"{summary['fail']} | {summary['partial']} | {summary['blocked_upstream']} | "
            f"{summary['not_examined']} | {summary.get('not_applicable', 0)} |"
        ),
        "",
        *_scenario_table(report),
        "## Results",
        "",
        "| ID | Area | Status | Evidence type | Traces to | Task | Criteria | Evidence |",
        "|----|------|--------|---------------|-----------|------|----------|----------|",
    ]
    for result in report["results"]:
        evidence = str(result.get("evidence", "")).replace("|", "\\|").replace("\n", " ")
        traces = ", ".join(result.get("traces") or []) or "-"
        criteria = "<br>".join(str(c['title']).replace("|", "\\|").replace("\n", " ")
                              + f" ({c['status']})" for c in result.get("criteria", [])) or "-"
        lines.append(
            f"| {result['id']} | {result.get('area') or '-'} | {result['status']} | "
            f"{result.get('evidence_type', '')} | {traces} | "
            f"{result.get('task_id') or '-'} | {criteria} | {evidence} |"
        )
    if report.get("selection"):
        lines += ["", "## Execution scope", "",
                  f"Mode: {report['selection']['mode']}. Only declared mappings are evidence for acceptance.", "",
                  "| Scenario | Task | Selector | Test name | Status |", "|---|---|---|---|---|"]
        seen = set()
        for result in report["results"]:
            for execution in result.get("executions", []):
                identity = json.dumps(execution, sort_keys=True)
                if result["kind"] == "criterion" and identity in seen:
                    continue
                seen.add(identity)
                values = [result["id"], execution.get("task_id", ""), execution.get("selector", ""),
                          execution.get("test_name", ""), execution["status"]]
                lines.append("| " + " | ".join(str(v).replace("|", "\\|").replace("\n", " ") for v in values) + " |")
    lines.append("")
    return "\n".join(lines)


_YAML_BARE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
# Digests and run ids: quoted whether or not they happen to start with a
# digit, so commit, fingerprint and run_id always read the same way.
_YAML_HEX = re.compile(r"^[0-9a-fA-F]{16,}$")
_YAML_RESERVED = {"true", "false", "null", "yes", "no", "on", "off", "y", "n"}


def _yaml_scalar(value: Any) -> str:
    """One YAML scalar. Anything a reader could misread stays quoted.

    JSON string escapes are a subset of YAML double-quoted escapes, so
    json.dumps is a valid YAML encoder for arbitrary text. speed diagnose
    renders risk-surface.yaml the same way through jq's tojson, and neither
    command needs a YAML library for it.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    text = str(value)
    if _YAML_BARE.match(text) and not _YAML_HEX.match(text) and text.lower() not in _YAML_RESERVED:
        return text
    return json.dumps(text)


def _evaluation_yaml(report: dict[str, Any]) -> str:
    """Render the report as evaluation.yaml, the hand-off the next workflow
    step (workbench define) reads.

    Same verdict and per-result records as report.json. Scoped runtime reports
    also carry selection metadata and individual test evidence; legacy standalone
    reports retain their original shape. Logs remain in the attempt directory.
    """
    build = (report.get("build") or {}).get("before")
    build = build if isinstance(build, dict) else {}
    summary = report.get("summary") or {}
    lines = [
        "# Written by `speed eval`. Each result carries its evidence. Silence is not a pass.",
        f"feature: {_yaml_scalar(report.get('feature'))}",
        f"task: {_yaml_scalar(report.get('task_id'))}",
        f"run_id: {_yaml_scalar(report.get('run_id'))}",
        f"generated_at: {_yaml_scalar(report.get('generated_at'))}",
        f"test_spec: {_yaml_scalar(report.get('test_spec'))}",
        f"test_spec_sha256: {_yaml_scalar(report.get('test_spec_sha256'))}",
        f"commit: {_yaml_scalar(report.get('commit'))}",
        "build:",
        f"  head_commit: {_yaml_scalar(build.get('head_commit'))}",
        f"  fingerprint: {_yaml_scalar(build.get('fingerprint'))}",
        f"  dirty: {_yaml_scalar(build.get('dirty'))}",
        f"accepted: {_yaml_scalar(bool(report.get('accepted')))}",
        "summary:",
    ]
    for key in ("total", "examined", "not_examined", "pass", "fail", "partial",
                "blocked_upstream", "unverifiable", "not_applicable"):
        lines.append(f"  {key}: {_yaml_scalar(int(summary.get(key) or 0))}")
    if report.get("selection"):
        # JSON flow collections are valid YAML and preserve arbitrary test names.
        lines.append("selection: " + json.dumps(report["selection"], ensure_ascii=True))
    results = report.get("results") or []
    lines.append("results:" if results else "results: []")
    for result in results:
        executions = [e for e in (result.get("executions") or []) if isinstance(e, dict)]
        artifact = evidence_artifact(executions[-1]) if executions else None
        log = str(artifact) if artifact else None
        fields = [
            ("id", result.get("id")),
            ("kind", result.get("kind")),
            ("area", result.get("area") or None),
            ("title", result.get("title")),
            ("expected", result.get("expected") or None),
            ("level", result.get("level") or None),
            ("status", result.get("status")),
            ("evidence_type", result.get("evidence_type")),
            ("evidence", result.get("evidence")),
        ]
        for index, (key, value) in enumerate(fields):
            prefix = "  - " if index == 0 else "    "
            lines.append(f"{prefix}{key}: {_yaml_scalar(value)}")
        traces = ", ".join(_yaml_scalar(trace) for trace in (result.get("traces") or []))
        lines.append(f"    traces: [{traces}]")
        lines.append(f"    task: {_yaml_scalar(result.get('task_id') or None)}")
        lines.append(f"    command: {_yaml_scalar(result.get('command') or None)}")
        lines.append(f"    log: {_yaml_scalar(log)}")
        if report.get("selection"):
            records = [{"selector": e.get("selector"), "test_name": e.get("test_name"),
                        "selection_level": e.get("selection_level"),
                        "status": e.get("status"), "tests": e.get("tests", [])}
                       for e in executions]
            lines.append("    tests: " + json.dumps(records, ensure_ascii=True))
    lines.append("")
    return "\n".join(lines)


def write_report(report: dict[str, Any], output_dir: Path) -> None:
    residue = {
        "feature": report["feature"],
        "results": [
            result
            for result in report["results"]
            if result["tier"] == "semantic" and result["status"] == "unverifiable"
        ],
    }
    report["residue"] = residue
    _atomic_json(output_dir / "report.json", report)
    _atomic_text(output_dir / "evaluation.yaml", _evaluation_yaml(report))
    _atomic_json(output_dir / "residue.json", residue)
    (output_dir / "summary.md").write_text(
        _summary_markdown(report),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--feature", required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--tasks-dir", type=Path, required=True)
    parser.add_argument("--test-spec", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--judgment", type=Path)
    parser.add_argument("--context", type=Path)
    parser.add_argument("--runner-config", type=Path)
    parser.add_argument("--task-id", help="limit the report to one task")
    parser.add_argument(
        "--test-plan",
        type=Path,
        help="scenario mapping file, read for depends_on_scenarios edges",
    )
    parser.add_argument(
        "--scenario-results",
        type=Path,
        help="JSON written by speed eval after running the test-plan.json mapping",
    )
    args = parser.parse_args()

    judgment = _read_json(args.judgment, {}) if args.judgment else None
    scenario_results = None
    if args.scenario_results:
        loaded = _read_json(args.scenario_results, {})
        scenario_results = loaded.get("results", []) if isinstance(loaded, dict) else loaded
    report = build_report(
        args.feature,
        args.project_root.resolve(),
        args.tasks_dir.resolve(),
        args.test_spec.resolve(),
        judgment,
        scenario_results,
        task_id=args.task_id,
        test_plan_path=args.test_plan,
        runner_config=read_object(args.runner_config) if args.runner_config else None,
        evidence_dir=args.output_dir / "commands",
        criteria_results=_read_json(args.output_dir / "criteria-results.json", None),
        context=read_object(args.context) if args.context else None,
    )
    _atomic_json(args.output_dir / "criteria-results.json", report.pop("criteria_results"))
    write_report(report, args.output_dir.resolve())
    print(json.dumps(report))


if __name__ == "__main__":
    main()
