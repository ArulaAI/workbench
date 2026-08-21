#!/usr/bin/env bash
# test_grounding_test_coverage_languages.sh — Tests for multi-language test coverage
#
# Verifies _test_file_stem(), _lang_family(), _test_file_exists_in_diff(),
# _test_coverage_excluded() build file exclusions, and speed.toml escape hatches.
#
# Usage: bash tests/test_grounding_test_coverage_languages.sh
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
    BOLD="" RESET="" SYM_CHECK="" SYM_CROSS="" SYM_WARN="" SYM_ARROW=""
    VERBOSITY=0

    # Logging stubs
    log_error()   { :; }
    log_warn()    { :; }
    log_step()    { :; }
    log_success() { :; }

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
    mkdir -p "$TASKS_DIR" "$LOGS_DIR"

    # Git helpers
    _git() { git -C "$PROJECT_ROOT" "$@"; }
    git_main_branch() { echo "main"; }

    # Source grounding.sh
    unset _GROUNDING_SH_LOADED 2>/dev/null || true
    # shellcheck source=../lib/grounding.sh
    source "${LIB_DIR}/grounding.sh"
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

# Helper: assert _test_file_stem returns expected stem
assert_stem() {
    local file="$1" expected="$2"
    local actual
    actual=$(_test_file_stem "$file") || {
        echo "    ASSERT: _test_file_stem '${file}' returned exit 1, expected stem '${expected}'" >&2
        return 1
    }
    if [[ "$actual" != "$expected" ]]; then
        echo "    ASSERT: _test_file_stem '${file}' = '${actual}', expected '${expected}'" >&2
        return 1
    fi
}

# Helper: assert _test_file_stem returns exit 1 (not a test file)
assert_no_stem() {
    local file="$1"
    local actual
    if actual=$(_test_file_stem "$file" 2>/dev/null); then
        echo "    ASSERT: _test_file_stem '${file}' returned stem '${actual}', expected exit 1" >&2
        return 1
    fi
}

# Helper: assert _lang_family returns expected family
assert_family() {
    local file="$1" expected="$2"
    local actual
    actual=$(_lang_family "$file")
    if [[ "$actual" != "$expected" ]]; then
        echo "    ASSERT: _lang_family '${file}' = '${actual}', expected '${expected}'" >&2
        return 1
    fi
}

# ══════════════════════════════════════════════════════════════════════════════
# Section 1: _test_file_stem — unit tests for all 20 languages
# ══════════════════════════════════════════════════════════════════════════════

test_stem_js_ts() {
    assert_stem "Button.test.ts"    "Button"
    assert_stem "Button.test.tsx"   "Button"
    assert_stem "utils.test.js"     "utils"
    assert_stem "utils.test.jsx"    "utils"
    assert_stem "Button.spec.ts"    "Button"
    assert_stem "Button.spec.tsx"   "Button"
    assert_stem "utils.spec.js"     "utils"
    assert_stem "utils.spec.jsx"    "utils"
    # Multi-dot basename
    assert_stem "button.controller.test.tsx" "button.controller"
}

test_stem_python() {
    assert_stem "test_parser.py"    "parser"
    assert_stem "parser_test.py"    "parser"
    assert_no_stem "parser.py"
}

test_stem_go() {
    assert_stem "parser_test.go"    "parser"
    assert_stem "handler_test.go"   "handler"
    assert_no_stem "parser.go"
}

test_stem_ruby() {
    assert_stem "parser_spec.rb"    "parser"
    assert_stem "parser_test.rb"    "parser"
    assert_stem "test_parser.rb"    "parser"
    assert_no_stem "parser.rb"
}

test_stem_java() {
    assert_stem "UserServiceTest.java"  "UserService"
    assert_stem "UserServiceTests.java" "UserService"
    assert_no_stem "UserService.java"
}

test_stem_scala() {
    assert_stem "ParserTest.scala"  "Parser"
    assert_stem "ParserSpec.scala"  "Parser"
    assert_no_stem "Parser.scala"
}

test_stem_csharp() {
    assert_stem "ParserTest.cs"     "Parser"
    assert_stem "ParserTests.cs"    "Parser"
    assert_no_stem "Parser.cs"
}

test_stem_php() {
    assert_stem "ParserTest.php"    "Parser"
    assert_stem "ParserTests.php"   "Parser"
    assert_no_stem "Parser.php"
}

test_stem_bash() {
    assert_stem "test_deploy.sh"    "deploy"
    assert_no_stem "deploy.sh"
}

test_stem_kotlin() {
    assert_stem "UserServiceTest.kt"  "UserService"
    assert_stem "UserServiceTests.kt" "UserService"
    assert_no_stem "UserService.kt"
}

test_stem_swift() {
    assert_stem "ParserTest.swift"  "Parser"
    assert_stem "ParserTests.swift" "Parser"
    assert_no_stem "Parser.swift"
}

test_stem_rust() {
    assert_stem "parser_test.rs"    "parser"
    assert_no_stem "parser.rs"
}

test_stem_dart() {
    assert_stem "parser_test.dart"  "parser"
    assert_no_stem "parser.dart"
}

test_stem_elixir() {
    assert_stem "parser_test.exs"   "parser"
    assert_no_stem "parser.ex"
}

test_stem_c() {
    assert_stem "test_parser.c"     "parser"
    assert_stem "parser_test.c"     "parser"
    assert_no_stem "parser.c"
}

