#!/usr/bin/env bash
# test_lock_regressions.sh — Tests for stale-lock breaking in lib/lock.sh
#
# Breaking a lock is inspect-then-remove. A plain rm -rf between those two
# steps let two waiters both remove the lock, so the second deleted a lock the
# first had already re-acquired, and two processes ran checkout + merge on main
# at the same time.
#
# Usage: bash tests/test_lock_regressions.sh
# Exit: 0 if all tests pass, 1 if any fail
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPEED_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PASS=0
FAIL=0
TEST_DIR=""

setup() {
    TEST_DIR=$(mktemp -d)
    STATE_DIR="${TEST_DIR}/.speed"
    LOCAL_DIR="$STATE_DIR"
    mkdir -p "$STATE_DIR"
    log_warn()  { echo "WARN: $*"; }
    log_error() { echo "ERROR: $*"; }
    log_step()  { echo "STEP: $*"; }
    actor_get() { echo "tester"; }
    # shellcheck source=/dev/null
    source "${SPEED_DIR}/lib/lock.sh"
}

teardown() {
    [[ -n "$TEST_DIR" && -d "$TEST_DIR" ]] && rm -rf "$TEST_DIR"
    return 0
}

assert_equals() {
    if [[ "$1" != "$2" ]]; then
        echo "expected '$1', got '$2'" >&2
        return 1
    fi
}

run_test() {
    local name="$1"
    setup
    local rc
    set +e
    (set -e; "$name")
    rc=$?
    set -e
    if [[ $rc -eq 0 ]]; then
        echo "PASS $name"
        PASS=$((PASS + 1))
    else
        echo "FAIL $name"
        FAIL=$((FAIL + 1))
    fi
    teardown
}

# ── main-branch lock ─────────────────────────────────────────

test_empty_main_lock_is_not_removed_while_its_owner_initializes() {
    # The owner is between mkdir and writing pid. Removing the lock here let a
    # second process acquire it and merge into main concurrently.
    mkdir -p "$MAIN_BRANCH_LOCK"

    local rc=0
    _lock_break "$MAIN_BRANCH_LOCK" _lock_never_initialized || rc=$?

    assert_equals "1" "$rc"
    [[ -d "$MAIN_BRANCH_LOCK" ]]
}

test_long_abandoned_empty_main_lock_is_removed() {
    # A process that died inside that window must not wedge the lock forever.
    mkdir -p "$MAIN_BRANCH_LOCK"
    touch -t 200001010000 "$MAIN_BRANCH_LOCK"

    _lock_break "$MAIN_BRANCH_LOCK" _lock_never_initialized
    [[ ! -d "$MAIN_BRANCH_LOCK" ]]
}

test_main_lock_held_by_a_live_process_is_never_broken() {
    mkdir -p "$MAIN_BRANCH_LOCK"
    echo $$ > "${MAIN_BRANCH_LOCK}/pid"

    local rc=0
    _lock_break "$MAIN_BRANCH_LOCK" _lock_holder_still_dead || rc=$?

    assert_equals "1" "$rc"
    [[ -d "$MAIN_BRANCH_LOCK" ]]
}

test_main_lock_left_by_a_dead_process_is_broken() {
    mkdir -p "$MAIN_BRANCH_LOCK"
    # PID 2^22 is above every configured pid_max and owns nothing.
    echo 4194303 > "${MAIN_BRANCH_LOCK}/pid"

    _lock_break "$MAIN_BRANCH_LOCK" _lock_holder_still_dead
    [[ ! -d "$MAIN_BRANCH_LOCK" ]]
}

# ── the race itself ──────────────────────────────────────────

test_only_one_waiter_may_break_a_lock_at_a_time() {
    mkdir -p "$MAIN_BRANCH_LOCK"
    echo 4194303 > "${MAIN_BRANCH_LOCK}/pid"
    # Stand in for a waiter that has already won the right to break.
    mkdir "${MAIN_BRANCH_LOCK}.breaking"

    local rc=0
    _lock_break "$MAIN_BRANCH_LOCK" _lock_holder_still_dead || rc=$?

    assert_equals "1" "$rc"
    [[ -d "$MAIN_BRANCH_LOCK" ]]
}

