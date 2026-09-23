"""Repository Digest — Phase 4: Runtime & Configuration.

All discovery here is a digest-layer, Layer-1-independent scan over
well-known manifest/config files (Dockerfile, package.json, pyproject.toml,
.python-version, .nvmrc, go.mod, Gemfile) — the same category of source
command_discovery.py already reads for commands.

SECURITY: environment variable values are never read into memory as
"the value" and never stored anywhere in the returned structures — every
extractor here captures only the variable *name* (the text left of `=`/
`:`), by construction, the same discipline env_extract.py already applies
to .env files. See _extract_env_names() and its docstring.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .repository_digest_schema import line_number, load_toml_file, make_evidence, manifest_paths


def _load_package_json(path: Path) -> dict[str, Any] | None:
    """Read and parse one package.json, or None on any I/O/parse failure
    or if its top level isn't an object — the common tail of every
    package.json-driven check below (engines, JS framework deps).
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


# ── Runtimes (language/interpreter versions) ─────────────────────

_DOCKERFILE_FROM_RE = re.compile(r'^\s*FROM\s+(\S+)', re.MULTILINE | re.IGNORECASE)


def _parse_docker_image(image: str) -> tuple[str, str | None] | None:
    """'python:3.12-slim' -> ('python', '3.12-slim'); 'node:22' -> ('node', '22').
    Images with no recognizable language prefix (e.g. custom internal
    image names) are skipped rather than guessed.
    """
    if "/" in image and not image.startswith(("python", "node", "ruby", "golang", "openjdk")):
        # A registry/namespace path (e.g. ghcr.io/org/app) rarely names a
        # language runtime directly — not confidently a runtime signal.
        return None
    name, _, tag = image.partition(":")
    known = {"python", "node", "ruby", "golang", "openjdk", "eclipse-temurin"}
    base = name.split("/")[-1]
    if base not in known:
        return None
    lang_map = {"golang": "go", "eclipse-temurin": "java", "openjdk": "java"}
    return lang_map.get(base, base), (tag or None)


def _package_json_paths(project_root: Path, project_map: dict[str, Any] | None) -> list[str]:
    """"package.json" (repository root, if present) plus every other
    package.json project_map already knows about — the same
    manifest-anywhere-in-the-tree reasoning as
    command_discovery.discover_from_package_json, so a project whose only
    package.json lives in a nested frontend/docs directory still surfaces
    its declared runtimes/frameworks instead of being silently skipped.
    """
    paths: list[str] = []
    if (project_root / "package.json").is_file():
        paths.append("package.json")
    for rel_path in manifest_paths(project_map, "package.json"):
        if rel_path not in paths:
            paths.append(rel_path)
    return paths


