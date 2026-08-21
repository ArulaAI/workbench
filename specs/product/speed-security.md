# Security Auditor & Security Gates

## Problem

SPEED's Reviewer agent checks security as one bullet among many concerns. Secrets committed to source, injection vulnerabilities, authentication bypasses, and insecure defaults pass through the pipeline undetected unless a human catches them during review. There is no dedicated mechanism for static analysis, no structured way to surface security findings, and no gate that prevents a committed secret from reaching integration.

## Users

### Engineering
Writes the code that introduces vulnerabilities. Wants automated detection during development, not after merge. A security finding surfaced at the `speed run` stage costs minutes to fix; the same finding caught in production costs days.

### Product
Needs assurance that security is not an afterthought. Wants visibility into the security posture of each feature before signing off on integration, without needing to understand the technical details of every finding.

### Security Teams
Operates outside the day-to-day SPEED pipeline but needs a window into it. Wants structured findings they can triage, track, and audit, formatted consistently regardless of which SAST or SCA tool produced them.

## User Stories

| ID | Story | Acceptance Criteria | Priority |
|----|-------|---------------------|----------|
| S1 | As an engineer, I want SAST tools to run automatically during quality gates so that common vulnerability classes are caught before review | Given a project with `[security]` configured in `speed.toml` including `sast_cmd`, when `speed run` executes quality gates, then the configured SAST tool runs and its findings appear in gate output | Must |
| S2 | As an engineer, I want a dedicated security audit stage that reads full source files and reports findings with severity and category | Given a completed feature branch, when I run `speed security`, then the Security Auditor agent reads all files in the feature scope, produces a findings report with severity/category/file/line for each issue, and prints a summary banner | Must |
| S3 | As an engineer, I want committed secrets detected and blocked at grounding gates so they never reach integration | Given a file containing a hardcoded API key, database password, or private key, when grounding gates run, then the gate fails with a blocking error identifying the file and line containing the secret | Must |
| S4 | As an engineer, I want security findings to warn loudly but never block integration so I can ship with known low-severity issues when the tradeoff is justified | Given security findings from SAST or the Security Auditor, when integration runs, then findings are printed as prominent warnings with severity, but integration proceeds unless a committed secret is detected | Must |
| S5 | As an engineer, I want to configure my project's SAST toolchain and secrets scanning exclusions in `speed.toml` so that SPEED uses the tools my team trusts and doesn't flag legitimate credential files | Given a `[security]` section in `speed.toml` with `sast_cmd`, optional `severity_threshold`, and optional `secrets_exclude` globs, when quality gates run, then SPEED invokes the declared SAST command, parses its output, and skips secrets scanning for files matching the exclusion globs | Must |
| S6 | As a product person, I want a warning when a feature spec has no Security section so that security considerations are addressed during planning | Given a PRD or RFC spec file, when `speed audit` runs, then a warning is emitted if the `## Security & Controls` section is missing or empty, without blocking the audit | Should |
| S7 | As an engineer, I want security findings routed to defect specs via `--create-defects` so I can track and fix them through the defect pipeline | Given security findings from `speed security`, when I run `speed security --create-defects`, then each finding above the configured severity threshold produces a defect spec in `specs/defects/` with severity, category, file, and reproduction details pre-populated | Should |
| S8 | As an engineer, I want security status visible in `speed status` so I can see the security posture of in-progress features at a glance | Given a feature with security findings, when I run `speed status`, then the status output includes a security summary line showing total findings by severity | Should |
| S9 | As a security team member, I want security defects to skip trivial classification and route directly to moderate-or-higher triage so that security issues receive appropriate scrutiny | Given a defect spec created by `speed security --create-defects`, when the defect enters triage, then the defect is tagged `security` and classified as moderate or higher regardless of file count | Could |
| S10 | As an engineer, I want dependency vulnerability checks (SCA) to run during quality gates so that known CVEs in my dependency tree are surfaced alongside SAST findings | Given a project with `sca_cmd` configured in `speed.toml`, when `speed run` executes quality gates, then the SCA tool runs against the project's lockfiles and findings appear as warnings in gate output | Must |

## User Flows

### Full pipeline with security gates