test_stem_cpp() {
    assert_stem "test_parser.cpp"   "parser"
    assert_stem "parser_test.cpp"   "parser"
    assert_stem "test_parser.cc"    "parser"
    assert_stem "parser_test.cc"    "parser"
    assert_stem "test_parser.cxx"   "parser"
    assert_stem "parser_test.cxx"   "parser"
    assert_no_stem "parser.cpp"
}

test_stem_lua() {
    assert_stem "test_parser.lua"   "parser"
    assert_stem "parser_test.lua"   "parser"
    assert_stem "parser_spec.lua"   "parser"
    assert_no_stem "parser.lua"
}

test_stem_perl() {
    assert_stem "parser.t"          "parser"
    assert_stem "parser_test.pl"    "parser"
    assert_no_stem "parser.pl"
}

test_stem_haskell() {
    assert_stem "ParserSpec.hs"     "Parser"
    assert_stem "ParserTest.hs"     "Parser"
    assert_no_stem "Parser.hs"
}

test_stem_clojure() {
    assert_stem "parser_test.clj"   "parser"
    assert_no_stem "parser.clj"
}

test_stem_tests_directory() {
    assert_stem "src/__tests__/Button.tsx"           "Button"
    assert_stem "src/__tests__/Button.test.tsx"      "Button"
    assert_stem "src/__tests__/Button.spec.tsx"      "Button"
    assert_stem "src/__tests__/utils/helpers.ts"     "helpers"
}

test_stem_edge_cases() {
    # Full paths (not just basenames)
    assert_stem "src/main/java/com/example/UserServiceTest.java" "UserService"
    assert_stem "pkg/parser/parser_test.go"                      "parser"
    assert_stem "lib/test_deploy.sh"                             "deploy"
    assert_no_stem "src/main/java/com/example/UserService.java"

    # Empty stem: Test.java → stem is ""
    local stem
    stem=$(_test_file_stem "Test.java") || {
        echo "    ASSERT: Test.java should be recognized as test file" >&2
        return 1
    }
    if [[ -n "$stem" ]]; then
        echo "    ASSERT: Test.java stem should be empty, got '${stem}'" >&2
        return 1
    fi

    # Multi-dot paths
    assert_stem "src/utils/api.client.test.ts" "api.client"
    assert_no_stem "src/utils/api.client.ts"

    # Prefix pattern with empty stem after stripping
    assert_stem "test_.py" ""

    # Suffix pattern with empty stem after stripping
    assert_stem "_test.py" ""

    # Files with no extension — not test files
    assert_no_stem "Makefile"
    assert_no_stem "Dockerfile"
    assert_no_stem "README"
}

test_stem_double_nested_tests_dir() {
    # Deeply nested __tests__/
    assert_stem "a/b/__tests__/c/d/foo.tsx"              "foo"
    assert_stem "a/__tests__/b/__tests__/bar.test.tsx"   "bar"
}

test_lang_family_with_test_files() {
    # Test file extensions should map to the correct family
    assert_family "UserServiceTest.java"    "jvm"
    assert_family "parser_test.go"          "go"
    assert_family "test_parser.py"          "py"
    assert_family "parser_test.rs"          "rust"
    assert_family "parser_test.exs"         "elixir"
    assert_family "ParserTest.kt"           "jvm"
    assert_family "ParserTests.swift"       "swift"
    assert_family "parser_test.dart"        "dart"
    assert_family "ParserTest.scala"        "jvm"
    assert_family "parser.t"               "perl"
    assert_family "ParserSpec.hs"           "haskell"
    assert_family "parser_test.clj"         "clojure"
}

# ══════════════════════════════════════════════════════════════════════════════
# Section 2: _lang_family — extension to family mapping
# ══════════════════════════════════════════════════════════════════════════════

test_lang_family_mapping() {
    assert_family "src/foo.ts"          "js"
    assert_family "src/foo.tsx"         "js"
    assert_family "src/foo.js"          "js"
    assert_family "src/foo.jsx"         "js"
    assert_family "src/foo.mjs"         "js"
    assert_family "src/foo.cjs"         "js"
    assert_family "src/foo.py"          "py"
    assert_family "src/foo.go"          "go"
    assert_family "src/foo.rb"          "rb"
    assert_family "src/foo.java"        "jvm"
    assert_family "src/foo.scala"       "jvm"
    assert_family "src/foo.kt"          "jvm"
    assert_family "src/foo.kts"         "jvm"
    assert_family "src/foo.cs"          "dotnet"
    assert_family "src/foo.php"         "php"
    assert_family "src/foo.sh"          "sh"
    assert_family "src/foo.bash"        "sh"
    assert_family "src/foo.swift"       "swift"
    assert_family "src/foo.rs"          "rust"
    assert_family "src/foo.dart"        "dart"
    assert_family "src/foo.ex"          "elixir"
    assert_family "src/foo.exs"         "elixir"
    assert_family "src/foo.c"           "c"
    assert_family "src/foo.h"           "c"
    assert_family "src/foo.cpp"         "cpp"
    assert_family "src/foo.cc"          "cpp"
    assert_family "src/foo.cxx"         "cpp"
    assert_family "src/foo.hpp"         "cpp"
    assert_family "src/foo.lua"         "lua"
    assert_family "src/foo.pl"          "perl"
    assert_family "src/foo.pm"          "perl"
    assert_family "src/foo.t"           "perl"
    assert_family "src/foo.hs"          "haskell"
    assert_family "src/foo.clj"         "clojure"
    assert_family "src/foo.cljs"        "clojure"
    assert_family "src/foo.cljc"        "clojure"
    assert_family "src/foo.xyz"         "unknown"
}

