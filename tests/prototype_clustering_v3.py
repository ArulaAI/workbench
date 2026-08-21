#!/usr/bin/env python3
"""
Prototype v3: 6-Layer Domain Clustering.

The user's architecture, validated layer by layer:

  Layer 1: project-map.json inventory → file list + language classification
  Layer 2a: Compiler/AST-based dependency resolution (per-language native rules)
  Layer 2b: Naming convention matching (story/test → component by filename)
  Layer 3: Cross-language bridges (GraphQL operation matching, REST route matching)
  Layer 4: Package-level grouping (monorepo packages share a deployment unit)
  Layer 5: TF-IDF semantic labeling (identifier similarity for domain labels + orphans)
  Layer 6: Co-change with IDF weighting (git history, hub files dampened)

Each layer adds edges to a single graph. Leiden+CPM clusters the result.
"""

import ast
import json
import math
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

import igraph as ig
import leidenalg as la
import networkx as nx
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# ─── Constants ────────────────────────────────────────────────────────

CODE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".rb", ".go", ".rs",
    ".java", ".kt", ".swift", ".c", ".cpp", ".h", ".hpp",
    ".cs", ".php", ".scala", ".ex", ".exs", ".clj", ".cljs",
    ".vue", ".svelte", ".astro",
}

SKIP_DIRS = {
    "node_modules", "vendor", "dist", "build", ".git", "__pycache__",
    ".venv", "venv", ".tox", ".mypy_cache", ".pytest_cache",
    "coverage", ".next", ".nuxt", ".astro", "site-packages",
    "egg-info", ".speed", ".claude", ".storybook-static",
}

SKIP_DIR_PATTERNS = {"_env", "site-packages", "egg-info", ".egg"}

PY_EXTS = {".py"}
TS_EXTS = {".ts", ".tsx", ".js", ".jsx"}


# ─── File discovery ───────────────────────────────────────────────────

def get_code_files(repo_path: str) -> list[str]:
    # Use git ls-files to respect .gitignore, fall back to os.walk
    git_files = _get_git_tracked_files(repo_path)
    if git_files is not None:
        files = []
        for f in git_files:
            ext = os.path.splitext(f)[1].lower()
            if ext not in CODE_EXTENSIONS:
                continue
            # Still apply SKIP_DIRS for safety (node_modules committed by mistake, etc.)
            parts = Path(f).parts
            if any(p in SKIP_DIRS for p in parts):
                continue
            if any(pat in f.lower() for pat in SKIP_DIR_PATTERNS):
                continue
            files.append(f)
        return sorted(files)

    # Fallback: os.walk (not a git repo)
    files = []
    for root, dirs, filenames in os.walk(repo_path):
        dirs[:] = [
            d for d in dirs
            if d not in SKIP_DIRS
            and not any(pat in d.lower() for pat in SKIP_DIR_PATTERNS)
        ]
        for f in filenames:
            ext = os.path.splitext(f)[1].lower()
            if ext in CODE_EXTENSIONS:
                rel = os.path.relpath(os.path.join(root, f), repo_path)
                if "site-packages" not in rel and "_env/" not in rel:
                    files.append(rel)
    return sorted(files)


def _get_git_tracked_files(repo_path: str) -> list[str] | None:
    """Return git-tracked files (respects .gitignore). None if not a git repo."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=repo_path, capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return None
        return [f.strip() for f in result.stdout.split("\n") if f.strip()]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def classify_language(filepath: str) -> str:
    ext = os.path.splitext(filepath)[1].lower()
    if ext in PY_EXTS:
        return "python"
    if ext in TS_EXTS:
        return "typescript"
    if ext == ".rb":
        return "ruby"
    if ext == ".go":
        return "go"
    return "other"


# ─── Layer 2: Compiler-native dependency resolution ───────────────────

def resolve_python_imports(repo_path: str, py_files: list[str]) -> list[tuple[str, str]]:
    """
    Use ast.parse to extract imports, then resolve using Python's module rules.

    Handles monorepo structure: imports say 'travel_api.resolvers.booking' but
    the file path is 'travel-api/travel_api/resolvers/booking.py'. We register
    module paths from every possible package root.
    """
    file_set = set(py_files)
    edges = []

    # Build lookup: module path → file path
    # Register multiple module paths per file to handle monorepo package roots
    module_to_file = {}
    for f in py_files:
        parts = Path(f).parts
        # Register the full path as a module
        mod = f.replace("/", ".").replace("\\", ".")
        if mod.endswith(".py"):
            mod = mod[:-3]
        if mod.endswith(".__init__"):
            mod = mod[:-9]
        module_to_file[mod] = f

        # Also register starting from each subdirectory
        # e.g., travel-api/travel_api/resolvers/booking.py registers:
        #   travel_api.resolvers.booking
        #   resolvers.booking
        #   booking
        for i in range(1, len(parts)):
            submod = ".".join(parts[i:])
            if submod.endswith(".py"):
                submod = submod[:-3]
            if submod.endswith(".__init__"):
                submod = submod[:-9]
            if submod and submod not in module_to_file:
                module_to_file[submod] = f

    def try_resolve(target_module: str) -> str | None:
        """Try to resolve a module name to a file path."""
        candidate = target_module
        while candidate:
            if candidate in module_to_file:
                return module_to_file[candidate]
            # Try as .py file
            py_path = candidate.replace(".", "/") + ".py"
            if py_path in file_set:
                return py_path
            # Try as __init__.py
            init_path = candidate.replace(".", "/") + "/__init__.py"
            if init_path in file_set:
                return init_path
            # Try parent prefix
            if "." in candidate:
                candidate = candidate.rsplit(".", 1)[0]
            else:
                break
        return None

    for source_file in py_files:
        full_path = os.path.join(repo_path, source_file)
        try:
            with open(full_path, "r", errors="ignore") as fh:
                tree = ast.parse(fh.read(), filename=source_file)
        except (SyntaxError, ValueError):
            continue

        source_dir = os.path.dirname(source_file)

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                target_module = node.module

                # Handle relative imports
                if node.level and node.level > 0:
                    # Relative import: go up `level` directories from source
                    base_parts = Path(source_dir).parts
                    if node.level <= len(base_parts):
                        base = ".".join(base_parts[: len(base_parts) - node.level + 1])
                        target_module = f"{base}.{target_module}" if target_module else base

                resolved = try_resolve(target_module)
                if resolved and resolved != source_file:
                    edges.append((source_file, resolved))

            elif isinstance(node, ast.Import):
                for alias in node.names:
                    resolved = try_resolve(alias.name)
                    if resolved and resolved != source_file:
                        edges.append((source_file, resolved))

    return [(s, t) for s, t in edges if s != t]


def resolve_typescript_imports(
    repo_path: str, ts_files: list[str],
    path_aliases: list[tuple[str, str, str]] | None = None,
) -> list[tuple[str, str]]:
    """Resolve TypeScript/JavaScript imports using scoped tsconfig paths and extension probing."""
    file_set = set(ts_files)
    edges = []

    if path_aliases is None:
        path_aliases = []

    # Collect all known alias prefixes for the node_modules skip check
    all_alias_prefixes = {prefix for _, prefix, _ in path_aliases}

    # Match all import/export from patterns including multiline destructured imports
    import_re = re.compile(
        r"""(?:import|export)\s+(?:type\s+)?(?:\{[\s\S]*?\}\s+from|[^'";\n]+from)\s+['"]([^'"]+)['"]|"""
        r"""(?:import|export)\s+['"]([^'"]+)['"]|"""
        r"""require\s*\(\s*['"]([^'"]+)['"]\s*\)|"""
        r"""import\s*\(\s*['"]([^'"]+)['"]\s*\)""",
        re.MULTILINE,
    )

    probe_exts = [".ts", ".tsx", ".js", ".jsx", "/index.ts", "/index.tsx", "/index.js", "/index.jsx"]

    for source_file in ts_files:
        full_path = os.path.join(repo_path, source_file)
        try:
            with open(full_path, "r", errors="ignore") as fh:
                content = fh.read(100_000)
        except OSError:
            continue

        source_dir = os.path.dirname(source_file)

        for match in import_re.finditer(content):
            raw = match.group(1) or match.group(2) or match.group(3) or match.group(4)
            if not raw:
                continue

            # Skip node_modules imports
            if not raw.startswith(".") and not any(raw.startswith(p) for p in all_alias_prefixes):
                continue

            # Apply scoped tsconfig path aliases.
            # Pick the alias whose scope_dir is an ancestor of the source file.
            # Longest scope_dir wins (most specific tsconfig).
            resolved_raw = raw
            is_aliased = False
            best_scope_len = -1
            for scope_dir, prefix, replacement in path_aliases:
                if raw.startswith(prefix) and source_file.startswith(scope_dir + "/" if scope_dir else ""):
                    if len(scope_dir) > best_scope_len:
                        best_scope_len = len(scope_dir)
                        resolved_raw = replacement + raw[len(prefix):]
                        is_aliased = True

            # Resolve path
            if is_aliased:
                candidate_base = os.path.normpath(resolved_raw)
            elif resolved_raw.startswith("."):
                candidate_base = os.path.normpath(os.path.join(source_dir, resolved_raw))
            else:
                candidate_base = resolved_raw

            # Probe extensions
            found = None
            if candidate_base in file_set:
                found = candidate_base
            else:
                for ext in probe_exts:
                    probe = candidate_base + ext
                    if probe in file_set:
                        found = probe
                        break

            if found and found != source_file:
                edges.append((source_file, found))

    return edges


