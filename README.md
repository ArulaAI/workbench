# SPEED

A bash-based orchestration framework that coordinates AI coding agents to build software from product specs. Give it a spec, it produces a task DAG, assigns agents to branches, runs quality gates, and merges the result.

A product-agnostic orchestrator. It lives alongside the code it builds.

## How it works

SPEED decomposes a product specification into a directed acyclic graph of tasks, then executes them in parallel using coding agents on isolated git branches. Each task is small (15-30 minutes of work), scoped to declared files, and verified by non-LLM gates before merge.

```
spec.md → validate → plan → verify → run → review → coherence → integrate
```

### The pipeline

1. **validate** — Cross-reference all specs for consistency. Catches missing relationships, orphaned requirements, and contradictions between feature specs before any code is written.

2. **plan** — The Architect agent reads the spec and produces a task DAG with dependency ordering, file ownership declarations, and a data model contract. A Product Guardian gate checks that the plan aligns with the product vision before proceeding.

3. **verify** — An independent Plan Verifier reads the spec blind (without seeing the Architect's reasoning) and checks whether the task plan actually delivers what the spec requires. Adversarial by design.

4. **run** — Tasks execute in parallel on isolated branches. Each Developer agent gets a single task, a system prompt with project conventions, and access to the codebase. Agents can report "blocked" status instead of guessing when requirements are ambiguous.

5. **review** — The Reviewer agent checks each completed task's diff against the original product spec (not just the task description). A second Product Guardian gate checks for vision drift.

6. **coherence** — Before integration, the Coherence Checker verifies that independently-developed branches compose correctly: matching interfaces, consistent schemas, no duplicate implementations, no missing connections.

7. **integrate** — Branches merge into main in dependency order. Regression tests run after each merge. A schema contract check verifies the data model matches the Architect's contract. A final Product Guardian gate checks the integrated result.

### Failure handling

When tasks fail, the system doesn't just retry blindly:

- A **Debugger** agent performs root cause analysis on the failure (exact file, line, classification)
- A **Supervisor** agent decides the recovery strategy: retry, escalate model, replan, or escalate to human
- Pattern detection catches systemic failures (same import error in 3 tasks = missing foundational task, fix the root cause once)
- If >30% of tasks fail, the Supervisor recommends halting

### Grounding gates

Quality checks split into two categories:

- **Grounding gates** (non-LLM): diff is non-empty, declared files exist, scope check (files touched vs declared), Python import resolution via AST parsing, blocked status detection. A script can't be bullshitted.
- **Quality gates** (tools): syntax checking (Python AST, JSON, JS/TS), lint, typecheck, test. Commands are parsed from the project's CLAUDE.md so SPEED uses the same gates as the humans.

## Providers

SPEED supports multiple AI coding agent providers through a plugin system. Each provider implements 5 functions: `provider_run`, `provider_run_json`, `provider_spawn_bg`, `provider_is_running`, `provider_wait`.

### Built-in providers

| Provider | Binary | Description |
|----------|--------|-------------|
| `claude-code` | `claude` | [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) (default) |
| `codex-cli` | `codex` | [OpenAI Codex CLI](https://github.com/openai/codex) |

### Selecting a provider

```bash
# Via environment variable (highest priority)
SPEED_PROVIDER=codex-cli ./speed/speed plan my-spec.md

# Via speed.toml (project-level)
# [agent]
# provider = "codex-cli"

# Default: claude-code
```

### Adding a provider

Create `speed/providers/<name>.sh` implementing the 5 provider functions. See `providers/claude-code.sh` as a reference.

## Configuration

SPEED is configured via `speed.toml` in the project root. All values are optional — without a config file, everything works with sensible defaults.

```toml
[agent]
provider = "claude-code"       # or "codex-cli"
planning_model = "opus"        # high-stakes: architect, verifier, coherence
support_model = "sonnet"       # structured: guardian, reviewer, developer default
timeout = 600                  # agent timeout in seconds
max_turns = 50                 # max turns for developer agents

[worktree.symlinks]
# Symlink these dirs from main repo into git worktrees
"src/frontend/node_modules" = "src/frontend/node_modules"
"src/backend/.venv" = "src/backend/.venv"

[subsystems]
# Map subsystem names to glob patterns for quality gate targeting
"frontend" = ["src/frontend/**"]
"backend" = ["src/backend/**"]

[specs]
vision_file = "specs/product/overview.md"

[ui]
# theme = "default"        # "default" or "colorblind"
# ascii = false             # true = ASCII-only symbols (no Unicode)
# verbosity = "normal"      # "quiet", "normal", "verbose", "debug"
```

### Configuration precedence

Environment variable > CLI flag > `speed.toml` > built-in default

For verbosity: `--quiet`/`--verbose`/`--debug` flag > `SPEED_VERBOSITY` env > `ui.verbosity` TOML > `1` (normal)

| Setting | Env var | TOML key | Default |
|---------|---------|----------|---------|
| Provider | `SPEED_PROVIDER` | `agent.provider` | `claude-code` |
| Planning model | `SPEED_PLANNING_MODEL` | `agent.planning_model` | `opus` |
| Support model | `SPEED_SUPPORT_MODEL` | `agent.support_model` | `sonnet` |
| Timeout | `SPEED_TIMEOUT` | `agent.timeout` | `600` |
| Max turns | `SPEED_MAX_TURNS` | `agent.max_turns` | `50` |
| Vision file | — | `specs.vision_file` | `specs/product/overview.md` |
| Theme | `SPEED_THEME` | `ui.theme` | `default` |
| ASCII symbols | `SPEED_ASCII` | `ui.ascii` | `false` |
| Verbosity | `SPEED_VERBOSITY` | `ui.verbosity` | `1` (normal) |

## Agents

| Agent | Role | When it runs |
|-------|------|--------------|
| **Architect** | Decomposes spec into task DAG + data model contract | `plan` |
| **Validator** | Cross-references all specs for consistency | `validate` |
| **Plan Verifier** | Blind-checks plan against spec (adversarial) | `verify` |
| **Product Guardian** | Checks alignment with product vision and anti-goals | `plan`, `review`, `integrate` |
| **Developer** | Implements a single task on an isolated branch | `run` |
| **Reviewer** | Code review against the product spec, not just task desc | `review` |
| **Coherence Checker** | Verifies independently-built branches compose correctly | `coherence` |
| **Debugger** | Root cause analysis on failed tasks | on failure |
| **Supervisor** | Decides recovery strategy for failures | on failure |
| **Integrator** | Merges branches in dependency order, resolves conflicts | `integrate` |

Agent definitions live in `agents/*.md`. Each defines the agent's mission, constraints, input/output format, and guidelines.

## Install

### Prerequisites

- A supported AI coding agent CLI (`claude`, `codex`, or custom provider)
- `jq` (JSON processing)
- `python3` (for AST-based import checking and TOML parsing)
- `git`
- GNU `timeout` (macOS: `brew install coreutils`)

### Option A: Subdirectory install (per-project)

Clone SPEED into your project as `./speed/`:

```bash
cd my-project
git clone git@github.com:speed-org/SPEED.git speed
# — or —
git submodule add git@github.com:speed-org/SPEED.git speed
```

Then invoke as `./speed/speed <command>`.

### Option B: PATH install (global)

Clone SPEED once and add it to your PATH:

```bash
git clone git@github.com:speed-org/SPEED.git ~/speed
export PATH="$HOME/speed:$PATH"  # add to your shell profile
```

Then invoke as `speed <command>` from any project directory.

Both methods work without additional configuration. SPEED resolves its own
files from the script location and uses `pwd` as the project root (overridable
via `SPEED_PROJECT_ROOT`).

## Tests

SPEED needs Python 3.11 or newer. Install the runtime and test dependencies, then
run the Python suites from the repository root:

```bash
python3 -m pip install -r requirements.txt -r requirements-dev.txt
PYTHONPATH=lib python3 -m pytest tests/skills/
```

`PYTHONPATH=lib` puts the `skills` package on the import path; collection fails
without it. Shell suites run on their own: `bash tests/test_multiplayer.sh`.

## Documentation

- **[Getting Started](docs/getting-started.md)** — Tutorial with example output
- **[Writing Specs](docs/writing-specs.md)** — How to write specs SPEED executes well
- **[Troubleshooting](docs/troubleshooting.md)** — Failures, logs, recovery
- **[Example Project](example/)** — Bookshelf app with pre-written specs

### Quick start

```bash
# Initialize a project for SPEED development
./speed/speed init

# Edit the generated files:
#   speed.toml         — configure provider and settings
#   specs/product/overview.md — define your product vision
#   CLAUDE.md          — project conventions and quality gates

# Cross-validate all specs for consistency
./speed/speed validate specs/

# Decompose a spec into a task DAG
./speed/speed plan specs/tech/my-feature.md --specs-dir specs/

# Blind-verify the plan against the spec
./speed/speed verify

# Execute tasks with parallel agents
./speed/speed run --max-parallel 3

# Show SPEED state and progress
./speed/speed status

# Code review completed tasks
./speed/speed review

# Check cross-task consistency before integration
./speed/speed coherence

# Merge completed branches into main
./speed/speed integrate

# Retry a failed task with human guidance
./speed/speed retry --task-id 3 --context "fix the import path"

# Recover from crashed/stale state
./speed/speed recover

# Run Product Guardian vision check on a spec
./speed/speed guardian specs/product/my-feature.md
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--max-parallel N` | 3 | Max concurrent agents |
| `--model MODEL` | sonnet | Default developer model |
| `--task-id ID` | — | Target a specific task (retry, review) |
| `--escalate` | — | Upgrade model on retry |
| `--specs-dir DIR` | — | Directory with related specs for cross-referencing |
| `--quiet` | — | Errors and final result only |
| `--verbose` | — | Show extra detail (gate output, agent commands) |
| `--debug` | — | Show internal state, timing, PID tracking |
| `--json` | — | Output structured JSON to stdout (logs to stderr) |
| `SKIP_GUARDIAN=true` | — | Skip Product Guardian gates |
| `NO_COLOR=1` | — | Disable all ANSI color output ([no-color.org](https://no-color.org/)) |

### Exit codes

| Code | Constant | Meaning |
|------|----------|---------|
| 0 | `EXIT_OK` | Success |
| 1 | `EXIT_TASK_FAILURE` | One or more tasks failed |
| 2 | `EXIT_GATE_FAILURE` | Quality gates failed |
| 3 | `EXIT_CONFIG_ERROR` | Bad config, missing binary, missing file |
| 4 | `EXIT_MERGE_CONFLICT` | Integration merge conflict |
| 5 | `EXIT_HALTED` | >30% tasks failed, supervisor halted |
| 130 | `EXIT_USER_ABORT` | Ctrl+C (128 + SIGINT) |

### Themes and accessibility

**Colorblind theme**: Uses blue for success and orange for warnings instead of green/yellow.

```bash
SPEED_THEME=colorblind ./speed/speed status
```

**ASCII mode**: Replaces Unicode symbols (✓, ✗, →) with ASCII equivalents ([ok], [FAIL], ->).

```bash
SPEED_ASCII=true ./speed/speed status
```

Both can be configured permanently in `speed.toml` under `[ui]`.

## Project structure

```
speed/
  speed                 # Main CLI (bash)
  agents/               # Agent role definitions (markdown)
    architect.md        # Spec → task DAG decomposition
    developer.md        # Single-task implementation
    reviewer.md         # Code review against product spec
    product-guardian.md  # Product vision alignment (generic)
    coherence-checker.md# Cross-branch composition check
    debugger.md         # Root cause analysis
    supervisor.md       # Recovery strategy decisions
    integrator.md       # Branch merging
    plan-verifier.md    # Adversarial plan audit
    validator.md        # Cross-spec consistency
  providers/            # Agent CLI provider implementations
    claude-code.sh      # Claude Code CLI provider (default)
    codex-cli.sh        # OpenAI Codex CLI provider
  lib/                  # Shell libraries
    colors.sh           # Color/theme system, NO_COLOR, semantic layer, ASCII fallback
    config.sh           # Paths, defaults, exit codes, TOML config
    log.sh              # Logging with verbosity levels
    provider.sh         # Provider abstraction (interface + loader)
    toml.py             # TOML parser (Python helper)
    tasks.sh            # Task CRUD, dependency resolution, topological sort
    git.sh              # Branch creation, merging, conflict detection
    grounding.sh        # Non-LLM verification gates
    gates.sh            # Quality gate runner (lint, test, typecheck)
  templates/            # Project scaffolding templates
    claude-md.md        # CLAUDE.md template
    speed-toml.toml     # speed.toml template (all defaults)
    overview.md         # Product vision document template
    spec.md             # Spec file template
    task.json           # Task schema
    architect-output.json # Architect output schema
```

## Design decisions

**Why bash?** It's glue. The orchestrator's job is to spawn processes, manage files, and call CLIs. Bash does this natively. The complex reasoning happens inside the agents, not the orchestrator.

**Why file-based state?** Tasks are JSON files in `.speed/tasks/`. No database, no server, no daemon. You can inspect state with `cat` and `jq`. If something breaks, the state is human-readable. Bash 3.2 compatibility (macOS default) means no associative arrays, hence temp-file-based tracking in the topological sort.

**Why isolated branches?** Each developer agent works on its own git branch, scoped to declared files. This prevents agents from stepping on each other, makes diffs reviewable per-task, and allows parallel execution without locks.

**Why a data model contract?** The Architect produces a machine-verifiable declaration of what tables, FKs, and relationships must exist. After integration, a bash script (not an LLM) checks whether the schema matches the contract. Scripts can't be bullshitted.

**Why a Product Guardian?** Scope creep is the default. Every individual feature request seems reasonable; collectively they turn a differentiated product into generic software. The Guardian runs at three insertion points (pre-plan, post-review, post-integration) and checks every change against the product's vision, anti-goals, and personas. It quotes the spec when flagging issues.

**Why a provider abstraction?** Different teams use different coding agent CLIs. The provider interface (5 functions) lets SPEED work with Claude Code, Codex CLI, or any future agent tool without changing the orchestration logic.

## Known limitations

- **JSON parsing is fragile.** Agent output is parsed from the agent's response. Falls back to brace-scanning extraction when structured output fails. Works in practice, but not bulletproof.
- **No rollback.** If integration fails partway, manual `git reset` is needed.
- **No tests for the orchestrator itself.** The agents are tested by running them. The bash scripts are not unit-tested.
- **Sleep-polling for parallel tasks.** Uses `kill -0` PID checks in a loop, which is simple but not efficient for long waits.
- **Codex CLI provider is untested.** The codex-cli provider implements the interface but has not been validated against a real Codex CLI installation.

## License

[MIT](../LICENSE)
