"""
Tests for refresh-safe session persistence.
"""

from datetime import datetime
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import session_store
from task_memory import initialize_task_memory, sync_memory_with_data_source, update_task_memory
from token_tracker import APICall, ResponseUsage, SessionTracker


def _demo_data_source(tmp_path: Path) -> dict[str, str]:
    return {
        "kind": "synthetic",
        "label": "Synthetic demo dataset",
        "db_path": str(tmp_path / "donors.db"),
        "source_note": "Built-in synthetic donor database bundled with the app.",
    }


def test_session_state_round_trip_restores_messages_memory_and_tracker(tmp_path, monkeypatch):
    monkeypatch.setattr(session_store, "DB_PATH", tmp_path / "session_state.db")

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
            timestamp=datetime(2026, 4, 20, 10, 30, 0),
            input_tokens=100,
            output_tokens=25,
            model="gpt-4.1-mini",
            had_tool_use=True,
            latency_ms=750,
            cache_read_input_tokens=20,
        )
    )

    tracker = SessionTracker()
    tracker.responses.append(usage)

    session_store.save_session_state(
        session_id="browser-1234",
        messages=[
            {"role": "user", "content": "Which lapsed donors in Virginia should we re-engage?", "usage": None},
            {"role": "assistant", "content": "Three donors stand out.", "usage": usage},
        ],
        task_memory=task_memory,
        data_source=data_source,
        tracker=tracker,
        selected_model="gpt-4.1-mini",
        selected_provider="openai",
    )

    restored = session_store.load_session_state("browser-1234")

    assert restored is not None
    assert restored["selected_model"] == "gpt-4.1-mini"
    assert restored["selected_provider"] == "openai"
    assert restored["task_memory"]["current_geography"] == "Virginia"
    assert restored["messages"][1]["content"] == "Three donors stand out."
    assert isinstance(restored["messages"][1]["usage"], ResponseUsage)
    assert restored["messages"][1]["usage"].total_cache_read_tokens == 20
    assert restored["tracker"].total_api_calls == 1


def test_session_state_ignores_malformed_usage_payloads(tmp_path, monkeypatch):
    monkeypatch.setattr(session_store, "DB_PATH", tmp_path / "session_state.db")

    conn = session_store._get_connection()
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
            """,
            (
                "browser-bad",
                "2026-04-20T12:00:00+00:00",
                "gpt-4.1-mini",
                "openai",
                session_store._dumps(_demo_data_source(tmp_path)),
                session_store._dumps(initialize_task_memory()),
                session_store._dumps([
                    {"role": "assistant", "content": "Hello", "usage": "not-a-dict"},
                ]),
                session_store._dumps({"responses": ["also-not-a-dict"]}),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    restored = session_store.load_session_state("browser-bad")

    assert restored is not None
    assert restored["messages"][0]["usage"] is None
    assert restored["tracker"].total_api_calls == 0
