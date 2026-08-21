"""Structured spec parser: markdown → typed, addressable sections.

Reads a spec .md file and produces:
  - A list of SpecSection objects (heading, tier, line range, content hash)
  - A mistune AST for downstream consumption
  - YAML frontmatter extraction
  - Section-level and file-level completeness scores
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import mistune

# ── Heading regex (same as define.py's _extract_headings) ──────────────────

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")

# ── Tier mapping ───────────────────────────────────────────────────────────
# From templates/spec-construction.md and templates/prd.md / rfc.md.
# T1 = structural (must exist for spec to function).
# T2 = quality (important but not load-bearing).
# T3 = supplementary.

TIER_MAP: dict[str, str] = {
    # PRD sections
    "Problem": "T1",
    "Users": "T1",
    "User Stories": "T1",
    "Scope": "T1",
    "Success Criteria": "T2",
    "User Flows": "T2",
    "RFC Decomposition": "T2",
    "Dependencies": "T2",
    "Security & Controls": "T2",
    "Risks": "T2",
    "Open Questions": "T2",
    # RFC sections
    "Basic Example": "T1",
    "Interface Contract": "T1",
    "Data Model": "T1",
    "API Surface": "T1",
    "State Machine": "T2",
    "Validation Rules": "T2",
    "Testing": "T2",
    "Acceptance Criteria": "T2",
    "Key Decisions": "T2",
    "Drawbacks": "T3",
    "Search / Query Strategy": "T3",
    "Migration Strategy": "T3",
    "File Impact": "T2",
    "Unresolved Questions": "T2",
    # Design sections
    "Design Intent": "T1",
    "Layout Structure": "T1",
    "Component Inventory": "T1",
    "States": "T1",
    "Data Binding": "T2",
    "Typography": "T2",
    "Spacing": "T2",
    "Color Application": "T2",
    "Elevation & Depth": "T3",
    "Interactions & Motion": "T3",
    "Responsive Behavior": "T2",
    "Accessibility": "T2",
    "Verification Criteria": "T2",
    # Shared
    "Security": "T2",
    "Risks and Coverage": "T2",
    "Test Plan": "T2",
    "Edge Cases": "T2",
    "Out of Scope": "T2",
    # Sub-sections under Scope
    "In Scope": "T1",
    "Out of Scope (and why)": "T2",
}

# ── Completeness checks ───────────────────────────────────────────────────
# Mechanical checks from templates/spec-construction.md Phase 3.
# Each check is a (check_id, description, applicable_types, checker_fn) tuple.
# checker_fn receives (sections, raw_content, spec_type) and returns bool.

_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_TABLE_ROW_RE = re.compile(r"^\|(.+)\|$", re.MULTILINE)
_VAGUE_CRITERIA_RE = re.compile(
    r"\b(appropriate|reasonable|properly|correctly|adequately)\b", re.IGNORECASE
)


def _check_links_resolve(
    sections: list[SpecSection], content: str, spec_type: str, project_root: Path | None,
    spec_dir: Path | None = None,
) -> bool:
    """Check 1: All markdown links to local files resolve."""
    if project_root is None:
        return True
    links = _LINK_RE.findall(content)
    if not links:
        return True
    # Determine the directory to resolve relative links from.
    # Spec links are relative to the spec file's directory.
    base = spec_dir if spec_dir else project_root
    for _label, target in links:
        if target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        resolved = (base / target).resolve()
        if not resolved.exists():
            return False
    return True


def _check_tables_populated(
    sections: list[SpecSection], content: str, spec_type: str, project_root: Path | None
) -> bool:
    """Check 2: Tables have at least one real data row (not just headers/placeholders)."""
    rows = _TABLE_ROW_RE.findall(content)
    if not rows:
        return True  # No tables = nothing to check
    # Filter out separator rows (all dashes/colons/spaces/pipes)
    data_rows = [
        r for r in rows
        if not all(c in "-|: " for c in r)
    ]
    # Check for placeholder content
    for row in data_rows:
        cells = [c.strip() for c in row.split("|") if c.strip()]
        if cells and all(c in ("", "TBD", "...") for c in cells):
            return False
    return True


def _check_criteria_testable(
    sections: list[SpecSection], content: str, spec_type: str, project_root: Path | None
) -> bool:
    """Check 3: Success/acceptance criteria don't use vague language without numbers."""
    criteria_sections = [
        s for s in sections
        if any(
            kw in s.heading.lower()
            for kw in ("success criteria", "acceptance criteria", "verification criteria")
        )
    ]
    if not criteria_sections:
        return True
    for section in criteria_sections:
        if _VAGUE_CRITERIA_RE.search(section.raw_markdown):
            return False
    return True


