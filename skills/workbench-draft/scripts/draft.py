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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


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


def _question_bank_path(artifact_type: str) -> Path:
    filename = ARTIFACTS[artifact_type]["question_bank"]
    return Path(__file__).resolve().parent.parent / "references" / filename


def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _implementation(artifact_type: str | None) -> dict[str, str | None]:
    """Identify the shared helper and question bank used by every entry point."""
    return {
        "helper_hash": _sha256_file(Path(__file__).resolve()),
        "question_bank_hash": (
            _sha256_file(_question_bank_path(artifact_type)) if artifact_type else None
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
    r"own|owner(?:ship)?|security|sensitive|personal data|migration|payment|billing|"
    r"compliance|legal|audit|delete|irreversible|external|third[ -]?party|"
    r"rollout|agent|llm|artificial intelligence|ai)\b",
    re.IGNORECASE,
)
IDENTITY_SIGNAL_RE = re.compile(
    r"\b(auth(?:entication|orization)?|login|log[ -]?in|sign[ -]?in|sign[ -]?up|"
    r"account|session|privacy|private|user ownership)\b",
    re.IGNORECASE,
)


def _planning_text(state: dict[str, Any]) -> str:
    parts = [
        str((state.get("intake") or {}).get("feature_description") or ""),
        *(str(record.get("answer") or "") for record in state.get("answers", {}).values()),
    ]
    return " ".join(part for part in parts if part)


COVERAGE_POLICY = {
    "P-Q1": {"impact": "critical", "leverage": 1.0},
    "P-Q2": {"impact": "high", "leverage": 1.0},
    "P-Q3": {"impact": "medium", "leverage": 0.7},
    "P-Q4": {"impact": "high", "leverage": 0.85},
    "P-Q5": {"impact": "high", "leverage": 0.8},
    "P-Q6": {"impact": "medium", "leverage": 0.6},
    "P-Q7": {"impact": "conditional", "leverage": 1.05},
    "P-Q8": {"impact": "conditional", "leverage": 1.05},
}
IMPACT_WEIGHT = {"low": 0.25, "medium": 0.5, "high": 0.8, "critical": 1.0}
CLARIFICATION_BUDGET = 3


def _coverage_confidence(question_id: str, state: dict[str, Any]) -> tuple[float, str, list[str]]:
    record = state.get("answers", {}).get(question_id, {})
    if record.get("state") == "confirmed":
        return 1.0, "confirmed", [f"interview:{question_id}"]

    description = str((state.get("intake") or {}).get("feature_description") or "")
    text = _planning_text(state)
    basis = ["intake:feature-description"] if description else []
    identity = bool(IDENTITY_SIGNAL_RE.search(text))
    scope_signal = bool(SCOPE_SIGNAL_RE.search(text))
    risk_signal = bool(RISK_SIGNAL_RE.search(text))

    if question_id == "P-Q1":
        return (0.95, "evidence_backed", basis) if description else (0.0, "missing", [])
    if question_id == "P-Q2":
        if identity:
            if re.search(
                r"\b(username|password|google|oauth|sso|single sign-on|magic link|"
                r"passkey|identity provider|sign-in provider|authentication method)\b",
                text,
                re.IGNORECASE,
            ):
                return 0.8, "inferred", basis
            return 0.25, "unresolved", basis
        if re.search(r"\b(users?|customers?|members?|admins?|leads?|contributors?|operators?)\b", text, re.IGNORECASE):
            return 0.7, "inferred", basis
        return 0.4, "unresolved", basis
    if question_id == "P-Q3":
        if re.search(r"\b(so that|enable|outcome|reduce|increase|improve|prevent)\b", text, re.IGNORECASE):
            return 0.7, "inferred", basis
        return 0.5, "inferred", basis
    if question_id == "P-Q4":
        if len(description.split()) >= 12 and re.search(r"\b(add|build|let|allow|enable|show|create|update|rename)\b", description, re.IGNORECASE):
            return 0.65, "inferred", basis
        return 0.45, "unresolved", basis
    if question_id == "P-Q5":
        if re.search(r"\b(given|when|then|done when|must|must not|reject)\b", text, re.IGNORECASE):
            return 0.75, "inferred", basis
        return 0.3, "unresolved", basis
    if question_id == "P-Q6":
        if re.search(r"\b(metric|measure|target|percent|within \d|success)\b|\d+%", text, re.IGNORECASE):
            return 0.8, "inferred", basis
        return 0.4, "inferred", basis
    if question_id == "P-Q7":
        if identity:
            if re.search(
                r"\b(existing|current|legacy) (users?|accounts?|data)|migrat|"
                r"rollout|roll out|invite|claim (?:an? )?account|set (?:a )?password|"
                r"create (?:their )?credentials?|assign(?:ed|ment)? (?:of )?(?:existing )?data",
                text,
                re.IGNORECASE,
            ):
                return 0.8, "inferred", basis
            return 0.3, "unresolved", basis
        if re.search(r"\b(in scope|out of scope|exclude|not include|not included|deliberately)\b", text, re.IGNORECASE):
            return 0.8, "inferred", basis
        return (0.3, "unresolved", basis) if scope_signal else (0.8, "not_material", basis)
    if question_id == "P-Q8":
        if not risk_signal:
            return 0.85, "not_material", basis
        if re.search(r"\b(owner|owned by|rollback|threshold|must not|audit|escalat)\b", text, re.IGNORECASE):
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
            identity_rollout = question_id == "P-Q7" and IDENTITY_SIGNAL_RE.search(
                planning_text
            )
            signal = SCOPE_SIGNAL_RE if question_id == "P-Q7" else RISK_SIGNAL_RE
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
    planning_text = _planning_text(state)
    identity_feature = bool(IDENTITY_SIGNAL_RE.search(planning_text))
    prompts = {
        "P-Q2": (
            "Which authentication method should the first release support: username "
            "and password, Google sign-in, another provider, or a specific "
            "combination?"
            if identity_feature
            else f"For {feature}, who needs this outcome? If every user behaves the "
            "same, say so; describe different access or constraints only when they "
            "genuinely exist."
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
            "and which failure or recovery path materially changes the experience?"
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
            else f"For {feature}, what is explicitly included or excluded, and is any "
            "dependency or sequencing decision material to delivery?"
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
    if state.get("artifact_type") != "prd":
        return [_contextualize_question(question, state) for question in bank["questions"]]

    assessment = _coverage_assessment(state, bank)
    state["coverage"] = assessment
    asked = list(dict.fromkeys(state.get("clarifications_asked", [])))
    current_plan = list(dict.fromkeys(state.get("clarification_plan", [])))

    # Keep surfaced questions stable. Drop unsurfaced questions when another
    # answer raises their confidence enough, then refill the remaining budget.
    retained = [
        question_id
        for question_id in current_plan
        if question_id in asked
        or assessment.get(question_id, {}).get("confidence", 0) < 0.65
    ]
    candidates = [
        question_id
        for question_id, item in assessment.items()
        if question_id not in retained
        and question_id not in state.get("answers", {})
        and item["impact"] in {"high", "critical"}
        and item["confidence"] < 0.65
    ]
    candidates.sort(key=lambda question_id: assessment[question_id]["question_value"], reverse=True)
    if asked:
        plan = retained
    else:
        plan = candidates[:CLARIFICATION_BUDGET]
    state["clarification_plan"] = plan
    by_id = {question["id"]: question for question in bank["questions"]}
    return [
        _contextualize_question(by_id[question_id], state)
        for question_id in plan
        if question_id in by_id
    ]


def _available_guided_prds(project_root: Path) -> list[dict[str, Any]]:
    """List only generated guided PRDs that are valid Design inputs."""
    features_root = project_root / ".speed" / "features"
    if not features_root.is_dir():
        return []
    available: list[dict[str, Any]] = []
    for state_path in sorted(features_root.glob("*/authoring-prd.json")):
        feature = state_path.parent.name
        if not FEATURE_RE.fullmatch(feature) or "--" in feature:
            continue
        state, error = _read_evidence_json(state_path)
        if error or not state or state.get("status") != "drafted":
            continue
        artifact = state.get("artifact") or {}
        expected_path = f"specs/{feature}/prd.md"
        prd_path = project_root / expected_path
        if artifact.get("path") != expected_path or not prd_path.is_file():
            continue
        actual_hash = hashlib.sha256(prd_path.read_bytes()).hexdigest()
        if actual_hash != artifact.get("sha256"):
            continue
        available.append({
            "feature_name": feature,
            "path": expected_path,
            "sha256": actual_hash,
            "interview_revision": state.get("revision"),
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
            ],
        }
        message = "Select the artifact before Workbench asks for its input."
    elif artifact_type == "prd":
        next_input = {
            "id": "new_prd_basics",
            "input_type": "form",
            "prompt": "Tell Workbench what this new PRD should define.",
            "fields": [
                {
                    "id": "feature_slug",
                    "input_type": "text",
                    "prompt": "What is the feature slug?",
                    "description": (
                        "Use a short lowercase name with hyphens, such as task-due-dates."
                    ),
                    "required": True,
                },
                {
                    "id": "feature_description",
                    "input_type": "textarea",
                    "prompt": "Briefly describe the feature and the problem it should solve.",
                    "description": (
                        "Include who experiences the problem, what happens today, and "
                        "the outcome the feature should enable."
                    ),
                    "required": True,
                },
            ],
            "allow_existing": False,
        }
        message = (
            "Enter the new feature slug and short description together. The description "
            "becomes direct evidence and the initial suggested response for P-Q1."
        )
    else:
        guided_prds = _available_guided_prds(project_root)
        next_input = {
            "id": "source_prd",
            "input_type": "prd_reference",
            "prompt": "Which PRD should ground this Design draft?",
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
            "Provide or select the upstream PRD first. Workbench derives the feature "
            "from a canonical PRD when possible; feature-name entry is the fallback."
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
    if len(normalized) > 2000:
        raise DraftError("The feature description must be at most 2000 characters.")
    return normalized


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


def _prd_upstream(project_root: Path, feature: str) -> dict[str, Any]:
    """Resolve and verify the canonical Product draft consumed by Design."""
    state_path = project_root / ".speed" / "features" / feature / "authoring-prd.json"
    prd_state = _read_json(state_path)
    expected_path = f"specs/{feature}/prd.md"
    if not prd_state or prd_state.get("status") != "drafted":
        raise DraftError(
            "Design drafting requires a completed guided Product draft. Run "
            f"`workbench draft prd {feature}` first."
        )
    artifact = prd_state.get("artifact") or {}
    if artifact.get("path") != expected_path or not artifact.get("sha256"):
        raise DraftError("The Product checkpoint does not identify a usable PRD artifact.")
    prd_path = project_root / expected_path
    if not prd_path.is_file():
        raise DraftError(f"The Product checkpoint references a missing PRD: {expected_path}")
    actual_hash = hashlib.sha256(prd_path.read_bytes()).hexdigest()
    if actual_hash != artifact["sha256"]:
        raise UpstreamChanged(
            "The PRD content no longer matches its Product checkpoint. Resume Product "
            "drafting before starting or continuing Design."
        )
    return {
        "path": expected_path,
        "sha256": actual_hash,
        "interview_revision": prd_state["revision"],
        "question_bank_version": prd_state["question_bank_version"],
        "captured_at": _now(),
    }


def _validate_pinned_upstream(state: dict[str, Any], current: dict[str, Any]) -> None:
    pinned = (state.get("upstream") or {}).get("prd")
    if not pinned:
        raise DraftError("The Design checkpoint is missing its pinned PRD input.")
    stable_fields = ("path", "sha256", "interview_revision", "question_bank_version")
    if any(pinned.get(field) != current.get(field) for field in stable_fields):
        raise UpstreamChanged(
            "The PRD changed after this Design interview started. Existing Design "
            "answers were preserved, but they must be revalidated against the new PRD."
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
    feature_dir = project_root / ".speed" / "features" / feature
    sources: list[dict[str, str]] = []
    gaps: list[str] = []

    intake_description = (state.get("intake") or {}).get("feature_description")
    if state["artifact_type"] == "prd" and intake_description:
        sources.append(_source(
            "intake:feature-description",
            f".speed/features/{feature}/authoring-prd.json",
            intake_description,
        ))

    if state["artifact_type"] == "design":
        prd_path = project_root / state["upstream"]["prd"]["path"]
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
        }
        prd_content = prd_path.read_text(encoding="utf-8")
        usable_prd_section = False
        for heading in prd_sections[question_id]:
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
                f".speed/features/{feature}/authoring-{state['artifact_type']}.json",
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
    sources, gaps = _evidence_sources(project_root, feature, state, question["id"])
    context_path = project_root / ".speed" / "features" / feature / "context-package.json"
    context, _ = _read_evidence_json(context_path)
    prepared = (context or {}).get("suggested_responses", {}).get(question["id"], {})
    prepared_answer = prepared.get("answer") if isinstance(prepared, dict) else None
    if not prepared_answer and question["id"] == "P-Q1":
        prepared_answer = (state.get("intake") or {}).get("feature_description")

    if prepared_answer and sources:
        answer = str(prepared_answer).strip()
        confidence = "grounded" if not gaps else "partial"
        accept_ready = confidence == "grounded"
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
    }


def _new_state(
    feature: str,
    artifact_type: str,
    bank: dict[str, Any],
    upstream: dict[str, Any] | None = None,
    feature_description: str | None = None,
) -> dict[str, Any]:
    now = _now()
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
        "self_review": {
            "pass_count": 0,
            "max_passes": 2,
            "status": "pending",
            "findings": [],
            "artifact_sha256": None,
        },
        "artifact": None,
        "upstream": {"prd": upstream} if upstream else {},
        "intake": ({
            "feature_description": feature_description,
            "captured_at": now,
        } if feature_description else {}),
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
        and state.get("question_bank_version") == "prd-v1"
    ):
        # v2 preserves P-Q1..P-Q8 identities and only changes planning metadata
        # and contextual wording, so existing decisions remain valid.
        state["question_bank_version"] = "prd-v2"
        for question_id in list(state.get("suggestions", {})):
            if question_id not in state.get("answers", {}) and question_id not in state.get("follow_ups", {}):
                state["suggestions"].pop(question_id, None)
                state.get("edit_requests", {}).pop(question_id, None)
    state.setdefault("intake", {})
    state.setdefault("coverage", {})
    state.setdefault("clarification_plan", [])
    state.setdefault("clarifications_asked", [])
    state.setdefault("follow_ups", {})
    state.setdefault("edit_requests", {})
    state.setdefault("self_review", {
        "pass_count": 0,
        "max_passes": 2,
        "status": "pending",
        "findings": [],
        "artifact_sha256": None,
    })
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
        or not isinstance(state.get("self_review"), dict)
    ):
        raise DraftError(
            "Interview state has malformed follow-up, edit, or self-review data."
        )


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
    if state["artifact_type"] == "prd" and question["id"] not in state["clarifications_asked"]:
        state["clarifications_asked"].append(question["id"])
    existing = state["suggestions"].get(question["id"])
    if existing:
        return existing
    suggestion = _build_suggestion(project_root, feature, state, question)
    state["suggestions"][question["id"]] = suggestion
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
    return {
        question_id: record["answer"]
        for question_id, record in state["answers"].items()
        if record.get("state") == "confirmed"
    }


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
    normalized = " ".join(text.split())
    match = re.match(r"(.+?[.!?])(?:\s|$)", normalized)
    return (match.group(1) if match else normalized).strip()


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
    """Render the compact PRD core without exposing the interview transcript."""
    confirmed = _confirmed_answers(state)
    display_name = feature.replace("-", " ").title()
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
        f"<!-- Interview: {bank['version']}; revision: {state['revision']} -->\n\n"
        "> This provisional draft combines provided evidence, confirmed "
        "clarifications, and explicitly marked inferences. Detailed Design, RFC, "
        "Eval, and ADR material belongs in linked artifacts."
    )
    intent = str((state.get("intake") or {}).get("feature_description") or "")
    problem = confirmed.get("P-Q1") or intent
    summary = (
        f"This PRD defines **{display_name}**. {_first_sentence(problem)}"
        if problem
        else f"This PRD defines **{display_name}** from confirmed product inputs."
    )
    contextual_questions = {
        question["id"]: question["prompt"] for question in _active_questions(state, bank)
    }
    hypothesis = confirmed.get("P-Q3") or (
        f"**Inferred for review:** If **{display_name}** is delivered, then the "
        "affected user should be able to achieve the outcome stated in the "
        "requirement because the current limitation is removed."
    )
    identity_feature = bool(IDENTITY_SIGNAL_RE.search(_planning_text(state)))
    user_story = (
        f"**Inferred for review:** As an existing or new user, I want to authenticate "
        "securely so that I can access the product and its data privately."
        if identity_feature
        else confirmed.get("P-Q2")
        or f"**Inferred for review:** As an affected user, I want {display_name.lower()} "
        "so that I can achieve the outcome described in the requirement."
    )
    behavior_question_ids = ("P-Q2", "P-Q4", "P-Q5") if identity_feature else ("P-Q4", "P-Q5")
    behavior_answers = [
        confirmed[question_id]
        for question_id in behavior_question_ids
        if confirmed.get(question_id)
    ]
    requirements = "\n\n".join(behavior_answers) or (
        "| ID | Product behavior | Done when |\n"
        "|---|---|---|\n"
        f"| REQ-1 | **Proposed:** Support {display_name.lower()} as described in the "
        "requirement. | The affected user can complete the stated outcome without "
        "regressing existing behavior. |"
    )

    scope_item = state.get("coverage", {}).get("P-Q7", {})
    if confirmed.get("P-Q7"):
        scope = confirmed["P-Q7"]
    elif scope_item.get("confidence_label") == "unresolved":
        scope = f"**Unresolved:** {contextual_questions.get('P-Q7', 'Confirm the material scope boundary.')}"
    else:
        scope = (
            f"**Included:** {display_name}.  \n"
            "**Not included:** No adjacent capability is implied by the current requirement."
        )

    control_item = state.get("coverage", {}).get("P-Q8", {})
    if confirmed.get("P-Q8"):
        guardrails = delivery = confirmed["P-Q8"]
    elif control_item.get("confidence_label") == "unresolved":
        unresolved_control = contextual_questions.get(
            "P-Q8", "Confirm the material guardrail or delivery decision."
        )
        guardrails = f"**Unresolved:** {unresolved_control}"
        delivery = f"**Open question:** {unresolved_control}"
    else:
        guardrails = "The existing product regression baseline continues to apply."
        delivery = "No feature-specific delivery risk was identified from current evidence."

    success = confirmed.get("P-Q6") or (
        "**Proposed for review:** Users can complete the intended outcome described "
        "in this PRD. A numeric target is provisional until an existing baseline or "
        "measurement owner is confirmed."
    )

    sections = [
        f"## Summary\n\n{summary}",
        f"## Problem & Evidence\n\n{problem or 'No grounded problem statement was provided.'}",
        f"## Hypothesis\n\n{hypothesis}",
        f"## User Stories\n\n{user_story}",
        f"## Requirements & Acceptance\n\n{requirements}",
        f"## Scope\n\n{scope}",
        f"## Guardrails / Must Not Regress\n\n{guardrails}",
        f"## Delivery, Risks & Open Questions\n\n{delivery}",
        f"## Success\n\n{success}",
    ]

    references = []
    seen_paths = set()
    for suggestion in state.get("suggestions", {}).values():
        for source in suggestion.get("sources", []):
            path = source.get("path")
            if path and path not in seen_paths:
                seen_paths.add(path)
                references.append(f"- `{path}`")
    references_body = "\n".join(references) or "- No durable reference was provided."
    sections.append(f"## References\n\n{references_body}")
    return header + "\n\n" + "\n\n".join(sections) + "\n"


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
    if artifact_type == "design":
        upstream = state["upstream"]["prd"]
        header += (
            "  \n**Product source:** [PRD](prd.md)  \n"
            f"**Product source hash:** `{upstream['sha256']}`  \n"
            f"**Product interview revision:** `{upstream['interview_revision']}`\n\n"
            "> This experience contract maps confirmed Design answers to the linked "
            "Product requirements. Workbench has not created independent product scope."
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
    feature_dir = project_root / ".speed" / "features" / feature
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
        "content": content,
        "file_path": artifact_path,
        "template_name": f"{artifact_type}.md",
        "generated_at": now,
        "child_specs": [],
    }
    if artifact_type == "design":
        draft_record["upstream"] = state["upstream"]
    draft_record["authoring"] = {
        "revision": state["revision"],
        "self_review": state["self_review"],
    }
    _write_json(feature_dir / f"draft-{artifact_type}.json", draft_record)

    package_index = project_root / "specs" / feature / "index.md"
    if not package_index.exists():
        index_content = (
            f"# Define Package: {feature}\n\n"
            "| Artifact | Status | Review |\n"
            "|---|---|---|\n"
        )
    else:
        index_content = package_index.read_text(encoding="utf-8")
    label = ARTIFACTS[artifact_type]["label"]
    filename = f"{artifact_type}.md"
    row = f"| [{label}]({filename}) | Draft | [Open dashboard]({dashboard_url}) |"
    if f"]({filename})" not in index_content:
        index_content = index_content.rstrip() + "\n" + row + "\n"
        _atomic_write(package_index, index_content)


