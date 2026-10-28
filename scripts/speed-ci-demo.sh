#!/usr/bin/env bash
# Build a small demo project that exercises every speed ci check, then run speed ci in it.
#
#   scripts/speed-ci-demo.sh [DIR]      (default: ./speed-ci-demo)
#
# Phase 1: eval, lint, typecheck, test, e2e, secrets, sast, sca.
# Phase 2: a custom check (api), Trivy, Gitleaks and CodeQL (from sample outputs, so
# no scanner has to be installed) and SonarQube when SONAR_HOST_URL and SONAR_TOKEN
# are set (sonar-scanner on PATH, or SONAR_SCANNER pointing at it).
# Nothing here calls a model.
set -euo pipefail

SPEED_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SPEED="${SPEED_HOME}/speed"
DIR="${1:-./speed-ci-demo}"

if [[ -e "$DIR" && -n "$(ls -A "$DIR" 2>/dev/null)" ]]; then
    echo "error: $DIR already exists and is not empty; pass another directory" >&2
    exit 3
fi

# The test gate and the eval run pytest; use a Python that has it.
PY=""
for candidate in "${SPEED_PYTHON:-}" "${SPEED_HOME}/.venv/bin/python3" python3; do
    if [[ -n "$candidate" ]] && "$candidate" -m pytest --version > /dev/null 2>&1; then
        PY="$candidate"
        break
    fi
done
if [[ -z "$PY" ]]; then
    echo "error: no Python with pytest found; run: python3 -m pip install pytest" >&2
    exit 3
fi

mkdir -p "$DIR/tests" "$DIR/specs/tests" "$DIR/.speed/features/adding/tasks"
DIR="$(cd "$DIR" && pwd)"
cd "$DIR"
git init -q -b main

cat > app.py <<'EOF'
def add(a, b):
    return a + b
EOF
cat > tests/test_app.py <<'EOF'
from app import add


def test_add():
    assert add(1, 2) == 3
EOF
printf '.speed/\n__pycache__/\n.pytest_cache/\n.scannerwork/\n' > .gitignore
echo 'requests==2.0.0' > requirements.txt

cat > AGENTS.md <<EOF
# speed ci demo

## Quality Gates

- lint: ${PY} -m py_compile app.py
- typecheck: ${PY} -c "import app"
- test: ${PY} -m pytest -q -p no:cacheprovider tests
- e2e: ${PY} -c "from app import add; assert add(2, 2) == 4"
- api: ${PY} -c "print('api contract ok')"
EOF

# A finished SPEED feature, so the eval check has something to accept.
cat > specs/tests/adding.md <<'EOF'
# Test Spec: Adding

## Scenario Catalog
| ID | Scenario | Level | Expected outcome |
|---|---|---|---|
| AC-01 | Add two numbers | unit | Returns their sum |

## Execution and Evidence
| Scenario | Selector | Command | Criterion |
|---|---|---|---|
| AC-01 | `tests/test_app.py::test_add` | | |
EOF
echo '{"status": "completed"}' > .speed/features/adding/state.json
cat > .speed/features/adding/tasks/1.json <<'EOF'
{"id": "1", "title": "Add two numbers", "status": "done", "required_test_cases": ["AC-01"],
 "test_selectors": ["tests/test_app.py::test_add"], "files_touched": ["app.py"],
 "acceptance_criteria": [], "depends_on": []}
EOF

# Sample scanner outputs in each tool's real format. The medium findings are below
# the "high" threshold, so they are counted but do not fail the run.
cat > semgrep.json <<'EOF'
{"results": [{"check_id": "python.lang.best-practice.example", "path": "app.py", "start": {"line": 2},
  "extra": {"severity": "WARNING", "message": "Example medium finding"}}]}
EOF
echo '{"dependencies": [{"name": "requests", "version": "2.0.0", "vulns": []}], "fixes": []}' > pip-audit.json
cat > trivy.json <<'EOF'
{"SchemaVersion": 2, "Results": [{"Target": "requirements.txt", "Vulnerabilities": [
  {"VulnerabilityID": "CVE-2024-0001", "PkgName": "requests", "Severity": "MEDIUM", "Title": "Example medium vulnerability"}]}]}
EOF
echo '[]' > gitleaks.json
echo '{"version": "2.1.0", "runs": [{"tool": {"driver": {"name": "CodeQL", "rules": []}}, "results": []}]}' > codeql.sarif

cat > speed.toml <<'EOF'
[security]
sast_cmd = "cat semgrep.json"
sca_cmd = "cat pip-audit.json"
severity_threshold = "high"

[ci]
security_mode = "strict"

[ci.tools.trivy]
format = "trivy"
cmd = "cat trivy.json"

[ci.tools.gitleaks]
format = "gitleaks"
cmd = "cat gitleaks.json"

[ci.tools.codeql]
format = "sarif"
cmd = "cat codeql.sarif"
EOF

if [[ -n "${SONAR_HOST_URL:-}" && -n "${SONAR_TOKEN:-}" ]]; then
    scanner="${SONAR_SCANNER:-$(command -v sonar-scanner || true)}"
    if [[ -z "$scanner" ]]; then
        echo "warning: SONAR_HOST_URL is set but sonar-scanner was not found; leaving SonarQube out" >&2
    else
        cat >> speed.toml <<EOF

[ci.sonarqube]
host_url = "${SONAR_HOST_URL}"
project_key = "speed-ci-demo"
scanner_cmd = "${scanner}"
EOF
        printf 'sonar.projectKey=speed-ci-demo\nsonar.sources=app.py\n' > sonar-project.properties
    fi
fi

git add -A
git -c user.name="speed ci demo" -c user.email=demo@example.invalid -c core.hooksPath=/dev/null \
    commit -qm "speed ci demo project"

echo "Demo project: $DIR"
echo
rc=0
"$SPEED" ci || rc=$?
cat <<EOF

Run it again with:  cd "$DIR" && speed ci
Reports:            $DIR/.speed/ci/ (report.json, speed-ci.sarif, junit.xml, logs/)
See a failure:      edit tests/test_app.py so the test fails and rerun speed ci
EOF
exit "$rc"
