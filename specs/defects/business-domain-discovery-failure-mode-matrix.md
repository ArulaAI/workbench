# Canonical-identity collision failure-mode matrix

## Scope and evidence rules

This matrix is the bounded executable failure partition for [canonical semantic identity collisions](business-domain-canonical-identity-collision.md). It replaces the prior 70-row inventory, which mixed historical observations, unexecuted risks, unrelated extraction defects, and proposed controls. Those entries remain in their dedicated defect records; they cannot support a 100% collision guarantee.

Every row below has:

1. a concrete value built with production `record()` and accepted by production `validate()` before the tested operation;
2. executed current failure evidence or an executed injected terminal failure;
3. a code-level root cause;
4. one fixing owner/function, reusing production paths;
5. an executed verification case; and
6. the business outcome.

“PASS” means the temporary replacement algorithm/runner satisfied the row. It does not mean production was changed. No retained/copy fixture or historical response was used, and no LLM, provider process, network request, or target application ran.

## Defect matrix

| ID | Contract-valid example | Executed failure evidence | Root cause | Fixing function | Verification | Business outcome |
| --- | --- | --- | --- | --- | --- | --- |
| C01 | Two `Activity` records differ only in temporary IDs. | Current `normalize_ids()` raised bare `INVALID_ID` (case 2). | Equal activity bases are rejected before rewritten-body comparison. | `_normalize_mapping()` | Case 16: one valid activity. | Duplicate output does not inflate activity/domain counts. |
| C02 | Two activities share `anchor:contract`; one has `effect:notify`. | Current code raised `INVALID_ID` although the grounded outcomes differ (case 6). | Activity basis is only `anchor_ids`. | `_identity_basis('activities', ...)` | Case 17: two injective IDs. | One endpoint can retain multiple evidenced business outcomes. |
| C03 | Same-anchor activities have identical traces/effects/rules but contradictory descriptions. | The generated multi-group specimen produced a collision group (case 44). | Prose alone cannot prove stable semantic identity. | `_collision_finding()` plus bounded repair | Case 44 reported the activity and domain groups together. | No arbitrary prose-based suffix or silent behavior choice. |
| C04 | Equal `Concept` records use `concept:left/right`; a second pair has the same name/types but a different symbol. | Current exact pair raised `INVALID_ID` (case 3). | Concept many-to-one results are globally rejected. | `_identity_basis()` + `_normalize_mapping()` | Cases 20-21: exact coalesced; unequal same basis rejected. | One terminology concept, with contradictory grounding reviewable. |
| C05 | Equal `Rule` records use two labels; a second pair shares the normative predicate tuple but differs in description. | Current exact pair raised `INVALID_ID` (case 4). | Rule identity allocation has no equivalence classification. | `_identity_basis()` + `_normalize_mapping()` | Cases 18-19. | Equal rules coalesce; non-equal rule meaning/metadata is not overwritten. |
| C06 | Equal `InformationUse` records identify one activity/concept/resource/access. | Current code retained two request-label-derived records (case 7). | Fallback basis contains `old`. | `_identity_basis('information_uses', ...)` | Cases 22-23. | Equivalent data use is stable across responses; contradictory resolution is repairable. |
| C07 | Equal `Ownership` records identify concept, nullable domain, kind, activities and uses. | Current code retained two label-derived records (case 8). | Fallback basis contains `old`. | `_identity_basis('ownerships', ...)` | Cases 24-25. | Ownership proposals cannot duplicate or silently disagree on rationale/support. |
| C08 | Equal `RuleRelationship` records identify two observations and `unresolved`; another differs in explanation. | Current code retained two label-derived records (case 9). | Fallback basis contains `old`. | `_identity_basis('rule_relationships', ...)` | Cases 26-27. | Observation relationships have stable identity and preserved contradictions. |
| C09 | Equal `Claim` records identify subject/kind/text/evidence/traces; another has different text. | Current code retained two label-derived records (case 10). | Fallback basis contains `old`. | `_identity_basis('claims', ...)` | Cases 28-29. | Equivalent claims do not multiply review work; distinct claims remain distinct. |
| C10 | Equal `Domain` records contain the same normalized primary membership; another pair differs in summary. | Current exact pair raised `INVALID_ID` (case 5). | Domain basis is calculated from unnormalized activity labels, then all many-to-one IDs are rejected. | dependency-ordered `_identity_basis('domains', ...)` | Cases 30-31 and 48. | Boundary identity follows stable membership; renames do not select identity. |
| C11 | Equal `Relationship` records identify the same normalized domain/activity endpoints, kind and trace; another differs in evidence. | Current code retained two label-derived records (case 11). | Fallback basis contains `old`. | `_identity_basis('relationships', ...)` | Cases 32-33. | Cross-domain interactions neither duplicate nor lose conflicting evidence. |
| C12 | Two dispositions for one scope subject are exact repeats; another pair says both `excluded` and `unresolved`. | Current exact pair raised `INVALID_ID` (case 12). | Disposition basis converges but global collision check cannot compare records. | `_normalize_sequence()` | Cases 34-35. | Exactly one disposition per subject; contradictions go to repair. |
| C13 | Verifier repeats one blocking finding with reversed subject/evidence order. | Current exact pair raised `INVALID_ID` (case 13). | Finding basis converges before set/order normalization. | `_canonicalize_sets()` + `_normalize_sequence()` | Cases 36-37. | One criticism appears once; set order cannot change review identity. |
| C14 | `activities` key is `activity:left` but enclosed ID is `activity:mismatch`. | Schema accepts both generic ID strings; current normalization does not explicitly prove equality. | Allocation trusts parallel key/value identity. | `_provider_records()` | Case 38: structured `INVALID_PROVIDER_OUTPUT`. | A record cannot be stored/referenced under two identities. |
| C15 | An activity carries `claim:left`, or a new record uses `_ref:1`. | The reusable generic ID grammar admits the wrong namespace; `_ref:` is a valid-looking string. | The operation-specific provider schema did not narrow record IDs by collection kind. | `wire_schema()` prefix specialization plus `_provider_records()` defense | Cases 39-40 retain structured `INVALID_ID`; the maintained prefix regression proves provider-boundary rejection and bounded retry. | Provider labels cannot masquerade as another record kind or supplied graph record. |
| C16 | One temporary string is reused by records in different collections. | Namespace-valid reuse is impossible because collections have distinct prefixes; generated invalid reuse was closed by the namespace check (case 41). | Flat alias ownership is otherwise last-write-wins. | `_provider_records()` global owner table | Case 41. | References cannot be redirected to the wrong semantic kind. |
| C17 | Two unequal canonical bases are forced to return `activity:forced` from the short allocator. | Forced short-hash collision executed (case 42). | A 24-hex digest is not an injectivity proof. | `_allocate_collision_safe_ids()` | Case 42 emitted two distinct full-canonical suffix IDs. | No unequal business identities share a storage key even under forced collision. |
| C18 | Rewriting dictionary keys `activity:a/b` through an alias map that maps both to `activity:x`. | Ordinary dict construction would retain only one value. | Current recursive comprehension has no duplicate-key guard. | `_rewrite()` | Case 43 raised `CANONICAL_KEY_COLLISION` before assignment. | No record/reference map entry can be silently overwritten. |
| C19 | One candidate contains a prose-only activity conflict and a same-membership domain conflict. | A fail-fast implementation would reveal only the first group. | Global cardinality test has no per-group classification. | `_normalize_mapping()` aggregation | Case 44 returned both findings in one semantic rejection. | One bounded repair receives the complete deterministic defect report. |
| C20 | All nine candidate collections reference other temporary semantic IDs, including activity→rule/concept/use/claim, domain→activity/ownership/claim, ownership→domain/use, and relationship endpoints. | Current output changes when all provider labels are renamed (case 49). | Domain and fallback bases use raw labels; rewriting is not dependency ordered. | `_identity_basis()` allocation order + `_rewrite()` | Cases 45 and 48: every old label absent and renamed input identical. | References remain closed and cache identity is independent of provider spelling. |
| C21 | Normalize an already normalized candidate, reverse all record-map insertion order, and reverse finding set order. | These transformations can expose order-sensitive allocation/comparison. | Raw container order and duplicate set entries are not canonical semantics. | `canonical()` + `_canonicalize_sets()` | Cases 37, 46-47. | Retries/cache hits are deterministic; normalization is idempotent. |
| C22 | `GraphScope(scope_kind='whole_graph', partition_strategy='none')` with a conflicting disposition pair. | Injected collision occurred before publication. | Collision behavior must not depend on scope selection. | proposed branch in production `Synthesis.run()` | Case 50: exact `synthesize→verify→repair→verify`. | A fitting repository self-heals once without losing complete graph scope. |
| C23 | `GraphScope(scope_kind='slice', parent_scope_id='scope:parent', partition_strategy='entrypoint_bundle')` with the same pair. | Injected slice collision. | A slice uses the same payload/identity contracts. | same normalization/runner owners | Case 51. | Validated hierarchical work has identical collision safety. |
| C24 | `GraphScope(scope_kind='reconciliation', child_scope_ids=['scope:child'])` with conflicting child dispositions. | Injected reconciliation collision. | Root/roll-up responses are canonical candidates too. | same normalization/runner owners | Case 52. | No child conflict can escape through root publication. |
| C25 | Exact duplicate dispositions in synthesis response. | Current runner stops after only `synthesize` with bare `INVALID_ID` and no cache (cases 14-15). | Normalization error occurs before `_validate_verify_repair()` and staging. | `Synthesis.run()` initial-findings branch | Case 53: duplicate coalesced, then only `synthesize→verify`. | Harmless repetition does not spend repair allowance. |
| C26 | Unequal disposition collision in synthesis; verifier returns fail; repair returns one excluded disposition; reverify passes. | Current runner never reaches verify (case 14). | No semantic repair context/entrance exists for initial normalization. | `Synthesis.run()` + `_validate_verify_repair(initial_findings=...)` | Cases 50-52 show all three scopes and exact four operations. | Contradictory candidate gets one bounded, independently checked correction. |
| C27 | Rerun the identical verified scope after successful normalization. | An unlinked or rejected candidate must not be reused. | Initial collision has no pending synthesis metadata; existing commit assumes it does. | `_commit_or_store_repaired_synthesis()` reusing cache owners | Cases 54-55: zero sequencer operations and non-null passing verifier link. | Unchanged refresh is free of semantic work and cannot reuse unverified output. |
| C28 | Repair returns the same unequal collision. | Injected repair collision (case 56). | Recursively repairing collisions would violate the one-repair bound. | existing `_run_with_retries()` terminal path | Cases 56-57: stop after repair; no candidate response cached. | Repeated contradiction fails safely and predictably. |
| C29 | Replacement normalizes, but reverify returns a blocking finding. | Injected non-pass reverify (case 58). | A shape-valid repair is not a verified repair. | existing `_validate_verify_repair()` final gate | Cases 58-59: `SEMANTIC_VERIFICATION_FAILED`; no candidate cache. | Unsupported repair cannot become repository truth. |
| C30 | Cancellation occurs on synthesis dispatch. | Injected `CANCELLED` (case 60). | Active work may stop before a candidate exists. | existing cancellation/error path | Cases 60-61: one attempted operation, zero cache files. | Cancellation leaves no reusable unverified state. |
| C31 | Deadline expires on synthesis dispatch. | Injected `BUILD_TIMEOUT` (case 62). | Time completion is independent of candidate validity. | existing deadline/error path | Cases 62-63: one attempted operation, zero cache files. | Timeout is visible and cannot publish a prefix. |
| C32 | Contract sequencer returns normalized provider-wide 403 denial. | Injected nonretryable `PROVIDER_UNAVAILABLE` (case 64). | Provider health is separate from semantic repair. | existing provider circuit/error path | Cases 64-65: one attempted operation, zero cache files. | Outage does not consume semantic repair or corrupt current domains. |
| C33 | A valid synthesis cache record is edited to remove its verifier link. | `_load_cached_response()` rejects the artifact; cache read is treated as miss. | Candidate reuse requires exact passing verifier linkage. | existing `_load_cached_response()` and `_store_response()` | Case 66: synthesis rebuilt; existing valid verifier reused. | Cache corruption cannot authorize an unverified candidate. |
| C34 | Generated OpenAPI source is extracted, collision repaired, accepted, source-checked, evidence-checked and atomically published through `discover()`. | A collision would previously terminate before acceptance/publication. | Runner integration was missing; publication controls already exist. | proposed runner integration + existing `discover()` | Cases 67-68: publication succeeded; unchanged refresh used zero sequencer operations. | Users receive one validated artifact through the existing refresh path. |
| C35 | Starting with a published artifact, changed inputs trigger repeated collision, non-pass reverify, cancellation, timeout, or provider failure. | Each terminal condition was injected through actual `discover()` (cases 69-73). | Failed attempts must never replace `old`. | existing `discover()` exception/status boundary | Cases 69-73 and 75: publication bytes identical. | Yesterday’s valid model remains readable after every semantic/operational failure. |
| C36 | Source is changed after passing reverify but before publication inventory check. | Actual `discover()` returned `SUPERSEDED` (case 74). | A valid candidate can still describe stale source. | existing source/snapshot recheck | Cases 74-75: phase `superseded`; prior bytes identical. | No stale candidate is advertised as current. |
| C37 | A verifier returns otherwise valid findings whose IDs pass the generic `ID` grammar but not the required `verification_finding:` prefix. | Production run `8243849c-c53f-4298-b0c5-63ed00c86c50` failed after verification with `INVALID_ID`. | The provider schema was broader than the normalization contract. | `wire_schema()` prefix specialization | `test_wire_schema_requires_provider_record_prefix` and `test_invalid_verification_finding_prefix_uses_schema_retry` | A malformed verifier label receives bounded schema retry instead of terminating the refresh. |

