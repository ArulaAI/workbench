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


def test_helper_rejects_empty_manifest(tmp_project):
    """`{}` records no skills, so it cannot prove anything is installed."""
    manifest = tmp_project / ".speed" / "skills" / "manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text("{}\n")

    result = _load_helper().build_result(tmp_project, "claude_code")

    assert result["status"] == "unhealthy"
    assert result["skills"] == []
    assert any("no Workbench skills are imported" in i for i in result["issues"])


def _load_projected_helper(path):
    spec = importlib.util.spec_from_file_location("projected_health", path)
    mod = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = previous
    return mod


def test_helper_ignores_generated_junk(tmp_project):
    """Finder or Python touching the projection is not a broken install."""
    _sync_project(tmp_project)
    projected = tmp_project / ".claude" / "skills" / "workbench-health"
    (projected / ".DS_Store").write_bytes(b"\x00")
    (projected / "scripts" / "__pycache__").mkdir(parents=True, exist_ok=True)
    (projected / "scripts" / "__pycache__" / "health.pyc").write_bytes(b"\x00")

    result = _load_helper().build_result(tmp_project, "claude_code")

    assert result["status"] == "healthy", result["issues"]


def test_projected_helper_infers_its_own_surface(tmp_path):
    """A codex projection must not check itself against the claude surface."""
    project = tmp_path / "codex-only"
    (project / ".agents").mkdir(parents=True)
    sync(project, REPO / "skills", "test", only_surface="codex")
    helper = project / ".agents" / "skills" / "workbench-health" / "scripts" / "health.py"

    result = _load_projected_helper(helper).build_result(project)

    assert result["surface"] == "codex"
    assert result["status"] == "healthy", result["issues"]
