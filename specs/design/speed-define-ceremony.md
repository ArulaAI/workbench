# Design: The Define Ceremony

> See [product spec](../product/speed-define-ceremony.md) for product context.
> Design system: `dashboard/frontend/app/globals.css`

## Design Intent

**Direction:** The ceremony surface is an authoring environment, not a dashboard. It should feel like a focused writing tool with intelligence alongside: calm, spacious, and quiet until the system has something to say. The closest reference is a code editor with an AI sidebar (Cursor, Copilot Chat) crossed with the existing SPEED dashboard's information density. The context panel is always present but never competes with the editor for attention.

**Do not:** Use rounded playful elements. Apply accent color to anything other than validation pass indicators and the Commit action. Use pure white (`#fff`) anywhere. Add gradients, decorative illustrations, or empty-state artwork. Use borders without paired shadows on elevated elements (use the `.surface` class). Make the context panel visually louder than the editor. Use skeleton loaders that pulse (use opacity fade instead).

## Pages / Routes

| Route | User Flow | Description |
|-------|-----------|-------------|
| `/define` | Reading the portfolio | Existing portfolio mode (three-column grid). Unchanged. |
| `/define/new` | Declaring intent and receiving context | Intent input, context delivery, then transitions to ceremony editor. Bootstrap flow intercepts here when cold start is detected. |
| `/define/:feature` | Authoring with context, Committing the spec | Ceremony editor: context panel + spec editor + validation panel. Also serves contributor view (read-only with suggestions). |
| `/define/:feature/review` | Approver ratification (MP) | Ratification view: read-only spec, context snapshot, validation state, suggestion summary, approve/reject controls. |
| `/define/:feature/history` | Viewing historical context | Historical context view: persisted context package from when the spec was authored, with comparison against current codebase state. Accessible from the ceremony editor and the portfolio grid for completed features. |

## Layout Structure

### Global Layout

The dashboard uses the skinny IconRail navigation (52px fixed, left side) — not a full sidebar. Content fills the remaining viewport to the right. The ceremony surface does not modify the global layout. All routes render within the existing content region. The IconRail must remain visible during the ceremony to allow navigation to other dashboard pages.

### Regions

| Region ID | Position | Width | Internal Layout | Scroll | Closable | Shortcut |
|-----------|----------|-------|-----------------|--------|----------|----------|
| intent-input | Content area (`/define/new`) | Full content width, max 720px centered | Vertical stack, centered | No | No | — |
| context-panel | Left side of ceremony editor | 320px fixed (48px collapsed) | Vertical stack, collapsible sections | Yes (independent) | Yes (collapses to icon rail) | Cmd+Shift+C |
| editor-area | Center of ceremony editor | Fluid (fills remaining) | Vertical stack: tab bar + editor + validation gutter | Yes (independent) | No (always visible) | — |
| validation-gutter | Bottom of editor-area | Full editor width, 40px collapsed / 200px expanded | Horizontal flex, expandable | No (editor scrolls above) | Yes (collapses to badge row) | Cmd+Shift+V |
| suggestion-sidebar | Right side of ceremony editor | 280px, toggleable | Vertical stack of suggestion cards | Yes (independent) | Yes (hidden by default, slides in) | Cmd+Shift+S |
| bootstrap-flow | Content area (`/define/new`, cold start) | Full content width, max 640px centered | Stepped wizard: vertical stack with progress indicator | Yes (page scroll) | No | — |
| history-view | Content area (`/define/:feature/history`) | Full content width, two equal columns with 1px divider | Two-column: snapshot (left), current (right). Each column scrolls independently. | Yes (per column) | No | — |

## Component Inventory

All new ceremony components live in `dashboard/frontend/components/define/ceremony/`. Modified components stay in their existing locations.

| Component ID | Type | Location | Parent ID | Description |
|--------------|------|----------|-----------|-------------|
| IntentInput | new | `ceremony/IntentInput.tsx` | intent-input | Free-text input for declaring intent. Large, minimal, single field with placeholder guidance. |
| ContextPanel | modified | `editor/IntelPanel.tsx` (existing) | context-panel | Extends the existing IntelPanel which already has collapsible sections for Codebase, Conventions, Lessons, Related Specs, and Traceability. Ceremony mode adds three sections (Defects, Vision Status, Audit History) and switches the data source from current-spec context to intent-scoped context package. Add a `mode` prop: `"editor"` (existing behavior) or `"ceremony"` (context package source, additional sections). Existing IntelPanel sections in the Reference tab are: Codebase, Conventions, Lessons, Dependencies, See Also, Shared Infrastructure, Parent RFC. The Health tab has Traceability, Observations, Tasks, Highlights, Contract. |
| ContextSection | existing | `editor/IntelPanel.tsx` | context-panel | The `Section` component inside IntelPanel. Already implements collapsible header with icon + title + item count. No changes needed. |
| SpecEditor | existing | `editor/SpecEditor.tsx` | editor-area | Markdown editor. No ceremony-specific modifications. The ceremony page composes SpecEditor with context, validation, and suggestion surfaces around it. Read-only contributor mode uses the existing `readOnly` prop. |
| EditorTabBar | modified | `editor/EditorTabs.tsx` (existing) | editor-area | Tab bar for multi-spec editing. Adds child RFC tabs for multi-RFC topologies. Adds suggestion sidebar toggle with unresolved count badge. |
| CeremonyLayout | new | `ceremony/CeremonyLayout.tsx` | content area | Page-level layout that composes SpecEditor, ContextPanel, ValidationGutter, SuggestionSidebar, and CommitBar into the three-panel ceremony experience. This is the integration layer — individual components don't know they're in a ceremony. |
| ValidationGutter | new | `ceremony/ValidationGutter.tsx` | validation-gutter | Collapsed: summary badges (pass/warn/fail counts per dimension). Expanded: full validation details per dimension. |
| ValidationBadge | new | `ceremony/ValidationBadge.tsx` | validation-gutter | Single dimension indicator: template, structure, cross-spec, codebase, sizing, vision. |
| SuggestionSidebar | new | `ceremony/SuggestionSidebar.tsx` | suggestion-sidebar | List of contributor suggestions with resolution controls. |
| SuggestionCard | new | `ceremony/SuggestionCard.tsx` | suggestion-sidebar | Individual suggestion: contributor avatar/name, section reference, suggestion text, accept/dismiss/reply actions. |
| CommitBar | new | `ceremony/CommitBar.tsx` | editor-area | Fixed bottom bar: validation summary, unresolved suggestion count, Commit button. |
| ScopeRefineBar | new | `ceremony/ScopeRefineBar.tsx` | context-panel | Appears at top of context panel when context is delivered. Shows current intent with edit affordance for refinement. |
| BootstrapWizard | new | `ceremony/BootstrapWizard.tsx` | bootstrap-flow | Stepped flow: vision generation/authoring, convention extraction review, persona-specific convention prompts. |
| VisionDraftEditor | new | `ceremony/VisionDraftEditor.tsx` | bootstrap-flow | Split view: system-generated draft on left, editable version on right. |
| ConventionReview | new | `ceremony/ConventionReview.tsx` | bootstrap-flow | List of system-derived conventions with accept/reject per item. |
| SuggestionComposer | new | `ceremony/SuggestionComposer.tsx` | editor-area | Inline suggestion input that appears when a contributor selects a section of the spec. Anchored to the selected section. Text input with submit/cancel. |
| ContributorBanner | new | `ceremony/ContributorBanner.tsx` | editor-area | Top bar shown in contributor view. Displays: spec author name, ceremony status, "You are viewing as a contributor" label, suggestion count for this contributor. |
| RatificationView | new | `ceremony/RatificationView.tsx` | content area | Page layout for approvers. Two-panel: left shows read-only spec with context panel, right shows ratification controls. |
| RatificationSummary | new | `ceremony/RatificationSummary.tsx` | RatificationView | Validation state summary, suggestion resolution history (N received, N accepted, N dismissed with expandable reasons), context snapshot reference. |
| RatificationControls | new | `ceremony/RatificationControls.tsx` | RatificationView | Approve/reject buttons with confirmation dialog. Shows current approval count vs. threshold. Disabled for the spec author. |
| HistoricalContextView | new | `ceremony/HistoricalContextView.tsx` | content area | Page layout for `/define/:feature/history`. Two-column comparison. Header shows feature name, ceremony author, committed date, and a label indicating this is a historical view. |
| ContextSnapshot | new | `ceremony/ContextSnapshot.tsx` | history-view (left) | Renders a frozen `ContextPackage` from `context-package.json`. Same collapsible sections as ContextPanel (Codebase, Learnings, Defects, Knowledge, Vision Status, Related Features, Audit History) but read-only and with a "Snapshot from {date}" header. Reuses existing `ContextSection` component. |
| ContextDiff | new | `ceremony/ContextDiff.tsx` | history-view (right) | Shows what changed since the spec was authored. Groups changes by source: files added/removed/modified, new defects or resolved defects, changed conventions, vision status change. Each group is a collapsible section. Items not present in the snapshot but present now are marked "New". Items present in the snapshot but gone now are marked "Removed". |

