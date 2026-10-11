"""Plan caches are keyed on everything their result depends on.

The Guardian and Architect caches were keyed on the specs alone. After the Guardian
prompt changed, `speed plan` reused a stale REJECTED verdict ("cached (specs
unchanged)"), and Architect prompt changes would reuse an old plan.
"""

import subprocess
from pathlib import Path

LIB = Path(__file__).resolve().parent.parent / "lib"
PLAN = LIB / "cmd" / "plan.sh"


def _key(tmp_path: Path, prompt: str, vision: str = "vision", model: str = "m1") -> str:
    agents = tmp_path / "agents"
    agents.mkdir(exist_ok=True)
    (agents / "product-guardian.md").write_text(prompt)
    (tmp_path / "overview.md").write_text(vision)
    script = (f"eval \"$(sed -n '/^_plan_guardian_cache_key()/,/^}}/p' '{PLAN}')\"; "
              "_plan_guardian_cache_key spec123")
    env = {"PATH": "/usr/bin:/bin", "PROJECT_ROOT": str(tmp_path), "VISION_FILE": "overview.md",
           "STATE_DIR": str(tmp_path / "state"), "AGENTS_DIR": str(agents), "MODEL_SUPPORT": model}
    return subprocess.run(["bash", "-c", script], check=False, capture_output=True, text=True, env=env).stdout.strip()


def test_guardian_key_is_stable_for_the_same_inputs(tmp_path):
    assert _key(tmp_path, "p") == _key(tmp_path, "p") != ""


def test_guardian_key_changes_with_prompt_vision_and_model(tmp_path):
    base = _key(tmp_path, "p")
    assert _key(tmp_path, "p2") != base
    assert _key(tmp_path, "p", vision="vision 2") != base
    assert _key(tmp_path, "p", model="m2") != base


def test_unparseable_guardian_verdicts_are_not_cached_and_architect_key_includes_prompts():
    source = PLAN.read_text()
    assert '[[ "$guardian_rc" != "3" ]] && _plan_cache_write "guardian" "$guardian_key"' in source
    key = source[source.index("architect_cache_hash=$({"):][:600]
    assert "architect.md" in key and "MODEL_PLANNING" in key


def _confirm(env_extra: dict, stdin: str | None) -> subprocess.CompletedProcess:
    script = (f'source "{LIB}/colors.sh"; source "{LIB}/log.sh"; EXIT_GATE_FAILURE=2; '
              "_log_gate_skip() { echo SKIPLOG \"$@\" >&2; }; _cov_critical=2; "
              f"eval \"$(sed -n '/^_plan_confirm_repair()/,/^}}/p' '{PLAN}')\"; "
              '_plan_confirm_repair "Add?"; echo "rc=$?"')
    env = {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin", "NO_COLOR": "1", **env_extra}
    return subprocess.run(["bash", "-c", script], check=False, input=stdin, capture_output=True, text=True, env=env)


def test_coverage_gaps_stop_without_a_terminal():
    # S3.4-TR2: interactive repair needs confirmation; noninteractive critical gaps stop.
    r = _confirm({}, stdin="")
    assert r.returncode == 2 and "rc=" not in r.stdout
    assert "SKIP_COVERAGE=true" in r.stderr and "in a terminal" in r.stderr


def test_skip_coverage_proceeds_without_repair_and_logs_the_bypass():
    r = _confirm({"SKIP_COVERAGE": "true"}, stdin="")
    assert "rc=1" in r.stdout and "SKIPLOG coverage plan" in r.stderr


def test_terminal_answer_yes_repairs():
    # Drive the helper through a real pseudo-terminal on stdin.
    import os
    import pty
    master, slave = pty.openpty()
    script = (f'source "{LIB}/colors.sh"; source "{LIB}/log.sh"; EXIT_GATE_FAILURE=2; _cov_critical=1; '
              f"eval \"$(sed -n '/^_plan_confirm_repair()/,/^}}/p' '{PLAN}')\"; "
              '_plan_confirm_repair "Add?"; echo "rc=$?"')
    os.write(master, b"y\n")
    r = subprocess.run(["bash", "-c", script], check=False, stdin=slave, capture_output=True, text=True,
                       env={"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin", "NO_COLOR": "1"}, timeout=30)
    os.close(slave)
    os.close(master)
    assert "rc=0" in r.stdout, r.stdout + r.stderr


def test_both_repairs_use_the_same_confirmation():
    source = PLAN.read_text()
    assert source.count("_plan_confirm_repair \"") == 2
    assert "No terminal to confirm" not in source


def test_coverage_verifier_runs_on_every_plan():
    # S3.4-TR2: single-pass or phased. It used to run only for phased plans.
    source = PLAN.read_text()
    gate = source[source.index("# ── Coverage verification gate"):]
    gate = gate[:gate.index("# ── Validation gate")]
    assert 'audit_sizing_rec" == "split" ]] || [[ "${FORCE_COVERAGE' not in gate
    assert 'if [[ "${SKIP_COVERAGE:-}" != "true" ]]; then\n    _run_coverage_check' in gate
