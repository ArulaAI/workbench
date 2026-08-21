"""Knowledge proposal merger for multi-player mode.

Reads pending proposals from shared/proposals/, auto-merges non-conflicting
entries into shared/knowledge/, bumps confidence on matches, and writes
conflicts to knowledge/conflicts.json for human curation.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# Confidence tiers
CONFIDENCE_LOW = "low"           # single observation from one actor
CONFIDENCE_MEDIUM = "medium"     # multiple observations or multiple actors
CONFIDENCE_HIGH = "high"         # consistent across 3+ features
CONFIDENCE_LOCKED = "locked"     # human-curated, never auto-modified


@dataclass
class MergeResult:
    """Result of merging proposals into shared knowledge."""
    merged: int = 0
    bumped: int = 0
    conflicted: int = 0
    skipped: int = 0
    proposals_processed: int = 0


def compute_confidence(
    convention: dict[str, Any],
    all_proposals: list[dict[str, Any]],
) -> str:
    """Compute confidence tier for a convention based on cross-proposal evidence.

    Scoring rules:
    - low: seen in 1 proposal from 1 actor
    - medium: seen in 2+ proposals OR 2+ actors
    - high: seen in 3+ features
    - locked: only set by human curation (never computed)
    """
    key = convention.get("key") or convention.get("pattern") or convention.get("name", "")
    if not key:
        return CONFIDENCE_LOW

    actors = set()
    features = set()

    for proposal in all_proposals:
        for conv in proposal.get("conventions", []):
            conv_key = conv.get("key") or conv.get("pattern") or conv.get("name", "")
            if conv_key == key:
                actors.add(proposal.get("actor", "unknown"))
                features.add(proposal.get("feature", "unknown"))

    if len(features) >= 3:
        return CONFIDENCE_HIGH
    if len(actors) >= 2 or len(features) >= 2:
        return CONFIDENCE_MEDIUM
    return CONFIDENCE_LOW


def _load_existing_knowledge(knowledge_dir: Path) -> dict[str, Any]:
    """Load existing conventions from shared knowledge."""
    conventions_file = knowledge_dir / "conventions.json"
    if conventions_file.exists():
        return json.loads(conventions_file.read_text())
    return {"conventions": [], "metadata": {}}


def _convention_key(conv: dict[str, Any]) -> str:
    """Extract a stable key for deduplication."""
    return conv.get("key") or conv.get("pattern") or conv.get("name") or json.dumps(conv, sort_keys=True)


def merge_proposals(
    proposals_dir: Path,
    knowledge_dir: Path,
) -> MergeResult:
    """Merge pending proposals into shared knowledge.

    Non-conflicting conventions are auto-merged. Conflicting ones
    (same key, different values) are written to conflicts.json.
    """
    result = MergeResult()

    # Load all pending proposals
    proposals = []
    proposal_files = sorted(proposals_dir.glob("*.json"))
    for pf in proposal_files:
        try:
            data = json.loads(pf.read_text())
            if data.get("status") == "pending":
                proposals.append(data)
        except (json.JSONDecodeError, KeyError):
            continue

    if not proposals:
        return result

    result.proposals_processed = len(proposals)

    # Load existing knowledge
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    existing = _load_existing_knowledge(knowledge_dir)
    existing_convs = {_convention_key(c): c for c in existing.get("conventions", [])}

    # Collect all proposed conventions
    new_convs: dict[str, list[dict[str, Any]]] = {}
    for proposal in proposals:
        for conv in proposal.get("conventions", []):
            key = _convention_key(conv)
            if key not in new_convs:
                new_convs[key] = []
            new_convs[key].append(conv)

    conflicts = []

    for key, proposed_list in new_convs.items():
        if key in existing_convs:
            existing_conv = existing_convs[key]
            # Skip locked conventions
            if existing_conv.get("confidence") == CONFIDENCE_LOCKED:
                result.skipped += 1
                continue

            # Check for value conflicts
            values = {json.dumps(p.get("value", p.get("description", "")), sort_keys=True) for p in proposed_list}
            existing_value = json.dumps(existing_conv.get("value", existing_conv.get("description", "")), sort_keys=True)

            if len(values) == 1 and values.pop() == existing_value:
                # Same value — bump confidence
                new_confidence = compute_confidence(existing_conv, proposals)
                if new_confidence != existing_conv.get("confidence"):
                    existing_conv["confidence"] = new_confidence
                    result.bumped += 1
            else:
                # Conflict
                conflicts.append({
                    "key": key,
                    "existing": existing_conv,
                    "proposed": proposed_list,
                })
                result.conflicted += 1
        else:
            # New convention — check internal consistency
            values = {json.dumps(p.get("value", p.get("description", "")), sort_keys=True) for p in proposed_list}
            if len(values) > 1:
                conflicts.append({
                    "key": key,
                    "existing": None,
                    "proposed": proposed_list,
                })
                result.conflicted += 1
            else:
                # Auto-merge
                merged_conv = proposed_list[0].copy()
                merged_conv["confidence"] = compute_confidence(merged_conv, proposals)
                existing_convs[key] = merged_conv
                result.merged += 1

    # Write updated knowledge
    existing["conventions"] = list(existing_convs.values())
    conventions_file = knowledge_dir / "conventions.json"
    tmp = conventions_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(existing, indent=2))
    tmp.rename(conventions_file)

    # Write conflicts if any
    if conflicts:
        conflicts_file = knowledge_dir / "conflicts.json"
        tmp = conflicts_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(conflicts, indent=2))
        tmp.rename(conflicts_file)

    # Mark proposals as processed
    for pf in proposal_files:
        try:
            data = json.loads(pf.read_text())
            if data.get("status") == "pending":
                data["status"] = "merged"
                pf.write_text(json.dumps(data, indent=2))
        except (json.JSONDecodeError, KeyError):
            continue

    # Merge observations into shared knowledge
    obs_file = knowledge_dir / "observations.jsonl"
    with open(obs_file, "a") as f:
        for proposal in proposals:
            for obs in proposal.get("observations", []):
                f.write(json.dumps(obs) + "\n")

    return result