### Component Props

#### IntentInput

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| onSubmit | (intent: string) => void | required | Called when author submits intent text |
| placeholder | string | "What do you want to build?" | Guidance text in empty state |
| disabled | boolean | false | True during context assembly |

#### ContextSection

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| title | string | required | Section header text |
| icon | ReactNode | required | Section icon (monochrome, 16px) |
| count | number | 0 | Item count displayed in header |
| defaultOpen | boolean | false | Initial collapsed/expanded state |
| children | ReactNode | required | Section content |

#### ValidationBadge

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| dimension | string | required | "template" \| "structure" \| "cross-spec" \| "codebase" \| "sizing" \| "vision" |
| status | string | required | "pass" \| "warn" \| "fail" \| "pending" |
| count | number | 0 | Number of issues (shown when > 0) |

#### SuggestionCard

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| suggestion | Suggestion | required | Suggestion data: id, author, section, text, status, resolution |
| onAccept | (id: string) => void | required | Accept callback |
| onDismiss | (id: string, reason: string) => void | required | Dismiss callback (reason required) |
| onReply | (id: string, text: string) => void | required | Reply callback |
| isAuthor | boolean | required | True if current user is the spec author (shows resolution controls) |

#### CommitBar

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| validationSummary | ValidationSummary | required | Pass/warn/fail counts per dimension |
| unresolvedCount | number | 0 | Unresolved suggestion count |
| templateConformant | boolean | required | Whether spec passes template check |
| onCommit | () => void | required | Commit callback |
| isMultiplayer | boolean | false | Shows "Commit & Propose" label in MP mode, "Commit" in SP |

#### ContextPanel (ceremony mode additions)

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| mode | "editor" \| "ceremony" | "editor" | Editor mode uses existing IntelPanel behavior. Ceremony mode adds Defects, Vision Status, Audit History sections and reads from context package. |
| contextPackage | ContextPackage \| null | null | Intent-scoped context data. Required when mode is "ceremony". |
| loading | boolean | false | True during context assembly. Shows progressive source completion. |
| sources | SourceStatus[] | [] | Per-source loading status: { name: string, status: "pending" \| "complete" \| "error" } |

#### CeremonyLayout

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| feature | string | required | Feature name (used for routes, artifact paths) |
| contextPackage | ContextPackage \| null | null | Delivered context. Null during assembly. |
| spec | SpecDraft | required | Current spec content and metadata |
| validation | ValidationState | required | Current validation state across all dimensions |
| suggestions | Suggestion[] | [] | All suggestions for this ceremony |
| isAuthor | boolean | required | Whether current user owns this ceremony |
| isMultiplayer | boolean | false | Multiplayer mode flag |
| onCommit | () => void | required | Commit callback |

#### ValidationGutter

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| dimensions | ValidationDimension[] | required | Array of { name, status, issues[] } for each validation dimension |
| expanded | boolean | false | Whether gutter is expanded to show full details |
| onToggle | () => void | required | Toggle expanded/collapsed |
| onIssueClick | (issueId: string) => void | required | Scrolls editor to the corresponding inline marker |

#### SuggestionSidebar

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| suggestions | Suggestion[] | required | All suggestions for the ceremony |
| isAuthor | boolean | required | Shows resolution controls when true, compose affordance when false |
| onAccept | (id: string) => void | required | Accept callback (author only) |
| onDismiss | (id: string, reason: string) => void | required | Dismiss callback (author only) |
| onReply | (id: string, text: string) => void | required | Reply callback (author or contributor) |

#### ScopeRefineBar

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| intent | string | required | Current intent text |
| onRefine | (newIntent: string) => void | required | Called when author submits refined intent. Triggers context re-assembly. |
| loading | boolean | false | True during re-assembly after refinement |

#### SuggestionComposer

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| sectionId | string | required | ID of the spec section this suggestion is anchored to |
| sectionTitle | string | required | Display name of the anchored section (shown in composer header) |
| onSubmit | (text: string) => void | required | Called when contributor submits suggestion |
| onCancel | () => void | required | Closes composer without submitting |

#### ContributorBanner

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| authorName | string | required | Name of the spec author |
| ceremonyStatus | "drafting" \| "committed" \| "ratifying" | required | Current ceremony state |
| suggestionCount | number | 0 | Number of suggestions this contributor has left |

#### BootstrapWizard

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| steps | BootstrapStep[] | required | Array of { id, title, status: "pending" \| "current" \| "complete" } |
| currentStep | string | required | Active step ID |
| onStepComplete | (stepId: string, data: unknown) => void | required | Called when a step is completed with its output data |
| onSkip | (stepId: string) => void | required | Called when author skips an optional step |
| graphBuildStatus | "building" \| "complete" \| "error" | required | Background semantic graph build progress |

#### VisionDraftEditor

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| generatedDraft | string \| null | null | LLM-generated vision text. Null if author chose "write from scratch". |
| onCommitVision | (content: string) => void | required | Writes vision to `specs/product/overview.md` |
| generating | boolean | false | True while LLM is generating draft |
| onRegenerate | () => void | required | Triggers re-generation of draft |

#### ConventionReview

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| derivedConventions | Convention[] | required | System-extracted conventions from codebase |
| onAccept | (id: string) => void | required | Accept a derived convention |
| onReject | (id: string) => void | required | Reject a derived convention |
| onAcceptAll | () => void | required | Accept all remaining conventions |

#### RatificationView

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| feature | string | required | Feature name |
| spec | SpecDraft | required | Committed spec (read-only) |
| contextPackage | ContextPackage | required | Context snapshot from commitment |
| commitment | CommitmentRecord | required | Who committed, when, validation state at commitment |
| isAuthor | boolean | required | True if viewer is the spec author (disables approve/reject) |

#### RatificationSummary

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| validationState | ValidationState | required | Validation state at commitment time |
| suggestionHistory | SuggestionHistory | required | { received: number, accepted: number, dismissed: { count: number, reasons: string[] } } |
| contextSnapshotRef | string | required | Path to persisted context package for reference |
| approvalCount | number | 0 | Current number of approvals |
| approvalThreshold | number | 1 | Required approvals (from speed.toml) |
| verdicts | Verdict[] | [] | All submitted verdicts: { actor, verdict, timestamp } |

#### RatificationControls

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| onApprove | () => void | required | Approve callback |
| onReject | (comment?: string) => void | required | Reject callback with optional comment |
| disabled | boolean | false | True when viewer is spec author |
| disabledReason | string | "" | "You cannot ratify your own spec" |
| hasVoted | boolean | false | True if this actor already submitted a verdict |
| approvalCount | number | 0 | Current approvals |
| approvalThreshold | number | 1 | Required threshold |

