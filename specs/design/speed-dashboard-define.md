# Design: Dashboard Define Surface

> See [product spec](../product/speed-dashboard-define.md) for product context.
> Design system: `dashboard/frontend/app/globals.css`

## Design Intent

**Direction:** Information-dense, calm, and analytical. The landing panel reads like an index card pinned to a corkboard; the Spec Alignment page reads like a coverage report. Both surfaces prioritize scannability over visual flourish, consistent with the dashboard's "Linear meets spacecraft HUD" reference vibe.

**Do not:** Use rounded playful elements. Apply accent color to anything other than hero metrics and primary actions. Use pure white (`#fff`) anywhere. Add gradients beyond the subtle vision warning banner. Use borders without paired shadows on elevated elements (use the `.surface` class). Add decorative illustrations or empty-state artwork.

## Pages / Routes

| Route | User Flow | Description |
|-------|-----------|-------------|
| `/` | Reading the portfolio | Landing page editorial grid. DefinePanel occupies the top-left cell (row 0, column 0). Shows vision status, draft specs, and defects as a summary card. |
| `/spec-alignment` | Drilling into coverage | Full-width page showing per-spec-file claim coverage. Summary bar at top, expandable section rows below. |

## Layout Structure

### Global Layout

The dashboard uses a fixed sidebar (icon rail) + header (top bar) shell. Content occupies the remaining viewport. The Define surface does not modify the global layout; both routes render within the existing content region.

### Regions

| Region ID | Position | Width | Internal Layout | Scroll |
|-----------|----------|-------|-----------------|--------|
| landing-grid | Content area (route `/`) | Full content width | CSS Grid: `260px 1fr 320px` columns, `3fr 1fr` rows, 1px gap colored `--border` | Cell overflow auto |
| define-panel | landing-grid cell [0,0] | 260px (first column) | Vertical flex stack, content-driven height | Yes (cell overflow) |
| spec-alignment | Content area (route `/spec-alignment`) | Full content width | Vertical stack, `space-y-4` (16px gap) | Yes (page scroll) |
| summary-bar | Top of spec-alignment | Full width | `.surface`, flex row, `gap-8`, `px-5 py-3` | No |
| spec-card | Below summary-bar, one per spec file | Full width | `.surface`, vertical stack: header, column headers, section rows | No (page scrolls) |

## Component Inventory

| Component ID | Type | Parent ID | Description |
|--------------|------|-----------|-------------|
| PanelLabel | existing | define-panel | Mono label + subtitle header for each landing panel |
| SurfaceLink | existing | define-panel | Bottom link with arrow icon, navigates to drilldown page |
| VisionWarning | new | define-panel | Dashed-border warning banner when `overview.md` is missing |
| SectionLabel | new | define-panel | Uppercase mono section divider ("Specs · N", "Defects · N") |
| DraftSpecItem | new | define-panel | Spec row: name, status badge, three type pills |
| DefectRow | new | define-panel | Defect row: severity badge + name |
| ViewAllLink | new | define-panel | "View all N" overflow link with arrow icon |
| Stat | new | summary-bar | KPI value + label pair for the summary bar |
| ProgressBar | existing | summary-bar, section-row | Segmented progress bar (confirmed/missing/other) |
| SpecCard | new | spec-alignment | Card per spec file with header, column headers, section rows |
| SectionRow | new | spec-card | Collapsible row: chevron, name, progress bar, coverage %, fraction |
| ClaimRow | new | section-row | Claim detail: status icon, text, evidence, divergence, badge |
| EvidenceButton | new | ClaimRow | Copy-to-clipboard button showing evidence path with copy/check icon |

### Component Props

#### VisionWarning

No props. Renders statically when `visionStatus === "missing"`.

#### DraftSpecItem

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| spec | DraftSpec | required | `{ name, specTypes, status }` |

#### DefectRow

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| defect | Defect | required | `{ severity, name }` |