test_breaker_does_not_delete_a_lock_reacquired_since_it_looked() {
    # The waiter saw a dead holder, then another process broke the lock and
    # took it. Re-reading pid after winning the guard is what stops the
    # breaker from deleting a live lock.
    mkdir -p "$MAIN_BRANCH_LOCK"
    echo $$ > "${MAIN_BRANCH_LOCK}/pid"

    local rc=0
    _lock_break "$MAIN_BRANCH_LOCK" _lock_holder_still_dead || rc=$?

    assert_equals "1" "$rc"
    assert_equals "$$" "$(cat "${MAIN_BRANCH_LOCK}/pid")"
}

test_breaking_guard_is_released_for_the_next_waiter() {
    mkdir -p "$MAIN_BRANCH_LOCK"
    echo 4194303 > "${MAIN_BRANCH_LOCK}/pid"

    _lock_break "$MAIN_BRANCH_LOCK" _lock_holder_still_dead
    [[ ! -d "${MAIN_BRANCH_LOCK}.breaking" ]]
}

test_interrupted_breaker_releases_guard_and_preserves_callers_trap() {
    interrupt_breaker() {
        local breaker_pid
        breaker_pid=$(cat "${MAIN_BRANCH_LOCK}.breaking"/owner.*)
        kill -s "$signal" "$breaker_pid"
    }
    trap ':' INT TERM
    local previous signal expected rc
    previous=$(trap -p INT TERM)
    for signal in INT TERM; do
        mkdir -p "$MAIN_BRANCH_LOCK"
        echo 4194303 > "${MAIN_BRANCH_LOCK}/pid"
        expected=130
        [[ "$signal" == INT ]] || expected=143
        rc=0
        _lock_break "$MAIN_BRANCH_LOCK" interrupt_breaker || rc=$?
        assert_equals "$expected" "$rc"
        assert_equals "$previous" "$(trap -p INT TERM)"
        [[ ! -d "${MAIN_BRANCH_LOCK}.breaking" ]]
        _lock_break "$MAIN_BRANCH_LOCK" _lock_holder_still_dead
        [[ ! -d "$MAIN_BRANCH_LOCK" ]]
    done
}

test_killed_breaker_is_recovered_on_retry() {
    mkdir -p "$MAIN_BRANCH_LOCK"
    echo 4194303 > "${MAIN_BRANCH_LOCK}/pid"
    kill_breaker() { kill -s KILL "$(cat "${MAIN_BRANCH_LOCK}.breaking"/owner.*)"; }
    local rc=0
    _lock_break "$MAIN_BRANCH_LOCK" kill_breaker 2>/dev/null || rc=$?
    assert_equals "137" "$rc"
    [[ -d "${MAIN_BRANCH_LOCK}.breaking" ]]
    _lock_break "$MAIN_BRANCH_LOCK" _lock_holder_still_dead
    [[ ! -d "$MAIN_BRANCH_LOCK" && ! -d "${MAIN_BRANCH_LOCK}.breaking" ]]
}

test_dead_breaker_before_pid_write_is_recovered_after_grace() {
    mkdir -p "$MAIN_BRANCH_LOCK" "${MAIN_BRANCH_LOCK}.breaking"
    echo 4194303 > "${MAIN_BRANCH_LOCK}/pid"
    touch -t 200001010000 "${MAIN_BRANCH_LOCK}.breaking/owner.empty"
    _lock_break "$MAIN_BRANCH_LOCK" _lock_holder_still_dead
    [[ ! -d "$MAIN_BRANCH_LOCK" && ! -d "${MAIN_BRANCH_LOCK}.breaking" ]]
}

test_dead_breaker_marker_is_recovered_without_manual_force() {
    mkdir -p "$MAIN_BRANCH_LOCK" "${MAIN_BRANCH_LOCK}.breaking"
    echo 4194303 > "${MAIN_BRANCH_LOCK}/pid"
    echo 4194303 > "${MAIN_BRANCH_LOCK}.breaking/owner.abandoned"
    _lock_break "$MAIN_BRANCH_LOCK" _lock_holder_still_dead
    [[ ! -d "$MAIN_BRANCH_LOCK" && ! -d "${MAIN_BRANCH_LOCK}.breaking" ]]
}

test_aged_live_breaker_is_not_stolen() {
    mkdir -p "$MAIN_BRANCH_LOCK" "${MAIN_BRANCH_LOCK}.breaking"
    echo 4194303 > "${MAIN_BRANCH_LOCK}/pid"
    echo $$ > "${MAIN_BRANCH_LOCK}.breaking/owner.live"
    touch -t 200001010000 "${MAIN_BRANCH_LOCK}.breaking"
    local rc=0
    _lock_break "$MAIN_BRANCH_LOCK" _lock_holder_still_dead || rc=$?
    assert_equals "1" "$rc"
    [[ -d "$MAIN_BRANCH_LOCK" ]]
}

