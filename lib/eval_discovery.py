"""Read test identities without importing test files or executing test bodies.

Python uses its AST. JS/TS uses the tree-sitter packages already used by the
context index. Dynamic titles and unsupported frameworks remain unverified.
"""
from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path

from lib.eval_criteria import scenario_tags


def _python(source: str) -> list[dict]:
    found = []
    def visit(body, parents=()):
        for node in body:
            if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                visit(node.body, (*parents, node.name))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                match = re.match(r"^test_([a-z][a-z0-9]*(?:_[a-z][a-z0-9]*)*)_(\d{2,})(?:_|$)", node.name)
                if match:
                    sid = match[1].upper().replace("_", "-") + "-" + match[2]
                    found.append({"scenario_ids": {sid}, "nodes": [*parents, node.name]})
    visit(ast.parse(source).body)
    return found


def _javascript(source: str, suffix: str) -> list[dict]:
    try:
        from tree_sitter import Language, Parser
        module = importlib.import_module("tree_sitter_typescript" if suffix in (".ts", ".tsx", ".mts", ".cts") else "tree_sitter_javascript")
        loader = "language_tsx" if suffix == ".tsx" else "language_typescript" if suffix in (".ts", ".mts", ".cts") else "language"
        tree = Parser(Language(getattr(module, loader)())).parse(source.encode())
    except (ImportError, AttributeError, TypeError) as exc:
        raise ValueError("JS/TS discovery needs the tree-sitter JavaScript/TypeScript packages in SPEED_PYTHON") from exc
    if tree.root_node.has_error:
        raise ValueError("Cannot discover tests from invalid JavaScript/TypeScript syntax")
    found = []
    def literal(node):
        if node is None or node.type not in ("string", "template_string"):
            return None
        if any(c.type == "template_substitution" for c in node.named_children):
            return None
        text = node.text.decode()
        if text.startswith("`"):
            text = "'" + text[1:-1].replace("'", "\\'") + "'"
        try:
            value = ast.literal_eval(text)
            return value if isinstance(value, str) else None
        except (ValueError, SyntaxError):
            return None
    def visit(node, suites=()):
        if node.type == "call_expression":
            function = node.child_by_field_name("function")
            args = node.child_by_field_name("arguments")
            name = function.text.decode() if function else ""
            arguments = args.named_children if args else []
            title = literal(arguments[0]) if arguments else None
            # Only literal test declarations are discoverable. A skipped test
            # retains its identity; the runner must still prove it executed.
            if re.fullmatch(r"(?:describe|suite)(?:\.(?:skip|only|concurrent))*", name):
                for child in arguments[1:]:
                    visit(child, (*suites, title))
                return
            if re.fullmatch(r"(?:test|it)(?:\.(?:skip|only|todo|concurrent))*", name):
                ids = scenario_tags(title or "")
                if ids:
                    if None in suites:
                        found.append({"scenario_ids": ids, "error": "Tagged test is inside a dynamically named suite"})
                    else:
                        found.append({"scenario_ids": ids, "test_name": " ".join([*suites, title])})
                return
            if title and scenario_tags(title) and (name.startswith("test.") or name.startswith("it.")):
                found.append({"scenario_ids": scenario_tags(title), "error": "Dynamic/parameterized JS test declaration needs a literal test title"})
                return
        for child in node.named_children:
            visit(child, suites)
    visit(tree.root_node)
    return found


def discover_tests(path: Path, runner: str) -> list[dict]:
    source = path.read_text(encoding="utf-8")
    if runner == "pytest" and path.suffix == ".py":
        return _python(source)
    if runner in ("node", "jest", "vitest") and path.suffix in (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts"):
        return _javascript(source, path.suffix)
    raise ValueError(f"No stable-ID test discovery adapter for {runner} / {path.suffix}")
