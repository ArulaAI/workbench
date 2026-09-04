"""
6-Layer Domain Clustering for CSG Layer C.

Builds file-level domain clusters from 6 independent signal layers,
then maps results back to the symbol-level consumer interface that
existing code (assembly, decomposition gate, cross-task, Layer D) expects.

Pipeline:
  Layer 0   File inventory via git ls-files
  Layer 2a  ast.parse (Python) + tsconfig regex (TypeScript) import edges
  Layer 2b  Naming conventions (test/story → component)
  Layer 3   Cross-language bridges (GraphQL, REST)
  Layer 4   Package detection (metadata for labeling, no edges)
  Layer 6   Co-change with IDF weighting (git log)
  Layer 5   TF-IDF semantic rescue (orphan files) + labeling
  Leiden    CPM resolution sweep → clusters
  Adopt     Singleton adoption (neighbor majority)
  Rescue    Directory rescue (sibling majority)
"""

import ast
import json
import math
import os
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

try:
    import igraph as ig
    import leidenalg as la
    import networkx as nx
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    HAS_CLUSTERING_DEPS = True
except ImportError:
    HAS_CLUSTERING_DEPS = False

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

_PY_EXTS = {".py"}
_TS_EXTS = {".ts", ".tsx", ".js", ".jsx"}
_JAVA_EXTS = {".java"}

_IDENT_PATTERN = re.compile(r"\b[a-zA-Z_][a-zA-Z0-9_]{2,}\b")

_STOP_IDENTS = {
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
    "url", "path", "file", "dir", "base", "root", "tmp", "temp",
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
    # Spring/Java persistence-testing infrastructure — the same problem
    # as _GENERIC_PATH_SEGMENTS's "java", moved to content instead of
    # paths: a project with parallel Jdbc/Jpa/SpringDataJpa
    # implementations of the same domain entity has test classes whose
    # TF-IDF vectors are otherwise near-identical (SpringBootTest,
    # ActiveProfiles, HSQLDB setup boilerplate) except for the one real
    # domain word — "jdbc"/"jpa" name an implementation *strategy*, not a
    # domain, so two unrelated entities' Jdbc-flavored tests end up
    # scoring more similar to each other than either does to its own
    # domain's Jpa-flavored test, pulling genuinely unrelated tests into
    # the same cluster (confirmed via file_terms on
    # spring-petclinic-reactjs's ClinicServiceJdbcTests vs
    # UserServiceJdbcTests: 9 of 10 top terms identical, only "clinic"
    # vs "user" differs).
    "springframework", "spring", "boot", "jdbc", "jpa", "hsqldb", "profiles",
}

_GENERIC_PATH_SEGMENTS = {
    "src", "lib", "app", "main", "core", "utils", "helpers", "common",
    "shared", "internal", "pkg", "packages", "modules", "vendor",
    "__init__", "index", "__tests__", "test", "tests", "stories", "specs",
    # Maven/Gradle source-root segment ("src/main/java/...") — present in
    # nearly every file of a Java project, so it carries no discriminating
    # signal for a domain label (this is the exact mechanism behind the
    # manager-reported "java/license" label contamination on PetClinic).
    "java",
}

# Clustering parameters
_RESOLUTION_SWEEP = [0.005, 0.01, 0.02, 0.03, 0.05, 0.08, 0.1, 0.15, 0.2, 0.3, 0.5]
_COCHANGE_MAX_DEGREE = 25
_GLOBAL_MAX_DEGREE = 50
_RECURSIVE_SPLIT_MAX_ROUNDS = 5
_RECURSIVE_SPLIT_RESOLUTIONS = [0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0]


# ─── Layer 0: File inventory ──────────────────────────────────────────


def _get_file_inventory(repo_path: str) -> list[str]:
    """Get code files via git ls-files, respecting .gitignore."""
    git_files = _get_git_tracked_files(repo_path)
    if git_files is not None:
        files = []
        for f in git_files:
            ext = os.path.splitext(f)[1].lower()
            if ext not in CODE_EXTENSIONS:
                continue
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


def _classify_language(filepath: str) -> str:
    ext = os.path.splitext(filepath)[1].lower()
    if ext in _PY_EXTS:
        return "python"
    if ext in _TS_EXTS:
        return "typescript"
    if ext in _JAVA_EXTS:
        return "java"
    if ext == ".rb":
        return "ruby"
    if ext == ".go":
        return "go"
    return "other"


# ─── Layer 2a: Compiler-native import resolution ──────────────────────


def _resolve_python_imports(
    repo_path: str, py_files: list[str],
) -> list[tuple[str, str]]:
    """Python import resolution via ast.parse.

    Handles monorepo structure by registering module paths from every
    possible package root.
    """
    file_set = set(py_files)
    edges = []

    # Build lookup: module path → file path
    module_to_file: dict[str, str] = {}
    for f in py_files:
        parts = Path(f).parts
        mod = f.replace("/", ".").replace("\\", ".")
        if mod.endswith(".py"):
            mod = mod[:-3]
        if mod.endswith(".__init__"):
            mod = mod[:-9]
        module_to_file[mod] = f

        for i in range(1, len(parts)):
            submod = ".".join(parts[i:])
            if submod.endswith(".py"):
                submod = submod[:-3]
            if submod.endswith(".__init__"):
                submod = submod[:-9]
            if submod and submod not in module_to_file:
                module_to_file[submod] = f

    def try_resolve(target_module: str) -> str | None:
        candidate = target_module
        while candidate:
            if candidate in module_to_file:
                return module_to_file[candidate]
            py_path = candidate.replace(".", "/") + ".py"
            if py_path in file_set:
                return py_path
            init_path = candidate.replace(".", "/") + "/__init__.py"
            if init_path in file_set:
                return init_path
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
        except (SyntaxError, ValueError, OSError):
            continue

        source_dir = os.path.dirname(source_file)

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                target_module = node.module
                if node.level and node.level > 0:
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


