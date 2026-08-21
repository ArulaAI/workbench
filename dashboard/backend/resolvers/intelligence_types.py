"""Strawberry GraphQL types for the Intelligence sidebar."""

from __future__ import annotations

from typing import Optional

import strawberry


@strawberry.type
class Lesson:
    id: str
    feature: str
    observation_type: str
    detail: str
    stage: str
    weight: float
    relevance: float


@strawberry.type
class Convention:
    id: str
    convention: str
    scope: list[str]
    confidence: str
    tags: list[str]
    adherence: float
    relevance: float


@strawberry.type
class ClusterContext:
    id: str
    label: str
    file_count: int
    symbol_count: int
    cohesion: float


@strawberry.type
class CodebaseStats:
    nodes: int
    files: int
    clusters: int
    total_clusters: int
    total_nodes: int


@strawberry.type
class CodebaseContext:
    clusters: list[ClusterContext]
    stats: CodebaseStats


# ── Traceability ─────────────────────────────────────────────


@strawberry.type
class CoveredRequirement:
    requirement: str
    evidence: str


@strawberry.type
class SpecTraceability:
    requirements_found: int
    coverage_ratio: float
    covered: list[CoveredRequirement]
    uncovered: list[str]


# ── Feature Health ───────────────────────────────────────────


@strawberry.type
class ObservationTypeCount:
    type: str
    count: int


@strawberry.type
class ObservationSummary:
    total: int
    types: list[ObservationTypeCount]


@strawberry.type
class ContractEntity:
    name: str
    type: str


@strawberry.type
class TaskDetail:
    id: str
    title: str
    status: str
    retry_count: int
    files_touched: int
    review_verdict: Optional[str] = None
    finding_count: Optional[int] = None


@strawberry.type
class Highlight:
    type: str
    stage: str
    weight: float
    detail: str


@strawberry.type
class FeatureHealth:
    feature: str
    status: str
    observation_summary: Optional[ObservationSummary]
    contract_entities: list[ContractEntity]
    tasks: list[TaskDetail]
    highlights: list[Highlight]
