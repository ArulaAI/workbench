---
status: draft
feature: speed-define-ceremony-ownership
---

# Design: Define Ceremony — Per-Spec Ownership

> See [product spec](../product/speed-define-ceremony-ownership.md) for product context.
> Extends: [parent Design spec](speed-define-ceremony.md). This child spec only covers the deltas introduced by per-spec ownership. Regions, spacing, typography, and component inventory from the parent apply unchanged unless explicitly overridden here.
> Design system: `dashboard/frontend/app/globals.css`
> Prototype: [working-docs/prototype-speed-define-ceremony-ownership.html](../../working-docs/prototype-speed-define-ceremony-ownership.html)

## Design Intent

**Direction:** The ceremony editor already feels like a focused writing tool with intelligence alongside. Ownership adds a quiet coordination layer on top: tabs carry claimant names, the context panel shows a progress overview, and every mutation affordance either works (you own the spec) or explains why it doesn't (someone else owns it, or the claim is stale and reclaimable). Nothing on the surface should shout. Coordination is information, not alarm.

**Do not:**

- Hide disabled affordances. Non-claimants see the Commit button with a muted "Claimed by alex" note, not an absent button. Discoverability over minimalism.
- Add colored borders or decorative frames around claimed tabs. Claim state is communicated through claimant name, text color, and the existing active-tab accent border. No second border layer.
- Introduce new accent colors. Teal accent is for mine-and-primary. Amber is for stale and warnings. Red is for unresolved-suggestions and rejection. Emerald is for ratified. No new hues.
- Show a confirmation dialog for Claim or Release. Both actions are reversible and have no external side effects. Stale takeover is one click, not a two-step modal.
- Branch rendering on roster size. Every ceremony renders the same tab bar, progress overview, and commit bar regardless of whether there is one roster member or twelve. A sole actor sees Claim buttons, claimant badges, and the full progress overview the same way a team does — they just never see "claimed-by-other" or "stale" states because they're the only member who could produce them.
- Auto-scroll, flash, or animate the Progress Overview when another claimant mutates a sibling spec. Updates land silently; the motion budget is reserved for user-initiated actions only.

## Pages / Routes

No new routes. Every ownership affordance lives on `/define/:feature`, the existing ceremony editor, with state-dependent chrome:

| Route | Change from parent | Notes |
|-------|--------------------|-------|
| `/define/:feature` | Tab bar gains claim badges and affordances; context panel gains Progress Overview section; commit bar scopes to active tab and toggles between commit / ratify / disabled-with-reason modes. | Single page, multiple modes based on viewer's relationship to the active spec. See **States** below. |
| `/define/:feature/review` | Parent spec defines this as a separate ratification page. **This child spec retires it.** Ratification happens inline on `/define/:feature` via a verdict control that surfaces in the commit bar region once the viewer is a non-claimant of a committed spec. One page, not two. | Rationale: the product PRD describes ratification as "approver opens the Define surface", and the parent's `/review` route was scaffolding for the single-author model. Per-spec ratification makes a separate route unnecessary because different specs in the same ceremony can be in different ratification states, which a single route can't represent. |
| `/define/:feature/history` | Unchanged from parent. Historical context viewing is orthogonal to ownership. | — |

## Layout Structure

### Global Layout

Unchanged from parent. IconRail (52px fixed) stays left; content fills the rest.

### Regions

The parent Design spec defines seven regions (`intent-input`, `context-panel`, `editor-area`, `validation-gutter`, `suggestion-sidebar`, `bootstrap-flow`, `history-view`). This spec adds one new region and modifies two existing ones:

| Region ID | Change | Position | Width | Internal Layout | Scroll | Shortcut |
|-----------|--------|----------|-------|-----------------|--------|----------|
| progress-overview | **new** — slot inside `context-panel` | Top of context-panel, above context package sections | Fills context-panel width (288px inside 320px panel) | Vertical stack: header + per-spec rows + summary footer | Inherits context-panel scroll | Cmd+Shift+P toggles expand/collapse |
| editor-area | modified — tab bar gains claim chrome, commit bar gains mode-aware scoping | unchanged | unchanged | unchanged | unchanged | — |
| context-panel | modified — hosts `progress-overview` as a new collapsible section above existing context package sections | unchanged | unchanged | unchanged | unchanged | unchanged |

The Progress Overview region is a child of context-panel, not a sibling. Collapsing the context panel collapses the progress overview with it. The two regions share the panel's existing scroll container.

## Component Inventory

New ownership components live in `dashboard/frontend/components/define/ceremony/ownership/`. Modified components stay at their existing paths.

