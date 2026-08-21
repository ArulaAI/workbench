"""LLM-driven spec draft generation for the Define Ceremony.

Reads intent + context package + SPEED template, asks the LLM to produce a
complete spec, validates against template conformance, and retries with
feedback when required sections are missing.
"""

from __future__ import annotations

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
    _read_json,
    _write_json,
)
from .spec_parser import TIER_MAP, extract_sections_from_content

log = logging.getLogger("speed.dashboard.ceremony.generator")

_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

# ── Template section requirements per spec type ────────────────────────────

# Map spec_type to the T1 section headings that MUST be present.
_REQUIRED_SECTIONS: dict[str, list[str]] = {
    "prd": [h for h, t in TIER_MAP.items() if t == "T1" and h in {
        "Problem", "Users", "User Stories", "Scope", "In Scope",
    }],
    "rfc": [h for h, t in TIER_MAP.items() if t == "T1" and h in {
        "Basic Example", "Interface Contract", "Data Model", "API Surface",
    }],
    "design": [h for h, t in TIER_MAP.items() if t == "T1" and h in {
        "Design Intent", "Layout Structure", "Component Inventory", "States",
    }],
}

# Spec type -> target directory under specs/
_SPEC_DIRS: dict[str, str] = {
    "prd": "specs/product",
    "rfc": "specs/tech",
    "design": "specs/design",
}

MAX_RETRIES = 2  # 3 total attempts


# ── Context serialization ──────────────────────────────────────────────────


def _serialize_context(pkg: ContextPackage) -> str:
    """Compact text representation of the context package for LLM prompts."""
    lines: list[str] = []
    lines.append(f"Feature: {pkg.feature_name}")
    lines.append(f"Intent: {pkg.intent}")

    unique_files = sorted(set(c.path for c in pkg.codebase))
    if unique_files:
        lines.append(f"\nScoped files ({len(unique_files)}):")
        for f in unique_files[:30]:
            lines.append(f"  {f}")
        if len(unique_files) > 30:
            lines.append(f"  ... and {len(unique_files) - 30} more")

    if pkg.defects:
        lines.append(f"\nKnown defects ({len(pkg.defects)}):")
        for d in pkg.defects:
            lines.append(f"  [{d.severity}] {d.name}")

    if pkg.learnings:
        lines.append(f"\nLearnings from past features ({len(pkg.learnings)}):")
        for item in pkg.learnings[:10]:
            lines.append(f"  [{item.confidence}] {item.text[:200]}")
        if len(pkg.learnings) > 10:
            lines.append(f"  ... and {len(pkg.learnings) - 10} more")

    if pkg.related_features:
        lines.append(f"\nRelated features ({len(pkg.related_features)}):")
        for r in pkg.related_features:
            lines.append(f"  {r.name} ({r.state}, {len(r.overlap_files)} shared files)")

    if pkg.audit_history:
        lines.append(f"\nAudit findings ({len(pkg.audit_history)}):")
        for a in pkg.audit_history:
            lines.append(f"  [{a.severity}] {a.finding[:200]}")

    if pkg.vision_content:
        lines.append(f"\nVision ({pkg.vision_status}):")
        lines.append(pkg.vision_content[:1000])

    if pkg.project_knowledge:
        lines.append(f"\nProject conventions ({len(pkg.project_knowledge)}):")
        for k in pkg.project_knowledge[:5]:
            lines.append(f"  {k.text[:150]}")

    return "\n".join(lines)


def _check_required_sections(
    content: str, spec_type: str
) -> list[str]:
    """Return list of missing required section headings."""
    sections = extract_sections_from_content(content)
    present = {s.heading for s in sections}
    required = _REQUIRED_SECTIONS.get(spec_type, [])
    return [h for h in required if h not in present]


# ── Draft generation ───────────────────────────────────────────────────────


