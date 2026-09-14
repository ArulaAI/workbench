# Petclinic whole-graph synthesis collapses distinct capabilities

Severity: P0

Related feature: `speed-business-domain-discovery`

Status: Open

Tags: business-domains, whole-graph, synthesis, verification, repair, petclinic

## Summary

`speed digest --refresh` first extracts a deterministic source-facts graph. It
then sends that graph through semantic synthesis, independent semantic
verification and bounded repair.

For Spring Petclinic, deterministic extraction retained 52 canonical entry
points. The synthesis candidate assigned all 52 entry points to one activity,
`Manage pet clinic records`, but cited only the implementation trace for
`GET /pets/{petId}`. Verification rejected the candidate. Four repair calls did
not produce a publishable replacement, so SPEED correctly published no
`business-domains.json`.

The primary defect is in the LLM path: synthesis and repair did not preserve the
distinct business outcomes already present in the supplied facts. Separate
non-LLM extraction, retention and digest-reporting issues also exist, but the
retained evidence does not prove that they caused the false merge.

## Core failures and ownership

The labels identify the executing path, not a proven root cause:

- **LLM**: The value or judgment came from a synthesis, verification or repair
  provider call. This can still expose a prompt, projection or orchestration
  defect; it does not prove that the model alone is at fault.
- **Non-LLM**: Deterministic extraction, validation, persistence, status or
  projection code owns the behavior.

The production boundary is explicit:

| Artifact or operation | Producer |
| --- | --- |
| `business-domain-facts.json` and `business-domain-snapshots/*` | Non-LLM extraction |
| `synthesize`, `verify` and `repair` candidate/report values | LLM provider calls |
| `business-domain-cache/*` | Non-LLM persistence of LLM request/response exchanges |
| `business-domain-status.json` | Non-LLM orchestration |
| `business-domains.json` | Non-LLM publication after deterministic and LLM verification pass |
| Business fields in `repository-digest.json` | Non-LLM projection from the published model and latest status |

### Non-LLM failures — fix first

| ID | Finding | Files touched | Type | Consequence |
| --- | --- | --- | --- | --- |
| F1 | The known Petclinic fixture emitted 26 generic `SOURCE_CAPABILITY_UNAVAILABLE` warnings. Duplicate extension ownership misclassified `.properties` as `ini`; application-property facts were dropped, unrelated assets were warned, and coverage still reported zero unsupported source IDs. | Code: `lib/context/business_domain_extract.py`, `lib/context/business_domain_adapters/__init__.py`, `lib/context/language_registry.py`, `lib/context/project_map.py`, `lib/context/data/languages.toml`, `lib/context/data/extraction.toml`<br>Artifact: `.speed/context/business-domain-facts.json`<br>Detail: `F1-business-domain-source-capability-warnings-hide-dropped-configuration.md` | Deterministic classification, source-selection, extraction and diagnostic defect; not a demonstrated cause of the merge | Security and runtime configuration is missing, while irrelevant assets produce unactionable warning noise. Petclinic should have zero source-capability warnings after explicit ownership and dispositions are installed. |
| F2 | Only 15 of 52 deterministic traces resolved; 36 were unresolved and one was ambiguous. Of 776 trace obligations, 201 were unresolved and seven were ambiguous. | Code: `lib/context/business_domain_extract.py`<br>Artifact: `.speed/context/business-domain-facts.json` | Input limitation; not a demonstrated cause of the merge | The semantic request contained explicit implementation uncertainty. |
| F3 | Coverage reported 2,065 resolved, 2,602 unresolved and 18 ambiguous relationships. | Code: `lib/context/business_domain_extract.py`<br>Artifact: `.speed/context/business-domain-facts.json` | Input limitation; not a demonstrated cause of the merge | Many structural relationships could not support strong claims. |
| F11 | The current cache retained the initial synthesis request, initial verification request and initial verification response, but no canonical repair request, repair candidate or per-round finding artifact. | Code: `lib/context/business_domain_synthesis.py`<br>Artifacts: `.speed/context/business-domain-cache/*`, `.speed/context/business-domain-status.json` | Persistence defect | The terminal repair sequence cannot be reconstructed from the contracted domain artifacts. |
| F13 | `repository-digest.json` reports `status: partial` and domain discovery `phase: failed`, but its `gaps` array is empty. | Code: `lib/context/business_domains.py`, `lib/context/repository_digest.py`<br>Artifacts: `.speed/context/business-domain-status.json`, `.speed/context/repository-digest.json` | Projection defect | A digest consumer cannot discover the missing business result from `gaps`. |

