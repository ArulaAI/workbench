#!/usr/bin/env python3
"""Tests for the synthesis pipeline.

Covers each pipeline step, end-to-end synthesis, incremental skipping,
and real data validation.
"""

import json
import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "lib"))

from lib.learn.extract import Observation
from lib.learn.synthesize import (
    Evidence,
    LearningsEntry,
    SynthesisResult,
    _AGENT_ROUTING,
    _TOKEN_BUDGETS,
    _build_entries,
    _cross_agent_id,
    _cross_agent_reframe,
    _apply_weight_modifiers,
    _deduplicate,
    _detect_conflicts,
    _detect_staleness,
    _enforce_budget,
    _entry_to_dict,
    _extract_files,
    _file_overlap,
    _observation_hash,
    _quality_bar,
    _read_all_observations,
    _format_entry_markdown,
    filter_learnings_for_task,
    synthesize,
)


# ── Fixtures ──────────────────────────────────────────────────────────


def make_obs(
    obs_type="retry",
    feature="feat-1",
    detail=None,
    weight=3.0,
    task_id="task-1",
    stage="develop",
    obs_id=None,
    timestamp="2026-03-01T00:00:00Z",
):
    if detail is None:
        detail = {
            "files_involved": ["lib/foo.py"],
            "what_happened": "test failed",
            "resolution": "fixed import",
        }
    if obs_id is None:
        import hashlib
        payload = f"{feature}-{task_id}-{obs_type}-{json.dumps(detail, sort_keys=True)}"
        obs_id = f"sha256:{hashlib.sha256(payload.encode()).hexdigest()}"
    return Observation(
        id=obs_id,
        feature=feature,
        stage=stage,
        task_id=task_id,
        timestamp=timestamp,
        observation_type=obs_type,
        detail=detail,
        weight=weight,
    )


def write_obs_jsonl(obs_dir, feature, observations):
    """Write observations to a JSONL file in obs_dir."""
    obs_dir.mkdir(parents=True, exist_ok=True)
    lines = []
    for obs in observations:
        d = {
            "id": obs.id,
            "feature": obs.feature,
            "stage": obs.stage,
            "task_id": obs.task_id,
            "timestamp": obs.timestamp,
            "observation_type": obs.observation_type,
            "detail": obs.detail,
            "weight": obs.weight,
        }
        lines.append(json.dumps(d))
    (obs_dir / f"{feature}.jsonl").write_text("\n".join(lines) + "\n")


# ── Step 1: Read observations ─────────────────────────────────────────


class TestReadAllObservations:
    def test_reads_jsonl_files(self, tmp_path):
        obs_dir = tmp_path / "observations"
        obs = [make_obs(feature="f1"), make_obs(feature="f1", task_id="task-2")]
        write_obs_jsonl(obs_dir, "f1", obs)

        result, warnings = _read_all_observations(obs_dir)
        assert len(result) == 2
        assert not warnings

    def test_excludes_success_and_pattern_match(self, tmp_path):
        obs_dir = tmp_path / "observations"
        obs = [
            make_obs(obs_type="success", detail={"files_planned": []}),
            make_obs(obs_type="pattern_match", detail={"pattern": "x"}),
            make_obs(obs_type="retry"),
        ]
        write_obs_jsonl(obs_dir, "f1", obs)

        result, _ = _read_all_observations(obs_dir)
        assert len(result) == 1
        assert result[0].observation_type == "retry"

    def test_skips_malformed_lines(self, tmp_path):
        obs_dir = tmp_path / "observations"
        obs_dir.mkdir(parents=True)
        (obs_dir / "f1.jsonl").write_text(
            "not valid json\n"
            + json.dumps({
                "id": "sha256:abc", "feature": "f1", "stage": "develop",
                "task_id": "t1", "timestamp": "2026-01-01T00:00:00Z",
                "observation_type": "retry",
                "detail": {"files_involved": ["a.py"]},
                "weight": 3.0,
            })
            + "\n"
        )

        result, warnings = _read_all_observations(obs_dir)
        assert len(result) == 1
        assert len(warnings) == 1

    def test_empty_dir(self, tmp_path):
        obs_dir = tmp_path / "observations"
        obs_dir.mkdir(parents=True)
        result, _ = _read_all_observations(obs_dir)
        assert result == []

    def test_missing_dir(self, tmp_path):
        result, _ = _read_all_observations(tmp_path / "nope")
        assert result == []

    def test_sorted_by_timestamp(self, tmp_path):
        obs_dir = tmp_path / "observations"
        obs = [
            make_obs(timestamp="2026-03-03T00:00:00Z", task_id="t3"),
            make_obs(timestamp="2026-03-01T00:00:00Z", task_id="t1"),
            make_obs(timestamp="2026-03-02T00:00:00Z", task_id="t2"),
        ]
        write_obs_jsonl(obs_dir, "f1", obs)

        result, _ = _read_all_observations(obs_dir)
        timestamps = [o.timestamp for o in result]
        assert timestamps == sorted(timestamps)

    def test_reads_multiple_files(self, tmp_path):
        obs_dir = tmp_path / "observations"
        write_obs_jsonl(obs_dir, "f1", [make_obs(feature="f1")])
        write_obs_jsonl(obs_dir, "f2", [make_obs(feature="f2")])

        result, _ = _read_all_observations(obs_dir)
        assert len(result) == 2


