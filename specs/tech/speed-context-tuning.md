# Tech Spec: Context Tuning

> Product spec: [speed-context-tuning.md](../product/speed-context-tuning.md)
> Depends on: Observation Infrastructure ([speed-observations.md](speed-observations.md)), Agent-Specific Synthesis ([speed-synthesis.md](speed-synthesis.md)), Layer 2 file selection (`lib/context/code_context.py`), CSG (`lib/context/csg.py`)

## Overview

Context tuning feeds learned file selection rules into Layer 2 so that the context package improves with experience. The observation pipeline already collects `context_miss` and `context_waste` signals. Synthesis already routes them to the developer. What's missing: a consumer in Layer 2 that reads those signals and adjusts file selection.

The tuning file (`context-learnings.json`) contains five rule types: learned exclusions, force-inclusions, co-modification bundles, tier overrides, and hop calibration. Layer 2 reads the file once at the start of `build_code_context()` and applies rules as a filter pass over the graph-expanded file list.

```
Observation pipeline (extract.py)
   context_miss: file modified but not in context package
   context_waste: file provided but never referenced in diff
        ↓
Synthesis (synthesize.py)
   Routes to developer as informational entries today
        ↓
Context tuning aggregator (NEW)
   Reads context_miss / context_waste observations across features
   Produces context-learnings.json with typed rules
        ↓
Layer 2 file selection (code_context.py)
   build_code_context() reads context-learnings.json
   Applies rules after graph expansion, before tier assignment
        ↓
Developer prompt with improved file selection
```

## Input Contract

### Observations consumed

Context tuning reads raw observations from `.speed/memory/observations/*.jsonl`, not synthesized learnings. Synthesis produces informational entries for agents; context tuning produces machine-readable rules for Layer 2.

| Observation type | Fields used | Rule produced |
|-----------------|------------|---------------|
| `context_waste` | `provided_count`, `used_count`, `waste_ratio`, files from `detail` | Learned exclusion (if waste_ratio > threshold across N features) |
| `context_miss` | `file`, `task_files_declared` | Force-inclusion (if file missed N+ times for tasks in same area) |

### Git history (for co-modification)

`git log --numstat` to extract co-modification pairs. Convention discovery also uses this data; context tuning imports the co-modification results rather than re-running git analysis.

Convention discovery's `_extract_comodification()` output is the source. If convention discovery hasn't run, context tuning runs its own lightweight version (file pairs only, no pattern interpretation).

### CSG cluster structure

Cluster IDs and file lists from `semantic-graph.json`. Used to scope per-area hop overrides and to identify hub files.

## Output Contract

### context-learnings.json

```json
{
  "generated_at": "2026-03-09T10:00:00Z",
  "observation_hash": "sha256:abc...",
  "rules": {
    "exclusions": [
      {
        "file": "lib/context/utils.py",
        "reason": "Included in 6 context packages, referenced in 0 diffs",
        "inclusions": 6,
        "references": 0,
        "scope": "lib/context/",
        "status": "active",
        "content_hash": "sha256:def..."
      }
    ],
    "force_inclusions": [
      {
        "file": "lib/context_bridge.sh",
        "reason": "Modified in 3 tasks touching lib/context/ but absent from all 3 context packages",
        "misses": 3,
        "scope": "lib/context/",
        "condition": "when task touches lib/context/"
      }
    ],
    "comodification_bundles": [
      {
        "files": ["lib/toml.py", "templates/speed-toml.toml"],
        "comodification_rate": 1.0,
        "commits_analyzed": 12
      }
    ],
    "tier_overrides": [
      {
        "pattern": "tests/test_*.py",
        "condition": "task has test requirements",
        "override_to": "full",
        "reason": "Skeleton tier for test files caused fixture rewrites in 2 features; full content eliminated the problem"
      }
    ],
    "hop_overrides": [
      {
        "cluster": "cluster_context_3",
        "default_hop": 2,
        "reason": "2-hop files referenced in 60% of tasks in this cluster",
        "evidence": "4 of 7 tasks used 2-hop files"
      },
      {
        "cluster": "cluster_toml_1",
        "default_hop": 1,
        "reason": "1-hop sufficient 100% of the time",
        "evidence": "5 of 5 tasks never used 2-hop files"
      }
    ],
    "hub_files": [
      {
        "file": "__init__.py",
        "pattern": "**/__init__.py",
        "discount": 0.5,
        "reason": "Inflates hop counts to 15+ files without adding signal. Never referenced in diffs."
      }
    ]
  }
}
```

