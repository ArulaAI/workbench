# Business-domain refresh can reject valid discovery results

## Context

`speed digest --refresh` analyzes repository source and publishes a repository digest that explains the software in business terms. Its business-domain output identifies what business outcomes the software supports, the rules and information involved, and how those responsibilities group into domains.

A **business activity** is a provider-proposed, evidence-backed business outcome, such as “cancel an order.” It is not an extracted function, endpoint or activity list. It is an interpretation of deterministic repository evidence.

The provider creates semantic records that do not exist in the extracted graph. Each new record needs an ID so other records in the same JSON response can refer to it.

**Provenance — generic provider candidate:** This contract example is not a retained provider response.

| Candidate location | Field | Value | Purpose |
| --- | --- | --- | --- |
| Proposed activity record | `id` | `activity:a` | Identifies the proposed activity within this response |
| Proposed domain membership | `activity_id` | `activity:a` | Connects the proposed domain to that activity |

`activity:a` is a **response-local ID**. It identifies the activity record only within this candidate. It is not the activity’s stable SPEED identity, and another equivalent response may call the same proposed activity `activity:x`. SPEED owns the conversion from response-local IDs to local canonical IDs.

The production pipeline has four relevant stages:

| Stage | Production output |
| --- | --- |
| Deterministic extraction | A validated facts graph containing source entry points, implementation traces, inputs, outputs, effects, rule observations and source excerpts. An entry point is stored as an **anchor**. Extraction does not assign business activities or domains. |
| Semantic synthesis | The configured provider interprets the facts graph and returns a `CandidatePayload` containing proposed activities, rules, concepts, information uses, ownerships, claims, domains, relationships and a disposition for every required graph subject. |
| Local normalization and verification | SPEED replaces response-local IDs with local canonical IDs, updates references to those records, validates references and evidence, independently verifies the candidate and, when permitted, runs one repair and reverification cycle. |
| Publication | SPEED incorporates the verified candidate into a `DomainArtifact`, reconciles persistent identities, validates the complete artifact and publishes it atomically. |

Production performs candidate normalization in `normalize_ids()` after provider-wire decoding and `CandidatePayload` schema validation, but before deterministic candidate validation, independent verification, candidate-cache commit or publication.

### Minimal example

**Provenance — hypothetical extracted evidence:** Assume deterministic extraction finds one HTTP anchor, `anchor:cancel-order`, and two source-backed implementation paths:

```text
anchor:cancel-order
  trace:update-order      → effect:update-order
  trace:notify-customer   → effect:notify-customer
```

These are graph facts, not extracted business activities.

**Provenance — provider candidate:** The following hypothetical payload interprets those facts; it is not a retained provider response:

| Business record | Response-local ID | Grounding or membership |
| --- | --- | --- |
| Update the stored order status | `activity:a` | `anchor:cancel-order`, `trace:update-order` and `effect:update-order` |
| Notify the customer | `activity:b` | `anchor:cancel-order`, `trace:notify-customer` and `effect:notify-customer` |
| Orders domain | `domain:orders` | `activity:a` primary; `activity:b` supporting |

**Provenance — synthetic test input:** The same payload was copied with only its response-local activity IDs and their references relabeled: `activity:a` became `activity:x`, and `activity:b` became `activity:y`. Both versions were constructed with production record factories and passed the production provider-output schema, alias restoration, response decoding and `CandidatePayload` validation. No provider was called.

The historical failing provider payload is unavailable, so neither version claims to reproduce production history.

### Current behavior

Production generates an activity ID from only its sorted anchor IDs:

```text
identity(activity:a) = hash([anchor:cancel-order])
identity(activity:b) = hash([anchor:cancel-order])
```

It therefore assigns both proposed activities the same generated ID, despite their different trace and effect references. The global duplicate-ID check raises `INVALID_ID` before references are rewritten or the candidate reaches deterministic and independent verification.

Relabeling the same payload exposes a second failure without introducing a different business example. The IDs `activity:x` and `activity:y` serve the same response-local purpose as `activity:a` and `activity:b`; only their spelling differs.

Current production derives all four activity calculations from the same sorted list, `[anchor:cancel-order]`. Corresponding activities in the original and relabeled payloads therefore get the same calculated IDs, but the two distinct activities within each payload also collide as described above.

Current production calculates the domain IDs from different, unnormalized membership values:

```text
identity(domain using activity:a/activity:b) = hash([(activity:a, primary), (activity:b, supporting)])
identity(domain using activity:x/activity:y) = hash([(activity:x, primary), (activity:y, supporting)])
```

The domain calculations differ even though both payloads describe the same membership. Rewriting `activity:a` to the same local activity ID as `activity:x`, and `activity:b` to the same local activity ID as `activity:y`, happens only after the domain IDs have been calculated.

**Provenance — normalized payload:** None exists for either synthetic input under current production. Both executed inputs were constructed with production record factories and passed the production provider-output schema, alias restoration, response decoding and `CandidatePayload` validation. `normalize_ids()` then raised `INVALID_ID` for each input. This first failure masks the differing domain calculations; fixing activity identity alone would leave the domain failure.

**Provenance — published artifact:** Neither synthetic input was published. Current production does not send this normalization failure through verification or repair, does not commit it to the candidate cache and does not publish it. An initial failed refresh has no business-domain artifact; a later failed refresh preserves the previous valid artifact.

