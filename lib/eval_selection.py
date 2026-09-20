"""Select task evidence without adding fields to the persisted task schema."""
from __future__ import annotations

from pathlib import Path
from collections import Counter
import os
import shlex

from lib.eval_execution import test_candidates, commands_for_file, runner_kind
from lib.eval_criteria import criteria_items, criterion_ids, task_scenarios
from lib.eval_discovery import discover_tests
from lib.test_spec import empty_mapping_rows, mapping_tasks, parse_scenarios, manual_scenarios


def select_task_plan(root: Path, spec: str, tasks: list[dict], config: dict,
                     task_id: str | None) -> dict:
    """Build execution mappings after planning, without rewriting the test spec."""
    known = {s["id"] for s in parse_scenarios(spec)}
    manual = manual_scenarios(spec)
    for task in tasks:
        unknown = task_scenarios(task) - known
        if unknown:
            raise ValueError(f"Task {task['id']} references unknown scenarios: {', '.join(sorted(unknown))}")
    selected = [t for t in tasks if task_id is None or str(t["id"]) == task_id]
    cases, gaps, associations, owned, candidates = [], [], {}, set(), set()
    required_by_task = {}
    discovery = {}
    for task in selected:
        owner = str(task["id"])
        ids = task_scenarios(task)
        owned.update(ids)
        automated = set(task.get("required_test_cases", [])) - manual
        for index, criterion in enumerate(criteria_items(task), 1):
            refs = criterion_ids(criterion)
            if criterion.get("verify_by") == "test":
                if not refs:
                    gaps.append(f"Task {owner} criterion {index} has verify_by=test but no [SCENARIO-ID]")
                automated.update(refs)
                associations.setdefault(owner, {})[str(index)] = sorted(refs)
        if not automated:
            continue
        required_by_task[owner] = automated
        files = test_candidates(task, config)
        candidates.update(files)
        if not files:
            gaps.append(f"Task {owner} has test criteria but no candidate test files in files_touched")
        for name in files:
            path = root / name
            if not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
                gaps.append(f"Task {owner}: candidate test file is missing or outside the project: {name}")
                continue
            commands = commands_for_file(config, "test", task, name)
            if len(commands) != 1:
                gaps.append(f"Task {owner}: no unambiguous configured test command for {name}")
                continue
            command = commands[0]
            try:
                kind = runner_kind(command)
                tokens = shlex.split(command)
                cwd = root / tokens[1] if len(tokens) > 2 and tokens[0] == "cd" and tokens[2] == "&&" else root
                if not cwd.resolve().is_relative_to(root.resolve()):
                    raise ValueError("Configured test directory leaves the project")
                key = (name, kind)
                if key not in discovery:
                    discovery[key] = discover_tests(path, kind)
                tests = [t for t in discovery[key] if t["scenario_ids"] & automated]
                identities = Counter(t.get("test_name") or "::".join(t.get("nodes", []))
                                     for t in tests if not t.get("error"))
                for test in tests:
                    identity = test.get("test_name") or "::".join(test.get("nodes", []))
                    if test.get("error") or identities[identity] > 1:
                        gaps.append(f"Task {owner}, {name}: {test.get('error') or 'Duplicate test identity: ' + identity}")
                        continue
                    selector = os.path.relpath(path, cwd)
                    if test.get("nodes"):
                        selector += "::" + "::".join(test["nodes"])
                    for sid in sorted(test["scenario_ids"] & automated):
                        case = {"scenario_id": sid, "task_id": owner, "selector": selector,
                                "command": command, "runner": kind, "source": "task_criteria"}
                        if test.get("test_name"):
                            case["test_name"] = test["test_name"]
                        cases.append(case)
            except (ValueError, OSError, SyntaxError) as exc:
                gaps.append(f"Task {owner}, {name}: {exc}")
    scope = owned if task_id is not None else known
    mapped = {c["scenario_id"] for c in cases}
    missing_by_task = {owner: sorted(ids - {c["scenario_id"] for c in cases if c["task_id"] == owner})
                       for owner, ids in required_by_task.items()}
    if task_id is not None and not owned:
        gaps.append("No scenarios are attributable to this task; include [SCENARIO-ID] in its acceptance criteria")
    return {"test_cases": cases, "selection": {
        "source": "task_criteria", "mode": "task" if task_id else "feature", "task_id": task_id,
        "scenario_ids": sorted(scope), "candidate_files": sorted(candidates),
        "gaps": list(dict.fromkeys(gaps)), "criterion_scenarios": associations,
        "missing_task_mappings": {owner: ids for owner, ids in missing_by_task.items() if ids},
        "missing_mappings": sorted(scope - mapped - manual)}}