def find_tsconfig_paths(repo_path: str, ts_files: list[str]) -> list[tuple[str, str, str]]:
    """
    Find and parse tsconfig.json path aliases, scoped to their tsconfig directory.

    Returns list of (scope_dir, alias_prefix, resolved_target) tuples.
    scope_dir is the directory containing tsconfig.json (repo-root-relative).
    Multiple packages can define the same alias (e.g. @/*) without collision.
    """
    result = []
    seen_tsconfigs = set()

    # Find tsconfig.json files by walking up from TS file directories
    seen_dirs = set()
    for f in ts_files:
        d = os.path.dirname(f)
        while d:
            if d not in seen_dirs:
                seen_dirs.add(d)
                tsconfig_path = os.path.join(repo_path, d, "tsconfig.json")
                if os.path.exists(tsconfig_path) and d not in seen_tsconfigs:
                    seen_tsconfigs.add(d)
                    try:
                        with open(tsconfig_path) as fh:
                            config = json.load(fh)
                        paths = config.get("compilerOptions", {}).get("paths", {})
                        for alias, targets in paths.items():
                            prefix = alias.rstrip("*")
                            if targets:
                                raw_target = targets[0].rstrip("*")
                                resolved = os.path.normpath(os.path.join(d, raw_target))
                                result.append((d, prefix, resolved + "/"))
                    except (json.JSONDecodeError, OSError):
                        pass
            if "/" in d:
                d = d.rsplit("/", 1)[0]
            else:
                break

    # Check root tsconfig
    tsconfig_path = os.path.join(repo_path, "tsconfig.json")
    if os.path.exists(tsconfig_path) and "" not in seen_tsconfigs:
        try:
            with open(tsconfig_path) as fh:
                config = json.load(fh)
            paths = config.get("compilerOptions", {}).get("paths", {})
            for alias, targets in paths.items():
                prefix = alias.rstrip("*")
                if targets:
                    raw_target = targets[0].rstrip("*")
                    result.append(("", prefix, raw_target))
        except (json.JSONDecodeError, OSError):
            pass

    return result


# ─── Layer 2b: Naming convention matching ─────────────────────────────


def _pascal_to_kebab(name: str) -> str:
    result = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", name)
    result = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1-\2", result)
    return result.lower()


def _pascal_to_snake(name: str) -> str:
    result = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    result = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", result)
    return result.lower()


def find_naming_convention_edges(files: list[str]) -> list[tuple[str, str]]:
    """
    Match test/story files to their component by filename transformation.

    Patterns:
      TS/JS:   AgencyReviews.stories.tsx → agency-reviews.tsx (PascalCase→kebab)
               BookingForm.test.tsx      → BookingForm.tsx
      Python:  test_booking.py           → booking.py
               booking_test.py           → booking.py

    Scoped matching: same dir > sibling dir > same package > global (unambiguous only).
    """
    # Build lookup indexes for non-test/non-story files
    dir_files = defaultdict(dict)  # dir → {stem_lower → filepath}
    all_stems = defaultdict(list)  # stem_lower → [filepaths]

    for f in files:
        stem = Path(f).stem
        # Skip test/story files in lookup
        if any(m in stem.lower() for m in [".stories", ".story", ".test", ".spec", "test_", "_test"]):
            continue
        if any(stem.endswith(s) for s in [".stories", ".story", ".test", ".spec"]):
            continue

        parent = os.path.dirname(f)
        stem_lower = stem.lower()
        kebab = _pascal_to_kebab(stem)
        snake = _pascal_to_snake(stem)

        for variant in {stem_lower, kebab, snake}:
            if variant:
                dir_files[parent][variant] = f
                all_stems[variant].append(f)

    edges = []

    for f in files:
        stem = Path(f).stem
        parent = os.path.dirname(f)
        lang = classify_language(f)

        # Detect test/story files and extract target name
        target_name = None
        if lang == "typescript":
            for marker in [".stories", ".story", ".test", ".spec"]:
                if marker in stem:
                    target_name = stem.split(marker)[0]
                    break
        elif lang == "python":
            if stem.startswith("test_"):
                target_name = stem[5:]
            elif stem.endswith("_test"):
                target_name = stem[:-5]

        if not target_name:
            continue

        variants = {target_name.lower(), _pascal_to_kebab(target_name), _pascal_to_snake(target_name)}
        candidates = set()

        # 1. Same directory
        local = dir_files.get(parent, {})
        for v in variants:
            if v in local:
                candidates.add(local[v])

        # 2. Sibling directories
        if not candidates:
            parent_of_parent = os.path.dirname(parent)
            if parent_of_parent:
                for sib_dir, sib_files in dir_files.items():
                    if sib_dir.startswith(parent_of_parent) and sib_dir != parent:
                        for v in variants:
                            if v in sib_files:
                                candidates.add(sib_files[v])

        # 3. Same top-level package
        if not candidates:
            pkg = f.split("/")[0] if "/" in f else None
            if pkg:
                for v in variants:
                    for c in all_stems.get(v, []):
                        if c.startswith(pkg + "/") and c != f:
                            candidates.add(c)

        # 4. Global (only if unambiguous)
        if not candidates:
            for v in variants:
                matches = [c for c in all_stems.get(v, []) if c != f]
                if len(matches) == 1:
                    candidates.add(matches[0])
                break  # don't try other variants if first found ambiguous

        for comp in candidates:
            if comp != f:
                edges.append((f, comp))

    return edges


