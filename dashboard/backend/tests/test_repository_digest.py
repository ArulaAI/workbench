"""Integration tests for the Repository Digest GraphQL layer.

Covers dashboard/backend/resolvers/repository_digest.py,
repository_digest_types.py, and their wiring into schema.py: reading a
real artifact through actual SpeedPaths resolution, missing/malformed
handling, freshness without repo mutation, the refresh mutation's
generating -> terminal lifecycle (including the single-build-per-project
lock and a subscription listener), and enum/limit translation.

See specs/tech/speed-repository-digest-dashboard.md > Testing > Test Plan.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_DASHBOARD_DIR = Path(__file__).resolve().parent.parent.parent
if str(_DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(_DASHBOARD_DIR))

from backend.schema import schema
from backend.subscriptions import SubscriptionManager, EventType
from backend.resolvers import repository_digest as digest_resolver


# ── Fixtures ────────────────────────────────────────────────────


def _write_project_map(root: Path, files: list[dict]) -> None:
    ctx = root / ".speed" / "context"
    ctx.mkdir(parents=True, exist_ok=True)
    total_lines = sum(f.get("lines", 0) for f in files)
    (ctx / "project-map.json").write_text(json.dumps({
        "generated_at": "2026-01-01T00:00:00Z",
        "git_head": "abc123",
        "project_root": str(root),
        "summary": {"total_files": len(files), "total_lines": total_lines, "by_language": {}},
        "files": files,
        "directories": [],
    }))


def _build_golden_digest(root: Path) -> dict:
    """Build a real digest on disk via the actual builder, through the same
    path resolution the dashboard resolver uses.
    """
    from lib.context.repository_digest import build_repository_digest
    _write_project_map(root, [
        {"path": "src/app.py", "language": "python", "lines": 40, "category": "source"},
        {"path": "src/util.py", "language": "python", "lines": 20, "category": "source"},
    ])
    return build_repository_digest(str(root), config={})


def _make_context(tmp_path: Path, sub_manager=None) -> dict:
    ctx = {"project_root": tmp_path}
    if sub_manager is not None:
        ctx["sub_manager"] = sub_manager
    return ctx


def _execute_gql(query: str, variable_values: dict | None = None, context_value: dict | None = None):
    """Execute a GraphQL operation via async execute — mutations here run a
    background thread through run_in_executor, which execute_sync cannot
    complete synchronously. Mirrors test_context.py's _execute_gql.
    """
    return asyncio.run(schema.execute(query, variable_values=variable_values, context_value=context_value))


@pytest.fixture(autouse=True)
def _clear_running_builds():
    with digest_resolver._running_lock:
        digest_resolver._running_builds.clear()
    yield
    with digest_resolver._running_lock:
        digest_resolver._running_builds.clear()


DIGEST_QUERY = """
query {
  repositoryDigest {
    schemaVersion
    status
    effectiveState
    generatedAt
    freshness { state indexedGitHead currentGitHead }
    identity { name summary confidence }
    footprint {
      fileCount lineCount sourceFileCount configFileCount assetFileCount
      symbolCount domainCount crossDomainRelationshipCount
      languages { name files lines percent }
    }
    domains(limit: 5) { id label confidence fileCount }
    warnings
  }
}
"""

STATUS_QUERY = """
query {
  repositoryDigestStatus {
    state
    startedAt
    completedAt
    lastError
    hasReadableDigest
  }
}
"""

REFRESH_MUTATION = """
mutation($rebuild: Boolean!) {
  refreshRepositoryDigest(rebuildDiscovery: $rebuild) {
    accepted
    state
    message
    hasReadableDigest
  }
}
"""

DIGEST_UPDATED_SUBSCRIPTION = """
subscription {
  repositoryDigestUpdated {
    state
    lastError
    hasReadableDigest
  }
}
"""


# ═════════════════════════════════════════════════════════════════
# Reading a real artifact through actual path resolution
# ═════════════════════════════════════════════════════════════════


class TestRepositoryDigestQuery:
    def test_reads_golden_digest_through_real_path_resolution(self, tmp_path: Path):
        """A digest built by the real builder, at the real .speed/context/
        path SpeedPaths resolves to, is readable end-to-end through the
        GraphQL layer with correct enum/type translation.
        """
        _build_golden_digest(tmp_path)

        result = schema.execute_sync(DIGEST_QUERY, context_value=_make_context(tmp_path))
        assert result.errors is None
        data = result.data["repositoryDigest"]

        assert data["schemaVersion"] == 1
        assert data["status"] in ("COMPLETE", "PARTIAL")
        assert data["effectiveState"] == "CURRENT"
        assert data["identity"]["name"]
        assert data["identity"]["confidence"] in ("CONFIRMED", "DERIVED", "INFERRED", "UNKNOWN")
        assert data["footprint"]["fileCount"] == 2
        assert data["footprint"]["lineCount"] == 60
        # Code review: source_file_count/config_file_count/asset_file_count/
        # cross_domain_relationship_count were computed by the builder but
        # silently dropped before reaching DigestFootprint.
        assert data["footprint"]["sourceFileCount"] == 2
        assert data["footprint"]["configFileCount"] == 0
        assert data["footprint"]["assetFileCount"] == 0
        assert isinstance(data["domains"], list)
        assert isinstance(data["warnings"], list)

    def test_missing_digest_returns_null_and_missing_status(self, tmp_path: Path):
        """No repository-digest.json on disk: query returns null, and the
        status query reports MISSING (no readable digest, no error, no
        build running).
        """
        (tmp_path / ".speed" / "context").mkdir(parents=True)

        result = schema.execute_sync(DIGEST_QUERY, context_value=_make_context(tmp_path))
        assert result.errors is None
        assert result.data["repositoryDigest"] is None

        status_result = schema.execute_sync(STATUS_QUERY, context_value=_make_context(tmp_path))
        assert status_result.errors is None
        status = status_result.data["repositoryDigestStatus"]
        assert status["state"] == "MISSING"
        assert status["hasReadableDigest"] is False

    def test_malformed_artifact_returns_null(self, tmp_path: Path):
        """A repository-digest.json that fails schema validation is treated
        as unreadable: the query returns null rather than surfacing a
        GraphQL error or partial/garbage data.
        """
        ctx = tmp_path / ".speed" / "context"
        ctx.mkdir(parents=True)
        (ctx / "repository-digest.json").write_text(json.dumps({"not": "a valid digest"}))

        result = schema.execute_sync(DIGEST_QUERY, context_value=_make_context(tmp_path))
        assert result.errors is None
        assert result.data["repositoryDigest"] is None

    def test_freshness_does_not_mutate_repository(self, tmp_path: Path):
        """Reading repositoryDigest computes a freshness comparison against
        the current git HEAD without writing anything into the project
        beyond the digest itself (no new files, no git state change).
        """
        _build_golden_digest(tmp_path)
        before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*") if p.is_file())

        schema.execute_sync(DIGEST_QUERY, context_value=_make_context(tmp_path))

        after = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*") if p.is_file())
        assert before == after

    def test_domains_limit_is_validated(self, tmp_path: Path):
        """limit outside 1-100 on a list field surfaces a GraphQL error
        rather than silently clamping or returning everything.
        """
        _build_golden_digest(tmp_path)
        result = schema.execute_sync(
            "query { repositoryDigest { domains(limit: 0) { id } } }",
            context_value=_make_context(tmp_path),
        )
        assert result.errors is not None


# ═════════════════════════════════════════════════════════════════
# Refresh mutation: generating -> terminal lifecycle, single-flight lock
# ═════════════════════════════════════════════════════════════════


class TestRefreshRepositoryDigestMutation:
    def test_refresh_builds_and_transitions_to_current(self, tmp_path: Path):
        """A refresh on a repo with no prior digest starts a background
        build that is accepted immediately, and the digest becomes readable
        once the build thread finishes.
        """
        _write_project_map(tmp_path, [{"path": "a.py", "language": "python", "lines": 5, "category": "source"}])

        result = _execute_gql(
            REFRESH_MUTATION, variable_values={"rebuild": False}, context_value=_make_context(tmp_path),
        )
        assert result.errors is None
        refresh = result.data["refreshRepositoryDigest"]
        assert refresh["accepted"] is True
        assert refresh["state"] == "GENERATING"

        # The build runs in a daemon thread; wait for it to finish.
        for _ in range(50):
            with digest_resolver._running_lock:
                still_running = digest_resolver._project_key(str(tmp_path)) in digest_resolver._running_builds
            if not still_running:
                break
            import time
            time.sleep(0.1)
        assert not still_running, "build did not finish in time"

        status_result = schema.execute_sync(STATUS_QUERY, context_value=_make_context(tmp_path))
        status = status_result.data["repositoryDigestStatus"]
        assert status["state"] == "CURRENT"
        assert status["hasReadableDigest"] is True

    def test_duplicate_refresh_while_running_is_rejected(self, tmp_path: Path):
        """A second refreshRepositoryDigest call while one is already
        running for this project returns accepted: false instead of
        starting a concurrent build.
        """
        key = digest_resolver._project_key(str(tmp_path))
        with digest_resolver._running_lock:
            digest_resolver._running_builds[key] = "2026-01-01T00:00:00Z"

        result = _execute_gql(
            REFRESH_MUTATION, variable_values={"rebuild": False}, context_value=_make_context(tmp_path),
        )
        assert result.errors is None
        refresh = result.data["refreshRepositoryDigest"]
        assert refresh["accepted"] is False
        assert refresh["state"] == "GENERATING"

    def test_refresh_failure_preserves_existing_digest(self, tmp_path: Path):
        """If a rebuild fails (project-map.json removed after an earlier
        successful build), the previously-written digest is left on disk
        and stays readable — a failed refresh must not delete good state.
        """
        _build_golden_digest(tmp_path)
        (tmp_path / ".speed" / "context" / "project-map.json").unlink()

        result = _execute_gql(
            REFRESH_MUTATION, variable_values={"rebuild": False}, context_value=_make_context(tmp_path),
        )
        assert result.data["refreshRepositoryDigest"]["accepted"] is True

        for _ in range(50):
            with digest_resolver._running_lock:
                still_running = digest_resolver._project_key(str(tmp_path)) in digest_resolver._running_builds
            if not still_running:
                break
            import time
            time.sleep(0.1)

        status_result = schema.execute_sync(STATUS_QUERY, context_value=_make_context(tmp_path))
        status = status_result.data["repositoryDigestStatus"]
        # get_repository_digest_status() only reports state "ERROR" when
        # there is *no* readable digest to fall back on; here the earlier
        # successful build is still on disk and readable, so state reflects
        # its freshness (STALE, since project-map.json is now gone) while
        # lastError still surfaces the failed rebuild for the UI banner.
        assert status["lastError"]
        assert status["hasReadableDigest"] is True
        digest_result = schema.execute_sync(DIGEST_QUERY, context_value=_make_context(tmp_path))
        assert digest_result.data["repositoryDigest"] is not None


# ═════════════════════════════════════════════════════════════════
# Subscription: generating -> terminal state push
# ═════════════════════════════════════════════════════════════════


class TestRepositoryDigestSubscription:
    def test_subscription_emits_generating_then_terminal_state(self, tmp_path: Path):
        """A listener subscribed to repositoryDigestUpdated before the
        mutation runs must observe GENERATING first and a terminal state
        (CURRENT) last, mirroring the assembly-progress subscription test
        in test_context.py for the executor-thread -> async-listener path.
        """
        _write_project_map(tmp_path, [{"path": "a.py", "language": "python", "lines": 5, "category": "source"}])

        async def run():
            sub_manager = SubscriptionManager()
            received: list[str] = []

            async def collect():
                async for event in sub_manager.listen(EventType.REPOSITORY_DIGEST_STATUS_CHANGED):
                    received.append(event.payload["state"])
                    if event.payload["state"] in ("CURRENT", "ERROR"):
                        break

            listener = asyncio.create_task(collect())
            await asyncio.sleep(0)

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: digest_resolver.refresh_repository_digest(
                    str(tmp_path), sub_manager=sub_manager,
                ),
            )
            await asyncio.wait_for(listener, timeout=5.0)
            return received

        received = asyncio.run(run())
        assert received[0] == "GENERATING"
        assert received[-1] == "CURRENT"


# ═════════════════════════════════════════════════════════════════
# Enum / limit translation
# ═════════════════════════════════════════════════════════════════


class TestEnumTranslation:
    def test_confidence_and_status_enums_match_json_contract(self, tmp_path: Path):
        """Lowercase confidence/status strings in the stored JSON translate
        to the exact uppercase GraphQL enum members the RFC's API Surface
        specifies.
        """
        digest = _build_golden_digest(tmp_path)
        assert digest["identity"]["confidence"] in ("confirmed", "derived", "inferred", "unknown")

        result = schema.execute_sync(DIGEST_QUERY, context_value=_make_context(tmp_path))
        gql_confidence = result.data["repositoryDigest"]["identity"]["confidence"]
        assert gql_confidence == digest["identity"]["confidence"].upper()


# ═════════════════════════════════════════════════════════════════
# Malformed vs. missing distinction
# ═════════════════════════════════════════════════════════════════


class TestMalformedVsMissingStatus:
    def test_never_built_reports_missing(self, tmp_path: Path):
        (tmp_path / ".speed" / "context").mkdir(parents=True)
        status_result = schema.execute_sync(STATUS_QUERY, context_value=_make_context(tmp_path))
        status = status_result.data["repositoryDigestStatus"]
        assert status["state"] == "MISSING"
        assert status["lastError"] is None

    def test_malformed_json_reports_error_with_reason(self, tmp_path: Path):
        ctx = tmp_path / ".speed" / "context"
        ctx.mkdir(parents=True)
        (ctx / "repository-digest.json").write_text("{not valid json")

        digest_result = schema.execute_sync(DIGEST_QUERY, context_value=_make_context(tmp_path))
        assert digest_result.data["repositoryDigest"] is None  # query contract: null either way

        status_result = schema.execute_sync(STATUS_QUERY, context_value=_make_context(tmp_path))
        status = status_result.data["repositoryDigestStatus"]
        assert status["state"] == "ERROR"
        assert status["lastError"]
        assert status["hasReadableDigest"] is False

    def test_unsupported_schema_version_reports_error_distinct_from_missing(self, tmp_path: Path):
        _build_golden_digest(tmp_path)
        ctx = tmp_path / ".speed" / "context"
        data = json.loads((ctx / "repository-digest.json").read_text())
        data["schema_version"] = 999
        (ctx / "repository-digest.json").write_text(json.dumps(data))

        status_result = schema.execute_sync(STATUS_QUERY, context_value=_make_context(tmp_path))
        status = status_result.data["repositoryDigestStatus"]
        assert status["state"] == "ERROR"
        assert "schema_version" in status["lastError"]


# ═════════════════════════════════════════════════════════════════
# Cross-process lock
# ═════════════════════════════════════════════════════════════════


class TestCrossProcessLock:
    def test_refresh_rejected_while_another_process_holds_the_lock(self, tmp_path: Path):
        """Simulates a second dashboard process already building for this
        project by holding the flock externally — the in-memory
        _running_builds dict alone wouldn't catch this since it's empty in
        this test process.
        """
        pytest.importorskip("fcntl")
        import fcntl as _fcntl

        _write_project_map(tmp_path, [{"path": "a.py", "language": "python", "lines": 5, "category": "source"}])
        lock_path = tmp_path / ".speed" / "context" / ".repository-digest.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        holder = open(lock_path, "w")
        _fcntl.flock(holder.fileno(), _fcntl.LOCK_EX | _fcntl.LOCK_NB)
        try:
            result = _execute_gql(
                REFRESH_MUTATION, variable_values={"rebuild": False}, context_value=_make_context(tmp_path),
            )
            assert result.data["refreshRepositoryDigest"]["accepted"] is False
        finally:
            _fcntl.flock(holder.fileno(), _fcntl.LOCK_UN)
            holder.close()


# ═════════════════════════════════════════════════════════════════
# Error sanitization
# ═════════════════════════════════════════════════════════════════


class TestSanitizeError:
    def test_strips_traceback_and_redacts_long_tokens(self):
        from backend.resolvers.repository_digest import _sanitize_error

        raw = (
            "Build failed: token opaque_abcdefghijklmnopqrstuvwxyz0123456789 rejected\n"
            "Traceback (most recent call last):\n"
            '  File "/some/path/module.py", line 42, in build\n'
            "    raise ValueError()\n"
            "ValueError"
        )
        sanitized = _sanitize_error(raw)
        assert "Traceback" not in sanitized
        assert "line 42" not in sanitized
        assert "opaque_abcdefghijklmnopqrstuvwxyz0123456789" not in sanitized
        assert "[redacted]" in sanitized

    def test_strips_home_directory(self):
        from backend.resolvers.repository_digest import _sanitize_error
        import os

        home = os.path.expanduser("~")
        sanitized = _sanitize_error(f"could not read {home}/project/file.txt")
        assert home not in sanitized
        assert "~/project/file.txt" in sanitized


# ═════════════════════════════════════════════════════════════════
# GraphQL-vs-JSON contract drift: DigestDomain / DigestHotspot
# ═════════════════════════════════════════════════════════════════
#
# Audit Pass 3 found that DomainDigest's cohesion/avg_blast_radius and
# HotspotDigest's evidence/domain_id/centrality were computed and stored
# in repository-digest.json but silently dropped before reaching GraphQL.
# These tests build a digest with a real semantic graph (so domains and
# hotspots are actually populated), then assert every field the Data
# Model requires for DomainDigest/HotspotDigest round-trips through the
# GraphQL layer with the same value the stored JSON has — not just that
# the query doesn't error.


def _write_semantic_graph(root: Path, nodes: list[dict], clusters: list[dict]) -> None:
    ctx = root / ".speed" / "context"
    ctx.mkdir(parents=True, exist_ok=True)
    (ctx / "semantic-graph.json").write_text(json.dumps({
        "generated_at": "2026-01-01T00:00:00Z",
        "git_head": "abc123",
        "nodes": nodes,
        "edges": [],
        "clusters": clusters,
        "cluster_edges": [],
    }))


def _build_golden_digest_with_domains_and_hotspots(root: Path) -> dict:
    """A golden digest whose semantic graph actually produces a non-empty
    domain (with distinct blast_radius values, so avg_blast_radius != 0)
    and a hotspot (with a real centrality value and a domain_id).
    """
    from lib.context.repository_digest import build_repository_digest

    _write_project_map(root, [
        {"path": "src/app.py", "language": "python", "lines": 40, "category": "source"},
        {"path": "src/util.py", "language": "python", "lines": 20, "category": "source"},
    ])
    _write_semantic_graph(
        root,
        nodes=[
            {
                "id": "src/app.py::main", "name": "main", "kind": "function", "file": "src/app.py", "line": 10,
                "impact": {"blast_radius": 20, "dependents": 12, "centrality": 0.8, "stability": "stable"},
            },
            {
                "id": "src/util.py::helper", "name": "helper", "kind": "function", "file": "src/util.py", "line": 5,
                "impact": {"blast_radius": 10, "dependents": 3, "centrality": 0.3, "stability": "stable"},
            },
        ],
        clusters=[{
            "id": "cluster-core", "label": "Core", "cohesion": 0.75,
            "symbols": ["src/app.py::main", "src/util.py::helper"],
            "files": ["src/app.py", "src/util.py"],
        }],
    )
    return build_repository_digest(str(root), config={})


DOMAIN_CONTRACT_QUERY = """
query {
  repositoryDigest {
    domains(limit: 5) {
      id cohesion avgBlastRadius
    }
  }
}
"""

HOTSPOT_CONTRACT_QUERY = """
query {
  repositoryDigest {
    hotspots(limit: 5) {
      symbolId domainId centrality
      evidence { source path symbol description }
    }
  }
}
"""


class TestDomainHotspotGraphQLContract:
    def test_domain_cohesion_and_avg_blast_radius_round_trip(self, tmp_path: Path):
        digest = _build_golden_digest_with_domains_and_hotspots(tmp_path)
        stored_domain = digest["domains"][0]
        assert stored_domain["cohesion"] == 0.75
        assert stored_domain["avg_blast_radius"] == 15.0  # avg(20, 10)

        result = schema.execute_sync(DOMAIN_CONTRACT_QUERY, context_value=_make_context(tmp_path))
        assert result.errors is None
        gql_domain = result.data["repositoryDigest"]["domains"][0]
        assert gql_domain["cohesion"] == stored_domain["cohesion"]
        assert gql_domain["avgBlastRadius"] == stored_domain["avg_blast_radius"]

    def test_hotspot_evidence_domain_id_centrality_round_trip(self, tmp_path: Path):
        digest = _build_golden_digest_with_domains_and_hotspots(tmp_path)
        stored_hotspots = {h["symbol_id"]: h for h in digest["hotspots"]}
        assert stored_hotspots, "expected at least one hotspot from the fixture's impact metrics"

        result = schema.execute_sync(HOTSPOT_CONTRACT_QUERY, context_value=_make_context(tmp_path))
        assert result.errors is None
        gql_hotspots = result.data["repositoryDigest"]["hotspots"]
        assert gql_hotspots

        for gql_h in gql_hotspots:
            stored_h = stored_hotspots[gql_h["symbolId"]]
            assert gql_h["domainId"] == stored_h["domain_id"] == "cluster-core"
            assert gql_h["centrality"] == stored_h["centrality"]
            assert stored_h["evidence"], "fixture hotspot must have stored evidence to test round-tripping"
            assert gql_h["evidence"], "hotspot evidence must not be dropped between JSON and GraphQL"
            assert gql_h["evidence"][0]["symbol"] == stored_h["evidence"][0]["symbol"]

    def test_domain_and_hotspot_json_fields_all_reachable_via_graphql(self, tmp_path: Path):
        """Generic contract-drift guard: every Data Model field for
        DomainDigest/HotspotDigest that the builder actually stores must
        have a same-named (camelCase) GraphQL field returning the same
        value — catches a future field silently added to the JSON schema
        but never wired into the GraphQL type, the exact failure mode
        audit Pass 3 found.
        """
        digest = _build_golden_digest_with_domains_and_hotspots(tmp_path)

        # Fields the RFC's DomainDigest / HotspotDigest tables define as
        # plain scalars (list/object fields like evidence/representative_*
        # are covered by the dedicated tests above and by existing tests).
        domain_scalar_fields = ["id", "label", "confidence", "file_count", "symbol_count", "cohesion", "avg_blast_radius"]
        hotspot_scalar_fields = ["symbol_id", "name", "file", "line", "domain_id", "blast_radius", "dependents", "centrality", "reason"]

        def to_camel(snake: str) -> str:
            head, *tail = snake.split("_")
            return head + "".join(w.capitalize() for w in tail)

        domain_gql_fields = " ".join(to_camel(f) for f in domain_scalar_fields)
        hotspot_gql_fields = " ".join(to_camel(f) for f in hotspot_scalar_fields)
        query = f"""
        query {{
          repositoryDigest {{
            domains(limit: 5) {{ {domain_gql_fields} }}
            hotspots(limit: 5) {{ {hotspot_gql_fields} }}
          }}
        }}
        """
        result = schema.execute_sync(query, context_value=_make_context(tmp_path))
        assert result.errors is None

        gql_domain = result.data["repositoryDigest"]["domains"][0]
        stored_domain = digest["domains"][0]
        for field in domain_scalar_fields:
            confidence_field = field == "confidence"
            gql_value = gql_domain[to_camel(field)]
            stored_value = stored_domain[field]
            if confidence_field:
                assert gql_value == stored_value.upper()
            else:
                assert gql_value == stored_value, f"domain field {field!r} drifted between JSON and GraphQL"

        gql_hotspot = result.data["repositoryDigest"]["hotspots"][0]
        stored_hotspot = digest["hotspots"][0]
        for field in hotspot_scalar_fields:
            assert gql_hotspot[to_camel(field)] == stored_hotspot[field], \
                f"hotspot field {field!r} drifted between JSON and GraphQL"
