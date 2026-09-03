import json
import shutil
from pathlib import Path

import pytest

from skills.inspect import inspect
from skills.sync import sync
from skills.manifest import hash_bytes, load_manifest
from skills.models import SkillState


def _run(project, skills_dir, version="0.3.0", **kw):
    """Sync, keyed by skill@harness. Values are SyncOutcome, so a caller reads
    `previous_state`, `action` and `final_state` rather than one blended state."""
    return {s.skill + "@" + s.harness: s for s in sync(project, skills_dir, version, **kw)}


def status(project, skills_dir, version="0.3.0", **kw):
    """The read-only rows `workbench skills status` prints, via inspection."""
    return inspect(project, skills_dir, version, **kw).skills


def test_sync_projects_then_idempotent(tmp_catalog, tmp_project):
    skills_dir = tmp_catalog()
    first = _run(tmp_project, skills_dir)
    proj_skill = tmp_project / ".claude" / "skills" / "example-skill" / "SKILL.md"
    assert proj_skill.exists()
    assert first["example-skill@claude"].final_state == SkillState.CURRENT  # post-write state
    again = status(tmp_project, skills_dir, "0.3.0")
    assert all(s.state == SkillState.CURRENT for s in again)


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
    assert any(s.state == SkillState.CONFLICTED for s in rows)
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
    assert any(s.state == SkillState.STALE for s in rows)
    _run(tmp_project, skills_dir, version="0.4.0")
    assert all(s.state == SkillState.CURRENT for s in status(tmp_project, skills_dir, "0.4.0"))


def test_no_harness_reports_unsupported(tmp_catalog, tmp_path):
    skills_dir = tmp_catalog()
    bare = tmp_path / "bare"
    bare.mkdir()
    rows = sync(bare, skills_dir, "0.3.0")
    assert [r.harness for r in rows] == ["claude", "codex", "copilot"]
    assert [r.final_state for r in rows] == [SkillState.UNSUPPORTED] * 3
    # Nothing was attempted, so nothing is reported as having happened.
    assert [r.action for r in rows] == ["", "", ""]


def test_explicit_harness_creates_only_selected_harness(tmp_catalog, tmp_path):
    skills_dir = tmp_catalog()
    project = tmp_path / "bare"
    for marker in (".claude", ".agents", ".github/skills"):
        (project / marker).mkdir(parents=True)

    rows = sync(
        project,
        skills_dir,
        "0.3.0",
        only_harness="codex",
    )

    assert [row.harness for row in rows] == ["codex"]
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

    assert [row.harness for row in rows] == ["claude", "codex", "copilot"]
    for skills_root in (".claude/skills", ".agents/skills", ".github/skills"):
        assert (project / skills_root / "example-skill" / "SKILL.md").is_file()


def test_sync_reports_post_apply_state_and_action(tmp_catalog, tmp_project):
    """A row must describe the world after sync ran, not before it started."""
    skills_dir = tmp_catalog()
    row = _run(tmp_project, skills_dir)["example-skill@claude"]
    assert row.final_state == SkillState.CURRENT
    assert row.action == "installed"


def test_sync_reports_update_after_catalog_change(tmp_catalog, tmp_project):
    skills_dir = tmp_catalog()
    _run(tmp_project, skills_dir, version="0.3.0")
    _edit_catalog(skills_dir)
    row = _run(tmp_project, skills_dir, version="0.4.0")["example-skill@claude"]
    assert row.final_state == SkillState.CURRENT
    assert row.action == "updated"


def test_forced_repair_reports_current_not_conflicted(tmp_catalog, tmp_project):
    skills_dir = tmp_catalog()
    _run(tmp_project, skills_dir)
    edited = tmp_project / ".claude" / "skills" / "example-skill" / "SKILL.md"
    edited.write_text("HAND EDITED\n")

    row = _run(tmp_project, skills_dir, force=True)["example-skill@claude"]

    assert row.final_state == SkillState.CURRENT
    assert row.action == "updated"
    assert all(s.state == SkillState.CURRENT for s in status(tmp_project, skills_dir, "0.3.0"))


def test_unforced_conflict_still_reports_conflicted(tmp_catalog, tmp_project):
    skills_dir = tmp_catalog()
    _run(tmp_project, skills_dir)
    edited = tmp_project / ".claude" / "skills" / "example-skill" / "SKILL.md"
    edited.write_text("HAND EDITED\n")

    row = _run(tmp_project, skills_dir)["example-skill@claude"]

    assert row.final_state == SkillState.CONFLICTED
    assert row.action == "conflict"


