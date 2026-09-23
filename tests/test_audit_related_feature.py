"""Tests the defect audit's related-spec resolver without the CLI preflight."""

import subprocess
from pathlib import Path


def test_audit_resolves_markdown_related_feature(tmp_path):
    product = tmp_path / "specs/product/payments.md"
    product.parent.mkdir(parents=True)
    product.write_text("# Payments\n")
    defect_dir = tmp_path / "specs/defects"
    defect_dir.mkdir(parents=True)
    audit_script = Path(__file__).resolve().parents[1] / "lib/cmd/audit.sh"
    command = 'source "$1"; _audit_related_feature_path "$2" "$3" "$4"'
    result = subprocess.run(
        ["bash", "-c", command, "audit-resolver", str(audit_script),
         "[payments](../product/payments.md)", str(defect_dir), str(tmp_path)],
        capture_output=True, text=True, check=True,
    )
    assert Path(result.stdout.strip()).resolve() == product


def test_audit_does_not_resolve_missing_related_feature(tmp_path):
    defect_dir = tmp_path / "specs/defects"
    defect_dir.mkdir(parents=True)
    audit_script = Path(__file__).resolve().parents[1] / "lib/cmd/audit.sh"
    result = subprocess.run(
        ["bash", "-c", 'source "$1"; _audit_related_feature_path "$2" "$3" "$4"',
         "audit-resolver", str(audit_script), "[missing](../product/missing.md)",
         str(defect_dir), str(tmp_path)],
        capture_output=True, text=True, check=True,
    )
    assert result.stdout == ""


def test_audit_rejects_escape_and_symlink_outside_project(tmp_path):
    project = tmp_path / "project"
    defect_dir = project / "specs/defects"
    defect_dir.mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text("private outside content\n")
    (defect_dir / "linked.md").symlink_to(outside)
    audit_script = Path(__file__).resolve().parents[1] / "lib/cmd/audit.sh"
    for link in ("[outside](../../../outside.md)", "[outside](linked.md)"):
        result = subprocess.run(
            ["bash", "-c", 'source "$1"; _audit_related_feature_path "$2" "$3" "$4"',
             "audit-resolver", str(audit_script), link, str(defect_dir), str(project)],
            capture_output=True, text=True, check=True,
        )
        assert result.stdout == ""
