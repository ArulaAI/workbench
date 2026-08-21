# Design: Define Ceremony — Bootstrap Wizard

> See [product spec](../product/speed-define-ceremony.md) for product context (stories S11, S12).
> See [tech RFC](../tech/speed-define-ceremony-bootstrap.md) for API surface and data model.
> Parent design spec: [speed-define-ceremony.md](speed-define-ceremony.md) — component inventory, full typography/color tables, accessibility matrix.
> Design system: `dashboard/frontend/app/globals.css`

<!--
  WHO READS THIS SPEC
  AI coding agents use this as their primary implementation reference.
  Humans review it, but agents execute from it. Every visual property
  references a token from globals.css. If the token doesn't exist,
  flag it for addition. Never write a raw hex, pixel, or font name
  outside of the token definitions.

  SCOPE
  Three components: BootstrapWizard, VisionDraftEditor, ConventionReview.
  One flow: cold start detection at /define/new, 4-step linear wizard
  (graph build, vision, conventions, complete). Everything else in the
  ceremony editor is covered by sibling design specs.
-->


## Design Intent

When an author opens `/define/new` on a project with no semantic graph, no vision, and no project knowledge, the system needs to build all three before the Define ceremony can deliver useful context. Bootstrap is the guided setup that produces those artifacts.

**Direction:** Each step produces a visible artifact the author can inspect: a semantic graph with file counts, a vision document they can edit, a set of conventions they accept or reject. The wizard should feel like walking through rooms of a building, not filling out a form. Progress is linear and irreversible within a session. Before each step runs, the author reads what it will do. After it finishes, they see what it produced.

**Do not:** Let the wizard feel like a settings panel or configuration form. Use tabs or free navigation between steps (progress is strictly linear, completed steps are read-only). Apply accent color to decorative elements (accent marks completed steps and primary actions only). Show raw JSON, file paths, or system internals outside of the discovery feed. Use borders without paired shadows on elevated elements. Skip the complete step or auto-dismiss the wizard after conventions.


## Scope

Three components compose the bootstrap flow:

| Component | File | Role |
|-----------|------|------|
| BootstrapWizard | `ceremony/BootstrapWizard.tsx` | Stepped container: step indicator bar, step panels, navigation between steps |
| VisionDraftEditor | `ceremony/VisionDraftEditor.tsx` | Split-pane editor: LLM-generated draft (left, read-only) and author's editable version (right) |
| ConventionReview | `ceremony/ConventionReview.tsx` | List of system-extracted conventions with per-item accept/reject, bulk accept, and persona input fields |

One route: `/define/new`, intercepted when cold start is detected (all three conditions true: no semantic graph, no vision, no project knowledge). The wizard replaces the IntentInput card. Four linear steps: Graph Build, Vision, Conventions, Complete.


## Layout Structure

### Global Layout

No changes to global layout. The IconRail (52px, left) remains visible. The wizard renders within the existing content region, centered horizontally and vertically.

### Region

| Region ID | Position | Width | Internal Layout | Scroll | Closable |
|-----------|----------|-------|-----------------|--------|----------|
| bootstrap-flow | Content area (`/define/new`, cold start) | Full content width, max 640px centered horizontally | Vertical stack: step indicator bar, then active step panel | Yes (page scroll) | No |

### Wizard Layout

```
┌─────────────────────────────────────────────────────────────────┐
│  IconRail (52px)  │                                             │
│                   │                                             │
│   S               │    ①─────②─────③─────④                     │
│   ⌂               │    Graph  Vision Conv  Done                 │
│   ✎ (active)      │                                             │
│   ◈               │    ┌───────────────────────────────┐        │
│                   │    │                               │        │
│                   │    │  [Active step panel content]  │        │
│                   │    │                               │        │
│                   │    │                               │        │
│                   │    └───────────────────────────────┘        │
│                   │                                             │
└─────────────────────────────────────────────────────────────────┘
```

The wizard card is a `.surface` element (`--color-bg-card`, border + shadow). Max width 640px. Internal padding 24px. The step indicator bar sits at the top of the card, followed by the active step panel.

### Step Indicator Bar

```
  ●──────●──────○──────○
  Graph   Vision  Conv   Done
  (done)  (current)(next)(next)
```

Four numbered circles connected by horizontal lines. Each circle is 22px diameter, `--font-mono` 11px 600. Connectors are 1px horizontal lines with flex-grow spacing, 12px margin on each side.

| Step State | Circle | Label | Connector Before |
|------------|--------|-------|------------------|
| Complete | `--color-accent` background, `--color-bg` checkmark icon (12px) | `--color-accent` | Accent fill (1px, animated left-to-right) |
| Current | `--color-bg-card-hover` background, `--color-text` number, 1.5px `--color-text` border | `--color-text` | `--color-accent` fill (completed segment) |
| Pending | transparent background, `--color-text-tertiary` number, 1.5px `--color-text-tertiary` border | `--color-text-tertiary` | `--color-border` (unfilled) |

When a step completes, its number is replaced by a checkmark icon (display swap, not animation). The connector between the completed step and the next step fills with `--color-accent` over 400ms ease.

### Step 1: Graph Build

