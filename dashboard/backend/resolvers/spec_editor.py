"""Resolver functions for the Spec Editor GraphQL API.

Queries: specTree, spec, specAudit, relatedSpecs, specSearch
Mutations: createSpec, updateSpecContent, deleteSpec
"""

from __future__ import annotations

import logging
import os
import json
import sqlite3
from pathlib import Path
from typing import Optional

from ..spec_parser import extract_sections, run_checklist, score_spec_completeness
from ..paths import get_paths
from ..spec_registry import (
    classify_spec_type,
    detect_ghosts,
    match_spec_to_feature,
    rebuild_registry,
    remove_spec,
    update_spec,
)
from .spec_editor_types import (
    AuditCheck,
    AuditResult,
    GhostSpec,
    SpecEntry,
    SpecGroup,
    SpecMutationResult,
    SpecRelation,
    SpecSearchResult,
    SpecSection,
    StructuredSpec,
)

log = logging.getLogger("speed.dashboard.spec_editor")


def _guided_authoring_target(project_root: Path, path: str) -> tuple[str, str] | None:
    """Identify canonical generated artifacts owned by guided authoring."""
    parts = Path(path).parts
    if len(parts) != 3 or parts[0] != "specs":
        return None
    feature, filename = parts[1], parts[2]
    artifact_type = Path(filename).stem
    if artifact_type not in {"prd", "design", "rfc"}:
        return None
    record_path = get_paths(project_root).ceremony_draft(feature, artifact_type)
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return (feature, artifact_type) if isinstance(record.get("authoring"), dict) else None


# ── Queries ──────────────────────────────────────────────────────────────


