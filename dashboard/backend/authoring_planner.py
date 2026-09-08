"""Model-backed coverage analysis and interview planning for guided PRDs.

The question bank remains the stable coverage contract.  The model decides
which decisions are already answered, which are not material, and how to ask
only the remaining contextual questions.  The helper validates and persists
the resulting plan; deterministic planning is used only when this module
cannot obtain a valid model response.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import sqlite3
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .llm import get_available_models, llm_complete, read_model_config

log = logging.getLogger("speed.dashboard.authoring.planner")

# v5 plans against the complete PRD contract and lets evidence completeness,
# rather than an arbitrary batch cap, determine the interview length.
PLANNER_VERSION = "model-prd-v5"
DOWNSTREAM_PLANNER_VERSION = "model-downstream-v1"
PLANNING_TIMEOUT_SECONDS = 45


def planner_version_for(artifact_type: str) -> str:
    return PLANNER_VERSION if artifact_type == "prd" else DOWNSTREAM_PLANNER_VERSION


class CoverageDecision(BaseModel):
    """The semantic decision for one stable PRD coverage area."""

    status: Literal["covered", "partial", "missing", "not_material"]
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=8, max_length=300)
    resolved_value: Optional[str] = Field(
        default=None,
        max_length=1200,
        description="Meaningful PRD-ready value when status is covered",
    )


class CoverageMap(BaseModel):
    """All stable coverage IDs, required explicitly by the output schema."""

    model_config = ConfigDict(populate_by_name=True)

    p_q1: CoverageDecision = Field(alias="P-Q1")
    p_q2: CoverageDecision = Field(alias="P-Q2")
    p_q3: CoverageDecision = Field(alias="P-Q3")
    p_q4: CoverageDecision = Field(alias="P-Q4")
    p_q5: CoverageDecision = Field(alias="P-Q5")
    p_q6: CoverageDecision = Field(alias="P-Q6")
    p_q7: CoverageDecision = Field(alias="P-Q7")
    p_q8: CoverageDecision = Field(alias="P-Q8")


class InterviewOption(BaseModel):
    """One contextual answer choice.  Its value is persisted as the answer."""

    value: str = Field(min_length=3, max_length=1200)
    label: str = Field(min_length=2, max_length=120)
    recommended: bool = False


class PlannedQuestion(BaseModel):
    """One question for an unresolved, material PRD decision."""

    coverage_id: str
    prompt: str = Field(min_length=12, max_length=1000)
    response_type: Literal["single_select", "multi_select", "textarea"]
    options: list[InterviewOption] = Field(default_factory=list, max_length=4)
    suggested_answer: Optional[str] = Field(default=None, max_length=1200)
    suggestion_confidence: Literal["grounded", "partial", "missing"] = "missing"
    suggestion_gap: Optional[str] = Field(default=None, max_length=300)


class PlannedRequirement(BaseModel):
    story_id: str = Field(default="US-1", min_length=4, max_length=20)
    product_behavior: str = Field(min_length=12, max_length=800)
    done_when: str = Field(min_length=12, max_length=800)


class PlannedScope(BaseModel):
    included: str = Field(min_length=3, max_length=1200)
    not_included: str = Field(min_length=3, max_length=1200)


class PlannedGuardrail(BaseModel):
    must_remain_true: str = Field(min_length=12, max_length=800)
    verification: str = Field(min_length=12, max_length=800)


class PlannedSuccess(BaseModel):
    outcome_or_signal: str = Field(min_length=12, max_length=800)
    target: str = Field(min_length=3, max_length=300)
    window: str = Field(min_length=3, max_length=300)
    owner: str = Field(min_length=2, max_length=200)


class DraftComposition(BaseModel):
    requirements: list[PlannedRequirement] = Field(default_factory=list, max_length=6)
    scope: Optional[PlannedScope] = None
    guardrails: list[PlannedGuardrail] = Field(default_factory=list, max_length=3)
    success: Optional[PlannedSuccess] = None


class ModelInterviewPlan(BaseModel):
    """Semantic coverage assessment and the complete necessary interview."""

    feature_title: str = Field(
        min_length=3,
        max_length=80,
        description="Concise product feature title derived from the author's description",
    )
    analysis_summary: str = Field(min_length=12, max_length=500)
    prd_size: Literal["Small", "Standard", "Initiative"] = "Small"
    coverage: CoverageMap
    questions: list[PlannedQuestion] = Field(default_factory=list)
    composition: DraftComposition = Field(default_factory=DraftComposition)


class CompactCoverageResolution(BaseModel):
    """One coverage area already resolved by author or repository evidence."""

    coverage_id: str
    resolved_value: str = Field(min_length=3, max_length=1200)
    confidence: float = Field(default=0.85, ge=0, le=1)


class CompactInterviewPlan(BaseModel):
    """Completeness-focused intake result; full PRD composition is deferred."""

    feature_title: str = Field(min_length=3, max_length=80)
    analysis_summary: str = Field(min_length=12, max_length=500)
    prd_size: Literal["Small", "Standard", "Initiative"] = "Small"
    resolved_coverage: list[CompactCoverageResolution] = Field(
        default_factory=list,
        max_length=8,
    )
    questions: list[PlannedQuestion] = Field(default_factory=list)


class RevisedPrdSection(BaseModel):
    """Complete replacement body for one reviewer-commented PRD section."""

    section_title: str = Field(min_length=2, max_length=160)
    revised_body: str = Field(min_length=12, max_length=12000)


class PrdReviewRevision(BaseModel):
    """A focused revision of every section named by the reviewer."""

    analysis_summary: str = Field(min_length=12, max_length=500)
    sections: list[RevisedPrdSection] = Field(min_length=1, max_length=10)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _reference_paths(artifact_type: str = "prd") -> tuple[Path, Path]:
    root = Path(__file__).resolve().parents[2]
    references = root / "skills" / "workbench-draft" / "references"
    return references / f"{artifact_type}-questions.json", references / "prd-template.md"


def _planner_prompt_path() -> Path:
    return _reference_paths("prd")[0].parent / "prd-interview-planner-prompt.md"


def _select_model(project_root: Path) -> str:
    config = read_model_config(project_root)
    available = get_available_models(project_root)
    if not available:
        raise RuntimeError(
            "No configured LLM is available. Configure an API provider or the CLI model in speed.toml."
        )
    # Guided intake is a bounded extraction/classification task. Prefer the
    # faster support model instead of the high-latency architecture model.
    # Projects that have not configured a support model still retain the
    # existing planning-model and first-available fallbacks.
    preferred = str(
        config.get("support_model") or config.get("planning_model") or "sonnet"
    ).strip()
    if preferred:
        for entry in available:
            model_id = str(entry["id"])
            if model_id == preferred or model_id.endswith(f"/{preferred}"):
                return model_id
    return str(available[0]["id"])


def _read_text(path: Path, limit: int) -> str:
    try:
        return path.read_text(encoding="utf-8")[:limit]
    except OSError:
        return ""


def _project_context(project_root: Path, feature_name: str) -> str:
    """Return a small, fixed context package for PRD decisions.

    Context assembly will eventually be owned by a dedicated repository
    intelligence module. Until then, use only the explicit project summary,
    feature package, and product vision. Do not recursively scan arbitrary
    repository documents: that made prompt size and planning latency depend on
    repository size and pulled unrelated historical PRDs into the interview.
    """
    chunks: list[str] = []
    included: set[Path] = set()
    total_chars = 0
    total_limit = 12000

    def include(path: Path, per_file_limit: int = 7000) -> None:
        nonlocal total_chars
        if path in included or total_chars >= total_limit or not path.is_file():
            return
        text = _read_text(path, min(per_file_limit, total_limit - total_chars))
        if not text.strip():
            return
        try:
            label = path.relative_to(project_root).as_posix()
        except ValueError:
            label = str(path)
        chunks.append(f"SOURCE {label}\n{text}")
        included.add(path)
        total_chars += len(text)

    # This stable file is the temporary hand-authored contract. A future
    # context module can generate/replace it without changing the planner API.
    for relative in (
        ".speed/context/authoring-project-context.md",
        ".speed/context/authoring-project-context.json",
    ):
        candidate = project_root / relative
        if candidate.is_file():
            include(candidate, 6000)
            break

    feature_dir = project_root / ".speed" / "features" / feature_name
    shared_dir = project_root / ".speed" / "shared" / "features" / feature_name
    for candidate in (
        feature_dir / "context-package.json",
        shared_dir / "context-package.json",
    ):
        if candidate.is_file():
            include(candidate, 3000)
            break

    include(project_root / "specs" / "product" / "overview.md", 3000)

    return "\n\n".join(chunks) or "No additional repository context was available."


def _confirmed_answers(payload: dict) -> list[dict[str, str]]:
    answers: list[dict[str, str]] = []
    for item in payload.get("interview") or []:
        if item.get("state") == "confirmed" and item.get("answer"):
            answers.append({
                "coverage_id": str(item.get("coverage_id") or item.get("id") or ""),
                "question": str(item.get("prompt") or ""),
                "answer": str(item.get("answer") or ""),
            })
    return answers


def _compact_bank(bank: dict, artifact_type: str = "prd") -> list[dict]:
    return [
        {
            "id": item["id"],
            "coverage": item.get("coverage"),
            "required": (
                item.get("applicability") == "always"
                or artifact_type in {"design", "rfc"}
            ),
            "sections": item.get("sections") or [],
            "complete_when": item.get("completion_evidence"),
        }
        for item in bank["questions"]
    ]


def _compact_template(template: str) -> str:
    """Keep structure and composition rules without the long extension notes."""
    start = template.find("## Required structure")
    end = template.find("## Interview readiness and drafting")
    if start >= 0 and end > start:
        return template[start:end].strip()
    return template[:7000]


def _coverage_decisions(plan: ModelInterviewPlan) -> dict[str, CoverageDecision]:
    return {
        key: CoverageDecision.model_validate(value)
        for key, value in plan.coverage.model_dump(by_alias=True).items()
    }


def _dedupe_questions(plan: ModelInterviewPlan) -> ModelInterviewPlan:
    """Remove exact prompt repeats while allowing multiple decisions per coverage area."""
    seen: set[tuple[str, str]] = set()
    questions: list[PlannedQuestion] = []
    for question in plan.questions:
        key = (question.coverage_id, " ".join(question.prompt.casefold().split()))
        if key in seen:
            log.warning(
                "Model repeated an authoring question for %s; keeping the first",
                question.coverage_id,
            )
            continue
        seen.add(key)
        questions.append(question)
    if len(questions) == len(plan.questions):
        return plan
    return plan.model_copy(update={"questions": questions})


def _reconcile_question_coverage(plan: ModelInterviewPlan) -> ModelInterviewPlan:
    """Resolve a common structured-output contradiction without dropping the plan.

    A question itself is evidence that the associated decision is not fully
    resolved. Some providers still label that same coverage as covered or not
    material. Preserve the question and downgrade the decision to partial or
    missing so validation and the UI describe one coherent state.
    """
    decisions = _coverage_decisions(plan)
    changed = False
    for question in plan.questions:
        decision = decisions.get(question.coverage_id)
        if decision is None or decision.status not in {"covered", "not_material"}:
            continue
        decision.status = "partial" if (decision.resolved_value or "").strip() else "missing"
        decision.confidence = min(decision.confidence, 0.75)
        changed = True
        log.warning(
            "Model asked %s while marking it resolved; treating it as %s",
            question.coverage_id,
            decision.status,
        )
    if not changed:
        return plan
    return plan.model_copy(
        update={
            "coverage": CoverageMap.model_validate({
                key: decision.model_dump()
                for key, decision in decisions.items()
            })
        }
    )


def _normalized_options(question: PlannedQuestion) -> list[dict]:
    """Make scope choices explicit about which side of the boundary they set."""
    options = [option.model_dump() for option in question.options]
    if question.coverage_id != "P-Q7" or question.response_type != "multi_select":
        return options
    exclusion = re.compile(
        r"(?:^no\b|\b(?:exclude|excluded|not include|out of scope|without)\b)",
        re.IGNORECASE,
    )
    for option in options:
        label = str(option.get("label") or "").strip()
        value = str(option.get("value") or "").strip()
        if re.match(r"^(?:include|exclude)\s+[—:-]", label, re.IGNORECASE):
            continue
        boundary = "Exclude" if exclusion.search(f"{label} {value}") else "Include"
        option["label"] = f"{boundary} — {label}"
    return options


def _validate_plan(plan: ModelInterviewPlan, bank: dict, payload: dict) -> None:
    bank_by_id = {str(item["id"]): item for item in bank["questions"]}
    decisions = _coverage_decisions(plan)
    if set(decisions) != set(bank_by_id):
        raise ValueError("Model coverage must contain every question-bank ID exactly once.")

    confirmed = {
        str(item.get("coverage_id") or item.get("id"))
        for item in payload.get("interview") or []
        if item.get("state") == "confirmed"
    }
    for coverage_id, decision in decisions.items():
        bank_item = bank_by_id[coverage_id]
        if bank_item.get("applicability") == "always" and decision.status == "not_material":
            raise ValueError(f"Required coverage {coverage_id} cannot be not_material.")
        if decision.status == "covered" and not (decision.resolved_value or "").strip():
            raise ValueError(f"Covered area {coverage_id} requires a resolved_value.")
    for question in plan.questions:
        if question.coverage_id not in bank_by_id:
            raise ValueError(f"Unknown coverage ID {question.coverage_id}.")
        if question.coverage_id in confirmed:
            raise ValueError(f"Already confirmed coverage {question.coverage_id} was asked again.")
        if decisions[question.coverage_id].status in {"covered", "not_material"}:
            raise ValueError(f"Resolved coverage {question.coverage_id} was asked again.")
        if question.response_type in {"single_select", "multi_select"}:
            if not 2 <= len(question.options) <= 4:
                raise ValueError("Choice questions require two to five contextual options.")
            values = [option.value for option in question.options]
            if len(values) != len(set(values)):
                raise ValueError("Choice values must be unique.")
        elif question.options:
            raise ValueError("Textarea questions cannot include options.")


def _source_records(payload: dict) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    feature = str(payload.get("feature_name") or "<feature>")
    checkpoint = f".speed/features/{feature}/authoring-prd.json"
    description = str((payload.get("intake") or {}).get("feature_description") or "").strip()
    if description:
        records.append({
            "id": "intake:feature-description",
            "path": checkpoint,
            "excerpt": description[:500],
        })
    for answer in _confirmed_answers(payload):
        records.append({
            "id": f"interview:{answer['coverage_id']}",
            "path": checkpoint,
            "excerpt": answer["answer"][:500],
        })
    return records


def _question_instance_id(questions: list[PlannedQuestion], index: int) -> str:
    """Give repeated coverage questions stable, unique persisted IDs."""
    coverage_id = questions[index].coverage_id
    matching = [
        position for position, question in enumerate(questions)
        if question.coverage_id == coverage_id
    ]
    if len(matching) == 1:
        return coverage_id
    return f"{coverage_id}-{matching.index(index) + 1}"


def _normalize(
    plan: ModelInterviewPlan,
    bank: dict,
    payload: dict,
    model: str,
) -> dict:
    bank_by_id = {str(item["id"]): item for item in bank["questions"]}
    confirmed = {
        str(item.get("coverage_id") or item.get("id"))
        for item in payload.get("interview") or []
        if item.get("state") == "confirmed"
    }
    coverage: dict[str, dict] = {}
    for coverage_id, decision in _coverage_decisions(plan).items():
        status = decision.status
        coverage[coverage_id] = {
            "coverage": bank_by_id[coverage_id].get("coverage"),
            "confidence": 1.0 if coverage_id in confirmed else round(decision.confidence, 2),
            "confidence_label": (
                "confirmed"
                if coverage_id in confirmed
                else "evidence_backed"
                if status == "covered"
                else "inferred"
                if status == "partial" and bool((decision.resolved_value or "").strip())
                else "not_material"
                if status == "not_material"
                else "unresolved"
            ),
            "impact": "high" if bank_by_id[coverage_id].get("applicability") == "always" else "medium",
            "basis": [decision.rationale],
            "rationale": decision.rationale,
            "resolved_value": decision.resolved_value,
            "question_value": round(1 - decision.confidence, 3),
        }

    source_records = _source_records(payload)
    questions: list[dict] = []
    for index, item in enumerate(plan.questions):
        bank_item = bank_by_id[item.coverage_id]
        question_id = _question_instance_id(plan.questions, index)
        coverage[item.coverage_id]["confidence_label"] = "unresolved"
        coverage[item.coverage_id]["resolved_value"] = None
        suggested = (item.suggested_answer or "").strip() or None
        if item.suggestion_confidence == "missing":
            suggested = None
        sources = source_records if suggested else []
        suggestion = {
            "id": f"model-{question_id.lower()}-{payload.get('revision', 0)}",
            "answer": suggested,
            "confidence": item.suggestion_confidence if suggested else "missing",
            "accept_ready": bool(suggested and item.suggestion_confidence == "grounded"),
            "sources": sources,
            "gaps": [item.suggestion_gap] if item.suggestion_gap else [],
            "created_at": _now(),
            "rejected": False,
        }
        options = _normalized_options(item)
        control_prompt = (
            "Select every inclusion and exclusion that should define V1."
            if item.coverage_id == "P-Q7" and item.response_type == "multi_select"
            else "Choose the closest answer or write your own."
            if item.response_type in {"single_select", "multi_select"}
            else "Review the suggested response, then submit your answer."
        )
        response_control = {
            "id": f"model-answer-{question_id.lower()}",
            "input_type": item.response_type,
            "prompt": control_prompt,
            "initial_value": suggested or "",
            "options": options,
            "submit_action": "answer",
            "allow_other": item.response_type in {"single_select", "multi_select"},
        }
        questions.append({
            **bank_item,
            "id": question_id,
            "coverage_id": item.coverage_id,
            "prompt": item.prompt,
            "purpose": bank_item.get("purpose"),
            "evidence": (
                f"{bank_item.get('evidence')}. Planner assessment: "
                f"{coverage[item.coverage_id]['rationale']}"
            ),
            "response_control": response_control,
            "suggestion": suggestion,
        })

    return {
        "mode": "model",
        "planner_version": PLANNER_VERSION,
        "model": model,
        "feature_title": plan.feature_title,
        "generated_at": _now(),
        "analysis_summary": plan.analysis_summary,
        "prd_size": plan.prd_size,
        "coverage": coverage,
        "questions": questions,
        "composition": plan.composition.model_dump(),
        "fallback_reason": None,
    }


def _dedupe_compact_questions(plan: CompactInterviewPlan) -> CompactInterviewPlan:
    seen: set[tuple[str, str]] = set()
    questions: list[PlannedQuestion] = []
    for question in plan.questions:
        key = (question.coverage_id, " ".join(question.prompt.casefold().split()))
        if key in seen:
            log.warning(
                "Compact planner repeated a question for %s; keeping the first",
                question.coverage_id,
            )
            continue
        seen.add(key)
        questions.append(question)
    return plan if len(questions) == len(plan.questions) else plan.model_copy(
        update={"questions": questions}
    )


def _reconcile_compact_plan(plan: CompactInterviewPlan) -> CompactInterviewPlan:
    """Prefer an explicit question when the compact result also marks it resolved.

    Structured-output providers occasionally include the same coverage ID in
    both arrays. Asking the author proves the decision is not actually settled,
    so retaining the question is safer than discarding the full model result.
    """
    question_ids = {question.coverage_id for question in plan.questions}
    resolved = [
        item
        for item in plan.resolved_coverage
        if item.coverage_id not in question_ids
    ]
    if len(resolved) == len(plan.resolved_coverage):
        return plan
    log.warning(
        "Compact planner both resolved and asked coverage; keeping questions for %s",
        ", ".join(sorted(
            question_ids
            & {item.coverage_id for item in plan.resolved_coverage}
        )),
    )
    return plan.model_copy(update={"resolved_coverage": resolved})


def _normalize_compact_coverage_ids(
    plan: CompactInterviewPlan, bank: dict
) -> CompactInterviewPlan:
    """Accept the bank's semantic coverage labels as aliases for stable IDs."""
    aliases = {
        str(item.get("coverage") or ""): str(item["id"])
        for item in bank["questions"]
        if item.get("coverage")
    }

    def stable_id(value: str) -> str:
        return aliases.get(value, value)

    resolved = [
        item.model_copy(update={"coverage_id": stable_id(item.coverage_id)})
        for item in plan.resolved_coverage
    ]
    questions = [
        item.model_copy(update={"coverage_id": stable_id(item.coverage_id)})
        for item in plan.questions
    ]
    return plan.model_copy(update={
        "resolved_coverage": resolved,
        "questions": questions,
    })


