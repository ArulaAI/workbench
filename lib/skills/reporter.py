"""Aggregate one sync run's outcomes into a ``SyncRunReport``.

Pure, in-memory, no I/O: the CLI feeds it ``SyncOutcome`` rows as the engine
returns them and asks it for the report and the exit code. ``SyncLogWriter``
persists the report; this module only decides what it says.

The report speaks a smaller, user-facing vocabulary than the engine. The engine
knows *why* it acted (``installed`` because the skill was ``absent``); a CI job
wants to know *what happened* (``added``). ``result_from_outcome`` is the one
place that translation lives.

Exit codes extend the engine's existing contract rather than replacing it:

  0  every skill converged
  1  at least one skill failed (new; outranks 2)
  2  no failures, but local edits were preserved as conflicts
  3  the run aborted before projecting anything
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from skills.models import (
    CONFLICT,
    FAILED,
    INSTALLED,
    REMOVED,
    UPDATED,
    SkillState,
)

OUTCOMES = ("added", "updated", "removed", "unchanged", "skipped", "failed")

_OUTCOME_FOR_ACTION = {
    INSTALLED: "added",
    UPDATED: "updated",
    REMOVED: "removed",
    CONFLICT: "skipped",
    FAILED: "failed",
}

EXIT_OK = 0
EXIT_PARTIAL = 1
EXIT_CONFLICTS = 2
EXIT_ABORTED = 3


@dataclass
class SkillSyncResult:
    skill_id: str
    harness: str
    outcome: str
    reason: str | None
    error_type: str | None
    duration_ms: int
    final_state: str


@dataclass
class SyncRunReport:
    run_id: str
    started_at: str
    finished_at: str
    catalog_version: str
    harnesses: list
    results: list
    summary: dict
    status: str
    exit_code: int
    error: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def result_from_outcome(outcome) -> SkillSyncResult:
    """Translate one engine ``SyncOutcome`` into a report row."""
    if outcome.action:
        kind = _OUTCOME_FOR_ACTION.get(outcome.action)
        if kind is None:
            raise ValueError(f"unknown sync action '{outcome.action}'")
    elif outcome.final_state is SkillState.UNSUPPORTED:
        kind = "skipped"
    else:
        kind = "unchanged"
    reason = outcome.reason
    if kind in ("skipped", "failed") and not reason:
        reason = str(outcome.final_state)
    return SkillSyncResult(
        skill_id=outcome.skill,
        harness=outcome.harness,
        outcome=kind,
        reason=reason,
        error_type=outcome.error_type,
        duration_ms=outcome.duration_ms,
        final_state=str(outcome.final_state),
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SyncReporter:
    run_id: str = ""
    catalog_version: str = ""
    started_at: str = ""
    requested_harnesses: tuple = ()
    results: list = field(default_factory=list)
    error: dict | None = None

    def start_run(self, run_id: str, catalog_version: str, harnesses=()) -> None:
        self.run_id = run_id
        self.catalog_version = catalog_version
        self.started_at = _now()
        self.requested_harnesses = tuple(harnesses or ())
        self.results = []
        self.error = None

    def record(self, result: SkillSyncResult) -> None:
        if result.outcome not in OUTCOMES:
            raise ValueError(f"unknown outcome '{result.outcome}'")
        self.results.append(result)

    def abort(self, error_type: str, message: str) -> None:
        """The run stopped before projecting anything (pre-flight failure)."""
        self.error = {"type": error_type, "message": message}

    def summary(self) -> dict:
        counts = dict.fromkeys(OUTCOMES, 0)
        for result in self.results:
            counts[result.outcome] += 1
        return counts

    def status(self) -> str:
        failed = sum(1 for r in self.results if r.outcome == "failed")
        if self.error is not None or (self.results and failed == len(self.results)):
            return "failed"
        return "partial" if failed else "success"

    def exit_code(self) -> int:
        if self.error is not None:
            return EXIT_ABORTED
        if any(r.outcome == "failed" for r in self.results):
            return EXIT_PARTIAL
        if any(r.final_state == SkillState.CONFLICTED.value for r in self.results):
            return EXIT_CONFLICTS
        return EXIT_OK

    def _harnesses(self) -> list:
        seen = list(dict.fromkeys(r.harness for r in self.results))
        return seen or list(self.requested_harnesses)

    def finish_run(self) -> SyncRunReport:
        return SyncRunReport(
            run_id=self.run_id,
            started_at=self.started_at,
            finished_at=_now(),
            catalog_version=self.catalog_version,
            harnesses=self._harnesses(),
            results=list(self.results),
            summary=self.summary(),
            status=self.status(),
            exit_code=self.exit_code(),
            error=self.error,
        )