## Payload-stage coverage

| Stage | Production contract/function exercised | Cases |
| --- | --- | --- |
| construction | `record()`, `DEFINITIONS` | all |
| canonical validation | `validate(CandidatePayload|VerificationReport|GraphScope|SemanticRequest|SemanticResponse|CacheArtifact)` | all applicable |
| provider projection | `ProviderProjection`, `wire_schema()` exact local round-trip and provider-created ID-prefix constraints | 14-15, 50-75 and the maintained prefix regression |
| wire decode | `from_wire()` for candidate and verifier outputs | 14-15, 50-75 |
| normalization | current and replacement `normalize_ids()` | 1-49 |
| deterministic scope validation | `required_scope_subjects()`, `candidate_scope_findings()`, verifier envelope checks | 50-59 |
| verify/repair/reverify | production request builder, retry gate and response handling | 50-52, 56, 58 |
| cache | production request/response identity, atomic writes and verifier linkage | 54-57, 59, 66, 68 |
| extraction/publication | actual `Extractor.extract()` and `discover()` validation/source/evidence/atomic-write path | 67-75 |

## Exact command and complete output

The generic production ID schema was separately proved to admit the boundary specimens before normalization:

```sh
.venv/bin/python - <<'PY'
from lib.context.business_domain_schema import digest, record, validate
def activity(i):
    return record('Activity', id=i, anchor_ids=['anchor:x'],
                  implementation_status='implementation_unresolved', support='partial')
def claim(i):
    return record('Claim', id=i, subject_id='activity:x', semantic_review='uncertain')
def candidate():
    return record('CandidatePayload', scope_id='scope:x', input_fingerprint=digest('x'))
cases = {}
p = candidate(); p['activities'] = {'activity:key': activity('activity:body')}
validate(p, 'CandidatePayload'); cases['map_key_mismatch'] = 'ACCEPTED'
p = candidate(); p['activities'] = {'claim:wrong': activity('claim:wrong')}
validate(p, 'CandidatePayload'); cases['wrong_namespace'] = 'ACCEPTED'
p = candidate(); p['activities'] = {'_ref:1': activity('_ref:1')}
validate(p, 'CandidatePayload'); cases['supplied_alias'] = 'ACCEPTED'
p = candidate(); p['activities'] = {'activity:reuse': activity('activity:reuse')}
p['claims'] = {'activity:reuse': claim('activity:reuse')}
validate(p, 'CandidatePayload'); cases['cross_collection_reuse'] = 'ACCEPTED'
print('BOUNDARY_SCHEMA ' + ' '.join(f'{k}={v}' for k, v in cases.items()))
PY
```

