#!/usr/bin/env bash
# test_diagnose_cmd.sh — Tests for cmd_diagnose() in lib/cmd/diagnose.sh
#
# Tests argument parsing, error handling, the "no classes file" invariant,
# and the exit-0-always contract. Mocks task_get/git helpers and the
# python engine so this file tests bash orchestration only — the rule
# engine itself is covered by tests/test_diagnose_engine.py.
#
# Usage: bash tests/test_diagnose_cmd.sh
# Exit: 0 if all tests pass, 1 if any fail

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="${SCRIPT_DIR}/../lib"
PASS=0
FAIL=0
TEST_DIR=""

# ── Harness ──────────────────────────────────────────────────────

setup() {
    TEST_DIR=$(mktemp -d)
    export SPEED_PROJECT_ROOT="$TEST_DIR"
    export VERBOSITY=0
    export GLOBAL_FEATURE="test-feature"

    COLOR_ERROR="" COLOR_WARN="" COLOR_DIM="" COLOR_SUCCESS=""
    COLOR_STEP="" COLOR_HEADER="" COLOR_INFO="" COLOR_ACCENT=""
    BOLD="" RESET="" SYM_CHECK="" SYM_CROSS="" SYM_WARN=""
    SYM_ARROW="" SYM_PENDING="" SYM_RUNNING=""

    # shellcheck disable=SC1090
    source "${LIB_DIR}/config.sh"
    # shellcheck disable=SC1090
    source "${LIB_DIR}/log.sh"

    # Stub feature resolution — always succeeds, points at the test feature dir
    feature_get_active() { echo "test-feature"; }
    _require_feature() {
        FEATURE_NAME="test-feature"
        FEATURE_DIR="${STATE_DIR}/features/test-feature"
        mkdir -p "$FEATURE_DIR"
    }

    _ensure_jq() { :; }

    # Stub task_get — returns a canned task record. Tests override as needed.
    task_get() {
        echo '{"id":"1","branch":"round-0","agent_model":"sonnet","files_touched":["src/payments/service.ts"],"description":"should never be read","acceptance_criteria":"should never be read","review_feedback":"should never be read"}'
    }

    # Stub git helpers
    git_main_branch() { echo "main"; }
    git_branch_exists() { return 0; }
    git_diff_branch() { echo "diff --git a/src/payments/service.ts b/src/payments/service.ts"; }

    # Stub the python engine call so these tests exercise bash flow only.
    _engine_output='{"classes":[{"id":"F2","title":"Cardholder data leakage","signals":[{"observed":"1 file(s) with an observability sink call","where":["src/payments/service.ts"]}]},{"id":"F5","title":"Sycophantic self-approval","signals":[]}]}'
    python3() {
        if [[ "$1" == *diagnose_engine.py ]]; then
            echo "$_engine_output"
            return 0
        fi
        command python3 "$@"
    }

    # shellcheck disable=SC1090
    source "${LIB_DIR}/cmd/diagnose.sh"

    mkdir -p "${TEST_DIR}/.speed"
    echo "classes: []" > "${TEST_DIR}/.speed/classes.yaml"
}

teardown() {
    rm -rf "$TEST_DIR"
    unset SPEED_PROJECT_ROOT
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
    local expected="$1" actual="$2" label="${3:-value}"
    if [[ "$expected" != "$actual" ]]; then
        echo "    ASSERT: expected ${label}='${expected}', got '${actual}'" >&2
        return 1
    fi
}

assert_output_contains() {
    local output="$1" pattern="$2"
    if ! echo "$output" | grep -q "$pattern"; then
        echo "    ASSERT: output does not contain '${pattern}'" >&2
        echo "    OUTPUT: ${output:0:400}" >&2
        return 1
    fi
}

assert_output_not_contains() {
    local output="$1" pattern="$2"
    if echo "$output" | grep -q "$pattern"; then
        echo "    ASSERT: output unexpectedly contains '${pattern}'" >&2
        return 1
    fi
}

# ── Tests ────────────────────────────────────────────────────────

test_cmd_diagnose_function_exists() {
    declare -f cmd_diagnose > /dev/null 2>&1
}

test_no_task_flag_exits_config_error() {
    local rc=0
    local output
    output=$(cmd_diagnose 2>&1) || rc=$?
    assert_eq "3" "$rc" "exit code" &&
    assert_output_contains "$output" "Required: --task"
}

