"""Code Context — Layer 2, Dimension 1.

Graph expansion from files_touched → 1-hop (full) → 2-hop (skeleton).
Answers: "What code does this task need to see?"

Tier structure:
  Distance 0 (files_touched): full file content — never cut
  Distance 1 (1-hop callers/callees): full content (downgrade if >2000 lines)
  Distance 2 (2-hop): skeleton only
  Distance 3+: nothing (agent reads on demand)

Usage:
    from lib.context.code_context import build_code_context
    ctx = build_code_context(task, project_root, csg, project_map, context_dir)

Tech spec: tech-spec-context-constructor.md → Layer 2 § Code Context
"""

from __future__ import annotations

import os
from collections import defaultdict
from typing import Any

from .skeletons import load_skeleton
from .utils import estimate_tokens_from_lines, write_json, read_json


FULL_CONTENT_THRESHOLD = 2000  # lines — 1-hop files above this downgrade to skeleton


# ── Graph expansion ──────────────────────────────────────────


def _resolve_files_to_symbols(
    files: list[str],
    csg: dict,
) -> list[str]:
    """Get all symbol IDs in the given files."""
    symbol_ids = []
    for node in csg.get("nodes", []):
        if node["file"] in files:
            symbol_ids.append(node["id"])
    return symbol_ids


def _get_connected_symbols(
    symbol_ids: list[str],
    csg: dict,
    exclude: set[str],
) -> dict[str, str]:
    """Get symbols connected to the given symbols via reference edges.

    Returns dict of {symbol_id: relationship_description}.
    """
    reference_types = {"calls", "instantiates", "references_type", "accesses", "inherits", "implements"}
    connected: dict[str, str] = {}

    for edge in csg.get("edges", []):
        if edge["type"] not in reference_types:
            continue

        if edge["from"] in symbol_ids and edge["to"] not in exclude:
            connected[edge["to"]] = f"{edge['type']} from {edge['from'].split('::')[-1]}"
        if edge["to"] in symbol_ids and edge["from"] not in exclude:
            connected[edge["from"]] = f"calls {edge['to'].split('::')[-1]}"

    return connected


def _symbols_to_files(
    symbol_ids: list[str],
    csg: dict,
) -> set[str]:
    """Map symbol IDs to their file paths."""
    node_lookup = {n["id"]: n for n in csg.get("nodes", [])}
    files = set()
    for sid in symbol_ids:
        node = node_lookup.get(sid)
        if node:
            files.add(node["file"])
    return files


def _directory_neighbors(
    new_files: list[str],
    csg: dict,
) -> list[str]:
    """For files not in CSG (new files), find symbols in same directory."""
    neighbor_symbols = []
    known_files = {n["file"] for n in csg.get("nodes", [])}

    for f in new_files:
        if f in known_files:
            continue
        dir_path = os.path.dirname(f)
        for node in csg.get("nodes", []):
            if os.path.dirname(node["file"]) == dir_path:
                neighbor_symbols.append(node["id"])

    return neighbor_symbols


# ── Content reading ──────────────────────────────────────────


def _read_file_content(project_root: str, rel_path: str) -> str | None:
    """Read full file content. Returns None if file doesn't exist."""
    abs_path = os.path.join(project_root, rel_path)
    try:
        with open(abs_path) as f:
            return f.read()
    except OSError:
        return None


def _get_file_lines(rel_path: str, project_map: dict) -> int | None:
    """Get line count for a file from the project map."""
    for f in project_map.get("files", []):
        if f["path"] == rel_path:
            return f.get("lines")
    return None


# ── Builder ──────────────────────────────────────────────────


