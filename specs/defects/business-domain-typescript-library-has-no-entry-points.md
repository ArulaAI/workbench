# Defect: A TypeScript library yields no entry points, and discovery publishes nothing useful

Severity: P1
Related Feature: speed-business-domain-discovery
Status: Resolved
Tags: anchors, typescript, javascript, library, receivers, imports, rule-observations, cli, publication

## Summary

Discovery on the Payments Validation Fixtures repository, a plain TypeScript library with no HTTP framework and no UI, extracted 0 entry points, 0 traces and 0 rule observations. The full pipeline then called the model anyway and could only return an empty model. A failed attempt also reported the previous build as if it had just been published.

The tech specification already names "CLI operations and exported library APIs where supported" as candidate anchors, and the artifact schema already lists `library` and `cli` as operation protocols. No adapter produced them.

## Evidence

Repository: `ArulaAI/payments-validation-fixture`, branch `feat/301-define-audit-plan-config`, commit `432dedd`. Ten files under `src/` hold the behaviour: `PaymentsService` (authorise, capture, refund, void, settlementSchedule), `AuthorisationGateway`, `RiskRules`, `Ledger`, plus money, vault and observability helpers.

| Measurement (`--facts-only`) | Before | After |
| --- | --- | --- |
| Entry points | 0 (`ENTRYPOINT_NONE_DETECTED`) | 12, all `library_export`, all resolved |
| Traces | 0 | 12; capture reaches `Ledger.post`, `applyRate`, `sub`; gateway authorise reaches `RiskRules.evaluate`, `issuerCountry`, `PaymentsService.authorise`, `tokenise` |
| Rule observations | 0 | 89 |
| Resolved relationships | 62 | 236 |
| Warnings | 7 | 6 (`SOURCE_CAPABILITY_UNAVAILABLE` for the JSON/YAML in `corpus/`) |

Before the fix, a full run on a repository with no anchors made 3 provider calls.

## Root causes

Six independent defects combined.

1. **No library anchors.** `rules/typescript/business.yml` declared no `business_anchor` rule, and `extraction.toml` limited rule-based entry-point detection to Java, JSX, Python and TSX. The rules adapter also gave an exact identity only to `http` anchors, so any other kind stayed `unresolved`.
2. **Relative imports with an extension did not resolve.** `csg._resolve_reference` compared `src/domain/money.ts` (from `'../domain/money.ts'`) with the extensionless stem `src/domain/money`. TypeScript's `allowImportingTsExtensions` and ESM `.js` specifiers both name the same module.
3. **Methods were named after their modifier.** `ts-method` and `js-method` captured no `$NAME`, so name extraction fell back to the first word of the method text. `private nextId()` became a method named `private`, and JavaScript `static`, `async`, `get` and `set` methods failed the same way.
4. **Calls through class members did not resolve.** Calls carry the receiver `this.ledger`, while no TypeScript rule bound a member to a type. Typed fields (`readonly rules: RiskRules`), `new`-initialised fields (`readonly ledger = new Ledger()`) and constructor parameter properties (`constructor(private readonly payments: PaymentsService)`) were all invisible.
5. **No TypeScript rule observations.** Java and TSX observe conditions; TypeScript did not, so guards such as `requested > remaining` never reached synthesis as rule evidence.
6. **Pipeline outcome.**
   - `discover` had no check between extraction and `synthesis.run`, so zero anchors still cost model calls.
   - On failure, `discover` returns the preserved model and `cli.run` set `published: model is not None`, so a failed attempt reported `published: true` with the previous build ID. The status renderer never printed the phase.

## Resolution

- `rules/typescript/business.yml`:
  - `ts-library-api-entrypoint` anchors the public methods of exported classes. It skips private, protected and `#` members, constructors, unexported classes and free functions. Test sources already lose anchor status in `Extractor.add_unit`.
  - Three receiver bindings cover typed fields, constructed fields and parameter properties.
  - `ts-conditional-observation` observes conditions, except inside Angular `@Component` classes.
- `rules.py` resolves `library` anchors with the identity `library:<scope>:<module>::<Class.method>` (`base.library_identity`) and registration kind `library_export`. It also supports `receiver_prefix` and `scope_kinds` on receiver bindings.
- `extraction.toml` adds `typescript` to rule-based entry-point detection.
- `csg._resolve_reference` drops a script extension from a relative specifier before comparing stems.
- `ts-method` and `js-method` capture the method name field.
- `business_domains.discover` raises `NO_ENTRY_POINTS` before constructing the synthesis when no anchor has an established identity. Facts are still written, nothing is published, the previous model is preserved and the exit code is 1.
- `business_domain_cli.run` reports `published` only for an attempt that published its own build, and names a surviving earlier build as `preserved_build_id`. `domains.sh` prints the outcome, attempt ID, preserved build and error code.

CLI entry points are deliberately not added. In this repository `bin/workbench` is the course's verification harness, not payments behaviour, and anchoring it would put tooling activities into the business model. A CLI detector needs its own design for telling product commands from tooling.

## Acceptance tests

`tests/test_business_domain_typescript_library.py` (25 tests). Run against `69ac901`, 20 fail. The 5 that pass there either assert an exclusion, which holds while TypeScript has no anchors or observations at all, or check behaviour that was already correct: extensionless imports and rejection of an unknown setting. All 25 pass after the fix.

| Area | Tests |
| --- | --- |
| Library anchors | exported public methods resolve with exact identity; helpers, constructors, private, protected, `#`, unexported and test members are excluded; no entry-point gap remains |
| Traces | capture reaches ledger, risk, money and a private method; a parameter property reaches the injected service |
| Naming and imports | TS private and JS static/async/get methods; `.ts`, `.js`, `.mjs` and extensionless specifiers |
| Observations | library guards are `api` observations; Angular component conditions are not |
| Zero anchors | no provider call, `NO_ENTRY_POINTS`, nothing published; a previous publication is preserved |
| Cache | unchanged input reuses the verified result with zero calls; a changed source misses |
| CLI | success names its own build; a failure reports `published: false` and the preserved build; no entry points exits 1; facts need no `speed.toml`; an unknown setting is `INVALID_CONFIG` |
| Rendering | failure output names outcome and preserved build; success names its own build |

PetClinic facts are unchanged by these rules: 54 anchors, 2,895 resolved edges, 270 rule observations and 931 warnings before and after.

## Validation on the fixture

Two full runs from separate fresh clones (Opus, `examples/petclinic/speed.toml` settings) both published `partial` builds with 12 of 12 anchors processed, 0 invalid evidence and every claim verified:

| | Run 1 | Run 2 |
| --- | --- | --- |
| Duration | 21 min | 24 min |
| Domains | Double-entry ledger; Card payment lifecycle; Card authorisation risk screening | Payment double-entry ledger; Card payment lifecycle; Card risk screening |
| Activities | 12 | 12 |
| Rules | 18 | 21 (all 18 of run 1, plus GBP default currency, BIN and last-four masking, positive-leg ledger totals) |

`partial` is correct: 11 traces stop at calls on built-in values such as `Map.get` and `Array.push`, which the TypeScript adapter cannot type. `src/domain/invariants.ts` has no activity because no payment operation calls it; only the verification harness and tests do.