#### Stat

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| label | string | required | KPI label below the value |
| value | number or string | required | The metric value |
| color | string | `--text` | Override color for the value |

#### SectionRow

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| section | SectionData | required | `{ section, claimCount, confirmed, missing, unverifiable, coveragePct, claims }` |

#### SectionLabel

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| children | ReactNode | required | Label text content (e.g., "Specs · 4") |

#### ViewAllLink

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| href | string | required | Navigation target URL |
| count | number | required | Total item count displayed after "View all" label |

#### SpecCard

SpecCard is not a discrete component with a props interface. Each spec file card is rendered inline within `SpecAlignmentPage` via a `.map()` over `sa.specs`. The card structure (header, column headers, section rows) is defined directly in the page component.

#### ClaimRow

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| claim | Claim | required | `{ source, claimType, claimText, entity, status, evidence, divergence }` |

#### EvidenceButton

EvidenceButton is not a standalone component. It renders inline within ClaimRow as a `<button>` element when `claim.evidence` is non-null. Internal state (`copied`) is managed via `useState` within ClaimRow. The button accepts no props; it reads `claim.evidence` from the parent closure.

## Spacing

| Context | Token / Value | Usage |
|---------|---------------|-------|
| Grid cell gap | 1px | Between editorial grid cells, filled by `--border` background |
| Panel internal padding | Inherited from grid cell | DefinePanel has no explicit padding; cell handles it |
| Section label margin | 20px top, 6px bottom | Space above and below "Specs · N" / "Defects · N" dividers |
| Spec item padding | 10px vertical, 10px horizontal | Inside each DraftSpecItem hover zone |
| Spec item pill gap | 4px | Between the three type pills |
| Defect row padding | 3px vertical | Between stacked defect rows |
| Vision warning padding | 14px all sides | Internal padding of the warning banner |
| Vision warning margin | 10px bottom | Space below the banner before spec list |
| Surface link | 16px top margin, 12px top padding | Space above the "Open Define Surface" link |
| Summary bar padding | 20px horizontal, 12px vertical (`px-5 py-3`) | Inside the Spec Alignment summary bar |
| Summary bar stat gap | 32px (`gap-8`) | Between stat components in the summary bar |
| Spec card section gap | 16px (`space-y-4`) | Between spec file cards on the Spec Alignment page |
| Section row padding | 16px horizontal, 12px vertical (`px-4 py-3`) | Inside each collapsible section row |
| Claim row padding | 10px vertical, 16px left, 12px right (`py-2.5 pl-4 pr-3`) | Inside each claim row |
| Expanded claims indent | 40px left (`pl-10`) | Left indent for claims inside expanded sections |

## Typography

