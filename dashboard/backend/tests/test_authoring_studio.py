"""Behavioral regression tests for the independent authoring architecture."""
import copy
import sqlite3
import subprocess
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest

from lib.authoring_studio import Studio, StudioError
from lib.authoring_studio.generator import source
from lib.authoring_studio.models import Clarification, Command, CreateFeature, Generation, Item, RFC_MODULES, TEMPLATES
from lib.authoring_studio.service import markdown
from lib.authoring_studio.reviews import saved_reviews


@pytest.fixture
def studio(tmp_path):
    return Studio(tmp_path)


def create(studio):
    return studio.create(CreateFeature(title="Saved views", brief="Save personal filters and restore them later.", request_id=uuid4().hex))


def command(studio, state, action, **kwargs):
    return studio.command(state["id"], Command(action=action, expected_revision=state["revision"], request_id=uuid4().hex, **kwargs))


def generated(kind="prd", head=None, scoped=None, **updates):
    sections = copy.deepcopy(head["sections"]) if head else [
        {"id": key, "body": f"A concrete {title.lower()} proposal.", "source_ids": [], "items": []}
        for key, title in TEMPLATES[kind]]
    if not head and kind == "prd":
        for s in sections:
            if s["id"] in ("stories", "requirements", "guardrails", "success"):
                s["items"] = [{"id": "new-" + s["id"], "statement": "Persist the current named view.",
                               "verification": "Reload the browser and verify that the same filters are restored.", "references": []}]
    sections = [{k: s[k] for k in ("id", "body", "source_ids", "items")} for s in sections if not scoped or s["id"] == scoped]
    result = {"summary": "Added a saved views proposal.", "sections": sections, "questions": [], "assumptions": [],
              "coverage": [{"module": m, "status": "not_material", "rationale": "No external contract changes for this bounded local feature."} for m in RFC_MODULES] if kind == "rfc" else []}
    result.update(updates)
    return Generation.model_validate(result)


def finish(studio, state, result=None, generator=None):
    op = next(o for o in state["operations"] if o["status"] == "queued")
    studio.run(state["id"], op["id"], generator or (lambda s, o, h, u: (
        Clarification(summary="The brief has enough direction.") if o["action"] == "clarify" else result or generated(o["kind"], h, o["section_id"]), [], "test-provider")))
    return studio.get(state["id"])


def draft(studio):
    return finish(studio, create(studio))


def publish(studio, state, kind="prd"):
    if any(not b.startswith('Review and acknowledge') for b in state['documents'][kind]['blockers']):
        return command(studio, state, "publish", kind=kind, version_id=state['documents'][kind]['head'])
    for review in state['documents'][kind]['publication_review']:
        if not review['acknowledgement'] and not review['requires_deferral'] and not review['legacy_published']:
            state = acknowledge(studio, state, review['id'], kind=kind)
    return command(studio, state, "publish", kind=kind, version_id=state["documents"][kind]["head"])


def acknowledge(studio, state, group, disposition='confirmed', text='', kind='prd'):
    return command(studio, state, 'acknowledge_publication', kind=kind,
                   version_id=state['documents'][kind]['head'], review_group=group, disposition=disposition, text=text)


def test_request_is_durable_on_failure_and_retry(studio):
    state = create(studio)
    def fail(*_):
        raise RuntimeError("provider offline")
    failed = finish(studio, state, generator=fail)
    assert failed["messages"][0]["text"] == state["brief"]
    assert failed["operations"][0]["error"] == "provider offline"
    assert failed["documents"]["prd"]["head"] is None
    done = finish(studio, command(studio, failed, "retry"))
    assert done["documents"]["prd"]["snapshot"]["number"] == 1


def test_create_and_commands_are_idempotent(studio):
    req = CreateFeature(title="Saved views", brief="Persist and reopen views.", request_id=uuid4().hex)
    first = studio.create(req)
    assert studio.create(req)["id"] == first["id"]
    state = finish(studio, first)
    req = Command(action="revise", expected_revision=state["revision"], text="Change the scope", request_id=uuid4().hex)
    new = studio.command(state["id"], req)
    same = studio.command(state["id"], req)
    assert same["revision"] == new["revision"]
    assert len(same["operations"]) == 3


def test_compare_and_swap_prevents_stale_writer(studio):
    state = draft(studio)
    command(studio, state, "comment", section_id="scope", version_id=state["documents"]["prd"]["head"], text="Clarify scope")
    with pytest.raises(StudioError, match="workspace changed"):
        publish(studio, state)


@pytest.mark.parametrize("kind", ["prd", "design", "rfc"])
def test_direct_edits_are_rendered_and_published_exactly(studio, kind):
    state = publish(studio, draft(studio))
    if kind != "prd":
        state = finish(studio, command(studio, state, "generate", kind=kind))
    snap = state["documents"][kind]["snapshot"]
    section = snap["sections"][0]["id"]
    state = command(studio, state, "edit", kind=kind, section_id=section, version_id=snap["id"], text="Exact author wording with a Unicode decision: café.")
    state = publish(studio, state, kind)
    published = studio.version(state["id"], state["documents"][kind]["published"])
    assert "Exact author wording with a Unicode decision: café." in markdown(published, state["title"])
    assert studio.version(state["id"], snap["id"])["sections"][0]["body"] != published["sections"][0]["body"]


