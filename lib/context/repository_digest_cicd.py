"""Repository Digest — Phase 4: CI/CD.

Structural parsing is implemented only for GitHub Actions, the one CI
provider this repository already has partial support for
(command_discovery.py's discover_from_ci_workflows() already loads these
same files with the same YAML library for a different purpose — pulling
`run:` lines for command corroboration). This module does its own,
independent parse of the same file set to build the richer
name/trigger/jobs/needs structure the Architecture screen's sibling
API/Data and Runtime screens don't need, rather than repurpose that
already-tested function.

Other CI providers (GitLab CI, CircleCI, Jenkins, Azure Pipelines, Drone)
are detected by file presence only — never claimed as "parsed" when this
module cannot reliably read their job/stage structure.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .repository_digest_schema import make_evidence

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover - PyYAML is a project dependency
    yaml = None  # type: ignore

_WORKFLOW_GLOBS = (".github/workflows/*.yml", ".github/workflows/*.yaml")

_OTHER_PROVIDERS: tuple[tuple[str, str], ...] = (
    ("gitlab_ci", ".gitlab-ci.yml"),
    ("circleci", ".circleci/config.yml"),
    ("jenkins", "Jenkinsfile"),
    ("azure_pipelines", "azure-pipelines.yml"),
    ("drone", ".drone.yml"),
)


def _normalize_triggers(on_value: Any) -> list[str]:
    if isinstance(on_value, str):
        return [on_value]
    if isinstance(on_value, list):
        return [str(v) for v in on_value]
    if isinstance(on_value, dict):
        return list(on_value.keys())
    return []


def _normalize_needs(needs_value: Any) -> list[str]:
    if isinstance(needs_value, str):
        return [needs_value]
    if isinstance(needs_value, list):
        return [str(v) for v in needs_value]
    return []


def _job_commands(job: dict[str, Any]) -> list[str]:
    commands: list[str] = []
    for step in job.get("steps") or []:
        if not isinstance(step, dict):
            continue
        run = step.get("run")
        if isinstance(run, str):
            for line in run.splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    commands.append(line)
    return commands


def derive_github_actions_workflows(project_root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Returns (workflows, warnings). A workflow file that fails to parse
    produces a warning naming the file, never a silent skip and never a
    crash — this is the one place malformed CI YAML must be visible.
    """
    workflows: list[dict[str, Any]] = []
    warnings: list[str] = []

    if yaml is None:
        return workflows, warnings

    seen_paths: set[str] = set()
    for pattern in _WORKFLOW_GLOBS:
        for path in sorted(project_root.glob(pattern)):
            if not path.is_file():
                continue
            rel_path = str(path.relative_to(project_root)).replace(os.sep, "/")
            if rel_path in seen_paths:
                continue
            seen_paths.add(rel_path)

            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                warnings.append(f"could not read CI workflow {rel_path}")
                continue
            try:
                doc = yaml.safe_load(text)
            except Exception as exc:  # noqa: BLE001 - any YAML error is a warning, not a crash
                warnings.append(f"could not parse CI workflow {rel_path}: {exc}")
                continue
            if not isinstance(doc, dict):
                warnings.append(f"CI workflow {rel_path} is not a mapping at the top level — skipped")
                continue

            name = doc.get("name") or path.stem
            triggers = _normalize_triggers(doc.get(True) if True in doc else doc.get("on"))
            jobs_raw = doc.get("jobs") if isinstance(doc.get("jobs"), dict) else {}

            jobs: list[dict[str, Any]] = []
            for job_name, job in jobs_raw.items():
                if not isinstance(job, dict):
                    continue
                jobs.append({
                    "name": str(job_name),
                    "runs_on": job.get("runs-on") if isinstance(job.get("runs-on"), str) else None,
                    "needs": _normalize_needs(job.get("needs")),
                    "commands": _job_commands(job),
                })

            if not jobs:
                warnings.append(f"CI workflow {rel_path} has no parseable jobs")

            workflows.append({
                "name": str(name),
                "provider": "github_actions",
                "config_file": rel_path,
                "triggers": triggers,
                "jobs": jobs,
                "evidence": [make_evidence("manifest", f"GitHub Actions workflow '{name}'", path=rel_path)],
            })

    return workflows, warnings


def derive_other_ci_providers(project_root: Path) -> list[dict[str, Any]]:
    """File-presence-only detection for CI systems this module cannot
    reliably parse. Never fabricates jobs/triggers for these — the
    frontend must show them as "detected, not parsed".
    """
    detected: list[dict[str, Any]] = []
    for provider, rel in _OTHER_PROVIDERS:
        path = project_root / rel
        if path.is_file():
            detected.append({
                "provider": provider,
                "config_file": rel,
                "evidence": [make_evidence("manifest", f"{provider} configuration file present", path=rel)],
            })
    return detected
