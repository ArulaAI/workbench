# Agent-Specific Synthesis

> Depends on: [Observation Infrastructure](speed-observations.md)
> Soft dependency: [Convention Discovery](speed-conventions.md) (deduplication only, not required)

## Problem

After 6 features across 2 projects, the observation pipeline has produced 403 observations: 254 reviewer findings, 52 agent concerns, 35 security findings, 19 gate failures, 16 retries, 10 context misses, 10 successes, 4 guardian verdicts, 3 context wastes. These observations are organized by feature and stored in `.speed/memory/observations/*.jsonl`. No agent reads them.

The Developer doesn't need Guardian false positives. The Guardian doesn't need Reviewer testing gaps. The Architect needs to hear that a decomposition decision caused downstream retries, but in decomposition language, not debugging language. Raw observations are the wrong shape, the wrong volume, and addressed to the wrong consumer.

Synthesis reads observations, groups by pattern, filters noise (single occurrences), weights by impact (retries outrank nits), resolves conflicts, formats per consumer, and respects token budgets. The output is 6 JSON files that agents actually read during prompt assembly.

Cross-agent feedback is the second function. A Developer retry is Developer-facing ("avoid this"), Architect-facing ("your decomposition caused this"), and Reviewer-facing ("scrutinize this task harder"). One observation can produce entries in multiple learnings files, each reframed for that agent's decision context.

## Consumers

| Agent | Learnings file | What it receives |
|-------|---------------|------------------|
| Developer | `developer-learnings.json` | Known pitfalls, testing gaps, retry patterns, integration warnings |
| Architect | `architect-learnings.json` | Task sizing calibration, decomposition precedents, downstream feedback |
| Reviewer | `reviewer-learnings.json` | Confirmed finding patterns, known false alarms, upstream awareness |
| Guardian | `guardian-learnings.json` | Scope precedents, intent patterns, scope elasticity by area |
| Coherence | `coherence-learnings.json` | Files that caused coherence issues in past features |
| Debugger | `debugger-learnings.json` | Common failure modes for files being debugged |
| Operator | `synthesis-meta.json` | Entry counts per agent, conflicts, rejections, last run timestamp |

## User Stories

| ID | Story | Acceptance Criteria | Priority |
|----|-------|---------------------|----------|
| S1 | Observations converted into agent-specific learnings | Given 20+ observations across 2+ features, synthesis produces 6 learnings files, each containing only entries relevant to that agent | Must |
| S2 | Single observations filtered as noise | Given 1 observation of type X and 3 of type Y, only Y appears in learnings (recurrence threshold: 2+ occurrences) | Must |
| S3 | Observations weighted by impact | Given 2 retries (weight 6.0 total) and 3 reviewer findings (weight 4.5 total), retry-based pattern ranks first | Must |
| S4 | Cross-agent views from reframing rules | Developer retry produces entries in developer-learnings (self-knowledge), architect-learnings (downstream feedback), and reviewer-learnings (upstream awareness) | Must |
| S5 | Stale observations excluded | Observations referencing deleted files are marked stale (0.5x weight) without modifying the observation file | Must |
| S6 | Conflicting observations resolved | Higher weight wins with a resolution note. Equal-weight conflicts logged in synthesis-conflicts.json and excluded from learnings | Must |
| S7 | Token budgets respected | Entries exceeding budget are truncated: drop lowest-weight, then merge similar, then compress evidence | Must |
| S8 | Synthesis runs before each feature | `speed plan` and `speed run` trigger synthesis (blocking) before agent prompts are assembled | Must |
| S9 | Quality bar enforced | Every entry must contain a verb, reference at least one file path, and cite at least one observation ID. Entries failing any check go to synthesis-rejects.json | Must |
| S10 | Operator can inspect synthesis output | `speed learn --synthesize` prints summary: entries per agent, rejected entries, unresolved conflicts | Should |
| S11 | Incremental synthesis | If no new observations arrived for an agent since last run, that agent's file is unchanged | Should |
| S12 | Learnings injected into agent prompts | Each assembly function reads its learnings file and positions it after constraints, before code/material | Must |
| S13 | Graceful degradation on injection | Missing, empty, or malformed learnings file: skip the section, log a warning, never crash | Must |
| S14 | Task-scoped injection filtering | Only entries referencing files in the current task's scope are injected. Zero matches: inject top 3 by weight | Must |
| S15 | Adherence tracking | After task completion, measure whether the agent followed each injected entry. Track rate per entry. Escalate entries ignored 3+ times | Deferred |

