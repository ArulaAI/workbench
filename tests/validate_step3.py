#!/usr/bin/env python3
"""Validation harness for Step 3: Guardian Verdicts.

Runs the proposed Step 3 implementation against synthetic guardian fixtures
that mirror the real data documented in the audit. Validates that the output
matches the spec's goals:

  G1: Non-aligned verdicts (flagged/rejected) produce observations
  G2: Aligned verdicts produce nothing
  G3: Scope violations extracted as separate observations
  G4: Flags (warning/critical) extracted, notes skipped
  G5: Persona grounding failures extracted from non-aligned files
  G6: Post-review guardians map to task IDs via timestamp correlation
  G7: Pre-plan and post-integration guardians use task_id="*"
  G8: Task JSON fallback fires for "GUARDIAN REJECTED" prefix
  G9: Human override produced when rejected task has status=done
  G10: All observations carry subtype key
  G11: Weight hierarchy: scope_violation=2.0, flag=1.5, persona=1.0, verdict=1.0

Usage:
  python tests/validate_step3.py
"""

import json
import sys
import tempfile
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from hashlib import sha256

# ---------------------------------------------------------------------------
# Minimal reproduction of extract.py types (self-contained, no imports)
# ---------------------------------------------------------------------------

@dataclass
class Observation:
    id: str
    feature: str
    stage: str
    task_id: str
    timestamp: str
    observation_type: str
    detail: dict
    weight: float

@dataclass
class ExtractResult:
    observations: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def observation_id(feature, task_id, stage, obs_type, detail) -> str:
    canonical = json.dumps({
        "feature": feature, "task_id": task_id, "stage": stage,
        "observation_type": obs_type, "detail": detail,
    }, sort_keys=True)
    return f"sha256:{sha256(canonical.encode()).hexdigest()}"

_WEIGHTS = {
    "retry": 3.0,
    "reviewer_finding": 1.5,
    "human_override": 2.5,
    "guardian_verdict": 2.0,
    "gate_failure": 2.0,
    "context_miss": 1.5,
    "context_waste": 0.5,
    "decomposition_miss": 2.0,
    "convention_violation": 1.5,
    "verify_finding": 2.0,
    "coherence_issue": 2.0,
    "security_finding": 1.5,
    "success": 0.5,
    "pattern_match": 2.0,
    "unattributed_changes": 1.0,
    "agent_concern": 1.0,
}

def _make_obs(feature, stage, task_id, obs_type, detail, weight=None):
    w = weight if weight is not None else _WEIGHTS.get(obs_type, 1.0)
    return Observation(
        id=observation_id(feature, task_id, stage, obs_type, detail),
        feature=feature, stage=stage, task_id=task_id,
        timestamp=_now_iso(), observation_type=obs_type,
        detail=detail, weight=w,
    )

def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.loads(f.read())
    except (OSError, json.JSONDecodeError):
        return None

# ---------------------------------------------------------------------------
# Proposed Step 3 implementation (exact copy from tech spec)
# ---------------------------------------------------------------------------

def _parse_check_type(filename: str) -> str:
    stem = filename.replace("guardian-", "").rsplit("-", 1)[0]
    return stem

def _resolve_task_id(gfile: Path, check_type: str,
                     tasks: dict) -> str:
    try:
        guardian_epoch = int(gfile.stem.rsplit("-", 1)[-1])
    except (ValueError, IndexError):
        return "*"

    best_task = "*"
    best_delta = float("inf")
    for task_id, task in tasks.items():
        iso_ts = task.get("reviewed_at") or task.get("completed_at")
        if not iso_ts:
            continue
        try:
            task_epoch = datetime.fromisoformat(
                iso_ts.replace("Z", "+00:00")).timestamp()
        except (ValueError, AttributeError):
            continue
        delta = abs(task_epoch - guardian_epoch)
        if delta < best_delta:
            best_delta = delta
            best_task = task_id
    return best_task

