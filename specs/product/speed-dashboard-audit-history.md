---
status: draft
feature: speed-dashboard-audit-history
---

# Dashboard: Audit History Panel

> Depends on: Spec Editor (shipped), Audit Persistence (shipped)

## Problem

The spec editor's Findings tab shows the latest audit result and a verdict strip with dots for recent runs. But there's no way to drill into a past audit, compare two runs side by side, or see which issues were fixed between iterations. A user editing a spec iteratively runs audit, fixes issues, runs again. They see the current state but lose the trail of how they got there. When the edit-audit loop goes in circles (fix one thing, break another), the only signal is a net change number and delta tags comparing latest vs. previous — not the full trajectory.

The audit data exists on disk (SPEED retains the last 3 per category). The verdict strip shows colored dots. Clicking a dot does nothing.

## Users

### Spec Author
Writes and iterates on specs. Runs audit repeatedly during editing. Wants to see progress over time: are issues going down? Which ones keep coming back? Needs to compare any two runs to see what changed.

### Reviewer
Reviews specs before approval. Wants to see the audit trail: how many rounds of editing, what the trajectory looked like, whether persistent issues remain unresolved.

## User Stories

| ID | Story | Acceptance Criteria | Priority |
|----|-------|---------------------|----------|
| AH1 | As a spec author, I want to click a verdict dot and see that audit's full findings | Given 3 audit runs exist for a spec, When I click the middle dot, Then the findings list shows that run's issues and the dot is visually selected | Must |
| AH2 | As a spec author, I want to compare two audit runs to see what changed | Given 2+ audit runs, When I shift-click two dots, Then a comparison view shows added/removed/unchanged findings | Must |
| AH3 | As a spec author, I want to see a net issue count trend across runs | Given 3 audit runs with 5, 3, and 2 issues, When I view the verdict strip, Then issue counts or a visual trend is visible | Must |
| AH4 | As a reviewer, I want to see persistent issues that survived multiple audit runs | Given an issue appears in both the latest and previous run, When I view findings, Then that issue is tagged "persistent" | Should |
| AH5 | As a spec author, I want the sizing recommendation history to show if scope estimates changed | Given two runs with different sizing, When I compare them, Then both sizing cards are shown | Should |
| AH6 | As a spec author, I want to see when each audit ran | Given audit runs exist, When I hover a verdict dot, Then a relative timestamp appears ("3h ago") | Must |

## User Flows

### View a past audit

1. User opens a spec in the editor
2. Findings tab loads the latest audit from disk
3. Verdict strip shows colored dots for recent runs
4. User clicks a dot
5. The findings list swaps to show that run's issues, with the selected dot highlighted
6. A header appears: "Viewing audit from 3h ago" with a "Back to latest" link
7. Clicking the leftmost dot (latest) returns to the current view

### Compare two runs

1. User is viewing audit findings
2. User holds Shift and clicks a second dot
3. The panel switches to comparison mode
4. Findings from both runs shown in a unified list: removed, unchanged, added sections
5. Issue counts shown for each run with net delta
6. User presses Escape or clicks "Exit comparison" to return to single-run view

### Review persistent issues

1. User views the latest audit findings
2. Findings present in both latest and previous run are tagged "persistent"
3. A "persistent issues" count appears in the verdict strip

## Success Criteria

- [ ] Clicking a verdict dot loads that audit run's findings in the panel
- [ ] Selected dot gets a visible highlight (ring or border)
- [ ] Shift-click on two dots enters comparison mode showing added/removed/unchanged findings
- [ ] Comparison mode shows issue counts for each run with net delta
- [ ] Persistent issues count shown in verdict strip when > 0
- [ ] Sizing card updates to show the selected run's sizing data
- [ ] Relative timestamps shown on verdict dot hover
- [ ] Panel falls back gracefully when fewer than 2 audit runs exist
- [ ] Escape exits comparison mode
- [ ] Works with both `audit-*.json` and `plan-audit-*.json` files

## Scope

### In Scope
- Interactive verdict dots (click to select run, shift-click to compare)
- Comparison view showing added/removed/unchanged findings between two runs
- Run selection with "Back to latest" navigation
- Relative timestamp display on hover
- Sizing card history (shows selected run's sizing)
- Keyboard navigation (Escape to exit, arrow keys between dots)

### Out of Scope (and why)
- Audit history beyond what SPEED retains on disk (3 per category) — retention policy is SPEED CLI's concern, not the dashboard's
- Diffing actual spec content between audit runs — requires git history integration which is a separate feature
- Triggering audits from the history panel — Run Audit button already exists in the action bar

## RFC Decomposition

| User Story IDs | Child RFC | Depends On | Testable Output |
|----------------|-----------|------------|-----------------|
| AH1, AH2, AH3, AH4, AH5, AH6 | `specs/tech/speed-dashboard-audit-history.md` | (none) | Verdict dots are clickable, shift-click enters comparison mode, findings update to selected run |
| (tests for above) | `specs/tech/speed-dashboard-audit-history-tests.md` | features RFC | 36 tests pass: formatRelativeTime, buildFindings deltas, verdict dot interaction, comparison mode |

<!-- features ── tests -->

## Dependencies

Audit Persistence (shipped): the `recentAudits(specPath, limit)` GraphQL query returns the last N `SpeedAuditResult` objects from disk. The audit file watcher publishes `AUDIT_COMPLETED` events when new files appear. Both are implemented and operational.

No external service dependencies. No API endpoints consumed beyond the existing GraphQL schema.

## Security & Controls

No authentication or authorization changes. The dashboard is a local development tool — all users who can access the dashboard can see all audit history. No PII in audit data. No rate limiting needed (reads from local filesystem). No audit logging beyond what SPEED CLI already writes.

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Audit files pruned between page loads — user clicks dot for a run that no longer exists on disk | Low | `recentAudits` query returns whatever exists; if a run disappears, the dot count updates on next refetch. No crash. |
| Comparison mode with very different issue sets is visually noisy | Medium | Group by removed/unchanged/added with clear section headers. Limit to 2-run comparison (no 3-way diff). |
| Shift-click is not discoverable on trackpad-only devices | Low | Verdict dots could show a "Compare" tooltip on long-press in a future iteration. For now, power-user feature. |

## Open Questions

None. The backend infrastructure is complete and the interaction model follows established patterns (GitHub PR file-change dots, Linear issue history).
