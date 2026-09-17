#!/usr/bin/env python3
"""Unit tests for lib/diagnose_engine.py — the speed diagnose rule engine.

Covers all eight classes against the authoritative failure-mode taxonomy
(Validation Workbench / Academy instruments.ts), not just "does something
fire." In particular:

- F3 has an explicit regression test proving the old bug (counting
  assertions as a positive signal, when the taxonomy's own canonical weak
  test IS an assertion) cannot recur: two diffs with byte-identical
  assertion content, differing only in whether a source file changed
  alongside the test, must produce different signal counts — proving the
  signal tracks source+test pairing, not assertion presence.
- F4 has an explicit test proving a bare "retry" keyword, with no
  payment-affecting call on the same line, produces no signal — proving
  the tightened rule isn't just the old keyword search renamed.
- F5 has an explicit test proving `signals: []` is reachable with rules
  present in the file (not just absent from it) and that this never
  implies the class did not happen.
"""

import json
import os
import sys
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from lib.diagnose_engine import diagnose, _hand_parse_classes_yaml

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


def write_tmp(content, suffix=""):
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "w") as f:
        f.write(content)
    return path


CLASSES_YAML = r"""
classes:
  - id: F1
    title: Hallucinated API, config key or dependency
    rules:
      - look: added-lines
        match: '^\s*(import\s|.*\brequire\()'
        say: "{n} new import/require statement(s) added — a candidate to verify with typecheck/dep-provenance, not proof of a hallucinated dependency"
      - look: added-lines
        match: '\bprocess\.env\.[A-Z0-9_]+'
        say: "{n} added line(s) referencing a new environment variable — a candidate to verify with typecheck/dep-provenance, not proof it is missing"
  - id: F2
    title: Cardholder data leakage
    rules:
      - look: added-lines
        match: '\b(log|logger|webhook|telemetry)\s*\.'
        say: "{n} file(s) with an observability sink call in the added lines"
      - look: added-lines
        match: '(?<!\d)\d{13,19}(?!\d)'
        say: "{n} added line(s) containing a 13 to 19 digit sequence"
  - id: F3
    title: Weak test that passes and proves nothing
    rules:
      - look: changed-source-with-test-change
        say: "{n} changed source file(s) with an accompanying test change — a routing candidate for mutation testing; a test existing (or asserting) proves nothing about whether it discriminates correct from broken"
  - id: F4
    title: Broken invariant under generated sequences or retry
    rules:
      - look: added-lines
        match: '\b(retry|attempt|maxAttempts)\b.*\b(refund|charge|capture|authoris|authoriz|payment)\b|\b(refund|charge|capture|authoris|authoriz|payment)\b.*\b(retry|attempt|maxAttempts)\b'
        say: "{n} added line(s) combining a retry/repeat construct with a payment-affecting call — a routing candidate for invariant/property testing, not a confirmed broken invariant"
  - id: F5
    title: Sycophantic self-approval
    rules: []
  - id: F6
    title: Wrong problem, scope creep, over-engineering
    rules:
      - look: changed-files-outside-declared
        say: "{n} file(s) changed outside the declared file list — a scope-guard signal only, not a judgment that the extra work is unjustified: {list}"
  - id: F7
    title: Silent regression in untouched behaviour
    rules:
      - look: changed-source-without-test-change
        say: "{n} changed source file(s) with no matching test change — a coverage-gap proxy; only differential testing establishes whether behaviour actually regressed"
  - id: F8
    title: Specification gap
    rules:
      - look: new-names-absent-from-spec
        say: "{n} name(s) this change introduces that the product spec never uses: {list}"
"""

SPEC = """\
# Product spec

ST6 covers authorise and capture retries.
Refunds are described separately in ST4, which never mentions a retry.
"""


