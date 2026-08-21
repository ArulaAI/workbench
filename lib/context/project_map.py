"""Project Map builder — Layer 1, Artifact 1.

The canonical file registry. Every file in the project that isn't ignored,
with language, line count, and category. The foundation that the rest of
Layer 1 iterates over.

Usage:
    from lib.context.project_map import build_project_map
    pm = build_project_map("/path/to/project")
    # pm is a dict matching the project-map.json schema

Tech spec: tech-spec-context-constructor.md → Artifact 1
"""

import fnmatch
import os
import re
import subprocess
from collections import defaultdict

from .utils import (
    count_lines,
    git_head_hash,
    is_binary,
    now_iso,
    read_json,
    write_json,
)


# ── Language classification ────────────────────────────────────

from .language_registry import registry

# Hardcoded ignores — always excluded, not configurable.
# Only truly universal directories that are never source code.
HARDCODED_IGNORES = {".git", ".speed", "node_modules", "__pycache__"}

# Extensions that map to a parseable language (e.g. SVG → XML) but are
# visual assets, not config or source.  Overrides the registry category.
_ASSET_EXTENSIONS = {".svg", ".svgz", ".ico"}


# ── Gitignore handling ─────────────────────────────────────────


def _build_git_ignored_set(project_root: str) -> set[str]:
    """Build a set of git-ignored file paths (relative to project root).

    Uses `git ls-files --others --ignored --exclude-standard` for a single
    batch call instead of per-file git check-ignore. Fast even on large repos.
    Falls back to empty set if git is unavailable.
    """
    try:
        result = subprocess.run(
            ["git", "ls-files", "--others", "--ignored", "--exclude-standard"],
            capture_output=True, text=True, cwd=project_root,
            timeout=60,
        )
        if result.returncode == 0:
            return set(line for line in result.stdout.strip().split("\n") if line)
    except (OSError, subprocess.TimeoutExpired):
        pass
    return set()


# ── Category classification ────────────────────────────────────


def _classify_file(
    rel_path: str,
    ext: str,
    extended_categories: dict[str, list[str]],
) -> tuple[str, str | None]:
    """Classify a file into (category, language).

    Returns (category, language) where:
    - category is one of: source, config, asset, or an extended category
    - language is the language name or None for assets
    """
    # Check extended categories first (project-specific overrides)
    for cat_name, patterns in extended_categories.items():
        for pattern in patterns:
            if fnmatch.fnmatch(rel_path, pattern):
                # Extended category overrides base — but still determine language
                _cat, language = registry.classify(ext)
                return cat_name, language

    # Base classification via registry
    category, language = registry.classify(ext)

    # Visual asset override (e.g. .svg classified as XML but really an image)
    if ext in _ASSET_EXTENSIONS:
        category = "asset"

    return category, language


def _parse_extended_categories(config: dict) -> dict[str, list[str]]:
    """Parse [categories] section from speed.toml.

    Returns {category_name: [glob_patterns]}.
    """
    categories_config = config.get("categories", {})
    result = {}
    for name, patterns in categories_config.items():
        if isinstance(patterns, list):
            result[name] = patterns
        elif isinstance(patterns, str):
            result[name] = [patterns]
    return result


def _parse_scope(config: dict) -> list[str]:
    """Parse scope from speed.toml. Returns list of directory prefixes."""
    scope = config.get("scope", [])
    if isinstance(scope, str):
        scope = [scope]
    return scope


def _parse_ignore_patterns(config: dict) -> list[str]:
    """Parse [ignore] section from speed.toml."""
    ignore = config.get("ignore", {})
    patterns = ignore.get("patterns", [])
    if isinstance(patterns, str):
        patterns = [patterns]
    return patterns


# ── Scope and ignore checks ───────────────────────────────────


def _in_scope(rel_path: str, scope: list[str]) -> bool:
    """Check if a path is within the declared scope."""
    if not scope:
        return True  # No scope = everything
    for s in scope:
        s = s.rstrip("/")
        if s == ".":
            return True
        if rel_path.startswith(s + "/") or rel_path == s:
            return True
    return False


def _matches_ignore(rel_path: str, patterns: list[str]) -> bool:
    """Check if a path matches any ignore pattern (gitignore-style globs)."""
    for pattern in patterns:
        # Handle directory patterns ending with /
        if pattern.endswith("/"):
            dir_pattern = pattern.rstrip("/")
            if rel_path.startswith(dir_pattern + "/") or rel_path == dir_pattern:
                return True
            continue

        if fnmatch.fnmatch(rel_path, pattern):
            return True
        # Also check against basename for patterns without /
        if "/" not in pattern and fnmatch.fnmatch(os.path.basename(rel_path), pattern):
            return True

    return False


# ── Main builder ───────────────────────────────────────────────


