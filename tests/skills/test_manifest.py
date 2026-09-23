import json

import pytest

from skills.manifest import (
    WrongType,
    classify_skill,
    inspect_skill,
    hash_bytes,
    hash_disk,
    load_manifest,
    manifest_state,
    save_manifest,
)
from skills import PATHS
from skills.models import SkillState


def _hashes(d):  # rendered dict -> hash map
    return {k: hash_bytes(v) for k, v in d.items()}


R = {"SKILL.md": b"v1", "references/n.md": b"ref"}


def test_absent():
    assert classify_skill(R, {}, None) == SkillState.ABSENT


def test_current():
    entry = {"files": _hashes(R)}
    assert classify_skill(R, _hashes(R), entry) == SkillState.CURRENT


def test_stale_when_catalog_changed_but_disk_unmodified():
    entry = {"files": _hashes(R)}
    r2 = {"SKILL.md": b"v2", "references/n.md": b"ref"}
    assert classify_skill(r2, _hashes(R), entry) == SkillState.STALE


def test_conflicted_when_disk_edited():
    entry = {"files": _hashes(R)}
    disk = dict(_hashes(R))
    disk["SKILL.md"] = hash_bytes(b"user-edit")
    assert classify_skill(R, disk, entry) == SkillState.CONFLICTED


def test_conflicted_when_unknown_preexisting_files():
    assert classify_skill(R, _hashes(R), None) == SkillState.CONFLICTED


def test_orphaned_when_removed_and_unmodified():
    entry = {"files": _hashes(R)}
    assert classify_skill(None, _hashes(R), entry) == SkillState.ORPHANED


def test_orphaned_edited_downgrades_to_conflicted():
    entry = {"files": _hashes(R)}
    disk = dict(_hashes(R))
    disk["SKILL.md"] = hash_bytes(b"user-edit")
    assert classify_skill(None, disk, entry) == SkillState.CONFLICTED


# ── Manifest schema (a committed file is untrusted input) ──────────────────

MANIFEST_REL = PATHS.manifest


def _write_manifest(project, payload):
    path = project / MANIFEST_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_load_manifest_of_a_fresh_project_is_the_empty_record(tmp_path):
    assert load_manifest(tmp_path) == {"catalog_version": None, "harnesses": {}}


def test_load_manifest_round_trips_what_save_wrote(tmp_path):
    data = {"catalog_version": "0.3.0", "harnesses": {}, "selected_harnesses": ["codex"]}
    save_manifest(tmp_path, data)
    assert load_manifest(tmp_path) == data


