"""Helpers for speed ci: settings, tool output parsers, reports and the GitHub workflow.

Every subcommand is deterministic and makes no model call. Errors that mean the
check could not be judged exit 3 with a one-line message on stderr.

  config SPEED_TOML                    The [ci] settings as JSON
  gates AGENT_FILE                     Quality Gates names, in file order
  parse FORMAT RAW OUT                 Normalise trivy/gitleaks/snyk/sarif output
  sonar-wait HOST REPORT_TASK TIMEOUT  Wait for a SonarQube analysis and read its quality gate
  sarif CI_DIR OUT                     One SARIF file from every *-findings.json
  junit REPORT OUT                     JUnit XML with one test case per check
  summary REPORT                       Markdown summary for GitHub's job page
  merge OUT_DIR DIR...                 Combine the reports of parallel jobs
  workflow                             The GitHub Actions workflow (settings as JSON on stdin)
"""
from __future__ import annotations

import base64
import json
import math
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from xml.sax.saxutils import escape, quoteattr

sys.path.insert(0, str(Path(__file__).resolve().parent))

from quality_gates import read_gates  # noqa: E402
from toml import parse_toml  # noqa: E402


class Unjudgeable(Exception):
    """The input cannot be judged; speed ci reports it as a failed or unrunnable check."""


SEVERITIES = ("critical", "high", "medium", "low", "info")
BUILTIN_GATES = ("lint", "typecheck", "test", "e2e")
BUILTIN_STEPS = ("eval", "lint", "typecheck", "test", "e2e", "secrets", "sast", "sca")
TOOL_FORMATS = ("trivy", "gitleaks", "snyk", "sarif")
DEFAULT_TOOL_COMMANDS = {
    "trivy": "trivy fs --format json --quiet --scanners vuln,misconfig,secret .",
    "gitleaks": "gitleaks detect --no-banner --redact --report-format json --report-path /dev/stdout",
    "snyk": "snyk test --json",
}
SERVICES = {
    "postgres": {
        "image": "postgres:16",
        "env": {"POSTGRES_USER": "postgres", "POSTGRES_PASSWORD": "postgres", "POSTGRES_DB": "test"},
        "ports": ["5432:5432"],
        "health": "pg_isready -U postgres",
        "job_env": {"DATABASE_URL": "postgresql://postgres:postgres@localhost:5432/test",
                    "PGHOST": "localhost", "PGPORT": "5432", "PGUSER": "postgres",
                    "PGPASSWORD": "postgres", "PGDATABASE": "test"},
    },
    "mysql": {
        "image": "mysql:8.4",
        "env": {"MYSQL_ROOT_PASSWORD": "mysql", "MYSQL_DATABASE": "test"},
        "ports": ["3306:3306"],
        "health": "mysqladmin ping -h 127.0.0.1 -pmysql",
        "job_env": {"MYSQL_URL": "mysql://root:mysql@127.0.0.1:3306/test"},
    },
    "redis": {
        "image": "redis:7",
        "env": {},
        "ports": ["6379:6379"],
        "health": "redis-cli ping",
        "job_env": {"REDIS_URL": "redis://localhost:6379/0"},
    },
}
NAME = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
GATE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,39}$")
# GitHub upper-cases secret names and reserves GITHUB_; the others would break the job.
TOKEN_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
TOKEN_RESERVED_PREFIXES = ("GITHUB_", "RUNNER_", "ACTIONS_", "SPEED_")
TOKEN_RESERVED = {"PATH", "HOME", "CI", "SHELL", "USER", "PWD", "TMPDIR", "LANG"}
# Marks the throwaway database credentials in the generated workflow, which SPEED's
# secrets scan skips; a real secret on such a line would still be in a file under review.
TEST_CREDENTIAL_MARK = "speed-ci: test service credential"
GATE_LINE = re.compile(r"^(?P<bullet>[-*+]\s*)?(?P<name>[^:]+?):\s*\S")
# Names speed ci itself uses for checks, steps or artifacts.
RESERVED = set(BUILTIN_STEPS) | {"sonarqube", "clean-tree", "merge-jobs", "merge-commit", "report", "check"}
# Pinned installers for tools whose default command the workflow runs.
TOOL_INSTALL = {
    "trivy": ["curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/v0.56.2/contrib/install.sh"
              " | sudo sh -s -- -b /usr/local/bin v0.56.2"],
    "gitleaks": ["curl -sfL https://github.com/gitleaks/gitleaks/releases/download/v8.21.2/gitleaks_8.21.2_linux_x64.tar.gz"
                 " | sudo tar -xz -C /usr/local/bin gitleaks"],
    "snyk": ["npm install -g snyk@1.1308.3"],
}
SONAR_SCANNER = "6.2.1.4610"


def fail(message: str, code: int = 3) -> None:
    print(message, file=sys.stderr)
    sys.exit(code)


# ── Settings ───────────────────────────────────────────────────────────────────

