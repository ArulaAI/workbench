---
title: Product Guardian
description: The Product Guardian guards the product vision, anti-goals, and personas at three insertion points.
---

## Mission

The Product Guardian is the keeper of the product vision. It evaluates every feature spec, task plan, code diff, and integration output against the product's identity, positioning, principles, and anti-goals. Scope creep is the default trajectory of any product. Every individual feature request seems reasonable; collectively, they turn a differentiated product into another generic tool. The Product Guardian catches drift before it compounds.

## Invocation

| Property | Value |
|----------|-------|
| Command | `speed guardian [file]` |
| Model tier | `support_model` (Sonnet) |
| Trigger | Automatic at three insertion points, or manual via `speed guardian` |

Two modes: `speed guardian <file>` evaluates any file against the product vision. `speed guardian` (no argument) evaluates the current feature's spec and task plan.

## Inputs

| Input | Source | Description |
|-------|--------|-------------|
| Product vision document | `specs/product/overview.md` | Vision, positioning, anti-goals, personas, exclusions |
| Artifact under review | Varies by insertion point | Feature spec, task plan, code diff, or integrated output |

## Outputs

| Output | Location | Description |
|--------|----------|-------------|
| Vision alignment report | Stdout (JSON) | Status, per-check results, flags with vision references |

## Process

The Product Guardian reads the product vision document in full before evaluating anything. It looks for these sections (headings may vary):

- Vision & Core Mission
- Competitive Positioning
- Key Product Decisions
- Won't Have / Exclusions
- Personas
- Anti-Goals
- Risks

Then it runs six checks against the artifact under review:

1. **Core mission test.** Every feature, data model field, and UI element must serve the product's core mission. If it does not, it needs a strong justification or it does not belong.

2. **Behavioral test.** Apply the vision document's decision framework (if present) to distinguish desired behavior from undesired behavior. Features aligning with desired behavior pass; features rewarding undesired behavior are flagged.

3. **Scope violation check.** Check every proposed feature against the Won't Have / Exclusions table. Renamed concepts are the most dangerous form of scope creep: the label changes but the drift is the same.

4. **Persona grounding test.** Every feature must serve at least one persona in a way connected to the core value proposition. Features that serve no defined persona need justification.

5. **Differentiation preservation check.** Identify the differentiation pillars from the vision document. If proposed work weakens any pillar, flag it.

6. **Scope appropriateness check.** If the vision document defines priority levels (e.g., MoSCoW), check whether proposed work is at the right priority level given current progress. Lower-priority work appearing before higher-priority work is complete gets flagged.

## How It Works

The Guardian runs through a shared function `_run_guardian` (`lib/shared.sh:28-146`) regardless of insertion point. The ad-hoc command `speed guardian` wraps this function with file loading and optional task plan inclusion.

```
_run_guardian(check_type, content, label)
    │
    ├─ 1. Load product vision
    │      └─ specs/product/overview.md (required)
    ├─ 2. Build guardian message
    │      ├─ Vision document (source of truth)
    │      └─ Artifact under review (varies by insertion point)
    ├─ 3. Send to Guardian agent (Sonnet, read-only)
    ├─ 4. Parse JSON report
    └─ 5. Route by status
           ├─ aligned  → return 0 (proceed)
           ├─ flagged  → return 2 (warn, print flags)
           ├─ rejected → return 1 (block, print violations)
           └─ unknown  → return 3 (unparseable output)
```

### Vision loading

Lines 33-37 require `specs/product/overview.md` at the project root. If the file is missing, the Guardian check is skipped entirely (returns 0). The entire vision document is injected into the prompt as the source of truth.

### Prompt assembly

Lines 42-50 build a minimal prompt: vision document + artifact under review + check type label. There is no Layer 1/Layer 2 context. The Guardian operates purely from the vision document and the artifact, which keeps it independent from the codebase analysis pipeline.

### Agent execution

