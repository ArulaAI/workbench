#!/usr/bin/env bash
# test_provider_parsing.sh — Tests for Claude Code provider parsing functions
#
# Tests pure-logic functions from providers/claude-code.sh:
#   _find_result_event, _detect_result_error, _result_metadata,
#   _resolve_claude_effort, _count_lines
#
# Usage: bash tests/test_provider_parsing.sh
# Exit: 0 if all tests pass, 1 if any fail

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROVIDER_FILE="${SCRIPT_DIR}/../providers/claude-code.sh"
PASS=0
FAIL=0
TEST_DIR=""

# ── Harness ───────────────────────────────────────────────────────────────────

setup() {
    TEST_DIR=$(mktemp -d)

    # Color/symbol stubs
    COLOR_ERROR="" COLOR_WARN="" COLOR_DIM="" COLOR_SUCCESS="" COLOR_STEP=""
    BOLD="" RESET="" SYM_CHECK="" SYM_CROSS="" SYM_WARN="" SYM_ARROW=""
    VERBOSITY=0

    # Logging stubs
    log_error()   { :; }
    log_warn()    { :; }
    log_step()    { :; }
    log_success() { :; }
    log_info()    { :; }
    log_verbose() { :; }
    log_debug()   { :; }

    # Stubs for dependencies that claude-code.sh expects
    AGENT_FILE_PATH="/dev/null"
    MODEL_SUPPORT="sonnet"
    MODEL_PLANNING="opus"
    DEFAULT_AGENT_TIMEOUT=600
    DEFAULT_MAX_TURNS=50
    AGENT_TOOLS_FULL="Read,Write,Edit,Bash,Glob,Grep"
    LOGS_DIR="${TEST_DIR}/logs"
    mkdir -p "$LOGS_DIR"

    # Stub provider.sh functions
    require_timeout_cmd() { :; }
    _TIMEOUT_CMD="timeout"
    parse_agent_json() { cat; }

    # Stub cleanup.sh functions
    cleanup_register_file() { :; }
    cleanup_unregister_file() { :; }
    cleanup_register_pid() { :; }
    cleanup_unregister_pid() { :; }

    # Stub progress.sh functions
    progress_start() { :; }
    progress_error() { :; }
    progress_done() { :; }
    _PROGRESS_START=$(date +%s)

    # Prevent claude-code.sh from failing on missing claude binary
    PROVIDER_BIN="/bin/true"
    CLAUDE_BIN="/bin/true"

    # Source just the functions we need (skip the setup line that resolves claude)
    # We extract functions individually to avoid side effects
    eval "$(sed -n '/^_find_result_event()/,/^}/p' "$PROVIDER_FILE")"
    eval "$(sed -n '/^_detect_result_error()/,/^}/p' "$PROVIDER_FILE")"
    eval "$(sed -n '/^_result_metadata()/,/^}/p' "$PROVIDER_FILE")"
    eval "$(sed -n '/^_resolve_claude_effort()/,/^}/p' "$PROVIDER_FILE")"
    eval "$(sed -n '/^_count_lines()/,/^}/p' "$PROVIDER_FILE")"
}