def ci_config(toml_path: str) -> dict:
    """The [ci] section, validated, with defaults filled in."""
    data = parse_toml(toml_path) if toml_path and Path(toml_path).is_file() else {}
    ci = data.get("ci", {}) if isinstance(data, dict) else {}
    if not isinstance(ci, dict):
        raise Unjudgeable("[ci] must be a table")
    _known_keys("[ci]", ci, CI_KEYS)
    raw_mode = ci.get("security_mode", "strict")
    mode = str(raw_mode).lower()
    if mode not in ("strict", "report"):
        raise Unjudgeable(f"[ci] security_mode must be strict or report, not {raw_mode!r}")
    services = ci.get("services", [])
    services = [services] if isinstance(services, str) else services
    if not isinstance(services, list) or not all(isinstance(item, str) for item in services):
        raise Unjudgeable("[ci] services must be a list of names, for example [\"postgres\"]")
    services = list(dict.fromkeys(services))
    for service in services:
        if service not in SERVICES:
            raise Unjudgeable(f"[ci] services: unknown service {service} (known: {', '.join(SERVICES)})")
    parallel = str(ci.get("parallel", "false")).lower()
    if parallel not in ("true", "false"):
        raise Unjudgeable("[ci] parallel must be true or false")
    ignore = ci.get("ignore_gates", [])
    ignore = [ignore] if isinstance(ignore, str) else ignore
    if not isinstance(ignore, list) or not all(isinstance(item, str) and item.strip() for item in ignore):
        raise Unjudgeable("[ci] ignore_gates must be a list of Quality Gates names")
    for name in ignore:
        if name.strip().lower() in BUILTIN_GATES:
            raise Unjudgeable(f"[ci] ignore_gates cannot leave out '{name}', a built-in check; use --skip {name.lower()}")

    tools = {}
    raw_tools = ci.get("tools", {})
    if not isinstance(raw_tools, dict):
        raise Unjudgeable("[ci.tools] must hold one table per tool, for example [ci.tools.trivy]")
    for name, settings in raw_tools.items():
        if not NAME.match(name) or name in RESERVED:
            raise Unjudgeable(f"[ci.tools.{name}]: tool names are lowercase letters, digits, - and _, "
                              f"and cannot be one of {', '.join(sorted(RESERVED))}")
        if not isinstance(settings, dict):
            raise Unjudgeable(f"[ci.tools.{name}] must be a table")
        _known_keys(f"[ci.tools.{name}]", settings, ("format", "cmd", "token_env"))
        if any(not isinstance(value, str) for value in settings.values()):
            raise Unjudgeable(f"[ci.tools.{name}] settings must be strings")
        fmt = str(settings.get("format", name if name in TOOL_FORMATS else "")).lower()
        if fmt not in TOOL_FORMATS:
            raise Unjudgeable(f"[ci.tools.{name}] needs format = one of {', '.join(TOOL_FORMATS)}")
        cmd = str(settings.get("cmd", DEFAULT_TOOL_COMMANDS.get(name, ""))).strip()
        if not cmd:
            raise Unjudgeable(f"[ci.tools.{name}] needs cmd = the command that prints its {fmt} output")
        token = str(settings.get("token_env", "SNYK_TOKEN" if fmt == "snyk" else "")).strip()
        if token and (not TOKEN_NAME.match(token) or token in TOKEN_RESERVED
                      or token.startswith(TOKEN_RESERVED_PREFIXES)):
            raise Unjudgeable(f"[ci.tools.{name}] token_env must be an upper-case secret name such as SNYK_TOKEN, "
                              f"not {token!r} (GITHUB_, RUNNER_, ACTIONS_, SPEED_ and PATH, HOME, CI are reserved)")
        tools[name] = {"format": fmt, "cmd": cmd, "token_env": token,
                       "default_cmd": cmd == DEFAULT_TOOL_COMMANDS.get(name)}

    sonar = None
    raw_sonar = ci.get("sonarqube")
    if raw_sonar is not None:
        if not isinstance(raw_sonar, dict):
            raise Unjudgeable("[ci.sonarqube] must be a table")
        _known_keys("[ci.sonarqube]", raw_sonar, ("host_url", "project_key", "organization", "scanner_cmd", "blocking",
                                                  "wait_timeout", "report_task"))
        host = str(raw_sonar.get("host_url", "")).rstrip("/")
        parsed = urllib.parse.urlparse(host)
        if parsed.scheme not in ("https", "http") or not parsed.hostname or any(c.isspace() for c in host):
            raise Unjudgeable("[ci.sonarqube] needs host_url, for example https://sonarcloud.io")
        if parsed.query or parsed.fragment or parsed.username or parsed.password or ";" in host:
            raise Unjudgeable("[ci.sonarqube] host_url must be the server address only, with no query, fragment or login")
        # The token would travel in clear text over http, so only a local server may use it.
        if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise Unjudgeable("[ci.sonarqube] host_url must use https (http is allowed only for localhost)")
        key = str(raw_sonar.get("project_key", "")).strip()
        organization = str(raw_sonar.get("organization", "")).strip()
        if organization and not re.match(r"^[A-Za-z0-9_.-]+$", organization):
            raise Unjudgeable("[ci.sonarqube] organization may hold letters, digits, '.', '_' and '-'")
        if not key:
            raise Unjudgeable("[ci.sonarqube] needs project_key")
        blocking = str(raw_sonar.get("blocking", "true")).lower()
        if blocking not in ("true", "false"):
            raise Unjudgeable("[ci.sonarqube] blocking must be true or false")
        wait = str(raw_sonar.get("wait_timeout", "300"))
        if not wait.isdigit() or int(wait) < 1:
            raise Unjudgeable("[ci.sonarqube] wait_timeout must be a number of seconds")
        report_task = str(raw_sonar.get("report_task", ".scannerwork/report-task.txt")).strip()
        if not report_task or report_task.endswith("/") or report_task.startswith("/") \
                or ".." in Path(report_task).parts:
            raise Unjudgeable("[ci.sonarqube] report_task must be a path inside the project")
        if not re.match(r"^[A-Za-z0-9_.:-]+$", key):
            raise Unjudgeable("[ci.sonarqube] project_key may hold letters, digits, '.', '_', ':' and '-'")
        sonar = {"host_url": host, "project_key": key, "report_task": report_task,
                 "organization": organization,
                 "scanner_cmd": str(raw_sonar.get("scanner_cmd", "sonar-scanner")).strip() or "sonar-scanner",
                 "blocking": blocking == "true", "wait_timeout": int(wait)}

    codecov = None
    raw_codecov = ci.get("codecov")
    if raw_codecov is not None:
        if not isinstance(raw_codecov, dict):
            raise Unjudgeable("[ci.codecov] must be a table")
        _known_keys("[ci.codecov]", raw_codecov, ("files", "check"))
        check = str(raw_codecov.get("check", "test")).strip() or "test"
        if not GATE_NAME.match(check):
            raise Unjudgeable("[ci.codecov] check must be the name of a check")
        files = str(raw_codecov.get("files", "")).strip()
        if any(c in files for c in "\n\r\"$`"):
            raise Unjudgeable("[ci.codecov] files must be a plain path or comma-separated paths")
        codecov = {"files": files, "check": check}
    return {"security_mode": mode, "services": services, "parallel": parallel == "true",
            "ignore_gates": ignore, "tools": tools, "sonarqube": sonar, "codecov": codecov}


def _gate_like_names(agent: Path) -> list[str]:
    """Names of '- name: command' bullets in ## Quality Gates, including ones read_gates cannot parse."""
    names, in_section, fence = [], False, ""
    for raw in agent.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if fence:
            if line.startswith(fence) and set(line) == {fence[0]}:
                fence = ""
            continue
        opening = re.match(r"^(`{3,}|~{3,})", line)
        if opening:
            fence = opening[1]
            continue
        heading = re.match(r"^(#{1,6})(?:\s|$)", line)
        if not in_section:
            in_section = bool(re.match(r"^##\s+Quality\s+Gates\s*$", line, re.I))
            continue
        # Same boundary as read_gates: ### groups gates, any other heading ends the section.
        if heading and len(heading[1]) != 3:
            break
        if heading:
            continue
        match = GATE_LINE.match(line)
        if match and "://" not in match["name"]:
            raw_name = match["name"]
            if raw_name != raw_name.rstrip() and GATE_NAME.match(raw_name.strip()):
                # '- api : cmd' is not read as a gate; report the space rather than the name.
                names.append((raw_name.rstrip(), (match["bullet"] or "").strip()))
            else:
                names.append((raw_name.strip(), (match["bullet"] or "").strip()))
    return names


