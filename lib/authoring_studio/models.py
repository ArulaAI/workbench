"""Small, provider-independent document contracts."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Kind = Literal["prd", "design", "rfc"]
SourceMode = Literal["brief", "prd", "design", "prd_design"]

TEMPLATES = {
    "prd": [
        ("metadata", "Metadata"), ("summary", "Summary"),
        ("problem", "Problem and evidence"), ("hypothesis", "Hypothesis"),
        ("stories", "User stories"), ("requirements", "Requirements and acceptance"),
        ("scope", "Scope"), ("guardrails", "Guardrails"),
        ("risks", "Delivery risks and open questions"), ("success", "Success"),
        ("references", "References"),
    ],
    "design": [
        ("intent", "Experience intent"), ("users", "Users and entry points"),
        ("journeys", "User journeys"), ("states", "Interactions and states"),
        ("accessibility", "Accessibility and content"),
        ("coverage", "Requirement coverage"), ("validation", "Validation"),
        ("decisions", "Open decisions"),
    ],
    "rfc": [
        ("metadata", "Metadata and status"), ("decision", "Decision summary and approval ask"),
        ("context", "Context and constraints"), ("design", "Proposed design"),
        ("contracts", "Contracts and impact"), ("alternatives", "Alternatives and tradeoffs"),
        ("delivery", "Delivery and verification"), ("decisions", "Open decisions and ownership"),
    ],
}
PREFIXES = {"stories": "US", "requirements": "REQ", "guardrails": "GR", "success": "SM"}
RFC_MODULES = ["api", "persistence", "compatibility", "migration", "security", "privacy",
               "reliability", "rollout", "performance", "ai_evaluation"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Item(StrictModel):
    id: str = Field(description="Existing ID unchanged, or a unique new-* placeholder for a new entity.")
    statement: str = Field(min_length=1, max_length=6000)
    verification: str = Field(description="Acceptance check, regression check, or success signal; outcome for a user story.", min_length=1, max_length=6000)
    references: list[str] = Field(default_factory=list)


class Section(StrictModel):
    id: str
    body: str = Field(max_length=18000)
    items: list[Item] = Field(default_factory=list, max_length=50)
    source_ids: list[str] = Field(default_factory=list, description="Use ONLY exact source IDs from available_source_ids. Do not use document titles, requirement IDs or snapshot IDs as source IDs.")


class Question(StrictModel):
    id: str = Field(description="Stable short identifier; retain the same ID across revisions.")
    question: str = Field(min_length=1, max_length=2000)
    why: str = Field(max_length=2000)
    blocking: bool
    section_id: str = Field(default="", description="Core section this question concerns, or empty for document-wide decisions.")


class Coverage(StrictModel):
    module: str
    status: Literal["material", "not_material", "unresolved"]
    rationale: str = Field(min_length=1, max_length=3000)


class Generation(StrictModel):
    summary: str = Field(min_length=1, max_length=2500)
    sections: list[Section] = Field(min_length=1, max_length=15)
    questions: list[Question] = Field(default_factory=list, max_length=3)
    assumptions: list[str] = Field(default_factory=list, max_length=15)
    coverage: list[Coverage] = Field(default_factory=list, max_length=10)


class InitialDocument(Generation):
    questions: list[Question] = Field(default_factory=list, max_length=0,
                                     description="Clarification is complete. Use the author's saved answers.")


class InitialPRD(InitialDocument):
    sections: list[Section] = Field(min_length=11, max_length=11)


class InitialDesign(InitialDocument):
    sections: list[Section] = Field(min_length=8, max_length=8)


class InitialRFC(InitialDocument):
    sections: list[Section] = Field(min_length=8, max_length=8)


INITIAL_DOCUMENT_MODELS = {"prd": InitialPRD, "design": InitialDesign, "rfc": InitialRFC}


class SuggestedAnswer(StrictModel):
    label: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=1000)


class ClarificationQuestion(StrictModel):
    id: str = Field(min_length=1, max_length=80)
    question: str = Field(min_length=1, max_length=2000)
    why: str = Field(min_length=1, max_length=2000)
    options: list[SuggestedAnswer] = Field(min_length=3, max_length=3,
        description="Three distinct, concrete answers. The application adds Write my own as the fourth option.")


class Clarification(StrictModel):
    summary: str = Field(min_length=1, max_length=2500)
    workspace_title: str | None = Field(default=None, min_length=1, max_length=160, pattern=r"\S")
    questions: list[ClarificationQuestion] = Field(default_factory=list, max_length=6,
        description="Only unanswered decisions necessary for the requested document; empty when the supplied context is sufficient.")


class NamedClarification(Clarification):
    workspace_title: str = Field(min_length=1, max_length=160, pattern=r"\S",
        description="A concise, descriptive title derived from the author's problem or intended outcome. No document-type prefix, invented solution or generic feature label.")


class Command(StrictModel):
    action: Literal["generate", "revise", "reconcile", "edit", "comment", "resolve", "dismiss",
                    "reopen", "publish", "cancel", "retry", "restore", "review_section", "answer_clarification",
                    "acknowledge_publication", "revoke_publication_review"]
    expected_revision: int = Field(ge=0)
    request_id: str = Field(min_length=8, max_length=100)
    kind: Kind = "prd"
    text: str = Field(default="", max_length=20000)
    section_id: str | None = None
    version_id: str | None = None
    comment_id: str | None = None
    quote: str = Field(default="", max_length=4000)
    blocking: bool = False
    items: list[Item] | None = None
    question_id: str | None = None
    choice: Literal["option-1", "option-2", "option-3", "custom"] | None = None
    review_group: Literal["success", "open_questions"] | None = None
    disposition: Literal["confirmed", "deferred"] | None = None
    source_mode: SourceMode | None = None


class DeleteFeature(StrictModel):
    expected_revision: int = Field(ge=0)


class CreateFeature(StrictModel):
    kind: Kind = "prd"
    title: str = Field(default="", max_length=160)
    brief: str = Field(min_length=12, max_length=20000)
    context: str = Field(default="", max_length=20000)
    request_id: str = Field(min_length=8, max_length=100)

    @field_validator("title", "brief", mode="before")
    @classmethod
    def trim_input(cls, value):
        return value.strip() if isinstance(value, str) else value
