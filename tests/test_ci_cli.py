"""speed ci: whole-project checks, the GitHub Actions workflow and PR creation.

Projects, remotes and the gh and claude stand-ins live under pytest's temporary
directory. The CLI skips only the global dependency preflight (grammar packages);
dispatch, gates, scans, eval and git use the real code. The claude stand-in
records every call, so each test can prove that speed ci never calls a model.
"""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

import pytest
import yaml


REPO = Path(__file__).resolve().parents[1]
PYTHON = shlex.quote(sys.executable)
AWS_KEY = "AKIA" + "ABCDEFGHIJKLMNOP"
SEMGREP = {"results": [{"check_id": "python.lang.security.eval", "path": "app.py",
                        "start": {"line": 3}, "extra": {"severity": "{severity}", "message": "Use of eval"}}]}


@pytest.fixture
def cli(tmp_path):
    entry = tmp_path / "speed-test"
    source = (REPO / "speed").read_text()
    source = source.replace('SCRIPT_DIR="$(cd "$(dirname "$_speed_source")" && pwd)"',
                            "SCRIPT_DIR=" + shlex.quote(str(REPO)))
    source = source.replace('source "${SCRIPT_DIR}/lib/deps.sh"', "# preflight omitted in isolated CLI tests")
    entry.write_text(source)
    return entry


@pytest.fixture
def tools(tmp_path):
    """Fake claude and gh on PATH. claude records any call; gh records its arguments."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    claude = bin_dir / "claude"
    claude.write_text(f"#!/bin/sh\necho \"$@\" >> {shlex.quote(str(tmp_path / 'claude-calls.log'))}\nexit 0\n")
    gh = bin_dir / "gh"
    gh.write_text(f"""#!/bin/sh
echo "$@" >> {shlex.quote(str(tmp_path / 'gh-calls.log'))}
case "$1 $2" in
  "auth status") exit 0 ;;
  "pr view") if [ -n "$FAKE_GH_OPEN_PR" ]; then echo "$FAKE_GH_OPEN_PR"; else exit 1; fi ;;
  "pr create") echo "https://github.com/acme/shop/pull/7" ;;
