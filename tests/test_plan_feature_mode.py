"""Tests for `speed plan --feature NAME` discovery, naming and input errors.

Only paths that exit before any agent call are exercised, so no provider is needed.
"""

import os
import subprocess
from pathlib import Path

import pytest

SPEED_DIR = Path(__file__).resolve().parent.parent
FEATURES_SH = SPEED_DIR / "lib" / "features.sh"
SPEED_BIN = SPEED_DIR / "speed"


def _bash(script: str, project_root: Path) -> str:
    result = subprocess.run(
        ["bash", "-c", f'set -euo pipefail; source "{FEATURES_SH}"; PROJECT_ROOT="{project_root}"; {script}'],
        capture_output=True, text=True, check=True,
    )
    return result.stdout


def _write(root: Path, rel: str, text: str = "# doc\n") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def course_layout(tmp_path: Path) -> Path:
    """The 301.1E adaptive-auth layout, plus a shared overview and noise files."""
    for rel in [
        "specs/product/overview.md",
        "specs/product/adaptive-auth/2-card-testing.md",
        "specs/product/adaptive-auth/1-high-value-traveller.md",
        "specs/architecture/overview.md",
        "specs/architecture/adaptive-auth.md",
        "specs/design/adaptive-auth/1-checkout-challenge.md",
        "specs/design/adaptive-auth/2-risk-review-queue.md",
        "specs/tech/adaptive-auth/10-later.md",
        "specs/tech/adaptive-auth/2-card-testing.md",
        "specs/tech/adaptive-auth/1-high-value-traveller.md",
        "specs/tech/adaptive-auth-extra.md",
    ]:
        _write(tmp_path, rel)
    (tmp_path / "specs/tech/adaptive-auth/.gitkeep").write_text("")
    return tmp_path


def _discover(root: Path, name: str) -> list[tuple[str, str]]:
    out = _bash(f"feature_discover_specs {name}", root)
    rows = []
    for line in out.splitlines():
        kind, path = line.split("\t")
        rows.append((kind, os.path.relpath(path, root)))
    return rows


class TestDiscovery:
    def test_course_layout_order_and_membership(self, course_layout):
        assert _discover(course_layout, "adaptive-auth") == [
            ("product", "specs/product/adaptive-auth/1-high-value-traveller.md"),
            ("product", "specs/product/adaptive-auth/2-card-testing.md"),
            ("architecture", "specs/architecture/adaptive-auth.md"),
            ("design", "specs/design/adaptive-auth/1-checkout-challenge.md"),
            ("design", "specs/design/adaptive-auth/2-risk-review-queue.md"),
            ("tech", "specs/tech/adaptive-auth/1-high-value-traveller.md"),
            ("tech", "specs/tech/adaptive-auth/2-card-testing.md"),
            ("tech", "specs/tech/adaptive-auth/10-later.md"),
        ]

    def test_shared_overviews_and_prefix_lookalikes_excluded(self, course_layout):
        paths = [p for _, p in _discover(course_layout, "adaptive-auth")]
        assert "specs/architecture/overview.md" not in paths
        assert "specs/product/overview.md" not in paths
        assert "specs/tech/adaptive-auth-extra.md" not in paths

    def test_flat_and_nested_both_belong(self, tmp_path):
        _write(tmp_path, "specs/tech/billing.md")
        _write(tmp_path, "specs/tech/billing/1.md")
        assert [p for _, p in _discover(tmp_path, "billing")] == [
            "specs/tech/billing.md",
            "specs/tech/billing/1.md",
        ]

    def test_symlinks_skipped(self, tmp_path):
        _write(tmp_path, "specs/tech/f/1.md")
        (tmp_path / "specs/tech/f/2.md").symlink_to(tmp_path / "specs/tech/f/1.md")
        assert [p for _, p in _discover(tmp_path, "f")] == ["specs/tech/f/1.md"]

    def test_unknown_feature_is_empty(self, course_layout):
        assert _discover(course_layout, "nope") == []


class TestFeatureNameFromSpec:
    @pytest.mark.parametrize("path,expected", [
        ("specs/tech/adaptive-auth/1-high-value-traveller.md", "adaptive-auth"),
        ("/abs/specs/design/adaptive-auth/2-risk-review-queue.md", "adaptive-auth"),
        ("specs/tech/adaptive-auth/sub/3.md", "adaptive-auth"),
        ("specs/tech/payments.md", "payments"),
        ("/tmp/my-feature.md", "my-feature"),
    ])
    def test_name(self, path, expected, tmp_path):
        assert _bash(f'feature_name_from_spec "{path}"', tmp_path).strip() == expected


def _plan(project: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(SPEED_BIN), "plan", *args],
        cwd=project, capture_output=True, text=True, stdin=subprocess.DEVNULL,
        env={**os.environ, "SPEED_PROJECT_ROOT": str(project)},
    )


class TestPlanFeatureModeErrors:
    @pytest.fixture
    def project(self, tmp_path):
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        _write(tmp_path, "specs/product/onlyprd/1.md")
        return tmp_path

    def test_path_given_as_feature_name(self, project):
        r = _plan(project, "--feature", "specs/design/x/1.md")
        assert r.returncode == 3, r.stdout + r.stderr
        assert "Invalid feature name" in r.stdout + r.stderr

    def test_feature_with_no_documents(self, project):
        r = _plan(project, "--feature", "nope")
        assert r.returncode == 3, r.stdout + r.stderr
        assert "No documents found for feature 'nope'" in r.stdout + r.stderr

    def test_feature_with_no_tech_spec(self, project):
        r = _plan(project, "--feature", "onlyprd", "--skip-audit")
        assert r.returncode == 3, r.stdout + r.stderr
        assert "has no tech spec" in r.stdout + r.stderr
        assert not (project / ".speed" / "features" / "onlyprd").exists()

    def test_no_file_and_no_feature_shows_both_usages(self, project):
        r = _plan(project)
        assert r.returncode == 1
        assert "speed plan --feature NAME" in r.stdout + r.stderr
