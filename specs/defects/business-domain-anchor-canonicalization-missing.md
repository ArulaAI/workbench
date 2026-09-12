# Defect: Contract and implementation anchors are not canonically reconciled

Severity: P0
Related Feature: speed-business-domain-discovery
Finding: F-06
Status: Resolved
Related Findings: F-01, F-02, F-03, F-04
Tags: anchors, identity, canonicalization, deduplication, aliases, openapi, controllers, ui, language-agnostic

## Summary

Business-domain discovery creates a separate anchor for every source-qualified declaration and sends each anchor through semantic interpretation independently. It has no stage that reconciles multiple source representations of one entry point into a canonical anchor, preserves the other representations as aliases, or records that a possible correspondence remains unresolved.

PetClinic exposes the gap through OpenAPI operations and Java controller methods. The facts contain 36 OpenAPI HTTP candidates and 35 controller-derived HTTP candidates. Thirty-four operation names occur once in each source family, producing 68 records that require relationship-based reconciliation.

Those matching names are correspondence candidates, not proof of 34 duplicates. The RFC explicitly forbids deduplication by similar wording alone. The defect is that the implementation has no mechanism capable of making the evidence-backed decision at all. It cannot produce a defensible canonical anchor count.

This failure occurs before provider reliability can be assessed fairly. The implementation may send separate semantic requests for a protocol contract and its implementation because deterministic extraction did not reconcile their identities first.

## Evidence from the PetClinic trial

The trial repository is `/private/tmp/speed-domain-petclinic`.

Its persisted `.speed/context/business-domain-facts.json` contains 95 candidate anchors:

- 36 OpenAPI HTTP candidates;
- 35 Java controller-method HTTP candidates; and
- 24 TSX UI candidates.

The 71 HTTP candidates contain 34 repeated operation names. Each of those names appears once in `src/main/resources/openapi.yml` and once in a Java controller. Examples include:

- `addOwner`;
- `addPet`;
- `addVisit`;
- `deleteOwner`;
- `getPet`;
- `listVets`; and
- `updateVisit`.

These 34 correspondence groups account for 68 HTTP records.

Three HTTP candidates have no same-named counterpart in the other source family:

| Candidate | Source | Extracted identity |
| --- | --- | --- |
| `failingRequest` | OpenAPI | `GET /oops` |
| `updateOwnersPet` | OpenAPI | `PUT /owners/{ownerId}/pets/{petId}` |
| `redirectToSwagger` | Java controller | HTTP method and route both null in persisted facts |

The repeated names are useful for locating cases to resolve, but names alone do not establish identity. Exact reconciliation must consider the protocol operation, owning contract, generated-interface configuration, implemented type, effective framework mapping, callable signature, service scope and source evidence.

### Concrete `addVisit` example

PetClinic supplies two records named `addVisit`:

```text
OpenAPI
  POST /visits
  operationId: addVisit

Java
  VisitRestController.addVisit
  controller implements VisitsApi
```

The OpenAPI record and controller record have different anchor IDs because their symbols are source-qualified differently. The facts contain no resolved relationship connecting the OpenAPI operation, generated interface declaration and controller implementation.

They consequently receive separate traces. As detailed in F-04, the OpenAPI trace is marked resolved after visiting only its contract symbol, while the controller body appears in a different unresolved trace.

The evidence strongly identifies `addVisit` as a case requiring reconciliation. It does not authorize merging solely because the method and operation ID have the same text. The missing contract-to-implementation resolution from F-01 and F-02 must supply the proof or leave the correspondence explicitly unresolved.

### What this evidence proves

- The persisted inventory contains 71 HTTP candidate records, not 71 established logical endpoints.
- Thirty-four HTTP names appear in both OpenAPI and controller source families.
- Every source-qualified declaration receives its own anchor identity.
- No canonical anchor or alias relationship connects the paired candidates.
- The stored schema and implementation contain no canonical-anchor alias field.
- Discovery dispatches activity interpretation once for each stored candidate anchor.
- Each dispatched activity packet contains only that one anchor.
- A later grouping step groups activities into domains; it does not reconcile duplicate activity or anchor identity.
- The implementation cannot currently calculate a defensible canonical anchor count.

### What this evidence does not prove

- It does not prove that all 34 same-named pairs are the same endpoint.
- It does not prove that 71 HTTP candidates should collapse to 37 canonical endpoints.
- It does not prove that every OpenAPI operation has a committed or deployable implementation.
- It does not prove that every controller method is reachable as an HTTP endpoint.
- It does not establish whether any of the 24 TSX candidates should be retained, linked, aliased or excluded.
- It does not establish that matching names are sufficient evidence for cross-language or cross-service identity.

