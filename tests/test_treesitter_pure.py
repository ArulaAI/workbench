"""Unit tests for pure-logic functions in treesitter_extract.py.

Tests only functions that require no tree-sitter binaries or ast-grep CLI:
  - _extract_name_from_match
  - _extract_edge_target
  - _parse_ast_grep_matches
  - _strip_collection_type
  - _extract_mapped_type
  - _accumulate_orm_match
"""

import sys
from pathlib import Path

# Ensure the project root is on sys.path so `lib.context` is importable.
_project_root = str(Path(__file__).parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import pytest

from lib.context.treesitter_extract import (
    SchemaAnnotation,
    SymbolDef,
    Reference,
    _extract_name_from_match,
    _extract_edge_target,
    _parse_ast_grep_matches,
    _strip_collection_type,
    _extract_mapped_type,
    _accumulate_orm_match,
)


# ── Helpers ──────────────────────────────────────────────────────

def _make_match(
    text="",
    meta_vars=None,
    metadata=None,
    rule_id="test-rule",
    start_line=0,
):
    """Build a minimal ast-grep match dict."""
    m = {
        "ruleId": rule_id,
        "text": text,
        "range": {"start": {"line": start_line, "column": 0}, "end": {"line": start_line, "column": len(text)}},
        "metaVariables": meta_vars or {},
        "metadata": metadata or {},
    }
    return m


def _make_match_with_name(name_text, kind="class", text="", **kwargs):
    """Build a match whose metaVariables.single.NAME resolves to name_text."""
    meta_vars = {"single": {"NAME": {"text": name_text}}}
    return _make_match(text=text, meta_vars=meta_vars, metadata={"produces": "node", "kind": kind}, **kwargs)


# ── _extract_name_from_match ─────────────────────────────────────


class TestExtractNameFromMatch:
    """Tests for _extract_name_from_match(match, kind)."""

    # -- metaVariable extraction --

    def test_name_from_meta_variable_NAME(self):
        match = _make_match(meta_vars={"single": {"NAME": {"text": "UserModel"}}})
        assert _extract_name_from_match(match, "class") == "UserModel"

    def test_name_from_meta_variable_FIELD(self):
        match = _make_match(meta_vars={"single": {"FIELD": {"text": "email"}}})
        assert _extract_name_from_match(match, "variable") == "email"

    def test_NAME_preferred_over_FIELD(self):
        match = _make_match(meta_vars={"single": {"NAME": {"text": "primary"}, "FIELD": {"text": "secondary"}}})
        assert _extract_name_from_match(match, "class") == "primary"

    def test_meta_variable_at_top_level(self):
        """NAME can appear directly under metaVariables (not nested in 'single')."""
        match = _make_match(meta_vars={"single": {}, "NAME": {"text": "TopLevel"}})
        assert _extract_name_from_match(match, "class") == "TopLevel"

    def test_meta_variable_strips_whitespace(self):
        match = _make_match(meta_vars={"single": {"NAME": {"text": "  padded  "}}})
        assert _extract_name_from_match(match, "class") == "padded"

    def test_meta_variable_empty_text(self):
        """If NAME text is empty string, returns empty string (truthy metavar dict)."""
        match = _make_match(meta_vars={"single": {"NAME": {"text": ""}}})
        result = _extract_name_from_match(match, "class")
        assert result == ""

    def test_meta_variable_missing_text_key(self):
        """NAME dict exists but has no 'text' key. get("text","") returns ""."""
        match = _make_match(
            text="class Fallback:",
            meta_vars={"single": {"NAME": {"node_id": 42}}},
        )
        result = _extract_name_from_match(match, "class")
        assert result == ""  # dict exists, .get("text","") returns ""

    # -- Text-based extraction: class / type --

    def test_class_from_text_python(self):
        match = _make_match(text="class User(Base):")
        assert _extract_name_from_match(match, "class") == "User"

    def test_class_from_text_struct(self):
        match = _make_match(text="struct Point { int x; int y; }")
        assert _extract_name_from_match(match, "class") == "Point"

    def test_type_from_text_interface(self):
        match = _make_match(text="interface Serializable {}")
        assert _extract_name_from_match(match, "type") == "Serializable"

    def test_type_from_text_enum(self):
        match = _make_match(text="enum Color { Red, Green, Blue }")
        assert _extract_name_from_match(match, "type") == "Color"

    def test_type_from_text_trait(self):
        match = _make_match(text="trait Drawable { fn draw(&self); }")
        assert _extract_name_from_match(match, "type") == "Drawable"

    def test_type_from_text_model(self):
        match = _make_match(text="model User { id Int @id }")
        assert _extract_name_from_match(match, "type") == "User"

    # -- Text-based extraction: function / method --

    def test_function_python_def(self):
        match = _make_match(text="def calculate_total(items, tax):")
        assert _extract_name_from_match(match, "function") == "calculate_total"

    def test_function_go_func(self):
        match = _make_match(text="func handleRequest(w http.ResponseWriter, r *http.Request) {")
        assert _extract_name_from_match(match, "function") == "handleRequest"

    def test_function_rust_fn(self):
        match = _make_match(text="fn process_data(input: &str) -> Result<(), Error> {")
        assert _extract_name_from_match(match, "function") == "process_data"

    def test_function_javascript(self):
        match = _make_match(text="function fetchData(url) {")
        assert _extract_name_from_match(match, "function") == "fetchData"

    def test_method_async_function(self):
        match = _make_match(text="async function loadUser(id) {")
        assert _extract_name_from_match(match, "method") == "loadUser"

    # -- Text-based extraction: variable --

    def test_variable_assignment(self):
        match = _make_match(text="count = 42")
        assert _extract_name_from_match(match, "variable") == "count"

    def test_variable_type_annotation(self):
        match = _make_match(text="name: str = 'Alice'")
        assert _extract_name_from_match(match, "variable") == "name"

    def test_variable_leading_whitespace(self):
        match = _make_match(text="    indented = True")
        assert _extract_name_from_match(match, "variable") == "indented"

    # -- Text-based extraction: constant --

    def test_constant_preprocessor_define(self):
        match = _make_match(text="#define MAX_SIZE 1024")
        assert _extract_name_from_match(match, "constant") == "MAX_SIZE"

    def test_constant_with_modifiers(self):
        match = _make_match(text="static const MAX_RETRIES = 3")
        assert _extract_name_from_match(match, "constant") == "MAX_RETRIES"

    def test_constant_export_declare(self):
        match = _make_match(text="export const API_URL = 'https://example.com'")
        assert _extract_name_from_match(match, "constant") == "API_URL"

    def test_constant_typescript_readonly(self):
        match = _make_match(text="readonly DEFAULT_TIMEOUT: number = 30")
        assert _extract_name_from_match(match, "constant") == "DEFAULT_TIMEOUT"

    def test_constant_all_lowercase_falls_to_last_word(self):
        """When all words are lowercase (no 'constant-like' name), return last word before =."""
        match = _make_match(text="const something = 5")
        result = _extract_name_from_match(match, "constant")
        # 'const' is in _CONST_MODIFIERS and is lowercase, 'something' is lowercase too,
        # so falls to "last word before =" which is 'something'
        assert result == "something"

    # -- Fallback --

    def test_fallback_first_identifier(self):
        match = _make_match(text="pub export const myGlobal = 99")
        # kind is something unexpected, fallback regex skips pub/export/const
        result = _extract_name_from_match(match, "unknown_kind")
        assert result == "myGlobal"

    def test_empty_text_no_metavars(self):
        match = _make_match(text="")
        assert _extract_name_from_match(match, "class") is None

    def test_completely_empty_match(self):
        assert _extract_name_from_match({}, "function") is None

    def test_no_metavariables_key(self):
        match = {"text": "class Empty:", "metadata": {}}
        assert _extract_name_from_match(match, "class") == "Empty"


# ── _extract_edge_target ─────────────────────────────────────────


class TestExtractEdgeTarget:
    """Tests for _extract_edge_target(match)."""

    # -- extends / implements (TS, Java, JS) --

    def test_extends_typescript(self):
        match = _make_match(text="class Admin extends User {")
        assert _extract_edge_target(match) == "User"

    def test_implements_java(self):
        match = _make_match(text="class UserService implements Service {")
        assert _extract_edge_target(match) == "Service"

    # -- Python parenthesized bases --

    def test_python_single_base(self):
        match = _make_match(text="class User(Base):")
        assert _extract_edge_target(match) == "Base"

    def test_python_multiple_bases_returns_first(self):
        match = _make_match(text="class Admin(User, Permissions):")
        assert _extract_edge_target(match) == "User"

    def test_python_no_base_class(self):
        """class Foo: (no parens) -> no Python base match, falls through."""
        match = _make_match(text="class Foo:")
        # No extends, no parens, no impl, no colon-base, no <, no bare identifier (has colon).
        assert _extract_edge_target(match) is None

    # -- Rust impl for --

    def test_rust_impl_trait_for(self):
        match = _make_match(text="impl Display for User {")
        assert _extract_edge_target(match) == "Display"

    # -- C++ style : public Base --

    def test_cpp_public_base(self):
        match = _make_match(text="class Derived : public BaseClass {")
        assert _extract_edge_target(match) == "BaseClass"

    def test_cpp_private_base(self):
        match = _make_match(text="class Derived : private Internal {")
        assert _extract_edge_target(match) == "Internal"

    def test_cpp_no_access_specifier(self):
        match = _make_match(text="class Derived : Parent {")
        assert _extract_edge_target(match) == "Parent"

    def test_struct_inheritance(self):
        match = _make_match(text="struct Derived : Base {")
        assert _extract_edge_target(match) == "Base"

    # -- Ruby < --

    def test_ruby_inheritance(self):
        match = _make_match(text="class Admin < User")
        assert _extract_edge_target(match) == "User"

    # -- Go struct embedding / bare identifier --

    def test_go_embedded_type(self):
        match = _make_match(text="  BaseModel  ")
        assert _extract_edge_target(match) == "BaseModel"

    # -- Edge cases --

    def test_empty_text(self):
        match = _make_match(text="")
        assert _extract_edge_target(match) is None

    def test_no_text_key(self):
        assert _extract_edge_target({}) is None

    def test_non_matching_text(self):
        match = _make_match(text="import os; x = 1 + 2")
        # None of the patterns match; fallback bare-identifier requires only \w+ surrounded by whitespace
        assert _extract_edge_target(match) is None

    def test_extends_takes_priority_over_python_parens(self):
        """If text has both 'extends' and parenthesized base, extends wins (checked first)."""
        match = _make_match(text="class Foo extends Bar(Baz)")
        assert _extract_edge_target(match) == "Bar"


# ── _strip_collection_type ───────────────────────────────────────


class TestStripCollectionType:

    def test_lowercase_list(self):
        assert _strip_collection_type("list[int]") == "int"

    def test_uppercase_List(self):
        assert _strip_collection_type("List[str]") == "str"

    def test_nested_type(self):
        assert _strip_collection_type("List[Optional[User]]") == "Optional[User]"

    def test_no_wrapper(self):
        assert _strip_collection_type("str") == "str"

    def test_empty_string(self):
        assert _strip_collection_type("") == ""

    def test_partial_match_no_brackets(self):
        assert _strip_collection_type("List") == "List"

    def test_dict_not_stripped(self):
        assert _strip_collection_type("dict[str, int]") == "dict[str, int]"

    def test_list_with_complex_inner(self):
        assert _strip_collection_type("list[dict[str, Any]]") == "dict[str, Any]"


# ── _extract_mapped_type ─────────────────────────────────────────


class TestExtractMappedType:

    def test_simple_mapped(self):
        assert _extract_mapped_type("Mapped[int]") == "int"

    def test_mapped_optional(self):
        assert _extract_mapped_type("Mapped[Optional[str]]") == "str"

    def test_no_mapped_wrapper(self):
        assert _extract_mapped_type("int") == "int"

    def test_empty_string(self):
        assert _extract_mapped_type("") == ""

    def test_mapped_complex_inner(self):
        assert _extract_mapped_type("Mapped[list[User]]") == "list[User]"

    def test_mapped_optional_complex(self):
        assert _extract_mapped_type("Mapped[Optional[list[int]]]") == "list[int]"

    def test_mapped_without_brackets(self):
        assert _extract_mapped_type("Mapped") == "Mapped"


# ── _accumulate_orm_match ────────────────────────────────────────


class TestAccumulateOrmMatch:

    def test_creates_schema_for_new_name(self):
        schemas = {}
        match = _make_match(text="class User(Base):")
        _accumulate_orm_match(schemas, match, "User", {"kind": "class", "orm": True})
        assert "User" in schemas
        assert isinstance(schemas["User"], SchemaAnnotation)

    def test_class_kind_no_columns_added(self):
        schemas = {}
        match = _make_match(text="class User(Base):")
        _accumulate_orm_match(schemas, match, "User", {"kind": "class", "orm": True})
        assert schemas["User"].columns == []
        assert schemas["User"].relationships == []

    def test_variable_column(self):
        schemas = {}
        match = _make_match(text="email = Column(String(255))")
        _accumulate_orm_match(schemas, match, "email", {"kind": "variable", "orm": True})
        assert len(schemas["email"].columns) == 1
        col = schemas["email"].columns[0]
        assert col["name"] == "email"
        assert col["primary_key"] is False
        assert col["nullable"] is True

    def test_variable_column_primary_key(self):
        schemas = {}
        match = _make_match(text="id = Column(Integer, primary_key=True)")
        _accumulate_orm_match(schemas, match, "id", {"kind": "variable", "orm": True})
        col = schemas["id"].columns[0]
        assert col["primary_key"] is True

    def test_variable_column_sequelize_primaryKey(self):
        schemas = {}
        match = _make_match(text="id: { type: DataTypes.INTEGER, primaryKey: true }")
        _accumulate_orm_match(schemas, match, "id", {"kind": "variable", "orm": True})
        col = schemas["id"].columns[0]
        assert col["primary_key"] is True

    def test_relationship(self):
        schemas = {}
        match = _make_match(text="posts = relationship('Post', back_populates='author')")
        _accumulate_orm_match(schemas, match, "posts", {"kind": "variable", "orm": True, "relationship": True})
        assert len(schemas["posts"].relationships) == 1
        rel = schemas["posts"].relationships[0]
        assert rel["target_model"] == "Post"
        assert rel["name"] == "posts"

    def test_relationship_unquoted_target(self):
        schemas = {}
        match = _make_match(text="posts = relationship(Post, back_populates='author')")
        _accumulate_orm_match(schemas, match, "posts", {"kind": "variable", "orm": True, "relationship": True})
        rel = schemas["posts"].relationships[0]
        assert rel["target_model"] == "Post"

    def test_relationship_no_target_found(self):
        """If regex can't find target, no relationship is added."""
        schemas = {}
        match = _make_match(text="posts = relationship()")
        _accumulate_orm_match(schemas, match, "posts", {"kind": "variable", "orm": True, "relationship": True})
        assert schemas["posts"].relationships == []

    def test_accumulates_multiple_columns(self):
        schemas = {}
        m1 = _make_match(text="id = Column(Integer, primary_key=True)")
        m2 = _make_match(text="name = Column(String(100))")
        _accumulate_orm_match(schemas, m1, "User", {"kind": "variable", "orm": True})
        _accumulate_orm_match(schemas, m2, "User", {"kind": "variable", "orm": True})
        assert len(schemas["User"].columns) == 2

    def test_mixed_columns_and_relationships(self):
        schemas = {}
        _accumulate_orm_match(
            schemas,
            _make_match(text="class User(Base):"),
            "User",
            {"kind": "class", "orm": True},
        )
        _accumulate_orm_match(
            schemas,
            _make_match(text="id = Column(Integer, primary_key=True)"),
            "User",
            {"kind": "variable", "orm": True},
        )
        _accumulate_orm_match(
            schemas,
            _make_match(text="posts = relationship('Post')"),
            "User",
            {"kind": "variable", "orm": True, "relationship": True},
        )
        assert len(schemas["User"].columns) == 1
        assert len(schemas["User"].relationships) == 1
        assert schemas["User"].relationships[0]["target_model"] == "Post"


# ── _parse_ast_grep_matches ──────────────────────────────────────


class TestParseAstGrepMatches:

    def test_empty_matches_list(self):
        defs, refs, schemas = _parse_ast_grep_matches([], "src/foo.py", "src/foo.py")
        assert defs == []
        assert refs == []
        assert schemas == {}

    def test_node_produces_symbol_def(self):
        matches = [
            _make_match_with_name("UserService", kind="class", text="class UserService:", start_line=10),
        ]
        defs, refs, schemas = _parse_ast_grep_matches(matches, "/abs/path.py", "path.py")
        assert len(defs) == 1
        assert defs[0].name == "UserService"
        assert defs[0].kind == "class"
        assert defs[0].file == "path.py"
        assert defs[0].line == 11  # 0-indexed start_line + 1

    def test_node_skipped_when_no_name(self):
        """If _extract_name_from_match returns None, the match is skipped."""
        matches = [
            _make_match(text="", metadata={"produces": "node", "kind": "class"}),
        ]
        defs, refs, schemas = _parse_ast_grep_matches(matches, "f.py", "f.py")
        assert defs == []

    def test_edge_inherits(self):
        matches = [{
            "ruleId": "py-inherits",
            "text": "class Admin(User):",
            "range": {"start": {"line": 5, "column": 0}, "end": {"line": 5, "column": 20}},
            "metaVariables": {"single": {"NAME": {"text": "Admin"}}},
            "metadata": {"produces": "edge", "edge_type": "inherits"},
        }]
        defs, refs, schemas = _parse_ast_grep_matches(matches, "f.py", "f.py")
        assert len(defs) == 1
        assert defs[0].name == "Admin"
        assert defs[0].kind == "class"
        assert defs[0].base_classes == ["User"]
        assert defs[0].implements == []

    def test_edge_implements(self):
        matches = [{
            "ruleId": "ts-implements",
            "text": "class UserService implements Service {",
            "range": {"start": {"line": 0, "column": 0}, "end": {"line": 0, "column": 40}},
            "metaVariables": {"single": {"NAME": {"text": "UserService"}}},
            "metadata": {"produces": "edge", "edge_type": "implements"},
        }]
        defs, refs, schemas = _parse_ast_grep_matches(matches, "f.ts", "f.ts")
        assert len(defs) == 1
        assert defs[0].implements == ["Service"]
        assert defs[0].base_classes == []

    def test_edge_no_name_skipped(self):
        matches = [{
            "ruleId": "test",
            "text": "",
            "range": {"start": {"line": 0, "column": 0}, "end": {"line": 0, "column": 0}},
            "metaVariables": {},
            "metadata": {"produces": "edge", "edge_type": "inherits"},
        }]
        defs, _, _ = _parse_ast_grep_matches(matches, "f.py", "f.py")
        assert defs == []

    def test_edge_no_edge_type_skipped(self):
        matches = [{
            "ruleId": "test",
            "text": "class Foo(Bar):",
            "range": {"start": {"line": 0, "column": 0}, "end": {"line": 0, "column": 20}},
            "metaVariables": {"single": {"NAME": {"text": "Foo"}}},
            "metadata": {"produces": "edge", "edge_type": ""},
        }]
        defs, _, _ = _parse_ast_grep_matches(matches, "f.py", "f.py")
        assert defs == []

    def test_reference_basic_call(self):
        matches = [{
            "ruleId": "py-call",
            "text": "do_something(x, y)",
            "range": {"start": {"line": 7, "column": 0}, "end": {"line": 7, "column": 20}},
            "metaVariables": {"single": {}, "multi": {}},
            "metadata": {"produces": "reference", "ref_kind": "call"},
        }]
        _, refs, _ = _parse_ast_grep_matches(matches, "f.py", "f.py")
        assert len(refs) == 1
        assert refs[0].kind == "call"
        assert refs[0].name == "do_something(x, y)"
        assert refs[0].line == 8
        assert refs[0].module is None
        assert refs[0].symbols == []

    def test_reference_with_name_var(self):
        matches = [{
            "ruleId": "py-import",
            "text": "from os.path import join",
            "range": {"start": {"line": 0, "column": 0}, "end": {"line": 0, "column": 25}},
            "metaVariables": {
                "single": {"MOD": {"text": "os.path"}, "SYM": {"text": "join"}},
                "multi": {},
            },
            "metadata": {
                "produces": "reference",
                "ref_kind": "import",
                "name_var": "SYM",
                "module_var": "MOD",
            },
        }]
        _, refs, _ = _parse_ast_grep_matches(matches, "f.py", "f.py")
        assert refs[0].name == "join"
        assert refs[0].module == "os.path"

    def test_reference_with_symbols_var_multi(self):
        matches = [{
            "ruleId": "py-import-multi",
            "text": "from typing import List, Dict, Optional",
            "range": {"start": {"line": 0, "column": 0}, "end": {"line": 0, "column": 40}},
            "metaVariables": {
                "single": {"MOD": {"text": "typing"}},
                "multi": {
                    "SYMS": [
                        {"text": "List"},
                        {"text": ","},
                        {"text": "Dict"},
                        {"text": ","},
                        {"text": "Optional"},
                    ],
                },
            },
            "metadata": {
                "produces": "reference",
                "ref_kind": "import",
                "name_var": "MOD",
                "module_var": "MOD",
                "symbols_var": "SYMS",
            },
        }]
        _, refs, _ = _parse_ast_grep_matches(matches, "f.py", "f.py")
        assert refs[0].symbols == ["List", "Dict", "Optional"]

    def test_reference_symbols_var_single_fallback(self):
        """When symbols_var key is found in single (not multi), treat as single-item list."""
        matches = [{
            "ruleId": "py-import",
            "text": "from os import path",
            "range": {"start": {"line": 0, "column": 0}, "end": {"line": 0, "column": 20}},
            "metaVariables": {
                "single": {"MOD": {"text": "os"}, "SYM": {"text": "path"}},
                "multi": {},
            },
            "metadata": {
                "produces": "reference",
                "ref_kind": "import",
                "name_var": "SYM",
                "module_var": "MOD",
                "symbols_var": "SYM",
            },
        }]
        _, refs, _ = _parse_ast_grep_matches(matches, "f.py", "f.py")
        assert refs[0].symbols == ["path"]

    def test_reference_long_text_truncated(self):
        """Match text is truncated to 200 chars when no name_var is set."""
        long_text = "x" * 300
        matches = [{
            "ruleId": "test",
            "text": long_text,
            "range": {"start": {"line": 0, "column": 0}, "end": {"line": 0, "column": 300}},
            "metaVariables": {"single": {}, "multi": {}},
            "metadata": {"produces": "reference", "ref_kind": "call"},
        }]
        _, refs, _ = _parse_ast_grep_matches(matches, "f.py", "f.py")
        assert len(refs[0].name) == 200

    def test_node_with_orm_triggers_schema(self):
        matches = [{
            "ruleId": "py-orm-class",
            "text": "class User(Base):",
            "range": {"start": {"line": 0, "column": 0}, "end": {"line": 0, "column": 20}},
            "metaVariables": {"single": {"NAME": {"text": "User"}}},
            "metadata": {"produces": "node", "kind": "class", "orm": True},
        }]
        defs, _, schemas = _parse_ast_grep_matches(matches, "f.py", "f.py")
        assert "User" in schemas
        assert len(defs) == 1

    def test_multiple_mixed_produces(self):
        """A match list with nodes, edges, and references all at once."""
        matches = [
            {
                "ruleId": "r1",
                "text": "class Foo(Bar):",
                "range": {"start": {"line": 0, "column": 0}, "end": {"line": 0, "column": 20}},
                "metaVariables": {"single": {"NAME": {"text": "Foo"}}},
                "metadata": {"produces": "node", "kind": "class"},
            },
            {
                "ruleId": "r2",
                "text": "class Foo(Bar):",
                "range": {"start": {"line": 0, "column": 0}, "end": {"line": 0, "column": 20}},
                "metaVariables": {"single": {"NAME": {"text": "Foo"}}},
                "metadata": {"produces": "edge", "edge_type": "inherits"},
            },
            {
                "ruleId": "r3",
                "text": "import os",
                "range": {"start": {"line": 1, "column": 0}, "end": {"line": 1, "column": 10}},
                "metaVariables": {"single": {}, "multi": {}},
                "metadata": {"produces": "reference", "ref_kind": "import"},
            },
        ]
        defs, refs, schemas = _parse_ast_grep_matches(matches, "f.py", "f.py")
        assert len(defs) == 2  # one node + one edge
        assert len(refs) == 1
        assert defs[1].base_classes == ["Bar"]

    def test_unknown_produces_ignored(self):
        """Matches with an unrecognized 'produces' value are silently skipped."""
        matches = [{
            "ruleId": "test",
            "text": "something",
            "range": {"start": {"line": 0, "column": 0}, "end": {"line": 0, "column": 10}},
            "metaVariables": {},
            "metadata": {"produces": "unknown_type"},
        }]
        defs, refs, schemas = _parse_ast_grep_matches(matches, "f.py", "f.py")
        assert defs == []
        assert refs == []
        assert schemas == {}

    def test_missing_metadata(self):
        """Match with no metadata is silently skipped (produces='')."""
        matches = [{
            "ruleId": "test",
            "text": "anything",
            "range": {"start": {"line": 0, "column": 0}, "end": {"line": 0, "column": 10}},
            "metaVariables": {},
        }]
        defs, refs, schemas = _parse_ast_grep_matches(matches, "f.py", "f.py")
        assert defs == []
        assert refs == []

    def test_missing_range(self):
        """Match with no range info defaults line to 1 (0 + 1)."""
        matches = [{
            "ruleId": "test",
            "text": "class X:",
            "metaVariables": {"single": {"NAME": {"text": "X"}}},
            "metadata": {"produces": "node", "kind": "class"},
        }]
        defs, _, _ = _parse_ast_grep_matches(matches, "f.py", "f.py")
        assert defs[0].line == 1

    def test_reference_name_var_empty_text(self):
        """If name_var points to a metavar with empty text, name stays as the match text."""
        matches = [{
            "ruleId": "test",
            "text": "some_call()",
            "range": {"start": {"line": 0, "column": 0}, "end": {"line": 0, "column": 12}},
            "metaVariables": {"single": {"FN": {"text": ""}}, "multi": {}},
            "metadata": {"produces": "reference", "ref_kind": "call", "name_var": "FN"},
        }]
        _, refs, _ = _parse_ast_grep_matches(matches, "f.py", "f.py")
        # Empty string is falsy, so name_var check fails and name stays as match text
        assert refs[0].name == "some_call()"

    def test_reference_module_var_not_dict(self):
        """If module_var points to something that isn't a dict, module stays None."""
        matches = [{
            "ruleId": "test",
            "text": "import x",
            "range": {"start": {"line": 0, "column": 0}, "end": {"line": 0, "column": 10}},
            "metaVariables": {"single": {"MOD": "not-a-dict"}, "multi": {}},
            "metadata": {"produces": "reference", "ref_kind": "import", "module_var": "MOD"},
        }]
        _, refs, _ = _parse_ast_grep_matches(matches, "f.py", "f.py")
        assert refs[0].module is None

    def test_reference_symbols_var_multi_filters_commas(self):
        """Commas in multi-match symbols are filtered out."""
        matches = [{
            "ruleId": "test",
            "text": "from m import a, b",
            "range": {"start": {"line": 0, "column": 0}, "end": {"line": 0, "column": 20}},
            "metaVariables": {
                "single": {},
                "multi": {
                    "S": [{"text": "a"}, {"text": ","}, {"text": "b"}],
                },
            },
            "metadata": {"produces": "reference", "ref_kind": "import", "symbols_var": "S"},
        }]
        _, refs, _ = _parse_ast_grep_matches(matches, "f.py", "f.py")
        assert refs[0].symbols == ["a", "b"]

    def test_reference_symbols_var_multi_filters_non_dicts(self):
        """Non-dict entries in multi-match are skipped."""
        matches = [{
            "ruleId": "test",
            "text": "from m import a",
            "range": {"start": {"line": 0, "column": 0}, "end": {"line": 0, "column": 20}},
            "metaVariables": {
                "single": {},
                "multi": {
                    "S": [{"text": "a"}, "stray_string", None],
                },
            },
            "metadata": {"produces": "reference", "ref_kind": "import", "symbols_var": "S"},
        }]
        _, refs, _ = _parse_ast_grep_matches(matches, "f.py", "f.py")
        assert refs[0].symbols == ["a"]
