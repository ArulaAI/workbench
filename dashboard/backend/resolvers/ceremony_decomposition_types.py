"""Strawberry/Pydantic types for the Architect decomposition preview.

Mirrors templates/architect-output.json schema. Used by the decompose_draft
resolver to return structured task DAG results to the frontend.
"""

from __future__ import annotations

from typing import Optional

import strawberry


@strawberry.type
class SpecReference:
    spec: str
    section: str
    requirement: str


@strawberry.type
class ArchitectTask:
    id: str
    title: str
    description: str
    acceptance_criteria: str
    depends_on: list[str]
    agent_model: str
    files_touched: list[str]
    rationale: Optional[str] = None
    assumptions: list[str] = strawberry.field(default_factory=list)
    spec_references: list[SpecReference] = strawberry.field(default_factory=list)


@strawberry.type
class ArchitectValidationItem:
    severity: str  # "critical" | "warning" | "note"
    issue: str
    product_requirement: str
    recommendation: str


@strawberry.type
class GateResult:
    overall: str  # "pass" | "warn" | "fail"
    warnings: list[str]


@strawberry.type
class DecompositionResult:
    feature_name: str
    spec_type: str
    status: str  # "complete" | "error"
    task_count: int
    parallel_chains: int
    longest_chain: int
    tasks: list[ArchitectTask]
    validation: list[ArchitectValidationItem]
    gate: Optional[GateResult]
    error: Optional[str]


def _compute_chain_stats(tasks: list[dict]) -> tuple[int, int]:
    """Compute parallel chain count and longest chain depth from a task DAG."""
    if not tasks:
        return 0, 0

    task_map = {t["id"]: t for t in tasks}
    depths: dict[str, int] = {}

    def depth(task_id: str) -> int:
        if task_id in depths:
            return depths[task_id]
        task = task_map.get(task_id)
        if not task or not task.get("depends_on"):
            depths[task_id] = 1
            return 1
        d = 1 + max(depth(dep) for dep in task["depends_on"] if dep in task_map)
        depths[task_id] = d
        return d

    for t in tasks:
        depth(t["id"])

    longest = max(depths.values()) if depths else 0

    # Parallel chains = tasks at depth 1 (no dependencies)
    roots = sum(1 for t in tasks if not t.get("depends_on"))

    return roots, longest
