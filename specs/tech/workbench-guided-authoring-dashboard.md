# RFC: Guided Artifact Drafting in the Dashboard

## Outcome

Let an author start and finish a PRD from the dashboard: describe the feature in
their own words, navigate under an opaque temporary identity, let the planner
derive a concise display title and canonical repository slug, answer only the
interview questions the helper still needs, and
get the same `specs/<feature>/prd.md` that `workbench draft prd <feature>`
produces. The helper asks only the conversational questions needed to make the
applicable PRD sections meaningful, then generates the same document on every
surface.

Completed drafts stay in the authoring route. The right panel embeds the existing
CodeMirror editor with a small formatting toolbar, word/character counts, and a
revision dropdown backed by checkpointed `artifact_versions`. A full-document
save is validated against the active PRD template and persisted as one revision.
Review comments support both document-wide chat instructions and selected-text
anchors; selected anchors retain section, quote, offsets, and source revision.

The dashboard becomes a third client of the existing interview. It contributes no
question wording, no ordering, no gate, and no generation logic. Everything it
shows comes from the helper's JSON result.

PRD, Design, and Technical RFC use one dashboard shell. PRD begins with a
freeform brief without a client-side character cap; Design requires a pinned,
hash-verified published PRD version and RFC requires pinned published PRD and
Design versions. Newer working drafts do not mutate those upstream snapshots.
Each branch owns its question bank and generation persona while sharing intake
navigation, interview controls, editor, comments, publish action, and versions.

## Surfaces Today

```text
CLI/TTY ──► workbench draft prd ─┐
                                 ├──► skills/workbench-draft/scripts/draft.py
Agent   ──► projected skill ─────┘         │
                                           ├──► .speed/features/<f>/authoring-prd.json   (authoritative)
                                           ├──► specs/<f>/prd.md                          (artifact)
                                           └──► .speed/features/<f>/draft-prd.json        (dashboard record)

Dashboard ──► GraphQL ──► resolvers/ceremony_*.py ──► broad-prompt draft generation
```

The dashboard can already display `draft-prd.json` and can overwrite it through
`updateDraft`, but it cannot answer a question or regenerate from answers. This
RFC adds one adapter so it can.

## Author Flow

```text
/define/new
   │  Description: Team leads cannot see which tasks are overdue ...
   ▼
startAuthoring ──► interview checkpoint exists immediately; no model wait, no prd.md yet
   │
   ▼
/define/<feature>/authoring/prd
   │  visible analysis state while one model plan returns every material question
   │  one question card is visible; each answer is checkpointed before advancing
   ▼
final confirmed answer ──► meaningful V1 generated locally in the 11-section template
   │  edit a section directly / collect section comments
   │  submit all comments once ──► one regeneration revision
   │
   ▼
Review & commit ──► prepareAuthoringCommit ──► existing Define commit flow
```

The page opens as a short, contextual interview, not a template checklist. No
draft is shown until the readiness gate passes. The model plans the complete
necessary batch once from the intake, PRD template, and repository
context. The browser presents that preplanned batch one question at a time and
persists each answer to the shared checkpoint before advancing. Submitting the
last answer generates the draft immediately from the stored plan and confirmed
evidence. There is no separate Create PRD step and no second model planning pass.
The initial plan is the only pass allowed to introduce interview questions;
later uncertainty remains visible as an open decision in the draft rather than
starting another question round. Follow-ups and later source-answer edits remain
single-question flows.

The configured `claude-code/sonnet` path launches a fresh CLI subprocess. The v5
planner uses the completeness-focused `complete-template-intake-v1` contract:
the model returns an AI-derived title, resolved coverage, and every material
question needed by the applicable PRD template. Full PRD
composition is deferred until local generation after the interview. On September
8, the supplied 968-character brief took 56–60 seconds with the former full-plan
schema and 22.0 seconds with the compact contract, a roughly 61% reduction. The
plan records `timing.model_ms` and `timing.total_ms` for diagnosis. Final
synthesis is local, so this model startup/output cost occurs once rather than
again after the last answer. `startAuthoring` does not wait for the planner: it
persists the intake checkpoint and navigates immediately, then the authoring
route runs the planner while showing its analysis state. Reaching a true 2–5
second first-question response will require a persistent provider connection or
streaming transport; changing CLI model tiers alone did not improve the trace.

## Intake: Description and model-derived identity

The intake UI asks only for the author's feature description. The server creates
an opaque `draft-*` identity so the checkpoint and route can exist immediately;
the compact AI plan derives a concise capability name and atomically renames the
package and route to its canonical slug. No guessed title is rendered.

