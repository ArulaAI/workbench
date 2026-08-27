import pytest


@pytest.fixture
def tmp_catalog(tmp_path):
    """Factory that writes a valid canonical skill package under tmp_path/skills."""

    def _make(name="example-skill", extra=None):
        pkg = tmp_path / "skills" / name
        (pkg / "references").mkdir(parents=True)
        (pkg / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: A test skill\n---\n\n# {name}\nDo the thing.\n"
        )
        (pkg / "references" / "notes.md").write_text("ref body\n")
        for rel, content in (extra or {}).items():
            p = pkg / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
        return tmp_path / "skills"

    return _make


@pytest.fixture
def tmp_project(tmp_path):
    """A project dir with .claude/ present so claude_code is detected."""
    proj = tmp_path / "proj"
    (proj / ".claude").mkdir(parents=True)
    return proj
