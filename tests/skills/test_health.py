import importlib.util
import sys
from pathlib import Path

from skills.catalog import load_package
from skills.project import render
from skills.sync import sync
from skills.targets import SURFACES

REPO = Path(__file__).resolve().parents[2]
HELPER = REPO / "skills" / "workbench-health" / "scripts" / "health.py"


def _load_helper():
    spec = importlib.util.spec_from_file_location("health_helper", HELPER)
    mod = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = previous
    return mod


def _sync_project(project):
    rows = sync(project, REPO / "skills", "test")
    assert rows


def test_helper_reports_imported_skills_ready(tmp_project):
    _sync_project(tmp_project)
    result = _load_helper().build_result(tmp_project, "claude_code")

    assert result["skill"] == "workbench-health"
    assert result["status"] == "healthy"
    assert result["message"] == (
        "Workbench skills were imported successfully and are ready to use."
    )
    assert result["catalog_version"] == "test"
    assert result["surface"] == "claude_code"
    assert result["skills"] == ["workbench-health"]
    assert result["issues"] == []


def test_helper_accepts_claude_harness_alias(tmp_project):
    _sync_project(tmp_project)

    result = _load_helper().build_result(tmp_project, "claude")

    assert result["status"] == "healthy"
    assert result["surface"] == "claude_code"


def test_helper_reports_missing_manifest(tmp_project):
    result = _load_helper().build_result(tmp_project, "claude_code")

    assert result["status"] == "unhealthy"
    assert result["skills"] == []
    assert "skill manifest is missing" in result["issues"][0]


def test_helper_reports_modified_projection(tmp_project):
    _sync_project(tmp_project)
    projected = (
        tmp_project
        / ".claude"
        / "skills"
        / "workbench-health"
        / "SKILL.md"
    )
    projected.write_text(projected.read_text() + "\nuser edit\n")

    result = _load_helper().build_result(tmp_project, "claude_code")

    assert result["status"] == "unhealthy"
    assert "workbench-health: modified SKILL.md" in result["issues"]


def test_helper_reports_missing_projection_file(tmp_project):
    _sync_project(tmp_project)
    projected = (
        tmp_project
        / ".claude"
        / "skills"
        / "workbench-health"
        / "scripts"
        / "health.py"
    )
    projected.unlink()

    result = _load_helper().build_result(tmp_project, "claude_code")

    assert result["status"] == "unhealthy"
    assert "workbench-health: missing scripts/health.py" in result["issues"]


def test_helper_reports_unexpected_projection_file(tmp_project):
    _sync_project(tmp_project)
    unexpected = (
        tmp_project
        / ".claude"
        / "skills"
        / "workbench-health"
        / "unexpected.txt"
    )
    unexpected.write_text("not managed\n")

    result = _load_helper().build_result(tmp_project, "claude_code")

    assert result["status"] == "unhealthy"
    assert "workbench-health: unexpected unexpected.txt" in result["issues"]


def test_projection_helper_is_byte_identical_to_canonical():
    package = load_package(REPO / "skills" / "workbench-health")
    output = render(package, SURFACES[0], "test")
    assert output["scripts/health.py"] == HELPER.read_bytes()
