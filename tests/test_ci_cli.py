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
    assert result.returncode == 3 and "--skip and --only cannot be used with --pr" in result.stderr


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


def test_ci_mode_leaves_the_feature_state_untouched(project):
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
    assert json.loads((feature / "state.json").read_text()) == {"status": "idle"}


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


def test_an_unreadable_speed_toml_stops_ci(project):
    project.toml("[ci]\ncommand_timeout = abc\n")
    project.commit()
    result = project.run()
    assert result.returncode == 3 and "speed.toml could not be parsed" in result.stderr


def test_failure_details_follow_the_failed_check(project):
    (project.root / "tests/test_app.py").write_text("def test_broken():\n    assert 1 == 2\n")
    project.commit()
    result = project.run()
    lines = (result.stdout + result.stderr).splitlines()
    # stdout and stderr are captured separately, so check order within stderr against the ✗ line on stdout.
    assert "test" in next(line for line in result.stdout.splitlines() if "✗" in line)
    assert any("exited 1; last lines of .speed/ci/logs/test-1.log" in line for line in lines)


def test_an_accepted_features_summary_is_kept_with_the_report(project):
    spec = project.root / "specs/tests/adding.md"
    spec.parent.mkdir(parents=True)
    spec.write_text(SPEC)
    project.commit()
    write_feature(project, "adding")
    assert project.run().returncode == 0
    assert "ACCEPTED" in (project.root / ".speed/ci/eval/adding-summary.md").read_text()


# ── Phase 2: custom checks, security mode, tools, SonarQube, parallel jobs, reports ──

def test_custom_quality_gates_run_as_their_own_checks(project):
    project.gates(test="true", api="echo api ok", coverage="echo 'coverage 40%' && exit 1")
    project.commit()
    assert project.run().returncode == 2
    report = project.report()
    assert step(report, "api")["status"] == "pass"
    assert step(report, "coverage")["status"] == "fail"
    assert [item["name"] for item in report["steps"]].index("api") < [item["name"] for item in report["steps"]].index("secrets")
    assert project.run("--skip", "coverage").returncode == 0


def test_ignored_gates_are_not_run(project):
    project.gates(test="true", deploy="exit 1")
    project.toml('[ci]\nignore_gates = ["deploy"]\n')
    project.commit()
    assert project.run().returncode == 0
    assert "deploy" not in {item["name"] for item in project.report()["steps"]}


def test_report_mode_warns_on_findings_instead_of_failing(project):
    (project.root / "semgrep.json").write_text(json.dumps(SEMGREP).replace("{severity}", "ERROR"))
    project.toml('[ci]\nsecurity_mode = "report"\n[security]\nsast_cmd = "cat semgrep.json"\n')
    project.commit()
    result = project.run()
    assert result.returncode == 0, result.stdout + result.stderr
    sast = step(project.report(), "sast")
    assert sast["status"] == "warn" and "report mode" in sast["summary"]
    assert project.report()["summary"]["warn"] == 1
    assert "1 warning(s)" in result.stdout


def test_report_mode_still_fails_a_crashing_scanner(project):
    project.toml('[ci]\nsecurity_mode = "report"\n[security]\nsast_cmd = "exit 2"\n')
    project.commit()
    assert project.run().returncode == 2
    assert step(project.report(), "sast")["status"] == "fail"


def test_report_mode_does_not_relax_the_secrets_scan(project):
    (project.root / "settings.py").write_text(f'KEY = "{AWS_KEY}"\n')
    project.toml('[ci]\nsecurity_mode = "report"\n')
    project.commit()
    assert project.run().returncode == 2
    assert step(project.report(), "secrets")["status"] == "fail"


def test_an_unknown_security_mode_is_rejected(project):
    project.toml('[ci]\nsecurity_mode = "loose"\n')
    project.commit()
    result = project.run()
    assert result.returncode == 3 and "security_mode" in result.stderr


def tool(project, name, fmt, payload, exit_code=0, extra=""):
    (project.root / f"{name}.json").write_text(json.dumps(payload))
    return f'[ci.tools.{name}]\nformat = "{fmt}"\ncmd = "cat {name}.json; exit {exit_code}"\n{extra}'


def test_trivy_gitleaks_and_sarif_tools_plug_in(project):
    trivy = {"SchemaVersion": 2, "Results": [{"Target": "package-lock.json", "Vulnerabilities": [
        {"VulnerabilityID": "CVE-2024-1", "PkgName": "lodash", "Severity": "CRITICAL", "Title": "Prototype pollution"}]}]}
    gitleaks = [{"RuleID": "aws-access-token", "File": "settings.py", "StartLine": 3, "Secret": AWS_KEY, "Match": AWS_KEY}]
    sarif_doc = {"version": "2.1.0", "runs": [{"tool": {"driver": {"name": "CodeQL", "rules": [
        {"id": "py/sql-injection", "properties": {"security-severity": "8.8"}}]}}, "results": [
        {"ruleId": "py/sql-injection", "level": "error", "message": {"text": "SQL built from user input"},
         "locations": [{"physicalLocation": {"artifactLocation": {"uri": "app.py"}, "region": {"startLine": 2}}}]}]}]}
    project.toml(tool(project, "trivy", "trivy", trivy) + tool(project, "gitleaks", "gitleaks", gitleaks, 1)
                 + tool(project, "codeql", "sarif", sarif_doc))
    project.commit()
    result = project.run()
    assert result.returncode == 2
    report = project.report()
    assert step(report, "trivy")["blocking_findings"][0] == {"severity": "critical", "title": "CVE-2024-1 Prototype pollution",
                                                            "file": "package-lock.json", "package": "lodash"}
    assert step(report, "gitleaks")["blocking_findings"][0]["file"] == "settings.py"
    assert step(report, "codeql")["blocking_findings"][0] == {"severity": "high", "title": "py/sql-injection SQL built from user input",
                                                             "file": "app.py", "line": 2}
    everything = result.stdout + result.stderr + "".join(
        path.read_text() for path in (project.root / ".speed/ci").rglob("*") if path.is_file())
    assert AWS_KEY not in everything
    assert "trivy" in project.run("--list").stdout.split()


