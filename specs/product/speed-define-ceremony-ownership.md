---
status: draft
feature: speed-define-ceremony-ownership
---

# Define Ceremony: Per-Spec Ownership

> Extends the parent PRD: [speed-define-ceremony.md](speed-define-ceremony.md). Replaces its single-author baseline (see "Ownership model" in the parent) with per-spec claims.
> Depends on: Define Ceremony (shipped), Multiplayer event sourcing and roster (shipped).

## Problem

The define ceremony today assigns one author to the whole feature. That author writes the PRD, the Design, and the RFC, resolves every suggestion, decomposes, commits, and drives ratification. Real teams split this work: a PM owns the product spec, a designer owns the design, an engineer owns the RFC, and each of them expects to make independent progress without waiting on the others. The single-author model forces all of it through one person and matches no real team.

## Users

Roles in this feature are ceremony-scoped and ephemeral. They emerge from the act of claiming a spec, not from a persistent tag on the roster. Claiming the PRD makes you the PM for this ceremony. Claiming the RFC makes you the Engineer. When the spec commits or the claim is released, the role dissolves.

### PM claimant

Writes the product requirements. Today, a PM who wants to add a PRD to an in-progress ceremony has no surface to do it: the ceremony already has an author, the draft is owned by that author, and the PM's only option is to paste text into Slack or wait for a handoff. The ceremony ignores how product work actually flows.

### Design claimant

Writes the design spec in parallel with the PRD. Today, a designer who opens a ceremony started by a PM sees a read-only PRD and has nowhere to author a design spec as a first-class sibling. Design decisions get pushed into Figma comments and PR reviews, disconnected from the ceremony's context package and validation.

### Engineer claimant

Writes the RFC, usually once the PRD is in a reviewable state but not necessarily after it commits. An engineer often wants the PRD and RFC to draft in parallel so cross-spec contradictions surface while both specs are still editable. The current single-author model prevents independent ownership of the RFC slot.

### Non-claimant reviewers

Any roster member who has not claimed a given spec. A PM who claims the PRD is a non-claimant relative to the RFC and can leave suggestions on it. Non-claimants see every spec in the ceremony read-only; they contribute by leaving inline suggestions. There is no separate "reviewer" role because review is suggestions plus resolution.

### Ratifiers

Non-claimants who submit verdicts on committed specs. A claimant cannot ratify their own spec. In a single-member roster `submitRatification` is never called — the ceremony auto-ratifies at commit time because no eligible ratifier exists. Each spec is ratified independently, so the PRD can ratify while the RFC is still drafting.

## User Stories

| ID | Story | Acceptance Criteria | Priority |
|----|-------|---------------------|----------|
| O1 | As a PM, I want to claim the PRD tab so I can author it and resolve its suggestions. | Given a ceremony exists and the PRD tab is unclaimed, when I click Claim on the PRD tab, then I become the PRD claimant, the tab displays my name, and I can edit the draft, resolve suggestions on it, and commit it independently of sibling specs. | Must |
| O2 | As a designer, I want to claim the Design tab independently of who claimed the PRD. | Given the PRD is claimed by another actor, when I click Claim on the Design tab, then I become the Design claimant without affecting the PRD claim, and the two claims have independent stale clocks. | Must |
| O3 | As an engineer, I want to claim the RFC tab while the PRD is still being drafted. | Given a PRD draft exists, when I click Claim on the RFC tab, then I become the RFC claimant and can author, decompose, and commit the RFC in parallel with ongoing PRD work. | Must |
| O4 | As a non-claimant, I want to leave review suggestions on any spec regardless of who claimed it. | Given the RFC is claimed by another actor, when I open the RFC tab, then the editor is read-only, I can select sections and leave inline suggestions, and the commit bar later warns the claimant about unresolved suggestions without blocking the commit. | Must |
| O5 | As a claimant, I want to resolve suggestions on my spec without involving other claimants. | Given a non-claimant has left a suggestion on my claimed spec, when I click Accept or Dismiss with reason, then the resolution is recorded under my identity and the suggestion state updates for every roster member viewing the ceremony. | Must |
| O6 | As a claimant, I want to decompose and commit my spec independently of sibling specs. | Given my spec passes validation, when I click Decompose (RFC only) and then Commit, then my spec is committed with a per-spec commit record while sibling specs remain in their current state. Decompose is only offered on RFC slots because only RFCs produce tasks. | Must |
| O7 | As a roster member, I want to see which specs are claimed, by whom, and what state each is in. | Given a ceremony with specs in mixed states, when I open the ceremony, then I see a progress overview listing every spec with its claimant, validation summary, open-suggestion count, and commit status (drafting, committed, or ratified). | Must |
| O8 | As a ratifier, I want to ratify a committed spec without waiting for sibling specs to catch up. | Given the PRD is committed but the RFC is still drafting, when I open the ratification view for the PRD, then I can submit a verdict on the PRD alone; the ceremony advances to RATIFIED only once every drafted spec has cleared its threshold. | Should |
| O9 | As a roster member, I want to claim a spec whose original claimant went dark. | Given a spec's claim is older than the stale window with no activity in between, when I click Claim, then the old claim is released and I become the new claimant in a single transaction. | Should |
| O10 | As a sole roster member, I want to ship each spec independently without needing a teammate. | Given I am the only roster member, when I declare intent, then the PRD is auto-claimed for me. I claim Design and RFC tabs the same way a teammate would (one click each). I edit, decompose, and commit each spec using the same surface as a multi-actor ceremony. When I commit, the ceremony auto-ratifies the spec inline because no eligible ratifier exists, and `speed plan` unblocks on the last commit. | Must |

