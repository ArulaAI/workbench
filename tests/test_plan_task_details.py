"""Phase 2 and coverage repair see each earlier task's full design.

Phase 2 received only the first line of each Phase 1 description, cut to 120
characters, and coverage repair only ids, titles and files. Later tasks were
written against the spec's interfaces while Phase 1 had designed different ones,
so speed verify found tasks that could not compile together.
"""

import json
import subprocess
from pathlib import Path

LIB = Path(__file__).resolve().parent.parent / "lib"
PLAN = LIB / "cmd" / "plan.sh"


def _details(tasks: list[dict]) -> str:
    script = (f"eval \"$(sed -n '/^_plan_task_details()/,/^}}/p' '{PLAN}')\"; "
              '_plan_task_details "$TASKS"')
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                          env={"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
                               "TASKS": json.dumps(tasks)}).stdout


LONG = "First line.\n" + "Capture is held through an injected captureHold predicate. " * 5


def test_full_description_and_object_criteria():
    out = _details([{"id": "7", "title": "Capture hold", "description": LONG, "depends_on": [1],
                     "files_touched": ["src/payments/service.ts"],
                     "acceptance_criteria": [{"criterion": "capture throws capture_held", "verify_by": "test"}]}])
    assert "#### Task 7: Capture hold" in out
    assert "Depends on: [1]" in out and "src/payments/service.ts" in out
    assert LONG.strip() in out
    assert "- capture throws capture_held" in out


def test_string_criteria_are_kept():
    out = _details([{"id": "2", "title": "T", "description": "d",
                     "acceptance_criteria": "- [test] a\n- [test] b"}])
    assert "- [test] a\n- [test] b" in out


def test_phase2_and_repair_use_the_full_details():
    source = PLAN.read_text()
    assert 'phase1_summary=$(_plan_task_details "$phase1_tasks")' in source
    assert "cut -c1-120" not in source
    assert "task_summary=$(_plan_task_details" in source
