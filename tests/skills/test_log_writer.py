"""SyncLogWriter: append, rotation, and write failure (WB-SYNC-REPORT REQ-2)."""
import json

from skills.log_writer import SyncLogWriter


def _lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_append_writes_one_line_per_run(tmp_path):
    writer = SyncLogWriter(tmp_path / "deep" / "sync-log.jsonl")
    assert writer.append({"run_id": "a"})
    assert writer.append({"run_id": "b"})
    assert [e["run_id"] for e in _lines(writer.path)] == ["a", "b"]


def test_rotation_keeps_at_most_three_files(tmp_path):
    path = tmp_path / "sync-log.jsonl"
    writer = SyncLogWriter(path, max_bytes=10, keep=3)
    for n in range(6):
        assert writer.append({"run_id": f"r{n}"})

    files = sorted(p.name for p in tmp_path.iterdir())
    assert files == ["sync-log.jsonl", "sync-log.jsonl.1", "sync-log.jsonl.2"]
    # Every entry is larger than max_bytes, so each run lands in a fresh file
    # and the newest three survive in order.
    assert _lines(path)[0]["run_id"] == "r5"
    assert _lines(tmp_path / "sync-log.jsonl.1")[0]["run_id"] == "r4"
    assert _lines(tmp_path / "sync-log.jsonl.2")[0]["run_id"] == "r3"


def test_below_the_threshold_nothing_rotates(tmp_path):
    writer = SyncLogWriter(tmp_path / "sync-log.jsonl", max_bytes=10_000)
    for n in range(5):
        writer.append({"run_id": n})
    assert [p.name for p in tmp_path.iterdir()] == ["sync-log.jsonl"]


def test_unwritable_path_returns_false_instead_of_raising(tmp_path):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("file where a directory is needed\n")
    writer = SyncLogWriter(blocker / "sync-log.jsonl")
    assert writer.append({"run_id": "x"}) is False
    assert isinstance(writer.last_error, OSError)
