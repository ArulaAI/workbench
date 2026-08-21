---
title: The Context Pipeline
description: How SPEED builds, scopes, and delivers high-fidelity context to every agent stage.
sidebar:
  order: 3
---

SPEED uses a 3-Layer architecture to solve the problem of agent orientation. Instead of asking agents to explore a codebase using tools, the pipeline pre-computes the necessary context and delivers it as a static, high-fidelity prompt.

For the implementation-level reference (assembly functions, budget allocation tables, scoping process), see the [Architecture: Context Pipeline](/docs/architecture/context-pipeline/) page.

## The 3-Layer Architecture

The pipeline transforms raw source code into stage-specific instructions through three distinct transformations.

### Layer 1: Global Indexing (Deterministic)
Layer 1 is the "Never Silently Wrong" foundation. It indexes the entire codebase into a queryable **Codebase Semantic Graph (CSG)**. For details on how we extract these symbols, see the [Language Support Reference](/docs/api/language-support/).

1.  **Project Map**: A registry of every file, its language, and its categorical importance.
2.  **File Skeletons**: Compressed versions of source files containing only signatures and interfaces.
3.  **Spec-Codebase Alignment**: A mapping that confirms whether spec requirements match existing code.

### Layer 2: Per-Task Scoping (Dynamic)
Layer 2 narrows the global index for a specific task. It applies a "Graph Distance" algorithm to the CSG to select only relevant information.

| Distance | Delivery Strategy | Rationale |
|---|---|---|
| **0 Hops** | Full Content | The files the task will modify. |
| **1 Hop** | Full Content | Direct callers and callees that the agent needs to understand. |
| **2 Hops** | Skeleton | Interface awareness of neighbors without using the token budget. |
| **3+ Hops** | Dropped | Distant code that is unlikely to be relevant to the immediate task. |

Layer 2 also calculates a **Budget Plan**. If the selected files exceed the agent's context window, it systematically downgrades content (starting with the most distant hops) until the budget is met. Every cut is recorded in `budget.json` for later debugging.

### Layer 3: Assembly (Formatting)
Layer 3 is the final assembly stage. It takes the scoped data from Layer 2 and formats it into a prompt optimized for a specific agent role.

The assembly follows the core principle of **Intent before Detail**:
*   **Context First**: Who is the agent, what is the mission, and what is the rationale for this task?
*   **Constraints second**: What are the "never" rules (gate constraints, model limits)?
*   **Content last**: The raw source code and technical documentation.

## Contextual Specialization

Each agent stage receives a different "projection" of the same codebase data.

| Stage | High-Priority Data | Filtered Data |
|---|---|---|
| **Architect** | CSG domain clusters and symbol counts. | Raw function implementations. |
| **Developer** | Full 1-hop source and task rationale. | Cross-task analysis and global schemas. |
| **Reviewer** | Blast radius and spec verification matrix. | Internal task-level assumptions. |

## Resilience and Budgeting

When content exceeds the configured token budget, the pipeline makes evidence-based cuts:
1.  **Skeleton Tier**: 2-hop neighbor files are dropped first.
2.  **Size Tier**: Large 1-hop files are downgraded from full content to skeletons.
3.  **Last Resort**: The most distant skeletons are truncated with a pointer for the agent to use a "Read" tool if necessary.

This structured approach ensures that developer agents never start a task in the dark. Infrastructure carries the weight of orientation, allowing the LLM to focus entirely on implementation.
