"""Repository Digest builder.

Consolidates existing Discover artifacts (project map, semantic graph,
conventions, project knowledge, observations) into one versioned,
evidence-backed repository-digest.json. See
specs/tech/speed-repository-digest-dashboard.md for the full spec this
module implements.

Zero LLM calls unless narrative=True is explicitly passed, and even then
falls back deterministically if no provider is configured (v1 ships with
narrative synthesis disabled by default, per the RFC).
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

from . import command_discovery
from .repository_digest_freshness import compute_fingerprint
from .repository_digest_schema import (
    MAX_DOMAINS,
    MAX_HOTSPOTS,
    MAX_RISKS,
    SCHEMA_VERSION,
    InputResult,
    empty_digest_body,
    load_toml_file,
    make_evidence,
    normalize_loaded_confidence,
    truncate,
    validate_digest,
)
from .utils import ensure_dir, git_head_hash, load_speed_toml, now_iso, read_json_or_none

log = logging.getLogger("speed.context.repository_digest")

DIGEST_FILENAME = "repository-digest.json"

# Filesystem boundaries: supplemental documentation/manifest loaders never
# read these, regardless of what a scan pattern might otherwise match.
_CREDENTIAL_DENYLIST_SUFFIXES = (".key", ".pem")
_CREDENTIAL_DENYLIST_NAMES = {".env", ".env.local"}
_CREDENTIAL_DENYLIST_PREFIXES = ("credentials.",)

_SUPPLEMENTAL_MAX_BYTES = 256 * 1024
_SUPPLEMENTAL_TOTAL_MAX_BYTES = 2 * 1024 * 1024

_STOPWORDS = {
    "the", "and", "for", "src", "lib", "app", "test", "tests", "util",
    "utils", "common", "helpers", "helper", "index", "main", "py", "ts",
    "js", "tsx", "jsx", "go", "rb", "rs",
}


class DigestInputError(Exception):
    """Raised only when the required project map is absent or invalid."""


class _SupplementalBudget:
    """Tracks the 2 MiB total-supplemental-text cap across every
    documentation/manifest read in one build (Security & Controls >
    Content handling: "Limit... total supplemental text to 2 MiB before
    normalization"). The 256 KiB per-source cap in `_safe_read_supplemental`
    is enforced independently of this.
    """

    def __init__(self, total_max_bytes: int = _SUPPLEMENTAL_TOTAL_MAX_BYTES) -> None:
        self.remaining = total_max_bytes

    def charge(self, num_bytes: int) -> bool:
        """Returns False (and charges nothing) if this read would exceed
        the remaining budget; otherwise deducts and returns True.
        """
        if num_bytes > self.remaining:
            return False
        self.remaining -= num_bytes
        return True


# ── Path / IO helpers ─────────────────────────────────────────────


def repository_digest_input_paths(project_root: str) -> dict[str, Path]:
    root = Path(project_root)
    context_dir = root / ".speed" / "context"

    # Memory dir follows single-player/multiplayer layout, same rule as
    # dashboard/backend/paths.py's SpeedPaths.memory_dir.
    memory_dir = root / ".speed" / "shared" / "knowledge"
    if not memory_dir.is_dir():
        memory_dir = root / ".speed" / "memory"

    return {
        "project_map": context_dir / "project-map.json",
        "semantic_graph": context_dir / "semantic-graph.json",
        "spec_alignment": context_dir / "spec-alignment.json",
        "skeletons": context_dir / "skeletons",
        "conventions": memory_dir / "conventions.json",
        "project_knowledge": memory_dir / "project-knowledge.json",
        "project_knowledge_drafts": memory_dir / "project-knowledge-drafts.json",
        "observations_dir": memory_dir / "observations",
        "digest": context_dir / DIGEST_FILENAME,
        "digest_status": context_dir / "repository-digest-status.json",
    }


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _is_credential_path(path: Path) -> bool:
    name = path.name
    if name in _CREDENTIAL_DENYLIST_NAMES:
        return True
    if any(name.endswith(suf) for suf in _CREDENTIAL_DENYLIST_SUFFIXES):
        return True
    if any(name.startswith(pre) for pre in _CREDENTIAL_DENYLIST_PREFIXES):
        return True
    return False


def _safe_read_supplemental(path: Path, project_root: Path, budget: "_SupplementalBudget | None" = None) -> str | None:
    """Read a supplemental doc/manifest file, enforcing the Security &
    Controls filesystem boundaries: resolved-inside-root only, denylist,
    per-source size cap, and (when a budget is supplied) the 2 MiB
    total-across-sources cap.
    """
    if _is_credential_path(path):
        return None
    try:
        resolved = path.resolve()
    except OSError:
        return None
    if not _is_within(resolved, project_root):
        return None
    if not resolved.is_file():
        return None
    try:
        size = resolved.stat().st_size
        capped = min(size, _SUPPLEMENTAL_MAX_BYTES)
        if budget is not None and not budget.charge(capped):
            return None
        if size > _SUPPLEMENTAL_MAX_BYTES:
            return resolved.read_text(encoding="utf-8", errors="replace")[: _SUPPLEMENTAL_MAX_BYTES]
        text = resolved.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return text.replace("\x00", "")


def load_optional_json(path: Path) -> Any | None:
    _, value = load_optional_json_with_status(path)
    return value


def load_optional_json_with_status(path: Path) -> tuple[str, Any | None]:
    """Like load_optional_json, but distinguishes 'file doesn't exist'
    (missing) from 'file exists but isn't valid JSON' (invalid) — the
    Builder Design pipeline needs this distinction so a malformed optional
    input is marked 'invalid', not 'unavailable', in readiness.
    """
    try:
        value = read_json_or_none(str(path))
    except Exception:
        return "invalid", None
    return ("missing", None) if value is None else ("ok", value)


def load_optional_json_list(path: Path, key: str | None = None) -> list[dict[str, Any]]:
    data = load_optional_json(path)
    if data is None:
        return []
    if key is not None and isinstance(data, dict):
        value = data.get(key, [])
        return value if isinstance(value, list) else []
    return data if isinstance(data, list) else []


def _relative(path: str, project_root: Path) -> str | None:
    """Normalize to a repository-relative path. Never returns an absolute
    path or one containing '..' — per Validation Rules, out-of-root paths
    are dropped rather than exposed.
    """
    try:
        candidate = Path(path)
        if candidate.is_absolute():
            candidate = candidate.relative_to(project_root)
        rel = os.path.normpath(str(candidate))
        if rel.startswith("..") or os.path.isabs(rel):
            return None
        return rel.replace(os.sep, "/")
    except (ValueError, OSError):
        return None


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """Write to a temp file in the same directory, flush, then replace the
    destination atomically. Never truncates the prior valid file before the
    replace completes.
    """
    ensure_dir(str(path.parent))
    tmp_path = path.with_name(f".{path.name}.tmp-{os.getpid()}-{int(time.time() * 1000)}")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)


# ── Public API ─────────────────────────────────────────────────────


def load_repository_digest(project_root: str) -> dict[str, Any] | None:
    """Return a validated stored digest, or None when absent or malformed.

    Thin convenience wrapper over load_repository_digest_with_status() for
    callers that only care about the value, not why it's absent.
    """
    _, digest, _ = load_repository_digest_with_status(project_root)
    return digest


def attach_effective_state(
    project_root: str, digest: dict[str, Any], *, config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute freshness and return a shallow copy of digest with
    `_freshness` and `_effective_state` (CURRENT|STALE) set.

    Single source of truth for both the dashboard resolver and the
    `speed digest` CLI, so project_digest_for_agent()'s freshness line
    reflects a real, consistently-computed state.
    """
    from .repository_digest_freshness import compute_digest_freshness

    freshness = compute_digest_freshness(project_root, digest, config=config)
    digest = dict(digest)
    digest["_freshness"] = freshness
    digest["_effective_state"] = freshness["state"]
    return digest


def load_repository_digest_with_status(
    project_root: str,
) -> tuple[str, dict[str, Any] | None, str | None]:
    """Like load_repository_digest(), but distinguishes *why* there's no
    usable digest — needed so the dashboard can tell "never built" apart
    from "a stored artifact exists but is malformed / unsupported schema"
    (Validation Rules > schema_version: "unsupported versions return no
    digest plus an invalid status reason"; Dashboard Design > Page states:
    Missing vs. Malformed artifact are distinct states).

    Returns (status, digest, reason):
      ("missing", None, None)               — no repository-digest.json on disk
      ("malformed", None, reason)            — file exists but isn't valid JSON,
                                                isn't a dict, or fails schema
                                                validation (including an
                                                unsupported schema_version)
      ("ok", digest, None)                   — valid, usable digest
    """
    paths = repository_digest_input_paths(project_root)
    digest_path = paths["digest"]

    if not digest_path.is_file():
        return "missing", None, None

    try:
        data = read_json_or_none(str(digest_path))
    except Exception as e:
        return "malformed", None, f"repository-digest.json is not valid JSON: {e}"

    if data is None:
        return "missing", None, None
    if not isinstance(data, dict):
        return "malformed", None, "repository-digest.json does not contain a JSON object"

    stored_version = data.get("schema_version")
    if stored_version != SCHEMA_VERSION:
        return (
            "malformed", None,
            f"repository-digest.json has schema_version {stored_version!r}; this build supports {SCHEMA_VERSION!r} only",
        )

    # Normalize before validating: an out-of-range confidence value is
    # exactly what normalize_loaded_confidence() exists to repair (per
    # Validation Rules > Confidence, "normalize... with a warning"), so it
    # must not be treated as a validation failure first.
    confidence_warnings = normalize_loaded_confidence(data)

    issues = validate_digest(data)
    if issues:
        return "malformed", None, "repository-digest.json failed validation: " + "; ".join(issues)

    if confidence_warnings:
        data.setdefault("warnings", [])
        data["warnings"].extend(confidence_warnings)

    return "ok", data, None


def build_repository_digest(
    project_root: str,
    *,
    config: dict[str, Any] | None = None,
    narrative: bool = False,
) -> dict[str, Any]:
    """Build and atomically persist repository-digest.json.

    Raises DigestInputError only when the required project map is absent
    or invalid. Every other optional-source failure is represented in
    readiness records, never raised.
    """
    start_time = time.time()
    root = Path(project_root)
    paths = repository_digest_input_paths(project_root)
    config = config if config is not None else load_speed_toml(project_root)

    project_map = load_optional_json(paths["project_map"])
    if not isinstance(project_map, dict) or "files" not in project_map or "summary" not in project_map:
        _emit_generation_event(
            project_root=project_root, identity_name=None, git_head=git_head_hash(project_root) or None,
            fingerprint=None, status="failed", duration_seconds=time.time() - start_time,
            readiness=[], warning_count=0, narrative_requested=narrative,
        )
        raise DigestInputError(
            f"{paths['project_map']} is missing or not a structurally valid project map "
            "(expected 'files' array and 'summary' object)"
        )

    csg_result = _load_optional_input("semantic_graph", paths["semantic_graph"])
    conventions_result = _load_optional_input("conventions", paths["conventions"])
    project_knowledge_result = _load_optional_input("project_knowledge", paths["project_knowledge"])
    spec_alignment_result = _load_optional_input("spec_alignment", paths["spec_alignment"])
    project_knowledge_drafts_raw = load_optional_json(paths["project_knowledge_drafts"])

    warnings: list[str] = []
    readiness: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []

    def _mark(capability: str, status: str, reason: str | None = None, remediation: str | None = None, source_path: Path | None = None) -> None:
        readiness.append({
            "capability": capability,
            "status": status,
            "reason": reason,
            "remediation": remediation,
            "source_path": _relative(str(source_path), root) if source_path else None,
        })

    def _mark_result(result: InputResult, *, remediation: str | None = None) -> None:
        _mark(result.capability, result.status, result.reason, remediation,
              Path(result.source_path) if result.source_path else None)

    _mark("project_map", "available", source_path=paths["project_map"])

    csg = csg_result.value
    csg_available = csg_result.status == "available" and isinstance(csg, dict) and "nodes" in csg
    if csg_result.status == "available" and not csg_available:
        # Structurally present but not a usable semantic graph.
        csg_result = InputResult(
            capability="semantic_graph", status="invalid", value=None,
            reason="semantic-graph.json is not a valid semantic graph", source_path=csg_result.source_path,
        )
        warnings.append("semantic_graph present but structurally invalid — treated as unavailable")
        csg = None
    _mark_result(
        csg_result,
        remediation="Run the Layer 1 context build" if csg_result.status == "unavailable"
        else "Rebuild the Layer 1 context index" if csg_result.status == "invalid" else None,
    )

    conventions_list: list[dict[str, Any]]
    if conventions_result.status == "available":
        extracted = _extract_conventions(conventions_result.value)
        conventions_list = extracted if extracted is not None else []
    else:
        conventions_list = []
        if conventions_result.status == "invalid":
            warnings.append("conventions.json present but invalid — conventions section left empty")
    _mark_result(conventions_result, remediation="Run speed learn --conventions")

    project_knowledge_entries = (
        _extract_list(project_knowledge_result.value, "entries")
        if project_knowledge_result.status == "available" else []
    )

    # Exactly one readiness record for "project_knowledge" (Data Model:
    # "One record per known discovery capability") — a pending draft takes
    # priority over the base available/unavailable status rather than
    # appending a second record for the same capability.
    drafts_count = len(_extract_list(project_knowledge_drafts_raw, None) or [])
    if drafts_count:
        _mark(
            "project_knowledge", "partial",
            f"{drafts_count} draft entr{'y' if drafts_count == 1 else 'ies'} pending human review",
            source_path=Path(project_knowledge_result.source_path) if project_knowledge_result.source_path else None,
        )
    else:
        _mark_result(project_knowledge_result)

    observations = _load_observations(paths["observations_dir"])
    if not paths["observations_dir"].is_dir():
        _mark("observations", "unavailable", "no observation log for this project", source_path=paths["observations_dir"])
    else:
        _mark("observations", "available", source_path=paths["observations_dir"])

    _mark_result(spec_alignment_result, remediation="Add product specifications and run SPEED validation")

    # Fingerprint captured now, right after every optional input has been
    # loaded and before the (potentially slower) derivation stages below —
    # compared against a second capture right before write so a mid-build
    # change to git HEAD or a knowledge file can't silently go unnoticed
    # (Edge Cases: "Current git HEAD changes while generation is in
    # progress" / "Knowledge files change between hash calculation and
    # artifact write").
    fingerprint_at_read = compute_fingerprint(
        project_root, config=config, project_map_path=paths["project_map"],
        semantic_graph_path=paths["semantic_graph"], conventions=conventions_list,
        project_knowledge=project_knowledge_entries,
    )

    # ── Derive deterministic facts ──────────────────────────────

    supplemental_budget = _SupplementalBudget()
    identity = _derive_identity(root, project_map, config, gaps, warnings, supplemental_budget)
    footprint = _derive_footprint(project_map, csg)
    domains = _derive_domains(csg, gaps, warnings) if csg_available else []
    relationships = _derive_relationships(csg) if csg_available else []
    symbol_to_domain = _build_symbol_to_domain(csg) if csg_available else {}
    hotspots = _derive_hotspots(csg, domains, symbol_to_domain) if csg_available else []
    commands, command_gaps = _derive_commands(root)
    gaps.extend(command_gaps)
    conventions = _derive_conventions(conventions_list)
    risks = _derive_risks(csg, domains, commands, observations, project_knowledge_entries, symbol_to_domain)

    _mark("documentation", "available" if (root / "README.md").is_file() else "unavailable",
          source_path=root / "README.md")
    manifests_present = _any_manifest_present(root)
    _mark("manifests", "available" if manifests_present else "unavailable",
          None if manifests_present else "No package.json, pyproject.toml, or Cargo.toml found")
    _mark("project_instructions", "available" if (root / "CLAUDE.md").is_file() or (root / "AGENTS.md").is_file() else "unavailable")

    # ── Optional bounded narrative synthesis ────────────────────

    if narrative:
        narrative_result, narrative_warning = _narrative_synthesize(identity)
        if narrative_warning:
            warnings.append(narrative_warning)
        if narrative_result:
            identity = narrative_result

    # ── Assemble, validate, atomically persist ──────────────────

    optional_all_unavailable_but_project_map_ok = any(
        r["status"] in ("unavailable", "invalid", "partial")
        for r in readiness if r["capability"] != "project_map"
    )
    status = "partial" if optional_all_unavailable_but_project_map_ok else "complete"

    domains, dropped_domains = _cap(domains, MAX_DOMAINS)
    hotspots, dropped_hotspots = _cap(hotspots, MAX_HOTSPOTS)
    risks, dropped_risks = _cap(risks, MAX_RISKS)
    if dropped_domains:
        warnings.append(f"domains truncated to {MAX_DOMAINS} entries")
    if dropped_hotspots:
        warnings.append(f"hotspots truncated to {MAX_HOTSPOTS} entries")
    if dropped_risks:
        warnings.append(f"risks truncated to {MAX_RISKS} entries")

    # Recheck right before write. If inputs moved since fingerprint_at_read,
    # persist the *at-read* fingerprint anyway (it's what the derived
    # content above actually reflects) but flag it so the very next
    # freshness check reports stale immediately rather than falsely CURRENT
    # (Edge Cases: "a mismatch writes the digest but immediately marks it
    # stale"). Retrying automatically is explicitly configuration-gated in
    # the RFC and no such configuration exists yet, so only the mandatory
    # "write, then stale" branch is implemented.
    fingerprint_at_write = compute_fingerprint(
        project_root, config=config, project_map_path=paths["project_map"],
        semantic_graph_path=paths["semantic_graph"], conventions=conventions_list,
        project_knowledge=project_knowledge_entries,
    )
    if fingerprint_at_write.to_dict() != fingerprint_at_read.to_dict():
        warnings.append(
            "repository inputs changed while the digest was being generated — "
            "this digest reflects a snapshot from generation start and will show as stale immediately"
        )
    fingerprint = fingerprint_at_read

    digest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "generated_at": now_iso(),
        "generator": {"name": "speed-repository-digest", "version": str(SCHEMA_VERSION)},
        "fingerprint": fingerprint.to_dict(),
        "identity": identity,
        "footprint": footprint,
        **empty_digest_body(),
    }
    digest["domains"] = domains
    digest["relationships"] = relationships
    digest["commands"] = commands
    digest["hotspots"] = hotspots
    digest["conventions"] = conventions
    digest["risks"] = risks
    digest["gaps"] = gaps
    digest["readiness"] = readiness
    digest["warnings"] = warnings

    issues = validate_digest(digest)
    if issues:
        # Validation failure on a digest we just built ourselves indicates a
        # builder bug, not a bad input — surface it rather than persist a
        # digest that fails its own contract.
        _emit_generation_event(
            project_root=project_root, identity_name=identity.get("name"), git_head=fingerprint.git_head,
            fingerprint=fingerprint.to_dict(), status="failed", duration_seconds=time.time() - start_time,
            readiness=readiness, warning_count=len(warnings), narrative_requested=narrative,
        )
        raise DigestInputError("built digest failed self-validation: " + "; ".join(issues))

    _atomic_write_json(paths["digest"], digest)
    _emit_generation_event(
        project_root=project_root, identity_name=identity.get("name"), git_head=fingerprint.git_head,
        fingerprint=fingerprint.to_dict(), status=status, duration_seconds=time.time() - start_time,
        readiness=readiness, warning_count=len(warnings), narrative_requested=narrative,
    )
    return digest


