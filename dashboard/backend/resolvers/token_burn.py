"""Token burn resolvers — SQL queries against agent_runs and model_usage tables."""

from __future__ import annotations

import sqlite3
from typing import Any


def get_agent_runs(
    conn: sqlite3.Connection,
    feature: str | None = None,
    agent_type: str | None = None,
    model: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Fetch agent run summaries with optional filters."""
    clauses: list[str] = []
    params: list[Any] = []

    if feature:
        clauses.append("ar.feature = ?")
        params.append(feature)
    if agent_type:
        clauses.append("ar.agent_type = ?")
        params.append(agent_type)
    if model:
        clauses.append("EXISTS (SELECT 1 FROM model_usage mu WHERE mu.agent_run_id = ar.id AND mu.model = ?)")
        params.append(model)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.extend([limit, offset])

    rows = conn.execute(
        f"""SELECT ar.*, GROUP_CONCAT(DISTINCT mu.model) as models
            FROM agent_runs ar
            LEFT JOIN model_usage mu ON mu.agent_run_id = ar.id
            {where}
            GROUP BY ar.id
            ORDER BY ar.created_at DESC
            LIMIT ? OFFSET ?""",
        params,
    ).fetchall()

    return [dict(r) for r in rows]


def get_model_usage_for_run(
    conn: sqlite3.Connection, run_id: str
) -> list[dict[str, Any]]:
    """Fetch per-model usage breakdown for a single agent run."""
    rows = conn.execute(
        "SELECT * FROM model_usage WHERE agent_run_id = ? ORDER BY model",
        (run_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def aggregate_token_burn(
    conn: sqlite3.Connection,
    group_by: str,
    feature: str | None = None,
) -> list[dict[str, Any]]:
    """Aggregate cost/tokens grouped by feature, agent_type, model, hour, or day.

    group_by: 'feature' | 'agent_type' | 'model' | 'hour' | 'day'
    """
    valid_groups = {
        "feature": "ar.feature",
        "agent_type": "ar.agent_type",
        "model": "mu.model",
        "hour": "strftime('%Y-%m-%dT%H:00:00Z', ar.created_at)",
        "day": "strftime('%Y-%m-%d', ar.created_at)",
    }

    group_col = valid_groups.get(group_by)
    if not group_col:
        raise ValueError(f"Invalid group_by: {group_by}")

    join = ""
    if group_by == "model":
        join = "JOIN model_usage mu ON mu.agent_run_id = ar.id"

    filter_clause = ""
    params: list[Any] = []
    if feature:
        filter_clause = "WHERE ar.feature = ?"
        params.append(feature)

    if group_by == "model":
        query = f"""
            SELECT {group_col} as group_key,
                   COUNT(DISTINCT ar.id) as run_count,
                   SUM(mu.cost_usd) as total_cost_usd,
                   SUM(mu.input_tokens) as total_input_tokens,
                   SUM(mu.output_tokens) as total_output_tokens,
                   SUM(mu.cache_read_tokens) as total_cache_read_tokens,
                   SUM(mu.cache_creation_tokens) as total_cache_creation_tokens
            FROM agent_runs ar {join}
            {filter_clause}
            GROUP BY {group_col}
            ORDER BY total_cost_usd DESC
        """
    else:
        query = f"""
            SELECT {group_col} as group_key,
                   COUNT(*) as run_count,
                   SUM(ar.total_cost_usd) as total_cost_usd,
                   SUM(ar.input_tokens) as total_input_tokens,
                   SUM(ar.output_tokens) as total_output_tokens,
                   SUM(ar.cache_read_tokens) as total_cache_read_tokens,
                   SUM(ar.cache_creation_tokens) as total_cache_creation_tokens
            FROM agent_runs ar {join}
            {filter_clause}
            GROUP BY {group_col}
            ORDER BY total_cost_usd DESC
        """

    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def token_burn_time_series(
    conn: sqlite3.Connection,
    feature: str | None = None,
    bucket_minutes: int = 60,
) -> list[dict[str, Any]]:
    """Windowed cumulative cost over time."""
    filter_clause = ""
    params: list[Any] = []
    if feature:
        filter_clause = "WHERE ar.feature = ?"
        params.append(feature)

    # SQLite doesn't have native time bucketing, use strftime rounding
    query = f"""
        SELECT
            strftime('%Y-%m-%dT%H:', ar.created_at) ||
            printf('%02d', (CAST(strftime('%M', ar.created_at) AS INTEGER) / {bucket_minutes}) * {bucket_minutes}) ||
            ':00Z' as bucket,
            SUM(ar.total_cost_usd) as cost_usd,
            COUNT(*) as run_count,
            SUM(ar.input_tokens + ar.output_tokens) as total_tokens
        FROM agent_runs ar
        {filter_clause}
        GROUP BY bucket
        ORDER BY bucket
    """
    rows = conn.execute(query, params).fetchall()

    # Compute cumulative totals
    results = []
    cumulative = 0.0
    for r in rows:
        d = dict(r)
        cumulative += d.get("cost_usd", 0) or 0
        d["cumulative_cost_usd"] = cumulative
        results.append(d)

    return results
