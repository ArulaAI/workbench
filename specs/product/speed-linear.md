# Phase 5: Linear Adapter

> Parent RFC: [Unified Intake & Defect Pipeline](../unified-intake.md)
> Depends on: [Phase 1: Spec Templates](speed-templates.md), [Phase 4: GitHub Adapter](speed-github.md)

## Problem

SPEED can scaffold specs from templates and process them through feature and defect pipelines, but work that originates in Linear stays disconnected. Teams using Linear for project management must manually copy ticket details into SPEED specs and manually update Linear when SPEED reaches milestones. This creates duplicate bookkeeping and stale status in the tracker.

The GitHub adapter (Phase 4) established the adapter plugin model: `adapter_fetch()` pulls data and scaffolds a spec, `adapter_sync()` pushes status back. The Linear adapter validates that this plugin model generalizes beyond GitHub. If it works cleanly for Linear, the architecture is proven for JIRA and future adapters.

## Users

### Product
Manages work in Linear. Wants to pull a Linear ticket into SPEED without re-typing the title, description, and priority. Wants to see SPEED progress reflected back in Linear as status transitions and comments, so the tracker stays current without manual updates.

### Engineering
Receives tickets in Linear, needs to process them through SPEED's structured pipeline. Wants a single command to fetch a ticket, classify it (feature or defect), scaffold the right spec template, and pre-fill what's available. Wants to stay in the terminal, not context-switch to the Linear UI to copy-paste fields.

### Design
Files visual/UX issues in Linear. Wants those tickets to flow into SPEED's defect pipeline with the right severity and type hints preserved from Linear labels.

## User Stories

| ID | Story | Acceptance Criteria | Priority |
|----|-------|---------------------|----------|
| S1 | As an engineer, I want to run `speed intake linear LIN-423` and get a scaffolded spec pre-filled from the Linear ticket | Given a valid Linear ticket ID, when I run `speed intake linear LIN-423`, then a spec file is created with title and description pre-filled from the ticket | Must |
| S2 | As an engineer, I want the adapter to classify the ticket as feature or defect based on Linear labels | Given a ticket with `bug`/`defect`/`fix` labels, when fetched, then it scaffolds a defect spec; given `feature`/`enhancement` labels, then it scaffolds a PRD | Must |
| S3 | As an engineer, I want to force the type with `--as defect` or `--as feature` when labels are ambiguous | Given any ticket, when I pass `--as defect`, then label classification is skipped and a defect spec is scaffolded | Must |
| S4 | As Product, I want Linear ticket priority (Urgent/High/Medium/Low/No priority) mapped to P0-P3 severity for defect specs | Given a ticket with priority "Urgent", when scaffolded as defect, then severity is set to P0; similarly High->P1, Medium->P2, Low/None->P3 | Must |
| S5 | As Product, I want SPEED stage transitions to update the Linear ticket status (In Progress, Done, Backlog) | Given sync is enabled and a spec reaches "plan complete", when the pipeline runs, then the Linear ticket status transitions to "In Progress" | Should |
| S6 | As Product, I want SPEED to post comments on the Linear ticket at each pipeline milestone | Given sync is enabled, when a pipeline milestone is reached, then a comment is posted on the Linear ticket describing the milestone | Should |
| S7 | As an engineer, I want the scaffolded spec to include a source reference so I can trace it back to the Linear ticket | Given a scaffolded spec, when I inspect the file, then it contains `<!-- source: linear#LIN-423 -->` | Must |
| S8 | As an engineer, I want clear error messages when the Linear API key is missing or the ticket ID is invalid | Given no API key is set, when I run intake, then I see an error naming the expected env var; given an invalid ticket ID, then I see the API error | Must |
| S9 | As an engineer, I want Linear comments on the ticket included as additional context in the scaffolded spec | Given a ticket with comments, when scaffolded, then comments appear in an "Additional Context" section with author and timestamp | Should |

## User Flows

### Fetch a feature ticket from Linear

1. User runs `./speed/speed intake linear LIN-423`
2. SPEED reads `[integrations.linear]` config from `speed.toml` for API key env var and team ID
3. SPEED calls the Linear API to fetch ticket LIN-423 (title, description, priority, labels, comments, status)
4. Adapter classifies based on labels: `feature`, `enhancement` labels hint at PRD template
5. Adapter scaffolds `specs/product/<name>.md` from PRD template, pre-fills:
   - Title -> spec title
   - Description -> Problem section body
   - Comments -> appended as "Additional Context" section
6. Adapter writes source reference: `<!-- source: linear#LIN-423 -->`
7. File opens in `$EDITOR` for human editing
8. Human completes the spec, proceeds to `speed audit` and the feature pipeline

### Fetch a defect ticket from Linear

1. User runs `./speed/speed intake linear LIN-423`
2. SPEED fetches the ticket via Linear API
3. Adapter classifies based on labels: `bug`, `defect`, `fix` labels hint at defect template
4. Adapter scaffolds `specs/defects/<name>.md` from defect template, pre-fills:
   - Title -> defect title
   - Description -> Observed Behavior section
   - Priority -> Severity (Urgent -> P0, High -> P1, Medium -> P2, Low/None -> P3)
   - Comments -> Additional Context
