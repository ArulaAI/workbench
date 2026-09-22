import json
import uuid
from pathlib import Path
from unittest.mock import patch

from dashboard.backend.paths import SpeedPaths
from dashboard.backend.db import connect, migrate
from dashboard.backend.schema import schema
from lib.defect_findings import publish_attempt, read_findings


def _project(root: Path) -> SpeedPaths:
    (root / "specs/product").mkdir(parents=True)
    (root / "specs/product/payments.md").write_text("# Payments\n")
    (root / "src/payments").mkdir(parents=True)
    (root / "src/payments/service.ts").write_text("\n".join(f"line {line}" for line in range(1, 61)) + "\n")
    paths = SpeedPaths(root)
    publish_attempt(paths, "payments", "structured_review", "4", {
        "issues": [{
            "message": "Retry charges twice", "observed": "Two charges are created.",
            "expected": "Only one charge exists.", "reproduction": "Run retry test.",
            "severity": "major", "file": "src/payments/service.ts", "line": 25,
        }],
    })
    return paths


def test_feature_findings_and_report_queries_share_core(tmp_path):
    _project(tmp_path)
    result = schema.execute_sync(
        "query { featureFindings(featureName: \"payments\") }",
        context_value={"project_root": tmp_path},
    )
    assert result.errors is None
    view = result.data["featureFindings"]
    assert view["feature"] == "payments"
    assert view["findings"][0]["evidence"][0]["producer"] == "structured_review"

    report = schema.execute_sync(
        "query { defectReport(features: [\"payments\"]) }",
        context_value={"project_root": tmp_path},
    )
    assert report.errors is None
    assert report.data["defectReport"]["totals"]["total"] == 0


def test_evidence_file_query_returns_only_declared_contained_source(tmp_path):
    paths = _project(tmp_path)
    finding = read_findings(paths, "payments")["findings"][0]
    evidence = finding["evidence"][0]
    query = """
      query Evidence($finding: String!, $evidence: String!, $path: String!) {
        evidenceFile(
          featureName: "payments", findingId: $finding,
          evidenceId: $evidence, sourcePath: $path
        )
      }
    """
    variables = {"finding": finding["id"], "evidence": evidence["id"], "path": "src/payments/service.ts:25"}
    result = schema.execute_sync(query, variable_values=variables, context_value={"project_root": tmp_path})
    assert result.errors is None
    payload = result.data["evidenceFile"]
    assert payload["success"] is True
    assert payload["highlight_line"] == 25
    assert payload["start_line"] == 5
    assert "line 25" in payload["content"]

    variables["path"] = "specs/product/payments.md"
    rejected = schema.execute_sync(query, variable_values=variables, context_value={"project_root": tmp_path})
    assert rejected.data["evidenceFile"]["code"] == "INVALID_INPUT"


def test_evidence_file_query_allows_declared_speed_task_file(tmp_path):
    (tmp_path / "specs/product").mkdir(parents=True)
    (tmp_path / "specs/product/payments.md").write_text("# Payments\n")
    task_path = tmp_path / ".speed/features/payments/tasks/1.json"
    task_path.parent.mkdir(parents=True)
    task_path.write_text('{"id": "1", "title": "Payment task"}\n')
    paths = SpeedPaths(tmp_path)
    publish_attempt(paths, "payments", "structured_review", "1", {"issues": [{
        "message": "Task metadata changed", "file": ".speed/features/payments/tasks/1.json",
    }]})
    finding = read_findings(paths, "payments")["findings"][0]
    evidence = finding["evidence"][0]
    query = """query Evidence($finding: String!, $evidence: String!) { evidenceFile(
      featureName: "payments", findingId: $finding, evidenceId: $evidence,
      sourcePath: ".speed/features/payments/tasks/1.json"
    ) }"""
    variables = {"finding": finding["id"], "evidence": evidence["id"]}
    result = schema.execute_sync(
        query, variable_values=variables, context_value={"project_root": tmp_path},
    )
    assert result.errors is None
    assert result.data["evidenceFile"]["success"] is True
    assert "Payment task" in result.data["evidenceFile"]["content"]

    outside = tmp_path.parent / f"{tmp_path.name}-outside.json"
    outside.write_text('{"secret": true}\n')
    task_path.unlink()
    task_path.symlink_to(outside)
    escaped = schema.execute_sync(
        query, variable_values=variables, context_value={"project_root": tmp_path},
    )
    assert escaped.data["evidenceFile"]["code"] == "INVALID_INPUT"


def test_file_mutation_creates_canonical_report_and_state(tmp_path):
    paths = _project(tmp_path)
    finding = read_findings(paths, "payments")["findings"][0]
    query = """
      mutation File($input: FileFindingDefectInput!) {
        fileFindingDefect(input: $input)
      }
    """
    variables = {"input": {
        "featureName": "payments", "findingId": finding["id"],
        "evidenceIds": [item["id"] for item in finding["evidence"]],
        "findingRevision": finding["revision"], "decisionRevision": 0,
        "requestId": str(uuid.uuid4()), "rationale": "Track after launch",
        "draft": {
            "title": "Retry charges twice", "severity": "P1", "severityConfirmed": True,
            "relatedFeatures": ["payments"], "observed": "Two charges are created.",
            "expected": "Only one charge exists.", "reproduction": "Run retry test.", "context": "Review task 4.",
        },
    }}
    conn = connect(tmp_path)
    migrate(conn)
    with patch("dashboard.backend.resolvers.feature_defects.get_current_actor", return_value=("Alex", "alex@example.test")):
        result = schema.execute_sync(
            query, variable_values=variables, context_value={"project_root": tmp_path, "conn": conn},
        )
    assert result.errors is None
    payload = result.data["fileFindingDefect"]
    assert payload["success"] is True
    assert (tmp_path / payload["canonical_path"]).is_file()
    state = json.loads((paths.defects_dir / payload["slug"] / "state.json").read_text())
    assert state["intake"]["request_id"] == variables["input"]["requestId"]
    indexed = conn.execute("SELECT spec_type FROM spec_index WHERE path = ?", (payload["canonical_path"],)).fetchone()
    assert indexed["spec_type"] == "defect"
    report = schema.execute_sync(
        "query { defectReport(features: [\"payments\"]) }",
        context_value={"project_root": tmp_path, "conn": conn},
    )
    assert report.data["defectReport"]["rows"][0]["source_finding_id"] == finding["id"]
    canonical = tmp_path / payload["canonical_path"]
    canonical.write_text(canonical.read_text().replace("Retry charges twice", "Retry regression"))
    stale_export = schema.execute_sync(
        "query Export($revision: String!) { defectReportExport(displayedRevision: $revision, format: \"json\") }",
        variable_values={"revision": report.data["defectReport"]["revision"]},
        context_value={"project_root": tmp_path, "conn": conn},
    )
    assert stale_export.data["defectReportExport"]["code"] == "STALE_REPORT"
    conn.close()