#### EditorTabBar (ceremony additions)

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| suggestionCount | number | 0 | Unresolved suggestion count, shown as badge on sidebar toggle icon |
| onToggleSuggestions | () => void | — | Toggles suggestion sidebar visibility |
| childRfcTabs | { id: string, label: string }[] | [] | Additional tabs for child RFCs in multi-RFC topology |

#### HistoricalContextView

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| feature | string | required | Feature name |
| snapshot | ContextPackage | required | Persisted context package from commit time |
| current | ContextPackage \| null | null | Current context for the same codebase area. Null if re-assembly fails or is skipped. |
| ceremony | CeremonyInfo | required | Ceremony metadata (author, committed date, status) |

#### ContextSnapshot

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| contextPackage | ContextPackage | required | The frozen context package |
| assembledAt | string | required | ISO 8601 timestamp shown in the header |

#### ContextDiff

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| snapshot | ContextPackage | required | Context at commit time |
| current | ContextPackage | required | Current context for the same area |

## Spacing

| Context | Token | Usage |
|---------|-------|-------|
| Page margin | 24px | Outer padding for all ceremony routes |
| Context panel padding | 16px | Internal padding for context-panel region |
| Context section gap | 12px | Between collapsible sections in context panel |
| Context section internal | 8px | Between items within a section |
| Editor padding | 20px | Internal padding for the editor area |
| Editor line spacing | Handled by editor | Markdown editor manages its own line height |
| Tab bar height | 40px | Height of EditorTabBar |
| Validation gutter collapsed | 40px | Height when collapsed (badges only) |
| Validation gutter expanded | 200px | Height when expanded (full details) |
| Suggestion card gap | 8px | Between suggestion cards |
| Suggestion card padding | 12px | Internal padding per card |
| Commit bar height | 52px | Fixed bottom bar |
| Bootstrap step gap | 24px | Between wizard steps |
| Intent input padding | 32px 24px | Generous padding around the intent field |
| Scope refine bar height | 36px | Compact bar at top of context panel |
| Scope refine bar padding | 8px 16px | Internal padding |
| Contributor banner height | 40px | Full-width bar at top of contributor view |
| Contributor banner padding | 8px 20px | Internal padding |
| Suggestion composer padding | 12px | Internal padding of anchored composer |
| Suggestion composer gap | 8px | Between composer elements (header, input, buttons) |
| Ratification summary padding | 20px | Internal padding of summary panel |
| Ratification summary section gap | 16px | Between summary sections (validation, suggestions, context) |
| Ratification controls padding | 16px 20px | Internal padding of controls area |
| Ratification controls button gap | 12px | Between approve and reject buttons |
| Dismiss reason dialog padding | 20px | Internal padding |
| Dismiss reason dialog width | 400px | Fixed width modal |
| Commit dialog padding | 24px | Internal padding |
| Commit dialog width | 480px | Fixed width modal |
| Validation inline marker gutter | 4px | Left margin for marker border |
| Cross-spec flag icon size | 16px | Gutter icon dimensions |
| Convention review item padding | 12px 16px | Per-convention row |
| Convention review item gap | 8px | Between convention items |
| Vision draft pane gap | 1px | Divider width between left/right panes |
| Vision draft pane padding | 20px | Internal padding per pane |
| History view column gap | 1px | Divider between snapshot and current columns |
| History view column padding | 20px | Internal padding per column |
| History view header height | 52px | Feature name, author, date bar |
| History view header padding | 12px 20px | Internal padding |
| Diff group gap | 12px | Between change groups (files, defects, conventions) |
| Diff item gap | 4px | Between individual change items within a group |

## Typography

| Element | Role | Family | Size | Weight | Line-Height | Color |
|---------|------|--------|------|--------|-------------|-------|
| Intent input text | custom | font-sans | 18px | 400 | 1.5 | text |
| Intent placeholder | custom | font-sans | 18px | 400 | 1.5 | text-tertiary |
| Context section title | type-section-header | font-sans | 13px | 600 | 1.4 | text |
| Context section count | type-mono-value | font-mono | 13px | 500 | 1.4 | text-secondary |
| Context item text | type-body | font-sans | 13px | 400 | 1.5 | text-secondary |
| Context code reference | type-mono-value | font-mono | 13px | 500 | 1.4 | accent |
| Editor spec content | type-body | font-sans | 13px | 400 | 1.5 | text |
| Editor heading (h2) | type-section-title | font-sans | 15px | 600 | 1.4 | text |
| Editor heading (h3) | type-section-header | font-sans | 13px | 600 | 1.4 | text |
| Editor template placeholder | type-body | font-sans | 13px | 400 | 1.5 | text-tertiary |
| Tab label (active) | type-cell-label | font-sans | 12px | 500 | 1.4 | text |
| Tab label (inactive) | type-cell-label | font-sans | 12px | 500 | 1.4 | text-secondary |
| Validation dimension label | type-badge | font-sans | 11px | 500 | 1 | text-secondary |
| Validation issue text | type-body | font-sans | 13px | 400 | 1.5 | text-secondary |
| Suggestion author | type-cell-label | font-sans | 12px | 500 | 1.4 | text |
| Suggestion text | type-body | font-sans | 13px | 400 | 1.5 | text-secondary |
| Suggestion section ref | type-caption | font-sans | 11px | 400 | 1.4 | text-tertiary |
| Commit button label | type-badge | font-sans | 13px | 600 | 1 | bg (on accent) |
| Unresolved count | type-mono-value | font-mono | 13px | 500 | 1.4 | amber |
| Scope refine intent text | type-body | font-sans | 13px | 400 | 1.5 | text |
| Bootstrap step title | type-section-title | font-sans | 15px | 600 | 1.4 | text |
| Bootstrap step description | type-body | font-sans | 13px | 400 | 1.5 | text-secondary |
| Bootstrap progress label | type-caption | font-sans | 11px | 400 | 1.4 | text-tertiary (pending), text (current), accent (complete) |
| Contributor banner label | type-badge | font-sans | 11px | 500 | 1 | amber |
| Contributor banner author name | type-cell-label | font-sans | 12px | 500 | 1.4 | text |
| Contributor banner status | type-caption | font-sans | 11px | 400 | 1.4 | text-secondary |
| Contributor banner suggestion count | type-mono-value | font-mono | 13px | 500 | 1.4 | text-secondary |
| Suggestion composer header | type-cell-label | font-sans | 12px | 500 | 1.4 | text |
| Suggestion composer input | type-body | font-sans | 13px | 400 | 1.5 | text |
| Suggestion composer section ref | type-caption | font-sans | 11px | 400 | 1.4 | text-tertiary |
| Suggestion composer button | type-badge | font-sans | 11px | 500 | 1 | accent (submit), text-secondary (cancel) |
| Ratification summary heading | type-section-header | font-sans | 13px | 600 | 1.4 | text |
| Ratification summary stat value | type-mono-value | font-mono | 13px | 500 | 1.4 | text |
| Ratification summary stat label | type-caption | font-sans | 11px | 400 | 1.4 | text-tertiary |
| Ratification dismiss reason | type-body | font-sans | 13px | 400 | 1.5 | text-secondary |
| Ratification approval count | type-kpi-value | font-mono | 28px | 600 | 1.1 | accent (met), text (not met) |
| Ratification threshold label | type-kpi-label | font-sans | 11px | 500 | 1.4 | text-secondary |
| Ratify button label | type-badge | font-sans | 13px | 600 | 1 | bg (on emerald approve), red (reject outline) |
| Validation inline marker tooltip | type-caption | font-sans | 11px | 400 | 1.4 | text |
| Cross-spec flag tooltip | type-body | font-sans | 13px | 400 | 1.5 | text |
| Dismiss reason dialog title | type-section-header | font-sans | 13px | 600 | 1.4 | text |
| Dismiss reason dialog input | type-body | font-sans | 13px | 400 | 1.5 | text |
| Dismiss reason validation error | type-caption | font-sans | 11px | 400 | 1.4 | red |
| Commit dialog title | type-section-title | font-sans | 15px | 600 | 1.4 | text |
| Commit dialog body | type-body | font-sans | 13px | 400 | 1.5 | text-secondary |
| Commit dialog button | type-badge | font-sans | 13px | 600 | 1 | bg (on accent), text-secondary (cancel) |
| Convention review item text | type-body | font-sans | 13px | 400 | 1.5 | text-secondary |
| Convention review source | type-caption | font-sans | 11px | 400 | 1.4 | text-tertiary |
| Vision draft label (left pane) | type-badge | font-sans | 11px | 500 | 1 | text-tertiary |
| Vision draft label (right pane) | type-badge | font-sans | 11px | 500 | 1 | text |
| Vision draft content | type-body | font-sans | 13px | 400 | 1.5 | text |
| History header feature name | type-section-title | font-sans | 15px | 600 | 1.4 | text |
| History header metadata | type-caption | font-sans | 11px | 400 | 1.4 | text-tertiary |
| History snapshot label | type-badge | font-sans | 11px | 500 | 1 | text-tertiary |
| History snapshot date | type-mono-value | font-mono | 13px | 500 | 1.4 | text-secondary |
| Diff group header | type-section-header | font-sans | 13px | 600 | 1.4 | text |
| Diff item text | type-body | font-sans | 13px | 400 | 1.5 | text-secondary |
| Diff "New" badge | type-badge | font-sans | 11px | 500 | 1 | emerald |
| Diff "Removed" badge | type-badge | font-sans | 11px | 500 | 1 | red |
| Diff "Changed" badge | type-badge | font-sans | 11px | 500 | 1 | amber |

