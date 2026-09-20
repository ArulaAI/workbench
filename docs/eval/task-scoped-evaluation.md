# Task-derived evaluation contract

The current end-to-end design is in [the walkthrough](end-to-end-walkthrough.md). This replaces the earlier approach that required Task and Test name columns in the test specification.

## Contract

1. Author stable scenario IDs and outcomes in the test catalog before planning.
2. `speed plan` assigns IDs to existing task `acceptance_criteria`, e.g. `[AC-03] Invalid input returns 400`, with `verify_by: test`, and lists test files in `files_touched`.
3. Tests use `[AC-03] ...` literal JS/TS titles or Python names `test_ac_03_...`. Descriptive prose need not be identical between criteria and test names.
4. `speed eval --task <id>` discovers and executes only matching individual tests within that task's declared test files. One task can span several files, languages and supported runners. Several tests can establish one scenario.
5. Feature eval uses every task and the entire catalog; an unowned or unimplemented required scenario remains a visible gap.

No new mapping fields were added. New task criteria are stored as arrays of `{criterion, verify_by}` objects. Legacy strings and serialized JSON lists are still normalized in memory. Original task and spec files remain read-only during evaluation.

For shared scenarios, each task needs its own declared-file mapping; evidence from one owner does not hide another owner's missing mapping. Identical valid executions can be reused. Criteria and scenario report rows do not imply duplicate execution.

## Compatibility

Tagged criteria choose the new source, even if an old spec mapping table remains. Specs without tagged criteria retain their previous mapping behavior. Explicit `--test-plan` remains a deliberate override. Existing projects must migrate criteria and test identifiers to adopt automatic discovery; this does not guess ownership from filenames or natural-language similarity.

No matching test, missing file, ambiguous command, duplicate test identity, skipped test, dynamic unsupported title or missing runner evidence can produce a pass. Static discovery supports pytest and Node/Jest/Vitest; frontend browser frameworks with other runners require adapters. Shared imports and hooks still belong to runner execution and can block selected tests.

## Validation

`tests/test_eval_task_criteria.py` covers exact isolation when unrelated test 2 fails, selected failures, multiple files, repeated scenario IDs, nested suites/classes, Python parameterization, missing ownership/tests/files, planner persistence/cache invalidation, legacy compatibility and mixed frontend/backend commands. The planner integration uses the real task writer with a controlled provider response; it does not claim to verify an LLM's planning quality.

See [validation](validation.md), [requirements checklist](task-criteria-checklist.md), and the live payments repository's `docs/speed-eval.md`.

`summary.md` starts with a three-column scenario table showing each test/file result, the overall scenario status, the expected outcome copied from the spec, and execution evidence with output-log links. This is evidence presentation, not an independent semantic check of whether assertions implement the spec.
