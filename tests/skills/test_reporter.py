"""SyncReporter: aggregation, status, and exit codes (WB-SYNC-REPORT REQ-1, REQ-3)."""
import pytest

from skills.models import (
    CONFLICT,
    FAILED,
    INSTALLED,
    REMOVED,
    UPDATED,
    SkillState,
    SyncOutcome,
)
from skills.reporter import OUTCOMES, SyncReporter, result_from_outcome


def _outcome(action="", final=SkillState.CURRENT, prev=SkillState.CURRENT, **kw):
    return SyncOutcome(
        harness=kw.pop("harness", "claude"),
        skill=kw.pop("skill", "s"),
        previous_state=prev,
        action=action,
        final_state=final,
        **kw,
    )


def _reporter(*outcomes):
    reporter = SyncReporter()
    reporter.start_run("run-1", "dev")
    for outcome in outcomes:
        reporter.record(result_from_outcome(outcome))
    return reporter


@pytest.mark.parametrize(
    "outcome, expected",
    [
        (_outcome(INSTALLED, prev=SkillState.ABSENT), "added"),
        (_outcome(UPDATED, prev=SkillState.STALE), "updated"),
        (_outcome(REMOVED, final=SkillState.ABSENT), "removed"),
        (_outcome(CONFLICT, final=SkillState.CONFLICTED, reason="kept"), "skipped"),
        (_outcome("", final=SkillState.UNSUPPORTED), "skipped"),
        (_outcome(""), "unchanged"),
        (_outcome(FAILED, final=SkillState.STALE, reason="boom", error_type="OSError"), "failed"),
    ],
)
def test_every_engine_action_maps_to_one_report_outcome(outcome, expected):
    assert result_from_outcome(outcome).outcome == expected


def test_skipped_and_failed_always_carry_a_reason():
    result = result_from_outcome(_outcome("", final=SkillState.UNSUPPORTED))
    assert result.reason


def test_unknown_action_is_refused():
    with pytest.raises(ValueError):
        result_from_outcome(_outcome("teleported"))


def test_empty_catalog_is_a_valid_successful_report():
    report = _reporter().finish_run()
    assert report.results == []
    assert report.summary == dict.fromkeys(OUTCOMES, 0)
    assert report.status == "success"
    assert report.exit_code == 0


def test_summary_counts_every_outcome_including_zeroes():
    report = _reporter(
        _outcome(INSTALLED, prev=SkillState.ABSENT, skill="a"),
        _outcome(INSTALLED, prev=SkillState.ABSENT, skill="b"),
        _outcome("", skill="c"),
    ).finish_run()
    assert report.summary == {
        "added": 2, "updated": 0, "removed": 0,
        "unchanged": 1, "skipped": 0, "failed": 0,
    }


def test_exit_codes():
    assert _reporter(_outcome("")).exit_code() == 0
    conflict = _outcome(CONFLICT, final=SkillState.CONFLICTED, reason="kept")
    assert _reporter(conflict).exit_code() == 2
    failed = _outcome(FAILED, final=SkillState.ABSENT, reason="x", error_type="OSError")
    assert _reporter(failed, _outcome("")).exit_code() == 1
    # failure outranks a preserved conflict
    assert _reporter(failed, conflict).exit_code() == 1


def test_unsupported_harness_is_skipped_but_exits_zero():
    reporter = _reporter(_outcome("", final=SkillState.UNSUPPORTED))
    assert reporter.exit_code() == 0
    assert reporter.status() == "success"


def test_status_partial_versus_failed():
    failed = _outcome(FAILED, final=SkillState.ABSENT, reason="x", error_type="OSError")
    assert _reporter(failed, _outcome("", skill="b")).status() == "partial"
    assert _reporter(failed).status() == "failed"


def test_abort_is_a_failed_run_with_exit_three():
    reporter = SyncReporter()
    reporter.start_run("run-2", "dev", harnesses=["claude"])
    reporter.abort("ValueError", "catalog unreadable")
    report = reporter.finish_run()
    assert report.status == "failed"
    assert report.exit_code == 3
    assert report.error == {"type": "ValueError", "message": "catalog unreadable"}
    assert report.harnesses == ["claude"]
