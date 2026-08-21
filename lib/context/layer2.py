"""Layer 2 Orchestration — Task-Specific Projection.

Per-task build: code context + task context + spec context → budget → write.
Cross-task analysis: built once per feature at start of speed run.

Just-in-time: runs when task dependencies complete. Upstream decisions
don't exist until dependency tasks finish, so packages can't be
pre-computed.

Usage:
    from lib.context.layer2 import build_task_context_package, build_feature_cross_task
    pkg = build_task_context_package(task, all_tasks, ...)
    cross = build_feature_cross_task(tasks, csg, ...)

Tech spec: tech-spec-context-constructor.md → Layer 2 Orchestration
"""

from __future__ import annotations

import os
import time
from typing import Any

from .budget import apply_budget, save_budget
from .code_context import build_code_context, save_code_context
from .cross_task import build_cross_task_analysis, save_cross_task_analysis
from .spec_context import build_spec_context, save_spec_context
from .task_context import build_task_context, save_task_context
from .utils import ensure_dir, write_json


def build_task_context_package(
    task: dict,
    all_tasks: list[dict],
    project_root: str,
    csg: dict,
    project_map: dict,
    context_dir: str,
    spec_files: dict[str, str] | None = None,
    spec_alignment: dict | None = None,
    completed_tasks: dict[str, dict] | None = None,
    stage: str = "developer",
    config: dict | None = None,
    task_output_base: str | None = None,
) -> dict:
    """Build the complete context package for a single task.

    Args:
        task: task dict (with files_touched, depends_on, etc.)
        all_tasks: all tasks in the feature's DAG
        project_root: absolute path to project root
        csg: semantic-graph.json dict (from Layer 1)
        project_map: project-map.json dict (from Layer 1)
        context_dir: path to .speed/context/ (for loading Layer 1 artifacts)
        spec_files: {spec_path: content} for spec context
        spec_alignment: spec-alignment.json dict (from Layer 1)
        completed_tasks: {task_id: output_dict} for completed deps
        stage: which stage's budget to use
        config: speed.toml config (for custom budgets)
        task_output_base: where to write task packages (feature-scoped).
            Falls back to context_dir when not provided.

    Returns:
        Summary dict with timing and paths.
    """
    t_start = time.time()
    task_id = task.get("id", "unknown")

    # Task-specific context directory
    # Feature-scoped when task_output_base provided, codebase-scoped fallback
    base = task_output_base or context_dir
    task_context_dir = os.path.join(
        base, "tasks", task_id, "context"
    )
    ensure_dir(task_context_dir)

    result: dict[str, Any] = {
        "task_id": task_id,
        "artifacts": {},
        "timing": {},
    }

    # 1. Code Context (Dimension 1)
    t0 = time.time()
    code_ctx = build_code_context(task, project_root, csg, project_map, context_dir)
    save_code_context(code_ctx, task_context_dir)
    result["timing"]["code_context"] = round(time.time() - t0, 3)
    result["artifacts"]["code_context"] = os.path.join(task_context_dir, "code-context.json")
    result["expansion_summary"] = code_ctx.get("expansion_summary", {})

    # 2. Task Context (Dimension 2)
    t0 = time.time()
    task_ctx = build_task_context(task, all_tasks, csg, completed_tasks)
    save_task_context(task_ctx, task_context_dir)
    result["timing"]["task_context"] = round(time.time() - t0, 3)
    result["artifacts"]["task_context"] = os.path.join(task_context_dir, "task-context.json")

    # 3. Spec Context (Dimension 3)
    t0 = time.time()
    spec_ctx = build_spec_context(task, spec_files or {}, spec_alignment, csg)
    save_spec_context(spec_ctx, task_context_dir)
    result["timing"]["spec_context"] = round(time.time() - t0, 3)
    result["artifacts"]["spec_context"] = os.path.join(task_context_dir, "spec-context.json")

    # 4. Token Budget
    t0 = time.time()
    budget = apply_budget(code_ctx, task_ctx, spec_ctx, stage=stage, config=config)
    save_budget(budget, task_context_dir)
    result["timing"]["budget"] = round(time.time() - t0, 3)
    result["artifacts"]["budget"] = os.path.join(task_context_dir, "budget.json")
    result["budget_summary"] = {
        "total_budget": budget["total_budget"],
        "total_used": budget["total_used"],
        "under_budget": budget["under_budget"],
        "cuts_made": len(budget["cuts_made"]),
    }

    result["timing"]["total"] = round(time.time() - t_start, 3)
    return result


def build_feature_cross_task(
    tasks: list[dict],
    csg: dict | None,
    feature_context_dir: str,
) -> dict:
    """Build cross-task analysis for a feature (once per speed run).

    Args:
        tasks: all tasks in the feature's DAG
        csg: semantic-graph.json dict
        feature_context_dir: .speed/features/{feature}/context/

    Returns:
        cross-task-analysis.json dict.
    """
    ensure_dir(feature_context_dir)
    analysis = build_cross_task_analysis(tasks, csg)
    save_cross_task_analysis(analysis, feature_context_dir)
    return analysis
