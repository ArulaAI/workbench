import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from skills import PATHS
from skills.catalog import load_package
from skills.models import HARNESSES, SkillState
from skills.project import render
from skills.sync import sync

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
    result = _load_helper().build_result(tmp_project, "claude")

    assert result["skill"] == "workbench-health"
    assert result["status"] == "healthy"
    assert result["message"] == (
        "Workbench skills were imported successfully and are ready to use."
    )
    assert result["catalog_version"] == "test"
    assert result["harness"] == "claude"
    assert result["skills"] == ["workbench-draft", "workbench-health"]
    assert result["issues"] == []


def test_helper_accepts_claude_harness_alias(tmp_project):
    _sync_project(tmp_project)

    result = _load_helper().build_result(tmp_project, "claude")

    assert result["status"] == "healthy"
    assert result["harness"] == "claude"


def test_helper_reports_missing_manifest(tmp_project):
    result = _load_helper().build_result(tmp_project, "claude")

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

    result = _load_helper().build_result(tmp_project, "claude")

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

    result = _load_helper().build_result(tmp_project, "claude")

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

    result = _load_helper().build_result(tmp_project, "claude")

    assert result["status"] == "unhealthy"
    assert "workbench-health: unexpected unexpected.txt" in result["issues"]


def test_projection_helper_is_byte_identical_to_canonical():
    package = load_package(REPO / "skills" / "workbench-health")
    output = render(package, HARNESSES[0], "test")
    assert output["scripts/health.py"] == HELPER.read_bytes()


def test_helper_rejects_empty_manifest(tmp_project):
    """`{}` records no skills, so it cannot prove anything is installed."""
    manifest = tmp_project / PATHS.manifest
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text("{}\n")

    result = _load_helper().build_result(tmp_project, "claude")

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

    result = _load_helper().build_result(tmp_project, "claude")

    assert result["status"] == "healthy", result["issues"]


def test_projected_helper_infers_its_own_harness(tmp_path):
    """A codex projection must not check itself against the claude harness."""
    project = tmp_path / "codex-only"
    (project / ".agents").mkdir(parents=True)
    sync(project, REPO / "skills", "test", only_harness="codex")
    helper = project / ".agents" / "skills" / "workbench-health" / "scripts" / "health.py"

    result = _load_projected_helper(helper).build_result(project)

    assert result["harness"] == "codex"
    assert result["status"] == "healthy", result["issues"]


# --- Review fixes: manifest validation, path containment, doc truth ---------


def _write_manifest(project, data):
    path = project / ".speed" / "skills" / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")
    return path


@pytest.mark.parametrize(
    ("manifest", "expected"),
    [
        ({"harnesses": []}, "skill manifest harnesses must be an object"),
        (
            {"harnesses": {"claude": []}},
            "manifest entry for harness 'claude' must be an object",
        ),
        (
            {"harnesses": {"claude": {"skills": ""}}},
            "manifest skills for harness 'claude' must be an object",
        ),
        (
            {"harnesses": {"claude": {"skills": {"workbench-health": []}}}},
            "workbench-health: manifest entry must be an object",
        ),
        (
            {
                "harnesses": {
                    "claude": {"skills": {"workbench-health": {"files": 0}}}
                }
            },
            "workbench-health: manifest files must be an object",
        ),
    ],
)
def test_helper_reports_falsey_non_object_manifest_nodes(
    tmp_project, manifest, expected
):
    """A falsey wrong-type node must be reported, not crash the type check."""
    _write_manifest(tmp_project, manifest)

    result = _load_helper().build_result(tmp_project, "claude")

    assert result["status"] == "unhealthy"
    assert any(expected in issue for issue in result["issues"]), result["issues"]


def test_helper_rejects_unknown_harness(tmp_project):
    """An unsupported harness has no canonical root, so nothing may be resolved."""
    _sync_project(tmp_project)

    result = _load_helper().build_result(tmp_project, "weird")

    assert result["status"] == "unhealthy"
    assert any("not a supported agent harness" in i for i in result["issues"])
    assert any("workbench init --harness" in f for f in result["remediation"])


def test_helper_ignores_manifest_supplied_root(tmp_project):
    """Only the canonical root is resolved; a manifest root could point anywhere."""
    _sync_project(tmp_project)
    path = tmp_project / ".speed" / "skills" / "manifest.json"
    data = json.loads(path.read_text())
    data["harnesses"]["claude"]["root"] = "../../etc"
    path.write_text(json.dumps(data, indent=2))

    result = _load_helper().build_result(tmp_project, "claude")

    assert result["status"] == "healthy", result["issues"]


def test_helper_rejects_unsafe_skill_name(tmp_project):
    """A manifest key that is not a legal skill name cannot name a projection."""
    _write_manifest(
        tmp_project,
        {
            "harnesses": {
                "claude": {
                    "skills": {"../../x": {"files": {"a.md": "sha256:0"}}}
                }
            }
        },
    )

    result = _load_helper().build_result(tmp_project, "claude")

    assert result["status"] == "unhealthy"
    assert any("unsafe skill name" in i for i in result["issues"]), result["issues"]


def test_helper_rejects_symlinked_projection_file(tmp_project):
    """A link out of the projection hashes its target, so the read must be refused."""
    _sync_project(tmp_project)
    projected = (
        tmp_project / ".claude" / "skills" / "workbench-health" / "SKILL.md"
    )
    outside = tmp_project.parent / "outside-SKILL.md"
    outside.write_bytes(projected.read_bytes())
    projected.unlink()
    projected.symlink_to(outside)

    result = _load_helper().build_result(tmp_project, "claude")

    assert result["status"] == "unhealthy", result
    assert any(
        "symlink" in issue and "SKILL.md" in issue for issue in result["issues"]
    ), result["issues"]


