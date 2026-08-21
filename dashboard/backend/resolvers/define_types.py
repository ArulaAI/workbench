"""Strawberry GraphQL type definitions for the Define page."""

from __future__ import annotations

from typing import Optional

import strawberry


# ── Spec types ────────────────────────────────────────────────────


@strawberry.type
class SpecIndicator:
    exists: bool
    path: Optional[str]
    # audit_status: "clean" | "warning" | "error"
    audit_status: str
    warning_count: int
    warnings: list[str]


@strawberry.type
class AdditionalSpec:
    path: str
    spec_type: str
    audit_status: str
    warning_count: int


@strawberry.type
class SpecifiedData:
    product_spec: SpecIndicator
    technical_spec: SpecIndicator
    design_spec: SpecIndicator
    additional_specs: list[AdditionalSpec]
    open_questions: int
    sizing_estimate: Optional[int]


# ── Built types ───────────────────────────────────────────────────


@strawberry.type
class BuiltData:
    coverage_pct: Optional[float]
    criteria_passed: Optional[int]
    criteria_total: Optional[int]
    # guardian_verdict: "pass" | "fail" | "warn" | "unknown"
    guardian_verdict: Optional[str]
    # task_progress: 0.0-100.0 (computed as tasksDone/tasksTotal * 100)
    task_progress: Optional[float]
    tasks_done: Optional[int]
    tasks_total: Optional[int]
    blocked_count: int
    completed_at: Optional[str]


# ── Gap types ─────────────────────────────────────────────────────


@strawberry.type
class GapEscalation:
    description: str
    linked_warning_id: Optional[str]


@strawberry.type
class GapData:
    escalation_count: int
    escalations: list[GapEscalation]
    unverifiable_count: int
    rework_count: int


# ── Feature and defect types ──────────────────────────────────────


@strawberry.type
class DefineFeature:
    name: str
    state: str
    specified: SpecifiedData
    built: BuiltData
    gap: GapData


@strawberry.type
class DefineDefect:
    name: str
    # severity: "P0" | "P1" | "P2" | "P3" — unrecognized values clamped to "P3"
    severity: str
    status: str
    description: str
    impact: Optional[str]
    filed_at: Optional[str]


# ── Aggregates ────────────────────────────────────────────────────


@strawberry.type
class DefineAggregates:
    design_spec_count: int
    feature_count: int
    audit_warning_count: int
    open_question_count: int
    escalation_count: int
    completed_count: int
    executing_count: int
    unplanned_count: int


# ── Root View ─────────────────────────────────────────────────────


@strawberry.type
class DefineView:
    # vision_status: "missing" | "placeholder" | "defined"
    vision_status: str
    vision_path: Optional[str]
    features: list[DefineFeature]
    defects: list[DefineDefect]
    aggregates: DefineAggregates
