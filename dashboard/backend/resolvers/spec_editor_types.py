"""Strawberry GraphQL type definitions for the Spec Editor."""

from __future__ import annotations

from typing import Optional

import strawberry


# ── Section types ────────────────────────────────────────────────


@strawberry.type
class SpecSection:
    heading: str
    heading_level: int
    tier: str
    ordinal: int
    line_start: int
    line_end: int


# ── Audit types ──────────────────────────────────────────────────


@strawberry.type
class AuditCheck:
    check_id: str
    description: str
    dimension: str
    passed: bool


@strawberry.type
class AuditResult:
    spec_path: str
    completeness: float
    checks: list[AuditCheck]


# ── Relationship types ───────────────────────────────────────────


@strawberry.type
class SpecRelation:
    source: str
    target: str
    rel_type: str
    evidence: Optional[str]


# ── Ghost types ──────────────────────────────────────────────────


@strawberry.type
class GhostSpec:
    feature: str
    missing_types: list[str]


# ── Spec types ───────────────────────────────────────────────────


@strawberry.type
class SpecEntry:
    path: str
    spec_type: str
    feature: Optional[str]
    lifecycle_state: str
    completeness: Optional[float]
    section_count: int
    updated_at: str


@strawberry.type
class SpecGroup:
    feature: str
    specs: list[SpecEntry]
    ghosts: list[str]


@strawberry.type
class StructuredSpec:
    path: str
    spec_type: str
    feature: Optional[str]
    lifecycle_state: str
    completeness: Optional[float]
    sections: list[SpecSection]
    content: str
    header_lines: list[str]


# ── Search types ─────────────────────────────────────────────────


@strawberry.type
class SpecSearchResult:
    path: str
    spec_type: str
    feature: Optional[str]
    snippet: str


# ── Mutation result types ────────────────────────────────────────


@strawberry.type
class SpecMutationResult:
    success: bool
    path: Optional[str]
    error: Optional[str]


# ── Subscription event types ─────────────────────────────────────


@strawberry.type
class SpecChangedEvent:
    path: str
    action: str


@strawberry.type
class AuditUpdatedEvent:
    spec_path: str
    completeness: float
    checks: list[AuditCheck]