| Component ID | Type | Location | Parent ID | Description |
|--------------|------|----------|-----------|-------------|
| EditorTabBar | modified | `editor/EditorTabs.tsx` (existing) | editor-area | Parent spec already modifies this for child RFC tabs and suggestion sidebar toggle. This spec adds claim chrome: claimant name inline with tab label, Claim/Release affordances, stale badge, lock glyph for read-only tabs, per-tab notification dot for unresolved suggestions. |
| TabClaimBadge | new | `ownership/TabClaimBadge.tsx` | EditorTabBar | Renders the claimant name or Claim affordance for a single tab. Accepts a `ClaimState` discriminated union and renders one of five variants: unclaimed, mine, claimed-by-other, stale, committed. |
| ClaimButton | new | `ownership/ClaimButton.tsx` | TabClaimBadge | Compact button rendered on unclaimed tabs. Dashed outline by default, accent border on hover. Fires `claimSpec` mutation on click with no confirmation. |
| TakeoverButton | new | `ownership/TakeoverButton.tsx` | TabClaimBadge | Amber-framed button on stale tabs. Fires `claimSpec` which the server resolves as a stale takeover in one transaction. Same click target as ClaimButton but different visual weight (amber fill instead of dashed outline). |
| StaleBadge | new | `ownership/StaleBadge.tsx` | TabClaimBadge | Amber pill showing "stale {duration}" where duration is human-readable ("2h", "1d"). Duration comes from `now - last_activity_at` computed on the client against a server-supplied clock reference. |
| CommitBar | modified | `ceremony/CommitBar.tsx` (existing) | editor-area | Parent spec defined it for single-author commits. This spec extends it with mode-aware scoping: scope label shows the active tab's spec type, validation and suggestion counts filter to that spec only, and the primary button swaps between Commit (claimant, drafting), Ratify (non-claimant, committed), and a disabled state with reason text (non-claimant, drafting or stale). |
| CommitBarScope | new | `ownership/CommitBarScope.tsx` | CommitBar | Mono-font label showing `SCOPE [spec_type]` at the left of the commit bar. Clicking it opens a dropdown listing every drafted spec in the ceremony, so the user can jump to a sibling commit bar without switching tabs first. |
| RatifyControl | new | `ownership/RatifyControl.tsx` | CommitBar | Replaces the Commit button when the viewer is a non-claimant of a committed spec and ratification is open. Two buttons side by side: Approve (emerald) and Reject (red outline). Both open a one-line verdict comment affordance. Submit fires `submitRatification`. |
| ContextPanel | modified | `editor/IntelPanel.tsx` (existing, ceremony mode) | context-panel | Parent spec adds ceremony mode. This spec adds the Progress Overview section as the first item in ceremony mode, above the existing context package sections. |
| ProgressOverview | new | `ownership/ProgressOverview.tsx` | context-panel | Top-of-panel section listing every drafted spec in the ceremony with its claimant, validation summary, open-suggestion count, and commit status. Single 5-column layout regardless of roster size. Collapses with the existing ContextSection pattern. |
| ProgressRow | new | `ownership/ProgressRow.tsx` | ProgressOverview | Single row per spec. Clicking the row activates that spec's tab in the editor. Row highlights on hover with the same treatment as other clickable list items in the dashboard. |
| ProgressSummary | new | `ownership/ProgressSummary.tsx` | ProgressOverview | Footer line summarizing aggregate state: `N of M committed · K of M ratified`. Font-mono, text-secondary. Same format regardless of roster size (sole-actor ceremonies simply show the same committed and ratified counts converging on the same number). |
| ReadOnlyBanner | new | `ownership/ReadOnlyBanner.tsx` | editor-area (inside SpecEditor wrapper) | Banner at the top of the editor body when the viewer is a non-claimant. Two states: **standard** (grey left-border, lock glyph, "Claimed by {name}") and **stale** (amber left-border, clock glyph, "{name} has been inactive for {duration}, click Claim to take over"). Same shape; different color and message. |
| SuggestionPopover | new | `ownership/SuggestionPopover.tsx` | SpecEditor (read-only mode) | Floating popover that appears when a non-claimant selects text in the read-only editor. Anchored to the selection rect. Contains a "Leave suggestion" button and a keyboard hint (`⌘⇧M`). Clicking the button opens the existing `SuggestionComposer` from the parent spec, anchored to the selected section. |
| ClaimHistoryPanel | new | `ownership/ClaimHistoryPanel.tsx` | context-panel | Optional secondary context block under Progress Overview. Shows the claim event log for the active tab's spec: claim started, edits, release/stale/commit. Collapsed by default in non-stale states; auto-expanded when the active tab is stale. Reads from the multiplayer event stream, filtered by feature name and spec type. |

### Component Props

#### TabClaimBadge

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| state | ClaimState | required | Discriminated union. See type definition below. |
| onClaim | () => void | — | Called when the Claim button is clicked (unclaimed or stale variants only). |
| onRelease | () => void | — | Called when the Release button is clicked (mine variant only). |

`ClaimState` discriminated union:

```ts
type ClaimState =
  | { kind: "unclaimed" }
  | { kind: "mine"; claimant: string }
  | { kind: "claimed-by-other"; claimant: string; committed: boolean }
  | { kind: "stale"; claimant: string; staleFor: string }
  | { kind: "committed"; claimant: string; ratified: boolean }
```

`ClaimState` is a client-side composition, not a single GraphQL field. The RFC's `ceremonyClaims` query returns `list[SpecClaim]` with claim-only fields (`claimant`, `claimant_email`, `claimed_at`, `last_activity_at`, `released_at`); it does not carry commit or ratification state. The client computes each variant by combining `SpecClaim` with the per-spec file reads the Progress Overview already performs:

| Variant | Composed from |
|---------|---------------|
| `unclaimed` | No `SpecClaim` entry for this `spec_type` |
| `mine` | `SpecClaim.claimant_email == currentActor.email` AND `released_at == null` |
| `claimed-by-other` | `SpecClaim.claimant_email != currentActor.email` AND `released_at == null` AND `last_activity_at` within `stale_window`. `committed` is `true` iff `commit-{spec_type}.json` exists (the original claimant's draft is locked in but ratification hasn't opened) |
| `stale` | `SpecClaim` exists AND `now - last_activity_at > stale_window` AND `released_at == null` |
| `committed` | `commit-{spec_type}.json` exists AND `SpecClaim.released_at != null`. `ratified` is `true` iff `ratification-{spec_type}.json.ratified == true` |

The composition runs on the same data already fetched for Progress Overview (`ceremonyClaims` + `commit-*.json` + `ratification-*.json` listings), so the tab bar does not need a new query. `EditorTabBar` reads the composed state from a selector over the same React Query cache the context panel uses.

#### ProgressOverview

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| rows | ProgressRowData[] | required | One entry per drafted spec. See row shape below. |
| ceremonyStatus | CeremonyStatus | required | DRAFTING / COMMITTED / RATIFIED / REJECTED / ABANDONED. Drives summary line format. |
| defaultOpen | boolean | — | Auto-computed from `rows.length`: true when > 3, false otherwise. Overridable for testing. |
| onRowClick | (spec_type: string) => void | required | Activates the corresponding tab in the editor. |

```ts
type ProgressRowData = {
  spec_type: string;
  claimant: string | null;          // null = unclaimed
  claimantStatus: "active" | "stale" | "released";
  validation: "pass" | "warn" | "fail" | "pending";
  validationWarnings: number;
  suggestionsOpen: number;
  status: "drafting" | "committed" | "ratified" | "rejected";
}
```

#### ProgressRow

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| row | ProgressRowData | required | Row data. |
| isActiveTab | boolean | false | Highlights the row when its spec is the currently active tab. |
| onClick | () => void | required | Activates this spec's tab. |

#### ProgressSummary

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| totalDrafted | number | required | Total drafted specs in the ceremony. |
| totalCommitted | number | required | Total committed. |
| totalRatified | number | required | Total ratified. |

#### ReadOnlyBanner

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| kind | "standard" \| "stale" | required | Drives color (grey vs amber) and glyph (lock vs clock). |
| claimant | string | required | Claimant name shown in banner text. |
| staleFor | string | — | Required when `kind = "stale"`. Human-readable duration. |
| onTakeover | () => void | — | Required when `kind = "stale"`. Takeover click handler. |

