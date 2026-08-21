"""Proactive Assist Engine: LLM-powered spec analysis and suggestions.

Components:
  - Ambiguity detector: find missing boundary conditions in criteria
  - Fix suggestion generator: produce concrete text edits
  - Spec builder: generate a spec draft from a problem statement
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Optional

from .llm import llm_complete, llm_complete_text
from .llm.models import AmbiguityReport, FixSuggestion, SpecDraft

log = logging.getLogger("speed.dashboard.assist")


# ── Ambiguity Detector ──────────────────────────────────────────────────


def detect_ambiguities(
    spec_content: str,
    spec_type: str,
    model: str,
    conn: Optional[sqlite3.Connection] = None,
    spec_path: Optional[str] = None,
    project_root: Optional[Path] = None,
) -> AmbiguityReport:
    """Analyze acceptance criteria for missing boundary conditions."""
    # Extract criteria sections
    criteria_text = _extract_criteria(spec_content, spec_type)
    if not criteria_text.strip():
        return AmbiguityReport(issues=[], summary="No acceptance criteria found to analyze.")

    messages = [
        {
            "role": "system",
            "content": (
                "You are a spec quality reviewer. Analyze acceptance criteria for "
                "missing boundary conditions, edge cases, and ambiguous language. "
                "Focus on conditions that would cause implementation disagreements. "
                "Only flag real issues, not style preferences. "
                "Severity: critical = would cause bugs in production, "
                "major = would cause rework during review, "
                "minor = could confuse but likely caught during implementation."
            ),
        },
        {
            "role": "user",
            "content": f"Analyze these acceptance criteria for ambiguities:\n\n{criteria_text}",
        },
    ]

    return llm_complete(
        messages=messages,
        response_model=AmbiguityReport,
        model=model,
        conn=conn,
        spec_path=spec_path,
        purpose="ambiguity_detection",
        project_root=project_root,
    )


# ── Fix Suggestion Generator ────────────────────────────────────────────


def suggest_fix(
    section_text: str,
    issue_description: str,
    model: str,
    conn: Optional[sqlite3.Connection] = None,
    spec_path: Optional[str] = None,
    project_root: Optional[Path] = None,
) -> FixSuggestion:
    """Generate a concrete text edit to fix a spec issue."""
    messages = [
        {
            "role": "system",
            "content": (
                "You are a spec editor. Given a section of a spec and a described issue, "
                "produce a concrete text replacement that fixes the issue. "
                "The old_text must be an exact substring of the section text. "
                "The new_text should be the minimal change that resolves the issue. "
                "Keep the same formatting style (markdown). "
                "Severity: critical, major, minor, or style."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Section text:\n```\n{section_text}\n```\n\n"
                f"Issue: {issue_description}\n\n"
                "Generate a fix."
            ),
        },
    ]

    return llm_complete(
        messages=messages,
        response_model=FixSuggestion,
        model=model,
        conn=conn,
        spec_path=spec_path,
        purpose="fix_suggestion",
        project_root=project_root,
    )


# ── Spec Builder ────────────────────────────────────────────────────────


def build_spec_draft(
    problem_statement: str,
    spec_type: str,
    model: str,
    codebase_context: str = "",
    conn: Optional[sqlite3.Connection] = None,
    project_root: Optional[Path] = None,
) -> SpecDraft:
    """Generate a structured spec draft from a problem statement."""
    type_guidance = {
        "prd": (
            "Generate a Product Requirements Document. Focus on: "
            "the user pain (not the solution), affected personas described by their problems, "
            "user stories in Given/When/Then format with testable acceptance criteria, "
            "measurable success criteria with numeric thresholds, "
            "and explicit scope boundaries with reasons for each exclusion."
        ),
        "rfc": (
            "Generate a Technical RFC. Focus on: "
            "a concrete code example showing the feature in use, "
            "data model with types and constraints, "
            "API surface with input/output types and error cases, "
            "and a testing plan derived from risks."
        ),
    }

    guidance = type_guidance.get(spec_type, type_guidance["prd"])

    system = (
        f"You are a spec writer for a software project. {guidance} "
        "Write concretely. Every criterion must be mechanically testable. "
        "No vague language (appropriate, reasonable, properly). "
        "No padding to exactly three items. "
        "If there are two points, write two. If there are five, write five."
    )

    user_content = f"Problem statement:\n{problem_statement}"
    if codebase_context:
        user_content += f"\n\nRelevant codebase context:\n{codebase_context}"

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ]

    return llm_complete(
        messages=messages,
        response_model=SpecDraft,
        model=model,
        conn=conn,
        purpose="spec_builder",
        project_root=project_root,
    )


def render_spec_draft(draft: SpecDraft, spec_type: str, template_path: Optional[Path] = None) -> str:
    """Render a SpecDraft into markdown using the project template."""
    if template_path and template_path.exists():
        template = template_path.read_text(encoding="utf-8")
    else:
        template = None

    lines = [f"# {spec_type.upper()} Draft\n"]

    lines.append("## Problem\n")
    lines.append(f"{draft.problem}\n")

    lines.append("## Users\n")
    for u in draft.users:
        lines.append(f"### {u.name}")
        lines.append(f"{u.problem}\n")

    lines.append("## User Stories\n")
    lines.append("| ID | Story | Acceptance Criteria | Priority |")
    lines.append("|----|-------|---------------------|----------|")
    for s in draft.stories:
        lines.append(f"| {s.id} | {s.story} | {s.acceptance_criteria} | {s.priority} |")
    lines.append("")

    lines.append("## Success Criteria\n")
    for c in draft.success_criteria:
        lines.append(f"- [ ] {c}")
    lines.append("")

    lines.append("## Scope\n")
    lines.append("### In Scope")
    for s in draft.scope_in:
        lines.append(f"- {s}")
    lines.append("")
    lines.append("### Out of Scope (and why)")
    for s in draft.scope_out:
        lines.append(f"- {s}")
    lines.append("")

    return "\n".join(lines)


# ── Helpers ──────────────────────────────────────────────────────────────


def _extract_criteria(content: str, spec_type: str) -> str:
    """Extract acceptance/success criteria sections from spec content."""
    lines = content.splitlines()
    sections: list[str] = []
    capturing = False
    current: list[str] = []

    keywords = ["success criteria", "acceptance criteria", "verification criteria"]

    for line in lines:
        stripped = line.strip().lower()
        is_heading = stripped.startswith("#")

        if is_heading and any(kw in stripped for kw in keywords):
            capturing = True
            current = [line]
            continue

        if capturing:
            if is_heading and not any(kw in stripped for kw in keywords):
                sections.append("\n".join(current))
                capturing = False
                current = []
            else:
                current.append(line)

    if current:
        sections.append("\n".join(current))

    # Also extract user stories table (contains acceptance criteria column)
    capturing = False
    for line in lines:
        stripped = line.strip().lower()
        if stripped.startswith("#") and "user stories" in stripped:
            capturing = True
            current = [line]
            continue
        if capturing:
            if stripped.startswith("#") and "user stories" not in stripped:
                sections.append("\n".join(current))
                capturing = False
                current = []
            else:
                current.append(line)
    if current:
        sections.append("\n".join(current))

    return "\n\n---\n\n".join(sections)
