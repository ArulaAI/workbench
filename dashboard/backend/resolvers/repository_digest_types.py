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


@strawberry.type
class DigestRelationship:
    source: str
    target: str
    weight: int


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

    _domains: strawberry.Private[list[dict[str, Any]]]
    _relationships: strawberry.Private[list[dict[str, Any]]]
    _entrypoints: strawberry.Private[list[dict[str, Any]]]
    _commands: strawberry.Private[list[dict[str, Any]]]
    _hotspots: strawberry.Private[list[dict[str, Any]]]
    _conventions: strawberry.Private[list[dict[str, Any]]]
    _risks: strawberry.Private[list[dict[str, Any]]]
    _gaps: strawberry.Private[list[dict[str, Any]]]
    _readiness: strawberry.Private[list[dict[str, Any]]]

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
            )
            for d in self._domains[:limit]
        ]

    @strawberry.field
    def relationships(self, limit: int = 30) -> list[DigestRelationship]:
        _validate_limit(limit)
        return [DigestRelationship(source=r["from"], target=r["to"], weight=r.get("weight", 0)) for r in self._relationships[:limit]]

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
                       severity=_RISK_SEVERITY.get(r["type"], "medium"), evidence=_to_evidence(r.get("evidence", [])))
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


class _LimitError(ValueError):
    pass


def _validate_limit(limit: int) -> None:
    if not (1 <= limit <= 100):
        raise _LimitError(f"limit must be between 1 and 100, got {limit}")


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
        _domains=data.get("domains", []),
        _relationships=data.get("relationships", []),
        _entrypoints=data.get("entrypoints", []),
        _commands=data.get("commands", []),
        _hotspots=data.get("hotspots", []),
        _conventions=data.get("conventions", []),
        _risks=data.get("risks", []),
        _gaps=data.get("gaps", []),
        _readiness=data.get("readiness", []),
    )


@strawberry.type
class RepositoryDigestBuildStatus:
    state: DigestEffectiveState
    started_at: Optional[str]
    completed_at: Optional[str]
    last_error: Optional[str]
    has_readable_digest: bool
    indexed_git_head: Optional[str]
    current_git_head: Optional[str]
    stale_reasons: list[str]


def to_build_status(data: dict[str, Any]) -> RepositoryDigestBuildStatus:
    return RepositoryDigestBuildStatus(
        state=DigestEffectiveState(data["state"]),
        started_at=data.get("started_at"), completed_at=data.get("completed_at"),
        last_error=data.get("last_error"), has_readable_digest=data["has_readable_digest"],
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
