"""Repository Digest — Phase 3: Architecture screen additions.

Two presentation-level derivations over data Layer 1 already computes,
kept separate from repository_digest.py for the same reason
repository_digest_extras.py is: each concern stays independently
readable. Neither derivation here changes clustering, resolution, or any
other Layer 1 algorithm — both read already-computed artifacts and label
them.

  1. Lane classification (Frontend/API/Services/Data/Other) — a
     deterministic, path/extension-evidence-based label per domain. No
     LLM, no guessing: a domain only gets a specific lane when at least
     one of its files matches an explicit rule; otherwise it's "other".

  2. Relationship evidence — every cross-domain relationship this digest
     exposes is aggregated exclusively from concrete symbol-to-symbol
     reference edges (see RELATIONSHIP_EVIDENCE_TYPE's docstring for why
     that makes every one of them VERIFIED, and why a genuine INFERRED
     tier isn't derivable without Layer 1 changes that are out of scope
     here).
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

# ── Lane classification ──────────────────────────────────────────
#
# Per-file classification is evidence-based only: a directory segment or
# file extension/suffix that's a strong, unambiguous signal of that lane.
# Evaluated in a fixed priority order (DATA > API > FRONTEND > SERVICES)
# so a file matching more than one category (e.g. "api/models/user.py")
# still gets exactly one deterministic label. A file matching none of
# these signals casts no vote — it does not default to any lane.

_DATA_SEGMENTS = {
    "models", "model", "entities", "entity", "repository", "repositories",
    "dao", "daos", "migrations", "migration", "schema", "schemas",
    "database", "db",
}
_DATA_EXTENSIONS = {"sql"}
_DATA_SUFFIXES = ("repository", "entity", "dao", "model")

_API_SEGMENTS = {
    "api", "apis", "controller", "controllers", "routes", "route",
    "endpoints", "endpoint", "resolvers", "resolver", "graphql", "rest",
}
_API_SUFFIXES = ("controller",)

_FRONTEND_SEGMENTS = {
    "frontend", "client", "ui", "components", "component", "pages",
    "page", "views", "view", "web", "public",
}
_FRONTEND_EXTENSIONS = {"tsx", "jsx", "vue", "svelte", "css", "scss"}

_SERVICES_SEGMENTS = {
    "services", "service", "domain", "core", "business", "usecases",
    "usecase",
}
_SERVICES_SUFFIXES = ("service",)

_LANE_PRIORITY = ("data", "api", "frontend", "services")


def classify_file_lane(path: str) -> str | None:
    """Classify a single file's lane from its path alone. Returns None
    (no vote) when no rule matches — never guesses.
    """
    p = PurePosixPath(path.replace("\\", "/"))
    segments = {seg.lower() for seg in p.parts[:-1]}
    ext = p.suffix.lstrip(".").lower()
    stem = p.stem.lower()

    if (
        segments & _DATA_SEGMENTS
        or ext in _DATA_EXTENSIONS
        or any(stem.endswith(suf) for suf in _DATA_SUFFIXES)
    ):
        return "data"
    if segments & _API_SEGMENTS or any(stem.endswith(suf) for suf in _API_SUFFIXES):
        return "api"
    if segments & _FRONTEND_SEGMENTS or ext in _FRONTEND_EXTENSIONS:
        return "frontend"
    if segments & _SERVICES_SEGMENTS or any(stem.endswith(suf) for suf in _SERVICES_SUFFIXES):
        return "services"
    return None


def classify_domain_lane(files: list[str]) -> str:
    """A domain's lane is a plurality vote across its files' per-file
    lanes. "other" when zero files cast a vote (no confident evidence
    anywhere in the domain) — never a default guess. Ties are broken by
    the same fixed priority order used per-file, so the result is fully
    deterministic regardless of file iteration order.
    """
    counts = {lane: 0 for lane in _LANE_PRIORITY}
    for f in files:
        lane = classify_file_lane(f)
        if lane:
            counts[lane] += 1

    if not any(counts.values()):
        return "other"

    top = max(counts.values())
    for lane in _LANE_PRIORITY:
        if counts[lane] == top:
            return lane
    return "other"  # unreachable — _LANE_PRIORITY covers every counted key


def annotate_domain_lanes(domains: list[dict[str, Any]], csg: dict[str, Any] | None) -> None:
    """Mutates each domain dict in place, adding "lane". Prefers the
    domain's full file list (csg["clusters"][*]["files"]) so classification
    considers the whole domain, not just its top-5 representative_files;
    falls back to representative_files only if the cluster can't be found.
    """
    files_by_cluster: dict[str, list[str]] = {}
    if csg:
        for cluster in csg.get("clusters") or []:
            cid = cluster.get("id")
            if cid:
                files_by_cluster[cid] = cluster.get("files") or []

    for d in domains:
        files = files_by_cluster.get(d.get("id"))
        if files is None:
            files = d.get("representative_files") or []
        d["lane"] = classify_domain_lane(files)


# ── Relationship evidence ────────────────────────────────────────

RELATIONSHIP_EVIDENCE_TYPE = "verified"
"""
Every cluster_edge the CSG builder produces (lib/context/csg.py and
lib/context/layer1_domain_clustering.py's build_layer_c_from_files) is
aggregated exclusively from concrete symbol-to-symbol reference edges —
calls, instantiates, references_type, accesses, contains, inherits,
implements — each one a real AST-derived reference tree-sitter extracted
from source. There is currently no code path in this pipeline that
produces a cluster-level relationship from indirect/domain-level evidence
(co-occurrence, naming similarity, directory proximity, ...). So every
relationship this digest exposes is, by construction, VERIFIED — this is
a statement of fact about how cluster_edges are built, not an invented
confidence value.

A genuine INFERRED tier was attempted and reverted: tagging a
cluster_edge INFERRED whenever any contributing symbol pair resolved via
_resolve_reference's third strategy (global unambiguous name match,
rather than same-file or import-linked) sounds like a reasonable proxy
for "less certain," but validating it against real Workbench/PetClinic
builds showed it mislabels ~100% of relationships as INFERRED. Reason:
Java (and similarly-scoped languages) never emits an import statement
for a same-package sibling class, so the overwhelming majority of
legitimate intra-package references resolve via that same "global name
match" strategy — the strategy that matched is not a reliable proxy for
confidence, because it conflates "no explicit import" (simply how the
language works for same-package access) with "coincidentally unique
name" (genuinely less certain). A meaningful INFERRED tier would need
Layer 1 to distinguish those two cases directly (e.g. same-package/
directory scoping awareness) — real semantic instrumentation, not the
small change this looked like, and out of scope here as a result.
"""


def sample_references(edge: dict[str, Any], cap: int = 3) -> list[dict[str, str]]:
    """A small, real sample of the concrete symbol-to-symbol reference
    pairs backing a cluster_edge — already computed and capped at 20 by
    Layer 1 (see cluster_edge_counts in csg.py / layer1_domain_clustering.py),
    just not previously threaded through to the digest. Never fabricated:
    an edge with no symbols sample yields an empty list, not a guess.
    """
    symbols = edge.get("symbols") or []
    return [
        {"from": s.get("from", ""), "to": s.get("to", "")}
        for s in symbols[:cap]
        if s.get("from") and s.get("to")
    ]
