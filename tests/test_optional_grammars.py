"""SPEED starts without the optional custom grammars.

prisma, graphql, protobuf and zig grammars are git-ignored builds. Startup
treated a missing library as an error, and probed every language's rules with
sgconfig.yml (which loads every custom grammar), so all 22 languages looked
broken and no command, not even `speed status`, could run on a fresh clone.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(shutil.which("sg") is None and shutil.which("ast-grep") is None,
                                reason="ast-grep not installed")
ENV = {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin", "NO_COLOR": "1", "HOME": "/tmp"}
# The checks must really run ast-grep: if they cannot find it they skip themselves.
SG = shutil.which("ast-grep") or shutil.which("sg") or ""  # SPEED prefers ast-grep


def _speed_dir(tmp_path: Path) -> Path:
    """A SPEED_DIR with the real rules and sgconfig.yml but no grammar libraries."""
    speed = tmp_path / "speed"
    (speed / "lib/context/data/grammars").mkdir(parents=True)
    shutil.copy(ROOT / "sgconfig.yml", speed / "sgconfig.yml")
    shutil.copytree(ROOT / "lib/context/rules", speed / "lib/context/rules")
    return speed


def _check(speed: Path, function: str) -> subprocess.CompletedProcess:
    # deps.sh runs every startup check when sourced; load only the two checks
    # under test and their platform helper.
    deps = ROOT / "lib/deps.sh"
    load = "".join(f"eval \"$(sed -n '/^{fn}()/,/^}}/p' '{deps}')\"; "
                   for fn in ("_platform_ext", "_check_sgconfig", "_check_ast_grep_rules"))
    python = ROOT / ".venv/bin/python3"
    script = (f'source "{ROOT}/lib/colors.sh"; source "{ROOT}/lib/log.sh"; {load}'
              f'_resolve_python() {{ _deps_python="{python if python.exists() else "python3"}"; }}; '
              f'_resolve_ast_grep() {{ _deps_ast_grep="{SG}"; }}; '
              f'SPEED_DIR="{speed}"; {function}; echo "rc=$?"')
    return subprocess.run(["bash", "-c", script], check=False, capture_output=True, text=True,
                          env=ENV, timeout=300)


def test_missing_optional_grammars_only_warn(tmp_path):
    r = _check(_speed_dir(tmp_path), "_check_sgconfig")
    assert "rc=0" in r.stdout, r.stdout + r.stderr
    assert "Optional grammars not built" in r.stderr and "zig" in r.stderr


def test_rules_are_valid_without_custom_grammars(tmp_path):
    speed = _speed_dir(tmp_path)
    r = _check(speed, "_check_ast_grep_rules")
    assert "rc=0" in r.stdout, r.stdout + r.stderr
    assert "broken ast-grep rules" not in r.stderr
    # Prove the probe ran: a rule ast-grep cannot load is reported.
    (speed / "lib/context/rules/python/zz_broken.yml").write_text(
        "id: broken-probe\nlanguage: python\nmetadata:\n  produces: node\n"
        "rule:\n  kind: completely_fabricated_node_type\n")
    assert "rc=1" in _check(speed, "_check_ast_grep_rules").stdout


def test_a_genuinely_broken_rule_is_still_reported(tmp_path):
    speed = _speed_dir(tmp_path)
    (speed / "lib/context/rules/python/zz_broken.yml").write_text(
        "id: broken-probe\nlanguage: python\nmetadata:\n  produces: node\n"
        "rule:\n  kind: completely_fabricated_node_type\n")
    r = _check(speed, "_check_ast_grep_rules")
    assert "rc=1" in r.stdout, r.stdout + r.stderr
    assert "1 language(s) have broken ast-grep rules" in r.stderr and "python/zz_broken.yml" in r.stderr