esac
exit 0
""")
    for tool in (claude, gh):
        tool.chmod(0o755)
    return bin_dir


class Project:
    def __init__(self, root, cli, tools):
        self.root, self.cli, self.tools = root, cli, tools
        root.mkdir()
        self.git("init", "-q", "-b", "main")
        (root / ".gitignore").write_text(".speed/\n__pycache__/\n.pytest_cache/\n")
        (root / "app.py").write_text("def add(a, b):\n    return a + b\n")
        (root / "tests").mkdir()
        (root / "tests/test_app.py").write_text("from app import add\n\ndef test_add():\n    assert add(1, 2) == 3\n")
        self.gates(test=f"{PYTHON} -m pytest -q -p no:cacheprovider tests")
        self.commit("initial")

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.root), *args], stderr=subprocess.PIPE, text=True).strip()

    def commit(self, message="change"):
        self.git("add", "-A")
        self.git("-c", "user.name=Tests", "-c", "user.email=tests@example.invalid",
                 "-c", "core.hooksPath=/dev/null", "commit", "-qm", message, "--allow-empty")

    def gates(self, **commands):
        lines = "".join(f"- {gate}: {command}\n" for gate, command in commands.items())
        (self.root / "AGENTS.md").write_text("# Project\n\n## Quality Gates\n\n" + lines)

    def toml(self, text):
        (self.root / "speed.toml").write_text(text)

    def run(self, *args, json_output=False, extra_env=None):
        env = {key: value for key, value in os.environ.items() if not key.endswith("_API_KEY")}
        env.pop("SPEED_CI", None)
        env.pop("SPEED_AGENT_FILE", None)
        env.update(SPEED_PROJECT_ROOT=str(self.root), SPEED_PYTHON=sys.executable, PYTHONDONTWRITEBYTECODE="1",
                   PATH=f"{self.tools}{os.pathsep}{env['PATH']}", CLAUDE_BIN=str(self.tools / "claude"),
                   GIT_AUTHOR_NAME="Tests", GIT_AUTHOR_EMAIL="tests@example.invalid",
                   GIT_COMMITTER_NAME="Tests", GIT_COMMITTER_EMAIL="tests@example.invalid")
        env.update(extra_env or {})
        argv = ["bash", str(self.cli), *(["--json"] if json_output else []), "ci", *args]
        return subprocess.run(argv, env=env, cwd=self.root, text=True, capture_output=True, timeout=120)

    def report(self):
        return json.loads((self.root / ".speed/ci/report.json").read_text())


@pytest.fixture
def project(tmp_path, cli, tools):
    yield Project(tmp_path / "shop project", cli, tools)
    assert not (tmp_path / "claude-calls.log").exists(), "speed ci called the model CLI"


def step(report, name):
    return next(item for item in report["steps"] if item["name"] == name)


def test_a_passing_project_passes_every_check_it_has(project):
    project.gates(lint="true", typecheck="true", test=f"{PYTHON} -m pytest -q -p no:cacheprovider tests")
    project.commit()
    result = project.run()
    assert result.returncode == 0, result.stdout + result.stderr
    report = project.report()
    assert report["passed"] is True
    assert {item["name"]: item["status"] for item in report["steps"]} == {
        "lint": "pass", "typecheck": "pass", "test": "pass", "e2e": "skipped", "secrets": "pass",
        "sast": "skipped", "sca": "skipped", "eval": "skipped"}
    assert report["commit"] == project.git("rev-parse", "HEAD")
    assert "PASSED" in result.stdout


def test_a_failing_test_fails_ci_and_keeps_its_log(project):
    (project.root / "tests/test_app.py").write_text("def test_broken():\n    assert 1 == 2\n")
    project.commit()
    result = project.run()
    assert result.returncode == 2
    test = step(project.report(), "test")
    assert test["status"] == "fail"
    log = project.root / test["commands"][0]["log"]
    assert "test_broken" in log.read_text()
    assert "FAILED" in result.stdout


def test_ci_fails_when_no_test_command_is_configured(project):
    project.gates(lint="true")
    project.commit()
    result = project.run()
    assert result.returncode == 2
    assert step(project.report(), "test")["status"] == "fail"


def test_end_to_end_tests_run_when_the_project_configures_them(project):
    project.gates(test="true", e2e="echo checkout flow broke && exit 1")
    project.commit()
    result = project.run()
    assert result.returncode == 2
    e2e = step(project.report(), "e2e")
    assert e2e["status"] == "fail" and e2e["commands"][0]["exit_code"] == 1


def test_skip_leaves_a_check_out_and_rejects_unknown_names(project):
    project.gates(test="false")
    project.commit()
    assert project.run("--skip", "test").returncode == 0
    assert step(project.report(), "test")["status"] == "skipped"
    result = project.run("--skip", "deploy")
    assert result.returncode == 3 and "Unknown check" in result.stderr


def test_a_committed_secret_fails_ci_without_printing_the_secret(project):
    (project.root / "settings.py").write_text(f'AWS_KEY = "{AWS_KEY}"\n')
    (project.root / "package-lock.json").write_text(json.dumps({"integrity": "sha512-" + "A" * 60}))
    project.commit()
    result = project.run()
    assert result.returncode == 2
    secrets = step(project.report(), "secrets")
    assert secrets["status"] == "fail"
    assert {"pattern": "AWS Access Key", "file": "settings.py", "line": 1} in secrets["findings"]
    assert not any(item["file"] == "package-lock.json" for item in secrets["findings"])
    everything = result.stdout + result.stderr + (project.root / ".speed/ci/report.json").read_text()
    assert AWS_KEY not in everything


def test_code_scan_findings_fail_at_or_above_the_threshold(project):
    project.toml(f'[security]\nsast_cmd = "cat semgrep.json"\n')
    (project.root / "semgrep.json").write_text(json.dumps(SEMGREP).replace("{severity}", "ERROR"))
    project.commit()
    assert project.run().returncode == 2
    sast = step(project.report(), "sast")
    assert sast["status"] == "fail" and sast["blocking_findings"][0]["severity"] == "high"

    (project.root / "semgrep.json").write_text(json.dumps(SEMGREP).replace("{severity}", "WARNING"))
    project.commit()
    assert project.run().returncode == 0
    assert step(project.report(), "sast")["summary"] == "No findings at or above high (1 in all)"

    project.toml('[security]\nsast_cmd = "cat semgrep.json"\nseverity_threshold = "medium"\n')
    project.commit()
    assert project.run().returncode == 2


def test_a_scanner_that_crashes_fails_ci(project):
    project.toml('[security]\nsast_cmd = "echo boom >&2; exit 2"\n')
    project.commit()
    assert project.run().returncode == 2
    assert "did not print exactly one JSON document" in step(project.report(), "sast")["summary"]


def test_dependency_scan_findings_name_the_package(project):
    audit = {"vulnerabilities": {"lodash": {"severity": "critical", "via": [{"title": "Prototype pollution"}]}}}
    (project.root / "audit.json").write_text(json.dumps(audit))
    project.toml('[security]\nsca_cmd = "cat audit.json; exit 1"\n')
    project.commit()
    result = project.run()
    assert result.returncode == 2
    finding = step(project.report(), "sca")["blocking_findings"][0]
    assert finding == {"severity": "critical", "title": "Prototype pollution", "package": "lodash"}
    assert "lodash" in result.stderr


def write_feature(project, name, status="done", branch=None):
    feature = project.root / ".speed/features" / name
    (feature / "tasks").mkdir(parents=True)
    (feature / "state.json").write_text(json.dumps({"status": "completed"}))
    task = {"id": "1", "title": "Add", "status": status, "required_test_cases": ["AC-01"],
            "test_selectors": ["tests/test_app.py::test_add"], "files_touched": ["app.py"],
            "acceptance_criteria": [], "depends_on": []}
    if branch:
        task["branch"] = branch
    (feature / "tasks/1.json").write_text(json.dumps(task))
    return feature


def test_eval_accepts_a_finished_feature_and_skips_one_in_progress(project):
    spec = project.root / "specs/tests/adding.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("# Test Spec: Adding\n## Scenario Catalog\n| ID | Scenario | Level | Expected outcome |\n"
                    "|---|---|---|---|\n| AC-01 | Add two numbers | unit | Their sum |\n\n"
                    "## Execution and Evidence\n| Scenario | Selector | Command | Criterion |\n|---|---|---|---|\n"
                    "| AC-01 | `tests/test_app.py::test_add` | | |\n")
    project.commit()
    write_feature(project, "adding")
    in_progress = write_feature(project, "subtracting", status="pending")
    (in_progress / "test_spec_path").write_text(str(spec))
    result = project.run()
    assert result.returncode == 0, result.stdout + result.stderr
    features = {item["feature"]: item for item in step(project.report(), "eval")["features"]}
    assert features["adding"]["status"] == "pass"
    assert features["subtracting"]["status"] == "skipped"
    assert features["subtracting"]["reason"] == "Work in progress (pending)"


def test_json_output_is_one_report_object(project):
    result = project.run(json_output=True)
    assert result.returncode == 0
    assert json.loads(result.stdout) == project.report()


def test_init_writes_a_workflow_that_runs_speed_ci(project):
    (project.root / "package.json").write_text("{}")
    (project.root / "package-lock.json").write_text("{}")
    result = project.run("init", "--speed-repo", "acme/speed", "--speed-ref", "v1.2")
    assert result.returncode == 0, result.stderr
    path = project.root / ".github/workflows/speed-ci.yml"
    workflow = yaml.safe_load(path.read_text())
    triggers = workflow[True] if True in workflow else workflow["on"]
    assert triggers["push"]["branches"] == ["main"] and "pull_request" in triggers
    steps = workflow["jobs"]["speed-ci"]["steps"]
    speed = next(item for item in steps if item.get("name") == "Check out SPEED")
    assert speed["with"]["repository"] == "acme/speed" and speed["with"]["ref"] == "v1.2"
    commands = [item.get("run", "") for item in steps]
    assert "npm ci" in commands
    assert any("speed --json ci" in command for command in commands)
    assert "@" not in path.read_text().replace("@v", "")

    again = project.run("init", "--speed-repo", "acme/speed")
    assert again.returncode == 3 and "--force" in again.stderr
    assert project.run("init", "--speed-repo", "acme/speed", "--force").returncode == 0


def test_init_rejects_a_malformed_repository(project):
    result = project.run("init", "--speed-repo", "not a repo")
    assert result.returncode == 3


@pytest.fixture
def feature_branches(project, tmp_path):
    """A bare origin and two finished task branches for feature 'shop'."""
    origin = tmp_path / "origin.git"
    subprocess.check_call(["git", "init", "-q", "--bare", "-b", "main", str(origin)])
    project.git("remote", "add", "origin", "https://github.com/acme/shop.git")
    project.git("config", f"url.{origin}.insteadOf", "https://github.com/acme/shop.git")
    project.git("push", "-q", "origin", "main")
    feature = project.root / ".speed/features/shop"
    (feature / "tasks").mkdir(parents=True)
    (feature / "state.json").write_text(json.dumps({"status": "completed"}))
    for task_id, name in (("1", "cart"), ("2", "checkout")):
        branch = f"speed/shop/task-{task_id}-{name}"
        project.git("checkout", "-q", "-b", branch, "main")
        (project.root / f"{name}.py").write_text(f"NAME = '{name}'\n")
        project.commit(f"task {task_id}")
        (feature / "tasks" / f"{task_id}.json").write_text(json.dumps(
            {"id": task_id, "title": name.title(), "status": "done", "branch": branch,
             "depends_on": [] if task_id == "1" else ["1"]}))
    project.git("checkout", "-q", "main")
    return origin


def gh_calls(tmp_path):
    log = tmp_path / "gh-calls.log"
    return log.read_text().splitlines() if log.exists() else []


def test_pr_merges_task_branches_opens_a_pr_and_posts_a_passing_status(project, feature_branches, tmp_path):
    result = project.run("--pr")
    assert result.returncode == 0, result.stdout + result.stderr
    assert project.git("branch", "--show-current") == "main"
    pushed = subprocess.check_output(["git", "-C", str(feature_branches), "ls-tree", "--name-only",
                                      "speed-ci/shop"], text=True).split()
    assert {"cart.py", "checkout.py"} <= set(pushed)
    sha = subprocess.check_output(["git", "-C", str(feature_branches), "rev-parse", "speed-ci/shop"], text=True).strip()
    calls = gh_calls(tmp_path)
    create = next(call for call in calls if call.startswith("pr create"))
    assert "--base main" in create and "--head speed-ci/shop" in create and "--draft" not in create
    assert "--repo acme/shop" in create
    status = next(call for call in calls if call.startswith("api"))
    assert f"repos/acme/shop/statuses/{sha}" in status and "state=success" in status and "context=speed/ci" in status
    body = (project.root / ".speed/ci/pr-body.md").read_text()
    assert "1: Cart" in body and "| test | pass |" in body


def test_pr_with_failing_checks_opens_a_draft_and_posts_a_failure(project, feature_branches, tmp_path):
    project.gates(test="false")
    project.commit()
    project.git("push", "-q", "origin", "main")
    result = project.run("--pr")
    assert result.returncode == 2
    calls = gh_calls(tmp_path)
    assert "--draft" in next(call for call in calls if call.startswith("pr create"))
    assert "state=failure" in next(call for call in calls if call.startswith("api"))


def test_pr_stops_on_a_conflict_and_returns_to_the_original_branch(project, feature_branches, tmp_path):
    project.git("checkout", "-q", "speed/shop/task-2-checkout")
    (project.root / "cart.py").write_text("NAME = 'other'\n")
    project.commit("conflicting change")
    project.git("checkout", "-q", "main")
    result = project.run("--pr")
    assert result.returncode == 4
    assert "conflicts" in result.stderr
    assert project.git("branch", "--show-current") == "main"
    assert project.git("status", "--porcelain") == ""
    assert not any(call.startswith("pr create") for call in gh_calls(tmp_path))


def test_pr_requires_every_task_to_be_done(project, feature_branches):
    task = project.root / ".speed/features/shop/tasks/2.json"
    task.write_text(json.dumps({**json.loads(task.read_text()), "status": "running"}))
    result = project.run("--pr")
    assert result.returncode == 3 and "not done: 2 (running)" in result.stderr


def test_pr_leaves_uncommitted_work_alone_and_out_of_the_pr(project, feature_branches):
    (project.root / "app.py").write_text("changed = True\n")
    result = project.run("--pr")
    assert result.returncode == 0, result.stderr
    assert "not part of the PR" in result.stderr
    assert (project.root / "app.py").read_text() == "changed = True\n"
    pushed = subprocess.check_output(["git", "-C", str(feature_branches), "show", "speed-ci/shop:app.py"], text=True)
    assert "changed" not in pushed


def test_pr_dry_run_checks_locally_without_pushing(project, feature_branches, tmp_path):
    result = project.run("--pr", "--dry-run", json_output=True)
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["dry_run"] is True and output["passed"] is True and output["pr_url"] == ""
    assert gh_calls(tmp_path) == []
    remote = subprocess.run(["git", "-C", str(feature_branches), "rev-parse", "--verify", "speed-ci/shop"],
                            capture_output=True)
    assert remote.returncode != 0


def test_pr_only_options_need_pr(project):
    result = project.run("--draft")
    assert result.returncode == 3 and "only applies with --pr" in result.stderr


def test_eval_fails_a_finished_feature_that_is_not_accepted(project):
    (project.root / "tests/test_app.py").write_text("from app import add\n\ndef test_add():\n    assert add(1, 2) == 4\n")
    spec = project.root / "specs/tests/adding.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("# Test Spec: Adding\n## Scenario Catalog\n| ID | Scenario | Level | Expected outcome |\n"
                    "|---|---|---|---|\n| AC-01 | Add two numbers | unit | Their sum |\n\n"
                    "## Execution and Evidence\n| Scenario | Selector | Command | Criterion |\n|---|---|---|---|\n"
                    "| AC-01 | `tests/test_app.py::test_add` | | |\n")
    project.gates(test="true")
    project.commit()
    write_feature(project, "adding")
    assert project.run().returncode == 2
    assert step(project.report(), "eval")["features"][0]["status"] == "fail"


def test_eval_fails_a_feature_with_a_failed_task_or_a_lost_spec(project):
    write_feature(project, "broken", status="failed")
    lost = write_feature(project, "lost")
    (lost / "test_spec_path").write_text(str(project.root / "specs/tests/gone.md"))
    assert project.run().returncode == 2
    features = {item["feature"]: item["status"] for item in step(project.report(), "eval")["features"]}
    assert features == {"broken": "fail", "lost": "fail"}


def test_eval_in_ci_mode_does_not_need_local_state_or_task_branches(project):
    """A fresh CI checkout has neither the feature's state.json nor its task branches."""
    spec = project.root / "specs/tests/adding.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("# Test Spec: Adding\n## Scenario Catalog\n| ID | Scenario | Level | Expected outcome |\n"
                    "|---|---|---|---|\n| AC-01 | Add two numbers | unit | Their sum |\n\n"
                    "## Execution and Evidence\n| Scenario | Selector | Command | Criterion |\n|---|---|---|---|\n"
                    "| AC-01 | `tests/test_app.py::test_add` | | |\n")
    project.commit()
    feature = write_feature(project, "adding", branch="speed/adding/task-1-add")
    (feature / "state.json").unlink()
    result = project.run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert step(project.report(), "eval")["status"] == "pass"


