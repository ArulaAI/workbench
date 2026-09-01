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
