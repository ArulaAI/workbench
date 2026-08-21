# RFC: Security Auditor & Security Gates

> See [product spec](../product/speed-security.md) for product context.
> Depends on: [Phase 3: Defect Pipeline](speed-defects.md), [Phase 2: Audit Agent](speed-audit.md)

## Basic Example

A CLI session showing the security pipeline end-to-end:

```toml
# speed.toml — security configuration
[security]
sast_cmd = "semgrep --config auto --json"
sca_cmd = "npm audit --json"
severity_threshold = "medium"    # only "medium", "high", "critical" create defects
secrets_patterns = ["AWS", "GITHUB_TOKEN", "GENERIC_SECRET"]
```

```bash
# 1. Normal pipeline run — SAST runs as a quality gate
./speed run
# ✓ Lint passed
# ✓ Typecheck passed
# ✓ Tests passed (14/14)
# ⚠ SAST: 2 findings (1 medium, 1 low)
#   [medium] possible SQL injection — src/api/users.py:42
#   [low] hardcoded timeout value — src/api/retry.py:18
# ⚠ SCA: 1 finding (1 high)
#   [high] CVE-2024-29041 — express <4.19.2 (path traversal)
# ✓ Quality gates passed (with warnings)

# 2. Dedicated security audit — agent reads full files
./speed security
# ┌─────────────────────────────────────────┐
# │  SECURITY AUDIT — feature: f5-payments  │
# ├─────────────────────────────────────────┤
# │  Findings: 3 total                      │
# │    critical: 0  high: 1  medium: 1      │
# │    low: 1       info: 0                 │
# │                                         │
# │  [high] Missing authentication check    │
# │    src/api/payments.py:67               │
# │    transfer_funds() callable without    │
# │    verified session token               │
# │                                         │
# │  [medium] Unparameterized SQL query     │
# │    src/api/users.py:42                  │
# │    String concatenation in WHERE clause │
# │                                         │
# │  [low] Verbose error message            │
# │    src/api/errors.py:15                 │
# │    Stack trace exposed in 500 response  │
# └─────────────────────────────────────────┘
# ⚠ Security findings are warnings — integration is not blocked.

# 3. Create defects from findings above threshold
./speed security --create-defects
# Created specs/defects/sec-missing-auth-payments.md (high)
# Created specs/defects/sec-sql-injection-users.md (medium)
# Skipped 1 finding below threshold (low)

# 4. Status shows security summary
./speed status
# Feature: f5-payments    planning → developing [████░░░░] 4/8 tasks
# Security: ⚠ 2 findings (1 high, 1 medium)
# Defects: sec-missing-auth-payments (filed), sec-sql-injection-users (filed)
```

## Data Model

### Directory structure

Security findings are stored alongside feature logs:

```
.speed/features/<name>/
  logs/
    security-audit.json    # Security Auditor agent output
    sast-output.json       # Raw SAST tool output (latest run)
    sca-output.json        # Raw SCA tool output (latest run)
    secrets-scan.log       # Grounding-level secrets scan log
```

### `security-audit.json` schema

Produced by the Security Auditor agent. Consumed by `speed status`, `speed security --create-defects`, and the integration summary.

```json
{
  "feature": "string",
  "timestamp": "ISO 8601",
  "agent_model": "string",
  "findings": [
    {
      "id": "string",
      "severity": "critical | high | medium | low | info",
      "category": "injection | auth | secrets | crypto | config | xss | path-traversal | info-disclosure",
      "title": "string",
      "description": "string",
      "file": "string",
      "line": 0,
      "snippet": "string",
      "recommendation": "string"
    }
  ],
  "summary": {
    "total": 0,
    "by_severity": {
      "critical": 0,
      "high": 0,
      "medium": 0,
      "low": 0,
      "info": 0
    }
  }
}
```

### `speed.toml [security]` schema

```toml
[security]
sast_cmd = "semgrep --config auto --json"   # Shell command — static analysis of your code
sca_cmd = "npm audit --json"                # Shell command — dependency vulnerability check
severity_threshold = "medium"                # Minimum severity for --create-defects
secrets_patterns = ["AWS", "GITHUB_TOKEN", "GENERIC_SECRET"]  # Built-in pattern names to enable
secrets_exclude = [".env*", "*.example", "tests/fixtures/**"]  # Globs excluded from secrets scanning
```

`sast_cmd` and `sca_cmd` serve different purposes. SAST analyzes your source code for vulnerability patterns (injection, auth bypasses). SCA checks your dependency tree for known CVEs. Both are optional, configured independently, and follow the same warn-not-block behavior.

Most package ecosystems ship a built-in audit command:

| Ecosystem | Command | Built-in? |
|---|---|---|
| Node.js | `npm audit --json` | Yes (npm 6+) |
| Python | `pip-audit --format=json` | `pip install pip-audit` |
| Rust | `cargo audit --json` | `cargo install cargo-audit` |
| Go | `govulncheck -json ./...` | `go install golang.org/x/vuln/cmd/govulncheck` |
| Ruby | `bundle-audit check --format=json` | `gem install bundler-audit` |
| PHP | `composer audit --format=json` | Yes (Composer 2.4+) |
| .NET | `dotnet list package --vulnerable --format=json` | Yes |

`sast_cmd` is a single shell command string. Teams that run multiple SAST tools should wrap them in a script that merges output into a single JSON stream:

```bash
# scripts/security-scan.sh
#!/usr/bin/env bash
semgrep --config auto --json --output /tmp/semgrep.json "$@"
bandit -r -f json --output /tmp/bandit.json "$@"
# merge into unified format expected by security_sast_parse()
python3 scripts/merge-sast.py /tmp/semgrep.json /tmp/bandit.json
```

```toml
[security]
sast_cmd = "./scripts/security-scan.sh"
```

### Shell variable mapping

`lib/toml.py` emits these variables when `[security]` is present:

| TOML key | Shell variable | Default |
|----------|---------------|---------|
| `security.sast_cmd` | `TOML_SECURITY_SAST_CMD` | (empty, SAST disabled) |
| `security.sca_cmd` | `TOML_SECURITY_SCA_CMD` | (empty, SCA disabled) |
| `security.severity_threshold` | `TOML_SECURITY_SEVERITY_THRESHOLD` | `"medium"` |
| `security.secrets_patterns` | `TOML_SECURITY_SECRETS_PATTERNS` | `"AWS GITHUB_TOKEN GENERIC_SECRET"` |
| `security.secrets_exclude` | `TOML_SECURITY_SECRETS_EXCLUDE` | `".env* *.example tests/fixtures/**"` |

## State Machine

