#!/usr/bin/env bash
# test_dashboard_health_check.sh — Regression coverage for
# lib/cmd/dashboard.sh's health-check functions.
#
# Code-review finding: _dashboard_api_alive correctly answers "is the
# API alive on *this* port," but a false answer from it is ambiguous
# between "nothing tracked is running" and "something tracked IS alive,
# just not on this port." _dashboard_start used to treat both cases the
# same way and would start a second instance on top of the first,
# overwriting api.pid and orphaning the original process (dashboard
# stop/status can no longer see or stop it). This exercises the two
# health-check functions directly, without starting a real server.
#
# Run: bash tests/test_dashboard_health_check.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEST_DIR=$(mktemp -d "${TMPDIR:-/tmp}/speed-dashboard-health-test-XXXXXX")
PASS=0
FAIL=0
SLEEPER_PID=""

cleanup() {
    [[ -n "$SLEEPER_PID" ]] && kill "$SLEEPER_PID" 2>/dev/null || true
    rm -rf "$TEST_DIR"
}
trap cleanup EXIT

assert_true() {
    local label="$1"
    if "${@:2}"; then
        echo "  PASS: $label"
        ((PASS++)) || true
    else
        echo "  FAIL: $label"
        ((FAIL++)) || true
    fi
}

assert_false() {
    local label="$1"
    if ! "${@:2}"; then
        echo "  PASS: $label"
        ((PASS++)) || true
    else
        echo "  FAIL: $label"
        ((FAIL++)) || true
    fi
}

export SPEED_DIR="$SCRIPT_DIR"
source "$SCRIPT_DIR/lib/colors.sh"
source "$SCRIPT_DIR/lib/log.sh"
source "$SCRIPT_DIR/lib/config.sh"
source "$SCRIPT_DIR/lib/cmd/dashboard.sh"

DASHBOARD_DIR="$TEST_DIR/.dashboard"
mkdir -p "$DASHBOARD_DIR"

echo ""
echo "=== _dashboard_pid_alive_on_a_different_port ==="

# No pidfile at all: nothing tracked, nothing to warn about.
rm -f "$DASHBOARD_DIR/api.pid"
assert_false "no pidfile at all -> false" _dashboard_pid_alive_on_a_different_port 4440

# A stale pidfile pointing at a definitely-dead PID.
echo "999999" > "$DASHBOARD_DIR/api.pid"
assert_false "pidfile present but PID is dead -> false" _dashboard_pid_alive_on_a_different_port 4440

# A genuinely alive process (this test's own sleeper), tracked in
# api.pid: the exact scenario the fix targets — some *other* process is
# alive and tracked, but health-checking it on this port is not this
# function's job (that's _dashboard_api_alive) — it only needs to know
# "is the tracked PID alive at all."
sleep 60 &
SLEEPER_PID=$!
echo "$SLEEPER_PID" > "$DASHBOARD_DIR/api.pid"
assert_true "tracked PID is genuinely alive -> true (regardless of port)" _dashboard_pid_alive_on_a_different_port 4440

echo ""
echo "=== _dashboard_start no longer silently overwrites a live-but-different-port PID ==="

# _dashboard_start must exit (not proceed to spawn a second instance and
# overwrite api.pid) when the tracked PID is alive but not answering on
# the requested port. Run in a subshell so its `exit` doesn't kill this
# test script, and stub out `curl` so _dashboard_api_alive's health
# check always fails (as it would for a real different-port process),
# without needing an actual HTTP server.
start_exit_code=0
(
    curl() { return 1; }
    export -f curl
    _dashboard_start --port 4440 >/dev/null 2>&1
) || start_exit_code=$?
recorded_pid=$(cat "$DASHBOARD_DIR/api.pid" 2>/dev/null)
assert_true "_dashboard_start exits non-zero instead of starting a second instance" [ "$start_exit_code" -ne 0 ]
assert_true "api.pid is untouched — original PID is not orphaned" [ "$recorded_pid" == "$SLEEPER_PID" ]

echo ""
echo "============================================================"
echo "Dashboard Health Check Tests: $PASS passed, $FAIL failed"
if [[ $FAIL -eq 0 ]]; then
    echo "ALL TESTS PASSED"
    exit 0
else
    echo "FAILURES: $FAIL"
    exit 1
fi
