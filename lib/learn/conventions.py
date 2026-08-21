"""Data models, shared types, atomic write utility, and pipeline orchestrator
for the conventions pipeline.

All pipeline phases (config extraction, mechanical extractors, observation
integration, template formatting) depend on these types. The public API
functions (discover_conventions, format_conventions_for_agent,
format_knowledge_for_agent) tie the pipeline together.
"""

import fnmatch
import hashlib
import json
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)


# ── Type aliases ──────────────────────────────────────────────────────


ConfidenceLevel = Literal["established", "emerging", "decaying", "conflict"]

SourceLiteral = Literal["config", "discovered"]

RejectionReason = Literal[
    "no_matching_template",
    "not_actionable",
    "not_project_specific",
    "not_evidenced",
    "not_scoped",
    "redundant",
]


# ── Dataclasses ───────────────────────────────────────────────────────


@dataclass
class RawPattern:
    """Intermediate representation from Phase A/B pattern extraction."""

    type: str                    # pattern type key (e.g. "naming_snake")
    files: list[str]             # files exhibiting this pattern
    scope: list[str]             # directory or module scopes where seen
    adherence: float             # fraction of in-scope instances following pattern (0–1)
    evidence: str                # human-readable description of evidence
    observation_support: int = 0  # count of corroborating observations
    recent_trend: str = "stable"  # "toward", "away", or "stable"


@dataclass
class ConventionEntry:
    """Final convention record written to conventions.json."""

    id: str                      # "conv-<slug>"
    convention: str              # human-readable convention statement
    scope: list[str]             # where this convention applies
    confidence: str              # ConfidenceLevel value
    canonical_example: str       # file path or representative code snippet
    exceptions: str | None       # known legitimate exceptions, or None
    evolution: dict | None       # {"from": ..., "to": ..., "trend": ...} or None
    tags: list[str]              # categorization tags
    evidence: dict               # structured evidence block
    source: str                  # SourceLiteral value


@dataclass
class ConventionResult:
    """Output of the full convention synthesis pipeline."""

    conventions: list[ConventionEntry]   # accepted conventions
    conflicts: list[dict]                # unresolved conflict dicts
    candidates: list[ConventionEntry]    # below-bar entries pending promotion
    meta: dict                           # run metadata

    def summary(self) -> str:
        """Format a CLI summary of the convention run.

        Returns a multi-line string containing convention count, candidate
        count, and source breakdown.
        """
        n = len(self.conventions)
        c = len(self.candidates)
        unit = "convention" if n == 1 else "conventions"
        cand_unit = "candidate" if c == 1 else "candidates"

        by_source: dict[str, int] = {}
        for conv in self.conventions:
            by_source[conv.source] = by_source.get(conv.source, 0) + 1

        lines = [f"{n} {unit}, {c} {cand_unit}"]

        if by_source:
            breakdown = ", ".join(
                f"{count} {src}" for src, count in sorted(by_source.items())
            )
            lines.append(f"sources: {breakdown}")

        if self.conflicts:
            nc = len(self.conflicts)
            conflict_unit = "conflict" if nc == 1 else "conflicts"
            lines.append(f"{nc} unresolved {conflict_unit}")

        return "\n".join(lines)


# ── Utility function ──────────────────────────────────────────────────


