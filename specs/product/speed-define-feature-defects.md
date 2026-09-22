# Define Feature: Evidence-to-Defect Intake

> Extends [The Define Ceremony](speed-define-ceremony.md) and [Dashboard Outcome Review](speed-dashboard-outcome-review.md). Created defects enter the existing [Defect Pipeline](speed-defects.md).
> See [design spec](../design/speed-define-feature-defects.md) for the dashboard interaction contract and [technical spec](../tech/speed-define-feature-defects.md) for implementation details.

## Problem

Diagnose, Review, and Eval produce evidence about risks and incomplete behavior, but the evidence remains split across pipeline artifacts and does not become actionable follow-up work. Teams must manually reinterpret the outputs, decide whether each item is a current-feature fix or a deferred defect, and rewrite the same evidence into a defect report, losing provenance and often creating duplicates. After defects are filed, product and engineering managers also lack a single report that shows the complete defect inventory grouped and filtered by the features those defects affect.

## Users

### Feature Owner

Decides whether a completed feature is ready to ship. Needs one place to resolve every material finding without treating every warning as a product bug or allowing deferred failures to disappear.

### Engineer

Needs the exact code, test, command, build, and reviewer evidence behind a finding. Wants defects created from that evidence to be reproducible and specific enough for the Triage Agent to investigate.

### Product Manager

Decides whether incomplete behavior should block the current feature, be explicitly deferred, or be accepted. Needs the decision and its relationship to the original requirement preserved, plus a feature-level view of all filed defects for planning and release discussions.

### Engineering Manager

Needs confidence that known failures cannot be hidden by filing low-quality defects. Wants a durable record of who dispositioned each finding and whether the feature shipped with a known issue, and a portfolio report that can be filtered by feature, severity, and lifecycle status.

## User Stories