test_unknown_flag_exits_config_error() {
    local rc=0
    output=$(cmd_diagnose --task 1 --bogus 2>&1) || rc=$?
    assert_eq "3" "$rc" "exit code" &&
    assert_output_contains "$output" "Unknown option"
}

test_missing_classes_file_exits_config_error() {
    rm -f "${TEST_DIR}/.speed/classes.yaml"
    local rc=0
    local output
    output=$(cmd_diagnose --task 1 2>&1) || rc=$?
    assert_eq "3" "$rc" "exit code" &&
    assert_output_contains "$output" "No Diagnose class rules configured"
}

test_missing_classes_file_message_names_the_toml_key() {
    rm -f "${TEST_DIR}/.speed/classes.yaml"
    local output
    output=$(cmd_diagnose --task 1 2>&1) || true
    assert_output_contains "$output" "classes_file"
}

test_task_with_no_branch_exits_config_error() {
    task_get() { echo '{"id":"1","agent_model":"sonnet","files_touched":[]}'; }
    local rc=0
    local output
    output=$(cmd_diagnose --task 1 2>&1) || rc=$?
    assert_eq "3" "$rc" "exit code" &&
    assert_output_contains "$output" "no branch recorded"
}

test_task_not_found_exits_config_error() {
    task_get() { log_error "Task 99 not found"; return 1; }
    local rc=0
    local output
    output=$(cmd_diagnose --task 99 2>&1) || rc=$?
    assert_eq "3" "$rc" "exit code" &&
    assert_output_contains "$output" "not found"
}

test_branch_not_found_exits_config_error() {
    git_branch_exists() { return 1; }
    local rc=0
    local output
    output=$(cmd_diagnose --task 1 2>&1) || rc=$?
    assert_eq "3" "$rc" "exit code" &&
    assert_output_contains "$output" "not found"
}

test_successful_run_exits_zero() {
    # cmd_diagnose calls `exit 0` directly on success. Command substitution
    # is not just for capturing output here — it's what contains that exit
    # to a subshell instead of killing this whole test script.
    local rc=0
    local _out
    _out=$(cmd_diagnose --task 1 2>&1) || rc=$?
    assert_eq "0" "$rc" "exit code on a successful diagnosis"
}

test_successful_run_exits_zero_even_with_signals_present() {
    # F2 in the stubbed engine output has a real signal — must still be exit 0.
    # A diagnosis is not a pass/fail check.
    local rc=0
    local _out
    _out=$(cmd_diagnose --task 1 2>&1) || rc=$?
    assert_eq "0" "$rc" "exit code with signals present"
}

test_risk_surface_file_is_written() {
    local _out
    _out=$(cmd_diagnose --task 1 2>&1) || true
    [[ -f "${TEST_DIR}/.speed/features/test-feature/risk-surface.yaml" ]]
}

test_risk_surface_names_task_and_branch() {
    local _out
    _out=$(cmd_diagnose --task 1 2>&1) || true
    local content
    content=$(cat "${TEST_DIR}/.speed/features/test-feature/risk-surface.yaml")
    assert_output_contains "$content" 'task: "1"' &&
    assert_output_contains "$content" 'branch: "round-0"'
}

test_every_class_gets_undecided_plausible() {
    local _out
    _out=$(cmd_diagnose --task 1 2>&1) || true
    local content
    content=$(cat "${TEST_DIR}/.speed/features/test-feature/risk-surface.yaml")
    local undecided_count
    undecided_count=$(grep -c "plausible: undecided" <<< "$content")
    assert_eq "2" "$undecided_count" "plausible: undecided count (one per declared class)"
}

test_no_rule_ever_fills_plausible_true_or_false() {
    local _out
    _out=$(cmd_diagnose --task 1 2>&1) || true
    local content
    content=$(cat "${TEST_DIR}/.speed/features/test-feature/risk-surface.yaml")
    assert_output_not_contains "$content" "plausible: true" &&
    assert_output_not_contains "$content" "plausible: false"
}

test_class_with_no_signals_renders_empty_array() {
    local _out
    _out=$(cmd_diagnose --task 1 2>&1) || true
    local content
    content=$(cat "${TEST_DIR}/.speed/features/test-feature/risk-surface.yaml")
    assert_output_contains "$content" "signals: \[\]"
}