| Element | Role | Family | Size | Weight | Line-Height | Color |
|---------|------|--------|------|--------|-------------|-------|
| Panel label "Define" | Panel header | Mono | 11px | 600 | 1 | `--text-tertiary`, uppercase, ls 0.06em |
| Panel subtitle | Panel subhead | Sans | 11px | 400 | 1 | `--text-tertiary` |
| Vision warning title | Alert title | Sans | 14px | 600 | 1.4 | `--red` |
| Vision warning desc | Alert body | Sans | 11px | 400 | 1.5 | `--text-secondary` |
| Vision code ref | Inline code | Mono | 10px | 400 | 1 | `--text-tertiary`, bg: `--bg-card` |
| Vision CTA | Link | Sans | 11px | 500 | 1 | `--violet` |
| Section label | Divider | Mono | 9px | 500 | 1 | `--text-tertiary`, uppercase, ls 0.06em |
| Spec name | Item title | Sans | 13px | 500 | 1.4 | `--text` |
| Status badge | Badge | Mono | 9px | 600 | 1 | Per-state, uppercase, ls 0.03em |
| Spec type pill | Badge | Sans | 9px | 500 | 1 | Per-type color |
| Defect severity | Badge | Mono | 8px | 600 | 1 | Per-severity |
| Defect name | Body | Sans | 11px | 400 | 1.4 | `--text-secondary` |
| View all link | Link | Sans | 11px | 500 | 1 | `--violet` |
| Surface link | Link | Sans | 11px | 500 | 1 | Panel color (violet) |
| Summary stat value | KPI value | Mono | 18px | 600 | 1 | Per-metric or `--text` |
| Summary stat label | KPI label | Mono | — | 500 | — | `--text-tertiary`, uppercase |
| Spec filename | Section header | Mono | 13px | 600 | 1.4 | `--text` |
| Claim fraction | Caption | Sans | — | 400 | — | `--text-tertiary` |
| Spec coverage % | KPI value | Mono | 15px | 700 | 1 | Coverage-coded |
| Section name | Section header | Sans | — | — | — | Standard section header |
| Section coverage % | Mono value | Mono | 13px | 600 | 1 | Coverage-coded |
| Section fraction | Meta | Mono | 11px | 400 | 1 | `--text-tertiary` |
| Claim text | Body | Sans | — | 400 | 1.5 | `--text` |
| Claim evidence | Code | Mono | 11px | 400 | 1 | `--text-tertiary` |
| Claim divergence | Alert | Sans | 11px | 400 | 1.4 | `--amber` |
| Status badge pill | Badge | — | — | — | — | Per-status color on tinted bg |

## Color Application

| Element | Property | Token | Notes |
|---------|----------|-------|-------|
| Grid gap | background | `--border` | 1px lines between editorial grid cells |
| Vision warning border | border | `rgba(239, 68, 100, 0.20)` | 1.5px dashed |
| Vision warning bg | background | `rgba(239, 68, 100, 0.025)` to transparent | linear-gradient 135deg |
| Vision title | color | `--red` | |
| Vision CTA | color | `--violet` | |
| Spec pill (product) | color + dot | `--emerald` | bg: `color-mix(in srgb, emerald 10%, transparent)` |
| Spec pill (technical) | color + dot | `--blue` | bg: `color-mix(in srgb, blue 10%, transparent)` |
| Spec pill (design) | color + dot | `--violet` | bg: `color-mix(in srgb, violet 10%, transparent)` |
| Spec pill (missing) | color + dot | `--text-tertiary` | bg: `rgba(85, 85, 106, 0.06)`, opacity 0.35 |
| Badge unplanned | color | `--text-tertiary` | bg: `rgba(85, 85, 106, 0.12)` |
| Badge writing | color | `--amber` | bg: `rgba(240, 178, 50, 0.08)` |
| Severity P0 | color | `--red` | bg: `rgba(239, 68, 100, 0.05)` |
| Severity P1/P2 | color | `--amber` | bg: `rgba(240, 178, 50, 0.05)` |
| Severity P3 | color | `--text-tertiary` | bg: `--bg-card`, whole row opacity 0.35 |
| Coverage ≥ 80% | color | `--emerald` | Applied to stat values, spec %, section % |
| Coverage ≥ 50% | color | `--amber` | |
| Coverage < 50% | color | `--red` | |
| Claim confirmed | color + border | `--emerald` | bg: `rgba(68, 204, 119, 0.10)` |
| Claim missing | color + border | `--red` | bg: `rgba(239, 68, 100, 0.10)` |
| Claim unverifiable | color + border | `--text-tertiary` | bg: `rgba(85, 85, 106, 0.10)` |
| Claim divergent | color + border | `--amber` | bg: `rgba(240, 178, 50, 0.10)` |
| Surface link | color | Panel color (violet for Define) | |

## Elevation & Depth