1. Engineer configures `[security]` in `speed.toml` with `sast_cmd` and `sca_cmd`
2. Engineer runs `speed run` on a feature
3. Developer Agent produces code on an isolated branch
4. Quality gates execute: lint, typecheck, test, SAST, then SCA
5. SAST tool runs against changed files, produces JSON findings
6. SCA tool runs against lockfiles (`package-lock.json`, `Pipfile.lock`, etc.), produces JSON findings
7. All findings are parsed, categorized, and printed as warnings in gate output
8. Quality gates pass (SAST and SCA findings are non-blocking)
9. Feature proceeds to review and integration
10. Security warnings appear in the integration summary banner

### Committed secret blocked at grounding

1. Developer Agent produces a file containing `OPENAI_API_KEY="sk-abc123..."` in `src/config.py`
2. Grounding gates run before quality gates
3. Secrets scanner checks changed files against exclusion globs (`.env*`, `*.example`, `tests/fixtures/**` by default). `src/config.py` is not excluded.
4. Scanner detects the hardcoded key pattern
5. Grounding gate **fails** with a blocking error: file, line, and pattern matched
6. Pipeline halts. The secret never reaches a commit on the feature branch
7. Engineer sees the error, removes the secret, retries with `speed retry`

Note: if the same key appeared in `.env.dev` or `tests/fixtures/mock-credentials.env`, the scanner would skip those files. The exclusion list is configurable via `secrets_exclude` in `speed.toml`.

### SAST warning during development

1. Developer Agent writes code with an unparameterized SQL query
2. Quality gates run SAST
3. Semgrep flags "possible SQL injection" at medium severity
4. Warning printed: `[SECURITY WARN] medium: possible SQL injection — src/api/users.py:42`
5. Quality gates pass (non-blocking)
6. Engineer sees the warning, can fix now or defer
7. If deferred, warning persists in `speed status` and integration summary

### No SAST toolchain configured

1. Engineer runs `speed run` on a project without `[security]` in `speed.toml`
2. Quality gates run: lint, typecheck, test
3. SAST stage is skipped with an info message: `[INFO] No SAST toolchain configured. Add [security] to speed.toml to enable.`
4. Grounding-level secrets scanning still runs (always on, no configuration needed)
5. Pipeline proceeds normally

### Creating defects from security findings

1. Engineer runs `speed security` after feature development
2. Security Auditor agent reads all feature-scope files, produces findings report
3. Report shows 2 medium findings, 1 low finding
4. Engineer runs `speed security --create-defects`
5. SPEED creates defect specs: `specs/defects/sec-sql-injection-users.md`, `specs/defects/sec-missing-auth-check.md` (medium and above, filtered by threshold)
6. Each defect spec is pre-populated with severity, category, affected file, line, and the finding description as reproduction steps
7. Engineer can now run `speed defect` on each to enter the defect pipeline

## Success Criteria

- [ ] `speed run` executes configured SAST tools during quality gates and prints findings as warnings
- [ ] Committed secrets are detected by grounding gates and block the pipeline with a clear error message
- [ ] Security findings from SAST and the Security Auditor never block integration (secrets excepted)
- [ ] `speed security` runs the Security Auditor agent and prints a findings summary with severity, category, file, and line
- [ ] `speed security --create-defects` generates defect specs from findings above the configured severity threshold
- [ ] `speed run` executes configured SCA tool during quality gates and prints dependency vulnerability findings as warnings
- [ ] `speed.toml [security]` section configures SAST command, SCA command, severity threshold, secrets patterns, and secrets exclusion globs
- [ ] Files matching `secrets_exclude` globs are skipped by the secrets scanner (defaults: `.env*`, `*.example`, `tests/fixtures/**`)
- [ ] `speed audit` warns (not errors) when a spec is missing its `## Security & Controls` section
- [ ] `speed status` includes a security summary line for features with findings
- [ ] Security defect specs created by `--create-defects` include pre-populated severity, category, file, line, and reproduction context
- [ ] Grounding-level secrets scanning runs unconditionally, even without `[security]` configuration

## Scope

### In Scope
- Tier 1: SAST tool integration as a quality gate stage (configured via `speed.toml`)
- Tier 1: SCA (dependency vulnerability) integration as a quality gate stage (configured via `sca_cmd` in `speed.toml`), leveraging built-in ecosystem commands (`npm audit`, `pip-audit`, `cargo audit`, etc.)
- Tier 2: Security Auditor agent (`agents/security-auditor.md`) that reads full files and produces structured findings
- Grounding-level secrets detection (always on, blocking)
- `[security]` configuration section in `speed.toml`
- `speed security` CLI command (run auditor, print report)
- `speed security --create-defects` (generate defect specs from findings)
- Security findings in `speed status` output
- `speed audit` warning for missing `## Security & Controls` sections
- Security defect type with routing to moderate-or-higher triage