#### SuggestionPopover

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| anchorRect | DOMRect | required | Bounding rect of the text selection. Popover positions below. |
| onLeaveSuggestion | () => void | required | Opens the `SuggestionComposer` (from parent spec) anchored to the selection. |
| onDismiss | () => void | required | Closes the popover without opening the composer. |

#### CommitBar (ownership additions)

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| activeSpecType | string | required | The spec_type of the currently active tab. Scope label reads from this. |
| mode | "commit" \| "ratify" \| "disabled-claimed" \| "disabled-stale" | required | Drives button rendering and disabled messaging. |
| disabledReason | string | — | Required when `mode` starts with `disabled-`. Shown as a muted caption next to the disabled button. |
| onRatify | (verdict: "approve" \| "reject", comment?: string) => void | — | Required when `mode = "ratify"`. Fires `submitRatification`. |

#### RatifyControl

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| specType | string | required | Spec being ratified. |
| approvalCount | number | required | Current approvals. |
| approvalThreshold | number | required | Required approvals. |
| hasVoted | boolean | required | True if this actor already submitted a verdict. |
| onApprove | (comment?: string) => void | required | Approve callback. |
| onReject | (comment?: string) => void | required | Reject callback. |

#### ClaimHistoryPanel

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| specType | string | required | Filters events to this spec. |
| events | ClaimEvent[] | required | Events: { timestamp, actor, kind, payload }. |
| activeTabIsStale | boolean | false | Drives default expanded state. |

## Spacing

Inherits the parent Design spec's spacing grid (4px base, 24px page margin, 20px editor padding, 40px tab bar height). New contexts introduced by this spec:

| Context | Token | Usage |
|---------|-------|-------|
| Tab claim badge gap | 6px | Between tab label and claimant name / Claim button inside a tab |
| Tab claim button padding | 3px 10px | Internal padding for Claim / Release / Takeover buttons on tabs |
| Tab stale badge padding | 2px 7px | Internal padding for the amber stale pill |
| Progress Overview section padding | 16px 0 0 0 | Top padding inside the section; inherits context panel horizontal padding |
| Progress Overview row padding | 10px 0 | Vertical padding per row; horizontal padding inherits the panel |
| Progress Overview row gap | 8px | Space between left column (spec name + claimant) and right column (metrics) |
| Progress Overview summary padding | 12px 0 0 0 | Top padding for the summary line, separated from rows by a border |
| Progress Overview column separator | 1px | Border between rows uses `--color-border-light` |
| Read-only banner padding | 10px 14px | Internal padding for the top-of-editor banner |
| Read-only banner gap | 10px | Between the glyph and the message text |
| Read-only banner margin-bottom | 20px | Space between banner and first editor heading |
| Suggestion popover padding | 6px 10px | Internal padding for the floating selection popover |
| Suggestion popover offset | 8px | Distance below the text selection where popover anchors |
| Commit bar scope label gap | 14px | Between scope label and validation status |
| Commit bar disabled note gap | 8px | Between disabled button and "Claimed by {name}" caption |
| Claim History panel row gap | 4px | Between event log rows |
| Claim History panel row padding | 0 | Rows are inline; padding lives on the section |
| Ratify control button gap | 8px | Between Approve and Reject buttons |
| Ratify comment affordance margin-top | 6px | Space between button row and comment field when verdict is being composed |

## Typography

Inherits the parent spec's type ladder. New typography roles and role reuse specific to ownership:

| Element | Role | Family | Size | Weight | Line-Height | Color |
|---------|------|--------|------|--------|-------------|-------|
| Tab label (unchanged) | type-cell-label | font-sans | 12px | 500 | 1.4 | text (active) / text-secondary (inactive) |
| Tab claimant name (mine) | type-caption | font-sans | 11px | 400 | 1.4 | accent |
| Tab claimant name (other) | type-caption | font-sans | 11px | 400 | 1.4 | text-tertiary |
| Tab claimant name (stale) | type-caption | font-sans | 11px | 400 | 1.4 | amber |
| Tab Claim button label | type-compact-label | font-mono | 9px | 500 | 1.4 | text-secondary (hover: accent) |
| Tab Takeover button label | type-compact-label | font-mono | 9px | 600 | 1.4 | amber |
| Tab stale badge text | type-compact-label | font-mono | 9px | 600 | 1.4 | amber |
| Progress Overview section title | type-compact-label | font-mono | 9px | 600 | 1.4 | text-tertiary |
| Progress Overview spec_type | type-mono-value | font-mono | 11px | 600 | 1.4 | text |
| Progress Overview claimant name | type-caption | font-sans | 11px | 400 | 1.6 | text-secondary (other) / accent (mine) / amber (stale) / text-tertiary italic (unclaimed) |
| Progress Overview validation meta | type-compact-label | font-mono | 10px | 400 | 1.6 | text-tertiary (with inline status color on the glyph) |
| Progress Overview status pill | type-compact-label | font-mono | 9px | 600 | 1.4 | per status (drafting = text-secondary, committed = accent, ratified = emerald, stale = amber, unclaimed = text-tertiary) |
| Progress Overview summary | type-caption | font-mono | 11px | 400 | 1.4 | text-secondary (strong numbers in text) |
| Read-only banner message | type-body | font-sans | 13px | 400 | 1.5 | text-secondary (claimant name in text) |
| Read-only banner glyph | — | — | 13px | — | — | amber (stale) / text-tertiary (standard) |
| Suggestion popover button | type-compact-label | font-mono | 10px | 600 | 1 | bg (on accent) |
| Suggestion popover hint | type-compact-label | font-mono | 10px | 400 | 1 | text-tertiary |
| Commit bar scope label | type-compact-label | font-mono | 11px | 500 | 1.4 | text-tertiary (SCOPE) / text-secondary (spec_type) |
| Commit bar disabled caption | type-caption | font-mono | 11px | 400 | 1.4 | text-tertiary |
| Ratify Approve button | type-badge | font-sans | 13px | 600 | 1 | bg (on emerald) |
| Ratify Reject button | type-badge | font-sans | 13px | 600 | 1 | red (outline variant) |
| Claim History row timestamp | type-compact-label | font-mono | 10px | 400 | 1.8 | text-tertiary |
| Claim History row actor + action | type-caption | font-mono | 11px | 400 | 1.8 | text-secondary |
| Claim History stale line | type-caption | font-mono | 11px | 500 | 1.8 | amber |