The file is consumed by Layer 2 only. It is never injected into agent prompts. Synthesis continues to produce `developer-learnings.json` with informational context entries for the Developer; context tuning produces machine-readable rules for the file selection algorithm.

## Pipeline Implementation

### Module: `lib/learn/context_tuning.py`

```python
def build_context_learnings(
    memory_dir: Path,
    project_root: Path,
    csg_path: Path | None = None,
) -> ContextLearningsResult:
    """Aggregate context observations into file selection rules."""
```

### Step 1: Read context observations

```python
def _read_context_observations(obs_dir: Path) -> tuple[list[dict], list[dict]]:
    """Read context_miss and context_waste observations from all features."""
```

Load all `.jsonl` files. Filter for `observation_type` in (`context_miss`, `context_waste`). Return two lists, sorted by timestamp.

### Step 2: Aggregate waste signals

```python
def _aggregate_waste(waste_obs: list[dict]) -> list[ExclusionRule]:
    """Group waste observations by file. Produce exclusion rules for consistent waste."""
```

Group `context_waste` observations by file path. For each file:
- Count how many context packages included it (`inclusions`)
- Count how many diffs referenced it (`references`)
- Compute `waste_ratio = 1 - (references / inclusions)`

Exclusion threshold: `inclusions >= 3` AND `waste_ratio >= 0.8` (file included 3+ times, used in fewer than 20% of cases).

Each exclusion stores a `content_hash` (SHA-256 of current file content) for staleness detection.

Scope is derived from the file's parent directory. An exclusion for `lib/context/utils.py` is scoped to `lib/context/` — if a task in a different area needs utils.py, the exclusion doesn't apply.

### Step 3: Aggregate miss signals

```python
def _aggregate_misses(miss_obs: list[dict]) -> list[ForceInclusionRule]:
    """Group miss observations by file. Produce force-inclusion rules for consistent misses."""
```

Group `context_miss` observations by file path. For each file:
- Count how many tasks needed it but didn't have it (`misses`)
- Identify the scope (common parent directory of tasks that needed it)

Force-inclusion threshold: `misses >= 2` (file needed and absent twice for tasks in the same area).

Each force-inclusion rule has a `condition` describing when to apply: "when task touches `lib/context/`" (derived from the scope of tasks that missed it).

### Step 4: Co-modification bundles

```python
def _build_comod_bundles(
    project_root: Path,
    conventions_path: Path | None = None,
) -> list[ComodBundle]:
    """Extract co-modification pairs from git history or convention discovery output."""
```

If `conventions.json` exists and contains co-modification patterns from Phase A1, import them directly (no duplicate git analysis).

If not available, run a lightweight `git log --numstat` analysis: for each pair of files, compute co-modification rate. Threshold: 80%+ co-modification rate across 5+ commits.

Bundle rule: when either file is in the task scope, include the other.

### Step 5: Tier overrides

```python
def _compute_tier_overrides(
    miss_obs: list[dict],
    waste_obs: list[dict],
) -> list[TierOverride]:
    """Detect tier assignment patterns that correlate with retries or waste."""
```

Cross-reference context observations with task retry data (from the same observation files). If test files provided as skeleton correlated with retries in 2+ features, produce a tier override: "test files at full content when task has test requirements."

Tier overrides are expressed as patterns (`tests/test_*.py`) with conditions (`task has test requirements`). Layer 2 checks task metadata against conditions during tier assignment.

### Step 6: Hop calibration

```python
def _calibrate_hops(
    miss_obs: list[dict],
    csg: dict,
) -> tuple[list[HopOverride], list[HubFile]]:
    """Per-cluster hop distance and hub file identification."""
```

For each CSG cluster:
1. Count tasks where 2-hop files appeared in diffs (from context_miss observations: if a missed file was 2 hops away, 2-hop expansion would have caught it)
2. If 2-hop files used in 50%+ of tasks for that cluster → set `default_hop: 2`
3. If 1-hop sufficient 100% of the time → set `default_hop: 1` (saves tokens)

Hub file identification: files that appear as 1-hop neighbors of many seed files but are never referenced in diffs. `__init__.py` files with <50 lines of actual logic are the primary candidates. Hub files get a `discount` factor (0.5) that reduces their weight in hop calculations without fully excluding them.

### Step 7: Staleness detection