# ══════════════════════════════════════════════════════════════════════════════
# Section 3: _test_file_exists_in_diff — cross-language collision prevention
# ══════════════════════════════════════════════════════════════════════════════

# Helper: create branch with files for diff-based tests
_create_diff_branch() {
    local branch_name="$1"
    shift

    git -C "$PROJECT_ROOT" checkout main --quiet 2>/dev/null
    git -C "$PROJECT_ROOT" checkout -b "$branch_name" --quiet

    for file_path in "$@"; do
        mkdir -p "$(dirname "$PROJECT_ROOT/$file_path")"
        echo "// content" > "$PROJECT_ROOT/$file_path"
        git -C "$PROJECT_ROOT" add "$file_path"
    done

    git -C "$PROJECT_ROOT" commit -m "add files" --quiet
}

test_diff_java_source_matched_by_java_test() {
    _create_diff_branch "feat/java" \
        "src/main/java/com/example/UserService.java" \
        "src/test/java/com/example/UserServiceTest.java"

    local diff_files
    diff_files=$(_git diff "main...feat/java" --name-only)

    local rc=0
    _test_file_exists_in_diff "src/main/java/com/example/UserService.java" "$diff_files" || rc=$?

    if [[ $rc -ne 0 ]]; then
        echo "    ASSERT: Java source should be matched by Java test, got exit ${rc}" >&2
        return 1
    fi
}

test_diff_cross_language_rejection() {
    # parser.py should NOT be matched by parser.test.tsx (different family)
    _create_diff_branch "feat/cross" \
        "src/utils/parser.py" \
        "src/components/parser.test.tsx"

    local diff_files
    diff_files=$(_git diff "main...feat/cross" --name-only)

    local rc=0
    _test_file_exists_in_diff "src/utils/parser.py" "$diff_files" || rc=$?

    if [[ $rc -eq 0 ]]; then
        echo "    ASSERT: Python source should NOT be matched by JS test, got exit 0" >&2
        return 1
    fi
}

test_diff_go_source_matched_by_go_test() {
    _create_diff_branch "feat/go" \
        "pkg/parser/parser.go" \
        "pkg/parser/parser_test.go"

    local diff_files
    diff_files=$(_git diff "main...feat/go" --name-only)

    local rc=0
    _test_file_exists_in_diff "pkg/parser/parser.go" "$diff_files" || rc=$?

    if [[ $rc -ne 0 ]]; then
        echo "    ASSERT: Go source should be matched by Go test, got exit ${rc}" >&2
        return 1
    fi
}

test_diff_kotlin_matched_by_java_family() {
    # Kotlin and Java share the jvm family
    _create_diff_branch "feat/jvm" \
        "src/main/kotlin/UserService.kt" \
        "src/test/java/UserServiceTest.java"

    local diff_files
    diff_files=$(_git diff "main...feat/jvm" --name-only)

    local rc=0
    _test_file_exists_in_diff "src/main/kotlin/UserService.kt" "$diff_files" || rc=$?

    if [[ $rc -ne 0 ]]; then
        echo "    ASSERT: Kotlin source should be matched by Java test (jvm family), got exit ${rc}" >&2
        return 1
    fi
}

test_diff_no_test_file_fails() {
    _create_diff_branch "feat/notest" \
        "src/main/java/com/example/UserService.java"

    local diff_files
    diff_files=$(_git diff "main...feat/notest" --name-only)

    local rc=0
    _test_file_exists_in_diff "src/main/java/com/example/UserService.java" "$diff_files" || rc=$?

    if [[ $rc -eq 0 ]]; then
        echo "    ASSERT: should fail with no test file in diff, got exit 0" >&2
        return 1
    fi
}

test_diff_rust_source_matched() {
    _create_diff_branch "feat/rust" \
        "src/parser.rs" \
        "src/parser_test.rs"

    local diff_files
    diff_files=$(_git diff "main...feat/rust" --name-only)

    local rc=0
    _test_file_exists_in_diff "src/parser.rs" "$diff_files" || rc=$?

    if [[ $rc -ne 0 ]]; then
        echo "    ASSERT: Rust source should be matched by Rust test, got exit ${rc}" >&2
        return 1
    fi
}

test_diff_python_different_directory() {
    # Python test in tests/ dir should match source in src/
    _create_diff_branch "feat/pydir" \
        "src/backend/models/user.py" \
        "tests/test_user.py"

    local diff_files
    diff_files=$(_git diff "main...feat/pydir" --name-only)

    local rc=0
    _test_file_exists_in_diff "src/backend/models/user.py" "$diff_files" || rc=$?

    if [[ $rc -ne 0 ]]; then
        echo "    ASSERT: Python source should be matched by test in different dir, got exit ${rc}" >&2
        return 1
    fi
}

test_diff_empty_diff_files() {
    local rc=0
    _test_file_exists_in_diff "src/Foo.java" "" || rc=$?

    if [[ $rc -eq 0 ]]; then
        echo "    ASSERT: empty diff should not match anything, got exit 0" >&2
        return 1
    fi
}

test_diff_elixir_source_matched() {
    _create_diff_branch "feat/elixir" \
        "lib/parser.ex" \
        "test/parser_test.exs"

    local diff_files
    diff_files=$(_git diff "main...feat/elixir" --name-only)

    local rc=0
    _test_file_exists_in_diff "lib/parser.ex" "$diff_files" || rc=$?

    if [[ $rc -ne 0 ]]; then
        echo "    ASSERT: Elixir source should be matched by Elixir test, got exit ${rc}" >&2
        return 1
    fi
}

