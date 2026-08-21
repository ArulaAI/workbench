# RFC: Human Correction Capture

> See [speed-human-corrections.md](../product/speed-human-corrections.md) for product context.
> Depends on: Observation Infrastructure ([speed-observations.md](speed-observations.md)), Extraction (`lib/learn/extract.py`), Git integration (`lib/git.sh`)

## Basic Example

```bash
# After merging a SPEED PR where you fixed 2 files:
speed learn --post-merge -f speed-security

# Post-merge correction capture — speed-security
#   Resolving task branches ........... 5 branches found
#   Diffing against merged result ..... 2 tasks with changes
#   Noise filter ...................... 1 changelog excluded
#   Classification .................... 2 transformative, 1 additive
#   PR comments ....................... 1 matched
#
#   3 human corrections captured (2 transformative, 1 additive)
#   2 tasks unchanged (unknown, not approved)

# Extraction-time signals (runs during normal speed learn):
speed learn -f speed-defects

# Step 11/14: Retry guidance ........ 3 (3 guidance)
# Step 12/14: Skip flags ........... 1 (1 skip)
# Step 13/14: Forced approvals ..... 0
# Step 14/14: Defect rejections .... 0
#
# Wrote 4 observations to .speed/memory/observations/speed-defects.jsonl
```

## Overview

Human corrections capture the gap between what SPEED produced and what the human shipped. Six signal types exist; each enters the observation pipeline as a `human_override` or `human_approved` observation.

The implementation splits into two paths based on trigger:

1. **Post-merge path** (`speed learn --post-merge`): Diffs SPEED's branch tip against the merged result, determines change type from diff structure, and creates observations. No LLM calls. Runs on demand after PR merge.

2. **Extraction-time path** (runs during `speed learn`): Reads existing artifacts (task JSON, skip logs, defect state) and detects retry guidance, skip flags, forced approvals, and defect rejections. Deterministic. No LLM calls.

```
Post-merge path:
  git diff (SPEED tip vs merged) → per-task hunks
       → noise filter → deterministic change type → rule-based attribution → observations

Extraction-time path:
  task JSON (review_feedback)     → parse "Human guidance:" → observations
  skipped-gates.json              → read skip entries       → observations
  task JSON (reviewed_at vs log)  → detect forced approval  → observations
  defect state.json (rejected)    → read triage context     → observations
```

### Signal Types

| Signal | Trigger | Observation Type | Weight | LLM Required | HC Stories |
|--------|---------|-----------------|--------|------|------------|
| Post-merge edit | `--post-merge` | `human_override` | 2.5 | No | HC1, HC3-HC11 |
| Zero-delta merge | `--post-merge` | `human_approved` | 0.5 | No | HC2 |
| Retry guidance | `speed learn` extraction | `human_override` | 2.5 | No | HC12 |
| Skip flag | `speed learn` extraction | `human_override` | 0.5 | No | HC13 |
| Forced approval | `speed learn` extraction | `human_override` | 2.0 | No | HC14 |
| Defect rejection | `speed learn` extraction | `human_override` | 1.5 | No | HC15 |

## Data Model

### New observation type

Add `human_approved` to `ObservationType` in `lib/learn/extract.py:18-24`:

```python
ObservationType = Literal[
    "retry", "reviewer_finding", "human_override", "guardian_verdict",
    "gate_failure", "context_miss", "context_waste", "decomposition_miss",
    "convention_violation", "verify_finding", "coherence_issue",
    "security_finding", "success", "pattern_match", "unattributed_changes",
    "agent_concern", "human_approved",  # ← new
]
```

Add to `_WEIGHTS` in `lib/learn/extract.py:31`:

```python
"human_approved": 0.5,
```

### Detail schemas

**Post-merge edit** (`human_override`, change_type=correction):

