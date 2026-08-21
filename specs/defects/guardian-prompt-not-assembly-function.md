# Closed: Guardian prompt not in assembly.py

**Status:** Won't fix — by design.

## Original concern

`_run_guardian` in `lib/shared.sh` builds its prompt as bash string concatenation. All other agents have Python assembly functions in `lib/context/assembly.py`. The inconsistency looked like a missing migration.

## Why it's correct

The 6 assembly functions (developer, reviewer, architect, coherence, debugger, verifier) exist to solve problems Guardian doesn't have:

| Problem | Other agents | Guardian |
|---|---|---|
| Token budget management | 60-100k budgets with per-content-type truncation (signatures-only, hunk-based, section-based) | Vision doc (1-5k tokens) + input artifact. Always small. Nothing to truncate. |
| Dynamic composition | Prompt structure varies by available data (upstream tasks? CSG? criteria results?) | Structurally identical at all three gate positions (pre-plan, post-review, post-integration). |
| Codebase coupling | Consume Layer 1/2 artifacts (code context, task DAGs, CSG, diffs, spec alignments) | Compares a document against a document. No Layer 1/2 dependency. |
| Contextual formatting | Same data presented differently per agent role | Reads vision as-is. Partial vision would defeat the purpose. |

Guardian's entire message assembly is 9 lines of bash. An `assemble_guardian()` function, bridge function, and bridge call would add ~80 lines of infrastructure with no problem to solve.

## Learnings injection

Guardian's inline Python formats learnings differently from `filter_learnings_for_task()`. This is the one real gap, but `filter_learnings_for_task()` scopes by file paths — Guardian doesn't operate on individual files. It evaluates whole specs and diffs against product vision. File-scoped filtering would be semantically wrong here.

## Conclusion

The 6 agents share an assembly architecture because they share a problem space (assembling codebase-derived context under token constraints). Guardian doesn't share that problem space. The apparent inconsistency reflects a genuine architectural difference.