The security stage is stateless. It reads source files, runs analysis, and produces a findings report. No state transitions, no persistent state machine. The findings JSON is a snapshot written on each invocation of `speed security` or each quality gate run.

Secrets scanning at the grounding level is similarly stateless: it scans, passes or fails, and writes a log. No recovery, no retry logic at the security layer itself.

## API Surface

### CLI commands

```bash
# Run Security Auditor agent on current feature
./speed security [--feature <name>]

# Run Security Auditor and create defect specs from findings
./speed security --create-defects [--feature <name>]
```

**`speed security`**
- Input: Feature name (auto-detected from `.speed/current` or `--feature` flag)
- Behavior: Runs Security Auditor agent against all files in the feature scope. Writes `security-audit.json`. Prints findings summary banner.
- Output on success: Findings banner with severity breakdown and per-finding details (file, line, category, title)
- Output on no findings: "No security findings."
- Error: Feature not found → "No active feature. Run speed plan first or specify --feature."

**`speed security --create-defects`**
- Input: Same as `speed security`, plus `severity_threshold` from `speed.toml`
- Behavior: Runs the audit (or reads cached `security-audit.json` if recent), then generates defect specs for findings at or above the threshold
- Output: Lists created defect spec paths, notes skipped findings below threshold
- Error: Defect pipeline not available → "Defect pipeline required for --create-defects. See specs/product/speed-defects.md."

### New file: `lib/security.sh`

