# Design: Define Feature Evidence-to-Defect Intake

> See [product spec](../product/speed-define-feature-defects.md) for product context.
> See [technical spec](../tech/speed-define-feature-defects.md) for data, API, persistence, and validation contracts.
> Design system: [`dashboard/frontend/app/globals.css`](../../dashboard/frontend/app/globals.css).

## Design Intent

**Direction:** Dense, calm, evidence-first, and explicit about consequences. The findings inbox should feel like an engineering review queue; the manager report should feel like a reliable portfolio ledger. Users must always know whether they are viewing evidence, editing an unwritten draft, or looking at a filed canonical defect.

**Do not:** Present every signal as a confirmed defect. Hide provenance behind generic summaries. Use cards as decoration when a list or table communicates hierarchy better. Use color as the only status indicator. Auto-open a draft, file a defect, execute an evidence command, or repair repository files merely because a page was viewed. Add gradients, decorative illustrations, pulsing skeletons, or visual tokens not defined in `globals.css`.

## Pages / Routes

| Route | User Flow | Description |
|-------|-----------|-------------|
| `/define/[feature]/findings` | Enter and review a feature findings inbox; disposition a finding; file a corroborated defect | Feature-scoped evidence queue with summary, filters, finding cards, evidence disclosure, disposition controls, and a defect draft drawer |
| `/define/[feature]/findings?finding=<id>` | Return from a filed defect to its source | Same inbox with the referenced finding expanded, scrolled into view, and briefly focused |
| `/define/defects` | Review all defects by feature | Read-only manager report with portfolio totals, grouped unfiltered results, URL-backed filters, canonical links, warnings, and exports |
| `/define/defects?feature=<name>&lifecycle=<active|closed>&severity=<value>&status=<value>&source=<value>&q=<text>` | Review or share a filtered defect report | Flat deduplicated result matching the active filters; repeated parameters represent multi-select values |
| `/editor?spec=specs%2Fdefects%2F<slug>.md&return=<encoded-report-url>` | Open the canonical report and return to report context | Existing spec editor deep-linked to the defect file; `return` is optional and must resolve to a local `/define/defects` URL |

## Layout Structure

### Global Layout

Both pages render inside the existing dashboard app shell with the fixed navigation rail and top header. The content region uses the existing page width and `p-6` outer padding. Findings uses a single scrollable content column plus an overlaid right drawer. The manager report uses one full-width content column; its filter bar becomes sticky below the app header after the page header scrolls away.

```text
FINDINGS INBOX                              DEFECT REPORT
┌──────────────────────────────────────┐   ┌──────────────────────────────────────┐
│ Breadcrumb · Feature · actions       │   │ Defect Report          Export ▾     │
│ Summary metrics                      │   │ Portfolio summary                    │
│ Filters                              │   │ Sticky filters + active chips        │
│ ┌ Finding card                     ┐ │   │ Feature group / filtered result      │
│ │ confidence · title · evidence    │ │   │ ┌ severity status title features ┐  │
│ │ disposition controls             │ │   │ └───────────────────────────────┘  │
│ └──────────────────────────────────┘ │   │ Metadata warnings / empty state      │
└───────────────────────────────┬──────┘   └──────────────────────────────────────┘
                                │ draft drawer
                                └───────────────┐
```

### Regions

| Region ID | Position | Width | Internal Layout | Scroll |
|-----------|----------|-------|-----------------|--------|
| findings-page | App content | Full content width | Vertical stack, `gap-4` | Page |
| findings-header | Top of findings-page | Full | Breadcrumb row, title row, summary row | No |
| findings-filter-bar | Below summary | Full; sticky below app header | Wrapped flex row, `gap-2` | No |
| findings-list | Below filters | Full | Vertical stack, `gap-3` | Page |
| draft-backdrop | Viewport overlay | Full viewport | Dims and inert-marks underlying content | No |
| draft-drawer | Right edge overlay | `max-w-2xl`, full height below app header | Header, scrollable form, fixed footer | Form only |
| report-page | App content | Full content width | Vertical stack, `gap-4` | Page |
| report-header | Top of report-page | Full | Title/actions row, summary grid | No |
| report-filter-bar | Below summary | Full; sticky below app header | Filter row then active-chip row | No |
| report-results | Below filters | Full | Feature sections when unfiltered; one table when feature-filtered | Page |
| export-menu | Anchored to Export button | Content width | Vertical action list | No |

