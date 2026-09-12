# Defect: Detected operations do not completely hydrate the canonical data model

Severity: P0
Related Feature: speed-business-domain-discovery
Finding: F-08
Status: Resolved
Related Findings: F-01, F-02, F-04, F-05, F-06, F-07
Tags: data-model, hydration, edges, resources, effects, bindings, traces, activities, information-use, ui, api, sql, language-agnostic

## Summary

Business-domain discovery detects database resources, database writes and frontend HTTP calls but does not completely hydrate the canonical records and references that describe those operations.

The canonical data model is already capable of representing the required structure. It defines:

- typed `Edge` records, including `reads_data`, `writes_data` and `invokes_endpoint`;
- canonical `Binding` records and edge binding references;
- `Effect` records with target, input/output bindings, condition, transaction scope, trace backlinks, resolution and evidence;
- `Trace.edge_ids`;
- `Activity` references to traces, bindings, effects and information uses; and
- `InformationUse` records that connect an activity and concept to resources, access type, bindings, effects and traces.

The implementation populates only isolated portions of that model. A detected table reference may become a `Resource`; a detected SQL mutation or `fetch` call may become an `Effect`; parameters may independently become `Binding` records. The implementation does not atomically connect those facts into the canonical operation structure.

As a result, the persisted artifact can pass JSON shape validation while failing to answer basic structural questions:

- Which callable read or wrote this table?
- Which frontend handler invoked this service operation?
- Which values were sent, returned or changed?
- Which trace contains the operation?
- Which activity owns the effect or information use?
- Was an empty reference list proven empty, left unimplemented or lost during extraction?

Complete data-model hydration is mandatory. Detecting an operation and storing only a resource name or effect label does not satisfy the RFC.

## User-visible impact

The semantic provider receives incomplete evidence packets and is forced either to:

- reconstruct call and data flow from source excerpts;
- infer relationships that deterministic extraction should have supplied;
- omit reads, writes and outbound calls from the activity; or
- produce internally inconsistent activities whose prose mentions behavior that their canonical references do not support.

This directly undermines domain discovery. Data responsibility and business effects are primary evidence for grouping business activities. A table inventory without access direction and an effect without a trace do not establish responsibility.

The failure occurs before provider availability is relevant. A perfect provider cannot restore canonical graph facts that were excluded from its bounded packet or cannot safely invent references absent from the fact model.

## Existing canonical model and required hydration

The fix must use the existing canonical model rather than introducing a second data-flow or effect model.

### Data read

A supported, detected read must hydrate the applicable records as one operation:

```text
origin Symbol
    |
    | Edge(kind = reads_data, binding_ids, exact evidence)
    v
target Resource
    |
    +--> included in Trace.edge_ids when reachable
    |
    +--> represented by InformationUse(access = reads/references)
         after the containing Activity and Concept exist
```

A read is not automatically an `Effect`. Its observable business use belongs in `InformationUse`; its structural source-to-resource connection belongs in `Edge`.

### Data write

A supported, detected write must hydrate:

```text
origin Symbol
    |
    | Edge(kind = writes_data, binding_ids, exact evidence)
    v
target Resource
    |
    +--> Effect(kind = data_write)
    |      - changed-value/input bindings
    |      - result/output bindings when evidenced
    |      - condition
    |      - transaction scope and completion
    |      - exact evidence
    |      - trace backlinks
    |
    +--> InformationUse(access = creates/updates/deletes)
           tied to the resource, effect, bindings and traces
```

### External invocation

A supported, detected outbound operation must hydrate:

```text
origin Symbol or registered UI handler
    |
    | Edge(kind = invokes_endpoint, bindings, exact evidence)
    v
service/operation Resource
    |
    +--> Effect(kind = external_action)
    |      - request bindings
    |      - response bindings
    |      - condition and completion
    |      - trace backlinks
    |
    +--> UIInteraction.calls when initiated by a UI event
```

