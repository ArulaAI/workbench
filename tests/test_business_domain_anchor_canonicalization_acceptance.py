"""F-06 production acceptance: canonical entry-point identity and aliases."""
from __future__ import annotations

import copy
import json
import uuid
from collections import defaultdict
from pathlib import Path

import pytest

from lib.context.business_domain_adapters.base import MAX_SEMANTIC_CANDIDATES
from lib.context.business_domain_extract import Extractor
from lib.context.business_domain_identity import reconcile_anchors
from lib.context.business_domain_schema import (
    DEFAULTS,
    copy_facts,
    identifier,
    record,
    validate,
    validate_references,
)
from lib.context.business_domain_synthesis import packet_for
from lib.context.business_domains import accept_activity


OPENAPI = """openapi: 3.0.1
info:
  title: Pets
  version: '1'
paths:
  /api/pets/{id}:
    get:
      operationId: getPet
      responses:
        '200':
          description: pet
"""

PETS_API = """
package app;
import org.springframework.web.bind.annotation.GetMapping;
public interface PetsApi {
  @GetMapping("/api/pets/{id}") String getPet(int id);
}
"""

PET_CONTROLLER = """
package app;
import org.springframework.web.bind.annotation.RestController;
@RestController
public class PetController implements PetsApi {
  public String getPet(int id) { return "pet"; }
}
"""


def _extract(root: Path, files: dict[str, str]):
    for name, source in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
    facts, units = Extractor(root, DEFAULTS).extract()
    validate(facts, "FactsArtifact")
    validate_references(facts)
    return facts, units


def _representations(facts):
    return [representation for anchor in facts["anchors"].values()
            for representation in anchor["representations"]]


def _correspondences(facts):
    return [correspondence for anchor in facts["anchors"].values()
            for correspondence in anchor["correspondences"]]


def _operation(name="same", method="GET", route="/same"):
    return record("Operation", protocol="http", name=name, method=method,
                  path=route, service_resource_id="resource:service")


def _representation(ident, role, identity_key, eligibility, source="resource:service"):
    return record(
        "AnchorRepresentation",
        id="anchor_representation:" + ident,
        role=role,
        identity_key=identity_key,
        source_id=source,
        symbol_id="symbol:" + ident,
        operation=_operation(),
        eligibility=eligibility,
        visibility="external" if eligibility == "eligible" else "internal",
        evidence_ids=["ev:" + ident],
        resolution="resolved",
        reason=None,
    )


def _anchor(ident, representation):
    return record(
        "Anchor",
        id="anchor:" + ident,
        kind="http",
        source_id=representation["source_id"],
        symbol_id=representation["symbol_id"],
        operation=representation["operation"],
        status="candidate",
        evidence_ids=representation["evidence_ids"],
        resolution="resolved",
        reason=None,
        representations=[representation],
    )


def _correspondence(ident, source, targets, state="resolved"):
    return record(
        "AnchorCorrespondence",
        id="anchor_correspondence:" + ident,
        from_representation=source["id"],
        to_representations=[target["id"] for target in targets],
        relationship_edges=["edge:" + ident],
        state=state,
        evidence_ids=sorted(source["evidence_ids"] + [eid for target in targets
                                                       for eid in target["evidence_ids"]]),
        reason="Exact normalized relationship evidence.",
    )


def test_ac01_same_name_without_relationship_never_merges(tmp_path):
    api = OPENAPI + """
  /api/owners/{id}:
    get:
      operationId: getPet
      responses:
        '200':
          description: owner
"""
    facts, _ = _extract(tmp_path, {"openapi.yaml": api})

    named = [anchor for anchor in facts["anchors"].values()
             if anchor["operation"]["name"] == "getPet"]
    assert len(named) == 2
    assert len({anchor["id"] for anchor in named}) == 2
    assert len({representation["identity_key"] for anchor in named
                for representation in anchor["representations"]}) == 2