def _step3_guardian_verdicts(feature: str, logs_dir: Path,
                              tasks: dict, result: ExtractResult) -> None:
    # Primary source: guardian JSON files
    for gfile in sorted(logs_dir.glob("guardian-*.json")):
        data = _read_json(gfile)
        if not isinstance(data, dict):
            continue

        status = data.get("status", "unknown")
        check_type = _parse_check_type(gfile.name)
        task_id = (_resolve_task_id(gfile, check_type, tasks)
                   if check_type == "post-review" else "*")

        if status in ("flagged", "rejected", "misaligned"):
            behavioral = data.get("behavioral_test", {})
            scope_violations = data.get("scope_violations", [])
            flags = data.get("flags", [])
            diff_impact = data.get("differentiation_impact", {})

            detail = {
                "subtype": "verdict",
                "verdict": status,
                "summary": data.get("summary", ""),
                "behavioral_test": behavioral.get("verdict", ""),
                "behavioral_reasoning": behavioral.get("reasoning", ""),
                "scope_violation_count": len(scope_violations),
                "flag_count": len(flags),
                "differentiation_direction": diff_impact.get("direction", ""),
                "check_type": check_type,
                "source_file": gfile.name,
            }
            result.observations.append(
                _make_obs(feature, "guardian", task_id,
                          "guardian_verdict", detail, weight=1.0)
            )

            for sv in scope_violations:
                if not isinstance(sv, dict):
                    continue
                sv_detail = {
                    "subtype": "scope_violation",
                    "feature_name": sv.get("feature", ""),
                    "maps_to": sv.get("maps_to", ""),
                    "severity": sv.get("severity", ""),
                    "reasoning": sv.get("reasoning", ""),
                    "source_file": gfile.name,
                }
                result.observations.append(
                    _make_obs(feature, "guardian", task_id,
                              "guardian_verdict", sv_detail, weight=2.0)
                )

            for flag in flags:
                if not isinstance(flag, dict):
                    continue
                if flag.get("severity") not in ("warning", "critical"):
                    continue
                flag_detail = {
                    "subtype": "flag",
                    "severity": flag.get("severity", ""),
                    "description": flag.get("description", ""),
                    "vision_reference": flag.get("vision_reference", ""),
                    "recommendation": flag.get("recommendation", ""),
                    "source_file": gfile.name,
                }
                result.observations.append(
                    _make_obs(feature, "guardian", task_id,
                              "guardian_verdict", flag_detail, weight=1.5)
                )

            for pg in data.get("persona_grounding", []):
                if not isinstance(pg, dict):
                    continue
                if pg.get("served") is False:
                    pg_detail = {
                        "subtype": "persona_not_served",
                        "persona": pg.get("persona", ""),
                        "use_case": pg.get("use_case", ""),
                        "source_file": gfile.name,
                    }
                    result.observations.append(
                        _make_obs(feature, "guardian", task_id,
                                  "guardian_verdict", pg_detail, weight=1.0)
                    )

    # Secondary source: task JSON prefix check
    for task_id, task in tasks.items():
        feedback = task.get("review_feedback", "")
        if not isinstance(feedback, str):
            continue
        if not feedback.startswith("GUARDIAN REJECTED"):
            continue
        summary = feedback.replace(
            "GUARDIAN REJECTED: ", "", 1).replace(
            "GUARDIAN REJECTED:", "", 1).strip()
        detail = {
            "subtype": "verdict",
            "verdict": "rejected",
            "summary": summary,
            "task_final_status": task.get("status", "unknown"),
            "led_to_rerun": task.get("status") == "done",
            "source_file": "task_json",
        }
        result.observations.append(
            _make_obs(feature, "guardian", task_id,
                      "guardian_verdict", detail, weight=1.0)
        )

        if task.get("status") == "done":
            override_detail = {
                "original_rejection": feedback,
                "task_status": "done",
                "review_verdict": task.get("review_verdict", "unknown"),
                "retry_count": task.get("retry_count", 0),
            }
            result.observations.append(
                _make_obs(feature, "human", task_id,
                          "human_override", override_detail)
            )