An unresolved destination remains an unresolved resource/edge/effect with a reason. It must not disappear merely because the URL, target implementation, transaction result or returned value is not fully resolvable.

### Activity materialization

After semantic interpretation creates an `Activity`, the canonical materializer must hydrate and validate the activity's closure:

- `trace_ids` identify its accepted execution paths;
- `input_binding_ids` and `output_binding_ids` refer to bindings applicable to those paths;
- `effect_ids` identify applicable responses, writes and external actions;
- `information_use_ids` identify its reads, creates, updates, deletes and references; and
- every referenced record remains connected to evidence and the corresponding trace.

The provider may interpret business meaning and choose among evidenced alternatives. It must not be the component responsible for repairing missing deterministic references or copying already-known graph membership into the canonical activity.

Complete hydration does **not** mean fabricating values for every nullable field or attaching every repository resource to an activity. It means every supported observation produces all structurally required records and references for the facts actually established. Unknown facts remain null or unresolved with a specific diagnostic; they are not silently represented by unexplained empty arrays.

## Evidence from the PetClinic trial

The trial repository is `/private/tmp/speed-domain-petclinic`.

### Persisted fact counts

The current `.speed/context/business-domain-facts.json` contains:

- 95 candidate anchors;
- 2,766 edges: 2,748 `calls` and 18 `selects_implementation`;
- zero `invokes_endpoint` edges;
- zero `reads_data` edges;
- zero `writes_data` edges;
- seven `external_action` effects;
- seven effects with no trace IDs;
- seven effects with no input bindings; and
- seven effects with no output bindings.

PetClinic source contains ten direct `fetch(...)` call sites under `client/src`, in addition to calls through the shared `submitForm` wrapper. The persisted model contains only seven external-action effects. This measured difference demonstrates an extraction-coverage gap, but it does not by itself establish the final number of distinct business operations: direct calls, wrapper implementation calls and caller operations must be resolved and canonically related rather than blindly counted.

### The detected HTTP effects are orphaned

The seven persisted effects include calls such as:

```text
fetch(fetchUrl)
fetch(requestUrl)
fetch(url(`/api/owner/${params.ownerId}`))
fetch('http://localhost:8080/api/oups')
```

All seven have:

```text
trace_ids = []
input_binding_ids = []
output_binding_ids = []
```

Six have a null target. Only the literal `http://localhost:8080/api/oups` call has a target resource. A dynamic or composed target can legitimately remain unresolved, but its invocation relationship, originating symbol, request bindings and trace membership must still be preserved.

### The final activities lose every HTTP effect

The resulting `.speed/context/business-domains.json` contains 27 activities and the same seven top-level effects. Across all 27 activities:

```text
total Activity.effect_ids references = 0
```

The effects therefore exist in the artifact but are not part of any interpreted activity.

This is not merely a presentation omission. Activity packet assembly selects effects only when `Effect.trace_ids` intersects the packet's traces. Because every PetClinic HTTP effect has an empty `trace_ids` array, none of the seven effects is supplied to activity interpretation.

### Wrapper and event flow is not hydrated

PetClinic has source flows such as:

```text
registered UI event
       |
       v
component handler
       |
       v
submitForm(...) or fetch(...)
       |
       v
HTTP operation/resource
```

The source contains concrete examples in `OwnerEditor`, `PetEditor`, `VisitsPage`, `FindOwnersPage`, `EditOwnerPage`, `OwnersPage`, `VetsPage` and the shared `util/index.tsx` wrapper.

The canonical model does not preserve the complete flow. In particular:

- the graph has no `invokes_endpoint` relationship;
- effects are not connected to traces;
- request/response bindings are empty;
- UI call records cannot be produced when the event handler cannot reach the effect-owning symbol through resolved graph edges; and
- activity packets omit the orphaned effects.

F-02 covers the missing discoverable resolution capability, and F-07 covers invalid UI anchor selection. F-08 remains independently reproducible because even a detected `fetch` effect is not hydrated into the existing edge, binding, trace and activity model.

