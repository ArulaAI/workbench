"""Layer 1 Orchestration — Pre-Computed Context Infrastructure.

Coordinates all Layer 1 artifacts in order:
  1. Project Map (file registry)
  2. tree-sitter extraction (parse all source files once)
  3. Codebase Semantic Graph (symbols → references → clusters → impact)
  4. File Skeletons (compressed text per file)
  5. Spec-Codebase Alignment (spec claims vs codebase reality)

Staleness check: skip rebuild if git HEAD unchanged (unless --fresh).
Extraction cache: files parsed once, results shared between CSG and skeletons.

Storage:
  Codebase-scoped: `.speed/context/`
  Feature-scoped:  `.speed/features/{feature}/context/`

Usage:
    from lib.context.layer1 import build_layer1
    result = build_layer1("/path/to/project")

Tech spec: tech-spec-context-constructor.md → Layer 1
"""

from __future__ import annotations

import os
import sys
import time
import warnings
from typing import Any

from .csg import build_csg, save_csg
from .env_extract import extract_env_keys
from .language_registry import registry
from .project_map import build_project_map, get_source_files, save_project_map
from .skeletons import build_skeletons
from .spec_alignment import build_spec_alignment, save_spec_alignment
from .treesitter_extract import Extractor
from .utils import (
    ensure_dir,
    is_stale,
    load_speed_toml,
    write_githead,
    write_json,
)


