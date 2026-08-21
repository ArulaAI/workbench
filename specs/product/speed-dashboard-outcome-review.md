# Dashboard: Outcome Review

> Part of the [Human Surface](../../working-docs/pm-surface-design.md) initiative.
> Prototype: [outcome-review-prototype.html](../../working-docs/outcome-review-prototype.html)
> Design decisions: [surface-design-decisions.md](../../working-docs/surface-design-decisions.md)

## Problem

The verification pipeline runs automatically: coverage computed, criteria checked, guardian evaluated, security scanned. But some items can't be resolved without human judgment. An unverifiable criterion, an intentionally deferred requirement, a failed check that might be acceptable. The system needs a surface where the team reviews outcomes and renders a verdict.

No surface exists for this today. Verification results live in JSON files across `.speed/features/`. The team has no way to see the aggregate outcome, judge unresolved items, or produce the approval record that downstream processes (learning pipeline, release management) depend on.

## Users

### Product Manager
Reviews whether the feature outcome matches the specification. Reads the executive summary to understand the aggregate picture. Makes judgment calls on deferred requirements and unverifiable criteria. Forwards the approved review to stakeholders.

### Engineer
Verifies technical claims. Expands evidence to check whether automated tests actually exercise the right paths. Judges whether an unverifiable criterion needs an automated test or is acceptable with manual verification.

### Engineering Manager
Gate-keeper for approval. Reads the summary and metrics. Checks guardian and security findings. Signs off on the verdict.

### VP / Stakeholder
Reads the shareable link after approval. Needs the executive summary and metrics to understand the outcome without SPEED context. Never interacts with the judgment UI.

## User Stories

| ID | Story | Acceptance Criteria | Priority |
|----|-------|---------------------|----------|
| S1 | As any team member, I want to see the aggregate outcome immediately when I open the review | Given a feature has completed verification, when I open the Outcome Review, then I see coverage %, criteria pass rate, guardian verdict, and security findings within 3 seconds, before reading any text | Must |
| S2 | As a PM, I want to work through items the system couldn't resolve | Given unresolved items exist (unverifiable criteria, uncovered requirements, failed checks), when I view the right panel, then each item shows a description, selectable options, and expandable inline evidence | Must |
| S3 | As an engineer, I want to expand evidence for any judgment item to verify the system's claim | Given a judgment item about ISBN validation, when I click "Show evidence", then I see the specific criteria, verification method, and evidence text inline within the judgment card | Must |
| S4 | As any team member, I want the approve button to activate only when all judgments are resolved | Given 2 judgment items exist, when I resolve both by selecting options, then the Approve button changes from disabled to active and the hint text updates | Must |
| S5 | As any team member, I want resolved judgments to collapse structurally | Given I resolve a judgment item, when the selection is made, then the card collapses to a compact line showing badge + title + chosen answer, and the description and options disappear (not just dim) | Must |
| S6 | As a VP, I want to read the review as a standalone artifact via a shared link | Given the review is approved, when someone opens the URL, then they see the feature name, executive summary in plain English, key metrics, resolved judgments with chosen answers, and approval status without needing SPEED context | Must |
| S7 | As any team member, I want to see the full requirements list to verify any passed item | Given 9 stories with 14 criteria exist, when I scroll below the judgment items, then I see a compact expandable list of all stories with pass/fail status and criteria detail | Should |
| S8 | As any team member, I want to see the aggregate outcome on the left while working through judgments on the right | Given I'm making a judgment about ISBN validation, when I glance left, then I see 94% coverage, 12/14 criteria, guardian approved, and the progress indicator showing how many judgments remain | Must |
| S9 | As any team member, I want to request rework and annotate which requirements need revisiting | Given the outcome is unsatisfactory, when I click Request Rework, then I can select which requirements need re-execution and provide context for each | Should |
| S10 | As any team member, when no items need judgment, I want the page to show the outcome as auto-approved | Given all criteria passed and no items need human input, when I open the Outcome Review, then the page shows metrics + summary + a green "auto-approved" indicator with no judgment queue | Should |

## User Flows

### The judgment ceremony

1. Team opens the Outcome Review for the Defect Pipeline feature
2. Left panel shows: 94% coverage, 12/14 criteria, guardian approved, 1 medium security finding, "0 of 2 judgments resolved"
3. Right panel shows 2 judgment cards and a collapsed Full Requirements section
4. PM reads the executive summary on the left: "Shipped at 94% coverage... Two items need judgment... Recommendation: approve with manual test for ISBN"
5. PM clicks the first judgment card (ISBN validation), reads the description
6. PM expands evidence: sees S4 criteria detail, 1 of 2 passed, the unverifiable criterion
7. PM selects "Will test manually". Card collapses to one line. Progress updates to "1 of 2 resolved"
8. PM reads second card (CSV import), selects "Intentional deferral". Card collapses. Progress updates to "2 of 2 resolved"
9. Approve button activates. PM clicks "Approve & Ship"
10. Left panel shows "Approved" with timestamp. Right panel shows the decision record.

