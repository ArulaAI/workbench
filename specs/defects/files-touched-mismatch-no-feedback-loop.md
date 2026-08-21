# Defect: files_touched mismatch has no correction pathway

**Severity:** P2-moderate
**Related Feature:** speed-conventions
**Reproducibility:** always
**Last Known Working:** never worked

## Observed Behavior

When an agent touches files that differ from the architect's `files_touched` prediction, the task enters a fail-retry-fail loop. The grounding gates correctly detect the mismatch (declared_files check at grounding.sh:35-42, scope check at grounding.sh:44-98), but nothing in the system can correct `files_touched` after the fact.

The human retries with `speed retry --task-id X --context "..."`. The context reaches the agent via `review_feedback`, but the agent cannot modify its own task JSON. The grounding gates don't read `review_feedback`. The same `files_touched` produces the same failure.

`files_touched` is not just a grounding gate input. Five downstream stages consume it as a source of truth:

| Stage | How it uses files_touched | Failure mode when wrong |
|---|---|---|
| Developer prompt (run.sh:843-850) | Scope constraint shown to agent | Agent misclassifies real issues as out-of-scope |
| Quality gates (gates.sh:276-287) | Subsystem detection, test scoping | Wrong tests run, failures in undeclared files hidden |
| Coherence (coherence.sh:305-333) | Dependency graph for fix tasks | Fix tasks get incomplete depends_on, run before upstream merges |
| Context assembly (assembly.py:623) | Cross-task coordination matrix | Verifier misses file conflicts between parallel tasks |
| Review (review.sh) | Not used; reads actual diff | Unaffected |

## Expected Behavior

When the grounding gates detect a `files_touched` mismatch, the system should surface the agent's actual file list alongside the architect's prediction and provide a pathway to correct the source of truth. Two distinct cases need different handling:

1. **Agent found a valid approach with different files.** The tech spec should be updated to reflect reality, and the architect should re-run for affected tasks. The corrected `files_touched` propagates to all downstream consumers.

2. **Agent went off the rails.** Current behavior (retry with human context) already handles this. No change needed.

A separate edge case: test files are expected byproducts of implementation work. No architect can reliably predict every test file path. The scope check at grounding.sh:70 counts undeclared test files toward the hard failure threshold (3+), even though test creation is a natural consequence of the work. The ownership check already distinguishes test files via `_is_test_file` (grounding.sh:430), but the undeclared count does not.

## Reproduction Steps

1. `speed plan` on a feature with a tech spec
2. Architect produces tasks with `files_touched` predictions
3. `speed run` — agent completes work but touches different files than predicted
4. Grounding gates fail on declared_files or scope (undeclared >2)
5. `speed retry --task-id X --context "the agent's file choices are valid"`
6. `speed run` — agent does the same work, hits the same gate, fails again
7. Repeat steps 5-6 indefinitely

## Additional Context

**Affected code paths:**

- `lib/grounding.sh:331-363` (`grounding_check_declared_files`) — checks `files_touched` against branch, no mechanism to update
- `lib/grounding.sh:367-449` (`grounding_check_scope`) — compares actual diff to `files_touched`, counts undeclared files
- `lib/grounding.sh:70` — undeclared count includes test files with no exemption
- `lib/cmd/retry.sh:158-172` — accumulates `review_feedback` but never modifies `files_touched`
- `lib/cmd/plan.sh:1094-1101` — where `files_touched` is originally set from architect output
- `lib/gates.sh:276-287` — subsystem detection trusts `files_touched`
- `lib/gates.sh:436-476` — test scoping trusts `files_touched`
- `lib/cmd/coherence.sh:305-333` — dependency resolution trusts `files_touched` from done tasks

**What the fix involves:**

Three changes, in order of complexity:

1. **Exempt test files from undeclared count** in `grounding_check_scope`. The `_is_test_file` helper already exists for ownership checks. Apply it to the undeclared count at line 70 as well.

2. **Capture actual files in gate_results** when grounding fails. The diff is already computed in `grounding_check_scope`. Persist the actual file list alongside the declared list in `gate_results` so `speed retry` can surface both to the human.

3. **Re-plan pathway** when the human confirms the agent's approach is valid. Update the tech spec, re-run the architect for affected tasks, and propagate corrected `files_touched` to all downstream consumers. This is the structural fix that closes the feedback loop.

The RCA at `working-docs/rca-perpetual-task-failure-loops.md` (Change 2, lines 320-367) proposes `_should_degrade` as a workaround: silently downgrade declared_files and scope gates after 2 retries. This punches a hole in grounding without correcting the data, leaving all downstream consumers with wrong `files_touched`.
