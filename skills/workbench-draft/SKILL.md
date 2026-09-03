---
name: workbench-draft
description: >
  Generate and iteratively refine an evidence-labelled PRD or PRD-linked Design
  draft, using confidence-ranked clarifications without inventing product
  decisions. Use when the user asks to draft a PRD or design specification,
  continue product or design definition, answer guided-authoring questions, or
  run `workbench draft`.
---

# Workbench Draft

Generate evidence-labelled specifications from provided requirements,
repository evidence, confirmed answers, and clearly marked inferences. Require
Design to remain pinned to its generated PRD input.

## Draft contract

Read [references/proportionality.md](references/proportionality.md) before
generating any draft. Use the same core structure for every artifact and infer
the necessary depth from confirmed user impact, scope, dependencies,
reversibility, uncertainty, and risk. Never ask the user to choose a size or
expose an internal size label in the artifact.

For PRD generation, also read
[references/prd-template.md](references/prd-template.md) completely. Treat it as
the composition and quality contract. ProductSpec is an interoperability format,
not the PRD quality bar: reuse its durable-ID and acceptance/success mechanics,
but do not claim a Workbench `prd.md` conforms to ProductSpec unless it is
explicitly exported and validated as `.product-spec.md`.

Ask a concrete follow-up only when missing information would materially change
scope, safety, acceptance, or delivery. Otherwise draft from available evidence
and record the uncertainty as an open question.

For PRD interviews, read
[references/interview-planning.md](references/interview-planning.md) completely.
Treat question-bank entries as stable coverage definitions, not a fixed script.
Re-plan after every answer, vary the active question count, and contextualize the
next prompt from the feature and confirmed evidence.

Generate a provisional PRD as soon as intake evidence is available. Score each
coverage area using evidence confidence and decision impact. Ask only low-
confidence, high-impact clarifications, with no more than three surfaced
questions. Return the artifact while clarifications remain so the author can
review useful output immediately.

## Intake without arguments

Use the helper's `needs_input` result instead of inventing repository choices.

1. If the artifact is missing, run
   `python3 scripts/draft.py --project-root <project-root> --json` and show its
   artifact choices.
2. If `prd` is selected without a feature, run
   `python3 scripts/draft.py prd --project-root <project-root> --json`. Present
   the returned `new_prd_basics` form as one step with both required fields:
   `feature_slug` and `feature_description`. The description should briefly say
   who experiences the problem, what happens today, and the desired outcome.
   Do not search for, list, recommend, or preselect existing feature directories
   or specifications. Validate the slug without adding another question unless
   normalization changes it or it collides with existing workflow state.
   Start with:

   `python3 scripts/draft.py prd <feature_slug> --project-root <project-root> --feature-description <feature_description> --json`

   Treat the intake description as direct problem evidence. Do not ask P-Q1
   merely to repeat it. Show the provisional PRD and the highest-value
   unresolved clarification returned by the helper.
3. If `design` is selected without a feature, run
   `python3 scripts/draft.py design --project-root <project-root> --json`. Ask
   for the upstream PRD first. Accept a PRD attachment, path, or one of the
   returned valid guided PRDs; do not list unrelated feature directories. Derive
   the feature from canonical `specs/<feature>/prd.md` or its metadata. Only when
   it cannot be derived, ask the returned fallback feature-name question as the
   third step. Do not silently import an external PRD or bypass the helper's
   Product prerequisite gate.

## Workflow

1. After intake resolves the artifact and feature, run
   `python3 scripts/draft.py <artifact> <feature> --project-root <project-root> --json`.
   Design returns a prerequisite error until the same feature has a completed,
   hash-matching guided PRD draft; route the user to Product rather than
   creating an independent Design brief.
2. If the result status is `question`, show the provisional artifact path first,
   then exactly the returned question,
   purpose, completion evidence, suggested response, confidence, supporting
   sources, and evidence gaps. If `follow_up` is present, ask that one targeted
   follow-up and submit the reply with `--answer`; do not invent another probe.
   Do not present a partial or missing suggestion as repository fact.
3. Render the returned `response_control`. When its `input_type` is
   `single_select`, use the host platform's select UI so the author chooses an
   action instead of typing a command. Show only the options returned by the
   helper; never display an unavailable or disabled action:

   - Accept: when present, submit `--accept-suggestion` with the expected
     revision. The helper omits Accept unless `accept_ready: true`.
   - Edit suggestion: first submit `--edit-suggestion` with the expected
     revision. Then render the returned textarea with its `initial_value` and
     submit the edited text with `--answer`.
   - Reject: submit `--reject-suggestion`; then ask for the user's own answer.
   - Defer: submit `--defer`; required deferred questions block generation.