def test_secrets_in_awkward_file_names_env_files_and_binary_marked_files_are_found(project):
    (project.root / "we:ird.txt").write_text(f"key = '{AWS_KEY}'\n")
    (project.root / ".env").write_text(f"AWS={AWS_KEY}\n")
    (project.root / ".gitattributes").write_text("*.cfg binary\n")
    (project.root / "deploy.cfg").write_text(f"x\n{AWS_KEY}\n")
    project.commit()
    project.git("config", "color.ui", "always")
    assert project.run().returncode == 2
    found = {(item["file"], item["line"]) for item in step(project.report(), "secrets")["findings"]
             if item["pattern"] == "AWS Access Key"}
    assert found == {("we:ird.txt", 1), (".env", 1), ("deploy.cfg", 2)}


def test_a_scanner_reporting_its_own_error_fails_ci(project):
    (project.root / "err.json").write_text(json.dumps({"error": {"code": "ENOLOCK", "summary": "no lockfile"}}))
    (project.root / "semgrep.json").write_text(json.dumps({"errors": [{"message": "bad rule"}], "results": []}))
    project.toml('[security]\nsca_cmd = "cat err.json; exit 1"\nsast_cmd = "cat semgrep.json; exit 7"\n')
    project.commit()
    assert project.run().returncode == 2
    report = project.report()
    assert "reported an error" in step(report, "sca")["summary"]
    assert step(report, "sast")["summary"] == "The scanner exited 7 without reporting any finding"


