#!/usr/bin/env bash
# Build tree-sitter grammar shared libraries for ast-grep custom languages.
#
# Produces platform-native shared libraries in lib/context/data/grammars/:
#   macOS   -> .dylib
#   Linux   -> .so
#   Windows -> .dll
#
# Prerequisites:
#   - tree-sitter CLI (npm install -g tree-sitter-cli  OR  cargo install tree-sitter-cli)
#   - git
#
# Usage:
#   ./scripts/build-grammars.sh             # build all
#   ./scripts/build-grammars.sh prisma      # build one
#   ./scripts/build-grammars.sh --clean     # delete existing, then rebuild

set -euo pipefail

GRAMMAR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/lib/context/data/grammars"
WORK_DIR=$(mktemp -d)
trap 'rm -rf "$WORK_DIR"' EXIT

# Grammar repos (parallel arrays — no associative arrays, Bash 3.2 compatible)
NAMES=(prisma graphql protobuf zig)
REPOS=(
    "https://github.com/victorhqc/tree-sitter-prisma.git"
    "https://github.com/bkegley/tree-sitter-graphql.git"
    "https://github.com/Clement-Jean/tree-sitter-proto.git"
    "https://github.com/tree-sitter-grammars/tree-sitter-zig.git"
)

case "$(uname -s)" in
    Darwin)              EXT="dylib" ;;
    Linux)               EXT="so" ;;
    MINGW*|MSYS*|CYGWIN*) EXT="dll" ;;
    *)                   echo "Unsupported platform: $(uname -s)"; exit 1 ;;
esac

get_repo() {
    local name="$1"
    for i in "${!NAMES[@]}"; do
        if [[ "${NAMES[$i]}" == "$name" ]]; then
            echo "${REPOS[$i]}"
            return
        fi
    done
    echo "Unknown grammar: $name (available: ${NAMES[*]})" >&2
    exit 1
}

build_one() {
    local name="$1"
    local repo
    repo=$(get_repo "$name")
    local out="$GRAMMAR_DIR/${name}.${EXT}"

    printf "  %s: cloning..." "$name"
    git clone --depth 1 --quiet "$repo" "$WORK_DIR/$name"
    printf " building..."
    tree-sitter build --output "$out" "$WORK_DIR/$name"
    printf " OK (%s)\n" "$(du -h "$out" | cut -f1 | xargs)"
}

# Check prerequisites
command -v tree-sitter >/dev/null 2>&1 || {
    echo "tree-sitter CLI not found. Install with:"
    echo "  npm install -g tree-sitter-cli"
    echo "  cargo install tree-sitter-cli"
    exit 1
}
command -v git >/dev/null 2>&1 || { echo "git not found."; exit 1; }

# Parse args
CLEAN=false
TARGETS=()
for arg in "$@"; do
    if [[ "$arg" == "--clean" ]]; then
        CLEAN=true
    else
        TARGETS+=("$arg")
    fi
done
[[ ${#TARGETS[@]} -eq 0 ]] && TARGETS=("${NAMES[@]}")

mkdir -p "$GRAMMAR_DIR"

if $CLEAN; then
    for f in "$GRAMMAR_DIR"/*."$EXT"; do
        [[ -f "$f" ]] && rm "$f" && echo "  Removed $f"
    done
fi

echo "Building ${#TARGETS[@]} grammar(s) for $(uname -s)/$(uname -m):"
echo ""

for name in "${TARGETS[@]}"; do
    build_one "$name"
done

echo ""
echo "Done. Output: $GRAMMAR_DIR/"
