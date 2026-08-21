# Design Spec: Dashboard Landing Page

> Prototype: [landing-editorial.html](../../working-docs/landing-editorial.html)
> Design system: [globals.css](../../dashboard/frontend/app/globals.css)
> Layout spec: [pm-surface-design.md](../../working-docs/pm-surface-design.md) lines 50-118

## Layout

T-shape editorial grid. Three columns, center splits horizontally. Sidebars span full height.

```
┌──────────┬─────────────────────────┬──────────┐
│          │          JUDGE           │          │
│  DEFINE  │    (the lead story)      │  LEARN   │
│          ├─────────────────────────┤          │
│  (left   │         EXECUTE          │  (right  │
│  sidebar)│    (operational status)  │  sidebar)│
│          │                         │          │
└──────────┴─────────────────────────┴──────────┘
```

CSS grid: `grid-template-columns: 260px 1fr 320px; grid-template-rows: 1fr 1fr`.
Gap: 1px with `background: var(--border)` on parent (same pattern as Define page column gaps).

The sidebars span both rows: Define uses `grid-row: 1/3`, Learn uses `grid-row: 1/3`.
Judge occupies `grid-column: 2; grid-row: 1`. Execute occupies `grid-column: 2; grid-row: 2`.

## Typography Mapping

| Element | Role | Size | Weight | Font | Color |
|---------|------|------|--------|------|-------|
| Greeting | Page title | 20px | 600 | Sans | `--text` |
| Project context | Item meta | 11px | 400 | Sans | `--text-4` |
| Panel labels | Section header | 15px | 600 | Sans | Per-phase color |
| Panel subtitles | Item meta | 11px | 400 | Sans | `--text-3` |
| Feature names | Item title | 13px | 500 | Sans | `--text` |
| Body/descriptions | Body | 12px | 400 | Sans | `--text-2` |
| Hero metrics (Judge) | KPI value | 28px | 600 | Mono | Per-status color |
| Metric labels | KPI label | 9px | 500 | Mono | `--text-3`, uppercase |
| Progress percentages | Mono value | 12px | 500 | Mono | Per-status color |
| Defect severity | Badge | 8px | 600 | Mono | Per-severity color |
| Defect names | Caption | 11px | 400 | Sans | `--text-2` |
| Section labels (mono) | Table header | 9px | 500 | Mono | `--text-4`, uppercase |
| Trend values | Mono value | 11px | 500 | Mono | Per-status color |
| Status bar | Caption | 10px | 400 | Sans | `--text-4` |

## Topbar

Greeting + project context. No page title (the landing page IS the dashboard home).

```
Good morning, Sanjay                    speed · feature/continuous-learning
```

Left: 20px/600 greeting. Right: 11px/400 `--text-4` project + branch.

## Panel Design (shared base)

All four panels share:
- Background: `--bg` (sidebars: `--bg-1` for subtle depth separation)
- Padding: 20px 24px
- Overflow-y: auto (each panel scrolls independently if needed)
- Panel label: 15px/600, colored per phase
- Panel subtitle: 11px/400, `--text-3`, 16px margin-bottom

## Define Panel (Left Sidebar)

Background: `--bg-1`. Label color: `--violet`.

### Vision warning

When `overview.md` missing:
- Dashed border: 1.5px `rgba(239,68,100,0.20)`, radius 9px
- Gradient background from `rgba(239,68,100,0.025)`
- Title: 14px/600 `--red`
- Description: 11px `--text-2`
- CTA: 11px `--violet`

### Draft specs

Each draft spec item:
- 26px icon box (rounded 6px, tinted background)
- Name: 13px/500 `--text`
- Meta: 11px/400 `--text-3` ("PRD + RFC · unplanned")
- Right chevron: `--text-4`, brightens to `--text-3` on hover
- Hover: `rgba(255,255,255,0.02)` background

### Defect list

Section label: 9px mono uppercase "Defects · 9"

Each defect:
- Severity badge: 8px mono in tinted pill (P0: red, P2: amber, P3: dimmed)
- Name: 11px `--text-2`, truncated with ellipsis
- P3 and lower: dimmed (opacity 0.35)

## Judge Panel (Top Center, Lead Story)

Background: `--bg`. Label color: `--emerald`.

