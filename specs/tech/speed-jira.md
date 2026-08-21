# RFC: JIRA Adapter

> See [product spec](../product/speed-jira.md) for product context.
> Depends on: [Phase 1: Spec Templates](speed-templates.md), [Phase 2: Audit Agent](speed-audit.md), [Phase 4: GitHub Adapter](speed-github.md)
> Parent RFC: [Unified Intake & Defect Pipeline](../unified-intake.md)

## Adapter Architecture

The JIRA adapter follows the adapter contract established in the parent RFC. Each adapter implements two functions: `adapter_fetch()` and `adapter_sync()`. The JIRA adapter lives at `speed/integrations/jira.sh` and is sourced by the main `speed/speed` script when the `intake jira` command is invoked.

### Adapter contract

These implement the `adapter_fetch()` / `adapter_sync()` contract from the [parent RFC](../unified-intake.md). Each adapter uses a prefixed name (`jira_fetch`, `github_fetch`, etc.) dispatched by `cmd_intake()`.

```bash
# Fetch a JIRA ticket and scaffold a spec
# Arguments: $1 = issue key (e.g., "PROJ-891"), $2 = optional type override ("defect" | "feature")
# Output: writes spec file, prints path
# Exit: EXIT_OK or EXIT_CONFIG_ERROR
jira_fetch() { ... }

# Push SPEED status to JIRA
# Arguments: $1 = spec file path, $2 = event type, $3 = event detail
# Output: transitions ticket and/or posts comment
# Exit: EXIT_OK (sync failures are warnings, not errors)
jira_sync() { ... }
```

## Configuration

### `speed.toml` section

```toml
[integrations.jira]
base_url = "https://company.atlassian.net"
api_key_env = "JIRA_API_KEY"           # env var name holding the API token
user_email_env = "JIRA_USER_EMAIL"     # env var name holding the user's email (required for Basic auth)
sync = true                             # enable bi-directional sync (default: false)

[integrations.jira.transitions]
in_progress = "31"                      # transition ID for "In Progress"
done = "41"                             # transition ID for "Done"
backlog = "11"                          # transition ID for "Backlog" (used for rejected defects)
```

All transition IDs are strings — JIRA returns and accepts them as strings despite being numeric. Every JIRA instance assigns different IDs to the same workflow states. Users discover their transition IDs via:

```bash
curl -u user@example.com:$JIRA_API_KEY \
  "https://company.atlassian.net/rest/api/3/issue/PROJ-1/transitions" \
  | jq '.transitions[] | {id, name}'
```

### Configuration validation

On every adapter invocation, validate:

1. `[integrations.jira]` section exists in `speed.toml` — if missing, exit with `EXIT_CONFIG_ERROR` and message: "JIRA integration not configured. Add [integrations.jira] to speed.toml."
2. `base_url` is set and non-empty — if missing, exit with `EXIT_CONFIG_ERROR`
3. `api_key_env` resolves to a non-empty env var — if missing, exit with `EXIT_CONFIG_ERROR` and message: "JIRA API key not found. Set the $VAR_NAME environment variable."
4. `user_email_env` resolves to a non-empty env var — if missing, exit with `EXIT_CONFIG_ERROR` and message: "JIRA user email not found. Set the $VAR_NAME environment variable."
5. For sync operations: `transitions` table exists and has the required key for the current operation — if missing, warn and skip the transition (still post the comment)

## CLI Command

### Command signature

```bash
./speed/speed intake jira <issue-key> [--as defect|feature] [--refresh]
```

### Implementation: `jira_fetch()`

Add to the `cmd_intake()` dispatcher in `speed/speed`:

```bash
cmd_intake() {
  local adapter="$1"
  shift
  case "$adapter" in
    github) source "$SPEED_DIR/integrations/github.sh"; github_fetch "$@" ;;
    linear) source "$SPEED_DIR/integrations/linear.sh"; linear_fetch "$@" ;;
    jira)   source "$SPEED_DIR/integrations/jira.sh";   jira_fetch "$@" ;;
    *)      _die "Unknown adapter: $adapter" ;;
  esac
}
```

### `jira_fetch()` implementation steps