def _check_scope_complete(
    sections: list[SpecSection], content: str, spec_type: str, project_root: Path | None
) -> bool:
    """Check 4: Out of Scope items have reasons, not just labels."""
    oos_sections = [
        s for s in sections if "out of scope" in s.heading.lower()
    ]
    if not oos_sections:
        return True
    for section in oos_sections:
        lines = section.raw_markdown.strip().splitlines()
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("- ") and len(stripped) < 15:
                return False
    return True


def _check_story_coverage(
    sections: list[SpecSection], content: str, spec_type: str, project_root: Path | None
) -> bool:
    """Check 5: User stories exist and flows map to stories."""
    story_sections = [
        s for s in sections if "user stories" in s.heading.lower()
    ]
    flow_sections = [
        s for s in sections if "user flow" in s.heading.lower()
    ]
    if not story_sections:
        return False  # PRD must have stories
    # Check stories table has content (not just header)
    for s in story_sections:
        rows = _TABLE_ROW_RE.findall(s.raw_markdown)
        data = [r for r in rows if not all(c in "-|: " for c in r)]
        # Exclude the header row
        if len(data) < 2:
            return False
    # If flows exist, check they reference story IDs
    if flow_sections:
        story_ids = set(re.findall(r"\bS\d+\b", content))
        for fs in flow_sections:
            flow_refs = set(re.findall(r"\bS\d+\b", fs.raw_markdown))
            if not flow_refs and story_ids:
                return False  # Flows don't reference any stories
    return True


def _check_problem_defined(
    sections: list[SpecSection], content: str, spec_type: str, project_root: Path | None
) -> bool:
    """Check: Problem section exists and has substantive content."""
    problem_sections = [
        s for s in sections if s.heading.lower() == "problem"
    ]
    if not problem_sections:
        return False
    for s in problem_sections:
        # Strip heading line, count remaining non-empty lines
        body_lines = [
            l for l in s.raw_markdown.splitlines()[1:]
            if l.strip() and not l.startswith("<!--")
        ]
        if len(body_lines) < 1:
            return False
    return True


def _check_users_defined(
    sections: list[SpecSection], content: str, spec_type: str, project_root: Path | None
) -> bool:
    """Check: Users section exists and has content (including child sections)."""
    user_sections = [
        s for s in sections if s.heading.lower() == "users"
    ]
    if not user_sections:
        return False
    for s in user_sections:
        body_lines = [
            l for l in s.raw_markdown.splitlines()[1:]
            if l.strip() and not l.startswith("<!--")
        ]
        if len(body_lines) >= 1:
            return True
    # Check for child sections (h3+ under Users)
    for i, s in enumerate(sections):
        if s.heading.lower() == "users":
            # Look for next sections at deeper level
            for child in sections[i + 1:]:
                if child.heading_level <= s.heading_level:
                    break
                body_lines = [
                    l for l in child.raw_markdown.splitlines()[1:]
                    if l.strip() and not l.startswith("<!--")
                ]
                if len(body_lines) >= 1:
                    return True
    return False


def _check_testing_complete(
    sections: list[SpecSection], content: str, spec_type: str, project_root: Path | None
) -> bool:
    """Check 15: Testing section has at least a test plan or acceptance criteria."""
    test_sections = [
        s for s in sections
        if any(kw in s.heading.lower() for kw in ("testing", "test plan", "acceptance criteria"))
    ]
    if not test_sections:
        return False
    # At least one testing section should have substantive content
    for s in test_sections:
        body_lines = [
            l for l in s.raw_markdown.splitlines()[1:]
            if l.strip() and not l.startswith("<!--")
        ]
        if len(body_lines) >= 1:
            return True
    return False


