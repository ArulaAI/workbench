"""Strawberry GraphQL schema — types, Query, Subscription."""

from __future__ import annotations

import asyncio
import sqlite3
from enum import Enum
from typing import Any, AsyncGenerator, Optional

import strawberry

from .resolvers import token_burn, mission_control, topology, budget
from .resolvers import landing as landing_resolver
from .resolvers import define
from .resolvers import spec_editor
from .resolvers import intelligence as intelligence_resolver
from .resolvers import assist as assist_resolver
from .resolvers import audit_runner
from .resolvers import process_status as process_status_resolver
from .resolvers.ceremony_types import (
    CeremonyInfo,
    CommitRecord,
    ContextPackage,
    DecompositionInput,
    GenerateChildRfcsResult,
    GenerateDraftResult,
    RatificationState,
    SpecDraft,
    Suggestion,
    SuggestionHistory,
    SuggestionReply,
    ValidationState,
    get_ceremony_info,
)
from .resolvers.ceremony_decomposition_types import DecompositionResult
from .resolvers import context as context_resolver
from .resolvers import ceremony_editor as ceremony_editor_resolver
from .resolvers import ceremony_suggestions as suggestions_resolver
from .resolvers import ceremony_commitment as commitment_resolver
from .resolvers import ceremony_claims as claims_resolver
from .resolvers import authoring as authoring_resolver
from .resolvers.authoring_types import (
    AuthoringAction,
    AuthoringIntake,
    AuthoringSession,
    AuthoringSessionEvent,
)
from .resolvers.ceremony_types import CurrentActor, SpecClaimInfo, SpecProgressInfo
from .resolvers.ceremony_types import get_current_actor as _get_current_actor
from .resolvers import ceremony_bootstrap as bootstrap_resolver
from .resolvers.context_types import (
    AssemblyStatus,
    ContextHistory,
    DeclareIntentResult,
)
from .resolvers.define_types import DefineView
from .resolvers.spec_alignment import (
    Claim,
    ClaimSource,
    SectionAlignment,
    SpecAlignmentView,
    SpecSummary,
    get_spec_alignment,
)
from .resolvers.spec_editor_types import (
    AuditCheck,
    AuditResult,
    AuditUpdatedEvent,
    GhostSpec as GhostSpecType,
    SpecChangedEvent,
    SpecEntry,
    SpecGroup,
    SpecMutationResult,
    SpecRelation,
    SpecSearchResult,
    SpecSection as SpecSectionType,
    StructuredSpec,
)
from .resolvers.intelligence_types import (
    Lesson,
    Convention as ConventionType,
    ClusterContext,
    CodebaseStats,
    CodebaseContext,
    CoveredRequirement,
    SpecTraceability,
    ObservationTypeCount,
    ObservationSummary,
    ContractEntity,
    TaskDetail,
    Highlight,
    FeatureHealth,
)
from .resolvers.assist_types import (
    LLMModel,
    UnconfiguredProvider,
    AmbiguityIssue as AmbiguityIssueType,
    AmbiguityReport as AmbiguityReportType,
    FixSuggestionResult,
    SpecDraftResult,
    AuditRunStatus,
    AuditStatus,
    AuditIssue,
    AuditLinkedSpecs,
    AuditSuggestedChild,
    AuditSizing,
    SpeedAuditResult,
)
from .resolvers.landing_types import (
    EscalationResponseInput,
    EscalationResponseResult,
    LandingDefinePanel,
    LandingView,
)
from .subscriptions import SubscriptionManager, EventType


# ── Enums ────────────────────────────────────────────────────────

@strawberry.enum
class GroupBy(Enum):
    FEATURE = "feature"
    AGENT_TYPE = "agent_type"
    MODEL = "model"
    HOUR = "hour"
    DAY = "day"


# ── Scalar types ─────────────────────────────────────────────────

@strawberry.type
class Project:
    id: str
    name: str
    root_path: str
    git_remote: Optional[str]
    git_head: Optional[str]
    created_at: str
    updated_at: str


@strawberry.type
class FeatureState:
    name: str
    status: str
    started_at: Optional[str]
    task_count: int


@strawberry.type
class ModelUsageDetail:
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    cost_usd: float
    context_window: Optional[int]
    max_output_tokens: Optional[int]


@strawberry.type
class AgentRunSummary:
    id: str
    feature: str
    session_id: str
    agent_type: str
    task_id: Optional[str]
    subtype: Optional[str]
    is_error: bool
    duration_ms: Optional[int]
    duration_api_ms: Optional[int]
    num_turns: Optional[int]
    total_cost_usd: Optional[float]
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    source_file: str
    created_at: str
    models: Optional[str]


@strawberry.type
class TokenBurnAggregate:
    group_key: str
    run_count: int
    total_cost_usd: float
    total_input_tokens: int
    total_output_tokens: int
    total_cache_read_tokens: int
    total_cache_creation_tokens: int


@strawberry.type
class TokenBurnTimeSeries:
    bucket: str
    cost_usd: float
    cumulative_cost_usd: float
    run_count: int
    total_tokens: int


# ── Mission Control types ────────────────────────────────────────

@strawberry.type
class StatusCounts:
    pending: int = 0
    running: int = 0
    done: int = 0
    failed: int = 0
    reviewing: int = 0


@strawberry.type
class TaskNode:
    id: str
    title: str
    status: str
    agent_model: Optional[str]
    depends_on: list[str]
    branch: Optional[str]
    acceptance_criteria: Optional[str]
    files_touched: list[str]
    error: Optional[str]
    review_feedback: Optional[str]
    retry_count: int
    created_at: Optional[str]
    started_at: Optional[str]
    completed_at: Optional[str]


@strawberry.type
class MissionControl:
    feature: str
    status: str
    task_count: int
    status_counts: StatusCounts
    tasks: list[TaskNode]
    cross_task_analysis: Optional[strawberry.scalars.JSON]


# ── Topology types ───────────────────────────────────────────────

@strawberry.type
class NodeImpact:
    blast_radius: int
    centrality: float
    dependents: int
    stability: str


@strawberry.type
class SymbolNode:
    id: str
    name: str
    kind: str
    file: str
    line: int
    cluster: str
    impact: NodeImpact


@strawberry.type
class GraphEdge:
    source: str
    target: str
    type: str


@strawberry.type
class ClusterSummary:
    id: str
    symbol_count: int
    files: list[str]
    kinds: list[str]
    avg_blast_radius: float


@strawberry.type
class CodebaseTopology:
    generated_at: Optional[str]
    git_head: Optional[str]
    node_count: int
    edge_count: int
    cluster_count: int
    nodes: list[SymbolNode]
    edges: list[GraphEdge]
    clusters: list[ClusterSummary]
    cluster_edges: list[GraphEdge]


@strawberry.type
class ClusterDetail:
    cluster_id: str
    nodes: list[SymbolNode]
    internal_edges: list[GraphEdge]
    external_edges: list[GraphEdge]


# ── Budget types ─────────────────────────────────────────────────