def test_a_tool_that_needs_a_token_fails_without_it(project):
    snyk = {"ok": True, "vulnerabilities": []}
    project.toml(tool(project, "snyk", "snyk", snyk))
    project.commit()
    result = project.run(extra_env={"SNYK_TOKEN": ""})
    assert result.returncode == 2 and "SNYK_TOKEN is not set" in step(project.report(), "snyk")["summary"]
    assert project.run(extra_env={"SNYK_TOKEN": "t"}).returncode == 0


def test_tool_output_that_cannot_be_read_fails(project):
    project.toml(tool(project, "trivy", "trivy", {"not": "trivy"}))
    project.commit()
    assert project.run().returncode == 2
    assert "Could not read the trivy output" in step(project.report(), "trivy")["summary"]


class FakeSonar:
    """A local SonarQube API: /api/ce/task and /api/qualitygates/project_status."""

    def __init__(self, gate_status, conditions=()):
        import http.server
        import threading
        sonar = self
        self.requests = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                sonar.requests.append((self.path, self.headers.get("Authorization")))
                if self.path.startswith("/api/ce/task"):
                    body = {"task": {"status": "SUCCESS", "analysisId": "A1"}}
                elif self.path.startswith("/api/qualitygates/project_status"):
                    body = {"projectStatus": {"status": gate_status, "conditions": list(conditions)}}
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                data = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()


def sonar_project(project, sonar, blocking="true"):
    scanner = project.root / "fake-scanner.sh"
    scanner.write_text("#!/bin/sh\nmkdir -p .scannerwork\necho \"$@\" > .scannerwork/args\n"
                       "printf 'ceTaskId=T1\\ndashboardUrl=%s/dashboard?id=shop\\n' "
                       f"{sonar.url} > .scannerwork/report-task.txt\n")
    scanner.chmod(0o755)
    (project.root / ".gitignore").write_text(".speed/\n__pycache__/\n.pytest_cache/\n.scannerwork/\n")
    project.toml(f'[ci.sonarqube]\nhost_url = "{sonar.url}"\nproject_key = "shop"\n'
                 f'scanner_cmd = "./fake-scanner.sh"\nblocking = "{blocking}"\nwait_timeout = "10"\n')
    project.commit()


def test_sonarqube_quality_gate_passes_and_links_the_dashboard(project):
    sonar = FakeSonar("OK")
    try:
        sonar_project(project, sonar)
        result = project.run(extra_env={"SONAR_TOKEN": "tok"})
        assert result.returncode == 0, result.stdout + result.stderr
        check = step(project.report(), "sonarqube")
        assert check["status"] == "pass" and check["dashboard_url"].endswith("dashboard?id=shop")
        assert all(auth == "Basic dG9rOg==" for _, auth in sonar.requests)
        args = (project.root / ".scannerwork/args").read_text()
        assert f"-Dsonar.host.url={sonar.url}" in args and "-Dsonar.projectKey=shop" in args and "tok" not in args
    finally:
        sonar.close()


def test_a_failed_sonarqube_gate_blocks_unless_set_to_warn(project):
    sonar = FakeSonar("ERROR", [{"status": "ERROR", "metricKey": "new_coverage", "actualValue": "41.0",
                                 "comparator": "LT", "errorThreshold": "80"}])
    try:
        sonar_project(project, sonar)
        assert project.run(extra_env={"SONAR_TOKEN": "tok"}).returncode == 2
        assert "new_coverage 41.0 (needs at least 80)" in step(project.report(), "sonarqube")["summary"]
        sonar_project(project, sonar, blocking="false")
        assert project.run(extra_env={"SONAR_TOKEN": "tok"}).returncode == 0
        assert step(project.report(), "sonarqube")["status"] == "warn"
    finally:
        sonar.close()


def test_sonarqube_without_a_token_fails(project):
    sonar = FakeSonar("OK")
    try:
        sonar_project(project, sonar)
        assert project.run(extra_env={"SONAR_TOKEN": ""}).returncode == 2
        assert "SONAR_TOKEN is not set" in step(project.report(), "sonarqube")["summary"]
    finally:
        sonar.close()


def test_parallel_jobs_merge_into_one_result(project, tmp_path):
    project.gates(lint="true", test="false")
    project.commit()
    jobs = []
    for check in ("lint", "test"):
        assert project.run("--only", check).returncode in (0, 2)
        job = tmp_path / f"job-{check}"
        subprocess.check_call(["cp", "-R", str(project.root / ".speed/ci"), str(job)])
        jobs.append(str(job))
    lint_only = json.loads((tmp_path / "job-lint/report.json").read_text())
    assert step(lint_only, "test")["selected"] is False
    result = project.run("merge", *jobs)
    assert result.returncode == 2
    merged = project.report()
    assert step(merged, "lint")["status"] == "pass" and step(merged, "test")["status"] == "fail"
    assert step(merged, "eval").get("summary") == "No job reported this check"
    result = project.run("merge", jobs[0], str(tmp_path / "job-missing"))
    assert result.returncode == 2 and "merge-jobs" in {item["name"] for item in project.report()["steps"]}


def test_every_run_writes_sarif_junit_and_a_github_summary(project, tmp_path):
    import xml.etree.ElementTree as ET
    (project.root / "settings.py").write_text(f'KEY = "{AWS_KEY}"\n')
    project.commit()
    summary_file = tmp_path / "summary.md"
    project.run(extra_env={"GITHUB_STEP_SUMMARY": str(summary_file)})
    sarif_doc = json.loads((project.root / ".speed/ci/speed-ci.sarif").read_text())
    assert sarif_doc["version"] == "2.1.0"
    secrets_run = next(run for run in sarif_doc["runs"] if run["tool"]["driver"]["name"] == "speed-ci/secrets")
    location = secrets_run["results"][0]["locations"][0]["physicalLocation"]
    assert location["artifactLocation"]["uri"] == "settings.py" and location["region"]["startLine"] == 1
    assert AWS_KEY not in json.dumps(sarif_doc)
    suite = ET.parse(project.root / ".speed/ci/junit.xml").getroot()
    assert suite.get("failures") == "1"
    assert {case.get("name") for case in suite} >= {"eval", "test", "secrets"}
    text = summary_file.read_text()
    assert "## speed ci: Failed" in text and "| secrets | ❌ fail |" in text