def test_ac02_openapi_interface_and_controller_form_one_canonical_anchor(tmp_path):
    facts, _ = _extract(tmp_path, {
        "openapi.yaml": OPENAPI,
        "src/app/PetsApi.java": PETS_API,
        "src/app/PetController.java": PET_CONTROLLER,
    })

    matching = [anchor for anchor in facts["anchors"].values()
                if anchor["operation"]["method"] == "GET"
                and anchor["operation"]["path"] == "/api/pets/{id}"]
    assert len(matching) == 1
    anchor = matching[0]
    assert anchor["canonical_anchor_id"] == anchor["id"]
    assert {item["role"] for item in anchor["representations"]} >= {
        "contract", "implementation"}
    assert len(anchor["representations"]) >= 3
    assert all(item["evidence_ids"] for item in anchor["representations"])


def test_ac03_missing_generated_interface_remains_explicitly_unresolved(tmp_path):
    controller = PET_CONTROLLER.replace("PetsApi", "GeneratedPetsApi")
    facts, _ = _extract(tmp_path, {
        "openapi.yaml": OPENAPI,
        "src/app/PetController.java": controller,
    })

    relevant = [anchor for anchor in facts["anchors"].values()
                if anchor["operation"]["name"] == "getPet"]
    assert len(relevant) >= 2
    assert not any({item["source_id"] for item in anchor["representations"]}
                   == {item["source_id"] for candidate in relevant
                       for item in candidate["representations"]}
                   for anchor in relevant)
    assert any(anchor["resolution"] != "resolved"
               or any(item["state"] in {"unresolved", "ambiguous"}
                      for item in anchor["correspondences"])
               for anchor in relevant)


def test_ac04_two_implementations_remain_bounded_and_ambiguous(tmp_path):
    second = PET_CONTROLLER.replace("PetController", "OtherPetController")
    facts, _ = _extract(tmp_path, {
        "openapi.yaml": OPENAPI,
        "src/app/PetsApi.java": PETS_API,
        "src/app/PetController.java": PET_CONTROLLER,
        "src/app/OtherPetController.java": second,
    })

    ambiguous = [item for item in _correspondences(facts)
                 if item["state"] == "ambiguous"]
    assert ambiguous
    assert all(2 <= len(item["to_representations"]) <= MAX_SEMANTIC_CANDIDATES
               for item in ambiguous)
    assert all(item["reason"] and item["evidence_ids"] for item in ambiguous)


def test_ac05_unmatched_contract_stays_visible_and_semantically_unresolved(tmp_path):
    facts, _ = _extract(tmp_path, {"openapi.yaml": OPENAPI})

    assert len(facts["anchors"]) == 1
    anchor = next(iter(facts["anchors"].values()))
    assert {item["role"] for item in anchor["representations"]} == {"contract"}
    assert not any(item["role"] == "implementation" for item in anchor["representations"])
    trace = next(item for item in facts["traces"].values()
                 if item["anchor_id"] == anchor["id"])
    assert trace["resolution"] == "unresolved"


def test_ac06_directly_registered_implementation_is_canonical(tmp_path):
    facts, _ = _extract(tmp_path, {"src/app/HealthController.java": """
        package app;
        import org.springframework.web.bind.annotation.RestController;
        import org.springframework.web.bind.annotation.GetMapping;
        @RestController public class HealthController {
          @GetMapping("/health") public String health() { return "ok"; }
        }
    """})

    assert len(facts["anchors"]) == 1
    anchor = next(iter(facts["anchors"].values()))
    assert anchor["canonical_anchor_id"] == anchor["id"]
    assert anchor["eligibility"] == "eligible"
    assert anchor["operation"]["method"] == "GET"
    assert anchor["operation"]["path"] == "/health"


def test_ac07_every_contract_interface_and_implementation_representation_survives(tmp_path):
    facts, _ = _extract(tmp_path, {
        "openapi.yaml": OPENAPI,
        "src/app/PetsApi.java": PETS_API,
        "src/app/PetController.java": PET_CONTROLLER,
    })
    anchor = next(anchor for anchor in facts["anchors"].values()
                  if anchor["operation"]["path"] == "/api/pets/{id}")
    representations = anchor["representations"]

    assert len(representations) >= 3
    assert len({item["id"] for item in representations}) == len(representations)
    assert all(item["source_id"] in facts["resources"] for item in representations)
    assert all(item["symbol_id"] in facts["symbols"] for item in representations)
    assert {eid for item in representations for eid in item["evidence_ids"]} <= set(facts["evidence"])


