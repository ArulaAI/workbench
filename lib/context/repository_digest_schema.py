"""Schema constants, dataclasses, and validation helpers for repository-digest.json.

Schema version 1, per specs/tech/speed-repository-digest-dashboard.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Generic, Literal, TypeVar

SCHEMA_VERSION = 1


def load_toml_file(path: Path) -> dict[str, Any] | None:
    """Read a TOML file via tomllib (3.11+) or the tomli backport. Returns
    None if the file doesn't exist, no TOML library is available, or the
    file fails to parse — every caller here treats that identically to "no
    metadata available" rather than raising.
    """
    if not path.is_file():
        return None
    try:
        import tomllib  # type: ignore
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore
        except ImportError:
            return None
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except Exception:
        return None

GENERATOR_NAME = "speed-repository-digest"
GENERATOR_VERSION = str(SCHEMA_VERSION)

Confidence = Literal["confirmed", "derived", "inferred", "unknown"]
CONFIDENCE_VALUES: tuple[Confidence, ...] = ("confirmed", "derived", "inferred", "unknown")

DigestStatus = Literal["complete", "partial", "failed"]

EvidenceSource = Literal[
    "project_map",
    "semantic_graph",
    "documentation",
    "manifest",
    "project_instructions",
    "convention",
    "project_knowledge",
    "observation",
    "spec_alignment",
]

CapabilityStatus = Literal["available", "partial", "unavailable", "invalid", "stale"]
Capability = Literal[
    "project_map",
    "semantic_graph",
    "documentation",
    "manifests",
    "project_instructions",
    "conventions",
    "project_knowledge",
    "observations",
    "spec_alignment",
]

CommandPurpose = Literal[
    "run", "develop", "build", "test", "lint", "typecheck",
    "format", "migrate", "worker", "other",
]

# Validation Rules table
MAX_DOMAINS = 100
MAX_HOTSPOTS = 100
MAX_RISKS = 100
MAX_IDENTITY_SUMMARY_CHARS = 600
MAX_DOMAIN_SUMMARY_CHARS = 400
MAX_RISK_GAP_DESCRIPTION_CHARS = 500
MAX_COMMAND_CHARS = 500
MAX_REPRESENTATIVE_FILES = 5
MAX_REPRESENTATIVE_SYMBOLS = 5

T = TypeVar("T")


@dataclass
class InputResult(Generic[T]):
    """Wraps one optional discovery input so a missing/invalid source
    degrades to a readiness record instead of throwing through the
    pipeline. See RFC > Builder Design > Input isolation.
    """

    capability: str
    status: Literal["available", "partial", "unavailable", "invalid", "stale"]
    value: T | None
    reason: str | None
    warnings: list[str] = field(default_factory=list)
    source_path: str | None = None


def normalize_confidence(value: Any) -> Confidence:
    """Normalize an arbitrary confidence value. Unknown inputs become
    'unknown' rather than raising — see Validation Rules > Confidence.
    """
    if value in CONFIDENCE_VALUES:
        return value  # type: ignore[return-value]
    return "unknown"


def make_evidence(
    source: EvidenceSource,
    description: str,
    *,
    path: str | None = None,
    line: int | None = None,
    symbol: str | None = None,
    artifact_key: str | None = None,
) -> dict[str, Any]:
    """Build one EvidenceRef. At least one of path/symbol/artifact_key
    must be non-null — callers are expected to satisfy that; this helper
    does not silently invent a value.
    """
    return {
        "source": source,
        "path": path,
        "line": line,
        "symbol": symbol,
        "artifact_key": artifact_key,
        "description": description,
    }


def has_evidence_locator(evidence: dict[str, Any]) -> bool:
    """True if an EvidenceRef has at least one of path/symbol/artifact_key."""
    return bool(evidence.get("path") or evidence.get("symbol") or evidence.get("artifact_key"))


def truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def empty_digest_body() -> dict[str, Any]:
    """The array/object skeleton every digest carries, even when every
    optional input was unavailable. Matches the Top-level RepositoryDigest
    table's array fields.
    """
    return {
        "domains": [],
        "relationships": [],
        "entrypoints": [],
        "commands": [],
        "hotspots": [],
        "conventions": [],
        "risks": [],
        "gaps": [],
        "readiness": [],
        "warnings": [],
    }


def normalize_loaded_confidence(digest: dict[str, Any]) -> list[str]:
    """Fix up any out-of-range confidence value found in a *loaded* stored
    digest, in place, per Validation Rules > Confidence: "unknown input
    values normalize to unknown with a warning." The builder itself never
    produces an invalid confidence value, so this only matters for a
    digest written by an older/different tool. Returns the warnings to
    append; empty if nothing needed fixing.
    """
    warnings: list[str] = []

    def _fix(owner: str, obj: dict[str, Any] | None) -> None:
        if not isinstance(obj, dict):
            return
        value = obj.get("confidence")
        if value is not None and value not in CONFIDENCE_VALUES:
            obj["confidence"] = normalize_confidence(value)
            warnings.append(f"{owner} had confidence {value!r}, which is not a recognized value — normalized to 'unknown'")

    _fix("identity", digest.get("identity"))
    for domain in digest.get("domains") or []:
        _fix(f"domain {domain.get('id')!r}", domain)
    for command in digest.get("commands") or []:
        _fix(f"command {command.get('command')!r}", command)
    for convention in digest.get("conventions") or []:
        _fix("a convention entry", convention)

    return warnings


def validate_digest(digest: dict[str, Any]) -> list[str]:
    """Structural validation against the Top-level RepositoryDigest table
    and the Validation Rules section. Returns a list of issue strings;
    empty means valid. Does not raise — callers decide what an invalid
    digest means for their own control flow.
    """
    issues: list[str] = []

    if digest.get("schema_version") != SCHEMA_VERSION:
        issues.append(f"schema_version must be {SCHEMA_VERSION}, got {digest.get('schema_version')!r}")

    if digest.get("status") not in ("complete", "partial", "failed"):
        issues.append(f"status must be complete|partial|failed, got {digest.get('status')!r}")

    for required_array in (
        "domains", "relationships", "entrypoints", "commands", "hotspots",
        "conventions", "risks", "gaps", "readiness", "warnings",
    ):
        if not isinstance(digest.get(required_array), list):
            issues.append(f"{required_array} must be an array")

    if len(digest.get("domains") or []) > MAX_DOMAINS:
        issues.append(f"domains exceeds the {MAX_DOMAINS}-entry cap")
    if len(digest.get("hotspots") or []) > MAX_HOTSPOTS:
        issues.append(f"hotspots exceeds the {MAX_HOTSPOTS}-entry cap")
    if len(digest.get("risks") or []) > MAX_RISKS:
        issues.append(f"risks exceeds the {MAX_RISKS}-entry cap")

    identity = digest.get("identity") or {}
    summary = identity.get("summary") or ""
    if len(summary) > MAX_IDENTITY_SUMMARY_CHARS:
        issues.append("identity.summary exceeds 600 characters")
    if summary and not identity.get("evidence"):
        issues.append("identity.summary is non-empty but has no evidence")
    issues.extend(_evidence_issues("identity", identity.get("evidence") or []))
    if identity.get("confidence") is not None and identity["confidence"] not in CONFIDENCE_VALUES:
        issues.append(f"identity.confidence must be one of {CONFIDENCE_VALUES}, got {identity['confidence']!r}")

    for domain in digest.get("domains") or []:
        if len(domain.get("summary") or "") > MAX_DOMAIN_SUMMARY_CHARS:
            issues.append(f"domain {domain.get('id')!r} summary exceeds 400 characters")
        if not domain.get("evidence"):
            issues.append(f"domain {domain.get('id')!r} has no evidence")
        issues.extend(_evidence_issues(f"domain {domain.get('id')!r}", domain.get("evidence") or []))
        if domain.get("confidence") is not None and domain["confidence"] not in CONFIDENCE_VALUES:
            issues.append(f"domain {domain.get('id')!r} confidence must be one of {CONFIDENCE_VALUES}, got {domain['confidence']!r}")

    for command in digest.get("commands") or []:
        if len(command.get("command") or "") > MAX_COMMAND_CHARS:
            issues.append("a command exceeds 500 characters")
        if "\x00" in (command.get("command") or ""):
            issues.append("a command contains a NUL byte")
        if not command.get("evidence"):
            issues.append(f"command {command.get('command')!r} has no evidence")
        issues.extend(_evidence_issues(f"command {command.get('command')!r}", command.get("evidence") or []))

    for convention in digest.get("conventions") or []:
        if not convention.get("evidence"):
            issues.append("a convention entry has no evidence")
        issues.extend(_evidence_issues("a convention entry", convention.get("evidence") or []))

    for risk in digest.get("risks") or []:
        if len(risk.get("description") or "") > MAX_RISK_GAP_DESCRIPTION_CHARS:
            issues.append("a risk description exceeds 500 characters")
        if not risk.get("evidence"):
            issues.append(f"risk {risk.get('type')!r} has no evidence")
        issues.extend(_evidence_issues(f"risk {risk.get('type')!r}", risk.get("evidence") or []))

    for gap in digest.get("gaps") or []:
        if len(gap.get("description") or "") > MAX_RISK_GAP_DESCRIPTION_CHARS:
            issues.append("a gap description exceeds 500 characters")

    return issues


def _evidence_issues(owner: str, evidence: list[dict[str, Any]]) -> list[str]:
    """Every EvidenceRef must carry at least one of path/symbol/artifact_key
    (Data Model > EvidenceRef: "At least one of path, symbol, or
    artifact_key must be non-null").
    """
    issues: list[str] = []
    for ev in evidence:
        if not has_evidence_locator(ev):
            issues.append(f"{owner} has an evidence reference with no path, symbol, or artifact_key")
    return issues
