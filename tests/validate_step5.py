#!/usr/bin/env python3
"""Validation harness for Step 5: Coherence Issues.

Runs the proposed Step 5 implementation against REAL coherence.log data
from speed-security (markdown) and f9-profile-completeness (JSON).
Validates that the output matches the spec's goals:

  G1: interface_mismatches → coherence_issue (issue_type=interface_mismatch), weight 2.0
  G2: schema_inconsistencies → coherence_issue (issue_type=schema_inconsistency), weight 2.0
  G3: missing_connections → coherence_issue (issue_type=missing_connection), weight 2.0
  G4: critical_issues → coherence_issue (issue_type=critical_issue), weight 2.5
  G5: contract_gaps (missing/partial) → coherence_issue (issue_type=contract_gap), weight 2.0
  G6: contract_gaps (satisfied) → no observation
  G7: duplicates → coherence_issue (issue_type=duplicate), weight 2.0
  G8: recommendations → coherence_issue (issue_type=recommendation), weight 1.0
  G9: Markdown fallback: status=fail → markdown_summary with critical/major counts, weight 2.5
  G10: Markdown fallback: status=pass → markdown_summary, weight 1.0
  G11: All observations have task_id="*" and source="coherence"
  G12: Empty/missing JSON → warning, no observations

Usage:
  python tests/validate_step5.py
"""

import json
import re
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

# ---------------------------------------------------------------------------
# Minimal reproduction of extract.py types (self-contained, no imports)
# ---------------------------------------------------------------------------

@dataclass
class Observation:
    id: str
    feature: str
    stage: str
    task_id: str
    timestamp: str
    observation_type: str
    detail: dict
    weight: float

@dataclass
class ExtractResult:
    observations: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)

_WEIGHTS: dict[str, float] = {
    "retry": 3.0,
    "reviewer_finding": 1.5,
    "human_override": 2.5,
    "guardian_verdict": 2.0,
    "gate_failure": 2.0,
    "context_miss": 1.5,
    "context_waste": 0.5,
    "decomposition_miss": 2.0,
    "convention_violation": 1.5,
    "verify_finding": 2.0,
    "coherence_issue": 2.0,
    "security_finding": 1.5,
    "success": 0.5,
    "pattern_match": 2.0,
    "unattributed_changes": 1.0,
    "agent_concern": 1.0,
}

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def observation_id(feature, task_id, stage, obs_type, detail) -> str:
    canonical = json.dumps({
        "feature": feature, "task_id": task_id, "stage": stage,
        "observation_type": obs_type, "detail": detail,
    }, sort_keys=True)
    return sha256(canonical.encode()).hexdigest()[:16]

def _make_obs(feature, stage, task_id, obs_type, detail, weight=None):
    w = weight if weight is not None else _WEIGHTS.get(obs_type, 1.0)
    return Observation(
        id=observation_id(feature, task_id, stage, obs_type, detail),
        feature=feature, stage=stage, task_id=task_id,
        timestamp=_now_iso(), observation_type=obs_type,
        detail=detail, weight=w,
    )

def _read_json(path: Path) -> dict | list | None:
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


# ---------------------------------------------------------------------------
# Proposed Step 5 implementation (matches tech spec)
# ---------------------------------------------------------------------------

def _step5_coherence_markdown_fallback(feature: str, raw: str,
                                        result: ExtractResult) -> None:
    """Extract minimal coherence signal from markdown when JSON parse fails."""
    status = "unknown"
    if "**Status: FAIL**" in raw or "Verdict: **FAIL**" in raw:
        status = "fail"
    elif "**Status: PASS**" in raw or "Verdict: **PASS**" in raw:
        status = "pass"

    critical_count = 0
    major_count = 0
    in_critical = False
    in_major = False
    for line in raw.splitlines():
        stripped = line.strip()
        if "Critical Issues" in line or "What blocks" in line:
            in_critical = True
            in_major = False
        elif "Major Issues" in line:
            in_major = True
            in_critical = False
        elif stripped.startswith("###") or (stripped.startswith("##") and "Issues" not in stripped and "blocks" not in stripped.lower()):
            in_critical = False
            in_major = False
        elif stripped.startswith("|") and not stripped.startswith("| #") and not stripped.startswith("|--"):
            if in_critical:
                critical_count += 1
            elif in_major:
                major_count += 1
        elif re.match(r'^\d+\.\s', stripped):
            if in_critical:
                critical_count += 1
            elif in_major:
                major_count += 1

    if status == "unknown" and critical_count == 0 and major_count == 0:
        result.warnings.append("Coherence output is non-JSON and unparseable")
        return

    detail = {
        "issue_type": "markdown_summary",
        "description": (f"Coherence checker produced markdown instead of JSON. "
                        f"Status: {status}, {critical_count} critical, "
                        f"{major_count} major issues detected."),
        "severity": "critical" if status == "fail" else "info",
        "critical_count": critical_count,
        "major_count": major_count,
        "status": status,
    }
    weight = 2.5 if status == "fail" else 1.0
    result.observations.append(
        _make_obs(feature, "coherence", "*",
                  "coherence_issue", detail, weight=weight)
    )
    result.warnings.append(
        "Coherence output was markdown, not JSON. Only summary extracted."
    )


