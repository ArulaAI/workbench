"""Commands judge the model's answer, not the exit code of the agent CLI.

A fake agent CLI (CLAUDE_BIN) returns canned responses, so these run without a
model. Found by this suite: a verdict without a status was reported as success
by validate (exit 0), verify (exit 0, "Next: speed run") and audit (exit 0); a
"pass" that listed critical gaps or failures was believed.
"""

import json
import stat
import subprocess
from pathlib import Path

SPEED = Path(__file__).resolve().parent.parent / "speed"
BASE_ENV = {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin", "NO_COLOR": "1", "HOME": "/tmp",
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}

FAKE_AGENT = """#!/bin/bash
cat > /dev/null 2>&1 || true
printf '%s\\n' "$FAKE_EVENT"
"""

RFC = "# RFC\n\n## Summary\nx\n\n## Data Model\ny\n"


def _project(tmp_path: Path) -> tuple[Path, dict]:
    repo = tmp_path / "proj"
    for d in ("specs/product", "specs/tech"):
        (repo / d).mkdir(parents=True)
    (repo / "specs/product/overview.md").write_text("# Vision\n\nAsk before refusing.\n")
    (repo / "specs/product/x.md").write_text("# PRD\n")
    (repo / "specs/tech/x.md").write_text(RFC)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True, env=BASE_ENV)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, env=BASE_ENV)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True, env=BASE_ENV)
    fake = tmp_path / "fake-claude"
    fake.write_text(FAKE_AGENT)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    return repo, dict(BASE_ENV, CLAUDE_BIN=str(fake))


def _event(text: str) -> str:
    # Compact, as the real CLI writes it: the provider looks for "type":"result".
    return json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": text,
                       "num_turns": 1, "duration_ms": 1, "total_cost_usd": 0}, separators=(",", ":"))


def _speed(repo: Path, env: dict, answer, *args) -> subprocess.CompletedProcess:
    text = answer if isinstance(answer, str) else json.dumps(answer)
    return subprocess.run([str(SPEED), *args], check=False, cwd=repo, capture_output=True, text=True,
                          env=dict(env, FAKE_EVENT=_event(text)), timeout=180)


def _out(r: subprocess.CompletedProcess) -> str:
    return r.stdout + r.stderr


# ── validate ──────────────────────────────────────────────────────

def test_validate_pass_and_fail(tmp_path):
    repo, env = _project(tmp_path)
    assert _speed(repo, env, {"status": "pass", "summary": "ok", "critical_gaps": [], "warnings": []},
                  "validate", "specs").returncode == 0
    r = _speed(repo, env, {"status": "fail", "summary": "gap", "warnings": [],
                           "critical_gaps": [{"source_spec": "specs/tech/x.md", "description": "Missing X."}]},
               "validate", "specs")
    assert r.returncode == 1 and "Validation FAILED" in _out(r) and "Missing X." in _out(r)


def test_validate_accepts_a_fenced_verdict(tmp_path):
    repo, env = _project(tmp_path)
    fenced = "```json\n" + json.dumps({"status": "pass", "critical_gaps": [], "warnings": []}) + "\n```"
    assert _speed(repo, env, fenced, "validate", "specs").returncode == 0


def test_validate_without_a_verdict_is_not_a_pass(tmp_path):
    repo, env = _project(tmp_path)
    r = _speed(repo, env, {"summary": "looked fine", "critical_gaps": []}, "validate", "specs")
    assert r.returncode == 1, _out(r)
    assert "no pass or fail verdict" in _out(r) and "Validation PASSED" not in _out(r)


def test_validate_pass_with_critical_gaps_is_a_failure(tmp_path):
    repo, env = _project(tmp_path)
    r = _speed(repo, env, {"status": "pass", "warnings": [],
                           "critical_gaps": [{"source_spec": "specs/tech/x.md", "description": "Real gap."}]},
               "validate", "specs")
    assert r.returncode == 1 and "Validation PASSED" not in _out(r)


def test_validate_agent_failure_text_is_reported(tmp_path):
    repo, env = _project(tmp_path)
    r = _speed(repo, env, "There's an issue with the selected model (x).", "validate", "specs")
    assert r.returncode == 1 and "The agent said: There's an issue with the selected model" in _out(r)