def test_missing_catalog_never_removes_a_projection(tmp_catalog, tmp_project):
    """A typo in --skills-dir must not be read as 'the catalog is now empty'."""
    skills_dir = tmp_catalog()
    _run(tmp_project, skills_dir)
    projected = tmp_project / ".claude" / "skills" / "example-skill"

    with pytest.raises(ValueError, match="skill catalog directory not found"):
        sync(tmp_project, skills_dir.parent / "gone", "0.3.0")

    assert projected.is_dir()


def test_explicit_harness_is_an_operational_scope_not_manifest_policy(tmp_catalog, tmp_project):
    """Durable harness intent belongs in speed.toml, not generated state."""
    skills_dir = tmp_catalog()
    (tmp_project / ".agents").mkdir(parents=True, exist_ok=True)

    _run(tmp_project, skills_dir, only_harness="codex")
    assert "selected_harnesses" not in load_manifest(tmp_project)
    assert not (tmp_project / ".claude" / "skills").exists()


def test_detection_still_applies_when_no_harness_was_chosen(tmp_catalog, tmp_project):
    skills_dir = tmp_catalog()
    (tmp_project / ".agents").mkdir(parents=True, exist_ok=True)

    _run(tmp_project, skills_dir)

    assert "selected_harnesses" not in load_manifest(tmp_project)
    assert {r.harness for r in status(tmp_project, skills_dir, "0.3.0")} == {
        "claude",
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

    assert [r.state for r in status(tmp_project, skills_dir, "0.3.0")] == [SkillState.ABSENT]

    _run(tmp_project, skills_dir)  # no --force

    assert (projected / "SKILL.md").is_file()


def test_partial_deletion_is_still_a_conflict(tmp_catalog, tmp_project):
    """Only a wholly missing projection is unambiguous; a partial one is not."""
    skills_dir = tmp_catalog()
    _run(tmp_project, skills_dir)
    (tmp_project / ".claude" / "skills" / "example-skill" / "references" / "notes.md").unlink()

    assert [r.state for r in status(tmp_project, skills_dir, "0.3.0")] == [SkillState.CONFLICTED]


def test_multiple_explicit_harnesses_are_supported_in_one_operation(tmp_catalog, tmp_project):
    skills_dir = tmp_catalog()
    (tmp_project / ".agents").mkdir(parents=True, exist_ok=True)

    _run(tmp_project, skills_dir, only_harness=("claude", "codex"))

    assert "selected_harnesses" not in load_manifest(tmp_project)
    assert {r.harness for r in status(
        tmp_project, skills_dir, "0.3.0", only_harness=("claude", "codex")
    )} == {
        "claude",
        "codex",
    }


def _poison_manifest(project, key, files):
    """Write a manifest entry under an arbitrary key, as a bad commit would."""
    path = project / ".speed" / "skills" / "manifest.json"
    data = json.loads(path.read_text())
    data["harnesses"]["claude"]["skills"][key] = {"files": files}
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

    skills = load_manifest(tmp_project)["harnesses"]["claude"]["skills"]
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

    assert [r.state for r in status(tmp_project, skills_dir, "0.3.0")] == [SkillState.CURRENT]


def test_failure_on_a_later_harness_keeps_earlier_writes_recorded(
    tmp_catalog, tmp_path
):
    """A half-finished sync must be resumable, not permanently conflicted."""
    skills_dir = tmp_catalog()
    project = tmp_path / "two-harness"
    (project / ".claude").mkdir(parents=True)
    (project / ".agents").mkdir(parents=True)
    # A regular file where codex needs a directory: claude is written
    # first, then codex raises part-way through the same sync.
    (project / ".agents" / "skills").write_text("not a directory\n")

    with pytest.raises(OSError):
        sync(project, skills_dir, "0.3.0")

    written = project / ".claude" / "skills" / "example-skill" / "SKILL.md"
    assert written.is_file()
    rows = status(project, skills_dir, "0.3.0", only_harness="claude")
    assert [r.state for r in rows] == [SkillState.CURRENT]


def test_a_different_install_leaves_a_committed_projection_alone(
    tmp_catalog, tmp_project
):
    """Teammates on different SPEED builds must not fight over the manifest."""
    skills_dir = tmp_catalog()
    _run(tmp_project, skills_dir, version="install-a")
    manifest = tmp_project / ".speed" / "skills" / "manifest.json"
    projected = tmp_project / ".claude" / "skills" / "example-skill" / "SKILL.md"
    m0, p0 = manifest.stat().st_mtime_ns, projected.stat().st_mtime_ns

    assert [r.state for r in status(tmp_project, skills_dir, "install-b")] == [SkillState.CURRENT]

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
    assert [r.state for r in status(tmp_project, skills_dir, "0.3.0")] == [SkillState.CURRENT]


# ── Replacing a projection must be all-or-nothing ──────────────────────────


def _tree(root):
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_a_failed_write_leaves_the_previous_projection_intact(
    tmp_catalog, tmp_project, monkeypatch
):
    """An update that dies half-way must not strand a partial skill on disk."""
    skills_dir = tmp_catalog()
    _run(tmp_project, skills_dir, version="0.3.0")
    installed = tmp_project / ".claude" / "skills" / "example-skill"
    before = _tree(installed)
    _edit_catalog(skills_dir)

    real_write = Path.write_bytes
    calls = {"n": 0}

    def flaky(self, data):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("no space left on device")
        return real_write(self, data)

    monkeypatch.setattr(Path, "write_bytes", flaky)
    with pytest.raises(OSError):
        sync(tmp_project, skills_dir, "0.4.0")
    monkeypatch.undo()

    assert _tree(installed) == before
    assert [r.state for r in status(tmp_project, skills_dir, "0.4.0")] == [SkillState.STALE]
    assert [p.name for p in installed.parent.iterdir()] == ["example-skill"]


def test_a_replaced_projection_drops_files_the_catalog_no_longer_ships(
    tmp_catalog, tmp_project
):
    skills_dir = tmp_catalog()
    (skills_dir / "example-skill" / "references" / "old.md").write_text(
        "retired\n", encoding="utf-8"
    )
    _run(tmp_project, skills_dir, version="0.3.0")
    installed = tmp_project / ".claude" / "skills" / "example-skill"
    assert (installed / "references" / "old.md").is_file()

    (skills_dir / "example-skill" / "references" / "old.md").unlink()
    _run(tmp_project, skills_dir, version="0.4.0")

    assert not (installed / "references" / "old.md").exists()
    assert (installed / "SKILL.md").is_file()


# ── A projection path can already hold something SPEED did not write ───────


def test_a_file_where_a_skill_belongs_is_a_conflict_not_an_overwrite(
    tmp_catalog, tmp_project
):
    skills_dir = tmp_catalog()
    occupied = tmp_project / ".claude" / "skills" / "example-skill"
    occupied.parent.mkdir(parents=True)
    occupied.write_text("someone else's file\n", encoding="utf-8")

    rows = _run(tmp_project, skills_dir)

    assert rows["example-skill@claude"].final_state == SkillState.CONFLICTED
    assert occupied.read_text(encoding="utf-8") == "someone else's file\n"


def test_force_replaces_a_file_occupying_the_projection_path(
    tmp_catalog, tmp_project
):
    skills_dir = tmp_catalog()
    occupied = tmp_project / ".claude" / "skills" / "example-skill"
    occupied.parent.mkdir(parents=True)
    occupied.write_text("someone else's file\n", encoding="utf-8")

    _run(tmp_project, skills_dir, force=True)

    assert (occupied / "SKILL.md").is_file()


def test_a_symlinked_projection_is_a_conflict(tmp_catalog, tmp_project, tmp_path):
    """Following the link would write outside the project's harness root."""
    skills_dir = tmp_catalog()
    outside = tmp_path / "outside"
    outside.mkdir()
    dest = tmp_project / ".claude" / "skills" / "example-skill"
    dest.parent.mkdir(parents=True)
    dest.symlink_to(outside, target_is_directory=True)

    rows = _run(tmp_project, skills_dir)

    assert rows["example-skill@claude"].final_state == SkillState.CONFLICTED
    assert list(outside.iterdir()) == []


# ── The manifest has to be able to converge ────────────────────────────────


def _empty_catalog(tmp_path):
    empty = tmp_path / "empty-catalog"
    empty.mkdir()
    return empty


def test_a_manifest_entry_with_no_projection_left_is_dropped(
    tmp_catalog, tmp_project, tmp_path
):
    """Skill gone from the catalog, projection already deleted: the record must go."""
    skills_dir = tmp_catalog()
    _run(tmp_project, skills_dir)
    shutil.rmtree(tmp_project / ".claude" / "skills" / "example-skill")

    rows = _run(tmp_project, _empty_catalog(tmp_path))

    assert rows["example-skill@claude"].action == "removed"
    assert load_manifest(tmp_project)["harnesses"]["claude"]["skills"] == {}


def test_the_converged_manifest_stays_quiet_on_the_next_sync(
    tmp_catalog, tmp_project, tmp_path
):
    skills_dir = tmp_catalog()
    empty = _empty_catalog(tmp_path)
    _run(tmp_project, skills_dir)
    shutil.rmtree(tmp_project / ".claude" / "skills" / "example-skill")
    _run(tmp_project, empty)

    assert _run(tmp_project, empty) == {}
    assert status(tmp_project, empty, "0.3.0") == []
