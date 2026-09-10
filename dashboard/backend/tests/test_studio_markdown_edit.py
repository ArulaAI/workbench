"""Whole-document manual changes retain the authoring contract and version history."""
import copy
from uuid import uuid4

import pytest

from lib.authoring_studio import Studio, StudioError
from lib.authoring_studio.editable_markdown import editable_markdown, parse_edit, table, ITEM_COLUMNS
from lib.authoring_studio.models import Command, CreateFeature
from dashboard.backend.tests.test_authoring_studio import command, finish, generated, publish


@pytest.fixture
def studio(tmp_path):
    return Studio(tmp_path)


def draft(studio, kind="prd"):
    return finish(studio, studio.create(CreateFeature(title="Markdown editing", kind=kind, brief="Save and restore personal filters.", request_id=uuid4().hex)))


def edit(studio, state, text, kind="prd"):
    return command(studio, state, "edit_document", kind=kind, version_id=state["documents"][kind]["head"], markdown=text)


@pytest.mark.parametrize("kind", ["prd", "design", "rfc"])
def test_roundtrip_and_multisection_save_preserve_source_history_and_reviews(studio, kind):
    state = publish(studio, draft(studio, kind), kind)
    head = state["documents"][kind]["snapshot"]
    text = editable_markdown(head)
    assert parse_edit(text, head) == head
    unchanged = edit(studio, state, text, kind)
    assert unchanged["documents"][kind]["head"] == head["id"]
    first, second = head["sections"][:2]
    text = text.replace(first["body"], "First author change.").replace(second["body"], "Second author change.")
    state = edit(studio, unchanged, text, kind)
    doc = state["documents"][kind]
    saved = doc["snapshot"]
    assert saved["number"] == head["number"] + 1
    assert doc["published"] == head["id"]
    assert studio.version(state["id"], head["id"]) == head
    assert [s["protected"] for s in saved["sections"]] == [True, True] + [False] * (len(saved["sections"]) - 2)
    assert saved["sources"] == head["sources"] and saved["pins"] == head["pins"]
    assert all(not r["acknowledgement"] for r in doc["publication_review"])


def test_roundtrip_prose_lists_code_tables_and_entities():
    head = {"kind":"prd", "sections":[{"id":"scope", "title":"Scope", "body": "Intro.\n\n# Generated internal heading\n\n- First\n- Second\n\n1. One\n2. Two\n\n```md\n# This is code\n| ID | Statement | Verification / outcome | References |\n```\n\n> # A quote\n\n## A subsection\n\n| Choice | Value |\n| --- | --- |\n| API | `hex` |\n", "items":[{"id":"REQ-1", "statement":"  A | B \\| C &amp; **bold** <br> café\nNext line  ", "verification":"`check()` & < > |", "references":[]}], "source_ids":[], "protected":False, "needs_review":True}], "assumptions":["Assume A\n& B | C"], "questions":[{"id":"q1", "question":"Where?", "why":"To decide | storage", "blocking":True, "section_id":"scope"}], "coverage":[]}
    assert parse_edit(editable_markdown(head), head) == head


def test_ids_add_remove_reorder_and_references_are_atomic(studio):
    state = draft(studio)
    head = state["documents"]["prd"]["snapshot"]
    text = editable_markdown(head)
    old = next(s for s in head["sections"] if s["id"] == "requirements")["items"][0]
    original_row = table(ITEM_COLUMNS, [[old["id"], old["statement"], old["verification"], ""]]).splitlines()[-1]
    text = text.replace(original_row, "| new-api | Return a hex code | Verify the API field | US-1 |\n" + original_row)
    state = edit(studio, state, text)
    new = state["documents"]["prd"]["snapshot"]
    items = next(s for s in new["sections"] if s["id"] == "requirements")["items"]
    assert [i["id"] for i in items] == ["REQ-2", old["id"]]
    assert items[0]["references"] == ["US-1"]
    before = copy.deepcopy(state)
    with pytest.raises(StudioError, match="unavailable entity"):
        edit(studio, state, editable_markdown(new).replace("| Verify the API field | US-1 |", "| Verify the API field | US-999 |"))
    assert studio.get(state["id"]) == before


