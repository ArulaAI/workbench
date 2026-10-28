---
title: CLI Reference
description: Command-line interface reference for the speed orchestrator.
---

The `speed` CLI is the entry point for the orchestration pipeline. It coordinates agents through separate stages from initialization to integration.

## Usage

```bash
speed <command> [options]
```

## Global Options

These flags apply to all commands.

| Flag | Description |
|---|---|
| `--feature NAME` | Target a specific feature directory. Auto-detected from context if omitted. |
| `--quiet` | Errors and final results only. |
| `--verbose` | Show extra detail including gate output and agent commands. |
| `--debug` | Show internal state, timing, and PID tracking. |
| `--json` | Output structured JSON to stdout (logs move to stderr). |

## Commands

### `init`
Initializes a project for SPEED development. Creates a `.speed/` runtime directory, scaffolds `CLAUDE.md`, `speed.toml`, and a product vision template if missing. Also creates `src/` and `tests/` directories, writes `.gitignore` entries, initializes `state.json`, and creates an initial git commit.

### `new <type> <name>`
Scaffolds a new spec file from a type-specific template. Supported types: `prd`, `rfc`, `design`, `defect`. Output goes to the matching `specs/` subdirectory (e.g., `prd` creates `specs/product/<name>.md`). Opens the file in `$EDITOR` after creation. Name must be lowercase alphanumeric with hyphens only.

### `validate <specs-dir>`
Cross-references all specification files in the target directory. The Validator agent identifies missing relationships, contradictory requirements, and orphaned features before any tasks are generated.

### `audit <spec-file>`
Runs a structural audit of a spec file against the official template for its type. Spec type is detected from the path: `product/` → PRD, `tech/` → RFC, `design/` → design, `defects/` → defect. The audit checks required sections, sizing (warns if the feature is too large for a single plan cycle), and cross-references linked specs and the product vision. Defect specs additionally cross-reference the related feature spec. Writes a timestamped audit JSON to the feature's logs directory.

### `plan <spec-file>`
Decomposes a technical specification into a directed acyclic graph (DAG) of tasks.
*   **Layer 1 Context**: Automatically builds a codebase index before running.
*   **Guardian Gate**: Runs a pre-plan vision check to ensure the feature aligns with the product roadmap.
*   **Caching**: Plans are cached by spec content hash. Unchanged specs reuse the cached plan.
*   **Sibling Specs**: Auto-derives related specs from the path convention (e.g., `specs/tech/foo.md` resolves `specs/product/foo.md` and `specs/design/foo.md`).
*   **Multi-Phase**: Large features (exceeding the sizing threshold) are decomposed in two phases: foundation, then feature implementation.
*   **Quality Gate**: Validates decomposition quality (cluster size, file ownership, bridge symbols). Auto-patches missing bridge-symbol dependencies when possible.
*   **Options**:
    *   `--specs-dir DIR`: Path to related specs for cross-referencing.
    *   `--force`: Bypasses the plan cache.
    *   `--skip-audit`: Skips the structural audit of the spec file.

### `verify`
Performs an adversarial audit. An independent verifier reads the product spec without seeing the Architect's reasoning and checks whether the proposed task plan actually delivers the requirements. Reads cross-cutting concerns and spec traceability data as additional input.

When fixable issues are found, a Fix Agent modifies task JSONs and the verifier re-runs (up to N iterations with convergence detection). Issues requiring human judgment skip the auto-fix loop and escalate directly.

### `run`
Executes pending tasks in parallel using isolated git worktrees.
*   **Concurrency**: Controlled by the `--max-parallel` flag.
*   **Stale Recovery**: On startup, resets "running" tasks from a previous crashed session to pending.
*   **Timeout Escalation**: Tasks that time out are retried with an upgraded model tier (sonnet to opus).
*   **Halt Threshold**: Stops the run when the failure rate exceeds 30% to prevent cascading failures.
*   **Pattern Detection**: The Supervisor analyzes failures across the log to identify systemic issues.
*   **Defect mode**: `speed run --defect <name>` runs the defect pipeline (triage → reproduce → fix) instead of the standard task pipeline. Trivial defects skip the reproduce stage.
*   **Options**:
    *   `--max-parallel N`: Maximum concurrent agents (default: 3).
    *   `--model MODEL`: Target LLM for developer agents (sonnet, opus, or haiku).