| Field | Source of truth | Behaviour |
|---|---|---|
| Title | Compact AI plan `feature_title` | Derived as a concise capability name; becomes the PRD H1 and display name. Until available the UI says **Deriving title…**. |
| Slug | Helper canonicalization | Derived server-side from the validated model title after planning; the opaque intake route is replaced without losing state. |
| Description | Existing `feature_description` | Freeform intake with no hard cap or character counter, persisted as direct problem evidence. P-Q1 is skipped when it is sufficient. |

Persisting the model-derived title avoids copying the author's opening sentence
or reconstructing an awkward title from the temporary identity.

Because the temporary identity is random, intake does not perform a semantic
slug collision check. Canonicalization detects an existing target before rename
and never silently attaches the new brief to another checkpoint.

## Adapter Boundary

A new module `dashboard/backend/authoring_helper.py` owns every decision about
reaching the helper: locating `skills/workbench-draft/scripts/draft.py` in the
Workbench install directory, selecting the interpreter (`SPEED_PYTHON`, then
`<install>/.venv/bin/python3`, then `<project>/.venv/bin/python3`, then
`python3`), passing `--project-root` and `--dashboard-url`, running the process,
and decoding its JSON.

Subprocess invocation rather than an import, for three reasons: the projected
skill is copied byte-for-byte and must not acquire dashboard dependencies; the
`implementation` hashes in the result then describe the exact file that executed;
and `ceremony_validator.py` and `llm/__init__.py` already establish subprocess
adapters in this backend.

Interpreter and helper-path resolution exists twice today, in the `workbench`
shim and in `lib/cmd/draft.sh`. The adapter is the third copy, so this RFC
requires the shell resolution to collapse into one sourced function with the
Python adapter mirroring it. A projection or venv change must not make two
surfaces run different implementations.

Rules for the adapter:

- Exit status is not the error signal. Status `0`, `1`, and `2` all carry a JSON
  payload; the `status` field is authoritative.
- A bounded helper timeout, surfaced as `helper_unavailable` with the resolved helper
  path and interpreter.
- Never repair, default, or reshape helper output. An unparseable payload is an
  error, not an empty session.
- No question text, option, threshold, or gate is defined in the adapter.

## Helper Contract Additions

Implemented in `draft.py` so the CLI and the agent inherit all of them. All six
landed on `codex/guided-prd-dashboard-ui`, including path resolution, so
multiplayer projects are supported rather than refused.

| # | Addition | Why the dashboard needs it | Blocking |
|---|---|---|---|
| 1 | `--peek`: return the current result from persisted state only, with `status: not_started` when no checkpoint exists | A page load or poll must not write. A plain `run_once` creates or advances the interview checkpoint. | Yes |
| 2 | `sections` array in the result and in `draft-prd.json`: `{title, question_ids, coverage_ids, state, source_answers}` | Section-level Edit needs both the exact source question and its confirmed value. The mapping reflects only answers actually composed into the section, so the UI never guesses from generated Markdown. | Yes |
| 3 | `feature_title` in the normalized compact plan, persisted with intake evidence and used as the PRD H1 and display name | Gives every surface the same concise semantic title without asking the author to name the feature. | Yes |
| 4 | Resolve `.speed` paths through the same single-player/multiplayer rule as `dashboard/backend/paths.py` | `draft.py` wrote `.speed/features/<f>/` unconditionally; in a multiplayer project the dashboard reads `.speed/shared/features/<f>/draft-prd.json`, so guided drafts were invisible there. | Yes |
| 5 | `authoring_url` beside `dashboard_url` on the artifact record | JSON retains the feature URL for compatibility, while every user-facing completion hands off only to the deeper authoring route. | Yes |
| 6 | `--list`: summarize every checkpoint under the resolved features root, most recently updated first | Resuming needs a project-wide list, and no surface had one. Globbing `authoring-*.json` from the resolver would put status, progress, and layout resolution in an adapter. One subprocess returns the whole list. | Yes |
| 7 | `--review-comments-json` plus `--review-plan-json`: apply section-scoped comments and validated host-model replacement bodies in one revision | Reviewers can collect feedback across the document; the model reconsiders each affected section in the context of the current PRD instead of appending the comment as document prose. A failed model call leaves the artifact unchanged. | Yes |

