"""Adapter to the packaged guided-authoring helper.

The interview implementation lives in
`skills/workbench-draft/scripts/draft.py` and is shared byte-for-byte with the
CLI and the projected skill. This module is the only place in the dashboard
that decides how to reach it: helper location, interpreter selection, argument
assembly, and JSON decoding.

It deliberately contains no question wording, option, threshold, or gate. Exit
status is not the error signal: the helper returns a JSON payload for success,
user-actionable errors (1), and revision conflicts (2), and the payload's
`status` field is authoritative.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

log = logging.getLogger("speed.dashboard.authoring")

TIMEOUT_S = 20
_REPO_ROOT = Path(__file__).resolve().parents[2]
_HELPER_RELATIVE = Path("skills") / "workbench-draft" / "scripts" / "draft.py"


class HelperUnavailable(RuntimeError):
    """The helper could not be executed or did not return a JSON payload."""


def helper_path() -> Path:
    override = os.environ.get("WORKBENCH_DRAFT_HELPER")
    if override:
        return Path(override)
    return _REPO_ROOT / _HELPER_RELATIVE


def interpreter(project_root: Path) -> str:
    configured = os.environ.get("SPEED_PYTHON")
    if configured:
        return configured
    for candidate in (
        _REPO_ROOT / ".venv" / "bin" / "python3",
        Path(project_root) / ".venv" / "bin" / "python3",
    ):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return sys.executable


def is_multiplayer(project_root: Path) -> bool:
    return (Path(project_root) / ".speed" / "shared").is_dir()


def dashboard_url() -> str:
    return os.environ.get("WORKBENCH_DASHBOARD_URL", "http://localhost:3000")


def _unavailable(project_root: Path, reason: str) -> dict[str, Any]:
    return {
        "skill": "workbench-draft",
        "status": "helper_unavailable",
        "message": reason,
        "helper_path": str(helper_path()),
        "interpreter": interpreter(project_root),
    }


def run(project_root: str | Path, *args: str) -> dict[str, Any]:
    """Execute the helper and return its decoded payload."""
    root = Path(project_root)
    helper = helper_path()
    if not helper.is_file():
        return _unavailable(root, f"Helper not found at {helper}.")

    helper_args = list(args)
    answer_file: str | None = None
    if "--answer" in helper_args:
        answer_index = helper_args.index("--answer")
        if answer_index + 1 < len(helper_args):
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", prefix="speed-answer-", delete=False
            ) as handle:
                handle.write(helper_args[answer_index + 1])
                answer_file = handle.name
            helper_args[answer_index:answer_index + 2] = ["--answer-file", answer_file]

    command = [
        interpreter(root),
        str(helper),
        *helper_args,
        "--project-root",
        str(root),
        "--dashboard-url",
        dashboard_url(),
        "--json",
    ]
    try:
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_S,
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired:
            return _unavailable(root, f"Helper did not respond within {TIMEOUT_S}s.")
        except OSError as exc:
            return _unavailable(root, f"Helper could not be executed: {exc}")
    finally:
        if answer_file:
            try:
                Path(answer_file).unlink()
            except OSError:
                pass

    if not completed.stdout.strip():
        log.warning("draft helper returned no payload: %s", completed.stderr[:400])
        return _unavailable(
            root,
            "Helper returned no payload. "
            + (completed.stderr.strip().splitlines() or ["No stderr output."])[-1],
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        log.warning("draft helper returned non-JSON output")
        return _unavailable(root, "Helper returned output that is not valid JSON.")
    if not isinstance(payload, dict):
        return _unavailable(root, "Helper returned a payload that is not an object.")
    return payload