test_abandoned_legacy_guard_recovers() {
    mkdir -p "$MAIN_BRANCH_LOCK" "${MAIN_BRANCH_LOCK}.breaking"
    echo 4194303 > "${MAIN_BRANCH_LOCK}/pid"
    touch -t 200001010000 "${MAIN_BRANCH_LOCK}.breaking"
    _lock_break "$MAIN_BRANCH_LOCK" _lock_holder_still_dead
    [[ ! -d "$MAIN_BRANCH_LOCK" && ! -d "${MAIN_BRANCH_LOCK}.breaking" ]]
}

# ── speed lock ───────────────────────────────────────────────

test_speed_lock_acquires_and_releases() {
    speed_acquire_lock "eval"
    assert_equals "$$" "$(cat "${SPEED_LOCK}/pid")"
    speed_release_lock
    [[ ! -d "$SPEED_LOCK" ]]
}

test_speed_lock_refuses_while_a_live_process_holds_it() {
    mkdir -p "$SPEED_LOCK"
    echo $$ > "${SPEED_LOCK}/pid"
    echo "merge" > "${SPEED_LOCK}/command"

    local rc=0
    speed_acquire_lock "eval" >/dev/null 2>&1 || rc=$?

    assert_equals "1" "$rc"
    assert_equals "$$" "$(cat "${SPEED_LOCK}/pid")"
}

test_speed_lock_breaks_a_dead_holder_and_takes_over() {
    mkdir -p "$SPEED_LOCK"
    echo 4194303 > "${SPEED_LOCK}/pid"
    echo "merge" > "${SPEED_LOCK}/command"

    speed_acquire_lock "eval" >/dev/null 2>&1
    assert_equals "$$" "$(cat "${SPEED_LOCK}/pid")"
}

test_force_break_clears_a_wedged_breaking_guard() {
    # A breaker that died mid-break would otherwise leave nobody able to
    # break a stale lock again.
    mkdir -p "${SPEED_LOCK}.breaking" "${MAIN_BRANCH_LOCK}.breaking"

    speed_force_break_lock >/dev/null 2>&1

    [[ ! -d "${SPEED_LOCK}.breaking" ]]
    [[ ! -d "${MAIN_BRANCH_LOCK}.breaking" ]]
}

test_main_branch_acquire_waits_out_an_initializing_owner() {
    # Exercises the public entry point. The old code removed any empty lock
    # and acquired immediately, so two processes could both be inside the
    # main-branch critical section.
    MAIN_LOCK_MAX_WAIT=2
    mkdir -p "$MAIN_BRANCH_LOCK"

    local rc=0
    main_branch_acquire_lock "merge" >/dev/null 2>&1 || rc=$?

    assert_equals "1" "$rc"
    [[ ! -f "${MAIN_BRANCH_LOCK}/pid" ]]
}

run_test test_main_branch_acquire_waits_out_an_initializing_owner
run_test test_empty_main_lock_is_not_removed_while_its_owner_initializes
run_test test_long_abandoned_empty_main_lock_is_removed
run_test test_main_lock_held_by_a_live_process_is_never_broken
run_test test_main_lock_left_by_a_dead_process_is_broken
run_test test_only_one_waiter_may_break_a_lock_at_a_time
run_test test_breaker_does_not_delete_a_lock_reacquired_since_it_looked
run_test test_breaking_guard_is_released_for_the_next_waiter
run_test test_interrupted_breaker_releases_guard_and_preserves_callers_trap
run_test test_killed_breaker_is_recovered_on_retry
run_test test_dead_breaker_before_pid_write_is_recovered_after_grace
run_test test_dead_breaker_marker_is_recovered_without_manual_force
run_test test_aged_live_breaker_is_not_stolen
run_test test_abandoned_legacy_guard_recovers
run_test test_speed_lock_acquires_and_releases
run_test test_speed_lock_refuses_while_a_live_process_holds_it
run_test test_speed_lock_breaks_a_dead_holder_and_takes_over
run_test test_force_break_clears_a_wedged_breaking_guard

echo "${PASS} passed, ${FAIL} failed"
[[ $FAIL -eq 0 ]]
