#!/usr/bin/env python3
"""Unit tests for [diagnose] section handling in lib/toml.py emit()."""

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
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        emit(data)
        return sys.stdout.getvalue()
    finally:
        sys.stdout = old_stdout


# ══════════════════════════════════════════════════════════════
# [diagnose] classes_file
# ══════════════════════════════════════════════════════════════

out = capture_emit({"diagnose": {"classes_file": ".speed/classes.yaml"}})
check(
    "classes_file is emitted as TOML_DIAGNOSE_CLASSES_FILE",
    "TOML_DIAGNOSE_CLASSES_FILE='.speed/classes.yaml'" in out,
    out,
)

out = capture_emit({"diagnose": {"spec_file": "specs/product/payments.md"}})
check(
    "spec_file is emitted as TOML_DIAGNOSE_SPEC_FILE",
    "TOML_DIAGNOSE_SPEC_FILE='specs/product/payments.md'" in out,
    out,
)

out = capture_emit({})
check(
    "no [diagnose] section emits nothing",
    "TOML_DIAGNOSE" not in out,
    out,
)

out = capture_emit({"diagnose": {}})
check(
    "empty [diagnose] section emits nothing",
    "TOML_DIAGNOSE" not in out,
    out,
)

out = capture_emit({"diagnose": {"classes_file": "it's here.yaml"}})
check(
    "single quote in classes_file is escaped",
    "TOML_DIAGNOSE_CLASSES_FILE='it'\\''s here.yaml'" in out,
    repr(out),
)

# ══════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════

print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed")
if failed:
    sys.exit(1)
