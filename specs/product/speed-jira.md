# Phase 7: JIRA Adapter

> Parent RFC: [Unified Intake & Defect Pipeline](../unified-intake.md)
> Depends on: [Phase 1: Spec Templates](speed-templates.md), [Phase 2: Audit Agent](speed-audit.md), [Phase 4: GitHub Adapter](speed-github.md)

## Problem

Enterprise teams live in JIRA. Their issues, epics, priorities, and workflows are already there — often with years of accumulated process encoded in custom fields and workflow transitions. Asking these teams to manually re-enter work into SPEED specs is a non-starter. They need SPEED to pull directly from JIRA and push status back, without requiring them to abandon their existing project management infrastructure.

But JIRA is not like GitHub or Linear. Every JIRA instance is different. Workflow transition IDs are instance-specific. Custom fields vary by project. Priority schemes differ across organizations. An adapter that assumes a standard JIRA configuration will break on first contact with a real enterprise setup. The adapter must be configurable enough to handle JIRA's per-instance complexity without becoming a configuration burden itself.

## Users

### Product
Manages work in JIRA. Files issues, sets priorities, tracks epics. Wants SPEED to ingest a JIRA ticket and produce a spec without copy-pasting fields between systems. Needs status updates pushed back to JIRA so stakeholders who only look at JIRA boards see progress.

### Engineering
Picks up JIRA tickets and builds from them. Wants to run `speed intake jira PROJ-891` and get a pre-filled spec with the right template, correct severity mapping, and epic context — then focus on filling in the technical details the Architect needs. Does not want to configure JIRA workflow IDs unless they have to.

### Design
Occasionally files visual bugs or UX issues in JIRA. Wants those tickets to flow into SPEED's defect pipeline with proper type classification, not be lost because the adapter only handles engineering tickets.

## User Stories

| ID | Story | Acceptance Criteria | Priority |
|----|-------|---------------------|----------|
| S1 | As an engineer, I want to ingest a JIRA ticket and get a pre-filled spec so I do not re-type what is already in the ticket | Given a valid JIRA key, when I run `speed intake jira <key>`, then a spec file is created with Summary, Description, Priority, and Components mapped to the correct sections | Must |
| S2 | As an engineer, I want JIRA Priority to map to SPEED severity (P0-P3) so triage starts with the right urgency | Given a JIRA ticket with Priority "Highest", when ingested, then the spec severity is set to P0; similarly High→P1, Medium→P2, Low/Lowest→P3 | Must |
| S3 | As an engineer, I want Issue Type to determine the spec template (Bug → defect, Story/Task → feature) so the right sections are scaffolded | Given a Bug-type ticket, when ingested, then the defect template is used; given a Story/Task/Epic, then the PRD template is used | Must |
| S4 | As an engineer, I want to override the auto-detected type with `--as defect` or `--as feature` | Given any ticket, when I pass `--as defect`, then the defect template is used regardless of Issue Type | Must |
| S5 | As a product person, I want SPEED pipeline status pushed back to JIRA as transitions so the board reflects reality | Given `sync = true` and valid transition IDs, when a pipeline stage completes, then the JIRA ticket is transitioned to the corresponding status | Should |
| S6 | As a product person, I want SPEED to comment on the JIRA ticket at key pipeline stages (triage complete, review done, integrated) | Given `sync = true`, when a pipeline stage completes, then a comment summarizing the stage outcome is posted on the JIRA ticket | Should |
| S7 | As an engineer, I want Epic Link extracted from the ticket so the spec links to the related feature automatically | Given a ticket with an Epic Link or parent field, when ingested, then the spec includes a reference to the related epic/feature | Should |
| S8 | As an engineer, I want Components mapped to subsystem hints so the Architect has context about which part of the codebase is affected | Given a ticket with Components, when ingested, then the spec includes the component names as subsystem hints | Should |
| S9 | As an engineer, I want to configure JIRA workflow transition IDs in `speed.toml` because every JIRA instance uses different IDs | Given transition IDs in `[integrations.jira.transitions]`, when sync triggers, then those IDs are used for JIRA API transition calls | Must |
| S10 | As an engineer, I want clear error messages when JIRA credentials are missing or the API returns an error | Given missing `JIRA_API_KEY` env var, when I run intake, then a specific error message names the missing variable and links to Atlassian docs | Must |
| S11 | As an engineer, I want to force-refresh a previously ingested ticket with `--refresh` in case the JIRA ticket was updated | Given a previously ingested ticket, when I run intake with `--refresh`, then the spec is re-scaffolded with the latest JIRA data | Could |
| S12 | As a designer, I want JIRA tickets with "Design" or "UX" components to hint at visual defect type so triage classifies correctly | Given a ticket with a "Design" or "UX" component, when ingested as a defect, then the spec includes a hint for visual defect classification | Could |

