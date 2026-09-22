import json
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from dashboard.backend.paths import SpeedPaths
from lib.defect_findings import FindingError, publish_attempt, read_findings
from lib.defect_intake import _slugify, append_defect_evidence, file_defect, preview_defect


class DefectIntakeTests(unittest.TestCase):
    def test_slug_truncates_at_word_boundary(self):
        title = (
            "The new reissueRefund helper retries a non-idempotent refund() call and is never "
            "exercised by any test added in this diff, so its double-refund risk is completely uncovered"
        )
        self.assertEqual(
            _slugify(title),
            "the-new-reissuerefund-helper-retries-a-non-idempotent-refund-call-and-is-never",
        )

    def test_slug_uses_stable_fallback_when_no_word_boundary_exists(self):
        title = "a" * 100
        slug = _slugify(title)
        self.assertRegex(slug, r"^defect-[a-f0-9]{12}$")
        self.assertEqual(slug, _slugify(title))

    def _fixture(self, multiplayer=False):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        if multiplayer:
            (root / ".speed/shared").mkdir(parents=True)
        (root / "specs/product").mkdir(parents=True)
        (root / "specs/product/payments.md").write_text("# Payments\n")
        paths = SpeedPaths(root)
        publish_attempt(paths, "payments", "structured_review", "4", {
            "issues": [{
                "message": "Refund retry charges twice", "observed": "A retry creates two charges.",
                "expected": "A retry creates no new charge.", "reproduction": "Run `pytest tests/test_retry.py`.",
                "file": "src/retry.py", "severity": "major", "issue_key": "retry-double-charge",
            }],
        }, commit="abc123", diff_hash="diff123")
        return temp, root, paths

    def test_preview_is_read_only_and_filing_is_idempotent(self):
        temp, root, paths = self._fixture()
        self.addCleanup(temp.cleanup)
        view_before = sorted(str(path.relative_to(root)) for path in root.rglob("*"))
        finding_id = __import__("lib.defect_findings", fromlist=["read_findings"]).read_findings(paths, "payments")["findings"][0]["id"]
        preview = preview_defect(paths, "payments", finding_id)
        self.assertEqual(view_before, sorted(str(path.relative_to(root)) for path in root.rglob("*")))
        self.assertEqual(preview["missing_fields"], ["severity"])
        draft = dict(preview["draft"])
        draft.update({"title": "Refund retry charges twice", "severity": "P1", "severity_confirmed": True})
        request_id = str(uuid.uuid4())
        args = (paths, "payments", finding_id, preview["provenance"]["evidence_ids"],
                preview["finding_revision"], preview["decision_revision"], request_id,
                draft, "Track separately", ("Alex", "alex@example.test"))
        result = file_defect(*args)
        self.assertFalse(result["replayed"])
        self.assertTrue((root / result["canonical_path"]).is_file())
        state = json.loads((paths.defects_dir / result["slug"] / "state.json").read_text())
        self.assertEqual(state["status"], "filed")
        self.assertIsNone(state["severity"])
        self.assertEqual(state["reported_severity"], "P1")
        self.assertEqual(state["source_feature"], "payments")
        manifest = json.loads((paths.defects_dir / ".intake" / request_id / "manifest.json").read_text())
        self.assertEqual(manifest["phase"], "committed")
        replay = file_defect(*args)
        self.assertTrue(replay["replayed"])

    def test_incomplete_draft_writes_nothing_in_multiplayer(self):
        temp, root, paths = self._fixture(multiplayer=True)
        self.addCleanup(temp.cleanup)
        from lib.defect_findings import read_findings
        finding = read_findings(paths, "payments")["findings"][0]
        preview = preview_defect(paths, "payments", finding["id"])
        with self.assertRaises(FindingError) as raised:
            file_defect(paths, "payments", finding["id"], preview["provenance"]["evidence_ids"],
                        preview["finding_revision"], preview["decision_revision"], str(uuid.uuid4()),
                        preview["draft"], "Track", ("Alex", "alex@example.test"))
        self.assertEqual(raised.exception.code, "INVALID_INPUT")
        self.assertFalse((root / "specs/defects").exists())
        self.assertTrue(str(paths.defects_dir).endswith(".speed/shared/defects"))

    def test_retry_rolls_prepared_transaction_forward(self):
        temp, root, paths = self._fixture()
        self.addCleanup(temp.cleanup)
        from lib.defect_findings import read_findings
        finding = read_findings(paths, "payments")["findings"][0]
        preview = preview_defect(paths, "payments", finding["id"])
        draft = dict(preview["draft"])
        draft.update({"title": "Recover retry defect", "severity": "P2", "severity_confirmed": True})
        request_id = str(uuid.uuid4())
        args = (paths, "payments", finding["id"], preview["provenance"]["evidence_ids"],
                preview["finding_revision"], preview["decision_revision"], request_id,
                draft, "Exercise recovery", ("Alex", "alex@example.test"))
        with patch("lib.defect_intake._complete_filing", side_effect=FindingError("WRITE_FAILED", "injected")):
            with self.assertRaises(FindingError):
                file_defect(*args)
        receipt = paths.defects_dir / ".intake" / request_id
        self.assertEqual(json.loads((receipt / "manifest.json").read_text())["phase"], "prepared")
        self.assertFalse((root / "specs/defects/recover-retry-defect.md").exists())
        result = file_defect(*args)
        self.assertTrue(result["replayed"])
        self.assertTrue((root / result["canonical_path"]).exists())

    def test_staging_failure_leaves_no_visible_receipt_or_defect(self):
        temp, root, paths = self._fixture()
        self.addCleanup(temp.cleanup)
        finding = read_findings(paths, "payments")["findings"][0]
        preview = preview_defect(paths, "payments", finding["id"])
        draft = dict(preview["draft"])
        draft.update({"title": "Staging failure", "severity": "P2", "severity_confirmed": True})
        request_id = str(uuid.uuid4())
        args = (
            paths, "payments", finding["id"], preview["provenance"]["evidence_ids"],
            preview["finding_revision"], preview["decision_revision"], request_id,
            draft, "Exercise staging", ("Alex", "alex@example.test"),
        )
        with patch("lib.defect_intake._write_exclusive", side_effect=OSError("injected")):
            with self.assertRaises(OSError):
                file_defect(*args)
        self.assertFalse((paths.defects_dir / ".intake" / request_id).exists())
        self.assertFalse((root / "specs/defects/staging-failure.md").exists())
        result = file_defect(*args)
        self.assertTrue((root / result["canonical_path"]).exists())

    def test_prepared_receipt_suppresses_filed_decision_until_retry_commits(self):
        temp, _root, paths = self._fixture()
        self.addCleanup(temp.cleanup)
        finding = read_findings(paths, "payments")["findings"][0]
        preview = preview_defect(paths, "payments", finding["id"])
        draft = dict(preview["draft"])
        draft.update({"title": "Commit point failure", "severity": "P2", "severity_confirmed": True})
        request_id = str(uuid.uuid4())
        args = (
            paths, "payments", finding["id"], preview["provenance"]["evidence_ids"],
            preview["finding_revision"], preview["decision_revision"], request_id,
            draft, "Exercise the commit point", ("Alex", "alex@example.test"),
        )
        from lib.defect_intake import _atomic_json as real_atomic_json

        def fail_manifest_commit(path, value):
            if path.name == "manifest.json" and value.get("phase") == "committed":
                raise OSError("injected")
            return real_atomic_json(path, value)

        with patch("lib.defect_intake._atomic_json", side_effect=fail_manifest_commit):
            with self.assertRaises(FindingError):
                file_defect(*args)
        incomplete = read_findings(paths, "payments")["findings"][0]
        self.assertEqual(incomplete["resolution"], "unresolved")
        self.assertIsNone(incomplete["linked_defect_slug"])
        result = file_defect(*args)
        self.assertTrue(result["replayed"])
        committed = read_findings(paths, "payments")["findings"][0]
        self.assertEqual(committed["resolution"], "filed")

    def test_new_evidence_can_be_appended_to_existing_defect(self):
        temp, root, paths = self._fixture()
        self.addCleanup(temp.cleanup)
        finding = read_findings(paths, "payments")["findings"][0]
        preview = preview_defect(paths, "payments", finding["id"])
        draft = dict(preview["draft"])
        draft.update({"title": "Refund retry charges twice", "severity": "P1", "severity_confirmed": True})
        filed = file_defect(
            paths, "payments", finding["id"], preview["provenance"]["evidence_ids"],
            preview["finding_revision"], preview["decision_revision"], str(uuid.uuid4()),
            draft, "Track separately", ("Alex", "alex@example.test"),
        )
        publish_attempt(paths, "payments", "structured_review", "4", {
            "issues": [{
                "message": "Refund retry still charges twice", "observed": "A later retry creates two charges.",
                "expected": "A retry creates no new charge.", "reproduction": "Run `pytest tests/test_retry.py`.",
                "file": "src/retry.py", "severity": "major", "issue_key": "retry-double-charge",
            }],
        })
        current = read_findings(paths, "payments")
        stale = next(item for item in current["findings"] if item["id"] == finding["id"])
        self.assertTrue(stale["stale"])
        self.assertEqual(stale["linked_defect_slug"], filed["slug"])
        self.assertNotIn("create_defect", stale["allowed_actions"])
        result = append_defect_evidence(
            paths, "payments", stale["id"], filed["slug"], stale["revision"],
            current["decision_revision"], str(uuid.uuid4()), "Attach the later run",
            ("Alex", "alex@example.test"),
        )
        self.assertTrue((root / result["path"]).is_file())
        updated = next(item for item in read_findings(paths, "payments")["findings"] if item["id"] == finding["id"])
        self.assertFalse(updated["stale"])
        self.assertEqual(updated["resolution"], "filed")

    def test_resolved_defect_regression_files_new_linked_defect(self):
        temp, _root, paths = self._fixture()
        self.addCleanup(temp.cleanup)
        finding = read_findings(paths, "payments")["findings"][0]
        preview = preview_defect(paths, "payments", finding["id"])
        draft = dict(preview["draft"])
        draft.update({"title": "Refund retry charges twice", "severity": "P1", "severity_confirmed": True})
        first = file_defect(
            paths, "payments", finding["id"], preview["provenance"]["evidence_ids"],
            preview["finding_revision"], preview["decision_revision"], str(uuid.uuid4()),
            draft, "Track separately", ("Alex", "alex@example.test"),
        )
        state_path = paths.defects_dir / first["slug"] / "state.json"
        state = json.loads(state_path.read_text())
        state["status"] = "resolved"
        state_path.write_text(json.dumps(state))
        current = preview_defect(paths, "payments", finding["id"])
        regression = dict(current["draft"])
        regression.update({
            "title": "Refund retry charges twice regression",
            "severity": "P1", "severity_confirmed": True,
        })
        second = file_defect(
            paths, "payments", finding["id"], current["provenance"]["evidence_ids"],
            current["finding_revision"], current["decision_revision"], str(uuid.uuid4()),
            regression, "Regression after resolution", ("Alex", "alex@example.test"),
            duplicate_reason="New regression after the prior fix",
        )
        self.assertNotEqual(second["slug"], first["slug"])
        second_state = json.loads((paths.defects_dir / second["slug"] / "state.json").read_text())
        self.assertEqual(second_state["regression_of"], first["slug"])

    def test_filing_rejects_task_branch_that_moved_after_review(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        (root / "specs/product").mkdir(parents=True)
        spec = root / "specs/product/payments.md"
        spec.write_text("# Payments\n")
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.test"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
        subprocess.run(["git", "-C", str(root), "add", "specs/product/payments.md"], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "initial"], check=True)
        inspected = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
        branch = subprocess.check_output(["git", "-C", str(root), "branch", "--show-current"], text=True).strip()
        paths = SpeedPaths(root)
        publish_attempt(paths, "payments", "structured_review", "4", {
            "issues": [{
                "message": "Retry fails", "observed": "It fails", "expected": "It works",
                "reproduction": "Run retry test", "severity": "major",
            }],
        }, commit=inspected)
        task_dir = paths.feature_shared("payments") / "tasks"
        task_dir.mkdir(parents=True)
        (task_dir / "4.json").write_text(json.dumps({"id": "4", "branch": branch}))
        spec.write_text("# Payments\n\nChanged after review.\n")
        subprocess.run(["git", "-C", str(root), "add", "specs/product/payments.md"], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "move branch"], check=True)
        finding = read_findings(paths, "payments")["findings"][0]
        preview = preview_defect(paths, "payments", finding["id"])
        draft = dict(preview["draft"])
        draft.update({"title": "Retry fails", "severity": "P1", "severity_confirmed": True})
        with self.assertRaises(FindingError) as raised:
            file_defect(
                paths, "payments", finding["id"], preview["provenance"]["evidence_ids"],
                preview["finding_revision"], preview["decision_revision"], str(uuid.uuid4()),
                draft, "Track it", ("Alex", "alex@example.test"),
            )
        self.assertEqual(raised.exception.code, "STALE_EVIDENCE")
        self.assertFalse((root / "specs/defects/retry-fails.md").exists())


if __name__ == "__main__":
    unittest.main()
