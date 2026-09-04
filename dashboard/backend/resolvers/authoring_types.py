"""GraphQL types for guided authoring.

Stable scalars are typed; interview-shaped payloads (coverage entries, the
current question and its response control, section provenance, self-review)
pass through as JSON so a question-bank change reaches the client without a
resolver edit.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

import strawberry


@strawberry.enum
class AuthoringAction(Enum):
    ACCEPT = "accept"
    EDIT = "edit"
    REJECT = "reject"
    DEFER = "defer"


@strawberry.type
class AuthoringProgress:
    confirmed: int
    total: int
    deferred: list[str]


@strawberry.type
class AuthoringIntake:
    status: str
    artifact_type: Optional[str]
    next_input: Optional[strawberry.scalars.JSON]
    message: str
    implementation: Optional[strawberry.scalars.JSON]


@strawberry.type
class AuthoringSession:
    status: str
    feature_name: Optional[str]
    feature_title: Optional[str]
    artifact_type: Optional[str]
    question_bank_version: Optional[str]
    revision: Optional[int]
    message: str
    progress: AuthoringProgress
    draft_available: bool
    artifact_path: Optional[str]
    artifact_content: Optional[str]
    dashboard_url: Optional[str]
    authoring_url: Optional[str]
    helper_path: Optional[str]
    interpreter: Optional[str]
    current_question: Optional[strawberry.scalars.JSON]
    coverage: Optional[strawberry.scalars.JSON]
    sections: Optional[strawberry.scalars.JSON]
    self_review: Optional[strawberry.scalars.JSON]
    resume_step: Optional[strawberry.scalars.JSON]
    upstream: Optional[strawberry.scalars.JSON]
    implementation: Optional[strawberry.scalars.JSON]


@strawberry.type
class AuthoringSessionEvent:
    feature: str
    artifact_type: str
    revision: Optional[int]
    status: str
