# RFC: Linear Adapter

> See [product spec](../product/speed-linear.md) for product context.
> Depends on: [Phase 1: Spec Templates](speed-templates.md), [Phase 4: GitHub Adapter](speed-github.md)
> Parent RFC: [Unified Intake & Defect Pipeline](../unified-intake.md)

## Adapter Interface

The Linear adapter implements the same two-function interface established by the GitHub adapter (Phase 4):

```bash
adapter_fetch()     # Pull ticket from Linear → scaffold spec from template
adapter_sync()      # Push SPEED status → Linear (status transition + comment)
```

**File:** `speed/integrations/linear.sh`

This is the second adapter. If the interface generalizes cleanly from GitHub to Linear, the plugin model is validated for JIRA (Phase 7) and future adapters.

## CLI Command

### Command signature

```bash
./speed/speed intake linear <ticket-id> [--as feature|defect]
```

### Implementation

The `intake` command already exists (added in Phase 4 for GitHub). It dispatches to the appropriate adapter based on the second argument:

```bash
cmd_intake() {
  local adapter="$1"
  local ticket_id="$2"
  # ... existing dispatch logic ...
  case "$adapter" in
    github) source "$SPEED_DIR/integrations/github.sh" ;;
    linear) source "$SPEED_DIR/integrations/linear.sh" ;;  # NEW
    *) _fatal "Unknown adapter: $adapter" ;;
  esac
  adapter_fetch "$ticket_id" "${@:3}"
}
```

## Linear API Integration

### Authentication

Linear uses a personal API key passed as a Bearer token. The key is stored in an env var; the env var name is configured in `speed.toml`.

```toml
[integrations.linear]
api_key_env = "LINEAR_API_KEY"
sync = true
team_id = "TEAM_ID"
```

At runtime:
```bash
local api_key_env
api_key_env=$(_config_get "integrations.linear.api_key_env" "LINEAR_API_KEY")
local api_key="${!api_key_env}"
[[ -n "$api_key" ]] || _fatal "Linear API key not set. Export $api_key_env in your environment."
```

### GraphQL Query: Fetch Ticket

Linear's API is GraphQL. Fetch a single issue by identifier:

```graphql
query IssueByIdentifier($id: String!) {
  issueByIdentifier(id: $id) {
    id
    identifier
    title
    description
    priority
    priorityLabel
    state {
      name
      type
    }
    labels {
      nodes {
        name
      }
    }
    comments {
      nodes {
        body
        user {
          name
        }
        createdAt
      }
    }
    url
  }
}
```

Implementation via `curl`:

```bash
linear_api() {
  local query="$1"
  local variables="$2"
  local api_key="${!api_key_env}"

  curl -s -X POST https://api.linear.app/graphql \
    -H "Authorization: Bearer $api_key" \
    -H "Content-Type: application/json" \
    -d "{\"query\": \"$query\", \"variables\": $variables}"
}
```

### Error handling

| Condition | Response |
|-----------|----------|
| `[integrations.linear]` missing from `speed.toml` | `_fatal "Linear integration not configured. Add [integrations.linear] to speed.toml."` |
| API key env var not set | `_fatal "Linear API key not set. Export $api_key_env in your environment."` |
| Ticket not found (API returns null) | `_fatal "Linear ticket $ticket_id not found."` |
| API request fails (network error, 401, etc.) | `_fatal "Linear API error: $http_status — $error_message"` |
| API returns unexpected schema | `_fatal "Unexpected Linear API response. Check API key permissions."` |

## Fetch: `adapter_fetch()`

### Field mapping

| Linear field | Spec field (PRD) | Spec field (Defect) |
|-------------|------------------|---------------------|
| `title` | Spec title (`# F{n}: {title}`) -- `{n}` left as placeholder, author sets feature number | Defect title (`# Defect: {title}`) |
| `description` | Problem section body | Observed Behavior section body |
| `priority` (1-4, 0) | Not used for features | Severity: 1->P0, 2->P1, 3->P2, 4/0->P3 |
| `labels[].name` | Classification hint | Classification hint |
| `comments[].body` | Additional Context section | Additional Context section |
| `state.name` | Not used | Not used (SPEED manages its own state) |
| `url` | Source reference comment | Source reference comment |

### Priority-to-severity mapping

Linear priorities are integers 0-4:

| Linear priority | Linear label | SPEED severity |
|----------------|-------------|----------------|
| 1 | Urgent | P0 (critical) |
| 2 | High | P1 (high) |
| 3 | Medium | P2 (moderate) |
| 4 | Low | P3 (low) |
| 0 | No priority | P3 (low) |

### Label-based classification

Scan `labels[].name` for type hints (case-insensitive):

| Label matches | Template |
|---------------|----------|
| `bug`, `defect`, `fix` | Defect (`speed/templates/defect.md`) |
| `feature`, `enhancement` | PRD (`speed/templates/prd.md`) |
| No match | Default to PRD (features are more common) |

The `--as feature` or `--as defect` flag overrides label classification.

### Scaffolding process

```bash
adapter_fetch() {
  local ticket_id="$1"
  local force_type=""

  # Parse --as flag
  while [[ $# -gt 1 ]]; do
    case "$2" in
      --as) force_type="$3"; shift 2 ;;
      *) shift ;;
    esac
  done

  # 1. Validate config
  _require_linear_config

  # 2. Fetch ticket from Linear API
  local response
  response=$(linear_api "$ISSUE_QUERY" "{\"id\": \"$ticket_id\"}")
  local issue
  issue=$(echo "$response" | jq -r '.data.issueByIdentifier')
  [[ "$issue" != "null" ]] || _fatal "Linear ticket $ticket_id not found."

  # 3. Extract fields
  local title description priority labels comments url
  title=$(echo "$issue" | jq -r '.title')
  description=$(echo "$issue" | jq -r '.description // ""')
  priority=$(echo "$issue" | jq -r '.priority')
  labels=$(echo "$issue" | jq -r '[.labels.nodes[].name] | join(",")')
  comments=$(echo "$issue" | jq -r '[.comments.nodes[] | "**\(.user.name)** (\(.createdAt)):\n\(.body)"] | join("\n\n---\n\n")')
  url=$(echo "$issue" | jq -r '.url')

  # 4. Classify type
  local spec_type
  if [[ -n "$force_type" ]]; then
    spec_type="$force_type"
  else
    spec_type=$(_classify_labels "$labels")
  fi

  # 5. Derive name from ticket ID
  local name
  name=$(echo "$ticket_id" | tr '[:upper:]' '[:lower:]' | tr '-' '-')

  # 6. Scaffold from template
  local template output_dir
  case "$spec_type" in
    defect)
      template="$SPEED_DIR/templates/defect.md"
      output_dir="specs/defects"
      ;;
    feature|*)
      template="$SPEED_DIR/templates/prd.md"
      output_dir="specs/product"
      ;;
  esac

  mkdir -p "$output_dir"
  local output_file="$output_dir/$name.md"
  [[ ! -f "$output_file" ]] || _fatal "File already exists: $output_file"

  # 7. Copy template and pre-fill
  cp "$template" "$output_file"
  _prefill_spec "$output_file" "$spec_type" "$title" "$description" "$priority" "$comments"

  # 8. Add source reference
  echo "" >> "$output_file"
  echo "<!-- source: linear#$ticket_id -->" >> "$output_file"

  # 9. Open in editor
  _open_editor "$output_file"

  _info "Scaffolded $spec_type spec from Linear ticket $ticket_id: $output_file"
}
```

### Pre-fill logic

```bash
_prefill_spec() {
  local file="$1" type="$2" title="$3" desc="$4" priority="$5" comments="$6"

  # Replace title placeholder (defect template uses {Short Description}, PRD uses {Feature Name})
  if [[ "$type" == "defect" ]]; then
    sed -i.bak "s/{Short Description}/$title/g" "$file"
  else
    sed -i.bak "s/{Feature Name}/$title/g" "$file"
  fi
  rm -f "$file.bak"

  if [[ "$type" == "defect" ]]; then
    # Map priority to severity
    local severity
    case "$priority" in
      1) severity="P0" ;;
      2) severity="P1" ;;
      3) severity="P2" ;;
      *) severity="P3" ;;
    esac
    # Pre-fill severity field
    sed -i.bak "s/{severity}/$severity/" "$file"
    rm -f "$file.bak"
    # Pre-fill observed behavior with description
    _insert_after_heading "$file" "Observed Behavior" "$desc"
  else
    # Pre-fill problem section with description
    _insert_after_heading "$file" "Problem" "$desc"
  fi

  # Append comments as additional context (if any)
  if [[ -n "$comments" && "$comments" != "[]" ]]; then
    echo "" >> "$file"
    echo "## Additional Context (from Linear)" >> "$file"
    echo "" >> "$file"
    echo "$comments" >> "$file"
  fi
}
```