def _check_security_addressed(
    sections: list[SpecSection], content: str, spec_type: str, project_root: Path | None
) -> bool:
    """Check: Security section exists and has content."""
    sec_sections = [
        s for s in sections
        if any(kw in s.heading.lower() for kw in ("security", "security & controls"))
    ]
    if not sec_sections:
        return False
    for s in sec_sections:
        body_lines = [
            l for l in s.raw_markdown.splitlines()[1:]
            if l.strip() and not l.startswith("<!--")
        ]
        if len(body_lines) >= 1:
            return True
    return False


_HEX_COLOR_RE = re.compile(r"(?<!`)#[0-9a-fA-F]{3,8}(?!`)")
_CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```")


def _check_token_traceability(
    sections: list[SpecSection], content: str, spec_type: str, project_root: Path | None
) -> bool:
    """Check 16: Colors reference tokens, not raw hex codes outside code blocks."""
    # Strip code blocks before checking
    stripped = _CODE_BLOCK_RE.sub("", content)
    # Also strip inline code
    stripped = re.sub(r"`[^`]+`", "", stripped)
    hex_matches = _HEX_COLOR_RE.findall(stripped)
    # Filter out likely non-color hex (issue refs like #123)
    color_hexes = [h for h in hex_matches if len(h) >= 4]  # #fff or longer
    return len(color_hexes) == 0


def _check_state_completeness(
    sections: list[SpecSection], content: str, spec_type: str, project_root: Path | None
) -> bool:
    """Check 17: States section has no empty cells in the states table."""
    state_sections = [
        s for s in sections if s.heading.lower() == "states"
    ]
    if not state_sections:
        return True  # No states section = nothing to check
    for s in state_sections:
        rows = _TABLE_ROW_RE.findall(s.raw_markdown)
        data = [r for r in rows if not all(c in "-|: " for c in r)]
        for row in data[1:]:  # Skip header row
            cells = [c.strip() for c in row.split("|") if c.strip() != ""]
            if any(c == "" for c in cells):
                return False
    return True


# Map of check_id → (description, applicable_types, checker_fn)
CHECKLIST: dict[str, tuple[str, set[str], Any]] = {
    # References dimension
    "links_resolve": (
        "All markdown links resolve",
        {"prd", "rfc", "dsn", "defect"},
        _check_links_resolve,
    ),
    # Structure dimension
    "tables_populated": (
        "Tables have real data rows",
        {"prd", "rfc", "dsn"},
        _check_tables_populated,
    ),
    # Criteria dimension
    "criteria_testable": (
        "Criteria are mechanically testable",
        {"prd", "rfc", "dsn"},
        _check_criteria_testable,
    ),
    # Scope dimension
    "scope_complete": (
        "Scope boundaries have rationale",
        {"prd", "rfc", "dsn"},
        _check_scope_complete,
    ),
    # Stories dimension
    "story_coverage": (
        "User stories exist and flows reference them",
        {"prd"},
        _check_story_coverage,
    ),
    # Problem dimension
    "problem_defined": (
        "Problem section has substantive content",
        {"prd", "rfc"},
        _check_problem_defined,
    ),
    # Users dimension
    "users_defined": (
        "Users section has substantive content",
        {"prd"},
        _check_users_defined,
    ),
    # Security dimension
    "security_addressed": (
        "Security section exists with content",
        {"prd", "rfc"},
        _check_security_addressed,
    ),
    # Testing dimension (Flows in the spec's terminology)
    "testing_complete": (
        "Testing or acceptance criteria section has content",
        {"rfc"},
        _check_testing_complete,
    ),
    # Design-specific
    "token_traceability": (
        "Colors use tokens, not raw hex codes",
        {"dsn"},
        _check_token_traceability,
    ),
    "state_completeness": (
        "States table has no empty cells",
        {"dsn"},
        _check_state_completeness,
    ),
}

# 8 audit dimensions from the spec (Section 4)
DIMENSION_MAP: dict[str, str] = {
    "links_resolve": "References",
    "tables_populated": "Structure",
    "criteria_testable": "Criteria",
    "scope_complete": "Scope",
    "story_coverage": "Stories",
    "problem_defined": "Problem",
    "users_defined": "Users",
    "security_addressed": "Security",
    "testing_complete": "Flows",
    "token_traceability": "Tokens",
    "state_completeness": "States",
}


# ── Data classes ───────────────────────────────────────────────────────────


@dataclass
class SpecSection:
    heading: str
    heading_level: int
    tier: str
    ordinal: int
    line_start: int
    line_end: int
    content_hash: str
    raw_markdown: str
    ast_nodes: list[dict] = field(default_factory=list)


@dataclass
class ParsedSpec:
    path: str
    content_hash: str
    sections: list[SpecSection]
    ast: list[dict]
    frontmatter: dict[str, str]
    header_lines: list[str]


# ── Tier lookup ────────────────────────────────────────────────────────────


def _get_tier(heading: str) -> str:
    """Look up tier for a heading. Tries exact match first, then substring."""
    if heading in TIER_MAP:
        return TIER_MAP[heading]
    # Substring match for headings like "Security & Controls" vs "Security"
    heading_lower = heading.lower()
    for key, tier in TIER_MAP.items():
        if key.lower() in heading_lower:
            return tier
    return "T3"


# ── Frontmatter parsing ───────────────────────────────────────────────────


def _parse_frontmatter(lines: list[str]) -> tuple[dict[str, str], int]:
    """Extract YAML frontmatter from lines. Returns (dict, end_line_index).

    end_line_index is the index of the closing --- line (exclusive).
    Returns ({}, 0) if no frontmatter present.
    """
    if not lines or lines[0].strip() != "---":
        return {}, 0

    fm: dict[str, str] = {}
    for i, line in enumerate(lines[1:], start=1):
        stripped = line.strip()
        if stripped == "---":
            return fm, i + 1
        if ":" in stripped:
            key, _, value = stripped.partition(":")
            value = value.strip().strip("'\"")
            fm[key.strip()] = value
    return {}, 0


# ── Core parser ────────────────────────────────────────────────────────────


def parse_markdown_to_ast(content: str) -> list[dict]:
    """Convert raw markdown to mistune v3 AST (list of token dicts)."""
    md = mistune.create_markdown(renderer="ast")
    return md(content)


def extract_sections(path: Path, project_root: Path) -> ParsedSpec:
    """Parse a spec markdown file into typed, addressable sections.

    Splits on heading boundaries. Each section spans from its heading line
    to the line before the next heading (or EOF). Sections are assigned
    tiers from TIER_MAP.
    """
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return ParsedSpec(
            path=str(path.relative_to(project_root)),
            content_hash="",
            sections=[],
            ast=[],
            frontmatter={},
            header_lines=[],
        )

    rel_path = str(path.relative_to(project_root))
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    lines = content.splitlines()

    # Parse frontmatter
    frontmatter, fm_end = _parse_frontmatter(lines)

    # Extract header lines (lines starting with "> " before first h2+)
    # These appear between the title (h1) and the first content heading.
    header_lines: list[str] = []
    for i, line in enumerate(lines[fm_end:], start=fm_end):
        m = _HEADING_RE.match(line)
        if m and len(m.group(1)) >= 2:
            break
        if line.startswith("> "):
            header_lines.append(line)

    # Find all heading positions
    heading_positions: list[tuple[int, int, str]] = []  # (line_idx, level, text)
    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line)
        if m:
            level = len(m.group(1))
            text = m.group(2).strip()
            # Strip optional attributes like {tier=T1}
            text = re.sub(r"\s*\{[^}]*\}\s*$", "", text)
            heading_positions.append((i, level, text))

    # Build sections
    sections: list[SpecSection] = []
    for idx, (line_idx, level, text) in enumerate(heading_positions):
        # Section ends at the next heading or EOF
        if idx + 1 < len(heading_positions):
            end_idx = heading_positions[idx + 1][0] - 1
        else:
            end_idx = len(lines) - 1

        # Trim trailing blank lines
        while end_idx > line_idx and not lines[end_idx].strip():
            end_idx -= 1

        section_lines = lines[line_idx:end_idx + 1]
        raw_md = "\n".join(section_lines)
        section_hash = hashlib.sha256(raw_md.encode()).hexdigest()

        sections.append(SpecSection(
            heading=text,
            heading_level=level,
            tier=_get_tier(text),
            ordinal=idx,
            line_start=line_idx + 1,  # 1-indexed
            line_end=end_idx + 1,     # 1-indexed, inclusive
            content_hash=section_hash,
            raw_markdown=raw_md,
        ))

    # Parse full AST
    ast = parse_markdown_to_ast(content)

    return ParsedSpec(
        path=rel_path,
        content_hash=content_hash,
        sections=sections,
        ast=ast,
        frontmatter=frontmatter,
        header_lines=header_lines,
    )