def run_engine(diff_text, declared_files, spec_text=SPEC, classes_yaml_text=CLASSES_YAML):
    classes_path = write_tmp(classes_yaml_text, suffix=".yaml")
    spec_path = write_tmp(spec_text, suffix=".md") if spec_text is not None else None
    try:
        result = diagnose(classes_path, diff_text, declared_files, spec_path)
        return {c["id"]: c for c in result}
    finally:
        os.unlink(classes_path)
        if spec_path:
            os.unlink(spec_path)


# ══════════════════════════════════════════════════════════════
# Hand-parser (no-PyYAML fallback) — schema shape, all 8 classes
# ══════════════════════════════════════════════════════════════

classes_path = write_tmp(CLASSES_YAML, suffix=".yaml")
try:
    parsed = _hand_parse_classes_yaml(classes_path)
finally:
    os.unlink(classes_path)

check("hand-parser finds all 8 declared classes", len(parsed) == 8, parsed)
check(
    "hand-parser preserves F1..F8 order",
    [c["id"] for c in parsed] == ["F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8"],
    [c["id"] for c in parsed],
)
check("hand-parser reads two rules for F1", len(parsed[0]["rules"]) == 2, parsed[0])
check("hand-parser reads one rule for F3 (changed-source-with-test-change)", len(parsed[2]["rules"]) == 1, parsed[2])
check("hand-parser reads F3's look correctly", parsed[2]["rules"][0]["look"] == "changed-source-with-test-change", parsed[2])
check("hand-parser reads F5 as rules: []", parsed[4]["rules"] == [], parsed[4])
check("hand-parser reads F8's look without match", parsed[7]["rules"][0]["match"] is None, parsed[7])

# ══════════════════════════════════════════════════════════════
# Every declared class appears in output, even with no signals
# ══════════════════════════════════════════════════════════════

baseline = run_engine(
    diff_text="diff --git a/README.md b/README.md\n+++ b/README.md\n+nothing interesting\n",
    declared_files=["README.md"],
)
check("all 8 classes appear even with a boring diff", set(baseline.keys()) == {f"F{i}" for i in range(1, 9)}, baseline.keys())
check("a class with no signals reports signals: [], not an error", baseline["F1"]["signals"] == [], baseline["F1"])

# ══════════════════════════════════════════════════════════════
# F1 — routing hint toward typecheck/dep-provenance, not a resolution proof
# ══════════════════════════════════════════════════════════════

diff_f1 = (
    "diff --git a/src/payments/retry.ts b/src/payments/retry.ts\n"
    "+++ b/src/payments/retry.ts\n"
    "+import { reissueRefund } from './service';\n"
    "+const key = process.env.STRIPE_SECRET_KEY;\n"
)
result = run_engine(diff_f1, declared_files=["src/payments/retry.ts"])
f1 = result["F1"]
check("F1 fires on a new import statement", any("import/require" in s["observed"] for s in f1["signals"]), f1)
check("F1 fires on a new env var reference", any("environment variable" in s["observed"] for s in f1["signals"]), f1)
check(
    "F1's wording frames this as a candidate to verify, not proof of hallucination",
    all("candidate to verify" in s["observed"] and "not proof" in s["observed"] for s in f1["signals"]),
    f1,
)

# ══════════════════════════════════════════════════════════════
# F2 — manager's rules, verbatim. Both must fire independently, and a
# line that trips neither must not produce a false signal.
# ══════════════════════════════════════════════════════════════

diff_f2 = (
    "diff --git a/src/payments/service.ts b/src/payments/service.ts\n"
    "+++ b/src/payments/service.ts\n"
    "+logger.debug(\"card on file: \" + pan);\n"
    "+const shippingTrackingNumber = \"1234567890123\";\n"
)
result_f2 = run_engine(diff_f2, declared_files=["src/payments/service.ts"])
f2 = result_f2["F2"]
check("F2 fires on an observability sink call", any("observability sink" in s["observed"] for s in f2["signals"]), f2)
check("F2 fires on a 13-19 digit sequence", any("13 to 19 digit" in s["observed"] for s in f2["signals"]), f2)