def _load_optional_input(capability: str, path: Path) -> InputResult:
    """Load one optional discovery input as an InputResult rather than a
    bare value, per Builder Design > Input isolation — a missing/invalid
    source degrades to a readiness record instead of throwing through the
    pipeline, and the caller reads .status/.value/.reason uniformly instead
    of re-deriving readiness from ad hoc None-checks.
    """
    status, value = load_optional_json_with_status(path)
    if status == "missing":
        return InputResult(capability=capability, status="unavailable", value=None,
                            reason=f"{path.name} does not exist", source_path=str(path))
    if status == "invalid":
        return InputResult(capability=capability, status="invalid", value=None,
                            reason=f"{path.name} is not valid JSON", source_path=str(path))
    return InputResult(capability=capability, status="available", value=value, reason=None, source_path=str(path))


def _any_manifest_present(root: Path) -> bool:
    return any((root / name).is_file() for name in ("package.json", "pyproject.toml", "Cargo.toml"))


def _emit_generation_event(
    *,
    project_root: str,
    identity_name: str | None,
    git_head: str | None,
    fingerprint: dict[str, Any] | None,
    status: str,
    duration_seconds: float,
    readiness: list[dict[str, Any]],
    warning_count: int,
    narrative_requested: bool,
) -> None:
    """Auditability: one structured record per digest build, success or
    failure. Deliberately excludes summary text, command strings, evidence,
    and anything else that could carry a secret value or a full provider
    prompt (Security & Controls > Auditability).
    """
    event = {
        "event": "repository_digest.generated",
        "project": identity_name or Path(project_root).resolve().name,
        "indexed_git_head": git_head,
        "fingerprint": fingerprint,
        "status": status,
        "duration_seconds": round(duration_seconds, 3),
        "capabilities": {r["capability"]: r["status"] for r in readiness},
        "warning_count": warning_count,
        "narrative_requested": narrative_requested,
    }
    log.info(json.dumps(event, sort_keys=True))