```bash
#!/usr/bin/env bash
# security.sh — Security scanning and audit orchestration
#
# Functions:
#   security_audit_run          — Run Security Auditor agent on feature files
#   security_sast_run           — Run configured SAST tool
#   security_sast_parse         — Normalize SAST output to findings format
#   security_sca_run            — Run configured SCA tool
#   security_sca_parse          — Normalize SCA output to findings format
#   security_print_banner       — Print findings summary banner
#   security_create_defects     — Generate defect specs from findings
#   security_has_cached_audit   — Check for recent audit results
#
# Requires config.sh, log.sh, provider.sh, features.sh to be sourced first.

# ── Severity ordering (for threshold comparisons) ──────────────────
declare -A _SEVERITY_RANK=(
    [critical]=5 [high]=4 [medium]=3 [low]=2 [info]=1
)

# ── Severity → defect priority mapping ─────────────────────────────
declare -A _SEVERITY_TO_PRIORITY=(
    [critical]=P0 [high]=P1 [medium]=P2 [low]=P3 [info]=P3
)

# Returns 0 if $1 >= $2 in severity ranking
_severity_at_or_above() {
    local severity="$1" threshold="$2"
    [[ ${_SEVERITY_RANK[$severity]:-0} -ge ${_SEVERITY_RANK[$threshold]:-0} ]]
}

# ── security_audit_run ─────────────────────────────────────────────
# Run the Security Auditor agent against all files in a feature's scope.
# Args: feature_name
# Writes: .speed/features/<name>/logs/security-audit.json
# Returns: 0 always (findings are warnings, not failures)

security_audit_run() {
    local feature_name="$1"
    local feature_dir="${STATE_DIR}/features/${feature_name}"
    local logs_dir="${feature_dir}/logs"
    local output_file="${logs_dir}/security-audit.json"

    mkdir -p "$logs_dir"

    log_step "Running Security Auditor agent on feature '${feature_name}'..."

    # Build agent prompt via context bridge
    local prompt
    prompt=$(context_assemble_security_auditor "$feature_name")

    if [[ -z "$prompt" ]]; then
        log_error "Failed to assemble Security Auditor prompt"
        return 0  # Non-blocking
    fi

    # Write prompt to temp file for provider_run_json
    local prompt_file
    prompt_file=$(mktemp "${TMPDIR:-/tmp}/speed-security-prompt.XXXXXX")
    echo "$prompt" > "$prompt_file"

    # Run agent with structured JSON output
    local agent_output
    agent_output=$(provider_run_json \
        "${SCRIPT_DIR}/agents/security-auditor.md" \
        "$(cat "$prompt_file")" \
        "${SCRIPT_DIR}/templates/architect-output.json" \
        "$MODEL_SUPPORT" \
        "$DEFAULT_JSON_MAX_TURNS" \
        "" \
        "Security Auditor" \
    ) || true

    rm -f "$prompt_file"

    # Parse agent output
    local parsed
    parsed=$(parse_agent_json "$agent_output") || {
        log_warn "Security Auditor returned unparseable output — skipping"
        return 0
    }

    # Write findings to logs
    echo "$parsed" | jq '.' > "$output_file"
    log_success "Security audit complete: ${output_file}"

    return 0
}

# ── security_sast_run ──────────────────────────────────────────────
# Run configured SAST tool against changed files on the feature branch.
# Args: feature_name worktree_path
# Writes: .speed/features/<name>/logs/sast-output.json
# Returns: 0 always (findings are warnings)

security_sast_run() {
    local feature_name="$1"
    local worktree_path="${2:-$PROJECT_ROOT}"
    local logs_dir="${STATE_DIR}/features/${feature_name}/logs"
    local raw_output="${logs_dir}/sast-output.json"

    mkdir -p "$logs_dir"

    local sast_cmd="${TOML_SECURITY_SAST_CMD:-}"
    if [[ -z "$sast_cmd" ]]; then
        log_info "No SAST toolchain configured. Add [security] to speed.toml to enable."
        return 0
    fi

    log_step "Running SAST: ${COLOR_DIM}${sast_cmd}${RESET}"

    # Run SAST tool in the worktree directory, capture output
    local sast_exit=0
    (cd "$worktree_path" && eval "$sast_cmd" > "$raw_output" 2>&1) || sast_exit=$?

    # SAST tools return non-zero when they find issues — that's expected
    if [[ ! -s "$raw_output" ]]; then
        log_warn "SAST tool produced no output (exit code: ${sast_exit})"
        echo '{"findings": []}' > "$raw_output"
    fi

    return 0
}

# ── security_sast_parse ────────────────────────────────────────────
# Parse SAST JSON output into normalized findings format.
# Currently supports Semgrep JSON. Extend for additional tools.
# Args: raw_json_path output_path
# Reads tool-specific JSON, writes normalized findings array.

security_sast_parse() {
    local raw_json_path="$1"
    local output_path="$2"

    if [[ ! -f "$raw_json_path" ]]; then
        echo '[]' > "$output_path"
        return 0
    fi

    # Detect format and normalize
    $(_context_python) -c "
import json, sys, os

raw_path = '$raw_json_path'
out_path = '$output_path'

with open(raw_path) as f:
    try:
        raw = json.load(f)
    except json.JSONDecodeError:
        json.dump([], open(out_path, 'w'))
        sys.exit(0)

findings = []
counter = 1

# Semgrep format: {'results': [{...}]}
if 'results' in raw:
    for r in raw['results']:
        sev_map = {'ERROR': 'high', 'WARNING': 'medium', 'INFO': 'low'}
        findings.append({
            'id': f'SAST-{counter:03d}',
            'severity': sev_map.get(r.get('extra', {}).get('severity', ''), 'medium'),
            'category': _map_semgrep_category(r),
            'title': r.get('check_id', 'unknown').split('.')[-1].replace('-', ' '),
            'description': r.get('extra', {}).get('message', ''),
            'file': r.get('path', ''),
            'line': r.get('start', {}).get('line', 0),
            'snippet': r.get('extra', {}).get('lines', '').strip()[:200],
            'recommendation': r.get('extra', {}).get('fix', 'Review and remediate.'),
        })
        counter += 1

# Bandit format: {'results': [{...}]} with different fields
elif isinstance(raw, dict) and 'results' in raw and raw.get('generated_at'):
    for r in raw['results']:
        sev_map = {'HIGH': 'high', 'MEDIUM': 'medium', 'LOW': 'low'}
        findings.append({
            'id': f'SAST-{counter:03d}',
            'severity': sev_map.get(r.get('issue_severity', ''), 'medium'),
            'category': 'injection' if 'injection' in r.get('issue_text', '').lower() else 'config',
            'title': r.get('test_name', 'unknown'),
            'description': r.get('issue_text', ''),
            'file': r.get('filename', ''),
            'line': r.get('line_number', 0),
            'snippet': r.get('code', '').strip()[:200],
            'recommendation': r.get('more_info', 'Review and remediate.'),
        })
        counter += 1

json.dump(findings, open(out_path, 'w'), indent=2)


def _map_semgrep_category(result):
    \"\"\"Map Semgrep check_id patterns to OWASP-derived categories.\"\"\"
    check_id = result.get('check_id', '').lower()
    if any(k in check_id for k in ('sqli', 'injection', 'sql')):
        return 'injection'
    if any(k in check_id for k in ('auth', 'session', 'jwt', 'password')):
        return 'auth'
    if any(k in check_id for k in ('xss', 'cross-site')):
        return 'xss'
    if any(k in check_id for k in ('crypto', 'hash', 'cipher', 'tls')):
        return 'crypto'
    if any(k in check_id for k in ('path', 'traversal', 'directory')):
        return 'path-traversal'
    if any(k in check_id for k in ('secret', 'key', 'token', 'credential')):
        return 'secrets'
    if any(k in check_id for k in ('disclosure', 'info-leak', 'verbose')):
        return 'info-disclosure'
    return 'config'
" 2>/dev/null || {
        log_warn "SAST parse failed — writing empty findings"
        echo '[]' > "$output_path"
    }
}

# ── security_sca_run ───────────────────────────────────────────────
# Run configured SCA tool against project dependencies.
# Args: feature_name worktree_path
# Writes: .speed/features/<name>/logs/sca-output.json
# Returns: 0 always (findings are warnings)

security_sca_run() {
    local feature_name="$1"
    local worktree_path="${2:-$PROJECT_ROOT}"
    local logs_dir="${STATE_DIR}/features/${feature_name}/logs"
    local raw_output="${logs_dir}/sca-output.json"

    mkdir -p "$logs_dir"

    local sca_cmd="${TOML_SECURITY_SCA_CMD:-}"
    if [[ -z "$sca_cmd" ]]; then
        return 0  # SCA not configured — silent skip
    fi

    log_step "Running SCA: ${COLOR_DIM}${sca_cmd}${RESET}"

    # SCA tools check lockfiles, run from project root
    local sca_exit=0
    (cd "$worktree_path" && eval "$sca_cmd" > "$raw_output" 2>&1) || sca_exit=$?

    if [[ ! -s "$raw_output" ]]; then
        log_warn "SCA tool produced no output (exit code: ${sca_exit})"
        echo '{"findings": []}' > "$raw_output"
    fi

    return 0
}

# ── security_sca_parse ─────────────────────────────────────────────
# Parse SCA JSON output into normalized findings format.
# Supports npm audit and pip-audit JSON formats.
# Args: raw_json_path output_path

security_sca_parse() {
    local raw_json_path="$1"
    local output_path="$2"

    if [[ ! -f "$raw_json_path" ]]; then
        echo '[]' > "$output_path"
        return 0
    fi

    $(_context_python) -c "
import json, sys

raw_path = '$raw_json_path'
out_path = '$output_path'

with open(raw_path) as f:
    try:
        raw = json.load(f)
    except json.JSONDecodeError:
        json.dump([], open(out_path, 'w'))
        sys.exit(0)

findings = []
counter = 1

# npm audit format: {'vulnerabilities': {'pkg': {...}}}
if 'vulnerabilities' in raw and isinstance(raw['vulnerabilities'], dict):
    sev_map = {'critical': 'critical', 'high': 'high', 'moderate': 'medium', 'low': 'low', 'info': 'info'}
    for pkg_name, vuln in raw['vulnerabilities'].items():
        findings.append({
            'id': f'SCA-{counter:03d}',
            'severity': sev_map.get(vuln.get('severity', ''), 'medium'),
            'category': 'vulnerable-dependency',
            'title': f\"{pkg_name} {vuln.get('range', '')}\",
            'description': vuln.get('title', vuln.get('url', '')),
            'file': 'package-lock.json',
            'line': 0,
            'snippet': f\"via: {', '.join(vuln.get('via', [])[:3]) if isinstance(vuln.get('via', []), list) and all(isinstance(v, str) for v in vuln.get('via', [])) else pkg_name}\",
            'recommendation': f\"Update to {vuln.get('fixAvailable', {}).get('version', 'latest')}\" if isinstance(vuln.get('fixAvailable'), dict) else 'Run npm audit fix',
        })
        counter += 1

# pip-audit format: [{'name': ..., 'version': ..., 'vulns': [...]}]
elif isinstance(raw, list) and raw and 'vulns' in raw[0]:
    for dep in raw:
        for vuln in dep.get('vulns', []):
            findings.append({
                'id': f'SCA-{counter:03d}',
                'severity': 'high',  # pip-audit doesn't provide severity
                'category': 'vulnerable-dependency',
                'title': f\"{dep['name']}=={dep.get('version', '?')} ({vuln.get('id', 'CVE-unknown')})\",
                'description': vuln.get('description', vuln.get('id', '')),
                'file': next((f for f in ['Pipfile.lock', 'requirements.txt', 'poetry.lock'] if __import__('os').path.isfile(f)), 'requirements.txt'),
                'line': 0,
                'snippet': f\"{dep['name']}=={dep.get('version', '?')}\",
                'recommendation': f\"Update {dep['name']} to {vuln.get('fix_versions', ['latest'])[0]}\" if vuln.get('fix_versions') else f\"Update {dep['name']}\",
            })
            counter += 1

json.dump(findings, open(out_path, 'w'), indent=2)
" 2>/dev/null || {
        log_warn "SCA parse failed — writing empty findings"
        echo '[]' > "$output_path"
    }
}

# ── security_print_banner ──────────────────────────────────────────
# Print a formatted findings summary banner to stdout.
# Args: security_audit_json_path

security_print_banner() {
    local audit_json="$1"

    if [[ ! -f "$audit_json" ]]; then
        echo -e "  ${COLOR_DIM}No security audit results.${RESET}"
        return
    fi

    local total critical high medium low info
    total=$(jq -r '.summary.total // 0' "$audit_json")
    critical=$(jq -r '.summary.by_severity.critical // 0' "$audit_json")
    high=$(jq -r '.summary.by_severity.high // 0' "$audit_json")
    medium=$(jq -r '.summary.by_severity.medium // 0' "$audit_json")
    low=$(jq -r '.summary.by_severity.low // 0' "$audit_json")
    info=$(jq -r '.summary.by_severity.info // 0' "$audit_json")

    local feature
    feature=$(jq -r '.feature // "unknown"' "$audit_json")

    echo ""
    echo -e "  ${BOLD}Security Audit — feature: ${feature}${RESET}"
    echo -e "  Findings: ${total} total"

    if [[ "$total" -gt 0 ]]; then
        local severity_line=""
        [[ "$critical" -gt 0 ]] && severity_line+="${COLOR_ERROR}critical: ${critical}${RESET}  "
        [[ "$high" -gt 0 ]]     && severity_line+="${COLOR_ERROR}high: ${high}${RESET}  "
        [[ "$medium" -gt 0 ]]   && severity_line+="${COLOR_WARN}medium: ${medium}${RESET}  "
        [[ "$low" -gt 0 ]]      && severity_line+="${COLOR_DIM}low: ${low}${RESET}  "
        [[ "$info" -gt 0 ]]     && severity_line+="${COLOR_DIM}info: ${info}${RESET}"
        echo -e "    ${severity_line}"
        echo ""

        # Print each finding
        jq -r '.findings[] | "  [\(.severity)] \(.title)\n    \(.file):\(.line)\n    \(.description)\n"' "$audit_json" | \
        while IFS= read -r line; do
            echo -e "  ${line}"
        done
    fi

    echo -e "  ${COLOR_WARN}${SYM_WARN} Security findings are warnings — integration is not blocked.${RESET}"
    echo ""
}

# ── security_create_defects ────────────────────────────────────────
# Generate defect specs from security findings above severity threshold.
# Args: security_audit_json_path severity_threshold
# Writes: specs/defects/sec-<slug>.md for each qualifying finding

security_create_defects() {
    local audit_json="$1"
    local threshold="${2:-${TOML_SECURITY_SEVERITY_THRESHOLD:-medium}}"

    if [[ ! -f "$audit_json" ]]; then
        log_error "No security audit results at: ${audit_json}"
        return 1
    fi

    # Check defect pipeline is available
    local defects_dir="${PROJECT_ROOT}/specs/defects"
    if [[ ! -d "$defects_dir" ]]; then
        mkdir -p "$defects_dir"
    fi

    local feature
    feature=$(jq -r '.feature // "unknown"' "$audit_json")

    local created=0
    local skipped=0

    # Iterate findings, filter by threshold
    local findings_count
    findings_count=$(jq '.findings | length' "$audit_json")

    local i=0
    while [[ $i -lt $findings_count ]]; do
        local severity title description file line snippet recommendation category
        severity=$(jq -r ".findings[$i].severity" "$audit_json")
        title=$(jq -r ".findings[$i].title" "$audit_json")
        description=$(jq -r ".findings[$i].description" "$audit_json")
        file=$(jq -r ".findings[$i].file" "$audit_json")
        line=$(jq -r ".findings[$i].line" "$audit_json")
        snippet=$(jq -r ".findings[$i].snippet" "$audit_json")
        recommendation=$(jq -r ".findings[$i].recommendation" "$audit_json")
        category=$(jq -r ".findings[$i].category" "$audit_json")

        if _severity_at_or_above "$severity" "$threshold"; then
            local priority="${_SEVERITY_TO_PRIORITY[$severity]:-P2}"

            # Slugify title for filename
            local slug
            slug=$(echo "$title" | tr '[:upper:]' '[:lower:]' | tr ' ' '-' | tr -cd 'a-z0-9-' | head -c 40)
            local defect_file="${defects_dir}/sec-${slug}.md"

            # Write defect spec with Classification-Override for triage routing
            cat > "$defect_file" <<DEFECT_EOF
# Defect: sec-${slug}
Severity: ${priority}
Related Feature: ${feature}
Tags: security
Classification-Override: moderate
Observed: ${title} — ${description}
Expected: ${recommendation}
Repro: See ${file}:${line} — ${snippet}
DEFECT_EOF

            log_step "Created ${defect_file} (${severity})"
            ((created++))
        else
            ((skipped++))
        fi

        ((i++))
    done

    echo ""
    if [[ $created -gt 0 ]]; then
        log_success "Created ${created} defect spec(s)"
    fi
    if [[ $skipped -gt 0 ]]; then
        log_info "Skipped ${skipped} finding(s) below threshold (${threshold})"
    fi
}

# ── security_has_cached_audit ──────────────────────────────────────
# Check if security audit results exist and are recent (< 1 hour).
# Args: feature_name
# Returns: 0 if cached results exist, 1 otherwise

security_has_cached_audit() {
    local feature_name="$1"
    local audit_file="${STATE_DIR}/features/${feature_name}/logs/security-audit.json"

    [[ -f "$audit_file" ]] || return 1

    # Check age (3600 seconds = 1 hour)
    local file_age
    if [[ "$(uname)" == "Darwin" ]]; then
        file_age=$(( $(date +%s) - $(stat -f %m "$audit_file") ))
    else
        file_age=$(( $(date +%s) - $(stat -c %Y "$audit_file") ))
    fi

    [[ $file_age -lt 3600 ]]
}
```

