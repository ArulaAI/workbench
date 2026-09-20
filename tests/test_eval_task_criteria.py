"""Task-derived plans: the catalog exists before task IDs and stays unchanged."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_eval_regressions import project, result, PYTEST
from lib.eval_criteria import normalize_criteria
from lib.eval_discovery import discover_tests


def task(owner, ids, files=None, form="list"):
    criteria = [{"criterion": f"[{sid}] Behavior {sid}", "verify_by": "test"} for sid in ids]
    if form == "text":
        criteria = "\n".join(f"- {c['criterion']}\n  verify_by: test" for c in criteria)
    elif form == "json":
        criteria = json.dumps(criteria)
    return dict(id=owner, status="done", files_touched=files or ['tests/test_books.py'], acceptance_criteria=criteria)


def catalog(project, ids, tasks):
    project.spec.write_text('# Tests, authored before planning\n## Scenario Catalog\n'
        '| ID | Scenario | Level | Expected outcome |\n|---|---|---|---|\n' +
        ''.join(f'| {sid} | Behavior {sid} | unit | Correct behavior |\n' for sid in ids) +
        '\n## Acceptance Traceability\n| RFC acceptance criterion | Covering scenarios |\n|---|---|\n' +
        ''.join(f'| Requirement {sid} | {sid} |\n' for sid in ids))
    for p in project.tasks.glob('*.json'):
        p.unlink()
    for t in tasks:
        (project.tasks / (t['id'] + '.json')).write_text(json.dumps(t))
    project.commit()


def five_python_tests(project):
    (project.root/'tests/test_books.py').write_text('from pathlib import Path\n'
        'def record(v):\n    with Path(".speed/executed").open("a") as f: f.write(v)\n' +
        ''.join(f'def test_ac_0{i}_behavior():\n    record("{i}")\n    assert {i} != 2\n' for i in range(1,6)))


@pytest.mark.parametrize('form', ['list', 'text', 'json'])
def test_only_third_and_fourth_run_despite_failing_second(project, form):
    five_python_tests(project)
    catalog(project, [f'AC-0{i}' for i in range(1,6)],
            [task('1',['AC-03','AC-04'],form=form), task('2',['AC-01','AC-02','AC-05'])])
    before = {p:p.read_bytes() for p in [project.spec,*project.tasks.glob('*.json')]}
    run, report = project.evaluate(task_id='1')
    assert report['accepted'],report
    assert (project.root/'.speed/executed').read_text() == '34'
    plan=json.loads((run/'test-plan.json').read_text())
    assert plan['selection']['source']=='task_criteria'
    assert [c['selector'] for c in plan['test_cases']]==['tests/test_books.py::test_ac_03_behavior','tests/test_books.py::test_ac_04_behavior']
    assert len(list((run/'commands').iterdir()))==2
    assert before=={p:p.read_bytes() for p in before}
    (project.root/'.speed/executed').unlink()
    _,feature=project.evaluate()
    assert not feature['accepted']
    assert result(feature,'AC-02')['status']=='fail'
    assert result(feature,'AC-03')['status']==result(feature,'AC-04')['status']=='pass'
    assert sorted((project.root/'.speed/executed').read_text())==list('12345')


def test_multiple_files_and_multiple_tests_for_one_scenario(project):
    (project.root/'tests/test_books.py').write_text('def test_ac_01_first(): pass\ndef test_ac_01_second(): pass\ndef test_ac_010_unrelated(): assert False\n')
    (project.root/'tests/test_second.py').write_text('def test_ac_01_third(): pass\n')
    catalog(project,['AC-01'],[task('1',['AC-01'],['tests/test_books.py','tests/test_second.py'])])
    run,report=project.evaluate(task_id='1')
    assert report['accepted'],report
    assert len(list((run/'commands').iterdir()))==3
    assert len(result(report)['executions'])==3


@pytest.mark.parametrize('scope',[None,'1'])
def test_missing_test_cannot_be_hidden_by_other_passing_test(project,scope):
    (project.root/'tests/test_books.py').write_text('def test_ac_01_present(): pass\n')
    catalog(project,['AC-01','AC-02'],[task('1',['AC-01','AC-02'])])
    _,report=project.evaluate(task_id=scope)
    assert result(report)['status']=='pass'
    assert result(report,'AC-02')['status']=='unverifiable'
    assert result(report,'TASK-1-CRIT-02')['status']=='unverifiable'
    assert not report['accepted']


def test_catalog_scenario_omitted_by_planner_remains_feature_gap(project):
    (project.root/'tests/test_books.py').write_text('def test_ac_01_present(): pass\n')
    catalog(project,['AC-01','AC-02'],[task('1',['AC-01'])])
    assert project.evaluate(task_id='1')[1]['accepted']
    report=project.evaluate()[1]
    assert result(report,'AC-02')['status']=='unverifiable' and not report['accepted']


@pytest.mark.parametrize('scope',[None,'1'])
def test_missing_file_is_explicit_gap(project,scope):
    catalog(project,['AC-01'],[task('1',['AC-01'],['tests/test_missing.py'])])
    report=project.evaluate(task_id=scope)[1]
    assert not report['accepted']
    assert any('test_missing.py' in r['evidence'] for r in report['results'])


def test_shared_scenario_across_tasks_does_not_borrow_evidence(project):
    (project.root/'tests/test_books.py').write_text('def test_ac_01_present(): pass\n')
    (project.root/'tests/test_second.py').write_text('def test_unrelated(): assert False\n')
    catalog(project,['AC-01'],[task('1',['AC-01']),task('2',['AC-01'],['tests/test_second.py'])])
    report=project.evaluate()[1]
    assert result(report)['status']=='unverifiable'
    assert result(report,'TASK-1-CRIT-01')['status']=='pass'
    assert result(report,'TASK-2-CRIT-01')['status']=='unverifiable'
    assert project.evaluate(task_id='1')[1]['accepted']


def test_class_and_parameterized_python_tests(project):
    (project.root/'tests/test_books.py').write_text('import pytest\nclass TestAPI:\n'
        '    @pytest.mark.parametrize("value", [1,2], ids=["one", "two"])\n'
        '    def test_ac_01_positive(self,value): assert value>0\n'
        '    def test_ac_02_unrelated(self): assert False\n')
    catalog(project,['AC-01'],[task('1',['AC-01'])])
    run,report=project.evaluate(task_id='1')
    assert report['accepted'],report
    assert len(result(report)['executions'][0]['tests'])==2


def test_unknown_scenario_is_rejected_before_execution(project):
    catalog(project,['AC-01'],[task('1',['AC-99'])])
    with pytest.raises(ValueError,match='unknown scenarios'):
        project.evaluate(task_id='1')


def test_missing_criterion_id_is_reported(project):
    one=task('1',['AC-01'])
    one['acceptance_criteria'].append({'criterion':'Missing identifier','verify_by':'test'})
    (project.root/'tests/test_books.py').write_text('def test_ac_01_pass(): pass\n')
    catalog(project,['AC-01'],[one])
    report=project.evaluate(task_id='1')[1]
    assert not report['accepted']
    assert result(report,'TASK-1-CRIT-02')['status']=='unverifiable'


def test_task_ids_in_legacy_spec_do_not_override_tagged_criteria(project):
    (project.root/'tests/test_books.py').write_text('def test_ac_01_pass(): pass\ndef test_bad(): assert False\n')
    catalog(project,['AC-01'],[task('1',['AC-01'])])
    project.spec.write_text(project.spec.read_text()+'\n## Execution and Evidence\n'
        '| Scenario | Task | Selector |\n|---|---|---|\n| AC-01 | old-task-id | tests/test_books.py::test_bad |\n')
    project.commit()
    assert project.evaluate(task_id='1')[1]['accepted']


def test_actual_task_create_string_roundtrip(project):
    criteria=json.dumps(task('1',['AC-01'])['acceptance_criteria'])
    script='source "$1/lib/tasks.sh"; TASKS_DIR="$2"; BRANCH_PREFIX=speed/books; task_create 1 title description "$3" "[]" sonnet'
    subprocess.run(['bash','-c',script,'test',str(Path(__file__).resolve().parents[1]),str(project.tasks),criteria],check=True,capture_output=True)
    saved=json.loads((project.tasks/'1.json').read_text())
    assert isinstance(saved['acceptance_criteria'],str)
    assert normalize_criteria(saved['acceptance_criteria'])==task('1',['AC-01'])['acceptance_criteria']
    saved['status']='done';saved['files_touched']=['tests/test_books.py'];saved.pop('branch')
    (project.root/'tests/test_books.py').write_text('def test_ac_01_pass(): pass\n')
    catalog(project,['AC-01'],[saved])
    assert project.evaluate(task_id='1')[1]['accepted']


def js_available():
    pytest.importorskip('tree_sitter_javascript')


def test_js_discovery_ignores_comments_and_resolves_nested_titles(tmp_path):
    js_available()
    p=tmp_path/'test.cjs'
    p.write_text("// test('[AC-01] not real', () => {});\n"
                 "describe('API', () => { it('[AC-03] bad input?', () => {}); test.skip('[AC-04] skipped', () => {}); });")
    found=discover_tests(p,'node')
    assert [t['test_name'] for t in found]==['API [AC-03] bad input?','API [AC-04] skipped']


def test_node_third_fourth_only_and_selected_failure(project):
    js_available()
    node=shutil.which('node')
    if not node:pytest.skip('Node unavailable')
    p=project.root/'tests/service.test.cjs'
    p.write_text("const {test,describe}=require('node:test');const fs=require('node:fs');\n"
        "describe('API',()=>{\n" + ''.join(f"test('[AC-0{i}] behavior',()=>{{fs.appendFileSync('.speed/executed','{i}');if({i}===2)throw Error('failure');}});\n" for i in range(1,6)) + '});\n')
    (project.root/'speed.toml').write_text('[eval]\ntest_command = '+json.dumps(shlex.quote(node)+' --test')+'\n')
    catalog(project,[f'AC-0{i}' for i in range(1,6)],
        [task('1',['AC-03','AC-04'],['tests/service.test.cjs']),task('2',['AC-01','AC-02','AC-05'],['tests/service.test.cjs'])])
    run,report=project.evaluate(task_id='1')
    assert report['accepted'],report
    assert (project.root/'.speed/executed').read_text()=='34'
    assert len(list((run/'commands').iterdir()))==2
    report=project.evaluate(task_id='2')[1]
    assert result(report,'AC-02')['status']=='fail' and not report['accepted']


@pytest.mark.parametrize('runner',['vitest','jest'])
def test_frontend_runner_and_python_backend(project,runner):
    js_available()
    entry=os.environ.get('SPEED_TEST_'+runner.upper())
    if not entry:pytest.skip(f'Set SPEED_TEST_{runner.upper()} to an installed runner')
    python=os.environ.get('SPEED_TEST_PYTEST_PYTHON',sys.executable)
    node=shutil.which('node')
    frontend=shlex.quote(node)+' '+shlex.quote(entry)
    frontend+= ' run --globals --maxWorkers=1 --minWorkers=1' if runner=='vitest' else ' --runInBand --config='+shlex.quote('{"testEnvironment":"node"}')
    with (project.root/'.gitignore').open('a') as f:f.write('node_modules/\n')
    (project.root/'speed.toml').write_text('[eval]\ntest_commands = '+json.dumps([shlex.quote(python)+' -m pytest -q',frontend])+'\n')
    (project.root/'tests/test_books.py').write_text('def test_ac_01_backend(): pass\ndef test_ac_02_bad(): assert False\n')
    (project.root/'tests/form.test.js').write_text("test('[AC-01] frontend',()=>{expect(1).toBe(1)});test('[AC-02] other task',()=>{throw Error('unrelated')});")
    catalog(project,['AC-01','AC-02'],[task('1',['AC-01'],['tests/test_books.py','tests/form.test.js']),task('2',['AC-02'],['tests/test_books.py','tests/form.test.js'])])
    run,report=project.evaluate(task_id='1')
    assert report['accepted'],report
    assert len(list((run/'commands').iterdir()))==2


@pytest.mark.parametrize('body',[
    'import pytest\n@pytest.mark.skip(reason="unavailable")\ndef test_ac_01_case(): pass\n',
    'def test_ac_01_duplicate(): pass\ndef test_ac_01_duplicate(): pass\n',
    'def test_untagged(): pass\n',
])
def test_skipped_duplicate_and_untagged_tests_do_not_pass(project,body):
    (project.root/'tests/test_books.py').write_text(body)
    catalog(project,['AC-01'],[task('1',['AC-01'])])
    assert not project.evaluate(task_id='1')[1]['accepted']


def test_real_plan_persistence_catalog_input_and_cache_invalidation(project,tmp_path):
    repo=Path(__file__).resolve().parents[1]
    (project.root/'specs/tech').mkdir()
    tech=project.root/'specs/tech/books.md';tech.write_text('# Books implementation\n')
    (project.root/'tests/test_books.py').write_text('def test_ac_03_pass(): pass\ndef test_ac_04_pass(): pass\ndef test_ac_02_bad(): assert False\n')
    catalog(project,['AC-02','AC-03','AC-04'],[])
    reply=tmp_path/'reply.json'
    planned=task('9',['AC-03','AC-04']);planned.update(title='Late task ID',description='Implement selected behavior',depends_on=[],agent_model='sonnet')
    reply.write_text(json.dumps({'tasks':[planned],'contract':{},'validation':[]}))
    prompt=tmp_path/'prompt.txt'
    script='''set -euo pipefail
source "$1/lib/config.sh"
source "$1/lib/log.sh"
source "$1/lib/tasks.sh"
source "$1/lib/features.sh"
source "$1/lib/cmd/plan.sh"
MP_ENABLED=""
_context_python() { printf '%s' "$TEST_PYTHON"; }
_git() { git -C "$PROJECT_ROOT" "$@"; }
_run_guardian() { return 0; }
_log_gate_skip() { :; }
_prune_logs() { :; }
context_build_layer1() { echo '{"status":"built"}'; }
context_assemble_architect() { :; }
parse_agent_json() { printf '%s' "$1"; }
provider_run_json() {
    if [[ "$1" == *coverage-verifier.md ]]; then
        printf '%s' "$2" > "$TEST_PROMPT.coverage"
        echo '{"coverage":"complete","gaps":[]}'
    else
        printf '%s' "$2" > "$TEST_PROMPT"
        cat "$TEST_REPLY"
    fi
}
cmd_plan "$2" --skip-audit --single-pass
'''
    env={**os.environ,'SPEED_PROJECT_ROOT':str(project.root),'SKIP_DECOMP':'true','FORCE_COVERAGE':'true',
         'TEST_PYTHON':sys.executable,'TEST_PROMPT':str(prompt),'TEST_REPLY':str(reply)}
    before=project.spec.read_bytes()
    for attempt in range(2):
        if attempt:
            project.spec.write_text(project.spec.read_text()+'\nCatalog revision two\n')
            prompt.unlink()
        run=subprocess.run(['bash','-c',script,'test',str(repo),str(tech)],cwd=project.root,env=env,text=True,capture_output=True)
        assert run.returncode==0,run.stdout+run.stderr
        assert '[SCENARIO-ID]' in prompt.read_text() and 'AC-03' in prompt.read_text()
        assert '[AC-03]' in Path(str(prompt)+'.coverage').read_text()
        if attempt:assert 'Catalog revision two' in prompt.read_text()
        else:assert project.spec.read_bytes()==before
    saved=json.loads((project.tasks/'9.json').read_text())
    assert isinstance(saved['acceptance_criteria'],str)
    assert normalize_criteria(saved['acceptance_criteria'])==planned['acceptance_criteria']
    project.git('branch',saved['branch'])
    saved['status']='done';(project.tasks/'9.json').write_text(json.dumps(saved))
    project.commit()
    assert project.evaluate(task_id='9')[1]['accepted']


@pytest.mark.parametrize('body',[
    "test.skip('[AC-01] skipped',()=>{});",
    "test('[AC-01] duplicate',()=>{});test('[AC-01] duplicate',()=>{});",
    "const title='dynamic';describe(title,()=>{test('[AC-01] case',()=>{})});",
    "test.each([1,2])('[AC-01] case %s',()=>{});",
])
def test_js_skips_duplicates_and_dynamic_names_stay_unverified(project,body):
    js_available()
    node=shutil.which('node')
    if not node:pytest.skip('Node unavailable')
    p=project.root/'tests/service.test.cjs'
    p.write_text("const {test,describe}=require('node:test');"+body)
    (project.root/'speed.toml').write_text('[eval]\ntest_command = '+json.dumps(shlex.quote(node)+' --test')+'\n')
    catalog(project,['AC-01'],[task('1',['AC-01'],['tests/service.test.cjs'])])
    run,report=project.evaluate(task_id='1')
    assert not report['accepted']
    assert result(report)['status']=='unverifiable'


def test_discovery_does_not_execute_python_imports_or_test_bodies(project):
    from lib.eval_runtime import prepare
    (project.root/'tests/test_books.py').write_text('from pathlib import Path\nPath(".speed/imported").touch()\ndef test_ac_01_body(): raise RuntimeError("must not execute during prepare")\n')
    catalog(project,['AC-01'],[task('1',['AC-01'])])
    run=prepare(project.root,project.feature,project.state,project.spec,task_id='1')
    assert not (project.root/'.speed/imported').exists()
    assert not (run/'commands').exists()
    assert json.loads((run/'test-plan.json').read_text())['test_cases'][0]['selector'].endswith('::test_ac_01_body')


def test_task_discovery_routes_relative_selectors_under_cd(project):
    p=project.root/'backend/tests/test_api.py';p.parent.mkdir(parents=True)
    p.write_text('def test_ac_01_api(): pass\ndef test_ac_02_bad(): assert False\n')
    (project.root/'speed.toml').write_text('[eval]\ntest_command = '+json.dumps('cd backend && '+PYTEST)+'\n')
    catalog(project,['AC-01'],[task('1',['AC-01'],['backend/tests/test_api.py'])])
    run,report=project.evaluate(task_id='1')
    assert report['accepted'],report
    assert json.loads((run/'test-plan.json').read_text())['test_cases'][0]['selector']=='tests/test_api.py::test_ac_01_api'
