"""Read existing task criteria without changing their persisted representation."""
from __future__ import annotations

import json
import re
from typing import Any

from lib.test_spec import SCENARIO_ID_RE

_BULLET = re.compile(r"^\s*[-*]\s+(.*\S)\s*$")
_VERIFY = re.compile(r"^\s*verify_by:\s*([A-Za-z_]+)\s*$")
_TAG = re.compile(r"\[([A-Z][A-Z0-9_-]*-\d{2,})\]")


def normalize_criteria(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    # task_create stores its argument as a string, including structured
    # architect output serialized by jq. Do not mistake that JSON for prose.
    try:
        decoded = json.loads(value)
        if isinstance(decoded, list):
            return decoded
    except ValueError:
        pass
    items = []
    for line in value.splitlines():
        bullet, verify = _BULLET.match(line), _VERIFY.match(line)
        if bullet:
            items.append({"criterion": bullet[1], "verify_by": "manual", "scenario_ids": []})
        elif verify and items:
            items[-1]["verify_by"] = verify[1].lower()
        elif line.strip() and items:
            items[-1]["criterion"] += " " + line.strip()
    return items or value


def criteria_items(task: dict) -> list[dict]:
    value = normalize_criteria(task.get("acceptance_criteria", []))
    if isinstance(value, str):
        value = [value]
    return [item if isinstance(item, dict) else {"criterion": str(item), "verify_by": "manual"}
            for item in value]


def scenario_tags(text: str) -> set[str]:
    return {match for match in _TAG.findall(text) if SCENARIO_ID_RE.fullmatch(match)}


def criterion_ids(criterion: dict) -> set[str]:
    return scenario_tags(str(criterion.get("criterion", ""))) | set(criterion.get("scenario_ids", []))


def task_scenarios(task: dict) -> set[str]:
    return set(task.get("required_test_cases", [])) | set().union(
        *(criterion_ids(criterion) for criterion in criteria_items(task)))


def has_tagged_criteria(tasks: list[dict]) -> bool:
    return any(scenario_tags(str(c.get("criterion", ""))) for t in tasks for c in criteria_items(t))