CI_KEYS = ("security_mode", "services", "parallel", "ignore_gates", "tools", "sonarqube", "codecov",
           "status_context", "command_timeout")


def _known_keys(section: str, table: dict, known) -> None:
    """A misspelled setting is refused, not silently ignored."""
    unknown = sorted(set(table) - set(known))
    if unknown:
        raise Unjudgeable(f"{section}: unknown setting(s) {', '.join(unknown)} (known: {', '.join(known)})")


def custom_gates(agent_file: str, ignore: list[str], tools: list[str]) -> dict:
    """Quality Gates names beyond lint, typecheck, test and e2e, in file order and as written,
    plus every name that cannot run as its own check, with the reason."""
    if not agent_file or not Path(agent_file).is_file():
        return {"gates": [], "problems": []}
    ignored = {name.lower() for name in ignore}
    taken = {name.lower() for name in tools}
    names, seen, problems = [], set(), []
    readable = {row["gate"] for row in read_gates(Path(agent_file))}
    for name, bullet in _gate_like_names(Path(agent_file)):
        plain = name.strip("`*_ ")
        if (name in readable and bullet in ("", "-")) or name.lower() in ignored or plain.lower() in ignored:
            continue
        if bullet in ("*", "+"):
            problems.append(f"'{name}' uses a '{bullet}' bullet; only '- {plain}: command' lines run")
        elif plain != name:
            problems.append(f"'{name}' must be written without backticks or bold, as '- {plain}: command'")
        elif GATE_NAME.match(name) or (len(name) > 40 and re.match(r"^[A-Za-z][A-Za-z0-9_-]*$", name)):
            problems.append(f"'{name}' is longer than 40 characters" if len(name) > 40
                            else f"'{name}' has a space before ':'; write '- {name}: command'")
        else:
            problems.append(f"'{name}' is not a valid check name (letters, digits, - and _, starting with a letter)")
    for row in read_gates(Path(agent_file)):
        name, key = row["gate"], row["gate"].lower()
        if key in ignored or name in names:
            continue
        if key in BUILTIN_GATES:
            if name != key:
                problems.append(f"'{name}' must be written '{key}'")
            continue
        if not GATE_NAME.match(name):
            problems.append(f"'{name}' is not a valid check name (letters, digits, - and _, starting with a letter)")
        elif key in RESERVED:
            problems.append(f"'{name}' is a name speed ci uses itself")
        elif key in taken:
            problems.append(f"'{name}' is also a [ci.tools.{key}] tool")
        elif key in seen:
            problems.append(f"'{name}' differs from another gate only by case")
        else:
            names.append(name)
            seen.add(key)
    return {"gates": names, "problems": problems}


# ── Tool output ────────────────────────────────────────────────────────────────

def severity(value) -> str:
    text = str(value or "").strip().lower()
    aliases = {"moderate": "medium", "error": "high", "warning": "medium", "note": "low", "none": "info",
               "negligible": "info"}
    text = aliases.get(text, text)
    return text if text in SEVERITIES else "unknown"


def _sarif_rule(result: dict, run: dict) -> dict:
    """The rule a SARIF result points at: by tool component and index, by index, or by id.
    CodeQL keeps its rules, with their security-severity, in tool.extensions."""
    tool = run.get("tool") or {}
    driver = tool.get("driver") or {}
    components = [driver] + [ext for ext in tool.get("extensions") or [] if isinstance(ext, dict)]
    reference = result.get("rule") if isinstance(result.get("rule"), dict) else {}
    index = reference.get("index", result.get("ruleIndex"))
    component = (reference.get("toolComponent") or {}).get("index")
    if isinstance(index, int):
        if isinstance(component, int) and not 0 <= component + 1 < len(components):
            return {"properties": {"security-severity": "unknown"}}
        source = components[component + 1] if isinstance(component, int) else driver
        rules = source.get("rules") or []
        if 0 <= index < len(rules) and isinstance(rules[index], dict):
            return rules[index]
    rule_id = result.get("ruleId") or reference.get("id")
    for source in components:
        for rule in source.get("rules") or []:
            if isinstance(rule, dict) and rule.get("id") == rule_id:
                return rule
    return {}


def _sarif_severity(result: dict, rule: dict) -> str:
    score = (result.get("properties") or {}).get("security-severity") or \
        (rule.get("properties") or {}).get("security-severity")
    if score is not None:
        try:
            score = float(score)
        except (TypeError, ValueError):
            return "unknown"
        if math.isnan(score) or math.isinf(score):
            return "unknown"
    if score is not None:
        return "critical" if score >= 9 else "high" if score >= 7 else "medium" if score >= 4 else "low"
    level = result.get("level") or ((rule.get("defaultConfiguration") or {}).get("level")) or "warning"
    return severity(level)


def _snyk_findings(project: dict) -> list[dict]:
    """A Snyk vulnerability appears once per dependency path; keep one per package version."""
    findings, seen = [], set()
    groups = [(project, project.get("displayTargetFile"))]
    for app in project.get("applications") or []:
        if isinstance(app, dict):
            target = app.get("displayTargetFile") or app.get("targetFile")
            # Container scans name files inside the image, which are not in the repository.
            groups.append((app, None if str(target or "").startswith("/") else target))
    for group, target in groups:
        for item in group.get("vulnerabilities") or []:
            key = (item.get("id"), item.get("packageName"), item.get("version"), target)
            if key in seen:
                continue
            seen.add(key)
            findings.append({"severity": severity(item.get("severity")), "rule": item.get("id"),
                             "title": f"{item.get('id', '')} {item.get('title', '')}".strip(),
                             "package": item.get("packageName"), "file": target})
    return findings