def get_spec_tree(
    conn: sqlite3.Connection, project_root: Path, feature: Optional[str] = None
) -> list[SpecGroup]:
    """Return specs grouped by feature for the navigator tree."""
    if feature:
        rows = conn.execute(
            """SELECT fs.feature, si.path, si.spec_type, si.feature as si_feature,
                      si.lifecycle_state, si.completeness, si.section_count, si.updated_at
               FROM feature_specs fs
               JOIN spec_index si ON si.path = fs.spec_path
               WHERE fs.feature = ?
               ORDER BY fs.feature, si.spec_type""",
            (feature,),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT fs.feature, si.path, si.spec_type, si.feature as si_feature,
                      si.lifecycle_state, si.completeness, si.section_count, si.updated_at
               FROM feature_specs fs
               JOIN spec_index si ON si.path = fs.spec_path
               ORDER BY fs.feature, si.spec_type"""
        ).fetchall()

    # Group by feature
    groups: dict[str, list[SpecEntry]] = {}
    for r in rows:
        feat = r["feature"]
        if feat not in groups:
            groups[feat] = []
        groups[feat].append(SpecEntry(
            path=r["path"],
            spec_type=r["spec_type"],
            feature=r["si_feature"],
            lifecycle_state=r["lifecycle_state"],
            completeness=r["completeness"],
            section_count=r["section_count"],
            updated_at=r["updated_at"],
        ))

    # Also include unmatched specs
    if not feature:
        unmatched = conn.execute(
            """SELECT path, spec_type, feature, lifecycle_state, completeness,
                      section_count, updated_at
               FROM spec_index
               WHERE path NOT IN (SELECT spec_path FROM feature_specs)
               ORDER BY path"""
        ).fetchall()
        if unmatched:
            groups["_unmatched"] = [
                SpecEntry(
                    path=r["path"],
                    spec_type=r["spec_type"],
                    feature=r["feature"],
                    lifecycle_state=r["lifecycle_state"],
                    completeness=r["completeness"],
                    section_count=r["section_count"],
                    updated_at=r["updated_at"],
                )
                for r in unmatched
            ]

    # Ghost detection
    ghosts = detect_ghosts(conn)
    ghost_map: dict[str, list[str]] = {g.feature: g.missing_types for g in ghosts}

    return [
        SpecGroup(
            feature=feat,
            specs=specs,
            ghosts=ghost_map.get(feat, []),
        )
        for feat, specs in sorted(groups.items())
    ]


def get_spec(
    conn: sqlite3.Connection, project_root: Path, path: str
) -> Optional[StructuredSpec]:
    """Return a single spec as structured sections."""
    full_path = (project_root / path).resolve()
    specs_root = (project_root / "specs").resolve()
    try:
        full_path.relative_to(specs_root)
    except ValueError:
        return None

    row = conn.execute(
        "SELECT * FROM spec_index WHERE path = ?", (path,)
    ).fetchone()
    if not row and full_path.is_file() and full_path.suffix == ".md":
        # A generated draft can be opened before the filesystem watcher has
        # indexed it. Index it synchronously so deep links never land blank.
        update_spec(conn, full_path, project_root)
        row = conn.execute(
            "SELECT * FROM spec_index WHERE path = ?", (path,)
        ).fetchone()
    if not row:
        return None

    if not full_path.exists():
        return None

    parsed = extract_sections(full_path, project_root)
    try:
        content = full_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    return StructuredSpec(
        path=path,
        spec_type=row["spec_type"],
        feature=row["feature"],
        lifecycle_state=row["lifecycle_state"],
        completeness=row["completeness"],
        sections=[
            SpecSection(
                heading=s.heading,
                heading_level=s.heading_level,
                tier=s.tier,
                ordinal=s.ordinal,
                line_start=s.line_start,
                line_end=s.line_end,
            )
            for s in parsed.sections
        ],
        content=content,
        header_lines=parsed.header_lines,
    )


def get_spec_audit(
    conn: sqlite3.Connection, project_root: Path, path: str
) -> Optional[AuditResult]:
    """Run the checklist against a spec and return dimension-level results."""
    row = conn.execute(
        "SELECT spec_type, completeness FROM spec_index WHERE path = ?", (path,)
    ).fetchone()
    if not row:
        return None

    full_path = project_root / path
    if not full_path.exists():
        return None

    parsed = extract_sections(full_path, project_root)
    results = run_checklist(parsed, row["spec_type"], project_root)

    return AuditResult(
        spec_path=path,
        completeness=row["completeness"] or 0.0,
        checks=[
            AuditCheck(
                check_id=r["check_id"],
                description=r["description"],
                dimension=r["dimension"],
                passed=r["passed"],
            )
            for r in results
        ],
    )


def get_related_specs(
    conn: sqlite3.Connection, path: str
) -> list[SpecRelation]:
    """Return all relationships for a given spec (as source or target)."""
    rows = conn.execute(
        """SELECT source_spec, target_spec, rel_type, evidence
           FROM spec_edges
           WHERE source_spec = ? OR target_spec = ?
           ORDER BY rel_type""",
        (path, path),
    ).fetchall()

    return [
        SpecRelation(
            source=r["source_spec"],
            target=r["target_spec"],
            rel_type=r["rel_type"],
            evidence=r["evidence"],
        )
        for r in rows
    ]


def search_specs(
    conn: sqlite3.Connection, project_root: Path, query: str, limit: int = 20
) -> list[SpecSearchResult]:
    """Search specs by path and heading content."""
    # Simple LIKE search (FTS5 can be added later for better performance)
    pattern = f"%{query}%"
    rows = conn.execute(
        """SELECT DISTINCT si.path, si.spec_type, si.feature,
                  ss.heading as snippet
           FROM spec_index si
           LEFT JOIN spec_sections ss ON ss.spec_path = si.path
           WHERE si.path LIKE ? OR ss.heading LIKE ?
           ORDER BY si.path
           LIMIT ?""",
        (pattern, pattern, limit),
    ).fetchall()

    return [
        SpecSearchResult(
            path=r["path"],
            spec_type=r["spec_type"],
            feature=r["feature"],
            snippet=r["snippet"] or r["path"],
        )
        for r in rows
    ]


# ── Mutations ────────────────────────────────────────────────────────────


def create_spec(
    conn: sqlite3.Connection, project_root: Path,
    name: str, spec_type: str, feature: Optional[str] = None,
) -> SpecMutationResult:
    """Create a new spec file from template."""
    type_to_dir = {"prd": "product", "rfc": "tech", "dsn": "design", "defect": "defects"}
    dir_name = type_to_dir.get(spec_type)
    if not dir_name:
        return SpecMutationResult(success=False, path=None, error=f"Unknown spec type: {spec_type}")

    # Sanitize name: strip all path separators and traversal attempts
    safe_name = name.replace("/", "").replace("\\", "").replace("..", "").replace("\x00", "")
    safe_name = safe_name.strip(". ")
    if not safe_name:
        return SpecMutationResult(success=False, path=None, error="Invalid name")

    if not safe_name.endswith(".md"):
        safe_name += ".md"

    spec_path = (project_root / "specs" / dir_name / safe_name).resolve()
    # Verify resolved path is under specs/
    specs_dir = (project_root / "specs").resolve()
    if not str(spec_path).startswith(str(specs_dir)):
        return SpecMutationResult(success=False, path=None, error="Invalid path")

    if spec_path.exists():
        return SpecMutationResult(
            success=False, path=None, error=f"Spec already exists: {spec_path.relative_to(project_root)}"
        )

    # Load template
    template_map = {"prd": "prd.md", "rfc": "rfc.md", "dsn": "spec.md", "defect": "spec.md"}
    template_path = project_root / "templates" / template_map.get(spec_type, "spec.md")
    if template_path.exists():
        content = template_path.read_text(encoding="utf-8")
        # Replace placeholder in title
        title_name = safe_name.replace(".md", "").replace("-", " ").title()
        content = content.replace("{Feature Name}", title_name)
        content = content.replace("{n}", "")
    else:
        title_name = safe_name.replace(".md", "").replace("-", " ").title()
        content = f"# {title_name}\n\n## Problem\n\n"

    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(content, encoding="utf-8")

    # Index the new spec
    update_spec(conn, spec_path, project_root)

    rel_path = str(spec_path.relative_to(project_root))
    log.info("Created spec: %s", rel_path)
    return SpecMutationResult(success=True, path=rel_path, error=None)


def update_spec_content(
    conn: sqlite3.Connection, project_root: Path,
    path: str, content: str,
) -> SpecMutationResult:
    """Write new content to a spec file and re-index."""
    # Resolve and validate path BEFORE any operations
    full_path = (project_root / path).resolve()
    specs_dir = (project_root / "specs").resolve()
    try:
        full_path.relative_to(specs_dir)
    except ValueError:
        return SpecMutationResult(success=False, path=path, error="Path not under specs/")
    if not full_path.exists():
        return SpecMutationResult(success=False, path=path, error="Spec not found")
    guided = _guided_authoring_target(
        project_root, str(full_path.relative_to(project_root.resolve()))
    )
    if guided:
        feature, artifact_type = guided
        return SpecMutationResult(
            success=False,
            path=path,
            error=(
                f"This {artifact_type} is owned by guided authoring. Open "
                f"/define/{feature}/authoring/{artifact_type} to edit it safely."
            ),
        )

    # Write directly (no tmp+replace — atomic replace triggers watcher delete events)
    try:
        full_path.write_text(content, encoding="utf-8")
    except OSError as e:
        return SpecMutationResult(success=False, path=path, error=str(e))

    # Re-index (watcher will also fire but debounce + hash check makes it a no-op)
    update_spec(conn, full_path, project_root)

    return SpecMutationResult(success=True, path=path, error=None)


def delete_spec(
    conn: sqlite3.Connection, project_root: Path, path: str,
) -> SpecMutationResult:
    """Delete a spec file and remove from index."""
    full_path = (project_root / path).resolve()
    specs_dir = (project_root / "specs").resolve()
    if not str(full_path).startswith(str(specs_dir)):
        return SpecMutationResult(success=False, path=path, error="Path not under specs/")

    if not full_path.exists():
        return SpecMutationResult(success=False, path=path, error="Spec not found")

    try:
        full_path.unlink()
    except OSError as e:
        return SpecMutationResult(success=False, path=path, error=str(e))

    remove_spec(conn, full_path, project_root)

    log.info("Deleted spec: %s", path)
    return SpecMutationResult(success=True, path=path, error=None)