## Color Application

| Element | Property | Token | Notes |
|---------|----------|-------|-------|
| Ceremony page background | background | bg | Base layer |
| Context panel background | background | bg-elevated | Slightly raised from page |
| Editor background | background | bg-card | Primary editing surface |
| Suggestion sidebar background | background | bg-elevated | Matches context panel |
| Intent input background | background | bg-card | Surface class |
| Validation badge (pass) | color | emerald | |
| Validation badge (warn) | color | amber | |
| Validation badge (fail) | color | red | |
| Validation badge (pending) | color | text-tertiary | |
| Validation badge background | background | 12% opacity of status color | Matches status-*-bg pattern |
| Commit button (enabled) | background | accent | Primary action — accent is appropriate here |
| Commit button (blocked) | background | text-tertiary | Template non-conformance or other blocker |
| Suggestion card surface | background | bg-card | Surface class |
| Suggestion accepted indicator | color | emerald | |
| Suggestion dismissed indicator | color | text-tertiary | |
| Suggestion unresolved indicator | color | amber | |
| Cross-spec contradiction flag | color | red | Inline in editor |
| Cross-spec coverage gap flag | color | amber | Inline in editor |
| Context code references | color | accent | File paths, function names |
| Scope refine edit icon | color | text-secondary | Hover → text |
| Bootstrap progress indicator (complete) | color | accent | |
| Bootstrap progress indicator (current) | color | text | |
| Bootstrap progress indicator (pending) | color | text-tertiary | |
| Tab active indicator | border-bottom | accent | 2px bottom border |
| Tab inactive | border-bottom | transparent | |
| Tab suggestion badge | background, color | amber, bg | Unresolved count badge on sidebar toggle |
| Contributor banner background | background | bg-elevated | Full-width bar at top of contributor view |
| Contributor banner label | color | amber | "You are viewing as a contributor" |
| Contributor banner author | color | text | Spec author name |
| Suggestion composer background | background | bg-card | Surface class, anchored to section |
| Suggestion composer border | border | accent-glow | Visible anchor to selected section |
| Suggestion composer submit | background, color | accent, bg | Submit button |
| Suggestion composer cancel | background, color | transparent, text-secondary | Cancel button |
| Ratification view background | background | bg | Base layer, same as ceremony page |
| Ratification summary background | background | bg-elevated | Summary panel |
| Ratification approval count (met) | color | accent | Threshold reached |
| Ratification approval count (not met) | color | text | Below threshold |
| Ratification verdict approve | color | emerald | Per-verdict indicator |
| Ratification verdict reject | color | red | Per-verdict indicator |
| Validation inline marker (error) | border-left | red | 2px left border on affected line |
| Validation inline marker (warning) | border-left | amber | 2px left border on affected line |
| Validation inline marker (info) | border-left | blue | 2px left border on affected line |
| Validation inline marker tooltip | background | bg-card | Tooltip surface |
| Cross-spec flag icon | color | red (contradiction), amber (gap) | Small icon in editor gutter |
| Cross-spec flag highlight | background | red 4% (contradiction), amber 4% (gap) | Subtle background highlight on affected lines |
| Dismiss reason dialog background | background | bg-card | Modal surface |
| Dismiss reason dialog overlay | background | rgba(0,0,0,0.5) | Backdrop |
| Dismiss reason error text | color | red | Validation error for < 10 chars |
| Commit dialog background | background | bg-card | Modal surface |
| Commit dialog overlay | background | rgba(0,0,0,0.5) | Backdrop |
| Convention review accept | color | emerald | Accept indicator |
| Convention review reject | color | red | Reject indicator |
| Convention review item background | background | bg-card | Per-convention row |
| Vision draft left pane background | background | bg-elevated | Read-only generated draft |
| Vision draft right pane background | background | bg-card | Editable version |
| Vision draft divider | border | border | Vertical divider between panes |
| History view background | background | bg | Base layer |
| History snapshot column | background | bg-elevated | Left column, slightly raised |
| History current column | background | bg-card | Right column, primary surface |
| History divider | border | border | 1px vertical divider |
| History header background | background | bg-elevated | Full-width bar |
| Diff "New" badge | background, color | emerald 12%, emerald | Added since snapshot |
| Diff "Removed" badge | background, color | red 12%, red | Gone since snapshot |
| Diff "Changed" badge | background, color | amber 12%, amber | Modified since snapshot |
| Diff unchanged item | color | text-tertiary | Present in both, no change |

## Elevation & Depth

| Element | Elevation Level | Treatment |
|---------|----------------|-----------|
| Page background | 0 (base) | Flat, `bg` |
| Context panel | 1 | `surface-elevated` class |
| Editor area | 2 | `surface` class |
| Suggestion sidebar | 1 | `surface-elevated` class |
| Suggestion cards | 2 | `surface` class |
| Validation gutter (expanded) | 2 | `surface` class, sits above editor scroll |
| Commit bar | 3 | `surface` class + stronger shadow (fixed position, must read above editor) |
| Intent input card | 2 | `surface` class, centered on page |
| Bootstrap wizard card | 2 | `surface` class |
| Contributor banner | 1 | `surface-elevated` class, full width, sits above editor |
| Suggestion composer | 2 | `surface` class, positioned adjacent to selected section |
| Ratification summary panel | 1 | `surface-elevated` class |
| Ratification controls | 1 | `surface-elevated` class, sits below summary |
| Dismiss reason dialog | 3 | `surface` class + shadow-lg, modal overlay |
| Commit confirmation dialog | 3 | `surface` class + shadow-lg, modal overlay |
| Validation inline marker tooltip | 3 | `surface` class + shadow-md, appears on hover |
| Cross-spec flag tooltip | 3 | `surface` class + shadow-md, appears on hover |
| Dropdown menus | 3 | shadow-md, higher z-index |
| History view background | 0 (base) | Flat, `bg` |
| History snapshot column | 1 | `surface-elevated` class |
| History current column | 2 | `surface` class |
| History header | 1 | `surface-elevated` class, full width |

## States

### Page-Level States

