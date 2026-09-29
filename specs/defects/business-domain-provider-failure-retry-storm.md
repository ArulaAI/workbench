# Defect: Provider-wide failure becomes a per-packet retry storm and publishable budget truncation

Severity: P0
Related Feature: speed-business-domain-discovery
Finding: F-09
Status: Resolved
Related Findings: F-04, F-07, F-08
Tags: provider, failure, retries, circuit-breaker, budget, cache, publication, concurrency, diagnostics

## Implementation progress

Resolved on 2026-09-08. The existing shared provider owner now carries one
validated provider-agnostic failure envelope; Codex and Claude adapters classify
their native failures without provider-specific orchestration branches. Cache
lookup precedes a synchronized first-real-request gate. Initial terminal failure
stops fan-out, while a previously healthy provider gets one controlled recovery
attempt before the build circuit opens. Opening the circuit cancels queued work,
prevents later dispatch/reservation, preserves provider causality and discards the
candidate while retaining facts, validated cache and the previous publication.

Oversized activity work now selects deterministic whole-graph, canonical-entry
bundle and typed execution-edge scopes. Stable child identity and cut-edge
coverage survive compact, recursive reconciliation; only a genuinely oversized
atomic child fails with `OVERSIZED_ATOMIC_RECORD`. No hierarchical prefix can
publish before root reconciliation. Status and GraphQL/UI projections expose the
execution mode, active scope, root-reconciliation state and normalized provider
cause with a bounded sanitized diagnostic reference.

Verification: 369 Business Domain tests, 95 shared parser/CSG tests, 28 Python
provider tests, 23 shell provider parsing tests, 23 valid plus 14 invalid contract
specimens, 8 GraphQL tests and 30 focused Discover UI tests pass. PetClinic- and
Grocery-shaped regressions prove bounded calls, causal status, cache retention,
byte-preservation of the previous 24-activity publication and recovery on a new
explicit refresh.

## Summary

Business-domain discovery treats failure of the shared semantic provider as an independent failure of each activity packet. Each packet receives a fresh retry allowance. After that packet fails, the activity loop marks only its anchor pending and sends the next packet to the same failing provider.

There is no build-wide provider-health state, initial provider gate or circuit breaker.

During a shared provider failure, the implementation can therefore:

- invoke the same unavailable provider once or twice for nearly every anchor;
- consume the build's request, time and token reservations on failures;
- relabel later unattempted work as `BUILD_BUDGET`;
- skip domain grouping because the induced budget exhaustion is treated as ordinary truncation; and
- publish a new `partial` artifact that is substantially less complete than the previous published artifact.

The external provider or authentication failure is not itself the product defect. The defect is SPEED's inability to identify a provider-scoped failure, stop further dispatch and preserve the previous published model.

The RFC requires one bounded retry for a transient provider failure and states that repeated failure ends the attempt without replacing the previous valid artifact. The current retry scope is the packet, not the attempt, so the implementation does not satisfy that requirement.

## User-visible impact

A user requesting one refresh can wait many minutes while SPEED repeatedly calls a provider path that has already failed in the same way. The final status can then blame the configured token budget rather than the provider failure that consumed it.

The result is nondeterministic and timing-dependent:

- if a final provider error escapes during grouping, the attempt fails and preserves the previous model;
- if failed calls exhaust the budget first, grouping converts the condition into publishable partial coverage; and
- cached activity results can make the incomplete candidate appear sufficiently populated to pass the current publication path even though fresh synthesis was unavailable.

Two runs against the same source and the same provider failure can therefore preserve or replace the prior artifact based on where the budget happens to run out.

## Evidence from the PetClinic trial

The trial repository is `/private/tmp/speed-domain-petclinic`.

### Provider failure evidence

At least one captured provider log records the Codex CLI attempting its response WebSocket and receiving repeated:

```text
HTTP error: 403 Forbidden
```

The wrapper then reports:

```text
Codex CLI (JSON mode) exited with code 1
CLI returned non-zero exit but produced output, proceeding
JSON agent returned no final agent message
```

