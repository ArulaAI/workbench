# Task-scoped eval implementation checklist

Started 2026-09-20 from `feat/eval-test-spec-template` at `ff04f50`.
Implementation checkout: `.claude/worktrees/task-scoped-eval` (shared main checkout left alone).

## Requirements and decisions

- [x] R1. Keep the task JSON schema unchanged; consume existing `files_touched`, task IDs, and acceptance criteria.
- [x] R2. A feature eval without a task ID evaluates all declared feature scenarios; missing mappings/tests remain visible.
- [x] R3. A task eval executes only tests explicitly attributable to that task, including selected tests inside shared files.
- [x] R4. Support one task selecting several tests across several files; unrelated tasks/tests must not execute.
- [x] R5. Support backend Python/pytest and frontend JavaScript/TypeScript runners with structured per-test results.
- [x] R6. Attribute failures to individual mapped tests/scenarios, not every scenario sharing the process/file.
- [x] R7. Detect missing mappings, missing files, missing/renamed tests, empty discovery and skipped selected tests at task and feature scope.
- [x] R8. Use configured test-file patterns with existing `files_touched`; do not mistake fixtures/helpers for executable tests.
- [x] R9. Preserve source/run provenance, failed evidence, manual-criterion residue and existing feature/task output separation.
- [x] R10. Prevent legacy task-batch and inferred-criterion paths from silently running a wider suite in task mode.
- [x] R11. Explain scope, selected tests, attribution and gaps in JSON, YAML and Markdown outputs.
- [x] R12. Keep a regression checklist with observed test results and an explicit limitations section.
- [x] R13. Leave a next-session prompt in this repository covering changes, validation and follow-up.

## Design constraints

Task JSON is not the new mapping store. Use the test spec's existing Execution and Evidence mapping (including its Task column), extended with individual test identities/runner information, and its generated test-plan JSON. `files_touched` identifies candidate files; it cannot establish ownership of individual tests in a shared file. Ambiguous ownership must be reported rather than guessed. Explicit task/criterion scenario references, when already present, remain usable.

The implementation must distinguish the selected test set from the tests the runner reports. A failure in one selected test must not fail unrelated mapped tests. Missing/filtered-out/skipped required identities cannot turn green. Task success is never feature acceptance.

## Work plan

1. [x] Inspect existing parser/runtime/report/runner and test constraints; finalize compatible mapping and configuration.
2. [x] Implement exact test selection and task attribution without modifying task creation/schema.
3. [x] Implement report/gap handling and guard every fallback execution path.
4. [x] Add regression fixtures covering all cases below and run real supported runners.
5. [x] Run existing eval/parser/TOML/CLI/lock/gate regression tests; investigate failures.
6. [x] Update usage/template documentation, record validation and create next-session handoff prompt.
7. [x] Audit this checklist against implementation and test evidence; explicitly record any remaining limitations.

## Validation matrix

| Case | Expected | Evidence / result |
|---|---|---|
| Two tasks share one file | Selected task's test runs; other test has no side effects | Verified; see the test mapping below |
| One task: two tests in file A, one in file B | Exactly all three execute | Verified; see the test mapping below |
| Feature mode | All mapped feature tests execute | Verified; see the test mapping below |
| Mixed frontend and backend task | Each test reaches its correct runner | Verified; see the test mapping below |
| Individual failure beside passing test | Only mapped failing scenario fails | Verified; see the test mapping below |
| Missing scenario mapping | Visible gap, never a pass | Verified; see the test mapping below |
| Missing/renamed individual test | Visible gap at task and feature scope | Verified; see the test mapping below |
| Missing file / zero discovery | No false pass | Verified; see the test mapping below |
| Skipped selected versus filtered-out tests | Selected skip blocks; unrelated filtered tests do not | Verified; see the test mapping below |
| Shared test mapped to several scenarios | Execute once where possible; reuse only exact evidence | Verified; see the test mapping below |
| Legacy task selectors / inferred test criteria | Cannot widen task execution | Verified; see the test mapping below |
| Files_touched/configured patterns | Correct test candidates, no schema changes | Verified; see the test mapping below |
| Task report versus feature output | Task run leaves feature verdict untouched | Verified; see the test mapping below |
| Malformed mappings/paths/commands | Reject safely, no unintended execution | Verified; see the test mapping below |

## Validation log and remaining limitations

Validation performed on 2026-09-20 (Asia/Kolkata). No changes were made to the original payments fixture or the shared main checkout.

