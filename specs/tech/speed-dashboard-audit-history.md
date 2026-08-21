---
status: draft
feature: speed-dashboard-audit-history
---

# RFC: Dashboard Audit History Panel — Features

> See [product spec](../product/speed-dashboard-audit-history.md) for product context.
> Depends on: Audit persistence (shipped — `latestAudit` + `recentAudits` queries)

## Basic Example

```tsx
// User clicks the second verdict dot to view an older audit
<VerdictDot status="warn" selected={selectedRunIndex === 1}
  onClick={() => setSelectedRunIndex(1)} />

// Findings list shows that run's issues
const selectedAudit = recentAudits[selectedRunIndex];
const findings = buildFindings(selectedAudit, recentAudits[selectedRunIndex + 1], ambiguities);

// Shift-click two dots to compare
<VerdictDot status="pass" compareSelected={compareIndices?.includes(0)}
  onClick={(e) => e.shiftKey ? addCompareIndex(0) : setSelectedRunIndex(0)} />
```

## Data Model

### SpeedAuditResult (already exists)

```typescript
interface SpeedAuditResult {
  status: string;        // pass | warn | fail
  specType: string;
  specFile: string;
  issues: AuditIssue[];  // {level, severity, section, message}
  sizing: AuditSizing | null;
  stale: boolean;
  ranAt: string;         // ISO timestamp
  feature: string;
}
```

### New Frontend State

```typescript
selectedRunIndex: number;                   // index into recentAudits, 0 = latest
compareIndices: [number, number] | null;    // two indices for comparison mode
```

No new GraphQL types, queries, or mutations.

## State Machine

Two UI entities have state transitions:

| Entity | States | Transitions |
|--------|--------|-------------|
| Run selection | `default` → `selected` → `default` | Click dot sets `selected`. Click latest or Escape returns to `default`. |
| Comparison mode | `inactive` → `active` → `inactive` | Shift-click second dot enters `active`. Escape or "Exit comparison" returns to `inactive`. Entering comparison clears single selection. |

Invalid transitions:
- Cannot compare with fewer than 2 audit runs (shift-click is no-op)
- Cannot select a dot index beyond `recentAudits.length - 1`

## API Surface

No backend changes. All work is in `IntelPanel.tsx`.

### Functions to modify

**`buildFindings(audit, previousAudit, ambiguity)` — no signature change**

Already accepts any audit pair. The caller changes which `recentAudits[i]` it passes based on `selectedRunIndex`.

### Functions to add

**`formatRelativeTime(isoString: string): string`**

| Input | Output |
|-------|--------|
| < 60s ago | "just now" |
| < 60m ago | "Nm ago" |
| < 24h ago | "Nh ago" |
| < 7d ago | "Nd ago" |
| >= 7d ago | "Mar 15" (short date) |
| empty/invalid | "unknown" |

## Validation Rules

| Field | Constraints |
|-------|-------------|
| `selectedRunIndex` | Integer, `0 <= index < recentAudits.length`. Clamped if audits are pruned between renders. |
| `compareIndices` | Tuple of two distinct integers within bounds, or null. `compareIndices[0] < compareIndices[1]` (older first). |
| Shift-click target | Must differ from existing `compareIndices[0]`. Clicking the same dot twice cancels comparison. |

## Component Changes

### Verdict dots (modify)

Each dot becomes a `<button>`. Click sets `selectedRunIndex`. Shift-click sets `compareIndices`. Selected dot gets 2px ring. Tooltip shows relative timestamp.

### Run header (new, conditional)

Appears when `selectedRunIndex !== 0`: "Viewing audit from {relativeTime}" with "← Latest" link.

### Findings list (modify)

Shows `recentAudits[selectedRunIndex]` instead of always latest. `buildFindings` receives selected audit as primary and the next older one as previous for delta computation.

### Comparison mode (new, conditional)

Replaces findings list when `compareIndices` is set. Groups findings into Removed, Unchanged, Added. Shows issue count delta between the two runs.

### Sizing card (modify)

Shows selected run's sizing. In comparison mode, shows both if they differ.

## Testing

### Acceptance Criteria