def test_ac08_resolved_pair_occurs_once_with_complete_alias_trace_scope(tmp_path):
    facts, _ = _extract(tmp_path, {
        "openapi.yaml": OPENAPI,
        "src/app/PetsApi.java": PETS_API,
        "src/app/PetController.java": PET_CONTROLLER,
    })
    matching = [anchor for anchor in facts["anchors"].values()
                if anchor["operation"]["path"] == "/api/pets/{id}"]
    assert len(matching) == 1
    anchor = matching[0]
    packet = packet_for(facts, "activity", [anchor["id"]])

    assert packet["anchor_ids"] == [anchor["id"]]
    assert list(packet["context"]["anchors"]) == [anchor["id"]]
    supplied = packet["context"]["anchors"][anchor["id"]]
    assert {item["id"] for item in supplied["representations"]} == {
        item["id"] for item in anchor["representations"]}
    assert len([trace for trace in packet["context"]["traces"].values()
                if trace["anchor_id"] == anchor["id"]]) == 1


def test_ac09_distinct_entrypoints_can_share_one_activity(tmp_path):
    facts, _ = _extract(tmp_path, {"service.py": """
@app.get('/orders')
def list_orders():
    return []

@app.post('/orders')
def create_order():
    return {}
"""})
    anchor_ids = sorted(facts["anchors"])
    assert len(anchor_ids) == 2
    packet = packet_for(facts, "activity", anchor_ids)
    model = copy_facts(facts, str(uuid.uuid4()))
    trace_ids = sorted(packet["context"]["traces"])
    evidence_ids = sorted(packet["context"]["evidence"])
    activity = record(
        "Activity", id="activity:orders", name="Manage orders",
        description="List and create orders", anchor_ids=anchor_ids,
        trace_ids=trace_ids, evidence_ids=evidence_ids,
        claim_ids=["claim:orders"], support="partial",
    )
    claim = record(
        "Claim", id="claim:orders", subject_id=activity["id"],
        text=activity["description"], kind="behavior", evidence_ids=evidence_ids,
        trace_ids=trace_ids, semantic_review="uncertain",
    )
    payload = record("ActivityPayload", activities={activity["id"]: activity},
                     claims={claim["id"]: claim})

    accept_activity(model, packet, payload)
    assert model["activities"][activity["id"]]["anchor_ids"] == anchor_ids
    assert len(model["anchors"]) == 2


def test_ac10_ui_api_proposal_without_resolved_path_stays_review_required():
    ui = _representation("ui", "registration", "ui:repository:/pets", "eligible")
    api = _representation("api", "registration", "http:repository:GET:/pets", "eligible")
    ui_anchor, api_anchor = _anchor("ui", ui), _anchor("api", api)
    ui_anchor["correspondences"] = [
        _correspondence("ui-api", ui, [api], "inferred_review_required")]
    model = {"anchors": {ui_anchor["id"]: ui_anchor, api_anchor["id"]: api_anchor},
             "coverage": record("Coverage")}

    reconcile_anchors(model)

    assert len(model["anchors"]) == 2
    retained = [item for anchor in model["anchors"].values()
                for item in anchor["correspondences"]]
    assert len(retained) == 1
    assert retained[0]["state"] == "inferred_review_required"
    assert retained[0]["reason"]
    assert model["coverage"]["representations_canonicalized"] == 2
    assert len({anchor["canonical_anchor_id"]
                for anchor in model["anchors"].values()}) == 2


def test_ac11_canonical_alias_references_validate_and_round_trip(tmp_path):
    facts, _ = _extract(tmp_path, {
        "openapi.yaml": OPENAPI,
        "src/app/PetsApi.java": PETS_API,
        "src/app/PetController.java": PET_CONTROLLER,
    })
    restored = json.loads(json.dumps(facts, sort_keys=True))

    validate(restored, "FactsArtifact")
    validate_references(restored)
    for anchor in restored["anchors"].values():
        assert anchor["canonical_anchor_id"] in {None, *restored["anchors"]}
        assert all(item["source_id"] in restored["resources"]
                   and item["symbol_id"] in restored["symbols"]
                   for item in anchor["representations"])


