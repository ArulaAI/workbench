"""Layer 3: Stage-Specific Assembly.

Formats structured context (from Layer 1 and Layer 2) into the actual
prompt text each agent stage receives. Pure formatting — structured data
in, markdown out. No LLM calls.

Six assembly functions — one per agent stage:
  assemble_architect   — Layer 1 → codebase context markdown
  assemble_verifier    — Layer 1 + task DAG → plan verification context
  assemble_developer   — Layer 2 → developer prompt
  assemble_reviewer    — Layer 2 + diff → review context
  assemble_coherence   — cross-task analysis + diffs → coherence context
  assemble_debugger    — budget + context + logs → debug context

Section ordering principle: context before content, intent before detail.
  1. What and why — task identity, rationale, criteria
  2. Constraints — assumptions, cross-cutting concerns, warnings
  3. Material — code, diffs, analysis
  4. Traceability — spec references, alignment status
  5. Operational — branch, gates, working directory, instructions

Usage:
    from lib.context.assembly import assemble_developer
    markdown = assemble_developer(context_package, task, feature_config)

Tech spec: tech-spec-context-constructor.md → Layer 3
"""

from __future__ import annotations

import os
import re

from .utils import estimate_tokens_from_text, get_context_budgets


# ── Truncation helper ─────────────────────────────────────────


def _truncate(text: str, max_tokens: int, label: str = "") -> str:
    """Truncate text to fit within a token budget."""
    estimated = estimate_tokens_from_text(text)
    if estimated <= max_tokens:
        return text

    # Estimate characters for budget (slightly conservative to avoid overshoot)
    max_chars = int(max_tokens * 3.8)
    truncated = text[:max_chars]
    # Find last newline to avoid cutting mid-line
    last_nl = truncated.rfind("\n")
    if last_nl > max_chars // 2:
        truncated = truncated[:last_nl]

    # Re-check and trim further if still over budget (accounts for token/char ratio variance)
    for _ in range(5):
        recheck = estimate_tokens_from_text(truncated)
        if recheck <= max_tokens:
            break
        overshoot = recheck - max_tokens
        trim_chars = max(overshoot * 4, 100)
        truncated = truncated[:-trim_chars]
        last_nl = truncated.rfind("\n")
        if last_nl > len(truncated) // 2:
            truncated = truncated[:last_nl]

    lines_total = text.count("\n")
    lines_kept = truncated.count("\n")
    suffix = f"\n\n[Truncated{': ' + label if label else ''}: {lines_total - lines_kept} lines omitted]"
    return truncated + suffix


def _truncate_code(text: str, max_tokens: int) -> str:
    """Truncate code: keep imports + top-level signatures, drop bodies."""
    estimated = estimate_tokens_from_text(text)
    if estimated <= max_tokens:
        return text

    lines = text.splitlines()
    kept: list[str] = []
    in_body = False
    body_indent = 0
    omitted = 0

    for line in lines:
        stripped = line.lstrip()
        indent = len(line) - len(stripped)

        # Always keep imports and blank lines between top-level items
        if stripped.startswith(("import ", "from ")) or not stripped:
            kept.append(line)
            in_body = False
            continue

        # Keep top-level definitions (def/class at indent 0-1)
        if indent <= 4 and stripped.startswith(("def ", "class ", "async def ")):
            kept.append(line)
            in_body = True
            body_indent = indent
            continue

        # Inside a body: skip (truncated)
        if in_body and indent > body_indent:
            omitted += 1
            continue

        # Keep decorators
        if stripped.startswith("@"):
            kept.append(line)
            continue

        # Top-level assignments and other statements
        if indent == 0:
            kept.append(line)
            in_body = False
            continue

        omitted += 1

        # Check budget
        if estimate_tokens_from_text("\n".join(kept)) > max_tokens:
            break

    result = "\n".join(kept)
    if omitted:
        result += f"\n\n[Truncated: {omitted} body lines omitted, imports + signatures preserved]"
    return result


def _truncate_skeleton(text: str, max_tokens: int) -> str:
    """Truncate skeleton: simple bottom truncation (already compressed)."""
    return _truncate(text, max_tokens, "skeleton")


def _truncate_diff(text: str, max_tokens: int) -> str:
    """Truncate diff: keep headers + first N hunks that fit budget."""
    estimated = estimate_tokens_from_text(text)
    if estimated <= max_tokens:
        return text

    # Split into hunks (each starts with @@ or diff --git)
    parts: list[str] = []
    current_part: list[str] = []

    for line in text.splitlines():
        if (line.startswith("diff --git") or line.startswith("@@")) and current_part:
            parts.append("\n".join(current_part))
            current_part = []
        current_part.append(line)
    if current_part:
        parts.append("\n".join(current_part))

    # Keep parts while under budget
    kept: list[str] = []
    for part in parts:
        candidate = "\n".join(kept + [part]) if kept else part
        if estimate_tokens_from_text(candidate) > max_tokens and kept:
            break
        kept.append(part)

    result = "\n".join(kept)
    remaining = len(parts) - len(kept)
    if remaining > 0:
        result += f"\n\n[Truncated: {remaining} hunks omitted]"
    return result


def _truncate_spec(text: str, max_tokens: int) -> str:
    """Truncate spec: drop least-relevant sections (from the end)."""
    estimated = estimate_tokens_from_text(text)
    if estimated <= max_tokens:
        return text

    # Split by section headers (## or ###)
    sections: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if re.match(r"^#{2,3}\s", line) and current:
            sections.append("\n".join(current))
            current = []
        current.append(line)
    if current:
        sections.append("\n".join(current))

    # Keep sections from the front (highest relevance) while under budget
    kept: list[str] = []
    for section in sections:
        candidate = "\n".join(kept + [section]) if kept else section
        if estimate_tokens_from_text(candidate) > max_tokens and kept:
            break
        kept.append(section)

    result = "\n".join(kept)
    dropped = len(sections) - len(kept)
    if dropped > 0:
        result += f"\n\n[Truncated: {dropped} spec sections omitted]"
    return result


