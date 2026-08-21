"""Tree-sitter + ast-grep extraction engine — Layer 1, Artifact 2.

ast-grep runs declarative YAML rules against tree-sitter ASTs to extract
definitions, references, and ORM/model patterns. tree-sitter handles
skeleton generation. Falls back gracefully when ast-grep CLI or a grammar
isn't installed.

Usage:
    from lib.context.treesitter_extract import Extractor
    ext = Extractor()
    result = ext.extract_file("src/models/user.py", "python")
    # result.definitions, result.references, result.skeleton_lines

Tech spec: tech-spec-context-constructor.md → Artifact 2
"""

from __future__ import annotations

import importlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tree_sitter
    HAS_TREE_SITTER = True
except ImportError:
    HAS_TREE_SITTER = False


# ── Data structures ──────────────────────────────────────────

@dataclass
class SymbolDef:
    """A symbol definition extracted from source."""
    name: str
    kind: str           # class, function, method, type, variable, constant, export
    file: str           # relative path
    line: int           # 1-indexed
    signature: str | None = None  # parameters + return type
    decorators: list[str] = field(default_factory=list)
    parent: str | None = None     # parent symbol name (e.g. class for a method)
    base_classes: list[str] = field(default_factory=list)
    implements: list[str] = field(default_factory=list)


@dataclass
class Reference:
    """A reference (call, import, type ref, attribute access) extracted from source."""
    kind: str           # call, import, type_ref, attribute_access
    name: str           # raw name as it appears in code
    file: str           # file where the reference occurs
    line: int           # 1-indexed
    module: str | None = None  # for imports: the module path
    symbols: list[str] = field(default_factory=list)  # for imports: imported symbol names


@dataclass
class SchemaAnnotation:
    """ORM schema annotation extracted from a model class."""
    table_name: str | None = None
    columns: list[dict] = field(default_factory=list)
    foreign_keys: list[dict] = field(default_factory=list)
    relationships: list[dict] = field(default_factory=list)


@dataclass
class ExtractionResult:
    """Complete extraction result for a single file."""
    file: str
    language: str
    definitions: list[SymbolDef] = field(default_factory=list)
    references: list[Reference] = field(default_factory=list)
    schema_annotations: dict[str, SchemaAnnotation] = field(default_factory=dict)
    skeleton_lines: list[str] = field(default_factory=list)


# ── Language registry ─────────────────────────────────────────

from .language_registry import registry


# ── ast-grep CLI integration ──────────────────────────────────
#
# Spec lines 243-256: SPEED invokes ast-grep via CLI, not Python API.
# The Python API (ast_grep_py) does not load YAML rule files or expose
# rule metadata on match results. The CLI provides both.

# Resolve paths relative to this file (treesitter_extract.py → context/ → lib/ → speed root)
_RULES_DIR = Path(__file__).parent / "rules"
_SPEED_ROOT = Path(__file__).parent.parent.parent
_SG_CONFIG = _SPEED_ROOT / "sgconfig.yml"

# Cache sg availability check
_SG_PATH: str | None = None
_SG_CHECKED = False


def _find_sg() -> str | None:
    """Find the ast-grep CLI binary. Cached after first call.

    Search order:
      1. ``ast-grep`` / ``sg`` on $PATH  (system-wide install)
      2. ``ast-grep`` next to the running Python interpreter
         (covers ``pip install ast-grep-cli`` inside a venv)
    """
    global _SG_PATH, _SG_CHECKED
    if _SG_CHECKED:
        return _SG_PATH
    _SG_CHECKED = True

    # Check next to the running Python first — SPEED invokes the venv
    # python by absolute path without activating it, so .venv/bin/ is
    # not on $PATH even though pip install ast-grep-cli placed the
    # binary there.  PATH is the fallback for Cargo/npm/brew installs.
    import sys
    venv_bin = Path(sys.executable).parent / "ast-grep"
    if venv_bin.is_file() and os.access(venv_bin, os.X_OK):
        _SG_PATH = str(venv_bin)
    else:
        _SG_PATH = shutil.which("ast-grep") or shutil.which("sg")

    return _SG_PATH


