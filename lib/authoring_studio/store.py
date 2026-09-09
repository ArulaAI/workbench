"""Transactional local authority; document snapshots are append-only."""
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


def encoded(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.transaction() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS features(id TEXT PRIMARY KEY, state TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS deleted_features(id TEXT PRIMARY KEY, create_request_id TEXT UNIQUE NOT NULL);
                CREATE TABLE IF NOT EXISTS snapshots(
                    id TEXT PRIMARY KEY, feature_id TEXT NOT NULL, kind TEXT NOT NULL,
                    payload TEXT NOT NULL, sha256 TEXT NOT NULL);
                CREATE TRIGGER IF NOT EXISTS immutable_snapshot_update
                    BEFORE UPDATE ON snapshots BEGIN SELECT RAISE(ABORT, 'Immutable snapshot'); END;
                CREATE TRIGGER IF NOT EXISTS immutable_snapshot_delete_v2
                    BEFORE DELETE ON snapshots
                    WHEN EXISTS (SELECT 1 FROM features WHERE id=OLD.feature_id)
                    BEGIN SELECT RAISE(ABORT, 'Immutable snapshot'); END;
                DROP TRIGGER IF EXISTS immutable_snapshot_delete;
                CREATE TRIGGER IF NOT EXISTS delete_feature_snapshots
                    AFTER DELETE ON features BEGIN DELETE FROM snapshots WHERE feature_id=OLD.id; END;
            """)

    @contextmanager
    def transaction(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def read(conn, feature_id: str) -> dict | None:
        row = conn.execute("SELECT state FROM features WHERE id=?", (feature_id,)).fetchone()
        return json.loads(row[0]) if row else None

    @staticmethod
    def save(conn, state: dict):
        conn.execute("INSERT INTO features VALUES(?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state",
                     (state["id"], encoded(state)))

    @staticmethod
    def snapshot(conn, snapshot: dict):
        payload = encoded(snapshot)
        digest = hashlib.sha256(payload.encode()).hexdigest()
        conn.execute("INSERT INTO snapshots VALUES(?,?,?,?,?)",
                     (snapshot["id"], snapshot["feature_id"], snapshot["kind"], payload, digest))

    @staticmethod
    def load_snapshot(conn, version_id: str) -> dict | None:
        row = conn.execute("SELECT payload,sha256 FROM snapshots WHERE id=?", (version_id,)).fetchone()
        if not row:
            return None
        if hashlib.sha256(row[0].encode()).hexdigest() != row[1]:
            raise ValueError("Snapshot integrity check failed")
        return json.loads(row[0])
