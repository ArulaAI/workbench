# Defect: spec_alignment resolver crashes on malformed claims + missing schema tests

Severity: P2
Related Feature: speed-dashboard-define

## Observed Behavior

Two issues in the spec alignment subsystem:

### 1. Filter crash on malformed claims (spec_alignment.py:93)

The `spec_file` filter at line 93 runs BEFORE the malformed-claim guards at line 101:

```python
# Line 92-96 — runs first, crashes on non-dict or null source
claims = [
    c for c in claims
    if c.get("source", {}).get("spec_file", "").endswith(spec_file)
]

# Line 101-103 — runs second, but too late
if not isinstance(claim, dict):
    logger.warning("Skipping malformed claim: not a dict")
    continue
```

If a claim is not a dict (e.g., a string or int), `c.get("source", {})` raises `AttributeError`. If `source` is `null`/`None`, `.get("spec_file", "")` raises `AttributeError`. The validation guards added by task 2 never execute because the crash happens in the filter above them.

### 2. Missing schema-level tests for specAlignment query

No integration test exists for the `specAlignment` GraphQL query. Task 3 acceptance criteria #5 (returns None when file absent) and #7 (returns populated SpecAlignmentView) both specify `verify_by: test` but no tests were delivered. The existing `test_schema_landing.py` covers the `landingView` query but not `specAlignment`.

## Expected Behavior

1. Malformed claims in the input JSON are skipped with a warning, never crash the resolver.
2. Schema integration tests cover: specAlignment returns None when file absent, returns full nested structure when populated, and spec_file filter narrows results.

## Affected Files

- `dashboard/backend/resolvers/spec_alignment.py` (move validation before the filter, or add guard in filter comprehension)
- `dashboard/backend/tests/test_schema_landing.py` (add specAlignment query tests)

## Reproduction Steps

1. Create a `spec-alignment.json` with a non-dict claim: `{"claims": ["not a dict"]}`
2. Call `get_spec_alignment(project_root, spec_file="foo.md")` — raises `AttributeError: 'str' object has no attribute 'get'`
3. `pytest dashboard/backend/tests/test_schema_landing.py -k specAlignment` — no tests match

## Acceptance Criteria

- `spec_file` filter handles non-dict claims without raising
- `spec_file` filter handles claims where `source` is None without raising
- Malformed claims logged as warnings, not exceptions
- Integration test: `specAlignment` returns None when `spec-alignment.json` absent
- Integration test: `specAlignment` returns full nested SpecAlignmentView when populated
- Integration test: `specAlignment(specFile: "foo.md")` filters results correctly
- `pytest dashboard/backend/tests/test_schema_landing.py` passes
- `pytest dashboard/backend/tests/test_spec_alignment.py` passes
