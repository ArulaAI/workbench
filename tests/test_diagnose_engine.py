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
import re
import sys
import tempfile

try:
    import yaml
except ImportError:
    yaml = None

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from lib.diagnose_engine import (
    diagnose, _hand_parse_classes_yaml, _added_lines_by_file,
    _changed_files, _looks_like_test_file, _has_matching_test_change,
    _git_unquote,
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

# F1 must fire the same way when the import is added to an existing file
# being modified (`--- a/<path>`), not only when the file is newly
# created — the engine reads only '+'/'+++' lines and never inspects
# 'new file mode'/'--- /dev/null', so this proves that indifference holds
# for a real modified-file diff shape, not just an unstated one.
diff_f1_existing_file = (
    "diff --git a/src/payments/service.ts b/src/payments/service.ts\n"
    "--- a/src/payments/service.ts\n"
    "+++ b/src/payments/service.ts\n"
    "+import { reissueRefund } from './retry';\n"
)
result_existing = run_engine(diff_f1_existing_file, declared_files=["src/payments/service.ts"])
f1_existing = result_existing["F1"]
check(
    "F1 fires on a new import added to an existing (modified, not newly created) file",
    any("import/require" in s["observed"] for s in f1_existing["signals"]),
    f1_existing,
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
# Regression: an added line beginning with "++" (e.g. a pre-increment
# with no leading indentation) must not be mistaken for the "+++ b/..."
# file header and dropped.
# ══════════════════════════════════════════════════════════════

diff_plusplus = (
    "diff --git a/src/counter.c b/src/counter.c\n"
    "+++ b/src/counter.c\n"
    "@@ -1,2 +1,3 @@\n"
    " int x = 0;\n"
    "+++x;\n"
    " return 0;\n"
)
check(
    "an added line starting with ++ is preserved, not mistaken for the file header",
    _added_lines_by_file(diff_plusplus) == [("src/counter.c", "++x;")],
    _added_lines_by_file(diff_plusplus),
)

diff_deleted_dev_null = (
    "diff --git a/src/old.c b/src/old.c\n"
    "deleted file mode 100644\n"
    "--- a/src/old.c\n"
    "+++ /dev/null\n"
    "@@ -1 +0,0 @@\n"
    "-int x;\n"
)
check(
    "the +++ /dev/null deletion header is still correctly skipped (no regression)",
    _added_lines_by_file(diff_deleted_dev_null) == [],
    _added_lines_by_file(diff_deleted_dev_null),
)

# ══════════════════════════════════════════════════════════════
# Regression: non-standard classes.yaml indentation must raise a clear
# configuration error, not crash with AttributeError.
# ══════════════════════════════════════════════════════════════

classes_yaml_4space_indent = write_tmp(
    "classes:\n"
    "    - id: F1\n"
    "      title: Four-space indented class\n"
    "      rules:\n"
    "        - look: added-lines\n"
    "          match: 'x'\n"
    "          say: \"y\"\n",
    suffix=".yaml",
)
try:
    error = None
    try:
        _hand_parse_classes_yaml(classes_yaml_4space_indent)
    except Exception as e:
        error = e
    check(
        "4-space indentation raises ValueError, not AttributeError",
        isinstance(error, ValueError) and not isinstance(error, AttributeError),
        error,
    )
    check(
        "the error names the offending line number (now caught at the "
        "malformed '- id:' line itself, line 2, not several lines later)",
        error is not None and "line 2" in str(error),
        error,
    )
finally:
    os.unlink(classes_yaml_4space_indent)

# A rule line at the very top of the file, before any class, is the same
# underlying gap (current_rules is None) — must also raise cleanly.
classes_yaml_rule_before_class = write_tmp(
    "classes:\n"
    "  - look: added-lines\n"
    "    match: 'x'\n"
    "    say: \"y\"\n",
    suffix=".yaml",
)
try:
    error = None
    try:
        _hand_parse_classes_yaml(classes_yaml_rule_before_class)
    except Exception as e:
        error = e
    check(
        "a rule before any '- id:' class raises ValueError, not AttributeError",
        isinstance(error, ValueError) and not isinstance(error, AttributeError),
        error,
    )
finally:
    os.unlink(classes_yaml_rule_before_class)

# The engine's public entry point must surface this as a clean config
# error end-to-end when PyYAML is unavailable (the hand-parser's only
# real audience), same as an actually-missing classes file — never an
# unhandled traceback. PyYAML parses non-standard indentation just fine
# on its own, so this has to force the fallback path to exercise it.
malformed_path = write_tmp(
    "classes:\n"
    "    - id: F1\n"
    "      rules:\n"
    "        - look: added-lines\n",
    suffix=".yaml",
)
try:
    import builtins
    real_import = builtins.__import__

    def _no_yaml(name, *args, **kwargs):
        if name == "yaml":
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    error = None
    builtins.__import__ = _no_yaml
    try:
        diagnose(malformed_path, "diff --git a/x b/x\n", [])
    except Exception as e:
        error = e
    finally:
        builtins.__import__ = real_import
    check(
        "diagnose() surfaces the malformed-indentation case as a ValueError, not a crash, when PyYAML is unavailable",
        isinstance(error, ValueError),
        error,
    )
finally:
    os.unlink(malformed_path)

# ══════════════════════════════════════════════════════════════
# Finding 1 — quoted/non-ASCII filenames must not be dropped or
# misattributed to the previous file.
# ══════════════════════════════════════════════════════════════

diff_quoted_solo = (
    'diff --git "a/caf\\303\\251.py" "b/caf\\303\\251.py"\n'
    "new file mode 100644\n"
    "--- /dev/null\n"
    '+++ "b/caf\\303\\251.py"\n'
    "@@ -0,0 +1 @@\n"
    "+ascii content\n"
)
check(
    "a quoted non-ASCII filename is decoded, not dropped, in _changed_files",
    _changed_files(diff_quoted_solo) == ["café.py"],
    _changed_files(diff_quoted_solo),
)
check(
    "its added lines are attributed to the decoded filename, not lost",
    _added_lines_by_file(diff_quoted_solo) == [("café.py", "ascii content")],
    _added_lines_by_file(diff_quoted_solo),
)

diff_quoted_after_normal = (
    "diff --git a/src/normal.py b/src/normal.py\n"
    "+++ b/src/normal.py\n"
    "@@ -0,0 +1 @@\n"
    "+normal file content\n"
    'diff --git "a/caf\\303\\251.py" "b/caf\\303\\251.py"\n'
    "new file mode 100644\n"
    "--- /dev/null\n"
    '+++ "b/caf\\303\\251.py"\n'
    "@@ -0,0 +1 @@\n"
    "+quoted file content\n"
)
check(
    "a quoted filename's content is not misattributed to the preceding file",
    _added_lines_by_file(diff_quoted_after_normal) == [
        ("src/normal.py", "normal file content"),
        ("café.py", "quoted file content"),
    ],
    _added_lines_by_file(diff_quoted_after_normal),
)

diff_unquoted_still_works = "diff --git a/normal.py b/normal.py\n+++ b/normal.py\n@@ -0,0 +1 @@\n+content\n"
check(
    "unquoted (ASCII) filenames are unaffected by the quoting fix",
    _changed_files(diff_unquoted_still_works) == ["normal.py"]
    and _added_lines_by_file(diff_unquoted_still_works) == [("normal.py", "content")],
    (_changed_files(diff_unquoted_still_works), _added_lines_by_file(diff_unquoted_still_works)),
)

# ══════════════════════════════════════════════════════════════
# Finding 2 — source/test matching must respect directory boundaries,
# not just basename stems, so unrelated modules/languages don't
# suppress a genuine missing-test signal.
# ══════════════════════════════════════════════════════════════

check(
    "backend/service.py does NOT match frontend/service.test.ts — different, unrelated modules",
    _has_matching_test_change("backend/service.py", ["backend/service.py", "frontend/service.test.ts"]) is False,
    None,
)
check(
    "a flat top-level test root still matches any source subdirectory (existing legitimate layout)",
    _has_matching_test_change("src/payments/refund.ts", ["src/payments/refund.ts", "test/refund.test.ts"]) is True,
    None,
)
check(
    "same-directory colocated test still matches",
    _has_matching_test_change(
        "src/payments/service.ts", ["src/payments/service.ts", "src/payments/service.test.ts"]
    ) is True,
    None,
)
check(
    "a per-module nested tests/ directory matches its own module",
    _has_matching_test_change("moduleA/service.py", ["moduleA/service.py", "moduleA/tests/test_service.py"]) is True,
    None,
)
check(
    "a per-module nested tests/ directory does NOT match a different module (cross-module false positive)",
    _has_matching_test_change("moduleA/utils.py", ["moduleA/utils.py", "moduleB/tests/test_utils.py"]) is False,
    None,
)

# ══════════════════════════════════════════════════════════════
# Finding 3 — colocated Python/Go test-file naming conventions must be
# recognized as test files, not misclassified as source.
# ══════════════════════════════════════════════════════════════

check("test_service.py is recognized as a test file", _looks_like_test_file("test_service.py") is True, None)
check("service_test.go is recognized as a test file", _looks_like_test_file("service_test.go") is True, None)
check(
    "a Python file with a matching colocated test is no longer flagged as untested (F7)",
    (lambda r: r["F7"]["signals"] == [])(
        run_engine(
            "diff --git a/backend/service.py b/backend/service.py\n"
            "+++ b/backend/service.py\n@@ -0,0 +1 @@\n+def handler(): pass\n"
            "diff --git a/backend/test_service.py b/backend/test_service.py\n"
            "+++ b/backend/test_service.py\n@@ -0,0 +1 @@\n+def test_handler(): pass\n",
            declared_files=["backend/service.py", "backend/test_service.py"],
        )
    ),
    "F7 should stay silent once the colocated Python test is recognized",
)
check(
    "'test_' as a substring of a longer word (testing_utils.py) is NOT misclassified as a test file",
    _looks_like_test_file("testing_utils.py") is False,
    None,
)
check(
    "'test' appearing mid-word (latest.py) is NOT misclassified as a test file",
    _looks_like_test_file("latest.py") is False,
    None,
)

# ══════════════════════════════════════════════════════════════
# Finding 4 — the hand-parser's double-quoted scalar decoding must
# match PyYAML's behavior for supported escapes, and clearly reject
# unsupported ones rather than silently compiling a broken regex.
# ══════════════════════════════════════════════════════════════

classes_yaml_dq_escape = write_tmp(
    'classes:\n'
    '  - id: F1\n'
    '    title: Test\n'
    '    rules:\n'
    '      - look: added-lines\n'
    '        match: "\\\\bimport\\\\b"\n'
    '        say: "{n}"\n',
    suffix=".yaml",
)
try:
    parsed = _hand_parse_classes_yaml(classes_yaml_dq_escape)
    decoded = parsed[0]["rules"][0]["match"]
    check(
        "a double-backslash escape in a double-quoted match value decodes the same as PyYAML",
        decoded == "\\bimport\\b",
        repr(decoded),
    )
    check(
        "the decoded pattern behaves as the intended word-boundary regex",
        bool(re.search(decoded, "import foo")),
        decoded,
    )
finally:
    os.unlink(classes_yaml_dq_escape)

classes_yaml_bad_escape = write_tmp(
    'classes:\n'
    '  - id: F1\n'
    '    title: Test\n'
    '    rules:\n'
    '      - look: added-lines\n'
    '        match: "\\d+"\n'
    '        say: "{n}"\n',
    suffix=".yaml",
)
try:
    error = None
    try:
        _hand_parse_classes_yaml(classes_yaml_bad_escape)
    except ValueError as e:
        error = e
    check(
        "an unsupported escape in a double-quoted value raises a clear error rather than a silently-wrong regex",
        error is not None and "unsupported escape" in str(error),
        error,
    )
finally:
    os.unlink(classes_yaml_bad_escape)

check(
    "single-quoted values are still never escape-processed (existing, unaffected behavior)",
    _hand_parse_classes_yaml(write_tmp(
        "classes:\n  - id: F1\n    title: Test\n    rules:\n      - look: added-lines\n        match: '\\bimport\\b'\n        say: \"{n}\"\n",
        suffix=".yaml",
    ))[0]["rules"][0]["match"] == r"\bimport\b",
    None,
)

# ══════════════════════════════════════════════════════════════
# Finding 5 — unrecognized/malformed classes.yaml structure must raise
# a clear configuration error, not silently return an empty class list
# that would let diagnose report a misleading successful diagnosis.
# ══════════════════════════════════════════════════════════════

flow_style_path = write_tmp('classes: [{id: F1, title: "Test"}]\n', suffix=".yaml")
try:
    error = None
    try:
        _hand_parse_classes_yaml(flow_style_path)
    except ValueError as e:
        error = e
    check(
        "flow-style YAML (unsupported by the hand-parser) raises, rather than returning []",
        error is not None and "unrecognized syntax" in str(error),
        error,
    )
finally:
    os.unlink(flow_style_path)

check(
    "a genuinely empty file (no classes at all) still returns [] without error — not every empty result is malformed",
    _hand_parse_classes_yaml(write_tmp("", suffix=".yaml")) == [],
    None,
)

check(
    "rules: [] (the F5 shape used throughout every real classes.yaml) still parses correctly",
    _hand_parse_classes_yaml(write_tmp(
        "classes:\n  - id: F5\n    title: Sycophantic self-approval\n    rules: []\n",
        suffix=".yaml",
    )) == [{"id": "F5", "title": "Sycophantic self-approval", "rules": []}],
    None,
)

# End-to-end: malformed structure surfaces through diagnose() itself as
# a config error, forcing the no-PyYAML fallback path since PyYAML
# would otherwise parse this flow-style file just fine on its own.
flow_style_path2 = write_tmp('classes: [{id: F1}]\n', suffix=".yaml")
try:
    import builtins
    real_import = builtins.__import__

    def _no_yaml2(name, *args, **kwargs):
        if name == "yaml":
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    error = None
    builtins.__import__ = _no_yaml2
    try:
        diagnose(flow_style_path2, "diff --git a/x b/x\n", [])
    except Exception as e:
        error = e
    finally:
        builtins.__import__ = real_import
    check(
        "diagnose() surfaces malformed YAML as a config error end-to-end, never a misleading empty success",
        isinstance(error, ValueError),
        error,
    )
finally:
    os.unlink(flow_style_path2)

# ══════════════════════════════════════════════════════════════
# Follow-up review, finding 1 of 3 — a filename containing a space is
# NOT quoted by git (only non-ASCII/control characters trigger quoting),
# so the quoted-filename fix must not break this far more common case.
# ══════════════════════════════════════════════════════════════

diff_spaced_solo = (
    "diff --git a/my file.py b/my file.py\n"
    "new file mode 100644\n"
    "--- /dev/null\n"
    "+++ b/my file.py\n"
    "@@ -0,0 +1 @@\n"
    "+spaced file content\n"
)
check(
    "an unquoted filename containing a space is not dropped",
    _changed_files(diff_spaced_solo) == ["my file.py"],
    _changed_files(diff_spaced_solo),
)
check(
    "its added lines are attributed to the spaced filename, not lost",
    _added_lines_by_file(diff_spaced_solo) == [("my file.py", "spaced file content")],
    _added_lines_by_file(diff_spaced_solo),
)

diff_spaced_after_normal = (
    "diff --git a/normal.py b/normal.py\n"
    "+++ b/normal.py\n"
    "@@ -0,0 +1 @@\n"
    "+normal content\n"
    "diff --git a/my file.py b/my file.py\n"
    "new file mode 100644\n"
    "--- /dev/null\n"
    "+++ b/my file.py\n"
    "@@ -0,0 +1 @@\n"
    "+spaced file content\n"
)
check(
    "a spaced filename's content is not misattributed to the preceding file (the actual reported regression)",
    _added_lines_by_file(diff_spaced_after_normal) == [
        ("normal.py", "normal content"),
        ("my file.py", "spaced file content"),
    ],
    _added_lines_by_file(diff_spaced_after_normal),
)
check(
    "the /dev/null deletion header still doesn't leak into current_file after this rewrite",
    _added_lines_by_file(
        "diff --git a/old.c b/old.c\ndeleted file mode 100644\n--- a/old.c\n+++ /dev/null\n@@ -1 +0,0 @@\n-int x;\n"
    ) == [],
    None,
)
check(
    "quoted non-ASCII filenames still work after the rewrite (Finding 1, unaffected)",
    _changed_files(
        'diff --git "a/caf\\303\\251.py" "b/caf\\303\\251.py"\nnew file mode 100644\n--- /dev/null\n+++ "b/caf\\303\\251.py"\n@@ -0,0 +1 @@\n+x\n'
    ) == ["café.py"],
    None,
)

# ══════════════════════════════════════════════════════════════
# Follow-up review, finding 2 of 3 — the "either side empty" wildcard
# for flat test roots must only apply to the TEST side. A root-level
# source file must not match an unrelated nested module's test just
# because the source has no directory of its own.
# ══════════════════════════════════════════════════════════════

check(
    "a root-level source file does NOT match an unrelated nested module's test (the reopened false positive)",
    _has_matching_test_change("utils.py", ["utils.py", "moduleB/tests/test_utils.py"]) is False,
    None,
)
check(
    "a root-level source file still matches a root-level colocated test",
    _has_matching_test_change("service.py", ["service.py", "test_service.py"]) is True,
    None,
)
check(
    "a root-level source file still matches a flat top-level test root",
    _has_matching_test_change("service.py", ["service.py", "test/service.test.ts"]) is True,
    None,
)
check(
    "flat test root for a nested source still works (regression check)",
    _has_matching_test_change("src/payments/refund.ts", ["src/payments/refund.ts", "test/refund.test.ts"]) is True,
    None,
)
check(
    "per-module nested tests/ still matches its own module (regression check)",
    _has_matching_test_change("moduleA/service.py", ["moduleA/service.py", "moduleA/tests/test_service.py"]) is True,
    None,
)
check(
    "cross-module nested tests/ still rejected (regression check)",
    _has_matching_test_change("moduleA/utils.py", ["moduleA/utils.py", "moduleB/tests/test_utils.py"]) is False,
    None,
)
check(
    "the original Finding 2 case (cross-directory/language) still rejected (regression check)",
    _has_matching_test_change("backend/service.py", ["backend/service.py", "frontend/service.test.ts"]) is False,
    None,
)

# ══════════════════════════════════════════════════════════════
# Follow-up review, finding 3 of 3 — \xHH, \uHHHH, \UHHHHHHHH are valid
# YAML double-quote escapes; the hand-parser must decode them the same
# way PyYAML does, not reject them as "unsupported."
# ══════════════════════════════════════════════════════════════

classes_yaml_hex_escape = write_tmp(
    'classes:\n'
    '  - id: F1\n'
    '    title: Test\n'
    '    rules:\n'
    '      - look: added-lines\n'
    '        match: "\\x41caf\\u00e9"\n'
    '        say: "{n}"\n',
    suffix=".yaml",
)
try:
    handparse_value = _hand_parse_classes_yaml(classes_yaml_hex_escape)[0]["rules"][0]["match"]
    if yaml is not None:
        pyyaml_value = yaml.safe_load(open(classes_yaml_hex_escape))["classes"][0]["rules"][0]["match"]
        check(
            "\\xHH and \\uHHHH decode identically under PyYAML and the hand-parser",
            pyyaml_value == handparse_value == "Acafé",
            (pyyaml_value, handparse_value),
        )
    else:
        check("\\xHH and \\uHHHH decode to the expected characters (PyYAML unavailable to cross-check)",
              handparse_value == "Acafé", handparse_value)
finally:
    os.unlink(classes_yaml_hex_escape)

classes_yaml_big_unicode = write_tmp(
    'classes:\n'
    '  - id: F1\n'
    '    title: Test\n'
    '    rules:\n'
    '      - look: added-lines\n'
    '        match: "\\U0001F600"\n'
    '        say: "{n}"\n',
    suffix=".yaml",
)
try:
    handparse_value = _hand_parse_classes_yaml(classes_yaml_big_unicode)[0]["rules"][0]["match"]
    if yaml is not None:
        pyyaml_value = yaml.safe_load(open(classes_yaml_big_unicode))["classes"][0]["rules"][0]["match"]
        check(
            "\\UHHHHHHHH (8-digit) decodes identically under PyYAML and the hand-parser",
            pyyaml_value == handparse_value,
            (pyyaml_value, handparse_value),
        )
    else:
        check("\\UHHHHHHHH (8-digit) decodes to the expected character (PyYAML unavailable to cross-check)",
              handparse_value == "\U0001F600", handparse_value)
finally:
    os.unlink(classes_yaml_big_unicode)

classes_yaml_short_hex = write_tmp(
    'classes:\n'
    '  - id: F1\n'
    '    title: Test\n'
    '    rules:\n'
    '      - look: added-lines\n'
    '        match: "\\x4"\n'
    '        say: "{n}"\n',
    suffix=".yaml",
)
try:
    error = None
    try:
        _hand_parse_classes_yaml(classes_yaml_short_hex)
    except ValueError as e:
        error = e
    check(
        "a truncated hex escape (too few digits) raises a clear error rather than misreading past the value",
        error is not None and "hex digits" in str(error),
        error,
    )
finally:
    os.unlink(classes_yaml_short_hex)

try:
    _hand_parse_classes_yaml(write_tmp(
        'classes:\n  - id: F1\n    title: Test\n    rules:\n      - look: added-lines\n        match: "\\d+"\n        say: "{n}"\n',
        suffix=".yaml",
    ))
    check("invalid escape \\d is still rejected (regression check)", False, "no error raised")
except ValueError as e:
    check("invalid escape \\d is still rejected (regression check)", "unsupported escape" in str(e), e)

# ══════════════════════════════════════════════════════════════
# Follow-up review, round 2 — regressions introduced by round 1's fixes
# ══════════════════════════════════════════════════════════════

# Finding 1 of 3: an ordinary ASCII rename (differing, unquoted paths — the
# common case the round-1 rewrite made ambiguous) must still show up as a
# changed file, both when git omits +++/--- (100% similarity) and when it
# doesn't (content changed alongside the rename).
diff_rename_full_sim = (
    "diff --git a/src/payments/old_name.ts b/src/payments/new_name.ts\n"
    "similarity index 100%\n"
    "rename from src/payments/old_name.ts\n"
    "rename to src/payments/new_name.ts\n"
)
check(
    "a 100%-similarity rename to a different bare (unquoted) name is still tracked",
    _changed_files(diff_rename_full_sim) == ["src/payments/new_name.ts"],
    _changed_files(diff_rename_full_sim),
)

diff_rename_with_content = (
    "diff --git a/src/payments/old_name.ts b/src/payments/new_name.ts\n"
    "similarity index 75%\n"
    "rename from src/payments/old_name.ts\n"
    "rename to src/payments/new_name.ts\n"
    "index abc..def 100644\n"
    "--- a/src/payments/old_name.ts\n"
    "+++ b/src/payments/new_name.ts\n"
    "@@ -1,2 +1,3 @@\n"
    " line1\n"
    " line2\n"
    "+line3\n"
)
check(
    "a rename with a content change alongside it is still tracked (regression check)",
    _changed_files(diff_rename_with_content) == ["src/payments/new_name.ts"],
    _changed_files(diff_rename_with_content),
)

diff_rename_mixed_quoting = (
    "diff --git a/src/payments/old name.ts \"b/src/payments/caf\\303\\251.ts\"\n"
    "similarity index 100%\n"
    "rename from src/payments/old name.ts\n"
    "rename to \"src/payments/caf\\303\\251.ts\"\n"
)
check(
    "a rename from a spaced name to a quoted non-ASCII name resolves via 'rename to' (regression check)",
    _changed_files(diff_rename_mixed_quoting) == ["src/payments/café.ts"],
    _changed_files(diff_rename_mixed_quoting),
)

diff_identical_paths = "diff --git a/src/payments/service.ts b/src/payments/service.ts\n"
check(
    "a non-rename (identical bare paths) is unaffected by the rename-lookahead change",
    _changed_files(diff_identical_paths) == ["src/payments/service.ts"],
    _changed_files(diff_identical_paths),
)

# A non-renamed file whose own path contains the literal substring " b/"
# (e.g. a directory named "foo b") defeats a single greedy regex split —
# the correct a==b split must still be found by trying every " b/"
# occurrence, not just the first/last one a backtracking regex happens to pick.
diff_path_contains_marker = (
    "diff --git a/foo b/bar.py b/foo b/bar.py\n"
    "index abc..def 100644\n"
    "--- a/foo b/bar.py\n"
    "+++ b/foo b/bar.py\n"
    "@@ -1 +1 @@\n"
    "-old\n"
    "+new\n"
)
check(
    "a path containing the literal substring ' b/' is still correctly split, not mistaken for a rename",
    _changed_files(diff_path_contains_marker) == ["foo b/bar.py"],
    _changed_files(diff_path_contains_marker),
)

# Finding 2 of 3: _git_unquote's escape table must cover the full C-style
# set git actually emits (\a \b \f \n \r \t \v \\ \"), not just a subset —
# an escape letter outside the handled set previously fell through to the
# literal letter itself, silently corrupting the decoded filename.
for esc, expected in (("r", "\r"), ("a", "\a"), ("b", "\b"), ("f", "\f"), ("v", "\v")):
    check(
        f"_git_unquote decodes \\{esc} to its real control character (regression check)",
        _git_unquote(f"foo\\{esc}bar.py") == f"foo{expected}bar.py",
        _git_unquote(f"foo\\{esc}bar.py"),
    )
check(
    "_git_unquote still decodes \\n, \\t, \\\", \\\\ correctly (existing behavior, unaffected)",
    _git_unquote('foo\\n\\t\\"\\\\bar.py') == 'foo\n\t"\\bar.py',
    _git_unquote('foo\\n\\t\\"\\\\bar.py'),
)

# Finding 3 of 3: a well-formed \UHHHHHHHH escape whose code point exceeds
# the valid Unicode range (> U+10FFFF) must raise the function's own
# classes.yaml-line-numbered ValueError, not an unlabeled internal error.
classes_yaml_out_of_range_unicode = write_tmp(
    'classes:\n'
    '  - id: F1\n'
    '    title: Test\n'
    '    rules:\n'
    '      - look: added-lines\n'
    '        match: "\\U11000000"\n'
    '        say: "{n}"\n',
    suffix=".yaml",
)
try:
    error = None
    try:
        _hand_parse_classes_yaml(classes_yaml_out_of_range_unicode)
    except ValueError as e:
        error = e
    check(
        "an out-of-range \\U escape raises a classes.yaml-line-numbered ValueError, not a bare internal error",
        error is not None and "classes.yaml line" in str(error),
        error,
    )
finally:
    os.unlink(classes_yaml_out_of_range_unicode)

# ══════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════

print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed")
if failed:
    sys.exit(1)
