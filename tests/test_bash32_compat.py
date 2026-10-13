"""Exercise real planning and status logic under Bash 3.2 and modern Bash.

Agent responses are deterministic fixtures; no external agent is launched.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BASHES = [p for p in ('/bin/bash', '/opt/homebrew/bin/bash') if Path(p).exists()]

class BashCompatibility(unittest.TestCase):
    def shell(self, bash, code, directory):
        env = os.environ.copy()
        env.update(PATH='/opt/homebrew/bin:/usr/bin:/bin', ROOT=str(ROOT),
                   PROJECT=str(directory), PYTHON=sys.executable)
        return subprocess.run([bash, '-c', 'set -euo pipefail\n' + code],
                              env=env, text=True, capture_output=True, timeout=30)

    def test_version_gate_accepts_test_interpreters(self):
        source = (ROOT / 'lib/deps.sh').read_text()
        function = source[source.index('_check_bash_version() {'):source.index('\n_check_git() {')]
        with tempfile.TemporaryDirectory() as tmp:
            for bash in BASHES:
                with self.subTest(bash=bash):
                    r = self.shell(bash, '_deps_os=Darwin; _detect_os() { :; }; log_error_block() { echo "$*"; };\n' + function + '\n_check_bash_version', tmp)
                    self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_status_counts_and_sorts_failure_classes(self):
        source = (ROOT / 'lib/cmd/status.sh').read_text()
        block = source[source.index('    # Failure classification breakdown'):source.index('    # Latest supervisor analysis')]
        for classes in ([], [('pipeline','z'), ('complexity','a'), ('pipeline','z'), ('pipeline','b')]):
            with tempfile.TemporaryDirectory() as tmp:
                for i, (cls, sub) in enumerate(classes):
                    Path(tmp, f'{i}.json').write_text(json.dumps({'failure_classification': {'class': cls, 'subclass': sub}}))
                # An unclassified task should never create a count entry.
                Path(tmp, 'unclassified.json').write_text('{}')
                for bash in BASHES:
                    with self.subTest(bash=bash, classes=classes):
                        r = self.shell(bash, 'TASKS_DIR="$PROJECT"\nBOLD="" RESET="" COLOR_WARN="" COLOR_ERROR="" COLOR_DIM="" SYM_WARN=""\ncheck_status() {\n' + block + '\n}\ncheck_status', tmp)
                        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                        if classes:
                            self.assertIn('4 classified failures', r.stdout)
                            self.assertIn('complexity:a: 1', r.stdout)
                            self.assertIn('pipeline:b: 1', r.stdout)
                            self.assertIn('pipeline:z: 2', r.stdout)
                            self.assertLess(r.stdout.index('complexity:a'), r.stdout.index('pipeline:b'))
                            self.assertLess(r.stdout.index('pipeline:b'), r.stdout.index('pipeline:z'))
                        else:
                            self.assertNotIn('Failure Classification:', r.stdout)

    def test_planning_single_split_and_defect_modes(self):
        for mode in ('single', 'split', 'defect'):
            for bash in BASHES:
                with self.subTest(bash=bash, mode=mode), tempfile.TemporaryDirectory(prefix='spec space ') as tmp:
                    project = Path(tmp)
                    for kind in ('tech', 'product', 'design'):
                        p = project / f'specs/{kind}/payments.md'
                        p.parent.mkdir(parents=True)
                        p.write_text(f'# {kind}\n## Foundation\n{kind}-foundation\n## Features\n{kind}-features\n')
                    defect = project / 'fee.md'
                    defect.write_text('# Defect: fee rounding\n\n## Observed Behavior\nFee rounds down.\n')
                    code = r'''
export SPEED_PROJECT_ROOT="$PROJECT"
source "$ROOT/lib/config.sh"
source "$ROOT/lib/log.sh"
source "$ROOT/lib/cmd/plan.sh"
GLOBAL_FEATURE=compat
FEATURE_DIR="$PROJECT/.speed/features/compat"
LOGS_DIR="$FEATURE_DIR/logs"
mkdir -p "$LOGS_DIR"
feature_activate() { :; }; feature_set_active() { :; }; _save_spec_path() { :; }
_run_guardian() { return 0; }
_plan_cache_valid() { return 1; }
_plan_cache_write() {
    if [[ "$1" == architect ]]; then
        printf '%s\n' "$3" > "$PROJECT/result.json"
        exit 0
    fi
}
_log_gate_skip() { :; }; _prune_logs() { :; }
parse_agent_json() { printf '%s\n' "$1"; }
context_build_layer1() { echo '{"status":"built"}'; }
context_assemble_architect() { echo 'codebase context'; }
cmd_audit() {
    # Design has no phase assignment: full content must appear in both phases.
    if [[ "$1" == */design/* ]]; then
        echo '{"sizing":{"estimated_tasks":1}}' > "$AUDIT_OUTPUT_FILE"
    elif [[ "$1" == */product/* ]]; then
        echo '{"sizing":{"estimated_tasks":99,"phase_sections":{"phase_1":[1],"phase_2":[0]}}}' > "$AUDIT_OUTPUT_FILE"
    else
        echo '{"sizing":{"estimated_tasks":99,"phase_sections":{"phase_1":[0],"phase_2":[1]}}}' > "$AUDIT_OUTPUT_FILE"
    fi
}
context_split_spec_for_phase() {
    PYTHONPATH="$ROOT" "$PYTHON" -c 'import sys,json; from lib.context.spec_split import split_spec_for_phase; print(split_spec_for_phase(sys.argv[1],json.loads(sys.argv[2])))' "$1" "$2"
}
context_verify_spec_split() { echo '{"pass":true,"warnings":[]}'; }
_run_architect_phase() {
    printf '%s\n' "$2" > "$PROJECT/$1.txt"
    local id=1
    [[ "$1" == 'Architect (Phase 2)' ]] && id=2
    printf '{"tasks":[{"id":%s,"title":"task","depends_on":[],"files_touched":[],"description":"task"}],"contract":{"entities":[],"relationships":[]}}\n' "$id"
}
'''
                    if mode == 'defect':
                        code += '\ncmd_plan --defects "$PROJECT/fee.md"\n'
                    elif mode == 'single':
                        code += '\ncmd_plan "$PROJECT/specs/tech/payments.md" --skip-audit\n'
                    else:
                        code += '\ncmd_plan "$PROJECT/specs/tech/payments.md"\n'
                    r = self.shell(bash, code, tmp)
                    self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                    result = json.loads((project / 'result.json').read_text())
                    self.assertEqual(len(result['tasks']), 2 if mode == 'split' else 1)
                    if mode == 'split':
                        p1 = (project / 'Architect (Phase 1).txt').read_text()
                        p2 = (project / 'Architect (Phase 2).txt').read_text()
                        self.assertIn('tech-foundation', p1)
                        self.assertNotIn('tech-features', p1)
                        self.assertIn('product-features', p1)
                        self.assertNotIn('product-foundation', p1)
                        self.assertIn('tech-features', p2)
                        self.assertNotIn('tech-foundation', p2)
                        self.assertIn('product-foundation', p2)
                        for prompt in (p1, p2):
                            self.assertIn('design-foundation', prompt)
                            self.assertIn('design-features', prompt)
                    elif mode == 'defect':
                        self.assertIn('Fee rounds down', (project / 'Architect.txt').read_text())

if __name__ == '__main__':
    unittest.main()