def generate_spec_draft(
    intent: str,
    context_package: ContextPackage,
    spec_type: str,
    model: str,
    *,
    prior_specs: Optional[list[SpecDraft]] = None,
    refinement: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
    project_root: Optional[Path] = None,
) -> SpecDraft:
    """Generate a complete spec draft from intent + context + template.

    prior_specs: completed specs that ground this generation (PRD → Design → RFC).
    refinement: optional author guidance for this specific spec type.

    Validates the output against template conformance and retries with
    targeted feedback up to MAX_RETRIES times.
    """
    from .llm import llm_complete_text

    if spec_type not in _SPEC_DIRS:
        raise ValueError(f"Unknown spec_type: {spec_type}. Must be one of: prd, rfc, design")

    root = project_root or Path.cwd()
    template_path = root / "templates" / f"{spec_type}.md"
    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")

    raw_template = template_path.read_text(encoding="utf-8")
    # Strip HTML comments (author instructions, not useful for the LLM)
    template = _HTML_COMMENT_RE.sub("", raw_template).strip()
    # Collapse runs of blank lines left by comment removal
    template = re.sub(r"\n{3,}", "\n\n", template)
    context_text = _serialize_context(context_package)

    # Build prior specs section for chained generation
    prior_section = ""
    if prior_specs:
        parts = []
        for ps in prior_specs:
            label = {"prd": "Product Spec (PRD)", "design": "Design Spec", "rfc": "Technical Spec (RFC)"}.get(ps.spec_type, ps.spec_type)
            parts.append(f"### {label}\n{ps.content}")
        prior_section = "## Prior Specs (already written for this feature)\n" + "\n\n".join(parts)

    type_guidance = {
        "prd": (
            "You are writing a Product Requirements Document (PRD). "
            "Focus on the problem, users, stories, and scope."
        ),
        "design": (
            "You are writing a Design Spec. The PRD for this feature has already been written "
            "and is provided below. Your design must address every user story and flow from the PRD. "
            "Reference PRD story IDs (S1, S2, etc.) in your component inventory and states."
        ),
        "rfc": (
            "You are writing a Technical RFC. The PRD and Design Spec for this feature have "
            "already been written and are provided below. Your RFC must implement every user story "
            "from the PRD and every component from the Design. Reference PRD story IDs and Design "
            "components. Include the Interface Contract, Data Model, and API Surface."
        ),
    }

    system_msg = (
        "You are a specification author for the SPEED framework. "
        "Your job is to produce a complete, high-quality spec document by filling in "
        "every section of the provided template with substantive content grounded in "
        "the assembled context and any prior specs.\n\n"
        f"{type_guidance.get(spec_type, '')}\n\n"
        "Rules:\n"
        "- Fill EVERY section heading from the template. Do not skip any.\n"
        "- Ground your content in the context provided: reference actual files, "
        "defects, learnings, and conventions where relevant.\n"
        "- Use the exact section heading names from the template.\n"
        "- For User Stories tables, assign IDs as S1, S2, S3, etc.\n"
        "- For acceptance criteria, use Given/When/Then format.\n"
        "- Output ONLY the markdown document, no preamble or explanation."
    )

    user_parts = [f"## Intent\n{intent}"]
    if refinement:
        user_parts.append(f"## Author Guidance for This Spec\n{refinement}")
    if prior_section:
        user_parts.append(prior_section)
    user_parts.append(f"## Assembled Context\n{context_text}")
    user_parts.append(f"## Template\n{template}")
    user_parts.append("Generate the complete spec now.")
    user_msg = "\n\n".join(user_parts)

    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]

    best_content = ""
    best_missing_count = float("inf")

    for attempt in range(1 + MAX_RETRIES):
        content = llm_complete_text(
            messages, model, max_tokens=8192, project_root=project_root,
            timeout=900,
        )

        # Strip markdown code fences if the LLM wrapped the output
        if content.startswith("```markdown"):
            content = content[len("```markdown"):].strip()
        if content.startswith("```md"):
            content = content[len("```md"):].strip()
        if content.startswith("```"):
            content = content[3:].strip()
        if content.endswith("```"):
            content = content[:-3].strip()

        # Strip LLM preamble before the first heading
        # e.g. "Here's the complete spec:\n---\n# F8: ..."
        first_heading = re.search(r"^#\s+", content, re.MULTILINE)
        if first_heading and first_heading.start() > 0:
            content = content[first_heading.start():].strip()

        missing = _check_required_sections(content, spec_type)

        if len(missing) < best_missing_count:
            best_content = content
            best_missing_count = len(missing)

        if not missing:
            break

        if attempt < MAX_RETRIES:
            feedback = (
                f"The draft is missing these required sections: {', '.join(missing)}. "
                "Please regenerate the spec with ALL required sections present. "
                "Keep the content you already wrote and add the missing sections."
            )
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": feedback})
            log.info(
                "Draft attempt %d missing %d sections, retrying: %s",
                attempt + 1, len(missing), missing,
            )

    feature_name = context_package.feature_name
    spec_dir = _SPEC_DIRS[spec_type]
    file_path = f"{spec_dir}/{feature_name}.md"
    now = datetime.now(timezone.utc).isoformat()

    draft = SpecDraft(
        feature_name=feature_name,
        spec_type=spec_type,
        content=best_content,
        file_path=file_path,
        template_name=f"{spec_type}.md",
        generated_at=now,
        child_specs=[],
    )

    if project_root:
        save_spec_draft(project_root, feature_name, draft)
        # Write the actual spec file so other tools can see it
        _write_spec_file(project_root, draft)

    return draft