test_diff_csharp_source_matched() {
    _create_diff_branch "feat/csharp" \
        "src/Parser.cs" \
        "tests/ParserTests.cs"

    local diff_files
    diff_files=$(_git diff "main...feat/csharp" --name-only)

    local rc=0
    _test_file_exists_in_diff "src/Parser.cs" "$diff_files" || rc=$?

    if [[ $rc -ne 0 ]]; then
        echo "    ASSERT: C# source should be matched by C# test, got exit ${rc}" >&2
        return 1
    fi
}

test_diff_swift_source_matched() {
    _create_diff_branch "feat/swift" \
        "Sources/Parser.swift" \
        "Tests/ParserTests.swift"

    local diff_files
    diff_files=$(_git diff "main...feat/swift" --name-only)

    local rc=0
    _test_file_exists_in_diff "Sources/Parser.swift" "$diff_files" || rc=$?

    if [[ $rc -ne 0 ]]; then
        echo "    ASSERT: Swift source should be matched by Swift test, got exit ${rc}" >&2
        return 1
    fi
}

test_diff_same_stem_same_family_different_dirs() {
    # Known limitation: two Parser.java in different packages, one test covers both
    # This is a false positive in the safe direction (claims coverage when ambiguous)
    _create_diff_branch "feat/ambig" \
        "com/foo/Parser.java" \
        "com/bar/Parser.java" \
        "com/foo/ParserTest.java"

    local diff_files
    diff_files=$(_git diff "main...feat/ambig" --name-only)

    # com/foo/Parser.java — matched (same stem Parser, same family jvm)
    local rc1=0
    _test_file_exists_in_diff "com/foo/Parser.java" "$diff_files" || rc1=$?
    if [[ $rc1 -ne 0 ]]; then
        echo "    ASSERT: com/foo/Parser.java should match, got exit ${rc1}" >&2
        return 1
    fi

    # com/bar/Parser.java — also matched (known false positive)
    local rc2=0
    _test_file_exists_in_diff "com/bar/Parser.java" "$diff_files" || rc2=$?
    if [[ $rc2 -ne 0 ]]; then
        echo "    ASSERT: com/bar/Parser.java matches too (known false positive), got exit ${rc2}" >&2
        return 1
    fi
}

test_diff_test_file_matches_regardless_of_path() {
    # _test_file_exists_in_diff only checks if a matching test exists in the diff.
    # It does NOT verify the source file is in the diff (caller's responsibility).
    # A test file anywhere in the diff with matching stem + family is a match.
    _create_diff_branch "feat/testmatch" \
        "src/main/UserService.java" \
        "completely/different/path/UserServiceTest.java"

    local diff_files
    diff_files=$(_git diff "main...feat/testmatch" --name-only)

    local rc=0
    _test_file_exists_in_diff "src/main/UserService.java" "$diff_files" || rc=$?

    if [[ $rc -ne 0 ]]; then
        echo "    ASSERT: test in any path should match by stem+family, got exit ${rc}" >&2
        return 1
    fi
}

# ══════════════════════════════════════════════════════════════════════════════
# Section 4: _test_coverage_excluded — build files and custom patterns
# ══════════════════════════════════════════════════════════════════════════════

test_excluded_build_files() {
    local build_files=(
        "pom.xml" "build.gradle" "build.gradle.kts"
        "go.mod" "go.sum" "Cargo.toml" "Cargo.lock"
        "Gemfile" "Makefile" "CMakeLists.txt"
        "build.sbt" "mix.exs" "pubspec.yaml"
        "Rakefile" "project.clj" "setup.py"
        "pyproject.toml" "Pipfile" "composer.json"
    )

    for f in "${build_files[@]}"; do
        if ! _test_coverage_excluded "$f"; then
            echo "    ASSERT: '${f}' should be excluded (build file)" >&2
            return 1
        fi
    done
}

test_excluded_test_files_all_languages() {
    local test_files=(
        "UserServiceTest.java" "UserServiceTest.kt" "ParserTest.scala"
        "parser_test.go" "parser_spec.rb" "parser_test.rs"
        "parser_test.dart" "parser_test.exs" "test_parser.c"
        "parser_test.cpp" "test_parser.lua" "parser.t"
        "ParserSpec.hs" "parser_test.clj" "ParserTest.swift"
        "ParserTests.cs" "ParserTest.php"
    )

    for f in "${test_files[@]}"; do
        if ! _test_coverage_excluded "$f"; then
            echo "    ASSERT: '${f}' should be excluded (test file)" >&2
            return 1
        fi
    done
}

test_excluded_custom_patterns() {
    # Write speed.toml with custom exclude patterns
    cat > "$PROJECT_ROOT/speed.toml" <<'EOF'
test_coverage.exclude_patterns = "src/generated/**,vendor/**"
EOF

    if ! _test_coverage_excluded "src/generated/api/client.java"; then
        echo "    ASSERT: 'src/generated/api/client.java' should be excluded by custom pattern" >&2
        return 1
    fi
    if ! _test_coverage_excluded "vendor/lib/parser.go"; then
        echo "    ASSERT: 'vendor/lib/parser.go' should be excluded by custom pattern" >&2
        return 1
    fi
    # Non-matching file should NOT be excluded
    if _test_coverage_excluded "src/main/UserService.java"; then
        echo "    ASSERT: 'src/main/UserService.java' should NOT be excluded" >&2
        return 1
    fi
}