### `review`
Triggers code review for completed tasks. Uses the Reviewer agent to check diffs against original product requirements rather than just task descriptions. After the Reviewer approves, the Product Guardian runs a post-review vision-alignment gate. A Guardian rejection overrides the approval and sends the task back to `request_changes`. Nits from approved tasks are collected into `review-nits.json`.
*   **Option**: `--task-id ID`: Target a specific completed task.

### `coherence`
Standalone cross-task coherence check. The Coherence Checker examines how independently developed task branches interact when combined, looking for interface mismatches, duplicated logic, and contradictory assumptions. Runs delta comparison against previous reports when they exist, categorizing issues as fixed, remaining, or new.

### `integrate`
Merges validated branches into the main repository in dependency order. Coherence checking is a separate command (`speed coherence`) run before integration.
*   **Regression**: Runs automated tests after each merge (skip with `--skip-tests`).
*   **CSG Rebuild**: Rebuilds the codebase index against the merged result.
*   **Contract Check**: Verifies that implemented code matches the Architect's data model contract. Invokes the Supervisor on failure.
*   **Guardian Gate**: Performs a final vision check on the integrated result.
*   **Option**: `--defect <name>`: Integrates a defect fix (runs review first for moderate defects in "fixed" state).

### `learn`
Extracts structured observations from a completed feature's artifacts and feeds them into the learning pipeline. Requires a prior `speed plan` and `speed run`. Without flags, runs a 14-step extraction pipeline that produces typed observations from task outcomes, agent logs, and human correction signals. See the [Learning System](/docs/api/learn/) reference for the full pipeline and observation types. For multiplayer knowledge collaboration, see the [Multi-Player Reference](/docs/api/multiplayer-reference/).

| Flag | Description |
|---|---|
| *(no flags)* | Extract observations from the active feature's artifacts. |
| `--summary` | Aggregate stats across all observed features. |
| `--synthesize` | Distill raw observations into per-agent learnings with routing, weighting, and token budgets. |
| `--post-merge` | Detect human corrections by diffing task branches against merged HEAD. |
| `--conventions` | Run convention discovery from accumulated observations and the semantic graph. |
| `--seed-knowledge` | Scan the project and generate draft knowledge entries for human review. |
| `--dry-run` | Run extraction without writing any files. |
| `--merge` | *(Multi-player)* Merge pending knowledge proposals into shared conventions. |
| `--curate` | *(Multi-player)* Interactive conflict resolution for opposing proposals. |
| `--pending` | *(Multi-player)* List unmerged proposals with actor, feature, and timestamp. |
| `--prune` | *(Multi-player)* Archive events older than the configured threshold (default: 30 days). |

### `retry`
Restarts a failed or blocked task with human guidance.
*   **Required**: `--task-id ID` and `--context "instructions"`. The `--context` flag prevents blind retries without diagnostic input.
*   **Option**: `--escalate`: Upgrades the agent model through the ladder (haiku → sonnet → opus).
*   **Option**: `--defect <name>`: Retries a defect fix with stage-aware re-entry, resuming from the failed stage.

### `security`
Runs a security audit against the current feature. Orchestrates three scanning tools:
*   **SAST**: Semgrep static analysis for code-level vulnerabilities.
*   **SCA**: Dependency scanning for known CVEs in third-party packages.
*   **Secrets**: Pattern-based detection of leaked credentials and API keys.

Findings are mapped to OWASP categories and assigned severity-based priority: critical=P0, high=P1, medium=P2, low=P3.
*   **Option**: `--create-defects`: Generates defect specs for findings above the configured severity threshold (default: medium). Cached audit results are reused if less than 1 hour old.

### `defect <spec-path>`
Triages a defect spec through the defect pipeline. The triage agent assesses complexity (trivial, moderate, complex). Trivial defects auto-continue through fix and integration within the same invocation. Moderate and complex defects stop after triage for review.
*   **Usage**: `speed defect specs/defects/my-bug.md`

### `gates`
Runs quality gates manually against a specific task.
*   **Required**: `--task ID`
*   **Modes**:
    *   `--fast` (default): Syntax check + lint + typecheck only.
    *   `--full`: Grounding gates + all quality gates including tests. Passing gates on a failed task promotes it to "done".
*   **Option**: `--worktree <path>`: Override the worktree path (auto-detected if omitted).