def load_workflow(project):
    workflow = yaml.safe_load((project.root / ".github/workflows/speed-ci.yml").read_text())
    return workflow, (workflow[True] if True in workflow else workflow["on"])


def test_init_adds_services_secrets_sarif_upload_and_codecov(project):
    sonar = '[ci.sonarqube]\nhost_url = "https://sonarcloud.io"\nproject_key = "acme_shop"\norganization = "acme"\n'
    project.toml('[ci]\nservices = ["postgres", "redis"]\n[ci.codecov]\nfiles = "coverage.xml"\n'
                 '[ci.tools.snyk]\n' + sonar)
    project.commit()
    result = project.run("init", "--speed-repo", "acme/speed", "--speed-ref", "v2")
    assert result.returncode == 0, result.stderr
    assert "SONAR_TOKEN" in result.stderr + result.stdout and "SNYK_TOKEN" in result.stderr + result.stdout
    workflow, _ = load_workflow(project)
    job = workflow["jobs"]["speed-ci"]
    assert set(job["services"]) == {"postgres", "redis"}
    assert job["services"]["postgres"]["image"] == "postgres:16"
    assert job["env"]["DATABASE_URL"].startswith("postgresql://") and "SONAR_TOKEN" not in job["env"]
    run_step = next(item for item in job["steps"] if item.get("name") == "Run speed ci")
    assert run_step["env"]["SONAR_TOKEN"] == "${{ secrets.SONAR_TOKEN }}"
    assert run_step["env"]["SNYK_TOKEN"] == "${{ secrets.SNYK_TOKEN }}"
    assert "SPEED_CI_SECRETS_UNAVAILABLE" in run_step["env"]
    checkout = job["steps"][0]
    assert checkout["with"]["fetch-depth"] == 0
    assert any(item.get("name") == "Install snyk" for item in job["steps"])
    assert any(item.get("name") == "Install sonarqube" for item in job["steps"])
    uses = [item.get("uses", "") for item in job["steps"]]
    assert "github/codeql-action/upload-sarif@v3" in uses and "codecov/codecov-action@v4" in uses
    assert workflow["permissions"] == {"contents": "read", "actions": "read", "security-events": "write"}


def test_init_with_parallel_runs_each_check_as_its_own_job(project):
    project.gates(test="true", api="true")
    project.toml("[ci]\nparallel = true\n")
    project.commit()
    assert project.run("init", "--speed-repo", "acme/speed", "--speed-ref", "v2").returncode == 0
    workflow, triggers = load_workflow(project)
    assert "pull_request" in triggers
    check = workflow["jobs"]["check"]
    assert check["strategy"]["matrix"]["check"] == ["eval", "lint", "typecheck", "test", "e2e", "api", "secrets", "sast", "sca"]
    assert check["strategy"]["fail-fast"] is False
    run_step = next(item for item in check["steps"] if str(item.get("name", "")).startswith("Run "))
    assert '--only "${{ matrix.check }}"' in run_step["run"]
    final = workflow["jobs"]["speed-ci"]
    assert final["needs"] == ["check"] and final["if"] == "${{ !cancelled() }}"
    combine = next(item for item in final["steps"] if item.get("name") == "Combine the results")
    assert "ci_tools.py merge merged reports/speed-ci-check-eval" in combine["run"] and "reports/speed-ci-check-api" in combine["run"]
    upload = next(item for item in check["steps"] if item.get("name") == "Upload this check's report")
    assert upload["with"]["name"] == "speed-ci-check-${{ matrix.check }}"


@pytest.mark.parametrize("parallel", [False, True])
def test_generated_workflows_pass_actionlint(project, parallel):
    import shutil
    linter = shutil.which("actionlint") or str(Path(sys.executable).parent / "actionlint")
    if not Path(linter).exists():
        pytest.skip("actionlint is not installed")
    project.gates(test="true", api="true")
    project.toml("[ci]\nservices = [\"postgres\"]\n" + ("parallel = true\n" if parallel else "")
                 + '[ci.codecov]\n[ci.tools.trivy]\n[ci.sonarqube]\nhost_url = "https://sonarcloud.io"\nproject_key = "a_b"\n')
    project.commit()
    assert project.run("init", "--speed-repo", "acme/speed", "--speed-ref", "v2").returncode == 0
    result = subprocess.run([linter, str(project.root / ".github/workflows/speed-ci.yml")], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr



# ── Phase 2 review fixes ──

def test_merge_keeps_the_most_severe_result_when_two_jobs_report_a_check(project, tmp_path):
    project.gates(test="false")
    project.commit()
    project.run("--only", "test")
    failing = tmp_path / "failing"
    subprocess.check_call(["cp", "-R", str(project.root / ".speed/ci"), str(failing)])
    project.gates(test="true")
    project.run("--only", "test")
    passing = tmp_path / "passing"
    subprocess.check_call(["cp", "-R", str(project.root / ".speed/ci"), str(passing)])
    for order in ((failing, passing), (passing, failing)):
        assert project.run("merge", *map(str, order)).returncode == 2
        assert step(project.report(), "test")["status"] == "fail"


def test_merge_reports_an_unreadable_job_and_different_commits(project, tmp_path):
    project.run()
    good = tmp_path / "good"
    subprocess.check_call(["cp", "-R", str(project.root / ".speed/ci"), str(good)])
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "report.json").write_text("")
    other = tmp_path / "other"
    subprocess.check_call(["cp", "-R", str(good), str(other)])
    report = json.loads((other / "report.json").read_text())
    (other / "report.json").write_text(json.dumps({**report, "commit": "0" * 40}))
    result = project.run("merge", str(good), str(broken), str(other))
    assert result.returncode == 2
    names = {item["name"] for item in project.report()["steps"]}
    assert {"merge-jobs", "merge-commit"} <= names
    assert project.report()["branch"] == "main"