test_class_with_signal_renders_observed_and_where() {
    local _out
    _out=$(cmd_diagnose --task 1 2>&1) || true
    local content
    content=$(cat "${TEST_DIR}/.speed/features/test-feature/risk-surface.yaml")
    assert_output_contains "$content" "observed:" &&
    assert_output_contains "$content" "src/payments/service.ts"
}

test_console_output_never_reads_description_or_review_fields() {
    # task_get's stub record deliberately includes description/review_feedback
    # fields containing the literal string "should never be read" — diagnose
    # must never surface them anywhere in its output.
    local output
    output=$(cmd_diagnose --task 1 2>&1) || true
    assert_output_not_contains "$output" "should never be read"
}

test_risk_surface_never_contains_description_or_review_fields() {
    local _out
    _out=$(cmd_diagnose --task 1 2>&1) || true
    local content
    content=$(cat "${TEST_DIR}/.speed/features/test-feature/risk-surface.yaml")
    assert_output_not_contains "$content" "should never be read"
}

test_engine_failure_preserves_stderr_message() {
    python3() {
        if [[ "$1" == *diagnose_engine.py ]]; then
            echo "Error: could not parse classes file: mapping values are not allowed here" >&2
            return 3
        fi
        command python3 "$@"
    }
    local rc=0
    local output
    output=$(cmd_diagnose --task 1 2>&1) || rc=$?
    assert_eq "3" "$rc" "exit code" &&
    assert_output_contains "$output" "mapping values are not allowed here"
}

test_title_with_embedded_quote_produces_valid_yaml() {
    _engine_output='{"classes":[{"id":"F1","title":"Uses \"any\" type without justification","signals":[{"observed":"a \"quoted\" phrase and a \\backslash","where":["src/x.ts"]}]}]}'
    local _out
    _out=$(cmd_diagnose --task 1 2>&1) || true
    local rs_file="${TEST_DIR}/.speed/features/test-feature/risk-surface.yaml"
    # The real defect was invalid YAML (unbalanced quotes). Parse it back and
    # check round-trip fidelity, rather than grep-matching a string full of
    # its own quotes and backslashes.
    python3 - "$rs_file" <<'PYEOF'
import sys, yaml
data = yaml.safe_load(open(sys.argv[1]))
cls = data["classes"][0]
assert cls["failureMode"] == 'Uses "any" type without justification', cls["failureMode"]
assert cls["signals"][0]["observed"] == 'a "quoted" phrase and a \\backslash', cls["signals"][0]["observed"]
PYEOF
}

test_speed_script_contains_diagnose_case() {
    local speed_script="${SCRIPT_DIR}/../speed"
    grep -q "diagnose)" "$speed_script"
}

test_speed_script_dispatches_diagnose_before_security() {
    # Not load-bearing, just confirms the case was added, not just left dangling.
    local speed_script="${SCRIPT_DIR}/../speed"
    grep -q "cmd_diagnose" "$speed_script"
}

# ── Run all tests ──────────────────────────────────────────────

echo ""
echo "cmd_diagnose tests"
echo "──────────────────────────────────────"

run_test test_cmd_diagnose_function_exists
run_test test_no_task_flag_exits_config_error
run_test test_unknown_flag_exits_config_error
run_test test_missing_classes_file_exits_config_error
run_test test_missing_classes_file_message_names_the_toml_key
run_test test_task_with_no_branch_exits_config_error
run_test test_task_not_found_exits_config_error
run_test test_branch_not_found_exits_config_error
run_test test_successful_run_exits_zero
run_test test_successful_run_exits_zero_even_with_signals_present
run_test test_risk_surface_file_is_written
run_test test_risk_surface_names_task_and_branch
run_test test_every_class_gets_undecided_plausible
run_test test_no_rule_ever_fills_plausible_true_or_false
run_test test_class_with_no_signals_renders_empty_array
run_test test_class_with_signal_renders_observed_and_where
run_test test_console_output_never_reads_description_or_review_fields
run_test test_risk_surface_never_contains_description_or_review_fields
run_test test_engine_failure_preserves_stderr_message
run_test test_title_with_embedded_quote_produces_valid_yaml
run_test test_speed_script_contains_diagnose_case
run_test test_speed_script_dispatches_diagnose_before_security

echo ""
echo "──────────────────────────────────────"
echo "Results: ${PASS} passed, ${FAIL} failed"
echo ""

if [[ "$FAIL" -gt 0 ]]; then
    exit 1
fi