```
┌───────────────────────────────────────┐
│                                       │
│  Build your codebase graph            │  ← step title
│  SPEED indexes your source files to   │  ← step description
│  understand project structure.        │
│                                       │
│  247 files indexed                    │  ← hero counter
│                                       │
│  ████████████░░░░░░░░░  68%           │  ← progress bar
│                                       │
│  ┌─────────────────────────────────┐  │
│  │ ✓ src/auth/Users.php    indexed │  │  ← discovery feed
│  │ ✓ src/auth/Session.php  indexed │  │
│  │ ● src/api/Router.php    parsed  │  │
│  │ · tests/fixtures/       skipped │  │
│  └─────────────────────────────────┘  │
│                                       │
│                          [ Continue ] │  ← enabled when build complete
│                                       │
└───────────────────────────────────────┘
```

**Hero counter.** A large number showing files indexed so far. The value (e.g., "247") is `--font-mono` 36px 600 `--color-text`, letter-spacing -0.02em, `font-variant-numeric: tabular-nums`. The unit label ("files indexed") is `--font-mono` 13px 400 `--color-text-secondary`, aligned to baseline with the number.

**Progress bar.** 4px track in `--color-bg-elevated`, 2px border-radius. Fill in `--color-accent` with a subtle glow (`0 0 8px rgba(0, 212, 170, 0.3)`). Width transitions via CSS `transition: width 0.3s ease`.

**Discovery feed.** A scrollable list (max-height 180px) showing files as they are processed. Each row contains an icon (14px), a file path (`--font-mono` 11px `--color-text-secondary`, truncated with ellipsis), and a status tag.

| Tag | Text Color | Background |
|-----|------------|------------|
| indexed | `--color-accent` | `--color-accent-dim` |
| parsed | `--color-blue` | `rgba(75, 166, 238, 0.1)` |
| skipped | `--color-text-tertiary` | `rgba(85, 85, 106, 0.12)` |

Tags use `--font-mono` 9px 500, uppercase, letter-spacing 0.05em, padding 1px 5px, border-radius 3px. Feed items appear with a staggered animation: each new item slides in from the left (8px translateX) and fades in over 300ms. Rows are separated by 1px `--color-border-light` bottom borders.

**Continue button.** Disabled (`--color-text-tertiary` background, 50% opacity, `cursor: not-allowed`) while the build runs. Enabled (`--color-accent` background, `--color-bg` text) once `graphBuildStatus` reaches "complete". If the build errors, a red error message replaces the progress bar and a "Retry" link in `--color-accent` appears.

### Step 2: Vision

```
┌───────────────────────────────────────┐
│                                       │
│  Establish your product vision        │
│  A vision document anchors Guardian   │
│  checks and context delivery.         │
│                                       │
│   [ Generate from codebase ]          │
│   [ Write from scratch ]              │
│                                       │
│  ─ ─ ─ ─ ─ after generation ─ ─ ─ ─  │
│                                       │
│  ┌─────────────┬─────────────────┐    │
│  │ GENERATED   │ YOUR VERSION    │    │
│  │ Regenerate ↻│                 │    │
│  │             │                 │    │
│  │ Appwrite is │ Appwrite is a   │    │
│  │ a self-host…│ self-hosted     │    │
│  │             │ backend-as-a-   │    │
│  │ (read-only) │ service...      │    │
│  │             │ (editable)      │    │
│  └─────────────┴─────────────────┘    │
│                                       │
│            [ Skip ]  [ Commit Vision ]│
│                                       │
└───────────────────────────────────────┘
```

**Choice phase.** Two options presented as buttons stacked vertically. "Generate from codebase" is `btn-primary` (accent). "Write from scratch" is `btn-secondary` (transparent, `--color-border`, `--color-text-secondary`). Choosing "Write from scratch" skips generation and shows only the right pane (editable, empty).

**Split pane.** Two side-by-side panes separated by a 1px `--color-border` divider. The container has border-radius 8px and `overflow: hidden`.

| Pane | Background | Label Color | Content Editability |
|------|------------|-------------|---------------------|
| Left (Generated) | `--color-bg-elevated` | `--font-mono` 11px 500 uppercase, `--color-text-tertiary` | Read-only |
| Right (Your Version) | `--color-bg-card` | `--font-mono` 11px 500 uppercase, `--color-text` | `contenteditable` |

Each pane has 20px padding. Content text is `--font-sans` 13px 400 `--color-text-secondary`, line-height 1.6. Editable content on focus gets a subtle background lift: `rgba(255, 255, 255, 0.03)`, border-radius 4px.

**Regenerate link.** Positioned in the left pane header, right-aligned. `--font-sans` 12px 500 `--color-accent`. On hover, opacity 0.8. During regeneration, a shimmer overlay sweeps across the left pane (linear gradient, `rgba(0, 212, 170, 0.15)` at center, 2.5s infinite loop). The right pane is unaffected by regeneration.

**Commit Vision button.** `btn-primary`. Disabled when the right pane is empty or whitespace-only. Calls `commitVision` with the right pane content. On success, writes to `specs/product/overview.md` and advances to step 3.

**Skip link.** `--font-sans` 12px 500 `--color-text-secondary`. Vision is technically required for bootstrap completion, but the author can skip this step during the wizard and come back before the final "Complete" step. The step indicator marks it as "skipped" (`--color-text-tertiary`).

### Step 3: Conventions

