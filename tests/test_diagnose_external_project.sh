#!/usr/bin/env bash
# test_diagnose_external_project.sh — Proves `speed diagnose` resolves
# SPEED's own installation independently of the caller's cwd, while
# project-owned config (speed.toml, .speed/classes.yaml, task/feature
# state) is read from wherever the caller actually is.
#
# This is exactly the property an external project invoking a globally
# installed `speed` binary (e.g. `cd /path/to/some-fixture && speed
# diagnose ...`) depends on: SPEED_DIR must anchor to the installation,
# PROJECT_ROOT must follow the caller, and the two must never cross.
#
# Unlike test_diagnose_cmd.sh (which pins PROJECT_ROOT via
# SPEED_PROJECT_ROOT), this file leaves that variable unset and instead
# `cd`s a subshell into a project directory that lives outside the SPEED
# repo entirely, so PROJECT_ROOT is resolved the same way a real external
# invocation resolves it: via $(pwd).
#
# Usage: bash tests/test_diagnose_external_project.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPEED_HOME="$(cd "${SCRIPT_DIR}/.." && pwd)"
LIB_DIR="${SPEED_HOME}/lib"
PASS=0
FAIL=0

# ── Harness ──────────────────────────────────────────────────────

make_external_project() {
    local dir
    dir=$(mktemp -d)
    mkdir -p "${dir}/.speed/features/demo/tasks"
    cat > "${dir}/.speed/classes.yaml" <<'YAML'
classes:
  - id: F1
    title: Test class
    rules:
      - look: added-lines
        match: "TODO"
        say: "{n} TODO(s) added"
YAML
    cat > "${dir}/speed.toml" <<'TOML'
[diagnose]
classes_file = ".speed/classes.yaml"
TOML
    cat > "${dir}/.speed/features/demo/tasks/1.json" <<'JSON'
{"id":"1","branch":"feature","agent_model":"sonnet","files_touched":["a.py"],
 "description":"should never be read","acceptance_criteria":"should never be read",
 "review_feedback":"should never be read"}
JSON
    echo "$dir"
}

run_test() {
    local test_name="$1"
    local rc=0
    "$test_name" || rc=$?
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

# ── Tests ──────────────────────────────────────────────────────

test_project_root_follows_external_cwd_not_speed_dir() {
    local ext_dir out
    ext_dir=$(make_external_project)
    out=$(
        cd "$ext_dir" && unset SPEED_PROJECT_ROOT
        # shellcheck disable=SC1090
        source "${LIB_DIR}/config.sh"
        echo "PROJECT_ROOT=${PROJECT_ROOT}"
        echo "SPEED_DIR=${SPEED_DIR}"
    )
    rm -rf "$ext_dir"
    assert_eq "PROJECT_ROOT=${ext_dir}" "$(echo "$out" | grep PROJECT_ROOT=)" "PROJECT_ROOT line" || return 1
    assert_eq "SPEED_DIR=${SPEED_HOME}" "$(echo "$out" | grep SPEED_DIR=)" "SPEED_DIR line"
}

test_cmd_diagnose_succeeds_from_an_external_project_directory() {
    local ext_dir rc
    ext_dir=$(make_external_project)
    (
        cd "$ext_dir" || exit 1
        unset SPEED_PROJECT_ROOT
        export VERBOSITY=0 GLOBAL_FEATURE="demo"
        COLOR_ERROR="" COLOR_WARN="" COLOR_DIM="" COLOR_SUCCESS=""
        COLOR_STEP="" COLOR_HEADER="" COLOR_INFO="" COLOR_ACCENT=""
        BOLD="" RESET="" SYM_CHECK="" SYM_CROSS="" SYM_WARN=""
        SYM_ARROW="" SYM_PENDING="" SYM_RUNNING=""

        # shellcheck disable=SC1090
        source "${LIB_DIR}/config.sh"
        # shellcheck disable=SC1090
        source "${LIB_DIR}/log.sh"
        # shellcheck disable=SC1090
        source "${LIB_DIR}/features.sh"
        # shellcheck disable=SC1090
        source "${LIB_DIR}/tasks.sh"
        # shellcheck disable=SC1090
        source "${LIB_DIR}/cmd/diagnose.sh"

        feature_get_active() { echo "demo"; }
        git_main_branch() { echo "main"; }
        git_branch_exists() { return 0; }
        git_diff_branch() { echo "diff --git a/a.py b/a.py"; }

        cmd_diagnose --task 1 >/dev/null 2>&1
        exit $?
    )
    rc=$?
    local surface_written=1
    [[ -f "${ext_dir}/.speed/features/demo/risk-surface.yaml" ]] && surface_written=0
    rm -rf "$ext_dir"
    assert_eq 0 "$rc" "cmd_diagnose exit code" || return 1
    assert_eq 0 "$surface_written" "risk-surface.yaml written under the external project's own .speed/, not SPEED's"
}

test_speed_dir_own_resources_unaffected_by_external_cwd() {
    local ext_dir out
    ext_dir=$(make_external_project)
    out=$(
        cd "$ext_dir" && unset SPEED_PROJECT_ROOT
        # shellcheck disable=SC1090
        source "${LIB_DIR}/config.sh"
        [[ -d "${SPEED_DIR}/agents" ]] && echo "agents_dir_found"
        [[ -f "${SPEED_DIR}/sgconfig.yml" ]] && echo "sgconfig_found"
    )
    rm -rf "$ext_dir"
    assert_output_has() { echo "$out" | grep -q "$1"; }
    if ! assert_output_has "agents_dir_found"; then
        echo "    ASSERT: SPEED_DIR/agents not found from an external cwd" >&2
        return 1
    fi
    if ! assert_output_has "sgconfig_found"; then
        echo "    ASSERT: SPEED_DIR/sgconfig.yml not found from an external cwd" >&2
        return 1
    fi
}

run_test test_project_root_follows_external_cwd_not_speed_dir
run_test test_cmd_diagnose_succeeds_from_an_external_project_directory
run_test test_speed_dir_own_resources_unaffected_by_external_cwd

echo ""
echo "──────────────────────────────────────"
echo "Results: ${PASS} passed, ${FAIL} failed"
echo ""

if [[ "$FAIL" -gt 0 ]]; then
    exit 1
fi
