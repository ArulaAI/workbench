# Eval

`speed eval` runs after a feature's tasks are done. It executes the test spec's scenarios on the integrated tree with the project's own test command and decides acceptance from what actually ran.

This page covers what eval reads, how to configure a project for it, how to run it against `payments-validation-fixture`, and what every word in its output means. It assumes the tests already exist; eval writes none.

For a lead-facing explanation of the goal, input/output shapes, flow diagrams and code evidence, start with the [end-to-end walkthrough](/Users/mohitpatel/Desktop/inrhythm/Workbench/.claude/worktrees/task-scoped-eval/docs/eval/end-to-end-walkthrough.md).

## What it does

- Reads the feature's test spec (`specs/tests/<name>.md`): the Scenario Catalog, Acceptance Traceability, the Execution and Evidence mapping table, and Out of Scope.
- Compiles the mapping table into `.speed/features/<name>/eval/test-plan.json`, one entry per scenario selector.
- Runs each selected test under its configured runner and retains individual test identities, status, exit code and logs. Identical command/selector/name mappings execute once per attempt and reuse the same evidence.
- Without a task ID, evaluates the feature catalog. With `--task-id` (or `--task`), runs only individually mapped tests attributable to that task. Legacy task selectors are used only for one otherwise unmapped scenario and only when they identify individual tests.
- Reports missing or ambiguous mappings without expanding to a whole-file task run. See [task-scoped evaluation](task-scoped-evaluation.md) for the mapping contract and migration examples.
- Builds `report.json`, `evaluation.yaml` and `summary.md`: one record per scenario with a status, an evidence type, and the requirements it traces to. Task acceptance criteria are appended as their own rows. The YAML is the hand-off `workbench define` reads. It lands at `.speed/features/<name>/evaluation.yaml`, beside the `risk-surface.yaml` that `workbench diagnose` writes, and follows the same shape.
- Optionally hands the leftover manual criteria to the evaluator agent. Its verdicts are recorded as opinion and cannot change an executed result.
- Marks the feature `accepted` only when every applicable result passed. A scenario with no test is reported as not examined, never as a pass. There is no score and no percentage.
- Exit code is `0` whatever the verdict unless `--strict` is set. Configuration errors (no spec, missing mapping file, unknown task) exit `3`.

## F1 to F8

The Validation Workbench course names eight failure classes. The test spec and eval cover the ones that depend on test cases; the rest belong to hooks or to a person.

| Class | Failure | Covered by test spec + eval |
|---|---|---|
| F1 | Hallucinated API, config key or dependency | No. Typecheck and dependency resolution |
| F2 | Cardholder data leakage | No. Taint and PAN scanning |
| F3 | Weak test that passes and proves nothing | Partly. The spec fixes the exact outcome each test must prove and a pass is typed statistical, never proof. Mutation still checks the test itself |
| F4 | Broken invariant under generated sequences or retry | Yes. Retry and invariant behaviours are catalog scenarios and run like any other |
| F5 | Sycophantic self-approval | Yes, for the verdict. The evaluator agent's view is recorded as opinion and cannot overturn an executed result |
| F6 | Wrong problem, scope creep, over-engineering | No. Scope guard |
| F7 | Silent regression in untouched behaviour | Yes. A requirement whose scenario has no selector is printed as not examined and blocks acceptance |
| F8 | Specification gap | Recorded, not decided. Out of Scope rows print with disposition and owner; the decision stays with that owner |

## Configuration

Two things live in the project being evaluated, not in this repo.

### The test command

`speed.toml`:

```toml
[eval]
test_command = "node --experimental-strip-types --test --test-reporter=junit --test-reporter-destination=$SPEED_EVAL_JUNIT_FILE {selectors}"
```

Plain shell, harness-agnostic: `pytest -q`, `go test`, `node --test`, whatever the project runs. Eval appends a selector to it, or substitutes the selector for a `{selectors}` placeholder. `test_commands = [...]` allows several when different scenarios need different invocations. When `[eval]` is absent, eval falls back to the `test:` line under `## Quality Gates` in the project's agent file. Eval does not infer `package.json` scripts; configure `npm test --` when the script accepts selectors.

