---
title: "Getting Started with SPEED"
description: An illustrative walkthrough of the core SPEED workflow, from spec to integrated code.
sidebar:
  order: 1
---

SPEED turns markdown specs into implemented, reviewed, and integrated code. This walkthrough follows the core workflow on a real project so you can see what each command does and what to expect.

## Prerequisites

1.  **SPEED installed** and available in your PATH.
2.  **Claude Code, Codex, or GitHub Copilot** available as your agent harness.
3.  **Git** initialized in your project.

## 1. Initialize the Project

```bash
# Choose the agent harness used by this project
workbench init --harness claude
```

Use `claude`, `codex`, or `copilot` as the harness value. Explicit selection
creates and configures only that harness's project skill directory:

| Harness | Project skill directory |
|---|---|
| Claude Code | `.claude/skills/` |
| Codex | `.agents/skills/` |
| GitHub Copilot | `.github/skills/` |

If `--harness` is omitted, Workbench detects existing supported harnesses and
projects skills into each detected agent harness. `speed init` remains available as a
temporary alias for `workbench init`.

Initialization creates the `.speed/` runtime directory, scaffolds `speed.toml`,
adds agent instructions and the product vision template at
`specs/product/overview.md` when needed, and imports the managed Workbench skill
catalog. The initial catalog contains the read-only `workbench-health` skill.

### Verify the Imported Skills

Invoke the health skill from your selected agent harness:

```text
/workbench-health
```

A successful result reports that the Workbench skills were imported and are
ready to use. Health is an agent skill; there is intentionally no
`workbench health` command.

You can inspect the same managed installation from the terminal:

```bash
# Show the state of every imported skill
workbench skills status

# Diagnose missing, stale, modified, or obsolete projections
workbench skills doctor

# Import catalog updates or repair an unmodified projection
workbench skills sync
```

Workbench preserves local edits to projected skills as conflicts. Review or
back up an intentional edit before using `workbench skills sync --force`.

## 2. Write a Spec

Create a tech spec at `specs/tech/search-endpoint.md`. If your feature also has a product spec or design spec, give them the same filename in their respective directories so the planner [links them automatically](/docs/writing-specs/#multiple-specs-for-one-feature).

```markdown
---
title: Search Endpoint
related:
  - specs/product/overview.md
---

## Goal
Add a `searchBooks` query that returns matching books by title.

## Data Model
| Entity | Field | Type | Constraints |
|--------|-------|------|-------------|
| books  | title | TEXT | NOT NULL, indexed |

## Acceptance Criteria
- AC1: Query returns books whose title contains the search string.
- AC2: Search strings shorter than 3 characters return a validation error.

## Out of Scope
- Full-text search ranking or relevance scoring.
```

## 3. Audit and Plan

```bash
# Structural audit — checks sizing, required sections, vision alignment
speed audit specs/tech/search-endpoint.md

# Generate the task DAG — builds the codebase index (Layer 1), runs
# the Guardian gate, then decomposes the spec into parallel tasks
speed plan specs/tech/search-endpoint.md
```

The Architect identifies files to modify, draws task boundaries along domain cluster lines, and produces a DAG of tasks with acceptance criteria, file lists, and a data model contract.

## 4. Verify the Plan

```bash
speed verify
```

An independent Verifier reads the spec without seeing the Architect's reasoning and checks whether the task plan actually delivers every requirement. Missing requirements surface here before any code runs.

## 5. Run the Agents

```bash
speed run
```

SPEED spawns developer agents in isolated git worktrees, one per task. Each agent receives pre-computed context (the right source files, skeletons, and spec references) and writes code from turn one. Quality gates (syntax, lint, test) run inside each worktree as agents complete.

Check progress at any point:

```bash
speed status
```

The status output shows task progress, active agents, security findings, failure classifications, and supervisor analysis if any tasks have failed.

## 6. Review, Coherence, and Integrate

```bash
# Trigger code review against the original spec
speed review

# Check that independently built branches compose correctly
speed coherence

# Merge validated branches in dependency order
speed integrate
```

Integration runs regression tests after each merge and performs a final contract check to verify the implementation matches the Architect's data model.

## 7. Security Audit

```bash
speed security
```

Runs Semgrep SAST, dependency SCA, and secrets scanning against the feature branch. Findings are mapped to OWASP categories with severity-based priority (critical=P0 through low=P3). Use `--create-defects` to automatically generate defect specs for findings above the configured threshold.

## What You Learned

*   **Spec-Driven Development**: You controlled the codebase by editing a markdown table, not writing code.
*   **High-Fidelity Context**: SPEED delivered exact signatures and file references to agents, preventing hallucinations.
*   **Parallelism**: Independent tasks run simultaneously on separate branches with automated coherence checking.

## Next Steps

*   [How to Write High-Fidelity Specs](/docs/writing-specs/) for complex, multi-subsystem features.
*   [Design Philosophy](/docs/design-philosophy/) for the reasoning behind the 3-Layer architecture.
*   [CLI Reference](/docs/api/cli/) for the full command set.