## User Flows

### Parallel PRD and RFC authoring

1. A PM opens the ceremony for a new feature and declares intent. The PRD is auto-claimed for the PM; the Design and RFC tabs show Claim affordances.
2. The PM edits the PRD draft with the context panel visible. Tier 1 validation runs inline.
3. An engineer opens the same ceremony. The PRD tab shows `[PRD · pm-name]` (read-only, suggestions allowed). The RFC tab shows Claim.
4. The engineer clicks Claim on the RFC tab and begins authoring the RFC against the PRD's current draft. Cross-spec validation flags contradictions live as both specs change.
5. The PM commits the PRD. The PRD claim is retired; its commit record is written. The RFC is still drafting and the ceremony remains in DRAFTING.
6. The engineer finishes the RFC and commits. The last drafted spec now has a commit record, so the ceremony transitions to COMMITTED in the same call.
7. With more than one roster member, per-spec ratification begins. With only the committing author on the roster, `commitSpec` writes the ratification inline and the ceremony reaches RATIFIED on the last commit in one round trip.

### Non-claimant reviewer leaves suggestions

1. A second engineer opens the ceremony. The RFC is claimed by eng-name.
2. They open the RFC tab. The editor is read-only; a "Leave suggestion" affordance appears when they select text.
3. They leave an inline suggestion on the API Surface section.
4. The RFC claimant sees the suggestion highlighted in their editor alongside a notification badge on the tab.
5. The claimant Accepts, Dismisses with reason, or Replies. The resolution is recorded with their identity.
6. At commit time, the commit bar summarizes unresolved suggestions as a warning but does not block. The claimant commits with the warning acknowledged.

### Stale claim takeover

1. A PM claimed the PRD two hours ago and went offline. The stale window is 60 minutes.
2. A second PM opens the ceremony. The PRD tab shows the old claimant's name with a "stale" badge and a Claim affordance.
3. The second PM clicks Claim. The server releases the old claim (sets `released_at` on the old file, reason = stale) and writes the new claim in one transaction.
4. The old claimant's draft content is preserved. The second PM reviews it, edits, and commits as normal.
5. The event log records both the stale release and the new claim for audit.

### Multi-RFC decomposition with per-child claims

1. The feature exceeds single-RFC scope. The PRD's RFC Decomposition table lists four child RFCs (`rfc-ingestion`, `rfc-query`, `rfc-editor`, `rfc-feedback`).
2. The ceremony tab bar now shows: `[PRD]`, `[Design]`, `[RFC: ingestion]`, `[RFC: query]`, `[RFC: editor]`, `[RFC: feedback]`.
3. Four engineers each click Claim on a different child RFC and work in parallel.
4. Each child has its own claim, validation state, decomposition, commit record, and ratification. A suggestion on `rfc-ingestion` does not block work on `rfc-query`.
5. The ceremony transitions to COMMITTED when every drafted slot (PRD, Design, and all four child RFCs) has a commit record.

### Sole roster member

1. A sole engineer opens the ceremony for a small feature and declares intent. The PRD is auto-claimed.
2. The tab bar renders the same ownership chrome as a multi-actor ceremony: Claim buttons on Design and RFC, progress overview in the context panel, per-tab claimant badges. Because the engineer is the only roster member, every claim they write shows their name and no "claimed-by-other" or "stale" states ever appear naturally.
3. The engineer clicks Claim on the Design tab, drafts it, and commits. Because the roster has no one other than the commit author, `commitSpec` writes `ratification-{spec_type}.json` inline with `source: "no-eligible-ratifier"` in the same call. The Design row on the progress overview advances to ratified.
4. They repeat for the RFC: click Claim, draft, decompose if needed, commit. Each commit advances its own spec to ratified inline.
5. They commit the PRD last (or first, or in any order). When the last drafted spec lands its commit, the ceremony reaches RATIFIED and `speed plan` unblocks. **Per-spec commit is the individual win**: the engineer can ship the PRD and immediately start editing the RFC without waiting for the ceremony to fully close.