def parse_tool(fmt: str, data) -> list[dict]:
    """Normalised findings: severity, title, file, line, package. Never the matched secret text."""
    findings = []
    if fmt == "trivy":
        if not isinstance(data, dict) or ("Results" not in data and "SchemaVersion" not in data):
            raise Unjudgeable("not Trivy JSON (expected an object with Results)")
        for result in data.get("Results") or []:
            target = result.get("Target", "")
            for item in result.get("Vulnerabilities") or []:
                findings.append({"severity": severity(item.get("Severity")), "rule": item.get("VulnerabilityID"),
                                 "title": f"{item.get('VulnerabilityID', '')} {item.get('Title', '')}".strip(),
                                 "file": target, "package": item.get("PkgName")})
            for item in result.get("Misconfigurations") or []:
                findings.append({"severity": severity(item.get("Severity")), "rule": item.get("ID"),
                                 "title": f"{item.get('ID', '')} {item.get('Title', '')}".strip(), "file": target,
                                 "line": (item.get("CauseMetadata") or {}).get("StartLine")})
            for item in result.get("Secrets") or []:
                findings.append({"severity": severity(item.get("Severity")), "rule": item.get("RuleID"),
                                 "title": f"Secret: {item.get('Title') or item.get('RuleID', '')}",
                                 "file": target, "line": item.get("StartLine")})
    elif fmt == "gitleaks":
        if not isinstance(data, list):
            raise Unjudgeable("not Gitleaks JSON (expected an array of leaks)")
        for item in data:
            if not isinstance(item, dict):
                raise Unjudgeable("not Gitleaks JSON (expected an array of leaks)")
            findings.append({"severity": "high", "rule": item.get("RuleID"),
                             "title": f"Secret: {item.get('RuleID') or item.get('Description')}",
                             "file": item.get("File"), "line": item.get("StartLine")})
    elif fmt == "snyk":
        projects = data if isinstance(data, list) else [data]
        for project in projects:
            if not isinstance(project, dict):
                raise Unjudgeable("not Snyk JSON")
            if project.get("error") and not project.get("vulnerabilities") and not project.get("applications"):
                raise Unjudgeable(f"Snyk reported an error: {str(project.get('error'))[:200]}")
            if "vulnerabilities" not in project and "applications" not in project:
                raise Unjudgeable("not Snyk JSON (expected vulnerabilities)")
            findings += _snyk_findings(project)
    elif fmt == "sarif":
        if not isinstance(data, dict) or not isinstance(data.get("runs"), list):
            raise Unjudgeable("not SARIF (expected an object with runs)")
        for run in data["runs"]:
            if not isinstance(run, dict):
                raise Unjudgeable("not SARIF (a run is not an object)")
            for result in run.get("results") or []:
                if not isinstance(result, dict) or result.get("kind", "fail") in ("pass", "notApplicable", "informational"):
                    continue
                suppressions = result.get("suppressions") or []
                if suppressions and all(isinstance(item, dict) and item.get("status", "accepted") == "accepted"
                                        for item in suppressions):
                    continue
                rule = _sarif_rule(result, run)
                location = ((result.get("locations") or [{}])[0].get("physicalLocation") or {})
                findings.append({"severity": _sarif_severity(result, rule), "rule": result.get("ruleId") or rule.get("id"),
                                 "title": f"{result.get('ruleId', '')} {((result.get('message') or {}).get('text') or '')}"
                                          .strip()[:300],
                                 "file": (location.get("artifactLocation") or {}).get("uri"),
                                 "line": (location.get("region") or {}).get("startLine")})
    else:
        raise Unjudgeable(f"unknown format {fmt}")
    return [{key: value for key, value in item.items() if value not in (None, "")} for item in findings]


# ── SonarQube ──────────────────────────────────────────────────────────────────

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """The token must never follow a redirect to another host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise Unjudgeable(f"SonarQube redirected to {newurl}; set host_url to the final address")


class _Transient(Unjudgeable):
    """A failure worth retrying while polling: a 5xx or 429 answer, or no answer at all."""


_OPENER = urllib.request.build_opener(_NoRedirect)


def _sonar_get(host: str, path: str, params: dict, token: str, deadline: float | None = None) -> dict:
    url = f"{host}{path}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url)
    # A SonarQube token is sent as the user name with an empty password; this works on every version.
    request.add_header("Authorization", "Basic " + base64.b64encode(f"{token}:".encode()).decode())
    try:
        limit = 30 if deadline is None else max(1, min(30, deadline - time.monotonic()))
        with _OPENER.open(request, timeout=limit) as response:
            body = json.loads(response.read().decode())
            if not isinstance(body, dict):
                raise ValueError("not an object")
            return body
    except urllib.error.HTTPError as error:
        kind = _Transient if error.code >= 500 or error.code == 429 else Unjudgeable
        raise kind(f"SonarQube {path} answered HTTP {error.code}") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise _Transient(f"SonarQube {path} could not be reached: {error}") from error
    except ValueError as error:
        raise Unjudgeable(f"SonarQube {path} did not answer JSON") from error


def sonar_wait(host: str, report_task: str, timeout: int) -> dict:
    token = os.environ.get("SONAR_TOKEN", "")
    if not token:
        raise Unjudgeable("SONAR_TOKEN is not set")
    task = {}
    try:
        for line in Path(report_task).read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            task[key.strip()] = value.strip()
    except OSError as error:
        raise Unjudgeable(f"the scanner wrote no report-task.txt ({error})") from error
    task_id = task.get("ceTaskId")
    if not task_id:
        raise Unjudgeable("report-task.txt has no ceTaskId")
    deadline = time.monotonic() + timeout
    while True:
        try:
            status = _sonar_get(host, "/api/ce/task", {"id": task_id}, token, deadline).get("task") or {}
            if not isinstance(status, dict):
                raise Unjudgeable("SonarQube /api/ce/task answered an unexpected shape")
        except _Transient:
            if time.monotonic() >= deadline:
                raise
            time.sleep(2)
            continue
        if status.get("status") == "SUCCESS":
            break
        if status.get("status") in ("FAILED", "CANCELED"):
            raise Unjudgeable(f"the SonarQube analysis {status.get('status').lower()}")
        if time.monotonic() >= deadline:
            raise Unjudgeable(f"the SonarQube analysis did not finish within {timeout}s")
        time.sleep(2)
    if not status.get("analysisId"):
        raise Unjudgeable("the SonarQube analysis finished without an analysisId")
    while True:
        try:
            gate = _sonar_get(host, "/api/qualitygates/project_status", {"analysisId": status["analysisId"]},
                              token, deadline).get("projectStatus") or {}
            if not isinstance(gate, dict):
                raise Unjudgeable("SonarQube /api/qualitygates/project_status answered an unexpected shape")
            break
        except _Transient:
            if time.monotonic() >= deadline:
                raise
            time.sleep(2)
    failed = [{"metric": item.get("metricKey"), "actual": item.get("actualValue"),
               "comparator": item.get("comparator"), "threshold": item.get("errorThreshold")}
              for item in gate.get("conditions") or [] if item.get("status") == "ERROR"]
    return {"status": gate.get("status", "NONE"), "dashboard_url": task.get("dashboardUrl", ""),
            "failed_conditions": failed}


POSIX_CLASSES = {"[:upper:]": "A-Z", "[:lower:]": "a-z", "[:digit:]": "0-9", "[:alpha:]": "A-Za-z",
                 "[:alnum:]": "A-Za-z0-9", "[:space:]": "\\s", "[:xdigit:]": "0-9A-Fa-f",
                 "[:punct:]": "!-/:-@\\[-`{-~"}
NOT_KEPT = "This text was not kept: a [security] secrets_patterns entry could not be applied to it."


def _redaction_patterns(lines: list[str]) -> list[str]:
    """Regexes from 'name<TAB>regex' lines; '=literal<TAB>value' lines are exact secret values."""
    patterns = []
    for line in lines:
        name, _, value = line.partition("\t")
        if not value:
            continue
        if name == "=literal":
            if len(value) >= 4:
                patterns.append(re.escape(value))
            continue
        for posix, replacement in POSIX_CLASSES.items():
            value = value.replace(posix, replacement)
        patterns.append(value)
    return patterns


def redact_text(text: str, patterns: list[str]) -> str:
    for regex in patterns:
        try:
            text = re.sub(regex, "[redacted]", text)
        except re.error:
            return NOT_KEPT
    return text


def _redact_value(value, patterns: list[str]):
    if isinstance(value, str):
        return redact_text(value, patterns)
    if isinstance(value, list):
        return [_redact_value(item, patterns) for item in value]
    if isinstance(value, dict):
        return {key: _redact_value(item, patterns) for key, item in value.items()}
    return value


def redact(path: str, patterns: list[str]) -> None:
    """Replace every secret-pattern match in a file with [redacted]. JSON is redacted value by
    value, because some patterns include the quotes that delimit JSON strings."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    if path.endswith((".json", ".sarif")):
        try:
            data = json.loads(text)
        except ValueError:
            data = None
        if data is not None:
            cleaned = _redact_value(data, patterns)
            if cleaned != data:
                Path(path).write_text(json.dumps(cleaned, indent=2) + "\n", encoding="utf-8")
            return
    cleaned = redact_text(text, patterns)
    if cleaned != text:
        Path(path).write_text(cleaned + ("\n" if cleaned == NOT_KEPT else ""), encoding="utf-8")


