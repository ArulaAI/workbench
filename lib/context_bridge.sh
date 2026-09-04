#!/usr/bin/env bash
# context_bridge.sh — Bash bridge to the Python context pipeline
#
# Sources into the SPEED orchestrator to provide context system integration.
# Bridges: bash (speed) → python (lib/context/)
#
# Functions:
#   context_build_layer1                    — Build/refresh Layer 1 (pre-computed index)
#   context_build_layer2_task               — Build Layer 2 for a single task
#   context_build_cross_task                — Build cross-task analysis for a feature
#   context_assemble_architect              — Assemble architect prompt (Layer 3)
#   context_assemble_verifier               — Assemble verifier prompt (Layer 3)
#   context_assemble_developer              — Assemble developer prompt (Layer 3)
#   context_assemble_reviewer               — Assemble reviewer prompt (Layer 3)
#   context_assemble_coherence              — Assemble coherence prompt (Layer 3)
#   context_assemble_debugger               — Assemble debugger prompt (Layer 3)
#   context_assemble_security_auditor       — Assemble security auditor prompt (Layer 3)
#   context_decomposition_gate              — Run decomposition quality checks
#   context_classify_failure                — Classify a task failure
#   context_spec_traceability               — Run spec-to-task coverage check
#   context_score_and_compress_specs        — Score and compress related specs
#   context_repository_digest_status        — Read stored repository-digest.json status (JSON)
#   context_build_repository_digest         — Build/refresh repository-digest.json (JSON result)
#   context_project_repository_digest_markdown — Bounded Markdown projection of the stored digest
#
# Requires: PROJECT_ROOT, python3 with lib/context/ on path.
# Uses SPEED_PYTHON if set, falls back to .venv/bin/python3 then python3.