@strawberry.type
class ContextAllocation:
    budget: int = 0
    used: int = 0
    files_full: Optional[int] = None
    files_skeleton: Optional[int] = None
    files_dropped: Optional[int] = None


@strawberry.type
class BudgetAllocation:
    code_context: ContextAllocation
    task_context: ContextAllocation
    spec_context: ContextAllocation
    reserve: int


@strawberry.type
class BudgetCut:
    file: str
    original_tier: str
    downgraded_to: str
    tokens_saved: int
    reason: str


@strawberry.type
class TaskBudget:
    task_id: str
    title: str
    stage: str
    total_budget: int
    total_used: int
    under_budget: bool
    allocated: BudgetAllocation
    cuts_made: list[BudgetCut]
    cuts_count: int
    tokens_saved: int


@strawberry.type
class BudgetSummary:
    task_count: int
    total_budget: int
    total_used: int
    utilization_pct: float
    total_cuts: int
    under_budget_count: int
    over_budget_count: int


@strawberry.type
class ContextBudgetView:
    tasks: list[TaskBudget]
    summary: BudgetSummary


# ── Subscription event types ─────────────────────────────────────

@strawberry.type
class TaskStatusEvent:
    feature: str
    task_id: str
    status: str


@strawberry.type
class AgentRunEvent:
    feature: str
    run_id: str
    cost: float


@strawberry.type
class CostAccumulationEvent:
    feature: Optional[str]
    total_cost_usd: float
    run_count: int


@strawberry.type
class AuditCompletedEvent:
    feature: str
    file: str


# ── Process detection types ──────────────────────────────────────


@strawberry.type
class AgentProcess:
    task_id: str
    pid: int
    alive: bool
    agent_type: Optional[str]


@strawberry.type
class StaleProcess:
    task_id: str
    pid: int
    pid_file: str
    agent_type: Optional[str]


@strawberry.type
class FeatureProcessState:
    name: str
    orchestrator_running: bool
    started_at: Optional[str]
    agents: list[AgentProcess]
    support_agents: list[AgentProcess]
    stale_processes: list[StaleProcess]


@strawberry.type
class ProcessStatus:
    active_feature: Optional[str]
    features: list[FeatureProcessState]


@strawberry.type
class ProcessStatusChangedEvent:
    feature: Optional[str]


@strawberry.type
class ContextAssemblyEvent:
    """Pushed per-source as context assembly progresses."""
    feature: str
    source: str       # "codebase" | "learnings" | ... | "complete"
    status: str       # "ok" | "empty" | "error"
    error: Optional[str] = None


@strawberry.type
class DraftGenerationEvent:
    """Pushed as draft generation progresses."""
    feature: str
    spec_type: str    # "prd" | "design" | "rfc"
    status: str       # "generating" | "complete" | "error"
    error: Optional[str] = None


@strawberry.type
class DecompositionProgressEvent:
    """Pushed at each stage of Architect decomposition."""
    feature: str
    spec_type: str
    stage: str        # loading_specs | assembling_context | calling_architect | parsing_response | running_gate | complete | error
    error: Optional[str] = None
    task_count: Optional[int] = None
    elapsed_s: Optional[float] = None
    model: Optional[str] = None


# ── Conversion helpers ───────────────────────────────────────────


def _to_speed_audit(data: dict) -> SpeedAuditResult:
    """Convert a raw audit dict from disk into the GraphQL type.

    SPEED audit JSON may contain explicit null values for list fields
    (e.g. "suggested_children": null). Python's dict.get() returns None
    when the key exists with a null value, not the default. Use `or []`
    to coerce None to empty list.
    """
    linked = data.get("linked_specs")
    linked_obj = None
    if linked and isinstance(linked, dict):
        linked_obj = AuditLinkedSpecs(
            prd=linked.get("prd"),
            design=linked.get("design"),
            parent_rfc=linked.get("parent_rfc"),
            child_rfcs=linked.get("child_rfcs") or [],
        )

    sizing = data.get("sizing")
    sizing_obj = None
    if sizing and isinstance(sizing, dict):
        children = []
        for ch in sizing.get("suggested_children") or []:
            if isinstance(ch, dict):
                children.append(AuditSuggestedChild(
                    name=ch.get("name", ""),
                    sections=ch.get("sections") or [],
                    depends_on=ch.get("depends_on") or [],
                    testable_output=ch.get("testable_output", ""),
                ))
        sizing_obj = AuditSizing(
            estimated_tasks=sizing.get("estimated_tasks", 0),
            recommendation=sizing.get("recommendation", "ok"),
            rationale=sizing.get("rationale", ""),
            suggested_children=children,
        )

    issues = []
    for issue in data.get("issues") or []:
        if isinstance(issue, dict):
            issues.append(AuditIssue(
                level=int(issue.get("level", 0)),
                severity=issue.get("severity", "warning"),
                section=issue.get("section", ""),
                message=issue.get("message", ""),
            ))

    return SpeedAuditResult(
        status=data.get("status", "unknown"),
        spec_type=data.get("spec_type", ""),
        spec_file=data.get("spec_file", ""),
        linked_specs=linked_obj,
        issues=issues,
        sizing=sizing_obj,
        stale=data.get("_stale", False),
        ran_at=data.get("_ran_at", ""),
        feature=data.get("_feature", ""),
    )

def _to_node(n: dict) -> SymbolNode:
    impact = n.get("impact", {})
    return SymbolNode(
        id=n.get("id", ""),
        name=n.get("name", ""),
        kind=n.get("kind", ""),
        file=n.get("file", ""),
        line=n.get("line", 0),
        cluster=n.get("cluster", ""),
        impact=NodeImpact(
            blast_radius=impact.get("blast_radius", 0),
            centrality=impact.get("centrality", 0.0),
            dependents=impact.get("dependents", 0),
            stability=impact.get("stability", "stable"),
        ),
    )


def _to_edge(e: dict) -> GraphEdge:
    return GraphEdge(
        source=e.get("source", e.get("from", "")),
        target=e.get("target", e.get("to", "")),
        type=e.get("type", ""),
    )


def _to_context_alloc(d: dict | int) -> ContextAllocation:
    if isinstance(d, int):
        return ContextAllocation(budget=d, used=0)
    return ContextAllocation(
        budget=d.get("budget", 0),
        used=d.get("used", 0),
        files_full=d.get("files_full"),
        files_skeleton=d.get("files_skeleton"),
        files_dropped=d.get("files_dropped"),
    )


def _to_budget_cut(c: dict) -> BudgetCut:
    return BudgetCut(
        file=c.get("file", ""),
        original_tier=c.get("original_tier", ""),
        downgraded_to=c.get("downgraded_to", ""),
        tokens_saved=c.get("tokens_saved", 0),
        reason=c.get("reason", ""),
    )


# ── Query ────────────────────────────────────────────────────────