### Required behavior

Normalization must process the same example in dependency order:

1. Assign stable IDs to any concepts and rules before activities that reference them.
2. For this example, use the shared anchor and the distinct source-backed traces and effects to assign one stable ID to the update activity and another to the notification activity. The `activity:a` and `activity:x` versions of the update activity must receive the same ID; the `activity:b` and `activity:y` versions of the notification activity must receive the same ID. Bindings and normalized concept or rule references must also participate when present.
3. Rewrite the domain membership in both versions of the payload to those local activity IDs.
4. Calculate domain identity from the rewritten `(activity ID, role)` memberships. Both versions of the payload must then receive the same domain ID.
5. Compare complete normalized record bodies before deciding whether records are duplicates or conflicts.

**Provenance — normalized payload:** The required result below is proposed behavior, not current production output.

| Business record | Original response-local IDs | Same payload with relabeled IDs | Required local result |
| --- | --- | --- | --- |
| Update the stored order status | `activity:a` | `activity:x` | The same update-activity ID |
| Notify the customer | `activity:b` | `activity:y` | The same notification-activity ID, distinct from the update activity |
| Orders domain | Memberships using `activity:a` and `activity:b` | Memberships using `activity:x` and `activity:y` | The same domain ID from the same rewritten memberships |

Exactly equal normalized records may coalesce, with every reference redirected to the retained record. Unequal records must never overwrite one another. An unequal same-identity group must produce a structured semantic finding for the existing bounded verification, repair and reverification cycle.

After normalization, deterministic candidate validation and independent verification must receive the same candidate for either set of response-local IDs. A passing candidate may enter the candidate cache only with its passing verification link and may then continue through the existing atomic publication path. A repaired candidate must be normalized, validated and independently reverified before caching or publication. If verification or repair does not produce a passing candidate, publication must preserve any existing valid artifact.

## Impact

- A schema-valid provider response can fail before independent verification.
- Harmless duplicate records can abort a refresh.
- Distinct business behavior on one entry point can be assigned one generated identity and rejected.
- Equivalent provider responses can receive different IDs because five record types include the temporary provider label in their identity basis.
- An initial refresh publishes no business-domain artifact. A failed later refresh preserves the previous valid artifact.

## Status and proof scope

| Item | State |
| --- | --- |
| Production defect | Verified in the baseline implementation |
| Production remediation | Implemented in the current worktree; release gates remain open |
| Proposed remediation | Installed in the existing provider-schema, normalization, repair and cache owners |
| Earlier harness result | 75 of 75 previously defined obligations passed; provider-prefix enforcement was omitted |
| Matrix result | 37 rows; the new provider-prefix regressions pass, while the historical harness remains 36 of 36 |
| Retained implementation or test | Production implementation and focused maintained regressions are present; the temporary harness remains removed |
| Current targeted suite | 144 passed across candidate protocol and contract alignment |
| Historical payload | Unavailable and not reproduced |
| Harness inputs | Generated with production `record()` and accepted by production `validate()` |
| Harness external calls | Zero model, provider process and network calls |

The bounded guarantee is:

> For every value admitted by the operation-specific provider schema, canonicalization either (a) returns one schema-valid, reference-rewritten, provider-label-invariant payload without overwriting a record, (b) coalesces only records whose complete bodies are equal after all ID rewriting and set canonicalization or (c) raises one structured semantic rejection containing every unequal same-identity group and the exact process-local rejected candidate. A rejected or unsuccessfully repaired value is never candidate-cached or published.

The guarantee covers the finite contract branches and collision-equivalence classes defined in this document and the companion [failure-mode matrix](business-domain-discovery-failure-mode-matrix.md). It does not claim that provider semantics are correct, SHA-256 cannot collide, the historical response was reconstructed or production was fixed.

## Verified production defect

The defect is between schema validation and canonical reference validation:

```text
Provider response
  → wire-schema validation
  → provider-alias restoration
  → CandidatePayload or VerificationReport validation
  → normalize_ids()                                      DEFECT
  → reference, scope and citation validation
  → SemanticResponse staging
  → verifier-linked cache commit
  → candidate acceptance
  → source recheck
  → atomic publication
```

`normalize_ids()` in `lib/context/business_domain_synthesis.py` builds one flat `old ID → generated ID` dictionary.

| Collection | Current identity basis |
| --- | --- |
| `activities` | Sorted `anchor_ids` only |
| `domains` | Memberships containing unnormalized provider activity IDs |
| `concepts` | Graph anchors, qualified type names and name |
| `rules` | Graph anchors, observations, predicate or formula, scope, evaluation kind, preconditions and outcome |
| Five other candidate maps | Input fingerprint, graph anchors and the temporary provider ID |
| Dispositions and findings | Separate selected-field bases |

Production rejects every many-to-one result before reference rewriting or record comparison:

```python
if len(set(replacements.values())) != len(replacements):
    raise DomainError(
        'INVALID_ID',
        'Distinct proposals have the same canonical identity')
```

Executed production output:

```text
PRODUCTION_FAILURE code=INVALID_ID findings=0 rejected_candidate=false repair_kind=null
CURRENT_EXACT_COLLISIONS activities=INVALID_ID concepts=INVALID_ID rules=INVALID_ID domains=INVALID_ID
```