1. **Parse arguments:** extract issue key, `--as` override, `--refresh` flag
2. **Load config:** read `[integrations.jira]` from `speed.toml`
3. **Validate credentials:** check `base_url`, resolve `api_key_env` and `user_email_env` to env var values
4. **Check for existing spec:** if a spec with `<!-- source: jira:<key> -->` already exists and `--refresh` is not set, print path and exit
5. **Fetch issue:** `GET /rest/api/3/issue/<key>?fields=summary,description,issuetype,priority,components,customfield_10014&expand=names`
   - `customfield_10014` is the standard Epic Link field (may vary — see Custom Fields section)
   - Authentication: HTTP Basic with `$JIRA_USER_EMAIL:$JIRA_API_KEY`
   - Handle errors: 401 → "Authentication failed", 404 → "Issue not found", other → print status and body
6. **Classify type:**
   - Read `issuetype.name` from response
   - If `--as` override provided, use that
   - Otherwise: "Bug" → defect, everything else ("Story", "Task", "Epic", "Sub-task", "Improvement") → feature
7. **Map priority to severity:**
   - "Highest", "Blocker" → P0
   - "High", "Critical" → P1
   - "Medium" → P2
   - "Low", "Lowest", "Trivial" → P3
   - Unknown → P2 (default to medium, log warning)
8. **Convert description:** ADF → markdown (see ADF Conversion section)
9. **Extract epic link:** from `customfield_10014` or the `parent` field (JIRA next-gen projects use `parent` instead of Epic Link)
10. **Extract components:** from `components[]` array → comma-separated list
11. **Scaffold spec:** load the appropriate template, fill in mapped fields
12. **Write spec file:**
    - Defect: `specs/defects/<key-lowercase>.md`
    - Feature: `specs/product/<key-lowercase>.md`
13. **Insert source reference:** `<!-- source: jira:<KEY> -->` as the first line after the title
14. **Print result:** "Scaffolded <type> spec from <KEY>. Edit: <path>"

### Field mapping detail

