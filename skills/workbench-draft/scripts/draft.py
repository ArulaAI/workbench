#!/usr/bin/env python3
"""Resumable, deterministic Product and Design interviews for Workbench Draft."""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

_SCRIPT_DIR = str(Path(__file__).resolve().parent)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from planner_contract import PlannerContractError, normalize_compact_plan


SKILL = "workbench-draft"
SCHEMA_VERSION = 2
FEATURE_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,48}[a-z0-9])?$")
ZERO_HASH = "0" * 64
INITIAL_REVISION = hashlib.sha256((ZERO_HASH * 3).encode()).hexdigest()[:8]
ARTIFACTS = {
    "prd": {
        "label": "PRD",
        "persona": "Product",
        "question_bank": "prd-questions.json",
        "sections": [
            "Summary", "Problem & Evidence", "Hypothesis", "User Stories",
            "Requirements & Acceptance", "Scope",
            "Guardrails / Must Not Regress",
            "Delivery, Risks & Open Questions", "Success", "References",
        ],
    },
    "design": {
        "label": "Design",
        "persona": "Design",
        "question_bank": "design-questions.json",
        "sections": [
            "Design Intent", "Pages / Routes", "Layout Structure",
            "Component Inventory", "Spacing", "Typography", "Color Application",
            "Elevation & Depth", "States", "Data Binding", "Interactions & Motion",
            "Responsive Behavior", "Accessibility", "Content Constraints",
            "Implementation Notes", "Verification Criteria", "Figma / Visual Reference",
        ],
    },
    "rfc": {
        "label": "Technical RFC",
        "persona": "Engineering",
        "question_bank": "rfc-questions.json",
        "sections": [
            "Basic Example", "Interface Contract", "Data Model", "State Machine",
            "API Surface", "Validation Rules", "Testing", "Security & Controls",
            "Key Decisions", "Drawbacks", "Search / Query Strategy",
            "Migration Strategy", "File Impact", "Dependencies",
            "Unresolved Questions",
        ],
    },
}


class DraftError(RuntimeError):
    """A user-actionable interview error."""

    status = "error"


class RevisionConflict(DraftError):
    status = "revision_conflict"


class UpstreamChanged(DraftError):
    status = "upstream_changed"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _features_root(project_root: Path) -> Path:
    """Mirror dashboard/backend/paths.py so every surface agrees on the layout."""
    shared = project_root / ".speed" / "shared"
    if shared.is_dir():
        return shared / "features"
    return project_root / ".speed" / "features"


def _feature_dir(project_root: Path, feature: str) -> Path:
    return _features_root(project_root) / feature


def _feature_dir_display(project_root: Path, feature: str) -> str:
    return _feature_dir(project_root, feature).relative_to(project_root).as_posix()


def _slugify(title: str) -> str:
    """Derive a candidate feature slug from a human title."""
    lowered = re.sub(r"[^a-z0-9]+", "-", title.strip().lower())
    return lowered.strip("-")[:50].strip("-")


def _feature_from_compact_plan(compact_plan_json: str) -> str:
    """Derive repository identity from the semantic title used by the PRD."""
    try:
        compact_plan = json.loads(compact_plan_json)
    except json.JSONDecodeError as exc:
        raise DraftError("The compact interview plan is not valid JSON.") from exc
    if not isinstance(compact_plan, dict):
        raise DraftError("The compact interview plan must be an object.")
    title = " ".join(str(compact_plan.get("feature_title") or "").split())
    feature = _slugify(title)
    if not title or not feature:
        raise DraftError("The compact interview plan must include a usable feature title.")
    return feature


def _canonicalize_provisional_feature(
    project_root: Path,
    feature: str,
    artifact_type: str,
    state: dict[str, Any],
) -> tuple[str, Path, Path]:
    """Replace an opaque intake route with the model-derived package identity.

    Only untouched PRD intake checkpoints using the ``draft-`` namespace may
    move. Existing feature packages are never renamed implicitly. The move is
    performed while the provisional feature lock is held and before the
    updated checkpoint is written to its new path.
    """
    feature_dir = _feature_dir(project_root, feature)
    state_path = feature_dir / f"authoring-{artifact_type}.json"
    if artifact_type != "prd" or not feature.startswith("draft-"):
        return feature, feature_dir, state_path
    if state.get("artifact") or state.get("artifact_versions"):
        raise DraftError("A generated feature package cannot be renamed automatically.")

    title = " ".join(str((state.get("intake") or {}).get("feature_title") or "").split())
    canonical = _slugify(title)
    if not canonical:
        # A fallback plan deliberately leaves the provisional identity in
        # place. Retrying semantic planning can canonicalize it later.
        return feature, feature_dir, state_path
    if canonical == feature:
        return feature, feature_dir, state_path

    target_dir = _feature_dir(project_root, canonical)
    target_specs = project_root / "specs" / canonical
    source_specs = project_root / "specs" / feature
    if target_dir.exists() or target_specs.exists():
        description = str((state.get("intake") or {}).get("feature_description") or title)
        suffix = hashlib.sha256(description.encode("utf-8")).hexdigest()[:8]
        canonical = f"{canonical[:41].rstrip('-')}-{suffix}"
        target_dir = _feature_dir(project_root, canonical)
        target_specs = project_root / "specs" / canonical
    if target_dir.exists() or target_specs.exists():
        raise DraftError(
            "The model-derived feature identity is already in use. Resume that package "
            "or revise the feature description."
        )

    target_dir.parent.mkdir(parents=True, exist_ok=True)
    feature_dir.rename(target_dir)
    if source_specs.exists():
        target_specs.parent.mkdir(parents=True, exist_ok=True)
        source_specs.rename(target_specs)

    # Planning evidence may contain checkpoint paths that include the
    # provisional identifier. Replace only that opaque token; it cannot occur
    # in user-authored prose unless the user copied the temporary route.
    serialized = json.dumps(state)
    state.clear()
    state.update(json.loads(serialized.replace(feature, canonical)))
    state["feature_name"] = canonical
    state.setdefault("identity", {}).update({
        "source": "model_derived_title",
        "provisional_feature_name": feature,
        "canonicalized_at": _now(),
    })
    return canonical, target_dir, target_dir / f"authoring-{artifact_type}.json"


def _question_bank_path(artifact_type: str) -> Path:
    filename = ARTIFACTS[artifact_type]["question_bank"]
    return Path(__file__).resolve().parent.parent / "references" / filename


def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _implementation(artifact_type: str | None) -> dict[str, str | None]:
    """Identify the shared helper and question bank used by every entry point."""
    script_dir = Path(__file__).resolve().parent
    reference_dir = script_dir.parent / "references"
    return {
        "helper_hash": _sha256_file(Path(__file__).resolve()),
        "question_bank_hash": (
            _sha256_file(_question_bank_path(artifact_type)) if artifact_type else None
        ),
        "planner_contract_hash": (
            _sha256_file(script_dir / "planner_contract.py")
            if artifact_type == "prd"
            else None
        ),
        "planner_prompt_hash": (
            _sha256_file(reference_dir / "prd-interview-planner-prompt.md")
            if artifact_type == "prd"
            else None
        ),
    }


def _load_question_bank(artifact_type: str) -> dict[str, Any]:
    path = _question_bank_path(artifact_type)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not data.get("version") or not data.get("questions"):
        raise DraftError(f"Question bank is invalid: {path}")
    return data


SCOPE_SIGNAL_RE = re.compile(
    r"\b(auth(?:entication|orization)?|login|sign[ -]?in|privacy|permission|"
    r"role|own|owner(?:ship)?|shared?|migration|existing data|integration|external|"
    r"platform|workspace|organization|tenant|admin|rollout|breaking)\b",
    re.IGNORECASE,
)
RISK_SIGNAL_RE = re.compile(
    r"\b(auth(?:entication|orization)?|login|sign[ -]?in|privacy|permission|"
    r"own|owner(?:ship)?|security|sensitive (?:data|information)|personal data|migration|payment|billing|"
    r"compliance|legal|audit|risk|open decision|delete|irreversible|external|third[ -]?party|"
    r"rollout|agent|llm|artificial intelligence|ai)\b",
    re.IGNORECASE,
)
IDENTITY_SIGNAL_RE = re.compile(
    r"\b(auth(?:entication|orization)?|login|log[ -]?in|sign[ -]?in|sign[ -]?up|"
    r"account|session|privacy|private|user ownership)\b",
    re.IGNORECASE,
)


def _has_identity_signal(text: str) -> bool:
    """Recognize identity scope without treating explicit exclusions as scope."""
    negative = re.compile(
        r"\b(no|none|without|not|don't|doesn't|do not|does not|isn't|is not|"
        r"aren't|are not|won't|will not)\b",
        re.IGNORECASE,
    )
    for clause in re.split(r"(?<=[.!?;])\s+|\b(?:but|however)\b", text):
        if IDENTITY_SIGNAL_RE.search(clause) and not negative.search(clause):
            return True
    return False


def _planning_text(state: dict[str, Any]) -> str:
    parts = [
        str((state.get("intake") or {}).get("feature_description") or ""),
        *(str(record.get("answer") or "") for record in state.get("answers", {}).values()),
    ]
    return " ".join(part for part in parts if part)


def _description_profile(description: str) -> dict[str, bool]:
    """Identify which product decisions the intake already answers."""
    return {
        "audience": bool(re.search(
            r"\b(user|users|person|people|customer|customers|member|members|team|teams)\b",
            description,
            re.IGNORECASE,
        )),
        "capability": bool(re.search(
            r"\b(add|assign|select|set|choose|create|edit|update|show|display|highlight|sort|order|filter)\w*\b",
            description,
            re.IGNORECASE,
        )),
        "outcome": bool(re.search(
            r"\b(so that|in order to|avoid|prevent|miss|missed|forget|forgot|"
            r"time-sensitive|nearby|approach(?:es|ing)?|due earlier)\b",
            description,
            re.IGNORECASE,
        )),
        "compatibility": bool(re.search(
            r"\bexisting\b.{0,100}\b(remain|continue|valid|unchanged|still|compatible)\b|"
            r"\b(remain|continue|valid|unchanged|still|compatible)\b.{0,100}\bexisting\b",
            description,
            re.IGNORECASE,
        )),
        "journey": bool(re.search(
            r"\bwhen\b.{0,100}\b(add|create|edit|select|set|save)\w*\b|"
            r"\b(add|create|edit|select|set|save)\w*\b.{0,100}\b(task|item|record)\b",
            description,
            re.IGNORECASE,
        )),
        "observable_result": bool(re.search(
            r"\b(list|board|screen|status|badge|highlight|sort|order|show|display)\w*\b",
            description,
            re.IGNORECASE,
        )),
        "failure_recovery": bool(re.search(
            r"\b(invalid|error|fail(?:s|ed|ure)?|retry|recover|preserve|cannot|can't)\b",
            description,
            re.IGNORECASE,
        )),
        "explicit_exclusion": bool(re.search(
            r"\b(out of scope|exclude[ds]?|not included|will not|won't|without)\b",
            description,
            re.IGNORECASE,
        )),
    }


COVERAGE_POLICY = {
    "P-Q1": {"impact": "critical", "leverage": 1.0},
    "P-Q2": {"impact": "high", "leverage": 1.0},
    "P-Q3": {"impact": "medium", "leverage": 0.7},
    "P-Q4": {"impact": "high", "leverage": 0.85},
    "P-Q5": {"impact": "high", "leverage": 0.8},
    "P-Q6": {"impact": "conditional", "leverage": 0.6},
    "P-Q7": {"impact": "high", "leverage": 1.05},
    "P-Q8": {"impact": "conditional", "leverage": 1.05},
}
IMPACT_WEIGHT = {"low": 0.25, "medium": 0.5, "high": 0.8, "critical": 1.0}
READINESS_CONFIDENCE = 0.7
SUCCESS_SIGNAL_RE = re.compile(
    r"\b(metric|measure|measurement|target|baseline|analytics|adoption|conversion|"
    r"retention|success rate|percent(?:age)?|within \d|by \d)\b|\d+%",
    re.IGNORECASE,
)
DELIVERY_DETAIL_RE = re.compile(
    r"\b(deliver(?:y|ed)?|depend(?:s|ency|encies)?|sequenc(?:e|ing)?|risks?|"
    r"owners?|owns|timezone|migration|rollout)\b|"
    r"\bexisting\b.{0,80}\b(remain|valid|compatible)\b",
    re.IGNORECASE,
)


def _coverage_confidence(question_id: str, state: dict[str, Any]) -> tuple[float, str, list[str]]:
    record = state.get("answers", {}).get(question_id, {})
    if record.get("state") == "confirmed":
        return 1.0, "confirmed", [f"interview:{question_id}"]

    description = str((state.get("intake") or {}).get("feature_description") or "")
    text = _planning_text(state)
    basis = ["intake:feature-description"] if description else []
    identity = _has_identity_signal(text)
    risk_signal = bool(RISK_SIGNAL_RE.search(text))
    profile = _description_profile(description)

    if question_id == "P-Q1":
        return (0.95, "evidence_backed", basis) if description else (0.0, "missing", [])
    if question_id == "P-Q2":
        if (
            profile["audience"]
            and profile["capability"]
            and profile["outcome"]
            and profile["compatibility"]
        ):
            return 0.8, "inferred", basis
        if profile["audience"] and profile["capability"] and profile["outcome"]:
            return 0.65, "unresolved", basis
        return (0.3, "unresolved", basis) if identity else (0.4, "unresolved", basis)
    if question_id == "P-Q3":
        audience = str(state.get("answers", {}).get("P-Q2", {}).get("answer") or "")
        if audience and re.search(
            r"\b(so that|enable|outcome|reduce|increase|improve|prevent|avoid|"
            r"remain|unchanged|must not|continue)\b",
            audience,
            re.IGNORECASE,
        ):
            return 0.85, "inferred", ["interview:P-Q2"]
        if profile["outcome"] or re.search(r"\b(so that|enable|outcome|reduce|increase|improve|prevent)\b", text, re.IGNORECASE):
            return 0.85, "inferred", basis
        return 0.5, "inferred", basis
    if question_id == "P-Q4":
        if profile["journey"] and profile["observable_result"]:
            if profile["failure_recovery"]:
                return 0.8, "inferred", basis
            return 0.65, "unresolved", basis
        if len(description.split()) >= 12 and re.search(r"\b(add|build|let|allow|enable|show|create|update|rename)\b", description, re.IGNORECASE):
            return 0.65, "inferred", basis
        return 0.45, "unresolved", basis
    if question_id == "P-Q5":
        journey = str(state.get("answers", {}).get("P-Q4", {}).get("answer") or "")
        if journey and re.search(
            r"\b(when|then|if|saving|saved|shows?|displays?|error|retry|"
            r"complete[sd]?|result)\b",
            journey,
            re.IGNORECASE,
        ):
            return 0.85, "inferred", ["interview:P-Q4"]
        if re.search(r"\b(given|when|then|done when|must|must not|reject)\b", text, re.IGNORECASE):
            return 0.75, "inferred", basis
        return 0.3, "unresolved", basis
    if question_id == "P-Q6":
        if (
            re.search(r"\b(target|baseline|within \d|by \d)\b|\d+%", text, re.IGNORECASE)
            and re.search(r"\b(owner|owns|analytics|product|team)\b", text, re.IGNORECASE)
        ):
            return 0.8, "inferred", basis
        if SUCCESS_SIGNAL_RE.search(text):
            return 0.4, "unresolved", basis
        return 0.85, "not_material", basis
    if question_id == "P-Q7":
        # Scope is core to the proposal. Nearby words such as "role" or
        # "permission" are useful context but cannot safely invent inclusions
        # and exclusions, so require an explicit answer.
        return 0.3, "unresolved", basis
    if question_id == "P-Q8":
        if not risk_signal:
            return 0.85, "not_material", basis
        if re.search(r"\b(owner|owns|owned by|rollback|threshold|must not|audit|escalat)\b", text, re.IGNORECASE):
            return 0.7, "inferred", basis
        return 0.3, "unresolved", basis
    return 0.0, "missing", basis


def _coverage_assessment(state: dict[str, Any], bank: dict[str, Any]) -> dict[str, Any]:
    assessment: dict[str, Any] = {}
    for question in bank["questions"]:
        question_id = question["id"]
        confidence, status, basis = _coverage_confidence(question_id, state)
        policy = COVERAGE_POLICY.get(question_id, {"impact": "medium", "leverage": 0.5})
        impact = policy["impact"]
        if impact == "conditional":
            planning_text = _planning_text(state)
            if question_id == "P-Q6":
                signal = SUCCESS_SIGNAL_RE
            elif question_id == "P-Q7":
                signal = SCOPE_SIGNAL_RE
            else:
                signal = RISK_SIGNAL_RE
            identity_rollout = question_id == "P-Q7" and _has_identity_signal(
                str((state.get("intake") or {}).get("feature_description") or "")
            )
            impact = "high" if identity_rollout or signal.search(planning_text) else "low"
        question_value = round(
            (1 - confidence) * IMPACT_WEIGHT[impact] * float(policy["leverage"]), 3
        )
        assessment[question_id] = {
            "coverage": question.get("coverage"),
            "confidence": round(confidence, 2),
            "confidence_label": status,
            "impact": impact,
            "basis": basis,
            "question_value": question_value,
        }
    return assessment


