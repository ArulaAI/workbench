"""Spec Registry: index, classify, group, and lifecycle-manage spec files.

Provides:
  - Full rebuild from filesystem scan (on init)
  - Incremental update (on file change)
  - Type classification (prd / rfc / dsn / defect)
  - Feature-to-spec grouping (junction table)
  - Ghost detection (missing spec types per feature)
  - Lifecycle state machine (draft → reviewed → approved)
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .db import transaction
from .spec_parser import (
    SpecSection,
    extract_sections,
    score_spec_completeness,
)

log = logging.getLogger("speed.dashboard.spec_registry")

# ── Spec type classification ───────────────────────────────────────────────

# Directory name → spec type
SPEC_DIR_MAP: dict[str, str] = {
    "product": "prd",
    "tech": "rfc",
    "design": "dsn",
    "defects": "defect",
}

# All expected types per feature (defects are separate)
EXPECTED_TYPES = {"prd", "rfc", "dsn"}


@dataclass
class GhostSpec:
    feature: str
    missing_types: list[str]


# ── Type classifier ───────────────────────────────────────────────────────


def classify_spec_type(path: Path, project_root: Path) -> str:
    """Detect spec type from directory path, falling back to content heuristics."""
    try:
        rel = path.relative_to(project_root / "specs")
    except ValueError:
        return _classify_by_content(path)

    parts = rel.parts
    if parts:
        dir_name = parts[0]
        if dir_name in SPEC_DIR_MAP:
            return SPEC_DIR_MAP[dir_name]

    return _classify_by_content(path)


def _classify_by_content(path: Path) -> str:
    """Fallback: classify by section headings in the file."""
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return "prd"

    content_lower = content.lower()
    # RFC indicators
    if "## basic example" in content_lower or "## api surface" in content_lower:
        return "rfc"
    # Design indicators
    if "## design intent" in content_lower or "## layout structure" in content_lower:
        return "dsn"
    # Defect indicators
    if "## severity" in content_lower or "severity: p" in content_lower:
        return "defect"
    return "prd"


# ── Feature matcher ────────────────────────────────────────────────────────


def match_spec_to_feature(
    path: Path, project_root: Path
) -> str | None:
    """Determine which feature a spec belongs to.

    Strategy (first match wins):
    1. YAML frontmatter `feature:` field
    2. Filename matches a feature dir in .speed/features/
    3. Filename stem appears in another spec directory (cross-match)
    4. None for unmatched specs
    """
    # 1. Frontmatter
    fm_feature = _read_frontmatter_feature(path)
    if fm_feature:
        return fm_feature

    # Guided authoring stores one artifact per feature directory, for example
    # specs/due-dates-for-tasks/prd.md. The parent directory is the feature.
    try:
        guided_rel = path.relative_to(project_root / "specs")
    except ValueError:
        guided_rel = None
    if guided_rel and len(guided_rel.parts) == 2 and guided_rel.name in {
        "prd.md", "rfc.md", "design.md",
    }:
        guided_feature = guided_rel.parent.name
        from .paths import get_paths
        known_root = get_paths(project_root).features_dir
        if (known_root / guided_feature).is_dir():
            return guided_feature

    stem = path.stem  # e.g., "speed-defects" or "fix-stale-branch-on-retry"

    # 2. Filename match against known features
    from .paths import get_paths
    paths = get_paths(project_root)
    features_dir = paths.features_dir
    if features_dir.is_dir():
        known_features = {d.name for d in features_dir.iterdir() if d.is_dir()}
        if stem in known_features:
            return stem
        # Try stripping "fix-" prefix for defect fix specs
        if stem.startswith("fix-"):
            base = stem[4:]
            if base in known_features:
                return base

    # 3. Cross-match: if the same stem exists in another spec directory,
    #    use the stem as the feature name. This groups product/tech/design
    #    specs by shared filename even without a .speed/features/ dir.
    specs_dir = project_root / "specs"
    if specs_dir.is_dir():
        spec_dirs = ["product", "tech", "design"]
        try:
            own_dir = path.relative_to(specs_dir).parts[0]
        except (ValueError, IndexError):
            own_dir = None

        for d in spec_dirs:
            if d == own_dir:
                continue
            if (specs_dir / d / f"{stem}.md").exists():
                return stem

    return None


def _read_frontmatter_feature(path: Path) -> str | None:
    """Read the 'feature:' field from YAML frontmatter if present."""
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None

    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return None

    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            break
        if stripped.lower().startswith("feature:"):
            value = stripped.split(":", 1)[1].strip()
            return value.strip("'\"") if value else None
    return None


# ── Registry operations ───────────────────────────────────────────────────


def rebuild_registry(
    conn: sqlite3.Connection, project_root: str | Path
) -> int:
    """Full rebuild: scan specs/ directory, populate spec_index + feature_specs + spec_sections.

    Deletes all existing rows and re-inserts. Used on init.
    Returns count of specs indexed.
    """
    root = Path(project_root).resolve()
    specs_dir = root / "specs"

    if not specs_dir.is_dir():
        log.info("No specs directory at %s", specs_dir)
        return 0

    spec_files = list(specs_dir.rglob("*.md"))
    if not spec_files:
        return 0

    with transaction(conn):
        # Clear existing data
        conn.execute("DELETE FROM spec_sections")
        conn.execute("DELETE FROM feature_specs")
        conn.execute("DELETE FROM spec_edges")  # edges rebuilt separately but clear for FK safety
        conn.execute("DELETE FROM spec_index")

        count = 0
        for spec_path in sorted(spec_files):
            _index_spec(conn, spec_path, root)
            count += 1

    log.info("Registry rebuilt: %d specs indexed", count)
    return count


def update_spec(
    conn: sqlite3.Connection, path: Path, project_root: str | Path
) -> None:
    """Incremental update: re-index a single spec file.

    Compares content_hash to skip no-ops.
    """
    root = Path(project_root).resolve()
    rel_path = str(path.relative_to(root))

    if not path.exists():
        remove_spec(conn, path, root)
        return

    # Check if content changed
    import hashlib
    content = path.read_text(encoding="utf-8")
    new_hash = hashlib.sha256(content.encode()).hexdigest()

    row = conn.execute(
        "SELECT content_hash FROM spec_index WHERE path = ?", (rel_path,)
    ).fetchone()
    if row and row["content_hash"] == new_hash:
        return  # No change

    with transaction(conn):
        # Remove old data for this spec (children before parent for FK safety)
        conn.execute("DELETE FROM spec_edges WHERE source_spec = ? OR target_spec = ?", (rel_path, rel_path))
        conn.execute("DELETE FROM spec_sections WHERE spec_path = ?", (rel_path,))
        conn.execute("DELETE FROM feature_specs WHERE spec_path = ?", (rel_path,))
        conn.execute("DELETE FROM spec_index WHERE path = ?", (rel_path,))

        _index_spec(conn, path, root)

    log.info("Spec updated: %s", rel_path)


def remove_spec(
    conn: sqlite3.Connection, path: Path, project_root: str | Path
) -> None:
    """Remove a deleted spec from all tables."""
    root = Path(project_root).resolve()
    try:
        rel_path = str(path.relative_to(root))
    except ValueError:
        return

    with transaction(conn):
        conn.execute("DELETE FROM spec_sections WHERE spec_path = ?", (rel_path,))
        conn.execute("DELETE FROM feature_specs WHERE spec_path = ?", (rel_path,))
        conn.execute(
            "DELETE FROM spec_edges WHERE source_spec = ? OR target_spec = ?",
            (rel_path, rel_path),
        )
        conn.execute("DELETE FROM spec_index WHERE path = ?", (rel_path,))

    log.info("Spec removed: %s", rel_path)


def _index_spec(
    conn: sqlite3.Connection, spec_path: Path, project_root: Path
) -> None:
    """Index a single spec: parse, classify, score, write to all tables."""
    parsed = extract_sections(spec_path, project_root)
    if not parsed.content_hash:
        return  # Unreadable file

    spec_type = classify_spec_type(spec_path, project_root)
    feature = match_spec_to_feature(spec_path, project_root)
    completeness = score_spec_completeness(parsed, spec_type, project_root)

    # Read lifecycle status from frontmatter (source of truth is the file)
    lifecycle = parsed.frontmatter.get("status", "draft").lower().strip()
    if lifecycle not in ("draft", "ready", "approved", "locked"):
        lifecycle = "draft"

    # Insert into spec_index
    conn.execute(
        """INSERT OR REPLACE INTO spec_index
           (path, spec_type, feature, lifecycle_state, content_hash,
            section_count, completeness, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?,
                   strftime('%Y-%m-%dT%H:%M:%SZ','now'))""",
        (
            parsed.path,
            spec_type,
            feature,
            lifecycle,
            parsed.content_hash,
            len(parsed.sections),
            completeness,
        ),
    )

    # Insert into feature_specs junction
    # Ensure the feature row exists (it may only live in specs/, not .speed/features/)
    if feature:
        # Ensure project row exists for FK
        conn.execute(
            """INSERT OR IGNORE INTO project (id, name, root_path)
               VALUES ('default', 'default', ?)""",
            (str(project_root),),
        )
        conn.execute(
            """INSERT OR IGNORE INTO features (name, project_id, status)
               VALUES (?, 'default', 'idle')""",
            (feature,),
        )
        conn.execute(
            """INSERT OR REPLACE INTO feature_specs (feature, spec_path, spec_type)
               VALUES (?, ?, ?)""",
            (feature, parsed.path, spec_type),
        )

    # Insert sections
    for section in parsed.sections:
        conn.execute(
            """INSERT INTO spec_sections
               (spec_path, heading, heading_level, tier, ordinal,
                line_start, line_end, content_hash, completeness)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                parsed.path,
                section.heading,
                section.heading_level,
                section.tier,
                section.ordinal,
                section.line_start,
                section.line_end,
                section.content_hash,
                None,  # Per-section completeness computed on demand
            ),
        )


# ── Ghost detection ────────────────────────────────────────────────────────


def detect_ghosts(conn: sqlite3.Connection) -> list[GhostSpec]:
    """For each feature with at least one spec, find missing spec types.

    Expected set: {prd, rfc, dsn}. Defects are separate.
    """
    rows = conn.execute(
        """SELECT feature, GROUP_CONCAT(DISTINCT spec_type) AS types
           FROM feature_specs
           WHERE feature IS NOT NULL AND spec_type != 'defect'
           GROUP BY feature"""
    ).fetchall()

    ghosts = []
    for row in rows:
        existing = set(row["types"].split(","))
        missing = sorted(EXPECTED_TYPES - existing)
        if missing:
            ghosts.append(GhostSpec(feature=row["feature"], missing_types=missing))

    return ghosts


# ── Lifecycle ──────────────────────────────────────────────────────────────
# Lifecycle state lives in the spec file's frontmatter (status: draft/ready/approved/locked).
# The spec_index.lifecycle_state column is a cache populated during indexing.
# To transition state, edit the frontmatter and save the file. Git tracks the history.
