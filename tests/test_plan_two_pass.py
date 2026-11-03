"""Two-pass planning: an Opus skeleton, a gate on it, then Sonnet enrichment.

One Architect call wrote every criterion, spec reference and contract entry at
planning-model rates, and the decomposition gate only saw the plan after all of
that was paid for. The skeleton pass decides boundaries, files and dependencies;
the gate checks them; the support model fills in the rest. Audits and coverage
verdicts of unchanged inputs are reused instead of re-run on every plan.
"""

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "lib"
PLAN = LIB / "cmd" / "plan.sh"


def _funcs(*names: str) -> str:
    return "; ".join(f"eval \"$(sed -n '/^{n}()/,/^}}/p' '{PLAN}' | tr -d '\\r')\"" for n in names)


def _bash(script: str, env_extra: dict | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess:
    env = {"PATH": os.environ["PATH"], "NO_COLOR": "1", **(env_extra or {})}
    prelude = f'source "{LIB}/colors.sh"; source "{LIB}/log.sh"; '
    return subprocess.run(["bash", "-c", prelude + script], check=False, capture_output=True, text=True, encoding="utf-8",
                          env=env, cwd=cwd, timeout=60)


SKELETON = {
    "tasks": [
        {"id": "1", "title": "Model", "description": "Add Book in src/book.py", "files_touched": ["src/book.py"],
         "depends_on": [], "agent_model": "sonnet"},
        {"id": "2", "title": "Service", "description": "borrow_book() in src/borrow.py",
         "files_touched": ["src/borrow.py"], "depends_on": ["1"], "agent_model": "sonnet"},
    ],
    "validation": [],
    "cross_cutting_concerns": ["IDs are UUIDv7"],
}


def _enrichment(ids: list[str], files_override: bool = False) -> dict:
    tasks = []
    for i in ids:
        t = {"id": i, "acceptance_criteria": [{"criterion": f"c{i}", "verify_by": "test"}],
             "spec_references": [{"spec": "tech", "section": "S", "requirement": "r"}],
             "rationale": f"why {i}", "assumptions": []}
        if files_override:
            t["files_touched"] = ["src/elsewhere.py"]
        tasks.append(t)
    return {"tasks": tasks, "contract": {"core_question": "q", "entities": [
        {"name": f"e{i}", "type": "file", "path": "src/book.py", "created_by_task": i, "key_fields": []} for i in ids],
        "relationships": [], "core_queries": []}}


def _enrich(tmp_path: Path, responses: list[dict]) -> subprocess.CompletedProcess:
    for n, r in enumerate(responses):
        (tmp_path / f"resp{n}.json").write_text(json.dumps(r))
    script = (
        _funcs("_plan_enrich_skeleton") + "; "
        'AGENTS_DIR=/a; TEMPLATES_DIR=/t; MODEL_SUPPORT=sonnet; '
        'plan_spec_paths=(specs/tech/x.md); plan_spec_contents=("spec body"); plan_spec_labels=("Tech Spec"); '
        f'_run_architect_phase() {{ n=$(cat "{tmp_path}/n" 2>/dev/null || echo 0); echo $((n+1)) > "{tmp_path}/n"; '
        f'printf "%s\\n" "$2" > "{tmp_path}/msg$n"; printf "%s\\n" "$4 $5" > "{tmp_path}/args$n"; cat "{tmp_path}/resp$n.json"; }}; '
        f"parsed_architect='{json.dumps(SKELETON)}'; "
        '_plan_enrich_skeleton; echo "RESULT=$(echo "$parsed_architect" | jq -c .)"'
    )
    return _bash(script)


def _result(r: subprocess.CompletedProcess) -> dict:
    line = next(ln for ln in r.stdout.splitlines() if ln.startswith("RESULT="))
    return json.loads(line[len("RESULT="):])


def test_enrichment_merges_without_changing_the_skeleton(tmp_path):
    r = _enrich(tmp_path, [_enrichment(["1", "2"], files_override=True)])
    assert r.returncode == 0, r.stdout + r.stderr
    plan = _result(r)
    t1, t2 = plan["tasks"]
    assert t1["acceptance_criteria"] == [{"criterion": "c1", "verify_by": "test"}]
    assert t2["rationale"] == "why 2"
    # Boundaries are the skeleton's: enrichment cannot move files or edges
    assert t1["files_touched"] == ["src/book.py"] and t2["depends_on"] == ["1"]
    assert [e["created_by_task"] for e in plan["contract"]["entities"]] == ["1", "2"]
    assert plan["cross_cutting_concerns"] == ["IDs are UUIDv7"]
    # The support model and the enrich schema were used
    assert "architect-enrich-output.json sonnet" in (tmp_path / "args0").read_text()


def test_skipped_tasks_get_one_retry_with_only_those_tasks(tmp_path):
    r = _enrich(tmp_path, [_enrichment(["1"]), _enrichment(["2"])])
    assert r.returncode == 0, r.stdout + r.stderr
    retry_msg = (tmp_path / "msg1").read_text()
    assert '"id":"2"' in retry_msg and '"id":"1"' not in retry_msg
    plan = _result(r)
    assert all(t["acceptance_criteria"] for t in plan["tasks"])
    assert len(plan["contract"]["entities"]) == 2


def test_plan_stops_when_a_task_stays_unenriched(tmp_path):
    r = _enrich(tmp_path, [_enrichment(["1"]), _enrichment(["1"])])
    assert r.returncode == 1
    assert "without acceptance criteria: 2" in r.stdout + r.stderr


def _gate(tmp_path: Path, results: list[dict], skip: bool = False, skel: dict = SKELETON) -> subprocess.CompletedProcess:
    for n, r in enumerate(results):
        (tmp_path / f"gate{n}.json").write_text(json.dumps(r))
    logs = tmp_path / "logs"
    logs.mkdir(exist_ok=True)
    script = (
        _funcs("_plan_task_depends_on", "_plan_decomposition_gate", "_plan_gate_skeleton") + "; "
        f'LOGS_DIR="{logs}"; '
        f'context_decomposition_gate() {{ n=$(cat "{tmp_path}/gn" 2>/dev/null || echo 0); echo $((n+1)) > "{tmp_path}/gn"; '
        f'cat "{tmp_path}/gate$n.json"; }}; '
        f"parsed_architect='{json.dumps(skel)}'; "
        '_plan_gate_skeleton; echo "RESULT=$(echo "$parsed_architect" | jq -c .)"'
    )
    return _bash(script, {"SKIP_DECOMP": "true"} if skip else None)


BRIDGE_FAIL = {"overall": "fail", "file_ownership": {"violations": []}, "warnings": [],
               "per_task": [{"task_id": "1", "checks": [{"check": "bridge_symbols", "verdict": "fail",
                                                         "missing_dependencies": [{"affected_task": "2",
                                                                                   "affected_files": []}]}]}]}


def test_skeleton_gate_patches_edges_back_into_the_plan(tmp_path):
    # Task 1 changes a bridge symbol that task 2's files use, and 2 has no edge yet
    skel = json.loads(json.dumps(SKELETON))
    skel["tasks"][1]["depends_on"] = []
    r = _gate(tmp_path, [BRIDGE_FAIL, {"overall": "pass", "file_ownership": {"violations": []}}], skel=skel)
    assert r.returncode == 0, r.stdout + r.stderr
    plan = _result(r)
    assert plan["tasks"][1]["depends_on"] == ["1"]
    assert plan["tasks"][0]["description"] == "Add Book in src/book.py"
    assert "Decomposition quality gate passed" in r.stdout


def test_failing_skeleton_stops_before_enrichment(tmp_path):
    fail = {"overall": "fail", "warnings": [], "per_task": [],
            "file_ownership": {"violations": ["src/book.py: tasks 1 and 2 run in parallel"]}}
    r = _gate(tmp_path, [fail])
    assert r.returncode == 1
    assert "FAILED on the skeleton" in r.stdout + r.stderr
    assert (tmp_path / "logs" / "architect-skeleton-rejected.json").exists()
    assert (tmp_path / "logs" / "decomposition-gate.json").exists()


def test_skip_decomp_skips_the_skeleton_gate(tmp_path):
    r = _gate(tmp_path, [], skip=True)
    assert r.returncode == 0 and not (tmp_path / "gn").exists()


def _audit_key(root: Path) -> str:
    script = _funcs("_plan_audit_cache_key") + "; _plan_audit_cache_key \"$PROJECT_ROOT/specs/tech/x.md\""
    env = {"PROJECT_ROOT": str(root), "AGENTS_DIR": str(root / "agents"), "TEMPLATES_DIR": str(root / "t"),
           "VISION_FILE": "specs/product/overview.md", "MODEL_SUPPORT": "sonnet"}
    return _bash(script, env).stdout.strip()


def test_audit_key_tracks_the_spec_its_links_and_the_prompt(tmp_path):
    (tmp_path / "specs" / "tech").mkdir(parents=True)
    (tmp_path / "specs" / "product").mkdir(parents=True)
    (tmp_path / "agents").mkdir()
    (tmp_path / "agents" / "audit.md").write_text("audit prompt")
    (tmp_path / "specs" / "tech" / "x.md").write_text("# X")
    (tmp_path / "specs" / "product" / "x.md").write_text("# PRD")
    base = _audit_key(tmp_path)
    assert base and base == _audit_key(tmp_path)

    (tmp_path / "specs" / "product" / "x.md").write_text("# PRD v2")
    linked = _audit_key(tmp_path)
    assert linked != base

    (tmp_path / "agents" / "audit.md").write_text("audit prompt v2")
    assert _audit_key(tmp_path) != linked


def test_coverage_verdict_is_reused_for_an_unchanged_plan(tmp_path):
    (tmp_path / "agents").mkdir()
    (tmp_path / "agents" / "coverage-verifier.md").write_text("cov")
    verdict = {"coverage": "complete", "gaps": [], "summary": "ok"}
    script = (
        _funcs("_plan_cache_dir", "_plan_cache_valid", "_plan_cache_write", "_plan_cache_read",
               "_run_coverage_check", "_plan_coverage_evaluate") + "; "
        f'FEATURE_DIR="{tmp_path}"; AGENTS_DIR="{tmp_path}/agents"; LOGS_DIR="{tmp_path}"; spec_hash=abc; '
        'tech_spec_content=spec; product_spec_content=""; design_spec_content=""; '
        f'provider_run_json() {{ echo call >> "{tmp_path}/calls"; echo \'{json.dumps(verdict)}\'; }}; '
        'parse_agent_json() { echo "$1"; }; '
        'parsed_architect=\'{"tasks":[{"id":"1","title":"t","description":"d","acceptance_criteria":"- a"}]}\'; '
        '_run_coverage_check; _run_coverage_check; echo "status=$_cov_status"; '
        'parsed_architect=\'{"tasks":[{"id":"1","title":"t2","description":"d","acceptance_criteria":"- a"}]}\'; '
        '_run_coverage_check'
    )
    r = _bash(script)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "status=complete" in r.stdout
    # Run 2 was cached; run 3 changed a task and ran again
    assert (tmp_path / "calls").read_text().count("call") == 2
    assert "Coverage: cached" in r.stdout


def test_architect_cache_key_depends_on_the_planning_mode():
    source = PLAN.read_text(encoding="utf-8")
    key = source[source.index("architect_cache_hash=$({"):][:900]
    assert "$arch_mode" in key
    assert "architect-skeleton.md" in key and "architect-enrich.md" in key and "architect.md" in key


def test_stable_context_leads_every_architect_message():
    source = PLAN.read_text(encoding="utf-8")
    assert 'local base_message="$stable_context"' in source
    assert 'local phase1_message="$stable_context"' in source
    assert 'local phase2_message="$stable_context"' in source


def test_skeleton_task_details_leave_out_the_empty_criteria_block():
    script = _funcs("_plan_task_details") + f" ; _plan_task_details '{json.dumps(SKELETON['tasks'])}'"
    out = _bash(script).stdout
    assert "#### Task 2: Service" in out and "Depends on: [1]" in out
    assert "Acceptance criteria" not in out


def test_task_criteria_render_structured_and_legacy():
    script = (f'source "{LIB}/tasks.sh"; '
              """echo '{"acceptance_criteria":[{"criterion":"a","verify_by":"test"},"b"]}' | jq -r "$TASK_CRITERIA_JQ"; """
              """echo '{"acceptance_criteria":"- legacy"}' | jq -r "$TASK_CRITERIA_JQ\"""")
    out = _bash(script).stdout
    assert "- a (verify: test)\n- b\n- legacy" in out


def test_shell_readers_use_the_shared_criteria_renderer():
    for rel in ("lib/cmd/run.sh", "lib/cmd/review.sh", "lib/cmd/verify.sh"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "jq -r '.acceptance_criteria'" not in text, rel
        assert "TASK_CRITERIA_JQ" in text, rel


def test_one_call_schema_matches_the_prompt():
    schema = json.loads((ROOT / "templates" / "architect-output.json").read_text(encoding="utf-8"))
    task = schema["properties"]["tasks"]["items"]["properties"]
    assert task["acceptance_criteria"]["type"] == "array"
    assert task["acceptance_criteria"]["items"]["required"] == ["criterion", "verify_by"]
    assert {"spec_references", "rationale", "assumptions"} <= set(task)
    # additionalProperties is false at the top: the prompt's cross_cutting_concerns must be allowed
    assert "cross_cutting_concerns" in schema["properties"]
