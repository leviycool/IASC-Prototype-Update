"""
Persistent cache for exact-match LLM responses.

This is used to stabilize repeated identical questions when the effective
request context has not changed.
"""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional


DB_PATH = Path(__file__).parent.parent / "data" / "response_cache.db"


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cached_responses (
            cache_key TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            response_text TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def get_cached_response(cache_key: str) -> Optional[str]:
    """Return a cached response for a fully-qualified request key."""
    conn = _get_connection()
    row = conn.execute(
        "SELECT response_text FROM cached_responses WHERE cache_key = ?",
        (cache_key,),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return row["response_text"]


def put_cached_response(
    cache_key: str,
    provider: str,
    model: str,
    response_text: str,
) -> None:
    """Persist the final response for an exact-match request."""
    conn = _get_connection()
    conn.execute(
        """
        INSERT INTO cached_responses (cache_key, provider, model, response_text, created_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(cache_key) DO UPDATE SET
            provider = excluded.provider,
            model = excluded.model,
            response_text = excluded.response_text,
            created_at = excluded.created_at
        """,
        (
            cache_key,
            provider,
            model,
            response_text,
            datetime.now().isoformat(),
        ),
    )
    conn.commit()
    conn.close()