## Success Criteria

- [ ] Multiple actors can hold different spec claims within the same ceremony simultaneously
- [ ] Each claimant can edit, resolve suggestions on, decompose (RFC slots only), and commit their spec without mutating sibling claims
- [ ] Non-claimants can leave suggestions on any spec but cannot edit, resolve, decompose, or commit
- [ ] A stale claim (older than `[multiplayer] stale_window`) is replaceable by any roster member in a single action
- [ ] Per-spec ratification proceeds independently; the ceremony transitions to RATIFIED only once every drafted spec has cleared its ratification threshold
- [ ] The progress overview displays every spec's claimant, validation summary, open-suggestion count, and commit status, and satisfies the acceptance criteria of O7 without requiring additional queries
- [ ] Sole roster members use the same tab bar, progress overview, and commit bar as multi-actor ceremonies. Claim buttons appear on Design and RFC tabs and behave identically to the multi-actor flow. Commits on any spec auto-ratify inline (`source: "no-eligible-ratifier"`) because the only roster member is the commit author
- [ ] Migrating an existing single-author ceremony preserves the original author as the claimant of every drafted spec
- [ ] Every authorization denial raises a recognizable error the UI can map to a user-facing message ("this spec is claimed by {name}"), not a generic 500

## Scope

### In Scope

- Per-spec claim records on disk, one file per claimed spec
- `claimSpec` and `releaseSpec` mutations with stale detection
- Per-spec commit and ratification records, replacing the single-file ceremony-wide versions
- Per-RFC decomposition (decompose action is unavailable on PRD and Design slots)
- Tab bar claim affordances (claimant name, Claim button, Release button, stale badge)
- Progress overview panel showing per-spec state for all roster members
- Authorization policy enforcing claimant-only mutations, with a single policy class that every mutation calls
- Migration of existing single-author ceremonies to the per-spec claim model on first load
- Backward compatibility with the existing `author_email` field (now populated as the PRD claimant)

### Out of Scope (and why)

- **Persistent role tags on the roster.** Roles are ephemeral and claim-derived. Persistent tags would duplicate the claim concept and introduce a static config layer that does not match how claims actually work in practice.
- **Assigning a spec to someone.** Claims are pulled by the actor, not pushed by a coordinator. Matches the existing `speed claim` pattern and avoids introducing a coordinator role or notification pipeline.
- **Multiple claimants on one spec at the same time.** One claimant per spec. Collaboration runs through suggestions, same as the parent ceremony. Real-time co-editing would require distributed locking outside the scope of a file-based ceremony.
- **Role-based claim gating.** Any roster member can claim any spec. No rule that "only designers can claim the Design spec." Teams self-police by leaving suggestions when the wrong person claims something.
- **Claim transfer after commit.** Once a spec's commit record is written for a revision, the claimant recorded inside it is immutable. Changing who committed requires creating a new revision and committing fresh.
- **Cross-spec dependency enforcement at commit time.** If the RFC depends on the PRD being ratified, the system does not block RFC commit. Dependencies are informational and shown in the progress overview only.
- **A separate "review" action.** Review is suggestions plus resolution. Claimants resolve open suggestions before committing, which serves the same function as a formal review step without a new action.

## Dependencies

- Parent Define Ceremony feature including the ceremony state machine, revision model, and artifact flow (shipped)
- Multiplayer event sourcing, roster (`.speed/shared/roster/`), and actor resolution chain (shipped)
- `[multiplayer] stale_window` setting in `speed.toml` (existing, reused unchanged)
- `lib/ownership.sh` UTC-safe staleness comparison (existing, reused; must not be reimplemented)
- Per-spec validation state already on disk at `validation-state-{spec_type}.json` via `ceremony_validation_state()`
- `get_current_actor()` from `ceremony_types.py` (existing)
- Multiplayer event stream at `.speed/shared/events/` for claim lifecycle events

## Security & Controls

**Authentication.** Actor identity is resolved by SPEED's existing chain (`$SPEED_ACTOR` env → `git config user.name` → `whoami`). Email follows the same pattern. No new auth.

