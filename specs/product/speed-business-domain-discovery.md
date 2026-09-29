# Business Domain Discovery

Status: Implementation validation; release gates pending
Date: 2026-09-08

> Technical design: [Business Domain Discovery RFC](../tech/speed-business-domain-discovery.md).
> Replaces the business-domain interpretation of [CSG Domain Clustering](speed-csg-clustering.md); structural dependency analysis remains useful supporting infrastructure.
> Format: [PRD template](../../templates/prd.md).

## Problem

When users inspect an unfamiliar repository, Workbench currently presents connected groups of files as business domains, with labels such as `repository/pet` that do not explain the responsibilities those files implement. Users cannot reliably tell what the application does, which business rules govern it, or where those rules are enforced across UI, API, SQL, configuration, external policies and workflows. They must reconstruct that understanding themselves before reviewing behavior or scoping a change, and misleading domain labels can send them to the wrong code.

## Users

| User | Problem to solve |
| --- | --- |
| Developer learning or changing an application | Needs to find the business activity and its implementations without guessing from folder names |
| Maintainer reviewing behavior | Needs to inspect a rule, compare enforcement locations, and identify conflicting or unavailable definitions |
| Technical lead planning work | Needs to understand which responsibilities a change touches, including shared services and workflows |
| Planning/review agent operating on the repository | Needs the same evidenced domain model as the human reader, with explicit uncertainty rather than invented boundaries |

The initial experience serves repository users, not an autonomous enterprise architecture authority. Proposed business boundaries remain open to review.

## User Stories

| ID | Story | Acceptance Criteria | Priority |
| --- | --- | --- | --- |
| PBD-01 | As a developer, I want business areas described through the activities they support, so I can understand what the application does. | Given a supported indexed repository, when I discover domains, then every displayed area has a responsibility description and supported activities, and a technical folder or central symbol alone cannot establish its name or boundary. | Must |
| PBD-02 | As a developer, I want to follow an activity into its implementation, so I can locate relevant code before changing it. | Given an activity, when I inspect its evidence, then I can follow its resolved entry point and supporting implementation to exact source locations; unresolved relationships are shown rather than guessed. | Must |
| PBD-03 | As a maintainer, I want the system to extract business rules explicitly, so important constraints are visible rather than buried in code. | Given a supported rule source, when rules are extracted, then each rule states its conditions, outcome, affected activity and evidence, or identifies which of those could not be established. | Must |
| PBD-04 | As a maintainer, I want to compare UI, API, SQL and configuration rules, so I can see where behavior differs. | Given observations with different scopes or values, when I inspect a rule, then their source locations and enforcement scopes remain visible, defaults are distinguished from effective values, and unresolved differences are not silently merged. | Must |
| PBD-05 | As a maintainer, I want externally loaded rules identified with their versions and availability, so I know which behavior cannot be explained from the repository alone. | Given a call to an external policy source, when discovery runs, then it identifies the delegation and local decision handling; a supplied or authorized definition is versioned, and absent contents or unknown activation remain explicit gaps. | Must |
| PBD-06 | As a lead, I want scheduled and DAG-driven business activities explained, so background processes are included in the application model. | Given a supported workflow definition, when it is analyzed, then business ordering claims are supported by task behavior, branches and trigger rules together; unsupported dynamic behavior is marked unresolved. | Must |
| PBD-07 | As a developer, I want shared implementation shown across business areas, so I do not overlook other responsibilities affected by a change. | Given one service implementing multiple activities, when I inspect its participation, then the relevant methods can support different domains, the file is marked shared, and domain file totals are explicitly non-additive. | Must |
| PBD-08 | As a maintainer, I want to correct domain names and membership, so reviewed understanding survives subsequent discovery. | Given a proposed domain, when I accept, reject, rename, merge, split or adjust membership, then my decision is recorded; later source changes retain compatible identity and flag invalidated or conflicting decisions for review. | Must |
| PBD-09 | As a repository user, I want discovery integrated with digest refresh, so I can use the existing workflow and retain good results if a rebuild fails. | Given the existing digest, when I request digest refresh, then it refreshes business domains within that same operation; reads never invoke synthesis, unchanged-input refreshes reuse valid cached work, oversized graphs use bounded resumable semantic units, and failed/cancelled refreshes preserve readable prior results. | Must |
| PBD-10 | As a reviewer, I want incomplete or stale knowledge clearly identified, so I can judge what the domain map actually establishes. | Given unsupported evidence or capabilities, a published partial model identifies those gaps; given unfinished budget/deadline work, changed inputs or a missing provider, the attempt state identifies the cause, current scope and remaining work while preserving the previous valid model. A zero-activity candidate with a missing or unresolved canonical anchor is an incomplete attempt and is never published as a business-domain model. No unavailable business domains are replaced with structural clusters. | Must |
| PBD-11 | As a lead, I want one consistent domain model across the digest, details and planning, so different parts of Workbench do not use conflicting meanings of domain. | Given a published domain build, when its consumers read it, then they use its business identities and memberships; legacy clusters remain explicitly structural and data from different builds is not silently combined. | Must |
| PBD-12 | As a repository owner, I want discovery to respect source and external-access boundaries, so understanding the application does not expose credentials or execute its code. | Given sensitive files, external references or executable workflow definitions, when discovery runs, then credentials and out-of-root sources are excluded, remote contents require authorized access, and source text cannot trigger execution or change review permissions. | Must |
| PBD-13 | As an operator, I want large or failing discovery runs to be bounded and observable, so I can understand progress, control cost and distinguish repairable model output from provider failure. | Given a refresh that requires semantic work, when it runs, then preflight selects whole-graph or hierarchical execution before dispatch, every request stays within the effective cap, status exposes units/current scope/request/retry/token counters, semantic validation failures receive bounded repair, and a repeated equivalent provider-wide failure stops further dispatch without publishing unfinished work. | Must |

