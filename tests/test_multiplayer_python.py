"""Tests for multiplayer Python modules: proposals and merge."""

import json
import sys
import tempfile
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.learn.proposals import write_proposal, ProposalResult
from lib.learn.merge import (
    merge_proposals,
    compute_confidence,
    MergeResult,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_HIGH,
    CONFIDENCE_LOCKED,
)


def test_write_proposal():
    """write_proposal creates a valid JSON file with correct structure."""
    with tempfile.TemporaryDirectory() as tmpdir:
        proposals_dir = Path(tmpdir) / "proposals"

        observations = [
            {"id": "obs-1", "type": "retry", "detail": {"task_id": "1"}},
            {"id": "obs-2", "type": "gate_failure", "detail": {"gate": "lint"}},
        ]
        conventions = [
            {"key": "naming_snake", "value": "Use snake_case for functions"},
        ]

        result = write_proposal(observations, conventions, "auth", "alice", proposals_dir)

        assert isinstance(result, ProposalResult)
        assert result.observation_count == 2
        assert result.convention_count == 1
        assert result.feature == "auth"
        assert result.actor == "alice"
        assert result.path.exists()

        data = json.loads(result.path.read_text())
        assert data["status"] == "pending"
        assert data["actor"] == "alice"
        assert data["feature"] == "auth"
        assert len(data["observations"]) == 2
        assert len(data["conventions"]) == 1

    print("PASS: test_write_proposal")


def test_merge_proposals_auto_merge():
    """Non-conflicting conventions are auto-merged."""
    with tempfile.TemporaryDirectory() as tmpdir:
        proposals_dir = Path(tmpdir) / "proposals"
        knowledge_dir = Path(tmpdir) / "knowledge"
        proposals_dir.mkdir(parents=True)
        knowledge_dir.mkdir(parents=True)

        # Write two proposals with different conventions
        p1 = {
            "timestamp": "2026-03-22T10:00:00Z",
            "actor": "alice",
            "feature": "auth",
            "observations": [],
            "conventions": [{"key": "naming", "value": "snake_case"}],
            "status": "pending",
        }
        p2 = {
            "timestamp": "2026-03-22T11:00:00Z",
            "actor": "bob",
            "feature": "dashboard",
            "observations": [],
            "conventions": [{"key": "testing", "value": "use pytest"}],
            "status": "pending",
        }
        (proposals_dir / "p1.json").write_text(json.dumps(p1))
        (proposals_dir / "p2.json").write_text(json.dumps(p2))

        result = merge_proposals(proposals_dir, knowledge_dir)

        assert result.merged == 2
        assert result.conflicted == 0
        assert result.proposals_processed == 2

        # Check knowledge was written
        convs = json.loads((knowledge_dir / "conventions.json").read_text())
        assert len(convs["conventions"]) == 2

    print("PASS: test_merge_proposals_auto_merge")


def test_merge_proposals_conflict():
    """Same key with different values creates a conflict."""
    with tempfile.TemporaryDirectory() as tmpdir:
        proposals_dir = Path(tmpdir) / "proposals"
        knowledge_dir = Path(tmpdir) / "knowledge"
        proposals_dir.mkdir(parents=True)
        knowledge_dir.mkdir(parents=True)

        p1 = {
            "timestamp": "2026-03-22T10:00:00Z",
            "actor": "alice",
            "feature": "auth",
            "observations": [],
            "conventions": [{"key": "indent", "value": "2 spaces"}],
            "status": "pending",
        }
        p2 = {
            "timestamp": "2026-03-22T11:00:00Z",
            "actor": "bob",
            "feature": "dashboard",
            "observations": [],
            "conventions": [{"key": "indent", "value": "4 spaces"}],
            "status": "pending",
        }
        (proposals_dir / "p1.json").write_text(json.dumps(p1))
        (proposals_dir / "p2.json").write_text(json.dumps(p2))

        result = merge_proposals(proposals_dir, knowledge_dir)

        assert result.conflicted == 1
        assert result.merged == 0

        # Conflicts file should exist
        conflicts = json.loads((knowledge_dir / "conflicts.json").read_text())
        assert len(conflicts) == 1
        assert conflicts[0]["key"] == "indent"

    print("PASS: test_merge_proposals_conflict")


