# Phase 1: Spec Templates

> Parent RFC: [Unified Intake & Defect Pipeline](../unified-intake.md)

## Problem

Every SPEED spec starts from a blank page. Authors decide what sections to include, agents parse unpredictable formats. There are no canonical templates and no scaffolding command. This makes authoring slow and agent parsing unreliable.

## Users

### Product
Writes PRDs. Needs to know what sections the Architect and Guardian read, what's required, and where the file goes. Currently guesses at structure by looking at existing specs.

### Engineering
Writes RFCs. Needs to know what the Architect needs for task decomposition (data model, API surface, validation rules). Currently no canonical structure to follow.

### Design
Writes design specs. Needs to know what states and components to define, how to reference design tokens, and how to link back to the PRD.

### New SPEED User
Setting up SPEED for the first time. Needs a fast path from "I have a feature idea" to "I have a spec SPEED can plan from." Currently blocked by the blank-page problem.

## User Stories

| ID | Story | Priority |
|----|-------|----------|
| S1 | As a product person, I want to scaffold a PRD so that I get the right sections pre-filled with guidance comments | Must |
| S2 | As an engineer, I want to scaffold an RFC so that I know what the Architect needs (data model, API surface, validation) | Must |
| S3 | As a designer, I want to scaffold a design spec so that I know what states and components to define | Must |
| S4 | As an engineer, I want to scaffold a defect report so that I can describe a bug in 2 minutes with the right fields | Must |
| S5 | As an engineer, I want the scaffold command to open my editor automatically so I can start writing immediately | Should |
| S6 | As a new user, I want the templates to include guidance comments explaining what goes in each section | Must |

## User Flows

### Scaffold a new feature spec

1. User runs `./speed/speed new prd my-feature`
2. SPEED creates `specs/product/my-feature.md` from the PRD template
3. SPEED replaces `{Feature Name}` with "my-feature" (human-readable)
4. SPEED opens the file in `$EDITOR` (if set)
5. User fills in sections, saves, closes editor
6. User repeats for `rfc` and `design` if needed

### Scaffold a defect report

1. User runs `./speed/speed new defect invite-failure`
2. SPEED creates `specs/defects/invite-failure.md` from the defect template
3. SPEED opens the file in `$EDITOR`
4. User fills in observed behavior, expected behavior, reproduction steps
5. User runs `./speed/speed defect specs/defects/invite-failure.md` to enter the defect pipeline

## Success Criteria

- [ ] `speed new prd <name>` creates `specs/product/<name>.md` with all PRD template sections
- [ ] `speed new rfc <name>` creates `specs/tech/<name>.md` with all RFC template sections
- [ ] `speed new design <name>` creates `specs/design/<name>.md` with all design template sections
- [ ] `speed new defect <name>` creates `specs/defects/<name>.md` with all defect template sections
- [ ] Each template includes `<!-- ... -->` guidance comments explaining what goes in each section
- [ ] Placeholder variables (`{Feature Name}`, `{name}`) are replaced with the user-provided name
- [ ] Files open in `$EDITOR` after creation (if `$EDITOR` is set)
- [ ] If the target file already exists, the command warns and does not overwrite
- [ ] `specs/defects/` directory is created automatically if it doesn't exist
- [ ] Templates match the canonical formats defined in the parent RFC

## Scope

### In Scope
- Four templates: PRD, RFC, Design, Defect Report
- `speed new` CLI command with subcommands for each template type
- Template files stored in `speed/templates/`
- Placeholder replacement (`{Feature Name}`, `{name}`)
- `$EDITOR` integration
- Directory auto-creation for `specs/defects/`

### Out of Scope (and why)
- Spec validation — that's Phase 2 (Audit Agent)
- Auto-numbering features (`F{n}`) — feature numbers are semantic, set by the author
- Template versioning — agents parse markdown flexibly, not needed yet
- Validation of filled-in templates — `speed audit` handles this (Phase 2)

## Dependencies

None. This is Phase 1 — zero external dependencies, builds on existing SPEED CLI.

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Templates become stale as agents evolve | Low | Templates are guidance, not contracts. Agents parse flexibly. Update templates when agent prompts change significantly. |
| Users skip guidance comments and submit hollow specs | Medium | `speed audit` (Phase 2) catches structural gaps. The Architect's RFC review catches technical issues. Templates can't force quality, only enable it. |
