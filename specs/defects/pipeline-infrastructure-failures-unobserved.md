# Defect: Pipeline infrastructure failures are not captured as observations

Severity: P2
Related Feature: continuous-learning
Tags: observations

> **Note:** This may be a feature rather than a defect. Pipeline infrastructure failures (git errors, stuck tasks, provider timeouts) are a different category from agent-level outcomes. They might warrant their own extraction mechanism rather than being folded into the observation system designed for learning signals. Filing here to ensure the gap is tracked either way.

## Observed Behavior

The observation infrastructure captures what agents *produced* (retries, findings, verdicts, context misses) but not cases where SPEED's own machinery failed. When the operator has to manually intervene — reset a stuck task, resolve a git merge conflict during integrate, rerun a command after a provider timeout — no observation is recorded. The system has no memory of infrastructure-level failures.

Examples of unobserved failures:

- Task stuck in `pending` status with no error, requiring manual reset
- Git merge conflict or lock file error during `speed integrate`
- Provider call timeout or malformed response from the LLM
- Agent output that fails JSON parsing (task/review/guardian produced garbage)
- Gate script crash (non-zero exit with no structured output, distinct from a gate *finding*)
- Context assembly failure (Layer 2 couldn't build the code context package)
- Turn exhaustion (agent ran out of turns before completing work)
- Feature state corruption (task JSON missing required fields, inconsistent status transitions)

## Expected Behavior

Infrastructure failures should be recorded so that recurring patterns surface. If git merge conflicts happen on every feature touching `lib/context/`, that's a learnable signal for the Architect (smaller tasks in that area, or explicit merge-order dependencies). If provider timeouts cluster around large context packages, that's a signal for context tuning.

## Impact

Without this data:
- Recurring infrastructure problems are invisible across features
- The operator's manual interventions (resets, reruns, workarounds) leave no trace
- Synthesis cannot learn from infrastructure patterns (e.g., "features touching area X have 3x the merge conflict rate")
- Time spent on manual recovery is untracked, making true cost-per-feature opaque

## Open Questions

1. Should this be an observation type (`pipeline_failure`) within the existing extraction pipeline, or a separate logging mechanism that runs orthogonally?
2. How would these be captured? Agent-level observations are extracted post-hoc from artifacts. Infrastructure failures may not produce artifacts at all — a stuck task just sits there silently.
3. Some infrastructure failures (provider timeout, parse error) are already logged to stderr. Should extraction read SPEED's own log output as an artifact source?