def test_merge_proposals_locked_skipped():
    """Locked conventions are never auto-modified."""
    with tempfile.TemporaryDirectory() as tmpdir:
        proposals_dir = Path(tmpdir) / "proposals"
        knowledge_dir = Path(tmpdir) / "knowledge"
        proposals_dir.mkdir(parents=True)
        knowledge_dir.mkdir(parents=True)

        # Pre-existing locked convention
        existing = {
            "conventions": [
                {"key": "indent", "value": "tabs", "confidence": "locked"},
            ]
        }
        (knowledge_dir / "conventions.json").write_text(json.dumps(existing))

        # Proposal tries to change it
        p1 = {
            "timestamp": "2026-03-22T10:00:00Z",
            "actor": "alice",
            "feature": "auth",
            "observations": [],
            "conventions": [{"key": "indent", "value": "2 spaces"}],
            "status": "pending",
        }
        (proposals_dir / "p1.json").write_text(json.dumps(p1))

        result = merge_proposals(proposals_dir, knowledge_dir)

        assert result.skipped == 1
        assert result.merged == 0
        assert result.conflicted == 0

        # Convention should still be tabs
        convs = json.loads((knowledge_dir / "conventions.json").read_text())
        assert convs["conventions"][0]["value"] == "tabs"
        assert convs["conventions"][0]["confidence"] == "locked"

    print("PASS: test_merge_proposals_locked_skipped")


def test_confidence_scoring():
    """Confidence tiers based on cross-proposal evidence."""
    proposals = [
        {"actor": "alice", "feature": "auth", "conventions": [{"key": "naming", "value": "snake"}]},
        {"actor": "alice", "feature": "billing", "conventions": [{"key": "naming", "value": "snake"}]},
        {"actor": "bob", "feature": "dashboard", "conventions": [{"key": "naming", "value": "snake"}]},
    ]

    conv = {"key": "naming", "value": "snake"}
    confidence = compute_confidence(conv, proposals)
    assert confidence == CONFIDENCE_HIGH, f"Expected high, got {confidence}"

    # Single observation
    single = [{"actor": "alice", "feature": "auth", "conventions": [{"key": "x", "value": "y"}]}]
    assert compute_confidence({"key": "x"}, single) == CONFIDENCE_LOW

    # Two actors
    two_actors = [
        {"actor": "alice", "feature": "auth", "conventions": [{"key": "z", "value": "1"}]},
        {"actor": "bob", "feature": "auth", "conventions": [{"key": "z", "value": "1"}]},
    ]
    assert compute_confidence({"key": "z"}, two_actors) == CONFIDENCE_MEDIUM

    print("PASS: test_confidence_scoring")


def test_merge_marks_proposals_processed():
    """Merged proposals get status changed from pending to merged."""
    with tempfile.TemporaryDirectory() as tmpdir:
        proposals_dir = Path(tmpdir) / "proposals"
        knowledge_dir = Path(tmpdir) / "knowledge"
        proposals_dir.mkdir(parents=True)
        knowledge_dir.mkdir(parents=True)

        p1 = {
            "timestamp": "2026-03-22T10:00:00Z",
            "actor": "alice",
            "feature": "auth",
            "observations": [],
            "conventions": [{"key": "test", "value": "pytest"}],
            "status": "pending",
        }
        (proposals_dir / "p1.json").write_text(json.dumps(p1))

        merge_proposals(proposals_dir, knowledge_dir)

        updated = json.loads((proposals_dir / "p1.json").read_text())
        assert updated["status"] == "merged"

    print("PASS: test_merge_marks_proposals_processed")


if __name__ == "__main__":
    test_write_proposal()
    test_merge_proposals_auto_merge()
    test_merge_proposals_conflict()
    test_merge_proposals_locked_skipped()
    test_confidence_scoring()
    test_merge_marks_proposals_processed()
    print("\nAll multiplayer Python tests passed.")
