---
title: CLI Reference
description: Command-line interface reference for the speed orchestrator.
---

The `speed` CLI is the entry point for the orchestration pipeline. It coordinates agents through separate stages from initialization to integration.

## Usage

```bash
speed <command> [options]
```

## Global Options

These flags apply to all commands.

| Flag | Description |
|---|---|
| `--feature NAME` | Target a specific feature directory. Auto-detected from context if omitted. |
| `--quiet` | Errors and final results only. |
| `--verbose` | Show extra detail including gate output and agent commands. |
| `--debug` | Show internal state, timing, and PID tracking. |
| `--json` | Output structured JSON to stdout (logs move to stderr). |

## Commands

### `init`
Initializes a project for SPEED development. Creates a `.speed/` runtime directory, scaffolds `CLAUDE.md`, `speed.toml`, and a product vision template if missing. Also creates `src/` and `tests/` directories, writes `.gitignore` entries, initializes `state.json`, and creates an initial git commit.

### `new <type> <name>`
Scaffolds a new spec file from a type-specific template. Supported types: `prd`, `rfc`, `design`, `defect`. Output goes to the matching `specs/` subdirectory (e.g., `prd` creates `specs/product/<name>.md`). Opens the file in `$EDITOR` after creation. Name must be lowercase alphanumeric with hyphens only.

### `validate <specs-dir>`
Cross-references all specification files in the target directory. The Validator agent identifies missing relationships, contradictory requirements, and orphaned features before any tasks are generated.

### `audit <spec-file>`
Runs a structural audit of a spec file against the official template for its type. Spec type is detected from the path: `product/` → PRD, `tech/` → RFC, `design/` → design, `defects/` → defect. The audit checks required sections, sizing (warns if the feature is too large for a single plan cycle), and cross-references linked specs and the product vision. Defect specs additionally cross-reference the related feature spec. Writes a timestamped audit JSON to the feature's logs directory.

### `plan <spec-file>`
Decomposes a technical specification into a directed acyclic graph (DAG) of tasks.
*   **Layer 1 Context**: Automatically builds a codebase index before running.
*   **Guardian Gate**: Runs a pre-plan vision check to ensure the feature aligns with the product roadmap.
*   **Caching**: Plans are cached by spec content hash. Unchanged specs reuse the cached plan.
*   **Sibling Specs**: Auto-derives related specs from the path convention (e.g., `specs/tech/foo.md` resolves `specs/product/foo.md` and `specs/design/foo.md`).
*   **Multi-Phase**: Large features (exceeding the sizing threshold) are decomposed in two phases: foundation, then feature implementation.
*   **Quality Gate**: Validates decomposition quality (cluster size, file ownership, bridge symbols). Auto-patches missing bridge-symbol dependencies when possible.
*   **Options**:
    *   `--specs-dir DIR`: Path to related specs for cross-referencing.
    *   `--force`: Bypasses the plan cache.
    *   `--skip-audit`: Skips the structural audit of the spec file.

### `verify`
Performs an adversarial audit. An independent verifier reads the product spec without seeing the Architect's reasoning and checks whether the proposed task plan actually delivers the requirements. Reads cross-cutting concerns and spec traceability data as additional input.

When fixable issues are found, a Fix Agent modifies task JSONs and the verifier re-runs (up to N iterations with convergence detection). Issues requiring human judgment skip the auto-fix loop and escalate directly.

### `run`
Executes pending tasks in parallel using isolated git worktrees.
*   **Concurrency**: Controlled by the `--max-parallel` flag.
*   **Stale Recovery**: On startup, resets "running" tasks from a previous crashed session to pending.
*   **Timeout Escalation**: Tasks that time out are retried with an upgraded model tier (sonnet to opus).
*   **Halt Threshold**: Stops the run when the failure rate exceeds 30% to prevent cascading failures.
*   **Pattern Detection**: The Supervisor analyzes failures across the log to identify systemic issues.
*   **Defect mode**: `speed run --defect <name>` runs the defect pipeline (triage → reproduce → fix) instead of the standard task pipeline. Trivial defects skip the reproduce stage.
*   **Options**:
    *   `--max-parallel N`: Maximum concurrent agents (default: 3).
    *   `--model MODEL`: Target LLM for developer agents (sonnet, opus, or haiku).