### `ci`
Verifies the whole project the way a CI server should, without calling a model. It runs the same way on a laptop and in GitHub Actions, needs no model CLI installed, and writes `.speed/ci/report.json` plus one log per command under `.speed/ci/logs/`. Only one `speed ci` runs in a project at a time.

| Check | What it runs | When it fails |
|---|---|---|
| `eval` | `speed eval` for every feature, or the one given with `--feature`. Runs first, while the tree is exactly as checked out. | A finished feature is not accepted, a feature has failed or blocked tasks, or its configured test spec is missing. Features with work in progress, no tasks or no test spec are skipped. Under `speed ci` the checked-out commit counts as the integrated code, so evals need no local feature state; a task branch that exists (locally or as a remote-tracking ref) and is not in HEAD still fails. This relaxed verdict stays in the CI report; `speed ci` never writes `.speed/features/*/state.json`. |
| `lint`, `typecheck`, `test`, `e2e` | Every matching command in the `## Quality Gates` section of `AGENTS.md` or `CLAUDE.md` (for example `- e2e: npm run test:e2e`). `###` headings group gates; any other heading ends the section, so examples under a `####` heading are never run. A command written as one code span (`` - test: `npm test` ``) loses its backticks; backticks inside a command are kept as shell syntax. | Any command exits non-zero or runs longer than `[ci] command_timeout` (default 1800 seconds). `test` also fails when no test command is configured; the others are skipped. The full suite runs, with no task-scoped fallback. |
| `secrets` | The secret patterns (AWS keys, GitHub tokens, `sk-` keys, private keys, long quoted strings, database URLs, or `[security] secrets_patterns`) over every tracked file, including committed `.env` files and files git treats as binary. A value that matches no pattern is not caught. In the generated `.github/workflows/speed-ci.yml` only, lines marked `speed-ci: test service credential` (its throwaway database settings) are skipped; the mark has no effect in any other file. Excludes `*.example` and `tests/fixtures/**` (or `[security] secrets_exclude`, which can also leave out the workflow file), and always lockfiles, whose hashes look like secrets. | Any match. Only the pattern name, file and line are reported, never the matched text. |
| `sast`, `sca` | `[security] sast_cmd` and `sca_cmd`, which must print one Semgrep or Bandit (sast), or npm audit 7+ or pip-audit (sca), JSON document to stdout | A finding at or above `[security] severity_threshold` (default `high` for CI; a severity SPEED does not recognise counts as blocking). Also fails when the output is not exactly one supported JSON document, the scanner reports a fatal error, it exits non-zero without any finding, or it times out. Per-file scanner warnings are counted but do not fail the check. Skipped when the command is not set. The raw scanner output is written outside `.speed/ci` and deleted; the scanner's log is kept with secret-pattern matches replaced by `[redacted]`. |

*   **Options**:
    *   `--skip CHECK[,CHECK]`: Leave out checks, for example `--skip e2e,sca`. Not allowed with `--pr`.
    *   `--feature NAME`: Evaluate only this feature (it must exist).
    *   `--json`: Print the report as one JSON object on stdout.
*   **Exit codes**: 0 every check passed or was skipped, 2 a check failed, 3 the checks could not run (another run is active, `speed.toml` cannot be parsed, an invalid `severity_threshold` or `command_timeout`, an unknown feature). With exit 3, `--json` prints `{passed, error, exit_code, steps}` and the previous `report.json` is left as it was.
*   **Time limit**: speed ci needs GNU `timeout` (or `gtimeout`, from coreutils on macOS) to enforce `command_timeout`. Without it, speed ci stops at startup with exit 3 (with `--json`, the error object is still printed). A command that exits 124 by itself before the limit is a plain failure, not a timeout.
*   **Tokens**: gate, e2e, custom-check and eval commands run without the scanner tokens (`token_env` names and `SONAR_TOKEN`), and the values of those tokens, `GITHUB_TOKEN`, `GH_TOKEN` and `SPEED_REPO_TOKEN` are replaced by `[redacted]` in logs, the report, SARIF, JUnit and the summary.
*   **Eval summaries**: each evaluated feature's summary is kept at `.speed/ci/eval/<feature>-summary.md`.

*   **Demo**: `examples/speed-ci-demo` turns on every check, with Trivy, Gitleaks and CodeQL reading sample outputs; run `speed ci` in it.