## Component Inventory

| Component ID | Type | Parent ID | Description |
|--------------|------|-----------|-------------|
| FindingsPageHeader | new | findings-header | Breadcrumb, feature name, evidence generation time, refresh state, and manager-report link |
| FindingsSummary | new | findings-header | Counts for unresolved, confirmed failures, review findings, risk signals, and verification gaps |
| FindingsFilters | new | findings-filter-bar | Resolution, source, kind, task, stale, and linked-defect filters |
| PartialEvidenceBanner | new | findings-list | Non-blocking warning listing malformed or unavailable evidence sources |
| FindingCard | new | findings-list | One correlated finding with confidence, status, recommendation, evidence, and actions |
| EvidenceDisclosure | new | FindingCard | Expandable source-aware evidence rows with inert paths and commands |
| DispositionControls | new | FindingCard | Allowed disposition actions and rationale/task/duplicate inputs |
| DefectDraftDrawer | new | draft-drawer | No-write defect preview and edit form with validation, duplicate warnings, and explicit filing |
| RelatedFeaturePicker | new | DefectDraftDrawer | Multi-select affected-feature control; source feature shown separately and read-only |
| DraftValidationSummary | new | DefectDraftDrawer | Blocking field errors, stale state, duplicate candidates, and write failures |
| FiledDefectConfirmation | new | FindingCard | Replaces action controls after filing with canonical, report, and triage links |
| DefectReportHeader | new | report-header | Page title, generation time, export menu, and portfolio summary |
| DefectReportSummary | new | report-header | Total, Active, Closed, P0/P1, affected-feature, and Unassigned metrics |
| DefectReportFilters | new | report-filter-bar | Related Feature, lifecycle category, exact status, severity, source, and literal-search controls |
| ActiveFilterChips | new | report-filter-bar | Removable URL-backed filter tokens and Clear all action |
| DefectFeatureGroup | new | report-results | Unfiltered-only feature heading, group count, and defect table |
| DefectReportTable | new | report-results or DefectFeatureGroup | Accessible table of unique defect records |
| DefectReportRow | new | DefectReportTable | Severity, status, title, updated time, source, feature badges, warning, and canonical link |
| DefectMetadataWarning | new | DefectReportRow | Inline warning for missing spec, missing state, conflict, unknown feature, or malformed metadata |
| ExportMenu | new | report-header | Download JSON or Markdown for the current exact view |
| EmptyResult | new | findings-list or report-results | Context-specific no-evidence, no-defects, or no-filter-match state |
| Toast | existing | page overlay | Announces successful copy/export or recoverable background errors |

### Component Props

#### FindingCard

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| finding | `FeatureFinding` | required | Current correlated finding and evidence |
| featureName | `string` | required | Source feature for disposition mutations |
| expanded | `boolean` | `false` | Whether evidence and actions are open |
| onExpandChange | `(expanded: boolean) => void` | required | Controls disclosure and deep-link focus |
| onPreviewDefect | `(findingId: string) => void` | required | Opens the no-write draft drawer |

#### DefectDraftDrawer

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| open | `boolean` | required | Controls drawer and backdrop |
| finding | `FeatureFinding` | required when open | Source finding |
| preview | `DefectDraftPreview` | required when open | Deterministic initial draft and duplicate warnings |
| availableFeatures | `FeatureOption[]` | required | Options for Related Features |
| onCancel | `() => void` | required | Closes without persistence |
| onRefreshEvidence | `() => Promise<void>` | required | Rebuilds stale preview after confirmation |
| onFile | `(input: FileFindingDefectInput) => Promise<Result>` | required | Performs explicit atomic filing |

#### DefectReportFilters

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| value | `DefectReportFilterInput` | required | URL-normalized filters |
| featureOptions | `FeatureOption[]` | required | Includes Unassigned sentinel and discovered legacy feature values |
| severityOptions | `FilterOption[]` | required | P0-P3 and Unknown |
| lifecycleOptions | `FilterOption[]` | required | Active and Closed derived categories |
| statusOptions | `FilterOption[]` | required | Current lifecycle values plus Untriaged |
| sourceOptions | `FilterOption[]` | required | Supported discovered sources |
| onChange | `(value) => void` | required | Replaces URL parameters after normalization |