def test_a_capitalised_custom_gate_runs(project):
    project.gates(test="true", API="exit 1")
    project.commit()
    assert project.run().returncode == 2
    assert step(project.report(), "API")["status"] == "fail"


def test_gate_names_that_cannot_run_are_refused_not_dropped(project):
    for gates, toml, expected in (({"test": "true", "secrets": "exit 1"}, "", "speed ci uses itself"),
                                  ({"test": "true", "trivy": "exit 1"}, "[ci.tools.trivy]\n", "also a [ci.tools.trivy]"),
                                  ({"test": "true", "api": "true", "Api": "true"}, "", "only by case"),
                                  ({"TEST": "true"}, "", "must be written 'test'")):
        project.gates(**gates)
        project.toml(toml)
        project.commit()
        result = project.run()
        assert result.returncode == 3 and expected in result.stderr, result.stderr


def test_invalid_tool_and_codecov_settings_are_refused(project):
    for toml, expected in (('[ci.tools.snyk]\ntoken_env = "a[$(touch PWNED)]"\n', "token_env"),
                           ("[ci]\nparallel = true\n[ci.codecov]\ncheck = \"test'\"\n", "[ci.codecov] check"),
                           ('[ci.sonarqube]\nhost_url = "http://sonar.example.com"\nproject_key = "a"\n', "https"),
                           ('[ci.tools.report]\nformat = "sarif"\ncmd = "true"\n', "cannot be one of")):
        project.toml(toml)
        project.commit()
        result = project.run()
        assert result.returncode == 3 and expected in result.stderr, result.stderr
    assert not (project.root / "PWNED").exists()
    project.toml("[ci]\nparallel = true\n[ci.codecov]\ncheck = \"coverage\"\n")
    project.commit()
    result = project.run("init", "--speed-repo", "acme/speed", "--speed-ref", "v2")
    assert result.returncode == 3 and "not one of this project's checks" in result.stderr


def test_codeql_rules_in_extensions_keep_their_severity(project):
    codeql = {"version": "2.1.0", "runs": [{"tool": {"driver": {"name": "CodeQL", "rules": []}, "extensions": [
        {"name": "codeql/python-queries", "rules": [{"id": "py/sql-injection", "properties": {"security-severity": "9.8"}}]}]},
        "results": [{"ruleId": "py/sql-injection", "rule": {"id": "py/sql-injection", "index": 0, "toolComponent": {"index": 0}},
                     "message": {"text": "SQL from user input"},
                     "locations": [{"physicalLocation": {"artifactLocation": {"uri": "app.py"}, "region": {"startLine": 4}}}]}]}]}
    project.toml(tool(project, "codeql", "sarif", codeql))
    project.commit()
    assert project.run().returncode == 2
    assert step(project.report(), "codeql")["blocking_findings"][0]["severity"] == "critical"


def test_snyk_applications_are_read_and_paths_are_not_counted_twice(project):
    vuln = {"id": "SNYK-JS-1", "title": "RCE", "severity": "high", "packageName": "minimist", "version": "1.0.0"}
    snyk = {"ok": False, "vulnerabilities": [vuln, vuln], "applications": [
        {"displayTargetFile": "app/package.json", "vulnerabilities": [dict(vuln, id="SNYK-JS-2", severity="critical")]}]}
    project.toml(tool(project, "snyk", "snyk", snyk, 1))
    project.commit()
    assert project.run(extra_env={"SNYK_TOKEN": "t"}).returncode == 2
    check = step(project.report(), "snyk")
    assert check["total_findings"] == 2
    assert {item["severity"] for item in check["blocking_findings"]} == {"high", "critical"}


def test_a_timed_out_secret_scanner_leaves_no_raw_output(project):
    leaks = [{"RuleID": "aws", "File": "x.py", "StartLine": 1, "Secret": AWS_KEY}]
    (project.root / "leaks.json").write_text(json.dumps(leaks))
    project.toml('[ci]\ncommand_timeout = 1\n[ci.tools.gitleaks]\ncmd = "cat leaks.json; sleep 30"\n')
    project.commit()
    assert project.run().returncode == 2
    assert step(project.report(), "gitleaks")["summary"].startswith("gitleaks timed out")
    for path in (project.root / ".speed").rglob("*"):
        assert not path.is_file() or AWS_KEY not in path.read_text(errors="replace"), path


def test_checks_needing_secrets_are_skipped_on_fork_pull_requests(project):
    project.toml('[ci.tools.snyk]\n[ci.sonarqube]\nhost_url = "https://sonarcloud.io"\nproject_key = "a_b"\n')
    project.commit()
    result = project.run(extra_env={"SNYK_TOKEN": "", "SONAR_TOKEN": "", "SPEED_CI_SECRETS_UNAVAILABLE": "true"})
    assert result.returncode == 0, result.stdout + result.stderr
    for name in ("snyk", "sonarqube"):
        assert step(project.report(), name)["status"] == "skipped"
        assert "forks or Dependabot" in step(project.report(), name)["summary"]


def test_an_empty_only_value_is_refused(project):
    result = project.run("--only", ",")
    assert result.returncode == 3 and "at least one check name" in result.stderr


