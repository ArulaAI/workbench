#!/usr/bin/env bash
# hello.sh — `workbench hello` platform proof command.
#
# Thin adapter: it owns argument transport only and executes the ONE canonical
# helper (skills/workbench-hello/scripts/hello.py) through the skills engine.
# It contains no greeting string, name default, or validator of its own.

cmd_hello() {
    _speed_alias_notice hello
    PYTHONPATH="${SPEED_DIR}/lib" "$(_skills_python)" -m skills hello \
        --skills-dir "${SPEED_DIR}/skills" \
        --catalog-version "$(_skills_catalog_version)" \
        --surface workbench-cli \
        "$@"
}
