"""Six-dimension validation pipeline for Define Ceremony spec drafts.

Tier 1 (live, < 100ms, no LLM): template, structure
Tier 2 (on-demand, may call LLM): cross_spec, codebase, sizing, vision
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .paths import get_paths
from .resolvers.ceremony_types import (
    ContextPackage,
    SpecDraft,
    ValidationDimension,
    ValidationIssue,
    ValidationState,
    _read_json,
    _write_json,
)
from .spec_parser import TIER_MAP, extract_sections_from_content, parse_markdown_to_ast

log = logging.getLogger("speed.dashboard.ceremony.validator")

# ── Helpers ────────────────────────────────────────────────────────────────

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
_TABLE_ROW_RE = re.compile(r"^\|(.+)\|$", re.MULTILINE)
_VAGUE_RE = re.compile(
    r"\b(appropriate|reasonable|properly|correctly|adequately)\b", re.IGNORECASE
)
_STORY_ID_RE = re.compile(r"\bS\d+\b")
_GWT_RE = re.compile(r"\b(Given|When|Then)\b", re.IGNORECASE)

# Section headings expected per spec type (T1 = must have, T2 = should have)
_TYPE_SECTIONS: dict[str, dict[str, set[str]]] = {
    "prd": {
        "T1": {"Problem", "Users", "User Stories", "Scope"},
        "T2": {"Success Criteria", "User Flows", "RFC Decomposition", "Dependencies"},
    },
    "rfc": {
        "T1": {"Basic Example", "Interface Contract", "Data Model", "API Surface"},
        "T2": {"Testing", "Key Decisions", "File Impact", "Validation Rules"},
    },
    "design": {
        "T1": {"Design Intent", "Layout Structure", "Component Inventory", "States"},
        "T2": {"Data Binding", "Typography", "Responsive Behavior", "Accessibility"},
    },
}


def _issue_id(dimension: str, message: str) -> str:
    """Deterministic issue ID from dimension + message content."""
    h = hashlib.sha256(f"{dimension}:{message}".encode()).hexdigest()[:8]
    return f"{dimension}-{h}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_code_spans(ast: list[dict]) -> list[str]:
    """Extract inline code span text from a mistune AST."""
    spans: list[str] = []

    def _walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                _walk(item)
        elif isinstance(node, dict):
            if node.get("type") == "codespan":
                raw = node.get("raw") or node.get("text") or ""
                if raw:
                    spans.append(raw)
            for key in ("children", "body", "head"):
                child = node.get(key)
                if child:
                    _walk(child)

    _walk(ast)
    return spans


def _extract_links(ast: list[dict]) -> list[tuple[str, str]]:
    """Extract (label, url) pairs from all links in a mistune AST."""
    links: list[tuple[str, str]] = []

    def _get_text(node: Any) -> str:
        parts: list[str] = []
        if isinstance(node, list):
            for item in node:
                parts.append(_get_text(item))
        elif isinstance(node, dict):
            if node.get("type") in ("text", "codespan"):
                parts.append(node.get("raw") or node.get("text") or "")
            child = node.get("children")
            if child:
                parts.append(_get_text(child))
        return "".join(parts)

    def _walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                _walk(item)
        elif isinstance(node, dict):
            if node.get("type") == "link":
                attrs = node.get("attrs") or {}
                url = attrs.get("url") or attrs.get("href") or node.get("link") or ""
                label = _get_text(node.get("children", []))
                links.append((label, url))
            for key in ("children", "body", "head"):
                child = node.get(key)
                if child:
                    _walk(child)

    _walk(ast)
    return links


def _build_file_index(project_root: Path) -> set[str]:
    """Build a set of relative file paths using git ls-files (respects .gitignore)."""
    import subprocess

    files: set[str] = set()
    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if line:
                    files.add(line)
    except (subprocess.TimeoutExpired, OSError):
        pass
    return files


def _ref_in_index(ref: str, file_index: set[str]) -> bool:
    """Check if ref matches any file path (exact or as a suffix)."""
    if ref in file_index:
        return True
    suffix = "/" + ref
    return any(f.endswith(suffix) for f in file_index)


# ── Tier 1: Template dimension ─────────────────────────────────────────────


def _validate_template(draft: SpecDraft, project_root: Path) -> ValidationDimension:
    """Check required sections are present and tables match template format."""
    issues: list[ValidationIssue] = []
    sections = extract_sections_from_content(draft.content)
    present_headings = {s.heading for s in sections}

    type_sections = _TYPE_SECTIONS.get(draft.spec_type, {})
    t1_required = type_sections.get("T1", set())
    t2_recommended = type_sections.get("T2", set())

    for heading in t1_required:
        if heading not in present_headings:
            issues.append(ValidationIssue(
                id=_issue_id("template", f"missing-{heading}"),
                dimension="template",
                severity="error",
                message=f"Required section missing: {heading}",
                section=None,
                line=None,
                cross_ref_spec=None,
                cross_ref_section=None,
            ))

    for heading in t2_recommended:
        if heading not in present_headings:
            issues.append(ValidationIssue(
                id=_issue_id("template", f"recommended-{heading}"),
                dimension="template",
                severity="warning",
                message=f"Recommended section missing: {heading}",
                section=None,
                line=None,
                cross_ref_spec=None,
                cross_ref_section=None,
            ))

    # Check tables aren't empty placeholders
    for section in sections:
        rows = _TABLE_ROW_RE.findall(section.raw_markdown)
        data_rows = [r for r in rows if not all(c in "-|: " for c in r)]
        # Exclude header row
        if len(data_rows) >= 1:
            content_rows = data_rows[1:]  # skip header
            for row in content_rows:
                cells = [c.strip() for c in row.split("|") if c.strip()]
                if cells and all(c in ("", "TBD", "...") for c in cells):
                    issues.append(ValidationIssue(
                        id=_issue_id("template", f"placeholder-table-{section.heading}"),
                        dimension="template",
                        severity="warning",
                        message=f"Table in '{section.heading}' has placeholder content",
                        section=section.heading,
                        line=section.line_start,
                        cross_ref_spec=None,
                        cross_ref_section=None,
                    ))
                    break

    errors = sum(1 for i in issues if i.severity == "error")
    status = "fail" if errors > 0 else ("warn" if issues else "pass")

    return ValidationDimension(
        name="template",
        status=status,
        issues=issues,
        checked_at=_now_iso(),
        tier=1,
    )


# ── Tier 1: Structure dimension ────────────────────────────────────────────


def _validate_structure(draft: SpecDraft, project_root: Path) -> ValidationDimension:
    """Check structural conventions: Given/When/Then, story IDs, scope subsections."""
    issues: list[ValidationIssue] = []
    sections = extract_sections_from_content(draft.content)
    present_headings = {s.heading for s in sections}

    # Check acceptance criteria use Given/When/Then
    criteria_sections = [
        s for s in sections
        if any(kw in s.heading.lower() for kw in (
            "acceptance criteria", "user stories", "verification criteria",
        ))
    ]
    for section in criteria_sections:
        # Look for Given/When/Then in table cells or bullet points
        if "Given" in section.raw_markdown or "given" in section.raw_markdown:
            continue
        # Only flag if the section has content beyond the heading
        body = "\n".join(section.raw_markdown.splitlines()[1:]).strip()
        if body and not _GWT_RE.search(section.raw_markdown):
            issues.append(ValidationIssue(
                id=_issue_id("structure", f"no-gwt-{section.heading}"),
                dimension="structure",
                severity="warning",
                message=f"'{section.heading}' lacks Given/When/Then acceptance criteria",
                section=section.heading,
                line=section.line_start,
                cross_ref_spec=None,
                cross_ref_section=None,
            ))

    # Check user stories have S-prefixed IDs (PRD only)
    if draft.spec_type == "prd":
        story_sections = [s for s in sections if "user stories" in s.heading.lower()]
        for section in story_sections:
            ids = _STORY_ID_RE.findall(section.raw_markdown)
            rows = _TABLE_ROW_RE.findall(section.raw_markdown)
            data_rows = [r for r in rows if not all(c in "-|: " for c in r)]
            # At least one data row beyond header should have an ID
            if len(data_rows) > 1 and not ids:
                issues.append(ValidationIssue(
                    id=_issue_id("structure", "no-story-ids"),
                    dimension="structure",
                    severity="warning",
                    message="User stories table lacks S-prefixed IDs (S1, S2, ...)",
                    section=section.heading,
                    line=section.line_start,
                    cross_ref_spec=None,
                    cross_ref_section=None,
                ))

    # Check Scope has In Scope / Out of Scope subsections
    if "Scope" in present_headings:
        has_in = "In Scope" in present_headings
        has_out = any("out of scope" in h.lower() for h in present_headings)
        if not has_in:
            issues.append(ValidationIssue(
                id=_issue_id("structure", "missing-in-scope"),
                dimension="structure",
                severity="warning",
                message="Scope section lacks 'In Scope' subsection",
                section="Scope",
                line=None,
                cross_ref_spec=None,
                cross_ref_section=None,
            ))
        if not has_out:
            issues.append(ValidationIssue(
                id=_issue_id("structure", "missing-out-scope"),
                dimension="structure",
                severity="warning",
                message="Scope section lacks 'Out of Scope' subsection",
                section="Scope",
                line=None,
                cross_ref_spec=None,
                cross_ref_section=None,
            ))

    # Check for vague language in criteria sections
    for section in criteria_sections:
        matches = _VAGUE_RE.findall(section.raw_markdown)
        if matches:
            issues.append(ValidationIssue(
                id=_issue_id("structure", f"vague-{section.heading}"),
                dimension="structure",
                severity="info",
                message=f"'{section.heading}' uses vague language: {', '.join(set(matches))}",
                section=section.heading,
                line=section.line_start,
                cross_ref_spec=None,
                cross_ref_section=None,
            ))

    errors = sum(1 for i in issues if i.severity == "error")
    status = "fail" if errors > 0 else ("warn" if issues else "pass")

    return ValidationDimension(
        name="structure",
        status=status,
        issues=issues,
        checked_at=_now_iso(),
        tier=1,
    )


# ── Tier 2: Cross-spec dimension ──────────────────────────────────────────


def _validate_cross_spec(draft: SpecDraft, project_root: Path) -> ValidationDimension:
    """Check contradictions and coverage gaps across companion specs."""
    issues: list[ValidationIssue] = []

    # Parse AST to find companion spec references from all contexts:
    # markdown links, blockquote header links, and backtick paths in tables
    ast = parse_markdown_to_ast(draft.content)

    seen: set[str] = set()
    companion_paths: list[tuple[str, str]] = []  # (label, relative_path)

    # Links anywhere in the document (covers blockquotes, paragraphs, tables)
    for label, url in _extract_links(ast):
        if url.startswith(("http://", "https://", "#", "mailto:")):
            continue
        if len(url) > 200:
            continue
        if url.endswith(".md") and url not in seen:
            seen.add(url)
            companion_paths.append((label, url))

    # Code spans that look like spec file paths (covers backtick-wrapped
    # paths in table cells, e.g. `specs/tech/some-rfc.md`)
    for span in _extract_code_spans(ast):
        if span.endswith(".md") and "/" in span and len(span) < 200:
            if span not in seen:
                seen.add(span)
                companion_paths.append((span, span))

    if not companion_paths:
        return ValidationDimension(
            name="cross_spec",
            status="pass",
            issues=[],
            checked_at=_now_iso(),
            tier=2,
        )

    # Resolve and load companion specs
    specs_dir = project_root / "specs"
    draft_dir = project_root / Path(draft.file_path).parent
    companions: list[tuple[str, str]] = []  # (resolved_path, content)

    for label, rel_path in companion_paths:
        resolved = None
        # Try relative to draft directory
        try:
            candidate = (draft_dir / rel_path).resolve()
            if candidate.exists():
                resolved = candidate
        except (OSError, ValueError):
            pass
        # Try relative to project root
        if not resolved:
            candidate = (project_root / rel_path).resolve()
            if candidate.exists():
                resolved = candidate
        # Try from specs/ root
        if not resolved:
            candidate = (specs_dir / rel_path).resolve()
            if candidate.exists():
                resolved = candidate

        if resolved:
            companions.append((
                str(resolved.relative_to(project_root)),
                resolved.read_text(encoding="utf-8"),
            ))
        else:
            line_num, section = _locate_ref(rel_path, draft.content)
            issues.append(ValidationIssue(
                id=_issue_id("cross_spec", f"missing-{rel_path}"),
                dimension="cross_spec",
                severity="warning",
                message=f"Referenced spec `{rel_path}` not found on disk",
                section=section or "RFC Decomposition",
                line=line_num,
                cross_ref_spec=rel_path,
                cross_ref_section=None,
            ))

    # Check user story coverage (PRD -> RFC mapping)
    draft_story_ids = set(_STORY_ID_RE.findall(draft.content))
    for comp_path, comp_content in companions:
        comp_story_ids = set(_STORY_ID_RE.findall(comp_content))

        # If draft is PRD and companion references stories, check coverage
        if draft.spec_type == "prd" and comp_story_ids:
            unmapped = draft_story_ids - comp_story_ids
            if unmapped:
                issues.append(ValidationIssue(
                    id=_issue_id("cross_spec", f"coverage-gap-{comp_path}"),
                    dimension="cross_spec",
                    severity="warning",
                    message=f"Stories {', '.join(sorted(unmapped))} not referenced in companion spec",
                    section="RFC Decomposition",
                    line=None,
                    cross_ref_spec=comp_path,
                    cross_ref_section="User Stories",
                ))

        # If companion is PRD and draft references stories, check they exist
        if draft.spec_type == "rfc" and draft_story_ids and comp_story_ids:
            phantom = draft_story_ids - comp_story_ids
            if phantom:
                issues.append(ValidationIssue(
                    id=_issue_id("cross_spec", f"phantom-stories-{comp_path}"),
                    dimension="cross_spec",
                    severity="error",
                    message=f"Stories {', '.join(sorted(phantom))} referenced but not found in PRD",
                    section=None,
                    line=None,
                    cross_ref_spec=comp_path,
                    cross_ref_section="User Stories",
                ))

    errors = sum(1 for i in issues if i.severity == "error")
    status = "fail" if errors > 0 else ("warn" if issues else "pass")

    return ValidationDimension(
        name="cross_spec",
        status=status,
        issues=issues,
        checked_at=_now_iso(),
        tier=2,
    )


# ── Tier 2: Codebase dimension ────────────────────────────────────────────


def _locate_ref(ref: str, content: str) -> tuple[int | None, str | None]:
    """Find the 1-based line number and enclosing section heading for a backtick ref."""
    target = f"`{ref}`"
    lines = content.splitlines()
    current_section: str | None = None
    for i, line in enumerate(lines):
        heading_match = _HEADING_RE.match(line)
        if heading_match:
            current_section = heading_match.group(2).strip()
        if target in line:
            return i + 1, current_section
    return None, None


def _validate_codebase(draft: SpecDraft, project_root: Path) -> ValidationDimension:
    """Check backtick references against the codebase (semantic graph + git files)."""
    issues: list[ValidationIssue] = []

    # Extract code spans from AST (not regex — avoids capturing garbage
    # between unrelated backtick pairs)
    ast = parse_markdown_to_ast(draft.content)
    code_spans = _extract_code_spans(ast)

    # Filter to references that look like file paths or dotted code symbols
    path_refs = [
        r for r in code_spans
        if len(r) < 200 and ("/" in r or "." in r)
    ]

    if not path_refs:
        return ValidationDimension(
            name="codebase",
            status="pass",
            issues=[],
            checked_at=_now_iso(),
            tier=2,
        )

    # Load semantic graph node file paths
    graph_path = project_root / ".speed" / "context" / "semantic-graph.json"
    graph_files: set[str] = set()
    if graph_path.exists():
        try:
            graph_data = json.loads(graph_path.read_text(encoding="utf-8"))
            for node in graph_data.get("nodes", []):
                f = node.get("file", "")
                if f:
                    graph_files.add(f)
        except (json.JSONDecodeError, OSError):
            pass

    # Build file index from git-tracked files (respects .gitignore)
    file_index = _build_file_index(project_root)

    for ref in set(path_refs):
        # Check semantic graph (exact match or suffix match)
        in_graph = (
            ref in graph_files
            or any(f.endswith("/" + ref) or f == ref for f in graph_files)
        )
        # Check file index (exact match or suffix match)
        in_files = _ref_in_index(ref, file_index)

        if not in_graph and not in_files:
            line_num, section = _locate_ref(ref, draft.content)
            issues.append(ValidationIssue(
                id=_issue_id("codebase", f"ref-{ref}"),
                dimension="codebase",
                severity="info",
                message=f"Reference `{ref}` not found in codebase",
                section=section,
                line=line_num,
                cross_ref_spec=None,
                cross_ref_section=None,
            ))

    errors = sum(1 for i in issues if i.severity == "error")
    warnings = sum(1 for i in issues if i.severity == "warning")
    status = "fail" if errors > 0 else ("warn" if warnings > 0 else "pass")

    return ValidationDimension(
        name="codebase",
        status=status,
        issues=issues,
        checked_at=_now_iso(),
        tier=2,
    )


# ── Tier 2: Sizing dimension ──────────────────────────────────────────────


def _validate_sizing(draft: SpecDraft, project_root: Path) -> ValidationDimension:
    """Spec-type-aware sizing check.

    PRD:    Checks that RFC Decomposition exists and maps all user stories.
    RFC:    Estimates task count from endpoints + models. Flags if too large.
    Design: No sizing check (designs don't generate tasks).
    """
    issues: list[ValidationIssue] = []
    sections = extract_sections_from_content(draft.content)

    # ── Design: skip entirely ─────────────────────────────────────
    if draft.spec_type == "design":
        return ValidationDimension(
            name="sizing", status="pass", issues=[],
            checked_at=_now_iso(), tier=2,
        )

    # Collect story IDs from User Stories section
    all_story_ids: set[str] = set()
    for section in sections:
        if "user stories" in section.heading.lower():
            all_story_ids.update(_STORY_ID_RE.findall(section.raw_markdown))

    # ── PRD: check decomposition coverage ─────────────────────────
    if draft.spec_type == "prd":
        decomp_sections = [
            s for s in sections
            if "rfc decomposition" in s.heading.lower()
        ]

        if not decomp_sections and len(all_story_ids) > 3:
            line_num, section = _locate_ref("RFC Decomposition", draft.content)
            issues.append(ValidationIssue(
                id=_issue_id("sizing", "no-decomposition"),
                dimension="sizing",
                severity="warning",
                message=f"{len(all_story_ids)} user stories with no RFC Decomposition "
                        "section. Consider breaking the implementation into child RFCs.",
                section="User Stories",
                line=line_num,
                cross_ref_spec=None,
                cross_ref_section=None,
            ))
        elif decomp_sections and all_story_ids:
            # Check which stories are mapped in the decomposition table
            decomp_content = "\n".join(s.raw_markdown for s in decomp_sections)
            mapped_ids = set(_STORY_ID_RE.findall(decomp_content))
            unmapped = all_story_ids - mapped_ids

            if unmapped:
                line_num = decomp_sections[0].line_start
                issues.append(ValidationIssue(
                    id=_issue_id("sizing", f"unmapped-stories-{','.join(sorted(unmapped))}"),
                    dimension="sizing",
                    severity="warning",
                    message=f"Stories {', '.join(sorted(unmapped))} not mapped in RFC Decomposition.",
                    section="RFC Decomposition",
                    line=line_num,
                    cross_ref_spec=None,
                    cross_ref_section="User Stories",
                ))

            # Check child RFC paths exist (advisory)
            ast = parse_markdown_to_ast(decomp_content)
            child_paths = [
                span for span in _extract_code_spans(ast)
                if span.endswith(".md") and "/" in span
            ]
            for path in child_paths:
                candidate = project_root / path
                if not candidate.exists():
                    line_num_ref, _ = _locate_ref(path, draft.content)
                    issues.append(ValidationIssue(
                        id=_issue_id("sizing", f"child-rfc-missing-{path}"),
                        dimension="sizing",
                        severity="info",
                        message=f"Child RFC `{path}` not yet written.",
                        section="RFC Decomposition",
                        line=line_num_ref,
                        cross_ref_spec=path,
                        cross_ref_section=None,
                    ))

        errors = sum(1 for i in issues if i.severity == "error")
        status = "fail" if errors > 0 else ("warn" if issues else "pass")
        return ValidationDimension(
            name="sizing", status=status, issues=issues,
            checked_at=_now_iso(), tier=2,
        )

    # ── RFC: task estimation heuristic ────────────────────────────
    story_count = len(all_story_ids)

    # Extract full content blocks (heading + all children until next same-level heading)
    # because sections split at every heading level, missing child content
    def _full_block(heading_prefix: str) -> str:
        lines = draft.content.splitlines()
        capturing = False
        block: list[str] = []
        trigger_level = 0
        for line in lines:
            m = _HEADING_RE.match(line)
            if m:
                level = len(m.group(1))
                title = m.group(2).strip().lower()
                if heading_prefix in title and not capturing:
                    capturing = True
                    trigger_level = level
                    continue
                elif capturing and level <= trigger_level:
                    break
            if capturing:
                block.append(line)
        return "\n".join(block)

    api_block = _full_block("api surface")
    endpoint_count = len(re.findall(
        r"(?:mutation|query|GET|POST|PUT|DELETE|PATCH)\b",
        api_block, re.IGNORECASE,
    ))

    model_block = _full_block("data model")
    tables = _TABLE_ROW_RE.findall(model_block)
    separator_rows = [r for r in tables if all(c in "-|: " for c in r)]
    model_count = len(separator_rows)

    estimated_tasks = story_count * 2 + endpoint_count + model_count

    if estimated_tasks > 15:
        issues.append(ValidationIssue(
            id=_issue_id("sizing", "decompose-error"),
            dimension="sizing",
            severity="error",
            message=f"Estimated {estimated_tasks} tasks ({story_count} stories, "
                    f"{endpoint_count} endpoints, {model_count} models). "
                    "Strongly recommend decomposing into child RFCs.",
            section=None,
            line=None,
            cross_ref_spec=None,
            cross_ref_section=None,
        ))
    elif estimated_tasks > 10:
        issues.append(ValidationIssue(
            id=_issue_id("sizing", "decompose-warning"),
            dimension="sizing",
            severity="warning",
            message=f"Estimated {estimated_tasks} tasks ({story_count} stories, "
                    f"{endpoint_count} endpoints, {model_count} models). "
                    "Consider decomposing into child RFCs.",
            section=None,
            line=None,
            cross_ref_spec=None,
            cross_ref_section=None,
        ))

    errors = sum(1 for i in issues if i.severity == "error")
    status = "fail" if errors > 0 else ("warn" if issues else "pass")

    return ValidationDimension(
        name="sizing",
        status=status,
        issues=issues,
        checked_at=_now_iso(),
        tier=2,
    )


# ── Tier 2: Vision dimension ──────────────────────────────────────────────


def _validate_vision(
    draft: SpecDraft,
    project_root: Path,
    *,
    model: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> ValidationDimension:
    """Check alignment with product vision."""
    issues: list[ValidationIssue] = []

    # Load context package for vision info
    paths = get_paths(project_root)
    pkg_data = _read_json(paths.ceremony_context_package(draft.feature_name))
    vision_status = "missing"
    vision_content = None

    if pkg_data:
        vision_status = pkg_data.get("vision_status", "missing")
        vision_content = pkg_data.get("vision_content")

    if vision_status in ("missing", "stale"):
        issues.append(ValidationIssue(
            id=_issue_id("vision", f"vision-{vision_status}"),
            dimension="vision",
            severity="warning",
            message=f"Vision is {vision_status}. Cannot verify alignment.",
            section=None,
            line=None,
            cross_ref_spec=None,
            cross_ref_section=None,
        ))
        return ValidationDimension(
            name="vision",
            status="warn",
            issues=issues,
            checked_at=_now_iso(),
            tier=2,
        )

    # Vision is available -- check alignment via LLM if model provided
    if model and vision_content:
        try:
            from .llm import llm_complete
            from pydantic import BaseModel, Field

            class VisionAlignment(BaseModel):
                aligned: bool = Field(description="Whether the spec aligns with the vision")
                concerns: list[str] = Field(
                    default_factory=list,
                    description="Specific concerns about vision alignment, if any",
                )

            result = llm_complete(
                messages=[
                    {"role": "system", "content": (
                        "You are a product guardian. Compare the spec draft against the "
                        "product vision and identify any misalignment or contradictions. "
                        "Be specific about what conflicts."
                    )},
                    {"role": "user", "content": (
                        f"## Product Vision\n{vision_content}\n\n"
                        f"## Spec Draft\n{draft.content[:4000]}\n\n"
                        "Is this spec aligned with the vision?"
                    )},
                ],
                response_model=VisionAlignment,
                model=model,
                project_root=project_root,
                conn=conn,
                purpose="vision-alignment",
            )

            if not result.aligned:
                for concern in result.concerns:
                    issues.append(ValidationIssue(
                        id=_issue_id("vision", concern[:50]),
                        dimension="vision",
                        severity="warning",
                        message=concern,
                        section=None,
                        line=None,
                        cross_ref_spec=None,
                        cross_ref_section=None,
                    ))
        except Exception as exc:
            log.warning("Vision alignment check failed: %s", exc)
            issues.append(ValidationIssue(
                id=_issue_id("vision", "check-failed"),
                dimension="vision",
                severity="info",
                message=f"Vision alignment check failed: {exc}",
                section=None,
                line=None,
                cross_ref_spec=None,
                cross_ref_section=None,
            ))

    errors = sum(1 for i in issues if i.severity == "error")
    status = "fail" if errors > 0 else ("warn" if issues else "pass")

    return ValidationDimension(
        name="vision",
        status=status,
        issues=issues,
        checked_at=_now_iso(),
        tier=2,
    )


# ── Top-level validation ──────────────────────────────────────────────────

_TIER_1_RUNNERS = [_validate_template, _validate_structure]
_TIER_2_RUNNERS = [_validate_cross_spec, _validate_codebase, _validate_sizing]
# Vision is separate because it needs extra kwargs


def validate_spec(
    draft: SpecDraft,
    project_root: Path,
    *,
    tiers: list[int] | None = None,
    model: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> ValidationState:
    """Run validation dimensions against the draft.

    Args:
        tiers: [1], [2], or [1, 2]. None means all tiers.
        model: LLM model for Tier 2 vision check. If None, vision returns a
               standing warning.
        conn: SQLite connection for LLM caching.
    """
    run_tiers = set(tiers or [1, 2])
    dimensions: list[ValidationDimension] = []

    if 1 in run_tiers:
        for runner in _TIER_1_RUNNERS:
            dimensions.append(runner(draft, project_root))

    if 2 in run_tiers:
        for runner in _TIER_2_RUNNERS:
            dimensions.append(runner(draft, project_root))
        dimensions.append(_validate_vision(
            draft, project_root, model=model, conn=conn,
        ))

    pass_count = sum(1 for d in dimensions if d.status == "pass")
    warn_count = sum(1 for d in dimensions if d.status == "warn")
    fail_count = sum(1 for d in dimensions if d.status == "fail")

    state = ValidationState(
        dimensions=dimensions,
        pass_count=pass_count,
        warn_count=warn_count,
        fail_count=fail_count,
    )

    return state


# ── Persistence ────────────────────────────────────────────────────────────


def _dimension_to_dict(dim: ValidationDimension) -> dict[str, Any]:
    return {
        "name": dim.name,
        "status": dim.status,
        "issues": [
            {
                "id": i.id,
                "dimension": i.dimension,
                "severity": i.severity,
                "message": i.message,
                "section": i.section,
                "line": i.line,
                "cross_ref_spec": i.cross_ref_spec,
                "cross_ref_section": i.cross_ref_section,
            }
            for i in dim.issues
        ],
        "checked_at": dim.checked_at,
        "tier": dim.tier,
    }


def _dict_to_dimension(data: dict[str, Any]) -> ValidationDimension:
    return ValidationDimension(
        name=data["name"],
        status=data["status"],
        issues=[
            ValidationIssue(
                id=i["id"],
                dimension=i["dimension"],
                severity=i["severity"],
                message=i["message"],
                section=i.get("section"),
                line=i.get("line"),
                cross_ref_spec=i.get("cross_ref_spec"),
                cross_ref_section=i.get("cross_ref_section"),
            )
            for i in data.get("issues", [])
        ],
        checked_at=data.get("checked_at"),
        tier=data.get("tier", 1),
    )


def save_validation_state(
    project_root: Path, feature_name: str, state: ValidationState,
    spec_type: str = "prd",
) -> None:
    """Persist validation state per spec type."""
    paths = get_paths(project_root)
    _write_json(paths.ceremony_validation_state(feature_name, spec_type), {
        "dimensions": [_dimension_to_dict(d) for d in state.dimensions],
        "pass_count": state.pass_count,
        "warn_count": state.warn_count,
        "fail_count": state.fail_count,
    })


def load_validation_state(
    project_root: Path, feature_name: str, spec_type: str = "prd",
) -> ValidationState | None:
    """Load persisted validation state for a spec type. Returns None if not found."""
    paths = get_paths(project_root)
    data = _read_json(paths.ceremony_validation_state(feature_name, spec_type))
    if data is None:
        return None
    return ValidationState(
        dimensions=[_dict_to_dimension(d) for d in data.get("dimensions", [])],
        pass_count=data.get("pass_count", 0),
        warn_count=data.get("warn_count", 0),
        fail_count=data.get("fail_count", 0),
    )
