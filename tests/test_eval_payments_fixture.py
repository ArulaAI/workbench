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
    a=text.index('| Scenario | Selector | Command |',text.index('## Execution and Evidence'))
    b=text.index('\n\n',a)
    rows=['| Scenario | Task | Selector | Test name | Runner |','|---|---|---|---|---|']
    for line in text[a:b].splitlines()[2:]:
        parts=[x.strip() for x in line.strip('|').split('|')]
        sid,selector=parts[:2]
        # Task 1 spans two service tests and one money test; task 2 shares both
        # files and includes the four missing declared scenarios.
        owner='1' if sid in ('AC-01','AC-02','VAL-01') else '2'
        rows.append(f'| {sid} | {owner} | {selector} | {NAMES.get(sid, "")} | node |')
    spec.write_text(text[:a]+'\n'.join(rows)+text[b:])
    feature=root/'.speed/features/payments'
    (feature/'tasks').mkdir(parents=True)
    for owner in ('1','2'):
        atomic_json(feature/'tasks'/f'{owner}.json',dict(id=owner,status='done',
            files_touched=['test/service.test.ts','test/money.test.ts']+(['test/ledger.test.ts'] if owner=='2' else []),acceptance_criteria=[]))
    atomic_json(feature/'state.json',dict(status='completed'))
    (feature/'test_spec_path').write_text(str(spec))
    subprocess.run(['git','init','-q',str(root)],check=True)
    subprocess.run(['git','-C',str(root),'add','-A'],check=True)
    subprocess.run(['git','-C',str(root),'-c','user.name=Tests','-c','user.email=tests@example.invalid',
                    '-c','core.hooksPath=/dev/null','commit','-qm','fixture'],check=True)
    return root,feature,spec


def evaluate(copy,task_id=None):
    root,feature,spec=copy
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
    assert {r['id'] for r in report['results']}=={'AC-01','AC-02','VAL-01'}
    executions=[e for r in report['results'] for e in r.get('executions',[])]
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
    assert len(list((run/'commands').iterdir()))==17


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
    assert len([r for r in feature_report['results'] if r['kind']=='scenario'])==21
