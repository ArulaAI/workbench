#!/usr/bin/env python3
"""Tests for lib/learn/convention_observations.py — Phase B observation integration."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.learn.conventions import RawPattern
from lib.learn.convention_observations import _integrate_observations


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_pattern(
    pat_type: str = "naming_snake",
    scope: list[str] | None = None,
    adherence: float = 0.9,
    evidence: str = "10 of 11 use it",
    observation_support: int = 0,
) -> RawPattern:
    return RawPattern(
        type=pat_type,
        files=["lib/foo.py"],
        scope=scope if scope is not None else ["lib/"],
        adherence=adherence,
        evidence=evidence,
        observation_support=observation_support,
    )


def write_obs(obs_dir: Path, filename: str, observations: list[dict]) -> None:
    obs_dir.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(obs) for obs in observations]
    (obs_dir / filename).write_text("\n".join(lines) + "\n")


def violation(file: str) -> dict:
    return {"observation_type": "convention_violation", "detail": {"file": file}}


def reviewer(file: str, category: str = "convention") -> dict:
    return {
        "observation_type": "reviewer_finding",
        "detail": {"category": category, "file": file},
    }


def override(file: str, change_category: str = "convention") -> dict:
    return {
        "observation_type": "human_override",
        "detail": {"change_category": change_category, "file": file},
    }


# ---------------------------------------------------------------------------
# 1. Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_obs_dir_returns_unchanged(self, tmp_path):
        obs_dir = tmp_path / "observations"
        obs_dir.mkdir()
        patterns = [make_pattern()]
        result = _integrate_observations(patterns, obs_dir)
        assert result[0] is patterns[0]

    def test_no_jsonl_files_returns_unchanged(self, tmp_path):
        obs_dir = tmp_path / "observations"
        obs_dir.mkdir()
        (obs_dir / "notes.txt").write_text("not a jsonl file")
        patterns = [make_pattern()]
        result = _integrate_observations(patterns, obs_dir)
        assert result[0] is patterns[0]

    def test_missing_obs_dir_returns_unchanged(self, tmp_path):
        obs_dir = tmp_path / "nonexistent"
        patterns = [make_pattern()]
        result = _integrate_observations(patterns, obs_dir)
        assert result[0] is patterns[0]

    def test_all_malformed_lines_returns_unchanged(self, tmp_path):
        obs_dir = tmp_path / "observations"
        obs_dir.mkdir()
        (obs_dir / "test.jsonl").write_text("not json\n{broken}\n")
        patterns = [make_pattern()]
        result = _integrate_observations(patterns, obs_dir)
        assert result[0] is patterns[0]

    def test_malformed_lines_skipped_valid_processed(self, tmp_path):
        """Malformed lines are warned and skipped; valid lines still run."""
        obs_dir = tmp_path / "observations"
        valid = json.dumps(violation("lib/foo.py"))
        obs_dir.mkdir()
        (obs_dir / "test.jsonl").write_text(
            "not json\n"
            + "{broken\n"
            + valid
            + "\n"
            + valid
            + "\n"
            + valid
            + "\n"
        )
        patterns = [make_pattern()]
        result = _integrate_observations(patterns, obs_dir)
        # 3 valid violations → support incremented
        assert result[0].observation_support == 3

    def test_empty_patterns_list(self, tmp_path):
        """No existing patterns; observation-only patterns get created."""
        obs_dir = tmp_path / "observations"
        write_obs(obs_dir, "f.jsonl", [override("src/new.py")])
        result = _integrate_observations([], obs_dir)
        assert len(result) == 1

    def test_no_relevant_obs_returns_unchanged(self, tmp_path):
        """Observations with irrelevant types leave patterns untouched."""
        obs_dir = tmp_path / "observations"
        write_obs(obs_dir, "f.jsonl", [
            {"observation_type": "retry", "detail": {"file": "lib/foo.py"}},
        ])
        patterns = [make_pattern()]
        result = _integrate_observations(patterns, obs_dir)
        assert result[0] is patterns[0]


# ---------------------------------------------------------------------------
# 2. convention_violation observations
# ---------------------------------------------------------------------------


class TestConventionViolation:
    def test_3_violations_increment_support(self, tmp_path):
        obs_dir = tmp_path / "observations"
        write_obs(obs_dir, "f.jsonl", [
            violation("lib/a.py"),
            violation("lib/b.py"),
            violation("lib/c.py"),
        ])
        pattern = make_pattern(scope=["lib/"])
        result = _integrate_observations([pattern], obs_dir)
        assert result[0].observation_support == 3

    def test_2_violations_below_threshold_no_increment(self, tmp_path):
        obs_dir = tmp_path / "observations"
        write_obs(obs_dir, "f.jsonl", [
            violation("lib/a.py"),
            violation("lib/b.py"),
        ])
        pattern = make_pattern(scope=["lib/"])
        result = _integrate_observations([pattern], obs_dir)
        assert result[0].observation_support == 0

    def test_5_violations_increment_by_5(self, tmp_path):
        obs_dir = tmp_path / "observations"
        write_obs(obs_dir, "f.jsonl", [violation(f"lib/{c}.py") for c in "abcde"])
        pattern = make_pattern(scope=["lib/"])
        result = _integrate_observations([pattern], obs_dir)
        assert result[0].observation_support == 5

    def test_out_of_scope_violations_no_increment(self, tmp_path):
        obs_dir = tmp_path / "observations"
        write_obs(obs_dir, "f.jsonl", [
            violation("src/a.py"),
            violation("src/b.py"),
            violation("src/c.py"),
        ])
        pattern = make_pattern(scope=["lib/"])
        result = _integrate_observations([pattern], obs_dir)
        assert result[0].observation_support == 0

    def test_out_of_scope_violations_become_observation_only(self, tmp_path):
        """Unmatched violations create a new observation-only pattern."""
        obs_dir = tmp_path / "observations"
        write_obs(obs_dir, "f.jsonl", [
            violation("src/a.py"),
            violation("src/b.py"),
            violation("src/c.py"),
        ])
        pattern = make_pattern(scope=["lib/"])
        result = _integrate_observations([pattern], obs_dir)
        # Original pattern unchanged + 1 new observation-only pattern
        assert len(result) == 2
        new_pat = result[1]
        assert new_pat.evidence == "N/A — observation-derived"

    def test_accumulated_support_with_existing(self, tmp_path):
        """Violations add to an already-nonzero observation_support."""
        obs_dir = tmp_path / "observations"
        write_obs(obs_dir, "f.jsonl", [
            violation("lib/a.py"),
            violation("lib/b.py"),
            violation("lib/c.py"),
        ])
        pattern = make_pattern(scope=["lib/"], observation_support=2)
        result = _integrate_observations([pattern], obs_dir)
        assert result[0].observation_support == 5


# ---------------------------------------------------------------------------
# 3. human_override observations
# ---------------------------------------------------------------------------


class TestHumanOverride:
    def test_override_convention_creates_new_pattern_when_no_match(self, tmp_path):
        obs_dir = tmp_path / "observations"
        write_obs(obs_dir, "f.jsonl", [override("src/new.py", "convention")])
        result = _integrate_observations([], obs_dir)
        assert len(result) == 1
        assert result[0].evidence == "N/A — observation-derived"
        assert result[0].observation_support == 1

    def test_override_style_creates_new_pattern_when_no_match(self, tmp_path):
        obs_dir = tmp_path / "observations"
        write_obs(obs_dir, "f.jsonl", [override("src/new.py", "style")])
        result = _integrate_observations([], obs_dir)
        assert len(result) == 1
        assert result[0].evidence == "N/A — observation-derived"

    def test_override_other_category_ignored(self, tmp_path):
        obs_dir = tmp_path / "observations"
        write_obs(obs_dir, "f.jsonl", [override("src/new.py", "bugfix")])
        result = _integrate_observations([], obs_dir)
        assert len(result) == 0

    def test_override_increments_existing_matching_pattern(self, tmp_path):
        obs_dir = tmp_path / "observations"
        write_obs(obs_dir, "f.jsonl", [override("lib/foo.py", "convention")])
        pattern = make_pattern(scope=["lib/"])
        result = _integrate_observations([pattern], obs_dir)
        assert result[0].observation_support == 1
        # Matched → no new observation-only pattern
        assert len(result) == 1

    def test_multiple_overrides_grouped_into_one_pattern(self, tmp_path):
        """Two unmatched overrides with same key → single new pattern."""
        obs_dir = tmp_path / "observations"
        write_obs(obs_dir, "f.jsonl", [
            override("new/a.py", "convention"),
            override("new/b.py", "convention"),
        ])
        result = _integrate_observations([], obs_dir)
        assert len(result) == 1
        assert result[0].observation_support == 2


# ---------------------------------------------------------------------------
# 4. reviewer_finding observations
# ---------------------------------------------------------------------------


class TestReviewerFinding:
    def test_convention_finding_increments_existing_pattern(self, tmp_path):
        obs_dir = tmp_path / "observations"
        write_obs(obs_dir, "f.jsonl", [reviewer("lib/foo.py", "convention")])
        pattern = make_pattern(scope=["lib/"])
        result = _integrate_observations([pattern], obs_dir)
        assert result[0].observation_support == 1

    def test_non_convention_finding_ignored(self, tmp_path):
        obs_dir = tmp_path / "observations"
        write_obs(obs_dir, "f.jsonl", [reviewer("lib/foo.py", "correctness")])
        pattern = make_pattern(scope=["lib/"])
        result = _integrate_observations([pattern], obs_dir)
        assert result[0].observation_support == 0
        assert result[0] is pattern

    def test_convention_finding_creates_obs_only_when_no_match(self, tmp_path):
        obs_dir = tmp_path / "observations"
        write_obs(obs_dir, "f.jsonl", [reviewer("src/new.py", "convention")])
        result = _integrate_observations([], obs_dir)
        assert len(result) == 1
        assert result[0].evidence == "N/A — observation-derived"

    def test_multiple_findings_increment_by_count(self, tmp_path):
        obs_dir = tmp_path / "observations"
        write_obs(obs_dir, "f.jsonl", [
            reviewer("lib/a.py"),
            reviewer("lib/b.py"),
        ])
        pattern = make_pattern(scope=["lib/"])
        result = _integrate_observations([pattern], obs_dir)
        assert result[0].observation_support == 2


# ---------------------------------------------------------------------------
# 5. Object identity — unmatched patterns pass through unchanged
# ---------------------------------------------------------------------------


class TestObjectIdentity:
    def test_unmatched_pattern_is_same_object(self, tmp_path):
        obs_dir = tmp_path / "observations"
        write_obs(obs_dir, "f.jsonl", [reviewer("src/foo.py")])
        pattern = make_pattern(scope=["lib/"])  # won't match src/
        result = _integrate_observations([pattern], obs_dir)
        assert result[0] is pattern
        assert result[0].observation_support == 0

    def test_matched_pattern_is_new_object(self, tmp_path):
        obs_dir = tmp_path / "observations"
        write_obs(obs_dir, "f.jsonl", [reviewer("lib/foo.py")])
        pattern = make_pattern(scope=["lib/"])
        result = _integrate_observations([pattern], obs_dir)
        assert result[0] is not pattern

    def test_mix_matched_and_unmatched(self, tmp_path):
        """Only matched patterns get replaced; others keep identity."""
        obs_dir = tmp_path / "observations"
        write_obs(obs_dir, "f.jsonl", [reviewer("lib/foo.py")])
        p_match = make_pattern("p1", scope=["lib/"])
        p_no_match = make_pattern("p2", scope=["src/"])
        result = _integrate_observations([p_match, p_no_match], obs_dir)
        assert result[0] is not p_match
        assert result[1] is p_no_match


# ---------------------------------------------------------------------------
# 6. Observation-derived pattern fields
# ---------------------------------------------------------------------------


class TestObservationDerivedPatterns:
    def test_evidence_field_is_na_observation_derived(self, tmp_path):
        obs_dir = tmp_path / "observations"
        write_obs(obs_dir, "f.jsonl", [override("new/thing.py")])
        result = _integrate_observations([], obs_dir)
        assert result[0].evidence == "N/A — observation-derived"

    def test_adherence_is_zero(self, tmp_path):
        obs_dir = tmp_path / "observations"
        write_obs(obs_dir, "f.jsonl", [override("new/a.py")])
        result = _integrate_observations([], obs_dir)
        assert result[0].adherence == 0.0

    def test_observation_support_equals_count(self, tmp_path):
        obs_dir = tmp_path / "observations"
        write_obs(obs_dir, "f.jsonl", [
            override("new/a.py"),
            override("new/b.py"),
            override("new/c.py"),
        ])
        result = _integrate_observations([], obs_dir)
        assert result[0].observation_support == 3

    def test_scope_derived_from_file_paths(self, tmp_path):
        obs_dir = tmp_path / "observations"
        write_obs(obs_dir, "f.jsonl", [override("lib/foo.py")])
        # No existing pattern that covers lib/ — creates observation-only pattern
        result = _integrate_observations([make_pattern(scope=["src/"])], obs_dir)
        obs_only = [p for p in result if p.evidence == "N/A — observation-derived"]
        assert len(obs_only) == 1
        assert "lib/" in obs_only[0].scope

    def test_different_types_create_separate_patterns(self, tmp_path):
        """Different observation types produce separate observation-only patterns."""
        obs_dir = tmp_path / "observations"
        write_obs(obs_dir, "f.jsonl", [
            override("new/a.py", "convention"),
            reviewer("new/b.py", "convention"),
        ])
        result = _integrate_observations([], obs_dir)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# 7. Multiple JSONL files
# ---------------------------------------------------------------------------


class TestMultipleFiles:
    def test_reads_across_multiple_files(self, tmp_path):
        obs_dir = tmp_path / "observations"
        write_obs(obs_dir, "feat-a.jsonl", [violation("lib/a.py")])
        write_obs(obs_dir, "feat-b.jsonl", [violation("lib/b.py")])
        write_obs(obs_dir, "feat-c.jsonl", [violation("lib/c.py")])
        pattern = make_pattern(scope=["lib/"])
        result = _integrate_observations([pattern], obs_dir)
        assert result[0].observation_support == 3

    def test_malformed_file_skipped_others_processed(self, tmp_path):
        obs_dir = tmp_path / "observations"
        write_obs(obs_dir, "feat-a.jsonl", [violation("lib/a.py")])
        write_obs(obs_dir, "feat-b.jsonl", [violation("lib/b.py")])
        write_obs(obs_dir, "feat-c.jsonl", [violation("lib/c.py")])
        obs_dir.mkdir(exist_ok=True)
        (obs_dir / "bad.jsonl").write_text("not json at all\n")
        pattern = make_pattern(scope=["lib/"])
        result = _integrate_observations([pattern], obs_dir)
        assert result[0].observation_support == 3