A zero exit on its own is not evidence. The runner must write a test report: JUnit XML to the path eval passes in `SPEED_EVAL_JUNIT_FILE`, or JSON of the form `{"tests": [{"id": "...", "status": "pass"}]}` to the `{report}` placeholder. pytest gets `--junitxml` added for it; Node gets JUnit flags when no reporter is already configured. Vitest and Jest get JSON reporter arguments. Existing explicitly configured Node reporters must write JUnit to `SPEED_EVAL_JUNIT_FILE`. A run that exits 0 without a report is reported as not examined, never as a pass.

Eval routes mapped files through configured commands using subsystem and runner information. Set Command explicitly when several commands could apply, and Runner for wrappers such as `npm test --`. A test-based task criterion must refer to scenarios through existing task references or the optional Criterion column in the spec; it reuses their results instead of invoking a whole file again. Unmapped automated criteria remain unverified and are never sent to the LLM evaluator.

### The test spec

`speed new test-spec <name>` scaffolds `specs/tests/<name>.md` from `templates/test-spec.md`. Eval reads four of its sections.

| Section | What eval takes from it |
|---|---|
| Scenario Catalog | Every `PREFIX-NN` row and the H3 area it sits under. Group by functional concern, never by whether a test exists yet |
| Acceptance Traceability and Additional Coverage | The requirement labels (`ST3`, `TR4`, a risk row) whose covering-scenarios cell names each scenario |
| Execution and Evidence | The `Scenario / Task / Selector / Test name / Runner / Command / Criterion` table. Older Scenario/Selector/Command tables remain readable. Repeat rows for multiple tests/files; an empty Selector records a missing test. Optional columns bind tasks and exact tests without task JSON changes |
| Out of Scope | Rows with an ID, a disposition, a reason and an owner |

Selector is a file path (or a pytest `file::test` node ID). Backticks preserve selectors containing spaces or parameter IDs. Test name is a literal full JavaScript test title; eval escapes and anchors it before passing it to the runner. Selectors cannot be empty, option-like, contain control characters, or leave the project. Whole-file selectors remain available for legacy feature runs, with an explicit attribution limitation; task runs require individual tests.

Eval evaluates a feature, so `.speed/features/<name>/` must exist: from `speed plan`, or `mkdir -p .speed/features/<name>/tasks` when there is no plan. Any task files present must have status `done`.

## Run

Fresh checkout, reproducing the `payments` example on the fixture's `main`. The fixture needs Node 22 or later for its `--experimental-strip-types` tests.

```bash
git clone https://github.com/ArulaAI/workbench.git
git clone https://github.com/ArulaAI/payments-validation-fixture.git
cd payments-validation-fixture

cat > speed.toml <<'TOML'
[eval]
test_command = "node --experimental-strip-types --test --test-reporter=junit --test-reporter-destination=$SPEED_EVAL_JUNIT_FILE {selectors}"
TOML

../workbench/speed new test-spec payments      # writes specs/tests/payments.md
# Fill the catalog, traceability and mapping table from specs/tech/payments.md
# and specs/product/payments.md. The completed spec from the eval work maps
# AC-* rows to test/service.test.ts, VAL-* to test/money.test.ts and
# LEDGER-* to test/ledger.test.ts, and leaves four rows without a selector.

mkdir -p .speed/features/payments/tasks
../workbench/speed eval -f payments --skip-judge --no-defects
```

The commands above describe initial setup; skip creation if your fixture branch already contains these files. For task-level execution, add Task and Test name mappings as shown in the task-scoped guide. `workbench eval` is the same command: `workbench` is a thin forwarder that execs `speed` with the same arguments, so either name works. Add `--strict` to get exit `2` on a not-accepted verdict for CI.

```
speed eval --feature <name> [--test-spec PATH] [--test-plan PATH]
           [--task-id ID] [--strict] [--no-defects] [--skip-judge]
```

| Flag | Effect |
|---|---|
| `--test-spec PATH` | Use this spec instead of `specs/tests/<name>.md` beside the RFC |
| `--test-plan PATH` | Override the spec's mapping table with a JSON mapping (for tool-generated plans) |
| `--task-id ID`, `--task ID` | Execute only that task’s individually mapped tests and criteria; report goes to `eval/task-<id>/`, feature state untouched |
| `--strict` | Exit `2` when not accepted. Default exit is `0` whatever the verdict |
| `--no-defects` | Do not file P2 defect specs for failed scenarios |
| `--skip-judge` | Leave manual criteria unverifiable instead of invoking the evaluator agent |

