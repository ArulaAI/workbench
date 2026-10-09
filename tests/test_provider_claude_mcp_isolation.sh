#!/usr/bin/env bash
# Verifies that schema-bound, tool-free Claude calls do not inherit personal
# or account-level MCP servers.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

export LOGS_DIR="$TMP/logs"
mkdir -p "$LOGS_DIR"
export AGENT_FILE_PATH=""
export MODEL_SUPPORT="sonnet"
export DEFAULT_JSON_MAX_TURNS=1
export DEFAULT_MAX_TURNS=1
export DEFAULT_AGENT_TIMEOUT=30
export AGENT_KILL_GRACE=1
export CLAUDE_BIN="claude"

log_error() { :; }
log_warn() { :; }
require_timeout_cmd() { return 0; }

# shellcheck disable=SC1091
source "$ROOT/providers/claude-code.sh"

CAPTURE="$TMP/args.txt"
_resolve_claude_effort() { echo ""; }
_provider_stream_exec() {
    printf '%s\n' "$@" > "$CAPTURE"
    : > "$2"
    echo '{"ok":true}'
}

echo "system" > "$TMP/system.md"
echo '{"type":"object"}' > "$TMP/schema.json"

provider_run "$TMP/system.md" "message" "sonnet" "Read" "Verifier" >/dev/null
grep -Fx -- "--tools" "$CAPTURE" >/dev/null
grep -Fx -- "--allowedTools" "$CAPTURE" >/dev/null
grep -Fx -- "--strict-mcp-config" "$CAPTURE" >/dev/null
grep -Fx -- "--mcp-config" "$CAPTURE" >/dev/null
grep -Fx -- '{"mcpServers":{}}' "$CAPTURE" >/dev/null
if grep -Fx -- "bypassPermissions" "$CAPTURE" >/dev/null; then
    echo "provider_run must not bypass all permission checks" >&2
    exit 1
fi

provider_run_json "$TMP/system.md" "message" "$TMP/schema.json" \
    "sonnet" 1 "" "Architect" >/dev/null

grep -Fx -- "--tools" "$CAPTURE" >/dev/null
grep -Fx -- "--strict-mcp-config" "$CAPTURE" >/dev/null
grep -Fx -- "--mcp-config" "$CAPTURE" >/dev/null
grep -Fx -- '{"mcpServers":{}}' "$CAPTURE" >/dev/null

provider_run_json "$TMP/system.md" "message" "$TMP/schema.json" \
    "sonnet" 1 "Read" "Reader" >/dev/null

grep -Fx -- "--strict-mcp-config" "$CAPTURE" >/dev/null
grep -Fx -- "--mcp-config" "$CAPTURE" >/dev/null
grep -Fx -- '{"mcpServers":{}}' "$CAPTURE" >/dev/null
grep -Fx -- "--allowedTools" "$CAPTURE" >/dev/null
if grep -Fx -- "bypassPermissions" "$CAPTURE" >/dev/null; then
    echo "provider_run_json must not bypass all permission checks" >&2
    exit 1
fi

echo "PASS: Claude calls isolate MCP configuration and restrict/preauthorize only the requested tools"