**Authorization.** Every protected mutation calls an `authorize(action, spec_type)` check before proceeding. The policy is implemented as a single class so every rule lives in one file and every mutation gets the same enforcement. The PRD specifies the product contract (the authorization matrix below); the RFC owns the implementation.

| Action | Allowed when |
|--------|--------------|
| Declare intent (creates ceremony, auto-claims PRD) | Any roster member |
| Claim a spec | Any roster member AND the spec is unclaimed or stale |
| Release own claim | Caller is the current claimant of that spec |
| Edit a spec | Caller is the current claimant of that spec |
| Create suggestion on a spec | Any roster member who is NOT the current claimant of that spec |
| Edit or delete own suggestion | Suggestion author, before resolution |
| Resolve suggestion | Caller is the current claimant of the suggestion's spec |
| Decompose a spec | Caller is the current claimant AND the spec is an RFC slot |
| Commit a spec | Caller is the current claimant of that spec AND validation passes |
| Ratify a spec | Caller is NOT the author recorded in the spec's commit record (the claimant snapshot taken at commit time; the live claim is retired once committed). When the roster contains no member other than the commit author, `commitSpec` writes the ratification inline and `submitRatification` is never called. |
| Abandon the ceremony | Caller is the current PRD claimant (the intent declarer) |

**Audit.** Every claim lifecycle event (claim started, released, stale takeover, committed) is written to the multiplayer event stream. Same pipeline as feature-level claims. Readers of the event log can reconstruct ownership history for any ceremony.

**Surprise UX mitigation.** Stale claim takeover is always a deliberate user action (explicit Claim click on a stale tab), never automatic. The stale clock runs lazily on read, not as a background sweeper. A claim never transitions to stale without a user action that observes it.

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| A claimant goes dark mid-ceremony and blocks other claimants | Medium | Claim goes stale after 60 minutes of inactivity (shared `[multiplayer] stale_window` default). Any roster member can re-claim after that. |
| Wrong role claims a spec (e.g., an engineer claims the Design) | Low | Claims are reversible via Release; non-claimants leave suggestions asking "did you mean to claim this?" Teams self-police. |
| Per-spec commit creates temporary inconsistency (PRD committed, RFC still drafting) | Medium | Ceremony state stays DRAFTING until all drafted specs are committed. `speed plan` gates on ceremony state, not per-spec state. |
| Sole roster members hit Claim friction they don't need | Low | Sole actors click Claim twice per ceremony (Design and RFC; PRD is auto-claimed by `declareIntent`). The trade is a unified claim model across roster sizes. Per-spec commit is the individual win: a sole dev can ship the PRD and start the RFC without waiting for the whole ceremony to close. |
| Stale claim takeover surprises the original claimant when they return | Low | The original claimant's draft content is preserved on release (not deleted). They can see the new claimant in the event log and in the progress overview. |
| Implicit reviewer quality bar (suggestions are not enforced sign-offs) | Medium | Non-claimants leave suggestions, claimants resolve. Teams that want a formal gate use ratification, which excludes claimants by construction. |
| Progress overview clutters the editor layout | Low | Panel is collapsible. Default open state is computed from `drafted_specs.length > 3` regardless of roster size. |
| Claim goes stale between the start and end of a commit transaction | Low | Commit is atomic server-side. Claim validity is checked once at the start of commit; if valid then, the commit proceeds regardless of staleness during the write. |

## Open Questions

| ID | Question | Impact | Status |
|----|----------|--------|--------|
| OQ1 | Does single-player show any claim UI at all, or does the model collapse invisibly to today's experience? | Affects UX complexity for sole users, who are the majority of SPEED's current installs. | **Resolved: unified model.** Sole actors see the same tab bar, claim buttons, and progress overview as multi-actor ceremonies. Trade-off accepted: two extra Claim clicks per ceremony in exchange for consistency, code simplification, and a Figma-style individual experience that scales into team experience without a mode change. |
| OQ2 | When a stale claim is taken over, should the original claimant get any notification beyond the event log entry? | Affects collaboration hygiene in multiplayer. | Open. Likely yes via the existing MP event stream; no new notification pipeline. |
| OQ3 | Where does the Progress Overview panel live in the editor layout — context region, secondary tab row, or slide-out? | Affects editor real estate and interaction flow. | Deferred to the design spec and prototype. |
| OQ4 | Should `ratification-{spec_type}.json` records carry any state beyond `{ratified: bool, verdicts: [...], source: str}`, or is a thin record sufficient? | Affects ratification audit trail granularity and event log design. | Deferred to RFC. |