`--list` resolves the current suggestion for each entry exactly as `--peek`
does. That step appends to `clarifications_asked`, which decides how many
questions stay active, so skipping it makes a listed `confirmed/total` disagree
with the interview page for the same feature. A checkpoint that fails to read or
validate is returned as one entry with `status: error` and its message, never
dropped from the list and never rewritten.

The dashboard's CORS origin list reads `DASHBOARD_ALLOWED_ORIGINS` (comma
separated, defaulting to port 3000) so a worktree can serve its own dashboard on
a spare port without the browser blocking every mutation at preflight.

## GraphQL Surface

One resolver module, `dashboard/backend/resolvers/authoring.py`, with types in
`authoring_types.py`. Field names mirror the helper's vocabulary so a UI state
maps to a CLI flag without a translation table. `artifactType` defaults to
`"prd"` and is sent explicitly for PRD, Design, and RFC mutations.

```graphql
type Query {
  authoringIntake: AuthoringIntake!
  authoringSession(featureName: String!, artifactType: String = "prd"): AuthoringSession!
  authoringSessions(artifactType: String = "prd"): AuthoringSessionList!
}

type AuthoringSessionList {
  status: String!
  message: String!
  sessions: [AuthoringSessionSummary!]!
}

type Mutation {
  startAuthoring(featureTitle: String!, featureName: String!,
                 featureDescription: String!,
                 artifactType: String = "prd"): AuthoringSession!
  submitAuthoringAnswer(featureName: String!, answer: String!,
                        expectedRevision: Int!,
                        artifactType: String = "prd"): AuthoringSession!
  submitAuthoringAnswers(featureName: String!, answers: JSON!,
                         expectedRevision: Int!,
                         artifactType: String = "prd"): AuthoringSession!
  selectAuthoringAction(featureName: String!, action: AuthoringAction!,
                        expectedRevision: Int!,
                        artifactType: String = "prd"): AuthoringSession!
  reviseAuthoringCoverage(featureName: String!, coverageId: String!,
                          answer: String!, expectedRevision: Int!,
                          artifactType: String = "prd"): AuthoringSession!
  prepareAuthoringCommit(featureName: String!,
                         artifactType: String = "prd"): AuthoringSession!
  publishAuthoringDraft(featureName: String!, expectedRevision: Int!,
                        artifactType: String = "prd"): AuthoringSession!
}

enum AuthoringAction { ACCEPT EDIT REJECT DEFER }

type Subscription {
  authoringSessionChanged(feature: String!): AuthoringSessionEvent!
}
```

| GraphQL field | Helper invocation |
|---|---|
| `authoringIntake` | `draft.py prd --json` |
| `authoringSession` | `draft.py prd <feature> --peek --json` |
| `authoringSessions` | `draft.py prd --list --json` |
| `startAuthoring` | `draft.py prd <feature> --feature-title T --feature-description D --json` |
| `submitAuthoringAnswer` | `--answer T --expected-revision N` |
| `submitAuthoringAnswers` | `--answers-json '[{"question_id":"P-Q2","answer":"..."}]' --expected-revision N` |
| `selectAuthoringAction` | `--accept-suggestion` / `--edit-suggestion` / `--reject-suggestion` / `--defer` |
| `reviseAuthoringCoverage` | `--update-coverage C --answer T --expected-revision N` |
| `prepareAuthoringCommit` | Read-only `--peek`, then create missing ceremony ownership state before opening the existing Define commit flow |

`AuthoringSession` projects the helper result field for field: `status`,
`revision`, `resumeStep`, `progress`, `coverage`, `currentQuestion` (with
`suggestion`, `followUp`, `editRequest`, `responseControl`, `reviewFindings`),
`sections`, `selfReview`, `artifactPath`, `draftAvailable`, `implementation`, and
`message`. Control types and coverage entries pass through as declared shapes
rather than enumerated GraphQL enums, so a question-bank change reaches the UI
without a resolver edit.

`AuthoringSessionSummary` is the resume projection only: `featureName`,
`featureTitle`, `artifactType`, `status`, `revision`, `updatedAt`, `progress`,
`draftAvailable`, `artifactPath`, `authoringUrl`, `message`. It carries no
question, suggestion, or artifact content, so listing a project costs one
subprocess and no document reads.

`Query.authoringSession` and `Query.authoringSessions` never write. Starting an
interview is a mutation because it creates the checkpoint. Artifact generation
remains blocked until every material interview answer is confirmed.

## Interview Page