Other captured calls report the same non-zero exit and missing final agent message without retaining a more specific remote error in that log. The available evidence proves that some calls received HTTP 403 and that the bridge ultimately returned a generic invocation failure. It does not establish whether every failed call had the same native cause.

An HTTP 403 can result from authentication, authorization, model/account access, transport policy or another provider-side rejection. The retained diagnostic does not identify which cause applied, so this defect does not label the event as a confirmed service outage.

### Retry-storm evidence

The current PetClinic status records:

- 95 total anchors;
- six processed anchors;
- one excluded anchor;
- 88 pending anchors;
- 88 `PROVIDER_FAILED` warnings;
- 185 provider requests;
- 89 retries;
- approximately 565 seconds elapsed; and
- terminal phase `failed` with `freshness = stale`.

The previous published build was retained. That part of the terminal failure behavior worked. The defect remains directly reproduced because the attempt contacted the failing provider 185 times before reaching that terminal result.

### What the PetClinic evidence proves

- Provider failure was repeated across many activity packets.
- A packet-level retry allowance was repeatedly renewed.
- The activity loop continued after each final packet failure.
- The attempt performed far more than one initial attempt and one bounded recovery retry.
- The eventual terminal failure preserved the previous model.

### What the PetClinic evidence does not prove

- It does not prove the underlying account, credential or service condition that caused the 403.
- It does not prove that every one of the 88 final packet failures was caused by the 403 rather than another provider error.
- It does not prove that every provider failure should be terminal; packet-specific invalid output can be isolated and repaired.
- It does not make PetClinic's 95-anchor inventory valid; F-07 covers that independent problem.

## Evidence from the Grocery trial

The trial repository is `/private/tmp/speed-domain-grocery`.

### Provider failure evidence

Captured Grocery logs also contain repeated Codex response-WebSocket failures with:

```text
HTTP error: 403 Forbidden
```

They end as generic exit-code-one/no-final-message failures, just as in PetClinic.

### Failure became budget truncation

The published Grocery status records:

- 29 total anchors;
- seven processed anchors;
- 22 pending anchors;
- 12 `PROVIDER_FAILED` warnings;
- 12 `BUILD_BUDGET` warnings;
- 33 provider requests;
- 14 retries;
- 5,940,000 input tokens reserved against a 6,000,000 build limit;
- `truncated = true`;
- approximately 1,712 seconds elapsed;
- zero published domains; and
- phase `partial`, `freshness = current`, with no terminal error.

The immediate previous artifact retained in history contains 24 activities. The newly published artifact contains only seven activities and zero domains.

This is the more serious failure mode. Repeated provider failures consumed enough budget that later work raised `BUILD_BUDGET`. Grouping treats that code as permissible partial truncation, so the candidate was validated and published instead of terminating the attempt and retaining the prior artifact.

### What the Grocery evidence proves

- Multiple provider failures were tolerated and retried during one build.
- The global reservation approached its configured maximum.
- Later anchors and grouping were classified as budget-limited.
- A degraded partial artifact became the current published artifact.
- The current artifact is materially less complete than its immediate predecessor by activity count.
- Provider failure and budget truncation are not kept causally distinct.

### What the Grocery evidence does not prove

- It does not prove the exact tokens billed by the provider; the shell bridge reports no usage and the implementation retains local reservations.
- It does not prove that every request represented a distinct business activity.
- It does not prove that the previous 24 activities or any earlier domains were semantically correct.
- It does not by itself determine the publication policy for ordinary budget exhaustion. The revised RFC now requires unfinished semantic work to remain resumable and non-publishing even when the provider is healthy.

## Exact implementation path

### 1. Provider configuration is mistaken for availability

`Synthesis.__init__()` calls:

```python
self._speed_call('config')
```

The `config` action in `lib/context_bridge.sh` returns the selected provider, model and project-instruction path. Sourcing `lib/provider.sh` also verifies that the configured provider binary exists.

This checks local configuration only. It does not verify:

- provider authentication;
- authorization for the selected model;
- remote endpoint availability;
- structured-output capability; or
- the end-to-end transport used by the actual request.