def derive_runtimes(project_root: Path, project_map: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    runtimes: list[dict[str, Any]] = []

    dockerfile = project_root / "Dockerfile"
    if dockerfile.is_file():
        try:
            text = dockerfile.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        for m in _DOCKERFILE_FROM_RE.finditer(text):
            parsed = _parse_docker_image(m.group(1).split()[0])
            if not parsed:
                continue
            lang, version = parsed
            line = line_number(text, m.start())
            runtimes.append({
                "language": lang,
                "version": version,
                "source_file": "Dockerfile",
                "evidence": [make_evidence("manifest", f"Dockerfile FROM {m.group(1)}", path="Dockerfile", line=line)],
            })

    pyproject = load_toml_file(project_root / "pyproject.toml")
    if pyproject:
        requires_python = pyproject.get("project", {}).get("requires-python")
        if isinstance(requires_python, str):
            runtimes.append({
                "language": "python", "version": requires_python, "source_file": "pyproject.toml",
                "evidence": [make_evidence("manifest", "pyproject.toml requires-python", path="pyproject.toml")],
            })

    for rel_path in _package_json_paths(project_root, project_map):
        data = _load_package_json(project_root / rel_path)
        if data is not None:
            engines = data.get("engines")
            if isinstance(engines, dict):
                for lang, version in engines.items():
                    if isinstance(version, str):
                        runtimes.append({
                            "language": lang, "version": version, "source_file": rel_path,
                            "evidence": [make_evidence("manifest", f"{rel_path} engines.{lang}", path=rel_path)],
                        })

    version_files = (("python", ".python-version"), ("node", ".nvmrc"))
    for lang, fname in version_files:
        path = project_root / fname
        if path.is_file():
            try:
                version = path.read_text(encoding="utf-8").strip()
            except OSError:
                version = ""
            if version:
                runtimes.append({
                    "language": lang, "version": version, "source_file": fname,
                    "evidence": [make_evidence("manifest", f"{fname} pinned version", path=fname)],
                })

    go_mod = project_root / "go.mod"
    if go_mod.is_file():
        try:
            text = go_mod.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        m = re.search(r'^go\s+(\S+)', text, re.MULTILINE)
        if m:
            runtimes.append({
                "language": "go", "version": m.group(1), "source_file": "go.mod",
                "evidence": [make_evidence("manifest", "go.mod go directive", path="go.mod")],
            })

    return runtimes


# ── Frameworks (declared dependencies only, never inferred from files) ──

_JS_FRAMEWORK_NAMES = (
    "react", "next", "vue", "nuxt", "svelte", "express", "@nestjs/core",
    "fastify", "koa", "@angular/core",
)
_PY_FRAMEWORK_NAMES = (
    "fastapi", "flask", "django", "sqlalchemy", "strawberry-graphql",
    "starlette", "celery",
)


def derive_frameworks(project_root: Path, project_map: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    frameworks: list[dict[str, Any]] = []

    for rel_path in _package_json_paths(project_root, project_map):
        data = _load_package_json(project_root / rel_path)
        if data is not None:
            deps = {**(data.get("dependencies") or {}), **(data.get("devDependencies") or {})}
            for name in _JS_FRAMEWORK_NAMES:
                if name in deps:
                    frameworks.append({
                        "name": name, "version": deps[name] if isinstance(deps[name], str) else None,
                        "source_file": rel_path,
                        "evidence": [make_evidence("manifest", f"{rel_path} dependency '{name}'", path=rel_path)],
                    })

    for req_file in ("requirements.txt", "requirements-dev.txt"):
        path = project_root / req_file
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            pkg_name = re.split(r'[<>=!\[; ]', line, maxsplit=1)[0].strip().lower()
            if pkg_name in _PY_FRAMEWORK_NAMES:
                frameworks.append({
                    "name": pkg_name, "version": None, "source_file": req_file,
                    "evidence": [make_evidence("manifest", f"{req_file} dependency '{pkg_name}'", path=req_file)],
                })

    pyproject = load_toml_file(project_root / "pyproject.toml")
    if pyproject:
        deps = pyproject.get("project", {}).get("dependencies") or []
        for entry in deps if isinstance(deps, list) else []:
            pkg_name = re.split(r'[<>=!\[; ]', str(entry), maxsplit=1)[0].strip().lower()
            if pkg_name in _PY_FRAMEWORK_NAMES:
                frameworks.append({
                    "name": pkg_name, "version": None, "source_file": "pyproject.toml",
                    "evidence": [make_evidence("manifest", f"pyproject.toml dependency '{pkg_name}'", path="pyproject.toml")],
                })

    seen: set[tuple[str, str]] = set()
    deduped = []
    for fw in frameworks:
        key = (fw["name"], fw["source_file"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(fw)
    return deduped


# ── Config sources (file presence, evidence-only) ─────────────────

_KNOWN_CONFIG_FILES = (
    "package.json", "pyproject.toml", "requirements.txt", "Dockerfile",
    "docker-compose.yml", "docker-compose.yaml", "Makefile", "go.mod",
    "Cargo.toml", "Gemfile", "tsconfig.json", "next.config.js",
    "next.config.ts", "vite.config.ts", "vite.config.js",
)


def derive_config_sources(project_root: Path, project_map: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    seen: set[str] = set()
    for fname in _KNOWN_CONFIG_FILES:
        if (project_root / fname).is_file():
            sources.append({
                "file": fname,
                "evidence": [make_evidence("manifest", f"{fname} present at repository root", path=fname)],
            })
            seen.add(fname)
    # Nested manifests project_map already knows about (e.g. a frontend's
    # own package.json) are as real a config source as a root one — same
    # manifest-anywhere-in-the-tree reasoning as _package_json_paths above.
    for rel_path in manifest_paths(project_map, "package.json"):
        if rel_path in seen:
            continue
        sources.append({
            "file": rel_path,
            "evidence": [make_evidence("manifest", f"{rel_path} present in repository", path=rel_path)],
        })
        seen.add(rel_path)
    return sources


# ── Environment variables — names only, never values ────────────

_SENSITIVE_NAME_RE = re.compile(
    r'(KEY|SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL|PRIVATE|AUTH)', re.IGNORECASE,
)

_DOCKERFILE_ENV_RE = re.compile(r'^\s*(?:ENV|ARG)\s+([A-Za-z_][A-Za-z0-9_]*)', re.MULTILINE)


def _looks_sensitive(name: str) -> bool:
    return bool(_SENSITIVE_NAME_RE.search(name))


def _names_from_dockerfile(project_root: Path) -> list[tuple[str, str]]:
    """(name, 'Dockerfile') pairs. Only ever captures the identifier after
    ENV/ARG — the regex has no capture group covering any '=value' that
    might follow, so a value can never reach this function's return value.
    """
    path = project_root / "Dockerfile"
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [(m.group(1), "Dockerfile") for m in _DOCKERFILE_ENV_RE.finditer(text)]


def _names_from_compose(project_root: Path) -> tuple[list[tuple[str, str]], list[str]]:
    """Same name-only discipline as _names_from_dockerfile, for
    docker-compose's `environment:` list/mapping form. Returns
    (names, warnings) — a docker-compose.yml that fails to parse used to
    silently drop every env var name it would have declared, with zero
    trace anywhere in the digest. That matters beyond this one section:
    a sensitive-named var (e.g. STRIPE_SECRET_KEY) declared only in that
    file would then also never become a secret indicator, since
    derive_secret_indicators reuses this list rather than re-deriving it.
    """
    results: list[tuple[str, str]] = []
    warnings: list[str] = []
    for fname in ("docker-compose.yml", "docker-compose.yaml"):
        path = project_root / fname
        if not path.is_file():
            continue
        try:
            import yaml  # type: ignore
        except ImportError:
            continue
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace"))
        except Exception as e:
            warnings.append(f"{fname}: skipped environment-variable discovery — not valid YAML ({e})")
            continue
        if not isinstance(doc, dict):
            continue
        for service in (doc.get("services") or {}).values():
            if not isinstance(service, dict):
                continue
            env = service.get("environment")
            if isinstance(env, dict):
                results.extend((str(k), fname) for k in env.keys())
            elif isinstance(env, list):
                for entry in env:
                    if isinstance(entry, str):
                        name = entry.split("=", 1)[0].strip()
                        if name:
                            results.append((name, fname))
    return results, warnings


def derive_environment_variables(
    project_root: Path, env_keys_raw: Any,
) -> tuple[list[dict[str, Any]], list[str]]:
    """env_keys_raw is repository-digest's already-loaded env-keys.json
    (lib/context/env_extract.py output via layer1.py) — {file: [names]},
    values already stripped before this ever runs. Dockerfile/
    docker-compose add more name-only sources on top.

    Returns (variables, warnings) — the same (result, warnings) shape
    derive_secret_indicators already uses, so a docker-compose.yml parse
    failure (see _names_from_compose) surfaces in the digest instead of
    silently dropping every env var name it would have declared.
    """
    seen: dict[tuple[str, str], dict[str, Any]] = {}

    if isinstance(env_keys_raw, dict):
        for file, names in env_keys_raw.items():
            if not isinstance(names, list):
                continue
            for name in names:
                if not isinstance(name, str):
                    continue
                key = (name, file)
                seen[key] = {
                    "name": name, "source_file": file, "looks_sensitive": _looks_sensitive(name),
                    "evidence": [make_evidence("manifest", f"{file} declares {name}", path=file)],
                }

    compose_names, warnings = _names_from_compose(project_root)
    for name, source_file in [*_names_from_dockerfile(project_root), *compose_names]:
        key = (name, source_file)
        if key in seen:
            continue
        seen[key] = {
            "name": name, "source_file": source_file, "looks_sensitive": _looks_sensitive(name),
            "evidence": [make_evidence("manifest", f"{source_file} declares {name}", path=source_file)],
        }

    return sorted(seen.values(), key=lambda e: (e["source_file"], e["name"])), warnings
