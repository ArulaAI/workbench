---
name: workbench-draft
description: >
  Generate and iteratively refine an evidence-labelled PRD, PRD-linked Design,
  or PRD-and-Design-linked Technical RFC using confidence-ranked clarifications
  without inventing decisions. Use when the user asks to draft or continue one
  of these Define artifacts, answer guided-authoring questions, or run
  `workbench draft`.
---

# Workbench Draft

Generate evidence-labelled specifications from provided requirements,
repository evidence, confirmed answers, and clearly marked inferences. Require
Design to remain pinned to its published PRD input and Technical RFC to remain
pinned to its published PRD and Design inputs.

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
[references/interview-planning.md](references/interview-planning.md),
[references/prd-interview-planner-prompt.md](references/prd-interview-planner-prompt.md),
and [references/prd-questions.json](references/prd-questions.json) completely.
Treat question-bank entries as stable coverage definitions, not a fixed script.
Use the current harness model to create one complete compact interview plan from
the description, repository evidence, PRD template, and confirmed answers. Pass
that plan to the helper with `--compact-plan-json`; the shared planner contract
normalizes it identically for the dashboard, CLI, and projected skill.

For Design and Technical RFC interviews, use their artifact-specific question
banks and the same compact planning and persistence contract. Resolve decisions
from the exact published upstream versions where possible, ask only the material
remainder, and preserve the pinned upstream paths and hashes as provenance.

Do not generate or expose a PRD while material interview questions remain.
Score each coverage area using evidence confidence and decision impact. Ask
every material clarification needed to complete the applicable PRD template;
do not apply an arbitrary question-count limit. Generate V1 only after the
interview is complete, then return it for review and editing.

## Intake without arguments

Use the helper's `needs_input` result instead of inventing repository choices.

1. When the user asks to create a PRD, run
   `python3 scripts/draft.py prd --project-root <project-root> --json`. Present
   the returned `new_prd_basics` form with its only required field,
   `feature_description`. Do not ask the user for a title, slug, repository path,
   or existing feature. Treat the description as direct problem evidence. It
   should briefly say who experiences the problem, what happens today, and the
   desired outcome, but accept the author's natural wording and let planning
   identify any material gaps.
2. Analyze the description and available repository evidence using the planner
   prompt, PRD template, and coverage bank. Derive a concise semantic
   `feature_title` and produce the compact plan defined by the planner prompt.
   Do this before creating workflow state. Then start the interview with:

   Write the compact plan to a temporary JSON file, then run:

   `python3 scripts/draft.py prd --project-root <project-root> --feature-description <feature_description> --compact-plan-file <compact_plan_file> --json`

   The helper derives the feature slug from the planned title, validates the
   complete plan, and persists the same normalized plan used by the dashboard.
   Do not ask P-Q1 merely to repeat the description and do not show a document
   preview while questions remain.
3. If the artifact is genuinely unspecified, run
   `python3 scripts/draft.py --project-root <project-root> --json` and show only
   its artifact choices.
4. If `design` is selected without a feature, run
   `python3 scripts/draft.py design --project-root <project-root> --json`. Ask
   for the upstream PRD first. Accept a PRD attachment, path, or one of the
   returned valid guided PRDs; do not list unrelated feature directories. Derive
   the feature from canonical `specs/<feature>/prd.md` or its metadata. Only when
   it cannot be derived, ask the returned fallback feature-name question as the
   third step. Do not silently import an external PRD or bypass the helper's
   Product prerequisite gate.

## Workflow

1. After intake resolves the artifact and feature, use the helper result already
   returned by the start command. On resume, run
   `python3 scripts/draft.py <artifact> <feature> --project-root <project-root> --peek --json`.
   Design returns a prerequisite error until the same feature has an immutable,
   hash-verified published PRD version; Technical RFC requires both a published
   PRD version and Design version. A newer editable draft does not invalidate the
   last published snapshot. Route the user to the earliest missing upstream artifact rather than
   creating an independent Design brief.
2. If the result status is `question`, do not show an artifact path or preview.
   Show exactly the returned question,
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

