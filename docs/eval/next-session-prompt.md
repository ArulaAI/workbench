# Next-session prompt

Copy the following into a new session:

---

Continue reviewing the completed task-scoped `speed eval` implementation. First use this checkout:

`/Users/mohitpatel/Desktop/inrhythm/Workbench/.claude/worktrees/task-scoped-eval`

Branch: `feat/eval-test-spec-template`, originally based on `ff04f50`. The shared `/Users/mohitpatel/Desktop/inrhythm/Workbench` checkout was left clean on `main`; do not switch or alter it to find this work. Read this branch's latest local commit and git status before changing anything. Changes were not pushed.

Read these repository files first:

1. `docs/eval/task-scoped-evaluation.md`: implemented design, examples, source-file responsibilities and limitations.
2. `docs/eval/task-scope-checklist.md`: every requirement and its validating test.
3. `docs/eval/validation.md`: observed counts, real payment fixture outcomes, runner versions and reproduction commands.

User requirements already implemented:

- Preserve the existing task JSON schema. Use Task/Test name/Runner/optional Criterion columns in the test spec and generated test-plan JSON for mapping.
- No task argument means all declared feature scenarios. `--task-id ID` and `--task ID` mean only that task's exact mapped tests and criteria.
- Select individual tests within files shared by different tasks. Support several tests across several files for one task and mixed frontend/backend runners.
- Attribute a failure only to scenarios mapped to that test. Reuse identical execution evidence once per attempt.
- Report missing mappings/files/individual tests, empty discovery, selected skips and ambiguity in both scopes. Do not guess ownership or expand a task to a whole-file run.
- Keep unresolved manual criteria in residue for optional review. Missing automated evidence cannot become an LLM pass.
- Preserve source/build provenance and separate task reports/YAML from the feature verdict.

Important implementation details:

- `lib/test_spec.py` parses extended mapping columns and retains owners for empty mapping rows.
- `lib/eval_selection.py` resolves explicit Task, existing scenario references, or unique file ownership using configured test patterns. Shared file ownership requires an explicit Task mapping. It records coverage/selection gaps and criterion associations.
- `lib/eval_execution.py` applies pytest node IDs or exact escaped JavaScript full-title filters, captures JUnit/JSON evidence and verifies selected identities.
- `lib/eval_runtime.py` prepares immutable attempts, filters scope, caches identical executions, suppresses unrelated task batches and preserves missing mapping rows.
- `lib/eval_report.py` reuses criterion scenario results and writes scope/per-test evidence to JSON, Markdown and YAML. Test criteria without associations remain unverified.
- No changes were needed in task creation/persistence (`lib/tasks.sh` or plan's task schema).

Validation completed: 204 distinct Python tests plus 3 subtests, 81 shell checks. This includes real pytest, Node, Vitest and Jest runs, an unmodified CLI with dependency preflight, Node 22 compatibility, and copied payments-fixture integrations. The final catalog-only guard regression was added and run separately after the 203-test combined pass; see the exact record in validation.md. Do not install dependencies or repeatedly rerun all suites without a new change or unresolved concern.

Original payment fixture:

`/Users/mohitpatel/Desktop/inrhythm/payments-validation-fixture`

It was only read/copied and remains unchanged on `codex/payments-test-spec` (inspected at `307cd00`). The test-only copy maps task 1 to AC-01 + AC-02 in service.test.ts and VAL-01 in money.test.ts: exactly three tests pass. Feature eval runs all 17 implemented scenario tests and flags RISK-01, RISK-02, AC-12 and EDGE-01 plus the existing TR12 coverage gap. The original fixture still uses coarse file-level mappings and has not been migrated to the new task mappings.

Next steps with me:

1. Walk me through the design so I can explain it to my lead, using the three-test/two-file task example.
2. Review whether this Task/Test name/optional Criterion spec format is the desired authoring contract. Shared-file ownership cannot be inferred from files_touched alone.
3. If I request migration, apply the explicit mappings to the real fixture using its actual task IDs, then rerun task and feature eval. Do not copy synthetic task IDs 1/2 from tests into a real plan without checking it.
4. Keep RISK-01, RISK-02, AC-12, EDGE-01 and TR12 visibly incomplete until actual tests/spec work closes them; do not invent passing evidence.
5. Consider future runner adapters or authoring automation only if requested. Reviewers still check assertion quality and missing business requirements. Legacy file mappings remain feature-level aggregates, and shared test setup/hooks still run.

Do not send messages, push branches, open PRs or change the original fixture merely because this handoff mentions them. Review the current branch and continue with my next explicit request.

---
