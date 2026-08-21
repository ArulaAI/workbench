---
title: Installation
description: Install SPEED and configure your first project.
sidebar:
  order: 0
---

Covers: system prerequisites, installing SPEED, building grammar libraries, initializing a project, and configuring `speed.toml` and `CLAUDE.md`.

## Prerequisites

SPEED runs on Linux and macOS. It requires bash 4.3+, a handful of CLI tools, Python 3.12+, and at least one AI agent provider.

### System dependencies

| Dependency | Why | macOS | Linux (apt) |
|-----------|-----|-------|-------------|
| bash >= 4.3 | Associative arrays, namerefs | `brew install bash` | Ships with distro |
| git | Worktree isolation, branch management | Xcode CLT or `brew install git` | `apt install git` |
| jq | JSON parsing for task state | `brew install jq` | `apt install jq` |
| curl | Network operations | Pre-installed | `apt install curl` |
| GNU timeout | Agent time limits | `brew install coreutils` (provides `gtimeout`) | Ships with coreutils |
| Node.js >= 18 | Required to install agent provider CLIs | `brew install node` | `apt install nodejs npm` |
| Python 3.12+ | Context extraction, grounding, gates | `brew install python@3.12` | Ships with `python3` or `apt install python3` |

macOS ships bash 3.2. You need Homebrew bash (`brew install bash`) for SPEED to work.

### Agent provider

You need at least one AI coding agent CLI on your PATH:

```bash
# Claude CLI (default provider)
npm install -g @anthropic-ai/claude-code

# Or Codex CLI (alternative)
npm install -g @openai/codex
```

SPEED checks for a provider at startup and exits with an error if neither is found.

## Install

Two paths: the automated curl installer (handles everything) or a manual git clone (you manage dependencies).

### Option A: curl installer (recommended)

The installer downloads the repo, installs `uv` (Python package manager), creates a Python 3.12 venv with all dependencies, builds grammar libraries, patches your shell rc, and writes a receipt file for future updates.

```bash
curl -fsSL https://raw.githubusercontent.com/sanjayk/SPEED/main/install.sh | bash
```

What happens:

1. Checks bash version, system deps, and agent provider
2. Installs [uv](https://docs.astral.sh/uv/) if not already present
3. Clones the SPEED repo to `~/.speed/versions/{hash}/`
4. Strips non-runtime directories (site, tests, working-docs)
5. Creates a Python 3.12 venv at `~/.speed/venv/` with all pip dependencies
6. Verifies tree-sitter grammars and core Python modules load
7. Symlinks `~/.speed/bin/speed` to the active version
8. Adds PATH and SPEED_PYTHON to your shell rc (`.zshrc`, `.bashrc`, or fish config)
9. Writes `~/.speed/receipt.json` (prevents duplicate installs, used by `speed self-update`)

After install, restart your shell (or `source ~/.zshrc`) and verify:

```bash
speed help
```

**Installer flags:**

| Flag | Purpose |
|------|---------|
| `--proxy URL` | Route curl and git through a corporate proxy |
| `-q`, `--quiet` | Suppress non-error output (for CI) |

**Environment overrides for the installer:**

| Variable | Purpose |
|----------|---------|
| `SPEED_REPO` | Git repo URL (for internal mirrors) |
| `SPEED_TARBALL_URL` | Tarball URL (when git is unavailable) |
| `HTTP_PROXY` / `HTTPS_PROXY` | Inherited by curl and git |

### Option B: git clone (manual)

Clone the repo, install Python dependencies, build grammar libraries, then run.

**Step 1: clone**

Per-project (subdirectory):

```bash
cd my-project
git clone git@github.com:sanjayk/SPEED.git speed
```

Or global (PATH):

```bash
git clone git@github.com:sanjayk/SPEED.git ~/speed
export PATH="$HOME/speed:$PATH"   # add to shell profile
```

**Step 2: Python dependencies**

Using a virtual environment is recommended but not required. SPEED auto-detects a `.venv/` in either its own directory or your project root.

```bash
# With venv (recommended)
python3 -m venv speed/.venv
speed/.venv/bin/pip install -r speed/requirements.txt

# Or without venv (dependencies go into system Python)
pip install -r speed/requirements.txt
```

**Step 3: build grammar libraries**

SPEED uses ast-grep for structural code search. Four languages (Prisma, GraphQL, Protobuf, Zig) need compiled grammar libraries. Without them, `speed help` fails at startup because ast-grep cannot load its configuration.

This step requires tree-sitter CLI:

```bash
npm install -g tree-sitter-cli
```

Then build the grammars:

```bash
cd speed
./scripts/build-grammars.sh
```

The script clones the grammar repos, compiles platform-native shared libraries (.dylib on macOS, .so on Linux), and places them in `lib/context/data/grammars/`.

**Step 4: verify**

```bash
./speed/speed help
```

If you see the command listing with no error blocks, the install is complete.

### What requirements.txt installs

The curl installer handles all of this. For manual installs, here is what you are pulling in:

| Package group | Packages | Purpose |
|--------------|----------|---------|
| AST parsing | tree-sitter >= 0.23 + 15 language grammars | Codebase analysis (skeletons, definitions, references) |
| Structural search | ast-grep-cli | Pattern-based code search via AST |
| ML / graph | scikit-learn, networkx, python-igraph, leidenalg | TF-IDF similarity, domain clustering |
| Dashboard (optional) | fastapi, strawberry-graphql, uvicorn, watchdog | Only needed for `speed dashboard` |
| LLM integration | litellm, instructor, tiktoken | Token counting, structured output |

## Initialize a project

From your project root (must be a git repo with at least one commit):

```bash
speed init
```

`speed init` creates:

| Path | Purpose |
|------|---------|
| `.speed/` | Runtime state directory (gitignored automatically) |
| `speed.toml` | Project configuration |
| `CLAUDE.md` | Agent instructions, coding conventions, quality gate commands |
| `specs/product/overview.md` | Product vision template |

All four files are scaffolded from templates. An initial commit is created automatically.

## Configure speed.toml

The generated `speed.toml` has all options commented out with their defaults. Uncomment what you need.

```toml
[agent]
provider = "claude-code"       # or "codex-cli"
planning_model = "opus"        # architect, verifier, coherence checker
support_model = "sonnet"       # developer, reviewer, guardian, debugger
timeout = 600                  # seconds per agent invocation
max_turns = 50                 # max turns for developer agents

[worktree.symlinks]
# Symlink heavy dirs from main repo into worktrees to avoid duplication.
# "node_modules" = "node_modules"
# ".venv" = ".venv"

[subsystems]
# Map names to glob patterns for targeted quality gates.
# "frontend" = ["src/frontend/**"]
# "backend" = ["src/backend/**"]

[specs]
# vision_file = "specs/product/overview.md"

[ignore]
# Exclude directories/files from the project map and context index.
# Gitignore-style globs. Use for vendor dirs checked into git (.yarn/),
# large test suites (cypress/), or build output not in .gitignore.
# patterns = [".yarn/", "cypress/", "dist/", "*.min.js"]

[rate]
# Rate limiting for agent API calls.
# tpm_budget = 200000       # tokens per minute across all agents
# rpm_budget = 5            # requests per minute across all agents

[context]
# Context pipeline tuning.
# related_spec_budget = 15000     # max tokens for related spec context
# related_spec_threshold = 0.05   # TF-IDF similarity threshold (0.0-1.0)
# related_spec_candidate_cap = 50 # max candidate specs to evaluate

[ui]
# theme = "default"         # or "colorblind" (blue/orange palette)
# ascii = false              # true for ASCII-only output
# verbosity = "normal"       # quiet, normal, verbose, debug

[security]
# sast_cmd = "semgrep --config auto --json"
# sca_cmd = "npm audit --json"
# severity_threshold = "medium"
# secrets_patterns = ["AWS", "GITHUB_TOKEN", "GENERIC_SECRET"]
# secrets_exclude = [".env*", "*.example", "tests/fixtures/**"]

[multiplayer]
# Multi-player mode settings.
# stale_window = 3600          # seconds before unclaimed features auto-release
# serve_port = 4450            # multiplayer sync server port
# sync_interval = 30           # seconds between state sync pulls
# approval_threshold = 1       # approvals required for spec ceremonies
# prune_days = 30              # days before old events are pruned
```

**Precedence rule:** environment variable > speed.toml > built-in default. Every TOML key has a corresponding `SPEED_*` env var override (see [Environment variables](#environment-variables) below).

## Configure CLAUDE.md

`CLAUDE.md` tells agents how your project works: coding conventions, directory structure, and quality gate commands. The template is a starting point. Edit it to match your project.

The critical section is the quality gate commands, which agents and SPEED's grounding system use to verify work:

```markdown
## Quality Gates

### Lint
npm run lint

### Test
npm test

### Typecheck
npx tsc --noEmit
```

Gate commands can be scoped per subsystem (matching the `[subsystems]` globs in `speed.toml`). Without subsystem scoping, gates run against the whole project.

## Environment variables

All take precedence over `speed.toml` values.

| Variable | Default | Purpose |
|----------|---------|---------|
| `SPEED_PROVIDER` | `claude-code` | Agent CLI provider |
| `SPEED_PLANNING_MODEL` | `opus` | Model for architect, verifier, coherence |
| `SPEED_SUPPORT_MODEL` | `sonnet` | Model for developer, reviewer, guardian |
| `SPEED_TIMEOUT` | `600` | Agent timeout in seconds |
| `SPEED_MAX_TURNS` | `50` | Max turns for developer agents |
| `SPEED_TPM_BUDGET` | `200000` | Token budget per minute |
| `SPEED_RPM_BUDGET` | `5` | Request budget per minute |
| `SPEED_VERBOSITY` | `1` | 0=quiet, 1=normal, 2=verbose, 3=debug |
| `SPEED_PROJECT_ROOT` | `$(pwd)` | Override project root detection |
| `SPEED_PYTHON` | auto-detected | Python binary (set by curl installer; manual installs auto-detect from .venv or PATH) |
| `NO_COLOR` | — | Disable ANSI color output |
| `ANTHROPIC_API_KEY` | — | Passed through to Claude CLI |

## Directory layout after install

**SPEED home (created by curl installer):**

```
~/.speed/
├── bin/speed              → symlink to current/speed
├── current/               → symlink to versions/{hash}
├── venv/                  → Python 3.12 virtual environment
├── versions/{hash}/       → immutable version snapshot
│   ├── speed              → main CLI entry point
│   ├── agents/            → agent role definitions (markdown)
│   ├── providers/         → provider implementations (bash)
│   ├── lib/               → library modules + Python context engine
│   └── templates/         → scaffolding templates
└── receipt.json           → install metadata
```

**Project state (created by `speed init`):**

```
my-project/
├── .speed/
│   ├── state.json         → global runtime state
│   ├── features/{name}/   → feature-scoped task state, logs
│   ├── worktrees/         → git worktrees for isolated branches
│   └── logs/              → cross-feature logs
├── CLAUDE.md              → agent instructions + gate commands
├── speed.toml             → project configuration
└── specs/
    └── product/overview.md → product vision
```

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `bash version too old` | `brew install bash` (macOS ships 3.2) |
| `timeout command not found` | `brew install coreutils` |
| `jq not found` | `brew install jq` or `apt install jq` |
| `No agent provider found` | Install Claude CLI: `npm install -g @anthropic-ai/claude-code` |
| `python3 not found` | The curl installer creates its own venv; for manual installs, ensure python3 is on PATH |
| `speed.toml parse failed` | Check TOML syntax; the parser requires Python 3.11+ (for `tomllib`) |
| `SPEED is already installed` | Run `speed self-update` to update, or `rm -rf ~/.speed` and reinstall |
| `sgconfig.yml validation failed` | Run `./scripts/build-grammars.sh` from the SPEED directory |
| `Cannot load custom language library` | Grammar .so/.dylib files missing. Run `npm install -g tree-sitter-cli && ./scripts/build-grammars.sh` |
| Git worktree conflicts | `speed clean all` removes all worktrees and state |

After resolving prerequisites, head to [Getting Started](/docs/getting-started/) for the full workflow walkthrough.
