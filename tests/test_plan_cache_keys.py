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
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env).stdout.strip()


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
