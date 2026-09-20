# SPEED eval

`speed eval` evaluates a feature or completed task using actual runner evidence. Begin with the [end-to-end walkthrough](end-to-end-walkthrough.md) for the goal, input/output shapes, flow diagram, source-code responsibilities and payments example.

New task acceptance criteria are stored as arrays of `{criterion, verify_by}` objects. Legacy strings remain readable. The current flow derives test mappings from task acceptance criteria and stable scenario IDs in individual tests. The test specification is the catalog authored before planning; it no longer needs task ownership or execution tables. [Task-scoped evaluation](task-scoped-evaluation.md) describes the contract and compatibility behavior.

```bash
speed eval --feature payments --task 1 --strict --skip-judge --no-defects
speed eval --feature payments --strict --skip-judge --no-defects
```

With a task ID, only its individually mapped tests execute. Without one, every catalog scenario is evaluated and all mapped feature tests execute. Missing tests remain unverified in either scope. `--task-id` is an alias for `--task`. An explicit `--test-plan` overrides automatic mapping; `--test-spec` selects a different catalog. Use supported runners and configured test file patterns in `speed.toml`.

Open `eval/summary.md`, or `eval/task-<id>/summary.md` for a task run. That directory contains only `summary.md`, `report.json`, `latest-attempt.json`, and the `runs/` archive. The YAML handoff stays in the feature directory as `evaluation.yaml` or `evaluation-task-<id>.yaml`. Plans, scenario results, manual observations, residue, judgment, and command artifacts remain in each attempt; old promoted copies of the plan, scenario results, and residue are removed after a completed run.

The promoted `report.json` and `--json` output keep each scenario result minimal: `{"id": "AC-01", "status": "pass"}`. Detailed scenario records, executions, and criterion mappings remain in `runs/<run_id>/report.json`. Separate manual criteria, multi-scenario criteria, and acceptance gates appear under `checks` when present, so a passing scenario cannot hide an unmet acceptance requirement. Unexecuted scenarios retain `unverifiable` status rather than being labelled as failed tests.

Both the normal CLI output and Markdown summary show a three-column scenario table with exact test results alongside the spec's expected behavior and execution evidence. Headlines and `report.json.summary` count scenarios. Criteria discharge and gate counts are separate; acceptance still requires all applicable scenarios, criteria, and gates to pass. In the detailed run report, one-to-one test criteria appear in a scenario's `criteria` list and the Results table's Criteria column. Manual, multi-scenario, and unmapped criteria retain their own rows. Execution scope lists reused evidence once. Links point to non-empty structured execution evidence instead of empty stdout logs.

`report.json` also embeds `residue`, including an empty result array. Skipping the judge can leave non-empty unresolved residue; it never implies that there are no gaps. `--json` still emits only the report object. Task outputs are separate from the feature verdict. Strict exit 2 means evaluation completed but was not accepted; exit 3 means it could not run.

- [Implementation and validation checklist](task-criteria-checklist.md)
- [Validation results](validation.md)
- [Next-session context](next-session-prompt.md)

Live fixture: `/Users/mohitpatel/Desktop/inrhythm/payments-validation-fixture`, branch `test/speed-eval`, based on `round-0`. Its `docs/speed-eval.md` gives reset/rerun commands and local artifact links. Earlier main-based copies and spec-owned mapping results are historical baselines.