def _generate(
    project_root: Path,
    feature: str,
    state: dict[str, Any],
    bank: dict[str, Any],
    dashboard_base: str,
) -> None:
    pending = _pending_questions(state, bank)
    if pending and state["artifact_type"] != "prd":
        deferred = [q["id"] for q in pending if q["id"] in state["answers"]]
        persona = ARTIFACTS[state["artifact_type"]]["persona"]
        raise DraftError(
            f"All required {persona} questions must be confirmed before generation"
            + (f"; deferred: {', '.join(deferred)}" if deferred else ".")
        )

    artifact_type = state["artifact_type"]
    if artifact_type == "design":
        _validate_pinned_upstream(state, _prd_upstream(project_root, feature))
    artifact_path = f"specs/{feature}/{artifact_type}.md"
    dashboard_url = f"{dashboard_base.rstrip('/')}/define/{feature}"
    content = _render_artifact(feature, state, bank)
    artifact_file = project_root / artifact_path
    _atomic_write(artifact_file, content)
    _ensure_define_compatibility(
        project_root, feature, state, content, artifact_path, dashboard_url
    )
    state["status"] = "clarifying" if pending else "drafted"
    state["artifact"] = {
        "path": artifact_path,
        "sha256": hashlib.sha256(content.encode()).hexdigest(),
        "generated_at": _now(),
        "dashboard_url": dashboard_url,
    }
    if artifact_type == "design":
        state["artifact"]["upstream"] = state["upstream"]


