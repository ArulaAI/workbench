#!/usr/bin/env python3
"""Reconcile, summarize, and audit a Workbench Define feature package."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


FEATURE_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,48}[a-z0-9])?$")
ARTIFACTS = ("prd", "design", "rfc")
LABELS = {"prd": "PRD", "design": "Design", "rfc": "Technical RFC"}
CHECK_SET_VERSION = "define-core-v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _features_root(root: Path) -> Path:
    shared = root / ".speed" / "shared"
    return shared / "features" if shared.is_dir() else root / ".speed" / "features"


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _actor(root: Path) -> tuple[str, str]:
    def git_value(key: str) -> str:
        result = subprocess.run(
            ["git", "config", key], cwd=root, capture_output=True, text=True
        )
        return result.stdout.strip() if result.returncode == 0 else ""

    return git_value("user.name") or "Workbench User", git_value("user.email") or "workbench@localhost"


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(raw)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _artifact(root: Path, feature_dir: Path, feature: str, kind: str) -> dict[str, Any]:
    state_path = feature_dir / f"authoring-{kind}.json"
    state = _read_json(state_path)
    spec_path = root / "specs" / feature / f"{kind}.md"
    actual_hash = _sha256(spec_path)
    artifact = (state or {}).get("artifact") or {}
    claim = _read_json(feature_dir / f"claim-{kind}.json") or {}
    commit = _read_json(feature_dir / f"commit-{kind}.json") or {}
    ratification = _read_json(feature_dir / f"ratification-{kind}.json") or {}
    expected_hash = artifact.get("sha256")
    open_comments = [
        item for item in (state or {}).get("review_comment_threads", [])
        if isinstance(item, dict) and item.get("status") == "open"
    ]
    return {
        "artifact_type": kind,
        "label": LABELS[kind],
        "path": f"specs/{feature}/{kind}.md",
        "checkpoint_path": state_path.relative_to(root).as_posix(),
        "exists": spec_path.is_file(),
        "status": (state or {}).get("status", "missing"),
        "revision": (state or {}).get("revision"),
        "published_revision": (state or {}).get("published_revision"),
        "sha256": actual_hash,
        "checkpoint_sha256": expected_hash,
        "hash_current": bool(actual_hash and expected_hash == actual_hash),
        "self_review": ((state or {}).get("self_review") or {}).get("status"),
        "open_comment_count": len(open_comments),
        "upstream": (state or {}).get("upstream") or {},
        "owner": claim.get("claimant") or commit.get("claimant"),
        "owner_email": claim.get("claimant_email") or commit.get("claimant_email"),
        "commit": {
            "present": bool(commit),
            "revision_id": commit.get("revision_id"),
            "content_hash_ref": commit.get("validation_state_ref"),
            "current": bool(
                commit
                and actual_hash
                and str(actual_hash).startswith(str(commit.get("validation_state_ref") or "!"))
            ),
        },
        "ratification": {
            "present": bool(ratification),
            "ratified": ratification.get("ratified") is True,
            "revision_id": ratification.get("revision_id"),
        },
    }


def _next_action(artifacts: dict[str, dict[str, Any]], audit: dict | None) -> dict[str, str]:
    for kind in ARTIFACTS:
        item = artifacts[kind]
        if item["status"] != "published" or not item["hash_current"]:
            return {
                "stage": kind,
                "reason": f"{item['label']} is not a current published version.",
                "command": f"workbench draft {kind} <feature>",
            }
    if not audit or audit.get("status") != "passed":
        return {
            "stage": "audit",
            "reason": "The published core package needs a current connected audit.",
            "command": "workbench audit <feature>",
        }
    for kind in ARTIFACTS:
        if not artifacts[kind]["ratification"]["ratified"]:
            return {
                "stage": "ratification",
                "reason": f"{artifacts[kind]['label']} is not ratified for its committed revision.",
                "command": f"Open Review & commit for {artifacts[kind]['label']}",
            }
    return {
        "stage": "decisions-evaluation",
        "reason": "Core artifacts are ready; ADR and evaluation gates are not implemented yet.",
        "command": "Complete ADR and evaluation support before Plan",
    }


def _snapshot(root: Path, feature: str) -> dict[str, Any]:
    feature_dir = _features_root(root) / feature
    artifacts = {
        kind: _artifact(root, feature_dir, feature, kind) for kind in ARTIFACTS
    }
    latest = _read_json(feature_dir / "define-audit-latest.json")
    if latest:
        current_inputs = {
            kind: item["sha256"] for kind, item in artifacts.items() if item["sha256"]
        }
        latest["stale"] = latest.get("inputs", {}).get("artifacts") != current_inputs
        if latest["stale"]:
            latest["status"] = "stale"
    package = {
        "schema_version": 1,
        "feature_name": feature,
        "reconciled_at": _now(),
        "context_package": {
            "path": (feature_dir / "context-package.json").relative_to(root).as_posix(),
            "sha256": _sha256(feature_dir / "context-package.json"),
        },
        "discover_handoff": None,
        "artifacts": artifacts,
        "connected_audit": latest,
        "unsupported_gates": ["adr", "evaluation"],
    }
    next_action = _next_action(artifacts, latest)
    package["next_action"] = {
        **next_action,
        "command": next_action["command"].replace("<feature>", feature),
    }
    package["plan_readiness"] = {
        "status": "blocked",
        "reasons": [
            package["next_action"]["reason"],
            "ADR and evaluation-specification gates are not implemented.",
        ],
    }
    return package


def _finding(
    check_id: str,
    severity: str,
    artifact: str,
    evidence: str,
    action: str,
    owner: str | None,
) -> dict[str, Any]:
    identity = f"{check_id}\0{artifact}\0{evidence}"
    return {
        "finding_id": hashlib.sha256(identity.encode()).hexdigest()[:16],
        "check_id": check_id,
        "severity": severity,
        "artifact": artifact,
        "evidence": evidence,
        "required_action": action,
        "owner": owner,
        "status": "open",
    }


def _audit_findings(root: Path, package: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    artifacts = package["artifacts"]
    for kind in ARTIFACTS:
        item = artifacts[kind]
        owner = item["owner"]
        if item["status"] != "published":
            findings.append(_finding(
                "PKG-ARTIFACT-PUBLISHED", "fail", kind,
                f"{item['label']} status is {item['status']}.",
                f"Finish, self-review, and publish {item['label']}.", owner,
            ))
            continue
        if not item["hash_current"]:
            findings.append(_finding(
                "PKG-ARTIFACT-HASH", "fail", kind,
                "Artifact bytes do not match the published checkpoint hash.",
                "Reconcile the edit through guided authoring and publish a new version.", owner,
            ))
        if item["self_review"] != "passed":
            findings.append(_finding(
                "PKG-SELF-REVIEW", "fail", kind,
                f"Self-review status is {item['self_review'] or 'missing'}.",
                "Resolve the blocking self-review findings.", owner,
            ))
        if item["open_comment_count"]:
            findings.append(_finding(
                "PKG-OPEN-COMMENTS", "fail", kind,
                f"{item['open_comment_count']} review comment(s) remain open.",
                "Apply or resolve every open review comment.", owner,
            ))

    prd = artifacts["prd"]
    if prd["sha256"]:
        text = (root / prd["path"]).read_text(encoding="utf-8")
        requirement_ids = [
            match.group(1)
            for line in text.splitlines()
            if (match := re.match(r"^\|\s*(REQ-\d+)\s*\|", line))
        ]
        if not requirement_ids:
            findings.append(_finding(
                "PRD-STABLE-REQUIREMENTS", "fail", "prd",
                "No stable REQ-n identifiers were found.",
                "Give every product requirement a stable identifier.", prd["owner"],
            ))
        elif len(requirement_ids) != len(set(requirement_ids)):
            findings.append(_finding(
                "PRD-STABLE-REQUIREMENTS", "fail", "prd",
                "Product requirement identifiers are not unique.",
                "Repair duplicate product requirement identifiers.", prd["owner"],
            ))

    for kind, upstream_types in (("design", ("prd",)), ("rfc", ("prd", "design"))):
        item = artifacts[kind]
        for upstream_type in upstream_types:
            pinned = item["upstream"].get(upstream_type) or {}
            upstream = artifacts[upstream_type]
            if item["status"] == "published" and pinned.get("sha256") != upstream["sha256"]:
                findings.append(_finding(
                    "PKG-UPSTREAM-PIN", "fail", kind,
                    f"Pinned {upstream_type.upper()} hash does not match the current published artifact.",
                    f"Revalidate and republish {item['label']} against the current upstream.",
                    item["owner"],
                ))

    for kind in ARTIFACTS:
        item = artifacts[kind]
        if item["status"] == "published" and not item["ratification"]["ratified"]:
            findings.append(_finding(
                "PKG-RATIFICATION-PENDING", "warn", kind,
                f"{item['label']} is not ratified for its committed ceremony revision.",
                "Complete Review & commit and obtain the required ratification.", item["owner"],
            ))
    return findings


def _write_index(root: Path, package: dict[str, Any]) -> None:
    feature = package["feature_name"]
    lines = [
        f"# Define Package: {feature}", "",
        f"**Plan readiness:** {package['plan_readiness']['status'].title()}  ",
        f"**Discover handoff:** Not connected  ",
        f"**Connected audit:** {((package.get('connected_audit') or {}).get('status') or 'Not run').title()}",
        "", "| Artifact | Status | Version | SHA-256 | Owner | Approval |", "|---|---|---|---|---|---|",
    ]
    for kind in ARTIFACTS:
        item = package["artifacts"][kind]
        approval = "Ratified" if item["ratification"]["ratified"] else "Pending"
        digest = (item["sha256"] or "—")[:12]
        lines.append(
            f"| [{item['label']}]({kind}.md) | {str(item['status']).replace('_', ' ').title()} | "
            f"{item['published_revision'] if item['published_revision'] is not None else '—'} | "
            f"`{digest}` | {item['owner'] or 'Unassigned'} | {approval} |"
        )
    lines.extend([
        "", "## Next action", "",
        package["next_action"]["reason"], "",
        f"`{package['next_action']['command']}`", "",
        "> ADR and evaluation-specification stages remain explicit unsupported gates; this package cannot yet be reported Plan-ready.", "",
    ])
    path = root / "specs" / feature / "index.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def reconcile(root: Path, feature: str) -> dict[str, Any]:
    package = _snapshot(root, feature)
    feature_dir = _features_root(root) / feature
    _atomic_json(feature_dir / "define-package.json", package)
    _write_index(root, package)
    return package


def audit(root: Path, feature: str) -> dict[str, Any]:
    package = _snapshot(root, feature)
    findings = _audit_findings(root, package)
    input_hashes = {
        kind: item["sha256"]
        for kind, item in package["artifacts"].items()
        if item["sha256"]
    }
    context_hash = package["context_package"]["sha256"]
    frozen = json.dumps(
        {"artifacts": input_hashes, "context": context_hash}, sort_keys=True
    )
    input_id = hashlib.sha256(frozen.encode()).hexdigest()
    actor, actor_email = _actor(root)
    report = {
        "schema_version": 1,
        "report_id": f"define-{input_id[:12]}",
        "check_set_version": CHECK_SET_VERSION,
        "feature_name": feature,
        "created_at": _now(),
        "actor": actor,
        "actor_email": actor_email,
        "inputs": {"artifacts": input_hashes, "context_package": context_hash},
        "status": "failed" if any(item["severity"] == "fail" for item in findings) else "passed",
        "findings": findings,
        "plan_readiness": {
            "status": "blocked",
            "reasons": [
                "Resolve every fail and warning finding." if findings else "Core audit passed.",
                "ADR and evaluation-specification gates are not implemented.",
                "Final package ratification is not implemented.",
            ],
        },
    }
    feature_dir = _features_root(root) / feature
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    report_path = feature_dir / "audits" / f"define-audit-{stamp}-{input_id[:8]}.json"
    if report_path.exists():
        raise RuntimeError(f"Refusing to overwrite immutable audit report {report_path}.")
    _atomic_json(report_path, report)
    latest = {
        "report_id": report["report_id"],
        "report_path": report_path.relative_to(root).as_posix(),
        "status": report["status"],
        "created_at": report["created_at"],
        "inputs": {"artifacts": input_hashes},
        "finding_count": len(findings),
        "stale": False,
    }
    _atomic_json(feature_dir / "define-audit-latest.json", latest)
    package = _snapshot(root, feature)
    _atomic_json(feature_dir / "define-package.json", package)
    _write_index(root, package)
    return {**report, "report_path": latest["report_path"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("feature")
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if not FEATURE_RE.fullmatch(args.feature) or "--" in args.feature:
        parser.error("feature must be a lowercase, hyphenated canonical name")
    root = Path(args.project_root).resolve()
    result = audit(root, args.feature) if args.audit else reconcile(root, args.feature)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        if args.audit:
            print(f"Connected audit: {result['status']} ({result['report_path']})")
            for item in result["findings"]:
                print(f"- {item['severity'].upper()} {item['check_id']}: {item['evidence']}")
        else:
            next_action = result["next_action"]
            print(f"Define: {args.feature}")
            for kind in ARTIFACTS:
                item = result["artifacts"][kind]
                print(f"- {item['label']}: {item['status']}")
            print(f"Next: {next_action['reason']}")
            print(next_action["command"])
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}), file=sys.stderr)
        raise SystemExit(1)