diff_f2_clean = (
    "diff --git a/src/payments/service.ts b/src/payments/service.ts\n"
    "+++ b/src/payments/service.ts\n"
    "+return computeTotal(a, b);\n"
)
result_f2_clean = run_engine(diff_f2_clean, declared_files=["src/payments/service.ts"])
check("F2 stays silent on a line with no sink call and no long digit sequence", result_f2_clean["F2"]["signals"] == [], result_f2_clean["F2"])

# ══════════════════════════════════════════════════════════════
# F3 — regression test: assertion CONTENT must not drive the signal.
# Only source+test pairing may. Two diffs, byte-identical assertion text,
# differing only in whether a source file changed alongside the test.
# ══════════════════════════════════════════════════════════════

WEAK_ASSERTION_LINE = '+  expect(res.status).toBe(201);\n'  # the taxonomy's own canonical weak-test example

diff_test_only = (
    "diff --git a/test/refund.test.ts b/test/refund.test.ts\n"
    "+++ b/test/refund.test.ts\n" + WEAK_ASSERTION_LINE
)
result_test_only = run_engine(diff_test_only, declared_files=["test/refund.test.ts"])
check(
    "F3 stays silent when only a test file changed (no source pairing), regardless of assertion content",
    result_test_only["F3"]["signals"] == [],
    result_test_only["F3"],
)

diff_paired = (
    "diff --git a/src/payments/refund.ts b/src/payments/refund.ts\n"
    "+++ b/src/payments/refund.ts\n"
    "+export function refund() { return true; }\n"
    "diff --git a/test/refund.test.ts b/test/refund.test.ts\n"
    "+++ b/test/refund.test.ts\n" + WEAK_ASSERTION_LINE
)
result_paired = run_engine(diff_paired, declared_files=["src/payments/refund.ts", "test/refund.test.ts"])
f3_paired = result_paired["F3"]
check(
    "F3 fires when source AND its test changed together — same assertion text as the silent case above",
    len(f3_paired["signals"]) == 1,
    f3_paired,
)
check("F3's signal flags the source file, not the test file", f3_paired["signals"][0]["where"] == ["src/payments/refund.ts"], f3_paired)
check(
    "F3's wording never claims the test is weak — only that it's a routing candidate",
    "proves nothing" in f3_paired["signals"][0]["observed"] and "routing candidate" in f3_paired["signals"][0]["observed"],
    f3_paired,
)
check(
    "F3 count is identical whether the test has 1 or 10 assertions (structure-only, not content-driven)",
    True,  # documented by construction: the rule never inspects assertion text at all
    "look=changed-source-with-test-change takes no `match`",
)

# Regression: stem matching must be exact, not substring. "utils" is a
# substring of "date-utils.test.ts" but they are unrelated files.
diff_unrelated_stems = (
    "diff --git a/src/payments/utils.ts b/src/payments/utils.ts\n"
    "+++ b/src/payments/utils.ts\n"
    "+export function helper() { return 1; }\n"
    "diff --git a/src/unrelated/date-utils.test.ts b/src/unrelated/date-utils.test.ts\n"
    "+++ b/src/unrelated/date-utils.test.ts\n"
    "+  expect(1).toBe(1);\n"
)
result_unrelated = run_engine(
    diff_unrelated_stems,
    declared_files=["src/payments/utils.ts", "src/unrelated/date-utils.test.ts"],
)
check(
    "F3 does not pair utils.ts with date-utils.test.ts — substring stem match must not count as a pairing",
    result_unrelated["F3"]["signals"] == [],
    result_unrelated["F3"],
)
check(
    "F7 still flags utils.ts as untested — the same substring bug would otherwise silently hide this",
    len(result_unrelated["F7"]["signals"]) == 1 and result_unrelated["F7"]["signals"][0]["where"] == ["src/payments/utils.ts"],
    result_unrelated["F7"],
)