def _validate_compact_plan(
    plan: CompactInterviewPlan,
    bank: dict,
    payload: dict,
    artifact_type: str = "prd",
) -> None:
    bank_by_id = {str(item["id"]): item for item in bank["questions"]}
    resolved_ids = [item.coverage_id for item in plan.resolved_coverage]
    question_ids = [item.coverage_id for item in plan.questions]
    if len(resolved_ids) != len(set(resolved_ids)):
        raise ValueError("Compact planner returned duplicate resolved coverage IDs.")
    unknown = (set(resolved_ids) | set(question_ids)) - set(bank_by_id)
    if unknown:
        raise ValueError(f"Compact planner returned unknown coverage IDs: {sorted(unknown)}")
    if set(resolved_ids) & set(question_ids):
        raise ValueError("Compact planner cannot both resolve and ask the same coverage area.")

    confirmed = {
        str(item.get("coverage_id") or item.get("id"))
        for item in payload.get("interview") or []
        if item.get("state") == "confirmed"
    }
    if confirmed & set(question_ids):
        raise ValueError("Compact planner re-asked already confirmed coverage.")
    required = {
        coverage_id
        for coverage_id, item in bank_by_id.items()
        if item.get("applicability") == "always" or artifact_type in {"design", "rfc"}
    }
    missing_required = required - confirmed - set(resolved_ids) - set(question_ids)
    if missing_required:
        raise ValueError(
            "Compact planner omitted required coverage: "
            + ", ".join(sorted(missing_required))
        )

    for question in plan.questions:
        if question.response_type in {"single_select", "multi_select"}:
            if not 2 <= len(question.options) <= 4:
                raise ValueError("Compact choice questions require two to four options.")
        elif question.options:
            raise ValueError("Compact textarea questions cannot include options.")


