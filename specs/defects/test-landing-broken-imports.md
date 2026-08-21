# Defect: test_landing.py has broken imports that prevent test collection

Severity: P1
Related Feature: speed-dashboard-define

## Observed Behavior

`dashboard/backend/tests/test_landing.py` cannot be collected by pytest. Two ImportErrors kill the entire module at import time, blocking all tests in the file.

1. Line 34 imports `_generate_narrative` from `resolvers.landing`. That function does not exist. The actual name is `_generate_narrative_for_feature` (landing.py:141), and it has a different signature: `(feature: LandingCompletedFeature, project_name: str, execute: LandingExecutePanel)`.

2. Line 44 imports `LandingPendingReview` from `resolvers.landing_types`. That class does not exist. The Judge panel uses `LandingCompletedFeature` (landing_types.py:49) with a `review_status` field, plus `LandingQualityGate` (landing_types.py:64). `LandingJudgePanel` (landing_types.py:73) has fields `completed_features` and `quality_gates`, not `pending_review` or `last_completed`.

Additional issues in the same file that will fail after imports are fixed:

3. All `TestJudgePanel` tests (around line 193) access `panel.pending_review` and `panel.last_completed`. Neither field exists on `LandingJudgePanel`. The actual fields are `completed_features: list[LandingCompletedFeature]` and `quality_gates: list[LandingQualityGate]`.

4. `test_draft_specs_speed_prefix_stripped` (line 127) asserts `name == 'auth'` for spec file `speed-auth.md`. `_feature_name()` returns `spec_file.stem` verbatim, which is `'speed-auth'`. Either implement prefix stripping or fix the test assertion.

5. `LandingExecutePanel` is constructed without its required `recent_features` field at lines 685, 703, 723. Strawberry types enforce field presence. Add `recent_features=[]` to each constructor call.

6. `test_landing_types.py:88` has `EXPECTED_CLASSES` listing `LandingPendingReview` and `LandingLastCompleted`, neither of which exists. Update to match actual classes in landing_types.py.

## Expected Behavior

All imports resolve. All tests pass via `pytest dashboard/backend/tests/test_landing.py`.

## Affected Files

- `dashboard/backend/tests/test_landing.py` (primary — fix imports, field names, constructor args)
- `dashboard/backend/tests/test_landing_types.py` (fix EXPECTED_CLASSES list)
- `dashboard/backend/resolvers/landing.py` (may need alias for `_generate_narrative` or other minor adjustments to match test expectations)

## Reproduction Steps

1. `cd dashboard/backend`
2. `pytest tests/test_landing.py --collect-only` — fails with `ImportError: cannot import name '_generate_narrative'`
3. Fix that import, run again — fails with `ImportError: cannot import name 'LandingPendingReview'`

## Acceptance Criteria

- `from resolvers.landing import _generate_narrative_for_feature` with correct call sites
- `LandingPendingReview` removed from imports; tests use `LandingCompletedFeature` and `LandingQualityGate`
- TestJudgePanel tests use `completed_features` and `quality_gates` fields
- `test_draft_specs_speed_prefix_stripped` assertion matches `_feature_name()` behavior
- `LandingExecutePanel(...)` calls include `recent_features=[]`
- `EXPECTED_CLASSES` in test_landing_types.py matches actual landing_types.py exports
- `pytest dashboard/backend/tests/test_landing.py` collects and passes all tests
- `pytest dashboard/backend/tests/test_landing_types.py` passes
