"""Validated evaluation inputs, immutable attempts and build provenance."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import uuid

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.eval_execution import (commands_for_file, load_config, resolve_command, run_command,
                                utc_now, valid_selector)
from lib.eval_selection import exact_selector, select_plan
from lib.test_spec import (SCENARIO_ID_RE, manual_scenarios, parse_execution_mapping,
                           parse_scenarios, silent_scenarios)

IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}\Z")


def identifier(value: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError(f"Invalid feature or task ID: {value!r}")
    return value


def read_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def safe_path(path: Path, root: Path) -> None:
    """Writable evaluation state must remain inside the project without links."""
    root_alias = Path(os.path.abspath(root))
    root = root.resolve()
    absolute = Path(os.path.abspath(path))
    if not absolute.resolve().is_relative_to(root):
        raise ValueError(f"Evaluation path leaves the project: {path}")
    current = absolute
    while True:
        if current.is_symlink() and current != root_alias:
            raise ValueError(f"Evaluation state must not be a symlink: {current}")
        if current.resolve() == root:
            break
        current = current.parent


def task_scenarios(task: dict) -> set[str]:
    ids = set(task.get("required_test_cases", []))
    criteria = task.get("acceptance_criteria", [])
    if isinstance(criteria, list):
        for criterion in criteria:
            if isinstance(criterion, dict):
                ids.update(criterion.get("scenario_ids", []))
    return ids


def validate_task(task: dict, path: Path, root: Path) -> None:
    task_id = identifier(str(task.get("id", "")))
    if path.stem != task_id:
        raise ValueError(f"Task ID does not match filename: {path}")
    for key in ("required_test_cases", "test_selectors", "files_touched"):
        items = task.get(key, [])
        if not isinstance(items, list) or any(not isinstance(x, str) for x in items):
            raise ValueError(f"Task {task_id}: {key} must be an array of strings")
    criteria = task.get("acceptance_criteria", [])
    if not isinstance(criteria, (list, str)):
        raise ValueError(f"Task {task_id}: invalid acceptance criteria")
    if isinstance(criteria, list):
        for criterion in criteria:
            if not isinstance(criterion, (str, dict)):
                raise ValueError(f"Task {task_id}: invalid criterion")
            if isinstance(criterion, dict):
                ids = criterion.get("scenario_ids", [])
                if not isinstance(ids, list) or any(not isinstance(s, str) for s in ids):
                    raise ValueError(f"Task {task_id}: invalid scenario_ids")
    if any(not SCENARIO_ID_RE.fullmatch(s) for s in task_scenarios(task)):
        raise ValueError(f"Task {task_id}: invalid scenario ID")
    for name in task.get("files_touched", []):
        if not (root / name).resolve().is_relative_to(root.resolve()):
            raise ValueError(f"Task {task_id}: file leaves project: {name}")
    if not isinstance(task.get("branch", ""), str):
        raise ValueError(f"Task {task_id}: invalid branch")
    if not isinstance(task.get("test_command", ""), str):
        raise ValueError(f"Task {task_id}: invalid test_command")


def validate_plan(plan: dict, known: set[str], tasks: list[dict]) -> None:
    cases = plan.get("test_cases")
    if not isinstance(cases, list):
        raise ValueError("The execution mapping must contain a test_cases array")
    task_ids = {str(t["id"]) for t in tasks}
    for case in cases:
        if not isinstance(case, dict) or case.get("scenario_id") not in known:
            raise ValueError("Mapping references an unknown catalog scenario")
        if not valid_selector(case.get("selector", "")):
            raise ValueError(f"Invalid mapping selector: {case.get('selector')!r}")
        if not isinstance(case.get("command", ""), str):
            raise ValueError("Mapping command must be a string")
        for key in ("test_name", "runner"):
            if key in case and (not isinstance(case[key], str) or not case[key].strip()
                                or any(ord(c) < 32 or ord(c) == 127 for c in case[key])):
                raise ValueError(f"Invalid mapping {key}")
        if case.get("runner") and case["runner"] not in ("pytest", "node", "vitest", "jest", "custom"):
            raise ValueError("Unknown mapping runner")
        if "criterion" in case and not re.fullmatch(r"[1-9][0-9]*", str(case["criterion"])):
            raise ValueError("Mapping Criterion must be the 1-based acceptance criterion index")
        owner = case.get("task_id", case.get("owner_task_id"))
        if owner is not None and str(owner) not in task_ids:
            raise ValueError(f"Mapping references unknown task: {owner}")
        deps = case.get("depends_on_scenarios", [])
        if not isinstance(deps, list) or any(not isinstance(s, str) or s not in known for s in deps):
            raise ValueError("Mapping has invalid scenario dependencies")


def build_snapshot(root: Path) -> dict:
    def git(*args):
        return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.DEVNULL)
    try:
        head = git("rev-parse", "HEAD").decode().strip()
        names = set(git("ls-files", "-c", "-o", "--exclude-standard", "-z").decode().split("\0"))
        changed = set(git("diff", "HEAD", "--name-only", "-z").decode().split("\0"))
        untracked = set(git("ls-files", "-o", "--exclude-standard", "-z").decode().split("\0"))
    except (OSError, subprocess.CalledProcessError):
        return {"head_commit": None, "fingerprint": None, "dirty": True, "available": False}
    def source(name):
        return bool(name) and not name.startswith(".speed/") and name != ".speed"
    digest = hashlib.sha256(head.encode())
    for name in sorted(filter(source, names)):
        path = root / name
        digest.update(name.encode() + b"\0")
        if path.is_symlink():
            digest.update(b"symlink\0" + os.readlink(path).encode())
        elif path.is_file():
            digest.update(str(path.stat().st_mode & 0o777).encode() + b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
        else:
            digest.update(b"missing")
    return {"head_commit": head, "fingerprint": digest.hexdigest(),
            "dirty": any(source(n) for n in changed | untracked), "available": True}


def prepare(root: Path, feature_dir: Path, state_file: Path, test_spec: Path,
            task_id: str | None = None, plan_path: Path | None = None,
            manual_path: Path | None = None) -> Path:
    root = root.resolve()
    for path in (feature_dir, feature_dir / "tasks", feature_dir / "eval", state_file):
        safe_path(path, root)
    # These three are read, not written, and were exempt from validation. A
    # symlinked test spec was read and pasted verbatim into the evaluator
    # prompt, so any file the user could link to was shipped to the model.
    for path in (test_spec, plan_path, manual_path):
        if path is not None:
            safe_path(path, root)
    state = read_object(state_file)
    tasks = []
    for path in sorted((feature_dir / "tasks").glob("*.json")):
        safe_path(path, root)
        task = read_object(path)
        validate_task(task, path, root)
        tasks.append(task)
    if task_id is not None:
        identifier(task_id)
        if not any(str(t["id"]) == task_id for t in tasks):
            raise ValueError(f"Task {task_id} not found")
    selected = [t for t in tasks if task_id is None or str(t["id"]) == task_id]
    if any(t.get("status") != "done" for t in selected):
        raise RuntimeError("Evaluation requires done tasks")
    spec_text = test_spec.read_text(encoding="utf-8")
    scenarios = {s["id"] for s in parse_scenarios(spec_text)}
    plan = read_object(plan_path) if plan_path else {"test_cases": parse_execution_mapping(spec_text)}
    # A catalog is meaningful even when every required test is still missing.
    # Report its gaps instead of refusing to produce the feature verdict.
    if not selected and not plan["test_cases"] and not scenarios:
        raise ValueError("No tasks or mapped scenarios to evaluate")
    validate_plan(plan, scenarios, tasks)
    config = load_config(root)
    plan = select_plan(plan, spec_text, tasks, config, task_id, task_scenarios, override=bool(plan_path))
    build = build_snapshot(root)
    manual = read_object(manual_path) if manual_path else {"results": []}
    if not isinstance(manual.get("results"), list):
        raise ValueError("Manual evidence must contain a results array")
    if manual["results"] and (not build["fingerprint"] or manual.get("build_fingerprint") != build["fingerprint"]):
        raise ValueError("Manual evidence does not identify this working tree fingerprint")
    allowed_manual = manual_scenarios(spec_text)
    seen = set()
    for item in manual["results"]:
        if (not isinstance(item, dict) or item.get("scenario_id") not in allowed_manual
                or item.get("scenario_id") in seen or item.get("status") not in ("pass", "fail", "unverifiable")
                or any(not isinstance(item.get(k), str) or not item[k].strip()
                       for k in ("reviewer", "evidence", "executed_at"))):
            raise ValueError("Invalid manual observation, reviewer, or scenario classification")
        seen.add(item["scenario_id"])
    if task_id is not None:
        owned = set(plan["selection"]["scenario_ids"])
        manual["results"] = [r for r in manual["results"] if r["scenario_id"] in owned]
    output = feature_dir / "eval"
    if task_id:
        output /= "task-" + task_id
    safe_path(output, root)
    output.mkdir(parents=True, exist_ok=True)
    safe_path(output / "runs", root)
    runs = output / "runs"
    runs.mkdir(exist_ok=True)
    # Preserve pre-upgrade evidence once, before changing the latest view.
    if (output / "report.json").exists() and not any(runs.iterdir()):
        legacy = runs / ("legacy-" + uuid.uuid4().hex)
        legacy.mkdir()
        for name in ("report.json", "summary.md", "scenario-results.json", "residue.json", "judgment.json", "test-plan.json"):
            if (output / name).is_file():
                shutil.copyfile(output / name, legacy / name)
    run = runs / uuid.uuid4().hex
    run.mkdir()
    (run / "tasks").mkdir()
    (run / "test-spec.md").write_text(spec_text)
    for task in selected:
        task = {**task, "scenario_results": []}
        atomic_json(run / "tasks" / f"{task['id']}.json", task)
    atomic_json(run / "test-plan.json", plan)
    atomic_json(run / "runner-config.json", config)
    atomic_json(run / "manual-results.json", manual)
    unmerged = []
    for task in selected:
        if task.get("branch"):
            if subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor", task["branch"], "HEAD"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
                unmerged.append(str(task["id"]))
    prior_evaluation = state.get("evaluation", {})
    integration_verified = (state.get("status") == "completed" or
                            (isinstance(prior_evaluation, dict) and
                             prior_evaluation.get("integration_verified") is True))
    integration_verified = bool(integration_verified and not state.get("integration_failure") and not unmerged)
    context = {"integration_verified": integration_verified, "run_id": run.name, "project_root": str(root), "feature_dir": str(feature_dir),
               "state_file": str(state_file), "output_dir": str(output), "task_id": task_id,
               "test_spec": str(test_spec), "test_spec_sha256": hashlib.sha256(spec_text.encode()).hexdigest(),
               "started_at": utc_now(), "build_before": build, "feature_state": state,
               "unmerged_tasks": unmerged, "selection": plan["selection"]}
    atomic_json(run / "context.json", context)
    atomic_json(run / "attempt.json", {"status": "running", "started_at": context["started_at"]})
    if task_id is None:
        state["evaluation"] = {"status": "running", "accepted": False, "run_id": run.name,
                               "integration_verified": integration_verified, "report": str(run / "report.json")}
        state["status"] = "evaluating"
        atomic_json(state_file, state)
    return run


def execute(run: Path) -> None:
    context = read_object(run / "context.json")
    root = Path(context["project_root"])
    config = read_object(run / "runner-config.json")
    plan = read_object(run / "test-plan.json")
    tasks = [read_object(p) for p in sorted((run / "tasks").glob("*.json"))]
    results = []
    timeout = int(os.environ.get("SPEED_TIMEOUT", "600"))
    cache = {}
    def invoke(command, selectors, task=None, case=None):
        case = case or {}
        try:
            if not command and len(selectors) == 1:
                commands = commands_for_file(config, "test", task or {}, selectors[0].split("::", 1)[0])
                if len(commands) != 1:
                    raise ValueError("No unambiguous test command for selector; set Command in the mapping")
                command = commands[0]
            base = resolve_command(config, command, task)
            key = (base, tuple(selectors), case.get("test_name", ""), case.get("runner", ""))
            if key not in cache:
                cache[key] = run_command(base, selectors, root, run / "commands", timeout=timeout,
                                         test_name=case.get("test_name", ""), runner=case.get("runner", ""),
                                         exact=bool(context.get("task_id")) or bool(case and exact_selector(case)))
            return dict(cache[key])
        except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
            return {"status": "unverifiable", "evidence": str(exc), "command": "", "tests": []}
    for case in plan["test_cases"]:
        owner = str(case.get("task_id", case.get("owner_task_id", "")))
        task = next((t for t in tasks if str(t["id"]) == owner), None)
        if context.get("task_id") and not exact_selector(case):
            outcome = {"status": "unverifiable", "command": "", "tests": [],
                       "evidence": "Task mapping selects a whole file/group; add an individual Test name or file::test selector"}
        else:
            outcome = invoke(case.get("command", ""), [case["selector"]], task, case)
            if not exact_selector(case):
                outcome["evidence"] += "; file-level evidence: individual scenario-to-test attribution is unavailable"
        results.append({**outcome, "scenario_id": case["scenario_id"], "task_id": owner,
                        "source": "mapping", "run_id": run.name, "selector": case["selector"],
                        "test_name": case.get("test_name", ""), "runner": case.get("runner", ""),
                        "selection_level": "test" if exact_selector(case) else "file"})
    mapped = {r["scenario_id"] for r in results}
    for sid in set(context.get("selection", {}).get("missing_mappings", [])) & mapped:
        results.append({"scenario_id": sid, "task_id": context.get("task_id"), "source": "mapping_missing",
                        "run_id": run.name, "status": "unverifiable", "command": "", "tests": [],
                        "evidence": "An additional declared mapping row has no selector"})
    mapped.update(r["scenario_id"] for r in read_object(run / "manual-results.json")["results"])
    # A mapping row with an empty Selector cell declares that nothing examines
    # this scenario. It carries no result of its own, so a task batch claiming
    # it would turn declared silence into a pass.
    silent = silent_scenarios((run / "test-spec.md").read_text(encoding="utf-8"))
    for task in tasks:
        owned = task_scenarios(task)
        task_results = []
        if owned:
            # A scenario the mapping executed, or manual evidence covers,
            # already has per-scenario evidence. A task batch cannot attribute
            # its outcome to one scenario, so a passing batch must neither
            # overwrite that evidence nor invent evidence of its own.
            attributed = sorted(owned - mapped - silent)
            selectors = task.get("test_selectors", [])
            # Only an unmapped single scenario can inherit a legacy selector
            # list. Mapping evidence is authoritative in both feature/task mode;
            # an unrelated failed task batch cannot poison every scenario.
            if len(attributed) == 1 and len(owned) == 1 and selectors and all(
                    exact_selector({"selector": s}) for s in selectors):
                task_results = [{**invoke(task.get("test_command", ""), [s], task),
                                 "scenario_id": attributed[0], "task_id": str(task["id"]),
                                 "source": "task", "selector": s, "run_id": run.name} for s in selectors]
            else:
                task_results = [{"scenario_id": sid, "task_id": str(task["id"]), "source": "task",
                                 "run_id": run.name, "status": "unverifiable", "command": "",
                                 "evidence": "No individual test mapping for this task scenario"} for sid in attributed]
        task["scenario_results"] = task_results
        atomic_json(run / "tasks" / f"{task['id']}.json", task)
        results.extend(task_results)
    for observation in read_object(run / "manual-results.json")["results"]:
        results.append({**observation, "source": "manual", "run_id": run.name, "command": ""})
    atomic_json(run / "scenario-results.json", {"results": results})


def finish(run: Path, failed: bool = False) -> None:
    context = read_object(run / "context.json")
    state_file = Path(context["state_file"])
    output = Path(context["output_dir"])
    root = Path(context["project_root"])
    # The YAML hand-off sits in the feature directory, beside the
    # risk-surface.yaml that diagnose writes, so the next workflow step finds
    # every step's artifact in one place. A task-scoped run must not pose as
    # the feature verdict, so it gets its own name.
    task_id = context["task_id"]
    handoff = Path(context["feature_dir"]) / (f"evaluation-task-{task_id}.yaml" if task_id else "evaluation.yaml")
    for path in (state_file, output, handoff):
        safe_path(path, root)
    if failed:
        atomic_json(run / "attempt.json", {"status": "failed", "finished_at": utc_now()})
    else:
        report = read_object(run / "report.json")
        targets = {name: output / name
                   for name in ("report.json", "summary.md", "residue.json", "scenario-results.json", "test-plan.json")}
        targets["evaluation.yaml"] = handoff
        for name, target in targets.items():
            source = run / name
            if source.is_file():
                fd, temp = tempfile.mkstemp(dir=target.parent)
                os.close(fd)
                try:
                    shutil.copyfile(source, temp)
                    os.replace(temp, target)
                finally:
                    if os.path.exists(temp):
                        os.unlink(temp)
        atomic_json(run / "attempt.json", {"status": "completed", "accepted": report["accepted"], "finished_at": utc_now()})
    atomic_json(output / "latest-attempt.json", {"run_id": run.name, **read_object(run / "attempt.json")})
    if context["task_id"] is None:
        state = read_object(state_file)
        accepted = not failed and report["accepted"]
        if context["integration_verified"]:
            state["status"] = "accepted" if accepted else "integrated_not_accepted"
        else:
            original_status = context["feature_state"].get("status", "idle")
            state["status"] = original_status if original_status not in ("accepted", "integrated_not_accepted", "evaluating") else "idle"
        state["evaluation"] = {"status": "failed" if failed else "completed", "accepted": accepted,
                               "integration_verified": context["integration_verified"],
                               "run_id": run.name, "report": str(run / "report.json"), "evaluated_at": utc_now()}
        # Existing integration failures belong to integration and are preserved.
        atomic_json(state_file, state)


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    guard = sub.add_parser("guard")
    guard.add_argument("--root", type=Path, required=True)
    guard.add_argument("--path", action="append", type=Path, default=[])
    prep = sub.add_parser("prepare")
    for name in ("root", "feature-dir", "state-file", "test-spec"):
        prep.add_argument("--" + name, type=Path, required=True)
    prep.add_argument("--task-id")
    prep.add_argument("--test-plan", type=Path)
    prep.add_argument("--manual-results", type=Path)
    for name in ("execute", "finish", "abort"):
        p = sub.add_parser(name)
        p.add_argument("run", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "guard":
            for path in args.path:
                safe_path(path, args.root)
        elif args.command == "prepare":
            print(prepare(args.root, args.feature_dir, args.state_file, args.test_spec,
                          args.task_id, args.test_plan, args.manual_results))
        elif args.command == "execute":
            execute(args.run)
        else:
            finish(args.run, failed=args.command == "abort")
    except RuntimeError as exc:
        print(f"Evaluation: {exc}", file=sys.stderr)
        sys.exit(2)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Invalid evaluation input: {exc}", file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    main()
