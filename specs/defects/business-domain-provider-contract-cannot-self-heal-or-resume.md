# Defect: Provider contract violations cannot self-heal or reliably resume

Severity: P0
Related Feature: speed-business-domain-discovery
Finding: F-10
Status: In Progress
Related Findings: F-04, F-08, F-09
Tags: provider, contracts, validation, repair, verification, cache, resume, hierarchy, budgets, observability

## Summary

Business-domain discovery advertises one provider output contract but applies
additional fail-fast rules after the response. A response can therefore satisfy
the model-facing schema and still fail runtime acceptance. The repair request
contains neither the rejected candidate nor a complete validation report, and
all structural and semantic failures share one repair allowance.

The implementation also runs a legacy activity/grouping/evidence-review
protocol instead of the RFC's synthesize/verify/repair protocol. It caches local
acceptance without independent candidate verification, invalidates successful
work through broad implementation fingerprints, cannot resume oversized
grouping, and reports reconciled anchor coverage instead of completed semantic
work.

The model is allowed to make mistakes. SPEED is not allowed to maintain
contradictory contracts, lose validated work, publish unverified work, or ask a
fresh model invocation to repair an output it cannot see.

## Required invariants

1. The canonical contract and runtime acceptance rules cannot disagree.
2. Every provider violation produces one complete structured validation report.
3. Repair receives the rejected candidate, original evidence scope, all
   deterministic findings and the independent verifier report.
4. Every repaired candidate is deterministically validated and independently
   verified again.
5. Every successful semantic unit is atomically cached before the orchestrator
   acknowledges completion or begins dependent work.
6. A failed unit cannot invalidate or hide other successful units.
7. Compatible cached candidates are revalidated and promoted; only incompatible
   candidates are regenerated.
8. An unfinished hierarchy never publishes, but its validated children remain
   resumable.
9. Status and CLI output distinguish provider transport failure, model contract
   violation, semantic rejection, pending work and completed cached work.

"Successful semantic unit" means a candidate whose shape, references,
evidence, deterministic rules and independent semantic verification all pass for
its declared scope. A merely parseable provider response is not successful.

## Production evidence

The PetClinic refresh started at 16:46:27 and failed at 17:08:15 after four
provider invocations. The status retained one validated semantic unit and eleven
pending units, but the CLI displayed `0/86 entrypoints processed`.

The second child response contained at least two independent violations:

- provider-created records used `review_state = needs_review`; and
- four `InformationUse` records had empty `resource_ids`.

The first validation pass reported only the review-state error. The one repair
changed the review state, after which validation exposed the previously hidden
resource error and exhausted the allowance. The final error was:

```text
Hierarchical child scope:fdbad720f93651472f5decaf could not be validated:
Information use requires an evidenced resource
```

The two directly observed field contradictions have been added to the current
wire schema. They prove the architectural defect; they do not close it.

## Verified implementation defects

### 1. Normative and runtime contracts intentionally differ

`specs/tech/contracts/check_contracts.py` explicitly states that runtime still
uses the legacy three-stage pipeline. It permits twelve normative-only
definitions, eleven runtime-only definitions and ten changed shared definitions
by pinning both divergent schema hashes.

A green contract check therefore proves only that the known divergence did not
change. It does not prove runtime RFC compliance.

### 2. Independent candidate verification is absent

Runtime stages are `activity`, `grouping` and `evidence_review`. Evidence review
evaluates individual submitted claims after grouping; it does not receive and
independently evaluate the complete candidate and scope for missing activities,
false merges, unsupported boundaries or omitted evidence.

The RFC requires `synthesize`, `verify` and `repair`, with verification of every
initial and repaired candidate.

### 3. Repair is blind regeneration

The retry path sends only an error code, message and generic instruction. It
does not send:

- the rejected payload;
- the failing record and field when known;
- all other deterministic violations;
- allowed evidence/reference alternatives; or
- an independent verification report.

Each CLI invocation starts a fresh provider context, so the provider cannot see
its previous output unless SPEED includes it in the repair request.

### 4. Validation reports only the first problem

Wire validation uses a throwing `validate()` call. Canonical validation collects
schema errors but selects `errors[0]`. Semantic acceptance contains twenty-eight
immediate `DomainError` sites, and information-use closure contributes three
more. No common validator aggregates them.

### 5. Repair allowances are conflated

Malformed JSON/schema output and deterministic semantic rejection use the same
`schema_repair_limit = 1`. A shape correction can consume the only opportunity
to repair an unrelated evidence or coverage defect. Provider transport retry,
schema correction and semantic repair are separate RFC operations and budgets.

### 6. The wire contract remains weaker than runtime acceptance

Known examples include:

- `Rule.basis.uniqueItems` is removed from the provider schema;
- activity evidence, claims and traces may be empty;
- a provider may mark a rule relationship as `verified`;
- rule-relationship evidence and explanation may be empty;
- domain memberships, evidence, claims and rationale may be empty;
- activity-membership claim IDs may be empty; and
- packet reference enums are omitted above 128 available IDs.

Graph-dependent constraints cannot all be represented in JSON Schema. They
must still be declared once as canonical rules and returned as structured,
repairable findings rather than hidden throwing conditions.

### 7. Material semantic claims can escape complete verification

The legacy acceptance path does not independently verify the complete candidate.
In particular, it does not fully prove supported domain membership,
ownership-through-information-use, evidenced domain relationships, or complete
activity coverage through claim-by-claim review.

### 8. Cache success is weaker than RFC success

The current response is cached after local schema/reference acceptance, but no
independent candidate verifier exists. The cache therefore cannot establish the
RFC's successful-unit invariant.

### 9. Cache lookup has no compatible promotion path

The response key includes the packet, prompt, output schema and provider
fingerprint. The provider fingerprint also hashes broad SPEED implementation and
bridge/provider files. Any changed component creates a new exact key. SPEED does
not search older candidates by stable semantic scope, revalidate them under the
current contract and promote compatible results.

The exact execution cache may retain all fingerprints for reproducibility. A
separate stable semantic checkpoint must identify reusable work by semantic unit,
relevant evidence and semantic-contract version.

### 10. Oversized grouping is a permanent failure loop

Grouping shrinks an oversized request to a stable activity prefix, caches the
prefix result, and then rejects publication because activities were omitted. A
later refresh selects the same prefix, reuses the same result and fails again.
There is no grouping hierarchy that reconciles all activity partitions.

### 11. Preflight does not reserve the completion path

Execution-mode selection sizes activity generation only. It does not reserve
the complete synthesis, independent verification, possible repair,
reverification, grouping and root-reconciliation sequence. The published
`completion_input_tokens_reserved` and `completion_output_tokens_reserved`
fields are never populated by runtime execution.

### 12. Hierarchical reconciliation loses typed obligations

Cut-edge IDs are placed inside coverage-claim prose instead of structured
cross-scope fields. Reconciliation retains one globally selected evidence
excerpt and assigns that same citation to every child coverage claim, regardless
of which child supplied it. Hash references cannot substitute for the typed
cut-edge and evidence closure required for verification.

### 13. Failure lacks durable per-unit repair state

Validated child payloads are cached, but validation findings, rejected
candidates, attempt state and the exact next operation are not durably linked to
the semantic unit. A failed child ends hierarchical reconciliation rather than
remaining a resumable repair task.

### 14. Operator progress is misleading

Hierarchical child completion increments semantic-unit counters but does not
increment processed-anchor coverage until root reconciliation. The CLI prints
only anchor coverage, so completed and cached work appears as zero progress.

### 15. Invalid prior artifacts repeatedly poison diagnostics

Refresh detects an invalid stored domain artifact but deliberately leaves it at
the authoritative path unless a new publication succeeds. Every failed refresh
and digest projection therefore reopens the same invalid artifact and repeats
the warning instead of quarantining it as a non-authoritative diagnostic object.

### 16. Completion is hard-coded to partial

Successful publication unconditionally sets `model.status = partial`. Runtime
never derives `complete` versus `partial` from processed scope, capability gaps,
support and external freshness.

## Root cause

The implementation created parallel sources of truth:

```text
runtime artifact schema
        +
provider wire-schema mutations
        +
three provider prompts
        +
throwing procedural validators
        +
different normative RFC schema
```

No registry proves that every provider-output rule has one schema projection,
one deterministic validator, one repair representation and one conformance test.
The legacy pipeline was retained beside the normative design, and the contract
checker was changed to pin that divergence instead of requiring convergence.

## Required correction

### Canonical contract and validation

1. Replace the legacy stage payloads with the RFC's `SemanticRequest`,
   `SemanticResponse`, `CandidatePayload`, `ValidationFinding` and
   `VerificationReport` contracts.
2. Make the runtime schema an exact generated or byte-identical copy of the
   normative schema. Remove the migration hash allowlist.
3. Create one canonical deterministic rule registry. Each rule declares its
   stage, applicability, schema projection when expressible, validator,
   structured finding and repair guidance.
4. Reject startup/tests when a provider-output validation rule is not registered
   or its schema projection and runtime behavior disagree.
5. Return all deterministic findings in one pass with stable rule ID, severity,
   subject IDs, field path, expected condition, supplied value summary, allowed
   evidence/reference choices and repair instruction.

### Self-healing sequence

6. Run schema decoding and every deterministic rule without mutating the
   candidate.
7. Run an independent complete-scope verifier after deterministic validation.
8. If either verifier rejects, send a repair request containing the original
   graph scope, rejected complete candidate, all deterministic findings and the
   failed/uncertain verifier report.
