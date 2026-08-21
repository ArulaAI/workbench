# Design Spec: Dashboard Learning Curation

> Prototype: [learning-prototype.html](../../working-docs/learning-prototype.html)
> Design system: [globals.css](../../dashboard/frontend/app/globals.css)
> Design decisions: [surface-design-decisions.md](../../working-docs/surface-design-decisions.md)

## Layout

Two-panel. Left panel is wider (420px) because the content is narrative prose, not compact metrics. Right panel holds the curation work.

```
┌────────────────────────────────────────────────────────────────────┐
│  [Topbar: "Learning" in violet + feature count + observation count] │
├────────────────────────┬───────────────────────────────────────────┤
│  LEFT (420px)          │  RIGHT (flex)                             │
│  Narrative-dominant    │  Action-dominant                           │
│  Scrolls independently │  Scrolls independently                    │
│                        │                                           │
│  Portfolio             │  Proposed Changes (in violet)              │
│  Coverage    94%  ↑    │  ┌─────────────────────────────────────┐  │
│  First-pass  86%  ↑    │  │ Ⓑ [TEMPLATE]                       │  │
│  Escalations  0   ↓    │  │ Add error-path requirement...       │  │
│  Rework       0   ↓    │  │ → writes to PRD template            │  │
│                        │  │ ┌─violet tinted block──────────┐    │  │
│  Coverage rose from    │  │ │ "For each flow, specify..."  │    │  │
│  78% to 94%...         │  │ └──────────────────────────────┘    │  │
│                        │  │ ▸ Evidence — 6 obs, weight 12.5     │  │
│  Defect Pipeline       │  │ [Accept] [Dismiss]                  │  │
│  Ⓐ ✓ GWT verified...  │  └─────────────────────────────────────┘  │
│  Ⓑ ⚠ Error paths...   │  ┌─────────────────────────────────────┐  │
│  ✓ Audit-clean...      │  │ Ⓐ [CONVENTION]                     │  │
│  Ⓒ ⚠ No design spec.. │  │ Prefer Given/When/Then...           │  │
│                        │  │ ...                                 │  │
│  Pipeline  2  ↓        │  └─────────────────────────────────────┘  │
│  Spec cmplx 3  →       │                                           │
└────────────────────────┴───────────────────────────────────────────┘
```

Left panel: 420px fixed. Background: subtle gradient `#0e0e14` to `#100f16`. Border-right: 1px `--border`. Padding: 28px 32px 48px.

Right panel: flex. Background: `--bg`. Padding: 24px 32px 64px.

## How This Differs from Outcome Review

| Dimension | Outcome Review | Learning |
|-----------|---------------|----------|
| Left panel width | 340px | 420px (narrative needs room) |
| Left panel bg | Flat `--bg-1` | Subtle gradient (warmer) |
| Accent color | Emerald (approval) | Violet (editorial) |
| Content density | Metric-heavy, compact | Narrative-heavy, generous spacing |
| Topbar title color | `--emerald` | `--violet` |
| Right panel cards | Judgment cards with option buttons | Proposal cards with violet change blocks |
| Section header color | `--text` | `--violet` for "Proposed Changes" |
| Narrative size | 12px (secondary to metrics) | 13px, line-height 1.8 (the star) |

## Typography Mapping

| Element | Role | Size | Weight | Font | Color |
|---------|------|------|--------|------|-------|
| "Learning" in topbar | Page title | 20px | 600 | Sans | `--violet` |
| "Portfolio" header | Section header | 15px | 600 | Sans | `--violet` |
| Portfolio subtitle | Item meta | 11px | 400 | Sans | `--text-3` |
| Trajectory labels | Item meta | 11px | 400 | Sans | `--text-2` |
| Trajectory values | Mono value | 13px | 600 | Mono | Per-status color |
| Trajectory "from" | Caption | 10px | 400 | Mono | `--text-2` |
| Trajectory arrows | Mono value | 10px | 400 | Mono | `--emerald` (improving) |
| LLM narrative | Body (star) | 13px | 400 | Sans | `--text-2`, line-height 1.8 |
| Narrative strong | Body strong | 13px | 500 | Sans | `--text` |
| Feature section head | Section header | 15px | 600 | Sans | `--text` |
| Feature section intent | Body | 12px | 400 | Sans | `--text-2` |
| Feature section agg | Item meta | 11px | 400 | Sans | `--text-3` |
| Lesson title (strong) | Item title | 13px | 500 | Sans | `--text` |
| Lesson body | Body | 12px | 400 | Sans | `--text-2`, line-height 1.6 |
| Failure box label | KPI label | 9px | 500 | Mono | `--text-4`, uppercase |
| Failure box value | Metric value | 20px | 600 | Mono | Per-status color |
| Failure box detail | Caption | 10px | 400 | Sans | `--text-3` |
| "Proposed Changes" | Section header | 15px | 600 | Sans | `--violet` |
| Proposal title | Item title | 13px | 500 | Sans | `--text` |
| Proposal badge | Badge | 8px | 600 | Mono | Per-type color |
| Proposal mechanism | Item meta | 11px | 400 | Mono | `--text-3` |
| Change text block | Body | 12px | 400 | Sans | `--text-2`, line-height 1.6 |
| Evidence trigger | Item meta | 11px | 400 | Sans | `--text-3` |
| Evidence observations | Caption | 10px | 400 | Sans | `--text-3` |
| Observation weight | Caption | 9px | 400 | Mono | `--text-4` |

## Trajectory Metrics (Left Panel)

Compact tabular rows, not boxed grid. The narrative is the star; metrics are supporting context.

