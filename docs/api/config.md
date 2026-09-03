---
title: Configuration Reference
description: Reference for speed.toml and environment variables.
---

SPEED is configured via a project-level `speed.toml` file. All configuration values can also be overridden by environment variables.

A malformed `speed.toml` is a configuration error. Workbench reports it once
and exits with status 3 instead of silently continuing with defaults.

## Precedence

Configuration is resolved in the following order (highest to lowest):
1.  Command-line flags (e.g., `--verbose`, `--max-parallel`)
2.  Environment variables (e.g., `SPEED_VERBOSITY`)
3.  `speed.toml` settings
4.  Built-in defaults

## Agent Settings

Configure the AI providers and model tiers used by the orchestrator.

| TOML Key | Environment Var | Default | Description |
|---|---|---|---|
| `agent.provider` | `SPEED_PROVIDER` | `claude-code` | The agent CLI provider to use. |
| `agent.planning_model` | `SPEED_PLANNING_MODEL` | `opus` | Model used for high-stakes reasoning (Architect, Verifier). |
| `agent.support_model` | `SPEED_SUPPORT_MODEL` | `sonnet` | Model used for structured support tasks (Guardian, Reviewer). |
| `agent.timeout` | `SPEED_TIMEOUT` | `600` | Max seconds allowed for a single agent run. |
| `agent.max_turns` | `SPEED_MAX_TURNS` | `50` | Max conversation turns allowed for developer agents. |

## Skill Settings

Skill harness policy is independent from `agent.provider`. The provider chooses
the execution backend; the harness list chooses where Workbench projects skills.

| TOML Key | Environment Var | Default | Description |
|---|---|---|---|
| `skills.harnesses` | `WORKBENCH_HARNESSES` | none | Durable project list containing `claude`, `codex`, and/or `copilot`. |

For initialization and skill lifecycle commands, harness selection precedence is
explicit `--harness`, `WORKBENCH_HARNESSES`, `skills.harnesses`, legacy manifest
selection during migration, then marker detection. `workbench init` persists the
resolved choice in `speed.toml`.

## Rate Limiting

Budget tracking for API usage to prevent account throttling.

| TOML Key | Environment Var | Default | Description |
|---|---|---|---|
| `rate.tpm_budget` | `SPEED_TPM_BUDGET` | `200000` | Tokens Per Minute budget. SPEED will pace calls at 80% of this. |
| `rate.rpm_budget` | `SPEED_RPM_BUDGET` | `5` | Requests Per Minute budget. |

## Specification Settings

| TOML Key | Environment Var | Default | Description |
|---|---|---|---|
| `specs.vision_file` | `SPEED_VISION_FILE` | `specs/product/overview.md` | Path to the project's product vision document. |

## User Interface

| TOML Key | Environment Var | Default | Description |
|---|---|---|---|
| `ui.theme` | `SPEED_THEME` | `default` | `default` or `colorblind`. |
| `ui.ascii` | `SPEED_ASCII` | `false` | Use ASCII-only symbols (e.g., `[ok]` vs `✓`). |
| `ui.verbosity` | `SPEED_VERBOSITY` | `1` | `0` (quiet), `1` (normal), `2` (verbose), `3` (debug). |

## Advanced Mapping

### `[subsystems]`
Maps subsystem names to glob patterns. This enables targeted quality gates (e.g., running different tests for "frontend" vs "backend").

```toml
[subsystems]
"frontend" = ["src/frontend/**"]
"backend" = ["src/backend/**"]
```

### `[worktree.symlinks]`
Declares directories that should be symlinked from the main repository into every git worktree. Essential for sharing `node_modules` or virtual environments to avoid re-installing dependencies for every task.

```toml
[worktree.symlinks]
"src/frontend/node_modules" = "src/frontend/node_modules"
"src/backend/.venv" = "src/backend/.venv"
```
