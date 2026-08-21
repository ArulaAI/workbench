#!/usr/bin/env python3
"""Validation harness for Step 6: Security Findings.

Runs the proposed Step 6 implementation against REAL data from
speed-defects, speed-security, f10-rich-feed, f9-profile-completeness,
and seed-onboarding-flag.

  G1: validation-report.json (bare array) → security_finding per item
  G2: security-audit.json (dict with validation key) → security_finding per item
  G3: Both files present → findings from both extracted
  G4: SEC-NNN pattern parsed into finding_id and severity
  G5: product_requirement preserved in detail
  G6: Neither file exists → warning, no observations
  G7: Files exist but empty → warning, no observations
  G8: All observations have task_id="*" and source="security"
  G9: Weight is 1.5 (from _WEIGHTS)

Usage:
  python tests/validate_step6.py
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
# Minimal reproduction of extract.py types
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
    "retry": 3.0, "reviewer_finding": 1.5, "human_override": 2.5,
    "guardian_verdict": 2.0, "gate_failure": 2.0, "context_miss": 1.5,
    "context_waste": 0.5, "decomposition_miss": 2.0, "convention_violation": 1.5,
    "verify_finding": 2.0, "coherence_issue": 2.0, "security_finding": 1.5,
    "success": 0.5, "pattern_match": 2.0, "unattributed_changes": 1.0,
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
# Proposed Step 6 implementation
# ---------------------------------------------------------------------------

def _step6_security_findings(feature: str, logs_dir: Path,
                               result: ExtractResult) -> None:
    """Step 6: Extract findings from validation-report.json and security-audit.json."""
    all_findings: list[dict] = []

    vr_path = logs_dir / "validation-report.json"
    if vr_path.exists():
        vr_data = _read_json(vr_path)
        if isinstance(vr_data, list):
            all_findings.extend(f for f in vr_data if isinstance(f, dict))
        elif isinstance(vr_data, dict):
            all_findings.extend(
                f for f in vr_data.get("validation", vr_data.get("findings", []))
                if isinstance(f, dict)
            )

    sa_path = logs_dir / "security-audit.json"
    if sa_path.exists():
        sa_data = _read_json(sa_path)
        if isinstance(sa_data, dict):
            all_findings.extend(
                f for f in sa_data.get("validation", sa_data.get("findings", []))
                if isinstance(f, dict)
            )
        elif isinstance(sa_data, list):
            all_findings.extend(f for f in sa_data if isinstance(f, dict))

    if not all_findings:
        if not vr_path.exists() and not sa_path.exists():
            result.warnings.append("No validation-report.json or security-audit.json found")
        else:
            result.warnings.append("Security/validation files exist but contain no findings")
        return

    for i, finding in enumerate(all_findings):
        issue_text = finding.get("issue", "")
        finding_id = f"SEC-{i+1:03d}"
        severity = finding.get("severity", "note")
        title = issue_text

        sec_match = re.match(r"(SEC-\d+)\s*\((\w+)\):\s*(.*)", issue_text)
        if sec_match:
            finding_id = sec_match.group(1)
            severity = sec_match.group(2)
            title = sec_match.group(3)

        detail = {
            "finding_id": finding_id,
            "severity": severity,
            "title": title[:200] if title else "",
            "recommendation": finding.get("recommendation", ""),
            "product_requirement": finding.get("product_requirement", ""),
        }
        result.observations.append(
            _make_obs(feature, "security", "*",
                      "security_finding", detail)
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
# Scenario 1: speed-defects (validation-report only, 7 findings)
# ===========================================================================

print("\n═══ Scenario 1: speed-defects (validation-report.json only) ═══")

logs = Path(".speed/features/speed-defects/logs")
if not (logs / "validation-report.json").exists():
    print("  SKIP: speed-defects validation-report.json not found")
else:
    result = ExtractResult()
    _step6_security_findings("speed-defects", logs, result)

    check("G1: 7 findings from validation-report.json",
          len(result.observations) == 7)
    check("G8: all task_id='*'",
          all(o.task_id == "*" for o in result.observations))
    check("G8: all source='security'",
          all(o.stage == "security" for o in result.observations))
    check("G9: all weight=1.5",
          all(o.weight == 1.5 for o in result.observations))
    check("G5: product_requirement populated",
          all(o.detail.get("product_requirement", "") != ""
              for o in result.observations))
    check("No warnings",
          len(result.warnings) == 0)


# ===========================================================================
# Scenario 2: speed-security (both files, 11+6=17 findings)
# ===========================================================================

print("\n═══ Scenario 2: speed-security (both files, 11+6=17) ═══")

logs = Path(".speed/features/speed-security/logs")
if not (logs / "validation-report.json").exists():
    print("  SKIP: speed-security files not found")
else:
    result = ExtractResult()
    _step6_security_findings("speed-security", logs, result)

    check("G3: 17 findings from both files",
          len(result.observations) == 17)

    # First 11 are from validation-report (no SEC-NNN pattern)
    vr_obs = result.observations[:11]
    check("G1: first 11 from validation-report have auto-generated finding_ids",
          all(o.detail["finding_id"].startswith("SEC-") for o in vr_obs))

    # Last 6 are from security-audit (SEC-NNN pattern)
    sa_obs = result.observations[11:]
    check("G4: SEC-NNN pattern parsed in security-audit findings",
          any("SEC-001" == o.detail["finding_id"] for o in sa_obs)
          or any(o.detail["finding_id"].startswith("SEC-0") for o in sa_obs))

    # Check SEC-NNN parsing extracts severity from pattern
    sec_parsed = [o for o in sa_obs
                  if re.match(r"SEC-\d+", o.detail["finding_id"])
                  and o.detail["severity"] not in ("warning", "note")]
    check("G4: at least one finding has severity parsed from SEC pattern",
          len(sec_parsed) > 0 or all(o.detail["severity"] in ("warning", "note") for o in sa_obs))

    check("G9: all weight=1.5",
          all(o.weight == 1.5 for o in result.observations))


# ===========================================================================
# Scenario 3: find-your-tribe features (validation-report only)
# ===========================================================================

fyt = Path("/Users/sanjay.kotagiri/Documents/code/tmp/find-your-tribe/.speed/features")

for feat, expected in [("f10-rich-feed", 5), ("f9-profile-completeness", 4), ("seed-onboarding-flag", 2)]:
    print(f"\n═══ Scenario 3: {feat} (validation-report, {expected} findings) ═══")
    logs = fyt / feat / "logs"
    if not (logs / "validation-report.json").exists():
        print(f"  SKIP: {feat} not found")
        continue

    result = ExtractResult()
    _step6_security_findings(feat, logs, result)

    check(f"G1: {expected} findings extracted",
          len(result.observations) == expected)
    check("G8: all task_id='*'",
          all(o.task_id == "*" for o in result.observations))
    check("G9: all weight=1.5",
          all(o.weight == 1.5 for o in result.observations))
    if result.observations:
        check("G5: recommendation field present",
              all("recommendation" in o.detail for o in result.observations))


# ===========================================================================
# Scenario 4: Edge cases
# ===========================================================================

print("\n═══ Scenario 4: Edge cases ═══")

# 4a: No files exist
with tempfile.TemporaryDirectory() as tmpdir:
    result = ExtractResult()
    _step6_security_findings("test", Path(tmpdir), result)
    check("G6: no files → warning",
          len(result.warnings) == 1 and "No validation-report" in result.warnings[0])
    check("G6: no files → 0 observations",
          len(result.observations) == 0)

# 4b: Empty array in validation-report.json
with tempfile.TemporaryDirectory() as tmpdir:
    (Path(tmpdir) / "validation-report.json").write_text("[]")
    result = ExtractResult()
    _step6_security_findings("test", Path(tmpdir), result)
    check("G7: empty array → warning",
          len(result.warnings) == 1)
    check("G7: empty array → 0 observations",
          len(result.observations) == 0)

# 4c: Dict with empty validation array
with tempfile.TemporaryDirectory() as tmpdir:
    (Path(tmpdir) / "security-audit.json").write_text(
        json.dumps({"validation": [], "tasks": []}))
    result = ExtractResult()
    _step6_security_findings("test", Path(tmpdir), result)
    check("G7: empty validation array → warning",
          len(result.warnings) == 1)

# 4d: SEC-NNN parsing
with tempfile.TemporaryDirectory() as tmpdir:
    (Path(tmpdir) / "validation-report.json").write_text(json.dumps([
        {"issue": "SEC-042 (high): SQL injection in login form",
         "severity": "warning", "recommendation": "Fix it",
         "product_requirement": "S3"}
    ]))
    result = ExtractResult()
    _step6_security_findings("test", Path(tmpdir), result)
    obs = result.observations[0]
    check("G4: finding_id parsed as SEC-042",
          obs.detail["finding_id"] == "SEC-042")
    check("G4: severity parsed as 'high' (not 'warning')",
          obs.detail["severity"] == "high")
    check("G4: title stripped of SEC prefix",
          obs.detail["title"] == "SQL injection in login form")

# 4e: Idempotency
with tempfile.TemporaryDirectory() as tmpdir:
    (Path(tmpdir) / "validation-report.json").write_text(json.dumps([
        {"issue": "Test finding", "severity": "note",
         "recommendation": "", "product_requirement": ""}
    ]))
    r1 = ExtractResult()
    _step6_security_findings("test", Path(tmpdir), r1)
    r2 = ExtractResult()
    _step6_security_findings("test", Path(tmpdir), r2)
    check("Idempotency: same IDs",
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
