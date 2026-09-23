"""Repository Digest — Phase 4: API & Data.

Two independent discovery passes, both digest-layer (never touch Layer 1):

  1. Routes — a Layer-1-independent regex scan over raw source text, the
     same style command_discovery.py already uses for Makefiles/CI YAML.
     Not derived from tree-sitter: SymbolDef.decorators is declared in
     treesitter_extract.py but never populated by any extraction path
     today (verified by reading _parse_ast_grep_matches — SymbolDef() is
     always constructed without a decorators= argument), so there is no
     existing decorator data to reuse. Scoped to frameworks whose route
     registration syntax is reliably regex-matchable: FastAPI/Flask
     (Python), Express/NestJS (JS/TS), Spring MVC (Java), and Strawberry
     GraphQL resolvers (Python) — the framework already in use by this
     very repository's own dashboard backend.

  2. Entities — reused, not re-extracted. csg["nodes"][*]["schema"] is
     already computed by Layer 1 (ast-grep ORM rules for Django/
     SQLAlchemy/JPA/GORM/TypeORM/Diesel/EF Core/Prisma — see
     lib/context/rules/*/models.yml). But tracing treesitter_extract.py's
     _accumulate_orm_match shows it's genuinely broken for producing a
     coherent per-entity view: table_name is declared on SchemaAnnotation
     but never assigned anywhere, and column/relationship matches get
     keyed by the *field's own name* rather than the enclosing class, so
     schema_annotations[ClassName].columns is always empty. This is a
     Layer 1 (treesitter_extract.py) bug — fixing it is out of scope
     here per the Layer 1 Safety directive ("Layer 1 symbol extraction"
     is explicitly protected), so it is not fixed. Instead this module
     reconstructs the class/column association with an explicit,
     disclosed heuristic — nearest enclosing class by line proximity,
     within the same file — over data Layer 1 already persists. Every
     entity produced this way is marked columns_inferred=True so nothing
     downstream mistakes the heuristic for a verified structural link.
     relationship_type is never propagated from Layer 1's hardcoded
     "one-to-many" default (see _accumulate_orm_match) — that value is
     not evidence-derived, so surfacing it as fact would be a form of
     fabrication; cardinality is reported "unknown" instead.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .repository_digest_schema import MAX_FILE_BYTES, line_number, make_evidence

# ── Routes ────────────────────────────────────────────────────

_PY_DECORATOR_ROUTE_RE = re.compile(
    r'@(?:\w+\.)*(?P<router>\w+)\.(?P<method>get|post|put|patch|delete|head|options)\(\s*["\'](?P<path>[^"\']+)["\']',
)
_PY_FLASK_ROUTE_RE = re.compile(
    r'@(?:\w+\.)*\w+\.route\(\s*["\'](?P<path>[^"\']+)["\']'
    r'(?:\s*,\s*methods\s*=\s*\[(?P<methods>[^\]]*)\])?',
)
_PY_STRAWBERRY_RE = re.compile(
    r'@strawberry\.(?P<op>field|mutation|subscription)\b',
)
_PY_DEF_AFTER_RE = re.compile(r'^\s*(?:async\s+)?def\s+(\w+)\s*\(', re.MULTILINE)

_JS_CALL_ROUTE_RE = re.compile(
    r'\b(?:app|router)\.(?P<method>get|post|put|patch|delete)\(\s*[`"\'](?P<path>[^`"\']+)[`"\']',
)
_JS_NEST_ROUTE_RE = re.compile(
    r'@(?P<method>Get|Post|Put|Patch|Delete)\(\s*[`"\']?(?P<path>[^`"\')]*)[`"\']?\)',
)
_JS_NEST_CONTROLLER_RE = re.compile(
    r'@Controller\(\s*[`"\']?(?P<prefix>[^`"\')]*)[`"\']?\)',
)

_JAVA_METHOD_MAPPING_RE = re.compile(
    r'@(?P<ann>GetMapping|PostMapping|PutMapping|PatchMapping|DeleteMapping|RequestMapping)'
    r'(?:\((?P<args>[^)]*)\))?',
)
_JAVA_PATH_ARG_RE = re.compile(r'(?:value\s*=\s*)?["\']([^"\']+)["\']')
_JAVA_REQUEST_METHOD_RE = re.compile(r'RequestMethod\.(\w+)')
_JAVA_CLASS_REQUEST_MAPPING_RE = re.compile(
    r'@RequestMapping\(\s*(?:value\s*=\s*)?["\'](?P<prefix>[^"\']*)["\']',
)
_JAVA_CLASS_DECL_RE = re.compile(r'\bclass\s+(\w+)')
# Skipped between an @RequestMapping match and whatever it actually
# annotates, to reach the real next declaration: further annotations
# (each with its own optional (...) args, e.g. @CrossOrigin(origins =
# "*")) and access/other modifiers.
_JAVA_ANNOTATION_OR_MODIFIER_RE = re.compile(
    r'\s*(?:@\w+(?:\([^)]*\))?|public|private|protected|static|final|abstract)\s*'
)


def _java_request_mapping_is_class_level(content: str, end: int) -> bool:
    """True if the @RequestMapping ending at `end` sits directly on a
    class declaration, false if it's on a method (or anything else).

    @RequestMapping's own regex matches identically whether it's written
    above a class or a method — there is no syntactic difference at the
    annotation site. The previous heuristic ("does the literal word
    'class' appear anywhere in the next 300 characters") produced false
    positives whenever another class happened to be declared within that
    window (a common shape: multiple classes per file, or a short method
    body) and mislabeled a method-level route as a class-level prefix.

    This instead walks forward past any further annotations/modifiers —
    the only things Java syntax permits between one annotation and the
    thing it decorates — and checks whether the actual next declaration
    starts with "class NAME". A method declaration's return type/name is
    never "class", so this can't produce the same false positive: it
    looks at the *next* declaration specifically, not an unbounded
    window that might contain an unrelated later class.
    """
    # _JAVA_CLASS_REQUEST_MAPPING_RE only captures up through the closing
    # quote of the prefix string, not the annotation's own closing ")" —
    # e.g. @RequestMapping(value = "/x", method = RequestMethod.GET) has
    # more content after the match before its real close. Same
    # no-nested-parens assumption _JAVA_METHOD_MAPPING_RE's [^)]* already
    # makes elsewhere in this file.
    close_paren = content.find(")", end)
    pos = close_paren + 1 if close_paren != -1 else end
    while True:
        m = _JAVA_ANNOTATION_OR_MODIFIER_RE.match(content, pos)
        if not m or m.end() == pos:
            break
        pos = m.end()
    # No annotation/modifier immediately follows (the common case: a
    # bare "class Foo" with no further modifier) — still need to skip
    # the whitespace/newline between the annotation and the declaration,
    # since .match() below is anchored exactly at `pos`.
    while pos < len(content) and content[pos].isspace():
        pos += 1
    return _JAVA_CLASS_DECL_RE.match(content, pos) is not None

_NEST_METHOD_MAP = {"Get": "GET", "Post": "POST", "Put": "PUT", "Patch": "PATCH", "Delete": "DELETE"}
_JAVA_ANN_METHOD_MAP = {
    "GetMapping": "GET", "PostMapping": "POST", "PutMapping": "PUT",
    "PatchMapping": "PATCH", "DeleteMapping": "DELETE",
}


def _nearest_following_def(content: str, offset: int) -> str:
    match = _PY_DEF_AFTER_RE.search(content, offset)
    if match and match.start() - offset < 200:
        return match.group(1)
    return ""


def _extract_python_routes(content: str, rel_path: str) -> list[dict[str, Any]]:
    routes: list[dict[str, Any]] = []
    for m in _PY_DECORATOR_ROUTE_RE.finditer(content):
        line = line_number(content, m.start())
        handler = _nearest_following_def(content, m.end())
        routes.append({
            "method": m.group("method").upper(),
            "path": m.group("path"),
            "file": rel_path,
            "line": line,
            "handler": handler,
            "framework": "fastapi_or_flask",
            "evidence": [make_evidence("manifest", f"@{m.group('router')}.{m.group('method')}(...) route decorator", path=rel_path, line=line)],
        })
    for m in _PY_FLASK_ROUTE_RE.finditer(content):
        line = line_number(content, m.start())
        handler = _nearest_following_def(content, m.end())
        methods_raw = m.group("methods")
        methods = [x.strip().strip("'\"") for x in methods_raw.split(",")] if methods_raw else ["GET"]
        for method in methods:
            routes.append({
                "method": method.upper(),
                "path": m.group("path"),
                "file": rel_path,
                "line": line,
                "handler": handler,
                "framework": "flask",
                "evidence": [make_evidence("manifest", "@app.route(...) decorator", path=rel_path, line=line)],
            })
    for m in _PY_STRAWBERRY_RE.finditer(content):
        handler = _nearest_following_def(content, m.end())
        if not handler:
            # No def found within range: far more likely this is prose
            # mentioning the decorator (a docstring/comment) than a real
            # anonymous resolver — Strawberry always names its resolvers.
            # Skip rather than report an unverifiable "(unnamed resolver)"
            # entry (found via QA: tests/prototype_clustering_v3.py has a
            # docstring literally describing "@strawberry.mutation /
            # @strawberry.field decorated functions", which this regex
            # was matching as if it were real code).
            continue
        line = line_number(content, m.start())
        op = m.group("op")
        routes.append({
            "method": {"field": "QUERY", "mutation": "MUTATION", "subscription": "SUBSCRIPTION"}[op],
            # GraphQL has no URL path — the resolver/field name is the
            # closest equivalent, and is labeled as such by "framework".
            "path": handler,
            "file": rel_path,
            "line": line,
            "handler": handler,
            "framework": "strawberry_graphql",
            "evidence": [make_evidence("manifest", f"@strawberry.{op} resolver", path=rel_path, line=line)],
        })
    return routes


def _extract_js_ts_routes(content: str, rel_path: str) -> list[dict[str, Any]]:
    routes: list[dict[str, Any]] = []
    for m in _JS_CALL_ROUTE_RE.finditer(content):
        line = line_number(content, m.start())
        routes.append({
            "method": m.group("method").upper(),
            "path": m.group("path"),
            "file": rel_path,
            "line": line,
            "handler": "",
            "framework": "express",
            "evidence": [make_evidence("manifest", "app/router HTTP method call", path=rel_path, line=line)],
        })

    controller_prefixes: list[tuple[int, str]] = [
        (m.start(), m.group("prefix")) for m in _JS_NEST_CONTROLLER_RE.finditer(content)
    ]

    def _prefix_for(offset: int) -> str:
        candidates = [p for pos, p in controller_prefixes if pos < offset]
        return candidates[-1] if candidates else ""

    for m in _JS_NEST_ROUTE_RE.finditer(content):
        line = line_number(content, m.start())
        prefix = _prefix_for(m.start())
        path = "/".join(p.strip("/") for p in (prefix, m.group("path")) if p.strip("/")) or "/"
        if not path.startswith("/"):
            path = "/" + path
        routes.append({
            "method": _NEST_METHOD_MAP[m.group("method")],
            "path": path,
            "file": rel_path,
            "line": line,
            "handler": "",
            "framework": "nestjs",
            "evidence": [make_evidence("manifest", f"@{m.group('method')}(...) route decorator", path=rel_path, line=line)],
        })
    return routes


def _extract_java_routes(content: str, rel_path: str) -> list[dict[str, Any]]:
    class_mappings: list[tuple[int, str]] = [
        (m.start(), m.group("prefix")) for m in _JAVA_CLASS_REQUEST_MAPPING_RE.finditer(content)
        if _java_request_mapping_is_class_level(content, m.end())
    ]
    class_mapping_positions = {pos for pos, _ in class_mappings}

    def _prefix_for(offset: int) -> str:
        candidates = [p for pos, p in class_mappings if pos < offset]
        return candidates[-1] if candidates else ""

    method_routes: list[dict[str, Any]] = []
    class_positions_with_method_routes: set[int] = set()
    for m in _JAVA_METHOD_MAPPING_RE.finditer(content):
        if m.start() in class_mapping_positions:
            # A class-level @RequestMapping is a prefix declaration, not a
            # route in its own right — handled in the fallback pass below,
            # only when the class has no method-level route at all.
            continue
        line = line_number(content, m.start())
        ann = m.group("ann")
        args = m.group("args") or ""
        if ann == "RequestMapping":
            method_match = _JAVA_REQUEST_METHOD_RE.search(args)
            method = method_match.group(1) if method_match else "ANY"
        else:
            method = _JAVA_ANN_METHOD_MAP[ann]
        prefix = _prefix_for(m.start())
        preceding = [pos for pos in class_mapping_positions if pos < m.start()]
        if preceding:
            class_positions_with_method_routes.add(max(preceding))
        path_match = _JAVA_PATH_ARG_RE.search(args)
        raw_path = path_match.group(1).strip() if path_match else ""
        path = "/".join(p.strip("/") for p in (prefix, raw_path) if p.strip("/")) or "/"
        if not path.startswith("/"):
            path = "/" + path
        method_routes.append({
            "method": method,
            "path": path,
            "file": rel_path,
            "line": line,
            "handler": "",
            "framework": "spring_mvc",
            "evidence": [make_evidence("manifest", f"@{ann}(...) route annotation", path=rel_path, line=line)],
        })

    # A class whose @RequestMapping prefix produced zero method-level
    # routes (e.g. route methods live on an interface this class
    # implements, generated elsewhere and not present in this source
    # checkout) still gets one honest entry — its own declared prefix —
    # rather than silently disappearing.
    fallback_routes: list[dict[str, Any]] = []
    for pos, prefix in class_mappings:
        if pos in class_positions_with_method_routes:
            continue
        line = line_number(content, pos)
        path = prefix if prefix.startswith("/") else "/" + prefix
        fallback_routes.append({
            "method": "ANY", "path": path or "/", "file": rel_path, "line": line, "handler": "",
            "framework": "spring_mvc",
            "evidence": [make_evidence("manifest", "@RequestMapping(...) class-level prefix, no method-level route found in source", path=rel_path, line=line)],
        })

    return method_routes + fallback_routes


_ROUTE_EXTRACTORS: dict[str, Any] = {
    "python": _extract_python_routes,
    "javascript": _extract_js_ts_routes,
    "typescript": _extract_js_ts_routes,
    "java": _extract_java_routes,
}


def derive_routes(project_root: Path, project_map: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """Scan every source file in a supported language for route patterns.
    Never guesses a route from a filename — only an actual matched call/
    decorator produces an entry. Returns (routes, warnings).
    """
    routes: list[dict[str, Any]] = []
    warnings: list[str] = []
    languages_seen: set[str] = set()

    for f in project_map.get("files") or []:
        lang = f.get("language")
        path = f.get("path")
        if not lang or not path or lang not in _ROUTE_EXTRACTORS:
            continue
        languages_seen.add(lang)
        abs_path = project_root / path
        try:
            if abs_path.stat().st_size > MAX_FILE_BYTES:
                continue
            content = abs_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            routes.extend(_ROUTE_EXTRACTORS[lang](content, path))
        except re.error:
            warnings.append(f"route scan failed on {path}: malformed source")

    if languages_seen and not routes:
        warnings.append(
            "no API routes were discovered from supported frameworks "
            "(FastAPI/Flask, Express/NestJS, Spring MVC, Strawberry GraphQL) "
            "despite finding source files in a supported language"
        )

    return routes, warnings


# ── Entities ──────────────────────────────────────────────────


def _language_for_file(rel_path: str, project_map: dict[str, Any]) -> str | None:
    for f in project_map.get("files") or []:
        if f.get("path") == rel_path:
            return f.get("language")
    return None


def derive_entities(csg: dict[str, Any] | None, project_map: dict[str, Any]) -> list[dict[str, Any]]:
    """See module docstring for the columns_inferred heuristic and why
    relationship cardinality is never propagated from Layer 1.
    """
    if not csg:
        return []
    nodes = csg.get("nodes") or []

    class_nodes = [n for n in nodes if n.get("kind") == "class" and n.get("schema") is not None and n.get("id") and n.get("name")]
    # Schema-bearing "variable" nodes are the mis-keyed column/relationship
    # matches (see module docstring) — every one of them, regardless of
    # which file-local class it *should* belong to.
    schema_bearing_vars = [n for n in nodes if n.get("kind") == "variable" and n.get("schema") is not None]

    classes_by_file: dict[str, list[dict[str, Any]]] = {}
    for n in class_nodes:
        classes_by_file.setdefault(n.get("file", ""), []).append(n)
    for bucket in classes_by_file.values():
        bucket.sort(key=lambda n: n.get("line", 0))

    entities: dict[str, dict[str, Any]] = {}
    for n in class_nodes:
        entities[n["id"]] = {
            "name": n["name"],
            "file": n.get("file"),
            "line": n.get("line"),
            "table_name": None,  # never computed anywhere in Layer 1 today
            "language": _language_for_file(n.get("file", ""), project_map),
            "columns": [],
            "columns_inferred": True,
            "relationships": [],
            "evidence": [make_evidence("semantic_graph", "ORM model class", path=n.get("file"), line=n.get("line"), symbol=n["id"])],
        }

    for var in schema_bearing_vars:
        file = var.get("file", "")
        line = var.get("line", 0)
        candidates = classes_by_file.get(file, [])
        enclosing = None
        for c in candidates:
            if c.get("line", 0) <= line:
                enclosing = c
            else:
                break
        if enclosing is None:
            continue
        entity = entities[enclosing["id"]]
        schema = var.get("schema") or {}
        for col in schema.get("columns") or []:
            entity["columns"].append({
                "name": col.get("name"),
                "type": col.get("type", "unknown"),
                "primary_key": bool(col.get("primary_key")),
            })
        for rel in schema.get("relationships") or []:
            entity["relationships"].append({
                "field": rel.get("name"),
                "target_entity": rel.get("target_model"),
                # Layer 1 hardcodes "one-to-many" for every relationship()
                # match regardless of actual cardinality — not evidence,
                # so it is never surfaced as if it were verified.
                "cardinality": "unknown",
            })

    return list(entities.values())


def derive_persistence_summary(entities: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not entities:
        return None
    by_language: dict[str, int] = {}
    for e in entities:
        lang = e.get("language") or "unknown"
        by_language[lang] = by_language.get(lang, 0) + 1
    return {
        "mode": "orm",
        "entity_count": len(entities),
        "by_language": by_language,
    }
