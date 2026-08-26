from pathlib import Path

from skills.catalog import SkillPackage
from skills.validate import validate_package, validate_catalog


def _pkg(name="workbench-draft", meta=None, files=None):
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
    v = validate_package(_pkg(meta={"name": "workbench-draft", "description": ""}))
    assert any("description" in x.reason for x in v)


def test_missing_skill_md_flagged():
    v = validate_package(_pkg(files={}))
    assert any("SKILL.md" in x.reason for x in v)


def test_path_traversal_flagged():
    v = validate_package(_pkg(files={"SKILL.md": b".", "../evil.md": b"x"}))
    assert any(".." in (x.path or "") for x in v)


def test_duplicate_names_flagged():
    v = validate_catalog([_pkg(), _pkg()])
    assert any("duplicate" in x.reason.lower() for x in v)