def _self_review(
    project_root: Path,
    feature: str,
    state: dict[str, Any],
    bank: dict[str, Any],
) -> None:
    """Run deterministic review and reopen source questions at most once."""
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

    for heading in ARTIFACTS[state["artifact_type"]]["sections"]:
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

    if review["pass_count"] < review["max_passes"]:
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
        return

    review["status"] = "open_questions"
    state["status"] = "drafted_with_open_questions"
    open_questions = "\n\n## Self-Review Open Questions\n\n" + "\n".join(
        f"- **{finding.get('question_id') or 'Artifact'}:** {finding['message']}"
        for finding in findings
    ) + "\n"
    content = content.rstrip() + open_questions
    _atomic_write(artifact_path, content)
    state["artifact"]["sha256"] = hashlib.sha256(content.encode()).hexdigest()
    state["artifact"]["generated_at"] = _now()
    review["artifact_sha256"] = state["artifact"]["sha256"]
    _ensure_define_compatibility(
        project_root,
        feature,
        state,
        content,
        state["artifact"]["path"],
        state["artifact"]["dashboard_url"],
    )


def _result(state: dict[str, Any], bank: dict[str, Any]) -> dict[str, Any]:
    pending = _pending_questions(state, bank)
    active_questions = _active_questions(state, bank)
    active_ids = {question["id"] for question in active_questions}
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
            response_control = {
                "id": "follow_up_answer",
                "input_type": "textarea",
                "prompt": follow_up["prompt"],
                "initial_value": "",
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
    return {
        "skill": SKILL,
        "implementation": _implementation(state["artifact_type"]),
        "status": status,
        "feature_name": state["feature_name"],
        "artifact_type": state["artifact_type"],
        "upstream": state.get("upstream", {}),
        "question_bank_version": state["question_bank_version"],
        "revision": state["revision"],
        "resume_step": resume_step,
        "self_review": state.get("self_review"),
        "coverage": state.get("coverage", {}),
        "draft_available": bool(artifact.get("path")),
        "progress": {
            "confirmed": sum(
                1
                for question_id, record in state["answers"].items()
                if question_id in active_ids and record.get("state") == "confirmed"
            ),
            "total": len(active_questions),
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
        "artifact_path": artifact.get("path"),
        "dashboard_url": artifact.get("dashboard_url"),
        "message": (
            f"{ARTIFACTS[state['artifact_type']]['label']} draft generated from "
            "confirmed interview answers."
            if status == "drafted"
            else "Draft generated with unresolved self-review findings recorded as open questions."
            if status == "drafted_with_open_questions"
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
                "A provisional PRD is available. Answer this material clarification "
                "to update the affected sections."
                if state["artifact_type"] == "prd" and artifact.get("path")
                else f"Answer the current {ARTIFACTS[state['artifact_type']]['persona']} "
                "interview question."
            )
        ),
    }


def _format_text(result: dict[str, Any]) -> str:
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
            "question_prompt": question["prompt"],
            "decision": action,
            "suggestion_id": suggestion["id"],
            "actor": actor_name,
            "actor_email": actor_email,
            "evidence_prompt": question["evidence"],
            "quality_gaps": quality_gaps,
            "confirmed_at": _now(),
        }
    state["answers"][question["id"]] = record
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
    state["artifact"] = None


