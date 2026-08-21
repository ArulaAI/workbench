---
title: The SPEED Process
description: How SPEED replaces Agile ceremonies with specification-driven automation and three high-leverage human ceremonies.
sidebar:
  order: 3
---

A two-week sprint costs 16 to 32 hours of ceremony per person. Planning, standups, grooming, demos, retros, code review. Most of that time exists to synchronize context between people who are doing the work.

SPEED removes that assumption. When execution belongs to agents on isolated branches with pre-loaded context and machine-verifiable criteria, most coordination ceremonies lose their structural reason to exist. Three remain.

## Define, Execute, Judge, Learn

![The SPEED Development Cycle](/images/speed-development-cycle.svg)

Two phases are human. Two are system. The handoffs are artifacts, not meetings.

**Define** is where humans write specifications together. PMs, engineers, and designers collaborate on structured documents with machine-verifiable acceptance criteria. SPEED feeds the session with codebase reality: the semantic graph shows which domains are coupled, which symbols carry high blast radius, and where the proposed feature lands relative to existing architecture. *Context delivered is worth 10 times context discovered* applies to the people writing specs, not just the agents executing them.

**Execute** is fully automated. Seven stages (validate, plan, verify, run, review, coherence, integrate), each gated by checks no LLM can bypass. Diffs must be non-empty. Declared files must exist. Scope must match ownership declarations. Secrets are blocked. The system produces evidence at every step. About 5% of tasks escalate to a human due to genuine complexity; the rest complete autonomously.

**Judge** is where humans return. Not a sprint demo where someone walks you through what they built. A structured review of verification evidence: pass/fail/unverifiable per acceptance criterion, Product Guardian findings with spec quotes, coherence reports, security audits. Humans judge outcomes, not effort.

**Learn** closes the loop. The system extracts observations from every pipeline artifact, synthesizes them into agent-specific learnings, and injects them into the next run automatically. Humans curate which patterns to codify and which to discard. Intelligence compounds because the structure retains it, not because someone remembered to update a wiki.

## Three Ceremonies, Not Thirteen

![The three SPEED ceremonies](/images/speed-three-ceremonies.svg)

Agile fills the calendar with recurring rituals because human coordination decays without them. SPEED has three ceremonies, all event-driven. None are weekly. None are on the calendar. They fire when the process needs human judgment, not when a timebox expires.

### The Spec Session

Sprint planning takes 2 to 4 hours and produces a backlog of estimated tickets. Grooming takes another hour or two. Together they answer: what are we building, how big is it, who's doing what?

The Spec Session answers a harder question: what exactly does this feature do, for whom, and how will a machine verify it? The team writes a structured specification with acceptance criteria, data model contracts, and scope boundaries. SPEED provides the codebase semantic graph, blast radius data, and convention learnings from prior features so the team writes against reality, not assumptions.

No story points. No velocity negotiation. The specification is the contract. Its precision determines the output ceiling.

### The Outcome Review

Sprint demos take 1 to 2 hours. PR review takes 5 to 10 hours per sprint across the team. QA adds more. All of it tries to answer: did we build what we said we'd build?

The Outcome Review answers that question with evidence. The verification report shows pass/fail/unverifiable per acceptance criterion. The Product Guardian quotes the spec when flagging drift. The coherence checker confirms independently-built pieces compose correctly. The security audit lists findings by OWASP category with file and line number.

Nobody rehearses a walkthrough. The system presents what it verified, what it flagged, and what it could not determine. Humans render judgment.

### Learning Curation

Retros take 1 to 1.5 hours and produce action items like "communicate better" and "update the wiki." Most decay within a week.

Learning Curation works from evidence, not memory. SPEED's 14-step extraction pipeline has already read every pipeline artifact: task outcomes, review findings, guardian verdicts, gate failures, context effectiveness, decomposition quality, human corrections. Synthesis has routed observations to agents, deduplicated, resolved conflicts, and enforced token budgets.

The human reviews what the system surfaced. Which conventions to codify. Which patterns to break. Which spec templates need refinement. Action items are structural changes to the process, not behavioral aspirations.

## The Comparison

![Ceremony hours: Agile vs SPEED](/images/speed-ceremony-comparison.svg)

| Agile Ceremony | Hours/Sprint | SPEED Equivalent |
|---|---|---|
| Sprint Planning | 2-4h | Spec Session (per feature, not per sprint) |
| Daily Standup | 1.25-2.5h | `speed status` (real-time, no meeting) |
| Backlog Grooming | 1-2h | `speed validate` + `speed audit` |
| Sprint Demo | 1-2h | Outcome Review (evidence, not walkthrough) |
| Sprint Retro | 1-1.5h | Learning Curation (evidence, not memory) |
| PR Code Review | 5-10h | `speed review` + grounding gates |
| Estimation/Pointing | 1-2h | Eliminated (spec precision replaces story points) |
| Design Review | 1-2h | Absorbed into Spec Session |
| QA Handoff | 0.5-1h | Eliminated (4-tier verification is automatic) |
| Bug Triage | 0.5-1h | `speed status` + failure classification |
| Release Planning | 1-2h | `speed integrate` (automated coherence) |
| Cross-team Sync | 0.5-1h | Eliminated (isolated branches, no coordination) |
| Stakeholder Update | 0.5-1h | Outcome Review artifacts |
| **Total** | **16-32h** | **3-5h** |

The difference is not just fewer hours. The hours that remain are specification and judgment, the highest-leverage work each role was hired to do.

## What Changes

**If you're a PM**, you stop writing JIRA tickets and start writing structured specifications with acceptance criteria. You stop attending standups and start reviewing context alignment reports that show what the codebase actually looks like relative to what you're proposing. You stop demoing and start judging verification evidence. The job becomes: define precisely, evaluate outcomes.

**If you're an engineer**, five hours of weekly meetings disappear. You handle the roughly 5% of tasks that escalate due to genuine complexity, where human judgment and creativity matter most. You review task DAGs for decomposition quality and design the verification gates that keep the system honest. The job becomes: architect the hard parts, govern the system's learning.

**If you lead a team**, velocity charts and sprint commitments are replaced by verification reports and failure classification. You can see whether failures are pipeline problems (bad context, wrong decomposition) or complexity problems (genuinely hard tasks that need better specs or human intervention). You curate learnings and evaluate whether the system improves over time. The job becomes: govern the process, not manage people through it.

## What SPEED Doesn't Replace

Product discovery. Figuring out *what* to build, who needs it, and whether it matters. SPEED starts after that decision is made.

Stakeholder relationships. Board updates, cross-team negotiations, organizational buy-in. Political and interpersonal work stays political and interpersonal.

Production operations. Deployment, monitoring, incident response. SPEED produces verified code. Getting it live and keeping it running is a different discipline.

SPEED changes what happens between "we decided what to build" and "it's verified and ready to ship." Everything before and after that window stays human.

## The Evidence

PR review times increased 91% after widespread AI code generation. The bottleneck moved downstream, where it costs more and hides better.

Meta's CCA ablation study: context management alone added +6.6 percentage points to resolve rate. Tool-use conventions contributed +7.0pp, the largest single factor. Sonnet with superior scaffolding consistently outperformed Opus with weaker scaffolding. The [manifesto](/docs/manifesto/) calls this *scaffolding carries the weight*. The [design philosophy](/docs/design-philosophy/) shows the full research.

Multi-file resolve rates dropped from 57% to 44% as project complexity grew from 2 to 6 files. Exploration-based agents degrade linearly with codebase size. SPEED's pre-computed context pipeline decouples performance from scale.
