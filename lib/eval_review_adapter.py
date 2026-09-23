"""Turn scenario-linked review findings into an eval test plan.

Review says which scenarios a human-facing problem touches. Eval decides
whether those scenarios actually hold. The join between them is the
`scenario_id` a reviewer declared outright: nothing here infers a scenario
from a file path, a line number, or the wording of a finding, because no
deterministic mapping from a location to a catalog scenario exists.

The output is the existing `--test-plan` object, so the eval engine needs no
change and `validate_plan` remains the single authority on plan shape.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from lib.eval_criteria import task_scenarios
from lib.eval_discovery import discover_tests
from lib.eval_execution import commands_for_file, load_config, runner_kind, test_candidates
from lib.test_spec import mapping_tasks, parse_scenarios


class ReviewAdapterError(ValueError):
    """A review payload could not be turned into an eval plan."""


def scenario_findings(review: dict[str, Any]) -> list[dict[str, Any]]:
    """Issues that name a scenario and are not marked untestable.

    `testable` is absent far more often than it is false, so absence must not
    exclude a finding — only an explicit `false` does. A finding without a
    `scenario_id` is dropped silently: that is the reviewer correctly
    declining to guess, not an error.
    """
    issues = review.get("issues")
    if not isinstance(issues, list):
        raise ReviewAdapterError("Review payload has no issues array")
    return [
        issue for issue in issues
        if isinstance(issue, dict)
        and issue.get("scenario_id")
        and issue.get("testable") is not False
    ]


def review_scenarios(review: dict[str, Any], known: set[str], *,
                     strict: bool = True) -> tuple[list[str], list[str]]:
    """Distinct declared scenario IDs in first-seen order, and the unknown ones.

    Under `strict`, an ID the catalog does not define is a hard error: someone
    asked for this review to be turned into a plan, and naming the review that
    carried a bad ID beats letting `validate_plan` reject its descendant.

    Eval's automatic path passes `strict=False`, because there the review is
    one input among several. A reviewer may legitimately cite an identifier
    that is not an evaluatable scenario — the payments catalog's `OOS-01` is a
    deferral row, not a scenario — and one such mention must not discard the
    scenarios the same review identified correctly. Unknown IDs are returned
    for the caller to report; they never become cases either way.
    """
    ids = list(dict.fromkeys(issue["scenario_id"] for issue in scenario_findings(review)))
    unknown = sorted(sid for sid in ids if sid not in known)
    if unknown and strict:
        raise ReviewAdapterError(
            f"Review references unknown catalog scenario: {', '.join(unknown)}"
        )
    return [sid for sid in ids if sid in known], unknown


def prove_ownership(
    scenario_id: str,
    selector_file: str,
    task: dict[str, Any],
    config: dict[str, Any],
    spec_assignments: dict[str, list[str]],
    tasks: list[dict[str, Any]] | None,
) -> tuple[bool, str | None, bool]:
    """Whether this task provably owns the scenario, why not, and whether that blocks.

    The third value separates the two refusals select_plan already treats
    differently. A scenario another task owns is simply not this task's
    business: select_plan drops such a case with no gap, and the verdict is
    unaffected. Ambiguous ownership -- this task among several possible owners
    -- is an unresolved question about this task, so it stays a real gap and
    can block. Returning that distinction here keeps the adapter aligned with
    the engine instead of promoting every refusal to a blocking gate.


    Mirrors the precedence select_plan applies, minus the explicit-owner tier
    that this function exists to justify:

    1. the spec's Execution-and-Evidence Task column (`mapping_tasks`)
    2. the task's own declared scenarios (`required_test_cases` and
       `[SCENARIO-ID]` tags on `verify_by: test` criteria)
    3. file inference, and only where exactly one task's candidate files
       contain the selector's file

    Tier 3 is the weak one. `files_touched` records that a task edited a file,
    not that it owns every test inside it, so a file two tasks touched proves
    nothing on its own. select_plan says as much and answers a shared file
    with "Ambiguous task ownership" rather than a guess. An adapter that
    stamped `task_id` from tier-3 membership alone would convert that refusal
    into a silent assertion, because select_plan trusts an explicit owner.
    """
    owner = str(task["id"])
    declared = spec_assignments.get(scenario_id) or []
    if declared:
        if owner in declared:
            return True, None, False
        return False, (
            f"Review scenario {scenario_id} is assigned to "
            f"task {', '.join(sorted(declared))} by the test spec, not task {owner}"
        ), False
    # `acceptance_criteria: null` is rejected upstream by validate_task, but the
    # adapter reads task JSON directly and would otherwise raise TypeError out
    # of task_scenarios. Treat an unusable value as "nothing declared" so the
    # weaker tiers still get their say and the engine reports it properly.
    declared_scenarios: set[str] = set()
    if isinstance(task.get("acceptance_criteria", []), (list, str)):
        declared_scenarios = task_scenarios(task)
    if scenario_id in declared_scenarios:
        return True, None, False
    sharers = sorted(
        str(other["id"]) for other in (tasks or [task])
        if selector_file in test_candidates(other, config)
    )
    if sharers == [owner]:
        return True, None, False
    if owner in sharers:
        competing = ", ".join(s for s in sharers if s != owner)
        return False, (
            f"Review scenario {scenario_id} maps to {selector_file}, which "
            f"task {owner} shares with task {competing}; a touched file does not "
            f"establish ownership. Declare [{scenario_id}] in the owning task's "
            f"acceptance criteria, or run feature-scoped Eval."
        ), True
    return False, (
        f"Review scenario {scenario_id} maps to {selector_file}, which is not "
        f"among task {owner}'s candidate test files"
    ), False


def _owning_tasks(
    scenario_id: str,
    root: Path,
    config: dict[str, Any],
    tasks: list[dict[str, Any]],
    exclude_id: str,
) -> list[str]:
    """Which other tasks' candidate files carry a test tagged with this scenario.

    Diagnostic only. Nothing this returns can become a test case; it exists so
    a gap can say "task 2 owns that test" instead of "no test", which reads as
    though none was ever written. Task scope still refuses to run it, because
    the evidence belongs to another task's verdict.

    Failures here are swallowed: a gap message is not worth failing a plan for.
    """
    found: list[str] = []
    for other in tasks:
        other_id = str(other.get("id"))
        if other_id == exclude_id:
            continue
        for name in test_candidates(other, config):
            path = root / name
            try:
                if not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
                    continue
                commands = commands_for_file(config, "test", other, name)
                if len(commands) != 1:
                    continue
                if any(scenario_id in t["scenario_ids"]
                       for t in discover_tests(path, runner_kind(commands[0]))):
                    found.append(other_id)
                    break
            except (ValueError, OSError, SyntaxError):
                continue
    return sorted(found)


def build_test_plan(
    review: dict[str, Any],
    spec_text: str,
    root: Path,
    config: dict[str, Any],
    task: dict[str, Any],
    tasks: list[dict[str, Any]] | None = None,
    strict: bool = True,
) -> dict[str, Any]:
    """Resolve each declared scenario to the test that carries its tag.

    Discovery is the same AST/tree-sitter pass the task-criteria path uses, so
    a scenario binds to a test exactly as it would without review in the loop.
    Anything undiscoverable becomes a gap rather than a silently missing case.

    `tasks`, when supplied, is read only to name the owner of a test this task
    does not own. It never widens what this task can execute.

    `strict=False` reports an out-of-catalog scenario as a gap instead of
    raising, so one unusable identifier cannot discard a whole review.
    """
    known = {s["id"] for s in parse_scenarios(spec_text)}
    wanted_ids, unknown_ids = review_scenarios(review, known, strict=strict)
    wanted = set(wanted_ids)
    # The spec's Task column, when it has one, outranks every other signal.
    spec_assignments = mapping_tasks(spec_text)
    owner = str(task["id"])
    cases: list[dict[str, Any]] = []
    gaps: list[str] = []
    # Notes are recorded and reported but never gate the verdict: they describe
    # work that belongs to another task, or an identifier this catalog cannot
    # evaluate. `gaps` stays reserved for problems this task must answer for.
    review_notes: list[str] = []
    refused: set[str] = set()
    review_notes.extend(
        f"Review scenario {sid} is not in the test spec's Scenario Catalog; "
        f"it cannot be evaluated"
        for sid in unknown_ids
    )
    if not wanted:
        return _plan(cases, gaps, owner, wanted, [], review_notes)

    files = test_candidates(task, config)
    if not files:
        gaps.append(f"Task {owner} has no candidate test files in files_touched")
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
            tests = [t for t in discover_tests(path, kind) if t["scenario_ids"] & wanted]
            identities = Counter(
                t.get("test_name") or "::".join(t.get("nodes", []))
                for t in tests if not t.get("error")
            )
            for test in tests:
                identity = test.get("test_name") or "::".join(test.get("nodes", []))
                if test.get("error") or identities[identity] > 1:
                    gaps.append(
                        f"Task {owner}, {name}: "
                        f"{test.get('error') or 'Duplicate test identity: ' + identity}"
                    )
                    continue
                selector = os.path.relpath(path, cwd)
                if test.get("nodes"):
                    selector += "::" + "::".join(test["nodes"])
                for sid in sorted(test["scenario_ids"] & wanted):
                    # `task_id` is an explicit ownership claim that select_plan
                    # trusts over its own inference, so it is made only where
                    # ownership is provable and the scenario is dropped where
                    # it is not. Refusing here matches what the engine would
                    # have decided on its own had no claim been made.
                    proven, reason, blocking = prove_ownership(
                        sid, name, task, config, spec_assignments, tasks)
                    if not proven:
                        if reason:
                            (gaps if blocking else review_notes).append(reason)
                        # Its own reason is the accurate one. Recording it here
                        # keeps the unmapped sweep below from adding a second,
                        # contradictory gap saying no test was found: one was
                        # found, and ownership is why it will not run.
                        refused.add(sid)
                        continue
                    case = {
                        "scenario_id": sid,
                        "task_id": owner,
                        "selector": selector,
                        "command": command,
                        "runner": kind,
                        "source": "review_findings",
                    }
                    if test.get("test_name"):
                        case["test_name"] = test["test_name"]
                    cases.append(case)
        except (ValueError, OSError, SyntaxError) as exc:
            gaps.append(f"Task {owner}, {name}: {exc}")

    for sid in sorted(wanted - {c["scenario_id"] for c in cases} - refused):
        owners = _owning_tasks(sid, root, config, tasks, owner) if tasks else []
        if owners:
            review_notes.append(
                f"Review scenario {sid} has a tagged test outside task {owner}'s "
                f"candidate files; the test is owned by "
                f"task {', '.join(owners)}. Run feature-scoped Eval to evaluate it."
            )
        else:
            # No owner found, or no task list to search. Say only what is known:
            # the scenario is outside this task's scope. Whether a test exists
            # elsewhere is not established, so neither is asserted.
            review_notes.append(
                f"Review scenario {sid} is outside task {owner}'s candidate scope; "
                f"no tagged test for it was found in the task's files_touched"
            )
    return _plan(cases, gaps, owner, wanted, files, review_notes)


def _plan(cases, gaps, owner, wanted, files, review_notes=()) -> dict[str, Any]:
    # `selection` is informational only: select_plan overwrites it. It is kept
    # so a generated plan is readable on its own when a run is being explained.
    return {
        "test_cases": cases,
        "selection": {
            "source": "review_findings",
            "mode": "task",
            "task_id": owner,
            "scenario_ids": sorted(wanted),
            "candidate_files": sorted(files),
            "gaps": list(dict.fromkeys(gaps)),
            "review_notes": list(dict.fromkeys(review_notes)),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="eval_review_adapter",
        description="Build an eval --test-plan from scenario-linked review findings.",
    )
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--test-spec", type=Path, required=True)
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        root = args.project_root.resolve()
        review = json.loads(args.review.read_text(encoding="utf-8"))
        task = json.loads(args.task.read_text(encoding="utf-8"))
        # Siblings from the same tasks/ directory, for gap wording only. A
        # directory that cannot be read costs a clearer message, not the plan.
        siblings: list[dict[str, Any]] = []
        for path in sorted(args.task.resolve().parent.glob("*.json")):
            try:
                other = json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                continue
            if isinstance(other, dict) and other.get("id") is not None:
                siblings.append(other)
        plan = build_test_plan(
            review,
            args.test_spec.read_text(encoding="utf-8"),
            root,
            load_config(root),
            task,
            siblings,
        )
    except (ReviewAdapterError, ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 3
    text = json.dumps(plan, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
