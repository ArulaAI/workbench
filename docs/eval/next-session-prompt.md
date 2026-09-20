# Next-session prompt

Copy the following into a new session:

---

Continue reviewing task-derived SPEED evaluation. Do not revert to putting task IDs in the test specification: it is authored before task planning.

Workbench implementation checkout:
`/Users/mohitpatel/Desktop/inrhythm/Workbench/.claude/worktrees/task-scoped-eval`
Branch: `feat/eval-test-spec-template`. Structured-criteria implementation commit: `462767d` (initial task mapping `ee22459`), followed by documentation and the CLI scenario-table fix. Read the latest branch commit for the terminal display change. Read current git status/log first. The shared Workbench main checkout was not switched or modified for this task.

Live payment fixture:
`/Users/mohitpatel/Desktop/inrhythm/payments-validation-fixture`
Branch: `test/speed-eval`, based on `round-0` (`965029f`). Structured task fixture inputs were committed as `44d1baf`; later commits document results. Do not use the separate `payments-validation-fixture-defect-synthesis` checkout to review these new runs.

Read:
1. Workbench `docs/eval/end-to-end-walkthrough.md`: goal, shapes, diagram, source responsibilities and example.
2. `docs/eval/task-scoped-evaluation.md` and `task-criteria-checklist.md`: contract and requirement coverage.
3. `docs/eval/validation.md`: exact checks/results and limitations.
4. Payment fixture `docs/speed-eval.md`: reset commands and links to actual generated artifacts.

Implemented flow:
- Scenario catalog contains stable IDs/outcomes, no required task ownership mapping.
- `speed plan` supplies the catalog to architect phases, coverage checking/repair and cache hashing. Existing task criteria retain `[AC-03] ...` plus `verify_by: test`; `files_touched` declares candidate files.
- New task/planner schemas require an array of `{criterion, verify_by}` objects. `task_create` stores the actual array instead of JSON-encoding it into a string. Legacy strings remain supported by `lib/eval_criteria.py`; eval itself never rewrites task inputs. Dashboard text fields/counts handle structured criteria.
- `lib/eval_discovery.py` discovers Python AST and JS/TS tree-sitter declarations. Python tests use `test_ac_03_...`; Node/Jest/Vitest literal titles use `[AC-03] ...`.
- `lib/eval_selection.py::select_task_plan` generates exact per-task/per-scenario selectors from criteria and discovered tests. Task runs never widen to entire files as a fallback. Feature mode checks the complete catalog, including planner omissions.
- Both normal CLI output and `summary.md` show a three-column scenario table: scenario ID; test/file results and scenario verdict; expected outcome from the spec beside execution evidence/output-log links. It does not independently establish spec-to-assertion correctness. Actual rendered tables were parsed to check column/row counts and expected/status values.
- Runtime/report layers retain individual evidence and reuse executions for task criteria. Shared scenario owners cannot borrow another task's missing evidence. Legacy mapping tables remain compatible when no tagged criteria exist; explicit `--test-plan` deliberately overrides discovery.

Validated: 237 eval/parser cases plus 3 subtests and 126 dashboard cases (363 Python cases overall) across Python 3.10 and dependency-complete 3.12, and 92 shell checks in the latest follow-up. Regression tests prove tests 3 and 4 execute alone when unrelated test 2 fails, multiple tests/files per scenario, mixed frontend/backend runners, missing tests, skips, duplicate/dynamic identities, task/spec immutability and actual planner persistence with a controlled provider response. No actual LLM planning run is claimed.

Prior validation run IDs below are historical: the user subsequently requested cleanup and manually ran task 1 as `204ad76de6c946d4ae1429e5b8d2a5a8`. The CLI-table follow-up preserved all 35 manual-run files and did not rerun eval in the original repository. Inspect current `latest-attempt.json` for live state.

Historical fixture validation outputs (ignored `.speed`, not committed):
- Task 1: run `95439694d7d34f1da7fc0259d9b459e5`, 3 tests passed, accepted, strict exit 0.
- Feature: run `9006a99835824f36b9a357a36cb299b3`, 18 tests passed; 4 missing scenarios plus coverage/integration gates, strict exit 2.
- Task 2: run `df1089adf46349549c899d79fd77b883`, 15 tests passed; 4 missing scenarios, strict exit 2.
- Report rows additionally include criteria reusing the same evidence. Full report totals: task 1 = 6 pass; task 2 = 30 pass/8 unverified; feature = 36 pass/10 unverified.
- Paths: `.speed/features/payments/eval/test-plan.json`, `report.json`, `summary.md`, and `.speed/features/payments/evaluation.yaml`. Task variants use `eval/task-1/`, `eval/task-2/`, and `evaluation-task-1.yaml`/`evaluation-task-2.yaml`.
- Validation metadata: `.speed/features/payments/logs/validation.json`; logs and raw JUnit evidence remain in this repository. Task inputs/spec were unchanged during eval, and task 2 did not overwrite the feature verdict.

Unresolved baseline issues: RISK-01, RISK-02, AC-12 and EDGE-01 have no tests; TR12 lacks scenario coverage; fixture setup has not run `speed integrate`. Existing tests/assertions and source remain round-0 except test-title IDs. RETRY-01 does not settle refund idempotency or prove the retry helper. `npm test` has 18 passes; `npm run verify` has the known course-corpus F1/F4/F5/F6 failure, also reproduced previously on untouched round-0.

Next steps: review the live generated plan/report/YAML with the lead; decide whether to implement the four missing tests and resolve the TR12 gate under a separate agreed scope; try the real planner against an intended feature with LLM access if desired. Add adapters if dynamic JS titles or other test runners are required. No packages were installed and no branches pushed.

Do not claim `.speed` regenerates just by switching branches. The fixture reset script explicitly replaces only payments runtime state and seeds done fixture tasks; eval regenerates artifacts from current inputs. Read current status before resetting again, because local runtime evidence would be replaced.

CLI follow-up: `lib/eval_display.py` is a read-only terminal renderer called by `_eval_print_summary` in `lib/cmd/eval.sh`. The area-count display was removed because scenario and criterion pass counts looked like duplicate tests. The renderer wraps long cells and references raw output logs. JSON output is unchanged. Tests: 14 Python renderer/copied-payment integrations plus 39 eval/CLI shell checks. Normal (non-JSON) task and feature commands are now explicitly tested. The user can rerun the same command already in their terminal; do not reset their manual artifacts without a request.
