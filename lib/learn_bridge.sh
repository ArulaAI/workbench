#!/usr/bin/env bash
# learn_bridge.sh — Bash bridge to the Python observation extraction pipeline
#
# Sources into the SPEED orchestrator to provide learning system integration.
# Bridges: bash (speed) → python (lib/learn/)
#
# Functions:
#   learn_extract        — Run the 10-step extraction pipeline for a feature
#   learn_summary        — Print aggregate stats across all observed features
#   learn_conventions    — Run convention discovery pipeline and print summary
#   learn_seed_knowledge — Scan project files and generate draft knowledge entries
#
# Requires: PROJECT_ROOT, python3 with lib/learn/ on path.
# Uses SPEED_PYTHON if set, falls back to .venv/bin/python3 then python3.

_learn_python() {
    if [[ -n "${SPEED_PYTHON:-}" ]]; then
        echo "$SPEED_PYTHON"
    elif [[ -x "${SPEED_DIR}/.venv/bin/python3" ]]; then
        echo "${SPEED_DIR}/.venv/bin/python3"
    elif [[ -x "${SCRIPT_DIR}/.venv/bin/python3" ]]; then
        echo "${SCRIPT_DIR}/.venv/bin/python3"
    else
        echo "python3"
    fi
}

learn_conventions() {
    local memory_dir="${STATE_DIR}/memory"
    [[ "${MP_ENABLED:-}" == "true" ]] && memory_dir="$(mp_knowledge_dir)"

    local output
    output=$($_TIMEOUT_CMD 120 env PYTHONPATH="${SCRIPT_DIR}" $(_learn_python) -c "
import sys, os
from pathlib import Path
sys.path.insert(0, os.environ.get('SPEED_DIR', '.'))
from lib.learn.conventions import discover_conventions

project_root = Path(os.environ.get('PROJECT_ROOT', '.'))
memory_dir = Path('${memory_dir}')
csg_path = project_root / '.speed' / 'context' / 'semantic-graph.json'

result = discover_conventions(
    project_root,
    memory_dir,
    csg_path=csg_path if csg_path.exists() else None,
)
print(result.summary())
" 2>&1)

    local rc=$?
    if [[ $rc -eq 124 ]]; then
        log_warn "Convention discovery timed out after 120s (non-blocking)"
        return 1
    fi
    if [[ $rc -ne 0 ]]; then
        echo "$output" >&2
        return $rc
    fi

    echo "$output"
    return 0
}

learn_seed_knowledge() {
    local memory_dir="${STATE_DIR}/memory"
    [[ "${MP_ENABLED:-}" == "true" ]] && memory_dir="$(mp_knowledge_dir)"

    local output
    output=$(PYTHONPATH="${SCRIPT_DIR}" $(_learn_python) -c "
import sys, os
from pathlib import Path
sys.path.insert(0, os.environ.get('SPEED_DIR', '.'))
from lib.learn.project_knowledge import seed_knowledge

project_root = Path(os.environ.get('PROJECT_ROOT', '.'))
memory_dir = Path('${memory_dir}')

entries = seed_knowledge(project_root, memory_dir)
n = len(entries)
print(f'Generated {n} draft entries in project-knowledge-drafts.json. Review and promote to project-knowledge.json.')
" 2>&1)

    local rc=$?
    if [[ $rc -ne 0 ]]; then
        echo "$output" >&2
        return $rc
    fi

    echo "$output"
    return 0
}

learn_extract() {
    local feature_dir="$1"
    local memory_dir="$2"
    local dry_run="${3:-false}"

    # Pre-parse raw agent output files into clean JSON.
    # plan-verification.log and coherence.log contain markdown-wrapped
    # JSON (prose preamble + ```json fence + trailing summary).
    # parse_agent_json (lib/provider.sh) already handles this format.
    local verify_json="" coherence_json=""
    if [[ -f "${feature_dir}/logs/plan-verification.log" ]]; then
        verify_json=$(parse_agent_json "$(cat "${feature_dir}/logs/plan-verification.log")") || verify_json=""
    fi
    if [[ -f "${feature_dir}/logs/coherence.log" ]]; then
        coherence_json=$(parse_agent_json "$(cat "${feature_dir}/logs/coherence.log")") || coherence_json=""
    fi

    # Write pre-parsed JSON to temp files for Python consumption.
    local tmp_verify tmp_coherence
    tmp_verify=$(mktemp "${TMPDIR:-/tmp}/_speed_verify_XXXXXX")
    tmp_coherence=$(mktemp "${TMPDIR:-/tmp}/_speed_coherence_XXXXXX")
    echo "$verify_json" > "$tmp_verify"
    echo "$coherence_json" > "$tmp_coherence"

    local _proposals_dir=""
    [[ "${MP_ENABLED:-}" == "true" ]] && _proposals_dir="$(mp_proposals_dir)"

    local output
    output=$(PYTHONPATH="${SCRIPT_DIR}" \
        _SPEED_SCRIPT_DIR="${SCRIPT_DIR}" \
        _SPEED_FEATURE_DIR="${feature_dir}" \
        _SPEED_MEMORY_DIR="${memory_dir}" \
        _SPEED_VERIFY_PATH="${tmp_verify}" \
        _SPEED_COHERENCE_PATH="${tmp_coherence}" \
        _SPEED_DRY_RUN="${dry_run}" \
        _SPEED_FEATURE_NAME="${GLOBAL_FEATURE}" \
        _SPEED_MP_ENABLED="${MP_ENABLED:-}" \
        _SPEED_PROPOSALS_DIR="${_proposals_dir}" \
        _SPEED_ACTOR="$(actor_get 2>/dev/null || echo '')" \
        $(_learn_python) -c "
import os, sys
from pathlib import Path
sys.path.insert(0, os.environ['_SPEED_SCRIPT_DIR'])
from lib.learn.extract import extract_observations, write_observations
from lib.learn.classify import classify, REVIEW_PROTOTYPES

feature_dir = Path(os.environ['_SPEED_FEATURE_DIR'])
memory_dir = Path(os.environ['_SPEED_MEMORY_DIR'])
verify_path = Path(os.environ['_SPEED_VERIFY_PATH'])
coherence_path = Path(os.environ['_SPEED_COHERENCE_PATH'])
dry_run = os.environ.get('_SPEED_DRY_RUN') == 'true'

def classify_fn(text):
    model_path = memory_dir / 'models' / 'review_classifier.pkl'
    return classify(text, REVIEW_PROTOTYPES, model_path=model_path)

result = extract_observations(
    feature_dir, memory_dir,
    verify_json_path=verify_path if verify_path.stat().st_size > 1 else None,
    coherence_json_path=coherence_path if coherence_path.stat().st_size > 1 else None,
    classify_fn=classify_fn,
)

# Output structured lines for bash to format
groups = result.by_type()
steps = [
    ('Task outcomes', ['retry', 'gate_failure', 'unattributed_changes']),
    ('Review findings', ['reviewer_finding']),
    ('Guardian verdicts', ['guardian_verdict']),
    ('Verify findings', ['verify_finding']),
    ('Coherence issues', ['coherence_issue']),
    ('Security findings', ['security_finding']),
    ('Context effectiveness', ['context_miss', 'context_waste']),
    ('Decomposition quality', ['decomposition_miss']),
    ('Success observations', ['success']),
    ('Pattern matching', ['pattern_match']),
]
for i, (label, types) in enumerate(steps, 1):
    count = sum(len(groups.get(t, [])) for t in types)
    parts = []
    for t in types:
        n = len(groups.get(t, []))
        if n > 0:
            parts.append(f'{n} {t}')
    detail = ', '.join(parts) if parts else 'none'
    print(f'STEP|{i}|{label}|{count}|{detail}')

# Steps 11-14: Human correction signals (filter by change_type)
human_obs = groups.get('human_override', []) + groups.get('human_approved', [])
human_steps = [
    ('Retry guidance', 'guidance'),
    ('Skip flags', 'skip'),
    ('Forced approvals', 'forced_approval'),
    ('Defect rejections', 'defect_rejection'),
]
for j, (label, ct) in enumerate(human_steps, 11):
    matching = [o for o in human_obs if o.detail.get('change_type') == ct]
    count = len(matching)
    detail = f'{count} human_override' if count > 0 else 'none'
    print(f'STEP|{j}|{label}|{count}|{detail}')

for w in result.warnings:
    print(f'WARN|{w}')
for e in result.errors:
    print(f'ERROR|{e}')

total = len(result.observations)
print(f'TOTAL|{total}')

if dry_run:
    print('DRY_RUN')
elif os.environ.get('_SPEED_MP_ENABLED') == 'true':
    from lib.learn.proposals import write_proposal
    proposals_dir = Path(os.environ['_SPEED_PROPOSALS_DIR'])
    obs_dicts = [{'id': o.id, 'feature': o.feature, 'stage': o.stage, 'task_id': o.task_id,
                  'observation_type': o.observation_type, 'detail': o.detail, 'weight': o.weight}
                 for o in result.observations]
    pr = write_proposal(obs_dicts, [], os.environ['_SPEED_FEATURE_NAME'],
                        os.environ.get('_SPEED_ACTOR', 'unknown'), proposals_dir)
    print(f'WRITE|{pr.observation_count}|0')
    print(f'PROPOSAL|{pr.path}')
else:
    output_path = memory_dir / 'observations' / (os.environ['_SPEED_FEATURE_NAME'] + '.jsonl')
    wr = write_observations(result.observations, output_path)
    print(f'WRITE|{wr.written}|{wr.skipped}')

    from lib.learn.classify import train_classifier
    trained = train_classifier(
        memory_dir / 'observations',
        memory_dir / 'models' / 'review_classifier.pkl',
    )
    if trained:
        print('TRAINED')
" 2>&1)

    local rc=$?
    rm -f "$tmp_verify" "$tmp_coherence"

    if [[ $rc -ne 0 ]]; then
        echo "$output" >&2
        return $rc
    fi

    # Format output with SPEED log system
    local step_num=0 total=0
    while IFS= read -r line; do
        case "$line" in
            STEP\|*)
                IFS='|' read -r _ num label count detail <<< "$line"
                local dots
                dots=$(printf '.%.0s' $(seq 1 $((30 - ${#label}))))
                if [[ "$count" -gt 0 ]]; then
                    log_step "Step ${num}/14: ${label} ${COLOR_DIM}${dots}${RESET} ${COLOR_SUCCESS}${count}${RESET} ${COLOR_DIM}(${detail})${RESET}"
                else
                    log_step "Step ${num}/14: ${label} ${COLOR_DIM}${dots} ${count}${RESET}"
                fi
                ;;
            WARN\|*)
                local msg="${line#WARN|}"
                log_warn "$msg"
                ;;
            ERROR\|*)
                local msg="${line#ERROR|}"
                log_error "$msg"
                ;;
            TOTAL\|*)
                total="${line#TOTAL|}"
                ;;
            DRY_RUN)
                echo ""
                log_info "Dry run ${COLOR_DIM}— ${total} observations found, nothing written${RESET}"
                ;;
            WRITE\|*)
                IFS='|' read -r _ written skipped <<< "$line"
                echo ""
                if [[ "$written" -gt 0 ]]; then
                    if [[ "${MP_ENABLED:-}" == "true" ]]; then
                        log_success "Wrote ${written} observations to proposal"
                    else
                        log_success "Wrote ${written} observations to ${COLOR_STEP}.speed/memory/observations/${GLOBAL_FEATURE}.jsonl${RESET}"
                    fi
                else
                    log_info "All ${skipped} observations already exist ${COLOR_DIM}— nothing new${RESET}"
                fi
                if [[ "$skipped" -gt 0 && "$written" -gt 0 ]]; then
                    log_info "${COLOR_DIM}${skipped} duplicates skipped${RESET}"
                fi
                ;;
            PROPOSAL\|*)
                local proposal_path="${line#PROPOSAL|}"
                log_success "Proposal written to ${COLOR_STEP}${proposal_path}${RESET}"
                log_info "Run ${COLOR_STEP}speed learn --merge${RESET} to merge into shared knowledge"
                ;;
            TRAINED)
                log_success "Classifier retrained with latest observations"
                ;;
            *)
                # Pass through any unrecognized output
                [[ -n "$line" ]] && echo "$line"
                ;;
        esac
    done <<< "$output"

    return 0
}

