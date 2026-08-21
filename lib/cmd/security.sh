#!/usr/bin/env bash
# security.sh — Security audit CLI command

cmd_security() {
    local create_defects=false
    local feature_name="${GLOBAL_FEATURE:-}"

    # Parse flags
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --create-defects)
                create_defects=true
                shift
                ;;
            --feature|-f)
                feature_name="$2"
                shift 2
                ;;
            *)
                log_error "Unknown option: $1"
                exit 1
                ;;
        esac
    done

    # Resolve feature name from active feature if not specified
    if [[ -z "$feature_name" ]]; then
        feature_name=$(feature_get_active)
    fi

    if [[ -z "$feature_name" ]]; then
        log_error "No active feature. Run speed plan first or specify --feature."
        exit 1
    fi

    log_header "Security Audit — ${feature_name}"

    local logs_dir="${STATE_DIR}/features/${feature_name}/logs"
    local audit_file="${logs_dir}/security-audit.json"

    # Run audit, or reuse cached results when creating defects
    if [[ "$create_defects" == "true" ]] && security_has_cached_audit "$feature_name"; then
        log_info "Using cached security audit results (less than 1 hour old)."
    else
        security_audit_run "$feature_name"
    fi

    # Print findings banner
    if [[ -f "$audit_file" ]]; then
        security_print_banner "$audit_file"
    else
        echo "No security findings."
    fi

    # Create defect specs if requested
    if [[ "$create_defects" == "true" ]]; then
        if [[ ! -f "$audit_file" ]]; then
            log_error "No audit results found. Cannot create defects."
            exit 1
        fi

        local threshold="${TOML_SECURITY_SEVERITY_THRESHOLD:-medium}"
        security_create_defects "$audit_file" "$threshold"
    fi
}
