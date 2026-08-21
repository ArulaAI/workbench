# RFC: Failure Autopsy & Prescriptive Retry

> See [product spec](../product/speed-failure-autopsy.md) for product context.
> Depends on: [Turn Exhaustion Salvage](fix-turn-exhaustion-loses-work.md), existing failure classification (`lib/failure_classify.py`), existing debugger agent (`agents/debugger.md`)

## Basic Example

A task fails. Today vs. after this change:

```
TODAY:
  Task 3 hits 50-turn limit → "Quality gates failed"
  → failure_classify: unclassified/unknown
  → operator reads 50-turn log manually (15 min)
  → operator writes: speed retry --task-id 3 --context "it ran out of turns, the code is mostly done, focus on the log path"
  → retry agent starts from scratch, rewrites 504 lines

AFTER:
  Task 3 hits 50-turn limit → salvage commits staged work
  → autopsy reads: log (50 turns), diff (504 lines), spec (12 criteria), gates (absent)
  → diagnosis.json:
      root_cause: turn_exhaustion
      evidence: "50/50 turns. 504 lines salvaged. Gates never reached."
      criteria_addressed: 11/12
      criteria_missed: ["secrets scan log path"]
      spec_divergences: ["uses LOGS_DIR, spec requires STATE_DIR/features/..."]
      salvageable: true
      recommended_budget: 75
  → speed retry --task-id 3
  → retry agent receives: diagnosis, salvaged diff reference, adjusted budget (75 turns)
  → completes in 23 turns
```

## Relationship to the Existing Debugger

The debugger and autopsy agent are complementary, not competing.

| Dimension | Debugger | Autopsy |
|-----------|----------|---------|
| Trigger | Gate failure (code was committed, gates ran, gates failed) | Any failure (including when gates never ran) |
| Focus | Code-level: syntax, imports, types, tests, lint, schema | Pipeline-level: turn exhaustion, context cuts, spec gaps, classification gaps |
| Reads | Task desc, error output, git diff, gate results | Agent log (full turn history), worktree state, acceptance criteria, gate output (or absence) |
| Produces | `fix.json`: root cause location, specific code fix, confidence | `diagnosis.json`: root cause class, criteria analysis, spec divergences, salvageability, budget recommendation |
| Question answered | "What line of code is wrong?" | "Why did the pipeline fail to produce the right code?" |

The debugger continues to handle gate failures where the code exists but is wrong. The autopsy handles everything upstream of that: turn exhaustion, missing context, spec ambiguity, and cases where gates never ran.

When gates fail after the autopsy's salvage step, both agents may run: autopsy classifies the pipeline-level cause, debugger pinpoints the code-level fix. The retry agent receives both.

## Data Model

### `diagnosis.json` schema

Stored at `.speed/features/<name>/tasks/<id>/diagnosis.json`, produced by the autopsy agent.

```json
{
  "task_id": "string",
  "timestamp": "ISO 8601",
  "agent_model": "string",
  "attempt": 1,

  "root_cause": "turn_exhaustion | gate_failure | context_cut | exploration_death | spec_gap | decomposition_error | agent_crash | undiagnosable",
  "evidence": "string — human-readable explanation with specific numbers",

  "criteria_analysis": {
    "total": 12,
    "addressed": 11,
    "missed": 1,
    "details": [
      {
        "criterion": "string — the acceptance criterion text",
        "status": "addressed | missed | unclear",
        "evidence": "string — what in the diff supports this assessment"
      }
    ]
  },

  "spec_divergences": [
    {
      "description": "string — what diverged",
      "spec_requires": "string — what the spec says",
      "implementation_uses": "string — what the code does",
      "file": "string — where in the diff",
      "line": 0
    }
  ],

  "salvageable": true,
  "salvage_ref": "string — git ref or branch name for the salvaged commit, null if not salvageable",
  "salvage_stats": {
    "lines_added": 504,
    "files_changed": 2
  },

  "recommended_budget": 75,
  "budget_rationale": "string — why this budget (e.g., '50% increase from exhausted 50')",

  "retry_context": "string — synthesized natural-language context for the retry agent prompt"
}
```

### Root cause taxonomy

Extends `failure_classify.py` with two new classes:

| Root cause | Category | Trigger | Current handling |
|-----------|----------|---------|------------------|
| `turn_exhaustion` | pipeline | Agent hit turn limit, work exists in worktree | **New.** Currently falls through to `unclassified/unknown`. |
| `gate_failure` | complexity | Gates ran and failed on committed code | Overlaps with existing `implementation_error`. Autopsy uses this label when the debugger should handle code fixes. |
| `context_cut` | pipeline | Budget cut files the agent needed | Existing rule 1 in `failure_classify.py`. Autopsy enriches with criteria analysis. |
| `exploration_death` | pipeline | 80%+ turns spent reading, <10% producing code | Existing rule 2. Autopsy enriches with specific files explored. |
| `spec_gap` | pipeline | Spec doesn't define required behavior | Existing rule 4. Autopsy enriches with the specific ambiguous criterion. |
| `decomposition_error` | pipeline | Undeclared files > declared files | Existing rule 3. Autopsy enriches with cluster analysis. |
| `agent_crash` | pipeline | Process died without completion marker | **New.** Currently reported as "Agent process crashed" but not classified. |
| `undiagnosable` | unknown | Insufficient signal to determine cause | Replaces `unclassified/unknown` with an explicit label and partial evidence. |

### Directory structure

```
.speed/features/<name>/tasks/<id>/
  task.json                    # Existing — task definition
  diagnosis.json               # NEW — autopsy output
  context/                     # Existing — Layer 2 context package
    budget.json                # Existing — token budget and cuts
```

## Autopsy Agent Definition

New file: `agents/autopsy.md`

The agent receives a structured prompt with four artifact sections and produces `diagnosis.json`. It is read-only. No file writes, no shell commands, no tool use beyond reading the provided artifacts.

### Input (assembled by `context_assemble_autopsy` in Layer 3)

```markdown
## Failed Task: {title}

### Task Specification
{task description}
{acceptance criteria — structured, with [verify: ...] tags}

### Agent Log (last {N} turns)
{truncated agent conversation log — last 20 turns or full log if shorter}

### Worktree Diff
{git diff of salvaged/committed changes, or "No changes in worktree" if empty}

### Gate Output
{gate results JSON, or "Gates did not run" if gate output directory is empty}

### Turn Usage
Turns used: {actual} / {budget}
Budget exhausted: {yes/no}

### Failure Classification (existing)
{output from failure_classify.py, including class/subclass/evidence}
```

### Output

The agent outputs `diagnosis.json` matching the schema above. The assembly function parses the JSON from the agent's response (same extraction pattern as the debugger and reviewer agents).

### Model selection

Use `MODEL_SUPPORT` (sonnet). The task is structured reading and pattern matching across four artifacts. The agent doesn't generate code or make creative decisions. Sonnet handles this at 5-10x lower cost than opus.

If the agent log exceeds 100K characters, truncate to the last 20 turns with a header noting how many turns were omitted.

## Implementation

### 1. New root cause: `turn_exhaustion` in `failure_classify.py`

Add as rule 0 (highest priority, checked before context_cut):

```python
def _check_turn_exhaustion(agent_output: str, task: dict) -> dict | None:
    """Agent hit turn limit with work present."""
    if not agent_output:
        return None

    # Check for max-turns signal in agent output
    hit_limit = bool(re.search(
        r"Reached max turns|max.turns.reached|turn limit|budget exhausted",
        agent_output,
        re.IGNORECASE,
    ))
    if not hit_limit:
        return None

    return {
        "class": "pipeline",
        "subclass": "turn_exhaustion",
        "evidence": "Agent hit turn limit. Work may exist in worktree.",
    }
```

Insert before rule 1 (context_cut) in `classify_failure()`. Turn exhaustion is checked first because context cuts and exploration death are secondary causes when the primary problem is budget.

### 2. New root cause: `agent_crash` in `failure_classify.py`

Add detection in the existing crash handling in `run.sh` (line ~385). Currently logs "Agent process crashed" but the classification call at line 520 receives an empty agent output, so no rule matches.

Pass a crash signal to `classify_failure`:

```python
def _check_agent_crash(agent_output: str, task: dict) -> dict | None:
    """Process died without completion marker."""
    if "SPEED_AGENT_CRASH" in agent_output:
        return {
            "class": "pipeline",
            "subclass": "agent_crash",
            "evidence": "Agent process terminated without completion marker (crash/OOM/SIGKILL)",
        }
    return None
```

In `run.sh`, when the crash is detected (line ~384), prepend `SPEED_AGENT_CRASH` to the agent output string passed to classification.

### 3. Autopsy trigger in `run.sh`

After `_classify_task_failure` and `_invoke_debugger`, add `_invoke_autopsy`:

```bash
_invoke_autopsy() {
    local task_id="$1"
    local task_json
    task_json=$(task_get "$task_id")
    local title branch
    title=$(echo "$task_json" | jq -r '.title')
    branch=$(echo "$task_json" | jq -r '.branch')

    # Gather artifacts
    local agent_log=""
    local log_file="${LOGS_DIR}/${task_id}.log"
    if [[ -f "$log_file" ]]; then
        local total_lines
        total_lines=$(wc -l < "$log_file" | tr -d ' ')
        if [[ "$total_lines" -le 2000 ]]; then
            agent_log=$(cat "$log_file")
        else
            # Last 2000 lines with omission note
            local omitted=$(( total_lines - 2000 ))
            agent_log="[${omitted} earlier lines omitted]"$'\n'
            agent_log+=$(tail -2000 "$log_file")
        fi
    fi

    local diff=""
    if git_branch_exists "$branch" 2>/dev/null; then
        diff=$(_git diff "$(git_main_branch)...${branch}" 2>/dev/null | head -"$DIFF_HEAD_LINES" || echo "No diff")
    fi

    # Assemble autopsy context via Layer 3
    local task_file_path="${TASKS_DIR}/${task_id}.json"
    local autopsy_prompt
    autopsy_prompt=$(context_assemble_autopsy \
        "$task_file_path" \
        "$agent_log" \
        "$diff" 2>/dev/null) || autopsy_prompt=""

    if [[ -z "$autopsy_prompt" ]]; then
        log_warn "Task ${task_id}: autopsy context assembly failed, skipping"
        return 0
    fi

    # Run autopsy agent (read-only, support model)
    local diagnosis_output
    diagnosis_output=$(run_agent \
        "$MODEL_SUPPORT" \
        "$autopsy_prompt" \
        "agents/autopsy.md" \
        "$DEFAULT_AGENT_TIMEOUT" \
        2>/dev/null) || {
        log_warn "Task ${task_id}: autopsy agent failed"
        return 0
    }

    # Extract JSON from agent output
    local diagnosis_json
    diagnosis_json=$(_extract_json "$diagnosis_output") || {
        log_warn "Task ${task_id}: could not parse autopsy JSON"
        return 0
    }

    # Write diagnosis.json
    local diagnosis_path
    diagnosis_path="${TASKS_DIR}/${task_id}/diagnosis.json"
    mkdir -p "$(dirname "$diagnosis_path")"
    echo "$diagnosis_json" > "$diagnosis_path"

    # Log summary
    local root_cause
    root_cause=$(echo "$diagnosis_json" | jq -r '.root_cause // "unknown"' 2>/dev/null)
    local criteria_addressed
    criteria_addressed=$(echo "$diagnosis_json" | jq -r '.criteria_analysis.addressed // "?"' 2>/dev/null)
    local criteria_total
    criteria_total=$(echo "$diagnosis_json" | jq -r '.criteria_analysis.total // "?"' 2>/dev/null)

    log_step "Task ${task_id}: autopsy complete — ${root_cause} (${criteria_addressed}/${criteria_total} criteria addressed)"
}
```

Call site in `run.sh`, after `_invoke_debugger`:

```bash
# Invoke debugger for code-level diagnosis
_invoke_debugger "$task_id"

# Invoke autopsy for pipeline-level diagnosis
_invoke_autopsy "$task_id"
```

### 4. Layer 3 assembly: `context_assemble_autopsy`

New function in `lib/context/assembly.py`:

```python
def assemble_autopsy(
    task_file: str,
    agent_log: str,
    diff: str,
) -> str:
    """Assemble autopsy context for the Autopsy agent.

    Source: Task JSON + agent log + worktree diff + gate results.

    Args:
        task_file: path to task JSON file
        agent_log: agent conversation log (possibly truncated)
        diff: git diff of the task's branch vs main

    Returns:
        Markdown string for the autopsy agent prompt.
    """
```

Reads the task JSON for: title, description, acceptance_criteria, files_touched, branch, failure_classification, max_turns. Reads gate output from the task's log directory. Assembles the structured prompt described in the agent definition section above.

### 5. Prescriptive retry: modify `speed retry`

`lib/cmd/retry.sh` currently:
1. Reads the task JSON
2. Optionally accepts `--context` from the operator
3. Resets the task to `pending`
4. Re-runs with the same or escalated model

After this change:
1. Reads the task JSON
2. Checks for `diagnosis.json` at `.speed/features/<name>/tasks/<id>/diagnosis.json`
3. If diagnosis exists:
   - Reads `retry_context` from the diagnosis
   - Reads `recommended_budget` and uses it as the turn limit
   - Reads `salvage_ref` and includes a reference to the salvaged diff
   - Synthesizes a combined context: diagnosis retry_context + operator `--context` (if provided)
4. If no diagnosis: falls back to current behavior (operator `--context` only)
5. Resets the task to `pending`
6. Re-runs with the combined context and adjusted budget

The operator's `--context` is appended after the diagnosis context, never replacing it. If the operator wants to override the diagnosis entirely, they can use `--no-diagnosis` to skip it.

### 6. Budget adjustment

When `diagnosis.json` has `root_cause: turn_exhaustion`:
- `recommended_budget` = previous budget * 1.5 (rounded up)
- The retry command passes this as `--max-turns` to the agent runner
- If the task exhausts this budget again, the next retry increases by another 50% (compounding), up to a hard cap of 200 turns