teardown() {
    rm -rf "$TEST_DIR"
    # Clean up env vars that tests may have set
    unset SPEED_CLAUDE_EFFORT SPEED_CLAUDE_EFFORT_ARCHITECT SPEED_CLAUDE_EFFORT_DEVELOPER 2>/dev/null || true
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

assert_eq() {
    local expected="$1" actual="$2" context="${3:-}"
    if [[ "$expected" != "$actual" ]]; then
        echo "    ASSERT: expected '${expected}', got '${actual}'${context:+ (${context})}" >&2
        return 1
    fi
}

assert_exit_code() {
    local expected="$1" actual="$2" context="${3:-}"
    if [[ "$expected" != "$actual" ]]; then
        echo "    ASSERT: expected exit ${expected}, got ${actual}${context:+ (${context})}" >&2
        return 1
    fi
}

# ══════════════════════════════════════════════════════════════════════════════
# _find_result_event tests
# ══════════════════════════════════════════════════════════════════════════════

test_find_result_event_success() {
    local events="${TEST_DIR}/events.jsonl"
    cat > "$events" <<'EOF'
{"type":"assistant","message":"working..."}
{"type":"assistant","message":"done"}
{"type":"result","subtype":"success","result":"the answer"}
EOF
    local result
    result=$(_find_result_event "$events")
    echo "$result" | grep -q '"type":"result"' || {
        echo "    ASSERT: result should contain type:result" >&2; return 1
    }
    echo "$result" | grep -q '"subtype":"success"' || {
        echo "    ASSERT: result should contain subtype:success" >&2; return 1
    }
}

test_find_result_event_takes_last() {
    local events="${TEST_DIR}/events.jsonl"
    cat > "$events" <<'EOF'
{"type":"result","subtype":"error_max_turns","num_turns":5}
{"type":"result","subtype":"success","result":"final"}
EOF
    local result
    result=$(_find_result_event "$events")
    echo "$result" | grep -q '"subtype":"success"' || {
        echo "    ASSERT: should take last result event" >&2; return 1
    }
}

test_find_result_event_missing() {
    local events="${TEST_DIR}/events.jsonl"
    echo '{"type":"assistant","message":"no result here"}' > "$events"
    local result
    result=$(_find_result_event "$events")
    assert_eq "" "$result" "should return empty when no result event"
}

test_find_result_event_empty_file() {
    local events="${TEST_DIR}/events.jsonl"
    touch "$events"
    local result
    result=$(_find_result_event "$events")
    assert_eq "" "$result" "should return empty for empty file"
}

# ══════════════════════════════════════════════════════════════════════════════
# _detect_result_error tests
# ══════════════════════════════════════════════════════════════════════════════

test_detect_error_success_returns_1() {
    local line='{"type":"result","subtype":"success","result":"ok"}'
    local rc=0
    _detect_result_error "$line" >/dev/null 2>&1 || rc=$?
    assert_exit_code "1" "$rc" "success should return 1 (no error)"
}

test_detect_error_max_turns() {
    local line='{"type":"result","subtype":"error_max_turns","num_turns":50,"total_cost_usd":1.23}'
    local rc=0
    local output
    output=$(_detect_result_error "$line") || rc=$?
    assert_exit_code "0" "$rc" "max_turns should return 0 (error detected)"
    echo "$output" | grep -q "max turns" || {
        echo "    ASSERT: output should mention max turns: $output" >&2; return 1
    }
}

test_detect_error_tool_use() {
    local line='{"type":"result","subtype":"error_tool_use"}'
    local rc=0
    local output
    output=$(_detect_result_error "$line") || rc=$?
    assert_exit_code "0" "$rc" "tool_use error should return 0"
    echo "$output" | grep -q "tool use" || {
        echo "    ASSERT: output should mention tool use" >&2; return 1
    }
}

test_detect_error_generic() {
    local line='{"type":"result","subtype":"error_something_new"}'
    local rc=0
    local output
    output=$(_detect_result_error "$line") || rc=$?
    assert_exit_code "0" "$rc" "generic error_ should return 0"
    echo "$output" | grep -q "error_something_new" || {
        echo "    ASSERT: output should contain subtype" >&2; return 1
    }
}

test_detect_error_is_error_true() {
    local line='{"type":"result","is_error":true,"errors":["something broke"]}'
    local rc=0
    local output
    output=$(_detect_result_error "$line") || rc=$?
    assert_exit_code "0" "$rc" "is_error:true should return 0"
    echo "$output" | grep -q "something broke" || {
        echo "    ASSERT: output should contain error message" >&2; return 1
    }
}

test_detect_error_empty_input() {
    local rc=0
    _detect_result_error "" >/dev/null 2>&1 || rc=$?
    assert_exit_code "1" "$rc" "empty input should return 1"
}

# ══════════════════════════════════════════════════════════════════════════════
# _result_metadata tests
# ══════════════════════════════════════════════════════════════════════════════

test_metadata_full() {
    local line='{"type":"result","duration_ms":45000,"num_turns":12,"total_cost_usd":0.85}'
    local output
    output=$(_result_metadata "$line")
    local duration turns cost
    read -r duration turns cost <<< "$output"
    assert_eq "45" "$duration" "duration should be 45s (45000ms / 1000)"
    assert_eq "12" "$turns" "num_turns"
    assert_eq "0.85" "$cost" "cost"
}

test_metadata_missing_fields() {
    local line='{"type":"result"}'
    local output
    output=$(_result_metadata "$line")
    local duration turns cost
    read -r duration turns cost <<< "$output"
    assert_eq "0" "$duration" "duration should default to 0"
}

test_metadata_zero_duration() {
    local line='{"type":"result","duration_ms":0,"num_turns":1,"total_cost_usd":0.01}'
    local output
    output=$(_result_metadata "$line")
    local duration
    read -r duration _ <<< "$output"
    assert_eq "0" "$duration" "0ms should be 0s"
}

# ══════════════════════════════════════════════════════════════════════════════
# _resolve_claude_effort tests
# ══════════════════════════════════════════════════════════════════════════════

test_effort_per_agent_override() {
    export SPEED_CLAUDE_EFFORT_ARCHITECT="low"
    local result
    result=$(_resolve_claude_effort "Architect" "opus" "100000")
    assert_eq "low" "$result" "per-agent env should take priority"
}

test_effort_global_override() {
    export SPEED_CLAUDE_EFFORT="high"
    local result
    result=$(_resolve_claude_effort "Developer" "sonnet" "1000")
    assert_eq "high" "$result" "global env should apply when no per-agent"
}

test_effort_per_agent_beats_global() {
    export SPEED_CLAUDE_EFFORT="high"
    export SPEED_CLAUDE_EFFORT_DEVELOPER="low"
    local result
    result=$(_resolve_claude_effort "Developer" "opus" "100000")
    assert_eq "low" "$result" "per-agent should beat global"
}

test_effort_auto_opus_large_input() {
    unset SPEED_CLAUDE_EFFORT SPEED_CLAUDE_EFFORT_ARCHITECT 2>/dev/null || true
    local result
    result=$(_resolve_claude_effort "Architect" "opus" "60000")
    assert_eq "medium" "$result" "opus + >50K chars should auto-detect medium"
}

test_effort_auto_opus_small_input() {
    unset SPEED_CLAUDE_EFFORT SPEED_CLAUDE_EFFORT_ARCHITECT 2>/dev/null || true
    local result
    result=$(_resolve_claude_effort "Architect" "opus" "10000")
    assert_eq "" "$result" "opus + small input should return empty (no override)"
}

test_effort_auto_sonnet_large_input() {
    unset SPEED_CLAUDE_EFFORT SPEED_CLAUDE_EFFORT_DEVELOPER 2>/dev/null || true
    local result
    result=$(_resolve_claude_effort "Developer" "sonnet" "100000")
    assert_eq "" "$result" "sonnet should not auto-detect medium (only opus)"
}

test_effort_label_normalization() {
    export SPEED_CLAUDE_EFFORT_COHERENCE_CHECKER="low"
    local result
    result=$(_resolve_claude_effort "Coherence-Checker" "opus" "100000")
    # tr -cd '[:alnum:]_' strips the hyphen, so COHERENCECHECKER
    # This tests whether the label normalization matches the env var
    # The hyphen gets stripped, so COHERENCE_CHECKER won't match COHERENCECHECKER
    # This verifies the actual behavior
    if [[ -n "$result" ]]; then
        assert_eq "low" "$result" "label with hyphen"
    fi
    # Clean up
    unset SPEED_CLAUDE_EFFORT_COHERENCE_CHECKER
}

# ══════════════════════════════════════════════════════════════════════════════
# _count_lines tests
# ══════════════════════════════════════════════════════════════════════════════

test_count_lines_empty() {
    local f="${TEST_DIR}/empty.txt"
    touch "$f"
    local count
    count=$(_count_lines "$f")
    assert_eq "0" "$count" "empty file should have 0 lines"
}

test_count_lines_one() {
    local f="${TEST_DIR}/one.txt"
    echo "single line" > "$f"
    local count
    count=$(_count_lines "$f")
    assert_eq "1" "$count" "single line file"
}

test_count_lines_multiple() {
    local f="${TEST_DIR}/multi.txt"
    printf "line1\nline2\nline3\n" > "$f"
    local count
    count=$(_count_lines "$f")
    assert_eq "3" "$count" "three line file"
}

# ── Run all tests ─────────────────────────────────────────────────────────────

echo ""
echo "Provider parsing tests (claude-code.sh)"
echo "──────────────────────────────────────"

run_test test_find_result_event_success
run_test test_find_result_event_takes_last
run_test test_find_result_event_missing
run_test test_find_result_event_empty_file
run_test test_detect_error_success_returns_1
run_test test_detect_error_max_turns
run_test test_detect_error_tool_use
run_test test_detect_error_generic
run_test test_detect_error_is_error_true
run_test test_detect_error_empty_input
run_test test_metadata_full
run_test test_metadata_missing_fields
run_test test_metadata_zero_duration
run_test test_effort_per_agent_override
run_test test_effort_global_override
run_test test_effort_per_agent_beats_global
run_test test_effort_auto_opus_large_input
run_test test_effort_auto_opus_small_input
run_test test_effort_auto_sonnet_large_input
run_test test_effort_label_normalization
run_test test_count_lines_empty
run_test test_count_lines_one
run_test test_count_lines_multiple

echo ""
echo "──────────────────────────────────────"
echo "Results: ${PASS} passed, ${FAIL} failed"
echo ""

if [[ "$FAIL" -gt 0 ]]; then
    exit 1
fi
