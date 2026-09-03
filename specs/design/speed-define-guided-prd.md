# Design: Define — Guided PRD Authoring

> See [product spec](../product/define-module/03-guided-authoring.md) for product context (AUTH-S1, AUTH-S3, AUTH-S4, AUTH-S6, AUTH-S8, AUTH-S9, AUTH-P1).
> See [tech RFC](../tech/workbench-guided-prd.md) for the interview helper, checkpoint schema, and JSON result contract.
> See [dashboard RFC](../tech/workbench-guided-authoring-dashboard.md) for the GraphQL surface, adapter, and helper additions this design depends on.
> Sibling design spec: [speed-define-ceremony-context.md](speed-define-ceremony-context.md) for the intent-first ceremony branch that shares `/define/new`.
> Design system: `dashboard/frontend/app/globals.css`

<!--
  WHO READS THIS SPEC
  AI coding agents use this as their primary implementation reference.
  Every visual property references a token from globals.css. No raw hex,
  no invented token names, no font families outside --font-sans and
  --font-mono.

  THE HARD CONSTRAINT UNIQUE TO THIS SURFACE
  Every question, prompt, option label, evidence line, gap, and message
  rendered here comes from the interview helper's JSON result. The UI
  chooses layout, type role, colour, and motion. It never authors,
  reorders, relabels, or infers interview content. A component that
  hardcodes a question, an option, or a threshold is a defect.
-->


## Scope

Three surfaces:

- **Guided PRD intake** (`/define/new`, guided branch) where the author gives the feature a title, confirms its slug, and describes the problem
- **Interview page** (`/define/:feature/authoring/prd`) where the author answers the clarifications the helper selected and watches the PRD fill in
- **Resume card** on `/define/:feature`, the single entry point back into an interview in progress

Out of scope: the Design and Technical branches on any surface (both stay on the CLI), the intent-first ceremony flow and its context panel, the suggestion sidebar, validation gutter, decomposition, commitment, and ratification. Those belong to the sibling ceremony specs.


## Design Intent

**Direction:** The author is reviewing, not filling in a form. A usable PRD exists before the first question is answered, so the page opens with a real document on the right and exactly one decision in the middle. The interview is a short conversation about the few things the evidence cannot settle, and the document visibly improves after each answer. Calm and dense, consistent with the rest of the dashboard: no ceremony around progress, no celebration at the end.

**Do not:** Render a fixed-length stepper, wizard breadcrumbs, or "step 2 of 8" (the plan is recomputed after every answer and the count legitimately changes). Show unavailable actions as disabled controls (the helper omits them; render only what it returns). Put the question in a modal or drawer (the draft must stay visible). Add a streaming shimmer, typing indicator, or "generating" animation (generation is deterministic and immediate). Make generated prose editable: no `contenteditable` preview, no Save button on the document, no inline Markdown editor. Handle a revision conflict with a toast. Apply accent to coverage rows, evidence text, or source paths. Use pulsing skeleton loaders (opacity fade only). Add illustrations, confetti, or a success screen on completion. Auto-advance to the next question without an explicit submit.


## Pages / Routes

| Route | User Flow | Description |
|-------|-----------|-------------|
| `/define/new` (guided branch) | AUTH-S1 start a PRD | Artifact choice, then one form: title, derived slug, description. Submitting calls `startAuthoring` and routes to the interview page. The intent-first ceremony branch shares this route and is unchanged. |
| `/define/:feature/authoring/prd` | AUTH-P1 interview, AUTH-S6 repair, AUTH-S9 section edit | Three regions: coverage, current question, draft preview. Every state of the interview lives here, including completion. |
| `/define/:feature` | AUTH-S4 resume | Existing ceremony page. Gains one ResumeCard above the fold when an authoring checkpoint exists for the feature. |


## Layout Structure

### Global Layout

Existing dashboard shell, unchanged: `IconRail` (52px, fixed, left) and `Header` (`bg-bg-elevated`, `px-6 py-4`, 1px bottom border, roughly 52px tall). Everything in this spec renders inside `<main>` to the right of the rail and below the header. Single column on the intake surface, three columns on the interview surface. No new global chrome, no new nav entry: Define already owns this area.

Base background is `--color-bg`. Regions sit on it as elevated surfaces so the eye reads three distinct jobs rather than one long page.

### Regions

Interview page (`/define/:feature/authoring/prd`):

| Region ID | Position | Width | Internal Layout | Scroll |
|-----------|----------|-------|-----------------|--------|
| `authoring-bar` | top of main, sticky | full | flex, space-between, 40px tall | no |
| `conflict-banner` | below `authoring-bar`, sticky | full | flex, space-between | no |
| `coverage-rail` | left | 280px fixed | flex-col, gap 12px | yes |
| `question-column` | centre, right of rail | fluid, content max 640px | stack, gap 16px | yes |
| `draft-preview` | right | 420px fixed | stack, header + document | yes |

Intake page (`/define/new`, guided branch):

| Region ID | Position | Width | Internal Layout | Scroll |
|-----------|----------|-------|-----------------|--------|
| `intake-card` | centred in main | 560px max | stack, gap 20px | no |

`conflict-banner` is conditional. It occupies layout only when the last mutation returned `revision_conflict`, and it pushes the three columns down rather than overlaying them.

### Intake Layout

```text
┌─ intake-card (560px, .surface, 32px 24px) ─────────────────┐
│  New PRD                                    type-section-title │
│  Workbench interviews you, then generates the draft.  caption  │
│                                                                │
│  Title                                            type-cell-label │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │ Due dates for tasks                          18px sans   │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                                │
│  Slug            derived from title, editable     type-cell-label │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │ due-dates-for-tasks                          13px mono   │ │
│  └──────────────────────────────────────────────────────────┘ │
│  specs/due-dates-for-tasks/prd.md                     caption  │
│                                                                │
│  What problem should it solve?                    type-cell-label │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │ Team leads cannot see which tasks are overdue...         │ │
│  │                                              13px sans   │ │
│  └──────────────────────────────────────────────────────────┘ │
│  Who hits the problem, what happens today, the outcome. caption │
│                                                                │
│                                    [ Start interview ]  accent │
└────────────────────────────────────────────────────────────────┘
```

Field order is title, slug, description, matching how an author thinks: name the thing, accept the identifier, explain the problem. The slug sits between them because it is derived from the title and confirmed, not composed.

### Interview Layout