def _step5_coherence_issues(feature: str, coherence_json_path: Path | None,
                            result: ExtractResult) -> None:
    """Step 5: Extract coherence issues from pre-parsed coherence JSON."""
    if not coherence_json_path or not coherence_json_path.exists():
        result.warnings.append("No coherence data available")
        return

    data = _read_json(coherence_json_path)
    if not isinstance(data, dict):
        raw = coherence_json_path.read_text().strip()
        if raw:
            _step5_coherence_markdown_fallback(feature, raw, result)
        else:
            result.warnings.append("Empty or invalid coherence JSON")
        return

    # Existing 3 arrays
    issue_sources = [
        ("interface_mismatches", "interface_mismatch"),
        ("schema_inconsistencies", "schema_inconsistency"),
        ("missing_connections", "missing_connection"),
    ]

    for json_key, issue_type in issue_sources:
        for item in data.get(json_key, []):
            if not isinstance(item, dict):
                continue
            detail = {
                "issue_type": issue_type,
                "task_a": str(item.get("task_a", item.get("tasks", [""])[0] if isinstance(item.get("tasks"), list) and item.get("tasks") else "")),
                "task_b": str(item.get("task_b", item.get("tasks", ["", ""])[1] if isinstance(item.get("tasks"), list) and len(item.get("tasks", [])) > 1 else "")),
                "location_a": item.get("location_a", item.get("location", "")),
                "location_b": item.get("location_b", ""),
                "description": item.get("description", item.get("issue", "")),
                "severity": item.get("severity", "warning"),
            }
            result.observations.append(
                _make_obs(feature, "coherence", "*",
                          "coherence_issue", detail)
            )

    # New: critical_issues
    for issue_text in data.get("critical_issues", []):
        if not isinstance(issue_text, str) or not issue_text.strip():
            continue
        detail = {
            "issue_type": "critical_issue",
            "description": issue_text,
            "severity": "critical",
        }
        result.observations.append(
            _make_obs(feature, "coherence", "*",
                      "coherence_issue", detail, weight=2.5)
        )

    # New: contract_gaps (only missing/partial)
    for gap in data.get("contract_gaps", []):
        if not isinstance(gap, dict):
            continue
        status = gap.get("status", "")
        if status in ("missing", "partial"):
            detail = {
                "issue_type": "contract_gap",
                "description": gap.get("contract_item", ""),
                "status": status,
                "notes": gap.get("notes", ""),
                "severity": "major" if status == "missing" else "minor",
            }
            result.observations.append(
                _make_obs(feature, "coherence", "*",
                          "coherence_issue", detail, weight=2.0)
            )

    # New: duplicates
    for dup in data.get("duplicates", []):
        if not isinstance(dup, dict):
            continue
        detail = {
            "issue_type": "duplicate",
            "description": dup.get("description", ""),
            "locations": dup.get("locations", []),
            "severity": "major",
        }
        result.observations.append(
            _make_obs(feature, "coherence", "*",
                      "coherence_issue", detail)
        )

    # New: recommendations
    for rec in data.get("recommendations", []):
        if not isinstance(rec, str) or not rec.strip():
            continue
        detail = {
            "issue_type": "recommendation",
            "description": rec,
            "severity": "info",
        }
        result.observations.append(
            _make_obs(feature, "coherence", "*",
                      "coherence_issue", detail, weight=1.0)
        )


# ---------------------------------------------------------------------------
# Test infrastructure
# ---------------------------------------------------------------------------

passed = 0
failed = 0

def check(label, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f"  ✓ {label}")
    else:
        failed += 1
        print(f"  ✗ {label}")


# ===========================================================================
# Scenario 1: f9-profile-completeness (real JSON data)
#   0 interface_mismatches, 1 schema_inconsistency, 0 missing_connections,
#   0 critical_issues, 8 contract_gaps (all satisfied), 0 duplicates,
#   1 recommendation
# ===========================================================================