Proof cases 14 and 15 executed the current runner. It called only `synthesize`, wrote no cache artifact and never reached verification. `_run_once()` normalizes after provider-wire decoding and schema validation but does not stage the response until normalization and contract checks pass. `_run_with_retries()` rethrows this non-schema, non-provider error. `Synthesis.run()` therefore never enters `_validate_verify_repair()`.

A later production refresh exposed an omitted provider-boundary case. Run `8243849c-c53f-4298-b0c5-63ed00c86c50` received a verification report containing two findings and 55 checked subjects. The generic provider ID pattern accepted the report, but normalization rejected at least one finding because its ID did not start with `verification_finding:`. The raw finding IDs were not retained, so their exact spelling is unknown.

## Root causes

| ID | Root cause | Consequence |
| --- | --- | --- |
| R1 | Activity identity uses only canonical anchors, although the contract permits several activities for one connected behavior | Distinct grounded outcomes on one anchor receive the same ID |
| R2 | `information_uses`, `ownerships`, `rule_relationships`, `claims` and `relationships` include the temporary provider ID in their basis | Equivalent responses normalize differently when only temporary labels change |
| R3 | One flat alias map does not first validate map-key/record-ID agreement, collection namespace or unique ownership | A temporary label can be ambiguous or overwrite another alias assignment |
| R4 | Production checks generated-ID cardinality before rewriting references and comparing canonical record bodies | It cannot distinguish exact duplicates from conflicting records |
| R5 | Initial normalization errors contain no findings, rejected candidate or repair kind | The existing verify → repair → reverify owner cannot process the failure |

Generated names and descriptions must not distinguish activity identity. They are provider-authored prose, not grounded implementation evidence. Two activities on one anchor are distinct only when traces, bindings, effects, concepts or rules distinguish them. A prose-only difference must enter repair or fail closed.

## Required solution

This is a replacement of the current flat normalization algorithm, not merely a reordering of its loop. Production must change the identity inputs, dependency ordering, reference rewriting, collision classification and repair entry together.

Keep these responsibilities in `business_domain_synthesis.py`. Reuse the existing schema, repair, cache and publication owners. Move reusable semantic-basis policy to the existing identity owner only if another caller requires it.

### 1. Validate provider-created IDs

Each new semantic record has a response-local ID so other records in the same response can refer to it. Before replacing those IDs with local canonical IDs, normalization must verify that every provider-created record has one unique ID with the prefix for its record type.

For example:

- An activity ID must start with `activity:`.
- A domain ID must start with `domain:`.
- A claim ID must start with `claim:`.
- A provider-created record must not use `_ref:` because that prefix identifies an existing record supplied in the graph.
- One response-local ID must not identify more than one new record in the same response. References may reuse the ID because they point to that record.

`from_wire()` remains responsible for rejecting repeated IDs within one provider record array and constructing the decoded ID-keyed maps. `validate_references()` remains responsible for validating canonical map keys and references. `_provider_records()` adds only the response-local ownership checks required before canonical allocation.

The prefix map is the single authoritative policy for provider-created and canonical semantic record IDs. `wire_schema()` must derive type-specific provider `id` patterns from this map. `_provider_records()` retains the same check as a defensive invariant after provider-schema validation.

| Collection | Required response-local prefix |
| --- | --- |
| `activities` | `activity:` |
| `rules` | `rule:` |
| `concepts` | `concept:` |
| `information_uses` | `information_use:` |
| `ownerships` | `ownership:` |
| `rule_relationships` | `rule_relationship:` |
| `claims` | `claim:` |
| `domains` | `domain:` |
| `relationships` | `relationship:` |
| `dispositions` | `disposition:` |
| `findings` | `verification_finding:` |

`_provider_records(payload)` must return one dictionary whose keys are the applicable collection names and whose values are ordered `(temporary_id, record)` pairs. Map entries are ordered by key; sequence entries preserve their contract order. It must maintain one global `temporary_id → collection` owner table while building that result.

Error ownership is exact:

| Condition | Boundary | Code | `repair_kind` |
| --- | --- | --- | --- |
| Repeated ID in one provider array | Provider-wire decoding | `INVALID_PROVIDER_OUTPUT` | `schema` |
| Decoded map key differs from the enclosed record ID | Normalization invariant | `INVALID_PROVIDER_OUTPUT` | `schema` |
| Wrong collection prefix or `_ref:` use | Provider-schema validation | `INVALID_PROVIDER_OUTPUT` | `schema` |
| Wrong prefix after bypassing provider-schema validation | Defensive normalization invariant | `INVALID_ID` | `semantic` |
| One response-local ID is owned by multiple records | Normalization ownership validation | `INVALID_ID` | `semantic` |

The operation-specific provider schema is the normal owner of prefix validation. A wrong prefix therefore enters the existing bounded schema-retry path before decoding and normalization. `_provider_records()` retains its existing check only as defense in depth for an internal caller that bypasses the provider boundary. Cross-record ownership and canonical identity collisions remain semantic errors handled by Section 4. `DomainError.record()` must continue to omit every rejected payload.

### 2. Allocate each ID after the IDs it depends on

A local canonical ID must not be calculated from a response-local reference. `_identity_basis(collection, item, graph, aliases)` and `_allocate_collision_safe_ids()` may allocate a record as soon as every provider-created record named in its identity basis has a local canonical ID. Records in the same dependency group do not depend on one another.