_JAVA_IMPORT_RE = re.compile(
    r"^\s*import\s+(static\s+)?([\w.]+)(\.\*)?\s*;", re.MULTILINE,
)


_JAVA_PACKAGE_DECL_RE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.MULTILINE)


def _resolve_java_imports(
    repo_path: str, java_files: list[str],
) -> list[tuple[str, str]]:
    """Java import resolution via regex, mirroring _resolve_python_imports's
    suffix-registration approach.

    Java imports are always fully qualified from the package root (unlike
    Python's relative imports), but the package root itself isn't at a
    fixed depth in the repo (src/main/java/, src/test/java/, multi-module
    layouts each with their own source root). Registering every path
    suffix as a candidate module key — same technique
    _resolve_python_imports uses for monorepo package roots — resolves an
    import regardless of how deep its actual source root sits, without
    having to detect or hardcode Maven/Gradle layout conventions.

    Wildcard imports (`import pkg.*;`) name a package, not a single file;
    fanning them out to every file in that package would manufacture
    edges no more real than the ones this fix removes elsewhere, so they
    are skipped rather than guessed at.

    Also resolves same-package references, which is not an edge case —
    it's the common case for a package-by-layer Java project (a `service`
    package's impl class referencing its own interface, a test subclass
    extending an abstract test base in the same package): Java requires
    no `import` at all for a class to reference another class in its own
    package, so an import-only scan sees a same-package test subclass as
    having almost no edges at all — a class that references nothing looks
    just as clusterable-anywhere as one that references half the domain,
    and downstream TF-IDF content similarity (which doesn't know about
    package structure) ends up deciding where it lands instead.
    """
    edges = []

    module_to_file: dict[str, str] = {}
    for f in java_files:
        parts = Path(f).parts
        for i in range(len(parts)):
            suffix = parts[i:]
            last = suffix[-1]
            if last.endswith(".java"):
                last = last[:-5]
            mod = ".".join((*suffix[:-1], last))
            if mod and mod not in module_to_file:
                module_to_file[mod] = f

    file_content: dict[str, str] = {}
    file_package: dict[str, str] = {}
    for f in java_files:
        full_path = os.path.join(repo_path, f)
        try:
            with open(full_path, "r", errors="ignore") as fh:
                content = fh.read(100_000)
        except OSError:
            continue
        file_content[f] = content
        m = _JAVA_PACKAGE_DECL_RE.search(content)
        if m:
            file_package[f] = m.group(1)

    siblings_by_package: dict[str, dict[str, str]] = defaultdict(dict)
    for f, pkg in file_package.items():
        class_name = Path(f).stem
        siblings_by_package[pkg].setdefault(class_name, f)

    for source_file, content in file_content.items():
        for match in _JAVA_IMPORT_RE.finditer(content):
            is_static, dotted, is_wildcard = match.group(1), match.group(2), match.group(3)
            if is_wildcard:
                continue
            target = dotted.rsplit(".", 1)[0] if is_static and "." in dotted else dotted

            resolved = module_to_file.get(target)
            if resolved and resolved != source_file:
                edges.append((source_file, resolved))

        pkg = file_package.get(source_file)
        if not pkg:
            continue
        own_class = Path(source_file).stem
        siblings = siblings_by_package.get(pkg, {})
        if len(siblings) <= 1:
            continue
        # Comment-stripped before matching a sibling class *name* as a
        # standalone word — a class merely mentioned in a comment (e.g.
        # "// see OwnerRepository for the contract") is not a real code
        # reference, and without this the raw, unstripped content (read
        # above for the import-statement regex, which never legitimately
        # matches inside a comment) would manufacture a spurious edge
        # from prose alone. Does not also strip string literals — a class
        # name appearing only inside a log/string literal can still
        # produce a false edge; narrower residual risk than comments,
        # left as-is rather than adding string-literal parsing here.
        code_only = _strip_comments(content, source_file)
        for class_name, sibling_file in siblings.items():
            if class_name == own_class:
                continue
            if re.search(rf"\b{re.escape(class_name)}\b", code_only):
                edges.append((source_file, sibling_file))

    return [(s, t) for s, t in edges if s != t]


def _resolve_typescript_imports(
    repo_path: str, ts_files: list[str],
    path_aliases: list[tuple[str, str, str]] | None = None,
) -> list[tuple[str, str]]:
    """TypeScript import resolution via regex + tsconfig path aliases."""
    file_set = set(ts_files)
    edges = []

    if path_aliases is None:
        path_aliases = []

    all_alias_prefixes = {prefix for _, prefix, _ in path_aliases}

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

            if not raw.startswith(".") and not any(raw.startswith(p) for p in all_alias_prefixes):
                continue

            resolved_raw = raw
            is_aliased = False
            best_scope_len = -1
            for scope_dir, prefix, replacement in path_aliases:
                if raw.startswith(prefix) and source_file.startswith(scope_dir + "/" if scope_dir else ""):
                    if len(scope_dir) > best_scope_len:
                        best_scope_len = len(scope_dir)
                        resolved_raw = replacement + raw[len(prefix):]
                        is_aliased = True

            if is_aliased:
                candidate_base = os.path.normpath(resolved_raw)
            elif resolved_raw.startswith("."):
                candidate_base = os.path.normpath(os.path.join(source_dir, resolved_raw))
            else:
                candidate_base = resolved_raw

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