print("\n═══ Scenario 1: f9-profile-completeness (real JSON data) ═══")

fyt = Path("/Users/sanjay.kotagiri/Documents/code/tmp/find-your-tribe/.speed/features")
clog = fyt / "f9-profile-completeness" / "logs" / "coherence.log"
if not clog.exists():
    print("  SKIP: f9-profile-completeness coherence.log not found")
else:
    data = json.loads(clog.read_text())

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        tmp = Path(f.name)

    result = ExtractResult()
    _step5_coherence_issues("f9-profile-completeness", tmp, result)
    tmp.unlink()

    obs = result.observations
    by_type = {}
    for o in obs:
        it = o.detail["issue_type"]
        by_type.setdefault(it, []).append(o)

    check("G2: 1 schema_inconsistency extracted",
          len(by_type.get("schema_inconsistency", [])) == 1)

    si = by_type.get("schema_inconsistency", [None])[0]
    if si:
        check("G2: schema_inconsistency weight is 2.0",
              si.weight == 2.0)
        check("G2: schema_inconsistency has description",
              "completenessFields" in si.detail["description"])

    check("G6: 8 satisfied contract_gaps produce nothing",
          len(by_type.get("contract_gap", [])) == 0)

    check("G8: 1 recommendation extracted",
          len(by_type.get("recommendation", [])) == 1)
    rec = by_type.get("recommendation", [None])[0]
    if rec:
        check("G8: recommendation weight is 1.0",
              rec.weight == 1.0)
        check("G8: recommendation severity is info",
              rec.detail["severity"] == "info")

    check("G1: 0 interface_mismatches → 0 observations of that type",
          len(by_type.get("interface_mismatch", [])) == 0)
    check("G3: 0 missing_connections → 0 observations of that type",
          len(by_type.get("missing_connection", [])) == 0)
    check("G4: 0 critical_issues → 0 observations of that type",
          len(by_type.get("critical_issue", [])) == 0)
    check("G7: 0 duplicates → 0 observations of that type",
          len(by_type.get("duplicate", [])) == 0)

    # Total: 1 schema_inconsistency + 1 recommendation = 2
    # Old code produced: 1 (only schema_inconsistency)
    check("Total: 2 observations (was 1, now 2)",
          len(obs) == 2)

    check("G11: all observations have task_id='*'",
          all(o.task_id == "*" for o in obs))
    check("G11: all observations have source='coherence'",
          all(o.stage == "coherence" for o in obs))
    check("G11: all observations have type='coherence_issue'",
          all(o.observation_type == "coherence_issue" for o in obs))

    check("No warnings on valid JSON",
          len(result.warnings) == 0)


# ===========================================================================
# Scenario 2: speed-security (real markdown data — fallback path)
#   Status: FAIL, 3 critical issues in table, 3 major issues in table
# ===========================================================================

print("\n═══ Scenario 2: speed-security (real markdown fallback) ═══")

slog = Path(".speed/features/speed-security/logs/coherence.log")
if not slog.exists():
    print("  SKIP: speed-security coherence.log not found")
else:
    raw = slog.read_text()

    # Write raw markdown to temp file (simulating bash bridge failure)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write(raw)
        tmp = Path(f.name)

    result = ExtractResult()
    _step5_coherence_issues("speed-security", tmp, result)
    tmp.unlink()

    obs = result.observations
    check("G9: markdown fallback produces 1 observation",
          len(obs) == 1)

    if obs:
        o = obs[0]
        check("G9: issue_type is markdown_summary",
              o.detail["issue_type"] == "markdown_summary")
        check("G9: status is fail",
              o.detail["status"] == "fail")
        check("G9: critical_count is 3",
              o.detail["critical_count"] == 3)
        check("G9: major_count is 3",
              o.detail["major_count"] == 3)
        check("G9: weight is 2.5 for fail status",
              o.weight == 2.5)
        check("G9: severity is critical",
              o.detail["severity"] == "critical")
        check("G11: task_id='*'",
              o.task_id == "*")
        check("G11: source='coherence'",
              o.stage == "coherence")

    check("G9: warning about markdown extraction",
          any("markdown" in w.lower() for w in result.warnings))


# ===========================================================================
# Scenario 3: speed-security coherence-prev.json (also markdown, different
#   format — uses "Verdict: **FAIL**" and "What blocks integration")
# ===========================================================================

print("\n═══ Scenario 3: speed-security coherence-prev.json (markdown variant) ═══")

prev = Path(".speed/features/speed-security/logs/coherence-prev.json")
if not prev.exists():
    print("  SKIP: coherence-prev.json not found")