### What the PetClinic evidence proves

- The implementation can detect some outbound HTTP call expressions.
- It stores those detections as isolated `Effect` records.
- It emits no `invokes_endpoint` edges.
- All detected HTTP effects lack trace and binding references.
- Packet assembly excludes all seven effects.
- The final activities reference none of them.
- Shape validation allows the incomplete artifact to pass.

### What the PetClinic evidence does not prove

- It does not prove that every direct `fetch` call is a separate activity.
- It does not prove that wrapper implementation and caller invocation should be deduplicated without a resolved call path.
- It does not prove the backend implementation for every URL.
- It does not authorize guessing a destination for a dynamic URL.
- It does not prove that all 27 generated activities are otherwise valid.

## Evidence from the Grocery trial

The trial repository is `/private/tmp/speed-domain-grocery`.

### Persisted fact counts

The current `.speed/context/business-domain-facts.json` contains:

- 29 candidate anchors;
- 192 edges, all of kind `calls`;
- zero `reads_data` edges;
- zero `writes_data` edges;
- 38 table resources;
- 28 `data_write` effects;
- 28 write effects with no input bindings; and
- 28 write effects with no output bindings.

Unlike PetClinic, every Grocery write effect has at least one trace ID. That does not demonstrate correct hydration. The association is produced by whole-symbol evidence overlap rather than an explicit write edge.

### Reads become an undirected table inventory

The SQL adapter's `resources(unit)` function recognizes table names following tokens such as `FROM`, `JOIN`, `INSERT INTO`, `UPDATE` and `REFERENCES`. It returns table resources but does not return an access kind, exact operation, originating symbol relationship or bindings.

Consequently, Grocery's SQL reads are represented as table resources with enclosing-unit evidence. There is no canonical fact stating which routine reads which table, which columns or values are returned, or which bindings carry those values into a decision.

For example, `JTA_Packages.sql` contains reads from tables including `work_hours`, `staff`, `inventory_by_location`, `products`, `customer_bills` and `billed_items`. The artifact inventories those resources but supplies no `reads_data` edges.

### Writes become partial effects without graph relationships

The SQL adapter's `effects(unit)` function recognizes `INSERT INTO`, `UPDATE` and `DELETE FROM`. Each match produces a partial effect containing:

- a target table resource;
- generic protocol `sql`;
- an outcome containing only the operation keyword;
- `completion = declared`; and
- an unresolved reason.

It does not create:

- a `writes_data` edge from the routine to the table;
- bindings for inserted, updated, filtered or returned values;
- exact statement evidence;
- control-flow condition;
- changed fields;
- transaction scope; or
- a direct operation-to-trace identity.

The common observation builder assigns the enclosing routine's evidence ID to the effect, not an evidence span for the individual SQL statement.

### Evidence overlap is being used as the relationship

After graph traversal finishes, `_traces()` associates an effect with a trace when the effect's evidence ID overlaps the evidence IDs of any symbol visited by the trace:

```text
if effect.evidence_ids intersects trace evidence:
    append trace ID to effect.trace_ids
```

This is not a data-flow relationship. It means “the write occurs somewhere in a source span included by this trace,” not “this reachable operation performs this write under these conditions using these bindings.”

The `jta_error.log_error` routine demonstrates the limitation. Its write to `jta_errors` is attached to 24 traces because those traces reach the enclosing routine. The effect still contains:

```text
outcome = "INSERT INTO"
condition = null
input_binding_ids = []
output_binding_ids = []
transaction_scope = null
```

The cited source explicitly contains `PRAGMA autonomous_transaction` and `COMMIT`, but that transaction evidence is not hydrated into the effect. The effect cites the complete routine span rather than the exact `INSERT` statement.

The 24 trace backlinks may include legitimate callers of the shared error logger. The defect is not the count by itself. The defect is that evidence overlap substitutes for a typed, conditional write relationship and loses the statement-level mapping needed to explain why and how each path can reach the write.

