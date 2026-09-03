# RFC: PRD Drafting in the Dashboard

## Outcome

Let an author start and finish a PRD from the dashboard: give the feature a title
and a short description, answer the interview questions the helper selects, and
get the same `specs/<feature>/prd.md` that `workbench draft prd <feature>`
produces. Same questions, same suggestions, same clarification budget, same
generated document.

The dashboard becomes a third client of the existing interview. It contributes no
question wording, no ordering, no gate, and no generation logic. Everything it
shows comes from the helper's JSON result.

Product branch only. The Design branch stays on the CLI and the conversational
skill; no Design UI, no Design intake, and no Design skill work is in this RFC.
The interview mechanic is shared, so adding Design later is a new route and a new
question bank, not a second engine.

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
   │  Title:       Due dates for tasks
   │  Slug:        due-dates-for-tasks          (derived, editable)
   │  Description: Team leads cannot see which tasks are overdue ...
   ▼
startAuthoring ──► provisional prd.md exists immediately, revision 0
   │
   ▼
/define/<feature>/authoring/prd
   │  [P-Q5] contextual question, evidence, suggestion, one control
   │  answer / accept / edit / reject / defer      (only what the helper offers)
   │  each answer regenerates the affected sections
   ▼
status: drafted            or   drafted_with_open_questions
   preview + self-review        preview + open findings tied to their questions
```

Two things follow from the helper's behaviour and shape the UI. A usable PRD
exists before the first question is answered, so the page opens with a draft
preview rather than an empty document. And the clarification plan is
recalculated after every answer within a budget of three, so the question count
moves and the UI must not present a fixed-length wizard.

## Intake: Title, Slug, Description

The helper's `new_prd_basics` form returns `feature_slug` and
`feature_description`. The dashboard asks for a title instead of a slug, because
a slug is a repository identifier and not how an author names a feature. Rather
than let the UI invent a field, the form gains `feature_title` in the helper and
the UI stays a generic renderer of the returned fields.

| Field | Source of truth | Behaviour |
|---|---|---|
| Title | New helper field `feature_title` | Free text. Becomes the PRD H1 and the display name. |
| Slug | Existing `feature_slug` | Derived client-side by `deriveSlug`, a mirror of the helper's `_slugify` held in place by `__tests__/guided/slug.test.ts`. Editable; the helper validates against `FEATURE_RE` before any write. |
| Description | Existing `feature_description` | Persisted as direct problem evidence. P-Q1 is skipped when it is sufficient. |

Today the PRD H1 is reconstructed from the slug, so `due-dates-for-tasks` renders
as "Due Dates For Tasks". Persisting the title keeps the author's wording in the
document on every surface.

Before submitting, the page calls `authoringSession` for the derived slug. A
`not_started` result means the slug is free. An existing checkpoint means the
form offers to resume that interview or asks for a different name; it never
silently attaches a new description to someone else's in-progress work, which is
what the helper already refuses at the write.

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
- 20s timeout per call, surfaced as `helper_unavailable` with the resolved helper
  path and interpreter.
- Never repair, default, or reshape helper output. An unparseable payload is an
  error, not an empty session.
- No question text, option, threshold, or gate is defined in the adapter.

## Helper Contract Additions

Implemented in `draft.py` so the CLI and the agent inherit all of them. All five
landed on `codex/guided-prd-dashboard-ui`, including path resolution, so the
multiplayer refusal below now guards only a layout that changes under a live
session.

| # | Addition | Why the dashboard needs it | Blocking |
|---|---|---|---|
| 1 | `--peek`: return the current result from persisted state only, with `status: not_started` when no checkpoint exists | A page load or poll must not write. A plain `run_once` creates the checkpoint, plans clarifications, refreshes suggestions, and generates the provisional PRD, so the read path currently mutates state. | Yes |
| 2 | `sections` array in the result and in `draft-prd.json`: `{title, question_ids, coverage_ids, state}` | Section-level Edit needs the source question. `PRD_SECTION_MAP` lives only in code and `_render_prd_section` emits no per-question headings, so the UI would otherwise regex generated Markdown. | Yes |
| 3 | `feature_title` on the intake form, persisted with the intake evidence and used as the PRD H1 and display name | Keeps the author's own name for the feature instead of a title-cased slug. | Yes |
| 4 | Resolve `.speed` paths through the same single-player/multiplayer rule as `dashboard/backend/paths.py` | `draft.py` writes `.speed/features/<f>/` unconditionally; in a multiplayer project the dashboard reads `.speed/shared/features/<f>/draft-prd.json`, so guided drafts are invisible there. | Multiplayer only |
| 5 | `authoring_url` beside `dashboard_url` on the artifact record | The helper returns the feature page; the interview is a deeper route. Without it, every client hardcodes the route shape. | No, route fallback documented |

Until addition 4 lands, the dashboard refuses guided PRD drafting in a
multiplayer project with an explicit reason instead of showing an empty session.

## GraphQL Surface

One resolver module, `dashboard/backend/resolvers/authoring.py`, with types in
`authoring_types.py`. Field names mirror the helper's vocabulary so a UI state
maps to a CLI flag without a translation table. `artifactType` is present and
defaults to `"prd"`; the UI only ever sends `prd`, and Design later needs no
schema change.

```graphql
type Query {
  authoringIntake: AuthoringIntake!
  authoringSession(featureName: String!, artifactType: String = "prd"): AuthoringSession!
}