def _truncate_upstream(text: str, max_tokens: int) -> str:
    """Truncate upstream decisions: drop oldest dependencies first."""
    estimated = estimate_tokens_from_text(text)
    if estimated <= max_tokens:
        return text

    # Split by task headers (#### Task ...)
    sections: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.startswith("#### Task ") and current:
            sections.append("\n".join(current))
            current = []
        current.append(line)
    if current:
        sections.append("\n".join(current))

    # Drop from front (oldest dependencies) to preserve recent context
    while len(sections) > 1:
        candidate = "\n".join(sections[1:])
        if estimate_tokens_from_text(candidate) <= max_tokens:
            dropped = len(sections) - len(sections[1:])
            result = candidate
            result += f"\n\n[Truncated: {dropped} oldest dependency sections omitted]"
            return result
        sections.pop(0)

    return _truncate(text, max_tokens, "upstream decisions")


def _truncate_cross_task(text: str, max_tokens: int) -> str:
    """Truncate cross-task analysis: keep high-risk items, drop low-risk."""
    estimated = estimate_tokens_from_text(text)
    if estimated <= max_tokens:
        return text

    # Split by risk items (lines starting with ** or `)
    lines = text.splitlines()
    # Separate high-risk (mentions "high" or "critical") from low-risk
    high_risk: list[str] = []
    low_risk: list[str] = []
    current_block: list[str] = []
    is_high = False

    for line in lines:
        if line.startswith(("**", "`", "---", "####")):
            if current_block:
                (high_risk if is_high else low_risk).append("\n".join(current_block))
                current_block = []
            is_high = bool(re.search(r"(?i)(high|critical|bridge)", line))
        current_block.append(line)
    if current_block:
        (high_risk if is_high else low_risk).append("\n".join(current_block))

    # Keep all high-risk, trim low-risk
    result = "\n".join(high_risk)
    if estimate_tokens_from_text(result) <= max_tokens:
        remaining_budget = max_tokens - estimate_tokens_from_text(result)
        for block in low_risk:
            if estimate_tokens_from_text(result + "\n" + block) <= max_tokens:
                result += "\n" + block
            else:
                break

    dropped = len(low_risk) - result.count("\n".join(low_risk[:1]) if low_risk else "")
    if dropped > 0 and len(low_risk) > 0:
        result += f"\n\n[Truncated: low-risk items omitted, {len(high_risk)} high-risk items preserved]"
    return _truncate(result, max_tokens, "cross-task analysis")


def _lang_for_path(path: str) -> str:
    """Infer language identifier from file path for code fences."""
    from .language_registry import registry
    return registry.fence_label_for(path)


# ══════════════════════════════════════════════════════════════
# 1. Architect Assembly
# ══════════════════════════════════════════════════════════════


def assemble_architect(
    project_map: dict,
    csg: dict,
    spec_alignment: dict | None = None,
    config: dict | None = None,
    learnings: str = "",
    conventions: str = "",
    project_knowledge: str = "",
) -> str:
    """Assemble codebase context markdown for the Architect.

    Source: Layer 1 artifacts directly. Layer 2 doesn't exist yet.
    Replaces: spec_ground.py output.

    Args:
        project_map: project-map.json dict
        csg: semantic-graph.json dict
        spec_alignment: spec-alignment.json dict (optional)
        config: speed.toml config (for budget)

    Returns:
        Markdown string for injection into the Architect prompt.
    """
    budgets = get_context_budgets(config or {})
    total_budget = budgets.get("architect", 60000)
    sections = []

    # ── Project Overview ──────────────────────────────────
    summary = project_map.get("summary", {})
    by_lang = summary.get("by_language", {})

    sections.append("## Codebase Context\n")
    sections.append("### Project Overview\n")
    sections.append(
        f"{summary.get('total_files', 0)} files, "
        f"{summary.get('total_lines', 0)} lines across "
        f"{len(by_lang)} languages.\n"
    )
    if by_lang:
        lang_lines = []
        for lang, stats in sorted(by_lang.items(), key=lambda x: x[1].get("lines", 0), reverse=True):
            lang_lines.append(f"- {lang}: {stats.get('files', 0)} files, {stats.get('lines', 0)} lines")
        sections.append("\n".join(lang_lines) + "\n")

    # ── Directory Structure ───────────────────────────────
    dirs = project_map.get("directories", [])
    if dirs:
        sections.append("### Directory Structure\n")
        sorted_dirs = sorted(dirs, key=lambda d: d.get("total_lines", 0), reverse=True)
        dir_lines = []
        for d in sorted_dirs[:30]:
            dir_lines.append(f"`{d['path']}`: {d.get('file_count', 0)} files, {d.get('total_lines', 0)} lines")
        sections.append("\n".join(dir_lines) + "\n")

    # ── Structural Conventions ────────────────────────────
    if conventions:
        sections.append(f"### Structural Conventions\n\n{conventions}\n")
        total_budget -= estimate_tokens_from_text(conventions)

    # ── Project Knowledge ─────────────────────────────────
    if project_knowledge:
        sections.append(f"### Project Knowledge\n\n{project_knowledge}\n")
        total_budget -= estimate_tokens_from_text(project_knowledge)

    # ── Project History ───────────────────────────────────
    if learnings:
        sections.append(f"### Project History\n\n{learnings}\n")
        total_budget -= estimate_tokens_from_text(learnings)

    # ── Domain Architecture ───────────────────────────────
    clusters = csg.get("clusters", [])
    # Filter to non-trivial clusters (2+ symbols)
    real_clusters = [c for c in clusters if len(c.get("symbols", [])) >= 2]

    if real_clusters:
        sections.append(f"### Domain Architecture\n")
        sections.append(
            f"The codebase organizes into {len(real_clusters)} domain clusters "
            f"(discovered from code references, not directory structure):\n"
        )

        # Build node lookup for symbol names
        node_lookup = {n["id"]: n for n in csg.get("nodes", [])}

        for cluster in sorted(real_clusters, key=lambda c: len(c.get("symbols", [])), reverse=True)[:20]:
            cid = cluster.get("id", "?")
            label = cluster.get("label", cid)
            files = cluster.get("files", [])
            cohesion = cluster.get("cohesion", 0)
            symbols = cluster.get("symbols", [])

            sections.append(f"**{label}** — {len(files)} files, cohesion: {cohesion:.2f}")

            # Top symbols by centrality
            symbol_nodes = [node_lookup[s] for s in symbols if s in node_lookup]
            top_symbols = sorted(
                symbol_nodes,
                key=lambda n: n.get("impact", {}).get("centrality", 0),
                reverse=True,
            )[:5]
            if top_symbols:
                names = ", ".join(n["name"] for n in top_symbols)
                sections.append(f"  Key symbols: {names}")

            if files:
                sections.append(f"  Files: {', '.join(files[:10])}")

            int_refs = cluster.get("internal_refs", 0)
            ext_refs = cluster.get("external_refs", 0)
            sections.append(f"  Internal references: {int_refs}, External references: {ext_refs}\n")

    # ── Cross-Domain Dependencies ─────────────────────────
    cluster_edges = csg.get("cluster_edges", [])
    if cluster_edges:
        sections.append("### Cross-Domain Dependencies\n")
        sorted_edges = sorted(cluster_edges, key=lambda e: e.get("edge_count", 0), reverse=True)
        for edge in sorted_edges[:20]:
            from_c = edge.get("from", "?")
            to_c = edge.get("to", "?")
            count = edge.get("edge_count", 0)
            sections.append(f"{from_c} → {to_c}: {count} references")
            pairs = edge.get("symbols", [])
            if pairs:
                pair_strs = [f"{p['from'].split('::')[-1]} → {p['to'].split('::')[-1]}" for p in pairs[:3]]
                sections.append(f"  Key connections: {', '.join(pair_strs)}")
        sections.append("")

    # ── High-Impact Symbols ───────────────────────────────
    bridge_symbols = [
        n for n in csg.get("nodes", [])
        if n.get("impact", {}).get("stability") == "bridge"
    ]
    if bridge_symbols:
        # Build node-id → file lookup and reverse-edge index for dependent files
        node_file = {n["id"]: n.get("file", "") for n in csg.get("nodes", [])}
        dependents_by_symbol: dict[str, set[str]] = {}
        for edge in csg.get("edges", []):
            target = edge.get("to", "")
            source_file = node_file.get(edge.get("from", ""), "")
            if target and source_file:
                dependents_by_symbol.setdefault(target, set()).add(source_file)

        sections.append("### High-Impact Symbols (modify with care)\n")
        for sym in sorted(bridge_symbols, key=lambda s: s.get("impact", {}).get("blast_radius", 0), reverse=True)[:15]:
            impact = sym.get("impact", {})
            sym_id = sym["id"]
            dep_files = sorted(dependents_by_symbol.get(sym_id, set()))
            files_str = ", ".join(dep_files) if dep_files else "none"
            sections.append(
                f"`{sym_id}`: {impact.get('dependents', 0)} dependents in {files_str}"
            )
        sections.append("")

    # ── Spec vs. Reality ──────────────────────────────────
    if spec_alignment:
        claims = spec_alignment.get("claims", [])
        if claims:
            confirmed = [c for c in claims if c.get("status") == "confirmed"]
            missing = [c for c in claims if c.get("status") == "missing"]
            divergent = [c for c in claims if c.get("status") == "divergent"]

            sections.append("### Spec vs. Reality\n")

            if confirmed:
                sections.append(f"**Confirmed ({len(confirmed)}):**")
                for c in confirmed[:20]:
                    sections.append(f"- {c.get('claim_text', c.get('entity', ''))}: {c.get('evidence', '')}")
                sections.append("")

            if missing:
                sections.append(f"**Missing ({len(missing)}):**")
                for c in missing:
                    sections.append(f"- {c.get('claim_text', c.get('entity', ''))}: expected but not found")
                sections.append("")

            if divergent:
                sections.append(f"**Divergent ({len(divergent)}):**")
                for c in divergent:
                    sections.append(f"- {c.get('claim_text', c.get('entity', ''))}: {c.get('evidence', '')}")
                sections.append("")

    result = "\n".join(sections)
    return _truncate(result, total_budget, "codebase context")


