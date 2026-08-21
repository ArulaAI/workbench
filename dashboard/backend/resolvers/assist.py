"""Resolvers for the LLM Assist engine.

Queries: availableModels
Mutations: detectAmbiguities, suggestFix, buildSpecDraft
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Optional

from ..llm import get_available_models, get_unconfigured_providers, get_ceremony_models, ensure_llm_tables
from ..assist_engine import (
    detect_ambiguities,
    suggest_fix,
    build_spec_draft,
    render_spec_draft,
)
from .assist_types import (
    LLMModel,
    UnconfiguredProvider,
    AmbiguityIssue,
    AmbiguityReport,
    FixSuggestionResult,
    SpecDraftResult,
)

log = logging.getLogger("speed.dashboard.assist")


def get_models(project_root: Path) -> list[LLMModel]:
    """Return LLM models available to the user."""
    models = get_available_models(project_root)
    return [LLMModel(**m) for m in models]


def get_ceremony_models_resolver(project_root: Path) -> list[LLMModel]:
    """Return ceremony models (config-filtered subset of available)."""
    models = get_ceremony_models(project_root)
    return [LLMModel(**m) for m in models]


def get_missing_providers(project_root: Path) -> list[UnconfiguredProvider]:
    """Return providers that need API keys."""
    return [UnconfiguredProvider(**p) for p in get_unconfigured_providers(project_root)]


def run_ambiguity_detection(
    conn: sqlite3.Connection,
    project_root: Path,
    spec_path: str,
    model: str,
) -> Optional[AmbiguityReport]:
    """Run ambiguity detection on a spec."""
    full_path = project_root / spec_path
    if not full_path.exists():
        return None

    ensure_llm_tables(conn)
    content = full_path.read_text(encoding="utf-8")

    # Determine spec type from path
    spec_type = "prd"
    if "/tech/" in spec_path:
        spec_type = "rfc"
    elif "/design/" in spec_path:
        spec_type = "dsn"

    try:
        result = detect_ambiguities(
            spec_content=content,
            spec_type=spec_type,
            model=model,
            conn=conn,
            spec_path=spec_path,
            project_root=project_root,
        )
    except Exception as e:
        log.error("Ambiguity detection failed: %s", e)
        return AmbiguityReport(
            issues=[],
            summary=f"Analysis failed: {str(e)[:200]}",
        )

    return AmbiguityReport(
        issues=[
            AmbiguityIssue(
                criterion_text=i.criterion_text,
                missing_condition=i.missing_condition,
                severity=i.severity,
                suggested_clause=i.suggested_clause,
            )
            for i in result.issues
        ],
        summary=result.summary,
    )


def run_fix_suggestion(
    conn: sqlite3.Connection,
    project_root: Path,
    spec_path: str,
    section_text: str,
    issue_description: str,
    model: str,
) -> Optional[FixSuggestionResult]:
    """Generate a fix suggestion for a spec issue."""
    ensure_llm_tables(conn)

    try:
        result = suggest_fix(
            section_text=section_text,
            issue_description=issue_description,
            model=model,
            conn=conn,
            spec_path=spec_path,
            project_root=project_root,
        )
    except Exception as e:
        log.error("Fix suggestion failed: %s", e)
        return None

    return FixSuggestionResult(
        section=result.section,
        issue=result.issue,
        old_text=result.old_text,
        new_text=result.new_text,
        rationale=result.rationale,
        severity=result.severity,
    )


def run_spec_builder(
    conn: sqlite3.Connection,
    project_root: Path,
    problem_statement: str,
    spec_type: str,
    model: str,
) -> SpecDraftResult:
    """Generate a spec draft from a problem statement."""
    ensure_llm_tables(conn)

    # Get codebase context if CSG is available
    codebase_context = ""
    csg_path = project_root / ".speed" / "context" / "semantic-graph.json"
    if csg_path.exists():
        import json
        try:
            csg = json.loads(csg_path.read_text(encoding="utf-8"))
            clusters = csg.get("clusters", [])[:5]
            if clusters:
                codebase_context = "Codebase clusters:\n"
                for cl in clusters:
                    files = cl.get("files", [])[:5]
                    codebase_context += f"- {cl.get('id', '')}: {', '.join(files)}\n"
        except Exception:
            pass

    try:
        draft = build_spec_draft(
            problem_statement=problem_statement,
            spec_type=spec_type,
            model=model,
            codebase_context=codebase_context,
            conn=conn,
            project_root=project_root,
        )
        content = render_spec_draft(draft, spec_type)
        section_count = len(draft.stories) + len(draft.users) + 4  # problem, stories, scope, criteria
    except Exception as e:
        log.error("Spec builder failed: %s", e)
        return SpecDraftResult(
            content=f"# Draft Generation Failed\n\nError: {str(e)[:200]}\n",
            section_count=0,
        )

    return SpecDraftResult(content=content, section_count=section_count)