# ─── Layer 3: Cross-language bridges ──────────────────────────────────

def find_graphql_bridges(repo_path: str, py_files: list[str], ts_files: list[str]) -> list[tuple[str, str]]:
    """
    Match GraphQL operations across Python (Strawberry) and TypeScript (Apollo/gql).

    Python side: @strawberry.mutation / @strawberry.field decorated functions
    TypeScript side: gql`mutation X` / gql`query X` operation names
    Bridge: snake_case function name → PascalCase operation name
    """
    # Extract Python GraphQL operations
    py_operations = {}  # operation_name_pascal → [file_paths]
    strawberry_re = re.compile(r"@strawberry\.(mutation|field|type|input)")

    for f in py_files:
        full_path = os.path.join(repo_path, f)
        try:
            with open(full_path, "r", errors="ignore") as fh:
                content = fh.read()
        except OSError:
            continue

        if "strawberry" not in content:
            continue

        try:
            tree = ast.parse(content, filename=f)
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Check for strawberry decorators
                for dec in node.decorator_list:
                    dec_str = ast.dump(dec)
                    if "strawberry" in dec_str and any(
                        kw in dec_str for kw in ["mutation", "field"]
                    ):
                        # Convert snake_case to PascalCase
                        pascal = "".join(
                            part.capitalize() for part in node.name.split("_")
                        )
                        if pascal not in py_operations:
                            py_operations[pascal] = []
                        py_operations[pascal].append(f)
                        break

    if not py_operations:
        return []

    # Extract TypeScript GraphQL operation usage
    ts_operations = {}  # operation_name → [file_paths]
    gql_op_re = re.compile(
        r"""(?:mutation|query|subscription)\s+([A-Z]\w+)""", re.MULTILINE
    )

    for f in ts_files:
        full_path = os.path.join(repo_path, f)
        try:
            with open(full_path, "r", errors="ignore") as fh:
                content = fh.read()
        except OSError:
            continue

        if "mutation" not in content and "query" not in content:
            continue

        for match in gql_op_re.finditer(content):
            op_name = match.group(1)
            if op_name not in ts_operations:
                ts_operations[op_name] = []
            ts_operations[op_name].append(f)

    # Match operations
    edges = []
    matched = 0
    for op_name, py_paths in py_operations.items():
        if op_name in ts_operations:
            matched += 1
            for py_path in py_paths:
                for ts_path in ts_operations[op_name]:
                    edges.append((py_path, ts_path))

    return edges


def find_rest_bridges(repo_path: str, py_files: list[str], ts_files: list[str]) -> list[tuple[str, str]]:
    """
    Match REST API routes: Python @app.route/FastAPI decorators → TypeScript fetch/axios calls.
    """
    # Extract Python routes
    py_routes = {}  # route_path → [file_paths]
    route_re = re.compile(
        r"""@(?:app|router)\.(get|post|put|delete|patch)\s*\(\s*['"]([^'"]+)['"]""",
        re.MULTILINE,
    )

    for f in py_files:
        full_path = os.path.join(repo_path, f)
        try:
            with open(full_path, "r", errors="ignore") as fh:
                content = fh.read()
        except OSError:
            continue

        for match in route_re.finditer(content):
            route = match.group(2)
            # Normalize: strip param placeholders
            normalized = re.sub(r"\{[^}]+\}", "*", route)
            if normalized not in py_routes:
                py_routes[normalized] = []
            py_routes[normalized].append(f)

    if not py_routes:
        return []

    # Extract TypeScript API calls
    ts_calls = {}  # route_path → [file_paths]
    fetch_re = re.compile(
        r"""(?:fetch|axios\.(?:get|post|put|delete|patch)|api\.(?:get|post|put|delete|patch))\s*\(\s*[`'"]([^`'"]+)[`'"]""",
        re.MULTILINE,
    )

    for f in ts_files:
        full_path = os.path.join(repo_path, f)
        try:
            with open(full_path, "r", errors="ignore") as fh:
                content = fh.read()
        except OSError:
            continue

        for match in fetch_re.finditer(content):
            url = match.group(1)
            # Extract path from URL
            path = re.sub(r"https?://[^/]+", "", url)
            path = re.sub(r"\$\{[^}]+\}", "*", path)
            if path not in ts_calls:
                ts_calls[path] = []
            ts_calls[path].append(f)

    # Match routes
    edges = []
    for route, py_paths in py_routes.items():
        if route in ts_calls:
            for py_path in py_paths:
                for ts_path in ts_calls[route]:
                    edges.append((py_path, ts_path))
        # Also try matching with trailing slash variants
        alt = route.rstrip("/") if route.endswith("/") else route + "/"
        if alt in ts_calls:
            for py_path in py_paths:
                for ts_path in ts_calls[alt]:
                    edges.append((py_path, ts_path))

    return edges


# ─── Layer 4: Package-level grouping ──────────────────────────────────

def detect_packages(repo_path: str, files: list[str]) -> dict[str, str]:
    """
    Detect monorepo packages. Files in the same package share a deployment unit.
    Returns mapping: file_path → package_name
    """
    # Find package boundaries: directories containing package.json or requirements.txt
    # or setup.py or pyproject.toml
    package_markers = {}
    for f in files:
        d = os.path.dirname(f)
        while d:
            if d not in package_markers:
                for marker in ["package.json", "requirements.txt", "setup.py", "pyproject.toml"]:
                    if os.path.exists(os.path.join(repo_path, d, marker)):
                        package_markers[d] = d
                        break
            if "/" in d:
                d = d.rsplit("/", 1)[0]
            else:
                break

    # Assign each file to its nearest package
    file_to_package = {}
    for f in files:
        d = os.path.dirname(f)
        best_pkg = None
        best_depth = -1
        while d:
            if d in package_markers:
                depth = d.count("/")
                if depth > best_depth:
                    best_pkg = d
                    best_depth = depth
            if "/" in d:
                d = d.rsplit("/", 1)[0]
            else:
                break
            if d in package_markers:
                depth = d.count("/")
                if depth > best_depth:
                    best_pkg = d
                    best_depth = depth

        if best_pkg:
            file_to_package[f] = best_pkg
        else:
            # Root-level files get "root" package
            top = f.split("/")[0] if "/" in f else "root"
            file_to_package[f] = top

    return file_to_package


def build_package_edges(files: list[str], file_to_package: dict[str, str]) -> list[tuple[str, str, float]]:
    """
    Same-package edges, but ONLY for files in the same immediate directory
    within a package. Pairwise edges across an entire 593-file package
    (O(n²) = 175K edges) would drown out all structural signals.

    Instead: files sharing a directory within a package get a weak edge.
    This provides a floor for otherwise-unconnected neighbors without
    flooding the graph.
    """
    # Group by (package, immediate directory)
    dir_groups = defaultdict(list)
    for f in files:
        pkg = file_to_package.get(f, "root")
        parent_dir = os.path.dirname(f)
        dir_groups[(pkg, parent_dir)].append(f)

    edges = []
    for (pkg, d), group_files in dir_groups.items():
        if len(group_files) < 2 or len(group_files) > 50:
            continue
        weight = 0.3 / math.log2(max(len(group_files), 2))
        for i, f1 in enumerate(group_files):
            for f2 in group_files[i + 1:]:
                edges.append((f1, f2, weight))

    return edges


# ─── Layer 5: TF-IDF Semantic Labeling ────────────────────────────────

