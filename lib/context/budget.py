"""Token Budgeting — Layer 2.

Per-stage configurable budgets with priority-ordered cuts.
Ensures context packages fit within LLM token limits.

Cut strategy (when total exceeds budget):
  1. files_touched: NEVER cut
  2. 2-hop files: dropped entirely first
  3. Large 1-hop files: downgraded to skeleton
  4. Skeleton content: truncated if still over

Usage:
    from lib.context.budget import apply_budget
    budgeted = apply_budget(code_context, task_context, spec_context, stage="developer")

Tech spec: tech-spec-context-constructor.md → Layer 2 § Token Budgeting
"""

from __future__ import annotations

from .utils import (
    estimate_tokens_from_text,
    estimate_tokens_from_lines,
    get_context_budgets,
)


# ── Default budget allocations (% of total) ──────────────────

STAGE_ALLOCATIONS = {
    "developer": {
        "code_context": 0.60,
        "task_context": 0.15,
        "spec_context": 0.15,
        "reserve": 0.10,
    },
    "reviewer": {
        "code_context": 0.20,
        "task_context": 0.10,
        "spec_context": 0.20,
        "diff": 0.40,
        "reserve": 0.10,
    },
    "coherence": {
        "code_context": 0.10,
        "task_context": 0.20,
        "spec_context": 0.10,
        "diff": 0.50,
        "reserve": 0.10,
    },
    "architect": {
        "code_context": 0.70,
        "spec_context": 0.20,
        "reserve": 0.10,
    },
    "verifier": {
        "code_context": 0.40,
        "spec_context": 0.30,
        "task_context": 0.20,
        "reserve": 0.10,
    },
    "debugger": {
        "code_context": 0.40,
        "task_context": 0.20,
        "spec_context": 0.10,
        "diff": 0.20,
        "reserve": 0.10,
    },
}


# ── Budget application ───────────────────────────────────────


def apply_budget(
    code_context: dict,
    task_context: dict | None = None,
    spec_context: dict | None = None,
    stage: str = "developer",
    config: dict | None = None,
) -> dict:
    """Apply token budget to a context package.

    Estimates tokens for each section, applies cuts if over budget,
    and returns a budget.json report.

    Args:
        code_context: code-context.json dict (from build_code_context)
        task_context: task-context.json dict (optional)
        spec_context: spec-context.json dict (optional)
        stage: which stage's budget to use (developer, reviewer, etc.)
        config: speed.toml config (for custom budgets)

    Returns:
        budget.json dict with allocation breakdown and cuts_made.
    """
    # Get total budget for this stage
    budgets = get_context_budgets(config or {})
    total_budget = budgets.get(stage, 80000)

    # Get allocation percentages
    allocations = STAGE_ALLOCATIONS.get(stage, STAGE_ALLOCATIONS["developer"])

    # Estimate current token usage
    code_tokens = _estimate_code_tokens(code_context)
    task_tokens = _estimate_dict_tokens(task_context) if task_context else 0
    spec_tokens = _estimate_dict_tokens(spec_context) if spec_context else 0

    # Compute section budgets
    code_budget = int(total_budget * allocations.get("code_context", 0.6))
    task_budget = int(total_budget * allocations.get("task_context", 0.15))
    spec_budget = int(total_budget * allocations.get("spec_context", 0.15))
    reserve = int(total_budget * allocations.get("reserve", 0.10))

    # Apply cuts if code context exceeds budget
    cuts_made = []
    if code_tokens > code_budget:
        cuts_made = _apply_cuts(code_context, code_budget)
        code_tokens = _estimate_code_tokens(code_context)

    # Count files
    files_full = len(code_context.get("full_content", {}).get("files_touched", []))
    files_full += len(code_context.get("full_content", {}).get("one_hop", []))
    files_skeleton = len(code_context.get("skeleton", {}).get("two_hop", []))
    files_dropped = sum(1 for c in cuts_made if c.get("downgraded_to") == "dropped")

    return {
        "stage": stage,
        "total_budget": total_budget,
        "allocated": {
            "code_context": {
                "budget": code_budget,
                "used": code_tokens,
                "files_full": files_full,
                "files_skeleton": files_skeleton,
                "files_dropped": files_dropped,
            },
            "task_context": {
                "budget": task_budget,
                "used": task_tokens,
            },
            "spec_context": {
                "budget": spec_budget,
                "used": spec_tokens,
            },
            "reserve": reserve,
        },
        "cuts_made": cuts_made,
        "total_used": code_tokens + task_tokens + spec_tokens,
        "under_budget": (code_tokens + task_tokens + spec_tokens) <= (total_budget - reserve),
    }


# ── Token estimation ─────────────────────────────────────────


def _estimate_code_tokens(code_context: dict) -> int:
    """Estimate total tokens for code context."""
    total = 0

    full_content = code_context.get("full_content", {})
    for entry in full_content.get("files_touched", []):
        content = entry.get("content", "")
        total += estimate_tokens_from_text(content)

    for entry in full_content.get("one_hop", []):
        content = entry.get("content", "")
        total += estimate_tokens_from_text(content)

    skeleton = code_context.get("skeleton", {})
    for entry in skeleton.get("two_hop", []):
        content = entry.get("skeleton_content", "")
        total += estimate_tokens_from_text(content)

    return total