# ══════════════════════════════════════════════════════════════
# 2. Plan Verifier Assembly
# ══════════════════════════════════════════════════════════════


def assemble_verifier(
    product_spec: str,
    tasks: list[dict],
    cross_cutting_concerns: list[str] | None = None,
    contract: dict | None = None,
    spec_alignment: dict | None = None,
    csg: dict | None = None,
    decomposition_result: dict | None = None,
    config: dict | None = None,
) -> str:
    """Assemble plan verification context for the Plan Verifier.

    Source: Task DAG (from Architect) + Layer 1 (Spec-Alignment, CSG).
    Replaces: Raw concatenation of task descriptions + product spec.

    Args:
        product_spec: full product spec content (ground truth)
        tasks: all tasks in the DAG
        cross_cutting_concerns: feature-level concerns
        contract: contract.json dict
        spec_alignment: spec-alignment.json dict
        csg: semantic-graph.json dict (for cluster mapping)
        decomposition_result: decomposition gate result
        config: speed.toml config

    Returns:
        Markdown string for the Plan Verifier prompt.
    """
    budgets = get_context_budgets(config or {})
    total_budget = budgets.get("verifier", 40000)
    sections = []

    # ── Product Specification ─────────────────────────────
    sections.append("## Product Specification\n")
    sections.append(product_spec + "\n")

    # ── Task Plan ─────────────────────────────────────────
    sections.append("## Task Plan\n")
    for task in tasks:
        tid = task.get("id", "?")
        title = task.get("title", task.get("description", ""))
        sections.append(f"### Task {tid}: {title}\n")
        sections.append(f"**Description:** {task.get('description', '')}\n")

        # Acceptance criteria
        criteria = task.get("acceptance_criteria", [])
        if isinstance(criteria, str):
            criteria = [line.strip() for line in criteria.split('\n') if line.strip()]
        if criteria:
            sections.append("**Acceptance Criteria:**")
            for c in criteria:
                if isinstance(c, dict):
                    sections.append(f"- {c.get('criterion', '')} (verify: {c.get('verify_by', 'manual')})")
                else:
                    sections.append(f"- {c} (verify: manual)")
            sections.append("")

        deps = task.get("depends_on", [])
        if isinstance(deps, str):
            deps = [deps]
        if deps:
            sections.append(f"**Depends On:** {', '.join(deps)}")

        files = task.get("files_touched", [])
        if files:
            sections.append(f"**Files:** {', '.join(files)}")

        rationale = task.get("rationale", "")
        if rationale:
            sections.append(f"**Rationale:** {rationale}")

        assumptions = task.get("assumptions", [])
        if assumptions:
            sections.append("**Assumptions:**")
            for a in assumptions:
                sections.append(f"- {a}")

        spec_refs = task.get("spec_references", [])
        if spec_refs:
            sections.append("**Spec References:**")
            for ref in spec_refs:
                sections.append(f"- {ref.get('spec', '?')} § {ref.get('section', '?')} — {ref.get('requirement', '')}")

        sections.append("")

    # ── Cross-Cutting Concerns ────────────────────────────
    if cross_cutting_concerns:
        sections.append("## Cross-Cutting Concerns\n")
        for concern in cross_cutting_concerns:
            sections.append(f"- {concern}")
        sections.append("")

    # ── Data Model Contract ───────────────────────────────
    if contract:
        sections.append("## Data Model Contract\n")
        sections.append("```json")
        import json
        sections.append(json.dumps(contract, indent=2))
        sections.append("```\n")

    # ── Codebase Reality Check ────────────────────────────
    if spec_alignment:
        claims = spec_alignment.get("claims", [])
        if claims:
            confirmed = [c for c in claims if c.get("status") == "confirmed"]
            missing = [c for c in claims if c.get("status") == "missing"]
            divergent = [c for c in claims if c.get("status") == "divergent"]

            sections.append("## Codebase Reality Check\n")
            sections.append("The following spec claims have been verified against the current codebase:\n")

            if confirmed:
                sections.append(f"**Confirmed ({len(confirmed)}):** {', '.join(c.get('entity', '') for c in confirmed[:20])}")
            if missing:
                sections.append(f"**Missing ({len(missing)})** — these need to be created by the plan:")
                for c in missing:
                    sections.append(f"- {c.get('claim_text', c.get('entity', ''))}")
            if divergent:
                sections.append(f"**Divergent ({len(divergent)})** — these exist but differ from the spec:")
                for c in divergent:
                    sections.append(f"- {c.get('claim_text', c.get('entity', ''))}: {c.get('evidence', '')}")
            sections.append("")

    # ── Decomposition Quality Indicators ──────────────────
    if csg:
        sections.append("## Decomposition Quality Indicators\n")

        # Task-to-cluster mapping
        node_lookup = {n["id"]: n for n in csg.get("nodes", [])}
        symbol_to_cluster = {}
        for cluster in csg.get("clusters", []):
            for sid in cluster.get("symbols", []):
                symbol_to_cluster[sid] = cluster.get("id", "?")

        sections.append("**Task-to-cluster mapping:**")
        for task in tasks:
            tid = task.get("id", "?")
            files = set(task.get("files_touched", []))
            task_clusters = set()
            for node in csg.get("nodes", []):
                if node["file"] in files:
                    c = symbol_to_cluster.get(node["id"])
                    if c:
                        task_clusters.add(c)
            if task_clusters:
                sections.append(f"- Task {tid} touches clusters: {', '.join(sorted(task_clusters))}")
        sections.append("")

        # Cross-task coordination points
        from collections import defaultdict
        file_to_tasks: dict[str, list[str]] = defaultdict(list)
        for task in tasks:
            tid = task.get("id", "?")
            for f in task.get("files_touched", []):
                file_to_tasks[f].append(tid)

        overlaps = {f: tids for f, tids in file_to_tasks.items() if len(tids) >= 2}
        if overlaps:
            sections.append(f"**Cross-task coordination points:** {len(overlaps)} shared files")
            for f, tids in sorted(overlaps.items()):
                sections.append(f"- `{f}`: {', '.join(tids)}")
            sections.append("")

    # ── Decomposition Gate Results ────────────────────────
    if decomposition_result:
        checks = decomposition_result.get("checks", [])
        failures = [c for c in checks if c.get("status") == "fail"]
        warnings = [c for c in checks if c.get("status") == "warn"]
        if failures or warnings:
            sections.append("## Decomposition Gate Results\n")
            for c in failures:
                sections.append(f"- FAIL: {c.get('check', '?')} — {c.get('message', '')}")
            for c in warnings:
                sections.append(f"- WARN: {c.get('check', '?')} — {c.get('message', '')}")
            sections.append("")

    result = "\n".join(sections)
    return _truncate(result, total_budget, "verifier context")


