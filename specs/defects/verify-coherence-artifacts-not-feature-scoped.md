# Defect: Verify and coherence reports write to global logs, not feature-scoped directory

Severity: P3
Related Feature: core pipeline

## Observed Behavior

`speed verify` writes to `.speed/logs/plan-verification.log` and `speed coherence` writes to `.speed/logs/coherence.log`. Both are global paths under `LOGS_DIR`. Each invocation overwrites the previous report.

`speed security` writes to `.speed/features/<name>/logs/security-audit.json`, scoped to the active feature.

All three commands are feature-wide operations that produce per-feature results. Verify and coherence break the pattern without an architectural reason.

## Expected Behavior

Verify and coherence reports should write to the feature-scoped directory alongside other feature artifacts:

- `.speed/features/<name>/logs/plan-verification.log`
- `.speed/features/<name>/logs/coherence.log`

This would make all feature artifacts discoverable under one path, prevent overwrite-on-rerun data loss, and allow the observation extraction pipeline (`speed learn`) to find artifacts reliably after integration.

## Impact

1. Running `speed verify` or `speed coherence` for a second feature overwrites the first feature's reports. If `speed learn` hasn't extracted observations yet, the data is lost.
2. The observation extraction pipeline needs special-case logic to read from two different locations (global logs vs. feature-scoped logs) depending on the artifact type.
3. There is no way to inspect historical verify or coherence reports after the fact.

## Affected Code

- `lib/cmd/verify.sh:340` — writes to `${LOGS_DIR}/plan-verification.log`
- `lib/cmd/verify.sh:555` — second write path, same global location
- `lib/cmd/coherence.sh:196` — writes to `${LOGS_DIR}/coherence.log`
- `lib/cmd/coherence.sh:80-81` — copies previous report to `coherence-prev.json` (workaround for the overwrite problem)
- `lib/cmd/security.sh:39` — correct pattern, writes to feature-scoped `${logs_dir}/security-audit.json`

## Proposed Fix

1. Change verify to write to `${FEATURE_LOGS_DIR}/plan-verification.log` (where `FEATURE_LOGS_DIR` is `.speed/features/<name>/logs/`)
2. Change coherence to write to `${FEATURE_LOGS_DIR}/coherence.log`
3. Remove the `coherence-prev.json` copy workaround (previous reports are preserved naturally when feature-scoped)
4. Update any readers of these files to use the new paths