#### DefectReportTable

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| defects | `DefectReportItem[]` | required | Unique, pre-sorted records |
| filtered | `boolean` | required | Selects flat filtered labeling versus group context |
| returnUrl | `string` | required | Safe local URL passed to editor deep links |

#### ExportMenu

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| filters | `DefectReportFilterInput` | required | Exact current filters |
| disabled | `boolean` | `false` | True while loading or when no records match |
| onExport | `(format: "json" \| "markdown") => Promise<void>` | required | Requests export and starts browser download |

## Spacing

The implementation uses the existing Tailwind spacing scale already used by dashboard pages. No new spacing tokens are introduced.

| Context | Token | Usage |
|---------|-------|-------|
| Page padding | `p-6` | Outer content inset on supported desktop widths |
| Major section gap | `gap-4` | Header, filters, results, and feature groups |
| Card/list gap | `gap-3` | Finding cards and report feature sections |
| Inline control gap | `gap-2` | Filter controls, badges, and action buttons |
| Compact badge gap | `gap-1` | Multiple related-feature badges |
| Surface padding | `p-4` | Finding cards, empty states, banners, summary surface |
| Drawer form padding | `p-6` | Scrollable draft content |
| Drawer field gap | `space-y-4` | Major fields; labels and help text use `gap-1` |
| Table cell padding | `px-4 py-3` | Desktop defect rows |
| Sticky filter offset | Existing app-header height | Filter bar never overlaps global navigation |

## Typography

| Element | Role | Family | Size | Weight | Line-Height | Color |
|---------|------|--------|------|--------|-------------|-------|
| Page title | `.type-page-title` | `--font-mono` | 18px | 600 | 1.3 | `--color-text` |
| Section/group title | `.type-section-title` | `--font-sans` | 15px | 600 | 1.4 | `--color-text` |
| Finding/defect title | `.type-section-header` | `--font-sans` | 13px | 600 | 1.4 | `--color-text` |
| Body/evidence summary | `.type-body` | `--font-sans` | 13px | 400 | 1.5 | `--color-text-secondary` |
| KPI value | `.type-kpi-value` | `--font-mono` | 28px | 600 | 1.1 | Metric-specific token |
| KPI label | `.type-kpi-label` | `--font-sans` | 11px | 500 | 1.4 | `--color-text-secondary` |
| Table header | `.type-table-header` | `--font-mono` | 11px | 500 | 1.4 | `--color-text-tertiary` |
| Table cell | `.type-table-cell` | `--font-sans` | 13px | 400 | 1.4 | `--color-text-secondary` |
| Status/feature badge | `.type-badge` | `--font-sans` | 11px | 500 | 1 | Semantic token |
| IDs, paths, commands | `.type-mono-value` | `--font-mono` | 13px | 500 | 1.4 | `--color-text-secondary` |
| Timestamp/helper text | `.type-caption` | `--font-sans` | 11px | 400 | 1.4 | `--color-text-tertiary` |
| Compact source label | `.type-compact-label` | `--font-mono` | 9px | 500 | 1.4 | Source semantic token |

## Color Application

| Element | Property | Token | Notes |
|---------|----------|-------|-------|
| Page | background | `--color-bg` | Existing app content background |
| Elevated surface | background/border/shadow | `.surface` | Summary, finding cards, drawer, menus, empty states |
| Filter bar | background/border | `--color-bg-elevated`, `--color-border-light` | Sticky layer; pair border with existing elevated treatment |
| Primary action | background/text | `--color-accent`, `--color-bg` | File defect only |
| Secondary action/link | color | `--color-violet` | Manager report, canonical spec, and navigation links |
| Confirmed/Eval pass/filed | color/background | `--color-emerald`, `.status-done-bg` | Always paired with text label or icon |
| Failed/P0/blocking error | color/background | `--color-red`, `.status-failed-bg` | P0 and blocking errors only |
| Warning/P1-P2/stale | color/background | `--color-amber`, `.status-running-bg` | Stale evidence, metadata warnings, P1-P2 |
| Review/verification | color/background | `--color-blue`, `.status-review-bg` | Review and verification semantics |
| P3 severity | color/background | `--color-text-secondary`, `.status-pending-bg` | Neutral severity treatment consistent with existing DefectRow |
| Pending/unjudged/untriaged | color/background | `--color-text-secondary`, `.status-pending-bg` | Do not use tertiary text for required meaning |
| Diagnose source | color | `--color-cyan` | Source badge only |
| Review source | color | `--color-violet` | Source badge only |
| Eval source | color | `--color-blue` | Source badge only |
| Backdrop | background | Existing modal backdrop treatment | If no shared treatment exists, add a named design-system token before implementation |

