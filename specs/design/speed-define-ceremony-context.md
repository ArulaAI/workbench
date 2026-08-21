# Design: Define Ceremony — Context Package

> See [product spec](../product/speed-define-ceremony.md) for product context (stories S1, S2, S13).
> See [tech RFC](../tech/speed-define-ceremony-context.md) for API surface and data model.
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
  Two surfaces: the intent input page (/define/new) and the context
  panel within the ceremony editor (/define/:feature). Also covers
  the intent anchor, progressive assembly loading, and the
  historical context view (/define/:feature/history). Everything
  else (editor, validation, suggestions, commitment, bootstrap,
  ratification) belongs to sibling design specs.
-->


## Scope

This spec covers four surfaces:

- **Intent input page** (`/define/new`) — where the author declares what they want to build
- **Context panel** (left column of `/define/:feature`) — the 7-source briefing delivered alongside the editor
- **Intent anchor** — the feature name and intent preview at the top of the context panel, with inline edit for scope refinement
- **Historical context view** (`/define/:feature/history`) — frozen snapshot vs. current state comparison

Everything else in the ceremony editor is covered by sibling specs: the editor and validation gutter ([editor](../tech/speed-define-ceremony-editor.md)), the suggestion sidebar ([contributor](../tech/speed-define-ceremony-contributor.md)), the commit bar and ratification ([commit](../tech/speed-define-ceremony-commit.md)), and the bootstrap wizard ([bootstrap](../tech/speed-define-ceremony-bootstrap.md)). The `CeremonyLayout` component that composes all of these together is defined in the editor spec.


## Design Intent

> See [design principles](../../working-docs/define-ceremony-design-principles.md) for the 8 principles governing all ceremony surfaces.

**Direction:** Context delivery is the ceremony's first impression. The author declares intent, the system assembles a brief. The BLUF (Bottom Line Up Front) presents the synthesized findings full-width before the editor appears. The author reads the brief, clicks "Start writing," and the BLUF transitions to a 320px sidebar with drill-down sections. The sidebar is reference material — the BLUF already delivered the critical information.

**Do not:** Show a loading spinner that blocks the full page during assembly. Use skeleton loaders with pulsing animations (use opacity fade). Apply accent color to context items (accent is reserved for code references only within the context panel). Add illustration or decorative empty-state artwork. Make the context panel visually compete with the editor. Use borders without paired shadows on elevated elements. Treat empty and unavailable as the same state — they carry different information.


## Pages / Routes

| Route | User Flow | Description |
|-------|-----------|-------------|
| `/define/new` | Declaring intent | IntentInput card, centered. Transitions to `/define/:feature` on successful assembly. Bootstrap flow intercepts here when cold start detected (covered by bootstrap design spec). |
| `/define/:feature` (BLUF) | Reading the brief | First view after assembly. Full-width synthesized summary of critical findings, warnings, and scope confirmation. Author reads the brief, then clicks "Start writing" to enter the editor. |
| `/define/:feature` (editor) | Authoring with context | Three-panel layout. Context panel (left, 320px) with intent anchor and drill-down sections. Editor (center). Suggestion sidebar (right, covered by contributor spec). |
| `/define/:feature/history` | Viewing historical context | Two-column comparison: frozen snapshot (left) vs. current state (right). Accessible from ceremony editor and portfolio grid for completed features. |


## Layout Structure

### Global Layout

No changes to global layout. The IconRail (52px, left) remains visible. Content fills the remaining viewport. These surfaces render within the existing content region.

### Regions

| Region ID | Position | Width | Internal Layout | Scroll | Closable | Shortcut |
|-----------|----------|-------|-----------------|--------|----------|----------|
| intent-input | Content area (`/define/new`) | Full content width, max 720px centered horizontally and vertically | Vertical stack, centered | No | No | — |
| bluf-view | Content area (`/define/:feature`, initial state) | Full content width, max 600px centered | Vertical stack: anchor, divider, findings, action | Yes (page scroll) | No (dismissed by "Start writing") | — |
| context-panel | Left side of ceremony editor | 320px fixed (48px collapsed) | Vertical stack: intent anchor + collapsible sections | Yes (independent of editor) | Yes (collapses to icon rail) | Cmd+Shift+C |
| history-view | Content area (`/define/:feature/history`) | Full content width, two equal columns with 1px divider | Left: snapshot. Right: diff. Each column scrolls independently. | Yes (per column) | No | — |

### Intent Input Layout

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│                                                                 │
│              ┌─────────────────────────────────┐                │
│              │                                 │                │
│              │  What do you want to build?     │                │
│              │  ▏                              │                │
│              │                                 │                │
│              │         Describe your intent    │                │
│              │         and SPEED will deliver  │                │
│              │         context from your       │                │
│              │         codebase.               │                │
│              │                                 │                │
│              └─────────────────────────────────┘                │
│                                                                 │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

The card is a `.surface` element (border + shadow, `--color-bg-card`). Centered both horizontally and vertically in the content area. Max width 720px. The field auto-grows vertically to accommodate multiline intent.

### Context Panel Layout

```
┌────────────────────────┐
│ sort-auth-by-last-act… │  ← feature name (mono, secondary)
│ Users should be able   │  ← intent preview (2-line clamp)
│ to sort the auth list… │
│ ──────────             │  ← centered 40% divider
│                        │
│ ▸ Codebase         3   │  ← ContextSection
│ ▸ Learnings        2   │
│ ▸ Defects          0   │
│ ▸ Project Knowledge 3  │
│ ▸ Vision           ●   │
│ ▸ Related Features 1   │
│ ▸ Audit History    4   │
│                        │
└────────────────────────┘
```

**Intent anchor.** The top of the panel orients the author: the feature name (mono, 12px, `--text-2`) as a compact system-derived label, and the author's intent text below it (13px, 400, `--text-3`). The intent preview is clamped to 2 lines. A centered 40%-width divider (1px, `--border`) separates the premise from the response.

The intent preview is editable inline. No pencil icon, no edit button. Clicking the text activates `contenteditable`: the clamp lifts, text color promotes to `--text`, and an accent glow ring appears. Enter commits and triggers re-assembly. Escape cancels. Editability is an earned behavior, not a visible affordance. The author discovers it when they need to refine scope.

**Context sections.** The 7 sections below the divider correspond to the 7 fields of the `ContextPackage` type from the foundation RFC. Each section uses the existing `Section` component from IntelPanel (collapsible header with chevron + title + count).

Each section has a subtitle — a one-line question that orients the author on what the section answers. The subtitle is always visible (11px, 400, `--text-3`), positioned below the header row and left-aligned with the title. The same text appears as a native `title` tooltip on the section title.

| Section | Subtitle |
|---------|----------|
| Codebase | What code exists in this area? |
| Learnings | What has the team learned from working here? |
| Defects | What's broken in this area right now? |
| Project Knowledge | What conventions apply here? |
| Vision | Is there a product direction to align with? |
| Related Features | Is anyone else working in this area? |
| Audit History | What have past spec audits flagged here? |

### BLUF View Layout

The BLUF (Bottom Line Up Front) is the first thing the author sees after context assembly completes. It occupies the full editor width, with the context panel and editor hidden. The author reads the synthesized findings, then clicks "Start writing" to transition to the three-panel editor layout. The BLUF is a moment, not a fixture — it does its job and gets out of the way.