def test_an_unknown_scanner_format_with_a_failing_exit_fails_ci(project):
    (project.root / "trivy.json").write_text(json.dumps({"Results": [{"Vulnerabilities": [{"Severity": "HIGH"}]}]}))
    project.toml('[security]\nsca_cmd = "cat trivy.json; exit 1"\n')
    project.commit()
    assert project.run().returncode == 2
    assert "Unsupported scanner output" in step(project.report(), "sca")["summary"]


def test_pip_audit_2_output_is_read(project):
    audit = {"dependencies": [{"name": "django", "version": "2.0", "vulns": [{"id": "PYSEC-2019-1", "fix_versions": ["2.2"]}]}],
             "fixes": []}
    (project.root / "audit.json").write_text(json.dumps(audit))
    project.toml('[security]\nsca_cmd = "cat audit.json; exit 1"\n')
    project.commit()
    assert project.run().returncode == 2
    assert step(project.report(), "sca")["blocking_findings"][0]["package"] == "django"


def test_a_bad_severity_threshold_is_rejected(project):
    project.toml('[security]\nseverity_threshold = "urgent"\n')
    project.commit()
    result = project.run()
    assert result.returncode == 3 and "severity_threshold" in result.stderr
    project.toml('[security]\nseverity_threshold = "HIGH"\n')
    project.commit()
    assert project.run().returncode == 0