@pytest.mark.parametrize(
    ("payload", "where"),
    [
        ([], "document root"),
        ({"harnesses": None}, "harnesses"),
        ({"harnesses": {"claude": []}}, "harnesses.claude"),
        ({"harnesses": {"claude": {"root": 7}}}, "harnesses.claude.root"),
        (
            {"harnesses": {"claude": {"skills": "none"}}},
            "harnesses.claude.skills",
        ),
        (
            {"harnesses": {"claude": {"skills": {"a": "x"}}}},
            "harnesses.claude.skills.a",
        ),
        (
            {"harnesses": {"claude": {"skills": {"a": {"files": []}}}}},
            "harnesses.claude.skills.a.files",
        ),
        (
            {"harnesses": {"claude": {"skills": {"a": {"files": {"x": 1}}}}}},
            "harnesses.claude.skills.a.files.x",
        ),
        ({"selected_harnesses": "codex"}, "selected_harnesses"),
        ({"selected_harnesses": [2]}, "selected_harnesses[0]"),
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

    save_manifest(project, {"catalog_version": None, "harnesses": {}})
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

    save_manifest(tmp_path, {"catalog_version": "0.3.0", "harnesses": {}})
    before = (tmp_path / MANIFEST_REL).read_text(encoding="utf-8")

    def refuse(src, dst):
        raise OSError("interrupted")

    monkeypatch.setattr(manifest_module.os, "replace", refuse)

    with pytest.raises(OSError):
        save_manifest(tmp_path, {"catalog_version": "0.4.0", "harnesses": {}})

    assert (tmp_path / MANIFEST_REL).read_text(encoding="utf-8") == before
    leftovers = sorted(p.name for p in (tmp_path / ".speed" / "skills").iterdir())
    assert leftovers == ["manifest.json"]


def test_manifest_reads_as_utf8_under_an_ascii_locale(tmp_path, ascii_locale_python):
    """The same manifest must load identically on every teammate's machine."""
    _write_manifest(tmp_path, {"catalog_version": "0.3.0-ünïcode", "harnesses": {}})

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

    assert isinstance(hash_disk(occupied), WrongType)


def test_hash_disk_refuses_a_symlinked_projection_directory(tmp_path):
    real = tmp_path / "elsewhere"
    real.mkdir()
    (real / "SKILL.md").write_text("outside\n", encoding="utf-8")
    link = tmp_path / "example-skill"
    link.symlink_to(real, target_is_directory=True)

    assert isinstance(hash_disk(link), WrongType)


def test_hash_disk_refuses_to_read_through_a_symlink_inside_a_projection(tmp_path):
    outside = tmp_path / "secret.txt"
    outside.write_text("secret\n", encoding="utf-8")
    dest = tmp_path / "example-skill"
    dest.mkdir()
    (dest / "SKILL.md").write_text("body\n", encoding="utf-8")
    (dest / "leak.txt").symlink_to(outside)

    assert isinstance(hash_disk(dest), WrongType)


def test_a_wrong_type_projection_path_is_a_conflict_not_an_absent_skill():
    assert classify_skill(R, WrongType("occupied"), None) == SkillState.CONFLICTED
    assert classify_skill(R, WrongType("occupied"), {"files": _hashes(R)}) == SkillState.CONFLICTED
    assert classify_skill(None, WrongType("occupied"), {"files": _hashes(R)}) == SkillState.CONFLICTED


def test_a_manifest_entry_with_nothing_on_disk_is_orphaned_so_it_can_converge():
    """The skill left the catalog and its projection is gone: drop the record."""
    assert classify_skill(None, {}, {"files": _hashes(R)}) == SkillState.ORPHANED


def test_hash_disk_ignores_a_junk_symlink_instead_of_condemning_the_skill(tmp_path):
    """A Finder-synced `.DS_Store` alias is junk, whatever kind of file it is.

    Excluding junk only from the hash while still testing it for link-ness made
    a stray alias classify the whole projection `conflicted`, so converging it
    needed `--force` and a rewrite nobody asked for.
    """
    outside = tmp_path / "elsewhere.txt"
    outside.write_text("not ours\n", encoding="utf-8")
    dest = tmp_path / "example-skill"
    dest.mkdir()
    (dest / "SKILL.md").write_text("body\n", encoding="utf-8")
    (dest / ".DS_Store").symlink_to(outside)

    assert hash_disk(dest) == {"SKILL.md": hash_bytes(b"body\n")}


def test_hash_disk_ignores_a_symlinked_junk_directory(tmp_path):
    """`__pycache__` is excluded as a name, so it is never descended or judged."""
    elsewhere = tmp_path / "cache"
    elsewhere.mkdir()
    (elsewhere / "mod.pyc").write_bytes(b"compiled")
    dest = tmp_path / "example-skill"
    (dest / "scripts").mkdir(parents=True)
    (dest / "SKILL.md").write_text("body\n", encoding="utf-8")
    (dest / "scripts" / "run.py").write_text("print()\n", encoding="utf-8")
    (dest / "scripts" / "__pycache__").symlink_to(elsewhere, target_is_directory=True)

    assert hash_disk(dest) == {
        "SKILL.md": hash_bytes(b"body\n"),
        "scripts/run.py": hash_bytes(b"print()\n"),
    }


def test_hash_disk_still_refuses_a_symlink_that_could_have_been_projected(tmp_path):
    """Junk exclusion must not widen into "ignore links": render() emits bytes."""
    outside = tmp_path / "secret.txt"
    outside.write_text("secret\n", encoding="utf-8")
    dest = tmp_path / "example-skill"
    dest.mkdir()
    (dest / "SKILL.md").write_text("body\n", encoding="utf-8")
    (dest / "reference.md").symlink_to(outside)

    disk = hash_disk(dest)

    assert isinstance(disk, WrongType)
    assert disk.path == "reference.md"
