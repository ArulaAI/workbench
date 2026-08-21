# Phase 4: GitHub Adapter

> Parent RFC: [Unified Intake & Defect Pipeline](../unified-intake.md)
> Depends on: [Phase 1: Spec Templates](speed-templates.md), [Phase 2: Audit Agent](speed-audit.md), [Phase 3: Defect Pipeline](speed-defects.md)

## Problem

Work lives in GitHub Issues. SPEED lives in markdown specs. Today, when someone files a GitHub issue, the path to SPEED is entirely manual: read the issue, open your editor, scaffold a spec with `speed new`, copy-paste fields, and remember to go back to GitHub to update the issue when the work is done. Nobody does the last part.

This creates two problems:

1. **Intake friction.** Every issue requires a manual transcription step. The title, body, labels, and comments are all sitting right there in GitHub, but the human has to re-enter them into a spec template by hand. This is busywork that discourages using SPEED for smaller issues.

2. **Status opacity.** Once work enters SPEED, the original GitHub issue goes dark. The person who filed the issue has no visibility into whether it's been triaged, is in progress, or was resolved — unless they check `.speed/` JSON files directly. Contributors, maintainers, and stakeholders who live in GitHub are cut off from progress.

The GitHub adapter solves both by bridging the two systems: fetch issue data into a spec scaffold, and push SPEED status back as issue comments and state changes.

## Users

### Product
Files feature requests as GitHub issues and expects visibility into delivery progress. Wants to see SPEED pipeline updates appear on the issue without checking a separate system. Needs confidence that closing an issue means the work actually shipped.

### Engineering
Triages and implements work from GitHub issues. Wants to pull an issue into SPEED with one command instead of manual copy-paste. Wants the issue to reflect the current pipeline state so teammates aren't asking "what's the status of #42?"

### Design
Files visual bugs and design improvement requests as GitHub issues. Wants the same intake path as engineering — one command to scaffold a spec from the issue, with labels determining the spec type.

## User Stories

| ID | Story | Acceptance Criteria | Priority |
|----|-------|---------------------|----------|
| S1 | As an engineer, I want to pull a GitHub issue into SPEED with one command so I don't have to manually transcribe title, body, and labels into a spec | Given a valid issue number, when I run `speed intake github #N`, then a spec file is created with title and body pre-filled from the issue | Must |
| S2 | As an engineer, I want SPEED to classify the issue as a defect or feature based on GitHub labels so the right template is used | Given an issue with `bug`/`defect`/`fix` labels, when ingested, then the defect template is used; given `feature`/`enhancement` labels, then the PRD template is used | Must |
| S3 | As an engineer, I want to override the auto-classification with `--as defect` or `--as feature` when labels are wrong or missing | Given any issue, when I pass `--as defect`, then the defect template is used regardless of labels | Must |
| S4 | As any team member, I want the scaffolded spec to contain a source reference back to the GitHub issue so the link is never lost | Given a scaffolded spec, when I inspect the file, then it contains `<!-- source: github#N -->` | Must |
| S5 | As a product person, I want SPEED to comment on the GitHub issue at pipeline stage transitions so I can follow progress without leaving GitHub | Given sync is enabled and a spec originated from GitHub, when a pipeline stage completes, then a comment is posted on the source issue | Should |
| S6 | As a product person, I want SPEED to close the GitHub issue when work is integrated so issue state reflects reality | Given sync is enabled and `close_on_resolve` is true, when `speed integrate` succeeds, then the source issue is closed with a summary comment | Should |
| S7 | As an engineer, I want sync to be opt-in so I can use intake without noisy comments on issues | Given no `[integrations.github]` config, when I use `speed intake github`, then no comments are posted to the issue | Should |
| S8 | As an engineer, I want a clear error when `gh` CLI is not installed or not authenticated | Given `gh` is not installed, when I run `speed intake github`, then I see an error with an install link and the command exits non-zero | Must |
| S9 | As any team member, I want to see which SPEED specs originated from GitHub issues in `speed status` | Given specs originated from GitHub, when I run `speed status`, then the source issue number is shown alongside the spec | Could |

## User Flows

### Intake a feature issue (happy path)

1. User runs `./speed/speed intake github #42`
2. SPEED checks `gh` CLI is installed and authenticated
3. SPEED fetches issue #42 via `gh issue view`
4. Issue has label `enhancement` — SPEED classifies as feature
5. SPEED scaffolds a PRD from the feature template
6. Title pre-fills the Feature Name, body pre-fills the Problem section
7. Source reference `<!-- source: github#42 -->` is embedded in the spec
8. SPEED opens the spec in `$EDITOR` for human editing
9. User completes the PRD, enters the standard feature pipeline

### Intake a defect issue

1. User runs `./speed/speed intake github #17`
2. SPEED fetches issue #17
3. Issue has label `bug` — SPEED classifies as defect
4. SPEED scaffolds a defect report from the defect template
5. Title pre-fills Short Description, body pre-fills Observed Behavior
6. Source reference embedded
7. SPEED opens for human editing
8. User completes the defect report, enters the defect pipeline

### Override classification

1. User runs `./speed/speed intake github #42 --as defect`
2. SPEED fetches issue #42 (which has label `enhancement`)
3. `--as defect` overrides label-based classification
4. SPEED scaffolds a defect report instead of a PRD
5. Proceeds as above

### Sync: pipeline updates comment on the issue

