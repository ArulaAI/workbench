#!/usr/bin/env bash
# test_define.sh — Integration tests for `speed define authorisation-risk`
# and for how `speed audit` handles the spec it generates.
#
# Uses a fake `claude` binary (CLAUDE_BIN) that records each prompt and
# replays canned responses, so the full define → write → audit path runs
# without a live agent.
#
# Usage: bash tests/test_define.sh
# Exit: 0 if all tests pass, 1 if any fail

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPEED_SCRIPT="${SCRIPT_DIR}/../speed"
PASS=0
FAIL=0
TEST_DIR=""

# ── Harness ───────────────────────────────────────────────────────

setup() {
    TEST_DIR=$(mktemp -d)
    mkdir -p "${TEST_DIR}/speed/templates" "${TEST_DIR}/speed/lib" "${TEST_DIR}/speed/providers" "${TEST_DIR}/speed/agents"
    mkdir -p "${TEST_DIR}/specs/product" "${TEST_DIR}/specs/tech" "${TEST_DIR}/specs/design"
    mkdir -p "${TEST_DIR}/src/api" "${TEST_DIR}/tests" "${TEST_DIR}/fake/responses" "${TEST_DIR}/fake/prompts"
    cp -r "${SCRIPT_DIR}/../templates/." "${TEST_DIR}/speed/templates/"
    cp -r "${SCRIPT_DIR}/../lib/." "${TEST_DIR}/speed/lib/"
    cp -r "${SCRIPT_DIR}/../providers/." "${TEST_DIR}/speed/providers/"
    cp -r "${SCRIPT_DIR}/../agents/." "${TEST_DIR}/speed/agents/"
    cp "${SPEED_SCRIPT}" "${TEST_DIR}/speed/speed"
    cp "${SCRIPT_DIR}/../sgconfig.yml" "${TEST_DIR}/speed/sgconfig.yml"
    chmod +x "${TEST_DIR}/speed/speed"
    # define and audit never run ast-grep; drop the rules so the startup
    # rule probe cannot fail on hosts without the custom grammar libraries.
    rm -rf "${TEST_DIR}/speed/lib/context/rules"

    cat > "${TEST_DIR}/speed.toml" <<'TOML'
[agent]
provider = "claude-code"
planning_model = "opus"
support_model = "sonnet"
TOML

    # Minimal project: product spec, overview, some code and a test
    cat > "${TEST_DIR}/specs/product/overview.md" <<'MD'
# Product Overview
Customers own their data. Nobody sees another tenant's records.
MD
    cat > "${TEST_DIR}/specs/product/invoices.md" <<'MD'
# PRD: Invoices
## Users
Account owners and accountants.
## User Stories
| ID | Story |
|----|-------|
| S1 | As an account owner I can export my invoices |
MD
    echo "export function authorize() {}" > "${TEST_DIR}/src/api/auth.ts"
    echo "test('403 for other tenant', () => {})" > "${TEST_DIR}/tests/auth.test.ts"

    # Fake claude: save the prompt, emit the next canned response as a
    # stream-json result event.
    cat > "${TEST_DIR}/fake/claude" <<'SH'
#!/usr/bin/env bash
dir="$(cd "$(dirname "$0")" && pwd)"
n=$(( $(ls "$dir/prompts" | wc -l) + 1 ))
cat > "$dir/prompts/${n}.txt"
resp="$dir/responses/${n}.md"
[[ -f "$resp" ]] || resp="$dir/responses/default.md"
jq -cn --rawfile r "$resp" '{type:"result",subtype:"success",result:$r,num_turns:1,duration_ms:1000}'
SH
    chmod +x "${TEST_DIR}/fake/claude"

    (cd "$TEST_DIR" && git init -q && git add -A && git -c user.email=t@t -c user.name=t commit -q -m "init")
}

teardown() {
    rm -rf "$TEST_DIR"
}

run_test() {
    local test_name="$1"
    setup
    local rc=0
    "$test_name" || rc=$?
    teardown
    if [[ $rc -eq 0 ]]; then
        printf "  PASS  %s\n" "$test_name"
        PASS=$((PASS + 1))
    else
        printf "  FAIL  %s\n" "$test_name"
        FAIL=$((FAIL + 1))
    fi
}

