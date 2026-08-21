---
title: Agent Fleet
description: Overview of the SPEED agent fleet, organized by mission area.
---

SPEED orchestrates 13 specialized agents grouped into four fleets. Each agent has a narrow mission, fixed inputs and outputs, and runs on a designated model tier. For how these agents coordinate during execution, see [Agent Orchestration](/docs/architecture/agent-orchestration/).

## Planning Fleet

Agents that analyze specifications and produce the task plan before any code is written.

| Agent | Mission | Model | Invoked By |
|-------|---------|-------|------------|
| [Architect](/docs/api/agents/architect/) | Decomposes specs into a task DAG with traceability contracts | `planning_model` (Opus) | `speed plan` |
| [Validator](/docs/api/agents/validator/) | Cross-references all specs for consistency before planning | `support_model` (Sonnet) | `speed validate` |
| [Plan Verifier](/docs/api/agents/plan-verifier/) | Adversarial audit of the Architect's plan against the original spec | `planning_model` (Opus) | `speed verify` |
| [Spec Auditor](/docs/api/agents/spec-auditor/) | Structural audit of a spec file against its type template | `support_model` (Sonnet) | `speed audit` |

## Execution Fleet

Agents that implement, review, and guard the product vision during development.

| Agent | Mission | Model | Invoked By |
|-------|---------|-------|------------|
| [Developer](/docs/api/agents/developer/) | Implements a single task on an isolated git worktree branch | `support_model` (Sonnet) | `speed run` |
| [Reviewer](/docs/api/agents/reviewer/) | Checks task diffs against the original product spec | `support_model` (Sonnet) | `speed review` |
| [Product Guardian](/docs/api/agents/product-guardian/) | Guards product vision, anti-goals, and personas at three insertion points | `support_model` (Sonnet) | `speed guardian` |

## Resilience Fleet

Agents that diagnose failures, decide recovery strategies, verify cross-task coherence, and merge branches.

| Agent | Mission | Model | Invoked By |
|-------|---------|-------|------------|
| [Debugger](/docs/api/agents/debugger/) | Root cause analysis on failed tasks with targeted fix instructions | `support_model` (Sonnet) | Automatic on failure |
| [Supervisor](/docs/api/agents/supervisor/) | Decides recovery strategy after failures and detects cross-task patterns | `planning_model` (Opus) | Automatic on failure |
| [Coherence Checker](/docs/api/agents/coherence-checker/) | Verifies independently built branches compose correctly before integration | `support_model` (Sonnet) | `speed integrate` (pre-merge) |
| [Integrator](/docs/api/agents/integrator/) | Merges validated branches in dependency order with regression testing | Deterministic (no LLM) | `speed integrate` |

## Security & Defect Fleet

Agents that scan for vulnerabilities and triage defect reports.

| Agent | Mission | Model | Invoked By |
|-------|---------|-------|------------|
| [Security Auditor](/docs/api/agents/security-auditor/) | Scans feature code for OWASP vulnerabilities across SAST, SCA, and secrets dimensions | `support_model` (Sonnet) | `speed security` |
| [Triage](/docs/api/agents/triage/) | Investigates defect reports and classifies complexity for fix pipeline routing | `support_model` (Sonnet) | `speed defect` |

## Model Tiers

SPEED uses three model tiers to balance capability against cost.

| Tier | Default Model | Used For |
|------|---------------|----------|
| `planning_model` | Opus | Agents making architectural decisions: Architect, Plan Verifier, Supervisor |
| `support_model` | Sonnet | All other agents: review, debugging, security scanning, triage |
| Deterministic | None (no LLM) | The Integrator runs git merge operations without an LLM |

The `--model` flag on `speed run` overrides the Developer's model tier. The `--escalate` flag on `speed retry` upgrades a failed task from `support_model` to `planning_model`.
