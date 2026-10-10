# RFC: Card payment capture and refund (F1)

> See [product spec](../product/paymentslatest.md) for product context.

Owner: payments-engineering. Version 1.3, restructured into the SPEED RFC template. The
requirements TR1 to TR12, the goals and the scope are unchanged from
[`specs/tech/payments.md`](payments.md). The sections the template adds describe the
service as it exists in `src/`, and anything not yet decided is listed under Unresolved
Questions rather than assumed.

An in-memory payments service covering authorise, capture, refund and void, with a
double-entry ledger and a token vault. No database and no network. Money is integer minor
units throughout.

Goals:

- Every movement of money is recorded as a balanced pair, so the ledger can be reconciled
  without reference to application state.
- The four invariants TR6 to TR9 hold after any sequence of operations, not only after the
  scenarios anyone thought to write down.
- A card number exists in exactly one module and leaves it only as a token.

## Basic Example

A merchant authorises 100.00 on a scheme test card, ships two items separately, refunds
part of the first shipment and asks for the capture to be settled in three instalments.
The scheme fee rate is 1.49%.

```text
authorise   amount 10000, idempotency key k1      -> pay_000001, status authorised
capture     pay_000001, amount 6000                -> cap_000002, fee 89, merchant net 5911
capture     pay_000001, amount 4000                -> cap_000003, fee 60, merchant net 3940
capture     pay_000001, amount 1                   -> rejected: exceeds remaining 0
refund      pay_000001, cap_000002, amount 2500    -> ref_000004
settlement  pay_000001, 3 instalments              -> 3334, 3333, 3333 (sums to 10000)
checkAll                                           -> no violations
```

Repeating the authorise with key k1 returns pay_000001 and creates no second payment.

## Interface Contract

This is a standalone RFC with no parent RFC and no prerequisite sibling RFCs. The section
records what other features rely on, because the adaptive authorisation work in
[`adaptive-auth/1-high-value-traveller.md`](adaptive-auth/1-high-value-traveller.md)
calls into this service through `src/payments/gateway.ts`.

### Consumes (from prerequisite RFCs)

Nothing. The service depends only on modules defined in this RFC.

### Produces (for downstream RFCs)

- `PaymentsService.authorise(request)` returning a `Payment`, called by the authorisation gateway.
- `PaymentsService.capture`, `refund`, `void` and `settlementSchedule`, with the signatures in API Surface.
- `checkAll(ledger, store)` returning a list of invariant violations, used by the workbench commands.
- `tokenise`, `maskedFor` and `redact`, the card-data boundary every other module must use.

## Data Model

All state lives in memory for the lifetime of the process. Amounts are integer minor
units of type `Minor`. Identifiers are opaque strings with a type prefix.

**Payment** (`src/payments/service.ts`), one per authorisation:

| Field | Type | Nullable | Notes |
|-------|------|----------|-------|
| id | string | no | Prefix `pay_` |
| token | Token | no | Vault token; never the card number |
| last4 | string | no | For display only |
| authorised | Minor | no | Amount reserved at authorisation |
| currency | string | no | Defaults to GBP; single currency only |
| status | authorised, captured or voided | no | See State Machine |
| captures | Capture list | no | Empty until the first capture |
| refunds | Refund list | no | Empty until the first refund |

**Capture**: `id` (prefix `cap_`), `amount` (Minor, gross captured amount), `at` (epoch
milliseconds). Belongs to exactly one Payment.

**Refund**: `id` (prefix `ref_`), `amount` (Minor), `captureId` (must reference a Capture
on the same Payment), `at`. Belongs to exactly one Payment.

**Ledger entry** (`src/domain/ledger.ts`): `id`, `pairId`, `account`, `amount` (signed
Minor), `paymentId`, `kind` (authorise, capture, refund or void), `at`. Entries are only
ever written in pairs that share a `pairId` and net to zero (TR5, TR6).

**Ledger accounts**: `cardholder`, `merchant_receivable`, `merchant_settled`,
`scheme_fees`, `refunds_payable`.

**Card record** (`src/vault.ts`): `token`, `last4`, `bin` (first six digits), `expiry`.
The card number itself is never stored, including inside the vault.

**Idempotency record**: a map from idempotency key to the result first returned for it.
Authorise stores the Payment and capture stores the Capture (TR10).

**Instalment schedule**: a list of Minor values produced on request by
`settlementSchedule`. It is computed from the captured total and is not stored.