class PollingSonar(FakeSonar):
    """Answers ce/task with the given sequence (status strings or HTTP codes), checks the ids sent."""

    def __init__(self, sequence, gate="OK", redirect=None):
        import http.server
        import threading
        import urllib.parse as up
        sonar = self
        self.requests = []
        sequence = list(sequence)

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                url = up.urlparse(self.path)
                query = dict(up.parse_qsl(url.query))
                sonar.requests.append((url.path, query))
                if redirect:
                    self.send_response(302)
                    self.send_header("Location", redirect)
                    self.end_headers()
                    return
                if url.path == "/api/ce/task" and query.get("id") == "T1":
                    item = sequence.pop(0) if len(sequence) > 1 else sequence[0]
                    if isinstance(item, int):
                        self.send_response(item)
                        self.end_headers()
                        return
                    body = {"task": {"status": item, "analysisId": "A1"}}
                elif url.path == "/api/qualitygates/project_status" and query.get("analysisId") == "A1":
                    body = {"projectStatus": {"status": gate, "conditions": []}}
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                data = json.dumps(body).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


def test_sonarqube_polls_until_done_and_rides_out_a_busy_server(project):
    sonar = PollingSonar(["PENDING", 503, "IN_PROGRESS", "SUCCESS"], gate="WARN")
    try:
        sonar_project(project, sonar)
        result = project.run(extra_env={"SONAR_TOKEN": "tok"})
        assert result.returncode == 0, result.stdout + result.stderr
        assert step(project.report(), "sonarqube")["status"] == "warn"
        assert sum(path == "/api/ce/task" for path, _ in sonar.requests) >= 4
        assert "-Dsonar.qualitygate.wait=false" in (project.root / ".scannerwork/args").read_text()
    finally:
        sonar.close()


def test_sonarqube_failed_analysis_and_redirects_fail(project):
    for sonar, expected in ((PollingSonar(["FAILED"]), "analysis failed"),
                            (PollingSonar(["SUCCESS"], redirect="http://127.0.0.1:9/steal"), "redirected")):
        try:
            sonar_project(project, sonar)
            assert project.run(extra_env={"SONAR_TOKEN": "tok"}).returncode == 2
            assert expected in step(project.report(), "sonarqube")["summary"]
        finally:
            sonar.close()


def test_pr_status_and_body_count_warnings(project, feature_branches, tmp_path):
    (project.root / "semgrep.json").write_text(json.dumps(SEMGREP).replace("{severity}", "ERROR"))
    project.toml('[ci]\nsecurity_mode = "report"\n[security]\nsast_cmd = "cat semgrep.json"\n')
    project.commit()
    project.git("push", "-q", "origin", "main")
    assert project.run("--pr").returncode == 0
    status = next(call for call in gh_calls(tmp_path) if call.startswith("api"))
    assert "1 warning(s)" in status and "state=success" in status
    body = (project.root / ".speed/ci/pr-body.md").read_text()
    assert "1 warning(s)" in body and "review them before merging" in body


def test_numeric_speed_refs_stay_strings_in_the_workflow(project):
    assert project.run("init", "--speed-repo", "acme/speed", "--speed-ref", "1.10").returncode == 0
    workflow, _ = load_workflow(project)
    speed = next(item for item in workflow["jobs"]["speed-ci"]["steps"] if item.get("name") == "Check out SPEED")
    assert speed["with"]["ref"] == "1.10"



# ── Phase 2 final-round fixes ──

def test_the_generated_database_workflow_passes_the_secrets_scan(project):
    project.toml('[ci]\nservices = ["postgres", "mysql", "redis"]\n')
    project.commit()
    assert project.run("init", "--speed-repo", "acme/speed", "--speed-ref", "v2").returncode == 0
    project.commit("add workflow")
    assert project.run().returncode == 0
    assert step(project.report(), "secrets")["status"] == "pass"
    (project.root / "deploy.yml").write_text("url: postgresql://admin:hunter22@db.example.com/prod\n")
    project.commit("a real one")
    assert project.run().returncode == 2


def test_scanner_raw_output_and_logs_never_keep_secret_text(project):
    semgrep = {"results": [{"check_id": "secrets.aws", "path": "app.py", "start": {"line": 1},
                            "extra": {"severity": "ERROR", "message": "AWS key", "lines": f'KEY = "{AWS_KEY}"'}}]}
    (project.root / "semgrep.json").write_text(json.dumps(semgrep))
    (project.root / "tool.sh").write_text(f"echo 'found {AWS_KEY}' >&2\necho '{{\"version\":\"2.1.0\",\"runs\":[]}}'\n")
    project.toml('[security]\nsast_cmd = "cat semgrep.json"\n[ci.tools.leaky]\nformat = "sarif"\ncmd = "sh tool.sh"\n')
    project.commit()
    project.run()
    for path in (project.root / ".speed").rglob("*"):
        assert not path.is_file() or AWS_KEY not in path.read_text(errors="replace"), path
    assert "[redacted]" in (project.root / ".speed/ci/logs/leaky.log").read_text()


def test_an_interrupted_tool_leaves_no_raw_output(project, tmp_path):
    import signal
    import time
    tmpdir = tmp_path / "tmpd"
    tmpdir.mkdir()
    (project.root / "leaks.json").write_text(json.dumps([{"RuleID": "aws", "File": "x", "StartLine": 1, "Secret": AWS_KEY}]))
    project.toml('[ci.tools.gitleaks]\ncmd = "cat leaks.json; sleep 30"\n')
    project.commit()
    env = {key: value for key, value in os.environ.items() if not key.endswith("_API_KEY")}
    env.update(SPEED_PROJECT_ROOT=str(project.root), SPEED_PYTHON=sys.executable, TMPDIR=str(tmpdir),
               PATH=f"{project.tools}{os.pathsep}{env['PATH']}", CLAUDE_BIN=str(project.tools / "claude"))
    proc = subprocess.Popen(["bash", str(project.cli), "ci", "--only", "gitleaks"], env=env, cwd=project.root,
                            start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)
    os.killpg(proc.pid, signal.SIGTERM)
    proc.wait(timeout=30)
    leftovers = [path for path in tmpdir.rglob("speed-ci-*") if AWS_KEY in path.read_text(errors="replace")]
    assert leftovers == []