def _find_tsconfig_paths(
    repo_path: str, ts_files: list[str],
) -> list[tuple[str, str, str]]:
    """Find tsconfig.json path aliases, scoped to their directory.

    Returns list of (scope_dir, alias_prefix, resolved_target).
    """
    result = []
    seen_tsconfigs: set[str] = set()

    seen_dirs: set[str] = set()
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


# ─── Layer 2b: Naming convention matching ──────────────────────────────


def _pascal_to_kebab(name: str) -> str:
    result = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", name)
    result = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1-\2", result)
    return result.lower()


def _pascal_to_snake(name: str) -> str:
    result = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    result = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", result)
    return result.lower()


def _find_naming_convention_edges(files: list[str]) -> list[tuple[str, str]]:
    """Match test/story files to components by filename transformation.

    Patterns: .stories removal, .test removal, .spec removal,
    test_ prefix strip, _test suffix strip. Case normalization
    via lowercase, PascalCase-to-kebab, PascalCase-to-snake.
    """
    dir_files: dict[str, dict[str, str]] = defaultdict(dict)
    all_stems: dict[str, list[str]] = defaultdict(list)

    for f in files:
        stem = Path(f).stem
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
        lang = _classify_language(f)

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
        candidates: set[str] = set()

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
                break

        for comp in candidates:
            if comp != f:
                edges.append((f, comp))

    return edges


# ─── Layer 3: Cross-language bridges ──────────────────────────────────


def _find_graphql_bridges(
    repo_path: str, py_files: list[str], ts_files: list[str],
) -> list[tuple[str, str]]:
    """Match Python @strawberry resolvers to TypeScript gql`` operations."""
    py_operations: dict[str, list[str]] = {}
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
                for dec in node.decorator_list:
                    dec_str = ast.dump(dec)
                    if "strawberry" in dec_str and any(
                        kw in dec_str for kw in ["mutation", "field"]
                    ):
                        pascal = "".join(
                            part.capitalize() for part in node.name.split("_")
                        )
                        if pascal not in py_operations:
                            py_operations[pascal] = []
                        py_operations[pascal].append(f)
                        break

    if not py_operations:
        return []

    ts_operations: dict[str, list[str]] = {}
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

    edges = []
    for op_name, py_paths in py_operations.items():
        if op_name in ts_operations:
            for py_path in py_paths:
                for ts_path in ts_operations[op_name]:
                    edges.append((py_path, ts_path))

    return edges


def _find_rest_bridges(
    repo_path: str, py_files: list[str], ts_files: list[str],
) -> list[tuple[str, str]]:
    """Match Python @app.route to TypeScript fetch/axios calls."""
    py_routes: dict[str, list[str]] = {}
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
            normalized = re.sub(r"\{[^}]+\}", "*", route)
            if normalized not in py_routes:
                py_routes[normalized] = []
            py_routes[normalized].append(f)

    if not py_routes:
        return []

    ts_calls: dict[str, list[str]] = {}
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
            path = re.sub(r"https?://[^/]+", "", url)
            path = re.sub(r"\$\{[^}]+\}", "*", path)
            if path not in ts_calls:
                ts_calls[path] = []
            ts_calls[path].append(f)

    edges = []
    for route, py_paths in py_routes.items():
        if route in ts_calls:
            for py_path in py_paths:
                for ts_path in ts_calls[route]:
                    edges.append((py_path, ts_path))
        alt = route.rstrip("/") if route.endswith("/") else route + "/"
        if alt in ts_calls:
            for py_path in py_paths:
                for ts_path in ts_calls[alt]:
                    edges.append((py_path, ts_path))

    return edges


# ─── Layer 4: Package detection ───────────────────────────────────────


def _detect_packages(repo_path: str, files: list[str]) -> dict[str, str]:
    """Detect monorepo packages. Returns file → package_name mapping."""
    package_markers: dict[str, str] = {}
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

    file_to_package: dict[str, str] = {}
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
            top = f.split("/")[0] if "/" in f else "root"
            file_to_package[f] = top

    return file_to_package


# ─── Layer 5: TF-IDF semantic rescue + labeling ──────────────────────

# Matches /* ... */ block comments (Javadoc/JSDoc included) across newlines.
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
# Matches // line comments, but not a "://" inside a string literal
# (http://, https://, ...) so URL text isn't half-truncated.
_LINE_COMMENT_SLASH_RE = re.compile(r"(?<!:)//[^\n]*")
# Matches # line comments (Python, Ruby, shell-style languages).
_LINE_COMMENT_HASH_RE = re.compile(r"#[^\n]*")

_HASH_COMMENT_EXTS = {".py", ".rb", ".sh", ".bash", ".toml", ".yml", ".yaml"}
# Matches a Java package or import declaration line in full — the
# reverse-DNS prefix repeated at the top of every file, see
# _strip_comments.
_JAVA_PACKAGE_IMPORT_RE = re.compile(r"^\s*(?:package|import(?:\s+static)?)\s+[\w.*]+\s*;", re.MULTILINE)


