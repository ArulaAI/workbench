"""Lock-safe queue adapter for applying finding rework through tasks.sh."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dashboard.backend.paths import get_paths
from lib.defect_findings import _atomic_json, _load_history, intake_lock


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("next", "ack"))
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--feature", required=True)
    parser.add_argument("--request-id")
    parser.add_argument("--status", choices=("applied", "blocked"))
    parser.add_argument("--error")
    args = parser.parse_args()
    paths = get_paths(Path(args.project_root))
    feature_dir = Path(paths.feature_shared(args.feature))
    with intake_lock(Path(paths.defects_dir)):
        history, warnings = _load_history(feature_dir)
        if warnings:
            print(json.dumps({"error": warnings[0]}))
            return 1
        if args.command == "next":
            decisions = {item["id"]: item for item in history["decisions"]}
            for request_id, item in history["rework"].items():
                if item.get("status") != "queued":
                    continue
                decision = decisions.get(request_id) or {}
                print(json.dumps({
                    "request_id": request_id, "task_id": item.get("task_id"),
                    "guidance": decision.get("rationale") or "Address the linked finding",
                }))
                return 0
            return 3
        if not args.request_id or not args.status:
            return 2
        item = history["rework"].get(args.request_id)
        if not item:
            return 2
        if item.get("status") == "queued":
            item["status"] = args.status
            item["error"] = args.error or None
            history["revision"] = int(history["revision"]) + 1
            _atomic_json(feature_dir / "findings.json", history)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