```text
┌─ authoring-bar ────────────────────────────────────────────────────────────┐
│ Due dates for tasks · PRD · rev 2            Saved · 1/2 confirmed         │
├─ coverage-rail (280) ─┬─ question-column ──────────┬─ draft-preview (420) ─┤
│                       │                            │ PRD · rev 2           │
│ COVERAGE      label   │ ┌ QuestionCard ──────────┐ │ specs/…/prd.md   ↗    │
│ ● P-Q1  evidence      │ │ P-Q5            mono   │ ├───────────────────────┤
│ ◉ P-Q5  unresolved    │ │ What must due dates do,│ │ # Due dates for tasks │
│ ○ P-Q4  unresolved    │ │ and what observable    │ │                       │
│ ○ P-Q7  not material  │ │ behaviour proves each  │ │ ## Summary            │
│                       │ │ essential requirement? │ │ …                     │
│ 1/2 confirmed         │ │                        │ │ ─ P-Q1 · Edit         │
│ Plan adapts after     │ │ Evidence to consider   │ │ ## Problem & Evidence │
│ each answer           │ │ Confirmed flows, …     │ │ …                     │
│                       │ │                        │ │ ─ P-Q1 · Edit         │
│                       │ │ SUGGESTION   partial   │ │ ## Requirements       │
│                       │ │ (no grounded response) │ │ …                     │
│                       │ │ source intake:feature… │ │ ─ P-Q5 · Edit         │
│                       │ │ gap does not resolve…  │ │                       │
│                       │ ├────────────────────────┤ │                       │
│                       │ │ ( ) Answer question    │ │                       │
│                       │ │ ( ) Defer              │ │                       │
│                       │ │            [Continue]  │ │                       │
│                       │ └────────────────────────┘ │                       │
└───────────────────────┴────────────────────────────┴───────────────────────┘
```

Reading order is deliberately left to right in importance: what is still open, what is being asked, what has been produced. The coverage rail is reference material and never competes with the question card, which is the only place in the layout that carries an accent action.

### Question Card Anatomy

Six stacked slots, all optional except the identifier, prompt, and control. Rendering order is fixed so the card does not reflow between questions:

| Slot | Present when | Content |
|------|--------------|---------|
| Identifier row | always | `current_question.id`, and the confirmed/active marker |
| Prompt | always | `current_question.prompt`, verbatim |
| Evidence | `current_question.evidence` non-empty | Label "Evidence to consider" plus the helper string |
| Notice | follow-up, findings, or rejection pending | FollowUpNotice or FindingsNotice, one at a time |
| Suggestion | `current_question.suggestion` present | Confidence chip, answer text or the no-grounded-response line, sources, gaps |
| Control | always | ActionChoiceGroup or AnswerTextarea plus the submit button |

### Draft Preview Layout

Header strip (32px) with `PRD · rev N`, the artifact path in mono, and an external-open affordance. Below it the rendered document with a provenance footer under each managed section. Sections come from `sections[]` in the result, in the helper's order, never from parsing the Markdown.


## Component Inventory

| Component ID | Type | Location | Parent Region | Role |
|--------------|------|----------|---------------|------|
| ArtifactChoice | new | `ceremony/guided/ArtifactChoice.tsx` | `intake-card` | Renders the helper's `artifact_type` options. PRD continues into the form; Design shows the CLI command and does not open a UI interview. |
| GuidedPrdIntakeForm | new | `ceremony/guided/GuidedPrdIntakeForm.tsx` | `intake-card` | Title, SlugField, description. Renders from `next_input.fields`; submits `startAuthoring`. |
| SlugField | new | `ceremony/guided/SlugField.tsx` | GuidedPrdIntakeForm | Derived-but-editable identifier with inline validation and the resulting artifact path. |
| AuthoringBar | new | `ceremony/guided/AuthoringBar.tsx` | `authoring-bar` | Feature title, artifact chip, revision, SaveStateChip, progress count. |
| SaveStateChip | new | `ceremony/guided/SaveStateChip.tsx` | AuthoringBar | Saved / Saving / Conflict. Never optimistic. |
| ConflictBanner | new | `ceremony/guided/ConflictBanner.tsx` | `conflict-banner` | Held revision, current revision, reload action, assurance that typed text is kept. |
| CoverageRail | new | `ceremony/guided/CoverageRail.tsx` | `coverage-rail` | CoverageProgress plus one CoverageRow per `coverage` entry. |
| CoverageProgress | new | `ceremony/guided/CoverageProgress.tsx` | CoverageRail | `confirmed/total` and the adaptive-plan caption. No bar segments for unplanned questions. |
| CoverageRow | new | `ceremony/guided/CoverageRow.tsx` | CoverageRail | State dot, question ID, confidence label, impact. Read-only for unanswered rows; confirmed rows link to their section. |
| QuestionCard | new | `ceremony/guided/QuestionCard.tsx` | `question-column` | The six-slot card above. Owns no interview text of its own. |
| EvidenceNote | new | `ceremony/guided/EvidenceNote.tsx` | QuestionCard | "Evidence to consider" block, clamped with expand. |
| SuggestionPanel | new | `ceremony/guided/SuggestionPanel.tsx` | QuestionCard | Confidence chip, suggestion body or the explicit no-suggestion line, SourcePathRef list, GapList. |
| GapList | new | `ceremony/guided/GapList.tsx` | SuggestionPanel | Helper gap strings. Secondary text, never tertiary: these are read to make a decision. |
| SourcePathRef | modified | `define/ref-marker.tsx` | SuggestionPanel | Existing marker, extended with a `status` prop for `available`, `missing`, `stale`. |
| ResponseControl | new | `ceremony/guided/ResponseControl.tsx` | QuestionCard | Dispatcher on `response_control.input_type`. Unknown type renders an explicit unsupported-control message, never a guess. |
| ActionChoiceGroup | new | `ceremony/guided/ActionChoiceGroup.tsx` | ResponseControl | Radio group over the returned options, in the returned order, with the returned labels. |
| AnswerTextarea | new | `ceremony/guided/AnswerTextarea.tsx` | ResponseControl | Auto-growing field prefilled from `initial_value`, labelled by the control prompt. |
| FollowUpNotice | new | `ceremony/guided/FollowUpNotice.tsx` | QuestionCard | The single declared follow-up prompt, framed as a targeted addition rather than a rejection. |
| FindingsNotice | new | `ceremony/guided/FindingsNotice.tsx` | QuestionCard | Self-review findings for the current question, each with its message. |
| BlockingNotice | new | `ceremony/guided/BlockingNotice.tsx` | `question-column` | Deferred required questions and what unblocks generation. |
| DraftPreview | modified | `editor/SpecPreview.tsx` | `draft-preview` | Existing Markdown renderer, wrapped to add the header strip and per-section provenance footers. Read-only. |
| SectionProvenance | new | `ceremony/guided/SectionProvenance.tsx` | DraftPreview | Source question IDs plus Edit for one section. |
| SelfReviewSummary | new | `ceremony/guided/SelfReviewSummary.tsx` | `question-column` | Terminal state: passed, or open questions with their source IDs. |
| ResumeCard | new | `ceremony/guided/ResumeCard.tsx` | `/define/:feature` page body | Artifact, status, `confirmed/total`, resume link. |
| HelperUnavailable | new | `ceremony/guided/HelperUnavailable.tsx` | `question-column`, `intake-card` | Adapter failure with the resolved helper path and interpreter. |