## User Flows

### 1. Understand an unfamiliar repository

Stories: PBD-01, PBD-02, PBD-09, PBD-10, PBD-11.

1. The user opens the repository digest. Existing business domains are shown with their freshness, or the page states that discovery has not run.
2. The user requests digest refresh; business-domain discovery is part of that refresh when inputs are missing or changed. Workbench displays progress while leaving the last valid result readable.
3. The result describes business areas using activities and responsibilities, with rule/evidence details available for inspection.
4. The user selects an activity and follows its implementation evidence.
5. Missing providers or unsupported source types produce an actionable unavailable/partial result, not a convincing-looking substitute.

```text
Open digest → Discover domains → Choose a business area
                                      |
                                      v
                              Inspect an activity
                                      |
                                      v
                            Read rule and source evidence
```

The existing misleading result supplies the motivation: PetClinic's `repository/pet` combines multiple entities, persistence implementations and clinic services; `service/clinic` identifies a group of tests. These observations establish a product problem, not a requirement for one predetermined replacement taxonomy. The RFC records the investigated code and revision.

### 2. Inspect a rule across its sources

Stories: PBD-02, PBD-03, PBD-04, PBD-05, PBD-06, PBD-12.

The following four hypothetical examples define the required kinds of experience. They are not claims about PetClinic and do not imply four separate domains based on technical layers.

| Example | What the user is trying to understand | What Workbench must show |
| --- | --- | --- |
| UI: request a refund | What the form receives, validates, sends and displays, and why a request is blocked | User/context inputs and their bindings; triggering events; field and business validations; API request/response mapping; pending, error and receipt states; separate evidence for server enforcement |
| API: cancel an order | Why shipped orders are rejected | Operation identity, caller/stored inputs, authorization, cancellation guard, writes and response mapping; concurrency and alternate-path gaps, with source evidence |
| SQL: create an invoice | Why an invoice number is rejected as a duplicate | Schema/constraint identity, input-to-column mappings, uniqueness/null semantics, write and error handling; distinguish migration, applied snapshot and committed execution |
| DAG: release a supplier payment | Whether payment requires approval | Workflow/task identity, start conditions, payment-ID lineage, approval predicate, task outcomes and trigger rule; retries, external-effect uncertainty and definition-versus-run evidence |

