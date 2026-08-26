from skills.catalog import load_package
from skills.targets import SURFACES
from skills.project import render
from skills.frontmatter import parse


def test_render_injects_provenance_and_keeps_refs(tmp_catalog):
    skills_dir = tmp_catalog()
    pkg = load_package(skills_dir / "workbench-draft")
    out = render(pkg, SURFACES[0], "0.3.0")
    assert "references/notes.md" in out
    assert out["references/notes.md"] == b"ref body\n"
    meta, body = parse(out["SKILL.md"].decode())
    assert meta["name"] == "workbench-draft"
    assert meta["x-speed-managed"] == "true"
    assert meta["x-speed-source"] == "workbench-draft"
    assert meta["x-speed-catalog-version"] == "0.3.0"
    assert "Do the thing." in body


def test_render_is_deterministic(tmp_catalog):
    skills_dir = tmp_catalog()
    pkg = load_package(skills_dir / "workbench-draft")
    assert render(pkg, SURFACES[0], "0.3.0") == render(pkg, SURFACES[0], "0.3.0")