#### Empty State (Intent Input `/define/new`)
The author sees a centered IntentInput card on the base background. No sidebar, no editor, no validation. The card contains: the intent field with placeholder text "What do you want to build?", and below it a one-line caption: "Describe your intent and SPEED will deliver context from your codebase."

#### Loading State (Context Assembly)
After intent is submitted, the IntentInput card transitions to a loading state: the input field becomes read-only, a subtle progress indicator appears below it showing which context sources are assembling (semantic graph, learnings, defects...). Each source transitions from pending (text-tertiary) to complete (accent) as it finishes. Partial context is visible in a growing context panel before full assembly completes.

#### Populated State (Ceremony Editor)
Three-panel layout: context panel (left), editor (center), suggestion sidebar (right, hidden by default until first suggestion arrives). Validation gutter collapsed at bottom of editor. Commit bar fixed at bottom.

#### Error State
Context assembly failure: inline error in the IntentInput card with retry affordance. Partial failures (one source failed): context panel shows the section with an error indicator and the rest loads normally. Editor validation failure: inline markers in the editor, validation gutter shows details.

#### Bootstrap State (`/define/new`, cold start)
Instead of the IntentInput card, the bootstrap wizard occupies the page. Stepped flow: vision (generate or write) → convention review (system-derived) → convention supplement (persona prompts). Each step is a `.surface` card. Progress indicator at top shows completed/current/pending steps.

#### History View States (`/define/:feature/history`)

**Loading**: Both columns show skeleton placeholders (opacity fade). The snapshot column loads from `context-package.json` (fast, single file read). The current column loads from a fresh context assembly for the same scoped area (slower, same pipeline as `declareIntent`).

**Populated**: Two-column layout. Left shows the frozen snapshot with "Snapshot from {date}" header. Right shows the diff grouped by change type.

**No Snapshot**: Feature exists but has no persisted `context-package.json` (ceremony was created before context persistence existed, or context assembly failed at commit time). Show: "No context snapshot available for this feature. Context persistence was not active when this spec was authored."

**Current Assembly Failed**: Snapshot loads successfully but current context re-assembly fails (e.g., semantic graph deleted, project restructured). Left column shows the snapshot. Right column shows: "Current context could not be assembled. The snapshot is still available for reference." No diff rendered.

### Interactive Element States

| Component | Enabled | Hover | Focus | Pressed | Disabled | Loading |
|-----------|---------|-------|-------|---------|----------|---------|
| IntentInput | bg: bg-card, border: border | border: accent-glow | ring: accent, offset: 2px | — | bg: bg-card, opacity: 0.4, cursor: not-allowed | Input read-only, progress indicator below |
| CommitButton | bg: accent, text: bg | bg: accent, opacity: 0.9 | ring: accent, offset: 2px | scale: 0.98 | bg: text-tertiary, cursor: not-allowed | Spinner replaces label, width locked |
| ContextSection chevron | color: text-tertiary | color: text-secondary | ring: accent, offset: 2px | — | — | — |
| SuggestionCard accept | color: emerald, bg: transparent | bg: emerald 8% | ring: accent | — | — | — |
| SuggestionCard dismiss | color: text-secondary, bg: transparent | bg: red 8% | ring: accent | — | — | — |
| EditorTab (inactive) | color: text-secondary, border-bottom: transparent | color: text, bg: bg-card-hover | ring: accent | — | — | — |
| EditorTab (active) | color: text, border-bottom: accent | — | ring: accent | — | — | — |
| ScopeRefineEdit | opacity: 0 | opacity: 1, color: text-secondary | ring: accent | — | — | — |
| ValidationGutter toggle | color: text-secondary | color: text | ring: accent | — | — | — |
| ValidationGutter validate button | bg: transparent, text: accent, border: accent | bg: accent-dim | ring: accent | scale: 0.98 | — | Spinner replaces label, width locked |
| ValidationBadge (stale) | color: text-3, opacity: 0.5 | opacity: 0.7 | — | — | — | — |
| SuggestionComposer submit | bg: accent, text: bg | bg: accent, opacity: 0.9 | ring: accent | scale: 0.98 | bg: text-tertiary, cursor: not-allowed (< 10 chars) | — |
| SuggestionComposer cancel | bg: transparent, text: text-secondary | text: text | ring: accent | — | — | — |
| SuggestionComposer input | bg: bg-elevated, border: border | border: accent-glow | ring: accent, offset: 2px | — | — | — |
| ContributorBanner | bg: bg-elevated, non-interactive | — | — | — | — | — |
| ConventionReview accept | color: emerald, bg: transparent | bg: emerald 8% | ring: accent | — | — | — |
| ConventionReview reject | color: text-secondary, bg: transparent | bg: red 8% | ring: accent | — | — | — |
| ConventionReview acceptAll | bg: accent, text: bg | bg: accent, opacity: 0.9 | ring: accent | scale: 0.98 | — | — |
| VisionDraftEditor regenerate | bg: transparent, text: text-secondary | text: text | ring: accent | — | — | Spinner replaces icon |
| SuggestionCard reply input | bg: bg-elevated, border: border | border: accent-glow | ring: accent | — | — | — |
| SuggestionSidebar toggle | color: text-secondary | color: text | ring: accent | — | — | — |
| RatifyApprove | bg: emerald, text: bg | bg: emerald, opacity: 0.9 | ring: emerald | scale: 0.98 | bg: text-tertiary, cursor: not-allowed (is author or already voted) | — |
| RatifyReject | bg: transparent, border: red, text: red | bg: red 8% | ring: red | scale: 0.98 | bg: text-tertiary, cursor: not-allowed (is author or already voted) | — |
| DismissReasonSubmit | bg: text-secondary, text: bg | bg: text, opacity: 0.9 | ring: accent | scale: 0.98 | bg: text-tertiary, cursor: not-allowed (< 10 chars) | — |
| CommitDialogConfirm | bg: accent, text: bg | bg: accent, opacity: 0.9 | ring: accent | scale: 0.98 | — | Spinner replaces label |
| CommitDialogCancel | bg: transparent, text: text-secondary | text: text | ring: accent | — | — | — |
| CrossSpecFlag | color: red/amber, opacity: 0.7 | opacity: 1, tooltip appears | ring: accent | — | — | — |
| ValidationInlineMarker | border-left: 2px red/amber/blue | tooltip appears on hover | ring: accent | — | — | — |

## Data Binding