### Component Props

#### GuidedPrdIntakeForm
| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `fields` | `IntakeField[]` | required | From `next_input.fields`; labels and descriptions render verbatim |
| `submitting` | `boolean` | `false` | Locks the form and swaps the button label |
| `existingSession` | `AuthoringSession \| null` | `null` | Non-null after a slug check finds a checkpoint; switches the button to Resume |
| `onSubmit` | `(title: string, slug: string, description: string) => void` | required | |
| `onSlugCheck` | `(slug: string) => void` | required | Debounced 300ms, fires on change and blur |

#### SlugField
| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `value` | `string` | required | Current slug |
| `derivedFrom` | `string` | required | Title the slug was derived from; a manual edit stops derivation |
| `error` | `string \| null` | `null` | Validation or collision message |
| `artifactPath` | `string` | required | `specs/<slug>/prd.md`, shown as caption |
| `onChange` | `(value: string) => void` | required | |

#### CoverageRow
| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `questionId` | `string` | required | e.g. `P-Q5` |
| `confidenceLabel` | `"confirmed" \| "evidence_backed" \| "inferred" \| "unresolved" \| "not_material" \| "missing"` | required | Helper value; label text is title-cased for display only |
| `impact` | `"low" \| "medium" \| "high" \| "critical" \| "conditional"` | required | |
| `state` | `"confirmed" \| "active" \| "planned" \| "deferred"` | required | Drives the dot |
| `sectionAnchor` | `string \| null` | `null` | Set for confirmed rows; scrolls the preview |

#### QuestionCard
| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `question` | `CurrentQuestion` | required | The helper's `current_question`, passed whole |
| `revision` | `number` | required | Revision this card was rendered from; returned with every submit |
| `submitting` | `boolean` | `false` | |
| `onAction` | `(action: "ACCEPT" \| "EDIT" \| "REJECT" \| "DEFER") => void` | required | |
| `onAnswer` | `(text: string) => void` | required | |

#### SuggestionPanel
| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `suggestion` | `Suggestion` | required | Includes `confidence`, `answer`, `sources`, `gaps`, `rejected` |
| `expanded` | `boolean` | `true` | Collapses to the confidence chip plus source count |

#### ResponseControl
| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `control` | `ResponseControlPayload` | required | `id`, `input_type`, `prompt`, `options?`, `initial_value?` |
| `disabled` | `boolean` | `false` | During a mutation |
| `onSelect` | `(value: string) => void` | required | |
| `onSubmitText` | `(text: string) => void` | required | |

#### DraftPreview
| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `content` | `string` | required | Rendered artifact for the current revision |
| `sections` | `SectionProvenance[]` | required | `{title, question_ids, coverage_ids}` from the result |
| `artifactPath` | `string` | required | |
| `revision` | `number` | required | |
| `highlightQuestionId` | `string \| null` | `null` | Sections sourced from this question get the regenerate highlight |
| `onEditSection` | `(coverageId: string) => void` | required | |

#### ConflictBanner
| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `heldRevision` | `number` | required | |
| `currentRevision` | `number` | required | |
| `onReload` | `() => void` | required | Refetches; the draft textarea value survives |

#### ResumeCard
| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `featureName` | `string` | required | |
| `title` | `string` | required | Author's title from the checkpoint intake |
| `status` | `string` | required | Helper status |
| `confirmed` | `number` | required | |
| `total` | `number` | required | |
| `href` | `string` | required | `authoring_url`, or the route fallback |


## Spacing

All values on the 4px grid.

| Context | Token/Value | Usage |
|---------|-------------|-------|
| Page padding | 24px | Around the three interview regions |
| Region gap | 16px | Between coverage rail, question column, preview |
| Intake card padding | 32px 24px | Generous, matches IntentInput |
| Intake field gap | 20px | Between title, slug, description groups |
| Intake label margin-bottom | 8px | Label to field |
| Intake caption margin-top | 8px | Field to helper text |
| Intake field min height | 40px | Single-line inputs |
| Description field min height | 96px | Auto-grows to 240px, then scrolls |
| `authoring-bar` height | 40px | Sticky, `0 24px` internal padding |
| `authoring-bar` item gap | 12px | Between title, chip, revision, save chip |
| Conflict banner padding | 12px 24px | Full-width strip |
| Coverage rail padding | 16px | Internal |
| Coverage progress margin-bottom | 16px | Progress block to first row |
| Coverage row height (min) | 32px | Single row, dot + ID + label |
| Coverage row gap | 4px | Between rows |
| Coverage dot size | 6px | Matches existing task dot |
| Coverage dot margin-right | 8px | Dot to question ID |
| Question card padding | 20px | Internal |
| Question card slot gap | 16px | Between identifier, prompt, evidence, suggestion, control |
| Prompt margin-bottom | 4px | Prompt to its evidence label |
| Suggestion panel padding | 12px | Inset block inside the card |
| Suggestion source row gap | 4px | Between source lines |
| Gap list margin-top | 8px | Sources to gaps |
| Control option height | 36px | Radio row target |
| Control option gap | 4px | Between options |
| Submit button margin-top | 16px | Control to button |
| Submit button height | 32px | `0 16px` internal padding |
| Preview header height | 32px | `0 12px` internal padding |
| Preview document padding | 24px | Reuses SpecPreview padding |
| Section provenance margin-top | 8px | Section body to its footer |
| Section provenance padding | 6px 0 | Above the 1px divider |
| Resume card padding | 20px | Internal |


## Typography

