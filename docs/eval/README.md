# Eval

`speed eval` runs after a feature's tasks are done. It executes the test spec's scenarios on the integrated tree with the project's own test command and decides acceptance from what actually ran.

This page covers what eval reads, how to configure a project for it, how to run it against `payments-validation-fixture`, and what every word in its output means. It assumes the tests already exist; eval writes none.

## What it does

- Reads the feature's test spec (`specs/tests/<name>.md`): the Scenario Catalog, Acceptance Traceability, the Execution and Evidence mapping table, and Out of Scope.
- Compiles the mapping table into `.speed/features/<name>/eval/test-plan.json`, one entry per scenario selector.
- Runs each selector under the configured test command, one scenario at a time, and records the exit code and gate log per scenario.
- Runs any selectors that finished tasks declare in their task files the same way.
- Builds `report.json` and `summary.md`: one record per scenario with a status, an evidence type, and the requirements it traces to. Task acceptance criteria are appended as their own rows.
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
test_command = "node --experimental-strip-types --test"
```

Plain shell, harness-agnostic: `pytest -q`, `go test`, `node --test`, whatever the project runs. Eval appends a selector to it, or substitutes the selector for a `{selectors}` placeholder. `test_commands = [...]` allows several when different scenarios need different invocations. When `[eval]` is absent, eval falls back to the `test:` line under `## Quality Gates` in the project's agent file. `package.json` scripts are never read, because `npm test` runs the whole suite and cannot take a selector.

### The test spec

`speed new test-spec <name>` scaffolds `specs/tests/<name>.md` from `templates/test-spec.md`. Eval reads four of its sections.

| Section | What eval takes from it |
|---|---|
| Scenario Catalog | Every `PREFIX-NN` row and the H3 area it sits under. Group by functional concern, never by whether a test exists yet |
| Acceptance Traceability and Additional Coverage | The requirement labels (`ST3`, `TR4`, a risk row) whose covering-scenarios cell names each scenario |
| Execution and Evidence | The `Scenario / Selector / Command` table. One row per scenario; several selectors in one cell separated by spaces; an empty Selector means no test yet. Command is optional and must equal a configured command |
| Out of Scope | Rows with an ID, a disposition, a reason and an owner |

Selectors are whatever the runner accepts after the command: a file path, `path::test_name`, a name pattern. Allowed characters are letters, digits and `_ . / : @ = , + -`. Anything else is rejected without running.

Eval evaluates a feature, so `.speed/features/<name>/` must exist: from `speed plan`, or `mkdir -p .speed/features/<name>/tasks` when there is no plan. Any task files present must have status `done`.

## Run

Fresh checkout, reproducing the `payments` example on the fixture's `main`. The fixture needs Node 22 or later for its `--experimental-strip-types` tests.

```bash
git clone https://github.com/ArulaAI/workbench.git
git clone https://github.com/ArulaAI/payments-validation-fixture.git
cd payments-validation-fixture

cat > speed.toml <<'TOML'
[eval]
test_command = "node --experimental-strip-types --test"
TOML

../workbench/speed new test-spec payments      # writes specs/tests/payments.md
# Fill the catalog, traceability and mapping table from specs/tech/payments.md
# and specs/product/payments.md. The completed spec from the eval work maps
# AC-* rows to test/service.test.ts, VAL-* to test/money.test.ts and
# LEDGER-* to test/ledger.test.ts, and leaves four rows without a selector.

mkdir -p .speed/features/payments/tasks
../workbench/speed eval -f payments --skip-judge --no-defects
```

`speed.toml` and `specs/tests/payments.md` are not committed in the fixture yet; the commands above create them. `workbench eval` is the same command: `workbench` is a thin forwarder that execs `speed` with the same arguments, so either name works. Add `--strict` to get exit `2` on a not-accepted verdict for CI.

```
speed eval --feature <name> [--test-spec PATH] [--test-plan PATH]
           [--task-id ID] [--strict] [--no-defects] [--skip-judge]
```

| Flag | Effect |
|---|---|
| `--test-spec PATH` | Use this spec instead of `specs/tests/<name>.md` beside the RFC |
| `--test-plan PATH` | Override the spec's mapping table with a JSON mapping (for tool-generated plans) |
| `--task-id ID` | Evaluate one task's scenarios and criteria only; report goes to `eval/task-<id>/`, feature state untouched |
| `--strict` | Exit `2` when not accepted. Default exit is `0` whatever the verdict |
| `--no-defects` | Do not file P2 defect specs for failed scenarios |
| `--skip-judge` | Leave manual criteria unverifiable instead of invoking the evaluator agent |

## Output

The run on the fixture's `main`:

```
Change: main @ 652a864   spec: specs/tests/payments.md
    Authorise                  3 pass, 1 not examined
    Capture                    3 pass, 2 not examined
    Refund and void            3 pass, 1 not examined
    Settlement and invariants  2 pass
    Money                      4 pass
    Ledger                     2 pass

    not examined
      RISK-01    TR11, Product risk, Critical    No test mapped to this scenario
      AC-12      ST6                             No test mapped to this scenario
      RISK-02    ST3, Product risk, High         No test mapped to this scenario
      EDGE-01    ST4                             No test mapped to this scenario

    not examined by decision
      OOS-01     Deferred                     payments-product to decide; release claim bounded until then
      OOS-02     Deferred                     scheme relations
      OOS-03     Deferred                     payments-operations
      OOS-04     Not applicable to this spec  Course workflow
      OOS-05     Not applicable to this spec  Course workflow
      OOS-06     Not applicable               Spec owners

Report written to .speed/features/payments/eval/summary.md
Not accepted. 4 never examined.
```

21 scenarios, 17 pass, 4 not examined. The existing suite is fully green, so a plain test run reports nothing wrong; eval reports that four requirements were never checked. A `failed` block appears before the verdict when a mapped test fails.

Files written under `.speed/features/<name>/`:

| File | Content |
|---|---|
| `eval/test-plan.json` | The mapping compiled from the spec's table |
| `eval/scenario-results.json` | Per-scenario status, command, evidence and timestamp |
| `eval/report.json` | Every result with status, evidence type, traces, area and task; `out_of_scope`; `summary` |
| `eval/summary.md` | The same as tables, with a Not examined by decision section |
| `eval/residue.json` | Manual criteria still unverifiable, the evaluator agent's input |
| `logs/gate-Scenario <ID>-<timestamp>.log` | The runner's output for each scenario |
| `state.json` | `accepted` or `integrated_not_accepted` after a full run |

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

`unverifiable` and `fail` both block acceptance, but only `fail` files a defect. A missing test is a gap in the spec, not a defect in the product.

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
| `2` | `--strict` and not accepted; or a task in the feature is not `done` |
| `3` | No test spec found, `--test-plan` file missing, `--task-id` names an unknown task |

## Known limits

- Per-file selectors are safe. A per-test name pattern that matches nothing exits 0 in Node's runner and would read as a pass; a discovery guard is the next addition.
- Eval reports what the tests assert. It will not find a defect no test looks at, and it does not run mutation, taint or differential checks.
- The `speed` CLI runs its dependency preflight first; on a machine without the ast-grep grammars built, `speed help` exits `3` before eval starts.

## Tests

```bash
python3 -m pytest tests/test_eval_report.py tests/test_eval_report_blocked.py \
                  tests/test_test_spec.py tests/test_toml_eval.py   # report, mapping, toml
bash tests/test_eval.sh                                             # CLI command
```

Last verified: 33 + 18 = 51 tests passing, 0 failing.
