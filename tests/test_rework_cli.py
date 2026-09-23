import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON = REPO_ROOT / ".venv/bin/python3"


def _run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)
    return subprocess.run(
        [str(PYTHON), "-m", "lib.rework_cli", *args, "--project-root", str(root), "--feature", "payments"],
        cwd=REPO_ROOT, env=env, text=True, capture_output=True, check=False,
    )


def test_rework_queue_reads_and_acknowledges_once(tmp_path: Path) -> None:
    feature_dir = tmp_path / ".speed/features/payments"
    feature_dir.mkdir(parents=True)
    (feature_dir / "findings.json").write_text(json.dumps({
        "schema_version": 1, "revision": 3, "groups": {}, "group_history": [],
        "decisions": [{"id": "request-1", "rationale": "Repair retry", "task_id": "4"}],
        "rework": {"request-1": {"task_id": "4", "status": "queued", "error": None}},
    }))
    queued = _run(tmp_path, "next")
    assert queued.returncode == 0
    assert json.loads(queued.stdout) == {
        "request_id": "request-1", "task_id": "4", "guidance": "Repair retry",
    }
    applied = _run(tmp_path, "ack", "--request-id", "request-1", "--status", "applied")
    assert applied.returncode == 0
    replay = _run(tmp_path, "ack", "--request-id", "request-1", "--status", "applied")
    assert replay.returncode == 0
    assert _run(tmp_path, "next").returncode == 3
    saved = json.loads((feature_dir / "findings.json").read_text())
    assert saved["revision"] == 4
    assert saved["rework"]["request-1"]["status"] == "applied"
