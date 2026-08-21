"""GraphQL resolver for the bootstrap wizard.

Handles the cold-start flow: graph build check, vision generation/commit,
convention extraction/review/commit, and bootstrap completion.

NOTE: Graph building and vision generation are stub implementations.
Actual LLM calls are deferred to avoid heavy compute. The stubs check
for existing artifacts and return their contents or placeholder data.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..paths import get_paths
from .ceremony_types import _read_json, _write_json

log = logging.getLogger("speed.dashboard.ceremony.bootstrap")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Queries ───────────────────────────────────────────────────────


def get_bootstrap_status(project_root: Path) -> dict[str, Any]:
    paths = get_paths(project_root)

    graph_path = project_root / ".speed" / "context" / "semantic-graph.json"
    graph_built = graph_path.exists()

    vision_path = project_root / ".speed" / "context" / "vision.md"
    vision_committed = vision_path.exists()

    conventions_path = paths.conventions_path
    conventions_committed = conventions_path.exists()

    all_done = graph_built and vision_committed and conventions_committed
    marker = project_root / ".speed" / "bootstrap-complete"
    if marker.exists():
        all_done = True

    current_step = "complete"
    if not graph_built:
        current_step = "graph"
    elif not vision_committed:
        current_step = "vision"
    elif not conventions_committed:
        current_step = "conventions"

    return {
        "needs_bootstrap": not all_done,
        "graph_built": graph_built,
        "vision_committed": vision_committed,
        "conventions_committed": conventions_committed,
        "current_step": current_step,
    }


def get_derived_conventions(project_root: Path) -> list[dict[str, Any]]:
    paths = get_paths(project_root)
    data = _read_json(paths.conventions_path)
    if data is None:
        return []
    conventions = data if isinstance(data, list) else data.get("conventions", [])
    return conventions


def get_vision_draft(project_root: Path) -> dict[str, Any]:
    vision_path = project_root / ".speed" / "context" / "vision.md"
    if vision_path.exists():
        content = vision_path.read_text(encoding="utf-8")
        return {"content": content, "status": "committed"}

    draft_path = project_root / ".speed" / "context" / "vision-draft.md"
    if draft_path.exists():
        content = draft_path.read_text(encoding="utf-8")
        return {"content": content, "status": "draft"}

    return {"content": "", "status": "missing"}


# ── Mutations ─────────────────────────────────────────────────────


def start_graph_build(project_root: Path) -> dict[str, Any]:
    """Check if graph exists, return stats. Does NOT run the actual build."""
    graph_path = project_root / ".speed" / "context" / "semantic-graph.json"

    if graph_path.exists():
        try:
            data = json.loads(graph_path.read_text(encoding="utf-8"))
            nodes = data.get("nodes", [])
            files = {n.get("file", "") for n in nodes if n.get("file")}
            return {
                "status": "complete",
                "file_count": len(files),
                "node_count": len(nodes),
            }
        except (json.JSONDecodeError, OSError):
            pass

    return {
        "status": "not_built",
        "file_count": 0,
        "node_count": 0,
        "message": "Run `speed plan` to build the semantic graph.",
    }


def generate_vision(project_root: Path) -> dict[str, Any]:
    """Return existing vision or a stub. Does NOT call LLM."""
    vision_path = project_root / ".speed" / "context" / "vision.md"
    if vision_path.exists():
        return {
            "generated_content": vision_path.read_text(encoding="utf-8"),
            "status": "complete",
        }

    draft_path = project_root / ".speed" / "context" / "vision-draft.md"
    if draft_path.exists():
        return {
            "generated_content": draft_path.read_text(encoding="utf-8"),
            "status": "complete",
        }

    return {
        "generated_content": "",
        "status": "unavailable",
        "message": "Vision generation requires LLM. Run bootstrap from CLI.",
    }


def commit_vision(project_root: Path, content: str) -> dict[str, Any]:
    vision_path = project_root / ".speed" / "context" / "vision.md"
    vision_path.parent.mkdir(parents=True, exist_ok=True)
    vision_path.write_text(content, encoding="utf-8")
    log.info("Vision committed: %d chars", len(content))
    return {"committed": True, "path": str(vision_path)}


def extract_conventions(project_root: Path) -> list[dict[str, Any]]:
    """Load existing conventions or return empty. Does NOT run extraction."""
    paths = get_paths(project_root)
    data = _read_json(paths.conventions_path)
    if data is None:
        return []
    conventions = data if isinstance(data, list) else data.get("conventions", [])
    # Ensure each has an id and status
    for i, c in enumerate(conventions):
        c.setdefault("id", f"conv-{i}")
        c.setdefault("status", "pending")
    return conventions


def resolve_convention(
    project_root: Path, convention_id: str, action: str
) -> dict[str, Any]:
    if action not in ("accept", "reject"):
        raise ValueError(f"Invalid action: {action}")

    paths = get_paths(project_root)
    data = _read_json(paths.conventions_path)
    if data is None:
        raise FileNotFoundError("No conventions file")

    conventions = data if isinstance(data, list) else data.get("conventions", [])
    for c in conventions:
        if c.get("id") == convention_id:
            c["status"] = "accepted" if action == "accept" else "rejected"
            if isinstance(data, list):
                _write_json(paths.conventions_path, data)
            else:
                data["conventions"] = conventions
                _write_json(paths.conventions_path, data)
            return c
    raise FileNotFoundError(f"Convention {convention_id} not found")


def commit_conventions(
    project_root: Path, persona_input: str | None = None
) -> dict[str, Any]:
    paths = get_paths(project_root)
    data = _read_json(paths.conventions_path)
    if data is None:
        data = []

    conventions = data if isinstance(data, list) else data.get("conventions", [])
    accepted = [c for c in conventions if c.get("status") == "accepted"]

    output = {
        "conventions": accepted,
        "committed_at": _now_iso(),
    }
    if persona_input:
        output["persona"] = persona_input

    _write_json(paths.conventions_path, output)
    log.info("Conventions committed: %d accepted", len(accepted))
    return {"committed": True, "accepted_count": len(accepted)}


def complete_bootstrap(project_root: Path) -> dict[str, Any]:
    marker = project_root / ".speed" / "bootstrap-complete"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(_now_iso(), encoding="utf-8")
    log.info("Bootstrap complete")
    return {"complete": True}