def test_published_versions_survive_more_than_twenty_edits(studio):
    state = publish(studio, draft(studio))
    published_id = state["documents"]["prd"]["published"]
    original = studio.version(state["id"], published_id)
    for n in range(24):
        state = command(studio, state, "edit", section_id="scope", version_id=state["documents"]["prd"]["head"], text=f"Scope revision {n}")
    assert studio.version(state["id"], published_id) == original
    assert len(state["documents"]["prd"]["versions"]) == 25
    with studio.store.transaction() as conn:
        with pytest.raises(sqlite3.IntegrityError, match="Immutable"):
            conn.execute("DELETE FROM snapshots WHERE id=?", (published_id,))


def test_entity_ids_survive_reorder_and_are_never_recycled(studio):
    state = draft(studio)
    original = state["documents"]["prd"]["snapshot"]["sections"][5]["items"][0]
    added = {**original, "id": "new-extra", "statement": "Rename a saved view."}
    state = command(studio, state, "edit", section_id="requirements", version_id=state["documents"]["prd"]["head"], text="Requirements", items=[added, original])
    rows = state["documents"]["prd"]["snapshot"]["sections"][5]["items"]
    assert [r["id"] for r in rows] == ["REQ-2", "REQ-1"]
    state = command(studio, state, "edit", section_id="requirements", version_id=state["documents"]["prd"]["head"], text="Requirements", items=[rows[1]])
    state = command(studio, state, "edit", section_id="requirements", version_id=state["documents"]["prd"]["head"], text="Requirements", items=[original, added])
    assert [r["id"] for r in state["documents"]["prd"]["snapshot"]["sections"][5]["items"]] == ["REQ-1", "REQ-3"]


def test_section_request_cannot_change_another_section(studio):
    state = draft(studio)
    old = state["documents"]["prd"]["head"]
    queued = command(studio, state, "revise", section_id="scope", text="Reduce scope")
    failed = finish(studio, queued, result=generated(head=state["documents"]["prd"]["snapshot"]))
    assert failed["documents"]["prd"]["head"] == old
    assert "another section" in failed["operations"][-1]["error"]


def test_whole_document_requests_preserve_direct_edits(studio):
    state = draft(studio)
    state = command(studio, state, "edit", section_id="scope", version_id=state["documents"]["prd"]["head"], text="Human-only scope")
    result = generated(head=state["documents"]["prd"]["snapshot"])
    next(s for s in result.sections if s.id == "scope").body = "Model tried to replace the scope"
    state = finish(studio, command(studio, state, "revise", text="Make this more concise"), result=result)
    assert next(s for s in state["documents"]["prd"]["snapshot"]["sections"] if s["id"] == "scope")["body"] == "Human-only scope"


def test_source_reconciliation_keeps_old_pins_and_reviews_protected_text(studio):
    state = publish(studio, draft(studio))
    old_prd = state["documents"]["prd"]["published"]
    state = finish(studio, command(studio, state, "generate", kind="design"))
    state = command(studio, state, "edit", kind="design", section_id="intent", version_id=state["documents"]["design"]["head"], text="Our chosen interaction")
    old_design = state["documents"]["design"]["head"]
    state = command(studio, state, "edit", section_id="scope", version_id=state["documents"]["prd"]["head"], text="A new product constraint")
    state = publish(studio, state)
    assert state["documents"]["design"]["stale"] == ["prd"]
    assert studio.version(state["id"], old_design)["pins"]["prd"] == old_prd
    state = finish(studio, command(studio, state, "reconcile", kind="design"))
    assert state["documents"]["design"]["stale"] == []
    assert "protected section" in " ".join(state["documents"]["design"]["blockers"])
    state = command(studio, state, "review_section", kind="design", section_id="intent", version_id=state["documents"]["design"]["head"])
    assert publish(studio, state, "design")["documents"]["design"]["published"]


def test_rfc_requires_a_current_published_design_only_when_selected(studio):
    state = publish(studio, draft(studio))
    state = finish(studio, command(studio, state, "generate", kind="design"))
    with pytest.raises(StudioError, match="Publish the Design"):
        command(studio, state, "generate", kind="rfc", source_mode="prd_design")
    state = publish(studio, state, "design")
    state = command(studio, state, "edit", section_id="scope", version_id=state["documents"]["prd"]["head"], text="New scope")
    state = publish(studio, state)
    with pytest.raises(StudioError, match="Reconcile and publish Design"):
        command(studio, state, "generate", kind="rfc", source_mode="prd_design")


def test_addressing_comment_does_not_resolve_it(studio):
    state = draft(studio)
    head = state["documents"]["prd"]["head"]
    state = command(studio, state, "comment", section_id="scope", version_id=head, text="Clarify excluded scope", quote="A concrete scope proposal.", blocking=True)
    comment_id = state["comments"][0]["id"]
    state = finish(studio, command(studio, state, "revise", comment_id=comment_id))
    assert state["comments"][0]["status"] == "addressed"
    assert state["comments"][0]["version_id"] == head
    with pytest.raises(StudioError, match="Resolve blocking comment"):
        publish(studio, state)
    state = command(studio, state, "resolve", comment_id=comment_id)
    assert publish(studio, state)["documents"]["prd"]["published"]


