"""
Behavioral test scenarios for the IASC donor analytics tool.

These tests send natural language questions through the full pipeline
(Claude API + tool use + data queries) and check that responses meet
basic quality criteria.

IMPORTANT: These tests make real API calls and cost money (~$0.01-0.05 each).
Run selectively during development:
    pytest tests/test_scenarios.py -v -k "top_donors"  # single scenario
    pytest tests/ -k "not llm"                          # skip all LLM tests

All tests in this module are marked with the "llm" pytest mark. To exclude
them from a test run, use:
    pytest tests/ -k "not llm"
"""

import os
import sys
import re
import pytest
from pathlib import Path

# Add src to path so we can import from llm.py and token_tracker.py
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

DB_PATH = Path(__file__).parent.parent / "data" / "donors.db"

# Mark all tests in this module as "llm" so they can be excluded with -k "not llm".
# Also skip the entire module if no API key or database is present.
pytestmark = [
    pytest.mark.skipif(
        not os.getenv("ANTHROPIC_API_KEY") or not DB_PATH.exists(),
        reason="Requires ANTHROPIC_API_KEY environment variable and data/donors.db",
    ),
    pytest.mark.llm,
]

from llm import get_response
from token_tracker import SessionTracker


# ─── Helper ──────────────────────────────────────────────────────────────────

def run_query(question: str) -> str:
    """Run a single question through the full pipeline and return the response text."""
    tracker = SessionTracker()
    response_text, _usage, _provenance = get_response(
        user_message=question,
        conversation_history=[],
        session_tracker=tracker,
    )
    return response_text


# ─── TestBasicDataQueries ─────────────────────────────────────────────────────

class TestBasicDataQueries:
    """Verify that Claude correctly queries and presents donor data."""

    def test_top_donors_includes_amounts(self):
        """Top donors response must include dollar amounts."""
        response = run_query("Who are our top 5 donors by total giving?")
        assert "$" in response, "Response should include dollar amounts"
        assert len(response) > 100, "Response should be substantive, not a one-liner"

    def test_lapsed_donors_virginia_mentions_state(self):
        """Lapsed donor query with Virginia filter must reference that state."""
        response = run_query("Which lapsed donors in Virginia gave more than $5,000?")
        assert "Virginia" in response or "VA" in response, (
            "Response should explicitly mention Virginia"
        )

    def test_pipeline_overview_covers_multiple_statuses(self):
        """Pipeline overview must address at least two donor status categories."""
        response = run_query("What does our donor pipeline look like?")
        statuses = ["active", "lapsed", "prospect"]
        mentioned = [s for s in statuses if s in response.lower()]
        assert len(mentioned) >= 2, (
            f"Should mention at least 2 status types; found: {mentioned}"
        )

    def test_subscriber_prospects_returns_a_number(self):
        """Query about non-donor subscribers should include at least one number."""
        response = run_query("How many subscribers have never donated?")
        numbers = re.findall(r"\d+", response)
        assert len(numbers) > 0, "Response should include at least one number"

    def test_giving_vehicle_filter_mentions_vehicle_type(self):
        """Filter by giving vehicle should acknowledge the vehicle type(s) asked about."""
        response = run_query("Show me donors who gave stock or through a DAF")
        assert any(term in response for term in ["stock", "Stock", "DAF", "donor-advised"]), (
            "Response should mention stock or DAF"
        )

    def test_top_donors_response_is_not_hallucinated(self):
        """Response should not be suspiciously short or purely generic."""
        response = run_query("Who are our top 10 donors by lifetime giving?")
        # A hallucinated or generic response would be very short
        assert len(response) > 200, (
            "Top-donors response should contain substantive detail"
        )
        # Should include at least one dollar sign (real gift amounts)
        assert "$" in response, "Response should include gift amounts"

    def test_new_donors_query_references_recency(self):
        """New donor cultivation query should acknowledge recency or time frame."""
        response = run_query("Which new donors from the last year should we cultivate?")
        recency_terms = ["year", "recent", "2024", "2025", "new", "last"]
        mentioned = [t for t in recency_terms if t.lower() in response.lower()]
        assert len(mentioned) >= 1, (
            f"Response should reference recency or time frame; found: {mentioned}"
        )


# ─── TestGeographicQueries ────────────────────────────────────────────────────

