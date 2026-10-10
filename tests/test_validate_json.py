"""speed validate must read the validator's JSON even when it is wrapped in a code fence.

The validator agent often answers with ```json ... ```. validate used to pass that text
straight to jq and report "invalid JSON" for a valid verdict.
"""

import subprocess
from pathlib import Path

SPEED_DIR = Path(__file__).resolve().parent.parent
LIB = SPEED_DIR / "lib"
PROJECT_SH = LIB / "cmd" / "project.sh"

VERDICT = '{"status": "fail", "critical_gaps": [{"type": "inconsistency"}], "warnings": []}'


def _parse(raw: str) -> subprocess.CompletedProcess:
    # Load only parse_agent_json: provider.sh has top-level setup that needs a full SPEED run.
    return subprocess.run(
        ["bash", "-c", f"eval \"$(sed -n '/^parse_agent_json()/,/^}}/p' '{LIB}/provider.sh')\"; "
                       'parse_agent_json "$RAW" | jq -r ".status"'],
        capture_output=True, text=True, env={"RAW": raw, "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"},
    )


def test_fenced_verdict_is_parsed():
    r = _parse(f"```json\n{VERDICT}\n```\n")
    assert r.stdout.strip() == "fail", r.stderr


def test_plain_verdict_still_parsed():
    r = _parse(VERDICT)
    assert r.stdout.strip() == "fail", r.stderr


def test_validate_extracts_json_before_checking_it():
    source = PROJECT_SH.read_text()
    extract = source.index('parsed_validator=$(parse_agent_json "$validator_output"')
    check = source.index('_require_json "Validator" "$validator_output"')
    assert extract < check