def test_helper_rejects_symlinked_projection_directory(tmp_project):
    """The whole projection directory can be relinked just as easily."""
    _sync_project(tmp_project)
    projected = tmp_project / ".claude" / "skills" / "workbench-health"
    moved = tmp_project.parent / "outside-projection"
    projected.rename(moved)
    projected.symlink_to(moved, target_is_directory=True)

    result = _load_helper().build_result(tmp_project, "claude")

    assert result["status"] == "unhealthy", result
    assert any(
        "projection directory is a symlink" in issue for issue in result["issues"]
    ), result["issues"]


def test_healthy_result_carries_no_remediation(tmp_project):
    _sync_project(tmp_project)

    result = _load_helper().build_result(tmp_project, "claude")

    assert result["remediation"] == []


def test_remediation_is_issue_specific(tmp_project):
    """One command cannot repair every state; each issue names its own fix."""
    helper = _load_helper()
    missing = helper.build_result(tmp_project, "claude")
    assert missing["remediation"] == ["Run `workbench skills sync`."]

    _sync_project(tmp_project)
    projected = (
        tmp_project / ".claude" / "skills" / "workbench-health" / "SKILL.md"
    )
    projected.write_text(projected.read_text() + "\nuser edit\n")
    modified = helper.build_result(tmp_project, "claude")
    assert modified["remediation"] == [
        "Review or back up local edits, then run `workbench skills sync --harness claude --force`."
    ]


def test_unreadable_manifest_does_not_recommend_sync(tmp_project):
    """Sync reads the same broken file, so it cannot be the advertised repair."""
    _write_manifest(tmp_project, {})
    (tmp_project / ".speed" / "skills" / "manifest.json").write_text("{not json")

    result = _load_helper().build_result(tmp_project, "claude")

    assert result["status"] == "unhealthy"
    assert result["remediation"] == [
        "Restore `.speed/skills/manifest.json` from version control, then run "
        "`workbench skills sync`."
    ]


SKILL_MD = REPO / "skills" / "workbench-health" / "SKILL.md"


def _documented_invocation():
    """The helper command line from the first shell block in SKILL.md."""
    block = re.search(r"```(?:bash|sh|console)\n(.*?)```", SKILL_MD.read_text(), re.S)
    assert block, "SKILL.md documents no shell block"
    for line in block.group(1).splitlines():
        if "scripts/health.py" in line:
            return line.strip()
    raise AssertionError("SKILL.md shell block does not invoke the helper")


@pytest.mark.skipif(
    shutil.which("python3") is None, reason="documented command needs python3"
)
def test_documented_invocation_runs_as_written(tmp_project):
    """Step 1 must be executable without the agent inventing path resolution."""
    _sync_project(tmp_project)
    command = _documented_invocation()

    assert command.startswith("python3 "), command
    assert "<" not in command, f"unresolved placeholder: {command}"
    assert "--json" in command, command

    completed = subprocess.run(
        command, shell=True, cwd=tmp_project, capture_output=True, text=True
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert json.loads(completed.stdout)["status"] == "healthy"


def test_documented_result_block_matches_real_output(tmp_project):
    """The example result is the helper's actual shape, keys and repair text."""
    _sync_project(tmp_project)
    projected = (
        tmp_project / ".claude" / "skills" / "workbench-health" / "SKILL.md"
    )
    projected.write_text(projected.read_text() + "\nuser edit\n")
    result = _load_helper().build_result(tmp_project, "claude")

    block = re.search(r"```json\n(.*?)```", SKILL_MD.read_text(), re.S)
    assert block, "SKILL.md documents no result block"
    documented = json.loads(block.group(1))

    assert set(documented) == set(result)
    assert documented["status"] == result["status"]
    assert documented["message"] == result["message"]
    assert documented["issues"] == result["issues"]
    assert documented["remediation"] == result["remediation"]


def test_helper_names_an_in_project_symlink_as_a_symlink(tmp_project):
    """A link that stays inside the repo is still a link, and says so."""
    _sync_project(tmp_project)
    projected = (
        tmp_project / ".claude" / "skills" / "workbench-health" / "SKILL.md"
    )
    twin = tmp_project / "twin.md"
    twin.write_bytes(projected.read_bytes())
    projected.unlink()
    projected.symlink_to(twin)

    result = _load_helper().build_result(tmp_project, "claude")

    assert result["status"] == "unhealthy"
    assert "workbench-health: symlink at SKILL.md" in result["issues"]
    assert not any("escapes" in issue for issue in result["issues"])


def test_the_helper_agrees_with_the_canonical_layout():
    """The projected helper carries its own literals and must not drift.

    It runs as a copy inside a harness skills directory with no package around
    it, so it cannot import the layout. Asserting the values match here is what
    keeps the embedded copy honest.
    """
    helper = _load_helper()
    assert helper.SKILLS_ROOTS == {
        harness.id: harness.skills_root for harness in HARNESSES
    }

    source = HELPER.read_text(encoding="utf-8")
    for part in PATHS.manifest.parts:
        assert f'"{part}"' in source, f"helper no longer names {part}"
    assert PATHS.manifest.as_posix() in source, "the repair text names a stale path"


def test_the_helper_copy_of_the_name_whitelist_rejects_a_trailing_newline():
    """The helper carries its own regex because it runs standalone.

    Two definitions of the same rule drift, and this one had the same `$`
    instead of `\\Z`, so both needed the fix and both need the test.
    """
    helper = _load_helper()
    assert helper._is_valid_skill_name("workbench-health")
    assert not helper._is_valid_skill_name("workbench-health\n")
    assert not helper._is_valid_skill_name("foo\r")