## Color Application

Inherits every color assignment from the parent Design spec. Ownership-specific element mappings:

| Element | Property | Token | Notes |
|---------|----------|-------|-------|
| Tab claimant (mine) | color | accent | Signals "you own this" without a second border |
| Tab claimant (claimed by other) | color | text-tertiary | Muted; the active-tab border still uses accent if active |
| Tab claimant (stale) | color | amber | Primary stale signal — reinforced by stale badge |
| Tab Claim button (unclaimed, rest) | border-color, color | border-strong (dashed), text-secondary | Dashed to signal empty/available |
| Tab Claim button (unclaimed, hover) | border-color, color | accent, accent | Single hover treatment |
| Tab Takeover button (stale) | background, border, color | amber-glow, amber, amber | Amber on amber-glow background, filled weight |
| Tab stale badge | background, border, color | amber-glow, amber 30% opacity, amber | Pill with soft fill |
| Tab lock glyph (claimed by other) | color | text-tertiary | Tertiary is OK here — glyph is decorative, text carries the meaning |
| Tab notification dot (unresolved suggestions) | background, color | red, bg | Red dot with tab bg color text for contrast |
| Progress Overview row (hover) | background | bg-card-hover | Matches dashboard list hover treatment |
| Progress Overview row (active tab) | border-left, padding-left | accent, 8px | 2px left accent bar replaces standard hover background |
| Progress Overview claimant (mine) | color | accent | Matches tab treatment |
| Progress Overview claimant (stale) | color | amber | Matches tab treatment |
| Progress Overview claimant (unclaimed) | color, font-style | text-tertiary, italic | Italic signals absence |
| Progress Overview validation pass | color | emerald | Glyph only; label stays text-tertiary |
| Progress Overview validation warn | color | amber | Glyph + count |
| Progress Overview suggestions (flag) | color | red | Applied when `suggestionsOpen > 0` for the claimant's spec |
| Progress Overview status pill (drafting) | background, border, color | bg-card, border-strong, text-secondary | Neutral |
| Progress Overview status pill (committed) | background, border, color | accent-glow, accent 25% opacity, accent | Primary signal |
| Progress Overview status pill (ratified) | background, border, color | emerald 10% opacity, emerald 25% opacity, emerald | Terminal good state |
| Progress Overview status pill (stale) | background, border, color | amber-glow, amber 25% opacity, amber | Matches tab stale treatment |
| Progress Overview status pill (unclaimed) | background, border, color | transparent, border-strong (dashed), text-tertiary | Matches tab unclaimed treatment |
| Progress Overview summary strong text | color | text | Strong numbers pop against the text-secondary body |
| Read-only banner background | background | bg-card | Surface class |
| Read-only banner left border (standard) | border-left | text-tertiary, 2px | Subtle |
| Read-only banner left border (stale) | border-left | amber, 2px | Matches stale signal family |
| Read-only banner glyph (standard) | color | text-tertiary | Matches border |
| Read-only banner glyph (stale) | color | amber | Matches border |
| Suggestion popover background | background, border | bg-card, border-strong | Surface class with stronger border because popover floats |
| Suggestion popover button | background, color | accent, bg | Matches Commit button treatment |
| Commit bar scope label (SCOPE) | color | text-tertiary | Prefix label |
| Commit bar scope label (spec_type) | color | text-secondary | The actual value |
| Commit bar mode disabled button | background, border, color | bg-card, border, text-tertiary | Same style as existing disabled commit button from parent |
| Commit bar disabled note | color | text-tertiary | Muted caption |
| Commit bar warning (unresolved) | color | amber | Matches parent spec's unresolved-count color |
| Commit bar warning (stale) | color | amber | Stale claim warning |
| Ratify Approve button | background, color | emerald, bg | Primary affordance |
| Ratify Reject button | background, border, color | transparent, red, red | Outline variant — rejection is consequential, not primary |
| Ratify threshold count (met) | color | accent | Matches parent ratification spec |
| Ratify threshold count (not met) | color | text | Matches parent |
| Claim History row | background | transparent | Inline list, no card |
| Claim History stale row highlight | color | amber | Stale milestone row stands out |

## Elevation & Depth

Inherits parent elevation levels. New elements:

| Element | Elevation Level | Treatment |
|---------|-----------------|-----------|
| Progress Overview section | inherits context-panel | Level 1, no additional elevation; it's a section inside the panel |
| Progress Overview row (hover) | inherits | No elevation change; only background tint |
| Read-only banner | 2 | `surface` class — sits above editor body, must read against the scroll area |
| Suggestion popover | 3 | `surface` class + shadow-md; floats above editor content |
| Tab stale badge | inherits tab bar | No independent elevation; inline text badge |
| Tab Claim / Takeover button | inherits tab bar | No elevation; inline button |
| Claim History panel | inherits context-panel | Level 1; same as Progress Overview |
| Ratify verdict comment affordance | inherits commit bar | Same level as commit bar when expanded |

## States

### Page-Level States

These are new to the ownership feature. The parent spec defines four ceremony page states (intent input, context assembly loading, ceremony editor populated, error). This spec adds viewer-relative modes that overlay the populated state.

#### Viewer is claimant of active tab

Editor writable. Tab bar shows mine treatment on the active tab (accent claimant name, accent underline). Commit bar scopes to the active spec, Commit button enabled when validation passes. No banner above the editor body. Progress Overview highlights the active tab row with the accent left bar.

#### Viewer is non-claimant of active tab (drafting)