## Output

Historical feature run using file-level mappings (task-scoped validation results are recorded in [the checklist](task-scope-checklist.md)):

```
Change: main @ uncommitted-working-tree   spec: specs/tests/payments.md
    Authorise                  3 pass, 1 not examined
    Capture                    3 pass, 2 not examined
    Refund and void            3 pass, 1 not examined
    Settlement and invariants  2 pass
    Money                      4 pass
    Ledger                     2 pass
    Acceptance gates           3 not examined

    not examined
      RISK-01    TR11, Product risk, Critical    No test mapped to this scenario
      AC-12      ST6                             No test mapped to this scenario
      RISK-02    ST3, Product risk, High         No test mapped to this scenario
      EDGE-01    ST4                             No test mapped to this scenario
      COVERAGE-01 -                              No scenario covers requirement: TR12: only scheme test BINs anywhere in the repository
      BUILD-COMMITTED -                          The tested working tree has uncommitted changes
      BUILD-INTEGRATED -                         Integration has not completed successfully for this feature

    not examined by decision
      OOS-01     Deferred                     payments-product to decide; release claim bounded until then
      OOS-02     Deferred                     scheme relations
      OOS-03     Deferred                     payments-operations
      OOS-04     Not applicable to this spec  Course workflow
      OOS-05     Not applicable to this spec  Course workflow
      OOS-06     Not applicable               Spec owners

Report written to <project-root>/.speed/features/payments/eval/runs/<run-id>/summary.md
Evaluation written to <project-root>/.speed/features/payments/evaluation.yaml
Not accepted. 7 never examined.
```

21 scenarios, 17 pass, 4 not examined, plus three acceptance gates. The existing suite is fully green, so a plain test run reports nothing wrong; eval reports that four requirements were never checked. The `Acceptance gates` rows come from the runtime, not the spec: `COVERAGE-01` names a requirement row (TR12) that no scenario covers, `BUILD-COMMITTED` reports the uncommitted `speed.toml` and spec in the tested tree, and `BUILD-INTEGRATED` reports that no integration has completed for the feature. All three block acceptance until resolved. A `failed` block appears before the verdict when a mapped test fails.

Each attempt has an immutable directory under `.speed/features/<name>/eval/runs/<run-id>/`. Completed attempts also update the files directly under `eval/`, and place the YAML hand-off in the feature directory itself. Task-scoped runs use `eval/task-<id>/` as their output root and name their hand-off `evaluation-task-<id>.yaml`, so a partial run never overwrites the feature verdict.

Files written under `.speed/features/<name>/`:

| File | Content |
|---|---|
| `eval/test-plan.json` | The mapping compiled from the spec's table |
| `eval/scenario-results.json` | Per-scenario status, command, evidence and timestamp |
| `eval/report.json` | Every result with status, evidence type, traces, area and task; `out_of_scope`; `summary`; per-test execution detail |
| `eval/summary.md` | The same as tables, with a Not examined by decision section |
| `eval/residue.json` | Manual criteria still unverifiable, the evaluator agent's input |
| `eval/runs/<run-id>/summary.md` | The attempt's summary, whose path is printed in the terminal |
| `eval/runs/<run-id>/evaluation.yaml` | The attempt's own copy of the YAML hand-off |
| `eval/runs/<run-id>/commands/<execution-id>/output.log` | The runner's output; each result identifies its execution log |
| `eval/latest-attempt.json` | The latest attempt ID and completion or failure status |
| `evaluation.yaml` | The verdict, selection scope, and individual test evidence as YAML, copied from the latest completed attempt; the next workflow step reads this file. Sits beside diagnose's `risk-surface.yaml`. Task-scoped runs write `evaluation-task-<id>.yaml` instead |
| `state.json` | Evaluation metadata; `accepted` or `integrated_not_accepted` after a full run with verified integration |

### The evaluation YAML

`.speed/features/<name>/evaluation.yaml` is the artifact the workflow carries forward: `workbench diagnose` writes `risk-surface.yaml` in the same directory, `workbench eval` writes this file, and `workbench define` turns its failed and not-examined results into defect specs. Trimmed from the fixture run above (two results out of 24, one Out of Scope row out of six):

