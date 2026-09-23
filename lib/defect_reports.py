"""Shared defect report parsing, inventory, filtering, and rendering.

This module intentionally depends only on the Python standard library.  The
dashboard, CLI, and Bash compatibility wrappers all consume the same model so
that a defect cannot acquire different metadata depending on where it is read.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


VALID_SEVERITIES = frozenset({"P0", "P1", "P2", "P3"})
CLOSED_STATUSES = frozenset({"resolved", "rejected"})
_SEVERITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "unknown": 4}
_FEATURE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,49}$")
_PLACEHOLDER_RE = re.compile(
    r"^\s*(?:<[^>]+>|\{[^}]+\}|tbd|todo|\[redacted:[^]]+\])\s*$", re.I,
)
_META_RE = re.compile(
    r"^\s*(?:\*\*)?"
    r"(?P<key>severity|related features?|reproducibility|last known working|source feature|source|intake request|"
    r"related files|affected files|tags)"
    r"(?:\*\*\s*:|\s*:\s*\*\*|\s*:)\s*(?P<value>.*?)\s*$",
    re.I,
)
_SECTION_RE = re.compile(r"^#{1,6}\s+(?P<name>.+?)\s*$")
_LINK_RE = re.compile(r"\[[^]]+\]\((?P<path>[^)]+)\)")


def secret_fields(fields: dict[str, str]) -> set[str]:
    """Return field names matching the existing grounding secret patterns."""
    grounding = Path(__file__).with_name("grounding.sh")
    script = r'''
source "$1"
_patterns=()
while IFS=$'\t' read -r _name _regex; do
    _patterns+=( -e "$_regex" )
done < <(_secrets_pattern_pairs)
grep -qE "${_patterns[@]}"
exit $?
'''
    flagged: set[str] = set()
    for name, value in fields.items():
        result = subprocess.run(
            ["/bin/bash", "-c", script, "secret-scan", str(grounding)],
            input=str(value), text=True, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, check=False,
        )
        if result.returncode == 0:
            flagged.add(name)
        elif result.returncode != 1:
            raise RuntimeError("secret-pattern scanner failed")
    return flagged


def _clean_value(value: Any) -> str:
    text = str(value or "").strip()
    return "" if _PLACEHOLDER_RE.match(text) else text


def _slug_from_feature(value: str) -> str:
    value = value.strip().strip("`")
    match = _LINK_RE.fullmatch(value)
    if match:
        value = match.group("path")
    value = value.split("#", 1)[0].rstrip("/")
    if value.endswith(".md"):
        value = Path(value).stem
    return value.strip()


def _split_values(value: Any, *, feature_names: bool = False) -> list[str]:
    if isinstance(value, list):
        raw = [str(item) for item in value]
    else:
        raw = re.split(r",\s*", str(value or ""))
    result: list[str] = []
    for item in raw:
        normalized = _slug_from_feature(item) if feature_names else item.strip().strip("`")
        if normalized and normalized not in result and not _PLACEHOLDER_RE.match(normalized):
            result.append(normalized)
    return result


def _frontmatter(text: str) -> tuple[dict[str, Any], str, list[str]]:
    """Return YAML frontmatter, remaining Markdown, and parse warnings."""
    if not text.startswith("---\n"):
        return {}, text, []
    end = text.find("\n---", 4)
    if end < 0:
        return {}, text, ["Unterminated YAML frontmatter"]
    raw = text[4:end]
    body = text[end + 4 :].lstrip("\n")
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(raw) or {}
        if not isinstance(data, dict):
            return {}, body, ["YAML frontmatter must be an object"]
        return data, body, []
    except ImportError:
        # The common scalar/list subset remains readable without PyYAML.
        data: dict[str, Any] = {}
        for line in raw.splitlines():
            if ":" not in line or line[:1].isspace():
                continue
            key, value = line.split(":", 1)
            value = value.strip()
            if value.startswith("[") and value.endswith("]"):
                data[key.strip()] = [v.strip(" '\"") for v in value[1:-1].split(",")]
            else:
                data[key.strip()] = value.strip("'\"")
        return data, body, ["PyYAML unavailable; parsed simple frontmatter only"]
    except Exception as exc:
        return {}, body, [f"Malformed YAML frontmatter: {exc}"]


def _sections(markdown: str) -> tuple[str, dict[str, str], dict[str, str]]:
    """Extract title, named section bodies, and metadata outside code fences."""
    title = ""
    sections: dict[str, list[str]] = {}
    metadata: dict[str, str] = {}
    current = ""
    in_fence = False
    in_comment = False
    for raw in markdown.splitlines():
        stripped = raw.strip()
        if "<!--" in stripped:
            in_comment = True
        if in_comment:
            if "-->" in stripped:
                in_comment = False
            continue
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        heading = _SECTION_RE.match(raw)
        if heading:
            name = heading.group("name").strip()
            if not title and raw.lstrip().startswith("# "):
                title = re.sub(r"^Defect:\s*", "", name, flags=re.I).strip()
                current = ""
            else:
                current = name.casefold()
                sections.setdefault(current, [])
            continue
        match = _META_RE.match(raw)
        if match and not current:
            metadata[match.group("key").casefold()] = _clean_value(match.group("value"))
            continue
        if current:
            sections[current].append(raw)
    normalized_sections = {
        key: "\n".join(lines).strip()
        for key, lines in sections.items()
    }
    return title, normalized_sections, metadata


def parse_report(text: str) -> dict[str, Any]:
    """Parse both existing defect templates without performing I/O."""
    frontmatter, body, warnings = _frontmatter(text)
    title, sections, metadata = _sections(body)

    lowered_frontmatter = {str(k).replace("_", " ").casefold(): v for k, v in frontmatter.items()}
    combined: dict[str, Any] = {**lowered_frontmatter, **metadata}
    raw_severity = _clean_value(combined.get("severity") or sections.get("severity"))
    severity_match = re.match(r"^(P[0-3])(?:[-\s].*)?$", raw_severity, re.I)
    severity = severity_match.group(1).upper() if severity_match else None
    if raw_severity and not severity:
        warnings.append(f"Unknown severity: {raw_severity}")

    related_raw = combined.get("related features")
    if related_raw is None:
        related_raw = combined.get("related feature")
    related_features = _split_values(related_raw, feature_names=True)
    related_features_explicit = "related features" in combined or "related feature" in combined

    def section(*names: str) -> str:
        for name in names:
            value = _clean_value(sections.get(name.casefold(), ""))
            if value:
                return value
        return ""

    # Legacy reports may store these fields inline instead of under headings.
    inline: dict[str, str] = {}
    for raw in body.splitlines():
        match = re.match(
            r"^\s*(?:\*\*)?(Observed(?: Behavior)?|Expected(?: Behavior)?|"
            r"Repro(?:duction Steps)?)(?:\*\*\s*:|\s*:\s*\*\*|\s*:)\s*(.+?)\s*$",
            raw,
            re.I,
        )
        if match:
            inline[match.group(1).casefold()] = _clean_value(match.group(2))

    observed = section("observed behavior", "observed") or inline.get("observed behavior", "") or inline.get("observed", "")
    expected = section("expected behavior", "expected") or inline.get("expected behavior", "") or inline.get("expected", "")
    reproduction = section("reproduction steps", "repro") or inline.get("reproduction steps", "") or inline.get("repro", "")
    context = section("additional context", "additional context (optional)")

    return {
        "title": title,
        "severity": severity,
        "severity_label": raw_severity or None,
        "related_features": related_features,
        "related_features_explicit": related_features_explicit,
        "source": _clean_value(combined.get("source")) or "unknown",
        "source_feature": _clean_value(combined.get("source feature")) or None,
        "observed": observed,
        "expected": expected,
        "reproduction": reproduction,
        "reproducibility": _clean_value(combined.get("reproducibility")),
        "last_known_working": _clean_value(combined.get("last known working")),
        "environment": section("environment"),
        "error_output": section("error output"),
        "context": context,
        "related_files": _split_values(combined.get("related files") or combined.get("affected files")),
        "tags": _split_values(combined.get("tags")),
        "intake_request_id": _clean_value(combined.get("intake request")) or None,
        "warnings": warnings,
    }


def validate_report(report: dict[str, Any], strict: bool = False) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if report.get("severity") not in VALID_SEVERITIES:
        errors.append({"field": "severity", "message": "Choose P0, P1, P2, or P3"})
    for field in ("observed", "expected", "reproduction"):
        value = _clean_value(report.get(field))
        if not value:
            errors.append({"field": field, "message": f"{field.replace('_', ' ').title()} is required"})
        elif len(value) > 16_384:
            errors.append({"field": field, "message": "Must be 16 KiB or smaller"})
    if strict:
        features = report.get("related_features") or []
        if not features:
            errors.append({"field": "relatedFeatures", "message": "At least one affected feature is required"})
        elif len(features) > 20 or any(not _FEATURE_RE.fullmatch(str(v)) for v in features):
            errors.append({"field": "relatedFeatures", "message": "Use 1-20 known lowercase feature names"})
    return errors


def initial_defect_state(source_spec: str, reported_severity: str | None, now: str) -> dict[str, Any]:
    return {
        "status": "filed",
        "severity": None,
        "reported_severity": reported_severity,
        "defect_type": None,
        "complexity": None,
        "branch": None,
        "created_at": now,
        "updated_at": now,
        "source_spec": source_spec,
    }


def render_report(draft: dict[str, Any], provenance: dict[str, Any]) -> str:
    related = ", ".join(draft.get("related_features") or [])
    primary_feature = provenance["related_spec_feature"]
    primary_link = provenance["related_spec_link"]
    primary_reference = f"[{primary_feature}]({primary_link})" if primary_link else primary_feature
    severity_label = {"P0": "critical", "P1": "high", "P2": "moderate", "P3": "low"}[draft["severity"]]
    evidence = provenance.get("evidence_paths") or []
    evidence_lines = "\n".join(f"- `{path}`" for path in evidence) or "- None"
    return (
        f"# Defect: {draft['title'].strip()}\n\n"
        f"**Severity:** {draft['severity']}-{severity_label}\n"
        f"**Related Feature:** {primary_reference}\n"
        f"Related Features: {related}\n"
        f"**Reproducibility:** {draft['reproducibility'].strip()}\n"
        f"**Last Known Working:** {draft['last_known_working'].strip()}\n"
        "Source: define\n"
        f"Source Feature: {provenance['source_feature']}\n"
        f"Intake Request: {provenance['request_id']}\n\n"
        f"## Observed Behavior\n\n{draft['observed'].strip()}\n\n"
        f"## Expected Behavior\n\n{draft['expected'].strip()}\n\n"
        f"## Reproduction Steps\n\n{draft['reproduction'].strip()}\n\n"
        f"## Environment\n\n{draft['environment'].strip()}\n\n"
        f"## Error Output\n\n{draft['error_output'].strip()}\n\n"
        f"## Additional Context\n\n{draft.get('context', '').strip()}\n\n"
        "## Provenance\n\n"
        f"Source finding: `{provenance['finding_id']}`\n\n"
        f"Evidence:\n{evidence_lines}\n\n"
        f"Filing decision: `{provenance['request_id']}`\n\n"
        f"Filed by: {provenance['actor_name']} <{provenance['actor_email']}> "
        f"at {provenance['filed_at']}\n"
    )


def discover_feature_names(root: Path, feature_dir: Path | None = None) -> list[str]:
    names: set[str] = set()
    if feature_dir and feature_dir.is_dir():
        names.update(path.name for path in feature_dir.iterdir() if path.is_dir())
    product_dir = root / "specs" / "product"
    if product_dir.is_dir():
        names.update(path.stem for path in product_dir.glob("*.md") if path.name != "overview.md")
    return sorted(name for name in names if _FEATURE_RE.fullmatch(name))


def _read_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            return None, "JSON root must be an object"
        return value, None
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, str(exc)


def _contained(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def intake_readiness(defects_dir: Path, slug: str, state: dict[str, Any] | None) -> tuple[bool, list[str]]:
    intake = (state or {}).get("intake")
    if not isinstance(intake, dict):
        return True, []  # legacy defect
    request_id = intake.get("request_id")
    if not isinstance(request_id, str) or not request_id:
        return False, ["Repair required: intake request ID is missing"]
    manifest_path = defects_dir / ".intake" / request_id / "manifest.json"
    if not _contained(defects_dir, manifest_path):
        return False, ["Repair required: intake manifest path escapes the defects root"]
    manifest, error = _read_json(manifest_path)
    if error or not manifest:
        return False, ["Repair required: intake manifest is missing or malformed"]
    if manifest.get("phase") != "committed" or manifest.get("slug") != slug:
        return False, ["Repair required: filing transaction is incomplete"]
    return True, []


def discover_defects(root: Path, defects_dir: Path) -> list[dict[str, Any]]:
    specs_dir = root / "specs" / "defects"
    slugs: set[str] = set()
    if specs_dir.is_dir():
        slugs.update(path.stem for path in specs_dir.glob("*.md"))
    if defects_dir.is_dir():
        slugs.update(path.parent.name for path in defects_dir.glob("*/state.json"))

    rows: list[dict[str, Any]] = []
    for slug in sorted(slugs):
        spec_path = specs_dir / f"{slug}.md"
        state_path = defects_dir / slug / "state.json"
        warnings: list[str] = []
        report: dict[str, Any] = {}
        state: dict[str, Any] | None = None
        state_error: str | None = None
        spec_safe = spec_path.is_file() and _contained(root, spec_path)
        state_safe = state_path.is_file() and _contained(defects_dir, state_path)
        if spec_path.is_file() and not spec_safe:
            warnings.append("Canonical report path escapes the project root")
        elif spec_safe:
            try:
                report = parse_report(spec_path.read_text(encoding="utf-8"))
                warnings.extend(report.get("warnings") or [])
            except (OSError, UnicodeError) as exc:
                warnings.append(f"Canonical report is unreadable: {exc}")
        else:
            warnings.append("Canonical report is missing")
        if state_path.is_file() and not state_safe:
            state_error = "path escapes the defects root"
            warnings.append("State path escapes the defects root")
        elif state_safe:
            state, state_error = _read_json(state_path)
            if state_error:
                warnings.append(f"State is malformed: {state_error}")
        else:
            warnings.append("Defect state is missing; record is untriaged")

        ready, readiness_warnings = intake_readiness(defects_dir, slug, state)
        warnings.extend(readiness_warnings)
        state = state or {}
        triaged_severity = state.get("severity")
        reported_severity = state.get("reported_severity")
        severity = next(
            (value for value in (triaged_severity, reported_severity, report.get("severity")) if value in VALID_SEVERITIES),
            "unknown",
        )
        legacy_severity = next(
            (value.casefold() for value in (triaged_severity, reported_severity, report.get("severity_label"))
             if isinstance(value, str) and value.casefold() in {"critical", "major", "minor"}),
            None,
        )
        report_features = report.get("related_features") or []
        state_features = _split_values(state.get("related_features"), feature_names=True)
        related_features = list(
            report_features if report.get("related_features_explicit") else state_features
        )
        if report_features and state_features and list(report_features) != list(state_features):
            warnings.append("Related Features differ between canonical report and state")
        report_severity = report.get("severity")
        if report_severity and reported_severity and report_severity != reported_severity:
            warnings.append("Reported severity differs between canonical report and state")

        status = "unknown" if state_error else (state.get("status") if state_safe and state else "untriaged")
        if not isinstance(status, str) or not status:
            status = "unknown"
        report_source = report.get("source")
        source = (report_source if report_source != "unknown" else None) or state.get("source") or "unknown"
        source_feature = report.get("source_feature") or state.get("source_feature")
        intake = state.get("intake") if isinstance(state.get("intake"), dict) else {}
        title = report.get("title") or state.get("name") or slug.replace("-", " ").title()
        observed = report.get("observed") or state.get("description") or ""
        description = observed.split("\n\n", 1)[0].strip()
        filed_at = state.get("filed_at") or state.get("created_at")
        updated_at = state.get("updated_at") or filed_at
        rows.append({
            "slug": slug,
            "name": slug,
            "title": title,
            "severity": severity,
            "legacy_severity": legacy_severity,
            "status": status,
            "description": description,
            "impact": state.get("impact"),
            "filed_at": filed_at,
            "updated_at": updated_at,
            "related_features": related_features,
            "source": source,
            "source_feature": source_feature,
            "source_finding_id": intake.get("finding_id"),
            "canonical_path": str(spec_path.relative_to(root)) if spec_safe else None,
            "related_files": report.get("related_files") or _split_values(state.get("related_files")),
            "tags": report.get("tags") or _split_values(state.get("tags")),
            "filed": bool(spec_safe and state_safe and ready),
            "warnings": warnings,
        })
    return rows


def lifecycle(status: str) -> str:
    return "closed" if status in CLOSED_STATUSES else "active"


def matches(row: dict[str, Any], filters: dict[str, Any]) -> bool:
    affected = set(row["related_features"]) or {"_unassigned"}
    if filters.get("features") and not affected.intersection(filters["features"]):
        return False
    for field in ("severity", "status", "source"):
        selected = filters.get(field) or []
        if selected and row[field] not in selected:
            return False
    selected_lifecycle = filters.get("lifecycle") or []
    if selected_lifecycle and lifecycle(row["status"]) not in selected_lifecycle:
        return False
    needle = str(filters.get("search") or "").strip().casefold()
    return not needle or needle in f"{row['title']} {row['slug']}".casefold()


def _timestamp_key(value: Any) -> float:
    if not isinstance(value, str) or not value:
        return float("-inf")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return float("-inf")


def report_revision(rows: Iterable[dict[str, Any]]) -> str:
    payload = [
        {key: value for key, value in row.items() if key != "legacy_severity"}
        for row in rows
    ]
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def build_report_view(rows: list[dict[str, Any]], filters: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized = {
        "features": list((filters or {}).get("features") or []),
        "severity": list((filters or {}).get("severity") or []),
        "status": list((filters or {}).get("status") or []),
        "source": list((filters or {}).get("source") or []),
        "lifecycle": list((filters or {}).get("lifecycle") or []),
        "search": str((filters or {}).get("search") or ""),
    }
    selected = [row for row in rows if matches(row, normalized)]
    selected.sort(key=lambda row: (
        _SEVERITY_ORDER.get(row["severity"], 4),
        -_timestamp_key(row.get("updated_at")),
        row["slug"],
    ))
    groups: list[dict[str, Any]] = []
    if not normalized["features"]:
        grouped: dict[str, list[str]] = {}
        for row in selected:
            group = row["related_features"][0] if row["related_features"] else "_unassigned"
            grouped.setdefault(group, []).append(row["slug"])
        groups = [
            {"feature": name, "slugs": slugs}
            for name, slugs in sorted(grouped.items(), key=lambda item: (item[0] == "_unassigned", item[0]))
        ]
    features = {feature for row in selected for feature in row["related_features"]}
    totals = {
        "total": len(selected),
        "active": sum(lifecycle(row["status"]) == "active" for row in selected),
        "closed": sum(lifecycle(row["status"]) == "closed" for row in selected),
        "p0_p1": sum(row["severity"] in {"P0", "P1"} for row in selected),
        "affected_features": len(features),
        "unassigned": sum(not row["related_features"] for row in selected),
    }
    feature_facets = sorted({feature for row in rows for feature in row["related_features"]})
    if any(not row["related_features"] for row in rows):
        feature_facets.append("_unassigned")
    facets = {
        "features": feature_facets,
        "severity": sorted({row["severity"] for row in rows}, key=lambda value: _SEVERITY_ORDER.get(value, 4)),
        "status": sorted({row["status"] for row in rows}),
        "source": sorted({row["source"] for row in rows}),
    }
    return {
        "schema_version": 1,
        "revision": report_revision(rows),
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "filters": normalized,
        "rows": selected,
        "groups": groups,
        "totals": totals,
        "facets": facets,
        "warnings": sorted({warning for row in selected for warning in row["warnings"]}),
    }


def export_report(view: dict[str, Any], format: str) -> str:
    if format == "json":
        return json.dumps(view, indent=2, sort_keys=True) + "\n"
    if format != "markdown":
        raise ValueError("format must be json or markdown")
    filters = view["filters"]
    active = [f"{key}={','.join(value) if isinstance(value, list) else value}" for key, value in filters.items() if value]
    lines = [
        "# Defect report",
        "",
        f"Generated: {view['generated_at']}",
        f"Filters: {', '.join(active) if active else 'none'}",
        f"Total: {view['totals']['total']} (Active {view['totals']['active']}, Closed {view['totals']['closed']})",
        "",
        "| Severity | Status | Defect | Related Features | Source |",
        "|---|---|---|---|---|",
    ]
    for row in view["rows"]:
        cells = [
            row["severity"], row["status"], row["title"],
            ", ".join(row["related_features"]) or "Unassigned", row["source"],
        ]
        escaped = [str(value).replace("|", "\\|").replace("\n", " ") for value in cells]
        lines.append("| " + " | ".join(escaped) + " |")
    return "\n".join(lines) + "\n"
