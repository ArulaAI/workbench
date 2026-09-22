import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SPEED = REPO_ROOT / "speed"
PYTHON = REPO_ROOT / ".venv/bin/python3"


def _run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update({"SPEED_PROJECT_ROOT": str(root), "SPEED_PYTHON": str(PYTHON), "VERBOSITY": "0"})
    return subprocess.run(
        [str(SPEED), "define", *args], cwd=root, env=env,
        text=True, capture_output=True, check=False,
    )


def _write_feature(root: Path, feature_dir: Path, name: str = "payments") -> None:
    (root / "specs/product").mkdir(parents=True, exist_ok=True)
    (root / f"specs/product/{name}.md").write_text(f"# {name.title()}\n")
    feature_dir.mkdir(parents=True, exist_ok=True)
    (feature_dir / "risk-surface.yaml").write_text(
        "task: '4'\nclasses:\n"
        "  - id: D1\n"
        "    failureMode: Retry risk\n"
        "    plausible: undecided\n"
        "    signals:\n"
        "      - observed: retry branch\n"
        "        where: [src/retry.py]\n"
    )


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*") if path.is_file()
    }


def test_define_feature_is_read_only_in_single_player(tmp_path: Path) -> None:
    _write_feature(tmp_path, tmp_path / ".speed/features/payments")
    before = _snapshot(tmp_path)
    result = _run(tmp_path, "feature", "payments", "--no-open", "--json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["feature"] == "payments"
    assert payload["findings"][0]["evidence"][0]["producer"] == "diagnose"
    assert _snapshot(tmp_path) == before


def test_define_report_uses_shared_multiplayer_roots_and_repeated_filters(tmp_path: Path) -> None:
    _write_feature(tmp_path, tmp_path / ".speed/shared/features/payments")
    _write_feature(tmp_path, tmp_path / ".speed/shared/features/refunds", "refunds")
    report_dir = tmp_path / "specs/defects"
    report_dir.mkdir(parents=True)
    (report_dir / "retry.md").write_text(
        "# Defect: Retry fails\n\nSeverity: P1\nRelated Features: payments, refunds\nSource: define\n\n"
        "## Observed Behavior\nFails.\n## Expected Behavior\nWorks.\n"
        "## Reproduction Steps\nRun the retry test.\n"
    )
    state_dir = tmp_path / ".speed/shared/defects/retry"
    state_dir.mkdir(parents=True)
    (state_dir / "state.json").write_text(json.dumps({"status": "filed", "reported_severity": "P1"}))
    result = _run(
        tmp_path, "defects", "--feature", "payments", "--feature", "refunds", "--json", "--no-open",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert [row["slug"] for row in payload["rows"]] == ["retry"]
    assert payload["rows"][0]["status"] == "filed"