### Additions to `lib/grounding.sh`

Add `grounding_check_secrets()` and call it from `grounding_run()` after Check 6 (test coverage):

```bash
# ── Check: secrets detection (BLOCKING) ─────────────────────────────
# Scans changed files for hardcoded secrets using regex patterns.
# Unlike all other security checks, this one is a HARD FAILURE.
# A committed secret in git history requires history rewriting to remove.
#
# Args: task_id [worktree_path]
# Returns: 0 if clean, 1 if secrets detected

grounding_check_secrets() {
    local task_id="$1"
    local worktree_path="${2:-$PROJECT_ROOT}"
    local task_json="${TASKS_DIR}/${task_id}.json"
    local branch
    branch=$(jq -r '.branch // empty' "$task_json")

    if [[ -z "$branch" ]] || [[ "$branch" == "null" ]]; then
        return 0  # No branch — nothing to scan
    fi

    # Get changed files on this branch
    local changed_files
    changed_files=$(_git diff "$(git_main_branch)...${branch}" --name-only 2>/dev/null)

    if [[ -z "$changed_files" ]]; then
        return 0
    fi

    # Build exclusion list from config (space-separated globs)
    local exclude_globs="${TOML_SECURITY_SECRETS_EXCLUDE:-.env* *.example tests/fixtures/**}"

    # Filter out excluded files
    local files_to_scan=""
    while IFS= read -r f; do
        [[ -z "$f" ]] && continue
        local excluded=false
        for glob in $exclude_globs; do
            # Use bash pattern matching (glob → case pattern)
            case "$f" in
                $glob) excluded=true; break ;;
            esac
            # Also check basename for patterns like "*.example"
            case "$(basename "$f")" in
                $glob) excluded=true; break ;;
            esac
        done
        if ! $excluded; then
            files_to_scan+="$f"$'\n'
        fi
    done <<< "$changed_files"

    if [[ -z "$files_to_scan" ]]; then
        return 0  # All files excluded
    fi

    # Scan for secret patterns
    # Each pattern: name|regex
    # IMPORTANT: never echo the matched content — only file, line, pattern name
    local patterns=(
        "AWS Access Key|AKIA[0-9A-Z]{16}"
        "AWS Secret Key|['\"][0-9a-zA-Z/+]{40}['\"]"
        "GitHub Token|gh[pousr]_[A-Za-z0-9_]{36,}"
        "Generic API Key|['\"]sk-[a-zA-Z0-9]{20,}['\"]"
        "Private Key Header|-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"
        "Generic High-Entropy Secret|['\"][A-Za-z0-9+/=]{40,}['\"]"
        "Database URL|[a-z]+://[^:]+:[^@]+@[^/]+"
    )

    local found_secrets=false
    local secrets_log="${STATE_DIR}/features/$(jq -r '.feature // "unknown"' "$task_json" 2>/dev/null)/logs/secrets-scan.log"
    mkdir -p "$(dirname "$secrets_log")" 2>/dev/null || true

    echo "# Secrets scan: $(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$secrets_log"
    echo "# Task: ${task_id}, Branch: ${branch}" >> "$secrets_log"

    while IFS= read -r f; do
        [[ -z "$f" ]] && continue
        local full_path="${worktree_path}/${f}"
        [[ -f "$full_path" ]] || continue

        # Skip binary files
        if file "$full_path" 2>/dev/null | grep -q "binary"; then
            continue
        fi

        for pattern_entry in "${patterns[@]}"; do
            local pattern_name="${pattern_entry%%|*}"
            local pattern_regex="${pattern_entry##*|}"

            # grep -n for line numbers, suppress actual match content
            local matches
            matches=$(grep -nE "$pattern_regex" "$full_path" 2>/dev/null | cut -d: -f1)

            if [[ -n "$matches" ]]; then
                while IFS= read -r line_num; do
                    # Log to file (no secret content)
                    echo "FOUND: ${pattern_name} at ${f}:${line_num}" >> "$secrets_log"
                    # Print to stderr (no secret content — only file, line, pattern)
                    log_error "Secret detected: ${pattern_name} pattern at ${f}:${line_num}"
                done <<< "$matches"
                found_secrets=true
            fi
        done
    done <<< "$files_to_scan"

    if $found_secrets; then
        echo "RESULT: BLOCKED" >> "$secrets_log"
        return 1
    fi

    echo "RESULT: CLEAN" >> "$secrets_log"
    return 0
}
```