See [design principles](../../working-docs/define-ceremony-design-principles.md) for the BLUF rationale.

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│         sort-auth-by-last-activity                              │
│         Users should be able to sort the auth                   │
│         list by last activity                                   │
│         7 sources assembled · 4 files scoped · 2s ago           │
│                                                                 │
│                    ──────────                                   │
│                                                                 │
│         ┌─────────────────────────────────────────┐             │
│         │ ⚠ Product vision is stale. Vision       │             │
│         │   alignment cannot be verified.          │             │
│         └─────────────────────────────────────────┘             │
│                                                                 │
│         DEFECTS IN THIS AREA                                    │
│         major  Query validator accepts invalid                  │
│                attribute combinations                           │
│         ·  No critical defects                                  │
│                                                                 │
│         LEARNINGS FROM PAST FEATURES                            │
│         high  Queryable attributes require index                │
│               migration                                         │
│         high  E2E tests for query attributes must               │
│               test all 7 query types                            │
│                                                                 │
│         SCOPED TO                                               │
│         Users.php  query validator                              │
│         accessedAt  exists in schema, not queryable             │
│         UsersTest.php  unit tests                               │
│         UsersBase.php  e2e, 24h throttle                        │
│                                                                 │
│         CLEAR                                                   │
│         ·  No related features in this area                     │
│         ·  No prior audit findings                              │
│                                                                 │
│                   [ Start writing ]                             │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Structure.** The BLUF reads top to bottom like a one-page brief:

1. **Anchor** — feature name (mono, 12px, `--text-3`), intent text (15px, 600, `--text`), assembly metadata (11px, `--text-3`). Centered divider below.
2. **Warnings first** — uncertainty surfaces immediately. Missing or stale vision, failed sources, low scope confidence. Red-tinted banner with icon. If no warnings, this section is absent.
3. **Defects** — critical and major defects with severity badges. If none, a "No critical defects" all-clear line.
4. **Learnings** — high-confidence findings with confidence badges. Only high-confidence learnings appear in the BLUF; medium and low are available in the drill-down panel.
5. **Scoped to** — the codebase files in compact form (filename + short description). Confirms the system found the right area.
6. **Clear** — sources that were checked and returned empty. Dim lines confirming nothing was found. Tells the author "we looked, there's nothing" rather than leaving silence.
7. **Start writing** — accent button, centered. Dismisses the BLUF and transitions to the three-panel editor layout.

**What doesn't appear in the BLUF:** Low-confidence learnings, project knowledge details, full audit history findings, related feature details. These are drill-down information available in the sidebar panel after the author starts writing.

**Transition.** Clicking "Start writing" hides the BLUF view and reveals the context panel (320px left) + editor (center). The context panel contains the same information as the BLUF but structured as collapsible sections for reference during writing.

### Codebase Section Design

The Codebase section uses a cluster-based layout instead of a flat file list. Files are grouped by CSG (codebase semantic graph) cluster. The cluster name (what the area does) is the headline; file paths are supporting detail.

```
Tight scope (4 files, 3 clusters):

  Query validation                    2
  Users.php · UsersTest.php

  Schema & data model                 1
  accessedAt in Migration V19,
  not currently queryable

  E2E coverage                        1
  UsersBase.php
  24h throttle on accessedAt updates


Broad scope (142 files, 12 clusters):

  ⚠ Scope is broad — 12 areas
    matched. Refine your intent
    to narrow.

  Query validation                    4
  Users.php · UsersTest.php + 2

  Auth endpoints                      5
  TokenHandler.php · SessionManager + 3

  Schema & migrations                 3
  V19.php · V22.php · V24.php

  E2E test coverage                   3
  UsersBase.php + 2

  ... 8 more areas · Show all 142 files


Empty (no graph):

  Codebase                            —
  No semantic graph available.
  Run speed plan or start bootstrap.


Empty (no matches):

  Codebase                            —
  No files matched your intent.
  Refine your intent.
```

**Cluster design:**
- **Cluster dot** — 6px circle, positioned before the cluster name. Uses a muted palette (50% opacity of the semantic colors: violet, blue, emerald, amber, accent, rose, cyan) cycling through so adjacent clusters are visually distinct. Not semantic — purely for visual differentiation.
- **Cluster name** — 13px, 500, `--text`. The semantic description of what the area is. Right-aligned count in mono `--text-3`.
- **File names** — 11px mono, `--text-3`. First 2 filenames shown inline, separated by `·`. Overflow shows `+ N` link that expands the cluster in place to reveal all filenames.
- **Cluster description** — 12px, `--text-3`. Optional. Shown when the cluster has a meaningful description beyond the file list (e.g., "24h throttle on accessedAt updates").

**Scenarios the design handles:**

| Scenario | Files | Clusters | Treatment |
|----------|-------|----------|-----------|
| Tight scope | 3-5 | 1-3 | All clusters visible. Quick confirmation scoping worked. |
| Normal scope | 10-20 | 3-5 | Clusters with `+ N` overflow on file lists. Scan cluster names to orient. |
| Broad scope | 50-100+ | 8-15 | Amber warning banner. Top 4 clusters shown. "N more areas · Show all" overflow link expands to full cluster list. |
| Single file | 1 | 1 | Single cluster with one file and description. |
| No graph | 0 | 0 | No chevron, em-dash count, dimmed title. Message: "No semantic graph available. Run speed plan or start bootstrap." |
| No matches | 0 | 0 | No chevron, em-dash count, dimmed title. Message: "No files matched your intent. Refine your intent." |

**Key distinction:** "No graph" (source unavailable) and "No matches" (source checked, nothing found) have different messages and different actions. Per design principle 5: uncertainty is the most important signal.

### Learnings Section Design

Confidence drives visual hierarchy. High-confidence and locked learnings are the signal; low-confidence learnings are speculative. The BLUF already surfaced high-confidence items, so the sidebar is drill-down for the full list.

```
3 learnings (confidence-ordered):

  high   Queryable attributes require
         index migration
         from add-search-filter

  high   E2E tests for query attributes
         must test all 7 query types
         from user-query-filters

  medium accessedAt updates are throttled
         to once per 24h window
         from login-tracking


8+ learnings (overflow):

  high   Queryable attributes require
         index migration
         from add-search-filter

  high   E2E tests for query attributes
         must test all 7 query types
         from user-query-filters

  medium accessedAt updates are throttled
         to once per 24h window
         from login-tracking

  ── 5 more learnings ──────────


0 learnings:

  Learnings                           —
  No prior learnings in this area.
```

**Confidence hierarchy:**
- **High / locked** — full opacity. Confidence badge in emerald (high) or violet (locked). Learning text in `--text-2`. Source feature in 10px `--text-3` below.
- **Medium** — full opacity. Amber badge. Same text treatment.
- **Low** — dimmed to 50% opacity. Badge in `--text-3`. The author sees them but their eye skips past unless they're looking.

**Overflow (5+ items):** The first 5 learnings are shown (sorted by confidence: high/locked first, then medium, then low). Remaining items are collapsed behind a centered "N more learnings" divider link. Clicking expands all in place.

**Scenarios:**

| Scenario | Items | Treatment |
|----------|-------|-----------|
| Normal | 1-5 | All items visible, confidence-sorted |
| Many | 5+ | First 5 shown, overflow link for rest |
| Empty | 0 | No chevron, em-dash count, "No prior learnings in this area." |
| Unavailable | — | No chevron, em-dash count, "Observation data unavailable. Check .speed/memory/observations/" |

### Defects Section Design

Severity drives visual hierarchy. Critical defects demand attention; minor defects recede. The BLUF already surfaced critical and major defects.

