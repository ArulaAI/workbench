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
from lib.authoring_studio.models import Command, CreateFeature, Generation, Item, RFC_MODULES, TEMPLATES
from lib.authoring_studio.service import markdown


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
    studio.run(state["id"], op["id"], generator or (lambda s, o, h, u: (result or generated(o["kind"], h, o["section_id"]), [], "test-provider")))
    return studio.get(state["id"])


def draft(studio):
    return finish(studio, create(studio))


def publish(studio, state, kind="prd"):
    return command(studio, state, "publish", kind=kind, version_id=state["documents"][kind]["head"])


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
    assert len(same["operations"]) == 2


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


def test_rfc_requires_a_current_published_design_when_design_exists(studio):
    state = publish(studio, draft(studio))
    state = finish(studio, command(studio, state, "generate", kind="design"))
    with pytest.raises(StudioError, match="Publish the Design"):
        command(studio, state, "generate", kind="rfc")
    state = publish(studio, state, "design")
    state = command(studio, state, "edit", section_id="scope", version_id=state["documents"]["prd"]["head"], text="New scope")
    state = publish(studio, state)
    with pytest.raises(StudioError, match="Reconcile and publish Design"):
        command(studio, state, "generate", kind="rfc")


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
    state = finish(studio, create(studio), result=generated(questions=[{"id":"storage", "question":"Where is data stored?", "why":"Data loss risk", "blocking":True, "section_id":"requirements"}]))
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
    assert state["operations"][0]["status"] == "failed"
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