```text
BOUNDARY_SCHEMA map_key_mismatch=ACCEPTED wrong_namespace=ACCEPTED supplied_alias=ACCEPTED cross_collection_reuse=ACCEPTED
```

```sh
shasum -a 256 .tmp_business_domain_collision_proof.py
.venv/bin/python .tmp_business_domain_collision_proof.py
```

```text
2df0c5169e3e34ebea9b6f0dbc9a47745dd7408e3a3099754057ae6924c6214b  .tmp_business_domain_collision_proof.py
CASE 01 current_bare_collision=PASS
CASE 02 current_exact_activities=PASS
CASE 03 current_exact_concepts=PASS
CASE 04 current_exact_rules=PASS
CASE 05 current_exact_domains=PASS
CASE 06 current_distinct_grounded_activities=PASS
CASE 07 current_noncanonical_information_uses=PASS
CASE 08 current_noncanonical_ownerships=PASS
CASE 09 current_noncanonical_rule_relationships=PASS
CASE 10 current_noncanonical_claims=PASS
CASE 11 current_noncanonical_relationships=PASS
CASE 12 current_exact_dispositions=PASS
CASE 13 current_exact_findings=PASS
CASE 14 current_runner_aborts_before_verify=PASS
CASE 15 current_runner_stages_no_cache=PASS
CASE 16 exact_activities=PASS
CASE 17 distinct_activities=PASS
CASE 18 exact_rules=PASS
CASE 19 distinct_rules=PASS
CASE 20 exact_concepts=PASS
CASE 21 distinct_concepts=PASS
CASE 22 exact_information_uses=PASS
CASE 23 distinct_information_uses=PASS
CASE 24 exact_ownerships=PASS
CASE 25 distinct_ownerships=PASS
CASE 26 exact_rule_relationships=PASS
CASE 27 distinct_rule_relationships=PASS
CASE 28 exact_claims=PASS
CASE 29 distinct_claims=PASS
CASE 30 exact_domains=PASS
CASE 31 distinct_domains=PASS
CASE 32 exact_relationships=PASS
CASE 33 distinct_relationships=PASS
CASE 34 exact_dispositions=PASS
CASE 35 distinct_dispositions=PASS
CASE 36 exact_findings=PASS
CASE 37 finding_set_order=PASS
CASE 38 map_key_record_id=PASS
CASE 39 namespace_kind=PASS
CASE 40 supplied_alias_rejected=PASS
CASE 41 cross_collection_reuse=PASS
CASE 42 forced_short_hash_collision=PASS
CASE 43 rewritten_map_key_collision=PASS
CASE 44 all_collision_groups_reported=PASS
CASE 45 all_collection_reference_rewrite=PASS
CASE 46 normalization_idempotent=PASS
CASE 47 map_order_invariant=PASS
CASE 48 temporary_label_invariant=PASS
CASE 49 current_temporary_label_variant=PASS
CASE 50 scope_whole_graph=PASS
CASE 51 scope_slice=PASS
CASE 52 scope_reconciliation=PASS
CASE 53 exact_duplicate_no_repair=PASS
CASE 54 verified_cache_hit=PASS
CASE 55 cache_verifier_link=PASS
CASE 56 repeat_collision=PASS
CASE 57 repeat_collision_not_candidate_cached=PASS
CASE 58 reverify_fail=PASS
CASE 59 reverify_fail_not_candidate_cached=PASS
CASE 60 cancelled_runner=PASS
CASE 61 cancelled_no_cache=PASS
CASE 62 timeout_runner=PASS
CASE 63 timeout_no_cache=PASS
CASE 64 provider_failure_runner=PASS
CASE 65 provider_failure_no_cache=PASS
CASE 66 invalid_cache_rebuilt=PASS
CASE 67 publication_success=PASS
CASE 68 publication_cache_hit=PASS
CASE 69 publication_preserves_repeat_collision=PASS
CASE 70 publication_preserves_reverify_fail=PASS
CASE 71 publication_preserves_cancelled=PASS
CASE 72 publication_preserves_timeout=PASS
CASE 73 publication_preserves_provider_failure=PASS
CASE 74 publication_preserves_superseded=PASS
CASE 75 publication_all_failure_bytes=PASS
PRODUCTION_FAILURE code=INVALID_ID findings=0 rejected_candidate=false repair_kind=null
CURRENT_EXACT_COLLISIONS activities=INVALID_ID concepts=INVALID_ID rules=INVALID_ID domains=INVALID_ID
COLLECTIONS exact=9/9 distinct_safe=9/9 sequences=4/4
GRAPH_SCOPES whole_graph=PASS slice=PASS reconciliation=PASS
PIPELINE synthesize>verify>repair>verify=PASS cache_hit=PASS verifier_link=PASS
FAILURES repeated_collision=PASS reverify_fail=PASS cancelled=PASS timeout=PASS provider=PASS candidate_cache_poison=0
PUBLICATION success=PASS cache_hit=PASS collision=preserved reverify=preserved cancelled=preserved timeout=preserved provider=preserved superseded=preserved
PROVIDER_CALLS external=0 model=0 network=0
CONTRACT_OBLIGATIONS passed=75 total=75 score=100.000%
```

The output above is retained as historical evidence. Its defined denominator did not include provider-schema and normalization-prefix agreement.

## Coverage limitation discovered in production

The earlier 75/75 result did not cover agreement between provider-schema ID patterns and normalization-prefix validation. Production run `8243849c-c53f-4298-b0c5-63ed00c86c50` disproved the earlier completeness claim. The maintained prefix and retry regressions now pass, but the removed harness has not been rerun with an amended denominator; no updated harness total is claimed.
