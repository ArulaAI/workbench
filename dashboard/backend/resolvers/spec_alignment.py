"""Spec alignment resolver — reads spec-alignment.json, computes coverage."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Optional

import strawberry

logger = logging.getLogger(__name__)


# ── Strawberry types ──────────────────────────────────────────────


@strawberry.type
class ClaimSource:
    spec_file: str
    section: str
    line: int


@strawberry.type
class Claim:
    source: ClaimSource
    claim_type: str
    claim_text: str
    entity: str
    status: str
    evidence: Optional[str]
    divergence: Optional[str]


@strawberry.type
class SectionAlignment:
    section: str
    claim_count: int
    confirmed: int
    missing: int
    unverifiable: int
    coverage_pct: float
    claims: list[Claim]


@strawberry.type
class SpecSummary:
    spec_file: str
    sections: list[SectionAlignment]
    total_claims: int
    confirmed: int
    coverage_pct: float


@strawberry.type
class SpecAlignmentView:
    specs: list[SpecSummary]
    total_claims: int
    total_confirmed: int
    total_missing: int
    total_unverifiable: int
    overall_coverage_pct: float


# ── Resolver ──────────────────────────────────────────────────────


def get_spec_alignment(
    project_root: Path,
    spec_file: Optional[str] = None,
) -> Optional[SpecAlignmentView]:
    """Read spec-alignment.json and compute per-section coverage percentages.

    Groups claims by spec_file + section, counts confirmed/missing/unverifiable.
    """
    from ..paths import get_paths
    paths = get_paths(project_root)
    alignment_path = paths.context_dir / "spec-alignment.json"

    if not alignment_path.exists():
        return None

    try:
        data = json.loads(alignment_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse spec-alignment.json: %s", e)
        return None
    except OSError as e:
        logger.warning("Failed to read spec-alignment.json: %s", e)
        return None

    claims = data.get("claims", [])

    # Optionally filter by spec_file
    if spec_file:
        claims = [
            c for c in claims
            if c.get("source", {}).get("spec_file", "").endswith(spec_file)
        ]

    # Group by spec_file -> section
    by_spec: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for claim in claims:
        if not isinstance(claim, dict):
            logger.warning("Skipping malformed claim: not a dict")
            continue
        source = claim.get("source")
        if not source or not isinstance(source, dict):
            logger.warning("Skipping malformed claim: missing or invalid 'source'")
            continue
        if "status" not in claim:
            logger.warning("Skipping malformed claim: missing 'status'")
            continue
        sf = source.get("spec_file", "unknown")
        section = source.get("section", "unknown")
        by_spec[sf][section].append(claim)

    # Compute summaries
    spec_summaries: list[SpecSummary] = []
    total_confirmed = 0
    total_missing = 0
    total_other = 0

    for sf, sections in sorted(by_spec.items()):
        section_summaries: list[SectionAlignment] = []
        for section_name, section_claims in sorted(sections.items()):
            confirmed = sum(1 for c in section_claims if c.get("status") == "confirmed")
            missing = sum(1 for c in section_claims if c.get("status") == "missing")
            other = len(section_claims) - confirmed - missing

            total_confirmed += confirmed
            total_missing += missing
            total_other += other

            total = len(section_claims)
            pct = (confirmed / total * 100) if total > 0 else 0

            section_summaries.append(SectionAlignment(
                section=section_name,
                claim_count=total,
                confirmed=confirmed,
                missing=missing,
                unverifiable=other,
                coverage_pct=round(pct, 1),
                claims=[
                    Claim(
                        source=ClaimSource(
                            spec_file=c.get("source", {}).get("spec_file", ""),
                            section=c.get("source", {}).get("section", ""),
                            line=c.get("source", {}).get("line", 0),
                        ),
                        claim_type=c.get("claim_type", ""),
                        claim_text=c.get("claim_text", ""),
                        entity=c.get("entity", ""),
                        status=c.get("status", ""),
                        evidence=c.get("evidence"),
                        divergence=c.get("divergence"),
                    )
                    for c in section_claims
                ],
            ))

        spec_total = sum(s.claim_count for s in section_summaries)
        spec_confirmed = sum(s.confirmed for s in section_summaries)
        spec_pct = (spec_confirmed / spec_total * 100) if spec_total > 0 else 0

        spec_summaries.append(SpecSummary(
            spec_file=sf,
            sections=section_summaries,
            total_claims=spec_total,
            confirmed=spec_confirmed,
            coverage_pct=round(spec_pct, 1),
        ))

    grand_total = total_confirmed + total_missing + total_other
    grand_pct = (total_confirmed / grand_total * 100) if grand_total > 0 else 0

    return SpecAlignmentView(
        specs=spec_summaries,
        total_claims=grand_total,
        total_confirmed=total_confirmed,
        total_missing=total_missing,
        total_unverifiable=total_other,
        overall_coverage_pct=round(grand_pct, 1),
    )