```yaml
# Written by `speed eval`. Each result carries its evidence. Silence is not a pass.
feature: payments
task: null
run_id: "a23d91fd73b34d9db68e96653a66549b"
generated_at: "2026-09-18T11:45:31Z"
test_spec: "<project-root>/specs/tests/payments.md"
test_spec_sha256: "a56fad841eb40b5cc083519179c248f005c6cfed97629fad79311cc13993702b"
commit: null
build:
  head_commit: "652a8648384792c6ca862911a7d5fa9602d9a85b"
  fingerprint: "75582d6a310b913b93b3194eff2e0e7a482ff52c213756b1a81282fb330a509d"
  dirty: true
accepted: false
summary:
  total: 24
  examined: 17
  not_examined: 7
  pass: 17
  fail: 0
  partial: 0
  blocked_upstream: 0
  unverifiable: 7
  not_applicable: 0
results:
  - id: AC-01
    kind: scenario
    area: Authorise
    title: "Given a valid card, when 2500 is authorised, then the amount is reserved and a balanced pair is posted"
    expected: "authorised is 2500; status authorised; ledger nets to 0; exactly two entries for the payment"
    level: integration
    status: pass
    evidence_type: statistical
    evidence: "All 11 discovered tests executed and passed (log: <project-root>/.speed/features/payments/eval/runs/<run-id>/commands/<execution-id>/output.log)"
    traces: [ST1, TR5]
    task: null
    command: "node --experimental-strip-types --test --test-reporter=junit --test-reporter-destination=$SPEED_EVAL_JUNIT_FILE test/service.test.ts"
    log: "<project-root>/.speed/features/payments/eval/runs/<run-id>/commands/<execution-id>/output.log"
  - id: RISK-01
    kind: scenario
    area: Authorise
    title: "Given an authorise request that fails, when the failure is serialised to the application log, then no field holds a full card number"
    expected: "the logged record shows the pan field as redacted"
    level: integration
    status: unverifiable
    evidence_type: silence
    evidence: "No test mapped to this scenario"
    traces: [TR11, "Product risk, Critical"]
    task: null
    command: null
    log: null
out_of_scope:
  - id: OOS-01
    excluded: "Refund idempotency: whether two identical refund requests are one refund or two"
    disposition: Deferred
    reason: "ST6 covers authorise and capture only; asserting either answer would invent policy"
    owner: "payments-product to decide; release claim bounded until then"
```

| Field | Meaning |
|---|---|
| `task` | `null` for a whole-feature run; the task ID for `--task-id` runs, where `results[].task` names the owning task |
| `commit` | The tested commit, or `null` when the tree had uncommitted changes; `build.head_commit` and `build.dirty` then say which commit and that it was dirty |
| `results[].kind` | `scenario` from the catalog, `criterion` from a task's acceptance criteria, `gate` for the runtime's `COVERAGE-NN` and `BUILD-*` rows |
| `results[].status`, `results[].evidence_type` | The vocabulary in Reading the result below |
| `results[].traces` | The requirement IDs the scenario covers, from Acceptance Traceability |
| `results[].command`, `results[].log` | What ran and where its output is; both `null` when nothing ran |

Every value is a plain scalar or a list of scalars, and free text is always double-quoted, so the file loads with any YAML parser without a schema. The per-test breakdown of each execution is in `report.json` and in the log each result names.

## Reading the result

### The blocks

| Block | What is listed | Where it comes from |
|---|---|---|
| Area rows | One row per H3 in the Scenario Catalog, plus `Task criteria` when task files carry acceptance criteria. Counts `pass`, `fail`, `not examined` and `n/a`; zero counts are left out. `fail` here also covers `partial` and `blocked_upstream` | Result statuses, grouped by catalog area |
| `not examined` | Every `unverifiable` result: ID, the requirements it traces to, why nothing ran | Empty Selector cells, tasks that declare a scenario but never ran it, manual criteria nobody judged |
| `not examined by decision` | The spec's Out of Scope rows: ID, disposition, owner. Not scenarios, in no count | The Out of Scope table, verbatim |
| `failed` | Every `fail`, `partial` or `blocked_upstream` result with its evidence type and gate log path | Runs that exited non-zero, rejected selectors, unconfigured commands |
| Verdict | `Accepted. Every scenario was examined and passed.` or `Not accepted. N failed; M never examined.` | The acceptance rule below |

The trace labels (`ST3`, `TR11`, `Product risk, High`) come from every Acceptance Traceability or Additional Coverage row whose covering-scenarios cell names the scenario. A risk row without an ID contributes the text before its first colon. `-` means no row names the scenario. A scenario named only in a row's gap column is not traced to it.

