# Defect: The adapter architecture lacks discoverable semantic resolution

Severity: P0
Related Feature: speed-business-domain-discovery
Finding: F-02
Status: Resolved
Related Findings: F-01, F-03, F-04, F-05
Tags: adapters, discovery, capabilities, resolution, language-agnostic, frameworks, java, spring

## Summary

Business-domain discovery has no language-agnostic extension point through which a source adapter can provide exact callable, type, inheritance and framework resolution while returning the common fact contract.

Languages registered at the rules extraction level fall through to one generic rules adapter. That adapter can load language-specific syntax rules, but it resolves relationships through generic lexical candidate matching. It cannot reliably select exact declarations, overloads, implemented interfaces or inherited framework mappings.

The required correction is not an `if language == ... and framework == ...` branch for every stack. Trusted adapters and framework enrichers must be discoverable from descriptors, selected from source evidence, and invoked through common capability and normalized-record contracts. Java/Spring is the first required conformance implementation, not a special case embedded in the core.

## Evidence from the PetClinic trial

The trial repository is `/private/tmp/speed-domain-petclinic`.

PetClinic's Maven build generates Spring API interfaces from `src/main/resources/openapi.yml` with `interfaceOnly` enabled. Seven committed controller classes implement those generated API interfaces. The generated interface source is not committed in the trial checkout.

The business-domain adapter catalog contains no Java-specific semantic adapter. The business-domain path contains no JavaParser, JavaSymbolSolver or equivalent Java type resolver. The persisted facts contain zero `implements` and zero `inherits` edges connecting controller types to their contracts.

Of the persisted call-edge records:

- 345 are marked resolved;
- 19 are marked ambiguous; and
- 2,384 are marked unresolved.

Those records come from syntax-level method-call matching and limited lexical candidate selection. Their existence does not establish compiler-grade type resolution.

### What this evidence proves

- The active business-domain architecture has no registered Java-specific type-resolution capability.
- Generic lexical matching is being used where the RFC requires exact declarations and overload handling.
- The PetClinic graph lacks the controller-to-interface relationships needed to connect protocol contracts to implementation.
- Generated or unavailable declarations are not represented through a capability-aware unresolved relationship.
- The common adapter contract cannot currently express and dispatch the required semantic-resolution capability.

### What this evidence does not prove

- It does not prove that JavaParser or JavaSymbolSolver is the only acceptable Java implementation.
- It does not prove that every call edge currently marked unresolved can be resolved from available source.
- It does not prove that every language or framework needs a unique adapter; compatible stacks may share one capability provider.
- It does not justify loading executable adapter code from the repository being analyzed.
- It does not prove that name equality is sufficient to connect OpenAPI and controller operations.

## Evidence from the Grocery trial

The Grocery trial at `/private/tmp/speed-domain-grocery` directly reproduces the missing capability architecture from a different language family.

The existing language registry classifies `.sql` as the generic language `sql`. `lib/context/business_domain_adapters/catalog.json` then contains a business-domain-local hardcoded override:

```json
"adapter_overrides": {
  "sql": "sql"
}
```

That override loads `business_domain_adapters/sql.py`, whose own module description says it is an `Oracle-style SQL source adapter`. No descriptor declares a SQL dialect, parser version, callable-resolution capability, built-in namespace, package visibility behavior or tested syntax coverage. There is no evidence-based dialect selection before the module is loaded.

Grocery happens to contain Oracle PL/SQL, but the selection was made from the `.sql` classification—not from Oracle syntax, dependencies, configuration or a validated dialect declaration. Any `.sql` file, including PostgreSQL PL/pgSQL or another dialect, is sent to the same Oracle-style implementation.

The resulting facts show why capability discovery matters:

- all 29 SQL routine/trigger anchors are labeled only as protocol/language `sql`;
- all 29 anchor records are marked resolved without a dialect capability record explaining that decision;
- all 29 traces are unresolved; and
- F-05 records 139 unresolved edges, including syntax and built-ins misclassified as application calls.

This does not mean language-specific parsing code is forbidden. Oracle PL/SQL and PostgreSQL PL/pgSQL require dialect-aware code. The requirement is that such code lives behind a discoverable, common capability contract. Core orchestration must not contain `if language == ...` or `if framework == ...` branches, and a business-domain-local map from generic `sql` to one dialect implementation is not dialect discovery.

## Exact execution path

`lib/context/business_domain_adapters/__init__.py` first looks for an adapter override. A language registered at the `rules` extraction level without an override falls back to `lib/context/business_domain_adapters/rules.py`.

```text
detected source language
          |
          v
business-domain adapter lookup
          |
          +--> explicit override exists --> use override
          |
          +--> rules language, no override
                         |
                         v
                  generic rules adapter
                         |
                         v
                 lexical candidates only
```