def _atomic_write(path: Path, data: dict | list) -> None:
    """Write JSON to a temp file then rename to prevent partial corruption.

    Creates parent directories if they don't exist. The temp file is placed
    in the same directory as the target so the rename is atomic on POSIX
    systems (same filesystem).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ── Serialization helpers ─────────────────────────────────────────────


def _convention_to_dict(entry: ConventionEntry) -> dict:
    """Serialize a ConventionEntry to a JSON-compatible dict."""
    return {
        "id": entry.id,
        "convention": entry.convention,
        "scope": entry.scope,
        "confidence": entry.confidence,
        "canonical_example": entry.canonical_example,
        "exceptions": entry.exceptions,
        "evolution": entry.evolution,
        "tags": entry.tags,
        "evidence": entry.evidence,
        "source": entry.source,
    }


def _dict_to_convention(d: dict) -> ConventionEntry:
    """Deserialize a dict into a ConventionEntry."""
    return ConventionEntry(
        id=d.get("id", ""),
        convention=d.get("convention", ""),
        scope=d.get("scope", []),
        confidence=d.get("confidence", ""),
        canonical_example=d.get("canonical_example", ""),
        exceptions=d.get("exceptions"),
        evolution=d.get("evolution"),
        tags=d.get("tags", []),
        evidence=d.get("evidence", {}),
        source=d.get("source", ""),
    )


# ── Trigger helpers ───────────────────────────────────────────────────


def _count_git_changes(project_root: Path, since: str) -> int:
    """Count unique files changed in git since a timestamp."""
    try:
        result = subprocess.run(
            ["git", "log", "--name-only", "--pretty=format:", f"--since={since}"],
            capture_output=True, text=True, cwd=project_root,
        )
        if result.returncode != 0:
            return 0
        files = {f.strip() for f in result.stdout.splitlines() if f.strip()}
        return len(files)
    except (FileNotFoundError, OSError):
        return 0


def _count_completed_features(project_root: Path, since: str) -> int:
    """Count features completed since a timestamp."""
    features_dir = project_root / ".speed" / "features"
    if not features_dir.is_dir():
        return 0

    try:
        since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return 0

    count = 0
    for feat_dir in features_dir.iterdir():
        if not feat_dir.is_dir():
            continue
        state_path = feat_dir / "state.json"
        if not state_path.exists():
            continue
        try:
            state = json.loads(state_path.read_text())
            status = state.get("status", "")
            completed_at = state.get("completed_at", "")
            if status in ("done", "merged", "complete") and completed_at:
                feat_dt = datetime.fromisoformat(
                    completed_at.replace("Z", "+00:00")
                )
                if feat_dt > since_dt:
                    count += 1
        except (json.JSONDecodeError, OSError, ValueError):
            continue
    return count


def _compute_cluster_checksums(csg: dict) -> dict:
    """Compute checksums for CSG clusters from their member lists."""
    clusters = csg.get("clusters", [])
    if not isinstance(clusters, list):
        return {}

    checksums = {}
    for cluster in clusters:
        if not isinstance(cluster, dict):
            continue
        cid = cluster.get("id", "")
        members = sorted(cluster.get("members", []))
        if cid and members:
            payload = json.dumps(members, sort_keys=True)
            checksums[cid] = hashlib.sha256(payload.encode()).hexdigest()[:16]
    return checksums


def _get_current_cluster_checksums(project_root: Path) -> dict:
    """Read current CSG from standard locations and compute cluster checksums."""
    for csg_name in ("csg.json", "code-structure-graph.json"):
        csg_path = project_root / ".speed" / "memory" / csg_name
        if csg_path.exists():
            try:
                csg = json.loads(csg_path.read_text())
                return _compute_cluster_checksums(csg)
            except (json.JSONDecodeError, OSError):
                pass
    return {}


def _count_convention_violations(memory_dir: Path, since: str) -> int:
    """Count convention_violation observations newer than a timestamp."""
    obs_dir = memory_dir / "observations"
    if not obs_dir.is_dir():
        return 0

    count = 0
    for jsonl_file in obs_dir.glob("*.jsonl"):
        try:
            for line in jsonl_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obs = json.loads(line)
                    if obs.get("observation_type") == "convention_violation":
                        ts = obs.get("timestamp", "")
                        if ts > since:
                            count += 1
                except json.JSONDecodeError:
                    continue
        except OSError:
            continue
    return count


# ── Trigger logic ─────────────────────────────────────────────────────


def _should_run_discovery(
    memory_dir: Path, project_root: Path
) -> tuple[bool, str]:
    """Check trigger conditions for convention discovery.

    Checks in order and returns on the first match:
    1. conventions-meta.json missing → first_run
    2. 50+ files changed since last_run → files_changed
    3. 3+ features completed since last_run → features_completed
    4. CSG cluster checksums differ → csg_restructured
    5. 5+ convention violations since last_run → violations_threshold

    Returns (should_run, trigger_reason). When no condition fires,
    returns (False, '').
    """
    meta_path = memory_dir / "conventions-meta.json"
    if not meta_path.exists():
        return True, "first_run"

    try:
        meta = json.loads(meta_path.read_text())
    except (json.JSONDecodeError, OSError):
        return True, "first_run"

    last_run = meta.get("last_run", "")
    if not last_run:
        return True, "first_run"

    # 2: Files changed
    changed = _count_git_changes(project_root, last_run)
    if changed >= 50:
        return True, "files_changed"

    # 3: Features completed
    completed = _count_completed_features(project_root, last_run)
    if completed >= 3:
        return True, "features_completed"

    # 4: Cluster checksums
    stored_checksums = meta.get("cluster_checksums", {})
    current_checksums = _get_current_cluster_checksums(project_root)
    if current_checksums and current_checksums != stored_checksums:
        return True, "csg_restructured"

    # 5: Convention violations
    violations = _count_convention_violations(memory_dir, last_run)
    if violations >= 5:
        return True, "violations_threshold"

    return False, ""


# ── Orchestrator helpers ──────────────────────────────────────────────


def _load_existing_conventions(memory_dir: Path) -> ConventionResult:
    """Load previously computed conventions from disk.

    Used when incremental mode determines no re-run is needed.
    Returns a ConventionResult with deserialized entries and stored metadata.
    """
    conventions: list[ConventionEntry] = []
    candidates: list[ConventionEntry] = []
    conflicts: list[dict] = []
    meta: dict = {}

    conventions_path = memory_dir / "conventions.json"
    if conventions_path.exists():
        try:
            data = json.loads(conventions_path.read_text())
            for c in data.get("conventions", []):
                conventions.append(_dict_to_convention(c))
        except (json.JSONDecodeError, OSError):
            pass

    meta_path = memory_dir / "conventions-meta.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    candidates_path = memory_dir / "conventions-candidates.json"
    if candidates_path.exists():
        try:
            cands = json.loads(candidates_path.read_text())
            if isinstance(cands, list):
                for c in cands:
                    entry = _dict_to_convention(c)
                    candidates.append(entry)
                    # Extract conflicts from candidates with rejection_reason
                    ev = c.get("evidence", {})
                    if isinstance(ev, dict) and ev.get("rejection_reason") == "conflict":
                        conflicts.append({
                            "id": c.get("id", ""),
                            "convention": c.get("convention", ""),
                            "scope": c.get("scope", []),
                        })
        except (json.JSONDecodeError, OSError):
            pass

    return ConventionResult(
        conventions=conventions,
        conflicts=conflicts,
        candidates=candidates,
        meta=meta,
    )


def _build_views(conventions: list[ConventionEntry]) -> dict:
    """Build agent-specific view entries from conventions.

    Each agent gets every convention formatted as a markdown bullet with
    scope metadata preserved for downstream filtering.
    """
    agents = ["developer", "reviewer", "architect"]
    views: dict[str, list[dict]] = {}

    for agent in agents:
        entries = []
        for conv in conventions:
            text = f"- **[{conv.confidence}]** {conv.convention}"
            entries.append({
                "id": conv.id,
                "text": text,
                "scope": conv.scope,
            })
        views[agent] = entries

    return views


# ── Pipeline orchestrator ─────────────────────────────────────────────


def discover_conventions(
    project_root: Path,
    memory_dir: Path,
    csg_path: Path | None = None,
    incremental: bool = True,
) -> ConventionResult:
    """Run the full convention discovery pipeline.

    Orchestrates config extraction (Phase 0), mechanical pattern detection
    (Phase A), observation integration (Phase B), and template formatting
    (Phase C). Writes conventions.json, conventions-meta.json, and
    conventions-candidates.json to memory_dir.
    """
    # Step 1: Incremental check
    if incremental:
        should_run, trigger = _should_run_discovery(memory_dir, project_root)
        if not should_run:
            return _load_existing_conventions(memory_dir)
    else:
        trigger = "full_run"

    # Step 2: Load CSG
    csg = None
    if csg_path is not None:
        try:
            csg = json.loads(csg_path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not load CSG from %s: %s", csg_path, exc)

    # Step 3: Phase 0 — config conventions
    from lib.learn.convention_configs import _extract_config_conventions
    config_conventions = _extract_config_conventions(project_root)

    # Step 4: Phase A — mechanical extractors
    from lib.learn.convention_extractors import (
        _extract_comodification,
        _extract_imports_and_naming,
        _extract_import_graph,
        _extract_dependency_usage,
    )
    raw_patterns: list[RawPattern] = []
    raw_patterns.extend(_extract_comodification(project_root))
    raw_patterns.extend(_extract_imports_and_naming(project_root, csg))
    raw_patterns.extend(_extract_import_graph(project_root, csg))
    raw_patterns.extend(_extract_dependency_usage(project_root))

    # Step 5: Phase B — observation integration
    from lib.learn.convention_observations import _integrate_observations
    obs_dir = memory_dir / "observations"
    enriched = _integrate_observations(raw_patterns, obs_dir)

    # Step 6: Phase C — template formatting and validation
    from lib.learn.convention_templates import _format_and_validate
    conventions, candidates = _format_and_validate(enriched, config_conventions)

    # Extract conflicts from candidates marked with rejection_reason="conflict"
    conflicts: list[dict] = []
    for c in candidates:
        if isinstance(c.evidence, dict) and c.evidence.get("rejection_reason") == "conflict":
            conflicts.append({
                "id": c.id,
                "convention": c.convention,
                "scope": c.scope,
            })

    # Step 7: Build agent-specific views
    views = _build_views(conventions)

    # Compute metadata
    analyzed_files: set[str] = set()
    for p in enriched:
        analyzed_files.update(p.files)
    cluster_checksums = _compute_cluster_checksums(csg) if csg else {}

    obs_dir = memory_dir / "observations"
    observation_count_at_run = 0
    convention_violation_count_at_run = 0
    if obs_dir.is_dir():
        for _jsonl_file in obs_dir.glob("*.jsonl"):
            try:
                for _line in _jsonl_file.read_text(encoding="utf-8").splitlines():
                    _line = _line.strip()
                    if not _line:
                        continue
                    try:
                        _obs = json.loads(_line)
                        observation_count_at_run += 1
                        if _obs.get("observation_type") == "convention_violation":
                            convention_violation_count_at_run += 1
                    except json.JSONDecodeError:
                        continue
            except OSError:
                continue

    meta = {
        "last_run": datetime.now(timezone.utc).isoformat(),
        "files_analyzed": len(analyzed_files),
        "cluster_checksums": cluster_checksums,
        "trigger": trigger,
        "convention_count": len(conventions),
        "candidate_count": len(candidates),
        "observation_count_at_run": observation_count_at_run,
        "convention_violation_count_at_run": convention_violation_count_at_run,
    }

    # Step 8: Write output files
    conventions_data = {
        "conventions": [_convention_to_dict(c) for c in conventions],
        "conflicts": conflicts,
        "views": views,
    }
    _atomic_write(memory_dir / "conventions.json", conventions_data)
    _atomic_write(memory_dir / "conventions-meta.json", meta)
    _atomic_write(
        memory_dir / "conventions-candidates.json",
        [_convention_to_dict(c) for c in candidates],
    )

    # Step 9: Return result
    return ConventionResult(
        conventions=conventions,
        conflicts=conflicts,
        candidates=candidates,
        meta=meta,
    )


# ── Formatting functions ──────────────────────────────────────────────


def _scope_intersects(
    scope: list[str], task_files_set: set[str], task_dirs: set[str]
) -> bool:
    """Check if a convention's scope overlaps with any task file or directory."""
    for s in scope:
        # Root scope matches everything
        if s in (".", "./"):
            return True

        # Direct file match
        if s in task_files_set:
            return True

        # Convention scope is a directory prefix of a task file
        s_prefix = s if s.endswith("/") else s + "/"
        for f in task_files_set:
            if f.startswith(s_prefix):
                return True

        # Task directory is under or contains the convention scope
        for d in task_dirs:
            d_prefix = d if d.endswith("/") else d + "/"
            if d_prefix.startswith(s_prefix) or s_prefix.startswith(d_prefix):
                return True

    return False


