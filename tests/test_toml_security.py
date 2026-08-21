#!/usr/bin/env python3
"""Unit tests for [security] section handling in lib/toml.py emit()."""

import io
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from lib.toml import emit

passed = 0
failed = 0


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name} — {detail}")


def capture_emit(data: dict) -> str:
    """Run emit() and return stdout as a string."""
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        emit(data)
        return sys.stdout.getvalue()
    finally:
        sys.stdout = old_stdout


# ══════════════════════════════════════════════════════════════
# Full [security] section
# ══════════════════════════════════════════════════════════════

print("\n=== Full [security] section ===")

data_full = {
    "security": {
        "sast_cmd": "semgrep --config auto --json",
        "sca_cmd": "npm audit --json",
        "severity_threshold": "medium",
        "secrets_patterns": ["AWS", "GITHUB_TOKEN", "GENERIC_SECRET"],
        "secrets_exclude": [".env*", "*.example", "tests/fixtures/**"],
    }
}
out = capture_emit(data_full)

check(
    "sast_cmd emitted correctly",
    "TOML_SECURITY_SAST_CMD='semgrep --config auto --json'" in out,
    repr(out),
)
check(
    "sca_cmd emitted correctly",
    "TOML_SECURITY_SCA_CMD='npm audit --json'" in out,
    repr(out),
)
check(
    "severity_threshold emitted correctly",
    "TOML_SECURITY_SEVERITY_THRESHOLD='medium'" in out,
    repr(out),
)
check(
    "secrets_patterns emitted as space-separated string",
    "TOML_SECURITY_SECRETS_PATTERNS='AWS GITHUB_TOKEN GENERIC_SECRET'" in out,
    repr(out),
)
check(
    "secrets_exclude emitted as space-separated string",
    "TOML_SECURITY_SECRETS_EXCLUDE='.env* *.example tests/fixtures/**'" in out,
    repr(out),
)

# ══════════════════════════════════════════════════════════════
# Missing [security] section
# ══════════════════════════════════════════════════════════════

print("\n=== Missing [security] section ===")

out_no_security = capture_emit({"agent": {"provider": "claude-code"}})

check(
    "no TOML_SECURITY_* vars when section absent",
    "TOML_SECURITY_" not in out_no_security,
    repr(out_no_security),
)
check(
    "other sections still emit without security present",
    "TOML_AGENT_PROVIDER='claude-code'" in out_no_security,
    repr(out_no_security),
)

# ══════════════════════════════════════════════════════════════
# Partial section — only sast_cmd
# ══════════════════════════════════════════════════════════════

print("\n=== Partial [security] section ===")

out_partial = capture_emit({"security": {"sast_cmd": "semgrep --config auto --json"}})

check(
    "sast_cmd present when only that key set",
    "TOML_SECURITY_SAST_CMD='semgrep --config auto --json'" in out_partial,
    repr(out_partial),
)
check(
    "sca_cmd absent when not set",
    "TOML_SECURITY_SCA_CMD" not in out_partial,
    repr(out_partial),
)
check(
    "secrets_patterns absent when not set",
    "TOML_SECURITY_SECRETS_PATTERNS" not in out_partial,
    repr(out_partial),
)

# ══════════════════════════════════════════════════════════════
# Array fields serialized as space-separated strings
# ══════════════════════════════════════════════════════════════

print("\n=== Array field serialization ===")

out_arrays = capture_emit({
    "security": {
        "secrets_patterns": ["AWS", "GITHUB_TOKEN", "GENERIC_SECRET"],
        "secrets_exclude": [".env*", "*.example", "tests/fixtures/**"],
    }
})

check(
    "secrets_patterns space-separated from list",
    "TOML_SECURITY_SECRETS_PATTERNS='AWS GITHUB_TOKEN GENERIC_SECRET'" in out_arrays,
    repr(out_arrays),
)
check(
    "secrets_exclude space-separated from list",
    "TOML_SECURITY_SECRETS_EXCLUDE='.env* *.example tests/fixtures/**'" in out_arrays,
    repr(out_arrays),
)

# ══════════════════════════════════════════════════════════════
# Empty arrays
# ══════════════════════════════════════════════════════════════

print("\n=== Empty arrays ===")

out_empty_arrays = capture_emit({
    "security": {
        "secrets_patterns": [],
        "secrets_exclude": [],
    }
})

check(
    "secrets_patterns emits empty string for empty list",
    "TOML_SECURITY_SECRETS_PATTERNS=''" in out_empty_arrays,
    repr(out_empty_arrays),
)
check(
    "secrets_exclude emits empty string for empty list",
    "TOML_SECURITY_SECRETS_EXCLUDE=''" in out_empty_arrays,
    repr(out_empty_arrays),
)

# ══════════════════════════════════════════════════════════════
# String values for array fields (backward compat)
# ══════════════════════════════════════════════════════════════

print("\n=== String values for array fields ===")

out_string_arrays = capture_emit({
    "security": {
        "secrets_patterns": "AWS GITHUB_TOKEN",
        "secrets_exclude": ".env* *.example",
    }
})

check(
    "secrets_patterns string passed through as-is",
    "TOML_SECURITY_SECRETS_PATTERNS='AWS GITHUB_TOKEN'" in out_string_arrays,
    repr(out_string_arrays),
)
check(
    "secrets_exclude string passed through as-is",
    "TOML_SECURITY_SECRETS_EXCLUDE='.env* *.example'" in out_string_arrays,
    repr(out_string_arrays),
)

# ══════════════════════════════════════════════════════════════
# Shell-unsafe characters in config values
# ══════════════════════════════════════════════════════════════

print("\n=== Shell escape ===")

out_unsafe = capture_emit({
    "security": {
        "sast_cmd": "semgrep --config='auto'",
        "severity_threshold": "it's medium",
    }
})

check(
    "single quotes in sast_cmd are escaped",
    "TOML_SECURITY_SAST_CMD='semgrep --config='\\''auto'\\'''" in out_unsafe,
    repr(out_unsafe),
)
check(
    "single quote in severity_threshold is escaped",
    "TOML_SECURITY_SEVERITY_THRESHOLD='it'\\''s medium'" in out_unsafe,
    repr(out_unsafe),
)

# ══════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════

print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed")
if failed:
    sys.exit(1)
