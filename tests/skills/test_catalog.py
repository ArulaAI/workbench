from pathlib import Path

import pytest

from skills.catalog import load_catalog, load_package

REPO = Path(__file__).resolve().parents[2]


def test_real_catalog_contains_only_health():
    assert [pkg.name for pkg in load_catalog(REPO / "skills")] == [
        "workbench-health"
    ]


def test_load_package_reads_meta_body_and_files(tmp_catalog):
    skills_dir = tmp_catalog()
    pkg = load_package(skills_dir / "example-skill")
    assert pkg.name == "example-skill"
    assert pkg.meta["description"] == "A test skill"
    assert "SKILL.md" in pkg.files
    assert pkg.files["references/notes.md"] == b"ref body\n"


def test_load_catalog_discovers_and_sorts(tmp_catalog):
    skills_dir = tmp_catalog()
    tmp_catalog(name="another-skill")  # same tmp_path/skills parent
    names = [p.name for p in load_catalog(skills_dir)]
    assert names == ["another-skill", "example-skill"]


def test_load_catalog_missing_dir_is_empty(tmp_path):
    assert load_catalog(tmp_path / "nope") == []


def test_load_catalog_rejects_invalid_package(tmp_catalog):
    skills_dir = tmp_catalog(name="Bad_Name")

    with pytest.raises(ValueError, match="invalid skill catalog"):
        load_catalog(skills_dir)


def test_load_package_excludes_junk_files(tmp_catalog):
    skills_dir = tmp_catalog(
        extra={
            "scripts/health.py": "print('healthy')\n",
            "scripts/__pycache__/health.cpython-311.pyc": "BYTECODE",
            ".DS_Store": "macjunk",
        }
    )
    pkg = load_package(skills_dir / "example-skill")
    assert "scripts/health.py" in pkg.files
    assert not any("__pycache__" in rel for rel in pkg.files)
    assert not any(rel.endswith(".pyc") for rel in pkg.files)
    assert ".DS_Store" not in pkg.files