### 2. The shared error loses its meaning at the bridge boundary

For an `agent` action, `context_bridge.sh` calls `provider_run_json()` and returns only a shell exit status on failure.

The Codex wrapper can receive a non-zero CLI result plus lifecycle JSONL output. It logs the non-zero result but proceeds when output exists. If the output contains no completed agent message, it finally returns exit code one.

`Synthesis._speed_call()` maps every non-zero `agent` result to:

```text
PROVIDER_FAILED
```

The Python layer therefore cannot distinguish:

- HTTP 401/403;
- rate limiting;
- service or network unavailability;
- model/capability rejection;
- timeout;
- provider CLI crash;
- a completed response with invalid JSON; or
- an incomplete structured-output stream.

Provider-specific parsing belongs in the provider adapter, but the shared provider interface currently exposes no machine-readable failure contract to its consumers.

### 3. Retry scope resets for every packet

`Synthesis.run()` initializes:

```python
transient = repairs = 0
```

That method is called independently for each activity, grouping and evidence-review packet. `PROVIDER_FAILED` and `PROVIDER_TIMEOUT` are transient retry codes, so every packet receives its own retry.

The implementation satisfies “one retry per call to `run`,” not “one bounded recovery from repeated provider failure during the build.”

### 4. The activity loop converts provider failures to pending anchors

The activity worker returns `DomainError` to the main loop. The main loop rethrows only:

```text
CANCELLED
PROVIDER_UNAVAILABLE
PROVIDER_CAPABILITY_UNAVAILABLE
```

Because runtime invocation failures are labeled `PROVIDER_FAILED`, each failure is converted into:

- an `Unassigned(status = pending)` record for that anchor; and
- a `PROVIDER_FAILED` warning.

The ordered worker then submits the next anchor.

### 5. Failed attempts consume global reservations

Before every provider dispatch, `_run_once()` reserves the estimated input and full configured output allowance. Retries are dispatched through the same path and therefore consume the same global budget.

Charging dispatched retries is required by the RFC. The defect is allowing a known shared failure to create another independently retryable packet. Once the shared provider failure is established, no further packets should be dispatched or reserved.

The shell bridge returns no usage object, so `_run_agent()` returns `{}` and conservative reservations remain in force. This is an explicit fallback in the current code; it makes stopping repeated provider failures particularly important.

### 6. Budget exhaustion changes the publication outcome

Grouping catches these errors as permissible truncation:

```text
BUILD_BUDGET
BUILD_TIMEOUT
PACKET_LIMIT
PROVIDER_BUDGET
```

If provider failures consume the build budget before grouping dispatch, grouping receives `BUILD_BUDGET`, not the original provider failure. It marks all interpreted activities pending grouping and continues toward partial publication.

If `PROVIDER_FAILED` reaches grouping before budget exhaustion, it is not caught and the attempt fails. The preservation decision therefore depends on which error occurs first.

### 7. Evidence review can swallow provider unavailability

The evidence-review loop catches every `DomainError` other than cancellation. For `PROVIDER_UNAVAILABLE`, it breaks out of review and continues toward publication.

That means even correctly classified provider unavailability is not currently terminal at every synthesis stage.

### 8. Error retryability is persisted incorrectly

`DomainError.record()` always emits:

```json
{"retryable": false}
```

This is true even when `Synthesis.run()` has treated the error code as transient and retried it. The persisted error contract therefore disagrees with runtime policy.

## Root cause

Provider execution has two incompatible failure models:

- the shared shell provider layer exposes largely unclassified exit status and human logs; and
- business-domain synthesis applies retries and continuation independently to each semantic packet.

There is no common provider failure taxonomy and no build-wide owner of provider health.

The implementation correctly tries to isolate packet-specific failures so one malformed response does not discard all useful work. It incorrectly applies that isolation to provider-scoped authentication and transport failures. A single bad packet and a shared unavailable provider both become `PROVIDER_FAILED`.

## Required behavior

Business-domain discovery must distinguish:

| Failure | Scope | Required response |
| --- | --- | --- |
| Invalid structured payload for one semantic request | Request | One schema repair; if still invalid, reject that candidate or leave that hierarchical unit incomplete |
| Whole graph or application-boundary slice too large | Build/unit | Select hierarchical mode, then canonical-entry-point bundles and typed execution-edge segments as required; never treat a monolith as indivisible |
| One atomic record plus mandatory evidence still exceeds the effective cap | Unit | Leave that exact unit pending with an oversized-atomic-record diagnostic and fail without publication; never silently truncate it |
| Genuine global budget limit while provider is healthy | Build | Stop dispatch, retain validated reusable work and exact pending scope, and preserve the previous published model |
| One transient transport interruption | Provider request | One bounded recovery retry |
| Initial authentication/authorization/capability failure | Provider/build | Stop before synthesis fan-out |
| Repeated equivalent provider failure after prior success | Provider/build | Open the circuit and terminate the attempt |
| User cancellation or source supersession | Build | Stop and preserve the previous publication |

Provider-scoped failure must never be converted into a sequence of unrelated anchor failures.

## Proposed solution

### 1. Add one shared machine-readable provider failure contract

Extend the existing shared provider abstraction in `lib/provider.sh`. Do not add Codex-, Claude- or vendor-specific parsing to business-domain Python.

The common failure envelope should contain at least:

```json
{
  "category": "authorization_denied",
  "scope": "provider",
  "retryable": false,
  "native_status": "403",
  "message": "Provider rejected the request",
  "diagnostic_log": ".speed/logs/..."
}
```

Required normalized categories include:

- `authentication_required`;
- `authorization_denied`;
- `capability_unavailable`;
- `rate_limited`;
- `transport_unavailable`;
- `timeout`;
- `process_failed`;
- `response_incomplete`; and
- `response_invalid`.

Provider adapters translate their own native stderr, structured events and exit codes into that contract. The shared bridge returns it losslessly to Python. Unknown failures must remain unknown provider failures; they must not be guessed as authentication failures.

The existing `provider_diagnose_failure` facility can be extended or reused as the owner of provider-native interpretation, but its output must become a stable machine-readable contract rather than human-only log advice. All SPEED consumers should use the same classification contract.

### 2. Use the first uncached real request as the availability gate

Do not add an unconditional synthetic health call.

The cache lookup in `_run_once()` already occurs before provider dispatch. Preserve that behavior. Immediately before the first actual provider dispatch, use a synchronized build-wide state machine:

```text
unknown -> probing -> healthy
                   \-> open

healthy -> recovering -> healthy
                      \-> open
```

Rules:

1. Cache hits return without entering the provider gate.
2. While state is `unknown`, only one thread may send the first uncached real request.
3. Other workers wait; they do not launch concurrent probes.
4. A successful first request changes state to `healthy` and releases normal configured concurrency.
5. An initial provider-scoped authentication, authorization or capability failure changes state directly to `open`.
6. No provider request or token reservation occurs after state becomes `open`.

This tests the actual configured model, authentication, transport and structured-output route without adding a provider-specific ping or violating the requirement that a fully cached build make zero provider calls.

### 3. Apply one controlled mid-build recovery

When a previously healthy provider returns a provider-scoped failure:

1. change state to `recovering`;
2. pause new dispatches;
3. allow one retry of the failed real request;
4. compare normalized failure signatures, not raw log strings;
5. return to `healthy` if the retry succeeds; and
6. change state to `open` if the retry returns the same provider-scoped failure.

A normalized signature should be based on stable fields such as provider identity, category, native status and selected model. Timestamps, log filenames and variable prose must not affect equality.

Packet schema repairs remain separate from provider-health recovery. An invalid semantic response must not trip a provider availability circuit unless the shared provider contract says the transport itself failed.

### 4. Promote an open circuit to terminal attempt status

When the circuit opens, raise a single terminal `PROVIDER_UNAVAILABLE` or more specific terminal provider code from `Synthesis`.

The build must then:

