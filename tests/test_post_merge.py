#!/usr/bin/env python3
"""Tests for post-merge correction extraction.

Tests the post-merge path in human_corrections.py: diffing task branch
tips against merged HEAD, classifying changes deterministically, and
creating observations. Uses temporary git repos for realistic testing.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "lib"))

from lib.learn.human_corrections import (
    DiffHunk,
    _attribute_agent,
    _is_noise_file,
    extract_post_merge,
    find_speed_branches,
    parse_diff_hunks,
)

passed = 0
failed = 0


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name} — {detail}")


# ── Git helpers ──────────────────────────────────────────────────────


def _run(cwd, *args):
    """Run a command in a directory, return stdout."""
    result = subprocess.run(
        list(args), capture_output=True, text=True, cwd=str(cwd),
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed: {args}\nstderr: {result.stderr}"
        )
    return result.stdout.strip()


def _git(cwd, *args):
    return _run(cwd, "git", *args)


def _init_repo(tmp):
    """Create a git repo with an initial commit."""
    repo = Path(tmp) / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@test.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("# Test\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial")
    return repo


def _make_feature_dir(tmp, tasks):
    """Create a .speed feature directory with task JSONs."""
    feature_dir = Path(tmp) / "feature"
    tasks_dir = feature_dir / "tasks"
    tasks_dir.mkdir(parents=True)
    (feature_dir / "logs").mkdir()
    for task in tasks:
        tid = task["id"]
        (tasks_dir / f"{tid}.json").write_text(json.dumps(task))
    return feature_dir


# ── Unit tests: parse_diff_hunks ─────────────────────────────────────


def test_parse_diff_hunks_transformative():
    """Hunk with both added and removed lines = transformative."""
    diff = (
        "diff --git a/src/main.py b/src/main.py\n"
        "--- a/src/main.py\n"
        "+++ b/src/main.py\n"
        "@@ -1,3 +1,3 @@\n"
        " import os\n"
        "-def old_func():\n"
        "+def new_func():\n"
        "     pass\n"
    )
    hunks = parse_diff_hunks(diff)
    check("parse: single hunk", len(hunks) == 1, f"got {len(hunks)}")
    if hunks:
        check("parse: file", hunks[0].file == "src/main.py")
        check("parse: change_type", hunks[0].change_type == "transformative")
        check("parse: summary", hunks[0].hunk_summary == "+1/-1 lines")


def test_parse_diff_hunks_additive():
    """Hunk with only added lines = additive."""
    diff = (
        "diff --git a/src/main.py b/src/main.py\n"
        "--- a/src/main.py\n"
        "+++ b/src/main.py\n"
        "@@ -1,2 +1,4 @@\n"
        " import os\n"
        "+import sys\n"
        "+import json\n"
        "     pass\n"
    )
    hunks = parse_diff_hunks(diff)
    check("parse: additive", len(hunks) == 1 and hunks[0].change_type == "additive")


def test_parse_diff_hunks_subtractive():
    """Hunk with only removed lines = subtractive."""
    diff = (
        "diff --git a/src/main.py b/src/main.py\n"
        "--- a/src/main.py\n"
        "+++ b/src/main.py\n"
        "@@ -1,3 +1,1 @@\n"
        " import os\n"
        "-import sys\n"
        "-import json\n"
    )
    hunks = parse_diff_hunks(diff)
    check("parse: subtractive", len(hunks) == 1 and hunks[0].change_type == "subtractive")


def test_parse_diff_hunks_cosmetic():
    """Hunk where added/removed differ only by whitespace = cosmetic."""
    diff = (
        "diff --git a/src/main.py b/src/main.py\n"
        "--- a/src/main.py\n"
        "+++ b/src/main.py\n"
        "@@ -1,2 +1,2 @@\n"
        "-def func():  \n"
        "+def func():\n"
    )
    hunks = parse_diff_hunks(diff)
    check("parse: cosmetic", len(hunks) == 1 and hunks[0].change_type == "cosmetic")


def test_parse_diff_hunks_multiple():
    """Multiple hunks across two files."""
    diff = (
        "diff --git a/a.py b/a.py\n"
        "@@ -1,2 +1,2 @@\n"
        "-old\n"
        "+new\n"
        "diff --git a/b.py b/b.py\n"
        "@@ -1,2 +1,3 @@\n"
        " keep\n"
        "+added\n"
    )
    hunks = parse_diff_hunks(diff)
    check("parse: multi-file count", len(hunks) == 2, f"got {len(hunks)}")
    if len(hunks) == 2:
        check("parse: first file", hunks[0].file == "a.py")
        check("parse: second file", hunks[1].file == "b.py")


# ── Unit tests: _attribute_agent ─────────────────────────────────────


def test_attribute_agent_developer():
    """Non-agents/ file attributes to developer."""
    agents = _attribute_agent("src/main.py", "transformative")
    check("attr: developer", agents == ["developer"])


def test_attribute_agent_architect():
    """agents/ file attributes to architect."""
    agents = _attribute_agent("agents/planner.md", "additive")
    check("attr: architect", agents == ["architect"])


def test_attribute_agent_subtractive_guardian():
    """Subtractive change adds guardian."""
    agents = _attribute_agent("src/main.py", "subtractive")
    check("attr: guardian on subtractive", agents == ["developer", "guardian"])


# ── Unit tests: _is_noise_file ───────────────────────────────────────


def test_noise_files():
    """Lock files and changelogs are noise."""
    check("noise: package-lock", _is_noise_file("package-lock.json") is True)
    check("noise: CHANGELOG.md", _is_noise_file("CHANGELOG.md") is True)
    check("noise: Cargo.lock", _is_noise_file("Cargo.lock") is True)
    check("noise: normal file", _is_noise_file("src/main.py") is False)
    check("noise: nested lock", _is_noise_file("sub/package-lock.json") is True)


# ── Integration tests: extract_post_merge ────────────────────────────


def test_zero_delta():
    """All task branches match HEAD produces human_approved observation."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = _init_repo(tmp)

        # Create a file and commit on main
        (repo / "src").mkdir()
        (repo / "src" / "app.py").write_text("print('hello')\n")
        _git(repo, "add", "src/app.py")
        _git(repo, "commit", "-m", "add app")

        # Create task branch at same commit
        branch_name = "speed/test-feature/task-1"
        _git(repo, "branch", branch_name)

        # Feature dir with task pointing to that branch
        feature_dir = _make_feature_dir(tmp, [{
            "id": "1",
            "branch": branch_name,
            "files_to_modify": ["src/app.py"],
        }])

        obs, warnings = extract_post_merge("test-feature", feature_dir, repo)
        check("zero-delta: has observation", len(obs) == 1, f"got {len(obs)}")
        if obs:
            check("zero-delta: type", obs[0].observation_type == "human_approved")
            check("zero-delta: weight", obs[0].weight == 0.5)
            check("zero-delta: tasks_approved", obs[0].detail["tasks_approved"] == 1)