### Final activity hydration is incomplete

The Grocery final artifact contains seven activities. Their `effect_ids` arrays contain 12 references to seven distinct effects, while 28 effects remain in the top-level facts/model.

This does not prove that all 28 effects belong to those seven activities; some anchors may be excluded or grouped differently. It proves that the artifact needs an explicit disposition and consistency check. The current model does not establish whether an unreferenced effect is:

- outside every accepted activity;
- omitted because its anchor was excluded;
- unavailable to the provider packet;
- lost during provider interpretation; or
- accidentally left orphaned during materialization.

### What the Grocery evidence proves

- Table references are extracted without data-access edges.
- Writes are extracted without write edges or bindings.
- Read and write access cannot be reconstructed from the edge graph.
- Effect evidence identifies the enclosing routine rather than the exact statement.
- Trace backlinks are assigned through evidence overlap.
- Known transaction syntax is not represented on the demonstrated write effect.
- The final activity model does not account for every top-level effect and provides no explicit disposition for the remainder.

### What the Grocery evidence does not prove

- It does not prove that every table resource belongs to a business activity.
- It does not prove that every recognized SQL write is reachable on every trace that visits its enclosing routine.
- It does not prove that all 28 effects should be attached to the seven generated activities.
- It does not establish commit success from the presence of `COMMIT`; exception paths and autonomous transactions still require dialect-aware control-flow analysis.
- It does not justify implementing Oracle or PL/SQL branches in common orchestration.

## Exact implementation path

The failure is created by three disconnected phases.

### 1. Connections populate only part of the graph

`Extractor._connections()` asks adapters for calls and optional relations. It emits `calls` edges and whatever relationship records an adapter explicitly returns.

It never consumes `adapter.resources()` or `adapter.effects()`, so detected data access and external actions do not automatically become graph edges.

```text
adapter.calls(unit)       ---> Edge(kind = calls)
adapter.relations(source) ---> Edge(kind = adapter relation)

adapter.resources(unit)   -X-> no data edge
adapter.effects(unit)     -X-> no operation edge
```

### 2. Observations populate side collections

`Extractor._observations()` independently:

- inserts resource records returned by `adapter.resources(unit)`;
- inserts rule observations; and
- inserts effects returned by `adapter.effects(unit)`.

For resources, it stores the enclosing unit's evidence ID. For effects, it generates an effect identity from the unit and match position but again stores the enclosing unit's evidence ID. It does not hydrate edge records or operation bindings.

### 3. Tracing cannot follow what is not in the graph

`Extractor._traces()` constructs its adjacency list exclusively from `facts.edges`. Therefore it cannot traverse a data operation or outbound invocation that was stored only in `resources` or `effects`.

It then attempts to repair effect membership using evidence-set intersection. This produces both observed failure modes:

- PetClinic effects remain completely orphaned because the effect-owning symbols are not reached from the selected UI anchors; and
- Grocery effects acquire trace IDs when their enclosing routine evidence happens to appear in a trace, without an explicit read/write relationship or bindings.

### 4. Packet assembly propagates the incomplete state

Activity packet assembly includes only effects whose `trace_ids` intersect the packet's traces. PetClinic's effects are therefore excluded. Grocery effects can be included through the evidence-overlap backlinks, but the packet receives partial effects without typed data edges or bindings.

### 5. Provider output is allowed to remain partially hydrated

The provider returns complete `Activity` and `InformationUse` shapes, but required array fields may be empty. Reference validation verifies that referenced IDs exist and have allowed types. It does not verify that all deterministically known operations were included, that bidirectional references agree, or that an effect is reachable through its activity traces.

The final artifact can therefore be schema-valid while structurally incomplete.

## Root cause

The root cause is fragmented ownership of one logical operation.