```python
{
    "change_type": "additive" | "subtractive" | "transformative" | "cosmetic",
    "file": "lib/security.py",
    "commit_sha": "abc123",
    "commit_message": "Fix httpx calls to use project wrapper",
    "hunk_summary": "+5/-3 lines",  # deterministic from diff
    "human_comment": "We always use the project wrapper" | null,
    "agent_attribution": ["developer"],
    "task_id": "3",
}
```

(`category` removed from extraction-time schema — assigned by synthesis, not extraction. See DD1.)

**Zero-delta merge** (`human_approved`):

```python
{
    "tasks_approved": 5,
    "files_approved": 15,
    "task_ids": ["1", "2", "3", "4", "5"],
}
```

**Retry guidance** (`human_override`, change_type=guidance):

```python
{
    "change_type": "guidance",
    "guidance_text": "The auth handler needs to validate tokens before checking permissions",
    "task_id": "3",
    "attempt": 2,
    "original_error": "timeout",
    "task_succeeded": true,
    "agent_attribution": ["developer"],
}
```

**Skip flag** (`human_override`, change_type=skip):

```python
{
    "change_type": "skip",
    "gate_name": "guardian_pre_plan" | "guardian_post_review" | "guardian_post_integration" | "gates" | "audit" | "tests",
    "pipeline_stage": "plan" | "review" | "integrate",
}
```

**Forced approval** (`human_override`, change_type=forced_approval):

```python
{
    "change_type": "forced_approval",
    "task_id": "3",
    "reviewer_verdict": "request_changes",
    "reviewer_findings": [...],  # from review-{task_id}.json
    "agent_attribution": ["reviewer"],
}
```

**Defect rejection** (`human_override`, change_type=defect_rejection):

```python
{
    "change_type": "defect_rejection",
    "defect_name": "auth-timeout-race",
    "defect_type": "regression",
    "complexity": "moderate",
    "triage_summary": "...",
    "agent_attribution": ["debugger"],
}
```

## State Machine

Not applicable. Human corrections are stateless observations. They are extracted once, written to the append-only JSONL log, and consumed by synthesis. No lifecycle, no transitions.

## API Surface

Not applicable. Human correction capture is a CLI feature (`speed learn --post-merge`), not a service or API. The interface is the observation JSONL format defined in Data Model.

## Post-Merge Path

### Step 1: Identify SPEED's output per task

SPEED doesn't use a distinct commit author or message pattern. The developer agent (Claude Code) commits with the user's git identity. Commit message prefixes are not reliable identifiers.

What IS reliable: **task branch names and task JSON**. Each task records its branch in `.branch` (e.g., `speed/<feature>/task-3-add-login`). That branch tip is SPEED's last commit for that task. Integration merges these into main with `--no-ff`.

When `speed learn --post-merge -f <feature>` runs:

```python
def find_speed_branches(feature: str, feature_dir: Path, project_root: Path) -> dict[str, str]:
    """Map task branches to their tip SHAs.

    Returns {branch_name: tip_sha} for all task branches that still exist.
    """
    branches = {}
    tasks_dir = feature_dir / "tasks"
    for task_file in tasks_dir.glob("*.json"):
        task = json.loads(task_file.read_text())
        branch = task.get("branch", "")
        if not branch:
            continue
        # Check branch still exists in git
        tip = _git("rev-parse", "--verify", branch)
        if tip:
            branches[branch] = tip
    return branches
```

Each task branch tip represents SPEED's output for that task. The merged result is `HEAD` of main (or the merge commit). The diff between a task branch tip and the corresponding files in the merged result reveals human corrections for that task's scope.

**Branch deleted?** If a task branch was cleaned up before `--post-merge` runs, that task's corrections are unrecoverable. Warn and skip. Remaining task branches still produce valid corrections.

**Squash merge fallback**: If the PR was squash-merged, task branches may point to commits that aren't ancestors of main. In that case, diff the task branch tip against `HEAD` of main for the files that task touched (`files_to_modify` + `files_to_create` from task JSON). Per-hunk analysis of the resulting diff.

### Step 2: Extract human changes

For each task branch, diff SPEED's output against the merged result:

