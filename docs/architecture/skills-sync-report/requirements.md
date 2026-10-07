---
title: "Skills Sync Reporting: Requirements"
description: "Requirements and EARS acceptance criteria for skills sync run reporting (WB-SYNC-REPORT)."
sidebar:
  order: 20
---

# Requirements: Skills Sync Run Reporting and Failure Logging

> Spec set: **`requirements.md`** -> `design.md` -> `tasks.md`
> Feature ID: `WB-SYNC-REPORT`
> Format: Kiro spec-driven development. Acceptance criteria use EARS notation
> (`WHEN <trigger> THEN the system SHALL <response>`).

## Introduction

`workbench skills sync` projects the canonical skill catalog into each agent
harness. A sync that fails today stops at the first exception and leaves the
operator with a traceback and no record of which skills landed. These
requirements describe the per-run report, the persistent failure log, and the
exit codes that let a human, a CI job, or an agent tell what happened.

Requirement IDs (`REQ-n`) are referenced from `design.md` section 2 and from
every task in `tasks.md`.

---

### REQ-1: Per-skill outcome

**User story:** As a developer running sync, I want every skill's outcome
reported individually, so that I know exactly which skills changed.

#### Acceptance criteria

1. WHEN a sync run completes THEN the system SHALL report one result per
   (harness, skill) pair with an outcome from the closed set `added`,
   `updated`, `removed`, `unchanged`, `skipped`, `failed`.
2. WHEN a skill's outcome is `skipped` or `failed` THEN the result SHALL carry
   a non-empty `reason`.
3. WHEN a sync run completes THEN the report SHALL include a `summary` with a
   count for every outcome, including outcomes with a count of zero.
4. WHEN the catalog is empty THEN the system SHALL produce a valid report with
   zero results and status `success`.

### REQ-2: Failure logging

**User story:** As a maintainer debugging a bad sync, I want failures written
to a durable log with their cause, so that I can reproduce them after the
terminal is gone.

#### Acceptance criteria

1. WHEN a sync run finishes (successfully, partially, or by aborting) THEN the
   system SHALL append exactly one JSON line describing the run to
   `.speed/skills/sync-log.jsonl`.
2. WHEN a skill fails THEN its log entry SHALL include the exception type, the
   message, the harness, and the skill id.
3. WHEN the log file exceeds 5 MB THEN the system SHALL rotate it and retain
   at most 3 files.
4. IF the log cannot be written THEN the system SHALL print a warning on
   stderr AND SHALL NOT change the exit code.
5. WHEN `--no-log` is passed THEN the system SHALL NOT write the log.

### REQ-3: Exit codes

**User story:** As a CI pipeline, I want the exit code to describe the run, so
that I can gate on it without parsing text.

#### Acceptance criteria

1. WHEN every skill converged THEN the system SHALL exit 0.
2. WHEN at least one skill failed THEN the system SHALL exit 1.
3. WHEN no skill failed but local edits were preserved as conflicts THEN the
   system SHALL exit 2 (existing contract, unchanged).
4. WHEN a pre-flight check fails before any projection is written THEN the
   system SHALL exit 3 (existing contract, unchanged).

### REQ-4: Machine-readable report

**User story:** As a CI pipeline, I want the report as JSON on stdout, so that
I can archive it or post it to a PR.

#### Acceptance criteria

1. WHEN `--report json` is passed THEN stdout SHALL contain only the
   `SyncRunReport` JSON object.
2. WHEN `--report json` is passed and pre-flight fails THEN stdout SHALL still
   contain a `SyncRunReport` with status `failed` and an `error` object.
3. WHEN `--json` (legacy) is passed THEN the system SHALL keep emitting the
   existing per-row array so current consumers keep working.

### REQ-5: Failure isolation

**User story:** As a developer with several harnesses, I want one broken
harness or skill not to block the rest, so that a single bad path does not
leave every harness stale.

#### Acceptance criteria

1. WHEN one skill fails to project THEN the system SHALL continue with the
   remaining skills and harnesses.
2. WHEN a harness's skills directory cannot be created THEN the system SHALL
   mark every planned write in that harness `failed` AND continue with other
   harnesses.
3. WHEN a skill fails THEN the manifest SHALL NOT record it as current, so the
   next sync retries it.

### REQ-6: Write boundary

**User story:** As a repository owner, I want sync to touch only its own
files, so that it can never damage unrelated work.

#### Acceptance criteria

1. WHEN sync runs THEN the system SHALL write only under `<harness>/skills/`
   and `.speed/skills/` (manifest, event log, sync lock, sync log).
2. WHEN sync runs THEN every file outside those paths SHALL be byte-identical
   before and after the run.
