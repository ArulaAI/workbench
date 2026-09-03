import dataclasses
from pathlib import Path

import pytest

from skills import validate
from skills.catalog import SkillPackage
from skills.validate import validate_package, validate_catalog


def _pkg(name="example-skill", meta=None, files=None):
    meta = meta if meta is not None else {"name": name, "description": "ok"}
    files = files if files is not None else {"SKILL.md": b"..."}
    return SkillPackage(name=name, root=Path("/x") / name, meta=meta, body="b", files=files)


def test_valid_package_has_no_violations():
    assert validate_package(_pkg()) == []


def test_name_dir_mismatch_flagged():
    v = validate_package(_pkg(meta={"name": "other", "description": "ok"}))
    assert any("name" in x.reason for x in v)


def test_bad_name_charset_flagged():
    v = validate_package(_pkg(name="Bad_Name", meta={"name": "Bad_Name", "description": "ok"}))
    assert any(x.reason for x in v)


def test_missing_description_flagged():
    v = validate_package(_pkg(meta={"name": "example-skill", "description": ""}))
    assert any("description" in x.reason for x in v)


def test_missing_skill_md_flagged():
    v = validate_package(_pkg(files={}))
    assert any("SKILL.md" in x.reason for x in v)


def test_path_traversal_flagged():
    v = validate_package(_pkg(files={"SKILL.md": b".", "../evil.md": b"x"}))
    assert any(".." in (x.path or "") for x in v)


def test_absolute_path_flagged():
    violations = validate_package(
        _pkg(files={"SKILL.md": b".", "/tmp/evil.md": b"x"})
    )

    assert any(item.path == "/tmp/evil.md" for item in violations)


def test_duplicate_names_flagged():
    v = validate_catalog([_pkg(), _pkg()])
    assert any("duplicate" in x.reason.lower() for x in v)


def test_escaping_symlink_flagged(tmp_path):
    root = tmp_path / "example-skill"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside\n")
    (root / "escape.txt").symlink_to(outside)
    pkg = _pkg()
    pkg.root = root

    violations = validate_package(pkg)

    assert any("symlink" in item.reason for item in violations)


def test_symlink_inside_the_package_is_flagged_too(tmp_path):
    """The contract bans links outright, so nothing has to resolve one to judge it."""
    root = tmp_path / "example-skill"
    (root / "references").mkdir(parents=True)
    (root / "references" / "notes.md").write_text("notes\n")
    (root / "alias.md").symlink_to(root / "references" / "notes.md")
    pkg = _pkg()
    pkg.root = root

    violations = validate_package(pkg)

    assert [item.path for item in violations] == ["alias.md"]


def test_a_symlink_is_reported_once_even_when_the_reader_already_saw_it(tmp_path):
    root = tmp_path / "example-skill"
    root.mkdir()
    (root / "alias.md").symlink_to(tmp_path / "outside.txt")
    pkg = _pkg()
    pkg.root = root
    pkg.errors = [("alias.md", "package files must not be symlinks")]

    violations = validate_package(pkg)

    assert [item.path for item in violations] == ["alias.md"]


def test_reader_errors_become_violations():
    pkg = _pkg()
    pkg.errors = [(None, "package directory must not be a symlink")]

    violations = validate_package(pkg)

    assert any("must not be a symlink" in item.reason for item in violations)


def test_reserved_provenance_key_is_rejected():
    """Projection sets x-workbench-*, so a package declaring one would lose it."""
    violations = validate_package(
        _pkg(
            meta={
                "name": "example-skill",
                "description": "ok",
                "x-workbench-managed": "false",
            }
        )
    )

    assert any("reserved front-matter key" in item.reason for item in violations)


def test_unreadable_front_matter_is_not_also_reported_as_a_missing_description():
    pkg = _pkg(meta={})
    pkg.errors = [("SKILL.md", "malformed front matter: the opening '---' has no closing '---'")]

    reasons = [item.reason for item in validate_package(pkg)]

    assert reasons == ["malformed front matter: the opening '---' has no closing '---'"]


def test_every_violation_carries_a_stable_code(tmp_path):
    """Callers should match on a code, not on prose that is free to improve."""
    pkg = SkillPackage(
        name="Bad_Name",
        root=tmp_path / "missing",
        meta={"x-workbench-managed": "true"},
        body="",
        files={},
    )

    violations = validate_package(pkg)

    codes = {item.code for item in violations}
    assert validate.MISSING_SKILL_MD in codes
    assert validate.INVALID_SKILL_NAME in codes
    assert validate.RESERVED_KEY in codes
    assert all(item.code for item in violations), "a violation with no code"


def test_a_violation_is_immutable_and_allows_a_pathless_finding(tmp_path):
    pkg = SkillPackage(
        name="Bad_Name", root=tmp_path / "missing", meta={}, body="", files={}
    )

    violations = validate_package(pkg)
    pathless = [item for item in violations if item.path is None]

    assert pathless, "a package-level violation should carry no path"
    with pytest.raises(dataclasses.FrozenInstanceError):
        pathless[0].reason = "rewritten"