```
┌───────────────────────────────────────┐
│                                       │
│  Review extracted conventions         │
│  SPEED analyzed your codebase and     │
│  found these patterns.      Accept all│
│                                       │
│  ┌─────────────────────────────────┐  │
│  │ ✓ All new endpoints require     │  │
│  │   rate limiting                 │  │
│  │   CI CONFIG  high        ✓  ✕  │  │
│  │─────────────────────────────────│  │
│  │   ESLint enforces no-unused-    │  │
│  │   vars with error severity      │  │
│  │   DETECTED   mid         ✓  ✕  │  │
│  │─────────────────────────────────│  │
│  │ ✕ Composer dependencies locked  │  │
│  │   to minor version              │  │
│  │   INFERRED   low         ✓  ✕  │  │
│  └─────────────────────────────────┘  │
│                                       │
│  ENGINEERING CONVENTIONS              │
│  ┌─────────────────────────────────┐  │
│  │ e.g. "We deploy via Docker,    │  │
│  │  staging required before prod" │  │
│  └─────────────────────────────────┘  │
│                                       │
│  PRODUCT CONVENTIONS                  │
│  ┌─────────────────────────────────┐  │
│  │ e.g. "All features need a      │  │
│  │  rollout plan before launch"   │  │
│  └─────────────────────────────────┘  │
│                                       │
│            [ Skip ]  [ Commit ]       │
│                                       │
└───────────────────────────────────────┘
```

**Convention list.** A container with border-radius 8px, `overflow: hidden`. Each row is `--color-bg-elevated` background, `--color-border-light` bottom border, 10px 16px padding. Rows have three zones: content (flex: 1), metadata, and toggle buttons.

**Convention content.** Text in `--font-sans` 13px 400 `--color-text-secondary`, line-height 1.4.

**Source badge.** `--font-mono` 9px 500 uppercase, letter-spacing 0.04em, padding 2px 6px, border-radius 4px.

| Source Type | Text Color | Background |
|-------------|------------|------------|
| inferred | `--color-violet` | `--color-violet-glow` |
| explicit | `--color-blue` | `rgba(75, 166, 238, 0.1)` |
| detected | `--color-amber` | `rgba(240, 178, 50, 0.1)` |

**Confidence tag.** `--font-mono` 10px 500, right-aligned, 32px fixed width.

| Confidence | Color |
|------------|-------|
| high | `--color-emerald` |
| mid | `--color-amber` |
| low | `--color-text-tertiary` |

**Toggle buttons.** Accept and reject icons in 26x26px buttons, border-radius 5px. Default state: both icons in `--color-text-tertiary`. Hover states and active states:

| Button | Hover | Active |
|--------|-------|--------|
| Accept (checkmark) | `--color-emerald` text, `rgba(68, 204, 119, 0.08)` background | `--color-emerald` text, `rgba(68, 204, 119, 0.12)` background |
| Reject (x-mark) | `--color-red` text, `rgba(239, 68, 100, 0.08)` background | `--color-red` text, `rgba(239, 68, 100, 0.12)` background |

Accepted rows remain at full opacity. Rejected rows dim to 40% opacity. Transitions take 150ms ease.

**Accept All button.** Positioned in the conventions header, right-aligned. `--font-mono` 10px 500 uppercase, `--color-accent` text, `--color-accent-dim` background, border-radius 5px, padding 4px 10px. On hover, background changes to `--color-accent-glow`.

**Persona input fields.** Below the convention list, optional text areas for manual convention entry. Label: `--font-mono` 11px 500 `--color-text-tertiary` uppercase, letter-spacing 0.04em. Input: `--color-bg-elevated` background, 1px `--color-border`, border-radius 8px, padding 12px 14px, `--font-sans` 13px `--color-text`, min-height 64px. Placeholder in `--color-text-tertiary`. Focus: border-color changes to `rgba(0, 212, 170, 0.3)`.

Three persona sections: Engineering, Product, Design. Each is independent. Empty inputs are valid (author can skip persona prompts entirely).

**Commit button.** `btn-primary`. Calls `commitConventions` with accepted conventions and persona inputs. On success, advances to step 4.

### Step 4: Complete

```
┌───────────────────────────────────────┐
│                                       │
│               ┌───┐                   │
│               │ ✓ │  ← accent circle  │
│               └───┘                   │
│                                       │
│        Project bootstrapped           │
│        SPEED is ready for your        │
│        first Define ceremony.         │
│                                       │
│   ┌──────────┬──────────┬──────────┐  │
│   │   247    │    1     │    8     │  │
│   │  files   │  vision  │ conven-  │  │
│   │ indexed  │ committed│  tions   │  │
│   └──────────┴──────────┴──────────┘  │
│                                       │
│          [ Start defining ]           │
│                                       │
└───────────────────────────────────────┘
```

**Checkmark circle.** 56px diameter, `--color-accent-dim` background, centered. Inner checkmark icon is 28px `--color-accent`. Entrance animation: scale from 0 to 1 with a spring curve (`cubic-bezier(0.34, 1.56, 0.64, 1)`, 400ms).

**Completion text.** Title: `--font-sans` 17px 600 `--color-text`. Subtitle: `--font-sans` 13px 400 `--color-text-secondary`. Both centered.

**Stats grid.** Three equal columns, 16px gap. Each stat card: `--color-bg-elevated` background, 1px `--color-border-light`, border-radius 8px, padding 16px. Value: `--font-mono` 24px 600 `--color-text`, line-height 1. Label: `--font-sans` 11px 500 `--color-text-tertiary`.

**Start defining button.** `--font-sans` 14px 600, `--color-accent` background, `--color-bg` text, border-radius 8px, padding 10px 28px. On hover, opacity 0.9. On click, calls `completeBootstrap` and navigates to `/define/new` with the IntentInput card (bootstrap is finished, cold start conditions no longer met).


## Component Inventory

