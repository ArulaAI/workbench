# Task-derived eval validation

## Latest follow-up: the table in the actual CLI

The prior change rendered the requested table in `summary.md` but left the CLI's old area counts intact. The CLI now calls `lib/eval_display.py` to print each scenario's mapped file/test results, expected behavior, runner evidence and log references. Criterion rows do not become additional scenario rows; a sentence explains reused evidence. Missing and failed scenarios remain visible. JSON mode is unchanged.

Validation for this display change: **14 Python tests passed** (8 renderer tests and 6 copied-payment integration cases), **20 eval shell checks**, and **19 CLI regression checks**. Renderer checks cover multiple files, failures, missing/skipped tests, unrelated deselected tests, empty reports and long text at 72/120/180 columns. New integration checks run the real non-JSON `speed eval` task and feature commands in temporary copies and compare the terminal scenario IDs/expected outcomes with the generated report. Shell syntax and patch whitespace passed.

The user's original manual task-1 run `204ad76de6c946d4ae1429e5b8d2a5a8` was used only for read-only display inspection. All 35 files under the payments feature state had identical fingerprints before and after. No reset or eval rerun was performed in the original payment checkout during this follow-up.


## Latest follow-up: structured criteria and scenario table

Validated on 2026-09-20 with Workbench `462767d` and clean payment fixture input commit `44d1baf`.

- New planner schemas require arrays of `{criterion, verify_by}` objects; the task writer preserves them as JSON arrays. Legacy text remains readable. Planner cache keys include the output schemas.
- Dashboard text fields render structured criteria without serialization errors, and criterion counts accept arrays.
- `summary.md` now starts with the requested three-column scenario table: scenario ID; individual test/file results and scenario verdict; expected behavior beside execution evidence and output-log links.
- The table does not invent observed values or independently certify that assertions implement the spec. Unrelated deselected tests from Jest/Vitest reports are excluded from scenario rows.

Validation: **237 eval/parser Python cases plus 3 subtests**, **126 dashboard cases**, and **92 shell checks** passed (363 distinct Python cases overall). The primary run reported 229 passes/8 skips; those eight JS/TS cases passed under the dependency-complete runtime together with 126 dashboard cases. Focused table and mixed-runner checks passed again after the final display adjustment. Shell checks were task CRUD (53), eval (20) and CLI regressions (19). All three task/planner schemas accept object arrays and reject strings.

Fresh live evaluations:

| Scope | Tests executed | Scenario table rows | Strict exit | Run ID |
|---|---:|---:|---:|---|
| task-1 | 3 | 3 | 0 | `95439694d7d34f1da7fc0259d9b459e5` |
| feature | 18 | 22 | 2 | `9006a99835824f36b9a357a36cb299b3` |
| task-2 | 15 | 19 | 2 | `df1089adf46349549c899d79fd77b883` |

Each Markdown table was parsed with `markdown-it-py`: exactly three columns; scenario IDs, verdicts and expected outcomes agreed with report JSON. Both generated task files contain arrays of objects. JSON/YAML verdicts agree, each Node invocation reports exactly one selected test, task/spec inputs remain unchanged during eval, and task 2 leaves the feature outputs unchanged.

`npm test` passes all 18 tests. The existing course-corpus `npm run verify` failure remains unchanged. Four missing scenarios and feature coverage/integration gates remain visible. Current paths and validation metadata are in the fixture's `docs/speed-eval.md` and `.speed/features/payments/logs/validation.json`.

The earlier validation below is retained as historical context; its previous run IDs were replaced when the payments runtime was reset for this follow-up.

## Prior task-derived mapping validation

Validated 2026-09-20. Workbench implementation: `ee22459` on `feat/eval-test-spec-template`, checkout `/Users/mohitpatel/Desktop/inrhythm/Workbench/.claude/worktrees/task-scoped-eval`.

## Automated checks

| Check | Observed result |
|---|---|
| Combined eval/parser/TOML suite, including copied payments full CLI | 225 passed, 8 skipped, 3 subtests passed, 65.38 seconds |
| Those 8 JS/TS discovery and mixed-runner cases under the dependency-complete Python runtime | 8 passed, 3.19 seconds |
| `tests/test_eval.sh` | 20 passed |
| `tests/test_eval_cli_regressions.sh` | 19 passed |
| `tests/test_lock_regressions.sh` | 18 passed |
| `tests/test_gates_subsystem.sh` | 24 passed |
| `tests/test_tasks.sh` | 51 passed |
| Shell syntax and patch whitespace | Passed |

**233 distinct Python cases plus 3 subtests, and 132 shell checks passed across the two runtime configurations.** The default Python 3.10 installation lacks the JS/TS grammar packages; its eight skips were explicitly rerun using Workbench's Python 3.12 virtual environment. No required case remained untested. The wider repository's unrelated suites were not run.

Real runners: pytest, Node 24.4.1, Vitest and Jest. Python pytest subprocesses use the installed Python 3.10 runtime; the full CLI and grammar discovery use the existing Workbench virtual environment. No packages were installed for this change.

`tests/test_eval_task_criteria.py` contributes 29 cases. It proves:

- In a shared file with five tests and failing test 2, task execution runs only tests 3 and 4. Feature evaluation includes and fails test 2; a selected failure still fails task evaluation.
- One scenario can have multiple tests across files; a task can combine Python backend and JS frontend tests. Unrelated test bodies do not execute.
- Missing files/tests, absent criterion IDs, unknown IDs, planner omissions, duplicate identities, skipped tests and unsupported dynamic names cannot pass.
- Existing criterion strings, structured arrays and serialized arrays preserve task-schema compatibility.
- Python classes/parameterization, nested JS suites and commands rooted with `cd` retain exact identities.
- Shared scenario ownership does not allow one task's evidence to hide another task's missing mapping.
- The real `cmd_plan` and `task_create` persistence path receives the catalog, preserves IDs, supplies the coverage checker, and invalidates cached planning when the catalog changes. **The provider response is controlled in this test; no actual LLM planning quality is claimed.**
- Discovery does not execute Python imports or test bodies. Eval does not rewrite original tasks or the test spec.

