"""
test_queries.py — Unit tests for the IASC Donor Analytics query functions.

Run with:
    pytest tests/                           # all tests
    pytest tests/ -k "not llm"             # skip any LLM-calling tests
    pytest tests/test_queries.py -v        # verbose mode

All tests require data/donors.db to exist. If it does not, the entire module
is skipped with a clear message telling the developer how to regenerate it.
"""

import pytest
import sys
from datetime import date, timedelta
from pathlib import Path

# Make sure src/ is on the path so we can import from queries.py regardless
# of the working directory the test runner is invoked from.
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from queries import (
    get_donor_detail,
    get_geographic_distribution,
    get_lapsed_donors,
    get_prospects_by_potential,
    get_summary_statistics,
    plan_fundraising_trip,
    search_donors,
)

# ---------------------------------------------------------------------------
# Module-level skip guard
# ---------------------------------------------------------------------------

DB_PATH = Path(__file__).parent.parent / "data" / "donors.db"
pytestmark = pytest.mark.skipif(
    not DB_PATH.exists(),
    reason="Database not found. Run: python data/generate_mock_data.py",
)


# ===========================================================================
# TestSearchDonors
# ===========================================================================

class TestSearchDonors:
    """Tests for search_donors() — the general-purpose filter/list function."""

    def test_returns_dict_with_required_keys(self):
        result = search_donors(limit=5)
        assert "results" in result
        assert "count" in result
        assert "summary" in result

    def test_state_filter_returns_only_that_state(self):
        result = search_donors(state="VA")
        assert result["count"] > 0, "Expected at least one VA contact in mock data"
        for row in result["results"]:
            assert row["state"] == "VA", f"Expected state=VA, got {row['state']}"

    def test_donor_status_filter(self):
        result = search_donors(donor_status="active")
        assert result["count"] > 0
        for row in result["results"]:
            assert row["donor_status"] == "active"

    def test_min_total_gifts_filter(self):
        result = search_donors(min_total_gifts=10_000)
        for row in result["results"]:
            assert row["total_gifts"] >= 10_000

    def test_max_total_gifts_filter(self):
        result = search_donors(max_total_gifts=500)
        for row in result["results"]:
            assert row["total_gifts"] <= 500

    def test_min_and_max_gifts_range(self):
        result = search_donors(min_total_gifts=100, max_total_gifts=1_000)
        for row in result["results"]:
            assert 100 <= row["total_gifts"] <= 1_000

    def test_limit_is_respected(self):
        result = search_donors(limit=5)
        assert len(result["results"]) <= 5

    def test_limit_max_capped_at_50(self):
        # Passing 200 should silently be capped at 50
        result = search_donors(limit=200)
        assert len(result["results"]) <= 50

    def test_empty_result_handled_gracefully(self):
        result = search_donors(state="ZZ")  # nonexistent state
        assert result["count"] == 0
        assert isinstance(result["summary"], str) and len(result["summary"]) > 0
        # The summary should acknowledge that nothing was found
        summary_lower = result["summary"].lower()
        assert "no" in summary_lower or "0" in summary_lower or "not" in summary_lower

    def test_sort_order_descending(self):
        result = search_donors(sort_by="total_gifts", sort_order="desc", limit=10)
        gifts = [r["total_gifts"] for r in result["results"] if r["total_gifts"] is not None]
        assert gifts == sorted(gifts, reverse=True)

    def test_sort_order_ascending(self):
        result = search_donors(sort_by="total_gifts", sort_order="asc", limit=10)
        gifts = [r["total_gifts"] for r in result["results"] if r["total_gifts"] is not None]
        assert gifts == sorted(gifts)

    def test_giving_vehicle_filter(self):
        result = search_donors(giving_vehicle="DAF")
        for row in result["results"]:
            assert row["giving_vehicle"] == "DAF"

    def test_subscription_status_filter(self):
        result = search_donors(subscription_status="active")
        assert result["count"] > 0
        for row in result["results"]:
            assert row["subscription_status"] == "active"

    def test_subscription_type_filter(self):
        result = search_donors(subscription_type="digital")
        for row in result["results"]:
            assert row["subscription_type"] == "digital"

    def test_min_wealth_score_filter(self):
        result = search_donors(min_wealth_score=8)
        for row in result["results"]:
            assert row["wealth_score"] >= 8

    def test_has_attended_events_true(self):
        result = search_donors(has_attended_events=True)
        for row in result["results"]:
            assert (row["event_attendance_count"] or 0) > 0

    def test_has_attended_events_false(self):
        result = search_donors(has_attended_events=False, limit=10)
        for row in result["results"]:
            assert (row["event_attendance_count"] or 0) == 0

    def test_city_partial_match(self):
        # 'New York' should match rows whose city contains 'New York'
        result = search_donors(city="New York")
        for row in result["results"]:
            assert "new york" in (row["city"] or "").lower()

    def test_zip_prefix_filter(self):
        result = search_donors(zip_prefix="229")  # Charlottesville area
        for row in result["results"]:
            assert (row["zip_code"] or "").startswith("229")

    def test_last_gift_before_filter(self):
        cutoff = "2022-01-01"
        result = search_donors(last_gift_before=cutoff, limit=10)
        for row in result["results"]:
            if row["last_gift_date"]:
                assert row["last_gift_date"] < cutoff

    def test_last_gift_after_filter(self):
        cutoff = "2023-01-01"
        result = search_donors(last_gift_after=cutoff, limit=10)
        for row in result["results"]:
            if row["last_gift_date"]:
                assert row["last_gift_date"] > cutoff

    def test_min_email_open_rate_filter(self):
        result = search_donors(min_email_open_rate=0.5, limit=10)
        for row in result["results"]:
            assert (row["email_open_rate"] or 0) >= 0.5

    def test_combined_filters(self):
        # Multiple filters should all be applied simultaneously
        result = search_donors(
            state="VA",
            donor_status="active",
            min_total_gifts=1_000,
            limit=10,
        )
        for row in result["results"]:
            assert row["state"] == "VA"
            assert row["donor_status"] == "active"
            assert row["total_gifts"] >= 1_000

    def test_result_rows_contain_expected_fields(self):
        result = search_donors(limit=1)
        if result["count"] == 0:
            pytest.skip("No contacts in database")
        row = result["results"][0]
        expected_fields = {
            "contact_id", "first_name", "last_name", "state",
            "total_gifts", "donor_status", "wealth_score",
        }
        for field in expected_fields:
            assert field in row, f"Expected field '{field}' missing from result row"

    def test_invalid_sort_column_falls_back_to_default(self):
        # Should not raise; should fall back to total_gifts ordering
        result = search_donors(sort_by="DROP TABLE contacts; --", limit=5)
        assert "results" in result

    def test_repeated_calls_return_same_order(self):
        first = search_donors(sort_by="total_gifts", sort_order="desc", limit=15)
        second = search_donors(sort_by="total_gifts", sort_order="desc", limit=15)
        first_ids = [row["contact_id"] for row in first["results"]]
        second_ids = [row["contact_id"] for row in second["results"]]
        assert first_ids == second_ids


