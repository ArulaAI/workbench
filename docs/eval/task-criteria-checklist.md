# Task-derived evaluation implementation checklist

The test specification precedes planning. Task ownership belongs in existing task acceptance criteria, using stable scenario IDs, and is never required in the test specification.

- [x] Normalize structured criteria, planner bullet text, and serialized JSON arrays without changing persisted task schemas.
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

Validation evidence: 233 distinct Python cases plus 3 subtests, 132 shell checks, and fresh live task-1 / feature / task-2 payment evaluations. See [validation](validation.md) for run IDs, counts, reproduction and limitations. Implementation `ee22459`; fixture inputs `924a28e`.