assert_exit_code() {
    local expected="$1" actual="$2" context="${3:-}"
    if [[ "$expected" != "$actual" ]]; then
        echo "    ASSERT: expected exit ${expected}, got ${actual}${context:+ (${context})}" >&2
        return 1
    fi
}

assert_contains() {
    local haystack="$1" needle="$2"
    local stripped
    stripped=$(echo "$haystack" | sed 's/\x1b\[[0-9;]*m//g')
    if ! echo "$stripped" | grep -qiF -- "$needle"; then
        echo "    ASSERT: missing '${needle}'" >&2
        echo "    GOT: ${stripped:0:800}" >&2
        return 1
    fi
}

assert_not_contains() {
    local haystack="$1" needle="$2"
    if echo "$haystack" | grep -qiF -- "$needle"; then
        echo "    ASSERT: should not contain '${needle}'" >&2
        return 1
    fi
}

# Run speed with the fake agent; prints combined output.
speed_fake() {
    SPEED_PROJECT_ROOT="$TEST_DIR" CLAUDE_BIN="${TEST_DIR}/fake/claude" \
        "${TEST_DIR}/speed/speed" "$@" 2>&1
}

# A complete spec: every template H2, with a > See link.
write_complete_response() {
    local file="${1:-${TEST_DIR}/fake/responses/default.md}"
    {
        echo "# Authorisation Risk: Invoices"
        echo ""
        echo "> See [product spec](../product/invoices.md) for product context."
        echo "> Spec type: authorisation-risk"
        grep -E '^## ' "${TEST_DIR}/speed/templates/authorisation-risk.md" | while IFS= read -r h; do
            echo ""
            echo "$h"
            echo "Content for ${h#\#\# }."
        done
    } > "$file"
}

# ── Tests: argument handling ─────────────────────────────────────

test_define_no_subject() {
    local rc=0
    speed_fake define >/dev/null || rc=$?
    assert_exit_code 1 "$rc"
}

test_define_unknown_subject() {
    local rc=0 out
    out=$(speed_fake define nonsense foo) || rc=$?
    assert_exit_code 1 "$rc" && assert_contains "$out" "Unknown define subject"
}

test_define_missing_feature() {
    local rc=0
    speed_fake define authorisation-risk >/dev/null || rc=$?
    assert_exit_code 1 "$rc"
}

test_define_missing_product_spec() {
    local rc=0 out
    out=$(speed_fake define authorisation-risk ghost) || rc=$?
    assert_exit_code 3 "$rc" && assert_contains "$out" "Product spec not found"
}

test_define_missing_flagged_input() {
    local rc=0 out
    out=$(speed_fake define authorisation-risk invoices --threat-model specs/nope.md) || rc=$?
    assert_exit_code 3 "$rc" && assert_contains "$out" "Threat Model spec not found"
}

test_define_refuses_overwrite() {
    echo "# existing" > "${TEST_DIR}/specs/tech/invoices-authorisation-risk.md"
    local rc=0 out
    out=$(speed_fake define authorisation-risk invoices) || rc=$?
    assert_exit_code 3 "$rc" && assert_contains "$out" "--force"
    [[ "$(cat "${TEST_DIR}/specs/tech/invoices-authorisation-risk.md")" == "# existing" ]]
}

# ── Tests: generation ────────────────────────────────────────────

test_define_writes_spec() {
    write_complete_response
    local rc=0 out
    out=$(speed_fake define authorisation-risk invoices) || rc=$?
    assert_exit_code 0 "$rc" "$out" || return 1
    local spec="${TEST_DIR}/specs/tech/invoices-authorisation-risk.md"
    [[ -f "$spec" ]] || { echo "    spec not written" >&2; return 1; }
    assert_contains "$(cat "$spec")" "## Risk Register" &&
    assert_contains "$out" "speed audit specs/tech/invoices-authorisation-risk.md"
}

