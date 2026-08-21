#!/usr/bin/env bash
# security.sh — Security scanning utilities: severity helpers, SAST/SCA parsers, banner
#
# Requires: config.sh and log.sh sourced before this file.
# Uses: _context_python() from lib/context_bridge.sh for inline Python execution.

# ── Source guard ───────────────────────────────────────────────────────────────
if [[ -n "${_SECURITY_SH_LOADED:-}" ]]; then return 0; fi
_SECURITY_SH_LOADED=1

# ── Severity helpers ───────────────────────────────────────────────────────────

# _severity_rank(severity_string) — echoes numeric rank for a severity level
# critical=5, high=4, medium=3, low=2, info=1
_severity_rank() {
    case "${1:-}" in
        critical) echo 5 ;;
        high)     echo 4 ;;
        medium)   echo 3 ;;
        low)      echo 2 ;;
        info)     echo 1 ;;
        *)        echo 0 ;;
    esac
}

# _severity_to_priority(severity_string) — echoes priority code
# critical=P0, high=P1, medium=P2, low=P3, info=P3
_severity_to_priority() {
    case "${1:-}" in
        critical) echo P0 ;;
        high)     echo P1 ;;
        medium)   echo P2 ;;
        low)      echo P3 ;;
        info)     echo P3 ;;
        *)        echo P3 ;;
    esac
}

# _severity_at_or_above(level, threshold)
# Returns 0 (true) if level >= threshold by rank, 1 (false) otherwise.
# Both arguments are severity strings: critical, high, medium, low, info.
_severity_at_or_above() {
    local level="${1:-info}"
    local threshold="${2:-info}"
    local level_rank threshold_rank
    level_rank=$(_severity_rank "$level")
    threshold_rank=$(_severity_rank "$threshold")
    [[ "$level_rank" -ge "$threshold_rank" ]]
}

# ── SAST parser ────────────────────────────────────────────────────────────────

# security_sast_parse(raw_json_path, output_path)
# Reads tool-specific SAST JSON (Semgrep or Bandit) and writes a normalized
# findings array to output_path. Writes [] on missing file or JSON decode error.
security_sast_parse() {
    local raw_json_path="${1:-}"
    local output_path="${2:-}"

    local py_bin
    py_bin=$(_context_python)

    "$py_bin" - <<PYEOF
import json, sys, os

raw_path = """${raw_json_path}"""
out_path = """${output_path}"""

def _map_semgrep_category(check_id):
    """Map a Semgrep check_id pattern to an OWASP category string."""
    cid = check_id.lower()
    # Check more specific patterns first to avoid false matches
    if any(k in cid for k in ("xss", "cross-site-scripting", "html-inject")):
        return "xss"
    if any(k in cid for k in ("sqli", "sql-inject", "sql_inject", "sql")):
        return "injection"
    if any(k in cid for k in ("auth", "authz", "authn", "privilege", "permission", "access-control")):
        return "auth"
    if any(k in cid for k in ("crypto", "cipher", "hash", "encrypt", "tls", "ssl", "weak-rand", "random")):
        return "crypto"
    if any(k in cid for k in ("path-traversal", "directory-traversal", "lfi", "rfi")):
        return "path-traversal"
    if any(k in cid for k in ("command", "cmd-inject", "exec", "shell")):
        return "command-injection"
    if any(k in cid for k in ("deserializ", "pickle", "yaml.load", "unsafe-load")):
        return "deserialization"
    if any(k in cid for k in ("secret", "credential", "api-key", "password", "token", "hardcode")):
        return "sensitive-data"
    if "inject" in cid:
        return "injection"
    return "other"

def _map_semgrep_severity(raw):
    mapping = {"ERROR": "high", "WARNING": "medium", "INFO": "low"}
    return mapping.get(raw.upper(), "info")

def _map_bandit_severity(raw):
    mapping = {"HIGH": "high", "MEDIUM": "medium", "LOW": "low"}
    return mapping.get(raw.upper(), "info")

findings = []

if not os.path.isfile(raw_path):
    with open(out_path, "w") as f:
        json.dump([], f)
    sys.exit(0)

try:
    with open(raw_path) as f:
        data = json.load(f)
except (json.JSONDecodeError, OSError):
    with open(out_path, "w") as f:
        json.dump([], f)
    sys.exit(0)

counter = 1

# Semgrep format: {"results": [...]}
if isinstance(data, dict) and "results" in data and "generated_at" not in data:
    for item in data.get("results", []):
        severity = _map_semgrep_severity(item.get("extra", {}).get("severity", item.get("severity", "INFO")))
        check_id = item.get("check_id", "")
        category = _map_semgrep_category(check_id)
        path = item.get("path", "")
        line = item.get("start", {}).get("line", 0)
        message = item.get("extra", {}).get("message", item.get("message", ""))
        findings.append({
            "id": "SAST-{:03d}".format(counter),
            "tool": "semgrep",
            "severity": severity,
            "category": category,
            "title": check_id,
            "file": path,
            "line": line,
            "message": message,
        })
        counter += 1

# Bandit format: {"results": [...], "generated_at": "..."}
elif isinstance(data, dict) and "results" in data and "generated_at" in data:
    for item in data.get("results", []):
        severity = _map_bandit_severity(item.get("issue_severity", "LOW"))
        findings.append({
            "id": "SAST-{:03d}".format(counter),
            "tool": "bandit",
            "severity": severity,
            "category": "other",
            "title": item.get("test_name", ""),
            "file": item.get("filename", ""),
            "line": item.get("line_number", 0),
            "message": item.get("issue_text", ""),
        })
        counter += 1

with open(out_path, "w") as f:
    json.dump(findings, f, indent=2)
PYEOF
}

