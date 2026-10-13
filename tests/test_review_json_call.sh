#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

export PROJECT_ROOT="$TMP/project"
export TASKS_DIR="$PROJECT_ROOT/tasks"
export LOGS_DIR="$PROJECT_ROOT/logs"
export FEATURE_DIR="$PROJECT_ROOT/feature"
export AGENTS_DIR="$ROOT/agents"
export TEMPLATES_DIR="$ROOT/templates"
export MODEL_SUPPORT="sonnet"
export DEFAULT_MAX_TURNS=50
export AGENT_TOOLS_READONLY="Read Glob Grep"
export EXIT_CONFIG_ERROR=3
mkdir -p "$TASKS_DIR" "$LOGS_DIR"

git -C "$PROJECT_ROOT" init -q
git -C "$PROJECT_ROOT" config user.email test@example.com
git -C "$PROJECT_ROOT" config user.name "Review Test"
touch "$PROJECT_ROOT/README.md"
git -C "$PROJECT_ROOT" add README.md
git -C "$PROJECT_ROOT" commit -q -m baseline
git -C "$PROJECT_ROOT" branch -M main
git -C "$PROJECT_ROOT" branch round-0
printf '%s\n' '{"branch":"round-0","author_model":"sonnet"}' > "$TASKS_DIR/1.json"

git_main_branch() { echo main; }
git_branch_exists() { git -C "$PROJECT_ROOT" rev-parse --verify "$1" >/dev/null 2>&1; }
_git() { git -C "$PROJECT_ROOT" "$@"; }
shasum() { shift 2; sha256sum "$@"; }
log_error() { :; }
_call_with_retry() {
    printf '%s\n' "$1" "$4" "$5" "$6" "$7" "$8" > "$TMP/call-args"
    printf '%s\n' "$SPEED_PROVIDER_EVENTS_FILE" > "$TMP/events-path"
    return 1
}

source "$ROOT/lib/cmd/review.sh"
rc=0
(_cmd_review_task 1) || rc=$?
[[ "$rc" -eq "$EXIT_CONFIG_ERROR" ]]
[[ "$(sed -n '1p' "$TMP/call-args")" == provider_run_json ]]
[[ "$(sed -n '2p' "$TMP/call-args")" == "$TEMPLATES_DIR/clean-review-output.json" ]]
[[ "$(sed -n '3p' "$TMP/call-args")" == "$MODEL_SUPPORT" ]]
[[ "$(sed -n '4p' "$TMP/call-args")" == "$DEFAULT_MAX_TURNS" ]]
[[ "$(sed -n '5p' "$TMP/call-args")" == "$AGENT_TOOLS_READONLY" ]]
[[ "$(sed -n '6p' "$TMP/call-args")" == Reviewer ]]
[[ -f "$(cat "$TMP/events-path")" ]]

echo "PASS: task review calls schema-bound provider with its evidence log"
