import dataclasses
from pathlib import Path

import pytest

from skills import is_valid_skill_name, validate
from skills.targets import dest_dir, get_harness
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


# Real YAML parsing means front matter can now hand the engine an int, a float,
# a bool or None where it expects a string. The contract is enforced here so no
# consumer downstream has to re-check the type.


@pytest.mark.parametrize(
    "value, kind",
    [(True, "bool"), (1.0, "float"), (2, "int"), (None, "NoneType"), (["a"], "list")],
)
def test_a_mistyped_metadata_field_is_reported_with_its_type(value, kind):
    pkg = _pkg(meta={"name": "example-skill", "description": value})

    violations = validate_package(pkg)

    assert [item.code for item in violations] == [validate.INVALID_METADATA_TYPE]
    assert kind in violations[0].reason
    assert "quote the value" in violations[0].reason


def test_a_mistyped_name_is_not_also_reported_as_a_mismatch():
    """One cause, one violation: `name: true` is a type error, not a rename."""
    pkg = _pkg(meta={"name": True, "description": "ok"})

    codes = {item.code for item in validate_package(pkg)}

    assert codes == {validate.INVALID_METADATA_TYPE}
    assert validate.NAME_MISMATCH not in codes


def test_a_mistyped_description_does_not_crash_on_strip():
    """`.strip()` on a float used to raise AttributeError from inside validate."""
    assert validate_package(_pkg(meta={"name": "example-skill", "description": 1.5}))


def test_a_non_string_version_is_rejected_so_the_manifest_records_a_string():
    pkg = _pkg(meta={"name": "example-skill", "description": "ok", "version": 1.0})

    violations = validate_package(pkg)

    assert [item.code for item in violations] == [validate.INVALID_METADATA_TYPE]
    assert "'version'" in violations[0].reason


def test_a_quoted_version_is_accepted():
    assert validate_package(
        _pkg(meta={"name": "example-skill", "description": "ok", "version": "1.0"})
    ) == []


@pytest.mark.parametrize(
    "name",
    ["foo\n", "foo\r", "example-skill\n", "a\n"],
)
def test_a_trailing_newline_is_not_a_legal_skill_name(name):
    """`$` also matches immediately before a final newline, `\\Z` does not.

    The pattern is the single definition of a legal name, and `dest_dir` builds
    a projection path from whatever it accepts while `_prune_unsafe_names`
    declines to clean up anything it calls legal. A manifest reaches both as
    untrusted input, and POSIX permits a newline in a filename, so the one
    trailing `\\n` that slipped through was a real hole in the whitelist.
    """
    assert not is_valid_skill_name(name)
    harness = get_harness("claude")
    with pytest.raises(ValueError):
        dest_dir(harness, name, Path("/tmp/does-not-matter"))


@pytest.mark.parametrize("name", ["a", "foo", "a-b-9", "example-skill"])
def test_ordinary_names_stay_legal(name):
    assert is_valid_skill_name(name)


def test_a_junk_symlink_is_not_a_package_violation(tmp_path):
    """Junk never enters the package, so a link where junk sits is not the author's problem."""
    root = tmp_path / "example-skill"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside\n")
    (root / ".DS_Store").symlink_to(outside)
    pkg = _pkg()
    pkg.root = root

    assert validate_package(pkg) == []


def test_a_missing_name_is_reported_as_missing_not_as_a_mismatch():
    """`name '' != directory 'x'` sent authors looking for a name they never wrote."""
    codes = {item.code for item in validate_package(_pkg(meta={"description": "ok"}))}

    assert codes == {validate.MISSING_NAME}


def test_a_blank_name_reads_the_same_as_an_absent_one():
    """Declared-but-empty is the author's same mistake, so it gets the same code."""
    for value in ("", "   "):
        codes = {
            item.code
            for item in validate_package(_pkg(meta={"name": value, "description": "ok"}))
        }
        assert codes == {validate.MISSING_NAME}, value


def test_a_name_that_disagrees_with_its_directory_is_still_a_mismatch():
    """The rename case keeps its own code: something was declared, just wrongly."""
    codes = {
        item.code
        for item in validate_package(_pkg(meta={"name": "other", "description": "ok"}))
    }

    assert codes == {validate.NAME_MISMATCH}