def _contextualize_question(
    question: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any]:
    """Adapt wording to the feature while retaining a stable coverage ID."""
    if state.get("artifact_type") != "prd":
        return question
    contextual = dict(question)
    feature = state["feature_name"].replace("-", " ")
    description = str((state.get("intake") or {}).get("feature_description") or "")
    profile = _description_profile(description)
    identity_feature = _has_identity_signal(
        description
    )
    prompts = {
        "P-Q2": (
            "Which authentication method should the first release support: username "
            "and password, Google sign-in, another provider, or a specific "
            "combination?"
            if identity_feature
            else f"For {feature}, who needs the outcome, what should they be able to "
            "accomplish, and what existing behavior must remain unchanged? If every "
            "user behaves the same, say so."
        ),
        "P-Q3": (
            f"What observable user or business outcome should {feature} create, and "
            "what must remain unchanged for that outcome to be acceptable?"
        ),
        "P-Q4": (
            "What should happen when someone opens the application signed out, signs "
            "in successfully, cannot sign in, loses their session, or signs out?"
            if identity_feature
            else f"For {feature}, where does the user begin, what completes the task, "
            "and what observable result should appear on the happy path and for any "
            "material failure or recovery path?"
        ),
        "P-Q5": (
            "What must the authentication and privacy boundary do, and what observable "
            "behavior proves that one user cannot access another user's private data?"
            if identity_feature
            else f"What must {feature} do, and what observable behavior proves each "
            "essential requirement?"
        ),
        "P-Q6": (
            f"After {feature} ships, what observable signal would show that it solved "
            "the problem without harming an existing outcome?"
        ),
        "P-Q7": (
            "How are you thinking of rolling out authentication to existing users? "
            "How will they set up authentication, and what should happen to their "
            "existing account and data?"
            if identity_feature
            else f"For {feature}, what is explicitly included or excluded, what does "
            "delivery depend on, and is there any material release risk or open "
            "decision with an owner? Say none if there is not one."
        ),
        "P-Q8": (
            "Which authentication failure or control must be resolved before release—"
            "for example session expiry, failed sign-in, account recovery, lockout, "
            "or preventing access to another user's private data—and who owns it?"
            if identity_feature
            else f"For {feature}, which material control, delivery risk, assumption, "
            "or unresolved decision needs an owner?"
        ),
    }
    if question["id"] in prompts:
        contextual["prompt"] = prompts[question["id"]]
    if question["id"] == "P-Q2" and profile["audience"] and profile["capability"] and profile["outcome"]:
        contextual["purpose"] = (
            "The audience and desired outcome are already covered. Confirm only the "
            "backward-compatible behavior for existing and undated tasks."
        )
        contextual["quality"] = {
            **(question.get("quality") or {}),
            "follow_up_prompt": (
                "Please confirm which existing cases must remain valid and unchanged, "
                "including the default behavior when the new capability is not used."
            ),
        }
    elif question["id"] == "P-Q4" and profile["journey"] and profile["observable_result"]:
        contextual["purpose"] = (
            "The happy path is already covered. Define only the material failure and recovery behavior."
        )
        contextual["quality"] = {
            **(question.get("quality") or {}),
            "follow_up_prompt": (
                "Please confirm what is preserved, what error is shown, and whether the user can retry."
            ),
        }
    elif question["id"] == "P-Q7" and profile["capability"] and not profile["explicit_exclusion"]:
        contextual["purpose"] = (
            "The core behavior is already covered. Set the V1 exclusions and any real delivery dependency."
        )
        contextual["quality"] = {
            **(question.get("quality") or {}),
            "follow_up_prompt": (
                "Please confirm the V1 exclusions and whether delivery has any external dependency."
            ),
        }
    if identity_feature:
        identity_metadata = {
            "P-Q2": {
                "evidence": "Current sign-in capabilities, platform constraints, security policy, and requested providers",
                "purpose": "Confirm the authentication method for the first release without inventing providers or credentials.",
                "completion_evidence": "Names the supported authentication method or provider combination and any explicit first-release exclusion.",
                "quality": {
                    "min_chars": 30,
                    "follow_up_prompt": "Please name the authentication method or provider combination for the first release.",
                },
            },
            "P-Q7": {
                "evidence": "Existing users, accounts, stored data, current identifiers, and available migration or invitation mechanisms",
                "purpose": "Protect backward compatibility by deciding how existing users establish authentication and retain access to their data.",
                "completion_evidence": "Explains how existing users set up authentication and what happens to their existing account and data.",
                "quality": {
                    "min_chars": 50,
                    "follow_up_prompt": "Please explain how existing users set up authentication and retain access to their existing account and data.",
                },
            },
            "P-Q8": {
                "evidence": "Session, recovery, privacy, security, support, and release-control evidence",
                "purpose": "Identify the release-blocking authentication control or unresolved risk and its owner.",
                "completion_evidence": "Names the material authentication control or failure, the required boundary, and an owner where action is needed.",
                "quality": {
                    "min_chars": 50,
                    "follow_up_prompt": "Please name the material authentication control or failure and who owns its resolution.",
                },
            },
        }
        contextual.update(identity_metadata.get(question["id"], {}))
    return contextual


def _active_questions(state: dict[str, Any], bank: dict[str, Any]) -> list[dict[str, Any]]:
    planning = state.get("planning") or {}
    if planning.get("mode") == "model":
        coverage = dict(planning.get("coverage") or {})
        for question_id, record in state.get("answers", {}).items():
            coverage_id = str(record.get("coverage_id") or question_id)
            if record.get("state") == "confirmed" and coverage_id in coverage:
                coverage[coverage_id] = {
                    **coverage[coverage_id],
                    "confidence": 1.0,
                    "confidence_label": "confirmed",
                    "basis": [f"interview:{question_id}"],
                }
        state["coverage"] = coverage
        by_id = {
            str(question.get("id")): question
            for question in planning.get("questions") or []
            if isinstance(question, dict) and question.get("id")
        }
        bank_by_id = {question["id"]: question for question in bank["questions"]}
        active_ids = list(by_id)
        # Preserve an explicit defer/stale review or targeted follow-up even if
        # a later model plan no longer contains the original question object.
        for question_id, record in state.get("answers", {}).items():
            if record.get("state") in {"deferred", "stale"} and question_id not in active_ids:
                active_ids.append(question_id)
        for question_id, follow_up in state.get("follow_ups", {}).items():
            if follow_up.get("status") == "pending" and question_id not in active_ids:
                active_ids.append(question_id)
        state["clarification_plan"] = active_ids
        return [
            by_id.get(question_id)
            or _contextualize_question(
                bank_by_id[
                    str((state.get("answers", {}).get(question_id) or {}).get("coverage_id") or question_id)
                ],
                state,
            )
            for question_id in active_ids
            if question_id in by_id
            or str((state.get("answers", {}).get(question_id) or {}).get("coverage_id") or question_id)
            in bank_by_id
        ]

    assessment = _coverage_assessment(state, bank)
    state["coverage"] = assessment
    current_plan = list(dict.fromkeys(state.get("clarification_plan", [])))

    if current_plan:
        # Freeze the complete initial plan. The browser may collect the whole
        # batch before persisting it, so an earlier answer must not remove a
        # later question while that batch is being applied.
        plan = current_plan
    else:
        # Bank order defines a natural conversation (audience before behavior,
        # behavior before measurement). Coverage value decides inclusion, not
        # an arbitrary count cap.
        plan = [
            question_id
            for question_id, item in assessment.items()
            if question_id not in state.get("answers", {})
            and item["impact"] in {"medium", "high", "critical"}
            and item["confidence_label"] not in {"not_material", "evidence_backed"}
            and item["confidence"] < READINESS_CONFIDENCE
        ]
    state["clarification_plan"] = plan
    by_id = {question["id"]: question for question in bank["questions"]}
    return [
        _contextualize_question(by_id[question_id], state)
        for question_id in plan
        if question_id in by_id
    ]


def _available_upstream_packages(
    project_root: Path, artifact_type: str
) -> list[dict[str, Any]]:
    """List only published packages that satisfy the downstream chain."""
    features_root = _features_root(project_root)
    if not features_root.is_dir():
        return []
    available: list[dict[str, Any]] = []
    for state_path in sorted(features_root.glob("*/authoring-prd.json")):
        feature = state_path.parent.name
        if not FEATURE_RE.fullmatch(feature) or "--" in feature:
            continue
        try:
            prd_source = _artifact_upstream(project_root, feature, "prd")
        except (DraftError, UpstreamChanged):
            continue
        source = prd_source
        if artifact_type == "rfc":
            try:
                source = _artifact_upstream(project_root, feature, "design")
            except (DraftError, UpstreamChanged):
                continue
        available.append({
            "feature_name": feature,
            "path": source["path"],
            "sha256": source["sha256"],
            "interview_revision": source["interview_revision"],
            "published_revision": source["published_revision"],
        })
    return available


def _intake_result(
    project_root: Path, artifact_type: str | None
) -> dict[str, Any]:
    """Return the shared missing-input contract without creating workflow state."""
    if artifact_type is None:
        next_input = {
            "id": "artifact_type",
            "input_type": "single_select",
            "prompt": "What would you like to draft?",
            "options": [
                {"value": "prd", "label": "New PRD"},
                {"value": "design", "label": "Design from PRD"},
                {"value": "rfc", "label": "Technical RFC from PRD"},
            ],
        }
        message = "Select the artifact before Workbench asks for its input."
    elif artifact_type == "prd":
        next_input = {
            "id": "new_prd_basics",
            "input_type": "conversation",
            "prompt": "What would you like to ship?",
            "fields": [
                {
                    "id": "feature_description",
                    "input_type": "textarea",
                    "prompt": "Describe the feature and the problem it should solve.",
                    "description": (
                        "Share the basic idea. Workbench will derive the title and ask only "
                        "for material details that are still missing."
                    ),
                    "required": True,
                },
            ],
            "allow_existing": False,
        }
        message = (
            "Start with one short description. Workbench derives the title, slug, and "
            "artifact path, then asks only the questions needed for a useful first draft."
        )
    else:
        guided_prds = _available_upstream_packages(project_root, artifact_type)
        label = ARTIFACTS[artifact_type]["label"]
        next_input = {
            "id": "source_prd",
            "input_type": "prd_reference",
            "prompt": (
                f"Which published PRD should ground this {label} draft?"
                if artifact_type == "design"
                else "Which package with published PRD and Design should ground this Technical RFC?"
            ),
            "accepts": ["attached_prd", "prd_path", "guided_prd", "feature_name"],
            "options": guided_prds,
            "fallback": {
                "id": "feature_name",
                "input_type": "text",
                "prompt": (
                    "If the feature cannot be derived from the PRD, enter its feature name."
                ),
            },
        }
        message = (
            f"Select the finalized upstream package first. The {label} agent derives the feature "
            "identity and asks its own artifact-specific questions."
        )
    return {
        "skill": SKILL,
        "implementation": _implementation(artifact_type),
        "status": "needs_input",
        "artifact_type": artifact_type,
        "next_input": next_input,
        "message": message,
    }


def _validate_feature(feature: str) -> str:
    if not FEATURE_RE.fullmatch(feature) or "--" in feature:
        raise DraftError(
            "Feature name must be lowercase alphanumeric with single hyphens, "
            "must not start or end with a hyphen, and must be at most 50 characters."
        )
    return feature


def _validate_feature_description(description: str | None) -> str | None:
    if description is None:
        return None
    normalized = " ".join(description.split())
    if len(normalized) < 10:
        raise DraftError("The feature description must contain at least 10 characters.")
    return normalized


def _validate_feature_title(title: str | None) -> str | None:
    if title is None:
        return None
    normalized = " ".join(title.split())
    if not normalized:
        raise DraftError("The feature title must not be empty.")
    if len(normalized) > 80:
        raise DraftError("The feature title must be at most 80 characters.")
    return normalized


def _display_name(feature: str, state: dict[str, Any]) -> str:
    """Prefer the author's own title; fall back to the slug."""
    title = (state.get("intake") or {}).get("feature_title")
    return str(title) if title else feature.replace("-", " ").title()


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            temp_path = Path(handle.name)
        os.replace(temp_path, path)
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()


