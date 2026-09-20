"""Real-runner task/feature acceptance tests; task JSON remains unchanged.

Set SPEED_TEST_VITEST to an installed vitest.mjs for the frontend integration.
The standard suite uses real pytest and Node when Node is installed.
"""
import json
import os
from pathlib import Path
import shlex
import shutil
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_eval_regressions import project, cli, invoke, PYTEST, result  # noqa: F401
from lib.eval_execution import run_command

NODE = shutil.which('node')


def configure(project, rows, extra_ids=(), tasks=None):
    """rows are (scenario, task, selector, test name, runner, command)."""
    ids = sorted({row[0] for row in rows} | set(extra_ids))
    project.spec.write_text('# Test spec\n## Scenario Catalog\n'
        '| ID | Scenario | Level | Expected outcome |\n|---|---|---|---|\n' +
        ''.join(f'| {sid} | Behavior {sid} | unit | Correct result |\n' for sid in ids) +
        '\n## Acceptance Traceability\n| RFC acceptance criterion | Covering scenarios |\n|---|---|\n' +
        ''.join(f'| Behavior {sid} | {sid} |\n' for sid in ids) +
        '\n## Execution and Evidence\n| Scenario | Task | Selector | Test name | Runner | Command |\n|---|---|---|---|---|---|\n' +
        ''.join('| ' + ' | '.join('`'+v+'`' if i in (2,3,5) and v else v for i,v in enumerate(row)) + ' |\n' for row in rows))
    for path in project.tasks.glob('*.json'):
        path.unlink()
    for task in tasks or [dict(id='1', status='done', files_touched=['tests/test_books.py'], acceptance_criteria=[])]:
        (project.tasks / (task['id']+'.json')).write_text(json.dumps(task))
    project.commit()


def row(sid='AC-01', task='1', selector='tests/test_books.py::test_pass', name='', runner='', command=''):
    return (sid, task, selector, name, runner, command)


def node_file(project):
    if not NODE:
        pytest.skip('Node is not installed')
    path = project.root / 'tests/service.test.cjs'
    path.write_text("const {test} = require('node:test');\nconst fs = require('node:fs');\n"
        "test('card [2500] + zero?', () => {fs.appendFileSync('.speed/executed', 'one\\n');});\n"
        "test('other task fails', () => {fs.appendFileSync('.speed/executed', 'other\\n'); throw Error('other');});\n"
        "test.skip('selected skip', () => {});\n")
    command = shlex.quote(NODE) + ' --test'
    (project.root / 'speed.toml').write_text('[eval]\ntest_commands = '+json.dumps([PYTEST,command])+'\n')
    return command


def test_shared_node_file_only_selected_test_runs_and_task_json_unchanged(project):
    command = node_file(project)
    configure(project, [row(selector='tests/service.test.cjs',name='card [2500] + zero?',runner='node',command=command),
                        row('AC-02','2','tests/service.test.cjs','other task fails','node',command)],
              tasks=[dict(id=i,status='done',files_touched=['tests/service.test.cjs'],acceptance_criteria=[]) for i in ['1','2']])
    original = {p.name:p.read_bytes() for p in project.tasks.glob('*.json')}
    run, report = project.evaluate(task_id='1')
    assert report['accepted'], report
    assert (project.root / '.speed/executed').read_text() == 'one\n'
    assert [r['id'] for r in report['results']] == ['AC-01']
    assert original == {p.name:p.read_bytes() for p in project.tasks.glob('*.json')}
    assert not (project.feature / 'evaluation.yaml').exists()
    assert (project.feature / 'evaluation-task-1.yaml').exists()


def test_one_task_two_tests_in_one_file_and_one_in_another(project):
    (project.root/'tests/test_books.py').write_text('from pathlib import Path\n'
        'def record(v):\n    with Path(".speed/executed").open("a") as f: f.write(v)\n'
        'def test_one(): record("one\\n")\n'
        'def test_two(): record("two\\n")\n'
        'def test_other(): record("other\\n"); assert False\n')
    (project.root/'tests/test_second.py').write_text('from pathlib import Path\n'
        'def test_three():\n    with Path(".speed/executed").open("a") as f: f.write("three\\n")\n')
    configure(project, [row(selector='tests/test_books.py::test_one'),
                        row(selector='tests/test_books.py::test_two'),
                        row(selector='tests/test_second.py::test_three'),
                        row('AC-02','2','tests/test_books.py::test_other')],
              tasks=[dict(id='1',status='done',files_touched=['tests/test_books.py','tests/test_second.py'],acceptance_criteria=[]),
                     dict(id='2',status='done',files_touched=['tests/test_books.py'],acceptance_criteria=[])])
    run, report = project.evaluate(task_id='1')
    assert report['accepted'], report
    assert (project.root/'.speed/executed').read_text().splitlines() == ['one','two','three']
    assert len(list((run/'commands').iterdir())) == 3