Integration into `grounding_run()` (add after the existing Check 6: test coverage):

```bash
    # Check 9: Secrets detection (BLOCKING)
    if grounding_check_secrets "$task_id" "$worktree_path"; then
        results+=("${COLOR_SUCCESS}${SYM_CHECK} No committed secrets${RESET}")
    else
        results+=("${COLOR_ERROR}${SYM_CROSS} Committed secrets detected — pipeline blocked${RESET}")
        all_passed=false
    fi
```

### Additions to `lib/gates.sh`

Add after the existing `for gate_type in lint typecheck test; do ... done` block inside `gates_run()`:

```bash
# ── SAST gate (warnings only) ──────────────────────────────────────
# Run SAST tool if configured. Findings are printed as warnings but
# never cause gate failure. This separation from the main gate loop
# is intentional: SAST is security-specific, always warn-only, and
# has its own output format.
#
# Args: task_id worktree_path
# Returns: 0 always

gate_sast() {
    local task_id="$1"
    local worktree_path="${2:-$PROJECT_ROOT}"

    local sast_cmd="${TOML_SECURITY_SAST_CMD:-}"
    if [[ -z "$sast_cmd" ]]; then
        return 0  # Not configured — skip silently
    fi

    # Determine feature name from task
    local task_json="${TASKS_DIR}/${task_id}.json"
    local feature_name
    feature_name=$(jq -r '.feature // "unknown"' "$task_json" 2>/dev/null)
    local logs_dir="${STATE_DIR}/features/${feature_name}/logs"
    local raw_output="${logs_dir}/sast-output.json"
    local parsed_output="${logs_dir}/sast-findings.json"

    mkdir -p "$logs_dir"

    log_step "Running SAST: ${COLOR_DIM}${sast_cmd}${RESET}"

    # Run SAST tool
    local sast_exit=0
    (cd "$worktree_path" && eval "$sast_cmd" > "$raw_output" 2>&1) || sast_exit=$?

    if [[ ! -s "$raw_output" ]]; then
        if [[ $sast_exit -ne 0 ]]; then
            log_warn "SAST tool failed (exit ${sast_exit}). Is '${sast_cmd%% *}' installed?"
        fi
        return 0
    fi

    # Parse into normalized format
    security_sast_parse "$raw_output" "$parsed_output"

    # Count and display findings
    local count
    count=$(jq 'length' "$parsed_output" 2>/dev/null || echo "0")

    if [[ "$count" -gt 0 ]]; then
        # Build severity summary
        local summary
        summary=$(jq -r '
            group_by(.severity) |
            map("\(length) \(.[0].severity)") |
            join(", ")
        ' "$parsed_output")

        results+=("${COLOR_WARN}${SYM_WARN} SAST: ${count} finding(s) (${summary})${RESET}")

        # Print individual findings (compact)
        jq -r '.[] | "    [\(.severity)] \(.title) — \(.file):\(.line)"' "$parsed_output" | \
        while IFS= read -r line; do
            echo -e "  ${COLOR_WARN}${line}${RESET}"
        done
    else
        results+=("${COLOR_SUCCESS}${SYM_CHECK} SAST: no findings${RESET}")
    fi

    return 0  # Always pass — findings are warnings
}

# ── SCA gate (warnings only) ───────────────────────────────────────
# Run SCA tool if configured. Same warn-only behavior as SAST.
# SCA checks lockfiles, not source — runs against worktree root.
#
# Args: task_id worktree_path
# Returns: 0 always

gate_sca() {
    local task_id="$1"
    local worktree_path="${2:-$PROJECT_ROOT}"

    local sca_cmd="${TOML_SECURITY_SCA_CMD:-}"
    if [[ -z "$sca_cmd" ]]; then
        return 0  # Not configured — skip silently
    fi

    local task_json="${TASKS_DIR}/${task_id}.json"
    local feature_name
    feature_name=$(jq -r '.feature // "unknown"' "$task_json" 2>/dev/null)
    local logs_dir="${STATE_DIR}/features/${feature_name}/logs"
    local raw_output="${logs_dir}/sca-output.json"
    local parsed_output="${logs_dir}/sca-findings.json"

    mkdir -p "$logs_dir"

    log_step "Running SCA: ${COLOR_DIM}${sca_cmd}${RESET}"

    local sca_exit=0
    (cd "$worktree_path" && eval "$sca_cmd" > "$raw_output" 2>&1) || sca_exit=$?

    if [[ ! -s "$raw_output" ]]; then
        if [[ $sca_exit -ne 0 ]]; then
            log_warn "SCA tool failed (exit ${sca_exit}). Is '${sca_cmd%% *}' installed?"
        fi
        return 0
    fi

    security_sca_parse "$raw_output" "$parsed_output"

    local count
    count=$(jq 'length' "$parsed_output" 2>/dev/null || echo "0")

    if [[ "$count" -gt 0 ]]; then
        local summary
        summary=$(jq -r '
            group_by(.severity) |
            map("\(length) \(.[0].severity)") |
            join(", ")
        ' "$parsed_output")

        results+=("${COLOR_WARN}${SYM_WARN} SCA: ${count} finding(s) (${summary})${RESET}")

        jq -r '.[] | "    [\(.severity)] \(.title)"' "$parsed_output" | \
        while IFS= read -r line; do
            echo -e "  ${COLOR_WARN}${line}${RESET}"
        done
    else
        results+=("${COLOR_SUCCESS}${SYM_CHECK} SCA: no findings${RESET}")
    fi

    return 0
}
```