def extract_sections_from_content(content: str) -> list[SpecSection]:
    """Extract sections from raw markdown content (no file I/O).

    Convenience function for callers that already have the content string.
    """
    lines = content.splitlines()

    heading_positions: list[tuple[int, int, str]] = []
    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line)
        if m:
            level = len(m.group(1))
            text = m.group(2).strip()
            text = re.sub(r"\s*\{[^}]*\}\s*$", "", text)
            heading_positions.append((i, level, text))

    sections: list[SpecSection] = []
    for idx, (line_idx, level, text) in enumerate(heading_positions):
        if idx + 1 < len(heading_positions):
            end_idx = heading_positions[idx + 1][0] - 1
        else:
            end_idx = len(lines) - 1

        while end_idx > line_idx and not lines[end_idx].strip():
            end_idx -= 1

        section_lines = lines[line_idx:end_idx + 1]
        raw_md = "\n".join(section_lines)
        section_hash = hashlib.sha256(raw_md.encode()).hexdigest()

        sections.append(SpecSection(
            heading=text,
            heading_level=level,
            tier=_get_tier(text),
            ordinal=idx,
            line_start=line_idx + 1,
            line_end=end_idx + 1,
            content_hash=section_hash,
            raw_markdown=raw_md,
        ))

    return sections