Recommended sequence: F1 → F2 → F3 → F11 → F13. Re-extract after each of
F1-F3 because an earlier extraction fix may reduce later unresolved counts.

### LLM-path failures — defer until the non-LLM graph is repaired

| ID | Finding | Files touched | Type | Consequence |
| --- | --- | --- | --- | --- |
| F4 | Synthesis merged all 52 anchors into one `Manage pet clinic records` activity. | Code: `lib/context/business_domain_synthesis.py`<br>Artifact: `.speed/context/business-domain-cache/3a56277515a687dc96ee691bc88cb2e57b0dcc5f4a6bd7aeb7a1a0885426f0f0.json` | Synthesis defect | Distinct owner, pet, visit, veterinarian, specialty, pet-type and user outcomes disappeared. |
| F5 | The merged activity cited only the `GET /pets/{petId}` trace. | Code: `lib/context/business_domain_synthesis.py`<br>Artifact: `.speed/context/business-domain-cache/3a56277515a687dc96ee691bc88cb2e57b0dcc5f4a6bd7aeb7a1a0885426f0f0.json` | Evidence-selection defect | One pet-read execution path was used as support for application-wide behavior. |
| F6 | The provider candidate supplied no information uses, rules, ownerships or relationships. Its chosen trace also produced zero deterministic effect/input/output closure. | Code: `lib/context/business_domain_synthesis.py`, `lib/context/business_domains.py`<br>Artifacts: `.speed/context/business-domain-cache/3a56277515a687dc96ee691bc88cb2e57b0dcc5f4a6bd7aeb7a1a0885426f0f0.json`, `.speed/context/business-domain-facts.json` | Derived candidate defect; not a separate extraction failure | The umbrella claim had no record-level explanation of inputs, outputs, changes, policy or responsibility. |
| F7 | The candidate omitted dispositions for three required anchor-correspondence subjects. | Code: `lib/context/business_domain_synthesis.py`, `lib/context/business_domain_schema.py`<br>Artifact: `.speed/context/business-domain-cache/3a56277515a687dc96ee691bc88cb2e57b0dcc5f4a6bd7aeb7a1a0885426f0f0.json` | Candidate-coverage defect caught by non-LLM validation | The candidate did not cover the complete whole-graph scope. |
| F8 | The candidate marked all 52 anchors `represented` while its sole activity was `implementation_unresolved` with `partial` support. | Code: `lib/context/business_domain_synthesis.py`<br>Artifact: `.speed/context/business-domain-cache/3a56277515a687dc96ee691bc88cb2e57b0dcc5f4a6bd7aeb7a1a0885426f0f0.json` | Certainty defect | Coverage certainty contradicted the attached implementation support. |
| F10 | Four provider repair calls did not produce a passing candidate. | Code: `lib/context/business_domain_synthesis.py`<br>Artifact: `.speed/context/business-domain-status.json` | Repair-path defect; exact root cause unresolved | The bounded repair chain exhausted its configured limit. |

### Non-LLM controls that are working

These are not failures and are excluded from the repair queue.

