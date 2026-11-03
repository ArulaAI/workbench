"""Imports resolve to the module they name; global fallback stays in-language.

The resolver matched an import by text (`source_module in node["file"]`):
TypeScript modules arrive quoted and with an extension ("'./money.ts'"), so no
import ever matched and every reference fell back to a global name match. When
two modules export the same name that match is ambiguous and the call edge was
dropped. The global fallback could also link a TypeScript call to a Java
method that happens to be the only symbol with that name.
"""

import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib.context.csg import _build_import_map, _import_module_path, build_csg
from lib.context.treesitter_extract import ExtractionResult, Extractor, Reference

pytestmark = pytest.mark.skipif(shutil.which("sg") is None and shutil.which("ast-grep") is None,
                                reason="ast-grep not installed")


def _graph(tmp_path: Path, files: dict[str, str]):
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    lang = {"ts": "typescript", "java": "java", "py": "python"}
    batch = [{"path": rel, "language": lang[rel.rsplit(".", 1)[1]]} for rel in files]
    graph = build_csg(str(tmp_path), Extractor().extract_batch(batch, str(tmp_path)))
    return {(e["type"], e["from"], e["to"]) for e in graph["edges"]}


COLLIDING = {
    "src/a/money.ts": "export const minor = (n: number) => n;\n",
    "src/b/money.ts": "export const minor = (n: number) => n * 100;\n",
}


def test_same_name_in_two_modules_resolves_through_the_import(tmp_path):
    edges = _graph(tmp_path, {**COLLIDING, "src/app/charge.ts":
        "import { minor } from '../a/money.ts';\nexport function charge(n: number) { return minor(n); }\n"})
    assert ("calls", "src/app/charge.ts::charge", "src/a/money.ts::minor") in edges
    assert not any(e[2] == "src/b/money.ts::minor" for e in edges)


@pytest.mark.parametrize("spec", ["'../b/money'", "'../b/money.js'", '"../b/money.ts"'])
def test_import_spelling_with_or_without_extension_and_quotes(tmp_path, spec):
    edges = _graph(tmp_path, {**COLLIDING, "src/app/charge.ts":
        f"import {{ minor }} from {spec};\nexport function charge(n: number) {{ return minor(n); }}\n"})
    assert ("calls", "src/app/charge.ts::charge", "src/b/money.ts::minor") in edges


def test_type_prefix_and_alias_are_normalised():
    ext = ExtractionResult(file="src/app/x.ts", language="typescript", references=[
        Reference(kind="import", name="i", file="src/app/x.ts", line=1, module="'./m.ts'",
                  symbols=["type Payment", "minor as m", "Ledger"])])
    imports = _build_import_map({"src/app/x.ts": ext})["src/app/x.ts"]
    assert imports["Payment"] == ("./m.ts", "Payment")
    assert imports["m"] == ("./m.ts", "minor")
    assert imports["Ledger"] == ("./m.ts", "Ledger")


def test_module_paths_relative_and_bare():
    assert _import_module_path("'../risk/rules.ts'", "src/payments/gateway.ts") == ("src/risk/rules", True)
    assert _import_module_path(".utils", "lib/context/csg.py") == ("lib/context/utils", True)
    assert _import_module_path("..shared", "lib/context/csg.py") == ("lib/shared", True)
    assert _import_module_path("lib.context.utils", "x.py") == ("lib/context/utils", False)
    assert _import_module_path("''", "x.ts") is None


def test_unique_name_in_another_language_is_not_a_call_target(tmp_path):
    edges = _graph(tmp_path, {
        "src/owner.ts": "export function check(x: any) { return x.isNew(); }\n",
        "java/Owner.java": "class Owner { boolean isNew() { return true; } }\n",
    })
    assert not any(e[0] == "calls" and e[1].startswith("src/owner.ts") and e[2].startswith("java/")
                   for e in edges), edges


def test_unique_name_in_the_same_language_still_resolves(tmp_path):
    edges = _graph(tmp_path, {
        "src/owner.ts": "export function check(x: any) { return x.isNew(); }\n",
        "src/entity.ts": "export class Entity { isNew() { return true; } }\n",
    })
    assert any(e[0] == "calls" and e[1] == "src/owner.ts::check" and e[2].endswith("isNew") for e in edges)
