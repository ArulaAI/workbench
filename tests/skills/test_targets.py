import pytest

from skills.targets import (
    SURFACES,
    detect_surfaces,
    dest_dir,
    get_surface,
    surface_for_harness,
)


def test_claude_detected_when_dot_claude_present(tmp_project):
    ids = [s.id for s in detect_surfaces(tmp_project)]
    assert ids == ["claude_code"]


def test_no_surface_when_absent(tmp_path):
    assert detect_surfaces(tmp_path) == []


def test_detects_all_existing_harness_markers(tmp_path):
    for marker in (".claude", ".agents", ".github/skills"):
        (tmp_path / marker).mkdir(parents=True)

    assert [surface.harness for surface in detect_surfaces(tmp_path)] == [
        "claude",
        "codex",
        "copilot",
    ]


def test_plain_github_directory_does_not_imply_copilot(tmp_path):
    (tmp_path / ".github").mkdir()

    assert detect_surfaces(tmp_path) == []


def test_dest_dir_layout(tmp_project):
    s = SURFACES[0]
    d = dest_dir(s, "example-skill", tmp_project)
    assert d == tmp_project / ".claude" / "skills" / "example-skill"


@pytest.mark.parametrize(
    ("harness", "surface_id", "skills_root"),
    [
        ("claude", "claude_code", ".claude/skills"),
        ("codex", "codex", ".agents/skills"),
        ("copilot", "copilot", ".github/skills"),
    ],
)
def test_resolves_harness(harness, surface_id, skills_root):
    surface = surface_for_harness(harness.upper())
    assert surface.id == surface_id
    assert surface.skills_root == skills_root
    assert get_surface(surface_id) == surface


def test_rejects_unknown_harness():
    with pytest.raises(ValueError, match="expected: claude, codex, copilot"):
        surface_for_harness("cursor")
