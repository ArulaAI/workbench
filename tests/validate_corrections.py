#!/usr/bin/env python3
"""Validate human corrections design against real SPEED and find-your-tribe data.

Runs the extraction-time signals (steps 11-14) and post-merge branch
detection against actual feature artifacts. No file modifications.

Usage:
    python3 tests/validate_corrections.py
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from collections import defaultdict

# ── Project paths ─────────────────────────────────────────────────────

SPEED_ROOT = Path(__file__).parent.parent
TRIBE_ROOT = Path.home() / "Documents" / "code" / "tmp" / "find-your-tribe"

PROJECTS = []
if (SPEED_ROOT / ".speed" / "features").is_dir():
    PROJECTS.append(("SPEED", SPEED_ROOT))
if (TRIBE_ROOT / ".speed" / "features").is_dir():
    PROJECTS.append(("find-your-tribe", TRIBE_ROOT))


# ── Git helper ────────────────────────────────────────────────────────

def _git(project_root: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(project_root)] + list(args),
            capture_output=True, text=True, timeout=10,
        )
        return out.stdout.strip() if out.returncode == 0 else None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


# ── Step 11: Retry guidance extraction ────────────────────────────────

def validate_retry_guidance(project_name: str, project_root: Path):
    print(f"\n{'='*60}")
    print(f"Step 11: Retry Guidance — {project_name}")
    print(f"{'='*60}")

    features_dir = project_root / ".speed" / "features"
    total_guidance = 0

    for feature_dir in sorted(features_dir.iterdir()):
        tasks_dir = feature_dir / "tasks"
        if not tasks_dir.is_dir():
            continue

        feature = feature_dir.name
        for task_file in sorted(tasks_dir.glob("*.json")):
            try:
                task = json.loads(task_file.read_text())
            except (json.JSONDecodeError, OSError):
                continue

            feedback = task.get("review_feedback", "") or ""
            if not feedback or not isinstance(feedback, str):
                continue

            # Parse "Human guidance:" markers
            matches = list(re.finditer(
                r"--- Attempt (\d+) ---\nFailed with: (.*?)\nHuman guidance: (.*?)(?=\n--- Attempt|\Z)",
                feedback, re.DOTALL,
            ))

            if matches:
                tid = task.get("id", "?")
                status = task.get("status", "?")
                print(f"\n  [{feature}] Task {tid} (status={status}, retries={task.get('retry_count', 0)})")
                for m in matches:
                    attempt = m.group(1)
                    error = m.group(2).strip()[:80]
                    guidance = m.group(3).strip()[:120]
                    print(f"    Attempt {attempt}: error={error}")
                    print(f"    Guidance: {guidance}...")
                    total_guidance += 1

    print(f"\n  Total retry guidance observations: {total_guidance}")
    return total_guidance


# ── Step 12: Skip flags (check if any skip logs exist) ───────────────

def validate_skip_flags(project_name: str, project_root: Path):
    print(f"\n{'='*60}")
    print(f"Step 12: Skip Flags — {project_name}")
    print(f"{'='*60}")

    features_dir = project_root / ".speed" / "features"
    total_skips = 0

    for feature_dir in sorted(features_dir.iterdir()):
        skip_file = feature_dir / "logs" / "skipped-gates.json"
        if skip_file.exists():
            lines = [l for l in skip_file.read_text().strip().split("\n") if l.strip()]
            print(f"  [{feature_dir.name}] {len(lines)} skip entries found")
            total_skips += len(lines)

    if total_skips == 0:
        print("  No skipped-gates.json files found (expected — logging not implemented yet)")
        # Check env vars that WOULD have been logged
        print("  Checking for evidence of skips in task artifacts...")
        for feature_dir in sorted(features_dir.iterdir()):
            logs_dir = feature_dir / "logs"
            if not logs_dir.is_dir():
                continue
            # No guardian logs = guardian was likely skipped
            guardian_logs = list(logs_dir.glob("guardian-*"))
            if not guardian_logs:
                print(f"    [{feature_dir.name}] No guardian logs — guardian may have been skipped")

    return total_skips


# ── Step 13: Forced approval detection ────────────────────────────────

def validate_forced_approvals(project_name: str, project_root: Path):
    print(f"\n{'='*60}")
    print(f"Step 13: Forced Approvals — {project_name}")
    print(f"{'='*60}")

    features_dir = project_root / ".speed" / "features"
    total_forced = 0

    for feature_dir in sorted(features_dir.iterdir()):
        tasks_dir = feature_dir / "tasks"
        logs_dir = feature_dir / "logs"
        if not tasks_dir.is_dir():
            continue

        feature = feature_dir.name
        for task_file in sorted(tasks_dir.glob("*.json")):
            try:
                task = json.loads(task_file.read_text())
            except (json.JSONDecodeError, OSError):
                continue

            tid = task.get("id", "?")
            status = task.get("status", "?")
            verdict = task.get("review_verdict")
            reviewed_at = task.get("reviewed_at")

            # Case 1: done + approve but no review log
            if status == "done" and verdict == "approve":
                review_log = logs_dir / f"review-{tid}.json"
                if not review_log.exists():
                    print(f"  [{feature}] Task {tid}: FORCED (approved, no review log)")
                    total_forced += 1
                    continue
                # Check if review log says request_changes but verdict is approve
                try:
                    review = json.loads(review_log.read_text())
                    if review.get("verdict") == "request_changes":
                        print(f"  [{feature}] Task {tid}: FORCED (reviewer rejected, verdict overridden to approve)")
                        total_forced += 1
                except (json.JSONDecodeError, OSError):
                    pass

            # Case 2: done but verdict is still request_changes (completed without proper review)
            if status == "done" and verdict == "request_changes":
                print(f"  [{feature}] Task {tid}: OVERRIDE (done despite request_changes verdict)")
                total_forced += 1

            # Case 3: done but never reviewed
            if status == "done" and verdict is None:
                print(f"  [{feature}] Task {tid}: SKIPPED REVIEW (done, no verdict)")
                total_forced += 1

    print(f"\n  Total forced/override approvals: {total_forced}")
    return total_forced


# ── Step 14: Defect rejections ────────────────────────────────────────

def validate_defect_rejections(project_name: str, project_root: Path):
    print(f"\n{'='*60}")
    print(f"Step 14: Defect Rejections — {project_name}")
    print(f"{'='*60}")

    defects_dir = project_root / ".speed" / "defects"
    total_rejected = 0

    if not defects_dir.is_dir():
        print("  No defects directory found")
        return 0

    for defect_dir in sorted(defects_dir.iterdir()):
        state_file = defect_dir / "state.json"
        if not state_file.exists():
            continue
        try:
            state = json.loads(state_file.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        status = state.get("status", "?")
        if status == "rejected":
            triage_file = defect_dir / "triage.json"
            has_triage = triage_file.exists()
            print(f"  [{defect_dir.name}] REJECTED (has_triage={has_triage})")
            total_rejected += 1

    if total_rejected == 0:
        print("  No rejected defects found")

    return total_rejected


# ── Post-merge: Branch detection ──────────────────────────────────────

def validate_branch_detection(project_name: str, project_root: Path):
    print(f"\n{'='*60}")
    print(f"Post-merge: Branch Detection — {project_name}")
    print(f"{'='*60}")

    features_dir = project_root / ".speed" / "features"
    main_branch = _git(project_root, "rev-parse", "--abbrev-ref", "HEAD") or "main"

    for feature_dir in sorted(features_dir.iterdir()):
        tasks_dir = feature_dir / "tasks"
        if not tasks_dir.is_dir():
            continue

        feature = feature_dir.name
        print(f"\n  [{feature}]")

        branches_found = 0
        branches_missing = 0
        diffs_found = 0

        for task_file in sorted(tasks_dir.glob("*.json")):
            try:
                task = json.loads(task_file.read_text())
            except (json.JSONDecodeError, OSError):
                continue

            tid = task.get("id", "?")
            branch = task.get("branch", "")
            if not branch:
                continue

            # Check if branch exists
            tip = _git(project_root, "rev-parse", "--verify", branch)
            if not tip:
                print(f"    Task {tid}: branch {branch} — MISSING")
                branches_missing += 1
                continue

            branches_found += 1

            # Get task files
            task_files = (
                task.get("files_to_modify", [])
                + task.get("files_to_create", [])
            )
            if not task_files:
                # Fall back to files_touched
                task_files = task.get("files_touched", [])
                if isinstance(task_files, str):
                    task_files = [f.strip() for f in task_files.split(",") if f.strip()]

            if not task_files:
                print(f"    Task {tid}: branch exists (tip={tip[:8]}) — no file list to diff")
                continue

            # Diff task branch tip against main HEAD for task files
            diff_args = ["diff", "--stat", tip, main_branch, "--"]
            diff_args.extend(task_files)
            diff_output = _git(project_root, *diff_args)

            if diff_output:
                lines = [l for l in diff_output.strip().split("\n") if l.strip()]
                print(f"    Task {tid}: branch exists (tip={tip[:8]}) — {len(lines)} files differ from {main_branch}")
                diffs_found += 1
            else:
                print(f"    Task {tid}: branch exists (tip={tip[:8]}) — no diff (zero-delta for this task)")

        print(f"    Summary: {branches_found} branches found, {branches_missing} missing, {diffs_found} with diffs")


# ── Main ──────────────────────────────────────────────────────────────

def main():
    print("Human Corrections Validation")
    print("Validating tech spec design against real project data\n")

    if not PROJECTS:
        print("ERROR: No SPEED projects found")
        sys.exit(1)

    print(f"Projects: {', '.join(name for name, _ in PROJECTS)}")

    results = defaultdict(dict)

    for name, root in PROJECTS:
        results[name]["retry_guidance"] = validate_retry_guidance(name, root)
        results[name]["skip_flags"] = validate_skip_flags(name, root)
        results[name]["forced_approvals"] = validate_forced_approvals(name, root)
        results[name]["defect_rejections"] = validate_defect_rejections(name, root)
        validate_branch_detection(name, root)

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")

    print(f"\n{'Project':<20} {'Retry':<10} {'Skips':<10} {'Forced':<10} {'Defects':<10}")
    print("-" * 60)
    for name in results:
        r = results[name]
        print(f"{name:<20} {r['retry_guidance']:<10} {r['skip_flags']:<10} {r['forced_approvals']:<10} {r['defect_rejections']:<10}")

    total_signals = sum(
        sum(r.values()) for r in results.values()
    )
    print(f"\nTotal human signals detected: {total_signals}")

    if total_signals > 0:
        print("\nThe tech spec's extraction-time path produces real observations from existing data.")
    else:
        print("\nNo signals found — check project paths and feature data.")


if __name__ == "__main__":
    main()