| Element | Role | Family | Size | Weight | Line-Height | Color |
|---------|------|--------|------|--------|-------------|-------|
| Intake heading | `type-section-title` | `--font-sans` | 15px | 600 | 1.4 | `--color-text` |
| Intake subheading | `type-caption` | `--font-sans` | 11px | 400 | 1.4 | `--color-text-tertiary` |
| Field label | `type-cell-label` | `--font-sans` | 12px | 500 | 1.4 | `--color-text-secondary` |
| Title input text | custom | `--font-sans` | 18px | 400 | 1.5 | `--color-text` |
| Title placeholder | custom | `--font-sans` | 18px | 400 | 1.5 | `--color-text-tertiary` |
| Slug input text | `type-mono-value` | `--font-mono` | 13px | 500 | 1.4 | `--color-text` |
| Artifact path caption | `type-caption` | `--font-mono` | 11px | 400 | 1.4 | `--color-text-tertiary` |
| Description input text | custom | `--font-sans` | 13px | 400 | 1.5 | `--color-text` |
| Field helper text | `type-caption` | `--font-sans` | 11px | 400 | 1.4 | `--color-text-tertiary` |
| Field error text | custom | `--font-sans` | 11px | 500 | 1.4 | `--color-red` |
| Authoring bar feature title | `type-section-header` | `--font-sans` | 13px | 600 | 1.4 | `--color-text` |
| Authoring bar artifact chip | `type-badge` | `--font-sans` | 11px | 500 | 1 | `--color-text-secondary` |
| Authoring bar revision | `type-mono-value` | `--font-mono` | 13px | 500 | 1.4 | `--color-text-secondary` |
| Save state chip | `type-badge` | `--font-sans` | 11px | 500 | 1 | Per state (see Color Application) |
| Conflict banner text | `type-body` | `--font-sans` | 13px | 400 | 1.5 | `--color-amber` |
| Coverage rail header | `type-compact-label` | `--font-mono` | 9px | 500 | 1.4 | `--color-text-tertiary` |
| Coverage question ID | `type-mono-value` | `--font-mono` | 13px | 500 | 1.4 | `--color-text-secondary` |
| Coverage confidence label | `type-badge` | `--font-sans` | 11px | 500 | 1 | Per label (see Color Application) |
| Coverage impact | `type-caption` | `--font-sans` | 11px | 400 | 1.4 | `--color-text-tertiary` |
| Coverage progress count | `type-mono-value` | `--font-mono` | 13px | 500 | 1.4 | `--color-text` |
| Coverage progress caption | `type-caption` | `--font-sans` | 11px | 400 | 1.4 | `--color-text-tertiary` |
| Question ID | `type-mono-value` | `--font-mono` | 13px | 500 | 1.4 | `--color-accent` |
| Question prompt | custom | `--font-sans` | 15px | 500 | 1.5 | `--color-text` |
| Evidence label | `type-compact-label` | `--font-mono` | 9px | 500 | 1.4 | `--color-text-tertiary` |
| Evidence body | `type-body` | `--font-sans` | 13px | 400 | 1.5 | `--color-text-secondary` |
| Suggestion label | `type-compact-label` | `--font-mono` | 9px | 500 | 1.4 | `--color-text-tertiary` |
| Suggestion confidence chip | `type-badge` | `--font-sans` | 11px | 500 | 1 | Per confidence |
| Suggestion body | `type-body` | `--font-sans` | 13px | 400 | 1.5 | `--color-text-secondary` |
| Suggestion absent line | custom | `--font-sans` | 13px | 400 | 1.5 | `--color-text-tertiary` |
| Source path | custom | `--font-mono` | 11px | 400 | 1.4 | `--color-text-tertiary` |
| Source ID | custom | `--font-mono` | 11px | 500 | 1.4 | `--color-text-secondary` |
| Gap text | `type-body` | `--font-sans` | 13px | 400 | 1.5 | `--color-text-secondary` |
| Follow-up prompt | custom | `--font-sans` | 13px | 500 | 1.5 | `--color-text` |
| Finding message | `type-body` | `--font-sans` | 13px | 400 | 1.5 | `--color-amber` |
| Control prompt | `type-cell-label` | `--font-sans` | 12px | 500 | 1.4 | `--color-text-secondary` |
| Control option label | custom | `--font-sans` | 13px | 400 | 1.4 | `--color-text` |
| Answer textarea text | custom | `--font-sans` | 13px | 400 | 1.5 | `--color-text` |
| Submit button label | `type-badge` | `--font-sans` | 11px | 500 | 1 | `--color-bg` on accent |
| Blocking notice text | `type-body` | `--font-sans` | 13px | 400 | 1.5 | `--color-amber` |
| Preview header artifact | `type-mono-value` | `--font-mono` | 13px | 500 | 1.4 | `--color-text-secondary` |
| Preview document | inherited | see `SpecPreview` | 13px | 400 | 1.7 | `--color-text-secondary` |
| Section provenance IDs | custom | `--font-mono` | 10px | 500 | 1.4 | `--color-text-tertiary` |
| Section Edit action | `type-caption` | `--font-sans` | 11px | 500 | 1.4 | `--color-text-secondary` |
| Self-review passed line | `type-body` | `--font-sans` | 13px | 400 | 1.5 | `--color-emerald` |
| Resume card title | `type-section-header` | `--font-sans` | 13px | 600 | 1.4 | `--color-text` |
| Resume card meta | `type-caption` | `--font-sans` | 11px | 400 | 1.4 | `--color-text-tertiary` |

The question prompt at 15px/500 is the largest text on the interview page. It outranks the feature title in the bar and the document headings in the preview, because answering it is the only action the page asks for.


## Color Application

Accent appears in exactly three places on this surface: the current question's ID, the primary submit button, and the active coverage dot. Nowhere else. Evidence, sources, gaps, and provenance are all neutral text, because tinting them would imply a severity the helper did not report.