5. Source reference stored: `<!-- source: linear#LIN-423 -->`
6. File opens in `$EDITOR`
7. Human completes the report, proceeds to `speed defect`

### Force type classification

1. User runs `./speed/speed intake linear LIN-423 --as defect`
2. Adapter skips label-based classification, uses defect template directly
3. Pre-fill proceeds as normal

### Sync: SPEED updates Linear ticket status

1. SPEED reaches a pipeline milestone (e.g., plan complete, triage done, integrated)
2. SPEED checks `[integrations.linear].sync` in `speed.toml` — if `true`, sync proceeds
3. SPEED reads the `<!-- source: linear#LIN-423 -->` reference from the spec
4. Adapter calls Linear API to transition the ticket status and post a comment
5. If the API call fails, SPEED logs a warning and continues (sync failure is non-blocking)

### Missing or invalid configuration

1. User runs `./speed/speed intake linear LIN-423`
2. `[integrations.linear]` section missing from `speed.toml` -> print error with setup instructions, exit
3. Or: env var named in `api_key_env` is not set -> print error naming the expected env var, exit
4. Or: ticket ID doesn't exist in Linear -> print API error, exit

## Success Criteria

- [ ] `speed intake linear LIN-423` fetches the ticket and scaffolds a spec from the correct template
- [ ] Label-based classification routes `bug`/`defect`/`fix` labels to defect template, `feature`/`enhancement` to PRD template
- [ ] `--as defect` and `--as feature` flags override label-based classification
- [ ] Linear priority maps to severity: Urgent -> P0, High -> P1, Medium -> P2, Low/None -> P3
- [ ] Title pre-fills the spec title, description pre-fills the appropriate body section
- [ ] Linear comments are included as additional context in the scaffolded spec
- [ ] `<!-- source: linear#LIN-423 -->` reference is embedded in the scaffolded spec
- [ ] File opens in `$EDITOR` after scaffolding (if `$EDITOR` is set)
- [ ] If `sync = true`, status transitions post comments and update ticket status in Linear
- [ ] Sync failure logs a warning and does not block the pipeline
- [ ] Missing `[integrations.linear]` config prints a clear error with setup instructions
- [ ] Missing API key env var prints a clear error naming the expected variable
- [ ] Invalid ticket ID prints the Linear API error
- [ ] Adapter reuses the same `adapter_fetch()` / `adapter_sync()` interface established by the GitHub adapter (Phase 4)

## Scope

### In Scope
- Linear adapter implementation (`speed/integrations/linear.sh`)
- `speed intake linear <ticket-id>` CLI command
- Linear API integration for fetching tickets (title, description, priority, labels, comments, status)
- Label-based classification (feature vs. defect) with `--as` override
- Priority-to-severity mapping for defect specs
- Spec scaffolding from templates with pre-filled fields
- Source reference tracking (`<!-- source: linear#LIN-423 -->`)
- Bidirectional sync: status transitions + comments posted back to Linear
- Configuration via `[integrations.linear]` in `speed.toml`

### Out of Scope (and why)
- Linear webhook support (real-time push) -- on-demand fetch is sufficient per the parent RFC
- Linear project/cycle sync -- SPEED is not a project management tool
- Batch import of multiple tickets -- one at a time, per the parent RFC pattern
- Creating Linear tickets from SPEED -- adapters pull in and push status, they don't create work items
- Linear OAuth flow -- API keys managed via env vars per the parent RFC's auth strategy
- Team-level operations (listing tickets, searching) -- the adapter fetches a single known ticket

## Dependencies

- Phase 1 (Spec Templates) -- templates must exist for scaffolding
- Phase 4 (GitHub Adapter) -- establishes the `adapter_fetch()` / `adapter_sync()` plugin interface that this adapter implements
- Linear API key (set via env var referenced in `speed.toml`)
- `curl` for HTTP requests to the Linear GraphQL API

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Linear API rate limiting blocks fetch or sync | Low | Single-ticket fetch is one API call. Sync posts one comment per stage transition. Well within limits. If rate-limited, log warning and continue. |
| Linear's GraphQL API changes field names or schema | Low | Pin to stable fields (title, description, priority, labels, comments). Linear's API is versioned and stable. |
| Label conventions vary across teams (no standard `bug` label) | Medium | `--as` override allows explicit classification. Document recommended label conventions. Adapter uses fuzzy matching (case-insensitive, partial match). |
| GitHub adapter (Phase 4) plugin interface doesn't generalize cleanly to Linear | Medium | This is the explicit goal of Phase 5: validate the plugin model. If the interface needs adjustment, change it in Phase 5 and update Phase 4 to match. |
| Linear priority model (1-4 + 0 for none) doesn't map cleanly to P0-P3 | Low | Direct mapping: 1 (Urgent) -> P0, 2 (High) -> P1, 3 (Medium) -> P2, 4 (Low) and 0 (None) -> P3. Documented and overridable in the spec. |