def _normalize_compact(
    plan: CompactInterviewPlan,
    bank: dict,
    payload: dict,
    model: str,
) -> dict:
    """Expand the compact model response into the stable helper contract."""
    bank_by_id = {str(item["id"]): item for item in bank["questions"]}
    confirmed_answers: dict[str, str] = {}
    for item in payload.get("interview") or []:
        if item.get("state") != "confirmed" or not item.get("answer"):
            continue
        coverage_id = str(item.get("coverage_id") or item.get("id") or "")
        answer = str(item.get("answer") or "").strip()
        previous = confirmed_answers.get(coverage_id, "")
        confirmed_answers[coverage_id] = (
            f"{previous}\n\n{answer}" if previous and answer not in previous else answer or previous
        )
    resolved = {item.coverage_id: item for item in plan.resolved_coverage}
    asked = {item.coverage_id for item in plan.questions}
    coverage: dict[str, dict] = {}
    for coverage_id, bank_item in bank_by_id.items():
        if coverage_id in confirmed_answers:
            confidence = 1.0
            label = "confirmed"
            value = confirmed_answers[coverage_id]
            rationale = "Confirmed directly by the author."
        elif coverage_id in resolved:
            confidence = round(resolved[coverage_id].confidence, 2)
            label = "evidence_backed"
            value = resolved[coverage_id].resolved_value
            rationale = "Resolved from the supplied author or repository context."
        elif coverage_id in asked:
            coverage_questions = [
                question for question in plan.questions
                if question.coverage_id == coverage_id
            ]
            suggestion = next(
                (
                    str(question.suggested_answer or "").strip()
                    for question in coverage_questions
                    if str(question.suggested_answer or "").strip()
                ),
                "",
            )
            confidence = 0.6 if suggestion else 0.2
            label = "unresolved"
            value = None
            rationale = (
                next(
                    (
                        question.suggestion_gap
                        for question in coverage_questions
                        if question.suggestion_gap
                    ),
                    None,
                )
                or "A material product decision still requires author confirmation."
            )
        else:
            # Omission is not affirmative evidence. Keep conditional coverage
            # out of the document, but do not record model silence as certainty.
            confidence = 0.5
            label = "not_material"
            value = None
            rationale = (
                "The planner did not identify this conditional coverage as material."
            )
        coverage[coverage_id] = {
            "coverage": bank_item.get("coverage"),
            "confidence": confidence,
            "confidence_label": label,
            "impact": "high" if bank_item.get("applicability") == "always" else "medium",
            "basis": [rationale],
            "rationale": rationale,
            "resolved_value": value,
            "question_value": round(1 - confidence, 3),
        }

    source_records = _source_records(payload)
    questions: list[dict] = []
    for index, item in enumerate(plan.questions):
        bank_item = bank_by_id[item.coverage_id]
        question_id = _question_instance_id(plan.questions, index)
        suggested = (item.suggested_answer or "").strip() or None
        if item.suggestion_confidence == "missing":
            suggested = None
        suggestion = {
            "id": f"model-{question_id.lower()}-{payload.get('revision', 0)}",
            "answer": suggested,
            "confidence": item.suggestion_confidence if suggested else "missing",
            "accept_ready": bool(suggested and item.suggestion_confidence == "grounded"),
            "sources": source_records if suggested else [],
            "gaps": [item.suggestion_gap] if item.suggestion_gap else [],
            "created_at": _now(),
            "rejected": False,
        }
        control_prompt = (
            "Select every inclusion and exclusion that should define V1."
            if item.coverage_id == "P-Q7" and item.response_type == "multi_select"
            else "Choose the closest answer or write your own."
            if item.response_type in {"single_select", "multi_select"}
            else "Review the suggested response, then submit your answer."
        )
        questions.append({
            **bank_item,
            "id": question_id,
            "coverage_id": item.coverage_id,
            "prompt": item.prompt,
            "purpose": bank_item.get("purpose"),
            "evidence": bank_item.get("evidence"),
            "response_control": {
                "id": f"model-answer-{question_id.lower()}",
                "input_type": item.response_type,
                "prompt": control_prompt,
                "initial_value": suggested or "",
                "options": _normalized_options(item),
                "submit_action": "answer",
                "allow_other": item.response_type in {"single_select", "multi_select"},
            },
            "suggestion": suggestion,
        })

    return {
        "mode": "model",
        "planner_version": PLANNER_VERSION,
        "model": model,
        "feature_title": plan.feature_title,
        "generated_at": _now(),
        "analysis_summary": plan.analysis_summary,
        "prd_size": plan.prd_size,
        "coverage": coverage,
        "questions": questions,
        "composition": {
            "requirements": [],
            "scope": None,
            "guardrails": [],
            "success": None,
        },
        "fallback_reason": None,
        "optimization": "complete-template-intake-v1",
    }


