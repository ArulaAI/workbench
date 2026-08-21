# Design: Define Ceremony — Contributor Suggestions

> See [product spec](../product/speed-define-ceremony.md) for product context (stories S7, S8).
> See [tech RFC](../tech/speed-define-ceremony-contributor.md) for API surface, data model, and validation rules.
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
  Five components: SuggestionSidebar, SuggestionCard, SuggestionComposer,
  ContributorBanner, DismissReasonDialog. Two viewing modes (author,
  contributor) within the ceremony editor at /define/:feature.
  Everything else (context panel, editor, validation, commitment,
  bootstrap, ratification) belongs to sibling design specs.
-->


## Design Intent

> See [design principles](../../working-docs/define-ceremony-design-principles.md) for the 8 principles governing all ceremony surfaces.

**Direction:** The contributor experience is asymmetric by design. A contributor arrives at `/define/:feature`, sees the spec in read-only mode with the same context panel the author sees, and can attach suggestions to specific sections. The author sees those suggestions in a sidebar and resolves them one by one. Resolution is deliberate: accepting is a single click, but dismissing requires a written reason (minimum 10 characters). The sidebar is reference material for the author, not a chat window. The suggestion count badge in the tab bar is the only persistent reminder that unresolved feedback exists.

**Do not:** Apply accent color to suggestion cards or sidebar headers (accent is reserved for the submit action and the tab badge active state). Use pure white (`#fff`) anywhere. Add decorative empty-state artwork. Make the sidebar visually compete with the editor. Use borders without paired shadows on elevated elements. Treat "no suggestions yet" and "all resolved" as the same state.


## Scope

Five components, two modes:

| Component | File | Role |
|-----------|------|------|
| SuggestionSidebar | `ceremony/SuggestionSidebar.tsx` | Toggleable right panel listing all suggestions grouped by section |
| SuggestionCard | `ceremony/SuggestionCard.tsx` | Individual suggestion with author, text, status, resolution controls |
| SuggestionComposer | `ceremony/SuggestionComposer.tsx` | Inline input anchored to a spec section heading |
| ContributorBanner | `ceremony/ContributorBanner.tsx` | Full-width bar at top indicating read-only contributor mode |
| DismissReasonDialog | `ceremony/DismissReasonDialog.tsx` | Modal requiring a written reason before dismissal |

| Mode | Who | Editor | Sidebar | Banner | Compose |
|------|-----|--------|---------|--------|---------|
| Author | Ceremony owner | Read-write | Accept/dismiss/reply controls | Hidden | Hidden |
| Contributor | Everyone else | Read-only | View suggestions, reply to own | Visible | Visible on section click |


## Layout Structure

### Author Mode

```
┌────────────────────────────────────────────────────────────────────┐
│  IconRail │  Context Panel (320px)  │  Editor (fluid)  │ Sidebar  │
│   52px    │                         │                  │  280px   │
│           │  ▸ Codebase         3   │  ## User Stories  │          │
│           │  ▸ Learnings        2   │  ...              │ ┌──────┐ │
│           │  ▸ Defects          0   │                   │ │ Card │ │
│           │  ...                    │  ## Scope          │ │      │ │
│           │                         │  ...               │ └──────┘ │
│           │                         │                    │ ┌──────┐ │
│           │                         │                    │ │ Card │ │
│           │                         │                    │ └──────┘ │
│           │                         │  [Validation]      │          │
│           │                         │  [CommitBar 52px]   │          │
└────────────────────────────────────────────────────────────────────┘
```

The suggestion sidebar occupies the rightmost 280px of the editor layout. It shares the same elevation tier as the context panel (`surface-elevated`), forming a visual frame around the central editor surface.

### Contributor Mode

```
┌────────────────────────────────────────────────────────────────────┐
│  IconRail │  Context Panel (320px)  │  Editor (fluid)     │ Sidebar│
│   52px    │                         │ ┌──────────────────┐│ 280px  │
│           │  ▸ Codebase         3   │ │ ContributorBanner││        │
│           │  ▸ Learnings        2   │ │ Authored by Jane ││ ┌────┐ │
│           │  ...                    │ └──────────────────┘│ │Card│ │
│           │                         │  ## User Stories [+] │ │    │ │
│           │                         │  ...                 │ └────┘ │
│           │                         │  ## Scope       [+]  │        │
│           │                         │  ┌────────────────┐  │        │
│           │                         │  │ Composer       │  │        │
│           │                         │  │ (anchored)     │  │        │
│           │                         │  └────────────────┘  │        │
└────────────────────────────────────────────────────────────────────┘
```

`[+]` represents the add-suggestion affordance that appears on heading hover in contributor mode. The `ContributorBanner` sits above the editor content, below the tab bar.

### Sidebar Collapsed State

When collapsed, the sidebar disappears entirely. The only trace is the chat icon in the `EditorTabBar` with an amber badge showing unresolved count (when > 0). Toggling is Cmd+Shift+S or clicking the icon.

```
Tab bar (right side):
  ... tab-spacer ... [💬 3]    ← chat icon with amber badge
```

The badge uses `--color-amber` background with `--color-bg` text, 14px pill, 9px mono weight-600 numeral.


## Component Inventory

### SuggestionSidebar

#### Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| suggestions | Suggestion[] | required | All suggestions for the ceremony |
| isAuthor | boolean | required | Shows resolution controls when true; compose affordance when false |
| onAccept | (id: string) => void | required | Accept callback (author only) |
| onDismiss | (id: string, reason: string) => void | required | Dismiss callback (author only) |
| onReply | (id: string, text: string) => void | required | Reply callback (author or contributor) |
| onEdit | (id: string, text: string) => void | required | Edit callback (contributor, own, unresolved only) |
| onDelete | (id: string) => void | required | Delete callback (contributor, own, unresolved only) |

