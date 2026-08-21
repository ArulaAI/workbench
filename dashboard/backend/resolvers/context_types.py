"""Types specific to the Define Ceremony context package.

Item types (CodebaseItem, LearningItem, etc.) and the ContextPackage type
live in ceremony_types.py.  This module defines the result and status types
that are unique to intent declaration, assembly, and historical comparison.
"""

from __future__ import annotations

from typing import Optional

import strawberry

from .ceremony_types import CeremonyInfo, ContextPackage


# ── Exceptions ─────────────────────────────────────────────────


class FeatureNameError(Exception):
    """Raised when a feature name is invalid or collides with an active ceremony."""

    def __init__(self, reason: str, detail: str) -> None:
        self.reason = reason  # "invalid_chars" | "too_long" | "empty" | "collision" | "consecutive_hyphens" | "leading_trailing_hyphen"
        self.detail = detail  # Human-readable message
        super().__init__(detail)


# ── GraphQL result types ───────────────────────────────────────


@strawberry.type
class DeclareIntentResult:
    """Returned by declareIntent and refineIntent mutations."""

    feature_name: str
    context_package: Optional[ContextPackage] = None
    ceremony: Optional[CeremonyInfo] = None


@strawberry.type
class SourceStatus:
    """Per-source assembly status."""

    name: str
    status: str  # "ok" | "error" | "empty"
    error: Optional[str] = None


@strawberry.type
class AssemblyStatus:
    """Overall context assembly status for a feature."""

    status: str  # "idle" | "assembling" | "complete"
    sources: list[SourceStatus]


@strawberry.type
class ContextHistory:
    """Snapshot vs. current comparison for the history view (S13)."""

    snapshot: Optional[ContextPackage]
    current: Optional[ContextPackage]
    current_assembly_status: str  # "ok" | "error"
    current_assembly_error: Optional[str] = None
    ceremony: Optional[CeremonyInfo] = None