## Evidence from the Grocery trial

Grocery exercises the same declaration-versus-implementation identity problem without producing the same double-counted shape.

`JTA_Packages.sql` contains:

- 24 public package-specification routine declarations: three in `jta_error` and 21 in `jta`;
- 25 package-body routines: the 24 public implementations plus the body-only private helper `jta.get_hours`; and
- four standalone triggers.

The SQL adapter explicitly skips declarations whose header ends at `;`:

```python
if not intro or intro.group() == ';':
    continue  # Package declarations are contracts, not executable bodies.
```

The persisted facts therefore contain:

- zero anchors or symbols for the 24 public package-specification declarations;
- 25 package-body routine anchors; and
- four trigger anchors.

Grocery does not show package specifications and bodies being double-counted. It shows the opposite shortcut: the contract representation is discarded instead of preserved and reconciled with its implementation.

That loses public API evidence, declared callable signatures and the distinction between exported package operations and private body helpers. It also prevents canonical identity from retaining both the public declaration and executable implementation as evidenced representations.

The body-only `jta.get_hours` anchor raises a separate anchor-eligibility question because it is private to the package body. F-06 records the missing canonicalization/alias mechanism; a later extraction finding must decide which SQL routines qualify as activity anchors rather than assuming all executable bodies are public entry points.

## RFC requirements

The RFC distinguishes candidate extraction from canonical identity:

- Activity IDs initially derive from resolved anchor identity.
- Deduplicated anchors have one canonical ID and an alias list.
- Frontend/API anchors may be deduplicated only through a resolved implementation link or a validated evidence-backed synthesis decision.
- Similar words alone are insufficient.
- A UI/API deduplication proposal requires the same resolved interaction path; otherwise it remains an inferred alias requiring review.
- A single activity can contain multiple anchor IDs.

The implementation provides candidate extraction but not the required reconciliation and alias contract.

## Exact execution path

### 1. Every extracted unit receives a source-qualified anchor ID

`lib/context/business_domain_extract.py::Extractor.add_unit()` creates the symbol and anchor directly from the extracted unit:

```python
unit.symbol_id = identifier('symbol', unit.qualified)

if unit.anchor_kind:
    unit.anchor_id = identifier('anchor', unit.qualified, unit.anchor_kind)
```

`unit.qualified` contains the source-specific symbol identity. An OpenAPI operation and a controller implementation therefore receive different anchor IDs even when later evidence could establish that they represent the same entry point.

The anchor record is inserted immediately:

```python
self.facts['anchors'][unit.anchor_id] = record(
    'Anchor',
    id=unit.anchor_id,
    kind=unit.anchor_kind,
    source_id=unit.source.resource_id,
    symbol_id=unit.symbol_id,
    operation=operation,
    status='candidate',
    evidence_ids=[unit.evidence_id],
)
```

There is no canonical identity, alias list, correspondence state or replaced-by reference on that record.

### 2. No reconciliation pass runs after relationships are extracted

The extractor builds anchors, edges and traces, but it does not run a pass that:

- groups possible representations of the same entry point;
- tests resolved implementation relationships;
- chooses a canonical anchor;
- preserves aliases and their individual evidence; or
- records an ambiguous or unresolved correspondence.

F-01 drops structural relationships already present in the extraction system. F-02 establishes that no discoverable semantic resolver can supply exact contract-to-implementation relationships. F-03 additionally leaves controller method and route identity incomplete. Even if those defects are corrected, F-06 remains: there is no consumer that turns an established relationship into canonical anchor identity.

### 3. Discovery schedules every candidate independently

`lib/context/business_domains.py::discover()` loops over all stored anchors:

```python
with ordered_work(
    sorted(facts['anchors']),
    interpret,
    config['provider_concurrency'],
    synthesis.stopping,
) as results:
```

For each anchor, `interpret()` creates a packet containing only that anchor:

```python
packet = packet_for(baseline, 'activity', [anchor])
```

The OpenAPI representation and controller representation are therefore interpreted as independent work items.

### 4. Activity validation prevents cross-packet merging

`accept_activity()` calculates the expected anchor set from the current packet:

```python
expected = set(packet['anchor_ids'])
represented = {
    anchor
    for activity in payload['activities'].values()
    for anchor in activity['anchor_ids']
}
```

It requires every represented, excluded or pending anchor to equal the packet's expected set. Because the packet contains one anchor, an activity response cannot legitimately include the corresponding anchor from another packet.

Although the activity schema supports multiple `anchor_ids`, the execution path never supplies a reconciled multi-anchor packet.

