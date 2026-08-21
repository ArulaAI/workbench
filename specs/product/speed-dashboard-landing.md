# Dashboard: Landing Page

> Part of the Human Surface initiative (see working-docs/pm-surface-design.md).
> Prototype: working-docs/landing-editorial.html

## Problem

A team member opening the dashboard sees Mission Control: task DAGs and token burn. There's no orientation about what needs human attention. The four development phases (Define, Execute, Judge, Learn) have no unified entry point. The user has to know which page to visit for which question.

The landing page should answer "What needs me?" in one glance, routing the user to the right phase page with the right feature context already set.

## Users

### Product Manager
Wants to know: is a feature waiting for review? Are there draft specs that need an RFC? Are there defects accumulating? Routes to Outcome Review or Define.

### Engineer
Wants to know: what's running? Is anything blocked? Are there escalations needing answers? Routes to Execute or the escalation inline.

### Engineering Manager
Wants a project health snapshot: how many features in each phase, what's the escalation count, are things progressing? Reads the whole page without routing.

### Designer
Wants to know: where are design specs missing? Which features executed without design guidance? Routes to Define.

## User Stories

| ID | Story | Acceptance Criteria | Priority |
|----|-------|---------------------|----------|
| S1 | As any team member, I want to see all four phases simultaneously when I open the dashboard | Given the landing page loads, when I look at the screen, then I see Define (left), Judge (top center), Execute (bottom center), and Learn (right) in fixed positions that don't change regardless of project state | Must |
| S2 | As any team member, I want the most urgent item to get the most visual space | Given a feature is awaiting Outcome Review, when the Judge panel renders, then it fills the top center with summary narrative, hero metrics, decision count, and a primary CTA. When nothing is pending review, the panel shows a calm empty state. | Must |
| S3 | As a PM, I want to see the Define panel with vision status, draft specs, and defect count | Given specs exist on disk and defects are filed, when I view the left sidebar, then I see vision status (missing/defined), draft specs needing next step, and defects grouped by severity | Must |
| S4 | As an engineer, I want to see running features with progress and respond to escalations inline | Given features are executing with an active escalation, when I view the Execute panel, then I see progress bars per feature and an escalation card with the question and an inline text input to respond | Must |
| S5 | As any team member, I want CTAs that route to the right page with feature context | Given a feature "Defect Pipeline" is awaiting review, when I click "Review & decide" in the Judge panel, then I'm taken to the Outcome Review page with the Defect Pipeline feature already selected | Must |
| S6 | As an EM, I want to see the Learn panel with coverage trends and insights | Given features have completed, when I view the right sidebar, then I see coverage trend per feature, latest insights (good/warn), and escalation trend | Should |
| S7 | As any team member, I want a project-level greeting and context | Given I open the dashboard, when the top bar renders, then I see a greeting ("Good morning, Sanjay"), the project name, and the current branch | Should |

## User Flows

### Morning check-in

1. PM opens the dashboard
2. Greeting: "Good morning, Sanjay" with project name and branch
3. Eyes land on Judge panel (top center): "Defect Pipeline" awaiting review, 94% coverage, 12/14 criteria, 2 decisions needed
4. PM clicks "Review & decide" → routed to Outcome Review with Defect Pipeline selected
5. After reviewing, PM returns to landing. Judge panel now shows the completed review summary.
6. PM glances left at Define: product vision missing (dashed warning), Turn Exhaustion unplanned
7. PM glances bottom center at Execute: Security Auditor at 92% with 1 escalation
8. PM scrolls the escalation, types a response inline, clicks Send

### Responding to an escalation

1. Engineer opens the dashboard
2. Execute panel shows: Security Auditor 92%, 1 task awaiting input
3. Escalation card: "Spec says [security] is optional, but implementation errors when absent. Fall back to defaults, or require it?"
4. Engineer types "Fall back to defaults" in the input field
5. Engineer clicks Send. Escalation resolved. Execute panel updates.

## Success Criteria

