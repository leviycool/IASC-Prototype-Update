"""
Persistent token usage storage.

Logs every API call to a local SQLite database so usage can be queried
across sessions. The DB file lives alongside the donor database in data/.

This is a lightweight append-only log; it does not store conversation content,
only token counts, timestamps, model names, and cost estimates.
"""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).parent.parent / "data" / "usage.db"


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS api_calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            model TEXT NOT NULL,
            input_tokens INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL,
            cache_creation_input_tokens INTEGER DEFAULT 0,
            cache_read_input_tokens INTEGER DEFAULT 0,
            had_tool_use INTEGER DEFAULT 0,
            latency_ms REAL DEFAULT 0,
            question TEXT,
            session_id TEXT
        )
    """)
    conn.commit()
    return conn


def log_api_call(
    timestamp: datetime,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
    had_tool_use: bool = False,
    latency_ms: float = 0,
    question: Optional[str] = None,
    session_id: Optional[str] = None,
) -> None:
    """Append one API call record to the persistent log."""
    conn = _get_connection()
    conn.execute(
        """
        INSERT INTO api_calls
            (timestamp, model, input_tokens, output_tokens,
             cache_creation_input_tokens, cache_read_input_tokens,
             had_tool_use, latency_ms, question, session_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            timestamp.isoformat(),
            model,
            input_tokens,
            output_tokens,
            cache_creation_input_tokens,
            cache_read_input_tokens,
            1 if had_tool_use else 0,
            latency_ms,
            question,
            session_id,
        ),
    )
    conn.commit()
    conn.close()


def get_usage_summary(
    since: Optional[str] = None,
    model: Optional[str] = None,
) -> dict:
    """Query cumulative usage statistics.

    Args:
        since: ISO date string (YYYY-MM-DD). If provided, only count calls after this date.
        model: Filter to a specific model name.

    Returns a dict with aggregate stats suitable for returning as a tool result.
    """
    conn = _get_connection()

    conditions = []
    params = []

    if since:
        conditions.append("timestamp >= ?")
        params.append(since)

    if model:
        conditions.append("model = ?")
        params.append(model)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    row = conn.execute(
        f"""
        SELECT
            COUNT(*) as total_api_calls,
            COUNT(DISTINCT session_id) as total_sessions,
            COUNT(DISTINCT question) as unique_questions,
            COALESCE(SUM(input_tokens), 0) as total_input_tokens,
            COALESCE(SUM(output_tokens), 0) as total_output_tokens,
            COALESCE(SUM(cache_read_input_tokens), 0) as total_cache_read_tokens,
            COALESCE(SUM(cache_creation_input_tokens), 0) as total_cache_write_tokens,
            MIN(timestamp) as first_call,
            MAX(timestamp) as last_call
        FROM api_calls
        {where}
        """,
        params,
    ).fetchone()

    result = dict(row)

    # Add per-model breakdown
    model_rows = conn.execute(
        f"""
        SELECT
            model,
            COUNT(*) as api_calls,
            SUM(input_tokens) as input_tokens,
            SUM(output_tokens) as output_tokens,
            SUM(cache_read_input_tokens) as cache_read_tokens
        FROM api_calls
        {where}
        GROUP BY model
        ORDER BY api_calls DESC
        """,
        params,
    ).fetchall()

    result["by_model"] = [dict(r) for r in model_rows]

    # Estimate cost (using the pricing from token_tracker)
    from token_tracker import MODEL_PRICING

    total_cost = 0.0
    for mr in result["by_model"]:
        pricing = MODEL_PRICING.get(mr["model"])
        if not pricing:
            continue
        base_rate = pricing["input_per_mtok"]
        output_rate = pricing["output_per_mtok"]

        cache_read = mr.get("cache_read_tokens", 0) or 0
        cache_write = mr.get("cache_creation_input_tokens", 0) or 0
        regular_input = (mr.get("input_tokens", 0) or 0) - cache_read - cache_write
        total_cost += (regular_input / 1_000_000) * base_rate
        total_cost += (cache_write / 1_000_000) * base_rate * 1.25
        total_cost += (cache_read / 1_000_000) * base_rate * 0.1
        total_cost += ((mr.get("output_tokens", 0) or 0) / 1_000_000) * output_rate

    result["estimated_total_cost_usd"] = round(total_cost, 4)
    result["note"] = (
        "These are estimates based on list pricing. For exact billing, "
        "see your provider's billing dashboard"
    )

    conn.close()
    return result
