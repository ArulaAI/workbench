# RFC: GitHub Adapter

> See [product spec](../product/speed-github.md) for product context.
> Depends on: [Phase 1: Spec Templates](speed-templates.md), [Phase 2: Audit Agent](speed-audit.md), [Phase 3: Defect Pipeline](speed-defects.md)
> Parent RFC: [Unified Intake & Defect Pipeline](../unified-intake.md)

## GitHub Adapter

### Adapter file

**File:** `speed/integrations/github.sh`
**Dependencies:** `gh` CLI (GitHub's official CLI, authenticated via `gh auth login`)

The adapter implements the two standard adapter functions defined in the parent RFC:

```bash
adapter_fetch()     # Fetch issue data, classify, scaffold spec
adapter_sync()      # Comment on issue, update labels, close on resolve
```

The adapter is sourced by the main `speed/speed` script when the `intake github` subcommand is invoked.

## CLI Commands

### `speed intake github`

```bash
# Basic intake — classify from labels
./speed/speed intake github #42
./speed/speed intake github 42        # '#' is optional

# Override classification
./speed/speed intake github #42 --as defect
./speed/speed intake github #42 --as feature
```

### Command parsing

The `cmd_intake()` function in `speed/speed` dispatches to the appropriate adapter:

```bash
cmd_intake() {
    local adapter="$1"; shift
    local identifier="$1"; shift

    # Strip leading '#' from issue number
    identifier="${identifier#\#}"

    # Source the adapter
    local adapter_file="speed/integrations/${adapter}.sh"
    if [[ ! -f "$adapter_file" ]]; then
        _die "Unknown adapter: $adapter. Available: github"
    fi
    source "$adapter_file"

    # Parse --as flag
    local force_type=""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --as) force_type="$2"; shift 2 ;;
            *) _die "Unknown flag: $1" ;;
        esac
    done

    adapter_fetch "$identifier" "$force_type"
}
```

## Fetch Implementation

### Prerequisite check

Before any GitHub operation, verify the `gh` CLI:

```bash
_check_gh() {
    if ! command -v gh &>/dev/null; then
        _die "gh CLI is required for GitHub integration. Install: https://cli.github.com/"
    fi
    if ! command -v jq &>/dev/null; then
        _die "jq is required for JSON parsing. Install with: brew install jq"
    fi
    if ! gh auth status &>/dev/null 2>&1; then
        _die "gh CLI is not authenticated. Run: gh auth login"
    fi
}
```

Exit with `EXIT_CONFIG_ERROR` on failure.

### `adapter_fetch()`

```bash
adapter_fetch() {
    local issue_number="$1"
    local force_type="$2"

    _check_gh

    # 1. Fetch issue data
    local issue_json
    issue_json=$(gh issue view "$issue_number" --json title,body,labels,assignees,comments 2>&1) || {
        _die "Issue #${issue_number} not found in this repository."
    }

    # 2. Extract fields
    local title body labels
    title=$(echo "$issue_json" | jq -r '.title')
    body=$(echo "$issue_json" | jq -r '.body // ""')
    labels=$(echo "$issue_json" | jq -r '[.labels[].name] | join(",")')

    # 3. Classify
    local spec_type
    spec_type=$(_classify_issue "$labels" "$force_type")

    # 4. Scaffold
    _scaffold_from_issue "$issue_number" "$title" "$body" "$spec_type"
}
```

### Classification logic

```bash
_classify_issue() {
    local labels="$1"
    local force_type="$2"

    # --as override takes precedence
    if [[ -n "$force_type" ]]; then
        case "$force_type" in
            defect|bug) echo "defect" ;;
            feature|enhancement) echo "feature" ;;
            *) _die "Unknown type: $force_type. Use 'defect' or 'feature'." ;;
        esac
        return
    fi

    # Label-based classification
    local defect_labels="bug,defect,fix"
    local feature_labels="feature,enhancement"

    local has_defect=false has_feature=false
    IFS=',' read -ra label_arr <<< "$labels"
    for label in "${label_arr[@]}"; do
        label=$(echo "$label" | xargs)  # trim whitespace
        if [[ ",$defect_labels," == *",$label,"* ]]; then
            has_defect=true
        fi
        if [[ ",$feature_labels," == *",$label,"* ]]; then
            has_feature=true
        fi
    done

    # Resolve conflicts
    if $has_defect && $has_feature; then
        _warn "Issue has both defect and feature labels. Defaulting to defect. Use --as feature to override."
        echo "defect"
    elif $has_defect; then
        echo "defect"
    elif $has_feature; then
        echo "feature"
    else
        # No matching labels — default to feature with warning
        _warn "No defect or feature labels found. Defaulting to feature. Use --as defect to override."
        echo "feature"
    fi
}
```

### Scaffolding

```bash
_scaffold_from_issue() {
    local issue_number="$1"
    local title="$2"
    local body="$3"
    local spec_type="$4"

    local template output_dir output_file slug

    # Derive slug from title (lowercase, spaces → hyphens, strip non-alphanum)
    slug=$(echo "$title" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9 ]//g' | tr ' ' '-' | sed 's/--*/-/g' | sed 's/^-//;s/-$//')

    case "$spec_type" in
        defect)
            template="speed/templates/defect.md"
            output_dir="specs/defects"
            ;;
        feature)
            template="speed/templates/prd.md"
            output_dir="specs/product"
            ;;
    esac

    output_file="${output_dir}/${slug}.md"

    # Check for existing file
    if [[ -f "$output_file" ]]; then
        _die "File already exists: $output_file. Remove it or use a different name."
    fi

    # Create output directory
    mkdir -p "$output_dir"

    # Copy template
    cp "$template" "$output_file"

    # Pre-fill fields based on spec type
    _prefill_spec "$output_file" "$issue_number" "$title" "$body" "$spec_type"

    # Append source tracking comment
    echo "" >> "$output_file"
    echo "<!-- source: github#${issue_number} -->" >> "$output_file"

    _info "Scaffolded $spec_type spec from GitHub issue #${issue_number}: $output_file"

    # Open in editor
    if [[ -n "${EDITOR:-}" ]]; then
        "$EDITOR" "$output_file"
    else
        _info "No \$EDITOR set. Edit manually: $output_file"
    fi
}
```

### Pre-fill mapping

The pre-fill step performs mechanical text substitution into the scaffolded template. No intelligent drafting — just placing the issue's title and body into the right sections.

**Feature (PRD template):**

| Issue field | Spec section | Method |
|-------------|-------------|--------|
| Title | `# {Feature Name}` heading | Replace placeholder in heading |
| Body | `## Problem` section | Insert body text below the Problem heading |
| Issue number | Source comment | Append `<!-- source: github#N -->` |

**Defect (defect template):**

| Issue field | Spec section | Method |
|-------------|-------------|--------|
| Title | `# Defect: {Short Description}` heading | Replace placeholder in heading |
| Body | `## Observed Behavior` section | Insert body text below the Observed Behavior heading |
| Issue number | Source comment | Append `<!-- source: github#N -->` |

```bash
_prefill_spec() {
    local file="$1"
    local issue_number="$2"
    local title="$3"
    local body="$4"
    local spec_type="$5"

    case "$spec_type" in
        feature)
            # Replace title placeholder
            sed -i '' "s/{Feature Name}/${title}/g" "$file" 2>/dev/null || \
                sed -i "s/{Feature Name}/${title}/g" "$file"

            # Insert body below ## Problem
            _insert_below_heading "$file" "## Problem" "$body"
            ;;
        defect)
            # Replace title placeholder
            sed -i '' "s/{Short Description}/${title}/g" "$file" 2>/dev/null || \
                sed -i "s/{Short Description}/${title}/g" "$file"

            # Insert body below ## Observed Behavior
            _insert_below_heading "$file" "## Observed Behavior" "$body"
            ;;
    esac
}
```

The `_insert_below_heading()` helper finds the target heading line and inserts the body text on the following line, preserving the rest of the template. Uses `awk` for multi-line insertion.

## Sync Implementation

### When sync runs

Sync is triggered from within existing pipeline commands (`cmd_plan`, `cmd_defect`, `cmd_integrate`, `cmd_review`) at stage transition points. Each command checks whether the current spec has a GitHub source reference and whether sync is enabled.

### Source reference detection

```bash
_get_github_source() {
    local spec_file="$1"
    local source_comment
    source_comment=$(grep -o '<!-- source: github#[0-9]* -->' "$spec_file" 2>/dev/null || true)
    if [[ -n "$source_comment" ]]; then
        echo "$source_comment" | grep -o '[0-9]*'
    fi
}
```

Returns the issue number if found, empty string otherwise.

### Sync configuration

Read from `speed.toml`:

```toml
[integrations.github]
sync = true              # Enable/disable sync comments (default: false)
close_on_resolve = true  # Close issue when work is integrated (default: true)
```

```bash
_github_sync_enabled() {
    local sync
    sync=$(_config_get "integrations.github.sync" "false")
    [[ "$sync" == "true" ]]
}

_github_close_on_resolve() {
    local close
    close=$(_config_get "integrations.github.close_on_resolve" "true")
    [[ "$close" == "true" ]]
}
```

### `adapter_sync()`

```bash
adapter_sync() {
    local issue_number="$1"
    local event="$2"
    local detail="$3"

    _check_gh

    if ! _github_sync_enabled; then
        return 0
    fi

    case "$event" in
        plan_complete)
            gh issue comment "$issue_number" --body "**SPEED:** Plan complete. ${detail}"
            ;;
        integrated)
            gh issue comment "$issue_number" --body "**SPEED:** Integrated. ${detail}"
            if _github_close_on_resolve; then
                gh issue close "$issue_number" --comment "Resolved via SPEED pipeline."
            fi
            ;;
        guardian_rejected)
            gh issue comment "$issue_number" --body "**SPEED:** Guardian concern — ${detail}"
            gh issue edit "$issue_number" --add-label "needs-revision"
            ;;
        triage_complete)
            gh issue comment "$issue_number" --body "**SPEED:** Triage complete. ${detail}"
            ;;
        escalated)
            gh issue comment "$issue_number" --body "**SPEED:** Escalated to feature spec. ${detail}"
            gh issue edit "$issue_number" --add-label "needs-spec"
            ;;
        rejected)
            # Do NOT close the issue — human decides
            gh issue comment "$issue_number" --body "**SPEED:** Not a defect. ${detail}"
            ;;
    esac
}
```

### Sync event table

Matches the parent RFC's sync specification:

| Pipeline | Event | `adapter_sync` event | GitHub Action |
|----------|-------|---------------------|---------------|
| Feature | Plan complete | `plan_complete` | Comment: task count, scope summary |
| Feature | Integrated | `integrated` | Comment: summary; close issue (if `close_on_resolve`) |
| Feature | Guardian rejected | `guardian_rejected` | Comment: concern; add label `needs-revision` |
| Defect | Triage complete | `triage_complete` | Comment: classification, root cause hypothesis |
| Defect | Integrated | `integrated` | Comment: summary; close issue (if `close_on_resolve`) |
| Defect | Escalated | `escalated` | Comment: explanation; add label `needs-spec` |
| Defect | Rejected | `rejected` | Comment: explanation (do NOT close) |

### Integration points in existing commands

Each pipeline command adds a sync hook after its stage transition:

| Command | Hook location | Event |
|---------|--------------|-------|
| `cmd_plan()` | After Architect produces task graph | `plan_complete` with task count |
| `cmd_defect()` | After triage completes | `triage_complete` with classification + root cause |
| `cmd_defect()` | After escalation decision | `escalated` with explanation |
| `cmd_defect()` | After rejection decision | `rejected` with explanation |
| `cmd_integrate()` | After successful merge | `integrated` with summary |
| `cmd_review()` | After Guardian rejection | `guardian_rejected` with concern |

Each hook follows this pattern:

```bash
# In cmd_plan(), after task graph is produced:
local issue_number
issue_number=$(_get_github_source "$spec_file")
if [[ -n "$issue_number" ]]; then
    source speed/integrations/github.sh
    adapter_sync "$issue_number" "plan_complete" "${task_count} tasks planned."
fi
```

The adapter is sourced lazily — only when a GitHub source reference exists and sync is needed. No performance impact on specs that didn't originate from GitHub.

## Source Tracking

### In the spec file

The `<!-- source: github#N -->` HTML comment is appended at the end of the scaffolded spec. It's invisible in rendered markdown, survives editing, and is parseable by grep.

### In SPEED state

When a spec originates from GitHub intake, the source is also recorded in the task or defect state JSON:

**Feature (task state):**
```json
{
  "spec": "specs/product/invite-friends.md",
  "source": {
    "type": "github",
    "issue": 42,
    "url": "https://github.com/owner/repo/issues/42"
  }
}
```

**Defect (defect state):**
```json
{
  "source_spec": "specs/defects/invite-failure.md",
  "source": {
    "type": "github",
    "issue": 17,
    "url": "https://github.com/owner/repo/issues/17"
  }
}
```

The URL is derived from `gh repo view --json url` at intake time and stored for reference.

## Configuration

### `speed.toml` section

```toml
[integrations.github]
sync = true              # Comment on issues at stage transitions (default: false)
close_on_resolve = true  # Close the source issue when work is integrated (default: true)
```

No API keys needed — `gh` CLI handles authentication via `gh auth login`. This is a deliberate simplification: no token management, no env vars to configure, no secrets in config files.

### Config reading

Uses the existing `_config_get()` utility from `speed/speed`:

```bash
# Read github config values with defaults
_config_get "integrations.github.sync" "false"
_config_get "integrations.github.close_on_resolve" "true"
```

### Default behavior (no config)

If `[integrations.github]` is not present in `speed.toml`:
- `intake github` works (fetch doesn't require config — only `gh` CLI)
- Sync is disabled (no comments, no closes)
- All sync calls are no-ops

This means `intake github` works out of the box with zero configuration. Sync is the opt-in part.

## Error Handling

| Condition | Behavior | Exit code |
|-----------|----------|-----------|
| `gh` CLI not installed | Print install link, exit | `EXIT_CONFIG_ERROR` |
| `jq` not installed | Print error: "jq is required for JSON parsing. Install with: brew install jq", exit | `EXIT_CONFIG_ERROR` |
| `gh` not authenticated | Print `gh auth login` hint, exit | `EXIT_CONFIG_ERROR` |
| Issue not found | Print "Issue #N not found in this repository", exit | `EXIT_RUNTIME_ERROR` |
| Invalid `--as` value | Print accepted values, exit | `EXIT_CONFIG_ERROR` |
| Template file missing | Print "Template not found: path", exit | `EXIT_CONFIG_ERROR` |
| Output file already exists | Print path, suggest removing or renaming, exit | `EXIT_CONFIG_ERROR` |
| Sync comment fails (network, permissions) | Print warning, continue (sync failure is not fatal) | No exit — warn only |
| `gh issue close` fails | Print warning, continue | No exit — warn only |
| `gh issue edit --add-label` fails (label doesn't exist) | Print warning, continue | No exit — warn only |
| Fetch and scaffold succeeds | Exit normally | `EXIT_OK` (0) |

Sync failures are non-fatal. The pipeline continues even if GitHub is unreachable. The adapter logs the warning and moves on.

## Files Changed

| File | Change |
|------|--------|
| `speed/integrations/github.sh` | New file — `adapter_fetch()`, `adapter_sync()`, classification, scaffolding, pre-fill, source tracking |
| `speed/speed` | Add `cmd_intake()` dispatcher; add sync hooks in `cmd_plan()`, `cmd_defect()`, `cmd_integrate()`, `cmd_review()` |
| `speed.toml` | Add `[integrations.github]` section (optional — adapter works without it) |

## Dependencies

- Phase 1 (Spec Templates) — `speed/templates/prd.md` and `speed/templates/defect.md` must exist for scaffolding
- Phase 2 (Audit Agent) — scaffolded specs can be audited before pipeline entry (existing flow, no changes needed)
- Phase 3 (Defect Pipeline) — defect-classified issues route into the defect pipeline
- `gh` CLI — GitHub's official CLI, handles auth and API calls
- `jq` — for JSON parsing of `gh issue view` output (already a common dependency)
- Existing `_config_get()` utility in `speed/speed` for reading `speed.toml`
- Existing `_die`, `_warn`, `_info` output utilities in `speed/speed`
