"""Unit tests for lib/context/repository_digest_api_data.py — Phase 4
API & Data (routes, entities, persistence summary).
"""

from __future__ import annotations

import sys
from pathlib import Path

_project_root = str(Path(__file__).parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from lib.context.repository_digest_api_data import (
    _extract_python_routes,
    _extract_js_ts_routes,
    _extract_java_routes,
    derive_routes,
    derive_entities,
    derive_persistence_summary,
)


# ── Route extraction ────────────────────────────────────────────


class TestPythonRoutes:
    def test_fastapi_decorator_route(self):
        code = '@router.get("/users/{id}")\ndef get_user(id: int):\n    pass\n'
        routes = _extract_python_routes(code, "app.py")
        assert len(routes) == 1
        assert routes[0]["method"] == "GET"
        assert routes[0]["path"] == "/users/{id}"
        assert routes[0]["handler"] == "get_user"
        assert routes[0]["framework"] == "fastapi_or_flask"
        assert routes[0]["evidence"][0]["path"] == "app.py"

    def test_flask_route_decorator_with_methods(self):
        code = '@app.route("/legacy", methods=["GET", "POST"])\ndef legacy():\n    pass\n'
        routes = _extract_python_routes(code, "app.py")
        methods = {r["method"] for r in routes}
        assert methods == {"GET", "POST"}
        assert all(r["path"] == "/legacy" for r in routes)

    def test_flask_route_decorator_defaults_to_get(self):
        code = '@app.route("/ping")\ndef ping():\n    pass\n'
        routes = _extract_python_routes(code, "app.py")
        assert routes[0]["method"] == "GET"

    def test_strawberry_resolver_is_not_an_http_route(self):
        code = "@strawberry.field\ndef domains(self) -> list:\n    pass\n"
        routes = _extract_python_routes(code, "types.py")
        assert routes[0]["method"] == "QUERY"
        assert routes[0]["framework"] == "strawberry_graphql"
        assert routes[0]["handler"] == "domains"

    def test_strawberry_mention_in_a_docstring_with_no_real_decorator_is_not_a_route(self):
        # Regression: tests/prototype_clustering_v3.py has a docstring
        # literally describing "@strawberry.mutation / @strawberry.field
        # decorated functions" as prose, not real decorators. Without a
        # following def, this must not be reported as a route at all —
        # not even as a placeholder "(unnamed resolver)".
        code = (
            'def helper():\n'
            '    """\n'
            '    Python side: @strawberry.mutation / @strawberry.field decorated functions\n'
            '    """\n'
            '    return None\n'
        )
        routes = _extract_python_routes(code, "prototype.py")
        assert routes == []

    def test_no_decorators_yields_no_routes(self):
        code = "def helper():\n    pass\n"
        assert _extract_python_routes(code, "util.py") == []


class TestJsTsRoutes:
    def test_express_call_route(self):
        code = "app.get('/api/users', handler);\n"
        routes = _extract_js_ts_routes(code, "app.js")
        assert routes[0] == {
            "method": "GET", "path": "/api/users", "file": "app.js", "line": 1,
            "handler": "", "framework": "express",
            "evidence": routes[0]["evidence"],
        }

    def test_nestjs_decorator_combines_controller_prefix(self):
        code = "@Controller('cats')\nclass CatsController {\n  @Get(':id')\n  find() {}\n}\n"
        routes = _extract_js_ts_routes(code, "cats.controller.ts")
        assert routes[0]["method"] == "GET"
        assert routes[0]["path"] == "/cats/:id"
        assert routes[0]["framework"] == "nestjs"

    def test_nestjs_decorator_without_prior_controller_has_no_prefix(self):
        code = "@Post('/x')\ncreate() {}\n"
        routes = _extract_js_ts_routes(code, "orphan.ts")
        assert routes[0]["path"] == "/x"

    def test_no_calls_yields_no_routes(self):
        assert _extract_js_ts_routes("const x = 1;\n", "util.ts") == []


class TestJavaRoutes:
    def test_class_and_method_mapping_combine_prefix(self):
        code = (
            '@RestController\n@RequestMapping("/api/owners")\nclass OwnerController {\n'
            '    @GetMapping("/{id}")\n    public Owner find(int id) {}\n'
            '    @PostMapping\n    public void create() {}\n}\n'
        )
        routes = _extract_java_routes(code, "OwnerController.java")
        by_method = {r["method"]: r["path"] for r in routes}
        assert by_method["GET"] == "/api/owners/{id}"
        assert by_method["POST"] == "/api/owners"
        # The class-level @RequestMapping itself must not also appear as a
        # third, separate "ANY" route now that method-level routes exist.
        assert len(routes) == 2

    def test_class_level_mapping_alone_falls_back_to_a_prefix_route(self):
        # Real-world case (Spring PetClinic REST's OpenAPI-delegate
        # controllers): the class implements an interface that carries the
        # actual @GetMapping/@PostMapping annotations, and that interface
        # isn't present in this source checkout. No method-level route can
        # be found, so the class's own declared prefix is surfaced instead
        # of the class silently producing zero routes.
        code = '@RestController\n@RequestMapping("/api")\nclass OwnerRestController implements OwnersApi {\n}\n'
        routes = _extract_java_routes(code, "OwnerRestController.java")
        assert len(routes) == 1
        assert routes[0]["method"] == "ANY"
        assert routes[0]["path"] == "/api"

    def test_request_mapping_with_explicit_method(self):
        code = '@RequestMapping(value = "/x", method = RequestMethod.PUT)\npublic void x() {}\n'
        routes = _extract_java_routes(code, "X.java")
        assert routes[0]["method"] == "PUT"
        assert routes[0]["path"] == "/x"

    def test_no_annotations_yields_no_routes(self):
        assert _extract_java_routes("class Plain {}\n", "Plain.java") == []

    # Code-review regression: a method-level @RequestMapping was
    # misclassified as a class-level prefix declaration whenever the
    # literal word "class" happened to appear within 300 characters
    # after it — a common shape (another class later in the same file,
    # or just a short method body). Fixed by checking what the
    # annotation *actually* sits on (skipping only further annotations/
    # modifiers) instead of scanning an unbounded window for the word
    # "class" anywhere in it.

    def test_method_level_mapping_followed_by_an_unrelated_class_within_300_chars(self):
        # The exact reported failure: a genuine class-level prefix, a
        # method-level @RequestMapping, a second @GetMapping method, then
        # an unrelated class within the old 300-char heuristic's window.
        code = (
            '@RestController\n@RequestMapping("/api/owners")\npublic class OwnerController {\n\n'
            '    @RequestMapping("/legacy")\n'
            '    public ResponseEntity<Owner> legacyGet() {\n        return null;\n    }\n\n'
            '    @GetMapping("/{id}")\n'
            '    public Owner getOwner(int id) {\n        return null;\n    }\n'
            '}\n\n'
            'class UnrelatedDto {\n}\n'
        )
        routes = _extract_java_routes(code, "OwnerController.java")
        by_path = {r["path"]: r["method"] for r in routes}
        # The method-level mapping must combine with the real class
        # prefix, not be dropped or double-counted as its own bare route.
        assert by_path == {"/api/owners/legacy": "ANY", "/api/owners/{id}": "GET"}

    def test_class_level_mapping_still_detected_when_another_annotation_follows_it(self):
        # @RequestMapping followed by a further annotation (not
        # immediately by "class") before the real class declaration —
        # exercises the skip-forward-past-annotations path specifically.
        code = (
            '@RequestMapping("/api/pets")\n@CrossOrigin(origins = "*")\n'
            'public class PetController {\n'
            '    @GetMapping("/{id}")\n    public Pet find(int id) {}\n'
            '}\n'
        )
        routes = _extract_java_routes(code, "PetController.java")
        assert routes == [{
            "method": "GET", "path": "/api/pets/{id}", "file": "PetController.java", "line": 4,
            "handler": "", "framework": "spring_mvc",
            "evidence": routes[0]["evidence"],
        }]

    def test_multiple_methods_all_combine_with_the_same_class_prefix(self):
        code = (
            '@RequestMapping("/api/vets")\npublic class VetController {\n'
            '    @GetMapping\n    public void list() {}\n'
            '    @GetMapping("/{id}")\n    public void get(int id) {}\n'
            '    @PostMapping\n    public void create() {}\n'
            '    @DeleteMapping("/{id}")\n    public void remove(int id) {}\n'
            '}\n'
        )
        routes = _extract_java_routes(code, "VetController.java")
        by_method_path = {(r["method"], r["path"]) for r in routes}
        assert by_method_path == {
            ("GET", "/api/vets"), ("GET", "/api/vets/{id}"),
            ("POST", "/api/vets"), ("DELETE", "/api/vets/{id}"),
        }

    def test_two_classes_each_with_their_own_method_level_mapping_in_one_file(self):
        # A second, more general shape than the exact reported repro:
        # two separate classes, each with a method-level (not
        # class-level) @RequestMapping — neither should borrow the
        # other's prefix or be mistaken for a class-level declaration.
        code = (
            'public class FirstController {\n'
            '    @RequestMapping("/first")\n    public void a() {}\n'
            '}\n\n'
            'public class SecondController {\n'
            '    @RequestMapping("/second")\n    public void b() {}\n'
            '}\n'
        )
        routes = _extract_java_routes(code, "Controllers.java")
        by_path = {r["path"]: r["method"] for r in routes}
        assert by_path == {"/first": "ANY", "/second": "ANY"}


class TestDeriveRoutes:
    def test_scans_files_by_language_from_project_map(self, tmp_path):
        (tmp_path / "app.py").write_text('@router.get("/x")\ndef x():\n    pass\n')
        project_map = {"files": [{"path": "app.py", "language": "python"}]}
        routes, warnings = derive_routes(tmp_path, project_map)
        assert len(routes) == 1
        assert warnings == []

    def test_unsupported_language_is_silently_skipped(self, tmp_path):
        (tmp_path / "main.rs").write_text("fn main() {}\n")
        project_map = {"files": [{"path": "main.rs", "language": "rust"}]}
        routes, warnings = derive_routes(tmp_path, project_map)
        assert routes == []
        assert warnings == []

    def test_supported_language_present_but_zero_routes_produces_a_warning(self, tmp_path):
        (tmp_path / "util.py").write_text("def helper():\n    pass\n")
        project_map = {"files": [{"path": "util.py", "language": "python"}]}
        routes, warnings = derive_routes(tmp_path, project_map)
        assert routes == []
        assert any("no API routes were discovered" in w for w in warnings)

    def test_missing_file_on_disk_does_not_crash(self, tmp_path):
        project_map = {"files": [{"path": "ghost.py", "language": "python"}]}
        routes, warnings = derive_routes(tmp_path, project_map)
        assert routes == []


# ── Entities ─────────────────────────────────────────────────────


def _var_node(id_, name, file, line, columns=None, relationships=None):
    return {
        "id": id_, "name": name, "kind": "variable", "file": file, "line": line,
        "schema": {"table_name": None, "columns": columns or [], "foreign_keys": [], "relationships": relationships or []},
    }


def _class_node(id_, name, file, line):
    return {
        "id": id_, "name": name, "kind": "class", "file": file, "line": line,
        "schema": {"table_name": None, "columns": [], "foreign_keys": [], "relationships": []},
    }


class TestDeriveEntities:
    def test_no_csg_returns_empty(self):
        assert derive_entities(None, {"files": []}) == []

    def test_class_with_no_schema_is_not_an_entity(self):
        csg = {"nodes": [{"id": "a.py::Plain", "name": "Plain", "kind": "class", "file": "a.py", "line": 1}]}
        assert derive_entities(csg, {"files": []}) == []

    def test_columns_reconstructed_via_nearest_enclosing_class(self):
        csg = {"nodes": [
            _class_node("m.py::Owner", "Owner", "m.py", 1),
            _var_node("m.py::id", "id", "m.py", 2, columns=[{"name": "id", "type": "unknown", "primary_key": True}]),
            _var_node("m.py::name", "name", "m.py", 3, columns=[{"name": "name", "type": "unknown", "primary_key": False}]),
        ]}
        project_map = {"files": [{"path": "m.py", "language": "python"}]}
        entities = derive_entities(csg, project_map)
        assert len(entities) == 1
        assert entities[0]["name"] == "Owner"
        assert entities[0]["columns_inferred"] is True
        assert [c["name"] for c in entities[0]["columns"]] == ["id", "name"]
        assert entities[0]["table_name"] is None  # never fabricated

    def test_columns_before_any_class_in_file_are_dropped_not_misattributed(self):
        csg = {"nodes": [
            _var_node("m.py::orphan", "orphan", "m.py", 1, columns=[{"name": "orphan", "type": "unknown", "primary_key": False}]),
            _class_node("m.py::Owner", "Owner", "m.py", 5),
        ]}
        entities = derive_entities(csg, {"files": []})
        assert entities[0]["columns"] == []

    def test_two_classes_in_same_file_each_get_their_own_columns(self):
        csg = {"nodes": [
            _class_node("m.py::Owner", "Owner", "m.py", 1),
            _var_node("m.py::oid", "oid", "m.py", 2, columns=[{"name": "oid", "type": "unknown", "primary_key": True}]),
            _class_node("m.py::Pet", "Pet", "m.py", 10),
            _var_node("m.py::pid", "pid", "m.py", 11, columns=[{"name": "pid", "type": "unknown", "primary_key": True}]),
        ]}
        entities = {e["name"]: e for e in derive_entities(csg, {"files": []})}
        assert [c["name"] for c in entities["Owner"]["columns"]] == ["oid"]
        assert [c["name"] for c in entities["Pet"]["columns"]] == ["pid"]

    def test_relationship_cardinality_is_never_propagated_as_verified(self):
        csg = {"nodes": [
            _class_node("m.py::Owner", "Owner", "m.py", 1),
            _var_node("m.py::pets", "pets", "m.py", 2, relationships=[
                {"name": "pets", "target_model": "Pet", "relationship_type": "one-to-many"},
            ]),
        ]}
        entities = derive_entities(csg, {"files": []})
        rel = entities[0]["relationships"][0]
        assert rel["target_entity"] == "Pet"
        assert rel["cardinality"] == "unknown"  # Layer 1's "one-to-many" is hardcoded, not evidence

    def test_language_comes_from_project_map(self):
        csg = {"nodes": [_class_node("m.java::Owner", "Owner", "m.java", 1)]}
        project_map = {"files": [{"path": "m.java", "language": "java"}]}
        entities = derive_entities(csg, project_map)
        assert entities[0]["language"] == "java"

    def test_malformed_node_missing_id_does_not_crash(self):
        csg = {"nodes": [{"name": "Broken", "kind": "class", "file": "m.py", "line": 1, "schema": {}}]}
        # id is required for the entities dict key — a KeyError here would
        # be a crash on malformed input, which must not happen.
        try:
            derive_entities(csg, {"files": []})
        except KeyError:
            assert False, "derive_entities crashed on a node missing 'id'"


class TestDerivePersistenceSummary:
    def test_no_entities_returns_none(self):
        assert derive_persistence_summary([]) is None

    def test_counts_by_language(self):
        entities = [
            {"language": "python"}, {"language": "python"}, {"language": "java"}, {"language": None},
        ]
        summary = derive_persistence_summary(entities)
        assert summary["mode"] == "orm"
        assert summary["entity_count"] == 4
        assert summary["by_language"] == {"python": 2, "java": 1, "unknown": 1}
