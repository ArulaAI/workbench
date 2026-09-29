# Defect: Incomplete framework endpoints silently default to resolved

Severity: P0
Related Feature: speed-business-domain-discovery
Finding: F-03
Status: Resolved
Related Findings: F-02, F-04
Tags: anchors, endpoints, spring, resolution, schema, validation, language-agnostic

## Summary

The Java controller rule identifies methods inside a Spring `@RestController`, but it does not extract their HTTP method or route. Anchor construction then omits both an explicit resolution decision and a diagnostic reason. The generic schema constructor supplies the first allowed enum value—`resolved`—for the missing resolution field.

The result is a fact that claims a successfully resolved HTTP boundary while lacking the information that identifies that boundary.

PetClinic demonstrates this through Spring, but the defect is producer-agnostic: any adapter or enricher that omits resolution can accidentally publish an incomplete record as successful.

## Evidence from the PetClinic trial

The persisted `.speed/context/business-domain-facts.json` contains 35 controller-derived HTTP anchors for which:

- HTTP method is null;
- route/path is null;
- resolution is `resolved`; and
- diagnostic reason is null.

This cannot be explained only by inherited API-interface mappings. `RootRestController.redirectToSwagger` declares `@RequestMapping("/")` directly in committed source, yet its persisted anchor still has a null route.

### What this evidence proves

- The Java controller-anchor rule does not supply the endpoint identity required by the normalized HTTP anchor.
- Direct mapping evidence present in committed source is missing from the anchor.
- Anchor construction omits an explicit resolution decision.
- Schema defaulting turns that omission into `resolved`.
- The persisted artifact cannot distinguish an actually resolved endpoint from an incomplete one.

### What this evidence does not prove

- It does not prove that all controller methods should be independent HTTP entry points; inherited contracts and framework configuration must be resolved.
- It does not prove that method-level annotations alone always determine the final route; class mappings, interfaces and configuration may contribute.
- It does not establish an exact number of duplicate OpenAPI/controller operations.
- It does not prove that every missing mapping can be recovered when generated source or dependencies are unavailable.

## Grocery trial applicability

Grocery confirms that the success-by-default mechanism is shared across languages.

`Extractor.add_unit()` creates every anchor without supplying `resolution` or `reason`; this is the same common path used by the Java, TSX and SQL adapters. All 29 Grocery SQL anchors consequently contain:

```text
resolution: resolved
reason: null
```

The SQL adapter never made or recorded that resolution decision. The generic schema constructor supplied it.

Grocery does not prove that all 29 routine declarations have invalid identities. A concrete package-body routine or trigger can be a correctly identified SQL callable. It proves that their successful state is not an explicit adapter conclusion and carries no dialect/capability rationale. This matters because the same trial shows unsupported parsing behavior and no dialect discovery under F-02/F-05.

The correction must therefore remain producer- and language-agnostic: every adapter explicitly states resolution, and the common validator rejects omission. It must not add special defaulting rules for Java, Spring, SQL or Oracle.

## Exact execution path

### 1. The rule detects a controller method without mapping identity

The Java business-anchor rule matches methods nested in a class containing `@RestController`. Its metadata sets `anchor_kind: http`, but it has no captures for:

- `@RequestMapping`;
- `@GetMapping`, `@PostMapping`, `@PutMapping`, `@DeleteMapping` or `@PatchMapping`;
- annotation `method` values;
- annotation route/path values; or
- class-plus-method route composition.

### 2. The rules adapter can populate only supplied captures

`lib/context/business_domain_adapters/rules.py` can populate `Unit.method` and `Unit.route` only when the rule supplies the corresponding metadata and captures. For these controller methods, both values remain null.

### 3. Anchor construction omits resolution

`Extractor.add_unit()` creates an `Anchor` without passing `resolution` or `reason`.

### 4. Generic schema defaulting turns omission into success

The schema-record constructor fills an omitted enum field with its first allowed value. For `resolution`, that value is `resolved`. The missing reason defaults to null.

```text
Spring controller method
          |
          v
rule labels it `anchor_kind: http`
          |
          v
no method or route capture
          |
          v
Unit(method=null, route=null)
          |
          v
Anchor created without resolution/reason
          |
          v
schema supplies first enum value
          |
          v
resolved HTTP anchor with no identity
```

The false state exists before graph traversal or semantic synthesis.

## Root cause

Two independent implementation choices combine:

1. the source producer emits a partial endpoint record without declaring the gap; and
2. the shared schema treats an omitted resolution decision as success.

Framework resolution belongs behind the discoverable capability contract described in F-02. However, even an unsupported framework must never produce a false resolved record. Explicit state is a requirement at the normalized fact boundary, regardless of which adapter produced the record.

## Expected behavior

1. Every anchor and relationship producer sets resolution deliberately.
2. Omitted resolution fails validation; it never defaults to success.
3. An HTTP anchor marked resolved has the endpoint identity required by the contract, including method and effective route when those fields define identity.
4. Direct, class-level, inherited-interface and configuration-derived mappings retain their individual evidence.
5. Missing generated source or unavailable framework capability produces an unresolved or partial anchor with a stable reason.
6. Ambiguous mappings remain ambiguous with candidates or equivalent bounded evidence.
7. The core validates the common anchor contract without checking for Java or Spring.

