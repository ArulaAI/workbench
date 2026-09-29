# Defect: Parallel extraction normalization drops structural relationships

Severity: P0
Related Feature: speed-business-domain-discovery
Finding: F-01
Status: Resolved
Related Findings: F-02, F-04
Tags: extraction, normalization, adapters, relationships, dry, language-agnostic

## Summary

Business-domain discovery independently decodes raw extraction-rule matches instead of consuming the normalized output already produced by the existing extraction system. The two decoding paths recognize different output vocabularies.

The existing decoder understands rules with `produces: edge`, including Java `implements` relationships. The business-domain rules adapter does not consume that output type. It recognizes nodes, calls and semantic relations, so `implements` and `inherits` relationships can disappear without an error or capability diagnostic.

PetClinic exposes the failure through Java, but the defect is not Java-specific. Any registered rules-based language can lose a relationship whenever the two raw-match decoders drift.

## Evidence from the PetClinic trial

The trial repository is `/private/tmp/speed-domain-petclinic`.

Seven committed Spring controller classes explicitly implement generated API interfaces. For example, `OwnerRestController.java` contains:

```java
public class OwnerRestController implements OwnersApi {
```

The Java extraction rule in `lib/context/rules/java/definitions.yml` recognizes that syntax and emits:

```yaml
produces: edge
edge_type: implements
```

The persisted `.speed/context/business-domain-facts.json` contains:

- 2,748 `calls` edges;
- 18 `selects_implementation` edges;
- zero `implements` edges; and
- zero `inherits` edges.

The facts artifact inventories controller types and OpenAPI operations, but it contains no structural relationship connecting their owning contract and implementation types.

### What this evidence proves

- PetClinic source declares controller-to-interface relationships.
- The existing Java rule catalog recognizes the `implements` syntax.
- The normalized business-domain facts contain none of those relationships.
- The business-domain rules adapter has no handler for the rule output type that carries them.
- A relationship already supported by the extraction system is lost on the parallel business-domain path.

### What this evidence does not prove

- It does not prove that a same-named OpenAPI operation and controller method are the same operation.
- It does not establish how many endpoint anchors should be deduplicated.
- It does not prove that restoring the structural edges alone provides exact type, overload or framework resolution.
- It does not prove that every registered language currently emits `produces: edge`; it proves that the architecture can silently lose any output type not duplicated in both decoders.

## Grocery trial applicability

The Grocery trial at `/private/tmp/speed-domain-grocery` was checked against this finding.

Grocery does **not** directly reproduce F-01's observed `produces: edge` loss. Its `.sql` files are routed through the specialized `business_domain_adapters/sql.py` override rather than the generic rules adapter that independently re-decodes `match_source()` output. It therefore does not pass through the exact divergent decoder path demonstrated by PetClinic.

This is a verified non-reproduction, not evidence that SQL extraction is correct. Grocery instead exposes separate SQL parsing and resolution failures in F-02 and F-05. A specialized parser is allowed behind the common extraction contract, but it must emit the same canonical records and must not create another owner for the shared normalized vocabulary.

F-01 remains language-agnostic because its correction removes competing normalization ownership for every rules-based language. Its cross-language acceptance test must include a non-Java rules adapter. SQL-specific conformance belongs to the common adapter contract and the SQL findings rather than being presented as proof of this exact raw-rule decoding failure.

## Exact execution path

### Existing path

`lib/context/treesitter_extract.py` consumes the rule match and understands `produces: edge`. It stores the structural relationship information in its normalized extraction result.

```text
language rule
    |
    v
match_source()
    |
    v
treesitter_extract decoder
    |
    +--> produces: node
    +--> produces: edge
    +--> other supported outputs
    |
    v
normalized extraction records
```

### Business-domain path

`lib/context/business_domain_adapters/rules.py` does not consume the existing normalized result. It calls `match_source()` directly and decodes the raw matches again:

- `extract()` consumes `produces: node`;
- `calls()` consumes call references;
- `relations()` consumes `produces: semantic_relation` and `also_relation`;
- nothing consumes `produces: edge`.

```text
same language rule
    |
    v
match_source()
    |
    v
business_domain_adapters/rules.py
    |
    +--> node                 retained
    +--> call reference       retained
    +--> semantic_relation    retained
    +--> edge                 dropped
    |
    v
business-domain facts without implements/inherits
```

The failure happens before traversal and synthesis. Those later stages cannot follow, diagnose or recover a relationship that was never normalized into the fact graph.

## Root cause

There are two owners for the same responsibility: converting extraction-rule matches into normalized source, symbol and relationship records.

This violates the project's DRY requirement at an architectural boundary, not merely at the level of duplicated lines. Each decoder defines its own vocabulary and must be updated whenever a rule output type is added or changed. Drift is inevitable and, in this case, silent.

Adding `if produces == "edge"` only to the business-domain adapter would repair the observed symptom while preserving the competing decoder and the possibility of the next output type being lost.

## Expected behavior