def test_no_model_function_can_run_under_speed_ci(tmp_path):
    """Every provider entry point is replaced, so even a code path that reaches one cannot call a model."""
    script = f"""
set -euo pipefail
SCRIPT_DIR={shlex.quote(str(REPO))}
export SPEED_PROJECT_ROOT={shlex.quote(str(tmp_path))} CLAUDE_BIN={shlex.quote(str(tmp_path / 'claude'))}
printf '#!/bin/sh\\ntouch {shlex.quote(str(tmp_path / 'called'))}\\n' > "$CLAUDE_BIN"; chmod +x "$CLAUDE_BIN"
source {shlex.quote(str(REPO / 'lib/config.sh'))}
source {shlex.quote(str(REPO / 'lib/log.sh'))}
source {shlex.quote(str(REPO / 'lib/provider.sh'))}
source {shlex.quote(str(REPO / 'lib/cmd/ci.sh'))}
_ci_forbid_models
for fn in provider_run provider_chat provider_spawn_bg _provider_stream_exec; do
    if declare -F "$fn" > /dev/null; then
        rc=0; "$fn" x y z > /dev/null 2>&1 || rc=$?
        [ "$rc" -eq 3 ] || {{ echo "$fn returned $rc"; exit 1; }}
    fi
done
echo checked
"""
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0 and "checked" in result.stdout, result.stdout + result.stderr
    assert not (tmp_path / "called").exists()


def test_speed_ci_starts_without_a_model_cli(project):
    result = project.run(extra_env={"CLAUDE_BIN": "/nonexistent/claude"})
    assert result.returncode == 0, result.stderr


def test_pr_refuses_to_use_the_base_or_a_task_branch_as_the_pr_branch(project, feature_branches):
    for name in ("main", "speed/shop/task-1-cart"):
        result = project.run("--pr", "--dry-run", "--branch", name)
        assert result.returncode == 3 and "cannot be" in result.stderr
    assert project.git("rev-parse", "main") == project.git("rev-parse", "origin/main")


def test_pr_will_not_overwrite_a_reviewers_commit_on_the_pr_branch(project, feature_branches):
    project.git("checkout", "-q", "-b", "review", "main")
    (project.root / "fix.py").write_text("FIX = 1\n")
    project.commit("reviewer fix")
    fix = project.git("rev-parse", "HEAD")
    project.git("push", "-q", "origin", "review:refs/heads/speed-ci/shop")
    project.git("checkout", "-q", "main")
    result = project.run("--pr")
    assert result.returncode == 3 and "pass --force" in result.stderr
    remote = subprocess.check_output(["git", "-C", str(feature_branches), "rev-parse", "speed-ci/shop"], text=True).strip()
    assert remote == fix
    assert project.run("--pr", "--force").returncode == 0


