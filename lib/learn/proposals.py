"""Knowledge proposal writer for multi-player mode.

When MP is enabled, learn_extract writes proposals instead of directly
modifying shared knowledge. Each proposal is a timestamped JSON file
in shared/proposals/ that can be reviewed and merged.
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class ProposalResult:
    """Result of writing a proposal."""
    path: Path
    observation_count: int
    convention_count: int
    feature: str
    actor: str


def write_proposal(
    observations: list[dict[str, Any]],
    conventions: list[dict[str, Any]],
    feature: str,
    actor: str,
    proposals_dir: Path,
) -> ProposalResult:
    """Write extracted observations and conventions as a proposal.

    Each proposal is a standalone JSON file that can be auto-merged or
    reviewed during `speed learn merge`.
    """
    proposals_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    slug = actor.lower().replace(" ", "-")
    filename = f"{ts}_{slug}_{feature}.json"

    proposal = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "actor": actor,
        "feature": feature,
        "observations": observations,
        "conventions": conventions,
        "status": "pending",
    }

    path = proposals_dir / filename
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(proposal, indent=2))
    tmp.rename(path)

    return ProposalResult(
        path=path,
        observation_count=len(observations),
        convention_count=len(conventions),
        feature=feature,
        actor=actor,
    )
