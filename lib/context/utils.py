"""Shared utilities for the context pipeline.

JSON I/O, path normalization, token estimation, config loading.
"""

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


# ── JSON I/O ────────────────────────────────────────────────────


def write_json(path: str, data: dict) -> None:
    """Write JSON with consistent formatting. Creates parent dirs."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def read_json(path: str) -> dict:
    """Read JSON file. Returns empty dict if file doesn't exist."""
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


class DigestValidationError(Exception):
    """A persisted context digest (CSG, project map, ...) exists on disk but
    is not trustworthy — malformed JSON or a structure that fails schema
    validation.

    Deliberately distinct from "file doesn't exist" (read_json_or_none
    returns None for that — a normal, expected first-run state). A digest
    that exists but is corrupt or truncated must never be silently treated
    as an empty-but-valid one: an empty CSG and a corrupt CSG look
    identical to `.get("nodes", [])`-style callers, but only one of them
    is actually safe to build downstream context from.
    """


def read_json_or_none(path: str) -> dict | None:
    """Read JSON file. Returns None if the file doesn't exist.

    Raises DigestValidationError if the file exists but isn't valid JSON.
    Callers that need to tell "not built yet" apart from "built but
    corrupted" (e.g. digest loaders that should trigger a rebuild rather
    than silently proceeding on empty data) should use this instead of
    read_json.
    """
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise DigestValidationError(f"{path} exists but is not valid JSON: {e}") from e


# ── Git helpers ─────────────────────────────────────────────────


def git_head_hash(project_root: str) -> str:
    """Get current git HEAD hash. Returns empty string if not a git repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=project_root,
            timeout=30,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


# ── Path helpers ────────────────────────────────────────────────


def relative_path(file_path: str, project_root: str) -> str:
    """Convert absolute path to project-relative path."""
    return os.path.relpath(file_path, project_root)


def ensure_dir(path: str) -> None:
    """Create directory and parents if they don't exist."""
    os.makedirs(path, exist_ok=True)


# ── Token estimation ───────────────────────────────────────────


# Rough estimation: 1 token ~ 4 characters.
# For code: avg ~80 chars per line → ~20 tokens per line.
CHARS_PER_TOKEN = 4
AVG_CHARS_PER_LINE = 80


def estimate_tokens_from_lines(line_count: int) -> int:
    """Estimate token count from line count. Rough — for budgeting, not billing."""
    return (line_count * AVG_CHARS_PER_LINE) // CHARS_PER_TOKEN


def estimate_tokens_from_text(text: str) -> int:
    """Estimate token count from text content."""
    return len(text) // CHARS_PER_TOKEN


def estimate_skeleton_tokens(line_count: int) -> int:
    """Estimate tokens for a skeleton (~10:1 compression ratio)."""
    skeleton_lines = max(1, line_count // 10)
    return estimate_tokens_from_lines(skeleton_lines)


# ── Staleness check ────────────────────────────────────────────


def is_stale(context_dir: str, project_root: str) -> bool:
    """Check if context artifacts are stale (git HEAD has moved).

    Returns True if artifacts should be rebuilt.
    """
    githead_file = os.path.join(context_dir, ".githead")
    if not os.path.exists(githead_file):
        return True

    try:
        with open(githead_file) as f:
            cached_hash = f.read().strip()
    except OSError:
        return True

    current_hash = git_head_hash(project_root)
    return cached_hash != current_hash


def write_githead(context_dir: str, project_root: str) -> None:
    """Write current git HEAD hash to staleness marker."""
    githead_file = os.path.join(context_dir, ".githead")
    ensure_dir(context_dir)
    current_hash = git_head_hash(project_root)
    with open(githead_file, "w") as f:
        f.write(current_hash + "\n")


# ── Timestamp ──────────────────────────────────────────────────


def now_iso() -> str:
    """Current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Config loading ─────────────────────────────────────────────


def load_speed_toml(project_root: str) -> dict:
    """Load speed.toml configuration. Returns empty dict if missing."""
    toml_path = os.path.join(project_root, "speed.toml")
    if not os.path.isfile(toml_path):
        return {}

    # Try tomllib (3.11+), then tomli, then fall back to empty
    try:
        import tomllib
        with open(toml_path, "rb") as f:
            return tomllib.load(f)
    except ImportError:
        pass

    try:
        import tomli
        with open(toml_path, "rb") as f:
            return tomli.load(f)
    except ImportError:
        pass

    return {}


def get_context_budgets(config: dict) -> dict:
    """Extract context budgets from speed.toml config. Returns defaults for missing keys."""
    defaults = {
        "architect": 60000,
        "verifier": 40000,
        "developer": 80000,
        "reviewer": 60000,
        "coherence": 100000,
        "debugger": 50000,
        "related_specs": 15000,
    }
    budgets = config.get("context", {}).get("budgets", {})
    return {stage: budgets.get(stage, default) for stage, default in defaults.items()}


# ── Binary detection ───────────────────────────────────────────


def is_binary(file_path: str) -> bool:
    """Check if a file is binary (contains null byte in first 8KB).

    Same heuristic as git diff.
    """
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(8192)
        return b"\x00" in chunk
    except OSError:
        return True  # Can't read = treat as binary


# ── Line counting ──────────────────────────────────────────────


def count_lines(file_path: str) -> int | None:
    """Count lines in a file. Returns None for binary files."""
    if is_binary(file_path):
        return None
    try:
        with open(file_path, "rb") as f:
            return sum(1 for _ in f)
    except OSError:
        return None
