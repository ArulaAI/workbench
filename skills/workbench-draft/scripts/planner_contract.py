"""Portable normalization for model-generated guided PRD interview plans.

This module deliberately depends only on the Python standard library. The
dashboard planner and any harness running the projected skill both pass the
same compact semantic plan through this contract before ``draft.py`` persists
it, so question IDs, response controls, coverage, and suggestions cannot drift
between surfaces.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any


PLANNER_VERSION = "model-prd-v5"
DOWNSTREAM_PLANNER_VERSION = "model-downstream-v1"


class PlannerContractError(ValueError):
    """The host-generated compact plan does not satisfy the shared contract."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _confirmed_answers(payload: dict[str, Any]) -> dict[str, str]:
    confirmed: dict[str, str] = {}
    raw_answers = payload.get("answers")
    if isinstance(raw_answers, dict):
        records = raw_answers.values()
    else:
        records = payload.get("interview") or []
    for item in records:
        if not isinstance(item, dict) or item.get("state") != "confirmed":
            continue
        coverage_id = _clean(item.get("coverage_id") or item.get("id"))
        answer = _clean(item.get("answer"))
        if not coverage_id or not answer:
            continue
        previous = confirmed.get(coverage_id, "")
        confirmed[coverage_id] = (
            f"{previous}\n\n{answer}"
            if previous and answer not in previous
            else answer or previous
        )
    return confirmed


def _source_records(
    payload: dict[str, Any], artifact_type: str = "prd"
) -> list[dict[str, str]]:
    feature = _clean(payload.get("feature_name")) or "<feature>"
    checkpoint = f".speed/features/{feature}/authoring-{artifact_type}.json"
    records: list[dict[str, str]] = []
    description = _clean((payload.get("intake") or {}).get("feature_description"))
    if description:
        records.append({
            "id": "intake:feature-description",
            "path": checkpoint,
            "excerpt": description[:500],
        })
    for coverage_id, answer in _confirmed_answers(payload).items():
        records.append({
            "id": f"interview:{coverage_id}",
            "path": checkpoint,
            "excerpt": answer[:500],
        })
    for upstream_type, upstream in (payload.get("upstream") or {}).items():
        if not isinstance(upstream, dict):
            continue
        path = _clean(upstream.get("path"))
        digest = _clean(upstream.get("sha256"))
        if path and digest:
            records.append({
                "id": f"published-upstream:{upstream_type}",
                "path": path,
                "excerpt": f"Pinned published SHA-256: {digest}",
            })
    return records


def _normalize_options(question: dict[str, Any]) -> list[dict[str, Any]]:
    options = []
    for item in question.get("options") or []:
        if not isinstance(item, dict):
            raise PlannerContractError("Every compact question option must be an object.")
        value = _clean(item.get("value"))
        label = _clean(item.get("label"))
        if not value or not label:
            raise PlannerContractError("Every compact question option needs a label and value.")
        options.append({
            "value": value,
            "label": label,
            "recommended": bool(item.get("recommended", False)),
        })
    if question.get("coverage_id") != "P-Q7" or question.get("response_type") != "multi_select":
        return options
    exclusion = re.compile(
        r"(?:^no\b|\b(?:exclude|excluded|not include|out of scope|without)\b)",
        re.IGNORECASE,
    )
    for option in options:
        if re.match(r"^(?:include|exclude)\s*[:\-]", option["label"], re.IGNORECASE):
            continue
        boundary = "Exclude" if exclusion.search(f"{option['label']} {option['value']}") else "Include"
        option["label"] = f"{boundary} — {option['label']}"
    return options


