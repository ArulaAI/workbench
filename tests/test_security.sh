#!/usr/bin/env bash
# test_security.sh — Runs security parse tests and cmd_security tests

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

bash "${SCRIPT_DIR}/test_security_parse.sh" "$@"
bash "${SCRIPT_DIR}/test_security_cmd.sh" "$@"
