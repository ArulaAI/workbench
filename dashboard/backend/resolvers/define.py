"""Define page resolver — reads specs, features, defects and assembles DefineView."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from .define_types import (
    BuiltData,
    DefineAggregates,
    DefineDefect,
    DefineFeature,
    DefineView,
    GapData,
    GapEscalation,
    SpecifiedData,
    SpecIndicator,
)
from .landing import _read_vision_status, _read_task_files

log = logging.getLogger("speed.dashboard.define")


# ── Constants ────────────────────────────────────────────────────────────────

_VALID_SEVERITIES = frozenset(["P0", "P1", "P2", "P3"])
_SEVERITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}

# Required sections per spec type (V1 audit: structural checks only)
_PRD_REQUIRED_SECTIONS = frozenset([
    "Problem",
    "Users",
    "User Stories",
    "Scope",
    "Success Criteria",
])

_RFC_REQUIRED_SECTIONS = frozenset([
    "Basic Example",
    "Data Model",
    "API Surface",
])

# States that indicate a feature is actively executing or beyond
_EXECUTING_STATES = frozenset(["running", "executing"])
_COMPLETED_STATES = frozenset(["done", "completed"])


# ── Shared helpers ───────────────────────────────────────────────────────────


def _read_json(path: Path) -> dict[str, Any] | None:
    """Safely read a JSON file, returning None on any error."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, ValueError):
        return None


