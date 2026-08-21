#!/usr/bin/env python3
"""Validate prototype classifier against real post-merge diff hunks.

Design Decision DD1 Evidence:
    This script validated TF-IDF prototype classification against 20 real
    diff hunks across 4 SPEED tasks. Results: change type 100%, category 20%,
    agent attribution 90%. The 20% category accuracy drove the decision to
    drop per-hunk LLM/prototype category classification from the post-merge
    path and defer category assignment to synthesis.

    Recorded in:
    - PRD: specs/product/speed-human-corrections.md (DD1 table)
    - Tech spec: specs/tech/speed-human-corrections.md (Step 6, DD1)

Parses real diffs between task branches and HEAD, classifies each hunk
using the existing TF-IDF prototype classifier (no LLM), and compares
against human-labeled ground truth.

Usage:
    python3 tests/validate_classifier_postmerge.py
"""

import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Add project root and lib to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from lib.learn.classify import classify, REVIEW_PROTOTYPES


# ── Hunk parsing ──────────────────────────────────────────────────────

@dataclass
class DiffHunk:
    file: str
    header: str
    removed: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    context: list[str] = field(default_factory=list)

    @property
    def change_type(self) -> str:
        """Deterministic change type from diff structure."""
        has_removed = any(l.strip() for l in self.removed)
        has_added = any(l.strip() for l in self.added)

        if has_removed and has_added:
            # Check if purely whitespace/cosmetic
            removed_stripped = [l.strip() for l in self.removed if l.strip()]
            added_stripped = [l.strip() for l in self.added if l.strip()]
            if removed_stripped == added_stripped:
                return "cosmetic"
            return "transformative"
        elif has_added and not has_removed:
            return "additive"
        elif has_removed and not has_added:
            return "subtractive"
        return "unknown"

    @property
    def description(self) -> str:
        """Human-readable description for classification input."""
        parts = []
        if self.removed:
            parts.append("Removed: " + " ".join(l.strip() for l in self.removed if l.strip()))
        if self.added:
            parts.append("Added: " + " ".join(l.strip() for l in self.added if l.strip()))
        if self.context:
            parts.append("Context: " + " ".join(l.strip() for l in self.context[:3] if l.strip()))
        return " | ".join(parts)


def parse_diff_hunks(diff_text: str) -> list[DiffHunk]:
    """Parse unified diff into individual hunks."""
    hunks = []
    current_file = None
    current_hunk = None

    for line in diff_text.split("\n"):
        if line.startswith("diff --git"):
            # Extract filename: diff --git a/path b/path
            parts = line.split()
            if len(parts) >= 4:
                current_file = parts[2].lstrip("a/")
        elif line.startswith("@@"):
            if current_hunk and (current_hunk.removed or current_hunk.added):
                hunks.append(current_hunk)
            current_hunk = DiffHunk(
                file=current_file or "unknown",
                header=line,
            )
        elif current_hunk is not None:
            if line.startswith("-") and not line.startswith("---"):
                current_hunk.removed.append(line[1:])
            elif line.startswith("+") and not line.startswith("+++"):
                current_hunk.added.append(line[1:])
            elif line.startswith(" "):
                current_hunk.context.append(line[1:])

    if current_hunk and (current_hunk.removed or current_hunk.added):
        hunks.append(current_hunk)

    return hunks


# ── Agent attribution rules ──────────────────────────────────────────

AGENT_RULES = {
    "correctness": ["developer"],
    "spec_alignment": ["developer", "reviewer"],
    "convention": ["developer"],
    "scope": ["guardian", "developer"],
    "testing": ["developer"],
    "maintainability": ["developer"],
    "performance": ["developer"],
}


# ── Ground truth labels ──────────────────────────────────────────────
# Manually labeled from reading the actual diffs above.

GROUND_TRUTH = {
    # Task 1: ((errors++)) -> ((errors++)) || true  (bash arithmetic exit code bug)
    "speed-defects/task-1": {
        "change_type": "transformative",
        "category": "correctness",
        "agents": ["developer"],
        "description": "bash arithmetic increment exits nonzero when var is 0 under set -e",
    },
    # Task 4: Rewrote developer agent prompt (removed hardcoded gate paths)
    "speed-defects/task-4": {
        "change_type": "transformative",
        "category": "correctness",
        "agents": ["developer"],
        "description": "hardcoded gate command paths were wrong, causing retry failures",
    },
    # Task 3: Mixed - || true fixes, return 0 instead of error, configurable patterns
    "speed-security/task-3": {
        "change_type": "transformative",
        "category": "correctness",
        "agents": ["developer"],
        "description": "bash arithmetic fix + error-on-no-branch was wrong + made patterns configurable",
    },
    # Task 6: ((count++)) -> ((count++)) || true
    "speed-security/task-6": {
        "change_type": "transformative",
        "category": "correctness",
        "agents": ["developer"],
        "description": "same bash arithmetic exit code bug as task 1",
    },
}


# ── Git helper ────────────────────────────────────────────────────────

def git_diff(branch: str, files: list[str]) -> str:
    try:
        cmd = ["git", "-C", str(PROJECT_ROOT), "diff", branch, "HEAD", "--"] + files
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return result.stdout if result.returncode == 0 else ""
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


# ── Test cases ────────────────────────────────────────────────────────

