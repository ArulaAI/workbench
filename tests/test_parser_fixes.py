"""ast-grep / tree-sitter extraction fixes (Layer 1 symbol graph).

- The four custom grammars (prisma, graphql, protobuf, zig) are optional,
  git-ignored builds. Scanning with sgconfig.yml loads all of them, so one
  missing library made every scan fail and a fresh clone extracted nothing.
- TS/JS class methods were named from the first word of the match, so
  `private nextId()` became a symbol called "private".
- Java qualified calls (repo.findById(), this.helper()) and constructor-
  injected types were never captured, so class-to-class links disappeared.
- `@MappedSuperclass public class BaseEntity` was named "public".
"""

import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib.context import treesitter_extract as te
from lib.context.treesitter_extract import Extractor

pytestmark = pytest.mark.skipif(shutil.which("sg") is None and shutil.which("ast-grep") is None,
                                reason="ast-grep not installed")

SERVICE_TS = """export class PaymentsService {
  private seq = 0;
  authorise(amount: number) { return this.nextId(); }
  private nextId(): string { return `pay_${++this.seq}`; }
  private require(id: string) { return id; }
  static create() { return new PaymentsService(); }
}
"""


def _extract(tmp_path: Path, files: dict[str, str], language: str):
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    batch = [{"path": rel, "language": language} for rel in files]
    return Extractor().extract_batch(batch, str(tmp_path))


def test_ordinary_languages_do_not_depend_on_custom_grammars(tmp_path, monkeypatch):
    # Point sgconfig at a config whose custom grammar library does not exist:
    # extraction for TypeScript must still work.
    broken = tmp_path / "sgconfig.yml"
    broken.write_text("ruleDirs:\n  - %s\ncustomLanguages:\n  zig:\n    libraryPath: missing/zig.dylib\n"
                      "    extensions: [zig]\n" % (ROOT / "lib/context/rules"))
    monkeypatch.setattr(te, "_SG_CONFIG", broken)
    res = _extract(tmp_path / "repo", {"src/service.ts": SERVICE_TS}, "typescript")
    assert len(res["src/service.ts"].definitions) > 0


def test_custom_grammar_check_only_covers_custom_languages():
    assert te._custom_grammar_available("typescript") is False
    assert te._custom_grammar_available("java") is False
    lib = ROOT / "lib/context/data/grammars" / f"zig.{'dylib' if sys.platform == 'darwin' else 'so'}"
    assert te._custom_grammar_available("zig") is lib.is_file()


def test_typescript_methods_are_named_by_their_name_not_modifier(tmp_path):
    res = _extract(tmp_path, {"src/service.ts": SERVICE_TS}, "typescript")
    methods = {d.name for d in res["src/service.ts"].definitions if d.kind == "method"}
    assert {"authorise", "nextId", "require", "create"} <= methods
    assert "private" not in methods and "static" not in methods


def test_javascript_methods_are_named_by_their_name_not_modifier(tmp_path):
    js = "class Q {\n  static make() { return new Q(); }\n  async load() { return 1; }\n  get size() { return 0; }\n}\n"
    res = _extract(tmp_path, {"src/q.js": js}, "javascript")
    methods = {d.name for d in res["src/q.js"].definitions if d.kind == "method"}
    assert {"make", "load", "size"} <= methods
    assert not methods & {"static", "async", "get"}


JAVA = {
    "src/OwnerRepository.java": "public class OwnerRepository { public Owner findById(int id) { return null; } }\n",
    "src/OwnerService.java": (
        "public class OwnerService {\n"
        "  private final OwnerRepository repository;\n"
        "  public OwnerService(OwnerRepository repository) { this.repository = repository; }\n"
        "  public Owner load(int id) { return repository.findById(id); }\n"
        "  public void audit() { this.helper(); }\n"
        "  private void helper() {}\n}\n"),
    "src/BaseEntity.java": "@MappedSuperclass\npublic class BaseEntity { }\n",
    "src/Owner.java": "public class Owner extends BaseEntity { }\n",
}
