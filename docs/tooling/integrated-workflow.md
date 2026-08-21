---
title: The SPEED + Claude Code Workflow
description: An integrated, high-fidelity development cycle for complex features.
---

This workflow combines the **orchestration power of SPEED**, the **ad-hoc agility of Claude Code**, and the **workspace persistence of TMUX**. We'll use the `bookshelf` example to illustrate.

## Phase 1: Context & Discovery (Claude Code)
Before triggering a formal SPEED run, use **Claude Code CLI** in your main TMUX window to probe the project.

- **Objective**: Understand where a new feature fits.
- **Action**: `claude "find where the book search logic is and explain the schema"`
- **Why**: Claude Code is much faster for "read-only" research and map-making than spawning full agent worktrees.

## Phase 1.5: The Structural Audit (SPEED)
Before moving to planning, audit your new spec to ensure it's structurally sound and appropriately sized.

- **Action**: `speed audit specs/tech/my-feature.md`
- **Result**: SPEED checks your spec against the official template and warns you if the feature is **too big** (sizing warning). If a spec is too large, split it now to avoid context overload later.

## Phase 2: The Pre-Plan Workflow (SPEED)
Once you have an initial direction, run the formal SPEED pre-plan battery to ensure your specifications are high-fidelity and vision-aligned.

1.  **Validate**: `speed validate specs/` - Catches orphans, contradictions, and missing links across your product, tech, and design specs.
2.  **Guard**: `speed plan <spec>` - This automatically triggers the **Pre-Plan Guardian Gate**, which uses the Product Guardian agent to check if your technical proposal actually aligns with the `overview.md` vision.
3.  **Verify**: `speed verify` - An adversarial "blind check" where an agent verifies the task DAG against the spec without seeing the Architect's reasoning.

## Phase 3: Monitoring the Fleet (TMUX)
This is where the **Ghostty-style TMUX** setup shines. Your screen becomes a command center:

- **Window 1 (Main)**: Your primary editor (Neovim/Helix) stays in the `bookshelf` root.
- **Window 2 (Monitor)**: `speed status --verbose`
    - You see Agent-1 (Developer) implemented the search endpoint in a worktree.
    - You see Agent-2 (Reviewer) catches an off-by-one error in the pagination.
- **Window 3 (Claude Help)**: Keep a Claude Code instance ready in a side pane for quick "How do I..." questions during implementation if you need to manually intervene.

## Phase 4: Quality Gates & Integration
As tasks complete, SPEED's **Quality Gates** run within their isolated worktrees.

- **Failure Analysis**: If a test fails, the **Failure Analyst** agent reports it to your TMUX log window.
- **Merge**: Once all gates are green, `speed integrate` merges the worktree branches back to `main`.

## Summary Layout
Using the Ghostty-style splits:
```text
+-----------------------------------------------------------+
| [SPEED] [bookshelf] [L1:Index]                            |
+-----------------------------+-----------------------------+
|                             |                             |
|          EDITOR             |       SPEED LOGS            |
|       (Neovim/Helix)        |    (speed status)           |
|                             |                             |
+-----------------------------+-----------------------------+
|        CLAUDE CODE          |       SHELL / TESTS         |
|      (Ad-hoc probing)       |      (Manual Check)         |
+-----------------------------+-----------------------------+
```
