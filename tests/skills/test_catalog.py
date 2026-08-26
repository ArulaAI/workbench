from skills.catalog import load_catalog, load_package


def test_load_package_reads_meta_body_and_files(tmp_catalog):
    skills_dir = tmp_catalog()
    pkg = load_package(skills_dir / "workbench-draft")
    assert pkg.name == "workbench-draft"
    assert pkg.meta["description"] == "A test skill"
    assert "SKILL.md" in pkg.files
    assert pkg.files["references/notes.md"] == b"ref body\n"


def test_load_catalog_discovers_and_sorts(tmp_catalog):
    skills_dir = tmp_catalog()
    tmp_catalog(name="another-skill")  # same tmp_path/skills parent
    names = [p.name for p in load_catalog(skills_dir)]
    assert names == ["another-skill", "workbench-draft"]


def test_load_catalog_missing_dir_is_empty(tmp_path):
    assert load_catalog(tmp_path / "nope") == []


def test_load_package_excludes_junk_files(tmp_catalog):
    skills_dir = tmp_catalog(
        extra={
            "scripts/hello.py": "print('hi')\n",
            "scripts/__pycache__/hello.cpython-311.pyc": "BYTECODE",
            ".DS_Store": "macjunk",
        }
    )
    pkg = load_package(skills_dir / "workbench-draft")
    assert "scripts/hello.py" in pkg.files
    assert not any("__pycache__" in rel for rel in pkg.files)
    assert not any(rel.endswith(".pyc") for rel in pkg.files)
    assert ".DS_Store" not in pkg.files
