"""Freshness fingerprinting for repository-digest.json.

Canonical hashing of the inputs that can change digest conclusions, and
comparison of a stored fingerprint against current repository state.
See specs/tech/speed-repository-digest-dashboard.md > Data Model > Fingerprint.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .repository_digest_schema import SCHEMA_VERSION
from .utils import git_head_hash

# Only these speed.toml sections affect discovery conclusions. Agent models,
# ports, UI theme, and verbosity must never appear here — a change to those
# must not mark the digest stale (Risks and Coverage: "Staleness fires for
# irrelevant config changes").
_DISCOVERY_CONFIG_SECTIONS = ("ignore", "subsystems", "context", "digest")


@dataclass(frozen=True)
class DigestFingerprint:
    git_head: str | None
    discovery_config_sha256: str
    project_map_sha256: str
    semantic_graph_sha256: str | None
    knowledge_sha256: str | None
    schema_version: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _canonical_hash(value: Any) -> str:
    """SHA-256 of a canonical (sorted-key, no-whitespace) JSON projection."""
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _file_hash(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def discovery_config_projection(config: dict[str, Any]) -> dict[str, Any]:
    """Project only the discovery-relevant subset of speed.toml."""
    return {k: config.get(k, {}) for k in _DISCOVERY_CONFIG_SECTIONS if k in config}


def compute_discovery_config_sha256(config: dict[str, Any]) -> str:
    return _canonical_hash(discovery_config_projection(config))


def compute_knowledge_sha256(
    conventions: list[dict[str, Any]], project_knowledge: list[dict[str, Any]]
) -> str | None:
    """Hash the canonical content of *approved* conventions and
    project-knowledge entries only. Draft knowledge never affects this
    hash (see Fingerprint: 'Draft knowledge is excluded... its count may
    affect readiness and therefore is computed at query time').
    """
    if not conventions and not project_knowledge:
        return None
    payload = {
        "conventions": sorted(
            (c.get("id", ""), c.get("convention", "")) for c in conventions
        ),
        "project_knowledge": sorted(
            (k.get("id", ""), k.get("knowledge", "")) for k in project_knowledge
        ),
    }
    return _canonical_hash(payload)


def compute_fingerprint(
    project_root: str,
    *,
    config: dict[str, Any],
    project_map_path: Path,
    semantic_graph_path: Path,
    conventions: list[dict[str, Any]],
    project_knowledge: list[dict[str, Any]],
) -> DigestFingerprint:
    return DigestFingerprint(
        git_head=git_head_hash(project_root) or None,
        discovery_config_sha256=compute_discovery_config_sha256(config),
        project_map_sha256=_file_hash(project_map_path) or "",
        semantic_graph_sha256=_file_hash(semantic_graph_path),
        knowledge_sha256=compute_knowledge_sha256(conventions, project_knowledge),
        schema_version=SCHEMA_VERSION,
    )


def compute_digest_freshness(
    project_root: str,
    digest: dict[str, Any],
    *,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare a stored digest's fingerprint against current repository
    state. Returns a dict with state (CURRENT|STALE), indexed_git_head,
    current_git_head, generated_at, and stale_reasons — never rebuilds
    anything or touches the repository beyond a HEAD read and a few
    stat/hash calls.
    """
    from . import repository_digest as _rd  # local import avoids a cycle

    stored = digest.get("fingerprint") or {}
    config = config if config is not None else {}

    paths = _rd.repository_digest_input_paths(project_root)
    conventions = _rd.load_optional_json_list(paths["conventions"], key="conventions")
    project_knowledge = _rd.load_optional_json_list(paths["project_knowledge"], key="entries")

    current = compute_fingerprint(
        project_root,
        config=config,
        project_map_path=paths["project_map"],
        semantic_graph_path=paths["semantic_graph"],
        conventions=conventions,
        project_knowledge=project_knowledge,
    )

    reasons: list[str] = []
    if (stored.get("git_head") or None) != current.git_head:
        reasons.append("git_head")
    if stored.get("discovery_config_sha256") != current.discovery_config_sha256:
        reasons.append("discovery_config")
    if stored.get("project_map_sha256") != current.project_map_sha256:
        reasons.append("project_map")
    if stored.get("semantic_graph_sha256") != current.semantic_graph_sha256:
        reasons.append("semantic_graph")
    if stored.get("knowledge_sha256") != current.knowledge_sha256:
        reasons.append("knowledge")
    if stored.get("schema_version") != current.schema_version:
        reasons.append("schema_version")

    state = "STALE" if reasons else "CURRENT"

    return {
        "state": state,
        "indexed_git_head": stored.get("git_head"),
        "current_git_head": current.git_head,
        "generated_at": digest.get("generated_at"),
        "stale_reasons": reasons,
    }