def test_outdated_quote_cannot_be_silently_applied(studio):
    state = draft(studio)
    state = command(studio, state, "comment", section_id="scope", version_id=state["documents"]["prd"]["head"], quote="A concrete scope proposal.", text="Change this")
    state = command(studio, state, "edit", section_id="scope", version_id=state["documents"]["prd"]["head"], text="Different scope")
    assert state["comments"][0]["outdated"]
    with pytest.raises(StudioError, match="quoted text changed"):
        command(studio, state, "revise", comment_id=state["comments"][0]["id"])


def test_cancelled_late_result_cannot_overwrite_newer_work(studio):
    state = create(studio)
    entered, release = Event(), Event()
    def delayed(*args):
        entered.set(); release.wait(timeout=5)
        return generated(), [], "test-provider"
    with ThreadPoolExecutor() as pool:
        job = pool.submit(finish, studio, state, generator=delayed)
        assert entered.wait(timeout=5)
        current = studio.get(state["id"])
        state = command(studio, current, "cancel")
        release.set(); job.result(timeout=5)
    assert studio.get(state["id"])["documents"]["prd"]["head"] is None


def test_restart_retains_request_and_marks_interrupted(studio):
    state = create(studio)
    studio.recover()
    state = studio.get(state["id"])
    assert state["operations"][0]["status"] == "interrupted"
    assert state["messages"][0]["text"] == state["brief"]
    assert finish(studio, command(studio, state, "retry"))["documents"]["prd"]["head"]


def test_exact_version_and_placeholders_are_checked_at_publication(studio):
    state = draft(studio)
    old = state["documents"]["prd"]["head"]
    state = command(studio, state, "edit", section_id="scope", version_id=old, text="TBD")
    with pytest.raises(StudioError, match="exact current revision"):
        command(studio, state, "publish", version_id=old)
    with pytest.raises(StudioError, match="unfinished placeholders"):
        publish(studio, state)
    with pytest.raises(StudioError, match="older version"):
        command(studio, state, "edit", section_id="scope", version_id=old, text="Attempted stale edit")


def test_scoped_edit_preserves_unrelated_blocking_decisions(studio):
    state = draft(studio)
    state = finish(studio, command(studio, state, "revise", text="Consider another persistence option"), result=generated(head=state["documents"]["prd"]["snapshot"], questions=[{"id":"storage", "question":"Where is data stored?", "why":"Data loss risk", "blocking":True, "section_id":"requirements"}]))
    state = finish(studio, command(studio, state, "revise", section_id="summary", text="Shorten the summary"))
    assert state["documents"]["prd"]["snapshot"]["questions"][0]["id"] == "storage"


def test_restore_is_new_revision_and_keeps_old_sources(studio):
    state = draft(studio)
    old = state["documents"]["prd"]["head"]
    state = command(studio, state, "edit", section_id="summary", version_id=old, text="New summary")
    state = command(studio, state, "restore", version_id=old)
    assert state["documents"]["prd"]["snapshot"]["number"] == 3
    assert state["documents"]["prd"]["head"] != old
    assert state["documents"]["prd"]["snapshot"]["sections"] == studio.version(state["id"], old)["sections"]


def test_unverified_evidence_keeps_a_visible_provisional_draft_and_blocks_publication(studio):
    payload = generated()
    payload.sections[0].source_ids = ["S-invented"]
    state = finish(studio, create(studio), result=payload)
    assert state["documents"]["prd"]["snapshot"]["sections"][0]["unverified_source_ids"] == ["S-invented"]
    assert state["documents"]["prd"]["snapshot"]["sections"][0]["source_ids"] == []
    with pytest.raises(StudioError, match="unavailable evidence"):
        publish(studio, state)
    state = publish(studio, finish(studio, command(studio, state, "revise", text="Remove unsupported references")))
    state = finish(studio, command(studio, state, "generate", kind="rfc"), result=generated("rfc", coverage=[]))
    assert state["documents"]["rfc"]["head"] is None
    assert "every conditional" in state["operations"][-1]["error"]


def test_rfc_coverage_cannot_block_a_prd(studio):
    state = finish(studio, create(studio), result=generated(coverage=[{"module":"rollout", "status":"unresolved", "rationale":"Not supplied"}]))
    assert state["documents"]["prd"]["snapshot"]["coverage"] == []
    assert publish(studio, state)["documents"]["prd"]["published"]


def test_snapshot_and_operation_completion_roll_back_together(studio, monkeypatch):
    state = create(studio)
    save = studio.store.save
    def fail_completion(conn, state):
        if state["operations"][-1]["status"] == "completed":
            raise OSError("simulated disk write failure")
        save(conn, state)
    monkeypatch.setattr(studio.store, "save", fail_completion)
    state = finish(studio, state)
    assert state["operations"][-1]["status"] == "failed"
    assert state["documents"]["prd"]["head"] is None
    assert state["messages"][0]["text"] == state["brief"]
    with studio.store.transaction() as conn:
        assert conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 0


def test_unresolved_material_rfc_decision_blocks_only_publication(studio):
    state = publish(studio, draft(studio))
    result = generated("rfc")
    result.coverage[0].status = "unresolved"
    state = finish(studio, command(studio, state, "generate", kind="rfc"), result=result)
    assert state["documents"]["rfc"]["head"] is not None
    with pytest.raises(StudioError, match="Decide RFC coverage"):
        publish(studio, state, "rfc")


