"""
Unit tests for session-scoped task memory helpers.
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
    update_task_memory,
    update_task_memory_from_response,
)


def test_initialize_task_memory_starts_inactive():
    task_state = initialize_task_memory()
    assert task_state["memory_active"] is False
    assert task_state["task_id"] is None
    assert task_state["active_filters"] == {}


def test_sample_question_initializes_lapsed_virginia_task():
    task_state = update_task_memory(
        "Which lapsed donors in Virginia should we re-engage?",
        classification="new_task",
        task_state=initialize_task_memory(),
        turn_index=1,
    )
    assert has_active_task(task_state) is True
    assert task_state["task_type"] == "donor_prioritization"
    assert task_state["current_segment"] == "lapsed donors"
    assert task_state["current_geography"] == "Virginia"
    assert "Prioritize lapsed donors in Virginia" == task_state["task_title"]


def test_sample_question_initializes_trip_planning_task():
    task_state = update_task_memory(
        "Plan a fundraising trip to NYC: who should we meet?",
        classification="new_task",
        task_state=initialize_task_memory(),
        turn_index=1,
    )
    assert task_state["task_type"] == "trip_planning"
    assert task_state["current_geography"] == "NYC"
    assert task_state["task_title"] == "Plan fundraising trip to NYC"


def test_refinement_classification_defaults_to_continuity_for_active_task():
    active_task = update_task_memory(
        "Which lapsed donors in Virginia should we re-engage?",
        classification="new_task",
        task_state=initialize_task_memory(),
        turn_index=1,
    )
    turn_type = classify_user_message(
        "Only show the ones with high wealth scores",
        task_state=active_task,
        chat_history=[{"role": "user", "content": "Which lapsed donors in Virginia should we re-engage?"}],
    )
    assert turn_type == "refinement"


def test_refinement_keeps_scope_and_adds_filter():
    active_task = update_task_memory(
        "Which lapsed donors in Virginia should we re-engage?",
        classification="new_task",
        task_state=initialize_task_memory(),
        turn_index=1,
    )
    refined_task = update_task_memory(
        "Only show the ones with high wealth scores",
        classification="refinement",
        task_state=active_task,
        turn_index=2,
    )
    assert refined_task["current_segment"] == "lapsed donors"
    assert refined_task["current_geography"] == "Virginia"
    assert refined_task["active_filters"]["wealth_score"] == "high wealth scores only"


def test_trip_refinement_preserves_geography_and_adds_recency_filter():
    active_task = update_task_memory(
        "Plan a fundraising trip to NYC: who should we meet?",
        classification="new_task",
        task_state=initialize_task_memory(),
        turn_index=1,
    )
    refined_task = update_task_memory(
        "Narrow to people who gave in the last two years",
        classification="refinement",
        task_state=active_task,
        turn_index=2,
    )
    assert refined_task["task_type"] == "trip_planning"
    assert refined_task["current_geography"] == "NYC"
    assert refined_task["active_filters"]["recency"] == "gave in the last 2 years"


def test_topic_switch_detects_new_standalone_request():
    active_task = update_task_memory(
        "Which lapsed donors in Virginia should we re-engage?",
        classification="new_task",
        task_state=initialize_task_memory(),
        turn_index=1,
    )
    turn_type = classify_user_message(
        "What does our donor pipeline look like?",
        task_state=active_task,
        chat_history=[{"role": "assistant", "content": "Here are the top lapsed donors in Virginia."}],
    )
    assert turn_type == "topic_switch"


def test_contextual_prompt_includes_task_summary_and_prior_context_flag():
    active_task = update_task_memory(
        "Which lapsed donors in Virginia should we re-engage?",
        classification="new_task",
        task_state=initialize_task_memory(),
        turn_index=1,
    )
    active_task["last_conclusion"] = "Three Virginia lapsed donors stand out for re-engagement."
    prompt = build_contextual_prompt(
        message="Only show the ones with high wealth scores",
        task_state=active_task,
        chat_history=[{"role": "user", "content": "Which lapsed donors in Virginia should we re-engage?"}],
        turn_type="refinement",
        use_prior_context=True,
    )
    assert "Current task summary: Prioritize lapsed donors in Virginia" in prompt
    assert "Using prior-turn context: yes" in prompt
    assert "Last conclusion: Three Virginia lapsed donors stand out for re-engagement." in prompt


def test_response_update_captures_conclusion_and_shortlist():
    active_task = update_task_memory(
        "Who are our top 3 donors?",
        classification="new_task",
        task_state=initialize_task_memory(),
        turn_index=1,
    )
    updated_task = update_task_memory_from_response(
        "Here are the best prospects to contact next.\n\n"
        "- Jane Doe (Virginia)\n"
        "- John Smith (New York)\n"
        "- Maria Garcia (Washington, DC)",
        task_state=active_task,
    )
    assert updated_task["last_conclusion"] == "Here are the best prospects to contact next."
    assert updated_task["current_shortlist"] == ["Jane Doe", "John Smith", "Maria Garcia"]


def test_sidebar_context_placeholder_and_scope_summary():
    empty_state = initialize_task_memory()
    assert format_task_context_markdown(empty_state) == "No active task."
    assert summarize_task_scope(empty_state) == "No active scope"