### `review`
Triggers code review for completed tasks. Uses the Reviewer agent to check diffs against original product requirements rather than just task descriptions. After the Reviewer approves, the Product Guardian runs a post-review vision-alignment gate. A Guardian rejection overrides the approval and sends the task back to `request_changes`. Nits from approved tasks are collected into `review-nits.json`.
*   **Option**: `--task-id ID`: Target a specific completed task.

### `coherence`
Standalone cross-task coherence check. The Coherence Checker examines how independently developed task branches interact when combined, looking for interface mismatches, duplicated logic, and contradictory assumptions. Runs delta comparison against previous reports when they exist, categorizing issues as fixed, remaining, or new.

### `integrate`
Merges validated branches into the main repository in dependency order. Coherence checking is a separate command (`speed coherence`) run before integration.
*   **Regression**: Runs automated tests after each merge (skip with `--skip-tests`).
*   **CSG Rebuild**: Rebuilds the codebase index against the merged result.
*   **Contract Check**: Verifies that implemented code matches the Architect's data model contract. Invokes the Supervisor on failure.
*   **Guardian Gate**: Performs a final vision check on the integrated result.
*   **Option**: `--defect <name>`: Integrates a defect fix (runs review first for moderate defects in "fixed" state).

### `learn`
Extracts structured observations from a completed feature's artifacts and feeds them into the learning pipeline. Requires a prior `speed plan` and `speed run`. Without flags, runs a 14-step extraction pipeline that produces typed observations from task outcomes, agent logs, and human correction signals. See the [Learning System](/docs/api/learn/) reference for the full pipeline and observation types. For multiplayer knowledge collaboration, see the [Multi-Player Reference](/docs/api/multiplayer-reference/).

| Flag | Description |
|---|---|
| *(no flags)* | Extract observations from the active feature's artifacts. |
| `--summary` | Aggregate stats across all observed features. |
| `--synthesize` | Distill raw observations into per-agent learnings with routing, weighting, and token budgets. |
| `--post-merge` | Detect human corrections by diffing task branches against merged HEAD. |
| `--conventions` | Run convention discovery from accumulated observations and the semantic graph. |
| `--seed-knowledge` | Scan the project and generate draft knowledge entries for human review. |
| `--dry-run` | Run extraction without writing any files. |
| `--merge` | *(Multi-player)* Merge pending knowledge proposals into shared conventions. |
| `--curate` | *(Multi-player)* Interactive conflict resolution for opposing proposals. |
| `--pending` | *(Multi-player)* List unmerged proposals with actor, feature, and timestamp. |
| `--prune` | *(Multi-player)* Archive events older than the configured threshold (default: 30 days). |

### `retry`
Restarts a failed or blocked task with human guidance.
*   **Required**: `--task-id ID` and `--context "instructions"`. The `--context` flag prevents blind retries without diagnostic input.
*   **Option**: `--escalate`: Upgrades the agent model through the ladder (haiku → sonnet → opus).
*   **Option**: `--defect <name>`: Retries a defect fix with stage-aware re-entry, resuming from the failed stage.

### `security`
Runs a security audit against the current feature. Orchestrates three scanning tools:
*   **SAST**: Semgrep static analysis for code-level vulnerabilities.
*   **SCA**: Dependency scanning for known CVEs in third-party packages.
*   **Secrets**: Pattern-based detection of leaked credentials and API keys.

Findings are mapped to OWASP categories and assigned severity-based priority: critical=P0, high=P1, medium=P2, low=P3.
*   **Option**: `--create-defects`: Generates defect specs for findings above the configured severity threshold (default: medium). Cached audit results are reused if less than 1 hour old.

### `defect <spec-path>`
Triages a defect spec through the defect pipeline. The triage agent assesses complexity (trivial, moderate, complex). Trivial defects auto-continue through fix and integration within the same invocation. Moderate and complex defects stop after triage for review.
*   **Usage**: `speed defect specs/defects/my-bug.md`

