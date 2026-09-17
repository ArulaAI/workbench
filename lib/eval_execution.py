"""Execute configured evaluation commands and retain per-test evidence.

Pytest writes a fresh JUnit report. Other runners can write JUnit to
SPEED_EVAL_JUNIT_FILE or {"tests": [{"id": "...", "status": "pass"}]} to
SPEED_EVAL_RESULT_FILE. A zero process exit without test evidence is unverified.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

from lib.toml import parse_toml


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def valid_selector(selector: str) -> bool:
    # Quote even validated selectors. Brackets, spaces and punctuation in
    # parameter IDs are data, never shell syntax or runner options.
    return (isinstance(selector, str) and bool(selector.strip())
            and not selector.startswith("-")
            and not any(ord(c) < 32 or ord(c) == 127 for c in selector))


def selected_agent_file(root: Path, config: dict) -> Path | None:
    name = os.environ.get("SPEED_AGENT_FILE") or config.get("project", {}).get("agents_file")
    if name:
        if not isinstance(name, str) or Path(name).name != name:
            raise ValueError("The project agent file must be a filename")
        path = root / name
        return path if path.is_file() else None
    return next((root / name for name in ("AGENTS.md", "CLAUDE.md") if (root / name).is_file()), None)


def heading_level(line: str) -> int:
    """ATX heading level of a stripped line, or 0 when it is not a heading.

    "#hashtag" is prose; "###### x" and a bare "#" are headings.
    """
    match = re.match(r"^(#{1,6})(?:\s|$)", line)
    return len(match[1]) if match else 0


def load_config(root: Path) -> dict[str, Any]:
    data = parse_toml(str(root / "speed.toml")) if (root / "speed.toml").is_file() else {}
    evaluation = data.get("eval", {})
    if not isinstance(evaluation, dict):
        raise ValueError("[eval] must be a table")
    commands = []
    override = os.environ.get("SPEED_EVAL_TEST_COMMAND")
    if override:
        commands = [override]
    else:
        for key in ("test_command", "test_commands"):
            value = evaluation.get(key, [])
            values = value if isinstance(value, list) else [value]
            if any(not isinstance(c, str) or not c.strip() for c in values):
                raise ValueError(f"eval.{key} must contain nonempty command strings")
            commands.extend(values)
    agent = selected_agent_file(root, data)
    gates: list[dict[str, str]] = []
    if agent:
        # Gate commands reach bash -c, so only the section's own grammar counts
        # as configuration: the "## Quality Gates" heading, optional "### <sub>"
        # subsystem groups, and gate lines. A heading of any other level starts
        # a new section and ends the scan, and fenced blocks are documentation
        # everywhere in the file. Without both, an appendix or a shell example
        # showing "- lint: rm -rf /" would be read as a configured command.
        in_section = False
        subsystem = ""
        fence = ""
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
            level = heading_level(line)
            if not in_section:
                in_section = bool(re.match(r"^##\s+Quality\s+Gates\s*$", line, re.I))
                continue
            if level == 3:
                subsystem = line[3:].strip().lower()
                continue
            if level:
                break
            match = re.match(r"^(?:-\s*)?(test|lint):\s*(.+)$", line)
            if match:
                gates.append({"gate": match[1], "subsystem": subsystem,
                              "command": match[2].strip().strip("`")})
    return {"test_commands": commands, "gates": gates, "subsystems": data.get("subsystems", {}),
            "agent_file": str(agent) if agent else None}


def subsystem_for(task: dict, config: dict) -> str:
    import fnmatch
    files = task.get("files_touched", [])
    subsystems = config.get("subsystems") or {"frontend": ["src/frontend/*"],
                                             "backend": ["src/backend/*"], "plugin": ["src/plugins/*"]}
    matched = set()
    for name, patterns in subsystems.items():
        for pattern in patterns if isinstance(patterns, list) else [patterns]:
            if any(fnmatch.fnmatch(f, pattern) for f in files):
                matched.add(name.lower())
    return next(iter(matched)) if len(matched) == 1 else "both"


def configured_commands(config: dict, gate: str = "test", task: dict | None = None) -> list[str]:
    if gate == "test" and config.get("test_commands"):
        return config["test_commands"]
    subsystem = subsystem_for(task, config) if task else "both"
    return [row["command"] for row in config.get("gates", [])
            if row["gate"] == gate and (subsystem == "both" or not row["subsystem"]
                                         or subsystem == row["subsystem"])]


def resolve_command(config: dict, declared: str = "", task: dict | None = None) -> str:
    candidates = configured_commands(config, task=task)
    if declared and declared not in candidates:
        raise ValueError("Unconfigured test command")
    if not candidates:
        raise ValueError("No configured test command")
    return declared or candidates[0]


def aggregate_status(results: list[dict]) -> str:
    statuses = {r["status"] for r in results}
    for status in ("fail", "partial", "blocked_upstream", "unverifiable"):
        if status in statuses:
            return status
    return "pass" if results and statuses == {"pass"} else "unverifiable"


def render_command(base: str, selectors: list[str], report: Path | None = None,
                   *, append: bool = True) -> str:
    """Replace whole argument placeholders, never text embedded in shell code.

    A quoted placeholder is replaced together with its quotes. Inserting a
    shlex-quoted filename *inside* existing double quotes would still expand
    dollar expressions and command substitutions in that filename.

    The same tokenisation decides whether selectors may be appended when the
    command declares no placeholder. Concatenating them onto a compound command
    scopes whichever simple command happens to come last: in "pytest -q ; echo
    done" they reach echo, pytest runs the whole suite, and the selected test
    turns up in that full report as a pass it never earned. A trailing comment
    swallows them outright. Such a command must say where the selectors go.
    """
    # "cd <dir> && <runner>" is the documented shape for a gate in a subproject
    # (example/CLAUDE.md uses it) and run_command already reads that prefix to
    # pick the working directory. Selectors still reach the runner, so only what
    # follows the prefix decides whether appending is safe. A second operator
    # after it is not exempt: there the selectors would scope the wrong command.
    prefix = ""
    lead = re.match(r"\s*cd\s+(?:'[^']*'|\"[^\"]*\"|[^\s;&|()<>#]+)\s*&&\s*", base)
    if lead and not re.search(r"[;&|()<>]", base[lead.end():]):
        prefix, base = base[:lead.end()], base[lead.end():]

    quoted = " ".join(shlex.quote(s) for s in selectors)
    replacements = {"{selectors}": quoted, "{file}": quoted}
    if report is not None:
        replacements["{report}"] = shlex.quote(str(report))
    rendered, word, quote, escaped, used_selectors = [], "", "", False, False
    compound = False

    def flush():
        nonlocal word, used_selectors
        if any(key in word for key in replacements):
            raw = word
            if len(raw) >= 2 and raw[0] in "\"'" and raw[-1] == raw[0]:
                raw = raw[1:-1]
            if raw not in replacements:
                raise ValueError("Command placeholders must be complete shell arguments")
            rendered.append(replacements[raw])
            used_selectors |= raw in ("{file}", "{selectors}")
        else:
            rendered.append(word)
        word = ""

    for char in base:
        if escaped:
            word += char
            escaped = False
        elif char == "\\" and quote != "'":
            word += char
            escaped = True
        elif quote:
            word += char
            if char == quote:
                quote = ""
        elif char in "\"'":
            word += char
            quote = char
        elif char.isspace() or char in ";&|()<>":
            compound |= char in ";&|()<>"
            flush()
            rendered.append(char)
        else:
            # A "#" opening a word starts a shell comment that would swallow
            # anything appended after it.
            compound |= char == "#" and not word
            word += char
    flush()
    if quote or escaped:
        raise ValueError("Unclosed quoting in configured command")
    command = prefix + "".join(rendered)
    if not append or used_selectors:
        return command
    if compound:
        raise ValueError(
            "Test selectors cannot be appended to a command that combines shell "
            "operators or comments, because they would scope the wrong command and "
            "let an unscoped suite report a pass. Add an explicit {selectors} "
            f"placeholder where the runner should receive them: {command}")
    return command + " " + quoted


def _tests_from_report(json_path: Path, xml_path: Path) -> list[dict]:
    if json_path.exists():
        data = json.loads(json_path.read_text())
        if not isinstance(data, dict) or not isinstance(data.get("tests"), list):
            raise ValueError("Test evidence must contain a tests array")
        tests = data["tests"]
        allowed = {"pass", "fail", "skipped", "not_run", "blocked", "error", "xfail"}
        if any(not isinstance(t, dict) or not isinstance(t.get("id"), str) or not t["id"]
               or t.get("status") not in allowed for t in tests):
            raise ValueError("Invalid test evidence record")
        if len({t["id"] for t in tests}) != len(tests):
            raise ValueError("Duplicate test identities in evidence")
        return tests
    if xml_path.exists():
        root = ET.parse(xml_path).getroot()
        tests = []
        for i, case in enumerate(root.iter("testcase")):
            status = "pass"
            if case.find("failure") is not None or case.find("error") is not None:
                status = "fail"
            elif case.find("skipped") is not None:
                status = "skipped"
            tests.append({"id": f"{case.get('classname', '')}::{case.get('name', i)}", "status": status})
        return tests
    return []


def run_command(base: str, selectors: list[str], root: Path, evidence_dir: Path,
                *, gate: str = "test", timeout: int = 600) -> dict:
    if not selectors or any(not valid_selector(s) for s in selectors):
        return {"status": "fail", "command": "", "evidence": "Rejected empty or option-like selector", "tests": []}
    try:
        tokens = shlex.split(base)
    except ValueError as exc:
        return {"status": "fail", "command": base, "evidence": str(exc), "tests": []}
    cwd = root / tokens[1] if len(tokens) > 2 and tokens[0] == "cd" else root
    paths = [cwd, *(cwd / selector.split("::", 1)[0] for selector in selectors)]
    if any(not path.resolve().is_relative_to(root.resolve()) for path in paths):
        return {"status": "fail", "command": "", "evidence": "Selector leaves the project boundary", "tests": []}
    run_dir = evidence_dir / uuid.uuid4().hex
    json_path, xml_path = run_dir / "tests.json", run_dir / "junit.xml"
    try:
        command = render_command(base, selectors, json_path)
    except ValueError as exc:
        # A command that cannot carry the selectors is a configuration error, not
        # a verdict. Report it instead of running an unscoped suite.
        return {"status": "unverifiable", "command": base, "evidence": str(exc), "tests": []}
    evidence_dir.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir()
    env = os.environ.copy()
    env.update(SPEED_EVAL_RESULT_FILE=str(json_path), SPEED_EVAL_JUNIT_FILE=str(xml_path))
    is_pytest = bool(re.search(r"(?:^|[\s/])pytest(?:\s|$)", base))
    if is_pytest:
        env["PYTEST_ADDOPTS"] = (env.get("PYTEST_ADDOPTS", "") + " --junitxml="
                                 + shlex.quote(str(xml_path)))
    # Match the normal gate runner's project-local environment activation.
    prefix = ""
    if (cwd / ".venv/bin/activate").is_file():
        prefix = f"source {shlex.quote(str(cwd / '.venv/bin/activate'))} && "
    elif (cwd / "node_modules/.bin").is_dir():
        env["PATH"] = str(cwd / "node_modules/.bin") + os.pathsep + env.get("PATH", "")
    status, detail, tests = "unverifiable", "", []
    with (run_dir / "output.log").open("w") as log:
        process = subprocess.Popen(["bash", "-c", prefix + command], cwd=root, env=env,
                                   stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            code = process.wait(timeout=timeout)
        except BaseException:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            raise
    try:
        tests = _tests_from_report(json_path, xml_path)
        if code != 0 or any(t["status"] in ("fail", "error") for t in tests):
            status, detail = "fail", f"Runner exited {code}; test failures: {sum(t['status'] in ('fail', 'error') for t in tests)}"
        elif gate == "lint":
            status, detail = "pass", "Configured lint command passed"
        elif not tests:
            detail = "No discovered test evidence; a zero process exit does not verify a scenario"
        elif any(t["status"] != "pass" for t in tests):
            detail = "Required tests were skipped, blocked, or not run"
        else:
            status, detail = "pass", f"All {len(tests)} discovered tests executed and passed"
            if is_pytest:
                for selector in selectors:
                    path, *nodes = selector.split("::")
                    selected_path = Path(path)
                    if not nodes and selected_path.as_posix() in (".", ""):
                        continue
                    expected = ".".join([selected_path.stem, *nodes])
                    identities = [t["id"].replace("::", ".") for t in tests]
                    matches = [identity for identity in identities
                               if identity == expected or identity.endswith("." + expected)
                               or identity.startswith(expected + ".") or "." + expected + "." in identity
                               or ("[" not in expected and
                                   (identity.startswith(expected + "[") or "." + expected + "[" in identity))]
                    if not matches:
                        status, detail = "unverifiable", f"Selected test was not discovered: {selector}"
                        break
    except (ValueError, OSError, ET.ParseError) as exc:
        status = "fail" if code else "unverifiable"
        detail = f"Invalid test evidence: {exc}"
    result = {"status": status, "evidence": detail + f" (log: {run_dir / 'output.log'})",
              "command": command, "tests": tests, "executed_at": utc_now(), "exit_code": code,
              "artifact_dir": str(run_dir)}
    (run_dir / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    return result