### Status

Execution produces only `pass` and `fail`. The other four come from the mapping, the dependency graph or task criteria.

| Status | Terminal word | How a result gets it | Blocks acceptance |
|---|---|---|---|
| `pass` | pass | Every selector mapped to the scenario ran under the configured command and exited 0 | No |
| `fail` | fail | A selector exited non-zero. Also given without running when a selector has disallowed characters, its Command cell is unconfigured, the scenario ID is duplicated in the catalog, or two tasks both claim it | Yes |
| `partial` | fail | Only from the evaluator agent judging a manual criterion that holds in part. Execution never produces it | Yes |
| `blocked_upstream` | fail | The scenario failed and a scenario it lists in `depends_on_scenarios` also failed. `root_cause` names the nearest failed upstream | Yes |
| `unverifiable` | not examined | Nothing ran: empty Selector, a task with the scenario but no selectors, a manual criterion skipped with `--skip-judge`, or a `verify_by: test` criterion with no test command | Yes |
| `not_applicable` | n/a | A task criterion needs a tool the project does not declare, such as `verify_by: lint` with no lint command. Catalog scenarios never get it | No |

`unverifiable` and `fail` both block acceptance, but only `fail` files a defect. A catalog scenario with no mapped test is a coverage gap. A task that explicitly requires test verification but has no corresponding test files fails that criterion, matching the legacy criteria verifier.

### Evidence type

Each result also says what kind of evidence backs it, in the course's evidence ledger vocabulary.

| Evidence type | Attached to | What it supports |
|---|---|---|
| `counterexample` | `fail`, `partial`, `blocked_upstream` from execution | A concrete run in which the behaviour was wrong. The strongest evidence eval produces |
| `statistical` | `pass` from execution | The test's example inputs behaved as expected. Not that all inputs do |
| `proof` | `pass` on a task criterion checked by file existence, schema match or lint | A deterministic check within its ruleset |
| `opinion` | Any status set by the evaluator agent | A reading of prose against a manual criterion. Never allowed to change an executed result |
| `silence` | `unverifiable` | Nothing was observed. Supports no claim either way |
| `none` | `not_applicable` | No claim is made |

### Not examined by decision

The disposition is copied from the spec's Out of Scope table. The template asks for one of two words.

| Disposition | Meaning | A gap? |
|---|---|---|
| `Deferred` | Required coverage a named owner has postponed. Exit Criteria must record the decision and a follow-up | Yes, an accepted one. The release claim is narrower until it closes |
| `Not applicable` | The check does not apply to this feature or spec, such as chargebacks outside the current version or repository scans that are not runtime scenarios | No |

### Verdict, counts and exit code

`summary.md` opens with the outcome and one row of counts: Total, Examined (total minus `unverifiable`), Pass, Fail, Partial, Blocked, Not examined (the `unverifiable` count), N/A.

Acceptance needs at least one applicable result and every applicable result `pass`. Applicable means every status except `not_applicable`. A full run moves feature state to `accepted` or `integrated_not_accepted`; a `--task-id` run reports and leaves state alone.

| Exit code | When |
|---|---|
| `0` | Any verdict, unless `--strict` is set |
| `2` | Evaluation completed with `--strict` and was not accepted |
| `3` | Evaluation could not run: missing or invalid inputs, an unknown or unfinished task, a feature ownership conflict, a lock conflict, or an operational error |

## Known limits

- A runner that cannot write a JUnit or JSON report supplies no evidence, so its scenarios stay not examined. A selector that matches nothing is caught the same way: no tests in the report, no pass.
- Eval reports what the tests assert. It will not find a defect no test looks at, and it does not run mutation, taint or differential checks.
- The `speed` CLI runs its dependency preflight first; on a machine without the ast-grep grammars built, `speed help` exits `3` before eval starts.

## Tests

```bash
python3 -m pytest tests/test_eval_report.py tests/test_eval_report_blocked.py \
                  tests/test_test_spec.py tests/test_toml_eval.py   # report, mapping, toml
python3 tests/test_eval_yaml.py                                     # evaluation.yaml
bash tests/test_eval.sh                                             # CLI command
```

Last verified: 36 + 10 + 20 = 66 tests passing, 0 failing.