def redact_tree(directory: str, patterns: list[str]) -> None:
    """Redact every text file speed ci wrote: reports, findings, SARIF, JUnit, logs and summaries."""
    for path in Path(directory).rglob("*"):
        if path.is_file() and not path.is_symlink() and path.stat().st_size < 20_000_000 and path.name != "pid":
            redact(str(path), patterns)


# ── Reports ────────────────────────────────────────────────────────────────────

SARIF_LEVEL = {"critical": "error", "high": "error", "unknown": "error", "medium": "warning", "low": "note",
               "info": "note"}
SARIF_SCORE = {"critical": "9.5", "high": "8.0", "unknown": "8.0", "medium": "5.5", "low": "2.0", "info": "0.0"}


MANIFESTS = ("package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml", "package.json",
             "poetry.lock", "Pipfile.lock", "uv.lock", "requirements.txt", "pyproject.toml", "go.sum", "go.mod",
             "Cargo.lock", "pom.xml", "build.gradle", "build.gradle.kts", "Gemfile.lock", "composer.lock", "Dockerfile")
# GitHub code scanning needs a location on every result; these are tried when nothing better is known.
FALLBACK_FILES = ("speed.toml", "AGENTS.md", "CLAUDE.md", "README.md")


def sarif(ci_dir: str) -> dict:
    """One SARIF run per check that has findings, for GitHub's Security tab."""
    runs = []
    root = Path(ci_dir).resolve().parent.parent
    manifest = next((name for name in MANIFESTS if (root / name).is_file()), "")
    fallback = next((name for name in FALLBACK_FILES if (root / name).is_file()), "README.md")
    for path in sorted(Path(ci_dir).glob("*-findings.json")):
        check = path.name[: -len("-findings.json")]
        try:
            findings = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(findings, list):
            continue
        rules, results = {}, []
        for item in findings:
            level = severity(item.get("severity", "high")) if "severity" in item else "high"
            title = item.get("title") or item.get("pattern") or check
            # Findings share a rule only when they share the tool's rule id and the severity,
            # since GitHub shows each alert with its rule's description and severity.
            rule_id = re.sub(r"[^A-Za-z0-9_.-]+", "-",
                             f"{check}/{item.get('rule') or item.get('pattern') or title}/{level}")[:160]
            rules.setdefault(rule_id, {"id": rule_id, "shortDescription": {"text": title[:200]},
                                       "properties": {"security-severity": SARIF_SCORE[level]}})
            text = str(item.get("message") or title)
            if item.get("message") and title not in text:
                text = f"{title}: {text}"
            if item.get("package") and str(item["package"]) not in text:
                text += f" in {item['package']}"
            result = {"ruleId": rule_id, "level": SARIF_LEVEL[level], "message": {"text": f"{text} ({level})"}}
            uri = item.get("file") or (manifest if item.get("package") else "") or manifest or fallback
            if uri:
                region = {"startLine": int(item["line"])} if item.get("file") and str(item.get("line", "")).isdigit() \
                    and int(item["line"]) > 0 else {}
                result["locations"] = [{"physicalLocation": {"artifactLocation": {"uri": urllib.parse.quote(uri, safe="/")},
                                                             **({"region": region} if region else {})}}]
            results.append(result)
        runs.append({"tool": {"driver": {"name": f"speed-ci/{check}", "rules": list(rules.values())}},
                     "automationDetails": {"id": f"speed-ci/{check}/"}, "results": results})
    return {"$schema": "https://json.schemastore.org/sarif-2.1.0.json", "version": "2.1.0", "runs": runs}


CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _one_line(text) -> str:
    """Text for a table cell or an XML attribute: no control characters, no line breaks."""
    return CONTROL.sub("", " ".join(str(text or "").split()))