def _strip_comments(content: str, filepath: str) -> str:
    """Strip comment text before identifier extraction.

    License headers, Javadoc/JSDoc prose, and other comment text are not
    code — tokenizing them lets boilerplate (e.g. Apache License headers,
    present verbatim in nearly every file of a project) dominate TF-IDF
    labeling terms. This is a structural strip of comment syntax, not a
    list of specific words to exclude, so it isn't defeated by a
    differently-worded license header (MIT, BSD, ...).
    """
    content = _BLOCK_COMMENT_RE.sub(" ", content)
    ext = Path(filepath).suffix.lower()
    if ext in _HASH_COMMENT_EXTS:
        content = _LINE_COMMENT_HASH_RE.sub(" ", content)
    else:
        content = _LINE_COMMENT_SLASH_RE.sub(" ", content)
    if ext == ".java":
        # Java's package declaration repeats the same reverse-DNS prefix
        # (org.springframework.samples.petclinic...) at the top of every
        # file in the project, and every import line repeats large chunks
        # of it again — unlike a hardcoded word list (which only ever
        # catches one specific organization's prefix), stripping the
        # declaration lines themselves works for any package name. Import
        # target *names* still carry real signal in most languages (a
        # Python "from x.y import Owner" or a TS "import { OwnerService }"
        # names something domain-relevant) so this is deliberately scoped
        # to Java only, not applied to every language's import syntax.
        content = _JAVA_PACKAGE_IMPORT_RE.sub(" ", content)
    return content


def _extract_identifiers(filepath: str) -> str:
    """Extract and expand identifiers from a source file for TF-IDF."""
    try:
        with open(filepath, "r", errors="ignore") as f:
            content = f.read(50_000)
    except (OSError, UnicodeDecodeError):
        return ""
    content = _strip_comments(content, filepath)
    idents = _IDENT_PATTERN.findall(content)
    expanded = []
    for ident in idents:
        lower = ident.lower()
        if lower in _STOP_IDENTS:
            continue
        parts = re.sub(r"([a-z])([A-Z])", r"\1 \2", ident)
        parts = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", parts)
        # camelCase compounds (fooBar) get split above, but a snake_case
        # compound (tmp_path, mock_data) never did — this only replaced
        # case-boundary transitions, never touched underscores, so a
        # Python-only compound whose components ARE individually
        # stopworded (e.g. tmp_path's "path") sailed through as one
        # opaque token the stopword list was never checked against.
        # Splitting on "_" here puts snake_case on equal footing with
        # camelCase before the stopword check below.
        parts = parts.replace("_", " ")
        for p in parts.split():
            if len(p) > 2 and p.lower() not in _STOP_IDENTS:
                expanded.append(p.lower())
    return " ".join(expanded)


def _build_semantic_edges(
    repo_path: str,
    files: list[str],
    orphan_files: set[str],
    file_to_package: dict[str, str],
    threshold: float = 0.4,
) -> tuple[list[tuple[str, str, float]], dict[str, list[str]]]:
    """TF-IDF cosine similarity edges for orphan files.

    Returns (edges, file_terms) where file_terms is used for labeling.
    Edges created only within the same package.
    """
    docs = []
    valid_files = []
    for f in files:
        idents = _extract_identifiers(os.path.join(repo_path, f))
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

    file_terms: dict[str, list[str]] = {}
    for i, f in enumerate(valid_files):
        row = tfidf_matrix[i].toarray()[0]
        top_indices = row.argsort()[-10:][::-1]
        file_terms[f] = [feature_names[j] for j in top_indices if row[j] > 0]

    edges: list[tuple[str, str, float]] = []
    if orphan_files:
        orphan_indices = [i for i, f in enumerate(valid_files) if f in orphan_files]
        for idx in orphan_indices:
            orphan_pkg = file_to_package.get(valid_files[idx], "root")
            sims = cosine_similarity(tfidf_matrix[idx: idx + 1], tfidf_matrix)[0]
            for j in range(len(valid_files)):
                if j != idx and sims[j] >= threshold:
                    target_pkg = file_to_package.get(valid_files[j], "root")
                    if target_pkg == orphan_pkg:
                        edges.append((valid_files[idx], valid_files[j], sims[j]))

    return edges, file_terms


_MAX_SEGMENT_DF = 0.6
# Deliberately lower than TfidfVectorizer's max_df=0.8 below: a reverse-DNS
# Java package prefix (org/springframework/samples/petclinic) sits at ~0.71
# document frequency in a real mixed-language repo (Java backend + JS/TS
# frontend dilute the ratio — every Java file has it, but it's not "every
# file in the repo"), while genuine architectural-layer segments that must
# still win a label (repository, service, mapper, client, ...) stay well
# under 0.3 in the same corpus. 0.6 was calibrated against
# spring-petclinic-reactjs, the repo the "java/license"-label bug was
# reported against, to sit strictly between those two bands.