```
Coverage       94%   ↑  from 78% on auth
First-pass     86%   ↑  from 64% on auth
Escalations     0    ↓  from 3 on auth
Rework          0    ↓  from 4 on auth
```

- Label: 11px `--text-2`, min-width 100px
- Value: 13px/600 mono, colored per-status
- Arrow: 10px mono, `--emerald` for improvement
- From: 10px mono, `--text-2`
- Row padding: 5px 0
- No background, no borders, no boxes

## LLM Narrative (Left Panel)

The centerpiece of the left panel. More prominent than Outcome Review's summary.

- Font: 13px/400 sans (one step up from OR's 12px)
- Line-height: 1.8 (more generous than OR's 1.7)
- Color: `--text-2` (strong: `--text`)
- Paragraphs separated by `<br><br>` within one container
- Bottom border: 1px `--border-s`, margin-bottom 24px
- No section header above it (flows from the trajectory metrics)

## Per-feature Lessons (Left Panel)

Section with three-layer header: feature name (15px) → intent (12px) → aggregate (11px).

Individual lessons:

```
┌──────────────────────────────────────────────┐
│ Ⓐ ✓  Given/When/Then criteria verified       │  good: emerald tint
│      automatically. All 10 structured...      │
└──────────────────────────────────────────────┘

┌──────────────────────────────────────────────┐
│ Ⓑ ⚠  User Flows still missing error paths.  │  warn: amber tint
│      Three consecutive features...            │
└──────────────────────────────────────────────┘
```

- Good: `rgba(68,204,119,0.03)` bg, `rgba(68,204,119,0.06)` border
- Warn: `rgba(240,178,50,0.03)` bg, `rgba(240,178,50,0.06)` border
- Icon: 13px SVG (checkmark for good, info-circle for warn)
- Ref-marker: 16px circle, colored per-type, positioned inline before title
- Padding: 10px 14px, radius 8px, margin-bottom 6px

## Failure Classification (Left Panel)

Two compact boxes side by side below the lessons.

- Background: `--bg-2`, radius 8px, padding 10px 14px
- Label: 9px mono uppercase `--text-4`
- Value: 20px/600 mono, colored
- Detail: 10px `--text-3`, line-height 1.5
- Separated from lessons by top border `--border-s` and 16px margin

## Proposal Cards (Right Panel)

### Active (proposed)

```
┌──────────────────────────────────────────────────┐
│  Ⓑ [TEMPLATE]  Add error-path requirement...     │  padding: 18px 20px
│  → writes to PRD template → User Flows section   │  bg: --bg-1, radius: 10px
│  ┌─────────────────────────────────────────────┐  │
│  │ "For each flow, specify what happens when   │  │  violet-tinted block
│  │  the primary action fails..."               │  │
│  └─────────────────────────────────────────────┘  │
│  ▸ Evidence — 6 observations, weight 12.5         │
│  [Accept] [Dismiss]                               │
└──────────────────────────────────────────────────┘
```

### Accepted (collapsed)

```
┌──────────────────────────────────────────────────────────────┐
│  Ⓑ [TEMPLATE]  Add error-path requirement...    ✓ Accepted  │  opacity: 0.5
└──────────────────────────────────────────────────────────────┘
```

### Dismissed (animated out)

Card animates: opacity → 0, height → 0, removed from flow.

## Change Text Block

The exact guidance being proposed. Visually distinct from description text.

- Background: `rgba(139,92,246,0.03)` (violet tint)
- Border-left: 2px solid `rgba(139,92,246,0.25)` (violet)
- Padding: 12px 16px, radius 7px
- Font: 12px/400, `--text-2`, line-height 1.6
- Strong text: `--text`
- Emphasis (proposed additions): `--accent`, normal style, weight 500

## Proposal Type Badges

| Type | Background | Color |
|------|-----------|-------|
| TEMPLATE | `--violet-soft` | `--violet` |
| CONVENTION | `--accent-soft` | `--accent` |
| AUDIT | `--blue-soft` | `--blue` |

## Expandable Evidence (Right Panel)

Collapsed by default. Trigger: 11px `--text-3` with caret icon.

Expanded panel:
- Background: `--bg`, radius 8px, padding 12px 16px
- Pattern description: 11px `--text-2`, strong: `--text`
- Mini trend chart: compact rows (feature | value | tiny bar)
- Observation rows: 10px `--text-3`, icon + description + feature tag + weight badge
- Feature tags: 9px mono `--text-4`, right-aligned
- Weight badges: 9px mono `--text-4`

## Cross-panel Ref-markers

Same system as Outcome Review but using the Learning page's color palette:

| Marker | Left panel (lesson) | Right panel (proposal) |
|--------|--------------------|-----------------------|
| Ⓐ | emerald circle on Given/When/Then lesson | emerald circle on Convention proposal |
| Ⓑ | amber circle on error-paths lesson | amber circle on Template proposal |
| Ⓒ | blue circle on design-spec lesson | blue circle on Audit proposal |

## Accept/Dismiss Buttons

**Accept**: `--accent` bg, `--bg` text, radius 7px, 11px/500
**Dismiss**: transparent bg, 1px `--border`, `--text-3` text, radius 7px, 11px/500

Hover: Accept brightens 10%. Dismiss gets `--text-2` text and lighter border.

## Empty States

- **No completed features**: left panel shows "No features completed yet. Trajectory data appears after the first feature ships." Right panel: "No proposals. The synthesis pipeline generates proposals after analyzing completed features."
- **No proposals (features completed but nothing actionable)**: left panel renders normally with trajectory and lessons. Right panel: "All learnings are within expected patterns. No changes proposed."
- **LLM unavailable**: narrative block omitted. Trajectory metrics and lessons render without the synthesized story.