def fallback_plan(
    reason: str, model: str | None = None, artifact_type: str = "prd"
) -> dict:
    return {
        "mode": "fallback",
        "planner_version": planner_version_for(artifact_type),
        "model": model,
        "generated_at": _now(),
        "analysis_summary": "The model planner was unavailable; deterministic fallback planning is active.",
        "prd_size": "Small",
        "coverage": {},
        "questions": [],
        "composition": {
            "requirements": [],
            "scope": None,
            "guardrails": [],
            "success": None,
        },
        "fallback_reason": reason[:600],
    }


def _downstream_context(project_root: Path, payload: dict, artifact_type: str) -> str:
    """Read only the immutable upstream artifacts pinned by the helper."""
    chunks: list[str] = []
    for upstream_type, record in (payload.get("upstream") or {}).items():
        if not isinstance(record, dict) or not record.get("path"):
            continue
        raw_content = str(record.get("content") or "")
        if not raw_content:
            path = project_root / str(record["path"])
            try:
                raw_content = path.read_text(encoding="utf-8")
            except OSError:
                raw_content = ""
        expected_hash = str(record.get("sha256") or "")
        if expected_hash and hashlib.sha256(raw_content.encode()).hexdigest() != expected_hash:
            log.warning(
                "Ignoring %s upstream context because it does not match pinned hash %s",
                upstream_type,
                expected_hash,
            )
            continue
        content = raw_content[:14000]
        if content.strip():
            chunks.append(
                f"PUBLISHED {str(upstream_type).upper()} "
                f"({expected_hash or 'hash unavailable'})\n{content}"
            )
    repository = _project_context(
        project_root, str(payload.get("feature_name") or "")
    )
    chunks.append(f"FIXED REPOSITORY CONTEXT\n{repository}")
    return "\n\n".join(chunks)


