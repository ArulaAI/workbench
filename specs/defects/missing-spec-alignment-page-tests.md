# Defect: Spec Alignment page test file never created

Severity: P1
Related Feature: speed-dashboard-define

## Observed Behavior

Task 12 ("Tests for Spec Alignment page") has cycled through run → review → run three times without producing any code. The file `dashboard/frontend/app/spec-alignment/page.test.tsx` does not exist. All 10 acceptance criteria are unsatisfied.

The root cause is a `branch_audit` short-circuit in `run.sh`. Task 12's branch was created from the integration branch (`feature/dashboard-human-surfaces`), which contains prototype code from earlier tasks. When `speed run` checks the branch before spawning an agent, `branch_audit` measures `git diff feature/continuous-learning...task-branch`. The inherited prototype code produces a non-empty diff, so `diff_non_empty` passes. The task is auto-promoted to `done` without the agent ever running.

Review correctly identifies the missing file and returns `request_changes`, setting the task back to `pending`. But the next `speed run` hits the same short-circuit. The cycle repeats indefinitely.

## Expected Behavior

`dashboard/frontend/app/spec-alignment/page.test.tsx` should exist with Vitest tests covering all component behaviors of `dashboard/frontend/app/spec-alignment/page.tsx`.

## Affected File

`dashboard/frontend/app/spec-alignment/page.test.tsx` (does not exist, must be created)

## Component Under Test

`dashboard/frontend/app/spec-alignment/page.tsx` — the Spec Alignment page component. Uses:
- `useQuery` from urql with `SPEC_ALIGNMENT_QUERY`
- Types: `SpecAlignmentClaim`, `SpecAlignmentSection`, `SpecAlignmentSpec`, `SpecAlignmentView`
- Shared components: `ProgressBar`, `CardSkeleton`, `formatPercent`
- Icons from lucide-react: `Check`, `X`, `HelpCircle`, `Copy`, `CheckCircle`, `ChevronDown`, `ChevronRight`
- `statusConfig` mapping claim statuses to colors and icons

## Acceptance Criteria

- Loading skeleton renders while query is fetching
- Error state renders when query fails
- Empty state shows 'speed plan' code tag when no data
- Summary bar stat values match fixture data
- Coverage color thresholds: red (<50%), amber (50-79%), emerald (>=80%)
- Section expand/collapse toggle works
- All four claim status badges render correct colors (confirmed=emerald, missing=red, unverifiable=tertiary, divergent=amber)
- Evidence copy button calls clipboard API
- Divergent claim text renders in amber
- All tests pass via `npx vitest run` in `dashboard/frontend`

## Reproduction Steps

1. `ls dashboard/frontend/app/spec-alignment/page.test.tsx` — file not found
2. `npx vitest run dashboard/frontend/app/spec-alignment/page.test.tsx` — no tests collected