1. User has previously ingested issue #42 as a feature spec
2. `speed plan` completes — Architect produces a task graph
3. SPEED comments on issue #42: "Plan complete. 5 tasks, estimated scope: [summary]"
4. User runs `speed integrate` — work ships
5. SPEED comments on issue #42 with a summary and closes the issue

### Sync: defect triage comments on the issue

1. User has previously ingested issue #17 as a defect report
2. `speed defect` completes triage
3. SPEED comments on issue #17: "Triage complete. Classification: moderate, Root cause: [hypothesis]"
4. If the defect is escalated, SPEED comments with the explanation and adds label `needs-spec`
5. If the defect is rejected, SPEED comments with the explanation but does NOT close the issue

### Intake fails: `gh` not available

1. User runs `./speed/speed intake github #42`
2. `gh` CLI is not installed or `gh auth status` fails
3. SPEED prints a clear error: "`gh` CLI is required for GitHub integration. Install: https://cli.github.com/"
4. Exits with config error

### Intake fails: issue not found

1. User runs `./speed/speed intake github #9999`
2. `gh issue view 9999` returns an error
3. SPEED prints: "Issue #9999 not found in this repository."
4. Exits with error

## Success Criteria

- [ ] `./speed/speed intake github #N` fetches the issue and scaffolds a spec from the correct template
- [ ] Label-based classification maps `bug`/`defect`/`fix` labels to defect template, `feature`/`enhancement` labels to PRD template
- [ ] `--as defect` and `--as feature` flags override label-based classification
- [ ] When no labels match and no override is given, SPEED defaults to feature with a warning
- [ ] Scaffolded spec contains `<!-- source: github#42 -->` comment for source tracking
- [ ] Issue title pre-fills the spec's title field; issue body pre-fills the appropriate content section
- [ ] `$EDITOR` opens the scaffolded spec for human editing after pre-fill
- [ ] Clear error message when `gh` CLI is missing or not authenticated
- [ ] Clear error message when the issue number doesn't exist
- [ ] When sync is enabled, SPEED comments on the source issue at each pipeline stage transition (per sync table in parent RFC)
- [ ] When sync is enabled and work is integrated, SPEED closes the source issue with a summary comment
- [ ] Defect rejection does NOT close the source issue — only comments
- [ ] Escalation adds `needs-spec` label to the source issue
- [ ] Guardian rejection adds `needs-revision` label to the source issue
- [ ] Sync is opt-in via `[integrations.github]` config in `speed.toml`
- [ ] `close_on_resolve` config controls whether integration auto-closes the issue
- [ ] Adapter gracefully handles issues with no labels (defaults to feature with a warning)
- [ ] Adapter handles issues with multiple conflicting labels (e.g., both `bug` and `feature`) by preferring the `--as` override, then defaults to defect, with a warning

## Scope

### In Scope
- `speed intake github` CLI subcommand
- GitHub issue fetch via `gh` CLI
- Label-based classification (defect vs. feature)
- `--as defect` / `--as feature` override flags
- Spec scaffolding with pre-filled fields from issue data
- Source tracking via `<!-- source: github#N -->` comment
- Sync: comment on source issue at pipeline stage transitions
- Sync: close issue on integration (configurable)
- Sync: add labels on escalation/rejection
- `[integrations.github]` configuration in `speed.toml`
- Error handling for missing `gh`, auth failures, missing issues

### Out of Scope (and why)
- GitHub Pull Request intake — PRs are delivery artifacts, not intake sources; features and defects enter via issues
- Batch intake of multiple issues — one at a time matches SPEED's single-spec-at-a-time model
- Webhook-based intake (GitHub → SPEED automatically) — SPEED is CLI-driven, not a server; the human initiates
- Two-way body sync (editing the spec updates the issue body) — the spec is the source of truth once ingested; the issue is the external reference
- GitHub Projects board integration — status lives in SPEED, not in GitHub project boards
- Issue creation from SPEED (creating GitHub issues from specs) — SPEED consumes issues, doesn't produce them

## Dependencies

- Phase 1 (Spec Templates) — templates must exist for scaffolding
- Phase 2 (Audit Agent) — audit can validate the scaffolded spec before pipeline entry
- Phase 3 (Defect Pipeline) — defect template and pipeline must exist for defect-classified issues
- `gh` CLI — must be installed and authenticated (`gh auth status`)
- Existing SPEED pipeline infrastructure for sync hooks

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| `gh` CLI not installed in CI or team environments | Medium | Clear error message with install link. `gh` is widely available (Homebrew, apt, GitHub Actions pre-installed). Adapter is optional — SPEED works without it. |
| Label conventions vary across repos (e.g., `type: bug` vs. `bug`) | Medium | Start with common labels (`bug`, `defect`, `fix`, `feature`, `enhancement`). `--as` override handles non-standard labels. Future: configurable label mappings in `speed.toml`. |
| Sync comments are noisy on active issues | Low | Sync is opt-in. Comments are concise (1-3 lines). The human can disable sync per-project in config. |
| Issue body format varies wildly — pre-fill produces poor spec content | Low | Pre-fill is mechanical, not intelligent. The human is expected to rewrite. A bad pre-fill is still faster than a blank template. |
| Rate limiting on `gh` CLI calls during sync | Low | Sync happens at pipeline stage transitions (a handful per issue lifecycle), not continuously. Well within GitHub API limits. |
| Source reference `<!-- source: github#N -->` gets accidentally deleted during editing | Low | It's an HTML comment — invisible in rendered markdown, unlikely to be noticed and deleted. If lost, sync still works if the spec path matches the issue mapping in `.speed/` state. |
