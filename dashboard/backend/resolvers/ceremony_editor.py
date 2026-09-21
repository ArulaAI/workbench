"""GraphQL resolver for the Define Ceremony Editor.

Wires draft generation, update, and validation to the Strawberry schema.
Supports multi-spec generation: PRD → Design → RFC, where each spec
feeds into the next. Generation runs in the background with subscription
progress events.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..ceremony_generator import (
    _write_spec_file,
    generate_spec_draft,
    load_all_spec_drafts,
    load_spec_draft,
    save_spec_draft,
)
from ..ceremony_validator import (
    load_validation_state,
    save_validation_state,
    validate_spec,
)
from ..paths import get_paths
from ..subscriptions import DashboardEvent, EventType, SubscriptionManager
from .ceremony_authz import CeremonyAbility
from .ceremony_claims import refresh_claim_activity
from .ceremony_types import (
    ChildRfcInput,
    ContextPackage,
    DecompositionInput,
    GenerateChildRfcsResult,
    GenerateDraftResult,
    SpecDraft,
    ValidationState,
    _load_ceremony_state,
    _read_json,
    get_current_actor,
)

log = logging.getLogger("speed.dashboard.ceremony.editor")

# Generation order: PRD grounds Design, PRD + Design ground RFC
SPEC_ORDER = ["prd", "design", "rfc"]


def _load_context_package(project_root: Path, feature_name: str) -> ContextPackage:
    """Load persisted context package. Raises if not found."""
    from .context import load_context_package

    pkg = load_context_package(project_root, feature_name)
    if pkg is None:
        raise FileNotFoundError(
            f"No context package for feature '{feature_name}'. "
            "Run declareIntent first to assemble context."
        )
    return pkg


def _authorize(
    project_root: Path, feature_name: str, action: str, spec_type: str
) -> CeremonyAbility:
    """Load a CeremonyAbility and authorize the action. Raises on deny."""
    paths = get_paths(project_root)
    state_path = paths.ceremony_state(feature_name)
    if not state_path.exists():
        raise FileNotFoundError(f"No ceremony for feature '{feature_name}'")
    ability = CeremonyAbility.for_request(
        feature_name, spec_type, project_root=project_root
    )
    ability.authorize(action, spec_type)
    return ability


def _prior_specs_for(
    project_root: Path, feature_name: str, spec_type: str
) -> list[SpecDraft]:
    """Load completed prior specs that should ground this spec type."""
    all_drafts = load_all_spec_drafts(project_root, feature_name)
    idx = SPEC_ORDER.index(spec_type) if spec_type in SPEC_ORDER else 0
    prior_types = set(SPEC_ORDER[:idx])
    return [d for d in all_drafts if d.spec_type in prior_types]


# ── Mutations ──────────────────────────────────────────────────────────────


def generate_draft_sync(
    project_root: Path,
    feature_name: str,
    spec_type: str,
    model: str,
    conn: sqlite3.Connection | None,
    refinement: str | None = None,
    sub_manager: SubscriptionManager | None = None,
) -> None:
    """Run draft generation (blocking). Called from background task.

    Publishes progress events via sub_manager and persists the result.
    """
    def _publish(status: str, **extra: Any) -> None:
        if sub_manager:
            sub_manager.publish_sync(DashboardEvent(
                type=EventType.DRAFT_GENERATION_PROGRESS,
                feature=feature_name,
                payload={"spec_type": spec_type, "status": status, **extra},
            ))

    _publish("generating")

    try:
        pkg = _load_context_package(project_root, feature_name)
        prior = _prior_specs_for(project_root, feature_name, spec_type)

        draft = generate_spec_draft(
            intent=pkg.intent,
            context_package=pkg,
            spec_type=spec_type,
            model=model,
            prior_specs=prior or None,
            refinement=refinement,
            conn=conn,
            project_root=project_root,
        )

        _publish("complete", content_length=len(draft.content))

        # Run validation (non-blocking failure)
        try:
            vs = validate_spec(draft, project_root, model=model, conn=conn)
            save_validation_state(project_root, feature_name, vs, spec_type=spec_type)
        except Exception as exc:
            log.warning("Post-generation validation failed: %s", exc)

    except Exception as exc:
        log.error("Draft generation failed for %s/%s: %s", feature_name, spec_type, exc)
        _publish("error", error=str(exc))


def start_generate_draft(
    project_root: Path,
    feature_name: str,
    spec_type: str,
    model: str,
    conn: sqlite3.Connection | None,
    refinement: str | None = None,
) -> GenerateDraftResult:
    """Validate inputs and return immediately. Actual generation is async."""
    _authorize(project_root, feature_name, "edit", spec_type)

    # Validate context package exists
    _load_context_package(project_root, feature_name)

    return GenerateDraftResult(
        feature_name=feature_name,
        spec_type=spec_type,
        status="generating",
    )


def update_draft(
    project_root: Path,
    feature_name: str,
    spec_type: str,
    content: str,
) -> SpecDraft:
    """Save claimant edits, write spec file, run Tier 1 validation."""
    _authorize(project_root, feature_name, "edit", spec_type)
    refresh_claim_activity(project_root, feature_name, spec_type)

    existing = load_spec_draft(project_root, feature_name, spec_type)
    if existing is None:
        raise FileNotFoundError(
            f"No {spec_type} draft for feature '{feature_name}'"
        )

    updated = SpecDraft(
        feature_name=existing.feature_name,
        spec_type=existing.spec_type,
        content=content,
        file_path=existing.file_path,
        template_name=existing.template_name,
        generated_at=existing.generated_at,
        child_specs=existing.child_specs,
    )
    save_spec_draft(project_root, feature_name, updated)
    _write_spec_file(project_root, updated)

    # Run Tier 1 validation (fast, < 100ms)
    try:
        existing_vs = load_validation_state(project_root, feature_name, spec_type=spec_type)
        tier1 = validate_spec(updated, project_root, tiers=[1])

        if existing_vs:
            tier2_dims = [d for d in existing_vs.dimensions if d.tier == 2]
            merged_dims = list(tier1.dimensions) + tier2_dims
            pass_count = sum(1 for d in merged_dims if d.status == "pass")
            warn_count = sum(1 for d in merged_dims if d.status == "warn")
            fail_count = sum(1 for d in merged_dims if d.status == "fail")
            merged = ValidationState(
                dimensions=merged_dims,
                pass_count=pass_count,
                warn_count=warn_count,
                fail_count=fail_count,
            )
            save_validation_state(project_root, feature_name, merged, spec_type=spec_type)
        else:
            save_validation_state(project_root, feature_name, tier1, spec_type=spec_type)
    except Exception as exc:
        log.warning("Tier 1 validation after update failed: %s", exc)

    return updated


def validate_draft(
    project_root: Path,
    feature_name: str,
    spec_type: str = "prd",
    model: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> ValidationState:
    """Run all 6 dimensions, persist, return."""
    draft = load_spec_draft(project_root, feature_name, spec_type)
    if draft is None:
        raise FileNotFoundError(
            f"No {spec_type} draft for feature '{feature_name}'"
        )

    vs = validate_spec(draft, project_root, model=model, conn=conn)
    save_validation_state(project_root, feature_name, vs, spec_type=spec_type)
    return vs


# ── Queries ────────────────────────────────────────────────────────────────


def get_spec_draft(
    project_root: Path, feature_name: str, spec_type: str = "prd"
) -> SpecDraft | None:
    """Load persisted draft for a specific type."""
    return load_spec_draft(project_root, feature_name, spec_type)


def get_all_spec_drafts(
    project_root: Path, feature_name: str
) -> list[SpecDraft]:
    """Load all drafts for a ceremony."""
    return load_all_spec_drafts(project_root, feature_name)


def get_validation_state(
    project_root: Path, feature_name: str, spec_type: str = "prd",
) -> ValidationState | None:
    """Load persisted validation state for a spec type."""
    return load_validation_state(project_root, feature_name, spec_type=spec_type)


def get_decomposition_result(
    project_root: Path, feature_name: str, spec_type: str = "rfc"
):
    """Load persisted decomposition result for a specific RFC slot.

    Decomposition only exists for RFC slots. PRD and Design never produce
    a decomposition file.
    """
    from .ceremony_decomposition_types import (
        ArchitectTask,
        DecompositionResult,
        GateResult,
        SpecReference,
        _compute_chain_stats,
    )
    from .ceremony_types import _read_json

    paths = get_paths(project_root)
    data = _read_json(paths.ceremony_decomposition(feature_name, spec_type))
    # Fall back to legacy decomposition.json for pre-ownership ceremonies
    # that wrote to the unsuffixed path before the per-spec storage change.
    if data is None and spec_type:
        data = _read_json(paths.ceremony_decomposition(feature_name, ""))
    if data is None:
        return None

    raw_tasks = data.get("tasks", [])
    tasks = [
        ArchitectTask(
            id=t["id"], title=t["title"],
            description=t.get("description", ""),
            acceptance_criteria=t.get("acceptance_criteria", ""),
            depends_on=t.get("depends_on", []),
            agent_model=t.get("agent_model", "sonnet"),
            files_touched=t.get("files_touched", []),
            rationale=t.get("rationale"),
            assumptions=t.get("assumptions", []),
            spec_references=[
                SpecReference(spec=r.get("spec",""), section=r.get("section",""), requirement=r.get("requirement",""))
                for r in t.get("spec_references", [])
            ],
        )
        for t in raw_tasks
    ]
    gate_data = data.get("gate")
    gate = GateResult(
        overall=gate_data["overall"],
        warnings=gate_data.get("warnings", []),
        per_task=gate_data.get("per_task", []),
    ) if gate_data else None
    pc, lc = _compute_chain_stats(raw_tasks)

    return DecompositionResult(
        feature_name=feature_name,
        spec_type=data.get("spec_type", "prd"),
        status="complete",
        task_count=len(tasks),
        parallel_chains=pc,
        longest_chain=lc,
        tasks=tasks,
        validation=[],
        gate=gate,
        error=None,
    )


# ── Decomposition ─────────────────────────────────────────────────


def start_decompose_draft(
    project_root: Path,
    feature_name: str,
    spec_type: str = "rfc",
    model: str | None = None,
) -> "DecompositionResult":
    """Validate inputs for decomposition and return immediately.

    Actual decomposition runs in the background via decompose_draft_sync.
    Decomposition only applies to RFC slots; the authorization check
    rejects PRD and Design.
    """
    from .ceremony_decomposition_types import DecompositionResult

    _authorize(project_root, feature_name, "decompose", spec_type)
    refresh_claim_activity(project_root, feature_name, spec_type)

    draft = load_spec_draft(project_root, feature_name, spec_type)
    if draft is None:
        return DecompositionResult(
            feature_name=feature_name, spec_type=spec_type, status="error",
            task_count=0, parallel_chains=0, longest_chain=0,
            tasks=[], validation=[], gate=None,
            error=f"No {spec_type} draft for '{feature_name}'",
        )
    if not model:
        return DecompositionResult(
            feature_name=feature_name, spec_type=spec_type, status="error",
            task_count=0, parallel_chains=0, longest_chain=0,
            tasks=[], validation=[], gate=None,
            error="No model specified for decomposition",
        )

    return DecompositionResult(
        feature_name=feature_name, spec_type=spec_type, status="running",
        task_count=0, parallel_chains=0, longest_chain=0,
        tasks=[], validation=[], gate=None, error=None,
    )


def decompose_draft_sync(
    project_root: Path,
    feature_name: str,
    spec_type: str = "prd",
    model: str | None = None,
    conn: sqlite3.Connection | None = None,
    sub_manager: "SubscriptionManager | None" = None,
) -> None:
    """Run Architect decomposition (blocking). Called from background task.

    Publishes progress events via sub_manager at each stage.
    """
    import json as _json
    import time

    from .ceremony_decomposition_types import (
        ArchitectTask,
        ArchitectValidationItem,
        DecompositionResult,
        GateResult,
        SpecReference,
        _compute_chain_stats,
    )

    def _publish(stage: str, **extra: Any) -> None:
        if sub_manager:
            sub_manager.publish_sync(DashboardEvent(
                type=EventType.DECOMPOSITION_PROGRESS,
                feature=feature_name,
                payload={"spec_type": spec_type, "stage": stage, **extra},
            ))

    _publish("loading_specs")

    # Load draft
    draft = load_spec_draft(project_root, feature_name, spec_type)
    if draft is None:
        _publish("error", error=f"No {spec_type} draft for '{feature_name}'")
        return

    # Load all drafts for multi-spec context
    all_drafts = load_all_spec_drafts(project_root, feature_name)
    spec_sections = []
    for d in all_drafts:
        label = {"prd": "Product Spec", "design": "Design Spec", "rfc": "Technical RFC"}.get(
            d.spec_type, d.spec_type.upper()
        )
        spec_sections.append(f"## {label}\n{d.content}")
    specs_text = "\n\n---\n\n".join(spec_sections)

    # Assemble codebase context
    _publish("assembling_context")

    codebase_context = ""
    try:
        from lib.context.assembly import assemble_architect

        csg_path = project_root / ".speed" / "context" / "semantic-graph.json"
        pm_path = project_root / ".speed" / "context" / "project-map.json"
        sa_path = project_root / ".speed" / "context" / "spec-alignment.json"

        csg = _json.loads(csg_path.read_text()) if csg_path.exists() else {}
        pm = _json.loads(pm_path.read_text()) if pm_path.exists() else {}
        sa = _json.loads(sa_path.read_text()) if sa_path.exists() else None

        codebase_context = assemble_architect(
            project_map=pm, csg=csg, spec_alignment=sa,
        )
    except Exception as exc:
        log.warning("Context assembly for decomposition failed: %s", exc)
        codebase_context = "(Context assembly unavailable)"

    # Read Architect agent prompt
    agent_path = project_root / "agents" / "architect.md"
    agent_prompt = ""
    if agent_path.exists():
        agent_prompt = agent_path.read_text(encoding="utf-8")

    system_msg = agent_prompt or (
        "You are a senior software architect. Decompose the provided specs "
        "into a task DAG for parallel execution by developer agents."
    )

    user_msg = (
        f"## Feature: {feature_name}\n\n"
        f"{specs_text}\n\n"
        f"## Codebase Context\n\n{codebase_context}"
    )

    # Read JSON schema for structured output
    schema_path = project_root / "templates" / "architect-output.json"
    json_schema = ""
    if schema_path.exists():
        json_schema = schema_path.read_text(encoding="utf-8")

    # Call Architect via CLI (same invocation as speed plan)
    _publish("calling_architect", model=model,
             context_chars=len(codebase_context), spec_chars=len(specs_text))

    t0 = time.monotonic()
    log.info(
        "Decomposing %s/%s with model=%s, context=%d chars, specs=%d chars",
        feature_name, spec_type, model,
        len(codebase_context), len(specs_text),
    )

    try:
        from ..llm import cli_run_architect

        data = cli_run_architect(
            system_prompt=system_msg,
            user_message=user_msg,
            json_schema=json_schema,
            model=model,
            project_root=project_root,
            timeout=900,
        )

        elapsed = time.monotonic() - t0
        log.info("Architect response received in %.1fs", elapsed)
        _publish("parsing_response", elapsed_s=round(elapsed, 1))

    except Exception as exc:
        elapsed = time.monotonic() - t0
        log.error("Architect decomposition failed after %.1fs: %s", elapsed, exc)

        import subprocess as _sp
        if isinstance(exc, _sp.TimeoutExpired):
            friendly = f"Architect timed out after {round(elapsed)}s."
        elif isinstance(exc, RuntimeError) and "overloaded" in str(exc).lower():
            friendly = "Model is overloaded. Try again in a minute or use a different model."
        elif isinstance(exc, (RuntimeError, ValueError)):
            msg = str(exc)
            friendly = msg if len(msg) <= 300 else msg[:200] + "..."
        else:
            friendly = f"{type(exc).__name__}: {str(exc)[:200]}"

        _publish("error", error=friendly, elapsed_s=round(elapsed, 1))
        return

    # Parse tasks
    raw_tasks = data.get("tasks", [])
    tasks = [
        ArchitectTask(
            id=t["id"],
            title=t["title"],
            description=t.get("description", ""),
            acceptance_criteria=t.get("acceptance_criteria", ""),
            depends_on=t.get("depends_on", []),
            agent_model=t.get("agent_model", "sonnet"),
            files_touched=t.get("files_touched", []),
        )
        for t in raw_tasks
    ]

    # Run decomposition gate
    _publish("running_gate", task_count=len(tasks))

    gate = None
    try:
        from lib.decomposition_gate import check_decomposition

        pm_path = project_root / ".speed" / "context" / "project-map.json"
        csg_path = project_root / ".speed" / "context" / "semantic-graph.json"
        pm = _json.loads(pm_path.read_text()) if pm_path.exists() else {}
        csg_data = _json.loads(csg_path.read_text()) if csg_path.exists() else None

        gate_result = check_decomposition(raw_tasks, pm, csg=csg_data)
        gate = GateResult(
            overall=gate_result.get("overall", "pass"),
            warnings=gate_result.get("warnings", []),
            per_task=gate_result.get("per_task", []),
        )
    except Exception as exc:
        log.warning("Decomposition gate failed: %s", exc)

    # Compute chain stats
    parallel_chains, longest_chain = _compute_chain_stats(raw_tasks)

    # Persist result for sizing validator to read
    result_data = {
        "feature_name": feature_name,
        "spec_type": spec_type,
        "task_count": len(tasks),
        "parallel_chains": parallel_chains,
        "longest_chain": longest_chain,
        "tasks": raw_tasks,
        "gate": {"overall": gate.overall, "warnings": gate.warnings} if gate else None,
    }
    from .ceremony_types import _write_json
    paths = get_paths(project_root)
    _write_json(
        paths.ceremony_decomposition(feature_name, spec_type),
        result_data,
    )

    elapsed_total = time.monotonic() - t0
    _publish("complete", task_count=len(tasks), elapsed_s=round(elapsed_total, 1))


# ── Child RFC generation ─────────────────────────────────────────────────


def start_generate_child_rfcs(
    project_root: Path,
    feature_name: str,
    decomposition: DecompositionInput,
    model: str,
) -> GenerateChildRfcsResult:
    """Validate inputs and return immediately. Actual generation is async."""
    # Authorization: the caller must hold the RFC claim (or PRD, depending
    # on the decomposition flow). Use "edit" on the parent RFC slot.
    _authorize(project_root, feature_name, "edit", "rfc")

    # Context package must exist
    _load_context_package(project_root, feature_name)

    # Validate child names
    for child in decomposition.children:
        if not child.name or not child.name.strip():
            raise ValueError("child RFC name must not be empty")
        slug = child.name.lower().strip().replace(" ", "-")
        spec_type = f"rfc-{slug}"
        # Check that the slug doesn't collide with an existing spec
        existing = load_spec_draft(project_root, feature_name, spec_type)
        if existing is not None:
            raise ValueError(
                f"child spec rfc-{slug} already exists for {feature_name}"
            )

    return GenerateChildRfcsResult(
        feature_name=feature_name,
        status="generating",
        drafts=[],
    )


def generate_child_rfcs_sync(
    project_root: Path,
    feature_name: str,
    decomposition: DecompositionInput,
    model: str,
    conn: sqlite3.Connection | None,
    sub_manager: SubscriptionManager | None = None,
) -> None:
    """Generate each child RFC from decomposition plan (blocking).

    For each child in the decomposition:
    1. Scope context to the child's user stories
    2. Generate the RFC from parent PRD context + subsystem-scoped context
    3. Validate against template + audit
    4. Save the draft

    After all children, update the parent PRD's RFC Decomposition table.
    """
    def _publish(status: str, **extra: Any) -> None:
        if sub_manager:
            sub_manager.publish_sync(DashboardEvent(
                type=EventType.DRAFT_GENERATION_PROGRESS,
                feature=feature_name,
                payload={"spec_type": "child-rfcs", "status": status, **extra},
            ))

    _publish("generating", total=len(decomposition.children))

    try:
        pkg = _load_context_package(project_root, feature_name)
        # Load all existing drafts to use as prior specs for child generation
        all_drafts = load_all_spec_drafts(project_root, feature_name)
        prior_specs = [d for d in all_drafts if d.spec_type in ("prd", "design", "rfc")]

        generated: list[SpecDraft] = []

        for i, child in enumerate(decomposition.children):
            slug = child.name.lower().strip().replace(" ", "-")
            child_spec_type = f"rfc-{slug}"

            _publish(
                "generating_child",
                child_name=child.name,
                child_index=i,
                total=len(decomposition.children),
            )

            # Build a refinement that scopes the child to its stories
            story_scope = ", ".join(child.user_story_ids) if child.user_story_ids else ""
            deps_scope = ""
            if child.depends_on:
                deps_scope = f" Depends on: {', '.join(child.depends_on)}."
            refinement = (
                f"Generate a child RFC named '{child.name}' covering user stories: "
                f"{story_scope}.{deps_scope} "
                f"This is one subsystem of a decomposed RFC."
            )

            draft = generate_spec_draft(
                intent=pkg.intent,
                context_package=pkg,
                spec_type=child_spec_type,
                model=model,
                prior_specs=prior_specs or None,
                refinement=refinement,
                conn=conn,
                project_root=project_root,
            )

            save_spec_draft(project_root, feature_name, draft)
            _write_spec_file(project_root, draft)

            # Run validation (non-blocking failure)
            try:
                vs = validate_spec(draft, project_root, model=model, conn=conn)
                save_validation_state(
                    project_root, feature_name, vs, spec_type=child_spec_type,
                )
            except Exception as exc:
                log.warning(
                    "Post-generation validation for %s failed: %s",
                    child_spec_type, exc,
                )

            generated.append(draft)
            # Each generated child becomes a prior for the next
            prior_specs.append(draft)

        # Update parent PRD decomposition table if a PRD draft exists
        prd_draft = load_spec_draft(project_root, feature_name, "prd")
        if prd_draft is not None:
            _update_prd_decomposition_table(
                project_root, feature_name, prd_draft, decomposition,
            )

        _publish("complete", child_count=len(generated))

    except Exception as exc:
        log.error(
            "Child RFC generation failed for %s: %s", feature_name, exc,
        )
        _publish("error", error=str(exc))


def _update_prd_decomposition_table(
    project_root: Path,
    feature_name: str,
    prd_draft: SpecDraft,
    decomposition: DecompositionInput,
) -> None:
    """Append or update the RFC Decomposition table in the PRD spec."""
    table_header = "\n\n## RFC Decomposition\n\n"
    table_header += "| Child RFC | User Stories | Dependencies |\n"
    table_header += "|-----------|-------------|-------------|\n"

    rows = []
    for child in decomposition.children:
        slug = child.name.lower().strip().replace(" ", "-")
        stories = ", ".join(child.user_story_ids) if child.user_story_ids else "—"
        deps = ", ".join(child.depends_on) if child.depends_on else "—"
        rows.append(f"| rfc-{slug} | {stories} | {deps} |")

    table = table_header + "\n".join(rows) + "\n"

    # Replace existing table or append
    content = prd_draft.content
    marker = "## RFC Decomposition"
    if marker in content:
        # Find the start of the existing section and the next section
        idx = content.index(marker)
        # Find the next ## heading after this one
        next_section = content.find("\n## ", idx + len(marker))
        if next_section == -1:
            content = content[:idx].rstrip() + table
        else:
            content = content[:idx].rstrip() + table + "\n" + content[next_section:]
    else:
        content = content.rstrip() + table

    updated = SpecDraft(
        feature_name=prd_draft.feature_name,
        spec_type="prd",
        content=content,
        file_path=prd_draft.file_path,
        template_name=prd_draft.template_name,
        generated_at=prd_draft.generated_at,
        child_specs=prd_draft.child_specs,
    )
    save_spec_draft(project_root, feature_name, updated)
    _write_spec_file(project_root, updated)