#### Custom checks, security mode, tools and SonarQube
*   **Custom checks**: every other name in `## Quality Gates`, for example `- api: npm run api:verify`, `- coverage: npm run test:coverage` or `- integration: npm run test:integration`, runs as its own check after `e2e`, with its own pass or fail, under the name as written. Every `- Name: text` bullet in the section is run as a shell command, so keep explanations outside it. `[ci] ignore_gates = ["deploy"]` leaves names out (compared without case); a built-in check cannot be ignored this way, use `--skip` for that. A name speed ci cannot run is refused with exit 3 rather than skipped: names must start with a letter and hold only letters, digits, `-` and `_`; they cannot be a built-in check (`eval`, `lint`, `typecheck`, `test`, `e2e`, `secrets`, `sast`, `sca`, `sonarqube`), a name speed ci uses itself (`clean-tree`, `merge-jobs`, `merge-commit`, `report`, `check`), a `[ci.tools.*]` name, or differ from another gate only by case; `lint`, `typecheck`, `test` and `e2e` must be lowercase. A `name: command` line whose name has a space or a dot, uses a `*` or `+` bullet, or wraps the name in backticks or bold is refused too; list it in `ignore_gates` to leave it out.
*   **Security mode**: `[ci] security_mode = "strict"` (default) fails on findings at or above the threshold. `"report"` records them as warnings (`!`) without failing CI; a scanner that crashes or prints output SPEED cannot read still fails. The mode covers `sast`, `sca` and the tools below. SPEED's own `secrets` scan always blocks. A run whose only problems are warnings exits 0, and `speed ci --pr` posts `success` and opens a ready PR whose status and body count the warnings.
*   **Tools** (`[ci.tools.NAME]`): each runs as its own check, judged by the same threshold and mode.

    | Tool | Settings | Default command |
    |---|---|---|
    | Trivy | `[ci.tools.trivy]` | `trivy fs --format json --quiet --scanners vuln,misconfig,secret .` |
    | Gitleaks | `[ci.tools.gitleaks]` | `gitleaks detect --no-banner --redact --report-format json --report-path - --log-opts=HEAD` (the checked commit and its history only) |
    | Snyk | `[ci.tools.snyk]` (needs `SNYK_TOKEN`) | `snyk test --json` |
    | CodeQL or any SARIF producer | `[ci.tools.codeql]` with `format = "sarif"` and `cmd = "..."` | none |

    `cmd` replaces the default, `format` is one of `trivy`, `gitleaks`, `snyk` or `sarif`, and `token_env` names the environment variable holding the tool's token: an upper-case name such as `SNYK_TOKEN` (letters, digits and `_`, starting with a letter), and not `PATH`, `HOME`, `CI` or a name starting with `GITHUB_`, `RUNNER_`, `ACTIONS_` or `SPEED_`. Tool names are lowercase letters, digits, `-` and `_`. A tool's raw output is written outside `.speed/ci`, read, and deleted on every path, including a timeout and Ctrl+C, so code snippets and secrets a tool found are never kept or uploaded; only the normalised findings are. Tool logs keep stderr with secret-pattern matches replaced by `[redacted]`, and Gitleaks' stderr is not kept at all. SARIF results take their severity from the rule's `security-severity`, including rules CodeQL keeps under `tool.extensions`. Snyk results include `applications`, and a vulnerability reached through several dependency paths counts once. When a tool's token is missing on a pull request from a fork or Dependabot (`SPEED_CI_SECRETS_UNAVAILABLE=true`, set by the generated workflow), the check is skipped instead of failed.
