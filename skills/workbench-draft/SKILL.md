---
name: workbench-draft
description: >
  Run a guided PRD, design, RFC, or evaluation interview and draft the matching
  SPEED spec from the answers, then self-review it. Use when asked to "draft a
  spec", "run the interview", or "start a PRD/design/RFC".
---

# workbench-draft

Guide the author through a structured interview and produce a reviewable SPEED
spec. This Phase-1 package establishes the skill contract; the full question
banks are delivered with the guided-authoring workflow (see
`specs/product/define-module/03-guided-authoring.md`).

## When to invoke

- The user asks to draft or spec a PRD, design, RFC, or evaluation.
- A product command such as `speed draft <type> <feature>` routes here (later phase).

## When NOT to invoke

- Implementation, debugging, or code review tasks — those are other skills.

## Inputs

- Artifact type: one of `prd`, `design`, `rfc`, `eval`.
- Feature name (kebab-case). Ask for anything not supplied by the caller.

## Workflow

1. Determine the artifact type and feature name. Ask only for what you were not given.
2. Interview the author one question at a time, carrying prior answers forward so
   each question builds on the last.
3. Draft the spec from the matching SPEED template under `templates/`, mapping each
   answer to its target section.
4. Self-review the draft for placeholders, contradictions, ambiguity, and scope creep.
   Present findings and resolve blocking gaps before handoff.

## Outputs

- A drafted spec written to the correct `specs/` location, ready for human review.

## Completion gate

- Every required template section is filled. Unresolved items are listed explicitly
  as open questions rather than left blank.

## Failure behavior

- If a required input cannot be resolved, stop and ask; do not invent answers.
- Human review and approval remain separate from generation. This skill never
  approves its own output.