# ===========================================================================
# TestLapsedDonors
# ===========================================================================

class TestLapsedDonors:
    """Tests for get_lapsed_donors() — re-engagement targeting function."""

    def test_returns_dict_with_required_keys(self):
        result = get_lapsed_donors()
        assert "results" in result
        assert "count" in result
        assert "summary" in result

    def test_returns_results(self):
        result = get_lapsed_donors()
        assert result["count"] > 0, "Expected at least one lapsed donor in mock data"

    def test_last_gift_date_is_old_enough(self):
        months = 24
        result = get_lapsed_donors(months_since_last_gift=months)
        cutoff = date.today() - timedelta(days=months * 30)
        for row in result["results"]:
            if row["last_gift_date"]:
                last = date.fromisoformat(row["last_gift_date"])
                assert last < cutoff, (
                    f"last_gift_date {last} is not before cutoff {cutoff}"
                )

    def test_min_previous_total_filter(self):
        result = get_lapsed_donors(min_previous_total=5_000)
        for row in result["results"]:
            assert row["total_gifts"] >= 5_000

    def test_state_filter(self):
        result = get_lapsed_donors(state="VA")
        for row in result["results"]:
            assert row["state"] == "VA"

    def test_limit_respected(self):
        result = get_lapsed_donors(limit=3)
        assert len(result["results"]) <= 3

    def test_shorter_lapse_window_returns_more(self):
        result_12 = get_lapsed_donors(months_since_last_gift=12)
        result_36 = get_lapsed_donors(months_since_last_gift=36)
        # A shorter window means MORE people qualify as lapsed
        assert result_12["count"] >= result_36["count"]

    def test_result_rows_contain_expected_fields(self):
        result = get_lapsed_donors(limit=1)
        if result["count"] == 0:
            pytest.skip("No lapsed donors found")
        row = result["results"][0]
        expected_fields = {"contact_id", "last_gift_date", "total_gifts", "state"}
        for field in expected_fields:
            assert field in row


