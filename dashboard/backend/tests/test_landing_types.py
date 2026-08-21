"""Structural tests for landing_types.py.

Verifies that all 16 required type definitions exist with correct fields,
decorators, and Optional annotations — using AST parsing so no Strawberry
install is required in the test environment.
"""

from __future__ import annotations

import ast
import pathlib
import sys

SOURCE = (
    pathlib.Path(__file__).parent.parent / "resolvers" / "landing_types.py"
)

passed = 0
failed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}" + (f" — {detail}" if detail else ""))


# ── Parse source ──────────────────────────────────────────────────

print("\n=== landing_types.py structural checks ===")

check("source file exists", SOURCE.exists(), str(SOURCE))

tree = ast.parse(SOURCE.read_text(encoding="utf-8"))

# Build lookup: class name → ClassDef node
classes: dict[str, ast.ClassDef] = {}
for node in ast.walk(tree):
    if isinstance(node, ast.ClassDef):
        classes[node.name] = node


def has_decorator(cls: ast.ClassDef, name: str) -> bool:
    for d in cls.decorator_list:
        if isinstance(d, ast.Attribute) and d.attr == name:
            return True
        if isinstance(d, ast.Name) and d.id == name:
            return True
    return False


def field_names(cls: ast.ClassDef) -> set[str]:
    names: set[str] = set()
    for stmt in cls.body:
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            names.add(stmt.target.id)
    return names


def annotation_is_optional(cls: ast.ClassDef, field: str) -> bool:
    for stmt in cls.body:
        if (
            isinstance(stmt, ast.AnnAssign)
            and isinstance(stmt.target, ast.Name)
            and stmt.target.id == field
        ):
            ann = stmt.annotation
            # Optional[X] → Subscript with Optional
            if isinstance(ann, ast.Subscript):
                val = ann.value
                if isinstance(val, ast.Name) and val.id == "Optional":
                    return True
                if isinstance(val, ast.Attribute) and val.attr == "Optional":
                    return True
    return False


# ── All 16 classes present ────────────────────────────────────────

EXPECTED_CLASSES = [
    "LandingDraftSpec",
    "LandingDefect",
    "LandingDefinePanel",
    "LandingDecisionItem",
    "LandingCompletedFeature",
    "LandingQualityGate",
    "LandingJudgePanel",
    "LandingRunningFeature",
    "LandingRecentFeature",
    "LandingEscalation",
    "LandingExecutePanel",
    "LandingCoverageTrend",
    "LandingInsight",
    "LandingEscalationTrend",
    "LandingLearnPanel",
    "LandingView",
    "EscalationResponseInput",
    "EscalationResponseResult",
]

print("\n-- Class presence --")
for name in EXPECTED_CLASSES:
    check(f"class {name} exists", name in classes)

# ── Decorators ────────────────────────────────────────────────────

print("\n-- Decorators --")
for name in EXPECTED_CLASSES:
    if name not in classes:
        continue
    cls = classes[name]
    is_input = name == "EscalationResponseInput"
    expected = "input" if is_input else "type"
    check(
        f"{name} has @strawberry.{expected}",
        has_decorator(cls, expected),
    )

# ── Field sets ────────────────────────────────────────────────────

print("\n-- LandingView fields --")
if "LandingView" in classes:
    flds = field_names(classes["LandingView"])
    for f in ["greeting", "project_name", "define", "judge", "execute", "learn"]:
        check(f"LandingView.{f}", f in flds)
    for f in ["branch", "narrative"]:
        check(f"LandingView.{f} is Optional", annotation_is_optional(classes["LandingView"], f))

print("\n-- LandingDefinePanel fields --")
if "LandingDefinePanel" in classes:
    flds = field_names(classes["LandingDefinePanel"])
    for f in ["vision_status", "draft_specs", "defects", "defect_count"]:
        check(f"LandingDefinePanel.{f}", f in flds)

print("\n-- LandingJudgePanel fields --")
if "LandingJudgePanel" in classes:
    flds = field_names(classes["LandingJudgePanel"])
    for f in ["completed_features", "quality_gates", "total_features", "awaiting_review"]:
        check(f"LandingJudgePanel.{f}", f in flds)

print("\n-- LandingExecutePanel fields --")
if "LandingExecutePanel" in classes:
    flds = field_names(classes["LandingExecutePanel"])
    for f in ["running_features", "escalations"]:
        check(f"LandingExecutePanel.{f}", f in flds)

print("\n-- LandingLearnPanel fields --")
if "LandingLearnPanel" in classes:
    flds = field_names(classes["LandingLearnPanel"])
    for f in ["coverage_trend", "insights", "escalation_trend"]:
        check(f"LandingLearnPanel.{f}", f in flds)

print("\n-- EscalationResponseInput fields --")
if "EscalationResponseInput" in classes:
    flds = field_names(classes["EscalationResponseInput"])
    for f in ["feature", "task_id", "response"]:
        check(f"EscalationResponseInput.{f}", f in flds)

print("\n-- EscalationResponseResult fields --")
if "EscalationResponseResult" in classes:
    flds = field_names(classes["EscalationResponseResult"])
    check("EscalationResponseResult.success", "success" in flds)
    check("EscalationResponseResult.error is Optional", annotation_is_optional(classes["EscalationResponseResult"], "error"))

# ── Summary ───────────────────────────────────────────────────────

print(f"\n=== Results: {passed} passed, {failed} failed ===")
if failed:
    sys.exit(1)
