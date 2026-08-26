from skills.manifest import hash_bytes, classify_skill
from skills import CURRENT, STALE, CONFLICTED, ORPHANED, ABSENT


def _hashes(d):  # rendered dict -> hash map
    return {k: hash_bytes(v) for k, v in d.items()}


R = {"SKILL.md": b"v1", "references/n.md": b"ref"}


def test_absent():
    assert classify_skill(R, {}, None) == ABSENT


def test_current():
    entry = {"files": _hashes(R)}
    assert classify_skill(R, _hashes(R), entry) == CURRENT


def test_stale_when_catalog_changed_but_disk_unmodified():
    entry = {"files": _hashes(R)}
    r2 = {"SKILL.md": b"v2", "references/n.md": b"ref"}
    assert classify_skill(r2, _hashes(R), entry) == STALE


def test_conflicted_when_disk_edited():
    entry = {"files": _hashes(R)}
    disk = dict(_hashes(R))
    disk["SKILL.md"] = hash_bytes(b"user-edit")
    assert classify_skill(R, disk, entry) == CONFLICTED


def test_conflicted_when_unknown_preexisting_files():
    assert classify_skill(R, _hashes(R), None) == CONFLICTED


def test_orphaned_when_removed_and_unmodified():
    entry = {"files": _hashes(R)}
    assert classify_skill(None, _hashes(R), entry) == ORPHANED


def test_orphaned_edited_downgrades_to_conflicted():
    entry = {"files": _hashes(R)}
    disk = dict(_hashes(R))
    disk["SKILL.md"] = hash_bytes(b"user-edit")
    assert classify_skill(None, disk, entry) == CONFLICTED