def _read_json_lenient(path: Path) -> Any:
    """Read JSON returning the raw parsed value (dict, list, etc.) or None."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, ValueError):
        return None


# ── Spec audit ───────────────────────────────────────────────────────────────


def _extract_headings(content: str) -> set[str]:
    """Extract markdown heading text (## Heading) from content."""
    from ..spec_parser import extract_sections_from_content

    sections = extract_sections_from_content(content)
    return {s.heading for s in sections}


def _audit_spec(path: Path, spec_type: str) -> SpecIndicator:
    """Audit a spec file for required sections.

    Args:
        path: Path to the markdown spec file.
        spec_type: "product" for PRD checks, "tech" for RFC checks.
            Other types get a clean pass (no required sections defined).

    Returns:
        SpecIndicator with exists, path, audit_status, warning_count, and warnings.
    """
    if not path.exists():
        return SpecIndicator(
            exists=False,
            path=None,
            audit_status="error",
            warning_count=0,
            warnings=[],
        )

    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return SpecIndicator(
            exists=True,
            path=str(path),
            audit_status="error",
            warning_count=0,
            warnings=[],
        )

    # 0-byte or whitespace-only file
    if not content.strip():
        return SpecIndicator(
            exists=True,
            path=str(path),
            audit_status="error",
            warning_count=0,
            warnings=[],
        )

    # Select required sections based on spec type
    if spec_type == "product":
        required = _PRD_REQUIRED_SECTIONS
    elif spec_type == "tech":
        required = _RFC_REQUIRED_SECTIONS
    else:
        # Design specs and other types have no required section checks in V1
        return SpecIndicator(
            exists=True,
            path=str(path),
            audit_status="clean",
            warning_count=0,
            warnings=[],
        )

    headings = _extract_headings(content)
    warnings: list[str] = []

    for section in sorted(required):
        # Case-insensitive match: check if any heading contains the required section name
        found = any(section.lower() in h.lower() for h in headings)
        if not found:
            warnings.append(f"Missing required section: {section}")

    if warnings:
        return SpecIndicator(
            exists=True,
            path=str(path),
            audit_status="error",
            warning_count=len(warnings),
            warnings=warnings,
        )

    return SpecIndicator(
        exists=True,
        path=str(path),
        audit_status="clean",
        warning_count=0,
        warnings=[],
    )


def _empty_spec_indicator() -> SpecIndicator:
    """Return a SpecIndicator for a spec that does not exist."""
    return SpecIndicator(
        exists=False,
        path=None,
        audit_status="error",
        warning_count=0,
        warnings=[],
    )


# ── Spec-to-feature matching ────────────────────────────────────────────────


def _read_frontmatter_feature(path: Path) -> str | None:
    """Read the 'feature:' field from YAML frontmatter if present."""
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None

    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return None

    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            break
        if stripped.lower().startswith("feature:"):
            value = stripped.split(":", 1)[1].strip()
            # Remove quotes if present
            if value and value[0] in ('"', "'") and value[-1] == value[0]:
                value = value[1:-1]
            return value if value else None

    return None


def _match_specs_to_feature(
    project_root: Path, feature_name: str,
) -> tuple[dict[str, Path | None], list[tuple[str, Path]]]:
    """Match spec files to a feature by filename convention, with frontmatter fallback.

    Returns:
      - primary: dict with keys 'product', 'tech', 'design' mapping to file paths or None
      - additional: list of (spec_type, path) for extra specs beyond the primary one per type
    """
    spec_dirs = {
        "product": project_root / "specs" / "product",
        "tech": project_root / "specs" / "tech",
        "design": project_root / "specs" / "design",
    }

    primary: dict[str, Path | None] = {"product": None, "tech": None, "design": None}
    additional: list[tuple[str, Path]] = []

    for spec_type, spec_dir in spec_dirs.items():
        if not spec_dir.is_dir():
            continue

        # Primary match: filename convention
        candidate = spec_dir / f"{feature_name}.md"
        if candidate.exists():
            primary[spec_type] = candidate

        # Scan for frontmatter matches (may find additional specs)
        try:
            for md_file in spec_dir.glob("*.md"):
                if md_file.name == "overview.md":
                    continue
                if md_file == candidate and candidate.exists():
                    continue  # skip the primary match
                fm_feature = _read_frontmatter_feature(md_file)
                if fm_feature == feature_name:
                    if primary[spec_type] is None:
                        primary[spec_type] = md_file
                    else:
                        additional.append((spec_type, md_file))
        except OSError:
            pass

    return primary, additional


# ── Build helpers ────────────────────────────────────────────────────────────


def _build_specified(project_root: Path, feature_name: str) -> SpecifiedData:
    """Assemble spec indicators, open question count, and sizing estimate for a feature."""
    from .define_types import AdditionalSpec
    specs, extra_specs = _match_specs_to_feature(project_root, feature_name)

    product_spec = (
        _audit_spec(specs["product"], "product")
        if specs["product"]
        else _empty_spec_indicator()
    )
    technical_spec = (
        _audit_spec(specs["tech"], "tech")
        if specs["tech"]
        else _empty_spec_indicator()
    )
    design_spec = (
        _audit_spec(specs["design"], "design")
        if specs["design"]
        else _empty_spec_indicator()
    )

    additional_specs = []
    for stype, spath in extra_specs:
        indicator = _audit_spec(spath, stype)
        additional_specs.append(AdditionalSpec(
            path=str(spath.relative_to(project_root)),
            spec_type=stype,
            audit_status=indicator.audit_status,
            warning_count=indicator.warning_count,
        ))

    # Count open questions from product spec (lines starting with "?" or containing "open question")
    open_questions = 0
    if specs["product"] and specs["product"].exists():
        try:
            content = specs["product"].read_text(encoding="utf-8")
            for line in content.splitlines():
                stripped = line.strip()
                if stripped.startswith("?") or "open question" in stripped.lower():
                    open_questions += 1
        except OSError:
            pass

    # Sizing estimate: rough heuristic based on user story count * 2
    sizing_estimate = None
    if specs["product"] and specs["product"].exists():
        try:
            content = specs["product"].read_text(encoding="utf-8")
            story_count = 0
            in_stories = False
            for line in content.splitlines():
                stripped = line.strip()
                if re.match(r"^#{1,6}\s+.*user stor", stripped, re.IGNORECASE):
                    in_stories = True
                    continue
                if in_stories and re.match(r"^#{1,6}\s+", stripped):
                    in_stories = False
                if in_stories and stripped.startswith("- "):
                    story_count += 1
            if story_count > 0:
                sizing_estimate = story_count * 2
        except OSError:
            pass

    return SpecifiedData(
        product_spec=product_spec,
        technical_spec=technical_spec,
        design_spec=design_spec,
        additional_specs=additional_specs,
        open_questions=open_questions,
        sizing_estimate=sizing_estimate,
    )


def _build_built(project_root: Path, feature_name: str) -> BuiltData:
    """Assemble built data from task files, spec-traceability, criteria-verify, and Guardian logs."""
    from ..paths import get_paths
    paths = get_paths(project_root)
    shared = paths.feature_shared(feature_name)
    local = paths.feature_local(feature_name)

    # Read tasks
    tasks_dir = shared / "tasks"
    tasks = _read_task_files(tasks_dir)

    tasks_total = len(tasks) if tasks else None
    tasks_done = None
    blocked_count = 0
    task_progress = None
    completed_at = None

    if tasks:
        tasks_done = sum(1 for t in tasks if t.get("status") in ("done", "completed"))
        blocked_count = sum(1 for t in tasks if t.get("status") == "blocked")
        task_progress = round((tasks_done / tasks_total * 100), 1) if tasks_total else None

    # Read state for completed_at
    state_file = local / "state.json"
    state = _read_json(state_file)
    if state:
        completed_at = state.get("completed_at")

    # Read spec-traceability.json for coverage
    coverage_pct = None
    trace_file = shared / "spec-traceability.json"
    if trace_file.exists():
        trace_data = _read_json(trace_file)
        if trace_data:
            raw_pct = trace_data.get("coverage_pct") or trace_data.get("coverage_ratio")
            if raw_pct is not None:
                pct = float(raw_pct)
                coverage_pct = max(0.0, min(100.0, pct * 100 if pct <= 1.0 else pct))

    # Read criteria-verify.json
    criteria_passed = None
    criteria_total_cv = None
    cv_file = shared / "criteria-verify.json"
    if cv_file.exists():
        cv_data = _read_json_lenient(cv_file)
        if isinstance(cv_data, dict):
            criteria_passed = cv_data.get("criteria_passed")
            criteria_total_cv = cv_data.get("criteria_total")
            if criteria_passed is not None:
                criteria_passed = int(criteria_passed)
            if criteria_total_cv is not None:
                criteria_total_cv = int(criteria_total_cv)
        elif isinstance(cv_data, list):
            criteria_total_cv = len(cv_data)
            criteria_passed = 0

    # Read Guardian verdict
    guardian_verdict = _read_guardian_verdict(local)

    return BuiltData(
        coverage_pct=coverage_pct,
        criteria_passed=criteria_passed,
        criteria_total=criteria_total_cv,
        guardian_verdict=guardian_verdict,
        task_progress=task_progress,
        tasks_done=tasks_done,
        tasks_total=tasks_total,
        blocked_count=blocked_count,
        completed_at=completed_at,
    )


def _read_guardian_verdict(local_dir: Path) -> str | None:
    """Read Guardian verdict from log files.

    Checks guardian-*.json, then Guardian-*.jsonl in the logs directory.
    Returns None if no Guardian data exists.

    Args:
        local_dir: The local feature directory (contains logs/).
    """
    logs_dir = local_dir / "logs"
    if not logs_dir.is_dir():
        return None

    # Try structured JSON logs first
    guardian_logs = sorted(logs_dir.glob("guardian-*.json"))
    if not guardian_logs:
        guardian_logs = sorted(logs_dir.glob("Guardian-*.jsonl"))
    if not guardian_logs:
        return None

    log_file = guardian_logs[-1]

    # Try as single JSON object
    try:
        content = log_file.read_text(encoding="utf-8")
        data = json.loads(content)
        if isinstance(data, dict):
            verdict = data.get("verdict") or data.get("status")
            if verdict:
                return verdict
    except (OSError, json.JSONDecodeError):
        pass

    # Try as JSONL (last line with verdict)
    try:
        content = log_file.read_text(encoding="utf-8")
        lines = [line for line in content.splitlines() if line.strip()]
        if lines:
            last_entry = json.loads(lines[-1])
            verdict = last_entry.get("verdict")
            if verdict:
                return verdict
    except (OSError, json.JSONDecodeError, AttributeError):
        pass

    return None


def _build_gap(project_root: Path, feature_name: str) -> GapData:
    """Assemble gap data from escalations.json and task files."""
    from ..paths import get_paths
    paths = get_paths(project_root)
    shared = paths.feature_shared(feature_name)

    # Read escalations.json
    escalations: list[GapEscalation] = []
    esc_file = shared / "escalations.json"
    if esc_file.exists():
        esc_data = _read_json_lenient(esc_file)
        if isinstance(esc_data, list):
            for entry in esc_data:
                if isinstance(entry, dict):
                    desc = entry.get("description") or entry.get("question") or ""
                    escalations.append(GapEscalation(
                        description=str(desc),
                        linked_warning_id=entry.get("linked_warning_id"),
                    ))
        elif isinstance(esc_data, dict):
            for entry in esc_data.get("escalations", []):
                if isinstance(entry, dict):
                    desc = entry.get("description") or entry.get("question") or ""
                    escalations.append(GapEscalation(
                        description=str(desc),
                        linked_warning_id=entry.get("linked_warning_id"),
                    ))

    # Also count escalations from blocked tasks with escalation_question
    tasks_dir = shared / "tasks"
    tasks = _read_task_files(tasks_dir)

    for task in tasks:
        question = task.get("escalation_question")
        if question and not task.get("escalation_response"):
            escalations.append(GapEscalation(
                description=str(question),
                linked_warning_id=None,
            ))

    # Rework count: tasks with retry_count > 0
    rework_count = sum(1 for t in tasks if t.get("retry_count", 0) > 0)

    # Unverifiable criteria: count from criteria-verify.json
    unverifiable_count = 0
    cv_file = shared / "criteria-verify.json"
    if cv_file.exists():
        cv_data = _read_json_lenient(cv_file)
        if isinstance(cv_data, dict):
            criteria = cv_data.get("criteria", [])
            if isinstance(criteria, list):
                unverifiable_count = sum(
                    1 for c in criteria
                    if isinstance(c, dict) and c.get("status") == "unverifiable"
                )
        elif isinstance(cv_data, list):
            unverifiable_count = sum(
                1 for c in cv_data
                if isinstance(c, dict) and c.get("status") == "unverifiable"
            )

    return GapData(
        escalation_count=len(escalations),
        escalations=escalations,
        unverifiable_count=unverifiable_count,
        rework_count=rework_count,
    )


# ── Defects ──────────────────────────────────────────────────────────────────


def _build_defects(project_root: Path) -> list[DefineDefect]:
    """Read defects from .speed/defects/*/state.json and specs/defects/*.md.

    Enriches with description from defect spec markdown (first paragraph).
    Clamps unknown severity values to P3.
    """
    seen: set[str] = set()
    defects: list[DefineDefect] = []

    # Source 1: defects/*/state.json
    from ..paths import get_paths
    paths = get_paths(project_root)
    defects_dir = paths.defects_dir
    if defects_dir.is_dir():
        for state_file in sorted(defects_dir.glob("*/state.json")):
            data = _read_json(state_file)
            if data is None:
                continue
            name = data.get("name", state_file.parent.name)
            severity = data.get("severity", "P3")
            if severity not in _VALID_SEVERITIES:
                severity = "P3"
            status = data.get("status", "open")
            filed_at = data.get("filed_at") or data.get("created_at")
            impact = data.get("impact")

            # Read description from companion spec markdown
            description = data.get("description", "")
            if not description:
                spec_md = project_root / "specs" / "defects" / f"{name}.md"
                description = _read_defect_description(spec_md)

            seen.add(name)
            defects.append(DefineDefect(
                name=name,
                severity=severity,
                status=status,
                description=description,
                impact=impact,
                filed_at=filed_at,
            ))

    # Source 2: specs/defects/*.md (only if not already seen)
    specs_defects_dir = project_root / "specs" / "defects"
    if specs_defects_dir.is_dir():
        for md_file in sorted(specs_defects_dir.glob("*.md")):
            name = md_file.stem
            if name in seen:
                continue

            severity = _parse_severity_from_md(md_file)
            description = _read_defect_description(md_file)

            defects.append(DefineDefect(
                name=name,
                severity=severity,
                status="open",
                description=description,
                impact=None,
                filed_at=None,
            ))

    defects.sort(key=lambda d: _SEVERITY_ORDER.get(d.severity, 3))
    return defects


def _read_defect_description(md_path: Path) -> str:
    """Read the first paragraph from a defect spec markdown file as description."""
    try:
        content = md_path.read_text(encoding="utf-8")
    except OSError:
        return ""

    lines = content.splitlines()
    paragraph_lines: list[str] = []
    past_heading = False

    for line in lines:
        stripped = line.strip()
        # Skip frontmatter
        if stripped == "---" and not past_heading:
            continue
        # Skip headings
        if stripped.startswith("#"):
            if past_heading and paragraph_lines:
                break
            past_heading = True
            continue
        # Collect first paragraph (non-empty lines after first heading)
        if past_heading:
            if stripped:
                paragraph_lines.append(stripped)
            elif paragraph_lines:
                break

    return " ".join(paragraph_lines) if paragraph_lines else ""


def _parse_severity_from_md(md_path: Path) -> str:
    """Parse severity from a "Severity: PX" line in the first 10 lines of a markdown file."""
    try:
        for line in md_path.read_text(encoding="utf-8").splitlines()[:10]:
            if line.strip().lower().startswith("severity:"):
                val = line.split(":", 1)[1].strip().upper()
                if val in _VALID_SEVERITIES:
                    return val
                return "P3"
    except OSError:
        pass
    return "P3"


# ── Aggregates ───────────────────────────────────────────────────────────────


def _compute_aggregates(features: list[DefineFeature]) -> DefineAggregates:
    """Compute aggregate fields from the features list."""
    design_spec_count = sum(1 for f in features if f.specified.design_spec.exists)
    feature_count = len(features)

    audit_warning_count = 0
    open_question_count = 0
    escalation_count = 0
    completed_count = 0
    executing_count = 0
    unplanned_count = 0

    for f in features:
        # Sum warnings across all spec types
        audit_warning_count += f.specified.product_spec.warning_count
        audit_warning_count += f.specified.technical_spec.warning_count
        audit_warning_count += f.specified.design_spec.warning_count

        open_question_count += f.specified.open_questions
        escalation_count += f.gap.escalation_count

        if f.state in ("done", "completed"):
            completed_count += 1
        elif f.state in ("running", "executing"):
            executing_count += 1
        elif f.state == "unplanned":
            unplanned_count += 1

    return DefineAggregates(
        design_spec_count=design_spec_count,
        feature_count=feature_count,
        audit_warning_count=audit_warning_count,
        open_question_count=open_question_count,
        escalation_count=escalation_count,
        completed_count=completed_count,
        executing_count=executing_count,
        unplanned_count=unplanned_count,
    )


# ── Feature state ────────────────────────────────────────────────────────────


def _read_feature_state(local_dir: Path) -> str:
    """Read feature state from state.json, defaulting to 'unplanned'.

    Args:
        local_dir: The local feature directory (contains state.json).
    """
    state_file = local_dir / "state.json"
    data = _read_json(state_file)
    if data is None:
        return "unplanned"
    return data.get("status", "unplanned")


# ── Vision path ──────────────────────────────────────────────────────────────


def _resolve_vision_path(project_root: Path) -> str | None:
    """Return the relative path to the vision document if it exists."""
    overview = project_root / "specs" / "product" / "overview.md"
    if overview.exists():
        return "specs/product/overview.md"
    return None


# ── Orchestrator ─────────────────────────────────────────────────────────────


def get_define_view(project_root: Path, feature: str | None = None) -> DefineView:
    """Assemble the complete Define view from filesystem sources.

    Args:
        project_root: Path to the project root directory.
        feature: Optional filter. When provided, only features whose name
            ends with this string are included (str.endswith semantics).
            Aggregates are recomputed from the filtered list.
            Defects are never filtered.

    Returns:
        DefineView with vision status, features, defects, and aggregates.
    """
    from ..paths import get_paths
    paths = get_paths(project_root)

    vision_status = _read_vision_status(project_root)
    vision_path = _resolve_vision_path(project_root)

    # Discover features from .speed/features/ directories
    features: list[DefineFeature] = []

    for feature_name in paths.feature_names():
        local = paths.feature_local(feature_name)
        state = _read_feature_state(local)

        specified = _build_specified(project_root, feature_name)
        built = _build_built(project_root, feature_name)
        gap = _build_gap(project_root, feature_name)

        features.append(DefineFeature(
            name=feature_name,
            state=state,
            specified=specified,
            built=built,
            gap=gap,
        ))

    # Also discover features from specs that don't have .speed/features/ entries
    product_dir = project_root / "specs" / "product"
    if product_dir.is_dir():
        existing_names = {f.name for f in features}
        for spec_file in sorted(product_dir.glob("*.md")):
            if spec_file.name == "overview.md":
                continue
            spec_name = spec_file.stem
            if spec_name in existing_names:
                continue

            specified = _build_specified(project_root, spec_name)
            built = _build_built(project_root, spec_name)
            gap = _build_gap(project_root, spec_name)

            features.append(DefineFeature(
                name=spec_name,
                state="unplanned",
                specified=specified,
                built=built,
                gap=gap,
            ))

    # Apply feature filter (str.endswith semantics)
    if feature:
        features = [f for f in features if f.name.endswith(feature)]

    # Compute aggregates from (potentially filtered) features
    aggregates = _compute_aggregates(features)

    # Defects are never filtered
    defects = _build_defects(project_root)

    return DefineView(
        vision_status=vision_status,
        vision_path=vision_path,
        features=features,
        defects=defects,
        aggregates=aggregates,
    )
