"""F-07 production acceptance: evidenced entry-point eligibility."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from lib.context.business_domain_adapters import rules
from lib.context.business_domain_adapters.base import (
    Unit,
    declare_anchor_representation,
    declare_trace_contract,
)
from lib.context.business_domain_extract import Extractor
from lib.context.business_domain_schema import (
    DEFAULTS,
    DomainError,
    validate,
    validate_references,
)


PETCLINIC = Path("/private/tmp/speed-domain-petclinic")
GROCERY = Path("/private/tmp/speed-domain-grocery")
PETCLINIC_ROUTES = {
    "/": "WelcomePage",
    "/owners/list": "FindOwnersPage",
    "/owners/new": "NewOwnerPage",
    "/owners/:ownerId/edit": "EditOwnerPage",
    "/owners/:ownerId/pets/:petId/edit": "EditPetPage",
    "/owners/:ownerId/pets/new": "NewPetPage",
    "/owners/:ownerId/pets/:petId/visits/new": "VisitsPage",
    "/owners/:ownerId": "OwnersPage",
    "/vets": "VetsPage",
    "/error": "ErrorPage",
    "*": "NotFoundPage",
}


def _extract(root: Path, files: dict[str, str]):
    for name, source in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
    facts, units = Extractor(root, DEFAULTS).extract()
    validate(facts, "FactsArtifact")
    validate_references(facts)
    return facts, units


@pytest.fixture(scope="module")
def petclinic():
    if not PETCLINIC.is_dir():
        pytest.skip("PetClinic trial repository is unavailable")
    result = Extractor(PETCLINIC, DEFAULTS).extract()
    validate_references(result[0])
    return result


@pytest.fixture(scope="module")
def grocery():
    if not GROCERY.is_dir():
        pytest.skip("Grocery trial repository is unavailable")
    result = Extractor(GROCERY, DEFAULTS).extract()
    validate_references(result[0])
    return result


def _representations(facts):
    return [representation for anchor in facts["anchors"].values()
            for representation in anchor["representations"]]


def _registered(facts, kind: str):
    return [(anchor, representation)
            for anchor in facts["anchors"].values()
            for representation in anchor["representations"]
            if representation.get("registration")
            and representation["registration"]["kind"] == kind
            and (kind not in {"route", "action"}
                 or representation["operation"]["protocol"] == "ui")]


def _evidence_text(facts, evidence_ids):
    return "\n".join(facts["evidence"][key]["excerpt"] for key in evidence_ids)


def _symbol_ids_for_files(facts, suffixes):
    return {symbol["id"] for symbol in facts["symbols"].values()
            if any(symbol["file"].endswith(suffix) for suffix in suffixes)}


def _represented_symbols(facts):
    return {representation["symbol_id"] for representation in _representations(facts)
            if representation["symbol_id"]}


def test_ac01_jsx_only_helper_is_supporting_evidence_not_an_anchor(tmp_path):
    facts, units = _extract(tmp_path, {"Helper.tsx": """