| Element | Source Field | Format | Constraints |
|---------|-------------|--------|-------------|
| Intent text | intent.text | string | Free-form, no length limit. Persisted to `intent.txt`. |
| Context: codebase items | contextPackage.codebase[] | structured | File path (mono, accent) + description (body). Max 20 visible, "Show all N" overflow. |
| Context: learnings | contextPackage.learnings[] | structured | Convention text + source feature name. |
| Context: defects | contextPackage.defects[] | structured | Severity badge + name. Same rendering as landing DefectRow. |
| Context: vision status | contextPackage.visionStatus | "missing" \| "placeholder" \| "defined" | Missing → warning banner. Placeholder → amber indicator. Defined → emerald indicator. |
| Context: related features | contextPackage.relatedFeatures[] | structured | Feature name + state badge + link to Define portfolio row. |
| Spec content | spec.content | markdown | Full spec rendered in editor. |
| Validation dimensions | validation.dimensions[] | structured | Dimension name + status + issue count + issue details (expanded). |
| Suggestion list | suggestions[] | structured | Author name, section reference, text, status (unresolved/accepted/dismissed), resolution details. |
| Commit bar: validation summary | validation.summary | structured | Count of pass/warn/fail per dimension. |
| Commit bar: unresolved count | suggestions.filter(unresolved).length | number | Amber when > 0. |
| Context: audit history | contextPackage.auditHistory[] | structured | Feature name + audit finding text + severity. Seventh context source. |
| Context: project knowledge | contextPackage.projectKnowledge[] | structured | Convention text + confidence level + source. |
| Scope refine: current intent | intent.text | string | Displayed in ScopeRefineBar. Editable on click. |
| Scope refine: loading | contextAssembly.status | "idle" \| "assembling" \| "complete" | Shows spinner during re-assembly. |
| Suggestion composer: section | selectedSection.id | string | Section ID anchoring the suggestion. |
| Suggestion composer: section title | selectedSection.title | string | Display name shown in composer header. |
| Contributor banner: author | ceremony.author.name | string | Git identity of spec author. |
| Contributor banner: status | ceremony.status | "drafting" \| "committed" \| "ratifying" | Current ceremony state. |
| Contributor banner: my suggestion count | suggestions.filter(mine).length | number | Count of this contributor's suggestions. |
| Ratification: validation state | commitment.validationState | structured | Dimension-by-dimension pass/warn/fail at commitment time. |
| Ratification: suggestion summary | commitment.suggestionHistory | structured | N received, N accepted, N dismissed (with reasons expandable). |
| Ratification: context snapshot path | commitment.contextSnapshotRef | string | Path to `.speed/features/{feature}/context-package.json`. |
| Ratification: approval count | ratification.approvalCount | number | Current approvals vs. threshold. |
| Ratification: threshold | ratification.threshold | number | From speed.toml (default 1). |
| Ratification: verdicts | ratification.verdicts[] | structured | Actor name + verdict + timestamp per vote. |
| Ratification: is author | ratification.isAuthor | boolean | Disables approve/reject controls. |
| Ratification: has voted | ratification.hasVoted | boolean | Disables controls if already voted. |
| Convention review: items | bootstrap.derivedConventions[] | structured | Convention text + source (file pattern, CI config, etc.) + accept/reject state. |
| Vision draft: generated text | bootstrap.visionDraft | string \| null | Null if author chose "write from scratch". |
| Vision draft: generating | bootstrap.generating | boolean | True while LLM drafts vision. |
| Commit dialog: validation summary | validation.summary | structured | Same as commit bar but rendered in dialog with dimension names. |
| Commit dialog: unresolved warnings | suggestions.filter(unresolved) | Suggestion[] | Listed in dialog with section references. |
| Commit dialog: multiplayer flag | ceremony.isMultiplayer | boolean | Changes dialog text: "Commit & Propose for Ratification" vs "Commit". |
| Inline validation marker | validation.issues[].location | { line, section, dimension } | Maps issue to editor position. |
| Cross-spec flag | validation.crossSpecIssues[] | { type, message, sourceSpec, sourceSection, targetSpec, targetSection } | Maps contradiction/gap to both specs. |
| History snapshot sections | snapshot.codebase[], snapshot.learnings[], etc. | structured | Same rendering as ContextPanel sections, using ContextSection component. Read-only. |
| History snapshot date | snapshot.assembled_at | ISO 8601 | Formatted as relative time ("3 weeks ago") with full date in tooltip. |
| History ceremony metadata | ceremony.author, ceremony.committed_at | string | Author name and commit date in header. |
| Diff: files added | current.codebase minus snapshot.codebase (by path) | structured | File path (mono, emerald) + "New" badge. |
| Diff: files removed | snapshot.codebase minus current.codebase (by path) | structured | File path (mono, red, strikethrough) + "Removed" badge. |
| Diff: defects resolved | snapshot.defects minus current.defects (by name) | structured | Defect name + "Resolved" badge (emerald). |
| Diff: defects new | current.defects minus snapshot.defects (by name) | structured | Defect name + severity badge + "New" badge. |
| Diff: conventions changed | entries where snapshot.projectKnowledge[].text != current.projectKnowledge[].text | structured | Convention text with inline diff highlighting. |
| Diff: vision status change | snapshot.visionStatus != current.visionStatus | string | "Vision was {old}, now {new}". |

## Interactions & Motion

### Interactions

| Trigger | Target | Response | Notes |
|---------|--------|----------|-------|
| Submit intent | IntentInput | Transitions to loading state; context assembly begins. Progress indicator appears. | Enter key or submit button. |
| Click refine | ScopeRefineBar | Intent text becomes editable. On re-submit, context re-assembles. | Pencil icon, appears on hover. |
| Click context section chevron | ContextSection | Toggle collapsed/expanded. | Preserves scroll position. |
| Save spec content | SpecEditor | Tier 1 validation (template + structure) runs immediately on save. Inline markers for Tier 1 issues appear/disappear. Tier 2 badges show stale indicator if draft changed since last full validation. | No flicker. Tier 1 completes < 100ms. |
| Click "Validate" button | ValidationGutter | Runs all 6 dimensions. Tier 2 badges show loading spinner, then update with results. Stale indicators clear. | Button in ValidationGutter header. Also triggered by Cmd+Shift+R. |
| Click validation badge | ValidationGutter | Expands gutter, scrolls to that dimension's details. | If already expanded, scrolls only. |
| Click inline validation marker | SpecEditor | Scrolls validation gutter to the corresponding issue. | Bidirectional: clicking issue in gutter scrolls editor to marker. |
| Click cross-spec flag | SpecEditor | Navigates to the conflicting section in the other spec's tab. Opens the tab if not already open. | Flag appears in both specs. |
| Click accept on suggestion | SuggestionCard | Suggestion text applied as edit. Card transitions to accepted state (emerald). | Author only. |
| Click dismiss on suggestion | SuggestionCard | Dismiss reason dialog appears. After reason entered, card transitions to dismissed state (tertiary). | Reason is required, minimum 10 characters. |
| Click reply on suggestion | SuggestionCard | Reply input expands below the card. | Thread model: flat, not nested. |
| Toggle suggestion sidebar | EditorTabBar | Sidebar slides in from right (280px). | Icon in tab bar shows unresolved count badge. |
| Click Commit | CommitBar | Confirmation: shows validation summary and unresolved warnings. On confirm, writes artifacts and transitions to committed state. | Blocked (disabled) when template non-conformant. |
| Click Approve | RatificationControls | Confirmation dialog: "Approve this spec for execution?" On confirm, emits `spec.reviewed` event with verdict "approve". Approval count updates. If threshold met, `speed plan` unblocked. | Disabled if viewer is author or has already voted. |
| Click Reject | RatificationControls | Optional comment input appears. On submit, emits `spec.reviewed` event with verdict "reject" and comment. | Disabled if viewer is author or has already voted. |
| Select section (contributor) | SpecEditor (read-only) | SuggestionComposer appears anchored to the selected section heading. Contributor clicks a heading or selects a text range, then clicks the "Suggest" affordance that appears in the editor gutter. | Gutter affordance: speech-bubble icon, appears on heading hover in contributor mode. |
| Submit suggestion | SuggestionComposer | Suggestion persisted, composer closes, suggestion appears in SuggestionSidebar. | Minimum 10 characters. Submit disabled below threshold. |
| Cancel suggestion | SuggestionComposer | Composer closes without persisting. | Escape key or cancel button. |
| Edit own suggestion | SuggestionCard | Card enters edit mode (text becomes editable). | Contributor only, before author resolves. Pencil icon on own cards. |
| Delete own suggestion | SuggestionCard | Confirmation: "Delete this suggestion?" On confirm, suggestion removed. | Contributor only, before author resolves. Trash icon on own cards. |
| Click dismiss reason submit | DismissReasonDialog | Validates >= 10 chars. On pass, dismisses suggestion with reason. Dialog closes. | Shows inline error "Reason must be at least 10 characters" below threshold. |
| Click commit confirm | CommitConfirmDialog | Writes commitment.json, validation-at-commit.json, context snapshot reference. Transitions page to committed state. SP: shows "speed plan is now unblocked." MP: shows "Spec proposed for ratification. Waiting for N approval(s)." | Spinner on confirm button during write. |
| Click scope refine edit | ScopeRefineBar | Intent text becomes editable inline. On submit (Enter or button), context re-assembles. Spec draft is preserved. Progress indicator replaces context panel content during re-assembly. | Pencil icon appears on hover over intent text. |
| Select vision generation | BootstrapWizard | System begins LLM draft. VisionDraftEditor shows generating state (spinner). On complete, split view appears: generated left, editable right. | Author can also choose "Write from scratch" to skip generation. |
| Accept convention | ConventionReview | Convention marked accepted (emerald check). | Individual accept per item. |
| Reject convention | ConventionReview | Convention marked rejected (strikethrough, dimmed). | Rejected conventions excluded from project-knowledge.json. |
| Accept all conventions | ConventionReview | All remaining unresolved conventions accepted. | Button at top of list. |
| Click regenerate vision | VisionDraftEditor | Left pane shows spinner. LLM regenerates. Previous draft replaced. Right pane editable content preserved. | Author can compare regenerated draft against their edits. |
| Bootstrap step complete | BootstrapWizard | Current step transitions to complete (accent). Next step becomes current. Progress indicator updates. | Author can go back to completed steps to edit. |
| Bootstrap step skip | BootstrapWizard | Step marked skipped (text-tertiary). Next step becomes current. | Only optional steps can be skipped. Vision is required. |
| Navigate to history | Portfolio grid or ceremony editor | Click "View history" link on a completed feature. Navigates to `/define/:feature/history`. | Link visible only for features with status `ratified` or `committed` (SP). |
| Collapse/expand diff group | ContextDiff group header | Toggle group collapsed/expanded. | Preserves scroll position in the right column. |
| Return to ceremony | History header | "Back to ceremony" link navigates to `/define/:feature`. | Always available. |