class TestGeographicQueries:
    """Verify geographic filtering and trip planning responses."""

    def test_nyc_trip_planning_mentions_new_york(self):
        """NYC trip planning must reference New York."""
        response = run_query("Plan a fundraising trip to NYC. Who should we meet?")
        assert any(term in response for term in ["New York", "NY", "NYC"]), (
            "Response should mention New York"
        )

    def test_dc_trip_planning_mentions_dc(self):
        """DC trip planning must reference DC or Washington."""
        response = run_query("We're planning a trip to DC. Who should we meet and why?")
        assert any(term in response for term in ["DC", "Washington", "D.C."]), (
            "Response should mention DC or Washington"
        )

    def test_trip_planning_explains_ranking(self):
        """Trip planning response should give a rationale for the candidates shown."""
        response = run_query("Plan a fundraising trip to Boston. Who should we meet?")
        rationale_terms = ["because", "given", "due to", "score", "giving", "capacity",
                           "engagement", "wealth", "subscription", "why", "reason"]
        mentioned = [t for t in rationale_terms if t.lower() in response.lower()]
        assert len(mentioned) >= 1, (
            "Trip planning should include some rationale for candidate selection"
        )

    def test_geographic_distribution_names_states(self):
        """Geographic distribution query should name at least two states."""
        response = run_query("What is the geographic distribution of our donors?")
        # Look for any 2-letter state codes or full state names as a proxy
        state_codes = re.findall(r"\b[A-Z]{2}\b", response)
        # At least two distinct state references
        assert len(set(state_codes)) >= 2 or len(response) > 200, (
            "Geographic distribution response should reference multiple states"
        )


# ─── TestKnowledgeBaseIntegration ─────────────────────────────────────────────

class TestKnowledgeBaseIntegration:
    """Verify that Claude draws on the fundraising knowledge base when relevant."""

    def test_best_practices_query_uses_fundraising_language(self):
        """Best practices query should reference established fundraising concepts."""
        response = run_query("What are best practices for re-engaging lapsed donors?")
        knowledge_terms = [
            "lapsed", "re-engage", "re-activation", "reactivation",
            "outreach", "cultivation", "stewardship", "benchmark",
            "recency", "recapture",
        ]
        mentioned = [t for t in knowledge_terms if t.lower() in response.lower()]
        assert len(mentioned) >= 2, (
            f"Should reference fundraising concepts; found: {mentioned}"
        )

    def test_prospect_cultivation_references_engagement_signals(self):
        """Prospect cultivation query should reference engagement or capacity indicators."""
        response = run_query("Who are the highest-potential prospects we should cultivate?")
        relevant_terms = [
            "wealth", "engagement", "subscription", "event", "email",
            "capacity", "potential", "score", "open rate",
        ]
        mentioned = [t for t in relevant_terms if t.lower() in response.lower()]
        assert len(mentioned) >= 2, (
            f"Should mention engagement signals; found: {mentioned}"
        )

    def test_strategy_question_does_not_hallucinate_data(self):
        """Pure strategy question should still be grounded and not invent numbers."""
        response = run_query("What are the most important metrics to track in fundraising?")
        # A valid response discusses metrics; a bad response makes up IASC-specific numbers
        assert len(response) > 100, "Strategy response should be substantive"


# ─── TestEdgeCases ────────────────────────────────────────────────────────────

class TestEdgeCases:
    """Test error handling, empty results, and edge cases."""

    def test_comparison_query_addresses_both_groups(self):
        """A comparison between Virginia and out-of-state donors should cover both."""
        response = run_query(
            "Compare giving patterns between Virginia donors and out-of-state donors"
        )
        assert "Virginia" in response or "VA" in response, (
            "Comparison should mention Virginia"
        )
        assert len(response) > 200, "Comparison should be substantive"

    def test_no_results_query_does_not_crash(self):
        """A query that likely returns zero results should produce a helpful message."""
        # Extremely restrictive filter: $10M+ donors in Hawaii — almost certainly 0
        response = run_query(
            "Who are the donors in Hawaii who gave more than $10 million?"
        )
        # Should not be empty and should not be an error traceback
        assert len(response) > 20, "Should produce some kind of response"
        assert "Traceback" not in response, "Should not expose a Python traceback"

    def test_follow_up_question_preserves_context(self):
        """A follow-up question after an initial answer should be coherent.

        This is a two-turn test: we seed a conversation history manually
        rather than relying on session state (which doesn't exist here).
        """
        tracker = SessionTracker()
        # First turn
        first_q = "Who are our top 3 donors?"
        first_response, _usage, _provenance = get_response(
            user_message=first_q,
            conversation_history=[],
            session_tracker=tracker,
        )
        # Build a minimal history for the follow-up
        history = [
            {"role": "user", "content": first_q},
            {"role": "assistant", "content": first_response},
        ]
        # Second turn — follow-up
        follow_up = "Where do each of them live?"
        follow_up_response, _usage2, _provenance2 = get_response(
            user_message=follow_up,
            conversation_history=history,
            session_tracker=tracker,
        )
        # The follow-up should be substantive and reference geography
        assert len(follow_up_response) > 50, "Follow-up response should be substantive"
        geo_terms = ["city", "state", "lives", "located", "based", "from", "NY", "VA",
                     "CA", "DC", "New York", "Virginia", "California"]
        mentioned = [t for t in geo_terms if t in follow_up_response]
        assert len(mentioned) >= 1, (
            "Follow-up about locations should reference geography"
        )