def selector_file(case: dict) -> str:
    name = case["selector"].split("::", 1)[0]
    tokens = shlex.split(case.get("command", ""))
    if len(tokens) > 2 and tokens[0] == "cd" and tokens[2] == "&&":
        name = str(Path(tokens[1]) / name)
    return str(Path(name))


def exact_selector(case: dict) -> bool:
    if case.get("test_name"):
        return True
    nodes = case["selector"].split("::")[1:]
    # A class node selects a group rather than an individual pytest test.
    return bool(nodes and nodes[-1] and not nodes[-1].startswith("Test"))


def select_plan(plan: dict, spec: str, tasks: list[dict], config: dict,
                task_id: str | None, scenario_ids, *, override: bool = False) -> dict:
    """Explicit owners win. File inference is safe only with one candidate owner.

    A shared file alone never establishes which test belongs to which task.
    Empty mapping rows keep their owners, making missing tests visible too.
    """
    known = {s["id"] for s in parse_scenarios(spec)}
    assignments = mapping_tasks(spec)
    task_ids = {str(t["id"]) for t in tasks}
    for sid, owners in assignments.items():
        if sid not in known or any(owner not in task_ids for owner in owners):
            raise ValueError(f"Invalid scenario/task assignment: {sid}: {owners}")
    candidates = {str(t["id"]): test_candidates(t, config) for t in tasks}
    required = {str(t["id"]): scenario_ids(t) for t in tasks}
    manual = manual_scenarios(spec)
    manual_only = set()
    for owner, ids in required.items():
        declared = ids | {sid for sid, owners in assignments.items() if owner in owners}
        if declared and declared <= manual:
            manual_only.add(owner)
    owned = set(required.get(task_id, set()))
    owned.update(sid for sid, owners in assignments.items() if task_id in owners)
    cases, gaps, criterion_scenarios = [], [], {}
    for original in plan["test_cases"]:
        case = dict(original)
        explicit = case.get("task_id", case.get("owner_task_id"))
        owners = ({str(explicit)} if explicit is not None else
                  {owner for owner, ids in required.items() if case["scenario_id"] in ids})
        if not owners:
            owners = {owner for owner, files in candidates.items() if selector_file(case) in files}
        if task_id is not None:
            if len(owners) > 1 and task_id in owners:
                gaps.append(f"Ambiguous task ownership for {case['scenario_id']} / {case['selector']}; add Task to the mapping")
                owned.add(case["scenario_id"])
                continue
            if owners != {task_id}:
                continue
            owned.add(case["scenario_id"])
        if len(owners) == 1:
            case["task_id"] = next(iter(owners))
        if case.get("criterion"):
            if len(owners) != 1:
                raise ValueError("Criterion mapping requires one unambiguous Task")
            criterion_scenarios.setdefault(case["task_id"], {}).setdefault(str(case["criterion"]), []).append(case["scenario_id"])
        cases.append(case)
    if task_id is not None and not owned:
        gaps.append("No scenarios are attributable to this task; add Task and individual selectors to Execution and Evidence")
    mapped_files = {selector_file(case) for case in cases}
    mapped_ids = {case["scenario_id"] for case in cases}
    # Only legacy selectors that the runtime can actually attribute count here.
    # Having any legacy selector must not hide a second unmapped test file.
    for task in tasks:
        if task_id is not None and str(task["id"]) != task_id:
            continue
        ids, selectors = required[str(task["id"])], task.get("test_selectors", [])
        if len(ids) == 1 and not ids & mapped_ids and selectors and all(exact_selector({"selector": s}) for s in selectors):
            mapped_files.update(selector_file({"selector": s, "command": task.get("test_command", "")}) for s in selectors)
    scoped_candidates = candidates.get(task_id, sorted({f for fs in candidates.values() for f in fs}))
    for name in scoped_candidates:
        owners = {owner for owner, files in candidates.items() if name in files and (task_id is None or owner == task_id)}
        if owners and owners <= manual_only:
            continue
        if name not in mapped_files:
            gaps.append(f"Touched test file has no {'task' if task_id else 'feature'} mapping: {name}")
    missing = sorted({row["scenario_id"] for row in empty_mapping_rows(spec)
                      if row["scenario_id"] not in manual and (task_id is None or row["task_id"] == task_id
                          or (not row["task_id"] and row["scenario_id"] in owned))}) if not override else []
    selection = {"mode": "task" if task_id else "feature", "task_id": task_id,
                 "scenario_ids": sorted(owned if task_id else known),
                 "candidate_files": scoped_candidates,
                 "gaps": list(dict.fromkeys(gaps)), "criterion_scenarios": criterion_scenarios,
                 "missing_mappings": missing}
    return {**plan, "test_cases": cases, "selection": selection}