Calls, resources, bindings, effects, traces, UI calls, activities and information uses are extracted or assembled through separate loops. There is no single normalized operation contract whose successful decoding obligates the canonical model to hydrate every applicable record and reference.

The implementation treats these as independent observations:

```text
resource discovered
effect discovered
binding discovered
edge discovered
trace built
activity interpreted
information use proposed
```

They are actually projections of the same evidenced operation. Creating only some projections leaves structurally orphaned facts.

The JSON schema compounds the problem by validating shape and reference existence without validating hydration completeness. Empty arrays are legal even when supported extraction has already observed facts that require references.

## Relationship to previous findings

F-08 is related to, but not replaced by, the earlier defects:

- **F-01** explains how a parallel normalization path can discard structural relationships already produced elsewhere. F-08 covers operations that reach resources/effects but are never fully projected into the canonical graph and activity model.
- **F-02** requires discoverable adapter capabilities for semantic resolution. Those capabilities must produce the normalized operation facts that F-08 hydrates. Even an unresolved operation must still be structurally represented.
- **F-03** covers records that incorrectly default to resolved. F-08 covers missing references and partial records regardless of their resolution label.
- **F-04** covers false trace completion. Missing data and invocation edges can contribute to an empty frontier, but F-08 also affects packets, effects, bindings and information uses after traversal.
- **F-05** covers false SQL call extraction. Correct SQL parsing is necessary to distinguish calls from reads and writes, but correct classification still must hydrate the canonical records described here.
- **F-06** covers canonical identity and reconciliation of multiple anchor representations. F-08 covers the operation closure beneath those anchors.
- **F-07** covers whether an implementation unit is a legitimate entry-point anchor. F-08 applies after an anchor or supporting symbol is selected: its evidenced operations must be connected completely.

Fixing F-08 must not hide unresolved F-02/F-05/F-07 conditions by manufacturing edges. Conversely, fixing those defects does not automatically populate the missing canonical references.

## RFC requirements violated

The RFC already requires the behavior:

- Source extraction includes endpoint contracts and data mappings.
- Initial relationship kinds include `reads_data`, `writes_data` and `invokes_endpoint`.
- Service traces include local and remote operations, input/return bindings, data reads/writes, responses and effects.
- Trace construction collects data operations along the path.
- SQL/ORM calls preserve query/operation, parameters, tables/columns, access kind, returned data and transaction handling.
- Remote calls preserve destination, operation, request/response mappings and relevant outcome handling.
- Effects preserve target, condition, payload or changed fields, ordering and transaction scope.
- Activities explicitly reference their bindings, effects and information uses across UI, API, SQL and DAG sources.
- Information uses connect access semantics to resources, bindings, effects and traces.
- Frontend tracing follows typed wrappers and preserves calls inside the canonical UI interaction.
- Adapter capabilities are declared separately for data access and response/effect tracing.

The requirements are distributed across the RFC. The following explicit invariant must be added so an implementation cannot satisfy them by creating disconnected records:

> Every supported detected data access, outbound invocation, response or observable effect must atomically hydrate every applicable canonical resource, edge, binding, effect and trace reference. Once an activity exists, deterministic materialization must hydrate its applicable binding, effect and information-use references from the accepted trace closure. Unsupported or unresolved portions remain explicit diagnostics; they must not become silent omissions or unexplained empty collections. A provider must never be required to reconstruct missing structural relationships from source excerpts.

## Proposed solution

### 1. Establish one normalized operation contract

Extend the existing adapter contract with one canonical, versioned operation observation rather than adding another parallel extractor or decoder. The conceptual contract must carry:

```text
origin_ref
operation_kind: read | write | invoke | respond | publish | render | ...
target_ref or unresolved target description
input binding observations
output binding observations
condition/control-flow identity
transaction/completion observation
exact source span
resolution and reason
adapter capability/provenance
```

Adapters own source-specific parsing. The common core owns exactly one projection from this normalized observation into the canonical records.