9. Validate and independently verify the complete replacement again. Continue
   for distinct failure signatures within the bounded schema/semantic allowances;
   never require a new CLI invocation merely to advance the repair chain.
10. If an equivalent failure repeats or a hard allowance is exhausted, persist
    the unit, attempted signatures, findings and next operation. Preserve all
    other successful units and the previous publication.
11. Keep provider transport retry, malformed-output correction and semantic
    repair as independent counters and budgets.

### Durable cache and resume

12. Atomically commit every successful unit before returning it to the scheduler.
13. Keep an immutable exact execution cache keyed by request, prompt, schema and
    provider fingerprints.
14. Add a semantic checkpoint index keyed by stable scope ID, relevant evidence
    fingerprint and semantic-contract version.
15. On an exact-key miss, revalidate a compatible prior candidate and promote it
    without a provider call. Regenerate only when evidence changed or the
    candidate fails the current contract/verifier requirements.
16. Persist request, candidate, validation report, verification response and
    completion state as one linked unit record. Invalid attempts may be retained
    separately for diagnostics but can never masquerade as successful cache.

### Complete bounded execution

17. Preflight and reserve synthesis, verification, one repair and reverification
    before dispatch; admit later distinct repairs only within remaining hard
    request, build and deadline allowances.
18. Partition and reconcile grouping as resumable semantic units; never send a
    known incomplete prefix as if it could complete the root operation.
19. Preserve child scope IDs, dispositions, typed cross-scope edges, obligations
    and child-specific evidence structurally through every roll-up.
20. Derive complete/partial status from validated coverage and capability gaps.
21. Expose total, validated, cached, active, failed and pending semantic units in
    CLI/API/UI alongside reconciled anchor coverage.
22. Quarantine invalid authoritative artifacts while retaining their bytes and
    diagnostic identity; do not repeatedly treat them as readable publication.

## Acceptance tests

F-10 is resolved only when all of the following pass:

1. Runtime and normative schemas are identical; no divergence allowlist remains.
2. Every registered provider rule has schema/validator/finding/repair conformance
   coverage.
3. Property fixtures accepted by the provider schema either pass deterministic
   validation or return declared semantic findings; no unregistered rejection
   path exists.
4. A response containing five independent violations returns all five findings
   in one report.
5. A repair request contains the exact rejected candidate and all findings.
6. A corrected replacement passes deterministic validation and independent
   reverification before caching.
7. A still-invalid replacement leaves only its unit pending and preserves every
   successful cached unit.
8. Malformed-output correction does not consume semantic-repair allowance.
9. A fabricated but shape-valid complete candidate is rejected by the independent
   verifier and cannot publish.
10. Every successful unit has a durable cache entry before dependent work begins.
11. Interruption immediately after unit completion resumes without repeating its
    provider calls.
12. An unrelated SPEED implementation change revalidates/promotes a compatible
    cached candidate instead of regenerating it.
13. Relevant evidence change invalidates only dependent semantic units.
14. Contract change revalidates old candidates and regenerates only failures.
15. Oversized grouping partitions, validates, caches and reconciles every activity
    without repeating a permanent prefix failure.
16. Preflight refuses dispatch when the complete required sequence cannot fit.
17. Every reconciliation packet contains typed child scopes, dispositions,
    cross-scope edges, obligations and child-specific evidence.
18. The PetClinic multi-error child self-heals within its declared allowances.
19. During that run, CLI/API/UI report semantic progress independently from root
    anchor reconciliation.
20. An invalid prior artifact is quarantined once and does not produce repeated
    authoritative-artifact warnings.
21. Complete evidence/capability coverage produces `complete`; explicit supported
    gaps produce `partial`; unfinished work never publishes either state.
22. One full uncached PetClinic run succeeds, its artifact passes canonical and
    independent verification, and an unchanged second run makes zero semantic
    provider calls.

## Resolution

Status: in progress. Implemented and covered:

- aggregate schema findings and exact-candidate repair context;
- independent schema, semantic-repair and provider-retry allowances;
- deterministic revalidation plus independent claim verification before cache;
- verifier-linked exact caches and stable semantic checkpoint promotion;
- durable completion/cached/active/failed/pending accounting at the unit boundary;
- full-sequence budget preflight before provider dispatch;
- one-time byte-preserving invalid-artifact quarantine;
- derived complete/partial publication status; and
- exhaustive verified grouping partitions with recursive reconciliation.

F-10 is not resolved until the remaining acceptance work lands: replace the
legacy request/payload types with `SemanticRequest`/`SemanticResponse`, make the
runtime and normative schemas identical without the migration allowlist, move
all procedural provider rules into the canonical aggregate rule registry,
persist failed repair state, preserve typed child/cross-scope reconciliation
records, and pass a full uncached plus zero-call cached PetClinic trial.