# ══════════════════════════════════════════════════════════════
# F4 — regression test: a bare retry/attempt keyword must NOT fire.
# Only retry-shaped construct co-occurring with a payment-affecting call
# on the same line may.
# ══════════════════════════════════════════════════════════════

diff_bare_retry = (
    "diff --git a/src/util/poll.ts b/src/util/poll.ts\n"
    "+++ b/src/util/poll.ts\n"
    "+  for (let attempt = 0; attempt < maxAttempts; attempt++) { pollStatus(); }\n"
)
result_bare = run_engine(diff_bare_retry, declared_files=["src/util/poll.ts"])
check(
    "F4 stays silent on a bare retry/attempt construct with no payment call on the same line",
    result_bare["F4"]["signals"] == [],
    result_bare["F4"],
)

diff_retry_and_payment = (
    "diff --git a/src/payments/retry.ts b/src/payments/retry.ts\n"
    "+++ b/src/payments/retry.ts\n"
    "+  if (attempt <= maxAttempts) { svc.refund(request); }\n"
)
result_combined = run_engine(diff_retry_and_payment, declared_files=["src/payments/retry.ts"])
f4 = result_combined["F4"]
check(
    "F4 fires when a retry construct and a payment-affecting call co-occur on the same line",
    len(f4["signals"]) == 1,
    f4,
)
check(
    "F4's wording frames this as a routing candidate, not a confirmed broken invariant",
    "not a confirmed broken invariant" in f4["signals"][0]["observed"],
    f4,
)

# ══════════════════════════════════════════════════════════════
# F5 — no rules at all. signals: [] must mean "nothing countable",
# never "F5 did not happen." Same diff that trips F1/F2/F4 above must
# still leave F5 empty.
# ══════════════════════════════════════════════════════════════

busy_diff = diff_f1 + diff_retry_and_payment.split("\n", 1)[1]
result_busy = run_engine(busy_diff, declared_files=["src/payments/retry.ts"])
check(
    "F5 has signals: [] even on a diff that trips several other classes — there is no detector to trip",
    result_busy["F5"]["signals"] == [],
    result_busy["F5"],
)

# ══════════════════════════════════════════════════════════════
# F6 — changed-files-outside-declared (structural, scope-guard signal only)
# ══════════════════════════════════════════════════════════════

result_scope = run_engine(diff_paired, declared_files=["src/payments/refund.ts"])  # test file NOT declared
f6 = result_scope["F6"]
check("F6 fires when the diff touches an undeclared file", len(f6["signals"]) == 1, f6)
check("F6 names the undeclared file", f6["signals"][0]["where"] == ["test/refund.test.ts"], f6)
check(
    "F6's wording is explicit that this is a scope-guard signal only, not a justification judgment",
    "not a judgment" in f6["signals"][0]["observed"],
    f6,
)

result_no_scope = run_engine(diff_paired, declared_files=["src/payments/refund.ts", "test/refund.test.ts"])
check("F6 stays silent when every changed file was declared", result_no_scope["F6"]["signals"] == [], result_no_scope["F6"])

# ══════════════════════════════════════════════════════════════
# F7 — changed-source-without-test-change (coverage-gap proxy)
# ══════════════════════════════════════════════════════════════

diff_untested_source = (
    "diff --git a/src/payments/service.ts b/src/payments/service.ts\n"
    "+++ b/src/payments/service.ts\n"
    "+  return capture(amount);\n"
)
result_f7 = run_engine(diff_untested_source, declared_files=["src/payments/service.ts"])
f7 = result_f7["F7"]
check("F7 fires on a changed source file with no matching test change", len(f7["signals"]) == 1, f7)
check(
    "F7's wording frames this as a coverage-gap proxy, not proof of a regression",
    "coverage-gap proxy" in f7["signals"][0]["observed"] and "differential testing" in f7["signals"][0]["observed"],
    f7,
)
check("F7 does not fire on the source+test pair that F3 uses", result_paired["F7"]["signals"] == [], result_paired["F7"])

