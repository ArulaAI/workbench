from skills.sync import sync, status
from skills import CURRENT, STALE, CONFLICTED, ABSENT


def _run(project, skills_dir, version="0.3.0", **kw):
    return {s.skill + "@" + s.surface: s for s in sync(project, skills_dir, version, **kw)}


def test_sync_projects_then_idempotent(tmp_catalog, tmp_project):
    skills_dir = tmp_catalog()
    first = _run(tmp_project, skills_dir)
    proj_skill = tmp_project / ".claude" / "skills" / "workbench-draft" / "SKILL.md"
    assert proj_skill.exists()
    assert first["workbench-draft@claude_code"].state == ABSENT  # pre-write classification
    again = status(tmp_project, skills_dir, "0.3.0")
    assert all(s.state == CURRENT for s in again)


def test_second_sync_writes_nothing(tmp_catalog, tmp_project):
    skills_dir = tmp_catalog()
    _run(tmp_project, skills_dir)
    manifest = tmp_project / ".speed" / "skills" / "manifest.json"
    projected = tmp_project / ".claude" / "skills" / "workbench-draft" / "SKILL.md"
    m0, p0 = manifest.stat().st_mtime_ns, projected.stat().st_mtime_ns
    _run(tmp_project, skills_dir)  # unchanged catalog
    assert manifest.stat().st_mtime_ns == m0  # manifest not rewritten
    assert projected.stat().st_mtime_ns == p0  # projection not rewritten


def test_sync_preserves_user_edit_as_conflict(tmp_catalog, tmp_project):
    skills_dir = tmp_catalog()
    _run(tmp_project, skills_dir)
    edited = tmp_project / ".claude" / "skills" / "workbench-draft" / "SKILL.md"
    edited.write_text("HAND EDITED\n")
    rows = status(tmp_project, skills_dir, "0.3.0")
    assert any(s.state == CONFLICTED for s in rows)
    _run(tmp_project, skills_dir)  # no force: must not clobber
    assert edited.read_text() == "HAND EDITED\n"
    _run(tmp_project, skills_dir, force=True)  # force overwrites
    assert "HAND EDITED" not in edited.read_text()


def test_version_bump_marks_stale_then_updates(tmp_catalog, tmp_project):
    skills_dir = tmp_catalog()
    _run(tmp_project, skills_dir, version="0.3.0")
    rows = status(tmp_project, skills_dir, "0.4.0")
    assert any(s.state == STALE for s in rows)
    _run(tmp_project, skills_dir, version="0.4.0")
    assert all(s.state == CURRENT for s in status(tmp_project, skills_dir, "0.4.0"))


def test_no_surface_reports_unsupported(tmp_catalog, tmp_path):
    skills_dir = tmp_catalog()
    bare = tmp_path / "bare"
    bare.mkdir()
    rows = sync(bare, skills_dir, "0.3.0")
    assert [r.state for r in rows] == ["unsupported"]
