# Design: Define Ceremony — Commit & Ratification

> See [product spec](../product/speed-define-ceremony.md) for product context (stories S5, S9).
> See [tech RFC](../tech/speed-define-ceremony-commit.md) for API surface, data model, and state machine.
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
  Five components across two flows: the author's commit flow
  (CommitBar, CommitDialog) within the ceremony editor
  (/define/:feature), and the reviewer's ratification flow
  (RatificationView, RatificationSummary, RatificationControls) on
  a dedicated route (/define/:feature/review). Single-player mode
  auto-ratifies on commit. Everything else (editor, validation,
  suggestions, context, bootstrap) belongs to sibling design specs.
-->


## Design Intent

> See [design principles](../../working-docs/define-ceremony-design-principles.md) for the 8 principles governing all ceremony surfaces.

**Direction:** The commit flow is a checkpoint, not a celebration. The author confirms readiness; the system shows what will be locked in. Validation state, suggestion resolution, and content hash form the evidence trail. Once the author commits, the spec is frozen and the record is permanent.

Ratification is the reviewer's workspace: evidence-dense and decision-oriented. The approval counter is the hero metric, set in large mono type so the reviewer immediately reads where the spec stands. Verdicts are permanent and attributed. Each vote appears as a timestamped line item, building an audit trail the team can revisit.

**Do not:** Apply accent color to the approval counter before threshold is met (accent is earned at completion). Use emerald for anything other than the Approve action and approved verdicts. Show decorative empty-state artwork on the ratification view. Add borders without paired shadows on elevated elements. Animate the commit action itself (only animate feedback after the action completes). Use pure white (`#fff`) anywhere.


## Scope

Five components, two flows:

| Flow | Mode | Route | Components |
|------|------|-------|------------|
| Commit | SP + MP | `/define/:feature` (bottom of editor-area) | CommitBar, CommitDialog |
| Ratification | MP only | `/define/:feature/review` | RatificationView, RatificationSummary, RatificationControls |

Single-player commit auto-ratifies: no ratification route, no reviewer flow. The commit mutation returns `planUnblocked = true` and the CommitBar shows post-commit success messaging inline.

Multiplayer commit transitions the ceremony to `approving` state and emits a `spec.proposed` event. Reviewers access the ratification route, where they see the frozen spec alongside evidence and vote controls.


## Layout Structure

### CommitBar Layout

CommitBar is a 52px fixed bar at the bottom of the editor-area region. It sits below the validation gutter.

```
┌─────────────────────────────────────────────────────────────────┐
│  ✓ 4 pass   ⚠ 1 warn   │  4 resolved, 0 pending    [ Commit ] │
│                          │                                      │
│  validation summary      │  suggestion summary     primary btn  │
└─────────────────────────────────────────────────────────────────┘
  52px height · bg: --color-bg-card · border-top: 1px --color-border
  shadow: 0 -2px 8px rgba(0,0,0,0.3)
```

Left region: validation stats as compact badges (mono 11px 500). Pass count in `--color-emerald`, warn count in `--color-amber`, fail count in `--color-red`. A 1px vertical separator (`--color-border`, 20px tall) divides validation from suggestions.

Right of separator: suggestion summary ("N resolved, N pending") in 12px 500 `--color-text-secondary`. When unresolved suggestions exist, the pending count renders in `--color-amber`.

Far right: the Commit button. In multiplayer mode the label reads "Commit & Propose".

When the spec fails template conformance, the button is disabled and a blocker message appears to its left: "Template conformance required" in 11px 500 `--color-red`.

### CommitDialog Layout

Modal overlay with centered card, max 480px width.

```
┌───────────────────────────────────────────┐
│  Commit spec                              │
│  sort-auth-by-last-activity               │
│                                           │
│  ✓  Template         All sections present │
│  ✓  Structure        Stories have IDs     │
│  ✓  Codebase         Refs match artifacts │
│  ✓  Sizing           Scope is appropriate │
│  ⚠  Vision           Vision is stale      │
│                                           │
│  ┌───────────────────────────────────────┐ │
│  │ Optional commit note...              │ │
│  └───────────────────────────────────────┘ │
│                                           │
│  ⚠ 0 unresolved suggestions              │
│                                           │
│                     [ Cancel ] [ Confirm ] │
└───────────────────────────────────────────┘
  max-width: 480px · padding: 24px · .surface class
  overlay: rgba(0,0,0,0.6)
```

Title: "Commit spec" (15px 600 `--color-text`). Feature name below in mono 12px 500 `--color-text-secondary`. A dimension-by-dimension checklist follows, each row showing a status icon + dimension name + summary text (13px 400 `--color-text-secondary`). Status icons use the standard validation colors: emerald for pass, amber for warn, red for fail.

Below the checklist, an optional commit note textarea (`--color-bg-elevated` background, `--color-border` border, 8px radius). Below that, an unresolved suggestion count. If > 0, the count uses `--color-amber` as a warning (not a blocker).

Action row: Cancel (ghost button, `--color-text-secondary`) right-aligned with Confirm (accent primary button). In multiplayer mode, the confirm label reads "Commit & Propose".

### RatificationView Layout

Two-panel layout on `/define/:feature/review`. The read-only spec occupies the left (fluid width); the evidence panel occupies the right (320px fixed).