```text
┌─ IconRail ─┬─ Header ────────────────────────────────────────────────────────┐
│            │ Due dates for tasks · PRD · rev 2 · Saved                       │
│            ├──────────────────┬────────────────────────────┬─────────────────┤
│            │ Coverage         │ Question                   │ Draft preview   │
│            │                  │                            │                 │
│            │ P-Q1 grounded    │ [P-Q5] What must due dates  │ ## Summary      │
│            │ P-Q5 unresolved  │ do, and what observable     │ ## Problem      │
│            │ P-Q4 unresolved  │ behaviour proves each ...   │   P-Q1 · Edit   │
│            │                  │                            │ ## Requirements │
│            │ 1/2 confirmed    │ Evidence to consider: ...   │   P-Q5 · Edit   │
│            │ plan adapts      │ Suggestion (partial)        │ ## Scope        │
│            │                  │   source · intake path      │ ...             │
│            │                  │   gap · does not resolve …  │                 │
│            │                  │ ( ) Answer question         │                 │
│            │                  │ ( ) Defer                   │                 │
└────────────┴──────────────────┴────────────────────────────┴─────────────────┘
```

Route: `/define/<feature>/authoring/prd`, inside the existing `IconRail` and
`Header` shell. `/define/<feature>` gains one resume card when a checkpoint
exists, showing artifact type, status, `confirmed/total`, and a link built from
`authoring_url` or the route shape.

For a new model-planned interview, the question region receives every entry in
`planning.questions` as one stable plan but renders only the current persisted
question. Each card is a generic renderer over
`responseControl`. A
`single_select` becomes a radio group over the returned options in the returned
order; a `multi_select` uses checkboxes and labels each scope choice explicitly
as `Include` or `Exclude`; a `textarea` becomes a labelled field prefilled from
`initial_value` with the returned prompt as its label. Each Continue persists
that question before the next prepared question is shown. Unavailable actions are
absent from the payload and must not appear as disabled choices. Option meaning
is normalized in the planner payload, never inferred by the browser.

Follow-ups, edit prefill, rejected suggestions, and self-review repair all arrive
as an ordinary control with a different `id` and prompt, so they need no special
components. Deferral shows a blocking notice naming the deferred required
questions, using the helper's own message.

The default readiness region says when V1 is available, lists the sections
supported by confirmed inputs, and explains only the next material gap. It does
not expose stable coverage IDs as a questionnaire. `?view=coverage` switches to
the original coverage region for evaluation; that view lists `coverage` entries
with confidence label and impact and shows `confirmed/total`.

The preview region is absent until the interview reaches a terminal generated
state. It then renders the artifact for the current revision. The generated
document always keeps the 11 core sections from `PRD Proposal.docx`; metadata
keeps internal PRD size out of the artifact, requirements pair behavior with independent pass/fail checks,
scope separates included from not included, guardrails protect existing behavior
with observable verification, and success describes a post-launch signal. Each
section exposes its answer provenance, **Edit draft**, and **Comment**. Edit draft
opens an explicit section textarea and calls `reviseAuthoringSection`; comments
can be collected across sections and submitted in one regeneration pass. The
configured model receives the current PRD, author inputs, confirmed answers,
the fixed authoring context package, template contract, and comments, then returns complete
replacement bodies only for the affected sections. Comments are instructions,
never verbatim content to append. If that model call fails, no revision is
persisted and the browser keeps the comments available for retry.
Direct edits are persisted as `manual_sections`, labeled `manual` in provenance,
and applied after answer-derived composition during every later regeneration.

## Status Mapping

| Helper status | Page state |
|---|---|
| `needs_input` | Intake form rendered from `next_input` |
| `not_started` | Start card for the resolved slug |
| `question` | Question card with the returned control |
| `blocked` | Question card plus the blocking notice for deferred required questions |
| `drafted` | Preview, self-review passed, interview complete |
| `review_repair` | Source-question repair, or a non-ready editor when structural/manual reconciliation needs a direct document repair |
| `published` | Current immutable version selected; subsequent edits branch a new draft revision |
| `revision_conflict` | Conflict banner, reload action, local text preserved |
| `error` | Helper message verbatim with the attempted invocation |
| `helper_unavailable` | Adapter failure with resolved helper path and interpreter |

Completed PRD states expose one `Review & commit` action in the editor header,
beside the Edit/View Markdown toggle. The action does not write a
second kind of commit record. The mutation ensures older guided checkpoints
have the ceremony state and PRD claim required by the existing Define commit
flow, then the browser navigates to `/define/<feature>` for validation and
commitment.

## Live Refresh and Concurrency