def format_conventions_for_agent(
    conventions_path: Path, agent: str, task_files: list[str]
) -> str:
    """Load conventions.json, filter for agent and task scope, format as markdown.

    Reads the pre-computed views.{agent} entries, filters those whose scope
    intersects with task_files, and concatenates their text. Output is
    truncated to a 2,000-token budget (approximated as len // 4).

    Returns empty string when the file is missing or malformed.
    """
    try:
        data = json.loads(conventions_path.read_text())
    except (json.JSONDecodeError, OSError):
        return ""

    if not isinstance(data, dict):
        return ""

    views = data.get("views", {})
    agent_view = views.get(agent, [])
    if not isinstance(agent_view, list) or not agent_view:
        return ""

    # Build lookup sets for scope matching
    task_files_set = set(task_files)
    task_dirs = {str(Path(f).parent) for f in task_files if "/" in f}

    matched = [
        entry for entry in agent_view
        if _scope_intersects(entry.get("scope", []), task_files_set, task_dirs)
    ]

    if not matched:
        return ""

    # Sort by confidence tier so high/locked survive truncation, low gets cut first
    _confidence_order = {"locked": 0, "high": 1, "established": 1, "medium": 2, "emerging": 2, "low": 3, "decaying": 4}
    matched.sort(key=lambda e: _confidence_order.get(e.get("confidence", "low"), 3))

    # Format and truncate to 2000 tokens
    lines: list[str] = []
    token_count = 0
    max_tokens = 2000

    for entry in matched:
        text = entry.get("text", "")
        confidence = entry.get("confidence", "")
        # Prefix locked/high confidence entries so agents know they're authoritative
        if confidence in ("locked", "high", "established"):
            text = f"[{confidence.upper()}] {text}"
        tokens = len(text) // 4
        if token_count + tokens > max_tokens:
            break
        lines.append(text)
        token_count += tokens

    return "\n".join(lines)


