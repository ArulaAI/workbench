# Task-scoped eval validation

Validated 2026-09-20 on `feat/eval-test-spec-template`, based on `ff04f50`. Implementation checkout: `/Users/mohitpatel/Desktop/inrhythm/Workbench/.claude/worktrees/task-scoped-eval`.

## Results

| Check | Observed result |
|---|---|
| Combined Python eval/parser/TOML suite with all runner integrations enabled | 203 passed, 3 subtests passed; no skips, 43.47 seconds |
| Final added regression: feature has a catalog but no tasks and no executable tests | 1 passed; produces an unverified report instead of refusing to report declared gaps |
| `tests/test_eval.sh` | 20 passed, 0 failed |
| `tests/test_eval_cli_regressions.sh` | 19 passed, 0 failed |
| `tests/test_lock_regressions.sh` | 18 passed, 0 failed |
| `tests/test_gates_subsystem.sh` | 24 passed, 0 failed |
| Node 22 compatibility | 7 Node-focused tests and 4 copied-payments tests passed |
| Shell syntax and patch whitespace | `bash -n speed lib/cmd/eval.sh` and `git diff --check` passed |

Totals: **204 distinct Python cases plus 3 subtests, and 81 shell checks passed**. The full combined run preceded the final one-condition catalog-only guard fix; its new case was then run separately. The wider repository's unrelated test suites were not run.

Real runners used: Python 3.10.2 / pytest 9.0.3 for Python fixtures; Node 24.4.1, Vitest 3.2.4 and Jest 30.4.2 for JavaScript integration. Node 22.17.1 was additionally exercised against named/nested Node tests and the TypeScript payments fixture. Full CLI tests used the existing Python 3.12.8 Workbench virtual environment for CLI dependencies.

Most existing CLI unit fixtures intentionally omit global dependency preflight, while exercising real command dispatch, locks and eval. A separate **unmodified `speed` CLI** test ran preflight and evaluation against a temporary payment repository with real Node tests. Installed grammar binaries were copied into the isolated implementation worktree's ignored grammar directory for this check; no dependencies were installed or downloaded.

## Payments fixture evidence

Source: `/Users/mohitpatel/Desktop/inrhythm/payments-validation-fixture`, branch `codex/payments-test-spec`, inspected at `307cd00`. Tests copy this repository to temporary directories and add test-only task/mapping setup in those copies. Original fixture files and state remain unchanged.

- Task 1 mapped AC-01 and AC-02 in `test/service.test.ts`, plus VAL-01 in `test/money.test.ts`. Exactly those three individual tests ran and passed.
- Task 2 shared both files and included the remaining mapped tests plus declared missing scenarios. Its missing scenarios stayed visible; task-1 scenarios did not enter its report.
- Feature evaluation ran 17 individual mapped tests, all passing. The report had 22 results: 17 pass and 5 unverified. The unverified rows were RISK-01, AC-12, RISK-02, EDGE-01 and COVERAGE-01 (the existing TR12 coverage gap).
- The unmodified CLI returned strict exit 0 for task 1, exit 2 for feature evaluation, and exit 2 for task 2. Task evaluation did not overwrite the full feature report.

The scenario/test name pairs are explicit in `tests/test_eval_payments_fixture.py::NAMES`; they were checked against the fixture's actual assertions. For example, AC-01 checks an authorised amount of 2500 and a balanced ledger pair. Ledger net zero is the sum of balanced entries, not a claim that a customer's card balance became zero.

## Reproduce

Run from the implementation checkout. These paths describe installed tools on this machine; portable CI can point the same environment variables at its own installations. Tests skip optional integrations when their environment variables are absent, so retain these flags for the full count.

```bash
export SPEED_PYTHON=/Users/mohitpatel/Desktop/inrhythm/Workbench/.venv/bin/python
export SPEED_TEST_FULL_CLI=1
export SPEED_TEST_PAYMENTS_FIXTURE=/Users/mohitpatel/Desktop/inrhythm/payments-validation-fixture
export SPEED_TEST_VITEST=/Users/mohitpatel/Desktop/inrhythm/Workbench/.claude/worktrees/studio-preview-3011/dashboard/frontend/node_modules/vitest/vitest.mjs
export SPEED_TEST_JEST=/Users/mohitpatel/.npm/_npx/b8d86e6551a4f492/node_modules/jest/bin/jest.js

python3 -m pytest -q \
  tests/test_eval_task_scope.py tests/test_eval_payments_fixture.py \
  tests/test_eval_report.py tests/test_eval_report_blocked.py \
  tests/test_eval_report_regressions.py tests/test_eval_regressions.py \
  tests/test_eval_runtime_regressions.py tests/test_eval_execution_regressions.py \
  tests/test_eval_yaml.py tests/test_test_spec.py \
  tests/test_test_spec_regressions.py tests/test_toml_eval.py

bash tests/test_eval.sh
bash tests/test_eval_cli_regressions.sh
bash tests/test_lock_regressions.sh
bash tests/test_gates_subsystem.sh
```

Expected current Python collection is 204 tests plus 3 subtests. Changing the fixture or runner versions can change observed outcomes. The task-scope tests assert absence of unrelated test-body side effects, rather than relying solely on an exit code or a list of arguments.

## Deliberate boundaries

No network push, original fixture migration, release, or PR was performed. The LLM evaluator was skipped in integration runs; deterministic missing tests and criteria never enter its residue. Existing judgment/provenance regressions passed. Individual-name adapters cover pytest, Node, Vitest and Jest; other frameworks need adapters or compliant custom runners. See `task-scoped-evaluation.md` for the legacy feature-file mapping and shared-hook limits.