# ══════════════════════════════════════════════════════════════
# 3. Developer Assembly
# ══════════════════════════════════════════════════════════════


def assemble_developer(
    task: dict,
    code_context: dict,
    task_context: dict,
    spec_context: dict,
    budget: dict | None = None,
    cross_cutting_concerns: list[str] | None = None,
    branch_name: str = "",
    worktree_path: str = "",
    feature_name: str = "",
    config: dict | None = None,
    learnings: str = "",
    conventions: str = "",
    project_knowledge: str = "",
) -> str:
    """Assemble developer prompt from Layer 2 context package.

    Source: Layer 2 full context package.
    Replaces: Flat task description + files_touched list in cmd_run.

    Args:
        task: task dict with all fields
        code_context: code-context.json dict
        task_context: task-context.json dict
        spec_context: spec-context.json dict
        budget: budget.json dict (for information)
        cross_cutting_concerns: feature-level concerns
        branch_name: git branch name
        worktree_path: path to isolated worktree
        feature_name: feature name (for gate commands)
        config: speed.toml config

    Returns:
        Markdown string for the Developer prompt.
    """
    budgets = get_context_budgets(config or {})
    total_budget = budgets.get("developer", 80000)
    sections = []

    tid = task.get("id", "?")
    title = task.get("title", task.get("description", ""))

    # ── Task Identity ─────────────────────────────────────
    sections.append(f"## Task: {title}\n")

    rationale = task.get("rationale", "")
    if rationale:
        sections.append(f"### Why This Task\n{rationale}\n")

    sections.append(f"### Description\n{task.get('description', '')}\n")

    # ── Acceptance Criteria ───────────────────────────────
    criteria = task.get("acceptance_criteria", [])
    if isinstance(criteria, str):
        criteria = [line.strip() for line in criteria.split('\n') if line.strip()]
    if criteria:
        sections.append("### Acceptance Criteria")
        for c in criteria:
            if isinstance(c, dict):
                sections.append(f"- [ ] {c.get('criterion', '')} (verify: {c.get('verify_by', 'manual')})")
            else:
                sections.append(f"- [ ] {c} (verify: manual)")
        sections.append("")

    # ── Review Feedback ──────────────────────────────────
    review_feedback = task.get("review_feedback")
    if review_feedback and task.get("review_verdict") == "request_changes":
        sections.append("### Previous Review Feedback")
        sections.append("The reviewer requested changes. Address each item:\n")
        if isinstance(review_feedback, dict):
            for issue in review_feedback.get("issues", []):
                sev = issue.get("severity", "?")
                msg = issue.get("message", issue.get("description", ""))
                loc = issue.get("file", "")
                if loc:
                    line = issue.get("line", "")
                    loc_str = f" (`{loc}:{line}`)" if line else f" (`{loc}`)"
                else:
                    loc_str = ""
                sections.append(f"- **[{sev}]** {msg}{loc_str}")
            summary = review_feedback.get("summary", "")
            if summary:
                sections.append(f"\nReviewer summary: {summary}")
        elif isinstance(review_feedback, str):
            sections.append(review_feedback)
        sections.append("")

    # ── Assumptions ───────────────────────────────────────
    assumptions = task.get("assumptions", [])
    if assumptions:
        sections.append("### Assumptions (verify these hold)")
        sections.append("These were inferred during planning where the spec was ambiguous:")
        for a in assumptions:
            sections.append(f"- {a}")
        sections.append("")

    # ── Cross-Cutting Constraints ─────────────────────────
    if cross_cutting_concerns:
        sections.append("### Cross-Cutting Constraints")
        for concern in cross_cutting_concerns:
            sections.append(f"- {concern}")
        sections.append("")

    # ── Project Conventions ───────────────────────────────
    if conventions:
        sections.append(f"### Project Conventions\n\n{conventions}\n")
        total_budget -= estimate_tokens_from_text(conventions)

    # ── Project Knowledge ─────────────────────────────────
    if project_knowledge:
        sections.append(f"### Project Knowledge\n\n{project_knowledge}\n")
        total_budget -= estimate_tokens_from_text(project_knowledge)

    # ── Learned Patterns ──────────────────────────────────
    if learnings:
        sections.append(f"### Learned Patterns\n\n{learnings}\n")
        total_budget -= estimate_tokens_from_text(learnings)

    # ── Files You'll Modify (Tier 0) ──────────────────────
    ft = code_context.get("full_content", {}).get("files_touched", [])
    if ft:
        sections.append("### Files You'll Modify")
        for entry in ft:
            path = entry.get("path", "?")
            content = entry.get("content", "")
            lines = content.count("\n") + 1
            lang = _lang_for_path(path)
            sections.append(f"#### `{path}` ({lines} lines)")
            sections.append(f"```{lang}")
            sections.append(content)
            sections.append("```\n")

    # ── Related Code (Tier 1 — 1-hop) ────────────────────
    oh = code_context.get("full_content", {}).get("one_hop", [])
    if oh:
        sections.append("### Related Code (direct dependencies)")
        for entry in oh:
            path = entry.get("path", "?")
            content = entry.get("content", "")
            rel = entry.get("relationship", "")
            lang = _lang_for_path(path)
            suffix = f" — {rel}" if rel else ""
            sections.append(f"#### `{path}`{suffix}")
            sections.append(f"```{lang}")
            sections.append(content)
            sections.append("```\n")

    # ── Nearby Code (Tier 2 — skeleton) ──────────────────
    th = code_context.get("skeleton", {}).get("two_hop", [])
    if th:
        sections.append("### Nearby Code (interfaces only)")
        for entry in th:
            path = entry.get("path", "?")
            skeleton = entry.get("skeleton_content", "")
            rel = entry.get("relationship", "")
            lang = _lang_for_path(path)
            suffix = f" — {rel}" if rel else ""
            sections.append(f"#### `{path}`{suffix}")
            sections.append(f"```{lang}")
            sections.append(skeleton)
            sections.append("```\n")

    # ── Context from Completed Dependencies ───────────────
    upstream = task_context.get("upstream", [])
    if upstream:
        sections.append("### Context from Completed Dependencies")
        for dep in upstream:
            dep_id = dep.get("task_id", "?")
            dep_title = dep.get("title", "")
            sections.append(f"#### Task {dep_id}: {dep_title}")

            files_mod = dep.get("files_modified", [])
            if files_mod:
                sections.append(f"Files modified: {', '.join(files_mod)}")

            decisions = dep.get("decisions", [])
            if decisions:
                sections.append("Decisions:")
                for d in decisions:
                    sections.append(f"- {d}")

            concerns = dep.get("concerns", [])
            if concerns:
                sections.append("Concerns:")
                for c in concerns:
                    sections.append(f"- {c}")
            sections.append("")

    # ── Downstream Awareness ──────────────────────────────
    downstream = task_context.get("downstream", [])
    if downstream:
        sections.append("### What Depends on You")
        for dep in downstream:
            dep_id = dep.get("task_id", "?")
            dep_title = dep.get("title", "")
            expect = dep.get("depends_on_me_for", "")
            sections.append(f"- Task {dep_id} ({dep_title}): expects {expect}")
        sections.append("")

    # ── Sibling-Owned Files ─────────────────────────────
    sibling_files = task_context.get("sibling_owned_files", {})
    if sibling_files:
        sections.append("### Files Owned by Other Tasks")
        sections.append(
            "Do not create or modify these files. They belong to sibling tasks "
            "and will trigger a scope violation.\n"
        )
        by_task: dict[str, list[str]] = {}
        for f, owner_tid in sibling_files.items():
            by_task.setdefault(owner_tid, []).append(f)
        for owner_tid, files in sorted(by_task.items()):
            file_list = ", ".join(f"`{f}`" for f in sorted(files))
            sections.append(f"- Task {owner_tid}: {file_list}")
        sections.append("")

    # ── Warnings ──────────────────────────────────────────
    warnings = task_context.get("shared_scope_warnings", [])
    if warnings:
        sections.append("### Warnings")
        for w in warnings:
            symbol = w.get("symbol", "?")
            also = w.get("also_modified_by", [])
            impact = w.get("impact", {})
            sections.append(
                f"- `{symbol}` is also modified by Task {', '.join(also)}.\n"
                f"  Impact: blast_radius={impact.get('blast_radius', 0)}, "
                f"stability={impact.get('stability', 'unknown')}.\n"
                f"  {w.get('warning', '')}"
            )
        sections.append("")

    # ── Spec Requirements ─────────────────────────────────
    spec_sections = spec_context.get("relevant_spec_sections", [])
    if spec_sections:
        sections.append("### Spec Requirements")
        for s in spec_sections:
            source = s.get("source", {})
            spec_name = source.get("spec", source.get("file", "?"))
            section_name = source.get("section", "?")
            content = s.get("content", "")
            sections.append(f"From {spec_name} § {section_name}:")
            sections.append(f"> {content}\n")
        sections.append("")

    # ── Codebase Status ───────────────────────────────────
    alignment = spec_context.get("alignment_status", [])
    if alignment:
        sections.append("### Codebase Status")
        for a in alignment:
            sections.append(f"- {a.get('claim', '?')}: {a.get('status', '?')} — {a.get('evidence', '')}")
        sections.append("")

    # ── Operational ───────────────────────────────────────
    if branch_name:
        sections.append(f"### Git Branch\nYou are working on branch: `{branch_name}`")
        sections.append("You are already on this branch in an isolated worktree.\n")

    speed_cmd = os.environ.get("SPEED_CMD", "./speed")
    feature_flag = f" -f {feature_name}" if feature_name else ""
    sections.append("### Quality Checks")
    sections.append(f"- After each group of files: `{speed_cmd} gates{feature_flag} --task {tid} --fast`")
    sections.append(f"- Before declaring done: `{speed_cmd} gates{feature_flag} --task {tid} --full`\n")

    if worktree_path:
        sections.append(f"### Working Directory\n`{worktree_path}`\n")

    result = "\n".join(sections)
    return _truncate(result, total_budget, "developer context")