def test_feature_runs_all_mappings_and_attributes_individual_failures(project):
    command=node_file(project)
    configure(project,[row(selector='tests/service.test.cjs',name='card [2500] + zero?',runner='node',command=command),
                       row('AC-02','1','tests/service.test.cjs','other task fails','node',command)],
              tasks=[dict(id='1',status='done',files_touched=['tests/service.test.cjs'],acceptance_criteria=[])])
    run,report=project.evaluate()
    assert result(report)['status']=='pass',report
    assert result(report,'AC-02')['status']=='fail',report
    assert (project.root/'.speed/executed').read_text().splitlines()==['one','other']
    import yaml
    yaml_report=yaml.safe_load((run/'evaluation.yaml').read_text())
    assert yaml_report['selection']==report['selection']
    assert yaml_report['results'][0]['tests'][0]['test_name']=='card [2500] + zero?'


@pytest.mark.parametrize('task_id',[None,'1'])
@pytest.mark.parametrize('name,expected',[('renamed test','unverifiable'),('selected skip','unverifiable')])
def test_node_missing_and_skipped_test_never_pass(project,task_id,name,expected):
    command=node_file(project)
    configure(project,[row(selector='tests/service.test.cjs',name=name,runner='node',command=command)],
              tasks=[dict(id='1',status='done',files_touched=['tests/service.test.cjs'],acceptance_criteria=[])])
    _,report=project.evaluate(task_id=task_id)
    assert result(report)['status']==expected,report
    assert not report['accepted']
    assert not (project.root/'.speed/executed').exists()


@pytest.mark.parametrize('task_id',[None,'1'])
def test_blank_owned_mapping_stays_missing_in_both_scopes(project,task_id):
    configure(project,[row(),row('AC-02','1','')])
    _,report=project.evaluate(task_id=task_id)
    assert result(report,'AC-02')['status']=='unverifiable'
    assert not report['accepted']


@pytest.mark.parametrize('task_id',[None,'1'])
@pytest.mark.parametrize('selector',['tests/missing.py::test_pass','tests/test_books.py::test_renamed'])
def test_missing_pytest_test_or_file_is_visible(project,task_id,selector):
    configure(project,[row(selector=selector)])
    _,report=project.evaluate(task_id=task_id)
    assert result(report)['status']!='pass'
    assert not report['accepted']


def test_shared_exact_evidence_executed_once(project):
    configure(project,[row(),row('AC-02')])
    run,report=project.evaluate(task_id='1')
    assert report['accepted'],report
    assert len(list((run/'commands').iterdir()))==1


def test_whole_file_mapping_and_criterion_cannot_widen_task(project):
    configure(project,[row(selector='tests/test_books.py')],tasks=[dict(id='1',status='done',
        files_touched=['tests/test_books.py'],required_test_cases=['AC-01'],test_selectors=['tests/test_books.py'],
        acceptance_criteria=[dict(criterion='tests pass',verify_by='test')])])
    run,report=project.evaluate(task_id='1')
    assert not (run/'commands').exists()
    assert not (run/'criteria-commands').exists()
    assert result(report)['status']=='unverifiable'
    assert result(report,'TASK-1-CRIT-01')['status']=='unverifiable'


def test_unique_file_owner_can_be_inferred_without_task_schema_changes(project):
    configure(project,[row(task='')])
    _,report=project.evaluate(task_id='1')
    assert report['accepted'],report


def test_shared_file_requires_explicit_ownership(project):
    configure(project,[row(task='')],tasks=[dict(id=i,status='done',files_touched=['tests/test_books.py'],acceptance_criteria=[]) for i in ['1','2']])
    run,report=project.evaluate(task_id='1')
    assert not report['accepted']
    assert not (run/'commands').exists()
    assert any('Ambiguous' in r['evidence'] for r in report['results'])


def test_custom_patterns_find_missing_touched_test_file(project):
    (project.root/'speed.toml').write_text('[eval]\ntest_file_patterns = ["checks/*.py"]\n')
    configure(project,[row()],tasks=[dict(id='1',status='done',files_touched=['checks/payment.py','tests/helper.py'],acceptance_criteria=[])])
    _,report=project.evaluate(task_id='1')
    assert report['selection']['candidate_files']==['checks/payment.py']
    assert any('checks/payment.py' in g for g in report['selection']['gaps'])