def _cap(items: list[Any], limit: int) -> tuple[list[Any], bool]:
    if len(items) <= limit:
        return items, False
    return items[:limit], True


# ── Identity ────────────────────────────────────────────────────


def _derive_identity(
    root: Path,
    project_map: dict[str, Any],
    config: dict[str, Any],
    gaps: list[dict[str, Any]],
    warnings: list[str],
    budget: "_SupplementalBudget",
) -> dict[str, Any]:
    name = _repository_name(root, config, warnings)

    vision_file = config.get("specs", {}).get("vision_file") if isinstance(config.get("specs"), dict) else None
    purpose, evidence = _repository_purpose(root, vision_file, budget)

    if not purpose:
        gaps.append({
            "type": "purpose_not_discovered",
            "description": "No purpose statement cleared the evidence bar (no vision file, no usable README prose, no manifest description).",
            "evidence": [],
        })

    return {
        "name": name,
        "summary": purpose or "",
        "confidence": "derived" if purpose else "unknown",
        "evidence": evidence,
    }


def _manifest_names(root: Path) -> dict[str, str]:
    """Read the declared project name from every present root manifest.
    Returns {manifest_filename: name}, only for manifests that actually
    declare one.
    """
    found: dict[str, str] = {}

    package_json = load_optional_json(root / "package.json")
    if isinstance(package_json, dict) and package_json.get("name"):
        found["package.json"] = str(package_json["name"])

    pyproject = load_toml_file(root / "pyproject.toml")
    if pyproject:
        proj_name = pyproject.get("project", {}).get("name") or pyproject.get("tool", {}).get("poetry", {}).get("name")
        if proj_name:
            found["pyproject.toml"] = str(proj_name)

    cargo_toml = load_toml_file(root / "Cargo.toml")
    if cargo_toml:
        pkg_name = cargo_toml.get("package", {}).get("name")
        if pkg_name:
            found["Cargo.toml"] = str(pkg_name)

    return found


