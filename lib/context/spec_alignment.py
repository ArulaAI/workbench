"""Spec-Codebase Alignment — Layer 1, Artifact 4.

Parses spec markdown for claims (backtick code references, file paths, entity
mentions), matches them against the Project Map and CSG, and outputs
per-claim status (confirmed/missing/divergent) with evidence.

Output: `.speed/features/{feature}/context/spec-alignment.json`

Usage:
    from lib.context.spec_alignment import build_spec_alignment
    alignment = build_spec_alignment(spec_files, project_map, csg)
    # alignment is a dict with "claims" list

Tech spec: tech-spec-context-constructor.md → Artifact 4
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from typing import Any

from .utils import write_json, read_json


# ── Data structures ──────────────────────────────────────────


@dataclass
class Claim:
    """A claim extracted from a spec document."""
    source: dict       # {spec_file, section, line}
    claim_type: str    # file_exists, entity_defined, function_exists (table_exists, relationship_exists kept for matchers)
    claim_text: str    # Human-readable description
    entity: str        # The entity being claimed about
    details: dict = field(default_factory=dict)  # Extra details (columns, type, etc.)

    # Set during matching
    status: str = "missing"     # confirmed, missing, divergent
    evidence: str = ""          # What was found
    divergence: str | None = None  # What differs (when divergent)


# ── Claim extraction from markdown ───────────────────────────


_NOISE_TERMS = frozenset({
    "true", "false", "null", "none", "nil", "undefined",
    "string", "number", "integer", "boolean", "float", "object", "array",
    "yes", "no", "on", "off",
    "TODO", "FIXME", "NOTE", "HACK",
    "---",
})

_LANGUAGE_KEYWORDS = frozenset({
    "class", "function", "def", "return", "import", "from", "if", "else",
    "elif", "for", "while", "try", "except", "finally", "with", "as",
    "yield", "async", "await", "pass", "break", "continue", "raise",
    "lambda", "in", "is", "not", "and", "or", "del", "global", "nonlocal",
    "assert", "type", "var", "let", "const", "export", "default",
    "interface", "enum", "struct", "impl", "fn", "pub", "mod", "use",
    "match", "case",
})


def _is_noise(term: str) -> bool:
    """Phase 2a: Filter terms that aren't code references."""
    if len(term) < 3:
        return True
    if " " in term:
        return True
    if term.startswith("[") or term.startswith("#"):
        return True
    if "*" in term:
        return True
    if "=" in term:
        return True
    if term.lower() in _NOISE_TERMS:
        return True
    if term.lower() in _LANGUAGE_KEYWORDS:
        return True
    if re.match(r"^[\d.+\-]+$", term):
        return True
    if (term.startswith('"') and term.endswith('"')) or \
       (term.startswith("'") and term.endswith("'")):
        return True
    if re.match(r"^#{1,6}$", term):
        return True
    return False


def _looks_like_identifier(term: str) -> bool:
    """Heuristic: does this term look like a code identifier?"""
    if ":" in term:
        return False
    if "_" in term:
        return True
    if term[0].isupper() and any(c.islower() for c in term):
        return True
    if term[0].islower() and any(c.isupper() for c in term):
        return True
    if term.isupper() and len(term) >= 3:
        return True
    return False


def _looks_like_module_name(term: str) -> bool:
    """Guard for stem matching: term must look like a module reference."""
    if "_" in term:
        return True
    if term[0].isupper() and any(c.islower() for c in term):
        return True
    return False


def _extract_backtick_terms(
    spec_text: str, spec_file: str,
) -> list[dict]:
    """Phase 1: Extract inline backtick terms outside fenced code blocks."""
    terms = []
    lines = spec_text.splitlines()
    in_fence = False
    current_section = ""

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.+)", line)
        if heading_match:
            current_section = heading_match.group(2).strip()

        source = {"spec_file": spec_file, "section": current_section, "line": i}

        for match in re.finditer(r"(?<!`)`([^`]+)`(?!`)", line):
            term = match.group(1).strip()
            if term:
                terms.append({"term": term, "source": source})

    return terms