**Scheme fee**: a rate of 1.49% applied to each capture with half-up rounding (TR3, TR4).
The fee and the merchant net are posted as separate ledger pairs.

Ledger postings per operation:

| Operation | Debit | Credit | Amount |
|-----------|-------|--------|--------|
| authorise | cardholder | merchant_receivable | authorised amount |
| capture | merchant_receivable | merchant_settled | captured amount less fee |
| capture | merchant_receivable | scheme_fees | fee |
| refund | merchant_settled | refunds_payable | refunded amount |
| void | merchant_receivable | cardholder | authorised amount |

## State Machine

A Payment moves through these states. Refunds do not change the Payment status.

| From | To | Trigger | Side effects |
|------|----|---------|--------------|
| (none) | authorised | `authorise` succeeds | Card tokenised, Payment stored, authorise pair posted |
| authorised | captured | First `capture` succeeds | Capture recorded, net and fee pairs posted |
| captured | captured | A further partial `capture` within the remaining amount | Capture recorded, net and fee pairs posted |
| authorised | voided | `void` on a Payment with no captures | Void pair posted, reservation released |

Impossible transitions:

- captured to voided is not allowed, because money has already moved. `void` is rejected (ST5).
- voided to captured is not allowed, because the reservation has been released. See Unresolved Questions for the current code's behaviour.
- A capture that would take the captured total above the authorised amount is rejected, not truncated (TR7).

## API Surface

All operations are methods on `PaymentsService` in `src/payments/service.ts`. Errors are
thrown as `RangeError` with the message shown; nothing is partially written when an
operation throws.

| Operation | Input | Returns | Errors |
|-----------|-------|---------|--------|
| `authorise(request)` | card number, expiry, amount (integer minor units), optional currency, optional idempotency key | `Payment` with status authorised | Fractional amount: "money must be integer minor units, got X". A tokenisation failure is logged through `serialiseFailure(error, redact(request))` and rethrown |
| `capture(paymentId, amount?, idempotencyKey?)` | Payment ID, amount defaulting to the remaining authorised amount, optional idempotency key | `Capture` | Unknown payment: "unknown payment P". Amount above remaining: "capture X exceeds remaining Y". Fractional amount as for authorise |
| `refund(paymentId, captureId, amount?)` | Payment ID, capture ID, amount defaulting to that capture's amount | `Refund` | Unknown payment. Unknown capture: "no capture C on P". Total refunds above total captured: "refund X exceeds refundable Y" |
| `void(paymentId)` | Payment ID | `Payment` with status voided | Unknown payment. Payment with any capture: "cannot void a captured payment" |
| `settlementSchedule(paymentId, instalments)` | Payment ID, number of instalments | List of Minor values | Unknown payment. Fewer than one instalment: "parts must be at least 1" |

Idempotency (TR10): when `authorise` or `capture` receives a key it has already seen, it
returns the original result and writes nothing. Refund does not take an idempotency key,
because TR10 covers authorise and capture only.

Side effects visible outside the service: `authorise` logs and emits a telemetry span with
the masked card, `capture` emits a span with amount, fee and net, and `refund` logs and
sends a webhook carrying the masked card. All of them pass through the controls in
Security & Controls.

## Validation Rules

These are the technical requirements from version 1.3, unchanged. Each one maps to at least
one test in Testing.

| Field | Constraints |
|-------|-------------|
| TR1 | All monetary values are integer minor units. Floating point must not appear in any money path, including intermediate calculations |
| TR2 | `sum(allocate(a, n)) === a` for every amount `a` and every part count `n` |
| TR3 | The scheme fee and the merchant net sum exactly to the captured amount |
| TR4 | A rate is applied with half-up rounding on the absolute value, so negative amounts round symmetrically. Truncation must not be used |
| TR5 | Every state change writes a balanced double-entry pair. No module writes a single entry |
| TR6 | `LEDGER_BALANCED`: every ledger pair nets to zero |
| TR7 | `CAPTURE_WITHIN_AUTH`: the sum of captures never exceeds the authorised amount |
| TR8 | `REFUND_TRACES_CAPTURE`: every refund references a capture that exists, and refunds never exceed it |
| TR9 | `NO_PAN_AT_REST`: no stored record holds a Luhn-valid card number outside the vault. Length alone is insufficient, because a millisecond timestamp is thirteen digits |
| TR10 | Authorise and capture accept an idempotency key and return the original result for a repeated key |
| TR11 | Any value reaching one of the five observability surfaces is tokenised or redacted first. `redact` is the sanitiser at the serialised exception boundary |
| TR12 | Every card number in the repository is a published scheme test BIN. Real or plausible non-test card numbers must not appear, including in history |