# ── Helpers ───────────────────────────────────────────────────────────


class TestExtractFiles:
    def test_files_involved_list(self):
        assert _extract_files({"files_involved": ["b.py", "a.py"]}) == [
            "a.py", "b.py"
        ]

    def test_file_string(self):
        assert _extract_files({"file": "lib/foo.py"}) == ["lib/foo.py"]

    def test_planned_and_actual(self):
        result = _extract_files({
            "planned_files": ["a.py"],
            "actual_files": ["a.py", "b.py"],
        })
        assert result == ["a.py", "b.py"]

    def test_empty_detail(self):
        assert _extract_files({}) == []

    def test_deduplicates(self):
        result = _extract_files({
            "files_involved": ["a.py"],
            "file": "a.py",
        })
        assert result == ["a.py"]


class TestFileOverlap:
    def test_identical(self):
        assert _file_overlap(["a.py", "b.py"], ["a.py", "b.py"]) == 1.0

    def test_disjoint(self):
        assert _file_overlap(["a.py"], ["b.py"]) == 0.0

    def test_partial(self):
        assert _file_overlap(["a.py", "b.py"], ["b.py", "c.py"]) == pytest.approx(1 / 3)

    def test_both_empty(self):
        # Empty file lists = distinct signals, not duplicates
        assert _file_overlap([], []) == 0.0

    def test_one_empty(self):
        assert _file_overlap(["a.py"], []) == 0.0


class TestObservationHash:
    def test_deterministic(self):
        obs = [make_obs(obs_id="sha256:aaa"), make_obs(obs_id="sha256:bbb")]
        h1 = _observation_hash(obs)
        h2 = _observation_hash(obs)
        assert h1 == h2

    def test_order_independent(self):
        a = make_obs(obs_id="sha256:aaa")
        b = make_obs(obs_id="sha256:bbb")
        assert _observation_hash([a, b]) == _observation_hash([b, a])

    def test_different_ids_different_hash(self):
        h1 = _observation_hash([make_obs(obs_id="sha256:aaa")])
        h2 = _observation_hash([make_obs(obs_id="sha256:bbb")])
        assert h1 != h2


# ── Step 2-3: Build entries ───────────────────────────────────────────


class TestBuildEntries:
    def test_routes_to_correct_agent(self):
        for obs_type, expected_agent in _AGENT_ROUTING.items():
            obs = make_obs(obs_type=obs_type)
            result = _build_entries([obs])
            assert expected_agent in result, f"{obs_type} should route to {expected_agent}"

    def test_detail_passes_through(self):
        detail = {"files_involved": ["x.py"], "custom": "data"}
        obs = make_obs(detail=detail)
        result = _build_entries([obs])
        entry = result["developer"][0]
        assert entry.detail is detail

    def test_files_extracted(self):
        obs = make_obs(detail={"files_involved": ["lib/a.py", "lib/b.py"]})
        result = _build_entries([obs])
        entry = result["developer"][0]
        assert entry.files == ["lib/a.py", "lib/b.py"]

    def test_weight_preserved(self):
        obs = make_obs(weight=5.0)
        result = _build_entries([obs])
        assert result["developer"][0].weight == 5.0

    def test_evidence_created(self):
        obs = make_obs(feature="my-feature")
        result = _build_entries([obs])
        entry = result["developer"][0]
        assert len(entry.evidence) == 1
        assert entry.evidence[0].feature == "my-feature"
        assert entry.evidence[0].observation_id == obs.id

    def test_unknown_type_skipped(self):
        obs = make_obs(obs_type="unknown_type")
        result = _build_entries([obs])
        assert not result

    def test_source_is_direct(self):
        obs = make_obs()
        result = _build_entries([obs])
        assert result["developer"][0].source == "direct"


# ── Step 4: Cross-agent reframing ─────────────────────────────────────