```python
def _detect_stale_rules(
    rules: dict,
    project_root: Path,
) -> dict:
    """Check existing rules against current codebase state."""
```

For each exclusion rule:
- Recompute file content hash
- If hash differs from `content_hash` stored in the rule by >50% (measured by line-level diff), mark rule as `possibly_stale`
- Stale rules revert to default behavior (file included if within hop range)

For each force-inclusion rule:
- Check if file still exists
- If deleted, remove the rule

Staleness runs at the start of every context tuning aggregation, before new rules are computed. Stale rules from the previous run are cleared before new evidence is processed.

### Step 8: Write output

Write `context-learnings.json` to `.speed/memory/`. Include `observation_hash` for incremental detection (same pattern as synthesis).

## Layer 2 Integration

### Hook point: `lib/context/code_context.py`

Context tuning integrates into `build_code_context()` after graph expansion and before tier assignment. The integration is a single function call.

```python
def build_code_context(task, project_root, csg, project_map, context_dir):
    # ... existing: seed collection (distance 0)
    # ... existing: 1-hop expansion
    # ... existing: 2-hop expansion

    # NEW: Apply context tuning rules
    tuning_path = Path(context_dir).parent / "memory" / "context-learnings.json"
    if tuning_path.exists():
        one_hop_files, two_hop_files, downgraded = _apply_context_tuning(
            tuning_path, task, seed_files, one_hop_files, two_hop_files,
            downgraded_one_hop, csg
        )

    # ... existing: tier assignment
    # ... existing: content loading
```

### `_apply_context_tuning()`

```python
def _apply_context_tuning(
    tuning_path: Path,
    task: dict,
    seed_files: list[str],
    one_hop_files: list[str],
    two_hop_files: list[str],
    downgraded: list[str],
    csg: dict,
) -> tuple[list[str], list[str], list[str]]:
    """Apply context-learnings.json rules to file lists."""
```

Processing order matters. Rules are applied in this sequence:

1. **Hub discounting.** Remove hub files from hop expansion results (or weight them down so they don't count as a "hop" for further expansion).

2. **Hop overrides.** For seed files in clusters with hop overrides, expand or contract the hop distance. If `cluster_context_3` has `default_hop: 2`, include 2-hop files for seeds in that cluster even if the default is 1-hop.

3. **Exclusions.** Remove files matching exclusion rules from all lists. Scope check: exclusion for `lib/context/utils.py` scoped to `lib/context/` only applies if the task touches `lib/context/`.

4. **Force-inclusions.** Add files matching force-inclusion rules if condition is met. If `lib/context_bridge.sh` has a force-inclusion "when task touches lib/context/" and the task's files include `lib/context/assembly.py`, add `context_bridge.sh` to 1-hop list.

5. **Co-modification bundles.** For each seed file, check if it's part of a bundle. If so, add the partner file(s) to the 1-hop list if not already present.

6. **Tier overrides.** For files matching tier override patterns, adjust tier if condition is met. Test files with `override_to: "full"` when task has test requirements → move from `downgraded` (skeleton) to `one_hop_files` (full content).

Returns modified `(one_hop_files, two_hop_files, downgraded)` tuples.

### Graceful degradation

```python
try:
    rules = json.loads(tuning_path.read_text())
except (OSError, json.JSONDecodeError, KeyError):
    return one_hop_files, two_hop_files, downgraded  # unchanged
```

Missing file, malformed JSON, or unexpected schema → return file lists unchanged. Layer 2 continues with default graph-based selection. No crash path.

## CLI Integration

### `speed learn` (automatic)

Context tuning runs as part of the `speed learn` pipeline, after observation extraction and before synthesis:

```
speed learn
  ├── Step 1: Observation extraction (extract.py)
  ├── Step 2: Context tuning aggregation (context_tuning.py)  ← NEW
  └── Step 3: Synthesis (synthesize.py)
```

Context tuning runs between extraction and synthesis because synthesis may use the tuning output to route context observations differently.

### `speed learn --context-tuning`

Standalone invocation to regenerate context-learnings.json without re-running extraction or synthesis.

### Incremental

Before aggregation, check `context-learnings.json.observation_hash` against current observation state. If unchanged, skip aggregation.

## Data Model

```python
@dataclass
class ExclusionRule:
    file: str
    reason: str
    inclusions: int
    references: int
    scope: str
    status: str           # "active" | "possibly_stale"
    content_hash: str

@dataclass
class ForceInclusionRule:
    file: str
    reason: str
    misses: int
    scope: str
    condition: str

@dataclass
class ComodBundle:
    files: list[str]
    comodification_rate: float
    commits_analyzed: int

@dataclass
class TierOverride:
    pattern: str          # glob pattern
    condition: str        # human-readable condition
    override_to: str      # "full" | "skeleton"
    reason: str

@dataclass
class HopOverride:
    cluster: str
    default_hop: int
    reason: str
    evidence: str

@dataclass
class HubFile:
    file: str
    pattern: str          # glob pattern (e.g., "**/__init__.py")
    discount: float       # 0.0-1.0
    reason: str

@dataclass
class ContextLearningsResult:
    rules: dict
    stale_cleared: int
    new_rules: int

    def summary(self) -> str:
        """Format summary for CLI output."""
```

## File Impact

| File | Change |
|------|--------|
| `lib/learn/context_tuning.py` | **New.** Aggregation pipeline (~400 lines estimated) |
| `lib/context/code_context.py` | Add `_apply_context_tuning()` function and call site in `build_code_context()`. ~80 lines. |
| `lib/learn_bridge.sh` | Add `learn_context_tuning()` bridge function |
| `lib/cmd/learn.sh` | Add `--context-tuning` flag handling. Insert context tuning step into default `speed learn` flow. |
| `tests/test_context_tuning.py` | **New.** Unit tests for aggregation and Layer 2 integration |

## Testing Plan

### Unit tests (`tests/test_context_tuning.py`)

**Waste aggregation:**
- File included 6 times, referenced 0 → exclusion rule produced
- File included 3 times, referenced 2 → no exclusion (waste_ratio < 0.8)
- File included 2 times, referenced 0 → no exclusion (below inclusion threshold)
- Exclusion scoped to parent directory of the file

**Miss aggregation:**
- File missed 3 times for tasks in `lib/context/` → force-inclusion rule with scope condition
- File missed 1 time → no rule (below threshold)
- Force-inclusion condition reflects common scope of tasks that missed it

**Co-modification:**
- Pair co-modified 12/12 commits → bundle created
- Pair co-modified 3/10 commits → no bundle (below 80% threshold)
- Pair co-modified 4/4 commits but only 4 total → bundle created (rate matters, not volume, once above minimum)
- Convention discovery output imported when available (no duplicate git analysis)

**Tier overrides:**
- Test files as skeleton correlated with retries → override to full content
- No correlation detected → no override

**Hop calibration:**
- Cluster where 2-hop files used 60% of time → hop override to 2
- Cluster where 1-hop sufficient 100% → hop override to 1
- Hub files identified: `__init__.py` with <50 lines, never in diffs

**Staleness:**
- Exclusion with matching content_hash → active
- Exclusion with >50% content change → possibly_stale, reverted
- Force-inclusion for deleted file → removed

**Layer 2 integration:**
- `_apply_context_tuning()` with exclusion → file removed from list
- `_apply_context_tuning()` with force-inclusion (condition met) → file added
- `_apply_context_tuning()` with force-inclusion (condition not met) → file not added
- `_apply_context_tuning()` with bundle → partner file added
- `_apply_context_tuning()` with tier override → file moved between lists
- `_apply_context_tuning()` with missing file → file lists unchanged
- `_apply_context_tuning()` with malformed JSON → file lists unchanged

### Integration tests

- Full pipeline: extract observations → aggregate tuning → produce context-learnings.json → Layer 2 reads and applies
- Layer 2 without context-learnings.json → default behavior (no crash, no change)
- Layer 2 with empty rules → default behavior
- Co-modification bundle: including file A → partner file B appears in context package

## Validation Criteria

| Check | Expected |
|-------|----------|
| Context observations from SPEED's own runs produce meaningful rules | At least 1 exclusion or 1 force-inclusion from real observation data |
| Layer 2 applies exclusion | File with waste_ratio=1.0 absent from context package |
| Layer 2 applies force-inclusion | Previously-missed file present in context package when condition met |
| Co-modification bundles work | Including `lib/toml.py` also includes `templates/speed-toml.toml` |
| Staleness clears stale rules | File with >50% content change has exclusion reverted |
| Graceful degradation | Corrupt context-learnings.json → Layer 2 continues with defaults |
| Budget not inflated | Force-inclusions and bundles don't push context packages over token budget (budget enforcement runs after tuning) |