test_define_prompt_includes_all_inputs() {
    write_complete_response
    mkdir -p "${TEST_DIR}/specs/architecture" "${TEST_DIR}/specs/threat-model" "${TEST_DIR}/specs/compliance"
    echo "# Design: invoices marker-design" > "${TEST_DIR}/specs/design/invoices.md"
    echo "# Arch marker-arch-a" > "${TEST_DIR}/specs/architecture/system.md"
    echo "# Arch marker-arch-b" > "${TEST_DIR}/specs/architecture/identity.md"
    echo "# Threats marker-threat" > "${TEST_DIR}/specs/threat-model/stride.md"
    echo "# SOC2 marker-compliance" > "${TEST_DIR}/specs/compliance/soc2.md"
    (cd "$TEST_DIR" && git add -A && git -c user.email=t@t -c user.name=t commit -q -m inputs)

    speed_fake define authorisation-risk invoices >/dev/null || return 1
    local prompt
    prompt=$(cat "${TEST_DIR}/fake/prompts/1.txt")
    assert_contains "$prompt" "As an account owner I can export" &&
    assert_contains "$prompt" "marker-design" &&
    assert_contains "$prompt" "marker-arch-a" &&
    assert_contains "$prompt" "marker-arch-b" &&
    assert_contains "$prompt" "marker-threat" &&
    assert_contains "$prompt" "marker-compliance" &&
    assert_contains "$prompt" "src/api/auth.ts" &&
    assert_contains "$prompt" "### Test files (1)" &&
    assert_contains "$prompt" "tests/auth.test.ts" &&
    assert_contains "$prompt" "../product/invoices.md"
}

test_define_feature_scoped_input_wins() {
    write_complete_response
    mkdir -p "${TEST_DIR}/specs/threat-model"
    echo "# marker-scoped" > "${TEST_DIR}/specs/threat-model/invoices.md"
    echo "# marker-other" > "${TEST_DIR}/specs/threat-model/payments.md"
    speed_fake define authorisation-risk invoices >/dev/null || return 1
    local prompt
    prompt=$(cat "${TEST_DIR}/fake/prompts/1.txt")
    assert_contains "$prompt" "marker-scoped" && assert_not_contains "$prompt" "marker-other"
}

test_define_flags_override_discovery() {
    write_complete_response
    mkdir -p "${TEST_DIR}/specs/compliance" "${TEST_DIR}/elsewhere"
    echo "# marker-default" > "${TEST_DIR}/specs/compliance/soc2.md"
    echo "# marker-flagged" > "${TEST_DIR}/elsewhere/hipaa.md"
    speed_fake define authorisation-risk invoices --compliance elsewhere/hipaa.md >/dev/null || return 1
    local prompt
    prompt=$(cat "${TEST_DIR}/fake/prompts/1.txt")
    assert_contains "$prompt" "marker-flagged" && assert_not_contains "$prompt" "marker-default"
}

test_define_missing_inputs_marked_not_provided() {
    write_complete_response
    local out
    out=$(speed_fake define authorisation-risk invoices) || return 1
    assert_contains "$out" "not provided" &&
    assert_contains "$(cat "${TEST_DIR}/fake/prompts/1.txt")" "## Threat Model Specs"$'\n\n'"Not provided."
}

test_define_retries_incomplete_draft() {
    printf '# Authorisation Risk: Invoices\n\n## Summary\nOnly one section.\n' > "${TEST_DIR}/fake/responses/1.md"
    write_complete_response "${TEST_DIR}/fake/responses/2.md"
    local out
    out=$(speed_fake define authorisation-risk invoices) || return 1
    [[ -f "${TEST_DIR}/fake/prompts/2.txt" ]] || { echo "    no retry happened" >&2; return 1; }
    assert_contains "$(cat "${TEST_DIR}/fake/prompts/2.txt")" "missing these sections" &&
    assert_contains "$(cat "${TEST_DIR}/specs/tech/invoices-authorisation-risk.md")" "## Source Traceability"
}

test_define_strips_preamble_and_adds_see_link() {
    {
        echo "Here is the spec:"
        echo '```markdown'
        write_complete_response /dev/stdout | grep -v '^> '
        echo '```'
    } > "${TEST_DIR}/fake/responses/default.md"
    speed_fake define authorisation-risk invoices >/dev/null || return 1
    local spec
    spec=$(cat "${TEST_DIR}/specs/tech/invoices-authorisation-risk.md")
    [[ "$(echo "$spec" | head -1)" == "# Authorisation Risk: Invoices" ]] || { echo "    preamble kept: $(echo "$spec" | head -1)" >&2; return 1; }
    assert_not_contains "$spec" '```' &&
    assert_contains "$spec" "> See [product spec](../product/invoices.md)"
}