**Provenance — proposed orchestration sketch:** The following replaces the flat loop and global cardinality check in the current `normalize_ids()`. `_provider_records()` reads the map and sequence collections declared by the existing candidate and verification contracts; it does not define another schema.

```python
DEPENDENCY_GROUPS = (
    ('concepts', 'rules', 'rule_relationships', 'dispositions'),
    ('activities',),
    ('domains', 'information_uses'),
    ('relationships', 'ownerships'),
    ('claims', 'findings'),
)


def normalize_ids(payload, graph):
    """Replace response-local IDs without depending on their spelling."""
    records = _provider_records(payload)
    aliases = {}

    for collections in DEPENDENCY_GROUPS:
        _allocate_collision_safe_ids(
            records, collections, graph, aliases)

    output_type = (
        'VerificationReport'
        if 'verdict' in payload
        else 'CandidatePayload'
    )
    return _normalize_payload(payload, aliases, output_type)
```

The two identity branches used by the cancel-order example are:

```python
def _identity_basis(collection, item, graph, aliases):
    def resolved(ident):
        return aliases.get(ident, ident)

    if collection == 'activities':
        return {
            'anchor_ids': sorted(item['anchor_ids']),
            'trace_ids': sorted(item['trace_ids']),
            'input_binding_ids': sorted(item['input_binding_ids']),
            'output_binding_ids': sorted(item['output_binding_ids']),
            'effect_ids': sorted(item['effect_ids']),
            'concept_ids': sorted(map(resolved, item['concept_ids'])),
            'rule_ids': sorted(map(resolved, item['rule_ids'])),
        }

    if collection == 'domains':
        return sorted(
            (resolved(member['activity_id']), member['role'])
            for member in item['activity_memberships']
        )
```

The dependency table below is authoritative for the remaining identity branches. Provider-authored names and descriptions and response-local IDs must not enter an activity identity basis.

| Dependency group | Record | Local canonical IDs required first | Other identity inputs |
| --- | --- | --- | --- |
| 1 | Concepts | None | Graph anchors, sorted qualified types and terminology name |
| 1 | Rules | None | Graph anchors, observations, predicate or formula, scope, evaluation kind, preconditions and outcome |
| 1 | Rule relationships | None | Graph observation endpoints and relationship kind |
| 1 | Dispositions | None | Graph scope, subject kind and subject ID |
| 2 | Activities | Referenced concepts and rules | Anchors, traces, input and output bindings and effects |
| 3 | Domains | Member activities | Membership roles |
| 3 | Information uses | Referenced activity and concept | Resources, access, bindings, effects and traces |
| 4 | Domain relationships | Endpoint domains and activities | Relationship kind and traces |
| 4 | Ownerships | Referenced concept, domain, activities and information uses | Ownership kind |
| 5 | Claims | Provider-created subject, when applicable | Claim kind, text, evidence and traces |
| 5 | Verification findings | Subjects in the already normalized candidate | Graph scope, category, severity, message and evidence |

This order applies only to identity calculation. Section 3 rewrites other references in the complete record bodies after all required IDs have been allocated.

The activity basis permits distinct outcomes on one anchor when grounded implementation evidence distinguishes them. A difference confined to mutable prose remains a repairable collision.

`_allocate_collision_safe_ids()` must group proposed IDs by both the shortened ID and the full canonical identity-basis bytes. Equal basis bytes retain one shortened ID. If one shortened ID contains more than one distinct basis, each distinct basis receives this deterministic fallback:

```python
basis_bytes = canonical(identity_basis)
fallback_id = (
    f'{short_id}:'
    f'{digest(basis_bytes)}'
)
```

All temporary IDs with equal basis bytes receive the same fallback. Sorting the basis bytes before allocation makes the result independent of record insertion order. A fallback cannot equal a normal shortened ID because it contains the additional full-digest component. The bounded guarantee excludes a collision in the full SHA-256 digest.

### 3. Rewrite references before classifying collisions

Section 2 produces `aliases`, one complete `response-local ID → local canonical ID` map. Section 3 must use that map to rewrite each record before deciding whether two records are equal. It must never rewrite an entire ID-keyed collection with a dictionary comprehension because two keys could resolve to the same key and silently overwrite a record.

**Provenance — proposed implementation sketch:** The following Python is required behavior expressed as code. It is not current production code and was not executed as a production implementation.

