# Defect: TypeScript discovery leaves known calls, tests, inputs and documentation unlinked

Severity: P2
Related Feature: speed-business-domain-discovery
Status: Resolved
Related Defects: business-domain-typescript-library-has-no-entry-points
Tags: typescript, receivers, platform-calls, tests, bindings, documentation, diagnostics

## Summary

After the library entry-point fix, discovery on the Payments Validation Fixtures repository published a correct model, but its evidence was thinner than the source supports:

| Gap | Measured on the fixture |
| --- | --- |
| Calls on values whose type the source declares stayed unresolved | 45 unresolved call sites on traces, most of them `Map` and array methods on typed members |
| Calls through an exported object never resolved | `log.info` and `log.error` from `src/obs` |
| Tests never linked to the behaviour they exercise | 0 `tests_behavior` edges from 30 test evidence records |
| The model never saw tests or documentation sections | the synthesis request held only trace-reachable records |
| TypeScript callables had no inputs | every activity had empty `input_binding_ids` |
| Documentation linked by substring and cited whole files | 24 of 96 operation links were false (`net` in "network"); every link cited the full file |
| Budget and deadline failures did not say what to change | `BUILD_BUDGET: Discovery token budget exhausted` |
| The run log hid why a candidate went back for repair | verify events carried counts only |

## Root causes and resolution

1. **Declared platform types.** `rules.resolve_call` classified a call as a platform boundary only when its root was an ambient global (`Date.now`). It now also does so when the receiver's declared type is one the language provides. That covers members typed `Map<…>` or `Entry[]`, members constructed with `new Map()`, and module constants such as `const store = new Map()`. An undeclared receiver still stays unresolved, and a parameter or local of the same name shadows a module constant (`ts-local-name-declaration`). Receivers of chains split across lines are compared without their line breaks.
2. **Exported objects.** `ts-exported-function-object` and `ts-exported-object-function` declare `export const log = { info: … }` and its members. `rules.prepare` resolves `log.info(...)` to the member the object owns. This uses a separate `resolved_member_targets` index, so a receiver call never takes a same-file name match.
3. **Tests.** `ts-test-case` makes `test('title', …)` and `it(…)` callbacks units named by their title (`name_from: literal` in `treesitter_extract`). Receiver bindings for locals (`new C()`), typed parameters (`(s: C)`) and same-file constructing factories (`const s = svc()`, `gw().run()`) let their calls resolve, so the existing `tests_behavior` edge is created. Test units never become anchors.
4. **Inputs.** `ts-input-binding` and `ts-untyped-input-binding` bind the parameters of methods, function declarations and named arrows, but not inline callbacks.
5. **Documentation.** `_documentation_edges` matches an operation's name or route as a whole word and cites each mentioning Markdown section, from its heading to the next, up to `MAX_DOCUMENT_SECTIONS` per link. Edge identifiers are unchanged.
6. **Model context and guidance.** `_model_ready_context` selected records reachable from traces only, so the synthesis request never contained a test or a documentation section (0 of 31 test cases in a published run's request). It now attaches `tests_behavior` edges into traced symbols, with the test's own span that holds its assertions, and `documents_behavior` edges to selected anchors. Neither edge is traversed. The synthesis and verification agent definitions, runtime and normative contract alike, now state when a rule's basis may include `test_expected` or `documented`: only when a cited test asserts, or a cited section states, the rule's condition or outcome. On the fixture the request grows from about 52,000 tokens; PetClinic's grows by about 15% from about 317,000, within the request input allowance.
7. **Diagnostics.** `BUILD_BUDGET` names the exhausted budget, the amounts and the `[business_domains]` setting to raise; `BUILD_TIMEOUT` names `deadline_seconds`. Verify progress events add each finding's category, severity and subject IDs, and the summary line lists blocking categories. A finding's free-text message is provider output and is still never logged.

Overload numbering was left keyed by name alone. Keying it by owner removes suffixes such as `log.info:0`, but it renames every Java class whose constructor shares its name, which changes symbol identities across PetClinic.

## Known limits

- Calls on locals and expressions whose type is declared away from the call (`payment.captures.reduce`, `digits.slice`, `(x ?? []).filter`) stayed unresolved here. [business-domain-typescript-declared-receiver-types](business-domain-typescript-declared-receiver-types.md) resolves them by reading those declarations.
- A route written inside a longer URL (`…/api/vets`) is not a documentation mention. Text cannot tell a URL segment from a file path such as `jsp/vets/vetList.jsp`, which the previous matcher linked falsely.
- The specified default build budget (512,000 output tokens) is smaller than one full repair chain at 128,000 tokens per request. This is unchanged because the technical specification fixes the value; the error now says how to raise it.

## Acceptance tests

`tests/test_business_domain_typescript_evidence.py` (19 tests). On `024c337`, 15 fail and the 4 guard tests pass; all 19 pass after the fix. The updated assertions in `test_semantic_outcome_summary_exposes_verdict_and_record_counts` and the provider progress test cover the verify log details and check that a finding's message is never logged.

| Area | Tests |
| --- | --- |
| Platform types | declared `Map` and array members; multi-line chain; module constant, and its shadowing by a parameter; an undeclared local stays unresolved |
| Exported objects | members owned by the object; `log.info` resolves to the member, not a top-level `info`; a receiver call never takes a same-file name match |
| Tests | test cases named by title; links through a factory local, an inline factory call, a constructed local and a typed parameter; test cases are never anchors |
| Inputs | typed, optional and untyped parameters; inline callback parameters excluded |
| Documentation | whole-word mentions only; sections cited, not the file |
| Model context | the synthesis context carries test cases with their assertions and documentation sections |
| Diagnostics | budget and deadline messages name their settings |

## Effect on the fixture (`--facts-only`)

| Measurement | Before | After |
| --- | --- | --- |
| Unresolved call sites on traces | 45 | 25 |
| Traces bounded or complete | 1 | 3 |
| `tests_behavior` edges | 0 | 43 |
| Operation documentation links | 96 (24 false) | 72 |
| Median cited documentation lines | 113 (whole file) | 12 |

PetClinic facts keep the same anchors, traces, resolved calls, test links, unsatisfied obligations and warnings. It gains two symbols (`Constraints.ts::NotEmpty` and its `validate` member) and 5 input bindings. Its documentation links fall from 10 to 3; all 7 removed links matched routes or names inside JSP file paths in `readme.md`.