export function Helper() { return <span>internal</span>; }
"""})

    helper = next(unit for unit in units if unit.name == "Helper")
    assert helper.symbol_id in facts["symbols"]
    assert helper.anchor_kind is None and helper.anchor_id is None
    assert helper.anchor_role == "implementation"
    assert helper.anchor_eligibility == "supporting"
    assert not facts["anchors"]


def test_ac02_petclinic_all_eleven_static_routes_are_exact_registration_anchors(petclinic):
    facts, _ = petclinic
    routes = _registered(facts, "route")

    assert len(routes) == 11
    assert {representation["operation"]["path"] for _, representation in routes} \
        == set(PETCLINIC_ROUTES)
    for anchor, representation in routes:
        path = representation["operation"]["path"]
        assert representation["operation"]["name"] == PETCLINIC_ROUTES[path]
        assert path in _evidence_text(facts, representation["registration"]["evidence_ids"])
        assert anchor["eligibility"] == "eligible"


def test_ac03_each_petclinic_route_selects_its_exact_component(petclinic):
    facts, _ = petclinic
    routes = _registered(facts, "route")
    assert len(routes) == 11
    for anchor, registration in routes:
        expected = PETCLINIC_ROUTES[registration["operation"]["path"]]
        implementations = [item for item in anchor["representations"]
                           if item["role"] == "implementation"]
        assert len(implementations) == 1
        symbol = facts["symbols"][implementations[0]["symbol_id"]]
        assert (expected in symbol["qualified_name"]
                or symbol["signature"].startswith(expected + "("))
        links = [facts["edges"][edge_id]
                 for correspondence in anchor["correspondences"]
                 if correspondence["state"] == "resolved"
                 for edge_id in correspondence["relationship_edges"]]
        assert any(edge["kind"] == "selects_implementation"
                   and edge["to_ref"]["id"] == symbol["id"] for edge in links)


def test_ac04_route_registry_is_registration_evidence_not_a_user_activity(petclinic):
    facts, _ = petclinic
    registry = next(symbol for symbol in facts["symbols"].values()
                    if symbol["qualified_name"].endswith("configureRoutes.default"))

    assert registry["id"] not in {anchor["symbol_id"] for anchor in facts["anchors"].values()}
    assert registry["id"] not in _represented_symbols(facts)
    assert len([item for item in _registered(facts, "route")
                if item[1]["source_id"] == next(resource["id"]
                    for resource in facts["resources"].values()
                    if resource["name"] == "client/src/configureRoutes.tsx")]) == 11


def test_ac05_routed_views_receive_resolved_route_context(petclinic):
    facts, _ = petclinic
    expected = {
        "/owners/:ownerId": "OwnersPage",
        "/owners/:ownerId/pets/:petId/visits/new": "VisitsPage",
    }
    for path, target in expected.items():
        anchor, registration = next(item for item in _registered(facts, "route")
                                    if item[1]["operation"]["path"] == path)
        assert registration["registration"]["target"] == target
        assert registration["registration"]["resolution"] == "resolved"
        trace = next(trace for trace in facts["traces"].values()
                     if trace["anchor_id"] == anchor["id"])
        assert any(path == pattern["pattern"]
                   for element in trace["ui_interaction"]["elements"].values()
                   for pattern in element["route_patterns"] or [])
        assert len([item for item in anchor["representations"]
                    if item["role"] == "implementation"]) == 1


def test_ac06_add_visit_action_keeps_label_handler_and_owning_route(petclinic):
    facts, _ = petclinic
    matches = [(anchor, representation) for anchor, representation in _registered(facts, "action")
               if representation["registration"]["label"] == "Add Visit"]

    assert len(matches) == 1
    anchor, action = matches[0]
    registration = action["registration"]
    assert registration["event"] == "onClick"
    assert registration["target"].endswith(".onSubmit")
    assert registration["scope"] == "/owners/:ownerId/pets/:petId/visits/new"
    assert action["operation"]["name"] == "Add Visit"
    assert action["operation"]["path"] == registration["scope"]
    assert any(item["role"] == "implementation"
               and facts["symbols"][item["symbol_id"]]["signature"].startswith("onSubmit(")
               and "VisitsPage" in facts["symbols"][item["symbol_id"]]["qualified_name"]
               for item in anchor["representations"])


def test_ac07_distinct_actions_in_one_component_keep_distinct_anchor_identities(tmp_path):
    facts, _ = _extract(tmp_path, {"Routes.tsx": """
