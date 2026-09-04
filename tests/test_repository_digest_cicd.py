"""Unit tests for lib/context/repository_digest_cicd.py — Phase 4 CI/CD."""

from __future__ import annotations

import sys
from pathlib import Path

_project_root = str(Path(__file__).parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from lib.context.repository_digest_cicd import (
    derive_github_actions_workflows,
    derive_other_ci_providers,
)


def _write(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


class TestGithubActionsWorkflows:
    def test_parses_name_triggers_jobs_needs_commands(self, tmp_path):
        _write(tmp_path, ".github/workflows/ci.yml", """
name: CI
on:
  push:
    branches: [main]
  pull_request: {}
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - run: pytest
  build:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - run: |
          npm install
          npm run build
""")
        workflows, warnings = derive_github_actions_workflows(tmp_path)
        assert warnings == []
        assert len(workflows) == 1
        wf = workflows[0]
        assert wf["name"] == "CI"
        assert wf["provider"] == "github_actions"
        assert set(wf["triggers"]) == {"push", "pull_request"}
        jobs = {j["name"]: j for j in wf["jobs"]}
        assert jobs["test"]["commands"] == ["pytest"]
        assert jobs["build"]["needs"] == ["test"]
        assert jobs["build"]["commands"] == ["npm install", "npm run build"]

    def test_on_as_bare_string_trigger(self, tmp_path):
        _write(tmp_path, ".github/workflows/x.yml", "name: X\non: push\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps: []\n")
        workflows, _ = derive_github_actions_workflows(tmp_path)
        assert workflows[0]["triggers"] == ["push"]

    def test_missing_workflows_directory_returns_empty(self, tmp_path):
        workflows, warnings = derive_github_actions_workflows(tmp_path)
        assert workflows == []
        assert warnings == []

    def test_multiple_workflow_files(self, tmp_path):
        _write(tmp_path, ".github/workflows/a.yml", "name: A\non: push\njobs:\n  x:\n    runs-on: ubuntu-latest\n    steps: []\n")
        _write(tmp_path, ".github/workflows/b.yaml", "name: B\non: push\njobs:\n  y:\n    runs-on: ubuntu-latest\n    steps: []\n")
        workflows, _ = derive_github_actions_workflows(tmp_path)
        assert {w["name"] for w in workflows} == {"A", "B"}

    def test_malformed_yaml_produces_a_warning_not_a_crash(self, tmp_path):
        _write(tmp_path, ".github/workflows/broken.yml", "name: [unterminated\njobs: {\n")
        workflows, warnings = derive_github_actions_workflows(tmp_path)
        assert workflows == []
        assert any("broken.yml" in w for w in warnings)

    def test_non_mapping_yaml_produces_a_warning(self, tmp_path):
        _write(tmp_path, ".github/workflows/list.yml", "- just\n- a\n- list\n")
        workflows, warnings = derive_github_actions_workflows(tmp_path)
        assert workflows == []
        assert any("list.yml" in w for w in warnings)

    def test_workflow_with_no_jobs_produces_a_warning(self, tmp_path):
        _write(tmp_path, ".github/workflows/empty.yml", "name: Empty\non: push\n")
        workflows, warnings = derive_github_actions_workflows(tmp_path)
        assert len(workflows) == 1
        assert any("no parseable jobs" in w for w in warnings)

    def test_workflow_name_falls_back_to_filename(self, tmp_path):
        _write(tmp_path, ".github/workflows/nameless.yml", "on: push\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps: []\n")
        workflows, _ = derive_github_actions_workflows(tmp_path)
        assert workflows[0]["name"] == "nameless"

    def test_job_with_no_runs_on_has_null_runs_on(self, tmp_path):
        _write(tmp_path, ".github/workflows/x.yml", "on: push\njobs:\n  a:\n    steps: []\n")
        workflows, _ = derive_github_actions_workflows(tmp_path)
        assert workflows[0]["jobs"][0]["runs_on"] is None


class TestOtherCiProviders:
    def test_detects_gitlab_ci_by_presence_only(self, tmp_path):
        _write(tmp_path, ".gitlab-ci.yml", "stages: [test]\n")
        detected = derive_other_ci_providers(tmp_path)
        assert len(detected) == 1
        assert detected[0]["provider"] == "gitlab_ci"
        assert "jobs" not in detected[0]  # never fabricates structure

    def test_no_ci_files_returns_empty(self, tmp_path):
        assert derive_other_ci_providers(tmp_path) == []

    def test_detects_multiple_providers(self, tmp_path):
        _write(tmp_path, ".gitlab-ci.yml", "stages: []\n")
        _write(tmp_path, "Jenkinsfile", "pipeline {}\n")
        detected = {d["provider"] for d in derive_other_ci_providers(tmp_path)}
        assert detected == {"gitlab_ci", "jenkins"}