type Mutation {
  startAuthoring(featureTitle: String!, featureName: String!,
                 featureDescription: String!,
                 artifactType: String = "prd"): AuthoringSession!
  submitAuthoringAnswer(featureName: String!, answer: String!,
                        expectedRevision: Int!,
                        artifactType: String = "prd"): AuthoringSession!
  selectAuthoringAction(featureName: String!, action: AuthoringAction!,
                        expectedRevision: Int!,
                        artifactType: String = "prd"): AuthoringSession!
  reviseAuthoringCoverage(featureName: String!, coverageId: String!,
                          answer: String!, expectedRevision: Int!,
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
| `startAuthoring` | `draft.py prd <feature> --feature-title T --feature-description D --json` |
| `submitAuthoringAnswer` | `--answer T --expected-revision N` |
| `selectAuthoringAction` | `--accept-suggestion` / `--edit-suggestion` / `--reject-suggestion` / `--defer` |
| `reviseAuthoringCoverage` | `--update-coverage C --answer T --expected-revision N` |

`AuthoringSession` projects the helper result field for field: `status`,
`revision`, `resumeStep`, `progress`, `coverage`, `currentQuestion` (with
`suggestion`, `followUp`, `editRequest`, `responseControl`, `reviewFindings`),
`sections`, `selfReview`, `artifactPath`, `draftAvailable`, `implementation`, and
`message`. Control types and coverage entries pass through as declared shapes
rather than enumerated GraphQL enums, so a question-bank change reaches the UI
without a resolver edit.

`Query.authoringSession` never writes. Starting an interview is a mutation
because it creates the checkpoint and the provisional PRD.

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

The question region is a generic renderer over `responseControl`. A
`single_select` becomes a radio group over the returned options in the returned
order; a `textarea` becomes a labelled field prefilled from `initial_value` with
the returned prompt as its label. Unavailable actions are absent from the payload
and must not appear as disabled choices. Nothing in the UI may add, relabel,
reorder, or infer an option, which is what keeps the browser and the terminal
identical.

Follow-ups, edit prefill, rejected suggestions, and self-review repair all arrive
as an ordinary control with a different `id` and prompt, so they need no special
components. Deferral shows a blocking notice naming the deferred required
questions, using the helper's own message.

The coverage region lists `coverage` entries with confidence label and impact,
and shows `confirmed/total` with a note that the plan adapts. Because the planner
may drop an unsurfaced question when another answer raises its confidence, a
fixed stepper would appear to lose steps.

The preview region renders the artifact for the current revision, each section
footed by its source question IDs and an Edit control that calls
`reviseAuthoringCoverage`. Generated prose is never directly editable on this
page; repair happens through the answer that produced it.

## Status Mapping

| Helper status | Page state |
|---|---|
| `needs_input` | Intake form rendered from `next_input` |
| `not_started` | Start card for the resolved slug |
| `question` | Question card with the returned control |
| `blocked` | Question card plus the blocking notice for deferred required questions |
| `drafted` | Preview, self-review passed, interview complete |
| `drafted_with_open_questions` | Preview plus open findings and their source questions |
| `revision_conflict` | Conflict banner, reload action, local text preserved |
| `error` | Helper message verbatim with the attempted invocation |
| `helper_unavailable` | Adapter failure with resolved helper path and interpreter |

## Live Refresh and Concurrency

`.speed/features/<f>/authoring-prd.json` is the shared truth. A watchdog
observer, registered in the `create_app` lifespan beside the existing spec and
active-feature watchers, publishes `EventType.AUTHORING_SESSION_CHANGED` with
`{feature, artifact_type, revision, status}` on every checkpoint change. An
answer confirmed in the terminal therefore advances an open dashboard tab without
a poll.

Write safety comes from the helper: the feature lock serialises writes and
`--expected-revision` rejects a stale author. The dashboard's obligations:

- Send the revision the rendered question came from, never a cached one.
- Treat `revision_conflict` as a page state, not a toast. The banner names the
  held revision and the current one and offers reload, and unsent local text
  survives that reload.
- Mark a control saved only after the mutation returns a higher revision.
  Optimistic confirmation is prohibited.

## Conflict with Direct Draft Editing

`Mutation.updateDraft` writes `draft-prd.json` and the spec file directly. For a
guided PRD that edit is lost at the next regeneration, since the checkpoint
remains the document's only source. Guided drafts are identified by the
`authoring` key that `_ensure_define_compatibility` writes into the draft record.
For those, `updateDraft` returns a refusal naming the responsible question and
the section Edit route. Non-guided drafts keep their current behaviour.

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
- A slug collision asks for a different name or an explicit resume; it never
  attaches new intake evidence to existing progress.
- Multiplayer projects are refused with a stated reason until helper path
  resolution is shared.

## Verification

- Title, slug, and description submitted in the browser produce
  `specs/<feature>/prd.md` with the author's title as its H1 and a provisional
  draft available before the first question is answered.
- A PRD started in the dashboard and continued through
  `workbench draft prd <feature>` resumes the same question at the same revision,
  and the reverse order behaves identically.
- Question prompt, evidence text, option labels, and option order in the browser
  match the CLI `--json` payload byte for byte.
- `authoringSession` leaves `authoring-prd.json`, `specs/<f>/`, and
  `draft-prd.json` unmodified, including the first call for an unknown feature.
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

Design and Technical branches in the UI, ADR-candidate capture, changes to
ratification and commitment, replacing `ceremony_generator.py` for non-guided
drafts, model-generated suggestions, asynchronous suggestion precomputation, and
multi-author presence.