#### Layout

```
┌──────────────────────────┐
│  Suggestions         3   │  ← header: title + count
├──────────────────────────┤
│                          │
│  SCOPE                   │  ← section group header
│  ┌────────────────────┐  │
│  │  SuggestionCard    │  │
│  └────────────────────┘  │
│  ┌────────────────────┐  │
│  │  SuggestionCard    │  │
│  └────────────────────┘  │
│                          │
│  USER STORIES            │  ← section group header
│  ┌────────────────────┐  │
│  │  SuggestionCard    │  │
│  └────────────────────┘  │
│                          │
└──────────────────────────┘
```

Suggestions are grouped by the spec section they target. Each group has a section header showing the original `section_title`. Cards within a group are ordered by `created_at` ascending.

#### Visual Specification

| Property | Value | Token |
|----------|-------|-------|
| Width | 280px fixed | — |
| Background | `--color-bg-elevated` | `.surface-elevated` class |
| Border left | 1px solid | `--color-border` |
| Header padding | 12px 16px | 4px grid |
| Header border-bottom | 1px solid | `--color-border` |
| Header title | 13px / 600 / `--color-text` | `type-section-header` |
| Header count | 13px mono / 500 / `--color-text-secondary` | `type-mono-value` |
| List padding | 8px | 4px grid |
| Section group header | 11px / 500 / `--color-text-tertiary`, uppercase, 0.04em tracking | `type-table-header` |
| Section group margin-top | 16px (first group: 0) | 4px grid |
| Section group margin-bottom | 8px | 4px grid |
| Scroll | Independent vertical scroll | — |


### SuggestionCard

#### Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| suggestion | Suggestion | required | Full suggestion data |
| onAccept | (id: string) => void | required | Accept callback |
| onDismiss | (id: string, reason: string) => void | required | Dismiss callback |
| onReply | (id: string, text: string) => void | required | Reply callback |
| onEdit | (id: string, text: string) => void | — | Edit callback (contributor's own, unresolved) |
| onDelete | (id: string) => void | — | Delete callback (contributor's own, unresolved) |
| isAuthor | boolean | required | True = show accept/dismiss/reply. False = show edit/delete on own. |
| currentUser | string | required | Current actor identity for ownership checks |

#### Layout

```
┌────────────────────────────┐
│  Alex Chen       10:32 AM  │  ← author + timestamp
│  scope > in-scope          │  ← section reference (mono)
│                            │
│  Add a criterion for the   │  ← suggestion text
│  24-hour throttle on       │
│  accessedAt updates.       │
│                            │
│  [Accept] [Dismiss] [Reply]│  ← author actions
│                            │
│  ┌──── reply thread ────┐  │
│  │ Jane: Good point,    │  │
│  │ I'll add that.       │  │
│  └──────────────────────┘  │
└────────────────────────────┘
```

#### Visual Specification

| Property | Value | Token |
|----------|-------|-------|
| Background | `--color-bg-card` | `.surface` class |
| Border | 1px solid | `--color-border` |
| Border-radius | 8px | — |
| Shadow | standard `.surface` shadow | — |
| Padding | 12px | 4px grid |
| Margin-bottom | 8px | 4px grid |
| Author name | 12px / 500 / `--color-text` | — |
| Timestamp | 10px mono / 400 / `--color-text-tertiary` | — |
| Section ref | 11px mono / 400 / `--color-text-tertiary` | — |
| Suggestion text | 13px / 400 / `--color-text-secondary`, line-height 1.5 | `type-body` |
| Action buttons | 11px / 500, 4px 10px padding, 4px radius | — |
| Status dot | 8px circle, flex-shrink 0 | — |
| Status label | 11px mono / 500 | — |


### SuggestionComposer

#### Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| sectionId | string | required | Slugified heading the suggestion anchors to |
| sectionTitle | string | required | Display name of the anchored section |
| onSubmit | (text: string) => void | required | Called on valid submission |
| onCancel | () => void | required | Closes composer |

#### Layout

```
┌──────────────────────────────────┐
│  ✎  Suggesting on: scope        │  ← context line
│  ┌──────────────────────────┐    │
│  │ Write your suggestion... │    │  ← textarea
│  │                          │    │
│  └──────────────────────────┘    │
│              [Cancel] [Submit]   │  ← actions, right-aligned
└──────────────────────────────────┘
```

The composer renders inline in the editor content, directly below the section heading the contributor clicked. It pushes subsequent content down.

#### Visual Specification

| Property | Value | Token |
|----------|-------|-------|
| Background | `--color-bg-card` | `.surface` class |
| Border | 1px solid | `--color-border` |
| Border-radius | 8px | — |
| Margin | 8px 0 16px | 4px grid |
| Padding | 16px | 4px grid |
| Context icon | 14px, `--color-accent` | — |
| Context section name | 11px mono / `--color-accent` | — |
| Context label ("Suggesting on:") | 12px / 500 / `--color-text-secondary` | — |
| Context line margin-bottom | 10px | — |
| Textarea background | `--color-bg-elevated` | — |
| Textarea border | 1px solid `--color-border`, focus: `rgba(0, 212, 170, 0.3)` | — |
| Textarea border-radius | 6px | — |
| Textarea padding | 10px 12px | — |
| Textarea font | 13px sans / 400 / `--color-text`, line-height 1.5 | `type-body` |
| Textarea placeholder | `--color-text-tertiary` | — |
| Textarea min-height | 72px | — |
| Actions gap | 8px | 4px grid |
| Actions margin-top | 8px | 4px grid |
| Cancel button | 12px / 500, transparent bg, `--color-text-secondary`, 1px border `--color-border`, 6px radius, 6px 14px padding | — |
| Submit button | 12px / 600, `--color-accent` bg, `--color-bg` text, no border, 6px radius, 6px 14px padding | — |


### ContributorBanner

#### Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| authorName | string | required | Name of the spec author |
| ceremonyStatus | "drafting" \| "committed" \| "ratifying" | required | Current ceremony state |
| suggestionCount | number | 0 | Number of suggestions this contributor has left |

#### Layout

```
┌──────────────────────────────────────────────────────────────────┐
│  ⚠  You are viewing as a contributor  ·  Jane Doe  ·  drafting  │
└──────────────────────────────────────────────────────────────────┘
```

Full-width bar sitting above the editor content, below the tab bar.

#### Visual Specification

| Property | Value | Token |
|----------|-------|-------|
| Height | 40px | 4px grid |
| Padding | 8px 20px | 4px grid |
| Background | `rgba(240, 178, 50, 0.04)` | Amber-tinted `--color-bg-elevated` |
| Border-bottom | 1px solid | `--color-border` |
| Icon | 14px, `--color-amber` | Warning triangle |
| Label ("You are viewing as a contributor") | 11px / 500 / `--color-amber` | `type-badge` |
| Author name | 12px / 600 / `--color-text` | — |
| Ceremony status | 11px / 400 / `--color-text-secondary` | `type-caption` |
| Suggestion count | 13px mono / 500 / `--color-text-secondary` | `type-mono-value` |
| Gap between elements | 8px | 4px grid |
| Elevation | Level 1 | `.surface-elevated` class |


### DismissReasonDialog

#### Layout

```
┌─── overlay (rgba(0,0,0,0.5)) ────────────────────────────────┐
│                                                                │
│           ┌──────────────────────────────────┐                 │
│           │  Dismiss suggestion              │                 │
│           │  Why are you dismissing this?     │                 │
│           │                                  │                 │
│           │  ┌────────────────────────────┐   │                 │
│           │  │ (textarea)                │   │                 │
│           │  │                           │   │                 │
│           │  └────────────────────────────┘   │                 │
│           │  ⚠ Reason must be at least 10    │                 │
│           │    characters                    │                 │
│           │                                  │                 │
│           │          [Cancel] [Dismiss]       │                 │
│           └──────────────────────────────────┘                 │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

#### Visual Specification

| Property | Value | Token |
|----------|-------|-------|
| Overlay | `rgba(0, 0, 0, 0.5)`, backdrop-filter: blur(4px) | — |
| Dialog width | 400px fixed | Parent spec spacing table |
| Dialog padding | 20px | Parent spec spacing table |
| Dialog background | `--color-bg-card` | `.surface` class |
| Dialog border-radius | 10px | Standard `.surface` |
| Dialog shadow | `.surface` shadow + shadow-lg | Elevation 3 |
| Title | 15px / 600 / `--color-text` | — |
| Prompt | 13px / 400 / `--color-text-secondary` | `type-body` |
| Prompt margin-bottom | 12px | 4px grid |
| Textarea background | `--color-bg-elevated` | — |
| Textarea border | 1px solid `--color-border`, focus: `rgba(239, 68, 100, 0.3)` | Red-tinted focus |
| Textarea border-radius | 6px | — |
| Textarea padding | 10px 12px | — |
| Textarea font | 13px sans / 400 / `--color-text` | `type-body` |
| Textarea placeholder | "Why are you dismissing this suggestion?" in `--color-text-tertiary` | — |
| Textarea min-height | 80px | — |
| Validation error | 11px / 400 / `--color-red` | `type-caption` with red override |
| Actions margin-top | 12px | 4px grid |
| Actions gap | 8px | 4px grid |
| Cancel button | 12px / 500, transparent bg, `--color-text-secondary`, 1px border `--color-border`, 6px radius, 6px 14px padding | Same as composer cancel |
| Dismiss confirm button | 12px / 600, `rgba(239, 68, 100, 0.12)` bg, `--color-red` text, 1px border `rgba(239, 68, 100, 0.2)`, 6px radius, 6px 16px padding | Red-tinted, not solid red |


## States

### SuggestionCard States

| State | Visual Treatment | Actions Visible | Notes |
|-------|-----------------|-----------------|-------|
| Pending (author view) | Full opacity, `.surface` card | Accept, Dismiss, Reply | Default state for new suggestions |
| Pending (contributor, own) | Full opacity, `.surface` card | Edit, Delete, Reply | Only on the contributor's own unresolved suggestions |
| Pending (contributor, other's) | Full opacity, `.surface` card | Reply only | Cannot modify another contributor's suggestion |
| Accepted | Opacity 0.55, emerald status dot (8px), "Accepted" label in `--color-emerald` (11px mono) | None (actions hidden) | Card dims to reduce visual weight |
| Dismissed | Opacity 0.35, red status dot (8px), "Dismissed" label in `--color-text-tertiary` (11px mono), italic dismiss reason in 11px `--color-text-tertiary` below | None (actions hidden) | Dimmer than accepted; the reason text is always visible |
| With reply thread | Thread area below actions, separated by 1px `--color-border-light` top border, 8px padding-top/margin-top | All actions remain | Replies stack vertically within the card |

**Reply bubble specification:**

| Property | Value | Token |
|----------|-------|-------|
| Background | `--color-bg-elevated` | — |
| Border | 1px solid `--color-border-light` | — |
| Shadow | `0 1px 2px rgba(0, 0, 0, 0.15)` | — |
| Border-radius | 6px | — |
| Padding | 6px 10px | — |
| Margin-bottom | 6px | — |
| Reply author | 11px / 500 / `--color-accent` | — |
| Reply text | 12px / 400 / `--color-text-secondary`, line-height 1.4 | — |

**Reply input** appears inline below the reply thread when the Reply button is clicked:

| Property | Value | Token |
|----------|-------|-------|
| Textarea background | `--color-bg-elevated` | — |
| Textarea border | 1px solid `--color-border`, focus: `rgba(0, 212, 170, 0.3)` | — |
| Textarea border-radius | 4px | — |
| Textarea padding | 6px 8px | — |
| Textarea font | 12px sans / 400 / `--color-text` | — |
| Textarea min-height | 48px | — |
| Send button | 10px / 600 / `--color-bg` on `--color-accent` bg, 3px 8px padding, 4px radius | — |
| Cancel button | 10px / 500 / `--color-text-tertiary`, transparent bg, 3px 8px padding | — |
| Actions gap | 6px | — |
| Actions margin-top | 4px | — |


### SuggestionSidebar States

| State | Visual Treatment | Notes |
|-------|-----------------|-------|
| Empty | Header reads "Suggestions" with em-dash count. Body shows: "No suggestions yet." in 13px `--color-text-secondary`, centered vertically. | Author sees this until a contributor submits. |
| Has pending | Header count shows total. Amber badge on tab bar toggle shows unresolved count only. Cards render grouped by section. | Unresolved cards at full opacity; resolved cards dimmed below them within each group. |
| All resolved | Header count shows total. Tab bar badge disappears (0 unresolved). All cards dimmed (accepted at 0.55, dismissed at 0.35). | The sidebar remains accessible but the visual weight is minimal. |

### ContributorBanner States

| State | Label Text | Status Text | Notes |
|-------|-----------|-------------|-------|
| Drafting | "You are viewing as a contributor" | "drafting" in `--color-text-secondary` | Active authoring; suggestions are expected |
| Committed | "You are viewing as a contributor" | "committed" in `--color-text-secondary` | Spec committed; suggestions still allowed (pre-ratification) |

### SuggestionComposer States

| State | Visual Treatment | Notes |
|-------|-----------------|-------|
| Collapsed | Not rendered. Contributor sees the `[+]` affordance on section heading hover. | Default state. |
| Composing | Composer visible inline below heading. Textarea focused. Submit disabled below 10 chars (submit button bg: `--color-text-tertiary`, cursor: not-allowed). | Cancel or Escape closes. |
| Submitting | Submit button shows spinner, textarea read-only, width locked. | Brief (network round-trip). On success, composer closes and card appears in sidebar. |

### DismissReasonDialog States

| State | Visual Treatment | Notes |
|-------|-----------------|-------|
| Open, invalid | Textarea empty or < 10 chars. Dismiss confirm button disabled (`--color-text-tertiary` bg, cursor: not-allowed). Validation error hidden until first submit attempt or after 10+ chars then deleting below threshold. | Focus trapped inside dialog. |
| Open, valid | Textarea >= 10 chars. Dismiss confirm button active (`rgba(239, 68, 100, 0.12)` bg, `--color-red` text). Validation error hidden. | Ready to submit. |

### Add-Suggestion Affordance

The `[+]` button only appears on section heading hover in contributor mode. Not a standalone component; rendered within the editor's heading elements.

| Property | Value | Token |
|----------|-------|-------|
| Font | 11px / 500 / `--color-accent` | — |
| Background | `--color-accent-dim` | — |
| Border | 1px solid `rgba(0, 212, 170, 0.15)` | — |
| Shadow | `0 1px 2px rgba(0, 0, 0, 0.2)` | — |
| Border-radius | 6px | — |
| Padding | 3px 8px | — |
| Hover background | `rgba(0, 212, 170, 0.16)` | — |
| Visibility | `display: none` by default; `display: inline-flex` on `.contributor-mode .section-heading:hover` | — |
| Icon | 12px, inline before label text | — |


## Data Binding

| Element | Source | Format | GraphQL Binding |
|---------|--------|--------|-----------------|
| Sidebar suggestion list | `suggestions[]` | Suggestion objects | `suggestions(featureName)` query |
| Sidebar suggestion count | `suggestions.length` | number | Derived from query result |
| Tab bar badge count | `suggestions.filter(s => s.status === "unresolved").length` | number | Derived client-side |
| Card author name | `suggestion.author` | string | From `Suggestion.author` field |
| Card section ref | `suggestion.section_title` | string | From `Suggestion.sectionTitle` field |
| Card suggestion text | `suggestion.text` | string | From `Suggestion.text` field |
| Card timestamp | `suggestion.created_at` | ISO 8601, formatted relative | From `Suggestion.createdAt` field |
| Card status | `suggestion.status` | "unresolved" / "accepted" / "dismissed" | From `Suggestion.status` field |
| Card resolution | `suggestion.resolution` | Resolution object or null | From `Suggestion.resolution` field |
| Card reply thread | `suggestion.thread[]` | SuggestionReply[] | From `Suggestion.thread` field |
| Dismiss reason | `suggestion.resolution.reason` | string | From `Resolution.reason` field |
| Contributor banner author | `ceremony.author.name` | string | From ceremony ownership record |
| Contributor banner status | `ceremony.status` | "drafting" / "committed" / "ratifying" | From `CeremonyStatus` |
| Contributor banner count | `suggestions.filter(s => s.author_email === currentUser).length` | number | Derived client-side |
| Composer section ref | `selectedSection.id`, `selectedSection.title` | string | Client-side from clicked heading |

**Mutations used:**

| Action | Mutation | Triggered by |
|--------|----------|-------------|
| Submit suggestion | `createSuggestion(featureName, sectionId, sectionTitle, text)` | SuggestionComposer submit |
| Edit suggestion | `editSuggestion(id, text)` | SuggestionCard edit confirm |
| Delete suggestion | `deleteSuggestion(id)` | SuggestionCard delete confirm |
| Accept | `resolveSuggestion(id, ACCEPT)` | SuggestionCard accept button |
| Dismiss | `resolveSuggestion(id, DISMISS, reason)` | DismissReasonDialog confirm |
| Reply | `replySuggestion(id, text)` | SuggestionCard reply send |


## Typography

Every text element in the suggestion system, mapped to globals.css tokens.

| Element | Role | Family | Size | Weight | Line-Height | Color |
|---------|------|--------|------|--------|-------------|-------|
| Sidebar header title | `type-section-header` | `--font-sans` | 13px | 600 | 1.4 | `--color-text` |
| Sidebar header count | `type-mono-value` | `--font-mono` | 13px | 500 | 1.4 | `--color-text-secondary` |
| Section group header | `type-table-header` | `--font-mono` | 11px | 500 | 1.4 | `--color-text-tertiary` |
| Card author name | custom | `--font-sans` | 12px | 500 | 1.4 | `--color-text` |
| Card timestamp | custom | `--font-mono` | 10px | 400 | 1.4 | `--color-text-tertiary` |
| Card section ref | custom | `--font-mono` | 11px | 400 | 1.4 | `--color-text-tertiary` |
| Card suggestion text | `type-body` | `--font-sans` | 13px | 400 | 1.5 | `--color-text-secondary` |
| Card action button | custom | `--font-sans` | 11px | 500 | 1 | Per-action color |
| Card status label | custom | `--font-mono` | 11px | 500 | 1 | Status color |
| Card dismiss reason | custom | `--font-sans` | 11px | 400 | 1.4 | `--color-text-tertiary` |
| Reply author | custom | `--font-sans` | 11px | 500 | 1.4 | `--color-accent` |
| Reply text | custom | `--font-sans` | 12px | 400 | 1.4 | `--color-text-secondary` |
| Reply input | custom | `--font-sans` | 12px | 400 | 1.4 | `--color-text` |
| Reply send button | custom | `--font-sans` | 10px | 600 | 1 | `--color-bg` on `--color-accent` |
| Reply cancel button | custom | `--font-sans` | 10px | 500 | 1 | `--color-text-tertiary` |
| Composer context label | custom | `--font-sans` | 12px | 500 | 1.4 | `--color-text-secondary` |
| Composer section name | custom | `--font-mono` | 11px | 500 | 1.4 | `--color-accent` |
| Composer textarea | `type-body` | `--font-sans` | 13px | 400 | 1.5 | `--color-text` |
| Composer placeholder | custom | `--font-sans` | 13px | 400 | 1.5 | `--color-text-tertiary` |
| Composer submit button | `type-badge` | `--font-sans` | 12px | 600 | 1 | `--color-bg` on `--color-accent` |
| Composer cancel button | custom | `--font-sans` | 12px | 500 | 1 | `--color-text-secondary` |
| Banner label | `type-badge` | `--font-sans` | 11px | 500 | 1 | `--color-amber` |
| Banner author name | custom | `--font-sans` | 12px | 600 | 1.4 | `--color-text` |
| Banner status | `type-caption` | `--font-sans` | 11px | 400 | 1.4 | `--color-text-secondary` |
| Banner suggestion count | `type-mono-value` | `--font-mono` | 13px | 500 | 1.4 | `--color-text-secondary` |
| Dialog title | custom | `--font-sans` | 15px | 600 | 1.4 | `--color-text` |
| Dialog prompt | `type-body` | `--font-sans` | 13px | 400 | 1.5 | `--color-text-secondary` |
| Dialog textarea | `type-body` | `--font-sans` | 13px | 400 | 1.5 | `--color-text` |
| Dialog validation error | `type-caption` | `--font-sans` | 11px | 400 | 1.4 | `--color-red` |
| Dialog dismiss button | custom | `--font-sans` | 12px | 600 | 1 | `--color-red` |
| Dialog cancel button | custom | `--font-sans` | 12px | 500 | 1 | `--color-text-secondary` |
| Tab bar badge numeral | custom | `--font-mono` | 9px | 600 | 1 | `--color-bg` on `--color-amber` |
| Empty state message | `type-body` | `--font-sans` | 13px | 400 | 1.5 | `--color-text-secondary` |
| Detached notice | `type-caption` | `--font-sans` | 11px | 400 | 1.4 | `--color-amber` |
| Add-suggestion button | custom | `--font-sans` | 11px | 500 | 1 | `--color-accent` |


## Color Application

| Element | Property | Token | Notes |
|---------|----------|-------|-------|
| Sidebar background | background | `--color-bg-elevated` | `.surface-elevated` class |
| Sidebar border | border-left | `--color-border` | 1px solid |
| Card surface | background | `--color-bg-card` | `.surface` class |
| Card border | border | `--color-border` | Part of `.surface` |
| Accept button text | color | `--color-emerald` | — |
| Accept button bg | background | `rgba(68, 204, 119, 0.08)` | Emerald at 8% |
| Accept button hover bg | background | `rgba(68, 204, 119, 0.16)` | Emerald at 16% |
| Dismiss button text | color | `--color-text-secondary` | Hover: `--color-red` |
| Dismiss button bg | background | `rgba(239, 68, 100, 0.08)` | Red at 8% |
| Dismiss button hover bg | background | `rgba(239, 68, 100, 0.16)` | Red at 16% |
| Reply button text | color | `--color-text-secondary` | Hover: `--color-text` |
| Reply button bg | background | transparent | — |
| Status dot (accepted) | background | `--color-emerald` | 8px circle |
| Status dot (dismissed) | background | `--color-red` | 8px circle |
| Status dot (pending) | background | `--color-amber` | 8px circle (tab badge only) |
| Accepted card opacity | opacity | 0.55 | — |
| Dismissed card opacity | opacity | 0.35 | — |
| Banner background | background | `rgba(240, 178, 50, 0.04)` | Amber-tinted |
| Banner icon | color | `--color-amber` | Warning triangle |
| Banner label | color | `--color-amber` | "You are viewing as a contributor" |
| Composer border on focus | border | `rgba(0, 212, 170, 0.3)` | Accent-tinted focus ring |
| Composer section name | color | `--color-accent` | Section anchor reference |
| Composer submit bg | background | `--color-accent` | Primary action |
| Dialog overlay | background | `rgba(0, 0, 0, 0.5)`, backdrop-filter blur(4px) | — |
| Dialog dismiss button bg | background | `rgba(239, 68, 100, 0.12)` | Red-tinted, not solid |
| Dialog dismiss button text | color | `--color-red` | — |
| Dialog dismiss button border | border | `rgba(239, 68, 100, 0.2)` | — |
| Dialog textarea focus border | border | `rgba(239, 68, 100, 0.3)` | Red-tinted focus, not accent |
| Dialog validation error | color | `--color-red` | — |
| Tab badge background | background | `--color-amber` | Unresolved count |
| Tab badge text | color | `--color-bg` | Dark on amber |
| Reply author | color | `--color-accent` | Distinguishes from card author |
| Add-suggestion affordance bg | background | `--color-accent-dim` | — |
| Add-suggestion affordance border | border | `rgba(0, 212, 170, 0.15)` | — |


## Spacing

All values on the 4px grid.

| Context | Value | Usage |
|---------|-------|-------|
| Sidebar width | 280px | Fixed right panel |
| Sidebar header padding | 12px 16px | Internal padding |
| Sidebar list padding | 8px | Internal padding |
| Section group margin-top | 16px | Between section groups (first: 0) |
| Section group margin-bottom | 8px | Below section group header |
| Card padding | 12px | Internal padding |
| Card margin-bottom | 8px | Between cards |
| Card author-to-section gap | 2px | Between author line and section ref |
| Card section-to-text gap | 6px | Between section ref and suggestion text |
| Card text-to-actions gap | 8px | Between suggestion text and action buttons |
| Action button padding | 4px 10px | Internal padding |
| Action button gap | 8px | Between action buttons |
| Reply thread margin-top | 8px | Above thread separator |
| Reply thread padding-top | 8px | Below thread separator |
| Reply bubble margin-bottom | 6px | Between reply bubbles |
| Reply bubble padding | 6px 10px | Internal padding |
| Reply input margin-top | 6px | Below last reply or thread separator |
| Reply input actions gap | 6px | Between cancel/send |
| Reply input actions margin-top | 4px | Below textarea |
| Composer margin | 8px 0 16px | Vertical margin in editor flow |
| Composer padding | 16px | Internal padding |
| Composer context margin-bottom | 10px | Below context line |
| Composer textarea padding | 10px 12px | Internal padding |
| Composer actions gap | 8px | Between cancel/submit |
| Composer actions margin-top | 8px | Below textarea |
| Banner height | 40px | Fixed height |
| Banner padding | 8px 20px | Internal padding |
| Banner element gap | 8px | Between icon, label, author, status |
| Dialog width | 400px | Fixed |
| Dialog padding | 20px | Internal padding |
| Dialog prompt margin-bottom | 12px | Below prompt text |
| Dialog textarea padding | 10px 12px | Internal padding |
| Dialog actions margin-top | 12px | Below textarea |
| Dialog actions gap | 8px | Between cancel/dismiss |
| Tab badge size | 14px min-width, 14px height | Pill shape |
| Tab badge padding | 0 3px | Internal padding |
| Status dot size | 8px | Circle indicator |


## Interactions & Motion

### Interactions

| Trigger | Target | Response | Notes |
|---------|--------|----------|-------|
| Click tab bar chat icon | SuggestionSidebar | Sidebar slides in from right (280px). Icon gets `.sidebar-active` class (`--color-accent` text, `--color-accent-dim` bg). | Cmd+Shift+S keyboard shortcut. |
| Hover section heading (contributor) | Add-suggestion button | `[+]` affordance fades in on the heading row. | Only in contributor mode. |
| Click `[+]` on heading | SuggestionComposer | Composer slides in below the heading. Textarea receives focus. | Previous open composer closes first. |
| Type in composer textarea | Submit button | Submit enables when text >= 10 chars. Disables below threshold. | Character count not shown; the disabled state is the only signal. |
| Click Submit (composer) | SuggestionComposer | Composer closes. New suggestion card slides into the sidebar from right. | `createSuggestion` mutation fires. |
| Click Cancel (composer) | SuggestionComposer | Composer slides up and disappears. No data persisted. | Escape key also cancels. |
| Click Accept (card) | SuggestionCard | Card transitions to accepted state: opacity fades to 0.55, emerald dot and "Accepted" label appear, action buttons hide. | `resolveSuggestion(id, ACCEPT)` mutation. |
| Click Dismiss (card) | DismissReasonDialog | Dialog fades in with overlay. Focus moves to textarea. | Card stays at full opacity until dismiss confirmed. |
| Click Dismiss confirm (dialog) | SuggestionCard + Dialog | Dialog closes. Card transitions to dismissed state: opacity fades to 0.35, red dot and "Dismissed" label appear, reason text renders, action buttons hide. | `resolveSuggestion(id, DISMISS, reason)` mutation. |
| Click Reply (card) | Reply input | Reply textarea slides open below the thread. Focus moves to textarea. | Both author and contributor can reply, even on resolved suggestions. |
| Click Send (reply) | Reply thread | New reply bubble slides in at bottom of thread. Input closes. | `replySuggestion(id, text)` mutation. |
| Click Edit (contributor, own card) | SuggestionCard | Card text becomes editable inline. Save/cancel buttons replace action buttons. | Only while unresolved. `editSuggestion(id, text)` mutation on save. |
| Click Delete (contributor, own card) | Confirmation prompt | "Delete this suggestion?" inline confirmation. On confirm, card fades out and is removed. | Only while unresolved. `deleteSuggestion(id)` mutation. |
| Escape key | DismissReasonDialog | Dialog closes without dismissing. Focus returns to the dismiss button on the card. | Standard dialog dismiss pattern. |

### Motion

| Name | Duration | Easing | Property | Usage |
|------|----------|--------|----------|-------|
| `sidebar-toggle` | 200ms | ease-out | width, opacity | Sidebar slide in/out. Width transitions from 0 to 280px. |
| `card-resolve` | 150ms | ease-out | opacity | Card transitions from full opacity to accepted (0.55) or dismissed (0.35) |
| `dialog-appear` | 150ms | ease-out | opacity | Overlay and dialog fade in together |
| `dialog-slide` | 200ms | ease-out | transform (translateY, scale), opacity | Dialog slides up from 12px below with 0.97 scale to final position |
| `reply-expand` | 200ms | ease-out | height, opacity | Reply input area expands from 0 height |
| `composer-enter` | 200ms | ease-out | opacity, transform (translateY) | Composer slides down from 8px above |
| `card-enter` | 250ms | ease-out | opacity, transform (translateX) | New suggestion card slides in from 16px right |
| `state-change` | 150ms | ease-out | background, border-color, color | Hover/focus transitions on buttons and inputs |

**Reduced motion policy:** Replace all animations with instant state changes. `sidebar-toggle` becomes instant width change. `card-enter` becomes instant appearance. `dialog-appear` and `dialog-slide` become instant show. The state change itself is never removed, only the motion.


## Accessibility

### Keyboard Navigation

| Component | Keys | Behavior |
|-----------|------|----------|
| SuggestionSidebar toggle | Cmd+Shift+S | Show/hide sidebar |
| SuggestionCard | Enter | Focus first action button (Accept for author, Edit for contributor on own) |
| SuggestionCard | Tab | Cycle through action buttons within a card |
| SuggestionCard (contributor) | E | Edit own unresolved suggestion |
| SuggestionCard (contributor) | Delete/Backspace | Delete own unresolved suggestion (with confirmation) |
| SuggestionComposer | Cmd+Enter | Submit suggestion |
| SuggestionComposer | Escape | Close composer without submitting |
| DismissReasonDialog | Cmd+Enter | Submit dismiss reason |
| DismissReasonDialog | Escape | Close dialog, return focus to dismiss button |
| DismissReasonDialog | Tab | Cycle through textarea, cancel, dismiss confirm |
| Reply input | Enter | Submit reply (single line behavior) |
| Reply input | Escape | Close reply input |
| ContributorBanner | Not interactive | No keyboard targets |

### ARIA & Screen Reader

| Component | Role | ARIA | Announcement |
|-----------|------|------|--------------|
| SuggestionSidebar | `complementary` | `aria-label="Suggestions ({unresolvedCount} unresolved)"` | Count announced on change via `aria-live="polite"` on the header count element |
| SuggestionCard | `article` | `aria-label="Suggestion from {author} on {sectionTitle}"` | — |
| SuggestionCard (accepted) | `article` | `aria-label="Accepted suggestion from {author}"` | — |
| SuggestionCard (dismissed) | `article` | `aria-label="Dismissed suggestion from {author}"` | — |
| SuggestionComposer | `form` | `aria-label="Leave a suggestion on {sectionTitle}"` | — |
| SuggestionComposer textarea | `textbox` | `aria-label="Suggestion text"`, `aria-describedby` pointing to character requirement | — |
| ContributorBanner | `banner` | `aria-label="Contributor view"` | "Viewing as contributor. Spec authored by {authorName}." on page load |
| DismissReasonDialog | `dialog` | `aria-modal="true"`, `aria-label="Dismiss suggestion"` | Focus trapped. Escape closes. |
| DismissReasonDialog textarea | `textbox` | `aria-label="Dismiss reason"`, `aria-describedby` pointing to validation error | — |
| Tab bar badge | `status` | `aria-label="{count} unresolved suggestions"` | Count announced on change |
| Accept button | `button` | `aria-label="Accept suggestion"` | — |
| Dismiss button | `button` | `aria-label="Dismiss suggestion"` | — |
| Reply button | `button` | `aria-label="Reply to suggestion"` | — |

### Contrast & Targets

All color tokens are defined in `globals.css` with contrast ratios documented:
- `--color-text` (#e4e4e9) against `--color-bg-card` (#1c1c27): ~13:1
- `--color-text-secondary` (#9494a3) against `--color-bg-card`: ~5.5:1
- `--color-text-tertiary` (#55556a): decorative only (timestamps, dismissed reasons, section refs)
- `--color-accent` (#00d4aa) against `--color-bg-elevated` (#16161e): ~8.5:1
- `--color-emerald` (#44cc77) against `--color-bg-card`: sufficient for status indicators
- `--color-amber` (#f0b232) against `--color-bg`: sufficient for badge background

All interactive targets meet 44x44px minimum. Action buttons use full card width as the interactive row. The tab bar chat icon uses the full 34x34px icon area within a 40px-tall tab bar. The add-suggestion `[+]` affordance uses the full heading row as the hover target.


## Content Constraints

| Element | Min | Max | Overflow | Placeholder |
|---------|-----|-----|----------|-------------|
| Suggestion text | 10 chars | 2000 chars | Wraps, no truncation | "Write your suggestion..." |
| Dismiss reason | 10 chars | 500 chars | Wraps | "Why are you dismissing this suggestion?" |
| Reply text | 1 char | 1000 chars | Wraps | "Reply to this suggestion..." |
| Card author name | — | 32 chars | Truncate with ellipsis | — |
| Card section ref | — | — | Truncate with ellipsis | — |
| Card timestamp | Fixed | Fixed | N/A (relative format) | — |
| Banner author name | — | 32 chars | Truncate with ellipsis | — |
| Dialog title | Fixed | Fixed | N/A | — |
| Reply thread | 0 replies | No limit | Thread scrolls within card (max-height: 200px, then overflow-y auto) | — |
| Suggestions per section | 0 | No limit | Cards stack vertically | — |

**Detached suggestions:** When a suggestion's `section_id` no longer matches any heading in the current spec draft, the card renders at the bottom of the sidebar in a "Detached" group. The section ref line shows the original `section_title` with an amber notice: "Referenced section was modified" in 11px `--color-amber`.


## Verification Criteria

### SuggestionSidebar
- [ ] Sidebar renders at 280px width with `surface-elevated` class
- [ ] Suggestions grouped by `section_title`, cards ordered by `created_at` within each group
- [ ] Section group headers use `type-table-header` (11px mono uppercase `--color-text-tertiary`)
- [ ] Header count reflects total suggestions; tab badge reflects unresolved count only
- [ ] Empty state shows "No suggestions yet." centered in 13px `--color-text-secondary`
- [ ] Sidebar toggle slides in/out with 200ms ease-out (instant under reduced motion)
- [ ] Sidebar scrolls independently of the editor

### SuggestionCard
- [ ] Pending cards at full opacity with `.surface` class
- [ ] Accepted cards at opacity 0.55, emerald dot, "Accepted" label, action buttons hidden
- [ ] Dismissed cards at opacity 0.35, red dot, "Dismissed" label, reason text visible, actions hidden
- [ ] Author sees Accept/Dismiss/Reply on pending cards
- [ ] Contributor sees Edit/Delete on own unresolved cards, Reply only on others'
- [ ] Reply thread renders below actions, separated by `--color-border-light` top border
- [ ] Reply bubbles use `--color-bg-elevated` background with `--color-accent` author name
- [ ] Card text wraps at 2000 chars without truncation

### SuggestionComposer
- [ ] Appears inline below clicked section heading with slide-down animation
- [ ] Section name rendered in `--color-accent` mono 11px
- [ ] Submit disabled (bg: `--color-text-tertiary`) when text < 10 characters
- [ ] Submit enabled (bg: `--color-accent`) when text >= 10 characters
- [ ] Escape key closes composer without submission
- [ ] Cmd+Enter submits when valid
- [ ] Only one composer open at a time

### ContributorBanner
- [ ] Renders at 40px height with amber-tinted background `rgba(240, 178, 50, 0.04)`
- [ ] Label "You are viewing as a contributor" in 11px/500 `--color-amber`
- [ ] Author name in 12px/600 `--color-text`
- [ ] Banner is non-interactive (no keyboard targets)
- [ ] `aria-label="Contributor view"` present

### DismissReasonDialog
- [ ] Opens with overlay (`rgba(0,0,0,0.5)` + backdrop blur) and focus trapped inside
- [ ] Textarea focus ring uses red-tinted `rgba(239, 68, 100, 0.3)`, not accent
- [ ] Dismiss confirm disabled when reason < 10 characters
- [ ] Validation error "Reason must be at least 10 characters" in 11px `--color-red`
- [ ] Escape closes dialog without dismissing; focus returns to the card's dismiss button
- [ ] Dialog width 400px, padding 20px

### General
- [ ] Token audit passes with zero hardcoded color/spacing/font values outside of globals.css
- [ ] All interactive elements have visible focus indicators using the accent ring pattern
- [ ] Reduced motion: all animations replaced with instant state changes
- [ ] All interactive targets meet 44x44px minimum
- [ ] No text element uses `--color-text-tertiary` for actionable content (decorative only)
- [ ] Detached suggestions render at bottom of sidebar with amber "Referenced section was modified" notice
- [ ] Tab bar badge disappears when unresolved count reaches 0


## Figma / Visual Reference

No Figma file exists for this feature. The prototype at `working-docs/contributor-suggestions-prototype.html` serves as the visual reference. It is a self-contained HTML file with all design tokens, interactive states, and three views: Author Mode (ceremony editor with sidebar), Contributor Mode (read-only editor with composer and banner), and Suggestion History (resolution timeline).
