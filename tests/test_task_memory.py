"""
Unit tests for GPT-style session-memory helpers.
"""

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from task_memory import (
    build_contextual_prompt,
    classify_user_message,
    format_task_context_markdown,
    has_active_task,
    initialize_task_memory,
    summarize_task_scope,
    sync_memory_with_data_source,
    update_task_memory,
    update_task_memory_from_response,
)


def test_initialize_task_memory_starts_inactive():
    memory = initialize_task_memory()
    assert memory["memory_active"] is False
    assert memory["memory_summary"] is None
    assert memory["memory_id"].startswith("mem-")


def test_greeting_does_not_activate_memory():
    memory = update_task_memory(
        "hello",
        classification="new_task",
        task_state=initialize_task_memory(),
        turn_index=1,
    )
    assert has_active_task(memory) is False
    assert memory["memory_summary"] is None


def test_sample_question_builds_session_summary():
    memory = update_task_memory(
        "Which lapsed donors in Virginia should we re-engage?",
        classification="new_task",
        task_state=initialize_task_memory(),
        turn_index=1,
    )
    assert has_active_task(memory) is True
    assert memory["task_type"] == "donor_prioritization"
    assert memory["current_segment"] == "lapsed donors"
    assert memory["current_geography"] == "Virginia"
    assert "We are analyzing lapsed donors in Virginia" in memory["memory_summary"]


def test_trip_question_initializes_broader_memory():
    memory = update_task_memory(
        "Plan a fundraising trip to NYC: who should we meet?",
        classification="new_task",
        task_state=initialize_task_memory(),
        turn_index=1,
    )
    assert memory["task_type"] == "trip_planning"
    assert memory["current_geography"] == "NYC"
    assert memory["task_title"] == "Fundraising trip in NYC"
    assert "planning a fundraising trip in NYC" in memory["memory_summary"]


def test_refinement_classification_defaults_to_continuity_for_active_memory():
    active_memory = update_task_memory(
        "Which lapsed donors in Virginia should we re-engage?",
        classification="new_task",
        task_state=initialize_task_memory(),
        turn_index=1,
    )
    turn_type = classify_user_message(
        "Only show the ones with high wealth scores",
        task_state=active_memory,
        chat_history=[{"role": "user", "content": "Which lapsed donors in Virginia should we re-engage?"}],
    )
    assert turn_type == "refinement"


def test_refinement_keeps_scope_and_adds_filter():
    active_memory = update_task_memory(
        "Which lapsed donors in Virginia should we re-engage?",
        classification="new_task",
        task_state=initialize_task_memory(),
        turn_index=1,
    )
    refined_memory = update_task_memory(
        "Only show the ones with high wealth scores",
        classification="refinement",
        task_state=active_memory,
        turn_index=2,
    )
    assert refined_memory["current_segment"] == "lapsed donors"
    assert refined_memory["current_geography"] == "Virginia"
    assert refined_memory["active_filters"]["wealth_score"] == "high wealth scores only"
    assert "high wealth scores only" in refined_memory["memory_summary"]


def test_trip_refinement_preserves_geography_and_adds_recency_filter():
    active_memory = update_task_memory(
        "Plan a fundraising trip to NYC: who should we meet?",
        classification="new_task",
        task_state=initialize_task_memory(),
        turn_index=1,
    )
    refined_memory = update_task_memory(
        "Narrow to people who gave in the last two years",
        classification="refinement",
        task_state=active_memory,
        turn_index=2,
    )
    assert refined_memory["task_type"] == "trip_planning"
    assert refined_memory["current_geography"] == "NYC"
    assert refined_memory["active_filters"]["recency"] == "gave in the last 2 years"


def test_topic_switch_detects_new_standalone_request():
    active_memory = update_task_memory(
        "Which lapsed donors in Virginia should we re-engage?",
        classification="new_task",
        task_state=initialize_task_memory(),
        turn_index=1,
    )
    turn_type = classify_user_message(
        "What does our donor pipeline look like?",
        task_state=active_memory,
        chat_history=[{"role": "assistant", "content": "Here are the top lapsed donors in Virginia."}],
    )
    assert turn_type == "topic_switch"


def test_contextual_prompt_includes_session_summary_and_dataset():
    active_memory = update_task_memory(
        "Which lapsed donors in Virginia should we re-engage?",
        classification="new_task",
        task_state=initialize_task_memory(),
        turn_index=1,
    )
    active_memory["last_conclusion"] = "Three Virginia lapsed donors stand out for re-engagement."
    active_memory = sync_memory_with_data_source(
        active_memory,
        {"label": "Uploaded CSV dataset", "kind": "uploaded_csv"},
    )
    prompt = build_contextual_prompt(
        message="Only show the ones with high wealth scores",
        task_state=active_memory,
        chat_history=[{"role": "user", "content": "Which lapsed donors in Virginia should we re-engage?"}],
        turn_type="refinement",
        use_prior_context=True,
    )
    assert "Summary: We are analyzing lapsed donors in Virginia" in prompt
    assert "Current data source: Uploaded CSV dataset" in prompt
    assert "Using prior-turn context: yes" in prompt


def test_response_update_captures_conclusion_and_shortlist():
    active_memory = update_task_memory(
        "Who are our top 3 donors?",
        classification="new_task",
        task_state=initialize_task_memory(),
        turn_index=1,
    )
    updated_memory = update_task_memory_from_response(
        "Here are the best prospects to contact next.\n\n"
        "- Jane Doe (Virginia)\n"
        "- John Smith (New York)\n"
        "- Maria Garcia (Washington, DC)",
        task_state=active_memory,
    )
    assert updated_memory["last_conclusion"] == "Here are the best prospects to contact next."
    assert updated_memory["current_shortlist"] == ["Jane Doe", "John Smith", "Maria Garcia"]
    assert "Jane Doe" in updated_memory["memory_summary"]


def test_sidebar_memory_placeholder_and_scope_summary():
    empty_memory = initialize_task_memory()
    assert "No remembered analysis context yet." in format_task_context_markdown(empty_memory)
    assert summarize_task_scope(empty_memory) == "No remembered analytical scope"


def test_sync_memory_with_data_source_updates_sidebar_context():
    memory = sync_memory_with_data_source(
        initialize_task_memory(),
        {"label": "Uploaded database: donors.db", "kind": "uploaded_db"},
    )
    assert memory["dataset_label"] == "Uploaded database: donors.db"
    assert memory["dataset_kind"] == "uploaded_db"