### Post-approval artifact

1. PM shares the review URL with the VP
2. VP opens the link
3. Left panel: feature name, metrics (94%, 12/14, guardian pass, 1 medium), executive summary, findings
4. Right panel: two resolved judgment lines ("ISBN validation → Will test manually", "CSV import → Intentional deferral"), expandable Full Requirements
5. VP reads the summary and metrics in 30 seconds, understands the outcome

### Auto-approval (no judgments needed)

1. Team opens the Outcome Review for a feature where all criteria passed
2. Left panel shows: 100% coverage, 14/14 criteria, guardian approved, 0 security findings
3. Right panel shows: "No items need judgment. All criteria verified automatically."
4. Left panel shows a green "Auto-approved" indicator instead of the Approve/Rework buttons

## Success Criteria

- [ ] Two-panel layout: left (340px) persistent context, right scrollable work area
- [ ] Left panel shows outcome metrics (24px hero numbers), executive summary, automated findings, judgment progress, verdict action (pinned to bottom)
- [ ] Right panel shows judgment cards with description, selectable options, expandable inline evidence
- [ ] Resolved judgments collapse structurally (reduced padding, hidden description/options, chosen answer shown inline)
- [ ] Approve button activates when all judgments resolved
- [ ] Full Requirements section below judgments lists all stories with expandable criteria detail
- [ ] Clean-pass stories show no expand caret (consistent: only expand when detail exists)
- [ ] Post-approval state is a readable artifact: resolved decisions + evidence archive
- [ ] Executive summary is LLM-synthesized in plain English (~$0.01 per review)
- [ ] Page degrades gracefully without LLM: structured evidence still works, summary omitted
- [ ] Review verdict persisted to `.speed/features/{feature}/review.json`
- [ ] Every judgment produces observation data for the learning pipeline

## Scope

### In Scope
- Two-panel layout (left: persistent context, right: work area)
- Outcome metrics display (coverage, criteria, guardian, security)
- LLM-synthesized executive summary
- Judgment queue with selectable options per item
- Inline expandable evidence per judgment
- Full requirements archive with expandable per-story detail
- Automated findings strip (guardian, coherence, security)
- Approve & Ship / Request Rework actions
- Structural collapse on judgment resolution
- GraphQL resolver reading verification artifacts
- GraphQL mutation persisting review.json

### Out of Scope
- Re-running verification (that's the pipeline's job)
- Editing specs from the review (that's the Spec Editor)
- Requirement-level rework re-execution (future: the mutation flags requirements, the pipeline re-plans)
- Email/Slack notifications on approval (future integration)
- Multi-reviewer workflow (V1 is single team approval)

## Dependencies

- Criteria verification output from `criteria_verify.py`
- Spec traceability output from `spec_traceability.py`
- Guardian verdict logs (`Guardian-*.jsonl`)
- Coherence report logs (`Coherence-*.jsonl`)
- Security audit logs (`Security-*.jsonl`)
- Feature state at `.speed/features/*/state.json`
- LLM provider for executive summary (`provider_chat()`)
- Existing dashboard infrastructure

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| LLM summary hallucinates metrics | Medium | Summary is supplementary. Hero metrics are computed from raw data, not the LLM output. User reads numbers first, narrative second. |
| Review.json write fails | Medium | Mutation returns error. UI shows "save failed" with retry. Judgments preserved in client state. |
| Team skips reviews and auto-approves without reading | Low | The page optimizes for judgment quality, not ceremony length. A clean feature with 0 judgment items auto-approves in seconds. Friction is proportional to the number of unresolved items. |

## Security & Controls

**Authentication**: Dashboard runs locally. No additional auth.

**Authorization**: Any team member can view the review. The Approve/Rework mutation writes `review.json` to the filesystem. No role-based access control in V1.

**Audit trail**: The `review.json` file records: who approved (git user), when (ISO timestamp), each judgment decision with the selected option, and the verdict. The learning pipeline consumes this as observation data.

**PII**: The executive summary may contain feature-specific language from the spec. No user PII is surfaced.

## Open Questions

| ID | Question | Impact | Status |
|----|----------|--------|--------|
| Q1 | Should the executive summary be cached or regenerated on each page load? | Cached is faster and cheaper. Regenerated ensures freshness if verification re-runs. | Open |
| Q2 | Should the VP see the judgment options or only the resolved answers? | Options show the alternatives the team considered. Resolved-only is cleaner for the artifact. | Open |
| Q3 | How does Request Rework mechanically trigger re-execution? | The mutation writes rework annotations to review.json. The pipeline reads them on next `speed run`. Exact handoff TBD. | Open |
| Q4 | Should the page support multiple review sessions (partial save)? | V1 assumes the ceremony completes in one session. Partial save would require draft state in review.json. | Open |