def normalize_compact_plan(
    compact_plan: dict[str, Any],
    bank: dict[str, Any],
    payload: dict[str, Any],
    *,
    model: str = "host-model",
    generated_at: str | None = None,
    artifact_type: str = "prd",
    planner_version: str | None = None,
) -> dict[str, Any]:
    """Validate and expand a compact plan into ``draft.py``'s stable contract."""
    if not isinstance(compact_plan, dict):
        raise PlannerContractError("The compact interview plan must be an object.")
    title = _clean(compact_plan.get("feature_title"))
    summary = _clean(compact_plan.get("analysis_summary"))
    size = compact_plan.get("prd_size", "Small")
    if not 3 <= len(title) <= 80:
        raise PlannerContractError("The compact plan needs a 3 to 80 character feature title.")
    if len(summary) < 12:
        raise PlannerContractError("The compact plan needs an analysis summary.")
    if size not in {"Small", "Standard", "Initiative"}:
        raise PlannerContractError("The compact plan has an invalid proportionality size.")

    bank_items = bank.get("questions") if isinstance(bank, dict) else None
    if not isinstance(bank_items, list):
        raise PlannerContractError("The PRD question bank is malformed.")
    bank_by_id = {str(item["id"]): item for item in bank_items}
    aliases = {
        _clean(item.get("coverage")): coverage_id
        for coverage_id, item in bank_by_id.items()
        if _clean(item.get("coverage"))
    }

    def stable_id(value: object) -> str:
        cleaned = _clean(value)
        return aliases.get(cleaned, cleaned)

    resolved: dict[str, dict[str, Any]] = {}
    raw_resolved = compact_plan.get("resolved_coverage") or []
    if not isinstance(raw_resolved, list):
        raise PlannerContractError("resolved_coverage must be a list.")
    for item in raw_resolved:
        if not isinstance(item, dict):
            raise PlannerContractError("Every resolved coverage item must be an object.")
        coverage_id = stable_id(item.get("coverage_id"))
        value = _clean(item.get("resolved_value"))
        if coverage_id not in bank_by_id or not value:
            raise PlannerContractError("Resolved coverage needs a known ID and meaningful value.")
        if coverage_id in resolved:
            raise PlannerContractError("The compact plan repeats a resolved coverage ID.")
        confidence = item.get("confidence", 0.85)
        if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise PlannerContractError("Resolved coverage confidence must be between 0 and 1.")
        resolved[coverage_id] = {**item, "coverage_id": coverage_id, "resolved_value": value}

    raw_questions = compact_plan.get("questions") or []
    if not isinstance(raw_questions, list):
        raise PlannerContractError("The compact plan questions must be a list.")
    questions: list[dict[str, Any]] = []
    seen_prompts: set[tuple[str, str]] = set()
    for item in raw_questions:
        if not isinstance(item, dict):
            raise PlannerContractError("Every compact question must be an object.")
        coverage_id = stable_id(item.get("coverage_id"))
        prompt = _clean(item.get("prompt"))
        response_type = item.get("response_type")
        if coverage_id not in bank_by_id:
            raise PlannerContractError(f"Unknown coverage ID {coverage_id}.")
        if len(prompt) < 12:
            raise PlannerContractError("Every compact question needs a contextual prompt.")
        if response_type not in {"single_select", "multi_select", "textarea"}:
            raise PlannerContractError("A compact question has an invalid response type.")
        normalized = {**item, "coverage_id": coverage_id, "prompt": prompt}
        normalized["options"] = _normalize_options(normalized)
        if response_type in {"single_select", "multi_select"}:
            if not 2 <= len(normalized["options"]) <= 4:
                raise PlannerContractError("Choice questions require two to four options.")
            values = [option["value"] for option in normalized["options"]]
            if len(values) != len(set(values)):
                raise PlannerContractError("Choice option values must be unique.")
        elif normalized["options"]:
            raise PlannerContractError("Textarea questions cannot include options.")
        key = (coverage_id, prompt.casefold())
        if key in seen_prompts:
            continue
        seen_prompts.add(key)
        questions.append(normalized)

    asked_ids = {item["coverage_id"] for item in questions}
    for coverage_id in asked_ids:
        resolved.pop(coverage_id, None)
    confirmed = _confirmed_answers(payload)
    if set(confirmed) & asked_ids:
        raise PlannerContractError("The compact plan re-asks already confirmed coverage.")
    required = {
        coverage_id
        for coverage_id, item in bank_by_id.items()
        if item.get("applicability") == "always" or artifact_type in {"design", "rfc"}
    }
    missing_required = required - set(confirmed) - set(resolved) - asked_ids
    if missing_required:
        raise PlannerContractError(
            "The compact plan omitted required coverage: "
            + ", ".join(sorted(missing_required))
        )

    coverage: dict[str, dict[str, Any]] = {}
    for coverage_id, bank_item in bank_by_id.items():
        if coverage_id in confirmed:
            confidence, label = 1.0, "confirmed"
            value = confirmed[coverage_id]
            rationale = "Confirmed directly by the author."
        elif coverage_id in resolved:
            confidence = round(float(resolved[coverage_id].get("confidence", 0.85)), 2)
            label = "evidence_backed"
            value = resolved[coverage_id]["resolved_value"]
            rationale = "Resolved from the supplied author or repository context."
        elif coverage_id in asked_ids:
            matching = [item for item in questions if item["coverage_id"] == coverage_id]
            has_suggestion = any(_clean(item.get("suggested_answer")) for item in matching)
            confidence, label, value = (0.6 if has_suggestion else 0.2), "unresolved", None
            rationale = next(
                (_clean(item.get("suggestion_gap")) for item in matching if _clean(item.get("suggestion_gap"))),
                "A material product decision still requires author confirmation.",
            )
        else:
            confidence, label, value = 0.5, "not_material", None
            rationale = "The planner did not identify this conditional coverage as material."
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

    source_records = _source_records(payload, artifact_type)
    normalized_questions: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    totals: dict[str, int] = {}
    for item in questions:
        totals[item["coverage_id"]] = totals.get(item["coverage_id"], 0) + 1
    revision = payload.get("revision", 0)
    for item in questions:
        coverage_id = item["coverage_id"]
        counts[coverage_id] = counts.get(coverage_id, 0) + 1
        question_id = coverage_id if totals[coverage_id] == 1 else f"{coverage_id}-{counts[coverage_id]}"
        bank_item = bank_by_id[coverage_id]
        suggested = _clean(item.get("suggested_answer")) or None
        suggestion_confidence = item.get("suggestion_confidence", "missing")
        if suggestion_confidence not in {"grounded", "partial", "missing"}:
            raise PlannerContractError("A compact suggestion has an invalid confidence label.")
        if suggestion_confidence == "missing":
            suggested = None
        control_prompt = (
            "Select every inclusion and exclusion that should define V1."
            if coverage_id == "P-Q7" and item["response_type"] == "multi_select"
            else "Choose the closest answer or write your own."
            if item["response_type"] in {"single_select", "multi_select"}
            else "Review the suggested response, then submit your answer."
        )
        normalized_questions.append({
            **bank_item,
            "id": question_id,
            "coverage_id": coverage_id,
            "prompt": item["prompt"],
            "purpose": bank_item.get("purpose"),
            "evidence": bank_item.get("evidence"),
            "response_control": {
                "id": f"model-answer-{question_id.lower()}",
                "input_type": item["response_type"],
                "prompt": control_prompt,
                "initial_value": suggested or "",
                "options": item["options"],
                "submit_action": "answer",
                "allow_other": item["response_type"] in {"single_select", "multi_select"},
            },
            "suggestion": {
                "id": f"model-{question_id.lower()}-{revision}",
                "answer": suggested,
                "confidence": suggestion_confidence if suggested else "missing",
                "accept_ready": bool(suggested and suggestion_confidence == "grounded"),
                "sources": source_records if suggested else [],
                "gaps": [_clean(item.get("suggestion_gap"))] if _clean(item.get("suggestion_gap")) else [],
                "created_at": generated_at or _now(),
                "rejected": False,
            },
        })

    return {
        "mode": "model",
        "planner_version": planner_version or (
            PLANNER_VERSION if artifact_type == "prd" else DOWNSTREAM_PLANNER_VERSION
        ),
        "model": model,
        "feature_title": title,
        "generated_at": generated_at or _now(),
        "analysis_summary": summary,
        "prd_size": size,
        "coverage": coverage,
        "questions": normalized_questions,
        "composition": {
            "requirements": [],
            "scope": None,
            "guardrails": [],
            "success": None,
        },
        "fallback_reason": None,
        "optimization": "complete-template-intake-v1",
    }