@strawberry.type
class Query:
    @strawberry.field
    def project(self, info: strawberry.types.Info) -> Optional[Project]:
        conn: sqlite3.Connection = info.context["conn"]
        row = conn.execute("SELECT * FROM project WHERE id = 'default'").fetchone()
        if not row:
            return None
        return Project(**dict(row))

    @strawberry.field
    def features(self, info: strawberry.types.Info) -> list[FeatureState]:
        project_root = info.context["project_root"]
        items = mission_control.list_features(project_root)
        return [
            FeatureState(
                name=f["name"],
                status=f["status"],
                started_at=f.get("started_at"),
                task_count=f["task_count"],
            )
            for f in items
        ]

    @strawberry.field
    def token_burn(
        self,
        info: strawberry.types.Info,
        feature: Optional[str] = None,
        agent_type: Optional[str] = None,
        model: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AgentRunSummary]:
        conn: sqlite3.Connection = info.context["conn"]
        rows = token_burn.get_agent_runs(conn, feature, agent_type, model, limit, offset)
        return [
            AgentRunSummary(
                id=r["id"],
                feature=r["feature"],
                session_id=r["session_id"],
                agent_type=r["agent_type"],
                task_id=r.get("task_id"),
                subtype=r.get("subtype"),
                is_error=bool(r.get("is_error", 0)),
                duration_ms=r.get("duration_ms"),
                duration_api_ms=r.get("duration_api_ms"),
                num_turns=r.get("num_turns"),
                total_cost_usd=r.get("total_cost_usd"),
                input_tokens=r.get("input_tokens", 0),
                output_tokens=r.get("output_tokens", 0),
                cache_creation_tokens=r.get("cache_creation_tokens", 0),
                cache_read_tokens=r.get("cache_read_tokens", 0),
                source_file=r["source_file"],
                created_at=r["created_at"],
                models=r.get("models"),
            )
            for r in rows
        ]

    @strawberry.field
    def token_burn_aggregate(
        self,
        info: strawberry.types.Info,
        group_by: GroupBy,
        feature: Optional[str] = None,
    ) -> list[TokenBurnAggregate]:
        conn: sqlite3.Connection = info.context["conn"]
        rows = token_burn.aggregate_token_burn(conn, group_by.value, feature)
        return [
            TokenBurnAggregate(
                group_key=r["group_key"] or "unknown",
                run_count=r["run_count"],
                total_cost_usd=r.get("total_cost_usd") or 0,
                total_input_tokens=r.get("total_input_tokens") or 0,
                total_output_tokens=r.get("total_output_tokens") or 0,
                total_cache_read_tokens=r.get("total_cache_read_tokens") or 0,
                total_cache_creation_tokens=r.get("total_cache_creation_tokens") or 0,
            )
            for r in rows
        ]

    @strawberry.field
    def token_burn_time_series(
        self,
        info: strawberry.types.Info,
        feature: Optional[str] = None,
        bucket_minutes: int = 60,
    ) -> list[TokenBurnTimeSeries]:
        conn: sqlite3.Connection = info.context["conn"]
        rows = token_burn.token_burn_time_series(conn, feature, bucket_minutes)
        return [
            TokenBurnTimeSeries(
                bucket=r["bucket"],
                cost_usd=r.get("cost_usd") or 0,
                cumulative_cost_usd=r.get("cumulative_cost_usd", 0),
                run_count=r.get("run_count", 0),
                total_tokens=r.get("total_tokens") or 0,
            )
            for r in rows
        ]

    @strawberry.field
    def mission_control(
        self, info: strawberry.types.Info, feature: str
    ) -> Optional[MissionControl]:
        project_root = info.context["project_root"]
        data = mission_control.get_mission_control(project_root, feature)
        if not data:
            return None

        sc = data.get("status_counts", {})
        tasks = [
            TaskNode(
                id=t.get("id", ""),
                title=t.get("title", ""),
                status=t.get("status", "pending"),
                agent_model=t.get("agent_model"),
                depends_on=t.get("depends_on", []),
                branch=t.get("branch"),
                acceptance_criteria=t.get("acceptance_criteria"),
                files_touched=t.get("files_touched", []),
                error=t.get("error"),
                review_feedback=t.get("review_feedback"),
                retry_count=t.get("retry_count", 0),
                created_at=t.get("created_at"),
                started_at=t.get("started_at"),
                completed_at=t.get("completed_at"),
            )
            for t in data.get("tasks", [])
        ]

        return MissionControl(
            feature=feature,
            status=data["state"].get("status", "unknown"),
            task_count=data["task_count"],
            status_counts=StatusCounts(
                pending=sc.get("pending", 0),
                running=sc.get("running", 0),
                done=sc.get("done", 0),
                failed=sc.get("failed", 0),
                reviewing=sc.get("reviewing", 0),
            ),
            tasks=tasks,
            cross_task_analysis=data.get("cross_task_analysis"),
        )

    @strawberry.field
    def codebase_topology(self, info: strawberry.types.Info) -> Optional[CodebaseTopology]:
        project_root = info.context["project_root"]
        data = topology.get_codebase_topology(project_root)
        if not data:
            return None

        return CodebaseTopology(
            generated_at=data.get("generated_at"),
            git_head=data.get("git_head"),
            node_count=data["node_count"],
            edge_count=data["edge_count"],
            cluster_count=data["cluster_count"],
            nodes=[_to_node(n) for n in data["nodes"]],
            edges=[_to_edge(e) for e in data["edges"]],
            clusters=[
                ClusterSummary(
                    id=c["id"],
                    symbol_count=c["symbol_count"],
                    files=c["files"],
                    kinds=c["kinds"],
                    avg_blast_radius=c["avg_blast_radius"],
                )
                for c in data["clusters"]
            ],
            cluster_edges=[_to_edge(e) for e in data["cluster_edges"]],
        )

    @strawberry.field
    def cluster_detail(
        self, info: strawberry.types.Info, cluster_id: str
    ) -> Optional[ClusterDetail]:
        project_root = info.context["project_root"]
        data = topology.get_cluster_detail(project_root, cluster_id)
        if not data:
            return None
        return ClusterDetail(
            cluster_id=data["cluster_id"],
            nodes=[_to_node(n) for n in data["nodes"]],
            internal_edges=[_to_edge(e) for e in data["internal_edges"]],
            external_edges=[_to_edge(e) for e in data["external_edges"]],
        )

    @strawberry.field
    def spec_alignment(
        self, info: strawberry.types.Info, spec_file: Optional[str] = None
    ) -> Optional[SpecAlignmentView]:
        project_root = info.context["project_root"]
        return get_spec_alignment(project_root, spec_file)

    @strawberry.field
    def landing_view(self, info: strawberry.types.Info) -> LandingView:
        project_root = info.context["project_root"]
        return landing_resolver.get_landing_view(project_root)

    @strawberry.field
    def define_view(
        self, info: strawberry.types.Info, feature: Optional[str] = None
    ) -> Optional[DefineView]:
        project_root = info.context["project_root"]
        return define.get_define_view(project_root, feature)

    # ── Ceremony queries ────────────────────────────────────────

    @strawberry.field
    def authoring_intake(
        self, info: strawberry.types.Info, artifact_type: Optional[str] = None,
    ) -> AuthoringIntake:
        """Branch-aware missing-input contract for guided authoring."""
        return authoring_resolver.get_intake(
            info.context["project_root"], artifact_type
        )

    @strawberry.field
    def authoring_session(
        self, info: strawberry.types.Info,
        feature_name: str, artifact_type: str = "prd",
    ) -> AuthoringSession:
        """Read-only interview view. Never creates or advances a checkpoint."""
        return authoring_resolver.get_session(
            info.context["project_root"], feature_name, artifact_type
        )

    @strawberry.field
    def ceremony_info(
        self, info: strawberry.types.Info, feature_name: str
    ) -> Optional[CeremonyInfo]:
        project_root = info.context["project_root"]
        return get_ceremony_info(project_root, feature_name)

    # ── Context package queries ──────────────────────────────────

    @strawberry.field
    def context_package(
        self, info: strawberry.types.Info, feature_name: str
    ) -> Optional[ContextPackage]:
        project_root = info.context["project_root"]
        return context_resolver.get_context_package(project_root, feature_name)

    @strawberry.field
    def context_assembly_status(
        self, info: strawberry.types.Info, feature_name: str
    ) -> AssemblyStatus:
        project_root = info.context["project_root"]
        return context_resolver.get_context_assembly_status(project_root, feature_name)

    @strawberry.field
    def context_history(
        self, info: strawberry.types.Info, feature_name: str
    ) -> Optional[ContextHistory]:
        project_root = info.context["project_root"]
        return context_resolver.get_context_history(project_root, feature_name)

    # ── Ceremony editor queries ───────────────────────────────────

    @strawberry.field
    def spec_draft(
        self, info: strawberry.types.Info, feature_name: str, spec_type: Optional[str] = "prd"
    ) -> Optional[SpecDraft]:
        project_root = info.context["project_root"]
        return ceremony_editor_resolver.get_spec_draft(project_root, feature_name, spec_type or "prd")

    @strawberry.field
    def all_spec_drafts(
        self, info: strawberry.types.Info, feature_name: str
    ) -> list[SpecDraft]:
        project_root = info.context["project_root"]
        return ceremony_editor_resolver.get_all_spec_drafts(project_root, feature_name)

    @strawberry.field
    def validation_state(
        self, info: strawberry.types.Info, feature_name: str,
        spec_type: Optional[str] = "prd",
    ) -> Optional[ValidationState]:
        project_root = info.context["project_root"]
        return ceremony_editor_resolver.get_validation_state(
            project_root, feature_name, spec_type=spec_type or "prd",
        )

    # ── Suggestion queries ──────────────────────────────────────

    @strawberry.field
    def suggestions(
        self, info: strawberry.types.Info, feature_name: str
    ) -> list[Suggestion]:
        project_root = info.context["project_root"]
        return suggestions_resolver.get_suggestions(project_root, feature_name)

    @strawberry.field
    def suggestion_history(
        self, info: strawberry.types.Info, feature_name: str,
        spec_type: Optional[str] = None,
    ) -> SuggestionHistory:
        project_root = info.context["project_root"]
        return suggestions_resolver.get_suggestion_history(
            project_root, feature_name, spec_type=spec_type,
        )

    # ── Claims queries ─────────────────────────────────────────

    @strawberry.field
    def ceremony_claims(
        self, info: strawberry.types.Info, feature_name: str,
    ) -> list[SpecClaimInfo]:
        project_root = info.context["project_root"]
        raw = claims_resolver.ceremony_claims(project_root, feature_name)
        return [claims_resolver._to_info(c) for c in raw]

    @strawberry.field
    def current_actor(self, info: strawberry.types.Info) -> CurrentActor:
        """Return the viewer's identity for client-side ownership checks."""
        name, email = _get_current_actor()
        return CurrentActor(name=name, email=email)

    # ── Commitment queries ─────────────────────────────────────

    @strawberry.field
    def commit_record(
        self, info: strawberry.types.Info, feature_name: str,
        spec_type: str = "prd",
    ) -> Optional[CommitRecord]:
        project_root = info.context["project_root"]
        return commitment_resolver.get_commit_record(
            project_root, feature_name, spec_type,
        )

    @strawberry.field
    def ratification_state(
        self, info: strawberry.types.Info, feature_name: str,
        spec_type: str = "prd",
    ) -> Optional[RatificationState]:
        project_root = info.context["project_root"]
        return commitment_resolver.get_ratification_state(
            project_root, feature_name, spec_type,
        )

    @strawberry.field
    def ceremony_progress(
        self, info: strawberry.types.Info, feature_name: str,
    ) -> list[SpecProgressInfo]:
        project_root = info.context["project_root"]
        return commitment_resolver.get_ceremony_progress(
            project_root, feature_name,
        )

    # ── Bootstrap queries ──────────────────────────────────────

    @strawberry.field
    def bootstrap_status(
        self, info: strawberry.types.Info
    ) -> strawberry.scalars.JSON:
        project_root = info.context["project_root"]
        return bootstrap_resolver.get_bootstrap_status(project_root)

    @strawberry.field
    def vision_draft(
        self, info: strawberry.types.Info
    ) -> strawberry.scalars.JSON:
        project_root = info.context["project_root"]
        return bootstrap_resolver.get_vision_draft(project_root)

    @strawberry.field
    def derived_conventions(
        self, info: strawberry.types.Info
    ) -> strawberry.scalars.JSON:
        project_root = info.context["project_root"]
        return bootstrap_resolver.get_derived_conventions(project_root)

    # ── Decomposition queries ─────────────────────────────────────

    @strawberry.field
    def decomposition_result(
        self, info: strawberry.types.Info, feature_name: str,
        spec_type: str = "rfc",
    ) -> Optional[DecompositionResult]:
        project_root = info.context["project_root"]
        return ceremony_editor_resolver.get_decomposition_result(
            project_root, feature_name, spec_type,
        )

    # ── Spec editor queries ──────────────────────────────────────

    @strawberry.field
    def spec_tree(
        self, info: strawberry.types.Info, feature: Optional[str] = None
    ) -> list[SpecGroup]:
        conn: sqlite3.Connection = info.context["conn"]
        project_root = info.context["project_root"]
        return spec_editor.get_spec_tree(conn, project_root, feature)

    @strawberry.field
    def spec(self, info: strawberry.types.Info, path: str) -> Optional[StructuredSpec]:
        conn: sqlite3.Connection = info.context["conn"]
        project_root = info.context["project_root"]
        return spec_editor.get_spec(conn, project_root, path)

    @strawberry.field
    def spec_audit(self, info: strawberry.types.Info, path: str) -> Optional[AuditResult]:
        conn: sqlite3.Connection = info.context["conn"]
        project_root = info.context["project_root"]
        return spec_editor.get_spec_audit(conn, project_root, path)

    @strawberry.field
    def related_specs(self, info: strawberry.types.Info, path: str) -> list[SpecRelation]:
        conn: sqlite3.Connection = info.context["conn"]
        return spec_editor.get_related_specs(conn, path)

    @strawberry.field
    def spec_search(
        self, info: strawberry.types.Info, query: str, limit: int = 20
    ) -> list[SpecSearchResult]:
        conn: sqlite3.Connection = info.context["conn"]
        project_root = info.context["project_root"]
        return spec_editor.search_specs(conn, project_root, query, limit)

    # ── Intelligence queries ────────────────────────────────────

    @strawberry.field
    def lessons_for_spec(
        self, info: strawberry.types.Info, path: str, limit: int = 5
    ) -> list[Lesson]:
        project_root = info.context["project_root"]
        results = intelligence_resolver.get_lessons_for_spec(project_root, path, limit)
        return [Lesson(**r) for r in results]

    @strawberry.field
    def conventions_for_spec(
        self, info: strawberry.types.Info, path: str, limit: int = 10
    ) -> list[ConventionType]:
        project_root = info.context["project_root"]
        results = intelligence_resolver.get_conventions_for_spec(project_root, path, limit)
        return [ConventionType(**r) for r in results]

    @strawberry.field
    def codebase_context(
        self, info: strawberry.types.Info, path: str
    ) -> CodebaseContext:
        project_root = info.context["project_root"]
        data = intelligence_resolver.get_codebase_context(project_root, path)
        return CodebaseContext(
            clusters=[ClusterContext(**c) for c in data["clusters"]],
            stats=CodebaseStats(**data["stats"]),
        )

    @strawberry.field
    def spec_traceability(
        self, info: strawberry.types.Info, path: str
    ) -> Optional[SpecTraceability]:
        project_root = info.context["project_root"]
        data = intelligence_resolver.get_spec_traceability(project_root, path)
        if not data:
            return None
        return SpecTraceability(
            requirements_found=data["requirements_found"],
            coverage_ratio=data["coverage_ratio"],
            covered=[CoveredRequirement(**c) for c in data["covered"]],
            uncovered=data["uncovered"],
        )

    @strawberry.field
    def feature_health(
        self, info: strawberry.types.Info, path: str
    ) -> Optional[FeatureHealth]:
        project_root = info.context["project_root"]
        data = intelligence_resolver.get_feature_health(project_root, path)
        if not data:
            return None
        obs = data.get("observation_summary", {})
        return FeatureHealth(
            feature=data["feature"],
            status=data["status"],
            observation_summary=ObservationSummary(
                total=obs.get("total", 0),
                types=[ObservationTypeCount(**t) for t in obs.get("types", [])],
            ) if obs.get("total", 0) > 0 else None,
            contract_entities=[ContractEntity(**e) for e in data.get("contract_entities", [])],
            tasks=[TaskDetail(**t) for t in data.get("tasks", [])],
            highlights=[Highlight(**h) for h in data.get("highlights", [])],
        )

    @strawberry.field
    def file_skeleton(
        self, info: strawberry.types.Info, path: str
    ) -> Optional[str]:
        project_root = info.context["project_root"]
        return intelligence_resolver.get_file_skeleton(project_root, path)

    # ── Assist queries ─────────────────────────────────────────

    @strawberry.field
    def latest_audit(
        self, info: strawberry.types.Info, spec_path: str,
    ) -> Optional[SpeedAuditResult]:
        """Read the most recent audit result for a spec from disk."""
        project_root = info.context["project_root"]
        data = audit_runner.get_latest_audit(project_root, spec_path)
        if data is None:
            return None
        return _to_speed_audit(data)

    @strawberry.field
    def recent_audits(
        self, info: strawberry.types.Info, spec_path: str, limit: int = 3,
    ) -> list[SpeedAuditResult]:
        """Read the last N audit results for a spec from disk."""
        project_root = info.context["project_root"]
        audits = audit_runner.get_recent_audits(project_root, spec_path, limit=limit)
        return [_to_speed_audit(a) for a in audits]

    @strawberry.field
    def process_status(self, info: strawberry.types.Info) -> ProcessStatus:
        """Detect running SPEED processes from PID files on disk."""
        project_root = info.context["project_root"]
        data = process_status_resolver.get_process_status(project_root)
        return ProcessStatus(
            active_feature=data["active_feature"],
            features=[
                FeatureProcessState(
                    name=f["name"],
                    orchestrator_running=f["orchestrator_running"],
                    started_at=f.get("started_at"),
                    agents=[AgentProcess(**a) for a in f["agents"]],
                    support_agents=[AgentProcess(**a) for a in f["support_agents"]],
                    stale_processes=[StaleProcess(**s) for s in f["stale_processes"]],
                )
                for f in data["features"]
            ],
        )

    @strawberry.field
    def audit_status(
        self, info: strawberry.types.Info, spec_path: str,
    ) -> Optional[AuditStatus]:
        """Check if an audit subprocess is running for the given spec."""
        data = audit_runner.get_audit_status(spec_path)
        if data is None:
            return None
        return AuditStatus(running=data["running"], started_at=data["started_at"])

    @strawberry.field
    def git_branch(self, info: strawberry.types.Info) -> Optional[str]:
        project_root = info.context["project_root"]
        return audit_runner.get_git_branch(project_root)

    @strawberry.field
    def available_models(self, info: strawberry.types.Info) -> list[LLMModel]:
        project_root = info.context["project_root"]
        return assist_resolver.get_models(project_root)

    @strawberry.field
    def ceremony_models(self, info: strawberry.types.Info) -> list[LLMModel]:
        project_root = info.context["project_root"]
        return assist_resolver.get_ceremony_models_resolver(project_root)

    @strawberry.field
    def unconfigured_providers(self, info: strawberry.types.Info) -> list[UnconfiguredProvider]:
        project_root = info.context["project_root"]
        return assist_resolver.get_missing_providers(project_root)

    @strawberry.field
    def context_budget(
        self, info: strawberry.types.Info, feature: Optional[str] = None
    ) -> ContextBudgetView:
        project_root = info.context["project_root"]
        data = budget.get_context_budget(project_root, feature)

        summary_data = data["summary"]
        tasks_data = data["tasks"]

        return ContextBudgetView(
            tasks=[
                TaskBudget(
                    task_id=t["task_id"],
                    title=t["title"],
                    stage=t["stage"],
                    total_budget=t["total_budget"],
                    total_used=t["total_used"],
                    under_budget=t["under_budget"],
                    allocated=BudgetAllocation(
                        code_context=_to_context_alloc(t["allocated"].get("code_context", {})),
                        task_context=_to_context_alloc(t["allocated"].get("task_context", {})),
                        spec_context=_to_context_alloc(t["allocated"].get("spec_context", {})),
                        reserve=t["allocated"].get("reserve", 0)
                        if isinstance(t["allocated"].get("reserve"), int)
                        else 0,
                    ),
                    cuts_made=[_to_budget_cut(c) for c in t.get("cuts_made", [])],
                    cuts_count=t["cuts_count"],
                    tokens_saved=t["tokens_saved"],
                )
                for t in tasks_data
            ],
            summary=BudgetSummary(**summary_data),
        )


