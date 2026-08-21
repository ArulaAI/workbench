<!--
Severity guide:
  P0 — System down or data loss. Blocks all users.
  P1 — Major feature broken. Workaround exists but painful.
  P2 — Feature partially broken. Minor impact or edge case.
  P3 — Cosmetic or minor inconvenience. No functional impact.

Related Feature must match a spec filename in specs/product/ without the .md extension.
For example, if the spec is specs/product/speed-defects.md, write: speed-defects
-->

# Defect: <title>

Severity: <P0 | P1 | P2 | P3>
Related Feature: <feature-name matching a spec in specs/product/>

## Observed Behavior

<What actually happens. Be specific: include error messages, wrong values, broken UI states.>

## Expected Behavior

<What should happen instead, per the spec or reasonable user expectation.>

## Reproduction Steps

<Numbered steps to trigger the bug. Include preconditions (user state, data setup).>

1. Step 1
2. Step 2
3. Bug manifests

## Additional Context (optional)

<Screenshots, log snippets, environment details, frequency of occurrence.>
