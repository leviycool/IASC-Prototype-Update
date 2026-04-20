"""
Minimal persistence for restoring the current chat after a page refresh.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from config import DATA_DIR
from data_source import get_default_data_source
from task_memory import coerce_task_memory, initialize_task_memory, sync_memory_with_data_source
from token_tracker import ResponseUsage, SessionTracker


DB_PATH = DATA_DIR / "session_state.db"


def _get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS session_state (
            session_id TEXT PRIMARY KEY,
            updated_at TEXT NOT NULL,
            selected_model TEXT,
            selected_provider TEXT,
            data_source_json TEXT NOT NULL,
            task_memory_json TEXT NOT NULL,
            messages_json TEXT NOT NULL,
            tracker_json TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def load_session_state(session_id: str) -> dict[str, Any] | None:
    """Load one persisted browser session."""
    conn = _get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM session_state WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return None

    data_source = _normalize_data_source(_loads(row["data_source_json"], default={}))
    task_memory = _normalize_task_memory(_loads(row["task_memory_json"], default={}), data_source)
    messages = _deserialize_messages(_loads(row["messages_json"], default=[]))
    tracker = SessionTracker.from_dict(_loads(row["tracker_json"], default={}))

    return {
        "session_id": row["session_id"],
        "updated_at": row["updated_at"],
        "selected_model": row["selected_model"],
        "selected_provider": row["selected_provider"],
        "data_source": data_source,
        "task_memory": task_memory,
        "messages": messages,
        "tracker": tracker,
    }


def save_session_state(
    *,
    session_id: str,
    messages: list[dict[str, Any]],
    task_memory: dict[str, Any] | None,
    data_source: dict[str, Any] | None,
    tracker: SessionTracker | dict[str, Any] | None,
    selected_model: str | None,
    selected_provider: str | None,
) -> None:
    """Persist the current browser session."""
    normalized_data_source = _normalize_data_source(data_source)
    normalized_task_memory = _normalize_task_memory(task_memory, normalized_data_source)
    normalized_messages = _normalize_messages(messages)
    normalized_tracker = SessionTracker.from_dict(tracker).to_dict()

    conn = _get_connection()
    try:
        conn.execute(
            """
            INSERT INTO session_state (
                session_id,
                updated_at,
                selected_model,
                selected_provider,
                data_source_json,
                task_memory_json,
                messages_json,
                tracker_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                updated_at = excluded.updated_at,
                selected_model = excluded.selected_model,
                selected_provider = excluded.selected_provider,
                data_source_json = excluded.data_source_json,
                task_memory_json = excluded.task_memory_json,
                messages_json = excluded.messages_json,
                tracker_json = excluded.tracker_json
            """,
            (
                session_id,
                _timestamp_now(),
                selected_model,
                selected_provider,
                _dumps(normalized_data_source),
                _dumps(normalized_task_memory),
                _dumps(_serialize_messages(normalized_messages)),
                _dumps(normalized_tracker),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _normalize_data_source(data_source: dict[str, Any] | None) -> dict[str, Any]:
    normalized = dict(get_default_data_source())
    if data_source:
        normalized.update(data_source)
    return normalized


def _normalize_task_memory(
    task_memory: dict[str, Any] | None,
    data_source: dict[str, Any] | None,
) -> dict[str, Any]:
    base = initialize_task_memory() if task_memory is None else coerce_task_memory(task_memory)
    return sync_memory_with_data_source(base, data_source)


def _normalize_messages(messages: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for message in messages or []:
        normalized.append(
            {
                "role": message.get("role", "assistant"),
                "content": str(message.get("content", "") or ""),
                "usage": message.get("usage"),
            }
        )
    return normalized


def _serialize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for message in messages:
        usage = message.get("usage")
        if isinstance(usage, ResponseUsage):
            usage_payload = usage.to_dict()
        elif isinstance(usage, dict):
            usage_payload = usage
        else:
            usage_payload = None

        serialized.append(
            {
                "role": message.get("role", "assistant"),
                "content": str(message.get("content", "") or ""),
                "usage": usage_payload,
            }
        )
    return serialized


def _deserialize_messages(messages: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    restored: list[dict[str, Any]] = []
    for message in messages or []:
        usage_payload = message.get("usage")
        usage = ResponseUsage.from_dict(usage_payload) if isinstance(usage_payload, dict) else None
        restored.append(
            {
                "role": message.get("role", "assistant"),
                "content": str(message.get("content", "") or ""),
                "usage": usage,
            }
        )
    return restored


def _loads(raw: str | None, *, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def _dumps(payload: Any) -> str:
    return json.dumps(payload, default=str, sort_keys=True)


def _timestamp_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()
