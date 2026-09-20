"""Structured task criteria stay readable through existing dashboard APIs."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.criteria_display import criteria_text
from backend.resolvers.landing import _read_criteria_verify
from backend.schema import schema


def test_criteria_text_keeps_verification_hints_and_legacy_values():
    criteria=[{'criterion':'[AC-01] Invalid input returns 400','verify_by':'test'}]
    assert criteria_text(criteria)=='- [AC-01] Invalid input returns 400\n  verify_by: test'
    assert criteria_text('Legacy text')=='Legacy text'
    assert criteria_text(None) is None
    assert criteria_text([])==''


def test_landing_counts_structured_criteria(tmp_path):
    tasks=tmp_path/'tasks';tasks.mkdir()
    (tasks/'1.json').write_text(json.dumps({'id':'1','status':'done',
        'acceptance_criteria':[{'criterion':'one','verify_by':'test'},{'criterion':'two','verify_by':'manual'}],
        'gate_results':{'checks':[{'name':'criteria','status':'pass'}]},'review_verdict':'approve'}))
    assert _read_criteria_verify(tmp_path)==(100.0,2,2,0)


def test_mission_control_graphql_serializes_structured_criteria(tmp_path,monkeypatch):
    from backend.resolvers import mission_control
    monkeypatch.setattr(mission_control,'get_mission_control',lambda *args: {
        'state':{'status':'done'},'task_count':1,
        'tasks':[{'id':'1','title':'API','status':'done','acceptance_criteria':[
            {'criterion':'[AC-01] Invalid input returns 400','verify_by':'test'}]}]})
    response=schema.execute_sync('query { missionControl(feature: "api") { tasks { id acceptanceCriteria } } }',
                                 context_value={'project_root':tmp_path})
    assert not response.errors,response.errors
    value=response.data['missionControl']['tasks'][0]['acceptanceCriteria']
    assert '[AC-01]' in value and 'verify_by: test' in value