| Element | Elevation Level | Treatment |
|---------|----------------|-----------|
| Editorial grid cells | 0 (base) | Flat background `--bg`, separated by 1px `--border` gap |
| Summary bar | 1 | `.surface` class (border + shadow) |
| Spec file cards | 1 | `.surface` class, `overflow-hidden` |
| Spec file card header | 1+ | Bottom border + `box-shadow: 0 1px 2px rgba(0,0,0,0.1)` for subtle lift above section rows |
| Vision warning | 0 (inset) | Dashed border instead of solid; gradient background creates depth without elevation |

## States

### Page-Level States

#### Empty State

**Landing panel**: When no draft specs, no defects, and vision is not missing, the panel shows "Nothing to review." in 12px `--text-tertiary`. The PanelLabel and SurfaceLink still render.

**Spec Alignment page**: When `spec-alignment.json` does not exist, the page shows "No spec alignment data found. Run `speed plan` to generate." The `speed plan` command renders in a code tag with `bg-bg-card text-accent` styling.

#### Loading State

**Landing panel**: Loads as part of the `LandingView` query. No independent loading state; the entire landing page shows a loading skeleton via `CardSkeleton` components until the query resolves.

**Spec Alignment page**: Shows a 4-column grid of `CardSkeleton` components while the `SpecAlignment` query is in flight.

#### Populated State

**Landing panel**: Vision warning (conditional) followed by specs list with type pills, defects list with severity badges, capped at 5 items each with overflow links.

**Spec Alignment page**: Summary bar with four stats and a progress bar, followed by one card per spec file, each containing collapsible section rows.

#### Error State

**Landing panel**: Handled at the landing page level. If the `LandingView` query fails, the entire page shows an error state.

**Spec Alignment page**: Shows "Error: " followed by the GraphQL error message in a `.surface` container with `--red` text color.

### Interactive Element States

| Component | Enabled | Hover | Focus | Pressed | Disabled | Loading |
|-----------|---------|-------|-------|---------|----------|---------|
| DraftSpecItem | transparent bg, `cursor: pointer` | `bg: rgba(255,255,255,0.02)`, 0.1s transition | Not focusable (no tab stop) | Same as hover | — | — |
| DefectRow | transparent bg, `cursor: pointer` | No background change | Not focusable | — | — | — |
| VisionWarning | Border `rgba(239,68,100,0.20)`, `cursor: pointer` | Border darkens (0.15s transition) | Not focusable | — | — | — |
| SectionRow | transparent bg, full-width button | `bg: bg-elevated/50` | Default browser focus ring | — | — | — |
| EvidenceButton | `text-text-tertiary` | `bg: bg-card-hover`, `text: accent` | Default focus ring | Copies to clipboard, icon swaps to CheckCircle for 1.5s | — | — |
| SurfaceLink | Panel color text, `cursor: pointer` | Implicit (no explicit hover change) | Not focusable | — | — | — |
| ViewAllLink | `--violet` text, `cursor: pointer` | Implicit | Not focusable | — | — | — |

## Data Binding

| Element | Source Field | Format | Constraints |
|---------|-------------|--------|-------------|
| Panel label subtitle | Static | "Specs and Preparation" | |
| Vision warning | `define.visionStatus` | Renders when value is `"missing"` | |
| Section count ("Specs · N") | `define.draftSpecs.length` | Integer | |
| Spec name | `draftSpec.name` | String | Truncate with ellipsis, single line |
| Spec status | `draftSpec.status` | Uppercase badge | |
| Spec type pills | `draftSpec.specTypes` | Always render all three; dim those not in the array | |
| Defect severity | `defect.severity` | Badge text (P0/P1/P2/P3) | |
| Defect name | `defect.name` | String | Truncate with ellipsis, single line |
| Summary coverage | `specAlignment.overallCoveragePct` | Percent, one decimal | Color-coded by threshold |
| Summary claims | `specAlignment.totalClaims` | Integer | |
| Summary confirmed | `specAlignment.totalConfirmed` | Integer | Emerald color |
| Summary missing | `specAlignment.totalMissing` | Integer | Red color |
| Spec filename | `spec.specFile` | Last path segment only (split on `/`) | Mono font |
| Spec fraction | `spec.confirmed` / `spec.totalClaims` | "N/M claims" | |
| Section name | `section.section` | String | Truncate, flex-1 |
| Section fraction | `section.confirmed` / `section.claimCount` | "N/M" | |
| Claim text | `claim.claimText` | String | Full text, wraps |
| Evidence | `claim.evidence` | String | Truncate with ellipsis at `max-w-md` |
| Divergence | `claim.divergence` | Prefixed with "Divergence: " label | Only renders when non-null |

