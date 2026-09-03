import os
import subprocess
import sys
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[2] / "lib"


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


@pytest.fixture
def ascii_locale_python():
    """Run a snippet in a child interpreter whose default text encoding is ASCII.

    Reproduces the machine where an implicit ``read_text()`` picks up the
    platform encoding instead of UTF-8 and blows up on a description with an
    accent in it. Returns the CompletedProcess so a test can assert on both the
    exit status and stderr.
    """

    def _run(code):
        env = dict(
            os.environ,
            LC_ALL="C",
            LANG="C",
            PYTHONCOERCECLOCALE="0",
            PYTHONUTF8="0",
            PYTHONPATH=str(LIB),
        )
        return subprocess.run(
            [sys.executable, "-c", code],
            env=env,
            capture_output=True,
            text=True,
        )

    return _run