The contract can be implemented by consolidating the existing `resources`, `effects`, `bindings` and semantic-relation outputs or by making them coordinated views over one adapter result. It must not create another raw-match decoder alongside the existing owners.

### 2. Hydrate canonical facts atomically

For each operation observation, a single common hydrator must create or reconcile all applicable records in one transaction-like step:

- canonical target `Resource`;
- `reads_data`, `writes_data`, `invokes_endpoint` or other appropriate `Edge`;
- canonical input/output/internal `Binding` records;
- effect record when the operation has an observable outcome;
- exact statement/call evidence;
- resolution and diagnostics; and
- internal origin metadata needed to attach the operation to traces deterministically.

If any required projection cannot be produced, retain the portions that are known and emit a structured hydration diagnostic identifying the missing projection. Do not discard the operation.

### 3. Derive trace membership from graph identity

Trace membership must be based on the originating symbol and operation edge, not source-evidence overlap.

When traversal reaches an operation edge:

- include the edge in `Trace.edge_ids`;
- include its bindings in the trace and every graph scope containing that trace;
- associate its effect with that trace;
- treat a data resource as a typed terminal rather than enqueueing it as a callable symbol;
- stop at an unresolved external/resource boundary with an explicit frontier reason where appropriate; and
- preserve the operation even if the downstream implementation is unavailable.

Evidence remains proof for the relationship. Evidence identity must not substitute for the relationship.

### 4. Hydrate activities deterministically after interpretation

Provider interpretation may select or propose an activity's anchors, traces, concepts and semantic description. After that response is validated, a deterministic materializer must populate the activity closure from the selected traces and accepted semantic decisions:

- union applicable input/output bindings;
- union applicable effects;
- create or reconcile information uses for evidenced resource access;
- connect information uses to resources, bindings, effects and traces;
- preserve excluded or ambiguous operations with an explicit disposition; and
- reject provider references outside the supplied evidence closure.

The provider may narrow an operation based on evidenced conditions, but it may not silently delete known structural facts by returning empty arrays.

### 5. Add hydration-completeness validation

Keep JSON Schema validation for document shape and add semantic invariants for the populated model.

At minimum, validate:

1. Every supported detected data operation has a typed operation edge or a structured unsupported diagnostic.
2. Every supported detected outbound operation has an `invokes_endpoint` edge or an explicit unresolved-target diagnostic.
3. Every operation edge identifies its origin, target when known, exact evidence, bindings when observed, resolution and reason.
4. Every write edge has a corresponding write effect when an observable mutation is established.
5. Reads are represented through `reads_data` and later `InformationUse`; they are not fabricated as effects.
6. Every effect with an originating operation is reachable from each listed trace through that operation's origin/edge.
7. Every applicable trace includes the operation edge, rather than receiving the effect solely through evidence overlap.
8. Every effect binding ID resolves to a canonical binding and has a compatible direction.
9. Every activity effect/binding/information-use reference is within the closure of its accepted traces or is marked as a separately evidenced semantic addition.
10. Every information use references an existing activity, concept, resource and applicable trace; its effects and bindings agree with its access kind.
11. Every supported extracted operation is represented in a candidate activity closure, explicitly excluded with a reason, or retained as an unresolved inventory item; unfinished semantic work remains attempt state and cannot enter a published model.
12. Empty collections that mean “not extracted” are distinguished through capability status and diagnostics from collections proven to be empty.
13. Evidence for an operation points to the exact call or SQL statement, with enclosing-symbol evidence retained separately.
14. Facts, traces, model-ready graph scopes, semantic request/response caches and the final artifact maintain reference closure after caching, rebuild and provider failure.
15. Trace traversal distinguishes callable targets from terminal resource targets and never assumes every resolved edge points to a symbol.

Validation must fail the build or downgrade it to explicit partial status when a mandatory hydration invariant is violated. It must not publish a fully supported activity whose known effect or data access was structurally omitted.

### 6. Keep the common implementation language agnostic