else:
    raw = prev.read_text()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write(raw)
        tmp = Path(f.name)

    result = ExtractResult()
    _step5_coherence_issues("speed-security", tmp, result)
    tmp.unlink()

    obs = result.observations
    check("Markdown variant: produces 1 observation",
          len(obs) == 1)

    if obs:
        o = obs[0]
        check("Markdown variant: status is fail",
              o.detail["status"] == "fail")
        check("Markdown variant: weight is 2.5",
              o.weight == 2.5)
        check("Markdown variant: critical_count >= 1",
              o.detail["critical_count"] >= 1)


# ===========================================================================
# Scenario 4: Synthetic JSON with all arrays populated
# ===========================================================================

print("\n═══ Scenario 4: Synthetic JSON — all arrays populated ═══")

synth_data = {
    "status": "fail",
    "summary": "Two critical issues found.",
    "interface_mismatches": [
        {"task_a": "1", "task_b": "3", "location_a": "src/api.ts:10",
         "location_b": "src/client.ts:20", "description": "Argument count mismatch",
         "severity": "critical"}
    ],
    "schema_inconsistencies": [
        {"description": "user_id vs owner_id", "locations": ["a.py:1", "b.py:2"],
         "severity": "major"}
    ],
    "missing_connections": [
        {"description": "Model not registered in __init__", "expected_in": "models/__init__.py",
         "severity": "major"}
    ],
    "critical_issues": [
        "Task 4 delivered nothing — lib/check.sh doesn't exist",
        "Task 12 missing entirely",
    ],
    "contract_gaps": [
        {"contract_item": "Auth middleware", "status": "missing", "notes": "No task creates it"},
        {"contract_item": "User model", "status": "satisfied", "notes": "Task 1 creates it"},
        {"contract_item": "Rate limiter", "status": "partial", "notes": "Config only, no enforcement"},
    ],
    "duplicates": [
        {"description": "formatDate implemented in both utils.ts and helpers.ts",
         "locations": ["src/utils.ts:45", "src/helpers.ts:12"]}
    ],
    "recommendations": [
        "Rename owner_id to user_id for consistency",
        "Register Model in __init__.py",
    ],
}

with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
    json.dump(synth_data, f)
    synth_tmp = Path(f.name)

result = ExtractResult()
_step5_coherence_issues("synth-feature", synth_tmp, result)
synth_tmp.unlink()

obs = result.observations
by_type = {}
for o in obs:
    it = o.detail["issue_type"]
    by_type.setdefault(it, []).append(o)

check("G1: 1 interface_mismatch",
      len(by_type.get("interface_mismatch", [])) == 1)
im = by_type.get("interface_mismatch", [None])[0]
if im:
    check("G1: interface_mismatch weight 2.0",
          im.weight == 2.0)
    check("G1: task_a and task_b populated",
          im.detail["task_a"] == "1" and im.detail["task_b"] == "3")

check("G2: 1 schema_inconsistency",
      len(by_type.get("schema_inconsistency", [])) == 1)

check("G3: 1 missing_connection",
      len(by_type.get("missing_connection", [])) == 1)

check("G4: 2 critical_issues",
      len(by_type.get("critical_issue", [])) == 2)
for ci in by_type.get("critical_issue", []):
    check("G4: critical_issue weight 2.5",
          ci.weight == 2.5)
    check("G4: critical_issue severity is critical",
          ci.detail["severity"] == "critical")

check("G5: 1 missing contract_gap (auth middleware)",
      len([g for g in by_type.get("contract_gap", [])
           if g.detail["status"] == "missing"]) == 1)
check("G5: 1 partial contract_gap (rate limiter)",
      len([g for g in by_type.get("contract_gap", [])
           if g.detail["status"] == "partial"]) == 1)
check("G6: satisfied contract_gap (user model) not extracted",
      len(by_type.get("contract_gap", [])) == 2)
for cg in by_type.get("contract_gap", []):
    check("G5: contract_gap weight 2.0",
          cg.weight == 2.0)

check("G7: 1 duplicate",
      len(by_type.get("duplicate", [])) == 1)
dup = by_type.get("duplicate", [None])[0]
if dup:
    check("G7: duplicate weight 2.0",
          dup.weight == 2.0)
    check("G7: duplicate has locations",
          len(dup.detail["locations"]) == 2)

check("G8: 2 recommendations",
      len(by_type.get("recommendation", [])) == 2)
for r in by_type.get("recommendation", []):
    check("G8: recommendation weight 1.0",
          r.weight == 1.0)

# Total: 1+1+1+2+2+1+2 = 10
check("Total: 10 observations",
      len(obs) == 10)