Budget cap rationale: a task that can't complete in 200 turns is either badly decomposed or genuinely beyond single-agent capability. Escalation (replan or human intervention) is appropriate at that point.

### 7. Diagnosis in `speed status`

When a failed task has `diagnosis.json`, `speed status` shows:

```
Task 3: FAILED — turn_exhaustion (11/12 criteria addressed)
  Evidence: Agent reached 50/50 turns. 504 lines salvaged.
  Divergence: uses LOGS_DIR, spec requires STATE_DIR/features/.../
  Recommended: speed retry --task-id 3 (budget: 75 turns)
```

Instead of the current:

```
Task 3: FAILED — Quality gates failed
```

Read `diagnosis.json` from the task directory. Fall back to the existing display when no diagnosis exists.

## Error Handling

| Condition | Behavior |
|-----------|----------|
| Autopsy agent fails (timeout, parse error, crash) | Log warning, skip diagnosis. Task remains failed with existing classification. Retry still works with manual `--context`. |
| Agent log is empty | Autopsy runs with reduced signal. `criteria_analysis` and `spec_divergences` may be empty. Root cause is likely `agent_crash` or `undiagnosable`. |
| Agent log exceeds 100K chars | Truncate to last 2000 lines with omission header. |
| No gate output directory | Evidence includes "Gates did not run." Distinguishes turn exhaustion (budget ran out before gates) from gate failure. |
| No salvaged code (worktree was clean) | `salvageable: false`, `salvage_ref: null`. Retry proceeds without salvaged code reference. |
| `diagnosis.json` already exists from a previous attempt | Overwritten. `attempt` field increments. Previous diagnosis is not preserved (the task JSON already tracks attempt history). |
| `--no-diagnosis` flag on retry | Skip reading `diagnosis.json`. Use only operator `--context`. |

## Files Changed

| File | Change |
|------|--------|
| `agents/autopsy.md` | **New.** Agent definition with mission, input format, output schema, and guidelines. |
| `lib/failure_classify.py` | Add `_check_turn_exhaustion` (rule 0) and `_check_agent_crash`. Update rule ordering in `classify_failure()`. |
| `lib/cmd/run.sh` | Add `_invoke_autopsy()` function. Call after `_invoke_debugger` in the failure handling block. Pass crash signal for agent_crash classification. |
| `lib/context/assembly.py` | Add `assemble_autopsy()` function for Layer 3 prompt assembly. |
| `lib/context_bridge.sh` | Add `context_assemble_autopsy` bridge function calling the Python assembly. |
| `lib/cmd/retry.sh` | Read `diagnosis.json` for retry context, budget adjustment, salvage reference. Add `--no-diagnosis` flag. |
| `lib/cmd/status.sh` | Read `diagnosis.json` for enhanced failure display. |

## Dependencies

| Dependency | Required? | Impact if missing |
|------------|-----------|-------------------|
| Turn exhaustion salvage (`fix-turn-exhaustion-loses-work.md`) | Recommended | Without salvage, autopsy analyzes empty diffs for turn-exhausted tasks. Diagnosis is less useful (no criteria analysis, no spec divergence detection). The classification still works. |
| `jq` | Yes (existing) | Already required by SPEED. Used for reading/writing diagnosis JSON. |
| Existing debugger (`agents/debugger.md`) | No | Autopsy and debugger are independent. Both can run. Neither depends on the other's output. |

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Separate agent vs. extending the debugger | Separate agent | Different focus (pipeline vs. code), different inputs (full turn log vs. error output), different outputs (diagnosis vs. fix). Combining them overloads the debugger's purpose and doubles its prompt size. |
| Support model vs. planning model | Support model (sonnet) | Structured pattern matching across artifacts, not creative reasoning. 5-10x cost reduction. Acceptable accuracy trade-off for a diagnostic task. |
| Autopsy runs after debugger, not instead of | Both run | Gate failures need code-level diagnosis (debugger) AND pipeline-level diagnosis (autopsy). Turn exhaustion only needs autopsy. Running both covers all cases. |
| Turn budget 50% increase, not 100% or fixed | 50% per retry, cap at 200 | 50% gives enough headroom for near-completions without doubling cost. Cap at 200 prevents runaway spending on badly decomposed tasks. |
| Overwrite previous diagnosis on re-attempt | Overwrite | Simplicity. The relevant diagnosis is always the most recent. Task JSON already has attempt history for post-hoc analysis. |
| `--no-diagnosis` escape hatch | Include | Operator may know the diagnosis is wrong and want a clean retry. Additive `--context` handles most cases, but a full override should be available. |
