# Tech Spec: Agent-Specific Synthesis

> Product spec: [speed-synthesis.md](../product/speed-synthesis.md)
> Depends on: Observation Infrastructure ([speed-observations.md](speed-observations.md)), assembly functions (`lib/context/assembly.py`), Guardian prompt (`lib/shared.sh`)

## Overview

Synthesis reads observation JSONL files, routes observations to agent-specific files, deduplicates, and truncates to budget. Observations pass through with their original detail dicts intact — no lossy reformatting. No LLM calls. The entire pipeline is deterministic and testable.

```
.speed/memory/observations/*.jsonl
         ↓
   synthesize()           ← lib/learn/synthesize.py
         ↓
.speed/memory/learnings/
   ├── developer-learnings.json
   ├── architect-learnings.json
   ├── reviewer-learnings.json
   ├── guardian-learnings.json
   ├── coherence-learnings.json
   ├── debugger-learnings.json
   ├── synthesis-meta.json
   ├── synthesis-rejects.json
   └── synthesis-conflicts.json
         ↓
   assemble_*()           ← lib/context/assembly.py (reads learnings)
         ↓
   agent prompts with "Learned Patterns" / "Review Calibration" / etc.
```

## Input Contract

Synthesis reads from `.speed/memory/observations/*.jsonl`. Each line is a JSON object matching the `Observation` dataclass from `lib/learn/extract.py`:

```python
@dataclass
class Observation:
    id: str                  # "sha256:<hex>"
    feature: str             # feature name
    stage: str               # pipeline stage
    task_id: str             # task ID or "*"
    timestamp: str           # ISO 8601
    observation_type: str    # one of 16 types
    detail: dict             # type-specific fields
    weight: float            # base weight from _WEIGHTS
```

### Detail schemas per observation type

The full detail dict passes through synthesis unchanged. These schemas document what fields each type carries.

| Type | Detail fields |
|------|--------------|
| `retry` | `retry_count`, `what_happened`, `resolution`, `files_involved`, `duration_seconds` |
| `reviewer_finding` | `category`, `finding`, `confirmed`, `led_to_retry`, `file`, `line` |
| `gate_failure` | (varies by gate type) |
| `guardian_verdict` | `verdict`, `summary`, `flags[]` |
| `agent_concern` | `concern`, `agent_model`, `task_status`, `predictive` |
| `security_finding` | `finding_id`, `severity`, `category`, `title`, `file`, `recommendation` |
| `verify_finding` | `finding_type`, `requirement`, `status`, `analysis` |
| `coherence_issue` | `issue_type`, `task_a`, `task_b`, `description`, `severity` |
| `context_miss` | `file`, `task_files_declared` |
| `context_waste` | `provided_count`, `used_count`, `waste_ratio` |
| `decomposition_miss` | `issue`, `planned_files`, `actual_files`, `analysis` |
| `success` | `files_planned`, `files_actual`, `guardian`, `duration_seconds` (excluded from synthesis) |
| `pattern_match` | `pattern`, `occurrences`, `frequency`, `severity` (excluded from synthesis) |

## Output Contract

### Learnings entry

```json
{
  "id": "sha256:<hex>",
  "observation_type": "retry",
  "detail": {
    "retry_count": 2,
    "what_happened": "template was stale after toml schema change",
    "resolution": "regenerated template from schema",
    "files_involved": ["lib/toml.py", "templates/speed-toml.toml"],
    "duration_seconds": 340
  },
  "files": ["lib/toml.py", "templates/speed-toml.toml"],
  "weight": 9.0,
  "source": "direct",
  "evidence": [
    {
      "observation_id": "sha256:abc123",
      "feature": "speed-defects"
    }
  ],
  "created": "2026-03-09T10:00:00Z",
  "stale": false
}
```

The `id` is the original observation ID for direct entries, or `sha256(observation_id + target_agent)` for cross-agent entries. Deterministic: same input always produces the same ID.

### Learnings file

```json
{
  "agent": "developer",
  "synthesized_at": "2026-03-09T10:00:00Z",
  "observation_count": 52,
  "feature_count": 4,
  "entries": [ ... ],
  "token_estimate": 420,
  "budget": 3000
}
```

Written to `.speed/memory/learnings/{agent}-learnings.json`.

### Metadata files

**synthesis-meta.json:**