## Sync: `adapter_sync()`

### When sync runs

Sync is called by the SPEED pipeline at stage transitions. The pipeline checks for a `<!-- source: linear#... -->` reference in the spec and dispatches to the correct adapter's `adapter_sync()`.

### Status transitions

Linear statuses are updated via the `issueUpdate` mutation:

```graphql
mutation IssueUpdate($id: String!, $stateId: String!) {
  issueUpdate(id: $id, input: { stateId: $stateId }) {
    success
  }
}
```

State IDs vary per team. The adapter resolves state names to IDs dynamically by querying the team's workflow states:

```graphql
query WorkflowStates($teamId: String!) {
  team(id: $teamId) {
    states {
      nodes {
        id
        name
        type
      }
    }
  }
}
```

### Pipeline-to-Linear status mapping

| Pipeline | Event | Linear Status | Comment |
|----------|-------|---------------|---------|
| Feature | Plan complete | In Progress | "SPEED: Plan complete. {n} tasks, scope: {summary}" |
| Feature | Integrated | Done | "SPEED: Feature integrated and merged." |
| Feature | Guardian rejected | Backlog | "SPEED: Product Guardian flagged concerns: {concerns}" |
| Defect | Triage complete | In Progress | "SPEED: Triage complete. Classification: {complexity}, root cause: {hypothesis}" |
| Defect | Integrated | Done | "SPEED: Defect resolved and merged." |
| Defect | Escalated | Backlog | "SPEED: Escalated to feature pipeline. Draft PRD: {path}" |
| Defect | Rejected | *(no status change)* | "SPEED: Not a defect. Reason: {explanation}" |

For rejected defects, the adapter posts a comment but does NOT change the status -- the human decides what to do next. This mirrors the GitHub adapter behavior.

### Comment posting

```graphql
mutation CommentCreate($issueId: String!, $body: String!) {
  commentCreate(input: { issueId: $issueId, body: $body }) {
    success
  }
}
```

### Sync implementation

```bash
adapter_sync() {
  local ticket_id="$1"
  local event="$2"
  local details="$3"

  # Check sync is enabled
  local sync_enabled
  sync_enabled=$(_config_get "integrations.linear.sync" "false")
  [[ "$sync_enabled" == "true" ]] || return 0

  _require_linear_config

  # Resolve the Linear issue internal ID from identifier
  local issue_id
  issue_id=$(_resolve_linear_id "$ticket_id")

  # Map event to status transition + comment
  local target_status comment_body
  case "$event" in
    plan_complete)
      target_status="In Progress"
      comment_body="SPEED: Plan complete. $details"
      ;;
    integrated)
      target_status="Done"
      comment_body="SPEED: Integrated and merged. $details"
      ;;
    guardian_rejected)
      target_status="Backlog"
      comment_body="SPEED: Product Guardian flagged concerns. $details"
      ;;
    triage_complete)
      target_status="In Progress"
      comment_body="SPEED: Triage complete. $details"
      ;;
    escalated)
      target_status="Backlog"
      comment_body="SPEED: Escalated to feature pipeline. $details"
      ;;
    rejected)
      target_status=""  # No status change for rejections
      comment_body="SPEED: Not a defect. $details"
      ;;
    *)
      _warn "Unknown sync event: $event"
      return 0
      ;;
  esac

  # Post comment (always)
  if ! _linear_post_comment "$issue_id" "$comment_body"; then
    _warn "Failed to post comment to Linear ticket $ticket_id. Pipeline continues."
  fi

  # Update status (if applicable)
  if [[ -n "$target_status" ]]; then
    local state_id
    state_id=$(_resolve_state_id "$target_status")
    if [[ -n "$state_id" ]]; then
      if ! _linear_update_status "$issue_id" "$state_id"; then
        _warn "Failed to update Linear ticket $ticket_id status. Pipeline continues."
      fi
    else
      _warn "Could not resolve Linear state '$target_status' for team. Check team workflow configuration."
    fi
  fi
}
```

### Non-blocking sync