| ID | Story | Acceptance Criteria | Priority |
|----|-------|---------------------|----------|
| S1 | As a feature owner, I want one findings inbox for a feature so I can resolve pipeline evidence without opening separate artifacts | Given Diagnose, Review, or Eval artifacts exist for a feature, when I run `speed define feature <name>` or open that feature's Define surface, then I see one list of unresolved findings grouped by underlying issue, with source, task or scenario, status, affected files, and evidence summary | Must |
| S2 | As an engineer, I want the system to preserve what each evidence source actually proves so that a signal is not presented as a confirmed defect | Given a Diagnose signal, Review finding, or Eval result, when it appears in the inbox, then Diagnose is labeled as an unjudged risk signal, Review as an interpreted implementation finding, and Eval as a build-bound execution result | Must |
| S3 | As a feature owner, I want related evidence combined so I do not file multiple defects for the same problem | Given Diagnose flags a retry risk, Review reports a retry correctness issue, and Eval fails the corresponding retry scenario, when the inbox is assembled, then the three records appear as one finding with three evidence sources rather than three findings | Must |
| S4 | As a feature owner, I want to choose an explicit disposition for every finding so that unresolved evidence cannot silently disappear | Given an unresolved finding, when I review it, then I can choose Fix in this feature, Create defect, Needs verification, Accept/defer, False positive, or Duplicate, and every choice except False positive and Duplicate requires a rationale or linked work item | Must |
| S5 | As an engineer, I want current-feature problems routed back to rework so that defects are not used to avoid completing the feature | Given a Review request for changes or a failed required Eval scenario, when I choose Fix in this feature, then the finding is linked to rework for the originating task or requirement and no defect is created | Must |
| S6 | As a feature owner, I want SPEED to draft a defect from selected evidence so I do not have to rewrite findings by hand | Given I choose Create defect, when the draft opens, then Observed Behavior, Expected Behavior, Reproduction Steps, Related Features, affected files, and Additional Context are pre-populated from the available Review and Eval evidence, with Diagnose signals included as supporting context | Must |
| S7 | As an engineer, I want incomplete defect drafts called out before filing so that triage receives actionable reports | Given the evidence cannot establish observed behavior, expected behavior, or reproducible steps, when the draft is generated, then those fields are visibly marked incomplete and filing remains disabled until a user completes them | Must |
| S8 | As a feature owner, I want to confirm defect severity rather than inherit an unreliable guess | Given a defect draft is ready to file, when I review it, then SPEED may suggest P1-P3 using requirement priority and evidence impact, but I must confirm the severity; SPEED never assigns P0 without explicit human selection | Must |
| S9 | As an engineer, I want filed defects to retain source provenance so I can reproduce the exact finding later | Given I file a defect from a finding, when I open the resulting report, then it identifies the source feature, task or scenario, source artifact, source finding IDs, Eval run and build identity when available, commands, logs, and the actor and time of the filing decision | Must |
| S10 | As a feature owner, I want defect creation to be idempotent so rerunning Define cannot duplicate work | Given a finding was already filed as a defect, when the same or a later pipeline run produces equivalent evidence, then SPEED links to the existing defect and offers Update evidence or Mark as duplicate instead of creating another report by default | Must |
| S11 | As an engineering manager, I want filing a defect separated from approving the feature so known failures cannot be laundered into a pass | Given a failed required scenario is filed as a defect, when its finding is dispositioned, then the outcome remains failed until it is fixed or an authorized user records an explicit ship-with-known-defect decision with rationale | Must |
| S12 | As a feature owner, I want non-defect findings routed correctly so verification gaps and scope problems do not pollute the defect backlog | Given an Eval result is unverifiable, a Review item is out of scope, or a Diagnose signal is unconfirmed, when I disposition it, then the default recommendation is Needs verification, Fix/revert scope, or Investigate respectively—not Create defect | Must |
| S13 | As a team member, I want the decision record preserved so later reviews and learning can explain what happened | Given a finding is dispositioned, when the feature is reopened or processed by Learn, then the selected action, rationale, actor, timestamp, linked task or defect, and source evidence remain available | Should |
| S14 | As a feature owner, I want stale evidence identified so I do not file a defect against a build that has already changed | Given a draft was generated from an earlier Review or Eval artifact, when a newer artifact or build exists, then the draft is marked stale and I must refresh the evidence or explicitly file against the older build | Should |
| S15 | As a product or engineering manager, I want a report of all defect files grouped and filtered by feature so I can understand feature quality and follow-up work without opening every defect | Given defect specs or defect state exist, when I open the defect report with no feature filter, then every discovered defect appears once under its primary affected feature or Unassigned, with title, severity, status, source, and a link to the defect file; when I filter to one or more features, then I see one flat deduplicated list matching any selected feature | Must |
| S16 | As a product or engineering manager, I want to combine feature, severity, status, and source filters and export the same result so I can share a stable planning or release view | Given I select one or more features and optional severity, status, or source filters, when I apply or export the report, then both the on-screen result and JSON or Markdown output contain the same matching defects and unique totals | Should |
| S17 | As a feature owner, I want every confirmed defect stored as a canonical, version-controlled spec so the report and defect pipeline use the same durable source | Given a valid defect draft, when I confirm filing, then SPEED creates `specs/defects/<slug>.md` as the default canonical report and initializes its defect state atomically; previewing, canceling, or merely viewing reports creates neither file | Must |
| S18 | As a feature owner, I want affected features separated from source provenance so managers can filter accurately without losing where a defect originated | Given I draft a defect from a finding, when the draft opens, then Source Feature is immutable provenance, Related Features defaults to that source feature, and I can add or remove affected features as long as at least one valid Related Feature remains | Must |
| S19 | As a product or engineering manager, I want completed or invalid defects categorized as closed automatically so the report stays current without manual housekeeping | Given defect state changes to `resolved` after successful integration or `rejected` after triage, when the report refreshes, then the defect appears in the derived Closed category automatically; `fixed`, `reviewed`, `integrating`, and `escalated` do not count as closed | Must |

## User Flows

### End-to-end flow contract

```text
Diagnose / Review / Eval evidence
  → correlated finding
  → explicit human disposition
  → defect draft (no writes)
  → validation and confirmation
  → atomic canonical spec + state
  → feature-filtered manager report
  → existing defect triage pipeline
```

The flow uses these terms consistently:

- **Finding:** A correlated set of Diagnose, Review, or Eval evidence that still needs a human disposition. It is not yet a defect.
- **Defect draft:** A deterministic preview built from selected evidence and user edits. Opening, editing, refreshing, or canceling a draft does not write a defect file or state.
- **Filed defect:** A confirmed canonical report at `specs/defects/<slug>.md` with matching defect state. Only this state enters the defect pipeline and manager report as a fully filed defect.
- **Source Feature:** Immutable provenance identifying the feature whose Define flow produced the finding. It does not independently control manager filters.
- **Related Features:** One or more features affected by the defect. These values control report filtering. A generated draft defaults to its Source Feature, and the owner may edit the affected set before filing.
- **Primary affected feature:** The first Related Feature, used only to group the unfiltered report. A defect is still counted once and retains all related-feature badges.
- **Closed:** A report category derived from terminal defect state, not a separately stored state. `resolved` and `rejected` are Closed; every other lifecycle state, including `escalated`, is Active.

### Enter and review a feature findings inbox

1. The feature owner runs `speed define feature payments` or selects Findings from the payments Define surface.
2. SPEED resolves the feature, refreshes current Diagnose, Review, and Eval artifacts, and opens `/define/payments/findings` when the dashboard is available.
3. The page shows summary counts and all correlated findings, with unresolved findings first. Each finding identifies its evidence sources, confidence, affected task or requirement, stale status, and recommended action.
4. The owner filters by resolution state, source, kind, task, stale status, or linked-defect status without changing the underlying evidence.
5. The owner expands a finding to inspect source-specific evidence. Explicit source-file references can open a bounded read-only excerpt in place. Artifact/log paths and commands remain inert and copyable; nothing is executed.
6. If no evidence exists, the page shows an intentional empty state and links back to the feature. If one source is malformed or unavailable, valid findings remain usable and the page shows a partial-evidence warning.

### Disposition a finding

| Action | Required input | Result | Effect on feature outcome |
|--------|----------------|--------|---------------------------|
| Fix in this feature | Feature task link; optional guidance | Finding links to rework and remains traceable; no defect is created | Remains unresolved until newer evidence proves the issue fixed |
| Create defect | Rationale followed by valid draft and explicit confirmation | Opens draft first; filing later creates canonical spec and state | Does not turn failed evidence into a pass |
| Needs verification | Rationale describing missing evidence | Finding remains visible as a verification gap | Feature remains unaccepted unless later evidence or an authorized exception resolves it |
| Accept/defer | Rationale and any required release authority | Decision is recorded without creating a defect | Governed independently by Outcome Review policy |
| False positive | Rationale | Decision is recorded; contradictory new evidence makes it stale | No defect and no automatic approval |
| Duplicate | Existing finding or defect link | Finding links to the existing work item | Inherits no status; the existing item remains authoritative |

Every successful disposition records actor, time, rationale, source revision, and linked work. A stale source revision rejects the action and reloads current evidence before the user can try again.

### File a defect from corroborated evidence

1. The feature owner runs `speed define feature payments` after Review and Eval complete.
2. SPEED opens the payments findings inbox.
3. One finding reads "Refund retry may charge twice" and shows:
   - Diagnose: retry invariant risk in `src/payments/retry.ts`
   - Review: major correctness issue in task 4
   - Eval: `RISK-03` failed on build `abc1234`
4. The owner expands Eval evidence and sees the failed test, expected behavior, command, and log.
5. The owner chooses Create defect.
6. SPEED opens a no-write draft with failed behavior as Observed Behavior, the scenario expectation as Expected Behavior, and the exact test command as Reproduction Steps. Source Feature is `payments`; Related Features initially contains `payments`.
7. The owner reviews every generated field, may add other affected features, confirms P1 severity, edits the title, and sees `specs/defects/refund-retry-double-charge.md` as the canonical destination; choosing a different output location is not part of the filing flow.
8. SPEED validates required fields, feature names, slug availability, stale evidence, and likely duplicates. Any error stays inline in the draft and creates no files.
9. The owner confirms File defect. SPEED atomically creates `specs/defects/refund-retry-double-charge.md` and its defect state as `filed`, links it from the finding, and records the decision. If either write fails, neither artifact is considered filed and the editable draft remains available.
10. The filed state replaces the action controls with links to the canonical report, originating evidence, and feature-filtered defect report.
11. SPEED offers `speed defect specs/defects/refund-retry-double-charge.md` as the next action; it does not begin triage automatically.

