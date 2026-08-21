"""Strawberry GraphQL type definitions for the landing page."""

from __future__ import annotations

from typing import Optional

import strawberry


# ── Define Panel ──────────────────────────────────────────────────


@strawberry.type
class LandingDraftSpec:
    name: str
    # spec_types limited to "product" and/or "technical"
    spec_types: list[str]
    # status: "unplanned" | "writing"
    status: str


@strawberry.type
class LandingDefect:
    # severity: "P0" | "P1" | "P2" | "P3" — unrecognized values clamped to "P3"
    severity: str
    name: str


@strawberry.type
class LandingDefinePanel:
    # vision_status: "missing" | "placeholder" | "defined"
    vision_status: str
    draft_specs: list[LandingDraftSpec]
    defects: list[LandingDefect]
    defect_count: int


# ── Judge Panel ───────────────────────────────────────────────────


@strawberry.type
class LandingDecisionItem:
    """A criterion the system couldn't fully verify — needs human judgment."""
    title: str
    description: str


@strawberry.type
class LandingCompletedFeature:
    feature: str
    completed_at: Optional[str]
    coverage_pct: float
    criteria_passed: int
    criteria_total: int
    guardian_verdict: str
    decisions_needed: int
    decision_items: list[LandingDecisionItem]
    # "pending" (no review.json), "approved", "rejected"
    review_status: str
    summary: Optional[str]


@strawberry.type
class LandingQualityGate:
    """Status of a quality gate (guardian, coherence, security)."""
    name: str
    # "pass", "fail", "warn", "unknown"
    status: str
    detail: Optional[str]


@strawberry.type
class LandingJudgePanel:
    completed_features: list[LandingCompletedFeature]
    quality_gates: list[LandingQualityGate]
    # Aggregate counts
    total_features: int
    awaiting_review: int


# ── Execute Panel ─────────────────────────────────────────────────


@strawberry.type
class LandingRunningFeature:
    name: str
    # progress_pct clamped 0–100
    progress_pct: float
    tasks_completed: int
    tasks_total: int
    blocked_count: int


@strawberry.type
class LandingRecentFeature:
    name: str
    completed_at: Optional[str]
    coverage_pct: float
    tasks_completed: int
    tasks_total: int


@strawberry.type
class LandingEscalation:
    feature: str
    task_id: str
    task_title: str
    question: str


@strawberry.type
class LandingExecutePanel:
    running_features: list[LandingRunningFeature]
    recent_features: list[LandingRecentFeature]
    escalations: list[LandingEscalation]


# ── Learn Panel ───────────────────────────────────────────────────


@strawberry.type
class LandingCoverageTrend:
    feature: str
    # coverage_pct clamped 0–100
    coverage_pct: float


@strawberry.type
class LandingInsight:
    # type: "good" | "warn"
    type: str
    text: str


@strawberry.type
class LandingEscalationTrend:
    feature: str
    count: int


@strawberry.type
class LandingLearnPanel:
    coverage_trend: list[LandingCoverageTrend]
    insights: list[LandingInsight]
    escalation_trend: list[LandingEscalationTrend]


# ── Root View ─────────────────────────────────────────────────────


@strawberry.type
class LandingView:
    greeting: str
    project_name: str
    branch: Optional[str]
    # LLM-generated summary; null when unavailable or timed out
    narrative: Optional[str]
    define: LandingDefinePanel
    judge: LandingJudgePanel
    execute: LandingExecutePanel
    learn: LandingLearnPanel


# ── Mutation I/O ──────────────────────────────────────────────────


@strawberry.input
class EscalationResponseInput:
    feature: str
    task_id: str
    response: str


@strawberry.type
class EscalationResponseResult:
    success: bool
    error: Optional[str]
