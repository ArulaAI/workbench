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
    assert result(report,'AC-02')['criteria'][0]['status']=='unverifiable'
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
    criteria = {c['id']: c for c in result(report)['criteria']}
    assert criteria['TASK-1-CRIT-01']['status']=='pass'
    assert criteria['TASK-2-CRIT-01']['status']=='unverifiable'
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


def test_actual_task_create_preserves_structured_criteria(project):
    criteria=json.dumps(task('1',['AC-01'])['acceptance_criteria'])
    script='source "$1/lib/tasks.sh"; TASKS_DIR="$2"; BRANCH_PREFIX=speed/books; task_create 1 title description "$3" "[]" sonnet'
    subprocess.run(['bash','-c',script,'test',str(Path(__file__).resolve().parents[1]),str(project.tasks),criteria],check=True,capture_output=True)
    saved=json.loads((project.tasks/'1.json').read_text())
    assert saved['acceptance_criteria']==task('1',['AC-01'])['acceptance_criteria']
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
    table=(run/'summary.md').read_text().split('## Scenario results\n',1)[1].split('## Results\n',1)[0]
    assert 'other task' not in table and 'frontend' in table and 'backend' in table


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
    assert saved['acceptance_criteria']==planned['acceptance_criteria']
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


@pytest.mark.parametrize('body,status',[
    ('def test_ac_01_behavior(): pass\n','PASS'),
    ('def test_ac_01_behavior(): assert False\n','FAIL'),
    ('def test_other_behavior(): pass\n','UNVERIFIABLE'),
])
def test_summary_table_expected_behavior_and_actual_evidence(project,body,status):
    (project.root/'tests/test_books.py').write_text(body)
    catalog(project,['AC-01'],[task('1',['AC-01'])])
    project.spec.write_text(project.spec.read_text().replace('| Correct behavior |','| Invalid input returns HTTP 400 |'))
    project.commit()
    run,report=project.evaluate(task_id='1')
    summary=(run/'summary.md').read_text()
    table=summary.split('## Scenario results\n',1)[1].split('## Results\n',1)[0]
    assert '| Scenario ID | Test cases in files and result | Expected behavior and execution evidence |' in table
    assert table.count('| AC-01 |')==1 and 'TASK-1-CRIT' not in table
    assert '**Expected:** Invalid input returns HTTP 400' in table
    assert '**Evidence:**' in table and f'**{status}**' in table
    assert 'does not independently verify' in table
    if status=='UNVERIFIABLE':
        assert 'No individual test result' in table and '[Execution evidence]' not in table
    else:
        assert 'tests/test\\_books.py' in table and '[Execution evidence]' in table
        assert 'test\\_ac\\_01\\_behavior' in table
        assert str(run).replace(' ', '%20') in table
    assert result(report)['status'].upper()==status


def test_summary_table_retains_all_individual_results_and_escapes_cells(project):
    (project.root/'tests/test_books.py').write_text('def test_ac_01_first(): pass\n')
    (project.root/'tests/second.py').write_text('def test_ac_01_second(): assert False\n')
    catalog(project,['AC-01'],[task('1',['AC-01'],['tests/test_books.py','tests/second.py'])])
    # Explicitly include this second file in the configured test patterns.
    (project.root/'speed.toml').write_text('[eval]\ntest_command = '+json.dumps(PYTEST)+'\ntest_file_patterns = ["tests/*.py"]\n')
    project.commit()
    run,report=project.evaluate(task_id='1')
    from lib.eval_report import _scenario_table
    result(report)['expected']='A | B <tag>\nsecond line'
    table='\n'.join(_scenario_table(report))
    assert table.count('| AC-01 |')==1
    assert 'test\\_ac\\_01\\_first' in table and 'test\\_ac\\_01\\_second' in table
    assert '**PASS**' in table and '**FAIL**' in table
    assert 'A \\| B &lt;tag&gt;<br>second line' in table
    assert len(list((run/'commands').iterdir()))==2