- stop submitting new semantic requests;
- cancel queued work;
- terminate active provider subprocesses through the existing process-group cleanup path;
- prevent further request/token reservations;
- discard the in-memory candidate domain model;
- retain newly extracted deterministic facts;
- preserve the previous published model unchanged;
- set attempt phase to `unavailable` or `failed` according to the normalized category; and
- report the provider failure as the causal error rather than `BUILD_BUDGET`.

Do not reuse the user-cancellation state as the provider circuit state. Otherwise the final cause can be misreported as `CANCELLED`.

Every synthesis, verification, repair and hierarchical-reconciliation path must propagate terminal provider unavailability to the build-wide circuit. No operation may convert it into an unresolved disposition, skip verification or continue toward publication.

### 5. Preserve the correct storage layers

On terminal provider failure:

| Stored or in-memory state | Required action |
| --- | --- |
| Failed provider response | Never cache it |
| In-memory candidate domain model | Discard it |
| Newly extracted deterministic facts | Preserve them |
| Previously published domain model | Preserve it unchanged |
| Previously validated response cache | Preserve it |
| A cache entry that fails validation | Remove or quarantine only that entry |
| Sanitized failure diagnostic | Preserve under bounded retention |

The current implementation writes a response cache only after provider output passes wire-schema, canonical-schema, ID/reference and optional payload validation. A 403/no-final-message failure therefore creates no valid response-cache entry to erase.

Deleting the entire cache on provider failure would be incorrect. It would destroy validated work, make recovery more expensive and cause the next build to call the provider for graph scopes whose exact input/prompt/schema/provider fingerprints have not changed.

### 6. Make retryability honest

Extend `DomainError` so retryability is supplied by the failure policy rather than hardcoded false.

The persisted terminal circuit-open error is non-retryable within the current attempt. A future explicit refresh may try the provider again; the circuit is build-scoped and must not permanently disable the provider.

Status should preserve:

- normalized error category/code;
- whether the triggering request was initial or mid-build;
- number of provider successes before failure;
- number of recovery attempts;
- last stable native status when safe to expose; and
- the bounded diagnostic-log reference.

Do not persist credentials, response bodies or raw sensitive provider output.

### 7. Preserve budget causality

Dispatched requests and retries continue to count against the global budget as required. Once the circuit is open, rejected local dispatches do not count as provider requests and do not reserve tokens.

If a genuine provider-health failure occurred first, the final error remains that provider failure even when the last allowed retry consumed the remaining budget. `BUILD_BUDGET` must not replace the causal provider error.

Ordinary budget exhaustion remains distinct from provider failure, but it is not publishable as a new authoritative domain model. Retain validated reusable work and pending-scope diagnostics for a later explicit refresh while preserving the previous publication.

### 8. Keep the solution DRY and provider agnostic

Provider-native error detection belongs in each existing provider adapter. Provider failure vocabulary, envelope validation and retry semantics belong in the shared provider layer. Build-health state belongs in `Synthesis`. Publication behavior belongs in `discover()`.

Do not add:

- Codex stderr parsing in business-domain Python;
- separate provider transports for domain discovery;
- provider-name branches in the discovery orchestrator;
- a second cache for connection tests; or
- independently implemented retry rules for synthesis, verification, repair or reconciliation.

All synthesis stages must call the same build-wide provider-health gate.

## Required regression tests

### Shared provider contract tests

1. Codex HTTP 401/403 output maps to a provider-scoped authorization category.
2. Claude authentication/capability failures map to the same common categories.
3. Timeout, rate limit, transport failure, process exit, incomplete stream and invalid final JSON remain distinct.
4. Unknown failures remain unknown and retain a diagnostic without guessing authentication.
5. Provider failure envelopes exclude credentials and sensitive payloads.

### Initial-gate tests

1. A build satisfied entirely from response cache performs zero provider calls.
2. With concurrency greater than one, only one first uncached request runs while health is unknown.
3. A successful first request releases normal concurrency.
4. An initial 403 opens the circuit without scheduling another semantic unit.
5. Initial provider failure retains deterministic facts and the previous model.
6. Initial failure with no previous model returns facts plus unavailable synthesis status and no fabricated domain artifact.