### Motion

| Name | Duration | Easing | Property | Usage |
|------|----------|--------|----------|-------|
| state-change | 150ms | ease-out | background, border-color, color, opacity | Hover/focus transitions on all interactive elements |
| panel-slide | 200ms | ease-out | transform (translateX), opacity | Context panel, suggestion sidebar enter/exit |
| gutter-expand | 250ms | ease-in-out | height, opacity | Validation gutter expand/collapse |
| context-source-complete | 300ms | ease-out | opacity, color | Context assembly: source transitions from pending to complete |
| validation-marker-appear | 150ms | ease-out | opacity | Inline markers appear after validation debounce |
| tab-switch | 0ms | — | — | Instant content swap. No transition on tab content. |

**Reduced motion policy:** Replace all animations with instant state changes. `panel-slide` becomes instant show/hide. `gutter-expand` becomes instant height change. `context-source-complete` becomes instant color change. The state change itself is never removed, only the motion.

## Responsive Behavior

| Breakpoint | Columns | Behavior |
|------------|---------|----------|
| < 1024px | Not supported | Ceremony editor requires minimum 1024px. Below this, show a message: "The Define ceremony requires a wider viewport." Link to portfolio mode (`/define`) which works at any width. |
| 1024-1280px | 2 | Context panel collapses to icon-only rail (48px). Click icon to overlay panel. Suggestion sidebar hidden by default (toggle to overlay). Editor fills remaining width. |
| 1280-1600px | 3 | Full layout: context panel (320px) + editor (fluid) + suggestion sidebar (280px, toggleable). |
| > 1600px | 3 | Same as above. Max content width 1600px, margins grow. |

**History view responsive behavior:**

| Breakpoint | Columns | Behavior |
|------------|---------|----------|
| < 1024px | Not supported | Show message: "Historical context comparison requires a wider viewport." Link to portfolio mode. |
| 1024-1280px | 1 | Single column. Snapshot and current shown in tabs instead of side-by-side. |
| 1280px+ | 2 | Full two-column layout. |

## Accessibility

### Keyboard Navigation

| Component | Keys | Behavior |
|-----------|------|----------|
| IntentInput | Enter | Submit intent |
| ContextSection | Enter/Space | Toggle collapsed/expanded |
| EditorTabBar | Arrow Left/Right | Move between tabs |
| EditorTabBar | Enter | Activate focused tab |
| ValidationGutter | Enter/Space | Toggle expanded/collapsed |
| ValidationBadge | Enter | Expand gutter and scroll to dimension |
| SuggestionCard | Enter | Focus first action (accept) |
| SuggestionCard | Tab | Cycle through accept/dismiss/reply actions |
| CommitBar | Enter | Trigger commit (when focused on Commit button) |
| BootstrapWizard | Tab | Move between wizard controls |
| Ceremony editor | Cmd+Shift+C | Toggle context panel (expand/collapse) |
| Ceremony editor | Cmd+Shift+V | Toggle validation gutter (expand/collapse) |
| Ceremony editor | Cmd+Shift+R | Run full validation (all 6 dimensions) |
| Ceremony editor | Cmd+Shift+S | Toggle suggestion sidebar (show/hide) |
| Ceremony editor | Cmd+Enter | Commit (same as clicking Commit) |
| SuggestionComposer | Escape | Close composer without submitting |
| SuggestionComposer | Cmd+Enter | Submit suggestion |
| SuggestionCard (contributor) | E | Edit own suggestion (before resolution) |
| SuggestionCard (contributor) | Delete/Backspace | Delete own suggestion (with confirmation) |
| DismissReasonDialog | Escape | Close dialog without dismissing |
| DismissReasonDialog | Cmd+Enter | Submit dismiss reason |
| CommitConfirmDialog | Escape | Close dialog without committing |
| CommitConfirmDialog | Enter | Confirm commit |
| RatificationControls | Enter | Activate focused button (approve or reject) |
| ConventionReview | Enter/Space | Toggle accept/reject on focused convention |
| VisionDraftEditor | Tab | Move focus between left pane, right pane, and action buttons |
| BootstrapWizard | Arrow Up/Down | Move between steps (completed steps are revisitable) |
| ContextDiff group | Enter/Space | Toggle collapsed/expanded |
| History tabs (< 1280px) | Arrow Left/Right | Switch between Snapshot and Current tabs |
| History view | Escape | Navigate back to ceremony editor |

### ARIA & Screen Reader

| Component | Role | ARIA | Announcement |
|-----------|------|------|--------------|
| IntentInput | search | aria-label="Declare what you want to build" | — |
| ContextPanel | complementary | aria-label="Context panel" | — |
| ContextSection | region | aria-expanded, aria-label="{title}" | "{title}: {count} items, collapsed/expanded" |
| ValidationGutter | status | aria-live="polite" | "Validation: {pass} pass, {warn} warnings, {fail} failures" on change |
| ValidationBadge | status | aria-label="{dimension}: {status}" | — |
| SuggestionCard | article | aria-label="Suggestion from {author}" | — |
| CommitBar | toolbar | aria-label="Commit controls" | — |
| CommitButton (disabled) | — | aria-disabled="true", title="Template conformance required" | — |
| RatifyApprove | button | aria-label="Approve spec for execution", aria-disabled when author or voted | — |
| RatifyReject | button | aria-label="Reject spec, request rework", aria-disabled when author or voted | — |
| SuggestionComposer | form | aria-label="Leave a suggestion on {sectionTitle}" | — |
| SuggestionComposer input | textbox | aria-label="Suggestion text" | — |
| ContributorBanner | banner | aria-label="Contributor view" | "Viewing as contributor. Spec authored by {authorName}." on page load. |
| SuggestionSidebar | complementary | aria-label="Suggestions ({count})" | — |
| DismissReasonDialog | dialog | aria-modal="true", aria-label="Dismiss suggestion" | Focus trapped inside dialog. |
| CommitConfirmDialog | dialog | aria-modal="true", aria-label="Commit spec" | Focus trapped inside dialog. |
| ConventionReview item | listitem | aria-label="{convention text}" | — |
| ConventionReview list | list | aria-label="Derived conventions" | — |
| VisionDraftEditor left | region | aria-label="Generated vision draft (read-only)" | — |
| VisionDraftEditor right | region | aria-label="Your vision (editable)" | — |
| BootstrapWizard | navigation | aria-label="Bootstrap setup" | "Step {n} of {total}: {stepTitle}" announced on step change. |
| BootstrapWizard step | listitem | aria-current="step" on active step | — |
| CrossSpecFlag | button | aria-label="Contradiction: {message}. Click to navigate to conflicting section." | — |
| ValidationInlineMarker | button | aria-label="{dimension}: {issue text}. Click to view details." | — |
| RatificationSummary | region | aria-label="Ratification evidence" | — |
| RatificationControls | toolbar | aria-label="Ratification controls" | — |