class TestCrossAgentReframe:
    def test_retry_fans_out_to_architect_and_reviewer(self):
        obs = make_obs(obs_type="retry")
        entries = _build_entries([obs])
        _cross_agent_reframe(entries)

        assert "architect" in entries
        assert "reviewer" in entries
        arch_entry = entries["architect"][0]
        assert arch_entry.source == "cross_agent"
        assert arch_entry.reframing_context == "downstream_feedback"
        rev_entry = entries["reviewer"][0]
        assert rev_entry.reframing_context == "upstream_awareness"

    def test_cross_agent_preserves_detail(self):
        detail = {"files_involved": ["lib/x.py"], "what_happened": "boom"}
        obs = make_obs(obs_type="retry", detail=detail)
        entries = _build_entries([obs])
        _cross_agent_reframe(entries)

        arch_entry = entries["architect"][0]
        assert arch_entry.detail == detail

    def test_cross_agent_id_differs_from_original(self):
        obs = make_obs(obs_type="retry")
        entries = _build_entries([obs])
        _cross_agent_reframe(entries)

        orig_id = entries["developer"][0].id
        arch_id = entries["architect"][0].id
        assert orig_id != arch_id

    def test_confirmed_reviewer_finding_goes_to_developer(self):
        obs = make_obs(
            obs_type="reviewer_finding",
            detail={
                "file": "lib/foo.py",
                "category": "style",
                "finding": "missing docstring",
                "confirmed": True,
            },
            weight=1.5,
        )
        entries = _build_entries([obs])
        _cross_agent_reframe(entries)

        assert "developer" in entries
        dev_entry = entries["developer"][0]
        assert dev_entry.reframing_context == "known_pitfall"

    def test_unconfirmed_reviewer_finding_no_cross_agent(self):
        obs = make_obs(
            obs_type="reviewer_finding",
            detail={
                "file": "lib/foo.py",
                "category": "style",
                "finding": "nit",
                "confirmed": False,
            },
        )
        entries = _build_entries([obs])
        _cross_agent_reframe(entries)

        # Reviewer is the primary. No cross-agent rules fire for unconfirmed
        # (rule 4 targets reviewer = same agent, skipped).
        assert "developer" not in entries

    def test_gate_failure_goes_to_architect(self):
        obs = make_obs(
            obs_type="gate_failure",
            detail={"files_involved": ["lib/x.py"]},
            weight=2.0,
        )
        entries = _build_entries([obs])
        _cross_agent_reframe(entries)

        assert "architect" in entries
        assert entries["architect"][0].reframing_context == "gate_failure_signal"

    def test_does_not_reframe_cross_agent_entries(self):
        obs = make_obs(obs_type="retry")
        entries = _build_entries([obs])
        _cross_agent_reframe(entries)

        # Run reframing again — cross-agent entries should not spawn more
        count_before = sum(len(v) for v in entries.values())
        _cross_agent_reframe(entries)
        count_after = sum(len(v) for v in entries.values())
        assert count_before == count_after


# ── Step 5: Weight modifiers ─────────────────────────────────────────


class TestApplyWeightModifiers:
    def test_recency_boost(self):
        obs = make_obs(feature="recent-feat", weight=3.0)
        entries = _build_entries([obs])
        _apply_weight_modifiers(entries, {"recent-feat"})
        assert entries["developer"][0].weight == pytest.approx(4.5)

    def test_no_recency_for_old_feature(self):
        obs = make_obs(feature="old-feat", weight=3.0)
        entries = _build_entries([obs])
        _apply_weight_modifiers(entries, {"other-feat"})
        assert entries["developer"][0].weight == pytest.approx(3.0)

    def test_cross_agent_discount(self):
        obs = make_obs(obs_type="retry", feature="f1", weight=3.0)
        entries = _build_entries([obs])
        _cross_agent_reframe(entries)
        _apply_weight_modifiers(entries, set())

        # Cross-agent entries get 0.7x
        arch_entry = entries["architect"][0]
        assert arch_entry.weight == pytest.approx(3.0 * 0.7)

    def test_recency_and_cross_agent_stack(self):
        obs = make_obs(obs_type="retry", feature="recent", weight=3.0)
        entries = _build_entries([obs])
        _cross_agent_reframe(entries)
        _apply_weight_modifiers(entries, {"recent"})

        arch_entry = entries["architect"][0]
        assert arch_entry.weight == pytest.approx(3.0 * 1.5 * 0.7)


# ── Step 6: Staleness ────────────────────────────────────────────────


class TestDetectStaleness:
    def test_missing_file_marks_stale(self, tmp_path):
        obs = make_obs(detail={"files_involved": ["lib/gone.py"]})
        entries = _build_entries([obs])
        _detect_staleness(entries, tmp_path)

        entry = entries["developer"][0]
        assert entry.stale is True
        assert entry.weight == pytest.approx(3.0 * 0.5)

    def test_existing_file_not_stale(self, tmp_path):
        (tmp_path / "lib").mkdir()
        (tmp_path / "lib" / "exists.py").write_text("x")
        obs = make_obs(detail={"files_involved": ["lib/exists.py"]})
        entries = _build_entries([obs])
        _detect_staleness(entries, tmp_path)

        assert entries["developer"][0].stale is False

    def test_partial_files_not_stale(self, tmp_path):
        (tmp_path / "a.py").write_text("x")
        obs = make_obs(detail={"files_involved": ["a.py", "gone.py"]})
        entries = _build_entries([obs])
        _detect_staleness(entries, tmp_path)

        assert entries["developer"][0].stale is False

    def test_no_files_skipped(self, tmp_path):
        obs = make_obs(
            obs_type="coherence_issue",
            detail={"issue_type": "overlap", "description": "x"},
        )
        entries = _build_entries([obs])
        _detect_staleness(entries, tmp_path)

        assert entries["coherence"][0].stale is False


