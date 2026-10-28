# speed ci demo

A tiny project with every `speed ci` check turned on, so one command shows all of them:

```bash
cd examples/speed-ci-demo
speed ci
```

| Check | Phase | What feeds it here |
|---|---|---|
| eval | 1 | the finished feature in `.speed/features/adding` and its test spec `specs/tests/adding.md` |
| lint, typecheck, test, e2e | 1 | `## Quality Gates` in `AGENTS.md` (tests run with `run_tests.py`, standard library only) |
| api | 2 | a custom Quality Gates check |
| secrets | 1 | SPEED's own scan of every tracked file |
| sast, sca | 1 | Semgrep and pip-audit output in `scan-results/` |
| trivy, gitleaks, codeql | 2 | `[ci.tools.*]` in `speed.toml`, reading Trivy, Gitleaks and SARIF output in `scan-results/` |

The scanner results are samples in each tool's real format, so nothing has to be installed.
Reports land in `.speed/ci/`: `report.json`, `speed-ci.sarif` (GitHub Security tab), `junit.xml` and `logs/`.

Try more:

* `speed ci --list`, `speed ci --only lint,test`, `speed --json ci`
* Report mode: set `security_mode = "report"` in `speed.toml` and change `MEDIUM` to `HIGH` in
  `scan-results/trivy.json`; Trivy then warns (`!`) instead of failing.
* A failure: change `3` to `4` in `tests/test_app.py`; `test` and `eval` fail.
  `git checkout .` puts it back.
* SonarQube: with a SonarQube server, add this to `speed.toml` and set `SONAR_TOKEN`:

  ```toml
  [ci.sonarqube]
  host_url = "http://localhost:9000"
  project_key = "speed-ci-demo"
  ```

  It needs `sonar-scanner` on `PATH` (or `scanner_cmd`) and runs with `sonar.sources=app.py`
  from `sonar-project.properties`.
