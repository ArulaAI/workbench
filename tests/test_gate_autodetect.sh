#!/usr/bin/env bash
# Standard Node projects expose npm test as the Run-stage test gate.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP=$(mktemp -d)
trap 'rm -f "$TMP/package.json"; rmdir "$TMP"' EXIT

# shellcheck disable=SC1091
source "$ROOT/lib/gates.sh"

[[ -z "$(_gates_default_test_command "$TMP")" ]]

cat > "$TMP/package.json" <<'EOF'
{"scripts":{"test":"node --test"}}
EOF

[[ "$(_gates_default_test_command "$TMP")" == "npm test" ]]

cat > "$TMP/package.json" <<'EOF'
{"scripts":{"build":"node build.js"}}
EOF

[[ -z "$(_gates_default_test_command "$TMP")" ]]
echo "PASS: Run gate auto-detects only a declared package.json test script"