def test_pr_never_touches_the_users_checkout(project, feature_branches):
    project.git("checkout", "-q", "-b", "work", "main")
    (project.root / ".gitignore").write_text(".speed/\n__pycache__/\n.pytest_cache/\nlocal.env\n")
    project.commit("ignore local.env")
    (project.root / "local.env").write_text("TOKEN=mine\n")
    result = project.run("--pr", "--dry-run")
    assert result.returncode == 0, result.stderr
    assert (project.root / "local.env").read_text() == "TOKEN=mine\n"
    assert project.git("branch", "--show-current") == "work"
    assert "speed-ci/shop" not in project.git("branch", "--list")
    assert project.git("worktree", "list").count("\n") == 0


def test_pr_rejects_a_pr_branch_that_differs_from_main_only_by_case(project, feature_branches):
    result = project.run("--pr", "--dry-run", "--branch", "MAIN")
    assert result.returncode == 3 and "cannot be" in result.stderr


def test_pr_into_another_repository_names_the_head_owner(project, feature_branches, tmp_path):
    assert project.run("--pr", "--repo", "upstream/shop").returncode == 0
    create = next(call for call in gh_calls(tmp_path) if call.startswith("pr create"))
    assert "--repo upstream/shop" in create and "--head acme:speed-ci/shop" in create
    status = next(call for call in gh_calls(tmp_path) if call.startswith("api"))
    assert "repos/acme/shop/statuses/" in status


def test_pr_returns_to_a_detached_head(project, feature_branches):
    commit = project.git("rev-parse", "main")
    project.git("checkout", "-q", "--detach", "main")
    assert project.run("--pr", "--dry-run").returncode == 0
    assert project.git("rev-parse", "HEAD") == commit
    assert project.git("branch", "--show-current") == ""


def test_pr_fails_when_the_checks_change_tracked_files_and_leaves_the_user_clean(project, feature_branches, tmp_path):
    project.gates(test="true", lint="echo '# formatted' >> app.py")
    project.commit()
    project.git("push", "-q", "origin", "main")
    assert project.run("--pr").returncode == 2
    assert step(project.report(), "clean-tree")["status"] == "fail"
    assert project.git("branch", "--show-current") == "main"
    assert project.git("status", "--porcelain") == ""


def test_pr_updates_an_open_pr_and_marks_it_draft_when_checks_fail(project, feature_branches, tmp_path):
    project.gates(test="false")
    project.commit()
    project.git("push", "-q", "origin", "main")
    result = project.run("--pr", extra_env={"FAKE_GH_OPEN_PR": "https://github.com/acme/shop/pull/7"})
    assert result.returncode == 2
    calls = gh_calls(tmp_path)
    assert not any(call.startswith("pr create") for call in calls)
    assert any(call.startswith("pr edit speed-ci/shop --repo acme/shop --base main") for call in calls)
    assert any(call.startswith("pr ready") and "--undo" in call for call in calls)
    assert "state=failure" in next(call for call in calls if call.startswith("api"))


def test_pr_is_built_on_the_published_base_not_unpushed_commits(project, feature_branches):
    (project.root / "local.py").write_text("x = 1\n")
    project.commit("not pushed")
    assert project.run("--pr").returncode == 0
    pushed = subprocess.check_output(["git", "-C", str(feature_branches), "ls-tree", "--name-only", "speed-ci/shop"],
                                     text=True).split()
    assert "local.py" not in pushed and "cart.py" in pushed


def test_pr_cannot_skip_checks(project, feature_branches):
    result = project.run("--pr", "--skip", "test")
    assert result.returncode == 3 and "--skip cannot be used with --pr" in result.stderr


def test_pr_branch_names_are_never_run_as_code(project, feature_branches, tmp_path):
    marker = tmp_path / "PWNED"
    project.git("checkout", "-q", "-b", f"x$(touch${{IFS}}{marker})", "main")
    project.run("--pr", "--dry-run")
    assert not marker.exists()


def test_newer_semgrep_severities_block(project):
    (project.root / "semgrep.json").write_text(json.dumps(SEMGREP).replace("{severity}", "HIGH"))
    project.toml('[security]\nsast_cmd = "cat semgrep.json"\n')
    project.commit()
    assert project.run().returncode == 2
    assert step(project.report(), "sast")["blocking_findings"][0]["severity"] == "high"


def test_scanner_output_must_be_one_supported_document(project):
    good = json.dumps(SEMGREP).replace("{severity}", "ERROR")
    (project.root / "two.json").write_text(good + "\n" + json.dumps({"results": []}))
    (project.root / "sarif.json").write_text(json.dumps({"version": "2.1.0", "runs": [{"results": [{"level": "error"}]}]}))
    (project.root / "advisories.json").write_text(json.dumps({"advisories": {"1": {"severity": "high"}}}))
    for sast, sca, expected in (("cat two.json", "", "exactly one JSON document"),
                                ("cat sarif.json", "", "Unsupported scanner output"),
                                ("", "cat advisories.json", "Unsupported scanner output")):
        project.toml(f'[security]\nsast_cmd = "{sast}"\nsca_cmd = "{sca}"\n')
        project.commit()
        assert project.run().returncode == 2
        kind = "sast" if sast else "sca"
        assert expected in step(project.report(), kind)["summary"]


