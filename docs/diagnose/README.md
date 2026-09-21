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

`.speed/` is gitignored in `payments-validation-fixture` (it's SPEED's runtime state directory). `classes.yaml` is committed there as a tracked exception; task records under `.speed/features/*/tasks/` are not committed and need to be created locally — see Run below.

`speed.toml` and `.speed/classes.yaml` live on the `config/speed-diagnose` branch, not on `main` — `main` itself is untouched. Diffing straight against `main` would pull that config commit into the diagnosis too (and trip F4/F6 on the config's own rule text). Set `MAIN_BRANCH` to make `config/speed-diagnose` the diff base instead; see Run below.

## Run

Fresh checkout, reproducing the reviewed `payments` / task `1` example:

```bash
git clone https://github.com/ArulaAI/workbench.git
git clone https://github.com/ArulaAI/payments-validation-fixture.git
cd payments-validation-fixture
git checkout diagnose-demo

mkdir -p .speed/features/payments/tasks
cat > .speed/features/payments/tasks/1.json <<'EOF'
{
  "id": "1",
  "branch": "diagnose-demo",
  "agent_model": "sonnet",
  "files_touched": ["src/payments/service.ts"]
}
EOF

MAIN_BRANCH=origin/config/speed-diagnose ../workbench/speed diagnose -f payments --task 1
```

`MAIN_BRANCH=origin/config/speed-diagnose` makes that branch the diff base instead of `main`, so the diagnosis covers only the actual demo change, not the config commit that `diagnose-demo` also carries. This diffs `diagnose-demo` against `config/speed-diagnose` and writes `.speed/features/payments/risk-surface.yaml`.

## Risk surface

A trimmed example (two classes out of the eight that always appear):

```yaml
# Written by `speed diagnose`. The signals are counted. The verdicts are yours.
task: "1"
branch: "diagnose-demo"
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
  - id: F5
    failureMode: "Sycophantic self-approval"
    plausible: undecided
    costOfMissing: undecided
    findableByReading: undecided
    signals: []   # nothing countable. Not a ruling.
```

## Tests

```bash
python3 tests/test_diagnose_engine.py   # rule engine
python3 tests/test_toml_diagnose.py     # [diagnose] speed.toml section
bash tests/test_diagnose_cmd.sh         # CLI command
```

Last verified: 40 + 5 + 22 = 67 tests passing, 0 failing.
