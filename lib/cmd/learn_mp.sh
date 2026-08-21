#!/usr/bin/env bash
# learn_mp.sh — Multi-player knowledge pipeline commands
#
# Provides merge, curate, and pending subcommands for the
# knowledge proposal workflow.
#
# Requires: multiplayer.sh, config.sh, log.sh

# Merge pending proposals into shared knowledge.
cmd_learn_merge() {
    if [[ "${MP_ENABLED:-}" != "true" ]]; then
        log_error "Multi-player mode not enabled. Run 'speed mp-init' first."
        exit 1
    fi

    log_header "Merging Knowledge Proposals"

    local proposals_dir knowledge_dir
    proposals_dir=$(mp_proposals_dir)
    knowledge_dir=$(mp_knowledge_dir)

    local output
    output=$(PYTHONPATH="${SPEED_DIR:-$SCRIPT_DIR}" $(_learn_python) -c "
import sys, os, json
from pathlib import Path
sys.path.insert(0, os.environ.get('SPEED_DIR', '.'))
from lib.learn.merge import merge_proposals

proposals_dir = Path('${proposals_dir}')
knowledge_dir = Path('${knowledge_dir}')

result = merge_proposals(proposals_dir, knowledge_dir)
print(f'PROPOSALS|{result.proposals_processed}')
print(f'MERGED|{result.merged}')
print(f'BUMPED|{result.bumped}')
print(f'CONFLICTED|{result.conflicted}')
print(f'SKIPPED|{result.skipped}')
" 2>&1)

    local rc=$?
    if [[ $rc -ne 0 ]]; then
        log_error "Merge failed:"
        echo "$output" >&2
        return $rc
    fi

    # Parse and display results
    local proposals=0 merged=0 bumped=0 conflicted=0 skipped=0
    while IFS= read -r line; do
        case "$line" in
            PROPOSALS\|*) proposals="${line#PROPOSALS|}" ;;
            MERGED\|*)    merged="${line#MERGED|}" ;;
            BUMPED\|*)    bumped="${line#BUMPED|}" ;;
            CONFLICTED\|*) conflicted="${line#CONFLICTED|}" ;;
            SKIPPED\|*)   skipped="${line#SKIPPED|}" ;;
        esac
    done <<< "$output"

    if [[ $proposals -eq 0 ]]; then
        log_info "No pending proposals to merge."
        return 0
    fi

    log_step "Processed ${proposals} proposal(s)"
    [[ $merged -gt 0 ]] && log_success "${merged} convention(s) auto-merged"
    [[ $bumped -gt 0 ]] && log_info "${bumped} convention(s) confidence bumped"
    [[ $conflicted -gt 0 ]] && log_warn "${conflicted} conflict(s) written to shared/knowledge/conflicts.json"
    [[ $skipped -gt 0 ]] && log_info "${skipped} locked convention(s) skipped"
    echo ""
}

# Show conflicts and prompt for resolution.
cmd_learn_curate() {
    if [[ "${MP_ENABLED:-}" != "true" ]]; then
        log_error "Multi-player mode not enabled. Run 'speed mp-init' first."
        exit 1
    fi

    local knowledge_dir
    knowledge_dir=$(mp_knowledge_dir)
    local conflicts_file="${knowledge_dir}/conflicts.json"

    if [[ ! -f "$conflicts_file" ]]; then
        log_info "No conflicts to curate."
        return 0
    fi

    local count
    count=$(jq 'length' "$conflicts_file" 2>/dev/null)
    if [[ "$count" -eq 0 ]]; then
        log_info "No conflicts to curate."
        return 0
    fi

    log_header "Knowledge Conflicts (${count})"
    echo ""

    local i=0
    while [[ $i -lt $count ]]; do
        local key existing proposed
        key=$(jq -r ".[$i].key" "$conflicts_file")
        existing=$(jq -c ".[$i].existing" "$conflicts_file")
        proposed=$(jq -c ".[$i].proposed" "$conflicts_file")

        echo -e "  ${BOLD}Conflict ${i}:${RESET} ${key}"
        if [[ "$existing" != "null" ]]; then
            echo -e "  ${COLOR_DIM}Existing:${RESET} $(echo "$existing" | jq -r '.value // .description // "?"')"
        fi
        echo -e "  ${COLOR_WARN}Proposed:${RESET}"
        echo "$proposed" | jq -r '.[] | "    - \(.value // .description // "?")"' 2>/dev/null

        echo ""
        local choice
        read -r -p "  Keep [e]xisting, accept [p]roposed, [s]kip? " choice </dev/tty || choice="s"
        case "$choice" in
            e|E)
                log_step "Keeping existing, locking convention"
                # Lock the existing entry
                local convs_file="${knowledge_dir}/conventions.json"
                if [[ -f "$convs_file" ]]; then
                    local tmp; tmp=$(mktemp)
                    jq --arg key "$key" \
                        '(.conventions[] | select((.key // .pattern // .name) == $key)).confidence = "locked"' \
                        "$convs_file" > "$tmp" && mv "$tmp" "$convs_file"
                fi
                ;;
            p|P)
                log_step "Accepting proposed, locking convention"
                local convs_file="${knowledge_dir}/conventions.json"
                local new_val
                new_val=$(echo "$proposed" | jq '.[0]')
                if [[ -f "$convs_file" ]]; then
                    local tmp; tmp=$(mktemp)
                    jq --arg key "$key" --argjson newval "$new_val" \
                        'if (.conventions | map(select((.key // .pattern // .name) == $key)) | length) > 0
                         then (.conventions[] | select((.key // .pattern // .name) == $key)) |= ($newval + {confidence: "locked"})
                         else .conventions += [$newval + {confidence: "locked"}]
                         end' \
                        "$convs_file" > "$tmp" && mv "$tmp" "$convs_file"
                fi
                ;;
            *)
                log_info "Skipped"
                ;;
        esac
        echo ""
        ((i++)) || true
    done

    # Clear resolved conflicts
    echo "[]" > "$conflicts_file"
    log_success "Curation complete"
}

# List pending proposals.
cmd_learn_pending() {
    if [[ "${MP_ENABLED:-}" != "true" ]]; then
        log_error "Multi-player mode not enabled. Run 'speed mp-init' first."
        exit 1
    fi

    local proposals_dir
    proposals_dir=$(mp_proposals_dir)
    [[ -d "$proposals_dir" ]] || { log_info "No proposals directory."; return 0; }

    log_header "Pending Knowledge Proposals"

    local count=0
    for f in "${proposals_dir}"/*.json; do
        [[ -f "$f" ]] || continue
        local status
        status=$(jq -r '.status // "unknown"' "$f" 2>/dev/null)
        if [[ "$status" == "pending" ]]; then
            local actor feature ts obs_count conv_count
            actor=$(jq -r '.actor // "?"' "$f")
            feature=$(jq -r '.feature // "?"' "$f")
            ts=$(jq -r '.timestamp // "?"' "$f")
            obs_count=$(jq '.observations | length' "$f" 2>/dev/null || echo 0)
            conv_count=$(jq '.conventions | length' "$f" 2>/dev/null || echo 0)
            echo -e "  ${COLOR_STEP}$(basename "$f")${RESET}"
            echo -e "    Actor: ${actor} | Feature: ${feature} | ${obs_count} obs, ${conv_count} conv | ${ts}"
            ((count++)) || true
        fi
    done

    if [[ $count -eq 0 ]]; then
        log_info "No pending proposals."
    else
        echo ""
        log_info "${count} pending proposal(s). Run 'speed learn --merge' to process."
    fi
}