Editor read-only with the diagonal-stripe background (see Implementation Notes). `ReadOnlyBanner` with `kind="standard"` renders above the editor body. Commit button disabled with "Claimed by {name}" caption. Selecting text in the editor body surfaces `SuggestionPopover`. Progress Overview highlights the active tab row with the standard hover background (no accent bar, since the viewer doesn't own it).

#### Viewer is non-claimant of active tab (committed, ratification open)

Editor still read-only with stripe background. Read-only banner text changes to "Claimed by {name} · committed {duration}". Commit bar swaps the Commit button for `RatifyControl` (Approve / Reject). Ratify threshold count shows current votes vs. required. If the viewer has already voted, buttons disable and show "You voted: {verdict}".

#### Viewer is non-claimant of active tab (stale)

Editor read-only. `ReadOnlyBanner` with `kind="stale"` renders (amber border, clock glyph, takeover invitation text). Commit bar shows a warning instead of a scoped button: "Claim stale — takeover available" and a disabled Commit button with "Claim RFC first" caption. Tab bar shows the stale tab with amber claimant name, stale badge, and inline Takeover button. Progress Overview shows the spec's row with amber claimant text and stale status pill.

#### Active tab is unclaimed

Editor is empty (no draft file yet, generated placeholder from template). Commit bar shows scope label but no validation (nothing to validate) and no button — the tab must be claimed before commit is possible. Tab bar shows the tab with dashed outline and inline Claim button. Clicking the Claim button claims the spec and transitions this viewer into the claimant state above without a page load. This is the same state a sole roster member sees on Design and RFC tabs after `declareIntent` auto-claims the PRD.

#### Sole-actor ceremony

No distinct visual treatment. A ceremony with one roster member renders the exact same tab bar, progress overview, context panel, and commit bar as a multi-actor ceremony. The only difference is which ClaimStates the user ever sees in practice: `unclaimed` until they click Claim on Design and RFC, `mine` after they claim, and `committed` after they commit. They never see `claimed-by-other` or `stale` because nobody else is on the roster to produce those states. Ratification is handled server-side: `commitSpec` detects the empty-non-author condition and writes the ratification inline (see RFC), so the tab bar shows `committed` → `ratified` in one action without any `RatifyControl` ever surfacing to the user.

### Interactive Element States

Matrix for every new interactive element. One row per component, one column per state. Properties that change across states are named by token; properties that do not change are omitted.

| Component | Enabled | Hover | Focus | Pressed | Disabled | Loading |
|-----------|---------|-------|-------|---------|----------|---------|
| ClaimButton | border: border-strong dashed, text: text-secondary | border: accent, text: accent | outline: accent 2px, offset 2px | transform: scale(0.97) | n/a (hidden when no claim possible) | spinner replaces label, width locked |
| TakeoverButton | background: amber-glow, border: amber, text: amber | background: amber 15% opacity | outline: amber 2px, offset 2px | transform: scale(0.97) | n/a | spinner, width locked |
| ReleaseButton (in Mine state, hover over tab) | border: border dashed, text: text-tertiary | border: red, text: red | outline: red 2px | transform: scale(0.97) | n/a | — |
| ProgressRow | background: transparent | background: bg-card-hover | outline: accent 1px inset | — | — | — |
| ProgressRow (active tab) | border-left: accent 2px, padding-left: 8px | background: bg-card-hover (retains accent bar) | outline: accent 1px inset | — | — | — |
| SuggestionPopover button | background: accent, text: bg | background: accent 90% opacity | outline: accent 2px, offset 2px | transform: scale(0.98) | n/a | — |
| CommitBar Commit button (claimant) | background: accent, text: bg | background: accent 90% | outline: accent 2px, offset 2px | transform: scale(0.98) | background: bg-card, text: text-tertiary, cursor: not-allowed | spinner replaces label |
| CommitBar Commit button (non-claimant, drafting) | — | — | — | — | **permanent disabled state**: background: bg-card, text: text-tertiary, disabled caption visible | — |
| CommitBar Commit button (non-claimant, stale) | — | — | — | — | **permanent disabled state** with "Claim {spec_type} first" caption | — |
| RatifyControl Approve | background: emerald, text: bg | background: emerald 90% | outline: emerald 2px, offset 2px | transform: scale(0.98) | after voting: background: emerald 30%, text: bg 70% | spinner replaces label |
| RatifyControl Reject | background: transparent, border: red, text: red | background: red 8% | outline: red 2px, offset 2px | transform: scale(0.98) | after voting: border: red 30%, text: red 50% | spinner replaces label |
| ReadOnlyBanner Takeover action (inline link) | color: amber, underline: none | underline: amber | outline: amber 2px, offset 2px | — | — | — |
| Progress Overview section header (collapse toggle) | color: text-tertiary | color: text-secondary | outline: accent 1px | — | — | — |

### Empty / Loading / Error for Progress Overview

| State | Treatment |
|-------|-----------|
| Empty (no drafted specs yet) | Progress Overview section collapses to a single line: "No specs drafted yet · claim a tab to begin" in text-tertiary. No rows rendered. |
| Loading (ceremonyClaims query in flight) | Rows render as skeleton rectangles (bg-card, 60% opacity, no pulse — opacity fade only per parent spec "Do not" rule). Summary shows em-dash placeholder. |
| Error (ceremonyClaims failed) | Red left border on section, message "Couldn't load claim state · {error}" with a retry link. Editor remains functional; the error is cosmetic in the context panel. |

### Page-level state transitions

Transitions that change ownership mode on the active tab without a page load:

| From | To | Trigger | Transition treatment |
|------|----|---------|----------------------|
| unclaimed | mine | User clicks Claim on active tab | Banner fades out (150ms opacity), stripe background fades out (150ms), editor enables. Tab badge fades from dashed to accent. |
| mine | unclaimed | User clicks Release on active tab | Inverse of above. No confirmation dialog. |
| mine | claimed-by-other | Another claimant takes over a stale claim while I'm viewing | Banner fades in with standard treatment; editor locks (input blurs, becomes read-only). Tab badge updates in place. No scroll jump. |
| claimed-by-other (drafting) | claimed-by-other (committed, ratification open) | Claimant commits their spec while I'm viewing it | Commit button morphs into RatifyControl (150ms cross-fade). Banner text updates inline. No banner fade; same banner, new message. |
| claimed-by-other (stale) | mine | User clicks Takeover on a stale active tab | Banner transitions from stale (amber) to hidden (150ms fade). Tab badge from stale to mine. Editor becomes writable. Draft content unchanged (preserved from previous claimant). |

**All transitions obey `prefers-reduced-motion`.** With reduced motion active, cross-fades are replaced with instant swaps. No position changes, no opacity animations, no width animations.

## Data Binding

Maps every dynamic element to its data source. Source names use the GraphQL schema the RFC introduces.

| Element | Source Field | Format | Constraints |
|---------|-------------|--------|-------------|
| Tab claimant name | `SpecClaim.claimant` | string | Truncate at 12 chars with ellipsis; full name in tooltip |
| Tab stale badge duration | computed: `now - SpecClaim.last_activity_at` | human-readable duration | "Xm" for < 1h, "Xh" for < 24h, "Xd" otherwise; computed on the client against a server-supplied reference clock |
| Tab notification dot count | filter: `Suggestion where spec_type == tab.spec_type and resolved == false` | number | "99+" when > 99; hidden when 0 |
| Progress Overview row.spec_type | `SpecClaim.spec_type` | string | Display: uppercase the leading segment (`"prd"` → `"PRD"`), title-case the slug (`"rfc-ingestion"` → `"RFC: ingestion"`) |
| Progress Overview row.claimant | `SpecClaim.claimant` or null | string | Truncate at 18 chars with ellipsis |
| Progress Overview row.claimantStatus | derived: `SpecClaim.released_at`, `last_activity_at`, `now`, `stale_window` | enum | "active" / "stale" / "released" |
| Progress Overview row.validation | `validation-state-{spec_type}.json`.summary | enum | Pass / Warn / Fail / Pending |
| Progress Overview row.validationWarnings | `validation-state-{spec_type}.json`.warnings.length | number | 0-N |
| Progress Overview row.suggestionsOpen | filter: `Suggestion where spec_type == row.spec_type and resolved == false` | number | 0-N |
| Progress Overview row.status | derived from the per-spec files: `drafting` if no `commit-{spec_type}.json`; `rejected` if `ratification-{spec_type}.json.verdicts` contains any entry with `verdict == "reject"`; `ratified` if `ratification-{spec_type}.json.ratified == true`; otherwise `committed` | enum | drafting / committed / ratified / rejected. Rejection is checked before ratification so a rejection verdict wins over a pending approval count. |
| Progress Overview summary | `ceremonyClaims` + `commit-*.json` + `ratification-*.json` listings | `N of M committed · K of M ratified` | Integers. Same format for every ceremony regardless of roster size. |
| Read-only banner claimant | `SpecClaim.claimant` | string | Not truncated; banner has room |
| Read-only banner stale duration | computed same as tab stale badge | human-readable | — |
| Claim History events | multiplayer event stream, filtered to `feature_name` + `spec_type`, kind in {claim_started, claim_refreshed, claim_released, claim_committed, claim_stale} | chronological list | Max 20 rows; older events link to full history page |
| Ratify control approval count | `ratification-{spec_type}.json`.verdicts.filter(v => v.verdict === "approve").length | number | — |
| Ratify control approval threshold | `speed.toml [multiplayer] ratification_threshold` | number | Default 1 |
| Ratify control hasVoted | `ratification-{spec_type}.json`.verdicts.some(v => v.actor_email === currentActor.email) | boolean | Keyed on `actor_email` (canonical identity), not `actor` (display name), to match the RFC's dedupe rule on Verdict |

## Interactions & Motion

### Interactions

| Trigger | Target | Response | Notes |
|---------|--------|----------|-------|
| Click Claim button on unclaimed tab | EditorTabBar | Fire `claimSpec(featureName, specType)`. Optimistic UI: tab transitions to mine state immediately. Rollback on server error with toast. | No confirmation dialog. |
| Click Release button on mine tab | EditorTabBar | Fire `releaseSpec(featureName, specType)`. Optimistic UI: tab transitions to unclaimed. Rollback on error. | Release button appears on hover over the claimant badge when the viewer is the claimant; not always visible. |
| Click Takeover button on stale tab | EditorTabBar | Fire `claimSpec(featureName, specType)` which server resolves as a stale takeover (single transaction). Optimistic UI: tab transitions from stale to mine, banner fades out, editor enables. | Same mutation as Claim on unclaimed; server handles the semantic difference. |
| Click Takeover link in ReadOnlyBanner (stale kind) | SpecEditor wrapper | Same as above. | Two click targets for the same action so either tab-bar scanners or tab-content scanners can discover it. |
| Select text in read-only editor | SpecEditor | Show SuggestionPopover anchored below the selection rect. | Popover dismisses on Escape, click outside, or scroll. |
| Click "Leave suggestion" in popover | SuggestionPopover | Open existing SuggestionComposer (from parent spec) anchored to the selected section. | SuggestionComposer fires the existing `createSuggestion` mutation; ownership only adds the `spec_type` field. |
| Press Cmd+Shift+M with text selected in read-only editor | SpecEditor | Same as clicking "Leave suggestion" in the popover. | Keyboard shortcut matches the hint shown in the popover. |
| Click Progress Overview row | ProgressRow | Activates the corresponding tab in the editor (no navigation). Scrolls editor to top. | Visual feedback: 100ms hover-bg flash before transition. |
| Hover over Progress Overview row | ProgressRow | Background transitions to bg-card-hover over 120ms. | Active tab row retains its accent left bar during hover. |
| Click scope label in commit bar | CommitBarScope | Dropdown opens listing every drafted spec in the ceremony with its commit status. Clicking a spec activates that tab. | Useful for quick jumping between specs when the commit bar has focus. |
| Click Approve in RatifyControl | RatifyControl | Opens an optional one-line comment field. Submit fires `submitRatification(specType, "approve", comment?)`. Cancel dismisses without submitting. | Comment is optional for approve; required for reject. |
| Click Reject in RatifyControl | RatifyControl | Opens a required comment field. Submit fires `submitRatification(specType, "reject", comment)`. Cancel dismisses. | Rejection without reason is blocked. |
| Expand Progress Overview collapse toggle | ProgressOverview | Section expands or collapses with 150ms height transition. State persists in localStorage per feature. | Default open state computed from `drafted_specs.count > 3`. |

### Motion

All ownership motions reuse the parent spec's motion tokens where possible. New tokens only where the parent spec has no equivalent.

| Name | Duration | Easing | Property | Usage |
|------|----------|--------|----------|-------|
| state-change (reused) | 150ms | ease-out | background, border-color, opacity | Tab badge state transitions, banner fade-in, row hover, button hover/focus transitions |
| enter (reused) | 200ms | ease-out | opacity, transform | SuggestionPopover entering, dropdown entering |
| exit (reused) | 150ms | ease-in | opacity | SuggestionPopover dismiss, banner fade-out on takeover |
| expand (reused) | 250ms | ease-in-out | height | Progress Overview section expand/collapse, Ratify comment field open |
| cross-fade (new) | 150ms | ease-in-out | opacity | CommitBar button morph (Commit → Ratify); rendered as two stacked elements with opposed opacities |
| scope-jump (new) | 0ms | — | — | Progress Overview row click to tab activation is instant; no animation because the user-initiated navigation should feel immediate |

**Reduced motion policy.** Replace every entry above with instant state changes. Cross-fades become instant swaps. Expand/collapse becomes instant visibility toggle. Hover transitions become instant. The focus ring stays visible but does not animate in. No motion is ever used to convey state that is not also conveyed statically (color, text, layout).

## Responsive Behavior

The ceremony editor is designed for desktop workflows. Mobile and narrow viewports get a reduced experience.

| Breakpoint | Columns | Behavior |
|------------|---------|----------|
| < 768px | 1 | Context panel (and Progress Overview inside it) hides behind a slide-out drawer toggled by an icon in the header. Editor fills full width. Tab bar scrolls horizontally when more than 3 tabs are present. Claim affordances move from inline-on-tab to a "•••" menu per tab (tap to open Claim/Release/Takeover). ReadOnlyBanner wraps to two lines. RatifyControl stacks Approve/Reject vertically. |
| 768–1024px | 2 | Context panel overlay on toggle (not fixed). Editor + overlay context panel. Tab bar horizontal scroll kicks in at 6+ tabs. |
| 1024–1440px | 3 | Context panel fixed 320px. Editor fluid. Tab bar fits up to 6 tabs without scroll; 7+ triggers horizontal scroll with gradient fade indicators at both edges. |
| > 1440px | 3 | Same as above. Editor max-width caps at 1080px so the reading measure stays comfortable; extra width becomes extra margin. |

### Tab bar overflow rule

When the number of tabs exceeds what fits without overflow, the tab bar scrolls horizontally. No collapse-behind-chevron pattern, because the active tab must always be visible and a collapse pattern would hide it in the chevron when the active tab is later in the order. Horizontal scroll keeps the active tab in view via `scrollIntoView({ inline: "nearest" })` on activation.

## Accessibility

### Keyboard Navigation

| Component | Keys | Behavior |
|-----------|------|----------|
| EditorTabBar | Left/Right arrows | Move focus between tabs; activating a tab is a separate Enter press |
| EditorTabBar | Home / End | Jump to first / last tab |
| EditorTabBar | Enter / Space (on focused tab) | Activate the tab |
| EditorTabBar | C (on focused unclaimed or stale tab) | Shortcut for Claim / Takeover (same mutation; context-dependent) |
| EditorTabBar | R (on focused mine tab) | Shortcut for Release |
| ProgressOverview | Up/Down arrows | Move focus between rows |
| ProgressOverview | Enter / Space | Activate the row's spec tab |
| ProgressOverview | Escape | Return focus to the editor |
| SuggestionPopover | Enter | Open the SuggestionComposer |
| SuggestionPopover | Escape | Dismiss the popover |
| RatifyControl | Tab | Move between Approve, Reject, and the comment field |
| RatifyControl | Escape | Dismiss the comment field without submitting |
| CeremonyLayout | Cmd+Shift+P | Toggle Progress Overview expand/collapse |
| CeremonyLayout | Cmd+Shift+M (with text selection in read-only editor) | Open SuggestionComposer anchored to selection |

Focus trap is not used anywhere in ownership UI. The editor, context panel, and commit bar are all in the same page flow; focus can move freely between them.

### ARIA & Screen Reader

| Component | Role | ARIA | Announcement |
|-----------|------|------|--------------|
| TabClaimBadge (mine) | — | aria-label="Owned by you" on the claimant name span | Screen reader reads "PRD, owned by you" when the tab is focused |
| TabClaimBadge (claimed-by-other) | — | aria-label="Claimed by {name}, read-only" on the claimant span | Screen reader reads "RFC, claimed by alex, read-only" |
| TabClaimBadge (stale) | status | aria-live="polite" on the stale badge; aria-label="Stale claim, takeover available" | Screen reader announces stale state when the tab gains focus; polite update when a claim transitions to stale |
| ClaimButton | button | aria-label="Claim {spec_type}" | "Claim PRD, button" |
| TakeoverButton | button | aria-label="Take over stale claim on {spec_type}" | "Take over stale claim on RFC, button" |
| ProgressOverview | region | aria-label="Ceremony progress"; aria-expanded on the collapse toggle | "Ceremony progress region, expanded" |
| ProgressRow | button | aria-label="{spec_type}, claimed by {claimant}, {status}" | "PRD, claimed by you, ratified" |
| ReadOnlyBanner | status | aria-live="polite" | Full banner text read when the banner first appears or when claim state changes |
| SuggestionPopover | dialog | aria-label="Suggestion actions"; aria-describedby pointing at selected text | "Suggestion actions dialog, anchored to Data Model section" |
| RatifyControl | group | aria-label="Ratification verdict for {spec_type}"; aria-describedby on the approval count | "Ratification verdict for RFC, 0 of 1 approvals needed" |
| CommitBar (disabled, non-claimant) | — | aria-label on button: "Commit {spec_type}, disabled — claimed by {name}" | "Commit RFC, disabled, claimed by alex, button" |

### Contrast & Targets

All new ownership text uses tokens from the parent spec's palette. Contrast ratios are pre-validated against `bg-card` and `bg-elevated`:

- Claimant name (mine, accent on bg-elevated): 7.2:1 — passes WCAG AA large text and AA normal text
- Claimant name (other, text-tertiary on bg-elevated): 2.8:1 — **below AA normal** but the tab label (text) carries the semantic content. The claimant name is decorative metadata. Flagged for a11y review; may need to bump text-tertiary to text-secondary for this specific use.
- Stale badge (amber on amber-glow): 6.1:1 — passes
- ReadOnlyBanner message (text-secondary on bg-card): 5.5:1 — passes

Touch targets: Claim, Release, Takeover buttons are 24px tall by 60px wide minimum. Below the 44x44 WCAG touch target minimum but above the 24px desktop pointer target. Flagged as a mobile concern; the responsive breakpoint < 768px moves these into a "•••" menu with full-size touch targets.

## Content Constraints

| Element | Min | Max | Overflow | Placeholder |
|---------|-----|-----|----------|-------------|
| Tab claimant name | 1 char | 12 chars on tab, full in tooltip | Truncate with ellipsis after 12 chars on the tab | — |
| Progress Overview claimant | 1 char | 18 chars | Truncate with ellipsis after 18 chars; full in tooltip | "unclaimed" (italic, text-tertiary) |
| Stale badge duration | — | 4 chars ("24h", "99d") | Cap at "99d" for claims older than 99 days | — |
| Progress Overview summary | — | one line | Wraps at narrow viewports to two lines; never truncated | — |
| ReadOnlyBanner message | — | two lines | Wraps; never truncated | — |
| Ratify comment | 0 chars (approve) / 10 chars (reject) | 280 chars | Character counter shown when > 240 chars | "Optional comment" (approve) / "Reason for rejection (required)" (reject) |
| Suggestion popover text | — | — | — | "Leave suggestion" |
| Tab label for child RFCs | 1 char | "RFC: {slug}" — slug truncated at 14 chars | Ellipsis on the slug portion only; "RFC:" prefix stays | — |

## Implementation Notes

- **Read-only stripe background.** The diagonal-stripe treatment on the read-only editor body is implemented as a repeating linear gradient, not an SVG overlay or background image. Use the exact value from the prototype (`repeating-linear-gradient(135deg, transparent 0 60px, rgba(255,255,255,0.008) 60px 61px)`) to match the rhythm. Any other angle or spacing reads as noise instead of "this is read-only."
- **Claim mutation is optimistic.** Every Claim / Release / Takeover click updates local state immediately and fires the mutation in the background. On server error, roll back the local state and show a toast. Don't block the UI waiting for the round trip — claims are reversible and the latency feels like lag otherwise.
- **Claim badge width.** Tabs in the unclaimed state are ~40% narrower than tabs with claimant badges. When the viewer claims a spec, the tab expands to accommodate the claimant name. This width transition is part of the state-change animation.
- **Stale clock is client-computed.** The server returns `last_activity_at` and a `now` reference; the client computes the stale duration for display. Do not poll the server for "is this stale yet" — staleness is lazy per the RFC.
- **Progress Overview row click semantics.** Clicking a row activates the tab, it does not navigate. Do not use an anchor tag (`<a>`); use a `<button>` with proper ARIA. An anchor would tempt users to right-click "open in new tab" which makes no sense for a tab-swap action.
- **CommitBar button morph.** The Commit → Ratify transition renders as two stacked elements with opposed opacities cross-fading, not a single element whose content changes. Single-element content changes produce a flicker on some browsers; stacked elements cross-fade cleanly.
- **Tab overflow with horizontal scroll.** When the tab bar scrolls, add `scroll-snap-type: x mandatory` so tabs snap to the edges when scrolled. Without snap the bar feels loose. The active tab should auto-`scrollIntoView({ inline: "nearest", behavior: "smooth" })` on activation.
- **Do: use `aria-live="polite"` for the read-only banner and stale badges.** Do not use `assertive` — a claim state change is informational, not urgent. Assertive live regions interrupt screen reader speech flow.
- **Do not reuse `SuggestionCard` from the parent spec for Progress Overview rows.** They look similar at first glance but the data models are different and the interactions are different. Duplicating the row primitive is worth it to keep each component focused.
- **Validation state source.** Read the existing `validation-state-{spec_type}.json` files from disk for the Progress Overview's validation column. Do not call a new GraphQL field for this; the file is already a first-class artifact per the parent ceremony design.

## Verification Criteria

- [ ] Tab bar renders five visually distinct claim states: mine, claimed-by-other, stale, unclaimed, committed. Visual regression snapshot covers all five.
- [ ] Claim and Release mutations fire optimistically; local state updates within 16ms of click. Server round trip does not block UI.
- [ ] A ceremony with roster size 1 renders the same tab bar chrome as a multi-actor ceremony. Test: Claim button exists on every unclaimed tab regardless of roster size; the DOM shape under `[data-claim-btn]` is identical for solo and multi-actor rosters.
- [ ] Non-claimant of a drafting tab sees the read-only stripe background, the ReadOnlyBanner (standard kind), and a disabled Commit button with "Claimed by {name}" caption.
- [ ] Non-claimant of a committed tab sees RatifyControl with current approval count and threshold. Author of the committed spec sees RatifyControl disabled with "You cannot ratify your own spec."
- [ ] Progress Overview row count equals the drafted-spec count from the filesystem (`draft-*.md` listing).
- [ ] Progress Overview status pills match the per-spec commit/ratification file state (derived per the RFC, not stored).
- [ ] Progress Overview renders 5 columns (Spec / Claimant / Validation / Suggestions / Status) for every ceremony, regardless of roster size.
- [ ] Summary line format is `N of M committed · K of M ratified` for every ceremony. Sole-actor ceremonies show the committed and ratified counts converging on the same number because auto-ratification fires inline at commit.
- [ ] Progress Overview default-open state: expanded when `drafted_specs.length > 3`, collapsed otherwise. Override persists in localStorage per feature.
- [ ] Stale badge duration updates on tab focus without a page reload, computed client-side against a server-supplied `now`.
- [ ] Tab bar horizontally scrolls at 7+ tabs on a 1024px viewport; activating a tab scrolls it into view via `scrollIntoView({ inline: "nearest" })`.
- [ ] Read-only banner glyph and left-border color switch between text-tertiary (standard) and amber (stale) based on `kind` prop.
- [ ] SuggestionPopover appears within 50ms of text selection in a read-only editor; dismisses on Escape, click-outside, or scroll.
- [ ] Keyboard navigation: arrow keys move focus between tabs; Enter activates; C claims; R releases. ProgressOverview rows reachable via Tab, activatable via Enter.
- [ ] All interactive components have visible focus indicators using `--color-accent` outline with 2px offset. Focus ring never hidden.
- [ ] Reduced motion: all transitions in the Motion table become instant when `prefers-reduced-motion: reduce` is active. Focus rings stay visible.
- [ ] No pure white (`#fff`) anywhere; brightest text token is `--color-text` (#e4e4e9).
- [ ] Accent color (`--color-accent`) used only on: mine-state claimant name, active-tab underline, Commit button, ProgressRow active-tab bar, SuggestionPopover button, selection highlight in editor. Audit fails if accent appears on any other element.
- [ ] No raw hex values, px font sizes, or un-tokenized colors in any new component file. Token audit passes.
- [ ] Contrast audit: every new text element meets WCAG AA against its background token. The one noted exception (claimant name text-tertiary on tab) is either bumped to text-secondary or documented as a reviewed trade-off.

## Figma / Visual Reference

No Figma source of truth for this spec. The [HTML prototype](../../working-docs/prototype-speed-define-ceremony-ownership.html) is the visual reference; its six scenes correspond one-to-one with the page-level states above. Where the prototype and this spec disagree, this spec wins for behavior, spacing, and token usage; the prototype wins for aesthetic ratios and the exact shape of the tab-bar chrome.

The prototype was built against the production design tokens in `dashboard/frontend/app/globals.css`, so anything you see there should render identically when implemented against the real tokens. A regression in that correspondence is a design bug.






