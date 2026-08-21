"""Phase C: Template formatting, quality bar, confidence assignment, and conflict handling.

Converts RawPatterns from Phase A/B into ConventionEntry objects using
deterministic templates. Applies a six-check quality bar, assigns confidence
levels, tracks convention evolution, and handles conflicting patterns.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict

from lib.learn.conventions import ConventionEntry, RawPattern


# ── Convention templates ─────────────────────────────────────────────
#
# Each key maps a RawPattern.type to a format string. Placeholders are
# filled from a context dict built per-pattern. Patterns whose type has
# no key here go to candidates with rejection_reason='no_matching_template'.


CONVENTION_TEMPLATES: dict[str, str] = {
    # Co-modification
    "comodification": (
        "Always modify `{file_a}` and `{file_b}` together. "
        "Co-modified in {commits}/{total} commits ({rate:.0%})."
    ),
    # Naming: base casing patterns
    "naming_snake": (
        "Use snake_case for {entity_type} in `{scope}`. "
        "{adherence:.0%} of {count} {entity_type}s follow this pattern."
    ),
    "naming_camel": (
        "Use camelCase for {entity_type} in `{scope}`. "
        "{adherence:.0%} of {count} {entity_type}s follow this pattern."
    ),
    "naming_pascal": (
        "Use PascalCase for {entity_type} in `{scope}`. "
        "{adherence:.0%} of {count} {entity_type}s follow this pattern."
    ),
    "naming_upper_snake": (
        "Use UPPER_SNAKE_CASE for {entity_type} in `{scope}`. "
        "{adherence:.0%} of {count} {entity_type}s follow this pattern."
    ),
    # Naming: language-specific patterns
    "naming_go_exported": (
        "Exported symbols use PascalCase, unexported use camelCase in `{scope}`. "
        "Go visibility-by-capitalization. {adherence:.0%} adherence."
    ),
    "naming_cs_interface": (
        "Interfaces use I prefix (e.g., IRepository) in `{scope}`. "
        "{adherence:.0%} of {count} interfaces follow this pattern."
    ),
    "naming_cs_async": (
        "Async methods use Async suffix in `{scope}`. "
        "{adherence:.0%} of {count} async methods follow this pattern."
    ),
    "naming_react_component": (
        "React components use PascalCase in `{scope}`. "
        "{adherence:.0%} of {count} components follow this pattern."
    ),
    "naming_react_hook": (
        "Custom hooks use `use` prefix in `{scope}`. "
        "{adherence:.0%} of {count} hooks follow this pattern."
    ),
    "naming_bool_prefix": (
        "Boolean functions/variables use {prefixes} prefix in `{scope}`. "
        "{adherence:.0%} of {count} boolean names follow this pattern."
    ),
    "naming_ruby_predicate": (
        "Predicate methods end with `?` in `{scope}`. "
        "{adherence:.0%} of {count} boolean methods follow this pattern."
    ),
    "naming_ruby_bang": (
        "Mutating methods end with `!` in `{scope}`. "
        "{adherence:.0%} of {count} mutating methods follow this pattern."
    ),
    # Naming: test file/function patterns
    "naming_test_prefix": (
        "Test files use `{prefix}` prefix in `{scope}`. "
        "{adherence:.0%} of {count} test files follow this pattern."
    ),
    "naming_test_suffix": (
        "Test files use `{suffix}` suffix in `{scope}`. "
        "{adherence:.0%} of {count} test files follow this pattern."
    ),
    # Imports
    "import_relative": (
        "Use relative imports within `{directory}`. "
        "Absolute imports elsewhere. {adherence:.0%} adherence."
    ),
    # Test framework
    "test_framework": (
        "Use {framework} for tests in `{scope}`. "
        "Detected in {count}/{total} test files."
    ),
    # Config-derived
    "config_rule": "{description} (from `{config_file}`).",
    # Dependency usage
    "wrapper_module": (
        "Use `{wrapper}` for {library} calls. "
        "Never import {library} directly. {importers} files use the wrapper."
    ),
}


# ── Generic patterns (quality bar: not_project_specific) ────────────
#
# Convention text containing any of these phrases (case-insensitive)
# fails the project-specific check.

_GENERIC_PHRASES: list[str] = [
    "use meaningful variable names",
    "use meaningful names",
    "use descriptive names",
    "use descriptive variable names",
    "write unit tests",
    "write tests for your code",
    "follow coding standards",
    "keep functions small",
    "avoid global variables",
    "use proper error handling",
    "document your code",
    "use version control",
    "don't repeat yourself",
    "keep it simple",
    "single responsibility",
]

# ── Entity type defaults per template type ───────────────────────────

_ENTITY_TYPES: dict[str, str] = {
    "naming_snake": "identifiers",
    "naming_camel": "identifiers",
    "naming_pascal": "identifiers",
    "naming_upper_snake": "constants",
    "naming_cs_interface": "interfaces",
    "naming_cs_async": "async methods",
    "naming_react_component": "components",
    "naming_react_hook": "hooks",
    "naming_bool_prefix": "boolean names",
    "naming_ruby_predicate": "boolean methods",
    "naming_ruby_bang": "mutating methods",
    "naming_test_prefix": "test files",
    "naming_test_suffix": "test files",
}


# ── Helpers ──────────────────────────────────────────────────────────


class _SafeDict(dict):
    """Dict subclass that returns '{key}' for missing keys during str.format_map."""

    def __missing__(self, key: str) -> str:
        return f"{{{key}}}"


def _make_convention_id(pattern_type: str, scope: list[str]) -> str:
    """Generate a deterministic convention ID from type and scope."""
    scope_str = "|".join(sorted(scope)) if scope else "project"
    payload = f"{pattern_type}:{scope_str}"
    digest = hashlib.sha256(payload.encode()).hexdigest()[:12]
    return f"conv-{pattern_type}-{digest}"


def _build_template_context(pattern: RawPattern) -> dict:
    """Build the placeholder context dict for template formatting."""
    scope_str = pattern.scope[0] if pattern.scope else "project"
    count = len(pattern.files)

    ctx: dict = {
        "scope": scope_str,
        "adherence": pattern.adherence,
        "count": count,
        "total": count,
        "entity_type": _ENTITY_TYPES.get(pattern.type, "identifiers"),
    }

    # Comodification-specific fields
    if pattern.type == "comodification":
        ctx["file_a"] = pattern.files[0] if len(pattern.files) >= 1 else "file_a"
        ctx["file_b"] = pattern.files[1] if len(pattern.files) >= 2 else "file_b"
        ctx["rate"] = pattern.adherence
        ctx["commits"] = max(1, int(pattern.adherence * max(count, 2)))

    # Naming-specific defaults
    if pattern.type == "naming_bool_prefix":
        ctx["prefixes"] = "is/has/can"
    if pattern.type == "naming_test_prefix":
        ctx["prefix"] = "test_"
    if pattern.type == "naming_test_suffix":
        ctx["suffix"] = "_test"

    # Import-specific
    if pattern.type == "import_relative":
        ctx["directory"] = scope_str

    # Test framework: extract framework name from evidence
    if pattern.type == "test_framework":
        ctx["framework"] = _extract_framework(pattern.evidence)

    # Config rule
    if pattern.type == "config_rule":
        ctx["description"] = pattern.evidence
        ctx["config_file"] = pattern.files[0] if pattern.files else "config"

    # Wrapper module
    if pattern.type == "wrapper_module":
        ctx["wrapper"] = pattern.files[0] if pattern.files else "wrapper"
        ctx["library"] = _extract_library(pattern.evidence)
        ctx["importers"] = str(count)

    return ctx


def _extract_framework(evidence: str) -> str:
    """Extract test framework name from evidence string."""
    lowered = evidence.lower()
    for fw in ("pytest", "vitest", "jest", "mocha", "unittest", "rspec", "minitest"):
        if fw in lowered:
            return fw
    return "unknown"


def _extract_library(evidence: str) -> str:
    """Extract library name from evidence string."""
    # Look for patterns like "for X calls" or "import X"
    match = re.search(r"(?:for|import)\s+(\w+)", evidence, re.IGNORECASE)
    if match:
        return match.group(1)
    return "library"


def _format_convention_text(template: str, pattern: RawPattern) -> str:
    """Format a template string with pattern data, using safe defaults for missing keys."""
    ctx = _build_template_context(pattern)
    return template.format_map(_SafeDict(ctx))


# ── Confidence assignment ────────────────────────────────────────────


def _assign_confidence(pattern: RawPattern) -> str:
    """Assign confidence level from enriched evidence.

    Requires two data sources for 'established': high code adherence
    AND at least one corroborating observation. A single data source
    at 95% adherence is not sufficient.
    """
    if pattern.adherence >= 0.9 and pattern.observation_support >= 1:
        return "established"
    if pattern.adherence >= 0.6 or pattern.observation_support >= 3:
        return "emerging"
    if pattern.recent_trend == "away":
        return "decaying"
    return "emerging"


# ── Quality bar ──────────────────────────────────────────────────────


def _check_actionable(convention_text: str) -> bool:
    """Check that convention text specifies a concrete action, not a vague aspiration."""
    # Template-formatted conventions reference specific patterns, scopes, or files.
    # Vague single-clause conventions without scope or file references fail.
    has_backtick_ref = "`" in convention_text
    has_percentage = "%" in convention_text
    has_specific_verb = any(
        v in convention_text.lower()
        for v in ("use ", "always ", "never ", "end with", "prefix")
    )
    return has_backtick_ref or has_percentage or has_specific_verb


def _check_project_specific(convention_text: str) -> bool:
    """Check that convention is project-specific, not a generic best practice."""
    lowered = convention_text.lower()
    return not any(phrase in lowered for phrase in _GENERIC_PHRASES)


def _check_evidenced(pattern: RawPattern) -> bool:
    """Check that pattern has 2+ concrete examples."""
    return len(pattern.files) >= 2


def _check_scoped(pattern: RawPattern) -> bool:
    """Check that pattern specifies where it applies."""
    return bool(pattern.scope) and any(s.strip() for s in pattern.scope)


def _check_redundant(
    entry: ConventionEntry, existing: list[ConventionEntry]
) -> bool:
    """Check if an existing convention covers the same pattern type in overlapping scope.

    Returns True if redundant (should be rejected).
    """
    for ex in existing:
        if not ex.id.startswith("conv-"):
            continue
        # Extract type from convention ID: conv-<type>-<hash>
        parts = ex.id.split("-", 2)
        if len(parts) < 3:
            continue
        ex_type = parts[1]
        entry_parts = entry.id.split("-", 2)
        entry_type = entry_parts[1] if len(entry_parts) >= 3 else ""

        if ex_type == entry_type:
            # Check scope overlap
            ex_scopes = set(ex.scope)
            entry_scopes = set(entry.scope)
            if ex_scopes & entry_scopes:
                return True
    return False


def _apply_quality_bar(
    entry: ConventionEntry,
    pattern: RawPattern,
    existing: list[ConventionEntry],
) -> str | None:
    """Run all quality bar checks. Returns rejection_reason or None if passed."""
    if not _check_actionable(entry.convention):
        return "not_actionable"
    if not _check_project_specific(entry.convention):
        return "not_project_specific"
    if not _check_evidenced(pattern):
        return "not_evidenced"
    if not _check_scoped(pattern):
        return "not_scoped"
    if _check_redundant(entry, existing):
        return "redundant"
    # Template match is checked before quality bar (no_matching_template handled earlier)
    return None


# ── Pattern-to-entry conversion ──────────────────────────────────────


def _pattern_to_entry(
    pattern: RawPattern,
    convention_text: str,
    confidence: str,
    rejection_reason: str | None = None,
) -> ConventionEntry:
    """Convert a RawPattern into a ConventionEntry."""
    entry_id = _make_convention_id(pattern.type, pattern.scope)
    canonical = pattern.files[0] if pattern.files else ""

    evidence: dict = {
        "code_adherence": pattern.adherence,
        "observation_support": pattern.observation_support,
        "files_checked": len(pattern.files),
        "recent_trend": pattern.recent_trend,
    }
    if rejection_reason:
        evidence["rejection_reason"] = rejection_reason

    return ConventionEntry(
        id=entry_id,
        convention=convention_text,
        scope=list(pattern.scope),
        confidence=confidence,
        canonical_example=canonical,
        exceptions=None,
        evolution=None,
        tags=[pattern.type],
        evidence=evidence,
        source="discovered",
    )


# ── Evolution tracking ───────────────────────────────────────────────


def _detect_evolution(entries: list[ConventionEntry]) -> None:
    """Detect old/new pattern pairs in the same scope and populate evolution fields.

    When one pattern in a scope trends 'away' while another trends 'toward',
    the away-trending pattern is the old one and the toward-trending is the new one.
    Mutates entries in place.
    """
    # Group entries by scope (using first scope element as key)
    by_scope: dict[str, list[ConventionEntry]] = defaultdict(list)
    for entry in entries:
        for s in entry.scope:
            by_scope[s].append(entry)

    for scope_key, scope_entries in by_scope.items():
        if len(scope_entries) < 2:
            continue

        away_entries = [
            e for e in scope_entries
            if e.evidence.get("recent_trend") == "away"
        ]
        toward_entries = [
            e for e in scope_entries
            if e.evidence.get("recent_trend") == "toward"
        ]

        for old in away_entries:
            for new in toward_entries:
                evolution_data = {
                    "old_pattern": old.convention,
                    "old_files": old.scope,
                    "new_pattern": new.convention,
                    "transition_started": f"scope {scope_key}",
                    "note": "Do not follow old pattern. Do not refactor old code unless task requires it.",
                }
                old.evolution = evolution_data
                new.evolution = evolution_data


# ── Conflict handling ────────────────────────────────────────────────


def _handle_conflicts(
    entries: list[ConventionEntry],
    candidates: list[ConventionEntry],
) -> list[dict]:
    """Detect and handle conflicting patterns in the same scope.

    Two patterns of the same category in the same scope with neither dominant
    produce a conflict dict. If observation evidence favors one, auto-resolve
    by setting the winner to emerging/established and the loser to decaying.

    Returns list of conflict dicts. Mutates entries and candidates in place.
    """
    conflicts: list[dict] = []

    # Group by (category, scope) where category is the first tag
    by_group: dict[tuple[str, str], list[ConventionEntry]] = defaultdict(list)
    for entry in entries:
        category = entry.tags[0] if entry.tags else ""
        for s in entry.scope:
            by_group[(category, s)].append(entry)

    for (category, scope_key), group in by_group.items():
        if len(group) < 2:
            continue

        # Compare pairs
        i = 0
        while i < len(group):
            j = i + 1
            while j < len(group):
                a, b = group[i], group[j]
                a_support = a.evidence.get("observation_support", 0)
                b_support = b.evidence.get("observation_support", 0)
                a_adherence = a.evidence.get("code_adherence", 0)
                b_adherence = b.evidence.get("code_adherence", 0)

                # Check if evidence favors one pattern
                if a_support > b_support or (a_support == b_support and a_adherence > b_adherence):
                    # A wins: auto-resolve
                    b.confidence = "decaying"
                    if a.confidence not in ("established",):
                        a.confidence = "emerging"
                elif b_support > a_support or (b_support == a_support and b_adherence > a_adherence):
                    # B wins: auto-resolve
                    a.confidence = "decaying"
                    if b.confidence not in ("established",):
                        b.confidence = "emerging"
                else:
                    # Neither dominant: create conflict, move both to candidates
                    conflict = {
                        "category": category,
                        "scope": scope_key,
                        "pattern_a": {
                            "id": a.id,
                            "convention": a.convention,
                            "adherence": a.evidence.get("code_adherence", 0),
                            "observation_support": a_support,
                        },
                        "pattern_b": {
                            "id": b.id,
                            "convention": b.convention,
                            "adherence": b.evidence.get("code_adherence", 0),
                            "observation_support": b_support,
                        },
                        "status": "unresolved",
                    }
                    conflicts.append(conflict)
                    # Move conflicting entries to candidates
                    if a in entries:
                        entries.remove(a)
                        a.evidence["rejection_reason"] = "conflict"
                        candidates.append(a)
                    if b in entries:
                        entries.remove(b)
                        b.evidence["rejection_reason"] = "conflict"
                        candidates.append(b)
                j += 1
            i += 1

    return conflicts


# ── Main entry point ─────────────────────────────────────────────────


def _format_and_validate(
    enriched_patterns: list[RawPattern],
    config_conventions: list[ConventionEntry],
) -> tuple[list[ConventionEntry], list[ConventionEntry]]:
    """Apply templates, quality bar, assign confidence. Returns (passed, candidates).

    Config conventions pass through without quality bar filtering (the config
    file itself is evidence). Discovered patterns go through the full pipeline:
    template lookup, formatting, quality bar, confidence assignment, evolution
    detection, and conflict handling.
    """
    passed: list[ConventionEntry] = []
    candidates: list[ConventionEntry] = []

    # Config conventions skip quality bar
    passed.extend(config_conventions)

    for pattern in enriched_patterns:
        # 1. Template match check
        template = CONVENTION_TEMPLATES.get(pattern.type)
        if template is None:
            entry = _pattern_to_entry(
                pattern,
                convention_text=pattern.evidence or f"Pattern: {pattern.type}",
                confidence="emerging",
                rejection_reason="no_matching_template",
            )
            candidates.append(entry)
            continue

        # 2. Format convention text from template
        convention_text = _format_convention_text(template, pattern)

        # 3. Assign confidence
        confidence = _assign_confidence(pattern)

        # 4. Create entry
        entry = _pattern_to_entry(pattern, convention_text, confidence)

        # 5. Quality bar
        rejection = _apply_quality_bar(entry, pattern, passed)
        if rejection:
            entry.evidence["rejection_reason"] = rejection
            candidates.append(entry)
        else:
            passed.append(entry)

    # 6. Evolution tracking across passed entries
    _detect_evolution(passed)

    # 7. Conflict handling
    conflicts = _handle_conflicts(passed, candidates)

    return passed, candidates