function save() { return true; }
function Editor() { return <div><button onClick={save}>Save</button><button onClick={save}>Save copy</button></div>; }
export default () => <Route path='/edit' component={Editor} />;
"""})
    actions = [(anchor, representation) for anchor, representation in _registered(facts, "action")]

    assert {item[1]["registration"]["label"] for item in actions} == {"Save", "Save copy"}
    assert len({item[0]["id"] for item in actions}) == 2
    assert len({item[1]["identity_key"] for item in actions}) == 2
    assert {item[1]["registration"]["target"] for item in actions} == {"save"}


def test_ac08_reusable_controls_are_reachable_without_standalone_anchors(petclinic):
    facts, _ = petclinic
    for component in ("Input", "DateInput", "SelectInput"):
        symbol_ids = _symbol_ids_for_files(facts, {f"/{component}.tsx"})
        assert symbol_ids
        assert not symbol_ids & {anchor["symbol_id"] for anchor in facts["anchors"].values()}
        assert any(symbol_ids & set(trace["symbol_ids"]) for trace in facts["traces"].values()
                   if facts["anchors"][trace["anchor_id"]]["kind"] == "ui")


def test_ac09_feedback_and_loading_views_are_not_render_anchors(petclinic):
    facts, _ = petclinic
    for component in ("FieldFeedbackPanel", "LoadingPanel"):
        symbol_ids = _symbol_ids_for_files(facts, {f"/{component}.tsx"})
        assert symbol_ids
        assert not symbol_ids & {anchor["symbol_id"] for anchor in facts["anchors"].values()}
        assert not symbol_ids & {item["symbol_id"] for item in _representations(facts)
                                 if item["eligibility"] == "eligible"}


def test_ac10_supporting_views_link_into_parent_interaction_paths(petclinic):
    facts, _ = petclinic
    for component in ("OwnerInformation", "PetsTable", "PetDetails"):
        symbol_ids = _symbol_ids_for_files(facts, {f"/{component}.tsx"})
        composition = [edge for edge in facts["edges"].values()
                       if edge["kind"] == "composes" and edge["to_ref"]
                       and edge["to_ref"]["id"] in symbol_ids]
        assert symbol_ids and composition
        assert all(edge["resolution"] == "resolved" and edge["evidence_ids"]
                   for edge in composition)
        assert any(edge["id"] in trace["edge_ids"] for edge in composition
                   for trace in facts["traces"].values())


def test_ac11_dynamic_route_retains_an_explicit_candidate_gap(tmp_path):
    facts, _ = _extract(tmp_path, {"Routes.tsx": """
function First() { return <div>first</div>; }
function Second() { return <div>second</div>; }
const selected = enabled ? First : Second;
export default () => <Route path={routePath} component={selected} />;
"""})
    routes = _registered(facts, "route")

    assert len(routes) == 1
    anchor, representation = routes[0]
    registration = representation["registration"]
    assert anchor["resolution"] in {"ambiguous", "unresolved"}
    assert representation["eligibility"] == "unresolved"
    assert registration["resolution"] in {"ambiguous", "unresolved"}
    assert registration["reason"] and registration["evidence_ids"]
    assert set(registration["candidate_targets"]) == {"First", "Second"}


def test_ac12_unknown_action_label_is_an_explicit_identity_gap(tmp_path):
    facts, _ = _extract(tmp_path, {"Form.tsx": """
function submit() { return true; }
function Form({caption}) { return <button onClick={submit}>{caption}</button>; }
"""})
    actions = _registered(facts, "action")

    assert len(actions) == 1
    anchor, representation = actions[0]
    registration = representation["registration"]
    assert registration["label"] is None
    assert representation["operation"]["name"] not in {"submit", "Form"}
    assert registration["resolution"] == "unresolved" and registration["reason"]
    assert anchor["resolution"] == "unresolved"


def test_ac13_frontend_producer_cannot_omit_registration_resolution(tmp_path, monkeypatch):
    def broken(source):
        unit = Unit(source, "Broken", source.path + "::Broken", 0, len(source.text),
                    "function", anchor_kind="ui", anchor_resolution="resolved",
                    anchor_reason=None, executable_body=True)
        declare_trace_contract(unit, "implementation")
        declare_anchor_representation(unit, "registration", "ui:repository:route:/broken",
                                      "eligible", "external")
        return [unit]

    monkeypatch.setattr(rules, "extract", broken)
    (tmp_path / "Broken.tsx").write_text("function Broken() { return <div/>; }")
    with pytest.raises(DomainError, match="registration"):
        Extractor(tmp_path, DEFAULTS).extract()


def test_ac14_route_and_action_aliases_are_canonical_and_evidence_preserving(petclinic):
    facts, _ = petclinic
    route = next(anchor for anchor, representation in _registered(facts, "route")
                 if representation["operation"]["path"] ==
                 "/owners/:ownerId/pets/:petId/visits/new")
    action = next(anchor for anchor, representation in _registered(facts, "action")
                  if representation["registration"]["label"] == "Add Visit")

    for anchor in (route, action):
        assert anchor["canonical_anchor_id"] == anchor["id"]
        assert {item["role"] for item in anchor["representations"]} \
            == {"registration", "implementation"}
        assert all(item["evidence_ids"] for item in anchor["representations"])
        assert any(item["state"] == "resolved" and item["relationship_edges"]
                   for item in anchor["correspondences"])


def test_ac15_disconnected_route_cannot_form_a_resolved_single_symbol_trace(tmp_path):
    facts, _ = _extract(tmp_path, {"Routes.tsx": """
