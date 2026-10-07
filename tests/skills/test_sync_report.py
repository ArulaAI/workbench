"""End-to-end sync reporting through the engine CLI (WB-SYNC-REPORT REQ-1..6).

Drives ``skills.__main__.main`` in-process so a single skill's write can be made
to fail deterministically on every platform.
"""
import json
from pathlib import Path

import pytest

import skills.sync as engine
from skills import PATHS, __main__ as cli
from skills.manifest import load_manifest


def _sync(project, skills_dir, *extra):
    return cli.main([
        "sync", "--project-root", str(project), "--skills-dir", str(skills_dir),
        "--catalog-version", "dev", *extra,
    ])


def _report(capsys):
    return json.loads(capsys.readouterr().out)


@pytest.fixture
def two_skills(tmp_catalog):
    tmp_catalog("alpha")
    return tmp_catalog("beta")


def _fail_for(monkeypatch, skill, exc):
    real = engine._write_projection

    def flaky(dest, rendered):
        if dest.name == skill:
            raise exc
        return real(dest, rendered)

    monkeypatch.setattr(engine, "_write_projection", flaky)


def test_one_failed_skill_does_not_stop_the_others(two_skills, tmp_project, monkeypatch, capsys):
    _fail_for(monkeypatch, "alpha", PermissionError("permission denied writing alpha"))

    code = _sync(tmp_project, two_skills, "--report", "json")
    report = _report(capsys)

    assert code == 1
    assert report["status"] == "partial"
    assert report["exit_code"] == 1
    by_skill = {r["skill_id"]: r for r in report["results"]}
    assert by_skill["alpha"]["outcome"] == "failed"
    assert by_skill["alpha"]["error_type"] == "PermissionError"
    assert "permission denied" in by_skill["alpha"]["reason"]
    assert by_skill["beta"]["outcome"] == "added"
    assert (tmp_project / ".claude/skills/beta/SKILL.md").is_file()

    # REQ-5.3: the failed skill is not recorded as current, so it is retried.
    recorded = load_manifest(tmp_project)["harnesses"]["claude"]["skills"]
    assert "alpha" not in recorded and "beta" in recorded

    monkeypatch.undo()
    assert _sync(tmp_project, two_skills, "--report", "json") == 0
    retry = {r["skill_id"]: r["outcome"] for r in _report(capsys)["results"]}
    assert retry == {"alpha": "added", "beta": "unchanged"}


def test_a_broken_harness_fails_alone(tmp_catalog, tmp_path, capsys):
    skills_dir = tmp_catalog()
    project = tmp_path / "proj"
    (project / ".claude").mkdir(parents=True)
    (project / ".agents").mkdir()
    (project / ".agents" / "skills").write_text("a file where a directory belongs\n")

    code = _sync(project, skills_dir, "--report", "json")
    report = _report(capsys)

    assert code == 1
    by_harness = {r["harness"]: r for r in report["results"]}
    assert by_harness["codex"]["outcome"] == "failed"
    assert by_harness["codex"]["reason"].startswith("harness-level: ")
    assert by_harness["claude"]["outcome"] == "added"


def test_json_report_matches_the_data_model(tmp_catalog, tmp_project, capsys):
    skills_dir = tmp_catalog()
    assert _sync(tmp_project, skills_dir, "--report", "json") == 0
    report = _report(capsys)

    assert set(report) == {
        "run_id", "started_at", "finished_at", "catalog_version", "harnesses",
        "results", "summary", "status", "exit_code", "error",
    }
    assert report["catalog_version"] == "dev"
    assert report["harnesses"] == ["claude"]
    assert report["status"] == "success" and report["error"] is None
    assert set(report["summary"]) == {
        "added", "updated", "removed", "unchanged", "skipped", "failed",
    }
    [row] = report["results"]
    assert set(row) == {
        "skill_id", "harness", "outcome", "reason", "error_type",
        "duration_ms", "final_state",
    }
    assert row["outcome"] == "added" and row["final_state"] == "current"


