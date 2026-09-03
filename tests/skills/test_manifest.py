import json

import pytest

from skills.manifest import (
    WRONG_TYPE,
    classify_skill,
    hash_bytes,
    hash_disk,
    load_manifest,
    manifest_state,
    save_manifest,
)
from skills import CURRENT, STALE, CONFLICTED, ORPHANED, ABSENT


def _hashes(d):  # rendered dict -> hash map
    return {k: hash_bytes(v) for k, v in d.items()}


R = {"SKILL.md": b"v1", "references/n.md": b"ref"}


def test_absent():
    assert classify_skill(R, {}, None) == ABSENT


def test_current():
    entry = {"files": _hashes(R)}
    assert classify_skill(R, _hashes(R), entry) == CURRENT


def test_stale_when_catalog_changed_but_disk_unmodified():
    entry = {"files": _hashes(R)}
    r2 = {"SKILL.md": b"v2", "references/n.md": b"ref"}
    assert classify_skill(r2, _hashes(R), entry) == STALE


def test_conflicted_when_disk_edited():
    entry = {"files": _hashes(R)}
    disk = dict(_hashes(R))
    disk["SKILL.md"] = hash_bytes(b"user-edit")
    assert classify_skill(R, disk, entry) == CONFLICTED


def test_conflicted_when_unknown_preexisting_files():
    assert classify_skill(R, _hashes(R), None) == CONFLICTED


def test_orphaned_when_removed_and_unmodified():
    entry = {"files": _hashes(R)}
    assert classify_skill(None, _hashes(R), entry) == ORPHANED


def test_orphaned_edited_downgrades_to_conflicted():
    entry = {"files": _hashes(R)}
    disk = dict(_hashes(R))
    disk["SKILL.md"] = hash_bytes(b"user-edit")
    assert classify_skill(None, disk, entry) == CONFLICTED


# ── Manifest schema (a committed file is untrusted input) ──────────────────

MANIFEST_REL = ".speed/skills/manifest.json"


def _write_manifest(project, payload):
    path = project / MANIFEST_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_load_manifest_of_a_fresh_project_is_the_empty_record(tmp_path):
    assert load_manifest(tmp_path) == {"catalog_version": None, "surfaces": {}}


def test_load_manifest_round_trips_what_save_wrote(tmp_path):
    data = {"catalog_version": "0.3.0", "surfaces": {}, "selected_surfaces": ["codex"]}
    save_manifest(tmp_path, data)
    assert load_manifest(tmp_path) == data


@pytest.mark.parametrize(
    ("payload", "where"),
    [
        ([], "document root"),
        ({"surfaces": None}, "surfaces"),
        ({"surfaces": {"claude_code": []}}, "surfaces.claude_code"),
        ({"surfaces": {"claude_code": {"root": 7}}}, "surfaces.claude_code.root"),
        (
            {"surfaces": {"claude_code": {"skills": "none"}}},
            "surfaces.claude_code.skills",
        ),
        (
            {"surfaces": {"claude_code": {"skills": {"a": "x"}}}},
            "surfaces.claude_code.skills.a",
        ),
        (
            {"surfaces": {"claude_code": {"skills": {"a": {"files": []}}}}},
            "surfaces.claude_code.skills.a.files",
        ),
        (
            {"surfaces": {"claude_code": {"skills": {"a": {"files": {"x": 1}}}}}},
            "surfaces.claude_code.skills.a.files.x",
        ),
        ({"selected_surfaces": "codex"}, "selected_surfaces"),
        ({"selected_surfaces": [2]}, "selected_surfaces[0]"),
    ],
)
def test_malformed_manifest_names_the_offending_path(tmp_path, payload, where):
    _write_manifest(tmp_path, payload)

    with pytest.raises(ValueError, match="invalid skill manifest") as excinfo:
        load_manifest(tmp_path)

    assert where in str(excinfo.value)


def test_unparseable_manifest_is_reported_as_an_invalid_manifest(tmp_path):
    path = tmp_path / MANIFEST_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid skill manifest"):
        load_manifest(tmp_path)


def _write_skill(root, name, managed):
    """Put a SKILL.md under ``root``, stamped as a projection or not."""
    skill = root / name
    skill.mkdir(parents=True)
    provenance = "x-workbench-managed: true\n" if managed else ""
    skill.joinpath("SKILL.md").write_text(
        f"---\nname: {name}\ndescription: fixture\n{provenance}---\n\nBody.\n",
        encoding="utf-8",
    )


