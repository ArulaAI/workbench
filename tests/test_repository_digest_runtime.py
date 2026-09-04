"""Unit tests for lib/context/repository_digest_runtime.py — Phase 4
Runtime & Configuration, with a heavy focus on secret redaction.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_project_root = str(Path(__file__).parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from lib.context.repository_digest_runtime import (
    derive_runtimes,
    derive_frameworks,
    derive_config_sources,
    derive_environment_variables,
    _looks_sensitive,
)


class TestDeriveRuntimes:
    def test_dockerfile_from_line(self, tmp_path):
        (tmp_path / "Dockerfile").write_text("FROM python:3.12-slim AS base\n")
        runtimes = derive_runtimes(tmp_path)
        assert runtimes[0] == {
            "language": "python", "version": "3.12-slim", "source_file": "Dockerfile",
            "evidence": runtimes[0]["evidence"],
        }
        assert runtimes[0]["evidence"][0]["line"] == 1

    def test_dockerfile_unrecognized_base_image_is_skipped(self, tmp_path):
        (tmp_path / "Dockerfile").write_text("FROM ghcr.io/myorg/custom-base:latest\n")
        assert derive_runtimes(tmp_path) == []

    def test_pyproject_requires_python(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text('[project]\nrequires-python = ">=3.11"\n')
        runtimes = derive_runtimes(tmp_path)
        assert runtimes[0]["language"] == "python"
        assert runtimes[0]["version"] == ">=3.11"

    def test_package_json_engines(self, tmp_path):
        (tmp_path / "package.json").write_text(json.dumps({"engines": {"node": ">=22"}}))
        runtimes = derive_runtimes(tmp_path)
        assert runtimes[0] == {
            "language": "node", "version": ">=22", "source_file": "package.json",
            "evidence": runtimes[0]["evidence"],
        }

    def test_python_version_file(self, tmp_path):
        (tmp_path / ".python-version").write_text("3.12.1\n")
        runtimes = derive_runtimes(tmp_path)
        assert runtimes[0]["language"] == "python"
        assert runtimes[0]["version"] == "3.12.1"

    def test_go_mod_directive(self, tmp_path):
        (tmp_path / "go.mod").write_text("module example.com/x\n\ngo 1.22\n")
        runtimes = derive_runtimes(tmp_path)
        assert runtimes[0] == {"language": "go", "version": "1.22", "source_file": "go.mod", "evidence": runtimes[0]["evidence"]}

    def test_no_manifests_returns_empty(self, tmp_path):
        assert derive_runtimes(tmp_path) == []

    def test_malformed_package_json_does_not_crash(self, tmp_path):
        (tmp_path / "package.json").write_text("{not valid json")
        assert derive_runtimes(tmp_path) == []

    def test_nested_package_json_engines_via_project_map(self, tmp_path):
        frontend = tmp_path / "dashboard" / "frontend"
        frontend.mkdir(parents=True)
        (frontend / "package.json").write_text(json.dumps({"engines": {"node": ">=20"}}))
        project_map = {"files": [{"path": "dashboard/frontend/package.json"}]}
        runtimes = derive_runtimes(tmp_path, project_map)
        assert runtimes[0] == {
            "language": "node", "version": ">=20", "source_file": "dashboard/frontend/package.json",
            "evidence": runtimes[0]["evidence"],
        }

    def test_no_project_map_ignores_nested_package_json(self, tmp_path):
        frontend = tmp_path / "dashboard" / "frontend"
        frontend.mkdir(parents=True)
        (frontend / "package.json").write_text(json.dumps({"engines": {"node": ">=20"}}))
        assert derive_runtimes(tmp_path) == []


class TestDeriveFrameworks:
    def test_js_framework_from_package_json(self, tmp_path):
        (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"react": "^18.0.0"}}))
        fws = derive_frameworks(tmp_path)
        assert fws[0]["name"] == "react"
        assert fws[0]["version"] == "^18.0.0"

    def test_nested_package_json_framework_via_project_map(self, tmp_path):
        frontend = tmp_path / "dashboard" / "frontend"
        frontend.mkdir(parents=True)
        (frontend / "package.json").write_text(json.dumps({"dependencies": {"next": "^15.0.0", "react": "^18.0.0"}}))
        project_map = {"files": [{"path": "dashboard/frontend/package.json"}]}
        fws = derive_frameworks(tmp_path, project_map)
        names = {f["name"] for f in fws}
        assert names == {"next", "react"}
        assert all(f["source_file"] == "dashboard/frontend/package.json" for f in fws)

    def test_unknown_js_package_is_not_a_framework(self, tmp_path):
        (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"lodash": "^4.0.0"}}))
        assert derive_frameworks(tmp_path) == []

    def test_python_framework_from_requirements_txt(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("fastapi==0.110.0\nrequests>=2\n")
        fws = derive_frameworks(tmp_path)
        assert [f["name"] for f in fws] == ["fastapi"]

    def test_python_framework_from_pyproject_dependencies(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text('[project]\ndependencies = ["django>=4.0", "requests"]\n')
        fws = derive_frameworks(tmp_path)
        assert [f["name"] for f in fws] == ["django"]

    def test_no_manifests_returns_empty(self, tmp_path):
        assert derive_frameworks(tmp_path) == []

    def test_deduplicates_same_name_and_source(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("fastapi==0.110.0\nfastapi\n")
        fws = derive_frameworks(tmp_path)
        assert len(fws) == 1


class TestDeriveConfigSources:
    def test_detects_present_files_only(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "Dockerfile").write_text("FROM scratch\n")
        sources = {s["file"] for s in derive_config_sources(tmp_path)}
        assert sources == {"package.json", "Dockerfile"}

    def test_empty_repo_returns_empty(self, tmp_path):
        assert derive_config_sources(tmp_path) == []

    def test_nested_package_json_via_project_map(self, tmp_path):
        frontend = tmp_path / "dashboard" / "frontend"
        frontend.mkdir(parents=True)
        (frontend / "package.json").write_text("{}")
        project_map = {"files": [{"path": "dashboard/frontend/package.json"}]}
        sources = {s["file"] for s in derive_config_sources(tmp_path, project_map)}
        assert sources == {"dashboard/frontend/package.json"}

    def test_root_and_nested_package_json_both_listed_without_duplication(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        frontend = tmp_path / "dashboard" / "frontend"
        frontend.mkdir(parents=True)
        (frontend / "package.json").write_text("{}")
        project_map = {"files": [{"path": "package.json"}, {"path": "dashboard/frontend/package.json"}]}
        sources = [s["file"] for s in derive_config_sources(tmp_path, project_map)]
        assert sources == ["package.json", "dashboard/frontend/package.json"]


class TestSecretRedaction:
    def test_looks_sensitive_matches_key_secret_token_password(self):
        assert _looks_sensitive("OPENAI_API_KEY")
        assert _looks_sensitive("DB_PASSWORD")
        assert _looks_sensitive("AUTH_TOKEN")
        assert _looks_sensitive("CLIENT_SECRET")

    def test_looks_sensitive_false_for_ordinary_names(self):
        assert not _looks_sensitive("DATABASE_URL")
        assert not _looks_sensitive("DEBUG")
        assert not _looks_sensitive("PORT")

    def test_env_keys_json_values_never_reach_output(self, tmp_path):
        # env_keys_raw simulates env-keys.json — already names-only by
        # construction (env_extract.py strips values before this runs).
        env_keys_raw = {".env": ["DATABASE_URL", "OPENAI_API_KEY"]}
        result, warnings = derive_environment_variables(tmp_path, env_keys_raw)
        names = {e["name"] for e in result}
        assert names == {"DATABASE_URL", "OPENAI_API_KEY"}
        assert warnings == []
        for e in result:
            assert "value" not in e
            for k, v in e.items():
                assert "supersecret" not in str(v)

    def test_dockerfile_env_value_never_appears_anywhere_in_output(self, tmp_path):
        (tmp_path / "Dockerfile").write_text(
            "FROM python:3.12\n"
            "ENV DATABASE_URL=postgres://user:supersecret@host/db\n"
            "ARG OPENAI_API_KEY\n"
        )
        result, _ = derive_environment_variables(tmp_path, None)
        blob = json.dumps(result)
        assert "supersecret" not in blob
        assert "postgres://" not in blob
        names = {e["name"] for e in result}
        assert names == {"DATABASE_URL", "OPENAI_API_KEY"}
        by_name = {e["name"]: e for e in result}
        assert by_name["OPENAI_API_KEY"]["looks_sensitive"] is True
        assert by_name["DATABASE_URL"]["looks_sensitive"] is False

    def test_docker_compose_environment_mapping_form(self, tmp_path):
        (tmp_path / "docker-compose.yml").write_text(
            "services:\n  web:\n    environment:\n      DATABASE_URL: postgres://x:secretpw@host/db\n"
        )
        result, warnings = derive_environment_variables(tmp_path, None)
        blob = json.dumps(result)
        assert "secretpw" not in blob
        assert {e["name"] for e in result} == {"DATABASE_URL"}
        assert warnings == []

    def test_docker_compose_environment_list_form(self, tmp_path):
        (tmp_path / "docker-compose.yml").write_text(
            "services:\n  web:\n    environment:\n      - DATABASE_URL=postgres://x:secretpw@host/db\n      - DEBUG=true\n"
        )
        result, warnings = derive_environment_variables(tmp_path, None)
        blob = json.dumps(result)
        assert "secretpw" not in blob
        assert {e["name"] for e in result} == {"DATABASE_URL", "DEBUG"}
        assert warnings == []

    def test_no_sources_returns_empty(self, tmp_path):
        assert derive_environment_variables(tmp_path, None) == ([], [])

    def test_none_env_keys_raw_does_not_crash(self, tmp_path):
        assert derive_environment_variables(tmp_path, None) == ([], [])

    def test_malformed_env_keys_raw_shape_does_not_crash(self, tmp_path):
        assert derive_environment_variables(tmp_path, {"weird": "not-a-list"}) == ([], [])
        assert derive_environment_variables(tmp_path, ["not", "a", "dict"]) == ([], [])

    def test_deduplicates_same_name_and_source(self, tmp_path):
        env_keys_raw = {".env": ["DATABASE_URL"]}
        (tmp_path / "Dockerfile").write_text("FROM python:3.12\nENV DATABASE_URL=x\n")
        result, _ = derive_environment_variables(tmp_path, env_keys_raw)
        # Different source files -> both kept, not merged into one.
        assert {(e["name"], e["source_file"]) for e in result} == {
            ("DATABASE_URL", ".env"), ("DATABASE_URL", "Dockerfile"),
        }

    def test_malformed_docker_compose_does_not_crash(self, tmp_path):
        (tmp_path / "docker-compose.yml").write_text("not: valid: yaml: [")
        result, warnings = derive_environment_variables(tmp_path, None)
        assert result == []

    def test_malformed_docker_compose_produces_a_warning_not_silence(self, tmp_path):
        # Code-review finding: a docker-compose.yml that fails to parse
        # used to silently drop every env var name it would have
        # declared, with zero trace anywhere in the digest.
        (tmp_path / "docker-compose.yml").write_text("not: valid: yaml: [")
        result, warnings = derive_environment_variables(tmp_path, None)
        assert result == []
        assert any("docker-compose.yml" in w for w in warnings), f"warnings={warnings!r}"

    def test_valid_docker_compose_alongside_a_malformed_one_still_reports_the_valid_names(self, tmp_path):
        # docker-compose.yml and .yaml are both checked; one failing to
        # parse must not suppress names correctly found in the other.
        (tmp_path / "docker-compose.yml").write_text("not: valid: yaml: [")
        (tmp_path / "docker-compose.yaml").write_text(
            "services:\n  web:\n    environment:\n      DATABASE_URL: postgres://x:secretpw@host/db\n"
        )
        result, warnings = derive_environment_variables(tmp_path, None)
        assert {e["name"] for e in result} == {"DATABASE_URL"}
        assert any("docker-compose.yml" in w for w in warnings), f"warnings={warnings!r}"