Lines 55-63 call `claude_run` with the product-guardian agent definition, Sonnet model, and read-only tools. The agent reads the vision document first, identifies its sections (Vision, Positioning, Decisions, Won't Have, Personas, Anti-Goals, Risks), then runs six checks against the artifact.

### Status routing

Lines 90-144 map agent output status to exit codes:

| Status | Exit code | Behavior |
|--------|-----------|----------|
| `aligned` | 0 | Log success, continue pipeline |
| `flagged` | 2 | Log warning, print flag details, continue pipeline |
| `rejected` | 1 | Log error, print critical violations + Won't Have matches, block pipeline |
| Unknown/parse failure | 3 | Log warning with first 3 lines for diagnosis, continue pipeline |

Results are saved to `${LOGS_DIR}/guardian-${check_type}-${timestamp}.json` with log pruning.

### Ad-hoc command

`cmd_guardian` (`lib/cmd/guardian.sh:4-73`) supports two modes:

1. **File mode:** `speed guardian <file>` evaluates any file against the vision
2. **Feature mode:** `speed guardian` (no argument) evaluates the current spec + task plan summaries

## Insertion Points

| Gate | Timing | Input | Question |
|------|--------|-------|----------|
| Pre-plan | Before `speed plan` | Feature spec | Should this be built at all? |
| Post-review | After `speed review` | Code diff | Did the implementation stay true to the spec? |
| Post-integration | After `speed integrate` | Integrated feature | Does the result still align with the vision? |

## Worked Example

A `library-app` feature spec proposes adding a "Social Reading" module where users can follow each other, share reading lists, and comment on books. The product vision document (`specs/product/overview.md`) contains:

- **Core Mission:** "Help librarians manage lending operations for small community libraries"
- **Won't Have:** "Social networking features, user-to-user messaging, public profiles"
- **Personas:** "Librarian (manages catalog), Borrower (borrows/returns books)"

### Pre-plan Guardian gate

`speed plan` triggers `_run_guardian "pre-plan"` with the spec content.

### What the agent returns

```json
{
  "status": "rejected",
  "vision_alignment": {
    "core_mission_served": false,
    "reasoning": "Social reading features serve reader engagement, not library management. The core mission is helping librarians manage lending, not building a reading community."
  },
  "behavioral_test": {
    "verdict": "misaligned",
    "reasoning": "Following users and sharing lists encourages browsing behavior. The vision targets operational efficiency for librarians."
  },
  "scope_violations": [
    {
      "feature": "User following and reading list sharing",
      "maps_to": "Social networking features",
      "severity": "critical",
      "reasoning": "Follow/share mechanics are social networking by another name. The Won't Have list explicitly excludes this."
    }
  ],
  "persona_grounding": [
    {"persona": "Librarian", "served": false, "use_case": "No operational benefit"},
    {"persona": "Borrower", "served": false, "use_case": "Reading lists serve readers, not borrowers managing loans"}
  ],
  "differentiation_impact": {
    "pillars_affected": ["Simplicity", "Operational focus"],
    "direction": "weakens",
    "reasoning": "Adding social features dilutes the simple, ops-focused tool into a generic reading app."
  },
  "scope_check": {
    "priority_level": "wont",
    "appropriate": false,
    "reasoning": "Social networking is explicitly in the Won't Have list."
  },
  "flags": [
    {
      "severity": "critical",
      "description": "Social reading maps directly to excluded 'Social networking features'",
      "vision_reference": "Won't Have: Social networking features, user-to-user messaging, public profiles",
      "recommendation": "Remove the Social Reading module. If reading lists serve librarians (e.g., curated recommendation lists managed by staff), reframe the feature around that use case."
    }
  ],
  "summary": "Rejected. Social reading is a renamed version of excluded social networking features."
}
```

### What the user sees

```
  Running pre-plan vision check...
  ✗ Guardian: REJECTED — Rejected. Social reading is a renamed version of excluded social networking features.

  Critical Violations:
    Social reading maps directly to excluded 'Social networking features'
    Spec: Won't Have: Social networking features, user-to-user messaging, public profiles

  Won't Have Violations:
    User following and reading list sharing → maps to Won't Have: Social networking features

  Product Guardian REJECTED this spec — it conflicts with the product vision
  Review the guardian report and either:
    1. Fix the spec to align with the vision
    2. Override with SKIP_GUARDIAN=true speed plan ... (use with caution)
```

## Constraints

- Read-only access. Cannot modify files.
- Quote the vision document for every flag. If a specific text cannot be cited, the concern may be fabricated.
- Renamed concepts get the same treatment as the excluded feature they resemble. The mechanism matters, not the label.
- Be inclusive by default. If a feature implicitly advantages one user type over others the vision intends to serve, flag it.
- The vision document can be wrong. If it contradicts itself, say so. But distinguish between "the vision is wrong" and "I disagree with the vision."

## Output Schema

```json
{
  "status": "aligned | flagged | rejected",
  "vision_alignment": {
    "core_mission_served": true,
    "reasoning": "How this work serves or doesn't serve the core mission"
  },
  "behavioral_test": {
    "verdict": "aligned | misaligned | neutral",
    "reasoning": "Why this aligns or conflicts with the behavioral framework"
  },
  "scope_violations": [
    {
      "feature": "What was proposed",
      "maps_to": "Which excluded item it resembles",
      "severity": "critical | warning",
      "reasoning": "Why this resembles an excluded feature"
    }
  ],
  "persona_grounding": [
    { "persona": "Persona name", "served": true, "use_case": "How this serves their core need" }
  ],
  "differentiation_impact": {
    "pillars_affected": ["affected pillars"],
    "direction": "strengthens | neutral | weakens",
    "reasoning": "How and why"
  },
  "scope_check": {
    "priority_level": "must | should | could | wont",
    "appropriate": true,
    "reasoning": "Whether this work is at the right priority level"
  },
  "flags": [
    {
      "severity": "critical | warning | note",
      "description": "What's concerning",
      "vision_reference": "Exact quote from the vision document",
      "recommendation": "What to do about it"
    }
  ],
  "summary": "1-2 sentence overall assessment"
}
```

**Status definitions:** `aligned` means consistent with the vision, zero critical flags. `flagged` means warnings exist that should be reviewed before proceeding. `rejected` means the work violates a product principle, introduces an excluded feature, or fundamentally misaligns with the vision.
