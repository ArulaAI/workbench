#!/usr/bin/env python3
"""Tests for Phase C: Template formatting, quality bar, and confidence assignment.

Covers all 20 CONVENTION_TEMPLATES, quality bar rejection reasons,
confidence assignment logic, evolution tracking, and conflict handling.
"""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from lib.learn.conventions import ConventionEntry, RawPattern
from lib.learn.convention_templates import (
    CONVENTION_TEMPLATES,
    _assign_confidence,
    _apply_quality_bar,
    _build_template_context,
    _check_actionable,
    _check_evidenced,
    _check_project_specific,
    _check_scoped,
    _detect_evolution,
    _format_and_validate,
    _format_convention_text,
    _handle_conflicts,
    _make_convention_id,
    _pattern_to_entry,
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


def make_pattern(
    ptype="naming_snake",
    files=None,
    scope=None,
    adherence=0.85,
    evidence="10 of 12 identifiers use snake_case",
    obs_support=0,
    trend="stable",
):
    return RawPattern(
        type=ptype,
        files=files if files is not None else ["lib/foo.py", "lib/bar.py"],
        scope=scope if scope is not None else ["lib/"],
        adherence=adherence,
        evidence=evidence,
        observation_support=obs_support,
        recent_trend=trend,
    )


def make_config_entry(entry_id="conv-config-001", scope=None):
    return ConventionEntry(
        id=entry_id,
        convention="Use 4-space indentation (from `.editorconfig`).",
        scope=scope if scope is not None else ["project"],
        confidence="established",
        canonical_example=".editorconfig",
        exceptions=None,
        evolution=None,
        tags=["config_rule"],
        evidence={"source_file": ".editorconfig"},
        source="config",
    )


# ══════════════════════════════════════════════════════════════
# 1: CONVENTION_TEMPLATES — all 20 entries
# ══════════════════════════════════════════════════════════════

print("\n=== 1: CONVENTION_TEMPLATES completeness ===")

EXPECTED_KEYS = [
    "comodification",
    "naming_snake", "naming_camel", "naming_pascal", "naming_upper_snake",
    "naming_go_exported", "naming_cs_interface", "naming_cs_async",
    "naming_react_component", "naming_react_hook", "naming_bool_prefix",
    "naming_ruby_predicate", "naming_ruby_bang",
    "naming_test_prefix", "naming_test_suffix",
    "import_relative",
    "test_framework",
    "config_rule",
    "wrapper_module",
]

check("19 template entries (spec lists 19 despite saying 20)",
      len(CONVENTION_TEMPLATES) == 19,
      f"got {len(CONVENTION_TEMPLATES)}")

for key in EXPECTED_KEYS:
    check(f"template key '{key}' exists", key in CONVENTION_TEMPLATES,
          f"missing from CONVENTION_TEMPLATES")


# ══════════════════════════════════════════════════════════════
# 2: Template formatting produces valid convention text
# ══════════════════════════════════════════════════════════════

print("\n=== 2: Template formatting with sample data ===")

# Each template type produces non-empty text with no unresolved placeholders
SAMPLE_PATTERNS = {
    "comodification": make_pattern(
        ptype="comodification",
        files=["lib/api.py", "lib/api_test.py", "lib/utils.py"],
        adherence=0.85,
        evidence="co-modified in 17 of 20 commits",
    ),
    "naming_snake": make_pattern(),
    "naming_camel": make_pattern(ptype="naming_camel"),
    "naming_pascal": make_pattern(ptype="naming_pascal"),
    "naming_upper_snake": make_pattern(ptype="naming_upper_snake"),
    "naming_go_exported": make_pattern(ptype="naming_go_exported"),
    "naming_cs_interface": make_pattern(ptype="naming_cs_interface"),
    "naming_cs_async": make_pattern(ptype="naming_cs_async"),
    "naming_react_component": make_pattern(ptype="naming_react_component"),
    "naming_react_hook": make_pattern(ptype="naming_react_hook"),
    "naming_bool_prefix": make_pattern(ptype="naming_bool_prefix"),
    "naming_ruby_predicate": make_pattern(ptype="naming_ruby_predicate"),
    "naming_ruby_bang": make_pattern(ptype="naming_ruby_bang"),
    "naming_test_prefix": make_pattern(ptype="naming_test_prefix"),
    "naming_test_suffix": make_pattern(ptype="naming_test_suffix"),
    "import_relative": make_pattern(
        ptype="import_relative",
        evidence="relative imports in lib/",
    ),
    "test_framework": make_pattern(
        ptype="test_framework",
        evidence="pytest detected in 8 of 10 test files",
    ),
    "config_rule": make_pattern(
        ptype="config_rule",
        files=[".eslintrc.json"],
        evidence="No unused variables",
    ),
    "wrapper_module": make_pattern(
        ptype="wrapper_module",
        files=["lib/http_client.py", "lib/api/auth.py"],
        evidence="for httpx calls via wrapper",
    ),
}

for key, pattern in SAMPLE_PATTERNS.items():
    template = CONVENTION_TEMPLATES[key]
    text = _format_convention_text(template, pattern)
    check(f"'{key}' produces non-empty text", len(text) > 0, f"got empty string")
    # No unresolved {placeholders} remaining
    import re as _re
    unresolved = _re.findall(r"\{[a-z_]+\}", text)
    check(f"'{key}' has no unresolved placeholders", len(unresolved) == 0,
          f"unresolved: {unresolved}")


# ══════════════════════════════════════════════════════════════
# 3: Comodification template produces expected string
# ══════════════════════════════════════════════════════════════

print("\n=== 3: Comodification template ===")

comod_pattern = make_pattern(
    ptype="comodification",
    files=["lib/api.py", "lib/api_test.py"],
    scope=["lib/"],
    adherence=0.9,
    evidence="co-modified in 9 of 10 commits",
)
comod_text = _format_convention_text(CONVENTION_TEMPLATES["comodification"], comod_pattern)
check("comod: contains file_a", "`lib/api.py`" in comod_text, comod_text)
check("comod: contains file_b", "`lib/api_test.py`" in comod_text, comod_text)
check("comod: contains rate percentage", "90%" in comod_text, comod_text)
check("comod: starts with 'Always modify'", comod_text.startswith("Always modify"), comod_text)

# Full pipeline: comodification pattern maps to template and produces entry
comod_entries, comod_cands = _format_and_validate([comod_pattern], [])
comod_discovered = [e for e in comod_entries if e.source == "discovered"]
check("comod: produces a passed entry", len(comod_discovered) >= 1,
      f"entries={len(comod_discovered)}, candidates={len(comod_cands)}")
if comod_discovered:
    check("comod: convention text matches",
          "`lib/api.py`" in comod_discovered[0].convention,
          comod_discovered[0].convention)


# ══════════════════════════════════════════════════════════════
# 4: No matching template → candidates with rejection_reason
# ══════════════════════════════════════════════════════════════

print("\n=== 4: No matching template ===")

unknown_pattern = make_pattern(
    ptype="unknown_pattern_type",
    files=["lib/a.py", "lib/b.py"],
    scope=["lib/"],
    adherence=0.8,
    evidence="some unknown pattern",
)
entries_4, candidates_4 = _format_and_validate([unknown_pattern], [])
discovered_4 = [e for e in entries_4 if e.source == "discovered"]
check("no template: goes to candidates", len(candidates_4) == 1,
      f"candidates={len(candidates_4)}")
check("no template: not in passed entries", len(discovered_4) == 0,
      f"discovered={len(discovered_4)}")
if candidates_4:
    check("no template: rejection_reason set",
          candidates_4[0].evidence.get("rejection_reason") == "no_matching_template",
          f"got {candidates_4[0].evidence.get('rejection_reason')}")


# ══════════════════════════════════════════════════════════════
# 5: Quality bar — not_project_specific
# ══════════════════════════════════════════════════════════════

print("\n=== 5: Quality bar — not_project_specific ===")

check("generic: 'Use meaningful variable names' fails",
      not _check_project_specific("Use meaningful variable names"))
check("generic: 'Write unit tests' fails",
      not _check_project_specific("Write unit tests"))
check("specific: template-formatted text passes",
      _check_project_specific(
          "Use snake_case for identifiers in `lib/`. 85% of 12 identifiers follow this pattern."
      ))

# Full pipeline: pattern that produces generic text
# (For this we test the quality bar directly since templates produce specific text)
generic_entry = ConventionEntry(
    id="conv-test-generic",
    convention="Use meaningful variable names",
    scope=["lib/"],
    confidence="emerging",
    canonical_example="lib/foo.py",
    exceptions=None,
    evolution=None,
    tags=["naming"],
    evidence={},
    source="discovered",
)
generic_pattern = make_pattern()
rejection = _apply_quality_bar(generic_entry, generic_pattern, [])
check("quality bar: rejects generic as not_project_specific",
      rejection == "not_project_specific", f"got {rejection}")


# ══════════════════════════════════════════════════════════════
# 6: Quality bar — not_evidenced
# ══════════════════════════════════════════════════════════════

print("\n=== 6: Quality bar — not_evidenced ===")

# Pattern with only 1 file (needs 2+)
single_file_pattern = make_pattern(files=["lib/foo.py"])
check("evidenced: 1 file fails", not _check_evidenced(single_file_pattern))
check("evidenced: 2 files passes", _check_evidenced(make_pattern()))

# Pattern with no canonical_example (empty files)
no_files_pattern = make_pattern(files=[])
check("evidenced: 0 files fails", not _check_evidenced(no_files_pattern))

# Full pipeline: single file pattern gets rejected
single_entries, single_cands = _format_and_validate([single_file_pattern], [])
discovered_single = [e for e in single_entries if e.source == "discovered"]
check("not_evidenced: rejected in pipeline",
      len(single_cands) == 1, f"candidates={len(single_cands)}")
if single_cands:
    check("not_evidenced: rejection_reason set",
          single_cands[0].evidence.get("rejection_reason") == "not_evidenced",
          f"got {single_cands[0].evidence.get('rejection_reason')}")


# ══════════════════════════════════════════════════════════════
# 7: _assign_confidence — established
# ══════════════════════════════════════════════════════════════

print("\n=== 7: _assign_confidence — established ===")

established_pattern = make_pattern(adherence=0.92, obs_support=2)
check("92% + 2 obs → established",
      _assign_confidence(established_pattern) == "established",
      f"got {_assign_confidence(established_pattern)}")

# Exactly 90% boundary
boundary_pattern = make_pattern(adherence=0.90, obs_support=1)
check("90% + 1 obs → established",
      _assign_confidence(boundary_pattern) == "established",
      f"got {_assign_confidence(boundary_pattern)}")


# ══════════════════════════════════════════════════════════════
# 8: _assign_confidence — emerging (adherence path)
# ══════════════════════════════════════════════════════════════

print("\n=== 8: _assign_confidence — emerging (adherence) ===")

emerging_adh_pattern = make_pattern(adherence=0.65, obs_support=0)
check("65% + 0 obs → emerging",
      _assign_confidence(emerging_adh_pattern) == "emerging",
      f"got {_assign_confidence(emerging_adh_pattern)}")

# 60% boundary
emerging_60_pattern = make_pattern(adherence=0.60, obs_support=0)
check("60% + 0 obs → emerging",
      _assign_confidence(emerging_60_pattern) == "emerging",
      f"got {_assign_confidence(emerging_60_pattern)}")


# ══════════════════════════════════════════════════════════════
# 9: _assign_confidence — decaying
# ══════════════════════════════════════════════════════════════

print("\n=== 9: _assign_confidence — decaying ===")

decaying_pattern = make_pattern(adherence=0.3, obs_support=0, trend="away")
check("trend=away + low adherence → decaying",
      _assign_confidence(decaying_pattern) == "decaying",
      f"got {_assign_confidence(decaying_pattern)}")

# Trend away but high adherence still triggers emerging (adherence check first)
decaying_high_adh = make_pattern(adherence=0.7, obs_support=0, trend="away")
check("trend=away + 70% adherence → emerging (adherence wins)",
      _assign_confidence(decaying_high_adh) == "emerging",
      f"got {_assign_confidence(decaying_high_adh)}")


# ══════════════════════════════════════════════════════════════
# 10: _assign_confidence — 95% + 0 obs is NOT established
# ══════════════════════════════════════════════════════════════

print("\n=== 10: Single source insufficient for established ===")

single_source_pattern = make_pattern(adherence=0.95, obs_support=0)
check("95% + 0 obs → emerging (not established)",
      _assign_confidence(single_source_pattern) == "emerging",
      f"got {_assign_confidence(single_source_pattern)}")

# Even 99% with 0 observations
very_high = make_pattern(adherence=0.99, obs_support=0)
check("99% + 0 obs → emerging (single source)",
      _assign_confidence(very_high) == "emerging",
      f"got {_assign_confidence(very_high)}")


# ══════════════════════════════════════════════════════════════
# 11: Evolution tracking
# ══════════════════════════════════════════════════════════════

print("\n=== 11: Evolution tracking ===")

old_pattern = make_pattern(
    ptype="naming_snake",
    files=["lib/old.py", "lib/legacy.py"],
    scope=["lib/"],
    adherence=0.4,
    obs_support=1,
    trend="away",
)
new_pattern = make_pattern(
    ptype="naming_camel",
    files=["lib/new.py", "lib/modern.py"],
    scope=["lib/"],
    adherence=0.7,
    obs_support=2,
    trend="toward",
)

evo_entries, evo_cands = _format_and_validate([old_pattern, new_pattern], [])
discovered_evo = [e for e in evo_entries if e.source == "discovered"]

# Find entries with evolution set
evo_with_field = [e for e in discovered_evo if e.evolution is not None]
check("evolution: at least one entry has evolution field",
      len(evo_with_field) >= 1,
      f"entries with evolution: {len(evo_with_field)}")

if evo_with_field:
    evo_data = evo_with_field[0].evolution
    check("evolution: has old_pattern key", "old_pattern" in evo_data,
          f"keys: {list(evo_data.keys())}")
    check("evolution: has new_pattern key", "new_pattern" in evo_data,
          f"keys: {list(evo_data.keys())}")


# Test evolution directly
print("\n--- Evolution direct test ---")
entry_old = _pattern_to_entry(old_pattern, "Old convention", "decaying")
entry_old.evidence["recent_trend"] = "away"
entry_new = _pattern_to_entry(new_pattern, "New convention", "emerging")
entry_new.evidence["recent_trend"] = "toward"

test_entries = [entry_old, entry_new]
_detect_evolution(test_entries)

check("direct: old entry gets evolution",
      entry_old.evolution is not None,
      "evolution is None")
check("direct: new entry gets evolution",
      entry_new.evolution is not None,
      "evolution is None")

if entry_old.evolution:
    check("direct: evolution references old convention",
          entry_old.evolution["old_pattern"] == "Old convention")
    check("direct: evolution references new convention",
          entry_old.evolution["new_pattern"] == "New convention")


# ══════════════════════════════════════════════════════════════
# 12: Conflict — neither dominant
# ══════════════════════════════════════════════════════════════

print("\n=== 12: Conflict — neither dominant ===")

conflict_a = _pattern_to_entry(
    make_pattern(ptype="naming_snake", scope=["src/"], adherence=0.5, obs_support=1),
    "Use snake_case in `src/`.",
    "emerging",
)
conflict_b = _pattern_to_entry(
    make_pattern(ptype="naming_snake", scope=["src/"], adherence=0.5, obs_support=1),
    "Use camelCase in `src/`.",
    "emerging",
)
# Give them the same tag so they're in the same category
conflict_b.tags = ["naming_snake"]

conflict_entries = [conflict_a, conflict_b]
conflict_candidates: list[ConventionEntry] = []
conflicts = _handle_conflicts(conflict_entries, conflict_candidates)

check("conflict: created when neither dominant",
      len(conflicts) >= 1, f"conflicts={len(conflicts)}")
if conflicts:
    check("conflict: has pattern_a and pattern_b",
          "pattern_a" in conflicts[0] and "pattern_b" in conflicts[0])
    check("conflict: status is unresolved",
          conflicts[0]["status"] == "unresolved")

check("conflict: both moved to candidates",
      len(conflict_candidates) == 2,
      f"candidates={len(conflict_candidates)}")
check("conflict: entries list emptied",
      len(conflict_entries) == 0,
      f"entries={len(conflict_entries)}")


# ══════════════════════════════════════════════════════════════
# 13: Conflict — auto-resolved by observation evidence
# ══════════════════════════════════════════════════════════════

print("\n=== 13: Conflict — auto-resolved ===")

winner = _pattern_to_entry(
    make_pattern(ptype="naming_camel", scope=["src/"], adherence=0.7, obs_support=3),
    "Use camelCase in `src/`.",
    "emerging",
)
loser = _pattern_to_entry(
    make_pattern(ptype="naming_camel", scope=["src/"], adherence=0.5, obs_support=0),
    "Use snake_case in `src/`.",
    "emerging",
)

auto_entries = [winner, loser]
auto_candidates: list[ConventionEntry] = []
auto_conflicts = _handle_conflicts(auto_entries, auto_candidates)

check("auto-resolve: no unresolved conflicts",
      len(auto_conflicts) == 0,
      f"conflicts={len(auto_conflicts)}")
check("auto-resolve: both stay in entries",
      len(auto_entries) == 2,
      f"entries={len(auto_entries)}")
check("auto-resolve: loser is decaying",
      loser.confidence == "decaying",
      f"loser confidence={loser.confidence}")
check("auto-resolve: winner confidence preserved or set",
      winner.confidence in ("emerging", "established"),
      f"winner confidence={winner.confidence}")


# ══════════════════════════════════════════════════════════════
# 14: Config conventions pass through
# ══════════════════════════════════════════════════════════════

print("\n=== 14: Config conventions pass through ===")

config_entry = make_config_entry()
entries_14, candidates_14 = _format_and_validate([], [config_entry])
check("config: appears in passed entries",
      any(e.id == "conv-config-001" for e in entries_14),
      f"entries={[e.id for e in entries_14]}")
check("config: not in candidates",
      not any(e.id == "conv-config-001" for e in candidates_14),
      f"candidates={[e.id for e in candidates_14]}")
check("config: source is config",
      entries_14[0].source == "config")
check("config: no quality bar applied (no rejection_reason)",
      "rejection_reason" not in entries_14[0].evidence,
      f"evidence keys={list(entries_14[0].evidence.keys())}")


# ══════════════════════════════════════════════════════════════
# 15: Quality bar — not_scoped
# ══════════════════════════════════════════════════════════════

print("\n=== 15: Quality bar — not_scoped ===")

no_scope_pattern = make_pattern(scope=[])
check("scoped: empty scope fails", not _check_scoped(no_scope_pattern))
check("scoped: non-empty scope passes", _check_scoped(make_pattern()))

# Scope with only whitespace
ws_scope_pattern = make_pattern(scope=["  ", ""])
check("scoped: whitespace-only scope fails", not _check_scoped(ws_scope_pattern))


# ══════════════════════════════════════════════════════════════
# 16: Quality bar — redundant
# ══════════════════════════════════════════════════════════════

print("\n=== 16: Quality bar — redundant ===")

existing_entry = _pattern_to_entry(
    make_pattern(ptype="naming_snake", scope=["lib/"]),
    "Use snake_case in lib/",
    "established",
)
duplicate_entry = _pattern_to_entry(
    make_pattern(ptype="naming_snake", scope=["lib/"]),
    "Use snake_case in lib/ (duplicate)",
    "emerging",
)
from lib.learn.convention_templates import _check_redundant
check("redundant: same type + same scope is redundant",
      _check_redundant(duplicate_entry, [existing_entry]))

different_scope_entry = _pattern_to_entry(
    make_pattern(ptype="naming_snake", scope=["src/"]),
    "Use snake_case in src/",
    "emerging",
)
check("redundant: same type + different scope is not redundant",
      not _check_redundant(different_scope_entry, [existing_entry]))

different_type_entry = _pattern_to_entry(
    make_pattern(ptype="naming_camel", scope=["lib/"]),
    "Use camelCase in lib/",
    "emerging",
)
check("redundant: different type + same scope is not redundant",
      not _check_redundant(different_type_entry, [existing_entry]))


# ══════════════════════════════════════════════════════════════
# 17: Convention ID generation
# ══════════════════════════════════════════════════════════════

print("\n=== 17: Convention ID generation ===")

id1 = _make_convention_id("naming_snake", ["lib/"])
id2 = _make_convention_id("naming_snake", ["lib/"])
id3 = _make_convention_id("naming_snake", ["src/"])
id4 = _make_convention_id("naming_camel", ["lib/"])

check("id: deterministic", id1 == id2)
check("id: different scope → different id", id1 != id3)
check("id: different type → different id", id1 != id4)
check("id: starts with conv-", id1.startswith("conv-"))


# ══════════════════════════════════════════════════════════════
# 18: _assign_confidence — emerging (observation path)
# ══════════════════════════════════════════════════════════════

print("\n=== 18: _assign_confidence — emerging (observation path) ===")

obs_3_pattern = make_pattern(adherence=0.3, obs_support=3)
check("low adherence + 3 obs → emerging",
      _assign_confidence(obs_3_pattern) == "emerging",
      f"got {_assign_confidence(obs_3_pattern)}")

# Default case: low adherence, no observations, stable trend
default_pattern = make_pattern(adherence=0.3, obs_support=0, trend="stable")
check("low adherence + 0 obs + stable → emerging (default)",
      _assign_confidence(default_pattern) == "emerging",
      f"got {_assign_confidence(default_pattern)}")


# ══════════════════════════════════════════════════════════════
# 19: End-to-end pipeline
# ══════════════════════════════════════════════════════════════

print("\n=== 19: End-to-end pipeline ===")

patterns = [
    make_pattern(
        ptype="naming_snake",
        files=["lib/a.py", "lib/b.py", "lib/c.py"],
        scope=["lib/"],
        adherence=0.92,
        obs_support=2,
    ),
    make_pattern(
        ptype="test_framework",
        files=["tests/test_a.py", "tests/test_b.py"],
        scope=["tests/"],
        adherence=0.9,
        obs_support=1,
        evidence="pytest detected in test files",
    ),
    # Unknown type → candidate
    make_pattern(
        ptype="error_handling_strategy",
        files=["lib/api.py", "lib/core.py"],
        scope=["lib/"],
    ),
]
config_convs = [make_config_entry()]

e2e_entries, e2e_cands = _format_and_validate(patterns, config_convs)

check("e2e: config entry passes through",
      any(e.source == "config" for e in e2e_entries))
check("e2e: naming_snake accepted",
      any("snake_case" in e.convention for e in e2e_entries if e.source == "discovered"))
check("e2e: test_framework accepted",
      any("pytest" in e.convention for e in e2e_entries if e.source == "discovered"))
check("e2e: unknown type → candidate",
      any(c.evidence.get("rejection_reason") == "no_matching_template" for c in e2e_cands))

# Confidence assignments
snake_entry = next(e for e in e2e_entries if "snake_case" in e.convention)
check("e2e: naming_snake is established (92% + 2 obs)",
      snake_entry.confidence == "established",
      f"got {snake_entry.confidence}")

test_entry = next(e for e in e2e_entries if "pytest" in e.convention)
check("e2e: test_framework is established (90% + 1 obs)",
      test_entry.confidence == "established",
      f"got {test_entry.confidence}")


# ══════════════════════════════════════════════════════════════
# 20: Actionable check
# ══════════════════════════════════════════════════════════════

print("\n=== 20: Actionable check ===")

check("actionable: template text with backticks passes",
      _check_actionable("Use snake_case for identifiers in `lib/`."))
check("actionable: text with percentage passes",
      _check_actionable("85% of identifiers follow this."))
check("actionable: text with 'Use' passes",
      _check_actionable("Use relative imports within lib/."))
check("actionable: vague text fails",
      not _check_actionable("Good code quality."))


# ══════════════════════════════════════════════════════════════
# Results
# ══════════════════════════════════════════════════════════════

print(f"\n{'='*60}")
print(f"Results: {passed} passed, {failed} failed")
if failed:
    sys.exit(1)
