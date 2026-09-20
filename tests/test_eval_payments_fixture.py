"""Opt-in integration against a copy of the user's payment fixture repository.

SPEED_TEST_PAYMENTS_FIXTURE=/path/to/payments-validation-fixture enables this.
No original fixture file or task state is changed.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lib.eval_runtime import atomic_json, execute, finish, prepare
from lib.eval_report import build_report, write_report
from lib.test_spec import parse_scenarios

NAMES = {
 'AC-01':'authorise records the amount and posts a balanced pair',
 'AC-02':'authorise never stores a full PAN',
 'AC-03':'idempotent authorise returns the original payment',
 'AC-04':'capture splits into net and fee, and both post',
 'AC-05':'partial captures accumulate exactly and never exceed the authorisation',
 'AC-06':'capture beyond the authorisation is rejected',
 'AC-07':'refund reduces nothing below zero and cannot exceed the capture',
 'AC-08':'void reverses an uncaptured authorisation',
 'AC-09':'a captured payment cannot be voided',
 'AC-10':'settlement schedule conserves the captured total',
 'AC-11':'all four invariants hold after a mixed sequence',
 'VAL-01':'money rejects fractional minor units',
 'VAL-02':'allocate never creates or destroys money',
 'VAL-03':'allocate front-loads the remainder',
 'VAL-04':'applyRate rounds symmetrically about zero',
 'LEDGER-01':'every post writes a balanced pair',
 'LEDGER-02':'ledger nets to zero across many postings',
}

@pytest.fixture
def payment_copy(tmp_path,monkeypatch):
    source=os.environ.get('SPEED_TEST_PAYMENTS_FIXTURE')
    if not source:
        pytest.skip('Set SPEED_TEST_PAYMENTS_FIXTURE for copied payment integration')
    monkeypatch.delenv('SPEED_EVAL_TEST_COMMAND',raising=False)
    root=tmp_path/'payments'
    shutil.copytree(source,root,ignore=shutil.ignore_patterns('.git','.speed','node_modules','.DS_Store'))
    spec=root/'specs/tests/payments.md'
    text=spec.read_text()
    # The test spec is a catalog authored before planning. Ownership comes
    # from existing task criteria, and the test names retain scenario IDs.
    a=text.index('## Execution and Evidence')
    b=text.index('## Exit Criteria',a)
    text=text[:a]+'## Execution and Evidence\n\nTask criteria and tagged test names generate the execution plan.\n\n'+text[b:]
    spec.write_text(text)
    names=dict(NAMES)
    if (root/'test/refund-retry.test.ts').exists():
        names['RETRY-01']='a retried refund is accepted'
    for sid,name in names.items():
        filename='refund-retry' if sid=='RETRY-01' else 'service' if sid.startswith('AC-') else 'money' if sid.startswith('VAL-') else 'ledger'
        path=root/f'test/{filename}.test.ts'
        contents=path.read_text()
        contents=contents.replace("test('"+name+"',", "test('["+sid+"] "+name+"',")
        assert "test('["+sid+"] "+name+"'," in contents
        path.write_text(contents)
    scenarios=parse_scenarios(text)
    feature=root/'.speed/features/payments'
    (feature/'tasks').mkdir(parents=True)
    for owner in ('1','2'):
        ids=[row['id'] for row in scenarios if ('1' if row['id'] in ('AC-01','AC-02','VAL-01') else '2')==owner]
        files=['test/service.test.ts','test/money.test.ts']+(['test/ledger.test.ts'] if owner=='2' else [])
        if owner=='2' and 'RETRY-01' in names:files.append('test/refund-retry.test.ts')
        criteria='\n'.join(f'- [{sid}] {names.get(sid, "Required catalog scenario")}\n  verify_by: test' for sid in ids)
        atomic_json(feature/'tasks'/f'{owner}.json',dict(id=owner,status='done',files_touched=files,acceptance_criteria=criteria))
    atomic_json(feature/'state.json',dict(status='completed'))
    (feature/'test_spec_path').write_text(str(spec))
    subprocess.run(['git','init','-q',str(root)],check=True)
    subprocess.run(['git','-C',str(root),'add','-A'],check=True)
    subprocess.run(['git','-C',str(root),'-c','user.name=Tests','-c','user.email=tests@example.invalid',
                    '-c','core.hooksPath=/dev/null','commit','-qm','fixture'],check=True)
    return root,feature,spec


def evaluate(copy,task_id=None):
    root,feature,spec=copy
    if os.environ.get('SPEED_TEST_FULL_CLI'):
        entry=Path(__file__).resolve().parents[1]/'speed'
        command=['bash',str(entry),'eval','--feature','payments','--json','--skip-judge','--no-defects']
        if task_id:command.extend(['--task',task_id])
        completed=subprocess.run(command,cwd=root,env={**os.environ,'SPEED_PROJECT_ROOT':str(root)},text=True,capture_output=True,timeout=60)
        assert completed.returncode==0,completed.stdout+completed.stderr
        report=json.loads(completed.stdout)
        output=feature/'eval' if task_id is None else feature/'eval'/f'task-{task_id}'
        return output/'runs'/report['run_id'],report
    pytest.importorskip('tree_sitter_typescript')
    run=prepare(root,feature,feature/'state.json',spec,task_id=task_id)
    execute(run)
    read=lambda name:json.loads((run/name).read_text())
    report=build_report('payments',root,run/'tasks',run/'test-spec.md',
        scenario_results=read('scenario-results.json')['results'],task_id=task_id,
        test_plan_path=run/'test-plan.json',runner_config=read('runner-config.json'),
        evidence_dir=run/'criteria-commands',context=read('context.json'))
    write_report(report,run)
    finish(run)
    return run,report


def test_payment_task_three_tests_in_two_files(payment_copy):
    run,report=evaluate(payment_copy,'1')
    assert report['accepted'],report
    assert {r['id'] for r in report['results'] if r['kind']=='scenario'}=={'AC-01','AC-02','VAL-01'}
    executions=[e for r in report['results'] if r['kind']=='scenario' for e in r.get('executions',[])]
    assert len(executions)==3
    assert all(len(e['tests'])==1 for e in executions),executions
    assert len(list((run/'commands').iterdir()))==3


def test_payment_feature_all_17_tests_and_four_declared_gaps(payment_copy):
    run,report=evaluate(payment_copy)
    results={r['id']:r for r in report['results']}
    assert all(results[sid]['status']=='pass' for sid in NAMES),report
    for sid in ('RISK-01','RISK-02','AC-12','EDGE-01'):
        assert results[sid]['status']=='unverifiable'
    assert not report['accepted']
    assert len(list((run/'commands').iterdir()))==len(NAMES)+int('RETRY-01' in results)


def test_payment_task_missing_tests_are_not_hidden(payment_copy):
    _,report=evaluate(payment_copy,'2')
    results={r['id']:r for r in report['results']}
    assert 'AC-01' not in results
    for sid in ('RISK-01','RISK-02','AC-12','EDGE-01'):
        assert results[sid]['status']=='unverifiable'
    assert not report['accepted']


def test_unmodified_cli_payment_task_and_feature(payment_copy):
    if not os.environ.get('SPEED_TEST_FULL_CLI'):
        pytest.skip('Set SPEED_TEST_FULL_CLI=1 with SPEED_PYTHON and installed CLI dependencies')
    root,feature,_=payment_copy
    entry=Path(__file__).resolve().parents[1]/'speed'
    env={**os.environ,'SPEED_PROJECT_ROOT':str(root)}
    for extra,expected_code in [(['--task','1'],0),([],2),(['--task-id','2'],2)]:
        completed=subprocess.run(['bash',str(entry),'eval','--feature','payments','--strict','--json',
            '--skip-judge','--no-defects',*extra],cwd=root,env=env,text=True,capture_output=True,timeout=60)
        assert completed.returncode==expected_code,completed.stdout+completed.stderr
        report=json.loads(completed.stdout)
        assert report['accepted']==(expected_code==0)
        if extra:
            assert report['task_id']==extra[1]
    feature_report=json.loads((feature/'eval/report.json').read_text())
    assert feature_report['task_id'] is None
    assert len([r for r in feature_report['results'] if r['kind']=='scenario'])==len(parse_scenarios(payment_copy[2].read_text()))


@pytest.mark.parametrize('task_id,expected_code',[('1',0),(None,2)])
def test_human_cli_payment_scenario_table(payment_copy,task_id,expected_code):
    if not os.environ.get('SPEED_TEST_FULL_CLI'):
        pytest.skip('Set SPEED_TEST_FULL_CLI=1 with SPEED_PYTHON and installed CLI dependencies')
    root,feature,_=payment_copy
    entry=Path(__file__).resolve().parents[1]/'speed'
    command=['bash',str(entry),'eval','--feature','payments','--strict','--skip-judge','--no-defects']
    if task_id:command+=['--task',task_id]
    completed=subprocess.run(command,cwd=root,env={**os.environ,'SPEED_PROJECT_ROOT':str(root),'COLUMNS':'160'},
                             text=True,capture_output=True,timeout=60)
    assert completed.returncode==expected_code,completed.stdout+completed.stderr
    output=completed.stdout
    for heading in ('Scenario ID','Test file / case / result','Expected behavior / execution evidence'):
        assert heading in output
    table=output.split('Scenario results\n',1)[1].split('PASS means',1)[0]
    rows={}
    current=None
    for line in table.splitlines():
        if not line.startswith('| '):continue
        parts=[part.strip() for part in line.split('|')[1:-1]]
        assert len(parts)==3
        if parts[0]=='Scenario ID':continue
        if parts[0]:current=parts[0];rows[current]=[]
        if current:rows[current].append(parts[2])
    directory=feature/'eval' if task_id is None else feature/'eval'/f'task-{task_id}'
    report=json.loads((directory/'report.json').read_text())
    scenarios=[r for r in report['results'] if r['kind']=='scenario']
    assert set(rows)=={r['id'] for r in scenarios}
    for result in scenarios:
        assert result['expected'] in ' '.join(rows[result['id']]),result
    assert 'test/service.test.ts' in table and 'test/money.test.ts' in table
    assert 'task criteria reuse scenario evidence' in output
    assert 'Task criteria          3 pass' not in output
    if task_id:
        assert set(rows)=={'AC-01','AC-02','VAL-01'}
        assert len(list((directory/'runs'/report['run_id']/'commands').iterdir()))==3
    else:
        assert {'RISK-01','RISK-02','AC-12','EDGE-01'}<=rows.keys()
        assert 'UNVERIFIABLE' in table and 'No individual test' in table