def _compute_segment_doc_freq(files: list[str]) -> dict[str, int]:
    """Document frequency (distinct-file count) for every normalized path
    segment token across `files` — the path-segment equivalent of the
    max_df cutoff TfidfVectorizer already applies to content-based terms
    in _build_semantic_edges.

    A static blocklist (_GENERIC_PATH_SEGMENTS) only catches whatever
    specific words someone thought to list ("java", "src", "main", ...).
    It can't catch a Java reverse-DNS package prefix like
    org/springframework/samples/petclinic or com/example/myapp — every
    segment of that prefix sits in nearly every file's path, so it's just
    as non-discriminating as "java" is, but the exact words are different
    for every organization and can never be fully enumerated by hand.
    Measuring how many files actually share a segment catches that
    structurally, project-agnostic, on top of the static list rather than
    instead of it.
    """
    doc_freq: Counter = Counter()
    for f in files:
        parts = Path(f).parts
        seen_in_file: set[str] = set()
        for p in parts:
            name = p.lower()
            # endswith + slice, not .replace(): .replace(".ts", "") also
            # matches the ".ts" *prefix* of ".tsx" wherever it occurs —
            # including right at the end of "owner.tsx" — corrupting it
            # to "ownerx" instead of "owner". endswith requires an exact
            # positional match at the string's end, so ".tsx" can never
            # be mistaken for a ".ts" suffix; order-independent by
            # construction, not because of list ordering.
            for ext in (".py", ".ts", ".tsx", ".js", ".jsx", ".java"):
                if name.endswith(ext):
                    name = name[: -len(ext)]
                    break
            for t in re.split(r"[-_.]", name):
                if len(t) > 2:
                    seen_in_file.add(t)
        for t in seen_in_file:
            doc_freq[t] += 1
    return dict(doc_freq)


def _label_cluster(
    cluster_files: list[str],
    file_terms: dict[str, list[str]],
    used_labels: set[str],
    segment_doc_freq: dict[str, int] | None = None,
    total_files: int = 0,
) -> str:
    """Generate cluster label from TF-IDF terms + path segments.

    segment_doc_freq/total_files (both optional, corpus-wide — see
    _compute_segment_doc_freq) dampen a path segment shared by more than
    _MAX_SEGMENT_DF of all files being clustered, the same way the static
    _GENERIC_PATH_SEGMENTS list already does for known-generic segments —
    callers that don't have this precomputed (e.g. existing unit tests
    exercising a single cluster's label directly) simply get the old,
    blocklist-only behavior.
    """
    if len(cluster_files) == 1:
        return Path(cluster_files[0]).stem

    term_scores: Counter = Counter()

    for f in cluster_files:
        terms = file_terms.get(f, [])
        for i, t in enumerate(terms):
            term_scores[t] += (10 - i) if i < 10 else 1

    for f in cluster_files:
        parts = Path(f).parts
        for p in parts:
            name = p.lower()
            for ext in [".py", ".ts", ".tsx", ".js", ".jsx"]:
                name = name.replace(ext, "")
            if name in _GENERIC_PATH_SEGMENTS or len(name) <= 2:
                continue
            tokens = re.split(r"[-_.]", name)
            for t in tokens:
                if len(t) <= 2 or t in _GENERIC_PATH_SEGMENTS:
                    continue
                if (
                    segment_doc_freq is not None and total_files > 0
                    and segment_doc_freq.get(t, 0) / total_files > _MAX_SEGMENT_DF
                ):
                    continue
                term_scores[t] += 3

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


# ─── Layer 6: Co-change with IDF weighting ────────────────────────────