def test_manifest_state_separates_a_new_install_from_a_lost_record(tmp_path):
    project = tmp_path / "proj"
    skills_root = project / ".claude" / "skills"
    (project / ".claude").mkdir(parents=True)
    assert manifest_state(project) == "new"

    _write_skill(skills_root, "example-skill", managed=True)
    assert manifest_state(project) == "lost"

    save_manifest(project, {"catalog_version": None, "surfaces": {}})
    assert manifest_state(project) == "present"


def test_a_hand_written_skill_is_not_a_lost_projection(tmp_path):
    """A harness skills root also holds skills the user wrote themselves.

    Reporting those as a lost manifest tells someone their record went missing
    when Workbench never wrote anything in that project.
    """
    project = tmp_path / "proj"
    _write_skill(project / ".claude" / "skills", "my-own-skill", managed=False)

    assert manifest_state(project) == "new"


def test_save_manifest_keeps_the_previous_record_when_the_commit_fails(
    tmp_path, monkeypatch
):
    """An interrupted write must not truncate the only record of managed files."""
    import skills.manifest as manifest_module

    save_manifest(tmp_path, {"catalog_version": "0.3.0", "surfaces": {}})
    before = (tmp_path / MANIFEST_REL).read_text(encoding="utf-8")

    def refuse(src, dst):
        raise OSError("interrupted")

    monkeypatch.setattr(manifest_module.os, "replace", refuse)

    with pytest.raises(OSError):
        save_manifest(tmp_path, {"catalog_version": "0.4.0", "surfaces": {}})

    assert (tmp_path / MANIFEST_REL).read_text(encoding="utf-8") == before
    leftovers = sorted(p.name for p in (tmp_path / ".speed" / "skills").iterdir())
    assert leftovers == ["manifest.json"]


def test_manifest_reads_as_utf8_under_an_ascii_locale(tmp_path, ascii_locale_python):
    """The same manifest must load identically on every teammate's machine."""
    _write_manifest(tmp_path, {"catalog_version": "0.3.0-ünïcode", "surfaces": {}})

    result = ascii_locale_python(
        "from skills.manifest import load_manifest\n"
        f"data = load_manifest({str(tmp_path)!r})\n"
        "assert data['catalog_version'].endswith('code'), data\n"
        "print('ok')\n"
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


# ── Reading disk state (a projection path can hold anything) ───────────────


def test_hash_disk_of_a_missing_projection_is_empty(tmp_path):
    assert hash_disk(tmp_path / "nope") == {}


def test_hash_disk_reports_a_file_where_a_projection_belongs(tmp_path):
    occupied = tmp_path / "example-skill"
    occupied.write_text("someone else's file\n", encoding="utf-8")

    assert hash_disk(occupied) is WRONG_TYPE


def test_hash_disk_refuses_a_symlinked_projection_directory(tmp_path):
    real = tmp_path / "elsewhere"
    real.mkdir()
    (real / "SKILL.md").write_text("outside\n", encoding="utf-8")
    link = tmp_path / "example-skill"
    link.symlink_to(real, target_is_directory=True)

    assert hash_disk(link) is WRONG_TYPE


def test_hash_disk_refuses_to_read_through_a_symlink_inside_a_projection(tmp_path):
    outside = tmp_path / "secret.txt"
    outside.write_text("secret\n", encoding="utf-8")
    dest = tmp_path / "example-skill"
    dest.mkdir()
    (dest / "SKILL.md").write_text("body\n", encoding="utf-8")
    (dest / "leak.txt").symlink_to(outside)

    assert hash_disk(dest) is WRONG_TYPE


def test_a_wrong_type_projection_path_is_a_conflict_not_an_absent_skill():
    assert classify_skill(R, WRONG_TYPE, None) == CONFLICTED
    assert classify_skill(R, WRONG_TYPE, {"files": _hashes(R)}) == CONFLICTED
    assert classify_skill(None, WRONG_TYPE, {"files": _hashes(R)}) == CONFLICTED


def test_a_manifest_entry_with_nothing_on_disk_is_orphaned_so_it_can_converge():
    """The skill left the catalog and its projection is gone: drop the record."""
    assert classify_skill(None, {}, {"files": _hashes(R)}) == ORPHANED
