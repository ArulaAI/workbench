"""Initialization policy, persistence, and verification contracts."""
import io
import json
from contextlib import redirect_stdout
from pathlib import Path

from skills.bootstrap import (
    configured_harnesses,
    persist_policy,
    plan_initialization,
    verify_installation,
)
from skills.manifest import save_manifest
from skills.sync import sync
from lib.toml import emit


REPO = Path(__file__).resolve().parents[2]
CATALOG = REPO / "skills"
TEMPLATE = REPO / "templates" / "speed-toml.toml"


def test_shell_config_loader_does_not_duplicate_the_skill_policy_parser():
    output = io.StringIO()
    with redirect_stdout(output):
        emit({"skills": {"harnesses": ["claude", "codex"]}})

    assert "TOML_SKILLS_HARNESSES" not in output.getvalue()


def test_provider_and_skill_harness_are_independent(tmp_path):
    config = tmp_path / "speed.toml"
    config.write_text(
        '[agent]\nprovider = "claude-code"\n\n[skills]\nharnesses = ["codex"]\n'
    )

    plan = plan_initialization(tmp_path, CATALOG, config_path=config)

    assert plan.harnesses == ("codex",)
    assert plan.source == "project configuration"
    assert plan.persist_required is False


def test_policy_precedence_is_cli_then_environment_then_config(tmp_path):
    config = tmp_path / "speed.toml"
    config.write_text('[skills]\nharnesses = ["claude"]\n')

    explicit = plan_initialization(
        tmp_path,
        CATALOG,
        explicit=("copilot",),
        environment=("codex",),
        config_path=config,
    )
    environment = plan_initialization(
        tmp_path,
        CATALOG,
        environment=("codex",),
        config_path=config,
    )
    configured = plan_initialization(tmp_path, CATALOG, config_path=config)

    assert (explicit.harnesses, explicit.source) == (("copilot",), "command line")
    assert (environment.harnesses, environment.source) == (("codex",), "environment")
    assert (configured.harnesses, configured.source) == (
        ("claude",),
        "project configuration",
    )


def test_legacy_manifest_policy_is_migrated_to_project_config(tmp_path):
    save_manifest(
        tmp_path,
        {
            "catalog_version": "old",
            "harnesses": {},
            "selected_harnesses": ["codex"],
        },
    )
    config = tmp_path / "speed.toml"

    plan = plan_initialization(tmp_path, CATALOG, config_path=config)
    persist_policy(
        config,
        plan.harnesses,
        template_path=TEMPLATE,
        project_root=tmp_path,
    )

    assert plan.source == "legacy manifest"
    assert plan.persist_required is True
    assert configured_harnesses(config) == ("codex",)
    manifest = json.loads((tmp_path / ".speed/skills/manifest.json").read_text())
    assert "selected_harnesses" not in manifest


def test_marker_detection_becomes_durable_policy(tmp_path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".agents").mkdir()
    config = tmp_path / "speed.toml"

    plan = plan_initialization(tmp_path, CATALOG, config_path=config)
    persist_policy(config, plan.harnesses, template_path=TEMPLATE)

    assert plan.source == "auto-detection"
    assert configured_harnesses(config) == ("claude", "codex")


def test_persist_policy_preserves_other_configuration(tmp_path):
    config = tmp_path / "speed.toml"
    config.write_text('[agent]\nprovider = "claude-code"\n')

    persist_policy(config, ("copilot",))

    text = config.read_text()
    assert 'provider = "claude-code"' in text
    assert configured_harnesses(config) == ("copilot",)


def test_verification_requires_every_selected_projection_to_be_current(tmp_path):
    sync(tmp_path, CATALOG, "test", only_harness=("claude", "codex"))

    healthy = verify_installation(
        tmp_path, CATALOG, "test", ("claude", "codex")
    )
    assert healthy["status"] == "healthy"

    projected = tmp_path / ".agents/skills/workbench-health/SKILL.md"
    projected.write_text(projected.read_text() + "\nlocal edit\n")
    unhealthy = verify_installation(
        tmp_path, CATALOG, "test", ("claude", "codex")
    )
    assert unhealthy["status"] == "unhealthy"


def test_the_policy_line_lands_below_the_section_explanation(tmp_path):
    """The live setting must not be written above the comments describing it.

    Inserting at ``[skills]`` + 1 put ``harnesses = [...]`` ahead of the
    template's own explanation, so the commented example appeared underneath
    the active value. Read top down, that invites someone to edit the comment
    and see nothing happen.
    """
    config = tmp_path / "speed.toml"
    persist_policy(config, ("claude",), template_path=TEMPLATE)

    lines = config.read_text(encoding="utf-8").splitlines()
    header = lines.index("[skills]")
    active = next(i for i, line in enumerate(lines) if line.startswith("harnesses ="))
    example = next(i for i, line in enumerate(lines) if line.startswith("# harnesses ="))

    assert example < active, "the live setting belongs after the commented example"
    assert lines[header + 1].lstrip().startswith("#"), "explanation stays under the header"
    next_section = next(
        i for i, line in enumerate(lines) if i > header and line.startswith("[")
    )
    assert active < next_section, "the policy must stay inside [skills]"
