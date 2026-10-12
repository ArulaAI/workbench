# Defect: TypeScript in-process state has no data access, so full discovery cannot cite where information lives

Severity: P1
Related Feature: speed-business-domain-discovery
Status: Resolved
Related Defects: business-domain-typescript-declared-receiver-types, business-domain-typescript-evidence-gaps
Tags: typescript, data-access, effects, information-uses, verification, trace-boundaries

## Summary

Full discovery on the Payments Validation Fixtures repository failed with `SEMANTIC_VERIFICATION_FAILED` after four repair rounds. The last blocking finding was the same in every round:

> Every information use cites a global runtime-boundary resource that is outside its activity's operation closure. These resources are Map get/set, Array push/reduce/filter/find.

The service keeps its records in process memory: payments in `PaymentsService.payments` (a `Map`), ledger entries in `Ledger.entries` (an array), velocity counts in `RiskRules.attempts`. Extraction recorded every access to them as a platform `calls` edge. `information_use_closure` accepts only resources a `reads_data` or `writes_data` edge reaches, so the model had nothing valid to cite. It also left the published facts with zero effects, which the verifier flagged as overstated certainty.

Classifying these calls as platform calls (business-domain-typescript-declared-receiver-types) made them more visible to the model, but the gap was older than that change.

## Resolution

1. **A collection held as shared state is a store.** `ts_types.store_access` reports a call as a store access when its receiver is a `Map`, `Set`, `WeakMap`, `WeakSet` or array that lives in one of three places. It must also be a collection some code in the repository writes; one nothing changes is reference data.

   | Where the collection lives | Store resource |
   | --- | --- |
   | A class member | `src/payments/service.ts::PaymentsService.payments` |
   | A module-level binding, or a member of a module-level object | `src/vault.ts::store`, `src/obs/index.ts::sinks.logs` |
   | A member of a declared record type | `src/payments/service.ts::Payment.captures` |

   A collection a parameter or a fresh local holds is not shared state and stays a platform call. A local bound to shared state (`const entries = this.entries`) still names the store.

2. **Store accesses are data operations.** `ts_semantic.operations` emits a `data_write` for `set`, `delete`, `clear`, `add`, `push`, `pop`, `shift`, `unshift`, `splice`, `sort`, `reverse`, `fill` and `copyWithin`, and for `store.length = n`. It emits a `data_read` for the reading methods (`get`, `has`, `filter`, `find`, `reduce` and the rest). Each targets one `memory_store` resource, so every activity that touches the same state cites the same resource. `ts_semantic.calls` drops the platform call edge for the same span. A write is an effect.

3. **In-process writes are a stated boundary.** A static data write must stay unresolved until its completion is established. Store writes carry `TS_IN_PROCESS_STATE`, which `trace_boundaries.json` classifies as the new `in_process_state` boundary: the write completes when the call returns and does not survive the process. Traces that write state are bounded, not incomplete.

4. **Contracts and guidance.** Both artifact schemas add the `memory_store` resource kind and the `in_process_state` boundary kind. The TypeScript adapter declares `data_access = "partial"` and the new diagnostic code. The synthesis and verification agent definitions, runtime and normative alike, state that an information use cites only resources its activity's data edges reach, never a platform call resource, and that a `memory_store` is in-process state, never persisted or durable.

5. **Summary.** `--facts-only` adds a "Data on traces" section listing each store with its reads and writes, and "Writes to in-process memory" appears among the places traces end.

## Effect on the fixture (`--facts-only`)

| Measurement | Before | After |
| --- | --- | --- |
| Stores (`memory_store` resources) | 0 | 11 |
| Data edges (reads / writes) | 0 / 0 | 24 / 15 |
| Effects | 0 | 19 |
| Traces complete / bounded / incomplete | 1 / 11 / 0 | 2 / 10 / 0 |
| Unresolved call sites on traces | 0 | 0 |

The constant lookup tables `PAN_FIELDS`, `ALLOWLIST_BINS`, `SKIP`, `SANITISERS` and `SOURCES` are never written and remain platform calls. PetClinic has no stores; its facts are unchanged except one more call classified (`owner.pets.map(...).join`).

## Effect on full discovery

| Run | Outcome |
| --- | --- |
| Before | `failed`: four repair rounds, the information-use finding blocking every round; nothing published |
| After | verification `pass` after one repair round (4 provider requests, 36 minutes); published as `partial` |

The published model has 3 domains, 10 activities, 16 rules, 33 information uses citing `memory_store` resources, 7 ownerships and 19 effects; all 23 claims have semantic review `supported`. It is `partial`, not `complete`, because `publication_status` requires every trace resolved and every adapter capability supported: ten traces end at stated platform and in-process boundaries, and the TypeScript adapter declares capabilities such as `overload_resolution` unsupported. That is the expected publication state for this repository under the current specification.

## Acceptance tests

`tests/test_business_domain_typescript_memory_stores.py` (7 tests) covers member, module and record stores, clearing and truncation, the effect and the bounded trace with its stated assumption, reference data and local collections staying platform calls, and an information use citing a store passing `information_use_closure`. Tests that asserted platform-call reasons for store accesses now assert the data edges.
