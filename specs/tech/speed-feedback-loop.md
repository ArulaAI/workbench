# RFC: SPEED Feedback Loops

> See [product spec](../product/speed-feedback-loop.md) for product context.
> Depends on: Existing SPEED pipeline (`speed/speed`, `gates.sh`, `grounding.sh`, `developer.md`)

## `speed gates` CLI Command

### Command signature

```bash
./speed/speed gates --task <id> [--fast | --full] [--worktree <path>]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--task <id>` | required | Task ID — used to resolve subsystem from `files_touched` and locate the task's worktree |
| `--fast` | (default) | Lint + typecheck only. Skips tests. |
| `--full` | | Lint + typecheck + tests. |
| `--worktree <path>` | auto-resolved | Override worktree path. If omitted, resolved from `${WORKTREES_DIR}/task-${task_id}`. Falls back to `${PROJECT_ROOT}`. |

### `cmd_gates()` implementation

Added to `speed/speed` alongside other `cmd_*()` functions. Reuses existing gate infrastructure — no new gate logic.

```
cmd_gates()
├── _require_feature "$GLOBAL_FEATURE"  # standard pattern — resolves TASKS_DIR, LOGS_DIR, WORKTREES_DIR
├── Parse flags: --task, --fast/--full, --worktree
├── Resolve worktree path:
│   └── --worktree flag > ${WORKTREES_DIR}/task-${id} > ${PROJECT_ROOT}
├── _detect_subsystem(task_id)          # existing function in gates.sh
├── If --fast:
│   ├── gate_syntax_check(task_id, worktree_path)
│   ├── gates_get_config("lint", subsystem)     → gate_run_command() for each
│   └── gates_get_config("typecheck", subsystem) → gate_run_command() for each
├── If --full:
│   └── gates_run(task_id, worktree_path)       # existing function — runs grounding + all quality gates
├── Print results (reuses existing gate output format)
└── Exit code: 0 = all pass, 1 = any fail
```