| ID | Working behavior | Files touched |
| --- | --- | --- |
| F9 | `candidate_scope_findings()` reported `INVALID_COVERAGE` for the three missing correspondence dispositions before the independent verifier ran. | Code: `lib/context/business_domain_schema.py`, `lib/context/business_domain_synthesis.py`<br>Artifact: `.speed/context/business-domain-cache/3a56277515a687dc96ee691bc88cb2e57b0dcc5f4a6bd7aeb7a1a0885426f0f0.json` |
| F12 | Publication rejected the failed candidate and left `business-domains.json` absent. | Code: `lib/context/business_domains.py`<br>Artifacts: `.speed/context/business-domain-status.json`, absent `.speed/context/business-domains.json` |

## Concrete Petclinic example

**Executed evidence:** retained artifacts from
`/Users/sanjay/Documents/code/tmp/spring-petclinic-reactjs` at Git commit
`77db261c615f30431014f431d5525ddf4ba770df`.

The deterministic facts contain these separate operations:

| Business outcome | Contract operation | Implementation |
| --- | --- | --- |
| Retrieve one pet | `GET /pets/{petId}`; `operationId: getPet` | `PetRestController.getPet` |
| Record a visit | `POST /owners/{ownerId}/pets/{petId}/visits`; `operationId: addVisitToOwner` | `OwnerRestController.addVisitToOwner` |
| List veterinarian specialties | `GET /specialties`; `operationId: listSpecialties` | `SpecialtyRestController.listSpecialties` |
| Create an application user | `POST /users`; `operationId: addUser` | `UserRestController.addUser` |

The actual pipeline result was:

```text
NON-LLM extraction
  52 canonical anchors
  52 traces
  10 effects
  760 bindings
  268 rule observations
        |
        v
LLM synthesis
  1 activity: Manage pet clinic records
  52 activity anchors
  1 trace: GET /pets/{petId}
  0 information uses, rules, ownerships or relationships
        |
        v
NON-LLM candidate checks
  INVALID_COVERAGE for 3 missing correspondence dispositions
        |
        v
LLM independent verification
  fail: missing_activity, incorrect_merge,
        unsupported_claim, overstated_certainty
        |
        v
LLM repair x4
  no passing replacement
        |
        v
NON-LLM publication
  no business-domains.json
```

The only cited trace was:

```text
OpenAPI GET /pets/{petId}
  -> PetRestController.getPet(Integer)
  -> ClinicService.findPetById(int)
  -> PetMapper.toPetDto(Pet)
```

That trace does not execute `addVisitToOwner`, `listSpecialties` or `addUser`.

## Actual and expected behavior

| Boundary | Actual | Expected |
| --- | --- | --- |
| Deterministic facts | Separate operations and traces are retained, with explicit unresolved work. | Preserve facts and uncertainty without inventing business boundaries. |
| LLM synthesis | One activity claims all 52 anchors using one pet-read trace. | Keep materially distinct outcomes separate unless evidence supports one indivisible activity. |
| Deterministic validation | Finds the three missing dispositions. | Continue rejecting objective coverage, reference and schema defects. |
| LLM verification | Rejects the merge and unsupported certainty. | Check every required subject and return actionable semantic findings. |
| LLM repair | Four calls fail to produce a passing replacement. | Correct the exact prior candidate and current complete finding set. |
| Non-LLM retention | Does not retain the repair sequence for this failed run. | Retain each rejected repair candidate and its findings as attempt evidence. |
| Non-LLM publication | Publishes nothing. | Continue to publish only a candidate that passes both validation boundaries. |
| Non-LLM digest projection | Shows failed/partial status with `gaps: []`. | Expose the terminal domain-discovery gap to digest consumers. |

The expected number of activities or domains is intentionally unspecified.
Related CRUD operations may share an activity when their evidence supports one
business outcome. The four operations above cannot be represented by the
`getPet` trace alone.

## Required behavior

### Non-LLM path — fix first

1. Extraction must keep unsupported parsing and unresolved relationships
   explicit in `business-domain-facts.json`.
2. Deterministic validation must continue to reject incomplete dispositions,
   broken references and unsupported evidence before publication.
