from skills.sync import sync
from skills.events import read_events


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