learn_summary() {
    local memory_dir="$1"

    local output
    output=$(PYTHONPATH="${SCRIPT_DIR}" $(_learn_python) -c "
import json, sys
from pathlib import Path
from collections import Counter

obs_dir = Path('${memory_dir}') / 'observations'
if not obs_dir.is_dir():
    print('EMPTY')
    sys.exit(0)

total = 0
features = set()
by_type = Counter()
patterns = []

for f in sorted(obs_dir.glob('*.jsonl')):
    feature_name = f.stem
    features.add(feature_name)
    for line in f.read_text().strip().split('\n'):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
            total += 1
            by_type[obj.get('observation_type', 'unknown')] += 1
            if obj.get('observation_type') == 'pattern_match':
                patterns.append(obj.get('detail', {}))
        except json.JSONDecodeError:
            continue

print(f'SUMMARY|{len(features)}|{total}')
for p in patterns[:5]:
    print(f\"PATTERN|{p.get('pattern', 'unknown')}|{p.get('frequency', '')}\")
for t, n in by_type.most_common():
    print(f'TYPE|{t}|{n}')
" 2>&1)

    while IFS= read -r line; do
        case "$line" in
            EMPTY)
                log_info "No observations found. Run ${COLOR_STEP}speed learn${RESET} after integrating a feature."
                ;;
            SUMMARY\|*)
                IFS='|' read -r _ feat_count obs_count <<< "$line"
                echo ""
                log_info "${COLOR_SUCCESS}${feat_count}${RESET} features observed ${COLOR_DIM}·${RESET} ${COLOR_SUCCESS}${obs_count}${RESET} total observations"
                ;;
            PATTERN\|*)
                IFS='|' read -r _ pattern freq <<< "$line"
                echo -e "  ${COLOR_WARN}${SYM_DOT}${RESET} ${pattern} ${COLOR_DIM}(${freq})${RESET}"
                ;;
            TYPE\|*)
                IFS='|' read -r _ type_name count <<< "$line"
                echo -e "  ${COLOR_DIM}${type_name}:${RESET} ${count}"
                ;;
        esac
    done <<< "$output"
    echo ""
}