```
Normal (2 defects):

  major  Query validator accepts invalid
         attribute combinations

  minor  E2E test flakiness on accessedAt
         throttle window


Critical present (3 defects):

  critical  Auth token bypass on expired
            sessions

  major     Query validator accepts invalid
            attribute combinations

  major     Migration V22 missing rollback


Many (10+ defects, overflow):

  critical  Auth token bypass on expired
            sessions

  major     Query validator accepts invalid
            attribute combinations

  major     Migration V22 missing rollback

  major     Rate limiter bypass on batch
            endpoints

  minor     Inconsistent error codes on
            validation failure

  ── 5 more minor defects ──────────
```

**Severity hierarchy:**
- **Critical** — full opacity. Red badge. These are show-stoppers the spec must address.
- **Major** — full opacity. Amber badge.
- **Minor** — dimmed to 50% opacity (`.dimmed` class). Visible but the eye skips past.

**Overflow (5+ items):** First 5 shown (severity-sorted: critical first, then major, then minor). Minor defects collapse first behind an overflow link.

**Scenarios:**

| Scenario | Items | Treatment |
|----------|-------|-----------|
| Normal | 1-5 | All items visible, severity-sorted, minor dimmed |
| Critical | 1+ critical | Critical items at full weight, unmissable |
| Many | 5+ | Overflow, minor items collapse first |
| Empty | 0 | No chevron, em-dash count, "No open defects in this area." |
| Unavailable | — | No chevron, em-dash count, "Defect data unavailable. Check .speed/defects/" |

### Project Knowledge Section Design

Same item pattern as Learnings: confidence badge + text on primary line, source ("observation" or "manual") on supporting line. Confidence drives hierarchy identically.

The distinction from Learnings: Learnings are scoped observations from past feature runs in this area. Knowledge is curated project-wide conventions. The supporting line shows the source type instead of a feature slug.

```
Normal (3 items):

  high    All new queryable fields need
          a migration spec
          observation

  high    Query validators follow the
          ALLOWED_ATTRIBUTES constant pattern
          manual

  medium  E2E test base classes use admin
          session creation
          manual
```

**Scenarios:**

| Scenario | Items | Treatment |
|----------|-------|-----------|
| Normal | 1-5 | Confidence-sorted, same hierarchy as Learnings |
| Many | 5+ | First 5 shown, overflow link |
| Empty | 0 | No chevron, em-dash count, "No project knowledge established yet." |
| Unavailable | — | No chevron, em-dash count, "Project knowledge unavailable. Check .speed/memory/project-knowledge.json" |

### Vision Section Design

Vision is a single status indicator, not a list of items. It answers a binary question with three states.

```
Available:

  ● Product vision defined

  SPEED is a structured execution
  pipeline that transforms product
  specifications into verified...


Stale:

  ● Vision may be outdated

  SPEED is a structured execution
  pipeline that transforms product
  specifications into verified...


Missing:

  ● No product vision

  Vision alignment cannot be verified.
  Consider running bootstrap or
  creating specs/product/overview.md.
```

**Status indicator:** 8px colored dot + status text. Emerald for available, amber for stale, red for missing. Per design principle 5 (uncertainty is the most important signal), missing vision is red, not just absent.

**Vision preview:** When available or stale, the vision content is shown as a 3-line truncated preview in `--text-2`. "Show more" expands to full content.

**Scenarios:**

| Scenario | Treatment |
|----------|-----------|
| Available | Emerald dot, "Product vision defined", content preview |
| Stale | Amber dot, "Vision may be outdated", content preview |
| Missing | Red dot, "No product vision", guidance message. Section remains expandable (not empty class) — it has content to show. |
| Unavailable | No chevron, em-dash count, "Vision document could not be read. Check specs/product/overview.md" |

### Related Features Section Design

Compact list of feature names with ceremony state badges. No supporting detail line — the feature name and state are sufficient.

```
Normal (1 feature):

  user-query-filters  ratified


Active (2 features, one in-flight):

  user-query-filters    ratified
  auth-session-cleanup  drafting
```

**State badges:** Pill badges using CeremonyStatus values. Ratified (emerald), committed (blue), drafting (`--text-3`), rejected (red), abandoned (`--text-3`).

**Scenarios:**

| Scenario | Items | Treatment |
|----------|-------|-----------|
| Normal | 1-3 | Feature name + state badge, one line per feature |
| Active | 1+ drafting | Drafting features are in-flight work in the same area — relevant to the author |
| Empty | 0 | No chevron, em-dash count, "No related features in this area." |
| Unavailable | — | No chevron, em-dash count, "Feature data unavailable. Check .speed/features/" |

### Audit History Section Design

Past audit findings use the same badge + text pattern as Defects, with severity badges. The supporting line shows the source feature and spec section the finding applies to.

```
Normal (2 findings):

  major  Missing acceptance criteria for
         NULL value handling
         from user-query-filters · Acceptance Criteria

  minor  No cross-reference to migration
         spec
         from user-query-filters · Dependencies


Many (7+ findings):

  major  Missing acceptance criteria for
         NULL value handling
         from user-query-filters · Acceptance Criteria

  major  Scope references non-existent
         helper function
         from add-search-filter · Scope

  minor  No cross-reference to migration
         spec
         from user-query-filters · Dependencies

  minor  User story missing priority field
         from add-search-filter · User Stories

  ── 3 more findings ──────────
```

**Item layout:** Severity badge + finding text on primary line (12px, `--text-2`). Source feature + section on supporting line (10px, `--text-3`, format: "from {feature} · {section}"). Minor findings dimmed.

**Scenarios:**

| Scenario | Items | Treatment |
|----------|-------|-----------|
| Normal | 1-5 | Severity-sorted, minor dimmed |
| Many | 5+ | Overflow, minor collapse first |
| Empty | 0 | No chevron, em-dash count, "No prior audit findings in this area." |
| Unavailable | — | No chevron, em-dash count, "Audit history unavailable. Check .speed/local/features/*/logs/" |

### Consistent Item Pattern

All 7 sections use the same visual rhythm for items. The content fields differ per type, but the layout is uniform:

```
Primary line:    [badge] text              12px / 400 / --text-2
Supporting line: attribution               10px / 400 / --text-3
```

| Section | Badge | Primary text | Supporting line |
|---------|-------|-------------|-----------------|
| Codebase | cluster dot (6px, muted color) | cluster name (12px/500/`--text`) | file names (10px mono `--text-3`) + optional description (11px `--text-2`) |
| Learnings | confidence (10px pill) | learning text | "from {feature-slug}" |
| Defects | severity (10px pill) | defect name | (none) |
| Project Knowledge | confidence (10px pill) | convention text | source type ("observation" / "manual") |
| Vision | status dot (8px) | status text | content preview |
| Related Features | state badge (10px pill) | feature name | (none) |
| Audit History | severity (10px pill) | finding text | "from {feature} · {section}" |

**Shared behaviors:**
- Minor/low items dimmed to 50% opacity (`.dimmed` class)
- 5+ items overflow with centered "── N more {type} ──" link
- Empty sections: no chevron, em-dash count, dimmed title, single-line message
- Unavailable sections: same treatment as empty but with a different message and path reference. Distinguishes "checked, nothing found" from "could not check."

### History View Layout