export default () => <Route path='/missing' component={MissingPage} />;
"""})
    anchor, representation = next(item for item in _registered(facts, "route"))
    trace = next(trace for trace in facts["traces"].values()
                 if trace["anchor_id"] == anchor["id"])

    assert representation["registration"]["resolution"] == "unresolved"
    assert trace["resolution"] == "unresolved"
    assert not (len(trace["symbol_ids"]) == 1 and not trace["edge_ids"]
                and trace["resolution"] == "resolved")
    assert any(facts["trace_obligations"][key]["status"] != "satisfied"
               for key in trace["obligation_ids"])


def test_ac16_workload_contains_only_eligible_canonical_ui_registrations(petclinic):
    facts, units = petclinic
    ui_anchors = {anchor["id"] for anchor in facts["anchors"].values()
                  if anchor["kind"] == "ui"}
    expected = {anchor["id"] for anchor in facts["anchors"].values()
                if anchor["kind"] == "ui" and anchor["eligibility"] == "eligible"
                and anchor["canonical_anchor_id"] == anchor["id"]
                and any(item.get("registration") for item in anchor["representations"])}

    assert ui_anchors == expected
    assert len([unit for unit in units if unit.source.language == "tsx"
                and unit.anchor_eligibility == "supporting"]) > len(ui_anchors)
    assert all(anchor["symbol_id"] not in _symbol_ids_for_files(
        facts, {"/FieldFeedbackPanel.tsx", "/LoadingPanel.tsx"})
        for anchor in facts["anchors"].values())


def test_ac17_equal_targets_handlers_and_labels_do_not_merge_interactions(tmp_path):
    facts, _ = _extract(tmp_path, {"Routes.tsx": """