Sync failures are warnings, not errors. The SPEED pipeline continues regardless. The adapter logs:
- What it tried to do
- What failed (HTTP status, error message)
- That the pipeline is continuing

This matches the parent RFC principle: "sync is opt-in and non-blocking."

## Configuration

### `speed.toml` section

```toml
[integrations.linear]
api_key_env = "LINEAR_API_KEY"    # Name of env var holding the API key
sync = true                       # Enable bidirectional sync
team_id = "TEAM_ID"              # Linear team ID (for resolving workflow states)
```

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `api_key_env` | Yes (for fetch) | `"LINEAR_API_KEY"` | Name of the env var containing the Linear API key |
| `sync` | No | `false` | Whether to push status updates back to Linear |
| `team_id` | Yes (for sync) | None | Linear team ID, used to resolve workflow state IDs for status transitions |

### Config validation

```bash
_require_linear_config() {
  local api_key_env
  api_key_env=$(_config_get "integrations.linear.api_key_env" "")
  [[ -n "$api_key_env" ]] || _fatal "Linear integration not configured. Add [integrations.linear] with api_key_env to speed.toml."

  local api_key="${!api_key_env}"
  [[ -n "$api_key" ]] || _fatal "Linear API key not set. Export $api_key_env in your environment."
}
```

For sync operations, additionally validate `team_id`:

```bash
_require_linear_sync_config() {
  _require_linear_config
  local team_id
  team_id=$(_config_get "integrations.linear.team_id" "")
  [[ -n "$team_id" ]] || _fatal "Linear team_id not configured. Add team_id to [integrations.linear] in speed.toml."
}
```

## Source Reference Parsing

The pipeline needs to detect which adapter to dispatch sync events to. Source references are embedded as HTML comments in the spec:

```markdown
<!-- source: linear#LIN-423 -->
```

Parsing:

```bash
_parse_source_ref() {
  local spec_file="$1"
  local ref
  ref=$(grep -o '<!-- source: [a-z]*#[A-Za-z0-9-]* -->' "$spec_file" | head -1)
  if [[ -n "$ref" ]]; then
    local adapter ticket_id
    adapter=$(echo "$ref" | sed 's/<!-- source: \([a-z]*\)#.*/\1/')
    ticket_id=$(echo "$ref" | sed 's/<!-- source: [a-z]*#\([A-Za-z0-9-]*\) -->/\1/')
    echo "$adapter $ticket_id"
  fi
}
```

This function is shared across all adapters (defined in `speed/speed` or a shared lib, not in the adapter itself). Phase 4 introduces it; Phase 5 reuses it.

## Dependencies

### External

- `curl` -- HTTP requests to Linear GraphQL API
- `jq` -- JSON parsing of API responses
- Linear API key with read/write permissions on the target team

### Internal

- Phase 1 (Spec Templates) -- templates must exist for scaffolding
- Phase 4 (GitHub Adapter) -- establishes `adapter_fetch()` / `adapter_sync()` interface, `_parse_source_ref()`, `cmd_intake()` dispatch logic, and sync hook points in the pipeline
- `speed.toml` config infrastructure (`_config_get`)

## Files Changed

| File | Change |
|------|--------|
| `speed/integrations/linear.sh` | New file -- Linear adapter implementing `adapter_fetch()` and `adapter_sync()` |
| `speed/speed` | Add `linear` case to `cmd_intake()` adapter dispatch |
| `speed.toml` | Add `[integrations.linear]` example configuration (documented, not auto-created) |

## What Phase 5 Validates About the Plugin Model

The Linear adapter is the second adapter. Its purpose beyond Linear support is to prove the plugin architecture generalizes:

1. **Interface sufficiency**: Do `adapter_fetch()` and `adapter_sync()` cover Linear's needs without extending the interface?
2. **Config pattern**: Does the `[integrations.<name>]` config pattern work for non-GitHub services?
3. **Source reference format**: Does `<!-- source: <adapter>#<id> -->` parse cleanly for Linear's ticket ID format (e.g., `LIN-423`)?
4. **Sync dispatch**: Does the pipeline's sync hook correctly route to the Linear adapter based on the source reference?
5. **Error isolation**: Does a Linear API failure stay contained without affecting the pipeline?

If any of these require changes to the shared interface, those changes are made in Phase 5 and retrofitted to the GitHub adapter. Better to discover interface gaps on the second adapter than the third.