## User Flows

### Ingest a JIRA bug as a defect spec

1. User runs `./speed/speed intake jira PROJ-891`
2. Adapter reads `[integrations.jira]` config from `speed.toml` — base URL, API key env var, user email env var
3. Adapter fetches issue via JIRA REST API: `GET /rest/api/3/issue/PROJ-891`
4. Adapter reads Issue Type: "Bug" → selects defect template
5. Adapter maps fields:
   - Summary → spec title
   - Description (Atlassian Document Format → markdown) → Observed Behavior section
   - Priority ("Highest" → P0, "High" → P1, "Medium" → P2, "Low"/"Lowest" → P3) → Severity
   - Epic Link → Related Feature hint
   - Components → subsystem hints (comment in spec)
6. Adapter writes spec to `specs/defects/proj-891.md`
7. Adapter stores source reference: `<!-- source: jira:PROJ-891 -->`
8. Adapter prints: "Scaffolded defect spec from PROJ-891. Edit: specs/defects/proj-891.md"
9. Human reviews and fills in missing sections (Expected Behavior, Reproduction Steps)

### Ingest a JIRA story as a feature spec

1. User runs `./speed/speed intake jira PROJ-500`
2. Adapter fetches issue, reads Issue Type: "Story" → selects PRD template
3. Adapter maps fields:
   - Summary → Feature Name
   - Description → Problem section
   - Epic Link → parent feature context
   - Components → subsystem hints
4. Adapter writes spec to `specs/product/proj-500.md`
5. Human fills in User Stories, Success Criteria, Scope, and all other sections the Architect needs

### Override auto-detected type

1. User runs `./speed/speed intake jira PROJ-891 --as feature`
2. Adapter fetches issue as usual
3. Adapter uses PRD template regardless of Issue Type
4. Adapter maps fields to PRD sections instead of defect sections
5. Human edits the spec

### Sync status back to JIRA

1. Engineer runs `./speed/speed plan specs/tech/proj-891.md` — plan completes
2. SPEED checks `speed.toml`: `[integrations.jira].sync = true`
3. Adapter resolves source ticket from `<!-- source: jira:PROJ-891 -->` in the spec
4. Adapter transitions JIRA ticket to "In Progress" using configured transition ID from `transitions.in_progress`
5. Adapter posts comment: "SPEED: Plan complete — 5 tasks, scope validated"
6. Later, `./speed/speed integrate` completes
7. Adapter transitions to "Done" using `transitions.done`
8. Adapter posts comment: "SPEED: Integrated — branch merged, quality gates passed"

### Configuration error — missing credentials

1. User runs `./speed/speed intake jira PROJ-891`
2. Adapter reads `[integrations.jira]` — finds `api_key_env = "JIRA_API_KEY"`
3. `$JIRA_API_KEY` is not set in the environment
4. Adapter prints: "JIRA API key not found. Set the JIRA_API_KEY environment variable. See: https://support.atlassian.com/atlassian-account/docs/manage-api-tokens-for-your-atlassian-account/"
5. Exits with `EXIT_CONFIG_ERROR`

### Configuration error — missing transition IDs during sync

1. SPEED pipeline reaches a sync point (e.g., plan complete)
2. Adapter reads `[integrations.jira].transitions` — `in_progress` key is missing
3. Adapter prints warning: "JIRA sync: transition ID for 'in_progress' not configured in speed.toml. Skipping transition. Comment still posted."
4. Adapter posts the comment but does not attempt the transition
5. Pipeline continues — sync failures do not block the pipeline

## Success Criteria