learn_post_merge() {
    local feature_dir="$1"
    local memory_dir="$2"
    local project_root="$3"

    local feature_name
    feature_name=$(basename "$feature_dir")

    local output
    output=$(PYTHONPATH="${SCRIPT_DIR}" $(_learn_python) -c "
import json, sys
from pathlib import Path
sys.path.insert(0, '${SCRIPT_DIR}')
sys.path.insert(0, '${SCRIPT_DIR}/lib')
from lib.learn.human_corrections import extract_post_merge
from lib.learn.extract import write_observations

feature_dir = Path('${feature_dir}')
project_root = Path('${project_root}')
memory_dir = Path('${memory_dir}')
feature = '${feature_name}'

observations, warnings = extract_post_merge(feature, feature_dir, project_root)

for w in warnings:
    print(f'WARN|{w}')

if not observations:
    print('EMPTY')
    sys.exit(0)

# Classify observations
overrides = [o for o in observations if o.observation_type == 'human_override']
approvals = [o for o in observations if o.observation_type == 'human_approved']

# Group overrides by change_type
from collections import Counter
ct_counts = Counter(o.detail.get('change_type', 'unknown') for o in overrides)
for ct, n in ct_counts.most_common():
    print(f'TYPE|{ct}|{n}')

if approvals:
    a = approvals[0]
    print(f'APPROVED|{a.detail.get(\"tasks_approved\", 0)}|{a.detail.get(\"files_approved\", 0)}')

print(f'TOTAL|{len(observations)}')

output_path = memory_dir / 'observations' / f'{feature}.jsonl'
wr = write_observations(observations, output_path)
print(f'WRITE|{wr.written}|{wr.skipped}')
" 2>&1)

    local rc=$?

    if [[ $rc -ne 0 ]]; then
        echo "$output" >&2
        return $rc
    fi

    local total=0

    while IFS= read -r line; do
        case "$line" in
            WARN\|*)
                local msg="${line#WARN|}"
                log_warn "$msg"
                ;;
            EMPTY)
                log_info "No post-merge corrections detected ${COLOR_DIM}— task branches match HEAD${RESET}"
                ;;
            TYPE\|*)
                IFS='|' read -r _ change_type count <<< "$line"
                local dots
                dots=$(printf '.%.0s' $(seq 1 $((25 - ${#change_type}))))
                log_step "${change_type} ${COLOR_DIM}${dots}${RESET} ${COLOR_SUCCESS}${count}${RESET}"
                ;;
            APPROVED\|*)
                IFS='|' read -r _ tasks files <<< "$line"
                log_step "Zero-delta merge ${COLOR_DIM}— ${tasks} tasks, ${files} files approved as-is${RESET}"
                ;;
            TOTAL\|*)
                total="${line#TOTAL|}"
                ;;
            WRITE\|*)
                IFS='|' read -r _ written skipped <<< "$line"
                echo ""
                if [[ "$written" -gt 0 ]]; then
                    log_success "Wrote ${written} post-merge observations to ${COLOR_STEP}.speed/memory/observations/${feature_name}.jsonl${RESET}"
                else
                    log_info "All ${skipped} observations already exist ${COLOR_DIM}— nothing new${RESET}"
                fi
                if [[ "$skipped" -gt 0 && "$written" -gt 0 ]]; then
                    log_info "${COLOR_DIM}${skipped} duplicates skipped${RESET}"
                fi
                ;;
            *)
                [[ -n "$line" ]] && echo "$line"
                ;;
        esac
    done <<< "$output"

    return 0
}