def _run_ast_grep(file_path: str, language: str) -> list[dict]:
    """Run ast-grep rules against a single file and return match dicts.

    Uses ``ast-grep scan`` with the project's ``sgconfig.yml`` (which
    declares ``ruleDirs``).  ast-grep discovers all ``.yml`` rule files,
    filters by the ``language:`` field in each rule, and applies only
    the ones that match the scanned file's language.

    Returns empty list if ast-grep is not installed, rules dir doesn't
    exist for this language, or the scan fails for any reason.
    """
    sg = _find_sg()
    if sg is None:
        return []

    # Quick bail-out: skip languages that have no rule directory
    lang_rules_dir = _RULES_DIR / language
    if not lang_rules_dir.is_dir():
        return []

    # Extensionless files: ast-grep can't detect language from extension,
    # so pipe content via stdin with explicit rule files.
    if not os.path.splitext(file_path)[1]:
        return _run_ast_grep_stdin(sg, file_path, lang_rules_dir)

    # Skip files larger than 500KB — bundled/generated files produce
    # enormous ast-grep output (e.g., yarn-3.5.1.cjs → 81MB of matches)
    # and can OOM the extraction process.
    try:
        if os.path.getsize(file_path) > 512_000:
            return []
    except OSError:
        return []

    try:
        result = subprocess.run(
            [sg, "scan", "--json", "--include-metadata",
             "--config", str(_SG_CONFIG), file_path],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return []
        if not result.stdout.strip():
            return []
        return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return []


def _run_ast_grep_stdin(sg: str, file_path: str, lang_rules_dir: Path) -> list[dict]:
    """Fallback for extensionless files: pipe content via stdin with explicit rule files."""
    try:
        source = open(file_path, "r", encoding="utf-8", errors="replace").read()
    except OSError:
        return []

    all_matches: list[dict] = []
    for rule_file in sorted(lang_rules_dir.glob("*.yml")):
        try:
            result = subprocess.run(
                [sg, "scan", "--json", "--include-metadata", "--stdin", "-r", str(rule_file)],
                input=source, capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0 or not result.stdout.strip():
                continue
            all_matches.extend(json.loads(result.stdout))
        except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
            continue

    return all_matches


def _parse_ast_grep_matches(
    matches: list[dict],
    file_path: str,
    rel_path: str,
) -> tuple[list[SymbolDef], list[Reference], dict[str, SchemaAnnotation]]:
    """Map ast-grep JSON matches to SymbolDef, Reference, and SchemaAnnotation objects.

    Each match has:
    - ruleId: which rule matched
    - metadata: {produces, kind, ref_kind, edge_type, orm, ...}
    - text: matched source text
    - range: {start: {line, column}, end: {line, column}}
    - metaVariables: captured $NAME / $$$MULTI values
    """
    defs: list[SymbolDef] = []
    refs: list[Reference] = []
    schemas: dict[str, SchemaAnnotation] = {}

    for match in matches:
        metadata = match.get("metadata", {})
        produces = metadata.get("produces", "")
        text = match.get("text", "")
        range_info = match.get("range", {})
        start = range_info.get("start", {})
        line = start.get("line", 0) + 1  # ast-grep is 0-indexed
        meta_vars = match.get("metaVariables", {})

        if produces == "node":
            kind = metadata.get("kind", "variable")
            # Extract name from metaVariables or from matched text
            name = _extract_name_from_match(match, kind)
            if not name:
                continue

            sym = SymbolDef(
                name=name,
                kind=kind,
                file=rel_path,
                line=line,
            )
            defs.append(sym)

            # ORM model handling
            if metadata.get("orm"):
                _accumulate_orm_match(schemas, match, name, metadata)

        elif produces == "edge":
            edge_type = metadata.get("edge_type", "")
            # Edge matches are structural (inherits, implements)
            # These get processed by CSG build, not stored as SymbolDefs
            name = _extract_name_from_match(match, "class")
            if name and edge_type:
                # Store as a def with edge info in base_classes/implements
                # CSG layer A will pick these up
                sym = SymbolDef(
                    name=name,
                    kind="class",
                    file=rel_path,
                    line=line,
                )
                if edge_type == "inherits":
                    target = _extract_edge_target(match)
                    if target:
                        sym.base_classes = [target]
                elif edge_type == "implements":
                    target = _extract_edge_target(match)
                    if target:
                        sym.implements = [target]
                defs.append(sym)

        elif produces == "reference":
            ref_kind = metadata.get("ref_kind", "call")
            single = meta_vars.get("single", {})
            multi = meta_vars.get("multi", {})

            name = text.strip()[:200]
            module = None
            symbols = []

            if "name_var" in metadata:
                var = single.get(metadata["name_var"], {})
                if isinstance(var, dict) and var.get("text"):
                    name = var["text"]

            if "module_var" in metadata:
                var = single.get(metadata["module_var"], {})
                if isinstance(var, dict) and var.get("text"):
                    module = var["text"]

            if "symbols_var" in metadata:
                key = metadata["symbols_var"]
                if key in multi:
                    symbols = [
                        v["text"] for v in multi[key]
                        if isinstance(v, dict) and v.get("text") and v["text"] != ","
                    ]
                elif key in single:
                    v = single[key]
                    if isinstance(v, dict) and v.get("text"):
                        symbols = [v["text"]]

            refs.append(Reference(
                kind=ref_kind,
                name=name,
                file=rel_path,
                line=line,
                module=module,
                symbols=symbols,
            ))

    return defs, refs, schemas


def _extract_name_from_match(match: dict, kind: str) -> str | None:
    """Extract symbol name from an ast-grep match.

    Tries metaVariables first ($NAME, $FIELD), then parses from matched text.
    """
    meta_vars = match.get("metaVariables", {})
    single = meta_vars.get("single", {})

    # Check common metavariable names (top-level and under "single")
    for var_name in ("NAME", "FIELD"):
        var = single.get(var_name) or meta_vars.get(var_name)
        if var and isinstance(var, dict):
            return var.get("text", "").strip()

    # Parse name from matched text based on kind
    text = match.get("text", "")
    if not text:
        return None

    # For classes/functions: first identifier-like word after keyword
    if kind in ("class", "type"):
        m = re.search(r"(?:class|struct|interface|type|enum|model|trait|impl)\s+(\w+)", text)
        if m:
            return m.group(1)
    elif kind in ("function", "method"):
        m = re.search(r"(?:def|func|fn|function|async\s+function)\s+(\w+)", text)
        if m:
            return m.group(1)
    elif kind == "variable":
        m = re.match(r"\s*(\w+)\s*[=:]", text)
        if m:
            return m.group(1)
    elif kind == "constant":
        # Preprocessor macros: #define NAME VALUE
        m = re.match(r"\s*#\s*define\s+(\w+)", text)
        if m:
            return m.group(1)
        # Skip leading modifiers/keywords to find the actual name
        _CONST_MODIFIERS = {
            "constexpr", "static", "const", "final", "public", "private",
            "protected", "readonly", "volatile", "extern", "inline",
            "export", "declare",
        }
        words = re.findall(r"\w+", text.split("=")[0] if "=" in text else text.split(":")[0] if ":" in text else text)
        for w in words:
            if w.lower() not in _CONST_MODIFIERS and not w.islower():
                return w
        # Last resort: last word before = or :
        if words:
            return words[-1]

    # Fallback: first identifier-like token
    m = re.match(r"\s*(?:pub\s+)?(?:export\s+)?(?:const\s+|let\s+|var\s+)?(\w+)", text)
    if m:
        return m.group(1)

    return None


def _extract_edge_target(match: dict) -> str | None:
    """Extract the target of an inherits/implements edge from match text.

    Handles language-specific inheritance syntax:
      TypeScript/Java:  class Foo extends Bar
      TypeScript/Java:  class Foo implements Bar
      Python:           class Foo(Bar):
      Rust:             impl Trait for Struct
      C#:               class Foo : Bar
      C++:              class Foo : public Bar
      Ruby:             class Foo < Bar
      Go:               embedded type_identifier (bare name)
    """
    text = match.get("text", "")

    # extends / implements (TypeScript, Java, JavaScript)
    m = re.search(r"(?:extends|implements)\s+(\w+)", text)
    if m:
        return m.group(1)

    # Python: class Name(Base, ...):
    m = re.search(r"class\s+\w+\s*\((\w+)", text)
    if m:
        return m.group(1)

    # Rust: impl Trait for Type
    m = re.search(r"impl\s+(\w+)\s+for\s+", text)
    if m:
        return m.group(1)

    # C++: class Name : public Base  /  class Name : Base
    m = re.search(r"(?:class|struct)\s+\w+\s*:\s*(?:public|protected|private)?\s*(\w+)", text)
    if m:
        return m.group(1)

    # Ruby: class Name < Base
    m = re.search(r"class\s+\w+\s*<\s*(\w+)", text)
    if m:
        return m.group(1)

    # Go struct embedding / fallback: bare identifier
    m = re.match(r"\s*(\w+)\s*$", text)
    if m:
        return m.group(1)

    return None


def _accumulate_orm_match(
    schemas: dict[str, SchemaAnnotation],
    match: dict,
    name: str,
    metadata: dict,
) -> None:
    """Accumulate ORM-related match into schema annotations."""
    if name not in schemas:
        schemas[name] = SchemaAnnotation()

    # ORM class-level match (the model itself)
    if metadata.get("kind") == "class":
        # Name is the model class, nothing more to extract from the match itself
        pass
    elif metadata.get("kind") == "variable":
        # Column or relationship match
        text = match.get("text", "")
        if metadata.get("relationship"):
            target = re.search(r'relationship\(["\']?(\w+)', text)
            if target:
                schemas[name].relationships.append({
                    "name": name,
                    "target_model": target.group(1),
                    "relationship_type": "one-to-many",
                })
        else:
            schemas[name].columns.append({
                "name": name,
                "type": "unknown",
                "nullable": True,
                "primary_key": "primary_key=True" in text or "primaryKey" in text,
            })


# ── Skeleton extraction (tree-sitter, kept) ───────────────────
#
# Skeletons use tree-sitter directly, not ast-grep. They need the full
# AST to select structural lines. These functions are language-specific
# because different languages have different structural node types.


def _find_nodes(node: Any, type_name: str) -> list:
    """Recursively find all nodes of a given type."""
    results = []
    if node.type == type_name:
        results.append(node)
    for child in node.children:
        results.extend(_find_nodes(child, type_name))
    return results


def _find_nodes_multi(node: Any, type_names: set[str]) -> list:
    """Recursively find all nodes matching any of the given types."""
    results = []
    if node.type in type_names:
        results.append(node)
    for child in node.children:
        results.extend(_find_nodes_multi(child, type_names))
    return results


def _node_text(node: Any) -> str:
    """Get decoded text of a node."""
    return node.text.decode("utf-8")


def _extract_python_skeleton(root: Any, source_lines: list[str]) -> list[str]:
    """Extract skeleton lines from Python AST — structural lines without function bodies."""
    skeleton: list[str] = []
    _seen_lines: set[int] = set()

    def _add_line(line_idx: int) -> None:
        if line_idx not in _seen_lines and 0 <= line_idx < len(source_lines):
            _seen_lines.add(line_idx)
            skeleton.append(source_lines[line_idx])

    def _add_node_line(node: Any) -> None:
        _add_line(node.start_point[0])

    def _process_node(node: Any, in_class: bool = False) -> None:
        if node.type == "module":
            for child in node.children:
                _process_node(child)
        elif node.type in ("import_statement", "import_from_statement"):
            _add_node_line(node)
        elif node.type == "expression_statement":
            _add_node_line(node)
        elif node.type == "class_definition":
            _add_node_line(node)
            body = node.child_by_field_name("body")
            if body:
                for item in body.children:
                    if item.type == "function_definition":
                        _add_node_line(item)
                    elif item.type == "decorated_definition":
                        for sub in item.children:
                            if sub.type == "decorator":
                                _add_node_line(sub)
                            elif sub.type in ("function_definition", "class_definition"):
                                _add_node_line(sub)
                                if sub.type == "class_definition":
                                    _process_node(sub, in_class=True)
                    elif item.type == "expression_statement":
                        _add_node_line(item)
                    elif item.type == "class_definition":
                        _process_node(item, in_class=True)
        elif node.type == "function_definition":
            _add_node_line(node)
        elif node.type == "decorated_definition":
            for sub in node.children:
                if sub.type == "decorator":
                    _add_node_line(sub)
                elif sub.type in ("function_definition", "class_definition"):
                    if sub.type == "class_definition":
                        _process_node(sub)
                    else:
                        _add_node_line(sub)
        elif node.type == "if_statement":
            text = _node_text(node)
            if '__name__' in text and '__main__' in text:
                _add_node_line(node)

    _process_node(root)
    skeleton.sort(key=lambda line: source_lines.index(line) if line in source_lines else 0)
    return skeleton


def _extract_ts_skeleton(root: Any, source_lines: list[str]) -> list[str]:
    """Extract skeleton from TypeScript/JavaScript — imports, signatures, types, exports."""
    skeleton_line_indices: set[int] = set()

    def _add_range(start_line: int, end_line: int) -> None:
        for i in range(start_line, min(end_line + 1, len(source_lines))):
            skeleton_line_indices.add(i)

    def _process_node(node: Any) -> None:
        ntype = node.type
        if ntype in ("import_statement", "interface_declaration", "type_alias_declaration",
                      "enum_declaration"):
            _add_range(node.start_point[0], node.end_point[0])
        elif ntype in ("function_declaration", "method_definition"):
            skeleton_line_indices.add(node.start_point[0])
        elif ntype == "class_declaration":
            skeleton_line_indices.add(node.start_point[0])
            body = node.child_by_field_name("body")
            if body:
                for item in body.children:
                    _process_node(item)
        elif ntype == "lexical_declaration":
            skeleton_line_indices.add(node.start_point[0])
        elif ntype == "export_statement":
            skeleton_line_indices.add(node.start_point[0])
            for child in node.children:
                if child.is_named:
                    _process_node(child)
        elif ntype == "public_field_definition":
            skeleton_line_indices.add(node.start_point[0])

    for child in root.children:
        _process_node(child)

    return [source_lines[i] for i in sorted(skeleton_line_indices) if i < len(source_lines)]


def _extract_generic_skeleton(root: Any, source_lines: list[str], language: str) -> list[str]:
    """Generic skeleton — definition lines + imports + top-level declarations."""
    skeleton_lines: set[int] = set()

    import_types = {
        "import_statement", "import_from_statement", "import_declaration",
        "use_declaration", "use_item", "include_directive", "preproc_include",
        "package_clause", "require",
    }
    # Generic definition node types per language
    def_types: dict[str, set[str]] = {
        "go": {"function_declaration", "method_declaration", "type_declaration", "type_spec"},
        "rust": {"function_item", "struct_item", "enum_item", "impl_item", "trait_item", "type_item", "const_item"},
        "java": {"class_declaration", "interface_declaration", "method_declaration", "constructor_declaration", "enum_declaration"},
        "ruby": {"class", "module", "method", "singleton_method"},
        "c": {"function_definition", "struct_specifier", "enum_specifier", "type_definition"},
        "cpp": {"function_definition", "class_specifier", "struct_specifier", "enum_specifier", "type_definition"},
        "c_sharp": {"class_declaration", "interface_declaration", "method_declaration", "constructor_declaration", "enum_declaration", "struct_declaration"},
        "bash": {"function_definition"},
        "php": {"class_declaration", "interface_declaration", "trait_declaration", "enum_declaration", "method_declaration", "function_definition", "const_declaration"},
        "kotlin": {"class_declaration", "object_declaration", "function_declaration", "interface_declaration", "enum_class"},
        "swift": {"class_declaration", "protocol_declaration", "function_declaration"},
        "scala": {"class_definition", "trait_definition", "object_definition", "enum_definition", "function_definition"},
        "elixir": {"call"},
        "lua": {"function_declaration", "variable_declaration"},
        "haskell": {"data_type", "class", "instance", "type_synomym", "newtype", "signature", "function"},
        "zig": {"variable_declaration", "function_declaration"},
    }

    target_types = def_types.get(language, set())

    for node in _find_nodes_multi(root, import_types):
        skeleton_lines.add(node.start_point[0])

    for node in _find_nodes_multi(root, target_types):
        skeleton_lines.add(node.start_point[0])

    return [source_lines[i] for i in sorted(skeleton_lines) if i < len(source_lines)]


# ── Helper retained for test compatibility ────────────────────

def _strip_collection_type(type_text: str) -> str:
    """Strip list[] or List[] wrapper from a type string."""
    match = re.search(r"(?:list|List)\[(.+)\]", type_text)
    if match:
        return match.group(1)
    return type_text


def _extract_mapped_type(type_text: str) -> str:
    """Extract inner type from Mapped[Type] annotation."""
    match = re.search(r"Mapped\[(.+)\]", type_text)
    if match:
        inner = match.group(1)
        opt_match = re.search(r"Optional\[(.+)\]", inner)
        if opt_match:
            return opt_match.group(1)
        return inner
    return type_text


# ── Main Extractor class ─────────────────────────────────────


class Extractor:
    """ast-grep + tree-sitter extraction engine.

    For extraction="rules" languages: runs ast-grep YAML rules via CLI
    to extract definitions, references, and ORM patterns. Falls back to
    tree-sitter skeleton-only if ast-grep is not installed.

    For extraction="skeleton" languages: tree-sitter parse for skeleton
    generation only.

    Skeletons always use tree-sitter directly (need full AST for
    structural line selection).
    """

    def __init__(self) -> None:
        if not HAS_TREE_SITTER:
            raise ImportError(
                "tree-sitter is not installed. "
                "Run: pip install tree-sitter tree-sitter-python ..."
            )
        self._parsers: dict[str, Any] = {}
        self._failed_languages: set[str] = set()

    def _get_parser(self, language: str) -> Any | None:
        """Get or create a parser for the given language."""
        if language in self._parsers:
            return self._parsers[language]
        if language in self._failed_languages:
            return None

        entry = registry.grammar(language)
        if not entry:
            self._failed_languages.add(language)
            return None

        module_name, func_name = entry
        try:
            mod = importlib.import_module(module_name)
            loader = getattr(mod, func_name)
            lang = tree_sitter.Language(loader())
            parser = tree_sitter.Parser(lang)
            self._parsers[language] = parser
            return parser
        except (ImportError, AttributeError, Exception):
            self._failed_languages.add(language)
            return None

    def can_parse(self, language: str) -> bool:
        """Check if we can parse the given language."""
        return self._get_parser(language) is not None

    def parse_file(self, file_path: str, language: str) -> Any | None:
        """Parse a file and return the tree-sitter Tree. Returns None on failure."""
        parser = self._get_parser(language)
        if not parser:
            return None
        try:
            with open(file_path, "rb") as f:
                source = f.read()
            return parser.parse(source)
        except (OSError, Exception):
            return None

    def extract_file(
        self,
        file_path: str,
        language: str,
        rel_path: str | None = None,
    ) -> ExtractionResult:
        """Extract definitions, references, schema, and skeleton from a file.

        Dispatch per spec line 870:
        - extraction="rules": ast-grep YAML rules for defs/refs, tree-sitter for skeleton
        - extraction="skeleton": tree-sitter skeleton only, no defs/refs
        - extraction="none": skip entirely
        """
        path_for_ids = rel_path or file_path
        result = ExtractionResult(file=path_for_ids, language=language)

        level = registry.extraction_level(language)

        if level == "rules":
            # ast-grep for definitions and references
            matches = _run_ast_grep(file_path, language)
            if matches:
                defs, refs, schemas = _parse_ast_grep_matches(matches, file_path, path_for_ids)
                result.definitions = defs
                result.references = refs
                result.schema_annotations = schemas

            # tree-sitter for skeleton (always, regardless of ast-grep success)
            tree = self.parse_file(file_path, language)
            if tree is not None:
                root = tree.root_node
                try:
                    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                        source_lines = f.read().splitlines()
                except OSError:
                    source_lines = []

                if language == "python":
                    result.skeleton_lines = _extract_python_skeleton(root, source_lines)
                elif language in ("typescript", "tsx", "javascript"):
                    result.skeleton_lines = _extract_ts_skeleton(root, source_lines)
                else:
                    result.skeleton_lines = _extract_generic_skeleton(root, source_lines, language)

        elif level == "skeleton":
            # tree-sitter skeleton only, no defs/refs
            tree = self.parse_file(file_path, language)
            if tree is not None:
                root = tree.root_node
                try:
                    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                        source_lines = f.read().splitlines()
                except OSError:
                    source_lines = []

                if language in ("typescript", "tsx", "javascript"):
                    result.skeleton_lines = _extract_ts_skeleton(root, source_lines)
                else:
                    result.skeleton_lines = _extract_generic_skeleton(root, source_lines, language)

        # level == "none": skip, return empty result

        return result

    def extract_batch(
        self,
        files: list[dict],
        project_root: str,
    ) -> dict[str, ExtractionResult]:
        """Extract from multiple files.

        Args:
            files: list of dicts with "path" and "language" keys
                   (as returned by project map)
            project_root: absolute path to project root

        Returns:
            dict mapping relative path -> ExtractionResult
        """
        results: dict[str, ExtractionResult] = {}

        for file_info in files:
            rel_path = file_info["path"]
            language = file_info.get("language")
            if not language:
                continue

            abs_path = os.path.join(project_root, rel_path)
            results[rel_path] = self.extract_file(abs_path, language, rel_path)

        return results
