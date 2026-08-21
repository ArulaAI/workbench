#!/usr/bin/env bash
# multiplayer.sh — Multi-player mode detection and path helpers
#
# Multi-player mode is enabled when .speed/shared/ exists (created by mp-init).
# All path helpers return absolute paths rooted in STATE_DIR.
#
# Requires: config.sh

# Check whether multi-player mode is active.
# Returns 0 if enabled, 1 if not.
mp_is_enabled() {
    [[ -d "${STATE_DIR}/shared" ]]
}

# ── Path helpers ──────────────────────────────────────────────────

mp_shared_dir()     { echo "${STATE_DIR}/shared"; }
mp_local_dir()      { echo "${STATE_DIR}/local"; }
mp_events_dir()     { echo "${STATE_DIR}/shared/events"; }
mp_roster_dir()     { echo "${STATE_DIR}/shared/roster"; }
mp_proposals_dir()  { echo "${STATE_DIR}/shared/proposals"; }
mp_knowledge_dir()  { echo "${STATE_DIR}/shared/knowledge"; }
