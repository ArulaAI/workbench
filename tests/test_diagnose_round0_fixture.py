#!/usr/bin/env python3
"""test_diagnose_round0_fixture.py — Regression test proving the Diagnose
engine correctly processes the REAL `payments-validation-fixture` round-0
diff, not just hand-written synthetic examples.

Inputs are frozen, real artifacts captured from the actual project:
  - tests/fixtures/round-0.diff   — literal `git diff main...round-0` output
  - CLASSES_YAML below            — the real .speed/classes.yaml content
  - SPEC_MD below                 — the real specs/product/payments.md content

This is a snapshot for regression testing, not a live mirror of the fixture
repo — see the provenance header in tests/fixtures/round-0.diff for the
exact commit SHAs it was captured at. If round-0 changes, this test (and
that fixture file) need to be recaptured.

Usage: python3 tests/test_diagnose_round0_fixture.py
"""

import os
import sys
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from lib.diagnose_engine import diagnose

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


# The real .speed/classes.yaml from payments-validation-fixture (config/speed-diagnose
# branch) — the actual F1-F8 rules the project declared, not a test-only rewrite.
CLASSES_YAML = r"""# Project-owned failure-class rules for `speed diagnose`. Every rule here
# is a routing hint toward a real downstream check (typecheck, mutation,
# invariant, differential, etc.) — none of them execute or approximate
# that check, and an absent signal never means the failure is absent.

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

# The real specs/product/payments.md from payments-validation-fixture's main branch —
# used by the new-names-absent-from-spec (F8) rule.
SPEC_MD = r"""# F1: Card payment capture and refund

Owner: payments-product. Version 1.3.
Related: [`specs/tech/payments.md`](../tech/payments.md)

## Problem

Merchants take card payments before they know the final amount. A restaurant authorises
for the bill and captures after the tip is added. A retailer authorises at checkout and
captures when the item ships. Without a split between authorisation and capture they must
either hold the wrong amount or ask the cardholder to pay twice.

When goods come back, the merchant owes money to the cardholder and needs that movement
recorded against the original capture rather than as a fresh payment in the opposite
direction.

## Users

- A merchant who needs to reserve funds now and take a different amount later.
- A cardholder who expects the amount taken to match what they agreed, and expects money
  back when they return goods.
- A finance operator who has to reconcile what the scheme settled against what the ledger
  says, and who is accountable when the two disagree.

## User Stories

| ID | Story | Acceptance Criteria | Priority |
|----|-------|---------------------|----------|
| ST1 | As a merchant, I want to authorise a payment, so that funds are reserved before I know the final amount | Given a valid card, When I authorise for an amount, Then the amount is reserved and no money moves | Must |
| ST2 | As a merchant, I want to capture part of an authorisation, so that I take only what I am owed | Given an authorisation for 10.00, When I capture 6.00 and then 4.00, Then both succeed and a third capture is rejected | Must |
| ST3 | As a finance operator, I want the scheme fee deducted at capture, so that settlement matches the statement | Given a capture of 100.00, When the fee rate is 1.49%, Then the merchant receives the captured amount less the fee and the two sum to the capture | Must |
| ST4 | As a cardholder, I want money returned against the original capture, so that the refund is traceable | Given a capture of 50.00, When a refund of 20.00 is issued against it, Then the refund references that capture and cannot exceed it | Must |
| ST5 | As a merchant, I want to void an authorisation I never captured, so that I release the cardholder's funds | Given an uncaptured authorisation, When I void it, Then the reservation is released. Given a captured payment, When I void it, Then the request is rejected | Must |
| ST6 | As a merchant, I want a retried authorisation or capture to be safe, so that a network timeout does not charge twice | Given a request carrying an idempotency key already seen, When it is retried, Then the original result is returned and no second record is created | Must |
| ST7 | As a finance operator, I want a capture paid out in instalments, so that large amounts settle over time | Given a capture of 99.99 and 7 instalments, When the schedule is produced, Then the instalments sum exactly to 99.99 | Should |

## User Flows

**Authorise then capture in full.** The merchant authorises for the basket total. Funds
are reserved. On dispatch the merchant captures the full amount. The scheme fee is
deducted and the remainder is owed to the merchant.

**Authorise then capture in part.** The merchant authorises for an estimate. Two items
ship separately, so the merchant captures twice. The sum of the two captures cannot exceed
the authorisation, and an attempt to capture beyond it is rejected rather than truncated.