*   **SonarQube or SonarCloud** (`[ci.sonarqube]` with `host_url` and `project_key`, plus `organization` for SonarCloud): runs `scanner_cmd` (default `sonar-scanner`) with `-Dsonar.qualitygate.wait=false`, waits up to `wait_timeout` seconds (default 300) for the analysis, retrying while the server is busy (5xx or 429), and reads the quality gate. A `host_url` on localhost is a developer's own server: inside CI (`CI` or `GITHUB_ACTIONS` is `true`) the check is skipped with that reason, since a CI runner cannot reach it; use SonarCloud or a shared server to check in CI. `host_url` must use https (http only for localhost) and be the server address only, with no query, fragment or login, and a redirect is refused so the token never goes to another host. OK passes, WARN warns, ERROR fails and lists the failed conditions with what each metric needs (for example `new_coverage 41.0 (needs at least 80)`) (or warns with `blocking = "false"`). The result links the dashboard. The token comes from `SONAR_TOKEN`, which the scanner reads from the environment; it is never put on the command line. On a developer's machine, `token_file = "~/path/to/token"` reads it from a file when `SONAR_TOKEN` is not set (it is redacted like any token). `report_task` changes where the scanner writes `report-task.txt` (default `.scannerwork/report-task.txt`; Maven and Gradle use `target/sonar/` and `build/sonar/`).
*   **Reports**: besides `report.json`, every run writes `.speed/ci/speed-ci.sarif` (findings from `secrets`, `sast`, `sca` and the tools, for GitHub's Security tab), `.speed/ci/junit.xml` (one test case per check), and, when `GITHUB_STEP_SUMMARY` is set, a results table on the GitHub Actions run page.
*   **Other options**: `--only CHECK[,CHECK]` runs just those checks (the others are recorded with `selected: false`), and `--list` prints the project's checks. `--skip` and `--only` match names without case, cannot be combined, need at least one name, and are refused with `--pr`.
*   **Report**: `report.json` has `passed`, `commit`, `branch`, `started_at`, `finished_at`, `summary` (`pass`, `fail`, `warn`, `skipped`) and `steps`. Exit 3 also covers an invalid or unknown (misspelled) `[ci]`, `[ci.tools.*]` or `[ci.sonarqube]` setting, a Quality Gates name that cannot run, and an unknown name for `--skip` or `--only`.

#### `ci merge DIR...`
Combines the `.speed/ci` directories of checks run as separate jobs into one report (and SARIF, JUnit and summary) in `.speed/ci`. Each check's result comes from the job that ran it; when more than one job reports a check, the most severe result counts (fail, then warn, then pass, then skipped). A check no job reported, a job with no readable report (`merge-jobs`), or jobs that checked different commits (`merge-commit`) fail the result. Exit codes: 0 passed, 2 failed, 3 the reports could not be combined (for example a job directory that is also `.speed/ci`); with exit 3 the previous report is left as it was. `ci merge` does not take the run lock, so do not run it while a `speed ci` is running in the same project.

#### `ci init`
Writes `.github/workflows/speed-ci.yml`, which runs `speed --json ci` on every pull request and every push to the main branch, then uploads the report and logs and sends the SARIF findings to GitHub's Security tab (this needs code scanning: public repositories, or GitHub Advanced Security on private ones; the step does not fail the run without it). The workflow follows `speed.toml`:
*   `[ci] services = ["postgres", "mysql", "redis"]` adds database containers for integration tests, with `DATABASE_URL` (and `PGHOST`, `PGUSER`, ...), `MYSQL_URL` or `REDIS_URL` set for every step.
*   `[ci] parallel = true` runs each check as its own job at the same time, each uploading a `speed-ci-check-<name>` artifact; with `services`, the `test`, `e2e` and custom checks run in a `check-db` job that has the databases and the others start none. A final `speed-ci` job (skipped when a newer push cancelled the run) combines them with SPEED's merge helper (the same logic as `speed ci merge`), and that one check is the one to require in branch protection.
*   `[ci.codecov]` (optional `files`) adds a Codecov upload with the `CODECOV_TOKEN` secret. With `parallel = true`, `check` (default `test`) names the job that uploads, and must be one of the project's checks.
*   SonarQube and tools that need a token get it from repository secrets (`SONAR_TOKEN`, `SNYK_TOKEN`) on the step that runs speed ci only, and with `parallel = true` only in the job whose check needs it; `speed ci init` lists the secrets to add. With SonarQube the project is checked out with full history (`fetch-depth: 0`).
*   The workflow installs pinned versions of Trivy, Gitleaks, Snyk and sonar-scanner when they run their default command; for a custom `cmd` or `scanner_cmd`, `speed ci init` says to add the install step to the project setup. Rerun `speed ci init --force` after adding checks, tools or services.

 Run it at the repository root, where GitHub reads workflows. It installs SPEED from its GitHub repository and adds setup steps for the project's toolchain when it finds `package.json`, `requirements.txt`, `pyproject.toml` or `go.mod`. Checkouts do not keep their tokens, so the project's own scripts cannot read them.
*   **Options**:
    *   `--speed-repo OWNER/REPO`, `--speed-ref REF`: Where to install SPEED from. Defaults to the origin remote of the SPEED checkout and the upstream of its current branch (or the remote's default branch). A private SPEED repository needs a `SPEED_REPO_TOKEN` secret that can read it.
    *   `--force`: Replace an existing workflow file.

#### `ci --pr`
Takes a feature whose tasks are all done and, in a temporary worktree, merges its task branches in dependency order onto the published base (`origin/main`), with plain `git merge` and no model. It runs every check there, pushes the result to `speed-ci/<feature>`, opens or updates the pull request with `gh`, and posts the result as a commit status (`speed/ci`, or `[ci] status_context`). A failing run still opens the PR, as a draft, with a failure status; a later passing run marks it ready.
*   **From plain `speed ci`**: with `[ci] pull_request = true` in `speed.toml`, a full `speed ci` on a developer's machine also does this for every finished feature that has a task branch not yet in the main branch (or the `--feature` one), one block per feature; with no such feature it only checks. Each feature's report and PR body are also kept in `.speed/ci/pr/<feature>/`. It never does so when `CI` or `GITHUB_ACTIONS` is `true`, or with `--skip` or `--only`, so the workflow's own runs only check. With `--json`, more than one waiting feature needs `--feature`.
*   **For the current branch**: with `[ci] pull_request = "branch"`, a full `speed ci` on a developer's machine, on any branch but the main one, checks that branch where it is (plus `clean-tree`), pushes it (never forced), opens or updates its PR into the main branch, and posts the status, in the same output. It refuses uncommitted changes, which the PR would not contain, and only checks on the main branch, inside CI, or with `--skip` / `--only`.
*   **Output**: the merge, push, PR and status steps print as lines in the same block as the checks (`merge` first; `push`, `pr` and `status` after `clean-tree`), followed by the PASSED or FAILED line.
*   **Your checkout is never touched**: no branch switch, no local branch created, and uncommitted work stays where it is (it is not part of the PR). Dependencies such as `node_modules` and `.venv` are linked into the worktree the same way `speed run` does (`[worktree.symlinks]`).
*   **Requires**: a remote whose URL is on github.com and `gh` logged in (`gh auth login`). `--repo` picks the repository the PR is opened in, but the pushed remote must still be a github.com URL so the PR head is known.
*   **Safety**: the PR branch cannot be the base, the current branch or a task branch (compared without case). If the remote PR branch has commits that did not come from the task branches, the run stops unless you pass `--force`, and the push uses `--force-with-lease` against the tip it checked. The checks must leave tracked files unchanged (`clean-tree`), so the status always describes the pushed commit.
*   **Options**: `--feature NAME`, `--base BRANCH`, `--branch NAME`, `--remote NAME` (default `origin`), `--repo OWNER/REPO` (a PR into another repository names its head `OWNER:branch`), `--draft`, `--force`, `--dry-run` (assemble and check locally from the local base, push nothing).
*   **Exit codes**: 0 checks passed, 2 checks failed (the PR is still opened), 3 could not run, 4 a task branch conflicts.

### `guardian [file]`
Runs the Product Guardian vision check. Two modes:
*   **Ad-hoc**: `speed guardian <file>` evaluates any file against the product vision.
*   **Feature**: `speed guardian` (no argument) evaluates the current feature's spec and task plan against the product vision.

### `status`
Displays current orchestration state for the active feature (or the one specified with `--feature`). Output includes:
*   Feature list with task progress counts (done/running/failed).
*   Task dependency graph and summary.
*   Security findings summary (critical/high/medium/low/info) aggregated from SAST, SCA, and secrets scans.
*   Failure classification breakdown (pipeline vs. complexity, with per-subclass counts).
*   Timed-out tasks that may need decomposition.
*   Latest Supervisor analysis (diagnosis, detected patterns, root cause, recommendations).
*   **Option**: `--defects`: Show defect state instead of task state.

### `add-language <language>`
Adds tree-sitter extraction support for a new programming language. Validates the grammar package is installed, reads `node-types.json`, generates draft ast-grep YAML rules via LLM, and registers the language in `extraction.toml`. Review generated rules with `speed test-rules <language>`.

### `test-rules [language | --all]`
Runs ast-grep rules against fixture files and compares output to expected results. Without arguments, tests the active language. With `--all`, tests every registered language. Reports PASS/FAIL/OK per fixture.

### `discover domains`
Discovers the business domains in the repository: their activities, entities, rules and the evidence behind each. Without options it extracts facts from the source, then has the model synthesize and verify a domain model, and publishes it to `.speed/context/business-domains.json`. Large repositories run in hierarchical mode: slices of entry points are synthesized separately and reconciled into one model. An interrupted run resumes from its cache when started again.
*   `--facts-only`: Extract facts without calling a model and print the extraction report.
*   `--status`: Show the latest attempt and whether a model is published.
*   `--cancel`: Ask a running discovery to stop.
*   `--review FILE`: Apply reviewed corrections from a JSON file to the published model, without calling a model. The file holds `{"author": "...", "decisions": [{"explanation": "...", "operation": {...}}]}`. Besides the context operations (accept, reject, rename, set_membership, merge, split), an operation can be `correct_rule` (`rule_id`, `set` with any of name, description, outcome, preconditions, predicate_or_formula, category, enforcement_status, unresolved_questions, enforcement_sites, plus optional `drop_evidence_ids` / `add_evidence_ids`, and `cite` with `{path, start_line, end_line}` line ranges that are read from the repository and recorded as evidence), `merge_rules` (`rule_ids`, first one kept), `correct_activity` (`activity_id`, `set` with name, description or unresolved_questions) or `correct_domain` (`domain_id`, `set` with summary, boundary_rationale, unresolved_questions or alternatives). Each decision is saved in `business-domain-overrides.json` with its author and explanation, recorded as review evidence, and replayed on later discovery runs. Decisions already applied are skipped. Run `--export ddd` afterwards to refresh the documents; corrected rules are marked "corrected after review".
*   `--export ddd [--out DIR]`: Write domain-driven design documents from the published model, without calling a model: an overview (context map, relationships, entity class diagram, aggregates, a table-level ER diagram and a completeness check that counts every model record against the documents), one page per bounded context (use cases, entities, data access, links, an architecture diagram by layer, call sequences, rules), a business-rules catalog, a glossary and a page of gaps. Diagrams are Mermaid, which GitHub renders; `index.html` shows every page and diagram in a browser (it loads marked and mermaid from jsDelivr); the command prints its `file://` link, and `--json` returns it as `viewer`. Output goes to `.speed/context/business-domain-ddd/` unless `--out` names another directory (relative to where the command runs). Each run rewrites the files it owns, listed in `manifest.json`, and leaves other files alone. It refuses with `EXPORT_CONFLICT` rather than overwrite a file it did not write, so point `--out` at an empty or new directory. Exits 1 with `DOMAIN_DISCOVERY_MISSING` when nothing is published, and with `EXPORT_WRITE_FAILED` when the directory can't be written.

## Multi-Player Commands

These commands are available after running `speed mp-init`. See the [Multi-Player Mode](/docs/multiplayer/) guide for the full workflow.

### `mp-init`
Initializes multi-player mode on an existing SPEED project. Creates the `shared/` and `local/` zone split under `.speed/`, migrates existing features, memory, worktrees, and the dashboard database to their new locations. Updates `.speed/.gitignore` to ignore only `local/` and updates the project `.gitignore` from `.speed/` to `.speed/local/`. Safe to run on a project that's already initialized (no-op).

### `claim <feature>`
Claims exclusive ownership of a feature. Emits a `feature.claimed` event to the shared event log. If another actor holds the claim, exits with an error showing the current owner. Creates the shared feature directory if it doesn't exist.

### `release <feature>`
Releases ownership of a feature. Emits a `feature.released` event. Only the current owner can release. Unclaimed features return a no-op.

### `whoami`
Prints the resolved actor identity and filesystem slug. Resolution order: `$SPEED_ACTOR` env → `git config user.name` → `$(whoami)`. Works without multi-player mode enabled.

### `rebuild-state`
Replays the shared event log and compares reconstructed task state against materialized task JSON files. Reports matches and divergences.
*   **Default**: Dry-run mode, reports only.
*   **Option**: `--apply`: Overwrites materialized state where it diverges from the event log.

### `status --team`
Displays the team roster: all actors who have run a `speed` command in the last 24 hours, their active feature, current stage, last seen time, and last command. Requires multi-player mode.

### `learn --merge`
Processes pending knowledge proposals in `shared/proposals/`. Non-conflicting conventions are auto-merged into `shared/knowledge/conventions.json` with confidence scoring. Conflicting proposals are written to `shared/knowledge/conflicts.json`.

### `learn --curate`
Interactive conflict resolution. Walks through each entry in `conflicts.json` and prompts for a decision: keep existing, accept proposed, or skip. Resolved entries are locked against future auto-modification.

### `learn --pending`
Lists all pending (unmerged) knowledge proposals with their actor, feature, observation count, and timestamp.

### `learn --prune`
Archives events older than 30 days (configurable via `speed.toml` `[multiplayer] prune_days`) into per-feature archive files. Reduces directory clutter without losing event history. Requires multi-player mode.

### `validate --all-active`
Cross-references all active (claimed) feature specs against each other. Detects contradictory requirements, incompatible schema changes, overlapping file ownership. Outputs a recommended integration order based on overlap density. Requires multi-player mode.

### `coherence --cross-feature`
Checks completed branches across all active features for compatibility. Finds interface mismatches, conflicting modifications to shared files, incompatible migrations. Requires multi-player mode.

### `spec propose <spec-path>`
Creates a review request event for a spec. Blocks `speed plan` until the spec is ratified. Records the spec content hash for change tracking.

### `spec review [--approve|--reject] [--comment "..."] [spec-path]`
Without flags, lists all pending spec proposals with approval counts. With `--approve` or `--reject`, submits a verdict as an event. Comments are optional.

### `spec ratify <spec-path>`
Checks the approval threshold (default 1, configurable in `speed.toml`). If met and no rejections are outstanding, emits a `spec.ratified` event that unlocks planning. Rejected specs must be re-proposed after addressing feedback.

### `review request`
Posts outcome evidence (task counts, review results, guardian verdicts) for team review. Run after `speed run` and `speed review` complete.

### `review judge [--approve|--reject] [--comment "..."]`
Submits a verdict on an outcome review as an event. Requires multi-player mode.

### `review status`
Shows consolidated feedback from the outcome review: who requested, evidence summary, all verdicts with comments.

### `sync start|stop|status`
Manages the background sync daemon. The daemon watches `.speed/shared/` for changes, auto-commits and pushes events/roster, and pulls remote changes on a configurable interval.
*   `start [--interval N]`: Start daemon (default: 30s interval).
*   `stop`: Stop daemon.
*   `status`: Show running state and recent log entries.

### `serve [start|stop|status]`
Manages the multi-player HTTP server. Serves roster, events, and features as REST endpoints. Provides claim arbitration to prevent race conditions.
*   `start [--port PORT]`: Start server (default: port 4450).
*   `stop`: Stop server.
*   `status`: Show running state.
*   **Endpoints**: `/api/roster`, `/api/events`, `/api/features`, `/api/claim` (POST), `/api/health`.

### `clean`
Removes runtime state.
*   `speed clean logs`: Clears log files (scoped to active feature when one is set).
*   `speed clean all`: Removes the entire `.speed/` state.
*   `speed clean feature <name>`: Removes a specific feature's state and associated worktrees.

### `fix-nits [--task-id ID]`
Creates a new task from reviewer nits collected during the last review. The generated task includes file paths, line numbers, severity, and suggested changes. Dependencies are set to the source tasks that produced the nits. The optional `--task-id` flag filters nits to a single source task.

### `recover`
Emergency recovery from a crashed session. Breaks stale locks, kills orphan agent processes, resets tasks stuck in "running" state to pending, cleans stale state directories, and removes orphaned worktrees.

### `dashboard start|stop|status|ingest`
Manages the monitoring dashboard.
*   `start [--port PORT] [--api-only]`: Launches FastAPI backend (default port 4440) and Next.js frontend (port 3000).
*   `stop`: Graceful shutdown with timeout, then force-kills.
*   `status`: Shows running/dead state of dashboard processes.
*   `ingest`: Backfills the dashboard database from state files without starting the server.

### `self-update`
Updates the SPEED installation atomically. Uses a staging directory and symlink swap, rebuilds the Python venv only when dependencies change, and retains the previous version for rollback. Requires a managed install (not a git clone).

### `self-uninstall`
Removes the SPEED installation (`~/.speed/`) and cleans PATH entries from shell configuration files (`.zshrc`, `.bashrc`, `.bash_profile`, fish config).

## Exit Codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Task failure (one or more agents failed) |
| 2 | Gate failure (lint, test, or contract check failed) |
| 3 | Config error (missing binary or invalid setup) |
| 4 | Merge conflict during integration |
| 5 | Halted (failure rate exceeded 30%) |
| 130 | User abort (Ctrl+C) |