# ── Step 7: Deduplicate ──────────────────────────────────────────────


class TestDeduplicate:
    def test_merges_same_type_same_files(self):
        obs1 = make_obs(
            obs_type="retry", task_id="t1", weight=3.0,
            detail={"files_involved": ["lib/foo.py"]},
        )
        obs2 = make_obs(
            obs_type="retry", task_id="t2", weight=2.0,
            detail={"files_involved": ["lib/foo.py"]},
        )
        entries = _build_entries([obs1, obs2])
        _deduplicate(entries)

        assert len(entries["developer"]) == 1
        merged = entries["developer"][0]
        assert len(merged.evidence) == 2
        assert merged.weight == 3.0  # higher weight kept

    def test_keeps_different_types(self):
        obs1 = make_obs(
            obs_type="retry",
            detail={"files_involved": ["lib/foo.py"]},
        )
        obs2 = make_obs(
            obs_type="gate_failure",
            detail={"files_involved": ["lib/foo.py"]},
            weight=2.0,
        )
        entries = _build_entries([obs1, obs2])
        _deduplicate(entries)

        assert len(entries["developer"]) == 2

    def test_keeps_low_overlap(self):
        obs1 = make_obs(
            obs_type="retry", task_id="t1",
            detail={"files_involved": ["lib/a.py"]},
        )
        obs2 = make_obs(
            obs_type="retry", task_id="t2",
            detail={"files_involved": ["lib/b.py"]},
        )
        entries = _build_entries([obs1, obs2])
        _deduplicate(entries)

        assert len(entries["developer"]) == 2

    def test_unions_files_on_merge(self):
        # 4/5 shared = 0.8 Jaccard, meets threshold
        obs1 = make_obs(
            obs_type="retry", task_id="t1",
            detail={"files_involved": [
                "lib/a.py", "lib/b.py", "lib/c.py", "lib/d.py",
            ]},
        )
        obs2 = make_obs(
            obs_type="retry", task_id="t2",
            detail={"files_involved": [
                "lib/a.py", "lib/b.py", "lib/c.py", "lib/d.py", "lib/e.py",
            ]},
        )
        entries = _build_entries([obs1, obs2])
        _deduplicate(entries)

        merged = entries["developer"][0]
        assert "lib/e.py" in merged.files


# ── Step 8: Conflict detection ───────────────────────────────────────


class TestDetectConflicts:
    def test_context_miss_vs_waste_conflict(self):
        obs1 = make_obs(
            obs_type="context_miss", task_id="t1",
            detail={"file": "lib/foo.py"},
            weight=2.0,
        )
        obs2 = make_obs(
            obs_type="context_waste", task_id="t2",
            detail={"file": "lib/foo.py", "waste_ratio": 80},
            weight=1.0,
        )
        entries = _build_entries([obs1, obs2])
        conflicts, rejects = _detect_conflicts(entries)

        # Higher weight wins
        assert len(rejects) == 1
        assert rejects[0].observation_type == "context_waste"
        assert len(entries["developer"]) == 1

    def test_equal_weight_both_excluded(self):
        obs1 = make_obs(
            obs_type="context_miss", task_id="t1",
            detail={"file": "lib/foo.py"},
            weight=2.0,
        )
        obs2 = make_obs(
            obs_type="context_waste", task_id="t2",
            detail={"file": "lib/foo.py", "waste_ratio": 80},
            weight=2.0,
        )
        entries = _build_entries([obs1, obs2])
        conflicts, rejects = _detect_conflicts(entries)

        assert len(conflicts) == 1
        assert len(entries["developer"]) == 0

    def test_different_files_no_conflict(self):
        obs1 = make_obs(
            obs_type="context_miss", task_id="t1",
            detail={"file": "lib/a.py"},
        )
        obs2 = make_obs(
            obs_type="context_waste", task_id="t2",
            detail={"file": "lib/b.py", "waste_ratio": 80},
        )
        entries = _build_entries([obs1, obs2])
        conflicts, rejects = _detect_conflicts(entries)

        assert len(conflicts) == 0
        assert len(rejects) == 0

    def test_non_contradiction_pair_ignored(self):
        obs1 = make_obs(obs_type="retry", task_id="t1",
                        detail={"files_involved": ["lib/foo.py"]})
        obs2 = make_obs(obs_type="gate_failure", task_id="t2",
                        detail={"files_involved": ["lib/foo.py"]}, weight=2.0)
        entries = _build_entries([obs1, obs2])
        conflicts, rejects = _detect_conflicts(entries)

        assert len(conflicts) == 0
        assert len(entries["developer"]) == 2