```json
{
  "last_run": "2026-03-09T10:00:00Z",
  "features_processed": ["speed-defects", "speed-security", "f9-profile-completeness", "f10-rich-feed"],
  "observation_hash": "sha256:<hex of sorted observation IDs>",
  "entry_counts": {
    "developer": 4, "architect": 2, "reviewer": 3,
    "guardian": 1, "coherence": 1, "debugger": 1
  },
  "rejected": 2,
  "conflicts": 0
}
```

`observation_hash` enables incremental synthesis: if the hash hasn't changed since last run, skip synthesis entirely.

**synthesis-rejects.json:** Array of entries that failed the quality bar. Each entry includes a `rejection_reason` field.

**synthesis-conflicts.json:** Array of unresolved conflicts. Each has `entry_a`, `entry_b`, `reason`, `resolution: null`.

## Pipeline Implementation

### Module: `lib/learn/synthesize.py`

```python
def synthesize(memory_dir: Path) -> SynthesisResult:
    """Run the full synthesis pipeline.

    Reads observations from memory_dir/observations/*.jsonl,
    produces learnings in memory_dir/learnings/*.json.
    """
```

### Step 1: Read observations

```python
def _read_all_observations(obs_dir: Path) -> list[Observation]:
    """Read all observations from all feature JSONL files."""
```

