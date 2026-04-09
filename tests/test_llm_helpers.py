"""
Unit tests for non-API helper logic in llm.py.
"""

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from llm import _build_response_cache_key


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