## Live payments rerun

The actual repository `/Users/mohitpatel/Desktop/inrhythm/payments-validation-fixture` was migrated on `test/speed-eval`, commit `924a28e`. It descends from `round-0` (`965029f`). All 18 test assertions and application source match round-0; only scenario-ID prefixes were added to test titles. The specification's old execution mapping table was removed. Existing criteria now own the IDs.

`python3 bin/setup-speed-eval.py --reset` replaced the payments runtime state. It seeded two done fixture tasks with idle feature state; this is a reproducible eval fixture, not a performed planning/development/integration lifecycle. The unmodified updated SPEED CLI then ran with `--strict --json --skip-judge --no-defects`:

| Scope | Executed tests | Scenario results | Full report rows | Strict exit | Run ID |
|---|---|---|---|---|---|
| Task 1 | 3 passed | 3 passed | 6 passed | 0 | `9b8818c518cf4fb3b4a426f395f0773d` |
| Feature | 18 passed | 18 passed, 4 unverified | 36 passed, 10 unverified | 2 | `db577c75b0f843a68997b896c047806d` |
| Task 2 | 15 passed | 15 passed, 4 unverified | 30 passed, 8 unverified | 2 | `61607ceb2f0d4d21a3b59442a3ddf9dd` |

Report rows include criteria that reuse scenario evidence. The feature also has two gate rows, so counts are not counts of tests run. The four missing scenarios are RISK-01, AC-12, RISK-02 and EDGE-01. Feature gates are COVERAGE-01 (TR12) and BUILD-INTEGRATED. They remain unresolved rather than being marked passed by setup.

Every command produced exactly one passing JUnit testcase. Task 1 selected three tests across two files; task 2 selected 15 across four. Task 2 left the full feature plan/report/YAML unchanged. Original task files and test spec stayed byte-for-byte unchanged during evaluation. Published YAML fields agree with report JSON; JSON additionally includes the existing `applicable` summary count. Logs and evidence paths refer to the real fixture checkout, not a temporary copy.

`npm test` passed all 18 tests. `npm run verify` still fails the existing course-corpus check: “the course teaches F1, F4, F5, F6 but no round seeds a defect for them.” This same failure was previously reproduced on an unmodified archive of round-0. This change does not repair that unrelated corpus.

The fixture's `docs/speed-eval.md` links each plan, report, summary and YAML. `.speed/features/payments/logs/validation.json` records commands' outcomes, commits, run IDs and tested identities. Later documentation-only commits do not change the tested setup or implementation.

## Reproduce the automated checks

From the implementation checkout:

```bash
export SPEED_PYTHON=/Users/mohitpatel/Desktop/inrhythm/Workbench/.venv/bin/python
export SPEED_TEST_FULL_CLI=1
export SPEED_TEST_PAYMENTS_FIXTURE=/Users/mohitpatel/Desktop/inrhythm/payments-validation-fixture
export SPEED_TEST_VITEST=/Users/mohitpatel/Desktop/inrhythm/Workbench/.claude/worktrees/studio-preview-3011/dashboard/frontend/node_modules/vitest/vitest.mjs
export SPEED_TEST_JEST=/Users/mohitpatel/.npm/_npx/b8d86e6551a4f492/node_modules/jest/bin/jest.js

PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  tests/test_eval_task_criteria.py tests/test_eval_task_scope.py \
  tests/test_eval_payments_fixture.py tests/test_eval_report.py \
  tests/test_eval_report_blocked.py tests/test_eval_report_regressions.py \
  tests/test_eval_regressions.py tests/test_eval_runtime_regressions.py \
  tests/test_eval_execution_regressions.py tests/test_eval_yaml.py \
  tests/test_test_spec.py tests/test_test_spec_regressions.py tests/test_toml_eval.py
```

For the eight cases skipped by Python 3.10, use the dependency-complete runtime while importing the existing pure-Python pytest installation:

```bash
export SPEED_TEST_PYTEST_PYTHON=/Library/Frameworks/Python.framework/Versions/3.10/bin/python3
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 "$SPEED_PYTHON" -B - <<'PY'
import sys
sys.path.append('/Users/mohitpatel/Library/Python/3.10/lib/python/site-packages')
import pytest
raise SystemExit(pytest.main(['-q', '-p', 'no:cacheprovider',
 'tests/test_eval_task_criteria.py::test_js_discovery_ignores_comments_and_resolves_nested_titles',
 'tests/test_eval_task_criteria.py::test_node_third_fourth_only_and_selected_failure',
 'tests/test_eval_task_criteria.py::test_frontend_runner_and_python_backend',
 'tests/test_eval_task_criteria.py::test_js_skips_duplicates_and_dynamic_names_stay_unverified']))
PY
```

These are machine-local runtime paths; other environments should provide equivalent installed runners and dependencies. Run the five shell test files listed above individually. Fresh fixture reset/CLI instructions are in its own guide.

## Limits

No remote push or deployment occurred. The semantic judge and automatic defect creation were skipped for live runs. Missing automated tests remain deterministic gaps. Literal pytest/Node/Jest/Vitest identities are supported; dynamic JS parameterized titles, aliases, custom wrappers and other browser/test runners need adapters or explicit supported mappings. Shared imports/setup can still block selected tests. Stable IDs do not assess assertion quality.