# ---------------------------------------------------------------------------
# Fixtures — mirror the audit's documented guardian data
# ---------------------------------------------------------------------------

# Epochs chosen so post-review files correlate with task reviewed_at timestamps.
# Task 3 reviewed_at ~1772438415, Task 4 reviewed_at ~1772439353.

GUARDIAN_FILES = {
    "guardian-pre-plan-1772438100.json": {
        "status": "aligned",
        "vision_alignment": {"core_mission_served": True, "reasoning": "Feed presentation only."},
        "behavioral_test": {"verdict": "aligned", "reasoning": "No new content types."},
        "scope_violations": [],
        "persona_grounding": [
            {"persona": "Maya Chen", "served": True, "use_case": "Sees project names at a glance"},
            {"persona": "James Okafor", "served": True, "use_case": "Evaluates projects visually"},
            {"persona": "David Morales", "served": True, "use_case": "Finds tribe context"},
        ],
        "differentiation_impact": {"direction": "strengthens", "pillars_affected": ["visual quality"]},
        "flags": [{"severity": "note", "description": "TRIBE_ANNOUNCEMENT may need review", "vision_reference": "", "recommendation": ""}],
        "summary": "No new content types introduced; presentation layer only."
    },
    "guardian-post-review-1772438415.json": {
        "status": "aligned",
        "vision_alignment": {"core_mission_served": True, "reasoning": "Seed data enrichment."},
        "behavioral_test": {"verdict": "aligned", "reasoning": "All event types represent build artifacts."},
        "scope_violations": [],
        "persona_grounding": [
            {"persona": "Maya Chen", "served": True, "use_case": "Actor names visible"},
            {"persona": "James Okafor", "served": True, "use_case": "Can see project relevance"},
        ],
        "differentiation_impact": {"direction": "neutral", "pillars_affected": []},
        "flags": [{"severity": "note", "description": "BUILDER_JOINED naming convention", "vision_reference": "", "recommendation": ""}],
        "summary": "All event types represent legitimate build artifacts."
    },
    "guardian-post-review-1772439353.json": {
        "status": "flagged",
        "vision_alignment": {"core_mission_served": True, "reasoning": "Feed serves builders, but one event type drifts."},
        "behavioral_test": {"verdict": "misaligned", "reasoning": "TRIBE_ANNOUNCEMENT is structurally a text post."},
        "scope_violations": [
            {
                "feature": "TRIBE_ANNOUNCEMENT",
                "maps_to": "Text-Only Posts / Content Creation (Won't Have)",
                "severity": "warning",
                "reasoning": "TRIBE_ANNOUNCEMENT is structurally identical to a text post. Vision excludes text-only content creation."
            }
        ],
        "persona_grounding": [
            {"persona": "Maya Chen", "served": True, "use_case": "Sees feed updates"},
            {"persona": "James Okafor", "served": True, "use_case": "Can browse projects"},
            {"persona": "David Morales", "served": False, "use_case": "Announcements lack build artifact context"},
        ],
        "differentiation_impact": {"direction": "weakens", "pillars_affected": ["build-first identity"]},
        "flags": [
            {"severity": "warning", "description": "TRIBE_ANNOUNCEMENT is structurally identical to a text post", "vision_reference": "Text-Only Posts / Content Creation (Won't Have)", "recommendation": "Remove from supported types or redefine with artifact anchor"},
            {"severity": "note", "description": "TextCard path used for announcements", "vision_reference": "", "recommendation": ""}
        ],
        "summary": "TRIBE_ANNOUNCEMENT introduces text-content-primary event type identical to excluded text posts."
    },
    "guardian-post-integration-1772439500.json": {
        "status": "aligned",
        "vision_alignment": {"core_mission_served": True, "reasoning": "Visual hierarchy rewards building."},
        "behavioral_test": {"verdict": "aligned", "reasoning": "Milestone > Content > Activity ordering."},
        "scope_violations": [
            {
                "feature": "TextCard path",
                "maps_to": "Text-Only Posts / Content Creation (Won't Have)",
                "severity": "warning",
                "reasoning": "TextCard component exists for TRIBE_ANNOUNCEMENT and PROJECT_UPDATE."
            }
        ],
        "persona_grounding": [
            {"persona": "Maya Chen", "served": True, "use_case": "Timeline shows build activity"},
        ],
        "differentiation_impact": {"direction": "strengthens", "pillars_affected": ["visual quality", "build-first"]},
        "flags": [{"severity": "note", "description": "TextCard path still present", "vision_reference": "", "recommendation": ""}],
        "summary": "Visual hierarchy explicitly rewards building over performing."
    },
}

