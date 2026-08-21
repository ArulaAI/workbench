# Dashboard: Learning Curation

> Part of the [Human Surface](../../working-docs/pm-surface-design.md) initiative.
> Prototype: [learning-prototype.html](../../working-docs/learning-prototype.html)
> Design decisions: [surface-design-decisions.md](../../working-docs/surface-design-decisions.md)
> Depends on: [Observations](speed-observations.md), [Synthesis](speed-synthesis.md)

## Problem

The 10-step extraction pipeline processes 120+ observations per feature across 13 types (retries, reviewer findings, guardian verdicts, context misses, verify findings). The synthesis phase groups these by agent, applies recurrence filters, and produces 6 learnings files with concrete guidance entries. But the team has no surface to see what the system learned, whether the process is improving, or to decide which proposed changes to carry forward.

Learnings exist as JSON files in `.speed/memory/`. Without a curation surface, the system silently injects all synthesized guidance into agent prompts. The team loses visibility into what's shaping agent behavior and can't override bad learnings or reinforce good ones.

## Users

### Product Manager
Reads spec quality trajectory: are acceptance criteria getting better? Are escalations declining? Reviews proposals about template guidance changes for the PRD structure.

### Engineer
Reads pipeline health: are retries declining? Are context misses decreasing? Reviews proposals about conventions and audit rules that affect how agents write code.

### Engineering Manager
Reads the portfolio trajectory: coverage, first-pass rates, escalation counts across features. Judges whether the team is improving or plateauing.

### Designer
Reads design spec gap patterns: how many features lack design specs, what visual decisions agents defaulted on without design guidance.

## User Stories

| ID | Story | Acceptance Criteria | Priority |
|----|-------|---------------------|----------|
| S1 | As any team member, I want to see the portfolio trajectory at a glance | Given multiple features have completed, when I open the Learning page, then the left panel shows coverage, first-pass rate, escalation count, and rework tasks with trend direction (up/down from earliest feature) | Must |
| S2 | As any team member, I want to read what the latest feature taught | Given the Defect Pipeline just completed, when I view the left panel, then I see per-feature lessons: specific findings with good/warn classification and supporting data | Must |
| S3 | As any team member, I want to see proposed changes the system recommends | Given the synthesis pipeline produced learnings, when I view the right panel, then I see proposal cards with type badge (TEMPLATE/CONVENTION/AUDIT), title, mechanism, the specific change text, and accept/dismiss buttons | Must |
| S4 | As any team member, I want to understand what "Accept" does before clicking | Given a proposal card, when I read the mechanism line, then I see exactly what file the change writes to (e.g., "writes to project-knowledge.json → conventions") at 11px secondary color, not hidden as a caption | Must |
| S5 | As any team member, I want to expand evidence per proposal to verify the justification | Given a proposal about error paths, when I click "Show evidence", then I see the specific observations, feature references, and weights that justify the proposal, inline within the card | Must |
| S6 | As any team member, I want lessons on the left to connect to proposals on the right via shared markers | Given lesson B says "User Flows still missing error paths" and proposal 1 says "Add error-path requirement to User Flows", when I view both panels, then both carry the same lettered ref-marker (B) | Should |
| S7 | As any team member, I want to dismiss a proposal I disagree with | Given a proposal about audit rules, when I click Dismiss, then the card animates out and the entry is logged to `synthesis-rejects.json` for audit trail | Must |
| S8 | As any team member, I want accepted proposals to collapse structurally | Given I accept a proposal, when the action completes, then the card collapses (change text, evidence trigger, and buttons hidden) showing only badge + title + "Accepted" | Must |
| S9 | As any team member, I want to see the portfolio narrative synthesized by the LLM | Given the LLM provider is configured, when the left panel renders, then I see a 2-3 paragraph narrative: trajectory summary, main gap, pipeline vs complexity classification | Should |

## User Flows

### The curation ceremony

1. Team opens the Learning page
2. Left panel shows trajectory: coverage 94% (up from 78%), first-pass 86% (up from 64%), escalations 0 (down from 3), rework 0 (down from 4)
3. Team reads the narrative: "Coverage rose from 78% to 94%. Main remaining gap: error paths in User Flows."
4. Team scrolls left panel to per-feature lessons: Given/When/Then success (marker A), error path gap (marker B), no design spec (marker C), audit-clean correlation
5. Team moves to right panel: 3 proposals
6. PM reads proposal 1 (marker B, TEMPLATE): "Add error-path requirement to User Flows." Mechanism: "writes to PRD template." Change text shows the exact guidance.
7. PM expands evidence: sees 6 observations across 3 features, combined weight 12.5, mini trend showing rework on billing and content
8. PM clicks Accept. Card collapses.
9. Engineer reads proposal 2 (marker A, CONVENTION): "Prefer Given/When/Then format." Accepts.
10. Team reads proposal 3 (marker C, AUDIT): "Flag missing design specs on features with CLI output." Discusses, decides to dismiss (design specs are not a priority yet). Clicks Dismiss. Card animates out.

### Expanding evidence

