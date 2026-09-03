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


def test_load_catalog_missing_dir_fails_closed(tmp_path):
    """A missing catalog is an installation error, never an empty catalog."""
    with pytest.raises(ValueError, match="skill catalog directory not found"):
        load_catalog(tmp_path / "nope")


def test_load_catalog_rejects_a_file_in_place_of_a_directory(tmp_path):
    not_a_dir = tmp_path / "catalog"
    not_a_dir.write_text("")

    with pytest.raises(ValueError, match="skill catalog directory not found"):
        load_catalog(not_a_dir)


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


# ── Symlinks: refused before anything they point at is read ────────────────


def test_a_symlinked_file_is_refused_and_never_read(tmp_catalog, tmp_path):
    skills_dir = tmp_catalog()
    secret = tmp_path / "secret.txt"
    secret.write_bytes(b"SECRET")
    (skills_dir / "example-skill" / "leak.txt").symlink_to(secret)

    pkg = load_package(skills_dir / "example-skill")

    assert b"SECRET" not in b"".join(pkg.files.values())
    assert "leak.txt" not in pkg.files
    assert any("symlink" in reason for _, reason in pkg.errors)


def test_a_symlinked_directory_is_refused_and_never_descended(tmp_catalog, tmp_path):
    skills_dir = tmp_catalog()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_bytes(b"SECRET")
    (skills_dir / "example-skill" / "linked").symlink_to(
        outside, target_is_directory=True
    )

    pkg = load_package(skills_dir / "example-skill")

    assert not any(rel.startswith("linked") for rel in pkg.files)
    assert b"SECRET" not in b"".join(pkg.files.values())


def test_load_catalog_rejects_a_symlink_even_when_it_stays_inside_the_package(
    tmp_catalog,
):
    """Projection copies bytes, so a link has no meaning a package can rely on."""
    skills_dir = tmp_catalog()
    (skills_dir / "example-skill" / "alias.md").symlink_to(
        skills_dir / "example-skill" / "references" / "notes.md"
    )

    with pytest.raises(ValueError, match="symlink"):
        load_catalog(skills_dir)


# ── Validation must see every candidate package ────────────────────────────


def test_a_directory_without_skill_md_is_reported_not_ignored(tmp_catalog):
    """The 'SKILL.md required' rule is unreachable if the loader filters first."""
    skills_dir = tmp_catalog()
    (skills_dir / "no-skill-md").mkdir()

    with pytest.raises(ValueError, match="missing SKILL.md"):
        load_catalog(skills_dir)


def test_hidden_and_generated_directories_are_not_candidate_packages(tmp_catalog):
    skills_dir = tmp_catalog()
    (skills_dir / "__pycache__").mkdir()
    (skills_dir / ".notes").mkdir()

    assert [pkg.name for pkg in load_catalog(skills_dir)] == ["example-skill"]


# ── Encoding and front-matter syntax ───────────────────────────────────────


def test_skill_md_reads_as_utf8_under_an_ascii_locale(tmp_catalog, ascii_locale_python):
    """A catalog must load the same way on every teammate's machine."""
    skills_dir = tmp_catalog()
    (skills_dir / "example-skill" / "SKILL.md").write_text(
        "---\nname: example-skill\ndescription: Prüfen Sie den Zustand\n---\n\n# ok\n",
        encoding="utf-8",
    )

    result = ascii_locale_python(
        "from skills.catalog import load_catalog\n"
        f"pkgs = load_catalog({str(skills_dir)!r})\n"
        "assert len(pkgs[0].meta['description']) == 22, pkgs[0].meta\n"
        "print('ok')\n"
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_unterminated_front_matter_is_reported_as_a_syntax_error(tmp_catalog):
    skills_dir = tmp_catalog()
    (skills_dir / "example-skill" / "SKILL.md").write_text(
        "---\nname: example-skill\ndescription: no closing fence\n\n# body\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="front matter"):
        load_catalog(skills_dir)


def test_unterminated_front_matter_does_not_masquerade_as_a_missing_description(
    tmp_catalog,
):
    skills_dir = tmp_catalog()
    (skills_dir / "example-skill" / "SKILL.md").write_text(
        "---\nname: example-skill\ndescription: no closing fence\n\n# body\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError) as excinfo:
        load_catalog(skills_dir)

    assert "description" not in str(excinfo.value)