def test_first_draft_journey_ids_are_allocated_by_the_application(studio):
    state = publish(studio, draft(studio))
    result = generated("design")
    journey = next(s for s in result.sections if s.id == "journeys")
    journey.body = "Follow J-1 to save a view."
    journey.items = [Item(id="J-1", statement="Save a view", verification="View appears", references=["REQ-1"])]
    result = Generation.model_validate(result.model_dump())
    state = finish(studio, command(studio, state, "generate", kind="design"), result=result)
    journey = next(s for s in state["documents"]["design"]["snapshot"]["sections"] if s["id"] == "journeys")
    assert journey["items"][0]["id"] == "D-1"
    assert journey["items"][0]["references"] == ["REQ-1"]
    assert "D-1" in journey["body"]


def test_cancelled_initial_request_can_be_retried(studio):
    state = command(studio, create(studio), "cancel")
    state = finish(studio, command(studio, state, "retry"))
    assert state["documents"]["prd"]["head"] is not None


def test_timeout_does_not_expose_provider_command_or_prompt(studio):
    def timeout(*_):
        raise subprocess.TimeoutExpired(["provider", "--system-prompt", "internal prompt"], 360)
    state = finish(studio, create(studio), generator=timeout)
    message = state["operations"][-1]["error"]
    assert "request and current document are saved" in message
    assert "system-prompt" not in message


def test_manual_edit_rejects_dangling_requirement_references(studio):
    state = draft(studio)
    item = copy.deepcopy(state["documents"]["prd"]["snapshot"]["sections"][5]["items"][0])
    item["references"] = ["US-999"]
    with pytest.raises(StudioError, match="unavailable entity"):
        command(studio, state, "edit", section_id="requirements", version_id=state["documents"]["prd"]["head"], text="Requirements", items=[item])
    assert studio.get(state["id"])["revision"] == state["revision"]


def clarification(count=2):
    return Clarification.model_validate({"summary": "Clarify audience and scope before drafting.", "questions": [
        {"id": f"q-{i}", "question": f"Who should use workflow {i}?", "why": "The answer determines access and scope.",
         "options": [{"label": label, "description": description} for label, description in [
             ("Personal", "Only the author uses this workflow."), ("Team", "People in the same team can use it."),
             ("Organization", "Everyone in the organization can use it.")]]} for i in range(count)]})


def awaiting_answers(studio, count=2):
    state = create(studio)
    calls = []
    def check(s, operation, *_):
        calls.append(operation["action"])
        assert operation["action"] == "clarify", "A PRD must not be generated before answers."
        return clarification(count), [], "test-provider"
    state = finish(studio, state, generator=check)
    assert calls == ["clarify"]
    return state


def test_brief_check_saves_questions_without_generating_any_prd(studio):
    state = create(studio)
    assert state["operations"][0]["action"] == "clarify"
    state = awaiting_answers(studio)
    assert state["intake"]["status"] == "awaiting_answers"
    assert len(state["intake"]["questions"][0]["options"]) == 3
    assert not state["documents"]["prd"]["head"]
    assert not state["documents"]["prd"]["versions"]
    with studio.store.transaction() as conn:
        assert conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 0
    with pytest.raises(StudioError, match="every clarification"):
        command(studio, state, "generate")


def test_complete_brief_proceeds_directly_through_check_to_generation(studio):
    calls = []
    def provider(state, op, *_):
        calls.append(op["action"])
        return (Clarification(summary="The brief is sufficient.") if op["action"] == "clarify" else generated()), [], "test-provider"
    state = finish(studio, create(studio), generator=provider)
    assert calls == ["clarify", "generate"]
    assert state["intake"]["questions"] == []
    assert state["documents"]["prd"]["snapshot"]["number"] == 1


def test_answers_survive_reload_and_only_final_answer_queues_generation(studio):
    state = awaiting_answers(studio)
    state = command(studio, state, "answer_clarification", question_id="q-0", choice="option-2", text="Ignored client substitution")
    reloaded = Studio(studio.root).get(state["id"])
    assert reloaded["intake"]["answers"]["q-0"]["text"] == "Team: People in the same team can use it."
    assert not any(o["status"] == "queued" for o in reloaded["operations"])
    assert reloaded["documents"]["prd"]["head"] is None
    state = command(studio, reloaded, "answer_clarification", question_id="q-0", choice="option-1")
    assert state["intake"]["answers"]["q-0"]["choice"] == "option-1"
    state = command(studio, state, "answer_clarification", question_id="q-1", choice="custom", text="  Invite-only reviewers.  ")
    assert state["intake"]["status"] == "ready"
    assert state["operations"][-1]["action"] == "generate"
    def provider(s, *_):
        assert s["intake"]["answers"]["q-1"]["text"] == "Invite-only reviewers."
        assert s["intake"]["answers"]["q-0"]["choice"] == "option-1"
        return generated(), [], "test-provider"
    assert finish(studio, state, generator=provider)["documents"]["prd"]["head"]