### Recover from a stale, invalid, duplicate, or failed draft

1. While the draft is open, newer evidence arrives, a duplicate is discovered, validation fails, or the atomic write cannot complete.
2. SPEED preserves the user's unsaved edits in browser state and shows a specific blocking message rather than closing the drawer.
3. For stale evidence, the owner chooses Refresh evidence, reviews the changed fields, and confirms again. SPEED never silently rebases the draft.
4. For a likely duplicate, the owner opens the existing defect and either links the finding as Duplicate or explicitly acknowledges why a separate defect is required.
5. For invalid fields, focus moves to the first invalid control and filing remains disabled until all required fields pass.
6. For a write failure, Retry repeats the same idempotent transaction. If one recoverable artifact exists, SPEED reports Repair required and does not create a differently named duplicate.
7. Cancel always returns to the unresolved finding and writes nothing.

### Return a Review finding to the current feature

1. Review reports that task 6 omitted a required authorization check and requests changes.
2. The finding appears with Fix in this feature as the recommended action.
3. The owner chooses Fix in this feature and adds guidance.
4. SPEED links the finding to task 6 rework; no defect report is created.
5. After the task is rerun and Review approves it, the finding shows Resolved by rework with links to both review attempts.

### Resolve an unverifiable Eval result

1. Eval reports `AC-07` as unverifiable because no test is mapped to the scenario.
2. The inbox labels the item "Verification gap" and recommends Needs verification.
3. The engineer chooses Needs verification and records the missing test requirement.
4. The feature remains unaccepted until new evidence is produced or an authorized user records an explicit exception.
5. No product defect is created solely because evidence was absent.

### Investigate a Diagnose-only signal

1. Diagnose reports a possible sensitive-data logging signal, but Review and Eval contain no corresponding finding.
2. The inbox labels it "Unjudged risk signal" and asks whether the failure mode is plausible.
3. The engineer inspects the cited code and marks it False positive with the reason "serialization helper redacts the field before logging."
4. The decision is retained for Learn and the signal does not become a defect.

### Prevent a duplicate defect

1. A later Eval run fails the same scenario against a newer build.
2. SPEED correlates the result with an open defect filed from the earlier run.
3. The inbox shows the existing defect and offers Update evidence or Mark as duplicate.
4. The engineer updates the defect with the new run and build identity; no second defect is created.

### Cancel defect creation

1. The owner chooses Create defect and reviews the generated draft.
2. The owner realizes the behavior is working as specified and cancels.
3. No spec or defect state is written.
4. The original finding remains unresolved until the owner selects another disposition.

### Review defects by feature

1. A product or engineering manager runs `speed define defects` or opens the Define defect report.
2. SPEED discovers the union of canonical files in `specs/defects/` and tracked defect state, and lists each defect once.
3. With no feature filter, the report shows portfolio totals and groups each defect once under its primary affected feature; records without Related Features appear under Unassigned.
4. The manager selects one or more Related Features and optionally filters by derived lifecycle category (Active or Closed), exact status, severity, source, or literal title/name search. Feature matching uses any Related Feature, never Source Feature alone.
5. Once any feature filter is active, the report uses one flat deduplicated list so a cross-feature defect cannot appear beneath an unexpected group or inflate totals.
6. Each row shows severity, lifecycle status, title, updated time, source, all Related Feature badges, metadata warnings, and a link that opens the canonical report in the existing spec editor.
7. Filter state is encoded in the URL. Back/forward navigation, refresh, and a copied URL restore the same view.
8. The manager exports the exact filtered view as Markdown or JSON for a release review or planning document. Export includes generation time and active filters but no raw evidence or logs.
9. If tracked state exists without a canonical spec, the report shows Repair required and disables the report link. If a spec exists without state, it remains visible as Untriaged. Opening or exporting the report never creates the missing artifact automatically.

### Move between a defect, its feature, and its evidence

1. From a report row, the user opens the canonical defect in the existing spec editor.
2. The defect shows Related Features, Source Feature, source finding ID, and current status when those values exist.
3. Selecting a Related Feature returns to `/define/defects?feature=<name>`; selecting Source Finding returns to `/define/<source-feature>/findings?finding=<id>` and expands that finding.
4. Returning to the report preserves the prior URL-backed filters and scroll position when browser history permits.
5. Missing or unsafe targets render as non-interactive text with a warning; the UI never constructs a link outside the project routes.