## Testing

### Acceptance Criteria

Each criterion traces to a product success criterion or story and gates the feature.

- Captures against one authorisation never sum to more than the authorised amount, and a capture beyond it is rejected rather than truncated (ST2, TR7).
- For every captured amount, the scheme fee and the merchant net sum exactly to the capture (ST3, TR3).
- Every refund references a capture that exists, and total refunds never exceed total captures (ST4, TR8).
- An uncaptured authorisation can be voided and its reservation released. A captured payment cannot be voided (ST5).
- A repeated authorise or capture carrying a seen idempotency key returns the original result and creates no second record (ST6, TR10).
- Instalments sum exactly to the captured amount for any number of instalments, including 99.99 in 7 instalments (ST7, TR2).
- No stored record holds a Luhn-valid card number, and no card number reaches a log, webhook, span, fixture or serialised error (TR9, TR11).
- `checkAll` reports no violations after a generated sequence of operations, not only after a fixed scenario (TR6 to TR9).

### Risks and Coverage

| Risk | Severity | Test Approach |
|------|----------|---------------|
| Rounding drift between fee and net leaves the ledger short | High | Unit tests on `applyRate` and an integration assertion that fee plus net equals each capture |
| Instalment schedules lose or create a minor unit | Medium | Unit tests on `allocate` across amounts and part counts, and the differential corpus |
| A card number reaches an observability surface | Critical | The pan-scan, secret-scan and taint hooks, plus integration tests that inspect every sink after each operation |
| An invariant breaks only under an unusual operation order | High | The generated-sequence property command across seeded operation sequences |
| A single ledger entry is written without its pair | High | A ledger unit test and `LEDGER_BALANCED` after every integration scenario |
| A retried request creates a duplicate authorisation or capture | High | Integration tests that repeat requests with the same idempotency key |

### Test Plan

**Unit tests**

`test/money.test.ts` covers `minor`, `allocate` and `applyRate`, including negative amounts
and fractional input. `test/ledger.test.ts` covers balanced posting and net-zero totals
across many postings.

**Integration tests**

`test/service.test.ts` drives `PaymentsService` end to end in memory: authorise, full and
partial capture, refund, void, idempotent replay and settlement schedules, asserting
`checkAll` returns no violations after each scenario.

**End-to-end tests**

There is no external interface, so the end-to-end level is the workbench run: the
invariant, property, mutation and differential commands exercise the service as a whole
and are run by `bin/workbench validate`.

**Visual/UI tests**

The feature has no user interface, so no visual tests are needed.

### Edge Cases

- A capture of exactly the remaining amount succeeds, and a capture of one more minor unit is rejected.
- A capture with no amount takes the whole remaining authorisation.
- An amount of 1 minor unit, and an amount that does not divide evenly by the instalment count.
- Negative values passed to `applyRate`, which must round symmetrically.
- A refund whose amount would take total refunds above total captures, and a refund against a capture ID from another payment.
- A void after a partial capture, which must be rejected.
- A 13-digit millisecond timestamp in a stored record, which must not be reported as a card number.
- A repeated idempotency key on capture after the authorisation has changed.

### Out of Scope

- Persistence. State lives in memory for the lifetime of the process.
- Concurrency control. Operations are sequential, so contention is out of scope for this version.
- Settlement file generation. The schedule is produced; the file format is not.
- Performance and load testing, because the service runs in memory and a full exercise completes in seconds.

## Security & Controls

There is no authentication or network surface: the service is an in-process module, so
access control belongs to the caller. The controls that matter are about card data.

- **Card data at rest.** Card data enters once, at authorisation, and is exchanged for a token in `src/vault.ts`. Only the BIN, last four and expiry are retained. No stored record may hold a Luhn-valid card number (TR9).
- **Card data in transit out of the process.** The five observability surfaces are the application log, webhook bodies, telemetry attributes, test fixture files and the serialised exception path. Anything reaching them is tokenised or masked with `maskedFor`, or redacted with `redact` (TR11).
- **Repository hygiene.** Every card number in the repository is a published scheme test BIN, enforced by the pan-scan hook with its documented test-BIN allowlist (TR12).
- **Input validation.** Fractional money is rejected at construction, and capture and refund amounts are checked against what remains before anything is written.
- **Audit trail.** Every money movement is a ledger pair carrying the payment ID and operation kind, so the ledger alone reconstructs what happened.