def test_clarification_rejects_blank_unknown_and_stale_answers(studio):
    state = awaiting_answers(studio)
    with pytest.raises(StudioError, match="1 to 4,000"):
        command(studio, state, "answer_clarification", question_id="q-0", choice="custom", text="   ")
    with pytest.raises(StudioError, match="current clarification"):
        command(studio, state, "answer_clarification", question_id="unknown", choice="option-1")
    updated = command(studio, state, "answer_clarification", question_id="q-0", choice="option-1")
    with pytest.raises(StudioError, match="workspace changed"):
        command(studio, state, "answer_clarification", question_id="q-1", choice="option-1")
    assert len(updated["intake"]["answers"]) == 1


def test_final_answer_is_idempotent_and_failed_generation_retains_answers(studio):
    state = awaiting_answers(studio, 1)
    answer = Command(action="answer_clarification", question_id="q-0", choice="custom", text="Only feature owners.",
                     request_id=uuid4().hex, expected_revision=state["revision"])
    state = studio.command(state["id"], answer)
    assert studio.command(state["id"], answer)["revision"] == state["revision"]
    assert len(state["operations"]) == 2
    def fail(*_):
        raise RuntimeError("provider unavailable")
    state = finish(studio, state, generator=fail)
    assert state["intake"]["answers"]["q-0"]["text"] == "Only feature owners."
    state = command(studio, state, "retry")
    assert state["operations"][-1]["action"] == "generate"
    assert finish(studio, state)["documents"]["prd"]["head"]


def test_brief_check_cancellation_discards_late_questions(studio):
    state = create(studio)
    entered, release = Event(), Event()
    def delayed(*_):
        entered.set(); release.wait(timeout=5)
        return clarification(), [], "test-provider"
    with ThreadPoolExecutor() as pool:
        job = pool.submit(finish, studio, state, generator=delayed)
        assert entered.wait(timeout=5)
        command(studio, studio.get(state["id"]), "cancel")
        release.set(); job.result(timeout=5)
    state = studio.get(state["id"])
    assert state["intake"]["questions"] == []
    assert state["documents"]["prd"]["head"] is None


def test_initial_prd_cannot_save_new_unanswered_questions(studio):
    result = generated(questions=[{"id":"unexpected", "question":"Who is this for?", "why":"Audience", "blocking":False}])
    state = finish(studio, create(studio), result=result)
    assert state["documents"]["prd"]["head"] is None
    assert "unanswered questions" in state["operations"][-1]["error"]


def test_generator_uses_clarification_schema_and_all_saved_answers(studio, monkeypatch):
    from dashboard.backend import llm
    from lib.authoring_studio.generator import Generator
    from lib.authoring_studio.models import InitialPRD
    import json
    calls = []
    monkeypatch.setattr(llm, "read_model_config", lambda _: {"provider":"claude-code", "support_model":"sonnet"})
    def complete(**kwargs):
        calls.append(kwargs)
        return clarification(1) if kwargs["response_model"] is Clarification else generated()
    monkeypatch.setattr(llm, "llm_complete", complete)
    state = finish(studio, create(studio), generator=Generator(studio.root))
    state = command(studio, state, "answer_clarification", question_id="q-0", choice="custom", text="Only invited editors, no public access.")
    state = finish(studio, state, generator=Generator(studio.root))
    assert [c["response_model"] for c in calls] == [Clarification, InitialPRD]
    payload = json.loads(calls[1]["messages"][1]["content"])
    evidence = next(s for s in payload["evidence"] if s["label"] == "Author's clarification answers")
    assert "Only invited editors, no public access." in evidence["text"]
    assert any(s["id"] == evidence["id"] for s in state["documents"]["prd"]["snapshot"]["sources"])


def test_publication_requires_both_author_reviews_even_with_complete_content(studio):
    state = draft(studio)
    version = state['documents']['prd']['head']
    with pytest.raises(StudioError, match='Success.*Open questions'):
        command(studio, state, 'publish', version_id=version)
    state = acknowledge(studio, state, 'success')
    with pytest.raises(StudioError, match='Open questions'):
        command(studio, state, 'publish', version_id=version)
    state = acknowledge(studio, state, 'open_questions')
    assert state['documents']['prd']['head'] == version
    assert len(state['documents']['prd']['versions']) == 1
    assert not state['documents']['prd']['blockers']
    state = command(studio, state, 'publish', version_id=version)
    assert len(state['documents']['prd']['publications'][0]['reviews']) == 2


def test_success_identifies_exact_row_and_requires_explicit_deferral(studio):
    payload = generated()
    payload.sections[9].items[0].verification = 'Target and measurement method are unknown/TBD; owner unknown.'
    state = finish(studio, create(studio), result=payload)
    review = state['documents']['prd']['publication_review'][0]
    assert review['requires_deferral']
    assert review['findings'][0]['location'] == 'SM-1 · Verification / outcome'
    assert review['findings'][0]['anchor'] == 'item-SM-1'
    assert 'unknown/TBD' in review['findings'][0]['excerpt']
    with pytest.raises(StudioError, match='Unresolved details remain'):
        acknowledge(studio, state, 'success')
    with pytest.raises(StudioError, match='Explain what remains open'):
        acknowledge(studio, state, 'success', 'deferred', '  ')
    state = acknowledge(studio, state, 'success', 'deferred', 'The product owner will set a target after two weeks of baseline data.')
    state = publish(studio, state)
    doc = state['documents']['prd']
    assert 'unknown/TBD' in doc['snapshot']['sections'][9]['items'][0]['verification']
    exported = markdown(doc['snapshot'], state['title'], saved_reviews(doc, doc['head']))
    assert 'Unresolved details acknowledged' in exported
    assert 'two weeks of baseline data' in exported