@pytest.mark.parametrize("transform", [
    lambda s: s.replace("# Summary", "# Renamed summary"),
    lambda s: s + "\n# Scope\n\nDuplicate",
    lambda s: s.replace("| Verification / outcome |", "| Removed column |"),
    lambda s: "Discarded preamble\n" + s,
])
def test_invalid_markdown_never_silently_drops_content(studio, transform):
    state = draft(studio)
    with pytest.raises(StudioError):
        edit(studio, state, transform(editable_markdown(state["documents"]["prd"]["snapshot"])))
    assert studio.get(state["id"]) == state


def test_custom_sections_survive_ai_and_can_be_revised_and_removed(studio):
    state = draft(studio)
    text = editable_markdown(state["documents"]["prd"]["snapshot"]) + "\n# API notes\n\nBackend returns a hex code.\n"
    state = edit(studio, state, text)
    new = state["documents"]["prd"]["snapshot"]["sections"][-1]
    state = finish(studio, command(studio, state, "revise", text="Review the document"))
    assert state["documents"]["prd"]["snapshot"]["sections"][-1] == new
    state = finish(studio, command(studio, state, "revise", section_id=new["id"], text="Explain hex values"), generator=lambda s,o,h,u: (generated(head=h, scoped=new["id"]), [], "test-provider"))
    head = state["documents"]["prd"]["snapshot"]
    assert head["sections"][-1]["id"] == new["id"]
    state = edit(studio, state, editable_markdown(head).split("\n# API notes")[0])
    assert all(s["id"] != new["id"] for s in state["documents"]["prd"]["snapshot"]["sections"])


def test_stale_version_and_lost_response_retry(studio):
    state = draft(studio)
    head = state["documents"]["prd"]["snapshot"]
    request = Command(action="edit_document", version_id=head["id"], expected_revision=state["revision"], request_id=uuid4().hex, markdown=editable_markdown(head).replace("# Scope\n", "# Scope\n\nAdded direction.\n"))
    saved = studio.command(state["id"], request)
    assert studio.command(state["id"], request)["documents"]["prd"]["head"] == saved["documents"]["prd"]["head"]
    with pytest.raises(StudioError, match="document changed"):
        command(studio, saved, "edit_document", version_id=head["id"], markdown=request.markdown)
    assert studio.get(state["id"]) == saved


def test_whole_rfc_edit_cannot_drop_coverage(studio):
    state = draft(studio, "rfc")
    text = editable_markdown(state["documents"]["rfc"]["snapshot"])
    with pytest.raises(StudioError, match="every area"):
        edit(studio, state, text.split("# RFC coverage")[0], "rfc")


def test_markdown_http_edit_supports_large_documents_without_ai(studio, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from dashboard.backend.studio import StudioAPI
    state = draft(studio)
    head = state["documents"]["prd"]["snapshot"]
    api = StudioAPI(tmp_path)
    app = FastAPI(); app.include_router(api.router)
    try:
        with TestClient(app) as client:
            path = f"/studio/features/{state['id']}"
            result = client.get(f"{path}/versions/{head['id']}/editable")
            assert result.status_code == 200
            text = result.json()["markdown"]
            text = text.replace("A concrete summary proposal.", "Long author content. " * 650).replace("A concrete scope proposal.", "More author content. " * 650)
            assert len(text) > 20000
            response = client.post(path + "/commands", json={"action":"edit_document", "markdown":text, "expected_revision":state["revision"], "version_id":head["id"], "request_id":uuid4().hex})
            assert response.status_code == 200, response.text
            saved = response.json()
            assert saved["documents"]["prd"]["snapshot"]["number"] == 2
            assert len(saved["operations"]) == len(state["operations"])
            assert client.get(f"{path}/versions/{head['id']}/editable").json() == result.json()
    finally:
        api.close()
