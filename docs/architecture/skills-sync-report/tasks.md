---
title: "Skills Sync Reporting: Tasks"
description: "Implementation tasks and verification log for skills sync reporting (WB-SYNC-REPORT)."
sidebar:
  order: 22
---

# Tasks: Skills Sync Run Reporting and Failure Logging

> Spec set: `requirements.md` -> `design.md` -> **`tasks.md`**
> Feature ID: `WB-SYNC-REPORT`
> Each task names the requirements it satisfies and the design section it
> implements. Execute in order; a task is done only when its tests pass.

- [x] 1. Extend the shared vocabulary
  - Add `FAILED` action and `reason`, `error_type`, `duration_ms` fields
    (with defaults) to `SyncOutcome` in `lib/skills/models.py`
  - Add `sync_log` to `SkillPaths` in `lib/skills/__init__.py`
  - _Requirements: REQ-1.1, REQ-2.1 · Design: 5, 4.3_

- [x] 2. Isolate failures in the sync engine (`lib/skills/sync.py`)
  - [x] 2.1 Wrap each skill's write/remove in `try/except Exception`; record
    `action="failed"`, the message and exception type; keep `final_state`
    as the pre-run state; do not touch the manifest record
    - _Requirements: REQ-5.1, REQ-5.3 · Design: 6.1, 6.3_
  - [x] 2.2 Before a harness's first write, create `<harness>/skills`; on
    failure mark every planned write in that harness `failed` with a
    harness-level reason
    - _Requirements: REQ-5.2 · Design: 6.1_
  - [x] 2.3 Attach a reason to preserved conflicts (finding codes) and to
    unsupported rows; time each operation in `duration_ms`
    - _Requirements: REQ-1.2 · Design: 5_

- [x] 3. Implement `SyncReporter` (`lib/skills/reporter.py`)
  - `SkillSyncResult`, `SyncRunReport`, `result_from_outcome`, status and
    exit-code rules, `abort()` for pre-flight errors
  - Unit tests: aggregation, empty catalog, every exit code, abort
  - _Requirements: REQ-1, REQ-3 · Design: 4.2, 5, 6.2_

- [x] 4. Implement `SyncLogWriter` (`lib/skills/log_writer.py`)
  - One JSON line per run, rotation at 5 MB keeping 3 files, `False` on
    write failure
  - Unit tests: append, rotation, unwritable path
  - _Requirements: REQ-2 · Design: 4.3_

- [x] 5. Wire the CLI
  - [x] 5.1 `lib/skills/__main__.py`: `--report text|json`, `--no-log`;
    feed outcomes into the reporter; print the report; write the log and
    warn on failure; return `reporter.exit_code()`
    - _Requirements: REQ-3, REQ-4, REQ-2.4, REQ-2.5 · Design: 4.1, 6.2_
  - [x] 5.2 Text mode: keep the `catalog <v> · N row(s)` header, show failed
    rows with their cause, append one summary line
    - _Requirements: REQ-1.3 · Design: 7.3_
  - [x] 5.3 `lib/cmd/skills.sh`: accept and forward `--report`/`--no-log`,
    document exit code 1
    - _Requirements: REQ-3, REQ-4 · Design: 4.1_

- [x] 6. Keep the per-machine log out of Git
  - Add `sync-log.jsonl*` to both managed ignore policies in
    `lib/skills/bootstrap.py`
  - _Requirements: REQ-6 · Design: 7.1, amendment A7_

- [x] 7. Integration tests (`tests/skills/test_sync_report.py`)
  - One skill's write raises -> exit 1, siblings `added`, manifest omits it,
    next sync retries and exits 0
  - Harness whose `skills` path is a regular file -> that harness `failed`,
    the other harness `added`
  - `--report json` validates against the data model; pre-flight error still
    emits a report with exit 3
  - Snapshot of every file outside sync targets is byte-identical after sync
  - `--no-log` writes no log; unwritable log warns and keeps the exit code
  - _Requirements: REQ-1 to REQ-6 · Design: 8_

- [x] 8. Verify
  - Full `tests/skills` suite shows no new failures against the baseline
  - Scenario run against a scratch repo with the real catalog: clean
    install, a forced failure, recovery
  - _Requirements: all · Design: 8_

---

## Verification log (2026-10-07)

| Check | Result |
|-------|--------|
| New tests (`test_reporter`, `test_log_writer`, `test_sync_report`) | 30 passed |
| Full `tests/skills` vs pre-change baseline | 324-325 passed; no new failures. The 57-59 failures are pre-existing Windows issues (symlink privileges, CRLF, no `fcntl`); the concurrency tests among them flip run to run |
| Updated tests | `test_failure_on_a_later_harness_keeps_earlier_writes_recorded`, `test_a_failed_write_leaves_the_previous_projection_intact` now assert a `failed` outcome instead of a raised exception (ADR-0002) |
| Scenario: broken codex harness | exit 1, claude `added`, codex `failed` (harness-level) |
| Scenario: harness fixed, `--report json` | exit 0, codex `added`, claude `unchanged` |
| Scenario: hand-edited projection | exit 2, claude `skipped` with finding codes |
| `sync-log.jsonl` | one line per run, three runs recorded |