```
┌─────────────────────────────────────────────────────────────────┐
│  RATIFICATION BANNER (hidden until resolved)                    │
├────────────────────────────────────────────┬────────────────────┤
│                                            │                    │
│  🔒 READ-ONLY SPEC                        │  1 / 2             │
│                                            │  APPROVALS         │
│  ## Sort Auth by Last Activity             │                    │
│                                            │  ────────          │
│  ### Problem                               │                    │
│  Appwrite's Users list endpoint...         │  COMMIT INFO       │
│                                            │  Author   Jane     │
│  ### User Stories                          │  Date     Mar 15   │
│  S1  Sort by activity...                   │  Hash     a3f2...  │
│                                            │                    │
│  ### Scope                                 │  ────────          │
│  accessedAt in Users.php...                │                    │
│                                            │  VALIDATION        │
│                                            │  ✓ Template        │
│                                            │  ✓ Structure       │
│                                            │  ⚠ Vision          │
│                                            │                    │
│                                            │  ────────          │
│                                            │                    │
│                                            │  SUGGESTIONS       │
│                                            │  4 received        │
│                                            │  3 accepted        │
│                                            │  1 dismissed       │
│                                            │  └ show reasons    │
│                                            │                    │
│                                            │  ────────          │
│                                            │                    │
│                                            │  VERDICTS          │
│                                            │  ● Alex  approved  │
│                                            │    2 min ago       │
│                                            │                    │
│                                            │  ────────          │
│                                            │                    │
│                                            │ [Approve] [Reject] │
│                                            │                    │
├────────────────────────────────────────────┴────────────────────┤
└─────────────────────────────────────────────────────────────────┘
  Left: flex 1, overflow-y auto, padding 20px
  Right: 320px fixed, border-left 1px --color-border, padding 20px
```

Left panel: the committed spec rendered read-only. A "READ-ONLY SPEC" label (mono 11px 500 uppercase, `--color-text-tertiary`, letter-spacing 0.04em) with a lock icon (14px) sits at the top. The spec content uses the same rendering as the editor (h2 at 15px 600, h3 at 13px 600, body at 13px 400 `--color-text-secondary`).

Right panel: RatificationSummary at top, RatificationControls pinned to bottom via `margin-top: auto`. The approval counter is the first element in the right panel, acting as the hero metric.

Ratification banner: a full-width bar that slides down from the top when the ceremony reaches a terminal state. Ratified: emerald background at 12% opacity, emerald text, emerald bottom border at 20% opacity. Rejected: red at the same pattern.


## Component Inventory

