"""Repository Digest — Phase 2 additions: coverage stats, entrypoints,
annotated tree, reading path, and read-only team-knowledge exposure.

Kept out of repository_digest.py (already 1,291 lines before this file
existed) to keep each concern independently readable. Every function here
is a pure, deterministic derivation over artifacts the builder already
loads — none of them read a new file type, call an LLM, or write
anything. Team-knowledge loading is read-only by construction: it never
imports from lib/learn (whose functions can write drafts/knowledge back
to disk) and never touches the filesystem itself — callers pass in
already-loaded data.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_ENTRYPOINT_FILE_RE = re.compile(
    r"\b([\w./-]+\.(?:py|js|mjs|cjs|ts|tsx|jsx|go|rb|java|rs))\b"
)

_ENTRYPOINT_PURPOSES = ("run", "develop")


def derive_coverage_stats(build_summary: Any) -> dict[str, Any] | None:
    """Coverage stats sourced entirely from build-summary.json's already-
    computed extraction_stats — the same numbers Layer 1 prints to stderr
    during a real build, just persisted and threaded through. Returns
    None (not a zero-filled/fabricated record) whenever the source data
    isn't shaped the way this function expects, including on an old
    build-summary.json predating the source_files_total field.
    """
    if not isinstance(build_summary, dict):
        return None
    extraction = build_summary.get("extraction_stats")
    if not isinstance(extraction, dict):
        return None

    source_total = extraction.get("source_files_total")
    parsed = extraction.get("files_parsed")
    if not isinstance(source_total, int) or not isinstance(parsed, int):
        return None

    pct = round(parsed / source_total * 100, 1) if source_total > 0 else None
    definitions = extraction.get("total_definitions")
    references = extraction.get("total_references")

    return {
        "source_files_total": source_total,
        "source_files_parsed": parsed,
        "parse_coverage_pct": pct,
        "symbols_extracted": definitions if isinstance(definitions, int) else None,
        "references_extracted": references if isinstance(references, int) else None,
    }


def derive_entrypoints(
    commands: list[dict[str, Any]], project_map: dict[str, Any],
) -> list[dict[str, Any]]:
    """An entrypoint here means exactly one thing: a file that a
    discovered RUN/DEVELOP command's own text names, and that file
    genuinely exists in the project map. No filename-convention guessing
    (no "main.py must be an entrypoint just because it's named that").
    """
    known_files = [f.get("path", "") for f in project_map.get("files") or [] if f.get("path")]
    by_basename: dict[str, list[str]] = {}
    for path in known_files:
        by_basename.setdefault(Path(path).name, []).append(path)
    known_set = set(known_files)

    seen: set[str] = set()
    entrypoints: list[dict[str, Any]] = []
    for cmd in commands:
        purpose = cmd.get("purpose")
        if purpose not in _ENTRYPOINT_PURPOSES:
            continue
        for match in _ENTRYPOINT_FILE_RE.finditer(cmd.get("command", "")):
            candidate = match.group(1)
            resolved = candidate if candidate in known_set else None
            if resolved is None:
                matches = by_basename.get(Path(candidate).name, [])
                if len(matches) == 1:
                    resolved = matches[0]
            if not resolved or resolved in seen:
                continue
            seen.add(resolved)
            entrypoints.append({
                "name": Path(resolved).name,
                "file": resolved,
                "kind": purpose,
            })
    return entrypoints


def derive_annotated_tree(
    project_map: dict[str, Any], csg: dict[str, Any] | None, domains: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Top-level directories from project-map.json's own directory stats,
    each optionally annotated with whichever domain owns the most files
    under it — a presentation-level join of two artifacts the builder
    already has in memory, not a new structural analysis.
    """
    directories = project_map.get("directories") or []
    top_level = [d for d in directories if d.get("path") and "/" not in d["path"]]

    label_by_domain_id = {d["id"]: d.get("label") for d in domains if d.get("id")}
    dir_file_counts: dict[str, dict[str, int]] = {}
    if csg:
        for cluster in csg.get("clusters") or []:
            cid = cluster.get("id")
            label = label_by_domain_id.get(cid)
            if not label:
                continue
            for f in cluster.get("files") or []:
                top = f.split("/", 1)[0]
                bucket = dir_file_counts.setdefault(top, {})
                bucket[label] = bucket.get(label, 0) + 1

    tree: list[dict[str, Any]] = []
    for d in sorted(top_level, key=lambda x: -x.get("file_count", 0)):
        path = d["path"]
        labels = dir_file_counts.get(path)
        dominant_label = max(labels, key=labels.get) if labels else None
        tree.append({
            "path": path,
            "file_count": d.get("file_count", 0),
            "total_lines": d.get("total_lines", 0),
            "dominant_domain_label": dominant_label,
        })
    return tree


