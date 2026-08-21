""".env Key Extraction.

Parses .env files to extract variable key names while stripping values.
Values are never included in agent context (security).

Usage:
    from lib.context.env_extract import extract_env_keys
    keys = extract_env_keys(content)
    # ["DATABASE_URL", "API_KEY", "DEBUG"]

Tech spec: tech-spec-context-constructor.md → Layer 1 § What tree-sitter Does NOT Handle
"""

from __future__ import annotations


def extract_env_keys(content: str) -> list[str]:
    """Extract variable key names from .env file content.

    Strips values, skips blanks and comments.

    Args:
        content: raw .env file content

    Returns:
        List of key names (e.g. ["DATABASE_URL", "API_KEY"]).
    """
    keys = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key = line.split("=", 1)[0].strip()
            if key:
                keys.append(key)
    return keys
