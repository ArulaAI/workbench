# The Define Ceremony

> Enhancement to the existing Define surface. See `specs/product/speed-dashboard-define.md` for the portfolio dashboard (shipped). See `working-docs/ceremony-design.md` for ceremony design exploration.

## Problem

SPEED has four phases: Define, Execute, Judge, Learn. Execute works end-to-end. An engineer runs `speed audit`, `speed plan`, `speed verify`, `speed run`, `speed review`, `speed coherence`, `speed integrate` and the pipeline handles everything from spec auditing to integration. The system side has a complete interaction model.

The three human phases have no equivalent. Someone finishes a feature with SPEED and the process ends. There is no structured moment where the team evaluates what the pipeline produced and decides whether it ships. No point where specs are validated against codebase reality before execution begins. No mechanism for extracted learnings to influence future runs.

The Define phase is where the highest-leverage human decision happens: what to build. A spec is a statement of organizational knowledge. If that knowledge is wrong, stale, or incomplete, SPEED executes faithfully on bad assumptions. The cost compounds: the learning pipeline carries forward lessons derived from a flawed premise, poisoning future context.

Today, an author opens a blank file and starts writing a spec. Everything they need to write well (codebase structure, prior learnings, known defects, what's been tried before in this area) exists somewhere in the system. None of it is delivered to them. They discover it piecemeal, or they don't discover it at all.

Context delivered is 1000x more powerful than context discovered. The Define Ceremony front-loads everything the system knows so the author writes with full context, not from a blank page.

## Users

### The Author

Turns intent into a structured spec. Usually a PM writing a PRD, but could be an engineer writing an RFC or a designer writing a design spec. Their primary challenge is not writing ability but knowledge access: understanding the codebase reality, prior patterns, and organizational context well enough to write a spec that will survive execution.

The author today writes specs in their editor with no system assistance. They search the codebase manually, ask teammates about prior decisions, and discover gaps when `speed audit` or execution surfaces them. The ceremony eliminates this discovery tax.

### The Contributor

Adds expertise the author doesn't have. An engineer reviewing a PM's PRD for technical feasibility. A designer flagging interaction patterns that conflict with existing UI. A PM adding acceptance criteria an engineer wouldn't think to specify.

Contributors today are pulled in ad-hoc via Slack, PR reviews, or meetings. The ceremony gives them a shared surface with the same context the author sees, so their contributions are grounded in codebase reality rather than memory.

### The Approver

Confirms the spec accurately represents organizational knowledge and intent. In single-player, the author and approver are the same person. In multiplayer, this is the ratification step where teammates confirm shared understanding before the system commits resources to execution.

Approvers today either rubber-stamp specs they haven't deeply reviewed or block on questions they could have answered earlier with better context. The ceremony front-loads context so approval is an informed judgment, not a trust exercise.

## User Stories

| ID | Story | Acceptance Criteria | Priority |
|----|-------|---------------------|----------|
| S1 | As an author, I want to declare what I intend to build so the system can deliver relevant context | Given the Define surface is open, when I enter a one-liner or paragraph describing my intent (e.g., "sort auth list by last activity"), then the system scopes its context assembly to the relevant area of the codebase. The declaring actor becomes the spec author and owns the ceremony for this feature. | Must |
| S2 | As an author, I want the system to deliver everything it knows about the area I'm working in before I start writing | Given I have declared intent, when context assembly completes, then I see: codebase structure for the relevant area, prior learnings from past features, known defects, curated project knowledge, product vision status, related features (built, in-flight, dependent), and audit history from past specs in this area. If the scoped context is irrelevant or too broad, I can refine my intent and the system re-scopes. | Must |
| S3 | As an author, I want the system to generate a complete first draft of my spec from intent and context, so I review and refine rather than write from scratch | Given context has been delivered, when I begin authoring, then the system generates a full draft spec (PRD, RFC, or design) using the correct SPEED template, grounded in codebase reality. The generated draft must pass template conformance and audit validation before being presented. I review and edit the draft in an interactive editor with the context panel visible alongside. | Must |
| S4 | As an author, I want validation feedback on my spec across six dimensions | Given I am editing a spec, when I save, then Tier 1 checks run immediately: template conformance (spec adheres to the SPEED template) and structural completeness (required sections, acceptance criteria format). When I click Validate (or press Cmd+Shift+R), then Tier 2 checks run: cross-spec coherence (contradictions between product/tech/design specs), codebase alignment (references to code that exists, doesn't exist, or has changed), sizing (decomposability into tasks), and vision alignment. Tier 2 badges show staleness when the draft has changed since the last run. Commit auto-runs all dimensions as a precondition. | Must |
| S5 | As an author, I want to explicitly commit my spec for execution with a recorded decision | Given my spec is complete and validation feedback is acceptable, when I commit, then the system records who committed, when, the validation state at commitment time, and the context package snapshot. Only the author (the actor who declared intent) can commit; this cannot be delegated. In single-player, `speed plan` is unblocked. In multiplayer, ratification begins. Commitment is blocked if the spec does not conform to its SPEED template. | Must |
| S6 | As an author working across multiple specs, I want the system to flag contradictions and gaps between them | Given a feature has companion specs (PRD + RFC, or PRD + multiple child RFCs), when the content of one spec contradicts another (e.g., the PRD says "must support pagination" but the RFC's data model has no cursor field), then the system flags the contradiction inline in both specs with a link to the conflicting section. When a PRD user story has no coverage in any child RFC, the system flags the gap in the PRD's RFC Decomposition section. | Must |
| S7 | As a contributor, I want to leave inline suggestions on a spec draft so the author can incorporate my expertise | Given an author has started a Define ceremony, when I open the same feature's Define surface, then I see the same context package and spec draft (read-only), and I can leave inline suggestions attached to specific sections. I can edit or delete my own suggestions before the author resolves them. Only the author can edit the spec. | Should |
| S8 | As an author, I want to resolve contributor suggestions with a clear decision trail | Given a contributor has left suggestions on my spec, when I view them in the editor, then I can accept (applies the suggested change), dismiss (with a required reason), or reply (starts a thread). Each resolution is recorded with who, when, and the decision. Unresolved suggestions surface as a warning at commitment time. | Should |
| S9 | As an approver, I want to see the validation state, context snapshot, and suggestion resolution history before ratifying | Given a spec has been proposed for ratification (MP), when I open the Define surface for that feature, then I see the current validation results, the context that was delivered to the author, and a summary of contributor suggestions (how many received, accepted, dismissed with reasons). The spec author cannot ratify their own spec. Each approver submits one verdict (approve or reject). Ratification threshold is configurable in `speed.toml` (default: 1 approval). | Should |
| S10 | As an author of a complex feature, I want the ceremony to guide me through multi-spec topologies | Given my intent describes a feature that is too large for a single RFC, when the system's sizing analysis detects this, then the ceremony guides me through decomposing the work: either multiple RFCs under one PRD (single feature, phased execution) or multiple PRDs (distinct features with a shared parent intent). The system scaffolds the correct template for each spec and tracks the dependency graph between them. | Should |
| S11 | As an author on a new project, I want a guided bootstrap that establishes minimum organizational knowledge | Given a project has no semantic graph, no vision document, and no project knowledge, when I start the Define ceremony for the first time, then the system builds the codebase graph and guides me through establishing vision and team conventions | Should |
| S12 | As an author bootstrapping a project, I want SPEED to draft a product vision from what it can see in the codebase so I don't start from scratch | Given the project has no vision document, when the bootstrap flow detects this, then the system offers to generate a draft vision from the README, docs, code structure, and any existing project metadata. The author reviews, edits, and commits the draft before it becomes the active vision. The author can also choose to write one from scratch instead. | Should |
| S13 | As any team member, I want to see the context that was delivered when a spec was written | Given a feature has a persisted context package, when I view that feature's Define history, then I can see what the system knew at the time the spec was authored, for post-mortems and learning | Could |

## User Flows

### First-time setup (Bootstrap)

1. Author opens the Define surface on a new project
2. System detects cold start: no semantic graph, no vision document, no project knowledge
3. Surface presents a guided bootstrap flow:
   a. System begins building the codebase semantic graph (runs in background)
   b. System detects no product vision. Author is offered two options: (1) let SPEED generate a draft vision from the codebase (README, docs, existing code structure, project metadata), or (2) write one from scratch. If the author chooses generation, SPEED produces a draft and the author reviews and edits before committing it.
   c. System runs an initial convention extraction using the same Learn pipeline capabilities that normally operate after feature execution. From the codebase, SPEED can derive: coding patterns, naming conventions, test structure, file organization, dependency choices, CI/CD configuration, linting rules, and framework usage. The system presents these as a draft conventions set for the author to review, correct, and commit.
   d. Author supplements with conventions the system cannot derive from code. The system prompts by persona for what's invisible in the codebase:
      - **Engineering**: deployment practices, branching strategy, testing requirements (unit/integration/e2e thresholds), infrastructure boundaries (cloud provider, container orchestration, serverless vs. traditional), performance budgets, API versioning strategy, database migration practices, dependency update policy
      - **Product**: release cadence, feature flag practices, A/B testing norms, analytics/instrumentation requirements, localization/i18n needs, accessibility standards, backward compatibility guarantees, deprecation policy
      - **Design**: design system or component library in use, responsive breakpoints, accessibility targets (WCAG level), animation/motion guidelines, brand constraints, supported platforms/browsers, dark mode requirements
   The author doesn't need to answer everything. Gaps are filled over time as the Learn ceremony extracts conventions from executed features.
4. System writes vision to `specs/product/overview.md`, conventions (derived + seeded) to `.speed/memory/project-knowledge.json`
5. Bootstrap complete. Future Define ceremonies have context to deliver. The conventions knowledge base grows automatically through the Learn ceremony.

### Declaring intent and receiving context

1. Author opens the Define surface on the dashboard
2. Author enters intent: "Users should be able to sort the auth list by last activity"
3. System parses intent, identifies relevant codebase area (Users module, auth endpoints, accessedAt attribute)
4. System assembles context package:
   - Codebase: Users.php validator, existing query attributes, accessedAt migration history
   - Prior learnings: conventions for adding queryable attributes (if any past features touched this)
   - Defects: none open in this area
   - Vision: product vision status (defined / placeholder / missing)
   - Related: no in-flight features in this area
   - Audit history: no prior specs for this area
5. Context package is persisted to `.speed/features/sort-auth-by-last-activity/context-package.json`
6. Context is delivered to the author's surface
7. Author reviews the scoped context. If it's too broad (includes unrelated modules) or too narrow (missing the migration history), they refine the intent: "sort auth list by last activity, specifically the accessedAt attribute in Users.php." System re-scopes and re-assembles.

### Authoring with context

1. System generates a complete first draft of the spec (PRD, RFC, or design) from the declared intent and the context package. The draft uses the correct SPEED template, populated with content grounded in codebase reality: user stories reference actual code paths, acceptance criteria reference real data structures, scope boundaries reflect what exists in the system. The draft is a starting point, not a final product.
2. Author sees context panel alongside the generated draft in the interactive editor. They review the draft section by section, editing, adding, or removing content.
3. As the author edits acceptance criteria referencing `accessedAt`, the system highlights that this attribute exists in the database schema and the response model but is not currently queryable.
4. As they reference the Users endpoint, the system shows the existing query validator structure.
5. Author adds edge cases the LLM missed. System validates: the `isNull` query type is supported by the existing validator pattern.
6. System flags sizing: this spec is small enough for a single phase (no decomposition needed).
7. If the system detects the spec exceeds single-RFC sizing (10+ tasks or naturally splits into independent phases), it flags this to the author with a recommended decomposition. The author chooses: (1) accept and let the system generate an RFC Decomposition section with drafted child RFCs, (2) decompose manually, or (3) proceed with a single RFC anyway.

### Authoring a complex feature (multi-RFC)

1. Author declares intent: "Rebuild the payment checkout flow with Stripe integration and fraud detection"
2. Context is delivered. System's sizing analysis flags: this intent spans multiple independent subsystems (payment gateway, fraud rules, checkout UI) and will likely exceed single-RFC sizing.
3. System suggests decomposition: one PRD with three child RFCs, or three separate PRDs if the subsystems are independent features.
4. Author chooses one PRD with three child RFCs.
5. System generates a complete draft PRD with the RFC Decomposition table populated, plus draft child RFCs for each phase. Each child RFC is grounded in the context package for its subsystem. Every generated spec must pass template conformance and audit validation before being presented to the author — the system does not surface drafts that violate the SPEED template or fail structural audit checks.
6. Author reviews the PRD and each child RFC in tabbed editors. Cross-spec validation runs across all specs in the topology, flagging contradictions between sibling RFCs or gaps where a child RFC doesn't cover its assigned user stories.

### Contributor leaving suggestions

1. Author shares the feature's Define ceremony link with an engineer (or the engineer sees it in the landing panel's Define section)
2. Engineer opens the Define surface for the feature. They see the same context package the author received and the current spec draft. The editor is read-only.
3. Engineer reads the acceptance criteria for the `accessedAt` sorting feature. Notices the spec doesn't mention the 24-hour throttle on `accessedAt` updates.
4. Engineer selects the acceptance criteria section and leaves an inline suggestion: "Add a criterion for the 24-hour throttle — accessedAt only updates once per 24h window, so 'last activity' has that resolution limit. Users filtering by hour will get stale results."
5. Author receives the suggestion inline in their editor, highlighted against the relevant section.
6. Author accepts the suggestion. The spec is updated with a new acceptance criterion. Resolution is recorded: accepted by author, timestamp, original suggestion preserved.

### Resolving suggestions before commitment

1. Author has received four suggestions from two contributors.
2. Author opens the suggestion panel: 4 unresolved.
3. Author accepts two (changes applied to spec), dismisses one with reason ("covered by the NULL handling edge case already"), and replies to one asking for clarification.
4. Contributor sees the reply, responds with more detail. Author reads and accepts.
5. Suggestion panel shows: 4 resolved (3 accepted, 1 dismissed). Commitment is unblocked.

### Cross-spec contradiction resolution

1. Author has written a PRD specifying "users can filter by exact date" and an RFC where the data model stores `accessedAt` as a date truncated to the day.
2. System flags a contradiction inline in both specs: "PRD S3 specifies exact-date filtering, but RFC data model truncates accessedAt to day precision. Exact timestamps will not match."
3. Author clicks the flag in the PRD. System navigates to the conflicting section in the RFC, highlighted.
4. Author decides the RFC is correct (day precision is intentional) and updates the PRD acceptance criteria to say "filter by date" instead of "filter by exact datetime."
5. Contradiction clears from both specs.

### Cross-spec coverage gap

1. Author has a PRD with five user stories and an RFC Decomposition mapping them to two child RFCs.
2. System flags: "S4 (pagination support) is not mapped to any child RFC in the decomposition table."
3. Author reviews and adds S4 to the second child RFC's user story mapping. System validates that the child RFC's content addresses S4.
4. Gap clears.

### Approver ratification (multiplayer)

1. Author commits the spec. Ratification begins. Teammates receive notification.
2. Approver opens the Define surface for the feature. They see:
   - The spec draft (read-only)
   - The context package that was delivered to the author
   - Validation state: template conforming, no cross-spec issues, all codebase references valid
   - Suggestion summary: 4 suggestions received from 2 contributors, 3 accepted, 1 dismissed ("covered by NULL handling edge case")
3. Approver reviews the dismissed suggestion's reason, agrees it's valid.
4. Approver ratifies. `speed plan` is unblocked.

### Committing the spec

1. Author finishes the spec. Validation panel shows: template conforming, structure complete, no cross-spec issues (no tech/design spec yet), codebase references valid, sizing acceptable, vision alignment unknown (vision is a placeholder template). Suggestion panel shows: all suggestions resolved.
2. Author clicks Commit
3. System records: author identity, timestamp, validation snapshot, context package reference, suggestion resolution history
4. Single-player: `speed plan` is now unblocked for this spec
5. Multiplayer: spec is proposed to teammates. Ratification threshold must be met before planning proceeds.

### Viewing historical context

1. Feature `sort-auth-by-last-activity` completed execution three weeks ago. A new team member is investigating an escalation.
2. They open the Define surface and navigate to the feature's history.
3. System loads the persisted context package from `.speed/features/sort-auth-by-last-activity/context-package.json`.
4. The team member sees what the system knew when the spec was written: the codebase structure at that time, the conventions in effect, the defects that were open, the vision status.
5. They compare this against the current state to understand whether the escalation stems from a context gap (something the system didn't know) or a judgment gap (something the author chose to ignore).

## Success Criteria

- [ ] Intent declaration accepts free-text input and scopes context assembly to the relevant codebase area
- [ ] Context package assembles from: semantic graph, prior learnings, known defects, project knowledge, vision status, related features, audit history
- [ ] Context package is persisted as a first-class artifact at `.speed/features/{feature}/context-package.json`
- [ ] System generates a complete first draft spec from intent + context package, using the correct SPEED template (PRD, RFC, or design), grounded in codebase reality
- [ ] Generated draft is presented in an interactive editor for the author to review and refine
- [ ] All specs authored through the ceremony conform 100% to their SPEED template. Commitment is blocked for non-conforming specs.
- [ ] Tier 1 validation (template conformance, structure) runs live on every save with inline feedback
- [ ] Tier 2 validation (cross-spec coherence, codebase alignment, sizing, vision alignment) runs on-demand via Validate button (Cmd+Shift+R), on draft generation, and as a commit precondition
- [ ] Tier 2 badges show staleness when draft has changed since last full validation run
- [ ] When sizing analysis detects a feature exceeds single-RFC scope, the ceremony guides the author through decomposition into multiple child RFCs under one PRD, or multiple independent PRDs
- [ ] Cross-spec validation runs across all specs in a multi-RFC topology, flagging contradictions and coverage gaps between sibling specs
- [ ] Contributors can leave inline suggestions on specific sections of a spec draft (read-only access to the spec itself)
- [ ] Author can accept, dismiss (with required reason), or reply to each suggestion
- [ ] Suggestion resolution is recorded: who, when, decision, original suggestion preserved
- [ ] Unresolved suggestions surface as a warning at commitment time
- [ ] Cross-spec validation flags contradictions between companion specs (PRD vs RFC, sibling RFCs) inline in both specs with cross-links to the conflicting section
- [ ] Cross-spec validation flags coverage gaps where a PRD user story is not mapped to any child RFC
- [ ] Approver sees suggestion resolution summary (received, accepted, dismissed with reasons) alongside validation state before ratifying
- [ ] Commitment records author, timestamp, validation state, context snapshot, and suggestion resolution history
- [ ] Commitment in single-player unblocks `speed plan`
- [ ] Commitment in multiplayer triggers ratification flow
- [ ] Bootstrap flow guides first-time users through vision and conventions (derived from code + human-provided per persona)
- [ ] Context package API is surface-agnostic (same data format consumable by any surface)
- [ ] Existing Define portfolio mode (three-column grid) continues to function unchanged

## Scope

### In Scope

- Intent declaration input and codebase area scoping
- Context package assembly from seven data sources
- Context package persistence
- Interactive spec editor on the dashboard (primary surface), scaffolded from SPEED templates
- Template conformance enforcement: all specs must adhere 100% to their SPEED template (PRD, RFC, or design). Non-conforming specs cannot be committed.
- Complex spec topology support: single PRD with multiple child RFCs, or multiple independent PRDs sharing a parent intent. Dependency graph tracking between sibling specs.
- Continuous validation with inline feedback (six dimensions: template conformance, structure, cross-spec coherence, codebase alignment, sizing, vision alignment)
- Cross-spec validation across multi-RFC topologies (contradictions and coverage gaps)
- Contributor suggestion system: inline suggestions, accept/dismiss/reply lifecycle, resolution history
- Commitment flow with durable artifact including suggestion resolution history (single-player and multiplayer)
- Bootstrap flow for new projects (guided vision, conventions, priorities)
- Context package API (surface-agnostic format, consumed by dashboard and external integrations)

### Out of Scope (and why)

- Spec editing outside the dashboard. The dashboard editor is the primary surface. Authors can still write specs in their editor and use the dashboard for context and validation only.
- Real-time collaborative editing. The ceremony assumes a single author. Multiplayer contribution happens asynchronously (contributors open the surface separately). Real-time co-editing requires distributed locking and conflict resolution.
- Fully autonomous spec authoring without human review. The system generates drafts, but the author must review and commit. SPEED does not plan or execute against a spec the author hasn't approved.

## RFC Decomposition

This feature spans context assembly (backend), interactive editing (frontend), and validation (backend + frontend). The natural split follows file ownership boundaries:

| User Story IDs | Child RFC | Depends On | Testable Output |
|----------------|-----------|------------|-----------------|
| S1, S2, S13 | `specs/tech/speed-define-ceremony-context.md` | (none) | Context package API returns scoped JSON for a given intent string. Persisted to `.speed/features/{feature}/context-package.json`. Scope refinement re-assembles on updated intent. Historical context viewing loads persisted package for completed features. |
| S3, S4, S6, S10 | `specs/tech/speed-define-ceremony-editor.md` | context | Interactive editor renders with context panel, scaffolded from SPEED templates. Template conformance validation inline within 2s. Multi-RFC topology support with tabbed child editors. Cross-spec validation flags contradictions and coverage gaps inline with cross-links. |
| S5, S9 | `specs/tech/speed-define-ceremony-commitment.md` | editor, contributor | Commitment writes `commitment.json`, `validation-at-commit.json`, suggestion resolution history. Blocks on template non-conformance and unresolved suggestions (warning). MP triggers ratification events with suggestion summary visible to approvers. Ratification threshold configurable in `speed.toml`. SP unblocks `speed plan`. For multi-RFC topologies, commitment is atomic across all specs in the topology. |
| S11, S12 | `specs/tech/speed-define-ceremony-bootstrap.md` | context | Bootstrap flow detects cold start, guides vision/conventions input (with optional LLM generation), writes artifacts. |
| S7, S8 | `specs/tech/speed-define-ceremony-contributor.md` | editor, context | Contributor opens surface with read-only spec and shared context. Inline suggestion system with accept/dismiss (with reason)/reply lifecycle. Resolution history recorded per suggestion. |

<!-- Dependency graph:
     context ── editor ── commitment
                  └── contributor
     context ── bootstrap
-->

## Dependencies

**Context assembly:**
- Codebase semantic graph (built by `speed plan`, needs to be triggerable independently for bootstrap and context assembly). Specifically the CSG cluster output at `.speed/context/semantic-graph.json` and the project map at `.speed/context/project-map.json`.
- Project knowledge at `.speed/memory/project-knowledge.json`
- Observation history at `.speed/memory/observations/*.jsonl`
- Product vision at `specs/product/overview.md`
- Feature state at `.speed/features/*/state.json`
- Spec traceability and criteria verification outputs from past features
- Defect state at `.speed/defects/*/state.json` and `specs/defects/*.md`
- Build and test configuration (for context delivery about CI/infrastructure)
- Learn pipeline convention extractors at `lib/learn/convention_extractors.py` (curated conventions feed context delivery; also reused during bootstrap to derive initial conventions from code)

**Spec generation and validation:**
- LLM provider (configured in `speed.toml`) for draft generation from intent + context
- SPEED spec templates at `templates/prd.md`, `templates/rfc.md`, `templates/design.md` (template conformance validation and generation scaffolding)
- Audit agent structural and completeness checks (for validating generated drafts before presenting to author)
- Audit agent sizing logic (for detecting when a feature exceeds single-RFC scope and needs decomposition)
- Guardian agent for vision alignment validation

**Editor and suggestion system:**
- Existing Define portfolio page infrastructure (Next.js 15 app router, Strawberry GraphQL backend, urql client)
- Existing audit logic in `speed audit` and `define.py` resolver
- Markdown editor component (new, or integration with existing spec editor at `/editor`)
- Suggestion storage and resolution tracking (new artifact type)

**Commitment and ratification:**
- Existing ceremony commands in `lib/cmd/ceremony.sh` (for MP ratification flow)
- Event system at `.speed/shared/events/` (for MP proposal/review/ratification events)
- Git identity (for recording who committed/ratified)

## Identity and Ownership

### How users are identified

**Single-player**: The sole user is identified by SPEED's actor resolution chain (`$SPEED_ACTOR` env -> `git config user.name` -> `whoami`). Email follows the same pattern (`$SPEED_ACTOR_EMAIL` -> `git config user.email` -> `{name}@local`). The chain never fails; environments without git fall back to the OS username. All ceremony actions are attributed to this identity. No additional auth.

**Multiplayer**: Same identity chain. This is already how SPEED's event system identifies actors (the `actor` field in every JSONL event, resolved by `lib/actor.sh`). The roster at `.speed/shared/roster/` tracks active actors. If you can push to the repo, you're a recognized actor.

### Ownership model

Each ceremony action has a single owner. Ownership follows the same claim/release model as SPEED's multiplayer feature ownership:

- **Claim**: Intent declaration claims the ceremony. The declaring actor becomes the author.
- **Release**: Commitment releases the claim (the ceremony is complete). Alternatively, the author can explicitly abandon the ceremony.
- **Stale**: If the author is inactive beyond the stale window (same threshold as `speed claim`), the claim expires. Another actor can declare fresh intent for the same area.
- **Transfer**: There is no mid-ceremony handoff. If ownership needs to change, the current author releases (or the claim goes stale), and a new author declares intent. The context package and any prior draft are available to the new author as prior art, but the ceremony restarts.
- **Enforcement**: The system blocks non-owners from editing, committing, or resolving suggestions. Same mechanism as `speed claim` — second claim on an owned ceremony exits with error.

| Action | Owner | Assigned when | Who else can act |
|--------|-------|---------------|------------------|
| Intent declaration | Author | Author enters intent | No one. Intent creates the ceremony and assigns authorship. |
| Context package | System | Intent is declared | Read-only for all actors. |
| Spec draft (generated) | Author | System generates draft | No one edits directly. Contributors leave suggestions. |
| Spec editing | Author | Intent is declared | Author only. Single writer. |
| Suggestion | Contributor | Contributor submits it | The contributor who created it can edit/delete before resolution. |
| Suggestion resolution | Author | Suggestion is submitted | Author only. Accept, dismiss (with reason), or reply. |
| Commitment | Author | Author clicks commit | Author only. Cannot be delegated. |
| Ratification verdict | Approver | Spec is proposed (MP) | Any actor except the author. Each actor submits one verdict. Threshold configurable in `speed.toml` (default: 1). |
| Bootstrap vision | Author | Bootstrap begins | Author only. System may generate a draft, but the author commits it. |
| Bootstrap conventions | Author | Bootstrap begins | Author only. System derives from code, author reviews and commits. |

### Single-player collapse

In single-player, the author is every role. All ownership constraints still apply (the system still records who and when), but there's no meaningful authorization check. The value is the audit trail, not the access control.

## Security & Controls

**Data sensitivity**: The context package may contain codebase structure, function signatures, and prior learnings. All of this already exists on disk. The ceremony assembles and presents it but does not transmit it externally. LLM host delivery requires the author to explicitly use an LLM — the system does not auto-send context to external services.

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Intent-to-codebase scoping produces irrelevant context | High | LLM seed file selection: the model receives the full project file list and intent, selects relevant files directly. Falls back to word-boundary keyword matching when no model is available. Full-graph fallback if no matches, with a low-confidence warning shown to the author. Author can refine scope after seeing initial results. |
| Context package assembly is slow for large codebases | Medium | Assemble incrementally: vision and project knowledge are fast (file reads). Semantic graph scoping is the bottleneck. Show partial context as each source completes rather than blocking on full assembly. |
| Continuous validation creates noisy feedback during early drafting | Medium | Debounce validation (run after 2s of inactivity, not on every keystroke). Allow the author to dismiss or snooze individual validation items. Distinguish blocking issues from advisory feedback visually. |
| Bootstrap asks too many questions for a user who just wants to run the pipeline | Low | Bootstrap is skippable. The system proceeds with whatever knowledge it has. Missing context is surfaced as gaps in the context panel, not as blocking errors. |
| Authors ignore context and write from assumptions anyway | Low | Not a system problem. The ceremony ensures context is available. Whether the author uses it is their decision. The persisted context package still has value for post-mortems. |
| Multi-RFC decomposition guidance leads to wrong topology (too many RFCs, wrong boundaries) | Medium | Sizing analysis suggests decomposition but the author makes the final call. System flags file-ownership overlaps between sibling RFCs. The author can merge or re-split at any point before commitment. |
| Template enforcement frustrates authors who want flexibility | Low | Templates exist because downstream agents (Architect, Reviewer, Guardian) depend on predictable structure. The ceremony surfaces template guidance inline so the author understands why each section matters, rather than treating conformance as an arbitrary gate. |
| Suggestion system becomes a bottleneck if contributors are unresponsive to replies | Low | Unresolved suggestions warn at commitment but do not block. The author can dismiss with a reason and proceed. The approver sees the dismissal reason during ratification. |

## Open Questions

| ID | Question | Impact | Status |
|----|----------|--------|--------|
| Q1 | Should the semantic graph builder be decoupled from `speed plan` so it can run independently during bootstrap and context assembly? | Blocks bootstrap flow and context delivery for projects that haven't run `speed plan` yet. | Decided: Yes. Dependencies section states it "needs to be triggerable independently." |
| Q2 | What is the context package schema? It needs to be stable enough for multiple surfaces to consume but flexible enough to evolve. | Blocks LLM host and IDE integrations. | Decided. Context RFC defines the schema (`ContextPackage` dataclass with 7 sources). External consumers (LLM hosts, IDE extensions) may require schema versioning. |
| Q3 | How does intent-to-codebase scoping work? Keyword matching, embedding similarity, or LLM-assisted? | Affects context relevance and assembly latency. | Decided: LLM seed file selection (the model selects relevant files from the project file list given the intent). Keyword matching with word boundaries as fallback. Full-graph delivery with low-confidence warning if no matches. Testing showed LLM seeds produce 0% noise vs 41% for keyword-only, and 56% precision vs 34%. Author can refine scope interactively (per S2). |
| Q4 | Should the dashboard editor support multiple spec types (PRD + RFC + design) in tabs, or one spec at a time? | Affects cross-spec validation and authoring UX. | Decided: Tabs. The multi-RFC flow (S10) and cross-spec validation (S6) require simultaneous visibility of sibling specs. |
| Q5 | How does the ceremony handle spec amendments? If a committed spec is revised after execution begins, should a new ceremony be required? | Affects spec integrity guarantees downstream. | Open |
| Q6 | For multi-PRD topologies (multiple independent features sharing a parent intent), should there be a parent intent artifact that tracks the relationship, or are they fully independent ceremonies that happen to share context? | Affects how the Judge ceremony evaluates outcomes across related features. | Open |
| Q7 | Should the template set be extensible (teams define custom templates), or is the fixed set (PRD, RFC, design) sufficient? | Affects template conformance validation complexity. Fixed set is simpler and aligns with current SPEED architecture. | Open |
