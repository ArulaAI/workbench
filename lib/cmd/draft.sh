#!/usr/bin/env bash
# draft.sh — guided-authoring alias adapter; all behavior lives in the skill helper.

_draft_python() {
    if [[ -n "${SPEED_PYTHON:-}" ]]; then
        echo "$SPEED_PYTHON"
    elif [[ -x "${SPEED_DIR}/.venv/bin/python3" ]]; then
        echo "${SPEED_DIR}/.venv/bin/python3"
    elif [[ -x "${PROJECT_ROOT}/.venv/bin/python3" ]]; then
        echo "${PROJECT_ROOT}/.venv/bin/python3"
    else
        echo "python3"
    fi
}

_draft_usage() {
    cat >&2 <<'USAGE'
Usage: workbench draft <prd|design> <feature-name> [options]

Starts or resumes the Product or PRD-linked Design interview. The artifact is
generated only after every required answer is confirmed.

Options:
    --feature-description TEXT Seed P-Q1 from the new feature's problem summary
    --answer TEXT             Confirm the current question (agent/non-TTY use)
    --accept-suggestion       Accept the grounded suggestion unchanged
    --edit-suggestion         Persist Edit, then resume with suggested text
    --reject-suggestion       Reject the suggestion and keep the question open
    --defer                   Defer the current question; generation stays blocked
    --expected-revision N     Reject stale concurrent answers
    --dashboard-url URL       Preview base URL (default: http://localhost:3000)
    --json                    Return structured interview state
USAGE
}

cmd_draft() {
    case "${1:-}" in
        -h|--help) _draft_usage; return 0 ;;
        ""|prd|design) ;;
        *)
            log_error "Unsupported draft type: ${1:-missing} (supported: prd, design)"
            return 1
            ;;
    esac

    if [[ "${JSON_OUTPUT:-false}" == "true" ]]; then
        set -- "$@" --json
    fi

    _speed_alias_notice draft
    "$(_draft_python)" "${SPEED_DIR}/skills/workbench-draft/scripts/draft.py" \
        "$@" --project-root "${PROJECT_ROOT}"
}