### When review is pending (lead story state)

Maximum visual weight. The most content of any panel.

- Panel subtitle: feature name + date ("Defect Pipeline · completed today")
- Summary narrative: 13px `--text-2`, line-height 1.7 (strong: `--text`)
- Hero metrics row: flex, gap 28px
  - Each metric: 28px/600 mono value + 9px mono label
  - Coverage in `--accent`, criteria in `--text`, guardian as checkmark, critical count
- Decisions section: 12px/500 `--amber` label with icon, decisions listed below
- Primary CTA: `--accent` bg, `--bg` text, 13px/600, radius 8px, padding 8px 20px

### When no review is pending (calm state)

Reduced visual weight. The panel recedes.

- Summary of last completed review OR "No features awaiting review"
- No hero metrics (they belong to the active review)
- No CTA

## Execute Panel (Bottom Center)

Background: `--bg`. Label color: `--accent`.

### Running features

Each feature row:
- Pulsing dot (6px, status color, `animation: pulse 2.5s`)
- Name: 13px/500 `--text`
- Subtitle: 11px/400 `--text-3` ("1 task awaiting input")
- Progress bar: 64px wide, 3px height, colored fill
- Percentage: 12px/500 mono, status color

### Escalation card

When a task is blocked and needs input:
- Container: `--bg-1` bg, radius 8px, 1px border tinted amber
- Badge: 8px mono "INPUT" in `--amber-soft` bg
- Label: 11px `--text-2` (feature + task + context)
- Question: 12px `--text-2` (code in mono, strong for the decision point)
- Input row: text input + Send button
  - Input: `--bg` bg, 1px `--border`, radius 6px, 12px font
  - Send: `--accent` bg, `--bg` text, 11px/600, radius 6px

## Learn Panel (Right Sidebar)

Background: `--bg-1`. Label color: `--violet` (dimmed: opacity 0.6).

### Coverage trend

Section label: 9px mono uppercase.

Each trend row:
- Feature name: 12px `--text-2` (current feature: `--text`/500)
- Bar: 48px wide, 3px height, colored fill
- Value: 11px/500 mono, colored

### Insights

Cards with tinted backgrounds:
- Good: `rgba(68,204,119,0.04)` bg, `rgba(68,204,119,0.08)` border
- Warn: `rgba(240,178,50,0.04)` bg, `rgba(240,178,50,0.08)` border
- Text: 11px `--text-2`, line-height 1.6
- Icon: 12px SVG inline before text

### Escalation trend

Same row format as coverage trend but values are counts, no bars.

## Variable Visual Weight

The layout doesn't rearrange. Positions are fixed. Weight changes based on content:

| Project state | Judge panel | Execute panel |
|---------------|-------------|---------------|
| Review pending | Lead story: summary + hero metrics + CTA | Normal: features + escalation |
| Features running, no review | Calm: last review summary or empty | Prominent: progress + escalation |
| Nothing active | Empty state | Empty state |

The center panels absorb visual attention when active. The sidebars provide persistent context regardless of center state.

## Status Bar

Full width below the grid. Height: 26px. Background: `--bg-1`. Top border: 1px `--border`.

Left: connection dot + "Connected" + project name (mono) + feature/defect counts.
Right: running feature indicators (name + task count + pulsing dot).

## Panel Colors

| Panel | Label color | Tint |
|-------|-------------|------|
| Define | `--violet` | `--bg-1` sidebar |
| Judge | `--emerald` | `--bg` center |
| Execute | `--accent` | `--bg` center |
| Learn | `--violet` (0.6 opacity) | `--bg-1` sidebar |

## Empty States

- **Define, no specs**: "No specs found. Create a spec to get started."
- **Judge, no completed features**: "No features completed yet."
- **Execute, nothing running**: "No features currently executing."
- **Learn, no completed features**: "Coverage trends appear after features complete."

All empty states: 12px `--text-3`, line-height 1.6.

## Hover and Interaction

- Draft spec items: bg tint on hover, chevron brightens
- Defect items: opacity reduction on hover
- Judge CTA: brightness(1.1) on hover
- Escalation Send button: standard button hover
- Trend rows: no hover (read-only)
- Insight cards: no hover (read-only)
- Panel labels: no hover (navigation is in the sidebar, not the panel headers)
