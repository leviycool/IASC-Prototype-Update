"""
Persistent storage for multi-topic chat conversations.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from config import DATA_DIR
from data_source import get_default_data_source
from task_memory import coerce_task_memory, initialize_task_memory, sync_memory_with_data_source
from token_tracker import ResponseUsage


DB_PATH = DATA_DIR / "conversations.db"
DEFAULT_CONVERSATION_TITLE = "New topic"


def _get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            is_archived INTEGER NOT NULL DEFAULT 0,
            archived_at TEXT,
            message_count INTEGER NOT NULL DEFAULT 0,
            preview TEXT,
            data_source_json TEXT NOT NULL,
            task_memory_json TEXT NOT NULL,
            messages_json TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def create_conversation(
    *,
    title: str | None = None,
    data_source: dict[str, Any] | None = None,
    task_memory: dict[str, Any] | None = None,
    messages: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create a new persisted conversation thread."""
    conversation_id = f"conv-{uuid.uuid4().hex[:10]}"
    now = _timestamp_now()
    normalized_data_source = _normalize_data_source(data_source)
    normalized_messages = _normalize_messages(messages)
    normalized_task_memory = _normalize_task_memory(task_memory, normalized_data_source)
    resolved_title = _derive_title(title, normalized_task_memory, normalized_messages)

    conn = _get_connection()
    try:
        conn.execute(
            """
            INSERT INTO conversations (
                id, title, created_at, updated_at, is_archived, archived_at,
                message_count, preview, data_source_json, task_memory_json, messages_json
            )
            VALUES (?, ?, ?, ?, 0, NULL, ?, ?, ?, ?, ?)
            """,
            (
                conversation_id,
                resolved_title,
                now,
                now,
                len(normalized_messages),
                _build_preview(normalized_messages),
                _dumps(normalized_data_source),
                _dumps(normalized_task_memory),
                _dumps(_serialize_messages(normalized_messages)),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return get_conversation(conversation_id)


def get_conversation(conversation_id: str | None) -> dict[str, Any] | None:
    """Load one conversation and deserialize its full state."""
    if not conversation_id:
        return None

    conn = _get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return None
    return _row_to_full_conversation(row)


def get_latest_conversation(include_archived: bool = False) -> dict[str, Any] | None:
    """Return the most recently updated conversation."""
    conn = _get_connection()
    try:
        if include_archived:
            row = conn.execute(
                "SELECT * FROM conversations ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT * FROM conversations
                WHERE is_archived = 0
                ORDER BY updated_at DESC
                LIMIT 1
                """
            ).fetchone()
    finally:
        conn.close()

    if row is None:
        return None
    return _row_to_full_conversation(row)


def list_conversations(*, archived: bool, limit: int = 25) -> list[dict[str, Any]]:
    """List conversation metadata for sidebar navigation."""
    conn = _get_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, title, created_at, updated_at, is_archived, archived_at,
                   message_count, preview, data_source_json, task_memory_json
            FROM conversations
            WHERE is_archived = ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (1 if archived else 0, int(limit)),
        ).fetchall()
    finally:
        conn.close()

    results: list[dict[str, Any]] = []
    for row in rows:
        data_source = _loads(row["data_source_json"], default={})
        task_memory = coerce_task_memory(_loads(row["task_memory_json"], default={}))
        results.append(
            {
                "id": row["id"],
                "title": row["title"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "is_archived": bool(row["is_archived"]),
                "archived_at": row["archived_at"],
                "message_count": row["message_count"],
                "preview": row["preview"],
                "data_source_label": data_source.get("label") or "Demo dataset",
                "task_title": task_memory.get("task_title"),
                "memory_summary": task_memory.get("memory_summary"),
            }
        )
    return results


def save_conversation_state(
    conversation_id: str,
    *,
    title: str | None = None,
    messages: list[dict[str, Any]] | None = None,
    task_memory: dict[str, Any] | None = None,
    data_source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist the latest state for one conversation."""
    existing = get_conversation(conversation_id)
    if existing is None:
        raise KeyError(f"Conversation not found: {conversation_id}")

    normalized_data_source = _normalize_data_source(
        existing["data_source"] if data_source is None else data_source
    )
    normalized_messages = _normalize_messages(
        existing["messages"] if messages is None else messages
    )
    normalized_task_memory = _normalize_task_memory(
        existing["task_memory"] if task_memory is None else task_memory,
        normalized_data_source,
    )
    resolved_title = _derive_title(title or existing["title"], normalized_task_memory, normalized_messages)

    conn = _get_connection()
    try:
        conn.execute(
            """
            UPDATE conversations
            SET title = ?,
                updated_at = ?,
                message_count = ?,
                preview = ?,
                data_source_json = ?,
                task_memory_json = ?,
                messages_json = ?
            WHERE id = ?
            """,
            (
                resolved_title,
                _timestamp_now(),
                len(normalized_messages),
                _build_preview(normalized_messages),
                _dumps(normalized_data_source),
                _dumps(normalized_task_memory),
                _dumps(_serialize_messages(normalized_messages)),
                conversation_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return get_conversation(conversation_id)


def set_conversation_archived(conversation_id: str, archived: bool) -> dict[str, Any]:
    """Archive or restore a conversation."""
    if get_conversation(conversation_id) is None:
        raise KeyError(f"Conversation not found: {conversation_id}")

    archived_at = _timestamp_now() if archived else None
    conn = _get_connection()
    try:
        conn.execute(
            """
            UPDATE conversations
            SET is_archived = ?,
                archived_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                1 if archived else 0,
                archived_at,
                _timestamp_now(),
                conversation_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return get_conversation(conversation_id)


def _row_to_full_conversation(row: sqlite3.Row) -> dict[str, Any]:
    data_source = _normalize_data_source(_loads(row["data_source_json"], default={}))
    task_memory = _normalize_task_memory(_loads(row["task_memory_json"], default={}), data_source)
    messages = _deserialize_messages(_loads(row["messages_json"], default=[]))
    return {
        "id": row["id"],
        "title": row["title"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "is_archived": bool(row["is_archived"]),
        "archived_at": row["archived_at"],
        "message_count": row["message_count"],
        "preview": row["preview"],
        "data_source": data_source,
        "task_memory": task_memory,
        "messages": messages,
    }


def _normalize_data_source(data_source: dict[str, Any] | None) -> dict[str, Any]:
    base = get_default_data_source()
    if not data_source:
        return base
    normalized = dict(base)
    normalized.update(data_source)
    return normalized


def _normalize_task_memory(
    task_memory: dict[str, Any] | None,
    data_source: dict[str, Any] | None,
) -> dict[str, Any]:
    if task_memory is None:
        task_memory = initialize_task_memory()
    return sync_memory_with_data_source(coerce_task_memory(task_memory), data_source)


def _normalize_messages(messages: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for message in messages or []:
        normalized.append(
            {
                "role": message.get("role", "assistant"),
                "content": message.get("content", ""),
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
        else:
            usage_payload = usage
        serialized.append(
            {
                "role": message.get("role", "assistant"),
                "content": message.get("content", ""),
                "usage": usage_payload,
            }
        )
    return serialized


def _deserialize_messages(messages: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    deserialized: list[dict[str, Any]] = []
    for message in messages or []:
        usage_payload = message.get("usage")
        usage = ResponseUsage.from_dict(usage_payload) if usage_payload else None
        deserialized.append(
            {
                "role": message.get("role", "assistant"),
                "content": message.get("content", ""),
                "usage": usage,
            }
        )
    return deserialized


def _derive_title(
    title: str | None,
    task_memory: dict[str, Any] | None,
    messages: list[dict[str, Any]] | None,
) -> str:
    cleaned_title = " ".join((title or "").split())
    inferred_title = None

    if task_memory:
        inferred_title = task_memory.get("task_title")

    if not inferred_title:
        for message in messages or []:
            if message.get("role") == "user" and message.get("content"):
                inferred_title = " ".join(message["content"].split())
                break

    resolved = inferred_title or cleaned_title or DEFAULT_CONVERSATION_TITLE
    return resolved[:120]


def _build_preview(messages: list[dict[str, Any]]) -> str | None:
    for message in reversed(messages):
        content = " ".join(str(message.get("content", "")).split())
        if content:
            return content[:140]
    return None


def _loads(raw: str | None, *, default: Any) -> Any:
    if not raw:
        return default
    return json.loads(raw)


def _dumps(payload: Any) -> str:
    return json.dumps(payload, default=str, sort_keys=True)


def _timestamp_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()