TASKS = {
    "1": {
        "id": 1, "status": "done",
        "reviewed_at": "2026-03-01T06:30:00Z",
        "completed_at": "2026-03-01T06:31:00Z",
        "review_verdict": "approve",
        "review_feedback": "",
    },
    "2": {
        "id": 2, "status": "done",
        "reviewed_at": "2026-03-01T06:45:00Z",
        "completed_at": "2026-03-01T06:46:00Z",
        "review_verdict": "approve",
        "review_feedback": "",
    },
    "3": {
        "id": 3, "status": "done",
        "reviewed_at": "2026-03-02T08:00:15Z",
        "completed_at": "2026-03-02T08:01:00Z",
        "review_verdict": "approve",
        "review_feedback": "",
    },
    "4": {
        "id": 4, "status": "done",
        "reviewed_at": "2026-03-02T08:15:53Z",
        "completed_at": "2026-03-02T08:16:00Z",
        "review_verdict": "approve",
        "review_feedback": "",
    },
}

# Separate task dict for fallback testing
TASKS_WITH_REJECTION = {
    "5": {
        "id": 5, "status": "done",
        "review_verdict": "approve",
        "review_feedback": "GUARDIAN REJECTED: Vision violation in text post support",
        "retry_count": 0,
    },
    "6": {
        "id": 6, "status": "pending",
        "review_verdict": "request_changes",
        "review_feedback": "GUARDIAN REJECTED: Scope creep into content creation",
        "retry_count": 0,
    },
    "7": {
        "id": 7, "status": "done",
        "review_verdict": "approve",
        "review_feedback": '{"issues": [], "verdict": "approve"}',
    },
}


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

def write_fixtures(logs_dir: Path):
    logs_dir.mkdir(parents=True, exist_ok=True)
    for filename, data in GUARDIAN_FILES.items():
        (logs_dir / filename).write_text(json.dumps(data, indent=2))


def print_obs(obs: Observation, indent=2):
    pad = " " * indent
    d = obs.detail
    subtype = d.get("subtype", "?")
    print(f"{pad}[{obs.observation_type}:{subtype}] task={obs.task_id} "
          f"stage={obs.stage} weight={obs.weight}")
    # Print key detail fields based on subtype
    if subtype == "verdict":
        print(f"{pad}  verdict={d.get('verdict')} check_type={d.get('check_type', '')} "
              f"behavioral={d.get('behavioral_test', '')}")
        if d.get("summary"):
            print(f"{pad}  summary: {d['summary'][:80]}")
    elif subtype == "scope_violation":
        print(f"{pad}  {d.get('feature_name')} -> {d.get('maps_to')} ({d.get('severity')})")
    elif subtype == "flag":
        print(f"{pad}  [{d.get('severity')}] {d.get('description', '')[:80]}")
    elif subtype == "persona_not_served":
        print(f"{pad}  {d.get('persona')}: {d.get('use_case', '')[:80]}")
    # Fallback verdict fields
    if d.get("source_file") == "task_json":
        print(f"{pad}  task_final_status={d.get('task_final_status')} "
              f"led_to_rerun={d.get('led_to_rerun')}")


