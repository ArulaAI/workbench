---
title: Running SPEED
description: From repo + feature description to integrated code in one command.
sidebar:
  order: 2
---

## Quick start

One command. You provide a repo and a feature. You get working code.

```bash
docker run -it --rm \
  -e REPO_URL="https://github.com/org/repo" \
  -e FEATURE="Add dark mode toggle to the settings page" \
  speed
```

The container handles the full pipeline: researching the codebase, writing specs, decomposing tasks, generating code, reviewing, checking coherence, and integrating. Critically, it also handles **every failure the pipeline catches**. SPEED's quality gates (spec audits, plan verification, grounding checks, code review, coherence analysis) catch real problems. The orchestrator reads those failures, diagnoses the root cause, fixes it, and retries. That loop is what makes the process hands-free.

Under the hood:

- **Pre-built image** with SPEED, Python 3.12, Node 22, grammar libraries, and provider CLIs
- **Entrypoint** clones the repo, detects auth, handles login
- **Coding CLI** (Claude Code, Codex, or any compatible tool) launches as the orchestrator with `speed plan` → `verify` → `run` → `review` → `coherence` → `integrate` pre-loaded

You watch it work in the same TUI you already know.

### Step by step

```bash
# 1. Run it
$ docker run -it --rm \
    -e REPO_URL="https://github.com/org/repo" \
    -e FEATURE="Add dark mode toggle" \
    speed
```

```
# 2. Container clones the repo into /work/<repo-name>

# 3. Auth check — if no API key was passed, the CLI opens.
#    Type these in the TUI:

  /login                          authenticate via OAuth
  /exit                           REQUIRED — hands control back, pipeline starts

# 4. CLI relaunches as the orchestrator — AUTONOMOUS FROM HERE
#
#    Phase 0  →  Install project deps (Java, Go, etc.)
#    Phase 1  →  speed init, configure speed.toml + agent instructions
#    Phase 2  →  Research codebase, write tech spec + product spec
#    Phase 3  →  speed plan → verify → run → review → coherence → integrate
#
#    At each stage: if a gate fails, the orchestrator
#    reads the error, fixes it, and retries.

# 5. Feature lands on main — "Tasks: N total | N done | 0 failed"
```

```bash
# 6. Get the code out
$ docker cp <container>:/work/<repo-name> ./output
```

### Setup (one time)

```bash
git clone git@github.com:sanjayk/SPEED.git
cd SPEED
docker build -t speed .
```

`FEATURE` accepts a plain-text description, a GitHub/Jira issue URL (`https://github.com/org/repo/issues/123`), or a path to a mounted spec file.

### What happens next

The container clones your repo and checks for an authenticated coding CLI. If no credentials are found, it opens the CLI for you to log in.

> **Authentication runs every time.** The container is ephemeral (`--rm`), so credentials don't persist between runs.

**Option A: Interactive login**

The container opens the CLI. Three steps:

1. Run **`/login`** and complete the OAuth flow
2. Type **`/exit`** to hand control back to the entrypoint
3. The pipeline starts automatically

> The `/exit` step is critical. After you authenticate, the CLI is in an interactive session. Typing `/exit` closes that session so the entrypoint can relaunch the CLI as the autonomous orchestrator.

**Option B: API key**

Skip the login entirely:

```bash
-e ANTHROPIC_API_KEY=sk-ant-...    # for Claude Code
-e OPENAI_API_KEY=sk-...           # for Codex
```

### Repo options

**Public repo** (cloned inside the container):
```bash
-e REPO_URL="https://github.com/org/repo"
```

**Private repo** (token injected into the clone URL):
```bash
-e GIT_TOKEN="ghp_..." \
-e REPO_URL="https://github.com/org/private-repo"
```

**Local repo** (mounted from your machine, no clone):
```bash
-v ~/code/myproject:/work/myproject \
-e REPO_URL=/work/myproject
```

### All options