def junit(report: dict) -> str:
    steps = report.get("steps", [])
    failures = sum(step.get("status") == "fail" for step in steps)
    skipped = sum(step.get("status") == "skipped" for step in steps)
    total_time = sum(step.get("duration_s", 0) for step in steps)
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             f'<testsuite name="speed ci" tests="{len(steps)}" failures="{failures}" skipped="{skipped}" '
             f'time="{total_time}">']
    for step in steps:
        head = f'  <testcase classname="speed-ci" name={quoteattr(step["name"])} time="{step.get("duration_s", 0)}"'
        summary = _one_line(step.get("summary", ""))
        if step.get("status") == "fail":
            lines += [head + ">", f"    <failure message={quoteattr(summary)}>{escape(summary)}</failure>", "  </testcase>"]
        elif step.get("status") == "skipped":
            lines += [head + ">", f"    <skipped message={quoteattr(summary)}/>", "  </testcase>"]
        else:
            output = f"    <system-out>{escape(summary)}</system-out>"
            lines += [head + ">", output, "  </testcase>"]
    lines.append("</testsuite>")
    return "\n".join(lines) + "\n"


def summary_markdown(report: dict) -> str:
    marks = {"pass": "✅", "fail": "❌", "warn": "⚠️", "skipped": "⏭️"}
    totals = report.get("summary", {})
    verdict = "Passed" if report.get("passed") else "Failed"
    lines = [f"## speed ci: {verdict}", "",
             f"{totals.get('pass', 0)} passed, {totals.get('fail', 0)} failed, {totals.get('warn', 0)} warning(s), "
             f"{totals.get('skipped', 0)} skipped. Commit `{report.get('commit', '')[:12]}`. No model calls.", "",
             "| Check | Result | Detail |", "|---|---|---|"]
    for step in report.get("steps", []):
        detail = _one_line(step.get("summary", "")).replace("|", "/")
        if step.get("dashboard_url"):
            detail += f" ([dashboard]({urllib.parse.quote(str(step['dashboard_url']), safe=':/?=&#%')}))"
        lines.append(f"| {step['name']} | {marks.get(step.get('status'), '')} {step.get('status')} | {detail} |")
    return "\n".join(lines) + "\n"


def totals(steps: list[dict]) -> dict:
    return {status: sum(step.get("status") == status for step in steps)
            for status in ("pass", "fail", "warn", "skipped")}


RANK = {"fail": 3, "warn": 2, "pass": 1, "skipped": 0}