IDENT_PATTERN = re.compile(r"\b[a-zA-Z_][a-zA-Z0-9_]{2,}\b")
STOP_IDENTS = {
    # Language keywords
    "self", "this", "true", "false", "none", "null", "undefined",
    "return", "import", "from", "class", "def", "function", "const",
    "let", "var", "async", "await", "yield", "export", "default",
    "interface", "type", "enum", "struct", "impl", "pub", "private",
    "protected", "public", "static", "final", "override", "abstract",
    "extends", "implements", "throws", "try", "catch", "finally",
    "raise", "except", "pass", "break", "continue", "for", "while",
    "with", "elif", "else", "end", "begin", "module", "require",
    "include", "use", "print", "println", "console", "log",
    # Primitive types
    "string", "int", "float", "bool", "boolean", "void", "any",
    "object", "array", "list", "dict", "map", "set", "tuple",
    # Test frameworks
    "test", "describe", "expect", "should", "assert",
    "mock", "jest", "spec", "story", "stories", "args", "meta",
    # React / JSX / DOM
    "react", "div", "span", "props", "children", "component",
    "render", "ref", "state", "use", "hook", "memo", "callback",
    "effect", "context", "portal", "fragment", "suspense",
    "class", "name", "class_name", "classname",
    "on_click", "onclick", "on_change", "onchange",
    "key", "index", "length", "typeof",
    # CSS / styling tokens
    "flex", "grid", "gap", "center", "justify", "items", "align",
    "border", "rounded", "font", "text", "opacity", "background",
    "foreground", "muted", "primary", "secondary", "variant",
    "size", "width", "height", "left", "right", "top", "bottom",
    "space", "auto", "full", "max", "min", "medium", "small", "large",
    "padding", "margin", "overflow", "hidden", "block", "inline",
    "absolute", "relative", "fixed", "sticky",
    "color", "white", "black", "gray", "grey", "dark", "light",
    "shadow", "ring", "outline", "stroke", "fill",
    # UI component library tokens (shadcn, radix, lucide)
    "lucide", "radix", "shadcn", "trigger", "content",
    "separator", "scroll", "popover", "tooltip", "dialog",
    "card", "button", "input", "label", "select", "slider",
    "checkbox", "switch", "toggle", "badge", "avatar",
    "accordion", "collapsible", "menubar", "navigation",
    "pagination", "progress", "skeleton", "spinner", "toast",
    "tabs", "table", "header", "footer", "sidebar",
    "carousel", "drawer", "hover", "aspect", "ratio",
    "resizable", "panel", "alert", "breadcrumb",
    # Generic programming
    "data", "value", "error", "result", "response", "request",
    "get", "set", "add", "remove", "delete", "update", "create",
    "new", "old", "start", "stop", "init", "setup", "config",
    "handle", "handler", "event", "action", "dispatch",
    "load", "loading", "fetch", "send", "receive",
    "check", "validate", "parse", "format", "convert",
    "find", "search", "filter", "sort", "group", "merge",
    "open", "close", "show", "hide", "enable", "disable",
    "number", "count", "total", "item", "entry", "record",
    "info", "warning", "debug", "trace", "level",
    "url", "path", "file", "dir", "base", "root",
    "client", "server", "app", "lib", "src", "utils", "helper",
    "status", "code", "flag", "option", "param", "arg",
    "first", "last", "next", "prev", "current",
    "found", "failed", "success", "done", "ready", "pending",
    "view", "page", "route", "link", "icon", "image", "img",
    # Storybook / test mocking
    "mocked", "mock_data", "fixture", "stub",
    "storybook", "vitest", "playwright", "cypress",
    # CSS modules / styling files
    "styles", "style", "styled", "css", "scss", "module",
    # JSX / templating
    "jsx", "tsx", "html", "xml",
    # Layout / structure
    "row", "col", "column", "container", "wrapper", "layout",
    "section", "main", "aside", "nav",
    # Python builtins that leak through
    "str", "len", "range", "iter", "repr", "isinstance",
    # Motion / animation libraries
    "motion", "animate", "transition", "duration", "ease",
    # Theming / design tokens
    "themed", "theme", "colors", "primitive",
    # Testing / browser automation
    "wait", "networkidle", "selector", "locator",
    # JS/TS utility patterns
    "define", "property", "prototype", "constructor",
    "promise", "resolve", "reject", "callback",
    # English stop words that leak through identifier extraction
    "and", "the", "not", "all", "has", "only", "can", "will",
    "from", "with", "that", "than", "then", "when", "where",
}


def extract_identifiers(filepath: str) -> str:
    try:
        with open(filepath, "r", errors="ignore") as f:
            content = f.read(50_000)
    except (OSError, UnicodeDecodeError):
        return ""
    idents = IDENT_PATTERN.findall(content)
    expanded = []
    for ident in idents:
        lower = ident.lower()
        if lower in STOP_IDENTS:
            continue
        parts = re.sub(r"([a-z])([A-Z])", r"\1 \2", ident)
        parts = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", parts)
        for p in parts.split():
            if len(p) > 2 and p.lower() not in STOP_IDENTS:
                expanded.append(p.lower())
    return " ".join(expanded)


def build_semantic_edges(
    repo_path: str,
    files: list[str],
    orphan_files: set[str],
    file_to_package: dict[str, str],
    threshold: float = 0.4,
) -> tuple[list[tuple[str, str, float]], dict[str, list[str]]]:
    """
    TF-IDF identifier similarity. Two outputs:
    1. Edges for orphan files (ONLY within the same package — cross-package
       semantic similarity in a monorepo just says "same domain vocabulary",
       which is true but useless for clustering)
    2. Domain term vectors for cluster labeling
    """
    docs = []
    valid_files = []
    for f in files:
        idents = extract_identifiers(os.path.join(repo_path, f))
        if idents.strip():
            docs.append(idents)
            valid_files.append(f)

    if len(docs) < 2:
        return [], {}

    vectorizer = TfidfVectorizer(max_features=5000, min_df=2, max_df=0.8)
    try:
        tfidf_matrix = vectorizer.fit_transform(docs)
    except ValueError:
        return [], {}

    feature_names = vectorizer.get_feature_names_out()

    # Extract top terms per file for labeling
    file_terms = {}
    for i, f in enumerate(valid_files):
        row = tfidf_matrix[i].toarray()[0]
        top_indices = row.argsort()[-10:][::-1]
        file_terms[f] = [feature_names[j] for j in top_indices if row[j] > 0]

    # Create edges only for orphan files, within the same package
    edges = []
    if orphan_files:
        orphan_indices = [i for i, f in enumerate(valid_files) if f in orphan_files]
        for idx in orphan_indices:
            orphan_pkg = file_to_package.get(valid_files[idx], "root")
            sims = cosine_similarity(tfidf_matrix[idx : idx + 1], tfidf_matrix)[0]
            for j in range(len(valid_files)):
                if j != idx and sims[j] >= threshold:
                    target_pkg = file_to_package.get(valid_files[j], "root")
                    if target_pkg == orphan_pkg:
                        edges.append((valid_files[idx], valid_files[j], sims[j]))

    return edges, file_terms


# ─── Layer 6: Co-change with IDF weighting ────────────────────────────