def check(label: str, condition: bool):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}")
    return condition


def main():
    passed = 0
    failed = 0

    def tally(ok):
        nonlocal passed, failed
        if ok:
            passed += 1
        else:
            failed += 1

    with tempfile.TemporaryDirectory() as tmpdir:
        logs_dir = Path(tmpdir) / "logs"
        write_fixtures(logs_dir)

        # ── Scenario 1: Primary source (guardian JSON files) ──────────
        print("=" * 70)
        print("SCENARIO 1: Guardian JSON files (4 files, 1 flagged)")
        print("=" * 70)

        result = ExtractResult()
        _step3_guardian_verdicts("f10-rich-feed", logs_dir, TASKS, result)

        print(f"\nProduced {len(result.observations)} observations:\n")
        for obs in result.observations:
            print_obs(obs)
        print()

        # G1: Non-aligned verdicts produce observations
        verdicts = [o for o in result.observations
                    if o.detail.get("subtype") == "verdict"]
        tally(check("G1: Flagged guardian produces verdict observation",
                     len(verdicts) == 1 and verdicts[0].detail["verdict"] == "flagged"))

        # G2: Aligned verdicts produce nothing
        aligned_obs = [o for o in result.observations
                       if o.detail.get("source_file", "").endswith("38100.json")  # pre-plan
                       or o.detail.get("source_file", "").endswith("39500.json")]  # post-integration
        tally(check("G2: Aligned guardians produce no observations",
                     len(aligned_obs) == 0))

        # G3: Scope violations extracted
        sv_obs = [o for o in result.observations
                  if o.detail.get("subtype") == "scope_violation"]
        tally(check("G3: Scope violation extracted from flagged file",
                     len(sv_obs) == 1
                     and sv_obs[0].detail["feature_name"] == "TRIBE_ANNOUNCEMENT"
                     and sv_obs[0].detail["maps_to"] == "Text-Only Posts / Content Creation (Won't Have)"))

        # G4: Warning flags extracted, notes skipped
        flag_obs = [o for o in result.observations
                    if o.detail.get("subtype") == "flag"]
        tally(check("G4: Warning flag extracted, note flags skipped",
                     len(flag_obs) == 1
                     and flag_obs[0].detail["severity"] == "warning"))

        # G5: Persona grounding failures
        pg_obs = [o for o in result.observations
                  if o.detail.get("subtype") == "persona_not_served"]
        tally(check("G5: Persona not served extracted from flagged file",
                     len(pg_obs) == 1
                     and pg_obs[0].detail["persona"] == "David Morales"))

        # G6: Post-review maps to task ID
        flagged_verdict = verdicts[0] if verdicts else None
        tally(check("G6: Post-review guardian maps to task_id via timestamp",
                     flagged_verdict is not None and flagged_verdict.task_id == "4"))

        # Also check the aligned post-review doesn't produce observations
        # (can't check task_id since no observation was produced — that's G2)

        # G7: Pre-plan and post-integration use task_id="*"
        # Since aligned files produce no observations, verify indirectly:
        # all observations from the flagged file (post-review) should have task_id
        all_task_ids = {o.task_id for o in result.observations}
        tally(check("G7: No feature-level observations (aligned pre-plan/post-integration produced nothing)",
                     "*" not in all_task_ids))

        # G10: All observations carry subtype
        all_have_subtype = all("subtype" in o.detail for o in result.observations)
        tally(check("G10: All observations carry subtype key",
                     all_have_subtype))

        # G11: Weight hierarchy
        tally(check("G11a: Verdict weight = 1.0",
                     flagged_verdict is not None and flagged_verdict.weight == 1.0))
        tally(check("G11b: Scope violation weight = 2.0",
                     len(sv_obs) > 0 and sv_obs[0].weight == 2.0))
        tally(check("G11c: Flag weight = 1.5",
                     len(flag_obs) > 0 and flag_obs[0].weight == 1.5))
        tally(check("G11d: Persona weight = 1.0",
                     len(pg_obs) > 0 and pg_obs[0].weight == 1.0))

        # ── Scenario 2: Aligned-only (no observations expected) ───────
        print("\n" + "=" * 70)
        print("SCENARIO 2: All-aligned guardian files (pre-plan + post-integration only)")
        print("=" * 70)

        aligned_dir = Path(tmpdir) / "aligned_logs"
        aligned_dir.mkdir()
        for fname in ["guardian-pre-plan-1772438100.json",
                      "guardian-post-integration-1772439500.json"]:
            (aligned_dir / fname).write_text(
                json.dumps(GUARDIAN_FILES[fname], indent=2))

        result2 = ExtractResult()
        _step3_guardian_verdicts("f10-aligned", aligned_dir, TASKS, result2)

        print(f"\nProduced {len(result2.observations)} observations")
        tally(check("Aligned-only: zero observations",
                     len(result2.observations) == 0))

        # ── Scenario 3: Task JSON fallback ────────────────────────────
        print("\n" + "=" * 70)
        print("SCENARIO 3: Task JSON fallback (no guardian files, GUARDIAN REJECTED in task)")
        print("=" * 70)

        empty_dir = Path(tmpdir) / "empty_logs"
        empty_dir.mkdir()

        result3 = ExtractResult()
        _step3_guardian_verdicts("f10-fallback", empty_dir, TASKS_WITH_REJECTION, result3)

        print(f"\nProduced {len(result3.observations)} observations:\n")
        for obs in result3.observations:
            print_obs(obs)
        print()

        # G8: Fallback fires
        fb_verdicts = [o for o in result3.observations
                       if o.observation_type == "guardian_verdict"]
        tally(check("G8: Task JSON fallback produces guardian_verdict for REJECTED tasks",
                     len(fb_verdicts) == 2))  # tasks 5 and 6

        # G9: Human override for done+rejected
        overrides = [o for o in result3.observations
                     if o.observation_type == "human_override"]
        tally(check("G9: Human override produced for task 5 (status=done + REJECTED)",
                     len(overrides) == 1 and overrides[0].task_id == "5"))

        # Task 7 (no GUARDIAN REJECTED prefix) should produce nothing
        task7_obs = [o for o in result3.observations if o.task_id == "7"]
        tally(check("Non-rejected task produces nothing from fallback",
                     len(task7_obs) == 0))

        # Fallback verdicts have source_file="task_json"
        fb_sources = {o.detail.get("source_file") for o in fb_verdicts}
        tally(check("Fallback verdicts have source_file='task_json'",
                     fb_sources == {"task_json"}))

        # Fallback weights
        fb_weights = {o.weight for o in fb_verdicts}
        tally(check("Fallback verdict weight = 1.0",
                     fb_weights == {1.0}))

        override_weight = overrides[0].weight if overrides else None
        tally(check("Human override weight = 2.5 (from _WEIGHTS default)",
                     override_weight == 2.5))

        # ── Scenario 4: _parse_check_type correctness ────────────────
        print("\n" + "=" * 70)
        print("SCENARIO 4: _parse_check_type")
        print("=" * 70 + "\n")

        tally(check("pre-plan parses correctly",
                     _parse_check_type("guardian-pre-plan-1772438901.json") == "pre-plan"))
        tally(check("post-review parses correctly",
                     _parse_check_type("guardian-post-review-1772439353.json") == "post-review"))
        tally(check("post-integration parses correctly",
                     _parse_check_type("guardian-post-integration-1772439500.json") == "post-integration"))

    # ── Summary ───────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    total = passed + failed
    print(f"RESULTS: {passed}/{total} passed, {failed} failed")
    print("=" * 70)

    if failed > 0:
        print("\nFAILED checks need investigation before implementation.")
        sys.exit(1)
    else:
        print("\nAll goals validated. Ready to implement.")
        sys.exit(0)


if __name__ == "__main__":
    main()