## Data Model

### Learnings entry

Each entry in a learnings file follows this schema:

```json
{
  "id": "sha256:<hex>",
  "guidance": "When modifying lib/toml.py, always update templates/speed-toml.toml in the same commit.",
  "files": ["lib/toml.py", "templates/speed-toml.toml"],
  "weight": 6.0,
  "source": "direct",
  "evidence": [
    {
      "observation_id": "sha256:abc123",
      "feature": "speed-defects",
      "summary": "Task 3 retried twice because template was stale"
    }
  ],
  "created": "2026-03-09T10:00:00Z",
  "stale": false
}
```

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | SHA-256 of `(guidance, files)` for deduplication |
| `guidance` | string | Actionable instruction. Must contain a verb and reference a file path |
| `files` | string[] | File paths this entry applies to. Used for task-scoped filtering |
| `weight` | float | Aggregated weight from source observations with modifiers applied |
| `source` | enum | `"direct"` (observation about this agent), `"cross_agent"` (reframed from another agent's observation), `"staleness_reduced"` (stale, weight halved) |
| `evidence` | object[] | Observation IDs and summaries that support this entry. Minimum 1 |
| `created` | string | ISO 8601 timestamp of when synthesis produced this entry |
| `stale` | bool | True if referenced files were deleted or rewritten >50%. Weight halved |

### Learnings file

Each agent's file is a JSON object:

```json
{
  "agent": "developer",
  "synthesized_at": "2026-03-09T10:00:00Z",
  "observation_count": 52,
  "feature_count": 4,
  "entries": [ ... ],
  "token_estimate": 420,
  "budget": 5000
}
```

### Metadata files

**synthesis-meta.json** tracks synthesis state:

```json
{
  "last_run": "2026-03-09T10:00:00Z",
  "observation_counts": {
    "developer": 52,
    "architect": 12,
    "reviewer": 28,
    "guardian": 8,
    "coherence": 5,
    "debugger": 3
  },
  "entry_counts": {
    "developer": 4,
    "architect": 2,
    "reviewer": 3,
    "guardian": 1,
    "coherence": 1,
    "debugger": 1
  },
  "rejected": 2,
  "conflicts": 0
}
```

**synthesis-conflicts.json** — array of unresolved conflicts (equal-weight opposing entries). Each has `entries`, `reason`, `resolution: null`.

**synthesis-rejects.json** — array of entries that failed the quality bar. Each has the entry plus a `rejection_reason` field.

## Observation Routing

Each observation type routes to one or more agents. This table defines which agent receives the direct entry, before cross-agent reframing applies.

| Observation type | Primary agent | Weight | Why this weight |
|---|---|---|---|
| `retry` | Developer | 3.0 | Retries are the strongest signal of something going wrong. A retry costs real time and tokens |
| `gate_failure` | Developer | 2.0 | Gate failures indicate the agent's output didn't meet quality thresholds |
| `reviewer_finding` | Reviewer | 1.5 (0.5 if dismissed) | Findings confirmed across features become calibration data. Dismissed findings become false-alarm data |
| `guardian_verdict` | Guardian | 2.0 | Verdicts calibrate scope judgment. False positives and false negatives both matter |
| `agent_concern` | Developer | 1.0 | Self-reported concerns. Lower weight because agents over-report |
| `security_finding` | Developer | 1.5 | Security patterns agents should learn to avoid |
| `verify_finding` | Architect | 2.0 | Spec drift indicates decomposition or understanding gaps |
| `coherence_issue` | Coherence | 2.0 | Cross-task integration failures |
| `context_miss` | Context | 1.5 | Files needed but not provided in the context package |
| `context_waste` | Context | 0.5 | Files provided but never referenced. Low weight because waste is cheaper than misses |
| `decomposition_miss` | Architect | 2.0 | Planned vs actual file boundaries diverged |
| `success` | (excluded) | 0.5 | Successes confirm what works but don't generate guidance entries |
| `pattern_match` | (excluded) | 2.0 | Meta-observations from Step 10. Already aggregated, not re-synthesized |

## Cross-Agent Reframing Rules

A single observation can produce entries for multiple agents. These 12 rules define how observations get reframed when routed to a non-primary agent.

| # | Origin | Also routed to | Reframed as |
|---|--------|---------------|-------------|
| 1 | Developer retry | Architect | "Downstream feedback: Developer retried because task was too broad / had a missing dependency" |
| 2 | Developer retry | Reviewer | "Upstream awareness: Developer struggled with this task, scrutinize the final attempt harder" |
| 3 | Reviewer finding (confirmed pattern) | Developer | "Known pitfall: Reviewer keeps catching this, avoid it proactively" |
| 4 | Reviewer finding (false alarm pattern) | Reviewer | "False alarm: stop flagging this, it's an accepted pattern" |
| 5 | Guardian false positive | Guardian | "Calibration: this was in-scope, accept it next time" |
| 6 | Guardian false negative | Guardian + Reviewer | "Guardian missed this. Reviewer should also watch for scope violations" |
| 7 | Context miss | Context | "Include this file when tasks touch this area" |
| 8 | Decomposition miss | Architect | "Task boundaries were wrong. Here's what the Developer actually touched" |
| 9 | Verify finding (spec drift) | Architect | "Spec interpretation gap: the plan didn't account for this requirement" |
| 10 | Security finding (recurring) | Developer | "Security pattern: avoid this in future tasks touching these files" |
| 11 | Gate failure (recurring) | Architect | "Downstream impact: tasks in this area consistently fail gates. Consider smaller scope" |
| 12 | Agent concern (recurring) | Developer | "Self-reported struggle: agents consistently flag difficulty in this area" |

Rules 1-6 require the human-corrections system to fully function (distinguishing confirmed findings from false alarms, human overrides from automated verdicts). Until human-corrections is built, rules 3-6 operate on observation recurrence alone: a finding appearing 2+ times is treated as confirmed.

## Synthesis Pipeline

```
Read observations
    ↓
Group by (type, category, files)
    ↓
Filter: drop groups with < 2 occurrences
    ↓
Weight: sum base weights, apply modifiers
    ↓
Staleness: check referenced files against codebase
    ↓
Conflict resolution: higher weight wins, equal → exclude
    ↓
Format: template-based guidance text
    ↓
Cross-agent: apply 12 reframing rules
    ↓
Route to agent files
    ↓
Token budget: truncate per agent
    ↓
Quality bar: reject entries missing verb/file/evidence
    ↓
Write learnings files + meta + rejects + conflicts
```

### Grouping

Observations are grouped by `(observation_type, category, files_key)` where `files_key` is the sorted tuple of referenced files. Groups with fewer than 2 occurrences are dropped as noise.

For groups that don't reach the threshold on the full key, a fallback pass groups by `(observation_type, category)` only (same two-pass logic as Step 10 pattern detection). A retry happening on different files across 2 features is still a retry pattern.

### Weight modifiers

Base weights come from the observation routing table above. Modifiers adjust based on recurrence and recency:

| Modifier | Multiplier | Rationale |
|----------|-----------|-----------|
| Recency: observation from last 3 features | 1.5x | Recent observations are more relevant to the current codebase state |
| Consistency: pattern appears in every feature | 1.3x | Patterns that never go away deserve more attention |
| High recurrence: 5+ occurrences | 1.2x | Volume reinforces signal |

Final weight = sum of (base_weight x applicable modifiers) across all observations in the group.

### Staleness detection

Before weighting, each observation's referenced files are checked against the working tree:

- **File deleted**: observation marked `stale`, weight multiplied by 0.5x
- **File rewritten >50%** (by line count vs. last observation timestamp): marked `possibly_stale`, weight multiplied by 0.5x
- **File renamed**: path updated in the observation's file references (detected via git log)
- **File unchanged**: no modification

Stale observations are never deleted from the JSONL files. Staleness is a synthesis-time flag only.

### Conflict resolution

Two entries conflict when they give opposing guidance about the same files. Detection: entries sharing 50%+ of their `files` list with opposing verbs ("include" vs "exclude", "add" vs "remove", "use" vs "avoid").

Resolution order:
1. **Weight**: higher weight wins
2. **Recency**: if weights are within 10%, more recent wins
3. **Unresolvable**: logged in `synthesis-conflicts.json`, excluded from learnings

### Formatting

Entries are formatted using templates, not LLM calls. Each observation type has a template:

```
retry:       "When modifying {files}, {what_happened}. This caused retries in {n} features."
reviewer:    "Reviewer pattern in {files}: {category}. Seen in {n} features."
gate_failure: "Tasks touching {files} consistently fail {gate}. {resolution_hint}."
context_miss: "Include {missed_file} when tasks modify {related_files}."
...
```

Templates produce deterministic, testable output. No LLM dependency in the synthesis pipeline.

### Token budgets

Each agent's learnings file has a maximum token budget. Learnings should be roughly 10% of the agent's typical prompt size to inform without crowding out code context.

| Agent | Budget | Rationale |
|-------|--------|-----------|
| Developer | 3,000 tokens | Typical developer prompt: ~30K tokens. 10% = 3K |
| Architect | 3,000 tokens | Typical architect prompt: ~30K tokens |
| Reviewer | 2,000 tokens | Typical review prompt: ~20K tokens |
| Guardian | 1,000 tokens | Guardian prompts are small (shell-based, ~10K) |
| Coherence | 1,000 tokens | Coherence prompts are focused on diffs |
| Debugger | 1,000 tokens | Debugger prompts are focused on failure context |

When entries exceed budget, truncation applies in order:
1. Drop lowest-weight entries
2. Merge entries sharing 50%+ files into a single entry
3. Compress evidence (keep observation IDs, drop summaries)
4. If still over budget, drop entire categories starting from lowest total weight

### Quality bar

Every entry must pass all four checks:

| Check | Rule | Example pass | Example fail |
|-------|------|-------------|-------------|
| Actionable | Contains a verb (update, include, avoid, check, add, remove, test, verify) | "Update templates/speed-toml.toml when modifying lib/toml.py" | "lib/toml.py is important" |
| Specific | References at least one file path | "Avoid timeout in test_score_service.py" | "Be careful with tests" |
| Evidenced | Cites at least one observation ID in the `evidence` array | evidence: [{observation_id: "sha256:abc"}] | evidence: [] |
| Non-redundant | No existing entry in the same file covers the same files with the same verb | (first entry about lib/toml.py) | (duplicate of existing entry) |

Entries failing any check go to `synthesis-rejects.json` with a `rejection_reason` field.

## Injection

### Positions per agent

Injection positions are based on the actual assembly functions in `lib/context/assembly.py` and `lib/shared.sh`.

| Agent | Function | Section name | Position |
|-------|----------|-------------|----------|
| Developer | `assemble_developer()` line 637 | "## Learned Patterns" | After `### Cross-Cutting Constraints`, before code context sections |
| Reviewer | `assemble_reviewer()` line 855 | "## Review Calibration" | After `### Assumptions to Verify`, before `### Instructions` |
| Architect | `assemble_architect()` line 280 | "## Project History" | After codebase context, before instructions |
| Guardian | `_run_guardian()` in shared.sh | "Scope Calibration" | Appended to the guardian prompt input |
| Coherence | `assemble_coherence()` line 1012 | "## Integration History" | Before `### Instructions` |
| Debugger | `assemble_debugger()` line 1144 | "## Known Failure Patterns" | Before diagnostic instructions |

### Task-scoped filtering

For task-scoped agents (Developer, Reviewer, Debugger), only entries whose `files` array overlaps with the current task's declared files are injected. Overlap is checked at the directory level too: an entry for `lib/toml.py` matches a task touching `lib/config.py` (same parent directory).

If zero entries match after filtering, inject the top 3 entries by weight regardless of scope. Zero learnings is worse than loosely-scoped learnings.

For feature-scoped agents (Architect, Guardian, Coherence), all entries are injected (no task-scoped filtering).

### Graceful degradation

| Failure mode | Behavior |
|---|---|
| Learnings file missing | Skip section silently. Agent runs without learnings (same as run 1) |
| Learnings file empty (`entries: []`) | Skip section silently |
| Malformed JSON | Log warning, skip section. Never crash |
| Synthesis hasn't run yet | No files exist, skip silently |

## User Flows

### First synthesis (real data)

1. Observations from 6 features exist: 403 total across `.speed/memory/observations/`
2. Operator runs `speed learn --synthesize`
3. Synthesis reads 403 observations. By type: 254 reviewer_finding, 52 agent_concern, 35 security_finding, 19 gate_failure, 16 retry, 10 context_miss, 10 success (excluded), 4 guardian_verdict, 3 context_waste
4. Grouping: 16 retries across 4 features form 3 patterns (by file area). 254 reviewer findings form ~20 groups by category and files
5. Recurrence filter: groups with < 2 occurrences dropped. ~15 patterns survive
6. Staleness check: all referenced files still exist. No stale entries
7. Cross-agent reframing: retry patterns also produce Architect downstream feedback and Reviewer upstream awareness entries
8. Routing: Developer gets retry self-knowledge + security patterns + confirmed reviewer pitfalls. Architect gets decomposition feedback + retry downstream. Reviewer gets finding calibration + upstream awareness. Guardian gets verdict calibration
9. Formatting: template-based, ~150 tokens per entry
10. Token budget: Developer at ~600/3000, Reviewer at ~450/2000. Well within limits
11. Quality bar: 2 entries rejected (missing file references). Written to synthesis-rejects.json
12. Output: 6 learnings files written to `.speed/memory/learnings/`
13. Summary: "Synthesis complete. 13 entries across 6 agent files. 0 conflicts. 2 rejected."

### Graceful degradation

1. `developer-learnings.json` is corrupted (invalid JSON)
2. `assemble_developer()` attempts to parse, catches the error
3. Warning logged: "Failed to parse developer-learnings.json, skipping Learned Patterns section"
4. Developer prompt assembled without learnings. Pipeline continues normally

## Success Criteria

- [ ] Synthesis reads `.speed/memory/observations/*.jsonl` and produces 6 learnings files in `.speed/memory/learnings/`
- [ ] Recurrence filter: groups with < 2 occurrences excluded
- [ ] Weighting: base weights from observation routing table, modifiers for recency/consistency/volume
- [ ] Cross-agent synthesis: 12 reframing rules applied, entries routed to non-primary agents
- [ ] Staleness: deleted files = stale (0.5x), rewritten >50% = possibly_stale (0.5x)
- [ ] Conflicts: higher weight wins. Equal weight = excluded, logged in synthesis-conflicts.json
- [ ] Token budgets: Developer 3K, Architect 3K, Reviewer 2K, Guardian/Coherence/Debugger 1K each
- [ ] Truncation: drop lowest → merge similar → compress evidence
- [ ] Quality bar: verb + file path + evidence. Failures go to synthesis-rejects.json
- [ ] Formatting: template-based, no LLM calls
- [ ] Incremental: skip agents with no new observations since last run
- [ ] State tracked in synthesis-meta.json
- [ ] Injection into 6 assembly functions at specified positions
- [ ] Task-scoped filtering for Developer/Reviewer/Debugger
- [ ] Scoping fallback: zero matches → top 3 by weight
- [ ] Graceful degradation: missing/empty/malformed → skip, warn, never crash
- [ ] `speed learn --synthesize` prints summary
- [ ] Synthesis triggers: blocking before `speed plan`/`speed run`, on-demand via `speed learn --synthesize`

## Scope

### In Scope

- Synthesis pipeline: read → group → filter → weight → staleness → conflict → format → cross-agent → budget → quality → write
- Observation routing table and base weights (already defined in extract.py `_WEIGHTS`)
- 12 cross-agent reframing rules
- Template-based formatting (no LLM dependency)
- Staleness detection against current working tree
- Conflict resolution (weight-based, with fallback to exclusion)
- Token budget enforcement with 3-level truncation
- Quality bar (4 checks: verb, file, evidence, non-redundant)
- 6 agent-specific learnings files + 3 metadata files
- Injection into assembly functions with task-scoped filtering
- Graceful degradation for all failure modes
- `speed learn --synthesize` command
- Incremental synthesis with state tracking

### Out of Scope

- **Observation extraction** (speed-observations). Synthesis consumes observations, doesn't produce them.
- **Convention discovery** (speed-conventions). If conventions.json exists, synthesis deduplicates against it. If not, deduplication is skipped.
- **Human correction capture** (speed-human-corrections). When human_override observations exist, they flow through synthesis like any other observation type. Until that system is built, rules 3-6 of cross-agent reframing operate on recurrence alone.
- **Context tuning** (speed-context-tuning). `context-learnings.json` is produced by synthesis. Layer 2 integration to consume it is context-tuning's scope.
- **LLM-based formatting**. Templates handle formatting. If templates prove insufficient, LLM formatting can be added later without changing the pipeline structure.
- **Adherence tracking** (S15). Deferred until injection is working and producing data to measure against.

## Dependencies

| Dependency | Status | Impact if missing |
|---|---|---|
| Observation Infrastructure (speed-observations) | Built | No observations to synthesize. Synthesis produces empty files |
| Assembly functions (`lib/context/assembly.py`) | Built | Injection positions exist. Functions need a new `learnings` parameter |
| Guardian prompt (`lib/shared.sh`) | Built | Shell function needs learnings content appended |
| Convention Discovery (speed-conventions) | Not built | Deduplication step skipped. No functional impact |
| Human Corrections (speed-human-corrections) | Not built | Cross-agent rules 3-6 use recurrence instead of human confirmation |

## Security & Controls

**Read-only observation access.** Synthesis reads observation files but never modifies them. Observations are append-only. Staleness is a synthesis-time flag, not written back to JSONL.

**No source code in learnings.** Entries reference file paths, not code content. Agent prompts include actual code via Layer 2 context; learnings tell the agent what to look for, not what the code says.

**No LLM calls.** Template-based formatting eliminates the risk of LLM hallucination in learnings content. Every entry is deterministically traceable to source observations.

**Graceful degradation as security boundary.** Malformed learnings must never reach agent prompts. A corrupted file that slips through could mislead an agent into writing wrong code. The parse-error-then-skip path is the defense.

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Wrong guidance from correct observations | High | Quality bar rejects vague entries. Recurrence filter requires 2+. Evidence citations enable tracing |
| Weighting model over-values rare events | Medium | Weights match extract.py _WEIGHTS (already validated against real data). Modifiers are multiplicative and capped |
| Cross-agent reframing creates noise | Medium | Cross-agent entries compete for the same token budget as direct entries. Lower-impact cross-agent entries are truncated first |
| Staleness detection too aggressive | Medium | Only triggers on deletion or >50% rewrite. Stale entries are halved, not removed. Renamed files get path updates |
| Template formatting too rigid | Low | Templates cover the 12 observation types with known detail schemas. If a new type needs richer formatting, add a template |

## Decisions

Resolved from the original open questions.

| ID | Decision | Rationale |
|----|----------|-----------|
| D1 | Synthesis runs synchronously (blocking) before `speed plan` and `speed run` | Synthesis is fast: reads JSON, applies templates, writes JSON. No LLM calls. Sub-second for 400 observations. Async adds complexity for no latency benefit |
| D2 | Recurrence threshold is 2 occurrences | With 6 features and 403 observations, patterns at 2+ are reliable. A threshold of 3 would miss legitimate patterns in early projects. Step 10 pattern detection uses min_features=3 across features; synthesis threshold of 2 within observations is a different granularity |
| D3 | Adherence tracking is deferred | Build injection first, measure effectiveness manually, then automate tracking once we know what to measure |