```bash
# Per-file diff between SPEED's branch tip and merged main
git diff <task_branch_tip> HEAD -- <file1> <file2> ...
```

The file list comes from the task JSON: `files_to_modify` + `files_to_create`. Only diff files SPEED was responsible for. Changes to other files are not corrections to SPEED's output.

If the diff is empty for all files in a task, that task's output was accepted unchanged.

If the diff is empty for ALL tasks in the feature, that's a zero-delta merge.

Filter out known bot authors from any additional commits on main between the last merge commit and HEAD:

```python
BOT_AUTHORS = {"github-actions[bot]", "dependabot[bot]", "renovate[bot]"}
```

This list is configurable via `speed.toml`.

### Step 3: Noise filter

Per task diff, check each changed file:

| Check | Action |
|-------|--------|
| File is CHANGELOG, version file, lock file | Exclude that file |
| Only whitespace/formatting changes in file | Record with weight 0.1, change_type=cosmetic |
| File not in task's `files_to_modify` or `files_to_create` | Exclude (not a correction to SPEED) |

Step 2 already scopes diffs to task files, so the third check is redundant but serves as a safety net.

### Step 4: Per-task hunk extraction

For each task with a non-empty diff:

```bash
git diff <task_branch_tip> HEAD -- <file1> <file2> ... --unified=3
```

Split the unified diff into per-file hunks. Each hunk's change type is determined deterministically from the diff structure: only additions = additive, only removals = subtractive, both = transformative, whitespace-only = cosmetic.

### Step 5: PR comment association

If the repo is GitHub-hosted (detect by `gh api` availability):

```bash
gh api repos/{owner}/{repo}/pulls/{pr_number}/comments
```

Match comments to hunks by file path and line range. Store matched comment text in the observation's `human_comment` field. If `gh api` fails or the repo is local-only, proceed with `human_comment: null`.

PR number detection: read from `.speed/features/<name>/pr-number` (written by `speed integrate` if it creates a PR) or search recent PRs by branch name.

### Step 6: Deterministic classification

Each hunk receives a change type from the diff structure and agent attribution from file-based rules. No LLM call. See DD1.

**Change type** (deterministic from diff):

| Type | Rule |
|------|------|
| additive | Only `+` lines, no corresponding `-` lines |
| subtractive | Only `-` lines, no corresponding `+` lines |
| transformative | Both `+` and `-` lines on the same content |
| cosmetic | Only whitespace/formatting differences |

**Agent attribution** (rule-based from file path):

```python
def _attribute_agent(file_path: str, change_type: str) -> list[str]:
    agents = []
    if file_path.startswith("agents/"):
        agents.append("architect")
    else:
        agents.append("developer")
    # Subtractive changes also attribute to guardian (should have caught scope drift)
    if change_type == "subtractive":
        agents.append("guardian")
    return agents
```

**Learning category**: Not assigned at extraction time. Synthesis assigns category when processing the observation alongside cross-feature context.

### Step 7: Create observations

Each classified hunk becomes an `Observation`. The task ID is known directly from Step 1 (each diff is scoped to a task branch):

```python
Observation(
    id=observation_id(feature, task_id, "human", "human_override", detail),
    feature=feature,
    stage="human",
    task_id=task_id,  # from the task whose branch produced this diff
    timestamp=now_iso(),
    observation_type="human_override",
    detail=detail,  # from deterministic classification
    weight=2.5,     # cosmetic gets overridden to 0.1
)
```

### Zero-delta detection

If Step 2 finds empty diffs for ALL tasks in the feature, create a single `human_approved` observation:

```python
Observation(
    id=observation_id(feature, "*", "human", "human_approved", detail),
    feature=feature,
    stage="human",
    task_id="*",
    timestamp=now_iso(),
    observation_type="human_approved",
    detail={
        "tasks_approved": len(tasks),
        "files_approved": len(all_files),
        "task_ids": [t["id"] for t in tasks],
    },
    weight=0.5,
)
```

## Extraction-Time Path