# ── Step 9: Quality bar ─────────────────────────────────────────────


class TestQualityBar:
    def test_passes_with_file_and_evidence(self):
        obs = make_obs(detail={"files_involved": ["lib/foo.py"]})
        entries = _build_entries([obs])
        rejects = _quality_bar(entries)

        assert len(rejects) == 0
        assert len(entries["developer"]) == 1

    def test_rejects_no_file_path(self):
        obs = make_obs(
            obs_type="coherence_issue",
            detail={"issue_type": "overlap", "description": "x"},
        )
        entries = _build_entries([obs])
        rejects = _quality_bar(entries)

        assert len(rejects) == 1
        assert "no file path" in rejects[0].rejection_reason

    def test_rejects_file_without_separator(self):
        obs = make_obs(detail={"file": "Makefile"})
        entries = _build_entries([obs])
        rejects = _quality_bar(entries)

        assert len(rejects) == 1

    def test_passes_file_with_separator(self):
        obs = make_obs(detail={"file": "lib/foo.py"})
        entries = _build_entries([obs])
        rejects = _quality_bar(entries)

        assert len(rejects) == 0


# ── Step 10: Token budget ───────────────────────────────────────────


class TestEnforceBudget:
    def test_within_budget_all_kept(self):
        obs = make_obs(detail={"files_involved": ["lib/a.py"]})
        entries = _build_entries([obs])
        dropped = _enforce_budget(entries)

        assert len(dropped) == 0
        assert len(entries["developer"]) == 1

    def test_over_budget_drops_lowest(self):
        # Create entries that exceed budget
        big_detail = {"files_involved": ["lib/a.py"], "data": "x" * 10000}
        obs_list = [
            make_obs(detail=big_detail, weight=5.0, task_id=f"t{i}")
            for i in range(10)
        ]
        entries = _build_entries(obs_list)
        dropped = _enforce_budget(entries)

        assert len(dropped) > 0
        # Remaining entries should be within budget
        total = sum(
            len(json.dumps(e.detail)) // 4
            for e in entries["developer"]
        )
        assert total <= _TOKEN_BUDGETS["developer"]

    def test_highest_weight_survives(self):
        big_detail = {"files_involved": ["lib/a.py"], "data": "x" * 8000}
        obs1 = make_obs(detail=big_detail, weight=10.0, task_id="t1")
        obs2 = make_obs(detail=big_detail, weight=1.0, task_id="t2")
        entries = _build_entries([obs1, obs2])
        dropped = _enforce_budget(entries)

        kept_weights = [e.weight for e in entries["developer"]]
        dropped_weights = [e.weight for e in dropped]
        if dropped:
            assert max(dropped_weights) <= min(kept_weights)


# ── End-to-end ───────────────────────────────────────────────────────


