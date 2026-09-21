# Diagnose

`speed diagnose` runs after an agent's task completes and before review or judgment.

## What it does

- Diffs the task's branch against `main` (`git diff main...<branch>`).
- Reads only the task's `branch`, `files_touched`, and `agent_model`. It never reads `description`, `acceptance_criteria`, or `review_feedback` — those are written about the change after the fact and would hand the human the answer.
- Runs the project's own rules against the diff, one rule set per failure class (F1–F8).
- Writes every declared class to `risk-surface.yaml`, each with a signal count and `plausible`, `costOfMissing`, `findableByReading` set to `undecided`. No rule can set any of these three.
- A signal is a routing hint, not proof or a verdict. It points at where a downstream check (typecheck, mutation, invariant, differential, etc.) should look. Zero signals doesn't mean the class is absent — it means nothing was mechanically countable.
- Exit code is `0` on any successful run, no matter how many signals fired. A missing or broken configuration (no classes file, task not found, no branch recorded, etc.) exits `3`.

**Known gap:** some earlier design notes describe diagnose reading "two declared file lists" from the task. The current task schema (`templates/architect-output.json`) only has one: `files_touched`. Diagnose reads only that field.

## F1–F8

| Class | Title | Signal |
|---|---|---|
| F1 | Hallucinated API, config key or dependency | new import/require statement, or reference to a new env var |
| F2 | Cardholder data leakage | observability sink call, or a 13–19 digit sequence, in added lines |
| F3 | Weak test that passes and proves nothing | a source file and a matching test file changed together |
| F4 | Broken invariant under generated sequences or retry | a retry/repeat construct combined with a payment-affecting call on the same line |
| F5 | Sycophantic self-approval | none — always `signals: []` |
| F6 | Wrong problem, scope creep, over-engineering | a changed file outside the task's declared file list |
| F7 | Silent regression in untouched behaviour | a changed source file with no matching test change |
| F8 | Specification gap | a new name introduced by the diff that the spec file never uses |

## Configuration

`speed.toml` and `.speed/classes.yaml` live in the project being diagnosed (e.g. `payments-validation-fixture`), not in this repo. Diagnose has no rules of its own — a project supplies them through a `[diagnose]` section in its `speed.toml`:

```toml
[diagnose]
classes_file = ".speed/classes.yaml"
spec_file = "specs/product/payments.md"
```

`classes_file` defaults to `.speed/classes.yaml` if not set. `spec_file` is only used by the `new-names-absent-from-spec` rule — for `payments-validation-fixture` that's `specs/product/payments.md`.

Each class in `classes.yaml` declares zero or more rules. A rule has a `look` (how it scans the diff), an optional `match` (regex, for the `added-lines` look), and a `say` template for the signal text:

```yaml
classes:
  - id: F2
    title: Cardholder data leakage
    rules:
      - look: added-lines
        match: '\b(log|logger|webhook|telemetry)\s*\.'
        say: "{n} file(s) with an observability sink call in the added lines"
      - look: added-lines
        match: '(?<!\d)\d{13,19}(?!\d)'
        say: "{n} added line(s) containing a 13 to 19 digit sequence"
```

A class with no rules (F5, sycophantic self-approval) always reports `signals: []` — no mechanical way to check it, not a ruling that it didn't happen.

`.speed/` is gitignored in the diagnosed project (it's SPEED's runtime state directory). `classes.yaml` is committed there as a tracked exception; task records under `.speed/features/*/tasks/` are not committed and need to be created locally.

`speed.toml` and `.speed/classes.yaml` live on the `feat/301-config` branch of `payments-validation-fixture`, not on `main` or on any round branch.

### The checkout supplies config; the task record supplies the diff — these are independent

Diagnose reads two things that have nothing to do with each other:

- **Project config** (`speed.toml`, `.speed/classes.yaml`) comes from `PROJECT_ROOT` — whatever happens to be checked out on disk when you run the command.
- **The diagnosed diff** comes from the task record's `branch` field, diffed against whatever `git_main_branch()` resolves to (`main`, unless `MAIN_BRANCH` overrides it). `git_diff_branch`/`git_main_branch` (`lib/git.sh`) resolve both purely by ref name — `git -C "$PROJECT_ROOT" diff <main>...<branch>` — with no dependency on the current `HEAD`.

