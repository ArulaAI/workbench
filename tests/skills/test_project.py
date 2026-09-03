import pytest

from skills.catalog import load_package
from skills.targets import SURFACES
from skills.project import render
from skills.frontmatter import parse


def test_render_injects_provenance_and_keeps_refs(tmp_catalog):
    skills_dir = tmp_catalog()
    pkg = load_package(skills_dir / "example-skill")
    out = render(pkg, SURFACES[0], "0.3.0")
    assert "references/notes.md" in out
    assert out["references/notes.md"] == b"ref body\n"
    meta, body = parse(out["SKILL.md"].decode())
    assert meta["name"] == "example-skill"
    assert meta["x-workbench-managed"] == "true"
    assert meta["x-workbench-source"] == "example-skill"
    assert "Do the thing." in body


def test_render_is_deterministic(tmp_catalog):
    skills_dir = tmp_catalog()
    pkg = load_package(skills_dir / "example-skill")
    assert render(pkg, SURFACES[0], "0.3.0") == render(pkg, SURFACES[0], "0.3.0")


def test_render_ignores_the_install_version(tmp_catalog):
    """Projections are committed, so their bytes cannot depend on who ran sync."""
    skills_dir = tmp_catalog()
    pkg = load_package(skills_dir / "example-skill")

    assert render(pkg, SURFACES[0], "0.3.0") == render(pkg, SURFACES[0], "9.9.9")
    meta, _ = parse(render(pkg, SURFACES[0], "0.3.0")["SKILL.md"].decode())
    assert "x-workbench-catalog-version" not in meta


def test_provenance_reaches_the_harness_as_a_yaml_boolean(tmp_catalog):
    """inject writes raw lines, so an unquoted `true` is already a YAML boolean."""
    yaml = pytest.importorskip("yaml")
    skills_dir = tmp_catalog()
    pkg = load_package(skills_dir / "example-skill")

    text = render(pkg, SURFACES[0], "0.3.0")["SKILL.md"].decode("utf-8")

    assert "x-workbench-managed: true\n" in text
    meta = yaml.safe_load(text.split("---\n")[1])
    assert meta["x-workbench-managed"] is True
    assert meta["x-workbench-source"] == "example-skill"


def test_non_ascii_front_matter_survives_projection(tmp_catalog):
    skills_dir = tmp_catalog()
    (skills_dir / "example-skill" / "SKILL.md").write_text(
        "---\nname: example-skill\ndescription: Prüfen Sie den Zustand\n---\n\n# ok\n",
        encoding="utf-8",
    )
    pkg = load_package(skills_dir / "example-skill")

    out = render(pkg, SURFACES[0], "0.3.0")["SKILL.md"].decode("utf-8")

    assert "Prüfen Sie den Zustand" in out
