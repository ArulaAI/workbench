#!/usr/bin/env bash
# test_gates_subsystem.sh — Tests for subsystem detection, test path mapping,
# and CLAUDE.md gate config parsing in lib/gates.sh
#
# Usage: bash tests/test_gates_subsystem.sh
# Exit: 0 if all tests pass, 1 if any fail

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="${SCRIPT_DIR}/../lib"
PASS=0
FAIL=0
TEST_DIR=""

# ── Harness ───────────────────────────────────────────────────────────────────

setup() {
    TEST_DIR=$(mktemp -d)

    # Color/symbol stubs
    COLOR_ERROR="" COLOR_WARN="" COLOR_DIM="" COLOR_SUCCESS="" COLOR_STEP=""
    COLOR_INFO="" COLOR_HEADER="" COLOR_ACCENT=""
    BOLD="" RESET="" SYM_CHECK="" SYM_CROSS="" SYM_WARN="" SYM_ARROW=""
    SYM_PENDING="" SYM_DOT="" SYM_RUNNING=""
    VERBOSITY=0

    # Logging stubs
    log_error()   { :; }
    log_warn()    { :; }
    log_step()    { :; }
    log_success() { :; }
    log_info()    { :; }
    log_verbose() { :; }
    log_debug()   { :; }

    # Python stub
    _context_python() { echo "python3"; }

    # Set up a temporary git repo
    export PROJECT_ROOT="$TEST_DIR/repo"
    mkdir -p "$PROJECT_ROOT"
    git -C "$PROJECT_ROOT" init -b main --quiet
    git -C "$PROJECT_ROOT" config user.email "test@test.com"
    git -C "$PROJECT_ROOT" config user.name "Test"

    # Initial commit on main
    echo "init" > "$PROJECT_ROOT/README.md"
    git -C "$PROJECT_ROOT" add README.md
    git -C "$PROJECT_ROOT" commit -m "init" --quiet

    # SPEED directory structure
    export STATE_DIR="${PROJECT_ROOT}/.speed"
    export FEATURES_DIR="${STATE_DIR}/features"
    export TASKS_DIR="${STATE_DIR}/tasks"
    export LOGS_DIR="${STATE_DIR}/logs"
    export AGENT_FILE_PATH="${PROJECT_ROOT}/CLAUDE.md"
    mkdir -p "$TASKS_DIR" "$LOGS_DIR"

    # Git helpers
    _git() { git -C "$PROJECT_ROOT" "$@"; }
    git_main_branch() { echo "main"; }

    # Clear TOML overrides
    unset TOML_SUBSYSTEMS 2>/dev/null || true

    # Source grounding.sh (gates.sh depends on it)
    unset _GROUNDING_SH_LOADED 2>/dev/null || true
    # shellcheck source=../lib/grounding.sh
    source "${LIB_DIR}/grounding.sh"

    # Source gates.sh
    # shellcheck source=../lib/gates.sh
    source "${LIB_DIR}/gates.sh"
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

assert_output_contains() {
    local output="$1" pattern="$2"
    if ! echo "$output" | grep -q "$pattern"; then
        echo "    ASSERT: output does not contain '${pattern}'" >&2
        echo "    OUTPUT: ${output:0:400}" >&2
        return 1
    fi
}

assert_output_equals() {
    local expected="$1" actual="$2" context="${3:-}"
    if [[ "$expected" != "$actual" ]]; then
        echo "    ASSERT: expected '${expected}', got '${actual}'${context:+ (${context})}" >&2
        return 1
    fi
}

# Helper: create a task JSON with files_touched
_create_task_with_files() {
    local task_id="$1"
    shift
    local files_json="["
    local first=true
    for f in "$@"; do
        if $first; then
            files_json+="\"${f}\""
            first=false
        else
            files_json+=", \"${f}\""
        fi
    done
    files_json+="]"

    cat > "${TASKS_DIR}/${task_id}.json" <<EOF
{
    "id": "${task_id}",
    "branch": "feat/task-${task_id}",
    "description": "test task ${task_id}",
    "files_touched": ${files_json}
}
EOF
}

# ── Tests: _detect_subsystem_hardcoded ────────────────────────────────────────

test_hardcoded_frontend_files() {
    local output
    output=$(_detect_subsystem_hardcoded "src/frontend/components/Button.tsx
src/frontend/pages/Home.tsx")
    assert_output_equals "frontend" "$output" "pure frontend files"
}

test_hardcoded_backend_files() {
    local output
    output=$(_detect_subsystem_hardcoded "src/backend/api/routes.py
src/backend/models/user.py")
    assert_output_equals "backend" "$output" "pure backend files"
}

test_hardcoded_mixed_files() {
    local output
    output=$(_detect_subsystem_hardcoded "src/frontend/components/Button.tsx
src/backend/api/routes.py")
    assert_output_equals "both" "$output" "mixed frontend+backend files"
}

test_hardcoded_plugin_files() {
    local output
    output=$(_detect_subsystem_hardcoded "src/plugins/auth/handler.ts")
    assert_output_equals "plugin" "$output" "plugin files"
}

test_hardcoded_no_match_returns_both() {
    local output
    output=$(_detect_subsystem_hardcoded "README.md
docs/guide.md")
    assert_output_equals "both" "$output" "unrecognized paths default to both"
}

test_hardcoded_empty_input_returns_both() {
    local output
    output=$(_detect_subsystem_hardcoded "")
    assert_output_equals "both" "$output" "empty input defaults to both"
}

# ── Tests: _detect_subsystem (full function with task JSON) ───────────────────

test_detect_subsystem_frontend_task() {
    _create_task_with_files "1" "src/frontend/app.tsx" "src/frontend/utils.ts"
    local output
    output=$(_detect_subsystem "1")
    assert_output_equals "frontend" "$output" "task with frontend files"
}

test_detect_subsystem_backend_task() {
    _create_task_with_files "2" "src/backend/server.py" "src/backend/db.py"
    local output
    output=$(_detect_subsystem "2")
    assert_output_equals "backend" "$output" "task with backend files"
}

test_detect_subsystem_mixed_task() {
    _create_task_with_files "3" "src/frontend/app.tsx" "src/backend/server.py"
    local output
    output=$(_detect_subsystem "3")
    assert_output_equals "both" "$output" "task with mixed files"
}

test_detect_subsystem_missing_task_file() {
    local output
    output=$(_detect_subsystem "nonexistent")
    assert_output_equals "both" "$output" "missing task file defaults to both"
}

test_detect_subsystem_no_files_touched() {
    cat > "${TASKS_DIR}/5.json" <<EOF
{
    "id": "5",
    "branch": "feat/task-5",
    "description": "task without files_touched"
}
EOF
    local output
    output=$(_detect_subsystem "5")
    assert_output_equals "both" "$output" "no files_touched defaults to both"
}

# ── Tests: _build_scoped_test_paths ───────────────────────────────────────────

test_scoped_test_tsx_mapping() {
    # Create source and test files on disk
    mkdir -p "$PROJECT_ROOT/src/frontend/components"
    echo "// source" > "$PROJECT_ROOT/src/frontend/components/Button.tsx"
    echo "// test"   > "$PROJECT_ROOT/src/frontend/components/Button.test.tsx"

    _create_task_with_files "10" "src/frontend/components/Button.tsx"

    local output
    output=$(_build_scoped_test_paths "10" "$PROJECT_ROOT")
    assert_output_contains "$output" "Button.test.tsx"
}

test_scoped_test_ts_mapping() {
    mkdir -p "$PROJECT_ROOT/src/frontend/utils"
    echo "// source" > "$PROJECT_ROOT/src/frontend/utils/format.ts"
    echo "// test"   > "$PROJECT_ROOT/src/frontend/utils/format.test.ts"

    _create_task_with_files "11" "src/frontend/utils/format.ts"

    local output
    output=$(_build_scoped_test_paths "11" "$PROJECT_ROOT")
    assert_output_contains "$output" "format.test.ts"
}

test_scoped_test_py_mapping() {
    mkdir -p "$PROJECT_ROOT/src/backend/app/models"
    mkdir -p "$PROJECT_ROOT/src/backend/app/tests"
    echo "# source" > "$PROJECT_ROOT/src/backend/app/models/user.py"
    echo "# test"   > "$PROJECT_ROOT/src/backend/app/tests/test_user.py"

    _create_task_with_files "12" "src/backend/app/models/user.py"

    local output
    output=$(_build_scoped_test_paths "12" "$PROJECT_ROOT")
    assert_output_contains "$output" "test_user.py"
}

test_scoped_test_already_test_file() {
    mkdir -p "$PROJECT_ROOT/src/frontend/components"
    echo "// test" > "$PROJECT_ROOT/src/frontend/components/Button.test.tsx"

    _create_task_with_files "13" "src/frontend/components/Button.test.tsx"

    local output
    output=$(_build_scoped_test_paths "13" "$PROJECT_ROOT")
    assert_output_contains "$output" "Button.test.tsx"
}

test_scoped_test_no_matching_test_file() {
    mkdir -p "$PROJECT_ROOT/src/frontend/components"
    echo "// source" > "$PROJECT_ROOT/src/frontend/components/Orphan.tsx"
    # No corresponding Orphan.test.tsx exists

    _create_task_with_files "14" "src/frontend/components/Orphan.tsx"

    local output
    output=$(_build_scoped_test_paths "14" "$PROJECT_ROOT")
    # Should be empty (no test files found)
    if [[ -n "$output" && "$output" =~ [^[:space:]] ]]; then
        echo "    ASSERT: expected empty output for missing test file, got '${output}'" >&2
        return 1
    fi
}

# ── Tests: gates_get_config ───────────────────────────────────────────────────

test_gates_config_parses_lint() {
    cat > "$AGENT_FILE_PATH" <<'EOF'
# Project

## Quality Gates

- lint: `cd frontend && npx eslint .`
- test: `cd frontend && npx vitest run`
- typecheck: `cd frontend && npx tsc --noEmit`
EOF

    local output
    output=$(gates_get_config "lint" "both")
    assert_output_equals "cd frontend && npx eslint ." "$output" "lint command"
}

test_gates_config_parses_test() {
    cat > "$AGENT_FILE_PATH" <<'EOF'
## Quality Gates

- test: `cd backend && python -m pytest`
EOF

    local output
    output=$(gates_get_config "test" "both")
    assert_output_equals "cd backend && python -m pytest" "$output" "test command"
}

test_gates_config_subsystem_frontend_only() {
    cat > "$AGENT_FILE_PATH" <<'EOF'
## Quality Gates

### Frontend
- lint: `npx eslint src/`
- test: `npx vitest run`

### Backend
- lint: `cd backend && flake8`
- test: `cd backend && pytest`
EOF

    local output
    output=$(gates_get_config "lint" "frontend")
    assert_output_equals "npx eslint src/" "$output" "frontend lint only"
}

test_gates_config_subsystem_backend_only() {
    cat > "$AGENT_FILE_PATH" <<'EOF'
## Quality Gates

### Frontend
- lint: `npx eslint src/`

### Backend
- lint: `cd backend && flake8`
EOF

    local output
    output=$(gates_get_config "lint" "backend")
    assert_output_equals "cd backend && flake8" "$output" "backend lint only"
}

test_gates_config_both_returns_all() {
    cat > "$AGENT_FILE_PATH" <<'EOF'
## Quality Gates

### Frontend
- lint: `npx eslint src/`

### Backend
- lint: `cd backend && flake8`
EOF

    local output
    output=$(gates_get_config "lint" "both")
    assert_output_contains "$output" "npx eslint src/"
    assert_output_contains "$output" "cd backend && flake8"
}

test_gates_config_missing_claude_md() {
    rm -f "$AGENT_FILE_PATH"

    local output
    output=$(gates_get_config "lint" "both")
    if [[ -n "$output" ]]; then
        echo "    ASSERT: expected empty output when CLAUDE.md missing, got '${output}'" >&2
        return 1
    fi
}

test_gates_config_no_quality_gates_section() {
    cat > "$AGENT_FILE_PATH" <<'EOF'
# Project

## Something Else

- lint: `should not match`
EOF

    local output
    output=$(gates_get_config "lint" "both")
    if [[ -n "$output" ]]; then
        echo "    ASSERT: expected empty output when no Quality Gates section, got '${output}'" >&2
        return 1
    fi
}

test_gates_config_stops_at_next_h2() {
    cat > "$AGENT_FILE_PATH" <<'EOF'
## Quality Gates

- lint: `npx eslint .`

## Other Section

- lint: `should not match`
EOF

    local output
    output=$(gates_get_config "lint" "both")
    # Should contain exactly one lint command, not the one after ## Other Section
    local count
    count=$(echo "$output" | grep -c "." || true)
    if [[ "$count" -ne 1 ]]; then
        echo "    ASSERT: expected 1 lint command, got ${count}" >&2
        echo "    OUTPUT: ${output}" >&2
        return 1
    fi
}

# ── Run all tests ─────────────────────────────────────────────────────────────

echo ""
echo "Gates subsystem tests"
echo "──────────────────────────────────────"

# _detect_subsystem_hardcoded
run_test test_hardcoded_frontend_files
run_test test_hardcoded_backend_files
run_test test_hardcoded_mixed_files
run_test test_hardcoded_plugin_files
run_test test_hardcoded_no_match_returns_both
run_test test_hardcoded_empty_input_returns_both

# _detect_subsystem (with task JSON)
run_test test_detect_subsystem_frontend_task
run_test test_detect_subsystem_backend_task
run_test test_detect_subsystem_mixed_task
run_test test_detect_subsystem_missing_task_file
run_test test_detect_subsystem_no_files_touched

# _build_scoped_test_paths
run_test test_scoped_test_tsx_mapping
run_test test_scoped_test_ts_mapping
run_test test_scoped_test_py_mapping
run_test test_scoped_test_already_test_file
run_test test_scoped_test_no_matching_test_file

# gates_get_config
run_test test_gates_config_parses_lint
run_test test_gates_config_parses_test
run_test test_gates_config_subsystem_frontend_only
run_test test_gates_config_subsystem_backend_only
run_test test_gates_config_both_returns_all
run_test test_gates_config_missing_claude_md
run_test test_gates_config_no_quality_gates_section
run_test test_gates_config_stops_at_next_h2

echo ""
echo "──────────────────────────────────────"
echo "Results: ${PASS} passed, ${FAIL} failed"
echo ""

if [[ "$FAIL" -gt 0 ]]; then
    exit 1
fi