def _repository_name(root: Path, config: dict[str, Any], warnings: list[str] | None = None) -> str:
    """Priority order per Builder Design > Repository identity: manifest
    name (package.json > pyproject.toml > Cargo.toml), then directory
    basename. ("Existing dashboard project registration name" is priority
    #1 in the RFC, but this codebase's own project registration
    — dashboard/backend/ingest.py's register_project() — always computes
    exactly root.name, identical to this function's own final fallback, so
    there is no distinct value to thread through here.)
    """
    names = _manifest_names(root)
    if warnings is not None and len(set(names.values())) > 1:
        warnings.append(
            "multiple manifests declare different project names ("
            + ", ".join(f"{k}: {v!r}" for k, v in names.items())
            + f") — using {next(iter(names.values()))!r} per source priority"
        )
    for manifest_name in ("package.json", "pyproject.toml", "Cargo.toml"):
        if manifest_name in names:
            return names[manifest_name]
    return root.resolve().name


def _manifest_description(root: Path) -> tuple[str, str] | None:
    """Root manifest description field, per Builder Design > Repository
    identity purpose-evidence priority #3. Returns (description, manifest
    filename) or None.
    """
    package_json = load_optional_json(root / "package.json")
    if isinstance(package_json, dict) and isinstance(package_json.get("description"), str) and package_json["description"].strip():
        return package_json["description"].strip(), "package.json"

    pyproject = load_toml_file(root / "pyproject.toml")
    if pyproject:
        desc = pyproject.get("project", {}).get("description") or pyproject.get("tool", {}).get("poetry", {}).get("description")
        if isinstance(desc, str) and desc.strip():
            return desc.strip(), "pyproject.toml"

    return None