| Element | Property | Token | Notes |
|---------|----------|-------|-------|
| Page background | background | `--color-bg` | Base |
| Intake card | background, border | `--color-bg-card`, `--color-border` | `.surface` |
| Input field background | background | `--color-bg-elevated` | Inset against the card |
| Input field border | border | `--color-border` | Focus: `--color-accent` at 2px outline |
| Input error border | border | `--color-red` | Paired with the error caption |
| `authoring-bar` background | background | `--color-bg-elevated` | 1px bottom border `--color-border` |
| Artifact chip | background, color | `rgba(255,255,255,0.04)`, `--color-text-secondary` | Neutral, not accent |
| Save chip: saved | background, color | `rgba(68,204,119,0.12)`, `--color-emerald` | |
| Save chip: saving | background, color | `rgba(240,178,50,0.12)`, `--color-amber` | |
| Save chip: conflict | background, color | `rgba(239,68,100,0.12)`, `--color-red` | |
| Conflict banner | background, border | `rgba(240,178,50,0.08)`, `--color-amber` at 1px | Full-width, in flow |
| Coverage rail | background, border | `--color-bg-elevated`, `--color-border-light` | `.surface-elevated` |
| Coverage dot: confirmed | background | `--color-emerald` | Filled |
| Coverage dot: active | background, box-shadow | `--color-accent`, `0 0 0 3px var(--color-accent-glow)` | Only accent in the rail |
| Coverage dot: planned | background | `--color-text-tertiary` | Hollow, 1px border |
| Coverage dot: deferred | background | `--color-amber` | Filled |
| Confidence label: confirmed | color | `--color-emerald` | |
| Confidence label: evidence_backed | color | `--color-blue` | Evidence exists and resolves the area |
| Confidence label: inferred | color | `--color-violet` | Present in the draft but marked for review |
| Confidence label: unresolved | color | `--color-amber` | The ones that get asked |
| Confidence label: not_material | color | `--color-text-tertiary` | Deliberately not asked |
| Confidence label: missing | color | `--color-red` | No evidence at all |
| Confidence label background | background | 12% of the label colour | Matches the status-badge pattern |
| Question card | background, border | `--color-bg-card`, `--color-border` | `.surface` |
| Question ID | color | `--color-accent` | |
| Question prompt | color | `--color-text` | |
| Suggestion panel | background | `rgba(255,255,255,0.02)` | Inset block, no border |
| Suggestion chip: grounded | background, color | `rgba(68,204,119,0.12)`, `--color-emerald` | Acceptable unchanged |
| Suggestion chip: partial | background, color | `rgba(240,178,50,0.12)`, `--color-amber` | Must be edited |
| Suggestion chip: missing | background, color | `rgba(85,85,106,0.12)`, `--color-text-tertiary` | No response offered |
| Source status: missing/stale | color | `--color-amber` | Marker only, path stays tertiary |
| Follow-up notice | background, border-left | `rgba(75,166,238,0.08)`, `--color-blue` at 2px | Additive, not an error |
| Findings notice | background, border-left | `rgba(240,178,50,0.08)`, `--color-amber` at 2px | Repair required |
| Blocking notice | background, border-left | `rgba(240,178,50,0.08)`, `--color-amber` at 2px | Deferral blocks generation |
| Radio option (unselected) | border, color | `--color-border`, `--color-text` | |
| Radio option (selected) | border, background | `--color-accent`, `--color-accent-dim` | |
| Primary submit | background, color | `--color-accent`, `--color-bg` | The one hero action |
| Secondary action | background, color | `transparent`, `--color-text-secondary` | Reload, cancel, copy command |
| Preview panel | background, border | `--color-bg-card`, `--color-border` | `.surface` |
| Preview header | background | `--color-bg-elevated` | 1px bottom border |
| Section provenance divider | border-top | `--color-border-light` | |
| Section highlight after regenerate | background | `--color-accent-dim` | Fades out, see Motion |
| Self-review passed | color | `--color-emerald` | Text only, no banner |
| Self-review open questions | color | `--color-amber` | |
| Helper unavailable | color | `--color-red` | With the resolved path in mono tertiary |


## Elevation & Depth

| Element | Elevation Level | Treatment |
|---------|----------------|-----------|
| Page background | 0 (base) | Flat, `--color-bg` |
| `authoring-bar` | 1 | `.surface-elevated`, full width, bottom border only |
| Conflict banner | 1 | Flat tinted strip with 1px border, in flow above the columns |
| Coverage rail | 1 | `.surface-elevated` |
| Coverage rows | 0 (inset) | Flat within the rail |
| Question card | 2 | `.surface` |
| Suggestion panel | 0 (inset) | Flat block inside the question card, no border, no shadow |
| Preview panel | 2 | `.surface` |
| Intake card | 2 | `.surface` |
| Resume card | 2 | `.surface` with `.surface-hover` |

Nothing on this surface goes above level 2. There are no modals, dropdowns, or overlays in the guided PRD flow: every decision is inline, which is what keeps the draft visible while the author decides.


## States

### Page-Level States

#### Intake, empty (`/define/new`, guided branch)

Centred `.surface` card. Title field autofocused. Slug empty and derived on first keystroke. Submit disabled until title, slug, and description all pass local validation. No example content prefilled: a placeholder is a hint, a prefill becomes someone else's PRD.

#### Intake, slug checking

Slug field shows a 11px tertiary caption "Checking…" 300ms after the last keystroke. The submit button stays enabled: the check informs, it does not gate, and the helper validates authoritatively at the write.

#### Intake, slug collision

Caption switches to the existing feature's status and the button splits into "Resume interview" (primary) and "Use a different slug" (secondary). Description and title text are preserved through the switch. The form never silently attaches a new description to existing progress.

#### Intake, invalid slug

Inline error under the field, from the helper's message when the failure came from the helper, otherwise the local rule ("lowercase letters, digits, and hyphens, 1 to 50 characters"). Border turns `--color-red`. Submit disabled.

#### Intake, submitting

Fields locked at 0.5 opacity, button label becomes "Starting…" with the width locked. Generation is fast, so no progress bar or stage list.

#### Interview, first load

Because a provisional PRD exists from the first call, the populated state is the first state. The preview shows the draft, the coverage rail shows every area with its label, and the question column shows the highest-value clarification. There is no onboarding overlay and no empty document.

#### Interview, loading

Three region shells at the correct sizes with content at 0.4 opacity, fading to full on arrival. No pulsing, no spinner over the page. The rail and preview populate first if the payload arrives together; they must not reflow when the question card lands.

#### Interview, populated (question)

Standard state. One question card, one control, one primary action. The preview keeps its scroll position across answers.

#### Interview, follow-up pending

FollowUpNotice above the suggestion, control replaced by AnswerTextarea with an empty value and the follow-up prompt as its label. The original answer stays visible as read-only text above the notice so the author can see what is being extended.

#### Interview, edit prefill

Control is AnswerTextarea prefilled from `initial_value` with the caret at the end. The suggestion panel collapses to its confidence chip to give the field room while keeping the sources one click away.

#### Interview, suggestion rejected

Suggestion panel renders struck-through at tertiary with a "Rejected" chip; control becomes an empty AnswerTextarea. The rejected text stays visible because provenance is preserved.

#### Interview, self-review repair

FindingsNotice lists each finding for this question; control is AnswerTextarea prefilled with the current answer. The preview shows the artifact that produced the findings, not a cleared document.

#### Interview, blocked

Question card stays, BlockingNotice appears below it naming the deferred required questions and stating that generation is blocked until they are confirmed. The draft remains available and openable: deferral never removes the provisional artifact.

#### Interview, drafted

Question column swaps to SelfReviewSummary: passed, the artifact path, and two actions, "Open in editor" and "Back to feature". The coverage rail shows every row confirmed or not-material. The preview stays exactly where it was. No modal, no confetti, no redirect.

#### Interview, drafted with open questions

Same layout, amber SelfReviewSummary listing each open finding with its source question ID and an Edit action that reopens that question. The document's own open-questions section is visible in the preview.

#### Interview, revision conflict