The generic adapter uses the detected language to choose syntax rules, but its candidate resolution has no language-owned semantic model. For Java, local names and captured receiver declarations are insufficient to prove:

- which imported type a short name denotes;
- which overload a call selects;
- which generated or dependency declaration a type implements;
- which annotation or inherited interface supplies a Spring route;
- whether an apparent candidate is concrete, abstract, external or unavailable.

The existing CSG extraction also lacks universal semantic resolution; the RFC explicitly identifies that limitation. The new feature was required to reuse adequate existing extraction and allow source adapters to re-resolve affected edges. Instead, F-01 regressed existing relationship preservation and F-02 omitted the capability boundary needed to make resolution stronger.

## Root cause

The implementation equates a language-independent core with one generic resolution algorithm. These are not the same requirement.

A language-independent core owns orchestration, normalized records, validation and trace semantics. A language or dialect adapter owns parsing and semantic decisions that require knowledge of its type system, name lookup, runtime or syntax. Framework enrichers own framework conventions. All communicate through common contracts.

Without discoverable capability providers, the implementation has only two bad choices:

1. keep using lexical matching for semantics it cannot prove; or
2. add hardcoded language and framework branches to core code.

The architecture must supply a third choice: select trusted capabilities from evidence and invoke them uniformly.

## Expected behavior

1. Adapters declare supported source languages or dialects, detection evidence, capability levels and normalized output versions.
2. Framework enrichers declare the semantic capabilities they add and the source evidence required to activate them.
3. Core orchestration asks for capabilities such as callable, type, inheritance, endpoint or data-flow resolution; it does not check language or framework names.
4. Adapter selection uses evidenced language/dialect detection, imports, annotations, dependencies and configuration.
5. Only trusted installed adapters are executable. A descriptor found inside the target repository is data and cannot cause repository-supplied code to run.
6. Exact, ambiguous, unresolved, external and unsupported outcomes use one normalized contract.
7. Missing source, generated declarations, dependencies and configuration become explicit diagnostics.
8. Adding a supported language or framework requires an adapter/enricher, registration and conformance fixtures—not changes to tracing or domain grouping.

## Example architecture

```text
source inventory
      |
      v
evidence-based detection
      |
      v
trusted adapter registry
      |
      +--> parser capability
      +--> callable-resolution capability
      +--> type/inheritance capability
      +--> framework enricher capability
      |
      v
common normalized facts
      |
      v
language-independent tracing and validation
```

For PetClinic, Java source and build evidence select a Java semantic adapter. Resolved Spring imports, annotations, dependencies and configuration activate a Spring enricher. The core sees only capability requests and normalized results; it contains no Java or Spring conditional.

## Violated requirements

- **Language-independent service tracing contract:** Source adapters provide language-specific facts without language-specific branches in the common core.
- **BD-01:** Java inheritance, interface implementation and calls must resolve to exact declarations as an initial supported-stack conformance case.
- **BD-02:** Spring interface mappings must connect to implementations when evidence permits.
- **Initial supported stack:** Java must use a parser with type resolution.
- **Spring and frontend connections:** Implemented API interfaces and inherited declarations must resolve; missing generated source must remain explicit.
- **Extraction contract:** Ambiguous, unresolved and unsupported behavior must not be upgraded through name matching.
- **Extensibility:** Supporting another language or framework must not require rewriting tracing, synthesis or verification.

## User and system impact

- Protocol contracts cannot be reliably connected to source implementations.
- Overloads and duplicate short names can be selected incorrectly or left as noisy unresolved edges.
- Generated, dependency-owned and external declarations are not explained honestly.
- Framework mappings inherited through interfaces or base types are missed.
- Every additional stack pressures the core toward hardcoded conditionals.
- Trace quality depends on lexical coincidence rather than source-language semantics.
- Provider time is spent guessing relationships deterministic adapters should establish or diagnose.

## Reproduction

1. Run repository-digest refresh against `/private/tmp/speed-domain-petclinic`.
2. Inspect `lib/context/business_domain_adapters/catalog.json` and confirm that no Java semantic adapter is registered.
3. Inspect `lib/context/business_domain_adapters/__init__.py` and follow the fallback for a rules-based language without an override.
4. Inspect the generic candidate-resolution logic in `business_domain_adapters/rules.py`.
5. Search the business-domain path for JavaParser, JavaSymbolSolver or an equivalent type-resolution integration and confirm that none is present.
6. Inspect the facts and confirm that the controller and contract inventories exist but their owning types are not connected by `implements` or `inherits` relationships.
7. Inspect call-edge resolution and confirm that lexical candidates do not encode full callable identities or compiler-backed selection.

