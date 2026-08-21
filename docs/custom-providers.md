---
title: How to Implement Custom Agent Providers
description: Goal-oriented guide for extending SPEED with new LLM providers.
sidebar:
  order: 7
---

SPEED is provider-agnostic. You can implement a custom provider by creating a shell script that responds to five core hooks. This allows you to bridge SPEED to ANY agent CLI or local LLM server.

## Goal
Implement a custom provider for a local [Ollama](https://ollama.com/) instance.

### 1. Create the Provider Script
Create `lib/providers/ollama.sh`. You must implement the five required functions.

```bash
#!/usr/bin/env bash

# hook 1: provider_run
# Primary entry point for executing an agent turn.
provider_run() {
    local task_id="$1"
    local prompt="$2"
    # Call Ollama CLI or generate a request to the API
    ollama run llama3 "$prompt"
}

# hook 2: provider_run_json
# Specialized entry point for agents that must return strict JSON.
provider_run_json() {
    local task_id="$1"
    local prompt="$2"
    # Hint: Append "Reply in strict JSON" to the prompt
    ollama run llama3 "$prompt. Reply only with valid JSON."
}

# hook 3: provider_spawn_bg
# Spawns a background agent process (returned as a PID).
provider_spawn_bg() {
    local task_id="$1"
    local prompt="$2"
    ollama run llama3 "$prompt" > "logs/$task_id.log" 2>&1 &
    echo $!
}

# hook 4: provider_is_running
# Checks if a background process is still active.
provider_is_running() {
    local pid="$1"
    kill -0 "$pid" 2>/dev/null
}

# hook 5: provider_wait
# Block until a background process completes.
provider_wait() {
    local pid="$1"
    wait "$pid"
}
```

### 2. Register the Provider
Update `speed.toml` to point to your new provider:

```toml
[agent]
provider = "ollama"
```

### 3. Verification
Test your implementation by running a simple task:
```bash
speed run --max-parallel 1
```

---

## Best Practices for Providers

### Token Tracking
SPEED expects providers to log token usage to stderr in the format `Token Usage: {input}/{output}`. The orchestrator uses this to update the budget analyzer.

### API Pacing
If your provider has a rate limit, implement a "wait and retry" strategy inside `provider_run`. SPEED provides a `log_warning` helper to notify the user when the pipeline is throttled.

### Environment Isolation
Always run agent commands within the git worktree provided in the agent's environment (`$AGENT_WORKTREE`). This ensures that agents don't interfere with your main repository.

## Environment Variables Available to Agents

SPEED passes context to agents through the provider interface. Custom providers receive these via function arguments:

| Argument Position | Content | Example |
|-------------------|---------|---------|
| 1st | System prompt file path | `agents/developer.md` |
| 2nd | User message (assembled context) | The full Layer 3 prompt |
| 3rd | Output file path | Where the agent writes results |
| 4th | Model name | `opus`, `sonnet`, or `haiku` |
| 5th | Allowed tools | `"Bash Edit Read Write Glob Grep"` |
| 6th | Working directory (worktree path) | `.speed/worktrees/task-3` |

The working directory (6th argument) is the isolated git worktree for the task. Agents should execute all commands within this directory. SPEED manages three tool permission levels:

| Variable | Tools | Used by |
|----------|-------|---------|
| `AGENT_TOOLS_FULL` | `Bash Edit Read Write Glob Grep` | Developer agents (full read/write + shell) |
| `AGENT_TOOLS_WRITE` | `Read Write Glob` | File manipulation only (no shell) |
| `AGENT_TOOLS_READONLY` | `Read Glob Grep` | Read-only agents (Reviewer, Auditor, Guardian) |

## Pre-flight Checklist
- [ ] All five shell hooks (`run`, `run_json`, `spawn`, `is_running`, `wait`) are implemented.
- [ ] The script is executable (`chmod +x`).
- [ ] `speed.toml` uses the provider name matching your filename.
- [ ] Tokens are logged to stderr for budget tracking.
