# F1: Card payment capture and refund

Owner: payments-product. Version 1.3.
Related: [`specs/tech/paymentslatest.md`](../tech/paymentslatest.md)

Same product requirements as [`specs/product/payments.md`](payments.md), paired with the
RFC-format tech spec. Only the links and the RFC Decomposition section differ.

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

## RFC Decomposition

The feature fits in a single RFC: every story changes the same payments service and its
money, ledger and vault modules, so splitting it would put two RFCs on the same files.

| User Story IDs | Child RFC | Depends On | Testable Output |
|----------------|-----------|------------|-----------------|
| ST1, ST2, ST3, ST4, ST5, ST6, ST7 | `specs/tech/paymentslatest.md` | (none) | `PaymentsService` operations pass `test/service.test.ts`, and `checkAll` reports no violations after generated operation sequences |

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