function First() { return <button onClick={submit}>Open</button>; }
function Second() { return <button onClick={submit}>Open</button>; }
function submit() { return true; }
export default () => <div><Route path='/one' component={First} /><Route path='/two' component={Second} /></div>;
"""})
    routes = _registered(facts, "route")
    actions = [(anchor, item) for anchor, item in _registered(facts, "action")
               if item["registration"]["label"] == "Open"]

    assert len(routes) == 2
    assert {item[1]["operation"]["path"] for item in routes} == {"/one", "/two"}
    assert len({item[0]["id"] for item in routes}) == 2
    assert len(actions) == 2 and len({item[0]["id"] for item in actions}) == 2
    assert {item[1]["registration"]["target"] for item in routes} == {"First", "Second"}
    assert {item[1]["registration"]["target"] for item in actions} == {"submit"}


def test_ac18_grocery_public_declarations_select_exact_implementations(grocery):
    facts, units = grocery
    contracts = [unit for unit in units
                 if getattr(unit, "sql_declaration_kind", None) == "package_spec"]

    assert len(contracts) == 24
    for contract in contracts:
        anchor = facts["anchors"][contract.anchor_id]
        assert {item["role"] for item in anchor["representations"]} \
            == {"contract", "implementation"}
        assert {item["visibility"] for item in anchor["representations"]} \
            == {"public", "internal"}
        assert len([edge for edge in facts["edges"].values()
                    if edge["kind"] == "selects_implementation"
                    and edge["from_ref"]["id"] == contract.symbol_id
                    and edge["resolution"] == "resolved"]) == 1


def test_ac19_grocery_private_get_hours_is_supporting_and_reached(grocery):
    facts, units = grocery
    helper = next(unit for unit in units if unit.name.casefold() == "get_hours")
    payroll = next(unit for unit in units if unit.name.casefold() == "process_payroll"
                   and getattr(unit, "sql_declaration_kind", None) == "package_body")

    assert helper.anchor_kind is None and helper.anchor_id is None
    assert helper.symbol_id in facts["symbols"]
    call = next(edge for edge in facts["edges"].values()
                if edge["kind"] == "calls"
                and edge["from_ref"]["id"] == payroll.symbol_id
                and edge["to_ref"] and edge["to_ref"]["id"] == helper.symbol_id)
    assert call["resolution"] == "resolved"
    assert any(helper.symbol_id in trace["symbol_ids"]
               for trace in facts["traces"].values()
               if trace["anchor_id"] == payroll.anchor_id)


def test_ac20_all_grocery_triggers_retain_complete_firing_identity(grocery):
    facts, _ = grocery
    triggers = {representation["operation"]["name"]: representation["registration"]
                for _, representation in _registered(facts, "database_trigger")}

    assert set(triggers) == {
        "update_job_history_trigger", "email_on_inv_trigger", "logon_trigger", "logoff_trigger"}
    expected = {
        "update_job_history_trigger": ("AFTER", "INSERT OR UPDATE OF job_id", "staff", "ROW", True),
        "email_on_inv_trigger": ("AFTER", "UPDATE OF quantity", "inventory_by_location", "ROW", True),
        "logon_trigger": ("AFTER", "LOGON", "SCHEMA", "SCHEMA", False),
        "logoff_trigger": ("BEFORE", "LOGOFF", "SCHEMA", "SCHEMA", False),
    }
    for name, (timing, event, target, scope, conditional) in expected.items():
        registration = triggers[name]
        assert registration["timing"].upper() == timing
        assert registration["event"].upper() == event.upper()
        assert registration["target"].casefold() == target.casefold()
        assert registration["scope"].upper() == scope
        assert bool(registration["condition"]) is conditional
        assert registration["evidence_ids"] and registration["resolution"] == "resolved"


def test_ac21_contract_without_body_survives_and_body_without_contract_is_not_promoted(tmp_path):
    facts, units = _extract(tmp_path, {"orders.sql": """
CREATE OR REPLACE PACKAGE orders AS
  PROCEDURE public_call(value IN NUMBER);
END orders;
/
CREATE OR REPLACE PACKAGE BODY orders AS
  PROCEDURE private_helper IS BEGIN NULL; END private_helper;
END orders;
/
"""})
    contract = next(unit for unit in units
                    if getattr(unit, "sql_declaration_kind", None) == "package_spec")
    helper = next(unit for unit in units if unit.name == "private_helper")

    assert contract.anchor_id in facts["anchors"]
    assert facts["anchors"][contract.anchor_id]["eligibility"] == "eligible"
    trace = next(trace for trace in facts["traces"].values()
                 if trace["anchor_id"] == contract.anchor_id)
    assert trace["resolution"] == "unresolved"
    assert helper.symbol_id in facts["symbols"] and helper.anchor_id is None
    assert len(facts["anchors"]) == 1


def test_ac22_react_sql_and_python_share_normalized_entrypoint_roles(tmp_path):
    facts, units = _extract(tmp_path, {
        "Routes.tsx": """
function Page() { return <span>page</span>; }
function Helper() { return <span>helper</span>; }
export default () => <Route path='/page' component={Page} />;
""",
        "service.py": """
def internal(): return 1
@app.get('/health')
def health(): return 'ok'
""",
        "routine.sql": "CREATE PROCEDURE run IS BEGIN NULL; END;\n/\n",
    })
    by_protocol = {}
    for representation in _representations(facts):
        if representation["role"] == "registration" and representation["eligibility"] == "eligible":
            by_protocol.setdefault(representation["operation"]["protocol"], representation)

    assert set(by_protocol) >= {"ui", "http", "sql"}
    common_keys = set(by_protocol["ui"])
    assert all(set(by_protocol[protocol]) == common_keys for protocol in ("http", "sql"))
    assert all(by_protocol[protocol]["role"] == "registration"
               and by_protocol[protocol]["identity_key"]
               and by_protocol[protocol]["registration"]["resolution"] == "resolved"
               for protocol in ("ui", "http", "sql"))
    internal = [unit for unit in units if unit.name in {"Helper", "internal"}]
    assert len(internal) == 2
    assert all(unit.anchor_kind is None and unit.anchor_eligibility == "supporting"
               for unit in internal)

    dynamic, _ = _extract(tmp_path / "dynamic", {"service.py": """