def _repository_purpose(
    root: Path, vision_file: str | None, budget: "_SupplementalBudget | None" = None,
) -> tuple[str | None, list[dict[str, Any]]]:
    if vision_file:
        vision_path = root / vision_file
        text = _safe_read_supplemental(vision_path, root, budget)
        if text:
            result = _first_meaningful_paragraph(text)
            if result:
                para, line_no = result
                return para, [make_evidence("documentation", "Product vision statement", path=vision_file, line=line_no)]

    for readme_name in ("README.md", "README", "readme.md"):
        readme_path = root / readme_name
        text = _safe_read_supplemental(readme_path, root, budget)
        if not text:
            continue
        result = _first_meaningful_paragraph(text)
        if result:
            para, line_no = result
            return para, [make_evidence("documentation", "Repository overview", path=readme_name, line=line_no)]

    manifest_desc = _manifest_description(root)
    if manifest_desc:
        desc, manifest_name = manifest_desc
        para = truncate(desc, 600)
        return para, [make_evidence("manifest", "Manifest description field", path=manifest_name)]

    return None, []


_BADGE_SYNTAX_RE = re.compile(r"^\s*(\[!\[|!\[|\[!)", re.IGNORECASE)
_BADGE_WORD_RE = re.compile(r"^\s*(badge|status)\b", re.IGNORECASE)
_BADGE_WORD_MAX_CHARS = 40  # a genuine "Status: passing" label line is short; a prose sentence isn't


def _is_badge_line(stripped: str) -> bool:
    if _BADGE_SYNTAX_RE.match(stripped):
        return True
    return bool(_BADGE_WORD_RE.match(stripped)) and len(stripped) <= _BADGE_WORD_MAX_CHARS


def _first_meaningful_paragraph(text: str) -> tuple[str, int] | None:
    """Returns (paragraph_text, one_based_start_line), or None."""
    lines = text.splitlines()
    buffer: list[str] = []
    start_line = 0
    for i, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            if buffer:
                para = " ".join(buffer).strip()
                if len(para) >= 10:
                    return truncate(para, 600), start_line
                buffer = []
            continue
        if stripped.startswith("#") or _is_badge_line(stripped):
            continue
        if not buffer:
            start_line = i
        buffer.append(stripped)
    if buffer:
        para = " ".join(buffer).strip()
        if len(para) >= 10:
            return truncate(para, 600), start_line
    return None


# ── Footprint ───────────────────────────────────────────────────


def _derive_footprint(project_map: dict[str, Any], csg: dict[str, Any] | None) -> dict[str, Any]:
    summary = project_map.get("summary") or {}
    files = project_map.get("files") or []
    total_lines = summary.get("total_lines") or 0

    by_category: dict[str, int] = {}
    for f in files:
        cat = f.get("category") or "source"
        by_category[cat] = by_category.get(cat, 0) + 1

    languages = []
    by_language = summary.get("by_language") or {}
    for lang, stats in sorted(by_language.items()):
        lines = stats.get("lines", 0)
        percent = round((lines / total_lines) * 100, 2) if total_lines else 0.0
        languages.append({"name": lang, "files": stats.get("files", 0), "lines": lines, "percent": percent})

    return {
        "file_count": summary.get("total_files", len(files)),
        "line_count": total_lines,
        "source_file_count": by_category.get("source", 0),
        "config_file_count": by_category.get("config", 0),
        "asset_file_count": by_category.get("asset", 0),
        "symbol_count": len(csg.get("nodes", [])) if csg else None,
        "domain_count": len(csg.get("clusters", [])) if csg else None,
        "cross_domain_relationship_count": len(csg.get("cluster_edges", [])) if csg else None,
        "languages": languages,
    }


# ── Domains ─────────────────────────────────────────────────────


def _tokenize_path(path: str) -> list[str]:
    stem = re.split(r"[/\\]", path)[-1]
    stem = re.sub(r"\.[A-Za-z0-9]+$", "", stem)
    parts = re.split(r"[/_\-.]+", path.lower())
    return [p for p in parts if p and p not in _STOPWORDS and not p.isdigit()]


