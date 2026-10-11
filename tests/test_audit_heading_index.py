"""The audit numbers H2 headings for the agent, exactly as the phase split counts them.

The audit agent was asked to count H2 headings 0-based and counted from 1: it named
heading 15 in a spec with 15 headings, the split failed and `speed plan --feature`
stopped. The audit message now carries the numbered list.
"""

import re
import subprocess
import sys
from pathlib import Path

SPEED_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SPEED_DIR))

from lib.context.spec_split import _extract_h2  # noqa: E402

SPEC = """# RFC

## Basic Example
text
### Sub
## Data Model
## Unresolved Questions
"""


def _index(spec: str) -> list[tuple[int, str]]:
    source = (SPEED_DIR / "lib" / "cmd" / "audit.sh").read_text()
    pipeline = re.search(r"h2_index=\$\((printf .*?)\)\n", source).group(1)
    out = subprocess.run(["bash", "-c", pipeline.replace('"$spec_content"', '"$SPEC"')],
                         capture_output=True, text=True, env={"SPEC": spec, "PATH": "/usr/bin:/bin"}).stdout
    return [(int(n), h) for n, h in (line.split("  ", 1) for line in out.splitlines())]


def test_heading_index_is_zero_based_and_matches_the_split():
    assert _index(SPEC) == list(enumerate(_extract_h2(SPEC)))
    assert _index(SPEC)[0] == (0, "Basic Example")


def test_audit_message_tells_the_agent_not_to_count():
    source = (SPEED_DIR / "lib" / "cmd" / "audit.sh").read_text()
    assert "## H2 Heading Index" in source and "Do not count headings yourself" in source


def test_split_failure_names_a_real_option():
    source = (SPEED_DIR / "lib" / "cmd" / "plan.sh").read_text()
    assert "--skip-split" not in source
    assert "--single-pass" in source[source.index("Audit recommended phased planning but spec split failed"):][:400]
