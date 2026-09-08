"""Contract tests for Define orchestration and connected package audit."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "skills/workbench-define/scripts/define.py"
FEATURE = "task-due-dates"


def _run(root: Path, *args: str) -> dict:
    result = subprocess.run(
        [str(REPO / ".venv/bin/python3"), str(SCRIPT), FEATURE, *args,
         "--project-root", str(root), "--json"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _published(root: Path, kind: str, content: str, upstream: dict | None = None) -> dict:
    spec = root / "specs" / FEATURE / f"{kind}.md"
    spec.parent.mkdir(parents=True, exist_ok=True)
    spec.write_text(content, encoding="utf-8")
    digest = hashlib.sha256(content.encode()).hexdigest()
    feature_dir = root / ".speed" / "features" / FEATURE
    feature_dir.mkdir(parents=True, exist_ok=True)
    state = {
        "status": "published",
        "revision": 3,
        "published_revision": 3,
        "artifact": {"path": f"specs/{FEATURE}/{kind}.md", "sha256": digest},
        "self_review": {"status": "passed"},
        "review_comment_threads": [],
        "upstream": upstream or {},
    }
    (feature_dir / f"authoring-{kind}.json").write_text(json.dumps(state), encoding="utf-8")
    (feature_dir / f"claim-{kind}.json").write_text(
        json.dumps({"claimant": "Mohit", "claimant_email": "mohit@example.com"}),
        encoding="utf-8",
    )
    return {"path": f"specs/{FEATURE}/{kind}.md", "sha256": digest}


def _complete_core_package(root: Path) -> None:
    prd = _published(
        root,
        "prd",
        "# PRD\n\n## Requirements & Acceptance\n\n| ID | Behavior | Done when |\n|---|---|---|\n| REQ-1 | Save a due date. | Reload returns it. |\n",
    )
    design = _published(
        root,
        "design",
        "# Design\n\nPublished PRD behavior and failure states.\n",
        {"prd": prd},
    )
    _published(
        root,
        "rfc",
        "# RFC\n\nImplement the published PRD and Design contracts.\n",
        {"prd": prd, "design": design},
    )


def test_reconcile_reports_the_earliest_safe_action_and_writes_the_index(tmp_path: Path):
    package = _run(tmp_path)

    assert package["next_action"]["stage"] == "prd"
    assert package["next_action"]["command"] == f"workbench draft prd {FEATURE}"
    assert package["plan_readiness"]["status"] == "blocked"
    assert (tmp_path / ".speed/features" / FEATURE / "define-package.json").is_file()
    assert "ADR and evaluation" in (tmp_path / "specs" / FEATURE / "index.md").read_text()


def test_connected_audit_freezes_hashes_and_writes_an_immutable_report(tmp_path: Path):
    _complete_core_package(tmp_path)

    report = _run(tmp_path, "--audit")

    assert report["status"] == "passed"
    assert report["inputs"]["artifacts"].keys() == {"prd", "design", "rfc"}
    assert all(item["finding_id"] for item in report["findings"])
    assert {item["severity"] for item in report["findings"]} == {"warn"}
    report_path = tmp_path / report["report_path"]
    assert report_path.is_file()
    before = report_path.read_bytes()
    second = _run(tmp_path, "--audit")
    assert second["report_path"] != report["report_path"]
    assert report_path.read_bytes() == before


def test_reconcile_marks_the_previous_audit_stale_after_material_change(tmp_path: Path):
    _complete_core_package(tmp_path)
    _run(tmp_path, "--audit")
    design = tmp_path / "specs" / FEATURE / "design.md"
    design.write_text(design.read_text() + "\nChanged after audit.\n", encoding="utf-8")

    package = _run(tmp_path)

    assert package["connected_audit"]["status"] == "stale"
    assert package["connected_audit"]["stale"] is True
    assert package["next_action"]["stage"] == "design"


def test_connected_audit_fails_when_required_artifacts_are_missing(tmp_path: Path):
    report = _run(tmp_path, "--audit")

    assert report["status"] == "failed"
    failures = [item for item in report["findings"] if item["severity"] == "fail"]
    assert {item["artifact"] for item in failures} == {"prd", "design", "rfc"}
    assert all(item["check_id"] == "PKG-ARTIFACT-PUBLISHED" for item in failures)


def test_connected_audit_rejects_duplicate_requirement_row_ids(tmp_path: Path):
    _complete_core_package(tmp_path)
    content = (
        "# PRD\n\n## Requirements & Acceptance\n\n"
        "| ID | Behavior | Done when |\n|---|---|---|\n"
        "| REQ-1 | Save a due date. | Reload returns it. |\n"
        "| REQ-1 | Clear a due date. | Reload omits it. |\n"
    )
    spec = tmp_path / "specs" / FEATURE / "prd.md"
    spec.write_text(content, encoding="utf-8")
    state_path = tmp_path / ".speed" / "features" / FEATURE / "authoring-prd.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["artifact"]["sha256"] = hashlib.sha256(content.encode()).hexdigest()
    state_path.write_text(json.dumps(state), encoding="utf-8")

    report = _run(tmp_path, "--audit")

    assert any(
        item["check_id"] == "PRD-STABLE-REQUIREMENTS"
        and "not unique" in item["evidence"]
        for item in report["findings"]
    )


def test_workbench_routes_feature_define_and_audit_to_the_connected_skill(tmp_path: Path):
    env = {**os.environ, "SPEED_PROJECT_ROOT": str(tmp_path)}
    defined = subprocess.run(
        [str(REPO / "workbench"), "define", FEATURE, "--json"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert defined.returncode == 0, defined.stderr
    assert json.loads(defined.stdout)["next_action"]["stage"] == "prd"

    audited = subprocess.run(
        [str(REPO / "workbench"), "audit", FEATURE, "--json"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert audited.returncode == 0, audited.stderr
    assert json.loads(audited.stdout)["status"] == "failed"