def _classify_term(
    term: str,
    source: dict,
    pm_paths: set[str],
    pm_basenames: dict[str, str],
    pm_stems: dict[str, str],
    csg_by_name: dict[str, list[dict]],
) -> Claim | None:
    """Phase 2b: Classify a backtick term against the codebase."""
    clean = term.rstrip(".,;:!?)")

    # ── 1. File path match ────────────────────────────────
    has_path_sep = "/" in clean
    has_file_ext = bool(re.search(r"\.[a-zA-Z]{1,5}$", clean))

    if has_path_sep or has_file_ext:
        # Exact path match
        if clean in pm_paths:
            return Claim(
                source=source, claim_type="file_exists",
                claim_text=f"File `{clean}` should exist", entity=clean,
            )

        # Basename match
        basename = os.path.basename(clean)
        if basename in pm_basenames:
            return Claim(
                source=source, claim_type="file_exists",
                claim_text=f"File `{clean}` should exist", entity=clean,
            )

        # Path-like (has /) but not found — still a file_exists claim
        if has_path_sep:
            return Claim(
                source=source, claim_type="file_exists",
                claim_text=f"File `{clean}` should exist", entity=clean,
            )

        # Has file extension but no / — falls through to CSG lookup

    # ── 2. CSG symbol match (exact name) ──────────────────
    has_parens = term.endswith(")")
    lookup_name = re.sub(r"\(.*\)$", "", term)

    # Handle dot-separated terms: resolve first segment
    if "." in lookup_name and "/" not in lookup_name:
        lookup_name = lookup_name.split(".")[0]

    if lookup_name in csg_by_name:
        nodes = csg_by_name[lookup_name]
        unique_ids = {n["id"] for n in nodes}
        if len(unique_ids) >= 3:
            return None  # Too ambiguous (G1)

        kinds = {n["kind"] for n in nodes}
        if kinds & {"class", "type"}:
            return Claim(
                source=source, claim_type="entity_defined",
                claim_text=f"Entity `{term}` should be defined",
                entity=lookup_name,
            )
        elif kinds & {"function", "method"}:
            return Claim(
                source=source, claim_type="function_exists",
                claim_text=f"Function `{term}` should exist",
                entity=lookup_name,
            )
        else:
            return Claim(
                source=source, claim_type="entity_defined",
                claim_text=f"Entity `{term}` should be defined",
                entity=lookup_name,
            )

    # ── 3. CSG case-insensitive match ─────────────────────
    lookup_lower = lookup_name.lower()
    for name, nodes in csg_by_name.items():
        if name.lower() == lookup_lower:
            unique_ids = {n["id"] for n in nodes}
            if len(unique_ids) >= 3:
                return None
            kinds = {n["kind"] for n in nodes}
            ct = "entity_defined" if kinds & {"class", "type"} else "function_exists"
            return Claim(
                source=source, claim_type=ct,
                claim_text=f"Entity `{term}` should be defined",
                entity=lookup_name,
            )

    # ── 4. Stem match against PM (extensionless terms only) ──
    if not has_file_ext and not has_path_sep:
        stem_name = re.sub(r"\(.*\)$", "", term)
        if stem_name in pm_stems and _looks_like_module_name(stem_name):
            return Claim(
                source=source, claim_type="file_exists",
                claim_text=f"File `{term}` should exist",
                entity=stem_name,
            )

    # ── 5. Function call syntax ───────────────────────────
    if has_parens:
        return Claim(
            source=source, claim_type="function_exists",
            claim_text=f"Function `{term}` should exist",
            entity=lookup_name,
        )

    # ── 6. Looks like a code identifier? ──────────────────
    if _looks_like_identifier(term):
        return Claim(
            source=source, claim_type="entity_defined",
            claim_text=f"Entity `{term}` should be defined",
            entity=term,
        )

    # ── 7. Discard ────────────────────────────────────────
    return None


