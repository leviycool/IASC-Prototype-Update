"""
Tests for persistent multi-topic conversation storage.
"""

from datetime import datetime
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import conversation_store
from task_memory import initialize_task_memory, sync_memory_with_data_source, update_task_memory
from token_tracker import APICall, ResponseUsage


def _demo_data_source(tmp_path: Path) -> dict[str, str]:
    return {
        "kind": "synthetic",
        "label": "Synthetic demo dataset",
        "db_path": str(tmp_path / "demo.db"),
        "source_note": "Built-in synthetic donor database bundled with the app.",
    }


def test_conversation_round_trip_restores_messages_memory_and_usage(tmp_path, monkeypatch):
    monkeypatch.setattr(conversation_store, "DB_PATH", tmp_path / "conversations.db")
    data_source = _demo_data_source(tmp_path)
    task_memory = sync_memory_with_data_source(initialize_task_memory(), data_source)
    task_memory = update_task_memory(
        "Which lapsed donors in Virginia should we re-engage?",
        classification="new_task",
        task_state=task_memory,
        turn_index=1,
    )

    usage = ResponseUsage(question="Which lapsed donors in Virginia should we re-engage?")
    usage.calls.append(
        APICall(
            timestamp=datetime(2026, 4, 20, 12, 0, 0),
            input_tokens=120,
            output_tokens=45,
            model="gpt-4.1-mini",
            had_tool_use=True,
            latency_ms=812,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=30,
        )
    )

    created = conversation_store.create_conversation(
        data_source=data_source,
        task_memory=task_memory,
        messages=[
            {
                "role": "user",
                "content": "Which lapsed donors in Virginia should we re-engage?",
                "usage": None,
            },
            {
                "role": "assistant",
                "content": "Three Virginia lapsed donors stand out for re-engagement.",
                "usage": usage,
            },
        ],
    )

    restored = conversation_store.get_conversation(created["id"])

    assert restored is not None
    assert restored["title"] == "Lapsed Donors in Virginia"
    assert restored["task_memory"]["current_geography"] == "Virginia"
    assert restored["messages"][0]["content"] == "Which lapsed donors in Virginia should we re-engage?"
    assert isinstance(restored["messages"][1]["usage"], ResponseUsage)
    assert restored["messages"][1]["usage"].total_output_tokens == 45
    assert restored["messages"][1]["usage"].total_cache_read_tokens == 30


def test_save_conversation_state_persists_empty_message_list(tmp_path, monkeypatch):
    monkeypatch.setattr(conversation_store, "DB_PATH", tmp_path / "conversations.db")
    created = conversation_store.create_conversation(
        title="Scratch pad",
        data_source=_demo_data_source(tmp_path),
    )

    updated = conversation_store.save_conversation_state(
        created["id"],
        title=conversation_store.DEFAULT_CONVERSATION_TITLE,
        messages=[],
        task_memory=initialize_task_memory(),
        data_source=_demo_data_source(tmp_path),
    )

    assert updated["messages"] == []
    assert updated["message_count"] == 0
    assert updated["title"] == conversation_store.DEFAULT_CONVERSATION_TITLE


def test_archiving_moves_topics_between_active_and_archived_lists(tmp_path, monkeypatch):
    monkeypatch.setattr(conversation_store, "DB_PATH", tmp_path / "conversations.db")
    data_source = _demo_data_source(tmp_path)

    first = conversation_store.create_conversation(title="Topic A", data_source=data_source)
    second = conversation_store.create_conversation(title="Topic B", data_source=data_source)

    active_titles = [item["title"] for item in conversation_store.list_conversations(archived=False)]
    assert "Topic A" in active_titles
    assert "Topic B" in active_titles

    archived = conversation_store.set_conversation_archived(first["id"], archived=True)
    assert archived["is_archived"] is True

    active_titles_after = [item["title"] for item in conversation_store.list_conversations(archived=False)]
    archived_titles = [item["title"] for item in conversation_store.list_conversations(archived=True)]

    assert "Topic A" not in active_titles_after
    assert "Topic A" in archived_titles
    assert "Topic B" in active_titles_after

    restored = conversation_store.set_conversation_archived(first["id"], archived=False)
    assert restored["is_archived"] is False
    active_titles_restored = [item["title"] for item in conversation_store.list_conversations(archived=False)]
    assert "Topic A" in active_titles_restored
