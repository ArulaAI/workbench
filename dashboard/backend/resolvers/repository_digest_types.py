"""Strawberry GraphQL types for Repository Digest.

Mirrors specs/tech/speed-repository-digest-dashboard.md > API Surface.
Conversion helpers translate the internal lowercase-string dict shape
(lib/context/repository_digest.py's output) into these typed objects.
"""

from __future__ import annotations

import enum
from typing import Any, Optional

import strawberry


@strawberry.enum
class DigestStatus(enum.Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


@strawberry.enum
class DigestEffectiveState(enum.Enum):
    MISSING = "MISSING"
    GENERATING = "GENERATING"
    CURRENT = "CURRENT"
    STALE = "STALE"
    ERROR = "ERROR"


@strawberry.enum
class DigestConfidence(enum.Enum):
    CONFIRMED = "confirmed"
    DERIVED = "derived"
    INFERRED = "inferred"
    UNKNOWN = "unknown"


@strawberry.enum
class DigestCapabilityStatus(enum.Enum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    INVALID = "invalid"
    STALE = "stale"


@strawberry.enum
class DigestCommandPurpose(enum.Enum):
    RUN = "run"
    DEVELOP = "develop"
    BUILD = "build"
    TEST = "test"
    LINT = "lint"
    TYPECHECK = "typecheck"
    FORMAT = "format"
    MIGRATE = "migrate"
    WORKER = "worker"
    OTHER = "other"


def _safe_enum(enum_cls: type, value: Optional[str], default: Any) -> Any:
    """Convert a raw stored string to a Strawberry enum member, falling
    back to `default` for anything unrecognized rather than raising —
    every digest enum field needs this same safety net.
    """
    try:
        return enum_cls(value)
    except ValueError:
        return default


def _confidence(value: Optional[str]) -> DigestConfidence:
    return _safe_enum(DigestConfidence, value, DigestConfidence.UNKNOWN)


def _purpose(value: Optional[str]) -> DigestCommandPurpose:
    return _safe_enum(DigestCommandPurpose, value, DigestCommandPurpose.OTHER)


def _capability_status(value: Optional[str]) -> DigestCapabilityStatus:
    return _safe_enum(DigestCapabilityStatus, value, DigestCapabilityStatus.UNAVAILABLE)


@strawberry.type
class DigestEvidence:
    source: str
    path: Optional[str]
    line: Optional[int]
    symbol: Optional[str]
    artifact_key: Optional[str]
    description: str


def _to_evidence(items: list[dict[str, Any]]) -> list[DigestEvidence]:
    return [
        DigestEvidence(
            source=e.get("source", ""), path=e.get("path"), line=e.get("line"),
            symbol=e.get("symbol"), artifact_key=e.get("artifact_key"),
            description=e.get("description", ""),
        )
        for e in items
    ]


@strawberry.type
class DigestFreshness:
    state: str
    indexed_git_head: Optional[str]
    current_git_head: Optional[str]
    generated_at: Optional[str]
    stale_reasons: list[str]


@strawberry.type
class DigestIdentity:
    name: str
    summary: str
    confidence: DigestConfidence
    evidence: list[DigestEvidence]


@strawberry.type
class DigestLanguage:
    name: str
    files: int
    lines: int
    percent: float


@strawberry.type
class DigestFootprint:
    file_count: int
    line_count: int
    source_file_count: int
    config_file_count: int
    asset_file_count: int
    symbol_count: Optional[int]
    domain_count: Optional[int]
    cross_domain_relationship_count: Optional[int]
    languages: list[DigestLanguage]


@strawberry.type
class DigestDomain:
    id: str
    label: str
    summary: str
    confidence: DigestConfidence
    file_count: int
    symbol_count: int
    cohesion: Optional[float]
    avg_blast_radius: float
    representative_files: list[str]
    representative_symbols: list[str]
    depends_on: list[str]
    used_by: list[str]
    evidence: list[DigestEvidence]
    lane: str
    """Deterministic Frontend/API/Services/Data/Other classification —
    see lib/context/repository_digest_architecture.py:classify_domain_lane.
    "other" on an old digest predating this field, never a guess."""


@strawberry.type
class DigestSymbolReference:
    source_symbol: str
    target_symbol: str


@strawberry.type
class DigestRelationship:
    source: str
    target: str
    weight: int
    evidence_type: str
    """Always "verified" today — see RELATIONSHIP_EVIDENCE_TYPE's docstring
    in repository_digest_architecture.py for why this pipeline currently
    produces no other category. "unknown" on an old digest predating this
    field."""
    sample_references: list[DigestSymbolReference]


@strawberry.type
class DigestEntrypoint:
    name: str
    file: str
    kind: str


@strawberry.type
class DigestCommand:
    purpose: DigestCommandPurpose
    command: str
    working_directory: str
    confidence: DigestConfidence
    evidence: list[DigestEvidence]


@strawberry.type
class DigestHotspot:
    symbol_id: str
    name: str
    file: str
    line: int
    domain_id: str
    blast_radius: int
    dependents: int
    centrality: float
    reason: str
    evidence: list[DigestEvidence]


@strawberry.type
class DigestConvention:
    text: str
    scope: list[str]
    confidence: DigestConfidence
    evidence: list[DigestEvidence]


@strawberry.type
class DigestRisk:
    type: str
    description: str
    severity: str
    evidence: list[DigestEvidence]
    domain_id: str


@strawberry.type
class DigestGap:
    type: str
    description: str
    evidence: list[DigestEvidence]


@strawberry.type
class DigestReadiness:
    capability: str
    status: DigestCapabilityStatus
    reason: Optional[str]
    remediation: Optional[str]


@strawberry.type
class DigestCoverageStats:
    """Sourced from build-summary.json's extraction_stats — see
    lib/context/repository_digest_extras.py:derive_coverage_stats. Never
    constructed with fabricated numbers: absent build-summary.json (never
    built, or predates source_files_total) means this whole type is None
    on RepositoryDigest, not a zero-filled instance of it.
    """
    source_files_total: int
    source_files_parsed: int
    parse_coverage_pct: Optional[float]
    symbols_extracted: Optional[int]
    references_extracted: Optional[int]


@strawberry.type
class DigestAnnotatedDirectory:
    path: str
    file_count: int
    total_lines: int
    dominant_domain_label: Optional[str]


@strawberry.type
class DigestReadingPathItem:
    file: str
    reason: str
    kind: str


@strawberry.type
class DigestKnowledgeEntry:
    """Approved project knowledge — .speed/memory/project-knowledge.json."""
    id: str
    knowledge: str
    why_it_matters: str
    applies_to: list[str]
    last_verified: Optional[str]
    staleness_flag: str


# ── Phase 4: API & Data ──────────────────────────────────────────


@strawberry.type
class DigestRoute:
    """A discovered API route. Never derived from a filename — only an
    actual matched decorator/call in source produces an entry. See
    lib/context/repository_digest_api_data.py."""
    method: str
    path: str
    file: str
    line: int
    handler: str
    framework: str
    evidence: list[DigestEvidence]


@strawberry.type
class DigestEntityColumn:
    name: str
    type: str
    primary_key: bool


@strawberry.type
class DigestEntityRelationship:
    field: str
    target_entity: Optional[str]
    cardinality: str
    """Always "unknown" today — Layer 1 hardcodes "one-to-many" for every
    ORM relationship() match regardless of actual cardinality, which is
    not evidence, so it is never surfaced as if it were verified."""


@strawberry.type
class DigestEntity:
    """An ORM model class. columns/relationships are reconstructed via a
    disclosed nearest-enclosing-class heuristic, not a direct structural
    link Layer 1 tracks — see columns_inferred and the module docstring
    in lib/context/repository_digest_api_data.py. table_name is always
    null: Layer 1 never computes it anywhere today."""
    name: str
    file: Optional[str]
    line: Optional[int]
    table_name: Optional[str]
    language: Optional[str]
    columns: list[DigestEntityColumn]
    columns_inferred: bool
    relationships: list[DigestEntityRelationship]
    evidence: list[DigestEvidence]


@strawberry.type
class DigestPersistenceSummary:
    mode: str
    entity_count: int
    by_language: strawberry.scalars.JSON


@strawberry.type
class DigestApiData:
    routes: list[DigestRoute]
    entities: list[DigestEntity]
    persistence_summary: Optional[DigestPersistenceSummary]


# ── Phase 4: CI/CD ────────────────────────────────────────────────


@strawberry.type
class DigestCiJob:
    name: str
    runs_on: Optional[str]
    needs: list[str]
    commands: list[str]


@strawberry.type
class DigestCiWorkflow:
    name: str
    provider: str
    config_file: str
    triggers: list[str]
    jobs: list[DigestCiJob]
    evidence: list[DigestEvidence]


@strawberry.type
class DigestOtherCiProvider:
    """File-presence-only detection — never claims parsed job/stage
    structure for a provider this backend cannot reliably read."""
    provider: str
    config_file: str
    evidence: list[DigestEvidence]


@strawberry.type
class DigestCicd:
    workflows: list[DigestCiWorkflow]
    other_providers_detected: list[DigestOtherCiProvider]


# ── Phase 4: Runtime & Configuration ─────────────────────────────


@strawberry.type
class DigestRuntime:
    language: str
    version: Optional[str]
    source_file: str
    evidence: list[DigestEvidence]


@strawberry.type
class DigestFramework:
    name: str
    version: Optional[str]
    source_file: str
    evidence: list[DigestEvidence]


@strawberry.type
class DigestConfigSource:
    file: str
    evidence: list[DigestEvidence]


@strawberry.type
class DigestEnvironmentVariable:
    """name only — see lib/context/repository_digest_runtime.py's module
    docstring for the redaction discipline. No field on this type, and no
    code path producing it, ever carries a secret value."""
    name: str
    source_file: str
    looks_sensitive: bool
    evidence: list[DigestEvidence]


@strawberry.type
class DigestRuntimeConfig:
    runtimes: list[DigestRuntime]
    frameworks: list[DigestFramework]
    config_sources: list[DigestConfigSource]
    environment_variables: list[DigestEnvironmentVariable]


# ── Phase 5A: Security ────────────────────────────────────────────


@strawberry.type
class DigestSecretIndicator:
    """A value is NEVER present on this type — see
    lib/context/repository_digest_security.py's module docstring for the
    three detection tiers (declared_name / hardcoded_value_pattern /
    committed_key_file), none of which ever captures the secret itself."""
    category: str
    pattern_type: Optional[str]
    name: str
    file: str
    line: Optional[int]
    redacted: bool
    evidence: list[DigestEvidence]


@strawberry.type
class DigestSensitiveConfigFinding:
    category: str
    title: str
    description: str
    severity: Optional[str]
    """Only ever set for the small set of objectively-established
    anti-patterns this module detects (TLS verification disabled, CORS
    wildcard, root container, hardcoded DEBUG) — never invented."""
    file: str
    line: Optional[int]
    evidence: list[DigestEvidence]


@strawberry.type
class DigestAuthIndicator:
    """Presence-only — a known auth dependency or guard/decorator pattern
    was found. No claim about whether auth is correctly implemented."""
    type: str
    name: str
    file: str
    line: Optional[int]
    evidence: list[DigestEvidence]


@strawberry.type
class DigestSecurityTool:
    name: str
    file: str
    evidence: list[DigestEvidence]


@strawberry.type
class DigestSecurity:
    secret_indicators: list[DigestSecretIndicator]
    sensitive_configuration: list[DigestSensitiveConfigFinding]
    authentication_indicators: list[DigestAuthIndicator]
    security_tooling_detected: list[DigestSecurityTool]


# ── Phase 5B: Changes History ─────────────────────────────────────


@strawberry.enum
class DigestChangesStatus(enum.Enum):
    FIRST_RUN = "first_run"
    COMPARED = "compared"


@strawberry.type
class DigestSnapshotMeta:
    generated_at: Optional[str]
    git_head: Optional[str]
    identity_name: Optional[str]
    schema_version: Optional[int]


@strawberry.type
class DigestChangeItem:
    key: str
    title: str
    evidence: list[DigestEvidence]


@strawberry.type
class DigestChangeFieldDiff:
    field: str
    before: Optional[strawberry.scalars.JSON]
    after: Optional[strawberry.scalars.JSON]


@strawberry.type
class DigestChangedItem:
    key: str
    title: str
    fields: list[DigestChangeFieldDiff]
    evidence: list[DigestEvidence]


@strawberry.type
class DigestChangeSection:
    key: str
    label: str
    available: bool
    """False when this section was not present in one of the two
    snapshots (predates that build's schema) — never conflated with a
    real added/removed/changed result. See `reason`."""
    reason: Optional[str]
    added: list[DigestChangeItem]
    removed: list[DigestChangeItem]
    changed: list[DigestChangedItem]


@strawberry.type
class DigestChangesHistory:
    """Computed at read time from repository-digest.json and
    repository-digest-previous.json — never persisted into either file,
    so neither one ever contains a copy of the other's history. See
    lib/context/repository_digest_changes.py."""
    status: DigestChangesStatus
    previous_snapshot: Optional[DigestSnapshotMeta]
    current_snapshot: Optional[DigestSnapshotMeta]
    summary: list[str]
    sections: list[DigestChangeSection]
    warnings: list[str]


@strawberry.type
class DigestKnowledgeDraft:
    """Pending, unreviewed — .speed/memory/project-knowledge-drafts.json.
    Never influences the main digest's conclusions; surfaced separately so
    the UI can keep it visibly distinct from approved knowledge.
    """
    id: str
    knowledge: str
    why_it_matters: str
    applies_to: list[str]
    source: str
    draft_reason: str


_RISK_SEVERITY = {
    "high_blast_radius": "high", "cross_domain_hub": "high",
    "repeated_failure": "medium", "stale_knowledge": "medium",
    "conflicting_discovery": "medium",
}


@strawberry.type
class RepositoryDigest:
    schema_version: int
    status: DigestStatus
    effective_state: DigestEffectiveState
    generated_at: str
    freshness: DigestFreshness
    identity: DigestIdentity
    footprint: DigestFootprint
    warnings: list[str]
    coverage_stats: Optional[DigestCoverageStats]
    api_data: Optional[DigestApiData]
    cicd: Optional[DigestCicd]
    runtime_config: Optional[DigestRuntimeConfig]
    security: Optional[DigestSecurity]
    changes_history: Optional[DigestChangesHistory]

    _domains: strawberry.Private[list[dict[str, Any]]]
    _relationships: strawberry.Private[list[dict[str, Any]]]
    _entrypoints: strawberry.Private[list[dict[str, Any]]]
    _commands: strawberry.Private[list[dict[str, Any]]]
    _hotspots: strawberry.Private[list[dict[str, Any]]]
    _conventions: strawberry.Private[list[dict[str, Any]]]
    _risks: strawberry.Private[list[dict[str, Any]]]
    _gaps: strawberry.Private[list[dict[str, Any]]]
    _readiness: strawberry.Private[list[dict[str, Any]]]
    _annotated_tree: strawberry.Private[list[dict[str, Any]]]
    _reading_path: strawberry.Private[list[dict[str, Any]]]
    _approved_knowledge: strawberry.Private[list[dict[str, Any]]]
    _pending_knowledge: strawberry.Private[list[dict[str, Any]]]

    @strawberry.field
    def domains(self, limit: int = 10) -> list[DigestDomain]:
        _validate_limit(limit)
        return [
            DigestDomain(
                id=d["id"], label=d["label"], summary=d.get("summary", ""),
                confidence=_confidence(d.get("confidence")), file_count=d["file_count"],
                symbol_count=d["symbol_count"], cohesion=d.get("cohesion"),
                avg_blast_radius=d.get("avg_blast_radius", 0.0),
                representative_files=d.get("representative_files", []),
                representative_symbols=d.get("representative_symbols", []),
                depends_on=d.get("depends_on", []), used_by=d.get("used_by", []),
                evidence=_to_evidence(d.get("evidence", [])),
                lane=d.get("lane", "other"),
            )
            for d in self._domains[:limit]
        ]

    @strawberry.field
    def relationships(self, limit: int = 30) -> list[DigestRelationship]:
        _validate_limit(limit)
        return [
            DigestRelationship(
                source=r["from"], target=r["to"], weight=r.get("weight", 0),
                evidence_type=r.get("evidence_type", "unknown"),
                sample_references=[
                    DigestSymbolReference(source_symbol=s.get("from", ""), target_symbol=s.get("to", ""))
                    for s in r.get("sample_references", [])
                ],
            )
            for r in self._relationships[:limit]
        ]

    @strawberry.field
    def entrypoints(self, limit: int = 10) -> list[DigestEntrypoint]:
        _validate_limit(limit)
        return [DigestEntrypoint(name=e.get("name", ""), file=e.get("file", ""), kind=e.get("kind", "")) for e in self._entrypoints[:limit]]

    @strawberry.field
    def commands(self) -> list[DigestCommand]:
        return [
            DigestCommand(
                purpose=_purpose(c.get("purpose")), command=c["command"],
                working_directory=c.get("working_directory", "."),
                confidence=_confidence(c.get("confidence")), evidence=_to_evidence(c.get("evidence", [])),
            )
            for c in self._commands
        ]

    @strawberry.field
    def hotspots(self, limit: int = 10) -> list[DigestHotspot]:
        _validate_limit(limit)
        return [
            DigestHotspot(
                symbol_id=h["symbol_id"], name=h["name"], file=h["file"], line=h["line"],
                domain_id=h.get("domain_id", ""), blast_radius=h["blast_radius"], dependents=h["dependents"],
                centrality=h.get("centrality", 0.0), reason=h.get("reason", ""),
                evidence=_to_evidence(h.get("evidence", [])),
            )
            for h in self._hotspots[:limit]
        ]

    @strawberry.field
    def conventions(self, limit: int = 10) -> list[DigestConvention]:
        _validate_limit(limit)
        return [
            DigestConvention(text=c["text"], scope=c.get("scope", []), confidence=_confidence(c.get("confidence")),
                              evidence=_to_evidence(c.get("evidence", [])))
            for c in self._conventions[:limit]
        ]

    @strawberry.field
    def risks(self, limit: int = 10) -> list[DigestRisk]:
        _validate_limit(limit)
        return [
            DigestRisk(type=r["type"], description=r["description"],
                       severity=_RISK_SEVERITY.get(r["type"], "medium"), evidence=_to_evidence(r.get("evidence", [])),
                       domain_id=r.get("domain_id", ""))
            for r in self._risks[:limit]
        ]

    @strawberry.field
    def gaps(self) -> list[DigestGap]:
        return [DigestGap(type=g["type"], description=g["description"], evidence=_to_evidence(g.get("evidence", []))) for g in self._gaps]

    @strawberry.field
    def readiness(self) -> list[DigestReadiness]:
        return [
            DigestReadiness(capability=r["capability"], status=_capability_status(r["status"]),
                            reason=r.get("reason"), remediation=r.get("remediation"))
            for r in self._readiness
        ]

    @strawberry.field
    def annotated_tree(self) -> list[DigestAnnotatedDirectory]:
        return [
            DigestAnnotatedDirectory(
                path=d["path"], file_count=d.get("file_count", 0), total_lines=d.get("total_lines", 0),
                dominant_domain_label=d.get("dominant_domain_label"),
            )
            for d in self._annotated_tree
        ]

    @strawberry.field
    def reading_path(self) -> list[DigestReadingPathItem]:
        return [
            DigestReadingPathItem(file=r["file"], reason=r.get("reason", ""), kind=r.get("kind", ""))
            for r in self._reading_path
        ]

    @strawberry.field
    def approved_knowledge(self) -> list[DigestKnowledgeEntry]:
        return [
            DigestKnowledgeEntry(
                id=e["id"], knowledge=e.get("knowledge", ""), why_it_matters=e.get("why_it_matters", ""),
                applies_to=e.get("applies_to", []), last_verified=e.get("last_verified"),
                staleness_flag=e.get("staleness_flag", ""),
            )
            for e in self._approved_knowledge
        ]

    @strawberry.field
    def pending_knowledge(self) -> list[DigestKnowledgeDraft]:
        return [
            DigestKnowledgeDraft(
                id=e["id"], knowledge=e.get("knowledge", ""), why_it_matters=e.get("why_it_matters", ""),
                applies_to=e.get("applies_to", []), source=e.get("source", ""),
                draft_reason=e.get("draft_reason", ""),
            )
            for e in self._pending_knowledge
        ]


def _validate_limit(limit: int) -> None:
    if not (1 <= limit <= 100):
        raise ValueError(f"limit must be between 1 and 100, got {limit}")


def to_repository_digest(data: dict[str, Any]) -> RepositoryDigest:
    freshness = data.get("_freshness", {})
    return RepositoryDigest(
        schema_version=data["schema_version"],
        status=DigestStatus(data["status"]) if data["status"] in ("complete", "partial", "failed") else DigestStatus.FAILED,
        effective_state=DigestEffectiveState(data.get("_effective_state", "CURRENT")),
        generated_at=data["generated_at"],
        freshness=DigestFreshness(
            state=freshness.get("state", "CURRENT"), indexed_git_head=freshness.get("indexed_git_head"),
            current_git_head=freshness.get("current_git_head"), generated_at=freshness.get("generated_at"),
            stale_reasons=freshness.get("stale_reasons", []),
        ),
        identity=DigestIdentity(
            name=data["identity"]["name"], summary=data["identity"]["summary"],
            confidence=_confidence(data["identity"].get("confidence")), evidence=_to_evidence(data["identity"].get("evidence", [])),
        ),
        footprint=DigestFootprint(
            file_count=data["footprint"]["file_count"], line_count=data["footprint"]["line_count"],
            source_file_count=data["footprint"].get("source_file_count", 0),
            config_file_count=data["footprint"].get("config_file_count", 0),
            asset_file_count=data["footprint"].get("asset_file_count", 0),
            symbol_count=data["footprint"].get("symbol_count"), domain_count=data["footprint"].get("domain_count"),
            cross_domain_relationship_count=data["footprint"].get("cross_domain_relationship_count"),
            languages=[DigestLanguage(**lang) for lang in data["footprint"].get("languages", [])],
        ),
        warnings=data.get("warnings", []),
        coverage_stats=_to_coverage_stats(data.get("coverage_stats")),
        api_data=_to_api_data(data.get("api_data")),
        cicd=_to_cicd(data.get("cicd")),
        runtime_config=_to_runtime_config(data.get("runtime_config")),
        security=_to_security(data.get("security")),
        changes_history=_to_changes_history(data.get("_changes_history")),
        _domains=data.get("domains", []),
        _relationships=data.get("relationships", []),
        _entrypoints=data.get("entrypoints", []),
        _commands=data.get("commands", []),
        _hotspots=data.get("hotspots", []),
        _conventions=data.get("conventions", []),
        _risks=data.get("risks", []),
        _gaps=data.get("gaps", []),
        _readiness=data.get("readiness", []),
        # .get(..., []) rather than data["..."]: a digest built before
        # Phase 2 existed simply won't have these keys, and must still
        # load — not crash — as an old digest with no coverage/tree/
        # reading-path/knowledge data, which is the true state of affairs.
        _annotated_tree=data.get("annotated_tree", []),
        _reading_path=data.get("reading_path", []),
        _approved_knowledge=data.get("approved_knowledge", []),
        _pending_knowledge=data.get("pending_knowledge", []),
    )


def _to_coverage_stats(raw: Optional[dict[str, Any]]) -> Optional[DigestCoverageStats]:
    if not isinstance(raw, dict):
        return None
    source_total = raw.get("source_files_total")
    parsed = raw.get("source_files_parsed")
    if not isinstance(source_total, int) or not isinstance(parsed, int):
        return None
    return DigestCoverageStats(
        source_files_total=source_total, source_files_parsed=parsed,
        parse_coverage_pct=raw.get("parse_coverage_pct"),
        symbols_extracted=raw.get("symbols_extracted"), references_extracted=raw.get("references_extracted"),
    )


def _to_api_data(raw: Optional[dict[str, Any]]) -> Optional[DigestApiData]:
    if not isinstance(raw, dict):
        return None
    routes = [
        DigestRoute(
            method=r.get("method", ""), path=r.get("path", ""), file=r.get("file", ""),
            line=r.get("line", 0), handler=r.get("handler", ""), framework=r.get("framework", ""),
            evidence=_to_evidence(r.get("evidence", [])),
        )
        for r in raw.get("routes") or []
    ]
    entities = [
        DigestEntity(
            name=e.get("name", ""), file=e.get("file"), line=e.get("line"),
            table_name=e.get("table_name"), language=e.get("language"),
            columns=[DigestEntityColumn(name=c.get("name", ""), type=c.get("type", "unknown"), primary_key=bool(c.get("primary_key"))) for c in e.get("columns") or []],
            columns_inferred=bool(e.get("columns_inferred")),
            relationships=[
                DigestEntityRelationship(field=r.get("field", ""), target_entity=r.get("target_entity"), cardinality=r.get("cardinality", "unknown"))
                for r in e.get("relationships") or []
            ],
            evidence=_to_evidence(e.get("evidence", [])),
        )
        for e in raw.get("entities") or []
    ]
    summary_raw = raw.get("persistence_summary")
    summary = (
        DigestPersistenceSummary(
            mode=summary_raw.get("mode", "unknown"), entity_count=summary_raw.get("entity_count", 0),
            by_language=summary_raw.get("by_language", {}),
        )
        if isinstance(summary_raw, dict) else None
    )
    return DigestApiData(routes=routes, entities=entities, persistence_summary=summary)


def _to_cicd(raw: Optional[dict[str, Any]]) -> Optional[DigestCicd]:
    if not isinstance(raw, dict):
        return None
    workflows = [
        DigestCiWorkflow(
            name=w.get("name", ""), provider=w.get("provider", ""), config_file=w.get("config_file", ""),
            triggers=w.get("triggers", []),
            jobs=[
                DigestCiJob(name=j.get("name", ""), runs_on=j.get("runs_on"), needs=j.get("needs", []), commands=j.get("commands", []))
                for j in w.get("jobs") or []
            ],
            evidence=_to_evidence(w.get("evidence", [])),
        )
        for w in raw.get("workflows") or []
    ]
    other = [
        DigestOtherCiProvider(provider=p.get("provider", ""), config_file=p.get("config_file", ""), evidence=_to_evidence(p.get("evidence", [])))
        for p in raw.get("other_providers_detected") or []
    ]
    return DigestCicd(workflows=workflows, other_providers_detected=other)


def _to_runtime_config(raw: Optional[dict[str, Any]]) -> Optional[DigestRuntimeConfig]:
    if not isinstance(raw, dict):
        return None
    return DigestRuntimeConfig(
        runtimes=[
            DigestRuntime(language=r.get("language", ""), version=r.get("version"), source_file=r.get("source_file", ""), evidence=_to_evidence(r.get("evidence", [])))
            for r in raw.get("runtimes") or []
        ],
        frameworks=[
            DigestFramework(name=f.get("name", ""), version=f.get("version"), source_file=f.get("source_file", ""), evidence=_to_evidence(f.get("evidence", [])))
            for f in raw.get("frameworks") or []
        ],
        config_sources=[
            DigestConfigSource(file=c.get("file", ""), evidence=_to_evidence(c.get("evidence", [])))
            for c in raw.get("config_sources") or []
        ],
        environment_variables=[
            DigestEnvironmentVariable(name=e.get("name", ""), source_file=e.get("source_file", ""), looks_sensitive=bool(e.get("looks_sensitive")), evidence=_to_evidence(e.get("evidence", [])))
            for e in raw.get("environment_variables") or []
        ],
    )


def _to_security(raw: Optional[dict[str, Any]]) -> Optional[DigestSecurity]:
    if not isinstance(raw, dict):
        return None
    return DigestSecurity(
        secret_indicators=[
            DigestSecretIndicator(
                category=i.get("category", ""), pattern_type=i.get("pattern_type"), name=i.get("name", ""),
                file=i.get("file", ""), line=i.get("line"), redacted=bool(i.get("redacted", True)),
                evidence=_to_evidence(i.get("evidence", [])),
            )
            for i in raw.get("secret_indicators") or []
        ],
        sensitive_configuration=[
            DigestSensitiveConfigFinding(
                category=c.get("category", ""), title=c.get("title", ""), description=c.get("description", ""),
                severity=c.get("severity"), file=c.get("file", ""), line=c.get("line"),
                evidence=_to_evidence(c.get("evidence", [])),
            )
            for c in raw.get("sensitive_configuration") or []
        ],
        authentication_indicators=[
            DigestAuthIndicator(
                type=a.get("type", ""), name=a.get("name", ""), file=a.get("file", ""), line=a.get("line"),
                evidence=_to_evidence(a.get("evidence", [])),
            )
            for a in raw.get("authentication_indicators") or []
        ],
        security_tooling_detected=[
            DigestSecurityTool(name=t.get("name", ""), file=t.get("file", ""), evidence=_to_evidence(t.get("evidence", [])))
            for t in raw.get("security_tooling_detected") or []
        ],
    )


def _to_snapshot_meta(raw: Optional[dict[str, Any]]) -> Optional[DigestSnapshotMeta]:
    if not isinstance(raw, dict):
        return None
    return DigestSnapshotMeta(
        generated_at=raw.get("generated_at"), git_head=raw.get("git_head"),
        identity_name=raw.get("identity_name"), schema_version=raw.get("schema_version"),
    )


def _to_change_section(raw: dict[str, Any]) -> DigestChangeSection:
    return DigestChangeSection(
        key=raw.get("key", ""), label=raw.get("label", ""), available=bool(raw.get("available")),
        reason=raw.get("reason"),
        added=[
            DigestChangeItem(key=i.get("key", ""), title=i.get("title", ""), evidence=_to_evidence(i.get("evidence", [])))
            for i in raw.get("added") or []
        ],
        removed=[
            DigestChangeItem(key=i.get("key", ""), title=i.get("title", ""), evidence=_to_evidence(i.get("evidence", [])))
            for i in raw.get("removed") or []
        ],
        changed=[
            DigestChangedItem(
                key=c.get("key", ""), title=c.get("title", ""),
                fields=[DigestChangeFieldDiff(field=f.get("field", ""), before=f.get("before"), after=f.get("after")) for f in c.get("fields") or []],
                evidence=_to_evidence(c.get("evidence", [])),
            )
            for c in raw.get("changed") or []
        ],
    )


def _to_changes_history(raw: Optional[dict[str, Any]]) -> Optional[DigestChangesHistory]:
    if not isinstance(raw, dict):
        return None
    status_raw = raw.get("status")
    status = DigestChangesStatus(status_raw) if status_raw in ("first_run", "compared") else DigestChangesStatus.FIRST_RUN
    return DigestChangesHistory(
        status=status,
        previous_snapshot=_to_snapshot_meta(raw.get("previous_snapshot")),
        current_snapshot=_to_snapshot_meta(raw.get("current_snapshot")),
        summary=raw.get("summary") or [],
        sections=[_to_change_section(s) for s in raw.get("sections") or []],
        warnings=raw.get("warnings") or [],
    )


@strawberry.type
class RepositoryDigestBuildStatus:
    state: DigestEffectiveState
    started_at: Optional[str]
    completed_at: Optional[str]
    last_error: Optional[str]
    has_readable_digest: bool
    has_project_map: bool
    indexed_git_head: Optional[str]
    current_git_head: Optional[str]
    stale_reasons: list[str]


def to_build_status(data: dict[str, Any]) -> RepositoryDigestBuildStatus:
    return RepositoryDigestBuildStatus(
        state=DigestEffectiveState(data["state"]),
        started_at=data.get("started_at"), completed_at=data.get("completed_at"),
        last_error=data.get("last_error"), has_readable_digest=data["has_readable_digest"],
        has_project_map=data.get("has_project_map", False),
        indexed_git_head=data.get("indexed_git_head"), current_git_head=data.get("current_git_head"),
        stale_reasons=data.get("stale_reasons", []),
    )


@strawberry.type
class RepositoryDigestRefreshResult:
    accepted: bool
    state: DigestEffectiveState
    message: str
    has_readable_digest: bool


def to_refresh_result(data: dict[str, Any]) -> RepositoryDigestRefreshResult:
    return RepositoryDigestRefreshResult(
        accepted=data["accepted"], state=DigestEffectiveState(data["state"]),
        message=data["message"], has_readable_digest=data["has_readable_digest"],
    )
