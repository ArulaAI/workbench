"""Versioned ingestion contract for clean-context review evidence."""

from __future__ import annotations

import json
import re
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
    "scenario_id",
    "testable",
})
_OPTIONAL_TEXT_FIELDS = ("file", "observed", "expected", "reproduction")
# Same shape as SCENARIO_ID_RE in lib/test_spec.py. Duplicated rather than
# imported so the review contract keeps no dependency on the eval engine:
# a reviewer must be able to declare a scenario without eval being installed.
# Membership in the catalog is not checked here — that is the adapter's job,
# because only the adapter knows which test spec a run is being judged against.
_SCENARIO_ID_RE = re.compile(r"[A-Z][A-Z0-9_-]*-\d{2,}")


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

        scenario_id = issue.get("scenario_id")
        if scenario_id is not None:
            if not isinstance(scenario_id, str) or not _SCENARIO_ID_RE.fullmatch(scenario_id):
                raise ValueError(
                    f"clean review issue {index} scenario_id must be a catalog scenario ID"
                )
            item["scenario_id"] = scenario_id
        testable = issue.get("testable")
        if testable is not None:
            # `type(...) is not bool` rather than isinstance: 0 and 1 are ints
            # that would otherwise pass as booleans and silently decide whether
            # a finding becomes an executable test case.
            if type(testable) is not bool:
                raise ValueError(f"clean review issue {index} testable must be a boolean")
            item["testable"] = testable
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


def _same_location(tool_issue: dict[str, Any], final_issue: dict[str, Any]) -> bool:
    """Whether a tool finding and a final-JSON issue sit at the same location.

    Exact equality on both fields, never proximity or resemblance. `file` and
    `line` are the only values ReportFindings and the final JSON are both
    required to carry verbatim, so they are the sole structural key. Wording
    is deliberately not consulted: the tool's `summary` is a compressed label
    and the final `message` is a full sentence, so two faithful descriptions
    of one finding routinely share almost no words.
    """
    return (
        tool_issue.get("file") == final_issue.get("file")
        and tool_issue.get("line") == final_issue.get("line")
    )


def _aligned(issues: list[dict[str, Any]], final_text: str) -> list[tuple[dict, dict]]:
    """Pair tool findings with final-JSON issues, or nothing if they disagree.

    The reviewer contract requires the same findings in the same order through
    both channels, so pairing is positional and equal counts are required: an
    unequal count means the two channels describe different finding sets, and
    position no longer identifies anything.

    Within a matched count, each position is judged on its own. One finding
    whose location disagrees loses only its own recovery; the others keep
    theirs. An earlier all-or-nothing rule discarded a whole review over a
    single disagreement, which cost two correctly-aligned scenario IDs in a
    real run because the reviewer sent a `file` through the tool and omitted
    it from the final JSON. Dropping only the disagreeing pair is equally safe
    against misattribution, since the fields still come from the very issue
    that sits at the same position and the same location.

    Deliberately silent: the caller uses this to recover fields the tool
    cannot carry, and a review whose severities were all supplied must not
    acquire a new way to fail just because its final JSON drifted.
    """
    try:
        final_issues = parse_clean_review_payload(final_text)["issues"]
    except ValueError:
        return []
    if len(final_issues) != len(issues):
        return []
    return [(tool, final) for tool, final in zip(issues, final_issues)
            if _same_location(tool, final)]


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
    # ReportFindings models only its own fields, so scenario_id and testable
    # survive nowhere but the final JSON. Recover them from the matching issue
    # rather than dropping a scenario the reviewer actually declared.
    # Severity travels the same way when the tool omits it, and is recovered on
    # the same terms: same position, same location, no resemblance test. The
    # rule used to be all-or-nothing and fuzzy, and it raised on a miss, which
    # is how a whole review was lost to `clean review final JSON does not match
    # confirmed ReportFindings` while five of six findings agreed exactly.
    if final_text is not None:
        for tool_issue, final_issue in _aligned(issues, final_text):
            for field in ("scenario_id", "testable"):
                if field in final_issue:
                    tool_issue[field] = final_issue[field]
            if tool_issue.get("severity") is None:
                tool_issue["severity"] = final_issue["severity"]
    if any(issue.get("severity") not in _SEVERITIES for issue in issues):
        # Severity is required, so an unrecovered one cannot be published from
        # the tool transcript. Decline the transcript rather than raise: the
        # caller then reads the reviewer's own final JSON, which carries every
        # severity by contract. A partial recovery must not cost the review.
        return None
    return _validate_current({"schema_version": CLEAN_REVIEW_SCHEMA_VERSION, "issues": issues})