# ── SCA parser ─────────────────────────────────────────────────────────────────

# security_sca_parse(raw_json_path, output_path)
# Reads tool-specific SCA JSON (npm audit or pip-audit) and writes a normalized
# findings array to output_path. Writes [] on missing/invalid input.
security_sca_parse() {
    local raw_json_path="${1:-}"
    local output_path="${2:-}"

    local py_bin
    py_bin=$(_context_python)

    "$py_bin" - <<PYEOF
import json, sys, os

raw_path = """${raw_json_path}"""
out_path = """${output_path}"""

def _map_npm_severity(raw):
    mapping = {
        "critical": "critical",
        "high": "high",
        "moderate": "medium",
        "low": "low",
        "info": "info",
    }
    return mapping.get(raw.lower(), "info")

findings = []

if not os.path.isfile(raw_path):
    with open(out_path, "w") as f:
        json.dump([], f)
    sys.exit(0)

try:
    with open(raw_path) as f:
        data = json.load(f)
except (json.JSONDecodeError, OSError):
    with open(out_path, "w") as f:
        json.dump([], f)
    sys.exit(0)

counter = 1

# npm audit format: {"vulnerabilities": {"pkg": {...}}}
if isinstance(data, dict) and "vulnerabilities" in data:
    for pkg_name, vuln in data["vulnerabilities"].items():
        severity = _map_npm_severity(vuln.get("severity", "info"))
        via = vuln.get("via", [])
        # via entries can be strings (transitive) or dicts (direct)
        advisories = [v for v in via if isinstance(v, dict)]
        title = advisories[0].get("title", pkg_name) if advisories else pkg_name
        fix_available = vuln.get("fixAvailable", False)
        if isinstance(fix_available, dict):
            recommendation = "Update to {}@{}".format(
                fix_available.get("name", pkg_name),
                fix_available.get("version", "latest"),
            )
        elif fix_available:
            recommendation = "Update to fixed version"
        else:
            recommendation = "No fix available"
        findings.append({
            "id": "SCA-{:03d}".format(counter),
            "tool": "npm-audit",
            "severity": severity,
            "category": "dependency",
            "title": title,
            "package": pkg_name,
            "range": vuln.get("range", ""),
            "recommendation": recommendation,
        })
        counter += 1

# pip-audit format: [{"name": ..., "vulns": [...]}]
elif isinstance(data, list):
    for pkg in data:
        pkg_name = pkg.get("name", "")
        for vuln in pkg.get("vulns", []):
            cve_id = vuln.get("id", "")
            description = vuln.get("description", "")
            fix_versions = vuln.get("fix_versions", [])
            title = "{} in {}".format(cve_id, pkg_name) if cve_id else pkg_name
            recommendation = "Update to {}".format(", ".join(fix_versions)) if fix_versions else "No fix available"
            findings.append({
                "id": "SCA-{:03d}".format(counter),
                "tool": "pip-audit",
                "severity": "high",
                "category": "dependency",
                "title": title,
                "package": pkg_name,
                "cve": cve_id,
                "description": description,
                "recommendation": recommendation,
            })
            counter += 1

with open(out_path, "w") as f:
    json.dump(findings, f, indent=2)
PYEOF
}