def _write_json(path: Path, data: dict[str, Any]) -> None:
    _atomic_write(path, json.dumps(data, indent=2) + "\n")


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DraftError(f"Persisted state is unreadable: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise DraftError(f"Persisted state must be a JSON object: {path}")
    return data


@contextlib.contextmanager
def _feature_lock(feature_dir: Path) -> Iterator[None]:
    feature_dir.mkdir(parents=True, exist_ok=True)
    lock_path = feature_dir / ".authoring.lock"
    with lock_path.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _actor(project_root: Path) -> tuple[str, str]:
    def git_config(key: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(project_root), "config", "--get", key],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else ""

    name = git_config("user.name") or "Workbench User"
    email = git_config("user.email") or "workbench@localhost"
    return name, email


def _read_evidence_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Read optional evidence without making a broken source destroy the session."""
    if not path.is_file():
        return None, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"{path}: unreadable ({exc})"
    if not isinstance(data, dict):
        return None, f"{path}: expected a JSON object"
    return data, None


def _artifact_upstream(
    project_root: Path, feature: str, artifact_type: str
) -> dict[str, Any]:
    """Resolve a finalized upstream artifact consumed by another branch."""
    state_path = _feature_dir(project_root, feature) / f"authoring-{artifact_type}.json"
    prd_state = _read_json(state_path)
    expected_path = f"specs/{feature}/{artifact_type}.md"
    label = ARTIFACTS[artifact_type]["label"]
    if not prd_state or prd_state.get("published_revision") is None:
        raise DraftError(
            f"Downstream drafting requires a published {label}. Finish its interview, "
            f"review it, and run `workbench draft {artifact_type} {feature} --publish` first."
        )
    artifact = prd_state.get("artifact") or {}
    if artifact.get("path") != expected_path:
        raise DraftError(f"The {label} checkpoint does not identify a usable artifact.")
    published_revision = prd_state.get("published_revision")
    published_version = next(
        (
            item
            for item in reversed(prd_state.get("artifact_versions", []))
            if item.get("revision") == published_revision
            and item.get("status") == "published"
            and isinstance(item.get("content"), str)
        ),
        None,
    )
    if not published_version:
        raise DraftError(f"The {label} checkpoint has no immutable published version.")
    published_content = published_version["content"]
    published_hash = hashlib.sha256(published_content.encode()).hexdigest()
    history_entry = next(
        (
            item for item in reversed(prd_state.get("publish_history", []))
            if item.get("revision") == published_revision
        ),
        None,
    )
    if history_entry and history_entry.get("sha256") != published_hash:
        raise UpstreamChanged(f"The stored published {label} version failed its integrity check.")

    # If the published version is still current, the checked-in artifact must
    # match it. A known newer draft may diverge safely because downstream work
    # consumes the immutable published snapshot, not the draft file.
    if prd_state.get("status") == "published":
        prd_path = project_root / expected_path
        if not prd_path.is_file():
            raise DraftError(
                f"The {label} checkpoint references a missing artifact: {expected_path}"
            )
        if hashlib.sha256(prd_path.read_bytes()).hexdigest() != published_hash:
            raise UpstreamChanged(
                f"The {label} content no longer matches its published checkpoint. Resume "
                f"{label} drafting and publish a new version before continuing downstream."
            )
    return {
        "artifact_type": artifact_type,
        "path": expected_path,
        "sha256": published_hash,
        "content": published_content,
        "interview_revision": published_version.get(
            "interview_revision", published_revision
        ),
        "published_revision": published_revision,
        "question_bank_version": published_version.get(
            "question_bank_version", prd_state["question_bank_version"]
        ),
        "captured_at": _now(),
    }


def _prd_upstream(project_root: Path, feature: str) -> dict[str, Any]:
    return _artifact_upstream(project_root, feature, "prd")


def _design_upstream(project_root: Path, feature: str) -> dict[str, Any]:
    return _artifact_upstream(project_root, feature, "design")


def _validate_pinned_upstream(
    state: dict[str, Any], artifact_type: str, current: dict[str, Any]
) -> None:
    pinned = (state.get("upstream") or {}).get(artifact_type)
    if not pinned:
        raise DraftError(
            f"The downstream checkpoint is missing its pinned {artifact_type.upper()} input."
        )
    stable_fields = (
        "path", "sha256", "interview_revision", "published_revision",
        "question_bank_version",
    )
    if any(pinned.get(field) != current.get(field) for field in stable_fields):
        raise UpstreamChanged(
            f"The published {artifact_type.upper()} changed after this downstream interview "
            "started. Existing answers were preserved, but they must be revalidated."
        )


def _markdown_section_excerpt(content: str, headings: tuple[str, ...]) -> str:
    sections: list[str] = []
    for heading in headings:
        pattern = re.compile(
            rf"^## {re.escape(heading)}\s*$\n(.*?)(?=^## |\Z)",
            re.MULTILINE | re.DOTALL,
        )
        match = pattern.search(content)
        if match:
            body = re.sub(r"^### .*?$", "", match.group(1), flags=re.MULTILINE)
            normalized = " ".join(body.split())
            if normalized:
                sections.append(f"{heading}: {normalized}")
    return " ".join(sections)


def _source(source_id: str, path: str, excerpt: str) -> dict[str, str]:
    normalized = " ".join(str(excerpt).split())
    return {
        "id": source_id,
        "path": path,
        "status": "available",
        "excerpt": normalized[:280],
    }


def _evidence_sources(
    project_root: Path, feature: str, state: dict[str, Any], question_id: str
) -> tuple[list[dict[str, str]], list[str]]:
    feature_dir = _feature_dir(project_root, feature)
    sources: list[dict[str, str]] = []
    gaps: list[str] = []

    intake_description = (state.get("intake") or {}).get("feature_description")
    if state["artifact_type"] == "prd" and intake_description:
        sources.append(_source(
            "intake:feature-description",
            f"{_feature_dir_display(project_root, feature)}/authoring-prd.json",
            intake_description,
        ))

    if state["artifact_type"] in {"design", "rfc"}:
        prd_source = state["upstream"]["prd"]
        prd_sections = {
            "D-Q1": ("Problem & Evidence", "Success", "Scope"),
            "D-Q2": ("Requirements & Acceptance", "User Stories"),
            "D-Q3": ("Requirements & Acceptance", "User Stories"),
            "D-Q4": ("User Stories", "Delivery, Risks & Open Questions"),
            "D-Q5": ("Requirements & Acceptance", "Delivery, Risks & Open Questions"),
            "D-Q6": ("Requirements & Acceptance", "Guardrails / Must Not Regress"),
            "D-Q7": ("Scope", "Delivery, Risks & Open Questions"),
            "D-Q8": (
                "User Stories", "Success", "Guardrails / Must Not Regress",
                "Delivery, Risks & Open Questions",
            ),
            "R-Q1": ("Requirements & Acceptance", "User Stories"),
            "R-Q2": ("Requirements & Acceptance", "Scope"),
            "R-Q3": ("Requirements & Acceptance", "Guardrails / Must Not Regress"),
            "R-Q4": ("Requirements & Acceptance", "Guardrails / Must Not Regress"),
            "R-Q5": ("Guardrails / Must Not Regress", "Delivery, Risks & Open Questions"),
            "R-Q6": ("Hypothesis", "Scope", "Delivery, Risks & Open Questions"),
            "R-Q7": ("Scope", "Guardrails / Must Not Regress", "Delivery, Risks & Open Questions"),
            "R-Q8": ("Delivery, Risks & Open Questions", "References"),
        }
        prd_content = str(prd_source.get("content") or "")
        if not prd_content:
            prd_content = (project_root / prd_source["path"]).read_text(encoding="utf-8")
        usable_prd_section = False
        for heading in prd_sections.get(question_id, ("Summary", "Requirements & Acceptance")):
            excerpt = _markdown_section_excerpt(prd_content, (heading,))
            if not excerpt:
                continue
            usable_prd_section = True
            sources.append(_source(
                f"prd:{heading.lower().replace(' ', '-').replace('&', 'and')}",
                state["upstream"]["prd"]["path"],
                excerpt,
            ))
        if not usable_prd_section:
            gaps.append(f"The linked PRD has no usable content routed to {question_id}.")
        if state["artifact_type"] == "rfc" and (state.get("upstream") or {}).get("design"):
            design_source = state["upstream"]["design"]
            design_content = str(design_source.get("content") or "")
            if not design_content:
                design_content = (
                    project_root / design_source["path"]
                ).read_text(encoding="utf-8")
            design_headings = {
                "R-Q1": ("Data Binding", "Interactions & Motion"),
                "R-Q2": ("Data Binding", "States"),
                "R-Q3": ("States", "Content Constraints"),
                "R-Q4": ("Verification Criteria", "States"),
                "R-Q5": ("Accessibility", "Content Constraints"),
                "R-Q6": ("Implementation Notes", "Component Inventory"),
                "R-Q7": ("Implementation Notes", "Pages / Routes"),
                "R-Q8": ("Implementation Notes", "Verification Criteria"),
            }
            for heading in design_headings.get(question_id, ("Implementation Notes",)):
                excerpt = _markdown_section_excerpt(design_content, (heading,))
                if excerpt:
                    sources.append(_source(
                        f"design:{heading.lower().replace(' ', '-').replace('/', '-')}",
                        design_source["path"],
                        excerpt,
                    ))

    intent_path = feature_dir / "intent.json"
    intent, error = _read_evidence_json(intent_path)
    if error:
        gaps.append(error)
    if intent and intent.get("text"):
        sources.append(_source(
            "intent",
            str(intent_path.relative_to(project_root)),
            intent["text"],
        ))

    context_path = feature_dir / "context-package.json"
    context, error = _read_evidence_json(context_path)
    if error:
        gaps.append(error)
    if context:
        if context.get("bluf_summary"):
            sources.append(_source(
                "context:summary",
                str(context_path.relative_to(project_root)),
                context["bluf_summary"],
            ))
        if context.get("vision_content") and question_id in {
            "P-Q2", "P-Q3", "P-Q6", "D-Q1", "D-Q7",
        }:
            sources.append(_source(
                "context:vision",
                str(context_path.relative_to(project_root)),
                context["vision_content"],
            ))

        routed_fields = {
            "P-Q1": ("defects", "learnings", "project_knowledge"),
            "P-Q2": ("project_knowledge", "related_features"),
            "P-Q3": ("project_knowledge", "learnings"),
            "P-Q4": ("defects", "related_features", "codebase"),
            "P-Q5": ("project_knowledge", "related_features"),
            "P-Q6": ("project_knowledge", "learnings"),
            "P-Q7": ("related_features", "project_knowledge"),
            "P-Q8": ("defects", "project_knowledge", "audit_history"),
            "D-Q1": ("project_knowledge", "related_features"),
            "D-Q2": ("codebase", "related_features"),
            "D-Q3": ("codebase", "project_knowledge"),
            "D-Q4": ("codebase", "project_knowledge", "related_features"),
            "D-Q5": ("defects", "learnings", "project_knowledge"),
            "D-Q6": ("defects", "project_knowledge"),
            "D-Q7": ("project_knowledge", "codebase"),
            "D-Q8": ("project_knowledge", "defects", "audit_history"),
            "R-Q1": ("codebase", "project_knowledge", "related_features"),
            "R-Q2": ("codebase", "project_knowledge"),
            "R-Q3": ("codebase", "project_knowledge", "related_features"),
            "R-Q4": ("defects", "learnings", "audit_history"),
            "R-Q5": ("defects", "project_knowledge", "audit_history"),
            "R-Q6": ("project_knowledge", "related_features", "learnings"),
            "R-Q7": ("codebase", "project_knowledge", "related_features"),
            "R-Q8": ("project_knowledge", "related_features", "audit_history"),
        }
        for field in routed_fields.get(question_id, ()):
            values = context.get(field) or []
            for index, value in enumerate(values[:2]):
                if not isinstance(value, dict):
                    continue
                excerpt = (
                    value.get("text")
                    or value.get("finding")
                    or value.get("description")
                    or value.get("name")
                )
                if excerpt:
                    sources.append(_source(
                        f"context:{field}:{index + 1}",
                        str(context_path.relative_to(project_root)),
                        excerpt,
                    ))

        source_status = context.get("sources_status") or {}
        if isinstance(source_status, dict):
            gaps.extend(
                f"Context source '{name}' is {status}."
                for name, status in source_status.items()
                if status in {"empty", "error", "stale", "missing"}
            )

    questions = [
        q["id"] for q in _load_question_bank(state["artifact_type"])["questions"]
    ]
    question_index = questions.index(question_id)
    for prior_id in questions[:question_index]:
        record = state["answers"].get(prior_id, {})
        if record.get("state") == "confirmed" and record.get("answer"):
            sources.append(_source(
                f"interview:{prior_id}",
                f"{_feature_dir_display(project_root, feature)}"
                f"/authoring-{state['artifact_type']}.json",
                record["answer"],
            ))

    deduped: list[dict[str, str]] = []
    seen = set()
    for item in sources:
        key = item["excerpt"]
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped[:5], gaps


def _build_suggestion(
    project_root: Path,
    feature: str,
    state: dict[str, Any],
    question: dict[str, Any],
) -> dict[str, Any]:
    planned = question.get("suggestion")
    if (
        state.get("artifact_type") == "prd"
        and (state.get("planning") or {}).get("mode") == "model"
        and isinstance(planned, dict)
    ):
        result = dict(planned)
        result.setdefault("id", f"model-{question['id'].lower()}")
        result.setdefault("answer", None)
        result.setdefault("confidence", "missing")
        result.setdefault("accept_ready", False)
        result.setdefault("sources", [])
        result.setdefault("gaps", [])
        result.setdefault("created_at", _now())
        result.setdefault("rejected", False)
        result["question_fingerprint"] = hashlib.sha256(
            str(question.get("prompt") or "").encode()
        ).hexdigest()[:16]
        return result

    sources, gaps = _evidence_sources(project_root, feature, state, question["id"])
    context_path = _feature_dir(project_root, feature) / "context-package.json"
    context, _ = _read_evidence_json(context_path)
    prepared = (context or {}).get("suggested_responses", {}).get(question["id"], {})
    prepared_answer = prepared.get("answer") if isinstance(prepared, dict) else None
    if not prepared_answer and question["id"] == "P-Q1":
        prepared_answer = (state.get("intake") or {}).get("feature_description")
    adaptive_answer = _adaptive_suggested_answer(question["id"], state)

    if prepared_answer and sources:
        answer = str(prepared_answer).strip()
        confidence = "grounded" if not gaps else "partial"
        accept_ready = confidence == "grounded"
    elif adaptive_answer and sources:
        answer = adaptive_answer
        confidence = "partial"
        accept_ready = False
        gaps.append(
            "This response is proposed from the intake and includes a decision that still needs your confirmation."
        )
    elif not sources:
        answer = None
        confidence = "missing"
        accept_ready = False
        gaps.append("No usable evidence was found for this question.")
    else:
        answer = None
        confidence = "partial"
        accept_ready = False
        gaps.append(
            "Available evidence provides context but does not resolve this decision."
        )

    source_fingerprint = json.dumps(sources, sort_keys=True)
    suggestion_id = "sug-" + hashlib.sha256(
        f"{question['id']}:{answer}:{source_fingerprint}".encode()
    ).hexdigest()[:10]
    return {
        "id": suggestion_id,
        "answer": answer,
        "confidence": confidence,
        "accept_ready": accept_ready,
        "sources": sources,
        "gaps": gaps,
        "created_at": _now(),
        "rejected": False,
        "question_fingerprint": hashlib.sha256(
            str(question.get("prompt") or "").encode()
        ).hexdigest()[:16],
    }


def _adaptive_suggested_answer(
    question_id: str, state: dict[str, Any]
) -> str | None:
    """Offer an editable default when intake resolves most of a targeted gap."""
    description = str((state.get("intake") or {}).get("feature_description") or "")
    normalized_description = description.casefold().replace("-", " ")
    task_due_date_feature = "due date" in normalized_description or (
        "task" in normalized_description and "deadline" in normalized_description
    )
    if not task_due_date_feature:
        return None
    profile = _description_profile(description)
    if question_id == "P-Q2" and all(
        profile[key] for key in ("audience", "capability", "outcome")
    ):
        return (
            "Existing tasks without a due date remain valid and continue to work unchanged. "
            "A due date remains optional for new and edited tasks. Undated tasks stay visible "
            "and appear after tasks with due dates when the list is ordered by due date."
        )
    if (
        question_id == "P-Q4"
        and profile["journey"]
        and profile["observable_result"]
        and not profile["failure_recovery"]
    ):
        return (
            "If the due date is invalid or saving fails, preserve the entered task values and "
            "selected date, show a clear error, and let the user correct the value and retry "
            "without losing other changes."
        )
    if (
        question_id == "P-Q7"
        and profile["capability"]
        and not profile["explicit_exclusion"]
    ):
        return (
            "For V1, include the optional due date, nearby-date highlighting, and due-date "
            "ordering described in the request. Exclude reminders, notifications, recurring "
            "schedules, and due times. No additional delivery dependency is currently identified."
        )
    return None


def _new_state(
    feature: str,
    artifact_type: str,
    bank: dict[str, Any],
    upstream: dict[str, dict[str, Any]] | None = None,
    feature_description: str | None = None,
    feature_title: str | None = None,
) -> dict[str, Any]:
    now = _now()
    intake: dict[str, Any] = {}
    if feature_description:
        intake["feature_description"] = feature_description
    if feature_title:
        intake["feature_title"] = feature_title
    if intake:
        intake["captured_at"] = now
    return {
        "schema_version": SCHEMA_VERSION,
        "feature_name": feature,
        "artifact_type": artifact_type,
        "question_bank_version": bank["version"],
        "status": "interviewing",
        "revision": 0,
        "created_at": now,
        "updated_at": now,
        "answers": {},
        "coverage": {},
        "clarification_plan": [],
        "clarifications_asked": [],
        "suggestions": {},
        "decision_history": [],
        "follow_ups": {},
        "edit_requests": {},
        "manual_sections": {},
        "review_comments": [],
        "review_comment_threads": [],
        "artifact_versions": [],
        "published_revision": None,
        "publish_history": [],
        "self_review": {
            "pass_count": 0,
            "max_passes": 2,
            "status": "pending",
            "findings": [],
            "artifact_sha256": None,
        },
        "artifact": None,
        "upstream": upstream or {},
        "intake": intake,
        "planning": {
            "mode": "fallback",
            "planner_version": None,
            "model": None,
            "generated_at": now,
            "analysis_summary": "Deterministic helper planning is active.",
            "coverage": {},
            "questions": [],
            "fallback_reason": "No model plan was supplied by the host.",
        },
    }


def _migrate_state(state: dict[str, Any]) -> dict[str, Any]:
    """Upgrade the un-released v1 checkpoint without losing confirmed answers."""
    if state.get("schema_version") == 1:
        state["schema_version"] = 2
        state.setdefault("suggestions", {})
        state.setdefault("decision_history", [])
        for record in state.get("answers", {}).values():
            record.setdefault("decision", "edited")
            record.setdefault("suggestion_id", None)
    if (
        state.get("artifact_type") == "prd"
        and state.get("question_bank_version") in {"prd-v1", "prd-v2", "prd-v3"}
    ):
        # v2 preserves P-Q1..P-Q8 identities and only changes planning metadata
        # and contextual wording, so existing decisions remain valid.
        state["question_bank_version"] = "prd-v4"
        # Preserve any legacy partial artifact on disk for recovery while its
        # answers are upgraded. Result projection keeps it hidden until the
        # interview reaches a generated terminal state.
        if not state.get("artifact"):
            state["status"] = "interviewing"
        for question_id in list(state.get("suggestions", {})):
            if question_id not in state.get("answers", {}) and question_id not in state.get("follow_ups", {}):
                state["suggestions"].pop(question_id, None)
                state.get("edit_requests", {}).pop(question_id, None)
    state.setdefault("intake", {})
    state.setdefault("planning", {
        "mode": "fallback",
        "planner_version": None,
        "model": None,
        "generated_at": state.get("updated_at"),
        "analysis_summary": "This existing session has not yet been analyzed by the model planner.",
        "coverage": {},
        "questions": [],
        "fallback_reason": "Model re-planning is required for this existing session.",
    })
    state.setdefault("coverage", {})
    state.setdefault("clarification_plan", [])
    state.setdefault("clarifications_asked", [])
    state.setdefault("follow_ups", {})
    state.setdefault("edit_requests", {})
    state.setdefault("manual_sections", {})
    state.setdefault("review_comments", [])
    state.setdefault("review_comment_threads", [])
    state.setdefault("artifact_versions", [])
    state.setdefault("published_revision", None)
    state.setdefault("publish_history", [])
    state.setdefault("self_review", {
        "pass_count": 0,
        "max_passes": 2,
        "status": "pending",
        "findings": [],
        "artifact_sha256": None,
    })
    if state.get("status") == "drafted_with_open_questions":
        state["status"] = "review_repair"
        state["self_review"]["status"] = "needs_repair"
        for finding in state["self_review"].get("findings", []):
            question_id = finding.get("question_id")
            if question_id in state.get("answers", {}):
                state["answers"][question_id]["state"] = "stale"
                state["answers"][question_id]["stale_reason"] = "self_review"
    return state


def _validate_state(
    state: dict[str, Any], feature: str, artifact_type: str, bank: dict[str, Any]
) -> None:
    if state.get("schema_version") != SCHEMA_VERSION:
        raise DraftError("Interview state uses an unsupported schema version.")
    if (
        state.get("feature_name") != feature
        or state.get("artifact_type") != artifact_type
    ):
        raise DraftError(
            f"Interview state identity does not match the requested {artifact_type}."
        )
    if state.get("question_bank_version") != bank["version"]:
        raise DraftError(
            "Interview question bank changed; migration is required before this session can resume."
        )
    if not isinstance(state.get("answers"), dict) or not isinstance(state.get("revision"), int):
        raise DraftError("Interview state has malformed answers or revision data.")
    if (
        not isinstance(state.get("coverage"), dict)
        or not isinstance(state.get("clarification_plan"), list)
        or not isinstance(state.get("clarifications_asked"), list)
    ):
        raise DraftError("Interview state has malformed confidence or clarification data.")
    if not isinstance(state.get("suggestions"), dict) or not isinstance(
        state.get("decision_history"), list
    ):
        raise DraftError("Interview state has malformed suggestion history.")
    if (
        not isinstance(state.get("follow_ups"), dict)
        or not isinstance(state.get("edit_requests"), dict)
        or not isinstance(state.get("manual_sections"), dict)
        or not isinstance(state.get("self_review"), dict)
        or not isinstance(state.get("review_comments"), list)
        or not isinstance(state.get("review_comment_threads"), list)
        or not isinstance(state.get("artifact_versions"), list)
        or not isinstance(state.get("publish_history"), list)
    ):
        raise DraftError(
            "Interview state has malformed follow-up, edit, or self-review data."
        )
    planning = state.get("planning")
    if not isinstance(planning, dict) or planning.get("mode") not in {"model", "fallback"}:
        raise DraftError("Interview state has malformed planning data.")


def _apply_planning_plan(
    state: dict[str, Any],
    bank: dict[str, Any],
    plan_json: str,
    expected_revision: int | None,
) -> None:
    """Validate and persist a host-generated semantic interview plan."""
    if expected_revision is not None and expected_revision != state["revision"]:
        raise RevisionConflict(
            f"Expected interview revision {expected_revision}, found {state['revision']}. "
            "Reload before applying the updated plan."
        )
    try:
        plan = json.loads(plan_json)
    except json.JSONDecodeError as exc:
        raise DraftError("The model interview plan is not valid JSON.") from exc
    if not isinstance(plan, dict) or plan.get("mode") not in {"model", "fallback"}:
        raise DraftError("The model interview plan has an invalid mode.")

    bank_by_id = {question["id"]: question for question in bank["questions"]}
    if plan["mode"] == "model":
        planned_title = " ".join(str(plan.get("feature_title") or "").split())
        if planned_title and state.get("artifact_type") == "prd":
            if len(planned_title) > 80:
                raise DraftError("The model-derived feature title must be at most 80 characters.")
            state.setdefault("intake", {})["feature_title"] = planned_title
            state["intake"].setdefault("captured_at", _now())
        coverage = plan.get("coverage")
        questions = plan.get("questions")
        if not isinstance(coverage, dict) or set(coverage) != set(bank_by_id):
            raise DraftError(
                "The model plan must assess every stable artifact coverage ID."
            )
        if not isinstance(questions, list):
            raise DraftError("The model plan questions must be a list.")
        seen: set[str] = set()
        for question in questions:
            if not isinstance(question, dict):
                raise DraftError("Every model-planned question must be an object.")
            question_id = str(question.get("id") or "")
            coverage_id = str(question.get("coverage_id") or question_id)
            if not question_id or coverage_id not in bank_by_id:
                raise DraftError("The model plan contains an unknown question or coverage ID.")
            if question_id in seen:
                raise DraftError("The model plan contains duplicate questions.")
            seen.add(question_id)
            control = question.get("response_control")
            if not isinstance(control, dict) or control.get("input_type") not in {
                "single_select", "multi_select", "textarea"
            }:
                raise DraftError("A model question has an invalid response control.")
            options = control.get("options") or []
            if control["input_type"] in {"single_select", "multi_select"}:
                if not isinstance(options, list) or not 2 <= len(options) <= 5:
                    raise DraftError("A model choice question requires two to five options.")
            if not str(question.get("prompt") or "").strip():
                raise DraftError("A model question is missing its prompt.")

        state["coverage"] = coverage
        state["clarification_plan"] = [question["id"] for question in questions]
        # Model-derived values may alter every composed section. Keep the
        # current artifact pointer until regeneration snapshots any direct
        # filesystem edits that occurred outside guided authoring.
        state["status"] = "interviewing"
        state["self_review"] = {
            "pass_count": 0,
            "max_passes": 2,
            "status": "pending",
            "findings": [],
            "artifact_sha256": None,
        }
        active = set(state["clarification_plan"])
        # Starting a session may have surfaced one deterministic placeholder
        # question while the host model was still planning. Once the complete
        # model plan arrives, discard any *unanswered* placeholder from the
        # transcript/progress set so the displayed total cannot grow after the
        # author answers the first real question. Keep answered items because
        # they remain durable author evidence across an explicit replan.
        state["clarifications_asked"] = [
            question_id
            for question_id in state.get("clarifications_asked", [])
            if question_id in active or question_id in state.get("answers", {})
        ]
        for question_id in list(state.get("suggestions", {})):
            if question_id not in state.get("answers", {}):
                state["suggestions"].pop(question_id, None)
    else:
        # Keep the deterministic planner's in-flight coverage and question
        # order intact. A failed host-model replan must not erase a confirmed
        # answer from progress or restart the fallback interview.
        pass

    state["planning"] = plan
    state["revision"] += 1
    state["updated_at"] = _now()


def _apply_compact_planning_plan(
    state: dict[str, Any],
    bank: dict[str, Any],
    compact_plan_json: str,
    expected_revision: int | None,
) -> None:
    """Normalize a host plan through the shared portable planner contract."""
    try:
        compact_plan = json.loads(compact_plan_json)
    except json.JSONDecodeError as exc:
        raise DraftError("The compact interview plan is not valid JSON.") from exc
    try:
        plan = normalize_compact_plan(
            compact_plan,
            bank,
            state,
            model=str(compact_plan.get("model") or "host-model"),
            artifact_type=str(state.get("artifact_type") or "prd"),
        )
    except (PlannerContractError, AttributeError) as exc:
        raise DraftError(f"The compact interview plan is invalid: {exc}") from exc
    _apply_planning_plan(state, bank, json.dumps(plan), expected_revision)


def _ensure_current_suggestion(
    project_root: Path,
    feature: str,
    state: dict[str, Any],
    bank: dict[str, Any],
) -> dict[str, Any] | None:
    pending = _pending_questions(state, bank)
    if not pending:
        return None
    question = pending[0]
    if question["id"] not in state["clarifications_asked"]:
        state["clarifications_asked"].append(question["id"])
    existing = state["suggestions"].get(question["id"])
    expected_fingerprint = hashlib.sha256(
        str(question.get("prompt") or "").encode()
    ).hexdigest()[:16]
    if existing and (
        existing.get("question_fingerprint") == expected_fingerprint
        or existing.get("answer")
        or existing.get("rejected")
    ):
        return existing
    suggestion = _build_suggestion(project_root, feature, state, question)
    state["suggestions"][question["id"]] = suggestion
    edit_request = state.get("edit_requests", {}).get(question["id"])
    if (
        edit_request
        and edit_request.get("status") == "pending"
        and not edit_request.get("initial_value")
        and suggestion.get("answer")
    ):
        edit_request["initial_value"] = suggestion["answer"]
    follow_up = state.get("follow_ups", {}).get(question["id"])
    targeted_follow_up = (question.get("quality") or {}).get("follow_up_prompt")
    if follow_up and follow_up.get("status") == "pending" and targeted_follow_up:
        follow_up["prompt"] = targeted_follow_up
    return suggestion


def _pending_questions(state: dict[str, Any], bank: dict[str, Any]) -> list[dict[str, Any]]:
    answers = state["answers"]
    active = _active_questions(state, bank)
    unanswered = [q for q in active if q["id"] not in answers]
    if unanswered:
        return unanswered
    return [
        q
        for q in active
        if answers.get(q["id"], {}).get("state") in {"deferred", "stale"}
    ]


def _answer_quality_gaps(question: dict[str, Any], answer: str) -> list[str]:
    quality = question.get("quality") or {}
    gaps: list[str] = []
    if len(answer.strip()) < int(quality.get("min_chars", 3)):
        gaps.append(question.get("completion_evidence") or "The answer is incomplete.")
    if re.search(r"\b(TBD|TODO|UNKNOWN)\b|<[^>]+>", answer, re.IGNORECASE):
        gaps.append("The answer still contains a placeholder or unresolved marker.")
    return gaps


def _confirmed_answers(state: dict[str, Any]) -> dict[str, str]:
    confirmed: dict[str, str] = {}
    human_confirmed: dict[str, str] = {}
    planning = state.get("planning") or {}
    if planning.get("mode") == "model":
        for question_id, item in (planning.get("coverage") or {}).items():
            resolved = str(item.get("resolved_value") or "").strip()
            if item.get("confidence_label") in {
                "confirmed", "evidence_backed", "inferred"
            } and resolved:
                confirmed[question_id] = resolved
    for question_id, record in state["answers"].items():
        if record.get("state") != "confirmed":
            continue
        coverage_id = str(record.get("coverage_id") or question_id)
        # Human-confirmed decisions always outrank model-derived coverage.
        answer = str(record.get("answer") or "").strip()
        if answer:
            previous = human_confirmed.get(coverage_id, "")
            human_confirmed[coverage_id] = (
                f"{previous}\n\n{answer}"
                if previous and answer not in previous
                else answer or previous
            )
    confirmed.update(human_confirmed)
    return confirmed


def _render_section(
    title: str, bank: dict[str, Any], confirmed: dict[str, str]
) -> str:
    relevant = [q for q in bank["questions"] if title in q["sections"]]
    blocks = []
    for question in relevant:
        answer = confirmed.get(question["id"])
        if answer:
            blocks.append(f"### {question['id']} — Confirmed interview answer\n\n{answer}")
    body = "\n\n".join(blocks) if blocks else "_No confirmed answer._"
    if title == "Scope":
        body += (
            "\n\n### In Scope\n\n"
            "_Use the confirmed P-Q7 scope decision above; separate each inclusion during review._"
            "\n\n### Out of Scope (and why)\n\n"
            "_Use the confirmed P-Q7 scope decision above; separate each "
            "exclusion and reason during review._"
        )
    return f"## {title}\n\n{body}"


def _first_sentence(text: str) -> str:
    """Return a compact, non-invented summary fragment from confirmed wording."""
    sentences = _sentences(text)
    return sentences[0] if sentences else ""


def _sentences(text: str) -> list[str]:
    """Split confirmed prose into stable sentence-sized composition units."""
    normalized = " ".join(text.split()).strip()
    if not normalized:
        return []
    protected = normalized
    abbreviations = {
        "e.g.": "e<prd-dot>g<prd-dot>",
        "i.e.": "i<prd-dot>e<prd-dot>",
    }
    for abbreviation, placeholder in abbreviations.items():
        protected = re.sub(
            re.escape(abbreviation), placeholder, protected, flags=re.IGNORECASE
        )
    parts = [
        part.strip()
        for part in re.split(r"(?<=[.!?])\s+", protected)
        if part.strip()
    ]
    return [part.replace("<prd-dot>", ".") for part in parts]


def _sentences_matching(text: str, pattern: re.Pattern[str]) -> list[str]:
    return [sentence for sentence in _sentences(text) if pattern.search(sentence)]


def _intake_behavior_sentences(intent: str) -> list[str]:
    """Return explicit requested behaviors, excluding problem-only narration."""
    request = re.compile(
        r"(?:^(?:add|show|display|provide|include)\b|"
        r"\b(?:let|allow|enable|what i want|should|must|will have|"
        r"can (?:be )?(?:select|set|show|display|highlight|sort|order)\w*)\b)",
        re.IGNORECASE,
    )
    behavior = re.compile(
        r"\b(select|set|assign|add|creat|edit|update|show|display|highlight|"
        r"sort|order|filter)\w*\b",
        re.IGNORECASE,
    )
    return [
        sentence for sentence in _sentences(intent)
        if request.search(sentence) and behavior.search(sentence)
    ]


def _intake_outcome_sentence(intent: str) -> str:
    outcome = re.compile(
        r"\b(avoid|prevent|miss|missed|forget|forgot|time-sensitive|"
        r"approach(?:es|ing)?|due earlier)\b",
        re.IGNORECASE,
    )
    matches = _sentences_matching(intent, outcome)
    direct = [
        sentence for sentence in matches
        if re.search(r"\b(miss|missed|forget|forgot|time-sensitive)\b", sentence, re.IGNORECASE)
    ]
    return (direct[-1] if direct else matches[-1]) if matches else ""


def _story_from_intake(intent: str, fallback_answer: str) -> str:
    """Compose a story from intake behavior before using a follow-up boundary."""
    direct_story = _story_from_answer(_first_sentence(intent))
    if "the confirmed outcome" not in direct_story:
        return direct_story
    behaviors = _intake_behavior_sentences(intent)
    if not behaviors:
        return _story_from_answer(fallback_answer)
    first = behaviors[0].rstrip(".?!")
    action_match = re.search(
        r"(?:let|allow|enable) users? (?:to )?(?P<action>.+)|"
        r"optional field to (?P<field_action>.+)|"
        r"^(?P<imperative>(?:add|show|display|provide|include)\s+.+)",
        first,
        re.IGNORECASE,
    )
    if not action_match:
        return _story_from_answer(fallback_answer)
    action = (
        action_match.group("action")
        or action_match.group("field_action")
        or action_match.group("imperative")
        or ""
    ).strip()
    action = action[:1].lower() + action[1:]
    outcome = _intake_outcome_sentence(intent)
    if re.search(r"\b(miss|missed|forget|forgot|time-sensitive)\b", outcome, re.IGNORECASE):
        benefit = "avoid missing time-sensitive work"
    else:
        benefit = "achieve the outcome described in the source request"
    return f"As a user, I want to {action}, so that I can {benefit}."


def _table_cell(value: str) -> str:
    """Keep confirmed prose valid inside a compact Markdown table cell."""
    return " ".join(value.split()).replace("|", "\\|")


def _markdown_table(headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> str:
    """Render a GFM table while making its column contract explicit in code."""
    header = "| " + " | ".join(headers) + " |"
    divider = "|" + "|".join("---" for _ in headers) + "|"
    body = [
        "| " + " | ".join(_table_cell(cell) for cell in row) + " |"
        for row in rows
    ]
    return "\n".join((header, divider, *body))


def _story_from_answer(answer: str) -> str:
    """Compose an outcome story from conversational audience wording."""
    sentence = _first_sentence(answer).rstrip(".!?")
    match = re.match(
        r"(?P<audience>.+?)\s+(?:need|needs|want|wants|should be able to)\s+"
        r"(?P<outcome>.+?)\s+so\s+(?:that\s+)?"
        r"(?:(?:they|the user|users?)\s+(?:can|could|may)\s+)?(?P<benefit>.+)$",
        sentence,
        re.IGNORECASE,
    )
    if not match:
        return f"As a user, I want the confirmed outcome — {sentence}."
    audience = match.group("audience").strip()
    audience = re.sub(r"^(?:all|every)\s+", "", audience, flags=re.IGNORECASE)
    if audience.lower().startswith("users who"):
        audience = f"one of the {audience}"
    elif audience.lower() == "users":
        audience = "user"
    elif audience.lower().endswith(" users"):
        audience = audience[:-1]
    audience = audience[:1].lower() + audience[1:]
    outcome = match.group("outcome").strip()
    benefit = match.group("benefit").strip()
    role = f"As {audience}" if audience.lower().startswith("one of the ") else f"As a {audience}"
    return f"{role}, I want {outcome}, so that I can {benefit}."


def _requirements_table(answers: list[str]) -> str:
    unresolved = re.compile(
        r"\b(?:unstated|unknown|unresolved|not (?:defined|decided|provided|specified)|"
        r"requires? (?:confirmation|a decision)|needs? (?:confirmation|a decision))\b",
        re.IGNORECASE,
    )
    behaviors: list[str] = []
    seen: set[str] = set()
    for answer in answers:
        for sentence in _sentences(answer):
            normalized = sentence.casefold()
            if unresolved.search(sentence) or normalized in seen:
                continue
            seen.add(normalized)
            behaviors.append(sentence)
    rows = [
        (
            f"REQ-{index}",
            "US-1",
            behavior,
            f"Pass when this observable behavior is true: {behavior}",
        )
        for index, behavior in enumerate(behaviors, 1)
    ]
    return _markdown_table(
        ("ID", "Story", "Product behavior", "Done when"), rows
    )


def _planned_requirements_table(items: list[dict[str, Any]]) -> str | None:
    rows = []
    for index, item in enumerate(items, 1):
        behavior = str(item.get("product_behavior") or "").strip()
        done_when = str(item.get("done_when") or "").strip()
        if not behavior or not done_when:
            continue
        rows.append((
            f"REQ-{index}",
            str(item.get("story_id") or "US-1"),
            behavior,
            done_when,
        ))
    if not rows:
        return None
    return _markdown_table(
        ("ID", "Story", "Product behavior", "Done when"), rows
    )


def _scope_table(scope_answer: str) -> str:
    sentences = [
        clause.strip()
        for sentence in _sentences(scope_answer)
        for clause in re.split(r";\s*", sentence)
        if clause.strip()
    ]
    excluded_sentences = [
        sentence for sentence in sentences
        if re.search(
            r"(?:^out\s*:|\b(?:(?:explicitly\s+)?excluded?|out of scope|not included|are out)\b)",
            sentence,
            re.IGNORECASE,
        )
    ]
    included_sentences = [
        sentence for sentence in sentences
        if sentence not in excluded_sentences and not DELIVERY_DETAIL_RE.search(sentence)
    ]
    included = " ".join(
        re.sub(r"^in(?:cluded)?\s*:\s*", "", sentence, flags=re.IGNORECASE)
        for sentence in included_sentences
    )
    excluded = " ".join(
        re.sub(
            r"^(?:out(?: of scope)?|not included|excluded?)\s*:\s*",
            "",
            sentence,
            flags=re.IGNORECASE,
        )
        for sentence in excluded_sentences
    )
    if not included:
        included = scope_answer
    if not excluded:
        excluded = "No explicit exclusion was confirmed."
    return _markdown_table(("Included", "Not included"), [(included, excluded)])


def _guardrails_table(guardrails: str) -> str:
    rows = [
        (
            f"GR-{index}",
            sentence,
            f"Regression check confirms: {sentence}",
        )
        for index, sentence in enumerate(_sentences(guardrails), 1)
    ]
    return _markdown_table(
        ("ID", "What must remain true", "How it will be verified"), rows
    )


def _planned_guardrails_table(items: list[dict[str, Any]]) -> str | None:
    rows = []
    for index, item in enumerate(items, 1):
        protected = str(item.get("must_remain_true") or "").strip()
        verification = str(item.get("verification") or "").strip()
        if protected and verification:
            rows.append((f"GR-{index}", protected, verification))
    if not rows:
        return None
    return _markdown_table(
        ("ID", "What must remain true", "How it will be verified"), rows
    )


def _delivery_section(delivery: str) -> str:
    if delivery.lower().startswith("no feature-specific"):
        return delivery
    sentences = _sentences(delivery)
    dependencies = [
        sentence for sentence in sentences
        if re.search(r"\bdepend(?:s|ed|ency|encies)?\b", sentence, re.IGNORECASE)
    ]
    risks = [
        sentence for sentence in sentences
        if sentence not in dependencies
        and re.search(r"\b(risk|uncertain|open decision|could|may|might)\b", sentence, re.IGNORECASE)
    ]
    parts: list[str] = []
    if dependencies:
        parts.append("**Dependencies:** " + " ".join(dependencies))
    if risks:
        rows = []
        for index, risk in enumerate(risks, 1):
            owner_match = re.match(r"(?P<owner>[^.]+?)\s+owns?\s+", risk, re.IGNORECASE)
            owner = owner_match.group("owner").strip() if owner_match else "Unassigned"
            rows.append((f"RISK-{index}", "Risk", risk, "Release readiness", owner))
        parts.append(_markdown_table(
            ("ID", "Type", "Item", "Impact or decision blocked", "Owner"), rows
        ))
    if not parts:
        parts.append(delivery)
    return "\n\n".join(parts)


def _success_table(success: str, has_measurement_answer: bool) -> str:
    if has_measurement_answer:
        outcome = success
        target = "Confirmed in the interview"
        window = "Post-launch"
    else:
        outcome = f"Post-launch validation of the hypothesis: {success}"
        target = "Provisional; baseline required"
        window = "First post-launch review"
    return _markdown_table(
        ("ID", "Outcome or signal", "Target", "Window", "Owner"),
        [("SM-1", outcome, target, window, "Unassigned")],
    )


def _planned_success_table(item: dict[str, Any] | None) -> str | None:
    if not isinstance(item, dict):
        return None
    values = tuple(
        str(item.get(key) or "").strip()
        for key in ("outcome_or_signal", "target", "window", "owner")
    )
    if not all(values):
        return None
    return _markdown_table(
        ("ID", "Outcome or signal", "Target", "Window", "Owner"),
        [("SM-1", *values)],
    )


def _has_review_edit(state: dict[str, Any], question_ids: tuple[str, ...]) -> bool:
    return any(
        (state.get("answers", {}).get(question_id) or {}).get("decision")
        == "review_edited"
        for question_id in question_ids
    )


def _render_prd_section(
    title: str, question_ids: tuple[str, ...], confirmed: dict[str, str]
) -> str:
    answers = [confirmed[qid] for qid in question_ids if confirmed.get(qid)]
    body = "\n\n".join(answers)
    if not body:
        body = "No feature-specific item was identified from the confirmed inputs."
    return f"## {title}\n\n{body}"


def _render_prd_artifact(
    feature: str, state: dict[str, Any], bank: dict[str, Any]
) -> str:
    """Render V1 only from usable interview evidence, without filler copy."""
    confirmed = _confirmed_answers(state)
    planning = state.get("planning") or {}
    composition = (
        planning.get("composition")
        if planning.get("mode") == "model"
        and isinstance(planning.get("composition"), dict)
        else {}
    )
    display_name = _display_name(feature, state)
    owner = next(
        (
            record.get("actor")
            for record in state["answers"].values()
            if record.get("state") == "confirmed" and record.get("actor")
        ),
        "Unassigned",
    )
    updated = state.get("updated_at", "")[:10]
    header = (
        f"# PRD: {display_name}\n\n"
        "| Status | Owner | Updated |\n"
        "|---|---|---|\n"
        f"| Draft | {owner} | {updated} |\n\n"
        f"<!-- Interview: {bank['version']}; revision: {state['revision']} -->"
    )
    intent = str((state.get("intake") or {}).get("feature_description") or "")
    intake_behaviors = _intake_behavior_sentences(intent)
    intake_outcome = _intake_outcome_sentence(intent)
    problem = confirmed.get("P-Q1") or _first_sentence(intent)
    audience_answer = confirmed.get("P-Q2", "")
    hypothesis_answer = (
        confirmed.get("P-Q3")
        or " ".join([*intake_behaviors, intake_outcome]).strip()
        or audience_answer
    )
    hypothesis = _first_sentence(hypothesis_answer)
    user_story = _story_from_intake(intent, audience_answer)
    summary_parts: list[str] = []
    for value in (problem, _first_sentence(audience_answer), hypothesis):
        fragment = _first_sentence(value) if value else ""
        if fragment and fragment not in summary_parts:
            summary_parts.append(fragment)
    summary = " ".join(summary_parts[:3])
    behavior_question_ids = ("P-Q4", "P-Q5")
    resolved_behaviors = [
        confirmed[question_id]
        for question_id in behavior_question_ids
        if confirmed.get(question_id)
    ]
    # Compact planning resolves individual coverage decisions but deliberately
    # does not precompose the final table. Preserve every distinct behavior
    # already stated in the brief, then add the interview's clarified flows.
    # Treating one clarified answer as a replacement for the brief previously
    # collapsed multi-rule features into a single requirement.
    behavior_answers = [*intake_behaviors, *resolved_behaviors]
    planned_requirements = (
        _planned_requirements_table(composition.get("requirements") or [])
        if not _has_review_edit(state, behavior_question_ids)
        else None
    )
    requirements = planned_requirements or _requirements_table(behavior_answers)
    scope_answer = confirmed.get("P-Q7", "")
    guardrail_matches = _sentences_matching(
        " ".join(part for part in (audience_answer, hypothesis_answer) if part),
        re.compile(
            r"\b(remain|unchanged|must not|continue|regress|compatible|stay valid)\b",
            re.IGNORECASE,
        ),
    )
    guardrails = " ".join(guardrail_matches) or hypothesis
    scoped_delivery_parts = _sentences_matching(scope_answer, DELIVERY_DETAIL_RE)
    scoped_parts = [
        sentence for sentence in _sentences(scope_answer)
        if sentence not in scoped_delivery_parts
    ]
    inclusion = " ".join(intake_behaviors)
    # Prefer the explicit/model-resolved scope decision. The broad intake
    # behavior is useful only when no scope value exists, and otherwise creates
    # duplicate or less precise table entries.
    scope_source = " ".join(scoped_parts) or scope_answer or inclusion
    planned_scope = composition.get("scope")
    if (
        isinstance(planned_scope, dict)
        and not _has_review_edit(state, ("P-Q7",))
        and str(planned_scope.get("included") or "").strip()
        and str(planned_scope.get("not_included") or "").strip()
    ):
        scope = _markdown_table(
            ("Included", "Not included"),
            [(
                str(planned_scope["included"]),
                str(planned_scope["not_included"]),
            )],
        )
    else:
        scope = _scope_table(scope_source)
    delivery = (
        confirmed.get("P-Q8")
        or " ".join(scoped_delivery_parts)
        or "No feature-specific rollout, migration, dependency, or open decision was identified."
    )
    success = confirmed.get("P-Q6") or hypothesis or intake_outcome
    planned_guardrails = (
        _planned_guardrails_table(composition.get("guardrails") or [])
        if not _has_review_edit(state, ("P-Q2", "P-Q3", "P-Q8"))
        else None
    )
    planned_success = (
        _planned_success_table(composition.get("success"))
        if not _has_review_edit(state, ("P-Q6",))
        else None
    )

    section_bodies = [
        ("Summary", summary),
        ("Problem & Evidence", problem or "No grounded problem statement was provided."),
        ("Hypothesis", hypothesis),
        ("User Stories", _markdown_table(
            ("ID", "Story", "Priority"), [("US-1", user_story, "Must")]
        )),
        ("Requirements & Acceptance", requirements),
        ("Scope", scope),
        (
            "Guardrails / Must Not Regress",
            planned_guardrails or _guardrails_table(guardrails),
        ),
    ]
    section_bodies.insert(7, ("Delivery, Risks & Open Questions", _delivery_section(delivery)))
    section_bodies.append((
        "Success",
        planned_success or _success_table(success, bool(confirmed.get("P-Q6"))),
    ))
    manual_sections = state.get("manual_sections", {})
    sections = []
    for title, body in section_bodies:
        final_body = manual_sections.get(title, {}).get("body", body).strip()
        if not final_body:
            raise DraftError(
                f"The PRD is not ready: '{title}' has no meaningful source value."
            )
        sections.append(f"## {title}\n\n{final_body}")

    references = []
    seen_paths = set()
    for suggestion in state.get("suggestions", {}).values():
        for source in suggestion.get("sources", []):
            path = source.get("path")
            if path and path not in seen_paths:
                seen_paths.add(path)
                references.append(f"- `{path}`")
    references_body = (
        manual_sections.get("References", {}).get("body")
        or "\n".join(references)
        or "No external research, policy, or prior decision was supplied for this PRD."
    )
    sections.append(f"## References\n\n{references_body}")
    return header + "\n\n" + "\n\n".join(sections) + "\n"


PRD_SECTION_SOURCES: dict[str, tuple[str, ...]] = {
    "Problem & Evidence": ("P-Q1",),
    "User Stories": ("P-Q2",),
    "Scope": ("P-Q7",),
    "Success": ("P-Q6",),
    "References": (),
}


def _prd_section_sources(state: dict[str, Any], title: str) -> tuple[str, ...]:
    """Return only the source decisions actually composed into a section."""
    confirmed = _confirmed_answers(state)
    if title == "Summary":
        return tuple(
            question_id
            for question_id in ("P-Q1", "P-Q2", "P-Q3")
            if question_id == "P-Q1" or confirmed.get(question_id)
        )
    if title in {"Hypothesis", "Guardrails / Must Not Regress"}:
        return ("P-Q3",) if confirmed.get("P-Q3") else ("P-Q2",)
    if title == "Requirements & Acceptance":
        return tuple(
            question_id
            for question_id in ("P-Q4", "P-Q5")
            if confirmed.get(question_id)
        )
    if title == "Delivery, Risks & Open Questions":
        if confirmed.get("P-Q8"):
            return ("P-Q8",)
        if confirmed.get("P-Q7") and DELIVERY_DETAIL_RE.search(confirmed["P-Q7"]):
            return ("P-Q7",)
        return ()
    if title == "Success":
        if confirmed.get("P-Q6"):
            return ("P-Q6",)
        return ("P-Q3",) if confirmed.get("P-Q3") else ("P-Q2",)
    return PRD_SECTION_SOURCES.get(title, ())


def _applicable_prd_sections(state: dict[str, Any]) -> list[str]:
    """Return the mandatory PRD Proposal section contract in document order."""
    core = [
        "Summary", "Problem & Evidence", "Hypothesis", "User Stories",
        "Requirements & Acceptance", "Scope", "Guardrails / Must Not Regress",
        "Delivery, Risks & Open Questions",
    ]
    core.extend(("Success", "References"))
    return core


def _artifact_sections(
    state: dict[str, Any], bank: dict[str, Any]
) -> list[dict[str, Any]]:
    """Machine-readable section to source-question map for clients."""
    artifact_type = state["artifact_type"]
    sections: list[dict[str, Any]] = []
    titles = (
        _applicable_prd_sections(state)
        if artifact_type == "prd"
        else ARTIFACTS[artifact_type]["sections"]
    )
    for title in titles:
        if artifact_type == "prd":
            question_ids = list(_prd_section_sources(state, title))
        else:
            question_ids = [
                question["id"]
                for question in bank["questions"]
                if title in question["sections"]
            ]
        answers = state.get("answers", {})
        composed_answers = _confirmed_answers(state)
        coverage = state.get("coverage", {})
        source_answers: dict[str, str] = {}
        for question_id in question_ids:
            source_answer = answers.get(question_id, {}).get("answer") or composed_answers.get(question_id)
            if not source_answer and question_id == "P-Q1":
                source_answer = (state.get("intake") or {}).get("feature_description")
            if source_answer:
                source_answers[question_id] = source_answer
        manual_section = state.get("manual_sections", {}).get(title)
        if manual_section:
            section_state = (
                "manual_stale"
                if manual_section.get("status") == "needs_reconciliation"
                else "reviewed"
                if manual_section.get("source") == "review_comments"
                else "manual"
            )
        elif question_ids and all(
            answers.get(qid, {}).get("state") == "confirmed"
            or coverage.get(qid, {}).get("confidence_label") == "evidence_backed"
            or (qid == "P-Q1" and bool((state.get("intake") or {}).get("feature_description")))
            for qid in question_ids
        ):
            section_state = (
                "confirmed"
                if all(answers.get(qid, {}).get("state") == "confirmed" for qid in question_ids)
                else "evidence_backed"
            )
        elif any(answers.get(qid, {}).get("state") == "deferred" for qid in question_ids):
            section_state = "deferred"
        elif any(
            coverage.get(qid, {}).get("confidence_label") == "unresolved"
            for qid in question_ids
        ):
            section_state = "unresolved"
        elif question_ids:
            section_state = "provisional"
        else:
            section_state = "generated"
        sections.append({
            "title": title,
            "question_ids": question_ids,
            "coverage_ids": question_ids,
            "state": section_state,
            "source_answer": source_answers.get(question_ids[0]) if question_ids else None,
            "source_answers": source_answers,
            "manual_override": (
                {
                    "source": manual_section.get("source") or "section_editor",
                    "status": manual_section.get("status") or "current",
                    "actor": manual_section.get("actor"),
                    "actor_email": manual_section.get("actor_email"),
                    "revision": manual_section.get("revision"),
                    "based_on_artifact_sha256": manual_section.get("based_on_artifact_sha256"),
                    "stale_reason": manual_section.get("stale_reason"),
                }
                if manual_section
                else None
            ),
        })
    return sections


def _mark_manual_sections_stale(
    state: dict[str, Any],
    bank: dict[str, Any],
    coverage_id: str,
    changed_revision: int,
) -> None:
    """Preserve manual prose while making source-answer divergence explicit."""
    for title, manual in state.get("manual_sections", {}).items():
        if state["artifact_type"] == "prd":
            sources = _prd_section_sources(state, title)
        else:
            sources = tuple(
                question["id"]
                for question in bank["questions"]
                if title in question.get("sections", [])
            )
        if coverage_id not in sources:
            continue
        manual["status"] = "needs_reconciliation"
        manual["stale_reason"] = f"Source answer {coverage_id} changed"
        manual["source_answer_changed_revision"] = changed_revision


def _render_artifact(feature: str, state: dict[str, Any], bank: dict[str, Any]) -> str:
    if state["artifact_type"] == "prd":
        return _render_prd_artifact(feature, state, bank)
    confirmed = _confirmed_answers(state)
    display_name = feature.replace("-", " ").title()
    artifact_type = state["artifact_type"]
    label = ARTIFACTS[artifact_type]["label"]
    header = (
        f"# {label}: {display_name}\n\n"
        "**Status:** Draft — requires human review  \n"
        f"**Feature:** `{feature}`  \n"
        f"**Interview:** `{bank['version']}`  \n"
        f"**Interview revision:** `{state['revision']}`"
    )
    if artifact_type in {"design", "rfc"}:
        upstream = state["upstream"]["prd"]
        header += (
            "  \n**Product source:** [PRD](prd.md)  \n"
            f"**Product source hash:** `{upstream['sha256']}`  \n"
            f"**Product interview revision:** `{upstream['interview_revision']}`\n\n"
            f"> This {label} contract maps confirmed {ARTIFACTS[artifact_type]['persona']} "
            "answers to the linked Product requirements. Workbench has not created "
            "independent product scope."
        )
        if artifact_type == "rfc":
            design = state["upstream"]["design"]
            header += (
                "  \n**Design source:** [Design](design.md)  \n"
                f"**Design source hash:** `{design['sha256']}`  \n"
                f"**Design interview revision:** `{design['interview_revision']}`\n\n"
                "> The technical contract must implement both the published Product "
                "and Design obligations without silently redefining either."
            )
    else:
        header += (
            "\n\n> This document maps confirmed interview answers into the PRD template. "
            "Workbench has not invented or expanded the product decisions."
        )
    sections = [
        _render_section(title, bank, confirmed)
        for title in ARTIFACTS[artifact_type]["sections"]
    ]
    return header + "\n\n" + "\n\n".join(sections) + "\n"


def _ensure_define_compatibility(
    project_root: Path,
    feature: str,
    state: dict[str, Any],
    content: str,
    artifact_path: str,
    dashboard_url: str,
) -> None:
    """Write only missing ceremony inputs plus the selected generated draft."""
    feature_dir = _feature_dir(project_root, feature)
    artifact_type = state["artifact_type"]
    name, email = _actor(project_root)
    now = _now()
    problem = _confirmed_answers(state).get("P-Q1", f"Define {feature}")

    intent_path = feature_dir / "intent.json"
    if not intent_path.exists():
        _write_json(intent_path, {
            "text": problem,
            "author": name,
            "author_email": email,
            "created_at": now,
            "feature_name": feature,
        })

    ceremony_path = feature_dir / "ceremony.json"
    if not ceremony_path.exists():
        _write_json(ceremony_path, {
            "feature_name": feature,
            "author": name,
            "author_email": email,
            "created_at": now,
            "is_multiplayer": (project_root / ".speed" / "shared").is_dir(),
            "current_revision": INITIAL_REVISION,
            "revision_count": 1,
            "revisions": {
                INITIAL_REVISION: {
                    "revision_id": INITIAL_REVISION,
                    "parent_id": None,
                    "status": "drafting",
                    "spec_content_hash": ZERO_HASH,
                    "context_package_hash": ZERO_HASH,
                    "validation_hash": ZERO_HASH,
                    "created_at": now,
                    "reason": None,
                }
            },
            "reflog": [],
        })

    claim_path = feature_dir / f"claim-{artifact_type}.json"
    if not claim_path.exists():
        _write_json(claim_path, {
            "spec_type": artifact_type,
            "claimant": name,
            "claimant_email": email,
            "claimed_at": now,
            "last_activity_at": now,
            "released_at": None,
        })

    context_path = feature_dir / "context-package.json"
    if not context_path.exists():
        _write_json(context_path, {
            "intent": problem,
            "feature_name": feature,
            "scoped_area": [],
            "codebase": [],
            "learnings": [],
            "defects": [],
            "project_knowledge": [],
            "vision_status": "missing",
            "vision_content": None,
            "related_features": [],
            "audit_history": [],
            "assembled_at": now,
            "sources_status": {"guided_interview": "ok"},
            "scoping_method": "guided_interview",
            "low_confidence": False,
            "bluf_summary": problem,
        })

    draft_record = {
        "feature_name": feature,
        "spec_type": artifact_type,
        "status": state.get("status", "drafted"),
        "content": content,
        "file_path": artifact_path,
        "template_name": f"{artifact_type}.md",
        "generated_at": now,
        "child_specs": [],
    }
    if artifact_type in {"design", "rfc"}:
        draft_record["upstream"] = state["upstream"]
    draft_record["authoring"] = {
        "revision": state["revision"],
        "published_revision": state.get("published_revision"),
        "publish_history": state.get("publish_history", []),
        "self_review": state["self_review"],
        "feature_title": _display_name(feature, state),
        "sections": _artifact_sections(state, _load_question_bank(artifact_type)),
        "authoring_url": f"{dashboard_url}/authoring/{artifact_type}",
    }
    _write_json(feature_dir / f"draft-{artifact_type}.json", draft_record)

    # Keep the package index derived from machine evidence. It is navigation,
    # never an independent gate that a user has to maintain by hand.
    latest_audit_path = feature_dir / "define-audit-latest.json"
    latest_audit = _read_json(latest_audit_path) or {}
    current_hashes: dict[str, str] = {}
    rows: list[str] = []
    next_stage: str | None = None
    for kind in ARTIFACTS:
        item_state = state if kind == artifact_type else (
            _read_json(feature_dir / f"authoring-{kind}.json") or {}
        )
        item_artifact = item_state.get("artifact") or {}
        item_path = project_root / "specs" / feature / f"{kind}.md"
        item_hash = hashlib.sha256(item_path.read_bytes()).hexdigest() if item_path.is_file() else ""
        if item_hash:
            current_hashes[kind] = item_hash
        is_current = bool(item_hash and item_hash == item_artifact.get("sha256"))
        item_status = str(item_state.get("status") or "missing")
        if next_stage is None and (item_status != "published" or not is_current):
            next_stage = kind
        claim = _read_json(feature_dir / f"claim-{kind}.json") or {}
        commit = _read_json(feature_dir / f"commit-{kind}.json") or {}
        ratification = _read_json(feature_dir / f"ratification-{kind}.json") or {}
        owner = claim.get("claimant") or commit.get("claimant") or "Unassigned"
        approval = "Ratified" if ratification.get("ratified") is True else "Pending"
        status_label = item_status.replace("_", " ").title()
        rows.append(
            f"| [{ARTIFACTS[kind]['label']}]({kind}.md) | {status_label} | "
            f"{item_state.get('published_revision') if item_state.get('published_revision') is not None else '—'} | "
            f"`{item_hash[:12] if item_hash else '—'}` | {owner} | {approval} |"
        )
    if latest_audit and (latest_audit.get("inputs") or {}).get("artifacts") != current_hashes:
        latest_audit["status"] = "stale"
        latest_audit["stale"] = True
        _write_json(latest_audit_path, latest_audit)
    audit_status = str(latest_audit.get("status") or "not run").replace("_", " ").title()
    next_text = (
        f"Continue `{next_stage.upper()}` authoring."
        if next_stage
        else "Run `workbench audit " + feature + "`."
        if latest_audit.get("status") != "passed"
        else "Complete artifact ratification, then the unsupported ADR and evaluation gates."
    )
    index_content = (
        f"# Define Package: {feature}\n\n"
        "**Plan readiness:** Blocked  \n"
        "**Discover handoff:** Not connected  \n"
        f"**Connected audit:** {audit_status}\n\n"
        "| Artifact | Status | Version | SHA-256 | Owner | Approval |\n"
        "|---|---|---|---|---|---|\n"
        + "\n".join(rows)
        + "\n\n## Next action\n\n"
        + next_text
        + "\n\n> ADR and evaluation-specification stages remain explicit unsupported gates; "
        "this package cannot yet be reported Plan-ready.\n"
    )
    _atomic_write(project_root / "specs" / feature / "index.md", index_content)


def _generate(
    project_root: Path,
    feature: str,
    state: dict[str, Any],
    bank: dict[str, Any],
    dashboard_base: str,
) -> None:
    pending = _pending_questions(state, bank)
    if pending:
        deferred = [q["id"] for q in pending if q["id"] in state["answers"]]
        persona = ARTIFACTS[state["artifact_type"]]["persona"]
        raise DraftError(
            f"All required {persona} questions must be confirmed before generation"
            + (f"; deferred: {', '.join(deferred)}" if deferred else ".")
        )

    artifact_type = state["artifact_type"]
    if artifact_type in {"design", "rfc"}:
        _validate_pinned_upstream(
            state, "prd", _prd_upstream(project_root, feature)
        )
    if artifact_type == "rfc":
        _validate_pinned_upstream(
            state, "design", _design_upstream(project_root, feature)
        )
    artifact_path = f"specs/{feature}/{artifact_type}.md"
    dashboard_url = f"{dashboard_base.rstrip('/')}/define/{feature}"
    if _snapshot_current_artifact(project_root, state):
        state["revision"] += 1
        state["updated_at"] = _now()
    content = _render_artifact(feature, state, bank)
    artifact_file = project_root / artifact_path
    _atomic_write(artifact_file, content)
    state["status"] = "drafted"
    _ensure_define_compatibility(
        project_root, feature, state, content, artifact_path, dashboard_url
    )
    state["artifact"] = {
        "path": artifact_path,
        "authoring_url": f"{dashboard_url}/authoring/{artifact_type}",
        "sha256": hashlib.sha256(content.encode()).hexdigest(),
        "generated_at": _now(),
        "dashboard_url": dashboard_url,
    }
    versions = state.setdefault("artifact_versions", [])
    version = {
        "revision": state["revision"],
        "content": content,
        "created_at": state["artifact"]["generated_at"],
        "status": "draft",
        "source": (
            state.get("decision_history", [{}])[-1].get("action", "generated")
            if state.get("decision_history") else "generated"
        ),
    }
    versions[:] = [item for item in versions if item.get("revision") != state["revision"]]
    versions.append(version)
    versions[:] = versions[-20:]
    if artifact_type in {"design", "rfc"}:
        state["artifact"]["upstream"] = state["upstream"]


def _publish_artifact(
    project_root: Path,
    state: dict[str, Any],
    expected_revision: int | None,
    actor: tuple[str, str],
) -> None:
    """Create an immutable published snapshot without losing editable history."""
    if expected_revision is not None and expected_revision != state["revision"]:
        raise RevisionConflict(
            f"Expected interview revision {expected_revision}, found {state['revision']}. "
            "Reload before publishing."
        )
    if (
        state.get("status") == "published"
        and state.get("published_revision") == state.get("revision")
    ):
        return
    if (state.get("self_review") or {}).get("status") != "passed":
        raise DraftError("Resolve every blocking self-review finding before publishing.")
    open_comments = [
        item for item in state.get("review_comment_threads", [])
        if item.get("status") == "open"
    ]
    if open_comments:
        raise DraftError(
            f"Apply or resolve {len(open_comments)} open review comment(s) before publishing."
        )
    stale_overrides = [
        title for title, item in state.get("manual_sections", {}).items()
        if item.get("status") == "needs_reconciliation"
    ]
    if stale_overrides:
        raise DraftError(
            "Reconcile manual edits after their source answers changed: "
            + ", ".join(stale_overrides)
        )
    artifact = state.get("artifact") or {}
    artifact_path = artifact.get("path")
    if not artifact_path:
        raise DraftError("Generate a draft before publishing it.")
    try:
        content = (project_root / artifact_path).read_text(encoding="utf-8")
    except OSError as exc:
        raise DraftError("The generated artifact could not be read for publishing.") from exc

    _snapshot_current_artifact(project_root, state)
    actor_name, actor_email = actor
    published_at = _now()
    next_revision = state["revision"] + 1
    content = re.sub(r"(?m)^\| Draft \|", "| Published |", content, count=1)
    content = content.replace(
        "Status: Draft — requires human review",
        "Status: Published",
        1,
    )
    _atomic_write(project_root / artifact_path, content)
    artifact["sha256"] = hashlib.sha256(content.encode()).hexdigest()
    artifact["generated_at"] = published_at
    versions = state.setdefault("artifact_versions", [])
    versions.append({
        "revision": next_revision,
        "content": content,
        "created_at": published_at,
        "published_at": published_at,
        "status": "published",
        "source": "publish",
        "interview_revision": next_revision,
        "question_bank_version": state.get("question_bank_version"),
    })
    versions[:] = versions[-20:]
    state["revision"] = next_revision
    state["published_revision"] = next_revision
    state["status"] = "published"
    state["updated_at"] = published_at
    state.setdefault("publish_history", []).append({
        "revision": next_revision,
        "published_at": published_at,
        "actor": actor_name,
        "actor_email": actor_email,
        "sha256": artifact["sha256"],
    })
    state["decision_history"].append({
        "question_id": None,
        "suggestion_id": None,
        "action": "draft_published",
        "answer": f"Published {ARTIFACTS[state['artifact_type']]['label']} v{next_revision}.",
        "actor": actor_name,
        "actor_email": actor_email,
        "at": published_at,
        "revision": next_revision,
    })
    dashboard_url = artifact.get("dashboard_url")
    if not dashboard_url:
        dashboard_url = f"http://localhost:3000/define/{state['feature_name']}"
    _ensure_define_compatibility(
        project_root,
        state["feature_name"],
        state,
        content,
        artifact_path,
        dashboard_url,
    )


def _artifact_quality_findings(
    state: dict[str, Any], content: str
) -> list[dict[str, Any]]:
    """Check rendered structure and traceability, not only answer length."""
    findings: list[dict[str, Any]] = []
    artifact_type = state["artifact_type"]
    without_comments = re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL)
    if re.search(
        r"\b(?:TBD|TODO|UNKNOWN)\b|_No confirmed answer\._|"
        r"No grounded problem statement was provided",
        without_comments,
        re.IGNORECASE,
    ):
        findings.append({
            "id": "artifact-unresolved-placeholder",
            "kind": "placeholder",
            "question_id": "P-Q1" if artifact_type == "prd" else None,
            "message": "Generated artifact still contains unresolved placeholder content.",
            "blocking": True,
        })

    lines = without_comments.splitlines()
    for index, line in enumerate(lines):
        if not line.lstrip().startswith("|"):
            continue
        if index and lines[index - 1].lstrip().startswith("|"):
            continue
        table: list[str] = []
        cursor = index
        while cursor < len(lines) and lines[cursor].lstrip().startswith("|"):
            table.append(lines[cursor])
            cursor += 1
        widths = [row.count("|") for row in table]
        if len(table) < 2 or any(width != widths[0] for width in widths[1:]):
            findings.append({
                "id": f"markdown-table-{index + 1}",
                "kind": "invalid_table",
                "question_id": None,
                "message": f"Markdown table near line {index + 1} has inconsistent columns.",
                "blocking": True,
            })

    for title, manual in state.get("manual_sections", {}).items():
        if manual.get("status") == "needs_reconciliation":
            findings.append({
                "id": "stale-manual-" + re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-"),
                "kind": "stale_manual_override",
                "question_id": None,
                "message": f"Manual section '{title}' must be reconciled with its changed source answer.",
                "blocking": True,
            })

    if artifact_type == "prd":
        requirement_rows = [
            line for line in lines if re.match(r"^\|\s*REQ-\d+\s*\|", line)
        ]
        requirement_ids = [
            re.match(r"^\|\s*(REQ-\d+)\s*\|", line).group(1)
            for line in requirement_rows
        ]
        if not requirement_rows:
            findings.append({
                "id": "prd-stable-requirements",
                "kind": "missing_stable_ids",
                "question_id": "P-Q4",
                "message": "PRD requirements need stable REQ-n identifiers and observable completion behavior.",
                "blocking": True,
            })
        elif len(requirement_ids) != len(set(requirement_ids)):
            findings.append({
                "id": "prd-duplicate-requirements",
                "kind": "duplicate_stable_ids",
                "question_id": "P-Q4",
                "message": "PRD requirement identifiers must be unique.",
                "blocking": True,
            })
        if "No explicit exclusion was confirmed." in without_comments:
            findings.append({
                "id": "prd-scope-boundary",
                "kind": "missing_scope_boundary",
                "question_id": "P-Q7",
                "message": "Scope needs at least one explicit V1 exclusion or a confirmed statement that none applies.",
                "blocking": True,
            })
    return findings


def _self_review(
    project_root: Path,
    feature: str,
    state: dict[str, Any],
    bank: dict[str, Any],
) -> None:
    """Run deterministic review and keep unusable drafts hidden until repaired."""
    review = state["self_review"]
    review["pass_count"] += 1
    artifact_path = project_root / state["artifact"]["path"]
    content = artifact_path.read_text(encoding="utf-8")
    findings: list[dict[str, Any]] = []

    for question in bank["questions"]:
        record = state["answers"].get(question["id"], {})
        for gap in record.get("quality_gaps", []):
            findings.append({
                "id": f"quality-{question['id'].lower()}",
                "kind": "answer_quality",
                "question_id": question["id"],
                "message": f"Answer does not yet show: {gap}",
                "blocking": True,
            })
        answer = record.get("answer") or ""
        if re.search(r"\b(TBD|TODO|UNKNOWN)\b|<[^>]+>", answer, re.IGNORECASE):
            findings.append({
                "id": f"placeholder-{question['id'].lower()}",
                "kind": "placeholder",
                "question_id": question["id"],
                "message": "Confirmed answer contains a placeholder or unresolved marker.",
                "blocking": True,
            })

    required_headings = (
        _applicable_prd_sections(state)
        if state["artifact_type"] == "prd"
        else ARTIFACTS[state["artifact_type"]]["sections"]
    )
    for heading in required_headings:
        if not re.search(rf"^## {re.escape(heading)}\s*$", content, re.MULTILINE):
            source = next(
                (q["id"] for q in bank["questions"] if heading in q["sections"]),
                None,
            )
            findings.append({
                "id": "missing-" + re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-"),
                "kind": "missing_section",
                "question_id": source,
                "message": f"Generated artifact is missing required section: {heading}.",
                "blocking": True,
            })

    findings.extend(_artifact_quality_findings(state, content))
    findings = list({finding["id"]: finding for finding in findings}.values())
    review["findings"] = findings
    review["artifact_sha256"] = state["artifact"]["sha256"]
    review["reviewed_at"] = _now()
    if not findings:
        review["status"] = "passed"
        state["status"] = "drafted"
        _ensure_define_compatibility(
            project_root,
            feature,
            state,
            content,
            state["artifact"]["path"],
            state["artifact"]["dashboard_url"],
        )
        return

    review["status"] = "needs_repair"
    for question_id in dict.fromkeys(
        finding["question_id"] for finding in findings if finding["question_id"]
    ):
        record = state["answers"].get(question_id)
        if record and record.get("state") == "confirmed":
            record["state"] = "stale"
            record["stale_reason"] = "self_review"
    state["status"] = "review_repair"
    _ensure_define_compatibility(
        project_root,
        feature,
        state,
        content,
        state["artifact"]["path"],
        state["artifact"]["dashboard_url"],
    )


def _artifact_version_ordinal(
    state: dict[str, Any], revision: int | None
) -> int | None:
    """Map an internal checkpoint revision to its user-facing artifact version."""
    versions = sorted(
        (
            item
            for item in state.get("artifact_versions", [])
            if isinstance(item, dict) and isinstance(item.get("revision"), int)
        ),
        key=lambda item: item["revision"],
    )
    for ordinal, version in enumerate(versions, start=1):
        if version["revision"] == revision:
            return ordinal
    return None


def _result(state: dict[str, Any], bank: dict[str, Any]) -> dict[str, Any]:
    pending = _pending_questions(state, bank)
    active_questions = _active_questions(state, bank)
    active_ids = {question["id"] for question in active_questions}
    progress_ids = active_ids | set(state.get("clarifications_asked", []))
    current = pending[0] if pending else None
    deferred = [
        question_id
        for question_id, record in state["answers"].items()
        if record.get("state") == "deferred"
    ]
    status = state["status"]
    if current:
        only_deferred = all(
            state["answers"].get(q["id"], {}).get("state") == "deferred"
            for q in pending
        )
        status = "blocked" if only_deferred else "question"
    artifact = state.get("artifact") or {}
    suggestion = state.get("suggestions", {}).get(current["id"]) if current else None
    follow_up = state.get("follow_ups", {}).get(current["id"]) if current else None
    edit_request = state.get("edit_requests", {}).get(current["id"]) if current else None
    findings = [
        finding
        for finding in state.get("self_review", {}).get("findings", [])
        if current and finding.get("question_id") == current["id"]
    ]
    response_control = None
    resume_step = None
    if current:
        if follow_up and follow_up.get("status") == "pending":
            follow_up_initial = str(follow_up.get("initial_answer") or "")
            suggested_initial = str((suggestion or {}).get("answer") or "")
            response_control = {
                "id": "follow_up_answer",
                "input_type": "textarea",
                "prompt": follow_up["prompt"],
                "initial_value": (
                    suggested_initial
                    if suggested_initial and len(follow_up_initial.split()) < 5
                    else follow_up_initial
                ),
                "submit_action": "answer",
            }
        elif edit_request and edit_request.get("status") == "pending":
            response_control = {
                "id": "edited_suggestion",
                "input_type": "textarea",
                "prompt": "Edit the suggested response, then submit your version.",
                "initial_value": edit_request.get("initial_value") or "",
                "submit_action": "answer",
            }
        elif findings:
            response_control = {
                "id": "revised_answer",
                "input_type": "textarea",
                "prompt": "Revise the answer to resolve the self-review findings.",
                "initial_value": state["answers"].get(current["id"], {}).get("answer") or "",
                "submit_action": "answer",
            }
        elif suggestion and suggestion.get("rejected"):
            response_control = {
                "id": "replacement_answer",
                "input_type": "textarea",
                "prompt": "Provide your own answer to replace the rejected suggestion.",
                "initial_value": "",
                "submit_action": "answer",
            }
        elif (
            (state.get("planning") or {}).get("mode") == "model"
            and isinstance(current.get("response_control"), dict)
        ):
            response_control = dict(current["response_control"])
            if response_control.get("input_type") == "textarea":
                response_control["initial_value"] = (
                    response_control.get("initial_value")
                    or (suggestion or {}).get("answer")
                    or ""
                )
        else:
            options = []
            if suggestion and suggestion.get("accept_ready"):
                options.append({
                    "value": "accept",
                    "label": "Accept suggestion",
                })
            options.append({
                "value": "edit",
                "label": (
                    "Edit suggestion"
                    if suggestion and suggestion.get("answer")
                    else "Answer question"
                ),
            })
            if suggestion and suggestion.get("answer"):
                options.append({
                    "value": "reject",
                    "label": "Reject suggestion",
                })
            options.append({
                "value": "defer",
                "label": "Defer",
            })
            response_control = {
                "id": "suggestion_action",
                "input_type": "single_select",
                "prompt": "How would you like to respond?",
                "options": options,
            }
        resume_step = {
            "question_id": current["id"],
            "control_id": response_control["id"],
            "revision": state["revision"],
        }
    questions_by_id = {
        question["id"]: question for question in bank.get("questions", [])
    }
    interview = []
    for question_id in state.get("clarifications_asked", []):
        record = state.get("answers", {}).get(question_id, {})
        answer = record.get("answer")
        if not answer and record.get("state") != "deferred":
            continue
        coverage_id = str(record.get("coverage_id") or question_id)
        question = questions_by_id.get(coverage_id, {})
        stored_prompt = str(record.get("question_prompt") or "")
        prompt = stored_prompt
        if not prompt or prompt.startswith("Draft review update for "):
            prompt = _contextualize_question(question, state).get("prompt", "")
        interview.append({
            "id": question_id,
            "coverage_id": coverage_id,
            # Coverage edits keep the original interview question visible
            # instead of replacing it with an internal review label.
            "prompt": prompt,
            "answer": answer,
            "state": record.get("state") or "answered",
            "decision": record.get("decision"),
            "confirmed_at": record.get("confirmed_at"),
        })
    # Interview-time artifacts stay private. A failed structural review with no
    # source question to reopen is different: the interview is complete and the
    # author needs the embedded editor to repair the generated document. Expose
    # that document without describing it as a ready V1.
    repair_preview = (
        status == "review_repair"
        and current is None
        and bool(artifact.get("path"))
    )
    draft_ready = (
        status in {"drafted", "published"} and bool(artifact.get("path"))
    ) or repair_preview
    published_version = _artifact_version_ordinal(
        state, state.get("published_revision")
    )
    return {
        "skill": SKILL,
        "implementation": _implementation(state["artifact_type"]),
        "planning": state.get("planning"),
        "review_comments": state.get("review_comment_threads", []),
        "versions": state.get("artifact_versions", []) if draft_ready else [],
        "published_revision": state.get("published_revision"),
        "publish_history": state.get("publish_history", []),
        "status": status,
        "feature_name": state["feature_name"],
        "artifact_type": state["artifact_type"],
        "upstream": state.get("upstream", {}),
        "question_bank_version": state["question_bank_version"],
        "revision": state["revision"],
        "resume_step": resume_step,
        "self_review": state.get("self_review"),
        "coverage": state.get("coverage", {}),
        "sections": _artifact_sections(state, bank),
        "intake": state.get("intake", {}),
        "interview": interview,
        "feature_title": _display_name(state["feature_name"], state),
        "draft_available": draft_ready,
        "progress": {
            "confirmed": sum(
                1
                for question_id, record in state["answers"].items()
                if question_id in progress_ids and record.get("state") == "confirmed"
            ),
            "total": len(progress_ids),
            "deferred": deferred,
        },
        "current_question": ({
            "id": current["id"],
            "prompt": current["prompt"],
            "evidence": current["evidence"],
            "purpose": current.get("purpose"),
            "completion_evidence": current.get("completion_evidence"),
            "suggestion": suggestion,
            "existing_answer": state["answers"].get(current["id"], {}).get("answer"),
            "follow_up": follow_up if follow_up and follow_up.get("status") == "pending" else None,
            "edit_request": edit_request if edit_request and edit_request.get("status") == "pending" else None,
            "response_control": response_control,
            "review_findings": findings,
        } if current else None),
        "artifact_path": artifact.get("path") if draft_ready else None,
        "dashboard_url": artifact.get("dashboard_url") if draft_ready else None,
        "authoring_url": artifact.get("authoring_url") if draft_ready else None,
        "message": (
            f"{ARTIFACTS[state['artifact_type']]['label']} draft generated from "
            "confirmed interview answers."
            if status == "drafted"
            else (
                f"{ARTIFACTS[state['artifact_type']]['label']} v{published_version} published."
                if published_version is not None
                else f"{ARTIFACTS[state['artifact_type']]['label']} published."
            )
            if status == "published"
            else "The generated draft needs a structural repair before V1 is ready."
            if repair_preview
            else "A required deferred answer must be confirmed before generation."
            if status == "blocked"
            else follow_up["prompt"]
            if follow_up and follow_up.get("status") == "pending"
            else "Edit the persisted suggestion and submit your version."
            if edit_request and edit_request.get("status") == "pending"
            else "Self-review reopened this question; revise its source answer."
            if findings
            else "The suggestion was rejected; provide your own answer or defer."
            if suggestion and suggestion.get("rejected")
            else (
                "Review the complete V1, edit source answers or sections, or collect "
                "section comments for one regeneration pass."
                if draft_ready
                else "Answer the next conversational question. V1 will be generated "
                "after every applicable product decision is usable."
            )
        ),
    }


def _format_text(result: dict[str, Any]) -> str:
    if result.get("draft_available") and result.get("authoring_url"):
        return str(result["authoring_url"])
    lines = [
        f"skill: {result['skill']}",
        f"status: {result['status']}",
        f"feature: {result['feature_name']}",
        f"artifact type: {result['artifact_type']}",
        f"revision: {result['revision']}",
        f"progress: {result['progress']['confirmed']}/{result['progress']['total']} confirmed",
    ]
    if result.get("upstream", {}).get("prd"):
        upstream = result["upstream"]["prd"]
        lines.append(
            f"product source: {upstream['path']} ({upstream['sha256']})"
        )
    if result["current_question"]:
        question = result["current_question"]
        lines.extend([
            f"question: {question['id']}",
            question["prompt"],
            f"evidence to consider: {question['evidence']}",
        ])
        if question.get("existing_answer"):
            lines.append(f"existing answer: {question['existing_answer']}")
        if question.get("follow_up"):
            lines.append(f"targeted follow-up: {question['follow_up']['prompt']}")
        lines.extend(
            f"self-review finding: {finding['message']}"
            for finding in question.get("review_findings", [])
        )
        suggestion = question.get("suggestion")
        if suggestion:
            if suggestion.get("rejected"):
                lines.append("suggested response: rejected")
            elif suggestion.get("answer"):
                lines.append(f"suggested response: {suggestion['answer']}")
            else:
                lines.append("suggested response: none")
            lines.append(f"suggestion confidence: {suggestion['confidence']}")
            lines.extend(
                f"suggestion source: {source['id']} ({source['path']})"
                for source in suggestion["sources"]
            )
            lines.extend(f"suggestion gap: {gap}" for gap in suggestion["gaps"])
    if result["artifact_path"]:
        lines.append(f"artifact: {result['artifact_path']}")
    if result["dashboard_url"]:
        lines.append(f"dashboard: {result['dashboard_url']}")
    return "\n".join(lines)


def _format_list(result: dict[str, Any]) -> str:
    lines = [f"skill: {result['skill']}", f"status: {result['status']}"]
    for entry in result["sessions"]:
        progress = entry["progress"]
        lines.append(
            f"  {entry['feature_name']}  {entry['artifact_type']}  {entry['status']}"
            f"  rev {entry['revision']}"
            f"  {progress['confirmed']}/{progress['total']} confirmed"
        )
    lines.append(f"message: {result['message']}")
    return "\n".join(lines)


def _format_intake(result: dict[str, Any]) -> str:
    next_input = result["next_input"]
    lines = [result["message"], next_input["prompt"]]
    for field in next_input.get("fields", []):
        lines.append(f"- {field['prompt']} {field.get('description', '')}".rstrip())
    for option in next_input.get("options", []):
        label = option.get("label") or option.get("feature_name")
        detail = option.get("path")
        lines.append(f"- {label}" + (f" ({detail})" if detail else ""))
    fallback = next_input.get("fallback")
    if fallback:
        lines.append(f"Fallback: {fallback['prompt']}")
    return "\n".join(lines)


def _apply_response(
    state: dict[str, Any],
    bank: dict[str, Any],
    answer: str | None,
    defer: bool,
    accept_suggestion: bool,
    edit_suggestion: bool,
    reject_suggestion: bool,
    expected_revision: int | None,
    actor: tuple[str, str],
    expected_question_id: str | None = None,
) -> None:
    if expected_revision is not None and expected_revision != state["revision"]:
        raise RevisionConflict(
            f"Expected interview revision {expected_revision}, found "
            f"{state['revision']}. Reload before answering."
        )
    pending = _pending_questions(state, bank)
    if not pending:
        persona = ARTIFACTS[state["artifact_type"]]["persona"]
        raise DraftError(f"The {persona} interview is already complete.")
    question = pending[0]
    if expected_question_id is not None and question["id"] != expected_question_id:
        raise RevisionConflict(
            f"Expected question {expected_question_id}, found {question['id']}. "
            "Reload before answering."
        )
    actor_name, actor_email = actor
    suggestion = state["suggestions"].get(question["id"])
    if suggestion is None:
        raise DraftError("The current question has no persisted suggestion.")
    follow_up = state["follow_ups"].get(question["id"])
    if follow_up and follow_up.get("status") == "pending" and (
        accept_suggestion or edit_suggestion or reject_suggestion
    ):
        raise DraftError("Answer or defer the pending targeted follow-up first.")

    if edit_suggestion:
        existing_edit = state["edit_requests"].get(question["id"])
        if existing_edit and existing_edit.get("status") == "pending":
            return
        state["edit_requests"][question["id"]] = {
            "status": "pending",
            "suggestion_id": suggestion["id"],
            "initial_value": suggestion.get("answer") or "",
            "created_at": _now(),
            "answer": None,
            "resolved_at": None,
        }
        state["decision_history"].append({
            "question_id": question["id"],
            "suggestion_id": suggestion["id"],
            "action": "edit_requested",
            "answer": None,
            "actor": actor_name,
            "actor_email": actor_email,
            "at": _now(),
            "revision": state["revision"] + 1,
        })
        state["revision"] += 1
        state["updated_at"] = _now()
        return

    if reject_suggestion:
        if not suggestion.get("answer"):
            raise DraftError(
                "There is no suggested answer to reject; answer or defer the question."
            )
        edit_request = state["edit_requests"].get(question["id"])
        if edit_request and edit_request.get("status") == "pending":
            edit_request["status"] = "rejected"
            edit_request["resolved_at"] = _now()
        suggestion["rejected"] = True
        action = "rejected"
        state["decision_history"].append({
            "question_id": question["id"],
            "suggestion_id": suggestion["id"],
            "action": action,
            "answer": None,
            "actor": actor_name,
            "actor_email": actor_email,
            "at": _now(),
            "revision": state["revision"] + 1,
        })
        state["revision"] += 1
        state["updated_at"] = _now()
        return

    if accept_suggestion:
        if not suggestion.get("accept_ready"):
            raise DraftError(
                "This suggestion is not grounded strongly enough to accept unchanged. "
                "Edit it with --answer, reject it, or defer the question."
            )
        normalized = suggestion["answer"].strip()
        action = "accepted"
    elif defer:
        edit_request = state["edit_requests"].get(question["id"])
        if edit_request and edit_request.get("status") == "pending":
            edit_request["status"] = "deferred"
            edit_request["resolved_at"] = _now()
        if follow_up and follow_up.get("status") == "pending":
            follow_up["status"] = "deferred"
            follow_up["resolved_at"] = _now()
        record = {
            "state": "deferred",
            "answer": None,
            "coverage_id": question.get("coverage_id") or question["id"],
            "question_prompt": question["prompt"],
            "decision": "deferred",
            "suggestion_id": suggestion["id"],
            "actor": actor_name,
            "actor_email": actor_email,
            "evidence_prompt": question["evidence"],
            "quality_gaps": [],
            "confirmed_at": None,
        }
        action = "deferred"
    else:
        normalized = (answer or "").strip()
        if len(normalized) < 3:
            raise DraftError("An interview answer must contain at least 3 characters.")
        action = "edited"

    if action in {"accepted", "edited"}:
        edit_request = state["edit_requests"].get(question["id"])
        if edit_request and edit_request.get("status") == "pending":
            edit_request["status"] = (
                "answered" if action == "edited" else "accepted"
            )
            edit_request["answer"] = normalized if action == "edited" else None
            edit_request["resolved_at"] = _now()
        if follow_up and follow_up.get("status") == "pending":
            normalized = f"{follow_up['initial_answer']}\n\n{normalized}"
            follow_up["status"] = "answered"
            follow_up["answer"] = answer
            follow_up["resolved_at"] = _now()
        quality_gaps = _answer_quality_gaps(question, normalized)
        if quality_gaps and not follow_up:
            prompt = (question.get("quality") or {}).get(
                "follow_up_prompt",
                f"Please add enough detail to show: {question.get('completion_evidence')}",
            )
            state["follow_ups"][question["id"]] = {
                "status": "pending",
                "prompt": prompt,
                "initial_answer": normalized,
                "quality_gaps": quality_gaps,
                "created_at": _now(),
                "answer": None,
                "resolved_at": None,
            }
            state["decision_history"].append({
                "question_id": question["id"],
                "suggestion_id": suggestion["id"],
                "action": "follow_up_requested",
                "answer": normalized,
                "actor": actor_name,
                "actor_email": actor_email,
                "at": _now(),
                "revision": state["revision"] + 1,
            })
            state["revision"] += 1
            state["updated_at"] = _now()
            state["status"] = "interviewing"
            return
        record = {
            "state": "confirmed",
            "answer": normalized,
            "coverage_id": question.get("coverage_id") or question["id"],
            "question_prompt": question["prompt"],
            "decision": action,
            "suggestion_id": suggestion["id"],
            "actor": actor_name,
            "actor_email": actor_email,
            "evidence_prompt": question["evidence"],
            "quality_gaps": quality_gaps,
            "confirmed_at": _now(),
        }
    previous_answer = (state.get("answers", {}).get(question["id"]) or {}).get("answer")
    state["answers"][question["id"]] = record
    if previous_answer and previous_answer != record.get("answer"):
        _mark_manual_sections_stale(
            state,
            bank,
            str(record.get("coverage_id") or question["id"]),
            state["revision"] + 1,
        )
    state["decision_history"].append({
        "question_id": question["id"],
        "suggestion_id": suggestion["id"],
        "action": action,
        "answer": record["answer"],
        "actor": actor_name,
        "actor_email": actor_email,
        "at": _now(),
        "revision": state["revision"] + 1,
    })
    state["revision"] += 1
    state["updated_at"] = _now()
    state["status"] = "interviewing"


def _snapshot_current_artifact(project_root: Path, state: dict[str, Any]) -> bool:
    """Keep the visible draft available before an edit invalidates the artifact."""
    artifact = state.get("artifact") or {}
    artifact_path = artifact.get("path")
    if not artifact_path:
        return False
    versions = state.setdefault("artifact_versions", [])
    try:
        content = (project_root / artifact_path).read_text(encoding="utf-8")
    except OSError:
        return False
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    if artifact.get("sha256") == content_hash:
        return False
    matching = next(
        (item for item in versions if item.get("revision") == state.get("revision")),
        None,
    )
    if matching and matching.get("content") == content:
        return False
    # Preserve a direct filesystem edit as its own revision. The caller's
    # subsequent generated or published artifact receives a later revision,
    # so version de-duplication cannot erase this recovery copy.
    snapshot_revision = state["revision"] + 1
    state["revision"] = snapshot_revision
    versions.append({
        "revision": snapshot_revision,
        "content": content,
        "created_at": artifact.get("generated_at") or state.get("updated_at") or _now(),
        "source": "external_edit_recovery",
        "status": "draft",
    })
    versions[:] = versions[-20:]
    return True


def _apply_coverage_update(
    project_root: Path,
    state: dict[str, Any],
    bank: dict[str, Any],
    coverage: str,
    answer: str | None,
    expected_revision: int | None,
    actor: tuple[str, str],
) -> None:
    """Persist a draft-review edit against stable coverage, then regenerate."""
    if state["artifact_type"] != "prd":
        raise DraftError("Coverage review updates are currently supported only for PRDs.")
    if expected_revision is not None and expected_revision != state["revision"]:
        raise RevisionConflict(
            f"Expected interview revision {expected_revision}, found "
            f"{state['revision']}. Reload before updating the draft."
        )
    normalized = re.sub(r"[^a-z0-9]+", "_", coverage.lower()).strip("_")
    aliases = {
        "problem": "problem_evidence",
        "problem_and_evidence": "problem_evidence",
        "users": "user_boundary",
        "user_stories": "user_boundary",
        "requirements": "product_behavior",
        "requirements_and_acceptance": "acceptance",
        "guardrails": "delivery_controls",
        "delivery_risks_and_open_questions": "delivery_controls",
        "scope": "scope_dependencies",
    }
    normalized = aliases.get(normalized, normalized)
    question = next(
        (
            item
            for item in bank["questions"]
            if item["id"].lower() == coverage.lower()
            or item.get("coverage") == normalized
        ),
        None,
    )
    if not question:
        valid = ", ".join(
            item.get("coverage", item["id"]) for item in bank["questions"]
        )
        raise DraftError(f"Unknown PRD coverage '{coverage}'. Valid values: {valid}.")
    revised = (answer or "").strip()
    if len(revised) < 3:
        raise DraftError("A coverage review update must contain at least 3 characters.")
    _snapshot_current_artifact(project_root, state)
    actor_name, actor_email = actor
    question_id = question["id"]
    previous = state.get("answers", {}).get(question_id, {})
    state["answers"][question_id] = {
        "state": "confirmed",
        "answer": revised,
        # Source history should continue to show the contextual question the
        # user actually answered, even after they edit that answer in review.
        "question_prompt": previous.get("question_prompt") or question.get("prompt"),
        "decision": "review_edited",
        "suggestion_id": None,
        "actor": actor_name,
        "actor_email": actor_email,
        "evidence_prompt": "Human review of the generated PRD",
        "quality_gaps": _answer_quality_gaps(question, revised),
        "confirmed_at": _now(),
    }
    _mark_manual_sections_stale(
        state,
        bank,
        question_id,
        state["revision"] + 1,
    )
    state["decision_history"].append({
        "question_id": question_id,
        "suggestion_id": None,
        "action": "review_edited",
        "answer": revised,
        "actor": actor_name,
        "actor_email": actor_email,
        "at": _now(),
        "revision": state["revision"] + 1,
    })
    state["revision"] += 1
    state["updated_at"] = _now()
    state["status"] = "interviewing"
    state["artifact"] = None
    state["self_review"] = {
        "pass_count": 0,
        "max_passes": 2,
        "status": "pending",
        "findings": [],
        "artifact_sha256": None,
    }


def _apply_section_update(
    project_root: Path,
    state: dict[str, Any],
    section_title: str,
    body: str | None,
    expected_revision: int | None,
    actor: tuple[str, str],
) -> None:
    """Persist a human-authored artifact section that survives regeneration."""
    if expected_revision is not None and expected_revision != state["revision"]:
        raise RevisionConflict(
            f"Expected interview revision {expected_revision}, found "
            f"{state['revision']}. Reload before updating the draft."
        )
    artifact_type = state["artifact_type"]
    valid_titles = (
        _applicable_prd_sections(state)
        if artifact_type == "prd"
        else ARTIFACTS[artifact_type]["sections"]
    )
    if section_title not in valid_titles:
        raise DraftError(
            f"Unknown {ARTIFACTS[artifact_type]['label']} section '{section_title}'. Valid sections: "
            + ", ".join(valid_titles)
            + "."
        )
    revised = (body or "").strip()
    if len(revised) < 3:
        raise DraftError("A direct section edit must contain at least 3 characters.")

    _snapshot_current_artifact(project_root, state)
    actor_name, actor_email = actor
    next_revision = state["revision"] + 1
    state.setdefault("manual_sections", {})[section_title] = {
        "body": revised,
        "actor": actor_name,
        "actor_email": actor_email,
        "updated_at": _now(),
        "revision": next_revision,
        "source": "section_editor",
        "status": "current",
        "based_on_artifact_sha256": (state.get("artifact") or {}).get("sha256"),
    }
    state["decision_history"].append({
        "question_id": None,
        "section_title": section_title,
        "suggestion_id": None,
        "action": "draft_section_edited",
        "answer": revised,
        "actor": actor_name,
        "actor_email": actor_email,
        "at": _now(),
        "revision": next_revision,
    })
    state["revision"] = next_revision
    state["updated_at"] = _now()
    state["status"] = "interviewing"
    state["artifact"] = None
    state["self_review"] = {
        "pass_count": 0,
        "max_passes": 2,
        "status": "pending",
        "findings": [],
        "artifact_sha256": None,
    }


def _apply_document_update(
    project_root: Path,
    state: dict[str, Any],
    content: str | None,
    expected_revision: int | None,
    actor: tuple[str, str],
) -> None:
    """Persist a complete editor save as section-level manual overrides."""
    if expected_revision is not None and expected_revision != state["revision"]:
        raise RevisionConflict(
            f"Expected interview revision {expected_revision}, found "
            f"{state['revision']}. Reload before saving the document."
        )
    revised = (content or "").strip()
    if not revised.startswith("## "):
        raise DraftError("The editor must preserve the artifact section headings.")
    matches = list(re.finditer(r"^##\s+(.+?)\s*$", revised, re.MULTILINE))
    titles = [match.group(1).strip() for match in matches]
    artifact_type = state["artifact_type"]
    expected_titles = list(
        _applicable_prd_sections(state)
        if artifact_type == "prd"
        else ARTIFACTS[artifact_type]["sections"]
    )
    if titles != expected_titles:
        raise DraftError(
            f"The editor must preserve every {ARTIFACTS[artifact_type]['label']} section in template order: "
            + ", ".join(expected_titles)
            + "."
        )

    _snapshot_current_artifact(project_root, state)
    actor_name, actor_email = actor
    next_revision = state["revision"] + 1
    updated_at = _now()
    manual_sections = state.setdefault("manual_sections", {})
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(revised)
        body = revised[match.end():end].strip()
        if len(body) < 3:
            raise DraftError(f"The section '{titles[index]}' cannot be empty.")
        manual_sections[titles[index]] = {
            "body": body,
            "actor": actor_name,
            "actor_email": actor_email,
            "updated_at": updated_at,
            "revision": next_revision,
            "source": "document_editor",
            "status": "current",
            "based_on_artifact_sha256": (state.get("artifact") or {}).get("sha256"),
        }
    state["decision_history"].append({
        "question_id": None,
        "section_title": None,
        "suggestion_id": None,
        "action": "draft_document_edited",
        "answer": f"Saved {len(matches)} {ARTIFACTS[artifact_type]['label']} sections from the embedded editor.",
        "actor": actor_name,
        "actor_email": actor_email,
        "at": updated_at,
        "revision": next_revision,
    })
    state["revision"] = next_revision
    state["updated_at"] = updated_at
    state["status"] = "interviewing"
    state["artifact"] = None
    state["self_review"] = {
        "pass_count": 0,
        "max_passes": 2,
        "status": "pending",
        "findings": [],
        "artifact_sha256": None,
    }


def _apply_review_comments(
    project_root: Path,
    state: dict[str, Any],
    comments_json: str,
    review_plan_json: str | None,
    expected_revision: int | None,
    actor: tuple[str, str],
) -> None:
    """Apply host-model section revisions as one atomic regeneration revision."""
    if not state.get("artifact"):
        raise DraftError("Review comments require a generated artifact.")
    if expected_revision is not None and expected_revision != state["revision"]:
        raise RevisionConflict(
            f"Expected interview revision {expected_revision}, found {state['revision']}. "
            "Reload before regenerating the draft."
        )
    try:
        comments = json.loads(comments_json)
    except json.JSONDecodeError as exc:
        raise DraftError("Review comments must be valid JSON.") from exc
    if not isinstance(comments, list) or not comments:
        raise DraftError("Add at least one review comment before regenerating.")
    if not review_plan_json:
        raise DraftError(
            "Review comments require a host-model revision plan. "
            "The existing artifact was not changed."
        )
    try:
        review_plan = json.loads(review_plan_json)
    except json.JSONDecodeError as exc:
        raise DraftError("The review revision plan must be valid JSON.") from exc
    if not isinstance(review_plan, dict):
        raise DraftError("The review revision plan must be a JSON object.")

    valid_titles = set(
        _applicable_prd_sections(state)
        if state["artifact_type"] == "prd"
        else ARTIFACTS[state["artifact_type"]]["sections"]
    )
    grouped: dict[str, list[str]] = {}
    for item in comments:
        if not isinstance(item, dict):
            raise DraftError("Each review comment must name a section and comment.")
        title = str(item.get("section_title") or "").strip()
        comment = str(item.get("comment") or "").strip()
        if title not in valid_titles:
            raise DraftError(f"Unknown or inactive artifact section '{title}'.")
        if len(comment) < 3:
            raise DraftError(f"The comment for '{title}' is too short.")
        grouped.setdefault(title, []).append(comment)

    artifact_path = project_root / state["artifact"]["path"]
    try:
        artifact_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DraftError("The generated artifact could not be read for review.") from exc
    _snapshot_current_artifact(project_root, state)

    table_headers = {
        "User Stories": ("ID", "Story", "Priority"),
        "Requirements & Acceptance": ("ID", "Story", "Product behavior", "Done when"),
        "Scope": ("Included", "Not included"),
        "Guardrails / Must Not Regress": (
            "ID", "What must remain true", "How it will be verified",
        ),
        "Success": ("ID", "Outcome or signal", "Target", "Window", "Owner"),
    }
    revisions: dict[str, str] = {}
    for item in review_plan.get("sections") or []:
        if not isinstance(item, dict):
            raise DraftError("Each review revision must name a section and revised body.")
        title = str(item.get("section_title") or "").strip()
        body = str(item.get("revised_body") or "").strip()
        if title in revisions:
            raise DraftError(f"The review plan repeats section '{title}'.")
        if len(body) < 3:
            raise DraftError(f"The review plan for '{title}' has no meaningful content.")
        if re.search(r"^##\s+", body, re.MULTILINE):
            raise DraftError(f"The review plan for '{title}' includes a section heading.")
        expected_headers = table_headers.get(title) if state["artifact_type"] == "prd" else None
        if expected_headers:
            lines = [line.strip() for line in body.splitlines() if line.strip()]
            expected_header = "| " + " | ".join(expected_headers) + " |"
            if (
                len(lines) < 3
                or lines[0] != expected_header
                or any(not line.startswith("|") or not line.endswith("|") for line in lines)
                or any(line.count("|") != len(expected_headers) + 1 for line in lines)
            ):
                raise DraftError(
                    f"The review plan for '{title}' must contain only its "
                    "template-shaped Markdown table."
                )
        revisions[title] = body
    if set(revisions) != set(grouped):
        raise DraftError(
            "The review plan must revise every commented section exactly once."
        )

    actor_name, actor_email = actor
    next_revision = state["revision"] + 1
    for title, section_comments in grouped.items():
        state.setdefault("manual_sections", {})[title] = {
            "body": revisions[title],
            "actor": actor_name,
            "actor_email": actor_email,
            "updated_at": _now(),
            "revision": next_revision,
            "source": "review_comments",
            "comments": section_comments,
            "model": review_plan.get("model"),
            "status": "current",
            "based_on_artifact_sha256": (state.get("artifact") or {}).get("sha256"),
        }
    state.setdefault("review_comments", []).append({
        "revision": next_revision,
        "comments": comments,
        "model": review_plan.get("model"),
        "analysis_summary": review_plan.get("analysis_summary"),
        "actor": actor_name,
        "actor_email": actor_email,
        "submitted_at": _now(),
    })
    applied_ids = {
        str(item.get("id"))
        for item in comments
        if isinstance(item, dict) and item.get("id")
    }
    for thread in state.setdefault("review_comment_threads", []):
        if thread.get("id") in applied_ids:
            thread["status"] = "applied"
            thread["applied_revision"] = next_revision
            thread["resolved_at"] = _now()
    state["decision_history"].append({
        "question_id": None,
        "suggestion_id": None,
        "action": "draft_comments_regenerated",
        "answer": json.dumps(comments, sort_keys=True),
        "actor": actor_name,
        "actor_email": actor_email,
        "at": _now(),
        "revision": next_revision,
    })
    state["revision"] = next_revision
    state["updated_at"] = _now()
    state["status"] = "interviewing"
    state["artifact"] = None
    state["self_review"] = {
        "pass_count": 0,
        "max_passes": 2,
        "status": "pending",
        "findings": [],
        "artifact_sha256": None,
    }


def _apply_review_comment(
    state: dict[str, Any],
    comment_json: str,
    expected_revision: int | None,
    actor: tuple[str, str],
) -> None:
    """Persist one review comment before any model regeneration occurs."""
    if not state.get("artifact"):
        raise DraftError("Review comments require a generated artifact.")
    if expected_revision is not None and expected_revision != state["revision"]:
        raise RevisionConflict(
            f"Expected interview revision {expected_revision}, found {state['revision']}. "
            "Reload before adding the comment."
        )
    try:
        submitted = json.loads(comment_json)
    except json.JSONDecodeError as exc:
        raise DraftError("The review comment must be valid JSON.") from exc
    if not isinstance(submitted, dict):
        raise DraftError("The review comment must be a JSON object.")
    section_title = str(submitted.get("section_title") or "__document__").strip()
    comment = str(submitted.get("comment") or "").strip()
    if len(comment) < 3:
        raise DraftError("Add meaningful review guidance before saving the comment.")
    valid_titles = set(
        _applicable_prd_sections(state)
        if state["artifact_type"] == "prd"
        else ARTIFACTS[state["artifact_type"]]["sections"]
    )
    if section_title != "__document__" and section_title not in valid_titles:
        raise DraftError(f"Unknown artifact section for review: {section_title}")

    selected_text = str(submitted.get("selected_text") or "").strip()
    selection_start = submitted.get("selection_start")
    selection_end = submitted.get("selection_end")
    anchor_revision = submitted.get("anchor_revision", state["revision"])
    if selected_text:
        if not isinstance(selection_start, int) or not isinstance(selection_end, int):
            raise DraftError("A selected-text comment requires numeric selection offsets.")
        if selection_start < 0 or selection_end <= selection_start:
            raise DraftError("The selected-text comment has invalid selection offsets.")
    actor_name, actor_email = actor
    next_revision = state["revision"] + 1
    state.setdefault("review_comment_threads", []).append({
        "id": str(uuid.uuid4()),
        "section_title": section_title,
        "comment": comment,
        "selected_text": selected_text or None,
        "selection_start": selection_start if selected_text else None,
        "selection_end": selection_end if selected_text else None,
        "anchor_revision": anchor_revision,
        "anchor_artifact_sha256": (state.get("artifact") or {}).get("sha256"),
        "author": actor_name,
        "author_email": actor_email,
        "status": "open",
        "created_at": _now(),
        "saved_revision": next_revision,
    })
    state["decision_history"].append({
        "question_id": None,
        "section_title": section_title,
        "suggestion_id": None,
        "action": "review_comment_added",
        "answer": comment,
        "actor": actor_name,
        "actor_email": actor_email,
        "at": _now(),
        "revision": next_revision,
    })
    state["revision"] = next_revision
    state["updated_at"] = _now()


def _apply_batch_answers(
    project_root: Path,
    feature: str,
    state: dict[str, Any],
    bank: dict[str, Any],
    answers_json: str,
    expected_revision: int | None,
    actor: tuple[str, str],
) -> None:
    """Apply every remaining planned answer under one checkpoint lock."""
    if expected_revision is not None and expected_revision != state["revision"]:
        raise RevisionConflict(
            f"Expected interview revision {expected_revision}, found "
            f"{state['revision']}. Reload before answering."
        )
    try:
        submitted = json.loads(answers_json)
    except json.JSONDecodeError as exc:
        raise DraftError("The interview answer batch is not valid JSON.") from exc
    if not isinstance(submitted, list) or not submitted:
        raise DraftError("Submit at least one planned interview answer.")

    pending = _pending_questions(state, bank)
    pending_ids = [question["id"] for question in pending]
    submitted_ids: list[str] = []
    normalized: list[tuple[str, str]] = []
    for item in submitted:
        if not isinstance(item, dict):
            raise DraftError("Each batched answer must identify its question and answer.")
        question_id = str(item.get("question_id") or "").strip()
        answer = str(item.get("answer") or "").strip()
        if not question_id or len(answer) < 3:
            raise DraftError("Each batched answer must contain at least 3 characters.")
        submitted_ids.append(question_id)
        normalized.append((question_id, answer))
    if submitted_ids != pending_ids:
        raise DraftError(
            "The answer batch must contain every remaining planned question in order."
        )

    for question_id, answer in normalized:
        current = _pending_questions(state, bank)
        if not current or current[0]["id"] != question_id:
            raise DraftError("The planned interview changed while applying the answer batch.")
        _ensure_current_suggestion(project_root, feature, state, bank)
        _apply_response(
            state,
            bank,
            answer,
            False,
            False,
            False,
            False,
            state["revision"],
            actor,
            question_id,
        )
        follow_up = state.get("follow_ups", {}).get(question_id)
        if follow_up and follow_up.get("status") == "pending":
            raise DraftError(
                f"The answer for {question_id} needs more detail before the batch can be saved."
            )


def run_once(args: argparse.Namespace) -> dict[str, Any]:
    project_root = Path(args.project_root).resolve()
    feature = _validate_feature(args.feature_name)
    artifact_type = args.artifact_type
    feature_description = _validate_feature_description(args.feature_description)
    feature_title = _validate_feature_title(getattr(args, "feature_title", None))
    if artifact_type != "prd" and feature_description:
        raise DraftError("--feature-description is supported only when starting a PRD.")
    if artifact_type != "prd" and feature_title:
        raise DraftError("--feature-title is supported only when starting a PRD.")
    bank = _load_question_bank(artifact_type)
    feature_dir = _feature_dir(project_root, feature)
    state_path = feature_dir / f"authoring-{artifact_type}.json"

    with _feature_lock(feature_dir):
        upstream = (
            {"prd": _prd_upstream(project_root, feature)}
            if artifact_type == "design"
            else {
                "prd": _prd_upstream(project_root, feature),
                "design": _design_upstream(project_root, feature),
            }
            if artifact_type == "rfc"
            else None
        )
        persisted = _read_json(state_path)
        if persisted and feature_title:
            persisted = _migrate_state(persisted)
            existing_title = (persisted.get("intake") or {}).get("feature_title")
            if not existing_title:
                intake = persisted.setdefault("intake", {})
                intake["feature_title"] = feature_title
                intake.setdefault("captured_at", _now())
            elif existing_title != feature_title:
                raise DraftError(
                    "--feature-title cannot rename an interview that already has a title."
                )
        if persisted and feature_description:
            persisted = _migrate_state(persisted)
            existing_description = (persisted.get("intake") or {}).get(
                "feature_description"
            )
            is_empty_checkpoint = (
                persisted.get("revision") == 0
                and not persisted.get("answers")
                and not persisted.get("decision_history")
                and not persisted.get("follow_ups")
                and not persisted.get("edit_requests")
                and persisted.get("status") in {"interviewing", "clarifying"}
            )
            if existing_description == feature_description:
                pass
            elif is_empty_checkpoint and not existing_description:
                persisted["intake"] = {
                    "feature_description": feature_description,
                    "captured_at": _now(),
                }
                persisted.get("suggestions", {}).pop("P-Q1", None)
                persisted["suggestions"] = {}
                persisted["clarification_plan"] = []
                persisted["clarifications_asked"] = []
                persisted["coverage"] = {}
                actor_name, actor_email = _actor(project_root)
                persisted["decision_history"].append({
                    "question_id": "P-Q1",
                    "suggestion_id": None,
                    "action": "intake_description_added",
                    "answer": feature_description,
                    "actor": actor_name,
                    "actor_email": actor_email,
                    "at": _now(),
                    "revision": 1,
                })
                persisted["revision"] = 1
                persisted["updated_at"] = _now()
                persisted["artifact"] = None
            else:
                raise DraftError(
                    "--feature-description cannot replace existing interview evidence or progress."
                )
        state = _migrate_state(
            persisted
            or _new_state(
                feature,
                artifact_type,
                bank,
                upstream,
                feature_description,
                feature_title,
            )
        )
        _validate_state(state, feature, artifact_type, bank)
        if upstream:
            for upstream_type, current_upstream in upstream.items():
                _validate_pinned_upstream(state, upstream_type, current_upstream)
        if args.model_plan_json:
            _apply_planning_plan(
                state,
                bank,
                args.model_plan_json,
                args.expected_revision,
            )
        elif args.compact_plan_json:
            _apply_compact_planning_plan(
                state,
                bank,
                args.compact_plan_json,
                args.expected_revision,
            )
        if args.canonicalize_feature:
            feature, feature_dir, state_path = _canonicalize_provisional_feature(
                project_root,
                feature,
                artifact_type,
                state,
            )
        _ensure_current_suggestion(project_root, feature, state, bank)
        if args.publish:
            _publish_artifact(
                project_root,
                state,
                args.expected_revision,
                _actor(project_root),
            )
        elif args.add_review_comment_json:
            _apply_review_comment(
                state,
                args.add_review_comment_json,
                args.expected_revision,
                _actor(project_root),
            )
        elif args.review_comments_json:
            _apply_review_comments(
                project_root,
                state,
                args.review_comments_json,
                args.review_plan_json,
                args.expected_revision,
                _actor(project_root),
            )
            _ensure_current_suggestion(project_root, feature, state, bank)
        elif args.update_document:
            if args.answer is None:
                raise DraftError("--update-document requires --answer with the revised content.")
            _apply_document_update(
                project_root,
                state,
                args.answer,
                args.expected_revision,
                _actor(project_root),
            )
            _ensure_current_suggestion(project_root, feature, state, bank)
        elif args.update_section:
            if args.answer is None:
                raise DraftError("--update-section requires --answer with the revised content.")
            _apply_section_update(
                project_root,
                state,
                args.update_section,
                args.answer,
                args.expected_revision,
                _actor(project_root),
            )
            _ensure_current_suggestion(project_root, feature, state, bank)
        elif args.update_coverage:
            if args.answer is None:
                raise DraftError("--update-coverage requires --answer with the revised content.")
            _apply_coverage_update(
                project_root,
                state,
                bank,
                args.update_coverage,
                args.answer,
                args.expected_revision,
                _actor(project_root),
            )
            _ensure_current_suggestion(project_root, feature, state, bank)
        elif args.answers_json:
            _apply_batch_answers(
                project_root,
                feature,
                state,
                bank,
                args.answers_json,
                args.expected_revision,
                _actor(project_root),
            )
            _ensure_current_suggestion(project_root, feature, state, bank)
        elif (
            args.answer is not None
            or args.defer
            or args.accept_suggestion
            or args.edit_suggestion
            or args.reject_suggestion
        ):
            _apply_response(
                state,
                bank,
                args.answer,
                args.defer,
                args.accept_suggestion,
                args.edit_suggestion,
                args.reject_suggestion,
                args.expected_revision,
                _actor(project_root),
                args.question_id,
            )
            _ensure_current_suggestion(project_root, feature, state, bank)
        pending = _pending_questions(state, bank)
        if (
            not args.hold_generation
            and not pending
            and state.get("status") not in {"drafted", "drafted_with_open_questions", "published"}
        ):
            _generate(project_root, feature, state, bank, args.dashboard_url)
            _self_review(project_root, feature, state, bank)
        _write_json(state_path, state)
        return _result(state, bank)


def _session_summary(project_root: Path, state_path: Path) -> dict[str, Any] | None:
    """Summarize one persisted checkpoint. Reads evidence, writes nothing."""
    feature = state_path.parent.name
    if not FEATURE_RE.fullmatch(feature) or "--" in feature:
        return None
    artifact_type = state_path.name[len("authoring-"):-len(".json")]
    if artifact_type not in ARTIFACTS:
        return None
    try:
        persisted = _read_json(state_path)
        if persisted is None:
            return None
        bank = _load_question_bank(artifact_type)
        state = _migrate_state(persisted)
        _validate_state(state, feature, artifact_type, bank)
    except DraftError as exc:
        # One damaged checkpoint is reported, not hidden, and never removed.
        return {
            "feature_name": feature,
            "feature_title": None,
            "artifact_type": artifact_type,
            "status": exc.status,
            "revision": None,
            "updated_at": None,
            "progress": {"confirmed": 0, "total": 0, "deferred": []},
            "draft_available": False,
            "artifact_path": None,
            "authoring_url": None,
            "message": str(exc),
        }
    # Resolving the current suggestion can raise a coverage confidence and drop
    # a planned clarification, so the same in-memory step --peek takes runs here
    # too. Without it a listed count disagrees with the interview page.
    _ensure_current_suggestion(project_root, feature, state, bank)
    result = _result(state, bank)
    return {
        "feature_name": feature,
        "feature_title": result["feature_title"],
        "artifact_type": artifact_type,
        "status": result["status"],
        "revision": result["revision"],
        "updated_at": state.get("updated_at") or state.get("created_at"),
        "progress": result["progress"],
        "draft_available": result["draft_available"],
        "artifact_path": result["artifact_path"],
        "authoring_url": result["authoring_url"],
        "message": result["message"],
    }


def list_once(args: argparse.Namespace) -> dict[str, Any]:
    """List every persisted interview, most recently updated first."""
    project_root = Path(args.project_root).resolve()
    wanted = args.artifact_type
    features_root = _features_root(project_root)
    sessions: list[dict[str, Any]] = []
    if features_root.is_dir():
        for state_path in sorted(features_root.glob("*/authoring-*.json")):
            summary = _session_summary(project_root, state_path)
            if summary is None:
                continue
            if wanted and summary["artifact_type"] != wanted:
                continue
            sessions.append(summary)
    sessions.sort(
        key=lambda entry: (entry["updated_at"] or "", entry["feature_name"]),
        reverse=True,
    )
    label = ARTIFACTS[wanted]["label"] if wanted else "guided"
    return {
        "skill": SKILL,
        "implementation": _implementation(wanted),
        "status": "listed",
        "artifact_type": wanted,
        "sessions": sessions,
        "message": (
            f"{len(sessions)} {label} interview{'' if len(sessions) == 1 else 's'} "
            f"in {_features_root(project_root).relative_to(project_root)}."
            if sessions
            else f"No {label} interview has been started in this project yet."
        ),
    }


def peek_once(args: argparse.Namespace) -> dict[str, Any]:
    """Return the current interview view without writing anything."""
    project_root = Path(args.project_root).resolve()
    feature = _validate_feature(args.feature_name)
    artifact_type = args.artifact_type
    bank = _load_question_bank(artifact_type)
    state_path = _feature_dir(project_root, feature) / f"authoring-{artifact_type}.json"
    persisted = _read_json(state_path)
    if persisted is None:
        return {
            "skill": SKILL,
            "implementation": _implementation(artifact_type),
            "status": "not_started",
            "feature_name": feature,
            "feature_title": None,
            "artifact_type": artifact_type,
            "question_bank_version": bank["version"],
            "revision": None,
            "resume_step": None,
            "coverage": {},
            "sections": [],
            "progress": {"confirmed": 0, "total": 0, "deferred": []},
            "current_question": None,
            "draft_available": False,
            "artifact_path": None,
            "dashboard_url": None,
            "authoring_url": None,
            "self_review": None,
            "upstream": {},
            "message": (
                f"No {ARTIFACTS[artifact_type]['label']} interview exists for "
                f"'{feature}' yet."
            ),
        }
    state = _migrate_state(persisted)
    _validate_state(state, feature, artifact_type, bank)
    # In-memory only: peek never persists, so the client sees the same control
    # the next write would produce without creating or advancing state.
    _ensure_current_suggestion(project_root, feature, state, bank)
    return _result(state, bank)


def _interactive(args: argparse.Namespace) -> dict[str, Any]:
    while True:
        result = run_once(args)
        args.feature_description = None
        args.update_coverage = None
        args.answer = None
        args.defer = False
        args.accept_suggestion = False
        args.edit_suggestion = False
        args.reject_suggestion = False
        args.expected_revision = result["revision"]
        if result["status"] in {"drafted", "drafted_with_open_questions", "published"}:
            return result
        question = result["current_question"]
        print(f"\n[{question['id']}] {question['prompt']}")
        print(f"Evidence to consider: {question['evidence']}")
        suggestion = question.get("suggestion")
        if suggestion and not suggestion.get("rejected") and suggestion.get("answer"):
            print(f"Suggested response ({suggestion['confidence']}): {suggestion['answer']}")
            for source in suggestion["sources"]:
                print(f"  source: {source['id']} — {source['path']}")
            for gap in suggestion["gaps"]:
                print(f"  gap: {gap}")
        elif suggestion and suggestion.get("rejected"):
            print("Suggested response: rejected")
        elif suggestion:
            print("Suggested response: none; answer the contextual question directly.")
            for gap in suggestion["gaps"]:
                print(f"  gap: {gap}")
        control = question["response_control"]
        if control["input_type"] == "textarea":
            response = input(f"{control['prompt']} (`:quit` to stop): ").strip()
            if response == ":quit":
                return result
            args.answer = response
            continue

        options = control["options"]
        print(control["prompt"])
        for index, option in enumerate(options, start=1):
            print(f"  {index}. {option['label']}")
        response = input(f"Select 1-{len(options)} (`:quit` to stop): ").strip()
        if response == ":quit":
            return result
        if response.isdigit() and 1 <= int(response) <= len(options):
            selected = options[int(response) - 1]["value"]
        else:
            selected = response.removeprefix(":")
            if selected not in {option["value"] for option in options}:
                print("Invalid selection. Choose one of the displayed options.")
                continue
        if selected == "defer":
            args.defer = True
        elif selected == "accept":
            args.accept_suggestion = True
        elif selected == "edit":
            args.edit_suggestion = True
        elif selected == "reject":
            args.reject_suggestion = True


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="workbench draft")
    parser.add_argument("artifact_type", choices=sorted(ARTIFACTS), nargs="?")
    parser.add_argument("feature_name", nargs="?")
    parser.add_argument("--project-root", default=".")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--answer")
    action.add_argument("--answer-file", help=argparse.SUPPRESS)
    action.add_argument(
        "--answers-json",
        help="JSON array containing every remaining planned interview answer",
    )
    action.add_argument("--defer", action="store_true")
    action.add_argument("--accept-suggestion", action="store_true")
    action.add_argument("--edit-suggestion", action="store_true")
    action.add_argument("--reject-suggestion", action="store_true")
    action.add_argument(
        "--publish",
        action="store_true",
        help="Publish the current artifact as an immutable version",
    )
    action.add_argument(
        "--add-review-comment-json",
        help="Persist one section, selection, or document review comment",
    )
    action.add_argument(
        "--review-comments-json",
        help="JSON array of section comments to apply in one model-backed regeneration",
    )
    action.add_argument(
        "--model-plan-json",
        help="Validated semantic coverage and question plan generated by the configured host model",
    )
    action.add_argument(
        "--compact-plan-json",
        help="Compact semantic intake plan generated by the current harness model",
    )
    action.add_argument(
        "--compact-plan-file",
        help="File containing a compact semantic intake plan generated by the current harness model",
    )
    parser.add_argument(
        "--review-plan-json",
        help="Validated affected-section revisions generated by the configured host model",
    )
    parser.add_argument("--expected-revision", type=int)
    parser.add_argument(
        "--question-id",
        help="Stable question ID expected to receive a single submitted answer",
    )
    parser.add_argument(
        "--update-coverage",
        help="Stable coverage ID or section name to revise during draft review",
    )
    parser.add_argument(
        "--update-section",
        help="Artifact section title to edit directly while preserving the manual override",
    )
    parser.add_argument(
        "--update-document",
        action="store_true",
        help="Save all artifact section bodies from the embedded document editor",
    )
    parser.add_argument(
        "--feature-title",
        help="Human title for a new PRD; becomes the document heading",
    )
    parser.add_argument(
        "--canonicalize-feature",
        action="store_true",
        help="Replace a draft-* intake identity with the model-derived title slug",
    )
    parser.add_argument(
        "--peek",
        action="store_true",
        help="Return the persisted interview view without writing or generating",
    )
    parser.add_argument(
        "--list",
        dest="list_sessions",
        action="store_true",
        help="List persisted interviews for this project without writing",
    )
    parser.add_argument(
        "--feature-description",
        help="Direct user context used as initial problem evidence",
    )
    parser.add_argument(
        "--dashboard-url",
        default=os.environ.get("WORKBENCH_DASHBOARD_URL", "http://localhost:3000"),
    )
    parser.add_argument(
        "--hold-generation",
        action="store_true",
        help="Persist this mutation but wait for the host to re-plan before generating",
    )
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.answer_file:
            args.answer = Path(args.answer_file).read_text(encoding="utf-8")
        if args.compact_plan_file:
            args.compact_plan_json = Path(args.compact_plan_file).read_text(encoding="utf-8")
        if args.list_sessions:
            result = list_once(args)
            print(json.dumps(result, indent=2) if args.json else _format_list(result))
            return 0
        if (
            args.artifact_type == "prd"
            and args.feature_name is None
            and args.feature_description
            and args.compact_plan_json
        ):
            args.feature_name = _feature_from_compact_plan(args.compact_plan_json)
        if args.artifact_type is None or args.feature_name is None:
            result = _intake_result(Path(args.project_root).resolve(), args.artifact_type)
            print(json.dumps(result, indent=2) if args.json else _format_intake(result))
            return 0
        if args.peek:
            result = peek_once(args)
            print(json.dumps(result, indent=2) if args.json else _format_text(result))
            return 0
        should_interview = (
            sys.stdin.isatty()
            and not args.json
            and args.answer is None
            and args.answers_json is None
            and args.update_coverage is None
            and args.update_section is None
            and not args.update_document
            and args.add_review_comment_json is None
            and args.review_comments_json is None
            and args.model_plan_json is None
            and args.compact_plan_json is None
            and not args.publish
            and not args.defer
            and not args.accept_suggestion
            and not args.edit_suggestion
            and not args.reject_suggestion
        )
        result = _interactive(args) if should_interview else run_once(args)
        print(json.dumps(result, indent=2) if args.json else _format_text(result))
        return 0
    except DraftError as exc:
        payload = {
            "skill": SKILL,
            "implementation": _implementation(args.artifact_type),
            "status": exc.status,
            "feature_name": args.feature_name,
            "artifact_type": args.artifact_type,
            "message": str(exc),
        }
        print(json.dumps(payload, indent=2) if args.json else f"error: {exc}")
        return 2 if isinstance(exc, RevisionConflict) else 1


if __name__ == "__main__":
    raise SystemExit(main())