def _downstream_system_prompt(artifact_type: str) -> str:
    label = "Design specification" if artifact_type == "design" else "technical RFC"
    return f"""You plan a concise guided interview for a {label}.
Use the published upstream artifacts as authoritative context. Resolve a coverage area
without asking only when the upstream documents or fixed repository context contain a
specific, implementation-ready answer. Ask every remaining material decision exactly
once. Do not invent repository capabilities. Questions must be contextual, answerable,
and use textarea unless two to four genuinely distinct choices improve the decision.
Return the requested structured object. `feature_title` is the product feature title;
preserve the supplied title. All question-bank coverage IDs are required: each one must
appear either in resolved_coverage or questions. Keep answers proportional to the change."""


def _shared_normalize_compact(
    plan: CompactInterviewPlan,
    bank: dict,
    payload: dict,
    model: str,
    artifact_type: str = "prd",
) -> dict:
    """Use the exact normalizer packaged with every projected draft skill."""
    contract_path = (
        _reference_paths()[0].parent.parent / "scripts" / "planner_contract.py"
    )
    module_name = "workbench_draft_planner_contract"
    module = sys.modules.get(module_name)
    if module is None:
        spec = importlib.util.spec_from_file_location(module_name, contract_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Could not load planner contract at {contract_path}.")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    return module.normalize_compact_plan(
        plan.model_dump(),
        bank,
        payload,
        model=model,
        artifact_type=artifact_type,
        planner_version=planner_version_for(artifact_type),
    )