All components referenced here are defined in the [parent design spec](speed-define-ceremony.md#component-inventory). Component files live in `dashboard/frontend/components/define/ceremony/`.

| Component ID | Type | Location | Parent Region | Role |
|--------------|------|----------|---------------|------|
| CommitBar | new | `ceremony/CommitBar.tsx` | editor-area (bottom) | Validation summary + suggestion summary + Commit button. Fixed 52px bar. |
| CommitDialog | new | `ceremony/CommitDialog.tsx` | modal overlay | Confirmation modal with dimension checklist, optional note, unresolved warnings. |
| RatificationView | new | `ceremony/RatificationView.tsx` | content area | Page layout for `/define/:feature/review`. Two-panel: read-only spec left, evidence right. |
| RatificationSummary | new | `ceremony/RatificationSummary.tsx` | RatificationView (right panel) | Approval counter, commit metadata, validation snapshot, suggestion history, verdict log. |
| RatificationControls | new | `ceremony/RatificationControls.tsx` | RatificationView (right panel, bottom) | Approve/Reject buttons with inline rejection comment. |

### Component Props

#### CommitBar

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| validationSummary | `ValidationSummary` | required | Pass/warn/fail counts per dimension |
| unresolvedCount | `number` | `0` | Unresolved suggestion count |
| templateConformant | `boolean` | required | Whether spec passes template check. Controls button enabled/disabled. |
| onCommit | `() => void` | required | Opens CommitDialog |
| isMultiplayer | `boolean` | `false` | "Commit & Propose" label in MP, "Commit" in SP |
| isCommitting | `boolean` | `false` | Loading state: spinner replaces button label |

#### CommitDialog

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| open | `boolean` | `false` | Controls modal visibility |
| featureName | `string` | required | Shown below title in mono |
| dimensions | `ValidationDimension[]` | required | Per-dimension status for the checklist |
| unresolvedSuggestions | `Suggestion[]` | `[]` | Listed as warnings in the dialog body |
| isMultiplayer | `boolean` | `false` | Changes confirm label and post-commit messaging |
| onConfirm | `(note?: string) => void` | required | Fires the `commitSpec` mutation |
| onCancel | `() => void` | required | Closes dialog |
| isCommitting | `boolean` | `false` | Spinner on confirm button during mutation |
| error | `string \| null` | `null` | Error message from failed mutation, shown below actions |

#### RatificationView

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| feature | `string` | required | Feature name |
| spec | `SpecDraft` | required | Committed spec content (read-only) |
| contextPackage | `ContextPackage` | required | Context snapshot from commitment time |
| commitment | `CommitRecord` | required | Author, timestamp, validation state, suggestion history |
| isAuthor | `boolean` | required | True if viewer is the spec author (disables controls) |

#### RatificationSummary

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| validationState | `ValidationState` | required | Frozen validation at commitment time |
| suggestionHistory | `SuggestionHistory` | required | `{ received, accepted, dismissed: { count, reasons[] } }` |
| contextSnapshotRef | `string` | required | Path to persisted `context-package.json` |
| approvalCount | `number` | `0` | Current number of approvals |
| approvalThreshold | `number` | `1` | Required approvals from `speed.toml` |
| verdicts | `Verdict[]` | `[]` | All submitted verdicts: `{ actor, verdict, comment?, timestamp }` |
| commitAuthor | `string` | required | Who committed the spec |
| committedAt | `string` | required | ISO 8601 timestamp |
| contentHash | `string` | required | SHA-256 hash of committed spec content |

#### RatificationControls

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| onApprove | `() => void` | required | Fires `submitRatification(verdict: APPROVE)` |
| onReject | `(comment?: string) => void` | required | Fires `submitRatification(verdict: REJECT)` |
| disabled | `boolean` | `false` | True when viewer is spec author |
| disabledReason | `string` | `""` | "You cannot ratify your own spec" |
| hasVoted | `boolean` | `false` | True if this actor already submitted a verdict |
| ownVerdict | `RatificationVerdict \| null` | `null` | The viewer's own verdict, if cast |
| approvalCount | `number` | `0` | Current approvals (shown alongside controls) |
| approvalThreshold | `number` | `1` | Required threshold |


## Spacing

All values on the 4px grid.

| Context | Token/Value | Usage |
|---------|-------------|-------|
| CommitBar height | 52px | Fixed bottom bar within editor-area |
| CommitBar padding | 0 20px | Horizontal padding, items centered vertically |
| CommitBar validation-to-separator gap | 12px | Between validation badges and the vertical separator |
| CommitBar separator dimensions | 1px wide, 20px tall | `--color-border` vertical divider |
| CommitBar suggestion-to-button gap | 16px | Between suggestion summary and Commit button |
| CommitDialog padding | 24px | Internal padding |
| CommitDialog max-width | 480px | Centered in viewport |
| CommitDialog title-to-feature gap | 4px | Between "Commit spec" and feature name |
| CommitDialog feature-to-checklist gap | 20px | Between feature name and first checklist row |
| CommitDialog checklist row padding | 8px 0 | Vertical padding per row |
| CommitDialog checklist icon-to-text gap | 10px | Between status icon and dimension label |
| CommitDialog note textarea margin-bottom | 16px | Below the textarea |
| CommitDialog actions gap | 8px | Between Cancel and Confirm buttons |
| RatificationView left padding | 20px | Read-only spec area |
| RatificationView right width | 320px | Evidence panel, fixed |
| RatificationView right padding | 20px | Internal padding |
| RatificationView right section gap | 16px | Between summary sections |
| Ratification approval counter margin-bottom | 4px | Below the N/M counter |
| Ratification section title margin-bottom | 8px | Below each section heading |
| Ratification meta row padding | 4px 0 | Per-row vertical padding |
| Ratification verdict entry padding | 8px 0 | Per-verdict vertical padding |
| Ratification verdict dot-to-text gap | 10px | Between colored dot and verdict info |
| Ratification buttons gap | 12px | Between Approve and Reject buttons |
| Ratification buttons padding-top | 16px | Above the button row |
| Rejection textarea min-height | 56px | Inline rejection comment |
| Rejection textarea margin-bottom | 8px | Below textarea, above submit row |
| Rejection submit row gap | 8px | Between Cancel and Reject Confirm |
| Ratification banner padding | 12px 20px | Full-width status banner |


## Typography

| Element | Role | Family | Size | Weight | Line-Height | Color |
|---------|------|--------|------|--------|-------------|-------|
| CommitBar validation stat | custom | `--font-mono` | 11px | 500 | 1 | Per-status color (emerald/amber/red) |
| CommitBar suggestion summary | custom | `--font-sans` | 12px | 500 | 1.4 | `--color-text-secondary` |
| CommitBar pending count (> 0) | custom | `--font-mono` | 13px | 500 | 1.4 | `--color-amber` |
| CommitBar blocker text | custom | `--font-sans` | 11px | 500 | 1 | `--color-red` |
| Commit button label | `type-badge` | `--font-sans` | 13px | 600 | 1 | `--color-bg` (on accent bg) |
| CommitDialog title | `type-section-title` | `--font-sans` | 15px | 600 | 1.4 | `--color-text` |
| CommitDialog feature name | custom | `--font-mono` | 12px | 500 | 1.4 | `--color-text-secondary` |
| CommitDialog checklist text | `type-body` | `--font-sans` | 13px | 400 | 1.5 | `--color-text-secondary` |
| CommitDialog checklist icon | — | — | 18px | — | — | Per-status color |
| CommitDialog note textarea | `type-body` | `--font-sans` | 13px | 400 | 1.5 | `--color-text` |
| CommitDialog note placeholder | `type-body` | `--font-sans` | 13px | 400 | 1.5 | `--color-text-tertiary` |
| CommitDialog button label | `type-badge` | `--font-sans` | 13px | 600 | 1 | `--color-bg` (confirm) / `--color-text-secondary` (cancel) |
| CommitDialog unresolved warning | `type-body` | `--font-sans` | 13px | 400 | 1.5 | `--color-amber` |
| CommitDialog error message | `type-body` | `--font-sans` | 13px | 400 | 1.5 | `--color-red` |
| Read-only spec label | custom | `--font-mono` | 11px | 500 | 1 | `--color-text-tertiary` |
| Read-only spec label letter-spacing | — | — | — | — | — | 0.04em, uppercase |
| Approval counter numerator | `type-kpi-value` | `--font-mono` | 28px | 600 | 1.1 | `--color-text` (below threshold) / `--color-accent` (met) |
| Approval counter separator + denominator | custom | `--font-mono` | 15px | 400 | 1.1 | `--color-text-tertiary` |
| Approval counter label | custom | `--font-sans` | 11px | 500 | 1.4 | `--color-text-secondary` |
| Approval counter label letter-spacing | — | — | — | — | — | 0.05em, uppercase |
| Ratification section title | `type-section-header` | `--font-sans` | 13px | 600 | 1.4 | `--color-text` |
| Commit metadata label | custom | `--font-sans` | 12px | 400 | 1.4 | `--color-text-tertiary` |
| Commit metadata value | custom | `--font-sans` | 12px | 400 | 1.4 | `--color-text-secondary` |
| Content hash value | custom | `--font-mono` | 11px | 500 | 1.4 | `--color-text-tertiary` |
| Suggestion summary stat value | `type-mono-value` | `--font-mono` | 13px | 500 | 1.4 | `--color-text` |
| Suggestion summary body | `type-body` | `--font-sans` | 13px | 400 | 1.6 | `--color-text-secondary` |
| Dismiss detail toggle | custom | `--font-sans` | 12px | 400 | 1.4 | `--color-text-tertiary` |
| Dismiss reason text | custom | `--font-sans` | 12px | 400 | 1.5 | `--color-text-tertiary` |
| Verdict actor name | `type-body` | `--font-sans` | 13px | 400 | 1.5 | `--color-text-secondary` |
| Verdict timestamp | `type-caption` | `--font-sans` | 11px | 400 | 1.4 | `--color-text-tertiary` |
| Approve button label | `type-badge` | `--font-sans` | 13px | 600 | 1 | `--color-bg` (on emerald bg) |
| Reject button label | `type-badge` | `--font-sans` | 13px | 600 | 1 | `--color-red` (outline style) |
| Rejection textarea | custom | `--font-sans` | 12px | 400 | 1.5 | `--color-text` |
| Rejection textarea placeholder | custom | `--font-sans` | 12px | 400 | 1.5 | `--color-text-tertiary` |
| Rejection confirm button | custom | `--font-sans` | 12px | 600 | 1 | `--color-bg` (on red bg) |
| Rejection cancel button | custom | `--font-sans` | 12px | 500 | 1 | `--color-text-secondary` |
| Ratification banner text | custom | `--font-sans` | 13px | 600 | 1 | `--color-emerald` (ratified) / `--color-red` (rejected) |
| Ratified banner text example | — | — | — | — | — | "Spec ratified. speed plan is now unblocked." |
| Rejected banner text example | — | — | — | — | — | "Spec rejected. Author must rework and re-commit." |
| SP post-commit inline message | `type-body` | `--font-sans` | 13px | 500 | 1.4 | `--color-emerald` |
| MP post-commit inline message | `type-body` | `--font-sans` | 13px | 500 | 1.4 | `--color-text-secondary` |


## Color Application

| Element | Property | Token | Notes |
|---------|----------|-------|-------|
| CommitBar background | background | `--color-bg-card` | Matches editor surface |
| CommitBar border-top | border | `--color-border` | 1px solid |
| CommitBar shadow | box-shadow | `0 -2px 8px rgba(0,0,0,0.3)` | Reads above editor content |
| CommitBar pass stat | color | `--color-emerald` | |
| CommitBar warn stat | color | `--color-amber` | |
| CommitBar fail stat | color | `--color-red` | |
| CommitBar separator | background | `--color-border` | Vertical 1px divider |
| Commit button (enabled) | background | `--color-accent` | Primary action |
| Commit button (disabled) | background | `--color-text-tertiary` | Template non-conformant |
| Commit button text | color | `--color-bg` | Dark text on accent bg |
| CommitDialog overlay | background | `rgba(0,0,0,0.6)` | Modal backdrop |
| CommitDialog card | `.surface` class | — | `--color-bg-card` + border + shadow |
| CommitDialog note bg | background | `--color-bg-elevated` | Recessed textarea |
| CommitDialog note border | border | `--color-border` | Focus: `--color-accent-glow` |
| CommitDialog cancel | color | `--color-text-secondary` | Ghost button, border `--color-border` |
| CommitDialog confirm | background | `--color-accent` | Primary action |
| Read-only spec label icon | color | `--color-text-tertiary` | Lock icon |
| Ratification left panel bg | background | `--color-bg-card` | Spec content area |
| Ratification right panel bg | background | `--color-bg-elevated` | Evidence panel, `.surface-elevated` |
| Ratification right border-left | border | `--color-border` | 1px vertical divider |
| Approval counter (below threshold) | color | `--color-text` | Numerator only |
| Approval counter (threshold met) | color | `--color-accent` | Numerator promotes to accent |
| Approval counter denominator | color | `--color-text-tertiary` | Always tertiary |
| Verdict dot (approve) | background | `--color-emerald` | 8px circle |
| Verdict dot (reject) | background | `--color-red` | 8px circle |
| Approve button bg | background | `--color-emerald` | Filled button |
| Approve button text | color | `--color-bg` | Dark on emerald |
| Reject button bg | background | transparent | Outline style |
| Reject button border | border | `--color-red` | 1px solid |
| Reject button text | color | `--color-red` | |
| Reject button hover bg | background | `rgba(239, 68, 100, 0.08)` | Subtle red tint |
| Rejection textarea border | border | `--color-red` | Active rejection state |
| Rejection textarea bg | background | `--color-bg-elevated` | |
| Ratification banner (ratified) bg | background | `rgba(68, 204, 119, 0.12)` | Emerald at 12% |
| Ratification banner (ratified) text | color | `--color-emerald` | |
| Ratification banner (ratified) border | border-bottom | `rgba(68, 204, 119, 0.2)` | |
| Ratification banner (rejected) bg | background | `rgba(239, 68, 100, 0.12)` | Red at 12% |
| Ratification banner (rejected) text | color | `--color-red` | |
| Ratification banner (rejected) border | border-bottom | `rgba(239, 68, 100, 0.2)` | |
| Dismiss reasons border-left | border | `--color-border` | 2px left border on expanded reasons |
| SP post-commit message | color | `--color-emerald` | "speed plan is now unblocked" |
| MP post-commit message | color | `--color-text-secondary` | "Proposed for ratification. Waiting for N approval(s)." |


## Elevation & Depth

| Element | Elevation Level | Treatment |
|---------|----------------|-----------|
| CommitBar | 3 | `.surface` class + stronger upward shadow. Fixed position, must read above editor scroll content. |
| CommitDialog overlay | — | `rgba(0,0,0,0.6)` backdrop, z-index 200 |
| CommitDialog card | 3 | `.surface` class + shadow-lg |
| Ratification left panel | 2 | `--color-bg-card` background |
| Ratification right panel | 1 | `.surface-elevated` class |
| Ratification banner | 2 | Sits above spec content, below right panel header |
| Approve/Reject buttons | 1 | `.surface-elevated` sits below summary in right panel |


## States

### CommitBar States

| State | Button | Left Summary | Right Summary | Trigger |
|-------|--------|-------------|--------------|---------|
| ready | Enabled: `--color-accent` bg, "Commit" / "Commit & Propose" label | Validation badges (pass/warn/fail counts) | "N resolved, 0 pending" | All validation dimensions checked, template conformant |
| blocked | Disabled: `--color-text-tertiary` bg, `cursor: not-allowed` | Validation badges (includes fail count) | Blocker text: "Template conformance required" in `--color-red`, 11px 500 | Template non-conformant |
| committing | Loading: spinner replaces label, button width locked, disabled | Unchanged | Unchanged | Author clicked Confirm in CommitDialog |
| committed-sp | Button replaced with inline message: "speed plan is now unblocked" in `--color-emerald` 13px 500 | Unchanged | Hidden | Single-player commit succeeds |
| committed-mp | Button replaced with inline message: "Proposed for ratification. Waiting for N approval(s)." in `--color-text-secondary` 13px 500 | Unchanged | Hidden | Multiplayer commit succeeds |

### CommitDialog States

| State | Confirm Button | Body | Trigger |
|-------|---------------|------|---------|
| open | Enabled, accent bg | Dimension checklist, optional note, unresolved count | Author clicks Commit on CommitBar |
| committing | Spinner replaces label, disabled | Unchanged | Author clicks Confirm |
| error | Re-enabled | Error message appears below actions in `--color-red` | Mutation returns error |

### RatificationView States

| State | Banner | Approval Counter | Controls | Condition |
|-------|--------|-----------------|----------|-----------|
| waiting | Hidden | `N / M` in `--color-text` (numerator), `--color-text-tertiary` (denominator) | Active (see RatificationControls states) | 0 < approvalCount < threshold |
| approved | Ratified banner visible (emerald), slides down | Numerator promotes to `--color-accent` | Replaced with "Spec ratified. speed plan is now unblocked." text + optional "Begin planning" accent button | approvalCount >= threshold |
| rejected | Rejected banner visible (red), slides down | Unchanged | Replaced with "Spec rejected. Author must rework and re-commit." text | Any verdict is REJECT |

### RatificationControls States

| State | Approve Button | Reject Button | Additional | Condition |
|-------|---------------|--------------|------------|-----------|
| active | Enabled: `--color-emerald` bg, "Approve" label | Enabled: transparent bg, `--color-red` border+text, "Reject" label | — | Viewer is not author, has not voted |
| voted-approve | Disabled, 50% opacity | Disabled, 50% opacity | Below buttons: "You approved this spec" + timestamp | Viewer already voted approve |
| voted-reject | Disabled, 50% opacity | Disabled, 50% opacity | Below buttons: "You rejected this spec" + timestamp | Viewer already voted reject |
| disabled-author | Both disabled, `--color-text-tertiary` bg, `cursor: not-allowed` | Same | Tooltip + text: "You cannot ratify your own spec" | isAuthor = true |

### Rejection Comment Flow

When the reviewer clicks Reject, an inline textarea slides open below the buttons:

1. Textarea appears (12px sans, `--color-text`, `--color-bg-elevated` bg, `--color-red` border, min-height 56px)
2. Placeholder: "Why are you rejecting this spec?"
3. Below the textarea: a "Cancel" ghost button and a "Reject" filled button (`--color-red` bg, `--color-bg` text, 12px 600)
4. Comment is optional but recommended. Max 500 chars.
5. On submit, the rejection verdict is recorded with the comment.


## Data Binding

| Element | Source | Format | Constraints |
|---------|--------|--------|-------------|
| CommitBar validation stats | `validation.summary` | `{ pass: number, warn: number, fail: number }` | Per-dimension counts rendered as compact badges |
| CommitBar suggestion summary | `suggestions.filter(s => s.status)` | Computed counts | "N resolved" = accepted + dismissed. "N pending" = unresolved. |
| CommitBar template conformant | `validation.dimensions.find(d => d.name === "template").status` | `"pass" \| "fail"` | Controls button enabled/disabled |
| CommitDialog dimensions | `validation.dimensions[]` | `{ name, status, issues[] }` | One row per dimension in checklist |
| CommitDialog unresolved list | `suggestions.filter(s => s.status === "unresolved")` | `Suggestion[]` | Section refs shown per unresolved item |
| CommitDialog multiplayer flag | `ceremony.isMultiplayer` | `boolean` | Changes confirm label |
| Ratification approval count | `ratificationState.ratificationCount` | `number` | Hero metric numerator |
| Ratification threshold | `ratificationState.threshold` | `number` | Denominator |
| Ratification verdicts | `ratificationState.verdicts[]` | `{ actor, verdict, comment?, timestamp }` | Rendered as verdict entries with colored dots |
| Ratification isAuthor | `ratificationState.isAuthor` | `boolean` | Disables controls |
| Ratification hasVoted | `ratificationState.hasVoted` | `boolean` | Disables controls after voting |
| Ratification validation state | `commitment.validationState` | `ValidationState` | Frozen at commit time |
| Ratification suggestion history | `commitment.suggestionHistory` | `{ received, accepted, dismissed: { count, reasons[] } }` | Stats shown in summary |
| Ratification context ref | `commitment.contextSnapshotRef` | `string` | Path to context-package.json |
| Commit metadata: author | `commitment.author` | `string` | Shown in metadata section |
| Commit metadata: date | `commitment.committedAt` | ISO 8601 | Formatted as relative time, full date in tooltip |
| Commit metadata: hash | `commitment.contentHash` | `string` | First 8 chars displayed in mono |
| Post-commit SP message | `commitResult.planUnblocked` | `boolean` | Shows success text when true |
| Post-commit MP message | `commitResult.planUnblocked` | `boolean` | Shows "waiting for N" when false |

### GraphQL Connections

| Component | Query/Mutation | Trigger |
|-----------|---------------|---------|
| CommitDialog confirm | `commitSpec(featureName)` mutation | Author clicks Confirm |
| RatificationView | `ratificationState(featureName)` query | Page load + poll every 5s |
| RatificationControls approve | `submitRatification(featureName, APPROVE)` mutation | Reviewer clicks Approve |
| RatificationControls reject | `submitRatification(featureName, REJECT, comment?)` mutation | Reviewer submits rejection |
| CommitBar post-commit | `commitRecord(featureName)` query | After commit mutation succeeds |


## Interactions & Motion

### Interactions

| Trigger | Target | Response | Notes |
|---------|--------|----------|-------|
| Click Commit button | CommitBar | Opens CommitDialog. Auto-runs all validation dimensions before dialog content renders. | Blocked (disabled) when template non-conformant. Keyboard: Cmd+Enter. |
| Click Confirm in dialog | CommitDialog | Spinner replaces label. `commitSpec` mutation fires. On success: dialog closes, CommitBar transitions to committed state. On error: spinner stops, error message appears below actions. | Confirm disabled during mutation. |
| Click Cancel in dialog | CommitDialog | Dialog closes. No state change. | Keyboard: Escape. |
| Press Escape | CommitDialog | Same as Cancel. | Focus trap active inside dialog. |
| Click Approve | RatificationControls | Fires `submitRatification(APPROVE)`. On success: controls transition to voted-approve. If threshold met: banner slides down, counter promotes to accent, controls replaced with ratified message. | Disabled for author and already-voted actors. |
| Click Reject | RatificationControls | Rejection textarea slides open below buttons. | First click opens textarea. Does not immediately fire mutation. |
| Submit rejection | RatificationControls | Fires `submitRatification(REJECT, comment)`. On success: controls transition to voted-reject. Banner slides down (red). | Comment optional, max 500 chars. |
| Cancel rejection | RatificationControls | Textarea slides closed. Buttons return to active state. | |
| Click "show reasons" | RatificationSummary | Expands dismissed suggestion reasons list. Toggle text changes to "hide reasons". | Left border `--color-border` 2px on expanded list. |
| Poll ratification state | RatificationView | Every 5 seconds, re-fetches `ratificationState`. Verdicts update in place. Approval counter animates if changed. | Poll stops when terminal state reached. |

### Motion

| Name | Duration | Easing | Property | Usage |
|------|----------|--------|----------|-------|
| `state-change` | 150ms | ease-out | background, border-color, color, opacity | Hover/focus transitions on Commit button, Approve, Reject, ghost buttons |
| `dialog-fade` | 150ms | ease-out | opacity | Modal overlay fade in/out |
| `dialog-slide` | 200ms | ease-out | opacity, transform (translateY 12px to 0) | Dialog card entrance |
| `banner-slide` | 250ms | ease-out | opacity, transform (translateY -8px to 0) | Ratification banner entrance (ratified or rejected) |
| `verdict-fade` | 200ms | ease-out | opacity | New verdict entry appears in the verdict list |
| `counter-tick` | 300ms | ease-out | opacity | Approval counter number change (old value fades, new value fades in) |
| `reject-expand` | 200ms | ease-out | height, opacity | Rejection textarea slides open |
| `spinner` | 600ms | linear | transform (rotate 0 to 360deg) | Infinite rotation on commit/approve loading |

**Reduced motion policy:** Replace all animations with instant state changes. `dialog-slide` becomes instant show. `banner-slide` becomes instant show. `verdict-fade` becomes instant appearance. `counter-tick` becomes instant swap. The state change itself is never removed, only the motion.


## Responsive Behavior

| Breakpoint | CommitBar | CommitDialog | RatificationView |
|------------|-----------|-------------|-----------------|
| < 1024px | Not supported (ceremony editor minimum) | Not supported | Not supported. "Ratification requires a wider viewport." Link to portfolio mode. |
| 1024-1280px | Full width, validation badges may wrap to 2 lines | Max 480px centered, unchanged | Right panel collapses to overlay (320px). Click summary icon to toggle. Spec fills viewport. |
| 1280px+ | Full width, single row | Same | Full two-panel layout. |


## Accessibility

### Keyboard Navigation

| Component | Keys | Behavior |
|-----------|------|----------|
| CommitBar | Cmd+Enter | Trigger commit (same as clicking Commit button) |
| CommitDialog | Escape | Close dialog without committing |
| CommitDialog | Enter | Confirm commit (when confirm button focused) |
| CommitDialog | Tab | Cycle through checklist items, note textarea, Cancel, Confirm |
| RatificationControls | Tab | Move between Approve and Reject buttons |
| RatificationControls | Enter | Activate focused button |
| Rejection textarea | Escape | Close rejection comment, return to button state |
| Rejection textarea | Cmd+Enter | Submit rejection |
| Dismiss reasons toggle | Enter/Space | Expand/collapse dismissed suggestion reasons |

### ARIA & Screen Reader

| Component | Role | ARIA | Announcement |
|-----------|------|------|--------------|
| CommitBar | `toolbar` | `aria-label="Commit controls"` | — |
| CommitButton (disabled) | — | `aria-disabled="true"`, `title="Template conformance required"` | — |
| CommitDialog | `dialog` | `aria-modal="true"`, `aria-label="Commit spec"` | Focus trapped inside dialog. |
| CommitDialog checklist | `list` | `aria-label="Validation summary"` | — |
| CommitDialog checklist item | `listitem` | `aria-label="{dimension}: {status}"` | — |
| RatificationView | `main` | `aria-label="Spec ratification for {feature}"` | — |
| RatificationSummary | `region` | `aria-label="Ratification evidence"` | — |
| Approval counter | `status` | `aria-live="polite"`, `aria-label="{N} of {M} approvals"` | "{N} of {M} approvals" announced on change |
| RatificationControls | `toolbar` | `aria-label="Ratification controls"` | — |
| Approve button | `button` | `aria-label="Approve spec for execution"`, `aria-disabled` when author or voted | — |
| Reject button | `button` | `aria-label="Reject spec, request rework"`, `aria-disabled` when author or voted | — |
| Ratification banner | `alert` | `aria-live="assertive"` | "Spec ratified. speed plan is now unblocked." or "Spec rejected." announced immediately. |
| Rejection textarea | `textbox` | `aria-label="Rejection comment (optional)"` | — |
| Verdict list | `list` | `aria-label="Submitted verdicts"` | — |
| Verdict entry | `listitem` | `aria-label="{actor} {verdict} at {time}"` | New verdict announced via parent's aria-live |

### Contrast & Targets

All color tokens are defined in `globals.css` with contrast ratios documented:
- `--color-text` (#e4e4e9) against `--color-bg-card` (#1c1c27): ~13:1
- `--color-text-secondary` (#9494a3) against `--color-bg-card`: ~5.5:1
- `--color-text-tertiary` (#55556a): decorative only, not used for actionable content
- `--color-emerald` (#44cc77) against `--color-bg` (#0c0c10): ~9:1 (approve button text is `--color-bg`, which gives >10:1)
- `--color-red` (#ef4464) against transparent bg: sufficient contrast for outline button text

All interactive targets meet 44x44px minimum. Approve and Reject buttons use `flex: 1` within the 320px panel, giving each button approximately 150px width and 44px height (10px vertical padding + line-height). CommitBar Commit button uses 8px vertical padding + 20px horizontal, exceeding 44px hit target height within the 52px bar.


## Content Constraints

| Element | Min | Max | Overflow | Placeholder |
|---------|-----|-----|----------|-------------|
| Commit note | 0 chars | No limit | Wraps, textarea grows | "Optional commit note..." |
| Rejection comment | 0 chars | 500 chars | Wraps | "Why are you rejecting this spec?" |
| Verdict actor name | — | 32 chars | Truncate with ellipsis | — |
| Feature name (dialog) | — | 50 chars | Truncate with ellipsis | — |
| Checklist dimension label | — | 20 chars | No overflow expected | — |
| Checklist summary text | — | 60 chars | Truncate with ellipsis | — |
| Ratification banner text | Fixed | Fixed | N/A | — |
| Post-commit inline message | Fixed | Fixed | N/A | — |
| Content hash display | 8 chars | 8 chars | First 8 chars of SHA-256 | — |
| Approval counter numerator | 1 char | 2 chars | N/A (max threshold ~99) | — |


## Implementation Notes

- CommitBar uses `position: sticky` at the bottom of editor-area, below the validation gutter. Verify no ancestor sets `overflow: hidden`, which would break sticky positioning. The prototype at `working-docs/commit-ratification-prototype.html` uses `flex-shrink: 0` with a flex column layout as an alternative.
- CommitDialog reuses the `.surface` class for the modal card and the `.btn-primary` / `.btn-ghost` patterns from the prototype. Focus trap implementation: on mount, record the previously focused element, focus the first focusable child (Cancel button), and on Escape/close restore focus. Use the `inert` attribute on content behind the overlay.
- The ratification route `/define/:feature/review` is a separate page, not a panel within the ceremony editor. `RatificationView` composes `RatificationSummary` and `RatificationControls` in the right panel alongside a read-only render of the committed spec on the left. The spec is read from `commitment.spec` (frozen at commit time), not from the live editor draft.
- Approval counter animation: when `approvalCount` changes, the old number fades out (150ms) and the new number fades in (150ms). At threshold met, the color transitions from `--color-text` to `--color-accent` using the `state-change` motion token (150ms). With `prefers-reduced-motion`, both changes are instant.
- Ratification polling: the `ratificationState` query runs every 5 seconds while the ratification view is mounted. Polling stops when `ratificationState.status` is `"approved"` or `"rejected"`. Use `useInterval` or equivalent, not `setInterval`, to avoid polling when the tab is not visible.
- The rejection textarea uses the `reject-expand` motion token (200ms ease-out on height and opacity). On mount, it auto-focuses the textarea. On cancel, it reverses the animation and restores focus to the Reject button.
- Post-commit messaging in CommitBar: after a successful commit, the right portion of the bar (suggestion summary + button) is replaced with the success message. The validation summary on the left remains visible as a record of the final state.


## Verification Criteria

### CommitBar
- [ ] CommitBar renders as a 52px fixed bar at the bottom of editor-area with `--color-bg-card` bg and `--color-border` top border
- [ ] Validation stats show pass/warn/fail counts using the correct status colors (emerald/amber/red) in mono 11px 500
- [ ] Vertical separator (1px, 20px tall, `--color-border`) separates validation from suggestion summary
- [ ] Suggestion summary shows resolved and pending counts; pending count uses `--color-amber` when > 0
- [ ] Commit button uses `--color-accent` bg when enabled, `--color-text-tertiary` bg when template non-conformant
- [ ] Disabled state shows "Template conformance required" blocker text in `--color-red`
- [ ] Cmd+Enter keyboard shortcut opens the commit dialog
- [ ] MP mode shows "Commit & Propose" label instead of "Commit"

### CommitDialog
- [ ] Modal overlay uses `rgba(0,0,0,0.6)` backdrop at z-index 200
- [ ] Dialog card is max 480px, centered, uses `.surface` class, 24px padding
- [ ] Title "Commit spec" (15px 600) with feature name below in mono 12px 500 `--color-text-secondary`
- [ ] Dimension checklist renders one row per validation dimension with status icon + name + summary
- [ ] Optional note textarea has `--color-bg-elevated` bg, `--color-border` border, focus state `--color-accent-glow`
- [ ] Unresolved suggestions listed as warnings in `--color-amber` (non-blocking)
- [ ] Confirm button shows spinner during mutation; Cancel button remains interactive
- [ ] Focus trapped inside dialog; Escape closes; Tab cycles through controls
- [ ] Error message from failed mutation renders below actions in `--color-red`

### RatificationView
- [ ] Two-panel layout: read-only spec (fluid width) left, evidence panel (320px) right
- [ ] Read-only spec shows lock icon + "READ-ONLY SPEC" label in mono 11px uppercase `--color-text-tertiary`
- [ ] Approval counter renders as hero metric: numerator in mono 28px 600, denominator in mono 15px 400 `--color-text-tertiary`
- [ ] Numerator color is `--color-text` below threshold, `--color-accent` when threshold met
- [ ] Approval label "APPROVALS" in 11px 500 `--color-text-secondary` uppercase with 0.05em letter-spacing
- [ ] Commit metadata section shows author, date (relative time + tooltip), and content hash (first 8 chars, mono 11px `--color-text-tertiary`)
- [ ] Validation section mirrors the commit dialog checklist (pass/warn/fail per dimension)
- [ ] Suggestion history shows received/accepted/dismissed counts; "show reasons" expands dismissed reasons with 2px `--color-border` left border

### Ratification Verdicts & Banner
- [ ] Each verdict renders as: 8px colored dot (emerald approve / red reject) + actor name + timestamp
- [ ] Ratified banner: `rgba(68, 204, 119, 0.12)` bg, `--color-emerald` text, slides down with 250ms ease-out
- [ ] Rejected banner: `rgba(239, 68, 100, 0.12)` bg, `--color-red` text, same animation
- [ ] Banner uses `aria-live="assertive"` for screen reader announcement

### RatificationControls
- [ ] Approve: emerald bg, `--color-bg` text. Reject: transparent bg, red border, red text
- [ ] Author sees both buttons disabled with "You cannot ratify your own spec" text
- [ ] Already-voted actor sees buttons disabled with "You approved/rejected this spec" + timestamp
- [ ] Reject click opens inline textarea (12px, `--color-bg-elevated` bg, `--color-red` border, 56px min-height)
- [ ] Rejection submit row: "Cancel" ghost + "Reject" red filled button (12px 600)

### General
- [ ] Token audit passes with zero hardcoded color/spacing/font values
- [ ] All interactive targets meet 44x44px minimum
- [ ] Reduced motion: all animations replaced with instant transitions when `prefers-reduced-motion: reduce` is active
- [ ] Focus indicators use the accent ring pattern (2px offset) on all interactive elements
- [ ] At viewports 1024-1280px, ratification right panel collapses to overlay toggle
- [ ] Polling stops on terminal state (approved or rejected)


## Figma / Visual Reference

No Figma file exists for this feature. The design spec is the source of truth.

Prototype: see `working-docs/commit-ratification-prototype.html` (local file, not tracked in specs). Single HTML file with five views: Editor Ready, Editor Blocked, Commit Dialog, Ratification Waiting, Ratification Approved. Uses actual design tokens from `globals.css`. Navigate between views using the bottom bar.

Reference the existing dashboard components for visual consistency: `.surface`, `.surface-elevated`, `.btn-primary`, `.btn-ghost`, `.vg-badge` classes in `globals.css` and the prototype.
