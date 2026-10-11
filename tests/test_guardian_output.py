"""Guardian's verdict must be readable wherever it runs.

_run_guardian printed the raw verdict JSON and the flag list on stdout. speed plan,
review and integrate capture stdout and never print it, so a flagged or rejected spec
showed no reasons there, while the standalone command dumped raw JSON on the terminal.
"""

import json
import subprocess
from pathlib import Path

SPEED_DIR = Path(__file__).resolve().parent.parent
LIB = SPEED_DIR / "lib"

VERDICT = {"status": "flagged", "summary": "Fits, with one concern.",
           "flags": [{"severity": "warning", "description": "Provider outage declines outright."}]}


def _guardian(tmp_path: Path, json_output: bool) -> subprocess.CompletedProcess:
    (tmp_path / "specs/product").mkdir(parents=True)
    (tmp_path / "specs/product/overview.md").write_text("# Vision\n")
    (tmp_path / "logs").mkdir()
    fn = lambda name, f: f"eval \"$(sed -n '/^{name}()/,/^}}/p' '{f}')\"; "  # noqa: E731
    script = (
        f'source "{LIB}/colors.sh"; source "{LIB}/log.sh"; '
        + fn("parse_agent_json", LIB / "provider.sh") + fn("_require_json", LIB / "provider.sh")
        + fn("_guardian_emit_json", LIB / "shared.sh") + fn("_run_guardian", LIB / "shared.sh")
        + 'provider_run() { printf "%s" "$VERDICT"; }; '
        + 'out=$(_run_guardian "pre-plan" "spec text" "spec.md"); rc=$?; '
        + 'printf "CAPTURED<%s>\\nRC=%s\\n" "$out" "$rc"'
    )
    env = {"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", "NO_COLOR": "1",
           "PROJECT_ROOT": str(tmp_path), "VISION_FILE": "specs/product/overview.md",
           "STATE_DIR": str(tmp_path / "state"), "LOGS_DIR": str(tmp_path / "logs"),
           "AGENTS_DIR": str(tmp_path), "VERDICT": json.dumps(VERDICT),
           "JSON_OUTPUT": "true" if json_output else "false"}
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env)


def test_flags_reach_the_terminal_when_stdout_is_captured(tmp_path):
    r = _guardian(tmp_path, json_output=False)
    assert "RC=2" in r.stdout
    assert "CAPTURED<>" in r.stdout  # nothing for a person is lost in a captured variable
    assert "FLAGGED" in r.stderr and "Provider outage declines outright." in r.stderr
    assert '"status"' not in r.stderr  # no raw JSON on the terminal


def test_json_mode_puts_the_verdict_on_stdout(tmp_path):
    r = _guardian(tmp_path, json_output=True)
    captured = r.stdout.split("CAPTURED<", 1)[1].split(">\nRC=", 1)[0]
    assert json.loads(captured)["status"] == "flagged"


def test_standalone_guardian_survives_a_flag_under_set_e():
    # speed runs with `set -e`: `_run_guardian ...; rc=$?` exited on a flag or a
    # rejection before printing where the report was saved.
    source = (LIB / "cmd" / "guardian.sh").read_text()
    assert source.count('|| rc=$?') == 2
    assert "local rc=$?" not in source


def test_standalone_guardian_logs_under_the_files_own_feature():
    source = (LIB / "cmd" / "guardian.sh").read_text()
    assert '_file_feature=$(feature_name_from_spec "$input_file"' in source
    assert '"$input_file" == *specs/*' in source


def test_guardian_rejects_only_verified_conflicts():
    # The same fixed spec bundle came back FLAGGED in some runs and REJECTED in others
    # over an interpretive question (whether a country counts as cardholder data).
    prompt = (SPEED_DIR / "agents" / "product-guardian.md").read_text()
    section = prompt[prompt.index("### Critical versus warning"):]
    assert "critical** only when the conflict is verified" in section
    assert "If you are unsure whether a conflict is verified, it is a warning." in section
    assert "`rejected` needs at least one `critical` flag" in prompt
