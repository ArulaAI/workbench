#!/usr/bin/env bash
# learn.sh — Observation extraction and synthesis command

cmd_learn() {
    local summary_mode=false
    local synthesize_mode=false
    local post_merge_mode=false
    local dry_run=false
    local conventions_mode=false
    local seed_knowledge_mode=false
    local merge_mode=false
    local curate_mode=false
    local pending_mode=false
    local prune_mode=false

    # Parse flags
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --summary)         summary_mode=true; shift ;;
            --synthesize)      synthesize_mode=true; shift ;;
            --post-merge)      post_merge_mode=true; shift ;;
            --dry-run)         dry_run=true; shift ;;
            --conventions)     conventions_mode=true; shift ;;
            --seed-knowledge)  seed_knowledge_mode=true; shift ;;
            --merge)           merge_mode=true; shift ;;
            --curate)          curate_mode=true; shift ;;
            --pending)         pending_mode=true; shift ;;
            --prune)           prune_mode=true; shift ;;
            *) log_error "Unknown option: $1"; exit 1 ;;
        esac
    done

    # Multi-player knowledge pipeline commands
    if [[ "$merge_mode" == true ]]; then
        cmd_learn_merge
        return $?
    fi
    if [[ "$curate_mode" == true ]]; then
        cmd_learn_curate
        return $?
    fi
    if [[ "$pending_mode" == true ]]; then
        cmd_learn_pending
        return $?
    fi
    if [[ "$prune_mode" == true ]]; then
        if [[ "${MP_ENABLED:-}" != "true" ]]; then
            log_error "Event pruning requires multi-player mode. Run 'speed mp-init' first."
            exit 1
        fi
        event_prune "${TOML_MULTIPLAYER_PRUNE_DAYS:-30}"
        return $?
    fi

    local memory_dir="${STATE_DIR}/memory"
    [[ "${MP_ENABLED:-}" == "true" ]] && memory_dir="$(mp_knowledge_dir)"

    # Conventions mode: run convention discovery pipeline
    if [[ "$conventions_mode" == true ]]; then
        log_header "Convention Discovery"
        if learn_conventions; then
            return 0
        else
            return 1
        fi
    fi

    # Seed knowledge mode: generate draft project knowledge entries
    if [[ "$seed_knowledge_mode" == true ]]; then
        log_header "Project Knowledge Seed"
        if learn_seed_knowledge; then
            return 0
        else
            return 1
        fi
    fi

    # Summary mode: aggregate stats across all features
    if [[ "$summary_mode" == true ]]; then
        learn_summary "$memory_dir"
        return 0
    fi

    # Synthesize mode: run synthesis pipeline on all observations
    if [[ "$synthesize_mode" == true ]]; then
        log_header "Synthesis Pipeline"
        log_step "Reading observations from ${COLOR_STEP}.speed/memory/observations/${RESET}"
        echo ""

        if learn_synthesize "$memory_dir" "$PROJECT_ROOT"; then
            echo ""
            log_success "Synthesis complete"
            return 0
        else
            log_error "Synthesis failed"
            return 1
        fi
    fi

    # Post-merge mode: diff task branches against merged HEAD
    if [[ "$post_merge_mode" == true ]]; then
        _require_feature "$GLOBAL_FEATURE"

        local feature_dir="${FEATURE_DIR}"

        log_header "Post-Merge Correction Extraction — ${GLOBAL_FEATURE}"
        log_step "Diffing task branches against HEAD"
        echo ""

        if learn_post_merge "$feature_dir" "$memory_dir" "$PROJECT_ROOT"; then
            echo ""
            log_success "Post-merge extraction complete"
            return 0
        else
            log_error "Post-merge extraction failed"
            return 1
        fi
    fi

    # Extraction mode: requires a feature
    _require_feature "$GLOBAL_FEATURE"

    local feature_dir="${FEATURE_DIR}"
    local tasks_dir="${TASKS_DIR}"

    # Verify feature has artifacts
    if [[ ! -d "$tasks_dir" ]] || [[ -z "$(ls -A "$tasks_dir" 2>/dev/null)" ]]; then
        log_error "No task artifacts found for feature '${GLOBAL_FEATURE}'."
        log_error "Run speed plan and speed run first."
        exit 2
    fi

    log_header "Observation Extraction — ${GLOBAL_FEATURE}"
    log_step "Reading artifacts from ${COLOR_STEP}${feature_dir}${RESET}"
    echo ""

    if learn_extract "$feature_dir" "$memory_dir" "$dry_run"; then
        echo ""
        [[ "${MP_ENABLED:-}" == "true" ]] && [[ "$dry_run" != true ]] && event_emit "learn.extracted" "$FEATURE_NAME" "{}"
        log_success "Extraction complete"

        # Auto-trigger convention discovery if conditions are met
        if [[ "$dry_run" != true ]]; then
            local should_discover
            should_discover=$(PYTHONPATH="${SCRIPT_DIR}" $(_learn_python) -c "
import sys, os
from pathlib import Path
sys.path.insert(0, os.environ.get('SPEED_DIR', '.'))
from lib.learn.conventions import _should_run_discovery
memory_dir = Path('${memory_dir}')
project_root = Path(os.environ.get('PROJECT_ROOT', '.'))
should_run, _ = _should_run_discovery(memory_dir, project_root)
print('yes' if should_run else 'no')
" 2>/dev/null)
            if [[ "$should_discover" == "yes" ]]; then
                echo ""
                log_step "Convention discovery triggered..."
                learn_conventions || log_warn "Convention discovery failed (non-blocking)"
            fi
        fi

        return 0
    else
        log_error "Extraction failed"
        return 1
    fi
}