ConflictBanner in flow, save chip red, control disabled but not cleared. Any text the author typed stays in the textarea across the reload so nothing is destroyed by someone else's write.

#### Interview, helper unavailable

Question column replaced by HelperUnavailable: what failed, the resolved helper path and interpreter in mono, and a retry action. The preview still renders the last known artifact if one was loaded. The UI never substitutes a question of its own.

#### Interview, multiplayer project

Question column shows a single notice that guided authoring runs in single-player layouts until path resolution is shared, with the CLI command as the alternative. No partial interview is offered.

### Interactive Element States

| Component | Enabled | Hover | Focus | Pressed | Disabled | Loading |
|-----------|---------|-------|-------|---------|----------|---------|
| PrimarySubmit | bg `--color-accent`, text `--color-bg` | brightness 1.08 | outline 2px `--color-accent`, offset 2px | scale 0.98 | opacity 0.4, `cursor: not-allowed`, no pointer events | label to "Saving…", width locked, no spinner |
| SecondaryAction | text `--color-text-secondary` | text `--color-text`, bg `rgba(255,255,255,0.03)` | outline 2px `--color-accent`, offset 2px | bg `rgba(255,255,255,0.06)` | opacity 0.4 | n/a |
| ActionChoiceGroup option | border `--color-border`, text `--color-text` | border `--color-accent-glow`, bg `rgba(255,255,255,0.03)` | outline 2px `--color-accent`, offset 2px | bg `--color-accent-dim` | opacity 0.4, no pointer events | n/a |
| ActionChoiceGroup option (selected) | border `--color-accent`, bg `--color-accent-dim` | same, brightness 1.04 | outline as above | n/a | opacity 0.4 | n/a |
| AnswerTextarea | bg `--color-bg-elevated`, border `--color-border` | border `rgba(255,255,255,0.10)` | border `--color-accent`, `box-shadow 0 0 0 2px var(--color-accent-glow)` | n/a | opacity 0.5, readonly | n/a |
| SlugField | as AnswerTextarea | as above | as above | n/a | opacity 0.5 | caption "Checking…" |
| CoverageRow (confirmed) | text `--color-text-secondary` | bg `rgba(255,255,255,0.03)`, text `--color-text` | outline 2px `--color-accent`, offset -2px | bg `rgba(255,255,255,0.06)` | n/a | n/a |
| CoverageRow (unanswered) | text `--color-text-secondary` | no change, `cursor: default` | not focusable | n/a | n/a | n/a |
| SectionProvenance Edit | text `--color-text-secondary`, hidden until section hover | text `--color-text`, underline | outline 2px `--color-accent`, offset 2px, always visible when focused | n/a | opacity 0.4 while a mutation is in flight | n/a |
| ResumeCard | `.surface` | `.surface-hover` | outline 2px `--color-accent`, offset 2px | scale 0.995 | n/a | n/a |
| SourcePathRef | text `--color-text-tertiary` | text `--color-text-secondary`, path fully expanded | outline 2px `--color-accent`, offset 2px | n/a | n/a | n/a |

Edit actions in the preview are revealed on section hover but must be reachable by keyboard at all times: focus makes them visible regardless of pointer position.


## Data Binding

Every field below comes from the helper result. No element on this surface derives interview content from anywhere else.

| Element | Source Field | Format | Constraints |
|---------|-------------|--------|-------------|
| Authoring bar title | `intake.feature_title`, falling back to the slug title-cased | string | Truncate at 48 chars with ellipsis, full value in `title` attribute |
| Artifact chip | `artifact_type` | uppercase label from `ARTIFACTS[type].label` | Always "PRD" on this surface |
| Revision | `revision` | `rev {n}` | Mono; changes are announced politely |
| Save chip | mutation lifecycle plus `status` | enum | `saved` only after a returned revision exceeds the held one |
| Progress count | `progress.confirmed` / `progress.total` | `{c}/{t} confirmed` | Denominator may decrease; never cached across payloads |
| Coverage rows | `coverage` entries | one row per key, helper order | Confidence and impact render as returned; never recomputed client-side |
| Coverage dot state | `answers` state plus `current_question.id` | enum | Active is the current question only |
| Question ID | `current_question.id` | string | Mono, verbatim |
| Question prompt | `current_question.prompt` | string | Verbatim, no truncation, no re-wrapping of punctuation |
| Evidence body | `current_question.evidence` | string | Clamp 3 lines, expand in place |
| Purpose tooltip | `current_question.purpose` | string | Optional; omitted when absent |
| Suggestion body | `current_question.suggestion.answer` | string | When null, render the explicit no-grounded-response line, never an empty box |
| Suggestion chip | `current_question.suggestion.confidence` | `grounded` / `partial` / `missing` | Chip text is the raw value title-cased |
| Suggestion sources | `suggestion.sources[]` | `{id, path, status, excerpt}` | Path middle-truncated to 44 chars; excerpt clamped to 2 lines |
| Gaps | `suggestion.gaps[]` | string list | Rendered in full; never summarised |
| Follow-up prompt | `current_question.follow_up.prompt` | string | Verbatim |
| Findings | `current_question.review_findings[]` | `{message, question_id}` | Verbatim messages |
| Control options | `response_control.options[]` | `{value, label}` | Rendered in the returned order with the returned labels; nothing added or removed |
| Textarea prefill | `response_control.initial_value` | string | Empty string means empty field, not a placeholder answer |
| Blocking notice | `progress.deferred[]` and `message` | list plus string | Helper message verbatim |
| Preview document | artifact content at `artifact_path` | Markdown | Read-only; re-rendered per revision |
| Section provenance | `sections[]` | `{title, question_ids, coverage_ids}` | Order and titles from the helper; never parsed from Markdown |
| Self-review summary | `self_review` | `{status, findings[], pass_count}` | Findings grouped by `question_id` |
| Resume card status | `status` and `progress` | enum plus counts | From `--peek`, which must not mutate state |
| Helper identity footer | `implementation.helper_hash`, `question_bank_hash` | `sha256:` prefix, first 12 chars shown | Full value on hover; proves which implementation answered |


## Interactions & Motion

### Interactions