### Contrast & Targets

All color tokens are defined in `globals.css` with contrast ratios documented:
- `--text` (#e4e4e9) against `--bg-card` (#1c1c27): ~13:1
- `--text-secondary` (#9494a3) against `--bg-card`: ~5.5:1
- `--text-tertiary` (#55556a): decorative only, not used for actionable content

All interactive targets meet 44x44px minimum: buttons, suggestion actions, validation badges, context section chevrons. The intent input field exceeds this. Tab targets use full tab-bar height (40px) with sufficient width.

## Content Constraints

| Element | Min | Max | Overflow | Placeholder |
|---------|-----|-----|----------|-------------|
| Intent text | 5 chars | No limit | Wraps to multiple lines | "What do you want to build?" |
| Context section title | — | 32 chars | Truncate with ellipsis | — |
| Context item path | — | — | Truncate middle with ellipsis (keep filename) | — |
| Suggestion text | 10 chars | 2000 chars | Wraps, no truncation | — |
| Dismiss reason | 10 chars | 500 chars | Wraps | "Why are you dismissing this suggestion?" |
| Reply text | 1 char | 1000 chars | Wraps | "Reply to this suggestion..." |
| Spec content | — | No limit | Editor scrolls | Template headings with placeholder guidance |
| Validation issue text | — | 200 chars | Truncate with ellipsis, expandable | — |
| Bootstrap vision draft | — | No limit | Scrolls in split view | — |
| Convention text | — | 200 chars | Truncate with ellipsis, expandable | — |
| Convention source | — | 100 chars | Truncate with ellipsis | — |
| Contributor banner author name | — | 32 chars | Truncate with ellipsis | — |
| Cross-spec flag message | — | 200 chars | Wraps in tooltip | — |
| Validation marker tooltip | — | 150 chars | Wraps in tooltip | — |
| Commit dialog validation line | — | 100 chars | Truncate with ellipsis | — |
| Ratification verdict actor | — | 32 chars | Truncate with ellipsis | — |
| Ratification reject comment | — | 500 chars | Wraps | "Why are you rejecting this spec?" |
| Scope refine intent | 5 chars | No limit | Wraps | Same as intent input |

## Implementation Notes

- The ceremony does not modify `SpecEditor`. The `CeremonyLayout` component composes SpecEditor with ContextPanel, ValidationGutter, SuggestionSidebar, and CommitBar as sibling regions. The editor doesn't know it's in a ceremony.
- The context panel extends `IntelPanel` with a `mode` prop for ceremony-specific sections (Defects, Vision Status) and data source (context package instead of current-spec context).
- The validation gutter is a new pattern. No existing component to extend. Use the `.surface` class for the expanded state.
- `position: sticky` is used for the CommitBar. Ensure no ancestor of the editor area sets `overflow: hidden`.
- The suggestion sidebar uses the same slide-in animation as the existing explorer panel in the Define portfolio page. Reuse the motion token.
- Markdown rendering in the editor should match the existing SpecPreview component for consistency. Authors should see the same formatting in edit mode as in preview.
- Context assembly may take 2-10 seconds depending on codebase size. The progressive loading (source by source) is critical to perceived performance. Never block the full UI waiting for all sources.
- The bootstrap wizard writes to `specs/product/overview.md` and `.speed/memory/project-knowledge.json`. These are filesystem writes triggered by GraphQL mutations. The existing `spec_editor.py` resolver pattern handles filesystem writes from the dashboard.

## Verification Criteria

- [ ] Token audit passes with zero hardcoded color/spacing/font values outside of `globals.css`
- [ ] All interactive components have visible focus indicators using the accent ring pattern
- [ ] Tab order matches the sequence defined in Accessibility section
- [ ] Empty, loading, populated, error, and bootstrap states render correctly for every region
- [ ] Layout matches breakpoint table at 1024px, 1280px, and 1600px
- [ ] No text element uses a raw font-size; all use typography role classes or the defined custom sizes
- [ ] Reduced motion: all animations replaced with instant transitions when `prefers-reduced-motion: reduce` is active
- [ ] Context panel loads progressively (sources appear as they complete, not all-at-once)
- [ ] Tier 1 validation markers (template, structure) update on save (< 100ms, no flicker)
- [ ] Tier 2 badges show stale indicator (dimmed, tooltip "last checked: Xm ago") when draft changed since last full validation
- [ ] Validate button (Cmd+Shift+R) runs all 6 dimensions with loading spinners on Tier 2 badges
- [ ] Commit auto-runs all dimensions; Tier 2 results shown in commit dialog
- [ ] Commit button is disabled (text-tertiary background, not-allowed cursor) when template non-conformant
- [ ] Suggestion sidebar toggle shows unresolved count badge (amber) when > 0
- [ ] Cross-spec flags navigate between tabs and highlight the conflicting section in the target spec
- [ ] Intent refinement re-assembles context without losing the current spec draft
- [ ] Minimum viewport width enforced: below 1024px, ceremony surfaces show fallback message
- [ ] Inline validation markers render as colored left-border on affected lines (red/amber/blue per dimension)
- [ ] Inline validation marker tooltips show issue text on hover and scroll gutter to issue on click
- [ ] Cross-spec flags render as gutter icons (red for contradictions, amber for gaps) with tooltips showing the conflict message
- [ ] Clicking a cross-spec flag opens the conflicting spec's tab and scrolls to the affected section
- [ ] Contributor mode shows ContributorBanner with author name and "You are viewing as a contributor" label
- [ ] Contributor can select a section heading and see the SuggestionComposer anchored to it
- [ ] SuggestionComposer enforces minimum 10 characters and disables submit below threshold
- [ ] Dismiss reason dialog traps focus, enforces minimum 10 characters, shows inline error
- [ ] Commit confirmation dialog shows validation summary per dimension + unresolved suggestion list + multiplayer-aware messaging
- [ ] Post-commit state shows success messaging appropriate to mode (SP: "speed plan unblocked" / MP: "Proposed for ratification")
- [ ] Ratification view shows approval count vs. threshold (e.g., "1 of 2 approvals")
- [ ] Author cannot see approve/reject controls on their own spec (controls disabled with reason)
- [ ] Each approver can vote once; controls disabled after voting
- [ ] Bootstrap wizard detects cold start (no semantic graph + no vision + no project knowledge)
- [ ] Bootstrap offers vision generation vs. write-from-scratch choice before vision step
- [ ] VisionDraftEditor shows split view: generated read-only left, editable right, with regenerate affordance
- [ ] ConventionReview shows system-derived conventions with per-item accept/reject and bulk accept-all
- [ ] Scope refinement preserves current spec draft during context re-assembly
- [ ] Context panel includes Audit History section (seventh source) alongside existing IntelPanel sections

## Figma / Visual Reference

No Figma file exists for this feature. The design spec is the source of truth.

Prototype: see `working-docs/define-ceremony-prototype.html` (local file, not tracked in specs). Single HTML file with four views: Intent Input, Ceremony Editor (three-panel layout with context, editor, suggestions), Bootstrap (vision draft split view), and Ratification. Uses actual design tokens from `globals.css`. Navigate between views using the bottom bar.

Reference the existing dashboard components for visual consistency: `SpecEditor`, `IntelPanel`, `EditorTabs`, `StatusBar`, and the `.surface` / `.surface-elevated` / `.surface-hover` classes in `globals.css`.