# ── Subscription ─────────────────────────────────────────────────

@strawberry.type
class Subscription:
    @strawberry.subscription
    async def task_status_changed(
        self, info: strawberry.types.Info, feature: str
    ) -> AsyncGenerator[TaskStatusEvent, None]:
        sub_manager: SubscriptionManager = info.context["sub_manager"]
        async for event in sub_manager.listen(EventType.TASK_STATUS_CHANGED, feature):
            yield TaskStatusEvent(
                feature=event.feature or feature,
                task_id=event.payload.get("task_id", ""),
                status=event.payload.get("status", ""),
            )

    @strawberry.subscription
    async def agent_run_completed(
        self, info: strawberry.types.Info, feature: Optional[str] = None
    ) -> AsyncGenerator[AgentRunEvent, None]:
        sub_manager: SubscriptionManager = info.context["sub_manager"]
        async for event in sub_manager.listen(EventType.AGENT_RUN_COMPLETED, feature):
            yield AgentRunEvent(
                feature=event.feature or "",
                run_id=event.payload.get("run_id", ""),
                cost=event.payload.get("cost", 0),
            )

    @strawberry.subscription
    async def spec_changed(
        self, info: strawberry.types.Info
    ) -> AsyncGenerator[SpecChangedEvent, None]:
        sub_manager: SubscriptionManager = info.context["sub_manager"]
        async for event in sub_manager.listen(EventType.SPEC_CHANGED):
            yield SpecChangedEvent(
                path=event.payload.get("path", ""),
                action=event.payload.get("action", "modified"),
            )

    @strawberry.subscription
    async def audit_completed(
        self, info: strawberry.types.Info, feature: Optional[str] = None,
    ) -> AsyncGenerator[AuditCompletedEvent, None]:
        sub_manager: SubscriptionManager = info.context["sub_manager"]
        async for event in sub_manager.listen(EventType.AUDIT_COMPLETED, feature):
            yield AuditCompletedEvent(
                feature=event.payload.get("feature", ""),
                file=event.payload.get("file", ""),
            )

    @strawberry.subscription
    async def process_status_changed(
        self, info: strawberry.types.Info, feature: Optional[str] = None,
    ) -> AsyncGenerator[ProcessStatusChangedEvent, None]:
        sub_manager: SubscriptionManager = info.context["sub_manager"]
        async for event in sub_manager.listen(EventType.PROCESS_STATUS_CHANGED, feature):
            yield ProcessStatusChangedEvent(feature=event.feature)

    @strawberry.subscription
    async def context_assembly_progress(
        self, info: strawberry.types.Info, feature: str,
    ) -> AsyncGenerator[ContextAssemblyEvent, None]:
        sub_manager: SubscriptionManager = info.context["sub_manager"]
        async for event in sub_manager.listen(EventType.CONTEXT_ASSEMBLY_PROGRESS, feature):
            yield ContextAssemblyEvent(
                feature=event.feature or feature,
                source=event.payload.get("source", ""),
                status=event.payload.get("status", ""),
                error=event.payload.get("error"),
            )

    @strawberry.subscription
    async def authoring_session_changed(
        self, info: strawberry.types.Info, feature: str,
    ) -> AsyncGenerator[AuthoringSessionEvent, None]:
        sub_manager: SubscriptionManager = info.context["sub_manager"]
        async for event in sub_manager.listen(
            EventType.AUTHORING_SESSION_CHANGED, feature
        ):
            yield AuthoringSessionEvent(
                feature=event.feature or feature,
                artifact_type=event.payload.get("artifact_type", ""),
                revision=event.payload.get("revision"),
                status=event.payload.get("status", ""),
            )

    @strawberry.subscription
    async def draft_generation_progress(
        self, info: strawberry.types.Info, feature: str,
    ) -> AsyncGenerator[DraftGenerationEvent, None]:
        sub_manager: SubscriptionManager = info.context["sub_manager"]
        async for event in sub_manager.listen(EventType.DRAFT_GENERATION_PROGRESS, feature):
            yield DraftGenerationEvent(
                feature=event.feature or feature,
                spec_type=event.payload.get("spec_type", ""),
                status=event.payload.get("status", ""),
                error=event.payload.get("error"),
            )

    @strawberry.subscription
    async def decomposition_progress(
        self, info: strawberry.types.Info, feature: str,
    ) -> AsyncGenerator[DecompositionProgressEvent, None]:
        sub_manager: SubscriptionManager = info.context["sub_manager"]
        async for event in sub_manager.listen(EventType.DECOMPOSITION_PROGRESS, feature):
            yield DecompositionProgressEvent(
                feature=event.feature or feature,
                spec_type=event.payload.get("spec_type", ""),
                stage=event.payload.get("stage", ""),
                error=event.payload.get("error"),
                task_count=event.payload.get("task_count"),
                elapsed_s=event.payload.get("elapsed_s"),
                model=event.payload.get("model"),
            )

    @strawberry.subscription
    async def cost_accumulation(
        self, info: strawberry.types.Info, feature: Optional[str] = None
    ) -> AsyncGenerator[CostAccumulationEvent, None]:
        sub_manager: SubscriptionManager = info.context["sub_manager"]
        conn: sqlite3.Connection = info.context["conn"]

        while True:
            await asyncio.sleep(5)
            filter_clause = ""
            params: list[Any] = []
            if feature:
                filter_clause = "WHERE feature = ?"
                params.append(feature)

            row = conn.execute(
                f"""SELECT COALESCE(SUM(total_cost_usd), 0) as total,
                           COUNT(*) as cnt
                    FROM agent_runs {filter_clause}""",
                params,
            ).fetchone()

            yield CostAccumulationEvent(
                feature=feature,
                total_cost_usd=row["total"] if row else 0,
                run_count=row["cnt"] if row else 0,
            )


