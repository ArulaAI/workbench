"""Unit tests for lib/context/repository_digest_architecture.py — the
Phase 3 Architecture screen additions (lane classification, relationship
evidence). Pure functions, synthetic inputs, no full build required.
"""

from __future__ import annotations

import sys
from pathlib import Path

_project_root = str(Path(__file__).parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from lib.context.repository_digest_architecture import (
    classify_file_lane,
    classify_domain_lane,
    annotate_domain_lanes,
    RELATIONSHIP_EVIDENCE_TYPE,
    sample_references,
)


# ── classify_file_lane ─────────────────────────────────────────


class TestClassifyFileLane:
    def test_data_directory_segment(self):
        assert classify_file_lane("src/models/pet.py") == "data"

    def test_data_extension(self):
        assert classify_file_lane("db/migrations/0001_init.sql") == "data"

    def test_data_filename_suffix(self):
        assert classify_file_lane("org/petclinic/owner/OwnerRepository.java") == "data"

    def test_api_directory_segment(self):
        assert classify_file_lane("dashboard/backend/resolvers/define.py") == "api"

    def test_api_filename_suffix(self):
        assert classify_file_lane("org/petclinic/owner/OwnerController.java") == "api"

    def test_frontend_directory_segment(self):
        assert classify_file_lane("dashboard/frontend/components/Sidebar.tsx") == "frontend"

    def test_frontend_extension(self):
        assert classify_file_lane("src/App.tsx") == "frontend"

    def test_services_directory_segment(self):
        assert classify_file_lane("org/petclinic/owner/OwnerService.java") == "services"

    def test_unmatched_file_returns_none_not_a_guess(self):
        assert classify_file_lane("README.md") is None
        assert classify_file_lane("scripts/deploy.sh") is None

    def test_priority_order_data_beats_api(self):
        # "api/models/" carries evidence for both — DATA wins by fixed priority.
        assert classify_file_lane("api/models/user.py") == "data"

    def test_priority_order_api_beats_frontend(self):
        # "frontend/api/" carries evidence for both — API wins by fixed priority.
        assert classify_file_lane("frontend/api/client.ts") == "api"

    def test_case_insensitive(self):
        assert classify_file_lane("SRC/MODELS/Pet.py") == "data"

    def test_windows_style_separators_normalized(self):
        assert classify_file_lane("src\\models\\pet.py") == "data"


# ── classify_domain_lane ────────────────────────────────────────


class TestClassifyDomainLane:
    def test_plurality_vote(self):
        files = ["a/services/foo.py", "a/services/bar.py", "a/models/baz.py"]
        assert classify_domain_lane(files) == "services"

    def test_no_evidence_anywhere_is_other(self):
        files = ["README.md", "docs/guide.md", "Makefile"]
        assert classify_domain_lane(files) == "other"

    def test_empty_file_list_is_other(self):
        assert classify_domain_lane([]) == "other"

    def test_tie_break_is_deterministic_by_fixed_priority(self):
        # One data-ish file, one api-ish file — tie broken toward "data".
        files = ["a/models/x.py", "a/api/y.py"]
        assert classify_domain_lane(files) == "data"

    def test_mixed_evidence_and_noise_ignores_unmatched_files(self):
        files = ["README.md", "a/services/x.py", "a/services/y.py", "LICENSE"]
        assert classify_domain_lane(files) == "services"


# ── annotate_domain_lanes ───────────────────────────────────────


class TestAnnotateDomainLanes:
    def test_uses_full_cluster_file_list_not_just_representative_files(self):
        domains = [{
            "id": "cluster_x",
            "representative_files": ["README.md"],  # would classify as "other" alone
        }]
        csg = {"clusters": [{"id": "cluster_x", "files": ["a/services/x.py", "a/services/y.py", "README.md"]}]}
        annotate_domain_lanes(domains, csg)
        assert domains[0]["lane"] == "services"

    def test_falls_back_to_representative_files_when_cluster_missing(self):
        domains = [{"id": "cluster_missing", "representative_files": ["a/models/x.py"]}]
        csg = {"clusters": []}
        annotate_domain_lanes(domains, csg)
        assert domains[0]["lane"] == "data"

    def test_no_csg_falls_back_to_representative_files(self):
        domains = [{"id": "cluster_x", "representative_files": ["a/api/x.py"]}]
        annotate_domain_lanes(domains, None)
        assert domains[0]["lane"] == "api"

    def test_mutates_every_domain_in_place(self):
        domains = [
            {"id": "c1", "representative_files": []},
            {"id": "c2", "representative_files": []},
        ]
        annotate_domain_lanes(domains, None)
        assert all("lane" in d for d in domains)
        assert all(d["lane"] == "other" for d in domains)


# ── Relationship evidence ───────────────────────────────────────


class TestRelationshipEvidence:
    def test_evidence_type_is_verified(self):
        assert RELATIONSHIP_EVIDENCE_TYPE == "verified"

    def test_sample_references_extracts_real_pairs(self):
        edge = {"symbols": [{"from": "a::foo", "to": "b::bar"}, {"from": "a::baz", "to": "b::qux"}]}
        result = sample_references(edge)
        assert result == [
            {"from": "a::foo", "to": "b::bar"},
            {"from": "a::baz", "to": "b::qux"},
        ]

    def test_sample_references_caps_at_default_of_three(self):
        edge = {"symbols": [{"from": f"a::{i}", "to": f"b::{i}"} for i in range(10)]}
        assert len(sample_references(edge)) == 3

    def test_sample_references_empty_when_no_symbols(self):
        assert sample_references({}) == []

    def test_sample_references_skips_malformed_pairs(self):
        edge = {"symbols": [{"from": "a::foo"}, {"to": "b::bar"}, {"from": "a::x", "to": "b::y"}]}
        assert sample_references(edge) == [{"from": "a::x", "to": "b::y"}]