def test_one_to_one_criteria_fold_and_promoted_files_are_pruned(project):
    from urllib.parse import unquote
    import re
    (project.root/'tests/test_books.py').write_text('def test_ac_01_present(): pass\n')
    catalog(project,['AC-01'],[task('1',['AC-01'])])
    first, report = project.evaluate(task_id='1')
    output = first.parent.parent
    archived = {p.relative_to(first): p.read_bytes() for p in first.rglob('*') if p.is_file()}
    for name in ('test-plan.json', 'scenario-results.json'):
        shutil.copyfile(first/name, output/name)  # Simulate the previous promotion layout.
    (output/'residue.json').write_text('{}')      # A stale copy from an older version.
    run, report = project.evaluate(task_id='1')
    assert {p.name for p in output.iterdir()} == {'runs','summary.md','report.json','latest-attempt.json'}
    assert archived == {p.relative_to(first): p.read_bytes() for p in first.rglob('*') if p.is_file()}
    assert (project.feature/'evaluation-task-1.yaml').is_file()
    assert report['summary']['total'] == report['summary']['pass'] == 1
    assert report['criteria_summary']['total'] == report['criteria_summary']['discharged'] == 1
    assert len(report['results']) == 1
    assert result(report)['criteria'][0]['title'] == '[AC-01] Behavior AC-01'
    public = json.loads((output/'report.json').read_text())
    assert public['results'] == [{'id':'AC-01','status':'pass'}]
    assert 'TASK-1-CRIT-01' not in json.dumps(public)
    archived_report = json.loads((run/'report.json').read_text())
    assert archived_report['results'][0]['executions']
    assert archived_report['results'][0]['criteria'][0]['id'] == 'TASK-1-CRIT-01'
    summary = (output/'summary.md').read_text()
    assert '1 scenarios, 1 pass' in summary and '1 of 1 criteria discharged' in summary
    for section in ('Scenario results','Results','Execution scope'):
        table = summary.split('## '+section+'\n',1)[1].split('\n## ',1)[0]
        assert table.count('| AC-01 |') == 1
        assert '| TASK-1-CRIT-01 |' not in table
    links = re.findall(r'\]\(<([^>]+)>\)', summary)
    assert links and all(Path(unquote(p)).is_file() and Path(unquote(p)).stat().st_size for p in links)
    assert all(p.endswith('/result.json') for p in links)


def test_non_one_to_one_criteria_remain_distinct_and_block_acceptance(project):
    (project.root/'tests/test_books.py').write_text('def test_ac_01_first(): pass\ndef test_ac_02_second(): pass\n')
    one = task('1',[])
    one['acceptance_criteria'] = [
        {'criterion':'[AC-01] [AC-02] Joint behavior','verify_by':'test'},
        {'criterion':'[AC-01] Human review','verify_by':'manual'},
        {'criterion':'No scenario ID','verify_by':'test'},
    ]
    catalog(project,['AC-01','AC-02'],[one])
    run, report = project.evaluate(task_id='1')
    assert not report['accepted']
    assert report['summary']['total'] == report['summary']['pass'] == 2
    assert report['criteria_summary']['total'] == 3
    assert report['criteria_summary']['discharged'] == 1
    assert result(report,'TASK-1-CRIT-01')['status'] == 'pass'
    assert result(report,'TASK-1-CRIT-02')['status'] == 'unverifiable'
    assert result(report,'TASK-1-CRIT-03')['status'] == 'unverifiable'
    assert any(r['id'].startswith('SELECTION-') for r in report['results'])
    scope = (run/'summary.md').read_text().split('## Execution scope\n',1)[1]
    assert scope.count('| AC-01 |') == scope.count('| AC-02 |') == 1
    assert 'TASK-1-CRIT-01' not in scope
    public = json.loads((run.parent.parent/'report.json').read_text())
    assert public['results'] == [{'id':sid,'status':'pass'} for sid in ('AC-01','AC-02')]
    assert not public['accepted']
    assert {row['id'] for row in public['checks']} == {
        row['id'] for row in report['results'] if row['kind'] != 'scenario'}


def test_absent_criterion_gate_survives_folding(project):
    from lib.eval_report import build_report
    (project.root/'tests/test_books.py').write_text('def test_ac_01_first(): pass\n')
    catalog(project,['AC-01'],[task('1',['AC-01'])])
    run, _ = project.evaluate(task_id='1')
    context = json.loads((run/'context.json').read_text())
    context['selection']['criterion_scenarios']['1']['2'] = ['AC-01']
    report = build_report('books',project.root,run/'tasks',run/'test-spec.md',task_id='1',
        scenario_results=json.loads((run/'scenario-results.json').read_text())['results'],context=context)
    assert result(report,'CRITERION-1-2')['status'] == 'unverifiable'
    assert not report['accepted'] and report['summary']['total'] == 1


def test_legacy_mapped_non_test_criteria_do_not_gain_verifier_executions(project, monkeypatch):
    from lib import eval_report
    def unexpected(*args, **kwargs):
        pytest.fail('Report presentation must not introduce verifier executions')
    monkeypatch.setattr(eval_report, 'run_command', unexpected)
    monkeypatch.setattr(eval_report, 'verify_criteria', unexpected)
    one = task('1', [])
    one['acceptance_criteria'] = [
        {'criterion': 'Mapped legacy check', 'verify_by': mode, 'scenario_ids': ['AC-01']}
        for mode in ('lint', 'schema')
    ]
    assert eval_report._semantic_results([one], project.root, evidence_dir=project.feature) == []