def _fallback_extraction(
    spec_text: str,
    spec_file: str,
    pm_paths: set[str],
    pm_basenames: dict[str, str],
    csg_by_name: dict[str, list[dict]],
) -> list[Claim]:
    """Fallback when no backtick terms found: file paths + PascalCase entities."""
    print(f"  [spec-alignment] No backtick terms found in {spec_file}. "
          "Using fallback extraction.", file=sys.stderr)

    claims: list[Claim] = []
    lines = spec_text.splitlines()
    current_section = ""

    for i, line in enumerate(lines, 1):
        heading_match = re.match(r"^(#{1,6})\s+(.+)", line)
        if heading_match:
            current_section = heading_match.group(2).strip()
            continue

        source = {"spec_file": spec_file, "section": current_section, "line": i}

        # File paths with / and extension
        file_refs = re.findall(
            r"(?:^|\s)([a-zA-Z0-9_/.-]+/[a-zA-Z0-9_/.-]+\.[a-zA-Z]{1,5})(?:\s|$|[,;:])",
            line,
        )
        for path in file_refs:
            if not path.startswith("http"):
                claims.append(Claim(
                    source=source, claim_type="file_exists",
                    claim_text=f"File `{path}` should exist", entity=path,
                ))

        # PascalCase entities (no keyword requirement)
        for match in re.finditer(r"\b([A-Z][a-zA-Z]{2,})\b", line):
            entity = match.group(1)
            if entity.lower() not in {"the", "this", "that", "each", "every",
                                       "some", "any", "all", "when", "where",
                                       "how", "what", "with", "from", "into",
                                       "not", "are", "was", "has", "have",
                                       "will", "should", "must", "can"}:
                claims.append(Claim(
                    source=source, claim_type="entity_defined",
                    claim_text=f"Entity `{entity}` should be defined",
                    entity=entity,
                ))

    # Deduplicate
    seen: set[tuple[str, str]] = set()
    unique = []
    for claim in claims:
        key = (claim.claim_type, claim.entity)
        if key not in seen:
            seen.add(key)
            unique.append(claim)

    return unique


def _extract_claims_from_markdown(
    spec_text: str,
    spec_file: str,
    project_map: dict | None = None,
    csg: dict | None = None,
) -> list[Claim]:
    """Extract verifiable claims from spec markdown via backtick terms.

    Phase 1: Extract inline backtick terms (outside fenced code blocks).
    Phase 2: Classify each term against the CSG and project map.
    Fallback: If no backtick terms found, use file path + PascalCase extraction.

    Returns deduplicated list of Claim objects.
    """
    # ── Build lookup indices ──────────────────────────────
    pm_paths: set[str] = set()
    pm_basenames: dict[str, str] = {}   # basename -> full path
    pm_stems: dict[str, str] = {}       # stem (no ext) -> full path
    if project_map:
        for f in project_map.get("files", []):
            path = f["path"]
            pm_paths.add(path)
            basename = os.path.basename(path)
            pm_basenames.setdefault(basename, path)
            stem = os.path.splitext(basename)[0]
            pm_stems.setdefault(stem, path)

    csg_by_name: dict[str, list[dict]] = {}
    if csg:
        for node in csg.get("nodes", []):
            name = node["name"]
            csg_by_name.setdefault(name, []).append(node)

    # ── Phase 1: Extract backtick terms ───────────────────
    terms = _extract_backtick_terms(spec_text, spec_file)

    # ── Fallback: no backtick terms found ─────────────────
    if not terms:
        return _fallback_extraction(spec_text, spec_file, pm_paths,
                                     pm_basenames, csg_by_name)

    # ── Phase 2: Filter and classify ──────────────────────
    claims: list[Claim] = []
    for term_info in terms:
        term = term_info["term"]
        source = term_info["source"]

        # 2a: Filter noise
        if _is_noise(term):
            continue

        # 2b: Classify against codebase
        claim = _classify_term(term, source, pm_paths, pm_basenames,
                               pm_stems, csg_by_name)
        if claim:
            claims.append(claim)

    # ── Deduplicate by (claim_type, entity) ───────────────
    seen: set[tuple[str, str]] = set()
    unique_claims = []
    for claim in claims:
        key = (claim.claim_type, claim.entity)
        if key not in seen:
            seen.add(key)
            unique_claims.append(claim)

    return unique_claims