| JIRA Field | Spec Field (Defect) | Spec Field (Feature/PRD) |
|------------|--------------------|-----------------------|
| Summary | Title | Feature Name (title) |
| Description (ADF → md) | Observed Behavior | Problem |
| Priority | Severity (P0-P3) | _(not used — PRDs don't have severity)_ |
| Issue Type | _(determines template selection)_ | _(determines template selection)_ |
| Epic Link / Parent | Related Feature | _(context comment)_ |
| Components | Subsystem hints (comment) | Subsystem hints (comment) |
| Reporter | _(logged in source reference)_ | _(logged in source reference)_ |
| Comments | Additional context (appended) | Additional context (appended) |

### ADF-to-markdown conversion

JIRA Cloud uses Atlassian Document Format (ADF) — a JSON-based rich text format. The adapter must convert the most common ADF node types to markdown.

Implement `_jira_adf_to_md()` as a bash function using `jq` for JSON traversal:

| ADF Node Type | Markdown Output |
|---------------|----------------|
| `paragraph` | Text with trailing newline |
| `heading` (attrs.level) | `#` / `##` / `###` etc. |
| `bulletList` / `listItem` | `- ` prefixed lines |
| `orderedList` / `listItem` | `1. ` prefixed lines |
| `codeBlock` (attrs.language) | ` ```lang ... ``` ` fenced code block |
| `blockquote` | `> ` prefixed lines |
| `table` / `tableRow` / `tableCell` | Markdown table (best-effort) |
| `text` (with marks) | `**bold**`, `_italic_`, `` `code` ``, `[text](url)` |
| `hardBreak` | Newline |
| `mediaSingle` / `mediaGroup` | `[attachment: filename]` (placeholder — no download) |
| `rule` | `---` |
| _Unknown nodes_ | `[unsupported: <type>]` |

This conversion is best-effort. Complex nested structures (multi-level lists, merged table cells) may lose fidelity. The human reviews and cleans up during editing.

**Implementation approach:** The ADF-to-markdown conversion is non-trivial in pure bash. Two options:

1. **jq-based:** Write a recursive `jq` filter that walks the ADF JSON tree. Handles 80% of cases. Fragile for deeply nested content.
2. **Inline Python/Node snippet:** Shell out to a small Python or Node script for the conversion. More robust, adds a runtime dependency.

Recommendation: Start with the `jq`-based approach. If ADF complexity demands it, extract to a Python helper script at `speed/lib/adf_to_md.py` (Python is already a project dependency for the backend).

## Sync Implementation

### `jira_sync()` implementation

Called by the SPEED pipeline at stage transitions when `[integrations.jira].sync = true`.

1. **Resolve source ticket:** read the spec file, extract `<!-- source: jira:<KEY> -->`, parse the issue key
2. **If no source reference:** return silently (spec was not ingested from JIRA)
3. **Determine action** based on event type:

| Pipeline | Event | JIRA Transition | JIRA Comment |
|----------|-------|----------------|-------------|
| Feature | Plan complete | `in_progress` | "SPEED: Plan complete — {N} tasks, scope validated" |
| Feature | Run complete (all tasks) | _(none)_ | "SPEED: Development complete — all tasks passed quality gates" |
| Feature | Review complete | _(none)_ | "SPEED: Review passed" |
| Feature | Integrated | `done` | "SPEED: Integrated — branch merged, quality gates passed" |
| Feature | Guardian rejected | _(none)_ | "SPEED: Guardian flagged scope concern — {detail}" |
| Defect | Triage complete | `in_progress` | "SPEED: Triage complete — {complexity}, {root_cause_summary}" |
| Defect | Fix complete | _(none)_ | "SPEED: Fix applied, quality gates passed" |
| Defect | Integrated | `done` | "SPEED: Resolved — branch merged" |
| Defect | Escalated | `backlog` | "SPEED: Escalated to feature pipeline — {reason}" |
| Defect | Rejected | _(none — human decides)_ | "SPEED: Not a defect — {explanation}" |

4. **Post transition** (if applicable):
   ```
   POST /rest/api/3/issue/<KEY>/transitions
   Body: { "transition": { "id": "<transition_id>" } }
   ```
   - If transition ID is not configured for this event: warn and skip
   - If transition fails (400/409 — invalid transition from current state): warn with the error, do not retry
5. **Post comment:**
   ```
   POST /rest/api/3/issue/<KEY>/comment
   Body: { "body": { "type": "doc", "version": 1, "content": [{"type": "paragraph", "content": [{"type": "text", "text": "<message>"}]}] } }
   ```
   - Comments use ADF format for the request body (JIRA v3 API requirement)
   - If comment fails: warn, do not retry

### Sync integration points

Modify the following functions in `speed/speed` to call `jira_sync()` at the appropriate moments:

```bash
# In cmd_plan(), after successful plan:
_adapter_sync "$spec_file" "plan_complete" "task_count=$task_count"

# In cmd_integrate(), after successful merge:
_adapter_sync "$spec_file" "integrated" ""

# In cmd_defect(), after triage:
_adapter_sync "$spec_file" "triage_complete" "complexity=$complexity root_cause=$root_cause"
```

The `_adapter_sync()` helper detects which adapter to use from the `<!-- source: ... -->` comment:

```bash
_adapter_sync() {
  local spec_file="$1" event="$2" detail="$3"
  local source_ref
  source_ref=$(grep -o '<!-- source: [^ ]* -->' "$spec_file" 2>/dev/null | head -1)
  case "$source_ref" in
    *github*) source "$SPEED_DIR/integrations/github.sh"; github_sync "$@" ;;
    *linear*) source "$SPEED_DIR/integrations/linear.sh"; linear_sync "$@" ;;
    *jira*)   source "$SPEED_DIR/integrations/jira.sh";   jira_sync "$@" ;;
  esac
}
```

## JIRA API Details

### Authentication

JIRA Cloud uses HTTP Basic Authentication with API tokens:

```
Authorization: Basic base64($JIRA_USER_EMAIL:$JIRA_API_KEY)
```

The adapter constructs this header using:

```bash
local auth
auth=$(printf '%s:%s' "$jira_email" "$jira_api_key" | base64)
curl -s -H "Authorization: Basic $auth" -H "Content-Type: application/json" "$url"
```

### API endpoints used

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/rest/api/3/issue/<key>` | Fetch issue fields |
| GET | `/rest/api/3/issue/<key>/transitions` | List available transitions (for debugging) |
| POST | `/rest/api/3/issue/<key>/transitions` | Transition issue to new status |
| POST | `/rest/api/3/issue/<key>/comment` | Add comment |

### Error handling

| HTTP Status | Meaning | Adapter Response |
|-------------|---------|-----------------|
| 200/201 | Success | Continue |
| 401 | Bad credentials | `EXIT_CONFIG_ERROR`: "Authentication failed. Check JIRA_API_KEY and JIRA_USER_EMAIL." |
| 403 | No permission | `EXIT_CONFIG_ERROR` (credentials or permissions): "Permission denied for issue <KEY>. Check your JIRA permissions." |
| 404 | Issue not found | `EXIT_CONFIG_ERROR` (user input — issue key not found): "Issue <KEY> not found. Check the issue key." |
| 409 | Invalid transition | Warning: "Cannot transition <KEY> — current state does not allow transition <ID>. Skipping." |
| 429 | Rate limited | Warning: "JIRA rate limit hit. Retry after {seconds}s." Exit with `EXIT_CONFIG_ERROR`. |
| 5xx | Server error | Warning: "JIRA server error (<status>). Sync skipped." |

All sync errors are warnings — they do not block the SPEED pipeline. Fetch errors (during `intake`) are fatal since the adapter cannot proceed without the issue data.

### Epic Link field

JIRA's Epic Link is a custom field, but Atlassian assigns it a well-known ID (`customfield_10014`) on most Cloud instances. However, this is not guaranteed.

Strategy:
1. Attempt to read `customfield_10014` (Epic Link) from the issue response
2. If null, check `fields.parent` (next-gen/Team-managed projects use this instead)
3. If both are null, the issue has no epic — skip epic context
4. If the fetch response includes `names` (from `expand=names`), log the actual field name for debugging

Future enhancement: allow `epic_link_field` in `speed.toml` config for instances where the field ID differs.

## File Changes

| File | Change |
|------|--------|
| `speed/integrations/jira.sh` | New file — `jira_fetch()` and `jira_sync()` implementations |
| `speed/speed` | Add `jira` case to `cmd_intake()` dispatcher, add `_adapter_sync()` helper if not already present |
| `speed/lib/adf_to_md.py` | New file (if jq approach is insufficient) — ADF-to-markdown converter |
| `speed.toml` | Document `[integrations.jira]` section with all fields |
| `speed/agents/architect.md` | No change — Architect reads specs regardless of source |

## Dependencies

- Phase 1 (Spec Templates) — templates must exist for scaffolding
- Phase 2 (Audit Agent) — scaffolded specs can be validated via `speed audit` before entering the pipeline
- Phase 4 (GitHub Adapter) — establishes `_adapter_sync()` helper and `<!-- source: -->` convention
- `curl` — for JIRA REST API calls (standard on macOS/Linux)
- `jq` — for JSON parsing and ADF conversion (already a SPEED dependency)
- `base64` — for Basic auth header construction (standard utility)
- JIRA Cloud account with API token access
- `speed.toml` configuration parsing (must already exist from prior phases)

## Testing

### Manual testing checklist

Since the JIRA adapter depends on a live JIRA instance, automated testing is limited to unit tests for field mapping and ADF conversion. Integration testing is manual.

1. **Config validation:** remove each required config field, verify correct error message
2. **Fetch — Bug:** ingest a Bug-type ticket, verify defect template used, priority mapped correctly
3. **Fetch — Story:** ingest a Story-type ticket, verify PRD template used
4. **Fetch — override:** ingest a Story with `--as defect`, verify defect template used
5. **Fetch — 404:** use a non-existent issue key, verify error message
6. **Fetch — 401:** use bad credentials, verify error message
7. **ADF conversion:** ingest a ticket with rich description (headings, lists, code blocks, links), verify markdown output
8. **Sync — transition:** trigger a plan completion, verify JIRA ticket transitions
9. **Sync — comment:** trigger a plan completion, verify comment posted on JIRA ticket
10. **Sync — missing transition ID:** remove a transition ID from config, verify warning and comment still posted
11. **Sync — wrong transition ID:** use an invalid transition ID, verify warning logged

### Unit-testable functions

These functions can be tested with mock data (no JIRA instance required):

- `_jira_classify_type()` — issue type name → template type
- `_jira_map_priority()` — JIRA priority name → P0-P3
- `_jira_adf_to_md()` — ADF JSON → markdown string
- `_jira_build_spec()` — mapped fields → spec file content