def _estimate_dict_tokens(d: dict) -> int:
    """Rough token estimation for a JSON dict (serialized)."""
    import json
    try:
        text = json.dumps(d, indent=2)
        return estimate_tokens_from_text(text)
    except (TypeError, ValueError):
        return 0


# ── Cut strategy ─────────────────────────────────────────────


def _apply_cuts(code_context: dict, budget: int) -> list[dict]:
    """Apply priority-ordered cuts to bring code context under budget.

    Tiered degradation (spec lines 1370-1372):
    1. 2-hop skeleton files: dropped entirely (lowest value)
    2. 1-hop files: downgraded from full content to skeleton
    3. Remaining skeletons: truncated as last resort

    files_touched are NEVER cut.
    """
    cuts = []
    current = _estimate_code_tokens(code_context)

    if current <= budget:
        return cuts

    # Step 1: Drop 2-hop files (largest first)
    two_hop = code_context.get("skeleton", {}).get("two_hop", [])
    two_hop_sorted = sorted(
        enumerate(two_hop),
        key=lambda x: len(x[1].get("skeleton_content", "")),
        reverse=True,
    )

    indices_to_remove = []
    for idx, entry in two_hop_sorted:
        if current <= budget:
            break
        tokens = estimate_tokens_from_text(entry.get("skeleton_content", ""))
        cuts.append({
            "file": entry["path"],
            "original_tier": "skeleton",
            "downgraded_to": "dropped",
            "tokens_saved": tokens,
            "reason": "2-hop, budget exceeded",
        })
        current -= tokens
        indices_to_remove.append(idx)

    # Remove dropped entries (reverse order to preserve indices)
    for idx in sorted(indices_to_remove, reverse=True):
        two_hop.pop(idx)

    if current <= budget:
        return cuts

    # Step 2: Downgrade 1-hop files to skeleton (largest first)
    # Load skeleton from skeleton_content field if present, otherwise
    # the file stays at full content (no skeleton available).
    one_hop = code_context.get("full_content", {}).get("one_hop", [])
    one_hop_sorted = sorted(
        enumerate(one_hop),
        key=lambda x: len(x[1].get("content", "")),
        reverse=True,
    )

    downgraded_to_skeleton = []
    for idx, entry in one_hop_sorted:
        if current <= budget:
            break
        content = entry.get("content", "")
        skeleton = entry.get("skeleton_content", "")
        if not skeleton:
            # No skeleton available — skip, handle in step 3
            continue
        content_tokens = estimate_tokens_from_text(content)
        skeleton_tokens = estimate_tokens_from_text(skeleton)
        tokens_saved = content_tokens - skeleton_tokens

        # Replace full content with skeleton
        entry["content"] = skeleton
        cuts.append({
            "file": entry["path"],
            "original_tier": "full",
            "downgraded_to": "skeleton",
            "tokens_saved": tokens_saved,
            "reason": f"1-hop file, downgraded to skeleton",
        })
        current -= tokens_saved
        downgraded_to_skeleton.append(idx)

    if current <= budget:
        return cuts

    # Step 3: Truncate remaining skeletons (last resort)
    # This covers: downgraded 1-hop files and any surviving 2-hop skeletons
    all_skeleton_entries = []
    for entry in one_hop:
        if estimate_tokens_from_text(entry.get("content", "")) > 0:
            all_skeleton_entries.append(("one_hop", entry))
    for entry in two_hop:
        if estimate_tokens_from_text(entry.get("skeleton_content", "")) > 0:
            all_skeleton_entries.append(("two_hop", entry))

    # Sort by size (largest first) for maximum budget recovery
    all_skeleton_entries.sort(
        key=lambda x: len(x[1].get("content", "") or x[1].get("skeleton_content", "")),
        reverse=True,
    )

    for tier, entry in all_skeleton_entries:
        if current <= budget:
            break
        if tier == "one_hop":
            text = entry.get("content", "")
            lines = text.splitlines()
            half = max(len(lines) // 2, 1)
            truncated = "\n".join(lines[:half])
            truncated += f"\n\n[Truncated: {len(lines) - half} lines omitted]"
            tokens_saved = estimate_tokens_from_text(text) - estimate_tokens_from_text(truncated)
            entry["content"] = truncated
        else:
            text = entry.get("skeleton_content", "")
            lines = text.splitlines()
            half = max(len(lines) // 2, 1)
            truncated = "\n".join(lines[:half])
            truncated += f"\n\n[Truncated: {len(lines) - half} lines omitted]"
            tokens_saved = estimate_tokens_from_text(text) - estimate_tokens_from_text(truncated)
            entry["skeleton_content"] = truncated

        cuts.append({
            "file": entry["path"],
            "original_tier": "skeleton" if tier == "two_hop" else "full",
            "downgraded_to": "truncated",
            "tokens_saved": tokens_saved,
            "reason": "skeleton truncation, last resort",
        })
        current -= tokens_saved

    return cuts


# ── Persistence ──────────────────────────────────────────────


def save_budget(budget: dict, task_context_dir: str) -> str:
    from .utils import write_json
    import os
    path = os.path.join(task_context_dir, "budget.json")
    write_json(path, budget)
    return path


def load_budget(task_context_dir: str) -> dict:
    from .utils import read_json
    import os
    path = os.path.join(task_context_dir, "budget.json")
    return read_json(path)