# ── Matching claims against codebase ─────────────────────────


def _match_claims(
    claims: list[Claim],
    project_map: dict | None,
    csg: dict | None,
) -> list[Claim]:
    """Match extracted claims against the Project Map and CSG.

    Updates each claim's status, evidence, and divergence fields.
    """
    # Build indices for fast lookup
    pm_files: set[str] = set()
    if project_map:
        for f in project_map.get("files", []):
            pm_files.add(f["path"])

    csg_symbols: dict[str, dict] = {}
    csg_by_name: dict[str, list[dict]] = {}
    if csg:
        for node in csg.get("nodes", []):
            csg_symbols[node["id"]] = node
            name = node["name"]
            if name not in csg_by_name:
                csg_by_name[name] = []
            csg_by_name[name].append(node)

    for claim in claims:
        if claim.claim_type == "file_exists":
            _match_file_exists(claim, pm_files)

        elif claim.claim_type == "table_exists":
            if claim.details.get("column"):
                _match_column_exists(claim, csg_by_name)
            else:
                _match_table_exists(claim, csg_by_name)

        elif claim.claim_type == "entity_defined":
            _match_entity_defined(claim, csg_by_name)

        elif claim.claim_type == "function_exists":
            _match_function_exists(claim, csg_by_name)

        elif claim.claim_type == "relationship_exists":
            _match_relationship_exists(claim, csg_by_name)

    return claims


def _match_file_exists(claim: Claim, pm_files: set[str]) -> None:
    """Match a file_exists claim against the project map."""
    entity = claim.entity

    # Direct match
    if entity in pm_files:
        claim.status = "confirmed"
        claim.evidence = f"File exists in project map: {entity}"
        return

    # Partial match (file exists somewhere in the tree)
    basename = os.path.basename(entity)
    matches = [f for f in pm_files if f.endswith(basename) or f.endswith("/" + basename)]
    if matches:
        claim.status = "divergent"
        claim.evidence = f"Found at different path(s): {', '.join(matches[:3])}"
        claim.divergence = f"Spec says '{entity}', found at '{matches[0]}'"
        return

    claim.status = "missing"
    claim.evidence = f"File not found: {entity}"


def _match_table_exists(claim: Claim, csg_by_name: dict[str, list[dict]]) -> None:
    """Match a table_exists claim against the CSG (ORM models)."""
    table_name = claim.entity

    # Search CSG for classes with schema.table_name matching
    for name, nodes in csg_by_name.items():
        for node in nodes:
            schema = node.get("schema")
            if schema and schema.get("table_name") == table_name:
                claim.status = "confirmed"
                cols = [c["name"] for c in schema.get("columns", [])]
                claim.evidence = (
                    f"Table '{table_name}' found in {node['file']}::{node['name']}. "
                    f"Columns: {', '.join(cols)}"
                )
                return

    # Fallback: look for class name matching table name (singular form)
    # e.g., table "users" might be class "User"
    singular = table_name.rstrip("s") if table_name.endswith("s") else table_name
    capitalized = singular.capitalize()
    if capitalized in csg_by_name:
        nodes = csg_by_name[capitalized]
        for node in nodes:
            if node["kind"] == "class":
                claim.status = "divergent"
                claim.evidence = f"Class '{capitalized}' exists but no ORM schema detected"
                claim.divergence = f"Expected table '{table_name}', found class without schema annotation"
                return

    claim.status = "missing"
    claim.evidence = f"No table or model matching '{table_name}' found in CSG"


