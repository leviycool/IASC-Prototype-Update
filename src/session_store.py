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
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS archived_conversations (
            archive_id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            archived_at TEXT NOT NULL,
            title TEXT NOT NULL,
            preview TEXT,
            message_count INTEGER NOT NULL DEFAULT 0,
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


def archive_session_state(
    session_id: str,
    *,
    title: str | None = None,
) -> dict[str, Any] | None:
    """Save the current live conversation as an archived snapshot."""
    current = load_session_state(session_id)
    if current is None or not current["messages"]:
        return None

    normalized_title = _derive_archive_title(
        title=title,
        task_memory=current["task_memory"],
        messages=current["messages"],
    )
    preview = _build_preview(current["messages"])
    message_count = len(current["messages"])

    conn = _get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO archived_conversations (
                session_id,
                archived_at,
                title,
                preview,
                message_count,
                selected_model,
                selected_provider,
                data_source_json,
                task_memory_json,
                messages_json,
                tracker_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                _timestamp_now(),
                normalized_title,
                preview,
                message_count,
                current.get("selected_model"),
                current.get("selected_provider"),
                _dumps(_normalize_data_source(current.get("data_source"))),
                _dumps(_normalize_task_memory(current.get("task_memory"), current.get("data_source"))),
                _dumps(_serialize_messages(_normalize_messages(current.get("messages")))),
                _dumps(SessionTracker.from_dict(current.get("tracker")).to_dict()),
            ),
        )
        conn.commit()
        archive_id = int(cursor.lastrowid)
    finally:
        conn.close()

    return load_archived_conversation(session_id=session_id, archive_id=archive_id)


def list_archived_conversations(session_id: str, limit: int = 25) -> list[dict[str, Any]]:
    """List archived conversation snapshots for one browser session."""
    conn = _get_connection()
    try:
        rows = conn.execute(
            """
            SELECT archive_id, archived_at, title, preview, message_count
            FROM archived_conversations
            WHERE session_id = ?
            ORDER BY archived_at DESC, archive_id DESC
            LIMIT ?
            """,
            (session_id, int(limit)),
        ).fetchall()
    finally:
        conn.close()

    return [
        {
            "archive_id": row["archive_id"],
            "archived_at": row["archived_at"],
            "title": row["title"],
            "preview": row["preview"],
            "message_count": row["message_count"],
        }
        for row in rows
    ]


def load_archived_conversation(*, session_id: str, archive_id: int) -> dict[str, Any] | None:
    """Load one archived snapshot for a browser session."""
    conn = _get_connection()
    try:
        row = conn.execute(
            """
            SELECT *
            FROM archived_conversations
            WHERE session_id = ? AND archive_id = ?
            """,
            (session_id, int(archive_id)),
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
        "archive_id": row["archive_id"],
        "session_id": row["session_id"],
        "archived_at": row["archived_at"],
        "title": row["title"],
        "preview": row["preview"],
        "message_count": row["message_count"],
        "selected_model": row["selected_model"],
        "selected_provider": row["selected_provider"],
        "data_source": data_source,
        "task_memory": task_memory,
        "messages": messages,
        "tracker": tracker,
    }


def restore_archived_conversation(*, session_id: str, archive_id: int) -> dict[str, Any] | None:
    """Copy one archived snapshot back into the live browser session."""
    archived = load_archived_conversation(session_id=session_id, archive_id=archive_id)
    if archived is None:
        return None

    save_session_state(
        session_id=session_id,
        messages=archived["messages"],
        task_memory=archived["task_memory"],
        data_source=archived["data_source"],
        tracker=archived["tracker"],
        selected_model=archived.get("selected_model"),
        selected_provider=archived.get("selected_provider"),
    )
    return load_session_state(session_id)


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


def _derive_archive_title(
    *,
    title: str | None,
    task_memory: dict[str, Any] | None,
    messages: list[dict[str, Any]] | None,
) -> str:
    cleaned = " ".join(str(title or "").split())
    if cleaned:
        return cleaned[:120]

    if isinstance(task_memory, dict):
        task_title = " ".join(str(task_memory.get("task_title") or "").split())
        if task_title:
            return task_title[:120]

    for message in messages or []:
        if message.get("role") == "user":
            content = " ".join(str(message.get("content", "")).split())
            if content:
                return content[:120]

    return "Archived conversation"


def _build_preview(messages: list[dict[str, Any]] | None) -> str | None:
    for message in reversed(messages or []):
        content = " ".join(str(message.get("content", "")).split())
        if content:
            return content[:160]
    return None


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