1. The user opens a rule within an activity.
2. Workbench lists the source observations separately: where it is declared, where it is enforced, and which environment/version or execution path applies.
3. The user opens the exact evidence for a condition or outcome.
4. If a UI allows 30 days while an API's repository configuration defaults to 14, Workbench shows a potential mismatch under that default. If production can override the value externally, the deployed limit remains unknown until supported evidence is available.
5. If an external definition cannot be read, Workbench explains the delegation and the unavailable definition. It does not invent its contents or request broad access automatically.

```text
Business rule
     |
     +-- UI check -------- browser scope
     +-- API check ------- request path
     +-- SQL constraint -- database/schema scope
     +-- Config/policy --- selected value and revision, or unknown
     +-- Workflow -------- branch and execution conditions
```

Not every rule appears in every location. Matching words or values do not establish that two observations are the same rule.

### 3. Scope a change that touches shared code

Stories: PBD-01, PBD-02, PBD-03, PBD-07, PBD-11.

1. The user selects a business activity that will change.
2. Workbench shows its supporting methods, rules and data, with other participating domains identified where evidenced.
3. The user inspects a shared service file and sees which methods support which activities, rather than receiving one exclusive file-level domain assignment.
4. Planning consumes the same memberships and uncertainty. Structural dependency analysis remains separately available for assessing code coupling.
5. If a path is unresolved, the proposed change scope is explicitly incomplete rather than advertised as exhaustive impact analysis.

### 4. Correct a proposal and revisit it after change

Stories: PBD-08, PBD-09, PBD-10, PBD-11.

1. The maintainer inspects why activities were grouped and any alternative boundaries.
2. They accept, reject or revise the proposal, recording the decision against that build.
3. A later refresh preserves compatible identities and decisions; a display-name change alone does not create a different domain.
4. Changed supporting evidence marks the decision for renewed review. Splits and merges retain lineage.
5. A review submitted against an older build fails with a visible conflict instead of modifying the new result silently.

### 5. Recover from missing information or failed discovery

Stories: PBD-05, PBD-09, PBD-10, PBD-12, PBD-13.

1. A build encounters an unavailable provider, inaccessible external policy, unsupported DAG construct, budget limit or cancellation.
2. Workbench preserves the prior valid domain result, if any, and exposes the latest attempt's outcome separately.
3. A valid partial model may identify explicit evidence, capability or support gaps only after the declared scope was completely processed. Budget- or deadline-pending work remains attempt state and is never published as the repository model.
4. The user can refresh after inputs or capabilities change. Merely reopening the page does not start a model call or execute the target application.

### 6. Run bounded discovery on a large repository

Stories: PBD-09, PBD-10, PBD-13.

1. Before the first semantic request, Workbench estimates the complete synthesis, verification, repair and reconciliation sequence against configured build limits and the selected provider's declared limits.
2. If the complete sequence fits, Workbench uses one whole-graph candidate. Otherwise it creates deterministic semantic units from complete entry-point trace closures and exposes their total, current scope and validated/pending counts.
3. A shape-valid but semantically inconsistent response is rejected before mutation and receives only the bounded repair/reverification allowed for that scope. The status distinguishes this from authentication, rate limiting, transport failure and budget exhaustion.
4. Validated unit results are reusable after interruption. No unit prefix becomes the current repository model until required root reconciliation and verification account for the declared scope.
5. A repeated equivalent provider-wide failure opens one build-scoped circuit, stops new requests and preserves facts, validated cache entries and the previous published model.

## Success Criteria

These are proposed release gates, not measurements of current capability. Evaluate on at least three reviewed repositories: PetClinic, a business-oriented package layout, and a technical/shared-service layout; at least one has no UI. Source-specific fixtures cover all four examples and configuration/external variants. Missing adapters cannot be counted as completed coverage for their release scope.