def build_project_map(
    project_root: str,
    config: dict | None = None,
    use_git_ignore: bool = True,
) -> dict:
    """Build the project map by walking the project tree.

    Args:
        project_root: absolute path to project root (where speed.toml lives)
        config: parsed speed.toml dict (or None for defaults)
        use_git_ignore: whether to respect .gitignore

    Returns:
        project-map.json dict with files[], directories[], summary
    """
    if config is None:
        config = {}

    scope = _parse_scope(config)
    ignore_patterns = _parse_ignore_patterns(config)
    extended_categories = _parse_extended_categories(config)

    # Batch git ignore check — single subprocess call
    git_ignored: set[str] = set()
    if use_git_ignore:
        git_ignored = _build_git_ignored_set(project_root)

    files = []
    dir_stats: dict[str, dict] = defaultdict(lambda: {"file_count": 0, "total_lines": 0})

    # Language rollup for summary
    lang_stats: dict[str, dict] = defaultdict(lambda: {"files": 0, "lines": 0})

    for root, dirs, filenames in os.walk(project_root, followlinks=False):
        rel_root = os.path.relpath(root, project_root)
        if rel_root == ".":
            rel_root = ""

        # Filter directories in-place
        dirs[:] = sorted([
            d for d in dirs
            if d not in HARDCODED_IGNORES
            and _in_scope(
                os.path.join(rel_root, d) if rel_root else d,
                scope,
            )
            and not _matches_ignore(
                os.path.join(rel_root, d) if rel_root else d,
                ignore_patterns,
            )
        ])

        for fname in sorted(filenames):
            if fname.startswith(".") and fname != ".env":
                continue

            rel_path = os.path.join(rel_root, fname) if rel_root else fname
            abs_path = os.path.join(project_root, rel_path)

            # Scope check
            if not _in_scope(rel_path, scope):
                continue

            # Ignore checks
            if _matches_ignore(rel_path, ignore_patterns):
                continue

            # Git ignore check (batch — O(1) set lookup)
            if use_git_ignore and rel_path in git_ignored:
                continue

            # Classify
            ext = os.path.splitext(fname)[1].lower()

            if is_binary(abs_path):
                category = "asset"
                language = None
                lines = None
            else:
                category, language = _classify_file(rel_path, ext, extended_categories)
                # Shebang fallback for extensionless files
                if not ext and language is None:
                    category, language = registry.classify_by_shebang(abs_path)
                lines = count_lines(abs_path)

            file_entry = {
                "path": rel_path,
                "language": language,
                "lines": lines,
                "category": category,
            }
            files.append(file_entry)

            # Update directory stats
            # Accumulate for all parent directories
            parts = rel_path.split("/")
            for i in range(1, len(parts)):
                dir_path = "/".join(parts[:i])
                dir_stats[dir_path]["file_count"] += 1
                if lines is not None:
                    dir_stats[dir_path]["total_lines"] += lines

            # Language stats
            lang_key = language or "other"
            lang_stats[lang_key]["files"] += 1
            if lines is not None:
                lang_stats[lang_key]["lines"] += lines

    # Compute summary
    total_files = len(files)
    total_lines = sum(f["lines"] for f in files if f["lines"] is not None)

    # Build directories list
    directories = [
        {"path": path, "file_count": stats["file_count"], "total_lines": stats["total_lines"]}
        for path, stats in sorted(dir_stats.items())
    ]

    # Build summary
    by_language = {
        lang: {"files": stats["files"], "lines": stats["lines"]}
        for lang, stats in sorted(lang_stats.items())
    }

    return {
        "generated_at": now_iso(),
        "git_head": git_head_hash(project_root),
        "project_root": project_root,
        "summary": {
            "total_files": total_files,
            "total_lines": total_lines,
            "by_language": by_language,
        },
        "files": files,
        "directories": directories,
    }


# ── Persistence ────────────────────────────────────────────────


def save_project_map(project_map: dict, context_dir: str) -> str:
    """Save project map to .speed/context/project-map.json. Returns path."""
    path = os.path.join(context_dir, "project-map.json")
    write_json(path, project_map)
    return path


def load_project_map(context_dir: str) -> dict:
    """Load project map from .speed/context/project-map.json."""
    path = os.path.join(context_dir, "project-map.json")
    return read_json(path)


# ── Queries ────────────────────────────────────────────────────


def get_source_files(project_map: dict) -> list[dict]:
    """Get all source files (category == 'source')."""
    return [f for f in project_map["files"] if f["category"] == "source"]


def get_files_by_language(project_map: dict, language: str) -> list[dict]:
    """Get all files of a specific language."""
    return [f for f in project_map["files"] if f["language"] == language]


def get_file_entry(project_map: dict, rel_path: str) -> dict | None:
    """Look up a file entry by relative path."""
    for f in project_map["files"]:
        if f["path"] == rel_path:
            return f
    return None


def get_directory_stats(project_map: dict, dir_path: str) -> dict | None:
    """Look up directory stats by path."""
    for d in project_map["directories"]:
        if d["path"] == dir_path:
            return d
    return None


def get_files_in_directory(project_map: dict, dir_path: str) -> list[dict]:
    """Get all files under a directory (recursive)."""
    prefix = dir_path.rstrip("/") + "/"
    return [f for f in project_map["files"] if f["path"].startswith(prefix)]


def sum_lines_for_paths(project_map: dict, paths: list[str]) -> int:
    """Sum line counts for a list of file paths. Used by decomposition gate."""
    total = 0
    for path in paths:
        entry = get_file_entry(project_map, path)
        if entry and entry["lines"] is not None:
            total += entry["lines"]
    return total


# ── CLI entry point ────────────────────────────────────────────


def main():
    """CLI entry point for building project map standalone."""
    import sys

    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <project_root> [--json]", file=sys.stderr)
        sys.exit(1)

    project_root = os.path.abspath(sys.argv[1])
    show_json = "--json" in sys.argv

    # Try to load speed.toml
    from .utils import load_speed_toml
    config = load_speed_toml(project_root)

    pm = build_project_map(project_root, config)

    if show_json:
        import json
        print(json.dumps(pm, indent=2))
    else:
        summary = pm["summary"]
        print(f"Project: {project_root}")
        print(f"Files: {summary['total_files']}, Lines: {summary['total_lines']}")
        print(f"Languages: {', '.join(f'{lang} ({stats['files']})' for lang, stats in summary['by_language'].items())}")


if __name__ == "__main__":
    main()
