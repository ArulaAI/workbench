---
status: draft
feature: speed-dashboard-audit-history
---

# Design: Dashboard Audit History Panel

> See [product spec](../product/speed-dashboard-audit-history.md) for product context.
> Design system: `dashboard/frontend/app/globals.css`

<!--
  WHO READS THIS SPEC
  This spec is consumed by AI coding agents as their primary implementation
  reference. Humans review it, but agents execute from it. Every section is
  structured for literal, unambiguous interpretation.

  THE #1 AGENT FAILURE MODE
  Agents fabricate design tokens. They generate plausible-looking variable
  names that don't exist in your design system. Every visual property in this
  spec must reference a token from the project's closed token set. If the
  token doesn't exist, flag it for addition to the design system. Never write
  a raw hex, pixel value, or font name outside of the token definitions.

  SCOPE
  This feature adds interactive audit history to the existing Findings tab
  of the IntelPanel sidebar. No new pages. No new panels. Verdict dots
  become clickable, shift-click compares two runs, findings list responds
  to the selection.
-->


## Design Intent

**Direction:** The audit history interaction lives entirely within the existing Findings tab of the IntelPanel. No new pages, no new panels. The verdict strip becomes interactive: dots become buttons, click selects a run, shift-click compares two. The findings list below responds to the selection. Minimal chrome, maximum information density. Feels like navigating git history in a terminal, not browsing a photo gallery.

