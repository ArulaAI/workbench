"""Schema constants, dataclasses, and validation helpers for repository-digest.json.

Schema version 1, per specs/tech/speed-repository-digest-dashboard.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, Literal, TypeVar

SCHEMA_VERSION = 1

# Filesystem boundaries shared by every discovery-time file reader in this
# package (supplemental docs in repository_digest.py, command sources in
# command_discovery.py, ...) — one denylist and one containment check, not
# a slightly-different one per module.
CREDENTIAL_DENYLIST_SUFFIXES = (".key", ".pem")
CREDENTIAL_DENYLIST_NAMES = {".env", ".env.local"}
CREDENTIAL_DENYLIST_PREFIXES = ("credentials.",)

DEFAULT_SAFE_READ_MAX_BYTES = 256 * 1024
MAX_FILE_BYTES = 500_000  # skip pathologically large generated files when scanning for evidence


def is_credential_path(path: Path) -> bool:
    name = path.name
    if name in CREDENTIAL_DENYLIST_NAMES:
        return True
    if any(name.endswith(suf) for suf in CREDENTIAL_DENYLIST_SUFFIXES):
        return True
    if any(name.startswith(pre) for pre in CREDENTIAL_DENYLIST_PREFIXES):
        return True
    return False


def is_within(path: Path, root: Path) -> bool:
    """True if `path` resolves to somewhere inside `root` — resolving
    both sides first means a symlink whose target lands outside the
    project root is rejected exactly like a literal out-of-root path,
    not silently followed.
    """
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def safe_read_text(
    path: Path, project_root: Path, max_bytes: int = DEFAULT_SAFE_READ_MAX_BYTES,
) -> str | None:
    """Bounded, root-contained, credential-denylisted text read — the one
    safe way every discovery-time reader in this package should read a
    file whose path it did not fully control (a path assembled from a
    project-map entry, a glob match, a workspace pattern, ...): resolved
    location must stay inside the project root (symlinks included), the
    file must not match the credential denylist, and the read is capped
    at max_bytes regardless of the file's actual size. Returns None for
    anything that fails any of these checks or isn't a readable file —
    callers treat that identically to "this source doesn't exist."
    """
    if is_credential_path(path):
        return None
    try:
        resolved = path.resolve()
    except OSError:
        return None
    if not is_within(resolved, project_root):
        return None
    if not resolved.is_file():
        return None
    try:
        size = resolved.stat().st_size
        if size > max_bytes:
            text = resolved.read_text(encoding="utf-8", errors="replace")[:max_bytes]
        else:
            text = resolved.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return text.replace("\x00", "")


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

def manifest_paths(project_map: dict[str, Any] | None, filename: str) -> list[str]:
    """Every path in project_map['files'] whose basename is exactly
    `filename` — reuses the file inventory Layer 1 already built instead of
    re-walking the filesystem, so a manifest anywhere in the tree (not just
    the repository root) is found the same way project-map.json already
    knows about it. Returns paths sorted for determinism; empty if
    project_map is missing/malformed or has no matches.
    """
    if not isinstance(project_map, dict):
        return []
    files = project_map.get("files")
    if not isinstance(files, list):
        return []
    paths: list[str] = []
    for entry in files:
        if not isinstance(entry, dict):
            continue
        path = entry.get("path")
        if isinstance(path, str) and path.rsplit("/", 1)[-1] == filename:
            paths.append(path)
    return sorted(paths)


Confidence = Literal["confirmed", "derived", "inferred", "unknown"]
CONFIDENCE_VALUES: tuple[Confidence, ...] = ("confirmed", "derived", "inferred", "unknown")

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


def line_number(content: str, offset: int) -> int:
    """1-based line number of a character offset into `content` — shared
    by every regex-scanning derivation (API routes, security indicators,
    command discovery, runtime config) that needs to cite a line in an
    EvidenceRef.
    """
    return content.count("\n", 0, offset) + 1


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
        # Phase 2 additions. Deliberately absent from validate_digest()'s
        # required-array check below — a digest built before these fields
        # existed must keep loading (as "ok", just without this data),
        # never fail validation and get treated as malformed.
        "annotated_tree": [],
        "reading_path": [],
        "approved_knowledge": [],
        "pending_knowledge": [],
        "coverage_stats": None,
        # Phase 4 additions. Same backward-compat rule as Phase 2/3: never
        # added to validate_digest()'s required-array check below — a
        # digest built before these fields existed must keep loading, just
        # without this data.
        "api_data": {"routes": [], "entities": [], "persistence_summary": None},
        "cicd": {"workflows": [], "other_providers_detected": []},
        "runtime_config": {
            "runtimes": [], "frameworks": [], "config_sources": [], "environment_variables": [],
        },
        # Phase 5A addition. Same backward-compat rule: never added to
        # validate_digest()'s required-array check below.
        "security": {
            "secret_indicators": [], "sensitive_configuration": [],
            "authentication_indicators": [], "security_tooling_detected": [],
        },
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
    empty means valid. Never raises, regardless of how malformed `digest`
    is — dashboard/backend/resolvers/repository_digest_types.py's
    to_repository_digest() indexes schema_version/status/generated_at/
    identity/footprint directly with `data["..."]` (not `.get()`), so
    this function is the *only* gate standing between an on-disk
    repository-digest.json (which this process didn't necessarily write —
    a stale/hand-edited/multiplayer-shared file counts too) and a
    KeyError/TypeError crash in the GraphQL layer. Every check below
    exists because something past it crashes on the wrong type, not
    because the schema doc says so.
    """
    if not isinstance(digest, dict):
        return ["digest must be a JSON object"]

    try:
        return _validate_digest_unsafe(digest)
    except Exception as e:  # noqa: BLE001 - see docstring: this must never raise
        return [f"validation itself failed on malformed input: {e!r}"]