# ══════════════════════════════════════════════════════════════
# 4. Reviewer Assembly
# ══════════════════════════════════════════════════════════════


def assemble_reviewer(
    task: dict,
    diff: str,
    task_context: dict,
    spec_context: dict,
    csg: dict | None = None,
    cross_cutting_concerns: list[str] | None = None,
    criteria_results: list[dict] | None = None,
    config: dict | None = None,
    learnings: str = "",
    conventions: str = "",
    project_knowledge: str = "",
) -> str:
    """Assemble review context from Layer 2 + git diff.

    Source: Layer 2 context package (narrowed) + git diff.
    Replaces: Diff + full product spec concatenation in cmd_review.

    Args:
        task: task dict
        diff: git diff string
        task_context: task-context.json dict
        spec_context: spec-context.json dict
        csg: semantic-graph.json dict (for impact assessment)
        cross_cutting_concerns: feature-level concerns
        criteria_results: output from criteria_verify (if run)
        config: speed.toml config

    Returns:
        Markdown string for the Reviewer prompt.
    """
    budgets = get_context_budgets(config or {})
    total_budget = budgets.get("reviewer", 60000)
    sections = []

    tid = task.get("id", "?")
    title = task.get("title", task.get("description", ""))

    sections.append(f"## Review: Task {tid} — {title}\n")

    # ── What This Task Should Achieve ─────────────────────
    rationale = task.get("rationale", "")
    if rationale:
        sections.append(f"### What This Task Should Achieve\n{rationale}\n")

    # ── Acceptance Criteria ───────────────────────────────
    criteria = task.get("acceptance_criteria", [])
    if isinstance(criteria, str):
        criteria = [line.strip() for line in criteria.split('\n') if line.strip()]
    if criteria:
        sections.append("### Acceptance Criteria\n")
        sections.append("| # | Criterion | Verify By |")
        sections.append("|---|---|---|")
        for i, c in enumerate(criteria, 1):
            if isinstance(c, dict):
                sections.append(f"| {i} | {c.get('criterion', '')} | {c.get('verify_by', 'manual')} |")
            else:
                sections.append(f"| {i} | {c} | manual |")
        sections.append("")

    # ── Task File Scope ──────────────────────────────────
    files_touched = task.get("files_touched", [])
    if files_touched:
        sections.append("### Task File Scope")
        sections.append("This task owns these files. Issues in other files belong to other tasks — report those in `out_of_scope`, not `issues`:")
        for f in files_touched:
            sections.append(f"- `{f}`")
        sections.append("")

    # ── Criteria Verification Results (if available) ──────
    if criteria_results:
        sections.append("### Automated Verification Results")
        for cr in criteria_results:
            status = cr.get("status", "?")
            icon = {"pass": "PASS", "fail": "FAIL", "unverifiable": "SKIP"}.get(status, "?")
            sections.append(f"- [{icon}] {cr.get('criterion', '?')}: {cr.get('evidence', '')}")
        sections.append("")

    # ── Assumptions to Verify ─────────────────────────────
    assumptions = task.get("assumptions", [])
    if assumptions:
        sections.append("### Assumptions to Verify")
        sections.append("These were NOT in the spec — they were inferred during planning:")
        for a in assumptions:
            sections.append(f"- {a}")
        sections.append("")

    # ── Convention Checklist ──────────────────────────────
    if conventions:
        sections.append(f"### Convention Checklist\n\n{conventions}\n")
        total_budget -= estimate_tokens_from_text(conventions)

    # ── Project Knowledge ─────────────────────────────────
    if project_knowledge:
        sections.append(f"### Project Knowledge\n\n{project_knowledge}\n")
        total_budget -= estimate_tokens_from_text(project_knowledge)

    # ── Review Calibration ────────────────────────────────
    if learnings:
        sections.append(f"### Review Calibration\n\n{learnings}\n")
        total_budget -= estimate_tokens_from_text(learnings)

    # ── Git Diff ──────────────────────────────────────────
    # Allocate ~40% of budget to diff
    diff_budget = int(total_budget * 0.4)
    sections.append("### Git Diff\n")
    sections.append("```diff")
    sections.append(_truncate_diff(diff, diff_budget))
    sections.append("```\n")

    # ── Impact Assessment ─────────────────────────────────
    if csg and diff:
        changed_files = _extract_diff_files(diff)
        impacted_symbols = []
        for node in csg.get("nodes", []):
            if node["file"] in changed_files:
                impact = node.get("impact", {})
                if impact.get("blast_radius", 0) >= 5 or impact.get("stability") == "bridge":
                    impacted_symbols.append(node)

        if impacted_symbols:
            sections.append("### Impact Assessment\n")
            sections.append("| Symbol | Blast Radius | Stability | Dependents |")
            sections.append("|---|---|---|---|")
            for sym in sorted(impacted_symbols, key=lambda s: s.get("impact", {}).get("blast_radius", 0), reverse=True)[:20]:
                impact = sym.get("impact", {})
                sections.append(
                    f"| `{sym['name']}` | {impact.get('blast_radius', 0)} | "
                    f"{impact.get('stability', '?')} | {impact.get('dependents', 0)} |"
                )
            sections.append("")

            bridge_syms = [s for s in impacted_symbols if s.get("impact", {}).get("stability") == "bridge"]
            if bridge_syms:
                sections.append("**Bridge symbols modified** — verify downstream consumers:")
                for sym in bridge_syms:
                    deps = sym.get("impact", {}).get("dependent_list", [])
                    sections.append(f"- `{sym['name']}`: consumed by {', '.join(deps[:10]) if deps else 'unknown'}")
                sections.append("")

    # ── Spec Requirements ─────────────────────────────────
    spec_sections = spec_context.get("relevant_spec_sections", [])
    if spec_sections:
        sections.append("### Spec Requirements")
        for s in spec_sections:
            source = s.get("source", {})
            spec_name = source.get("spec", source.get("file", "?"))
            section_name = source.get("section", "?")
            content = s.get("content", "")
            sections.append(f"**{spec_name} § {section_name}:**")
            sections.append(f"> {content}\n")

        alignment = spec_context.get("alignment_status", [])
        if alignment:
            sections.append("Codebase status:")
            for a in alignment:
                sections.append(f"- {a.get('claim', '?')} → {a.get('status', '?')}")
            sections.append("")

    # ── Cross-Cutting Constraints ─────────────────────────
    if cross_cutting_concerns:
        sections.append("### Cross-Cutting Constraints")
        sections.append("Verify the diff respects these:")
        for concern in cross_cutting_concerns:
            sections.append(f"- {concern}")
        sections.append("")

    # ── Instructions ──────────────────────────────────────
    sections.append("### Instructions")
    sections.append("1. Check each acceptance criterion against the diff")
    sections.append("2. Verify assumptions are reasonable")
    sections.append("3. Check impact — bridge symbols need downstream verification")
    sections.append("4. Verify cross-cutting constraints are followed")
    sections.append("5. Standard code review (quality, security, conventions)\n")

    result = "\n".join(sections)
    return _truncate(result, total_budget, "reviewer context")