So you can check out `feat/301-config` (to put its config files on disk) while diagnosing a completely different pair of refs (`main...round-0`) — the checkout is never part of the diff, and never needs to be.

## Run

Diagnosing the real `round-0` course round against `payments-validation-fixture`'s actual `main`:

```bash
# feat/301 carries the Diagnose implementation — a plain clone leaves you
# on main, which doesn't have it.
git clone -b feat/301 https://github.com/ArulaAI/workbench.git
git clone https://github.com/ArulaAI/payments-validation-fixture.git
cd payments-validation-fixture

# Check out the ref that carries SPEED's config — this determines what's
# on disk, not what gets diffed.
git checkout feat/301-config

# round-0 and main only need to be resolvable refs, not checked out. If you
# cloned this repo directly with `git clone -b feat/301-config ...` instead
# of the plain-clone-then-checkout above, main has no local branch either —
# only origin/main — so create both explicitly:
git branch round-0 origin/round-0   # if you don't already have a local round-0
git branch main origin/main         # if you don't already have a local main

# .speed/round-0-task.example.json is the tracked source of truth for this
# task record (see the fixture's own README, "SPEED Diagnose" section) —
# copy it in once per clone, the same way corpus/decisions.example.json
# becomes decisions.json there.
mkdir -p .speed/features/payments/tasks
cp .speed/round-0-task.example.json .speed/features/payments/tasks/1.json

../workbench/speed diagnose -f payments --task 1
```

No `MAIN_BRANCH` override — `round-0` branched off the fixture's real `main` before the config commit existed on any branch, so `main` is already the correct baseline. This diffs exactly `main...round-0` (independently verified: the four changed files and the 51 insertions/3 deletions match the course's own reference description of the change) and writes `.speed/features/payments/risk-surface.yaml`.

## Risk surface

A trimmed example against `round-0` (three classes out of the eight that always appear):

```yaml
# Written by `speed diagnose`. The signals are counted. The verdicts are yours.
task: "1"
branch: "round-0"
agent_model: "sonnet"
classes:
  - id: F2
    failureMode: "Cardholder data leakage"
    plausible: undecided
    costOfMissing: undecided
    findableByReading: undecided
    signals:
      - observed: "1 file(s) with an observability sink call in the added lines"
        where:
          - "src/payments/service.ts"
      - observed: "1 added line(s) containing a 13 to 19 digit sequence"
        where:
          - "test/fixtures/cards.ts"
  - id: F3
    failureMode: "Weak test that passes and proves nothing"
    plausible: undecided
    costOfMissing: undecided
    findableByReading: undecided
    signals:
      - observed: "1 changed source file(s) with an accompanying test change — a routing candidate for mutation testing; a test existing (or asserting) proves nothing about whether it discriminates correct from broken"
        where:
          - "src/payments/retry.ts"
  - id: F5
    failureMode: "Sycophantic self-approval"
    plausible: undecided
    costOfMissing: undecided
    findableByReading: undecided
    signals: []   # nothing countable. Not a ruling.
```

The F2 signal on `service.ts` is the course's deliberate red herring: `redact(req)` became `req` on line 67. It reads exactly like a cardholder-data leak, and it isn't one — `serialiseFailure` redacts elsewhere. Diagnose correctly surfaces it as a signal (a routing hint) and does not, and cannot, rule on it; a human has to read the surrounding code to rule it out, which is the entire point of the exercise.

The F3 signal on `retry.ts` pairs it with `test/refund-retry.test.ts` — a test file named after the feature it exercises ("refund retry") rather than mirroring the source filename. `changed-source-with-test-change` recognizes this because the source's stem (`retry`) appears as a whole hyphen/underscore-delimited word within the test's stem, not just under exact stem equality (`test_foo.py` / `foo.test.ts` / `foo_test.go`).

## Tests

```bash
python3 tests/test_diagnose_engine.py         # rule engine
python3 tests/test_toml_diagnose.py           # [diagnose] speed.toml section
bash tests/test_diagnose_cmd.sh               # CLI command
python3 tests/test_diagnose_round0_fixture.py # regression test against the real, frozen round-0 diff
```
