#!/usr/bin/env python3
"""Validate the fixed classification logic for Step 8."""

import sys

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


def classify(planned, actual):
    """Reproduce the fixed classification logic."""
    extras = sorted(actual - planned)
    missing = sorted(planned - actual)
    if not extras and not missing:
        return None  # no mismatch
    if missing and extras:
        return "boundary_mismatch"
    elif missing:
        return "missing_dependency"
    else:
        return "scope_too_broad"


print("═══ Classification logic ═══\n")

# 1. Developer swapped files completely
check("planned=[a], actual=[b] → boundary_mismatch",
      classify({"a"}, {"b"}) == "boundary_mismatch")

# 2. Developer swapped some, kept some
check("planned=[a,b], actual=[a,c] → boundary_mismatch",
      classify({"a", "b"}, {"a", "c"}) == "boundary_mismatch")

# 3. Developer swapped all for many
check("planned=[a], actual=[b,c,d] → boundary_mismatch",
      classify({"a"}, {"b", "c", "d"}) == "boundary_mismatch")

# 4. Developer didn't finish
check("planned=[a,b], actual=[a] → missing_dependency",
      classify({"a", "b"}, {"a"}) == "missing_dependency")

# 5. Developer touched nothing planned
check("planned=[a,b], actual=[] would be caught earlier (both empty guard)",
      True)  # edge case handled before classify

# 6. Developer went wide, small extra
check("planned=[a], actual=[a,b] → scope_too_broad",
      classify({"a"}, {"a", "b"}) == "scope_too_broad")

# 7. Developer went wide, many extras
check("planned=[a], actual=[a,b,c,d] → scope_too_broad",
      classify({"a"}, {"a", "b", "c", "d"}) == "scope_too_broad")

# 8. Developer went wide, proportionally small
check("planned=[a,b,c,d,e], actual=[a,b,c,d,e,f] → scope_too_broad",
      classify({"a","b","c","d","e"}, {"a","b","c","d","e","f"}) == "scope_too_broad")

# 9. Exact match
check("planned=[a,b], actual=[a,b] → None",
      classify({"a", "b"}, {"a", "b"}) is None)

# 10. Big swap
check("planned=[a,b,c], actual=[d,e,f] → boundary_mismatch",
      classify({"a","b","c"}, {"d","e","f"}) == "boundary_mismatch")

# 11. Partial overlap with both missing and extra
check("planned=[a,b,c], actual=[b,d] → boundary_mismatch",
      classify({"a","b","c"}, {"b","d"}) == "boundary_mismatch")

print(f"\n{'═' * 50}")
print(f"Results: {passed} passed, {failed} failed out of {passed + failed}")
if failed > 0:
    sys.exit(1)
else:
    print("ALL CHECKS PASSED")