def test_per_file_scanner_warnings_do_not_fail_a_clean_scan(project):
    (project.root / "semgrep.json").write_text(json.dumps(
        {"results": [], "errors": [{"level": "warn", "type": "PartialParsing", "message": "skipped a file"}]}))
    project.toml('[security]\nsast_cmd = "cat semgrep.json"\n')
    project.commit()
    assert project.run().returncode == 0
    assert step(project.report(), "sast")["scanner_warnings"] == 1


def test_a_command_that_never_finishes_is_stopped(project):
    project.toml("[ci]\ncommand_timeout = 2\n")
    project.gates(test="sleep 60")
    project.commit()
    assert project.run().returncode == 2
    assert step(project.report(), "test")["commands"][0]["timed_out"] is True


def test_project_commands_cannot_write_into_the_json_report(project):
    project.gates(test="echo injected >&3 || true")
    project.commit()
    result = project.run(json_output=True)
    assert json.loads(result.stdout)["passed"] is True


def test_two_runs_cannot_share_the_report(project):
    lock = project.root / ".speed/ci/.lock"
    lock.mkdir(parents=True)
    sleeper = subprocess.Popen(["sleep", "30"])
    try:
        (lock / "pid").write_text(str(sleeper.pid))
        result = project.run()
        assert result.returncode == 3 and "Another speed ci" in result.stderr
    finally:
        sleeper.kill()
        sleeper.wait()
    assert project.run().returncode == 0


def test_an_unknown_feature_is_rejected(project):
    result = project.run("--feature", "typo")
    assert result.returncode == 3 and "Unknown feature" in result.stderr
    assert not (project.root / ".speed/features/typo").exists()


def test_init_refuses_a_subdirectory_and_avoids_creating_a_lockfile(project, cli, tools):
    sub = Project.__new__(Project)
    sub.root, sub.cli, sub.tools = project.root / "web", cli, tools
    sub.root.mkdir()
    result = sub.run("init", "--speed-repo", "acme/speed", "--speed-ref", "v1")
    assert result.returncode == 3 and "repository root" in result.stderr
    (project.root / "package.json").write_text("{}")
    assert project.run("init", "--speed-repo", "acme/speed", "--speed-ref", "v1").returncode == 0
    assert "npm install --no-package-lock" in (project.root / ".github/workflows/speed-ci.yml").read_text()


def test_ci_mode_does_not_record_integration_in_the_feature_state(project):
    spec = project.root / "specs/tests/adding.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("# Test Spec: Adding\n## Scenario Catalog\n| ID | Scenario | Level | Expected outcome |\n"
                    "|---|---|---|---|\n| AC-01 | Add two numbers | unit | Their sum |\n\n"
                    "## Execution and Evidence\n| Scenario | Selector | Command | Criterion |\n|---|---|---|---|\n"
                    "| AC-01 | `tests/test_app.py::test_add` | | |\n")
    project.commit()
    feature = write_feature(project, "adding")
    (feature / "state.json").write_text(json.dumps({"status": "idle"}))
    assert project.run().returncode == 0
    state = json.loads((feature / "state.json").read_text())
    assert state["evaluation"]["integration_verified"] is False
    assert state["status"] == "idle"


def test_ci_mode_still_fails_a_task_branch_that_is_only_on_the_remote(project, tmp_path):
    spec = project.root / "specs/tests/adding.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("# Test Spec: Adding\n## Scenario Catalog\n| ID | Scenario | Level | Expected outcome |\n"
                    "|---|---|---|---|\n| AC-01 | Add two numbers | unit | Their sum |\n\n"
                    "## Execution and Evidence\n| Scenario | Selector | Command | Criterion |\n|---|---|---|---|\n"
                    "| AC-01 | `tests/test_app.py::test_add` | | |\n")
    project.commit()
    project.git("checkout", "-q", "-b", "speed/adding/task-1-add")
    (project.root / "extra.py").write_text("X = 1\n")
    project.commit("unmerged task work")
    project.git("checkout", "-q", "main")
    project.git("update-ref", "refs/remotes/origin/speed/adding/task-1-add", "speed/adding/task-1-add")
    project.git("branch", "-D", "speed/adding/task-1-add")
    write_feature(project, "adding", branch="speed/adding/task-1-add")
    assert project.run().returncode == 2
    assert step(project.report(), "eval")["features"][0]["status"] == "fail"


SPEC = ("# Test Spec: Adding\n## Scenario Catalog\n| ID | Scenario | Level | Expected outcome |\n"
        "|---|---|---|---|\n| AC-01 | Add two numbers | unit | Their sum |\n\n"
        "## Execution and Evidence\n| Scenario | Selector | Command | Criterion |\n|---|---|---|---|\n"
        "| AC-01 | `tests/test_app.py::test_add` | | |\n")


def test_an_unrecognised_severity_blocks(project):
    bandit = {"results": [{"filename": "app.py", "line_number": 1, "issue_severity": "UNDEFINED",
                           "issue_text": "Something odd", "test_id": "B000"}], "errors": [], "generated_at": "2026-10-27T00:00:00Z"}
    (project.root / "bandit.json").write_text(json.dumps(bandit))
    project.toml('[security]\nsast_cmd = "cat bandit.json"\n')
    project.commit()
    assert project.run().returncode == 2
    assert step(project.report(), "sast")["blocking_findings"][0]["severity"] == "unknown"