### Close a defect automatically

1. A filed defect continues through the existing Defect Pipeline; this feature provides no manual Close button.
2. A successfully implemented defect remains Active while `fixed`, `reviewing`, `reviewed`, or `integrating` because the change has not yet been successfully integrated.
3. After integration merges the fix and regression checks pass, the pipeline writes `status: resolved`.
4. On its next refresh, the manager report automatically derives lifecycle category Closed and updates its Active and Closed totals. No second closure mutation or user confirmation is required.
5. If triage determines the report is not a valid defect, the pipeline writes `status: rejected`; the report likewise categorizes it as Closed and retains the rejection status and provenance.
6. `escalated` remains in Active with a Needs attention indicator because automation ending is not the same as the underlying issue being resolved.
7. A regression after `resolved` is filed as a new defect and linked to the earlier one; resolved defects are not reopened or silently moved back to Active.

## Source Interpretation Rules

| Source result | Default treatment | Eligible for defect draft? |
|---------------|-------------------|----------------------------|
| Diagnose signal with undecided plausibility | Investigate | Only after a human confirms plausibility and supplies an observable failure |
| Review critical or major issue | Fix in current feature | Yes, if explicitly deferred beyond the feature |
| Review minor issue or nit | Fix as nit or accept | Yes, if the team wants separately tracked follow-up work |
| Review out-of-scope implementation | Revert or rework scope | No, unless shipped behavior creates a separate user-visible defect |
| Eval fail | Confirmed defect candidate | Yes |
| Eval partial | Human judgment required | Yes, after the missing behavior is isolated |
| Eval unverifiable | Verification gap | Not by default |
| Eval blocked upstream | Attach to upstream cause | Only the root cause should become a defect |
| Eval did not run | Operational failure | No product defect; surface as pipeline recovery work |

## Success Criteria

- [ ] `speed define feature <name>` exposes all unresolved Diagnose, Review, and Eval findings for that feature through a single findings inbox
- [ ] 100% of displayed findings identify their source artifact and source finding ID
- [ ] Diagnose signals are never presented as confirmed defects before human adjudication
- [ ] Failed Eval results can generate a valid defect draft without retyping expected behavior, command, scenario ID, or build identity
- [ ] Filing is blocked when Observed Behavior, Expected Behavior, Reproduction Steps, at least one valid Related Feature, or severity is missing
- [ ] Source Feature remains immutable provenance while Related Features defaults to it and can be edited before filing
- [ ] Confirming a defect uses `specs/defects/<name>.md` as the default canonical destination and atomically creates it with `.speed/defects/<name>/state.json`, without overwriting existing files
- [ ] A filing failure leaves neither artifact considered filed and provides a recoverable error
- [ ] Canceling a draft creates no defect files or state
- [ ] Equivalent findings from multiple sources produce one candidate and retain all source evidence
- [ ] Reopening Define after filing shows the linked defect instead of offering an unqualified second creation action
- [ ] Every disposition records actor, timestamp, rationale, and source evidence
- [ ] A failed required result remains non-passing after defect filing unless an explicit ship-with-known-defect decision is recorded
- [ ] The inbox loads within 2 seconds for a feature with 50 tasks, 50 Review artifacts, 50 Diagnose artifacts, and 200 Eval results
- [ ] The defect report discovers the union of `specs/defects/*.md` and tracked defect state, deduplicates by defect slug, and displays every defect once
- [ ] The unfiltered report groups each defect once by its first Related Feature, while a feature-filtered report shows one flat deduplicated list matching any selected Related Feature; defects lacking feature metadata remain visible as Unassigned
- [ ] Feature filters can be combined with severity, lifecycle status, and source filters, and the summary reports unique totals rather than duplicated group memberships
- [ ] The report automatically derives Closed for `resolved` and `rejected`, derives Active for every other status including `escalated`, and offers lifecycle-category filters without writing a new state
- [ ] `fixed`, `reviewed`, and `integrating` remain Active until successful integration records `resolved`
- [ ] Every report row links to the canonical defect file and identifies missing or conflicting spec/state metadata without hiding the defect
- [ ] Viewing, filtering, or exporting the report never creates a missing defect spec or state file
- [ ] Markdown and JSON exports contain the same filters, totals, ordering, and defects as the on-screen report
- [ ] Report filters survive refresh and browser navigation, and links can open the canonical defect or originating finding without losing report context
- [ ] The unfiltered report loads within 2 seconds for 20 features and 500 defects on a local development machine

