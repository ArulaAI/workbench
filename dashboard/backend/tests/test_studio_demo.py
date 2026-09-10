"""Recording examples keep the real authoring gates, without calling a model."""
from uuid import uuid4
from threading import Event
from concurrent.futures import ThreadPoolExecutor

import pytest

from lib.authoring_studio import Studio, StudioError
from lib.authoring_studio.demo import DEMO_BRIEF, REVIEW_PREFIX, REVIEW_SEPARATOR
from lib.authoring_studio.models import Command, CreateFeature
from lib.authoring_studio.editable_markdown import editable_markdown


def cmd(studio, state, action, **values):
    return studio.command(state['id'], Command(action=action, expected_revision=state['revision'], request_id=uuid4().hex, **values))


def forbidden_model(*_):
    raise AssertionError('A saved example must never call the real generator')


def finish(studio, state):
    op=next(o for o in state['operations'] if o['status']=='queued')
    studio.run(state['id'], op['id'], forbidden_model)
    result=studio.get(state['id'])
    assert not [o for o in result['operations'] if o['status']=='failed'], result['operations'][-1]
    return result


def start(studio, kind='prd'):
    return studio.create(CreateFeature(demo='task-due-dates', kind=kind, brief=DEMO_BRIEF, request_id=uuid4().hex))


def answer_all(studio, state, choice='option-1', text=''):
    for question in state['intakes']['prd']['questions']:
        state=cmd(studio,state,'answer_clarification',question_id=question['id'],choice=choice,text=text)
    return finish(studio,state)


@pytest.fixture
def waits(monkeypatch):
    calls=[]
    monkeypatch.setattr('lib.authoring_studio.demo.time.sleep',lambda seconds:calls.append(seconds))
    return calls


def test_demo_full_recording_edit_review_publish_and_skip_design(tmp_path, waits):
    studio=Studio(tmp_path)
    state=start(studio)
    assert state['demo']=='task-due-dates'
    assert state['operations'][0]['demo'] is True
    assert state['documents']['prd']['head'] is None
    state=finish(studio,state)
    assert waits==[5]
    assert len(state['intakes']['prd']['questions'])==3
    with pytest.raises(StudioError,match='every clarification'):
        cmd(studio,state,'generate')
    state=answer_all(studio,state)
    first=state['documents']['prd']['snapshot']
    assert waits==[5,5]
    assert first['number']==1 and first['model'].endswith('(no AI)')
    assert len(first['sections'])==11
    assert all('Review and acknowledge' in b for b in state['documents']['prd']['blockers'])
    with pytest.raises(StudioError):
        cmd(studio,state,'publish',version_id=first['id'],reviewed=True)
    text=editable_markdown(first).replace('# Scope\n', '# Scope\n\nDemo edit: document the hex API field for backend consumers.\n')
    state=cmd(studio,state,'edit_document',version_id=first['id'],markdown=text)
    second=state['documents']['prd']['snapshot']
    assert second['number']==2 and second['parent_id']==first['id']
    assert 'Demo edit:' in next(s for s in second['sections'] if s['id']=='scope')['body']
    assert 'Demo edit:' not in editable_markdown(studio.version(state['id'],first['id']))
    assert waits==[5,5] # manual save does not generate
    answer='The design owner will review the palette and contrast before frontend rollout. The backend can ship its metadata contract first.'
    state=cmd(studio,state,'revise',version_id=second['id'],text=REVIEW_PREFIX+'Open questions publication review. Update the document.'+REVIEW_SEPARATOR+answer)
    state=finish(studio,state)
    third=state['documents']['prd']['snapshot']
    assert third['number']==3
    assert answer in next(s for s in third['sections'] if s['id']=='risks')['body']
    assert next(s for s in third['sections'] if s['id']=='scope')==next(s for s in second['sections'] if s['id']=='scope')
    assert not next(r for r in state['documents']['prd']['publication_review'] if r['id']=='open_questions')['requires_deferral']
    state=cmd(studio,state,'acknowledge_publication',version_id=third['id'],review_group='success',disposition='confirmed')
    assert not state['documents']['prd']['blockers']
    state=cmd(studio,state,'publish',version_id=third['id'],reviewed=True)
    assert state['documents']['prd']['published']==third['id']
    state=cmd(studio,state,'generate',kind='rfc',source_mode='prd')
    state=finish(studio,state)
    rfc=state['documents']['rfc']['snapshot']
    assert state['documents']['design']['head'] is None
    assert rfc['pins']=={'prd':third['id']}
    assert len(rfc['sections'])==8 and len(rfc['coverage'])==10
    assert 'Demo edit:' in next(s for s in rfc['sections'] if s['id']=='context')['body']
    assert not any(s['unverified_source_ids'] for s in rfc['sections'])
    assert all('Review and acknowledge' in b for b in state['documents']['rfc']['blockers'])
    assert waits==[5,5,5,5,5]
    # Persisted mode survives service recreation; unsupported commands never
    # queue AI work, and repeating Use example creates a fresh empty workspace.
    reopened=Studio(tmp_path)
    with pytest.raises(StudioError,match='does not use AI'):
        cmd(reopened,state,'revise',text='Invent a different feature')
    with pytest.raises(StudioError,match='PRD and RFC'):
        cmd(reopened,state,'generate',kind='design')
    fresh=start(reopened)
    assert fresh['id']!=state['id'] and fresh['documents']['prd']['head'] is None
    assert reopened.get(state['id'])['documents']['prd']['published']==third['id']