- [ ] **SC-01 — Useful business coverage:** At least 90% activity precision and 80% recall against a reviewed activity inventory, with zero critical false-boundary claims in the PetClinic regression cases. Accept documented alternative groupings rather than requiring exact generated names. Stories: PBD-01.
- [ ] **SC-02 — Traceable evidence:** 100% of displayed evidence references resolve to the recorded source version, and every implementation claim in the curated fixtures has a valid trace or an explicit unresolved status. Stories: PBD-02.
- [ ] **SC-03 — Explicit rules:** Every positive rule fixture yields the expected condition, outcome, scope and evidence; negative fixtures do not produce unsupported rules. Measure rule precision/recall by category and require zero unsupported production-rule claims in the curated regression set. Stories: PBD-03.
- [ ] **SC-04 — Scope and conflicts preserved:** Every curated UI/API/SQL/config conflict and override case retains distinct observations and the expected unknowns; zero cases silently substitute a default for an unverified effective value. Stories: PBD-04.
- [ ] **SC-05 — External truthfulness:** Every external-policy fixture distinguishes reference, available definition, revision and activation evidence; no absent definition is fabricated and a snapshot change invalidates dependent results at unchanged Git HEAD. Stories: PBD-05.
- [ ] **SC-06 — Workflow truthfulness:** Every curated DAG case preserves branch/trigger semantics; changing a success-required trigger to a failure-tolerant one cannot leave an unsupported approval prerequisite asserted. Unsupported dynamic behavior is explicit. Stories: PBD-06.
- [ ] **SC-07 — Shared participation:** All shared-service fixtures retain their distinct method/activity memberships and mark shared files; domain counts never imply exclusive repository coverage. Stories: PBD-07.
- [ ] **SC-08 — Review continuity:** All rename, merge, split, changed-evidence and stale-review fixtures preserve the specified identity/history or return an explicit conflict; synthesis never grants human acceptance. Stories: PBD-08.
- [ ] **SC-09 — Safe existing workflow:** Reads and unchanged-input refreshes make zero semantic-provider calls; changed-input refreshes run bounded discovery; duplicate, failed, superseded and cancelled builds never corrupt the last valid result. Discovery is part of the existing digest refresh CLI/API, with no extra enable flag. Stories: PBD-09.
- [ ] **SC-10 — Honest completeness:** Every published model accounts for 100% of canonical anchors. Before returning, synthesis inspects every anchor and attempts semantic synthesis from its supplied evidence. A zero-activity candidate passes only when every anchor is independently excluded with subject-specific evidence and no supplied evidence describes business behavior. Missing, unresolved or evidence-free anchor dispositions fail deterministically; generic or irrelevant explanations fail independent semantic verification. Pending semantic work remains visible only in attempt status and never publishes a new model. Stories: PBD-10.
- [ ] **SC-11 — One model:** All migrated domain consumers use canonical business IDs and memberships; cross-build reads conflict explicitly and legacy artifacts are identified as structural. Stories: PBD-11.
- [ ] **SC-12 — Controlled access:** All credential, symlink, hostile-source, unauthorized-external and executable-DAG fixtures prevent the prohibited exposure/action. Stories: PBD-12.
- [ ] **SC-13 — Bounded, observable execution:** Whole-graph, oversized-graph, interruption, semantic-repair and provider-failure fixtures prove that every dispatched request is within its effective cap; provider transport accepts every payload permitted by that cap without a smaller undocumented local ceiling; status reports the selected mode, active scope, units, requests, retries, token reservations/usage and causal error; repeated equivalent provider failure stops build-wide fan-out; and hierarchical publication occurs only after verified root reconciliation. Stories: PBD-09, PBD-10, PBD-13.

“Critical false-boundary claim” means the result asserts that a responsibility is covered while omitting known material activities/rules, or assigns unrelated behavior solely because of a technical grouping. Reviewers record the supporting counterexample; automated checks validate the recorded evaluation outcome. Mechanical citation validity alone cannot establish business correctness.