# ===========================================================================
# TestFundraisingTrip
# ===========================================================================

class TestFundraisingTrip:
    """Tests for plan_fundraising_trip() — composite-scored trip prioritisation."""

    def test_returns_dict_with_required_keys(self):
        result = plan_fundraising_trip(target_state="NY")
        assert "results" in result
        assert "count" in result
        assert "summary" in result

    def test_returns_scored_results(self):
        result = plan_fundraising_trip(target_state="NY")
        assert result["count"] > 0, "Expected at least one NY contact in mock data"
        for row in result["results"]:
            assert "score" in row, "score field missing from result row"
            assert 0.0 <= row["score"] <= 1.0, f"score {row['score']} out of [0, 1]"

    def test_results_are_in_target_geography_by_state(self):
        result = plan_fundraising_trip(target_state="VA")
        for row in result["results"]:
            assert row["state"] == "VA"

    def test_sorted_by_score_descending(self):
        result = plan_fundraising_trip(target_state="NY", limit=10)
        scores = [r["score"] for r in result["results"]]
        assert scores == sorted(scores, reverse=True), (
            "Results must be sorted by score descending"
        )

    def test_limit_respected(self):
        result = plan_fundraising_trip(target_state="NY", limit=5)
        assert len(result["results"]) <= 5

    def test_no_geography_returns_error_summary(self):
        result = plan_fundraising_trip()
        assert result["count"] == 0
        assert len(result["summary"]) > 0

    def test_exclude_prospects_flag(self):
        result = plan_fundraising_trip(target_state="NY", include_prospects=False, limit=20)
        for row in result["results"]:
            assert row["donor_status"] != "prospect"

    def test_exclude_lapsed_flag(self):
        result = plan_fundraising_trip(target_state="NY", include_lapsed=False, limit=20)
        for row in result["results"]:
            assert row["donor_status"] != "lapsed"

    def test_min_total_gifts_for_donors(self):
        # Donors below the threshold should be excluded
        result = plan_fundraising_trip(
            target_state="NY", min_total_gifts=5_000, include_prospects=False, limit=20
        )
        for row in result["results"]:
            if row["donor_status"] != "prospect":
                assert (row["total_gifts"] or 0) >= 5_000

    def test_zip_prefix_filter(self):
        result = plan_fundraising_trip(target_zip_prefix="229", limit=20)
        for row in result["results"]:
            assert (row["zip_code"] or "").startswith("229")

    def test_scores_are_deterministic(self):
        result1 = plan_fundraising_trip(target_state="VA", limit=10)
        result2 = plan_fundraising_trip(target_state="VA", limit=10)
        scores1 = [r["score"] for r in result1["results"]]
        scores2 = [r["score"] for r in result2["results"]]
        assert scores1 == scores2, "Scores should be deterministic for the same input"

    def test_result_order_is_deterministic(self):
        result1 = plan_fundraising_trip(target_state="VA", limit=10)
        result2 = plan_fundraising_trip(target_state="VA", limit=10)
        ids1 = [r["contact_id"] for r in result1["results"]]
        ids2 = [r["contact_id"] for r in result2["results"]]
        assert ids1 == ids2, "Ranked contact order should be deterministic"


# ===========================================================================
# TestSummaryStatistics
# ===========================================================================

