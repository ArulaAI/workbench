"""verify's Fix Agent keeps task files and the contract consistent.

The Fix Agent only received task files. It removed a behaviour from a task but the
contract still required it, so the verifier failed again on the stale contract.
The Architect also kept planning work the spec lists as an Unresolved Question.
"""

import json
import subprocess
from pathlib import Path

SPEED_DIR = Path(__file__).resolve().parent.parent
LIB = SPEED_DIR / "lib"
VERIFY = LIB / "cmd" / "verify.sh"
ENV = {"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", "NO_COLOR": "1"}


def _run(fn: str, script: str, **env) -> subprocess.CompletedProcess:
    load = (f'source "{LIB}/colors.sh"; source "{LIB}/log.sh"; '
            f"eval \"$(sed -n '/^{fn}()/,/^}}/p' '{VERIFY}')\"; ")
    return subprocess.run(["bash", "-c", load + script], capture_output=True, text=True,
                          env=dict(ENV, **env))


def test_fix_agent_receives_tasks_and_contract(tmp_path):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "1.json").write_text('{"id": "1"}')
    contract = tmp_path / "contract.json"
    contract.write_text('{"entities": ["capture rejects voided"]}')
    r = _run("_verify_fix_files_content", "_verify_fix_files_content",
             TASKS_DIR=str(tasks), CONTRACT_FILE=str(contract))
    assert f"--- FILE: {tasks / '1.json'} ---" in r.stdout
    assert f"--- FILE: {contract} (contract) ---" in r.stdout
    assert "capture rejects voided" in r.stdout


def test_fix_agent_is_told_to_update_the_contract_with_the_tasks():
    source = VERIFY.read_text()
    assert "update the matching contract entry in the same pass" in source
    assert source.count("task_files_content=$(_verify_fix_files_content)") == 2


def _restore(tmp_path, edits: dict) -> subprocess.CompletedProcess:
    """Snapshot task files and contract, apply the Fix Agent's edits, restore."""
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "1.json").write_text('{"id": "1", "title": "old"}')
    (tasks / "2.json").write_text('{"id": "2"}')
    contract = tmp_path / "contract.json"
    contract.write_text('{"ok": true}')
    edits_sh = "; ".join(f"printf %s {json.dumps(v)} > '{tasks if k != 'contract' else tmp_path}/{k if k != 'contract' else 'contract'}.json'"
                         for k, v in edits.items())
    load = (f'source "{LIB}/colors.sh"; source "{LIB}/log.sh"; '
            f"eval \"$(sed -n '/^_verify_snapshot_plan_files()/,/^}}/p' '{VERIFY}')\"; "
            f"eval \"$(sed -n '/^_verify_restore_invalid_files()/,/^}}/p' '{VERIFY}')\"; ")
    script = load + 'snap=$(_verify_snapshot_plan_files); ' + edits_sh + '; _verify_restore_invalid_files "$snap"'
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                          env=dict(ENV, TASKS_DIR=str(tasks), CONTRACT_FILE=str(contract)))


def test_invalid_task_file_left_by_fix_agent_is_restored(tmp_path):
    # The Fix Agent wrote a task file with a raw control character; the next jq call
    # ended verify with jq's exit code 5, which reads as "halted".
    r = _restore(tmp_path, {"1": '{"id": "1", "title": "new"}', "2": '{"id": "2", "d": "a\u0001b'})
    assert json.loads((tmp_path / "tasks/1.json").read_text())["title"] == "new"  # valid edit kept
    assert json.loads((tmp_path / "tasks/2.json").read_text()) == {"id": "2"}       # invalid one restored
    assert "Fix Agent left 2.json invalid" in r.stderr


def test_invalid_contract_left_by_fix_agent_is_restored(tmp_path):
    r = _restore(tmp_path, {"contract": "{not json"})
    assert json.loads((tmp_path / "contract.json").read_text()) == {"ok": True}
    assert "restored the previous version" in r.stderr


def test_valid_contract_edit_is_kept(tmp_path):
    _restore(tmp_path, {"contract": '{"new": true}'})
    assert json.loads((tmp_path / "contract.json").read_text()) == {"new": True}


def test_architect_prompts_leave_unresolved_questions_unplanned():
    for name in ("architect.md", "architect-skeleton.md", "architect-enrich.md"):
        text = (SPEED_DIR / "agents" / name).read_text()
        assert "Unresolved Questions" in text, name


def test_fix_agent_may_use_the_edit_tool():
    # The Fix Agent was allowed Read, Write and Glob only. When it chose Edit, as it
    # often does, every change was denied and verification reported no fixes.
    config = (LIB / "config.sh").read_text()
    tools = config.split('AGENT_TOOLS_WRITE="', 1)[1].split('"', 1)[0].split()
    assert {"Read", "Write", "Edit"} <= set(tools)
    assert "Bash" not in tools
    assert "Edit or Write tool" in VERIFY.read_text()