| Trigger | Target | Response | Notes |
|---------|--------|----------|-------|
| Type in title | SlugField | Slug re-derives from the title | Stops deriving permanently once the slug is edited by hand |
| Blur slug, or 300ms after last keystroke | SlugField | `authoringSession` check for that slug | Read-only call; must not create a checkpoint |
| Submit intake | Intake form | `startAuthoring`, then route to the interview page | Button locks; failure keeps every field intact |
| Select an action option | ActionChoiceGroup | Marks selection only | No mutation on selection: confirmation is always a second, explicit act |
| Click Continue with Accept, Reject, or Defer selected | Question card | `selectAuthoringAction` with the rendered revision | Card enters loading, options disabled but visible |
| Click Continue with Edit or Answer selected | Question card | `selectAuthoringAction(EDIT)`, control returns as a prefilled textarea | Two steps, matching the helper's persisted edit request |
| Submit answer text | AnswerTextarea | `submitAuthoringAnswer` with the rendered revision | Empty or whitespace-only text does not submit |
| Cmd/Ctrl + Enter in textarea | AnswerTextarea | Submits | Plain Enter inserts a newline: answers are prose |
| Answer confirmed | Preview | Document replaced, affected sections highlighted, scroll position kept | Highlight targets sections whose `question_ids` include the answered ID |
| Click Edit on a section | SectionProvenance | `reviseAuthoringCoverage` opens that question, question column scrolls into view | Never opens an inline Markdown editor |
| Click a confirmed coverage row | CoverageRail | Preview scrolls to that question's first section | Read-only navigation |
| Mutation returns `revision_conflict` | Page | ConflictBanner appears in flow, save chip red, control disabled | Typed text preserved verbatim |
| Click Reload in the banner | ConflictBanner | Refetch, banner clears, typed text restored into the new control when the question is unchanged | |
| Checkpoint changed by another surface | Page | Subscription refetches; if the current question is unchanged, only the rail and preview update | Never yanks a control the author is typing into |
| Open artifact path | Preview header | Routes to `/editor` for that path | Read-only view of the same file |

### Motion

| Name | Duration | Easing | Property | Usage |
|------|----------|--------|----------|-------|
| `state-change` | 120ms | ease-out | background, border-color, box-shadow | Option, row, and button state transitions |
| `card-enter` | 160ms | ease-out | opacity | New question card replacing the previous one |
| `region-reveal` | 200ms | ease-out | opacity | Region shells resolving from 0.4 to 1 on first load |
| `section-highlight` | 240ms in, 600ms hold, 400ms out | ease-in-out | background | Regenerated section flash in `--color-accent-dim` |
| `notice-enter` | 160ms | ease-out | opacity, height | Conflict banner, blocking notice, follow-up notice |

No transform-based slides, no staggered lists, no height animation on the question card itself: the card changes content, and animating its box would shift the control under the pointer.

**Reduced motion policy:** under `prefers-reduced-motion: reduce`, all five entries become instant state changes. The section highlight still applies its background for the hold duration and then removes it without a fade, because the highlight carries information about what changed. Nothing is removed, only the motion.


## Responsive Behavior

The dashboard targets desktop. The floor is a 1024px laptop; below that the interview stays usable but stops being a three-column reading surface.

| Breakpoint | Columns | Behavior |
|------------|---------|----------|
| < 768px | 1 | Coverage rail and preview both collapse into a two-tab strip under the authoring bar ("Coverage", "Draft"), question card full width. Intake card goes edge to edge with 16px page padding. Section Edit remains available inside the Draft tab. |
| 768–1279px | 2 | Coverage rail collapses to a 40px-tall summary strip above the question card, showing the progress count and confidence dots only. Preview keeps its own column at 360px. |
| 1280–1599px | 3 | Full layout. Coverage 280px, question column fluid with 640px content max, preview 420px. |
| ≥ 1600px | 3 | Same regions; the question column's extra width goes to margins, not to line length. Preview may grow to 480px. |

The question column never falls below 320px of content width, and the preview is the region that yields first. Losing the document is recoverable through a tab; losing the question is not.


## Accessibility

### Keyboard Navigation

| Component | Keys | Behavior |
|-----------|------|----------|
| Intake form | Tab | Title, slug, description, submit, in that order |
| Intake form | Enter (single-line fields) | Submits when valid |
| ActionChoiceGroup | Arrow Up/Down | Move selection within the group (single tab stop, roving tabindex) |
| ActionChoiceGroup | Space / Enter | Select the focused option |
| ActionChoiceGroup | 1–4 | Select the option at that position, mirroring the CLI's numbered prompt |
| Question card | Enter on Continue | Submit the selected action |
| AnswerTextarea | Cmd/Ctrl + Enter | Submit the answer |
| AnswerTextarea | Escape | Return focus to the control's first element without discarding text |
| CoverageRail | Tab, then Arrow Up/Down | Enter the list once, then move between confirmed rows |
| DraftPreview | Tab | Reaches each section's Edit action in document order |
| ConflictBanner | Tab | First stop after the authoring bar while present |

No component traps focus, because nothing here is modal. Tab order follows the visual order: bar, banner, rail, question, preview.

### ARIA & Screen Reader

| Component | Role | ARIA | Announcement |
|-----------|------|------|--------------|
| ActionChoiceGroup | `radiogroup` | `aria-labelledby` on the control prompt; each option `role="radio"` with `aria-checked` | "How would you like to respond? Accept suggestion, radio 1 of 4" |
| AnswerTextarea | `textbox` | `aria-labelledby` the control prompt, `aria-describedby` the gap list | Label read on focus, gaps read after it |
| SaveStateChip | `status` | `aria-live="polite"` | "Saved, revision 3" |
| CoverageProgress | `status` | `aria-live="polite"` | "1 of 2 confirmed" |
| QuestionCard | `region` | `aria-labelledby` the question ID and prompt | Announced on question change |
| SuggestionPanel | `group` | `aria-label="Suggested response, {confidence}"` | Confidence announced before the body |
| FollowUpNotice | `note` | `aria-live="polite"` | Follow-up prompt read when it appears |
| FindingsNotice | `alert` | `aria-live="assertive"` | Finding messages read immediately |
| ConflictBanner | `alert` | `aria-live="assertive"` | "Someone else answered. This tab holds revision 2, current revision is 3." |
| BlockingNotice | `note` | `aria-live="polite"` | Deferred questions and the blocking reason |
| SectionProvenance Edit | `button` | `aria-label="Edit the answer behind {section title}, question {ids}"` | Names the question, not just "Edit" |
| DraftPreview | `document` | `aria-label="Generated PRD, revision {n}"` | |

The document is a live surface: after a regeneration, the preview's container announces "PRD updated, revision {n}" politely, once, rather than announcing every changed section.

### Contrast & Targets

Body text uses `--color-text-secondary` (~5.5:1 on `--color-bg-card`) or better. `--color-text-tertiary` (~2.8:1) is restricted to source paths, provenance IDs, captions, and the not-material label, none of which are required to make a decision. Gap text is explicitly secondary, not tertiary, because an author reads gaps to decide whether a suggestion is safe to accept.