The common hydrator must dispatch on normalized operation capability and fact kind, never on language, framework or SQL dialect names.

Forbidden common-core patterns include:

```text
if language == "java"
if framework == "spring"
if language == "typescript"
if dialect == "oracle"
```

Java/Spring, TypeScript/React, PL/SQL, PostgreSQL and future technologies belong in discoverable, versioned adapters or enrichers. Each adapter declares which operation capabilities it supports and emits the same normalized operation contract. The core projection, trace membership, activity hydration and semantic validation remain technology independent.

### 7. Preserve DRY ownership

Before adding an extractor, decoder, registry, schema vocabulary or normalization path, locate and extend the existing owner of that responsibility.

Do not create separate resource, edge and effect extraction implementations that independently rediscover the same source operation. If an adapter cannot reuse the canonical operation contract, document the incompatibility and add conformance tests proving equivalent behavior before proceeding.

## Required regression and conformance tests

### Common contract tests

The same adapter-neutral fixtures must verify:

- a read creates a resource, `reads_data` edge, exact evidence and trace membership;
- a create/update/delete creates a resource, `writes_data` edge, effect, bindings and trace membership;
- an outbound call creates an `invokes_endpoint` edge, external-action effect and request/response bindings;
- an unresolved target preserves the origin and operation with an unresolved edge/effect and diagnostic;
- a response remains distinct from a committed data write;
- shared helper effects attach only to traces that can reach the helper through resolved or explicitly alternative paths;
- evidence overlap alone cannot create trace membership;
- provider output cannot erase deterministic effects or bindings from an accepted trace closure;
- information uses are hydrated after activity/concept creation; and
- semantic validation rejects intentionally orphaned edges, effects, bindings and information uses.

### PetClinic acceptance tests

Tests must cover direct and wrapped frontend calls without relying on component or method names:

1. A registered action reaches its handler, shared wrapper and outbound HTTP operation when statically resolvable.
2. The outbound operation produces `invokes_endpoint`, effect and binding records.
3. Literal and provable template/constant URLs resolve to canonical protocol operation identities.
4. Dynamic destinations remain explicit unresolved targets while retaining origin, edge, effect and trace membership.
5. Every detected supported HTTP operation has an explicit represented, unsupported or excluded disposition.
6. Every model-ready graph scope containing the operation also contains its reachable effects and reference closure.
7. Accepted activities contain the deterministically applicable effect references.
8. A reusable wrapper is not independently counted as the user's business activity merely because it owns the physical `fetch` call.

### Grocery acceptance tests

Tests must use real dialect-aware fixtures and the same canonical assertions:

1. `SELECT` operations produce `reads_data` edges to the correct tables with exact statement evidence.
2. `INSERT`, `UPDATE` and `DELETE` operations produce `writes_data` edges and matching effects.
3. Parameter, selected-value, changed-field and result bindings are preserved when supported.
4. Control-flow conditions and exception paths constrain effect reachability.
5. Transaction and completion facts are populated when established; otherwise the precise gap is recorded.
6. `jta_error.log_error` links its `jta_errors` write through an explicit operation edge and retains the autonomous-transaction/commit evidence supported by the adapter.
7. A trace reaches that effect only through a resolved or explicitly alternative call path to `log_error`, never solely because evidence IDs overlap.
8. Package operations, private helpers and registered triggers follow the corrected F-06/F-07 identity and eligibility rules before activity hydration.
9. Oracle-specific parsing remains inside a discoverable dialect adapter; the common hydration assertions also pass equivalent PostgreSQL and other supported SQL fixtures.

### End-to-end model tests

For both trial styles, assert the entire closure:

```text
anchor
  -> trace
     -> symbol
     -> operation edge
        -> resource
        -> bindings
        -> effect when applicable
  -> activity
     -> bindings
     -> effects
     -> information uses
        -> concept/resource/trace/effect/binding evidence
```

