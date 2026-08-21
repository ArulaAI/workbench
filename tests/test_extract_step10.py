#!/usr/bin/env python3
"""Tests for Step 10: Pattern Detection — against real extract.py."""

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from learn.extract import (
    detect_patterns,
    _obs_files_key,
    _obs_category,
    _make_obs,
    Observation,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_obs(feature, obs_type, task_id="1", detail=None, stage="reviewer"):
    return _make_obs(feature, stage, task_id, obs_type, detail or {})


def write_prior(prior_dir, feature, observations):
    """Write observations to a prior JSONL file."""
    prior_dir.mkdir(parents=True, exist_ok=True)
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
    (prior_dir / f"{feature}.jsonl").write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# 1. _obs_files_key helper
# ---------------------------------------------------------------------------

class TestObsFilesKey:
    def test_list_sorted(self):
        obs = make_obs("f", "retry", detail={"files_involved": ["b.py", "a.py"]})
        assert _obs_files_key(obs) == ("a.py", "b.py")

    def test_string_file(self):
        obs = make_obs("f", "retry", detail={"file": "a.py"})
        assert _obs_files_key(obs) == ("a.py",)

    def test_empty(self):
        obs = make_obs("f", "retry", detail={})
        assert _obs_files_key(obs) == ()

    def test_empty_string(self):
        obs = make_obs("f", "retry", detail={"file": ""})
        assert _obs_files_key(obs) == ()

    def test_empty_list(self):
        obs = make_obs("f", "retry", detail={"files_involved": []})
        assert _obs_files_key(obs) == ()


# ---------------------------------------------------------------------------
# 2. _obs_category helper
# ---------------------------------------------------------------------------

class TestObsCategory:
    def test_category_field(self):
        obs = make_obs("f", "retry", detail={"category": "timeout"})
        assert _obs_category(obs) == "timeout"

    def test_finding_type_fallback(self):
        obs = make_obs("f", "retry", detail={"finding_type": "spec_drift"})
        assert _obs_category(obs) == "spec_drift"

    def test_issue_type_fallback(self):
        obs = make_obs("f", "retry", detail={"issue_type": "mismatch"})
        assert _obs_category(obs) == "mismatch"

    def test_empty(self):
        obs = make_obs("f", "retry", detail={})
        assert _obs_category(obs) == ""

    def test_category_takes_precedence(self):
        obs = make_obs("f", "retry", detail={
            "category": "cat", "finding_type": "ft"})
        assert _obs_category(obs) == "cat"


# ---------------------------------------------------------------------------
# 3. Below min_features threshold
# ---------------------------------------------------------------------------

class TestBelowThreshold:
    def test_one_feature(self):
        current = [make_obs("feat-a", "retry")]
        with tempfile.TemporaryDirectory() as tmpdir:
            assert detect_patterns(current, Path(tmpdir)) == []

    def test_two_features(self):
        current = [make_obs("feat-a", "retry")]
        with tempfile.TemporaryDirectory() as tmpdir:
            prior = Path(tmpdir)
            write_prior(prior, "feat-b", [make_obs("feat-b", "retry")])
            assert detect_patterns(current, prior) == []

    def test_empty_current(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            assert detect_patterns([], Path(tmpdir)) == []

    def test_nonexistent_prior_dir(self):
        current = [make_obs("feat-a", "retry")]
        assert detect_patterns(current, Path("/nonexistent")) == []


# ---------------------------------------------------------------------------
# 4. Pass 2: type-level patterns (different files across features)
# ---------------------------------------------------------------------------

class TestTypeLevelPatterns:
    def test_same_type_different_files_detected(self):
        """Retries on different files across 3 features should produce a pattern."""
        current = [make_obs("feat-c", "retry", detail={
            "files_involved": ["c.py"]})]
        with tempfile.TemporaryDirectory() as tmpdir:
            prior = Path(tmpdir)
            write_prior(prior, "feat-a", [make_obs("feat-a", "retry", detail={
                "files_involved": ["a.py"]})])
            write_prior(prior, "feat-b", [make_obs("feat-b", "retry", detail={
                "files_involved": ["b.py"]})])
            patterns = detect_patterns(current, prior)
        assert len(patterns) == 1
        assert patterns[0].observation_type == "pattern_match"
        assert "retry" in patterns[0].detail["pattern"]

    def test_category_splits_groups(self):
        """Same type but different categories should not merge."""
        current = [make_obs("feat-c", "reviewer_finding", detail={
            "category": "correctness"})]
        with tempfile.TemporaryDirectory() as tmpdir:
            prior = Path(tmpdir)
            write_prior(prior, "feat-a", [make_obs("feat-a", "reviewer_finding",
                        detail={"category": "correctness"})])
            write_prior(prior, "feat-b", [make_obs("feat-b", "reviewer_finding",
                        detail={"category": "style"})])
            patterns = detect_patterns(current, prior)
        # Only 2 features have "correctness", 1 has "style" — neither reaches 3
        assert len(patterns) == 0

    def test_same_category_across_3_features(self):
        current = [make_obs("feat-c", "reviewer_finding", detail={
            "category": "unclassified", "files_involved": ["z.py"]})]
        with tempfile.TemporaryDirectory() as tmpdir:
            prior = Path(tmpdir)
            write_prior(prior, "feat-a", [make_obs("feat-a", "reviewer_finding",
                        detail={"category": "unclassified",
                                "files_involved": ["a.py"]})])
            write_prior(prior, "feat-b", [make_obs("feat-b", "reviewer_finding",
                        detail={"category": "unclassified",
                                "files_involved": ["b.py"]})])
            patterns = detect_patterns(current, prior)
        assert len(patterns) == 1
        assert "unclassified" in patterns[0].detail["pattern"]


# ---------------------------------------------------------------------------
# 5. Pass 1: file-specific patterns
# ---------------------------------------------------------------------------

class TestFileSpecificPatterns:
    def test_same_file_across_3_features(self):
        """Same file causing retries across 3 features should produce a
        file-specific pattern in Pass 1."""
        current = [make_obs("feat-c", "retry", detail={
            "files_involved": ["shared.py"]})]
        with tempfile.TemporaryDirectory() as tmpdir:
            prior = Path(tmpdir)
            write_prior(prior, "feat-a", [make_obs("feat-a", "retry", detail={
                "files_involved": ["shared.py"]})])
            write_prior(prior, "feat-b", [make_obs("feat-b", "retry", detail={
                "files_involved": ["shared.py"]})])
            patterns = detect_patterns(current, prior)
        assert len(patterns) == 1
        assert "shared.py" in patterns[0].detail["pattern"]

    def test_file_specific_prevents_double_count(self):
        """If all observations share the same file, Pass 1 covers them
        and Pass 2 should not produce a duplicate."""
        current = [make_obs("feat-c", "retry", detail={
            "files_involved": ["shared.py"]})]
        with tempfile.TemporaryDirectory() as tmpdir:
            prior = Path(tmpdir)
            write_prior(prior, "feat-a", [make_obs("feat-a", "retry", detail={
                "files_involved": ["shared.py"]})])
            write_prior(prior, "feat-b", [make_obs("feat-b", "retry", detail={
                "files_involved": ["shared.py"]})])
            patterns = detect_patterns(current, prior)
        # Only 1 pattern, not 2
        assert len(patterns) == 1

    def test_mixed_file_specific_and_type_level(self):
        """Some retries on shared.py (Pass 1) and some on different files
        (Pass 2). Should produce 2 patterns if both cross threshold."""
        current = [
            make_obs("feat-c", "retry", detail={
                "files_involved": ["shared.py"]}),
            make_obs("feat-c", "gate_failure", detail={
                "files_involved": ["c_other.py"]}),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            prior = Path(tmpdir)
            write_prior(prior, "feat-a", [
                make_obs("feat-a", "retry", detail={
                    "files_involved": ["shared.py"]}),
                make_obs("feat-a", "gate_failure", detail={
                    "files_involved": ["a_other.py"]}),
            ])
            write_prior(prior, "feat-b", [
                make_obs("feat-b", "retry", detail={
                    "files_involved": ["shared.py"]}),
                make_obs("feat-b", "gate_failure", detail={
                    "files_involved": ["b_other.py"]}),
            ])
            patterns = detect_patterns(current, prior)
        types = {p.detail["pattern"].split(" on ")[0] for p in patterns}
        assert "retry" in types
        assert "gate_failure" in types
        assert len(patterns) == 2


# ---------------------------------------------------------------------------
# 6. Excluded observation types
# ---------------------------------------------------------------------------

class TestExcludedTypes:
    def test_success_excluded(self):
        current = [make_obs("feat-c", "success")]
        with tempfile.TemporaryDirectory() as tmpdir:
            prior = Path(tmpdir)
            write_prior(prior, "feat-a", [make_obs("feat-a", "success")])
            write_prior(prior, "feat-b", [make_obs("feat-b", "success")])
            patterns = detect_patterns(current, prior)
        assert len(patterns) == 0

    def test_pattern_match_excluded(self):
        current = [make_obs("feat-c", "pattern_match")]
        with tempfile.TemporaryDirectory() as tmpdir:
            prior = Path(tmpdir)
            write_prior(prior, "feat-a", [make_obs("feat-a", "pattern_match")])
            write_prior(prior, "feat-b", [make_obs("feat-b", "pattern_match")])
            patterns = detect_patterns(current, prior)
        assert len(patterns) == 0


# ---------------------------------------------------------------------------
# 7. Severity and weight
# ---------------------------------------------------------------------------

class TestSeverityWeight:
    def test_medium_at_3_features(self):
        current = [make_obs("feat-c", "retry")]
        with tempfile.TemporaryDirectory() as tmpdir:
            prior = Path(tmpdir)
            write_prior(prior, "feat-a", [make_obs("feat-a", "retry")])
            write_prior(prior, "feat-b", [make_obs("feat-b", "retry")])
            patterns = detect_patterns(current, prior)
        assert patterns[0].detail["severity"] == "medium"
        assert patterns[0].weight == 2.0

    def test_medium_at_4_features(self):
        current = [make_obs("feat-d", "retry")]
        with tempfile.TemporaryDirectory() as tmpdir:
            prior = Path(tmpdir)
            write_prior(prior, "feat-a", [make_obs("feat-a", "retry")])
            write_prior(prior, "feat-b", [make_obs("feat-b", "retry")])
            write_prior(prior, "feat-c", [make_obs("feat-c", "retry")])
            patterns = detect_patterns(current, prior)
        assert patterns[0].detail["severity"] == "medium"
        assert patterns[0].weight == 2.0

    def test_high_at_5_features(self):
        current = [make_obs("feat-e", "retry")]
        with tempfile.TemporaryDirectory() as tmpdir:
            prior = Path(tmpdir)
            for f in ["feat-a", "feat-b", "feat-c", "feat-d"]:
                write_prior(prior, f, [make_obs(f, "retry")])
            patterns = detect_patterns(current, prior)
        assert patterns[0].detail["severity"] == "high"
        assert patterns[0].weight == 3.0


# ---------------------------------------------------------------------------
# 8. Common properties
# ---------------------------------------------------------------------------

class TestCommonProperties:
    def test_observation_type_is_pattern_match(self):
        current = [make_obs("feat-c", "retry")]
        with tempfile.TemporaryDirectory() as tmpdir:
            prior = Path(tmpdir)
            write_prior(prior, "feat-a", [make_obs("feat-a", "retry")])
            write_prior(prior, "feat-b", [make_obs("feat-b", "retry")])
            patterns = detect_patterns(current, prior)
        assert all(p.observation_type == "pattern_match" for p in patterns)

    def test_task_id_is_star(self):
        current = [make_obs("feat-c", "retry")]
        with tempfile.TemporaryDirectory() as tmpdir:
            prior = Path(tmpdir)
            write_prior(prior, "feat-a", [make_obs("feat-a", "retry")])
            write_prior(prior, "feat-b", [make_obs("feat-b", "retry")])
            patterns = detect_patterns(current, prior)
        assert all(p.task_id == "*" for p in patterns)

    def test_stage_is_meta(self):
        current = [make_obs("feat-c", "retry")]
        with tempfile.TemporaryDirectory() as tmpdir:
            prior = Path(tmpdir)
            write_prior(prior, "feat-a", [make_obs("feat-a", "retry")])
            write_prior(prior, "feat-b", [make_obs("feat-b", "retry")])
            patterns = detect_patterns(current, prior)
        assert all(p.stage == "meta" for p in patterns)

    def test_feature_from_current(self):
        current = [make_obs("my-feature", "retry")]
        with tempfile.TemporaryDirectory() as tmpdir:
            prior = Path(tmpdir)
            write_prior(prior, "feat-a", [make_obs("feat-a", "retry")])
            write_prior(prior, "feat-b", [make_obs("feat-b", "retry")])
            patterns = detect_patterns(current, prior)
        assert all(p.feature == "my-feature" for p in patterns)

    def test_frequency_string(self):
        current = [make_obs("feat-c", "retry")]
        with tempfile.TemporaryDirectory() as tmpdir:
            prior = Path(tmpdir)
            write_prior(prior, "feat-a", [make_obs("feat-a", "retry")])
            write_prior(prior, "feat-b", [make_obs("feat-b", "retry")])
            patterns = detect_patterns(current, prior)
        assert patterns[0].detail["frequency"] == "3 of last 3 features"

    def test_occurrences_have_required_fields(self):
        current = [make_obs("feat-c", "retry")]
        with tempfile.TemporaryDirectory() as tmpdir:
            prior = Path(tmpdir)
            write_prior(prior, "feat-a", [make_obs("feat-a", "retry")])
            write_prior(prior, "feat-b", [make_obs("feat-b", "retry")])
            patterns = detect_patterns(current, prior)
        for occ in patterns[0].detail["occurrences"]:
            assert "feature" in occ
            assert "task_id" in occ
            assert "observation_id" in occ


# ---------------------------------------------------------------------------
# 9. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_malformed_prior_jsonl(self):
        current = [make_obs("feat-c", "retry")]
        with tempfile.TemporaryDirectory() as tmpdir:
            prior = Path(tmpdir)
            write_prior(prior, "feat-a", [make_obs("feat-a", "retry")])
            write_prior(prior, "feat-b", [make_obs("feat-b", "retry")])
            # Add a malformed file
            (prior / "feat-bad.jsonl").write_text("not json\n{broken\n")
            patterns = detect_patterns(current, prior)
        # Still works — malformed file ignored
        assert len(patterns) == 1

    def test_empty_prior_file(self):
        current = [make_obs("feat-c", "retry")]
        with tempfile.TemporaryDirectory() as tmpdir:
            prior = Path(tmpdir)
            write_prior(prior, "feat-a", [make_obs("feat-a", "retry")])
            write_prior(prior, "feat-b", [make_obs("feat-b", "retry")])
            (prior / "feat-empty.jsonl").write_text("")
            patterns = detect_patterns(current, prior)
        assert len(patterns) == 1

    def test_idempotency(self):
        current = [make_obs("feat-c", "retry")]
        with tempfile.TemporaryDirectory() as tmpdir:
            prior = Path(tmpdir)
            write_prior(prior, "feat-a", [make_obs("feat-a", "retry")])
            write_prior(prior, "feat-b", [make_obs("feat-b", "retry")])
            p1 = detect_patterns(current, prior)
            p2 = detect_patterns(current, prior)
        assert [p.detail["pattern"] for p in p1] == \
               [p.detail["pattern"] for p in p2]

    def test_custom_min_features(self):
        current = [make_obs("feat-b", "retry")]
        with tempfile.TemporaryDirectory() as tmpdir:
            prior = Path(tmpdir)
            write_prior(prior, "feat-a", [make_obs("feat-a", "retry")])
            # 2 features, min_features=2 should fire
            patterns = detect_patterns(current, prior, min_features=2)
        assert len(patterns) == 1


# ---------------------------------------------------------------------------
# 10. Real data: find-your-tribe + speed combined (4 features → 2 patterns)
# ---------------------------------------------------------------------------

class TestRealCombined:
    @pytest.fixture
    def patterns(self):
        """Load observations from both projects into a combined run.

        find-your-tribe has 3 feature files but seed-onboarding-flag only
        has a success observation (excluded from grouping). speed has
        speed-security. Combined: 4 features, 3 with groupable observations.
        """
        fyt_dir = Path("/Users/sanjay.kotagiri/Documents/code/tmp"
                        "/find-your-tribe/.speed/memory/observations")
        speed_dir = Path(".speed/memory/observations")
        if not fyt_dir.is_dir():
            pytest.skip("find-your-tribe observations not available")
        if not speed_dir.is_dir():
            pytest.skip("speed observations not available")

        # Load all observations from both projects
        all_obs = []
        for obs_dir in [fyt_dir, speed_dir]:
            for f in obs_dir.glob("*.jsonl"):
                with open(f) as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            all_obs.append(Observation(**json.loads(line)))
                        except (json.JSONDecodeError, TypeError):
                            continue

        if not all_obs:
            pytest.skip("no observations loaded")

        # Use all as "current" with empty prior (detect_patterns merges them)
        return detect_patterns(all_obs, Path("/nonexistent"))

    def test_patterns_detected(self, patterns):
        assert len(patterns) >= 2

    def test_retry_pattern(self, patterns):
        retry_patterns = [p for p in patterns
                         if "retry" in p.detail["pattern"]]
        assert len(retry_patterns) == 1

    def test_reviewer_finding_pattern(self, patterns):
        reviewer_patterns = [p for p in patterns
                            if "reviewer_finding" in p.detail["pattern"]]
        assert len(reviewer_patterns) >= 1

    def test_all_medium_severity(self, patterns):
        # 3-4 features → medium
        assert all(p.detail["severity"] == "medium" for p in patterns)

    def test_all_weight_2(self, patterns):
        assert all(p.weight == 2.0 for p in patterns)


# ---------------------------------------------------------------------------
# 11. Real data: speed alone (1 feature → no patterns)
# ---------------------------------------------------------------------------

class TestRealSpeedAlone:
    def test_insufficient_features(self):
        prior_dir = Path(".speed/memory/observations")
        if not prior_dir.is_dir():
            pytest.skip("speed observations not available")
        files = list(prior_dir.glob("*.jsonl"))
        if len(files) >= 3:
            pytest.skip("speed now has 3+ features, test no longer applicable")
        current = [make_obs("test-feature", "retry")]
        patterns = detect_patterns(current, prior_dir)
        assert len(patterns) == 0
