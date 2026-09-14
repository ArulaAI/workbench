# ADR Composition Contract

Generate a decision record, not a PRD or RFC excerpt. One ADR covers one
promoted candidate. Preserve the candidate's original context, decision, and
consequences; do not soften or expand a decision beyond what was confirmed.

## Required structure

```markdown
# ADR: <Outcome-oriented decision title>

**Status:** Draft — requires human review
**Candidate:** <ADRC-id>
**Source question:** <the P-Qn or T-Qn the decision was raised from>

## Context
<What forced this decision. The constraint or problem, not the topic area.>

## Decision
<The concrete, checkable choice that was made.>

## Alternatives Considered
<At least one real alternative and why it was rejected.>

## Consequences
<What this decision costs or rules out going forward.>

## Status
<Promoted from candidate <id>. Publication history, if any.>

## Related Requirements
<The PRD/RFC requirement or section IDs this decision governs, or state
that none apply yet.>
```

## Rules

- One ADR per promoted candidate. Do not merge multiple decisions into one
  document; a feature with several significant choices gets several ADRs.
- Do not present a rejected alternative as if it had been chosen, and do not
  invent an alternative the candidate never considered.
- A decision without a real cost or trade-off is usually not a decision worth
  an ADR. Say so in Consequences rather than inventing one.
- Keep `Related Requirements` traceable to real `REQ-`/`GR-`/section
  identifiers from the source PRD or RFC. Leave it explicit rather than
  guessed when no requirement is affected yet.
