"""SPEED runs from Git Bash on Windows, where Python and jq are native programs.

Windows Python could not open the /c/... paths SPEED wrote into Python source,
so the Layer 1 index never built. Windows jq ended lines with CRLF, `read` kept
the \\r, and every plan failed its dependency sort ("task 1 does not exist").
"""

import os
import platform
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "lib" / "config.sh"
ON_WINDOWS_BASH = platform.system() == "Windows"


def _bash(script: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-c", script], check=False, capture_output=True, text=True, encoding="utf-8",
                          env={"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "")},
                          cwd=cwd, timeout=60)


def _funcs(*names: str) -> str:
    return "; ".join(f"eval \"$(sed -n '/^{n}()/,/^}}/p' '{CONFIG.as_posix()}')\"" for n in names)


def test_paths_pass_through_off_windows():
    r = _bash(_funcs("speed_native_path") + "; SPEED_WINDOWS=false; speed_native_path /c/Users/x")
    assert r.stdout.strip() == "/c/Users/x"


def test_venv_python_found_in_unix_and_windows_layouts(tmp_path):
    unix, win = tmp_path / "u", tmp_path / "w"
    (unix / ".venv" / "bin").mkdir(parents=True)
    (win / ".venv" / "Scripts").mkdir(parents=True)
    for py in (unix / ".venv" / "bin" / "python3", win / ".venv" / "Scripts" / "python.exe"):
        py.write_text("#!/bin/sh\n")
        py.chmod(0o755)
    script = _funcs("speed_venv_python") + f"; speed_venv_python '{unix.as_posix()}'; speed_venv_python '{win.as_posix()}'"
    out = _bash(script).stdout
    assert "/.venv/bin/python3" in out and "/.venv/Scripts/python.exe" in out
    assert _bash(_funcs("speed_venv_python") + f"; speed_venv_python '{tmp_path.as_posix()}' || echo none").stdout.strip() == "none"


def test_platform_ext_knows_windows():
    deps = (ROOT / "lib" / "deps.sh").read_text(encoding="utf-8")
    assert 'MINGW*|MSYS*|CYGWIN*) echo "dll"' in deps


def test_scripts_check_out_with_lf():
    attrs = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "* text=auto eol=lf" in attrs


@pytest.mark.skipif(not ON_WINDOWS_BASH, reason="Git Bash on Windows only")
def test_windows_roots_are_native_and_jq_reads_without_cr(tmp_path):
    script = (f"source '{CONFIG.as_posix()}' >/dev/null 2>&1; "
              'echo "root=$PROJECT_ROOT"; echo "speed=$SPEED_DIR"; '
              """while IFS= read -r d; do echo "dep=${#d}"; done < <(echo '{"d":["1"]}' | jq -r '.d[]')""")
    out = _bash(script, cwd=tmp_path).stdout
    root = next(ln for ln in out.splitlines() if ln.startswith("root="))[5:]
    assert root[1:3] == ":/", root           # C:/... form
    assert Path(root) == tmp_path
    assert "dep=1" in out                    # no trailing \r