- [ ] T-shape layout: Define left (260px), Judge top center, Execute bottom center, Learn right (320px)
- [ ] All four panels visible simultaneously without scrolling (for typical project state)
- [ ] Fixed positions: Define always left, Judge always top center, Execute always bottom center, Learn always right
- [ ] Variable visual weight: Judge panel expands when review is pending, calms when nothing pending
- [ ] Panel labels follow Name → Intent pattern ("Define" → "Specs and preparation")
- [ ] Judge panel shows review summary, hero metrics (28px mono), decision count, primary CTA
- [ ] Execute panel shows running features with progress bars, escalation card with inline input
- [ ] Define panel shows vision status, draft specs, defect list with severity
- [ ] Learn panel shows coverage trend, insights, escalation trend
- [ ] CTAs route to correct page with feature context preserved
- [ ] Escalation response sends inline (without navigating away)
- [ ] Status bar shows connection status, project name, feature counts, running feature indicators
- [ ] LLM project narrative enhances Judge panel when available (~$0.005)
- [ ] Page degrades without LLM: bullet points replace narrative
- [ ] Live updates via `taskStatusChanged` subscription for Execute panel

## Scope

### In Scope
- T-shape editorial grid layout
- Four phase panels (Define, Judge, Execute, Learn)
- Greeting top bar with project context
- Panel content summaries from all four phase data sources
- CTAs routing to phase pages with feature context
- Inline escalation response in Execute panel
- Status bar with connection and running feature indicators
- Live task status updates via WebSocket subscription
- LLM project narrative for Judge panel
- Single summary resolver projecting data from all phases

### Out of Scope (and why)
- Detailed spec editing (Define page). Covered by the dedicated Define page RFC; the landing panel is a summary projection only.
- Full judgment ceremony (Outcome Review page). The Judge panel surfaces the CTA and key metrics, but the multi-step review workflow belongs on its own page where criteria and decisions have room.
- Task-level execution detail (Execute/Mission Control page). The landing shows progress and escalations; task DAGs, logs, and token burn stay on Mission Control where they already work.
- Full learning curation (Learning page). The Learn panel shows trends and top insights; editing, weighting, and archiving learnings requires the dedicated Learning page.
- Customizable panel arrangement (positions are fixed). Fixed positions build muscle memory; the user should know where each phase lives without scanning after a week of use.
- Dark/light theme toggle (dark only). The dashboard design system is dark-only; adding a light theme is a system-wide decision, not scoped to the landing page.

## Dependencies

- Feature state at `.speed/features/*/state.json`
- Spec files at `specs/product/`, `specs/tech/`, `specs/design/`
- Verification results for completed features
- Task status and escalation data from `.speed/features/*/tasks/*.json`
- Observation and learning data from `.speed/memory/`
- LLM provider for project narrative (`provider_chat()`)
- WebSocket subscription infrastructure (already exists for Mission Control)
- Define, Outcome Review, and Learning pages (for routing targets)
- Existing dashboard infrastructure

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Four panels don't fit on smaller screens | Medium | Minimum supported width: 1280px. Below that, the sidebars could collapse to icons. Not a V1 priority. |
| Summary resolver is slow (reads from all four data sources) | Medium | Each panel projection is lightweight (counts and top items, not full data). Target: <200ms for the combined query. |
| Escalation inline response doesn't reach the pipeline | Medium | Response writes to the task's input field in task JSON. The pipeline reads it on next poll. Same mechanism as existing escalation handling. |

## Security & Controls

**Authentication**: Local dashboard. No additional auth.

**Authorization**: Any team member can view. Escalation response writes to task JSON (same as CLI escalation response).

**PII**: Escalation questions may reference code or spec content. No new PII surfaces.

## Open Questions

| ID | Question | Impact | Status |
|----|----------|--------|--------|
| Q1 | Should the landing page replace the current root redirect to Mission Control? | If yes, `/` shows the landing page, Mission Control moves to its own nav item. If no, landing is a separate route. | Open |
| Q2 | How should the Judge panel handle multiple features awaiting review? | Show the most recent one with a "2 more" indicator? Stack them? The spec says one lead story. | Open |
| Q3 | Should the greeting include time-of-day awareness? | "Good morning" vs "Good afternoon" based on local time. Low effort, nice touch. | Open |
| Q4 | Should the Define panel show spec audit warnings inline? | The prototype shows them. The summary resolver would need to run basic structural checks. | Open |