# ── Mutation ─────────────────────────────────────────────────────

@strawberry.type
class Mutation:
    @strawberry.mutation
    def respond_to_escalation(
        self,
        info: strawberry.types.Info,
        feature: str,
        task_id: str,
        response: str,
    ) -> EscalationResponseResult:
        project_root = info.context["project_root"]
        return landing_resolver.respond_to_escalation(
            project_root,
            EscalationResponseInput(feature=feature, task_id=task_id, response=response),
        )

    # ── Spec editor mutations ─────────────────────────────────────

    @strawberry.mutation
    def create_spec(
        self,
        info: strawberry.types.Info,
        name: str,
        spec_type: str,
        feature: Optional[str] = None,
    ) -> SpecMutationResult:
        conn: sqlite3.Connection = info.context["conn"]
        project_root = info.context["project_root"]
        return spec_editor.create_spec(conn, project_root, name, spec_type, feature)

    @strawberry.mutation
    def update_spec_content(
        self,
        info: strawberry.types.Info,
        path: str,
        content: str,
    ) -> SpecMutationResult:
        conn: sqlite3.Connection = info.context["conn"]
        project_root = info.context["project_root"]
        return spec_editor.update_spec_content(conn, project_root, path, content)

    # ── Assist mutations ──────────────────────────────────────────

    @strawberry.mutation
    async def detect_ambiguities(
        self,
        info: strawberry.types.Info,
        path: str,
        model: str,
    ) -> Optional[AmbiguityReportType]:
        conn: sqlite3.Connection = info.context["conn"]
        project_root = info.context["project_root"]
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, assist_resolver.run_ambiguity_detection, conn, project_root, path, model
        )

    @strawberry.mutation
    async def suggest_fix(
        self,
        info: strawberry.types.Info,
        spec_path: str,
        section_text: str,
        issue_description: str,
        model: str,
    ) -> Optional[FixSuggestionResult]:
        conn: sqlite3.Connection = info.context["conn"]
        project_root = info.context["project_root"]
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, assist_resolver.run_fix_suggestion,
            conn, project_root, spec_path, section_text, issue_description, model
        )

    @strawberry.mutation
    async def build_spec_draft(
        self,
        info: strawberry.types.Info,
        problem_statement: str,
        spec_type: str,
        model: str,
    ) -> SpecDraftResult:
        conn: sqlite3.Connection = info.context["conn"]
        project_root = info.context["project_root"]
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, assist_resolver.run_spec_builder,
            conn, project_root, problem_statement, spec_type, model
        )

    @strawberry.mutation
    async def run_audit(
        self,
        info: strawberry.types.Info,
        path: str,
    ) -> AuditRunStatus:
        project_root = info.context["project_root"]
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(
            None, audit_runner.run_speed_audit, project_root, path
        )
        return AuditRunStatus(
            success=data["success"],
            error=data.get("error"),
        )

    @strawberry.mutation
    def delete_spec(
        self,
        info: strawberry.types.Info,
        path: str,
    ) -> SpecMutationResult:
        conn: sqlite3.Connection = info.context["conn"]
        project_root = info.context["project_root"]
        return spec_editor.delete_spec(conn, project_root, path)

    # ── Context package mutations ────────────────────────────────

    @strawberry.mutation
    async def declare_intent(
        self,
        info: strawberry.types.Info,
        text: str,
        feature_name: str,
        model: Optional[str] = None,
    ) -> DeclareIntentResult:
        project_root = info.context["project_root"]
        conn: sqlite3.Connection = info.context["conn"]
        sub_manager: SubscriptionManager = info.context["sub_manager"]
        loop = asyncio.get_event_loop()

        # Create ceremony (fast) — returns immediately
        result = await loop.run_in_executor(
            None,
            context_resolver.create_ceremony,
            project_root, text, feature_name,
        )

        # Fire assembly in background — subscription delivers progress
        async def _assemble():
            await loop.run_in_executor(
                None,
                lambda: context_resolver.assemble_context_package(
                    project_root, text, feature_name,
                    model=model, conn=conn, sub_manager=sub_manager,
                ),
            )
        asyncio.create_task(_assemble())

        return result

    @strawberry.mutation
    async def refine_intent(
        self,
        info: strawberry.types.Info,
        feature_name: str,
        text: str,
        model: Optional[str] = None,
    ) -> DeclareIntentResult:
        project_root = info.context["project_root"]
        conn: sqlite3.Connection = info.context["conn"]
        sub_manager: SubscriptionManager = info.context["sub_manager"]
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            context_resolver.refine_intent,
            project_root, feature_name, text,
            sub_manager, model, conn,
        )

    # ── Ceremony editor mutations ────────────────────────────────

    @strawberry.mutation
    async def generate_draft(
        self,
        info: strawberry.types.Info,
        feature_name: str,
        spec_type: str,
        model: str,
        refinement: Optional[str] = None,
    ) -> GenerateDraftResult:
        project_root = info.context["project_root"]
        conn: sqlite3.Connection = info.context["conn"]
        sub_manager: SubscriptionManager = info.context["sub_manager"]
        loop = asyncio.get_event_loop()

        # Validate inputs synchronously (fast)
        result = await loop.run_in_executor(
            None,
            lambda: ceremony_editor_resolver.start_generate_draft(
                project_root, feature_name, spec_type, model, conn,
                refinement=refinement,
            ),
        )

        # Fire generation in background
        async def _generate():
            await loop.run_in_executor(
                None,
                lambda: ceremony_editor_resolver.generate_draft_sync(
                    project_root, feature_name, spec_type, model, conn,
                    refinement=refinement,
                    sub_manager=sub_manager,
                ),
            )
        asyncio.create_task(_generate())

        return result

    @strawberry.mutation
    async def start_authoring(
        self,
        info: strawberry.types.Info,
        feature_name: str,
        feature_title: Optional[str] = None,
        feature_description: Optional[str] = None,
        artifact_type: str = "prd",
    ) -> AuthoringSession:
        project_root = info.context["project_root"]
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            authoring_resolver.start,
            project_root, feature_name, artifact_type,
            feature_title, feature_description,
        )

    @strawberry.mutation
    async def submit_authoring_answer(
        self,
        info: strawberry.types.Info,
        feature_name: str,
        answer: str,
        expected_revision: int,
        artifact_type: str = "prd",
    ) -> AuthoringSession:
        project_root = info.context["project_root"]
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            authoring_resolver.submit_answer,
            project_root, feature_name, artifact_type, answer, expected_revision,
        )

    @strawberry.mutation
    async def select_authoring_action(
        self,
        info: strawberry.types.Info,
        feature_name: str,
        action: AuthoringAction,
        expected_revision: int,
        artifact_type: str = "prd",
    ) -> AuthoringSession:
        project_root = info.context["project_root"]
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            authoring_resolver.select_action,
            project_root, feature_name, artifact_type, action, expected_revision,
        )

    @strawberry.mutation
    async def revise_authoring_coverage(
        self,
        info: strawberry.types.Info,
        feature_name: str,
        coverage_id: str,
        answer: str,
        expected_revision: int,
        artifact_type: str = "prd",
    ) -> AuthoringSession:
        project_root = info.context["project_root"]
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            authoring_resolver.revise_coverage,
            project_root, feature_name, artifact_type,
            coverage_id, answer, expected_revision,
        )

    @strawberry.mutation
    async def update_draft(
        self,
        info: strawberry.types.Info,
        feature_name: str,
        spec_type: str,
        content: str,
    ) -> SpecDraft:
        project_root = info.context["project_root"]
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            ceremony_editor_resolver.update_draft,
            project_root, feature_name, spec_type, content,
        )

    @strawberry.mutation
    async def validate_draft(
        self,
        info: strawberry.types.Info,
        feature_name: str,
        spec_type: Optional[str] = "prd",
        model: Optional[str] = None,
    ) -> ValidationState:
        project_root = info.context["project_root"]
        conn: sqlite3.Connection = info.context["conn"]
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: ceremony_editor_resolver.validate_draft(
                project_root, feature_name, spec_type or "prd", model, conn,
            ),
        )


    # ── Suggestion mutations ─────────────────────────────────────

    @strawberry.mutation
    async def create_suggestion(
        self, info: strawberry.types.Info,
        feature_name: str, spec_type: str, section_id: str,
        section_title: str, text: str,
    ) -> Suggestion:
        project_root = info.context["project_root"]
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: suggestions_resolver.create_suggestion(
                project_root, feature_name, spec_type,
                section_id, section_title, text,
            ),
        )

    @strawberry.mutation
    async def resolve_suggestion(
        self, info: strawberry.types.Info,
        feature_name: str, suggestion_id: str, action: str,
        reason: Optional[str] = None,
    ) -> Suggestion:
        project_root = info.context["project_root"]
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: suggestions_resolver.resolve_suggestion(
                project_root, feature_name, suggestion_id, action, reason,
            ),
        )

    @strawberry.mutation
    async def reply_suggestion(
        self, info: strawberry.types.Info,
        feature_name: str, suggestion_id: str, text: str,
    ) -> SuggestionReply:
        project_root = info.context["project_root"]
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: suggestions_resolver.reply_suggestion(
                project_root, feature_name, suggestion_id, text,
            ),
        )

    @strawberry.mutation
    async def delete_suggestion(
        self, info: strawberry.types.Info,
        feature_name: str, suggestion_id: str,
    ) -> bool:
        project_root = info.context["project_root"]
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: suggestions_resolver.delete_suggestion(
                project_root, feature_name, suggestion_id,
            ),
        )

    # ── Commitment mutations ──────────────────────────────────

    @strawberry.mutation
    async def commit_spec(
        self, info: strawberry.types.Info, feature_name: str,
        spec_type: str = "prd",
    ) -> CommitRecord:
        project_root = info.context["project_root"]
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: commitment_resolver.commit_spec(
                project_root, feature_name, spec_type,
            ),
        )

    @strawberry.mutation
    async def submit_ratification(
        self, info: strawberry.types.Info,
        feature_name: str, spec_type: str, verdict: str,
        comment: Optional[str] = None,
    ) -> RatificationState:
        project_root = info.context["project_root"]
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: commitment_resolver.submit_ratification(
                project_root, feature_name, spec_type, verdict, comment,
            ),
        )

    # ── Claims mutations ──────────────────────────────────────

    @strawberry.mutation
    async def claim_spec(
        self, info: strawberry.types.Info,
        feature_name: str, spec_type: str,
    ) -> SpecClaimInfo:
        project_root = info.context["project_root"]
        loop = asyncio.get_event_loop()
        claim = await loop.run_in_executor(
            None,
            lambda: claims_resolver.claim_spec(
                project_root, feature_name, spec_type,
            ),
        )
        return claims_resolver._to_info(claim)

    @strawberry.mutation
    async def release_spec(
        self, info: strawberry.types.Info,
        feature_name: str, spec_type: str,
    ) -> SpecClaimInfo:
        project_root = info.context["project_root"]
        loop = asyncio.get_event_loop()
        claim = await loop.run_in_executor(
            None,
            lambda: claims_resolver.release_spec(
                project_root, feature_name, spec_type,
            ),
        )
        return claims_resolver._to_info(claim)

    # ── Decomposition mutations ─────────────────────────────────

    @strawberry.mutation
    async def decompose_draft(
        self, info: strawberry.types.Info,
        feature_name: str,
        spec_type: Optional[str] = "prd",
        model: Optional[str] = None,
    ) -> DecompositionResult:
        project_root = info.context["project_root"]
        conn: sqlite3.Connection = info.context["conn"]
        sub_manager: SubscriptionManager = info.context["sub_manager"]
        loop = asyncio.get_event_loop()

        # Validate inputs synchronously (fast)
        result = await loop.run_in_executor(
            None,
            lambda: ceremony_editor_resolver.start_decompose_draft(
                project_root, feature_name, spec_type or "prd", model,
            ),
        )

        if result.status == "error":
            return result

        # Fire decomposition in background
        async def _decompose():
            await loop.run_in_executor(
                None,
                lambda: ceremony_editor_resolver.decompose_draft_sync(
                    project_root, feature_name, spec_type or "prd", model, conn,
                    sub_manager=sub_manager,
                ),
            )
        asyncio.create_task(_decompose())

        return result

    @strawberry.mutation
    async def generate_child_rfcs(
        self, info: strawberry.types.Info,
        feature_name: str,
        decomposition: DecompositionInput,
        model: str,
    ) -> GenerateChildRfcsResult:
        project_root = info.context["project_root"]
        conn: sqlite3.Connection = info.context["conn"]
        sub_manager: SubscriptionManager = info.context["sub_manager"]
        loop = asyncio.get_event_loop()

        # Validate inputs synchronously (fast)
        result = await loop.run_in_executor(
            None,
            lambda: ceremony_editor_resolver.start_generate_child_rfcs(
                project_root, feature_name, decomposition, model,
            ),
        )

        if result.status == "error":
            return result

        # Fire generation in background
        async def _generate():
            await loop.run_in_executor(
                None,
                lambda: ceremony_editor_resolver.generate_child_rfcs_sync(
                    project_root, feature_name, decomposition, model, conn,
                    sub_manager=sub_manager,
                ),
            )
        asyncio.create_task(_generate())

        return result

    # ── Bootstrap mutations ───────────────────────────────────

    @strawberry.mutation
    async def start_graph_build(
        self, info: strawberry.types.Info,
    ) -> strawberry.scalars.JSON:
        project_root = info.context["project_root"]
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: bootstrap_resolver.start_graph_build(project_root),
        )

    @strawberry.mutation
    async def generate_vision(
        self, info: strawberry.types.Info,
    ) -> strawberry.scalars.JSON:
        project_root = info.context["project_root"]
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: bootstrap_resolver.generate_vision(project_root),
        )

    @strawberry.mutation
    async def commit_vision(
        self, info: strawberry.types.Info, content: str,
    ) -> strawberry.scalars.JSON:
        project_root = info.context["project_root"]
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: bootstrap_resolver.commit_vision(project_root, content),
        )

    @strawberry.mutation
    async def extract_conventions(
        self, info: strawberry.types.Info,
    ) -> strawberry.scalars.JSON:
        project_root = info.context["project_root"]
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: bootstrap_resolver.extract_conventions(project_root),
        )

    @strawberry.mutation
    async def resolve_convention(
        self, info: strawberry.types.Info,
        convention_id: str, action: str,
    ) -> strawberry.scalars.JSON:
        project_root = info.context["project_root"]
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: bootstrap_resolver.resolve_convention(
                project_root, convention_id, action,
            ),
        )

    @strawberry.mutation
    async def commit_conventions(
        self, info: strawberry.types.Info,
        persona_input: Optional[str] = None,
    ) -> strawberry.scalars.JSON:
        project_root = info.context["project_root"]
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: bootstrap_resolver.commit_conventions(
                project_root, persona_input,
            ),
        )

    @strawberry.mutation
    async def complete_bootstrap(
        self, info: strawberry.types.Info,
    ) -> strawberry.scalars.JSON:
        project_root = info.context["project_root"]
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: bootstrap_resolver.complete_bootstrap(project_root),
        )


# ── Schema ───────────────────────────────────────────────────────

schema = strawberry.Schema(query=Query, mutation=Mutation, subscription=Subscription)
