"""plan finds File Impact files that no task owns, without an AI call."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.file_impact import file_impact_paths, unowned_paths

BULLETS = """## File Impact

- `src/domain/money.ts`: the only module; `minor`, `Ledger.post`, `applyRate`.
- `test/money.test.ts`, `test/ledger.test.ts` and `test/fixtures/cards.ts`.
- `workbench/commands/invariant.ts`, `property.ts`, `mutation.ts` and `differential.ts`.

## Unresolved Questions

- `src/other.ts` is mentioned here, not in File Impact.
"""

TABLE = """## File Impact

| File | Change |
|---|---|
| `src/risk/rules.ts` | Rule behind the shadow flag |
| `src/risk/scoring.ts` (new) | `Scorer`, `ScoringInput` |
"""


def test_bullets_with_bare_names_take_the_line_directory():
    assert file_impact_paths(BULLETS) == [
        "src/domain/money.ts", "test/money.test.ts", "test/ledger.test.ts", "test/fixtures/cards.ts",
        "workbench/commands/invariant.ts", "workbench/commands/property.ts",
        "workbench/commands/mutation.ts", "workbench/commands/differential.ts",
    ]


def test_symbols_and_other_sections_are_ignored():
    paths = file_impact_paths(BULLETS)
    assert "Ledger.post" not in paths and "src/other.ts" not in paths


def test_table_rows():
    assert file_impact_paths(TABLE) == ["src/risk/rules.ts", "src/risk/scoring.ts"]


def test_unowned_paths_compare_with_files_touched():
    tasks = [{"files_touched": ["src/risk/rules.ts"]}, {"files_touched": ["./src/risk/scoring.ts"]}]
    assert unowned_paths(TABLE, tasks) == []
    assert unowned_paths(TABLE, [{"files_touched": ["src/risk/rules.ts"]}]) == ["src/risk/scoring.ts"]


def test_every_tech_spec_in_a_feature_bundle_is_read():
    bundle = "## Tech Spec: a.md\n\n" + TABLE + "\n## Tech Spec: b.md\n\n## File Impact\n\n- `src/b.ts`\n"
    assert file_impact_paths(bundle)[-1] == "src/b.ts"


def test_plan_checks_file_impact_before_creating_tasks():
    source = (Path(__file__).resolve().parent.parent / "lib" / "cmd" / "plan.sh").read_text()
    check = source.index("_unowned=$(_plan_unowned_file_impact)")
    assert check < source.index("# ── Coverage verification gate")
    assert check < source.index('log_step "Creating ${task_count} tasks..."') if 'log_step "Creating ${task_count} tasks..."' in source else True
    assert "_repair_coverage_gaps" in source[check:check + 1500]


def test_bare_name_without_a_directory_on_the_line_is_ignored():
    # `x.ts` alone could be anywhere; guessing would invent an unowned file.
    assert file_impact_paths("## File Impact\n\n- `helpers.ts` and `src/a.ts`\n") == ["src/a.ts"]


def test_command_line_entry_point_used_by_plan(tmp_path):
    import json
    import subprocess
    spec = tmp_path / "spec.md"
    spec.write_text(TABLE)
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"tasks": [{"files_touched": ["src/risk/rules.ts"]}]}))
    lib = Path(__file__).resolve().parent.parent / "lib" / "file_impact.py"
    r = subprocess.run(["python3", str(lib), str(spec), str(plan)], check=False, capture_output=True, text=True)
    assert r.returncode == 0 and json.loads(r.stdout) == ["src/risk/scoring.ts"]