def derive_reading_path(
    root: Path,
    identity: dict[str, Any],
    entrypoints: list[dict[str, Any]],
    domains: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Deterministic, explainable ordering — never an LLM call. Priority
    mirrors the same evidence hierarchy already used for repository
    identity (Builder Design > Repository identity): documentation, then
    manifest, then what the repository itself says to run, then its
    highest-ranked domain. Each item carries the reason it was picked so
    the UI never has to assert authority it can't back with evidence.
    """
    path: list[dict[str, Any]] = []
    seen_files: set[str] = set()

    def _add(file: str, reason: str, kind: str) -> None:
        if file in seen_files:
            return
        seen_files.add(file)
        path.append({"file": file, "reason": reason, "kind": kind})

    for ev in identity.get("evidence") or []:
        if ev.get("source") == "documentation" and ev.get("path"):
            _add(ev["path"], "Repository overview — where the project explains its own purpose.", "documentation")
            break

    for manifest_name in ("package.json", "pyproject.toml", "Cargo.toml"):
        if (root / manifest_name).is_file():
            _add(manifest_name, "Declares dependencies and how the project is built and run.", "manifest")
            break

    for ep in entrypoints[:2]:
        _add(ep["file"], f"Discovered {ep['kind']} entrypoint — a command in this repository actually runs this file.", "entrypoint")

    ranked_domains = sorted(domains, key=lambda d: d.get("rank", 999999))
    if ranked_domains:
        top = ranked_domains[0]
        rep_files = top.get("representative_files") or []
        if rep_files:
            _add(
                rep_files[0],
                f"Representative file of {top.get('label', 'the highest-ranked domain')}, the highest-ranked domain by symbol count, file count, and cross-domain connectivity.",
                "domain",
            )

    return path


def load_pending_knowledge(drafts_raw: Any) -> list[dict[str, Any]]:
    """Read-only projection of project-knowledge-drafts.json's own already-
    parsed shape (lib/learn/project_knowledge.py's DraftEntry fields).
    Never calls into lib/learn — that module's functions can write new
    drafts to disk, which this read-only surface must never trigger.
    """
    if isinstance(drafts_raw, dict):
        entries = drafts_raw.get("entries", [])
    elif isinstance(drafts_raw, list):
        entries = drafts_raw
    else:
        entries = []

    result = []
    for e in entries:
        if not isinstance(e, dict) or not e.get("id"):
            continue
        result.append({
            "id": e["id"],
            "knowledge": e.get("knowledge", ""),
            "why_it_matters": e.get("why_it_matters", ""),
            "applies_to": e.get("applies_to") or [],
            "source": e.get("source", ""),
            "draft_reason": e.get("draft_reason", ""),
        })
    return result


def project_knowledge_to_digest_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Same read-only projection for the *approved* project-knowledge.json
    entries the builder already loads into project_knowledge_entries for
    risk/staleness detection — just exposing the fields that already
    exist on that same object instead of computing anything new.
    """
    result = []
    for e in entries:
        if not isinstance(e, dict) or not e.get("id"):
            continue
        result.append({
            "id": e["id"],
            "knowledge": e.get("knowledge", ""),
            "why_it_matters": e.get("why_it_matters", ""),
            "applies_to": e.get("applies_to") or [],
            "last_verified": e.get("last_verified"),
            "staleness_flag": e.get("staleness_flag", ""),
        })
    return result