1. Every extraction-rule match is decoded through one canonical normalization path.
2. Both CSG and business-domain consumers project from the same normalized records.
3. Every registered `produces` type becomes a normalized record or an explicit unsupported diagnostic.
4. Source-specific relationships retain their kind, source and target evidence, candidate state and resolution state.
5. A consumer cannot silently ignore a normalized relationship kind required by its contract.
6. The common records remain language-independent; a Java relationship and an equivalent relationship from another language use the same normalized shape.

## Violated requirements

- **Reuse and language-independent core:** The domain pipeline must reuse the existing extraction infrastructure and must not create a competing normalization path.
- **Extraction contract:** Supported structural relationships must reach normalized facts with evidence and resolution state.
- **Language-independent service tracing contract:** Source adapters supply source-specific facts without forcing core tracing to understand language-specific syntax.
- **BD-01:** Java inheritance and interface implementation must resolve as an initial conformance case.
- **No invented or omitted implementation evidence:** Unsupported output must remain explicit rather than disappearing.

## User and system impact

- Controller-to-interface relationships disappear before tracing.
- OpenAPI contracts and controller implementations remain disconnected.
- Missing extractor output creates no diagnostic and can falsely improve reported coverage.
- Downstream synthesis receives incomplete evidence packets.
- Fixes made to the established decoder do not automatically protect business-domain discovery.
- Every new rule output type can introduce another silent incompatibility.

## Reproduction

1. Run repository-digest refresh against `/private/tmp/speed-domain-petclinic`.
2. Confirm the committed relationships with:

   ```shell
   rg -n 'class .*RestController implements .*Api' src/main/java
   ```

3. Inspect `lib/context/rules/java/definitions.yml` and confirm that the Java declaration rule emits `produces: edge` and `edge_type: implements`.
4. Inspect `lib/context/treesitter_extract.py` and confirm that the existing decoder handles that output.
5. Inspect `lib/context/business_domain_adapters/rules.py` and confirm that its independently implemented decoding paths do not handle `produces: edge`.
6. Group edges in `.speed/context/business-domain-facts.json` by `kind` and observe zero `implements` and zero `inherits` edges.

## Required correction

1. Establish one canonical decoder for extraction-rule output.
2. Project its normalized source, symbol and relationship records into CSG and business-domain facts as required.
3. Remove the business-domain path's independent reinterpretation of raw extraction metadata.
4. Define one versioned normalized relationship vocabulary with explicit evidence and resolution.
5. Require every registered `produces` type to map to that vocabulary or emit a stable unsupported-output diagnostic.
6. Make unconsumed normalized records a validation failure when the consumer contract declares them relevant.
7. Preserve resolved, ambiguous and unresolved structural relationships rather than reducing them to names.
8. Apply this enforceable implementation rule:

   > Before creating an extractor, decoder, registry, schema vocabulary, or normalization path, locate the existing owner of that responsibility and extend or reuse it. Do not create a parallel implementation. If reuse is impossible, document the incompatibility and add a conformance test proving equivalent behavior before proceeding.

## Acceptance tests

The defect is fixed only when all of the following pass:

1. **Single decoder:** A call-site or architectural test prevents business-domain code from introducing another raw-match decoder.
2. **Output-contract completeness:** Every registered extraction `produces` type becomes a normalized record or an explicit unsupported diagnostic.
3. **Structural preservation:** The seven PetClinic controller-to-API-interface declarations are retained as resolved, ambiguous or unresolved relationships with source evidence.
4. **Cross-language preservation:** Equivalent structural fixtures from Java and at least one non-Java rules-based language produce the same normalized relationship shape.
5. **No silent consumption gap:** A fixture with a newly registered output type fails validation until the canonical decoder maps or explicitly rejects it.
6. **Consumer parity:** CSG and business-domain projections agree on relationship identity and evidence for the same normalized match.
7. **Unresolved preservation:** A structural target that cannot be uniquely selected remains ambiguous or unresolved; normalization does not discard it or upgrade it by name.
8. **PetClinic regression:** The business-domain facts no longer report zero `implements` relationships while the seven declarations are present in source.
9. **Specialized-parser boundary:** A SQL or other specialized parser can supply canonical records through the shared contract without defining a second common record vocabulary.

Fixing F-01 restores relationships the existing extractor already understands. It does not, by itself, add the exact semantic-resolution capability required by F-02 or the semantic trace-completion rules required by F-04.

## Resolution

Status: completed

The business-domain rules adapter now consumes normalized `RuleOutput` records
from the established `normalize_rule_outputs()` owner plus its normalized
declarations and references. The canonical decoder rejects
unknown output and structural-edge kinds, and relationship projection preserves
source evidence plus an explicit unresolved state when semantic target selection
is unavailable. The specialized SQL adapter continues to emit the common
language-neutral `Unit` contract rather than defining another shared vocabulary.

Verification completed on 2026-09-08:

- the PetClinic trial retained all seven controller-to-API `implements`
  declarations (30 `implements` and 38 `inherits` relationships overall);
- Java, Python, and TypeScript structural fixtures produced equivalent canonical
  relationship records;
- the TypeScript interface-inheritance regression retained both relationships;
- 184 Discover tests and 95 shared tree-sitter tests passed;
- the contract specimen checker passed all 23 valid and 14 invalid variants.
