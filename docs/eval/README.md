# SPEED eval

`speed eval` evaluates a feature or completed task using actual runner evidence. Begin with the [end-to-end walkthrough](end-to-end-walkthrough.md) for the goal, input/output shapes, flow diagram, source-code responsibilities and payments example.

The current flow derives test mappings from existing task acceptance criteria and stable scenario IDs in individual tests. The test specification is the catalog authored before planning; it no longer needs task ownership or execution tables. [Task-scoped evaluation](task-scoped-evaluation.md) describes the contract and compatibility behavior.

```bash
speed eval --feature payments --task 1 --strict --skip-judge --no-defects
speed eval --feature payments --strict --skip-judge --no-defects
```

With a task ID, only its individually mapped tests execute. Without one, every catalog scenario is evaluated and all mapped feature tests execute. Missing tests remain unverified in either scope. `--task-id` is an alias for `--task`. An explicit `--test-plan` overrides automatic mapping; `--test-spec` selects a different catalog. Use supported runners and configured test file patterns in `speed.toml`.

Completed results are written as `report.json`, `summary.md` and `evaluation.yaml`, with immutable attempt evidence. Task outputs are separate from the feature verdict. Strict exit 2 means evaluation completed but was not accepted; exit 3 means it could not run.

- [Implementation and validation checklist](task-criteria-checklist.md)
- [Validation results](validation.md)
- [Next-session context](next-session-prompt.md)

Live fixture: `/Users/mohitpatel/Desktop/inrhythm/payments-validation-fixture`, branch `test/speed-eval`, based on `round-0`. Its `docs/speed-eval.md` gives reset/rerun commands and local artifact links. Earlier main-based copies and spec-owned mapping results are historical baselines.