def _derive_label(cluster: dict[str, Any]) -> tuple[str, str]:
    """Returns (label, confidence). Prefers an existing Layer 1 label;
    otherwise derives from the longest common meaningful token, falling
    back to 'Unlabeled domain <short-id>' with confidence unknown.
    """
    existing = (cluster.get("label") or "").strip()
    if existing:
        return existing[:80], "derived"

    files = cluster.get("files") or cluster.get("symbols") or []
    counts: dict[str, int] = {}
    for f in files:
        for tok in set(_tokenize_path(f)):
            counts[tok] = counts.get(tok, 0) + 1

    if not counts:
        return f"Unlabeled domain {cluster['id'][-8:]}", "unknown"

    best_token, best_count = max(counts.items(), key=lambda kv: (kv[1], kv[0]))
    threshold = min(0.30 * len(files), 3)
    if best_count < threshold:
        return f"Unlabeled domain {cluster['id'][-8:]}", "unknown"

    return best_token.replace("_", " ").title()[:80], "derived"


def _derive_domains(csg: dict[str, Any], gaps: list[dict[str, Any]], warnings: list[str] | None = None) -> list[dict[str, Any]]:
    clusters = csg.get("clusters") or []
    nodes_by_id = {n["id"]: n for n in csg.get("nodes") or []}

    cluster_edges = csg.get("cluster_edges") or []
    depends_on: dict[str, set[str]] = {}
    used_by: dict[str, set[str]] = {}
    degree: dict[str, int] = {}
    for edge in cluster_edges:
        src, dst = edge.get("from"), edge.get("to")
        if not src or not dst:
            continue
        depends_on.setdefault(src, set()).add(dst)
        used_by.setdefault(dst, set()).add(src)
        degree[src] = degree.get(src, 0) + 1
        degree[dst] = degree.get(dst, 0) + 1

    raw_domains: list[dict[str, Any]] = []
    for cluster in clusters:
        cid = cluster.get("id")
        if not cid:
            continue
        symbols = cluster.get("symbols") or []
        symbol_nodes = [nodes_by_id[s] for s in symbols if s in nodes_by_id]

        ranked_symbols = sorted(
            symbol_nodes,
            key=lambda n: (
                -(n.get("impact", {}).get("centrality") or 0.0),
                -(n.get("impact", {}).get("blast_radius") or 0),
                n["id"],
            ),
        )
        representative_symbols = [n["id"] for n in ranked_symbols[:5]]

        file_symbol_counts: dict[str, int] = {}
        for n in ranked_symbols:
            f = n.get("file")
            if f:
                file_symbol_counts[f] = file_symbol_counts.get(f, 0) + 1
        rep_symbol_files = {n.get("file") for n in ranked_symbols[:5] if n.get("file")}
        representative_files = sorted(
            file_symbol_counts.keys(),
            key=lambda f: (f not in rep_symbol_files, -file_symbol_counts[f], f),
        )[:5]

        avg_blast = (
            sum((n.get("impact", {}).get("blast_radius") or 0) for n in symbol_nodes) / len(symbol_nodes)
            if symbol_nodes else 0.0
        )

        label, label_confidence = _derive_label(cluster)
        if label_confidence == "unknown":
            gaps.append({
                "type": "domain_label_unresolved",
                "description": f"No meaningful term cleared the support threshold for cluster {cid}.",
                "evidence": [],
            })

        evidence = [
            make_evidence("semantic_graph", "Representative symbol for this domain", path=n.get("file"), symbol=n["id"])
            for n in ranked_symbols[:3]
        ] or [make_evidence("semantic_graph", "Cluster membership", artifact_key=f"/clusters/{cid}")]

        raw_domains.append({
            "id": cid,
            "label": label,
            "summary": "",
            "confidence": label_confidence,
            "file_count": len(cluster.get("files") or []),
            "symbol_count": len(symbols),
            "cohesion": cluster.get("cohesion"),
            "avg_blast_radius": avg_blast,
            "representative_files": representative_files,
            "representative_symbols": representative_symbols,
            "depends_on": sorted(depends_on.get(cid, set())),
            "used_by": sorted(used_by.get(cid, set())),
            "evidence": evidence,
            "_cross_domain_degree": degree.get(cid, 0),
        })

    if not raw_domains:
        return []

    # Validation Rules > Domain references: depends_on/used_by IDs must
    # refer to stored domains; a cluster_edges endpoint that isn't an
    # actual cluster (duplicate/missing-node edge case) is dropped rather
    # than surfaced as a dangling reference.
    valid_ids = {d["id"] for d in raw_domains}
    dropped_refs: set[str] = set()
    for d in raw_domains:
        kept_depends_on = [ref for ref in d["depends_on"] if ref in valid_ids]
        kept_used_by = [ref for ref in d["used_by"] if ref in valid_ids]
        dropped_refs.update(set(d["depends_on"]) - valid_ids)
        dropped_refs.update(set(d["used_by"]) - valid_ids)
        d["depends_on"] = kept_depends_on
        d["used_by"] = kept_used_by
    if dropped_refs and warnings is not None:
        warnings.append(
            f"dropped {len(dropped_refs)} domain relationship reference(s) to unknown cluster ID(s): "
            + ", ".join(sorted(dropped_refs))
        )

    max_symbols = max(d["symbol_count"] for d in raw_domains) or 1
    max_files = max(d["file_count"] for d in raw_domains) or 1
    max_degree = max(d["_cross_domain_degree"] for d in raw_domains) or 1
    max_blast = max(d["avg_blast_radius"] for d in raw_domains) or 1

    for d in raw_domains:
        score = (
            0.35 * (d["symbol_count"] / max_symbols)
            + 0.25 * (d["file_count"] / max_files)
            + 0.25 * (d["_cross_domain_degree"] / max_degree)
            + 0.15 * (d["avg_blast_radius"] / max_blast if max_blast else 0)
        )
        d["_rank_score"] = score

    raw_domains.sort(key=lambda d: (-d["_rank_score"], d["id"]))
    for i, d in enumerate(raw_domains, start=1):
        d["rank"] = i
        d["rank_score"] = round(d.pop("_rank_score"), 6)
        d.pop("_cross_domain_degree", None)

    return raw_domains