def plan_authoring(
    project_root: str | Path,
    payload: dict,
    conn: sqlite3.Connection | None = None,
) -> dict:
    """Create a validated model plan, returning an explicit fallback on failure."""
    planning_started = time.monotonic()
    root = Path(project_root).resolve()
    artifact_type = str(payload.get("artifact_type") or "prd").lower()
    if artifact_type not in {"prd", "design", "rfc"}:
        return fallback_plan(
            f"Unsupported guided artifact type: {artifact_type}.",
            artifact_type=artifact_type,
        )
    question_path, template_path = _reference_paths(artifact_type)
    bank = json.loads(question_path.read_text(encoding="utf-8"))
    template = template_path.read_text(encoding="utf-8") if artifact_type == "prd" else ""
    planner_prompt = (
        _planner_prompt_path().read_text(encoding="utf-8")
        if artifact_type == "prd"
        else _downstream_system_prompt(artifact_type)
    )
    model = ""
    try:
        model = _select_model(root)
        intake = payload.get("intake") or {}
        author_title = str(intake.get("feature_title") or "").strip()
        routing_slug = str(payload.get("feature_name") or "")
        description = str(intake.get("feature_description") or "")
        confirmed = _confirmed_answers(payload)
        surfaced = [
            {
                "question_id": str(item.get("id") or ""),
                "coverage_id": str(item.get("coverage_id") or item.get("id") or ""),
                "question": str(item.get("prompt") or ""),
                "state": str(item.get("state") or ""),
            }
            for item in payload.get("interview") or []
            if item.get("id")
        ]
        repository_context = (
            _project_context(root, str(payload.get("feature_name") or ""))
            if artifact_type == "prd"
            else _downstream_context(root, payload, artifact_type)
        )
        contract_label = (
            f"PRD TEMPLATE AND COMPOSITION CONTRACT\n{_compact_template(template)}\n\n"
            if artifact_type == "prd"
            else f"TARGET ARTIFACT\n{artifact_type.upper()}\n\n"
        )
        messages = [
            {
                "role": "system",
                "content": planner_prompt,
            },
            {
                "role": "user",
                "content": (
                    f"EXPLICIT AUTHOR TITLE\n{author_title or '[none; derive from the description]'}\n\n"
                    f"ROUTING SLUG (identifier only; do not treat as a title)\n{routing_slug}\n\n"
                    f"AUTHOR DESCRIPTION\n{description or '[none]'}\n\n"
                    f"CONFIRMED INTERVIEW ANSWERS\n{json.dumps(confirmed, indent=2)}\n\n"
                    f"ALREADY SURFACED QUESTIONS\n{json.dumps(surfaced, indent=2)}\n\n"
                    f"REPOSITORY CONTEXT\n{repository_context}\n\n"
                    f"{contract_label}"
                    f"COVERAGE ROUTING CONTRACT\n"
                    f"{json.dumps(_compact_bank(bank, artifact_type), indent=2)}"
                ),
            },
        ]
        model_started = time.monotonic()
        result = llm_complete(
            messages=messages,
            response_model=CompactInterviewPlan,
            model=model,
            temperature=0.1,
            # CompactInterviewPlan is intentionally small. Staying below the
            # CLI's high-effort threshold keeps interactive intake responsive.
            max_tokens=4096,
            purpose=f"guided_{artifact_type}_completeness_planning",
            spec_path=f"specs/{payload.get('feature_name')}/{artifact_type}.md",
            project_root=root,
            conn=conn,
            timeout=PLANNING_TIMEOUT_SECONDS,
        )
        model_elapsed_ms = int((time.monotonic() - model_started) * 1000)
        if isinstance(result, ModelInterviewPlan):
            # Compatibility for callers/tests that still supply the former
            # full planning object while migrating to the compact contract.
            result = _reconcile_question_coverage(_dedupe_questions(result))
            _validate_plan(result, bank, payload)
            normalized = _normalize(result, bank, payload, model)
        else:
            result = _normalize_compact_coverage_ids(result, bank)
            result = _reconcile_compact_plan(_dedupe_compact_questions(result))
            _validate_compact_plan(result, bank, payload, artifact_type)
            normalized = _shared_normalize_compact(
                result, bank, payload, model, artifact_type
            )
        normalized["planner_version"] = planner_version_for(artifact_type)
        normalized["timing"] = {
            "model_ms": model_elapsed_ms,
            "total_ms": int((time.monotonic() - planning_started) * 1000),
        }
        log.info(
            "Guided %s planning completed with %s in %dms (%d questions)",
            artifact_type.upper(),
            model,
            normalized["timing"]["total_ms"],
            len(normalized["questions"]),
        )
        return normalized
    except Exception as exc:
        log.warning("Model-backed authoring plan failed; using fallback", exc_info=True)
        if isinstance(exc, TimeoutError) or type(exc).__name__ == "TimeoutExpired":
            detail = f"Model request timed out after {PLANNING_TIMEOUT_SECONDS} seconds."
        else:
            detail = f"{type(exc).__name__}: {exc}"
        return fallback_plan(detail, model or None, artifact_type)