All components are defined in the [parent design spec](speed-define-ceremony.md#component-inventory). Below are rendering details specific to the bootstrap flow.

### BootstrapWizard

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| steps | BootstrapStep[] | required | Array of `{ id, title, status }` where status is `"pending"` \| `"current"` \| `"complete"` \| `"skipped"` |
| currentStep | string | required | Active step ID: `"graph"` \| `"vision"` \| `"conventions"` \| `"complete"` |
| onStepComplete | (stepId: string, data: unknown) => void | required | Called when a step finishes with its output data |
| onSkip | (stepId: string) => void | required | Called when author skips an optional step |
| graphBuildStatus | `"not_started"` \| `"building"` \| `"complete"` \| `"error"` | required | Background graph build progress, tracked independently from step progression |

### VisionDraftEditor

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| generatedDraft | string \| null | null | LLM-generated vision text. Null if "write from scratch" chosen. |
| sources | string[] | [] | Files the LLM used as input (shown as metadata) |
| generating | boolean | false | True while LLM is generating draft |
| onCommitVision | (content: string) => void | required | Writes vision to `specs/product/overview.md` |
| onRegenerate | () => void | required | Triggers re-generation, replaces left pane content |

### ConventionReview

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| derivedConventions | DerivedConvention[] | required | System-extracted conventions with `{ id, text, source, category, status, confidence }` |
| onAccept | (id: string) => void | required | Mark convention as accepted |
| onReject | (id: string) => void | required | Mark convention as rejected |
| onAcceptAll | () => void | required | Accept all pending conventions |
| onCommit | (personaInputs: PersonaConventionInput) => void | required | Commit accepted conventions and persona inputs |


## States

### BootstrapWizard States

| State | Step Indicator | Panel Content | Actions Available |
|-------|---------------|---------------|-------------------|
| detecting | All steps pending | Spinner + "Checking project status..." in `--color-text-secondary` | None |
| step-1-idle | Step 1 current, 2-4 pending | Step 1 title, description, "Build Graph" button | Build Graph |
| step-1-building | Step 1 current | Hero counter + progress bar + discovery feed | None (Continue disabled) |
| step-1-complete | Step 1 complete | Hero counter at final value, progress bar at 100%, feed scrollable | Continue |
| step-2-idle | Steps 1 complete, 2 current | Step 2 title, description, Generate/Write choice | Generate, Write from scratch |
| step-2-generating | Step 2 current | Left pane shimmer, right pane empty | None (waiting for generation) |
| step-2-editing | Step 2 current | Split pane: generated left, editable right | Regenerate, Skip, Commit Vision |
| step-2-committed | Steps 1-2 complete | Confirmation message | Continue |
| step-3-idle | Steps 1-2 complete, 3 current | "Extracting conventions..." spinner | None (waiting for extraction) |
| step-3-reviewing | Step 3 current | Convention list + persona inputs | Accept, Reject, Accept All, Skip, Commit |
| step-3-committed | Steps 1-3 complete | Confirmation message | Continue |
| complete | Steps 1-3 complete, 4 current | Checkmark + stats + CTA | Start defining |

### VisionDraftEditor States

| State | Left Pane | Right Pane | Actions |
|-------|-----------|------------|---------|
| generating | Shimmer animation overlay | Empty, non-interactive | None |
| ready | Generated text, read-only | Copy of generated text, `contenteditable` | Regenerate, Commit Vision |
| regenerating | Shimmer animation, previous text visible beneath | Author's edits preserved, still editable | None on left; right remains editable |
| write-from-scratch | Hidden (pane absent) | Empty, `contenteditable`, full width | Commit Vision |

### ConventionReview States

Each convention row has an independent state:

| Row State | Visual Treatment | Toggle Buttons |
|-----------|-----------------|----------------|
| pending | Full opacity, neutral background | Both icons `--color-text-tertiary` |
| accepted | Full opacity | Accept icon active (emerald), reject icon dimmed |
| rejected | 40% opacity | Reject icon active (red), accept icon dimmed |


## Spacing

All values on the 4px grid.

| Context | Value | Usage |
|---------|-------|-------|
| Wizard card padding | 24px | Internal padding for the `.surface` wizard container |
| Step indicator margin-bottom | 28px | Gap below step indicator bar before active panel |
| Step title margin-bottom | 4px | Between step title and step description |
| Step description margin-bottom | 20px | Between description and step content |
| Step actions margin-top | 20px | Between step content and action buttons |
| Step actions gap | 8px | Between adjacent action buttons |
| Progress bar margin-bottom | 20px | Between progress track and discovery feed |
| Discovery feed max-height | 180px | Scrollable overflow boundary |
| Discovery feed item padding | 6px 0 | Vertical padding per feed row |
| Discovery feed item gap | 8px | Between icon, path, and tag within a row |
| Vision split pane gap | 1px | Divider width between left and right panes |
| Vision pane padding | 20px | Internal padding per pane |
| Vision pane header margin-bottom | 12px | Between pane label and content |
| Convention row padding | 10px 16px | Per-convention row |
| Convention row gap | 12px | Between content, source badge, confidence, and toggles |
| Convention list border-radius | 8px | Container rounding |
| Persona section margin-top | 16px | Between convention list and persona inputs |
| Persona label margin-bottom | 8px | Between label and input |
| Persona input padding | 12px 14px | Internal padding |
| Persona input min-height | 64px | Minimum height for textarea |
| Complete section padding | 20px 0 | Vertical padding for complete step content |
| Complete checkmark margin-bottom | 20px | Below checkmark circle |
| Complete subtitle margin-bottom | 24px | Between subtitle and stats grid |
| Stats grid gap | 16px | Between stat cards |
| Stats card padding | 16px | Internal padding per stat card |
| Stats grid margin-bottom | 28px | Between stats and CTA button |


## Typography

| Element | Role | Family | Size | Weight | Line-Height | Color |
|---------|------|--------|------|--------|-------------|-------|
| Step title | `type-section-title` | `--font-sans` | 15px | 600 | 1.4 | `--color-text` |
| Step description | `type-body` | `--font-sans` | 13px | 400 | 1.5 | `--color-text-secondary` |
| Graph hero counter | custom | `--font-mono` | 36px | 600 | 1 | `--color-text` |
| Graph hero unit | custom | `--font-mono` | 13px | 400 | 1 | `--color-text-secondary` |
| Progress percentage | `type-mono-value` | `--font-mono` | 13px | 500 | 1.4 | `--color-text-secondary` |
| Discovery feed path | custom | `--font-mono` | 11px | 400 | 1.5 | `--color-text-secondary` |
| Discovery feed tag | custom | `--font-mono` | 9px | 500 | 1 | Per-tag color (see Step 1 table) |
| Vision pane label | `type-badge` | `--font-mono` | 11px | 500 | 1 | `--color-text-tertiary` (left), `--color-text` (right) |
| Vision draft content | `type-body` | `--font-sans` | 13px | 400 | 1.6 | `--color-text-secondary` |
| Convention text | `type-body` | `--font-sans` | 13px | 400 | 1.4 | `--color-text-secondary` |
| Convention source badge | custom | `--font-mono` | 9px | 500 | 1 | Per-source color (see Step 3 table) |
| Convention confidence | custom | `--font-mono` | 10px | 500 | 1 | Per-confidence color (see Step 3 table) |
| Persona label | custom | `--font-mono` | 11px | 500 | 1 | `--color-text-tertiary` |
| Persona input text | `type-body` | `--font-sans` | 13px | 400 | 1.5 | `--color-text` |
| Persona placeholder | `type-body` | `--font-sans` | 13px | 400 | 1.5 | `--color-text-tertiary` |
| Complete title | custom | `--font-sans` | 17px | 600 | 1.4 | `--color-text` |
| Complete subtitle | `type-body` | `--font-sans` | 13px | 400 | 1.5 | `--color-text-secondary` |
| Stat value | custom | `--font-mono` | 24px | 600 | 1 | `--color-text` |
| Stat label | `type-caption` | `--font-sans` | 11px | 500 | 1.4 | `--color-text-tertiary` |
| CTA button label | custom | `--font-sans` | 14px | 600 | 1 | `--color-bg` (on accent) |
| Step indicator label | custom | `--font-sans` | 11px | 500 | 1 | Per-state color (see Step Indicator table) |
| Step indicator number | custom | `--font-mono` | 11px | 600 | 1 | Per-state color |
| Accept All button | custom | `--font-mono` | 10px | 500 | 1 | `--color-accent` |


## Color Application

| Element | Property | Token | Notes |
|---------|----------|-------|-------|
| Wizard card background | background | `--color-bg-card` | `.surface` class |
| Wizard card border | border | `--color-border` | Part of `.surface` |
| Step indicator: complete circle | background | `--color-accent` | |
| Step indicator: complete checkmark | color | `--color-bg` | Dark checkmark on accent circle |
| Step indicator: complete label | color | `--color-accent` | |
| Step indicator: current circle bg | background | `--color-bg-card-hover` | |
| Step indicator: current circle border | border | `--color-text` | 1.5px |
| Step indicator: current number | color | `--color-text` | |
| Step indicator: current label | color | `--color-text` | |
| Step indicator: pending circle border | border | `--color-text-tertiary` | 1.5px |
| Step indicator: pending number | color | `--color-text-tertiary` | |
| Step indicator: pending label | color | `--color-text-tertiary` | |
| Step connector: completed | background (pseudo) | `--color-accent` | Animated fill |
| Step connector: pending | background | `--color-border` | |
| Progress bar track | background | `--color-bg-elevated` | |
| Progress bar fill | background | `--color-accent` | With glow shadow |
| Discovery feed icon: indexed | color | `--color-accent` | |
| Discovery feed icon: skipped | color | `--color-text-tertiary` | |
| Discovery feed row border | border-bottom | `--color-border-light` | |
| Vision left pane background | background | `--color-bg-elevated` | Read-only pane |
| Vision right pane background | background | `--color-bg-card` | Editable pane |
| Vision pane divider | background | `--color-border` | 1px vertical |
| Regenerate link | color | `--color-accent` | |
| Shimmer gradient center | — | `rgba(0, 212, 170, 0.15)` | Matches accent at low opacity |
| Convention row background | background | `--color-bg-elevated` | |
| Convention row border | border-bottom | `--color-border-light` | |
| Convention row hover | background | `--color-bg-card-hover` | |
| Convention accept active | color, bg | `--color-emerald`, `rgba(68, 204, 119, 0.12)` | |
| Convention reject active | color, bg | `--color-red`, `rgba(239, 68, 100, 0.12)` | |
| Accept All button bg | background | `--color-accent-dim` | Hover: `--color-accent-glow` |
| Persona input border | border | `--color-border` | Focus: `rgba(0, 212, 170, 0.3)` |
| Persona input background | background | `--color-bg-elevated` | |
| Complete checkmark circle | background | `--color-accent-dim` | |
| Complete checkmark icon | color | `--color-accent` | |
| Stat card background | background | `--color-bg-elevated` | |
| Stat card border | border | `--color-border-light` | |
| Primary button | background, color | `--color-accent`, `--color-bg` | |
| Primary button disabled | background | `--color-text-tertiary` | 50% opacity |
| Secondary button | background, color, border | transparent, `--color-text-secondary`, `--color-border` | |
| Secondary button hover | background, color, border | `--color-bg-card-hover`, `--color-text`, `rgba(255,255,255,0.12)` | |
| Error text | color | `--color-red` | Build failures, validation errors |


## Elevation & Depth

| Element | Elevation Level | Treatment |
|---------|----------------|-----------|
| `/define/new` page background | 0 (base) | Flat, `--color-bg` |
| Wizard card | 2 | `.surface` class |
| Discovery feed container | 0 (inset) | Flat within wizard card |
| Vision split pane container | 0 (inset) | Border-radius 8px container within wizard card |
| Vision left pane | 1 | `--color-bg-elevated` background |
| Vision right pane | 2 | `--color-bg-card` background |
| Convention list container | 0 (inset) | Border-radius 8px container within wizard card |
| Convention rows | 1 | `--color-bg-elevated` background |
| Persona inputs | 1 | `--color-bg-elevated` background with border |
| Stat cards | 1 | `--color-bg-elevated` with `--color-border-light` |


## Data Binding

| Element | Source | Format | Constraints |
|---------|-------|--------|-------------|
| Cold start detection | `bootstrapStatus` query | `{ needed, reasons[], graphBuildStatus }` | All three conditions true: no graph, no vision, no knowledge |
| Graph build progress | `bootstrapStatus.graphBuildStatus` | `"not_started"` \| `"building"` \| `"complete"` \| `"error"` | Polled via `bootstrapStatus` query at 500ms interval |
| Graph file count | `startGraphBuild` mutation response | number | Updates via polling during build |
| Vision draft | `visionDraft` query | `{ content, sources[], generatedAt }` | Null before generation triggered |
| Vision generating | `generateVision` mutation state | boolean | True during LLM generation |
| Vision commit | `commitVision(content)` mutation | `{ path, written }` | Content min 50 chars, at least 3 non-heading lines |
| Derived conventions | `derivedConventions` query | `DerivedConvention[]` | Available after `extractConventions` mutation completes |
| Convention resolution | `resolveConvention(id, action)` mutation | `DerivedConvention` | `action`: ACCEPT or REJECT |
| Bulk accept | `acceptAllConventions` mutation | `DerivedConvention[]` | Returns updated list |
| Persona inputs | `commitConventions(personaInputs)` mutation | `CommitConventionsResult` | All fields optional. Written with `confidence: "locked"`. |
| Bootstrap completion | `completeBootstrap` mutation | `BootstrapResult` | Requires vision committed. Conventions optional. |

### GraphQL Operations

```graphql
# Check if bootstrap needed (polled during build)
query BootstrapStatus {
  bootstrapStatus {
    needed
    reasons
    graphBuildStatus
    steps { id title status }
  }
}

# Step 1
mutation StartGraphBuild { startGraphBuild { status } }

# Step 2
mutation GenerateVision { generateVision { content sources generatedAt } }
mutation RegenerateVision { regenerateVision { content sources generatedAt } }
mutation CommitVision($content: String!) {
  commitVision(content: $content) { path written }
}

# Step 3
mutation ExtractConventions { extractConventions { id text source category status } }
mutation ResolveConvention($id: String!, $action: ConventionAction!) {
  resolveConvention(id: $id, action: $action) { id status }
}
mutation AcceptAllConventions { acceptAllConventions { id status } }
mutation CommitConventions($personaInputs: PersonaConventionInput) {
  commitConventions(personaInputs: $personaInputs) { written count }
}

# Step 4
mutation CompleteBootstrap { completeBootstrap { success } }
```


## Interactions & Motion

### Interactions

| Trigger | Target | Response | Notes |
|---------|--------|----------|-------|
| Page load at `/define/new` | BootstrapWizard | Query `bootstrapStatus`. If `needed=true`, render wizard. If `needed=false`, render IntentInput. | Detecting state shown during query. |
| Click "Build Graph" | Step 1 | `startGraphBuild` mutation fires. Hero counter begins incrementing. Progress bar fills. Discovery feed populates. | Continue button remains disabled until complete. |
| Click Continue (step 1) | Step 1 → Step 2 | Current step panel fades out (200ms). Step 1 indicator transitions to complete (accent fill). Step 2 panel fades in (200ms). | |
| Click "Generate from codebase" | Step 2 | `generateVision` mutation fires. Left pane shows shimmer. On completion, both panes populate. | Right pane receives a copy of the generated text. |
| Click "Write from scratch" | Step 2 | Left pane hidden. Right pane renders full-width, empty, with cursor focus. | No LLM call. |
| Click "Regenerate" | VisionDraftEditor | `regenerateVision` mutation fires. Left pane shows shimmer over previous text. Right pane edits are preserved. | Author can compare new generation against their edits. |
| Click "Commit Vision" | Step 2 | `commitVision` fires with right pane content. On success, step 2 completes. | Disabled when content is empty or < 50 chars. |
| Click Continue (step 2) | Step 2 → Step 3 | Panel transition. `extractConventions` fires automatically. Spinner shown during extraction. | Convention list appears when extraction completes. |
| Click accept toggle | ConventionReview row | Row state changes to accepted. `resolveConvention(id, ACCEPT)` fires. | Toggleable: clicking again reverts to pending. |
| Click reject toggle | ConventionReview row | Row dims to 40% opacity. `resolveConvention(id, REJECT)` fires. | Toggleable: clicking again reverts to pending. |
| Click "Accept All" | ConventionReview | All pending rows transition to accepted. `acceptAllConventions` fires. | Already-accepted rows unaffected. Rejected rows unaffected. |
| Click "Commit" (step 3) | Step 3 | `commitConventions` fires with persona inputs. On success, step 3 completes. | |
| Click "Skip" (step 2/3) | Current step | Step marked skipped (indicator in `--color-text-tertiary`). Advances to next step. | Vision skip: author must commit vision before "Complete". |
| Click "Start defining" | Step 4 | `completeBootstrap` fires. On success, navigates to `/define/new` (IntentInput card). | Blocked if vision was skipped and never committed. |

### Motion

| Name | Duration | Easing | Property | Usage |
|------|----------|--------|----------|-------|
| step-transition | 200ms | ease-out | opacity, transform (translateY 6px) | Panel content fade in/out between steps |
| progress-fill | 300ms | ease | width | Progress bar fill during graph build |
| connector-fill | 400ms | ease | width (pseudo-element) | Step connector accent fill on step completion |
| feed-item-enter | 300ms | ease | opacity, transform (translateX -8px → 0) | Discovery feed items stagger in |
| shimmer-sweep | 2500ms | linear (infinite) | left position | Vision regeneration shimmer gradient |
| convention-resolve | 150ms | ease | opacity, background | Convention row accept/reject state change |
| check-pop | 400ms | cubic-bezier(0.34, 1.56, 0.64, 1) | transform (scale 0 → 1), opacity | Complete step checkmark entrance |
| state-change | 150ms | ease-out | background, border-color, color, opacity | Hover/focus transitions on all interactive elements |

**Reduced motion policy:** Replace all animations with instant state changes. `step-transition` becomes instant show/hide. `feed-item-enter` items appear immediately without slide. `shimmer-sweep` is disabled (left pane shows a static "Generating..." label instead). `check-pop` appears at full scale immediately. `progress-fill` and `connector-fill` jump to final position.


## Responsive Behavior

| Breakpoint | Layout | Behavior |
|------------|--------|----------|
| < 1024px | Not supported | Message: "Bootstrap setup requires a wider viewport." Link to portfolio mode (`/define`). |
| 1024-1280px | Wizard card at max 560px | Discovery feed max-height reduced to 120px. Vision panes stack vertically (generated above, editable below). |
| 1280px+ | Wizard card at max 640px | Full layout as described. Vision panes side-by-side. |


## Accessibility

### Keyboard Navigation

| Component | Keys | Behavior |
|-----------|------|----------|
| BootstrapWizard | Tab | Move between step controls and action buttons |
| Step actions | Enter/Space | Activate focused button |
| ConventionReview row | Tab | Move focus between rows |
| ConventionReview accept/reject | Enter/Space | Toggle accept/reject on focused convention |
| ConventionReview | Shift+A | Accept all conventions (keyboard shortcut for Accept All button) |
| VisionDraftEditor | Tab | Move focus between left pane, right pane, and action buttons |
| VisionDraftEditor right pane | Standard text editing | `contenteditable` text editing |
| Persona input | Tab | Move between persona fields |
| CTA buttons | Enter | Activate (Continue, Commit Vision, Commit, Start defining) |

### ARIA & Screen Reader

| Component | Role | ARIA | Announcement |
|-----------|------|------|--------------|
| BootstrapWizard | `navigation` | `aria-label="Bootstrap setup"` | "Step {n} of 4: {stepTitle}" announced on step change |
| Step indicator (active) | `listitem` | `aria-current="step"` | Active step identified |
| Progress bar | `progressbar` | `aria-valuenow={percent}`, `aria-valuemin="0"`, `aria-valuemax="100"`, `aria-label="Graph build progress"` | "{percent}% complete" announced on significant changes (every 25%) |
| Discovery feed | `log` | `aria-live="polite"`, `aria-label="File indexing activity"` | New items announced as they appear |
| VisionDraftEditor left pane | `region` | `aria-label="Generated vision draft (read-only)"` | |
| VisionDraftEditor right pane | `region` | `aria-label="Your vision (editable)"` | |
| ConventionReview list | `list` | `aria-label="Derived conventions"` | |
| ConventionReview item | `listitem` | `aria-label="{convention text}"` | |
| Accept toggle | `button` | `aria-pressed={accepted}`, `aria-label="Accept convention"` | "Convention accepted" / "Convention acceptance removed" |
| Reject toggle | `button` | `aria-pressed={rejected}`, `aria-label="Reject convention"` | "Convention rejected" / "Convention rejection removed" |
| Accept All | `button` | `aria-label="Accept all pending conventions"` | "{count} conventions accepted" |
| Persona input | `textbox` | `aria-label="{category} conventions"` | |
| Complete checkmark | `img` | `aria-label="Bootstrap complete"` | "Project bootstrapped successfully" |

### Contrast & Targets

All color tokens are defined in `globals.css` with contrast ratios documented:
- `--color-text` (#e4e4e9) against `--color-bg-card` (#1c1c27): ~13:1
- `--color-text-secondary` (#9494a3) against `--color-bg-card`: ~5.5:1
- `--color-text-tertiary` (#55556a): decorative only, not used for actionable content
- `--color-accent` (#00d4aa) against `--color-bg` (#0c0c10): ~9.5:1

All interactive targets meet 44x44px minimum: action buttons exceed this via padding. Convention row toggle buttons (26x26px) use the full row as an extended click target. Step indicator circles (22px) use a 44px invisible hit area.


## Content Constraints

| Element | Min | Max | Overflow | Placeholder |
|---------|-----|-----|----------|-------------|
| Vision content | 50 chars | No limit | Right pane scrolls | — |
| Convention text | — | 200 chars | Truncate with ellipsis | — |
| Persona input | 0 (optional) | No limit | Textarea grows vertically | Category-specific example text |
| Discovery feed path | — | — | Truncate with ellipsis, keep filename | — |
| Stat values | 0 | — | — | "0" if nothing produced |
| Graph hero counter | 0 | — | Tabular-nums for stable width | "0" while waiting |


## Implementation Notes

- The wizard renders in place of the IntentInput card on `/define/new`. Cold start detection runs on page load via the `bootstrapStatus` query. If `needed` is false, the IntentInput card renders normally. If true, `BootstrapWizard` renders. The switch is a conditional render in `page.tsx`, not a route change.
- Graph build runs as a subprocess (see [tech RFC](../tech/speed-define-ceremony-bootstrap.md#mutations)). The frontend polls `bootstrapStatus` at 500ms to update the progress bar and file count. Polling stops when `graphBuildStatus` reaches `"complete"` or `"error"`.
- The step indicator bar uses a flex layout. Each step segment contains a circle and label. Connectors between segments use `flex: 1` with a pseudo-element for the accent fill. The fill width transitions from 0% to 100% on step completion.
- Vision generation timeout is 60 seconds (server-side). If the timeout fires, the frontend receives a partial draft or an error. Partial drafts populate the left pane with a "Generation timed out" warning below.
- Convention extraction runs the same Learn pipeline extractors used post-feature (A1 through A4). On large codebases, extraction can take 30 to 60 seconds. The wizard shows a spinner during this period without blocking other interactions.
- The persona input fields use standard `<textarea>` elements, not `contenteditable`. Resize is `vertical` only. Empty arrays are valid submissions.


## Verification Criteria

### Cold Start Detection
- [ ] `bootstrapStatus.needed` returns true only when all three conditions are met (no graph, no vision, no knowledge)
- [ ] Wizard renders in place of IntentInput when `needed` is true
- [ ] IntentInput renders normally when `needed` is false

### Step Indicator
- [ ] Four numbered circles connected by 1px lines
- [ ] Complete steps: `--color-accent` background, `--color-bg` checkmark, number hidden
- [ ] Current step: `--color-bg-card-hover` background, `--color-text` border and number
- [ ] Pending steps: transparent background, `--color-text-tertiary` border and number
- [ ] Connectors fill with `--color-accent` on step completion (400ms ease)
- [ ] Active step has `aria-current="step"`

### Step 1: Graph Build
- [ ] Hero counter uses `--font-mono` 36px 600 with `tabular-nums`
- [ ] Progress bar: 4px track in `--color-bg-elevated`, fill in `--color-accent` with glow
- [ ] Discovery feed items stagger in with 300ms slide animation
- [ ] Feed tags use correct color mapping: indexed=accent, parsed=blue, skipped=text-3
- [ ] Continue button disabled during build, enabled on completion
- [ ] Build error shows `--color-red` message with "Retry" link in `--color-accent`

### Step 2: Vision
- [ ] Two-button choice: accent primary (Generate) and secondary outline (Write from scratch)
- [ ] Split pane: left `--color-bg-elevated` read-only, right `--color-bg-card` editable
- [ ] Pane labels: `--font-mono` 11px 500 uppercase
- [ ] Regenerate triggers shimmer on left pane only; right pane edits preserved
- [ ] "Write from scratch" hides left pane; right pane renders full-width
- [ ] Commit Vision disabled when content < 50 chars

### Step 3: Conventions
- [ ] Convention rows: `--color-bg-elevated`, 10px 16px padding, `--color-border-light` separator
- [ ] Source badges: inferred=violet, explicit=blue, detected=amber
- [ ] Confidence tags: high=emerald, mid=amber, low=text-3
- [ ] Accept toggle: emerald on active; reject toggle: red on active
- [ ] Accepted rows full opacity; rejected rows 40% opacity
- [ ] Accept All button uses `--font-mono` 10px uppercase, `--color-accent` on `--color-accent-dim`
- [ ] Persona inputs: `--color-bg-elevated` background, border changes to `rgba(0, 212, 170, 0.3)` on focus

### Step 4: Complete
- [ ] Checkmark circle: 56px, `--color-accent-dim` background, scale-pop animation (400ms spring)
- [ ] Stats grid: three equal columns, `--font-mono` 24px 600 values, 11px 500 labels
- [ ] "Start defining" button navigates to `/define/new` (normal IntentInput flow)
- [ ] Bootstrap blocked if vision was never committed

### General
- [ ] Token audit passes with zero hardcoded color/spacing/font values outside of `globals.css`
- [ ] All interactive targets meet 44x44px minimum (convention toggles use row as extended target)
- [ ] Reduced motion: all animations replaced with instant transitions
- [ ] Viewport < 1024px shows fallback message with link to portfolio mode
- [ ] Vision panes stack vertically at 1024-1280px


## Figma / Visual Reference

No Figma file exists for this feature. The prototype at `working-docs/bootstrap-wizard-prototype.html` serves as the visual reference. It is a self-contained HTML file with all design tokens, interactive states, and step switching for all four wizard steps.