```python
def _rewrite(value, aliases, rejected_candidate):
    """Replace exact ID values and keys without losing a dictionary entry."""
    if isinstance(value, str):
        return aliases.get(value, value)

    if isinstance(value, list):
        return [
            _rewrite(item, aliases, rejected_candidate)
            for item in value
        ]

    if not isinstance(value, dict):
        return value

    rewritten = {}
    original_key = {}
    for old_key in sorted(value):
        new_key = aliases.get(old_key, old_key)
        if new_key in rewritten:
            subjects = [
                key for key in (original_key[new_key], old_key, new_key)
                if ':' in key
            ]
            finding = validation_finding(
                'CANONICAL_KEY_COLLISION',
                'Two dictionary keys resolve to the same canonical ID',
                subject_ids=subjects,
            )
            raise DomainError(
                finding['code'], finding['message'],
                findings=[finding],
                rejected_candidate=copy.deepcopy(rejected_candidate),
                repair_kind='semantic',
            )
        original_key[new_key] = old_key
        rewritten[new_key] = _rewrite(
            value[old_key], aliases, rejected_candidate)
    return rewritten


def _canonicalize_sets(value, set_paths, path=()):
    """Canonicalize only arrays the contract declares unordered."""
    if isinstance(value, dict):
        return {
            key: _canonicalize_sets(child, set_paths, path + (key,))
            for key, child in value.items()
        }

    if not isinstance(value, list):
        return value

    items = [
        _canonicalize_sets(child, set_paths, path + ('[]',))
        for child in value
    ]
    if path not in set_paths:
        return items  # Preserve the order of contract-defined sequences.

    by_value = {}
    for item in items:
        by_value.setdefault(canonical(item), item)
    return [by_value[key] for key in sorted(by_value)]


def _evidence_ids(value):
    """Collect only evidence IDs already present in the rejected records."""
    found = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key == 'evidence_ids' and isinstance(child, list):
                found.update(child)
            else:
                found.update(_evidence_ids(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_evidence_ids(child))
    return found


def _collision_finding(collection, canonical_id, entries):
    temporary_ids = [temporary_id for temporary_id, _ in entries]
    evidence_ids = {
        evidence_id
        for _, record in entries
        for evidence_id in _evidence_ids(record)
    }
    return validation_finding(
        'CANONICAL_ID_COLLISION',
        f'Unequal {collection} records resolve to one canonical ID',
        subject_ids=[canonical_id, *temporary_ids],
        evidence_ids=evidence_ids,
    )


def _normalize_records(collection, entries, aliases, set_paths, payload):
    """Return nonconflicting records in first-occurrence order."""
    groups = {}
    group_order = []
    for temporary_id, record in entries:
        canonical_id = aliases[temporary_id]
        body = _rewrite(record, aliases, payload)
        body = _canonicalize_sets(body, set_paths)
        if canonical_id not in groups:
            groups[canonical_id] = []
            group_order.append(canonical_id)
        groups[canonical_id].append((temporary_id, body))

    normalized = []
    findings = []
    for canonical_id in group_order:
        group = groups[canonical_id]
        distinct_bodies = {}
        for _, body in group:
            distinct_bodies.setdefault(canonical(body), body)
        if len(distinct_bodies) == 1:
            normalized.append(next(iter(distinct_bodies.values())))
        else:
            findings.append(
                _collision_finding(collection, canonical_id, group))
    return normalized, findings


def _normalize_mapping(collection, records, aliases, set_paths, payload):
    normalized, findings = _normalize_records(
        collection, sorted(records.items()), aliases, set_paths, payload)
    return {record['id']: record for record in normalized}, findings


def _normalize_sequence(collection, records, aliases, set_paths, payload):
    entries = [(record['id'], record) for record in records]
    return _normalize_records(
        collection, entries, aliases, set_paths, payload)
```

`set_paths` is authoritative contract data for the record type being normalized. The implementation must not guess that an array is a set because its field name ends in `_ids`. A path absent from `set_paths` remains in its original order; this preserves ordered values such as trace traversal edges.

The caller must run both collection helpers for every applicable map and sequence, collect all returned findings and reject once after every group has been inspected:

```python
def _normalize_payload(payload, aliases, output_type):
    normalized = copy.deepcopy(payload)
    findings = []

    for collection, record_type in MAPPING_RECORD_TYPES.items():
        if collection not in payload:
            continue
        normalized[collection], collection_findings = _normalize_mapping(
            collection,
            payload[collection],
            aliases,
            SET_PATHS_BY_TYPE[record_type],
            payload,
        )
        findings.extend(collection_findings)

    for collection, record_type in SEQUENCE_RECORD_TYPES.items():
        if collection not in payload:
            continue
        normalized[collection], collection_findings = _normalize_sequence(
            collection,
            payload[collection],
            aliases,
            SET_PATHS_BY_TYPE[record_type],
            payload,
        )
        findings.extend(collection_findings)

    if findings:
        raise DomainError(
            findings[0]['code'],
            findings[0]['message'],
            findings=findings,
            rejected_candidate=copy.deepcopy(payload),
            repair_kind='semantic',
        )

    validate(normalized, output_type)
    return normalized
```

`MAPPING_RECORD_TYPES`, `SEQUENCE_RECORD_TYPES` and `SET_PATHS_BY_TYPE` must come from the canonical candidate and verification contracts rather than form a second schema. The flow above produces one of two results for every group that resolves to one local canonical ID:

| Canonical bodies in the group | Result |
| --- | --- |
| One distinct body | Emit it once |
| More than one distinct body | Emit no group member and add one `CANONICAL_ID_COLLISION` finding |

#### Example: Follow the cancel-order payload through every helper

This continues the cancel-order example from Context. It introduces no new activities, traces, effects, memberships or evidence.

**Provenance — synthetic test input:** `payload` below denotes the schema-validated synthetic input described in Context. These are the fields used by this walkthrough; its other schema-required fields remain unchanged. The same payload with relabeled IDs substitutes `activity:x` for `activity:a` and `activity:y` for `activity:b` everywhere.