TASKS = [
    {
        "id": "speed-defects/task-1",
        "branch": "speed/speed-defects/task-1-defect-state-management-library",
        "files": ["lib/defects.sh"],
    },
    {
        "id": "speed-defects/task-4",
        "branch": "speed/speed-defects/task-4-developer-agent-defect-prompt-variants",
        "files": ["agents/developer.md"],
    },
    {
        "id": "speed-security/task-3",
        "branch": "speed/speed-security/task-3-grounding-level-secrets-scanner",
        "files": ["lib/grounding.sh"],
    },
    {
        "id": "speed-security/task-6",
        "branch": "speed/speed-security/task-6-sast-and-sca-quality-gate-functions-in-l",
        "files": ["lib/gates.sh"],
    },
]


# ── Main ──────────────────────────────────────────────────────────────

def main():
    print("Post-Merge Classifier Validation")
    print("Testing TF-IDF prototype classifier against real diff hunks\n")

    total_hunks = 0
    correct_change_type = 0
    correct_category = 0
    correct_agents = 0
    results = []

    for task in TASKS:
        diff_text = git_diff(task["branch"], task["files"])
        if not diff_text:
            print(f"  [{task['id']}] No diff found — skipping")
            continue

        hunks = parse_diff_hunks(diff_text)
        gt = GROUND_TRUTH.get(task["id"], {})

        print(f"\n{'='*70}")
        print(f"Task: {task['id']}")
        print(f"Ground truth: {gt.get('description', 'unknown')}")
        print(f"Expected: change_type={gt.get('change_type')}, "
              f"category={gt.get('category')}, agents={gt.get('agents')}")
        print(f"Hunks: {len(hunks)}")
        print(f"{'='*70}")

        # Deduplicate similar hunks (e.g., 10 identical ((errors++)) || true fixes)
        seen_descriptions = set()
        unique_hunks = []
        for h in hunks:
            desc_key = (h.change_type, h.description[:80])
            if desc_key not in seen_descriptions:
                seen_descriptions.add(desc_key)
                unique_hunks.append(h)

        for i, hunk in enumerate(unique_hunks):
            total_hunks += 1

            # 1. Deterministic change type
            ct = hunk.change_type
            ct_match = ct == gt.get("change_type", "")
            if ct_match:
                correct_change_type += 1

            # 2. TF-IDF prototype classification
            cr = classify(hunk.description, REVIEW_PROTOTYPES)
            cat_match = cr.category == gt.get("category", "")
            if cat_match:
                correct_category += 1

            # 3. Rule-based agent attribution
            predicted_agents = AGENT_RULES.get(cr.category, ["developer"])
            agent_match = set(predicted_agents) == set(gt.get("agents", []))
            if agent_match:
                correct_agents += 1

            # Report
            ct_sym = "✓" if ct_match else "✗"
            cat_sym = "✓" if cat_match else "✗"
            agent_sym = "✓" if agent_match else "✗"

            print(f"\n  Hunk {i+1}/{len(unique_hunks)} in {hunk.file}")
            print(f"    Change type:  {ct_sym} predicted={ct}, expected={gt.get('change_type')}")
            print(f"    Category:     {cat_sym} predicted={cr.category} (confidence={cr.confidence:.3f}, stage={cr.stage}), expected={gt.get('category')}")
            print(f"    Agents:       {agent_sym} predicted={predicted_agents}, expected={gt.get('agents')}")

            # Show top scores for category
            top_scores = sorted(cr.scores.items(), key=lambda x: -x[1])[:3]
            scores_str = ", ".join(f"{k}={v:.3f}" for k, v in top_scores)
            print(f"    Top scores:   {scores_str}")

            # Show what the classifier saw
            desc_preview = hunk.description[:120]
            print(f"    Input text:   {desc_preview}...")

            results.append({
                "task": task["id"],
                "file": hunk.file,
                "ct_match": ct_match,
                "cat_match": cat_match,
                "agent_match": agent_match,
                "predicted_cat": cr.category,
                "expected_cat": gt.get("category"),
                "confidence": cr.confidence,
            })

    # Summary
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    print(f"\nTotal unique hunks analyzed: {total_hunks}")
    print(f"Change type accuracy:  {correct_change_type}/{total_hunks} ({100*correct_change_type/max(total_hunks,1):.0f}%)")
    print(f"Category accuracy:     {correct_category}/{total_hunks} ({100*correct_category/max(total_hunks,1):.0f}%)")
    print(f"Agent accuracy:        {correct_agents}/{total_hunks} ({100*correct_agents/max(total_hunks,1):.0f}%)")

    overall = sum(1 for r in results if r["ct_match"] and r["cat_match"] and r["agent_match"])
    print(f"All three correct:     {overall}/{total_hunks} ({100*overall/max(total_hunks,1):.0f}%)")

    # Show misclassifications
    misses = [r for r in results if not r["cat_match"]]
    if misses:
        print(f"\nCategory misclassifications:")
        for m in misses:
            print(f"  {m['task']} ({m['file']}): predicted={m['predicted_cat']}, expected={m['expected_cat']}, confidence={m['confidence']:.3f}")

    print(f"\nConclusion: {'LLM classifier NOT needed' if correct_category / max(total_hunks, 1) >= 0.6 else 'Prototype coverage needs expansion'}")


if __name__ == "__main__":
    main()
