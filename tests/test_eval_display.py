"""The human CLI shows individual evidence rather than duplicate area counts."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.eval_display import scenario_table


def scenario(sid='AC-01', status='pass', executions=None):
    return {'id':sid,'kind':'scenario','status':status,'expected':'Invalid input returns 400',
            'evidence':'No test mapped to this scenario','executions':executions or []}


def execution(file='tests/api.py', name='test_ac_01_invalid', status='pass'):
    return {'selector':file,'status':status,'artifact_dir':'/project/eval/commands/first',
            'evidence':f'Selected assertion {status} (log: /project/eval/commands/first/output.log)',
            'tests':[{'id':name,'status':status}]}


def test_scenario_table_has_tests_expectations_and_evidence_without_duplicate_criteria(tmp_path):
    artifact = tmp_path/'commands/first'
    artifact.mkdir(parents=True)
    (artifact/'result.json').write_text('{"status":"pass"}')
    (artifact/'output.log').touch()
    item = execution()
    item['artifact_dir'] = str(artifact)
    item['evidence'] = f'Selected assertion pass (evidence: {artifact}/result.json)'
    report={'results':[scenario(executions=[item]),
        {'id':'TASK-1-CRIT-01','kind':'criterion','status':'pass',
         'evidence':'Reused declared criterion scenarios: AC-01'}]}
    output=scenario_table(report,columns=160,evidence_root=tmp_path)
    for expected in ('Scenario ID','Test file / case / result','Expected behavior / execution evidence',
                     'AC-01','tests/api.py','test_ac_01_invalid','Result: PASS','Invalid input returns 400',
                     'Selected assertion pass','[1] commands/first/result.json'):
        assert expected in output
    assert output.count('| AC-01 ')==1
    assert 'TASK-1-CRIT-01' not in output
    assert '1 task criteria reuse scenario evidence' in output


def test_multiple_files_failures_and_missing_scenarios_are_visible():
    report={'results':[scenario(status='fail',executions=[execution(),execution('tests/ui.js','rejects_invalid','fail')]),
                       scenario('AC-02','unverifiable')]}
    output=scenario_table(report,columns=160)
    for expected in ('tests/api.py','tests/ui.js','Scenario: FAIL','Result: PASS','Result: FAIL',
                     'AC-02','UNVERIFIABLE','No individual test evidence','No test mapped'):
        assert expected in output
    assert output.count('| AC-01 ')==1 and output.count('| AC-02 ')==1


def test_named_selection_excludes_other_skipped_tests():
    item=execution('tests/api.js','selected')
    item['test_name']='selected'
    item['tests']=[{'id':'selected','name':'selected','status':'pass'},
                   {'id':'unrelated','name':'unrelated','status':'skip'}]
    output=scenario_table({'results':[scenario(executions=[item])]})
    assert 'Test: selected' in output and 'unrelated' not in output


@pytest.mark.parametrize('columns',[72,120,180])
def test_table_wraps_long_values_without_truncating_or_emitting_control_codes(columns):
    item=scenario(executions=[execution()])
    item['expected']='start '+('word '*80)+'final-marker\x1b[2J'
    output=scenario_table({'results':[item]},columns=columns)
    grid=[line for line in output.splitlines() if line.startswith(('|','+'))]
    assert all(len(line)<=columns for line in grid)
    assert output.count('word')==80 and 'final-marker' in output
    assert '\x1b' not in output


def test_skipped_test_is_not_presented_as_passing():
    output=scenario_table({'results':[scenario(status='unverifiable',executions=[execution(status='skip')])]})
    assert 'Scenario: UNVERIFIABLE' in output and 'Result: SKIP' in output
    assert 'Scenario: PASS' not in output


def test_empty_report_renders_without_inventing_scenarios():
    assert scenario_table({'results':[]})=='0 scenarios, 0 pass\nNo scenario results in this evaluation.'