## Required correction

1. Define a versioned, language-agnostic adapter capability contract for parsing, callable resolution, type resolution, inheritance, entry-point detection and framework enrichment.
2. Discover trusted installed adapters and enrichers from validated descriptors declaring supported languages/dialects, detection evidence, capabilities and conformance level.
3. Never load executable adapter code from the repository being analyzed.
4. Activate adapters and framework enrichers using resolved source evidence such as file content, imports, annotations, dependencies, generated-source configuration and runtime configuration.
5. Keep language and framework names out of core inventory, tracing, synthesis and verification branches.
6. Return all results through one normalized fact contract with exact evidence and explicit resolved, ambiguous, unresolved, external or unsupported states.
7. Implement Java exact type/callable resolution behind the contract as the first required language conformance provider.
8. Implement Spring endpoint and inherited-interface resolution as an evidence-activated enricher behind the same capability boundary.
9. Retain missing generated source as an unresolved relationship unless independent evidence establishes the target.
10. Emit stable, capability-specific diagnostics whenever the selected adapter cannot perform a required operation.
11. Apply the same architecture to SQL dialect parsers and resolvers described in F-05 rather than treating `sql` as one regex-resolved language.

## Acceptance tests

The defect is fixed only when all of the following pass:

1. **Language-agnostic core:** Adding a fixture adapter for a new language requires no changes to inventory, tracing, synthesis or verification code.
2. **Discoverable adapter:** A trusted fixture adapter is selected from its descriptor and source evidence without a language conditional in core code.
3. **Discoverable framework enricher:** A fixture enricher activates from dependency/import/annotation evidence without a framework conditional in core code.
4. **Safe discovery:** An adapter descriptor in the target repository cannot cause repository-supplied executable code to load.
5. **Capability reporting:** Every adapter accurately reports supported, partial and unavailable entry-point, callable, type, relationship and framework capabilities.
6. **Java imports:** Duplicate short type names resolve to the imported declaration rather than the first lexical name match.
7. **Java overloads:** Overloaded methods resolve using complete callable identity rather than method name alone.
8. **Java inheritance:** Implemented interfaces and inherited declarations resolve to exact available declarations.
9. **Spring inheritance:** A controller implementing an annotated API interface receives the correct inherited endpoint mapping when evidence is available.
10. **Missing generated source:** An unavailable generated declaration produces an explicit unresolved relationship unless independent evidence establishes it.
11. **Ambiguity:** Two viable implementations remain ambiguous with bounded candidates; the resolver cannot select one by name order.
12. **External boundary:** Dependency-owned or runtime-owned behavior is recorded as external or unavailable rather than a missing local source routine.
13. **Cross-language conformance:** Equivalent exact, ambiguous, unresolved and external fixtures in Java and at least one non-Java adapter produce the same normalized result shapes.
14. **PetClinic regression:** All seven declared controller-to-interface relationships are resolved or explicitly diagnosed, and every OpenAPI-to-controller connection is evidence-backed rather than name-only.
15. **SQL dialect discovery:** Oracle PL/SQL and PostgreSQL PL/pgSQL fixtures select their trusted dialect adapters from evidence and descriptors without a language/dialect conditional in core code.
16. **Unknown SQL dialect:** A generic or unsupported `.sql` fixture reports explicit capability gaps instead of silently using the Oracle adapter and claiming complete parsing.

F-02 supplies the semantic facts that tracing needs. It does not replace F-01's single-decoder correction, F-03's explicit endpoint state, or F-04's independent trace-completion contract.

## Resolution

Status: completed

- Installed descriptors now declare a versioned 15-capability contract, normalized-output version, provider kind, conformance level, detection evidence and stable diagnostics.
- Core orchestration invokes generic adapter/enricher hooks and contains no Java, Spring or SQL-dialect branches. Only modules inside the installed adapter package can load.
- `SemanticResult` is the shared evidenced exact/ambiguous/unresolved/external/unsupported result contract; canonical edges retain at most eight candidate symbol IDs.
- The installed Java provider performs closed-world import, type, inheritance, receiver and argument-type overload resolution. Unsupported or unavailable declarations remain explicit because the provider reports partial capability.
- The Spring enricher activates from parsed import/annotation evidence and resolves exact inherited interface mappings.
- Oracle, PostgreSQL and unknown SQL are selected from installed evidence predicates. PostgreSQL and unknown dialects report unavailable capabilities rather than falling through to Oracle.
- A clean PetClinic extraction retained and explicitly diagnosed all seven unavailable generated API interfaces; none received a name-only target.
- Verification passed: 298 combined Discover/shared extraction tests and all 23 valid/14 invalid contract specimens.