## Elevation & Depth

| Element | Elevation Level | Treatment |
|---------|----------------|-----------|
| Page and grouped table rows | 0 | Flat on `--color-bg`; rows separated by `--color-border-light` |
| Finding cards, summary, empty states | 1 | `.surface` |
| Sticky filter bar | 2 | `.surface-elevated` plus bottom border; no standalone shadow |
| Filter popovers and export menu | 3 | `.surface` with existing menu z-index |
| Draft drawer | 4 | `.surface` treatment on left boundary and shared modal z-index above backdrop |
| Toast | 5 | Existing Toast treatment; highest transient layer |

## States

### Page-Level States

#### Empty State

**Findings inbox, no evidence:** Keep the header and zeroed summary. Replace the list with a `.surface` message: “No Diagnose, Review, or Eval findings are available for payments.” Provide Back to feature and Refresh evidence actions. Do not offer Create defect.

**Findings inbox, all dispositioned:** Show the list collapsed under “Dispositioned,” with “No unresolved findings” as the primary message. Filed links remain available.

**Defect report, no defects:** Show zeroed summary and “No defect specs or tracked defect state found.” Keep filters and disable Export.

**Defect report, filters match nothing:** Preserve active filters and show “No defects match these filters,” plus Clear all. Do not replace the portfolio summary with zeros; the summary immediately above the result shows filtered totals and is labeled “Filtered result.”

#### Loading State

Preserve page geometry with opacity-fade skeleton blocks: one header line, summary surface, filter bar, and three result rows. Do not pulse. Existing content remains visible with reduced opacity during a background refresh; controls that could mutate stale data are disabled until refresh completes.

#### Populated State

Findings render unresolved before dispositioned. Cards default collapsed except a deep-linked finding or the first blocking confirmed failure. Evidence details load in the initial query but remain visually collapsed.

The unfiltered manager report groups records under primary affected feature headings and places Unassigned last. Any active feature filter switches the result to one flat table labeled with the selected feature chips. Every defect appears once. Active and Closed totals are always derived from exact state: `resolved` and `rejected` are Closed; all other states, including `escalated`, are Active.

#### Error State

**Whole-query error:** Render the page header, then a `.surface` error with the safe error message, Retry, and Back to Define. Never show a blank page.

**Partial evidence/metadata error:** Render all valid content plus `PartialEvidenceBanner` or row-level `DefectMetadataWarning`. A malformed record never blocks unrelated records.

**Mutation error:** Keep the finding or draft open, preserve user input, focus the error summary, and offer the action appropriate to the code: Refresh evidence, Review duplicate, Retry filing, or Cancel.

### Finding and Draft State Matrix

| State | Finding card | Available action | Draft behavior |
|-------|--------------|------------------|----------------|
| Unresolved | Full title, confidence, recommendation, source badges | All valid dispositions | Drawer remains shut until Create defect |
| Risk signal unconfirmed | “Unjudged risk” label | Investigate, false positive, needs verification | Filing disabled until observable failure supplied |
| Stale | Amber stale banner and prior disposition | Refresh or reaffirm where allowed | File disabled; Refresh evidence explicit |
| Preview valid | Finding remains visible beneath inert backdrop | None behind drawer | File defect enabled after severity confirmation |
| Preview invalid | Same | None behind drawer | Inline errors; focus first invalid field; file disabled |
| Duplicate candidate | Duplicate badge and existing target link | Duplicate or continue with acknowledgement | Separate-defect acknowledgement required |
| Filing | Card and drawer controls disabled | None | Label becomes “Filing…”, width locked, no close by backdrop |
| Filed | Filed badge and canonical slug | Open defect, view report, start triage | Drawer closes after success announcement |
| Write failure | Original unresolved state retained | Retry or cancel | Edits preserved; error summary focused |

