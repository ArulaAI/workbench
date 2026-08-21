---
status: draft
feature: speed-dashboard-audit-history
---

# RFC: Dashboard Audit History Panel — Tests

> See [product spec](../product/speed-dashboard-audit-history.md) for product context.
> Parent RFC: [Features](speed-dashboard-audit-history.md)
> Depends on: [Features](speed-dashboard-audit-history.md) (implementation must exist before tests exercise it)

## Basic Example

```typescript
// Unit test for formatRelativeTime
expect(formatRelativeTime(fiveMinutesAgo)).toBe("5m ago");

// Component test for verdict dot click
const { getByTitle } = render(<IntelPanel specPath="specs/tech/foo.md" ... />);
fireEvent.click(getByTitle("3h ago"));  // click older verdict dot
expect(screen.getByText("Viewing audit from 3h ago")).toBeInTheDocument();
```

## Data Model

No new data types. Tests consume the existing `SpeedAuditResult`, `AuditIssue`, and `UnifiedFinding` types as fixtures.

### Test Fixtures

```typescript
const AUDIT_FIXTURE: SpeedAuditResult = {
  status: "warn",
  specType: "rfc",
  specFile: "specs/tech/test.md",
  issues: [{ level: 2, severity: "warning", section: "API Surface", message: "Missing endpoint" }],
  sizing: { estimatedTasks: 5, recommendation: "ok", rationale: "fits", suggestedChildren: [] },
  stale: false,
  ranAt: "2026-03-25T10:00:00Z",
  feature: "test-feature",
};
```

## API Surface

No APIs. This RFC produces test files that exercise the features RFC's implementation.

### Files Produced

| File | Tests | What it verifies |
|------|-------|------------------|
| `__tests__/editor/formatRelativeTime.test.ts` | 7 | Relative time helper edge cases |
| `__tests__/editor/buildFindings.test.ts` | 10 | Delta computation (new/persistent/resolved/mixed) |
| `__tests__/editor/VerdictDots.test.tsx` | 8 | Dot rendering, click selection, shift-click comparison |
| `__tests__/editor/RunSelection.test.tsx` | 5 | Run header, findings update, back to latest |
| `__tests__/editor/ComparisonMode.test.tsx` | 6 | Added/removed/unchanged grouping, issue counts, exit |

## Validation Rules

| Rule | Constraint |
|------|-----------|
| Test isolation | Each test uses fresh fixture data, no shared mutable state |
| No real GraphQL | urql hooks mocked via `vi.mock("urql")`, matching existing patterns |
| No timers | `formatRelativeTime` receives injected timestamps, no `Date.now()` dependency |
| Deterministic | All assertions use exact values, no flaky timing checks |

## Testing

### Acceptance Criteria

- All 36 tests pass in CI
- Breaking a feature (e.g., removing Escape handler) causes the corresponding test to fail
- Coverage report shows IntelPanel verdict strip, run selection, and comparison branches covered
- No test depends on real GraphQL server or filesystem

### Risks and Coverage

| Risk | Severity | Test Approach |
|------|----------|---------------|
| urql mock doesn't match real hook behavior | Medium | Follow existing mock patterns from `__tests__/landing/LandingPage.test.tsx` |
| Fixture data drifts from actual SpeedAuditResult shape | Low | Fixtures use the TypeScript interface directly — type checker catches drift |
| Component tests break on IntelPanel restructuring | Medium | Test observable behavior (text content, DOM presence), not implementation details |

### Test Plan

**Unit tests** (17 total)
- `formatRelativeTime`: just now, minutes, hours, days, future, empty, boundary values
- `buildFindings`: no previous, new issue, persistent, resolved, mixed, same-section-different-message
- `issueKey`: identical issues same key, different section different key, long message truncation

**Integration tests**
Not applicable. Tests mock all external dependencies.

**End-to-end tests**
Deferred. Component tests with mocked data cover the interaction patterns.

**Visual/UI tests**
- Verdict dot states rendered correctly (default opacity, selected ring, compare ring)
- Comparison mode sections (Removed/Unchanged/Added) render with correct styling

### Edge Cases

- 0 audit runs: no dots, no interaction, no crash
- 1 audit run: dot rendered but not clickable, comparison impossible
- `formatRelativeTime` with future timestamp: clamps to "just now"
- `formatRelativeTime` with empty string: returns "unknown"
- `buildFindings` with null previousAudit: no delta tags
- `compareIndices` with same index twice: cancels comparison

### Out of Scope

- Performance benchmarking of `buildFindings` — data size is trivially small (max 3 runs × 20 issues)
- Snapshot testing — layout is evolving, snapshots would break constantly

## Security & Controls

No security implications. Test files do not handle user input, network requests, or sensitive data. All data is mocked fixtures.

## Key Decisions

| Decision | Choice | Alternatives Considered | Rationale |
|----------|--------|------------------------|-----------|
| Test framework | Jest + React Testing Library | Vitest, Cypress | Matches existing dashboard test infrastructure |
| Mock strategy | `vi.mock("urql")` at module level | MSW, manual fetch mocks | Consistent with 21 existing test files that use this pattern |
| Fixture approach | Typed constants per test file | Shared fixture module, factory functions | Each test file is self-contained; 36 tests don't justify shared infra |

## Drawbacks

- 36 tests across 5 files adds maintenance surface. If the features RFC changes IntelPanel structure significantly, multiple test files need updates.
- Component tests with mocked urql don't verify actual GraphQL query correctness. A real integration test (against running backend) would catch query/type mismatches but is out of scope.

## File Impact

| File | Change |
|------|--------|
| `__tests__/editor/formatRelativeTime.test.ts` | New — 7 unit tests |
| `__tests__/editor/buildFindings.test.ts` | New — 10 unit tests |
| `__tests__/editor/VerdictDots.test.tsx` | New — 8 component tests |
| `__tests__/editor/RunSelection.test.tsx` | New — 5 component tests |
| `__tests__/editor/ComparisonMode.test.tsx` | New — 6 component tests |

5 new files, 36 total tests.

## Dependencies

- Features RFC (parent): `IntelPanel.tsx` must have `selectedRunIndex`, `compareIndices`, `formatRelativeTime`, and comparison mode implemented before tests can exercise them
- Existing test infrastructure: Jest config, React Testing Library, urql mock patterns from `__tests__/landing/`

## Unresolved Questions

None. Test patterns are established in the codebase, fixture shapes match existing TypeScript interfaces.
