# Business-domain artifact contracts

Schema version 1; companion to the [RFC](../speed-business-domain-discovery.md#data-model). The [JSON Schema](business-domain-artifacts.schema.json) is the normative proposed structural contract. The implementation must replace its current runtime schema with an identical generated/copied artifact when these defects are implemented; this documentation change does not modify runtime code. This document states the cross-record semantics that JSON Schema cannot express; application validators must enforce those invariants separately.

## Artifact ownership and validation

Validate a stored document against its named `$defs` entry: FactsArtifact, DomainArtifact, SnapshotArtifact, StatusArtifact, OverridesArtifact or CacheArtifact. Immutable builds use DomainArtifact. DigestDomainProjection validates the domain-related field subset of the existing version-2 digest; it is not a replacement schema for unrelated digest sections. Existing digest producers must merge and validate both contracts. Every declared field is required; unknown fields are rejected. Nullable fields must be explicit null. Maps are keyed by enclosed record ID; all IDs must be unique across the model closure, including nested UI records.

Facts contain deterministic observations and source-resolution uncertainty, not domain assignments. Interpretations live in the canonical model. Extracted RuleObservation.rule_id is null and activity_ids is empty in facts; publication assigns semantic references only in the canonical copy. Facts contain all extracted diagnostics; canonical models retain the complete transitive closure of references actually used. A ModelReadyGraph contains the complete validated fact closure in whole-graph mode. Application-boundary and entrypoint-bundle slices contain complete entry-point closures plus explicit cross-scope references. An execution-segment slice contains an exact trace subgraph plus typed cut-edge obligations and is valid only as input to reconciliation; no slice is an arbitrary file batch or independently publishable model.

## Hashes, snapshots and cache keys

Use UTF-8 compact JSON with recursively sorted keys, no insignificant whitespace and no non-finite numbers for hash inputs. Fingerprint.value hashes the other named component hashes as an object; each component hashes the exact corresponding source/config/version inventory. For file sources, source hash is over original bytes. Source paths and inclusion/exclusion decisions are fingerprint inputs.

SnapshotArtifact.source_hash hashes the original source; fragment.excerpt_hash hashes UTF-8 text. Snapshot metadata content_hash is the source hash, not the blob-file hash. Persist the snapshot under the SHA-256 of its canonical JSON bytes. Evidence.content_hash hashes its excerpt, and its pointer resolves to that same retained text. Repository-span locators additionally preserve one-based inclusive lines and source_hash. Exact execution-event locators are required for observed-runtime claims; static source does not establish execution.

Request cache key = SHA-256 of the canonical `SemanticRequest` with transport-only `request_id` and `deadline_at` omitted. Response cache key = SHA-256(canonical object of request_key, prompt_hash, output_schema_hash and provider_fingerprint). Validate the stored key against these inputs before cache reuse. Operation, response fingerprint and request fingerprint must match; reuse does not bypass evidence/reference validation. Cache a candidate response only after deterministic validation and independent semantic verification pass. Cache a verifier response only after its shape, references and evidence citations validate. JSON Schema passed to the provider is a trusted schema document, not source-controlled instructions.

## Referential and semantic invariants

- Record-map key equals enclosed id. Typed references resolve to the named collection, including nested UI records. Anchor source IDs resolve to resources. An enforcement site's source ID resolves to the enforcing symbol or a declarative resource; a callable site should retain its method/function identity rather than being reduced to its enclosing file. Snapshot IDs resolve to source_snapshots; dependency IDs resolve to bindings, resources (for example, a table with a declared constraint), or other rules whose result or enforcement the rule depends on. Subject IDs may name any record. Every *_ids field has its documented target collection; do not infer a missing target from its label. The runtime's `business_domain_reference_targets.json` declares these target kinds separately from source-language rules.
- Binding sources/targets can be unresolved null only with a reason. Null scope fields mean unknown, not unrestricted. UI route_patterns null means unknown; [] means no route. A resolved root view may have null parent; an unresolved parent needs a diagnostic.
- Activity input/output IDs point to bindings of the corresponding direction. Effects, information uses and ownership claims have independent evidence. A read or shared table does not imply ownership. Ownership with unknown domain remains an explicit proposal/gap, not an automatic assignment.
- Trace edge order is discovery traversal order; branch conditions remain on edges. It is not a fabricated runtime sequence. Missing control-flow proof leaves enforcement unresolved. Effect completion committed requires transaction-path evidence; observed requires execution evidence. Declared effects are never reported as completed executions.
- UITransition references UIState/UIEvent/UICall/UIOutput in its containing interaction. UI bindings reference the canonical map. Rule conflicts name rule relationships or observations. Domain concepts/rules/ownership IDs resolve to their respective maps. Domain relationships require both endpoint activities and trace evidence.
- At most one primary domain per activity. Counts derive from distinct symbol memberships; shared files are non-additive. Ownership proposals require supporting activity/information-use/claim records and independent review state. Model-produced names are interpretations, not code identities.
- Coverage anchors_total = processed + excluded + pending; every anchor is accounted for. Facts anchors with status `candidate` count as `anchors_pending` until semantic disposition. `anchors_pending` is attempt progress and must be zero in a published DomainArtifact. A partial published model may contain explicit unresolved traces or capability gaps, but never pending semantic work, invalid evidence or budget/deadline truncation. Missing material evidence limits record support without converting unfinished processing into a publishable model.
- Status phase and timestamps follow RFC transitions; failed/cancelled/unavailable attempts cannot replace the published domain model. Status freshness is recorded at the last explicit observation/build, not live source scanning on reads. Published build IDs link to retained model versions.
- Override revision equals its last decision revision (0 with no decisions). Revisions are contiguous starting at 1. Persist result_domain_ids when allocating merge/split identities. Decision explanation and author are nonempty; names are trimmed/nonempty <=120 characters and explanations <=2000. Replay checks expected build and applicability; conflicts preserve history. Source-based review evidence snapshots the immutable decision.
- Candidate semantic IDs are request-scoped. Producers send empty derived symbol memberships/counts where not yet computed; the orchestrator recomputes them, resolves persistent domain IDs and validates before publication. Synthesis, verification and repair cannot set human acceptance. A verifier cannot mutate the candidate; repair produces a complete replacement candidate that is verified again.

## Populated examples

[UI](examples/ui.domain.json), [API](examples/api.domain.json), [SQL](examples/sql.domain.json) and [DAG](examples/dag.domain.json) are manually authored partial model specimens, not extractor output. Each contains an activity, input/output bindings, a selected effect and retained evidence. The API specimen includes a proposed domain, information use and explicitly unresolved ownership; other semantic collections remain empty where a complete interpreted record has not been authored; uncertainty is explicit. UI/DAG evidence is a documented fixture requirement, not implementation. API/SQL retain authored source snapshots but omit full implementation traces. Facts/status/snapshot siblings illustrate other artifacts. Empty and rename review documents plus synthesis-request, verification-request and verification-response cache specimens demonstrate their envelopes; fixture-reviewer is an authored identity, not a real review. The rename specimen is a later proposed input, not applied to the model with override_revision 0. These are complete schema documents, not ellipsis-filled pseudo-JSON. The RFC's richer findings remain acceptance expectations beyond the compact specimens.

## Executable contract checks

Run `.venv/bin/python specs/tech/contracts/check_contracts.py` from the repository root. This validates the specification schema, populated documents, example reference closure, captured source hashes, semantic-unit accounting, request/response cache keys and linkage, and rejection of malformed variants. It is not the production validator: lifecycle transitions, full typed-reference semantics, semantic support and review replay still require implementation tests. No provider or database is invoked.

## Exact type index

The following shapes are generated from the schema. A pipe denotes an enum/union; arrays and maps are typed. Hash/ID patterns and minimum array sizes are defined in JSON Schema. All object fields below are required, including nullable fields, unless marked optional for backward compatibility.

### Diagnostic

```text
code: string
message: string
subject_ids: Array<string>
evidence_ids: Array<string>
```

### Error

```text
code: string
message: string
field: string | null
retryable: boolean
provider_failure?: ProviderFailure | null
```

### ProviderFailure

```text
schema_version: 1
category: authentication_required | authorization_denied | capability_unavailable | rate_limited | transport_unavailable | timeout | process_failed | response_incomplete | response_invalid | unknown
scope: provider | request
retryable: boolean
native_status: string | null
message: string
diagnostic_log: string | null
```

### Scope

```text
environment: string | null
tenant: string | null
actor: string | null
profile: string | null
effective_from: string (date-time) | null
effective_to: string (date-time) | null
version: string | null
entrypoint_ids: Array<string> | null
```

### Fingerprint

```text
value: string
sources: string
configuration: string
extractors: string
prompts: string
provider: string
overrides: string
snapshots: string
```

### Capability

```text
language: string | null
framework: string | null
version: string | null
adapter: string
adapter_version: string
feature: "parsing" | "declaration_extraction" | "entrypoint_detection" | "call_classification" | "callable_resolution" | "overload_resolution" | "type_resolution" | "relationship_resolution" | "framework_enrichment" | "bindings" | "data_access" | "rules" | "outputs" | "runtime_selection" | "control_flow"
status: "supported" | "partial" | "unsupported"
diagnostic_codes: Array<string>
```

### Coverage

```text
anchors_total: integer >= 0
representations_total: integer >= 0
representations_canonicalized: integer >= 0
correspondences_ambiguous: integer >= 0
correspondences_unresolved: integer >= 0
anchors_processed: integer >= 0
anchors_excluded: integer >= 0
anchors_pending: integer >= 0
edges_resolved: integer >= 0
edges_ambiguous: integer >= 0
edges_unresolved: integer >= 0
evidence_valid: integer >= 0
evidence_invalid: integer >= 0
unsupported_source_ids: Array<string>
diagnostics: Array<Diagnostic>
```

`anchors_total` counts canonical anchors, never raw contract/registration/implementation representations. `representations_total` counts those source-preserving records. `representations_canonicalized` counts representations assigned to resolved or provisional review-required canonical anchors. Ambiguous and unresolved correspondence counts remain separate, so neither provider workload nor product coverage can treat extracted representations as independent operations.

### Limits

```text
max_trace_depth: integer >= 1
max_symbols_per_activity: integer >= 1
max_request_input_tokens: integer >= 1
max_request_output_tokens: integer >= 1
max_build_input_tokens: integer >= 1
max_build_output_tokens: integer >= 1
token_estimator: nonempty string
provider_context_tokens: integer >= 1 | null
provider_max_output_tokens: integer >= 1 | null
effective_request_input_tokens: integer >= 1
effective_request_output_tokens: integer >= 1
provider_concurrency: integer >= 1
deadline_seconds: integer >= 1
max_source_bytes: integer >= 1
max_artifact_bytes: integer >= 1
cache_retention_days: integer >= 1
semantic_units_total: integer >= 0
semantic_units_validated: integer >= 0
semantic_units_cached: integer >= 0
semantic_units_active: integer >= 0
semantic_units_failed: integer >= 0
semantic_units_pending: integer >= 0
model_ready_graph_tokens: integer >= 0
completion_input_tokens_reserved: integer >= 0
completion_output_tokens_reserved: integer >= 0
input_tokens_reserved: integer >= 0
input_tokens_reported: integer >= 0 | null
output_limit_enforcement: unknown | provider | local_estimate
output_tokens_reported: integer >= 0 | null
requests: integer >= 0
retries: integer >= 0
elapsed_ms: integer >= 0
source_bytes: integer >= 0
artifact_bytes: integer >= 0
truncated: boolean
```

### Locator

```text
one of ({ kind: "repository_span", path: string, start_line: integer >= 1, end_line: integer >= 1, source_hash: string, snapshot_id: string, pointer: string }; { kind: "snapshot_pointer", snapshot_id: string, pointer: string }; { kind: "execution_event", snapshot_id: string, run_id: string, event_id: string, observed_at: string (date-time) })
```

### Evidence

```text
id: string
source_kind: "source" | "test" | "contract" | "documentation" | "user_review" | "configuration" | "external_policy" | "workflow" | "execution"
locator: Locator
symbol_id: string | null
content_hash: string
excerpt: string
claim_kind: string
extractor: string
extractor_version: string
```

### Snapshot

```text
id: string
resource_kind: string
resource_identity: string
content_hash: string
local_blob_path: string
provider_revision: string | null
retrieved_at: string (date-time)
effective_from: string (date-time) | null
expires_at: string (date-time) | null
scope: Scope
availability: "available" | "unavailable"
activation_evidence_id: string | null
```

### Resource

```text
id: string
kind: "repository_file" | "service" | "database" | "table" | "queue" | "configuration" | "clock" | "literal" | "external_policy" | "workflow" | "review"
name: string
language: string | null
framework: string | null
version: string | null
locator: Locator | null
evidence_ids: Array<string>
resolution: "resolved" | "ambiguous" | "unresolved"
reason: string | null
```

### Symbol

```text
id: string
qualified_name: string
signature: string | null
kind: "function" | "class" | "method" | "field" | "type" | "module" | "declarative_operation"
file: string
evidence_ids: Array<string>
resolution: "resolved" | "ambiguous" | "unresolved"
reason: string | null
```

### Ref

```text
kind: "resource" | "symbol" | "anchor" | "binding" | "effect" | "activity" | "concept" | "rule" | "domain" | "ui_element" | "ui_event" | "ui_state" | "ui_output"
id: string
```

### Binding

```text
id: string
name: string
value_type: string
direction: "input" | "output" | "internal"
source: Ref | null
target: Ref | null
expression: string | null
scope: Scope
evidence_ids: Array<string>
resolution: "resolved" | "ambiguous" | "unresolved"
reason: string | null
```

### Edge

```text
id: string
from_ref: Ref
to_ref: Ref | null
kind: "declares" | "inherits" | "implements" | "calls" | "has_field" | "accepts_type" | "returns_type" | "reads_data" | "writes_data" | "exposes_endpoint" | "invokes_endpoint" | "tests_behavior" | "documents_behavior" | "depends_on" | "emits" | "selects_implementation"
condition: string | null
binding_ids: Array<string>
evidence_ids: Array<string>
resolution: "resolved" | "ambiguous" | "unresolved"
reason: string | null
```

### Operation

```text
protocol: "http" | "rpc" | "graphql" | "sql" | "event" | "ui" | "workflow" | "cli" | "library"
service_resource_id: string | null
name: string
method: string | null
path: string | null
version: string | null
```

### Anchor

```text
id: string
kind: string
source_id: string
symbol_id: string | null
operation: Operation | null
status: "candidate" | "processed" | "excluded" | "pending"
evidence_ids: Array<string>
resolution: "resolved" | "ambiguous" | "unresolved"
reason: string | null
```

`Anchor.status: pending` is valid only in deterministic facts and live attempt state. A published `DomainArtifact` permits only `processed` or `excluded` anchors; semantic uncertainty is carried by `resolution`, dispositions, claims and support.

### AnchorRepresentation

```text
id: ID
role: "contract" | "registration" | "declaration" | "implementation" | "external_boundary"
source_id: ID
symbol_id: ID | null
operation: Operation | null
registration: EntryPointRegistration | null
evidence_ids: Array<EvidenceID>
resolution: "resolved" | "ambiguous" | "unresolved"
reason: string | null
```

Each detected contract, registration, declaration, implementation or external boundary remains independently addressable. Canonicalization never erases the representation that supplied its evidence.

### EntryPointRegistration

```text
kind: string
event: string | null
timing: string | null
target: string | null
scope: string | null
condition: string | null
label: string | null
candidate_targets: Array<string> (at most 8)
evidence_ids: Array<EvidenceID>
resolution: "resolved" | "ambiguous" | "unresolved"
reason: string | null
```

This technology-neutral record preserves how an entry point is registered or exposed. Adapters populate the applicable fields without forcing routing, user-action, database-trigger, schedule, subscription or command semantics into common orchestration. A resolved registration has exact evidence and no reason; an incomplete or ambiguous registration retains its reason.

### AnchorCorrespondence

```text
id: ID
canonical_anchor_id: ID | null
representation_ids: Array<ID> (at least one)
status: "resolved" | "ambiguous" | "unresolved" | "inferred_review_required"
candidate_representation_sets: Array<Array<ID>>
relationship_ids: Array<ID>
evidence_ids: Array<EvidenceID>
reason: string | null
```

Resolved correspondence requires a canonical anchor, no alternative sets and null reason. Ambiguous correspondence has no selected canonical anchor, at least two nonempty alternative sets of representation IDs and a reason. Unresolved correspondence has no selected canonical anchor and a reason. Inferred/review-required correspondence has a provisional canonical anchor, at least one candidate representation set and the reason deterministic evidence could not decide it. Alternative sets never become fake entries in the canonical anchor map. Exact normalized relationships and evidence—not names or source order—support the decision.

### UIElement

```text
id: string
kind: "view" | "control"
symbol_id: string | null
label: string | null
route_patterns: Array<{ pattern: string, evidence_ids: Array<string> }> | null
routing_resolution: "resolved" | "ambiguous" | "unresolved"
parent_view_id: string | null
route_binding_ids: Array<string>
evidence_ids: Array<string>
resolution: "resolved" | "ambiguous" | "unresolved"
reason: string | null
```

### UIEvent

```text
id: string
element_id: string
trigger: string
handler_symbol_id: string | null
evidence_ids: Array<string>
resolution: "resolved" | "ambiguous" | "unresolved"
reason: string | null
```

### UIValidation

```text
id: string
event_id: string
input_binding_ids: Array<string>
predicate_evidence_ids: Array<string>
enforcement: "native" | "client" | "server"
failure_output_ids: Array<string>
rule_observation_id: string | null
evidence_ids: Array<string>
resolution: "resolved" | "ambiguous" | "unresolved"
reason: string | null
```

### UICall

```text
id: string
event_id: string
caller_symbol_id: string | null
target_anchor_id: string | null
request_binding_ids: Array<string>
response_binding_ids: Array<string>
failure_output_ids: Array<string>
evidence_ids: Array<string>
resolution: "resolved" | "ambiguous" | "unresolved"
reason: string | null
```

`UICall.resolution` describes static target-anchor resolution. A resolved UI
call identifies exactly one canonical anchor. Runtime request values, response
mapping and completion remain independently represented by bindings and the
corresponding effect.

### UIState

```text
id: string
label: string
render_evidence_ids: Array<string>
evidence_ids: Array<string>
resolution: "resolved" | "ambiguous" | "unresolved"
reason: string | null
```

### UITransition

```text
id: string
from_state_id: string
event_id: string
guard_evidence_ids: Array<string>
to_state_id: string
call_ids: Array<string>
output_ids: Array<string>
evidence_ids: Array<string>
resolution: "resolved" | "ambiguous" | "unresolved"
reason: string | null
```

### UIOutput

```text
id: string
kind: "render" | "message" | "navigation" | "emitted_event" | "state_write"
target_ref: Ref | null
binding_ids: Array<string>
effect_id: string | null
evidence_ids: Array<string>
resolution: "resolved" | "ambiguous" | "unresolved"
reason: string | null
```

### UIInteraction

```text
elements: Map<ID, UIElement>
binding_ids: Array<string>
events: Map<ID, UIEvent>
validations: Map<ID, UIValidation>
calls: Map<ID, UICall>
states: Map<ID, UIState>
transitions: Map<ID, UITransition>
outputs: Map<ID, UIOutput>
```

### Trace

```text
id: string
anchor_id: string
symbol_ids: Array<string>
edge_ids: Array<string>
obligation_ids: Array<string>
frontier_ids: Array<string>
stop_reasons: Array<string>
traversal_complete: boolean
ui_interaction: UIInteraction | null
evidence_ids: Array<string>
resolution: "resolved" | "ambiguous" | "unresolved"
reason: string | null
```

### TraceObligation

```text
id: ID
trace_id: ID
kind: "implementation_selection" | "call_target" | "data_target" | "external_boundary" | "capability" | "depth_limit" | "symbol_limit" | "execution_segment"
origin_ref: Ref
edge_id: ID | null
candidate_target_ids: Array<ID>
status: "satisfied" | "ambiguous" | "unresolved" | "external" | "limit_reached"
reason_code: nonempty string
reason: nonempty string
evidence_ids: Array<EvidenceID>
```

Traversal exhaustion and semantic trace completion are separate. A resolved trace has no ambiguous, unresolved, external or limit-reached obligation material to its claimed implementation scope. Every missing expected relationship, adapter capability gap, traversal limit and execution-segment cut is a stable obligation; an empty edge frontier cannot erase it.

### Effect

```text
id: string
kind: "response" | "data_write" | "event_publish" | "external_action" | "render" | "navigation" | "audit" | "cache_write"
target: Ref | null
input_binding_ids: Array<string>
output_binding_ids: Array<string>
condition: string | null
outcome: string
protocol: string | null
target_identity_key: string | null
status: string | null
media_type: string | null
header_binding_ids: Array<string>
transaction_scope: string | null
completion: "declared" | "invoked" | "acknowledged" | "committed" | "observed" | "unknown"
trace_ids: Array<string>
evidence_ids: Array<string>
resolution: "resolved" | "ambiguous" | "unresolved"
reason: string | null
```

### Concept

```text
id: string
name: string
qualified_type_names: Array<string>
symbol_ids: Array<string>
evidence_ids: Array<string>
claim_ids: Array<string>
```

### InformationUse

```text
id: string
activity_id: string
concept_id: string
resource_ids: non-empty Array<string>
access: "reads" | "creates" | "updates" | "deletes" | "references"
binding_ids: Array<string>
effect_ids: Array<string>
trace_ids: Array<string>
evidence_ids: Array<string>
resolution: "resolved" | "ambiguous" | "unresolved"
reason: string | null
```

### Ownership

```text
id: string
concept_id: string
domain_id: string | null
kind: "creates" | "maintains" | "authoritative_source" | "shared" | "unknown"
activity_ids: Array<string>
information_use_ids: Array<string>
rationale: string
claim_ids: Array<string>
evidence_ids: Array<string>
support: "supported" | "partial" | "insufficient"
review_state: "proposed" | "accepted" | "rejected" | "needs_review"
unresolved_questions: Array<string>
```

### Activity

```text
id: string
name: string
description: string
anchor_ids: Array<string>
actor: string | null
concept_ids: Array<string>
rule_ids: Array<string>
trace_ids: Array<string>
input_binding_ids: Array<string>
output_binding_ids: Array<string>
effect_ids: Array<string>
information_use_ids: Array<string>
claim_ids: Array<string>
evidence_ids: Array<string>
implementation_status: "implemented" | "documented_only" | "implementation_unresolved"
support: "supported" | "partial" | "insufficient"
review_state: "proposed" | "accepted" | "rejected" | "needs_review"
unresolved_questions: Array<string>
```

### Site

```text
activity_ids: Array<string>
source_id: string
condition: string | null
evidence_ids: Array<string>
```

### Rule

Canonical rule identity includes its anchor context, observations, predicate/formula, scope, evaluation kind, preconditions and outcome. A shared condition with different consequences must not collapse distinct rules. Display names alone do not establish identity.

```text
id: string
name: string
description: string
category: "validation" | "eligibility" | "authorization" | "calculation" | "state_transition" | "invariant" | "cross_record_constraint" | "technical" | "unclassified" | "business_ordering" | "timing"
activity_ids: Array<string>
concept_ids: Array<string>
preconditions: Array<string>
predicate_or_formula: string | null
outcome: string
enforcement_sites: Array<Site>
evidence_ids: Array<string>
basis: Array<"source_observed" | "test_expected" | "contract_declared" | "documented" | "user_asserted">
enforcement_status: "verified_on_trace" | "declared_only" | "conditional" | "unresolved"
support: "supported" | "partial" | "insufficient"
conflicts: Array<string>
unresolved_questions: Array<string>
observation_ids: Array<string>
scope: Scope
parameter_binding_ids: Array<string>
dependency_ids: Array<string>
evaluation_kind: "predicate" | "calculation" | "transition" | "data_constraint" | "workflow" | "external_decision"
```

### RuleObservation

```text
id: string
rule_id: string | null
source_location_kind: "ui" | "api" | "sql" | "configuration" | "external" | "workflow"
native_expression: string | null
activity_ids: Array<string>
input_binding_ids: Array<string>
output_binding_ids: Array<string>
scope: Scope
dependency_ids: Array<string>
evidence_ids: Array<string>
resolution: "resolved" | "ambiguous" | "unresolved"
reason: string | null
```

### RuleRelationship

```text
id: string
from_observation_id: string
to_observation_id: string
kind: "equivalent" | "stronger_than" | "overrides" | "supplies_parameter" | "delegates_to" | "conditional_on" | "conflicts_with" | "unresolved"
verification: "verified" | "inferred" | "unresolved"
evidence_ids: Array<string>
explanation: string
```

### Claim

```text
id: string
subject_id: string
text: string
kind: string
evidence_ids: Array<string>
trace_ids: Array<string>
semantic_review: "supported" | "unsupported" | "uncertain"
```

### ActivityMembership

```text
activity_id: string
role: "primary" | "supporting"
claim_ids: Array<string>
```

### SymbolMembership

```text
symbol_id: string
activity_id: string
role: "implements" | "data" | "validates" | "tests" | "shared_support"
trace_ids: Array<string>
```

### BoundaryItem

```text
subject_ids: Array<string>
explanation: string
claim_ids: Array<string>
```

### Domain

```text
id: string
name: string
summary: string
activity_memberships: Array<ActivityMembership>
concepts: Array<string>
rules: Array<string>
ownership_ids: Array<string>
symbol_memberships: Array<SymbolMembership>
boundary_rationale: string
exclusions: Array<BoundaryItem>
alternatives: Array<BoundaryItem>
evidence_ids: Array<string>
claim_ids: Array<string>
support: "supported" | "partial" | "insufficient"
review_state: "proposed" | "accepted" | "rejected" | "needs_review"
unresolved_questions: Array<string>
file_count: integer >= 0
symbol_count: integer >= 0
shared_file_count: integer >= 0
```

### Relationship

```text
id: string
from_domain_id: string
to_domain_id: string
from_activity_id: string
to_activity_id: string
kind: "uses_information_from" | "requests_action_from" | "publishes_event_to"
trace_ids: Array<string>
evidence_ids: Array<string>
```

### Unassigned

```text
subject_kind: "anchor" | "anchor_correspondence"
subject_id: string
status: "excluded" | "unresolved"
reason: string
```

Published unassigned records are the projection of final excluded/unresolved canonical-anchor and anchor-correspondence dispositions. Represented dispositions resolve through activities and are not duplicated here. Published unassigned records never contain pending semantic work. Pending units and anchors exist only in the latest attempt status.

### IdentityChange

```text
kind: "added" | "retained" | "revised" | "retired" | "merged" | "split"
from_ids: Array<string>
to_ids: Array<string>
reason: string
```

### FactsArtifact

```text
schema_version: 1
generated_at: string (date-time)
build_id: string (uuid)
fingerprint: Fingerprint
capabilities: Array<Capability>
coverage: Coverage
warnings: Array<Diagnostic>
limits: Limits
resources: Map<ID, Resource>
symbols: Map<ID, Symbol>
edges: Map<ID, Edge>
anchors: Map<ID, Anchor>
anchor_representations: Map<ID, AnchorRepresentation>
anchor_correspondences: Map<ID, AnchorCorrespondence>
bindings: Map<ID, Binding>
traces: Map<ID, Trace>
trace_obligations: Map<ID, TraceObligation>
effects: Map<ID, Effect>
evidence: Map<ID, Evidence>
source_snapshots: Map<ID, Snapshot>
rule_observations: Map<ID, RuleObservation>
```

### DomainArtifact

```text
schema_version: 1
generated_at: string (date-time)
build_id: string (uuid)
fingerprint: Fingerprint
capabilities: Array<Capability>
coverage: Coverage
warnings: Array<Diagnostic>
limits: Limits
facts_build_id: string (uuid)
status: "complete" | "partial"
resources: Map<ID, Resource>
symbols: Map<ID, Symbol>
edges: Map<ID, Edge>
anchors: Map<ID, Anchor>
anchor_representations: Map<ID, AnchorRepresentation>
anchor_correspondences: Map<ID, AnchorCorrespondence>
bindings: Map<ID, Binding>
traces: Map<ID, Trace>
trace_obligations: Map<ID, TraceObligation>
effects: Map<ID, Effect>
evidence: Map<ID, Evidence>
source_snapshots: Map<ID, Snapshot>
rule_observations: Map<ID, RuleObservation>
activities: Map<ID, Activity>
concepts: Map<ID, Concept>
information_uses: Map<ID, InformationUse>
ownerships: Map<ID, Ownership>
rules: Map<ID, Rule>
rule_relationships: Map<ID, RuleRelationship>
claims: Map<ID, Claim>
domains: Map<ID, Domain>
relationships: Map<ID, Relationship>
unassigned: Array<Unassigned>
identity_changes: Array<IdentityChange>
override_revision: integer >= 0
```

### SnapshotArtifact

```text
schema_version: 1
snapshot_id: string
source_hash: string
encoding: "utf-8"
fragments: Array<{ id: string, original_locator: string, text: string, excerpt_hash: string }>
```

### StatusArtifact

```text
schema_version: 1
attempt_build_id: string (uuid) | null
phase: "idle" | "extracting" | "synthesizing" | "validating" | "complete" | "partial" | "unavailable" | "failed" | "cancelled" | "superseded"
execution_mode: "whole_graph" | "hierarchical" | null
current_scope_id: ID | null
root_reconciled: boolean
started_at: string (date-time) | null
completed_at: string (date-time) | null
published_build_id: string (uuid) | null
heartbeat_at: string (date-time) | null
freshness: "missing" | "current" | "stale"
external_freshness: "not_applicable" | "snapshot_only" | "verified_current" | "stale" | "unknown"
coverage: Coverage
limits: Limits
warnings: Array<Diagnostic>
error: Error | null
```

### ReviewOperation

```text
one of ({ operation: "accept" | "reject", domain_id: string }; { operation: "rename", domain_id: string, name: string }; { operation: "set_membership", domain_id: string, activity_ids: Array<string> }; { operation: "merge", domain_ids: Array<string>, name: string }; { operation: "split", domain_id: string, groups: Array<{ name: string, activity_ids: Array<string> }> })
```

### Decision

```text
id: string
revision: integer >= 1
expected_build_id: string (uuid)
author: string
recorded_at: string (date-time)
explanation: string
operation: ReviewOperation
result_domain_ids: Array<string>
```

### OverridesArtifact

```text
schema_version: 1
revision: integer >= 0
updated_at: string (date-time) | null
decisions: Array<Decision>
```

### GraphContext

`record_refs` identifies omitted canonical records. Its hashes establish identity, not semantic support; independent verification requires actual excerpts. The wire codec may transmit payload maps as arrays, but stored artifacts retain ID-keyed maps.

### GraphRecordRef

```text
id: ID
collection: string
content_hash: SHA-256
```

### GraphContext fields

```text
record_refs: Map<ID, GraphRecordRef>
resources: Map<ID, Resource>
symbols: Map<ID, Symbol>
edges: Map<ID, Edge>
anchors: Map<ID, Anchor>
anchor_representations: Map<ID, AnchorRepresentation>
anchor_correspondences: Map<ID, AnchorCorrespondence>
bindings: Map<ID, Binding>
traces: Map<ID, Trace>
trace_obligations: Map<ID, TraceObligation>
effects: Map<ID, Effect>
evidence: Map<ID, Evidence>
source_snapshots: Map<ID, Snapshot>
rule_observations: Map<ID, RuleObservation>
activities: Map<ID, Activity>
concepts: Map<ID, Concept>
information_uses: Map<ID, InformationUse>
ownerships: Map<ID, Ownership>
rules: Map<ID, Rule>
rule_relationships: Map<ID, RuleRelationship>
claims: Map<ID, Claim>
domains: Map<ID, Domain>
relationships: Map<ID, Relationship>
```

### GraphScope

```text
schema_version: 1
scope_id: ID
scope_kind: "whole_graph" | "slice" | "reconciliation"
partition_strategy: "none" | "application_boundary" | "entrypoint_bundle" | "execution_segment" | "reconciliation"
estimated_input_tokens: integer >= 0
parent_scope_id: ID | null
input_fingerprint: SHA-256
context: GraphContext
source_representation_ids: Array<ID>
canonical_anchor_ids: Array<ID>
child_scope_ids: Array<ID>
cross_scope_edge_ids: Array<ID>
```

Whole-graph scope uses `partition_strategy: none`, contains the complete validated fact collections, has null `parent_scope_id`, no child scopes and no omitted `record_refs`. A slice has a parent, no child scopes and uses `application_boundary`, `entrypoint_bundle` or `execution_segment`. Application-boundary and entrypoint-bundle slices contain complete trace/evidence closure for their canonical anchors. An oversized individual closure may use execution-segment slices cut only at typed trace edges; each segment carries the cut edges, applicable anchor identity, evidence and unresolved obligations, and the root reconciliation alone emits the authoritative final anchor disposition. A reconciliation scope uses `partition_strategy: reconciliation`, contains no raw source-representation or canonical-anchor IDs, and contains one or more validated child semantic scopes, cross-scope relationships, coverage manifests and the evidence required for its claims. Its parent is null only at the hierarchy root. `estimated_input_tokens` is calculated over the exact canonical wire serialization before dispatch. `record_refs` may preserve cross-scope identity but never substitutes for excerpts required to support a material claim.

### ScopeDisposition

```text
id: ID
subject_kind: "anchor" | "anchor_correspondence" | "child_scope"
subject_id: ID
status: "represented" | "excluded" | "unresolved"
activity_ids: Array<ID>
incorporated_record_ids: Array<ID>
reason: string | null
evidence_ids: Array<ID>
```

Every canonical anchor and every ambiguous/unresolved anchor-correspondence gap in a whole-graph/slice scope, and every child in a reconciliation scope, has exactly one disposition. An anchor disposition has empty `incorporated_record_ids`; a represented anchor has one or more `activity_ids`. An anchor-correspondence disposition is excluded or unresolved, has no activity/incorporated IDs and explains why no canonical entry point could be established. A child-scope disposition has empty `activity_ids`; a represented child has one or more `incorporated_record_ids` naming the child activities, domains or relationships included in the reconciliation candidate. Represented dispositions have null reason. Excluded and unresolved dispositions have no incorporated or activity IDs, require a nonempty subject-specific reason and cite at least one evidence record from that subject's supplied graph closure. A reason without evidence is incomplete. No published candidate contains a pending disposition.

### CandidatePayload

```text
scope_id: ID
input_fingerprint: SHA-256
activities: Map<ID, Activity>
rules: Map<ID, Rule>
concepts: Map<ID, Concept>
information_uses: Map<ID, InformationUse>
ownerships: Map<ID, Ownership>
rule_relationships: Map<ID, RuleRelationship>
claims: Map<ID, Claim>
domains: Map<ID, Domain>
relationships: Map<ID, Relationship>
dispositions: Array<ScopeDisposition>
```

The reusable artifact schema defines the generic `ID` grammar. The operation-specific provider schema narrows every provider-created record ID to its record-specific prefix using the shared normalization prefix map. This includes `activity:`, `rule:`, `concept:`, `information_use:`, `ownership:`, `rule_relationship:`, `claim:`, `domain:`, `relationship:` and `disposition:`.

Schema validity establishes payload shape, not semantic completeness. Before returning a candidate, synthesis MUST inspect every required subject, attempt synthesis from all supplied evidence and satisfy the normative completion gate in the synthesis-agent contract.

A whole-graph or slice candidate with zero activities is valid only when every canonical anchor is independently excluded with subject-specific evidence and no supplied evidence describes a business activity. A zero-activity candidate with any missing or unresolved anchor disposition is `VACUOUS_BUSINESS_MODEL` and MUST fail deterministic validation.

### ValidationFinding

```text
code: string
severity: "error" | "warning"
message: string
subject_ids: Array<ID>
evidence_ids: Array<ID>
```

### VerificationFinding

```text
id: ID
category: "missing_activity" | "invalid_activity" | "incorrect_merge" | "incorrect_split" | "unsupported_claim" | "unsupported_boundary" | "ignored_contradiction" | "missing_alternative" | "overstated_certainty" | "other"
severity: "blocking" | "warning"
message: string
subject_ids: Array<ID>
evidence_ids: Array<ID>
```

The provider-facing `VerificationFinding.id` pattern is `^verification_finding:[^ ]+$`. A nonmatching provider response enters the bounded schema-retry path.

### VerificationReport

```text
scope_id: ID
input_fingerprint: SHA-256
verdict: "pass" | "fail" | "uncertain"
findings: Array<VerificationFinding>
checked_subject_ids: Array<ID>
```

`pass` requires no blocking finding and complete checked-subject coverage. A material uncertainty produces `uncertain`, which is non-passing for publication. The verifier reports findings but cannot modify the candidate. Deterministic findings are a minimum required finding set, not the verifier's review boundary. The verifier independently checks global semantic completeness and reports every observable blocking defect in one report.

### SemanticRequest

```text
schema_version: 1
request_id: UUID
operation: "synthesize" | "verify" | "repair"
input_fingerprint: SHA-256
graph: GraphScope
candidate: CandidatePayload | null
parent_candidate_hash: SHA-256 | null
deterministic_findings: Array<ValidationFinding>
verification_report: VerificationReport | null
allowed_evidence_ids: Array<EvidenceID>
output_schema: JSON Schema object
model: nonempty string
max_output_tokens: positive integer
deadline_at: UTC date-time
```

Every field is present. Operation invariants are:

| Operation | `candidate` | `parent_candidate_hash` | `deterministic_findings` | `verification_report` | Raw model output |
| --- | --- | --- | --- | --- | --- |
| `synthesize` | null | null | empty | null | Complete `CandidatePayload` |
| `verify` | candidate under review | candidate hash | complete deterministic report, possibly empty | null | Complete `VerificationReport` |
| `repair` | rejected candidate | rejected candidate hash | complete deterministic report | failed/uncertain verifier report | Complete `RepairPayload` |

The request fingerprint covers the graph, operation-specific inputs, prompt/schema versions, provider/model selection and project instructions. `output_schema` is the trusted raw-model-output schema: `CandidatePayload` for synthesize, `VerificationReport` for verify and `RepairPayload` for repair. The model returns that payload only. The shared provider adapter supplies the response envelope fields.

### RepairPayload

```text
parent_candidate_hash: SHA-256
candidate: CandidatePayload
```

The hash must identify the exact rejected candidate. The model returns the complete replacement but no identity ledger. After canonical normalization, the orchestrator derives `revised` entries for same-ID body changes, `retired` entries for records absent from the replacement and `added` entries for new records. The derived ledger is exact, deterministic and stored in `SemanticResponse`. Old IDs remain historical lineage, not active aliases in the replacement.

### SemanticResponse

```text
schema_version: 1
request_id: UUID
operation: "synthesize" | "verify" | "repair"
input_fingerprint: SHA-256
candidate: CandidatePayload | null
verification_report: VerificationReport | null
identity_changes: Array<IdentityChange>
usage:
  input_tokens: integer >= 0 | null
  output_tokens: integer >= 0 | null
provider_revision: string | null
warnings: Array<Diagnostic>
```

Every field is present. `synthesize` requires a candidate, null verification report and an empty identity ledger. `repair` requires a candidate, null verification report and the orchestrator-derived repair ledger. `verify` requires a verification report, null candidate and an empty ledger. Response operation, request ID and input fingerprint must exactly match the request. The adapter creates `schema_version`, `request_id`, `operation`, `input_fingerprint`, `identity_changes`, `usage`, `provider_revision` and transport warnings around the validated raw payload; the model cannot supply or alter those fields.

### CacheArtifact

```text
one of:
  Request cache:
    schema_version: 1
    kind: "request"
    key: SHA-256
    created_at: UTC date-time
    request: SemanticRequest

  Response cache:
    schema_version: 1
    kind: "response"
    key: SHA-256
    created_at: UTC date-time
    request_key: SHA-256
    prompt_hash: SHA-256
    output_schema_hash: SHA-256
    provider_fingerprint: SHA-256
    validated_at: UTC date-time
    verification_response_key: SHA-256 | null
    response: SemanticResponse
```

Every listed field is required and both variants reject additional properties. A request key is the SHA-256 of the canonical request after removing exactly `request_id` and `deadline_at`; those values control one transport attempt and must not invalidate reusable semantic work. A response key is the SHA-256 of the canonical object containing exactly `request_key`, `prompt_hash`, `output_schema_hash` and `provider_fingerprint`. A synthesis or repair response has a nonnull `verification_response_key` naming the passing independent-verifier response for that exact candidate; a verifier response has null `verification_response_key`. A response cache entry is reusable only when its request exists, request/response operation, request ID and input fingerprint match, its provider and schema fingerprints still match, the required verification link resolves and passes, and its citations and references revalidate against the current graph scope.

### DigestDomainProjection

```text
domain_build_id: string (uuid) | null
domain_fingerprint: string | null
domain_status: StatusArtifact
domains: Array<Domain>
relationships: Array<Relationship>
```

The request operation must equal the response operation. Request/response IDs and fingerprints match. `allowed_evidence_ids` equals the permitted graph-scope evidence; response citations cannot exceed it. Validate `output_schema` as JSON Schema before dispatch and select it from trusted versioned schema assets; this standard-defined object is the deliberate exception to closed domain-record objects. The provider never supplies its own validation schema.