def test_a_command_that_ignores_term_is_still_reported_as_timed_out(project):
    project.toml("[ci]\ncommand_timeout = 1\n")
    project.gates(test="trap '' TERM; sleep 30")
    project.commit()
    assert project.run().returncode == 2
    assert step(project.report(), "test")["commands"][0]["timed_out"] is True


def test_ctrl_c_stops_the_running_check(project, tmp_path):
    marker = tmp_path / "still-running"
    project.gates(test=f"sleep 4; touch {shlex.quote(str(marker))}")
    project.commit()
    env = {key: value for key, value in os.environ.items() if not key.endswith("_API_KEY")}
    env.update(SPEED_PROJECT_ROOT=str(project.root), SPEED_PYTHON=sys.executable,
               PATH=f"{project.tools}{os.pathsep}{env['PATH']}", CLAUDE_BIN=str(project.tools / "claude"))
    proc = subprocess.Popen(["bash", str(project.cli), "ci"], env=env, cwd=project.root, start_new_session=True,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    import signal, time
    time.sleep(1.5)
    os.killpg(proc.pid, signal.SIGINT)
    proc.wait(timeout=20)
    time.sleep(4)
    assert not marker.exists()


def test_pr_evaluates_the_feature_state_it_checked_not_an_older_committed_copy(project, feature_branches, tmp_path):
    # The base has the feature committed with a pending task; locally the tasks are done.
    (project.root / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n.speed/ci/\n.speed/features/*/state.json\n")
    spec = project.root / "specs/tests/shop.md"
    spec.parent.mkdir(parents=True)
    spec.write_text(SPEC.replace("tests/test_app.py::test_add", "tests/test_app.py::test_missing"))
    tasks = project.root / ".speed/features/shop/tasks"
    done = {name: path.read_text() for name, path in ((p.name, p) for p in tasks.iterdir())}
    for path in tasks.iterdir():
        path.write_text(json.dumps({**json.loads(path.read_text()), "status": "pending"}))
    project.commit("feature state")
    project.git("push", "-q", "origin", "main")
    for name, text in done.items():
        (tasks / name).write_text(text)
    project.commit("tasks done")
    result = project.run("--pr", "--dry-run")
    assert result.returncode == 2, result.stdout + result.stderr
    assert step(project.report(), "eval")["features"][0]["status"] == "fail"


def test_pr_handles_an_absolute_test_spec_path(project, feature_branches):
    spec = project.root / "specs/tests/shop.md"
    spec.parent.mkdir(parents=True)
    spec.write_text(SPEC)
    project.commit()
    project.git("push", "-q", "origin", "main")
    (project.root / ".speed/features/shop/test_spec_path").write_text(str(spec))
    task = project.root / ".speed/features/shop/tasks/1.json"
    task.write_text(json.dumps({**json.loads(task.read_text()), "test_selectors": ["tests/test_app.py::test_add"],
                                "required_test_cases": ["AC-01"], "acceptance_criteria": [],
                                "files_touched": ["app.py"]}))
    result = project.run("--pr", "--dry-run")
    assert result.returncode == 0, result.stdout + result.stderr
    assert step(project.report(), "eval")["status"] == "pass"


def test_pr_links_dependencies_without_making_the_tree_dirty(project, feature_branches):
    (project.root / ".gitignore").write_text(".speed/\n__pycache__/\n.pytest_cache/\nnode_modules/\n")
    (project.root / "node_modules/left-pad").mkdir(parents=True)
    project.gates(test="test -d node_modules/left-pad && test -z \"$(git status --porcelain)\"")
    project.commit()
    project.git("push", "-q", "origin", "main")
    result = project.run("--pr", "--dry-run")
    assert result.returncode == 0, result.stdout + result.stderr


def test_pr_from_a_subdirectory_checks_that_subdirectory(project, feature_branches):
    app = project.root / "app"
    app.mkdir()
    for name in ("AGENTS.md", "app.py"):
        project.git("mv", name, f"app/{name}")
    project.git("mv", "tests", "app/tests")
    project.commit("move into app/")
    project.git("push", "-q", "origin", "main")
    (project.root / ".speed").rename(app / ".speed")
    sub = Project.__new__(Project)
    sub.root, sub.cli, sub.tools = app, project.cli, project.tools
    for path in (app / ".speed/features/shop/tasks").iterdir():
        task = json.loads(path.read_text())
        project.git("branch", "-f", task["branch"], "main")
    result = sub.run("--pr", "--dry-run")
    assert result.returncode == 0, result.stdout + result.stderr
    assert step(sub.report(), "test")["status"] == "pass"


def test_pr_and_a_plain_run_cannot_overlap(project, feature_branches):
    lock = project.root / ".speed/ci/.lock"
    lock.mkdir(parents=True)
    sleeper = subprocess.Popen(["sleep", "30"])
    try:
        (lock / "pid").write_text(str(sleeper.pid))
        result = project.run("--pr", "--dry-run")
        assert result.returncode == 3 and "Another speed ci" in result.stderr
    finally:
        sleeper.kill()
        sleeper.wait()