def _match_column_exists(claim: Claim, csg_by_name: dict[str, list[dict]]) -> None:
    """Match a column claim against CSG ORM schemas."""
    col_name = claim.details.get("column", "")
    col_type = claim.details.get("type", "")

    # Search all ORM models for this column
    for name, nodes in csg_by_name.items():
        for node in nodes:
            schema = node.get("schema")
            if not schema:
                continue
            for col in schema.get("columns", []):
                if col["name"] == col_name:
                    if col_type and col_type.lower() not in col["type"].lower():
                        claim.status = "divergent"
                        claim.evidence = f"Column '{col_name}' found in {node['name']}"
                        claim.divergence = f"Expected type '{col_type}', found '{col['type']}'"
                    else:
                        claim.status = "confirmed"
                        claim.evidence = f"Column '{col_name}' exists in {node['name']} with type {col['type']}"
                    return

    claim.status = "missing"
    claim.evidence = f"Column '{col_name}' not found in any ORM model"


def _match_entity_defined(claim: Claim, csg_by_name: dict[str, list[dict]]) -> None:
    """Match an entity_defined claim against CSG symbols."""
    entity = claim.entity

    if entity in csg_by_name:
        nodes = csg_by_name[entity]
        # Prefer class definitions
        classes = [n for n in nodes if n["kind"] == "class"]
        if classes:
            n = classes[0]
            claim.status = "confirmed"
            claim.evidence = f"Class '{entity}' defined in {n['file']} at line {n['line']}"
            return

        n = nodes[0]
        claim.status = "confirmed"
        claim.evidence = f"Symbol '{entity}' ({n['kind']}) defined in {n['file']} at line {n['line']}"
        return

    # Try case-insensitive match
    entity_lower = entity.lower()
    for name, nodes in csg_by_name.items():
        if name.lower() == entity_lower:
            n = nodes[0]
            claim.status = "divergent"
            claim.evidence = f"Found '{name}' (case differs) in {n['file']}"
            claim.divergence = f"Expected '{entity}', found '{name}'"
            return

    claim.status = "missing"
    claim.evidence = f"Entity '{entity}' not found in CSG"


def _match_function_exists(claim: Claim, csg_by_name: dict[str, list[dict]]) -> None:
    """Match a function_exists claim against CSG symbols."""
    func_name = claim.entity

    # Skip endpoint patterns (GET /path) — can't verify statically
    if func_name.startswith(("GET ", "POST ", "PUT ", "DELETE ", "PATCH ")):
        claim.status = "missing"
        claim.evidence = "Endpoint matching requires runtime analysis"
        return

    if func_name in csg_by_name:
        nodes = csg_by_name[func_name]
        funcs = [n for n in nodes if n["kind"] in ("function", "method")]
        if funcs:
            n = funcs[0]
            claim.status = "confirmed"
            sig = n.get("signature", "")
            claim.evidence = f"Function '{func_name}' defined in {n['file']} at line {n['line']}"
            if sig:
                claim.evidence += f" with signature {sig}"
            return

    claim.status = "missing"
    claim.evidence = f"Function '{func_name}' not found in CSG"


def _match_relationship_exists(claim: Claim, csg_by_name: dict[str, list[dict]]) -> None:
    """Match a relationship_exists claim against CSG ORM schemas."""
    from_entity = claim.details.get("from", "")
    to_entity = claim.details.get("to", "")

    if from_entity in csg_by_name:
        for node in csg_by_name[from_entity]:
            schema = node.get("schema")
            if not schema:
                continue
            for rel in schema.get("relationships", []):
                if rel.get("target_model", "").lower() == to_entity.lower():
                    claim.status = "confirmed"
                    claim.evidence = (
                        f"Relationship {from_entity} → {to_entity} found "
                        f"in {node['file']}::{node['name']}.{rel['name']}"
                    )
                    return

    claim.status = "missing"
    claim.evidence = f"Relationship {from_entity} → {to_entity} not found in ORM schemas"