# ── Persistence ────────────────────────────────────────────────────────────


def _draft_to_dict(draft: SpecDraft) -> dict[str, Any]:
    return {
        "feature_name": draft.feature_name,
        "spec_type": draft.spec_type,
        "content": draft.content,
        "file_path": draft.file_path,
        "template_name": draft.template_name,
        "generated_at": draft.generated_at,
        "child_specs": [_draft_to_dict(c) for c in draft.child_specs],
    }


def _dict_to_draft(data: dict[str, Any]) -> SpecDraft:
    return SpecDraft(
        feature_name=data["feature_name"],
        spec_type=data["spec_type"],
        content=data["content"],
        file_path=data["file_path"],
        template_name=data["template_name"],
        generated_at=data.get("generated_at"),
        child_specs=[_dict_to_draft(c) for c in data.get("child_specs", [])],
    )


def save_spec_draft(project_root: Path, feature_name: str, draft: SpecDraft) -> None:
    """Persist a SpecDraft to draft-{type}.json in the ceremony directory."""
    paths = get_paths(project_root)
    draft_path = paths.ceremony_draft(feature_name, draft.spec_type)
    _write_json(draft_path, _draft_to_dict(draft))


def load_spec_draft(
    project_root: Path, feature_name: str, spec_type: str = "prd"
) -> SpecDraft | None:
    """Load a persisted SpecDraft for a specific type. Returns None if not found."""
    paths = get_paths(project_root)
    # Try type-specific file first, fall back to legacy draft.json
    draft_path = paths.ceremony_draft(feature_name, spec_type)
    data = _read_json(draft_path)
    if data is None:
        legacy_path = paths.ceremony_draft(feature_name)
        data = _read_json(legacy_path)
        if data is None:
            return None
        # Only return if the legacy draft matches the requested type
        if data.get("spec_type") != spec_type:
            return None
    return _dict_to_draft(data)


def load_all_spec_drafts(project_root: Path, feature_name: str) -> list[SpecDraft]:
    """Load all persisted drafts for a ceremony.

    Returns core specs (prd, design, rfc) first in generation order,
    then any child RFC drafts (draft-rfc-*.json) sorted alphabetically.
    """
    result = []
    seen_types: set[str] = set()

    # Core specs in generation order
    for st in ["prd", "design", "rfc"]:
        draft = load_spec_draft(project_root, feature_name, st)
        if draft:
            result.append(draft)
            seen_types.add(st)

    # Scan for additional draft files (child RFCs)
    paths = get_paths(project_root)
    ceremony_dir = paths.ceremony_dir(feature_name)
    if ceremony_dir.is_dir():
        for draft_file in sorted(ceremony_dir.glob("draft-*.json")):
            # Extract spec_type from filename: draft-{spec_type}.json
            stem = draft_file.stem  # e.g. "draft-rfc-ingestion"
            spec_type = stem[6:]  # strip "draft-" prefix
            if spec_type in seen_types:
                continue
            data = _read_json(draft_file)
            if data:
                result.append(_dict_to_draft(data))
                seen_types.add(spec_type)

    return result


def _write_spec_file(project_root: Path, draft: SpecDraft) -> None:
    """Write the draft content to its actual spec path (e.g. specs/product/foo.md)."""
    spec_path = project_root / draft.file_path
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(draft.content, encoding="utf-8")