Integration into `gates_run()` (add after the test gate loop, before printing results):

```bash
    # Gate 5-6: Security gates (always warn-only)
    gate_sast "$task_id" "$worktree_path"
    gate_sca "$task_id" "$worktree_path"
```

### Audit security section check (S6)

A new shell module `lib/security-audit-check.sh` provides a deterministic check for `## Security & Controls` sections in spec files. Checking whether a markdown heading exists is a binary question — a shell grep is 100% reliable; delegating it to an LLM agent introduces unnecessary probabilism for no gain.

`check_security_section(spec_file)` — greps for a `## Security` heading (case-insensitive, matching variations like `## Security & Controls`, `## Security Considerations`). Returns a warning-level finding if the heading is missing or the section is empty (no content between the heading and the next `##` or end of file).

`check_security_sections_in_specs(specs_dir)` — runs `check_security_section` against all `.md` files in the specs directory. Collects and returns warnings.

The `speed audit` command calls `check_security_sections_in_specs` as a pre-audit or post-audit shell step and includes warnings in its output. Warnings do not block the audit.

### Security defect routing (S9)

`security_create_defects()` writes a `Classification-Override: moderate` field into each generated defect spec. When the triage agent reads a defect spec with this field, it skips trivial classification and routes the defect to moderate or higher. The field also includes a `Tags: security` line that the triage agent preserves in `triage.json` for downstream filtering.

The generated defect spec template:

```markdown
# Defect: sec-<slug>
Severity: <P-level mapped from finding severity>
Related Feature: <feature-name>
Tags: security
Classification-Override: moderate
Observed: <finding title + description>
Expected: <recommendation from finding>
Repro: See <file>:<line> — <snippet>
```

Severity mapping: `critical` → P0, `high` → P1, `medium` → P2, `low` → P3.

### Additions to `lib/toml.py`

Add to the `emit()` function after the existing `[ui]` section handler:

```python
    # [security] section
    security = data.get("security", {})
    if isinstance(security, dict):
        for key in ("sast_cmd", "sca_cmd", "severity_threshold"):
            val = security.get(key)
            if val is not None:
                var_name = f"TOML_SECURITY_{key.upper()}"
                print(f"{var_name}='{shell_escape(str(val))}'")

        # Array fields → space-separated strings
        for key in ("secrets_patterns", "secrets_exclude"):
            val = security.get(key)
            if val is not None:
                if isinstance(val, list):
                    joined = " ".join(str(v) for v in val)
                else:
                    joined = str(val)
                var_name = f"TOML_SECURITY_{key.upper()}"
                print(f"{var_name}='{shell_escape(joined)}'")
```

### Additions to `lib/context_bridge.sh`

```bash
# ── Security Auditor assembly ──────────────────────────────────────
# Assembles the prompt for the Security Auditor agent (Layer 3).
# Collects all feature-scope files, specs, and conventions.
# Args: feature_name
# Returns: assembled prompt on stdout

context_assemble_security_auditor() {
    local feature_name="$1"

    $(_context_python) - "$feature_name" <<'PYTHON_EOF'
import sys, os, json

feature_name = sys.argv[1]
project_root = os.environ.get("PROJECT_ROOT", ".")
context_dir = os.path.join(project_root, ".speed", "context")
feature_dir = os.path.join(project_root, ".speed", "features", feature_name)
tasks_dir = os.path.join(feature_dir, "tasks")

# Collect all files in feature scope from task declarations
feature_files = set()
if os.path.isdir(tasks_dir):
    for fname in sorted(os.listdir(tasks_dir)):
        if fname.endswith(".json"):
            with open(os.path.join(tasks_dir, fname)) as f:
                task = json.load(f)
            for ft in task.get("files_touched", []):
                feature_files.add(ft)

# Load specs
specs = {}
for spec_type in ("product", "tech"):
    spec_path = os.path.join(project_root, "specs", spec_type, f"{feature_name}.md")
    if os.path.isfile(spec_path):
        with open(spec_path) as f:
            specs[spec_type] = f.read()

# Load CLAUDE.md conventions
conventions = ""
claude_md = os.path.join(project_root, "CLAUDE.md")
if os.path.isfile(claude_md):
    with open(claude_md) as f:
        conventions = f.read()

# Assemble prompt
sections = []
sections.append(f"# Security Audit: {feature_name}")
sections.append("")
sections.append("## Files in scope")
sections.append(f"Feature '{feature_name}' touches {len(feature_files)} file(s):")
for fp in sorted(feature_files):
    full = os.path.join(project_root, fp)
    if os.path.isfile(full):
        sections.append(f"\n### {fp}")
        with open(full) as f:
            sections.append(f.read())

if specs.get("product"):
    sections.append("\n## Product spec")
    sections.append(specs["product"])

if specs.get("tech"):
    sections.append("\n## Tech spec")
    sections.append(specs["tech"])

if conventions:
    sections.append("\n## Project conventions")
    sections.append(conventions)

print("\n".join(sections))
PYTHON_EOF
}
```

