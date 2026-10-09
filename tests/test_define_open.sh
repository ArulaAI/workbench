#!/usr/bin/env bash
# The Define findings route opens with the platform-native browser launcher.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT/lib/cmd/define.sh"

TMP=$(mktemp -d)
trap 'rm -f "$TMP/args"; rmdir "$TMP"' EXIT
URL="http://localhost:3000/define/payments/findings"

uname() { echo "MINGW64_NT"; }
cmd.exe() { printf '%s\n' "$@" > "$TMP/args"; }
_define_open_url "$URL"
[[ "$(paste -sd ' ' "$TMP/args")" == "/c start  $URL" ]]

uname() { echo "Darwin"; }
open() { printf '%s\n' "$@" > "$TMP/args"; }
_define_open_url "$URL"
[[ "$(cat "$TMP/args")" == "$URL" ]]

uname() { echo "Linux"; }
xdg-open() { printf '%s\n' "$@" > "$TMP/args"; }
_define_open_url "$URL"
[[ "$(cat "$TMP/args")" == "$URL" ]]

echo "PASS: Define uses the native findings-route browser launcher"