def format_knowledge_for_agent(
    knowledge_path: Path, agent: str, task_files: list[str]
) -> str:
    """Load project-knowledge.json, filter by agent and applies_to scope.

    Entries pass when their ``agents`` list includes the given agent (or is
    empty, meaning all agents) AND their ``applies_to`` glob patterns
    intersect with task_files (or applies_to is empty, meaning global).

    Output is truncated to a 1,500-token budget. Returns empty string
    when the file is missing or malformed.
    """
    try:
        data = json.loads(knowledge_path.read_text())
    except (json.JSONDecodeError, OSError):
        return ""

    if not isinstance(data, dict):
        return ""

    entries = data.get("entries", [])
    if not isinstance(entries, list) or not entries:
        return ""

    matched: list[dict] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue

        # Agent filter: empty means all agents
        agents = entry.get("agents", [])
        if agents and agent not in agents:
            continue

        # Scope filter: empty applies_to means global
        applies_to = entry.get("applies_to", [])
        if applies_to and not _applies_to_match(applies_to, task_files):
            continue

        matched.append(entry)

    if not matched:
        return ""

    # Format as markdown and truncate to 1500 tokens
    lines: list[str] = []
    token_count = 0
    max_tokens = 1500

    for entry in matched:
        content = entry.get("knowledge", "")
        title = entry.get("why_it_matters", "")
        line = f"- **{title}**: {content}" if title else f"- {content}"

        tokens = len(line) // 4
        if token_count + tokens > max_tokens:
            break
        lines.append(line)
        token_count += tokens

    return "\n".join(lines)


def _applies_to_match(applies_to: list[str], task_files: list[str]) -> bool:
    """Check if any applies_to glob pattern matches any task file."""
    for pattern in applies_to:
        for task_file in task_files:
            if fnmatch.fnmatch(task_file, pattern):
                return True
    return False
