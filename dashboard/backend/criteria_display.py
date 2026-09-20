"""Render task criteria for existing text-based dashboard API fields."""
from __future__ import annotations


def criteria_text(value: object) -> str | None:
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, list):
        return '\n'.join(
            f"- {item.get('criterion', '')}\n  verify_by: {item.get('verify_by', 'manual')}"
            if isinstance(item, dict) else f'- {item}'
            for item in value
        )
    return str(value)