test_excluded_source_files_not_excluded() {
    # Source files across languages should NOT be excluded
    local source_files=(
        "src/UserService.java" "src/parser.go" "src/handler.py"
        "src/Parser.kt" "src/widget.dart" "lib/grounding.sh"
        "src/Parser.scala" "src/Parser.cs" "src/Parser.php"
        "src/parser.rs" "lib/parser.ex" "src/parser.c"
        "src/parser.cpp" "src/parser.lua" "src/parser.pl"
        "src/Parser.hs" "src/parser.clj" "src/Parser.swift"
    )

    for f in "${source_files[@]}"; do
        if _test_coverage_excluded "$f"; then
            echo "    ASSERT: '${f}' should NOT be excluded (source file)" >&2
            return 1
        fi
    done
}

test_excluded_remaining_build_files() {
    # Build files not covered by test_excluded_build_files
    local more_build_files=(
        "settings.gradle" "settings.gradle.kts"
        "Gemfile.lock" "foo.gemspec"
        "composer.lock" "foo.cmake"
        "Foo.csproj" "Foo.sln" "Foo.fsproj"
        "mix.lock" "pubspec.lock"
        "foo.cabal" "stack.yaml"
        "setup.cfg" "Pipfile.lock"
    )

    for f in "${more_build_files[@]}"; do
        if ! _test_coverage_excluded "$f"; then
            echo "    ASSERT: '${f}' should be excluded (build file)" >&2
            return 1
        fi
    done
}

test_excluded_requirements_glob() {
    # requirements*.txt should match requirements-dev.txt, requirements-prod.txt, etc.
    local req_files=(
        "requirements.txt"
        "requirements-dev.txt"
        "requirements-prod.txt"
    )
    for f in "${req_files[@]}"; do
        if ! _test_coverage_excluded "$f"; then
            echo "    ASSERT: '${f}' should be excluded (requirements glob)" >&2
            return 1
        fi
    done
}

test_excluded_test_directories() {
    # Files within test/, tests/, __tests__/ directories
    local dir_files=(
        "test/helpers.py"
        "tests/conftest.py"
        "src/__tests__/setup.ts"
        "src/backend/tests/fixtures.py"
        "pkg/test/utils.go"
    )
    for f in "${dir_files[@]}"; do
        if ! _test_coverage_excluded "$f"; then
            echo "    ASSERT: '${f}' should be excluded (test directory)" >&2
            return 1
        fi
    done
}

# ══════════════════════════════════════════════════════════════════════════════
# Section 5: Escape hatches — test_coverage.skip, test_coverage.patterns
# ══════════════════════════════════════════════════════════════════════════════

test_skip_escape_hatch() {
    cat > "$PROJECT_ROOT/speed.toml" <<'EOF'
test_coverage.skip = true
EOF

    # Create a branch with a testable source file but no test
    git -C "$PROJECT_ROOT" checkout -b "feat/skip-test" --quiet
    mkdir -p "$PROJECT_ROOT/src"
    echo "class Foo {}" > "$PROJECT_ROOT/src/Foo.java"
    git -C "$PROJECT_ROOT" add src/Foo.java
    git -C "$PROJECT_ROOT" commit -m "add Foo.java" --quiet

    cat > "${TASKS_DIR}/1.json" <<'EOF'
{
    "id": "1",
    "branch": "feat/skip-test",
    "description": "test task",
    "files_touched": ["src/Foo.java"]
}
EOF

    local rc=0
    grounding_check_test_coverage "1" || rc=$?

    if [[ $rc -ne 0 ]]; then
        echo "    ASSERT: test_coverage.skip=true should make check pass, got exit ${rc}" >&2
        return 1
    fi
}

test_custom_stem_patterns() {
    # Custom pattern: *Spec.kt uses suffix:Spec rule
    cat > "$PROJECT_ROOT/speed.toml" <<'EOF'
test_coverage.patterns = "*Spec.kt=suffix:Spec"
EOF

    local stem
    stem=$(_test_file_stem "UserServiceSpec.kt") || {
        echo "    ASSERT: custom pattern should recognize UserServiceSpec.kt as test file" >&2
        return 1
    }
    if [[ "$stem" != "UserService" ]]; then
        echo "    ASSERT: stem should be 'UserService', got '${stem}'" >&2
        return 1
    fi
}

test_custom_stem_prefix_rule() {
    cat > "$PROJECT_ROOT/speed.toml" <<'EOF'
test_coverage.patterns = "check_*.rb=prefix:check_"
EOF

    local stem
    stem=$(_test_file_stem "check_parser.rb") || {
        echo "    ASSERT: custom prefix pattern should recognize check_parser.rb as test file" >&2
        return 1
    }
    if [[ "$stem" != "parser" ]]; then
        echo "    ASSERT: stem should be 'parser', got '${stem}'" >&2
        return 1
    fi
}