_context_python() {
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

# ── Layer 1: Pre-Computed Index ─────────────────────────────────

context_build_layer1() {
    local fresh="${1:-false}"
    local spec_files_json="${2:-}"  # Optional: JSON string of {path: content}

    local py_fresh="False"
    [[ "$fresh" == "true" ]] && py_fresh="True"

    local py_cmd="
import sys, json
sys.path.insert(0, '${SPEED_DIR}')
from lib.context.layer1 import build_layer1

spec_files = None
spec_json = '''${spec_files_json}'''
if spec_json.strip():
    try:
        spec_files = json.loads(spec_json)
    except: pass

result = build_layer1(
    '${PROJECT_ROOT}',
    fresh=${py_fresh},
    spec_files=spec_files,
)
print(json.dumps(result))
"
    $(_context_python) -c "$py_cmd"
}


# ── Layer 2: Task-Specific Projection ───────────────────────────

context_build_layer2_task() {
    local task_json_path="$1"
    local all_tasks_dir="$2"
    local completed_json="${3:-}"  # Optional: JSON string of {task_id: output_dict}
    local stage="${4:-developer}"

    $(_context_python) - "$task_json_path" "$all_tasks_dir" "$completed_json" "$stage" <<'PYTHON_EOF'
import sys, os, json
sys.path.insert(0, os.environ.get("SPEED_DIR", "."))

task_json_path = sys.argv[1]
all_tasks_dir = sys.argv[2]
completed_json = sys.argv[3] if len(sys.argv) > 3 else ""
stage = sys.argv[4] if len(sys.argv) > 4 else "developer"

project_root = os.environ.get("PROJECT_ROOT", ".")
context_dir = os.path.join(project_root, ".speed", "context")

# Load task
with open(task_json_path) as f:
    task = json.load(f)

# Load all tasks from directory
all_tasks = []
if os.path.isdir(all_tasks_dir):
    for fname in sorted(os.listdir(all_tasks_dir)):
        if fname.endswith(".json"):
            with open(os.path.join(all_tasks_dir, fname)) as f:
                all_tasks.append(json.load(f))

# Load completed tasks
completed_tasks = {}
if completed_json:
    try:
        completed_tasks = json.loads(completed_json)
    except:
        pass

# Load Layer 1 artifacts
from lib.context.utils import read_json
csg = read_json(os.path.join(context_dir, "semantic-graph.json"))
project_map = read_json(os.path.join(context_dir, "project-map.json"))

# Load spec files (from feature directory if available)
spec_files = {}
feature_name = task.get("feature", "")
if feature_name:
    spec_dir = os.path.join(project_root, ".speed", "features", feature_name)
    for fname in os.listdir(spec_dir) if os.path.isdir(spec_dir) else []:
        if fname.endswith(".md"):
            path = os.path.join(spec_dir, fname)
            with open(path) as f:
                spec_files[fname] = f.read()

# Load spec alignment (feature-scoped when available, codebase-scoped fallback)
if feature_name:
    _align_dir = os.path.join(project_root, ".speed", "features", feature_name, "context")
else:
    _align_dir = context_dir
spec_alignment = read_json(os.path.join(_align_dir, "spec-alignment.json"))

# Task output base: feature-scoped when available, codebase-scoped fallback
if feature_name:
    task_output_base = os.path.join(project_root, ".speed", "features", feature_name)
else:
    task_output_base = None

from lib.context.layer2 import build_task_context_package
result = build_task_context_package(
    task=task,
    all_tasks=all_tasks,
    project_root=project_root,
    csg=csg,
    project_map=project_map,
    context_dir=context_dir,
    spec_files=spec_files,
    spec_alignment=spec_alignment if spec_alignment else None,
    completed_tasks=completed_tasks,
    stage=stage,
    task_output_base=task_output_base,
)

print(json.dumps(result))
PYTHON_EOF
}


context_build_cross_task() {
    local all_tasks_dir="$1"
    local feature_name="${2:-default}"

    $(_context_python) - "$all_tasks_dir" "$feature_name" <<'PYTHON_EOF'
import sys, os, json
sys.path.insert(0, os.environ.get("SPEED_DIR", "."))

all_tasks_dir = sys.argv[1]
feature_name = sys.argv[2] if len(sys.argv) > 2 else "default"

project_root = os.environ.get("PROJECT_ROOT", ".")
context_dir = os.path.join(project_root, ".speed", "context")

# Load all tasks
all_tasks = []
if os.path.isdir(all_tasks_dir):
    for fname in sorted(os.listdir(all_tasks_dir)):
        if fname.endswith(".json"):
            with open(os.path.join(all_tasks_dir, fname)) as f:
                all_tasks.append(json.load(f))

from lib.context.utils import read_json
csg = read_json(os.path.join(context_dir, "semantic-graph.json"))

feature_context_dir = os.path.join(
    project_root, ".speed", "features", feature_name, "context"
)

from lib.context.layer2 import build_feature_cross_task
result = build_feature_cross_task(all_tasks, csg, feature_context_dir)

print(json.dumps(result))
PYTHON_EOF
}


# ── Layer 3: Assembly Functions ─────────────────────────────────

context_assemble_architect() {
    local _memory_dir="${STATE_DIR}/memory"
    [[ "${MP_ENABLED:-}" == "true" ]] && _memory_dir="$(mp_knowledge_dir)"
    SPEED_MEMORY_DIR="$_memory_dir" $(_context_python) - <<'PYTHON_EOF'
import sys, os, json
sys.path.insert(0, os.environ.get("SPEED_DIR", "."))

project_root = os.environ.get("PROJECT_ROOT", ".")
context_dir = os.path.join(project_root, ".speed", "context")

from lib.context.utils import read_json
project_map = read_json(os.path.join(context_dir, "project-map.json"))
csg = read_json(os.path.join(context_dir, "semantic-graph.json"))
spec_alignment = read_json(os.path.join(context_dir, "spec-alignment.json"))

from pathlib import Path
from lib.learn.synthesize import filter_learnings_for_task
memory_dir = Path(os.environ.get("SPEED_MEMORY_DIR", os.path.join(project_root, ".speed", "memory")))
learnings_path = memory_dir / "learnings" / "architect-learnings.json"
# Architect operates at feature level — no task-scoping, pass all project files
all_files = [f.get("path", "") for f in project_map.get("files", [])]
learnings = filter_learnings_for_task(learnings_path, all_files)

from lib.learn.conventions import format_conventions_for_agent, format_knowledge_for_agent
conventions_path = memory_dir / "conventions.json"
knowledge_path = memory_dir / "project-knowledge.json"
conventions_md = format_conventions_for_agent(conventions_path, "architect", all_files)
knowledge_md = format_knowledge_for_agent(knowledge_path, "architect", all_files)

from lib.context.assembly import assemble_architect
result = assemble_architect(
    project_map=project_map,
    csg=csg,
    spec_alignment=spec_alignment if spec_alignment else None,
    learnings=learnings,
    conventions=conventions_md,
    project_knowledge=knowledge_md,
)

print(result)
PYTHON_EOF
}


context_assemble_verifier() {
    local product_spec_content="$1"
    local all_tasks_dir="$2"
    local cross_cutting_json="${3:-}"
    local contract_file="${4:-}"

    $(_context_python) - "$all_tasks_dir" "$contract_file" <<PYTHON_EOF
import sys, os, json
sys.path.insert(0, os.environ.get("SPEED_DIR", "."))

all_tasks_dir = sys.argv[1]
contract_file = sys.argv[2] if len(sys.argv) > 2 else ""

project_root = os.environ.get("PROJECT_ROOT", ".")
context_dir = os.path.join(project_root, ".speed", "context")

product_spec = """${product_spec_content}"""

# Load tasks
all_tasks = []
if os.path.isdir(all_tasks_dir):
    for fname in sorted(os.listdir(all_tasks_dir)):
        if fname.endswith(".json"):
            with open(os.path.join(all_tasks_dir, fname)) as f:
                all_tasks.append(json.load(f))

# Cross-cutting concerns
cross_cutting = None
cross_json = """${cross_cutting_json}"""
if cross_json.strip():
    try:
        cross_cutting = json.loads(cross_json)
    except: pass

# Contract
contract = None
if contract_file and os.path.isfile(contract_file):
    with open(contract_file) as f:
        contract = json.load(f)

from lib.context.utils import read_json
spec_alignment = read_json(os.path.join(context_dir, "spec-alignment.json"))
csg = read_json(os.path.join(context_dir, "semantic-graph.json"))

from lib.context.assembly import assemble_verifier
result = assemble_verifier(
    product_spec=product_spec,
    tasks=all_tasks,
    cross_cutting_concerns=cross_cutting,
    contract=contract,
    spec_alignment=spec_alignment if spec_alignment else None,
    csg=csg if csg else None,
)

print(result)
PYTHON_EOF
}


context_assemble_developer() {
    local task_json_path="$1"
    local branch_name="${2:-}"
    local worktree_path="${3:-}"
    local feature_name="${4:-}"
    local cross_cutting_json="${5:-}"

    local _memory_dir="${STATE_DIR}/memory"
    [[ "${MP_ENABLED:-}" == "true" ]] && _memory_dir="$(mp_knowledge_dir)"
    SPEED_MEMORY_DIR="$_memory_dir" $(_context_python) - "$task_json_path" "$branch_name" "$worktree_path" "$feature_name" <<PYTHON_EOF
import sys, os, json
sys.path.insert(0, os.environ.get("SPEED_DIR", "."))

task_json_path = sys.argv[1]
branch_name = sys.argv[2] if len(sys.argv) > 2 else ""
worktree_path = sys.argv[3] if len(sys.argv) > 3 else ""
feature_name = sys.argv[4] if len(sys.argv) > 4 else ""

project_root = os.environ.get("PROJECT_ROOT", ".")
context_dir = os.path.join(project_root, ".speed", "context")
task_id = os.path.basename(task_json_path).replace(".json", "")
task_context_dir = os.path.join(context_dir, "tasks", task_id, "context")

with open(task_json_path) as f:
    task = json.load(f)

from lib.context.utils import read_json
code_ctx = read_json(os.path.join(task_context_dir, "code-context.json"))
task_ctx = read_json(os.path.join(task_context_dir, "task-context.json"))
spec_ctx = read_json(os.path.join(task_context_dir, "spec-context.json"))
budget = read_json(os.path.join(task_context_dir, "budget.json"))

cross_cutting = None
cross_json = """${cross_cutting_json}"""
if cross_json.strip():
    try:
        cross_cutting = json.loads(cross_json)
    except: pass

# Learnings injection
from pathlib import Path
from lib.learn.synthesize import filter_learnings_for_task
memory_dir = Path(os.environ.get("SPEED_MEMORY_DIR", os.path.join(project_root, ".speed", "memory")))
learnings_path = memory_dir / "learnings" / "developer-learnings.json"
task_files = task.get("files_to_modify", []) + task.get("files_to_create", [])
learnings = filter_learnings_for_task(learnings_path, task_files)

from lib.learn.conventions import format_conventions_for_agent, format_knowledge_for_agent
conventions_path = memory_dir / "conventions.json"
knowledge_path = memory_dir / "project-knowledge.json"
conventions_md = format_conventions_for_agent(conventions_path, "developer", task_files)
knowledge_md = format_knowledge_for_agent(knowledge_path, "developer", task_files)

from lib.context.assembly import assemble_developer
result = assemble_developer(
    task=task,
    code_context=code_ctx,
    task_context=task_ctx,
    spec_context=spec_ctx,
    budget=budget if budget else None,
    cross_cutting_concerns=cross_cutting,
    branch_name=branch_name,
    worktree_path=worktree_path,
    feature_name=feature_name,
    learnings=learnings,
    conventions=conventions_md,
    project_knowledge=knowledge_md,
)

print(result)
PYTHON_EOF
}


context_assemble_reviewer() {
    local task_json_path="$1"
    local diff="$2"
    local cross_cutting_json="${3:-}"

    local _memory_dir="${STATE_DIR}/memory"
    [[ "${MP_ENABLED:-}" == "true" ]] && _memory_dir="$(mp_knowledge_dir)"
    SPEED_MEMORY_DIR="$_memory_dir" $(_context_python) - "$task_json_path" <<PYTHON_EOF
import sys, os, json
sys.path.insert(0, os.environ.get("SPEED_DIR", "."))

task_json_path = sys.argv[1]

project_root = os.environ.get("PROJECT_ROOT", ".")
context_dir = os.path.join(project_root, ".speed", "context")
task_id = os.path.basename(task_json_path).replace(".json", "")
task_context_dir = os.path.join(context_dir, "tasks", task_id, "context")

with open(task_json_path) as f:
    task = json.load(f)

diff = """${diff}"""

from lib.context.utils import read_json
task_ctx = read_json(os.path.join(task_context_dir, "task-context.json"))
spec_ctx = read_json(os.path.join(task_context_dir, "spec-context.json"))
csg = read_json(os.path.join(context_dir, "semantic-graph.json"))

cross_cutting = None
cross_json = """${cross_cutting_json}"""
if cross_json.strip():
    try:
        cross_cutting = json.loads(cross_json)
    except: pass

# Learnings injection
from pathlib import Path
from lib.learn.synthesize import filter_learnings_for_task
memory_dir = Path(os.environ.get("SPEED_MEMORY_DIR", os.path.join(project_root, ".speed", "memory")))
learnings_path = memory_dir / "learnings" / "reviewer-learnings.json"
task_files = task.get("files_to_modify", []) + task.get("files_to_create", [])
learnings = filter_learnings_for_task(learnings_path, task_files)

from lib.learn.conventions import format_conventions_for_agent, format_knowledge_for_agent
conventions_path = memory_dir / "conventions.json"
knowledge_path = memory_dir / "project-knowledge.json"
conventions_md = format_conventions_for_agent(conventions_path, "reviewer", task_files)
knowledge_md = format_knowledge_for_agent(knowledge_path, "reviewer", task_files)

from lib.context.assembly import assemble_reviewer
result = assemble_reviewer(
    task=task,
    diff=diff,
    task_context=task_ctx,
    spec_context=spec_ctx,
    csg=csg if csg else None,
    cross_cutting_concerns=cross_cutting,
    learnings=learnings,
    conventions=conventions_md,
    project_knowledge=knowledge_md,
)

print(result)
PYTHON_EOF
}


context_assemble_coherence() {
    local all_tasks_dir="$1"
    local task_diffs_json="$2"  # JSON string: {task_id: diff_string}
    local product_spec_content="$3"
    local contract_file="${4:-}"
    local feature_name="${5:-default}"

    local _memory_dir="${STATE_DIR}/memory"
    [[ "${MP_ENABLED:-}" == "true" ]] && _memory_dir="$(mp_knowledge_dir)"
    SPEED_MEMORY_DIR="$_memory_dir" $(_context_python) - "$all_tasks_dir" "$contract_file" "$feature_name" <<PYTHON_EOF
import sys, os, json
sys.path.insert(0, os.environ.get("SPEED_DIR", "."))

all_tasks_dir = sys.argv[1]
contract_file = sys.argv[2] if len(sys.argv) > 2 else ""
feature_name = sys.argv[3] if len(sys.argv) > 3 else "default"

project_root = os.environ.get("PROJECT_ROOT", ".")
context_dir = os.path.join(project_root, ".speed", "context")
feature_context_dir = os.path.join(project_root, ".speed", "features", feature_name, "context")

# Load tasks
all_tasks = []
if os.path.isdir(all_tasks_dir):
    for fname in sorted(os.listdir(all_tasks_dir)):
        if fname.endswith(".json"):
            with open(os.path.join(all_tasks_dir, fname)) as f:
                all_tasks.append(json.load(f))

# Task diffs
task_diffs = {}
diffs_json = """${task_diffs_json}"""
if diffs_json.strip():
    try:
        task_diffs = json.loads(diffs_json)
    except: pass

product_spec = """${product_spec_content}"""

contract = None
if contract_file and os.path.isfile(contract_file):
    with open(contract_file) as f:
        contract = json.load(f)

from lib.context.utils import read_json
cross_task = read_json(os.path.join(feature_context_dir, "cross-task-analysis.json"))

# Learnings injection — coherence operates at feature level, all task files
from pathlib import Path
from lib.learn.synthesize import filter_learnings_for_task
memory_dir = Path(os.environ.get("SPEED_MEMORY_DIR", os.path.join(project_root, ".speed", "memory")))
learnings_path = memory_dir / "learnings" / "coherence-learnings.json"
all_task_files = []
for t in all_tasks:
    all_task_files.extend(t.get("files_to_modify", []))
    all_task_files.extend(t.get("files_to_create", []))
learnings = filter_learnings_for_task(learnings_path, all_task_files)

from lib.context.assembly import assemble_coherence
result = assemble_coherence(
    cross_task_analysis=cross_task if cross_task else {"domain_overlap": [], "interface_boundaries": [], "high_impact_modifications": []},
    completed_tasks=all_tasks,
    task_diffs=task_diffs,
    product_spec=product_spec,
    contract=contract,
    learnings=learnings,
)

print(result)
PYTHON_EOF
}


context_assemble_debugger() {
    local task_json_path="$1"
    local agent_output="$2"
    local diff="${3:-}"

    local _memory_dir="${STATE_DIR}/memory"
    [[ "${MP_ENABLED:-}" == "true" ]] && _memory_dir="$(mp_knowledge_dir)"
    SPEED_MEMORY_DIR="$_memory_dir" $(_context_python) - "$task_json_path" <<PYTHON_EOF
import sys, os, json
sys.path.insert(0, os.environ.get("SPEED_DIR", "."))

task_json_path = sys.argv[1]

project_root = os.environ.get("PROJECT_ROOT", ".")
context_dir = os.path.join(project_root, ".speed", "context")
task_id = os.path.basename(task_json_path).replace(".json", "")
task_context_dir = os.path.join(context_dir, "tasks", task_id, "context")

with open(task_json_path) as f:
    task = json.load(f)

agent_output = """${agent_output}"""
diff = """${diff}"""

from lib.context.utils import read_json
budget = read_json(os.path.join(task_context_dir, "budget.json"))
code_ctx = read_json(os.path.join(task_context_dir, "code-context.json"))

# Try to get failure classification
failure_class = None
fc = task.get("failure_classification")
if fc:
    failure_class = fc

# Learnings injection
from pathlib import Path
from lib.learn.synthesize import filter_learnings_for_task
memory_dir = Path(os.environ.get("SPEED_MEMORY_DIR", os.path.join(project_root, ".speed", "memory")))
learnings_path = memory_dir / "learnings" / "debugger-learnings.json"
task_files = task.get("files_to_modify", [])
learnings = filter_learnings_for_task(learnings_path, task_files)

from lib.context.assembly import assemble_debugger
result = assemble_debugger(
    task=task,
    budget=budget if budget else {"total_budget": 0, "allocated": {}, "cuts_made": []},
    agent_output=agent_output,
    diff=diff,
    code_context=code_ctx if code_ctx else None,
    failure_classification=failure_class,
    learnings=learnings,
)

print(result)
PYTHON_EOF
}


# ── Verification Integration ────────────────────────────────────

context_decomposition_gate() {
    local all_tasks_dir="$1"

    $(_context_python) - "$all_tasks_dir" <<'PYTHON_EOF'
import sys, os, json
sys.path.insert(0, os.environ.get("SPEED_DIR", "."))

all_tasks_dir = sys.argv[1]
project_root = os.environ.get("PROJECT_ROOT", ".")
context_dir = os.path.join(project_root, ".speed", "context")

# Load tasks
all_tasks = []
if os.path.isdir(all_tasks_dir):
    for fname in sorted(os.listdir(all_tasks_dir)):
        if fname.endswith(".json"):
            with open(os.path.join(all_tasks_dir, fname)) as f:
                all_tasks.append(json.load(f))

from lib.context.utils import read_json
csg = read_json(os.path.join(context_dir, "semantic-graph.json"))
project_map = read_json(os.path.join(context_dir, "project-map.json"))

from lib.decomposition_gate import check_decomposition
result = check_decomposition(
    all_tasks,
    project_map=project_map if project_map else {},
    csg=csg if csg else None,
)

print(json.dumps(result))
PYTHON_EOF
}


context_classify_failure() {
    local task_json_path="$1"
    local agent_output="${2:-}"
    local escalated="${3:-false}"
    local timed_out="${4:-false}"

    $(_context_python) - "$task_json_path" "$escalated" "$timed_out" <<PYTHON_EOF
import sys, os, json
sys.path.insert(0, os.environ.get("SPEED_DIR", "."))

task_json_path = sys.argv[1]
escalated = sys.argv[2] == "true" if len(sys.argv) > 2 else False
timed_out = sys.argv[3] == "true" if len(sys.argv) > 3 else False

project_root = os.environ.get("PROJECT_ROOT", ".")
context_dir = os.path.join(project_root, ".speed", "context")
task_id = os.path.basename(task_json_path).replace(".json", "")
task_context_dir = os.path.join(context_dir, "tasks", task_id, "context")

with open(task_json_path) as f:
    task = json.load(f)

agent_output = """${agent_output}"""

from lib.context.utils import read_json
budget = read_json(os.path.join(task_context_dir, "budget.json"))

# Build gate results from task JSON if available
gate_results = task.get("gate_results", {})

from lib.failure_classify import classify_failure
result = classify_failure(
    budget=budget if budget else None,
    gate_results=gate_results,
    agent_output=agent_output,
    task=task,
    escalated=escalated,
    timed_out=timed_out,
)

print(json.dumps(result))
PYTHON_EOF
}


context_spec_traceability() {
    local spec_content="$1"
    local all_tasks_dir="$2"

    $(_context_python) - "$all_tasks_dir" <<PYTHON_EOF
import sys, os, json
sys.path.insert(0, os.environ.get("SPEED_DIR", "."))

all_tasks_dir = sys.argv[1]

spec_content = """${spec_content}"""

# Load tasks
all_tasks = []
if os.path.isdir(all_tasks_dir):
    for fname in sorted(os.listdir(all_tasks_dir)):
        if fname.endswith(".json"):
            with open(os.path.join(all_tasks_dir, fname)) as f:
                all_tasks.append(json.load(f))

from lib.spec_traceability import spec_to_task_check, format_uncovered_for_verifier
result = spec_to_task_check(spec_content, all_tasks)

# Print formatted output (for injection into verifier prompt)
formatted = format_uncovered_for_verifier(result)
if formatted:
    print(formatted)
else:
    print("## Spec Coverage\n\nAll requirements covered by the task plan.\n")
PYTHON_EOF
}

# ── Related Spec Compression ─────────────────────────────────

context_score_and_compress_specs() {
    local primary_specs_json="$1"    # JSON: {path: content}
    local related_specs_json="$2"    # JSON: {path: content}
    local project_root="$3"         # Absolute path for resolving relative links
    local budget="${4:-15000}"
    local threshold="${5:-0.05}"
    local candidate_cap="${6:-50}"

    local tmp_primary tmp_related
    tmp_primary=$(mktemp "${TMPDIR:-/tmp}/_speed_primary_XXXXXX")
    tmp_related=$(mktemp "${TMPDIR:-/tmp}/_speed_related_XXXXXX")
    echo "$primary_specs_json" > "$tmp_primary"
    echo "$related_specs_json" > "$tmp_related"

    $(_context_python) - "$tmp_primary" "$tmp_related" "$project_root" "$budget" "$threshold" "$candidate_cap" <<'PYTHON_EOF'
import sys, os, json
sys.path.insert(0, os.environ.get("SPEED_DIR", "."))

primary_path = sys.argv[1]
related_path = sys.argv[2]
project_root = sys.argv[3]
budget = int(sys.argv[4])
threshold = float(sys.argv[5])
candidate_cap = int(sys.argv[6])

with open(primary_path) as f:
    primary_specs = json.load(f)
with open(related_path) as f:
    related_specs = json.load(f)

from lib.context.related_specs import score_and_assemble_specs, ScoringError

try:
    assembled, scoring_log = score_and_assemble_specs(
        primary_specs, related_specs, project_root, budget, threshold, candidate_cap
    )
except ScoringError as e:
    # Hard stop: print diagnostics + error message, exit non-zero
    for entry in e.scoring_log:
        signals = ", ".join(entry["signals"]) if entry["signals"] else "tfidf only"
        print(
            f"  {entry['path']:50s} score={entry['score']:.4f} [{signals}] {entry['disposition'].upper()}",
            file=sys.stderr,
        )
    print(f"HARD STOP: {e}", file=sys.stderr)
    sys.exit(1)

# Diagnostics to stderr (visible in logs, not in output)
for entry in scoring_log:
    signals = ", ".join(entry["signals"]) if entry["signals"] else "tfidf only"
    print(
        f"  {entry['path']:50s} score={entry['score']:.4f} [{signals}] {entry['disposition'].upper()}",
        file=sys.stderr,
    )
if scoring_log:
    included = sum(1 for e in scoring_log if e["disposition"] == "included")
    print(f"  {included}/{len(scoring_log)} specs included", file=sys.stderr)

print(assembled)
PYTHON_EOF

    rm -f "$tmp_primary" "$tmp_related"
}

# ── Spec Splitting (Fix 4) ────────────────────────────────────

context_split_spec_for_phase() {
    local spec_content="$1"
    local exclude_headings_json="$2"   # JSON array of heading strings

    $(_context_python) -c "
import sys, os, json
sys.path.insert(0, os.environ.get('SPEED_DIR', '.'))
from lib.context.spec_split import split_spec_for_phase

spec = sys.stdin.read()
exclude = json.loads(sys.argv[1])
print(split_spec_for_phase(spec, exclude))
" "$exclude_headings_json" <<< "$spec_content"
}

context_verify_spec_split() {
    local original="$1"
    local phase1="$2"
    local phase2="$3"
    local p1_sections_json="$4"   # JSON array
    local p2_sections_json="$5"   # JSON array

    local tmpdir
    tmpdir=$(mktemp -d)
    trap "rm -rf '$tmpdir'" RETURN
    printf '%s' "$original" > "${tmpdir}/orig"
    printf '%s' "$phase1" > "${tmpdir}/p1"
    printf '%s' "$phase2" > "${tmpdir}/p2"

    $(_context_python) -c "
import sys, os, json
sys.path.insert(0, os.environ.get('SPEED_DIR', '.'))
from lib.context.spec_split import verify_spec_split

tmpdir = sys.argv[1]
p1_sec = json.loads(sys.argv[2])
p2_sec = json.loads(sys.argv[3])

with open(f'{tmpdir}/orig') as f: orig = f.read()
with open(f'{tmpdir}/p1') as f: p1 = f.read()
with open(f'{tmpdir}/p2') as f: p2 = f.read()

result = verify_spec_split(orig, p1, p2, p1_sec, p2_sec)
print(json.dumps(result))
" "$tmpdir" "$p1_sections_json" "$p2_sections_json"
}


context_assemble_security_auditor() {
    local feature_name="$1"

    $(_context_python) - "$feature_name" <<'PYTHON_EOF'
import sys, os, json

feature_name = sys.argv[1]
project_root = os.environ.get("PROJECT_ROOT", ".")

feature_dir = os.path.join(project_root, ".speed", "features", feature_name)
tasks_dir = os.path.join(feature_dir, "tasks")

# Collect files_touched from all task JSON files
files_touched = set()
if os.path.isdir(tasks_dir):
    for fname in sorted(os.listdir(tasks_dir)):
        if fname.endswith(".json"):
            try:
                with open(os.path.join(tasks_dir, fname)) as f:
                    task = json.load(f)
                for path in task.get("files_touched", []):
                    if path:
                        files_touched.add(path)
            except Exception:
                pass

files_touched = sorted(files_touched)

# Load file contents from worktree (skip files that don't exist)
file_contents = {}
for path in files_touched:
    full_path = os.path.join(project_root, path)
    if os.path.isfile(full_path):
        try:
            with open(full_path) as f:
                file_contents[path] = f.read()
        except Exception:
            pass

# Load specs
product_spec = ""
product_spec_path = os.path.join(project_root, "specs", "product", f"{feature_name}.md")
if os.path.isfile(product_spec_path):
    with open(product_spec_path) as f:
        product_spec = f.read()

tech_spec = ""
tech_spec_path = os.path.join(project_root, "specs", "tech", f"{feature_name}.md")
if os.path.isfile(tech_spec_path):
    with open(tech_spec_path) as f:
        tech_spec = f.read()

# Load project conventions
agent_file_text = ""
agent_file_path = os.path.join(project_root, os.environ.get("SPEED_AGENT_FILE") or "CLAUDE.md")
if os.path.isfile(agent_file_path):
    with open(agent_file_path) as f:
        agent_file_text = f.read()

# Assemble prompt
parts = []
parts.append(f"# Security Audit: {feature_name}\n")

parts.append(f"## Files in scope\n\n{len(file_contents)} file(s) in scope.\n")
for path, content in sorted(file_contents.items()):
    parts.append(f"### {path}\n\n```\n{content}\n```\n")

if product_spec:
    parts.append(f"## Product spec\n\n{product_spec}\n")

if tech_spec:
    parts.append(f"## Tech spec\n\n{tech_spec}\n")

if agent_file_text:
    parts.append(f"## Project conventions\n\n{agent_file_text}\n")

print("\n".join(parts))
PYTHON_EOF
}


# ── Repository Digest ────────────────────────────────────────────

context_repository_digest_status() {
    # Prints {"load_status": "missing"|"malformed"|"ok", "digest": {...}|null, "reason": str|null}
    $(_context_python) - <<'PYTHON_EOF'
import sys, os, json
sys.path.insert(0, os.environ.get("SPEED_DIR", "."))
from lib.context.repository_digest import load_repository_digest_with_status

project_root = os.environ.get("PROJECT_ROOT", ".")
load_status, digest, reason = load_repository_digest_with_status(project_root)
print(json.dumps({"load_status": load_status, "digest": digest, "reason": reason}))
PYTHON_EOF
}

context_build_repository_digest() {
    local narrative="${1:-false}"
    local rebuild_discovery="${2:-false}"

    if [[ "$rebuild_discovery" == "true" ]]; then
        context_build_layer1 true >/dev/null
    fi

    $(_context_python) - "$narrative" <<'PYTHON_EOF'
import sys, os, json
sys.path.insert(0, os.environ.get("SPEED_DIR", "."))
from lib.context.repository_digest import build_repository_digest, DigestInputError
from lib.context.utils import load_speed_toml

project_root = os.environ.get("PROJECT_ROOT", ".")
narrative = sys.argv[1] == "true"
config = load_speed_toml(project_root)
try:
    digest = build_repository_digest(project_root, config=config, narrative=narrative)
    print(json.dumps({"ok": True, "status": digest["status"], "warnings": digest["warnings"]}))
except DigestInputError as e:
    print(json.dumps({"ok": False, "error": str(e)}))
    sys.exit(1)
PYTHON_EOF
}

context_project_repository_digest_markdown() {
    local token_budget="${1:-4000}"
    $(_context_python) - "$token_budget" <<'PYTHON_EOF'
import sys, os
sys.path.insert(0, os.environ.get("SPEED_DIR", "."))
from lib.context.repository_digest import attach_effective_state, load_repository_digest, project_digest_for_agent
from lib.context.utils import load_speed_toml

project_root = os.environ.get("PROJECT_ROOT", ".")
token_budget = int(sys.argv[1])
digest = load_repository_digest(project_root)
if digest is None:
    sys.exit(1)
digest = attach_effective_state(project_root, digest, config=load_speed_toml(project_root))
sys.stdout.write(project_digest_for_agent(digest, token_budget=token_budget))
PYTHON_EOF
}