### Out of Scope (and why)
- **DAST / runtime security testing** — Requires a running application environment. SPEED operates on source code and specs, not live systems. DAST is a deployment-phase concern.
- **Runtime monitoring and alerting** — Same boundary as DAST. SPEED's pipeline ends at integration. Post-deployment monitoring belongs to infrastructure tooling.
- **Custom CVE database or advisory feed** — SPEED delegates dependency scanning to the project's existing SCA tool (`npm audit`, `pip-audit`, etc.) via `sca_cmd`. Building or syncing a proprietary CVE database adds maintenance burden with no advantage over the ecosystem tools that already track advisories.
- **Auto-remediation of security findings** — Automatically rewriting code to fix vulnerabilities risks introducing subtle behavioral changes. Security fixes require human judgment about intent. The defect pipeline (`--create-defects`) provides the structured path instead.

## Dependencies

- **Existing SPEED pipeline infrastructure** — Quality gates (`lib/gates.sh`), grounding gates (`lib/grounding.sh`), CLI command dispatch (`speed`), agent execution (`lib/provider.sh`), configuration loading (`lib/config.sh`, `lib/toml.py`)
- **Defect pipeline** ([Phase 3: Defect Pipeline](speed-defects.md)) — Required for `--create-defects` functionality. Security findings become defect specs that enter the existing defect triage pipeline. Without the defect pipeline, `--create-defects` is unavailable.
- **Audit agent** ([Phase 2: Audit Agent](speed-audit.md)) — The `## Security & Controls` warning integrates into the existing audit check levels. The audit agent must support configurable warning rules.

## Security & Controls

**Agent access:** The Security Auditor agent has read-only codebase access. No file writes, no shell commands, no network calls. It reads source files and produces a findings report. SAST tools are invoked by the pipeline shell, not by the agent.

**No new PII surfaces:** Security findings contain file paths, line numbers, and code snippets. No user data, credentials, or personal information is introduced. The findings JSON is stored locally in `.speed/features/<name>/logs/`.

**Input sanitization:** File paths passed to SAST tool commands are validated against the project root. The `sast_cmd` value from `speed.toml` is executed as a shell command, so `speed.toml` must be treated as a trusted configuration file (same trust model as `CLAUDE.md`).

**Secrets in output:** The secrets scanner must not echo the detected secret value in its output. Error messages reference file and line number only, pattern matched (e.g., "AWS key pattern"), not the actual secret content.

**Local-only:** All commands run locally. No security findings are transmitted externally. No telemetry, no cloud dashboards.

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| False positive fatigue from SAST tools drowns real findings in noise | Medium | Configurable `severity_threshold` in `speed.toml` filters low-confidence results. Warnings are categorized by severity so engineers can focus on high/critical first. |
| Security defects routed through triage may be misclassified by the Triage Agent, which lacks security domain expertise | Medium | Security defects skip trivial classification (S9) and are tagged `security` for visibility. Triage output includes the original SAST finding for context. |
| SAST tool availability varies across environments (CI vs local dev, different OS) | Low | SAST is optional. Missing tool produces a clear error message with install instructions. Grounding-level secrets scanning uses built-in patterns (no external tool dependency). |
| Agent token cost for full-file Security Auditor reads on large features | Low | The Security Auditor runs on-demand (`speed security`), not on every `speed run`. Engineers invoke it when they want a deep scan, keeping routine pipeline runs fast. |

## Open Questions

| ID | Question | Impact | Status |
|----|----------|--------|--------|
| Q1 | Should the Security Auditor agent use the `planning_model` or `support_model`? Full-file reads benefit from larger context, but cost scales with file count. | Determines agent cost per run and quality of findings. | Open |
| Q2 | What built-in secrets patterns should ship by default? AWS keys, GitHub tokens, and generic high-entropy strings are standard, but the list needs scoping. | Determines false positive rate of the always-on secrets scanner. | Open |
| Q3 | Should `--create-defects` require explicit confirmation before writing defect specs, or should it write them immediately? | Affects workflow friction. Immediate write is faster; confirmation prevents accidental defect spam from noisy SAST output. | Open |
| Q4 | How should security findings interact with the Product Guardian? Should the Guardian see the security summary, or is that outside its mandate? | Determines whether security posture influences the Guardian's ship/hold decision. | Open |