test_skip_false_does_not_skip() {
    cat > "$PROJECT_ROOT/speed.toml" <<'EOF'
test_coverage.skip = false
EOF

    # Create a branch with a testable source file but no test
    git -C "$PROJECT_ROOT" checkout -b "feat/noskip" --quiet
    mkdir -p "$PROJECT_ROOT/src"
    echo "class Foo {}" > "$PROJECT_ROOT/src/Foo.java"
    git -C "$PROJECT_ROOT" add src/Foo.java
    git -C "$PROJECT_ROOT" commit -m "add Foo.java" --quiet

    cat > "${TASKS_DIR}/1.json" <<'EOF'
{
    "id": "1",
    "branch": "feat/noskip",
    "description": "test task",
    "files_touched": ["src/Foo.java"]
}
EOF

    local rc=0
    grounding_check_test_coverage "1" || rc=$?

    if [[ $rc -eq 0 ]]; then
        echo "    ASSERT: test_coverage.skip=false should NOT skip, got exit 0" >&2
        return 1
    fi
}

test_custom_pattern_fallthrough_to_builtin() {
    # Custom pattern matches *Verify.kt but not *Test.java
    # Built-in should still handle *Test.java
    cat > "$PROJECT_ROOT/speed.toml" <<'EOF'
test_coverage.patterns = "*Verify.kt=suffix:Verify"
EOF

    # Custom pattern works
    local stem1
    stem1=$(_test_file_stem "ParserVerify.kt") || {
        echo "    ASSERT: custom pattern should match ParserVerify.kt" >&2
        return 1
    }
    if [[ "$stem1" != "Parser" ]]; then
        echo "    ASSERT: custom stem should be 'Parser', got '${stem1}'" >&2
        return 1
    fi

    # Built-in still works for non-matching files
    local stem2
    stem2=$(_test_file_stem "UserServiceTest.java") || {
        echo "    ASSERT: built-in should still match UserServiceTest.java" >&2
        return 1
    }
    if [[ "$stem2" != "UserService" ]]; then
        echo "    ASSERT: built-in stem should be 'UserService', got '${stem2}'" >&2
        return 1
    fi
}

test_multiple_custom_patterns() {
    cat > "$PROJECT_ROOT/speed.toml" <<'EOF'
test_coverage.patterns = "*Verify.kt=suffix:Verify,*Check.rb=suffix:Check"
EOF

    local stem1
    stem1=$(_test_file_stem "ParserVerify.kt") || {
        echo "    ASSERT: first custom pattern should match" >&2
        return 1
    }
    if [[ "$stem1" != "Parser" ]]; then
        echo "    ASSERT: first stem should be 'Parser', got '${stem1}'" >&2
        return 1
    fi

    local stem2
    stem2=$(_test_file_stem "ValidatorCheck.rb") || {
        echo "    ASSERT: second custom pattern should match" >&2
        return 1
    }
    if [[ "$stem2" != "Validator" ]]; then
        echo "    ASSERT: second stem should be 'Validator', got '${stem2}'" >&2
        return 1
    fi
}

# ══════════════════════════════════════════════════════════════════════════════
# Section 6: End-to-end — grounding_check_test_coverage with Java project
# ══════════════════════════════════════════════════════════════════════════════

test_e2e_java_with_test_passes() {
    git -C "$PROJECT_ROOT" checkout -b "feat/java-e2e" --quiet
    mkdir -p "$PROJECT_ROOT/src/main/java/com/example"
    mkdir -p "$PROJECT_ROOT/src/test/java/com/example"
    echo "class UserService {}" > "$PROJECT_ROOT/src/main/java/com/example/UserService.java"
    echo "class UserServiceTest {}" > "$PROJECT_ROOT/src/test/java/com/example/UserServiceTest.java"
    git -C "$PROJECT_ROOT" add .
    git -C "$PROJECT_ROOT" commit -m "add Java source + test" --quiet

    cat > "${TASKS_DIR}/1.json" <<'EOF'
{
    "id": "1",
    "branch": "feat/java-e2e",
    "description": "java task",
    "files_touched": [
        "src/main/java/com/example/UserService.java",
        "src/test/java/com/example/UserServiceTest.java"
    ]
}
EOF

    local rc=0
    grounding_check_test_coverage "1" || rc=$?

    if [[ $rc -ne 0 ]]; then
        echo "    ASSERT: Java project with test should pass, got exit ${rc}" >&2
        return 1
    fi
}

test_e2e_java_without_test_fails() {
    git -C "$PROJECT_ROOT" checkout -b "feat/java-notest" --quiet
    mkdir -p "$PROJECT_ROOT/src/main/java/com/example"
    echo "class UserService {}" > "$PROJECT_ROOT/src/main/java/com/example/UserService.java"
    git -C "$PROJECT_ROOT" add .
    git -C "$PROJECT_ROOT" commit -m "add Java source only" --quiet

    cat > "${TASKS_DIR}/1.json" <<'EOF'
{
    "id": "1",
    "branch": "feat/java-notest",
    "description": "java task no test",
    "files_touched": ["src/main/java/com/example/UserService.java"]
}
EOF

    local rc=0
    grounding_check_test_coverage "1" || rc=$?

    if [[ $rc -eq 0 ]]; then
        echo "    ASSERT: Java project without test should fail, got exit 0" >&2
        return 1
    fi
}

test_e2e_kotlin_with_test_passes() {
    git -C "$PROJECT_ROOT" checkout -b "feat/kotlin-e2e" --quiet
    mkdir -p "$PROJECT_ROOT/src/main/kotlin"
    mkdir -p "$PROJECT_ROOT/src/test/kotlin"
    echo "class UserService" > "$PROJECT_ROOT/src/main/kotlin/UserService.kt"
    echo "class UserServiceTest" > "$PROJECT_ROOT/src/test/kotlin/UserServiceTest.kt"
    git -C "$PROJECT_ROOT" add .
    git -C "$PROJECT_ROOT" commit -m "add Kotlin source + test" --quiet

    cat > "${TASKS_DIR}/1.json" <<'EOF'
{
    "id": "1",
    "branch": "feat/kotlin-e2e",
    "description": "kotlin task",
    "files_touched": [
        "src/main/kotlin/UserService.kt",
        "src/test/kotlin/UserServiceTest.kt"
    ]
}
EOF

    local rc=0
    grounding_check_test_coverage "1" || rc=$?

    if [[ $rc -ne 0 ]]; then
        echo "    ASSERT: Kotlin project with test should pass, got exit ${rc}" >&2
        return 1
    fi
}