route_path = choose_route()
@app.get(route_path)
def dynamic_endpoint(): return 'ok'
"""})
    dynamic_anchor = next(iter(dynamic["anchors"].values()))
    dynamic_representation = dynamic_anchor["representations"][0]
    assert dynamic_anchor["resolution"] == "unresolved"
    assert dynamic_representation["role"] == "registration"
    assert dynamic_representation["eligibility"] == "unresolved"
    assert dynamic_representation["registration"]
    assert dynamic_representation["registration"]["resolution"] == "unresolved"
    assert dynamic_representation["registration"]["reason"]
    assert dynamic_representation["registration"]["evidence_ids"]


def test_ac23_common_pipeline_has_no_technology_specific_conditionals():
    root = Path(__file__).parents[1]
    common = [
        root / "lib/context/business_domain_extract.py",
        root / "lib/context/business_domain_identity.py",
        root / "lib/context/business_domain_synthesis.py",
        root / "lib/context/business_domains.py",
        root / "lib/context/business_domain_schema.py",
    ]
    forbidden = {"tsx", "react", "router", "sql", "oracle", "procedure", "trigger"}

    for path in common:
        tree = ast.parse(path.read_text())
        conditional_strings = {
            value.lower()
            for node in ast.walk(tree)
            if isinstance(node, (ast.If, ast.IfExp, ast.Match, ast.comprehension))
            for child in ast.walk(node)
            if isinstance(child, ast.Constant) and isinstance(child.value, str)
            for value in [child.value]
        }
        assert not any(word in value for word in forbidden for value in conditional_strings), path


def test_ac24_all_twenty_four_legacy_petclinic_jsx_candidates_are_accounted_for(petclinic):
    facts, units = petclinic
    legacy = [unit for unit in units if unit.source.language == "tsx"
              and getattr(unit, "ui_implementation", False)]
    eligible = {item["symbol_id"] for item in _representations(facts)
                if item["eligibility"] == "eligible" and item["symbol_id"]}

    assert len(legacy) == 24
    assert all(unit.symbol_id in facts["symbols"] for unit in legacy)
    for unit in legacy:
        assert unit.anchor_role == "implementation"
        assert ((unit.anchor_eligibility == "supporting")
                or unit.symbol_id in eligible
                or (unit.anchor_eligibility == "unresolved" and unit.anchor_reason))


def test_ac25_all_twenty_nine_legacy_grocery_bodies_have_honest_dispositions(grocery):
    facts, units = grocery
    bodies = [unit for unit in units if unit.source.path == "JTA_Packages.sql"
              and getattr(unit, "sql_declaration_kind", None)
              in {"package_body", "trigger_body"}]
    trigger_units = [unit for unit in bodies
                     if getattr(unit, "sql_routine_kind", None) == "trigger"]
    routine_bodies = [unit for unit in bodies
                      if getattr(unit, "sql_routine_kind", None) != "trigger"]
    eligible_symbols = {item["symbol_id"] for anchor in facts["anchors"].values()
                        if anchor["eligibility"] == "eligible"
                        for item in anchor["representations"] if item["symbol_id"]}
    supporting_symbols = {item["symbol_id"] for item in _representations(facts)
                          if item["eligibility"] == "supporting" and item["symbol_id"]}
    traced = {symbol_id for trace in facts["traces"].values()
              for symbol_id in trace["symbol_ids"]}

    assert len(routine_bodies) == 25 and len(trigger_units) == 4
    assert len([unit for unit in routine_bodies if unit.symbol_id in eligible_symbols]) == 24
    private = [unit for unit in routine_bodies if unit.symbol_id not in eligible_symbols]
    assert len(private) == 1 and private[0].name.casefold() == "get_hours"
    assert private[0].symbol_id in supporting_symbols | traced
    assert all(unit.symbol_id in eligible_symbols for unit in trigger_units)
    assert all(unit.symbol_id in facts["symbols"] for unit in bodies)