def test_open_question_acknowledgement_keeps_question_and_survives_restart(studio):
    state = draft(studio)
    result = generated(head=state['documents']['prd']['snapshot'], questions=[{
        'id':'q-owner', 'question':'Who owns rollout?', 'why':'Follow-up responsibility.', 'blocking':True, 'section_id':'risks'}])
    state = finish(studio, command(studio, state, 'revise', text='Record the remaining question'), result=result)
    with pytest.raises(StudioError, match='Unresolved details remain'):
        acknowledge(studio, state, 'open_questions')
    state = acknowledge(studio, state, 'open_questions', 'deferred', 'Assign rollout ownership at the planning meeting before delivery starts.')
    reloaded = Studio(studio.root).get(state['id'])
    assert reloaded['documents']['prd']['publication_review'][1]['acknowledgement']['note'].startswith('Assign rollout')
    state = publish(studio, reloaded)
    assert state['documents']['prd']['snapshot']['questions'][0]['blocking'] is True
    output = markdown(state['documents']['prd']['snapshot'], state['title'], saved_reviews(state['documents']['prd'], state['documents']['prd']['head']))
    assert '[Acknowledged as unresolved] Who owns rollout?' in output


def test_edit_restore_and_ai_revision_each_require_fresh_reviews(studio):
    state = publish(studio, draft(studio))
    original_version = state['documents']['prd']['head']
    frozen_reviews = copy.deepcopy(state['documents']['prd']['publications'][0]['reviews'])
    state = command(studio, state, 'edit', section_id='scope', version_id=original_version, text='Updated scope')
    assert all(r['acknowledgement'] is None for r in state['documents']['prd']['publication_review'])
    with pytest.raises(StudioError, match='current document version'):
        command(studio, state, 'acknowledge_publication', review_group='success', disposition='confirmed', version_id=original_version)
    state = publish(studio, state)
    state = command(studio, state, 'restore', version_id=original_version)
    assert all(r['acknowledgement'] is None for r in state['documents']['prd']['publication_review'])
    state = publish(studio, state)
    state = finish(studio, command(studio, state, 'revise', section_id='summary', text='Shorten summary'))
    assert all(r['acknowledgement'] is None for r in state['documents']['prd']['publication_review'])
    assert saved_reviews(state['documents']['prd'], original_version) == frozen_reviews


def test_reviews_are_idempotent_revocable_and_fixed_at_publication(studio):
    state = draft(studio)
    req = Command(action='acknowledge_publication', expected_revision=state['revision'], request_id=uuid4().hex,
                  version_id=state['documents']['prd']['head'], review_group='success', disposition='confirmed')
    state = studio.command(state['id'], req)
    assert studio.command(state['id'], req)['revision'] == state['revision']
    assert len(state['documents']['prd']['review_history']) == 1
    state = command(studio, state, 'revoke_publication_review', version_id=state['documents']['prd']['head'], review_group='success')
    assert state['documents']['prd']['publication_review'][0]['acknowledgement'] is None
    state = publish(studio, state)
    with pytest.raises(StudioError, match='Published acknowledgements are fixed'):
        command(studio, state, 'revoke_publication_review', version_id=state['documents']['prd']['head'], review_group='success')


def test_acknowledgements_do_not_override_content_or_comment_blockers(studio):
    state = draft(studio)
    state = command(studio, state, 'edit', section_id='requirements', version_id=state['documents']['prd']['head'], text='todo: define the behavior')
    state = acknowledge(studio, state, 'success')
    state = acknowledge(studio, state, 'open_questions')
    state = command(studio, state, 'comment', section_id='scope', version_id=state['documents']['prd']['head'], text='Scope needs review', blocking=True)
    with pytest.raises(StudioError, match='Requirements and acceptance / Section text.*todo.*Resolve blocking comment'):
        command(studio, state, 'publish', version_id=state['documents']['prd']['head'])


def test_plain_unknown_success_and_prose_open_decisions_are_reviewable(studio):
    payload = generated()
    payload.sections[9].items[0].verification = 'No target defined; owner unassigned.'
    payload.sections[8].body = 'Rollout ownership is not yet assigned.'
    state = finish(studio, create(studio), result=payload)
    assert all(g['requires_deferral'] for g in state['documents']['prd']['publication_review'])
    assert state['documents']['prd']['snapshot']['questions'] == []


def test_legacy_published_snapshot_remains_valid_but_next_version_requires_review(studio):
    state = draft(studio)
    with studio.store.transaction() as conn:
        old = studio._read(conn, state['id'])
        doc = old['documents']['prd']
        doc['published'] = doc['head']
        doc['publications'] = [{'version_id':doc['head'], 'created_at':'before-review-feature'}]
        studio._save(conn, old)
    state = studio.get(state['id'])
    assert all(g['legacy_published'] for g in state['documents']['prd']['publication_review'])
    assert state['documents']['prd']['blockers'] == []
    state = command(studio, state, 'edit', section_id='scope', version_id=state['documents']['prd']['head'], text='New scope')
    assert all(not g['legacy_published'] for g in state['documents']['prd']['publication_review'])
    assert len(state['documents']['prd']['blockers']) == 2


