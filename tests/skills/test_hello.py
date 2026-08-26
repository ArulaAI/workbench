import importlib.util
from pathlib import Path

from skills import __main__ as cli
from skills.catalog import load_package
from skills.project import render
from skills.targets import SURFACES

REPO = Path(__file__).resolve().parents[2]
HELPER = REPO / "skills" / "workbench-hello" / "scripts" / "hello.py"


def _load_helper():
    spec = importlib.util.spec_from_file_location("hello_helper", HELPER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_helper_builds_greeting_invariant():
    h = _load_helper()
    r = h.build_result("Mohit", "0.1.0", "workbench-cli")
    assert r["skill"] == "workbench-hello"
    assert r["message"] == "Hello, Mohit! Workbench skills are available."
    assert r["catalog_version"] == "0.1.0"
    assert r["surface"] == "workbench-cli"


def test_helper_defaults_name_to_world():
    h = _load_helper()
    assert h.build_result("", "v", "s")["message"].startswith("Hello, World!")


def test_engine_hello_reuses_canonical_helper(capsys):
    rc = cli.main(
        ["hello", "Mohit", "--skills-dir", str(REPO / "skills"),
         "--catalog-version", "test", "--surface", "workbench-cli"]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "Hello, Mohit! Workbench skills are available." in out
    assert "surface: workbench-cli" in out
    assert "catalog_version: test" in out


def test_projection_helper_is_byte_identical_to_canonical():
    pkg = load_package(REPO / "skills" / "workbench-hello")
    out = render(pkg, SURFACES[0], "test")
    assert out["scripts/hello.py"] == HELPER.read_bytes()  # shared implementation
