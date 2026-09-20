# Task-derived evaluation implementation checklist

The test specification precedes planning. Task ownership belongs in existing task acceptance criteria, using stable scenario IDs, and is never required in the test specification.

- [x] Read structured criteria and legacy bullet/serialized text without rewriting existing task inputs during eval. New planner output now uses the requested object-array representation.
- [x] Supply the existing scenario catalog to single-pass and phased planning; include it in cache invalidation and preserve IDs in developer instructions.
- [x] Derive task ownership from `[AC-03]` in criteria. Discover individual tests in `files_touched` filtered by `speed.toml`.
- [x] Select Python tests named `test_ac_03_...` and JS/TS tests titled `[AC-03] ...`; retain exact runner selectors and per-test evidence.
- [x] Support shared files, multiple files per task, nested suites/classes, parameterized Python tests, and frontend/backend commands.
- [x] Prove only tests 3 and 4 execute for their task when test 2 fails. Verify selected failures remain failures in task and feature reports.
- [x] Flag missing tests, absent files, missing IDs, unknown IDs, unsupported discovery, skips, duplicate identities, and catalog scenarios omitted by planning.
- [x] Keep legacy explicit mappings readable without letting them replace task-derived ownership when tagged criteria exist.
- [x] Keep task JSON and test spec unchanged during eval; preserve report/YAML agreement and task/feature output separation.
- [x] Migrate and reset the payments fixture on `test/speed-eval`, retain the round-0 application behavior, and run fresh task and feature evaluations.
- [x] Record validation and update the walkthrough and next-session prompt with the corrected flow and limitations.

Initial mapping validation evidence: 233 distinct Python cases plus 3 subtests, 132 shell checks, and fresh live task-1 / feature / task-2 payment evaluations. See [validation](validation.md) for run IDs, counts, reproduction and limitations. Implementation `ee22459`; fixture inputs `924a28e`.

## Follow-up: readable task JSON and scenario table

- [x] New planner schemas emit arrays of `{criterion, verify_by}` objects; task persistence retains the array, with legacy strings still readable.
- [x] Dashboard readers tolerate arrays without breaking their existing text display API.
- [x] Summary has one scenario row with individual file/test results and the expected outcome beside execution evidence and logs.
- [x] Validate pass, failure, missing tests and multiple tests/files; never claim an independent semantic match or invent observed values.
- [x] Migrate tracked payment task fixtures to arrays, rerun eval and inspect real generated task JSON and summary tables.

Follow-up evidence: Workbench `462767d`, fixture `44d1baf`; 237 eval/parser cases plus 3 subtests, 126 dashboard cases, 92 shell checks. Fresh live tables were parsed as Markdown and checked for exactly three columns, correct scenario rows, expected behavior and statuses. See the latest section of [validation](validation.md).