### `cmd_security()` in `speed`

```bash
cmd_security() {
    local create_defects=false
    local feature_name="${GLOBAL_FEATURE:-}"

    # Parse flags
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --create-defects) create_defects=true; shift ;;
            --feature)        feature_name="$2"; shift 2 ;;
            -f)               feature_name="$2"; shift 2 ;;
            *)                log_error "Unknown flag: $1"; exit 1 ;;
        esac
    done

    # Resolve feature
    if [[ -z "$feature_name" ]]; then
        feature_name=$(_current_feature)
    fi
    if [[ -z "$feature_name" ]]; then
        log_error "No active feature. Run speed plan first or specify --feature."
        exit 1
    fi

    log_header "Security Audit — ${feature_name}"

    local logs_dir="${STATE_DIR}/features/${feature_name}/logs"
    local audit_file="${logs_dir}/security-audit.json"

    # Run audit (or use cache)
    if $create_defects && security_has_cached_audit "$feature_name"; then
        log_info "Using cached audit results (< 1 hour old)"
    else
        security_audit_run "$feature_name"
    fi

    # Print findings banner
    if [[ -f "$audit_file" ]]; then
        security_print_banner "$audit_file"
    else
        log_info "No security findings."
    fi

    # Create defects if requested
    if $create_defects; then
        local threshold="${TOML_SECURITY_SEVERITY_THRESHOLD:-medium}"

        if [[ ! -f "$audit_file" ]]; then
            log_error "No audit results to create defects from."
            exit 1
        fi

        security_create_defects "$audit_file" "$threshold"
    fi
}
```

### Agent definition

**File:** `agents/security-auditor.md`
**Model:** `support_model` (sonnet by default)
**Access:** Read-only codebase access (Read, Glob, Grep tools). No file writes, no shell commands.

The Security Auditor receives:
- All files in the feature's scope (from task declarations)
- The feature's product spec and tech spec
- Project conventions from `CLAUDE.md`
- A structured output format matching the `security-audit.json` schema

The agent reads each file in full (not diffs) and evaluates against OWASP categories. Coverage varies by tier:

### OWASP Top 10 coverage by tier

| OWASP Category | Grounding (secrets) | SAST (Tier 1) | SCA (Tier 1) | Agent (Tier 2) |
|---|---|---|---|---|
| A01: Broken Access Control | | Partial (missing auth middleware patterns) | | Yes (can trace route → middleware → handler chains) |
| A02: Cryptographic Failures | | Yes (weak algorithm detection) | | Yes (can evaluate crypto usage in context) |
| A03: Injection (SQL, NoSQL, OS, LDAP) | | Yes (pattern-based detection) | | Yes (can follow data flow from input to query) |
| A04: Insecure Design | | | | Partial (can flag missing validation, but design-level issues need human review) |
| A05: Security Misconfiguration | | Yes (hardcoded configs, debug flags) | | Yes (can check config files holistically) |
| A06: Vulnerable Components | | | Yes (CVE lookup in dependency tree) | |
| A07: Auth Failures (weak passwords, session) | Yes (hardcoded credentials) | Yes (weak password patterns) | | Yes (can evaluate session handling logic) |
| A08: Data Integrity Failures | | | Yes (known-compromised package versions) | Partial (can detect missing signature checks) |
| A09: Logging & Monitoring Failures | | | | Partial (can flag missing audit logging, but coverage is best-effort) |
| A10: SSRF | | Yes (URL construction patterns) | | Yes (can trace URL sources to request calls) |

Key gaps: A04 (Insecure Design) and A09 (Logging Failures) are fundamentally hard to catch with automated tools. The Security Auditor agent can flag obvious omissions, but these categories ultimately require human security review.

## Validation Rules

| Field | Constraints |
|-------|-------------|
| `severity` (finding) | Required. One of: `critical`, `high`, `medium`, `low`, `info`. |
| `category` (finding) | Required. One of: `injection`, `auth`, `secrets`, `crypto`, `config`, `xss`, `path-traversal`, `info-disclosure`, `vulnerable-dependency`. |
| `file` (finding) | Required. Must be a relative path from project root. Must exist in the feature's file scope. |
| `line` (finding) | Required. Positive integer. |
| `severity_threshold` (config) | One of: `critical`, `high`, `medium`, `low`, `info`. Default: `medium`. |
| `sast_cmd` (config) | Non-empty string when present. No validation of the command itself (trusted config). |
| `sca_cmd` (config) | Non-empty string when present. Same trust model as `sast_cmd`. |
| `secrets_patterns` (config) | Array of strings. Each must match a built-in pattern name. Unrecognized names produce a warning at config load. |
| `secrets_exclude` (config) | Array of glob strings. Matched against file paths relative to project root. Invalid globs produce a warning at config load. |
| `id` (finding) | Required. Unique within a single audit run. Format: `SEC-<NNN>` (e.g., `SEC-001`). |

## Security & Controls

**Agent isolation:** The Security Auditor agent has read-only access. It cannot write files, execute shell commands, or make network requests. All SAST tool execution is handled by the pipeline shell (`lib/security.sh`), not the agent.

**Secrets scanner output sanitization:** `grounding_check_secrets()` never echoes the matched secret value. Error messages reference file path, line number, and pattern name (e.g., "AWS key pattern matched at src/config.py:12"). The actual secret content is redacted.

**Path traversal prevention:** File paths from SAST output and agent findings are validated against the project root before use. Paths containing `..` or absolute paths outside the project are rejected with an error.