class TestSummaryStatistics:
    """Tests for get_summary_statistics() — aggregate reporting function."""

    def test_returns_dict_with_required_keys(self):
        result = get_summary_statistics()
        assert "results" in result
        assert "count" in result
        assert "summary" in result

    def test_overall_stats_has_total_contacts(self):
        result = get_summary_statistics()
        assert result["count"] > 0
        row = result["results"][0]
        assert "total_contacts" in row, "overall stats row should contain total_contacts"
        assert row["total_contacts"] > 0

    def test_group_by_donor_status(self):
        result = get_summary_statistics(group_by="donor_status")
        assert result["count"] > 0
        # Mock data has multiple statuses; we should see at least 2 groups
        assert len(result["results"]) >= 2
        for row in result["results"]:
            assert "group_value" in row
            assert "total_contacts" in row

    def test_group_by_state(self):
        result = get_summary_statistics(group_by="state")
        assert result["count"] > 0
        # There should be several states in 300-record mock data
        assert len(result["results"]) >= 3

    def test_group_by_subscription_type(self):
        result = get_summary_statistics(group_by="subscription_type")
        assert result["count"] > 0

    def test_group_by_giving_vehicle(self):
        result = get_summary_statistics(group_by="giving_vehicle")
        assert result["count"] > 0

    def test_filter_status(self):
        result = get_summary_statistics(filter_status="active")
        row = result["results"][0]
        # Every counted contact must be active; lapsed_donors should be 0
        assert row.get("lapsed_donors", 0) == 0 or "group_value" in row

    def test_filter_state(self):
        result = get_summary_statistics(filter_state="VA")
        assert result["count"] > 0

    def test_invalid_group_by_falls_back_to_overall(self):
        # Invalid group_by should not raise; should return overall stats
        result = get_summary_statistics(group_by="DROP TABLE contacts; --")
        assert result["count"] > 0
        assert "total_contacts" in result["results"][0]


# ===========================================================================
# TestGeographicDistribution
# ===========================================================================

class TestGeographicDistribution:
    """Tests for get_geographic_distribution() — state-level aggregation."""

    def test_returns_dict_with_required_keys(self):
        result = get_geographic_distribution()
        assert "results" in result
        assert "count" in result
        assert "summary" in result

    def test_returns_state_data(self):
        result = get_geographic_distribution()
        assert result["count"] > 0
        for row in result["results"]:
            assert "state" in row
            assert "donor_count" in row
            assert "total_giving" in row

    def test_top_n_respected(self):
        result = get_geographic_distribution(top_n=5)
        assert len(result["results"]) <= 5

    def test_min_total_gifts_filter(self):
        # With a high threshold, the total per state should reflect only big donors
        result_all = get_geographic_distribution()
        result_big = get_geographic_distribution(min_total_gifts=10_000)
        # Fewer or equal contacts should qualify with the filter applied
        total_all = sum(r["donor_count"] for r in result_all["results"])
        total_big = sum(r["donor_count"] for r in result_big["results"])
        assert total_big <= total_all

    def test_sorted_by_donor_count_descending(self):
        result = get_geographic_distribution(top_n=10)
        counts = [r["donor_count"] for r in result["results"]]
        assert counts == sorted(counts, reverse=True)

    def test_donor_status_filter(self):
        result = get_geographic_distribution(donor_status="active")
        assert result["count"] > 0

    def test_repeated_calls_return_same_state_order(self):
        first = get_geographic_distribution(top_n=10)
        second = get_geographic_distribution(top_n=10)
        first_states = [row["state"] for row in first["results"]]
        second_states = [row["state"] for row in second["results"]]
        assert first_states == second_states


# ===========================================================================
# TestProspectsByPotential
# ===========================================================================