def _validate_digest_unsafe(digest: dict[str, Any]) -> list[str]:
    issues: list[str] = []

    if digest.get("schema_version") != SCHEMA_VERSION:
        issues.append(f"schema_version must be {SCHEMA_VERSION}, got {digest.get('schema_version')!r}")

    if digest.get("status") not in ("complete", "partial", "failed"):
        issues.append(f"status must be complete|partial|failed, got {digest.get('status')!r}")

    if not isinstance(digest.get("generated_at"), str) or not digest["generated_at"]:
        issues.append("generated_at must be a non-empty string")

    generator = digest.get("generator")
    if not isinstance(generator, dict) or not isinstance(generator.get("name"), str) or not isinstance(generator.get("version"), str):
        issues.append("generator must be an object with string 'name' and 'version'")

    fingerprint = digest.get("fingerprint")
    if not isinstance(fingerprint, dict):
        issues.append("fingerprint must be an object")

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

    identity = digest.get("identity")
    if not isinstance(identity, dict):
        issues.append("identity must be an object")
    elif not isinstance(identity.get("name"), str) or not identity["name"]:
        issues.append("identity.name must be a non-empty string")
    elif not isinstance(identity.get("summary", ""), str):
        issues.append("identity.summary must be a string")
    else:
        summary = identity.get("summary") or ""
        if len(summary) > MAX_IDENTITY_SUMMARY_CHARS:
            issues.append("identity.summary exceeds 600 characters")
        if summary and not identity.get("evidence"):
            issues.append("identity.summary is non-empty but has no evidence")
        issues.extend(_evidence_issues("identity", _dict_list(identity.get("evidence"))))
        if identity.get("confidence") is not None and identity["confidence"] not in CONFIDENCE_VALUES:
            issues.append(f"identity.confidence must be one of {CONFIDENCE_VALUES}, got {identity['confidence']!r}")

    footprint = digest.get("footprint")
    if not isinstance(footprint, dict):
        issues.append("footprint must be an object")
    else:
        if not isinstance(footprint.get("file_count"), int):
            issues.append("footprint.file_count must be an integer")
        if not isinstance(footprint.get("line_count"), int):
            issues.append("footprint.line_count must be an integer")
        languages = footprint.get("languages", [])
        if not isinstance(languages, list):
            issues.append("footprint.languages must be an array")
        else:
            for lang in languages:
                if (
                    not isinstance(lang, dict)
                    or not isinstance(lang.get("name"), str)
                    or not isinstance(lang.get("files"), int)
                    or not isinstance(lang.get("lines"), int)
                    or not isinstance(lang.get("percent"), (int, float))
                ):
                    issues.append(f"footprint.languages entry is malformed: {lang!r}")

    for domain in _dict_list(digest.get("domains")):
        if len(domain.get("summary") or "") > MAX_DOMAIN_SUMMARY_CHARS:
            issues.append(f"domain {domain.get('id')!r} summary exceeds 400 characters")
        if not domain.get("evidence"):
            issues.append(f"domain {domain.get('id')!r} has no evidence")
        issues.extend(_evidence_issues(f"domain {domain.get('id')!r}", _dict_list(domain.get("evidence"))))
        if domain.get("confidence") is not None and domain["confidence"] not in CONFIDENCE_VALUES:
            issues.append(f"domain {domain.get('id')!r} confidence must be one of {CONFIDENCE_VALUES}, got {domain['confidence']!r}")

    for command in _dict_list(digest.get("commands")):
        if len(command.get("command") or "") > MAX_COMMAND_CHARS:
            issues.append("a command exceeds 500 characters")
        if "\x00" in (command.get("command") or ""):
            issues.append("a command contains a NUL byte")
        if not command.get("evidence"):
            issues.append(f"command {command.get('command')!r} has no evidence")
        issues.extend(_evidence_issues(f"command {command.get('command')!r}", _dict_list(command.get("evidence"))))

    for convention in _dict_list(digest.get("conventions")):
        if not convention.get("evidence"):
            issues.append("a convention entry has no evidence")
        issues.extend(_evidence_issues("a convention entry", _dict_list(convention.get("evidence"))))

    for risk in _dict_list(digest.get("risks")):
        if len(risk.get("description") or "") > MAX_RISK_GAP_DESCRIPTION_CHARS:
            issues.append("a risk description exceeds 500 characters")
        if not risk.get("evidence"):
            issues.append(f"risk {risk.get('type')!r} has no evidence")
        issues.extend(_evidence_issues(f"risk {risk.get('type')!r}", _dict_list(risk.get("evidence"))))

    for gap in _dict_list(digest.get("gaps")):
        if len(gap.get("description") or "") > MAX_RISK_GAP_DESCRIPTION_CHARS:
            issues.append("a gap description exceeds 500 characters")

    for array_name in (
        "relationships", "entrypoints", "hotspots", "readiness",
        "domains", "commands", "conventions", "risks", "gaps",
    ):
        value = digest.get(array_name)
        if isinstance(value, list) and any(not isinstance(item, dict) for item in value):
            issues.append(f"{array_name} contains a non-object entry")

    if isinstance(digest.get("warnings"), list) and any(not isinstance(w, str) for w in digest["warnings"]):
        issues.append("warnings must contain only strings")

    return issues


def _dict_list(value: Any) -> list[dict[str, Any]]:
    """Every object-array in a digest, filtered to actual objects — the
    single place validate_digest()'s per-entry loops get a
    guaranteed-safe list to iterate, so a non-object entry (or a
    non-array value entirely) is reported once by the required_array
    check above and never reached by code that assumes `.get()` works.
    """
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, dict)]


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