def test_task_alias_dispatches_real_cli(project,cli):
    configure(project,[row()])
    completed=invoke(project,cli,'--task','1','--strict','--no-defects')
    assert completed.returncode==0,completed.stdout+completed.stderr
    report=json.loads((project.feature/'eval/task-1/report.json').read_text())
    assert report['task_id']=='1' and report['accepted']


def test_mixed_frontend_vitest_and_backend_pytest_task(project):
    executable=os.environ.get('SPEED_TEST_VITEST')
    if not executable or not NODE:
        pytest.skip('Set SPEED_TEST_VITEST to the installed vitest.mjs to run frontend integration')
    entry=Path(executable).resolve()
    frontend=project.root/'frontend'
    frontend.mkdir()
    (frontend/'service.test.mjs').write_text(
        'import {test,expect} from '+json.dumps(str(entry.parent/'dist/index.js'))+';\n'
        'import fs from "node:fs";\n'
        'test("task one [ui]",()=>{fs.appendFileSync("../.speed/ui", "one");expect(1).toBe(1);});\n'
        'test("task two ui",()=>{fs.appendFileSync("../.speed/ui", "other");expect(1).toBe(2);});\n')
    frontend_command='cd frontend && '+shlex.quote(NODE)+' '+shlex.quote(str(entry))+' run --maxWorkers=1 --no-file-parallelism'
    (project.root/'speed.toml').write_text('[eval]\ntest_commands = '+json.dumps([PYTEST,frontend_command])+'\n')
    with (project.root/'.gitignore').open('a') as f: f.write('node_modules/\n')
    configure(project,[row(),row('AC-02','1','service.test.mjs','task one [ui]','vitest',frontend_command)],
              tasks=[dict(id='1',status='done',files_touched=['tests/test_books.py','frontend/service.test.mjs'],acceptance_criteria=[])])
    run,report=project.evaluate(task_id='1')
    assert report['accepted'],report
    assert (project.root/'.speed/ui').read_text()=='one'
    assert len(list((run/'commands').iterdir()))==2


def test_nested_node_full_title_selects_only_one_test(project):
    command=node_file(project)
    (project.root/'tests/service.test.cjs').write_text(
        "const {describe,it}=require('node:test');describe('payment suite',()=>{"
        "it('authorise',()=>{});it('capture',()=>{throw Error('unrelated')})});")
    configure(project,[row(selector='tests/service.test.cjs',name='payment suite authorise',runner='node',command=command)],
              tasks=[dict(id='1',status='done',files_touched=['tests/service.test.cjs'],acceptance_criteria=[])])
    _,report=project.evaluate(task_id='1')
    assert report['accepted'],report


def test_test_criterion_reuses_named_scenario_and_does_not_rerun_file(project):
    configure(project,[row()],tasks=[dict(id='1',status='done',files_touched=['tests/test_books.py'],
        acceptance_criteria=[dict(criterion='Read a book',verify_by='test')])])
    text=project.spec.read_text().replace('| Runner | Command |','| Runner | Command | Criterion |')
    text=text.replace('|---|---|---|---|---|---|','|---|---|---|---|---|---|---|')
    text=text.replace('| AC-01 | 1 | `tests/test_books.py::test_pass` |  |  |  |',
                      '| AC-01 | 1 | `tests/test_books.py::test_pass` |  |  |  | 1 |')
    project.spec.write_text(text)
    project.commit()
    run,report=project.evaluate(task_id='1')
    assert report['accepted'],report
    assert result(report)['criteria'][0]['status']=='pass'
    assert len(list((run/'commands').iterdir()))==1
    assert not (run/'criteria-commands').exists()


@pytest.mark.parametrize('selector',['tests/test_books.py::test_parameter','tests/test_books.py::test_parameter[two words, three]'])
def test_pytest_parameterized_selection(project,selector):
    configure(project,[row(selector=selector)])
    _,report=project.evaluate(task_id='1')
    assert report['accepted'],report


def test_whole_file_legacy_batch_is_not_executed(project):
    configure(project,[],extra_ids=['AC-01'],tasks=[dict(id='1',status='done',files_touched=['tests/test_books.py'],
        required_test_cases=['AC-01'],test_selectors=['tests/test_books.py'],acceptance_criteria=[])])
    run,report=project.evaluate(task_id='1')
    assert result(report)['status']=='unverifiable'
    assert not (run/'commands').exists()


