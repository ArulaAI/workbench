"""Synthesis pipeline: observations → agent-specific learnings files.

Reads observation JSONL files, routes observations to agent-specific
learnings files, deduplicates, and truncates to budget. Observations
pass through with their original detail dicts intact.

No LLM calls. Deterministic and testable.
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .extract import Observation


# ── Data classes ──────────────────────────────────────────────────────


@dataclass
class Evidence:
    observation_id: str
    feature: str


@dataclass
class LearningsEntry:
    id: str
    observation_type: str
    detail: dict
    files: list[str]
    weight: float
    source: str                  # "direct" | "cross_agent"
    reframing_context: str       # "" for direct, tag for cross-agent
    agent: str                   # target agent
    evidence: list[Evidence]
    created: str
    stale: bool = False
    rejection_reason: str = ""


@dataclass
class Conflict:
    entry_a_id: str
    entry_b_id: str
    reason: str
    resolution: str | None = None


@dataclass
class SynthesisMeta:
    last_run: str
    features_processed: list[str]
    observation_hash: str
    entry_counts: dict[str, int]
    rejected: int
    conflicts: int


@dataclass
class SynthesisResult:
    entries_by_agent: dict[str, list[LearningsEntry]]
    rejects: list[LearningsEntry]
    conflicts: list[Conflict]
    meta: SynthesisMeta
    skipped: bool = False

    def summary(self) -> str:
        if self.skipped:
            return "Synthesis skipped (observations unchanged)."
        lines = ["Synthesis complete."]
        for agent in sorted(self.entries_by_agent):
            entries = self.entries_by_agent[agent]
            count = len(entries)
            tokens = sum(len(json.dumps(e.detail)) // 4 for e in entries)
            budget = _TOKEN_BUDGETS.get(agent, 1000)
            unit = "entry" if count == 1 else "entries"
            lines.append(
                f"  {agent}: {count} {unit} "
                f"({tokens} tokens / {budget} budget)"
            )
        if self.rejects:
            lines.append(
                f"  rejected: {len(self.rejects)} entries "
                f"(see synthesis-rejects.json)"
            )
        else:
            lines.append("  rejected: 0")
        lines.append(f"  conflicts: {len(self.conflicts)}")
        return "\n".join(lines)


# ── Constants ─────────────────────────────────────────────────────────


_AGENT_ROUTING: dict[str, str] = {
    "retry": "developer",
    "gate_failure": "developer",
    "agent_concern": "developer",
    "security_finding": "developer",
    "reviewer_finding": "reviewer",
    "guardian_verdict": "guardian",
    "verify_finding": "architect",
    "decomposition_miss": "architect",
    "coherence_issue": "coherence",
    "context_miss": "developer",
    "context_waste": "developer",
    "human_override": "developer",
    "human_approved": "developer",
}


# (obs_type, condition_fn_or_None, target_agent, reframing_context)
# Only cross-boundary rules are included. Same-agent rules are skipped
# because without templates the detail dict is identical to the direct
# entry, and dedup would merge them anyway.
_REFRAMING_RULES: list[tuple] = [
    ("retry", None, "architect", "downstream_feedback"),
    ("retry", None, "reviewer", "upstream_awareness"),
    (
        "reviewer_finding",
        lambda d: d.get("confirmed", False),
        "developer",
        "known_pitfall",
    ),
    (
        "guardian_verdict",
        lambda d: str(d.get("verdict", "")).lower()
        in ("pass", "accept", "in_scope"),
        "reviewer",
        "missed_scope_issue",
    ),
    ("gate_failure", None, "architect", "gate_failure_signal"),
    (
        "human_override",
        lambda d: d.get("change_type") in ("transformative", "additive"),
        "reviewer",
        "missed_by_review",
    ),
]


_TOKEN_BUDGETS: dict[str, int] = {
    "developer": 3000,
    "architect": 3000,
    "reviewer": 2000,
    "guardian": 1000,
    "coherence": 1000,
    "debugger": 1000,
}

_EXCLUDED_TYPES = frozenset({"success", "pattern_match"})

_CONTRADICTION_PAIRS = frozenset({
    frozenset({"context_miss", "context_waste"}),
})


# ── Helpers ───────────────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _observation_hash(observations: list[Observation]) -> str:
    ids = sorted(o.id for o in observations)
    payload = "\n".join(ids)
    digest = hashlib.sha256(payload.encode()).hexdigest()
    return f"sha256:{digest}"


def _extract_files(detail: dict) -> list[str]:
    """Extract file paths from observation detail dict."""
    files: list[str] = []
    for key in ("files_involved", "file", "planned_files", "actual_files"):
        val = detail.get(key)
        if isinstance(val, list):
            files.extend(str(f) for f in val if f)
        elif isinstance(val, str) and val:
            files.append(val)
    return sorted(set(files))


def _file_overlap(files_a: list[str], files_b: list[str]) -> float:
    """Jaccard similarity of two file lists.

    Returns 0.0 when both lists are empty — entries without file scope
    are distinct signals that should not be merged by dedup.
    """
    set_a, set_b = set(files_a), set(files_b)
    if not set_a and not set_b:
        return 0.0
    union = set_a | set_b
    if not union:
        return 0.0
    return len(set_a & set_b) / len(union)


def _cross_agent_id(obs_id: str, target_agent: str) -> str:
    payload = f"{obs_id}\n{target_agent}"
    digest = hashlib.sha256(payload.encode()).hexdigest()
    return f"sha256:{digest}"


def _entry_to_dict(entry: LearningsEntry) -> dict:
    d: dict = {
        "id": entry.id,
        "observation_type": entry.observation_type,
        "detail": entry.detail,
        "files": entry.files,
        "weight": entry.weight,
        "source": entry.source,
        "reframing_context": entry.reframing_context,
        "evidence": [
            {"observation_id": ev.observation_id, "feature": ev.feature}
            for ev in entry.evidence
        ],
        "created": entry.created,
        "stale": entry.stale,
    }
    if entry.rejection_reason:
        d["rejection_reason"] = entry.rejection_reason
    return d


# ── Pipeline steps ────────────────────────────────────────────────────


def _read_all_observations(obs_dir: Path) -> tuple[list[Observation], list[str]]:
    """Step 1: Read all observation JSONL files.

    Returns (observations, warnings). Excludes success and pattern_match.
    """
    observations: list[Observation] = []
    warnings: list[str] = []

    if not obs_dir.exists():
        return observations, warnings

    for jsonl_file in sorted(obs_dir.glob("*.jsonl")):
        with open(jsonl_file, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    obs = Observation(
                        id=obj["id"],
                        feature=obj["feature"],
                        stage=obj["stage"],
                        task_id=obj["task_id"],
                        timestamp=obj["timestamp"],
                        observation_type=obj["observation_type"],
                        detail=obj["detail"],
                        weight=obj["weight"],
                    )
                    if obs.observation_type in _EXCLUDED_TYPES:
                        continue
                    observations.append(obs)
                except (json.JSONDecodeError, KeyError, TypeError) as exc:
                    warnings.append(
                        f"{jsonl_file.name}:{line_num}: {exc}"
                    )

    observations.sort(key=lambda o: o.timestamp)
    return observations, warnings


def _build_entries(
    observations: list[Observation],
) -> dict[str, list[LearningsEntry]]:
    """Steps 2-3: Route observations to agents and build entries.

    Detail dict passes through unchanged. Files list extracted from detail.
    """
    entries_by_agent: dict[str, list[LearningsEntry]] = {}
    for obs in observations:
        agent = _AGENT_ROUTING.get(obs.observation_type)
        if agent is None:
            continue
        # Human corrections carry their own agent attribution
        if obs.observation_type == "human_override":
            attr = obs.detail.get("agent_attribution", [])
            if attr:
                agent = attr[0]
        entry = LearningsEntry(
            id=obs.id,
            observation_type=obs.observation_type,
            detail=obs.detail,
            files=_extract_files(obs.detail),
            weight=obs.weight,
            source="direct",
            reframing_context="",
            agent=agent,
            evidence=[Evidence(obs.id, obs.feature)],
            created=obs.timestamp,
        )
        entries_by_agent.setdefault(agent, []).append(entry)
    return entries_by_agent


def _cross_agent_reframe(
    entries_by_agent: dict[str, list[LearningsEntry]],
) -> None:
    """Step 4: Produce secondary entries for other agents.

    Only fires for cross-boundary rules (target != primary agent).
    Same-agent rules are skipped: without templates, the detail dict
    is identical and dedup would merge the duplicate.
    """
    new_entries: list[LearningsEntry] = []

    # Track existing cross-agent IDs for idempotency
    existing_ids: set[str] = set()
    for entries in entries_by_agent.values():
        for e in entries:
            if e.source == "cross_agent":
                existing_ids.add(e.id)

    for agent, entries in list(entries_by_agent.items()):
        for entry in list(entries):
            if entry.source != "direct":
                continue
            for obs_type, condition, target_agent, context in _REFRAMING_RULES:
                if entry.observation_type != obs_type:
                    continue
                if target_agent == agent:
                    continue
                if condition is not None and not condition(entry.detail):
                    continue
                new_id = _cross_agent_id(entry.id, target_agent)
                if new_id in existing_ids:
                    continue
                existing_ids.add(new_id)
                new_entry = LearningsEntry(
                    id=new_id,
                    observation_type=entry.observation_type,
                    detail=entry.detail,
                    files=entry.files[:],
                    weight=entry.weight,
                    source="cross_agent",
                    reframing_context=context,
                    agent=target_agent,
                    evidence=[
                        Evidence(
                            entry.evidence[0].observation_id,
                            entry.evidence[0].feature,
                        )
                    ],
                    created=entry.created,
                )
                new_entries.append(new_entry)

    for entry in new_entries:
        entries_by_agent.setdefault(entry.agent, []).append(entry)


def _apply_weight_modifiers(
    entries_by_agent: dict[str, list[LearningsEntry]],
    recent_features: set[str],
) -> None:
    """Step 5: Apply recency and cross-agent weight modifiers."""
    for entries in entries_by_agent.values():
        for entry in entries:
            if entry.evidence and entry.evidence[0].feature in recent_features:
                entry.weight *= 1.5
            if entry.source == "cross_agent":
                entry.weight *= 0.7


def _detect_staleness(
    entries_by_agent: dict[str, list[LearningsEntry]],
    project_root: Path,
) -> None:
    """Step 6: Mark entries as stale if all referenced files are gone."""
    for entries in entries_by_agent.values():
        for entry in entries:
            if not entry.files:
                continue
            all_missing = all(
                not (project_root / f).exists() for f in entry.files
            )
            if all_missing:
                entry.stale = True
                entry.weight *= 0.5


def _deduplicate(
    entries_by_agent: dict[str, list[LearningsEntry]],
) -> None:
    """Step 7: Merge entries with same type and >80% file overlap."""
    for agent in list(entries_by_agent):
        entries = entries_by_agent[agent]
        if len(entries) < 2:
            continue

        entries.sort(key=lambda e: -e.weight)
        merged: list[LearningsEntry] = []
        consumed: set[int] = set()

        for i, entry_a in enumerate(entries):
            if i in consumed:
                continue
            for j in range(i + 1, len(entries)):
                if j in consumed:
                    continue
                entry_b = entries[j]
                if entry_a.observation_type != entry_b.observation_type:
                    continue
                if _file_overlap(entry_a.files, entry_b.files) < 0.8:
                    continue
                entry_a.evidence.extend(entry_b.evidence)
                entry_a.files = sorted(
                    set(entry_a.files) | set(entry_b.files)
                )
                consumed.add(j)
            merged.append(entry_a)

        entries_by_agent[agent] = merged


def _detect_conflicts(
    entries_by_agent: dict[str, list[LearningsEntry]],
) -> tuple[list[Conflict], list[LearningsEntry]]:
    """Step 8: Find and resolve contradictory entries."""
    conflicts: list[Conflict] = []
    rejects: list[LearningsEntry] = []

    for agent in list(entries_by_agent):
        entries = entries_by_agent[agent]
        to_remove: set[int] = set()

        for i, a in enumerate(entries):
            if i in to_remove:
                continue
            for j in range(i + 1, len(entries)):
                if j in to_remove:
                    continue
                b = entries[j]
                type_pair = frozenset({a.observation_type, b.observation_type})
                if type_pair not in _CONTRADICTION_PAIRS:
                    continue
                if _file_overlap(a.files, b.files) < 0.5:
                    continue

                max_w = max(a.weight, b.weight, 0.001)
                if abs(a.weight - b.weight) / max_w <= 0.1:
                    conflicts.append(Conflict(
                        entry_a_id=a.id,
                        entry_b_id=b.id,
                        reason="contradictory types on shared files",
                    ))
                    to_remove.add(i)
                    to_remove.add(j)
                else:
                    winner, loser = (a, b) if a.weight >= b.weight else (b, a)
                    loser_idx = i if loser is a else j
                    loser.rejection_reason = (
                        f"conflict: outweighed by {winner.id}"
                    )
                    rejects.append(loser)
                    to_remove.add(loser_idx)

        entries_by_agent[agent] = [
            e for idx, e in enumerate(entries) if idx not in to_remove
        ]

    return conflicts, rejects


def _quality_bar(
    entries_by_agent: dict[str, list[LearningsEntry]],
) -> list[LearningsEntry]:
    """Step 9: Reject entries that fail structural quality checks."""
    rejects: list[LearningsEntry] = []

    for agent in list(entries_by_agent):
        entries = entries_by_agent[agent]
        passed: list[LearningsEntry] = []

        for entry in entries:
            # Human corrections are signal-level, not file-level (P4)
            is_human = entry.observation_type in (
                "human_override", "human_approved",
            )
            if not is_human and not any("/" in f for f in entry.files):
                entry.rejection_reason = "not specific: no file path"
                rejects.append(entry)
                continue
            if not entry.evidence:
                entry.rejection_reason = (
                    "not evidenced: no supporting observations"
                )
                rejects.append(entry)
                continue
            passed.append(entry)

        entries_by_agent[agent] = passed

    return rejects


def _enforce_budget(
    entries_by_agent: dict[str, list[LearningsEntry]],
) -> list[LearningsEntry]:
    """Step 10: Drop lowest-weight entries until within token budget."""
    dropped: list[LearningsEntry] = []

    for agent in list(entries_by_agent):
        budget = _TOKEN_BUDGETS.get(agent, 1000)
        entries = entries_by_agent[agent]
        entries.sort(key=lambda e: -e.weight)

        kept: list[LearningsEntry] = []
        total_tokens = 0

        for entry in entries:
            tokens = len(json.dumps(entry.detail)) // 4
            if total_tokens + tokens <= budget:
                kept.append(entry)
                total_tokens += tokens
            else:
                entry.rejection_reason = (
                    f"budget: {total_tokens + tokens} > {budget}"
                )
                dropped.append(entry)

        entries_by_agent[agent] = kept

    return dropped


def _write_output(
    learnings_dir: Path,
    entries_by_agent: dict[str, list[LearningsEntry]],
    rejects: list[LearningsEntry],
    conflicts: list[Conflict],
    meta: SynthesisMeta,
) -> None:
    """Step 11: Write learnings files, meta, rejects, conflicts."""
    learnings_dir.mkdir(parents=True, exist_ok=True)

    for agent, entries in entries_by_agent.items():
        data = {
            "agent": agent,
            "synthesized_at": meta.last_run,
            "observation_count": sum(len(e.evidence) for e in entries),
            "feature_count": len(set(
                ev.feature for e in entries for ev in e.evidence
            )),
            "entries": [_entry_to_dict(e) for e in entries],
            "token_estimate": sum(
                len(json.dumps(e.detail)) // 4 for e in entries
            ),
            "budget": _TOKEN_BUDGETS.get(agent, 1000),
        }
        path = learnings_dir / f"{agent}-learnings.json"
        path.write_text(json.dumps(data, indent=2) + "\n")

    meta_path = learnings_dir / "synthesis-meta.json"
    meta_path.write_text(json.dumps({
        "last_run": meta.last_run,
        "features_processed": meta.features_processed,
        "observation_hash": meta.observation_hash,
        "entry_counts": meta.entry_counts,
        "rejected": meta.rejected,
        "conflicts": meta.conflicts,
    }, indent=2) + "\n")

    rejects_path = learnings_dir / "synthesis-rejects.json"
    rejects_path.write_text(json.dumps(
        [_entry_to_dict(e) for e in rejects], indent=2,
    ) + "\n")

    conflicts_path = learnings_dir / "synthesis-conflicts.json"
    conflicts_path.write_text(json.dumps([
        {
            "entry_a_id": c.entry_a_id,
            "entry_b_id": c.entry_b_id,
            "reason": c.reason,
            "resolution": c.resolution,
        }
        for c in conflicts
    ], indent=2) + "\n")


# ── Main entry point ─────────────────────────────────────────────────


def synthesize(
    memory_dir: Path,
    project_root: Path | None = None,
) -> SynthesisResult:
    """Run the full synthesis pipeline.

    Reads observations from memory_dir/observations/*.jsonl,
    produces learnings in memory_dir/learnings/*.json.
    """
    obs_dir = memory_dir / "observations"
    learnings_dir = memory_dir / "learnings"

    if project_root is None:
        project_root = memory_dir.parent.parent

    # Step 1: Read observations
    all_obs, _warnings = _read_all_observations(obs_dir)

    if not all_obs:
        meta = SynthesisMeta(
            last_run=_now_iso(),
            features_processed=[],
            observation_hash=_observation_hash([]),
            entry_counts={},
            rejected=0,
            conflicts=0,
        )
        _write_output(learnings_dir, {}, [], [], meta)
        return SynthesisResult(
            entries_by_agent={},
            rejects=[],
            conflicts=[],
            meta=meta,
        )

    # Incremental check
    obs_hash = _observation_hash(all_obs)
    meta_path = learnings_dir / "synthesis-meta.json"
    if meta_path.exists():
        try:
            existing = json.loads(meta_path.read_text())
            if existing.get("observation_hash") == obs_hash:
                meta = SynthesisMeta(
                    last_run=existing.get("last_run", ""),
                    features_processed=existing.get(
                        "features_processed", []
                    ),
                    observation_hash=existing.get("observation_hash", ""),
                    entry_counts=existing.get("entry_counts", {}),
                    rejected=existing.get("rejected", 0),
                    conflicts=existing.get("conflicts", 0),
                )
                return SynthesisResult(
                    entries_by_agent={},
                    rejects=[],
                    conflicts=[],
                    meta=meta,
                    skipped=True,
                )
        except (json.JSONDecodeError, TypeError, KeyError):
            pass

    # Determine recent features (last 3 by latest timestamp)
    feature_latest: dict[str, str] = {}
    for obs in all_obs:
        cur = feature_latest.get(obs.feature, "")
        if obs.timestamp > cur:
            feature_latest[obs.feature] = obs.timestamp
    sorted_features = sorted(
        feature_latest, key=lambda f: feature_latest[f], reverse=True
    )
    recent_features = set(sorted_features[:3])

    # Steps 2-3: Route and build entries
    entries_by_agent = _build_entries(all_obs)

    # Step 4: Cross-agent reframing
    _cross_agent_reframe(entries_by_agent)

    # Step 5: Weight modifiers
    _apply_weight_modifiers(entries_by_agent, recent_features)

    # Step 6: Staleness
    _detect_staleness(entries_by_agent, project_root)

    # Step 7: Deduplicate
    _deduplicate(entries_by_agent)

    # Step 8: Conflicts
    conflicts, conflict_rejects = _detect_conflicts(entries_by_agent)

    # Step 9: Quality bar
    quality_rejects = _quality_bar(entries_by_agent)

    # Step 10: Token budget
    budget_rejects = _enforce_budget(entries_by_agent)

    all_rejects = conflict_rejects + quality_rejects + budget_rejects

    features = sorted(set(obs.feature for obs in all_obs))
    meta = SynthesisMeta(
        last_run=_now_iso(),
        features_processed=features,
        observation_hash=obs_hash,
        entry_counts={
            agent: len(entries)
            for agent, entries in entries_by_agent.items()
        },
        rejected=len(all_rejects),
        conflicts=len(conflicts),
    )

    # Step 11: Write output
    _write_output(learnings_dir, entries_by_agent, all_rejects, conflicts, meta)

    return SynthesisResult(
        entries_by_agent=entries_by_agent,
        rejects=all_rejects,
        conflicts=conflicts,
        meta=meta,
    )


# ── Injection ─────────────────────────────────────────────────────────


def _format_entry_markdown(entry: dict) -> str:
    """Format a single learnings entry as a markdown bullet."""
    obs_type = entry.get("observation_type", "unknown")
    files = entry.get("files", [])
    detail = entry.get("detail", {})
    evidence = entry.get("evidence", [])
    context = entry.get("reframing_context", "")

    # Files as inline code
    files_str = ", ".join(f"`{f}`" for f in files) if files else "(no files)"

    # Key detail fields as key=value (skip internal/meta fields)
    skip_keys = {"files_involved", "file", "planned_files", "actual_files",
                 "source_file", "subtype"}
    parts = []
    for k, v in detail.items():
        if k in skip_keys:
            continue
        if isinstance(v, (list, dict)):
            continue
        parts.append(f'{k}="{v}"')
    detail_str = ", ".join(parts[:5])  # cap at 5 fields

    # Features from evidence
    features = sorted(set(ev.get("feature", "") for ev in evidence))
    features_str = ", ".join(features) if features else ""

    # Cross-agent tag
    tag = f" [cross-agent: {context}]" if context else ""

    line = f"- **{obs_type}** on {files_str}"
    if detail_str:
        line += f": {detail_str}"
    if tag:
        line += tag
    if features_str:
        line += f" (from {features_str})"

    return line


def filter_learnings_for_task(
    learnings_path: Path,
    task_files: list[str],
) -> str:
    """Read a learnings file, filter entries by task scope, format as markdown.

    Returns empty string on any failure. Never raises.
    """
    try:
        data = json.loads(learnings_path.read_text())
        if not isinstance(data, dict) or "entries" not in data:
            return ""
    except (OSError, json.JSONDecodeError, ValueError):
        return ""

    entries = data["entries"]
    if not entries:
        return ""

    task_files_set = set(task_files)
    task_dirs = set(str(Path(f).parent) for f in task_files if "/" in f)

    matched: list[dict] = []
    for entry in entries:
        entry_files = entry.get("files", [])
        # Direct match
        if task_files_set & set(entry_files):
            matched.append(entry)
            continue
        # Directory match
        entry_dirs = set(str(Path(f).parent) for f in entry_files if "/" in f)
        if task_dirs & entry_dirs:
            matched.append(entry)

    # Fallback: top 3 by weight if no matches
    if not matched:
        by_weight = sorted(entries, key=lambda e: -e.get("weight", 0))
        matched = by_weight[:3]

    lines = [_format_entry_markdown(e) for e in matched]
    return "\n".join(lines)
