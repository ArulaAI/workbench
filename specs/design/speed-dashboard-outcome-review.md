# Design Spec: Dashboard Outcome Review

> Prototype: [outcome-review-prototype.html](../../working-docs/outcome-review-prototype.html)
> Design system: [globals.css](../../dashboard/frontend/app/globals.css)
> Design decisions: [surface-design-decisions.md](../../working-docs/surface-design-decisions.md)

## Layout

Two-panel. Left panel is persistent judgment context. Right panel is the scrollable work area.

```
┌──────────────────────────────────────────────────────────────────┐
│  [Topbar: "Outcome Review" in emerald + feature + date]          │
├──────────────────┬───────────────────────────────────────────────┤
│  LEFT (340px)    │  RIGHT (flex)                                 │
│  Fixed, scrolls  │  Scrolls independently                        │
│  independently   │                                               │
│                  │  Judgments (Name → Intent → Agg)               │
│  Feature name    │  ┌─────────────────────────────────┐          │
│  ─────────────   │  │ UNVERIFIABLE  ISBN validation    │          │
│  94%  coverage   │  │ Description...                   │          │
│  12/14 criteria  │  │ [Option 1] [Option 2] [Option 3] │          │
│  ─────────────   │  │ ▸ Show evidence                  │          │
│  Summary text... │  └─────────────────────────────────┘          │
│  ─────────────   │  ┌─────────────────────────────────┐          │
│  ✓ Guardian      │  │ UNCOVERED  CSV import            │          │
│  ✓ Coherence     │  │ ...                              │          │
│  ⚠ Security      │  └─────────────────────────────────┘          │
│  ─────────────   │                                               │
│  0 of 2 resolved │  Full Requirements (Name → Intent → Agg)      │
│                  │  S1  Submit defect report        2/2 ✓        │
│  ═══════════════ │  S2  See triage result           2/2 ✓        │
│  [Approve & Ship]│  S3  Trivial defects             2/2 ✓        │
│  [Request Rework]│  S4  Validate input format       1/2 (!)      │
│  Resolve all...  │  ...                                          │
└──────────────────┴───────────────────────────────────────────────┘
```

Left panel: 340px fixed. Background: `--bg-1`. Border-right: 1px `--border`.
Right panel: flex. Background: `--bg`. Padding: 24px 32px 64px.

## Typography Mapping

| Element | Role | Size | Weight | Font | Color |
|---------|------|------|--------|------|-------|
| "Outcome Review" in topbar | Page title | 20px | 600 | Sans | `--emerald` |
| Feature name (left) | Section header | 15px | 600 | Sans | `--text` |
| Feature meta (left) | Item meta | 11px | 400 | Sans | `--text-3` |
| Hero metrics (left) | KPI value | 24px | 600 | Mono | `--accent` / `--text` |
| Metric labels (left) | KPI label | 9px | 500 | Mono | `--text-3`, uppercase |
| Executive summary (left) | Body | 12px | 400 | Sans | `--text-2`, line-height 1.7 |
| Finding labels (left) | Body | 11px | 400 | Sans | `--text-2` |
| Finding detail (left) | Caption | 10px | 400 | Sans | `--text-3` |
| Progress ("0 of 2") | Mono value | 11px | 400 | Mono | `--text-3` (strong: `--text-2`) |
| "Judgments" section header | Section header | 15px | 600 | Sans | `--text` |
| Section intent | Body | 12px | 400 | Sans | `--text-2` |
| Section aggregate | Item meta | 11px | 400 | Sans | `--text-3` |
| Judgment title | Item title | 13px | 500 | Sans | `--text` |
| Judgment badge | Badge | 8px | 600 | Mono | Per-type color |
| Judgment ref | Caption | 9px | 400 | Mono | `--text-4` |
| Judgment description | Body | 12px | 400 | Sans | `--text-2`, line-height 1.6 |
| Option buttons | Badge | 11px | 500 | Sans | `--text-2` (selected: `--accent`) |
| Evidence trigger | Item meta | 11px | 400 | Sans | `--text-3` |
| Evidence criteria | Item meta | 11px | 400 | Sans | `--text-2` |
| Evidence method | Caption | 9px | 400 | Mono | `--text-4` |
| Requirement title | Item title | 13px | 500 | Sans | `--text-2` |
| Requirement ID | Caption | 10px | 400 | Mono | `--text-4` |
| Requirement status | Mono value | 10px | 500 | Mono | Per-status color |

## Left Panel Element Hierarchy

Top to bottom, every element justifies its presence by helping the team judge items on the right:

1. **Feature identity** (15px name + 11px meta): what am I judging?
2. **Outcome metrics** (24px hero in `--bg-2` cards, 2-column grid): aggregate picture at a glance
3. **Executive summary** (12px narrative): the system's case, read once
4. **Automated findings** (icon + 11px label + 10px detail per row): guardian, coherence, security verdicts
5. **Judgment progress** (mono "N of M resolved"): how far along am I?
6. **Verdict action** (pinned to bottom of panel): approve/rework always reachable

Verdict action pinned using flex layout: `context-scroll` is `flex: 1; overflow-y: auto`. `ctx-action` has `flex-shrink: 0` and top border.

## Judgment Cards

### Expanded (unresolved)

```
┌──────────────────────────────────────────────┐
│  [UNVERIFIABLE]  ISBN format validation  S4  │  padding: 18px 20px
│                                              │  bg: --bg-1, radius: 10px
│  Description text explaining the issue...    │
│                                              │
│  [Will test manually] [Needs test] [Block]   │  gap: 6px between options
│                                              │
│  ▸ Evidence — S4: 1 of 2 criteria passed     │  11px, --text-3
└──────────────────────────────────────────────┘
```

### Collapsed (resolved)

```
┌──────────────────────────────────────────────────────────────┐
│  [UNVERIFIABLE]  ISBN format validation    → Will test manually │  padding: 12px 20px
└──────────────────────────────────────────────────────────────┘
```

Structural changes on resolve:
- Padding: 18px → 12px
- Description: hidden
- Options: hidden
- Evidence trigger: hidden
- Chosen answer: appears inline, 11px `--accent`

## Option Buttons

Default: 1px `--border`, `--bg` background, `--text-2` text. Radius: 7px. Padding: 6px 14px.

Hover: `--bg-2` background, `rgba(255,255,255,0.08)` border, `--text` color.

Selected: `--accent-soft` background, `rgba(0,212,170,0.15)` border, `--accent` text.

## Inline Evidence

Expandable per judgment card. Triggered by clicking the evidence trigger line.

- Container: `--bg` background, radius 8px, padding 12px 16px
- Criteria rows: icon + text + method label, separated by `--border-s`
- Pass icon: emerald checkmark
- Unverifiable icon: blue info circle
- Uncovered icon: amber info circle
- Method labels: "verified by test", "schema check", "file exists", "manual check needed", "not verified" (self-describing, not abbreviated)

## Full Requirements Section

Below the judgment cards on the right panel. Collapsed by default.

- Section header: three-layer (Name → Intent → Aggregate)
- Items: caret + ID (10px mono) + title (13px/500) + status (10px mono, colored)
- Clean-pass items: no caret (`.no-expand`), hidden caret placeholder for alignment
- Items with issues: functional caret, expandable criteria detail
- Expanded criteria: same format as inline evidence criteria rows

## Automated Findings Strip (Left Panel)

Compact rows, one per finding type:

```
[✓ icon (20px box, emerald-soft bg)]  Product Guardian — approved     PASS
                                       No vision drift. Aligned...
```

- Icon: 20px square, rounded 6px, tinted background
- Label: 12px/400, `--text-2` (strong: `--text`)
- Detail: 11px/400, `--text-3`
- Verdict: 10px mono, colored (PASS: emerald, MEDIUM: amber, FAIL: red)

## Post-approval State

Natural collapse. No mode switch. The ceremony's resolved state IS the artifact.

- Right panel: judgment cards show collapsed one-liners. Full Requirements remains expandable.
- Left panel: verdict action shows "Approved" with timestamp and `--emerald` color. Rework button hidden.
- No structural layout changes. The reduced card heights give the summary and metrics more visual weight naturally.

## Color Palette

Emerald is the accent for this page. Approval is the ceremony's goal.

| Use | Color |
|-----|-------|
| Topbar title | `--emerald` |
| Approve button | `--accent` (teal) bg, `--bg` text |
| Approved state | `--emerald` text |
| Judgment UNVERIFIABLE badge | `--blue-soft` bg, `--blue` text |
| Judgment UNCOVERED badge | `--amber-soft` bg, `--amber` text |
| Judgment FAILED badge | `--red-soft` bg, `--red` text |
| Resolved answer | `--accent` text |
| Approve disabled | 0.25 opacity |

## Empty State (Auto-approved)

When no judgment items exist:

- Left panel: metrics, summary, findings render normally
- Right panel: "No items need judgment. All criteria verified automatically." (12px, `--text-3`)
- Left panel verdict: green "Auto-approved" indicator instead of Approve/Rework buttons
- The page is immediately the artifact. No ceremony needed.
