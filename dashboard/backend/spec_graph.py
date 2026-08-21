"""Spec Relationship Graph: explicit + implicit edges between specs.

Explicit edges: parsed from spec header lines (> See, > Depends on, > Parent RFC).
Implicit edges: specs that touch overlapping CSG clusters get a shared_infra edge.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .db import transaction

log = logging.getLogger("speed.dashboard.spec_graph")

# ── Data classes ───────────────────────────────────────────────────────────


@dataclass
class SpecEdge:
    source: str
    target: str
    rel_type: str
    evidence: str | None = None


# ── Header line regexes ───────────────────────────────────────────────────
# Observed patterns from the actual specs:
#   > See [label](path)
#   > Depends on: [label](path), [label](path)
#   > Depends on: text ([label](path)), text
#   > Parent RFC: [label](path)

_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_SEE_RE = re.compile(r"^>\s*See\s+", re.IGNORECASE)
_DEPENDS_RE = re.compile(r"^>\s*Depends on:?\s+", re.IGNORECASE)
_PARENT_RE = re.compile(r"^>\s*Parent RFC:?\s+", re.IGNORECASE)

# File path references in backticks (for implicit coupling)
_CODE_REF_RE = re.compile(
    r"`([^`]+\.(?:py|ts|tsx|js|jsx|sh|rs|go|java|rb|css|html))`"
)


# ── Explicit relationship parser ──────────────────────────────────────────


def parse_explicit_relationships(
    path: Path, project_root: Path
) -> list[SpecEdge]:
    """Extract declared relationships from spec header lines.

    Parses > See, > Depends on, > Parent RFC lines and extracts all
    [label](path) pairs. Resolves relative paths. Only keeps edges
    where the target is a .md file under specs/.
    """
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return []

    rel_source = str(path.relative_to(project_root))
    spec_dir = path.parent
    edges: list[SpecEdge] = []

    for line in content.splitlines():
        if not line.startswith(">"):
            # Header lines are always at the top; once we pass them, stop
            if line.startswith("#"):
                # Allow header lines to appear after the title heading
                continue
            if line.strip() and not line.startswith(">") and not line.startswith("#") and not line.startswith("<!--"):
                # Non-header, non-heading, non-comment line found
                # Keep scanning (blank lines and comments are ok)
                if edges or any(line.startswith(">") for _ in []):
                    pass
                continue
            continue

        # Determine edge type
        if _SEE_RE.match(line):
            rel_type = "see"
        elif _DEPENDS_RE.match(line):
            rel_type = "depends_on"
        elif _PARENT_RE.match(line):
            rel_type = "parent_rfc"
        else:
            continue

        # Extract all [label](path) pairs from the line
        for _label, target_path in _LINK_RE.findall(line):
            resolved = _resolve_spec_path(target_path, spec_dir, project_root)
            if resolved:
                edges.append(SpecEdge(
                    source=rel_source,
                    target=resolved,
                    rel_type=rel_type,
                    evidence=line.strip(),
                ))

    return edges


def _resolve_spec_path(
    target: str, spec_dir: Path, project_root: Path
) -> str | None:
    """Resolve a relative path from a spec header line.

    Returns the path relative to project_root if it's a .md file under specs/.
    Returns None if the target doesn't resolve to a spec.
    """
    if target.startswith(("http://", "https://", "#", "mailto:")):
        return None
    if not target.endswith(".md"):
        return None

    # Resolve relative to the spec file's directory
    resolved = (spec_dir / target).resolve()

    # Must be under project_root/specs/
    specs_dir = (project_root / "specs").resolve()
    try:
        rel = resolved.relative_to(project_root.resolve())
        # Verify it's under specs/
        if not str(rel).startswith("specs"):
            return None
        return str(rel)
    except ValueError:
        return None


# ── Implicit coupling via CSG ──────────────────────────────────────────────


def detect_implicit_coupling(
    conn: sqlite3.Connection, project_root: Path
) -> list[SpecEdge]:
    """Find specs with overlapping CSG cluster coverage.

    For each spec, extract file-path references from its content.
    Map those to CSG clusters. Specs sharing clusters get shared_infra edges.
    """
    import sys
    from .paths import get_paths
    speed_paths = get_paths(project_root)
    csg_path = speed_paths.context_dir / "semantic-graph.json"
    if not csg_path.exists():
        log.info("CSG not available at %s, skipping implicit coupling", csg_path)
        return []

    # Import CSG functions
    lib_path = str(project_root / "lib" / "context")
    if lib_path not in sys.path:
        sys.path.insert(0, str(project_root))

    try:
        from lib.context.csg import load_csg, get_cluster_for_file
    except ImportError:
        log.warning("Could not import CSG functions, skipping implicit coupling")
        return []

    context_dir = str(speed_paths.context_dir)
    try:
        csg = load_csg(context_dir)
    except Exception:
        log.warning("Could not load CSG, skipping implicit coupling")
        return []

    # Build spec → cluster set mapping
    spec_clusters: dict[str, set[str]] = {}

    rows = conn.execute("SELECT path FROM spec_index").fetchall()
    for row in rows:
        spec_path = row["path"]
        full_path = project_root / spec_path
        try:
            content = full_path.read_text(encoding="utf-8")
        except OSError:
            continue

        # Extract code file references
        clusters: set[str] = set()
        for ref in _CODE_REF_RE.findall(content):
            cluster = get_cluster_for_file(csg, ref)
            if cluster and "id" in cluster:
                clusters.add(cluster["id"])

        if clusters:
            spec_clusters[spec_path] = clusters

    # Find overlapping pairs
    edges: list[SpecEdge] = []
    specs = list(spec_clusters.keys())
    for i, spec_a in enumerate(specs):
        for spec_b in specs[i + 1:]:
            shared = spec_clusters[spec_a] & spec_clusters[spec_b]
            if shared:
                edges.append(SpecEdge(
                    source=spec_a,
                    target=spec_b,
                    rel_type="shared_infra",
                    evidence=",".join(sorted(shared)),
                ))

    return edges


# ── Edge store operations ──────────────────────────────────────────────────


def rebuild_edges(
    conn: sqlite3.Connection, project_root: str | Path
) -> int:
    """Full rebuild of spec_edges table.

    Deletes all rows, then:
    1. For each spec in spec_index, run parse_explicit_relationships
    2. Run detect_implicit_coupling for all specs
    3. Insert all edges

    Returns edge count.
    """
    root = Path(project_root).resolve()

    with transaction(conn):
        conn.execute("DELETE FROM spec_edges")

        all_edges: list[SpecEdge] = []

        # Explicit edges
        rows = conn.execute("SELECT path FROM spec_index").fetchall()
        for row in rows:
            spec_path = root / row["path"]
            if spec_path.exists():
                edges = parse_explicit_relationships(spec_path, root)
                all_edges.extend(edges)

        # Implicit edges
        implicit = detect_implicit_coupling(conn, root)
        all_edges.extend(implicit)

        # Insert, skipping edges where target doesn't exist in spec_index
        known_specs = {
            r["path"]
            for r in conn.execute("SELECT path FROM spec_index").fetchall()
        }

        inserted = 0
        for edge in all_edges:
            if edge.target not in known_specs:
                continue
            if edge.source not in known_specs:
                continue
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO spec_edges
                       (source_spec, target_spec, rel_type, evidence)
                       VALUES (?, ?, ?, ?)""",
                    (edge.source, edge.target, edge.rel_type, edge.evidence),
                )
                inserted += 1
            except sqlite3.IntegrityError:
                pass  # Duplicate edge

    log.info("Edges rebuilt: %d edges", inserted)
    return inserted


def update_edges_for_spec(
    conn: sqlite3.Connection, path: Path, project_root: str | Path
) -> None:
    """Incremental update: recompute edges where this spec is source or target."""
    root = Path(project_root).resolve()
    rel_path = str(path.relative_to(root))

    with transaction(conn):
        # Delete existing edges involving this spec
        conn.execute(
            "DELETE FROM spec_edges WHERE source_spec = ? OR target_spec = ?",
            (rel_path, rel_path),
        )

        if not path.exists():
            return

        # Recompute explicit edges for this spec
        edges = parse_explicit_relationships(path, root)

        known_specs = {
            r["path"]
            for r in conn.execute("SELECT path FROM spec_index").fetchall()
        }

        for edge in edges:
            if edge.target not in known_specs or edge.source not in known_specs:
                continue
            conn.execute(
                """INSERT OR IGNORE INTO spec_edges
                   (source_spec, target_spec, rel_type, evidence)
                   VALUES (?, ?, ?, ?)""",
                (edge.source, edge.target, edge.rel_type, edge.evidence),
            )

    log.info("Edges updated for: %s", rel_path)