def revise_artifact_from_comments(
    project_root: str | Path,
    payload: dict,
    comments: object,
    current_content: str,
    conn: sqlite3.Connection | None = None,
) -> dict:
    """Reconsider affected artifact sections using reviewer guidance and context.

    Unlike interview planning, review regeneration has no deterministic prose
    fallback: appending a review instruction to the artifact misrepresents the
    instruction as product content. A failed model call therefore leaves the
    existing artifact untouched so the reviewer can retry.
    """
    root = Path(project_root).resolve()
    if not isinstance(comments, list) or not comments:
        raise ValueError("Add at least one review comment before regenerating.")

    normalized_comments: list[dict[str, object]] = []
    requested_titles: list[str] = []
    has_global_feedback = False
    for item in comments:
        if not isinstance(item, dict):
            raise ValueError("Each review comment must include revision guidance.")
        title = str(item.get("section_title") or "").strip()
        comment = str(item.get("comment") or "").strip()
        if len(comment) < 3:
            raise ValueError("Each review comment must include meaningful guidance.")
        is_global = title in {"", "__document__"}
        has_global_feedback = has_global_feedback or is_global
        normalized = {
            "scope": "document" if is_global else "selection" if item.get("selected_text") else "section",
            "section_title": None if is_global else title,
            "comment": comment,
        }
        if item.get("selected_text"):
            normalized["selected_text"] = str(item["selected_text"])[:2000]
            normalized["anchor_revision"] = item.get("anchor_revision")
        normalized_comments.append(normalized)
        if not is_global and title not in requested_titles:
            requested_titles.append(title)

    artifact_type = str(payload.get("artifact_type") or "prd")
    artifact_label = {
        "prd": "product requirements document",
        "design": "design specification",
        "rfc": "technical RFC",
    }.get(artifact_type, "artifact")
    _, template_path = _reference_paths()
    template = (
        _compact_template(template_path.read_text(encoding="utf-8"))
        if artifact_type == "prd"
        else "Preserve every existing section heading and its current order."
    )
    model = _select_model(root)
    title = str(payload.get("feature_title") or payload.get("feature_name") or "")
    description = str((payload.get("intake") or {}).get("feature_description") or "")
    messages = [
        {
            "role": "system",
            "content": (
                f"You revise an existing {artifact_label} from explicit reviewer "
                "comments. Treat each comment as an instruction to reconsider and rewrite the "
                "complete affected section, never as prose to append verbatim. A document-scoped "
                "comment may affect one or more sections; choose only the sections genuinely needed. "
                "A selected_text quote is anchor context and must not be copied as an instruction. Use the existing "
                f"{artifact_label}, author inputs, confirmed interview answers, repository context, and the "
                "artifact contract together. Return exactly one complete replacement body for every explicitly "
                "commented section; when document-scoped feedback exists, you may also return the minimal "
                "additional affected sections. Do not include the section's ## "
                "heading in revised_body. Preserve the required structure for that section. For any "
                "table-based section, return only the Markdown table with the exact existing headers. "
                "Integrate supported "
                "reviewer-provided facts naturally into the appropriate table row, reconcile them "
                "with existing content, and do not invent unrelated requirements, metrics, owners, "
                "or implementation details."
            ),
        },
        {
            "role": "user",
            "content": (
                f"FEATURE TITLE\n{title}\n\n"
                f"AUTHOR DESCRIPTION\n{description or '[none]'}\n\n"
                f"CONFIRMED INTERVIEW ANSWERS\n{json.dumps(_confirmed_answers(payload), indent=2)}\n\n"
                f"REVIEW COMMENTS\n{json.dumps(normalized_comments, indent=2)}\n\n"
                f"CURRENT {artifact_label.upper()}\n{current_content[:30000]}\n\n"
                f"REPOSITORY CONTEXT\n{_project_context(root, str(payload.get('feature_name') or ''))}\n\n"
                f"ARTIFACT CONTRACT\n{template}"
            ),
        },
    ]
    try:
        result = llm_complete(
            messages=messages,
            response_model=PrdReviewRevision,
            model=model,
            temperature=0.1,
            max_tokens=6000,
            purpose=f"guided_{artifact_type}_review_regeneration",
            spec_path=f"specs/{payload.get('feature_name')}/{artifact_type}.md",
            project_root=root,
            conn=conn,
        )
    except Exception as exc:
        log.warning("Model-backed artifact review regeneration failed", exc_info=True)
        raise RuntimeError(
            f"The configured model could not reconsider the {artifact_label} comments. "
            "The existing draft was not changed; retry when the model is available. "
            f"({type(exc).__name__}: {exc})"
        ) from exc

    revisions: dict[str, str] = {}
    for section in result.sections:
        section_title = section.section_title.strip()
        body = section.revised_body.strip()
        if section_title in revisions:
            raise ValueError(f"The model returned duplicate revisions for '{section_title}'.")
        if re.search(r"^##\s+", body, re.MULTILINE):
            raise ValueError(
                f"The model returned a section heading inside the '{section_title}' body."
            )
        revisions[section_title] = body

    valid_titles = {
        str(section.get("title"))
        for section in payload.get("sections") or []
        if isinstance(section, dict) and section.get("title")
    }
    if not valid_titles:
        valid_titles = set(requested_titles)
    missing = sorted(set(requested_titles) - set(revisions))
    extra = sorted(set(revisions) - valid_titles)
    if missing or extra or (has_global_feedback and not revisions):
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("unexpected " + ", ".join(extra))
        if has_global_feedback and not revisions:
            details.append("no section selected for document feedback")
        raise ValueError(
            "The model did not return the required affected artifact sections: "
            + "; ".join(details)
            + "."
        )

    return {
        "model": model,
        "analysis_summary": result.analysis_summary,
        "sections": [
            {"section_title": section_title, "revised_body": revisions[section_title]}
            for section_title in revisions
        ],
    }


def revise_prd_from_comments(
    project_root: str | Path,
    payload: dict,
    comments: object,
    current_content: str,
    conn: sqlite3.Connection | None = None,
) -> dict:
    """Backward-compatible name for the generalized review operation."""
    return revise_artifact_from_comments(
        project_root, payload, comments, current_content, conn=conn
    )