def test_downstream_generation_receives_frozen_author_review_notes(studio, monkeypatch):
    import json
    from dashboard.backend import llm
    from lib.authoring_studio.generator import Generator
    state = draft(studio)
    state = acknowledge(studio, state, 'success', 'deferred', 'Measure the baseline before agreeing a target with the product owner.')
    state = publish(studio, state)
    calls = []
    monkeypatch.setattr(llm, 'read_model_config', lambda _: {'provider':'claude-code', 'support_model':'sonnet'})
    def complete(**kwargs):
        calls.append(kwargs)
        return Clarification(summary='The published PRD provides enough context.') if kwargs['response_model'] is Clarification else generated('design')
    monkeypatch.setattr(llm, 'llm_complete', complete)
    state = finish(studio, command(studio, state, 'generate', kind='design'), generator=Generator(studio.root))
    payload = json.loads(calls[0]['messages'][1]['content'])
    upstream = next(s for s in payload['evidence'] if s['label'].startswith('Published PRD'))
    assert 'Measure the baseline before agreeing a target' in upstream['text']
    assert 'Unresolved details acknowledged' in upstream['text']
    assert [r['id'] for r in state['documents']['design']['publication_review']] == ['open_questions']


@pytest.mark.parametrize('kind', ['design', 'rfc'])
def test_start_directly_with_any_document_and_clarify_before_drafting(studio, kind):
    state = studio.create(CreateFeature(kind=kind, title='Task reminders', brief='Remind owners before a personal task is due.', request_id=uuid4().hex))
    assert state['initial_kind'] == kind
    assert state['operations'][0]['kind'] == kind
    state = finish(studio, state, generator=lambda *_: (clarification(1), [], 'test'))
    assert state['intakes'][kind]['status'] == 'awaiting_answers'
    assert all(d['head'] is None for d in state['documents'].values())
    with pytest.raises(StudioError, match='Answer every clarification'):
        command(studio, state, 'generate', kind=kind, source_mode='brief')
    state = command(studio, state, 'answer_clarification', kind=kind, question_id='q-0', choice='custom', text='Personal reminders only; no team sharing.')
    state = finish(studio, state, result=generated(kind))
    assert state['documents'][kind]['snapshot']['source_mode'] == 'brief'
    assert state['documents'][kind]['snapshot']['pins'] == {}
    assert state['documents']['prd']['head'] is None
    state = publish(studio, state, kind)
    assert state['documents'][kind]['published']
    assert state['documents']['prd']['published'] is None


@pytest.mark.parametrize('design_status', ['draft', 'published', 'stale'])
def test_prd_to_rfc_can_skip_design_in_any_state(studio, design_status):
    state = publish(studio, draft(studio))
    state = finish(studio, command(studio, state, 'generate', kind='design'))
    if design_status != 'draft':
        state = publish(studio, state, 'design')
    if design_status == 'stale':
        state = command(studio, state, 'edit', section_id='scope', version_id=state['documents']['prd']['head'], text='Add a new product constraint.')
        state = publish(studio, state)
    design_head = state['documents']['design']['head']
    state = finish(studio, command(studio, state, 'generate', kind='rfc', source_mode='prd'))
    assert state['documents']['rfc']['snapshot']['pins'] == {'prd':state['documents']['prd']['published']}
    assert state['documents']['rfc']['snapshot']['source_mode'] == 'prd'
    assert state['documents']['design']['head'] == design_head
    assert state['documents']['rfc']['stale'] == []
    if design_status == 'draft':
        state = publish(studio, state, 'design')
        assert state['documents']['rfc']['stale'] == []


def test_standalone_documents_do_not_gain_implicit_upstream_dependencies(studio):
    state = studio.create(CreateFeature(kind='rfc', title='Storage proposal', brief='Persist personal views locally with safe recovery.', request_id=uuid4().hex))
    state = finish(studio, state)
    rfc_head = state['documents']['rfc']['head']
    state = publish(studio, finish(studio, command(studio, state, 'generate', kind='prd')))
    state = publish(studio, finish(studio, command(studio, state, 'generate', kind='design')), 'design')
    assert state['documents']['rfc']['head'] == rfc_head
    assert state['documents']['rfc']['snapshot']['pins'] == {}
    assert state['documents']['rfc']['stale'] == []
    state = finish(studio, command(studio, state, 'reconcile', kind='rfc'))
    assert state['documents']['rfc']['snapshot']['source_mode'] == 'brief'


def test_intakes_and_saved_answers_are_independent_per_document(studio):
    state = studio.create(CreateFeature(kind='design', title='Saved views', brief='Reopen personal saved filters quickly.', request_id=uuid4().hex))
    state = finish(studio, state, generator=lambda *_: (clarification(1), [], 'test'))
    state = finish(studio, command(studio, state, 'generate', kind='prd'))
    assert state['intakes']['design']['status'] == 'awaiting_answers'
    assert state['intakes']['prd']['status'] == 'ready'
    state = command(studio, state, 'answer_clarification', kind='design', question_id='q-0', choice='option-2')
    state = finish(studio, state)
    assert state['documents']['design']['head'] and state['documents']['prd']['head']
    assert state['intakes']['prd']['answers'] == {}
    assert state['intakes']['design']['answers']['q-0']['choice'] == 'option-2'
    assert next(m for m in state['messages'] if m.get('question_id') == 'q-0')['kind'] == 'design'


