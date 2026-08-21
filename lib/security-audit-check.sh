#!/usr/bin/env bash
# security-audit-check.sh — Audit-time checks for security section presence in spec files.
#
# Separated from security.sh (pipeline-time) because these functions run during
# `speed audit`, not during task execution. Different lifecycle, different callers.
#
# Functions:
#   check_security_section <spec_file>
#   check_security_sections_in_specs <specs_dir>

# ── check_security_section ───────────────────────────────────────
#
# Checks whether a spec file contains a non-empty ## Security section.
#
# Returns:
#   Empty string  — section present with content (success)
#   Warning string — section missing or empty (warning)
#
# Usage: result=$(check_security_section path/to/spec.md)

check_security_section() {
    local spec_file="$1"
    local filename
    filename=$(basename "$spec_file")

    # Check for a heading matching ## Security (case-insensitive).
    # Matches ## Security, ## Security & Controls, ## Security Considerations, etc.
    if ! grep -qi '^## security' "$spec_file" 2>/dev/null; then
        echo "WARN: Missing security section in ${filename}"
        return 0
    fi

    # Heading exists — check whether it has content before the next ## or EOF.
    # Strategy: extract lines between the security heading and the next ## heading (or EOF),
    # then check if any non-blank, non-heading content exists.
    local in_section=false
    local has_content=false

    while IFS= read -r line; do
        if [[ "$in_section" == "false" ]]; then
            # Detect the security heading (case-insensitive)
            if echo "$line" | grep -qi '^## security'; then
                in_section=true
            fi
            continue
        fi

        # We are inside the security section
        # A new ## heading ends the section
        if [[ "$line" =~ ^## ]]; then
            break
        fi

        # Check for non-whitespace content
        if [[ -n "${line// /}" ]] && [[ -n "${line//	/}" ]]; then
            has_content=true
            break
        fi
    done < "$spec_file"

    if [[ "$has_content" == "false" ]]; then
        echo "WARN: Empty security section in ${filename}"
    fi
    # Return empty on success (has_content == true) — no echo needed
}

# ── check_security_sections_in_specs ────────────────────────────
#
# Runs check_security_section on every .md file in a directory.
#
# Usage: warnings=$(check_security_sections_in_specs path/to/specs/)
# Returns a newline-separated list of warnings (empty if all pass).

check_security_sections_in_specs() {
    local specs_dir="$1"
    local warnings=""

    while IFS= read -r -d '' spec_file; do
        local result
        result=$(check_security_section "$spec_file")
        if [[ -n "$result" ]]; then
            if [[ -n "$warnings" ]]; then
                warnings+=$'\n'"$result"
            else
                warnings="$result"
            fi
        fi
    done < <(find "$specs_dir" -name '*.md' -type f -print0 | sort -z)

    echo "$warnings"
}
