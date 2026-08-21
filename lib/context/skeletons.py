"""File Skeletons — Layer 1, Artifact 3.

Compressed text representations of source files: imports, signatures,
type annotations, class/function structure — without implementation bodies.
~10:1 compression ratio. Used as the "medium detail" tier in Layer 2
context assembly.

Directory: `.speed/context/skeletons/{relative_path}.skeleton`

Built from the same tree-sitter parse used for the CSG — no additional
file reads. Complements the CSG: the CSG is structured JSON for the
orchestrator, skeletons are text for agent prompts.

Usage:
    from lib.context.skeletons import build_skeletons, load_skeleton
    stats = build_skeletons(project_root, project_map, extractor, context_dir)
    text = load_skeleton(context_dir, "lib/context/utils.py")

Tech spec: tech-spec-context-constructor.md → Artifact 3
"""

import os
from typing import Any

from .treesitter_extract import ExtractionResult, Extractor
from .utils import ensure_dir


# ── Builder ──────────────────────────────────────────────────


def build_skeletons(
    project_root: str,
    project_map: dict,
    extractor: Extractor,
    context_dir: str,
    extraction_cache: dict[str, ExtractionResult] | None = None,
) -> dict:
    """Build skeleton files for all source files in the project map.

    Args:
        project_root: absolute path to project root
        project_map: project-map.json dict (from build_project_map)
        extractor: initialized Extractor instance
        context_dir: path to .speed/context/ directory
        extraction_cache: optional pre-computed extraction results
            (avoids re-parsing files that were already extracted for CSG)

    Returns:
        Summary dict: {files_processed, files_skipped, total_source_lines,
                       total_skeleton_lines, compression_ratio}
    """
    skeletons_dir = os.path.join(context_dir, "skeletons")
    ensure_dir(skeletons_dir)

    files_processed = 0
    files_skipped = 0
    total_source_lines = 0
    total_skeleton_lines = 0

    for file_entry in project_map.get("files", []):
        language = file_entry.get("language")
        category = file_entry.get("category")
        rel_path = file_entry["path"]
        source_lines = file_entry.get("lines")

        # Only generate skeletons for source files with a parseable language
        if category != "source" or not language:
            continue

        if not extractor.can_parse(language):
            files_skipped += 1
            continue

        # Use cached extraction if available
        if extraction_cache and rel_path in extraction_cache:
            skeleton_lines = extraction_cache[rel_path].skeleton_lines
        else:
            abs_path = os.path.join(project_root, rel_path)
            result = extractor.extract_file(abs_path, language, rel_path)
            skeleton_lines = result.skeleton_lines

        if not skeleton_lines:
            files_skipped += 1
            continue

        # Write skeleton file
        skeleton_path = os.path.join(skeletons_dir, rel_path + ".skeleton")
        ensure_dir(os.path.dirname(skeleton_path))

        with open(skeleton_path, "w") as f:
            f.write("\n".join(skeleton_lines))
            f.write("\n")

        files_processed += 1
        if source_lines is not None:
            total_source_lines += source_lines
        total_skeleton_lines += len(skeleton_lines)

    compression_ratio = (
        round(total_source_lines / total_skeleton_lines, 1)
        if total_skeleton_lines > 0
        else 0
    )

    return {
        "files_processed": files_processed,
        "files_skipped": files_skipped,
        "total_source_lines": total_source_lines,
        "total_skeleton_lines": total_skeleton_lines,
        "compression_ratio": compression_ratio,
    }


# ── Loaders ──────────────────────────────────────────────────


def load_skeleton(context_dir: str, rel_path: str) -> str | None:
    """Load a skeleton file for a given source file path.

    Returns the skeleton text, or None if no skeleton exists.
    """
    skeleton_path = os.path.join(context_dir, "skeletons", rel_path + ".skeleton")
    try:
        with open(skeleton_path) as f:
            return f.read()
    except OSError:
        return None


def skeleton_exists(context_dir: str, rel_path: str) -> bool:
    """Check if a skeleton file exists for the given source file."""
    skeleton_path = os.path.join(context_dir, "skeletons", rel_path + ".skeleton")
    return os.path.isfile(skeleton_path)


def list_skeletons(context_dir: str) -> list[str]:
    """List all skeleton files. Returns relative source paths (without .skeleton suffix)."""
    skeletons_dir = os.path.join(context_dir, "skeletons")
    if not os.path.isdir(skeletons_dir):
        return []

    result = []
    suffix = ".skeleton"
    for root, _dirs, files in os.walk(skeletons_dir):
        for fname in files:
            if fname.endswith(suffix):
                full = os.path.join(root, fname)
                rel = os.path.relpath(full, skeletons_dir)
                # Strip .skeleton suffix to get original source path
                result.append(rel[: -len(suffix)])

    return sorted(result)
