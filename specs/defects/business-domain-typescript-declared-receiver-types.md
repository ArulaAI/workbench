# Defect: TypeScript calls on values typed away from the call stay open, and the facts summary misreads as failure

Severity: P2
Related Feature: speed-business-domain-discovery
Status: Resolved
Related Defects: business-domain-typescript-evidence-gaps
Tags: typescript, receivers, platform-calls, type-guards, facts-only, terminal-output

## Summary

After the evidence-gaps fix, `speed discover domains --facts-only` on the Payments Validation Fixtures repository left 27 call sites open on traces. Every one was a platform method (`push`, `reduce`, `slice`, `padStart`) on a value whose type the source declares, only not where the call is:

| Call | Where the type is declared |
| --- | --- |
| `payment.captures.reduce(...)` | `const payment = this.require(id)`, `require(): Payment`, `Payment.captures: Capture[]` |
| `req.pan.replace(...)` | `req: GatewayRequest`, `GatewayRequest = AuthoriseRequest & {...}`, `AuthoriseRequest.pan: string` |
| `sinks.logs.push(...)` | `const sinks = { logs: [] as LogRecord[] }` |
| `(++seq).toString(36).padStart(6, '0')` | an increment is a number; `Number.toString` returns a string |
| `digits.slice(0, 6)` | `const digits = pan.replace(...)`, `pan: string` |
| `p.captures.reduce(...)` | `for (const p of store.values())`, `store: PaymentStore = Map<string, Payment>` |
| `value.map(redact)` | `if (Array.isArray(value))`, a guard the platform declares |

Nine of twelve traces were reported incomplete because of these calls, and the summary led with `Traces: 1/12 resolved (11 unresolved)` and `Missing call targets 9 traces`. A reader concluded discovery had failed, when every trace reached all of its business code.

## Root causes and resolution

1. **Declared types were read only at the call.** `rules.receiver_types` binds a receiver from a catalog rule that matches its own declaration (`this.items = new Map()`). A new module, `business_domain_adapters/ts_types.py`, evaluates the receiver expression instead. Each step reads something written:

   | Step | Example |
   | --- | --- |
   | Parameter and local annotations, and initializers | `req: Routed`, `const out: Violation[] = []`, `const digits = pan.replace(...)` |
   | `as` assertions | `[] as LogRecord[]` |
   | Type aliases, interfaces, intersections, unions with `undefined` | `PaymentStore = Map<string, Payment>` |
   | Members of object types, object literals and classes | `Payment.captures`, `sinks.logs`, `this.attempts` |
   | Declared return types of functions and methods | `require(): Payment`, `strings(): string[]` |
   | Imports between repository files | `import { type Payment } from './service.ts'` |
   | Return types the platform declares for its own methods | `String.replace` returns a string; `Map.get` returns the value type |
   | Loop variables, increments, arithmetic, `??` | `for (const p of store.values())`, `(++seq)`, `(m / 100)` |
   | Type guards in an `if` condition or `?:` test | `Array.isArray(value)`, `typeof value === 'string'` |

   `ts_semantic.resolve_call` consults it only after the existing resolution leaves a call unresolved, so no existing result changes. A receiver typed as a repository class also resolves the call to that class's method (`owner.ledger.net()` reaches `Ledger.net`).

2. **The reason did not say why.** A classified call's reason now ends with its derivation, read from the receiver down, each step with its file and line: `payment.captures is declared as Array, a type typescript provides; reduce is its method. Declared by: payment = this.require(paymentId) (src/payments/service.ts:105); PaymentsService.require(): Payment (src/payments/service.ts:205); ...`.

3. **The summary counted the wrong thing first.** `facts_only` now returns a `report` (`business_domain_cli.facts_report`) and the terminal leads with whether each entry point reached a known end. Traces are split into complete, bounded and open. Every call site on a trace is counted once as repository, platform, library, ambiguous or open. Platforms are named, each open site is listed with its line, and data files that were not analysed say whether any facts were lost. Existing JSON fields are unchanged.

What stays unresolved, by design:

- `any`, `unknown` and untyped parameters, and contextually typed callback parameters (`validate: (value) => ...` typed only by `IConstraint`).
- A negated or `||`-joined guard, and narrowing after an early return.
- JavaScript. An initializer there is not a declaration: a `let` holding an array may later hold anything. Only `typescript` and `tsx` sources are indexed.

## Effect on the fixture (`--facts-only`)

| Measurement | Before | After |
| --- | --- | --- |
| Unresolved call sites on traces | 27 | 0 |
| Traces complete / bounded / incomplete | 1 / 2 / 9 | 1 / 11 / 0 |
| Calls resolved into the repository (whole graph) | 356 | 357 |
| Extraction time | 1.92 s | 2.01 s |

PetClinic keeps the same symbols, anchors, traces and resolutions. Three call edges change from open to platform calls (`pettypes.map`, `owners.map`, `owner.pets.map`), and extraction time goes from 6.92 s to 7.05 s.

## Acceptance tests

| File | Covers |
| --- | --- |
| `tests/test_business_domain_typescript_declared_types.py` (13 tests) | each step above; guards that must not narrow; `any`, untyped and shadowed receivers stay unresolved; JavaScript is not typed |
| `tests/test_business_domain_facts_report.py` (7 tests) | call-site classes add up; open sites carry their line; unanalysed files; relationship parts add up; the summary headline, open-site list and plain output without a terminal |
| `tests/test_business_domain_typescript_evidence.py` | `guess(input: any)` replaces `guess(input: string[])`, which is now declared; `first(input: string[])` is the declared counterpart |
| Render tests in `test_business_domain_measurement.py`, `test_business_domain_trace_blockers.py`, `test_business_domain_entrypoint_coverage.py` | the same assertions against the new layout |
