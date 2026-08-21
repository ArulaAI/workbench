"""Spec splitting and verification for phased architect planning.

Split a tech spec by H2 headings for phased planning. The exclude-other-phase
approach ensures shared sections (those not assigned to either phase) appear in
both phases by default.

Heading resolution
------------------
The audit agent assigns H2 headings to phases using 0-based indices into the
document-order heading list. ``_resolve_indices`` maps those indices back to
the canonical heading text extracted deterministically from the spec file.
Heading text flows through a single path (code extraction), never through the
LLM, so there is no format mismatch to reconcile.
"""

from __future__ import annotations

from typing import Any


def _extract_h2(text: str) -> list[str]:
    """Extract H2 headings from markdown in document order.

    Returns the full heading text after the ``## `` prefix, preserving any
    annotations like ``**[NEW]**`` or ``**[MODIFIED ...]**``.
    """
    return [
        line[3:].strip()
        for line in text.split("\n")
        if line.startswith("## ") and not line.startswith("### ")
    ]


def _resolve_indices(
    spec_content: str,
    indices: list[int],
) -> tuple[list[str], list[str]]:
    """Resolve heading indices to canonical heading text.

    Returns:
        (resolved_headings, errors)
    """
    all_headings = _extract_h2(spec_content)
    resolved: list[str] = []
    errors: list[str] = []

    for idx in indices:
        if not isinstance(idx, int) or idx < 0 or idx >= len(all_headings):
            errors.append(
                f"Heading index {idx} out of range "
                f"(spec has {len(all_headings)} H2 headings)"
            )
        else:
            resolved.append(all_headings[idx])

    return resolved, errors


def split_spec_for_phase(spec_content: str, exclude_indices: list[int]) -> str:
    """Exclude the other phase's H2 sections from a spec.

    Sections not in the exclude list (shared sections) are preserved.
    The preamble before the first H2 is always preserved.

    Args:
        spec_content: Full spec markdown content.
        exclude_indices: 0-based indices of H2 headings to remove.

    Returns:
        Filtered spec content with excluded sections removed.
    """
    if not exclude_indices:
        return spec_content

    headings, errors = _resolve_indices(spec_content, exclude_indices)
    if errors:
        raise ValueError("; ".join(errors))

    exclude = set(headings)
    lines = spec_content.split("\n")
    output: list[str] = []
    in_excluded_section = False

    for line in lines:
        if line.startswith("## ") and not line.startswith("### "):
            current_h2 = line[3:].strip()
            in_excluded_section = current_h2 in exclude
        if not in_excluded_section:
            output.append(line)

    return "\n".join(output)


def verify_spec_split(
    original: str,
    phase1: str,
    phase2: str,
    phase1_indices: list[int],
    phase2_indices: list[int],
    min_size_pct: float = 30.0,
) -> dict[str, Any]:
    """Verify that a spec split didn't lose context.

    Three checks:
      1. Index validation: every audit index resolves to a real spec heading.
      2. Coverage invariant: every original H2 appears in at least one phase output.
      3. Minimum size: neither phase is less than min_size_pct of the original.

    Args:
        original: Full spec content.
        phase1: Phase 1 split output.
        phase2: Phase 2 split output.
        phase1_indices: 0-based heading indices for Phase 1.
        phase2_indices: 0-based heading indices for Phase 2.
        min_size_pct: Minimum percentage threshold for size warning.

    Returns:
        {"pass": bool, "errors": [...], "warnings": [...]}
    """
    errors: list[str] = []
    warnings: list[str] = []

    # Check 1: resolve indices to canonical headings
    p1_headings, p1_errors = _resolve_indices(original, phase1_indices)
    p2_headings, p2_errors = _resolve_indices(original, phase2_indices)
    errors.extend(p1_errors)
    errors.extend(p2_errors)

    # Check 2: every spec heading in at least one phase output
    orig_h2 = set(_extract_h2(original))
    p1_h2 = set(_extract_h2(phase1))
    p2_h2 = set(_extract_h2(phase2))

    uncovered = orig_h2 - (p1_h2 | p2_h2)
    if uncovered:
        errors.append(
            f"Sections lost from both phases: {', '.join(sorted(uncovered))}"
        )

    # Check 3: minimum size threshold
    orig_len = len(original)
    if orig_len > 0:
        p1_pct = len(phase1) / orig_len * 100
        p2_pct = len(phase2) / orig_len * 100
        if p1_pct < min_size_pct:
            warnings.append(
                f"Phase 1 is {p1_pct:.0f}% of original "
                f"({len(phase1)}/{orig_len} chars)"
            )
        if p2_pct < min_size_pct:
            warnings.append(
                f"Phase 2 is {p2_pct:.0f}% of original "
                f"({len(phase2)}/{orig_len} chars)"
            )

    return {"pass": len(errors) == 0, "errors": errors, "warnings": warnings}
