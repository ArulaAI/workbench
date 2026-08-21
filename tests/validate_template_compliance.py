#!/usr/bin/env python3
"""Validate PRD and RFC against SPEED templates.

Checks that every section in the template appears in the spec file.
Reports missing sections and extra sections not in the template.
"""

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


def extract_h2_sections(path: Path) -> list[str]:
    """Extract all ## headings from a markdown file."""
    sections = []
    for line in path.read_text().split("\n"):
        m = re.match(r"^## (.+?)(?:\s*<!--.*)?$", line)
        if m:
            sections.append(m.group(1).strip())
    return sections


def check_compliance(template_path: Path, spec_path: Path, label: str):
    print(f"\n{'='*60}")
    print(f"{label}")
    print(f"  Template: {template_path.relative_to(PROJECT_ROOT)}")
    print(f"  Spec:     {spec_path.relative_to(PROJECT_ROOT)}")
    print(f"{'='*60}")

    template_sections = extract_h2_sections(template_path)
    spec_sections = extract_h2_sections(spec_path)

    # Normalize for comparison
    def normalize(s):
        return re.sub(r"[^a-z0-9]", "", s.lower())

    template_norm = {normalize(s): s for s in template_sections}
    spec_norm = {normalize(s): s for s in spec_sections}

    missing = []
    for norm, original in template_norm.items():
        if norm not in spec_norm:
            missing.append(original)

    extra = []
    for norm, original in spec_norm.items():
        if norm not in template_norm:
            extra.append(original)

    matched = []
    for norm, original in template_norm.items():
        if norm in spec_norm:
            matched.append(f"  ✓ {original}")

    for line in matched:
        print(line)

    if missing:
        print(f"\n  MISSING ({len(missing)}):")
        for s in missing:
            print(f"  ✗ {s}")

    if extra:
        print(f"\n  EXTRA (not in template, may be valid):")
        for s in extra:
            print(f"  + {s}")

    total = len(template_sections)
    found = total - len(missing)
    pct = 100 * found / max(total, 1)
    print(f"\n  Coverage: {found}/{total} ({pct:.0f}%)")

    return len(missing) == 0


def main():
    prd_template = PROJECT_ROOT / "templates" / "prd.md"
    rfc_template = PROJECT_ROOT / "templates" / "rfc.md"
    spec_template = PROJECT_ROOT / "templates" / "spec.md"

    prd_spec = PROJECT_ROOT / "specs" / "product" / "speed-human-corrections.md"
    rfc_spec = PROJECT_ROOT / "specs" / "tech" / "speed-human-corrections.md"

    results = []

    if prd_template.exists() and prd_spec.exists():
        results.append(check_compliance(prd_template, prd_spec, "PRD Compliance"))

    if rfc_template.exists() and rfc_spec.exists():
        results.append(check_compliance(rfc_template, rfc_spec, "RFC Compliance"))

    # Also check against spec.md template for Goal section
    if spec_template.exists() and prd_spec.exists():
        spec_sections = extract_h2_sections(spec_template)
        prd_sections = extract_h2_sections(prd_spec)
        has_goal = any("goal" in s.lower() for s in prd_sections)
        print(f"\n{'='*60}")
        print(f"Goal check (from spec.md template)")
        print(f"{'='*60}")
        if has_goal:
            print(f"  ✓ Goal section present in PRD")
        else:
            print(f"  ✗ Goal section missing from PRD")
            results.append(False)

    print(f"\n{'='*60}")
    print("RESULT")
    print(f"{'='*60}")
    if all(results):
        print("  All checks passed")
    else:
        print(f"  {sum(1 for r in results if not r)} check(s) failed")

    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