No measured productivity/time-saving claim is made yet. The first release must establish truthful, inspectable results before a separate user study can quantify onboarding or change-planning improvements.

### Release readiness

Resolved defect specifications and passing deterministic tests are implementation evidence, not proof that these product success criteria are met. Release remains blocked until the integrated CLI/API/UI workflow and opt-in real-provider evaluation pass on the declared repository corpus. In particular, a successful PetClinic build must produce a valid canonical artifact and useful reviewed activities; completing requests, reducing retries or satisfying JSON shape alone is insufficient.

The implementation must therefore report these states separately:

| Gate | Evidence required |
| --- | --- |
| Contract and deterministic behavior | Artifact conformance, negative fixtures, migration, failure, cache and consumer tests pass together |
| Provider compatibility | At least one full uncached build and one unchanged-input cache build complete for every advertised provider/model profile |
| Semantic quality | Reviewed PetClinic and comparison-repository outputs satisfy SC-01 through SC-07 and SC-10 |
| Product workflow | CLI and dashboard expose the same published build, progress, failure and evidence-navigation behavior |
| Release decision | Every applicable success criterion is recorded as passed; unresolved advertised-source gaps block that coverage claim |

## Scope

The RFC delivers a responsibility map, activity explanations with inputs/outputs/effects, information-use and proposed-ownership records, a scoped rule inventory, interactions, evidence and review/freshness status through one authoritative model. See the [artifact contracts](../tech/contracts/business-domain-artifacts.md) for exact proposed shapes.

### In Scope

- Replace the existing cluster-as-business-domain interpretation with one authoritative business-domain model.
- Identify activities and extract business rules with their supporting evidence, shared implementations, boundary explanations and uncertainties.
- Handle UI, API, SQL, configuration, external policy/data and workflow/DAG observations through explicit supported-source capabilities.
- Model business activities and service boundaries independently of language/framework, including calls between services implemented in different stacks. Java/Spring and TypeScript/React are the initial adapter delivery scope, not product-model restrictions; declare SQL/configuration, workflow/policy and additional language coverage by tested adapter/version rather than presuming universal extraction.
- Identify unsupported external/workflow sources from the start; ship full extraction for each source only after its conformance criteria pass. Full source coverage remains a product requirement, not something reference-only detection satisfies.
- Let users inspect and correct proposals; preserve review history and report invalidated evidence.
- Integrate with existing digest refresh, evidence navigation and domain-aware planning consumers.
- Preflight and execute semantic work with explicit request/build limits, resumable validated units, root reconciliation, bounded repair and build-scoped provider failure containment.
- Retain useful structural code analysis under accurate structural terminology.

### Out of Scope (and why)

- Automatic microservice, deployment or team boundaries: these require organizational/runtime decisions that a repository does not establish.
- Automatic code refactoring or moving files: this feature provides understanding and evidence, not changes to the target system.
- Executing target applications, migrations or arbitrary DAG construction during ordinary discovery: those operations can have side effects and exceed a read-only understanding workflow.
- Unrestricted remote policy harvesting: external definitions require authorized access and versioned evidence.
- Guaranteeing the complete behavior of a deployed system from source alone: runtime configuration, dynamic code and unavailable external rules can remain unknown.
- Treating a UML diagram or folder map as a finished business-domain model: those describe supporting structure, not business responsibility.
- A new standalone domains CLI/product surface: discovery belongs to the existing digest workflow.

## Dependencies

- Existing repository indexing, symbol extraction and structural relationships, enhanced where resolution is inadequate.
- Existing digest persistence, refresh execution, GraphQL and evidence UI; their business-domain contracts require migration.
- Configured synthesis provider for business interpretation, with declared context/output capabilities, structured output, request transport that supports the configured cap, and explicit unavailable behavior when missing.
- Source-specific adapters and versioned fixtures for the advertised Java, frontend, SQL, policy/config and DAG capabilities.
- Maintainer-reviewed activities, rules and acceptable boundary alternatives for evaluation.
- Explicitly authorized external connections or supplied snapshots where necessary to inspect policy definitions.