# ── Builder ──────────────────────────────────────────────────


def build_spec_alignment(
    spec_files: dict[str, str],
    project_map: dict | None = None,
    csg: dict | None = None,
) -> dict:
    """Build spec-codebase alignment by extracting and matching claims.

    Args:
        spec_files: dict of {spec_file_path: spec_content}
        project_map: project-map.json dict (or None)
        csg: semantic-graph.json dict (or None)

    Returns:
        spec-alignment.json dict with claims list and summary
    """
    all_claims: list[Claim] = []

    for spec_file, content in spec_files.items():
        claims = _extract_claims_from_markdown(content, spec_file, project_map, csg)
        all_claims.extend(claims)

    # Match claims against codebase
    _match_claims(all_claims, project_map, csg)

    # Build output
    claims_output = []
    for claim in all_claims:
        claims_output.append({
            "source": claim.source,
            "claim_type": claim.claim_type,
            "claim_text": claim.claim_text,
            "entity": claim.entity,
            "status": claim.status,
            "evidence": claim.evidence,
            "divergence": claim.divergence,
        })

    # Summary
    confirmed = sum(1 for c in all_claims if c.status == "confirmed")
    missing = sum(1 for c in all_claims if c.status == "missing")
    divergent = sum(1 for c in all_claims if c.status == "divergent")

    return {
        "claims": claims_output,
        "summary": {
            "total_claims": len(all_claims),
            "confirmed": confirmed,
            "missing": missing,
            "divergent": divergent,
        },
    }


# ── Persistence ──────────────────────────────────────────────


def save_spec_alignment(alignment: dict, context_dir: str) -> str:
    """Save spec alignment to context directory. Returns path."""
    path = os.path.join(context_dir, "spec-alignment.json")
    write_json(path, alignment)
    return path


def load_spec_alignment(context_dir: str) -> dict:
    """Load spec alignment from context directory."""
    path = os.path.join(context_dir, "spec-alignment.json")
    return read_json(path)


# ── Queries ──────────────────────────────────────────────────


def get_claims_by_status(alignment: dict, status: str) -> list[dict]:
    """Get all claims with a given status (confirmed/missing/divergent)."""
    return [c for c in alignment.get("claims", []) if c["status"] == status]


def get_claims_for_entity(alignment: dict, entity: str) -> list[dict]:
    """Get all claims related to a specific entity."""
    return [c for c in alignment.get("claims", []) if c["entity"] == entity]


def format_alignment_summary(alignment: dict) -> str:
    """Format spec alignment as markdown for prompt injection."""
    summary = alignment.get("summary", {})
    lines = ["### Spec vs. Reality\n"]

    confirmed = get_claims_by_status(alignment, "confirmed")
    missing = get_claims_by_status(alignment, "missing")
    divergent = get_claims_by_status(alignment, "divergent")

    if confirmed:
        lines.append(f"**Confirmed ({len(confirmed)}):**")
        for c in confirmed:
            lines.append(f"- {c['claim_text']}: {c['evidence']}")
        lines.append("")

    if missing:
        lines.append(f"**Missing ({len(missing)}):**")
        for c in missing:
            lines.append(f"- {c['claim_text']}: expected but not found")
        lines.append("")

    if divergent:
        lines.append(f"**Divergent ({len(divergent)}):**")
        for c in divergent:
            lines.append(f"- {c['claim_text']}: {c['divergence']}")
        lines.append("")

    if not (confirmed or missing or divergent):
        lines.append("No verifiable claims extracted from spec.\n")

    return "\n".join(lines)
