# RFC: Guided PRD Drafting — First Vertical Slice

## Outcome

Implement `workbench draft prd <feature>` and the `workbench-draft` skill as two
entry points into one persisted Product interview. The command plans contextual
questions from confidence-scored coverage definitions, stores confirmed
clarifications, and writes V1 only after the interview is complete.
It returns only the guided authoring URL at
`http://localhost:3000/define/<feature>/authoring/prd`.

The workflow does not ask a model to invent or rewrite product decisions.

## Shared Implementation Boundary

The canonical implementation lives in `skills/workbench-draft/scripts/draft.py`.
Its portable compact-plan normalizer lives beside it in `planner_contract.py`,
with the stable question bank and planner prompt in the same skill package. The
dashboard, `workbench draft` CLI, and conversational skill provide semantic
model output through the same compact contract, then execute the helper. They
must not independently implement normalization, questions, suggestions,
checkpoint transitions, validation, or PRD rendering.

Skill projection copies the helper, planner contract, planner prompt, and
question bank byte-for-byte. Every JSON result exposes SHA-256 hashes for all
four files under `implementation`, allowing callers and tests to prove which
shared implementation produced a response. A
parity test starts through the CLI, continues through the projected skill, and
then reloads through the CLI against the same checkpoint.

## Scope

- Product/PRD branch only.
- Interactive terminal execution and conversational agent execution.
- One question at a time with durable resume.
- Contextual wording and conditional scope/control coverage.
- A complete coverage confidence map and every material clarification needed by
  the applicable PRD template.
- V1 generation only after every material clarification is complete.
- Grounded suggested responses with source, confidence, and gap reporting.
- Explicit accept, edit, reject, and defer decisions.
- Required-answer deferral and generation blocking.
- Revision checking to reject stale concurrent answers.
- Deterministic Markdown generation with question-level provenance.
- Compatibility records for the existing Define dashboard.

Design, Technical, Discover-handoff validation, orchestration-stage selection,
answer editing, full self-review, and package ratification remain later slices.

## Interfaces

```text
workbench draft prd <feature>
workbench draft prd --feature-description <text> --compact-plan-file <path> --json
workbench draft prd <feature> --json
workbench draft prd <feature> --answer <text> --expected-revision <n> --json
workbench draft prd <feature> --update-coverage <coverage> --answer <text> --expected-revision <n> --json
workbench draft prd <feature> --accept-suggestion --expected-revision <n> --json
workbench draft prd <feature> --edit-suggestion --expected-revision <n> --json
workbench draft prd <feature> --reject-suggestion --expected-revision <n> --json
workbench draft prd <feature> --defer --expected-revision <n> --json
```

When invoked as `workbench draft prd` without a feature, the shared helper
returns `needs_input` with one `new_prd_basics` form containing only
`feature_description`. It does not scan or expose existing feature directories.
The current harness model derives the title and complete question plan using the
packaged planner prompt, template, and bank. The client submits the description
and compact plan without a feature argument; the helper derives and validates
the slug from the semantic title before creating the checkpoint. The helper
persists the description separately from answers and treats it as direct problem
evidence. P-Q1 is skipped when that evidence is sufficient.

Interactive terminal execution loops over only selected material clarifications
until final review or `:quit`. Each answer is checkpointed before the next one,
and terminal completion prints only the guided authoring URL. The skill uses the
JSON form and submits answers with the returned question ID and revision.

Draft-review edits are submitted against a stable coverage ID with
`--update-coverage` and `--answer`. The helper records the human revision,
invalidates the prior generated artifact, and regenerates from authoritative
state instead of patching Markdown.

## Persisted State

`.speed/features/<feature>/authoring-prd.json` is the authoritative interview
checkpoint:

```json
{
  "schema_version": 2,
  "feature_name": "add-due-date-to-task",
  "artifact_type": "prd",
  "question_bank_version": "prd-v2",
  "status": "interviewing",
  "revision": 3,
  "coverage": {
    "P-Q2": {
      "confidence": 0.25,
      "confidence_label": "unresolved",
      "impact": "high",
      "basis": ["intake:feature-description"],
      "question_value": 0.6
    }
  },
  "clarification_plan": ["P-Q2", "P-Q7", "P-Q8"],
  "clarifications_asked": ["P-Q2"],
  "suggestions": {
    "P-Q1": {
      "id": "sug-0123456789",
      "answer": "Evidence-backed draft response: ...",
      "confidence": "grounded",
      "accept_ready": true,
      "sources": [{"id": "intent", "path": ".speed/features/.../intent.json"}],
      "gaps": []
    }
  },
  "answers": {
    "P-Q1": {
      "state": "confirmed",
      "answer": "...",
      "question_prompt": "The contextual question answered at this revision.",
      "decision": "accepted",
      "suggestion_id": "sug-0123456789",
      "actor": "Feature Owner",
      "actor_email": "owner@example.com",
      "evidence_prompt": "Reviewed Discover handoff, research, ...",
      "confirmed_at": "..."
    }
  },
  "decision_history": [],
  "artifact": null
}
```

The feature lock serializes writes. `--expected-revision` prevents a stale
agent or terminal from overwriting a newer checkpoint. Suggestions remain
separate from answers, and every action appends to `decision_history`.

