#!/usr/bin/env python3
"""Unit tests for lib/learn/project_knowledge.py.

Covers seed_knowledge, detect_knowledge_gaps, and check_staleness.
Uses tmp_path fixtures for full isolation — no shared state between tests.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from lib.learn.project_knowledge import (
    DraftEntry,
    check_staleness,
    detect_knowledge_gaps,
    seed_knowledge,
)


# ── Helpers ───────────────────────────────────────────────────────────


def _write_knowledge(memory_dir: Path, entries: list[dict]) -> None:
    """Write a project-knowledge.json with the given entries."""
    (memory_dir / "project-knowledge.json").write_text(
        json.dumps(entries, indent=2)
    )


def _write_obs_jsonl(obs_dir: Path, filename: str, observations: list[dict]) -> None:
    """Write observations to a JSONL file in obs_dir."""
    obs_dir.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(obs) for obs in observations]
    (obs_dir / filename).write_text("\n".join(lines) + "\n")


def _make_obs(obs_type: str, file_path: str) -> dict:
    """Build a minimal observation dict referencing a file path."""
    return {
        "observation_type": obs_type,
        "detail": {"files_involved": [file_path]},
    }


def _iso_days_ago(days: int) -> str:
    """Return an ISO 8601 date string for N days ago."""
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return dt.strftime("%Y-%m-%d")


# ── TestSeedKnowledge ─────────────────────────────────────────────────


class TestSeedKnowledge:
    def test_readme_important_comment_produces_draft(self, tmp_path):
        memory_dir = tmp_path / "memory"
        (tmp_path / "README.md").write_text(
            "# My Project\n\nIMPORTANT: payment service returns 202 on async processing\n"
        )

        result = seed_knowledge(tmp_path, memory_dir)

        assert len(result) == 1
        assert "payment service returns 202" in result[0].knowledge
        assert result[0].source == "seeded"

    def test_claude_md_never_comment_produces_draft(self, tmp_path):
        memory_dir = tmp_path / "memory"
        (tmp_path / "CLAUDE.md").write_text(
            "# Instructions\n\nNEVER import tomli directly — use the compat shim.\n"
        )

        result = seed_knowledge(tmp_path, memory_dir)

        assert len(result) == 1
        assert "tomli" in result[0].knowledge
        assert result[0].applies_to == ["CLAUDE.md"]

    def test_inline_python_comment_produces_draft(self, tmp_path):
        memory_dir = tmp_path / "memory"
        src = tmp_path / "lib"
        src.mkdir()
        (src / "payments.py").write_text(
            "def process():\n    # HACK: workaround for upstream API returning wrong status\n    pass\n"
        )

        result = seed_knowledge(tmp_path, memory_dir)

        assert len(result) == 1
        assert "HACK" in result[0].knowledge or "workaround" in result[0].knowledge
        assert result[0].source == "seeded"
        assert "lib/payments.py" in result[0].applies_to[0]

    def test_env_example_var_names_extracted(self, tmp_path):
        memory_dir = tmp_path / "memory"
        (tmp_path / ".env.example").write_text(
            "DATABASE_URL=postgres://localhost/mydb\nREDIS_URL=redis://localhost\nSECRET_KEY=changeme\n"
        )

        result = seed_knowledge(tmp_path, memory_dir)

        assert len(result) == 1
        knowledge = result[0].knowledge
        assert "DATABASE_URL" in knowledge
        assert "REDIS_URL" in knowledge
        assert "SECRET_KEY" in knowledge
        # Values must never appear
        assert "postgres://localhost/mydb" not in knowledge
        assert "changeme" not in knowledge

    def test_env_is_skipped_not_env_example(self, tmp_path):
        memory_dir = tmp_path / "memory"
        (tmp_path / ".env").write_text("SECRET=super_secret_value\n")

        result = seed_knowledge(tmp_path, memory_dir)

        # .env is denylisted and must never be read
        assert result == []
        knowledge_file = memory_dir / "project-knowledge.json"
        assert not knowledge_file.exists()

    def test_no_scannable_files_empty_list_and_empty_array_written(self, tmp_path):
        memory_dir = tmp_path / "memory"

        result = seed_knowledge(tmp_path, memory_dir)

        assert result == []
        drafts_path = memory_dir / "project-knowledge-drafts.json"
        assert drafts_path.exists()
        data = json.loads(drafts_path.read_text())
        assert data == []

    def test_duplicate_run_merges_without_duplicate_ids(self, tmp_path):
        memory_dir = tmp_path / "memory"
        (tmp_path / "README.md").write_text("IMPORTANT: always use UTC for timestamps\n")

        first = seed_knowledge(tmp_path, memory_dir)
        second = seed_knowledge(tmp_path, memory_dir)

        assert len(first) == 1
        assert len(second) == 1
        # On-disk file must not have duplicates
        drafts_path = memory_dir / "project-knowledge-drafts.json"
        data = json.loads(drafts_path.read_text())
        ids = [e["id"] for e in data]
        assert len(ids) == len(set(ids))
        assert len(data) == 1

    def test_draft_entry_schema_conformance(self, tmp_path):
        memory_dir = tmp_path / "memory"
        (tmp_path / "README.md").write_text("NOTE: retry logic uses exponential backoff\n")

        result = seed_knowledge(tmp_path, memory_dir)

        assert len(result) >= 1
        entry = result[0]
        assert entry.id.startswith("pk-draft-")
        assert len(entry.id) == len("pk-draft-") + 16
        assert isinstance(entry.knowledge, str) and entry.knowledge
        assert isinstance(entry.why_it_matters, str)
        assert isinstance(entry.applies_to, list)
        assert isinstance(entry.agents, list) and entry.agents
        assert isinstance(entry.tags, list)
        assert entry.source in ("seeded", "system-prompted", "stale-flag")
        assert isinstance(entry.draft_reason, str)
        assert isinstance(entry.staleness_flag, str)
        # last_verified is None for freshly seeded entries
        assert entry.last_verified is None

    def test_output_file_is_drafts_not_knowledge(self, tmp_path):
        memory_dir = tmp_path / "memory"
        (tmp_path / "README.md").write_text("ALWAYS validate inputs before saving\n")

        seed_knowledge(tmp_path, memory_dir)

        assert (memory_dir / "project-knowledge-drafts.json").exists()
        assert not (memory_dir / "project-knowledge.json").exists()


# ── TestDetectKnowledgeGaps ───────────────────────────────────────────


class TestDetectKnowledgeGaps:
    def test_three_retries_generates_gap_entry(self, tmp_path):
        memory_dir = tmp_path / "memory"
        obs_dir = memory_dir / "observations"
        target_file = "lib/api/payments.py"
        _write_obs_jsonl(obs_dir, "feat-1.jsonl", [
            _make_obs("retry", target_file),
            _make_obs("retry", target_file),
            _make_obs("retry", target_file),
        ])

        result = detect_knowledge_gaps(memory_dir)

        assert len(result) == 1
        assert target_file in result[0].applies_to
        assert result[0].source == "system-prompted"
        assert result[0].id.startswith("pk-draft-")
        assert "payments.py" in result[0].knowledge or target_file in result[0].knowledge

    def test_two_retries_below_threshold_returns_empty(self, tmp_path):
        memory_dir = tmp_path / "memory"
        obs_dir = memory_dir / "observations"
        _write_obs_jsonl(obs_dir, "feat-1.jsonl", [
            _make_obs("retry", "lib/api/payments.py"),
            _make_obs("retry", "lib/api/payments.py"),
        ])

        result = detect_knowledge_gaps(memory_dir)

        assert result == []

    def test_empty_observations_dir_returns_empty(self, tmp_path):
        memory_dir = tmp_path / "memory"
        obs_dir = memory_dir / "observations"
        obs_dir.mkdir(parents=True)

        result = detect_knowledge_gaps(memory_dir)

        assert result == []

    def test_missing_observations_dir_returns_empty(self, tmp_path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()

        result = detect_knowledge_gaps(memory_dir)

        assert result == []

    def test_malformed_jsonl_line_skipped_valid_lines_processed(self, tmp_path):
        memory_dir = tmp_path / "memory"
        obs_dir = memory_dir / "observations"
        obs_dir.mkdir(parents=True)
        target = "lib/api/payments.py"
        valid_lines = [json.dumps(_make_obs("retry", target)) for _ in range(3)]
        content = "not valid json\n" + "\n".join(valid_lines) + "\n"
        (obs_dir / "feat-1.jsonl").write_text(content)

        result = detect_knowledge_gaps(memory_dir)

        # Valid lines are processed; malformed line is silently skipped
        assert len(result) == 1
        assert target in result[0].applies_to

    def test_existing_knowledge_entry_prevents_gap_detection(self, tmp_path):
        memory_dir = tmp_path / "memory"
        obs_dir = memory_dir / "observations"
        target = "lib/api/payments.py"
        # Write 3 failures
        _write_obs_jsonl(obs_dir, "feat-1.jsonl", [
            _make_obs("retry", target),
            _make_obs("retry", target),
            _make_obs("retry", target),
        ])
        # Existing knowledge covers this path
        _write_knowledge(memory_dir, [
            {"id": "pk-001", "knowledge": "payments docs", "applies_to": [target]},
        ])

        result = detect_knowledge_gaps(memory_dir)

        assert result == []

    def test_gate_failure_observations_count_toward_threshold(self, tmp_path):
        memory_dir = tmp_path / "memory"
        obs_dir = memory_dir / "observations"
        target = "lib/core/runner.py"
        _write_obs_jsonl(obs_dir, "feat-1.jsonl", [
            _make_obs("gate_failure", target),
            _make_obs("gate_failure", target),
            _make_obs("gate_failure", target),
        ])

        result = detect_knowledge_gaps(memory_dir)

        assert len(result) == 1
        assert target in result[0].applies_to

    def test_drafts_file_written_when_gaps_found(self, tmp_path):
        memory_dir = tmp_path / "memory"
        obs_dir = memory_dir / "observations"
        target = "lib/api/payments.py"
        _write_obs_jsonl(obs_dir, "feat-1.jsonl", [
            _make_obs("retry", target),
            _make_obs("retry", target),
            _make_obs("retry", target),
        ])

        detect_knowledge_gaps(memory_dir)

        drafts_path = memory_dir / "project-knowledge-drafts.json"
        assert drafts_path.exists()
        data = json.loads(drafts_path.read_text())
        assert len(data) == 1
        assert data[0]["id"].startswith("pk-draft-")


# ── TestCheckStaleness ────────────────────────────────────────────────


class TestCheckStaleness:
    def test_deleted_file_flagged_with_staleness_flag(self, tmp_path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        _write_knowledge(memory_dir, [
            {
                "id": "pk-001",
                "knowledge": "Use the payments adapter",
                "applies_to": ["lib/api/deleted_module.py"],
                "last_verified": None,
            }
        ])
        # File does NOT exist in project root

        result = check_staleness(tmp_path, memory_dir)

        assert len(result) == 1
        assert "deleted_module.py" in result[0].staleness_flag
        assert result[0].source == "stale-flag"

    def test_old_last_verified_flagged(self, tmp_path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        _write_knowledge(memory_dir, [
            {
                "id": "pk-001",
                "knowledge": "Old pattern for auth",
                "applies_to": [],
                "last_verified": _iso_days_ago(100),
            }
        ])

        result = check_staleness(tmp_path, memory_dir)

        assert len(result) == 1
        assert "100" in result[0].staleness_flag or "days ago" in result[0].staleness_flag

    def test_recent_last_verified_not_flagged(self, tmp_path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        existing_file = tmp_path / "lib" / "auth.py"
        existing_file.parent.mkdir()
        existing_file.write_text("# auth module\n")
        _write_knowledge(memory_dir, [
            {
                "id": "pk-001",
                "knowledge": "Auth module notes",
                "applies_to": ["lib/auth.py"],
                "last_verified": _iso_days_ago(30),
            }
        ])

        result = check_staleness(tmp_path, memory_dir)

        assert result == []

    def test_unknown_version_in_lock_file_flagged(self, tmp_path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        # Lock file has 2.28.0, knowledge references 3.0.0 (not in lock file)
        (tmp_path / "requirements.txt").write_text("requests==2.28.0\nflask==2.3.0\n")
        _write_knowledge(memory_dir, [
            {
                "id": "pk-001",
                "knowledge": "Use requests 3.0.0 for the new streaming API",
                "applies_to": [],
                "last_verified": None,
            }
        ])

        result = check_staleness(tmp_path, memory_dir)

        assert len(result) == 1
        assert "3.0.0" in result[0].staleness_flag

    def test_matching_version_not_flagged(self, tmp_path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        (tmp_path / "requirements.txt").write_text("requests==2.28.0\n")
        existing_file = tmp_path / "lib" / "client.py"
        existing_file.parent.mkdir()
        existing_file.write_text("# client\n")
        _write_knowledge(memory_dir, [
            {
                "id": "pk-001",
                "knowledge": "Use requests 2.28.0 for the HTTP client",
                "applies_to": ["lib/client.py"],
                "last_verified": _iso_days_ago(10),
            }
        ])

        result = check_staleness(tmp_path, memory_dir)

        assert result == []

    def test_missing_knowledge_file_returns_empty(self, tmp_path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        # project-knowledge.json does not exist

        result = check_staleness(tmp_path, memory_dir)

        assert result == []

    def test_malformed_knowledge_file_raises_json_decode_error(self, tmp_path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        (memory_dir / "project-knowledge.json").write_text("{not valid json!!")

        with pytest.raises(json.JSONDecodeError):
            check_staleness(tmp_path, memory_dir)

    def test_missing_lock_file_skips_version_check(self, tmp_path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        # No lock files present; knowledge mentions a version
        _write_knowledge(memory_dir, [
            {
                "id": "pk-001",
                "knowledge": "Use library 4.2.1 for feature X",
                "applies_to": [],
                "last_verified": _iso_days_ago(10),
            }
        ])

        result = check_staleness(tmp_path, memory_dir)

        # No lock files → version check skipped; applies_to is empty, age is fine
        assert result == []

    def test_drafts_file_written_for_stale_entries(self, tmp_path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        _write_knowledge(memory_dir, [
            {
                "id": "pk-001",
                "knowledge": "Outdated pattern",
                "applies_to": ["lib/gone.py"],
                "last_verified": None,
            }
        ])

        check_staleness(tmp_path, memory_dir)

        drafts_path = memory_dir / "project-knowledge-drafts.json"
        assert drafts_path.exists()
        data = json.loads(drafts_path.read_text())
        assert len(data) == 1
        assert data[0]["source"] == "stale-flag"

    def test_non_list_knowledge_file_returns_empty(self, tmp_path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        (memory_dir / "project-knowledge.json").write_text(json.dumps({"not": "a list"}))

        result = check_staleness(tmp_path, memory_dir)

        assert result == []