test_e2e_go_with_test_passes() {
    git -C "$PROJECT_ROOT" checkout -b "feat/go-e2e" --quiet
    mkdir -p "$PROJECT_ROOT/pkg/parser"
    echo "package parser" > "$PROJECT_ROOT/pkg/parser/parser.go"
    echo "package parser" > "$PROJECT_ROOT/pkg/parser/parser_test.go"
    git -C "$PROJECT_ROOT" add .
    git -C "$PROJECT_ROOT" commit -m "add Go source + test" --quiet

    cat > "${TASKS_DIR}/1.json" <<'EOF'
{
    "id": "1",
    "branch": "feat/go-e2e",
    "description": "go task",
    "files_touched": [
        "pkg/parser/parser.go",
        "pkg/parser/parser_test.go"
    ]
}
EOF

    local rc=0
    grounding_check_test_coverage "1" || rc=$?

    if [[ $rc -ne 0 ]]; then
        echo "    ASSERT: Go project with test should pass, got exit ${rc}" >&2
        return 1
    fi
}

test_e2e_build_file_only_passes() {
    # Adding only build files should not require tests
    git -C "$PROJECT_ROOT" checkout -b "feat/build-only" --quiet
    echo "<project/>" > "$PROJECT_ROOT/pom.xml"
    echo "module example" > "$PROJECT_ROOT/go.mod"
    git -C "$PROJECT_ROOT" add .
    git -C "$PROJECT_ROOT" commit -m "add build files" --quiet

    cat > "${TASKS_DIR}/1.json" <<'EOF'
{
    "id": "1",
    "branch": "feat/build-only",
    "description": "build files only",
    "files_touched": ["pom.xml", "go.mod"]
}
EOF

    local rc=0
    grounding_check_test_coverage "1" || rc=$?

    if [[ $rc -ne 0 ]]; then
        echo "    ASSERT: build-files-only task should pass, got exit ${rc}" >&2
        return 1
    fi
}

test_e2e_no_branch_fails() {
    # Task with no branch should fail
    cat > "${TASKS_DIR}/1.json" <<'EOF'
{
    "id": "1",
    "description": "no branch task",
    "files_touched": ["src/Foo.java"]
}
EOF

    local rc=0
    grounding_check_test_coverage "1" || rc=$?

    if [[ $rc -eq 0 ]]; then
        echo "    ASSERT: task with no branch should fail, got exit 0" >&2
        return 1
    fi
}

test_e2e_declared_test_missing_from_diff() {
    # Task declares a test file in files_touched but it's not in the diff
    git -C "$PROJECT_ROOT" checkout -b "feat/missing-declared" --quiet
    mkdir -p "$PROJECT_ROOT/src/main/java/com/example"
    echo "class Foo {}" > "$PROJECT_ROOT/src/main/java/com/example/Foo.java"
    git -C "$PROJECT_ROOT" add .
    git -C "$PROJECT_ROOT" commit -m "add source only" --quiet

    cat > "${TASKS_DIR}/1.json" <<'EOF'
{
    "id": "1",
    "branch": "feat/missing-declared",
    "description": "declared test missing",
    "files_touched": [
        "src/main/java/com/example/Foo.java",
        "src/test/java/com/example/FooTest.java"
    ]
}
EOF

    local rc=0
    grounding_check_test_coverage "1" 2>/dev/null || rc=$?

    if [[ $rc -eq 0 ]]; then
        echo "    ASSERT: declared test missing from diff should fail, got exit 0" >&2
        return 1
    fi
}

test_e2e_modified_files_only_passes() {
    # Only modified files (no new files) — should pass without tests
    git -C "$PROJECT_ROOT" checkout -b "feat/modify-only" --quiet
    mkdir -p "$PROJECT_ROOT/src"
    echo "original" > "$PROJECT_ROOT/src/existing.java"
    git -C "$PROJECT_ROOT" add .
    git -C "$PROJECT_ROOT" commit -m "add existing" --quiet
    git -C "$PROJECT_ROOT" checkout main --quiet
    git -C "$PROJECT_ROOT" merge "feat/modify-only" --quiet

    git -C "$PROJECT_ROOT" checkout -b "feat/modify-only-2" --quiet
    echo "modified" > "$PROJECT_ROOT/src/existing.java"
    git -C "$PROJECT_ROOT" add .
    git -C "$PROJECT_ROOT" commit -m "modify existing" --quiet

    cat > "${TASKS_DIR}/1.json" <<'EOF'
{
    "id": "1",
    "branch": "feat/modify-only-2",
    "description": "modify only",
    "files_touched": ["src/existing.java"]
}
EOF

    local rc=0
    grounding_check_test_coverage "1" || rc=$?

    if [[ $rc -ne 0 ]]; then
        echo "    ASSERT: modify-only task should pass (no new files), got exit ${rc}" >&2
        return 1
    fi
}

