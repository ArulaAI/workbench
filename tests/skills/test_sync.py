import json
import shutil

import pytest

from skills.sync import sync, status
from skills.manifest import hash_bytes, load_manifest
from skills import CURRENT, STALE, CONFLICTED, ABSENT


def _run(project, skills_dir, version="0.3.0", **kw):
    return {s.skill + "@" + s.surface: s for s in sync(project, skills_dir, version, **kw)}


def test_sync_projects_then_idempotent(tmp_catalog, tmp_project):
    skills_dir = tmp_catalog()
    first = _run(tmp_project, skills_dir)
    proj_skill = tmp_project / ".claude" / "skills" / "example-skill" / "SKILL.md"
    assert proj_skill.exists()
    assert first["example-skill@claude_code"].state == CURRENT  # post-write state
    again = status(tmp_project, skills_dir, "0.3.0")
    assert all(s.state == CURRENT for s in again)


def test_second_sync_writes_nothing(tmp_catalog, tmp_project):
    skills_dir = tmp_catalog()
    _run(tmp_project, skills_dir)
    manifest = tmp_project / ".speed" / "skills" / "manifest.json"
    projected = tmp_project / ".claude" / "skills" / "example-skill" / "SKILL.md"
    m0, p0 = manifest.stat().st_mtime_ns, projected.stat().st_mtime_ns
    _run(tmp_project, skills_dir)  # unchanged catalog
    assert manifest.stat().st_mtime_ns == m0  # manifest not rewritten
    assert projected.stat().st_mtime_ns == p0  # projection not rewritten


def test_sync_preserves_user_edit_as_conflict(tmp_catalog, tmp_project):
    skills_dir = tmp_catalog()
    _run(tmp_project, skills_dir)
    edited = tmp_project / ".claude" / "skills" / "example-skill" / "SKILL.md"
    edited.write_text("HAND EDITED\n")
    rows = status(tmp_project, skills_dir, "0.3.0")
    assert any(s.state == CONFLICTED for s in rows)
    _run(tmp_project, skills_dir)  # no force: must not clobber
    assert edited.read_text() == "HAND EDITED\n"
    _run(tmp_project, skills_dir, force=True)  # force overwrites
    assert "HAND EDITED" not in edited.read_text()


def _edit_catalog(skills_dir, name="example-skill", body="Do a different thing."):
    (skills_dir / name / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: A test skill\n---\n\n# {name}\n{body}\n"
    )


def test_catalog_change_marks_stale_then_updates(tmp_catalog, tmp_project):
    skills_dir = tmp_catalog()
    _run(tmp_project, skills_dir, version="0.3.0")
    _edit_catalog(skills_dir)
    rows = status(tmp_project, skills_dir, "0.4.0")
    assert any(s.state == STALE for s in rows)
    _run(tmp_project, skills_dir, version="0.4.0")
    assert all(s.state == CURRENT for s in status(tmp_project, skills_dir, "0.4.0"))


def test_no_surface_reports_unsupported(tmp_catalog, tmp_path):
    skills_dir = tmp_catalog()
    bare = tmp_path / "bare"
    bare.mkdir()
    rows = sync(bare, skills_dir, "0.3.0")
    assert [r.surface for r in rows] == ["claude_code", "codex", "copilot"]
    assert [r.state for r in rows] == ["unsupported"] * 3


def test_explicit_surface_creates_only_selected_harness(tmp_catalog, tmp_path):
    skills_dir = tmp_catalog()
    project = tmp_path / "bare"
    for marker in (".claude", ".agents", ".github/skills"):
        (project / marker).mkdir(parents=True)

    rows = sync(
        project,
        skills_dir,
        "0.3.0",
        only_surface="codex",
    )

    assert [row.surface for row in rows] == ["codex"]
    assert (project / ".agents" / "skills" / "example-skill" / "SKILL.md").is_file()
    assert not (
        project / ".claude" / "skills" / "example-skill"
    ).exists()
    assert not (
        project / ".github" / "skills" / "example-skill"
    ).exists()