| Variable | Default | Purpose |
|----------|---------|---------|
| `REPO_URL` | *(required)* | Git clone URL or path to a mounted local repo |
| `FEATURE` | *(required)* | Plain-text description, GitHub/Jira issue URL, or path to a mounted spec file |
| `GIT_TOKEN` | — | Injected into HTTPS clone URL for private repos |
| `GIT_NAME` | `SPEED Agent` | Git commit author name |
| `GIT_EMAIL` | `speed@localhost` | Git commit author email |
| `ORCHESTRATOR_CMD` | auto-detected | Override the orchestrator CLI (e.g. `"ollama run llama3"`) |

### What the orchestrator does

After authentication, the CLI relaunches with SPEED's pipeline prompt loaded into its system context. From this point on, **it runs autonomously**. You watch the CLI's normal interactive UI. You can intervene if needed, but the orchestrator handles the standard failure modes on its own.

The pipeline prompt guides it through four phases. Each builds on the previous; the orchestrator **will not skip ahead** past a failure.

**Phase 0: Dependencies**
The base image includes Python and Node. The orchestrator inspects the repo for other runtimes (`pom.xml` → Java, `go.mod` → Go, `Gemfile` → Ruby) and installs them before proceeding.

**Phase 1: Project setup**
Runs `speed init`, identifies subsystems and ignore patterns from the repo structure, finds `lint`/`test`/`typecheck` commands from build configs, commits the configuration.

**Phase 2: Spec writing**
Researches the codebase until it can answer seven research questions (exact file paths, call chains, data models, test patterns, prior art, whether the target code is actually wired in). Writes a **tech spec** (RFC template) and **product spec** (PRD template). A self-audit step checks that every section references actual code, not assumptions.

**Phase 3: Pipeline execution**

```
speed plan → speed verify → speed run → speed review → speed coherence → speed integrate
```

Every stage has quality gates. When a gate fails, the orchestrator has diagnostic instructions for each failure type:

| Failure | What the orchestrator does |
|---------|--------------------------|
| Spec audit rejection | Reads the audit JSON, adds missing sections, re-commits, re-plans |
| Decomposition gate false positive | Reads the gate report, applies `SKIP_DECOMP=true` for simple features |
| Verifier finds spec gaps | Fixes task descriptions per the Verifier's guidance, re-runs verify |
| Empty diff (agent produced no changes) | Reads the task log, retries with `--context` pointing to exact files and lines |
| Review requests changes | Runs `speed run` so the agent sees the feedback |
| Coherence conflict | Runs `speed coherence --resolve` → `speed run` → `speed coherence` loop |
| Merge conflict at integration | Resolves manually or lets the Integrator agent attempt resolution |

### Reference

Test run on **find-your-tribe** (350 source files, 4 tasks, 8 files changed):

| Stage | Time |
|-------|------|
| Research + spec writing | ~15 min |
| Plan + audit | ~5 min |
| Verify | ~2 min |
| Run (4 tasks, 3 parallel) | ~5 min |
| Review (incl. 1 round-trip) | ~8 min |
| Coherence | ~2 min |
| Integrate | ~3 min |
| **Total** | **~40 min** |

Inner agent cost: **$4.01** across 21 invocations. Prompt caching kept input costs low (1.87M cache-read tokens vs 448K cache-write tokens).

### Monitoring and intervention

The orchestrator handles most failures on its own. When you need to understand what's happening or step in, here's how.

#### Getting into the container

Find the container name and exec in:

```bash
docker ps --format '{{.Names}} {{.Status}}'    # find the container
docker exec -it <container-name> bash           # open a shell
cd /work/<repo-name>                            # go to the repo
```

#### Checking pipeline state

```bash
/opt/speed/speed status
```

The output shows:

- **Feature name** and how many tasks are done/running/pending/failed
- **Task list** with dependencies, one line per task (check marks, spinners, or X marks)
- **Failure classification** when tasks have failed (pipeline error vs. complexity)
- **Active agents** and whether SPEED is idle or running

If `speed status` shows `SPEED: idle` with pending tasks, the orchestrator has likely stalled or is between commands.

#### Reading logs

SPEED writes logs per agent invocation. All logs are under:

```
.speed/features/<feature-name>/logs/
```

Key files:

| File pattern | What it tells you |
|-------------|-------------------|
| `<task_id>.log` | Full output from a developer agent run |
| `plan-audit-*.json` | Why the spec audit passed or failed |
| `plan-verification.log` | What the Verifier found (requirements coverage, gaps) |
| `decomposition-gate.json` | Why the decomposition gate passed or failed |
| `coherence.log` | Cross-task compatibility issues |
| `integration.log` | Merge results, regression test output |
| `Architect-*.jsonl` | Raw Architect agent events (stream JSON) |
| `Reviewer-*.jsonl` | Raw Reviewer agent events |

To understand why a task failed, read its log:

```bash
cat .speed/features/<feature-name>/logs/<task_id>.log
```

#### Stuck vs. slow

The orchestrator can look stuck when it's actually working. Common slow points:

| What you see | What's happening | How long to wait |
|-------------|-----------------|-----------------|
| No output for 2-3 min after `speed plan` | Layer 1 is building the codebase index (tree-sitter parsing thousands of files) | Up to 5 min for large repos |
| No output during `speed run` | Developer agents are working in worktrees | 5-15 min per task |
| Orchestrator reading many files | Researching the codebase before writing specs | 5-15 min depending on repo size |
| `speed verify` running | Verifier agent is doing a blind check against the spec | 2-8 min |

If nothing has changed for **20+ minutes**, the orchestrator is likely stuck. Check `speed status` from another shell.

#### Manual intervention

When the orchestrator can't fix something, you can step in from inside the container:

```bash
# Check what failed
/opt/speed/speed status

# Retry a specific task with guidance
/opt/speed/speed retry --task-id <id> --context "The method signature changed to include ExecuteActionDTO as the 4th parameter"

# Recover from a crashed session (stale locks, stuck tasks)
/opt/speed/speed recover

# Create fix tasks from coherence issues
/opt/speed/speed coherence --resolve

# Then re-run
/opt/speed/speed run --max-parallel 3
```

> **`--context` matters.** Blind retries fail for the same reason. Read the task log, find the specific issue, and tell the agent exactly what to do differently. `"Edit RestApiPlugin.java at line 142"` is useful. `"Try again"` is not.

#### When to start over

Kill the container and run fresh when:

- The orchestrator is looping on the same failure (same error after 3+ retries)
- The spec is fundamentally wrong (wrong feature understanding, wrong files identified)
- The codebase has changed since the container started (someone pushed to the repo)

```bash
docker rm -f <container-name>
# fix the feature description or spec, then re-run
docker run -it --rm -e REPO_URL="..." -e FEATURE="..." speed
```

When NOT to start over:

- A single task failed (use `speed retry`)
- Review requested changes (the orchestrator handles this automatically)
- Coherence found issues (`speed coherence --resolve` creates fix tasks)

#### What success looks like

When the pipeline completes, the orchestrator runs `speed status` and you see:

```
Tasks: N total | N done | 0 running | 0 pending | 0 failed
```

The integrated code is on `main` inside the container. To inspect:

```bash
docker exec <container-name> bash -c "cd /work/<repo-name> && git log --oneline -10"
docker exec <container-name> bash -c "cd /work/<repo-name> && git diff HEAD~N"
```

To copy the code out:

```bash
docker cp <container-name>:/work/<repo-name> ./output
```

---

## Rules

These apply whether the orchestrator is handling things automatically or you're intervening manually. Every rule exists because violating it caused a real failure.

1. **Never manually edit `.speed/` JSON files.** Use `speed retry`, `speed recover`, `speed coherence --resolve`.
2. **Never modify SPEED source code.** Use env vars for overrides.
3. **Scope gate skips to individual tasks:** `SKIP_GATES=true speed retry --task-id N`. Never globally disable gates on `speed run`.
4. **Use `speed retry` for blocked tasks.** Not `speed recover` (that's for crashed sessions).
5. **Always check git diffs** after task completion. An agent can report "done" with no actual file changes.
6. **Never skip coherence.** Every coherence failure in testing was a runtime crash invisible to code review.
7. **Never skip verify.** The Verifier catches architectural gaps that agents and reviewers miss.
8. **Run `speed recover` before `speed run`** if a previous run was interrupted.
9. **Retry with specific `--context`**, not blind retries. Read the task log first.