- [ ] `speed intake jira PROJ-891` fetches the ticket and scaffolds a spec from the correct template
- [ ] Issue Type "Bug" maps to defect template; "Story", "Task", "Epic" map to PRD template
- [ ] JIRA Priority maps to SPEED severity: Highest → P0, High → P1, Medium → P2, Low/Lowest → P3
- [ ] Summary, Description, Epic Link, and Components are extracted and placed in the correct spec sections
- [ ] JIRA Atlassian Document Format (ADF) description is converted to readable markdown
- [ ] `--as defect` and `--as feature` override auto-detected type
- [ ] Source reference `<!-- source: jira:PROJ-891 -->` is stored in the scaffolded spec
- [ ] With `sync = true`, SPEED transitions the JIRA ticket at pipeline stage changes using configured transition IDs
- [ ] With `sync = true`, SPEED posts comments on the JIRA ticket at key pipeline stages
- [ ] Missing or invalid JIRA credentials produce a clear error message and exit with `EXIT_CONFIG_ERROR`
- [ ] Missing transition IDs produce a warning but do not block the pipeline — comments are still posted
- [ ] Adapter handles JIRA API errors gracefully (404 for bad ticket, 401 for bad auth, rate limits)
- [ ] `speed.toml` `[integrations.jira]` section is documented with all required and optional fields
- [ ] Adapter works with JIRA Cloud (Atlassian-hosted) — on-premise JIRA Server is out of scope

## Scope

### In Scope
- JIRA REST API v3 integration (Cloud only)
- `speed intake jira <key>` CLI command
- Field mapping: Summary, Description, Priority, Issue Type, Epic Link, Components
- ADF-to-markdown conversion for Description field
- Type classification from Issue Type (Bug → defect, Story/Task/Epic → feature)
- `--as defect` / `--as feature` type override
- Priority-to-severity mapping (JIRA priorities → P0-P3)
- Source reference tracking (`<!-- source: jira:PROJ-891 -->`)
- Bi-directional sync: transitions + comments pushed back to JIRA
- Configurable transition IDs in `speed.toml`
- Credential validation and clear error messages
- `[integrations.jira]` configuration block in `speed.toml`

### Out of Scope (and why)
- JIRA Server / Data Center — Phase 7 targets Cloud-first; Server support adds authentication complexity (OAuth 1.0a, session tokens) that is not justified until demand exists
- Custom field extraction — every JIRA instance defines custom fields differently; a generic custom field mapper is a project unto itself and can be added later
- JQL-based bulk import — one ticket at a time matches the adapter architecture; bulk import is a different workflow
- JIRA webhook listener — SPEED is pull-based (user runs a command), not event-driven; webhooks require a running server
- Sprint or board management — SPEED is not a project management tool
- Attachment download — specs are text; screenshots in JIRA should be re-described in the spec

## Dependencies

- Phase 1 (Spec Templates) — templates must exist for scaffolding
- Phase 2 (Audit Agent) — scaffolded specs run through audit before entering the pipeline
- Phase 4 (GitHub Adapter) — establishes the adapter architecture (`adapter_fetch()` / `adapter_sync()` contract) that JIRA follows
- `curl` or equivalent for JIRA REST API calls
- JIRA Cloud account with API token access
- `speed.toml` configuration support (must already exist from Phase 5+ or be added)

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Every JIRA instance has different workflow transition IDs | High | Transition IDs are fully configurable in `speed.toml`. Adapter never assumes hardcoded IDs. Missing IDs produce warnings, not errors. |
| JIRA Description uses Atlassian Document Format (ADF), not markdown | Medium | Implement ADF-to-markdown conversion for common node types (paragraph, heading, list, code block, table). Unsupported nodes render as `[unsupported: node_type]` — the human cleans up during editing. |
| JIRA API rate limits on large instances | Low | Adapter makes 1-2 API calls per intake (issue fetch, optional epic fetch). Sync adds 1-2 calls per stage. Well within rate limits. |
| Enterprise JIRA instances require network access (VPN, allowlists) | Medium | Out of scope for the adapter. If the user can `curl` the JIRA API from their machine, the adapter works. Network access is the user's responsibility. Document this clearly. |
| JIRA custom fields hold critical data the adapter misses | Medium | Start with standard fields only. Log a note in the scaffolded spec: "Custom fields not extracted — review the JIRA ticket for additional context." Add custom field support in a future iteration if demand warrants. |
| Users configure wrong transition IDs and transitions fail silently | Low | Adapter logs the HTTP response from failed transitions. Add a `speed intake jira --test-config` command that attempts a dry-run transition check (future enhancement, not Phase 7 scope). |
