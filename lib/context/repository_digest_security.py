"""Repository Digest — Phase 5A: Security.

Deterministic, evidence-based security discovery — never an LLM judgment
call. Two pre-existing, related mechanisms were found and deliberately
NOT reused, for different reasons:

  - `speed security` (lib/security.sh) runs an LLM "Security Auditor
    agent" over one feature's task diffs — non-deterministic and
    feature-scoped, the wrong shape for a persistent, evidence-backed
    repository-wide digest.
  - `grounding_check_secrets()` (lib/grounding.sh) is a real, already-
    shipped, already-tested secret scanner — but it scans one task
    branch's git diff at merge-gate time, is bash, and is tightly
    coupled to the task/grounding pipeline (TASKS_DIR, LOGS_DIR, a
    branch to diff against) with no repo-wide, buildable-from-Python
    entry point. Not practically reusable here. Its pattern set is used
    as a cross-check, though: this module's database_url_credentials
    pattern was added specifically because grounding.sh already
    validates that category as low-false-positive enough to ship.

Four categories, each gated on real, defensible evidence:

  1. Secret indicators — three tiers, a value is NEVER stored:
     a. sensitive-named declared env vars (reuses Phase 4's
        repository_digest_runtime.derive_environment_variables output —
        not re-derived)
     b. hardcoded secret-*shaped* values in source (name/file/line/
        pattern-type only)
     c. committed key/cert files by extension (project_map is already
        .gitignore-aware, so a match here means genuinely committed)

  2. Sensitive configuration — Dockerfile with no USER (runs as root),
     CORS wildcard origin, TLS verification disabled, DEBUG-enabled
     patterns. All well-established, industry-standard anti-patterns.

  3. Authentication indicators — presence-only: known auth dependencies
     and auth-guard decorator patterns. No claim about correctness, no
     severity.

  4. Security tooling detected — presence of SECURITY.md, Dependabot
     config, .snyk, bandit config, eslint-security plugin.

Explicitly NOT implemented: CVE/dependency-vulnerability scanning — no
evidence source without a network call, which is out of scope. Callers
should represent that as an unavailable capability, not fake it.

Severity is only ever set for the small set of objectively-established
anti-patterns below; everything else omits severity rather than invent
one no evidence supports.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .repository_digest_schema import MAX_FILE_BYTES, is_within, line_number, make_evidence

# ── Secret indicators — hardcoded secret-shaped values ───────────
#
# Each pattern is a well-known, unambiguous credential *format* — not a
# generic "looks suspicious" heuristic. The matched value itself is never
# captured in any group used downstream; only the match's position and a
# best-effort preceding variable name (never its value) are kept.

_SECRET_VALUE_PATTERNS: tuple[tuple[str, "re.Pattern[str]"], ...] = (
    ("aws_access_key_id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("openai_api_key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("stripe_key", re.compile(r"\bsk_(live|test)_[A-Za-z0-9]{20,}\b")),
    ("private_key_block", re.compile(r"-----BEGIN (RSA |EC |OPENSSH |DSA |)PRIVATE KEY-----")),
    ("jwt_like_token", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    # Same category the repo's own pre-existing branch-diff secret gate
    # (grounding_check_secrets() in lib/grounding.sh) already validates as
    # low-false-positive enough to ship — kept consistent with it. Its
    # broader "Generic High-Entropy Secret" pattern (bare 40+ char
    # base64-ish string) is deliberately NOT mirrored here: that pattern
    # is tuned for a narrow branch-diff gate, and would have a materially
    # higher false-positive rate scanning an entire repository at rest.
    ("database_url_credentials", re.compile(r"\b[a-z]+://[^\s:'\"@/]+:[^\s@'\"]+@[^\s/'\"]+")),
)
# A single combined alternation was tried here and measured *slower* in
# practice (profiled on this repo: ~580ms separate vs. ~880ms combined) —
# each pattern above has a distinct literal prefix (AKIA, gh, xox, sk-,
# sk_, -----BEGIN, eyJ, a URL scheme) that Python's re module fast-paths
# via its own literal-prefix search when compiled alone; folding them
# into one alternation loses that per-pattern fast path. Kept as separate
# compiled patterns deliberately, not merged.

_PRECEDING_VAR_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*[:=]\s*[\"']?\Z")

_KEY_FILE_EXTENSIONS = {".pem", ".key", ".p12", ".pfx", ".jks", ".keystore"}


def _preceding_variable_name(content: str, match_start: int) -> str:
    """Best-effort variable name immediately before the match (e.g.
    `API_KEY = "..."` -> "API_KEY"). Only ever looks at text *before* the
    secret-shaped value — never returns or touches the value itself.
    """
    window_start = max(0, match_start - 80)
    window = content[window_start:match_start]
    m = _PRECEDING_VAR_RE.search(window)
    return m.group(1) if m else ""


_GENERATED_LOCKFILE_NAMES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Cargo.lock", "Gemfile.lock",
}


def _iter_scannable_files(project_map: dict[str, Any]) -> list[str]:
    """Source and config files only — never binary/asset categories,
    which can't meaningfully contain a hardcoded credential and would
    just waste time reading. Package-manager lockfiles are excluded too:
    they're deterministically machine-generated (package names, versions,
    integrity hashes), never hand-edited, and on this repo alone account
    for ~800KB of the ~9.8MB otherwise scanned for a category of file
    that structurally cannot contain a hardcoded credential.
    """
    return [
        f["path"] for f in project_map.get("files") or []
        if f.get("path")
        and f.get("category") in ("source", "config")
        and Path(f["path"]).name not in _GENERATED_LOCKFILE_NAMES
    ]


def _read_for_scanning(abs_path: Path, project_root: Path, max_bytes: int = MAX_FILE_BYTES) -> str | None:
    """Bounded, root-contained read for security scanning. Deliberately
    does NOT go through repository_digest_schema.safe_read_text's
    credential denylist: that denylist exists to keep sensitive files'
    *content* out of supplemental documentation/identity text, where
    reading a .env or key file would never be appropriate. This
    scanner's entire job is reading exactly those files — safely,
    since a matched value is never captured or stored, only
    pattern-type/name/line — so denylisting them here would blind the
    scanner to the files most likely to contain what it's looking for.

    Still enforces the containment guarantee those helpers share:
    resolved location must stay inside the project root, symlinks
    included — a path built from a project_map entry is not
    necessarily trustworthy just because project_map said so.
    """
    try:
        resolved = abs_path.resolve()
    except OSError:
        return None
    if not is_within(resolved, project_root):
        return None
    try:
        if not resolved.is_file() or resolved.stat().st_size > max_bytes:
            return None
        return resolved.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def derive_secret_indicators(
    project_root: Path,
    project_map: dict[str, Any],
    environment_variables: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Returns (indicators, warnings). `environment_variables` is the
    already-computed runtime_config.environment_variables list — reused,
    not re-derived, per RFC "search before creating a new extractor."
    """
    indicators: list[dict[str, Any]] = []
    warnings: list[str] = []

    for env_var in environment_variables:
        if not env_var.get("looks_sensitive"):
            continue
        indicators.append({
            "category": "declared_name",
            "pattern_type": None,
            "name": env_var.get("name", ""),
            "file": env_var.get("source_file", ""),
            "line": None,
            "redacted": True,
            "evidence": env_var.get("evidence", []),
        })

    for path in _iter_scannable_files(project_map):
        abs_path = project_root / path
        content = _read_for_scanning(abs_path, project_root)
        if content is None:
            # Code-review finding: a file this scanner skips (over
            # MAX_FILE_BYTES, most concretely — a checked-in bundled/
            # generated file categorized as "source" is exactly the
            # shape that both crosses that size and could contain a
            # real hardcoded secret) previously vanished with zero
            # trace, unlike derive_github_actions_workflows, which
            # already warns on every file it can't read/parse. Only the
            # size case is worth a warning here: is_within/containment
            # failures never happen for a project_map-sourced path, and
            # a plain unreadable/OSError file has nothing more specific
            # to report than "couldn't read it," which isn't actionable
            # the way "skipped because oversized" is.
            try:
                if abs_path.stat().st_size > MAX_FILE_BYTES:
                    warnings.append(f"{path}: skipped secret scan — file exceeds {MAX_FILE_BYTES} bytes")
            except OSError:
                pass
            continue
        for pattern_type, pattern in _SECRET_VALUE_PATTERNS:
            try:
                matches = list(pattern.finditer(content))
            except re.error:
                warnings.append(f"secret pattern scan failed on {path}: malformed source")
                continue
            for m in matches:
                line = line_number(content, m.start())
                indicators.append({
                    "category": "hardcoded_value_pattern",
                    "pattern_type": pattern_type,
                    "name": _preceding_variable_name(content, m.start()),
                    "file": path,
                    "line": line,
                    "redacted": True,
                    "evidence": [make_evidence("manifest", f"source text matches the {pattern_type} format", path=path, line=line)],
                })

    for f in project_map.get("files") or []:
        path = f.get("path")
        if not path:
            continue
        ext = Path(path).suffix.lower()
        if ext in _KEY_FILE_EXTENSIONS:
            indicators.append({
                "category": "committed_key_file",
                "pattern_type": ext.lstrip("."),
                "name": Path(path).name,
                "file": path,
                "line": None,
                "redacted": True,
                "evidence": [make_evidence("project_map", f"{ext} file is committed to the repository", path=path)],
            })

    return indicators, warnings