def _derive_relationships(csg: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for edge in csg.get("cluster_edges") or []:
        out.append({
            "from": edge.get("from"),
            "to": edge.get("to"),
            "weight": edge.get("edge_count", edge.get("weight", 0)),
        })
    return out


# ── Hotspots ────────────────────────────────────────────────────


def _build_symbol_to_domain(csg: dict[str, Any]) -> dict[str, str]:
    symbol_to_domain: dict[str, str] = {}
    for cluster in csg.get("clusters") or []:
        for s in cluster.get("symbols") or []:
            symbol_to_domain[s] = cluster.get("id")
    return symbol_to_domain


def _derive_hotspots(
    csg: dict[str, Any], domains: list[dict[str, Any]], symbol_to_domain: dict[str, str],
) -> list[dict[str, Any]]:
    nodes = csg.get("nodes") or []
    ranked = sorted(
        nodes,
        key=lambda n: (
            -(n.get("impact", {}).get("blast_radius") or 0),
            -(n.get("impact", {}).get("dependents") or 0),
            -(n.get("impact", {}).get("centrality") or 0.0),
            n["id"],
        ),
    )

    hotspots = []
    for n in ranked:
        impact = n.get("impact") or {}
        blast = impact.get("blast_radius") or 0
        dependents = impact.get("dependents") or 0
        if blast == 0 and dependents == 0:
            continue
        reason = f"{dependents} dependent{'s' if dependents != 1 else ''}, blast radius {blast}"
        if impact.get("stability") == "bridge":
            reason += " — crosses a domain boundary"
        hotspots.append({
            "symbol_id": n["id"],
            "name": n.get("name", n["id"]),
            "file": n.get("file", ""),
            "line": n.get("line") or 0,
            "domain_id": symbol_to_domain.get(n["id"], ""),
            "blast_radius": blast,
            "dependents": dependents,
            "centrality": impact.get("centrality") or 0.0,
            "reason": reason,
            "evidence": [make_evidence("semantic_graph", "High-impact symbol", path=n.get("file"), symbol=n["id"])],
        })
        if len(hotspots) >= MAX_HOTSPOTS:
            break
    return hotspots


# ── Commands ────────────────────────────────────────────────────


def _derive_commands(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    commands = command_discovery.discover_commands(root)
    gaps: list[dict[str, Any]] = []

    by_purpose_root: dict[str, list[dict[str, Any]]] = {}
    for cmd in commands:
        if cmd["working_directory"] == ".":
            by_purpose_root.setdefault(cmd["purpose"], []).append(cmd)

    for purpose, entries in by_purpose_root.items():
        distinct_commands = {e["command"] for e in entries}
        if len(distinct_commands) > 1:
            gaps.append({
                "type": "conflicting_commands",
                "description": f"Multiple root-level commands claim the '{purpose}' purpose: {', '.join(sorted(distinct_commands))}.",
                "evidence": [ev for e in entries for ev in e["evidence"]],
            })

    return commands, gaps


# ── Conventions ─────────────────────────────────────────────────


def _extract_conventions(raw: Any) -> list[dict[str, Any]] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        return None
    entries = raw.get("conventions")
    return entries if isinstance(entries, list) else []


def _extract_list(raw: Any, key: str | None) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if key is not None and isinstance(raw, dict):
        value = raw.get(key, [])
        return value if isinstance(value, list) else []
    return raw if isinstance(raw, list) else []


def _derive_conventions(conventions_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Only entries the convention pipeline already accepted are included —
    conventions.json's own `conventions[]` array holds accepted entries
    only; candidates/drafts live in a separate file this builder never
    reads. See RFC > Builder Design > Conventions.
    """
    out = []
    for entry in conventions_list:
        source = entry.get("source")
        confidence = "confirmed" if source == "config" else "derived"
        canonical_example = entry.get("canonical_example")
        out.append({
            "text": entry.get("convention", ""),
            "scope": entry.get("scope") or [],
            "confidence": confidence,
            "evidence": [make_evidence(
                "convention", entry.get("convention", "")[:120],
                path=canonical_example.split(":")[0] if canonical_example else None,
                line=int(canonical_example.split(":")[1]) if canonical_example and ":" in canonical_example and canonical_example.split(":")[1].isdigit() else None,
            )],
        })
    return out


# ── Risks ───────────────────────────────────────────────────────


def _derive_risks(
    csg: dict[str, Any] | None,
    domains: list[dict[str, Any]],
    commands: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    project_knowledge_entries: list[dict[str, Any]],
    symbol_to_domain: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []

    if csg:
        nodes = csg.get("nodes") or []
        blast_radii = sorted((n.get("impact", {}).get("blast_radius") or 0) for n in nodes)
        if blast_radii:
            p99_index = max(0, int(len(blast_radii) * 0.99) - 1)
            p99_threshold = blast_radii[p99_index]
            for n in nodes:
                impact = n.get("impact") or {}
                if impact.get("blast_radius", 0) >= p99_threshold and impact.get("blast_radius", 0) > 0 and impact.get("dependents", 0) >= 10:
                    risks.append({
                        "type": "high_blast_radius",
                        "description": f"{n.get('name', n['id'])} is in the top 1% by blast radius ({impact['blast_radius']}) with {impact['dependents']} dependents.",
                        "evidence": [make_evidence("semantic_graph", "High blast-radius symbol", path=n.get("file"), symbol=n["id"])],
                    })

        symbol_to_domain = symbol_to_domain if symbol_to_domain is not None else _build_symbol_to_domain(csg)
        edge_domains: dict[str, set[str]] = {}
        for edge in csg.get("edges") or []:
            src_dom = symbol_to_domain.get(edge.get("from"))
            dst_dom = symbol_to_domain.get(edge.get("to"))
            if src_dom:
                edge_domains.setdefault(edge["from"], set()).add(dst_dom or "")
        nodes_by_id = {n["id"]: n for n in nodes}
        for symbol_id, doms in edge_domains.items():
            doms.discard("")
            if len(doms) >= 3:
                n = nodes_by_id.get(symbol_id)
                risks.append({
                    "type": "cross_domain_hub",
                    "description": f"{symbol_id} has edges touching {len(doms)} distinct domains.",
                    "evidence": [make_evidence("semantic_graph", "Cross-domain hub symbol", symbol=symbol_id, path=n.get("file") if n else None)],
                })

    failure_groups: dict[tuple[str, str], int] = {}
    for obs in observations:
        obs_type = obs.get("type", "")
        if "fail" not in obs_type and "error" not in obs_type and "violation" not in obs_type:
            continue
        scope = obs.get("scope") or obs.get("file") or obs.get("task_id") or ""
        key = (obs_type, str(scope))
        failure_groups[key] = failure_groups.get(key, 0) + 1
    for (obs_type, scope), count in failure_groups.items():
        if count >= 3:
            risks.append({
                "type": "repeated_failure",
                "description": f"{count} '{obs_type}' observations share scope {scope!r}.",
                "evidence": [make_evidence("observation", f"{count} matching observations", artifact_key=f"/{obs_type}/{scope}")],
            })

    from datetime import datetime, timezone
    for entry in project_knowledge_entries:
        last_verified = entry.get("last_verified")
        stale = False
        if entry.get("staleness_flag"):
            stale = True
        elif last_verified:
            try:
                age_days = (datetime.now(timezone.utc) - datetime.fromisoformat(last_verified).replace(tzinfo=timezone.utc)).days
                stale = age_days > 90
            except ValueError:
                pass
        if stale:
            risks.append({
                "type": "stale_knowledge",
                "description": f"Project knowledge entry {entry.get('id', '')!r} is past its staleness threshold.",
                "evidence": [make_evidence("project_knowledge", entry.get("knowledge", "")[:120], artifact_key=f"/entries/{entry.get('id', '')}")],
            })

    by_purpose_root: dict[str, set[str]] = {}
    for cmd in commands:
        if cmd["working_directory"] == ".":
            by_purpose_root.setdefault(cmd["purpose"], set()).add(cmd["command"])
    for purpose, distinct in by_purpose_root.items():
        if len(distinct) > 1:
            risks.append({
                "type": "conflicting_discovery",
                "description": f"Multiple sources disagree about the '{purpose}' command: {', '.join(sorted(distinct))}.",
                "evidence": [make_evidence(
                    "manifest", f"Conflicting '{purpose}' commands", artifact_key=f"/commands/{purpose}",
                )],
            })

    return risks


# ── Observations ────────────────────────────────────────────────


def _load_observations(observations_dir: Path) -> list[dict[str, Any]]:
    if not observations_dir.is_dir():
        return []
    out: list[dict[str, Any]] = []
    try:
        files = sorted(observations_dir.glob("*.jsonl"))
    except OSError:
        return []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


# ── Narrative synthesis (optional, off by default) ─────────────


def _narrative_synthesize(identity: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """v1 has no configured narrative provider wired into the dashboard
    backend. Rather than invent one, this always falls back to the
    deterministic identity produced earlier and records a warning — the
    same code path a real provider failure/timeout would take per the
    RFC's Narrative synthesis section.
    """
    return None, "narrative synthesis requested but no provider is configured; used deterministic identity"


# ── Agent projection ─────────────────────────────────────────────


def project_digest_for_agent(digest: dict[str, Any], *, token_budget: int) -> str:
    """Deterministic bounded Markdown projection. Priority order: identity,
    freshness, readiness gaps, then domains ranked highest-first,
    truncating an individual domain's detail before dropping it outright.
    Never triggers a rebuild — reads only what's passed in.
    """
    from .utils import estimate_tokens_from_text

    def cost(text: str) -> int:
        return estimate_tokens_from_text(text)

    header = f"# Repository Digest: {digest.get('identity', {}).get('name', 'unknown')}\n\n"
    if cost(header) > token_budget:
        notice = "(digest truncated: budget too small)\n"
        return notice if cost(notice) <= token_budget else ""

    sections: list[str] = [header]
    used = cost(header)

    identity = digest.get("identity") or {}
    if identity.get("summary"):
        block = f"{identity['summary']}\n\n"
        if used + cost(block) <= token_budget:
            sections.append(block)
            used += cost(block)

    freshness_state = digest.get("_effective_state")
    if freshness_state:
        block = f"**Freshness:** {freshness_state}\n\n"
        if used + cost(block) <= token_budget:
            sections.append(block)
            used += cost(block)

    unresolved_gaps = digest.get("gaps") or []
    if unresolved_gaps:
        lines = ["## Readiness gaps\n"]
        for gap in unresolved_gaps:
            lines.append(f"- {gap.get('description', gap.get('type', ''))}")
        block = "\n".join(lines) + "\n\n"
        if used + cost(block) <= token_budget:
            sections.append(block)
            used += cost(block)

    domains = sorted(digest.get("domains") or [], key=lambda d: d.get("rank", 999999))
    if domains:
        sections.append("## Domains\n\n")
        used += cost("## Domains\n\n")
        for domain in domains:
            full = f"### {domain['label']}\n{domain.get('summary', '')} ({domain['file_count']} files, {domain['symbol_count']} symbols)\n\n"
            if used + cost(full) <= token_budget:
                sections.append(full)
                used += cost(full)
                continue
            brief = f"- {domain['label']} ({domain['file_count']} files)\n"
            if used + cost(brief) <= token_budget:
                sections.append(brief)
                used += cost(brief)
            else:
                break

    return "".join(sections)