Load every `.jsonl` file in `obs_dir`. Skip malformed lines (log warning). Return flat list sorted by timestamp. Exclude `success` and `pattern_match` types (these don't generate learnings).

### Step 2: Route to agents

Each observation has a primary agent. The routing is a direct lookup.

```python
_AGENT_ROUTING: dict[str, str] = {
    "retry": "developer",
    "gate_failure": "developer",
    "agent_concern": "developer",
    "security_finding": "developer",
    "reviewer_finding": "reviewer",
    "guardian_verdict": "guardian",
    "verify_finding": "architect",
    "decomposition_miss": "architect",
    "coherence_issue": "coherence",
    "context_miss": "developer",
    "context_waste": "developer",
}
```

### Step 3: Build entries

Each observation becomes a learnings entry directly. The observation's `detail` dict passes through unchanged — no template formatting, no lossy text generation. The entry's `files` list (for task-scoped injection) is extracted from the observation's detail: `files_involved`, `file`, `planned_files`, `actual_files` — whichever fields contain file paths. The entry's `weight` starts as the observation's base weight from `_WEIGHTS`.

### Step 4: Cross-agent reframing

Some observations also produce entries for secondary agents. These carry the same `detail` dict but are tagged with a `reframing_context` that tells the receiving agent why it's seeing this observation.

| # | Origin type | Condition | Target agent | `reframing_context` |
|---|------------|-----------|-------------|---------------------|
| 1 | `retry` | | architect | `downstream_feedback` |
| 2 | `retry` | | reviewer | `upstream_awareness` |
| 3 | `reviewer_finding` | confirmed | developer | `known_pitfall` |
| 4 | `reviewer_finding` | single occurrence | reviewer | `possible_false_alarm` |
| 5 | `guardian_verdict` | false positive | guardian | `calibration` |
| 6 | `guardian_verdict` | false negative | reviewer | `missed_scope_issue` |
| 7 | `context_miss` | | developer | `context_gap` |
| 8 | `decomposition_miss` | | architect | `boundary_error` |
| 9 | `verify_finding` | spec_drift | architect | `spec_interpretation_gap` |
| 10 | `security_finding` | | developer | `security_pattern` |
| 11 | `gate_failure` | | architect | `gate_failure_signal` |
| 12 | `agent_concern` | | developer | `agent_difficulty` |

Cross-agent entries use `source: "cross_agent"` and carry 0.7x the original weight (secondary signal). The `reframing_context` is a short tag the receiving agent uses to interpret the observation from its perspective — the LLM handles the reframing, not a template.

### Step 5: Apply weight modifiers

Starting from each entry's base weight:

| Modifier | Condition | Multiplier |
|----------|-----------|------------|
| Recency | Observation from last 3 features | 1.5x |
| Cross-agent | Entry is a reframed cross-agent entry | 0.7x |

Weight modifiers are simple. No consistency or volume bonuses — the budget step naturally promotes types with higher base weights and recency. Adding more modifier knobs is premature complexity.

### Step 6: Staleness detection

For each entry, check whether its referenced files still exist in the working tree.

- **File deleted**: mark entry `stale = true`, weight × 0.5
- **File exists**: no change

No git history checks for renames or rewrite percentage in v1. Deleted-file detection covers the critical case (entries referencing files that no longer exist). Rewrite detection can be added later if stale entries prove to be a problem.

Staleness is never written back to observation JSONL. Synthesis-time only.

### Step 7: Deduplicate

Multiple observations can produce entries with nearly identical content (e.g., 14 `reviewer_finding/unclassified` observations about different lines in the same file).

Deduplication: within each agent's entry list, if two entries share the same `observation_type` and have >80% overlap in their `files` list, merge them:
- Keep the higher weight
- Combine `evidence` arrays
- Union `files` lists
- Keep the detail dict from the higher-weight entry

No grouping step. Each observation produces an entry independently. Deduplication merges entries that are structurally about the same files and type. Distinct files or distinct types stay separate, even if they share a category.

### Step 8: Conflict detection and resolution

Two entries conflict when they share 50%+ of their `files` list and have contradictory observation types. Contradiction pairs: (`context_miss`, `context_waste`) on the same file (one says include it, the other says it's unused).

Resolution:
1. Higher weight wins. Losing entry goes to `synthesis-rejects.json` with reason "conflict: outweighed"
2. If weights within 10%: logged in `synthesis-conflicts.json`, both excluded from learnings

### Step 9: Quality bar

Every entry must pass three checks:

| Check | Implementation | Rejection reason |
|-------|---------------|-----------------|
| Specific | `any("/" in f for f in files)` (at least one path with a directory separator) | "not specific: no file path" |
| Evidenced | `len(evidence) >= 1` | "not evidenced: no supporting observations" |
| Non-redundant | No existing entry in the same agent file shares `observation_type` + >80% file overlap (after dedup) | "redundant: similar to entry {id}" |

The "actionable verb" check from the template-based design is gone. Observations are produced by our own extraction pipeline and already carry high-signal content. The quality bar guards against structural issues (missing files, missing evidence, duplicates), not content quality.

Failures go to `synthesis-rejects.json`.

### Step 10: Token budget enforcement

```python
_TOKEN_BUDGETS: dict[str, int] = {
    "developer": 3000,
    "architect": 3000,
    "reviewer": 2000,
    "guardian": 1000,
    "coherence": 1000,
    "debugger": 1000,
}
```

Token estimation: `len(json.dumps(detail)) // 4` (rough approximation, 4 chars per token).

If an agent's entries exceed budget, truncate by dropping lowest-weight entries until the total fits. Weight already encodes importance (retries at 3.0 survive over agent concerns at 1.0) and recency (1.5x modifier).

No merging or evidence compression during truncation. Dropped entries are clean drops. If the budget is tight enough to need merging, the budget number should be increased, not the truncation logic.

### Step 11: Write output

Write each agent's learnings file to `.speed/memory/learnings/{agent}-learnings.json`. Write `synthesis-meta.json`, `synthesis-rejects.json`, `synthesis-conflicts.json`.

### Incremental synthesis

Before running the pipeline, check `synthesis-meta.json`:
1. Compute `observation_hash` from current observations (SHA-256 of sorted observation IDs)
2. If hash matches `synthesis-meta.json.observation_hash`, skip synthesis entirely
3. If hash differs, run full pipeline

Per-agent incrementality is not implemented in v1. If any observations changed, all agents are regenerated. The pipeline is fast enough (sub-second for 400 observations) that per-agent skipping adds complexity for negligible benefit.

### Pipeline summary

```
Read observations (exclude success, pattern_match)
    ↓
Route each observation to primary agent
    ↓
Build entries (detail dict passes through, extract files list)
    ↓
Cross-agent reframing (secondary entries with reframing_context)
    ↓
Weight modifiers (recency, cross-agent discount)
    ↓
Staleness (check files exist)
    ↓
Deduplicate (same type + >80% file overlap → merge)
    ↓
Conflict resolution (opposing entries on same files)
    ↓
Quality bar (file path + evidence + non-redundant)
    ↓
Token budget (drop lowest-weight until fits)
    ↓
Write learnings files + meta + rejects + conflicts
```

## Injection

Learnings reach agent prompts through the existing context bridge pattern: shell callers prepare parameters, pass them to Python assembly functions via `context_bridge.sh`. Injection adds one parameter to each bridge function.

```
speed plan / speed run / speed review / ...
    ↓
lib/cmd/*.sh  (shell caller)
    ↓
lib/context_bridge.sh  (bridge function)
    ↓ reads .speed/memory/learnings/{agent}-learnings.json
    ↓ calls filter_learnings_for_task()
    ↓ passes result as learnings="" parameter
lib/context/assembly.py  (assembly function)
    ↓ inserts learnings string into prompt
agent prompt
```

### `filter_learnings_for_task`

Lives in `lib/learn/synthesize.py` (co-located with the learnings data model).

```python
def filter_learnings_for_task(
    learnings_path: Path,
    task_files: list[str],
) -> str:
    """Read a learnings file, filter entries by task scope, format as markdown."""
```

1. Read the learnings JSON. Return `""` on any failure (missing file, malformed JSON, missing `entries` key).
2. For each entry, check file overlap with `task_files`:
   - Direct match: entry `files` contains a file in `task_files`
   - Directory match: entry file's parent dir matches a task file's parent dir
3. If zero matches, fall back to top 3 entries by weight.
4. Format matched entries as markdown, one bullet per entry:

```markdown
- **retry** on `lib/toml.py`, `templates/speed-toml.toml`: what_happened="template was stale", resolution="regenerated template" (from speed-defects)
- **reviewer_finding** on `lib/toml.py`: category="unclassified", finding="empty diff" [cross-agent: known_pitfall] (from f9-profile, speed-defects)
```

Cross-agent entries include the `reframing_context` tag in brackets so the agent knows why it's seeing the observation.

### Assembly function changes

Each function gains one optional `learnings: str = ""` parameter at the end, following the existing pattern where all context arrives as strings.

| Function | New parameter | Section header | Insert after |
|----------|--------------|----------------|-------------|
| `assemble_developer` | `learnings: str = ""` | `### Learned Patterns` | `### Cross-Cutting Constraints` |
| `assemble_reviewer` | `learnings: str = ""` | `### Review Calibration` | `### Assumptions to Verify` |
| `assemble_architect` | `learnings: str = ""` | `### Project History` | `### Domain Architecture` |
| `assemble_coherence` | `learnings: str = ""` | `### Integration History` | `#### High-Impact Modifications` |
| `assemble_debugger` | `learnings: str = ""` | `### Known Failure Patterns` | `### Context Budget Analysis` |

Each function inserts the learnings section and subtracts its token cost from the context budget so code context and other sections keep their full allocation:

```python
if learnings:
    sections.append(f"### Learned Patterns\n\n{learnings}\n")
    total_budget -= estimate_tokens_from_text(learnings)
```

(Section header varies per function as shown in table above.)

Current context budgets and learnings impact:

| Agent | Context budget | Learnings budget | Learnings % |
|-------|---------------|-----------------|-------------|
| Developer | 80,000 | 3,000 | 3.75% |
| Reviewer | 60,000 | 2,000 | 3.3% |
| Architect | 60,000 | 3,000 | 5.0% |
| Coherence | 100,000 | 1,000 | 1.0% |
| Debugger | 50,000 | 1,000 | 2.0% |

Learnings get a guaranteed slot. The remaining budget goes to code context, diffs, and other sections. If the prompt is tight, `_truncate` cuts from the end as usual, but never touches learnings.

### Bridge function changes

Each `context_assemble_*` function in `lib/context_bridge.sh` gains the learnings preparation step. Example for developer:

```python
# In context_assemble_developer's Python block:
from lib.learn.synthesize import filter_learnings_for_task
from pathlib import Path

memory_dir = Path(project_root) / ".speed" / "memory"
learnings_path = memory_dir / "learnings" / "developer-learnings.json"
task_files = task.get("files_to_modify", []) + task.get("files_to_create", [])
learnings = filter_learnings_for_task(learnings_path, task_files)

result = assemble_developer(
    ...,
    learnings=learnings,
)
```

The same pattern applies to all bridge functions. The agent name and task files source vary:

| Bridge function | Learnings file | Task files source |
|----------------|---------------|-------------------|
| `context_assemble_developer` | `developer-learnings.json` | `task["files_to_modify"] + task["files_to_create"]` |
| `context_assemble_reviewer` | `reviewer-learnings.json` | `task["files_to_modify"] + task["files_to_create"]` |
| `context_assemble_architect` | `architect-learnings.json` | All files from project map (no task-scoping) |
| `context_assemble_coherence` | `coherence-learnings.json` | All files across completed tasks |
| `context_assemble_debugger` | `debugger-learnings.json` | `task["files_to_modify"]` |

Architect and coherence don't filter by task because they operate at the feature level. They receive all entries within budget.

### Guardian injection

Guardian is shell-only (`_run_guardian` in `lib/shared.sh`). Injection happens by reading the learnings file in bash and appending to the prompt string:

```bash
# In _run_guardian, before building guardian_message:
local learnings_file="${PROJECT_ROOT}/.speed/memory/learnings/guardian-learnings.json"
local scope_calibration=""
if [[ -f "$learnings_file" ]]; then
    scope_calibration=$($(_context_python) -c "
import json, sys
data = json.load(open('$learnings_file'))
for e in data.get('entries', []):
    t = e['observation_type']
    ctx = e.get('reframing_context', '')
    detail = e.get('detail', {})
    summary = detail.get('summary', detail.get('description', ''))
    tag = f' [{ctx}]' if ctx else ''
    print(f'- **{t}**{tag}: {summary}')
" 2>/dev/null || true)
fi
```

Then in the prompt between `### Product Vision` and `### Input to Evaluate`:

```bash
$([ -n "$scope_calibration" ] && echo "
### Scope Calibration
${scope_calibration}
")
```

### Graceful degradation

Every learnings read path returns empty string on failure. No exception propagation. No crash path.

- Missing learnings file → `""` → section skipped
- Malformed JSON → `""` → section skipped
- Missing `entries` key → `""` → section skipped
- Empty entries after filtering → `""` → section skipped

## CLI Integration

### `speed learn --synthesize`

Added to `lib/cmd/learn.sh`. Calls `synthesize()` via the learn bridge (`lib/learn_bridge.sh`).

```bash
learn_synthesize() {
    .venv/bin/python -c "
import sys; sys.path.insert(0, 'lib')
from learn.synthesize import synthesize
from pathlib import Path
result = synthesize(Path('.speed/memory'))
print(result.summary())
"
}
```

### Trigger points

| Trigger | Location | Blocking? |
|---------|----------|-----------|
| `speed learn --synthesize` | `lib/cmd/learn.sh` | Yes (direct invocation) |
| Before `speed plan` | `lib/cmd/plan.sh` | Yes (synthesis must complete before Architect prompt assembly) |
| Before `speed run` | `lib/cmd/run.sh` | Yes (synthesis must complete before Developer prompt assembly) |

The trigger checks `synthesis-meta.json.observation_hash` first. If unchanged, synthesis is skipped (sub-millisecond).

## Data Model

### SynthesisResult

```python
@dataclass
class SynthesisResult:
    entries_by_agent: dict[str, list[LearningsEntry]]
    rejects: list[LearningsEntry]
    conflicts: list[Conflict]
    meta: SynthesisMeta

    def summary(self) -> str:
        """Format summary for CLI output."""
```

### LearningsEntry

```python
@dataclass
class LearningsEntry:
    id: str                     # observation ID (direct) or sha256(obs_id + agent) (cross-agent)
    observation_type: str       # original observation type
    detail: dict                # original observation detail, unmodified
    files: list[str]            # file paths for scoping (extracted from detail)
    weight: float               # final weight after modifiers
    source: str                 # "direct" | "cross_agent"
    reframing_context: str      # "" for direct, tag like "downstream_feedback" for cross-agent
    evidence: list[Evidence]    # supporting observations
    created: str                # ISO 8601
    stale: bool                 # staleness flag
```

### Evidence

```python
@dataclass
class Evidence:
    observation_id: str
    feature: str
```

### Conflict

```python
@dataclass
class Conflict:
    entry_a: LearningsEntry
    entry_b: LearningsEntry
    reason: str                 # "contradictory types on shared files"
    resolution: str | None      # None = unresolved
```

### SynthesisMeta

```python
@dataclass
class SynthesisMeta:
    last_run: str
    features_processed: list[str]
    observation_hash: str
    entry_counts: dict[str, int]
    rejected: int
    conflicts: int
```

## File Impact

| File | Change |
|------|--------|
| `lib/learn/synthesize.py` | **New.** Core synthesis pipeline (~400 lines estimated) |
| `lib/learn_bridge.sh` | Add `learn_synthesize()` bridge function |
| `lib/cmd/learn.sh` | Add `--synthesize` flag handling |
| `lib/cmd/plan.sh` | Add synthesis trigger before Architect assembly |
| `lib/cmd/run.sh` | Add synthesis trigger before Developer assembly |
| `lib/context/assembly.py` | Add `learnings` parameter to 5 assembly functions. ~5 lines each |
| `lib/shared.sh` | Add learnings content to `_run_guardian` prompt |
| `tests/test_synthesize.py` | **New.** Unit tests for synthesis pipeline |
| `tests/test_injection.py` | **New.** Unit tests for injection into assembly functions |

## Testing Plan

### Unit tests (`tests/test_synthesize.py`)

**Reading:**
- All `.jsonl` files loaded
- Malformed lines skipped with warning
- `success` and `pattern_match` excluded

**Routing:**
- Each observation type routes to correct primary agent
- Cross-agent reframing produces entries in secondary agents
- Cross-agent entries have `source: "cross_agent"` and `reframing_context`

**Entry building:**
- Detail dict passes through unchanged
- Files extracted correctly from `files_involved`, `file`, `planned_files`, `actual_files`
- Weight starts as base weight from `_WEIGHTS`

**Weighting:**
- Recency modifier applied to observations from last 3 features
- Cross-agent discount applied (0.7x)
- Modifiers stack multiplicatively

**Staleness:**
- Deleted file → stale, 0.5x weight
- Existing file → not stale, 1.0x
- Missing files in observation detail → not stale (nothing to check)

**Deduplication:**
- Same type + >80% file overlap → merged
- Different types on same files → kept separate
- Merged entry keeps higher weight, unions files, combines evidence

**Conflicts:**
- Contradictory types on shared files detected (`context_miss` vs `context_waste`)
- Higher weight wins
- Equal weight → both excluded, logged

**Token budget:**
- Entries within budget → all included
- Entries over budget → lowest-weight dropped first

**Quality bar:**
- Entry with file path + evidence → passes
- Entry without file path → rejected
- Entry without evidence → rejected
- Duplicate (same type + file overlap) → rejected as redundant

**Incremental:**
- Same observation hash → synthesis skipped
- Different hash → full pipeline runs
- First run (no meta file) → full pipeline runs

### `filter_learnings_for_task` tests (`tests/test_synthesize.py`)

- Direct file match: entry with `lib/foo.py` matches task with `lib/foo.py`
- Directory match: entry with `lib/foo.py` matches task with `lib/bar.py` (same parent)
- No match: entry with `lib/foo.py` doesn't match task with `tests/bar.py`
- Fallback: zero matches → top 3 by weight returned
- Missing file → `""` returned
- Malformed JSON → `""` returned
- Empty entries → `""` returned
- Cross-agent entries include `[reframing_context]` tag in output

### Integration tests (`tests/test_injection.py`)

**Assembly functions:**
- `assemble_developer` with learnings → "Learned Patterns" section present in output
- `assemble_developer` with `learnings=""` → no "Learned Patterns" section
- `assemble_reviewer` with learnings → "Review Calibration" section present
- `assemble_architect` with learnings → "Project History" section present
- All 5 assembly functions: learnings inserted at correct position relative to surrounding sections

**Bridge functions:**
- `context_assemble_developer` reads `developer-learnings.json` and passes to assembly
- Missing learnings file → assembly called with `learnings=""`
- Malformed learnings file → assembly called with `learnings=""`

**Guardian:**
- `_run_guardian` with learnings file → "Scope Calibration" section in prompt
- `_run_guardian` without learnings file → no "Scope Calibration" section

### Real data tests

- Run synthesis on speed observations (1 feature) → entries produced, detail dicts intact
- Run synthesis on find-your-tribe observations (5 features) → entries produced, dedup merges similar entries
- Combined observations (6 features) → cross-agent entries present, token budgets respected
- Verify output files are valid JSON with correct schemas

## Validation Criteria

Before marking synthesis complete, verify against real data:

| Check | Expected |
|-------|----------|
| speed-security (173 obs) produces developer entries | retry and security_finding details intact |
| f9-profile-completeness (103 obs) produces reviewer entries | reviewer_finding details with category, finding, file |
| Combined 6-feature run produces cross-agent entries | retry → architect with `reframing_context: downstream_feedback` |
| All output files parse as valid JSON | Schema matches data model |
| Token budgets respected for all agents | No file exceeds its budget |
| Quality bar catches structural issues | Entries without file paths rejected |
| Incremental: re-run with same data produces same output | observation_hash match → skip |
| Injection: developer prompt contains learnings section | Section between constraints and code |
| Graceful degradation: corrupt learnings file → no crash | Warning logged, section skipped |
