#!/usr/bin/env python3
"""Tests for Steps 11-14: Human correction extraction.

Tests the four extraction-time human signal steps in human_corrections.py
against synthetic fixtures matching real pipeline artifact schemas.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "lib"))

from lib.learn.human_corrections import (
    step11_retry_guidance,
    step12_skip_flags,
    step13_forced_approvals,
    step14_defect_rejections,
)

passed = 0
failed = 0


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name} — {detail}")


# ── Step 11: Retry guidance ─────────────────────────────────────────


def test_step11_single_attempt():
    """Single retry with human guidance produces 1 observation."""
    tasks = [{
        "id": "3",
        "status": "done",
        "review_feedback": (
            "--- Attempt 2 ---\n"
            "Failed with: timeout\n"
            "Human guidance: The auth handler needs to validate tokens first"
        ),
    }]
    obs = step11_retry_guidance(tasks, "test-feature")
    check("step11: single attempt count", len(obs) == 1, f"got {len(obs)}")
    if obs:
        check("step11: change_type", obs[0].detail["change_type"] == "guidance")
        check("step11: task_id", obs[0].task_id == "3")
        check("step11: weight", obs[0].weight == 2.5, f"got {obs[0].weight}")
        check("step11: task_succeeded", obs[0].detail["task_succeeded"] is True)
        check("step11: guidance_text",
              "validate tokens" in obs[0].detail["guidance_text"])
        check("step11: observation_type",
              obs[0].observation_type == "human_override")


def test_step11_multiple_attempts():
    """Task with 3 attempts, 2 with guidance, produces 2 observations."""
    tasks = [{
        "id": "5",
        "status": "done",
        "review_feedback": (
            "--- Attempt 1 ---\n"
            "Failed with: syntax error\n"
            "Human guidance: Check the import order\n"
            "--- Attempt 2 ---\n"
            "Failed with: type error\n"
            "Human guidance: Use Optional[str] not str\n"
            "--- Attempt 3 ---\n"
            "Failed with: test failure\n"
            "Human guidance: "
        ),
    }]
    obs = step11_retry_guidance(tasks, "test-feature")
    # Third attempt has empty guidance, should be skipped
    check("step11: multiple attempts count", len(obs) == 2, f"got {len(obs)}")
    if len(obs) >= 2:
        check("step11: attempt numbers",
              obs[0].detail["attempt"] == 1 and obs[1].detail["attempt"] == 2)


def test_step11_no_guidance_marker():
    """Task with reviewer feedback but no Human guidance markers."""
    tasks = [{
        "id": "1",
        "status": "done",
        "review_feedback": "Reviewer says: fix the indentation",
    }]
    obs = step11_retry_guidance(tasks, "test-feature")
    check("step11: no markers produces 0", len(obs) == 0, f"got {len(obs)}")


def test_step11_task_failed():
    """Guidance from a failed task records task_succeeded=false."""
    tasks = [{
        "id": "7",
        "status": "failed",
        "review_feedback": (
            "--- Attempt 1 ---\n"
            "Failed with: crash\n"
            "Human guidance: Try using the async variant"
        ),
    }]
    obs = step11_retry_guidance(tasks, "test-feature")
    check("step11: failed task count", len(obs) == 1, f"got {len(obs)}")
    if obs:
        check("step11: task_succeeded false",
              obs[0].detail["task_succeeded"] is False)


# ── Step 12: Skip flags ─────────────────────────────────────────────


def test_step12_single_skip():
    """Single skip entry produces 1 observation."""
    with tempfile.TemporaryDirectory() as tmp:
        feature_dir = Path(tmp)
        logs_dir = feature_dir / "logs"
        logs_dir.mkdir()
        skip_file = logs_dir / "skipped-gates.json"
        skip_file.write_text(
            '{"gate":"guardian_pre_plan","stage":"plan",'
            '"timestamp":"2026-03-10T10:00:00Z"}\n'
        )
        obs = step12_skip_flags(feature_dir, "test-feature")
        check("step12: single skip count", len(obs) == 1, f"got {len(obs)}")
        if obs:
            check("step12: change_type", obs[0].detail["change_type"] == "skip")
            check("step12: gate_name",
                  obs[0].detail["gate_name"] == "guardian_pre_plan")
            check("step12: weight", obs[0].weight == 0.5, f"got {obs[0].weight}")


def test_step12_multiple_skips():
    """3 skip entries produce 3 observations."""
    with tempfile.TemporaryDirectory() as tmp:
        feature_dir = Path(tmp)
        logs_dir = feature_dir / "logs"
        logs_dir.mkdir()
        entries = [
            '{"gate":"guardian_pre_plan","stage":"plan","timestamp":"2026-03-10T10:00:00Z"}',
            '{"gate":"gates","stage":"run","timestamp":"2026-03-10T10:01:00Z"}',
            '{"gate":"audit","stage":"plan","timestamp":"2026-03-10T10:02:00Z"}',
        ]
        (logs_dir / "skipped-gates.json").write_text("\n".join(entries) + "\n")
        obs = step12_skip_flags(feature_dir, "test-feature")
        check("step12: multiple skips count", len(obs) == 3, f"got {len(obs)}")


def test_step12_no_file():
    """Missing skipped-gates.json produces 0 observations."""
    with tempfile.TemporaryDirectory() as tmp:
        feature_dir = Path(tmp)
        (feature_dir / "logs").mkdir()
        obs = step12_skip_flags(feature_dir, "test-feature")
        check("step12: no file produces 0", len(obs) == 0, f"got {len(obs)}")


# ── Step 13: Forced approvals ───────────────────────────────────────


def test_step13_no_review_log():
    """Task approved with no review log = forced approval."""
    with tempfile.TemporaryDirectory() as tmp:
        logs_dir = Path(tmp)
        tasks = [{"id": "2", "review_verdict": "approve", "status": "done"}]
        obs = step13_forced_approvals(tasks, "test-feature", logs_dir)
        check("step13: no review log count", len(obs) == 1, f"got {len(obs)}")
        if obs:
            check("step13: change_type",
                  obs[0].detail["change_type"] == "forced_approval")
            check("step13: reviewer_verdict",
                  obs[0].detail["reviewer_verdict"] == "no_review")
            check("step13: weight", obs[0].weight == 2.0, f"got {obs[0].weight}")


def test_step13_reviewer_rejected():
    """Reviewer said request_changes but verdict is approve = forced."""
    with tempfile.TemporaryDirectory() as tmp:
        logs_dir = Path(tmp)
        review_data = {
            "verdict": "request_changes",
            "issues": [
                {"description": "Missing error handling", "severity": "major"},
                {"description": "No tests", "severity": "major"},
            ],
        }
        (logs_dir / "review-4.json").write_text(json.dumps(review_data))
        tasks = [{"id": "4", "review_verdict": "approve", "status": "done"}]
        obs = step13_forced_approvals(tasks, "test-feature", logs_dir)
        check("step13: reviewer rejected count", len(obs) == 1,
              f"got {len(obs)}")
        if obs:
            check("step13: reviewer_verdict is request_changes",
                  obs[0].detail["reviewer_verdict"] == "request_changes")
            check("step13: findings captured",
                  len(obs[0].detail["reviewer_findings"]) == 2)


def test_step13_normal_approval():
    """Reviewer approved and verdict is approve = not forced."""
    with tempfile.TemporaryDirectory() as tmp:
        logs_dir = Path(tmp)
        review_data = {"verdict": "approve", "issues": []}
        (logs_dir / "review-1.json").write_text(json.dumps(review_data))
        tasks = [{"id": "1", "review_verdict": "approve", "status": "done"}]
        obs = step13_forced_approvals(tasks, "test-feature", logs_dir)
        check("step13: normal approval produces 0", len(obs) == 0,
              f"got {len(obs)}")


# ── Step 14: Defect rejections ──────────────────────────────────────


def test_step14_rejected_with_triage():
    """Rejected defect with triage produces 1 observation."""
    with tempfile.TemporaryDirectory() as tmp:
        defects_dir = Path(tmp)
        defect = defects_dir / "auth-timeout-race"
        defect.mkdir()
        (defect / "state.json").write_text(json.dumps({
            "status": "rejected",
            "defect_type": "regression",
        }))
        (defect / "triage.json").write_text(json.dumps({
            "defect_type": "regression",
            "complexity": "moderate",
            "summary": "Race condition in auth token refresh",
        }))
        obs = step14_defect_rejections(defects_dir, "test-feature")
        check("step14: rejected with triage count", len(obs) == 1,
              f"got {len(obs)}")
        if obs:
            check("step14: change_type",
                  obs[0].detail["change_type"] == "defect_rejection")
            check("step14: defect_name",
                  obs[0].detail["defect_name"] == "auth-timeout-race")
            check("step14: complexity",
                  obs[0].detail["complexity"] == "moderate")
            check("step14: weight", obs[0].weight == 1.5, f"got {obs[0].weight}")
            check("step14: agent_attribution",
                  obs[0].detail["agent_attribution"] == ["debugger"])


def test_step14_non_rejected():
    """Defect with status=resolved produces 0 observations."""
    with tempfile.TemporaryDirectory() as tmp:
        defects_dir = Path(tmp)
        defect = defects_dir / "some-bug"
        defect.mkdir()
        (defect / "state.json").write_text(json.dumps({
            "status": "resolved",
        }))
        obs = step14_defect_rejections(defects_dir, "test-feature")
        check("step14: non-rejected produces 0", len(obs) == 0,
              f"got {len(obs)}")


def test_step14_no_triage():
    """Rejected defect without triage.json still produces observation."""
    with tempfile.TemporaryDirectory() as tmp:
        defects_dir = Path(tmp)
        defect = defects_dir / "null-ptr"
        defect.mkdir()
        (defect / "state.json").write_text(json.dumps({
            "status": "rejected",
            "defect_type": "false_positive",
            "complexity": "low",
        }))
        obs = step14_defect_rejections(defects_dir, "test-feature")
        check("step14: no triage count", len(obs) == 1, f"got {len(obs)}")
        if obs:
            check("step14: falls back to state fields",
                  obs[0].detail["defect_type"] == "false_positive")
            check("step14: triage_summary empty",
                  obs[0].detail["triage_summary"] == "")


# ── Idempotency ─────────────────────────────────────────────────────


def test_idempotency():
    """Running the same extraction twice produces identical observation IDs."""
    tasks = [{
        "id": "3",
        "status": "done",
        "review_feedback": (
            "--- Attempt 1 ---\n"
            "Failed with: error\n"
            "Human guidance: Fix the import"
        ),
    }]
    obs1 = step11_retry_guidance(tasks, "test-feature")
    obs2 = step11_retry_guidance(tasks, "test-feature")
    check("idempotency: same IDs",
          len(obs1) == 1 and len(obs2) == 1 and obs1[0].id == obs2[0].id,
          f"ids: {[o.id for o in obs1]} vs {[o.id for o in obs2]}")


# ── Main ────────────────────────────────────────────────────────────


def main():
    print("\nStep 11: Retry guidance")
    print("-" * 40)
    test_step11_single_attempt()
    test_step11_multiple_attempts()
    test_step11_no_guidance_marker()
    test_step11_task_failed()

    print("\nStep 12: Skip flags")
    print("-" * 40)
    test_step12_single_skip()
    test_step12_multiple_skips()
    test_step12_no_file()

    print("\nStep 13: Forced approvals")
    print("-" * 40)
    test_step13_no_review_log()
    test_step13_reviewer_rejected()
    test_step13_normal_approval()

    print("\nStep 14: Defect rejections")
    print("-" * 40)
    test_step14_rejected_with_triage()
    test_step14_non_rejected()
    test_step14_no_triage()

    print("\nIdempotency")
    print("-" * 40)
    test_idempotency()

    print(f"\n{'=' * 40}")
    print(f"{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