class TestProspectsByPotential:
    """Tests for get_prospects_by_potential() — prospect ranking function."""

    def test_returns_dict_with_required_keys(self):
        result = get_prospects_by_potential()
        assert "results" in result
        assert "count" in result
        assert "summary" in result

    def test_returns_only_prospects(self):
        result = get_prospects_by_potential()
        for row in result["results"]:
            assert row["donor_status"] == "prospect", (
                f"Expected prospect, got {row['donor_status']}"
            )

    def test_wealth_score_filter(self):
        result = get_prospects_by_potential(min_wealth_score=7)
        for row in result["results"]:
            if row["wealth_score"] is not None:
                assert row["wealth_score"] >= 7

    def test_min_email_open_rate_filter(self):
        result = get_prospects_by_potential(min_email_open_rate=0.4)
        for row in result["results"]:
            if row["email_open_rate"] is not None:
                assert row["email_open_rate"] >= 0.4

    def test_has_attended_events_filter(self):
        result = get_prospects_by_potential(has_attended_events=True)
        for row in result["results"]:
            assert (row["event_attendance_count"] or 0) > 0

    def test_has_subscription_true(self):
        result = get_prospects_by_potential(has_subscription=True)
        for row in result["results"]:
            assert row["subscription_status"] == "active"

    def test_state_filter(self):
        result = get_prospects_by_potential(state="NY")
        for row in result["results"]:
            assert row["state"] == "NY"

    def test_limit_respected(self):
        result = get_prospects_by_potential(limit=3)
        assert len(result["results"]) <= 3

    def test_repeated_calls_return_same_order(self):
        first = get_prospects_by_potential(limit=10)
        second = get_prospects_by_potential(limit=10)
        first_ids = [row["contact_id"] for row in first["results"]]
        second_ids = [row["contact_id"] for row in second["results"]]
        assert first_ids == second_ids

    def test_result_rows_contain_expected_fields(self):
        result = get_prospects_by_potential(limit=1)
        if result["count"] == 0:
            pytest.skip("No prospects in database")
        row = result["results"][0]
        expected_fields = {
            "contact_id", "first_name", "last_name",
            "wealth_score", "email_open_rate", "subscription_status",
        }
        for field in expected_fields:
            assert field in row


# ===========================================================================
# TestDonorDetail
# ===========================================================================

class TestDonorDetail:
    """Tests for get_donor_detail() — single-record lookup with history."""

    def test_returns_dict_with_required_keys(self):
        search = search_donors(donor_status="active", limit=1)
        if search["count"] == 0:
            pytest.skip("No active donors in database")
        contact_id = search["results"][0]["contact_id"]
        result = get_donor_detail(contact_id)
        assert "results" in result
        assert "count" in result
        assert "summary" in result

    def test_returns_complete_record(self):
        search = search_donors(donor_status="active", limit=1)
        if search["count"] == 0:
            pytest.skip("No active donors in database")
        contact_id = search["results"][0]["contact_id"]

        detail = get_donor_detail(contact_id)
        assert detail["count"] == 1
        row = detail["results"][0]
        assert row["contact_id"] == contact_id
        assert "gifts" in row, "Expected 'gifts' key in detail result"
        assert isinstance(row["gifts"], list)

    def test_includes_interactions(self):
        search = search_donors(limit=1)
        if search["count"] == 0:
            pytest.skip("No contacts in database")
        contact_id = search["results"][0]["contact_id"]

        detail = get_donor_detail(contact_id)
        row = detail["results"][0]
        assert "interactions" in row, "Expected 'interactions' key in detail result"
        assert isinstance(row["interactions"], list)

    def test_invalid_id_returns_empty(self):
        result = get_donor_detail("INVALID_ID_XXXX")
        assert result["count"] == 0
        assert result["results"] == []
        assert "not" in result["summary"].lower() or "no" in result["summary"].lower()

    def test_gifts_capped_at_10(self):
        # Even if a donor has many gifts, we only return the last 10
        search = search_donors(min_gift_count=1, limit=1)
        if search["count"] == 0:
            pytest.skip("No donors with gifts in database")
        contact_id = search["results"][0]["contact_id"]

        detail = get_donor_detail(contact_id)
        gifts = detail["results"][0]["gifts"]
        assert len(gifts) <= 10

    def test_interactions_capped_at_5(self):
        search = search_donors(limit=1)
        if search["count"] == 0:
            pytest.skip("No contacts in database")
        contact_id = search["results"][0]["contact_id"]

        detail = get_donor_detail(contact_id)
        interactions = detail["results"][0]["interactions"]
        assert len(interactions) <= 5

    def test_gifts_sorted_by_date_descending(self):
        search = search_donors(min_gift_count=2, limit=1)
        if search["count"] == 0:
            pytest.skip("No donors with multiple gifts")
        contact_id = search["results"][0]["contact_id"]

        detail = get_donor_detail(contact_id)
        gifts = detail["results"][0]["gifts"]
        if len(gifts) >= 2:
            dates = [g["gift_date"] for g in gifts if g["gift_date"]]
            assert dates == sorted(dates, reverse=True), (
                "Gifts should be returned most-recent-first"
            )