# ── Completeness scoring ───────────────────────────────────────────────────


def score_section_completeness(
    section: SpecSection,
    spec_type: str,
    all_sections: list[SpecSection],
    content: str,
    project_root: Path | None = None,
) -> float | None:
    """Grade a section against applicable checklist items.

    Returns 0.0-1.0 or None if no checklist items apply.
    """
    applicable = [
        (cid, desc, fn)
        for cid, (desc, types, fn) in CHECKLIST.items()
        if spec_type in types
    ]
    if not applicable:
        return None

    passed = sum(
        1 for _, _, fn in applicable
        if fn([section], section.raw_markdown, spec_type, project_root)
    )
    return passed / len(applicable) if applicable else None


def score_spec_completeness(
    parsed: ParsedSpec,
    spec_type: str,
    project_root: Path | None = None,
) -> float:
    """Aggregate completeness score for the full spec.

    Runs all applicable checks against the full content.
    Returns 0.0-1.0.
    """
    content = "\n".join(s.raw_markdown for s in parsed.sections)
    # Resolve spec_dir for link checking
    spec_dir = None
    if project_root and parsed.path:
        spec_dir = (Path(project_root) / parsed.path).parent

    applicable = [
        (cid, desc, fn)
        for cid, (desc, types, fn) in CHECKLIST.items()
        if spec_type in types
    ]
    if not applicable:
        return 1.0

    passed = sum(
        1 for _, _, fn in applicable
        if _run_check(fn, parsed.sections, content, spec_type, project_root, spec_dir)
    )
    return passed / len(applicable)


def run_checklist(
    parsed: ParsedSpec,
    spec_type: str,
    project_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Run all applicable checks and return detailed results.

    Returns list of {check_id, description, dimension, passed} dicts.
    Used by the audit resolver in Phase 1.
    """
    content = "\n".join(s.raw_markdown for s in parsed.sections)
    spec_dir = None
    if project_root and parsed.path:
        spec_dir = (Path(project_root) / parsed.path).parent

    results = []
    for cid, (desc, types, fn) in CHECKLIST.items():
        if spec_type not in types:
            continue
        results.append({
            "check_id": cid,
            "description": desc,
            "dimension": DIMENSION_MAP.get(cid, "Other"),
            "passed": _run_check(fn, parsed.sections, content, spec_type, project_root, spec_dir),
        })
    return results


def _run_check(fn: Any, sections: list[SpecSection], content: str,
               spec_type: str, project_root: Path | None, spec_dir: Path | None) -> bool:
    """Run a check function, passing spec_dir to link checks."""
    if fn is _check_links_resolve:
        return fn(sections, content, spec_type, project_root, spec_dir=spec_dir)
    return fn(sections, content, spec_type, project_root)
