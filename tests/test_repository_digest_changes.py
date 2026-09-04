"""Unit tests for lib/context/repository_digest_changes.py — Phase 5B
Changes History comparison logic. Pure function, synthetic before/after
digest dicts, no filesystem involved.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

_project_root = str(Path(__file__).parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from lib.context.repository_digest_changes import derive_changes_history


def _base_digest(**overrides) -> dict:
    base = {
        "schema_version": 9,
        "generated_at": "2026-01-01T00:00:00Z",
        "fingerprint": {"git_head": "abc111"},
        "identity": {"name": "speed"},
        "domains": [],
        "relationships": [],
        "api_data": {"routes": [], "entities": []},
        "cicd": {"workflows": []},
        "runtime_config": {"runtimes": [], "frameworks": [], "config_sources": [], "environment_variables": []},
        "security": {"secret_indicators": [], "sensitive_configuration": [], "authentication_indicators": [], "security_tooling_detected": []},
        "readiness": [],
        "coverage_stats": None,
    }
    base.update(overrides)
    return base


def _section(result: dict, key: str) -> dict:
    return next(s for s in result["sections"] if s["key"] == key)


# ── 1. First digest, no previous snapshot ───────────────────────


def test_first_run_with_no_previous_snapshot():
    current = _base_digest()
    result = derive_changes_history(current, None)
    assert result["status"] == "first_run"
    assert result["previous_snapshot"] is None
    assert result["sections"] == []
    assert result["summary"] == []
    assert result["current_snapshot"]["git_head"] == "abc111"


# ── 2. Second digest with a previous snapshot ───────────────────


def test_second_digest_with_previous_snapshot_is_compared():
    previous = _base_digest()
    current = _base_digest(generated_at="2026-01-02T00:00:00Z")
    result = derive_changes_history(current, previous)
    assert result["status"] == "compared"
    assert result["previous_snapshot"]["generated_at"] == "2026-01-01T00:00:00Z"
    assert result["current_snapshot"]["generated_at"] == "2026-01-02T00:00:00Z"


# ── 3-5. Domain added / removed / changed ───────────────────────


class TestDomainChanges:
    def test_added_domain(self):
        previous = _base_digest()
        current = _base_digest(domains=[{"id": "c1", "label": "Core", "lane": "services", "file_count": 5, "symbol_count": 20, "evidence": []}])
        result = derive_changes_history(current, previous)
        domains = _section(result, "domains")
        assert len(domains["added"]) == 1
        # Keyed by label, not id: cluster IDs carry a numeric suffix that
        # isn't stable across Layer 1 rebuilds (see module comment).
        assert domains["added"][0]["key"] == "Core"
        assert domains["removed"] == []
        assert domains["changed"] == []
        assert "+1 domain" in result["summary"]

    def test_removed_domain(self):
        previous = _base_digest(domains=[{"id": "c1", "label": "Core", "lane": "services", "file_count": 5, "symbol_count": 20, "evidence": []}])
        current = _base_digest()
        result = derive_changes_history(current, previous)
        domains = _section(result, "domains")
        assert len(domains["removed"]) == 1
        assert "-1 domain" in result["summary"]

    def test_changed_domain(self):
        previous = _base_digest(domains=[{"id": "c1", "label": "Core", "lane": "services", "file_count": 5, "symbol_count": 20, "evidence": []}])
        current = _base_digest(domains=[{"id": "c1", "label": "Core", "lane": "api", "file_count": 8, "symbol_count": 20, "evidence": []}])
        result = derive_changes_history(current, previous)
        domains = _section(result, "domains")
        assert len(domains["changed"]) == 1
        fields = {f["field"]: (f["before"], f["after"]) for f in domains["changed"][0]["fields"]}
        assert fields["lane"] == ("services", "api")
        assert fields["file_count"] == (5, 8)
        assert "symbol_count" not in fields

    def test_same_domain_unchanged_produces_no_entry(self):
        d = {"id": "c1", "label": "Core", "lane": "services", "file_count": 5, "symbol_count": 20, "evidence": []}
        previous = _base_digest(domains=[dict(d)])
        current = _base_digest(domains=[dict(d)])
        result = derive_changes_history(current, previous)
        domains = _section(result, "domains")
        assert domains["added"] == domains["removed"] == domains["changed"] == []

    def test_same_domain_label_with_shifted_cluster_id_is_not_a_false_add_and_remove(self):
        # Real finding from live A/B rebuild on this repository: cluster
        # IDs carry a numeric suffix (e.g. cluster_backend/tmp_path_75)
        # that is not stable across separate Layer 1 rebuilds, even with
        # no meaningful repository change. Keying by id alone reported
        # ~68 of 86 domains as simultaneously "added" and "removed" on a
        # rebuild that changed nothing but one new file. Keying by label
        # instead must treat this as unchanged.
        previous = _base_digest(domains=[{"id": "cluster_core_12", "label": "Core", "lane": "services", "file_count": 5, "symbol_count": 20, "evidence": []}])
        current = _base_digest(domains=[{"id": "cluster_core_47", "label": "Core", "lane": "services", "file_count": 5, "symbol_count": 20, "evidence": []}])
        result = derive_changes_history(current, previous)
        domains = _section(result, "domains")
        assert domains["added"] == domains["removed"] == domains["changed"] == []

    # Code-review regression: two domains sharing the same TF-IDF-derived
    # label (a real, if rare, labeling collision — e.g. a frontend
    # "Models" cluster and an unrelated backend "Models" cluster) were
    # silently collapsed by dict-comprehension keying on label alone,
    # which could fabricate a phantom "changed" event and hide a genuine
    # deletion. Fixed by refining the key with each colliding domain's
    # own top representative_files entry, but ONLY when a collision is
    # actually present in that snapshot.

    def _colliding_pair(self, rep_files_a, rep_files_b, **shared):
        base = {"label": "Models", "lane": "data", "file_count": 5, "symbol_count": 10, "evidence": [], **shared}
        return (
            {**base, "id": "c1", "representative_files": rep_files_a},
            {**base, "id": "c2", "representative_files": rep_files_b},
        )

    def test_two_domains_sharing_a_label_are_kept_distinct_not_collapsed(self):
        frontend_models, backend_models = self._colliding_pair(
            ["client/src/models/Owner.ts"], ["src/main/java/model/Owner.java"],
        )
        previous = _base_digest(domains=[frontend_models, backend_models])
        current = _base_digest(domains=[dict(frontend_models), dict(backend_models)])
        result = derive_changes_history(current, previous)
        domains = _section(result, "domains")
        # Both survive as distinct, unchanged entries — not collapsed
        # into one, not reported as a spurious change against each other.
        assert domains["added"] == domains["removed"] == domains["changed"] == []

    def test_one_same_label_domain_deleted_while_the_other_survives(self):
        frontend_models, backend_models = self._colliding_pair(
            ["client/src/models/Owner.ts"], ["src/main/java/model/Owner.java"],
        )
        previous = _base_digest(domains=[frontend_models, backend_models])
        # backend_models deleted; frontend_models (same label) remains
        # completely unchanged.
        current = _base_digest(domains=[dict(frontend_models)])
        result = derive_changes_history(current, previous)
        domains = _section(result, "domains")
        assert len(domains["removed"]) == 1
        assert domains["added"] == []
        # The real deletion must not be masked as a "changed Models".
        assert domains["changed"] == []

    def test_one_same_label_domain_changes_while_the_other_stays_the_same(self):
        frontend_models, backend_models = self._colliding_pair(
            ["client/src/models/Owner.ts"], ["src/main/java/model/Owner.java"],
        )
        previous = _base_digest(domains=[frontend_models, backend_models])
        changed_backend = {**backend_models, "file_count": 9}
        current = _base_digest(domains=[dict(frontend_models), changed_backend])
        result = derive_changes_history(current, previous)
        domains = _section(result, "domains")
        assert domains["added"] == domains["removed"] == []
        # Only the backend Models domain changed — a fabricated diff
        # comparing it against the (unrelated, unchanged) frontend one
        # would report an incorrect file_count delta or spurious lane
        # noise instead of exactly this one real change.
        assert len(domains["changed"]) == 1
        fields = {f["field"]: (f["before"], f["after"]) for f in domains["changed"][0]["fields"]}
        assert fields == {"file_count": (5, 9)}

    def test_domains_with_unique_labels_are_unaffected_by_collision_handling(self):
        # Normal, non-colliding case must behave exactly as before:
        # label alone is the identity, and an unrelated same-label pair
        # elsewhere in the snapshot must not change that.
        core = {"id": "c1", "label": "Core", "lane": "services", "file_count": 5, "symbol_count": 20, "evidence": [], "representative_files": ["lib/core.py"]}
        previous = _base_digest(domains=[dict(core)])
        current = _base_digest(domains=[dict(core)])
        result = derive_changes_history(current, previous)
        domains = _section(result, "domains")
        assert domains["added"] == domains["removed"] == domains["changed"] == []


# ── 6-7. Route added / removed ───────────────────────────────────


class TestRouteChanges:
    def test_added_route(self):
        previous = _base_digest()
        current = _base_digest(api_data={"routes": [{"method": "GET", "path": "/x", "file": "a.py", "handler": "x", "framework": "flask", "evidence": []}], "entities": []})
        result = derive_changes_history(current, previous)
        routes = _section(result, "routes")
        assert len(routes["added"]) == 1
        assert routes["added"][0]["title"] == "GET /x"
        assert "+1 api route" in result["summary"]

    def test_removed_route(self):
        previous = _base_digest(api_data={"routes": [{"method": "GET", "path": "/x", "file": "a.py", "handler": "x", "framework": "flask", "evidence": []}], "entities": []})
        current = _base_digest()
        result = derive_changes_history(current, previous)
        routes = _section(result, "routes")
        assert len(routes["removed"]) == 1
        assert "-1 api route" in result["summary"]

    def test_route_line_number_shift_alone_is_not_a_change(self):
        # Evidence carries line, but line is not a compare_field for
        # routes — a line shifting due to unrelated edits must not be
        # reported as a "changed" route.
        previous = _base_digest(api_data={"routes": [{"method": "GET", "path": "/x", "file": "a.py", "handler": "x", "framework": "flask", "evidence": [{"line": 10}]}], "entities": []})
        current = _base_digest(api_data={"routes": [{"method": "GET", "path": "/x", "file": "a.py", "handler": "x", "framework": "flask", "evidence": [{"line": 25}]}], "entities": []})
        result = derive_changes_history(current, previous)
        routes = _section(result, "routes")
        assert routes["added"] == routes["removed"] == routes["changed"] == []


# ── 7b. Singular-form summary lines for irregular labels ──────────
# Max-effort code review finding: the naive "strip a trailing s" singular
# heuristic mangled "Entities" -> "entitie" and "Discovery readiness" ->
# "discovery readines" (the label itself already ends in "s").


class TestSummarySingularForms:
    def test_one_entity_added_is_not_misspelled(self):
        previous = _base_digest()
        current = _base_digest(api_data={"routes": [], "entities": [{"name": "User", "file": "models.py", "columns": [], "relationships": [], "evidence": []}]})
        result = derive_changes_history(current, previous)
        assert "+1 entity" in result["summary"]
        assert not any("entitie" in line for line in result["summary"])

    def test_one_entity_removed_is_not_misspelled(self):
        previous = _base_digest(api_data={"routes": [], "entities": [{"name": "User", "file": "models.py", "columns": [], "relationships": [], "evidence": []}]})
        current = _base_digest()
        result = derive_changes_history(current, previous)
        assert "-1 entity" in result["summary"]
        assert not any("entitie" in line for line in result["summary"])

    def test_one_readiness_entry_added_is_not_misspelled(self):
        previous = _base_digest()
        current = _base_digest(readiness=[{"capability": "conventions", "status": "available", "evidence": []}])
        result = derive_changes_history(current, previous)
        assert "+1 discovery readiness" in result["summary"]
        assert not any("readines" in line and "readiness" not in line for line in result["summary"])

    def test_multiple_entities_still_use_plural_label(self):
        # The regular (non-count-of-1) branch already worked correctly —
        # confirming the fix didn't change that path.
        previous = _base_digest()
        current = _base_digest(api_data={"routes": [], "entities": [
            {"name": "User", "file": "models.py", "columns": [], "relationships": [], "evidence": []},
            {"name": "Pet", "file": "models.py", "columns": [], "relationships": [], "evidence": []},
        ]})
        result = derive_changes_history(current, previous)
        assert "+2 entities" in result["summary"]


# ── 8. Changed runtime/config ────────────────────────────────────


def test_runtime_version_change_produces_narrative_summary():
    previous = _base_digest(runtime_config={"runtimes": [{"language": "python", "source_file": "Dockerfile", "version": "3.11", "evidence": []}], "frameworks": [], "config_sources": [], "environment_variables": []})
    current = _base_digest(runtime_config={"runtimes": [{"language": "python", "source_file": "Dockerfile", "version": "3.12", "evidence": []}], "frameworks": [], "config_sources": [], "environment_variables": []})
    result = derive_changes_history(current, previous)
    assert "Runtime (python) changed from 3.11 to 3.12" in result["summary"]


# ── 9. Changed CI/CD ──────────────────────────────────────────────


def test_cicd_workflow_jobs_changed():
    previous = _base_digest(cicd={"workflows": [{"name": "CI", "config_file": ".github/workflows/ci.yml", "triggers": ["push"], "jobs": [{"name": "test"}], "evidence": []}]})
    current = _base_digest(cicd={"workflows": [{"name": "CI", "config_file": ".github/workflows/ci.yml", "triggers": ["push"], "jobs": [{"name": "test"}, {"name": "build"}], "evidence": []}]})
    result = derive_changes_history(current, previous)
    cicd = _section(result, "cicd_workflows")
    assert len(cicd["changed"]) == 1
    jobs_field = next(f for f in cicd["changed"][0]["fields"] if f["field"] == "jobs")
    assert jobs_field["after"] == ["build", "test"]


def test_cicd_workflow_rename_and_jobs_change_both_reported():
    """Max-effort code review finding: the generic _diff_list pass
    (compare_fields=("name",)) already creates a 'changed' entry when a
    workflow's name changes; the jobs-specific block used to see that
    entry already present and skip appending its own diff entirely,
    silently dropping the job change. Both must be reported now.
    """
    previous = _base_digest(cicd={"workflows": [{"name": "CI", "config_file": ".github/workflows/ci.yml", "triggers": ["push"], "jobs": [{"name": "test"}], "evidence": []}]})
    current = _base_digest(cicd={"workflows": [{"name": "Build & Test", "config_file": ".github/workflows/ci.yml", "triggers": ["push"], "jobs": [{"name": "test"}, {"name": "build"}], "evidence": []}]})
    result = derive_changes_history(current, previous)
    cicd = _section(result, "cicd_workflows")
    assert len(cicd["changed"]) == 1
    fields_by_name = {f["field"]: f for f in cicd["changed"][0]["fields"]}
    assert fields_by_name["name"] == {"field": "name", "before": "CI", "after": "Build & Test"}
    assert fields_by_name["jobs"]["after"] == ["build", "test"]


# ── 10. Changed security finding ─────────────────────────────────


def test_sensitive_configuration_severity_changed():
    previous = _base_digest(security={"secret_indicators": [], "sensitive_configuration": [{"category": "tls_verification_disabled", "title": "TLS off", "severity": "medium", "file": "a.py", "evidence": []}], "authentication_indicators": [], "security_tooling_detected": []})
    current = _base_digest(security={"secret_indicators": [], "sensitive_configuration": [{"category": "tls_verification_disabled", "title": "TLS off", "severity": "high", "file": "a.py", "evidence": []}], "authentication_indicators": [], "security_tooling_detected": []})
    result = derive_changes_history(current, previous)
    sensitive = _section(result, "sensitive_configuration")
    assert len(sensitive["changed"]) == 1
    assert sensitive["changed"][0]["fields"][0] == {"field": "severity", "before": "medium", "after": "high"}


def test_new_secret_indicator_is_added_never_a_value():
    previous = _base_digest()
    current = _base_digest(security={"secret_indicators": [{"category": "declared_name", "pattern_type": None, "name": "API_KEY", "file": ".env", "redacted": True, "evidence": []}], "sensitive_configuration": [], "authentication_indicators": [], "security_tooling_detected": []})
    result = derive_changes_history(current, previous)
    secrets = _section(result, "secret_indicators")
    assert len(secrets["added"]) == 1
    import json
    assert "value" not in json.dumps(secrets).lower().replace("evidence", "")


# ── 11. Relationship changes ─────────────────────────────────────


def test_relationship_weight_changed():
    previous = _base_digest(relationships=[{"from": "c1", "to": "c2", "weight": 3, "evidence_type": "verified"}])
    current = _base_digest(relationships=[{"from": "c1", "to": "c2", "weight": 7, "evidence_type": "verified"}])
    result = derive_changes_history(current, previous)
    rels = _section(result, "relationships")
    assert len(rels["changed"]) == 1
    assert rels["changed"][0]["fields"][0] == {"field": "weight", "before": 3, "after": 7}


def test_relationship_endpoints_resolved_via_domain_label_survive_a_cluster_id_shift():
    # Same accuracy fix as domains: relationship endpoints are cluster
    # IDs too, resolved to each side's own domain label before diffing.
    previous = _base_digest(
        domains=[
            {"id": "cluster_core_12", "label": "Core", "lane": "services", "file_count": 1, "symbol_count": 1, "evidence": []},
            {"id": "cluster_api_9", "label": "Api", "lane": "api", "file_count": 1, "symbol_count": 1, "evidence": []},
        ],
        relationships=[{"from": "cluster_core_12", "to": "cluster_api_9", "weight": 5, "evidence_type": "verified"}],
    )
    current = _base_digest(
        domains=[
            {"id": "cluster_core_47", "label": "Core", "lane": "services", "file_count": 1, "symbol_count": 1, "evidence": []},
            {"id": "cluster_api_22", "label": "Api", "lane": "api", "file_count": 1, "symbol_count": 1, "evidence": []},
        ],
        relationships=[{"from": "cluster_core_47", "to": "cluster_api_22", "weight": 5, "evidence_type": "verified"}],
    )
    result = derive_changes_history(current, previous)
    rels = _section(result, "relationships")
    assert rels["added"] == rels["removed"] == rels["changed"] == []


# ── 12. Unchanged digest ─────────────────────────────────────────


def test_fully_identical_digest_produces_no_changes_anywhere():
    digest = _base_digest(
        domains=[{"id": "c1", "label": "Core", "lane": "services", "file_count": 5, "symbol_count": 20, "evidence": []}],
        relationships=[{"from": "c1", "to": "c1", "weight": 1, "evidence_type": "verified"}],
    )
    previous = copy.deepcopy(digest)
    current = copy.deepcopy(digest)
    current["generated_at"] = "2026-01-02T00:00:00Z"  # only generated_at differs
    result = derive_changes_history(current, previous)
    for s in result["sections"]:
        assert s["added"] == [], s["key"]
        assert s["removed"] == [], s["key"]
        assert s["changed"] == [], s["key"]
    assert result["summary"] == []


# ── 13. Previous digest from an older schema (sections missing) ──


class TestOlderSchemaPreviousDigest:
    def test_missing_sections_are_unavailable_not_all_removed(self):
        previous = {
            "schema_version": 5, "generated_at": "2025-01-01T00:00:00Z",
            "fingerprint": {"git_head": "oldhead"}, "identity": {"name": "speed"},
            "domains": [], "relationships": [], "readiness": [], "coverage_stats": None,
            # no api_data / cicd / runtime_config / security at all
        }
        current = _base_digest(
            api_data={"routes": [{"method": "GET", "path": "/x", "file": "a.py", "handler": "x", "framework": "flask", "evidence": []}], "entities": []},
        )
        result = derive_changes_history(current, previous)
        routes = _section(result, "routes")
        assert routes["available"] is False
        assert "predates" in routes["reason"]
        assert routes["added"] == routes["removed"] == routes["changed"] == []
        # Must never claim the new route was "added" when it's really
        # "not comparable" — those are different, non-conflatable states.
        assert not any("route" in line for line in result["summary"])

    def test_current_digest_missing_a_section_present_in_previous(self):
        previous = _base_digest(api_data={"routes": [{"method": "GET", "path": "/x", "file": "a.py", "handler": "x", "framework": "flask", "evidence": []}], "entities": []})
        current = {k: v for k, v in _base_digest().items() if k != "api_data"}
        result = derive_changes_history(current, previous)
        routes = _section(result, "routes")
        assert routes["available"] is False
        assert "current digest" in routes["reason"]


# ── 15. Repository identity mismatch ─────────────────────────────


def test_identity_mismatch_produces_a_warning_but_still_compares():
    previous = _base_digest(identity={"name": "other-project"})
    current = _base_digest(identity={"name": "speed"})
    result = derive_changes_history(current, previous)
    assert any("identity changed" in w for w in result["warnings"])
    assert result["status"] == "compared"


# ── 16. Git SHA unavailable ───────────────────────────────────────


def test_missing_git_sha_produces_a_warning_not_a_crash():
    previous = _base_digest(fingerprint={"git_head": None})
    current = _base_digest(fingerprint={"git_head": None})
    result = derive_changes_history(current, previous)
    assert any("git revision unavailable" in w for w in result["warnings"])
    assert result["status"] == "compared"


# ── 18. Generated metadata ignored ───────────────────────────────


def test_generated_at_and_fingerprint_alone_never_trigger_a_change():
    digest = _base_digest()
    previous = copy.deepcopy(digest)
    current = copy.deepcopy(digest)
    current["generated_at"] = "2099-01-01T00:00:00Z"
    current["fingerprint"] = {"git_head": "zzzz999"}
    result = derive_changes_history(current, previous)
    assert result["summary"] == []
    for s in result["sections"]:
        assert s["added"] == s["removed"] == s["changed"] == []


# ── 19. History storage does not recursively contain history ────


def test_changes_history_result_never_embeds_another_changes_history():
    previous = _base_digest()
    current = _base_digest()
    result = derive_changes_history(current, previous)
    assert "_changes_history" not in result
    assert "changes_history" not in result
    # And the inputs themselves must never have carried one either —
    # this function must not read or depend on a nested history key.
    assert "_changes_history" not in previous
    assert "_changes_history" not in current


# ── Malformed / defensive input handling ─────────────────────────


class TestMalformedInput:
    def test_non_list_section_values_do_not_crash(self):
        previous = _base_digest(domains="not-a-list")
        current = _base_digest(domains=[])
        # domains being a non-list on the previous side should degrade
        # gracefully rather than raise.
        try:
            result = derive_changes_history(current, previous)
        except Exception as e:
            assert False, f"derive_changes_history crashed on malformed domains: {e}"
        domains = _section(result, "domains")
        # A malformed (non-list) value is treated the same as "missing" —
        # the safer, more defensible degrade, not a crash.
        assert domains["available"] is False

    def test_missing_coverage_stats_on_both_sides(self):
        previous = _base_digest()
        current = _base_digest()
        result = derive_changes_history(current, previous)
        coverage = _section(result, "coverage")
        assert coverage["available"] is False

    # Code-review regression: a non-dict coverage_stats value (a hand-
    # edited/legacy/corrupted snapshot) called .get() on it and raised
    # AttributeError, which the caller's blanket except Exception then
    # used to discard the *entire* Changes History result — every other
    # section's real diff, not just coverage — to recover.

    def test_valid_coverage_stats_still_diff(self):
        previous = _base_digest(coverage_stats={"source_files_total": 100, "source_files_parsed": 90, "parse_coverage_pct": 90.0})
        current = _base_digest(coverage_stats={"source_files_total": 100, "source_files_parsed": 95, "parse_coverage_pct": 95.0})
        result = derive_changes_history(current, previous)
        coverage = _section(result, "coverage")
        assert coverage["available"] is True
        fields = {f["field"]: (f["before"], f["after"]) for f in coverage["changed"][0]["fields"]}
        assert fields == {"source_files_parsed": (90, 95), "parse_coverage_pct": (90.0, 95.0)}

    def test_none_coverage_stats_does_not_crash(self):
        previous = _base_digest(coverage_stats=None)
        current = _base_digest(coverage_stats={"source_files_total": 100, "source_files_parsed": 90, "parse_coverage_pct": 90.0})
        result = derive_changes_history(current, previous)
        coverage = _section(result, "coverage")
        assert coverage["available"] is False

    def test_malformed_coverage_stats_types_do_not_crash(self):
        for malformed in ("unknown", 42, [1, 2, 3], True):
            previous = _base_digest(coverage_stats=malformed)
            current = _base_digest(coverage_stats={"source_files_total": 100, "source_files_parsed": 90, "parse_coverage_pct": 90.0})
            try:
                result = derive_changes_history(current, previous)
            except Exception as e:
                assert False, f"derive_changes_history crashed on coverage_stats={malformed!r}: {e}"
            coverage = _section(result, "coverage")
            assert coverage["available"] is False, f"expected unavailable for coverage_stats={malformed!r}"

    def test_malformed_coverage_stats_does_not_suppress_domain_changes(self):
        previous = _base_digest(
            coverage_stats="unknown",
            domains=[{"id": "c1", "label": "Core", "lane": "services", "file_count": 5, "symbol_count": 20, "evidence": []}],
        )
        current = _base_digest(
            coverage_stats={"source_files_total": 100, "source_files_parsed": 90, "parse_coverage_pct": 90.0},
            domains=[],
        )
        result = derive_changes_history(current, previous)
        assert _section(result, "coverage")["available"] is False
        domains = _section(result, "domains")
        assert len(domains["removed"]) == 1

    def test_malformed_coverage_stats_does_not_suppress_relationship_changes(self):
        previous = _base_digest(
            coverage_stats=123,
            domains=[
                {"id": "c1", "label": "Core", "lane": "services", "file_count": 5, "symbol_count": 20, "evidence": []},
                {"id": "c2", "label": "UI", "lane": "frontend", "file_count": 3, "symbol_count": 10, "evidence": []},
            ],
            relationships=[{"source": "c1", "target": "c2", "weight": 4, "evidence_type": "verified", "sample_references": []}],
        )
        current = _base_digest(
            coverage_stats={"source_files_total": 100, "source_files_parsed": 90, "parse_coverage_pct": 90.0},
            domains=[
                {"id": "c1", "label": "Core", "lane": "services", "file_count": 5, "symbol_count": 20, "evidence": []},
                {"id": "c2", "label": "UI", "lane": "frontend", "file_count": 3, "symbol_count": 10, "evidence": []},
            ],
            relationships=[],
        )
        result = derive_changes_history(current, previous)
        assert _section(result, "coverage")["available"] is False
        relationships = _section(result, "relationships")
        assert len(relationships["removed"]) == 1
