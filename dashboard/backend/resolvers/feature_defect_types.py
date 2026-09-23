"""Typed GraphQL inputs for Define findings and defect intake."""

from __future__ import annotations

from typing import Optional

import strawberry


@strawberry.input
class DefectDraftInput:
    title: str
    severity: str
    severity_confirmed: bool
    related_features: list[str]
    observed: str
    expected: str
    reproduction: str
    reproducibility: str
    last_known_working: str
    environment: str
    error_output: str
    context: str


@strawberry.input
class FileFindingDefectInput:
    feature_name: str
    finding_id: str
    evidence_ids: list[str]
    finding_revision: str
    decision_revision: int
    request_id: str
    draft: DefectDraftInput
    rationale: str
    duplicate_reason: Optional[str] = None


@strawberry.input
class FindingDecisionInput:
    feature_name: str
    finding_id: str
    finding_revision: str
    decision_revision: int
    request_id: str
    action: str
    rationale: str
    task_id: Optional[str] = None
    duplicate_target: Optional[str] = None


@strawberry.input
class FindingMembershipInput:
    finding_id: str
    evidence_identities: list[str]


@strawberry.input
class GroupFindingsInput:
    feature_name: str
    decision_revision: int
    request_id: str
    memberships: list[FindingMembershipInput]
    rationale: str


@strawberry.input
class AppendDefectEvidenceInput:
    feature_name: str
    finding_id: str
    finding_revision: str
    decision_revision: int
    request_id: str
    defect_slug: str
    rationale: str