The checkpoint also persists `follow_ups`, `edit_requests`, and `self_review`.
Selecting Edit writes a pending edit request before returning a textarea control
prefilled from the persisted suggestion. `resume_step` identifies that exact
control so either client resumes it after interruption. A response below
its question's declared quality threshold creates one durable targeted
follow-up without confirming the answer. The follow-up response is combined
with the initial response; any remaining gap is retained on the answer for
self-review. A question never receives a second automatic follow-up.

## Contextual Planning and Suggestion Grounding

The Product v2 planner treats P-Q entries as stable coverage definitions rather
than a fixed script. Every area receives a confidence label, numeric confidence,
impact, evidence basis, and question value. Question value combines uncertainty,
impact, and downstream leverage. The dashboard model planner keeps every material
high-value clarifications in one initial batch. It performs one final reassessment
after that batch is confirmed, but cannot add another interview question; newly
noticed uncertainty is retained as an open decision in the PRD. Follow-up prompts
declared by the question bank remain available for an answer that fails its
quality rule.

The evidence router reads available intent and context-package evidence plus
earlier confirmed answers. Each suggestion reports `grounded`, `partial`, or
`missing` confidence, its source excerpts and paths, and source-status gaps.
An evidence-backed response supplied through the context package's
`suggested_responses` map may be marked grounded and accepted unchanged. Raw
evidence alone provides context and gaps but no pseudo-answer; the response
control asks the contextual question directly. A missing or partial suggestion
cannot be accepted or silently become PRD content.

## Generation

Provisional generation starts as soon as a requirement or other problem evidence
is available, even while material clarifications remain. Evidence-backed content
is stated directly; inferred content is labelled for review; unresolved high-
impact content is shown as unresolved rather than invented. Each clarification
regenerates the artifact. Final self-review runs when selected clarifications are
resolved. Every generated PRD uses the
same compact composition contract: Summary, Problem & Evidence, Hypothesis, User
Stories, Requirements & Acceptance, Scope, Guardrails / Must Not Regress,
Delivery/Risks/Open Questions, Success, and References. The helper varies depth
inside those sections from confirmed impact, scope, dependencies, reversibility,
uncertainty, and risk; it never asks for or exposes a document-size label.
Confirmed answers are composed into these sections; the visible document is not
an interview transcript. The generated artifact is
`specs/<feature>/prd.md`; `specs/<feature>/index.md` provides package navigation.

For compatibility with the current dashboard, generation also writes
`.speed/features/<feature>/draft-prd.json`. Missing ceremony, claim, intent, and
context records are bootstrapped with the minimum schema consumed by the
existing dashboard. Existing records are preserved.

Generation is followed by deterministic self-review. Missing required sections,
answer placeholders, and unresolved answer-quality gaps produce findings tied
to their source P-Q IDs. Pass one reopens those answers as stale. Pass two either
returns `drafted` or records remaining findings under `Self-Review Open
Questions` and returns `drafted_with_open_questions`. The dashboard-compatible
draft record carries the same review state.

## Dashboard Contract

The result contains:

```json
{
  "implementation": {
    "helper_hash": "sha256:...",
    "question_bank_hash": "sha256:...",
    "planner_contract_hash": "sha256:...",
    "planner_prompt_hash": "sha256:..."
  },
  "artifact_path": "specs/add-due-date-to-task/prd.md",
  "dashboard_url": "http://localhost:3000/define/add-due-date-to-task",
  "authoring_url": "http://localhost:3000/define/add-due-date-to-task/authoring/prd"
}
```

JSON clients retain both URLs for compatibility, but user-facing CLI and skill
completion returns only `authoring_url`. The authoring route reads the compatible
context, interview, and draft records and renders the answered questions beside
the same generated content.

## Failure Rules

- Invalid or ambiguous feature slugs fail before a write.
- Malformed persisted state fails without replacement.
- A question-bank version mismatch requires migration rather than silent resume.
- A stale expected revision returns `revision_conflict` without changing state.
- Deferred material answers remain visible and block artifact generation until
  they are resolved.
- Missing or partial suggestions reject unchanged acceptance without advancing
  the interview revision.
- Rejecting a suggestion records the decision and keeps the question open.
- Existing context, ceremony, intent, and claim records are never overwritten.

## Verification

- No PRD artifact or preview exists while material clarifications remain open.
- The initial Product question batch contains every material question required
  for a faithful draft, with no fixed count limit, and
  the final reassessment cannot append another one.
- Authentication asks for the sign-in method, then keeps existing-user setup
  and data continuity as a user-confirmed backward-compatibility decision.
- Authentication does not introduce sharing unless current evidence shows a
  sharing capability or the requested scope adds one.
- A local reversible feature omits immaterial scope and control questions.
- Every answer survives process restarts.
- A stale revision cannot change answers.
- Deferral blocks generation after the remaining questions are answered.
- Grounded suggestions expose sources and can be accepted unchanged.
- Missing suggestions expose gaps and cannot be accepted unchanged.
- Reject preserves suggestion provenance without creating an answer.
- Existing dashboard context is preserved.
- CLI and projected-skill execution report identical implementation hashes and
  resume the same persisted checkpoint.
- Catalog validation and projection tests include `workbench-draft`.