## Scope

### In Scope

- `speed define feature <name>` as the entry point to a feature findings inbox
- Findings ingestion from task-scoped Diagnose artifacts, Review artifacts, and feature- or task-scoped Eval artifacts
- Source-aware labeling and default dispositions
- Correlation and deduplication across evidence sources and reruns
- Human dispositions: Fix in this feature, Create defect, Needs verification, Accept/defer, False positive, Duplicate
- Evidence-backed defect draft generation and editing
- Immutable Source Feature provenance with editable Related Features used for manager filtering
- Validation of required defect fields
- Explicit severity confirmation
- Atomic creation of `specs/defects/<slug>.md` as the default canonical defect spec together with its initial defect state
- Provenance and decision history persisted with the feature outcome review
- Stale-evidence and existing-defect warnings
- Ship-with-known-defect decision recording
- Read-only defect inventory grouped and filtered by related feature
- Combined severity, lifecycle status, and defect-source filters
- Automatically derived Active and Closed report categories based on the existing Defect Pipeline state
- CLI, dashboard, Markdown, and JSON renderings of the same filtered report
- An Unassigned group and metadata warnings for legacy or incomplete defect files

### Out of Scope (and why)

- Automatically creating defects when Diagnose, Review, or Eval runs — these commands produce evidence, while Define owns the human decision
- Automatically triaging or fixing a newly filed defect — the existing Defect Pipeline owns investigation, routing, reproduction, fixing, review, and integration
- Replacing task rework — findings that should be corrected before feature completion stay in the feature workflow
- Treating every unverifiable result as a defect — absent evidence is not proof of broken behavior
- Production monitoring and log ingestion — this feature only consumes SPEED pipeline artifacts
- External issue tracker synchronization — GitHub, Linear, and Jira adapters remain part of external intake work
- Automatic release approval after filing defects — outcome approval remains an explicit human decision
- General backlog prioritization or SLA management — SPEED records and routes defects but is not a project management system
- Editing, triaging, or changing defect status from the report — the report links to existing defect workflows and remains read-only
- Automatically backfilling a missing spec or state from the manager report — incomplete records are surfaced for explicit repair so a read-only action never mutates the repository
- A manual Close, Reopen, or report-owned closure state — the existing Defect Pipeline remains authoritative; regressions are filed as new linked defects

## Dependencies

- [The Define Ceremony](speed-define-ceremony.md) for feature context, identity, and human decision surfaces
- [Dashboard Outcome Review](speed-dashboard-outcome-review.md) for judgment items, approval state, and the durable feature review record
- [Defect Pipeline](speed-defects.md) for the defect report contract, initial state, triage, fix, review, and integration lifecycle
- `speed diagnose` risk-surface artifacts, changed to preserve task and attempt identity rather than overwriting one feature-level file
- `speed review` structured results, including `spec_verification`, `missing_from_spec`, `out_of_scope`, and `issues`
- `speed eval` evaluation handoffs, including run ID, build identity, result status, expected behavior, commands, logs, and traces
- Current actor identity for attribution and authorization
- Existing `specs/defects/` registry and `.speed/defects/` state management
- A tolerant metadata reader for legacy defect templates and generated provenance fields
- [Design spec](../design/speed-define-feature-defects.md) for page structure, components, states, responsive behavior, and accessibility
- Learn observation extraction so dispositions and false positives improve future guidance

## Security & Controls

**Authentication:** The dashboard and CLI run with the current local project identity. No new remote authentication is introduced.

**Authorization:** Any project member may inspect evidence. Filing a defect requires repository write access. Recording a ship-with-known-defect decision requires the same authority used to approve the feature outcome; the person who generated a draft does not gain additional approval rights.

**Path safety:** Source artifact paths, defect output paths, commands, and log references are treated as untrusted data. Paths must remain inside the project root, generated slugs cannot traverse directories, and existing specs or state directories are never overwritten.

