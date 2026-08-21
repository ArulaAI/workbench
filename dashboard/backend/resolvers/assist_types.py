"""Strawberry GraphQL types for the Assist engine."""

from __future__ import annotations

from typing import Optional

import strawberry


@strawberry.type
class LLMModel:
    id: str
    provider: str
    label: str


@strawberry.type
class UnconfiguredProvider:
    provider: str
    label: str
    env_var: str


@strawberry.type
class AmbiguityIssue:
    criterion_text: str
    missing_condition: str
    severity: str
    suggested_clause: str


@strawberry.type
class AmbiguityReport:
    issues: list[AmbiguityIssue]
    summary: str


@strawberry.type
class FixSuggestionResult:
    section: str
    issue: str
    old_text: str
    new_text: str
    rationale: str
    severity: str


@strawberry.type
class SpecDraftResult:
    content: str
    section_count: int


@strawberry.type
class AuditRunStatus:
    """Return type for the runAudit mutation — just success/error."""
    success: bool
    error: Optional[str]


@strawberry.type
class AuditStatus:
    """Whether an audit subprocess is currently running for a spec."""
    running: bool
    started_at: str


# ── SPEED-native audit types (read from disk, not normalized) ────


@strawberry.type
class AuditIssue:
    level: int
    severity: str
    section: str
    message: str


@strawberry.type
class AuditLinkedSpecs:
    prd: Optional[str]
    design: Optional[str]
    parent_rfc: Optional[str]
    child_rfcs: list[str]


@strawberry.type
class AuditSuggestedChild:
    name: str
    sections: list[int]
    depends_on: list[str]
    testable_output: str


@strawberry.type
class AuditSizing:
    estimated_tasks: int
    recommendation: str
    rationale: str
    suggested_children: list[AuditSuggestedChild]


@strawberry.type
class SpeedAuditResult:
    """SPEED's native audit output, read directly from disk."""
    status: str  # pass | warn | fail
    spec_type: str
    spec_file: str
    linked_specs: Optional[AuditLinkedSpecs]
    issues: list[AuditIssue]
    sizing: Optional[AuditSizing]
    stale: bool
    ran_at: str
    feature: str