```python
payload['activities'] = {
    'activity:a': record(
        'Activity',
        id='activity:a',
        name='Update the stored order status',
        anchor_ids=['anchor:cancel-order'],
        trace_ids=['trace:update-order'],
        effect_ids=['effect:update-order'],
    ),
    'activity:b': record(
        'Activity',
        id='activity:b',
        name='Notify the customer',
        anchor_ids=['anchor:cancel-order'],
        trace_ids=['trace:notify-customer'],
        effect_ids=['effect:notify-customer'],
    ),
}
payload['domains'] = {
    'domain:orders': record(
        'Domain',
        id='domain:orders',
        name='Orders',
        activity_memberships=[
            record('ActivityMembership',
                   activity_id='activity:a', role='primary'),
            record('ActivityMembership',
                   activity_id='activity:b', role='supporting'),
        ],
    ),
}
payload['dispositions'] = [
    record(
        'ScopeDisposition',
        id='disposition:cancel-order',
        subject_kind='anchor',
        subject_id='anchor:cancel-order',
        status='represented',
        activity_ids=['activity:a', 'activity:b'],
    ),
]
```

**Provenance — normalized payload:** The local canonical IDs below are descriptive placeholders for the required result, not recorded production output. Current production still raises `INVALID_ID` before producing this payload.

The two activity calculations now differ on grounded implementation evidence even though their anchor is shared:

```text
activity:a basis = anchor:cancel-order
                   trace:update-order
                   effect:update-order

activity:b basis = anchor:cancel-order
                   trace:notify-customer
                   effect:notify-customer
```

Relabeling `activity:a` as `activity:x` or `activity:b` as `activity:y` does not change either basis. Section 2 therefore supplies a separate alias map for each spelling of the input, but both maps have the same canonical values:

```python
aliases_for_original_ids = {
    'activity:a': 'activity:<update>',
    'activity:b': 'activity:<notify>',
    'domain:orders': 'domain:<orders>',
    'disposition:cancel-order': 'disposition:<cancel-order>',
}

# For the same payload with relabeled response-local activity IDs:
aliases_for_relabeled_ids = {
    'activity:x': 'activity:<update>',
    'activity:y': 'activity:<notify>',
    'domain:orders': 'domain:<orders>',
    'disposition:cancel-order': 'disposition:<cancel-order>',
}

# First run; use aliases_for_relabeled_ids with the relabeled payload.
aliases = aliases_for_original_ids
```

The successful call flow is:

```text
_normalize_payload(payload, aliases, 'CandidatePayload')
├── _normalize_mapping('activities', payload['activities'], ...)
│   └── _normalize_records(...)
│       ├── _rewrite(activity, aliases, payload)
│       └── _canonicalize_sets(rewritten_activity, activity_set_paths)
├── _normalize_mapping('domains', payload['domains'], ...)
│   └── _normalize_records(...)
│       ├── _rewrite(domain, aliases, payload)
│       └── _canonicalize_sets(rewritten_domain, domain_set_paths)
└── _normalize_sequence('dispositions', payload['dispositions'], ...)
    └── _normalize_records(...)
        ├── _rewrite(disposition, aliases, payload)
        └── _canonicalize_sets(rewritten_disposition,
                               disposition_set_paths)
```

Each function receives and returns the following values in that flow:

| Function | Concrete input from the example | Result passed to its caller |
| --- | --- | --- |
| `_normalize_payload()` | `payload`, either alias map above and `'CandidatePayload'` | One validated payload containing normalized activities, domain and disposition |
| `_normalize_mapping()` | `'domains'`, `payload['domains']`, `aliases`, `domain_set_paths`, `payload` | `{'domain:<orders>': rewritten_domain}` and no findings |
| `_normalize_sequence()` | `'dispositions'`, `payload['dispositions']`, `aliases`, `disposition_set_paths`, `payload` | A one-record list whose disposition ID and activity references are canonical, and no findings |
| `_normalize_records()` | `'domains'`, `sorted(payload['domains'].items())`, `aliases`, `domain_set_paths`, `payload` | `[rewritten_domain]` and no findings |
| `_rewrite()` | `payload['domains']['domain:orders']`, `aliases`, `payload` | The same record with ID `domain:<orders>` and memberships using `activity:<update>` and `activity:<notify>` |
| `_canonicalize_sets()` | `rewritten_domain`, `domain_set_paths` | The same domain with only contract-defined set arrays deduplicated and sorted; each activity role remains attached to its activity ID |
| `_evidence_ids()` | Not called on the successful path; the collision variation below passes each unequal rewritten update-activity record | The `evidence_ids` already present in those records; the factory-built example returns an empty set |
| `_collision_finding()` | Not called on the successful path; the collision variation passes `'activities'`, `'activity:<update>'` and the unequal update-activity entries | One `CANONICAL_ID_COLLISION` finding whose subjects are the shared canonical ID and the response-local IDs |

The domain membership rewrite performed inside `_normalize_records()` is therefore:

```text
_rewrite() input:  [(activity:a, primary), (activity:b, supporting)]
_rewrite() output: [(activity:<update>, primary),
                    (activity:<notify>, supporting)]
```

The relabeled input produces the same output when `_rewrite()` receives `activity:x` and `activity:y`. `_normalize_mapping()` does not perform that rewrite itself. It invokes `_normalize_records()`, which invokes `_rewrite()`, and then stores the returned domain under `domain:<orders>`.

The same grouping step handles repeated records without guessing:

| Synthetic variation | Records grouped under `activity:<update>` after rewriting | Required result |
| --- | --- | --- |
| An additional response-local activity repeats the update activity exactly, including equivalent normalized references | One distinct canonical body | Emit the update activity once and redirect every reference to `activity:<update>` |
| An additional activity uses the same identity basis as the update activity but has a different description | Two distinct canonical bodies | Emit neither group member and add one `CANONICAL_ID_COLLISION` finding |