1. Team is looking at proposal 1 (error paths)
2. Clicks "Evidence - 6 observations across 3 features, combined weight 12.5"
3. Evidence panel expands inline: pattern description, mini trend chart (billing: 2 rework, content: 1 rework, defects: 0), individual observation rows with feature labels and weights
4. Team reads the evidence, satisfied the pattern is real, clicks Accept

## Success Criteria

- [ ] Two-panel layout: left (420px) narrative comprehension, right curation work area
- [ ] Left panel shows trajectory metrics in compact rows (not boxed grid)
- [ ] Left panel shows LLM narrative at 13px with 1.8 line-height (narrative is the star)
- [ ] Left panel shows per-feature lessons with good/warn classification and ref-markers
- [ ] Left panel shows failure classification: pipeline vs spec complexity
- [ ] Right panel shows proposal cards with type badge, title, mechanism, change text, evidence trigger, accept/dismiss
- [ ] Proposal mechanism is prominent (11px, secondary color, not tertiary)
- [ ] Change text uses violet-tinted block with left border
- [ ] Evidence is expandable per-proposal, collapsed by default
- [ ] Accepted proposals collapse structurally. Dismissed proposals animate out.
- [ ] Cross-panel ref-markers connect lessons to proposals
- [ ] Accept writes to the appropriate target: `project-knowledge.json`, template files, or `speed.toml`
- [ ] Dismiss writes to `synthesis-rejects.json`
- [ ] Page degrades gracefully without LLM: metrics + lessons render, narrative omitted
- [ ] Page loads within 500ms for a portfolio of 10 completed features

## Scope

### In Scope
- Two-panel layout (left: comprehension, right: curation)
- Portfolio trajectory metrics with trend direction
- LLM-synthesized portfolio narrative
- Per-feature lessons from most recently completed feature
- Failure classification (pipeline vs spec complexity)
- Proposal cards with type, mechanism, change text, evidence, accept/dismiss
- Accept mutation writing to 3 targets (project-knowledge.json, templates, speed.toml)
- Dismiss mutation writing to synthesis-rejects.json
- Cross-panel ref-markers
- GraphQL resolvers reading observations and learnings files

### Out of Scope
- Convention tagging (established/emerging/decaying) (future curation workflow)
- Human knowledge editing (`project-knowledge.json` direct editing) (future)
- Synthesis reject review workflow (future)
- Raw observation browsing (the 120+ observations are synthesized into narrative, not shown individually)
- Re-running the synthesis pipeline from the dashboard (CLI only)

## Dependencies

- Observation JSONL files at `.speed/memory/observations/{feature}.jsonl`
- Synthesized learnings at `.speed/memory/{agent}-learnings.json` (6 files)
- Synthesis metadata at `.speed/memory/synthesis-meta.json`
- Project knowledge at `.speed/memory/project-knowledge.json`
- LLM provider for portfolio narrative (`provider_chat()`)
- Template files at `specs/product/*.md`, `specs/tech/*.md` (for TEMPLATE proposals)
- `speed.toml` (for AUDIT proposals)
- Existing dashboard infrastructure

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Synthesis produces bad learnings that the team auto-accepts | Medium | Evidence is expandable per-proposal. The mechanism line shows exactly what changes. The team can dismiss and the entry goes to rejects log. |
| Template writes corrupt the PRD format | Medium | Accept mutation adds guidance text to a specific template section annotation, not arbitrary file content. The write is appending structured guidance, not rewriting the file. |
| Too many proposals overwhelm the team | Low | Synthesis applies a recurrence filter (2+ occurrences). Single-occurrence observations don't produce proposals. Typical project generates 3-7 proposals per completed feature. |
| Trajectory metrics mislead when few features exist | Medium | The section-agg shows "Based on N features." Trend direction is only shown when N >= 2. With 1 feature, the trajectory shows absolute values without trend arrows. |

## Security & Controls

**Authentication**: Dashboard runs locally. No additional auth.

**Authorization**: Any team member can view learnings. Accept/Dismiss mutations write to filesystem. No role-based access in V1.

**File writes**: Accept mutates `project-knowledge.json` (appends a JSON entry), template markdown (appends guidance text to a specific section), or `speed.toml` (adds/modifies an audit rule). All writes are append-only or section-scoped. No deletions or destructive overwrites.

**Audit trail**: Dismissed entries logged to `synthesis-rejects.json` with timestamp and reason. Accepted entries remain in the learnings files with `accepted: true` flag.

## Open Questions

| ID | Question | Impact | Status |
|----|----------|--------|--------|
| Q1 | Should the LLM narrative be cached per synthesis run or regenerated each page load? | Cached is cheaper. Regenerated reflects latest observation data. | Open |
| Q2 | How should the page handle concurrent curation (two team members accepting different proposals)? | File writes could conflict. V1 assumes single-user curation. Locking mechanism or last-write-wins for V2. | Open |
| Q3 | Should actionless lessons (observations without proposals) appear on the left panel or be omitted? | Current design: they fold into the narrative and per-feature lessons. If the system can't propose a change, the finding is context. | Decided: include as context |
| Q4 | Should proposals group by type (all TEMPLATE together, all CONVENTION together) or display in priority/weight order? | Weight order surfaces the highest-evidence proposals first. Type grouping helps the PM vs engineer reading pattern. | Open |
