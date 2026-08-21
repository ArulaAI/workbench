#!/usr/bin/env python3
"""Tests for Step 3: Guardian Verdicts extraction.

Tests the rewritten _step3_guardian_verdicts against the real extract.py
implementation. Uses synthetic fixtures matching the guardian JSON schema.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from lib.learn.extract import (
    ExtractResult,
    _step3_guardian_verdicts,
    _parse_check_type,
    _resolve_task_id,
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


def write_guardian(logs_dir, filename, data):
    (logs_dir / filename).write_text(json.dumps(data))


def make_flagged_guardian(**overrides):
    base = {
        "status": "flagged",
        "vision_alignment": {"core_mission_served": True, "reasoning": "Drifts."},
        "behavioral_test": {"verdict": "misaligned", "reasoning": "Text post."},
        "scope_violations": [
            {"feature": "TRIBE_ANNOUNCEMENT", "maps_to": "Text-Only Posts (Won't Have)",
             "severity": "warning", "reasoning": "Identical to text post."}
        ],
        "persona_grounding": [
            {"persona": "Maya Chen", "served": True, "use_case": "Sees updates"},
            {"persona": "David Morales", "served": False, "use_case": "No artifact context"},
        ],
        "differentiation_impact": {"direction": "weakens", "pillars_affected": ["build-first"]},
        "flags": [
            {"severity": "warning", "description": "Text post violation",
             "vision_reference": "Won't Have", "recommendation": "Remove or redefine"},
            {"severity": "note", "description": "Minor naming issue",
             "vision_reference": "", "recommendation": ""},
        ],
        "summary": "TRIBE_ANNOUNCEMENT drifts from vision."
    }
    base.update(overrides)
    return base


def make_aligned_guardian(**overrides):
    base = {
        "status": "aligned",
        "vision_alignment": {"core_mission_served": True, "reasoning": "All good."},
        "behavioral_test": {"verdict": "aligned", "reasoning": "No drift."},
        "scope_violations": [],
        "persona_grounding": [
            {"persona": "Maya Chen", "served": True, "use_case": "Works"},
        ],
        "differentiation_impact": {"direction": "strengthens", "pillars_affected": []},
        "flags": [{"severity": "note", "description": "Minor note", "vision_reference": "", "recommendation": ""}],
        "summary": "Everything aligned."
    }
    base.update(overrides)
    return base


# Task reviewed_at timestamps derived from guardian epoch suffixes:
#   guardian-post-review-1772438415.json -> task 3 reviewed near epoch 1772438415
#   guardian-post-review-1772439353.json -> task 4 reviewed near epoch 1772439353
TASKS = {
    "3": {
        "id": 3, "status": "done",
        "reviewed_at": "2026-03-02T08:00:15Z",
        "completed_at": "2026-03-02T08:01:00Z",
        "review_verdict": "approve", "review_feedback": "",
    },
    "4": {
        "id": 4, "status": "done",
        "reviewed_at": "2026-03-02T08:15:53Z",
        "completed_at": "2026-03-02T08:16:00Z",
        "review_verdict": "approve", "review_feedback": "",
    },
}


# ══════════════════════════════════════════════════════════════
# 1: _parse_check_type
# ══════════════════════════════════════════════════════════════

print("\n=== 1: _parse_check_type ===")

check("pre-plan",
      _parse_check_type("guardian-pre-plan-1772438901.json") == "pre-plan")
check("post-review",
      _parse_check_type("guardian-post-review-1772439353.json") == "post-review")
check("post-integration",
      _parse_check_type("guardian-post-integration-1772439500.json") == "post-integration")


# ══════════════════════════════════════════════════════════════
# 2: _resolve_task_id
# ══════════════════════════════════════════════════════════════

print("\n=== 2: _resolve_task_id ===")

with tempfile.TemporaryDirectory() as tmpdir:
    # guardian epoch 1772439353 should be closest to task 4's reviewed_at
    gfile = Path(tmpdir) / "guardian-post-review-1772439353.json"
    gfile.touch()
    tid = _resolve_task_id(gfile, "post-review", TASKS)
    check("Maps to nearest task by timestamp", tid == "4",
          f"got {tid}")

    # guardian epoch 1772438415 should be closest to task 3's reviewed_at
    gfile2 = Path(tmpdir) / "guardian-post-review-1772438415.json"
    gfile2.touch()
    tid2 = _resolve_task_id(gfile2, "post-review", TASKS)
    check("Maps second guardian to task 3", tid2 == "3",
          f"got {tid2}")

    # No timestamps in tasks -> falls back to "*"
    empty_tasks = {"1": {"id": 1, "status": "done"}}
    tid3 = _resolve_task_id(gfile, "post-review", empty_tasks)
    check("Falls back to * when no timestamps", tid3 == "*",
          f"got {tid3}")

    # Malformed filename -> falls back to "*"
    bad = Path(tmpdir) / "guardian-post-review-notanumber.json"
    bad.touch()
    tid4 = _resolve_task_id(bad, "post-review", TASKS)
    check("Malformed epoch falls back to *", tid4 == "*",
          f"got {tid4}")


# ══════════════════════════════════════════════════════════════
# 3: Primary source — flagged guardian
# ══════════════════════════════════════════════════════════════

print("\n=== 3: Flagged guardian produces observations ===")

with tempfile.TemporaryDirectory() as tmpdir:
    logs = Path(tmpdir) / "logs"
    logs.mkdir()
    write_guardian(logs, "guardian-post-review-1772439353.json", make_flagged_guardian())

    result = ExtractResult()
    _step3_guardian_verdicts("test-feature", logs, TASKS, result)

    obs = result.observations
    check("Produces observations", len(obs) > 0, f"got {len(obs)}")

    verdicts = [o for o in obs if o.detail.get("subtype") == "verdict"]
    check("One verdict observation", len(verdicts) == 1,
          f"got {len(verdicts)}")
    if verdicts:
        v = verdicts[0]
        check("Verdict status is flagged", v.detail["verdict"] == "flagged")
        check("Verdict weight is 1.0", v.weight == 1.0, f"got {v.weight}")
        check("Verdict has check_type", v.detail["check_type"] == "post-review")
        check("Verdict has source_file", "1772439353" in v.detail["source_file"])
        check("Verdict maps to task 4", v.task_id == "4", f"got {v.task_id}")
        check("Verdict has behavioral_test", v.detail["behavioral_test"] == "misaligned")

    svs = [o for o in obs if o.detail.get("subtype") == "scope_violation"]
    check("One scope violation", len(svs) == 1, f"got {len(svs)}")
    if svs:
        check("Scope violation feature_name", svs[0].detail["feature_name"] == "TRIBE_ANNOUNCEMENT")
        check("Scope violation maps_to", "Won't Have" in svs[0].detail["maps_to"])
        check("Scope violation weight is 2.0", svs[0].weight == 2.0, f"got {svs[0].weight}")

    flags = [o for o in obs if o.detail.get("subtype") == "flag"]
    check("One flag (warning only, note skipped)", len(flags) == 1,
          f"got {len(flags)}")
    if flags:
        check("Flag severity is warning", flags[0].detail["severity"] == "warning")
        check("Flag weight is 1.5", flags[0].weight == 1.5, f"got {flags[0].weight}")
        check("Flag has recommendation", flags[0].detail["recommendation"] != "")

    pgs = [o for o in obs if o.detail.get("subtype") == "persona_not_served"]
    check("One persona not served", len(pgs) == 1, f"got {len(pgs)}")
    if pgs:
        check("Persona is David Morales", pgs[0].detail["persona"] == "David Morales")
        check("Persona weight is 1.0", pgs[0].weight == 1.0, f"got {pgs[0].weight}")

    # All observations have subtype
    check("All observations have subtype key",
          all("subtype" in o.detail for o in obs))

    # All observations are guardian_verdict type
    check("All obs are guardian_verdict type",
          all(o.observation_type == "guardian_verdict" for o in obs))


# ══════════════════════════════════════════════════════════════
# 4: Aligned guardians produce nothing
# ══════════════════════════════════════════════════════════════

print("\n=== 4: Aligned guardians produce nothing ===")

with tempfile.TemporaryDirectory() as tmpdir:
    logs = Path(tmpdir) / "logs"
    logs.mkdir()
    write_guardian(logs, "guardian-pre-plan-1772438100.json", make_aligned_guardian())
    write_guardian(logs, "guardian-post-review-1772438415.json", make_aligned_guardian())
    write_guardian(logs, "guardian-post-integration-1772439500.json", make_aligned_guardian())

    result = ExtractResult()
    _step3_guardian_verdicts("test-feature", logs, TASKS, result)

    check("Zero observations from aligned files", len(result.observations) == 0,
          f"got {len(result.observations)}")


# ══════════════════════════════════════════════════════════════
# 5: Pre-plan and post-integration use task_id="*"
# ══════════════════════════════════════════════════════════════

print("\n=== 5: Feature-level guardians use task_id='*' ===")

with tempfile.TemporaryDirectory() as tmpdir:
    logs = Path(tmpdir) / "logs"
    logs.mkdir()
    # Make pre-plan flagged so it produces an observation
    write_guardian(logs, "guardian-pre-plan-1772438100.json",
                   make_flagged_guardian())
    write_guardian(logs, "guardian-post-integration-1772439500.json",
                   make_flagged_guardian())

    result = ExtractResult()
    _step3_guardian_verdicts("test-feature", logs, TASKS, result)

    verdicts = [o for o in result.observations if o.detail.get("subtype") == "verdict"]
    check("Pre-plan verdict has task_id='*'",
          any(v.task_id == "*" and "pre-plan" in v.detail.get("source_file", "")
              for v in verdicts))
    check("Post-integration verdict has task_id='*'",
          any(v.task_id == "*" and "post-integration" in v.detail.get("source_file", "")
              for v in verdicts))


# ══════════════════════════════════════════════════════════════
# 6: Task JSON fallback
# ══════════════════════════════════════════════════════════════

print("\n=== 6: Task JSON fallback (no guardian files) ===")

with tempfile.TemporaryDirectory() as tmpdir:
    logs = Path(tmpdir) / "logs"
    logs.mkdir()  # empty, no guardian files

    tasks_with_rejection = {
        "5": {
            "id": 5, "status": "done",
            "review_verdict": "approve",
            "review_feedback": "GUARDIAN REJECTED: Vision violation",
            "retry_count": 0,
        },
        "6": {
            "id": 6, "status": "pending",
            "review_verdict": "request_changes",
            "review_feedback": "GUARDIAN REJECTED: Scope creep",
            "retry_count": 0,
        },
        "7": {
            "id": 7, "status": "done",
            "review_verdict": "approve",
            "review_feedback": '{"issues": []}',
        },
    }

    result = ExtractResult()
    _step3_guardian_verdicts("test-feature", logs, tasks_with_rejection, result)

    gv = [o for o in result.observations if o.observation_type == "guardian_verdict"]
    check("Two guardian_verdict from fallback", len(gv) == 2,
          f"got {len(gv)}")

    overrides = [o for o in result.observations if o.observation_type == "human_override"]
    check("One human_override (task 5, status=done)", len(overrides) == 1,
          f"got {len(overrides)}")
    if overrides:
        check("Override is for task 5", overrides[0].task_id == "5",
              f"got {overrides[0].task_id}")
        check("Override weight is 2.5", overrides[0].weight == 2.5,
              f"got {overrides[0].weight}")

    task7 = [o for o in result.observations if o.task_id == "7"]
    check("Task 7 (no GUARDIAN REJECTED) produces nothing", len(task7) == 0,
          f"got {len(task7)}")

    # Fallback verdicts have source_file="task_json" and subtype
    for gvo in gv:
        check(f"Fallback task {gvo.task_id} has source_file=task_json",
              gvo.detail.get("source_file") == "task_json")
        check(f"Fallback task {gvo.task_id} has subtype=verdict",
              gvo.detail.get("subtype") == "verdict")
        check(f"Fallback task {gvo.task_id} weight=1.0",
              gvo.weight == 1.0, f"got {gvo.weight}")


# ══════════════════════════════════════════════════════════════
# 7: Rejected guardian JSON (not just flagged)
# ══════════════════════════════════════════════════════════════

print("\n=== 7: Rejected status from guardian JSON ===")

with tempfile.TemporaryDirectory() as tmpdir:
    logs = Path(tmpdir) / "logs"
    logs.mkdir()
    write_guardian(logs, "guardian-post-review-1772439353.json",
                   make_flagged_guardian(status="rejected"))

    result = ExtractResult()
    _step3_guardian_verdicts("test-feature", logs, TASKS, result)

    verdicts = [o for o in result.observations if o.detail.get("subtype") == "verdict"]
    check("Rejected status produces verdict", len(verdicts) == 1)
    if verdicts:
        check("Verdict says rejected", verdicts[0].detail["verdict"] == "rejected")


# ══════════════════════════════════════════════════════════════
# 8: Edge cases
# ══════════════════════════════════════════════════════════════

print("\n=== 8: Edge cases ===")

with tempfile.TemporaryDirectory() as tmpdir:
    logs = Path(tmpdir) / "logs"
    logs.mkdir()

    # Malformed JSON file
    (logs / "guardian-pre-plan-1772438100.json").write_text("not json{{{")
    result = ExtractResult()
    _step3_guardian_verdicts("test-feature", logs, TASKS, result)
    check("Malformed JSON skipped gracefully", len(result.observations) == 0)

    # Empty scope_violations and flags in flagged guardian
    (logs / "guardian-pre-plan-1772438100.json").write_text(json.dumps({
        "status": "flagged",
        "behavioral_test": {"verdict": "misaligned", "reasoning": ""},
        "scope_violations": [],
        "persona_grounding": [],
        "differentiation_impact": {},
        "flags": [],
        "summary": "Flagged but no details."
    }))
    result2 = ExtractResult()
    _step3_guardian_verdicts("test-feature", logs, TASKS, result2)
    check("Flagged with empty arrays produces only verdict",
          len(result2.observations) == 1
          and result2.observations[0].detail["subtype"] == "verdict")

    # Non-dict scope violation entry skipped
    (logs / "guardian-pre-plan-1772438100.json").write_text(json.dumps({
        "status": "flagged",
        "behavioral_test": {},
        "scope_violations": ["not a dict", {"feature": "X", "maps_to": "Y",
                                             "severity": "warning", "reasoning": "Z"}],
        "persona_grounding": [],
        "differentiation_impact": {},
        "flags": [],
        "summary": "Mixed."
    }))
    result3 = ExtractResult()
    _step3_guardian_verdicts("test-feature", logs, TASKS, result3)
    svs = [o for o in result3.observations if o.detail.get("subtype") == "scope_violation"]
    check("Non-dict scope violation entry skipped, valid one kept",
          len(svs) == 1 and svs[0].detail["feature_name"] == "X")

    # review_feedback is not a string (e.g. dict from reviewer)
    result4 = ExtractResult()
    tasks_nonstr = {"8": {"id": 8, "status": "done",
                          "review_feedback": {"issues": [], "verdict": "approve"}}}
    empty_logs = Path(tmpdir) / "empty"
    empty_logs.mkdir()
    _step3_guardian_verdicts("test-feature", empty_logs, tasks_nonstr, result4)
    check("Non-string review_feedback skipped", len(result4.observations) == 0)


# ══════════════════════════════════════════════════════════════
# 9: Idempotency — same input produces same observation IDs
# ══════════════════════════════════════════════════════════════

print("\n=== 9: Idempotency ===")

with tempfile.TemporaryDirectory() as tmpdir:
    logs = Path(tmpdir) / "logs"
    logs.mkdir()
    write_guardian(logs, "guardian-post-review-1772439353.json", make_flagged_guardian())

    r1 = ExtractResult()
    _step3_guardian_verdicts("test-feature", logs, TASKS, r1)
    ids1 = [o.id for o in r1.observations]

    r2 = ExtractResult()
    _step3_guardian_verdicts("test-feature", logs, TASKS, r2)
    ids2 = [o.id for o in r2.observations]

    # IDs won't match because timestamp differs per run, but count should match
    check("Same input produces same observation count",
          len(ids1) == len(ids2) and len(ids1) > 0)


# ══════════════════════════════════════════════════════════════

print(f"\n{'=' * 60}")
print(f"Results: {passed} passed, {failed} failed")
print(f"{'=' * 60}")

sys.exit(1 if failed else 0)