`.speed/features/<f>/authoring-prd.json` is the shared truth. A watchdog handler,
registered in the `create_app` lifespan, publishes
`EventType.AUTHORING_SESSION_CHANGED` with
`{feature, artifact_type, revision, status}` on every checkpoint change. An
answer confirmed in the terminal therefore advances an open dashboard tab without
a poll.

The handler joins the observer the log watcher already owns rather than starting
its own. In a single-player layout both watch `.speed/features`, and the fsevents
backend raises `Cannot add watch - it is already scheduled` for a second native
watch on one path, which silently killed the emitter thread and left checkpoint
events undelivered. Sharing the observer also gives a multiplayer layout its own
watch on `.speed/shared/features`, which is a different path.

Write safety comes from the helper: the feature lock serialises writes and
`--expected-revision` rejects a stale author. The dashboard's obligations:

- Send the revision the rendered question came from, never a cached one.
- Send one initial answer with its persisted question ID and rendered revision.
  A question-ID mismatch rejects that answer without advancing the checkpoint.
- Treat `revision_conflict` as a page state, not a toast. The banner names the
  held revision and the current one and offers reload, and unsent local text
  survives that reload.
- Mark a control saved only after the mutation returns a higher revision.
  Optimistic confirmation is prohibited.

## Direct Draft Editing

Guided PRDs are edited section-by-section through `reviseAuthoringSection` so
the authoring checkpoint remains the source of truth. The helper stores the
body, actor, timestamp, and revision under `manual_sections`. Later answer edits
regenerate the PRD but retain overridden bodies. The general editor remains
available for full-document review; its existing guided-draft guard continues
to prevent an untracked edit that a later regeneration could erase.

## Design Language

Tokens, `.surface`, and the typography ladder in
`dashboard/frontend/app/globals.css` govern the page. Question IDs, coverage
scores, revision numbers, and hashes use IBM Plex Mono; prompts, evidence, and
prose use Inter. Accent is reserved for the primary submit action and the active
question in the coverage list. Confidence labels reuse the existing validation
badge palette so `grounded`, `partial`, and `missing` read the same as elsewhere
in Define. Elevated regions carry border and shadow together; spacing stays on
the 4px grid at 24px page padding, 16px region gaps, 20px card padding.

## Failure Rules

- The dashboard never writes `authoring-prd.json` or `specs/<f>/prd.md`. Only the
  helper writes interview state and artifacts.
- A missing or unreachable helper is reported, never emulated.
- A mutation without `expectedRevision` is rejected by the schema.
- Local edits are never shown as saved before the checkpoint advances.
- No dashboard-only draft, template, or prompt pipeline is introduced for a
  guided PRD.
- A canonicalization collision fails without moving either feature package; it
  never attaches new intake evidence to existing progress.

## Verification

- A description submitted in the browser creates only the opaque interview
  checkpoint. Completing every material answer produces
  `specs/<feature>/prd.md` with the derived title as its H1 and reveals V1.
- A PRD started in the dashboard and continued through
  `workbench draft prd <feature>` resumes the same question at the same revision,
  and the reverse order behaves identically.
- Question prompt, evidence text, option labels, and option order in the browser
  match the CLI `--json` payload byte for byte.
- `authoringSession` leaves `authoring-prd.json`, `specs/<f>/`, and
  `draft-prd.json` unmodified, including the first call for an unknown feature.
- `authoringSessions` lists every interview in the project, writes nothing, and
  reports the same status, revision, and `confirmed/total` that
  `authoringSession` reports for each of those features.
- A checkpoint that cannot be read appears in the list as one `error` entry and
  is left on disk untouched.
- The rendered clarification count changes when an answer raises another area's
  confidence, without the UI showing a lost or skipped step.
- Two open clients answering the same question yield one confirmed answer and one
  `revision_conflict`, with no lost answer and no duplicated revision.
- A CLI answer updates an open dashboard tab through the subscription with no
  page reload.
- Section Edit reopens the question named in `sections[].question_ids`, and
  regeneration updates that section and the self-review state.
- Deferring a required question blocks generation in the UI with the message the
  CLI returns.
- `updateDraft` against a guided PRD is refused and names the source question.
- `implementation` hashes are identical across CLI, projected skill, and
  dashboard for one checkpoint.

## Out of Scope

ADR-candidate capture, changes to ratification and commitment, replacing
`ceremony_generator.py` for non-guided
drafts, model-generated suggestions, asynchronous suggestion precomputation, and
multi-author presence.