# ── Security banner ────────────────────────────────────────────────────────────

# security_print_banner(security_audit_json_path)
# Reads security-audit.json (agent output schema) and prints a formatted banner
# with severity breakdown and per-finding detail lines.
# Handles missing file gracefully.
security_print_banner() {
    local audit_json_path="${1:-}"

    if [[ -z "$audit_json_path" ]] || [[ ! -f "$audit_json_path" ]]; then
        echo -e "${COLOR_WARN}No security audit results found.${RESET}"
        return 0
    fi

    local total by_severity

    total=$(jq -r '.summary.total // 0' "$audit_json_path" 2>/dev/null) || total=0
    by_severity=$(jq -r '.summary.by_severity // {}' "$audit_json_path" 2>/dev/null) || by_severity="{}"

    echo ""
    echo -e "${BOLD}Security Audit Results${RESET}"
    echo -e "${COLOR_DIM}────────────────────────────────────${RESET}"
    echo -e "  Total findings: ${BOLD}${total}${RESET}"
    echo ""

    # Print severity breakdown
    local critical high medium low info
    critical=$(echo "$by_severity" | jq -r '.critical // 0' 2>/dev/null) || critical=0
    high=$(echo "$by_severity" | jq -r '.high // 0' 2>/dev/null) || high=0
    medium=$(echo "$by_severity" | jq -r '.medium // 0' 2>/dev/null) || medium=0
    low=$(echo "$by_severity" | jq -r '.low // 0' 2>/dev/null) || low=0
    info=$(echo "$by_severity" | jq -r '.info // 0' 2>/dev/null) || info=0

    [[ "$critical" -gt 0 ]] && echo -e "  ${COLOR_ERROR}Critical: ${critical}${RESET}"
    [[ "$high" -gt 0 ]]     && echo -e "  ${COLOR_ERROR}High:     ${high}${RESET}"
    [[ "$medium" -gt 0 ]]   && echo -e "  ${COLOR_WARN}Medium:   ${medium}${RESET}"
    [[ "$low" -gt 0 ]]      && echo -e "  ${COLOR_DIM}Low:      ${low}${RESET}"
    [[ "$info" -gt 0 ]]     && echo -e "  ${COLOR_DIM}Info:     ${info}${RESET}"

    echo ""

    # Per-finding detail lines
    local findings_count
    findings_count=$(jq '.findings | length' "$audit_json_path" 2>/dev/null) || findings_count=0

    if [[ "$findings_count" -gt 0 ]]; then
        echo -e "${BOLD}Findings:${RESET}"
        jq -r '.findings[] | "  [\(.severity | ascii_upcase)] \(.id // "") \(.title // .message // "") (\(.file // ""):\(.line // ""))"' \
            "$audit_json_path" 2>/dev/null | while IFS= read -r line; do
            local severity_part
            severity_part=$(echo "$line" | sed -n 's/.*\[\([A-Z]*\)\].*/\1/p')
            case "$severity_part" in
                CRITICAL|HIGH) echo -e "  ${COLOR_ERROR}${line}${RESET}" ;;
                MEDIUM)        echo -e "  ${COLOR_WARN}${line}${RESET}" ;;
                *)             echo -e "  ${COLOR_DIM}${line}${RESET}" ;;
            esac
        done
        echo ""
    fi

    echo -e "${COLOR_WARN}Security issues found — review before merging. Gate not blocking.${RESET}"
    echo ""
}

# ── Audit orchestration ───────────────────────────────────────────────────────