def test_sync_without_selection_projects_all_detected_harnesses(
    tmp_catalog, tmp_path
):
    skills_dir = tmp_catalog()
    project = tmp_path / "multi-harness"
    for marker in (".claude", ".agents", ".github/skills"):
        (project / marker).mkdir(parents=True)

    rows = sync(project, skills_dir, "0.3.0")

    assert [row.surface for row in rows] == ["claude_code", "codex", "copilot"]
    for skills_root in (".claude/skills", ".agents/skills", ".github/skills"):
        assert (project / skills_root / "example-skill" / "SKILL.md").is_file()


def test_sync_reports_post_apply_state_and_action(tmp_catalog, tmp_project):
    """A row must describe the world after sync ran, not before it started."""
    skills_dir = tmp_catalog()
    row = _run(tmp_project, skills_dir)["example-skill@claude_code"]
    assert row.state == CURRENT
    assert row.action == "installed"


def test_sync_reports_update_after_catalog_change(tmp_catalog, tmp_project):
    skills_dir = tmp_catalog()
    _run(tmp_project, skills_dir, version="0.3.0")
    _edit_catalog(skills_dir)
    row = _run(tmp_project, skills_dir, version="0.4.0")["example-skill@claude_code"]
    assert row.state == CURRENT
    assert row.action == "updated"


def test_forced_repair_reports_current_not_conflicted(tmp_catalog, tmp_project):
    skills_dir = tmp_catalog()
    _run(tmp_project, skills_dir)
    edited = tmp_project / ".claude" / "skills" / "example-skill" / "SKILL.md"
    edited.write_text("HAND EDITED\n")

    row = _run(tmp_project, skills_dir, force=True)["example-skill@claude_code"]

    assert row.state == CURRENT
    assert row.action == "updated"
    assert all(s.state == CURRENT for s in status(tmp_project, skills_dir, "0.3.0"))


def test_unforced_conflict_still_reports_conflicted(tmp_catalog, tmp_project):
    skills_dir = tmp_catalog()
    _run(tmp_project, skills_dir)
    edited = tmp_project / ".claude" / "skills" / "example-skill" / "SKILL.md"
    edited.write_text("HAND EDITED\n")

    row = _run(tmp_project, skills_dir)["example-skill@claude_code"]

    assert row.state == CONFLICTED
    assert row.action == "conflict"


def test_missing_catalog_never_removes_a_projection(tmp_catalog, tmp_project):
    """A typo in --skills-dir must not be read as 'the catalog is now empty'."""
    skills_dir = tmp_catalog()
    _run(tmp_project, skills_dir)
    projected = tmp_project / ".claude" / "skills" / "example-skill"

    with pytest.raises(ValueError, match="skill catalog directory not found"):
        sync(tmp_project, skills_dir.parent / "gone", "0.3.0")

    assert projected.is_dir()


def test_explicit_surface_is_remembered_by_later_syncs(tmp_catalog, tmp_project):
    """Init picks a harness; a later bare sync must not fan out to others."""
    skills_dir = tmp_catalog()
    (tmp_project / ".agents").mkdir(parents=True, exist_ok=True)

    _run(tmp_project, skills_dir, only_surface="codex")
    assert load_manifest(tmp_project)["selected_surfaces"] == ["codex"]

    rows = status(tmp_project, skills_dir, "0.3.0")

    assert {r.surface for r in rows} == {"codex"}
    assert not (tmp_project / ".claude" / "skills").exists()


def test_detection_still_applies_when_no_surface_was_chosen(tmp_catalog, tmp_project):
    skills_dir = tmp_catalog()
    (tmp_project / ".agents").mkdir(parents=True, exist_ok=True)

    _run(tmp_project, skills_dir)

    assert "selected_surfaces" not in load_manifest(tmp_project)
    assert {r.surface for r in status(tmp_project, skills_dir, "0.3.0")} == {
        "claude_code",
        "codex",
    }


def _cli(project, skills_dir, *extra, cmd="sync"):
    from skills.__main__ import main

    return main([
        cmd,
        "--project-root", str(project),
        "--skills-dir", str(skills_dir),
        "--catalog-version", "0.3.0",
        *extra,
    ])