def test_single_correction():
    """One file changed after task branch = transformative override."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = _init_repo(tmp)

        (repo / "src").mkdir()
        (repo / "src" / "app.py").write_text("def old():\n    pass\n")
        _git(repo, "add", "src/app.py")
        _git(repo, "commit", "-m", "add app")

        # Task branch at this commit
        branch_name = "speed/test-feature/task-1"
        _git(repo, "branch", branch_name)

        # Human edits on HEAD (main)
        (repo / "src" / "app.py").write_text("def new_and_improved():\n    return True\n")
        _git(repo, "add", "src/app.py")
        _git(repo, "commit", "-m", "human fix")

        feature_dir = _make_feature_dir(tmp, [{
            "id": "1",
            "branch": branch_name,
            "files_to_modify": ["src/app.py"],
        }])

        obs, warnings = extract_post_merge("test-feature", feature_dir, repo)
        overrides = [o for o in obs if o.observation_type == "human_override"]
        check("single: has overrides", len(overrides) >= 1, f"got {len(overrides)}")
        if overrides:
            check("single: change_type", overrides[0].detail["change_type"] == "transformative")
            check("single: weight", overrides[0].weight == 2.5)
            check("single: file", overrides[0].detail["file"] == "src/app.py")
            check("single: agent", "developer" in overrides[0].detail["agent_attribution"])


def test_multi_task():
    """Two tasks with changes produce observations for each."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = _init_repo(tmp)

        (repo / "src").mkdir()
        (repo / "src" / "a.py").write_text("a = 1\n")
        (repo / "src" / "b.py").write_text("b = 1\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "add files")

        _git(repo, "branch", "speed/feat/task-1")
        _git(repo, "branch", "speed/feat/task-2")

        # Human edits both files
        (repo / "src" / "a.py").write_text("a = 2  # fixed\n")
        (repo / "src" / "b.py").write_text("b = 2  # fixed\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "human fixes")

        feature_dir = _make_feature_dir(tmp, [
            {"id": "1", "branch": "speed/feat/task-1", "files_to_modify": ["src/a.py"]},
            {"id": "2", "branch": "speed/feat/task-2", "files_to_modify": ["src/b.py"]},
        ])

        obs, warnings = extract_post_merge("feat", feature_dir, repo)
        overrides = [o for o in obs if o.observation_type == "human_override"]
        task_ids = {o.task_id for o in overrides}
        check("multi: both tasks", task_ids == {"1", "2"}, f"got {task_ids}")


def test_noise_changelog_filtered():
    """CHANGELOG.md changes are filtered out."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = _init_repo(tmp)

        (repo / "CHANGELOG.md").write_text("# v1.0\n")
        (repo / "src").mkdir()
        (repo / "src" / "app.py").write_text("x = 1\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "add files")

        _git(repo, "branch", "speed/feat/task-1")

        (repo / "CHANGELOG.md").write_text("# v1.1\n- fix\n")
        (repo / "src" / "app.py").write_text("x = 2\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "release")

        feature_dir = _make_feature_dir(tmp, [{
            "id": "1",
            "branch": "speed/feat/task-1",
            "files_to_modify": ["src/app.py", "CHANGELOG.md"],
        }])

        obs, warnings = extract_post_merge("feat", feature_dir, repo)
        overrides = [o for o in obs if o.observation_type == "human_override"]
        files = [o.detail["file"] for o in overrides]
        check("noise: CHANGELOG filtered", "CHANGELOG.md" not in files, f"got {files}")
        check("noise: app.py kept", "src/app.py" in files, f"got {files}")


def test_cosmetic_low_weight():
    """Whitespace-only changes get weight 0.1."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = _init_repo(tmp)

        (repo / "src").mkdir()
        (repo / "src" / "app.py").write_text("def func():  \n    pass  \n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "add")

        _git(repo, "branch", "speed/feat/task-1")

        # Only strip trailing whitespace
        (repo / "src" / "app.py").write_text("def func():\n    pass\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "trim whitespace")

        feature_dir = _make_feature_dir(tmp, [{
            "id": "1",
            "branch": "speed/feat/task-1",
            "files_to_modify": ["src/app.py"],
        }])

        obs, warnings = extract_post_merge("feat", feature_dir, repo)
        overrides = [o for o in obs if o.observation_type == "human_override"]
        check("cosmetic: has override", len(overrides) >= 1, f"got {len(overrides)}")
        if overrides:
            check("cosmetic: change_type", overrides[0].detail["change_type"] == "cosmetic")
            check("cosmetic: weight", overrides[0].weight == 0.1)


def test_squash_merge():
    """Post-merge works when HEAD is a squash commit ahead of branch tip."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = _init_repo(tmp)

        (repo / "src").mkdir()
        (repo / "src" / "app.py").write_text("v1\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "v1")

        _git(repo, "branch", "speed/feat/task-1")

        # Multiple commits squashed (simulated by just making a new commit)
        (repo / "src" / "app.py").write_text("v3 squashed\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "squash: v2 + v3")

        feature_dir = _make_feature_dir(tmp, [{
            "id": "1",
            "branch": "speed/feat/task-1",
            "files_to_modify": ["src/app.py"],
        }])

        obs, warnings = extract_post_merge("feat", feature_dir, repo)
        overrides = [o for o in obs if o.observation_type == "human_override"]
        check("squash: detected changes", len(overrides) >= 1, f"got {len(overrides)}")


def test_branch_deleted():
    """Deleted task branch is skipped gracefully."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = _init_repo(tmp)

        (repo / "src").mkdir()
        (repo / "src" / "a.py").write_text("a\n")
        (repo / "src" / "b.py").write_text("b\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "add")

        # Only create one branch, task-2 branch doesn't exist
        _git(repo, "branch", "speed/feat/task-1")

        (repo / "src" / "a.py").write_text("a2\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "fix a")

        feature_dir = _make_feature_dir(tmp, [
            {"id": "1", "branch": "speed/feat/task-1", "files_to_modify": ["src/a.py"]},
            {"id": "2", "branch": "speed/feat/task-2", "files_to_modify": ["src/b.py"]},
        ])

        obs, warnings = extract_post_merge("feat", feature_dir, repo)
        # Should still produce results for task-1
        overrides = [o for o in obs if o.observation_type == "human_override"]
        task_ids = {o.task_id for o in overrides}
        check("deleted: task-1 still processed", "1" in task_ids, f"got {task_ids}")
        check("deleted: task-2 skipped", "2" not in task_ids, f"got {task_ids}")


def test_all_branches_deleted():
    """All task branches deleted returns warning, no crash."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = _init_repo(tmp)

        feature_dir = _make_feature_dir(tmp, [
            {"id": "1", "branch": "speed/feat/task-1", "files_to_modify": ["a.py"]},
            {"id": "2", "branch": "speed/feat/task-2", "files_to_modify": ["b.py"]},
        ])

        obs, warnings = extract_post_merge("feat", feature_dir, repo)
        check("all-deleted: no observations", len(obs) == 0, f"got {len(obs)}")
        check("all-deleted: has warning", len(warnings) >= 1, f"got {len(warnings)}")
        if warnings:
            check("all-deleted: warning mentions branches",
                  "branch" in warnings[0].lower(), f"got: {warnings[0]}")


def test_idempotent():
    """Running extract_post_merge twice produces identical observation IDs."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = _init_repo(tmp)

        (repo / "src").mkdir()
        (repo / "src" / "app.py").write_text("old\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "add")

        _git(repo, "branch", "speed/feat/task-1")

        (repo / "src" / "app.py").write_text("new\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "fix")

        feature_dir = _make_feature_dir(tmp, [{
            "id": "1",
            "branch": "speed/feat/task-1",
            "files_to_modify": ["src/app.py"],
        }])

        obs1, _ = extract_post_merge("feat", feature_dir, repo)
        obs2, _ = extract_post_merge("feat", feature_dir, repo)
        ids1 = sorted(o.id for o in obs1)
        ids2 = sorted(o.id for o in obs2)
        check("idempotent: same IDs", ids1 == ids2, f"{ids1} vs {ids2}")


# ── Main ─────────────────────────────────────────────────────────────


def main():
    print("\nparse_diff_hunks")
    print("-" * 40)
    test_parse_diff_hunks_transformative()
    test_parse_diff_hunks_additive()
    test_parse_diff_hunks_subtractive()
    test_parse_diff_hunks_cosmetic()
    test_parse_diff_hunks_multiple()

    print("\n_attribute_agent")
    print("-" * 40)
    test_attribute_agent_developer()
    test_attribute_agent_architect()
    test_attribute_agent_subtractive_guardian()

    print("\n_is_noise_file")
    print("-" * 40)
    test_noise_files()

    print("\nextract_post_merge integration")
    print("-" * 40)
    test_zero_delta()
    test_single_correction()
    test_multi_task()
    test_noise_changelog_filtered()
    test_cosmetic_low_weight()
    test_squash_merge()
    test_branch_deleted()
    test_all_branches_deleted()
    test_idempotent()

    print(f"\n{'=' * 40}")
    print(f"{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