def build_layer1(
    project_root: str,
    config: dict | None = None,
    context_dir: str | None = None,
    spec_files: dict[str, str] | None = None,
    fresh: bool = False,
) -> dict:
    """Build all Layer 1 artifacts.

    Args:
        project_root: absolute path to project root
        config: parsed speed.toml dict (or None to load from project root)
        context_dir: where to write artifacts (default: .speed/context/)
        spec_files: dict of {spec_path: content} for spec alignment
            (or None to skip spec alignment)
        fresh: if True, rebuild even if artifacts aren't stale

    Returns:
        Summary dict with timing, artifact paths, and statistics.
    """
    t_start = time.time()
    warnings.filterwarnings("ignore", category=SyntaxWarning)

    # Load config if not provided
    if config is None:
        config = load_speed_toml(project_root)

    # Default context directory
    if context_dir is None:
        context_dir = os.path.join(project_root, ".speed", "context")

    ensure_dir(context_dir)

    # Staleness check
    if not fresh and not is_stale(context_dir, project_root):
        return {
            "status": "skipped",
            "reason": "artifacts up to date (git HEAD unchanged)",
            "context_dir": context_dir,
        }

    result: dict[str, Any] = {
        "status": "built",
        "context_dir": context_dir,
        "artifacts": {},
        "timing": {},
    }

    # ── Step 1: Project Map ──────────────────────────────────
    print("  project map...", end="", flush=True, file=sys.stderr)
    t0 = time.time()
    project_map = build_project_map(project_root, config)
    pm_path = save_project_map(project_map, context_dir)
    result["timing"]["project_map"] = round(time.time() - t0, 3)
    result["artifacts"]["project_map"] = pm_path
    result["project_map_summary"] = project_map["summary"]
    total_files = project_map["summary"]["total_files"]
    print(f" ✓ {result['timing']['project_map']}s ({total_files} files)", file=sys.stderr)

    # ── Missing grammar warnings ─────────────────────────────
    languages_in_project = {
        f["language"] for f in project_map.get("files", []) if f.get("language")
    }
    unparseable = {
        lang for lang in languages_in_project
        if lang in registry._by_name and not registry.can_parse(lang)
    }
    if unparseable:
        # Count files per unparseable language
        file_counts: dict[str, int] = {}
        for f in project_map.get("files", []):
            lang = f.get("language")
            if lang in unparseable:
                file_counts[lang] = file_counts.get(lang, 0) + 1

        parts = [
            f"{count} .{registry._by_name[lang].extensions[0].lstrip('.')} files"
            for lang, count in sorted(file_counts.items(), key=lambda x: -x[1])
        ]
        packages = [
            f"tree-sitter-{lang.replace('_', '-')}" for lang in sorted(unparseable)
        ]

        warning = (
            f"Found {', '.join(parts)} but no grammars installed.\n"
            "  These files will appear in the project map but won't be parsed for\n"
            "  definitions, references, or skeletons.\n\n"
            f"  To enable parsing:\n    pip install {' '.join(packages)}"
        )
        result.setdefault("warnings", []).append(warning)

    # ── Step 2: tree-sitter extraction ───────────────────────
    t0 = time.time()
    extractor = Extractor()
    extractions = {}
    source_files = get_source_files(project_map)
    print(f"  tree-sitter ({len(source_files)} source files)...", end="", flush=True, file=sys.stderr)

    for f in source_files:
        lang = f["language"]
        if lang and extractor.can_parse(lang):
            abs_path = os.path.join(project_root, f["path"])
            extraction = extractor.extract_file(abs_path, lang, f["path"])
            extractions[f["path"]] = extraction

    result["timing"]["treesitter"] = round(time.time() - t0, 3)
    result["extraction_stats"] = {
        "files_parsed": len(extractions),
        # Already computed above (source_files) — recorded here too so
        # Repository Digest's coverage stats have a true denominator
        # (parseable source files) rather than project_map_summary's
        # total_files, which also counts config/doc/asset files no
        # extractor ever attempts to parse.
        "source_files_total": len(source_files),
        "total_definitions": sum(len(e.definitions) for e in extractions.values()),
        "total_references": sum(len(e.references) for e in extractions.values()),
    }
    print(f" ✓ {result['timing']['treesitter']}s ({result['extraction_stats']['total_definitions']} defs)", file=sys.stderr)

    # ── Step 2b: .env key extraction (security: strip values) ─
    env_keys: dict[str, list[str]] = {}
    for f_entry in project_map.get("files", []):
        fpath = f_entry.get("path", "")
        basename = os.path.basename(fpath)
        if basename.startswith(".env") and f_entry.get("category") == "config":
            abs_path = os.path.join(project_root, fpath)
            try:
                with open(abs_path) as fh:
                    env_keys[fpath] = extract_env_keys(fh.read())
            except OSError:
                pass
    if env_keys:
        env_path = os.path.join(context_dir, "env-keys.json")
        write_json(env_path, env_keys)
        result["artifacts"]["env_keys"] = env_path
        result["env_keys_count"] = sum(len(v) for v in env_keys.values())

    # ── Step 3: Codebase Semantic Graph ──────────────────────
    print("  semantic graph...", end="", flush=True, file=sys.stderr)
    t0 = time.time()
    csg = build_csg(project_root, extractions)
    csg_path = save_csg(csg, context_dir)
    result["timing"]["csg"] = round(time.time() - t0, 3)
    result["artifacts"]["csg"] = csg_path
    result["csg_stats"] = {
        "nodes": len(csg["nodes"]),
        "edges": len(csg["edges"]),
        "clusters": len(csg["clusters"]),
    }
    print(f" ✓ {result['timing']['csg']}s ({len(csg['nodes'])} nodes, {len(csg['edges'])} edges)", file=sys.stderr)

    # ── Step 4: File Skeletons ───────────────────────────────
    print("  skeletons...", end="", flush=True, file=sys.stderr)
    t0 = time.time()
    skeleton_stats = build_skeletons(
        project_root, project_map, extractor, context_dir,
        extraction_cache=extractions,
    )
    result["timing"]["skeletons"] = round(time.time() - t0, 3)
    result["artifacts"]["skeletons"] = os.path.join(context_dir, "skeletons")
    result["skeleton_stats"] = skeleton_stats
    print(f" ✓ {result['timing']['skeletons']}s", file=sys.stderr)

    # ── Step 5: Spec-Codebase Alignment (optional) ───────────
    if spec_files:
        print("  spec alignment...", end="", flush=True, file=sys.stderr)
        t0 = time.time()
        alignment = build_spec_alignment(spec_files, project_map, csg)
        align_path = save_spec_alignment(alignment, context_dir)
        result["timing"]["spec_alignment"] = round(time.time() - t0, 3)
        result["artifacts"]["spec_alignment"] = align_path
        result["alignment_summary"] = alignment["summary"]
        print(f" ✓ {result['timing']['spec_alignment']}s", file=sys.stderr)

    # ── Write staleness marker ───────────────────────────────
    write_githead(context_dir, project_root)

    # ── Total timing ─────────────────────────────────────────
    result["timing"]["total"] = round(time.time() - t_start, 3)

    # ── Write build summary ──────────────────────────────────
    summary_path = os.path.join(context_dir, "build-summary.json")
    write_json(summary_path, result)
    result["artifacts"]["build_summary"] = summary_path

    return result


def build_layer1_for_feature(
    project_root: str,
    feature_name: str,
    spec_files: dict[str, str] | None = None,
    fresh: bool = False,
) -> dict:
    """Build Layer 1 for a specific feature.

    Uses feature-scoped context directory but shares codebase-level artifacts
    (project map, CSG) from the main .speed/context/ directory.

    Args:
        project_root: absolute path to project root
        feature_name: feature name (used for directory)
        spec_files: spec files for this feature's spec alignment
        fresh: if True, rebuild even if artifacts aren't stale

    Returns:
        Same as build_layer1.
    """
    feature_context_dir = os.path.join(
        project_root, ".speed", "features", feature_name, "context"
    )
    return build_layer1(
        project_root,
        context_dir=feature_context_dir,
        spec_files=spec_files,
        fresh=fresh,
    )