def test_ac12_canonical_identity_is_independent_of_alias_and_source_id_order():
    contract = _representation("contract", "contract",
                               "http:repository:GET:/pets", "eligible")
    implementation = _representation("implementation", "implementation", None, "supporting")

    def reconcile(contract_id, implementation_id, reverse_representations=False):
        contract_anchor = _anchor(contract_id, copy.deepcopy(contract))
        implementation_anchor = _anchor(implementation_id, copy.deepcopy(implementation))
        contract_anchor["correspondences"] = [
            _correspondence("contract-implementation", contract,
                            [implementation], "resolved")]
        if reverse_representations:
            contract_anchor["representations"].reverse()
        model = {"anchors": {
            contract_anchor["id"]: contract_anchor,
            implementation_anchor["id"]: implementation_anchor,
        }}
        reconcile_anchors(model)
        assert len(model["anchors"]) == 1
        return next(iter(model["anchors"].values()))

    contract_first = reconcile("a-contract", "z-implementation")
    implementation_first = reconcile("z-contract", "a-implementation", True)
    expected = identifier("anchor", "canonical", "http:repository:GET:/pets")
    assert contract_first["id"] == implementation_first["id"] == expected
    assert contract_first["canonical_anchor_id"] == implementation_first["canonical_anchor_id"] == expected
    assert contract_first["eligibility"] == implementation_first["eligibility"] == "eligible"
    assert {item["id"] for item in contract_first["representations"]} == {
        item["id"] for item in implementation_first["representations"]}


def test_ac13_removing_implementation_alias_preserves_public_contract_identity(tmp_path):
    source = """CREATE OR REPLACE PACKAGE orders AS
  PROCEDURE submit(order_id IN NUMBER);
END orders;
/
CREATE OR REPLACE PACKAGE BODY orders AS
  PROCEDURE submit(order_id IN NUMBER) IS BEGIN NULL; END submit;
END orders;
/
"""
    facts, _ = _extract(tmp_path, {"orders.sql": source})
    canonical = next(iter(facts["anchors"].values()))
    canonical_id = canonical["id"]
    assert {item["role"] for item in canonical["representations"]} == {
        "contract", "implementation"}

    facts, _ = _extract(tmp_path, {"orders.sql": source.split("CREATE OR REPLACE PACKAGE BODY")[0]})
    remaining = next(iter(facts["anchors"].values()))
    assert remaining["id"] == canonical_id
    assert {item["role"] for item in remaining["representations"]} == {"contract"}


def test_ac14_coverage_separates_representations_canonical_anchors_and_gaps(tmp_path):
    facts, _ = _extract(tmp_path, {
        "openapi.yaml": OPENAPI,
        "src/app/PetsApi.java": PETS_API,
        "src/app/PetController.java": PET_CONTROLLER,
        "src/app/MissingController.java": PET_CONTROLLER
            .replace("PetController", "MissingController")
            .replace("PetsApi", "MissingApi"),
    })
    coverage = facts["coverage"]
    representations = _representations(facts)
    correspondences = _correspondences(facts)

    assert coverage["representations_total"] == len(representations)
    assert coverage["anchors_total"] == len(facts["anchors"])
    assert coverage["representations_canonicalized"] == sum(
        anchor["canonical_anchor_id"] is not None
        for anchor in facts["anchors"].values()
        for _ in anchor["representations"])
    assert coverage["correspondences_ambiguous"] == sum(
        item["state"] == "ambiguous" for item in correspondences)
    assert coverage["correspondences_unresolved"] == sum(
        item["state"] == "unresolved" for item in correspondences)


PETCLINIC = Path("/private/tmp/speed-domain-petclinic")


