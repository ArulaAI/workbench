"""Resolvers for the Intelligence sidebar: related specs, lessons, conventions, CSG context.

Queries:
  - relatedSpecs (already in spec_editor.py)
  - lessonsForSpec
  - conventionsForSpec
  - codebaseContext (scoped CSG stats + skeleton hover)
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from pathlib import Path
from typing import Optional

log = logging.getLogger("speed.dashboard.intelligence")

# ── Lessons ──────────────────────────────────────────────────────────────


def get_lessons_for_spec(
    project_root: Path, spec_path: str, limit: int = 5
) -> list[dict]:
    """Return observations relevant to a spec, ranked by weight.

    Scans .speed/memory/observations/*.jsonl for observations whose
    feature matches the spec's feature, or whose detail text overlaps
    with the spec's content.
    """
    from ..paths import get_paths
    paths = get_paths(project_root)

    obs_dir = paths.observations_dir
    if not obs_dir.is_dir():
        return []

    # Determine the spec's feature from its path
    spec_feature = _feature_from_path(spec_path)

    # Load spec content for keyword matching
    full_path = project_root / spec_path
    spec_keywords: set[str] = set()
    if full_path.exists():
        try:
            content = full_path.read_text(encoding="utf-8").lower()
            # Extract meaningful words (4+ chars, not common stopwords)
            spec_keywords = {
                w for w in re.findall(r"\b[a-z]{4,}\b", content)
                if w not in _STOPWORDS
            }
        except (OSError, UnicodeDecodeError):
            pass

    all_observations: list[dict] = []
    for jsonl_file in obs_dir.glob("*.jsonl"):
        try:
            for line in jsonl_file.read_text(encoding="utf-8").strip().split("\n"):
                if not line.strip():
                    continue
                try:
                    obs = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Score relevance
                score = obs.get("weight", 0.5)
                obs_feature = obs.get("feature", "")

                # Boost if same feature
                if spec_feature and obs_feature == spec_feature:
                    score += 2.0

                # Boost if detail text shares keywords with spec
                detail = str(obs.get("detail", "")).lower()
                if spec_keywords:
                    overlap = sum(1 for kw in spec_keywords if kw in detail)
                    score += min(overlap * 0.1, 1.0)

                obs["_relevance"] = score
                all_observations.append(obs)
        except (OSError, UnicodeDecodeError):
            continue

    # Sort by relevance, deduplicate by detail content, return top N
    all_observations.sort(key=lambda o: o.get("_relevance", 0), reverse=True)
    seen_details: set[str] = set()

    results = []
    for obs in all_observations:
        if len(results) >= limit:
            break
        detail = obs.get("detail", "")
        if isinstance(detail, dict):
            detail = "; ".join(f"{k}: {v}" for k, v in detail.items() if v)
        elif not isinstance(detail, str):
            detail = str(detail)

        # Deduplicate by detail content
        detail_key = detail[:200]
        if detail_key in seen_details:
            continue
        seen_details.add(detail_key)

        results.append({
            "id": obs.get("id", ""),
            "feature": obs.get("feature", ""),
            "observation_type": obs.get("observation_type", ""),
            "detail": detail,
            "stage": obs.get("stage", ""),
            "weight": obs.get("weight", 0),
            "relevance": round(obs.get("_relevance", 0), 2),
        })

    return results


# ── Conventions ──────────────────────────────────────────────────────────


def get_conventions_for_spec(
    project_root: Path, spec_path: str, limit: int = 10
) -> list[dict]:
    """Return conventions relevant to a spec's domain.

    Reads .speed/memory/conventions.json and filters by scope overlap
    with the spec's referenced files/directories.
    """
    from ..paths import get_paths
    paths = get_paths(project_root)

    conv_path = paths.conventions_path
    if not conv_path.exists():
        return []

    try:
        data = json.loads(conv_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    conventions = data.get("conventions", [])
    if not conventions:
        return []

    # Extract specific file paths referenced in the spec (backtick-quoted and link targets)
    full_path = project_root / spec_path
    spec_files: set[str] = set()
    if full_path.exists():
        try:
            content = full_path.read_text(encoding="utf-8")
            for match in re.findall(r"`([^`]+)`", content):
                if "/" in match and "." in match.rsplit("/", 1)[-1]:
                    # Only keep paths that look like files (have extension)
                    spec_files.add(match)
            for match in re.findall(r"\]\(([^)]+)\)", content):
                if "/" in match and not match.startswith("http"):
                    spec_files.add(match)
        except (OSError, UnicodeDecodeError):
            pass

    if not spec_files:
        return []

    results = []
    for conv in conventions:
        scope = conv.get("scope", [])
        convention_text = conv.get("convention", "")
        if not scope:
            continue

        # Score: check if any file the spec references appears in the convention's
        # text or scope. Require exact file path match, not directory prefix.
        relevance = 0.0
        for spec_file in spec_files:
            # Check if this file is mentioned in the convention text
            if spec_file in convention_text:
                relevance += 2.0
            # Check if this file falls under a convention's scope directory
            for s in scope:
                if spec_file.startswith(s + "/") or spec_file == s:
                    relevance += 0.5

        if relevance > 0:
            evidence = conv.get("evidence", {})
            results.append({
                "id": conv.get("id", ""),
                "convention": conv.get("convention", ""),
                "scope": scope,
                "confidence": conv.get("confidence", ""),
                "tags": conv.get("tags", []),
                "adherence": evidence.get("code_adherence", 0),
                "relevance": relevance,
            })

    # Sort by relevance, then adherence
    results.sort(key=lambda c: (c["relevance"], c["adherence"]), reverse=True)
    return results[:limit]


# ── Codebase Context ─────────────────────────────────────────────────────


def get_codebase_context(
    project_root: Path, spec_path: str
) -> dict:
    """Return CSG stats scoped to the spec's domain.

    Maps file references in the spec to CSG clusters, then returns
    stats about those clusters.
    """
    from ..paths import get_paths
    paths = get_paths(project_root)

    csg_path = paths.context_dir / "semantic-graph.json"
    if not csg_path.exists():
        return {"clusters": [], "stats": {"nodes": 0, "edges": 0, "clusters": 0}}

    try:
        csg = json.loads(csg_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"clusters": [], "stats": {"nodes": 0, "edges": 0, "clusters": 0}}

    # Extract file references from spec
    full_path = project_root / spec_path
    spec_files: set[str] = set()
    if full_path.exists():
        try:
            content = full_path.read_text(encoding="utf-8")
            for match in re.findall(
                r"`([^`]+\.(?:py|ts|tsx|js|jsx|sh|rs|go|java|rb|css|html))`",
                content,
            ):
                spec_files.add(match)
        except (OSError, UnicodeDecodeError):
            pass

    # Build file-to-cluster map
    clusters = csg.get("clusters", [])
    file_to_cluster: dict[str, dict] = {}
    for cluster in clusters:
        for f in cluster.get("files", []):
            file_to_cluster[f] = cluster

    # Find clusters touched by the spec
    touched_clusters: dict[str, dict] = {}
    for f in spec_files:
        cl = file_to_cluster.get(f)
        if cl:
            touched_clusters[cl["id"]] = cl

    # Compute scoped stats
    scoped_nodes = sum(len(cl.get("symbols", [])) for cl in touched_clusters.values())
    scoped_files = set()
    for cl in touched_clusters.values():
        scoped_files.update(cl.get("files", []))

    return {
        "clusters": [
            {
                "id": cl["id"],
                "label": cl.get("label", cl["id"]),
                "file_count": len(cl.get("files", [])),
                "symbol_count": len(cl.get("symbols", [])),
                "cohesion": cl.get("cohesion", 0),
            }
            for cl in touched_clusters.values()
        ],
        "stats": {
            "nodes": scoped_nodes,
            "files": len(scoped_files),
            "clusters": len(touched_clusters),
            "total_clusters": len(clusters),
            "total_nodes": len(csg.get("nodes", [])),
        },
    }


def get_file_skeleton(
    project_root: Path, file_path: str
) -> Optional[str]:
    """Return the compressed skeleton for a file (for hover preview)."""
    from ..paths import get_paths
    paths = get_paths(project_root)

    skeleton_path = paths.context_dir / "skeletons" / f"{file_path}.skeleton"
    if skeleton_path.exists():
        try:
            return skeleton_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
    return None


# ── Spec Traceability ────────────────────────────────────────────────────


def get_spec_traceability(
    project_root: Path, spec_path: str
) -> Optional[dict]:
    """Return coverage data for the spec's feature from spec-traceability.json."""
    feature = _feature_from_path(spec_path)
    if not feature:
        return None

    from ..paths import get_paths
    paths = get_paths(project_root)

    trace_path = paths.feature_shared(feature) / "spec-traceability.json"
    if not trace_path.exists():
        return None

    try:
        data = json.loads(trace_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    covered = data.get("covered", [])
    uncovered = data.get("uncovered", [])

    return {
        "requirements_found": data.get("requirements_found", 0),
        "coverage_ratio": data.get("coverage_ratio", 0),
        "covered": [
            {"requirement": c.get("requirement", "")[:200], "evidence": c.get("evidence", "")[:100]}
            for c in (covered if isinstance(covered, list) else [])
        ],
        "uncovered": [
            r if isinstance(r, str) else str(r)[:200]
            for r in (uncovered if isinstance(uncovered, list) else [])
        ],
    }


# ── Feature Health ───────────────────────────────────────────────────────


def get_feature_health(
    project_root: Path, spec_path: str
) -> Optional[dict]:
    """Return aggregated observation stats and contract summary for the spec's feature."""
    feature = _feature_from_path(spec_path)
    if not feature:
        return None

    from ..paths import get_paths
    paths = get_paths(project_root)

    result: dict = {"feature": feature, "observation_summary": {}, "contract_entities": [], "status": "unknown"}

    # Feature state
    state_path = paths.feature_local(feature) / "state.json"
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            result["status"] = state.get("status", "unknown")
        except (json.JSONDecodeError, OSError):
            pass

    # Observation breakdown
    obs_dir = paths.observations_dir
    obs_file = obs_dir / f"{feature}.jsonl"
    if obs_file.exists():
        type_counts: dict[str, int] = {}
        total = 0
        try:
            for line in obs_file.read_text(encoding="utf-8").strip().split("\n"):
                if not line.strip():
                    continue
                try:
                    obs = json.loads(line)
                    t = obs.get("observation_type", "unknown")
                    type_counts[t] = type_counts.get(t, 0) + 1
                    total += 1
                except json.JSONDecodeError:
                    continue
        except (OSError, UnicodeDecodeError):
            pass
        result["observation_summary"] = {
            "total": total,
            "types": [{"type": t, "count": c} for t, c in sorted(type_counts.items(), key=lambda x: -x[1])],
        }

    # Contract entities (top-level summary)
    contract_path = paths.feature_shared(feature) / "contract.json"
    if contract_path.exists():
        try:
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            entities = contract.get("entities", [])
            result["contract_entities"] = [
                {"name": e.get("name", ""), "type": e.get("type", "")}
                for e in entities[:15]
            ]
        except (json.JSONDecodeError, OSError):
            pass

    # Task-level detail: retries, review verdicts, human overrides
    task_dir = paths.feature_shared(feature) / "tasks"
    tasks_detail: list[dict] = []
    if task_dir.exists():
        for task_file in sorted(task_dir.glob("*.json")):
            try:
                td = json.loads(task_file.read_text(encoding="utf-8"))
                task_info: dict = {
                    "id": task_file.stem,
                    "title": td.get("title", ""),
                    "status": td.get("status", "unknown"),
                    "retry_count": td.get("retry_count", 0),
                    "files_touched": len(td.get("files_touched", [])),
                }
                # Extract reviewer verdict
                review = td.get("review_feedback")
                if review:
                    if isinstance(review, str):
                        try:
                            review = json.loads(review)
                        except json.JSONDecodeError:
                            review = None
                    if isinstance(review, dict):
                        task_info["review_verdict"] = review.get("verdict", "")
                        findings = review.get("spec_verification", [])
                        task_info["finding_count"] = len(findings)

                tasks_detail.append(task_info)
            except (json.JSONDecodeError, OSError):
                continue

    result["tasks"] = tasks_detail

    # High-signal observations: human overrides and security findings
    result["highlights"] = []
    if obs_file.exists():
        try:
            for line in obs_file.read_text(encoding="utf-8").strip().split("\n"):
                if not line.strip():
                    continue
                try:
                    obs = json.loads(line)
                except json.JSONDecodeError:
                    continue
                otype = obs.get("observation_type", "")
                weight = obs.get("weight", 0)
                if otype in ("human_override", "security_finding", "context_miss", "coherence_issue") or weight >= 2.0:
                    detail = obs.get("detail", {})
                    if isinstance(detail, dict):
                        detail = "; ".join(f"{k}: {v}" for k, v in detail.items() if v and k not in ("id", "timestamp"))
                    elif not isinstance(detail, str):
                        detail = str(detail)
                    result["highlights"].append({
                        "type": otype,
                        "stage": obs.get("stage", ""),
                        "weight": weight,
                        "detail": str(detail)[:250],
                    })
        except (OSError, UnicodeDecodeError):
            pass
        # Deduplicate and limit
        seen: set[str] = set()
        unique: list[dict] = []
        for h in sorted(result["highlights"], key=lambda x: -x["weight"]):
            key = h["detail"][:100]
            if key not in seen:
                seen.add(key)
                unique.append(h)
        result["highlights"] = unique[:10]

    return result


# ── Helpers ──────────────────────────────────────────────────────────────


def _feature_from_path(spec_path: str) -> Optional[str]:
    """Extract feature name from a spec path."""
    # specs/product/speed-defects.md → speed-defects
    parts = spec_path.split("/")
    if len(parts) >= 3:
        return parts[-1].replace(".md", "")
    return None


_STOPWORDS = {
    "this", "that", "with", "from", "have", "will", "been", "were", "they",
    "their", "which", "would", "should", "could", "about", "into", "then",
    "than", "when", "what", "each", "make", "like", "long", "look", "many",
    "some", "them", "time", "very", "your", "just", "know", "take", "come",
    "more", "most", "only", "over", "also", "back", "after", "work", "first",
    "even", "give", "need", "does", "well", "much", "good", "great", "being",
    "other", "where", "there", "these", "those", "under", "still", "every",
    "using", "used", "file", "spec", "feature", "should", "must", "because",
}