3. Failed repair rounds must be inspectable through contracted cache/status
   artifacts with candidate identity, findings and parent-candidate identity.
4. Publication must remain fail closed.
5. `repository-digest.json` must expose failed or pending domain discovery as an
   actionable gap.

### LLM path — defer

1. Synthesis must account for every required whole-graph subject.
2. Each proposed activity must cite traces compatible with every material
   outcome it claims.
3. Synthesis must not use one pet-read trace to represent visit, specialty or
   user-management behavior.
4. Repair must receive the exact preceding candidate, deterministic findings
   and independent verification report.
5. Each repair must correct the supplied defects without dropping unrelated
   valid records.

## Acceptance tests

### Petclinic end-to-end

Preconditions:

- Repository: `/Users/sanjay/Documents/code/tmp/spring-petclinic-reactjs`
- Commit: `77db261c615f30431014f431d5525ddf4ba770df`
- Provider and model configuration retained with the result
- Clean domain publication/cache fixture, or a documented resume fixture

```sh
cd /Users/sanjay/Documents/code/tmp/spring-petclinic-reactjs
/Users/sanjay/Documents/code/workbench-prs/speed digest --refresh --json
```

This command was not rerun while rewriting this defect. The retained artifacts
do not record the original shell command.

The run passes only when:

- every canonical anchor and required correspondence subject has exactly one
  disposition;
- no activity uses `GET /pets/{petId}` as its sole support while claiming visit,
  specialty or user outcomes;
- deterministic validation has no findings;
- independent semantic verification passes;
- `business-domains.json` is published atomically; and
- an unchanged second run reuses the verified result and produces the same
  canonical model.

### Focused collapsed-capability regression

Use a whole-graph fixture with the four operations above.

```text
Candidate A
  activities: [Manage pet clinic records]
  anchors: [getPet, addVisitToOwner, listSpecialties, addUser]
  traces: [getPet trace]
```

Candidate A must fail semantic verification for an incorrect merge and
unsupported claim. A replacement may group operations only when every grouped
outcome has compatible evidence and every required subject has one disposition.

### Deterministic boundary regression

```text
Required subjects: 52 anchors + 3 unresolved correspondences
Candidate dispositions: 52 anchors only
```

`candidate_scope_findings()` must return `INVALID_COVERAGE` naming the three
missing correspondence IDs. Publication must not occur. This test must not
depend on an LLM response.

### Failed-repair retention regression

Configure four non-passing repair responses. After failure, contracted domain
artifacts must allow an engineer to reconstruct:

```text
initial candidate
  -> initial deterministic findings + verifier report
  -> repair 1 candidate + findings
  -> repair 2 candidate + findings
  -> repair 3 candidate + findings
  -> repair 4 candidate + final findings
```

No rejected candidate may be published as `business-domains.json`.

## Verified evidence and limitations

| Evidence | Verified state |
| --- | --- |
| `business-domain-facts.json` | 52 anchors, 52 traces, 10 effects, 760 bindings and 268 rule observations |
| Trace resolution | 15 resolved, 36 unresolved and one ambiguous |
| Initial candidate | Retained in the current run's verification request |
| Deterministic candidate finding | `INVALID_COVERAGE` names three missing correspondence subjects |
| Independent verification | Failed with four blocking findings |
| Attempt status | Failed after four repair attempts; six provider requests total |
| Repair candidates and per-round findings | Not retained as current-run `CacheArtifact` records |
| `business-domains.json` | Absent |
| `repository-digest.json` | `status: partial`, domain `phase: failed`, `gaps: []` |

The evidence proves the initial false merge, deterministic scope failure,
semantic rejection, repair-limit exhaustion, missing repair audit trail and
empty digest gaps. It does not establish whether prompt wording, provider
behavior, provider projection, repair normalization or their interaction caused
the repair failure. It also does not establish that F1-F3 caused F4-F8.