### Report Record State Matrix

| State | Row treatment | Link behavior |
|-------|---------------|---------------|
| Complete spec + state | Normal severity/status/title/features | Canonical title opens editor deep link |
| Resolved | `Resolved` status plus Closed category | Canonical link active; no manual Reopen action |
| Rejected | `Rejected` status plus Closed category | Canonical link active; rejection provenance retained |
| Escalated | `Escalated` plus Needs attention indicator in Active category | Canonical link active; never styled as closed |
| Spec only | `Untriaged` status badge and warning icon | Canonical title remains active |
| State only | `Repair required` warning and missing-report text | Canonical link disabled |
| Conflicting metadata | Resolved value shown plus amber warning disclosure | Canonical link active if safe spec exists |
| Unknown related feature | Feature badge plus warning indicator | Feature badge still filters; no feature-detail link |
| Unassigned | Unassigned badge | Badge applies `__unassigned__` filter |

### Interactive Element States

| Component | Enabled | Hover | Focus | Pressed | Disabled | Loading |
|-----------|---------|-------|-------|---------|----------|---------|
| PrimaryButton | `--color-accent` bg, `--color-bg` text | existing accent hover treatment | visible shared focus ring | accent active treatment | opacity reduced, `not-allowed` | spinner + stable label width |
| SecondaryButton | `--color-bg-elevated`, border + text | `--color-bg-card-hover` | visible shared focus ring | elevated active treatment | opacity reduced, `not-allowed` | spinner + label |
| FindingCard trigger | full-width transparent button | `--color-bg-card-hover` tint | visible shared focus ring | same as hover | N/A | N/A |
| EvidenceDisclosure | caret + label | text becomes `--color-text` | visible shared focus ring | toggles `aria-expanded` | unavailable evidence is text, not button | N/A |
| Filter control | current value + border | `--color-bg-card-hover` | visible shared focus ring | menu open | disabled during initial load | compact spinner |
| Filter chip remove | icon button | `--color-bg-card-hover` | visible shared focus ring | removes chip and URL value | N/A | N/A |
| Canonical defect link | `--color-violet` text | underline | visible shared focus ring | navigates | state-only record renders non-link text | N/A |
| Export button | secondary action | elevated hover | visible shared focus ring | opens menu | no matching records | spinner during request |
| Drawer close | icon button | `--color-bg-card-hover` | visible shared focus ring | closes when safe | disabled during filing | N/A |

## Data Binding

| Element | Source Field | Format | Constraints |
|---------|-------------|--------|-------------|
| Feature title | `FeatureFindingsView.featureName` | Humanized slug with slug retained in breadcrumb | One line; ellipsis after available width |
| Evidence time | `FeatureFindingsView.generatedAt` | Local date/time with exact ISO in title | Caption |
| Findings metrics | `FeatureFindingsView.summary.*` | Integer | Zero shown explicitly |
| Finding title | `FeatureFinding.title` | String | Two-line clamp in collapsed card; full when expanded |
| Confidence | `FeatureFinding.confidence` | Confirmed, Interpreted, Unjudged, Silent | Text plus semantic badge |
| Recommendation | `FeatureFinding.recommendedAction` | Human label | Never represented by color alone |
| Source badge | `FindingEvidence.source` | Diagnose, Review, Eval | Fixed vocabulary |
| Evidence summary | `FindingEvidence.summary` | Plain text | Wrap; no HTML rendering |
| Source file | `FindingEvidence.files[]` | Monospace button opening an inline read-only excerpt | Only exact evidence-declared paths; server enforces containment and bounded text reads |
| Artifact/log/command | `artifactPath`, `logPath`, `command` | Monospace inert text with Copy action | Never execute; middle-ellipsis only when collapsed |
| Source Feature | draft source feature | Read-only feature badge | Immutable in drawer |
| Related Features | draft/report `relatedFeatures` | Ordered removable badges | At least one before filing; first is primary affected feature |
| Draft path | `suggestedSlug` | `specs/defects/<slug>.md` | Recomputed after title/slug edit; project-relative only |
| Report summary | `DefectReportView.summary` | Integer counts by status/severity/source | Unique slugs only |
| Report group | `DefectReportGroup.displayName` | Feature display name or Unassigned | Only used when no feature filter is active |
| Defect title | `DefectReportItem.title` | Canonical report title | Two-line maximum on compact widths |
| Severity | `DefectReportItem.severity` | P0-P3 or Unknown | Badge and accessible text |
| Status | `DefectReportItem.status` | Humanized lifecycle value | No inferred status beyond `untriaged` |
| Lifecycle category | `DefectReportItem.lifecycleCategory` | Active or Closed | Derived: Closed only for `resolved` or `rejected`; never persisted by UI |
| Updated time | `DefectReportItem.updatedAt` | Relative under 7 days, otherwise local date; ISO title | Fallback to created time, then em dash |
| Metadata warnings | `DefectReportItem.warnings` | Short label + disclosure text | Multiple warnings collapse under one icon/count |