test_define_force_overwrites() {
    write_complete_response
    echo "# old" > "${TEST_DIR}/specs/tech/invoices-authorisation-risk.md"
    speed_fake define authorisation-risk invoices --force >/dev/null || return 1
    assert_contains "$(cat "${TEST_DIR}/specs/tech/invoices-authorisation-risk.md")" "## Permission Matrix"
}

# ── Tests: audit of the generated spec ───────────────────────────

test_audit_detects_authorisation_risk() {
    write_complete_response "${TEST_DIR}/specs/tech/invoices-authorisation-risk.md"
    echo '{"status":"pass","issues":[],"sizing":null}' > "${TEST_DIR}/fake/responses/default.md"
    local rc=0 out
    out=$(speed_fake audit specs/tech/invoices-authorisation-risk.md) || rc=$?
    assert_exit_code 0 "$rc" "$out" &&
    assert_contains "$out" "Spec type: authorisation-risk" &&
    assert_contains "$out" "authorisation-risk.md"
}

test_audit_sends_prd_overview_and_codebase() {
    write_complete_response "${TEST_DIR}/specs/tech/invoices-authorisation-risk.md"
    echo '{"status":"pass","issues":[],"sizing":null}' > "${TEST_DIR}/fake/responses/default.md"
    speed_fake audit specs/tech/invoices-authorisation-risk.md >/dev/null || return 1
    local prompt
    prompt=$(cat "${TEST_DIR}/fake/prompts/1.txt")
    assert_contains "$prompt" "As an account owner I can export" &&
    assert_contains "$prompt" "Nobody sees another tenant" &&
    assert_contains "$prompt" "Codebase Inventory" &&
    assert_contains "$prompt" "src/api/auth.ts" &&
    assert_contains "$prompt" "## Permission Matrix"
}

test_audit_detects_by_header() {
    write_complete_response "${TEST_DIR}/specs/tech/invoices-access.md"
    echo '{"status":"pass","issues":[],"sizing":null}' > "${TEST_DIR}/fake/responses/default.md"
    local out
    out=$(speed_fake audit specs/tech/invoices-access.md) || return 1
    assert_contains "$out" "Spec type: authorisation-risk"
}

test_audit_plain_rfc_unchanged() {
    echo "# RFC: invoices" > "${TEST_DIR}/specs/tech/invoices.md"
    echo '{"status":"pass","issues":[],"sizing":null}' > "${TEST_DIR}/fake/responses/default.md"
    local out
    out=$(speed_fake audit specs/tech/invoices.md) || return 1
    assert_contains "$out" "Spec type: rfc" &&
    assert_not_contains "$(cat "${TEST_DIR}/fake/prompts/1.txt")" "### Source files ("
}

test_help_lists_define() {
    local out
    out=$(speed_fake help) || true
    assert_contains "$out" "define" && assert_contains "$out" "--threat-model"
}

# A Windows checkout gives the template CRLF endings; headings must still match.
test_crlf_template_no_retry() {
    write_complete_response
    sed -i 's/$//' "${TEST_DIR}/speed/templates/authorisation-risk.md"
    speed_fake define authorisation-risk invoices >/dev/null || return 1
    [[ ! -f "${TEST_DIR}/fake/prompts/2.txt" ]] || { echo "    retried on CRLF template" >&2; return 1; }
}

# ── Main ─────────────────────────────────────────────────────────

echo "Running speed define tests..."
echo ""

run_test test_define_no_subject
run_test test_define_unknown_subject
run_test test_define_missing_feature
run_test test_define_missing_product_spec
run_test test_define_missing_flagged_input
run_test test_define_refuses_overwrite
run_test test_define_writes_spec
run_test test_define_prompt_includes_all_inputs
run_test test_define_feature_scoped_input_wins
run_test test_define_flags_override_discovery
run_test test_define_missing_inputs_marked_not_provided
run_test test_define_retries_incomplete_draft
run_test test_define_strips_preamble_and_adds_see_link
run_test test_define_force_overwrites
run_test test_audit_detects_authorisation_risk
run_test test_audit_sends_prd_overview_and_codebase
run_test test_audit_detects_by_header
run_test test_audit_plain_rfc_unchanged
run_test test_help_lists_define
run_test test_crlf_template_no_retry

echo ""
echo "────────────────────────────────────────────────────────────"
echo "Results: ${PASS} passed, ${FAIL} failed"
echo ""

[[ $FAIL -eq 0 ]]