# ── Sensitive configuration ──────────────────────────────────────

_DOCKERFILE_USER_RE = re.compile(r"^\s*USER\s+\S+", re.MULTILINE)
_CORS_WILDCARD_RE = re.compile(
    r"""(Access-Control-Allow-Origin['"]?\s*[:=]\s*['"]?\*|origin\s*:\s*['"]\*['"]|CORS_ORIGIN_ALLOW_ALL\s*=\s*True|allow_origins\s*=\s*\[\s*['"]\*['"]\s*\])""",
)
_TLS_DISABLED_RE = re.compile(
    r"""(verify\s*=\s*False|rejectUnauthorized\s*:\s*false|NODE_TLS_REJECT_UNAUTHORIZED\s*=\s*['"]?0|InsecureSkipVerify\s*:\s*true)""",
)
_DEBUG_ENABLED_RE = re.compile(r"""^\s*DEBUG\s*=\s*True\s*$""", re.MULTILINE)


def derive_sensitive_configuration(project_root: Path, project_map: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    dockerfile = project_root / "Dockerfile"
    text = _read_for_scanning(dockerfile, project_root) or ""
    if text and not _DOCKERFILE_USER_RE.search(text):
        findings.append({
            "category": "container_runs_as_root",
            "title": "Dockerfile does not set a non-root USER",
            "description": "No USER instruction was found — the container image defaults to running as root.",
            "severity": "low",
            "file": "Dockerfile",
            "line": None,
            "evidence": [make_evidence("manifest", "Dockerfile has no USER instruction", path="Dockerfile")],
        })

    for path in _iter_scannable_files(project_map):
        content = _read_for_scanning(project_root / path, project_root)
        if content is None:
            continue

        m = _CORS_WILDCARD_RE.search(content)
        if m:
            line = line_number(content, m.start())
            findings.append({
                "category": "cors_wildcard_origin",
                "title": "CORS configured to allow any origin",
                "description": "A wildcard CORS origin was found — any website can make authenticated cross-origin requests.",
                "severity": "medium",
                "file": path,
                "line": line,
                "evidence": [make_evidence("manifest", "wildcard CORS origin", path=path, line=line)],
            })

        m = _TLS_DISABLED_RE.search(content)
        if m:
            line = line_number(content, m.start())
            findings.append({
                "category": "tls_verification_disabled",
                "title": "TLS certificate verification appears to be disabled",
                "description": "Code disabling TLS/SSL certificate verification was found, which allows man-in-the-middle attacks.",
                "severity": "high",
                "file": path,
                "line": line,
                "evidence": [make_evidence("manifest", "TLS verification disabled", path=path, line=line)],
            })

        m = _DEBUG_ENABLED_RE.search(content)
        if m:
            line = line_number(content, m.start())
            findings.append({
                "category": "debug_enabled",
                "title": "DEBUG appears to be hardcoded on",
                "description": "A DEBUG = True setting was found committed to source, which can leak stack traces and internals in production.",
                "severity": "medium",
                "file": path,
                "line": line,
                "evidence": [make_evidence("manifest", "DEBUG = True", path=path, line=line)],
            })

    return findings


# ── Authentication indicators ────────────────────────────────────

_AUTH_DEPENDENCY_NAMES = (
    "passport", "next-auth", "@nestjs/passport", "jsonwebtoken", "bcrypt", "argon2",
    "django-rest-framework-simplejwt", "flask-login", "flask-jwt-extended", "pyjwt",
    "authlib", "python-jose",
)
_AUTH_PATTERN_RE = re.compile(
    r"(@login_required|@PreAuthorize|@UseGuards\(\s*AuthGuard|@RequiresAuth|@jwt_required|@Secured\b)",
)


def _package_json_deps(project_root: Path) -> dict[str, Any]:
    """dependencies + devDependencies of the root package.json, sandboxed
    through _read_for_scanning — {} if absent/unreadable/malformed.
    """
    text = _read_for_scanning(project_root / "package.json", project_root)
    if text is None:
        return {}
    try:
        data = json.loads(text)
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {**(data.get("dependencies") or {}), **(data.get("devDependencies") or {})}


def derive_authentication_indicators(project_root: Path, project_map: dict[str, Any]) -> list[dict[str, Any]]:
    indicators: list[dict[str, Any]] = []

    deps = _package_json_deps(project_root)
    if deps:
        for name in _AUTH_DEPENDENCY_NAMES:
            if name in deps:
                indicators.append({
                    "type": "dependency", "name": name, "file": "package.json", "line": None,
                    "evidence": [make_evidence("manifest", f"package.json dependency '{name}'", path="package.json")],
                })

    for req_file in ("requirements.txt", "requirements-dev.txt"):
        text = _read_for_scanning(project_root / req_file, project_root)
        if text is None:
            continue
        for line in text.splitlines():
            pkg_name = re.split(r"[<>=!\[; ]", line.strip(), maxsplit=1)[0].strip().lower()
            if pkg_name in _AUTH_DEPENDENCY_NAMES:
                indicators.append({
                    "type": "dependency", "name": pkg_name, "file": req_file, "line": None,
                    "evidence": [make_evidence("manifest", f"{req_file} dependency '{pkg_name}'", path=req_file)],
                })

    for path in _iter_scannable_files(project_map):
        content = _read_for_scanning(project_root / path, project_root)
        if content is None:
            continue
        m = _AUTH_PATTERN_RE.search(content)
        if m:
            line = line_number(content, m.start())
            indicators.append({
                "type": "pattern", "name": m.group(1), "file": path, "line": line,
                "evidence": [make_evidence("manifest", f"{m.group(1)} auth guard/decorator", path=path, line=line)],
            })

    return indicators


# ── Security tooling detected ────────────────────────────────────

_SECURITY_TOOLING_FILES = (
    "SECURITY.md", ".github/dependabot.yml", ".snyk", ".bandit", "bandit.yaml", "bandit.yml",
)


def derive_security_tooling(project_root: Path) -> list[dict[str, Any]]:
    detected: list[dict[str, Any]] = []
    for rel in _SECURITY_TOOLING_FILES:
        path = project_root / rel
        if path.is_file():
            detected.append({
                "name": rel, "file": rel,
                "evidence": [make_evidence("manifest", f"{rel} present at repository root", path=rel)],
            })

    deps = _package_json_deps(project_root)
    if "eslint-plugin-security" in deps:
        detected.append({
            "name": "eslint-plugin-security", "file": "package.json",
            "evidence": [make_evidence("manifest", "package.json dependency 'eslint-plugin-security'", path="package.json")],
        })

    return detected
