#!/usr/bin/env python3
"""Tests for lib/learn/conventions.py — data models and atomic write utility."""

import json
import os
import sys
import tempfile
import threading
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from lib.learn.conventions import (
    ConventionEntry,
    ConventionResult,
    RawPattern,
    _atomic_write,
)

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


def make_entry(source="config", confidence="established"):
    return ConventionEntry(
        id="conv-test",
        convention="Use snake_case for function names",
        scope=["lib/"],
        confidence=confidence,
        canonical_example="lib/foo.py",
        exceptions=None,
        evolution=None,
        tags=["naming"],
        evidence={"files_checked": 10, "adherence": 0.95},
        source=source,
    )


# ══════════════════════════════════════════════════════════════
# RawPattern dataclass
# ══════════════════════════════════════════════════════════════

print("\n=== RawPattern ===")

rp = RawPattern(
    type="naming_snake",
    files=["lib/foo.py", "lib/bar.py"],
    scope=["lib/"],
    adherence=0.92,
    evidence="10 of 11 functions use snake_case",
)
check("type field", rp.type == "naming_snake")
check("files field", rp.files == ["lib/foo.py", "lib/bar.py"])
check("scope field", rp.scope == ["lib/"])
check("adherence field", rp.adherence == 0.92)
check("evidence field", rp.evidence == "10 of 11 functions use snake_case")
check("observation_support default", rp.observation_support == 0)
check("recent_trend default", rp.recent_trend == "stable")

rp2 = RawPattern(
    type="import_relative",
    files=["a.py"],
    scope=["src/"],
    adherence=0.7,
    evidence="relative imports",
    observation_support=3,
    recent_trend="toward",
)
check("observation_support explicit", rp2.observation_support == 3)
check("recent_trend explicit", rp2.recent_trend == "toward")


# ══════════════════════════════════════════════════════════════
# ConventionEntry dataclass
# ══════════════════════════════════════════════════════════════

print("\n=== ConventionEntry ===")

entry = make_entry()
check("id field", entry.id == "conv-test")
check("convention field", "snake_case" in entry.convention)
check("scope field", entry.scope == ["lib/"])
check("confidence field", entry.confidence == "established")
check("canonical_example field", entry.canonical_example == "lib/foo.py")
check("exceptions default None", entry.exceptions is None)
check("evolution default None", entry.evolution is None)
check("tags field", entry.tags == ["naming"])
check("evidence field is dict", isinstance(entry.evidence, dict))
check("source field", entry.source == "config")

entry_with_evolution = ConventionEntry(
    id="conv-evo",
    convention="Use absolute imports",
    scope=["lib/"],
    confidence="emerging",
    canonical_example="lib/x.py",
    exceptions="legacy modules",
    evolution={"from": "relative", "to": "absolute", "trend": "toward"},
    tags=["imports"],
    evidence={},
    source="discovered",
)
check("exceptions non-None", entry_with_evolution.exceptions == "legacy modules")
check("evolution non-None", isinstance(entry_with_evolution.evolution, dict))
check("evolution trend", entry_with_evolution.evolution["trend"] == "toward")


# ══════════════════════════════════════════════════════════════
# ConventionResult dataclass
# ══════════════════════════════════════════════════════════════

print("\n=== ConventionResult ===")

result_empty = ConventionResult(
    conventions=[],
    conflicts=[],
    candidates=[],
    meta={"run_at": "2026-03-15T00:00:00Z"},
)
check("empty conventions list", result_empty.conventions == [])
check("empty conflicts list", result_empty.conflicts == [])
check("empty candidates list", result_empty.candidates == [])
check("meta field is dict", isinstance(result_empty.meta, dict))


# ══════════════════════════════════════════════════════════════
# ConventionResult.summary()
# ══════════════════════════════════════════════════════════════

print("\n=== ConventionResult.summary() ===")

# Zero conventions
s = result_empty.summary()
check("zero: shows 0 conventions", "0 conventions" in s, s)
check("zero: shows 0 candidates", "0 candidates" in s, s)
check("zero: no sources line when empty", "sources:" not in s, s)

