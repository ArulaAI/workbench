---
title: Design Philosophy
description: Why SPEED exists and the five goals that drive every architectural decision.
sidebar:
  order: 2
---

The [manifesto](/docs/manifesto/) fits on one screen. This page expands on the reasoning: the organizational problem SPEED addresses, and the five goals that translate those beliefs into architecture.

## The Alignment Problem

Every product team claims to value collaboration. In practice, what passes for collaboration is often just relationships.

People with the strongest interpersonal skills extract the most from large organizations. That's natural, and it isn't inherently bad. But when organizational silos separate engineers, product managers, designers, and leadership into different rooms with different tools and different definitions of "done," alignment stops being a process and becomes a social game. Who was in the meeting, who remembered to forward the context, and who has enough political capital to push back on a requirement that doesn't make sense?

Anyone who's worked in a team larger than a dozen people recognizes the ground truth: decisions move slowly, context fragments across teams and tools, meetings multiply without resolving, and the same conversations recur in different rooms with different participants.

## The Cost of Scale

Communication channels grow as n(n-1)/2. A 10-person team manages 45 channels; scaling to 250 people produces 31,125. Each channel is a surface where context can leak, mutate, or vanish.

More people, more channels, more surfaces, more opportunities for signal to degrade before it reaches the person who needs it.

## The AI Paradox

AI amplified this dynamic rather than solving it.

Code generation accelerated tenfold, but PR review times spiked 91% after widespread adoption. The bottleneck migrated downstream, where it costs more and hides better. **Cognitive Debt** is what accumulates: the mental tax of auditing code you didn't write, from a process you can't inspect, against requirements that were already fragmenting before they reached you.

Generating more code faster into an organization that already struggles with alignment just creates more surfaces for context to leak.

## The Thesis

Product thinking, engineering depth, design craft: these capabilities matter more than ever. The talent isn't the problem.

Context and intelligence break down at scale. Requirements lose fidelity crossing silo boundaries, design intent dissolves during implementation, and integration reveals misalignments that weeks of meetings failed to surface. SPEED exists to make alignment structural instead of relational, so that the talent in the organization can do the work it was hired to do.

## Five Goals

Ordered by the severity of their failure, not by aspiration. Each goal addresses a specific way that context and alignment degrade.

Meta's CCA study grounds the overall approach: context management alone added +6.6pp to resolve rate, while tool-use conventions contributed +7.0pp (the largest single factor). Sonnet with superior scaffolding consistently outperformed Opus with weaker scaffolding.

### 1. Never Silently Wrong

Silent failure is the most damaging class of error. Once a user detects that an agent produced output that looked correct but diverged from the spec, the value of automation collapses to zero.

Verification is prioritized over generation. Every stage passes through four validation tiers:

| Tier | Method | Verification Mechanism |
|---|---|---|
| 1 | Deterministic | Lint, typecheck, and structural schema validation |
| 2 | Criteria-driven | Machine-verifiable rules extracted from acceptance criteria |
| 3 | Semantic | LLM-based review against original product requirements |
| 4 | Traceability | End-to-end mapping from spec section to task ID to commit hash |

Ternary reporting: **Pass**, **Fail**, or **Unverifiable**. Unverifiable states are surfaced for human judgment, never promoted to a silent pass.

### 2. Failure Is Informative

Distinguishing pipeline errors from task complexity is what makes an orchestrator improvable. Without that distinction, failure data is noise.

| Metric | Pipeline Failure | Complexity Failure |
|---|---|---|
| **Primary Cause** | Missing context or bad decomposition | Novel logic or ambiguous requirements |
| **Responsibility** | SPEED must be fixed | The Architect or User must refine the spec |
| **Detection** | Correlation with dropped files in `budget.json` | Context was present; the agent hit a logic cap |

The [context pipeline](/docs/architecture/context-pipeline/) records every scoping decision. If a developer agent fails because it cannot find a symbol in a file that Layer 2 discarded, the system classifies the failure as a pipeline context gap. Evidence, not intuition, drives improvement.

### 3. Scaffolding Carries the Weight

Exploration scales poorly. Agents that spend turns reading files to build a mental model are burning budget on work the infrastructure should have done.

Before a developer agent starts, the pipeline:
- Parses the entire codebase with tree-sitter
- Maps symbols and relationships in the **Codebase Semantic Graph (CSG)**
- Generates compressed file skeletons for interfaces

Each agent starts with a pre-loaded workspace: full source for modified files, 1-hop callers/callees from the CSG, and skeletons for 2-hop dependencies. Code gets written from the first turn because infrastructure provides the orientation that agents usually earn through expensive exploration.

### 4. Right Context, Right Format, Right Stage

Information needs vary by stage. Feeding the full codebase to every agent creates noise and increases hallucination risk.

| Stage | Information Priority | Excluded Data |
|---|---|---|
| **Architect** | Domain clusters and coupling patterns | Individual function bodies |
| **Developer** | 1-hop caller/callee source and rationale | Cross-task analysis and full schemas |
| **Reviewer** | Blast radius and criteria mapping | Upstream architectural assumptions |

The 3-layer context architecture projects codebase data into stage-specific formats. Architects receive domain density and symbol counts for decomposition, while developers get raw source and technical rationale for implementation.

### 5. Scale Through Context, Not Exploration

Exploration-based agents degrade linearly with codebase size. Meta's research measured multi-file resolve rates dropping from 57% to 44% as project complexity increased from 2 files to 6.

SPEED decouples performance from project scale. The pre-computed index grows with the codebase, but the projected context window delivered to agents stays within the high-fidelity zone. A 500-line project and a 500,000-line project produce identical agent experiences.