# ══════════════════════════════════════════════════════════════
# 5. Coherence Checker Assembly
# ══════════════════════════════════════════════════════════════


def assemble_coherence(
    cross_task_analysis: dict,
    completed_tasks: list[dict],
    task_diffs: dict[str, str],
    product_spec: str = "",
    contract: dict | None = None,
    config: dict | None = None,
    learnings: str = "",
) -> str:
    """Assemble coherence check context from cross-task analysis + diffs.

    Source: Layer 2 cross-task analysis + all task diffs + contract.
    Replaces: All-diffs + full-spec + contract concatenation in cmd_coherence.

    Args:
        cross_task_analysis: cross-task-analysis.json dict
        completed_tasks: list of completed task dicts
        task_diffs: {task_id: diff_string}
        product_spec: full product spec content
        contract: contract.json dict
        config: speed.toml config

    Returns:
        Markdown string for the Coherence Checker prompt.
    """
    budgets = get_context_budgets(config or {})
    total_budget = budgets.get("coherence", 100000)
    sections = []

    sections.append(f"## Coherence Check: {len(completed_tasks)} completed tasks\n")

    # ── Cross-Task Risk Analysis ──────────────────────────
    sections.append("### Cross-Task Risk Analysis\n")

    # Domain Overlap
    overlaps = cross_task_analysis.get("domain_overlap", [])
    if overlaps:
        sections.append("#### Domain Overlap\n")
        for o in overlaps:
            cluster = o.get("cluster", o.get("file", "?"))
            tasks_touching = o.get("tasks_touching", [])
            shared_symbols = o.get("shared_symbols", [])
            coord_edges = o.get("coordination_edges", 0)
            risk = o.get("risk", "?")

            sections.append(f"**{cluster}** — touched by tasks: {', '.join(tasks_touching)}")
            if shared_symbols:
                sections.append(f"  Shared symbols: {', '.join(shared_symbols[:10])}")
            if coord_edges:
                sections.append(f"  Coordination edges: {coord_edges}")
            sections.append(f"  Risk: {risk}\n")

    # Interface Boundaries
    boundaries = cross_task_analysis.get("interface_boundaries", [])
    if boundaries:
        sections.append("#### Interface Boundaries\n")
        for b in boundaries:
            from_t = b.get("from_task", "?")
            to_t = b.get("to_task", "?")
            symbols = b.get("interface_symbols", [])
            sections.append(f"Task {from_t} → Task {to_t}:")
            for sym in symbols[:10]:
                sections.append(f"  {sym.get('symbol', '?')}")
            sections.append("")

    # High-Impact Modifications
    high_impact = cross_task_analysis.get("high_impact_modifications", [])
    if high_impact:
        sections.append("#### High-Impact Modifications\n")
        for h in high_impact:
            symbol = h.get("symbol", "?")
            mod_by = h.get("modified_by", "?")
            blast = h.get("blast_radius", 0)
            centrality = h.get("centrality", 0)
            stability = h.get("stability", "?")
            consumers = h.get("downstream_consumers", [])
            sections.append(
                f"`{symbol}` (modified by Task {mod_by}):\n"
                f"  blast_radius={blast}, centrality={centrality:.3f}, stability={stability}"
            )
            if consumers:
                sections.append(f"  Downstream consumers in other tasks: {', '.join(consumers)}")
            sections.append("")

    # ── Integration History ───────────────────────────────
    if learnings:
        sections.append(f"### Integration History\n\n{learnings}\n")
        total_budget -= estimate_tokens_from_text(learnings)

    # ── All Task Diffs ────────────────────────────────────
    # Allocate ~50% of budget to diffs
    diff_budget = int(total_budget * 0.5)
    per_task_budget = diff_budget // max(len(task_diffs), 1)

    sections.append("### All Task Diffs\n")
    for task in completed_tasks:
        tid = task.get("id", "?")
        title = task.get("title", task.get("description", ""))
        files = task.get("files_touched", [])
        diff = task_diffs.get(tid, "")

        sections.append(f"--- TASK {tid}: {title} ---")
        sections.append(f"Files: {', '.join(files)}")
        sections.append("```diff")
        sections.append(_truncate_diff(diff, per_task_budget))
        sections.append("```\n")

    # ── Product Specification ─────────────────────────────
    if product_spec:
        sections.append("### Product Specification\n")
        sections.append(product_spec + "\n")

    # ── Data Model Contract ───────────────────────────────
    if contract:
        sections.append("### Data Model Contract\n")
        sections.append("```json")
        import json
        sections.append(json.dumps(contract, indent=2))
        sections.append("```\n")

    # ── Instructions ──────────────────────────────────────
    sections.append("### Instructions")
    sections.append("The analysis above identifies the highest-risk integration points.")
    sections.append("Focus on:")
    sections.append("1. Interface mismatches at the boundaries identified above")
    sections.append("2. Schema consistency across tasks that touch the same domain")
    sections.append("3. Contract compliance — do all declared entities and relationships exist?")
    sections.append("4. Naming consistency, duplicate logic, missing connections\n")

    result = "\n".join(sections)
    return _truncate(result, total_budget, "coherence context")


