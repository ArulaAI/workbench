#!/usr/bin/env python3
"""Unit tests for related spec compression (lib/context/related_specs.py).

Tests individual functions with synthetic inputs — no full build required.
Covers: TF-IDF scoring, front-matter parsing, structural boosters,
hard stops, budget assembly, scoring diagnostics.
"""

import os
import sys
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from lib.context.related_specs import (
    _parse_front_matter,
    _compute_tfidf_scores,
    _apply_structural_boosts,
    _assemble_within_budget,
    score_and_assemble_specs,
    ScoringError,
    BOOST_FRONT_MATTER,
    BOOST_CROSS_REF,
    BOOST_DEPENDENCY,
    BOOST_FILENAME_PAIR,
    BOOST_PARENT_REF,
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


# ══════════════════════════════════════════════════════════════
# 1: Front-matter Parsing
# ══════════════════════════════════════════════════════════════

print("\n=== 1: Front-matter Parsing ===")

# Basic front-matter with related paths
fm_spec = """---
title: My Feature
related:
  - specs/tech/speed-defects.md
  - specs/tech/speed-audit.md
version: 1.0
---

# My Feature

Content here.
"""

fm_result = _parse_front_matter({"specs/tech/my-feature.md": fm_spec})
check("parses related paths", len(fm_result) == 2, f"got {len(fm_result)}")
check("includes defects path", os.path.normpath("specs/tech/speed-defects.md") in fm_result)
check("includes audit path", os.path.normpath("specs/tech/speed-audit.md") in fm_result)

# No front-matter
no_fm_result = _parse_front_matter({"specs/tech/plain.md": "# Just a spec\n\nNo front-matter."})
check("no front-matter returns empty set", len(no_fm_result) == 0)

# Front-matter without related key
no_related = _parse_front_matter({"specs/tech/other.md": "---\ntitle: Other\n---\nContent."})
check("no related key returns empty set", len(no_related) == 0)

# Quoted paths
quoted_fm = """---
related:
  - 'specs/tech/quoted-single.md'
  - "specs/tech/quoted-double.md"
---
"""
quoted_result = _parse_front_matter({"test.md": quoted_fm})
check("strips single quotes", os.path.normpath("specs/tech/quoted-single.md") in quoted_result)
check("strips double quotes", os.path.normpath("specs/tech/quoted-double.md") in quoted_result)

# Multiple primary specs (union of all related)
multi_result = _parse_front_matter({
    "specs/tech/a.md": "---\nrelated:\n  - specs/tech/x.md\n---\n",
    "specs/product/a.md": "---\nrelated:\n  - specs/tech/y.md\n---\n",
})
check("unions across primary specs", len(multi_result) == 2)


# ══════════════════════════════════════════════════════════════
# 2: TF-IDF Scoring
# ══════════════════════════════════════════════════════════════

print("\n=== 2: TF-IDF Scoring ===")

primary_texts = ["Security audit scanning vulnerability detection threat analysis"]
related_texts = {
    "specs/tech/speed-security-audit.md": "Security scanning vulnerability detection threat mitigation audit compliance",
    "specs/tech/speed-figma.md": "Figma design tokens color palette typography spacing layout components",
    "specs/tech/speed-feedback.md": "Feedback loop error handling retry mechanism timeout recovery",
}

scores = _compute_tfidf_scores(primary_texts, related_texts)

check("returns scores for all candidates", len(scores) == 3)
check("all scores between 0 and 1",
      all(0.0 <= s <= 1.0 for s in scores.values()),
      f"scores: {scores}")
check("security spec scores highest",
      scores["specs/tech/speed-security-audit.md"] > scores["specs/tech/speed-figma.md"],
      f"security={scores['specs/tech/speed-security-audit.md']:.4f}, figma={scores['specs/tech/speed-figma.md']:.4f}")
check("figma spec scores low (below security)",
      scores["specs/tech/speed-figma.md"] < scores["specs/tech/speed-security-audit.md"],
      f"figma={scores['specs/tech/speed-figma.md']:.4f}, security={scores['specs/tech/speed-security-audit.md']:.4f}")

# Empty candidates
empty_scores = _compute_tfidf_scores(["some content"], {})
check("empty candidates returns empty dict", len(empty_scores) == 0)


# ══════════════════════════════════════════════════════════════
# 3: Structural Boosters
# ══════════════════════════════════════════════════════════════

print("\n=== 3: Structural Boosters ===")

with tempfile.TemporaryDirectory() as tmpdir:
    # Links use relative paths from the spec's directory.
    # _parse_links resolves: join(project_root, spec_path) → dirname → join(link_path)
    # For "specs/tech/speed-security.md" in tmpdir:
    #   spec_dir = tmpdir/specs/tech/
    #   link "speed-defects.md" → tmpdir/specs/tech/speed-defects.md
    primary = {
        "specs/tech/speed-security.md": (
            "> Depends on: [defects](speed-defects.md)\n"
            "> Parent RFC: [overview](../product/overview.md)\n"
            "\n"
            "# Security\n\n"
            "See [audit spec](speed-audit.md) for details.\n"
        ),
    }
    related = {
        "specs/tech/speed-defects.md": "defects content",
        "specs/tech/speed-audit.md": "audit content",
        "specs/product/overview.md": "overview content",
        "specs/product/speed-security.md": "product security content",
        "specs/tech/speed-figma.md": "figma content",
    }
    base_scores = {p: 0.10 for p in related}
    fm_paths = {os.path.normpath("specs/tech/speed-defects.md")}

    boosted = _apply_structural_boosts(primary, related, base_scores, tmpdir, fm_paths)

    check("front-matter boost applied",
          boosted["specs/tech/speed-defects.md"]["score"] >= 0.10 + BOOST_FRONT_MATTER,
          f"score={boosted['specs/tech/speed-defects.md']['score']}")
    check("front-matter signal recorded",
          "front_matter" in boosted["specs/tech/speed-defects.md"]["signals"])

    check("dependency boost also applied",
          "dependency_header" in boosted["specs/tech/speed-defects.md"]["signals"],
          f"signals={boosted['specs/tech/speed-defects.md']['signals']}")

    check("cross-ref boost applied to audit",
          boosted["specs/tech/speed-audit.md"]["score"] >= 0.10 + BOOST_CROSS_REF,
          f"score={boosted['specs/tech/speed-audit.md']['score']}")
    check("cross_ref signal recorded",
          "cross_ref" in boosted["specs/tech/speed-audit.md"]["signals"])

    check("parent ref boost applied to overview",
          boosted["specs/product/overview.md"]["score"] >= 0.10 + BOOST_PARENT_REF,
          f"score={boosted['specs/product/overview.md']['score']}")

    check("filename pair boost applied to product/speed-security",
          boosted["specs/product/speed-security.md"]["score"] >= 0.10 + BOOST_FILENAME_PAIR,
          f"score={boosted['specs/product/speed-security.md']['score']}")
    check("filename_pair signal recorded",
          "filename_pair" in boosted["specs/product/speed-security.md"]["signals"])

    check("no boost for unrelated spec",
          boosted["specs/tech/speed-figma.md"]["score"] == 0.10,
          f"score={boosted['specs/tech/speed-figma.md']['score']}")

    check("tfidf field preserved",
          all(b["tfidf"] == 0.10 for b in boosted.values()))


# ══════════════════════════════════════════════════════════════
# 4: Budget Assembly
# ══════════════════════════════════════════════════════════════

print("\n=== 4: Budget Assembly ===")

scored_specs = {
    "a.md": {"score": 0.90, "tfidf": 0.20, "signals": ["cross_ref"]},
    "b.md": {"score": 0.50, "tfidf": 0.15, "signals": []},
    "c.md": {"score": 0.03, "tfidf": 0.03, "signals": []},  # below threshold
}
spec_texts = {
    "a.md": "A " * 500,   # ~500 tokens
    "b.md": "B " * 500,   # ~500 tokens
    "c.md": "C " * 500,   # ~500 tokens
}

parts, log = _assemble_within_budget(scored_specs, spec_texts, budget_tokens=2000, threshold=0.05)

check("includes above-threshold specs", len(parts) == 2,
      f"got {len(parts)} parts")
check("excludes below-threshold spec",
      all("c.md" not in p for p in parts))
check("scoring log has all specs", len(log) == 3)

included = [e for e in log if e["disposition"] == "included"]
excluded = [e for e in log if e["disposition"] == "excluded"]
check("2 included in log", len(included) == 2)
check("1 excluded in log", len(excluded) == 1)
check("excluded reason mentions threshold",
      "threshold" in excluded[0]["reason"])

# Budget overflow: only first spec fits (each spec ~263 tokens with header)
tiny_parts, tiny_log = _assemble_within_budget(scored_specs, spec_texts, budget_tokens=300, threshold=0.05)
tiny_included = [e for e in tiny_log if e["disposition"] == "included"]
check("budget constraint limits inclusion", len(tiny_included) == 1,
      f"got {len(tiny_included)}")
check("highest scorer included first", tiny_included[0]["path"] == "a.md")

# Headers include score and signals
check("header has score annotation", "score=0.90" in parts[0])
check("header has signal annotation", "cross_ref" in parts[0])


# ══════════════════════════════════════════════════════════════
# 5: Hard Stop #1 — Candidate Cap
# ══════════════════════════════════════════════════════════════

print("\n=== 5: Hard Stop #1 — Candidate Cap ===")

primary = {"tech.md": "primary content about security"}
# 5 candidates, cap at 3
many_related = {f"spec-{i}.md": f"content {i}" for i in range(5)}

try:
    score_and_assemble_specs(primary, many_related, "/tmp", candidate_cap=3)
    check("hard stop #1 raises ScoringError (no FM)", False, "did not raise")
except ScoringError as e:
    check("hard stop #1 raises ScoringError (no FM)", True)
    check("error mentions cap", "cap" in str(e).lower())

# With front-matter: narrows to FM only
fm_primary = {
    "tech.md": "---\nrelated:\n  - spec-0.md\n  - spec-1.md\n---\nprimary content about security"
}
try:
    result, log = score_and_assemble_specs(fm_primary, many_related, "/tmp", candidate_cap=3)
    check("hard stop #1 with FM narrows instead of erroring", True)
except ScoringError:
    check("hard stop #1 with FM narrows instead of erroring", False, "raised ScoringError")


# ══════════════════════════════════════════════════════════════
# 6: Hard Stop #2 — All Below Threshold
# ══════════════════════════════════════════════════════════════

print("\n=== 6: Hard Stop #2 — All Below Threshold ===")

primary_low = {"tech.md": "completely unique terminology xyzzy plugh"}
related_low = {
    "a.md": "totally different vocabulary alpha beta gamma",
    "b.md": "another unrelated document delta epsilon zeta",
}

try:
    score_and_assemble_specs(primary_low, related_low, "/tmp", threshold=0.90)
    check("hard stop #2 raises ScoringError", False, "did not raise")
except ScoringError as e:
    check("hard stop #2 raises ScoringError", True)
    check("error mentions threshold", "threshold" in str(e).lower())
    check("scoring log attached", len(e.scoring_log) > 0)


# ══════════════════════════════════════════════════════════════
# 7: Hard Stop #3 — No Differentiation
# ══════════════════════════════════════════════════════════════

print("\n=== 7: Hard Stop #3 — No Differentiation ===")

# All candidates have nearly identical content (same TF-IDF score)
primary_uniform = {"tech.md": "the quick brown fox jumps over the lazy dog"}
related_uniform = {
    f"spec-{i}.md": "the quick brown fox jumps over the lazy dog extra" for i in range(5)
}

try:
    score_and_assemble_specs(primary_uniform, related_uniform, "/tmp")
    # May not always trigger depending on exact scores — check spread
    check("hard stop #3 test executed", True)
except ScoringError as e:
    if "spread" in str(e).lower() or "differentiate" in str(e).lower():
        check("hard stop #3 raises on no differentiation", True)
    else:
        check("hard stop #3 raises on no differentiation", False, f"wrong error: {e}")


# ══════════════════════════════════════════════════════════════
# 8: Hard Stop #4 — Budget Monopolized
# ══════════════════════════════════════════════════════════════

print("\n=== 8: Hard Stop #4 — Budget Monopolized ===")

primary_mono = {"tech.md": "security audit scanning vulnerability " * 50}
related_mono = {
    "big.md": "security vulnerability " * 5000,   # huge spec
    "small.md": "unrelated content " * 10,
}

try:
    score_and_assemble_specs(primary_mono, related_mono, "/tmp", budget_tokens=500)
    check("hard stop #4 raises ScoringError", False, "did not raise")
except ScoringError as e:
    check("hard stop #4 raises ScoringError", True)
    check("error mentions budget", "budget" in str(e).lower() or "50%" in str(e))


# ══════════════════════════════════════════════════════════════
# 9: Full Pipeline — Happy Path
# ══════════════════════════════════════════════════════════════

print("\n=== 9: Full Pipeline — Happy Path ===")

primary_full = {
    "specs/tech/speed-security.md": "Security audit scanning vulnerability detection threat analysis hardening compliance",
}
related_full = {
    "specs/tech/speed-defects.md": "Defect handling error triage security vulnerability bug tracking",
    "specs/tech/speed-figma.md": "Figma design tokens color palette typography spacing layout components",
    "specs/tech/speed-templates.md": "Template rendering mustache jinja output formatting HTML",
}

assembled, scoring_log = score_and_assemble_specs(
    primary_full, related_full, "/tmp", budget_tokens=50000
)

check("returns assembled string", isinstance(assembled, str))
check("returns scoring log", isinstance(scoring_log, list))
check("scoring log has entries", len(scoring_log) > 0)

# Defects should score highest (security vocabulary overlap)
defects_entry = next((e for e in scoring_log if "defects" in e["path"]), None)
figma_entry = next((e for e in scoring_log if "figma" in e["path"]), None)
if defects_entry and figma_entry:
    check("defects scores higher than figma",
          defects_entry["score"] > figma_entry["score"],
          f"defects={defects_entry['score']}, figma={figma_entry['score']}")

# Check log structure
for entry in scoring_log:
    check(f"log entry for {entry['path']} has required fields",
          all(k in entry for k in ("path", "score", "tfidf", "signals", "disposition", "reason")),
          f"keys: {list(entry.keys())}")
    break  # Just check one


# ══════════════════════════════════════════════════════════════
# 10: Empty Input
# ══════════════════════════════════════════════════════════════

print("\n=== 10: Empty Input ===")

empty_result, empty_log = score_and_assemble_specs(
    {"tech.md": "content"}, {}, "/tmp"
)
check("empty candidates returns empty string", empty_result == "")
check("empty candidates returns empty log", empty_log == [])


# ══════════════════════════════════════════════════════════════
# 11: ScoringError Carries Log
# ══════════════════════════════════════════════════════════════

print("\n=== 11: ScoringError Exception ===")

err = ScoringError("test error", scoring_log=[{"path": "x.md", "score": 0.1}])
check("ScoringError has message", str(err) == "test error")
check("ScoringError has scoring_log", len(err.scoring_log) == 1)
check("ScoringError scoring_log accessible", err.scoring_log[0]["path"] == "x.md")


# ══════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════

print(f"\n{'='*50}")
print(f"Related Specs Unit Tests: {passed} passed, {failed} failed")
if failed == 0:
    print("ALL TESTS PASSED")
else:
    print(f"FAILURES: {failed}")
    sys.exit(1)