## Interactions & Motion

### Interactions

| Trigger | Target | Response | Notes |
|---------|--------|----------|-------|
| Click finding header | FindingCard | Expand/collapse evidence and actions | Updates `aria-expanded`; no route change unless deep-linked |
| Click evidence disclosure | EvidenceDisclosure | Reveal source records in strength order | Eval, Review, Diagnose ordering; retain source labels |
| Click declared source file | EvidenceSourceExcerpt | Load a bounded read-only excerpt inline and highlight the declared line | Never loads arbitrary, escaping, binary, environment, or oversized paths |
| Choose non-defect disposition | DispositionControls | Reveal only required inputs; submit writes decision | Successful card collapses to decision summary |
| Choose Create defect | FindingCard | Request preview, then open DefectDraftDrawer | Preview makes no filesystem writes |
| Edit draft field | DefectDraftDrawer | Update local draft and field validation | No mutation until File defect |
| Change Related Features | RelatedFeaturePicker | Update ordered affected set | Source Feature remains separately visible and immutable |
| Click Refresh evidence | DraftValidationSummary | Confirm refresh, rebuild preview, visually mark changed fields | User edits are not silently overwritten |
| Click File defect | Drawer footer | Validate then invoke filing mutation | Disable drawer controls while in flight; one request at a time |
| Click Cancel/Escape | Draft drawer | Close and return focus to Create defect trigger | Block Escape only while filing |
| Change report filter | DefectReportFilters | Normalize and replace URL query; refetch report | Search debounced 250ms; selects apply immediately |
| Remove filter chip | ActiveFilterChips | Remove one URL value and refetch | Clear all removes all report parameters |
| Click feature badge | DefectReportRow | Apply that feature as the report filter | Does not navigate to source feature findings |
| Click defect title | DefectReportRow | Open editor deep link with encoded safe return URL | Missing-spec rows have no link |
| Click Source Finding in editor/detail | Provenance link | Open deep-linked finding route | Only when feature and finding ID are valid |
| Click Export | ExportMenu | Request current JSON/Markdown and start download | Same filters/order as visible result; no server file write |
| Browser Back | Any deep-linked page | Restore prior URL filters and browser scroll where supported | No custom history replacement after initial filter change |

### Motion

Use the existing interaction timing already established in dashboard surfaces; no new motion tokens are introduced.

| Name | Duration | Easing | Property | Usage |
|------|----------|--------|----------|-------|
| control-state | 150ms | ease | background, border-color, color | Buttons, rows, filters, links |
| disclosure | 150ms | ease-out | opacity | Evidence content appearing; height changes may be instant |
| drawer-enter | 200ms | ease-out | transform, opacity | Drawer from right and backdrop fade |
| drawer-exit | 150ms | ease-in | transform, opacity | Drawer close after cancel or success |
| deep-link-focus | 600ms | ease-out | outline-color | One-time focus emphasis on requested finding |

**Reduced motion policy:** Under `prefers-reduced-motion: reduce`, drawer and disclosure transitions become instant, deep-link focus remains as a static visible outline, and loading uses static skeleton blocks. Functional state changes and focus movement remain intact.

## Responsive Behavior

