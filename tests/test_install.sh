#!/usr/bin/env bash
#
# test_install.sh — End-to-end tests for install, self-update, and self-uninstall
#
# Runs inside a Docker container for full isolation. No changes to the host.
#
# Usage:
#   bash tests/test_install.sh          # Build image + run all tests
#   bash tests/test_install.sh --shell  # Drop into the container for manual testing
#
# Requirements: docker

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPEED_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
IMAGE_NAME="speed-install-test"
CONTAINER_NAME="speed-install-test-$$"

# ── Colors ─────────────────────────────────────────────────────

BOLD='\033[1m'
RESET='\033[0m'

info() { printf "${BOLD}==> %s${RESET}\n" "$*"; }

# ── Docker Setup ───────────────────────────────────────────────

build_image() {
    info "Building test image..."

    local build_dir
    build_dir=$(mktemp -d "${TMPDIR:-/tmp}/speed-test-build-XXXXXX")

    cat > "${build_dir}/Dockerfile" <<'DOCKERFILE'
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV HOME=/root

RUN apt-get update && apt-get install -y \
    bash \
    curl \
    git \
    jq \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN git config --global user.email "test@test.com" && \
    git config --global user.name "Test" && \
    git config --global init.defaultBranch main

WORKDIR /test
DOCKERFILE

    docker build -t "$IMAGE_NAME" "$build_dir" 2>/dev/null
    rm -rf "$build_dir"
}

# ── Main ──────────────────────────────────────────────────────

main() {
    local mode="${1:-test}"

    info "SPEED Install Test Suite"
    echo ""

    if ! command -v docker &>/dev/null; then
        echo "Error: docker is required to run these tests."
        exit 1
    fi

    build_image

    case "$mode" in
        --shell)
            info "Dropping into container shell..."
            info "SPEED source mounted at /speed-src (read-only)"
            info "Test script mounted at /test/run_tests.sh"
            docker run -it --rm \
                -v "${SPEED_ROOT}:/speed-src:ro" \
                -v "${SCRIPT_DIR}/test_install_inner.sh:/test/run_tests.sh:ro" \
                "$IMAGE_NAME" \
                bash
            ;;
        *)
            info "Running tests in container..."
            echo ""
            if docker run --rm \
                --name "$CONTAINER_NAME" \
                -v "${SPEED_ROOT}:/speed-src:ro" \
                -v "${SCRIPT_DIR}/test_install_inner.sh:/test/run_tests.sh:ro" \
                -e "TERM=dumb" \
                "$IMAGE_NAME" \
                bash /test/run_tests.sh; then
                echo ""
                info "All tests passed."
            else
                echo ""
                info "Some tests failed."
                exit 1
            fi
            ;;
    esac
}

main "$@"