Radio rows are 36px tall and full-width clickable. The submit button is 32px tall, above the 24px minimum for pointer targets on a desktop-only surface, and the Edit actions in the preview get 24px of hit area with 8px of separation from adjacent text. Accent on `--color-bg` for the primary button clears 4.5:1; accent as text is only used for the question ID at 13px/500, which clears the large-text threshold against `--color-bg-card`.


## Content Constraints

| Element | Min | Max | Overflow | Placeholder |
|---------|-----|-----|----------|-------------|
| Feature title | 1 char | 80 chars | Ellipsis after 1 line in the bar; full text in the form | "Name this feature" |
| Slug | 1 char | 50 chars | No wrap, horizontal scroll in field | Derived from title |
| Description | 1 char (helper), 40 chars recommended | 2000 chars | Field scrolls after 240px height | "Who hits the problem, what happens today, and what should change" |
| Description helper hint | — | — | — | Shown below 40 chars, as a hint, never as a block |
| Question prompt | — | — | Wraps freely, never truncated | — |
| Evidence body | — | — | Clamp 3 lines, "Show more" expands in place | — |
| Suggestion body | — | — | Clamp 6 lines, expands in place | "No grounded response is available for this question." |
| Suggestion source path | — | — | Middle-truncate at 44 chars, full path on hover and focus | — |
| Suggestion excerpt | — | — | Clamp 2 lines | — |
| Gap text | — | — | Wraps freely, never clamped | — |
| Answer textarea | 1 non-whitespace char | none | Grows to 320px, then scrolls | Control prompt is the label, not a placeholder |
| Coverage question ID | — | — | No wrap | — |
| Confidence label | — | — | No wrap | — |
| Section provenance IDs | — | 4 IDs shown | "+N" suffix, full list on hover | — |
| Finding message | — | — | Wraps freely | — |
| Helper hash | — | 12 chars shown | Full value on hover | — |

Placeholders are hints only. No field on the intake form is pre-filled with example content, because a prefilled description becomes evidence in the generated PRD.


## Implementation Notes

- Section provenance comes from `sections[]` in the result. Do not parse the rendered Markdown to find a section's source question: `_render_prd_section` emits no per-question headings, so any regex over the document will silently mis-attribute an Edit action.
- Send the revision that the rendered control came from, not the newest one the client has seen. A subscription refetch that updates the rail must not quietly raise the revision behind an in-progress answer.
- `response_control.options` is the whole truth about available actions. Never synthesise Accept for a `partial` suggestion, never render an omitted action as disabled, and never reorder options to a house convention.
- The preview must not steal focus. It re-renders on every confirmed answer, so key the document container by revision and keep the focused element in the question column untouched.
- `authoring-bar` and `coverage-rail` use `position: sticky`, which fails inside an ancestor with `overflow: hidden`. The existing `<main>` in the Define pages sets `overflow: auto`; keep the sticky elements outside any wrapper that clips.
- Reuse `editor/SpecPreview.tsx` for Markdown rendering rather than adding a second renderer. Wrap it for the header strip and provenance footers; do not fork its typography.
- `progress.total` can decrease when the planner drops an unsurfaced question. Derive the count from each payload and never persist it in component state across fetches.
- `--peek` is required for every read path, including the slug collision check and the ResumeCard. A plain call creates the checkpoint and generates the draft, so a hover-prefetch or a stray poll would create feature state the author never asked for.
- Do: use `.surface` for the question card, intake card, and preview panel. Don't: apply a shadow without its paired border, and don't elevate the suggestion panel, which is an inset block.
- Confidence and impact labels are helper vocabulary (`evidence_backed`, `not_material`, `conditional`). Title-case them for display in one shared formatter; do not remap them to friendlier words in individual components, or the browser and the terminal will disagree about what an area's state is called.


## Verification Criteria

### Intake
- [ ] Title, slug, and description render from `next_input.fields`, with the helper's labels and descriptions
- [ ] Slug derives from the title until manually edited, then stops deriving
- [ ] The slug check performs a read-only call and creates no `.speed/features/<slug>/` directory
- [ ] A colliding slug offers Resume or rename, and never submits a new description into existing progress
- [ ] No field is prefilled with example content
- [ ] Submitting routes to `/define/:feature/authoring/prd` with a draft already present

### Interview content fidelity
- [ ] Question prompt, evidence, option labels, and option order match the CLI `--json` payload byte for byte
- [ ] An omitted action never appears, including as a disabled control
- [ ] A `partial` or `missing` suggestion offers no Accept path anywhere in the UI
- [ ] Gap and finding text render in full, unclamped and unsummarised
- [ ] Coverage labels and impacts display the helper's values with no client-side recomputation

### Interview behaviour
- [ ] The first load shows a populated preview and a question, never an empty document
- [ ] Confirming an answer keeps the preview's scroll position and highlights only sections sourced from that question
- [ ] Selecting an action never mutates state without the explicit Continue
- [ ] Edit is a two-step flow: action persisted, then a prefilled textarea
- [ ] Section Edit opens the question named in `sections[].question_ids`
- [ ] Deferring a required question shows the blocking notice and leaves the draft openable
- [ ] `revision_conflict` renders the in-flow banner, keeps typed text, and offers reload
- [ ] A CLI answer updates the rail and preview without disturbing focus in the question column
- [ ] `drafted` and `drafted_with_open_questions` both render in place, with no modal and no redirect

### Design system
- [ ] Token audit passes with zero hardcoded colour, font, or size values outside the token set
- [ ] Accent appears only on the question ID, the primary submit, and the active coverage dot
- [ ] Every elevated element carries border and shadow together
- [ ] All spacing values are multiples of 4
- [ ] No text element sets a size without its role's weight and colour
- [ ] Gap text is `--color-text-secondary` or brighter

### Accessibility
- [ ] Every interactive element has a visible focus indicator
- [ ] Tab order matches bar, banner, rail, question, preview
- [ ] ActionChoiceGroup is one tab stop with arrow-key selection and 1–4 shortcuts
- [ ] Findings and conflicts announce assertively; save state and progress announce politely
- [ ] Section Edit buttons are keyboard reachable while hidden to the pointer
- [ ] `prefers-reduced-motion: reduce` removes all five motion entries while keeping every state change

### Responsive
- [ ] Layout matches the breakpoint table at 640px, 1024px, 1280px, and 1600px
- [ ] The question column never renders below 320px of content width
- [ ] Below 768px, coverage and draft are reachable as tabs with the question card full width


## Figma / Visual Reference

None. The ASCII layouts in Intake Layout, Interview Layout, and Question Card Anatomy are the visual reference, and `dashboard/frontend/app/globals.css` is the source of truth for every token. When a future Figma frame disagrees with this spec, Figma wins on pixel-level aesthetics and this spec wins on behaviour, states, data binding, and spatial relationships.