### `gates`
Runs quality gates manually against a specific task.
*   **Required**: `--task ID`
*   **Modes**:
    *   `--fast` (default): Syntax check + lint + typecheck only.
    *   `--full`: Grounding gates + all quality gates including tests. Passing gates on a failed task promotes it to "done".
*   **Option**: `--worktree <path>`: Override the worktree path (auto-detected if omitted).

### `guardian [file]`
Runs the Product Guardian vision check. Two modes:
*   **Ad-hoc**: `speed guardian <file>` evaluates any file against the product vision.
*   **Feature**: `speed guardian` (no argument) evaluates the current feature's spec and task plan against the product vision.

### `status`
Displays current orchestration state for the active feature (or the one specified with `--feature`). Output includes:
*   Feature list with task progress counts (done/running/failed).
*   Task dependency graph and summary.
*   Security findings summary (critical/high/medium/low/info) aggregated from SAST, SCA, and secrets scans.
*   Failure classification breakdown (pipeline vs. complexity, with per-subclass counts).
*   Timed-out tasks that may need decomposition.
*   Latest Supervisor analysis (diagnosis, detected patterns, root cause, recommendations).
*   **Option**: `--defects`: Show defect state instead of task state.

### `add-language <language>`
Adds tree-sitter extraction support for a new programming language. Validates the grammar package is installed, reads `node-types.json`, generates draft ast-grep YAML rules via LLM, and registers the language in `extraction.toml`. Review generated rules with `speed test-rules <language>`.

### `test-rules [language | --all]`
Runs ast-grep rules against fixture files and compares output to expected results. Without arguments, tests the active language. With `--all`, tests every registered language. Reports PASS/FAIL/OK per fixture.

## Multi-Player Commands

These commands are available after running `speed mp-init`. See the [Multi-Player Mode](/docs/multiplayer/) guide for the full workflow.

### `mp-init`
Initializes multi-player mode on an existing SPEED project. Creates the `shared/` and `local/` zone split under `.speed/`, migrates existing features, memory, worktrees, and the dashboard database to their new locations. Updates `.speed/.gitignore` to ignore only `local/` and updates the project `.gitignore` from `.speed/` to `.speed/local/`. Safe to run on a project that's already initialized (no-op).

### `claim <feature>`
Claims exclusive ownership of a feature. Emits a `feature.claimed` event to the shared event log. If another actor holds the claim, exits with an error showing the current owner. Creates the shared feature directory if it doesn't exist.

### `release <feature>`
Releases ownership of a feature. Emits a `feature.released` event. Only the current owner can release. Unclaimed features return a no-op.

### `whoami`
Prints the resolved actor identity and filesystem slug. Resolution order: `$SPEED_ACTOR` env → `git config user.name` → `$(whoami)`. Works without multi-player mode enabled.

### `rebuild-state`
Replays the shared event log and compares reconstructed task state against materialized task JSON files. Reports matches and divergences.
*   **Default**: Dry-run mode, reports only.
*   **Option**: `--apply`: Overwrites materialized state where it diverges from the event log.

### `status --team`
Displays the team roster: all actors who have run a `speed` command in the last 24 hours, their active feature, current stage, last seen time, and last command. Requires multi-player mode.

### `learn --merge`
Processes pending knowledge proposals in `shared/proposals/`. Non-conflicting conventions are auto-merged into `shared/knowledge/conventions.json` with confidence scoring. Conflicting proposals are written to `shared/knowledge/conflicts.json`.

### `learn --curate`
Interactive conflict resolution. Walks through each entry in `conflicts.json` and prompts for a decision: keep existing, accept proposed, or skip. Resolved entries are locked against future auto-modification.

### `learn --pending`
Lists all pending (unmerged) knowledge proposals with their actor, feature, observation count, and timestamp.

### `learn --prune`
Archives events older than 30 days (configurable via `speed.toml` `[multiplayer] prune_days`) into per-feature archive files. Reduces directory clutter without losing event history. Requires multi-player mode.