The current [RFC](../tech/speed-business-domain-discovery.md) is the single review document for this proposal. Implementation sizing may justify child RFCs later; no unwritten child RFC is a prerequisite for understanding these requirements.

## Security & Controls

- Use the server-selected project root for viewing, discovering and reviewing domains. The current local dashboard does not establish per-user authorization; shared deployments require authentication and project authorization before exposing these operations.
- Exclude credentials and out-of-root files; bound source excerpts and restrict exposure to the selected project.
- Send evidence only through the configured provider under existing permissions. Repository content is data, not authority to execute instructions.
- Read external contents only through an authorized connection or supplied export. Preserve revision and freshness limitations.
- Never execute arbitrary source, SQL migrations or DAG definitions to satisfy a normal discovery request.
- Record reviewer identity, operation, time and build revision. Distinguish user acceptance from model inference.
- Limit build concurrency and synthesis resource consumption; preserve previous readable results on failure.
- Keep large provider request bodies out of process arguments and other observable command metadata; use bounded protected transport and never persist raw prompts in diagnostics.

## Risks

| Risk | Severity | Mitigation |
| --- | --- | --- |
| Plausible names hide unsupported business meaning | Critical | Activity/rule evidence, negative fixtures, boundary review and explicit uncertainty |
| One enforcement location is mistaken for universal behavior | Critical | Source observations, scope comparison and unresolved external/config state |
| Shared code is assigned exclusively and hides change impact | High | Method/activity participation and shared-file reporting |
| Rule definitions change outside Git | High | Versioned snapshots, freshness dependencies and unknown deployed-state labels |
| A broad capability claim hides unsupported SQL/DAG/policy constructs | High | Tested source/version matrix, source-level coverage and staged release claims |
| Model cost and review effort outweigh the benefit | Medium | Bounded explicit builds, cache reuse and separate evidence-quality versus productivity measurement |
| Migration makes different screens/planners disagree | High | Canonical model, coordinated consumer cutover and cross-build consistency tests |
| Sensitive content or executable definitions escape read-only analysis | Critical | Existing access controls, bounded readers, authorized snapshots and shared SPEED provider permissions; document provider isolation limits |
| Large requests exceed a model, local transport or rate limit and waste quota through fan-out | High | Conservative preflight, explicit effective caps, bounded concurrency, completion reserves, reusable unit cache, build-scoped provider circuit and causal telemetry |
| Shape-valid model output contains inconsistent or unsupported references | Critical | Validate before mutation, bounded targeted repair, independent semantic verification and no publication before root reconciliation |

## Open Questions

| Question | Decision blocked | Owner / resolution path |
| --- | --- | --- |
| Which SQL dialects, policy formats and workflow versions are required for the first release? | Initial advertised coverage | Product owner and maintainer select representative target repositories; engineering publishes a tested support matrix |
| Who owns the reviewed activity/rule inventory and boundary adjudication? | Semantic release evaluation | Maintainer/product owner nominates domain reviewers and records accepted alternatives before scoring |
| How much source/snapshot retention is acceptable for target repositories? | Evidence/cache retention defaults | Repository owners and engineering define retention within existing storage controls |
| What user-effort baseline should a later productivity study measure? | Quantified onboarding/change-planning benefit | Observe users answering fixed activity/rule questions before and after; do not invent improvement percentages |
| Which provider/model profiles and default request/concurrency caps meet the release time, quality and cost envelope? | Advertised provider profiles and production defaults | Run the complete uncached/cache-hit corpus, record actual input/output, latency, repair and failure rates, and publish the selected profile rather than inferring it from context-window size |

These questions do not reopen the agreed requirements for explicit rule extraction, all four example types, one authoritative model or the existing digest command. Implementation may continue through validation, but release remains blocked until the applicable success criteria and provider/repository profiles are evidenced.