The rejected candidate remains process-local. `DomainError.record()` must continue to omit it.

### 4. Use the existing repair cycle

`Synthesis.run()` must catch only a semantic normalization error that contains findings and a rejected candidate. It must pass those findings to the existing `_validate_verify_repair(..., initial_findings=findings)` owner. The result must remain in the existing accounting path rather than return early:

```python
initial_findings = None
try:
    candidate, cached = self._run_with_retries(
        synthesis_request, allow_candidate_cache=True)
except DomainError as exc:
    if not (
            exc.repair_kind == 'semantic'
            and exc.findings
            and exc.rejected_candidate is not None):
        raise
    candidate = exc.rejected_candidate
    cached = False
    initial_findings = exc.findings

if cached:
    result = candidate
else:
    result = self._validate_verify_repair(
        graph, synthesis_request, candidate, validate_candidate,
        initial_findings=initial_findings)
```

The existing owner gains only the optional findings entrance:

```python
def _validate_verify_repair(
        self, graph, synthesis_request, candidate, validate_candidate,
        initial_findings=None):
    findings = (
        copy.deepcopy(initial_findings)
        if initial_findings is not None
        else self._candidate_findings(
            graph, candidate, validate_candidate)
    )
```

The required sequence is:

```text
synthesis returns a collision
  → verify the rejected candidate and deterministic collision findings
  → repair once
  → normalize and deterministically validate the replacement
  → independently reverify the replacement
  → commit the verifier-linked cache record
```

A second collision, failed reverification, cancellation, timeout, provider failure, budget failure or source supersession must stop through the existing terminal failure path. The runtime must not recursively repair another collision.

### 5. Commit only a verified replacement

`_commit_or_store_repaired_synthesis(request, repaired, verification_key)` must reuse `_request_key()`, `project_exchange()`, `_cache_identity()`, `_store_request()` and `_store_response()`.

The successful repaired response must use the stable original synthesis-request identity and link to the passing reverification record. If the initial collision occurred before response staging, this function must create the same canonical `SemanticResponse` metadata. It must never write the rejected candidate.

The fallback synthesis checkpoint is a locally constructed association between the original synthesis request and the independently verified repaired candidate. Its `usage.input_tokens` and `usage.output_tokens` must be `null`: attributing either the rejected synthesis call or the separate repair call to this constructed response would be false. Actual provider usage remains charged in the shared `Limits` counters, and the repair response retains its own reported usage.

The existing final synthesis commit in `_validate_verify_repair()` must call this helper instead of assuming `_run_once()` staged a response:

```python
def _commit_or_store_repaired_synthesis(
        self, request, repaired, verification_key):
    request_key = self._request_key(request)
    metadata = copy.deepcopy(self.pending_responses.get(request_key))

    if metadata is None:
        schema = wire_schema('CandidatePayload', request['graph'])
        _, provider_schema, _ = self.project_exchange(request, schema)
        request_key, response_key, prompt_hash, schema_hash = \
            self._cache_identity(request, provider_schema)
        response = record(
            'SemanticResponse', request_id=request['request_id'],
            operation='synthesize',
            input_fingerprint=request['input_fingerprint'],
            candidate=copy.deepcopy(repaired),
            verification_report=None,
            usage={'input_tokens': None, 'output_tokens': None},
            provider_revision=None, warnings=[])
        metadata = {
            'request_key': request_key,
            'response_key': response_key,
            'prompt_hash': prompt_hash,
            'schema_hash': schema_hash,
            'response': response,
        }
        self._store_request(
            self.root/'.speed/context/business-domain-cache',
            request, request_key)
    else:
        metadata['response']['candidate'] = copy.deepcopy(repaired)

    validate(metadata['response'], 'SemanticResponse')
    self._store_response(
        self.root/'.speed/context/business-domain-cache',
        metadata, verification_key)
    self.pending_responses.pop(request_key, None)
```

### 6. Keep the publication boundary unchanged

No new publication path is required. `discover()` in `business_domains.py` already retains the previous model, accepts only a verified candidate, rechecks inventory and snapshots, validates references and evidence and writes atomically.

The harness exercised this production publication path. It covered a successful publication, a cache-only refresh and byte-for-byte preservation of the previous artifact after a repeated collision, failed reverification, cancellation, timeout, provider failure or source supersession.

## Contract-derived proof

### Production owners used

The temporary harness imported these production owners:

```python
from lib.context.business_domain_schema import (
    DEFINITIONS, DomainError, canonical, digest, limits, record,
    required_scope_subjects, settings, validate, validation_finding,
)
from lib.context.business_domain_synthesis import (
    OPERATIONS, ProviderProjection, Synthesis, wire_schema,
)
from lib.context.business_domains import discover, paths
```

The harness generated each specimen with `record()` and passed it through `validate()` before the tested operation. It did not import test fixtures, copy a retained payload, start a provider process or call a model. Its deterministic sequencer implemented only the existing injected `generate()` test boundary and returned schema-derived values.

### Complete finite partition

The algorithm's behavior can differ only across these contract branches:

- Nine candidate map collections with one record, equal records with one basis, unequal records with one basis or unequal records with different bases.
- Two sequence collections with equal records, reordered set fields or unequal records.
- Temporary-ID ownership checks.
- Scalar, list and dictionary rewrite, including a rewritten-key collision.
- Ordinary allocation and a forced short-hash collision.
- Whole-graph, slice and reconciliation graph scopes.
- Synthesis, verification, repair and reverification responses.
- First-pass, repaired, cached, repeated-failure, cancellation, timeout, provider-failure, corrupt-cache and publication outcomes.
- Provider-schema prefix enforcement for every provider-created record type, including all three `ScopeDisposition` conditional variants.
- A malformed verification-finding prefix followed by one schema-valid retry.

JSON strings and array lengths are unbounded, so enumerating values is not a meaningful proof method. The proposed algorithm is value-independent:

- Canonical serialization is total for schema-valid JSON.
- Recursive rewriting is partitioned by scalar, list and dictionary structure.
- Full canonical bytes distinguish values after a forced short-hash collision.
- Final group cardinality selects one of the three guaranteed outcomes.

The earlier harness omitted agreement between provider-schema ID patterns and normalization-prefix validation. The maintained prefix and retry regressions pass, but the removed harness has not been rerun with an amended denominator; no updated harness-completeness claim is made.

### Payload-stage coverage

| Stage | Production contract or function | Proof cases |
| --- | --- | --- |
| Construction | `record()`, `DEFINITIONS` | All applicable cases |
| Schema validation | `validate(CandidatePayload\|VerificationReport\|GraphScope\|SemanticRequest\|SemanticResponse\|CacheArtifact)` | All applicable cases |
| Provider projection | `ProviderProjection`, `wire_schema()` exact local round-trip and provider-created ID-prefix constraints | 14-15, 50-75 and the maintained prefix regression |
| Wire decoding | `from_wire()` for candidate and verifier output | 14-15 and 50-75 |
| Normalization | Current and proposed `normalize_ids()` behavior | 1-49 |
| Scope validation | `required_scope_subjects()`, `candidate_scope_findings()` and verifier-envelope checks | 50-59 |
| Verify, repair and reverify | Production request builder, retry gate and response handling | 50-52, 56 and 58 |
| Cache | Production request and response identity, atomic writes and verifier linkage | 54-57, 59, 66 and 68 |
| Extraction and publication | Actual `Extractor.extract()` and `discover()` validation, source, evidence and atomic-write path | 67-75 |

The companion [failure-mode matrix](business-domain-discovery-failure-mode-matrix.md) provides one contract-valid example, executed failure, root cause, fixing function, verification case and business outcome for each of its 36 rows.

## Commands and recorded output

The temporary harness was executed with these commands:

```sh
shasum -a 256 .tmp_business_domain_collision_proof.py
.venv/bin/python .tmp_business_domain_collision_proof.py
```

The earlier 75-case output is recorded in the companion [failure-mode matrix](business-domain-discovery-failure-mode-matrix.md). The harness file is no longer present. Its recorded SHA-256 and summary are:

```text
2df0c5169e3e34ebea9b6f0dbc9a47745dd7408e3a3099754057ae6924c6214b  .tmp_business_domain_collision_proof.py
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

This recorded result predates the verifier-prefix production regression. It is retained as historical evidence and is not a complete result for the amended contract.

The maintained supplemental suite was rerun after the provider-prefix fix:

```sh
.venv/bin/pytest -q tests/test_business_domain_candidate_protocol.py tests/test_business_domain_contract_alignment.py
```

```text
144 passed in 5.74s
```

An earlier offline rerun showed that this suite depends on an external tokenizer download:

```sh
.venv/bin/pytest -q --tb=no tests/test_business_domain_candidate_protocol.py tests/test_business_domain_contract_alignment.py
```

```text
8 failed, 118 passed in 3.53s
```

All eight failures attempted to download `o200k_base.tiktoken` from `openaipublic.blob.core.windows.net` and failed on name resolution. They do not change the recorded 75-case harness denominator, but they prove that the maintained supplemental suite is not hermetic in this checkout.

The broader collection command also remains blocked:

```sh
.venv/bin/pytest -q --collect-only tests/test_business_domain*.py
```

```text
332 tests collected, 10 errors in 1.97s
```

Eight modules import the removed `packet_for` or `STAGES` symbols. Two modules import an unresolved `test_business_domain_pipeline` module path. The broader suite did not execute and is not a release signal.

## Implementation and release gates

Implementation is complete only when all gates pass:

1. Add the specified normalization and runner changes to the existing production owners.
2. Install the 75 temporary harness obligations as maintained tests that execute the production implementation without monkeypatching replacement logic.
3. Make the targeted suite hermetic and pass all 126 tests offline.
4. Repair the 10 collection errors and pass the complete business-domain suite.
5. Confirm that the implementation diff adds no parallel parser, validator, error, cache or publication path.
6. Run a real provider evaluation as a separate semantic-quality gate. Do not use it as proof of deterministic collision safety.

## Scientific confidence score

**100.000% deterministic contract-partition coverage: 75 of 75 atomic obligations and 36 of 36 matrix rows passed.**

```text
score = min(75 / 75, 36 / 36) × 100 = 100.000%
```

This is an exact coverage calculation, not a confidence estimate. It applies only to the defined identity-collision contract, its finite branch partition and the temporary proposed implementation that the harness executed. It does not mean production is fixed, the current test suite is green, arbitrary provider semantics are correct or the historical payload was reproduced.