### 5. Grouping does not repair activity identity

The later grouping stage receives already interpreted activity summaries and assigns them to proposed domains. `accept_grouping()` validates domain memberships and exclusions. It does not merge two activities, select a canonical anchor, or create anchor aliases.

```text
OpenAPI operation ----------------> source-qualified anchor A
                                           |
                                           v
                                  activity packet A

Generated interface relationship -------- missing/unresolved

Controller method ---------------> source-qualified anchor B
                                           |
                                           v
                                  activity packet B

                                           |
                                           v
                                domain grouping only
                         no anchor/activity reconciliation
```

## Root cause

The implementation treats source declaration identity as canonical activity-entry identity.

Those are different concepts:

- A source declaration identifies one observed representation and its evidence.
- A canonical anchor identifies one resolved entry point while retaining all evidenced representations and aliases.
- An activity may be reachable through multiple distinct entry points, so canonicalizing anchors is also different from grouping anchors into an activity.

The missing layer must preserve all three distinctions. It cannot solve them through a name-based set operation, and the semantic provider cannot safely repair them after receiving isolated single-anchor packets.

## Expected behavior

1. Preserve every extracted source representation and its evidence.
2. Build evidence-backed correspondence candidates without merging them by name.
3. Resolve contract-to-implementation identity through adapter-provided semantic relationships.
4. Assign one canonical anchor identity when the relationship is resolved.
5. Retain other source representations as aliases with their original source, symbol, operation and evidence.
6. Preserve ambiguous candidates and missing implementations explicitly.
7. Distinguish two representations of one endpoint from two genuinely different entry points that participate in one activity.
8. Construct model-ready graph input from canonical anchors and all required alias/trace evidence; the RFC's size gate decides whole-graph versus hierarchical execution.
9. Permit validated evidence-backed synthesis to propose an alias only when deterministic resolution is unavailable, and retain that proposal as reviewable rather than silently canonical.
10. Apply the same normalized reconciliation contract across languages, frameworks and protocols.

## User and system impact

- The displayed candidate count can be mistaken for a logical entry-point count.
- Protocol contracts and their implementations may be interpreted as separate activities.
- Provider calls, token reservations and failure exposure may be multiplied by duplicated representations.
- One representation may be marked resolved while its actual implementation is unresolved elsewhere.
- Domain grouping can receive duplicate or contradictory summaries for the same behavior.
- Evidence is fragmented between separate traces and activity packets.
- Coverage metrics measure dispositions of raw candidates without disclosing the unresolved canonical count.
- UI-to-API and cross-service representations have no general alias mechanism.
- Deleted or changed representations cannot be reconciled reliably against a stable canonical anchor.

## Reproduction

1. Run repository-digest refresh against `/private/tmp/speed-domain-petclinic`.
2. Count anchors in `.speed/context/business-domain-facts.json` by source family and observe 36 OpenAPI, 35 Java controller and 24 TSX candidates.
3. Group the 71 HTTP candidates by `operation.name`.
4. Observe 34 groups containing one OpenAPI record and one Java controller record.
5. Observe the three unmatched HTTP candidates: `failingRequest`, `updateOwnersPet` and `redirectToSwagger`.
6. Inspect `Extractor.add_unit()` and confirm that anchor identity derives from `unit.qualified` and `anchor_kind`.
7. Search the normalized artifact schema and implementation for a canonical-anchor alias field and confirm that none exists.
8. Search the extraction and discovery paths for an anchor reconciliation or deduplication pass and confirm that none exists.
9. Inspect `discover()` and confirm that it calls `packet_for(..., 'activity', [anchor])` separately for every stored candidate.
10. Inspect `accept_activity()` and confirm that represented anchors must come from that single-anchor packet.
11. Inspect grouping and confirm that it assigns existing activities to domains without merging activities or canonicalizing their anchors.
12. Inspect the `addVisit` OpenAPI and controller traces and confirm that they remain disconnected.

## Required correction

Do not fix this by merging equal operation names, routes, component names or short symbols. Do not discard source representations after selecting a canonical record.

The correction must:

1. Add a normalized anchor-correspondence contract with states such as resolved, ambiguous, unresolved and inferred/review-required.
2. Add a canonical anchor identity and evidence-preserving alias representation to the versioned artifact schema.
3. Run deterministic reconciliation after normalized relationship extraction and before model-ready graph serialization or semantic-unit scheduling.
4. Consume the exact callable, type, interface, route and framework relationships supplied through F-02's discoverable adapter capabilities.
5. Treat missing relationship capability as an explicit unresolved correspondence, not as proof that records are distinct.
6. Select canonical identity from resolved protocol and implementation evidence rather than source ordering or display names.
7. Preserve each alias's original source identity, symbol, operation details, evidence and resolution reason.
8. Include each canonicalized entry point exactly once in the complete model-ready graph scope, with all relevant contract, alias and implementation traces. Request packaging follows the RFC's whole-graph or hierarchical size path; it must not return to isolated raw-candidate interpretation.
9. Keep multiple genuinely distinct entry points available to one activity without incorrectly collapsing them into one anchor.
10. Keep ambiguous/unresolved correspondence as a graph-level disposition that synthesis must explain but cannot convert into a resolved canonical identity; only new deterministic relationship evidence may resolve it in a later build. Human review may flag the gap or guide adapter work but cannot manufacture a source relationship.
11. Recalculate coverage over both source representations and canonical anchors so neither evidence nor workload is silently hidden.
12. Make canonicalization language- and framework-independent; core code evaluates normalized relationships rather than Java, Spring, OpenAPI or React names.

## Acceptance tests

The defect is fixed only when all of the following pass:

1. **No name-only merge:** Same-named operations with different routes, services or callable targets remain distinct.
2. **Resolved contract implementation:** An OpenAPI operation linked through an exact generated interface to a controller produces one canonical anchor with evidence-preserving aliases.
3. **Missing generated source:** When the implementation relationship cannot be established, the records remain separate or unresolved correspondence candidates; they are not silently merged or declared unrelated.
4. **Ambiguous implementations:** One contract with two viable implementations retains an ambiguous correspondence and bounded candidates.
5. **Unmatched contract:** A contract operation with no evidenced implementation remains an unresolved contract anchor.
6. **Unmatched implementation:** A directly registered implementation with no contract remains its own canonical anchor when its protocol identity is resolved.
7. **Multiple representations:** Contract, interface, framework registration and concrete method evidence survive canonicalization as aliases or related representations.
8. **Single interpretation occurrence:** A resolved contract/implementation pair appears once as one canonical entry point in the selected whole-graph or hierarchical semantic scope, with all required alias, trace and evidence records.
9. **Multi-entry activity:** Two genuinely distinct canonical entry points may be assigned to one activity without being collapsed into one anchor.
10. **Frontend/API path:** A UI/API alias proposal requires the same resolved interaction path or remains inferred and review-required.
11. **Schema support:** Canonical and alias references validate, survive serialization and resolve within the same build closure.
12. **Stable identity:** Reordering source files or aliases cannot change the canonical ID.
13. **Source change:** Removing one alias retires only that representation unless the canonical identity loses all supporting evidence.
14. **Coverage accounting:** Status separately reports extracted representations, canonical anchors, unresolved correspondence candidates and pending interpretations.
15. **PetClinic regression:** The 34 same-named OpenAPI/controller groups are each resolved, ambiguous or explicitly unresolved from evidence; the artifact does not present 68 unexplained independent HTTP records.
16. **Cross-language conformance:** Equivalent protocol/implementation pairs across at least two implementation languages produce the same canonical and alias record shapes without core language branches.
17. **SQL specification/body identity:** A public package specification and its exact package-body implementation produce one canonical callable/anchor identity while retaining both source representations and evidence.
18. **SQL private helper:** A body-only private routine is not merged into a public contract and is not promoted to a public entry point merely because it has an executable body.

## Relationship to provider failure handling

F-06 must be resolved or explicitly measured before using candidate-anchor count to judge provider workload. Provider outage containment remains independently defective if retry state resets for every packet, but its impact must be reported against canonical interpretation work rather than assuming every extracted candidate is legitimate.

## Resolution

Status: completed

Adapters now emit language-neutral anchor representations, service-scoped exact
identities and bounded correspondence evidence. Reconciliation runs before trace
construction and semantic scheduling, uses only resolved relationships, assigns
stable canonical IDs, retains every alias/evidence record, preserves unresolved
and ambiguous candidates, and reports representation/correspondence coverage.
Whole-graph activity packets include canonical aliases and traces, with stable
batching only when the complete scope exceeds request limits.

Verification completed on 2026-09-08:

- all 18 F-06 acceptance cases and all 270 Discover tests passed;
- the contract checker passed 23 valid and 14 invalid specimens;
- PetClinic's 34 OpenAPI/controller groups are all explicitly explained;
- Grocery produced 28 canonical anchors from 52 representations, including 24
  public specification/body pairs, while private `jta.get_hours` produced no
  anchor or trace; and
- Python compilation and diff-integrity checks passed.