These four signal types are captured during the existing `speed learn` extraction pipeline. They run as new steps in `extract_observations()`.

### Step 11: Retry guidance extraction

**Source**: Task JSON files in `.speed/features/<feature>/tasks/*.json`

**Logic**:

```python
def _step11_retry_guidance(tasks: list[dict], feature: str) -> list[Observation]:
    observations = []
    for task in tasks:
        feedback = task.get("review_feedback", "")
        if not feedback:
            continue
        # Parse "Human guidance:" markers written by retry.sh
        for match in re.finditer(
            r"--- Attempt (\d+) ---\nFailed with: (.*?)\nHuman guidance: (.*?)(?=\n--- Attempt|\Z)",
            feedback, re.DOTALL,
        ):
            attempt = int(match.group(1))
            error = match.group(2).strip()
            guidance = match.group(3).strip()
            if not guidance:
                continue
            detail = {
                "change_type": "guidance",
                "guidance_text": guidance,
                "task_id": task["id"],
                "attempt": attempt,
                "original_error": error,
                "task_succeeded": task.get("status") == "done",
                "agent_attribution": [_agent_for_task(task)],
            }
            observations.append(Observation(
                id=observation_id(feature, task["id"], "human", "human_override", detail),
                feature=feature,
                stage="human",
                task_id=task["id"],
                timestamp=_now_iso(),
                observation_type="human_override",
                detail=detail,
                weight=2.5,
            ))
    return observations
```

**Agent attribution**: The failing agent is recorded in `task.agent_model`. For now, all task-level failures attribute to `developer` since that's the only agent that executes tasks.

### Step 12: Skip flag extraction

**Source**: `.speed/features/<feature>/logs/skipped-gates.json`

This file doesn't exist today. Gate call sites need a one-line addition to log skips.

**Skip logging (new code in gate call sites)**:

```bash
# In plan.sh, review.sh, integrate.sh, gates.sh at each skip check:
_log_gate_skip() {
    local gate_name="$1"
    local stage="$2"
    local skip_file="${LOGS_DIR}/skipped-gates.json"
    local entry
    entry=$(jq -nc --arg g "$gate_name" --arg s "$stage" --arg t "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        '{gate: $g, stage: $s, timestamp: $t}')
    echo "$entry" >> "$skip_file"
}
```

Call sites (insert after each skip check):

| File | Line | Gate Name | Stage |
|------|------|-----------|-------|
| `plan.sh:251` | After `SKIP_GUARDIAN` check | `guardian_pre_plan` | `plan` |
| `review.sh:273` | After `SKIP_GUARDIAN` check | `guardian_post_review` | `review` |
| `integrate.sh:200` | After `SKIP_GUARDIAN` check | `guardian_post_integration` | `integrate` |
| `gates.sh:27` | After `SKIP_GATES` check | `gates` | `run` |
| `plan.sh:264` | After `--skip-audit` check | `audit` | `plan` |
| `integrate.sh:165` | After `--skip-tests` check | `tests` | `integrate` |

**Extraction logic**:

```python
def _step12_skip_flags(feature_dir: Path, feature: str) -> list[Observation]:
    skip_file = feature_dir / "logs" / "skipped-gates.json"
    if not skip_file.exists():
        return []
    observations = []
    for line in skip_file.read_text().strip().split("\n"):
        if not line.strip():
            continue
        entry = json.loads(line)
        detail = {
            "change_type": "skip",
            "gate_name": entry["gate"],
            "pipeline_stage": entry["stage"],
        }
        observations.append(Observation(
            id=observation_id(feature, "*", "human", "human_override", detail),
            feature=feature,
            stage="human",
            task_id="*",
            timestamp=entry.get("timestamp", _now_iso()),
            observation_type="human_override",
            detail=detail,
            weight=0.5,
        ))
    return observations
```

### Step 13: Forced approval detection

**Source**: Task JSON (`.reviewed_at`, `.review_verdict`) and review logs (`${LOGS_DIR}/review-{task_id}.json`)

