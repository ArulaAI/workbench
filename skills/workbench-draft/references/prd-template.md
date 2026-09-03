# PRD Composition Contract

Generate a decision document, not an interview transcript, discovery report,
test plan, or implementation plan. Preserve confirmed intent, remove repetition,
and keep detail proportional using [proportionality.md](proportionality.md).

## Required structure

```markdown
# PRD: <Outcome-oriented title>

| Status | Owner | Updated |
|---|---|---|
| Draft | <owner> | <date> |

## Summary
<Two or three sentences: user, problem, proposed outcome, and boundary.>

## Problem & Evidence
<Concise problem statement.>

- <Up to three strongest evidence points with links where available.>
- **Assumption:** <Clearly label unvalidated claims.>

## Hypothesis
If <change>, then <observable behavior or outcome>, because <evidence-backed reason>.

<For a material bet, add one falsification condition.>

## User Stories

| ID | Story | Priority |
|---|---|---|
| US-1 | As a <user>, I want <outcome>, so that <benefit>. | Must |

## Requirements & Acceptance

| ID | Story | Product behavior | Done when |
|---|---|---|---|
| REQ-1 | US-1 | <Observable obligation, not implementation> | <Pass/fail acceptance condition> |

## Scope

| Included | Not included |
|---|---|
| <What ships> | <Explicit exclusion and, when useful, why> |

## Guardrails / Must Not Regress

| ID | What must remain true | How it will be verified |
|---|---|---|
| GR-1 | <Protected behavior, outcome, or constraint> | <Observable check or measure> |

## Delivery, Risks & Open Questions

**Appetite:** <Time or investment boundary, when known>  
**Dependencies:** <Only material dependencies, or None>  
**Delivery notes:** <Rollout, migration, reversibility, or ownership only when material>

| ID | Type | Item | Impact or decision blocked | Owner |
|---|---|---|---|---|
| RISK-1 | Risk | <Material uncertainty or failure mode> | <Impact> | <Owner> |
| OQ-1 | Open question | <Decision still needed> | <What it blocks> | <Owner> |

## Success

| ID | Outcome or signal | Target | Window | Owner |
|---|---|---|---|---|
| SM-1 | <Post-launch behavior or lightweight signal> | <Target or provisional> | <Window> | <Owner> |

## References

- <Evidence, related decision, design, RFC, eval, or implementation artifact>
```

## Composition rules

- Write the Summary last. Do not introduce scope that is absent elsewhere.
- Keep Problem & Evidence about the current pain, not the proposed feature.
- Use one falsifiable hypothesis for a focused PRD. Do not treat a desired mental
  state as an observable outcome.
- Write stories around user outcomes, not endpoints, screens, or validation
  cases. Do not create one story per requirement.
- Combine requirements and acceptance to avoid restating behavior in two
  sections. Each Must story must be covered by at least one requirement.
- Keep technical design out of product behavior unless the implementation is a
  product constraint or public contract.
- Use Guardrails only for behavior, value, or safety that must not regress.
  Do not duplicate new-feature acceptance criteria. If no feature-specific
  guardrail exists, say that the existing regression baseline applies.
- Put only material readiness information in Delivery, Risks & Open Questions.
  Do not create separate assumption, dependency, rollout, research, analytics,
  or risk essays for a localized change.
- Distinguish pre-launch acceptance from post-launch success. Never invent a
  target; mark it `provisional`, name its owner, or use a justified lightweight
  signal when dedicated analytics would be disproportionate.
- Keep stable IDs once published. Append new IDs; never renumber an item cited
  by another artifact.
- Link detailed flows, test matrices, research, designs, RFCs, eval sets, ADRs,
  and rollout plans instead of embedding them.
- Omit empty table rows. A mandatory section may contain one honest sentence
  saying no feature-specific item was identified.

## Confidence-aware drafting

Generate the provisional PRD before clarification is complete. Use the internal
coverage assessment without printing bare numeric scores in the document:

- `confirmed` or `evidence_backed`: state the supported content directly;
- `inferred`: propose content and label it for review;
- `not_material`: use a concise baseline statement instead of asking a question;
- `unresolved` with low impact: record an open question or reviewable inference;
- `unresolved` with high impact: mark the affected section unresolved and ask a
  contextual clarification.

Surface no more than three high-value clarifications. Reassess after each answer
and remove any unsurfaced question that the new evidence resolves. Regenerate
the affected sections while preserving the rest of the draft.

## AI-agent extension

Add this extension only when the product interprets goals, selects actions, or
produces nondeterministic output. Do not add it to ordinary deterministic PRDs.

### Context & Boundaries

- Runtime context: data, tools, authoritative sources, freshness, and excluded
  information.
- Permissions: actions allowed without approval; unlisted actions default to no.
- Human gates: explicit actions and numeric thresholds requiring approval.
- Logging: inputs or references, context/model versions, tool calls, approvals,
  outcomes, errors, retention, and sensitive-data handling. Do not require hidden
  model reasoning.
- Escalation and fallback: owner, trigger, response expectation, and safe failure
  behavior.

Keep deterministic controls in Requirements & Acceptance. Summarize variable-
output thresholds there using durable `EVAL-` IDs and link the detailed eval set.

## ProductSpec alignment

Apply ProductSpec's useful mechanics: durable `AC-`, `SM-`, and `EVAL-` IDs;
pre-launch acceptance versus post-launch success; provisional targets rather
than invented numbers; and linked evidence. A normal Workbench `prd.md` is not
automatically a ProductSpec v0.1 file. Only claim conformance when explicitly
exporting `.product-spec.md` with ProductSpec's required section order and
structured fenced blocks, then validate it with the ProductSpec parser.
