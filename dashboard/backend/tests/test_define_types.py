"""Structural tests for define_types.py.

Verifies that all 9 required type definitions exist with correct fields,
decorators, and Optional annotations — using AST parsing so no Strawberry
install is required in the test environment.
"""

from __future__ import annotations

import ast
import pathlib
import sys

SOURCE = (
    pathlib.Path(__file__).parent.parent / "resolvers" / "define_types.py"
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

print("\n=== define_types.py structural checks ===")

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
            if isinstance(ann, ast.Subscript):
                val = ann.value
                if isinstance(val, ast.Name) and val.id == "Optional":
                    return True
                if isinstance(val, ast.Attribute) and val.attr == "Optional":
                    return True
    return False


# ── All 9 classes present ──────────────────────────────────────────

EXPECTED_CLASSES = [
    "SpecIndicator",
    "SpecifiedData",
    "BuiltData",
    "GapEscalation",
    "GapData",
    "DefineFeature",
    "DefineDefect",
    "DefineAggregates",
    "DefineView",
]

print("\n-- Class presence --")
for name in EXPECTED_CLASSES:
    check(f"class {name} exists", name in classes)

# ── Decorators ────────────────────────────────────────────────────

print("\n-- Decorators --")
for name in EXPECTED_CLASSES:
    if name not in classes:
        continue
    check(
        f"{name} has @strawberry.type",
        has_decorator(classes[name], "type"),
    )

# ── Field sets ────────────────────────────────────────────────────

print("\n-- SpecIndicator fields --")
if "SpecIndicator" in classes:
    flds = field_names(classes["SpecIndicator"])
    for f in ["exists", "audit_status", "warning_count", "warnings"]:
        check(f"SpecIndicator.{f}", f in flds)
    check("SpecIndicator.path is Optional", annotation_is_optional(classes["SpecIndicator"], "path"))

print("\n-- SpecifiedData fields --")
if "SpecifiedData" in classes:
    flds = field_names(classes["SpecifiedData"])
    for f in ["product_spec", "technical_spec", "design_spec", "open_questions"]:
        check(f"SpecifiedData.{f}", f in flds)
    check("SpecifiedData.sizing_estimate is Optional", annotation_is_optional(classes["SpecifiedData"], "sizing_estimate"))

print("\n-- BuiltData fields --")
if "BuiltData" in classes:
    flds = field_names(classes["BuiltData"])
    check("BuiltData.blocked_count", "blocked_count" in flds)
    for f in ["coverage_pct", "criteria_passed", "criteria_total", "guardian_verdict",
              "task_progress", "tasks_done", "tasks_total", "completed_at"]:
        check(f"BuiltData.{f} is Optional", annotation_is_optional(classes["BuiltData"], f))

print("\n-- GapEscalation fields --")
if "GapEscalation" in classes:
    flds = field_names(classes["GapEscalation"])
    check("GapEscalation.description", "description" in flds)
    check("GapEscalation.linked_warning_id is Optional", annotation_is_optional(classes["GapEscalation"], "linked_warning_id"))

print("\n-- GapData fields --")
if "GapData" in classes:
    flds = field_names(classes["GapData"])
    for f in ["escalation_count", "escalations", "unverifiable_count", "rework_count"]:
        check(f"GapData.{f}", f in flds)

print("\n-- DefineFeature fields --")
if "DefineFeature" in classes:
    flds = field_names(classes["DefineFeature"])
    for f in ["name", "state", "specified", "built", "gap"]:
        check(f"DefineFeature.{f}", f in flds)

print("\n-- DefineDefect fields --")
if "DefineDefect" in classes:
    flds = field_names(classes["DefineDefect"])
    for f in ["name", "severity", "status", "description"]:
        check(f"DefineDefect.{f}", f in flds)
    for f in ["impact", "filed_at"]:
        check(f"DefineDefect.{f} is Optional", annotation_is_optional(classes["DefineDefect"], f))

print("\n-- DefineAggregates fields --")
if "DefineAggregates" in classes:
    flds = field_names(classes["DefineAggregates"])
    for f in ["design_spec_count", "feature_count", "audit_warning_count", "open_question_count",
              "escalation_count", "completed_count", "executing_count", "unplanned_count"]:
        check(f"DefineAggregates.{f}", f in flds)

print("\n-- DefineView fields --")
if "DefineView" in classes:
    flds = field_names(classes["DefineView"])
    for f in ["vision_status", "features", "defects", "aggregates"]:
        check(f"DefineView.{f}", f in flds)
    check("DefineView.vision_path is Optional", annotation_is_optional(classes["DefineView"], "vision_path"))

# ── Summary ───────────────────────────────────────────────────────

print(f"\n=== Results: {passed} passed, {failed} failed ===")
if failed:
    sys.exit(1)