def build_code_context(
    task: dict,
    project_root: str,
    csg: dict,
    project_map: dict,
    context_dir: str,
) -> dict:
    """Build code context for a task via graph expansion.

    Args:
        task: task dict with files_touched
        project_root: absolute path to project root
        csg: semantic-graph.json dict
        project_map: project-map.json dict
        context_dir: path to .speed/context/ for loading skeletons

    Returns:
        code-context.json dict with full_content, skeleton, symbols_in_scope,
        expansion_summary.
    """
    files_touched = task.get("files_touched", [])
    files_touched_set = set(files_touched)

    # Step 1: Collect seed symbols (distance 0)
    seed_symbols = _resolve_files_to_symbols(files_touched, csg)

    # Handle new files (not in CSG) via directory-neighbor heuristic
    neighbor_symbols = _directory_neighbors(files_touched, csg)
    seed_symbols.extend(neighbor_symbols)
    seed_set = set(seed_symbols)

    # Step 2: Expand to 1-hop
    one_hop_connected = _get_connected_symbols(seed_symbols, csg, seed_set)
    one_hop_symbols = set(one_hop_connected.keys())
    one_hop_files = _symbols_to_files(list(one_hop_symbols), csg) - files_touched_set

    # Step 3: Expand to 2-hop
    all_near = seed_set | one_hop_symbols
    two_hop_connected = _get_connected_symbols(list(one_hop_symbols), csg, all_near)
    two_hop_symbols = set(two_hop_connected.keys())
    two_hop_files = _symbols_to_files(list(two_hop_symbols), csg) - files_touched_set - one_hop_files

    # Step 4: Apply size safety valve — large 1-hop files downgrade to skeleton
    full_one_hop = []
    downgraded_one_hop = []

    for f in sorted(one_hop_files):
        lines = _get_file_lines(f, project_map)
        if lines is not None and lines > FULL_CONTENT_THRESHOLD:
            downgraded_one_hop.append(f)
        else:
            full_one_hop.append(f)

    # Step 5: Assemble code context
    # Tier 0: files_touched — full content
    tier0 = []
    for f in files_touched:
        content = _read_file_content(project_root, f)
        if content is not None:
            tier0.append({"path": f, "content": content})

    # Tier 1: 1-hop — full content (non-downgraded)
    # Include skeleton_content for budget downgrade support
    tier1 = []
    for f in full_one_hop:
        content = _read_file_content(project_root, f)
        if content is not None:
            # Find the relationship description
            rel = ""
            for sid, desc in one_hop_connected.items():
                node = _find_node(sid, csg)
                if node and node["file"] == f:
                    rel = desc
                    break
            entry = {"path": f, "content": content, "relationship": rel}
            skeleton = load_skeleton(context_dir, f)
            if skeleton:
                entry["skeleton_content"] = skeleton
            tier1.append(entry)

    # Tier 2: 2-hop + downgraded 1-hop — skeleton
    tier2_files = sorted(two_hop_files | set(downgraded_one_hop))
    tier2 = []
    for f in tier2_files:
        skeleton = load_skeleton(context_dir, f)
        if skeleton:
            rel = ""
            for sid, desc in {**two_hop_connected, **one_hop_connected}.items():
                node = _find_node(sid, csg)
                if node and node["file"] == f:
                    rel = desc
                    break
            tier2.append({"path": f, "skeleton_content": skeleton, "relationship": rel})

    # Symbols in scope (distance 0 and 1)
    symbols_in_scope = sorted(seed_set | one_hop_symbols)

    # Token estimation
    tier0_tokens = sum(
        estimate_tokens_from_lines(len(entry["content"].splitlines()))
        for entry in tier0
    )
    tier1_tokens = sum(
        estimate_tokens_from_lines(len(entry["content"].splitlines()))
        for entry in tier1
    )
    tier2_tokens = sum(
        estimate_tokens_from_lines(len(entry["skeleton_content"].splitlines()))
        for entry in tier2
    )

    return {
        "full_content": {
            "files_touched": tier0,
            "one_hop": tier1,
        },
        "skeleton": {
            "two_hop": tier2,
        },
        "symbols_in_scope": symbols_in_scope,
        "expansion_summary": {
            "seed_files": len(files_touched),
            "one_hop_files": len(full_one_hop),
            "one_hop_downgraded": len(downgraded_one_hop),
            "two_hop_files": len(two_hop_files),
            "total_tokens_estimate": tier0_tokens + tier1_tokens + tier2_tokens,
        },
    }


def _find_node(symbol_id: str, csg: dict) -> dict | None:
    """Look up a CSG node by symbol ID."""
    for node in csg.get("nodes", []):
        if node["id"] == symbol_id:
            return node
    return None


# ── Persistence ──────────────────────────────────────────────


def save_code_context(code_context: dict, task_context_dir: str) -> str:
    """Save code context to task's context directory. Returns path."""
    path = os.path.join(task_context_dir, "code-context.json")
    write_json(path, code_context)
    return path


def load_code_context(task_context_dir: str) -> dict:
    """Load code context from task's context directory."""
    path = os.path.join(task_context_dir, "code-context.json")
    return read_json(path)