**Data sensitivity:** Evidence can contain stack traces, test data, and command output. Defect drafts must not copy secrets, credentials, full payment data, or unrelated personal data from logs. Sensitive evidence remains referenced by path rather than duplicated when possible.

**Report safety:** The manager report exposes defect metadata and project-relative file links, not raw evidence or log bodies. Filters are read-only, exports escape untrusted Markdown content, and report discovery cannot read outside the canonical defect roots.

**Audit trail:** Every disposition records the actor, timestamp, rationale, source artifact identities, resulting task or defect, and any explicit ship-with-known-defect decision. Previous decisions are append-only history even when the current disposition changes.

**Failure atomicity:** Filing either creates a complete defect spec and valid initial state or creates neither. A partial write is reported and recoverable without generating a duplicate on retry.

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Weak correlation merges distinct problems into one finding | High | Show every source record, allow Split finding, and use stable requirement, task, file, and scenario identities before semantic similarity |
| Weak correlation creates duplicate defects | Medium | Check stable finding fingerprints and existing open defects before filing; present likely duplicates for confirmation |
| Teams use defects to defer required work and approve incomplete features | High | Filing does not convert a failed result to pass; require a separate authorized ship-with-known-defect decision |
| Diagnose signals create false-positive backlog noise | High | Label them as unjudged, require plausibility confirmation and observable behavior, and default to Investigate rather than Create defect |
| Generated reports overstate what the evidence proves | Medium | Preserve source labels, quote evidence rather than infer missing facts, and block filing until required gaps are completed by a human |
| A rerun makes a draft stale | Medium | Compare source attempt, Eval run ID, commit, and build fingerprint before filing; require refresh or explicit older-build filing |
| Evidence contains secrets or sensitive test data | High | Redact known secret patterns, avoid copying full logs, and reference protected artifacts by path |
| Diagnose and Review artifacts are overwritten across tasks or attempts | High | Persist immutable task- and attempt-scoped artifacts and maintain a separate latest pointer for convenience |
| Legacy defects omit or inconsistently format Related Feature metadata | Medium | Parse canonical and legacy labels, use an explicit state `related_features` mirror when available, never infer affected scope from Source Feature alone, and retain unmatched records in Unassigned with warnings |
| Source Feature is mistaken for affected feature scope | Medium | Label source as provenance, default but do not lock Related Features to it, and drive manager filters only from Related Features |
| Spec and state metadata disagree, producing misleading manager totals | Medium | Discover their union, apply documented field precedence, surface conflicts, and count each defect slug only once |

## Open Questions

| ID | Question | Impact | Status |
|----|----------|--------|--------|
| Q1 | Should `speed define feature <name>` render an interactive terminal workflow, open the dashboard feature route, or support both? | Determines the primary UI and whether CLI-only environments have full filing capability | Resolved: print a terminal summary and open the dashboard in an interactive session; `--no-open` and `--json` support headless inspection, while filing remains dashboard-only in V1 |
| Q2 | Which roles may authorize Ship with known defect, and should P0/P1 defects ever allow that override? | Determines release governance and approval enforcement | External dependency: Outcome Review policy must decide this; defect filing never grants or implies that authority |
| Q3 | Should Needs verification create a new task immediately, annotate the current feature for re-planning, or only remain an unresolved outcome-review item? | Determines how verification gaps return to execution | Resolved for V1: retain an unresolved outcome-review item and do not create a task automatically |
| Q4 | How much semantic similarity should be used after stable IDs and file overlap when correlating findings? | Affects false merges versus duplicate candidates | Resolved for V1: no free-text-only grouping; use deterministic stable anchors and explicit manual merge/split |
| Q5 | Should a filed defect snapshot selected evidence inside its state directory or only reference immutable feature artifacts? | Affects portability after feature cleanup versus duplicated sensitive data | Resolved for V1: persist structured provenance and immutable artifact references, not raw evidence or log snapshots |
| Q6 | Should an existing defect be updated automatically with evidence from a newer run after user confirmation, or should updates create an append-only evidence entry? | Determines defect history and concurrent-edit behavior | Resolved for V1: require confirmation and append a new evidence entry; never overwrite prior provenance automatically |