### Mid-build recovery tests

1. A transient failure followed by one successful retry resumes processing.
2. A mid-build 403 followed by the same normalized 403 opens the circuit after exactly one retry.
3. No new provider call begins after the circuit opens.
4. Already queued work is cancelled and active subprocesses observe the shutdown signal.
5. Different timestamps or log paths do not make the same normalized error appear different.
6. A request-specific invalid response receives its one schema repair without opening the provider circuit.

### Publication tests

1. Provider circuit opening during synthesis preserves the previous artifact.
2. Provider circuit opening during independent verification or semantic repair preserves the previous artifact.
3. Provider circuit opening during hierarchical root reconciliation preserves the previous artifact.
4. A repeated provider failure cannot become `BUILD_BUDGET` and publish a degraded candidate.
5. The status reports terminal provider causality, correct freshness and correct retryability.
6. Successful response-cache files remain byte-identical after the failed attempt.
7. No cache file is created for the failed response.
8. A subsequent explicit refresh can retry provider health and reuse unaffected validated cache entries.

### Trial-shaped tests

1. A PetClinic-sized anchor inventory with an unavailable provider performs one initial gate attempt, not a request/retry pair per anchor.
2. A Grocery-shaped hierarchical build with some validated cached scopes and a mid-build repeated 403 preserves its previous 24-activity artifact rather than publishing a seven-activity replacement.
3. Neither test labels undispatched anchors as budget-exhausted when provider unavailability was the cause.
4. Both tests complete promptly after the circuit opens rather than waiting for the full build deadline.

## Acceptance criteria

1. Provider failures cross the shared shell/Python boundary through one machine-readable, provider-agnostic contract.
2. Provider-native classification is implemented only in the existing provider adapters/shared provider owner.
3. A fully cached build makes zero provider calls.
4. The first uncached real request gates synthesis fan-out.
5. Initial provider-scoped authorization/capability failure stops the attempt.
6. A previously healthy provider receives at most one controlled recovery retry for the same provider-scoped failure.
7. Repeated equivalent provider failure opens a build-wide circuit.
8. No semantic request is dispatched or budget-reserved after the circuit opens.
9. Synthesis, verification, repair and reconciliation operations propagate terminal provider unavailability consistently.
10. The candidate model is discarded; deterministic facts, validated cache and the previous published model are retained.
11. Provider-caused termination cannot be reclassified as ordinary budget truncation.
12. Status reports the causal provider category, accurate retryability and a bounded diagnostic reference.
13. A later explicit refresh starts with a new build-scoped health state and may recover.
14. No language, framework, SQL dialect or provider-name branch is introduced into business-domain orchestration.

## Non-goals

- Do not claim that every individual provider failure is a service outage.
- Do not stop the build for a single repairable semantic-response schema error.
- Do not introduce a provider-specific health endpoint into business-domain discovery.
- Do not make an unconditional probe when all required responses are cached.
- Do not delete validated response caches because authentication or transport failed.
- Do not publish a partially reviewed candidate after the provider circuit opens.
- Do not suppress honest request/token accounting for calls that were actually dispatched.
- Do not persist a circuit across independent explicit refresh attempts.

## Certainty

Confidence is very high that the retry and publication defect exists.

It is directly established by:

- the generic non-zero-exit mapping in `_speed_call()`;
- the per-call retry counter in `Synthesis.run()`;
- the activity loop's decision to continue after `PROVIDER_FAILED`;
- the grouping path's partial handling of `BUILD_BUDGET`;
- the evidence-review path's non-terminal handling of `PROVIDER_UNAVAILABLE`;
- PetClinic's 185 requests, 89 retries and 88 provider-failed anchors; and
- Grocery's provider failures, induced budget truncation and publication of a less complete current artifact.

Confidence is deliberately lower about the native reason for every failed provider call. The retained logs prove HTTP 403 for specific calls and generic missing-final-message failures for others. The proposed shared classification contract is required precisely because the current implementation discards the information needed to make that distinction reliably.