## Interactions & Motion

### Interactions

| Trigger | Target | Response | Notes |
|---------|--------|----------|-------|
| Click DraftSpecItem | DraftSpecItem | Background flash on hover, no navigation yet | Row is clickable as preparation for future spec editor link |
| Click VisionWarning | VisionWarning | Navigates to Spec Editor to create `overview.md` | Entire banner is the click target |
| Click "Open Define Surface" | SurfaceLink | Navigate to `/spec-alignment` | Standard anchor navigation |
| Click "View all N" | ViewAllLink | Navigate to `/specs` or `/defects` | Standard anchor navigation |
| Click SectionRow | SectionRow | Toggle expanded state, reveal/hide child ClaimRows | Chevron rotates from right to down |
| Click EvidenceButton | ClaimRow evidence | Copy `claim.evidence` to clipboard | Icon swaps Copy → CheckCircle for 1.5s |
| Hover DraftSpecItem | DraftSpecItem | Subtle background tint | |
| Hover SectionRow | SectionRow | Background change to `bg-elevated/50` | |
| Hover EvidenceButton | EvidenceButton | Background and text color change | |

### Motion

| Name | Duration | Easing | Property | Usage |
|------|----------|--------|----------|-------|
| spec-hover | 100ms | ease | background | DraftSpecItem hover transition |
| vision-border | 150ms | ease | border-color | VisionWarning hover |
| section-expand | instant | — | display | SectionRow expand/collapse (no animation, React conditional render) |
| copy-feedback | 1500ms | — | icon swap | Evidence button icon changes from Copy to CheckCircle, then reverts |

**Reduced motion policy:** No continuous animations are used. The only transitions are hover state changes (background, border-color) which are 100-150ms and acceptable under `prefers-reduced-motion`. The pulsing dot on running features (Execute panel) would be disabled, but the Define surface has no pulse animations.

## Responsive Behavior

| Breakpoint | Columns | Behavior |
|------------|---------|----------|
| < 1024px | — | Dashboard is designed for desktop viewport. Landing grid and Spec Alignment page do not adapt to mobile. Minimum supported width is 1024px. |
| 1024-1280px | 3 | Landing grid: `260px 1fr 320px`. Spec Alignment: full width, section progress bars at `w-48`. |
| > 1280px | 3 | Same layout. Content area grows with viewport; cards expand horizontally. |

The dashboard does not target mobile or tablet viewports. Responsive breakpoints below 1024px are out of scope.

## Accessibility

### Keyboard Navigation

| Component | Keys | Behavior |
|-----------|------|----------|
| SectionRow | Enter/Space | Toggle expand/collapse (rendered as `<button>`) |
| SectionRow | Tab | Focus moves through section rows in document order |
| EvidenceButton | Enter/Space | Copy evidence text to clipboard |
| SurfaceLink | Enter | Navigate to linked page (rendered as `<a>`) |
| ViewAllLink | Enter | Navigate to linked page (rendered as `<a>`) |

DraftSpecItem and DefectRow are not keyboard-focusable in the current implementation. VisionWarning is a `<div>` with `cursor: pointer` but no keyboard accessibility. These are acceptable for V1 since the landing panel is a summary view with no destructive actions.

### ARIA & Screen Reader