# ══════════════════════════════════════════════════════════════
# 6. Debugger Assembly
# ══════════════════════════════════════════════════════════════


def assemble_debugger(
    task: dict,
    budget: dict,
    agent_output: str = "",
    diff: str = "",
    code_context: dict | None = None,
    failure_classification: dict | None = None,
    config: dict | None = None,
    learnings: str = "",
) -> str:
    """Assemble debug context for the Debugger agent.

    Source: Layer 2 budget.json + task context + error logs + diff.
    Replaces: Task description + error logs + diff in _invoke_debugger.

    Args:
        task: task dict
        budget: budget.json dict
        agent_output: agent output log (may be long)
        diff: git diff from failed attempt
        code_context: code-context.json dict (for relevant code)
        failure_classification: pre-computed failure classification (if available)
        config: speed.toml config

    Returns:
        Markdown string for the Debugger prompt.
    """
    budgets = get_context_budgets(config or {})
    total_budget = budgets.get("debugger", 50000)
    sections = []

    tid = task.get("id", "?")
    title = task.get("title", task.get("description", ""))

    sections.append(f"## Failed Task {tid}: {title}\n")

    # ── Failure Classification (if available) ─────────────
    if failure_classification:
        fc = failure_classification
        sections.append("### Failure Classification\n")
        sections.append(f"**Class:** {fc.get('class', '?')}")
        sections.append(f"**Subclass:** {fc.get('subclass', '?')}")
        sections.append(f"**Evidence:** {fc.get('evidence', '')}\n")

    # ── Known Failure Patterns ────────────────────────────
    if learnings:
        sections.append(f"### Known Failure Patterns\n\n{learnings}\n")
        total_budget -= estimate_tokens_from_text(learnings)

    # ── Context Budget Analysis ───────────────────────────
    sections.append("### Context Budget Analysis\n")
    sections.append(f"Total budget: {budget.get('total_budget', '?')} tokens")

    allocated = budget.get("allocated", {})
    code_alloc = allocated.get("code_context", {})
    if isinstance(code_alloc, dict):
        sections.append(
            f"Code context: {code_alloc.get('used', '?')}/{code_alloc.get('budget', '?')} "
            f"({code_alloc.get('files_full', 0)} full, {code_alloc.get('files_skeleton', 0)} skeleton, "
            f"{code_alloc.get('files_dropped', 0)} dropped)"
        )

    cuts = budget.get("cuts_made", [])
    if cuts:
        sections.append(f"\n**Context was cut — potential pipeline failure:**")
        for cut in cuts:
            sections.append(
                f"- `{cut.get('file', '?')}`: {cut.get('original_tier', '?')} → "
                f"{cut.get('downgraded_to', '?')} ({cut.get('reason', '')})"
            )
        sections.append(
            "\nIf the failure involves symbols from these files, the root cause "
            "may be insufficient context, not a task complexity problem."
        )
    sections.append("")

    # ── Task Description ──────────────────────────────────
    sections.append(f"### Task Description\n{task.get('description', '')}\n")

    # ── Acceptance Criteria ───────────────────────────────
    criteria = task.get("acceptance_criteria", [])
    if isinstance(criteria, str):
        criteria = [line.strip() for line in criteria.split('\n') if line.strip()]
    if criteria:
        sections.append("### Acceptance Criteria")
        for c in criteria:
            if isinstance(c, dict):
                sections.append(f"- {c.get('criterion', '')} (verify: {c.get('verify_by', 'manual')})")
            else:
                sections.append(f"- {c} (verify: manual)")
        sections.append("")

    # ── Agent Output ──────────────────────────────────────
    if agent_output:
        # Allocate ~20% of budget to agent output
        output_budget = int(total_budget * 0.2)
        sections.append("### Agent Output\n")
        sections.append(_truncate(agent_output, output_budget, "agent output"))
        sections.append("")

    # ── Git Diff ──────────────────────────────────────────
    if diff:
        diff_budget = int(total_budget * 0.2)
        sections.append("### Git Diff\n")
        sections.append("```diff")
        sections.append(_truncate_diff(diff, diff_budget))
        sections.append("```\n")

    # ── Relevant Code Context ─────────────────────────────
    if code_context:
        oh = code_context.get("full_content", {}).get("one_hop", [])
        if oh:
            code_budget = int(total_budget * 0.25)
            sections.append("### Relevant Code Context\n")
            accumulated = 0
            for entry in oh:
                path = entry.get("path", "?")
                content = entry.get("content", "")
                tokens = estimate_tokens_from_text(content)
                if accumulated + tokens > code_budget:
                    sections.append(f"\n[Remaining {len(oh) - oh.index(entry)} files omitted for budget]")
                    break
                lang = _lang_for_path(path)
                rel = entry.get("relationship", "")
                suffix = f" — {rel}" if rel else ""
                sections.append(f"#### `{path}`{suffix}")
                sections.append(f"```{lang}")
                sections.append(content)
                sections.append("```\n")
                accumulated += tokens

    sections.append("Diagnose why this task failed and classify the failure.\n")

    result = "\n".join(sections)
    return _truncate(result, total_budget, "debugger context")


# ── Helpers ───────────────────────────────────────────────────


def _extract_diff_files(diff: str) -> set[str]:
    """Extract file paths from a git diff string."""
    files = set()
    for line in diff.splitlines():
        if line.startswith("+++ b/") or line.startswith("--- a/"):
            path = line[6:]
            if path and path != "/dev/null":
                files.add(path)
    return files