def _apply_coverage_update(
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
    actor_name, actor_email = actor
    question_id = question["id"]
    state["answers"][question_id] = {
        "state": "confirmed",
        "answer": revised,
        "question_prompt": f"Draft review update for {question.get('coverage')}",
        "decision": "review_edited",
        "suggestion_id": None,
        "actor": actor_name,
        "actor_email": actor_email,
        "evidence_prompt": "Human review of the generated PRD",
        "quality_gaps": _answer_quality_gaps(question, revised),
        "confirmed_at": _now(),
    }
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


def run_once(args: argparse.Namespace) -> dict[str, Any]:
    project_root = Path(args.project_root).resolve()
    feature = _validate_feature(args.feature_name)
    artifact_type = args.artifact_type
    feature_description = _validate_feature_description(args.feature_description)
    if artifact_type != "prd" and feature_description:
        raise DraftError("--feature-description is supported only when starting a PRD.")
    bank = _load_question_bank(artifact_type)
    feature_dir = project_root / ".speed" / "features" / feature
    state_path = feature_dir / f"authoring-{artifact_type}.json"

    with _feature_lock(feature_dir):
        upstream = _prd_upstream(project_root, feature) if artifact_type == "design" else None
        persisted = _read_json(state_path)
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
            )
        )
        _validate_state(state, feature, artifact_type, bank)
        if upstream:
            _validate_pinned_upstream(state, upstream)
        _ensure_current_suggestion(project_root, feature, state, bank)
        if args.update_coverage:
            if args.answer is None:
                raise DraftError("--update-coverage requires --answer with the revised content.")
            _apply_coverage_update(
                state,
                bank,
                args.update_coverage,
                args.answer,
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
            )
            _ensure_current_suggestion(project_root, feature, state, bank)
        pending = _pending_questions(state, bank)
        if artifact_type == "prd" and not state.get("artifact"):
            _generate(project_root, feature, state, bank, args.dashboard_url)
            if not pending:
                _self_review(project_root, feature, state, bank)
        elif (
            artifact_type != "prd"
            and not pending
            and state.get("status") not in {"drafted", "drafted_with_open_questions"}
        ):
            _generate(project_root, feature, state, bank, args.dashboard_url)
            _self_review(project_root, feature, state, bank)
        _write_json(state_path, state)
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
        if result["status"] in {"drafted", "drafted_with_open_questions"}:
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
    action.add_argument("--defer", action="store_true")
    action.add_argument("--accept-suggestion", action="store_true")
    action.add_argument("--edit-suggestion", action="store_true")
    action.add_argument("--reject-suggestion", action="store_true")
    parser.add_argument("--expected-revision", type=int)
    parser.add_argument(
        "--update-coverage",
        help="Stable PRD coverage ID or section name to revise during draft review",
    )
    parser.add_argument(
        "--feature-description",
        help="Direct user context used as initial problem evidence",
    )
    parser.add_argument(
        "--dashboard-url",
        default=os.environ.get("WORKBENCH_DASHBOARD_URL", "http://localhost:3000"),
    )
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.artifact_type is None or args.feature_name is None:
            result = _intake_result(Path(args.project_root).resolve(), args.artifact_type)
            print(json.dumps(result, indent=2) if args.json else _format_intake(result))
            return 0
        should_interview = (
            sys.stdin.isatty()
            and not args.json
            and args.answer is None
            and args.update_coverage is None
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