test_e2e_no_speed_toml() {
    # No speed.toml at all — escape hatches should silently skip
    rm -f "$PROJECT_ROOT/speed.toml"

    git -C "$PROJECT_ROOT" checkout -b "feat/notoml" --quiet
    mkdir -p "$PROJECT_ROOT/src"
    echo "class Bar {}" > "$PROJECT_ROOT/src/Bar.java"
    echo "class BarTest {}" > "$PROJECT_ROOT/src/BarTest.java"
    git -C "$PROJECT_ROOT" add .
    git -C "$PROJECT_ROOT" commit -m "add Bar + test" --quiet

    cat > "${TASKS_DIR}/1.json" <<'EOF'
{
    "id": "1",
    "branch": "feat/notoml",
    "description": "no toml",
    "files_touched": ["src/Bar.java", "src/BarTest.java"]
}
EOF

    local rc=0
    grounding_check_test_coverage "1" || rc=$?

    if [[ $rc -ne 0 ]]; then
        echo "    ASSERT: should work without speed.toml, got exit ${rc}" >&2
        return 1
    fi
}

test_escape_hatch_malformed_pattern() {
    # Malformed custom pattern (no : separator in rule) — should not crash
    cat > "$PROJECT_ROOT/speed.toml" <<'EOF'
test_coverage.patterns = "*Spec.kt=badformat"
EOF

    # Should not crash, should fall through to built-in
    local rc=0
    _test_file_stem "UserServiceSpec.kt" >/dev/null 2>&1 || rc=$?
    # The glob matches but the rule type "badformat" doesn't match suffix/prefix,
    # so it falls through. The function should not crash.

    # Built-in patterns should still work
    local stem
    stem=$(_test_file_stem "UserServiceTest.java") || {
        echo "    ASSERT: built-in should still work after malformed custom pattern" >&2
        return 1
    }
    if [[ "$stem" != "UserService" ]]; then
        echo "    ASSERT: stem should be 'UserService', got '${stem}'" >&2
        return 1
    fi
}

# ══════════════════════════════════════════════════════════════════════════════
# Run all tests
# ══════════════════════════════════════════════════════════════════════════════

echo ""
echo "Grounding test coverage language tests"
echo "──────────────────────────────────────"

echo ""
echo "  _test_file_stem — 20 languages + edge cases"
echo "  ────────────────────────────────────────────"
run_test test_stem_js_ts
run_test test_stem_python
run_test test_stem_go
run_test test_stem_ruby
run_test test_stem_java
run_test test_stem_scala
run_test test_stem_csharp
run_test test_stem_php
run_test test_stem_bash
run_test test_stem_kotlin
run_test test_stem_swift
run_test test_stem_rust
run_test test_stem_dart
run_test test_stem_elixir
run_test test_stem_c
run_test test_stem_cpp
run_test test_stem_lua
run_test test_stem_perl
run_test test_stem_haskell
run_test test_stem_clojure
run_test test_stem_tests_directory
run_test test_stem_edge_cases
run_test test_stem_double_nested_tests_dir

echo ""
echo "  _lang_family — extension mapping"
echo "  ─────────────────────────────────"
run_test test_lang_family_mapping
run_test test_lang_family_with_test_files

echo ""
echo "  _test_file_exists_in_diff — cross-language + edge cases"
echo "  ───────────────────────────────────────────────────────"
run_test test_diff_java_source_matched_by_java_test
run_test test_diff_cross_language_rejection
run_test test_diff_go_source_matched_by_go_test
run_test test_diff_kotlin_matched_by_java_family
run_test test_diff_no_test_file_fails
run_test test_diff_rust_source_matched
run_test test_diff_python_different_directory
run_test test_diff_empty_diff_files
run_test test_diff_elixir_source_matched
run_test test_diff_csharp_source_matched
run_test test_diff_swift_source_matched
run_test test_diff_same_stem_same_family_different_dirs
run_test test_diff_test_file_matches_regardless_of_path

echo ""
echo "  _test_coverage_excluded — build files + overrides"
echo "  ─────────────────────────────────────────────────"
run_test test_excluded_build_files
run_test test_excluded_remaining_build_files
run_test test_excluded_requirements_glob
run_test test_excluded_test_files_all_languages
run_test test_excluded_source_files_not_excluded
run_test test_excluded_test_directories
run_test test_excluded_custom_patterns

echo ""
echo "  Escape hatches — speed.toml overrides"
echo "  ─────────────────────────────────────"
run_test test_skip_escape_hatch
run_test test_skip_false_does_not_skip
run_test test_custom_stem_patterns
run_test test_custom_stem_prefix_rule
run_test test_custom_pattern_fallthrough_to_builtin
run_test test_multiple_custom_patterns
run_test test_escape_hatch_malformed_pattern

echo ""
echo "  End-to-end — grounding_check_test_coverage"
echo "  ──────────────────────────────────────────"
run_test test_e2e_java_with_test_passes
run_test test_e2e_java_without_test_fails
run_test test_e2e_kotlin_with_test_passes
run_test test_e2e_go_with_test_passes
run_test test_e2e_build_file_only_passes
run_test test_e2e_no_branch_fails
run_test test_e2e_declared_test_missing_from_diff
run_test test_e2e_modified_files_only_passes
run_test test_e2e_no_speed_toml

echo ""
echo "──────────────────────────────────────"
echo "Results: ${PASS} passed, ${FAIL} failed"
echo ""

if [[ "$FAIL" -gt 0 ]]; then
    exit 1
fi