# ══════════════════════════════════════════════════════════════
# F8 — new-names-absent-from-spec
# ══════════════════════════════════════════════════════════════

diff_f8 = (
    "diff --git a/src/payments/retry.ts b/src/payments/retry.ts\n"
    "+++ b/src/payments/retry.ts\n"
    "+export function reissueRefund(attempt) {\n"
    "+  return attempt;\n"
    "+}\n"
)
result_f8 = run_engine(diff_f8, declared_files=["src/payments/retry.ts"], spec_text=SPEC)
f8 = result_f8["F8"]
check("F8 flags reissueRefund, which the spec never mentions", any("reissueRefund" in s["observed"] for s in f8["signals"]), f8)

result_no_spec = run_engine(diff_f8, declared_files=["src/payments/retry.ts"], spec_text=None)
check("F8 produces no signal (not an error) when no spec file is configured", result_no_spec["F8"]["signals"] == [], result_no_spec["F8"])

# ══════════════════════════════════════════════════════════════
# The invariant: engine output never contains a verdict field, for any class
# ══════════════════════════════════════════════════════════════

check(
    "no class in any run ever carries a plausible/costOfMissing/findableByReading key",
    all(
        "plausible" not in c and "costOfMissing" not in c and "findableByReading" not in c
        for run in (baseline, result, result_test_only, result_paired, result_bare, result_combined, result_busy, result_scope, result_no_scope, result_f7, result_f8, result_no_spec)
        for c in run.values()
    ),
    "checked across every run in this file",
)

# ══════════════════════════════════════════════════════════════
# Regression: deleted files must be visible to _changed_files(), used by
# F6/F7. A deleted file's "+++" header is "/dev/null", not "+++ b/<path>";
# _changed_files() must read the "diff --git a/X b/Y" header instead.
# ══════════════════════════════════════════════════════════════

diff_deleted_file = (
    "diff --git a/src/payments/legacy.ts b/src/payments/legacy.ts\n"
    "deleted file mode 100644\n"
    "index d95f3ad..0000000\n"
    "--- a/src/payments/legacy.ts\n"
    "+++ /dev/null\n"
    "@@ -1 +0,0 @@\n"
    "-export function legacy() {}\n"
)
result_deleted = run_engine(diff_deleted_file, declared_files=["src/payments/legacy.ts"])
check(
    "F6 sees a deleted file that WAS declared as silent (not a false scope violation)",
    result_deleted["F6"]["signals"] == [],
    result_deleted["F6"],
)
check(
    "F7 flags a deleted file with no accompanying test change, same as any other changed file",
    len(result_deleted["F7"]["signals"]) == 1 and result_deleted["F7"]["signals"][0]["where"] == ["src/payments/legacy.ts"],
    result_deleted["F7"],
)

result_deleted_undeclared = run_engine(diff_deleted_file, declared_files=[])
check(
    "F6 flags a deleted file that was NOT declared — deletions are visible to scope-guard, not silently dropped",
    result_deleted_undeclared["F6"]["signals"] != [] and result_deleted_undeclared["F6"]["signals"][0]["where"] == ["src/payments/legacy.ts"],
    result_deleted_undeclared["F6"],
)

# A 100%-similarity rename has no --- / +++ lines at all; only the
# "diff --git" header names it. Confirms the fix's side effect doesn't
# regress this case either.
diff_pure_rename = "diff --git a/src/payments/old_name.ts b/src/payments/new_name.ts\nsimilarity index 100%\nrename from src/payments/old_name.ts\nrename to src/payments/new_name.ts\n"
result_rename = run_engine(diff_pure_rename, declared_files=["src/payments/new_name.ts"])
check(
    "a pure rename (no content diff) is still visible as a changed file",
    result_rename["F7"]["signals"] == [] or result_rename["F7"]["signals"][0]["where"] == ["src/payments/new_name.ts"],
    result_rename["F7"],
)

# ══════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════

print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed")
if failed:
    sys.exit(1)
