"""SQLite database layer for the SPEED dashboard.

Single DB per target project at {PROJECT_ROOT}/.speed/dashboard.db.
WAL mode for concurrent reads during live ingestion.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from contextlib import contextmanager
from typing import Generator

SCHEMA_VERSION = 2

DDL = """
CREATE TABLE IF NOT EXISTS project (
    id              TEXT PRIMARY KEY DEFAULT 'default',
    name            TEXT NOT NULL,
    root_path       TEXT NOT NULL,
    git_remote      TEXT,
    git_head        TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%%H:%%M:%%SZ','now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%%H:%%M:%%SZ','now'))
);

CREATE TABLE IF NOT EXISTS features (
    name        TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL DEFAULT 'default',
    status      TEXT NOT NULL DEFAULT 'idle',
    started_at  TEXT,
    spec_path   TEXT,
    FOREIGN KEY (project_id) REFERENCES project(id)
);

CREATE TABLE IF NOT EXISTS agent_runs (
    id                TEXT PRIMARY KEY,
    feature           TEXT NOT NULL,
    session_id        TEXT NOT NULL,
    agent_type        TEXT NOT NULL,
    task_id           TEXT,
    subtype           TEXT,
    is_error          INTEGER DEFAULT 0,
    duration_ms       INTEGER,
    duration_api_ms   INTEGER,
    num_turns         INTEGER,
    total_cost_usd    REAL,
    input_tokens      INTEGER DEFAULT 0,
    output_tokens     INTEGER DEFAULT 0,
    cache_creation_tokens  INTEGER DEFAULT 0,
    cache_read_tokens      INTEGER DEFAULT 0,
    source_file       TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    FOREIGN KEY (feature) REFERENCES features(name)
);

CREATE TABLE IF NOT EXISTS model_usage (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_run_id          TEXT NOT NULL,
    model                 TEXT NOT NULL,
    input_tokens          INTEGER DEFAULT 0,
    output_tokens         INTEGER DEFAULT 0,
    cache_read_tokens     INTEGER DEFAULT 0,
    cache_creation_tokens INTEGER DEFAULT 0,
    cost_usd              REAL DEFAULT 0.0,
    context_window        INTEGER,
    max_output_tokens     INTEGER,
    FOREIGN KEY (agent_run_id) REFERENCES agent_runs(id)
);

CREATE TABLE IF NOT EXISTS agent_turns (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_run_id          TEXT,
    feature               TEXT NOT NULL,
    session_id            TEXT NOT NULL,
    source_file           TEXT NOT NULL,
    turn_index            INTEGER NOT NULL,
    model                 TEXT,
    input_tokens          INTEGER DEFAULT 0,
    output_tokens         INTEGER DEFAULT 0,
    cache_read_tokens     INTEGER DEFAULT 0,
    cache_creation_tokens INTEGER DEFAULT 0,
    has_tool_use          INTEGER DEFAULT 0,
    has_thinking          INTEGER DEFAULT 0,
    created_at            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ingested_files (
    path          TEXT PRIMARY KEY,
    mtime         REAL NOT NULL,
    size          INTEGER NOT NULL,
    ingested_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%%H:%%M:%%SZ','now'))
);

CREATE TABLE IF NOT EXISTS spec_index (
    path            TEXT PRIMARY KEY,
    spec_type       TEXT NOT NULL,
    feature         TEXT,
    lifecycle_state TEXT NOT NULL DEFAULT 'draft',
    content_hash    TEXT NOT NULL,
    section_count   INTEGER NOT NULL DEFAULT 0,
    completeness    REAL,
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%%H:%%M:%%SZ','now'))
);

CREATE TABLE IF NOT EXISTS feature_specs (
    feature         TEXT NOT NULL,
    spec_path       TEXT NOT NULL,
    spec_type       TEXT NOT NULL,
    PRIMARY KEY (feature, spec_path),
    FOREIGN KEY (feature) REFERENCES features(name),
    FOREIGN KEY (spec_path) REFERENCES spec_index(path)
);

CREATE TABLE IF NOT EXISTS spec_edges (
    source_spec     TEXT NOT NULL,
    target_spec     TEXT NOT NULL,
    rel_type        TEXT NOT NULL,
    evidence        TEXT,
    PRIMARY KEY (source_spec, target_spec, rel_type),
    FOREIGN KEY (source_spec) REFERENCES spec_index(path),
    FOREIGN KEY (target_spec) REFERENCES spec_index(path)
);

CREATE TABLE IF NOT EXISTS spec_sections (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    spec_path       TEXT NOT NULL,
    heading         TEXT NOT NULL,
    heading_level   INTEGER NOT NULL,
    tier            TEXT NOT NULL,
    ordinal         INTEGER NOT NULL,
    line_start      INTEGER NOT NULL,
    line_end        INTEGER NOT NULL,
    content_hash    TEXT NOT NULL,
    completeness    REAL,
    FOREIGN KEY (spec_path) REFERENCES spec_index(path)
);
"""

INDEXES = """
CREATE INDEX IF NOT EXISTS idx_agent_runs_feature    ON agent_runs(feature);
CREATE INDEX IF NOT EXISTS idx_agent_runs_agent_type ON agent_runs(agent_type);
CREATE INDEX IF NOT EXISTS idx_agent_runs_created_at ON agent_runs(created_at);
CREATE INDEX IF NOT EXISTS idx_model_usage_run_id    ON model_usage(agent_run_id);
CREATE INDEX IF NOT EXISTS idx_model_usage_model     ON model_usage(model);
CREATE INDEX IF NOT EXISTS idx_agent_turns_run_id    ON agent_turns(agent_run_id);
CREATE INDEX IF NOT EXISTS idx_agent_turns_feature   ON agent_turns(feature);
CREATE INDEX IF NOT EXISTS idx_spec_index_type       ON spec_index(spec_type);
CREATE INDEX IF NOT EXISTS idx_spec_index_feature    ON spec_index(feature);
CREATE INDEX IF NOT EXISTS idx_feature_specs_feature  ON feature_specs(feature);
CREATE INDEX IF NOT EXISTS idx_feature_specs_path     ON feature_specs(spec_path);
CREATE INDEX IF NOT EXISTS idx_spec_edges_source      ON spec_edges(source_spec);
CREATE INDEX IF NOT EXISTS idx_spec_edges_target      ON spec_edges(target_spec);
CREATE INDEX IF NOT EXISTS idx_spec_sections_path     ON spec_sections(spec_path);
"""


def db_path(project_root: str | Path) -> Path:
    """Return the path to the dashboard SQLite DB for a target project."""
    from .paths import get_paths
    return get_paths(project_root).db_path


def connect(project_root: str | Path) -> sqlite3.Connection:
    """Open a connection to the dashboard DB with recommended pragmas."""
    path = db_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    """Run schema DDL and create indexes. Idempotent."""
    conn.executescript(DDL)
    conn.executescript(INDEXES)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)"
    )
    row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,)
        )
    elif row["version"] < SCHEMA_VERSION:
        conn.execute(
            "UPDATE schema_version SET version = ?", (SCHEMA_VERSION,)
        )
    conn.commit()


@contextmanager
def transaction(conn: sqlite3.Connection) -> Generator[sqlite3.Connection, None, None]:
    """Context manager for explicit transactions with rollback on error."""
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