def test_gate_lines_with_spaces_are_refused_unless_ignored(project):
    (project.root / "AGENTS.md").write_text("# P\n\n## Quality Gates\n\n- test: true\n- unit tests: exit 1\n")
    project.commit()
    result = project.run()
    assert result.returncode == 3 and "'unit tests' is not a valid check name" in result.stderr
    project.toml('[ci]\nignore_gates = ["unit tests"]\n')
    project.commit()
    assert project.run().returncode == 0


def test_only_and_skip_match_check_names_without_case(project):
    project.gates(test="true", Smoke_Check="exit 1")
    project.commit()
    assert project.run("--only", "smoke_check").returncode == 2
    assert step(project.report(), "Smoke_Check")["status"] == "fail"
    assert project.run("--skip", "SMOKE_CHECK").returncode == 0


def test_token_names_must_be_valid_github_secrets(project):
    for token in ("snyk_token", "GITHUB_TOKEN", "PATH", "SPEED_CI_SECRETS_UNAVAILABLE"):
        project.toml(f'[ci.tools.snyk]\ntoken_env = "{token}"\n')
        project.commit()
        result = project.run()
        assert result.returncode == 3 and "token_env" in result.stderr, token


def test_default_tool_commands_run_the_real_tool_names(project, tmp_path):
    fake = project.tools / "trivy"
    fake.write_text(f'#!/bin/sh\necho "$@" > {shlex.quote(str(tmp_path / "trivy-args"))}\n'
                    'echo \'{"SchemaVersion": 2, "Results": []}\'\n')
    fake.chmod(0o755)
    project.toml("[ci.tools.trivy]\n")
    project.commit()
    assert project.run().returncode == 0
    assert (tmp_path / "trivy-args").read_text().split() == ["fs", "--format", "json", "--quiet", "--scanners",
                                                            "vuln,misconfig,secret", "."]
    project.toml("[ci.tools.codeql]\n")
    project.commit()
    result = project.run()
    assert result.returncode == 3 and "needs format" in result.stderr


def test_sonarqube_gate_read_retries_and_timeouts_and_empty_gates_fail(project):
    sonar = PollingSonar(["PENDING"])
    try:
        sonar_project(project, sonar)
        project.toml((project.root / "speed.toml").read_text().replace('wait_timeout = "10"', 'wait_timeout = "1"'))
        project.commit()
        assert project.run(extra_env={"SONAR_TOKEN": "tok"}).returncode == 2
        assert "did not finish within 1s" in step(project.report(), "sonarqube")["summary"]
    finally:
        sonar.close()
    sonar = PollingSonar(["SUCCESS"], gate="NONE")
    try:
        sonar_project(project, sonar)
        assert project.run(extra_env={"SONAR_TOKEN": "tok"}).returncode == 2
        assert "no quality gate result" in step(project.report(), "sonarqube")["summary"]
    finally:
        sonar.close()


def test_pr_body_links_the_sonarqube_dashboard(project, feature_branches):
    sonar = FakeSonar("OK")
    try:
        sonar_project(project, sonar)
        project.git("push", "-q", "origin", "main")
        assert project.run("--pr", extra_env={"SONAR_TOKEN": "tok"}).returncode == 0
        assert "[dashboard](" in (project.root / ".speed/ci/pr-body.md").read_text()
    finally:
        sonar.close()


def test_parallel_databases_only_start_for_checks_that_test(project):
    project.gates(test="true", integration="true")
    project.toml('[ci]\nparallel = true\nservices = ["postgres"]\n[ci.tools.trivy]\n')
    project.commit()
    assert project.run("init", "--speed-repo", "acme/speed", "--speed-ref", "v2").returncode == 0
    workflow, _ = load_workflow(project)
    plain, with_db = workflow["jobs"]["check"], workflow["jobs"]["check-db"]
    assert "services" not in plain and set(with_db["services"]) == {"postgres"}
    assert with_db["strategy"]["matrix"]["check"] == ["test", "e2e", "integration"]
    assert "trivy" in plain["strategy"]["matrix"]["check"] and "lint" in plain["strategy"]["matrix"]["check"]
    assert workflow["jobs"]["speed-ci"]["needs"] == ["check", "check-db"]
    install = next(item for item in plain["steps"] if item.get("name") == "Install trivy")
    assert install["if"] == "matrix.check == 'trivy'"