**Refund after capture.** A cardholder returns one item. The merchant issues a refund
against the capture that paid for it. The refund cannot exceed what that capture took.

**Void before capture.** An order is cancelled before dispatch. The merchant voids the
authorisation and the reservation is released. A payment that has already been captured
cannot be voided.

**Retry after a timeout.** A merchant's request times out with no response. They retry
with the same idempotency key. The original result comes back and no second authorisation
or capture is created.

## Success Criteria

- [ ] Captures against a single authorisation never sum to more than the authorised amount
- [ ] Scheme fee and merchant net sum exactly to the captured amount for every amount
- [ ] Every refund references a capture that exists and never exceeds it
- [ ] Instalments sum exactly to the captured amount for any number of instalments
- [ ] A repeated authorise or capture carrying a seen idempotency key creates no second record
- [ ] No full card number is stored outside the token vault

## Scope

### In Scope

- Authorise, capture including partial capture, refund and void
- Scheme fee deduction at capture
- Idempotency on authorise and capture
- Instalment settlement schedules
- Double-entry recording of every movement

### Out of Scope (and why)

- **Chargebacks.** Requires the dispute lifecycle and scheme messaging, which lands with
  the disputes work in a later version.
- **Multi-currency.** Needs an FX rate source and a settlement currency decision that
  finance has not made.
- **Partial reversals of a refund.** No merchant has asked for it and it doubles the
  refund state machine.
- **Network tokenisation.** Blocked on the scheme certification programme.

## Dependencies

Requires the token vault for card storage. Every downstream record carries a token rather
than a card number.

## Security & Controls

Card data enters once, at authorisation, and is exchanged for a token. Only the last four
digits and the BIN are retained for display and routing.

No full card number may appear in a log, a webhook body, telemetry, a test fixture or a
serialised error.

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Rounding drift between fee and net leaves the ledger short | High | Fee and net must sum exactly to the capture, asserted per transaction |
| A card number reaches an observability surface | Critical | Tokenise at the boundary and redact before any value leaves the process |
| Instalment schedules lose or create a minor unit | Medium | Allocation conserves the total by construction |

## Open Questions

- Does the scheme fee rate vary by card type? Blocks the fee calculation for commercial
  cards. Answer needed from scheme relations.
- Who owns the decision to release a void after the authorisation has expired? Blocks the
  expiry path. Answer needed from payments-operations.
"""

FIXTURE_DIFF_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "round-0.diff")

DECLARED_FILES = [
    "src/payments/retry.ts",
    "src/payments/service.ts",
    "test/refund-retry.test.ts",
    "test/fixtures/cards.ts",
]

EXPECTED_SIGNAL_COUNTS = {
    "F1": 1,
    "F2": 2,
    "F3": 1,
    "F4": 1,
    "F5": 0,
    "F6": 0,
    "F7": 1,
    "F8": 1,
}


def main():
    with open(FIXTURE_DIFF_PATH, "r") as f:
        diff_text = f.read()

    classes_yaml_path = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False).name
    with open(classes_yaml_path, "w") as f:
        f.write(CLASSES_YAML)

    spec_path = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False).name
    with open(spec_path, "w") as f:
        f.write(SPEC_MD)

    try:
        result = diagnose(classes_yaml_path, diff_text, DECLARED_FILES, spec_path)
    finally:
        os.unlink(classes_yaml_path)
        os.unlink(spec_path)

    by_id = {cls["id"]: cls for cls in result}

    check(
        "all eight F1-F8 classes are present in the result",
        set(by_id.keys()) == set(EXPECTED_SIGNAL_COUNTS.keys()),
        sorted(by_id.keys()),
    )

    for class_id, expected_count in EXPECTED_SIGNAL_COUNTS.items():
        actual_count = len(by_id[class_id]["signals"]) if class_id in by_id else -1
        check(
            f"{class_id} has {expected_count} signal(s) on the real round-0 diff",
            actual_count == expected_count,
            f"expected {expected_count}, got {actual_count}: {by_id.get(class_id, {}).get('signals')}",
        )

    # The engine's own contract: no rule can ever populate a verdict field.
    # diagnose() only returns id/title/signals per class — verify that
    # structurally, not just that the CLI writer hardcodes "undecided".
    check(
        "no class result carries a plausible/costOfMissing/findableByReading key",
        all(
            "plausible" not in cls and "costOfMissing" not in cls and "findableByReading" not in cls
            for cls in result
        ),
        result,
    )

    print(f"\n{'='*40}")
    print(f"Results: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