| Breakpoint | Columns | Behavior |
|------------|---------|----------|
| `< 768px` | N/A | Unsupported by the current dashboard shell. Content remains readable through horizontal viewport scrolling; no separate mobile navigation is introduced by this feature. |
| `768-1023px` | 1 | Finding cards remain one column. Draft drawer becomes full content width. Summary metrics wrap to two columns. Report table switches to stacked record rows with labeled values; sticky filters wrap. |
| `1024-1279px` | 1 | Standard supported layout. Drawer uses `max-w-2xl`; report columns hide Source and show it in row disclosure. Summary uses five equal or wrapped cells. |
| `>= 1280px` | 1 | Full report table columns visible. Content follows the app shell width; no independent max-width is added. |

## Accessibility

### Keyboard Navigation

| Component | Keys | Behavior |
|-----------|------|----------|
| FindingCard header | Enter/Space | Toggle expanded state |
| Finding list | Tab | Move through card headers and visible actions in document order |
| EvidenceDisclosure | Enter/Space | Toggle evidence; focus remains on trigger |
| Disposition radio group | Arrow keys | Move selection within valid actions |
| RelatedFeaturePicker | Enter/Space | Open; arrows navigate; Enter selects; Backspace removes last badge when input is empty |
| Draft drawer | Tab/Shift+Tab | Trap focus inside while open |
| Draft drawer | Escape | Cancel and restore trigger focus unless filing is in progress |
| Filter multiselect | Enter/Space | Open; arrows navigate; Enter toggles; Escape closes |
| Defect table | Tab | Visit title and feature links in row order; rows themselves are not extra tab stops |
| Export menu | Enter/Space | Open; arrows navigate; Enter activates; Escape closes and restores focus |

### ARIA & Screen Reader

| Component | Role | ARIA | Announcement |
|-----------|------|------|--------------|
| FindingsSummary | region | `aria-label="Findings summary"` | Metric labels and values in reading order |
| FindingCard header | button | `aria-expanded`, `aria-controls` | Title, confidence, disposition, evidence-source count |
| PartialEvidenceBanner | status | `aria-live="polite"` | Number of unavailable sources and that valid results remain |
| DispositionControls | radiogroup | `aria-labelledby` to finding title | Selected action and revealed required inputs |
| DefectDraftDrawer | dialog | `aria-modal="true"`, labelled by draft title | “Defect draft for <finding title>” on open |
| DraftValidationSummary | alert | `aria-live="assertive"` on submit failure | Count and first blocking error |
| Filing result | status | `aria-live="polite"` | Canonical path on success |
| Report filters | search | `aria-label="Filter defects"` | Updated unique result count after each applied filter |
| DefectReportTable | table | Caption identifies all/grouped/filtered view | Column headers associated with cells |
| Metadata warning | button + description | `aria-expanded`, `aria-describedby` | Warning count and full warning text |
| Toast | status or alert | Existing Toast contract | Export success is polite; export failure is assertive |

### Contrast & Targets

Required text uses `--color-text` or `--color-text-secondary`, which meet the design system's documented contrast against dashboard surfaces. `--color-text-tertiary` is restricted to decorative timestamps and helper labels, never required status or error content. All buttons, filter triggers, badge-removal controls, disclosure triggers, and links have a minimum 44px target through padding or an expanded pseudo-element. Status meaning always combines text or icon with color.

## Content Constraints

| Element | Min | Max | Overflow | Placeholder |
|---------|-----|-----|----------|-------------|
| Finding title | 1 char | 160 chars displayed | Two-line clamp collapsed; full expanded | “Untitled finding” only for malformed legacy evidence |
| Evidence summary | 1 char | 2,000 chars displayed | Wrap; disclosure for additional records | “Evidence summary unavailable” |
| Rationale | 10 chars | 2,000 chars | Counter after 1,800; reject over max | Action-specific prompt |
| Defect title | 1 char | 160 chars | One line in report; full in drawer/editor | None; required |
| Slug | 1 char | 80 chars | No visual truncation in editable control | Generated from title |
| Related Features | 1 item | 20 items | Wrap badges; scroll picker menu | Source Feature preselected |
| Observed/Expected/Reproduction | 20 non-whitespace chars | Bounded by 128 KiB report total | Textarea grows to defined maximum then scrolls | Generated evidence or explicit incomplete marker |
| Report search | 0 chars | 200 chars | One line | “Search defect name or title…” |
| Feature badge | 1 char | 50 chars | Ellipsis with full `title` | “Unassigned” |
| Defect report result | 0 records | 500 records | Page scroll; no client truncation | Context-specific empty state |
| Warning text | 1 char | 240 chars displayed | Wrap within disclosure | “Metadata warning” |