def test_preserved_conflict_is_skipped_with_a_reason_and_exits_two(
    tmp_catalog, tmp_project, capsys
):
    skills_dir = tmp_catalog()
    _sync(tmp_project, skills_dir, "--no-log")
    capsys.readouterr()
    (tmp_project / ".claude/skills/example-skill/SKILL.md").write_text("HAND EDIT\n")

    assert _sync(tmp_project, skills_dir, "--report", "json") == 2
    [row] = _report(capsys)["results"]
    assert row["outcome"] == "skipped"
    assert "projected_file_modified" in row["reason"]
    assert "--force" in row["reason"]


def test_preflight_error_still_emits_a_report_and_exits_three(tmp_project, tmp_path, capsys):
    missing = tmp_path / "no-such-catalog"
    assert _sync(tmp_project, missing, "--report", "json") == 3
    report = _report(capsys)
    assert report["status"] == "failed"
    assert report["error"]["type"]
    assert report["results"] == []
    # the aborted run is logged too (REQ-2.1)
    [entry] = (tmp_project / PATHS.sync_log).read_text().splitlines()
    assert json.loads(entry)["exit_code"] == 3


def test_every_run_is_logged_with_failure_context(two_skills, tmp_project, monkeypatch, capsys):
    _fail_for(monkeypatch, "beta", OSError("disk full"))
    _sync(tmp_project, two_skills)
    entries = [json.loads(l) for l in (tmp_project / PATHS.sync_log).read_text().splitlines()]
    [entry] = entries
    failed = [r for r in entry["results"] if r["outcome"] == "failed"]
    assert failed == [{
        "skill_id": "beta", "harness": "claude", "outcome": "failed",
        "reason": "disk full", "error_type": "OSError",
        "duration_ms": failed[0]["duration_ms"], "final_state": "absent",
    }]


def test_no_log_writes_nothing(tmp_catalog, tmp_project):
    _sync(tmp_project, tmp_catalog(), "--no-log")
    assert not (tmp_project / PATHS.sync_log).exists()


def test_unwritable_log_warns_and_keeps_the_exit_code(tmp_catalog, tmp_project, capsys):
    blocked = tmp_project / PATHS.sync_log
    blocked.mkdir(parents=True)  # a directory where the log file belongs
    assert _sync(tmp_project, tmp_catalog()) == 0
    assert "warning: could not write sync log" in capsys.readouterr().err


def test_text_mode_keeps_the_header_and_adds_a_summary(two_skills, tmp_project, monkeypatch, capsys):
    _fail_for(monkeypatch, "alpha", PermissionError("denied"))
    _sync(tmp_project, two_skills, "--no-log")
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "catalog dev · 2 row(s)"
    assert any("alpha" in l and "failed" in l and "PermissionError: denied" in l for l in lines)
    assert lines[-1].startswith("summary: 1 added · 0 updated")
    assert lines[-1].endswith("status partial")


def test_legacy_json_keeps_the_row_array(tmp_catalog, tmp_project, capsys):
    _sync(tmp_project, tmp_catalog(), "--json", "--no-log")
    rows = json.loads(capsys.readouterr().out)
    assert isinstance(rows, list)
    assert rows[0]["action"] == "installed"


def _snapshot(root: Path, exclude) -> dict:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and not any(p.relative_to(root).as_posix().startswith(e) for e in exclude)
    }


def test_files_outside_sync_targets_are_untouched(two_skills, tmp_project, monkeypatch):
    (tmp_project / "src").mkdir()
    (tmp_project / "src" / "app.py").write_text("print('hi')\n")
    (tmp_project / ".claude" / "settings.json").write_text("{}\n")
    (tmp_project / "README.md").write_text("# readme\n")
    targets = (".claude/skills/", ".speed/skills/")
    before = _snapshot(tmp_project, targets)

    _fail_for(monkeypatch, "alpha", PermissionError("denied"))
    _sync(tmp_project, two_skills)

    assert _snapshot(tmp_project, targets) == before
    written = {p.relative_to(tmp_project).as_posix() for p in (tmp_project / ".speed").rglob("*") if p.is_file()}
    allowed = {"manifest.json", "events.jsonl", "sync.lock", "sync-log.jsonl"}
    assert {Path(w).name for w in written} <= allowed