# ── audit ─────────────────────────────────────────────────────────

def _audit(status: str | None) -> dict:
    a = {"spec_type": "rfc", "spec_file": "specs/tech/x.md", "issues": [], "summary": "s"}
    if status:
        a["status"] = status
    if status == "fail":
        a["issues"] = [{"level": 1, "severity": "error", "section": "Testing", "message": "Missing section."}]
    return a


def test_audit_verdicts_map_to_exit_codes(tmp_path):
    repo, env = _project(tmp_path)
    assert _speed(repo, env, _audit("pass"), "audit", "specs/tech/x.md").returncode == 0
    assert _speed(repo, env, _audit("warn"), "audit", "specs/tech/x.md").returncode == 0
    assert _speed(repo, env, _audit("fail"), "audit", "specs/tech/x.md").returncode == 2


def test_audit_without_a_verdict_does_not_pass(tmp_path):
    repo, env = _project(tmp_path)
    r = _speed(repo, env, _audit(None), "audit", "specs/tech/x.md")
    assert r.returncode == 1 and "did not complete" in _out(r)
    r = _speed(repo, env, "not json at all", "audit", "specs/tech/x.md")
    assert r.returncode == 1 and "The agent said: not json at all" in _out(r)


# ── guardian ──────────────────────────────────────────────────────

def _verdict(status: str, severity: str = "warning") -> dict:
    return {"status": status, "summary": f"{status} summary",
            "flags": [] if status == "aligned" else
            [{"severity": severity, "description": "Concern.", "vision_reference": "Ask before refusing."}]}


def test_guardian_verdicts_map_to_exit_codes(tmp_path):
    repo, env = _project(tmp_path)
    assert _speed(repo, env, _verdict("aligned"), "guardian", "specs/tech/x.md").returncode == 0
    flagged = _speed(repo, env, _verdict("flagged"), "guardian", "specs/tech/x.md")
    assert flagged.returncode == 2 and "Concern." in _out(flagged) and '"status"' not in _out(flagged)
    rejected = _speed(repo, env, _verdict("rejected", "critical"), "guardian", "specs/tech/x.md")
    assert rejected.returncode == 1 and "REJECTED" in _out(rejected)
    assert _speed(repo, env, "garbage", "guardian", "specs/tech/x.md").returncode == 3


# ── verify ────────────────────────────────────────────────────────

def _planned(repo: Path) -> None:
    feat = repo / ".speed/features/x"
    (feat / "tasks").mkdir(parents=True)
    (feat / "tasks/1.json").write_text(json.dumps({
        "id": "1", "title": "Build X", "description": "d", "acceptance_criteria": "- [test] x",
        "status": "pending", "depends_on": [], "files_touched": ["src/x.ts"]}))
    (feat / "spec_path").write_text(str(repo / "specs/tech/x.md") + "\n")
    (repo / ".speed/active_feature").write_text("x\n")


def _verify_answer(status: str | None, failures: int = 0) -> dict:
    v = {"core_question": "answerable", "spec_requirements": [], "critical_failures": [
        {"description": f"Gap {i}.", "spec_says": "s", "plan_says": "p"} for i in range(failures)],
        "warnings": [], "recommendations": [], "summary": "s"}
    if status:
        v["status"] = status
    return v


def test_verify_pass(tmp_path):
    repo, env = _project(tmp_path)
    _planned(repo)
    r = _speed(repo, env, _verify_answer("pass"), "verify")
    assert r.returncode == 0 and "Plan verification PASSED" in _out(r), _out(r)


def test_verify_without_a_verdict_is_not_a_pass(tmp_path):
    repo, env = _project(tmp_path)
    _planned(repo)
    r = _speed(repo, env, _verify_answer(None), "verify")
    assert r.returncode == 1 and "no pass or fail verdict" in _out(r)
    assert "PASSED" not in _out(r) and "Next:" not in _out(r)


def test_verify_pass_with_critical_failures_is_a_failure(tmp_path):
    repo, env = _project(tmp_path)
    _planned(repo)
    r = _speed(repo, env, _verify_answer("pass", failures=1), "verify")
    assert r.returncode != 0 and "Plan verification PASSED" not in _out(r), _out(r)