## Implementation Notes

- Reuse existing app-shell, `.surface`, typography roles, status backgrounds, Toast, and shared focus-ring conventions. Add named design-system tokens before using any new backdrop, focus, spacing, or color value.
- Treat GraphQL data as the rendering contract. The frontend must not independently parse defect markdown, correlate findings, compute primary features, or recalculate unique totals.
- Findings filter state may be local in V1 except the `finding` deep link. Manager-report filters must be URL-backed because sharing and browser restoration are product requirements.
- The editor must read the optional safe `spec` query parameter once on initial navigation, validate it as a project-relative `specs/defects/*.md` path, and open it through the existing `openSpec` path. It must ignore unsafe or nonexistent targets with a visible warning.
- The optional `return` query parameter must start with `/define/defects` after URL decoding. Never accept an origin, protocol-relative URL, or arbitrary path.
- While the drawer is open, apply `inert` and `aria-hidden` to background content and lock page scroll. Restore focus to the invoking Create defect button on cancel or error close, and to the filed confirmation link after success.
- Preserve draft edits in component state across preview validation and recoverable mutation errors. A deliberate Cancel or successful filing clears them. A full browser refresh does not promise draft recovery.
- Use a real semantic `<table>` at desktop widths. The stacked 768-1023px variant must preserve labels and DOM reading order; do not convert it into unlabeled decorative cards.
- Export uses the backend-provided filename and content. Create a temporary Blob URL, click a temporary download anchor, then revoke the URL. Do not persist exports on the server.
- No component in this design executes copied commands or opens raw artifact paths directly. Copy is allowed; navigation is limited to validated project routes.

## Verification Criteria

- [ ] Every PRD user flow maps to one of the documented routes or an explicit state transition on those routes
- [ ] Findings distinguish confirmed, interpreted, unjudged, and silent evidence with text labels, not color alone
- [ ] Opening, editing, refreshing, or canceling a defect draft performs no canonical filesystem write
- [ ] Source Feature is read-only in the draft; Related Features defaults to it, is editable, and requires at least one value
- [ ] Filing errors and stale evidence preserve draft edits and move focus to an actionable error summary
- [ ] Successful filing replaces disposition controls with canonical-report, manager-report, and triage links
- [ ] The unfiltered report groups each slug once by primary affected feature and places Unassigned last
- [ ] Any active feature filter renders one flat deduplicated list matching any Related Feature
- [ ] Spec-only records display Untriaged; state-only records display Repair required with no canonical link
- [ ] `resolved` and `rejected` automatically display in Closed; every other exact status, including `escalated`, displays in Active
- [ ] No report surface exposes Close or Reopen; lifecycle categories update from authoritative defect state on refresh
- [ ] Report filters survive refresh, browser Back/Forward, and copied-URL navigation
- [ ] JSON and Markdown downloads use the exact visible filters and unique ordered record set
- [ ] Editor and source-finding deep links reject unsafe paths and preserve a validated report return URL
- [ ] Draft drawer traps focus, Escape behavior follows filing state, and focus returns correctly on close
- [ ] All controls have visible focus, status is not color-only, and required text does not use `--color-text-tertiary`
- [ ] At 768-1023px the drawer is full width and the report uses labeled stacked rows; at 1024px and 1280px the documented desktop layouts render without horizontal clipping
- [ ] Reduced-motion mode removes drawer/disclosure animation while retaining state and focus changes
- [ ] No visual property introduces an undefined color, font, elevation, or motion token

## Figma / Visual Reference

No Figma file or raster mockup exists for this feature. This design spec is the source of truth for behavior, states, data binding, accessibility, and spatial relationships. Visual implementation should extend the existing [Dashboard Define Surface](speed-dashboard-define.md) and [Dashboard Outcome Review](speed-dashboard-outcome-review.md) patterns without introducing a new visual language.
