import pytest

from skills.models import HARNESSES
from skills.targets import detect_harnesses, dest_dir, get_harness


def test_claude_detected_when_dot_claude_present(tmp_project):
    ids = [s.id for s in detect_harnesses(tmp_project)]
    assert ids == ["claude"]


def test_no_harness_when_absent(tmp_path):
    assert detect_harnesses(tmp_path) == []


def test_detects_all_existing_harness_markers(tmp_path):
    for marker in (".claude", ".agents", ".github/skills"):
        (tmp_path / marker).mkdir(parents=True)

    assert [harness.id for harness in detect_harnesses(tmp_path)] == [
        "claude",
        "codex",
        "copilot",
    ]


def test_plain_github_directory_does_not_imply_copilot(tmp_path):
    (tmp_path / ".github").mkdir()

    assert detect_harnesses(tmp_path) == []


def test_dest_dir_layout(tmp_project):
    s = HARNESSES[0]
    d = dest_dir(s, "example-skill", tmp_project)
    assert d == tmp_project / ".claude" / "skills" / "example-skill"


@pytest.mark.parametrize(
    ("typed", "harness_id", "skills_root"),
    [
        ("claude", "claude", ".claude/skills"),
        ("codex", "codex", ".agents/skills"),
        ("copilot", "copilot", ".github/skills"),
    ],
)
def test_resolves_harness(typed, harness_id, skills_root):
    harness = get_harness(typed.upper())
    assert harness.id == harness_id
    assert harness.skills_root == skills_root
    assert get_harness(harness_id) == harness


def test_rejects_unknown_harness():
    with pytest.raises(ValueError, match="expected: claude, codex, copilot"):
        get_harness("cursor")


@pytest.mark.parametrize(
    "name", ["../escape", "a/b", "/abs", "..", "Upper", ".hidden", ""]
)
def test_dest_dir_refuses_names_that_are_not_legal_skill_names(tmp_path, name):
    with pytest.raises(ValueError, match="unsafe skill name"):
        dest_dir(HARNESSES[0], name, tmp_path)


def test_dest_dir_resolves_a_legal_name_under_the_harness_root(tmp_path):
    assert dest_dir(HARNESSES[0], "workbench-health", tmp_path) == (
        tmp_path / ".claude" / "skills" / "workbench-health"
    )


# ── Bounded writes: a marker must be a real directory inside the project ───


def test_symlinked_marker_is_not_a_detected_harness(tmp_path):
    """A symlinked .claude would let sync write wherever the link points."""
    project = tmp_path / "proj"
    project.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (project / ".claude").symlink_to(outside, target_is_directory=True)

    assert detect_harnesses(project) == []


def test_marker_reached_through_a_symlinked_parent_is_not_detected(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    outside = tmp_path / "outside"
    (outside / "skills").mkdir(parents=True)
    (project / ".github").symlink_to(outside, target_is_directory=True)

    assert detect_harnesses(project) == []


def test_marker_symlinked_within_the_project_is_still_refused(tmp_path):
    """Even an inward link is refused: the rule stays simple and checkable."""
    project = tmp_path / "proj"
    (project / "real").mkdir(parents=True)
    (project / ".claude").symlink_to(project / "real", target_is_directory=True)

    assert detect_harnesses(project) == []


def test_dest_dir_refuses_a_projection_root_that_leaves_the_project(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (project / ".claude").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="outside the project"):
        dest_dir(HARNESSES[0], "example-skill", project)


def test_dest_dir_refuses_a_symlinked_skills_root(tmp_path):
    project = tmp_path / "proj"
    (project / ".claude").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (project / ".claude" / "skills").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="outside the project"):
        dest_dir(HARNESSES[0], "example-skill", project)


def test_dest_dir_accepts_a_project_reached_through_a_symlinked_parent(tmp_path):
    """A project checked out under a symlinked path is ordinary, not an escape."""
    real = tmp_path / "real-project"
    (real / ".claude").mkdir(parents=True)
    link = tmp_path / "via-link"
    link.symlink_to(real, target_is_directory=True)

    assert dest_dir(HARNESSES[0], "example-skill", link) == (
        link / ".claude" / "skills" / "example-skill"
    )
