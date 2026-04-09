"""
Unit tests for non-API helper logic in llm.py.
"""

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from llm import _build_response_cache_key, _format_final_response


def test_long_response_gets_tldr_prefix():
    text = (
        "Andrew should prioritize the Virginia lapsed donors with the strongest past giving "
        "and recent engagement signals. Start with donors above $5,000 in lifetime giving, "
        "then narrow by recent email activity, event attendance, and subscription status. "
        "That gives the development team a short, actionable outreach list instead of a long "
        "raw export. The recommended outreach order should focus on donors with both strong "
        "historical giving and visible recent engagement, because that combination suggests "
        "higher near-term reactivation potential. In practice, that means the answer should "
        "call out the first few names, explain the filters used to identify them, and make "
        "it easy to scan the next steps without reading a dense paragraph from top to bottom. "
        "If the response keeps expanding with supporting detail, it should still open with a "
        "one-line summary so the development team can grasp the recommendation immediately."
    )
    formatted = _format_final_response(text)
    assert formatted.startswith("TL;DR:")
    assert text in formatted


def test_short_response_is_left_alone():
    text = "No donors matched those filters."
    assert _format_final_response(text) == text


def test_existing_tldr_is_not_duplicated():
    text = "TL;DR: Focus on the top three donors first.\n\nThen review recent engagement."
    formatted = _format_final_response(text)
    assert formatted.count("TL;DR:") == 1


def test_response_cache_key_is_stable_for_identical_inputs():
    key1 = _build_response_cache_key(
        provider="claude",
        model="claude-haiku-4-5-20251001",
        system_prompt="system",
        user_message="Who are our top donors?",
        conversation_history=[],
    )
    key2 = _build_response_cache_key(
        provider="claude",
        model="claude-haiku-4-5-20251001",
        system_prompt="system",
        user_message="Who are our top donors?",
        conversation_history=[],
    )
    assert key1 == key2


def test_response_cache_key_changes_when_question_changes():
    key1 = _build_response_cache_key(
        provider="claude",
        model="claude-haiku-4-5-20251001",
        system_prompt="system",
        user_message="Who are our top donors?",
        conversation_history=[],
    )
    key2 = _build_response_cache_key(
        provider="claude",
        model="claude-haiku-4-5-20251001",
        system_prompt="system",
        user_message="Which donors are lapsed?",
        conversation_history=[],
    )
    assert key1 != key2