### `validate --all-active`
Cross-references all active (claimed) feature specs against each other. Detects contradictory requirements, incompatible schema changes, overlapping file ownership. Outputs a recommended integration order based on overlap density. Requires multi-player mode.

### `coherence --cross-feature`
Checks completed branches across all active features for compatibility. Finds interface mismatches, conflicting modifications to shared files, incompatible migrations. Requires multi-player mode.

### `spec propose <spec-path>`
Creates a review request event for a spec. Blocks `speed plan` until the spec is ratified. Records the spec content hash for change tracking.

### `spec review [--approve|--reject] [--comment "..."] [spec-path]`
Without flags, lists all pending spec proposals with approval counts. With `--approve` or `--reject`, submits a verdict as an event. Comments are optional.

### `spec ratify <spec-path>`
Checks the approval threshold (default 1, configurable in `speed.toml`). If met and no rejections are outstanding, emits a `spec.ratified` event that unlocks planning. Rejected specs must be re-proposed after addressing feedback.

### `review request`
Posts outcome evidence (task counts, review results, guardian verdicts) for team review. Run after `speed run` and `speed review` complete.

### `review judge [--approve|--reject] [--comment "..."]`
Submits a verdict on an outcome review as an event. Requires multi-player mode.

### `review status`
Shows consolidated feedback from the outcome review: who requested, evidence summary, all verdicts with comments.

### `sync start|stop|status`
Manages the background sync daemon. The daemon watches `.speed/shared/` for changes, auto-commits and pushes events/roster, and pulls remote changes on a configurable interval.
*   `start [--interval N]`: Start daemon (default: 30s interval).
*   `stop`: Stop daemon.
*   `status`: Show running state and recent log entries.

### `serve [start|stop|status]`
Manages the multi-player HTTP server. Serves roster, events, and features as REST endpoints. Provides claim arbitration to prevent race conditions.
*   `start [--port PORT]`: Start server (default: port 4450).
*   `stop`: Stop server.
*   `status`: Show running state.
*   **Endpoints**: `/api/roster`, `/api/events`, `/api/features`, `/api/claim` (POST), `/api/health`.

### `clean`
Removes runtime state.
*   `speed clean logs`: Clears log files (scoped to active feature when one is set).
*   `speed clean all`: Removes the entire `.speed/` state.
*   `speed clean feature <name>`: Removes a specific feature's state and associated worktrees.

### `fix-nits [--task-id ID]`
Creates a new task from reviewer nits collected during the last review. The generated task includes file paths, line numbers, severity, and suggested changes. Dependencies are set to the source tasks that produced the nits. The optional `--task-id` flag filters nits to a single source task.

### `recover`
Emergency recovery from a crashed session. Breaks stale locks, kills orphan agent processes, resets tasks stuck in "running" state to pending, cleans stale state directories, and removes orphaned worktrees.

### `dashboard start|stop|status|ingest`
Manages the monitoring dashboard.
*   `start [--port PORT] [--api-only]`: Launches FastAPI backend (default port 4440) and Next.js frontend (port 3000).
*   `stop`: Graceful shutdown with timeout, then force-kills.
*   `status`: Shows running/dead state of dashboard processes.
*   `ingest`: Backfills the dashboard database from state files without starting the server.

### `self-update`
Updates the SPEED installation atomically. Uses a staging directory and symlink swap, rebuilds the Python venv only when dependencies change, and retains the previous version for rollback. Requires a managed install (not a git clone).

### `self-uninstall`
Removes the SPEED installation (`~/.speed/`) and cleans PATH entries from shell configuration files (`.zshrc`, `.bashrc`, `.bash_profile`, fish config).

## Exit Codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Task failure (one or more agents failed) |
| 2 | Gate failure (lint, test, or contract check failed) |
| 3 | Config error (missing binary or invalid setup) |
| 4 | Merge conflict during integration |
| 5 | Halted (failure rate exceeded 30%) |
| 130 | User abort (Ctrl+C) |