@pytest.mark.skipif(not PETCLINIC.is_dir(), reason="PetClinic trial repository is unavailable")
def test_ac15_petclinic_http_correspondence_groups_are_explained():
    facts = Extractor(PETCLINIC, DEFAULTS).extract()[0]
    validate_references(facts)
    resources = facts["resources"]
    by_name = defaultdict(list)
    for anchor in facts["anchors"].values():
        for representation in anchor["representations"]:
            operation = representation["operation"]
            if operation and operation["protocol"] == "http":
                by_name[operation["name"]].append((anchor, representation))

    dual_source = {}
    for name, members in by_name.items():
        paths = {resources[item[1]["source_id"]]["name"] for item in members}
        if any(path.endswith((".yml", ".yaml")) for path in paths) \
                and any(path.endswith(".java") for path in paths):
            dual_source[name] = members
    assert len(dual_source) == 34
    for members in dual_source.values():
        anchors = {item[0]["id"]: item[0] for item in members}
        explained = len(anchors) == 1 or any(
            correspondence["state"] in {"ambiguous", "unresolved"}
            for anchor in anchors.values()
            for correspondence in anchor["correspondences"])
        assert explained


def test_ac16_java_and_python_endpoint_shapes_are_language_independent(tmp_path):
    java_root, python_root = tmp_path / "java", tmp_path / "python"
    java, _ = _extract(java_root, {"HealthController.java": """
        import org.springframework.web.bind.annotation.RestController;
        import org.springframework.web.bind.annotation.GetMapping;
        @RestController class HealthController {
          @GetMapping("/health") String health() { return "ok"; }
        }
    """})
    python, _ = _extract(python_root, {"health.py": """
@app.get('/health')
def health():
    return 'ok'
"""})
    java_anchor = next(iter(java["anchors"].values()))
    python_anchor = next(iter(python["anchors"].values()))

    assert java_anchor["id"] == python_anchor["id"]
    assert {key: value for key, value in java_anchor["operation"].items()
            if key != "service_resource_id"} == {
                key: value for key, value in python_anchor["operation"].items()
                if key != "service_resource_id"}
    assert set(java_anchor) == set(python_anchor)
    assert {key for key in java_anchor["representations"][0]} == {
        key for key in python_anchor["representations"][0]}
    assert not any(language in Path(__file__).parents[1]
                   .joinpath("lib/context/business_domain_identity.py").read_text().lower()
                   for language in ("java", "python", "spring", "openapi"))


def test_ac17_sql_package_spec_and_body_have_one_public_canonical_identity(tmp_path):
    facts, _ = _extract(tmp_path, {"orders.sql": """
CREATE OR REPLACE PACKAGE orders AS
  PROCEDURE submit(order_id IN NUMBER);
END orders;
/
CREATE OR REPLACE PACKAGE BODY orders AS
  PROCEDURE submit(order_id IN NUMBER) IS BEGIN NULL; END submit;
END orders;
/
"""})

    assert len(facts["anchors"]) == 1
    anchor = next(iter(facts["anchors"].values()))
    assert anchor["canonical_anchor_id"] == anchor["id"]
    assert {item["role"] for item in anchor["representations"]} == {
        "contract", "implementation"}
    assert {item["visibility"] for item in anchor["representations"]} == {
        "public", "internal"}
    assert len(anchor["evidence_ids"]) >= 2


def test_ac18_sql_body_only_private_helper_is_not_an_entrypoint(tmp_path):
    facts, units = _extract(tmp_path, {"orders.sql": """
CREATE OR REPLACE PACKAGE orders AS
  PROCEDURE submit(order_id IN NUMBER);
END orders;
/
CREATE OR REPLACE PACKAGE BODY orders AS
  PROCEDURE helper(order_id IN NUMBER) IS BEGIN NULL; END helper;
  PROCEDURE submit(order_id IN NUMBER) IS BEGIN helper(order_id); END submit;
END orders;
/
"""})

    helper_unit = next(unit for unit in units if unit.name == "helper")
    helper = facts["symbols"][helper_unit.symbol_id]
    assert helper["evidence_ids"] and set(helper["evidence_ids"]) <= set(facts["evidence"])
    assert not any(anchor["symbol_id"] == helper["id"]
                   or any(item["symbol_id"] == helper["id"]
                          and item["eligibility"] == "eligible"
                          for item in anchor["representations"])
                   for anchor in facts["anchors"].values())