- Clicking a verdict dot loads that run's findings
- Selected dot has a visible ring
- Shift-click two dots enters comparison mode showing added/removed/unchanged
- Comparison mode shows issue count delta
- Escape exits comparison mode and run selection
- `formatRelativeTime` returns correct strings for all time ranges
- Panel degrades gracefully with 0 or 1 audit runs

### Risks and Coverage

| Risk | Severity | Test Approach |
|------|----------|---------------|
| Audit files pruned between renders — selected index out of bounds | Medium | Unit test: clamp index when recentAudits shrinks |
| Shift-click not discoverable on trackpad | Low | Not tested — UX documentation concern, not a code risk |
| Delta computation has false matches (same section + message prefix from different issues) | Medium | Unit test: verify `issueKey` distinguishes issues with same section but different messages |

### Test Plan

**Unit tests**
- `formatRelativeTime` with edge cases (future, empty, boundary values)
- `buildFindings` delta computation (new, persistent, resolved, mixed)
- `issueKey` uniqueness verification
- Index clamping when audit count changes

**Integration tests**
Not needed — no backend changes, no cross-module interactions.

**End-to-end tests**
Deferred to the Tests RFC which covers component-level interaction testing.

**Visual/UI tests**
- Verdict dot states: default, selected, compare-selected
- Comparison mode layout with added/removed/unchanged sections
- Run header appearance/disappearance

### Edge Cases

- 0 audit runs: no dots rendered, no interaction possible
- 1 audit run: single dot, click does nothing (already viewing latest), shift-click is no-op
- All issues resolved between runs: comparison shows only "Removed" section
- All issues are new: comparison shows only "Added" section
- Identical runs: comparison shows only "Unchanged" section
- Sizing changed between runs: both sizing cards shown in comparison
- Sizing identical: single sizing card in comparison

### Out of Scope

- Component tests for verdict dot clicks and comparison mode — covered by Tests RFC
- Performance testing — audit data is at most 3 runs with ~20 issues each, no performance concern

## Security & Controls

No authentication, authorization, or data sensitivity changes. The dashboard is a local development tool. Audit data contains spec section names and issue messages — no PII, no secrets. No new endpoints. No rate limiting needed.

## Key Decisions

| Decision | Choice | Alternatives Considered | Rationale |
|----------|--------|------------------------|-----------|
| Run selection via dot click | Index into `recentAudits` array | Dropdown selector, tab bar | Dots are already rendered; making them interactive is zero new chrome. Dropdown adds a form element to a dense panel. |
| Comparison via shift-click | Shift modifier + second dot | Dedicated "Compare" button, drag between dots | Shift-click is standard multi-select UX (file managers, GitHub). No extra UI needed. |
| Delta grouping in comparison | Removed → Unchanged → Added | Side-by-side columns, inline diff | Grouped list is readable in the narrow panel width. Side-by-side needs horizontal space the panel doesn't have. |
| Relative timestamps | Custom `formatRelativeTime` helper | `date-fns`, `dayjs`, `Intl.RelativeTimeFormat` | No dependency for 15 lines of code. `Intl.RelativeTimeFormat` has inconsistent output across browsers. |

## Drawbacks

- Shift-click is not discoverable without documentation. Trackpad users may never find comparison mode. A future iteration could add a tooltip or a small "Compare" icon.
- The `issueKey` function matches on `section + message[:80]`. Two genuinely different issues with the same section and similar opening text would be incorrectly matched as "persistent." This is unlikely given audit message specificity but not impossible.
- Comparison mode replaces the findings list entirely. The user cannot see the current findings and the comparison simultaneously.

## File Impact

| File | Change |
|------|--------|
| `dashboard/frontend/components/editor/IntelPanel.tsx` | Add `selectedRunIndex`, `compareIndices` state. Modify verdict dots to buttons. Add `formatRelativeTime` helper. Add run header. Add comparison mode layout. Modify findings list to respect selection. |

Single file change. No backend modifications.

## Dependencies

- `recentAudits` GraphQL query (shipped) — returns `[SpeedAuditResult]` from disk
- `AUDIT_COMPLETED` subscription (shipped) — triggers refetch when new audit files appear
- `buildFindings` function (shipped) — already accepts arbitrary audit pairs for delta computation

All dependencies are implemented and operational.

## Unresolved Questions

None. The interaction model follows established patterns (GitHub PR file-change dots, Linear history). All backend infrastructure exists.
