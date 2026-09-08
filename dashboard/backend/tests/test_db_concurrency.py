"""Concurrency guarantees for the shared dashboard SQLite connection."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from dashboard.backend import db


def test_other_thread_cannot_commit_a_half_finished_transaction(tmp_path: Path) -> None:
    conn = db.connect(tmp_path)
    db.migrate(conn)
    conn.execute("CREATE TABLE transaction_probe (value TEXT NOT NULL)")
    conn.commit()
    inserted = threading.Event()
    commit_attempted = threading.Event()
    release_writer = threading.Event()
    commit_finished = threading.Event()

    def writer() -> None:
        try:
            with db.transaction(conn):
                conn.execute("INSERT INTO transaction_probe VALUES ('partial')")
                inserted.set()
                release_writer.wait(timeout=2)
                raise RuntimeError("force rollback")
        except RuntimeError:
            pass

    def unrelated_committer() -> None:
        inserted.wait(timeout=2)
        commit_attempted.set()
        conn.commit()
        commit_finished.set()

    writer_thread = threading.Thread(target=writer)
    commit_thread = threading.Thread(target=unrelated_committer)
    writer_thread.start()
    commit_thread.start()
    assert commit_attempted.wait(timeout=2)
    assert not commit_finished.wait(timeout=0.1)
    release_writer.set()
    writer_thread.join(timeout=2)
    commit_thread.join(timeout=2)

    observer = sqlite3.connect(db.db_path(tmp_path))
    try:
        assert observer.execute("SELECT COUNT(*) FROM transaction_probe").fetchone()[0] == 0
    finally:
        observer.close()
        conn.close()