class TestSynthesize:
    def test_empty_observations(self, tmp_path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        (memory_dir / "observations").mkdir()

        result = synthesize(memory_dir, project_root=tmp_path)

        assert not result.skipped
        assert result.entries_by_agent == {}
        assert (memory_dir / "learnings" / "synthesis-meta.json").exists()

    def test_basic_pipeline(self, tmp_path):
        memory_dir = tmp_path / "memory"
        obs_dir = memory_dir / "observations"

        # Create a file so staleness check passes
        (tmp_path / "lib").mkdir()
        (tmp_path / "lib" / "foo.py").write_text("x")

        obs = [
            make_obs(
                feature="f1", task_id="t1",
                detail={"files_involved": ["lib/foo.py"], "what_happened": "x"},
            ),
            make_obs(
                obs_type="reviewer_finding", feature="f1", task_id="t2",
                detail={
                    "file": "lib/foo.py", "category": "bug",
                    "finding": "null check", "confirmed": True,
                },
                weight=1.5,
            ),
        ]
        write_obs_jsonl(obs_dir, "f1", obs)

        result = synthesize(memory_dir, project_root=tmp_path)

        assert not result.skipped
        assert "developer" in result.entries_by_agent
        assert "reviewer" in result.entries_by_agent

        # Check files written
        learnings_dir = memory_dir / "learnings"
        assert (learnings_dir / "developer-learnings.json").exists()
        assert (learnings_dir / "reviewer-learnings.json").exists()
        assert (learnings_dir / "synthesis-meta.json").exists()
        assert (learnings_dir / "synthesis-rejects.json").exists()
        assert (learnings_dir / "synthesis-conflicts.json").exists()

    def test_output_files_valid_json(self, tmp_path):
        memory_dir = tmp_path / "memory"
        obs_dir = memory_dir / "observations"
        (tmp_path / "lib").mkdir()
        (tmp_path / "lib" / "foo.py").write_text("x")

        obs = [make_obs(detail={"files_involved": ["lib/foo.py"]})]
        write_obs_jsonl(obs_dir, "f1", obs)

        synthesize(memory_dir, project_root=tmp_path)

        learnings_dir = memory_dir / "learnings"
        for path in learnings_dir.glob("*.json"):
            data = json.loads(path.read_text())
            assert data is not None

    def test_learnings_file_schema(self, tmp_path):
        memory_dir = tmp_path / "memory"
        obs_dir = memory_dir / "observations"
        (tmp_path / "lib").mkdir()
        (tmp_path / "lib" / "foo.py").write_text("x")

        obs = [make_obs(detail={"files_involved": ["lib/foo.py"]})]
        write_obs_jsonl(obs_dir, "f1", obs)

        synthesize(memory_dir, project_root=tmp_path)

        data = json.loads(
            (memory_dir / "learnings" / "developer-learnings.json").read_text()
        )
        assert "agent" in data
        assert "entries" in data
        assert "token_estimate" in data
        assert "budget" in data
        assert data["agent"] == "developer"

        entry = data["entries"][0]
        assert "id" in entry
        assert "observation_type" in entry
        assert "detail" in entry
        assert "files" in entry
        assert "weight" in entry
        assert "source" in entry
        assert "evidence" in entry

    def test_cross_agent_entries_present(self, tmp_path):
        memory_dir = tmp_path / "memory"
        obs_dir = memory_dir / "observations"
        (tmp_path / "lib").mkdir()
        (tmp_path / "lib" / "foo.py").write_text("x")

        obs = [make_obs(
            obs_type="retry",
            detail={"files_involved": ["lib/foo.py"], "what_happened": "x"},
        )]
        write_obs_jsonl(obs_dir, "f1", obs)

        result = synthesize(memory_dir, project_root=tmp_path)

        # retry → developer (direct) + architect + reviewer (cross-agent)
        assert "architect" in result.entries_by_agent
        assert "reviewer" in result.entries_by_agent
        arch = result.entries_by_agent["architect"][0]
        assert arch.source == "cross_agent"
        assert arch.reframing_context == "downstream_feedback"


# ── Incremental ──────────────────────────────────────────────────────


class TestIncremental:
    def test_skips_when_hash_matches(self, tmp_path):
        memory_dir = tmp_path / "memory"
        obs_dir = memory_dir / "observations"
        (tmp_path / "lib").mkdir()
        (tmp_path / "lib" / "foo.py").write_text("x")

        obs = [make_obs(detail={"files_involved": ["lib/foo.py"]})]
        write_obs_jsonl(obs_dir, "f1", obs)

        # First run
        r1 = synthesize(memory_dir, project_root=tmp_path)
        assert not r1.skipped

        # Second run — same data
        r2 = synthesize(memory_dir, project_root=tmp_path)
        assert r2.skipped

    def test_runs_when_hash_differs(self, tmp_path):
        memory_dir = tmp_path / "memory"
        obs_dir = memory_dir / "observations"
        (tmp_path / "lib").mkdir()
        (tmp_path / "lib" / "foo.py").write_text("x")

        obs = [make_obs(detail={"files_involved": ["lib/foo.py"]})]
        write_obs_jsonl(obs_dir, "f1", obs)

        r1 = synthesize(memory_dir, project_root=tmp_path)
        assert not r1.skipped

        # Add new observation
        obs.append(make_obs(
            task_id="t2",
            detail={"files_involved": ["lib/foo.py"], "what_happened": "new"},
        ))
        write_obs_jsonl(obs_dir, "f1", obs)

        r2 = synthesize(memory_dir, project_root=tmp_path)
        assert not r2.skipped

    def test_first_run_no_meta(self, tmp_path):
        memory_dir = tmp_path / "memory"
        obs_dir = memory_dir / "observations"
        (tmp_path / "lib").mkdir()
        (tmp_path / "lib" / "foo.py").write_text("x")

        obs = [make_obs(detail={"files_involved": ["lib/foo.py"]})]
        write_obs_jsonl(obs_dir, "f1", obs)

        result = synthesize(memory_dir, project_root=tmp_path)
        assert not result.skipped


# ── Real data ────────────────────────────────────────────────────────


class TestRealData:
    """Run synthesis on actual observation data if available."""

    SPEED_OBS = Path(PROJECT_ROOT) / ".speed" / "memory" / "observations"
    TRIBE_OBS = (
        Path(PROJECT_ROOT).parent / "find-my-tribe"
        / ".speed" / "memory" / "observations"
    )

    def _has_obs(self, path):
        return path.exists() and list(path.glob("*.jsonl"))

    @pytest.mark.skipif(
        not (Path(PROJECT_ROOT) / ".speed" / "memory" / "observations").exists(),
        reason="No speed observations available",
    )
    def test_speed_observations(self, tmp_path):
        """Synthesis on speed project observations."""
        import shutil

        memory_dir = tmp_path / "memory"
        obs_dir = memory_dir / "observations"
        obs_dir.mkdir(parents=True)

        for f in self.SPEED_OBS.glob("*.jsonl"):
            shutil.copy(f, obs_dir / f.name)

        result = synthesize(memory_dir, project_root=Path(PROJECT_ROOT))

        assert not result.skipped
        total = sum(len(v) for v in result.entries_by_agent.items())
        print(f"\nSpeed synthesis: {result.summary()}")

    @pytest.mark.skipif(
        not (
            Path(PROJECT_ROOT).parent / "find-my-tribe"
            / ".speed" / "memory" / "observations"
        ).exists(),
        reason="No find-my-tribe observations available",
    )
    def test_tribe_observations(self, tmp_path):
        """Synthesis on find-my-tribe observations."""
        import shutil

        memory_dir = tmp_path / "memory"
        obs_dir = memory_dir / "observations"
        obs_dir.mkdir(parents=True)

        for f in self.TRIBE_OBS.glob("*.jsonl"):
            shutil.copy(f, obs_dir / f.name)

        tribe_root = Path(PROJECT_ROOT).parent / "find-my-tribe"
        result = synthesize(memory_dir, project_root=tribe_root)

        assert not result.skipped
        print(f"\nTribe synthesis: {result.summary()}")

    @pytest.mark.skipif(
        not (Path(PROJECT_ROOT) / ".speed" / "memory" / "observations").exists(),
        reason="No observations available",
    )
    def test_combined_observations(self, tmp_path):
        """Synthesis on all available observations combined."""
        import shutil

        memory_dir = tmp_path / "memory"
        obs_dir = memory_dir / "observations"
        obs_dir.mkdir(parents=True)

        for src in [self.SPEED_OBS, self.TRIBE_OBS]:
            if src.exists():
                for f in src.glob("*.jsonl"):
                    dest = obs_dir / f"{src.parent.parent.parent.name}-{f.name}"
                    shutil.copy(f, dest)

        result = synthesize(memory_dir, project_root=Path(PROJECT_ROOT))

        assert not result.skipped
        print(f"\nCombined synthesis: {result.summary()}")

        # Verify cross-agent entries exist
        has_cross = any(
            e.source == "cross_agent"
            for entries in result.entries_by_agent.values()
            for e in entries
        )
        if any(
            e.observation_type == "retry"
            for entries in result.entries_by_agent.values()
            for e in entries
            if e.source == "direct"
        ):
            assert has_cross, "retry observations should produce cross-agent entries"

        # Verify token budgets
        for agent, entries in result.entries_by_agent.items():
            total = sum(len(json.dumps(e.detail)) // 4 for e in entries)
            budget = _TOKEN_BUDGETS.get(agent, 1000)
            assert total <= budget, f"{agent}: {total} tokens > {budget} budget"


# ── Format Entry Markdown ────────────────────────────────────────────


class TestFormatEntryMarkdown:
    """Tests for _format_entry_markdown."""

    def test_basic_entry(self):
        entry = {
            "observation_type": "retry",
            "files": ["lib/cmd/plan.sh"],
            "detail": {"reason": "timeout", "severity": "high"},
            "evidence": [],
        }
        result = _format_entry_markdown(entry)
        assert result == '- **retry** on `lib/cmd/plan.sh`: reason="timeout", severity="high"'

    def test_no_files(self):
        entry = {
            "observation_type": "guardian_verdict",
            "files": [],
            "detail": {"outcome": "blocked"},
            "evidence": [],
        }
        result = _format_entry_markdown(entry)
        assert "(no files)" in result
        assert result.startswith("- **guardian_verdict** on (no files)")

    def test_skips_internal_keys(self):
        entry = {
            "observation_type": "drift",
            "files": ["src/app.py"],
            "detail": {
                "files_involved": ["a.py", "b.py"],
                "subtype": "internal",
                "source_file": "obs.jsonl",
                "actual_finding": "misaligned",
            },
            "evidence": [],
        }
        result = _format_entry_markdown(entry)
        assert "files_involved" not in result
        assert "subtype" not in result
        assert "source_file" not in result
        assert 'actual_finding="misaligned"' in result

    def test_skips_list_and_dict_values(self):
        entry = {
            "observation_type": "pattern",
            "files": ["lib/foo.py"],
            "detail": {
                "tags": ["a", "b"],
                "nested": {"key": "val"},
                "summary": "works",
            },
            "evidence": [],
        }
        result = _format_entry_markdown(entry)
        assert "tags" not in result
        assert "nested" not in result
        assert 'summary="works"' in result

    def test_caps_detail_at_five_fields(self):
        entry = {
            "observation_type": "pattern",
            "files": ["lib/foo.py"],
            "detail": {f"field_{i}": f"val_{i}" for i in range(8)},
            "evidence": [],
        }
        result = _format_entry_markdown(entry)
        # Count key="value" pairs
        pairs = [p for p in result.split(": ", 1)[1].split(", ") if "=" in p]
        assert len(pairs) <= 5

    def test_cross_agent_tag_and_features(self):
        entry = {
            "observation_type": "retry",
            "files": ["lib/cmd/plan.sh"],
            "detail": {"reason": "timeout"},
            "evidence": [
                {"feature": "auth-flow"},
                {"feature": "auth-flow"},
                {"feature": "user-login"},
            ],
            "reframing_context": "downstream_feedback",
        }
        result = _format_entry_markdown(entry)
        assert "[cross-agent: downstream_feedback]" in result
        assert "(from auth-flow, user-login)" in result


# ── Filter Learnings For Task ────────────────────────────────────────


class TestFilterLearningsForTask:
    """Tests for filter_learnings_for_task."""

    def _write_learnings(self, path: Path, entries: list[dict]) -> None:
        data = {
            "agent": "developer",
            "entries": entries,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))

    def _make_entry(
        self, obs_type: str, files: list[str], weight: float = 1.0, **detail_kwargs
    ) -> dict:
        return {
            "observation_type": obs_type,
            "files": files,
            "detail": detail_kwargs if detail_kwargs else {"summary": "test"},
            "evidence": [{"feature": "feat-1"}],
            "weight": weight,
        }

    def test_direct_file_match(self, tmp_path):
        lpath = tmp_path / "learnings.json"
        self._write_learnings(lpath, [
            self._make_entry("retry", ["lib/cmd/plan.sh", "lib/shared.sh"]),
            self._make_entry("drift", ["lib/other.py"]),
        ])
        result = filter_learnings_for_task(lpath, ["lib/cmd/plan.sh"])
        assert "**retry**" in result
        assert "**drift**" not in result

    def test_directory_match(self, tmp_path):
        lpath = tmp_path / "learnings.json"
        self._write_learnings(lpath, [
            self._make_entry("pattern", ["lib/cmd/build.sh"]),
            self._make_entry("drift", ["src/other.py"]),
        ])
        result = filter_learnings_for_task(lpath, ["lib/cmd/deploy.sh"])
        assert "**pattern**" in result
        assert "**drift**" not in result

    def test_no_match_falls_back_to_top_3_by_weight(self, tmp_path):
        lpath = tmp_path / "learnings.json"
        entries = [
            self._make_entry("a", ["unrelated/x.py"], weight=5.0),
            self._make_entry("b", ["unrelated/y.py"], weight=3.0),
            self._make_entry("c", ["unrelated/z.py"], weight=1.0),
            self._make_entry("d", ["unrelated/w.py"], weight=0.5),
        ]
        self._write_learnings(lpath, entries)
        result = filter_learnings_for_task(lpath, ["totally/different.py"])
        assert "**a**" in result
        assert "**b**" in result
        assert "**c**" in result
        assert "**d**" not in result

    def test_missing_file_returns_empty(self, tmp_path):
        lpath = tmp_path / "nonexistent.json"
        result = filter_learnings_for_task(lpath, ["lib/foo.py"])
        assert result == ""

    def test_malformed_json_returns_empty(self, tmp_path):
        lpath = tmp_path / "bad.json"
        lpath.write_text("{not valid json!!")
        result = filter_learnings_for_task(lpath, ["lib/foo.py"])
        assert result == ""

    def test_empty_entries_returns_empty(self, tmp_path):
        lpath = tmp_path / "learnings.json"
        self._write_learnings(lpath, [])
        result = filter_learnings_for_task(lpath, ["lib/foo.py"])
        assert result == ""

    def test_invalid_structure_returns_empty(self, tmp_path):
        lpath = tmp_path / "learnings.json"
        lpath.write_text(json.dumps([{"not": "a dict"}]))
        result = filter_learnings_for_task(lpath, ["lib/foo.py"])
        assert result == ""

    def test_mixed_direct_and_directory_no_dupes(self, tmp_path):
        lpath = tmp_path / "learnings.json"
        self._write_learnings(lpath, [
            self._make_entry("retry", ["lib/cmd/plan.sh", "lib/cmd/build.sh"]),
            self._make_entry("drift", ["lib/cmd/other.sh"]),
            self._make_entry("pattern", ["src/unrelated.py"]),
        ])
        # plan.sh matches directly; other.sh matches via directory lib/cmd
        result = filter_learnings_for_task(lpath, ["lib/cmd/plan.sh"])
        assert "**retry**" in result
        assert "**drift**" in result
        assert "**pattern**" not in result
        # retry should appear only once
        assert result.count("**retry**") == 1
