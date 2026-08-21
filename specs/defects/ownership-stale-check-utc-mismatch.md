# Defect: Ownership stale-check parses UTC timestamps as local time

Severity: P1
Related Feature: multiplayer
Tags: ownership, timestamp, timezone

## Observed Behavior

`ownership_check()` in `lib/ownership.sh` (line 66) parses claim event timestamps using `date -j -f "%Y-%m-%dT%H:%M:%SZ"`, which interprets the input as local time. But `event_emit()` in `lib/events.sh` (line 36) writes timestamps using `date -u`, producing UTC values like `2026-04-01T10:55:42Z`.

The mismatch means the staleness calculation is off by the machine's UTC offset. On a machine at UTC-5:30 (e.g., US Pacific), a claim made 10 seconds ago looks 5 hours and 30 minutes old. With the default 3600-second stale window, any claim appears stale immediately on machines west of UTC+01:00.

When a claim is stale, `ownership_check` returns 2 (unclaimed). A second actor can then claim the same feature without the first actor releasing it. The identity feature (email-based disambiguation) works correctly, but the staleness check defeats it before the comparison ever runs.

## Expected Behavior

A claim made N seconds ago should have an age of approximately N seconds, regardless of the machine's timezone. The staleness check should compare apples to apples: both `now` and `claim_epoch` in the same timezone.

## Impact

Ownership is silently broken for any developer whose local timezone is more than 1 hour behind UTC (most of the Americas, parts of Asia). Two developers can hold the same feature simultaneously, which is the exact scenario multiplayer mode exists to prevent. The default stale window of 3600 seconds (1 hour) means only UTC+00:00 and UTC+01:00 timezones are unaffected.

## Reproduction Steps

1. Set local timezone to anything west of UTC+01:00 (e.g., US Pacific, UTC-7)
2. `speed claim my-feature` as Actor A
3. Immediately `speed claim my-feature` as Actor B (different email, same name)
4. Actor B succeeds instead of being rejected

## Suggested Fix

Add `-u` to the `date -j` call in `ownership_check` so it parses the timestamp as UTC, matching how it was written:

```bash
# Before (line 66)
claim_epoch=$(date -j -f "%Y-%m-%dT%H:%M:%SZ" "$latest_claim_ts" +%s 2>/dev/null || \
              date -d "$latest_claim_ts" +%s 2>/dev/null || echo "0")

# After
claim_epoch=$(date -j -u -f "%Y-%m-%dT%H:%M:%SZ" "$latest_claim_ts" +%s 2>/dev/null || \
              date -u -d "$latest_claim_ts" +%s 2>/dev/null || echo "0")
```

The same fix applies to every `date -j -f "%Y-%m-%dT%H:%M:%SZ"` call that parses event or roster timestamps: `ownership.sh:66`, `roster.sh:65`, `roster.sh:94`.

## Scope

The `event_prune` function in `events.sh` has a similar pattern but was recently fixed to normalize timestamps before parsing. It should also get the `-u` flag.