Key design decisions:
- `--fast` is the default because agents call it frequently (after each file group). Fast must be cheap.
- `--full` delegates to `gates_run()` directly — no parallel code path. One source of truth for what "all gates pass" means.
- `--fast` does NOT run grounding gates (those check branch diffs, which aren't meaningful mid-task before the final commit).
- Follows the standard `_require_feature "$GLOBAL_FEATURE"` pattern. The task message template includes `-f <feature>` so the Developer Agent passes the feature context when calling `speed gates`.

### Machine-readable output

Gate results are printed to stderr (human-readable, same format as post-hoc gates). The exit code is the machine-readable signal:

- Exit 0 → all gates passed
- Exit 1 → one or more gates failed

The agent reads the exit code to decide whether to proceed or fix. Detailed output goes to log files via `gate_run_command()` (existing behavior).

### Subsystem detection

Reuses `_detect_subsystem()` from `gates.sh`:
1. Reads `files_touched` from `${TASKS_DIR}/${task_id}.json`
2. Matches against `TOML_SUBSYSTEMS` (if configured) or hardcoded prefixes (`src/frontend/*`, `src/backend/*`, `src/plugins/*`)
3. Returns `"frontend"`, `"backend"`, `"plugin"`, or `"both"`

This determines which gate commands from CLAUDE.md's `## Quality Gates` section are executed.

### Worktree support

`cmd_gates()` resolves the worktree path and passes it to `gate_run_command()` as the `gate_cwd` argument. The existing `gate_run_command()` already supports this:
- It `cd`s into `gate_cwd` before running commands
- It activates venv/node_modules relative to the target directory
- Syntax check reads files from the worktree path

No changes needed in `gate_run_command()`.

## Developer Agent Prompt Enhancement

### New section in `developer.md`

Replace the current vague "Write tests" instruction (step 3 bullet under "Implement incrementally") with an explicit "Quality Checks" section:

```markdown
## Quality Checks

Run quality gates iteratively as you work. Do not wait until the end.

### After writing each group of files:
```
./speed/speed gates -f {feature_name} --task {task_id} --fast
```
This runs lint + typecheck for your subsystem. Fix any errors before continuing.

### Before declaring done:
```
./speed/speed gates -f {feature_name} --task {task_id} --full
```
This runs lint + typecheck + tests. All gates must pass before you output your completion JSON.

### If gates fail:
1. Read the error output
2. Fix the issue in your code
3. Re-run the gate
4. Do not declare done until gates pass

Do NOT skip these checks. Your output log is audited for gate invocations.
```

The `{task_id}` placeholder is filled by `cmd_run()` when building the task message (see below).

### Task message template update in `cmd_run()`

The `agent_message` variable in `cmd_run()` (around line 1402 in `speed/speed`) is updated to include the task ID for gate commands:

Current:
```
### Git Branch
You are working on branch: `${branch}`
You are already on this branch in an isolated worktree. Do NOT run git checkout.
Commit your work to this branch.${extra_context}

### Working Directory
${worktree_path}
```

Updated:
```
### Git Branch
You are working on branch: `${branch}`
You are already on this branch in an isolated worktree. Do NOT run git checkout.
Commit your work to this branch.${extra_context}

### Quality Checks
Run gates iteratively as you work:
- After each group of files: `./speed/speed gates -f ${feature_name} --task ${task_id} --fast`
- Before declaring done: `./speed/speed gates -f ${feature_name} --task ${task_id} --full`
All gates must pass before you output your completion JSON.

### Working Directory
${worktree_path}
```

This puts copy-pasteable commands directly in the task message. The agent doesn't need to construct them.

## Grounding Gate: Test File Coverage

### `grounding_check_test_coverage()`

Added to `speed/lib/grounding.sh`. Runs as part of `grounding_run()`.

**Logic:**

1. Get the branch diff: `git diff main...<branch> --name-only`
2. Filter to new files only (files that don't exist on main): `git diff main...<branch> --diff-filter=A --name-only`
3. Filter to source files that should have tests (see inclusion/exclusion below)
4. For each source file, check if a corresponding test file exists in the diff
5. If any source file is missing its test counterpart → hard failure

**Source-to-test file mapping:**

| Source file | Expected test file |
|------------|-------------------|
| `src/frontend/components/features/widget.tsx` | `src/frontend/components/features/widget.test.tsx` |
| `src/frontend/hooks/use-auth.ts` | `src/frontend/hooks/use-auth.test.ts` |
| `src/backend/app/models/user.py` | `src/backend/app/models/user_test.py` or `tests/test_user.py` |
| `src/backend/app/graphql/mutations/tribe.py` | Co-located `*_test.py` or `tests/test_*.py` |

Rule: same directory, same base name with `.test.{ext}` suffix (frontend) or `_test.py` / `test_*.py` (backend). Backend also checks `tests/test_<basename>.py` for the `tests/` directory convention.

**Exclusion patterns (files that don't require tests):**

Source files matching these patterns are skipped:

```
# Config and setup
**/vitest.config.*
**/next.config.*
**/tailwind.config.*
**/.eslintrc.*
**/tsconfig.*
**/setup.ts
**/setup.js

# Type definitions
**/*.d.ts
**/types.ts
**/types/*.ts

# Barrel exports / re-exports
**/index.ts
**/index.tsx

# CSS and assets
**/*.css
**/*.svg
**/*.png
**/*.jpg

# Migrations
**/alembic/**
**/migrations/**

# GraphQL schema (types, not mutations/queries)
**/graphql/types/**

# Test utilities (not themselves tested)
**/test/**
**/tests/**
**/__tests__/**
**/*.test.*
**/*_test.*

# Seed data
**/seed/**

# Layout components (thin wrappers, tested via integration)
**/layout.tsx
**/loading.tsx
**/error.tsx
**/not-found.tsx

# Next.js route segments
**/page.tsx
**/route.ts
```

These patterns are derived from the project conventions in CLAUDE.md:
- `src/frontend/components/ui/` — shadcn primitives, not custom-tested
- `src/frontend/src/test/setup.ts` — test infrastructure
- `src/backend/app/seed/` — seed data
- Alembic migrations — tested by the migration tool itself

**Implementation sketch:**

```bash
grounding_check_test_coverage() {
    local task_id="$1"
    local task_json="${TASKS_DIR}/${task_id}.json"
    local branch
    branch=$(jq -r '.branch // empty' "$task_json")

    # Get newly added files (not modified — only new files need new tests)
    local new_files
    new_files=$(_git diff "$(git_main_branch)...${branch}" --diff-filter=A --name-only 2>/dev/null)

    [[ -z "$new_files" ]] && return 0

    local missing=()

    while IFS= read -r f; do
        [[ -z "$f" ]] && continue

        # Skip excluded patterns
        _test_coverage_excluded "$f" && continue

        # Skip test files themselves
        [[ "$f" == *.test.* ]] && continue
        [[ "$f" == *_test.py ]] && continue
        [[ "$f" == */test_*.py ]] && continue

        # Check for corresponding test file in the diff
        if ! _test_file_exists_in_diff "$f" "$new_files"; then
            missing+=("$f")
        fi
    done <<< "$new_files"

    if [[ ${#missing[@]} -gt 0 ]]; then
        log_error "New source files missing test coverage:"
        for f in "${missing[@]}"; do
            log_error "  ${f}"
        done
        return 1
    fi

    return 0
}
```

**Helper: `_test_coverage_excluded()`**

Checks a file path against the exclusion patterns above. Returns 0 (true) if excluded, 1 if the file should have a test.

**Helper: `_test_file_exists_in_diff()`**

Given a source file and the full diff file list, checks if a matching test file exists:
1. Extract base name and extension
2. Generate expected test file names (co-located `.test.{ext}`, `_test.py`, `tests/test_*.py`)
3. Check if any expected name appears in the diff file list

### Integration into `grounding_run()`

Added as a new check in `grounding_run()` after the existing 5 checks:

```bash
# Check 6: Test file coverage (new source files must have tests)
if grounding_check_test_coverage "$task_id"; then
    results+=("${COLOR_SUCCESS}${SYM_CHECK} Test file coverage${RESET}")
else
    results+=("${COLOR_ERROR}${SYM_CROSS} New source files missing test coverage${RESET}")
    all_passed=false
fi
```

This is a **hard failure** — same severity as "empty diff" or "missing declared files."

## Grounding Gate: Gate Invocation Evidence

### `grounding_check_gate_evidence()`

Added to `speed/lib/grounding.sh`. Runs as part of `grounding_run()`.

**Logic:**

1. Read the agent output log: `${LOGS_DIR}/${task_id}.log`
2. Search for evidence that the agent ran `speed gates`
3. Evidence markers: the gate output format printed by `gates_run()` / `gate_run_command()`:
   - `"Quality Gates:"` (the header printed by `gates_run()`)
   - `"Running quality gates for task"` (the log line from `gates_run()`)
   - `"speed gates"` (the command itself in the agent's bash history)
4. If none of these markers appear in the log → check fails

**Severity: warning (initially).**

This gate starts as a warning, not a hard failure. Rationale:
- Need to verify agents actually comply with the new prompt instructions before making it blocking
- Existing tasks in-flight when this ships won't have the new prompt
- After confirming >80% compliance across a batch of runs, promote to hard failure

**Implementation sketch:**

```bash
grounding_check_gate_evidence() {
    local task_id="$1"
    local output_file="${LOGS_DIR}/${task_id}.log"

    if [[ ! -f "$output_file" ]]; then
        return 1  # No output = can't verify
    fi

    # Look for evidence of gate invocation in agent output
    if grep -q "Quality Gates:" "$output_file" 2>/dev/null || \
       grep -q "Running quality gates for task" "$output_file" 2>/dev/null || \
       grep -q "speed gates" "$output_file" 2>/dev/null; then
        return 0  # Evidence found
    fi

    return 1  # No evidence
}
```

### Integration into `grounding_run()`

Added as Check 7, after test file coverage:

```bash
# Check 7: Gate invocation evidence (agent should have run gates mid-task)
if grounding_check_gate_evidence "$task_id"; then
    results+=("${COLOR_SUCCESS}${SYM_CHECK} Gate invocation evidence${RESET}")
else
    results+=("${COLOR_WARN}${SYM_WARN} No evidence of mid-task gate invocation${RESET}")
    # Warning only — does not set all_passed=false
    # TODO: Promote to hard failure after rollout stabilizes
fi
```

Note: this intentionally does NOT set `all_passed=false`. It's a warning like the scope check (exit code 2 pattern). The warning is visible in output and logged, but doesn't block the task.

## Plan Verification Feedback Loop

### Problem: `cmd_verify()` is broken in three ways

1. **Parser bug**: `cmd_verify()` (line 817) calls `_require_json()` directly on raw agent output. `_require_json()` does a bare `jq empty` check. But the Plan Verifier agent often wraps its JSON in markdown — `---` separators, `**Summary**` text, code fences. The parser fails and reports "invalid JSON" even though the verification succeeded. Meanwhile, `parse_agent_json()` in `provider.sh` already handles code-fence extraction and brace scanning — it just isn't called.

2. **Raw dump as feedback**: `cmd_verify()` does `echo "$verify_output"` (line 809) — dumps the entire agent output verbatim. The verification report has structured fields (`critical_failures`, `recommendations`, `spec_requirements` with statuses) but none are formatted for human consumption.

3. **Dead end on failure**: When `status == "fail"`, the user gets a generic "fix the spec or re-run speed plan" message (lines 831-834). The verifier knows *exactly* what's wrong — which task, which field, what the spec says vs. what the plan says — but this information is not presented actionably. There's no path from the finding to the fix.

### Fix 1: Robust JSON extraction

Replace `_require_json` with `parse_agent_json` in `cmd_verify()`:

```bash
# Current (line 817):
if ! _require_json "Plan Verifier" "$verify_output"; then

# Updated:
verify_json=$(parse_agent_json "$verify_output") || {
    log_error "Plan Verifier returned unparseable output"
    log_error "Review raw output: ${LOGS_DIR}/plan-verification.log"
    exit 1
}
```

This handles JSON wrapped in markdown, code fences, or surrounding prose — the same extraction that already works for the Supervisor, Guardian, and Coherence Checker agents.

### Fix 2: Human-readable verification report

New function `_print_verify_report()` formats the structured JSON into the same visual style as `gates_run()`:

```
cmd_verify()
├── ...existing setup...
├── parse_agent_json(verify_output)
├── _print_verify_report(verify_json)      # NEW
│   ├── Core question: ✓ answerable / ✗ not answerable
│   ├── Spec requirements: "24 of 25 covered"
│   │   └── For each non-covered requirement:
│   │       ├── ✗ requirement text (status: missing/drifted/partial)
│   │       └── "  Spec says: X | Plan says: Y | Task: N"
│   ├── Semantic drift: (if any)
│   │   └── ⚠ "spec_term" → "plan_term": risk
│   ├── Critical failures: (if any)
│   │   └── ✗ description
│   │       └── "  Spec: spec_reference | Gap: plan_gap"
│   ├── Recommendations: (if any)
│   │   └── → recommendation text
│   └── Summary line: "N critical, M warnings, K recommendations"
└── ...fix loop or exit...
```

Output uses the existing color/symbol constants from `colors.sh`: `COLOR_SUCCESS`/`SYM_CHECK` for covered requirements, `COLOR_ERROR`/`SYM_CROSS` for critical failures, `COLOR_WARN`/`SYM_WARN` for drift/partial, `COLOR_DIM` for contextual details.

### Fix 3: Automatic verify → fix → re-verify loop

When verification finds fixable issues, `cmd_verify()` enters an automatic correction loop instead of dumping the report and exiting.

```
cmd_verify()
├── Run Plan Verifier → parse JSON → print report
├── If status == "pass": done
├── If status == "fail":
│   ├── Classify each issue: auto-fixable or needs-human
│   ├── If all issues need human judgment: print actionable guidance, exit
│   ├── If some issues are auto-fixable:
│   │   ├── Spawn Fix Agent with:
│   │   │   ├── Verification report (the JSON)
│   │   │   ├── Task files (from TASKS_DIR)
│   │   │   └── Scoped instruction: "Fix ONLY the listed issues"
│   │   ├── Fix Agent edits task JSON files
│   │   ├── Re-run Plan Verifier
│   │   ├── If pass → print "PASSED (N issues auto-fixed)" + fix summary
│   │   ├── If same issues persist → human escalation (fix didn't work)
│   │   ├── If new issues → one more iteration
│   │   └── Cap at MAX_VERIFY_FIX_ITERATIONS (3)
│   └── Print summary of all auto-applied fixes
```

### Fix Agent

The Fix Agent is not a new agent definition — it's an inline `claude_run()` call within `cmd_verify()`, similar to how `cmd_plan()` runs the Architect inline. No separate `.md` file.

**Model:** `MODEL_SUPPORT` (sonnet) — these are mechanical edits, not reasoning tasks.

**Tools:** `AGENT_TOOLS_WRITE` (`Read Write Glob`) — needs to read task files, write edits, find files. No Bash or Edit access.

**Prompt template:**

```
## Verification Failures

${verify_json}

## Task Files

Directory: ${TASKS_DIR}/
Files: ${task_file_list}

## Instructions

Apply ONLY the fixes described in the critical_failures and recommendations above.
For each fix:
1. Read the task JSON file
2. Find the specific field that needs changing
3. Rewrite it using the Write tool
4. Do NOT change anything else in the task file

If a fix is ambiguous — multiple valid approaches, or the issue describes a design
decision rather than a factual error — do NOT fix it. Instead, output it in your
"needs_human" list.

## Output

{
  "fixes_applied": [
    {
      "task_id": "1",
      "file": ".speed/features/speed-audit/tasks/1.json",
      "field": "description",
      "before": "> 10 tasks",
      "after": "> 8 tasks",
      "reason": "L4 sizing threshold: spec says > 8, plan said > 10"
    }
  ],
  "needs_human": [
    {
      "task_id": "2",
      "issue": "Architect RFC review output format — spec says { approved, issues } but plan maps to existing validation severity. Both are valid.",
      "options": ["Use spec's { approved, issues } format", "Keep existing validation severity mapping"]
    }
  ]
}
```

### Human escalation format

When the Fix Agent reports `needs_human` items, or when auto-fix fails, `cmd_verify()` prints actionable guidance:

```
Cannot auto-fix — requires your judgment:

  Task 2 (.speed/features/speed-audit/tasks/2.json):
    Issue: Architect RFC review output format drifted from spec
    Spec says: "{ approved: true/false, issues: [...] } format"
    Plan says: "validation array with severity: critical"
    Options:
      1. Use spec's format (edit Task 2 description)
      2. Keep plan's approach (functionally equivalent)

After fixing, run: speed verify
```

This gives the operator everything they need: which file, what's wrong, what the choices are, and what to do next.

### Iteration cap and convergence

- `MAX_VERIFY_FIX_ITERATIONS=3` — hard cap to prevent infinite loops
- Convergence detection: if re-verification finds the *same* critical failures after a fix attempt, the Fix Agent failed. Stop and escalate rather than retrying the same fix.
- New issues (not in the previous report) get one more fix iteration. This handles cascading fixes where fixing issue A reveals issue B.

### Constants

```bash
MAX_VERIFY_FIX_ITERATIONS=3    # max fix → re-verify cycles
```

Added to `config.sh` alongside existing orchestration tuning constants.

## Reviewer: Smart Spec Loader

### Problem

`cmd_review()` loads every `.md` file under `specs/` into every review prompt (lines 2813-2824 in `speed/speed`). For this project that's 15+ specs totaling ~288KB (~70k tokens). The reviewer only needs specs relevant to the code being reviewed.

### Solution: Two-layer grep

Replace the `find specs/ -name '*.md'` dump with a targeted loader that greps spec file contents against the diff.

```
_load_relevant_specs(diff_text, primary_spec_path)
├── Always include the feature's own spec (primary_spec_path)
├── Layer 1: File path matching
│   ├── Extract file paths from diff (grep '^[+-]{3} [ab]/' or --name-only)
│   ├── For each spec file in specs/:
│   │   └── grep -l any of the diff file paths → include
├── Layer 2: Function/feature name matching
│   ├── Extract identifiers from diff (function names, class names, imports)
│   │   └── grep -oE '[a-zA-Z_][a-zA-Z0-9_]{4,}' from diff, deduplicated
│   ├── For each remaining spec file:
│   │   └── grep -l any of the identifiers → include
├── Deduplicate results
└── Return list of spec file paths
```

**Key design decisions:**
- All bash — no LLM needed. `grep -l` is fast enough even for 20+ spec files.
- False positives are fine — loading one extra spec is far better than missing a relevant one.
- The feature's own spec is always included, bypassing grep.
- Layer 1 (file paths) catches most cases. Layer 2 (identifiers) catches cross-cutting concerns like shared utilities referenced by name in specs.
- Minimum identifier length of 5 chars avoids noise from common short words.

### Implementation

New function `_load_relevant_specs()` in `speed/speed`, called by `cmd_review()`:

```bash
_load_relevant_specs() {
    local diff_text="$1"
    local primary_spec="$2"
    local specs_dir="${PROJECT_ROOT}/speed/specs"
    local result=""

    # Always include primary spec
    if [[ -n "$primary_spec" ]] && [[ -f "$primary_spec" ]]; then
        result="$primary_spec"
    fi

    [[ ! -d "$specs_dir" ]] && echo "$result" && return 0

    # Layer 1: file paths from diff
    local diff_paths
    diff_paths=$(echo "$diff_text" | grep -oE '(src|speed|lib)/[^ ]+' | sort -u)

    # Layer 2: identifiers (function names, class names) — 5+ chars
    local identifiers
    identifiers=$(echo "$diff_text" | grep -oE '[a-zA-Z_][a-zA-Z0-9_]{4,}' | sort -u | head -100)

    while IFS= read -r -d '' sf; do
        # Skip primary spec (already included)
        [[ -n "$primary_spec" ]] && [[ "$(realpath "$sf")" == "$(realpath "$primary_spec")" ]] && continue

        local matched=false

        # Layer 1: check if any diff file path appears in spec
        if [[ -n "$diff_paths" ]]; then
            while IFS= read -r dp; do
                [[ -z "$dp" ]] && continue
                if grep -q "$dp" "$sf" 2>/dev/null; then
                    matched=true
                    break
                fi
            done <<< "$diff_paths"
        fi

        # Layer 2: check if any identifier appears in spec
        if [[ "$matched" == "false" ]] && [[ -n "$identifiers" ]]; then
            while IFS= read -r id; do
                [[ -z "$id" ]] && continue
                if grep -q "$id" "$sf" 2>/dev/null; then
                    matched=true
                    break
                fi
            done <<< "$identifiers"
        fi

        [[ "$matched" == "true" ]] && result+=$'\n'"$sf"
    done < <(find "$specs_dir" -name '*.md' -type f -print0 | sort -z)

    echo "$result"
}
```

### Integration into `cmd_review()`

Replace lines 2813-2824 (the `find specs/ ... cat` loop) with:

```bash
# Gather relevant specs (not all specs)
local relevant_specs
relevant_specs=$(_load_relevant_specs "$diff" "$spec_file")
local spec_context=""
while IFS= read -r sf; do
    [[ -z "$sf" ]] && continue
    local relpath="${sf#${PROJECT_ROOT}/}"
    if [[ -n "$spec_file" ]] && [[ "$(realpath "$sf")" == "$(realpath "$spec_file")" ]]; then
        spec_context+="
### Product Specification (SOURCE OF TRUTH)
$(cat "$sf")"
    else
        spec_context+=$'\n\n'"--- RELATED SPEC: ${relpath} ---"$'\n'"$(cat "$sf")"
    fi
done <<< "$relevant_specs"
```

## Reviewer: Diff Truncation

### Problem

`cmd_review()` sends the full `git diff` with no size limit. `DIFF_HEAD_LINES=500` exists in `config.sh` but is only applied by the Guardian.

### Solution

Apply `DIFF_HEAD_LINES` truncation in `cmd_review()` after fetching the diff:

```bash
# Truncate diff if too long
local diff_lines
diff_lines=$(echo "$diff" | wc -l)
if [[ $diff_lines -gt $DIFF_HEAD_LINES ]]; then
    diff=$(echo "$diff" | head -n "$DIFF_HEAD_LINES")
    diff+=$'\n'"... (truncated at ${DIFF_HEAD_LINES} lines — full diff on branch ${branch})"
fi
```

Inserted after line 2797 (where `diff` is fetched) and before line 2826 (where `agent_message` is built).

Same pattern the Guardian uses at line ~1899. One config value `DIFF_HEAD_LINES=500` for both.

## Token Budget and Rate Limit Handling

### Problem

SPEED has no awareness of Claude's API rate limits. It fires requests as fast as it can with no tracking or pacing. Claude Code CLI limits are TPM-based (200k-300k for 1-5 users) with a rolling 5-hour window.

### Config additions (`config.sh`)

```bash
# ── Token Budget ────────────────────────────────────────────────
TPM_BUDGET="${SPEED_TPM_BUDGET:-${TOML_RATE_TPM_BUDGET:-200000}}"  # tokens per minute
RPM_BUDGET="${SPEED_RPM_BUDGET:-${TOML_RATE_RPM_BUDGET:-5}}"       # requests per minute
RATE_LIMIT_MAX_RETRIES=3       # max retries on rate limit error
RATE_LIMIT_BASE_DELAY=60       # base delay in seconds for backoff
RATE_LIMIT_MAX_DELAY=300       # max delay cap (5 minutes)
```

Defaults are conservative (200k TPM, 5 RPM) — safe for the 1-5 user tier. Operators on higher tiers can increase via env vars or `speed.toml`.

### Token estimation

Claude Code CLI doesn't expose token counts in its output. We estimate from character count:

```bash
# ~4 characters per token (rough heuristic, errs on the high side)
_estimate_tokens() {
    local text="$1"
    local chars=${#text}
    echo $(( (chars + 3) / 4 ))
}
```

This is intentionally imprecise. The goal is pacing, not exact accounting. We include 20% headroom in the budget check.

### Token tracker (state file)

Track cumulative usage in a temp file per pipeline run:

```bash
_TOKEN_TRACKER="${TMPDIR:-/tmp}/_speed_tokens_$$"

_track_tokens() {
    local estimated="$1"
    local now
    now=$(date +%s)
    echo "${now} ${estimated}" >> "$_TOKEN_TRACKER"
}

_tokens_used_last_minute() {
    local now cutoff total=0
    now=$(date +%s)
    cutoff=$((now - 60))
    while IFS=' ' read -r ts tokens; do
        [[ $ts -ge $cutoff ]] && total=$((total + tokens))
    done < "$_TOKEN_TRACKER" 2>/dev/null
    echo "$total"
}

_requests_last_minute() {
    local now cutoff count=0
    now=$(date +%s)
    cutoff=$((now - 60))
    while IFS=' ' read -r ts _; do
        [[ $ts -ge $cutoff ]] && count=$((count + 1))
    done < "$_TOKEN_TRACKER" 2>/dev/null
    echo "$count"
}
```

### Pre-flight check and pacing

Before each API call, check if we have budget:

```bash
_pace_api_call() {
    local estimated_tokens="$1"

    while true; do
        local used rpm
        used=$(_tokens_used_last_minute)
        rpm=$(_requests_last_minute)
        local headroom=$(( TPM_BUDGET * 80 / 100 ))  # 80% threshold

        if [[ $((used + estimated_tokens)) -lt $headroom ]] && [[ $rpm -lt $RPM_BUDGET ]]; then
            return 0  # safe to proceed
        fi

        local wait_secs=15
        log_dim "Pacing: ${used}/${TPM_BUDGET} TPM, ${rpm}/${RPM_BUDGET} RPM — waiting ${wait_secs}s"
        sleep "$wait_secs"
    done
}
```

### Rate limit retry with backoff

Wrap the `claude_run()` call with retry logic for rate limit errors:

```bash
_call_with_retry() {
    # $@ = full claude_run argument list
    local attempt=0
    local delay=$RATE_LIMIT_BASE_DELAY

    while [[ $attempt -lt $RATE_LIMIT_MAX_RETRIES ]]; do
        local output=""
        local rc=0
        output=$("$@") || rc=$?

        # Check for rate limit in output
        if echo "$output" | grep -qi "rate limit" 2>/dev/null; then
            attempt=$((attempt + 1))
            if [[ $attempt -ge $RATE_LIMIT_MAX_RETRIES ]]; then
                echo "$output"
                return 1
            fi
            log_warn "Rate limit reached — waiting ${delay}s before retry (attempt ${attempt}/${RATE_LIMIT_MAX_RETRIES})"
            sleep "$delay"
            delay=$(( delay * 2 ))
            [[ $delay -gt $RATE_LIMIT_MAX_DELAY ]] && delay=$RATE_LIMIT_MAX_DELAY
            continue
        fi

        # Check for "prompt too long" — not retryable, fail immediately
        if echo "$output" | grep -qi "prompt.*too long\|too long.*prompt" 2>/dev/null; then
            log_error "Prompt too long — reduce context size"
            echo "$output"
            return 1
        fi

        echo "$output"
        return $rc
    done
}
```

### Integration into `cmd_review()`

```bash
# Before the claude_run call:
local prompt_text="${agent_message}"
local estimated
estimated=$(_estimate_tokens "$prompt_text")
_pace_api_call "$estimated"

# Replace direct claude_run with:
review_output=$(_call_with_retry claude_run \
    "${AGENTS_DIR}/reviewer.md" \
    "$agent_message" \
    "$MODEL_SUPPORT" \
    "$AGENT_TOOLS_READONLY" \
    "Reviewer")

# After successful call:
_track_tokens "$estimated"
```

### Where to put the functions

- `_estimate_tokens`, `_tokens_used_last_minute`, `_requests_last_minute`, `_pace_api_call`, `_track_tokens` → `speed/lib/provider.sh` (next to the existing provider abstraction)
- `_call_with_retry` → `speed/lib/provider.sh` (wraps `claude_run`)
- Config constants → `speed/lib/config.sh`
- `_load_relevant_specs` → `speed/speed` (local to the review flow)

## Reviewer: Nit Summary and Aggregation

### Problem

When the reviewer approves a task, it may still include `nit` or `minor` severity issues in its structured output. These findings are written to the review log JSON but never surfaced to the operator. The operator sees "Task 3: approved by Reviewer" and moves on. Across a batch of 5 tasks, 10-15 minor issues accumulate silently.

### Solution

Collect nit/minor issues from all approved tasks during `cmd_review()` and print an aggregated summary at the end.

### `_print_review_nits()` function

Added before `cmd_review()` in `speed/speed`:

```bash
_print_review_nits() {
    local nits_json="$1"
    local count
    count=$(echo "$nits_json" | jq 'length' 2>/dev/null) || count=0

    [[ "$count" == "0" ]] || [[ -z "$count" ]] && return 0

    # Save to file
    echo "$nits_json" | jq '.' > "${LOGS_DIR}/review-nits.json"

    # Print summary
    echo ""
    echo -e "  ${BOLD}Review Nits (${count} items across approved tasks):${RESET}"
    echo ""

    echo "$nits_json" | jq -r '.[] | "\(.task_id): \(.severity) — \(.message // .description // "no message") (\(.file // "?"):\(.line // "?"))"' 2>/dev/null | while IFS= read -r line; do
        echo -e "    ${COLOR_WARN}${SYM_WARN}${RESET} ${line}"
    done

    echo ""
    echo -e "  ${COLOR_DIM}Full details: ${LOGS_DIR}/review-nits.json${RESET}"
}
```

### Integration into `cmd_review()`

1. Initialize `local all_nits="[]"` before the review loop
2. After each approved task, extract nit/minor issues and append:
   ```bash
   local task_nits
   task_nits=$(echo "$parsed_review" | jq -c --arg tid "$tid" --arg title "$title" \
       '[.issues[]? | select(.severity == "nit" or .severity == "minor") | . + {task_id: $tid, task_title: $title}]' 2>/dev/null) || task_nits="[]"
   if [[ "$task_nits" != "[]" ]] && [[ -n "$task_nits" ]]; then
       all_nits=$(echo "$all_nits" "$task_nits" | jq -s 'add')
   fi
   ```
3. After the review loop, call `_print_review_nits "$all_nits"`

### Output example

```
  Review Nits (3 items across approved tasks):

    ⚠ 1: nit — Unused import 'os' (speed/lib/gates.sh:14)
    ⚠ 3: minor — Consider extracting helper for repeated pattern (speed/speed:892)
    ⚠ 3: nit — Inconsistent quoting style (speed/speed:901)

  Full details: .speed/features/my-feature/logs/review-nits.json
```

## `speed fix-nits` — Nits to Tasks Pipeline

### Command signature

```bash
./speed/speed fix-nits [-f feature] [--task-id ID]
```

| Flag | Default | Description |
|------|---------|-------------|
| `-f feature` | auto-detected | Feature context (standard global flag) |
| `--task-id ID` | (optional) | Filter nits to a specific original task |

### `cmd_fix_nits()` implementation

Added to `speed/speed` alongside other `cmd_*()` functions. Reads `review-nits.json`, creates a single aggregate task.

```
cmd_fix_nits()
├── _require_feature "$GLOBAL_FEATURE"
├── Parse --task-id (optional filter)
├── Read ${LOGS_DIR}/review-nits.json
│   └── Error if missing/empty: "No nits found. Run 'speed review' first."
├── Filter by --task-id if provided
├── Compute next task ID (max existing ID + 1)
├── Build description: numbered list from nits JSON
│   └── Each nit: file:line (severity, from task N) + issue + fix suggestion
├── Build acceptance criteria
├── Compute depends_on: unique original task IDs from nits
├── Compute files_touched: unique file paths from nits
├── task_create(next_id, title, description, criteria, depends_on, MODEL_SUPPORT)
├── task_update_raw(next_id, "files_touched", files_touched)
└── Print: "Created task {id}. Next: speed run && speed review"
```

Key design decisions:
- **One task for all nits.** Nits are small by definition. Spinning up a developer agent (worktree, branch, agent spawn) for each nit is massive overhead for one-line fixes. One task, one pass, all nits fixed.
- **Depends on original tasks.** The generated task's `depends_on` lists the original task IDs, ensuring it doesn't run until those tasks are done.
- **Uses MODEL_SUPPORT (sonnet).** Nit fixes are mechanical, not reasoning tasks.
- **No new agent type.** The task goes through the normal `run → review` cycle with the standard Developer Agent.

### Task description template

```
Title: "Fix review nits from tasks {ids}"

Description:
  Fix the following reviewer nits. Each fix is small and mechanical.

  1. **speed/speed:?** (minor, from task 5)
     Issue: Fix Agent schema uses task_file but spec uses file
     Fix: Change task_file to file in the prompt

  2. ...

  Apply each fix. If a suggestion is wrong or not applicable,
  add a code comment explaining why it was skipped.

Acceptance Criteria:
  - Each nit is fixed or has a comment explaining why not applicable
  - No new lint/typecheck/test failures
  - All quality gates pass
```

### Operator flow

```
speed review          → nits surfaced, saved to review-nits.json
speed fix-nits        → task created from nits
speed run             → developer agent fixes nits
speed review          → fixes reviewed (cycle repeats if needed)
```

### Reused functions (no modifications needed)

- `task_create()` — creates the task JSON file
- `task_update_raw()` — sets `files_touched` as a JSON array
- `_require_feature()` — resolves feature context, sets TASKS_DIR/LOGS_DIR
- `log_header()`, `log_step()`, `log_success()`, `log_error()` — output helpers

## Command registration

Add `gates` and `fix-nits` to the command dispatch in `speed/speed`:

```bash
# In the main case statement:
gates)     cmd_gates "$@" ;;
fix-nits)  cmd_fix_nits "$@" ;;
```

Add to help text:

```
gates       Run quality gates for a task (used by Developer Agent mid-task)
fix-nits    Create a task to fix reviewer nits
```

## Coherence Re-Check Delta

### Problem

`speed coherence` finds cross-task compatibility issues, the operator fixes them, then re-runs coherence. The second run gives no indication of progress — the operator sees the full report fresh with no context about whether their fixes landed.

### Design

Automatic delta summary when `speed coherence` detects a previous report. No new commands, no new flags — just smarter output on re-runs.

**`_print_coherence_delta(prev_file, new_json)`** (~50 lines in `speed/speed`, placed before `cmd_coherence()`):

1. Reads previous report from `coherence-prev.json`
2. Extracts `critical_issues[]` from both reports
3. Uses `grep -qxF` for exact string matching to compute three sets:
   - **Fixed**: in prev but not in new → `SYM_CHECK`/green
   - **Remaining**: in both → `SYM_WARN`/yellow
   - **New**: in new but not in prev → `SYM_CROSS`/red
4. Prints count transition: `"Critical issues: 3 → 1"`
5. Celebratory message if all previous issues resolved
6. Graceful no-op if prev file missing or invalid JSON

### Flow

1. `cmd_coherence()` starts → copies `coherence.log` to `coherence-prev.json` (if exists)
2. Agent runs, produces new report → saved to `coherence.log`
3. If `coherence-prev.json` exists: `_print_coherence_delta()` prints delta
4. On pass: `coherence-prev.json` is cleaned up (prevents stale delta on next run)

### Files changed

| File | Change |
|------|--------|
| `speed/speed` | Add `_print_coherence_delta()`, modify `cmd_coherence()` (3 insertion points: archive prev, call delta, clean up on pass) |

## Files Changed

| File | Change |
|------|--------|
| `speed/speed` | Add `cmd_gates()`, `cmd_fix_nits()`, `_load_relevant_specs()`. Rewrite `cmd_verify()`: use `parse_agent_json()`, add `_print_verify_report()`, add auto-fix loop with Fix Agent, add human escalation output. Rewrite `cmd_review()` spec loading (smart loader), diff truncation, paced API calls with retry. Add `cmd_fix_nits()` to read `review-nits.json` and create aggregate fix task. Update command dispatch and help text for `gates` and `fix-nits`. Update `agent_message` template in `cmd_run()` to include gate commands. |
| `speed/agents/developer.md` | Replace vague "write tests" instruction with explicit "Quality Checks" section containing copy-pasteable `speed gates` commands |
| `speed/lib/grounding.sh` | Add `grounding_check_test_coverage()`, `_test_coverage_excluded()`, `_test_file_exists_in_diff()`, `grounding_check_gate_evidence()`. Update `grounding_run()` to include checks 6 and 7. |
| `speed/lib/config.sh` | Add `MAX_VERIFY_FIX_ITERATIONS=3`, `TPM_BUDGET`, `RPM_BUDGET`, `RATE_LIMIT_MAX_RETRIES`, `RATE_LIMIT_BASE_DELAY`, `RATE_LIMIT_MAX_DELAY` constants |
| `speed/lib/provider.sh` | Add `_estimate_tokens()`, `_track_tokens()`, `_tokens_used_last_minute()`, `_requests_last_minute()`, `_pace_api_call()`, `_call_with_retry()` |

No new files created. All changes are modifications to existing files.

## Dependencies

- `speed/lib/gates.sh` — `gates_run()`, `_detect_subsystem()`, `gates_get_config()`, `gate_run_command()`, `gate_syntax_check()` (all existing, no modifications)
- `speed/lib/grounding.sh` — `grounding_run()` (modified to add checks 6-7)
- `speed/lib/provider.sh` — `parse_agent_json()` (existing, used by new `cmd_verify()`), `claude_run()` (existing, used for Fix Agent)
- `speed/agents/developer.md` — prompt text (modified)
- `speed/agents/plan-verifier.md` — existing agent (no modifications; output consumed by new formatting logic)
- `speed/lib/config.sh` — `TASKS_DIR`, `WORKTREES_DIR`, `LOGS_DIR`, `PROJECT_ROOT` (existing), `MAX_VERIFY_FIX_ITERATIONS`, `TPM_BUDGET`, `RPM_BUDGET`, `RATE_LIMIT_*` (new)
- `speed/providers/claude-code.sh` — `provider_run()` (existing, no modifications — retry wraps it from provider.sh)
- `CLAUDE.md` — gate commands read by `gates_get_config()`, file organization conventions inform exclusion patterns (read only)