def test_pending_other_task_does_not_block_selected_done_task(project):
    configure(project,[row(),row('AC-02','2','tests/test_books.py::test_fail')],tasks=[
        dict(id='1',status='done',files_touched=['tests/test_books.py'],acceptance_criteria=[]),
        dict(id='2',status='pending',files_touched=['tests/test_books.py'],acceptance_criteria=[])])
    _,report=project.evaluate(task_id='1')
    assert report['accepted']
    with pytest.raises(RuntimeError,match='done tasks'):
        project.evaluate()


def test_jest_individual_test_and_json_evidence(project):
    executable=os.environ.get('SPEED_TEST_JEST')
    if not executable or not NODE:
        pytest.skip('Set SPEED_TEST_JEST to the installed jest.js for Jest integration')
    test_file=project.root/'tests/ui.test.cjs'
    test_file.write_text('const fs=require("node:fs");\n'
        'describe("payments",()=>{test("task one",()=>{fs.writeFileSync(".speed/jest", "one");expect(1).toBe(1)});'
        'test("task two",()=>{fs.writeFileSync(".speed/jest", "other");expect(1).toBe(2)});});\n')
    command=shlex.quote(NODE)+' '+shlex.quote(executable)+' --runInBand --config='+shlex.quote('{"testEnvironment":"node"}')
    (project.root/'speed.toml').write_text('[eval]\ntest_command = '+json.dumps(command)+'\n')
    configure(project,[row(selector='tests/ui.test.cjs',name='payments task one',runner='jest',command=command)],
              tasks=[dict(id='1',status='done',files_touched=['tests/ui.test.cjs'],acceptance_criteria=[])])
    _,report=project.evaluate(task_id='1')
    assert report['accepted'],report
    assert (project.root/'.speed/jest').read_text()=='one'


@pytest.mark.parametrize('task_id',[None,'1'])
def test_missing_additional_mapping_not_hidden_by_passing_test(project,task_id):
    configure(project,[row(),row(selector='')])
    _,report=project.evaluate(task_id=task_id)
    assert result(report)['status']=='unverifiable',report
    assert not report['accepted']


@pytest.mark.parametrize('task_id',[None,'1'])
def test_legacy_selector_does_not_hide_another_unmapped_touched_file(project,task_id):
    configure(project,[],extra_ids=['AC-01'],tasks=[dict(id='1',status='done',
        files_touched=['tests/test_books.py','tests/test_missing.py'],required_test_cases=['AC-01'],
        test_selectors=['tests/test_books.py::test_pass'],acceptance_criteria=[])])
    _,report=project.evaluate(task_id=task_id)
    assert not report['accepted']
    assert any('tests/test_missing.py' in gap for gap in report['selection']['gaps'])


@pytest.mark.parametrize('data',[{'testResults':[None]}, {'testResults':[{'assertionResults':[{}]}]}])
def test_malformed_frontend_report_does_not_crash_or_pass(project,data):
    script=project.root/'reporter.py'
    script.write_text('import os,json\nfrom pathlib import Path\n'
        'Path(os.environ["SPEED_EVAL_RESULT_FILE"]).write_text('+repr(json.dumps(data))+')\n')
    outcome=run_command(shlex.quote(sys.executable)+' reporter.py',['tests/test_books.py::test_pass'],
                        project.root,project.root/'.speed/evidence',exact=True)
    assert outcome['status']=='unverifiable'
    assert 'Invalid' in outcome['evidence']


def test_duplicate_node_full_title_cannot_pass(project):
    command=node_file(project)
    (project.root/'tests/service.test.cjs').write_text(
        "const {test}=require('node:test');test('same',()=>{});test('same',()=>{});")
    configure(project,[row(selector='tests/service.test.cjs',name='same',runner='node',command=command)],
              tasks=[dict(id='1',status='done',files_touched=['tests/service.test.cjs'],acceptance_criteria=[])])
    _,report=project.evaluate(task_id='1')
    assert result(report)['status']=='unverifiable'
    assert 'ambiguous' in result(report)['evidence']


def test_feature_without_tasks_still_reports_all_missing_declared_tests(project):
    configure(project,[row(task='',selector='')])
    for path in project.tasks.glob('*.json'):
        path.unlink()
    project.commit()
    run,report=project.evaluate()
    assert result(report)['status']=='unverifiable'
    assert not report['accepted']
    assert not (run/'commands').exists()