### Scenario-to-test evidence

All names below are in `tests/test_eval_task_scope.py` unless a different file is named.

| Requirement / scenario | Regression evidence |
|---|---|
| R1, R3: shared file, immutable task JSON | `test_shared_node_file_only_selected_test_runs_and_task_json_unchanged` checks the marker and byte-for-byte task contents |
| R2, R6: all feature mappings, individual failure attribution | `test_feature_runs_all_mappings_and_attributes_individual_failures` checks one passing and one failing test in the same file |
| R4: two tests in one file, one in another | `test_one_task_two_tests_in_one_file_and_one_in_another` checks exactly three markers and three command artifacts |
| R5: mixed frontend/backend | `test_mixed_frontend_vitest_and_backend_pytest_task`; `test_jest_individual_test_and_json_evidence`; real Node tests and copied TypeScript payments tests |
| R7: blank/missing/renamed tests in both scopes | `test_blank_owned_mapping_stays_missing_in_both_scopes`, `test_missing_pytest_test_or_file_is_visible`, `test_node_missing_and_skipped_test_never_pass`, `test_missing_additional_mapping_not_hidden_by_passing_test` |
| R7: broken evidence and duplicate identities | `test_malformed_frontend_report_does_not_crash_or_pass`, `test_duplicate_node_full_title_cannot_pass` |
| R8: candidate patterns and ownership | `test_custom_patterns_find_missing_touched_test_file`, `test_unique_file_owner_can_be_inferred_without_task_schema_changes`, `test_shared_file_requires_explicit_ownership` |
| R9: task/feature output separation | Shared-file test plus `tests/test_eval_payments_fixture.py::test_unmodified_cli_payment_task_and_feature`; existing build, manual evidence and lock regressions |
| R10: no fallback widening | `test_whole_file_mapping_and_criterion_cannot_widen_task`, `test_whole_file_legacy_batch_is_not_executed`, `test_legacy_selector_does_not_hide_another_unmapped_touched_file` |
| R10: criterion evidence reuse | `test_test_criterion_reuses_named_scenario_and_does_not_rerun_file`; updated effective-runner and shell-filename security tests |
| R11: YAML/JSON/Markdown evidence | YAML assertion in feature-failure test plus existing `tests/test_eval_yaml.py` |
| Exact-title and parameter handling | `test_nested_node_full_title_selects_only_one_test`, Node punctuation title in shared-file test, `test_pytest_parameterized_selection` |
| Duplicate mapping execution | `test_shared_exact_evidence_executed_once` checks one command artifact for two scenarios |
| Done-task guard and CLI alias | `test_pending_other_task_does_not_block_selected_done_task`, `test_task_alias_dispatches_real_cli` |
| Original payment cases and missing tests | All four tests in `tests/test_eval_payments_fixture.py`; original fixture copied into temporary projects |

### Observed validation

Final regression totals are recorded in `validation.md`, along with commands and installed runner versions. The original payments fixture yielded:

- Task 1: exactly AC-01, AC-02 and VAL-01, three individual tests across two files, accepted.
- Feature: all 17 implemented scenarios passed; RISK-01, RISK-02, AC-12 and EDGE-01 stayed unverified. The existing TR12 coverage gap also remains visible.
- Task 2: its implemented tests ran and its four missing scenarios remained visible; task-1 scenarios were excluded.
- Unmodified CLI with dependency preflight enabled: task-1 strict exit 0; feature and task-2 strict exit 2. Task output did not replace feature output.
- Node 22.17.1 compatibility: seven Node-focused cases plus four copied-payment cases passed, including the real CLI.

### Compatibility decisions and limits

The old regression asserting that an unrelated failing task batch must fail a mapped scenario was changed deliberately: mapped test evidence now defines that scenario's execution set. Another regression now maps both passing and failing tests explicitly to prove executed failures are preserved.

Test criteria without explicit associations no longer infer whole-file execution in the runtime path. Criterion indexes in the spec provide that association without changing task JSON. Direct standalone report generation retains its old feature-only compatibility path; task report generation cannot use it to run broad tests.

Legacy file-only mappings remain available in feature mode and explicitly disclose their attribution limit. Exact task mode requires an individual identity. Shared setup/hooks still execute. Custom runners must honor selectors. Undeclared business requirements and weak assertions still need review. Manual-only tasks are not required to invent automated mappings for their touched files. More detail is in `task-scoped-evaluation.md`.

R12/R13 deliverables: `validation.md` and `next-session-prompt.md`.