def _read_report(directory: str):
    """A job's report, or None when it is missing or not a speed ci report."""
    try:
        report = json.loads((Path(directory) / "report.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    steps = report.get("steps") if isinstance(report, dict) else None
    if not isinstance(steps, list) or not all(
            isinstance(step, dict) and isinstance(step.get("name"), str) and step.get("status") in RANK
            for step in steps):
        return None
    return report


def merge(out_dir: str, dirs: list[str]) -> int:
    """Combine reports from parallel jobs. A check's result comes from the job that ran it;
    when more than one job reports it, the most severe result counts."""
    target = Path(out_dir).resolve()
    if any(Path(directory).resolve() == target for directory in dirs):
        raise Unjudgeable("a job directory cannot also be where the combined report is written")
    chosen, order, sarif_runs, commits, branches, started, finished = {}, [], [], set(), set(), [], []
    missing = []
    for directory in dirs:
        report = _read_report(directory)
        if report is None:
            missing.append(directory)
            continue
        commits.add(report.get("commit", ""))
        branches.add(report.get("branch", ""))
        started += [report["started_at"]] if report.get("started_at") else []
        finished += [report["finished_at"]] if report.get("finished_at") else []
        for step in report["steps"]:
            if step["name"] not in order:
                order.append(step["name"])
            if step.get("selected") is False:
                continue
            previous = chosen.get(step["name"])
            if previous is None or RANK[step["status"]] > RANK[previous["status"]]:
                chosen[step["name"]] = step
        try:
            sarif_runs += json.loads((Path(directory) / "speed-ci.sarif").read_text(encoding="utf-8")).get("runs", [])
        except (OSError, ValueError, AttributeError):
            pass
    steps = [chosen.get(name, {"name": name, "status": "fail", "summary": "No job reported this check",
                               "duration_s": 0}) for name in order]
    if missing:
        steps.append({"name": "merge-jobs", "status": "fail", "duration_s": 0,
                      "summary": f"{len(missing)} job(s) left no readable report: {', '.join(missing)}"})
    if len(commits) > 1:
        steps.append({"name": "merge-commit", "status": "fail", "duration_s": 0,
                      "summary": "The jobs checked different commits"})
    if not steps:
        steps.append({"name": "merge-jobs", "status": "fail", "duration_s": 0, "summary": "No job reported any check"})
    report = {"passed": not any(step["status"] == "fail" for step in steps),
              "commit": next(iter(commits)) if len(commits) == 1 else "",
              "branch": next(iter(branches)) if len(branches) == 1 else "",
              "started_at": min(started) if started else "", "finished_at": max(finished) if finished else "",
              "merged_from": len(dirs) - len(missing), "summary": totals(steps), "steps": steps}
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (out / "speed-ci.sarif").write_text(json.dumps({"$schema": "https://json.schemastore.org/sarif-2.1.0.json",
                                                    "version": "2.1.0", "runs": sarif_runs}, indent=2) + "\n")
    (out / "junit.xml").write_text(junit(report), encoding="utf-8")
    (out / "summary.md").write_text(summary_markdown(report), encoding="utf-8")
    return 0 if report["passed"] else 2


# ── GitHub Actions workflow ────────────────────────────────────────────────────

def _q(value: str) -> str:
    """A YAML double-quoted scalar."""
    return json.dumps(str(value))


def workflow(settings: dict) -> str:
    main, repo, ref = settings["main_branch"], settings["speed_repository"], settings["speed_ref"]
    for label, value in (("main branch", main), ("SPEED repository", repo), ("SPEED ref", ref)):
        if not re.match(r"^[A-Za-z0-9_./-]+$", str(value)):
            raise Unjudgeable(f"the {label} {value!r} cannot be written into a workflow")
    setup = settings.get("project_setup", "")
    config = settings["config"]
    checks = settings.get("checks", [])
    services = config.get("services", [])
    sonar, codecov = config.get("sonarqube"), config.get("codecov")
    # Secrets go only to the step that runs speed ci, and in parallel jobs only to the job
    # whose check needs them, never to dependency installs or unrelated checks.
    token_checks = {}
    for tool_name, tool in config.get("tools", {}).items():
        if tool.get("token_env"):
            token_checks.setdefault(tool["token_env"], []).append(tool_name)
    if sonar:
        token_checks.setdefault("SONAR_TOKEN", []).append("sonarqube")
    env = {}
    for service in services:
        env.update(SERVICES[service]["job_env"])
    secrets_unavailable = ("${{ github.event_name == 'pull_request' && "
                           "(github.event.pull_request.head.repo.fork || github.actor == 'dependabot[bot]') }}")

    def run_env(parallel: bool) -> list[str]:
        lines = ["        env:",
                 "          # Forks and Dependabot get no secrets; checks that need one are skipped there.",
                 f"          SPEED_CI_SECRETS_UNAVAILABLE: {_q(secrets_unavailable)}"]
        for name, needed_by in sorted(token_checks.items()):
            if parallel:
                condition = " || ".join(f"matrix.check == '{check}'" for check in needed_by)
                value = f"${{{{ ({condition}) && secrets.{name} || '' }}}}"
            else:
                value = f"${{{{ secrets.{name} }}}}"
            lines.append(f"          {name}: {_q(value)}")
        return lines

    installs = []
    for tool_name, tool in config.get("tools", {}).items():
        if tool.get("default_cmd") and tool_name in TOOL_INSTALL:
            installs.append((tool_name, TOOL_INSTALL[tool_name]))
    if sonar and sonar.get("scanner_cmd") == "sonar-scanner":
        installs.append(("sonarqube", [
            f"curl -sfLo \"$RUNNER_TEMP/sonar.zip\" https://binaries.sonarsource.com/Distribution/sonar-scanner-cli/"
            f"sonar-scanner-cli-{SONAR_SCANNER}-linux-x64.zip",
            "unzip -q \"$RUNNER_TEMP/sonar.zip\" -d \"$RUNNER_TEMP\"",
            f"echo \"$RUNNER_TEMP/sonar-scanner-{SONAR_SCANNER}-linux-x64/bin\" >> \"$GITHUB_PATH\""]))

    def job_env(indent: str) -> list[str]:
        if not env:
            return []
        return [f"{indent}env:"] + [f"{indent}  {key}: {_q(value)}  # {TEST_CREDENTIAL_MARK}, not a secret"
                                    for key, value in env.items()]

    def job_services(indent: str) -> list[str]:
        if not services:
            return []
        lines = [f"{indent}services:"]
        for name in services:
            spec = SERVICES[name]
            lines += [f"{indent}  {name}:", f"{indent}    image: {spec['image']}"]
            if spec["env"]:
                lines.append(f"{indent}    env:")
                lines += [f"{indent}      {key}: {_q(value)}  # {TEST_CREDENTIAL_MARK}" for key, value in spec["env"].items()]
            lines.append(f"{indent}    ports:")
            lines += [f"{indent}      - {_q(port)}" for port in spec["ports"]]
            lines.append(f"{indent}    options: >-")
            lines.append(f"{indent}      --health-cmd {_q(spec['health'])} --health-interval 5s "
                         f"--health-timeout 5s --health-retries 20")
        return lines

    install = [
        "      - name: Check out the project",
        "        uses: actions/checkout@v4",
        "        with:",
        "          # Keep tokens out of .git/config, where the project's own scripts could read them.",
        "          persist-credentials: false",
    ] + (["          # SonarQube needs the history to find new code and blame lines.",
          "          fetch-depth: 0"] if sonar else []) + [
        "",
        "      - name: Check out SPEED",
        "        uses: actions/checkout@v4",
        "        with:",
        f"          repository: {_q(repo)}",
        f"          ref: {_q(ref)}",
        "          path: .speed-tool",
        "          persist-credentials: false",
        "          # A private SPEED repository needs a token that can read it.",
        "          token: ${{ secrets.SPEED_REPO_TOKEN || github.token }}",
        "",
        "      - uses: actions/setup-python@v5",
        "        with:",
        "          python-version: '3.12'",
        "",
        "      - uses: actions/setup-node@v4",
        "        with:",
        "          node-version: '22'",
        "",
        "      - name: Install SPEED",
        "        run: |",
        "          # Move SPEED out of the project so the project's own tools never see it.",
        "          mv .speed-tool \"$RUNNER_TEMP/speed\"",
        "          sudo apt-get update -qq && sudo apt-get install -y -qq jq",
        "          python -m venv \"$RUNNER_TEMP/speed/.venv\"",
        "          \"$RUNNER_TEMP/speed/.venv/bin/pip\" install -q -r \"$RUNNER_TEMP/speed/requirements.txt\"",
        "          echo \"SPEED_PYTHON=$RUNNER_TEMP/speed/.venv/bin/python3\" >> \"$GITHUB_ENV\"",
        "          echo \"$RUNNER_TEMP/speed\" >> \"$GITHUB_PATH\"",
        "",
    ]
    for tool_name, commands in installs:
        step_if = f"        if: matrix.check == '{tool_name}'" if config.get("parallel") else None
        install += [f"      - name: Install {tool_name}"] + ([step_if] if step_if else []) + ["        run: |"]
        install += [f"          {command}" for command in commands] + [""]
    install += [
        "      # Project setup: these steps were detected from the repository.",
        "      # Review them and add anything else the project needs to build and test.",
    ] + ([line for line in setup.rstrip("\n").split("\n")] if setup else []) + [""]

    def codecov_step(condition: str) -> list[str]:
        if not codecov:
            return []
        lines = ["      - name: Upload coverage to Codecov", f"        if: {_q(condition)}",
                 "        uses: codecov/codecov-action@v4", "        with:",
                 "          token: ${{ secrets.CODECOV_TOKEN }}", "          fail_ci_if_error: false"]
        if codecov.get("files"):
            lines.append(f"          files: {_q(codecov['files'])}")
        return lines + [""]

    upload_sarif = [
        "      - name: Upload findings to the Security tab",
        "        if: always() && hashFiles('{path}') != ''",
        "        # Needs GitHub code scanning (public repositories, or Advanced Security on private ones).",
        "        continue-on-error: true",
        "        uses: github/codeql-action/upload-sarif@v3",
        "        with:",
        "          sarif_file: {path}",
        "          category: speed-ci",
        "",
    ]
    header = [
        "# Generated by `speed ci init`. Runs `speed ci` on every pull request and on",
        f"# every push to {main}. `speed ci` makes no model calls, so this workflow",
        "# needs no model credentials and costs nothing beyond runner time.",
        "# Rerun `speed ci init --force` after adding checks, tools or services to speed.toml.",
        "name: SPEED CI", "", "on:", "  pull_request:", "  push:", f"    branches: [{_q(main)}]", "",
        "permissions:", "  contents: read", "  actions: read", "  security-events: write", "",
        "concurrency:", "  group: speed-ci-${{ github.ref }}", "  cancel-in-progress: true", "", "jobs:",
    ]
    if not config.get("parallel"):
        lines = header + ["  speed-ci:", "    name: speed-ci", "    runs-on: ubuntu-latest", "    timeout-minutes: 60"]
        lines += job_services("    ") + job_env("    ") + ["    steps:"] + install
        lines += ["      - name: Run speed ci",
                  "        # The report goes outside the project so the checked tree stays clean."]
        lines += run_env(False) + ["        run: speed --json ci > \"$RUNNER_TEMP/speed-ci-report.json\"", ""]
        lines += codecov_step("always()")
        lines += [line.replace("{path}", ".speed/ci/speed-ci.sarif") for line in upload_sarif]
        lines += ["      - name: Upload the CI report", "        if: always()", "        uses: actions/upload-artifact@v4",
                  "        with:", "          name: speed-ci-report", "          path: |",
                  "            ${{ runner.temp }}/speed-ci-report.json", "            .speed/ci/",
                  "          include-hidden-files: true", "          if-no-files-found: warn"]
        return "\n".join(lines) + "\n"
    # With databases, the test, e2e and custom checks run in a job that has them; the rest
    # do not start containers they never use.
    db_checks = [check for check in checks
                 if services and (check in ("test", "e2e") or check not in BUILTIN_STEPS + tuple(config.get("tools", {}))
                                  and check != "sonarqube")]
    groups = [("check", [check for check in checks if check not in db_checks], False)]
    if db_checks:
        groups.append(("check-db", db_checks, True))
    lines = list(header)
    for job_name, job_checks, with_services in groups:
        if not job_checks:
            continue
        matrix = ", ".join(_q(check) for check in job_checks)
        lines += [f"  {job_name}:", "    name: ${{ matrix.check }}", "    runs-on: ubuntu-latest", "    timeout-minutes: 60",
                  "    strategy:", "      fail-fast: false", "      matrix:", f"        check: [{matrix}]"]
        lines += (job_services("    ") + job_env("    ") if with_services else []) + ["    steps:"] + install
        lines += ["      - name: Run ${{ matrix.check }}"] + run_env(True)
        lines += ["        run: speed --json ci --only \"${{ matrix.check }}\" > \"$RUNNER_TEMP/speed-ci-report.json\"", ""]
        if codecov:
            lines += codecov_step(f"always() && matrix.check == '{codecov['check']}'")
        lines += ["      - name: Upload this check's report", "        if: always()", "        uses: actions/upload-artifact@v4",
                  "        with:", "          name: speed-ci-check-${{ matrix.check }}", "          path: .speed/ci/",
                  "          include-hidden-files: true", "          if-no-files-found: warn", ""]
    needs = [job_name for job_name, job_checks, _ in groups if job_checks]
    lines += ["  speed-ci:", "    # The one status check to require: it passes only when every check passed.",
              "    name: speed-ci", f"    needs: [{', '.join(needs)}]",
              "    # Runs when checks failed, but not when a newer push cancelled this run.",
              "    if: ${{ !cancelled() }}", "    runs-on: ubuntu-latest", "    steps:",
              "      - name: Check out SPEED", "        uses: actions/checkout@v4", "        with:",
              f"          repository: {_q(repo)}", f"          ref: {_q(ref)}", "          path: .speed-tool",
              "          persist-credentials: false", "          token: ${{ secrets.SPEED_REPO_TOKEN || github.token }}",
              "", "      - name: Download the check reports", "        uses: actions/download-artifact@v4", "        with:",
              "          pattern: speed-ci-check-*", "          path: reports", "",
              "      - name: Combine the results",
              "        run: |",
              "          status=0",
              f"          python3 .speed-tool/lib/ci_tools.py merge merged {' '.join('reports/speed-ci-check-' + c for c in checks)}"
              " || status=$?",
              "          if [ -f merged/summary.md ]; then cat merged/summary.md >> \"$GITHUB_STEP_SUMMARY\"; fi",
              "          exit \"$status\"", ""]
    lines += [line.replace("{path}", "merged/speed-ci.sarif") for line in upload_sarif]
    lines += ["      - name: Upload the combined report", "        if: always()", "        uses: actions/upload-artifact@v4",
              "        with:", "          name: speed-ci-report", "          path: merged/", "          if-no-files-found: warn"]
    return "\n".join(lines) + "\n"


# ── Entry point ────────────────────────────────────────────────────────────────

def main(argv: list[str]) -> int:
    if not argv:
        fail(__doc__)
    command, args = argv[0], argv[1:]
    try:
        if command == "config":
            print(json.dumps(ci_config(args[0] if args else "")))
        elif command == "gates":
            ignore = json.loads(args[1]) if len(args) > 1 else []
            tools = json.loads(args[2]) if len(args) > 2 else []
            print(json.dumps(custom_gates(args[0], ignore, tools)))
        elif command == "parse":
            fmt, raw, out = args
            try:
                text = Path(raw).read_text(encoding="utf-8", errors="replace")
                decoder = json.JSONDecoder()
                data, end = decoder.raw_decode(text.lstrip())
            except ValueError as error:
                raise Unjudgeable("the tool did not print JSON") from error
            if text.lstrip()[end:].strip():
                raise Unjudgeable("the tool printed more than one JSON document")
            Path(out).write_text(json.dumps(parse_tool(fmt, data)), encoding="utf-8")
        elif command == "redact":
            redact(args[0], _redaction_patterns(sys.stdin.read().splitlines()))
        elif command == "redact-tree":
            redact_tree(args[0], _redaction_patterns(sys.stdin.read().splitlines()))
        elif command == "redact-text":
            # Patterns come from the file named in args[0]; the text from stdin.
            patterns = _redaction_patterns(Path(args[0]).read_text(encoding="utf-8").splitlines())
            sys.stdout.write(redact_text(sys.stdin.read(), patterns))
        elif command == "sonar-wait":
            print(json.dumps(sonar_wait(args[0], args[1], int(args[2]))))
        elif command == "sarif":
            Path(args[1]).write_text(json.dumps(sarif(args[0]), indent=2) + "\n", encoding="utf-8")
        elif command == "junit":
            Path(args[1]).write_text(junit(json.loads(Path(args[0]).read_text(encoding="utf-8"))), encoding="utf-8")
        elif command == "summary":
            print(summary_markdown(json.loads(Path(args[0]).read_text(encoding="utf-8"))), end="")
        elif command == "merge":
            return merge(args[0], args[1:])
        elif command == "workflow":
            print(workflow(json.load(sys.stdin)), end="")
        else:
            fail(f"unknown command: {command}")
    except Unjudgeable as error:
        fail(str(error))
    except (IndexError, ValueError, KeyError, TypeError, AttributeError) as error:
        fail(f"{command}: unexpected input ({type(error).__name__}: {str(error)[:200]})")
    except OSError as error:
        fail(f"{command}: {error}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