**Logic**: A forced approval is detected when:
- `review_verdict == "approve"` AND
- No review log exists (`review-{task_id}.json` missing), OR
- Review log exists but its verdict is `"request_changes"` (human overrode the reviewer's rejection)

```python
def _step13_forced_approvals(
    tasks: list[dict], feature: str, logs_dir: Path,
) -> list[Observation]:
    observations = []
    for task in tasks:
        if task.get("review_verdict") != "approve":
            continue
        tid = task["id"]
        log_path = logs_dir / f"review-{tid}.json"

        forced = False
        reviewer_findings = []

        if not log_path.exists():
            # No review log but verdict is approve → forced
            forced = True
        else:
            review_data = json.loads(log_path.read_text())
            if review_data.get("verdict") == "request_changes":
                # Reviewer said no, but verdict is approve → forced
                forced = True
                reviewer_findings = review_data.get("issues", [])

        if not forced:
            continue

        detail = {
            "change_type": "forced_approval",
            "task_id": tid,
            "reviewer_verdict": "request_changes" if reviewer_findings else "no_review",
            "reviewer_findings": reviewer_findings[:5],  # cap stored findings
            "agent_attribution": ["reviewer"],
        }
        observations.append(Observation(
            id=observation_id(feature, tid, "human", "human_override", detail),
            feature=feature,
            stage="human",
            task_id=tid,
            timestamp=_now_iso(),
            observation_type="human_override",
            detail=detail,
            weight=2.0,
        ))
    return observations
```

### Step 14: Defect rejection extraction

**Source**: `.speed/defects/*/state.json`

This step runs separately from feature extraction since defects are not feature-scoped. It reads all defect directories and finds those in `rejected` state.

```python
def _step14_defect_rejections(
    defects_dir: Path, feature: str,
) -> list[Observation]:
    if not defects_dir.is_dir():
        return []
    observations = []
    for state_file in defects_dir.glob("*/state.json"):
        state = json.loads(state_file.read_text())
        if state.get("status") != "rejected":
            continue
        defect_name = state_file.parent.name
        # Read triage output if available
        triage_path = state_file.parent / "triage.json"
        triage = {}
        if triage_path.exists():
            triage = json.loads(triage_path.read_text())
        detail = {
            "change_type": "defect_rejection",
            "defect_name": defect_name,
            "defect_type": triage.get("defect_type", state.get("defect_type")),
            "complexity": triage.get("complexity", state.get("complexity")),
            "triage_summary": triage.get("summary", ""),
            "agent_attribution": ["debugger"],
        }
        observations.append(Observation(
            id=observation_id(feature, "*", "human", "human_override", detail),
            feature=feature,
            stage="human",
            task_id="*",
            timestamp=_now_iso(),
            observation_type="human_override",
            detail=detail,
            weight=1.5,
        ))
    return observations
```

## Synthesis Integration

Human correction observations flow through the existing synthesis pipeline unchanged. Two adjustments:

### Agent routing

Add to `_AGENT_ROUTING` in `lib/learn/synthesize.py`:

```python
"human_override": "developer",   # default; detail.agent_attribution overrides
"human_approved": "developer",   # positive signal for all agents
```

The `_build_entries` function already reads the primary agent from `_AGENT_ROUTING`. For `human_override`, override with `detail.get("agent_attribution", ["developer"])[0]` when present.

### Cross-agent reframing

Add one rule to `_REFRAMING_RULES`:

```python
# Human override attributed to developer → reviewer gets "missed by review" signal
{
    "source_type": "human_override",
    "source_agent": "developer",
    "target_agent": "reviewer",
    "condition": lambda e: e.detail.get("change_type") in ("transformative", "additive"),
    "reframing_context": "missed_by_review",
}
```

### Conflict resolution

`human_override` already has weight 2.5, the highest failure weight. In `_detect_conflicts`, if a `human_override` contradicts a `reviewer_finding` on the same files, the human override wins automatically (higher weight resolves the conflict).

## CLI Integration

### `speed learn --post-merge`

Add to `cmd_learn` in `lib/cmd/learn.sh`:

```bash
--post-merge)  postmerge_mode=true; shift ;;
```

New bridge function `learn_post_merge` in `lib/learn_bridge.sh` that:
1. Calls `find_speed_tip()` to get the commit range
2. Calls `extract_human_corrections()` for the post-merge path
3. Calls `write_observations()` to append to the feature's JSONL
4. Prints summary: N corrections, categories, zero-delta status

### Extraction pipeline changes

Update `extract_observations()` in `lib/learn/extract.py` to call steps 11-14 after step 10:

```python
# Step 11: Retry guidance
observations.extend(_step11_retry_guidance(tasks, feature))

# Step 12: Skip flags
observations.extend(_step12_skip_flags(feature_dir, feature))

# Step 13: Forced approvals
observations.extend(_step13_forced_approvals(tasks, feature, logs_dir))

# Step 14: Defect rejections (feature-independent, but runs here for simplicity)
defects_dir = project_root / ".speed" / "defects"
observations.extend(_step14_defect_rejections(defects_dir, feature))
```

## Validation Rules

Not applicable. All inputs are pipeline artifacts (task JSON, git diffs, skip logs) read from the local filesystem. No user-facing input validation.

## Security & Controls

**No secrets in observations.** Observations record file paths, change types, hunk summaries (`+5/-3 lines`), and commit messages. Actual diff content is not stored. If a human correction removes a hardcoded secret, the observation records "subtractive correction in lib/config.py" without the secret itself.

**PR comments are stored verbatim.** Comments are human-authored text written for public review. Storing them carries no additional risk beyond what the PR already exposed.

**No LLM calls.** Post-merge classification is deterministic. No code is sent to any provider during correction extraction. See DD1.

**Append-only storage.** Human override observations follow the same append-only model as all other observations. Never modified or deleted by the system.

## Key Decisions

| Decision | Choice | Alternatives Considered | Rationale |
|----------|--------|------------------------|-----------|
| DD1: Post-merge classification method | Deterministic (change type from diff, agents from rules). Category deferred to synthesis. | LLM classification per hunk; TF-IDF prototype classifier | TF-IDF validated at 20% category accuracy on 20 real hunks (vocabulary mismatch: code tokens vs. prose prototypes). LLM adds cost, latency, non-determinism, and provider dependency. Change type (100%) and agent attribution (90%) are accurate without either. See `tests/validate_classifier_postmerge.py`. |
| DD2: Task branch tips as SPEED output identifier | Read `.branch` from task JSON, resolve via `git rev-parse` | Commit message pattern matching; commit author detection; stored tip SHA | SPEED commits with the user's git identity. No unique author or message prefix. Task branches are the only reliable artifact. |
| DD3: Two-path architecture | Extraction-time (deterministic, steps 11-14) separate from post-merge (git diff, steps 1-7) | Single unified path; single post-merge path for all signals | Extraction-time signals read existing artifacts with zero new dependencies. Post-merge requires branch preservation and git diffs. Separating them lets Phase 1 ship without blocking on Phase 2. |

## Drawbacks

**Branch deletion loses post-merge data permanently.** If task branches are cleaned up before `speed learn --post-merge` runs, those corrections are unrecoverable. No fallback. Extraction-time signals survive because they read task JSON, not branches.

**Category assignment is deferred, not solved.** DD1 drops per-hunk category classification because prototype accuracy was 20%. Synthesis must still assign categories from change type and cross-feature context. If it can't, the correction's routing to the right agent is uncertain.

**Cold start requires multiple features.** Synthesis needs 2+ occurrences of a correction pattern before producing learnings entries. A new project gets no correction-driven guidance until the human has corrected the same pattern across at least two features.

**Extraction-time signals are indirect.** Retry guidance, skip flags, and forced approvals capture what the human told the system (intentions), not what the human changed in the code (actions). The highest-value signal (post-merge diff) is also the most complex to implement.

## Search / Query Strategy

Not applicable. Observations are append-only JSONL files read sequentially by synthesis. No indexing, no queries.

## Migration Strategy

Not applicable. Human correction capture adds new observation types (`human_approved`) and new detail schemas to an append-only log. Existing observations are unaffected. No schema migration required.

## File Impact

| File | Change |
|------|--------|
| `lib/learn/extract.py` | Add `human_approved` to ObservationType, add to `_WEIGHTS`, call into `human_corrections.py` for steps 11-14 |
| `lib/learn/human_corrections.py` | New file: steps 11-14 (extraction-time human signals) + post-merge path (Phase 2) |
| `lib/cmd/learn.sh` | Add `--post-merge` flag |
| `lib/learn_bridge.sh` | Add `learn_post_merge` bridge function |
| `lib/cmd/plan.sh` | Add `_log_gate_skip` call at line 251, 264 |
| `lib/cmd/review.sh` | Add `_log_gate_skip` call at line 273 |
| `lib/cmd/integrate.sh` | Add `_log_gate_skip` call at line 200, 165 |
| `lib/gates.sh` | Add `_log_gate_skip` function definition, call at line 27 |
| `lib/shared.sh` | Add `_log_gate_skip` function (shared across call sites) |
| `lib/learn/synthesize.py` | Add `human_override`/`human_approved` to `_AGENT_ROUTING`, add cross-agent rule |
| `tests/test_corrections.py` | New file: tests for steps 11-14 |
| `tests/test_post_merge.py` | New file: tests for post-merge path |

## Implementation Order

The extraction-time signals (steps 11-14) are independent from the post-merge path and simpler to implement. Build them first.

1. **Phase 1: Extraction-time signals** (no LLM, no git diff)
   - Add `human_approved` type and weight to extract.py
   - Implement steps 11-14 in `human_corrections.py`, called from `extract_observations()`
   - Add `_log_gate_skip` function to shared.sh
   - Wire skip logging into 6 gate call sites
   - Tests for all 4 extraction steps
   - Update synthesis routing

2. **Phase 2: Post-merge path** (git diff, deterministic classification)
   - Implement `find_speed_branches` (task branch resolution from task JSON)
   - Implement noise filter
   - Implement per-hunk extraction with deterministic change type
   - Implement rule-based agent attribution
   - Implement PR comment extraction via `gh api` (optional enrichment)
   - Add `--post-merge` CLI flag and bridge function
   - Tests with mock git repos

3. **Phase 3: Integration testing**
   - End-to-end: corrections → synthesis → injection → agent prompt
   - Verify conflict resolution (human override wins over reviewer finding)
   - Verify weight 2.5 propagation through synthesis

## Testing Plan

### Unit tests (steps 11-14)

| Test | Input | Expected |
|------|-------|----------|
| Retry guidance: single attempt | task with `review_feedback` containing one `Human guidance:` block | 1 observation, change_type=guidance |
| Retry guidance: multiple attempts | task with 3 `--- Attempt ---` blocks, 2 with guidance | 2 observations |
| Retry guidance: no guidance marker | task with only reviewer feedback in `review_feedback` | 0 observations |
| Retry guidance: task failed | task with guidance but status=failed | 1 observation, task_succeeded=false |
| Skip flags: single skip | skipped-gates.json with 1 entry | 1 observation, weight=0.5 |
| Skip flags: multiple skips | 3 entries for different gates | 3 observations |
| Skip flags: no file | no skipped-gates.json | 0 observations |
| Forced approval: no review log | task approved, no review-{id}.json | 1 observation, reviewer_verdict=no_review |
| Forced approval: reviewer rejected | task approved, review log has verdict=request_changes | 1 observation with reviewer findings |
| Forced approval: normal approval | task approved, review log has verdict=approve | 0 observations |
| Defect rejection: rejected state | state.json with status=rejected | 1 observation with triage context |
| Defect rejection: non-rejected | state.json with status=resolved | 0 observations |
| Defect rejection: no triage | rejected defect with no triage.json | 1 observation, empty triage fields |

### Unit tests (post-merge path)

| Test | Input | Expected |
|------|-------|----------|
| Zero-delta merge | All task branch tips match HEAD for their files | 1 `human_approved` observation |
| Single task correction | 1 task branch with diff against HEAD | 1+ `human_override` observations (one per hunk) |
| Multi-task corrections | 3 task branches with diffs | Observations per task, task_id set correctly |
| Noise: changelog only | Diff includes only CHANGELOG.md (not in task files) | 0 observations |
| Noise: cosmetic | Whitespace-only diff in task file | 1 observation, weight=0.1 |
| Squash merge fallback | Task branch not ancestor of main, diff by file list | N observations (one per hunk) |
| PR comment match | Comment on same file/line as hunk | Observation has human_comment field |
| Branch deleted | Task branch cleaned up before --post-merge | Warning for that task, other tasks still processed |
| All branches deleted | No task branches exist | Warning, 0 observations |

## Graceful Degradation

| Failure | Behavior |
|---------|----------|
| Task branch deleted before `--post-merge` | Warning for that task, skip it. Other task branches still processed. Extraction-time signals still captured. |
| `gh api` unavailable | PR comments skipped, `human_comment: null` on all observations |
| `skipped-gates.json` malformed | Skip corrupted lines, warn. Valid lines still processed. |
| Task JSON missing `review_feedback` | Step 11 produces 0 observations for that task. |
| No review log and no review verdict | Step 13 skips that task (not a forced approval, just not reviewed). |

## Dependencies

- **Observation Infrastructure** (`lib/learn/extract.py`) — Human corrections are stored as observations in the existing JSONL format. Observation ID generation and idempotency apply.
- **Synthesis** (`lib/learn/synthesize.py`) — Human override observations flow into synthesis with weight 2.5. Without synthesis, corrections are collected but not actionable.
- **Git history** — Post-merge path requires task branch tips and merged result to be accessible via `git rev-parse` and `git diff`.
- **GitHub API (optional)** — PR comment extraction uses `gh api`. Corrections work without comments (`human_comment: null`).
- **Skip flag logging** — Requires each gate function to write a log entry when skipped. Today gates are bypassed silently. Needs one-line additions to 6 call sites.

## Success Criteria

Cross-reference with [PRD success criteria](../product/speed-human-corrections.md#success-criteria). Implementation-specific verification:

- [ ] `find_speed_branches()` resolves all task branches from task JSON `.branch` field
- [ ] `git diff <task_branch_tip> HEAD -- <files>` produces per-task diffs scoped to task's declared files
- [ ] Change type classification is deterministic: additive/subtractive/transformative/cosmetic from diff structure alone (validated at 100% accuracy)
- [ ] Agent attribution is rule-based from file path (validated at 90% accuracy)
- [ ] Noise filter excludes CHANGELOG, version files, lock files, and files not in task's declared scope
- [ ] Zero-delta detection: empty diffs across all tasks produces a single `human_approved` observation
- [ ] Steps 11-14 produce observations from existing artifacts without new dependencies (validated: 26 signals across 2 projects)
- [ ] `_log_gate_skip()` writes to `skipped-gates.json` at all 6 gate call sites
- [ ] Observations use deterministic IDs: re-running extraction produces no duplicates
- [ ] Graceful degradation: deleted branches warn and skip, missing artifacts skip silently, no extraction failure crashes the pipeline

## Unresolved Questions

| ID | Question | Recommendation |
|----|----------|---------------|
| Q4 | Capture retry guidance even when all retries fail? | Yes. Failed diagnoses still reveal what the human thinks the problem is. If the diagnosis is wrong, the failed status is recorded (`task_succeeded: false`) and synthesis can weight accordingly. |
| Q5 | Skip observation at skip time or extraction time? | Extraction time. Write to `skipped-gates.json` at skip time (cheap, one line), create observations at extraction time (consistent with all other observation creation). |