## Violated requirements

- **Extraction contract:** Unsupported or unresolved framework behavior must remain an explicit gap.
- **BD-02:** Spring mappings must connect to implementations when evidence permits.
- **Spring and frontend connections:** Inherited and direct mappings must be resolved from evidence; unavailable declarations remain unresolved.
- **No invented implementation:** Missing endpoint identity cannot be presented as a resolved HTTP boundary.
- **Language-independent core:** Common validation, not a Spring-specific core branch, must reject incomplete successful records.
- **Support decision table:** Supported status requires a resolved production path rather than a partial declaration mislabeled as complete.

## User and system impact

- Consumers cannot identify or compare controller endpoints reliably.
- Contract and implementation anchors can appear unrelated or be incorrectly treated as duplicates.
- Coverage appears healthier because incomplete records carry no diagnostic.
- Semantic synthesis receives an HTTP anchor without the method and route needed to interpret it.
- Later validation trusts a false success state inherited from schema defaulting.
- The same default can hide omissions from future language and framework adapters.

## Reproduction

1. Run repository-digest refresh against `/private/tmp/speed-domain-petclinic`.
2. Inspect the 35 controller-derived HTTP anchors in `.speed/context/business-domain-facts.json`.
3. Confirm that each has null method, null path, `resolution: resolved` and no reason.
4. Inspect the Java controller-anchor rule and confirm that it labels controller methods as HTTP anchors without capturing mapping method or route.
5. Inspect `lib/context/business_domain_adapters/rules.py` and confirm that method and route depend on captures the rule did not provide.
6. Inspect `Extractor.add_unit()` and confirm that anchor construction omits resolution and reason.
7. Inspect schema-record defaulting and confirm that the first allowed `resolution` enum value is `resolved`.
8. Inspect `RootRestController.redirectToSwagger` and confirm that committed `@RequestMapping("/")` evidence is absent from its persisted anchor.

## Required correction

1. Make `resolution` required for every normalized anchor and relationship producer.
2. Remove success-by-default behavior for semantic state fields.
3. Reject records whose producer omits a resolution decision.
4. Define identity-completeness validation by normalized anchor kind. A resolved HTTP anchor must satisfy the common HTTP identity contract.
5. Preserve separate evidence for direct, class-level, inherited and configuration-derived mapping components.
6. Use the discoverable framework capability contract from F-02 to resolve Spring mappings without Spring branches in core code.
7. When mapping evidence is unavailable, emit unresolved or ambiguous state with a stable reason and capability diagnostic.
8. Propagate incomplete anchor state into trace obligations so F-04 cannot treat the anchor as a completed production path.

## Acceptance tests

The defect is fixed only when all of the following pass:

1. **Required state:** A fixture producer that omits anchor resolution fails validation.
2. **No success default:** Constructing a semantic record without resolution cannot yield `resolved`.
3. **Identity validation:** A resolved HTTP anchor lacking required method or effective route fails validation.
4. **Direct Spring mapping:** A directly annotated controller method produces the correct HTTP method and class-plus-method route.
5. **Root controller regression:** `RootRestController.redirectToSwagger` retains its committed `/` route evidence.
6. **Inherited Spring mapping:** A controller implementing an annotated interface receives the correct mapping when the interface is exactly resolved.
7. **Missing interface:** When generated interface source is unavailable and no independent evidence resolves the mapping, the anchor remains unresolved with a reason.
8. **Ambiguous mapping:** Conflicting viable mappings remain ambiguous and retain their evidence.
9. **Cross-language validation:** An equivalent incomplete HTTP anchor from a non-Java adapter is rejected by the same common validation without core language checks.
10. **PetClinic regression:** None of the 35 controller-derived anchors can remain `resolved` with both method and route null and no reason.
11. **SQL producer state:** Every SQL routine/trigger anchor receives an explicit adapter decision; omitting resolution fails the same common validation used for HTTP anchors.

Correcting F-03 makes anchor state honest. It does not itself establish the exact semantic relationships in F-02 or prove trace completeness under F-04.

## Resolution

- Anchor and edge producers must provide an explicit resolution; omission cannot default to success.
- Both runtime and normative contracts reject resolved HTTP anchors without a method and effective path, unresolved/ambiguous anchors without a reason, and resolved anchors with a failure reason.
- The Spring enricher composes direct and inherited class/method mappings, retains each mapping span as evidence, and preserves missing or conflicting mappings as explicit unresolved/ambiguous states.
- SQL producers make an explicit dialect/visibility decision through the same language-neutral boundary.
- The complete Discover regression suite passes (305 tests), and the contract checker passes all 23 specimens plus 14 invalid variants.
- A clean PetClinic acceptance extraction produced 35 controller anchors, zero invalid resolved anchors, and retained `RootRestController.redirectToSwagger` as path `/`, unresolved because no single HTTP method is evidenced, with three evidence records.