def test_sarif_names_a_real_file_for_dependency_findings(project):
    audit = {"vulnerabilities": {"lodash": {"severity": "high", "via": [{"title": "Prototype pollution"}]}}}
    (project.root / "audit.json").write_text(json.dumps(audit))
    (project.root / "package-lock.json").write_text("{}")
    project.toml('[security]\nsca_cmd = "cat audit.json; exit 1"\n')
    project.commit()
    project.run()
    runs = json.loads((project.root / ".speed/ci/speed-ci.sarif").read_text())["runs"]
    result = next(run for run in runs if run["tool"]["driver"]["name"] == "speed-ci/sca")["results"][0]
    assert result["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] == "package-lock.json"
    assert result["message"]["text"].count("lodash") == 1


# ── Phase 2 confirmation-round fixes ──

def test_the_test_credential_mark_only_counts_in_the_generated_workflow(project):
    (project.root / "config.py").write_text(f'KEY = "{AWS_KEY}"  # speed-ci: test service credential\n')
    project.commit()
    assert project.run("--only", "secrets").returncode == 2
    assert step(project.report(), "secrets")["findings"][0]["file"] == "config.py"


def test_other_gate_bullet_forms_are_refused_not_dropped(project):
    for line, expected in (("* smoke: exit 1", "uses a '*' bullet"), ("- `smoke`: exit 1", "without backticks"),
                           ("api.v2: exit 1", "not a valid check name")):
        (project.root / "AGENTS.md").write_text(f"# P\n\n## Quality Gates\n\n- test: true\n{line}\n")
        project.commit()
        result = project.run()
        assert result.returncode == 3 and expected in result.stderr, (line, result.stderr)


def test_log_redaction_understands_posix_classes(project):
    project.toml('[security]\nsecrets_patterns = ["CorpToken|CORPTOKEN-[[:upper:][:digit:]]{8}"]\n'
                 'sast_cmd = "echo debug CORPTOKEN-ABCD1234 >&2; echo \'{\\"results\\": []}\'"\n')
    project.commit()
    project.run()
    assert "CORPTOKEN-ABCD1234" not in (project.root / ".speed/ci/logs/sast.log").read_text()


def test_every_sarif_result_has_a_location(project):
    audit = {"vulnerabilities": {"lodash": {"severity": "high", "via": [{"title": "Prototype pollution"}]}}}
    (project.root / "audit.json").write_text(json.dumps(audit))
    project.toml('[security]\nsca_cmd = "cat audit.json; exit 1"\n')
    project.commit()
    project.run()
    for run in json.loads((project.root / ".speed/ci/speed-ci.sarif").read_text())["runs"]:
        for result in run["results"]:
            assert result["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]


def test_sonarqube_failures_say_what_the_metric_needs(project):
    sonar = FakeSonar("ERROR", [{"status": "ERROR", "metricKey": "new_coverage", "actualValue": "41.0",
                                 "comparator": "LT", "errorThreshold": "80"}])
    try:
        sonar_project(project, sonar)
        project.run(extra_env={"SONAR_TOKEN": "tok"})
        assert "new_coverage 41.0 (needs at least 80)" in step(project.report(), "sonarqube")["summary"]
    finally:
        sonar.close()


def test_default_gitleaks_and_snyk_commands(project, tmp_path):
    for name, payload in (("gitleaks", "[]"), ("snyk", '{"ok": true, "vulnerabilities": []}')):
        fake = project.tools / name
        fake.write_text(f'#!/bin/sh\necho "$@" > {shlex.quote(str(tmp_path / (name + "-args")))}\necho \'{payload}\'\n')
        fake.chmod(0o755)
    project.toml("[ci.tools.gitleaks]\n[ci.tools.snyk]\n")
    project.commit()
    assert project.run(extra_env={"SNYK_TOKEN": "t"}).returncode == 0
    assert (tmp_path / "gitleaks-args").read_text().split() == ["detect", "--no-banner", "--redact", "--report-format",
                                                               "json", "--report-path", "-", "--log-opts=HEAD"]
    assert (tmp_path / "snyk-args").read_text().split() == ["test", "--json"]


def test_sonarqube_scanner_failure_and_custom_report_task(project):
    sonar = FakeSonar("OK")
    try:
        sonar_project(project, sonar)
        (project.root / "fake-scanner.sh").write_text("#!/bin/sh\nexit 1\n")
        project.commit()
        assert project.run(extra_env={"SONAR_TOKEN": "tok"}).returncode == 2
        assert "scanner exited 1" in step(project.report(), "sonarqube")["summary"]
        (project.root / "fake-scanner.sh").write_text(
            "#!/bin/sh\nmkdir -p target/sonar\nprintf 'ceTaskId=T1\\n' > target/sonar/report-task.txt\n")
        project.toml((project.root / "speed.toml").read_text() + 'report_task = "target/sonar/report-task.txt"\n')
        (project.root / ".gitignore").write_text(".speed/\n__pycache__/\n.pytest_cache/\n.scannerwork/\ntarget/\n")
        project.commit()
        assert project.run(extra_env={"SONAR_TOKEN": "tok"}).returncode == 0
    finally:
        sonar.close()


def test_merge_keeps_every_jobs_sarif_runs(project, tmp_path):
    (project.root / "settings.py").write_text(f'KEY = "{AWS_KEY}"\n')
    (project.root / "trivy.json").write_text(json.dumps({"SchemaVersion": 2, "Results": [{"Target": "x", "Vulnerabilities": [
        {"VulnerabilityID": "CVE-1", "PkgName": "p", "Severity": "LOW"}]}]}))
    project.toml('[ci.tools.trivy]\ncmd = "cat trivy.json"\n')
    project.commit()
    jobs = []
    for check in ("secrets", "trivy"):
        project.run("--only", check)
        job = tmp_path / f"job-{check}"
        subprocess.check_call(["cp", "-R", str(project.root / ".speed/ci"), str(job)])
        jobs.append(str(job))
    project.run("merge", *jobs)
    names = {run["tool"]["driver"]["name"] for run in json.loads((project.root / ".speed/ci/speed-ci.sarif").read_text())["runs"]}
    assert {"speed-ci/secrets", "speed-ci/trivy"} <= names


def test_an_example_under_a_deep_heading_is_never_run(project):
    (project.root / "AGENTS.md").write_text("# Project\n\n## Quality Gates\n\n- test: true\n\n#### Example\n\n"
                                           "- lint: false\n")
    project.commit()
    assert project.run().returncode == 0
    assert step(project.report(), "lint")["status"] == "skipped"


def test_only_a_whole_command_code_span_loses_its_backticks(project):
    project.gates(lint="`true`", test="test \"`echo ok`\" = ok")
    project.commit()
    result = project.run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert step(project.report(), "lint")["status"] == "pass"


def test_a_command_that_exits_124_by_itself_is_a_failure_not_a_timeout(project):
    project.gates(test="exit 124")
    project.commit()
    assert project.run().returncode == 2
    test = step(project.report(), "test")
    assert test["status"] == "fail" and "timed out" not in json.dumps(test).lower()


def test_a_corrupt_task_file_fails_eval(project):
    project.commit()
    feature = write_feature(project, "adding")
    (feature / "tasks/1.json").write_text("{not json")
    assert project.run().returncode == 2
    assert "not valid JSON" in step(project.report(), "eval")["features"][0]["reason"]


def test_a_lock_left_by_a_dead_run_is_taken_over(project):
    lock = project.root / ".speed/ci/.lock"
    lock.mkdir(parents=True)
    dead = subprocess.Popen(["true"])
    dead.wait()
    (lock / "pid").write_text(str(dead.pid))
    assert project.run().returncode == 0
    assert not lock.exists()


def test_gates_never_see_scanner_tokens_and_token_values_are_redacted(project):
    project.gates(test="test -z \"$SNYK_TOKEN\"")
    (project.root / "tool.sh").write_text("echo \"token is $SNYK_TOKEN\" >&2\necho '{\"ok\":true,\"vulnerabilities\":[]}'\n")
    project.toml('[ci.tools.snyk]\nformat = "snyk"\ncmd = "sh tool.sh"\n')
    project.commit()
    secret = "snyk-" + "a1b2c3d4e5f6"
    result = project.run(extra_env={"SNYK_TOKEN": secret})
    assert result.returncode == 0, result.stdout + result.stderr
    assert secret not in result.stdout + result.stderr
    for path in (project.root / ".speed").rglob("*"):
        assert not path.is_file() or secret not in path.read_text(errors="replace"), path


def test_unknown_ci_settings_are_refused(project):
    project.toml("[ci]\nsecurity_mod = \"report\"\n")
    project.commit()
    result = project.run()
    assert result.returncode == 3 and "security_mod" in result.stderr


def test_ignore_gates_cannot_leave_out_a_built_in_check(project):
    project.toml("[ci]\nignore_gates = [\"test\"]\n")
    project.commit()
    result = project.run()
    assert result.returncode == 3 and "--skip test" in result.stderr


def test_sonarqube_host_url_with_a_query_is_refused(project):
    project.toml("[ci.sonarqube]\nhost_url = \"https://sonar.example.com/?token=x\"\nproject_key = \"shop\"\n")
    project.commit()
    result = project.run(extra_env={"SONAR_TOKEN": "t"})
    assert result.returncode == 3 and "no query" in result.stderr


def test_merge_refuses_its_own_output_directory_as_a_job(project):
    project.run()
    before = (project.root / ".speed/ci/report.json").read_text()
    result = project.run("merge", str(project.root / ".speed/ci"))
    assert result.returncode == 3 and "cannot also be where" in result.stderr
    assert (project.root / ".speed/ci/report.json").read_text() == before


def test_json_startup_failures_still_print_one_object(project, cli, tmp_path):
    source = cli.read_text().replace("# preflight omitted in isolated CLI tests",
                                     "_speed_ci_startup_failed \"dependency check failed\"; exit 3")
    cli.write_text(source)
    result = project.run(json_output=True)
    assert result.returncode == 3
    assert json.loads(result.stdout) == {"passed": False, "error": "dependency check failed",
                                         "exit_code": 3, "steps": []}


def test_init_json_lists_the_secrets_to_add(project):
    project.toml('[ci.tools.snyk]\nformat = "snyk"\n')
    project.commit()
    result = project.run("init", "--speed-repo", "acme/speed", json_output=True)
    assert result.returncode == 0, result.stderr
    assert "SNYK_TOKEN" in json.dumps(json.loads(result.stdout))


def test_pr_will_not_overwrite_a_reviewers_merge_commit(project, feature_branches):
    assert project.run("--pr").returncode == 0
    project.git("fetch", "-q", "origin", "speed-ci/shop")
    project.git("checkout", "-q", "-b", "review", "FETCH_HEAD")
    project.git("checkout", "-q", "-b", "side", "main")
    (project.root / "side.py").write_text("SIDE = 1\n")
    project.commit("side work")
    project.git("checkout", "-q", "review")
    project.git("-c", "user.name=Reviewer", "-c", "user.email=r@example.invalid",
                "merge", "-q", "--no-ff", "--no-edit", "side")
    project.git("push", "-q", "origin", "review:refs/heads/speed-ci/shop")
    merged = project.git("rev-parse", "HEAD")
    project.git("checkout", "-q", "main")
    result = project.run("--pr")
    assert result.returncode == 3 and "pass --force" in result.stderr
    remote = subprocess.check_output(["git", "-C", str(feature_branches), "rev-parse", "speed-ci/shop"], text=True).strip()
    assert remote == merged


def test_pr_json_output_is_one_object_with_the_pr_branch(project, feature_branches):
    result = project.run("--pr", json_output=True)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["passed"] is True and "speed-ci/shop" in json.dumps(report)


def test_a_project_in_a_subdirectory_ignores_changes_outside_it(tmp_path):
    sys.path.insert(0, str(REPO / "lib"))
    from eval_runtime import build_snapshot
    repo = tmp_path / "repo"
    (repo / "demo").mkdir(parents=True)
    (repo / "demo/app.py").write_text("X = 1\n")
    (repo / "README.md").write_text("readme\n")
    git = ["git", "-C", str(repo)]
    subprocess.check_call([*git, "init", "-q", "-b", "main"])
    subprocess.check_call([*git, "add", "-A"])
    subprocess.check_call([*git, "-c", "user.name=T", "-c", "user.email=t@example.invalid", "commit", "-qm", "i"])
    (repo / "README.md").write_text("edited outside the project\n")
    assert build_snapshot(repo / "demo")["dirty"] is False
    assert build_snapshot(repo)["dirty"] is True
    (repo / "demo/app.py").write_text("X = 2\n")
    assert build_snapshot(repo / "demo")["dirty"] is True


def test_pr_steps_print_inside_the_result_block(project, feature_branches):
    result = project.run("--pr")
    assert result.returncode == 0, result.stdout + result.stderr
    lines = [line.split()[1] if line.startswith("  ") else line.split()[0]
             for line in result.stdout.splitlines() if line.strip()]
    assert lines[0] == "SPEED" and lines[1] == "merge" and lines[-1] == "PASSED"
    assert lines[-4:-1] == ["push", "pr", "status"]
    assert "clean-tree" in lines and lines.count("SPEED") == 1
    assert "Opened https://github.com/acme/shop/pull/7" in result.stdout
    dry = project.run("--pr", "--dry-run")
    assert "Dry run" in dry.stdout and dry.stdout.strip().splitlines()[-1].startswith("PASSED")