@pytest.mark.parametrize('choice,text',[('option-2',''),('option-3',''),('custom','Use a separate archive view with no highlight.')])
def test_example_respects_selected_and_custom_answers(tmp_path,waits,choice,text):
    studio=Studio(tmp_path)
    state=answer_all(studio,finish(studio,start(studio)),choice,text)
    req=next(s for s in state['documents']['prd']['snapshot']['sections'] if s['id']=='requirements')
    for answer in state['intakes']['prd']['answers'].values():
        assert answer['text'] in req['body']
        assert any(answer['text']==i['statement'] for i in req['items'])


def test_cancelled_example_never_creates_late_draft_and_can_retry(tmp_path,monkeypatch):
    entered, release=Event(),Event()
    def pause(_):
        entered.set(); assert release.wait(3)
    monkeypatch.setattr('lib.authoring_studio.demo.time.sleep',pause)
    studio=Studio(tmp_path); state=start(studio)
    with ThreadPoolExecutor() as executor:
        future=executor.submit(studio.run,state['id'],state['operations'][0]['id'],forbidden_model)
        assert entered.wait(3)
        state=cmd(studio,studio.get(state['id']),'cancel')
        release.set(); future.result()
    state=studio.get(state['id'])
    assert state['operations'][0]['status']=='cancelled'
    assert state['intakes']['prd']['questions']==[]
    state=finish(studio,cmd(studio,state,'retry'))
    assert state['intakes']['prd']['status']=='awaiting_answers'


def test_demo_is_explicit_and_rejects_changed_inputs(tmp_path,waits):
    studio=Studio(tmp_path)
    regular=studio.create(CreateFeature(brief=DEMO_BRIEF,request_id=uuid4().hex))
    assert not regular.get('demo')
    calls=[]
    def regular_generator(*args):
        calls.append(True); raise RuntimeError('regular provider')
    studio.run(regular['id'],regular['operations'][0]['id'],regular_generator)
    assert calls==[True] and waits==[]
    for values in ({'brief':'A completely different problem statement.'},{'kind':'design'},{'context':'Different constraints'}):
        with pytest.raises(StudioError,match='original due-date brief'):
            studio.create(CreateFeature(**({'demo':'task-due-dates','brief':DEMO_BRIEF,'request_id':uuid4().hex}|values)))
    direct=finish(studio,start(studio,'rfc'))
    assert direct['documents']['rfc']['snapshot']['pins']=={}
    assert direct['documents']['prd']['head'] is None