def test_rfc_can_use_a_standalone_published_design_without_a_prd(studio):
    state = studio.create(CreateFeature(kind='design', title='Saved views', brief='Reopen personal saved filters quickly.', request_id=uuid4().hex))
    state = publish(studio, finish(studio, state), 'design')
    state = finish(studio, command(studio, state, 'generate', kind='rfc', source_mode='design'))
    assert state['documents']['rfc']['snapshot']['pins'] == {'design':state['documents']['design']['published']}
    assert state['documents']['prd']['head'] is None


def test_retry_preserves_selected_sources_while_other_documents_are_published(studio):
    state = publish(studio, draft(studio))
    old_prd = state['documents']['prd']['published']
    state = command(studio, state, 'generate', kind='rfc', source_mode='prd')
    def fail_generation(s, o, h, u):
        if o['action'] == 'clarify':
            return Clarification(summary='Ready to draft.'), [], 'test'
        raise RuntimeError('provider disconnected')
    state = finish(studio, state, generator=fail_generation)
    assert state['operations'][-1]['status'] == 'failed'
    state = publish(studio, finish(studio, command(studio, state, 'generate', kind='design')), 'design')
    state = command(studio, state, 'edit', section_id='scope', version_id=old_prd, text='A revised constraint')
    state = publish(studio, state)
    state = finish(studio, command(studio, state, 'retry', kind='rfc'))
    assert state['documents']['rfc']['snapshot']['pins'] == {'prd':old_prd}
    assert state['documents']['rfc']['stale'] == ['prd']
    state = finish(studio, command(studio, state, 'reconcile', kind='rfc'))
    assert state['documents']['rfc']['snapshot']['pins'] == {'prd':state['documents']['prd']['published']}
    assert state['documents']['rfc']['stale'] == []


@pytest.mark.parametrize('kind', ['design', 'rfc'])
def test_direct_generation_provider_receives_correct_contract_without_invented_prd(studio, monkeypatch, kind):
    import json
    from dashboard.backend import llm
    from lib.authoring_studio.generator import Generator
    from lib.authoring_studio.models import INITIAL_DOCUMENT_MODELS
    calls = []
    monkeypatch.setattr(llm, 'read_model_config', lambda _: {'provider':'claude-code', 'support_model':'sonnet'})
    def complete(**kwargs):
        calls.append(kwargs)
        return Clarification(summary='The brief is complete.') if kwargs['response_model'] is Clarification else generated(kind)
    monkeypatch.setattr(llm, 'llm_complete', complete)
    state = studio.create(CreateFeature(kind=kind,title='Saved views',brief='Persist personal named filter views locally.',request_id=uuid4().hex))
    state = finish(studio, state, generator=Generator(studio.root))
    assert [c['response_model'] for c in calls] == [Clarification, INITIAL_DOCUMENT_MODELS[kind]]
    payload = json.loads(calls[-1]['messages'][1]['content'])
    assert payload['document_kind'] == kind and payload['upstream'] == {}
    assert payload['source_mode'] == 'brief'
    assert all(not s['label'].startswith('Published PRD') for s in payload['evidence'])
    assert state['documents'][kind]['head']


def test_selected_document_sources_must_be_published_and_acyclic(studio):
    state = draft(studio)
    with pytest.raises(StudioError, match='Publish the PRD'):
        command(studio, state, 'generate', kind='rfc', source_mode='prd')
    with pytest.raises(StudioError, match='Choose sources supported'):
        command(studio, state, 'generate', kind='design', source_mode='design')
    state = finish(studio, command(studio, state, 'generate', kind='rfc', source_mode='brief'))
    assert state['documents']['rfc']['head']


def test_design_only_rfc_tracks_the_selected_designs_own_prd_dependency(studio):
    state = publish(studio, draft(studio))
    state = publish(studio, finish(studio, command(studio, state, 'generate', kind='design')), 'design')
    state = finish(studio, command(studio, state, 'generate', kind='rfc', source_mode='design'))
    state = command(studio, state, 'edit', section_id='scope', version_id=state['documents']['prd']['head'], text='A new product requirement')
    state = publish(studio, state)
    assert state['documents']['design']['stale'] == ['prd']
    assert state['documents']['rfc']['stale'] == ['design']
    with pytest.raises(StudioError, match='Reconcile and publish Design spec'):
        command(studio, state, 'reconcile', kind='rfc')


def test_source_availability_checks_published_design_not_its_reconciled_draft(studio):
    state = publish(studio, draft(studio))
    state = publish(studio, finish(studio, command(studio, state, 'generate', kind='design')), 'design')
    state = command(studio, state, 'edit', section_id='scope', version_id=state['documents']['prd']['head'], text='A new product requirement')
    state = publish(studio, state)
    state = finish(studio, command(studio, state, 'reconcile', kind='design'))
    assert state['documents']['design']['stale'] == []
    assert state['documents']['design']['published_stale'] == ['prd']
    with pytest.raises(StudioError, match='Reconcile and publish Design spec'):
        command(studio, state, 'generate', kind='rfc', source_mode='prd_design')