learn_synthesize() {
    local memory_dir="$1"
    local project_root="$2"

    local output
    output=$(PYTHONPATH="${SCRIPT_DIR}" $(_learn_python) -c "
import json, sys
from pathlib import Path
sys.path.insert(0, '${SCRIPT_DIR}')
sys.path.insert(0, '${SCRIPT_DIR}/lib')
from lib.learn.synthesize import synthesize

memory_dir = Path('${memory_dir}')
project_root = Path('${project_root}')

result = synthesize(memory_dir, project_root=project_root)

if result.skipped:
    print('SKIPPED')
    sys.exit(0)

# Per-agent results
for agent, entries in sorted(result.entries_by_agent.items()):
    tokens = sum(len(json.dumps(e.detail)) // 4 for e in entries)
    print(f'AGENT|{agent}|{len(entries)}|{tokens}')

# Rejects and conflicts
print(f'REJECTS|{len(result.rejects)}')
print(f'CONFLICTS|{len(result.conflicts)}')

# Features processed
features = result.meta.features_processed
print(f'FEATURES|{len(features)}')
" 2>&1)

    local rc=$?

    if [[ $rc -ne 0 ]]; then
        echo "$output" >&2
        return $rc
    fi

    local total_entries=0 total_tokens=0

    while IFS= read -r line; do
        case "$line" in
            SKIPPED)
                log_info "No new observations since last synthesis ${COLOR_DIM}— skipped${RESET}"
                return 0
                ;;
            AGENT\|*)
                IFS='|' read -r _ agent count tokens <<< "$line"
                total_entries=$((total_entries + count))
                total_tokens=$((total_tokens + tokens))
                local dots
                dots=$(printf '.%.0s' $(seq 1 $((20 - ${#agent}))))
                if [[ "$count" -gt 0 ]]; then
                    log_step "${agent} ${COLOR_DIM}${dots}${RESET} ${COLOR_SUCCESS}${count}${RESET} entries ${COLOR_DIM}(${tokens} tokens)${RESET}"
                else
                    log_step "${agent} ${COLOR_DIM}${dots} 0 entries${RESET}"
                fi
                ;;
            REJECTS\|*)
                local rejects="${line#REJECTS|}"
                if [[ "$rejects" -gt 0 ]]; then
                    log_info "${COLOR_DIM}${rejects} entries rejected (quality/budget/conflict)${RESET}"
                fi
                ;;
            CONFLICTS\|*)
                local conflicts="${line#CONFLICTS|}"
                if [[ "$conflicts" -gt 0 ]]; then
                    log_warn "${conflicts} unresolved conflicts written to synthesis-conflicts.json"
                fi
                ;;
            FEATURES\|*)
                local feat_count="${line#FEATURES|}"
                echo ""
                log_info "${COLOR_SUCCESS}${feat_count}${RESET} features ${COLOR_DIM}→${RESET} ${COLOR_SUCCESS}${total_entries}${RESET} learnings entries ${COLOR_DIM}(${total_tokens} tokens)${RESET}"
                ;;
            *)
                [[ -n "$line" ]] && echo "$line"
                ;;
        esac
    done <<< "$output"

    return 0
}