```
┌─────────────────────────────────────────────────────────────────┐
│  sort-auth-by-last-activity · Jane Doe · committed Mar 15      │
│                                                        ← Back  │
├───────────────────────────────┬─────────────────────────────────┤
│  SNAPSHOT FROM MAR 15         │  CHANGES SINCE SNAPSHOT         │
│                               │                                 │
│  ▸ Codebase            3      │  ▸ Codebase           +2 −1    │
│  ▸ Learnings           2      │  ▸ Defects            +1       │
│  ▸ Defects             0      │  ▸ Project Knowledge  ~1       │
│  ▸ Project Knowledge   5      │  ▸ Vision             ✓        │
│  ▸ Vision              ●      │                                 │
│  ▸ Related Features    1      │                                 │
│  ▸ Audit History       4      │                                 │
│                               │                                 │
└───────────────────────────────┴─────────────────────────────────┘
```

Left column uses `ContextSnapshot` component (frozen context package rendered as read-only collapsible sections). Right column uses `ContextDiff` component (grouped changes between snapshot and current state).


## Component Inventory

All components referenced here are defined in the [parent design spec](speed-define-ceremony.md#component-inventory). This section specifies rendering details unique to the context package surfaces.

| Component ID | Type | Location | Parent Region | Role in Context Surfaces |
|--------------|------|----------|---------------|--------------------------|
| IntentInput | new | `ceremony/IntentInput.tsx` | intent-input | Two fields: feature name (short identifier) and free-text intent (what the author wants to build). Submit on Enter or button. |
| BlufView | new | `ceremony/BlufView.tsx` | bluf-view | Full-width synthesized brief shown after assembly. Warnings, defects, learnings, scope, clear signals. "Start writing" dismisses to editor layout. |
| ContextPanel | modified | `editor/IntelPanel.tsx` | context-panel | Existing IntelPanel with `mode="ceremony"` prop. Adds Defects, Vision Status, Audit History sections. |
| ContextSection | existing | `editor/IntelPanel.tsx` | context-panel | Collapsible section with icon + title + count. No changes. |
| IntentAnchor | new | `ceremony/IntentAnchor.tsx` | context-panel, bluf-view | Feature name label + intent preview. In panel: inline contenteditable refinement. In BLUF: display only. |
| CodebaseCluster | new | `ceremony/CodebaseCluster.tsx` | context-panel (Codebase section) | Renders a CSG cluster: cluster name, file list with overflow, optional description. |
| HistoricalContextView | new | `ceremony/HistoricalContextView.tsx` | history-view | Page layout for `/define/:feature/history`. Header + two-column body. |
| ContextSnapshot | new | `ceremony/ContextSnapshot.tsx` | history-view (left) | Frozen context package rendered in read-only ContextSection components. |
| ContextDiff | new | `ceremony/ContextDiff.tsx` | history-view (right) | Change groups between snapshot and current state. |

### Component Props

Props are defined in the [parent design spec](speed-define-ceremony.md#component-props). Key props for context surfaces:

**IntentInput**: `onSubmit(featureName: string, intent: string)`, `disabled` (true during assembly). Two fields: feature name (13px mono, placeholder "feature-name") and intent text (18px sans, placeholder "What do you want to build?"). Feature name validates inline: lowercase, hyphens, alphanumeric, max 50 chars. Collision checked on blur.

**ContextPanel (ceremony additions)**: `mode: "editor" | "ceremony"`, `contextPackage: ContextPackage | null`, `loading: boolean`, `sources: SourceStatus[]`.

**IntentAnchor**: `featureName: string`, `intentText: string`, `onRefine(newIntent: string)`, `loading: boolean`.

**HistoricalContextView**: `feature: string`, `snapshot: ContextPackage`, `current: ContextPackage | null`, `ceremony: CeremonyInfo`.

**ContextSnapshot**: `contextPackage: ContextPackage`, `assembledAt: string` (ISO 8601).

**ContextDiff**: `snapshot: ContextPackage`, `current: ContextPackage`.


## Spacing

All values on the 4px grid.

| Context | Token/Value | Usage |
|---------|-------------|-------|
| Intent input card padding | 32px 24px | Generous internal padding around the field |
| Intent input field height (min) | 48px | Single-line minimum; auto-grows with content |
| Intent caption margin-top | 16px | Gap between field and helper text below |
| Context panel padding | 16px | Internal padding for the context-panel region |
| Context section gap | 12px | Between collapsible sections |
| Context section internal gap | 8px | Between items within a section |
| Context item row height (min) | 32px | Per-item row within a section |
| Context item icon size | 16px | Monochrome icons for file type, severity, etc. |
| Intent anchor padding | 16px 16px 12px | Top/sides/bottom of intent anchor area |
| Intent anchor feature name margin-bottom | 4px | Gap between feature name and intent preview |
| Intent anchor divider margin-top | 12px | Space above the centered divider |
| Intent anchor divider width | 40% | Centered, 1px height |
| History view column gap | 1px | Divider between snapshot and current columns |
| History view column padding | 20px | Internal padding per column |
| History view header height | 52px | Feature name, author, date bar |
| History view header padding | 12px 20px | Internal padding |
| Diff group gap | 12px | Between change groups (files, defects, conventions) |
| Diff item gap | 4px | Between individual change items within a group |
| Assembly source indicator gap | 8px | Between source status rows during loading |


## Typography

| Element | Role | Family | Size | Weight | Line-Height | Color |
|---------|------|--------|------|--------|-------------|-------|
| Intent input text | custom | `--font-sans` | 18px | 400 | 1.5 | `--color-text` |
| Intent placeholder | custom | `--font-sans` | 18px | 400 | 1.5 | `--color-text-tertiary` |
| Intent caption | `type-body` | `--font-sans` | 13px | 400 | 1.5 | `--color-text-tertiary` |
| Context section title | `type-section-header` | `--font-sans` | 13px | 600 | 1.4 | `--color-text` |
| Context section subtitle | custom | `--font-sans` | 11px | 400 | 1.3 | `--color-text-tertiary` |
| Context section count | `type-mono-value` | `--font-mono` | 13px | 500 | 1.4 | `--color-text-secondary` |
| Context item text | custom | `--font-sans` | 12px | 400 | 1.5 | `--color-text-secondary` |
| Context code reference | custom | `--font-mono` | 11px | 500 | 1.4 | `--color-accent` |
| Context item description | custom | `--font-sans` | 12px | 400 | 1.4 | `--color-text-secondary` |
| Context defect severity badge | custom | `--font-sans` | 10px | 500 | 1 | Per-severity color |
| Context vision indicator | custom | `--font-sans` | 10px | 500 | 1 | Status color (see Color Application) |
| Context learning source | custom | `--font-sans` | 10px | 400 | 1.4 | `--color-text-tertiary` |
| Context confidence badge | custom | `--font-sans` | 10px | 500 | 1 | Per-confidence color |
| Context audit finding | custom | `--font-sans` | 12px | 400 | 1.5 | `--color-text-secondary` |
| Context related feature name | custom | `--font-sans` | 12px | 400 | 1.5 | `--color-text` |
| Context related feature state | custom | `--font-sans` | 10px | 500 | 1 | Status color per state |
| Cluster name | custom | `--font-sans` | 12px | 500 | 1.4 | `--color-text` |
| Cluster count | custom | `--font-mono` | 10px | 400 | 1.4 | `--color-text-tertiary` |
| Cluster files | custom | `--font-mono` | 10px | 400 | 1.5 | `--color-text-tertiary` |
| Cluster description | custom | `--font-sans` | 11px | 400 | 1.4 | `--color-text-secondary` |
| Intent anchor feature name | custom | `--font-mono` | 12px | 500 | 1.4 | `--color-text-secondary` |
| Intent anchor preview (display) | `type-body` | `--font-sans` | 13px | 400 | 1.5 | `--color-text-tertiary` |
| Intent anchor preview (hover) | `type-body` | `--font-sans` | 13px | 400 | 1.5 | `--color-text-secondary` |
| Intent anchor preview (editing) | `type-body` | `--font-sans` | 13px | 400 | 1.5 | `--color-text` |
| Assembly source name | `type-caption` | `--font-sans` | 11px | 400 | 1.4 | `--color-text-tertiary` (pending), `--color-text` (complete) |
| Assembly source status | `type-caption` | `--font-sans` | 11px | 400 | 1.4 | `--color-accent` (complete), `--color-red` (error) |
| Low scope confidence warning | `type-body` | `--font-sans` | 13px | 400 | 1.5 | `--color-amber` |
| History header feature name | `type-section-title` | `--font-sans` | 15px | 600 | 1.4 | `--color-text` |
| History header metadata | `type-caption` | `--font-sans` | 11px | 400 | 1.4 | `--color-text-tertiary` |
| History snapshot label | `type-badge` | `--font-sans` | 11px | 500 | 1 | `--color-text-tertiary` |
| History snapshot date | `type-mono-value` | `--font-mono` | 13px | 500 | 1.4 | `--color-text-secondary` |
| Diff group header | `type-section-header` | `--font-sans` | 13px | 600 | 1.4 | `--color-text` |
| Diff item text | `type-body` | `--font-sans` | 13px | 400 | 1.5 | `--color-text-secondary` |
| Diff "New" badge | `type-badge` | `--font-sans` | 11px | 500 | 1 | `--color-emerald` |
| Diff "Removed" badge | `type-badge` | `--font-sans` | 11px | 500 | 1 | `--color-red` |
| Diff "Changed" badge | `type-badge` | `--font-sans` | 11px | 500 | 1 | `--color-amber` |
| "Back" link (history) | `type-caption` | `--font-sans` | 11px | 400 | 1.4 | `--color-text-tertiary` |


## Color Application

Accent within the context panel is restricted to code references (file paths, function names) and assembly completion indicators. No accent on section headers, item backgrounds, or decorative elements.

| Element | Property | Token | Notes |
|---------|----------|-------|-------|
| Intent input card background | background | `--color-bg-card` | `.surface` class |
| Intent input card border | border | `--color-border` | Part of `.surface` |
| Intent field text | color | `--color-text` | |
| Intent placeholder | color | `--color-text-tertiary` | |
| Intent caption | color | `--color-text-tertiary` | |
| Context panel background | background | `--color-bg-elevated` | `.surface-elevated` class |
| Context section chevron | color | `--color-text-tertiary` | Hover: `--color-text-secondary` |
| Context item path / code ref | color | `--color-accent` | File paths, function names in mono |
| Context item description | color | `--color-text-secondary` | |
| Context defect severity (P0) | color | `--color-red` | |
| Context defect severity (P2) | color | `--color-amber` | |
| Context defect severity (P3+) | color | `--color-text-tertiary` | Dimmed, opacity 0.35 |
| Context defect severity badge bg | background | 12% opacity of severity color | Matches landing page defect badge pattern |
| Context vision: available | color | `--color-emerald` | Filled circle indicator |
| Context vision: missing | color | `--color-red` | |
| Context vision: stale | color | `--color-amber` | |
| Context learning confidence high | color | `--color-emerald` | |
| Context learning confidence medium | color | `--color-amber` | |
| Context learning confidence low | color | `--color-text-tertiary` | |
| Context related feature state badge | background, color | Status color at 12%, status color | Reuse existing feature state badge pattern |
| Context audit finding severity | color | Per-severity color | Same mapping as defects |
| Intent anchor background | background | transparent | Sits within context panel |
| Intent anchor divider | background | `--color-border` | Centered 40%-width rule below intent preview |
| Intent anchor preview (hover) | background | `rgba(255, 255, 255, 0.03)` | Subtle background lift on hover |
| Intent anchor preview (editing) | background, box-shadow | `--color-bg-card`, `0 0 0 2px --color-accent-glow` | Active editing state |
| Assembly source: pending | color | `--color-text-tertiary` | |
| Assembly source: complete | color | `--color-accent` | Only place accent appears in loading state |
| Assembly source: error | color | `--color-red` | |
| Low scope confidence warning bg | background | `rgba(240, 178, 50, 0.08)` | `--color-amber` at 8% opacity |
| Low scope confidence warning text | color | `--color-amber` | |
| History view background | background | `--color-bg` | Base layer |
| History snapshot column bg | background | `--color-bg-elevated` | Left column, slightly raised |
| History current column bg | background | `--color-bg-card` | Right column, primary surface |
| History divider | border | `--color-border` | 1px vertical divider |
| History header background | background | `--color-bg-elevated` | Full-width bar |
| "Back" link | color | `--color-text-tertiary` | Hover: `--color-text-secondary` |
| Diff "New" badge | background, color | `rgba(68, 204, 119, 0.12)`, `--color-emerald` | |
| Diff "Removed" badge | background, color | `rgba(239, 68, 100, 0.12)`, `--color-red` | |
| Diff "Changed" badge | background, color | `rgba(240, 178, 50, 0.12)`, `--color-amber` | |
| Diff unchanged item | color | `--color-text-tertiary` | Present in both, no change |


## Elevation & Depth

| Element | Elevation Level | Treatment |
|---------|----------------|-----------|
| `/define/new` page background | 0 (base) | Flat, `--color-bg` |
| Intent input card | 2 | `.surface` class |
| Context panel | 1 | `.surface-elevated` class |
| Intent anchor | 0 (inset) | Flat within context panel. Separated from sections by centered divider. |
| Context sections | 0 (inset) | Flat within context panel. No additional elevation. |
| History view background | 0 (base) | Flat, `--color-bg` |
| History header | 1 | `.surface-elevated` class, full width |
| History snapshot column | 1 | `--color-bg-elevated` background |
| History current column | 2 | `.surface` class |


## States

### Page-Level States

#### Empty State (Intent Input, `/define/new`)

Centered `.surface` card on the base background. Contains:
- Feature name field (13px mono, `--text`, placeholder "feature-name" in `--text-3`). Validates inline: lowercase, hyphens, alphanumeric only, max 50 chars. Shows collision error on blur if name is taken.
- Intent field (18px sans, `--text`, placeholder "What do you want to build?" in `--text-3`). Free-form, auto-grows vertically.
- Below the fields, a single caption line: "Name your feature and describe your intent. SPEED will deliver context from your codebase." (13px sans, `--text-3`)

No sidebar, no editor, no validation. The card sits at vertical center of the content area. The feature name field is compact (single line, above the intent field). The intent field is the visual focus — large, inviting.

#### Loading State (Context Assembly)

After the author submits intent, the IntentInput card transitions:
1. Input field becomes read-only (text remains visible, cursor gone)
2. Below the field, the caption is replaced by an assembly progress list showing the 7 context sources

Assembly progress renders as a vertical stack of source names. Each source transitions independently:

```
  Semantic graph         ✓
  Learnings              ✓
  Defects                ●  ← assembling (text color)
  Project knowledge      ·  ← pending (tertiary)
  Vision                 ·
  Related features       ·
  Audit history          ·
```

- Pending: source name in `--color-text-tertiary`, dot marker in `--color-text-tertiary`
- Assembling: source name in `--color-text`, dot marker in `--color-text`
- Complete: source name in `--color-text`, checkmark in `--color-accent`
- Error: source name in `--color-text`, "x" marker in `--color-red`

Each source transitions from pending to complete via a 300ms opacity/color fade (`context-source-complete` motion token from parent design spec).

Once 3+ sources complete, the page transitions to the ceremony editor (`/define/:feature`). The context panel renders immediately with available sources. Remaining sources continue assembling within the panel, each section fading in as its source completes.

#### Populated State (Context Panel)

Context panel fully assembled. Intent anchor at top shows the feature name and intent preview. All 7 source sections rendered as collapsible `ContextSection` components below the divider. Each section shows its item count in the header. Sections with zero items still render (collapsed, count shows "0") so the author sees the full picture of what was checked.

Source display order within the panel:
1. Codebase (files and functions in the scoped area)
2. Learnings (observations and conventions from past features)
3. Defects (open defects in the scoped area)
4. Project Knowledge (curated conventions)
5. Vision Status (single indicator, not a list)
6. Related Features (other ceremonies touching overlapping files)
7. Audit History (findings from past spec audits)

The first section with items (typically Codebase) defaults to expanded. All others default to collapsed.

#### Low Scope Confidence

When the semantic graph produces no matches for the intent and falls back to full graph delivery, a warning bar appears between the intent anchor divider and the first section:

```
┌────────────────────────┐
│ ✏ "improve performance"│
├────────────────────────┤
│ ⚠ Scope confidence is  │
│   low. Refine your     │
│   intent to narrow     │
│   results.             │
├────────────────────────┤
│ ▸ Codebase        142  │
│   ...                  │
```

Warning uses `--color-amber` text on `rgba(240, 178, 50, 0.08)` background. Padding 8px 16px.

#### Context Panel Error State

Individual source failure: the section renders with an error indicator instead of content. The section header shows the source name + a red dot. Expanded, it shows: "Failed to load {source}" in `--color-red`, 13px sans. Other sections render normally. No retry affordance per-source (the author refines intent to re-trigger full assembly).

Full assembly failure (no sources complete): the IntentInput card shows an inline error below the field. "Context assembly failed. Check that the project has a valid .speed/ directory." in `--color-red`, 13px sans. A "Retry" text link in `--color-accent` re-triggers assembly.

#### Scope Refinement In Progress

When the author clicks the intent preview and edits inline:
- The 2-line clamp lifts, text promotes to `--text`, accent glow ring appears
- On Enter, context panel sections fade to 40% opacity (150ms, `state-change` motion token)
- As sources complete, sections update in place with new data (fade back to 100% opacity)
- The spec draft in the editor is preserved (context re-assembly does not affect it)

#### History View States

**Loading**: Both columns show content at 30% opacity fading in. The snapshot column loads from `context-package.json` (single file read, effectively instant). The current column loads from a fresh context assembly for the same scoped area (2-10 seconds, same pipeline as `declareIntent`).

**Populated**: Two-column layout. Left shows frozen snapshot sections. Right shows diff grouped by change type. Both columns scroll independently.

**No Snapshot**: Feature exists but has no persisted `context-package.json`. Single centered message: "No context snapshot available for this feature. Context persistence was not active when this spec was authored." (13px sans, `--color-text-secondary`, max-width 480px, centered.)

**Current Assembly Failed**: Snapshot loads. Right column shows: "Current context could not be assembled. The snapshot is still available for reference." (13px sans, `--color-text-secondary`.) No diff rendered.


### Interactive Element States

| Component | Enabled | Hover | Focus | Pressed | Disabled | Loading |
|-----------|---------|-------|-------|---------|----------|---------|
| IntentInput field | bg: `--color-bg-card`, border: `--color-border` | border: `--color-accent-glow` | ring: `--color-accent`, offset 2px | — | bg: `--color-bg-card`, opacity 0.4, cursor not-allowed | Input read-only, progress list below |
| ContextSection chevron | color: `--color-text-tertiary` | color: `--color-text-secondary` | ring: `--color-accent`, offset 2px | — | — | — |
| Intent preview (display) | color: `--color-text-tertiary`, 2-line clamp | bg: `rgba(255,255,255,0.03)`, color: `--color-text-secondary` | — | — | — | — |
| Intent preview (editing) | color: `--color-text`, clamp lifted | — | bg: `--color-bg-card`, ring: `--color-accent-glow` 2px | — | — | — |
| "Back" link (history) | color: `--color-text-tertiary` | color: `--color-text-secondary`, cursor pointer | outline: `--color-accent`, offset 2px | opacity 0.8 | — | — |
| Diff group chevron | color: `--color-text-tertiary` | color: `--color-text-secondary` | ring: `--color-accent`, offset 2px | — | — | — |


## Data Binding

| Element | Source Field | Format | Constraints |
|---------|-------------|--------|-------------|
| Intent text | `intent.text` | string | Free-form. Min 5 chars (submit disabled below). No length limit. Wraps to multiple lines. |
| Context: codebase items | `contextPackage.codebase[]` | structured | File path (mono, accent) + description (body, secondary). Max 20 visible; "Show all N" overflow link when > 20. |
| Context: learnings | `contextPackage.learnings[]` | structured | Learning text (body) + source feature name (caption, tertiary) + confidence badge. |
| Context: defects | `contextPackage.defects[]` | structured | Severity badge + name. Same rendering as landing page DefectRow. P3+ dimmed at opacity 0.35. |
| Context: project knowledge | `contextPackage.projectKnowledge[]` | structured | Convention text (body) + confidence badge + source label (caption, tertiary). |
| Context: vision status | `contextPackage.visionStatus` | `"available"` \| `"missing"` \| `"stale"` | Available: emerald dot + "Product vision defined". Missing: red dot + "No product vision". Stale: amber dot + "Vision may be outdated". |
| Context: vision content | `contextPackage.visionContent` | string \| null | Rendered as truncated preview (3 lines) within the Vision Status section when available. Expandable to full content. |
| Context: related features | `contextPackage.relatedFeatures[]` | structured | Feature name (body, text) + state badge (executing/completed/etc.) + overlapping file count (caption, tertiary). |
| Context: audit history | `contextPackage.auditHistory[]` | structured | Feature name (caption, tertiary) + finding text (body) + severity badge. Grouped by source feature. |
| Intent anchor: feature name | `intent.feature_name` | string | Slugified feature name in mono. Always visible. |
| Intent anchor: preview | `intent.text` | string | Author's intent text, 2-line clamp in display mode. Full text when editing. |
| Intent anchor: loading | assembly status | `"idle"` \| `"assembling"` \| `"complete"` | Sections dim during re-assembly after refinement. |
| Assembly sources | `contextAssemblyStatus.sources[]` | `{ name, status }` | 7 rows, each transitioning independently. |
| History snapshot sections | `snapshot.codebase[]`, `.learnings[]`, etc. | structured | Same rendering as ContextPanel sections via ContextSection. Read-only. |
| History snapshot date | `snapshot.assembled_at` | ISO 8601 | Formatted as relative time ("3 weeks ago") with full date in tooltip. |
| History ceremony metadata | `ceremony.author`, `ceremony.committed_at` | string | Author name and commit date in header bar. |
| Diff: files added | `current.codebase` minus `snapshot.codebase` (by path) | structured | File path (mono, emerald) + "New" badge. |
| Diff: files removed | `snapshot.codebase` minus `current.codebase` (by path) | structured | File path (mono, red, strikethrough) + "Removed" badge. |
| Diff: defects new | `current.defects` minus `snapshot.defects` (by name) | structured | Defect name + severity badge + "New" badge. |
| Diff: defects resolved | `snapshot.defects` minus `current.defects` (by name) | structured | Defect name + "Resolved" badge (emerald). |
| Diff: conventions changed | entries where `snapshot.projectKnowledge[].text` != `current.projectKnowledge[].text` | structured | Convention text with "Changed" badge. |
| Diff: vision status change | `snapshot.visionStatus` != `current.visionStatus` | string | "Vision was {old}, now {new}". |


## Interactions & Motion

### Interactions

| Trigger | Target | Response | Notes |
|---------|--------|----------|-------|
| Submit intent (Enter) | IntentInput | Field becomes read-only. Assembly progress list appears. Sources transition independently. On 3+ sources complete, navigate to `/define/:feature`. | Submit disabled when < 5 chars. |
| Click intent preview | IntentAnchor | Intent preview becomes contenteditable: 2-line clamp lifts, text promotes to `--text`, accent glow ring appears. On Enter, context re-assembles. On Escape, reverts to original text. | No visible edit affordance. Cursor change on hover is the only hint. Editability is earned behavior. |
| Click section chevron | ContextSection | Toggle collapsed/expanded. Preserves scroll position. | Same interaction as existing IntelPanel sections. |
| Click "Show all N" | Codebase section overflow | Section expands to show all items. Link text changes to "Show fewer". | Only appears when items > 20. |
| Navigate to history (portfolio) | Portfolio grid | Click "View history" link on a completed feature card. Navigates to `/define/:feature/history`. | Visible only for features with status `committed` (SP) or `ratified` (MP). Link renders as 11px `--text-3` text, hover: `--text-2`. |
| Navigate to history (editor) | Intent anchor | Click the feature name (mono text at top of context panel). Feature name acts as a link to the history view for completed ceremonies. | Only interactive when the ceremony is in `committed` or `ratified` state. During `drafting`, the feature name is plain text (no link affordance). Cursor change on hover is the only hint, same earned-behavior pattern as intent editing. |
| Click "Back" (history) | History header | "Back to ceremony" link navigates to `/define/:feature`. | Always available in history view. 11px `--text-3`, hover: `--text-2`. Right-aligned in the header bar. |
| Escape (history) | History view | Navigate back to `/define/:feature`. | Keyboard shortcut for the back action. |
| Toggle diff group | ContextDiff group header | Toggle collapsed/expanded. Preserves scroll position in the right column. | |

### Motion

All motion tokens are defined in the [parent design spec](speed-define-ceremony.md#motion). Context-specific usage:

| Name | Duration | Easing | Property | Usage |
|------|----------|--------|----------|-------|
| `state-change` | 150ms | ease-out | background, border-color, color, opacity | Hover/focus transitions on all interactive elements |
| `context-source-complete` | 300ms | ease-out | opacity, color | Assembly: source transitions from pending to complete |
| `panel-slide` | 200ms | ease-out | transform (translateX), opacity | Context panel collapse/expand |

**Reduced motion policy:** Replace all animations with instant state changes. `context-source-complete` becomes instant color change. `panel-slide` becomes instant show/hide. The state change itself is never removed, only the motion.


## Responsive Behavior

| Breakpoint | Context Panel | History View |
|------------|---------------|--------------|
| < 1024px | Not supported. Ceremony editor requires 1024px minimum. Fallback message links to portfolio mode (`/define`). | Not supported. "Historical context comparison requires a wider viewport." Link to portfolio mode. |
| 1024-1280px | Collapses to icon-only rail (48px). Click icon to overlay panel at 320px on top of editor. | Single column. Snapshot and current shown as tabs instead of side-by-side. Tab bar at top: "Snapshot" and "Changes". |
| 1280px+ | Full 320px panel, always visible alongside editor. | Full two-column layout: snapshot left, diff right. |


## Accessibility

### Keyboard Navigation

| Component | Keys | Behavior |
|-----------|------|----------|
| IntentInput | Enter | Submit intent |
| IntentInput | Tab | Move focus to next page element |
| ContextSection | Enter/Space | Toggle collapsed/expanded |
| ContextSection | Tab | Move to next section header |
| Intent preview | Click | Activate inline editing (contenteditable) |
| Intent preview (editing) | Enter | Submit refined intent, trigger re-assembly |
| Intent preview (editing) | Escape | Cancel edit, restore original text |
| Ceremony editor | Cmd+Shift+C | Toggle context panel collapse/expand |
| ContextDiff group | Enter/Space | Toggle collapsed/expanded |
| History tabs (< 1280px) | Arrow Left/Right | Switch between Snapshot and Changes tabs |
| History view | Escape | Navigate back to ceremony editor |

### ARIA & Screen Reader

| Component | Role | ARIA | Announcement |
|-----------|------|------|--------------|
| IntentInput | `search` | `aria-label="Declare what you want to build"` | — |
| ContextPanel | `complementary` | `aria-label="Context panel"` | — |
| ContextSection | `region` | `aria-expanded`, `aria-label="{title}"` | "{title}: {count} items, collapsed/expanded" |
| Assembly progress | `status` | `aria-live="polite"` | "{source} complete" announced per source |
| Low scope confidence warning | `alert` | `aria-live="assertive"` | "Scope confidence is low. Refine your intent to narrow results." |
| HistoricalContextView | `main` | `aria-label="Historical context for {feature}"` | — |
| ContextSnapshot | `region` | `aria-label="Context snapshot from {date}"` | — |
| ContextDiff | `region` | `aria-label="Changes since snapshot"` | — |
| History tabs (< 1280px) | `tablist` | `aria-label="Context comparison"` | Tab name announced on switch |

### Contrast & Targets

All color tokens are defined in `globals.css` with contrast ratios documented:
- `--color-text` (#e4e4e9) against `--color-bg-card` (#1c1c27): ~13:1
- `--color-text-secondary` (#9494a3) against `--color-bg-card`: ~5.5:1
- `--color-text-tertiary` (#55556a): decorative only, not used for actionable content
- `--color-accent` (#00d4aa) against `--color-bg-elevated` (#16161e): ~8.5:1

All interactive targets meet 44x44px minimum: section chevrons use the full section header as the click target. The intent input field exceeds this. The intent preview text area fills the panel width, exceeding the minimum.


## Content Constraints

| Element | Min | Max | Overflow | Placeholder |
|---------|-----|-----|----------|-------------|
| Intent text | 5 chars | No limit | Wraps to multiple lines, card grows vertically | "What do you want to build?" |
| Intent caption | Fixed | Fixed | N/A | — |
| Context section title | — | 32 chars | Truncate with ellipsis | — |
| Context item path | — | — | Truncate middle with ellipsis (keep filename visible) | — |
| Context item description | — | — | Truncate at 65 chars with ellipsis (existing `truncate()` utility) | — |
| Context defect name | — | — | Truncate with ellipsis | — |
| Context learning text | — | — | Truncate at 65 chars, expandable on click | — |
| Context knowledge text | — | — | Truncate at 65 chars, expandable on click | — |
| Context audit finding | — | — | Truncate at 65 chars with ellipsis | — |
| Context vision preview | — | 3 lines | Truncate with "Show more" link | — |
| Codebase items visible | 0 | 20 | "Show all N" overflow link | "(empty)" when 0 |
| Intent anchor feature name | — | 50 chars | Truncate with ellipsis | — |
| Intent anchor preview | 5 chars | No limit | 2-line clamp in display; unclamped in edit mode | — |
| Assembly source name | Fixed | Fixed | N/A | — |
| History feature name | — | 50 chars | Truncate with ellipsis | — |
| History author name | — | 32 chars | Truncate with ellipsis | — |
| Diff item text | — | — | Truncate at 65 chars | — |


## Implementation Notes

- The context panel extends `IntelPanel` (at `dashboard/frontend/components/editor/IntelPanel.tsx`) with a `mode` prop. In `"ceremony"` mode, the data source switches from the per-spec GraphQL queries (`CODEBASE_CONTEXT_QUERY`, `LESSONS_QUERY`, etc.) to the `contextPackage` prop. The existing `Section` component inside IntelPanel is reused without modification for all context sections.
- Three sections are ceremony-only: Defects, Vision Status, Audit History. Render them after the existing sections when `mode="ceremony"`. When `mode="editor"` (default), they do not render.
- The assembly progress list on `/define/new` polls `contextAssemblyStatus` via the GraphQL query defined in the [RFC](../tech/speed-define-ceremony-context.md#queries). Poll interval: 500ms. Stop polling when all sources are complete or errored.
- The transition from `/define/new` to `/define/:feature` happens client-side via `router.push` after the `declareIntent` mutation returns. The context package data carries over in client state (no re-fetch).
- The IntentAnchor uses `contenteditable` for inline editing. On submit (Enter), it calls the `refineIntent` mutation. On success, the `contextPackage` prop updates via query invalidation. During re-assembly, sections show a subtle opacity reduction (40%) until their source completes. The feature name is derived from `intent.feature_name` (slugified by the backend on `declareIntent`).
- The `truncate()` utility already exists in IntelPanel (line 73 of the current file). Reuse it for context item overflow.
- The codebase section "Show all N" overflow pattern: render the first 20 items, then a text link. Clicking it renders all items in place (no modal, no pagination). The link toggles to "Show fewer" which restores the 20-item cap.
- History view: the snapshot column is a straight render of a `ContextPackage` JSON file. The current column requires calling `assemble_context_package` for the same scoped area, which takes 2-10 seconds. Show the snapshot column immediately; show the diff column with a loading state until assembly completes.
- Diff computation for the history view runs client-side. Compare arrays by key fields: codebase by `path`, defects by `name`, knowledge by `text`, features by `name`. Vision status is a direct string comparison.
- The history view at viewports < 1280px uses a tab pattern instead of side-by-side columns. Two tabs: "Snapshot" and "Changes". The tab bar sits below the header. Standard tab behavior: arrow keys switch tabs, content swaps instantly (no transition per `tab-switch` motion token).


## Verification Criteria

### Intent Input (`/define/new`)
- [ ] IntentInput renders as a centered `.surface` card with 18px sans input and helper caption
- [ ] Submit is disabled when intent < 5 characters
- [ ] Assembly progress shows 7 sources transitioning independently from pending → complete/error
- [ ] Page transitions to `/define/:feature` (BLUF view) after assembly completes

### BLUF View
- [ ] BLUF renders full-width in the editor area, max 600px centered
- [ ] Context panel and editor are hidden while BLUF is visible
- [ ] Warnings (missing/stale vision, failed sources) appear first, before findings
- [ ] "Start writing" button dismisses BLUF and reveals the three-panel editor layout
- [ ] BLUF shows only high-confidence learnings; medium/low are in the sidebar only

### Intent Anchor
- [ ] Feature name in mono `--text-2`, intent preview in 13px/400 `--text-3`, 2-line clamp
- [ ] Centered 40%-width divider separates intent anchor from context sections
- [ ] Clicking intent preview activates contenteditable: clamp lifts, text promotes to `--text`, accent glow ring
- [ ] No visible edit affordance. Editability is earned behavior.
- [ ] Enter commits refinement and triggers re-assembly; Escape cancels

### Context Panel (general)
- [ ] Token audit passes with zero hardcoded color/spacing/font values outside of `globals.css`
- [ ] All 7 sections render in fixed order: Codebase, Learnings, Defects, Project Knowledge, Vision, Related Features, Audit History
- [ ] Each section has a subtitle (11px/400/`--text-3`) always visible below the header
- [ ] Subtitle also appears as native `title` tooltip on the section title
- [ ] Section titles: 13px/600/`--text`. Item text: 12px/400/`--text-2`. Supporting detail: 10px/400/`--text-3`. Badges: 10px/500.
- [ ] Empty sections: no chevron, em-dash count, dimmed title, single-line message
- [ ] Unavailable sections: same treatment as empty but different message with path reference
- [ ] 5+ items overflow with centered "── N more {type} ──" link; clicking expands in place
- [ ] Minor/low items dimmed to 50% opacity

### Codebase Section
- [ ] Items grouped by CSG cluster, not flat file list
- [ ] Each cluster has a 6px colored dot (muted palette, cycling)
- [ ] Cluster name (12px/500/`--text`) is the headline; file names (10px mono `--text-3`) are supporting detail
- [ ] Cluster file overflow: first 2 names shown, `+ N` link expands inline
- [ ] Broad scope (50+): amber warning banner, top 4 clusters, "N more areas · Show all" overflow
- [ ] No graph: "No semantic graph available. Run speed plan or start bootstrap."
- [ ] No matches: "No files matched your intent. Refine your intent."

### Learnings Section
- [ ] Confidence badge + text on primary line; "from {feature-slug}" on supporting line
- [ ] Confidence-sorted: high/locked first, then medium, then low
- [ ] Low-confidence items dimmed to 50%

### Defects Section
- [ ] Severity badge + defect name on primary line
- [ ] Severity-sorted: critical first, then major, then minor
- [ ] Minor defects dimmed to 50%

### Project Knowledge Section
- [ ] Confidence badge + convention text on primary line; source ("observation"/"manual") on supporting line
- [ ] Same confidence hierarchy as Learnings

### Vision Section
- [ ] 8px colored dot (emerald/amber/red) + status text
- [ ] Available/stale: 3-line content preview with "Show more"
- [ ] Missing: red dot + guidance message. Section remains expandable (not empty class).

### Related Features Section
- [ ] Feature name + CeremonyStatus badge, one line per feature
- [ ] State badges: ratified (emerald), committed (blue), drafting (`--text-3`), rejected (red), abandoned (`--text-3`)

### Audit History Section
- [ ] Severity badge + finding text on primary line; "from {feature} · {section}" on supporting line
- [ ] Minor findings dimmed

### General
- [ ] All interactive targets meet 44x44px minimum
- [ ] Reduced motion: all animations replaced with instant transitions
- [ ] Context panel collapses to 48px icon rail at viewports 1024-1280px
- [ ] History view: two-column at 1280px+, tab pattern at 1024-1280px
- [ ] Diff section names match context package field names (Codebase, not Files)


## Figma / Visual Reference

No Figma file exists for this feature. The prototypes at `working-docs/context-panel-prototype.html`, `working-docs/context-intent-prototype.html`, and `working-docs/context-history-prototype.html` serve as the visual reference. These are self-contained HTML files with all design tokens, interactive states, and scenario switching for every section.

See also [design principles](../../working-docs/define-ceremony-design-principles.md) for the rationale behind BLUF, earned attention, and uncertainty-first design decisions.