5. The complete initial question set is planned once. Ask the returned questions
   one at a time in their persisted order. Submit every answer immediately with
   `--question-id` and `--expected-revision`; do not hold answers in conversation
   memory, re-run planning between answers, or batch-save only at the end. The
   helper generates and self-reviews the PRD immediately after the final material
   answer is saved. If self-review reopens a question, show its
   `existing_answer` and `review_findings`, collect a revision, and regenerate.
6. Stop after at most two self-review passes. Return `drafted` only when review
   passes. Reopen a source question for an answer-level failure. For a structural
   or manual-edit reconciliation failure, return `review_repair` and expose the
   embedded editor as a repair surface without describing the document as V1-ready.
7. When the result is terminal, return exactly the reported `authoring_url` and
   no artifact path, general feature dashboard URL, draft prose, or explanatory
   text. That route is the handoff: it displays the original description,
   answered questions, generated recommendation, and PRD draft together.
8. When the user edits a source answer while reviewing a generated artifact, map
   the edit to its stable coverage ID and submit it through the helper:

   `python3 scripts/draft.py prd <feature> --project-root <project-root> --update-coverage <coverage> --answer <replacement> --expected-revision <revision> --json`

   Regenerate and show the resulting draft. The common section aliases accepted
   by the helper include problem, hypothesis, user stories, requirements,
   acceptance, scope, guardrails, delivery/risks/open questions, and success.
9. Direct section edits, full-document edits, anchored comments, publication,
   version switching, and review handoff must all use the helper-backed dashboard
   operations. Keep comment anchors, actor attribution, source revision, and
   section hash durable. Publication creates an immutable selectable version;
   it does not imply approval or ratification.

## Rules

- Use `scripts/draft.py` as the only interview, suggestion, state, and spec
  generation implementation. The harness supplies semantic judgment only as the
  compact plan described by the applicable planner prompt and question bank;
  `planner_contract.py` owns its normalization for PRD, Design, and Technical
  RFC. Do not reproduce normalization, state, or generation logic in a CLI adapter.
- Treat persisted interview state as authoritative. Never infer that a question
  is complete from conversation memory. Use `resume_step` and
  `current_question.response_control` to resume the exact saved interaction.
- Preserve question IDs and answer wording. Do not turn uncertain answers into
  confident requirements.
- Never tell the user there are eight fixed PRD questions. Stable coverage IDs
  exist for scoring and traceability; surface every material clarification and
  skip decisions already resolved or immaterial. Several independent questions
  may map to the same coverage ID.
- Use `coverage.confidence`, `confidence_label`, `impact`, `basis`, and
  `question_value` to explain why a clarification was selected. Do not expose a
  bare score without its evidence basis.
- Keep `evidence_backed`, `inferred`, `not_material`, and `unresolved` distinct.
  Never render unresolved high-impact content as fact; ask its clarification
  before generating V1.
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
  revision. For Technical RFC, show both pinned PRD and Design versions. Treat
  `upstream_changed` as blocking and preserve downstream answers for later revalidation.
- Keep the persisted system suggestion separate from the human decision. Never
  describe an edited response as an accepted suggestion.
- Preserve the new-PRD description in the helper checkpoint. Treat it as direct
  problem evidence, while retaining provenance distinct from a confirmed
  clarification answer. If an empty revision-0 checkpoint already exists,
  attach the description and continue planning the interview without creating
  a partial artifact.
- Persist every action transition, including selecting Edit before the edited
  text is submitted. Do not rely on the chat transcript to reconstruct an
  interrupted step.
- Ask at most one helper-provided targeted follow-up per question. Persist and
  resume it like every other interview transition.
- Repair self-review findings through their returned source question IDs. Never
  patch generated prose directly or run more than two review passes.
- On `revision_conflict`, reload status and show the changed checkpoint before
  asking the user to continue.
- Do not bypass the helper when editing generated Markdown. Use its section or
  document update operations so provenance, review state, and versions remain coherent.
- Do not commit, approve, or ratify a generated specification.

## Safety

- Keep a new PRD on an opaque temporary route until the model derives a semantic
  title; canonicalize the slug from that title atomically. For Design and RFC,
  use the feature identity carried by their published upstream artifacts.
- The helper writes only interview records, compatible Define ceremony
  artifacts, and generated PRD, Design, or Technical RFC files under the selected project root.
- Never delete or overwrite an existing ceremony, context package, or unrelated
  specification. A completed artifact is regenerated only from persisted answers.
