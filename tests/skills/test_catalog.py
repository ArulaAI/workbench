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
