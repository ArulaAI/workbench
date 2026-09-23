"""Versioned ingestion contract for clean-context review evidence."""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from pathlib import PurePosixPath
from typing import Any


CLEAN_REVIEW_SCHEMA_VERSION = 1
_SEVERITIES = frozenset({"critical", "major", "minor", "nit"})
_ROOT_FIELDS = frozenset({"schema_version", "issues"})
_ISSUE_FIELDS = frozenset({
    "message",
    "file",
    "line",
    "severity",
    "observed",
    "expected",
    "reproduction",
})
_OPTIONAL_TEXT_FIELDS = ("file", "observed", "expected", "reproduction")


def _json_candidate(text: str) -> tuple[str, str]:
    stripped = text.lstrip("\ufeff").strip()
    fenced = re.fullmatch(
        r"```(?:json)?\s*(.*?)\s*```",
        stripped,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return stripped, fenced.group(1) if fenced else stripped


def _validate_relative_file(value: str, index: int) -> None:
    path = PurePosixPath(value)
    if (
        not value
        or value.startswith(("/", "~"))
        or "\\" in value
        or path.is_absolute()
        or ".." in path.parts
    ):
        raise ValueError(f"clean review issue {index} file must be project-relative")


def _validate_current(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("clean review root must be a JSON object")
    unknown = set(payload) - _ROOT_FIELDS
    if unknown:
        raise ValueError(f"clean review contains unsupported field: {sorted(unknown)[0]}")
    if (
        type(payload.get("schema_version")) is not int
        or payload["schema_version"] != CLEAN_REVIEW_SCHEMA_VERSION
    ):
        raise ValueError(f"clean review schema_version must be {CLEAN_REVIEW_SCHEMA_VERSION}")
    issues = payload.get("issues")
    if not isinstance(issues, list):
        raise ValueError("clean review issues must be an array")

    normalized: list[dict[str, Any]] = []
    for index, issue in enumerate(issues):
        if not isinstance(issue, dict):
            raise ValueError(f"clean review issue {index} must be an object")
        unknown = set(issue) - _ISSUE_FIELDS
        if unknown:
            raise ValueError(
                f"clean review issue {index} contains unsupported field: {sorted(unknown)[0]}"
            )

        message = issue.get("message")
        if not isinstance(message, str) or not message.strip():
            raise ValueError(f"clean review issue {index} message must be a non-empty string")
        severity = issue.get("severity")
        if not isinstance(severity, str) or severity not in _SEVERITIES:
            allowed = ", ".join(sorted(_SEVERITIES))
            raise ValueError(f"clean review issue {index} severity must be one of: {allowed}")

        item: dict[str, Any] = {
            "message": message.strip(),
            "severity": severity,
        }
        for field in _OPTIONAL_TEXT_FIELDS:
            if field not in issue:
                continue
            value = issue[field]
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"clean review issue {index} {field} must be a non-empty string")
            item[field] = value.strip()
        if "file" in item:
            _validate_relative_file(item["file"], index)

        line = issue.get("line")
        if line is not None:
            if type(line) is not int or line <= 0:
                raise ValueError(f"clean review issue {index} line must be a positive integer")
            if "file" not in item:
                raise ValueError(f"clean review issue {index} line requires file")
            item["line"] = line
        normalized.append(item)

    return {"schema_version": CLEAN_REVIEW_SCHEMA_VERSION, "issues": normalized}


def parse_clean_review_payload(text: str, *, legacy: bool = False) -> dict[str, Any]:
    """Parse clean-review output at the current or legacy compatibility boundary."""
    stripped, candidate = _json_candidate(text)
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as exc:
        if legacy:
            return {"issues": [{"message": stripped, "severity": "unknown"}]}
        raise ValueError("clean review must be valid JSON matching schema version 1") from exc
    if legacy:
        if not isinstance(payload, dict):
            raise ValueError("legacy clean review root must be an object")
        return payload
    return _validate_current(payload)


def parse_report_findings_events(text: str, *, final_text: str | None = None) -> dict[str, Any] | None:
    """Use confirmed tool findings, recovering only severities omitted by the tool."""
    calls: dict[str, list[dict[str, Any]]] = {}
    confirmed: list[dict[str, Any]] | None = None
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        message = event.get("message")
        blocks = message.get("content", []) if isinstance(message, dict) else []
        if not isinstance(blocks, list):
            continue
        if event.get("type") == "assistant":
            for block in blocks:
                if not isinstance(block, dict) or block.get("type") != "tool_use" or block.get("name") != "ReportFindings":
                    continue
                tool_id = block.get("id")
                value = block.get("input")
                findings = value.get("findings") if isinstance(value, dict) else None
                if isinstance(tool_id, str) and isinstance(findings, list):
                    calls[tool_id] = findings
        elif event.get("type") == "user":
            result = event.get("tool_use_result")
            if not isinstance(result, dict) or not isinstance(result.get("findings"), list):
                continue
            count = result.get("count")
            returned = result["findings"]
            for block in blocks:
                if not isinstance(block, dict) or block.get("type") != "tool_result" or block.get("is_error"):
                    continue
                submitted = calls.get(block.get("tool_use_id"))
                if submitted is None or type(count) is not int or count == 0 or count != len(submitted) or count != len(returned):
                    continue
                if any(
                    not isinstance(original, dict) or not isinstance(accepted, dict)
                    or original.get("file") != accepted.get("file")
                    or original.get("line") != accepted.get("line")
                    or original.get("summary") != accepted.get("summary")
                    for original, accepted in zip(submitted, returned)
                ):
                    continue
                confirmed = submitted
    if confirmed is None:
        return None
    issues = []
    for finding in confirmed:
        issue = {
            "message": finding.get("summary") or finding.get("short_summary"),
            "severity": finding.get("severity"),
        }
        for source, target in (("file", "file"), ("line", "line"), ("failure_scenario", "reproduction")):
            if finding.get(source) is not None:
                issue[target] = finding[source]
        issues.append(issue)
    if all(issue.get("severity") in _SEVERITIES for issue in issues):
        return _validate_current({"schema_version": CLEAN_REVIEW_SCHEMA_VERSION, "issues": issues})
    if final_text is None or any(issue.get("severity") not in _SEVERITIES | {None} for issue in issues):
        return _validate_current({"schema_version": CLEAN_REVIEW_SCHEMA_VERSION, "issues": issues})
    final_issues = parse_clean_review_payload(final_text)["issues"]
    if len(final_issues) != len(issues):
        raise ValueError("clean review final JSON does not match confirmed ReportFindings")
    for tool_issue, final_issue in zip(issues, final_issues):
        tool_words = " ".join(re.findall(r"[a-z0-9]+", str(tool_issue["message"]).casefold()))
        final_words = " ".join(re.findall(r"[a-z0-9]+", final_issue["message"].casefold()))
        if (
            tool_issue.get("file") != final_issue.get("file")
            or tool_issue.get("line") != final_issue.get("line")
            or SequenceMatcher(None, tool_words, final_words).ratio() < 0.8
        ):
            raise ValueError("clean review final JSON does not match confirmed ReportFindings")
        if tool_issue["severity"] is None:
            tool_issue["severity"] = final_issue["severity"]
    return _validate_current({"schema_version": CLEAN_REVIEW_SCHEMA_VERSION, "issues": issues})
