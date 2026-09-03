import os
import subprocess
import sys
from pathlib import Path

import pytest

from skills.sync import sync
from skills.events import read_events

LIB = Path(__file__).resolve().parents[2] / "lib"


def _sync(project, skills_dir, version="0.3.0", **kw):
    return sync(project, skills_dir, version, **kw)


def test_first_sync_logs_installed_under_one_transaction(tmp_catalog, tmp_project):
    skills_dir = tmp_catalog()
    _sync(tmp_project, skills_dir)
    events = read_events(tmp_project)
    assert len(events) == 1
    e = events[0]
    assert e["action"] == "installed"
    assert e["skill"] == "example-skill"
    assert e["surface"] == "claude_code"
    assert e["catalog_version"] == "0.3.0"
    assert e["transaction"]


def test_unchanged_sync_appends_no_events(tmp_catalog, tmp_project):
    skills_dir = tmp_catalog()
    _sync(tmp_project, skills_dir)
    n = len(read_events(tmp_project))
    _sync(tmp_project, skills_dir)  # no-op
    assert len(read_events(tmp_project)) == n  # nothing appended


def test_conflict_is_logged(tmp_catalog, tmp_project):
    skills_dir = tmp_catalog()
    _sync(tmp_project, skills_dir)
    edited = tmp_project / ".claude" / "skills" / "example-skill" / "SKILL.md"
    edited.write_text("HAND EDITED\n")
    _sync(tmp_project, skills_dir)  # no force
    actions = [e["action"] for e in read_events(tmp_project)]
    assert "conflict" in actions


def test_single_transaction_per_sync(tmp_catalog, tmp_project):
    skills_dir = tmp_catalog()
    tmp_catalog(name="second-skill")
    _sync(tmp_project, skills_dir)
    txns = {e["transaction"] for e in read_events(tmp_project)}
    assert len(txns) == 1  # both installs share one transaction id


EVENTS_REL = ".speed/skills/events.jsonl"


def _log(project):
    return project / EVENTS_REL


def _write_log(project, text):
    path = _log(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_a_truncated_final_line_is_tolerated(tmp_path):
    """The one corruption an interrupted append can produce is recoverable."""
    _write_log(
        tmp_path,
        '{"action": "installed", "skill": "a"}\n{"action": "upda',
    )

    events = read_events(tmp_path)

    assert [e["skill"] for e in events] == ["a"]


def test_a_corrupt_middle_line_is_reported_with_its_line_number(tmp_path):
    _write_log(
        tmp_path,
        '{"action": "installed"}\nnot json at all\n{"action": "updated"}\n',
    )

    with pytest.raises(ValueError, match="line 2"):
        read_events(tmp_path)


def test_a_complete_but_corrupt_last_line_is_not_silently_dropped(tmp_path):
    """A newline proves the write finished, so bad content there is real damage."""
    _write_log(tmp_path, '{"action": "installed"}\n{"action": ]\n')

    with pytest.raises(ValueError, match="line 2"):
        read_events(tmp_path)


def test_missing_log_reads_as_no_events(tmp_path):
    assert read_events(tmp_path) == []


def test_events_survive_an_ascii_locale(tmp_path, ascii_locale_python):
    result = ascii_locale_python(
        "from skills.events import append_events, read_events\n"
        f"root = {str(tmp_path)!r}\n"
        "append_events(root, [{'skill': 'skill-\\u00fc', 'action': 'installed'}])\n"
        "assert read_events(root)[0]['skill'].endswith('\\u00fc')\n"
        "print('ok')\n"
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_concurrent_appends_neither_interleave_nor_vanish(tmp_path):
    """Two Workbench processes can sync the same repo; the log must survive it."""
    writers, batches, per_batch = 4, 6, 3
    payload = "x" * 20000  # large enough that one batch spans several writes
    child = (
        "import sys\n"
        "from skills.events import append_events\n"
        "root, tag = sys.argv[1], sys.argv[2]\n"
        f"body = {payload!r}\n"
        f"for i in range({batches}):\n"
        "    append_events(root, [\n"
        "        {'writer': tag, 'n': i, 'k': k, 'body': body}\n"
        f"        for k in range({per_batch})\n"
        "    ])\n"
    )
    env = dict(os.environ, PYTHONPATH=str(LIB))
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", child, str(tmp_path), str(w)], env=env
        )
        for w in range(writers)
    ]
    assert [p.wait(timeout=60) for p in procs] == [0] * writers

    events = read_events(tmp_path)

    assert len(events) == writers * batches * per_batch
    assert {e["writer"] for e in events} == {str(w) for w in range(writers)}


def _versioned_catalog(skills_dir, version):
    (skills_dir / "example-skill" / "SKILL.md").write_text(
        "---\n"
        "name: example-skill\n"
        "description: A test skill\n"
        f"version: {version}\n"
        "---\n\n"
        f"# example-skill\nBody for {version}.\n",
        encoding="utf-8",
    )


def test_a_conflict_event_does_not_claim_a_version_was_installed(
    tmp_catalog, tmp_project
):
    """Nothing was written, so recording the catalog's version would be a lie."""
    skills_dir = tmp_catalog()
    _versioned_catalog(skills_dir, "1.0.0")
    _sync(tmp_project, skills_dir)
    edited = tmp_project / ".claude" / "skills" / "example-skill" / "SKILL.md"
    edited.write_text("HAND EDITED\n", encoding="utf-8")
    _versioned_catalog(skills_dir, "2.0.0")

    _sync(tmp_project, skills_dir)

    conflict = [e for e in read_events(tmp_project) if e["action"] == "conflict"][0]
    assert conflict["prev_version"] == "1.0.0"
    assert conflict["new_version"] is None


def test_an_update_event_still_records_both_versions(tmp_catalog, tmp_project):
    skills_dir = tmp_catalog()
    _versioned_catalog(skills_dir, "1.0.0")
    _sync(tmp_project, skills_dir)
    _versioned_catalog(skills_dir, "2.0.0")

    _sync(tmp_project, skills_dir)

    updated = [e for e in read_events(tmp_project) if e["action"] == "updated"][0]
    assert (updated["prev_version"], updated["new_version"]) == ("1.0.0", "2.0.0")