**Do not:** Add a separate history page or modal. Use tabs to switch between runs (dots are the selector). Add animations beyond the existing `fvFadeIn` transition. Use accent color on non-selected dots. Introduce hover tooltips that block interaction. Add loading spinners for local file reads (they're instant).


## Pages / Routes

No new routes. All changes are within the IntelPanel component on the editor page (`/editor`). The verdict strip, run header, comparison view, and findings list are sub-regions of the existing Findings tab.

| Route | User Flow | Description |
|-------|-----------|-------------|
| `/editor` | View past audit (AH1) | Click verdict dot to load that run's findings |
| `/editor` | Compare two runs (AH2) | Shift-click two dots to enter comparison mode |
| `/editor` | Review persistent issues (AH4) | Latest findings tagged "persistent" when present in previous run |


## Layout Structure

### Global Layout

No changes to the global layout. The editor page uses a two-column structure: code editor (fluid) + IntelPanel sidebar (~320px, fixed width). The IntelPanel contains tabs (Findings, Reference, Health). All audit history changes are scoped to the Findings tab content area.

### Regions

| Region ID | Position | Width | Internal Layout | Scroll |
|-----------|----------|-------|-----------------|--------|
| verdict-strip | Top of Findings tab, fixed | Full panel width (~320px) | flex-col, gap 0 | no |
| run-header | Below verdict-strip, conditional | Full panel width | flex, space-between | no |
| comparison-header | Below verdict-strip, conditional (replaces run-header) | Full panel width | flex-col | no |
| findings-list | Below run-header or comparison-header | Full panel width | flex-col, gap 0 | yes (vertical) |
| comparison-list | Replaces findings-list in comparison mode | Full panel width | flex-col, gap 0 | yes (vertical) |


## Component Inventory

| Component ID | Type | Parent ID | Description |
|--------------|------|-----------|-------------|
| VerdictDot | modified | verdict-strip | Interactive button replacing static `fv-verdict-dot` span. Three visual states: default, selected, compare-selected. |
| RunHeader | new | run-header | Contextual banner showing relative timestamp of selected run with "Back to latest" link. Appears only when viewing a non-latest run. |
| ComparisonHeader | new | comparison-header | Summary banner showing two timestamps, issue counts, and net delta. Appears only in comparison mode. |
| ComparisonView | new | comparison-list | Grouped list of findings categorized as Removed, Unchanged, or Added between two audit runs. |
| FindingRow | modified | findings-list | Existing finding row, now also rendering "persistent" badge when issue appears in both latest and previous run. |

### Component Props

#### VerdictDot

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| status | `"pass"` \| `"warn"` \| `"fail"` | required | Determines dot color via `--color-emerald`, `--color-amber`, `--color-red` |
| selected | boolean | `false` | Single-click selection state. Shows border ring in `--color-border`. |
| compareSelected | boolean | `false` | Shift-click selection state. Shows border ring in `--color-accent`. |
| isLatest | boolean | `false` | Leftmost dot. Always renders at 100% opacity regardless of selection. |
| onClick | `() => void` | required | Fires on regular click |
| onShiftClick | `() => void` | required | Fires on shift+click |
| tooltip | string | required | Relative timestamp, e.g. "2h ago". Shown on hover via native `title` attribute. |

#### RunHeader

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| relativeTime | string | required | Human-readable relative timestamp of the selected run |
| onBackToLatest | `() => void` | required | Callback when user clicks the "Latest" link |

#### ComparisonHeader

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| olderTime | string | required | Relative timestamp of the older run |
| newerTime | string | required | Relative timestamp of the newer run |
| olderCount | number | required | Issue count of the older run |
| newerCount | number | required | Issue count of the newer run |

#### ComparisonView

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| olderAudit | `SpeedAuditResult` | required | Full audit result for the older of the two selected runs |
| newerAudit | `SpeedAuditResult` | required | Full audit result for the newer of the two selected runs |
| onExit | `() => void` | required | Fires on "Exit comparison" click or Escape keypress |


## Spacing

All values on the 4px grid.

| Context | Token/Value | Usage |
|---------|-------------|-------|
| Verdict strip padding | `10px 12px` | Internal padding of `.fv-verdict`, matching existing implementation |
| Dot gap | `8px` | Horizontal gap between verdict dots in `.fv-verdict-row` |
| Run header padding | `6px 12px` | Internal padding of the RunHeader banner |
| Comparison header padding | `10px 12px` | Internal padding of ComparisonHeader |
| Findings list item padding | `8px 12px` | Per-row padding in findings list (existing) |
| Section group gap | `4px` | Vertical spacing between comparison section groups (Removed, Unchanged, Added) |
| Dot size default | `6px` | Unselected, non-latest dots |
| Dot size selected | `8px` | Selected or latest dots |
| Ring offset | `2px` | Gap between dot edge and selection ring |


## Typography

| Element | Role | Family | Size | Weight | Line-Height | Color |
|---------|------|--------|------|--------|-------------|-------|
| Verdict label (PASS/WARN/FAIL) | `type-kpi-label`-like | `--font-mono` | 11px | 600 | 1.4 | Status color per verdict |
| Verdict counts | custom | `--font-mono` | 10px | 400 | 1.4 | `--color-text-tertiary` |
| Verdict summary | custom | `--font-sans` | 10px | 400 | 1.4 | `--color-text-tertiary` |
| Run header timestamp | custom | `--font-mono` | 10px | 400 | 1.4 | `--color-text-tertiary` |
| Run header "Latest" link | custom | `--font-mono` | 10px | 500 | 1.4 | `--color-accent` |
| Comparison header timestamps | `type-mono-value`-like | `--font-mono` | 11px | 500 | 1.4 | `--color-text` |
| Comparison issue count | `type-mono-value`-like | `--font-mono` | 11px | 500 | 1.4 | Contextual (see Color Application) |
| Comparison net delta | `type-badge` | `--font-sans` | 11px | 500 | 1 | `--color-emerald` (decrease) or `--color-red` (increase) |
| Comparison section headers | existing `fv-group-header` | `--font-mono` | 10px | 500 | 1.4 | `--color-text-tertiary` |
| Finding text (normal) | `type-body` | `--font-sans` | 13px | 400 | 1.5 | `--color-text-secondary` |
| Finding text (removed, strikethrough) | `type-body` | `--font-sans` | 13px | 400 | 1.5 | `--color-emerald` at 60% opacity |
| Finding text (added) | `type-body` | `--font-sans` | 13px | 400 | 1.5 | `--color-red` at 80% opacity |
| "Persistent" badge | `type-badge` | `--font-sans` | 11px | 500 | 1 | `--color-amber` |
| "Exit comparison" link | `type-caption` | `--font-sans` | 11px | 400 | 1.4 | `--color-text-tertiary` |
| Dot tooltip | native `title` | `--font-mono` | browser default | — | — | OS-rendered |


## Color Application

Accent is reserved for compare-selected dot rings and the "Latest" navigation link. All other color usage maps to semantic status tokens.

| Element | Property | Token | Notes |
|---------|----------|-------|-------|
| Verdict strip background | background | (inherited from panel) | No distinct background |
| Dot: pass | background | `--color-emerald` | |
| Dot: warn | background | `--color-amber` | |
| Dot: fail | background | `--color-red` | |
| Dot: unselected, non-latest | opacity | `0.5` | Applied to the dot element, not the color token |
| Dot: selected ring | box-shadow/outline | `--color-border` | 2px ring using `box-shadow: 0 0 0 2px` |
| Dot: compare-selected ring | box-shadow/outline | `--color-accent` | 2px ring. Only place accent appears on dots. |
| Run header background | background | `--color-bg` | Distinct from panel `--color-bg-elevated` to create depth inversion cue |
| Run header border | border-bottom | `--color-border` | `1px solid` |
| "Latest" link | color | `--color-accent` | Primary action within the run header |
| Comparison header background | background | `--color-bg` | Same depth as run header |
| Comparison delta (improved) | color | `--color-emerald` | Fewer issues in newer run |
| Comparison delta (regressed) | color | `--color-red` | More issues in newer run |
| Comparison delta (unchanged) | color | `--color-text-tertiary` | Same count |
| Removed findings tint | background | `rgba(68, 204, 119, 0.08)` | Uses `--color-emerald` at 8% opacity. Improvements feel positive. |
| Added findings tint | background | `rgba(239, 68, 100, 0.08)` | Uses `--color-red` at 8% opacity. Regressions feel cautionary. |
| "Exit comparison" link | color | `--color-text-tertiary` | Low-priority action, decorative weight |
| "Persistent" badge background | background | `rgba(240, 178, 50, 0.12)` | Matches `status-running-bg` pattern from globals.css |
| "Persistent" badge text | color | `--color-amber` | |


## Elevation & Depth

The IntelPanel sidebar is already an elevated surface. Audit history components sit within it and do not introduce additional elevation layers.

| Element | Elevation Level | Treatment |
|---------|----------------|-----------|
| IntelPanel (existing) | 1 | `.surface-elevated` — `--color-bg-elevated`, border + shadow |
| Verdict strip | 0 (inset) | Flat within the panel. No additional shadow. Separated by `border-bottom`. |
| Run header | 0 (inset) | `--color-bg` background creates a subtle depth inversion (darker than panel). Separated by `border-bottom`. |
| Comparison header | 0 (inset) | Same treatment as run header |
| Findings list items | 0 (inset) | Flat rows. Hover uses `--color-bg-card-hover` background, no shadow. |
| Dot tooltip | OS-level | Native `title` attribute, rendered by browser |


## States

### Page-Level States

#### Empty State

Zero audit runs exist for the current spec. The verdict strip renders no dots. A single line of text replaces the findings list: "No audit results yet" in `--font-sans`, 12px, `--color-text-tertiary`, centered within the findings area. The "Run Audit" button in the action bar remains fully functional. No skeleton, no illustration.

#### Loading State

Audit files are local reads, so loading is effectively instant (sub-10ms). No loading skeleton or spinner is needed. If the GraphQL query is in flight (e.g., after an `AUDIT_COMPLETED` subscription fires), the existing findings list remains visible until new data arrives (optimistic hold). No flash of empty state between runs.

#### Populated State

One or more audit runs loaded. The verdict strip renders dots left-to-right (latest first). The latest dot is full opacity. Older dots are 50% opacity. The findings list shows the latest run's issues grouped by section. Delta tags compare latest vs. previous run (existing behavior). When `persistentIssues > 0`, a count appears in the verdict summary area.

Realistic content example: 3 dots (pass, warn, fail from left to right), latest selected, 4 findings in 2 sections, 1 persistent issue badge.

#### Error State

GraphQL query failure shows an inline error within the Findings tab content area: "Failed to load audit history" in `--color-red`, 12px, with a "Retry" text link in `--color-accent`. The verdict strip hides entirely (no partial rendering of stale dots). Other IntelPanel tabs remain functional.

### Interactive Element States

| Component | Enabled | Hover | Focus | Pressed | Disabled |
|-----------|---------|-------|-------|---------|----------|
| VerdictDot (default) | 6px circle, status color, opacity 0.5 | opacity 0.8, `cursor: pointer` | 2px outline `--color-accent` offset 2px | scale(0.9) | N/A (dots are always interactive when present) |
| VerdictDot (latest) | 8px circle, status color, opacity 1.0 | same as enabled (already full opacity) | 2px outline `--color-accent` offset 2px | scale(0.9) | N/A |
| VerdictDot (selected) | 8px circle, status color, opacity 1.0, ring `--color-border` | ring color brightens to `rgba(255,255,255,0.12)` | 2px outline `--color-accent` offset 2px | scale(0.9) | N/A |
| VerdictDot (compare-selected) | 8px circle, status color, opacity 1.0, ring `--color-accent` | ring glows with `--color-accent-glow` shadow | 2px outline `--color-accent` offset 2px | scale(0.9) | N/A |
| "Latest" link | `--color-accent`, underline: none | underline, cursor: pointer | outline `--color-accent` offset 2px | opacity 0.8 | N/A (hidden when latest is selected) |
| "Exit comparison" link | `--color-text-tertiary` | `--color-text-secondary`, cursor: pointer | outline `--color-accent` offset 2px | opacity 0.8 | N/A (hidden outside comparison mode) |
| Finding row (in comparison) | default finding styling | `--color-bg-card-hover` background | same as hover | N/A (not clickable in comparison mode) | N/A |


## Data Binding

| Element | Source Field | Format | Constraints |
|---------|-------------|--------|-------------|
| Verdict dots | `recentAudits(specPath, 3)` | Array of `SpeedAuditResult` | Max 3 per category (SPEED retention policy). Ordered newest-first. |
| Dot color | `audit.verdict` | `"pass"` \| `"warn"` \| `"fail"` mapped to `--color-emerald` / `--color-amber` / `--color-red` | Always one of three values |
| Dot tooltip | `audit.timestamp` | Relative time string | "2h ago", "3d ago". Beyond 7 days, show "Mar 15". Uses `formatRelativeTime()` utility. |
| Findings list | `audit.issues[]` | Array of `AuditIssue` | Each issue has `severity`, `section`, `message`, `ruleId` |
| Run header timestamp | `selectedAudit.timestamp` | Relative time string | Same format as dot tooltip |
| Comparison issue counts | `olderAudit.issues.length`, `newerAudit.issues.length` | integer | Displayed as "5 issues → 2 issues" |
| Comparison net delta | `newerCount - olderCount` | signed integer | Displayed as "(−3)" or "(+2)". Parenthesized. |
| Persistent badge | Computed: issue present in both `latestAudit.issues` and `previousAudit.issues` | boolean per issue | Matched by `ruleId` + `section`. Badge only appears on latest view, not historical. |
| Sizing card | `audit.sizing` | `{ taskCount, recommendation, confidence }` | In comparison mode, both sizing cards shown side-by-side (or stacked if space insufficient). |


## Interactions & Motion

### Interactions

| Trigger | Target | Response | Notes |
|---------|--------|----------|-------|
| Click dot | VerdictDot | Set `selectedRunIndex` to that dot's index. Findings list swaps to selected run. RunHeader appears if not latest. | Clicking already-selected dot deselects (returns to latest). |
| Shift+click dot | VerdictDot | Add dot to comparison set. When 2 dots selected, enter comparison mode. | If already in comparison, shift-clicking a third dot replaces the older of the two. |
| Click "Latest" link | RunHeader | Set `selectedRunIndex` to 0. RunHeader disappears. | Same as clicking the leftmost dot. |
| Click "Exit comparison" | ComparisonView | Clear comparison set, return to single-run view (latest). | |
| Press Escape | Global (Findings tab) | If in comparison mode: exit comparison. If run selected: deselect (return to latest). If neither: no-op. | Two-level escape: comparison first, then selection. |
| Arrow Left/Right | VerdictDot (when strip focused) | Move focus between dots. | Does not change selection. User must press Enter/Space to select. |
| Press Enter/Space | Focused VerdictDot | Same as click on that dot. | Standard button activation. |
| Hover dot | VerdictDot | Show native tooltip with relative timestamp. Dot opacity transitions to hover state. | |

### Motion

| Name | Duration | Easing | Property | Usage |
|------|----------|--------|----------|-------|
| fvFadeIn (existing) | 150ms | ease | opacity | Findings list content swap when switching runs |
| dot-state | 120ms | ease-out | opacity, transform, box-shadow | Dot hover, selection ring appear/disappear |
| header-enter | 150ms | ease | opacity, max-height | RunHeader or ComparisonHeader appearing |
| header-exit | 100ms | ease-in | opacity, max-height | RunHeader or ComparisonHeader disappearing |

**Reduced motion policy:** When `prefers-reduced-motion: reduce` is active, replace all animations with instant state changes. Opacity crossfade (0 to 1 in 0ms) is acceptable. No transform animations, no height transitions. The state change itself still occurs; only the motion is removed.


## Responsive Behavior

N/A for breakpoint-based responsive changes. The IntelPanel is a fixed-width sidebar (~320px) that does not participate in responsive layout shifts. It is hidden entirely on viewports below 1024px (existing behavior controlled by the editor page layout). Within the panel, all components use full-width fluid layouts that adapt automatically.

| Breakpoint | Behavior |
|------------|----------|
| < 1024px | IntelPanel hidden entirely (existing). No audit history UI visible. |
| >= 1024px | IntelPanel visible at ~320px. All audit history components render at full panel width. |


## Accessibility

### Keyboard Navigation

| Component | Keys | Behavior |
|-----------|------|----------|
| VerdictDot | `Tab` | Dots are tabbable buttons. Tab order: left-to-right (latest first). |
| VerdictDot | `Arrow Left` / `Arrow Right` | Move focus between dots within the strip. Wraps at boundaries. |
| VerdictDot | `Enter` / `Space` | Activate (same as click). `Shift+Enter` / `Shift+Space` for compare-select. |
| VerdictDot | `Escape` | Deselect current run or exit comparison mode (two-level, as defined in Interactions). |
| "Latest" link | `Tab` → `Enter` | Standard link activation. Focus returns to latest dot after activation. |
| "Exit comparison" link | `Tab` → `Enter` | Standard link activation. Focus returns to the verdict strip. |
| Comparison finding rows | `Arrow Up` / `Arrow Down` | Navigate between rows in the comparison list (read-only focus, not selection). |

### ARIA & Screen Reader

| Component | Role | ARIA | Announcement |
|-----------|------|------|--------------|
| VerdictDot | `button` | `aria-label="Audit run from {relativeTime}, verdict: {status}"`, `aria-pressed="{selected}"` | Selected state announced: "Audit run from 2h ago, verdict: pass, selected" |
| Verdict strip | `toolbar` | `aria-label="Audit history"`, `aria-orientation="horizontal"` | Groups dots for screen readers as a single control strip |
| RunHeader | `status` | `aria-live="polite"` | "Viewing audit from 3h ago" announced when run header appears |
| ComparisonHeader | `status` | `aria-live="polite"` | "Comparing audit from 5h ago with 2h ago. 3 issues to 1 issue." announced on enter |
| ComparisonView sections | `group` | `aria-label="Removed findings"` / `"Unchanged findings"` / `"Added findings"` | Section announced before its items |
| "Persistent" badge | `status` | `aria-label="Persistent issue"` | Announced inline with finding text |

### Contrast & Targets

Verdict dots at 6px diameter are below the 44x44px minimum touch target. Mitigated by ensuring the clickable area extends to at least 24x24px via padding on the `<button>` element (the visual dot is centered within the larger hit area). The 8px gap between dots provides sufficient separation for the enlarged hit areas.

Color contrast notes:
- `--color-text-tertiary` (#55556a) against `--color-bg-elevated` (#16161e) yields ~2.8:1 contrast. Used only for decorative text (timestamps, exit link, section headers). Interactive elements using tertiary color also have hover states that promote to `--color-text-secondary` (~5.5:1).
- `--color-emerald` (#44cc77) against `--color-bg-elevated` (#16161e) yields ~7.5:1. Passes AA.
- `--color-amber` (#f0b232) against `--color-bg-elevated` (#16161e) yields ~8.2:1. Passes AA.
- `--color-red` (#ef4464) against `--color-bg-elevated` (#16161e) yields ~5.1:1. Passes AA for normal text.
- `--color-accent` (#00d4aa) against `--color-bg-elevated` (#16161e) yields ~8.5:1. Passes AAA.


## Content Constraints

| Element | Min | Max | Overflow | Placeholder |
|---------|-----|-----|----------|-------------|
| Verdict dots | 0 | 3 per category | N/A (hard limit from SPEED retention) | "No audit results yet" when 0 |
| Dot tooltip (relative time) | 4 chars ("now") | 12 chars ("Mar 15, 2026") | N/A (native tooltip handles wrapping) | — |
| Run header timestamp | 4 chars | 12 chars | N/A (single line, always fits within ~320px) | — |
| Finding message | 1 char | ~200 chars | Truncate with ellipsis after 65 chars (existing `truncate()` utility) | — |
| Comparison section items | 0 | Unbounded (but practically < 20 per audit) | Scrollable within findings-list region | "(none)" when a section has zero items |
| "Persistent" badge text | Fixed: "persistent" | Fixed: "persistent" | N/A | — |
| Net delta display | 4 chars ("(0)") | 7 chars ("(−99)") | N/A | — |


## Implementation Notes

- Verdict dots are currently `<span>` elements with class `fv-verdict-dot`. Convert to `<button>` elements to gain keyboard accessibility for free. Preserve the existing class name for styling continuity; add `role` and `aria-*` attributes.
- The `recentAudits(specPath, limit)` GraphQL query already exists and returns `SpeedAuditResult[]` sorted newest-first. The subscription `AUDIT_COMPLETED` fires when new audit files land on disk. Wire the subscription to prepend the new result and drop the oldest if count exceeds the limit.
- Shift-click detection: check `event.shiftKey` in the click handler. On macOS trackpads without a Shift key convention, this is still the standard modifier. Discoverability is a known tradeoff (see product spec risks).
- Comparison matching uses `ruleId` + `section` as the composite key. Two issues are "the same" if both fields match. Message text may differ between runs (e.g., updated line numbers), so do not match on message.
- Do not use the `.surface` class on sub-components within the panel. The panel itself is the elevated surface. Inner components use flat backgrounds (`--color-bg` or transparent) with `border-bottom` separators only.
- Persistent issue detection runs client-side by comparing `latestAudit.issues` against `previousAudit.issues` using the same `ruleId + section` key. No backend changes required.
- The `fvFadeIn` keyframe animation (150ms ease, opacity 0→1) already exists in the IntelPanel stylesheet. Reuse it for findings list content swap. Do not create a duplicate animation.
- Arrow key navigation within the verdict strip should use a roving tabindex pattern: only the focused dot has `tabIndex={0}`, others have `tabIndex={-1}`. A single Tab press enters the strip; arrow keys move within it.


## Verification Criteria

- [ ] Token audit passes with zero hardcoded color, spacing, or font values outside of design system tokens
- [ ] Verdict dots render as `<button>` elements with correct `aria-label` and `aria-pressed`
- [ ] Clicking a non-latest dot swaps the findings list to that run's issues and shows the RunHeader
- [ ] Clicking the already-selected dot returns to latest view
- [ ] Shift-clicking two dots enters comparison mode with Removed/Unchanged/Added sections
- [ ] Comparison net delta shows correct sign, color (`--color-emerald` for decrease, `--color-red` for increase)
- [ ] Escape exits comparison mode first, then deselects run (two-level)
- [ ] Arrow Left/Right navigates between dots within the verdict strip using roving tabindex
- [ ] 0-run state shows "No audit results yet" text, no dots rendered
- [ ] 1-run state shows single dot at full opacity, dot is not compare-selectable (no shift-click behavior)
- [ ] Persistent issue badge appears only on latest view when issue matches previous run by `ruleId + section`
- [ ] RunHeader "Latest" link uses `--color-accent`; no other element in audit history uses accent except compare-selected dot ring
- [ ] All text elements use `--font-mono` or `--font-sans` per the Typography table (no system font fallthrough)
- [ ] Reduced motion: all animations replaced with instant transitions when `prefers-reduced-motion: reduce` is active
- [ ] Dot hit area is at least 24x24px despite 6-8px visual size
- [ ] `fvFadeIn` reused for findings list swap, no duplicate keyframe definitions


## Figma / Visual Reference

No Figma file exists for this feature. The ASCII wireframes in Layout Structure serve as the authoritative visual reference. The implementation should match the existing Findings tab aesthetic — visual continuity verified by comparing screenshots of the modified panel against the current panel.

```
Verdict strip with 3 dots (latest selected):

  ●  ◌  ◌   PASS   2 errors · 1 warning
                     ↑ latest    ↑ 50% opacity

Run header (viewing past run):

  ┌─────────────────────────────────────┐
  │  Viewing audit from 2h ago   ← Latest │
  └─────────────────────────────────────┘

Comparison mode:

  ┌─────────────────────────────────────┐
  │  Comparing: 5h ago → 2h ago         │
  │  3 issues → 1 issue  (−2)           │
  ├─────────────────────────────────────┤
  │  ┄ Removed ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄  │
  │  ✓  L2 Missing acceptance criteria  │
  │  ✓  L3 Broken cross-reference       │
  │                                     │
  │  ┄ Unchanged ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄  │
  │  ⚠  L2 Inconsistent ID format       │
  │                                     │
  │  ┄ Added ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄  │
  │  (none)                             │
  │                                     │
  │  [Exit comparison]                  │
  └─────────────────────────────────────┘
```
