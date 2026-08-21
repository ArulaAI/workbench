#!/usr/bin/env python3
"""Validation harness for Step 4: Verify Findings.

Runs the proposed Step 4 implementation against REAL plan-verification.log
data from speed-defects, speed-security, and find-your-tribe features.
Validates that the output matches the spec's goals:

  G1: drifted requirements → verify_finding (finding_type=spec_drift), weight 2.0
  G2: missing requirements → verify_finding (finding_type=missing_requirement), weight 2.0
  G3: partial requirements → verify_finding (finding_type=partial_requirement), weight 1.0
  G4: partial + uncertain=true → detail["uncertain"] is True
  G5: covered requirements → no observation
  G6: critical_failures → verify_finding (finding_type=critical_failure), weight 2.0
  G7: semantic_drift → verify_finding (finding_type=spec_drift), weight 2.0
  G8: recommendations → verify_finding (finding_type=recommendation), weight 1.0
  G9: contract_issues → verify_finding (finding_type=contract_issue), weight 1.5
  G10: All observations have task_id="*" and source="verifier"
  G11: Empty/missing JSON → warning, no observations

Usage:
  python tests/validate_step4.py
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
# Proposed Step 4 implementation (matches tech spec)
# ---------------------------------------------------------------------------

def _step4_verify_findings(feature: str, verify_json_path: Path | None,
                           result: ExtractResult) -> None:
    """Step 4: Extract verify findings from pre-parsed plan-verification JSON."""
    if not verify_json_path or not verify_json_path.exists():
        result.warnings.append("No plan-verification data available")
        return

    data = _read_json(verify_json_path)
    if not isinstance(data, dict):
        result.warnings.append("Empty or invalid verify JSON")
        return

    # Process spec_requirements: drifted, missing, AND partial
    for req in data.get("spec_requirements", []):
        if not isinstance(req, dict):
            continue
        status = req.get("status", "")
        if status in ("drifted", "missing", "partial"):
            if status == "partial":
                finding_type = "partial_requirement"
            elif status == "drifted":
                finding_type = "spec_drift"
            else:
                finding_type = "missing_requirement"

            detail = {
                "finding_type": finding_type,
                "requirement": req.get("requirement", req.get("spec_quote", "")),
                "status": status,
                "spec_location": req.get("spec_section", ""),
                "analysis": req.get("notes", req.get("evidence", "")),
                "uncertain": req.get("uncertain", False),
            }
            result.observations.append(
                _make_obs(feature, "verifier", "*", "verify_finding", detail,
                          weight=1.0 if status == "partial" else None)
            )

    # Process critical_failures
    for failure in data.get("critical_failures", []):
        if isinstance(failure, str):
            detail = {
                "finding_type": "critical_failure",
                "requirement": failure,
                "status": "failed",
                "spec_location": "",
                "analysis": "",
            }
        elif isinstance(failure, dict):
            detail = {
                "finding_type": "critical_failure",
                "requirement": failure.get("requirement", failure.get("description", "")),
                "status": "failed",
                "spec_location": failure.get("spec_section", ""),
                "analysis": failure.get("analysis", failure.get("evidence", "")),
            }
        else:
            continue
        result.observations.append(
            _make_obs(feature, "verifier", "*", "verify_finding", detail)
        )

    # Process semantic_drift
    for drift in data.get("semantic_drift", []):
        if not isinstance(drift, dict):
            continue
        detail = {
            "finding_type": "spec_drift",
            "requirement": drift.get("requirement", drift.get("area", "")),
            "status": "drifted",
            "spec_location": drift.get("spec_section", ""),
            "analysis": drift.get("risk", drift.get("analysis", "")),
        }
        result.observations.append(
            _make_obs(feature, "verifier", "*", "verify_finding", detail)
        )

    # Process recommendations
    for rec in data.get("recommendations", []):
        if not isinstance(rec, str):
            continue
        detail = {
            "finding_type": "recommendation",
            "requirement": rec,
            "status": "suggested",
            "spec_location": "",
            "analysis": "",
        }
        result.observations.append(
            _make_obs(feature, "verifier", "*", "verify_finding", detail,
                      weight=1.0)
        )

    # Process contract_issues
    for issue in data.get("contract_issues", []):
        if not isinstance(issue, dict):
            continue
        detail = {
            "finding_type": "contract_issue",
            "requirement": issue.get("description", ""),
            "status": issue.get("type", "unknown"),
            "spec_location": "",
            "analysis": "",
        }
        result.observations.append(
            _make_obs(feature, "verifier", "*", "verify_finding", detail,
                      weight=1.5)
        )


# ---------------------------------------------------------------------------
# Helper: parse JSON from markdown-wrapped log files
# ---------------------------------------------------------------------------

def parse_verification_log(log_path: Path) -> dict | None:
    """Extract JSON block from a plan-verification.log file."""
    text = log_path.read_text()
    m = re.search(r'```json\s*\n(.*?)\n```', text, re.DOTALL)
    if not m:
        return None
    return json.loads(m.group(1))


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
# Scenario 1: speed-defects (1 partial+uncertain, 3 semantic_drift,
#              2 contract_issues, 6 recommendations, 0 critical_failures)
# ===========================================================================

print("\n═══ Scenario 1: speed-defects (real data) ═══")

defects_log = Path(".speed/features/speed-defects/logs/plan-verification.log")
if not defects_log.exists():
    print("  SKIP: speed-defects log not found")
else:
    defects_data = parse_verification_log(defects_log)
    assert defects_data is not None, "Failed to parse speed-defects log"

    # Write pre-parsed JSON to temp file (simulating bash bridge)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(defects_data, f)
        defects_tmp = Path(f.name)

    result = ExtractResult()
    _step4_verify_findings("speed-defects", defects_tmp, result)
    defects_tmp.unlink()

    obs = result.observations
    by_type = {}
    for o in obs:
        ft = o.detail["finding_type"]
        by_type.setdefault(ft, []).append(o)

    # Current code extracts: 0 drifted/missing reqs + 3 semantic_drift = 3 observations
    # New code adds: 1 partial + 6 recommendations + 2 contract_issues = 9 new
    # Total = 3 + 9 = 12
    check("G5: 18 covered requirements produce nothing",
          all(o.detail.get("status") != "covered" for o in obs))

    check("G3: 1 partial requirement extracted",
          len(by_type.get("partial_requirement", [])) == 1)

    partial = by_type.get("partial_requirement", [None])[0]
    if partial:
        check("G3: partial weight is 1.0 (explicit override of _WEIGHTS 2.0)",
              partial.weight == 1.0)
        check("G4: partial+uncertain has uncertain=True in detail",
              partial.detail.get("uncertain") is True)
        check("G3: partial requirement text matches 80% triage accuracy",
              "80%" in partial.detail["requirement"])

    check("G7: 3 semantic_drift items → 3 spec_drift observations",
          len([o for o in by_type.get("spec_drift", [])
               if "semantic_drift" not in str(o.detail.get("status", ""))
               ]) == 3)
    for sd in by_type.get("spec_drift", []):
        check(f"G7: semantic_drift weight is 2.0 (inherited from _WEIGHTS)",
              sd.weight == 2.0)

    check("G9: 2 contract_issues extracted",
          len(by_type.get("contract_issue", [])) == 2)
    for ci in by_type.get("contract_issue", []):
        check(f"G9: contract_issue weight is 1.5",
              ci.weight == 1.5)
        check(f"G9: contract_issue has description in requirement",
              len(ci.detail["requirement"]) > 0)

    check("G8: 6 recommendations extracted",
          len(by_type.get("recommendation", [])) == 6)
    for rec in by_type.get("recommendation", []):
        check(f"G8: recommendation weight is 1.0",
              rec.weight == 1.0)
        check(f"G8: recommendation status is 'suggested'",
              rec.detail["status"] == "suggested")

    check("G6: 0 critical_failures → 0 critical_failure observations",
          len(by_type.get("critical_failure", [])) == 0)

    check("G10: all observations have task_id='*'",
          all(o.task_id == "*" for o in obs))
    check("G10: all observations have source='verifier'",
          all(o.stage == "verifier" for o in obs))
    check("G10: all observations have type='verify_finding'",
          all(o.observation_type == "verify_finding" for o in obs))

    total = 1 + 3 + 2 + 6  # partial + semantic_drift + contract_issues + recommendations
    check(f"Total: {total} observations (was 3, now {total})",
          len(obs) == total)


# ===========================================================================
# Scenario 2: speed-security (1 partial, 1 drifted, 2 missing,
#              1 semantic_drift, 1 contract_issue, 5 recommendations)
# ===========================================================================

print("\n═══ Scenario 2: speed-security (real data) ═══")

security_log = Path(".speed/features/speed-security/logs/plan-verification.log")
if not security_log.exists():
    print("  SKIP: speed-security log not found")
else:
    security_data = parse_verification_log(security_log)
    assert security_data is not None, "Failed to parse speed-security log"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(security_data, f)
        security_tmp = Path(f.name)

    result = ExtractResult()
    _step4_verify_findings("speed-security", security_tmp, result)
    security_tmp.unlink()

    obs = result.observations
    by_type = {}
    for o in obs:
        ft = o.detail["finding_type"]
        by_type.setdefault(ft, []).append(o)

    check("G1: 1 drifted requirement → spec_drift",
          len([o for o in by_type.get("spec_drift", [])
               if o.detail.get("status") == "drifted"]) >= 1)

    drifted = [o for o in by_type.get("spec_drift", [])
               if o.detail.get("status") == "drifted"]
    for d in drifted:
        check("G1: drifted weight is 2.0",
              d.weight == 2.0)

    check("G2: 2 missing requirements → missing_requirement",
          len(by_type.get("missing_requirement", [])) == 2)
    for m in by_type.get("missing_requirement", []):
        check("G2: missing weight is 2.0",
              m.weight == 2.0)

    check("G3: 1 partial requirement → partial_requirement",
          len(by_type.get("partial_requirement", [])) == 1)
    sec_partial = by_type.get("partial_requirement", [None])[0]
    if sec_partial:
        check("G3: partial weight is 1.0",
              sec_partial.weight == 1.0)
        # speed-security partial does NOT have uncertain=true
        check("G4: partial without uncertain flag → uncertain=False",
              sec_partial.detail.get("uncertain") is False)

    check("G7: 1 semantic_drift → spec_drift",
          len(by_type.get("spec_drift", [])) >= 2)  # 1 drifted req + 1 semantic_drift

    check("G9: 1 contract_issue extracted",
          len(by_type.get("contract_issue", [])) == 1)

    check("G8: 5 recommendations extracted",
          len(by_type.get("recommendation", [])) == 5)

    # Total: 1 drifted + 2 missing + 1 partial + 1 semantic_drift + 1 contract + 5 recs = 11
    total_sec = 1 + 2 + 1 + 1 + 1 + 5
    check(f"Total: {total_sec} observations",
          len(obs) == total_sec)


# ===========================================================================
# Scenario 3: find-your-tribe f10-rich-feed (all covered, 5 recs, 1 contract)
# ===========================================================================

print("\n═══ Scenario 3: find-your-tribe f10-rich-feed (real data) ═══")

fyt_base = Path("/Users/sanjay.kotagiri/Documents/code/tmp/find-your-tribe/.speed/features")
feed_log = fyt_base / "f10-rich-feed" / "logs" / "plan-verification.log"
if not feed_log.exists():
    print("  SKIP: f10-rich-feed log not found")
else:
    feed_data = parse_verification_log(feed_log)
    assert feed_data is not None, "Failed to parse f10-rich-feed log"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(feed_data, f)
        feed_tmp = Path(f.name)

    result = ExtractResult()
    _step4_verify_findings("f10-rich-feed", feed_tmp, result)
    feed_tmp.unlink()

    obs = result.observations
    by_type = {}
    for o in obs:
        ft = o.detail["finding_type"]
        by_type.setdefault(ft, []).append(o)

    check("G5: all 16 covered requirements produce nothing",
          len(by_type.get("spec_drift", [])) == 0
          and len(by_type.get("missing_requirement", [])) == 0
          and len(by_type.get("partial_requirement", [])) == 0)

    check("G8: 5 recommendations extracted",
          len(by_type.get("recommendation", [])) == 5)

    check("G9: 1 contract_issue extracted",
          len(by_type.get("contract_issue", [])) == 1)

    check("G7: 0 semantic_drift → 0 spec_drift observations",
          len(by_type.get("spec_drift", [])) == 0)

    # Total: 5 recs + 1 contract = 6
    # Old code: 0 observations (nothing drifted/missing, no semantic_drift)
    check("Total: 6 observations (was 0, now 6)",
          len(obs) == 6)


# ===========================================================================
# Scenario 4: find-your-tribe f9-profile-completeness (all covered, 2 recs,
#              1 contract, 0 semantic_drift)
# ===========================================================================

print("\n═══ Scenario 4: find-your-tribe f9-profile-completeness (real data) ═══")

profile_log = fyt_base / "f9-profile-completeness" / "logs" / "plan-verification.log"
if not profile_log.exists():
    print("  SKIP: f9-profile-completeness log not found")
else:
    profile_data = parse_verification_log(profile_log)
    assert profile_data is not None, "Failed to parse f9-profile-completeness log"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(profile_data, f)
        profile_tmp = Path(f.name)

    result = ExtractResult()
    _step4_verify_findings("f9-profile-completeness", profile_tmp, result)
    profile_tmp.unlink()

    obs = result.observations
    by_type = {}
    for o in obs:
        ft = o.detail["finding_type"]
        by_type.setdefault(ft, []).append(o)

    check("G5: all 15 covered requirements produce nothing",
          len(by_type.get("spec_drift", [])) == 0
          and len(by_type.get("missing_requirement", [])) == 0
          and len(by_type.get("partial_requirement", [])) == 0)

    check("G8: 2 recommendations extracted",
          len(by_type.get("recommendation", [])) == 2)

    check("G9: 1 contract_issue extracted",
          len(by_type.get("contract_issue", [])) == 1)

    # Total: 2 recs + 1 contract = 3
    check("Total: 3 observations (was 0, now 3)",
          len(obs) == 3)


# ===========================================================================
# Scenario 5: Edge cases — empty, missing, no JSON
# ===========================================================================

print("\n═══ Scenario 5: Edge cases ═══")

# 5a: None path
result = ExtractResult()
_step4_verify_findings("test", None, result)
check("G11: None path → warning",
      len(result.warnings) == 1 and "No plan-verification" in result.warnings[0])
check("G11: None path → 0 observations",
      len(result.observations) == 0)

# 5b: Non-existent path
result = ExtractResult()
_step4_verify_findings("test", Path("/nonexistent/verify.json"), result)
check("G11: nonexistent path → warning",
      len(result.warnings) == 1)

# 5c: Empty JSON file
with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
    f.write("")
    empty_tmp = Path(f.name)
result = ExtractResult()
_step4_verify_findings("test", empty_tmp, result)
empty_tmp.unlink()
check("G11: empty file → warning",
      len(result.warnings) == 1 and "Empty or invalid" in result.warnings[0])
check("G11: empty file → 0 observations",
      len(result.observations) == 0)

# 5d: Valid JSON with empty arrays (passing verification, nothing to extract)
with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
    json.dump({
        "status": "pass",
        "spec_requirements": [],
        "critical_failures": [],
        "semantic_drift": [],
        "recommendations": [],
        "contract_issues": [],
    }, f)
    clean_tmp = Path(f.name)
result = ExtractResult()
_step4_verify_findings("test", clean_tmp, result)
clean_tmp.unlink()
check("G11: all-empty arrays → 0 observations, 0 warnings",
      len(result.observations) == 0 and len(result.warnings) == 0)


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