def build_cochange_graph_idf(
    repo_path: str,
    files: list[str],
    max_commits: int = 5000,
    max_commit_size: int = 50,
    min_shared: int = 2,
) -> nx.Graph:
    """
    Co-change graph with IDF weighting.

    The key insight: files like mutations.ts that appear in 200+ commits are hubs.
    Without dampening, they create mega-clusters that swallow everything.

    IDF = log(total_commits / commits_containing_file)
    Edge weight = co_count * idf(f1) * idf(f2) * confidence

    Hub files get low IDF → their edges are dampened.
    Rare-but-coupled files get high IDF → their edges are amplified.
    """
    G = nx.Graph()
    file_set = set(files)
    G.add_nodes_from(files)

    try:
        result = subprocess.run(
            ["git", "log", f"--max-count={max_commits}",
             "--pretty=format:--COMMIT--", "--name-only"],
            cwd=repo_path, capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            return G
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return G

    # Parse commits
    commits = []
    current_files = []
    for line in result.stdout.split("\n"):
        line = line.strip()
        if line == "--COMMIT--":
            if current_files:
                commits.append(current_files)
            current_files = []
        elif line and line in file_set:
            current_files.append(line)
    if current_files:
        commits.append(current_files)

    total_commits = len(commits)
    if total_commits == 0:
        return G

    # Count commits per file (for IDF)
    file_commit_count = Counter()
    pair_counts = Counter()
    for commit_files in commits:
        if len(commit_files) > max_commit_size or len(commit_files) < 2:
            continue
        for f in commit_files:
            file_commit_count[f] += 1
        for i, f1 in enumerate(commit_files):
            for f2 in commit_files[i + 1:]:
                pair = tuple(sorted([f1, f2]))
                pair_counts[pair] += 1

    # Compute IDF per file
    file_idf = {}
    for f in files:
        doc_freq = file_commit_count.get(f, 0)
        if doc_freq == 0:
            file_idf[f] = 0.0
        else:
            file_idf[f] = math.log(total_commits / doc_freq)

    # Add edges with IDF weighting
    for (f1, f2), count in pair_counts.items():
        if count < min_shared:
            continue
        conf1 = count / max(file_commit_count[f1], 1)
        conf2 = count / max(file_commit_count[f2], 1)

        # IDF-weighted: dampen hub files, amplify rare couplings
        idf_weight = file_idf[f1] * file_idf[f2]
        weight = count * ((conf1 + conf2) / 2) * idf_weight

        if weight > 0:
            G.add_edge(f1, f2, weight=weight)

    return G


# ─── Clustering ───────────────────────────────────────────────────────

def leiden_cluster(G: nx.Graph, resolution: float = 0.05) -> dict[str, int]:
    if G.number_of_edges() == 0:
        return {n: i for i, n in enumerate(G.nodes())}

    nodes = list(G.nodes())
    node_to_idx = {n: i for i, n in enumerate(nodes)}
    ig_graph = ig.Graph(n=len(nodes), directed=False)

    edges = []
    weights = []
    for u, v, data in G.edges(data=True):
        edges.append((node_to_idx[u], node_to_idx[v]))
        weights.append(data.get("weight", 1.0))
    ig_graph.add_edges(edges)

    partition = la.find_partition(
        ig_graph, la.CPMVertexPartition,
        resolution_parameter=resolution,
        weights=weights, seed=42,
    )

    result = {}
    for cluster_id, members in enumerate(partition):
        for idx in members:
            result[nodes[idx]] = cluster_id
    return result


# ─── Labeling ─────────────────────────────────────────────────────────

def label_cluster(
    cluster_files: list[str],
    file_terms: dict[str, list[str]],
    used_labels: set[str],
) -> str:
    """Label cluster using TF-IDF domain terms + path segments."""
    if len(cluster_files) == 1:
        return Path(cluster_files[0]).stem

    term_scores = Counter()

    # Source 1: TF-IDF terms from file content
    for f in cluster_files:
        terms = file_terms.get(f, [])
        for i, t in enumerate(terms):
            # Weight by rank (top terms score higher)
            term_scores[t] += (10 - i) if i < 10 else 1

    # Source 2: path segments (for specificity)
    generic = {
        "src", "lib", "app", "main", "core", "utils", "helpers", "common",
        "shared", "internal", "pkg", "packages", "modules", "vendor",
        "__init__", "index", "__tests__", "test", "tests", "stories", "specs",
    }
    for f in cluster_files:
        parts = Path(f).parts
        for i, p in enumerate(parts):
            name = p.lower()
            for ext in [".py", ".ts", ".tsx", ".js", ".jsx"]:
                name = name.replace(ext, "")
            if name in generic or len(name) <= 2:
                continue
            tokens = re.split(r"[-_.]", name)
            for t in tokens:
                if len(t) > 2 and t not in generic:
                    term_scores[t] += 3  # Path terms are strong signals

    if not term_scores:
        return f"cluster_{len(used_labels)}"

    for term, _ in term_scores.most_common(20):
        if term not in used_labels:
            remaining = [
                (t, s) for t, s in term_scores.most_common(20)
                if t != term and t not in used_labels
            ]
            if remaining:
                combo = f"{term}/{remaining[0][0]}"
                if combo not in used_labels:
                    return combo
            return term

    return f"cluster_{len(used_labels)}"


# ─── Quality metrics ─────────────────────────────────────────────────

def compute_mq(G: nx.Graph, clusters: dict[str, int]) -> float:
    """
    Modularization Quality (Bunch MQ metric).
    MQ = avg(intra-cluster density) - avg(inter-cluster density)
    Higher is better.
    """
    cluster_to_files = defaultdict(set)
    for f, cid in clusters.items():
        cluster_to_files[cid].add(f)

    if len(cluster_to_files) <= 1:
        return 0.0

    intra_densities = []
    inter_edges = 0
    inter_possible = 0

    for cid, members in cluster_to_files.items():
        if len(members) < 2:
            continue
        intra_edges = sum(
            1 for u, v in G.edges() if u in members and v in members
        )
        possible = len(members) * (len(members) - 1) / 2
        intra_densities.append(intra_edges / possible if possible > 0 else 0)

    # Inter-cluster
    for u, v in G.edges():
        cu, cv = clusters.get(u), clusters.get(v)
        if cu is not None and cv is not None and cu != cv:
            inter_edges += 1

    all_files = set(clusters.keys())
    total_possible = len(all_files) * (len(all_files) - 1) / 2
    inter_density = inter_edges / total_possible if total_possible > 0 else 0

    avg_intra = sum(intra_densities) / len(intra_densities) if intra_densities else 0
    return avg_intra - inter_density


# ─── Main analysis ────────────────────────────────────────────────────

def analyze_codebase(repo_path: str, name: str):
    print(f"\n{'=' * 70}")
    print(f"  6-LAYER DOMAIN CLUSTERING: {name}")
    print(f"{'=' * 70}\n")

    files = get_code_files(repo_path)
    py_files = [f for f in files if classify_language(f) == "python"]
    ts_files = [f for f in files if classify_language(f) == "typescript"]
    other_files = [f for f in files if classify_language(f) not in ("python", "typescript")]

    print(f"Total files: {len(files)}")
    print(f"  Python: {len(py_files)}")
    print(f"  TypeScript/JS: {len(ts_files)}")
    print(f"  Other: {len(other_files)}")

    # Initialize the combined graph
    combined = nx.Graph()
    combined.add_nodes_from(files)

    layer_stats = {}

    # ── Layer 1: File inventory (already done by get_code_files) ──
    print(f"\n{'─' * 50}")
    print("Layer 1: File Inventory")
    print(f"  {len(files)} files across {len(set(f.split('/')[0] for f in files if '/' in f))} top-level directories")

    # ── Layer 2a: Compiler-native dependency resolution ──
    print(f"\n{'─' * 50}")
    print("Layer 2a: Compiler-Native Dependencies")

    py_edges = resolve_python_imports(repo_path, py_files)
    print(f"  Python (ast.parse): {len(py_edges)} edges from {len(py_files)} files")

    tsconfig_paths = find_tsconfig_paths(repo_path, ts_files)
    if tsconfig_paths:
        scopes = defaultdict(list)
        for scope, prefix, target in tsconfig_paths:
            scopes[scope or "(root)"].append(f"{prefix}* → {target}*")
        for scope, aliases in sorted(scopes.items()):
            print(f"  tsconfig [{scope}]: {', '.join(aliases)}")
    ts_edges = resolve_typescript_imports(repo_path, ts_files, tsconfig_paths)
    print(f"  TypeScript (tsconfig): {len(ts_edges)} edges from {len(ts_files)} files")

    # Deduplicate
    py_unique = set(tuple(sorted(e)) for e in py_edges)
    ts_unique = set(tuple(sorted(e)) for e in ts_edges)
    total_l2 = len(py_unique) + len(ts_unique)
    print(f"  Total unique: {total_l2}")

    # Convert direct imports to CO-IMPORT similarity.
    # Files that import the same targets are likely in the same domain.
    # Direct A→B import edges just mean A depends on B, which is weaker.
    import_targets = defaultdict(set)  # file → set of files it imports
    for source, target in py_unique | ts_unique:
        import_targets[source].add(target)

    # Co-import: for each pair of files, count shared import targets
    co_import_edges = 0
    files_with_imports = [f for f in files if f in import_targets]
    for i, f1 in enumerate(files_with_imports):
        t1 = import_targets[f1]
        for f2 in files_with_imports[i + 1:]:
            t2 = import_targets[f2]
            shared = len(t1 & t2)
            if shared >= 2:  # At least 2 shared imports
                # Jaccard-like weight: shared / union
                union = len(t1 | t2)
                weight = shared / union * 3.0  # Scale up for significance
                combined.add_edge(f1, f2, weight=weight)
                co_import_edges += 1

    # Also keep direct import edges but with lower weight (1.0)
    for u, v in py_unique | ts_unique:
        if combined.has_edge(u, v):
            combined[u][v]["weight"] += 1.0
        else:
            combined.add_edge(u, v, weight=1.0)

    layer_stats["L2a_edges"] = total_l2
    print(f"  Co-import edges (shared deps >= 2): {co_import_edges}")
    l2a_connected = sum(1 for n in files if combined.degree(n) > 0)
    print(f"  Connected: {l2a_connected}/{len(files)} ({l2a_connected * 100 // len(files)}%)")

    # ── Layer 2b: Naming convention matching ──
    print(f"\n{'─' * 50}")
    print("Layer 2b: Naming Convention Matching")

    nc_edges = find_naming_convention_edges(files)
    nc_pairs = set(tuple(sorted(e)) for e in nc_edges)
    existing_pairs = set()
    for u, v in nc_pairs:
        if combined.has_edge(u, v):
            existing_pairs.add((u, v))

    novel_nc = 0
    reinforced_nc = 0
    for u, v in nc_pairs:
        if combined.has_edge(u, v):
            combined[u][v]["weight"] += 3.0
            reinforced_nc += 1
        else:
            combined.add_edge(u, v, weight=3.0)
            novel_nc += 1

    print(f"  Matched pairs: {len(nc_pairs)}")
    print(f"  Novel edges (not in import graph): {novel_nc}")
    print(f"  Reinforced existing edges: {reinforced_nc}")
    layer_stats["L2b_edges"] = novel_nc
    l2b_connected = sum(1 for n in files if combined.degree(n) > 0)
    print(f"  Connected: {l2b_connected}/{len(files)} ({l2b_connected * 100 // len(files)}%)")

    # ── Layer 3: Cross-language bridges ──
    print(f"\n{'─' * 50}")
    print("Layer 3: Cross-Language Bridges")

    gql_edges = find_graphql_bridges(repo_path, py_files, ts_files)
    gql_unique = set(tuple(sorted(e)) for e in gql_edges)
    print(f"  GraphQL bridges: {len(gql_unique)} edges")

    rest_edges = find_rest_bridges(repo_path, py_files, ts_files)
    rest_unique = set(tuple(sorted(e)) for e in rest_edges)
    print(f"  REST bridges: {len(rest_unique)} edges")

    total_l3 = len(gql_unique) + len(rest_unique)
    print(f"  Total cross-language: {total_l3}")

    # Cross-language edges are extremely valuable — weight = 3.0
    for u, v in gql_unique | rest_unique:
        if combined.has_edge(u, v):
            combined[u][v]["weight"] += 3.0
        else:
            combined.add_edge(u, v, weight=3.0)

    layer_stats["L3_edges"] = total_l3

    # ── Layer 4: Package detection (metadata only, no edges) ──
    print(f"\n{'─' * 50}")
    print("Layer 4: Package Detection (metadata for labeling)")

    file_to_package = detect_packages(repo_path, files)
    packages = defaultdict(list)
    for f, pkg in file_to_package.items():
        packages[pkg].append(f)

    print(f"  Detected packages: {len(packages)}")
    for pkg, pkg_files in sorted(packages.items(), key=lambda x: -len(x[1])):
        print(f"    {pkg}: {len(pkg_files)} files")
    print("  (No edges added — package membership used for labeling only)")

    layer_stats["L4_packages"] = len(packages)

    # ── Layer 6 (before 5, because 5 needs to know orphans): Co-change ──
    print(f"\n{'─' * 50}")
    print("Layer 6: Co-Change with IDF Weighting")

    cc_graph = build_cochange_graph_idf(repo_path, files)
    cc_edges = cc_graph.number_of_edges()
    print(f"  IDF-weighted edges: {cc_edges}")

    # Show hub dampening effect
    if cc_edges > 0:
        edge_weights = [d["weight"] for _, _, d in cc_graph.edges(data=True)]
        print(f"  Weight range: {min(edge_weights):.2f} — {max(edge_weights):.2f}")
        print(f"  Median weight: {sorted(edge_weights)[len(edge_weights)//2]:.2f}")

        # Show top hubs and their dampened degree
        hub_degree = sorted(
            [(n, cc_graph.degree(n)) for n in cc_graph.nodes() if cc_graph.degree(n) > 0],
            key=lambda x: -x[1],
        )[:5]
        print("  Top hubs (after IDF dampening):")
        for node, deg in hub_degree:
            print(f"    {node}: {deg} edges")

    # Degree-cap hub files: keep only top-k edges by weight per node
    MAX_DEGREE = 25
    cc_capped = nx.Graph()
    cc_capped.add_nodes_from(cc_graph.nodes())
    for node in cc_graph.nodes():
        neighbors = list(cc_graph[node].items())
        if len(neighbors) <= MAX_DEGREE:
            for nbr, data in neighbors:
                if not cc_capped.has_edge(node, nbr):
                    cc_capped.add_edge(node, nbr, weight=data["weight"])
        else:
            # Keep only top-k by weight
            top_k = sorted(neighbors, key=lambda x: x[1]["weight"], reverse=True)[:MAX_DEGREE]
            for nbr, data in top_k:
                if not cc_capped.has_edge(node, nbr):
                    cc_capped.add_edge(node, nbr, weight=data["weight"])

    capped_edges = cc_capped.number_of_edges()
    print(f"  After degree cap (max {MAX_DEGREE}): {capped_edges} edges ({cc_edges - capped_edges} removed)")

    # Add capped co-change to combined
    for u, v, data in cc_capped.edges(data=True):
        if combined.has_edge(u, v):
            combined[u][v]["weight"] += data["weight"]
        else:
            combined.add_edge(u, v, weight=data["weight"])

    layer_stats["L6_edges"] = cc_edges

    # ── Layer 5: Semantic labeling + orphan edges ──
    print(f"\n{'─' * 50}")
    print("Layer 5: TF-IDF Semantic Labeling")

    orphans = {n for n in files if combined.degree(n) == 0}
    print(f"  Orphan files (no edges from L2-L6): {len(orphans)}")

    sem_edges, file_terms = build_semantic_edges(repo_path, files, orphans, file_to_package, threshold=0.4)
    print(f"  Semantic edges for orphans: {len(sem_edges)}")
    print(f"  Files with term vectors: {len(file_terms)}")

    for u, v, w in sem_edges:
        if combined.has_edge(u, v):
            combined[u][v]["weight"] += w * 0.5
        else:
            combined.add_edge(u, v, weight=w * 0.5)

    layer_stats["L5_edges"] = len(sem_edges)

    # ── Global degree cap on combined graph ──
    # Even after per-layer capping, some nodes accumulate too many edges
    # across layers. Cap the combined degree to prevent super-connectors.
    GLOBAL_MAX_DEGREE = 50
    nodes_capped = 0
    edges_before_cap = combined.number_of_edges()
    for node in list(combined.nodes()):
        neighbors = list(combined[node].items())
        if len(neighbors) > GLOBAL_MAX_DEGREE:
            nodes_capped += 1
            # Keep top-k by weight, remove the rest
            sorted_nbrs = sorted(neighbors, key=lambda x: x[1]["weight"], reverse=True)
            for nbr, _ in sorted_nbrs[GLOBAL_MAX_DEGREE:]:
                combined.remove_edge(node, nbr)
    edges_after_cap = combined.number_of_edges()
    if nodes_capped > 0:
        print(f"\n  Global degree cap (max {GLOBAL_MAX_DEGREE}): {nodes_capped} nodes capped, {edges_before_cap - edges_after_cap} edges removed")

    # ── Final graph stats ──
    print(f"\n{'─' * 50}")
    print("Combined Graph")
    total_edges = combined.number_of_edges()
    connected = sum(1 for n in files if combined.degree(n) > 0)
    final_orphans = sum(1 for n in files if combined.degree(n) == 0)
    print(f"  Total edges: {total_edges}")
    print(f"  Connected files: {connected}/{len(files)} ({connected * 100 // len(files)}%)")
    print(f"  Remaining orphans: {final_orphans}")

    print(f"\n  Edge contribution by layer:")
    for layer, count in sorted(layer_stats.items()):
        pct = count * 100 // max(total_edges, 1)
        bar = "█" * (pct // 2) + "░" * (50 - pct // 2)
        print(f"    {layer}: {count:>6} ({pct:>3}%) {bar}")

    # ── Clustering ──
    print(f"\n{'─' * 50}")
    print("Clustering (Leiden + CPM)")

    target = max(5, int(len(files) ** 0.5))
    best_clusters = None
    best_diff = float("inf")
    best_res = None
    best_mq = -999

    for res in [0.005, 0.01, 0.02, 0.03, 0.05, 0.08, 0.1, 0.15, 0.2, 0.3, 0.5]:
        clusters = leiden_cluster(combined, resolution=res)
        n_clusters = len(set(clusters.values()))
        mq = compute_mq(combined, clusters)
        diff = abs(n_clusters - target)

        # Prefer resolution that gives good MQ near target cluster count
        if diff < best_diff or (diff <= best_diff + 3 and mq > best_mq):
            best_diff = diff
            best_clusters = clusters
            best_res = res
            best_mq = mq

    print(f"  Target: ~{target} clusters")
    print(f"  Best resolution: {best_res}")
    print(f"  MQ (Modularization Quality): {best_mq:.4f}")

    # Build cluster objects
    cluster_to_files = defaultdict(list)
    for f, cid in best_clusters.items():
        cluster_to_files[cid].append(f)

    # Recursive splitting: keep splitting until no cluster exceeds max_size
    max_cluster_size = max(40, int(len(files) * 0.08))  # 8% of codebase or 40
    next_id = max(cluster_to_files.keys()) + 1
    total_splits = 0
    max_iterations = 5

    for iteration in range(max_iterations):
        oversized = [cid for cid, cfiles in cluster_to_files.items() if len(cfiles) > max_cluster_size]
        if not oversized:
            break
        for cid in oversized:
            cfiles = cluster_to_files[cid]
            subgraph = combined.subgraph(cfiles).copy()
            if subgraph.number_of_edges() == 0:
                continue
            sub_target = max(3, int(len(cfiles) ** 0.5))
            sub_best = None
            sub_best_diff = float("inf")
            for sub_res in [0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0]:
                sub_clusters = leiden_cluster(subgraph, resolution=sub_res)
                n = len(set(sub_clusters.values()))
                if n > 1:
                    diff = abs(n - sub_target)
                    if sub_best is None or diff < sub_best_diff:
                        sub_best = sub_clusters
                        sub_best_diff = diff
                        if n >= sub_target:
                            break
            if sub_best and len(set(sub_best.values())) > 1:
                del cluster_to_files[cid]
                sub_groups = defaultdict(list)
                for f, sub_cid in sub_best.items():
                    sub_groups[sub_cid].append(f)
                for sub_cid, sub_files in sub_groups.items():
                    cluster_to_files[next_id] = sub_files
                    next_id += 1
                total_splits += 1

    if total_splits > 0:
        print(f"  Recursive splits: {total_splits} mega-clusters split across {iteration + 1} rounds (max_size={max_cluster_size})")

    # ── Post-clustering adoption ──
    # Singletons with all neighbors in the same multi-file cluster get adopted.
    # Safety: only adopt if the singleton's neighbors unanimously agree on one cluster.
    file_to_cluster = {}
    for cid, cfiles in cluster_to_files.items():
        for f in cfiles:
            file_to_cluster[f] = cid

    adopted = 0
    for cid in list(cluster_to_files.keys()):
        cfiles = cluster_to_files[cid]
        if len(cfiles) != 1:
            continue
        f = cfiles[0]
        if combined.degree(f) == 0:
            continue

        # Find which clusters this singleton's neighbors belong to
        nbr_clusters = Counter()
        for nbr in combined[f]:
            nbr_cid = file_to_cluster.get(nbr)
            if nbr_cid is not None and len(cluster_to_files.get(nbr_cid, [])) > 1:
                nbr_clusters[nbr_cid] += 1

        if not nbr_clusters:
            continue

        # Adopt if all neighbor edges point to the same cluster,
        # or if the dominant cluster has a clear majority (>= 2/3 of edges)
        best_cid, best_count = nbr_clusters.most_common(1)[0]
        total_nbr_edges = sum(nbr_clusters.values())
        if len(nbr_clusters) == 1 or best_count >= total_nbr_edges * 2 / 3:
            del cluster_to_files[cid]
            cluster_to_files[best_cid].append(f)
            file_to_cluster[f] = best_cid
            adopted += 1

    if adopted > 0:
        print(f"  Post-clustering adoption: {adopted} singletons joined neighbor clusters")

    # ── Directory-based rescue ──
    # Remaining singletons: if all/most files in the same directory belong to one cluster,
    # assign the singleton there. Directory proximity is weaker than graph edges,
    # so this runs last and only rescues files that no other layer could connect.
    dir_rescued = 0
    for cid in list(cluster_to_files.keys()):
        cfiles = cluster_to_files[cid]
        if len(cfiles) != 1:
            continue
        f = cfiles[0]
        parent = os.path.dirname(f)
        if not parent:
            continue

        # Find clusters of other files in the same directory
        dir_clusters = Counter()
        for other_f in files:
            if other_f == f or os.path.dirname(other_f) != parent:
                continue
            other_cid = file_to_cluster.get(other_f)
            if other_cid is not None and len(cluster_to_files.get(other_cid, [])) > 1:
                dir_clusters[other_cid] += 1

        if not dir_clusters:
            continue

        # Only rescue if a clear majority of directory siblings are in one cluster
        best_cid, best_count = dir_clusters.most_common(1)[0]
        total_dir_files = sum(dir_clusters.values())
        if total_dir_files >= 2 and best_count >= total_dir_files * 2 / 3:
            del cluster_to_files[cid]
            cluster_to_files[best_cid].append(f)
            file_to_cluster[f] = best_cid
            dir_rescued += 1

    if dir_rescued > 0:
        print(f"  Directory-based rescue: {dir_rescued} singletons joined directory-majority clusters")

    sorted_clusters = sorted(cluster_to_files.items(), key=lambda x: -len(x[1]))
    sizes = [len(fs) for _, fs in sorted_clusters]
    n_final = len(sorted_clusters)
    singletons = sum(1 for s in sizes if s == 1)
    multi_file = n_final - singletons

    print(f"  Final clusters: {n_final}")
    print(f"  Singletons: {singletons} ({singletons * 100 // max(n_final, 1)}%)")
    print(f"  Multi-file: {multi_file}")
    print(f"  Largest: {max(sizes)} files")
    print(f"  Size distribution: {sorted(sizes, reverse=True)[:15]}...")

    # Cross-directory analysis
    cross_dir = 0
    cross_lang = 0
    for cid, cfiles in sorted_clusters:
        if len(cfiles) < 2:
            continue
        top_dirs = set(Path(f).parts[0] for f in cfiles if Path(f).parts)
        if len(top_dirs) > 1:
            cross_dir += 1
        exts = set(os.path.splitext(f)[1] for f in cfiles)
        has_py = ".py" in exts
        has_ts = bool(exts & {".ts", ".tsx", ".js", ".jsx"})
        if has_py and has_ts:
            cross_lang += 1

    print(f"\n  Cross-directory clusters: {cross_dir}/{multi_file} ({cross_dir * 100 // max(multi_file, 1)}%)")
    print(f"  Cross-language clusters: {cross_lang}/{multi_file} ({cross_lang * 100 // max(multi_file, 1)}%)")

    # ── Show clusters ──
    print(f"\n{'─' * 50}")
    print("Clusters (multi-file, by size)")
    used_labels = set()
    for cid, cfiles in sorted_clusters:
        if len(cfiles) < 2:
            break

        label = label_cluster(cfiles, file_terms, used_labels)
        used_labels.add(label)

        top_dirs = Counter(Path(f).parts[0] for f in cfiles if Path(f).parts)
        exts = Counter(os.path.splitext(f)[1] for f in cfiles)
        is_cross = len(top_dirs) > 1

        has_py = ".py" in exts
        has_ts = bool(set(exts.keys()) & {".ts", ".tsx", ".js", ".jsx"})
        tags = []
        if is_cross:
            tags.append("CROSS-DIR")
        if has_py and has_ts:
            tags.append("CROSS-LANG")
        tag_str = f" [{', '.join(tags)}]" if tags else ""

        print(f"\n  [{label}] ({len(cfiles)} files){tag_str}")
        if is_cross:
            dir_summary = ", ".join(f"{d}:{c}" for d, c in top_dirs.most_common(5))
            print(f"    dirs: {dir_summary}")
        if len(exts) > 1:
            ext_summary = ", ".join(f"{e}:{c}" for e, c in exts.most_common(5))
            print(f"    langs: {ext_summary}")

        for s in cfiles[:8]:
            print(f"    {s}")
        if len(cfiles) > 8:
            print(f"    ... and {len(cfiles) - 8} more")

    # ── Compare with current Layer C ──
    csg_path = os.path.join(repo_path, ".speed", "context", "semantic-graph.json")
    if os.path.exists(csg_path):
        with open(csg_path) as f:
            csg = json.load(f)
        old = csg.get("clusters", [])
        old_singletons = sum(1 for c in old if len(c.get("symbols", [])) <= 1)
        old_zero = sum(1 for c in old if c.get("cohesion", 0) == 0)

        print(f"\n{'─' * 50}")
        print("vs Current Layer C")
        print(f"  {'Metric':<30} {'Current':>12} {'6-Layer':>12}")
        print(f"  {'─' * 54}")
        print(f"  {'Total clusters':<30} {len(old):>12} {n_final:>12}")
        print(f"  {'Singletons':<30} {old_singletons:>12} {singletons:>12}")
        print(f"  {'Singleton %':<30} {old_singletons * 100 // max(len(old), 1):>11}% {singletons * 100 // max(n_final, 1):>11}%")
        print(f"  {'Zero-cohesion':<30} {old_zero:>12} {'n/a':>12}")
        print(f"  {'Cross-dir clusters':<30} {'~0':>12} {cross_dir:>12}")
        print(f"  {'Cross-lang clusters':<30} {'0':>12} {cross_lang:>12}")
        print(f"  {'Largest cluster':<30} {'1-2':>12} {max(sizes):>12}")
        print(f"  {'MQ score':<30} {'n/a':>12} {best_mq:>12.4f}")

    return {
        "name": name,
        "files": len(files),
        "clusters": n_final,
        "singletons": singletons,
        "multi_file": multi_file,
        "largest": max(sizes),
        "cross_dir": cross_dir,
        "cross_lang": cross_lang,
        "mq": best_mq,
        "layer_stats": layer_stats,
    }


if __name__ == "__main__":
    repos = [
        ("/Users/sanjay.kotagiri/Documents/code/project-travel-prod-bug-fixes", "travel-prod"),
        ("/Users/sanjay.kotagiri/Documents/code/tmp/find-your-tribe", "find-your-tribe"),
        ("/Users/sanjay.kotagiri/Documents/code/tmp/speed", "SPEED"),
    ]

    results = []
    for path, name in repos:
        if os.path.exists(path):
            try:
                r = analyze_codebase(path, name)
                results.append(r)
            except Exception as e:
                print(f"\nERROR on {name}: {e}")
                import traceback
                traceback.print_exc()

    print(f"\n\n{'=' * 70}")
    print("  SUMMARY")
    print(f"{'=' * 70}")
    print(f"{'Codebase':<16} {'Files':>6} {'Clust':>6} {'Sing%':>6} {'Multi':>6} {'X-Dir':>6} {'X-Lang':>7} {'MQ':>8}")
    for r in results:
        sing_pct = r["singletons"] * 100 // max(r["clusters"], 1)
        print(
            f"{r['name']:<16} {r['files']:>6} {r['clusters']:>6} "
            f"{sing_pct:>5}% {r['multi_file']:>6} {r['cross_dir']:>6} "
            f"{r['cross_lang']:>7} {r['mq']:>8.4f}"
        )