def _build_cochange_graph(
    repo_path: str,
    files: list[str],
    max_commits: int = 5000,
    max_commit_size: int = 50,
    min_shared: int = 2,
) -> "nx.Graph":
    """Build co-change graph from git log with IDF weighting.

    Hub files (appearing in many commits) get dampened via IDF.
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

    commits: list[list[str]] = []
    current_files: list[str] = []
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

    file_commit_count: Counter = Counter()
    pair_counts: Counter = Counter()
    for commit_files in commits:
        if len(commit_files) > max_commit_size or len(commit_files) < 2:
            continue
        for f in commit_files:
            file_commit_count[f] += 1
        for i, f1 in enumerate(commit_files):
            for f2 in commit_files[i + 1:]:
                pair = tuple(sorted([f1, f2]))
                pair_counts[pair] += 1

    file_idf: dict[str, float] = {}
    for f in files:
        doc_freq = file_commit_count.get(f, 0)
        if doc_freq == 0:
            file_idf[f] = 0.0
        else:
            file_idf[f] = math.log(total_commits / doc_freq)

    for (f1, f2), count in pair_counts.items():
        if count < min_shared:
            continue
        conf1 = count / max(file_commit_count[f1], 1)
        conf2 = count / max(file_commit_count[f2], 1)
        idf_weight = file_idf[f1] * file_idf[f2]
        weight = count * ((conf1 + conf2) / 2) * idf_weight

        if weight > 0:
            G.add_edge(f1, f2, weight=weight)

    return G


# ─── Clustering ───────────────────────────────────────────────────────


def _leiden_cluster(G: "nx.Graph", resolution: float = 0.05) -> dict[str, int]:
    """Run Leiden with CPM on the combined graph."""
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


def _compute_mq(G: "nx.Graph", clusters: dict[str, int]) -> float:
    """Modularization Quality (Bunch MQ metric).

    MQ = avg(intra-cluster density) - avg(inter-cluster density).
    """
    cluster_to_files: dict[int, set[str]] = defaultdict(set)
    for f, cid in clusters.items():
        cluster_to_files[cid].add(f)

    if len(cluster_to_files) <= 1:
        return 0.0

    intra_densities = []
    inter_edges = 0

    for cid, members in cluster_to_files.items():
        if len(members) < 2:
            continue
        intra_edge_count = sum(
            1 for u, v in G.edges() if u in members and v in members
        )
        possible = len(members) * (len(members) - 1) / 2
        intra_densities.append(intra_edge_count / possible if possible > 0 else 0)

    for u, v in G.edges():
        cu, cv = clusters.get(u), clusters.get(v)
        if cu is not None and cv is not None and cu != cv:
            inter_edges += 1

    all_files = set(clusters.keys())
    total_possible = len(all_files) * (len(all_files) - 1) / 2
    inter_density = inter_edges / total_possible if total_possible > 0 else 0

    avg_intra = sum(intra_densities) / len(intra_densities) if intra_densities else 0
    return avg_intra - inter_density


# ─── Orchestrator ─────────────────────────────────────────────────────


def build_file_clusters(
    repo_path: str,
) -> tuple[dict[str, int], dict[int, list[str]], "nx.Graph", dict[str, list[str]]]:
    """Run the 6-layer clustering pipeline on a repository.

    Returns:
        file_to_cluster: file path → cluster ID
        cluster_to_files: cluster ID → list of file paths
        combined: the combined edge graph (for computing refs)
        file_terms: TF-IDF term vectors per file (for labeling)
    """
    files = _get_file_inventory(repo_path)
    if not files:
        return {}, {}, nx.Graph(), {}

    py_files = [f for f in files if _classify_language(f) == "python"]
    ts_files = [f for f in files if _classify_language(f) == "typescript"]
    java_files = [f for f in files if _classify_language(f) == "java"]

    combined = nx.Graph()
    combined.add_nodes_from(files)

    # ── Layer 2a: Compiler-native dependencies ──
    py_edges = _resolve_python_imports(repo_path, py_files)
    tsconfig_paths = _find_tsconfig_paths(repo_path, ts_files)
    ts_edges = _resolve_typescript_imports(repo_path, ts_files, tsconfig_paths)
    java_edges = _resolve_java_imports(repo_path, java_files)

    py_unique = set(tuple(sorted(e)) for e in py_edges)
    ts_unique = set(tuple(sorted(e)) for e in ts_edges)
    java_unique = set(tuple(sorted(e)) for e in java_edges)
    import_unique = py_unique | ts_unique | java_unique

    # Convert direct imports to co-import similarity edges
    import_targets: dict[str, set[str]] = defaultdict(set)
    for source, target in import_unique:
        import_targets[source].add(target)

    files_with_imports = [f for f in files if f in import_targets]
    for i, f1 in enumerate(files_with_imports):
        t1 = import_targets[f1]
        for f2 in files_with_imports[i + 1:]:
            t2 = import_targets[f2]
            shared = len(t1 & t2)
            if shared >= 2:
                union = len(t1 | t2)
                weight = shared / union * 3.0
                combined.add_edge(f1, f2, weight=weight)

    # Direct import edges at lower weight.
    # Sorted: a raw set of string-tuples iterates in an order that depends
    # on Python's per-process string-hash randomization, which otherwise
    # makes combined's edge-insertion order — and therefore Leiden's
    # local-moving result, even with a fixed seed — vary run to run on
    # identical input. Every other set-of-edges iterated below has the
    # same fix for the same reason.
    for u, v in sorted(import_unique):
        if combined.has_edge(u, v):
            combined[u][v]["weight"] += 1.0
        else:
            combined.add_edge(u, v, weight=1.0)

    # ── Layer 2b: Naming conventions ──
    nc_edges = _find_naming_convention_edges(files)
    nc_pairs = set(tuple(sorted(e)) for e in nc_edges)

    for u, v in sorted(nc_pairs):
        if combined.has_edge(u, v):
            combined[u][v]["weight"] += 3.0
        else:
            combined.add_edge(u, v, weight=3.0)

    # ── Layer 3: Cross-language bridges ──
    gql_edges = _find_graphql_bridges(repo_path, py_files, ts_files)
    gql_unique = set(tuple(sorted(e)) for e in gql_edges)

    rest_edges = _find_rest_bridges(repo_path, py_files, ts_files)
    rest_unique = set(tuple(sorted(e)) for e in rest_edges)

    for u, v in sorted(gql_unique | rest_unique):
        if combined.has_edge(u, v):
            combined[u][v]["weight"] += 3.0
        else:
            combined.add_edge(u, v, weight=3.0)

    # ── Layer 4: Package detection (metadata only) ──
    file_to_package = _detect_packages(repo_path, files)

    # ── Layer 6: Co-change (before Layer 5, because 5 needs orphans) ──
    cc_graph = _build_cochange_graph(repo_path, files)

    # Degree-cap hub files
    cc_capped = nx.Graph()
    cc_capped.add_nodes_from(cc_graph.nodes())
    for node in cc_graph.nodes():
        neighbors = list(cc_graph[node].items())
        if len(neighbors) <= _COCHANGE_MAX_DEGREE:
            for nbr, data in neighbors:
                if not cc_capped.has_edge(node, nbr):
                    cc_capped.add_edge(node, nbr, weight=data["weight"])
        else:
            top_k = sorted(neighbors, key=lambda x: x[1]["weight"], reverse=True)[:_COCHANGE_MAX_DEGREE]
            for nbr, data in top_k:
                if not cc_capped.has_edge(node, nbr):
                    cc_capped.add_edge(node, nbr, weight=data["weight"])

    for u, v, data in cc_capped.edges(data=True):
        if combined.has_edge(u, v):
            combined[u][v]["weight"] += data["weight"]
        else:
            combined.add_edge(u, v, weight=data["weight"])

    # ── Layer 5: TF-IDF semantic rescue ──
    orphans = {n for n in files if combined.degree(n) == 0}
    sem_edges, file_terms = _build_semantic_edges(
        repo_path, files, orphans, file_to_package, threshold=0.4,
    )

    for u, v, w in sem_edges:
        if combined.has_edge(u, v):
            combined[u][v]["weight"] += w * 0.5
        else:
            combined.add_edge(u, v, weight=w * 0.5)

    # ── Global degree cap ──
    for node in list(combined.nodes()):
        neighbors = list(combined[node].items())
        if len(neighbors) > _GLOBAL_MAX_DEGREE:
            sorted_nbrs = sorted(neighbors, key=lambda x: x[1]["weight"], reverse=True)
            for nbr, _ in sorted_nbrs[_GLOBAL_MAX_DEGREE:]:
                combined.remove_edge(node, nbr)

    # ── Clustering: resolution sweep ──
    target = max(5, int(len(files) ** 0.5))
    best_clusters = None
    best_diff = float("inf")
    best_res = None
    best_mq = -999.0

    for res in _RESOLUTION_SWEEP:
        clusters = _leiden_cluster(combined, resolution=res)
        n_clusters = len(set(clusters.values()))
        mq = _compute_mq(combined, clusters)
        diff = abs(n_clusters - target)

        if diff < best_diff or (diff <= best_diff + 3 and mq > best_mq):
            best_diff = diff
            best_clusters = clusters
            best_res = res
            best_mq = mq

    assert best_clusters is not None

    # Build cluster_to_files
    cluster_to_files: dict[int, list[str]] = defaultdict(list)
    for f, cid in best_clusters.items():
        cluster_to_files[cid].append(f)

    # ── Recursive splitting for oversized clusters ──
    max_cluster_size = max(40, int(len(files) * 0.08))
    next_id = max(cluster_to_files.keys()) + 1

    for _ in range(_RECURSIVE_SPLIT_MAX_ROUNDS):
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
            for sub_res in _RECURSIVE_SPLIT_RESOLUTIONS:
                sub_clusters = _leiden_cluster(subgraph, resolution=sub_res)
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
                sub_groups: dict[int, list[str]] = defaultdict(list)
                for f, sub_cid in sub_best.items():
                    sub_groups[sub_cid].append(f)
                for sub_files in sub_groups.values():
                    cluster_to_files[next_id] = sub_files
                    next_id += 1

    # ── Post-clustering singleton adoption ──
    file_to_cluster: dict[str, int] = {}
    for cid, cfiles in cluster_to_files.items():
        for f in cfiles:
            file_to_cluster[f] = cid

    for cid in list(cluster_to_files.keys()):
        cfiles = cluster_to_files[cid]
        if len(cfiles) != 1:
            continue
        f = cfiles[0]
        if combined.degree(f) == 0:
            continue

        nbr_clusters: Counter = Counter()
        for nbr in combined[f]:
            nbr_cid = file_to_cluster.get(nbr)
            if nbr_cid is not None and len(cluster_to_files.get(nbr_cid, [])) > 1:
                nbr_clusters[nbr_cid] += 1

        if not nbr_clusters:
            continue

        best_cid, best_count = nbr_clusters.most_common(1)[0]
        total_nbr_edges = sum(nbr_clusters.values())
        if len(nbr_clusters) == 1 or best_count >= total_nbr_edges * 2 / 3:
            del cluster_to_files[cid]
            cluster_to_files[best_cid].append(f)
            file_to_cluster[f] = best_cid

    # ── Directory-based rescue ──
    for cid in list(cluster_to_files.keys()):
        cfiles = cluster_to_files[cid]
        if len(cfiles) != 1:
            continue
        f = cfiles[0]
        parent = os.path.dirname(f)
        if not parent:
            continue

        dir_clusters: Counter = Counter()
        for other_f in files:
            if other_f == f or os.path.dirname(other_f) != parent:
                continue
            other_cid = file_to_cluster.get(other_f)
            if other_cid is not None and len(cluster_to_files.get(other_cid, [])) > 1:
                dir_clusters[other_cid] += 1

        if not dir_clusters:
            continue

        best_cid, best_count = dir_clusters.most_common(1)[0]
        total_dir_files = sum(dir_clusters.values())
        if total_dir_files >= 2 and best_count >= total_dir_files * 2 / 3:
            del cluster_to_files[cid]
            cluster_to_files[best_cid].append(f)
            file_to_cluster[f] = best_cid

    return file_to_cluster, dict(cluster_to_files), combined, file_terms


# ─── Consumer interface ──────────────────────────────────────────────


def _map_files_to_symbols(
    file_to_cluster: dict[str, int],
    nodes: list[dict],
) -> dict[str, str]:
    """Map file-level clusters to symbol-level for consumer compatibility.

    All symbols in a file inherit the file's cluster assignment.
    """
    symbol_to_cluster: dict[str, str] = {}
    for node in nodes:
        file_path = node.get("file", "")
        cluster_id = file_to_cluster.get(file_path)
        if cluster_id is not None:
            symbol_to_cluster[node["id"]] = f"cluster_{cluster_id}"
    return symbol_to_cluster


def build_layer_c_from_files(
    nodes: list[dict],
    edges: list[dict],
    repo_path: str,
) -> tuple[list[dict], list[dict], dict[str, str]]:
    """Entry point: 6-layer file clustering mapped to the consumer interface.

    Returns (clusters, cluster_edges, symbol_to_cluster) matching
    the schema that assembly, decomposition gate, cross-task analysis,
    and Layer D expect.
    """
    if not HAS_CLUSTERING_DEPS:
        return [], [], {}

    file_to_cluster, cluster_to_files, combined, file_terms = build_file_clusters(repo_path)

    if not cluster_to_files:
        return [], [], {}

    # Map files to symbols
    symbol_to_cluster = _map_files_to_symbols(file_to_cluster, nodes)

    # Corpus-wide path-segment document frequency, so _label_cluster can
    # dampen a segment shared by nearly every file (see
    # _compute_segment_doc_freq) — computed once over every file that
    # went into clustering, not per-cluster.
    all_clustered_files = [f for cfiles in cluster_to_files.values() for f in cfiles]
    segment_doc_freq = _compute_segment_doc_freq(all_clustered_files)
    total_clustered_files = len(all_clustered_files)

    # Build cluster objects matching the consumer schema
    used_labels: set[str] = set()
    node_lookup = {n["id"]: n for n in nodes}
    reference_types = {"calls", "instantiates", "references_type", "accesses", "contains", "inherits", "implements"}

    clusters_out: list[dict] = []
    cluster_id_map: dict[int, str] = {}  # numeric ID → string ID

    sorted_clusters = sorted(cluster_to_files.items(), key=lambda x: -len(x[1]))

    for numeric_id, cfiles in sorted_clusters:
        label = _label_cluster(cfiles, file_terms, used_labels, segment_doc_freq, total_clustered_files)
        used_labels.add(label)
        cluster_id = f"cluster_{label}_{numeric_id}"
        cluster_id_map[numeric_id] = cluster_id

        # Collect symbols in this cluster
        cluster_symbols = [
            sid for sid, cid_str in symbol_to_cluster.items()
            if cid_str == f"cluster_{numeric_id}"
        ]

        # Count internal vs external refs using the combined file graph
        internal_refs = 0
        external_refs = 0
        cfile_set = set(cfiles)
        for u, v in combined.edges():
            u_in = u in cfile_set
            v_in = v in cfile_set
            if u_in and v_in:
                internal_refs += 1
            elif u_in or v_in:
                external_refs += 1

        total = internal_refs + external_refs
        cohesion = round(internal_refs / total, 2) if total > 0 else 0.0

        clusters_out.append({
            "id": cluster_id,
            "label": label,
            "symbols": cluster_symbols,
            "files": sorted(cfiles),
            "internal_refs": internal_refs,
            "external_refs": external_refs,
            "cohesion": cohesion,
        })

    # Fix symbol_to_cluster to use string cluster IDs (with labels)
    updated_symbol_to_cluster: dict[str, str] = {}
    for sid, old_cid_str in symbol_to_cluster.items():
        numeric_id = int(old_cid_str.replace("cluster_", ""))
        if numeric_id in cluster_id_map:
            updated_symbol_to_cluster[sid] = cluster_id_map[numeric_id]
        else:
            updated_symbol_to_cluster[sid] = old_cid_str

    # Build inter-cluster edges
    cluster_edge_counts: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for edge in edges:
        if edge.get("type") not in reference_types:
            continue
        from_cluster = updated_symbol_to_cluster.get(edge.get("from", ""))
        to_cluster = updated_symbol_to_cluster.get(edge.get("to", ""))
        if from_cluster and to_cluster and from_cluster != to_cluster:
            key = (from_cluster, to_cluster)
            cluster_edge_counts[key].append({
                "from": edge["from"],
                "to": edge["to"],
            })

    cluster_edges_out: list[dict] = []
    for (from_c, to_c), symbol_pairs in cluster_edge_counts.items():
        cluster_edges_out.append({
            "from": from_c,
            "to": to_c,
            "edge_count": len(symbol_pairs),
            "symbols": symbol_pairs[:20],
        })

    return clusters_out, cluster_edges_out, updated_symbol_to_cluster


def measure_commit_coherence(
    repo_path: str,
    file_to_cluster: dict[str, int],
    max_commits: int = 200,
) -> dict:
    """Measure how well clusters predict real change sets.

    For each multi-file, non-merge commit:
      coherence = files_in_dominant_cluster / total_changed_files

    Returns summary statistics.
    """
    try:
        result = subprocess.run(
            ["git", "log", f"--max-count={max_commits}",
             "--no-merges", "--pretty=format:--COMMIT--", "--name-only"],
            cwd=repo_path, capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            return {"error": "git log failed"}
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return {"error": "git unavailable"}

    commits: list[list[str]] = []
    current_files: list[str] = []
    clustered_files = set(file_to_cluster.keys())

    for line in result.stdout.split("\n"):
        line = line.strip()
        if line == "--COMMIT--":
            if current_files:
                commits.append(current_files)
            current_files = []
        elif line and line in clustered_files:
            current_files.append(line)
    if current_files:
        commits.append(current_files)

    coherences: list[float] = []
    for commit_files in commits:
        if len(commit_files) < 2 or len(commit_files) > 30:
            continue
        cluster_counts: Counter = Counter()
        for f in commit_files:
            cid = file_to_cluster.get(f)
            if cid is not None:
                cluster_counts[cid] += 1
        if not cluster_counts:
            continue
        dominant = cluster_counts.most_common(1)[0][1]
        coherences.append(dominant / len(commit_files))

    if not coherences:
        return {"commits_analyzed": 0}

    return {
        "commits_analyzed": len(coherences),
        "mean_coherence": sum(coherences) / len(coherences),
        "median_coherence": sorted(coherences)[len(coherences) // 2],
        "above_50pct": sum(1 for c in coherences if c >= 0.5),
        "below_50pct": sum(1 for c in coherences if c < 0.5),
    }