check("G11: all task_id='*'",
      all(o.task_id == "*" for o in obs))
check("G11: all source='coherence'",
      all(o.stage == "coherence" for o in obs))


# ===========================================================================
# Scenario 5: Synthetic markdown — pass status
# ===========================================================================

print("\n═══ Scenario 5: Synthetic markdown — PASS status ═══")

pass_md = """## Summary

**Status: PASS** (zero issues)

### What Composes Correctly

All tasks compose correctly at their boundaries.
"""

with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
    f.write(pass_md)
    pass_tmp = Path(f.name)

result = ExtractResult()
_step5_coherence_issues("pass-feature", pass_tmp, result)
pass_tmp.unlink()

obs = result.observations
check("G10: pass markdown produces 1 observation",
      len(obs) == 1)
if obs:
    check("G10: status is pass",
          obs[0].detail["status"] == "pass")
    check("G10: weight is 1.0 for pass",
          obs[0].weight == 1.0)
    check("G10: critical_count is 0",
          obs[0].detail["critical_count"] == 0)
    check("G10: major_count is 0",
          obs[0].detail["major_count"] == 0)


# ===========================================================================
# Scenario 6: Edge cases
# ===========================================================================

print("\n═══ Scenario 6: Edge cases ═══")

# 6a: None path
result = ExtractResult()
_step5_coherence_issues("test", None, result)
check("G12: None path → warning",
      len(result.warnings) == 1 and "No coherence data" in result.warnings[0])
check("G12: None path → 0 observations",
      len(result.observations) == 0)

# 6b: Non-existent path
result = ExtractResult()
_step5_coherence_issues("test", Path("/nonexistent/coherence.json"), result)
check("G12: nonexistent path → warning",
      len(result.warnings) == 1)

# 6c: Empty file
with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
    f.write("")
    empty_tmp = Path(f.name)
result = ExtractResult()
_step5_coherence_issues("test", empty_tmp, result)
empty_tmp.unlink()
check("G12: empty file → warning",
      len(result.warnings) == 1 and "Empty or invalid" in result.warnings[0])
check("G12: empty file → 0 observations",
      len(result.observations) == 0)

# 6d: Valid JSON with all empty arrays
with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
    json.dump({
        "status": "pass", "summary": "Clean.",
        "interface_mismatches": [], "schema_inconsistencies": [],
        "missing_connections": [], "critical_issues": [],
        "contract_gaps": [], "duplicates": [], "recommendations": [],
    }, f)
    clean_tmp = Path(f.name)
result = ExtractResult()
_step5_coherence_issues("test", clean_tmp, result)
clean_tmp.unlink()
check("G12: all-empty arrays → 0 observations, 0 warnings",
      len(result.observations) == 0 and len(result.warnings) == 0)

# 6e: Unparseable non-JSON, non-markdown
with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
    f.write("this is just random text with no structure")
    junk_tmp = Path(f.name)
result = ExtractResult()
_step5_coherence_issues("test", junk_tmp, result)
junk_tmp.unlink()
check("G12: unparseable text → warning",
      any("unparseable" in w.lower() for w in result.warnings))
check("G12: unparseable text → 0 observations",
      len(result.observations) == 0)

# 6f: Non-string critical_issue skipped
with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
    json.dump({"critical_issues": [42, "", "Valid issue"]}, f)
    mixed_tmp = Path(f.name)
result = ExtractResult()
_step5_coherence_issues("test", mixed_tmp, result)
mixed_tmp.unlink()
check("G4: non-string and empty critical_issues skipped, valid one kept",
      len(result.observations) == 1
      and result.observations[0].detail["description"] == "Valid issue")

# 6g: Idempotency
with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
    json.dump({
        "schema_inconsistencies": [
            {"description": "field mismatch", "severity": "minor"}
        ],
        "recommendations": ["Fix it"],
    }, f)
    idem_tmp = Path(f.name)
r1 = ExtractResult()
_step5_coherence_issues("test", idem_tmp, r1)
r2 = ExtractResult()
_step5_coherence_issues("test", idem_tmp, r2)
idem_tmp.unlink()
check("Idempotency: same IDs on repeated runs",
      [o.id for o in r1.observations] == [o.id for o in r2.observations])


# ===========================================================================
# Summary
# ===========================================================================

print(f"\n{'═' * 50}")
print(f"Results: {passed} passed, {failed} failed out of {passed + failed}")
if failed > 0:
    print("FAIL")
    sys.exit(1)
else:
    print("ALL CHECKS PASSED")
    sys.exit(0)