def test_sync_exit_code_reflects_post_operation_state(tmp_catalog, tmp_project):
    skills_dir = tmp_catalog()
    assert _cli(tmp_project, skills_dir) == 0

    edited = tmp_project / ".claude" / "skills" / "example-skill" / "SKILL.md"
    edited.write_text("HAND EDITED\n")
    assert _cli(tmp_project, skills_dir) == 2  # conflict survives, nothing written

    assert _cli(tmp_project, skills_dir, "--force") == 0  # repaired, so not a failure


def test_missing_catalog_exits_as_an_error_not_a_success(tmp_catalog, tmp_project):
    skills_dir = tmp_catalog()
    _cli(tmp_project, skills_dir)

    assert _cli(tmp_project, skills_dir.parent / "gone") == 3


def test_deleted_projection_is_reprojected_without_force(tmp_catalog, tmp_project):
    """git clean or an ignored .claude/ must not need --force to recover."""
    skills_dir = tmp_catalog()
    _run(tmp_project, skills_dir)
    projected = tmp_project / ".claude" / "skills" / "example-skill"
    shutil.rmtree(projected)

    assert [r.state for r in status(tmp_project, skills_dir, "0.3.0")] == [ABSENT]

    _run(tmp_project, skills_dir)  # no --force

    assert (projected / "SKILL.md").is_file()


def test_partial_deletion_is_still_a_conflict(tmp_catalog, tmp_project):
    """Only a wholly missing projection is unambiguous; a partial one is not."""
    skills_dir = tmp_catalog()
    _run(tmp_project, skills_dir)
    (tmp_project / ".claude" / "skills" / "example-skill" / "references" / "notes.md").unlink()

    assert [r.state for r in status(tmp_project, skills_dir, "0.3.0")] == [CONFLICTED]


def test_explicit_surfaces_accumulate(tmp_catalog, tmp_project):
    """Choosing a second harness must not orphan the first one's projection."""
    skills_dir = tmp_catalog()
    (tmp_project / ".agents").mkdir(parents=True, exist_ok=True)

    _run(tmp_project, skills_dir, only_surface="claude")
    _run(tmp_project, skills_dir, only_surface="codex")

    assert load_manifest(tmp_project)["selected_surfaces"] == ["claude_code", "codex"]
    assert {r.surface for r in status(tmp_project, skills_dir, "0.3.0")} == {
        "claude_code",
        "codex",
    }


def _poison_manifest(project, key, files):
    """Write a manifest entry under an arbitrary key, as a bad commit would."""
    path = project / ".speed" / "skills" / "manifest.json"
    data = json.loads(path.read_text())
    data["surfaces"]["claude_code"]["skills"][key] = {"files": files}
    path.write_text(json.dumps(data))


def test_manifest_skill_name_cannot_steer_removal_outside_the_project(
    tmp_catalog, tmp_project
):
    """manifest.json is committed, so its keys are untrusted input to rmtree."""
    skills_dir = tmp_catalog()
    _run(tmp_project, skills_dir)
    victim = tmp_project.parent / "victim"
    victim.mkdir()
    (victim / "important.txt").write_text("keep me\n")
    escape = "../../../victim"
    _poison_manifest(
        tmp_project,
        escape,
        {"important.txt": hash_bytes(b"keep me\n")},  # matches disk -> orphaned
    )

    rows = _run(tmp_project, skills_dir)

    assert (victim / "important.txt").is_file()
    assert escape not in {row.skill for row in rows.values()}


def test_forced_sync_cannot_delete_outside_the_project(tmp_catalog, tmp_project):
    """--force is the documented repair, so it must not widen the blast radius."""
    skills_dir = tmp_catalog()
    _run(tmp_project, skills_dir)
    victim = tmp_project.parent / "victim"
    victim.mkdir()
    (victim / "important.txt").write_text("keep me\n")
    _poison_manifest(
        tmp_project,
        "../../../victim",
        {"important.txt": "sha256:deadbeef"},  # mismatched -> conflicted
    )

    _run(tmp_project, skills_dir, force=True)

    assert (victim / "important.txt").is_file()