# One convention, one candidate
r1 = ConventionResult(
    conventions=[make_entry(source="config")],
    conflicts=[],
    candidates=[make_entry(source="discovered")],
    meta={},
)
s1 = r1.summary()
check("singular: '1 convention'", "1 convention" in s1, s1)
check("singular: '1 candidate'", "1 candidate" in s1, s1)
check("singular: sources line present", "sources:" in s1, s1)
check("singular: config in sources", "config" in s1, s1)

# Multiple conventions with mixed sources
r2 = ConventionResult(
    conventions=[
        make_entry(source="config"),
        make_entry(source="config"),
        make_entry(source="discovered"),
    ],
    conflicts=[],
    candidates=[],
    meta={},
)
s2 = r2.summary()
check("multi: '3 conventions'", "3 conventions" in s2, s2)
check("multi: '0 candidates'", "0 candidates" in s2, s2)
check("multi: sources has config", "config" in s2, s2)
check("multi: sources has discovered", "discovered" in s2, s2)
check("multi: 2 config in breakdown", "2 config" in s2, s2)
check("multi: 1 discovered in breakdown", "1 discovered" in s2, s2)

# With conflicts
r3 = ConventionResult(
    conventions=[make_entry()],
    conflicts=[{"a": "x", "b": "y"}, {"a": "m", "b": "n"}],
    candidates=[],
    meta={},
)
s3 = r3.summary()
check("conflicts: shows unresolved count", "2 unresolved" in s3, s3)
check("conflicts: plural form", "conflicts" in s3, s3)

r4 = ConventionResult(
    conventions=[make_entry()],
    conflicts=[{"a": "x"}],
    candidates=[],
    meta={},
)
s4 = r4.summary()
check("single conflict: singular form", "1 unresolved conflict" in s4, s4)


# ══════════════════════════════════════════════════════════════
# _atomic_write
# ══════════════════════════════════════════════════════════════

print("\n=== _atomic_write ===")

with tempfile.TemporaryDirectory() as tmp:
    target = Path(tmp) / "output.json"

    # Basic write
    _atomic_write(target, {"key": "value", "count": 42})
    check("file created", target.exists())
    data = json.loads(target.read_text())
    check("data correct after write", data == {"key": "value", "count": 42})

    # Overwrites existing
    _atomic_write(target, {"updated": True})
    data2 = json.loads(target.read_text())
    check("overwrites correctly", data2 == {"updated": True})

    # Accepts list
    _atomic_write(target, [1, 2, 3])
    data3 = json.loads(target.read_text())
    check("accepts list", data3 == [1, 2, 3])

    # Creates parent dirs
    nested = Path(tmp) / "a" / "b" / "c.json"
    _atomic_write(nested, {"nested": True})
    check("creates parent dirs", nested.exists())
    check("nested data correct", json.loads(nested.read_text()) == {"nested": True})

    # No temp files left behind
    remaining_tmp = list(Path(tmp).glob("*.tmp"))
    check("no .tmp files left", len(remaining_tmp) == 0, f"found: {remaining_tmp}")

    # Output is valid JSON with trailing newline
    raw = target.read_text()
    check("ends with newline", raw.endswith("\n"), repr(raw[-2:]))

    # Partial write simulation: if an error occurs mid-write, the target
    # is not corrupted. We write good data first, then trigger a failure.
    good_target = Path(tmp) / "guarded.json"
    _atomic_write(good_target, {"original": "data"})
    original_content = good_target.read_text()

    # Verify original is intact (the error path cleans up the temp file)
    try:
        # Passing a non-serializable object triggers json.dump failure
        _atomic_write(good_target, object())
    except TypeError:
        pass

    current_content = good_target.read_text()
    check("original intact after failed write", current_content == original_content,
          f"content changed: {current_content!r}")

    # No stale temp files after failure
    stale = list(Path(tmp).glob(".guarded.json.*.tmp"))
    check("no stale temp files after failure", len(stale) == 0, f"found: {stale}")


# ══════════════════════════════════════════════════════════════
# Results
# ══════════════════════════════════════════════════════════════

print(f"\n{'='*60}")
print(f"Results: {passed} passed, {failed} failed")
if failed:
    sys.exit(1)
