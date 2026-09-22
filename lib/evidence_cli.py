"""Publish immutable Diagnose and Review attempts from shell commands."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from dashboard.backend.paths import get_paths
from lib.defect_findings import FindingError, publish_attempt
from lib.review_evidence import parse_clean_review_payload, parse_report_findings_events


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--feature", required=True)
    parser.add_argument("--producer", required=True)
    parser.add_argument("--task")
    parser.add_argument("--payload", required=True)
    parser.add_argument("--compatibility")
    parser.add_argument("--content-hash")
    parser.add_argument("--commit")
    parser.add_argument("--diff-hash")
    parser.add_argument("--provider-events")
    parser.add_argument("--normalized-output")
    args = parser.parse_args(argv)
    try:
        paths = get_paths(Path(args.project_root))
        compatibility = Path(args.compatibility) if args.compatibility else None
        if compatibility and compatibility.is_file():
            legacy_bytes = compatibility.read_bytes()
            legacy_text = legacy_bytes.decode("utf-8")
            if args.producer == "diagnose":
                import yaml
                legacy_payload = yaml.safe_load(legacy_text)
            elif args.producer == "clean_review":
                legacy_payload = parse_clean_review_payload(legacy_text, legacy=True)
            else:
                legacy_payload = json.loads(legacy_text)
            if isinstance(legacy_payload, dict):
                legacy_task = str(legacy_payload.get("task") or args.task or "") or None
                legacy_base = Path(paths.feature_shared(args.feature)) / "evidence" / args.producer / (legacy_task or "_feature")
                if not any(legacy_base.glob("*.json")):
                    publish_attempt(
                        paths, args.feature, args.producer, legacy_task, legacy_payload,
                        hashlib.sha256(legacy_bytes).hexdigest(), None, None,
                    )

        raw = Path(args.payload).read_text(encoding="utf-8")
        tool_report = False
        source_event_log = None
        if args.producer == "clean_review":
            payload = None
            if args.provider_events:
                event_path = Path(args.provider_events).resolve()
                source_event_log = str(event_path.relative_to(Path(args.project_root).resolve()))
                payload = parse_report_findings_events(event_path.read_text(encoding="utf-8"))
                tool_report = payload is not None
            if payload is None:
                payload = parse_clean_review_payload(raw)
        else:
            payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("evidence payload must be an object")
        if args.normalized_output and args.producer == "clean_review":
            Path(args.normalized_output).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        path = publish_attempt(
            paths, args.feature, args.producer, args.task,
            payload, args.content_hash, args.commit, args.diff_hash,
            source_event_log,
        )
        if tool_report:
            print(f"Normalized {len(payload['issues'])} confirmed ReportFindings into separate Define findings", file=sys.stderr)
        print(path)
        return 0
    except (FindingError, OSError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