4. When `response_control.input_type` is `textarea`, use its prompt and initial
   value. Submit an edited or replacement answer with:

   `python3 scripts/draft.py <artifact> <feature> --project-root <project-root> --answer <answer> --expected-revision <revision> --json`

5. Re-plan after each answer. An unsurfaced question may disappear when another
   answer raises its confidence. The helper regenerates the PRD and self-reviews
   after material clarifications are resolved. If self-review reopens a
   question, show its
   `existing_answer` and `review_findings`, collect a revision, and regenerate.
6. Stop after at most two self-review passes. Return `drafted` when review passes,
   or `drafted_with_open_questions` with the remaining findings made explicit.
7. Return the reported artifact path and dashboard URL. State that the document
   is assembled from confirmed answers and report its self-review status.
8. When the user edits a section while reviewing the provisional PRD, map the
   edit to its stable coverage ID and submit it through the helper rather than
   changing generated Markdown:

   `python3 scripts/draft.py prd <feature> --project-root <project-root> --update-coverage <coverage> --answer <replacement> --expected-revision <revision> --json`

   Regenerate and show the resulting draft. The common section aliases accepted
   by the helper include problem, hypothesis, user stories, requirements,
   acceptance, scope, guardrails, delivery/risks/open questions, and success.

## Rules

- Use `scripts/draft.py` as the only interview, suggestion, state, and spec
  generation implementation. Do not reproduce that logic in the skill prompt or
  a CLI adapter; both entry points must call the packaged helper.
- Treat persisted interview state as authoritative. Never infer that a question
  is complete from conversation memory. Use `resume_step` and
  `current_question.response_control` to resume the exact saved interaction.
- Preserve question IDs and answer wording. Do not turn uncertain answers into
  confident requirements.
- Never tell the user there are eight fixed PRD questions. Stable coverage IDs
  exist for scoring and traceability; surface no more than three material
  clarifications and skip decisions already resolved or immaterial.
- Use `coverage.confidence`, `confidence_label`, `impact`, `basis`, and
  `question_value` to explain why a clarification was selected. Do not expose a
  bare score without its evidence basis.
- Keep `evidence_backed`, `inferred`, `not_material`, and `unresolved` distinct.
  Never render unresolved high-impact content as fact; mark it in the
  provisional PRD and ask its clarification.
- Ask one contextual product decision at a time. Do not assume multiple roles,
  permission differences, or jobs merely because a generic question mentions
  them.
- For authentication work, first clarify the supported sign-in method. Treat
  rollout to existing users as a backward-compatibility decision: ask how they
  will set up authentication and what happens to their existing account and
  data. Keep that answer user-confirmed unless durable evidence fully resolves
  it. Do not introduce sharing unless it exists in the requirement or product.
- Do not offer an "evidence-backed starter" when existing evidence does not
  answer the current question. Show the evidence gap and ask directly.
- Do not render the interview transcript as the PRD. Compose confirmed answers
  into the PRD contract, show uncertainty explicitly, and avoid repeating one
  decision across flows, requirements, acceptance, guardrails, and delivery.
- Keep stable artifact item IDs after publication. Add new IDs at the end; do
  not renumber cited `US-`, `REQ-`, `AC-`, `GR-`, `RISK-`, `OQ-`, `SM-`, or
  `EVAL-` items.
- Never invent evidence, targets, risks, dependencies, guardrails, or adjacent
  scope to make a section look complete.
- For Design, show the returned pinned PRD path, hash, and Product interview
  revision. Treat `upstream_changed` as blocking and preserve existing Design
  answers for later revalidation.
- Keep the persisted system suggestion separate from the human decision. Never
  describe an edited response as an accepted suggestion.
- Preserve the new-PRD description in the helper checkpoint. Treat it as direct
  problem evidence, while retaining provenance distinct from a confirmed
  clarification answer. If an empty revision-0 checkpoint already exists,
  attach the description and regenerate the provisional PRD.
- Persist every action transition, including selecting Edit before the edited
  text is submitted. Do not rely on the chat transcript to reconstruct an
  interrupted step.
- Ask at most one helper-provided targeted follow-up per question. Persist and
  resume it like every other interview transition.
- Repair self-review findings through their returned source question IDs. Never
  patch generated prose directly or run more than two review passes.
- On `revision_conflict`, reload status and show the changed checkpoint before
  asking the user to continue.
- Do not edit the generated Markdown directly. Resume the interview or use a
  coverage review update to replace the responsible answer in a later workflow
  revision.
- Do not commit, approve, or ratify a generated specification.

## Safety

- Confirm a new PRD feature slug only after the author names the feature. For
  Design, prefer the feature identity carried by the selected PRD.
- The helper writes only interview records, compatible Define ceremony
  artifacts, and generated PRD or Design files under the selected project root.
- Never delete or overwrite an existing ceremony, context package, or unrelated
  specification. A completed artifact is regenerated only from persisted answers.