| Component | Role | ARIA | Announcement |
|-----------|------|------|--------------|
| SectionRow | button | Implicit from `<button>` element | Section name announced with button role |
| EvidenceButton | button | Implicit from `<button>` element | "Copied" state not announced (visual-only feedback) |
| Spec type pills | none | Decorative indicators | Not announced individually; spec name provides context |
| Severity badges | none | Decorative indicators | Severity is part of the visible text flow |

### Contrast & Targets

All text colors meet WCAG 4.5:1 against the dark background (`--bg`: `#0f0f13`). The lowest-contrast text is `--text-tertiary` (`#55556a`) which is used only for decorative labels and timestamps. Interactive targets (SectionRow, EvidenceButton) exceed 44px height due to padding.

## Content Constraints

| Element | Min | Max | Overflow | Placeholder |
|---------|-----|-----|----------|-------------|
| Spec name | 1 char | No limit | Ellipsis after 1 line, `title` tooltip | — |
| Defect name | 1 char | No limit | Ellipsis after 1 line, `title` on parent | — |
| Status badge | 4 chars ("done") | 10 chars ("unplanned") | No overflow (fixed vocabulary) | — |
| Claim text | 1 char | No limit | Wraps to multiple lines | — |
| Evidence text | 1 char | No limit | Truncate at `max-w-md` with ellipsis | — |
| Section name | 1 char | No limit | Truncate with ellipsis, flex-1 | — |
| Spec filename | 1 char | No limit | Displays last segment only (`split("/").pop()`) | — |
| Draft spec list | 0 items | 5 visible | "View all N" link for overflow | "Nothing to review." |
| Defect list | 0 items | 5 visible | "View all N" link for overflow | Section hidden when 0 |

## Implementation Notes

- The DefinePanel renders inside the EditorialGrid's CSS Grid cell. It has no explicit padding or width; all sizing comes from the grid column definition (`260px`).
- Spec type pills always render all three types (Product, Technical, Design). Types not present in `specTypes` are dimmed to `opacity: 0.35` with a neutral background rather than hidden entirely. This makes gaps visible at a glance.
- The VisionWarning uses inline styles throughout (consistent with other landing panel components). The hover border-color change relies on CSS transition set on the container, not a separate hover class.
- Spec Alignment uses Tailwind utility classes (via the dashboard's Tailwind setup) while the landing panel uses inline styles. The difference exists because the landing panel was built as part of the editorial grid prototype (inline-style-first), while Spec Alignment was built later using the established Tailwind workflow.
- The `ProgressBar` component is shared with other dashboard pages (Mission Control, Budget). It accepts `segments` with value/color/label and renders proportionally within the given width.
- `CardSkeleton` is a shared loading component used across all dashboard pages.

## Verification Criteria

- [ ] Vision warning renders when `visionStatus` is `"missing"` and hides for `"placeholder"` and `"defined"`
- [ ] All three spec type pills render for each draft spec, with missing types dimmed at reduced opacity
- [ ] P3 defects render at `opacity: 0.35`; P0 renders in red, P1-P2 in amber
- [ ] Lists of specs and defects cap at 5 items with "View all N" overflow link
- [ ] SurfaceLink at the bottom of the panel navigates to `/spec-alignment`
- [ ] Summary bar stat values use mono font and are color-coded by coverage threshold
- [ ] Section rows expand and collapse on click, showing/hiding child claim rows
- [ ] Evidence copy button changes icon to CheckCircle for 1.5s after click
- [ ] Divergent claims show "Divergence: " prefix followed by the divergence description in amber below the claim text
- [ ] No hardcoded colors outside of intentional `rgba()` tints (all semantic colors use tokens)
- [ ] `.surface` class applied to all elevated elements (summary bar, spec file cards)

## Figma / Visual Reference

No Figma file exists for this surface. The implementation was prototyped directly in code. The landing panel follows the editorial grid pattern established by the other three landing panels (Execute, Judge, Learn). The Spec Alignment page follows the dashboard's standard full-width card layout pattern used by Mission Control and Budget pages.
