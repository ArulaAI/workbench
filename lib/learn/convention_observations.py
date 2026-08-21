"""Phase B: Observation log integration for the conventions pipeline.

Integrates SPEED observation logs into raw patterns discovered by the
mechanical extractors. Corroborates existing patterns and surfaces
observation-only conventions that have no code footprint yet.
"""

import json
import logging
from dataclasses import replace
from pathlib import Path

from lib.learn.conventions import RawPattern

logger = logging.getLogger(__name__)

# Minimum convention_violation observations required to corroborate a pattern.
_VIOLATION_THRESHOLD = 3


def _get_obs_files(obs: dict) -> list[str]:
    """Extract file paths from an observation's detail dict."""
    detail = obs.get("detail", {}) if isinstance(obs, dict) else {}
    files: list[str] = []

    files_involved = detail.get("files_involved")
    if isinstance(files_involved, list):
        files.extend(f for f in files_involved if isinstance(f, str) and f)

    file_val = detail.get("file")
    if isinstance(file_val, str) and file_val:
        files.append(file_val)

    return files


def _matches_scope(obs_files: list[str], pattern_scope: list[str]) -> bool:
    """Return True if any observation file falls under any pattern scope prefix."""
    for obs_file in obs_files:
        for scope in pattern_scope:
            if not scope:
                continue
            if obs_file.startswith(scope):
                return True
    return False


def _obs_group_key(obs: dict) -> str:
    """Derive a grouping key for creating observation-only patterns."""
    obs_type = obs.get("observation_type", "unknown")
    detail = obs.get("detail", {}) if isinstance(obs, dict) else {}
    category = detail.get("category") or detail.get("change_category") or ""
    return f"{obs_type}:{category}" if category else obs_type


def _integrate_observations(
    raw_patterns: list[RawPattern], obs_dir: Path
) -> list[RawPattern]:
    """Integrate observation log data into raw patterns.

    Reads all .jsonl files from obs_dir, filters for convention-relevant
    observation types, and updates raw_patterns with observation_support.
    Creates new RawPattern objects for observation-only conventions (observations
    that have no matching code pattern).

    Convention-relevant observation types:
    - convention_violation: direct evidence of a pattern deviation
    - reviewer_finding with category='convention': reviewer spotted a convention
    - human_override with change_category in ('convention', 'style'): human corrected code

    Args:
        raw_patterns: Patterns from Phase A mechanical extractors.
        obs_dir: Path to the observation log directory (.speed/memory/observations/).

    Returns:
        Updated pattern list. Patterns without observation matches are returned
        as the same objects (identity preserved). Patterns that gain support are
        returned as new objects with incremented observation_support. Observation-
        only patterns are appended at the end.
    """
    if not obs_dir.exists() or not obs_dir.is_dir():
        return raw_patterns

    jsonl_files = list(obs_dir.glob("*.jsonl"))
    if not jsonl_files:
        return raw_patterns

    relevant_obs: list[dict] = []
    total_lines = 0
    malformed_count = 0

    for jsonl_file in sorted(jsonl_files):
        try:
            content = jsonl_file.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not read %s: %s", jsonl_file, exc)
            continue

        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
            total_lines += 1
            try:
                obs = json.loads(line)
            except json.JSONDecodeError as exc:
                malformed_count += 1
                logger.warning(
                    "Skipping malformed JSON in %s: %s", jsonl_file.name, exc
                )
                continue

            if not isinstance(obs, dict):
                malformed_count += 1
                logger.warning("Skipping non-dict entry in %s", jsonl_file.name)
                continue

            obs_type = obs.get("observation_type", "")
            detail = obs.get("detail", {}) if isinstance(obs.get("detail"), dict) else {}

            if obs_type == "convention_violation":
                relevant_obs.append(obs)
            elif obs_type == "reviewer_finding" and detail.get("category") == "convention":
                relevant_obs.append(obs)
            elif obs_type == "human_override" and detail.get("change_category") in (
                "convention",
                "style",
            ):
                relevant_obs.append(obs)

    if total_lines > 0 and malformed_count == total_lines:
        logger.warning(
            "All %d observation lines were malformed; returning patterns unchanged",
            malformed_count,
        )
        return raw_patterns

    if not relevant_obs:
        return raw_patterns

    # Build mutable list — only replace elements that gain support so that
    # unmatched patterns preserve their original object identity.
    patterns: list[RawPattern] = list(raw_patterns)

    # Accumulate support increments before mutating so each pattern is
    # replaced at most once.
    support_increments: list[int] = [0] * len(patterns)

    # Track which observation indices were matched to at least one pattern.
    obs_matched: set[int] = set()

    # Collect convention_violation matches per pattern for threshold check.
    violations_by_pattern: list[list[int]] = [[] for _ in patterns]
    # Collect human_override / reviewer_finding matches per pattern.
    other_by_pattern: list[list[int]] = [[] for _ in patterns]

    for obs_idx, obs in enumerate(relevant_obs):
        obs_type = obs.get("observation_type", "")
        obs_files = _get_obs_files(obs)

        for pat_idx, pattern in enumerate(patterns):
            if not pattern.scope or not obs_files:
                continue
            if not _matches_scope(obs_files, pattern.scope):
                continue

            if obs_type == "convention_violation":
                violations_by_pattern[pat_idx].append(obs_idx)
            else:
                other_by_pattern[pat_idx].append(obs_idx)

    # Apply accumulated support — violations only when 3+ match the same pattern.
    for pat_idx in range(len(patterns)):
        violations = violations_by_pattern[pat_idx]
        if len(violations) >= _VIOLATION_THRESHOLD:
            support_increments[pat_idx] += len(violations)
            obs_matched.update(violations)

        others = other_by_pattern[pat_idx]
        support_increments[pat_idx] += len(others)
        obs_matched.update(others)

    # Replace only patterns that gained support (preserves identity for others).
    for pat_idx, increment in enumerate(support_increments):
        if increment > 0:
            patterns[pat_idx] = replace(
                patterns[pat_idx],
                observation_support=patterns[pat_idx].observation_support + increment,
            )

    # Create new RawPattern objects for observations with no matching pattern.
    unmatched = [obs for idx, obs in enumerate(relevant_obs) if idx not in obs_matched]
    if unmatched:
        groups: dict[str, list[dict]] = {}
        for obs in unmatched:
            key = _obs_group_key(obs)
            groups.setdefault(key, []).append(obs)

        for key, group_obs in groups.items():
            # Deduplicate files and derive scopes while preserving insertion order.
            seen_files: dict[str, None] = {}
            seen_scopes: dict[str, None] = {}
            for obs in group_obs:
                for f in _get_obs_files(obs):
                    seen_files[f] = None
                    parts = f.split("/")
                    if len(parts) > 1:
                        seen_scopes[parts[0] + "/"] = None

            patterns.append(
                RawPattern(
                    type=key,
                    files=list(seen_files),
                    scope=list(seen_scopes),
                    adherence=0.0,
                    evidence="N/A — observation-derived",
                    observation_support=len(group_obs),
                    recent_trend="stable",
                )
            )

    return patterns
