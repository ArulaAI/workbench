"""Derive per-spec transition sets from the ceremony directory.

The ceremony state machine needs three sets to evaluate transition gates:
drafted_specs, committed_specs, and ratified_specs. Rather than storing
these on CeremonyState (which would duplicate filesystem state and invite
drift), they are derived on demand from the per-spec files that are the
actual ground truth.

See specs/tech/speed-define-ceremony-ownership.md section "Derived per-spec
sets (no new Revision fields)" for the contract.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from ..paths import get_paths


def derive_transition_sets(
    feature_name: str,
    *,
    project_root: Path | None = None,
) -> tuple[set[str], set[str], set[str]]:
    """Return (drafted, committed, ratified) sets for the current revision.

    - `drafted`:   spec_types with a `draft-{spec_type}.json` file on disk.
    - `committed`: spec_types with a `commit-{spec_type}.json` file on disk.
    - `ratified`:  spec_types with a `ratification-{spec_type}.json` file
                   whose `ratified` field is True.

    Note: the RFC prose mentions `draft-*.md`, but the existing
    `ceremony_draft()` path helper uses `.json`. The derivation follows the
    on-disk reality.

    The ceremony directory is expected to exist. A missing directory yields
    three empty sets rather than raising.
    """
    root = project_root or Path(os.environ.get("SPEED_PROJECT_ROOT", os.getcwd()))
    paths = get_paths(root)
    ceremony_dir = paths.ceremony_dir(feature_name)

    if not ceremony_dir.is_dir():
        return set(), set(), set()

    drafted = {
        f.stem.removeprefix("draft-")
        for f in ceremony_dir.glob("draft-*.json")
    }
    committed = {
        f.stem.removeprefix("commit-")
        for f in ceremony_dir.glob("commit-*.json")
    }

    ratified: set[str] = set()
    for f in ceremony_dir.glob("ratification-*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("ratified") is True:
            ratified.add(f.stem.removeprefix("ratification-"))

    return drafted, committed, ratified


def has_eligible_ratifier(
    commit_author_email: str,
    roster_emails: list[str],
) -> bool:
    """Return True iff the roster has a member other than the commit author.

    Used by `commitSpec` at commit time to decide whether to write the
    ratification file inline (`source: "no-eligible-ratifier"`). This is a
    roster-side check, not an authorization rule — the authorization check
    for `ratify` is a flat "not the commit author" predicate.

    A single-member roster always returns False. A multi-member roster
    returns False only in the edge case where every non-author has been
    removed from the roster between commit and ratify.
    """
    return any(email != commit_author_email for email in roster_emails)