Tests must validate the persisted facts artifact, the exact whole-graph or deterministic-slice input, the verified candidate and the final domain artifact. Testing only an adapter return value or JSON Schema shape is insufficient.

## Acceptance criteria

1. The canonical model remains the single owner of business-domain facts; no parallel data-flow/effect model is introduced.
2. Every supported detected operation completely hydrates all applicable canonical records and references.
3. `reads_data`, `writes_data` and `invokes_endpoint` edges are emitted when supported evidence establishes those operations.
4. Trace membership derives from graph identity and reachability, not evidence overlap.
5. Effects contain applicable targets, bindings, conditions, completion/transaction state, exact evidence, resolution and trace backlinks.
6. Activity bindings, effects and information uses are deterministically materialized from accepted trace closures and evidenced semantic decisions.
7. Every omitted or unresolved projection has a structured diagnostic and visible partial-coverage consequence.
8. Semantic validation rejects or downgrades orphaned or contradictory hydration even when the JSON document is shape-valid.
9. PetClinic's supported frontend calls reach every applicable model-ready graph scope and final activity through canonical invocation relationships.
10. Grocery's supported reads and writes reach traces and final activities through canonical data relationships.
11. Both trials retain honest unresolved states where target, binding, control flow, transaction or completion cannot be proven.
12. The common core contains no language-, framework- or dialect-name branches.
13. New adapters satisfy the same normalized-operation and hydration conformance suite.
14. Provider availability or quality is not required to establish structural hydration correctness.

## Non-goals

- Do not infer business ownership from touching a table or calling a service.
- Do not mark a write committed merely because a mutation statement exists.
- Do not resolve a dynamic URL or SQL target by guessing.
- Do not attach every effect in the repository to every accepted activity.
- Do not turn reads into effects solely to make them visible.
- Do not make the provider reconstruct missing deterministic graph facts.
- Do not fix this with language/framework/dialect conditionals in common orchestration.
- Do not add a second canonical model or duplicate normalization path.

## Certainty

Confidence is very high.

The finding is directly established by:

- the canonical schema fields already present;
- the separate `_connections()`, `_observations()` and `_traces()` implementation paths;
- the evidence-overlap effect attachment logic;
- PetClinic's zero data/invocation edges, seven orphaned HTTP effects and zero final activity effect references; and
- Grocery's calls-only edge graph, 38 table resources, 28 binding-free write effects and enclosing-routine evidence.

The final expected number of PetClinic HTTP operations, Grocery activities or activity-effect memberships is intentionally not asserted. Those totals depend on corrected anchor selection, identity reconciliation, resolution and reachability. The defect is the absence of complete, internally consistent hydration for each operation that the supported extraction path does detect.

## Resolution

Resolved on 2026-09-08.

- Added one strict, versioned, technology-neutral adapter operation contract and one common atomic projector for canonical resources, typed operation edges, bindings, effects, exact evidence, diagnostics and provenance.
- Trace and effect membership now derives from graph reachability. Activity bindings, effects and information uses are deterministically materialized and semantically validated against accepted trace closure.
- Frontend HTTP extraction now retains literal, constant, template and unresolved targets, request/response bindings, exact call evidence and explicit projection gaps. The live PetClinic corpus hydrates all 10 supported direct `fetch` operations into reachable invocation/effect closure.
- SQL extraction now hydrates exact read/write relationships, physical targets, bindings, conditions and evidenced transaction declarations without claiming runtime completion. The live Grocery corpus hydrates 61 reads and 25 writes; all 86 data edges are trace-reachable and all 25 writes have matching effects.
- Provider-independent and cross-adapter conformance coverage verifies all 14 acceptance criteria, including orphan rejection, partial-state diagnostics, language-agnostic common code and deterministic model-ready closure.

Verification: 35 focused F-08 tests, 331 Business Domain tests, 95 shared parser/CSG tests, 23 valid and 14 invalid contract specimens, Python compilation and `git diff --check` all pass.