def test_unsafe_manifest_entry_is_pruned(tmp_catalog, tmp_project):
    skills_dir = tmp_catalog()
    _run(tmp_project, skills_dir)
    _poison_manifest(tmp_project, "../../../victim", {"important.txt": "sha256:dead"})

    _run(tmp_project, skills_dir)

    skills = load_manifest(tmp_project)["surfaces"]["claude_code"]["skills"]
    assert set(skills) == {"example-skill"}


@pytest.mark.parametrize(
    "junk", [".DS_Store", "__pycache__/x.pyc", "references/.DS_Store"]
)
def test_generated_junk_beside_a_projection_is_not_a_conflict(
    tmp_catalog, tmp_project, junk
):
    """render() never emits these, so their presence says nothing about drift."""
    skills_dir = tmp_catalog()
    _run(tmp_project, skills_dir)
    dropped = tmp_project / ".claude" / "skills" / "example-skill" / junk
    dropped.parent.mkdir(parents=True, exist_ok=True)
    dropped.write_bytes(b"\x00")

    assert [r.state for r in status(tmp_project, skills_dir, "0.3.0")] == [CURRENT]


def test_failure_on_a_later_surface_keeps_earlier_writes_recorded(
    tmp_catalog, tmp_path
):
    """A half-finished sync must be resumable, not permanently conflicted."""
    skills_dir = tmp_catalog()
    project = tmp_path / "two-harness"
    (project / ".claude").mkdir(parents=True)
    (project / ".agents").mkdir(parents=True)
    # A regular file where codex needs a directory: claude_code is written
    # first, then codex raises part-way through the same sync.
    (project / ".agents" / "skills").write_text("not a directory\n")

    with pytest.raises(OSError):
        sync(project, skills_dir, "0.3.0")

    written = project / ".claude" / "skills" / "example-skill" / "SKILL.md"
    assert written.is_file()
    rows = status(project, skills_dir, "0.3.0", only_surface="claude")
    assert [r.state for r in rows] == [CURRENT]


def test_a_different_install_leaves_a_committed_projection_alone(
    tmp_catalog, tmp_project
):
    """Teammates on different SPEED builds must not fight over the manifest."""
    skills_dir = tmp_catalog()
    _run(tmp_project, skills_dir, version="install-a")
    manifest = tmp_project / ".speed" / "skills" / "manifest.json"
    projected = tmp_project / ".claude" / "skills" / "example-skill" / "SKILL.md"
    m0, p0 = manifest.stat().st_mtime_ns, projected.stat().st_mtime_ns

    assert [r.state for r in status(tmp_project, skills_dir, "install-b")] == [CURRENT]

    _run(tmp_project, skills_dir, version="install-b")

    assert manifest.stat().st_mtime_ns == m0
    assert projected.stat().st_mtime_ns == p0


def test_structured_front_matter_survives_projection(tmp_catalog, tmp_project):
    """A list or a colon in a description must not break the projected skill."""
    yaml = pytest.importorskip("yaml")
    skills_dir = tmp_catalog()
    (skills_dir / "example-skill" / "SKILL.md").write_text(
        "---\n"
        "name: example-skill\n"
        "description: >\n"
        "  Use when: the user asks about charts.\n"
        "allowed-tools:\n"
        "  - Read\n"
        "  - Bash(git status:*)\n"
        "---\n\n"
        "# example-skill\n"
    )

    _run(tmp_project, skills_dir)

    projected = tmp_project / ".claude" / "skills" / "example-skill" / "SKILL.md"
    meta = yaml.safe_load(projected.read_text().split("---\n")[1])
    assert meta["allowed-tools"] == ["Read", "Bash(git status:*)"]
    assert meta["description"].strip() == "Use when: the user asks about charts."
    assert meta["x-workbench-managed"] is True  # unquoted true, as YAML reads it
    assert [r.state for r in status(tmp_project, skills_dir, "0.3.0")] == [CURRENT]