## Key Decisions

| Decision | Choice | Alternatives Considered | Rationale |
|----------|--------|------------------------|-----------|
| Money representation | Integer minor units through a branded `Minor` type | Floating-point amounts; a decimal library | Integers make conservation exact and checkable, and keep the repository free of dependencies |
| Rounding of rates | Half-up on the absolute value | Banker's rounding; truncation | Matches the statement the scheme produces and treats negative amounts symmetrically (TR4) |
| Splitting amounts | Distribute the remainder one unit at a time across the leading parts | Round each part independently | Rounding each part can create or lose a minor unit, which breaks TR2 |
| Recording money | Double-entry pairs written only by `Ledger.post` | Single-entry balance updates on the payment | Pairs make `LEDGER_BALANCED` assertable after any operation sequence |
| Card data | Tokenise at the vault boundary and keep BIN and last four only | Encrypt the card number at rest | A card number that is never stored cannot leak from storage |
| Retries | Idempotency keys on authorise and capture | Deduplicate on request payload | Keys are explicit and match how merchants retry after a timeout |
| Storage | In memory for the lifetime of the process | A database | The service exists to be exercised quickly and deterministically |

## Drawbacks

- State is lost when the process stops, so the service cannot be used for anything that needs durable records.
- Operations are sequential. The idempotency store and the capture checks are not safe under concurrent requests, which a real deployment with several replicas would need.
- A single flat scheme fee rate cannot express different rates by card type.
- The idempotency store keeps every key forever, so memory grows with request volume.

## Search / Query Strategy

The service introduces no queries beyond lookups by ID. Payments and idempotency records
are held in maps keyed by ID, so lookups are constant time. Ledger entries for one payment
are found by a linear scan, which is acceptable for the in-memory volumes this service
handles.

## Migration Strategy

There is no data to migrate. All state is in memory and is rebuilt on each run, and this
revision changes the document's structure, not the service's behaviour.

## File Impact

- `src/domain/money.ts`: the only module that constructs monetary values; `minor`, `add`, `sub`, `allocate`, `applyRate`.
- `src/domain/ledger.ts`: `Ledger.post`, the only ledger writer, and the five accounts.
- `src/domain/invariants.ts`: `LEDGER_BALANCED`, `CAPTURE_WITHIN_AUTH`, `REFUND_TRACES_CAPTURE`, `NO_PAN_AT_REST` and `checkAll`.
- `src/vault.ts`: `tokenise`, `describe`, `maskedFor`.
- `src/payments/service.ts`: `PaymentsService` with authorise, capture, refund, void and settlementSchedule.
- `src/obs/index.ts`: the log, span and webhook sinks, `redact` and `serialiseFailure`.
- `test/money.test.ts`, `test/ledger.test.ts`, `test/service.test.ts` and `test/fixtures/cards.ts`.
- `workbench/commands/invariant.ts`, `property.ts`, `mutation.ts` and `differential.ts`, which exercise the service.

## Dependencies

- The token vault in `src/vault.ts`. Every downstream record carries a token rather than a card number, as the product spec requires.
- Node 22 or later with native TypeScript type stripping, and no installed packages, so the service and its tests run with no install step.

## Unresolved Questions

- **Does the scheme fee rate vary by card type?** Blocks the fee calculation for commercial cards. Proposed path: scheme relations to answer; until then the single 1.49% rate applies to every capture.
- **Who owns the decision to release a void after the authorisation has expired?** Blocks the expiry path, and authorisation expiry is not defined anywhere yet. Proposed path: payments-operations to decide before an expiry path is planned.
- **Should authorisation post to the ledger?** ST1 says no money moves at authorisation, while TR5 asks for a balanced pair on every state change and the current service posts an authorise pair. Blocks any change to the authorise and void ledger postings. Proposed path: payments-engineering and finance to agree whether the authorise pair is a reservation record or a money movement.
- **Should a voided payment reject further captures?** The State Machine treats voided to captured as impossible, but the current `capture` does not check the status. Blocks the capture status check and its test. Proposed path: confirm the rule with payments-product, then add the check and a test.