**SAST command trust model:** `sast_cmd` in `speed.toml` is executed via shell. The same trust model applies as for `CLAUDE.md`: the config file is part of the repository and reviewed via normal code review. SPEED does not sanitize or sandbox the SAST command.

## Key Decisions

| Decision | Choice | Alternatives Considered | Rationale |
|----------|--------|------------------------|-----------|
| Two-tier security model | Tier 1 (SAST in gates) + Tier 2 (agent audit on demand) | Single-tier SAST only; single-tier agent only; three tiers with runtime scanning | SAST catches known patterns cheaply on every run. The agent catches logic-level issues that SAST misses but costs more tokens. Keeping them separate lets engineers choose depth. |
| Warn, never block (except secrets) | Security findings produce warnings, not gate failures | Block on high/critical; block on any finding; always warn | Blocking on security findings in an automated pipeline creates a perverse incentive to disable security checks. Loud warnings with a defect creation path gives visibility without friction. |
| Committed secrets are blocking at grounding | Secrets detection fails the grounding gate, halting the pipeline | Warn on secrets like other findings; block only on high-entropy matches | A committed secret is not a code quality issue. Once committed to git history, removal requires history rewriting. The cost of a false negative (leaked secret) vastly exceeds the cost of a false positive (pipeline halt on a test fixture). |
| Full-file reads, not diffs | Security Auditor reads complete source files, not just changed lines | Diff-only analysis; diff + N lines of context; full files only for flagged files | Security vulnerabilities often span multiple functions or files. A diff showing a new API endpoint doesn't reveal that the auth middleware is missing from the route definition three files away. Full-file reads catch context-dependent issues. |
| Different recovery model | No retries for security failures; create defects instead | Retry with agent; retry with different model; auto-fix | Security findings require human judgment about intent and risk tolerance. Auto-retry assumes the fix is mechanical, but security fixes often involve design decisions (add auth check vs. restructure the endpoint). The defect pipeline provides the structured path. |
| Security defects skip trivial classification | Security-tagged defects route to moderate or higher in triage | Normal triage classification; always route to complex; skip triage entirely | Trivial triage auto-fixes without human review. Security fixes need human eyes. Routing to moderate ensures a reproduce stage (failing test) and review stage, providing the scrutiny security issues warrant. |

## Search / Query Strategy

Not applicable. The security feature introduces no new database queries, search indexes, or query patterns. Findings are written and read as flat JSON files in `.speed/features/<name>/logs/`.

## Migration Strategy

Not applicable. The security feature is a greenfield addition. No existing data structures are modified. Projects without `[security]` in `speed.toml` see no behavioral change beyond the always-on grounding-level secrets scanner.

## Drawbacks

- **Agent token cost scales with feature size.** The Security Auditor reads full files. A feature touching 20 files across 3,000 lines consumes significant context. On large features, the audit cost could exceed the cost of the Developer Agent run that produced the code.
- **False positive noise from SAST.** Generic SAST rulesets (e.g., `semgrep --config auto`) produce false positives, especially for framework-specific patterns. Engineers may learn to ignore the warnings, defeating the purpose. The `severity_threshold` config helps but doesn't eliminate the problem.
- **External tool dependency for SAST and SCA.** SPEED doesn't ship SAST or SCA tools. Projects must install and configure them. If a configured tool is missing or misconfigured, the corresponding gate silently skips (by design), which means engineers may think they have coverage when they don't. SCA tools are more forgiving here since most ecosystems ship one built-in (`npm audit`, `composer audit`), but SAST almost always requires an explicit install.
- **No DAST coverage.** Static analysis catches pattern-based vulnerabilities but misses runtime issues (CORS misconfiguration, session handling bugs, race conditions). The security audit provides a false sense of completeness for engineers unfamiliar with security testing tiers.
- **Secrets scanner pattern maintenance.** Built-in regex patterns for secret detection require ongoing maintenance as providers change key formats. Stale patterns mean missed detections. There's no auto-update mechanism.

## File Impact

| File | Change |
|------|--------|
| `speed` | Add `cmd_security()` to command dispatch. Modify `cmd_status()` to include security summary. |
| `lib/security.sh` | New file. Functions: `security_audit_run`, `security_sast_run`, `security_sast_parse`, `security_sca_run`, `security_sca_parse`, `security_print_banner`, `security_create_defects`, `security_has_cached_audit`. |
| `lib/grounding.sh` | Add `grounding_check_secrets()`. Call it from `grounding_run()`. |
| `lib/gates.sh` | Add `gate_sast()` and `gate_sca()`. Call both from `gates_run()` after existing gates. |
| `lib/toml.py` | Extend to emit `TOML_SECURITY_*` variables from `[security]` section. |
| `lib/context_bridge.sh` | Add `context_assemble_security_auditor()` for agent prompt assembly. |
| `agents/security-auditor.md` | New file. Agent definition for the Security Auditor (model, tools, instructions, output format). |
| `lib/security-audit-check.sh` | New file. Deterministic shell check for `## Security & Controls` section presence in spec files. Integrated into `speed audit` as a pre/post-audit step. |
| `templates/speed-toml.toml` | Add commented `[security]` section with defaults and documentation. |

## Dependencies

- **Existing pipeline infrastructure:** Quality gates (`lib/gates.sh`), grounding gates (`lib/grounding.sh`), agent execution (`lib/provider.sh`), TOML config (`lib/toml.py`), context assembly (`lib/context_bridge.sh`), CLI dispatch (`speed`)
- **Defect pipeline** ([Phase 3: Defect Pipeline](speed-defects.md)) — Required for `security_create_defects()` to generate defect specs. Without it, `--create-defects` exits with an error message pointing to the defect pipeline spec.
- **Audit agent** ([Phase 2: Audit Agent](speed-audit.md)) — The `speed audit` command provides the integration point for the security section check shell step.

## Unresolved Questions

- **SAST output normalization:** Different SAST tools produce different JSON schemas (Semgrep, Bandit, ESLint security plugins). How many parsers should `security_sast_parse()` support at launch? Starting with Semgrep-only and adding parsers as needed is the path of least complexity, but limits initial adoption for teams using other tools.
- **Secrets pattern extensibility:** Should `speed.toml` support custom regex patterns for secrets detection, or only named built-in patterns? Custom regex gives flexibility but increases misconfiguration risk (a bad pattern causes false positives on every run).
- **Audit caching duration:** The current design caches `security-audit.json` for 1 hour. Is that the right duration? Too short means redundant agent runs; too long means stale results when code changes between `speed security` and `speed security --create-defects`.
- **Security Auditor model choice:** The plan defaults to `support_model` (sonnet). For full-file reads of security-sensitive code, `planning_model` (opus) may produce higher-quality findings. The cost/quality tradeoff needs empirical testing.