# security_audit_run(feature_name)
# Runs the Security Auditor agent on the given feature and writes the parsed
# output to security-audit.json in the feature's logs directory.
# Returns 0 always (audit failures are non-blocking).
security_audit_run() {
    local feature_name="${1:-}"
    local logs_dir="${STATE_DIR}/features/${feature_name}/logs"

    mkdir -p "$logs_dir"

    log_step "Running Security Auditor agent on feature '${feature_name}'..."

    # Assemble the audit prompt via context bridge
    local prompt
    prompt=$(context_assemble_security_auditor "$feature_name")

    if [[ -z "$prompt" ]]; then
        log_error "Security auditor context assembly returned empty for '${feature_name}'"
        return 0
    fi

    # Write prompt to temp file for provider_run_json
    local prompt_file
    prompt_file=$(mktemp "${TMPDIR:-/tmp}/speed-sec-audit-XXXXXX")
    echo "$prompt" > "$prompt_file"

    # Run the security auditor agent
    local agent_output
    agent_output=$(provider_run_json \
        "${SPEED_DIR}/agents/security-auditor.md" \
        "$(cat "$prompt_file")" \
        "${SPEED_DIR}/templates/security-audit-output.json" \
        "$MODEL_SUPPORT" \
        "10" \
        "" \
        "Security Auditor" \
        "900") || true

    rm -f "$prompt_file"

    # Parse agent output
    local parsed
    parsed=$(parse_agent_json "$agent_output") || {
        log_warn "Could not parse Security Auditor output as JSON"
        return 0
    }

    # Write parsed JSON to logs directory
    echo "$parsed" | jq '.' > "${logs_dir}/security-audit.json"

    return 0
}

# security_has_cached_audit(feature_name)
# Returns 0 if a security-audit.json exists for the feature and is less than
# 1 hour old. Returns 1 otherwise.
security_has_cached_audit() {
    local feature_name="${1:-}"
    local audit_file="${STATE_DIR}/features/${feature_name}/logs/security-audit.json"

    [[ -f "$audit_file" ]] || return 1

    local file_mtime now age
    # Darwin (macOS) and Linux use different stat flags
    if [[ "$(uname -s)" == "Darwin" ]]; then
        file_mtime=$(stat -f %m "$audit_file")
    else
        file_mtime=$(stat -c %Y "$audit_file")
    fi
    now=$(date +%s)
    age=$(( now - file_mtime ))

    [[ "$age" -lt 3600 ]]
}

# security_create_defects(audit_json, threshold)
# Reads the security audit JSON and creates defect spec files for findings
# at or above the given severity threshold.
# Returns 1 if audit_json is missing, 0 otherwise.
security_create_defects() {
    local audit_json="${1:-}"
    local threshold="${2:-medium}"

    if [[ -z "$audit_json" ]] || [[ ! -f "$audit_json" ]]; then
        log_error "Audit JSON not found: ${audit_json}"
        return 1
    fi

    mkdir -p "specs/defects"

    local feature_name
    feature_name=$(jq -r '.feature // ""' "$audit_json" 2>/dev/null)

    local findings_count
    findings_count=$(jq '.findings | length' "$audit_json" 2>/dev/null) || findings_count=0

    local created=0
    local skipped=0
    local i=0

    while [[ $i -lt $findings_count ]]; do
        local severity title description file line snippet recommendation category
        severity=$(jq -r ".findings[$i].severity // \"info\"" "$audit_json")
        title=$(jq -r ".findings[$i].title // \"\"" "$audit_json")
        description=$(jq -r ".findings[$i].description // .findings[$i].message // \"\"" "$audit_json")
        file=$(jq -r ".findings[$i].file // \"\"" "$audit_json")
        line=$(jq -r ".findings[$i].line // \"\"" "$audit_json")
        snippet=$(jq -r ".findings[$i].snippet // \"\"" "$audit_json")
        recommendation=$(jq -r ".findings[$i].recommendation // \"\"" "$audit_json")
        category=$(jq -r ".findings[$i].category // \"\"" "$audit_json")

        # Check if severity meets threshold
        if ! _severity_at_or_above "$severity" "$threshold"; then
            skipped=$((skipped + 1))
            i=$((i + 1))
            continue
        fi

        # Map severity to priority
        local priority
        priority=$(_severity_to_priority "$severity")

        # Slugify title: lowercase, spaces to hyphens, strip non-alphanumeric (except hyphens), truncate
        local slug
        slug=$(echo "$title" | tr '[:upper:]' '[:lower:]' | tr ' ' '-' | sed 's/[^a-z0-9-]//g' | cut -c1-40)

        local defect_file="specs/defects/sec-${slug}.md"

        cat > "$defect_file" <<EOF
Severity: ${priority}
Related Feature: ${feature_name}
Tags: security
Classification-Override: moderate

Observed: ${description}${snippet:+ Snippet: ${snippet}}
Expected: ${recommendation}
Repro: ${file}${line:+:${line}} — category: ${category}
EOF

        log_step "Created ${defect_file}"
        created=$((created + 1))

        i=$((i + 1))
    done

    echo "${created} defect(s) created, ${skipped} skipped (below ${threshold} threshold)"
    return 0
}
