"""
queries.py — Data query functions for the IASC Donor Analytics tool.

Each function is callable by Claude via tool use. They accept filter parameters,
build parameterized SQL queries, and return a consistent dict structure:
  {
    "results": list[dict],   # data rows
    "count":   int,          # number of matching records
    "summary": str           # human-readable description of the result set
  }

Database: SQLite at data/donors.db (resolved relative to this file's location).
All queries use sqlite3 with row_factory so rows are addressable by column name.
No pandas is used here; transformation is done in pure Python.
"""

import math
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

# Resolve DB path relative to this file so the module works regardless of cwd
DB_PATH = Path(__file__).parent.parent / "data" / "donors.db"


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------

def get_db_connection() -> sqlite3.Connection:
    """Open a read-only connection to the donor database.

    Using URI mode with mode=ro prevents accidental writes and makes the
    intent explicit to anyone reading the code.
    """
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Internal utility
# ---------------------------------------------------------------------------

def _rows_to_dicts(rows: list) -> list[dict]:
    """Convert sqlite3.Row objects to plain dicts for JSON serialisation."""
    return [dict(row) for row in rows]


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    """Return unique items while preserving first-seen order."""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _table_provenance(name: str, fields: list[str]) -> dict:
    """Describe one source table and the fields used from it."""
    return {
        "name": name,
        "fields": _dedupe_preserve_order(fields),
    }


def _filter_provenance(
    field: str,
    operator: str,
    value,
    display: Optional[str] = None,
) -> dict:
    """Describe one applied filter in a UI-friendly structure."""
    return {
        "field": field,
        "operator": operator,
        "value": value,
        "display": display or f"{field} {operator} {value}",
    }


def _build_provenance(
    tool_name: str,
    source_tables: list[dict],
    filters: Optional[list[dict]] = None,
    notes: Optional[list[str]] = None,
) -> dict:
    """Build a consistent provenance payload for downstream display."""
    return {
        "tool": tool_name,
        "source_tables": source_tables,
        "filters": filters or [],
        "notes": notes or [],
    }


# ---------------------------------------------------------------------------
# Public query functions
# ---------------------------------------------------------------------------

def search_donors(
    state: Optional[str] = None,
    city: Optional[str] = None,
    zip_prefix: Optional[str] = None,
    donor_status: Optional[str] = None,
    min_total_gifts: Optional[float] = None,
    max_total_gifts: Optional[float] = None,
    min_gift_count: Optional[int] = None,
    subscription_type: Optional[str] = None,
    subscription_status: Optional[str] = None,
    min_wealth_score: Optional[int] = None,
    last_gift_before: Optional[str] = None,
    last_gift_after: Optional[str] = None,
    min_email_open_rate: Optional[float] = None,
    has_attended_events: Optional[bool] = None,
    giving_vehicle: Optional[str] = None,
    sort_by: str = "total_gifts",
    sort_order: str = "desc",
    limit: int = 20,
) -> dict:
    """Search and filter the donor database. Returns matching contacts with key fields.

    Use this for any question about finding, filtering, or listing donors.

    Parameters
    ----------
    state : 2-letter state code (e.g., "VA", "NY", "DC")
    city : city name (partial match OK)
    zip_prefix : zip code prefix to filter by (e.g., "229" for Charlottesville)
    donor_status : one of "active", "lapsed", "prospect", "new_donor"
    min_total_gifts / max_total_gifts : filter by lifetime giving amount
    min_gift_count : minimum number of gifts
    subscription_type : "print", "digital", "both", "none"
    subscription_status : "active", "expired", "never"
    min_wealth_score : minimum WealthEngine wealth score (1-10)
    last_gift_before / last_gift_after : ISO date strings (YYYY-MM-DD)
    min_email_open_rate : minimum email open rate (0.0-1.0)
    has_attended_events : True = event_attendance_count > 0
    giving_vehicle : "check", "online", "stock", "DAF", "wire"
    sort_by : column name to sort by (default: total_gifts)
    sort_order : "asc" or "desc"
    limit : max results to return (default: 20, max: 50)
    """
    # Guard against SQL-injection via sort_by / sort_order by whitelisting
    allowed_sort_columns = {
        "total_gifts", "total_number_of_gifts", "average_gift",
        "last_gift_date", "first_gift_date", "wealth_score",
        "email_open_rate", "event_attendance_count", "contact_id",
        "last_name", "first_name",
    }
    if sort_by not in allowed_sort_columns:
        sort_by = "total_gifts"
    sort_order = "DESC" if sort_order.lower() == "desc" else "ASC"
    limit = min(int(limit), 50)

    conditions: list[str] = []
    params: list = []

    if state is not None:
        conditions.append("state = ?")
        params.append(state.upper())

    if city is not None:
        conditions.append("city LIKE ?")
        params.append(f"%{city}%")

    if zip_prefix is not None:
        conditions.append("zip_code LIKE ?")
        params.append(f"{zip_prefix}%")

    if donor_status is not None:
        conditions.append("donor_status = ?")
        params.append(donor_status)

    if min_total_gifts is not None:
        conditions.append("total_gifts >= ?")
        params.append(min_total_gifts)

    if max_total_gifts is not None:
        conditions.append("total_gifts <= ?")
        params.append(max_total_gifts)

    if min_gift_count is not None:
        conditions.append("total_number_of_gifts >= ?")
        params.append(min_gift_count)

    if subscription_type is not None:
        conditions.append("subscription_type = ?")
        params.append(subscription_type)

    if subscription_status is not None:
        conditions.append("subscription_status = ?")
        params.append(subscription_status)

    if min_wealth_score is not None:
        conditions.append("wealth_score >= ?")
        params.append(min_wealth_score)

    if last_gift_before is not None:
        conditions.append("last_gift_date < ?")
        params.append(last_gift_before)

    if last_gift_after is not None:
        conditions.append("last_gift_date > ?")
        params.append(last_gift_after)

    if min_email_open_rate is not None:
        conditions.append("email_open_rate >= ?")
        params.append(min_email_open_rate)

    if has_attended_events is True:
        conditions.append("event_attendance_count > 0")
    elif has_attended_events is False:
        conditions.append("(event_attendance_count = 0 OR event_attendance_count IS NULL)")

    if giving_vehicle is not None:
        conditions.append("giving_vehicle = ?")
        params.append(giving_vehicle)

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    sql = f"""
        SELECT
            contact_id, first_name, last_name, email,
            city, state, zip_code,
            donor_status, first_gift_date, last_gift_date,
            total_gifts, total_number_of_gifts, average_gift,
            giving_vehicle, subscription_type, subscription_status,
            email_open_rate, event_attendance_count, wealth_score
        FROM contacts
        {where_clause}
        ORDER BY {sort_by} {sort_order}
        LIMIT ?
    """
    params.append(limit)

    with get_db_connection() as conn:
        rows = conn.execute(sql, params).fetchall()

    results = _rows_to_dicts(rows)
    count = len(results)

    if count == 0:
        summary = "No donors found matching those criteria."
    else:
        summary = (
            f"Found {count} contact(s) matching the applied filters, "
            f"sorted by {sort_by} ({sort_order.lower()})."
        )
    applied_filters: list[dict] = []
    if state is not None:
        applied_filters.append(_filter_provenance("state", "=", state.upper()))
    if city is not None:
        applied_filters.append(
            _filter_provenance("city", "contains", city, f"city contains '{city}'")
        )
    if zip_prefix is not None:
        applied_filters.append(
            _filter_provenance("zip_code", "starts_with", zip_prefix, f"zip_code starts with '{zip_prefix}'")
        )
    if donor_status is not None:
        applied_filters.append(_filter_provenance("donor_status", "=", donor_status))
    if min_total_gifts is not None:
        applied_filters.append(_filter_provenance("total_gifts", ">=", min_total_gifts))
    if max_total_gifts is not None:
        applied_filters.append(_filter_provenance("total_gifts", "<=", max_total_gifts))
    if min_gift_count is not None:
        applied_filters.append(
            _filter_provenance("total_number_of_gifts", ">=", min_gift_count)
        )
    if subscription_type is not None:
        applied_filters.append(_filter_provenance("subscription_type", "=", subscription_type))
    if subscription_status is not None:
        applied_filters.append(_filter_provenance("subscription_status", "=", subscription_status))
    if min_wealth_score is not None:
        applied_filters.append(_filter_provenance("wealth_score", ">=", min_wealth_score))
    if last_gift_before is not None:
        applied_filters.append(_filter_provenance("last_gift_date", "<", last_gift_before))
    if last_gift_after is not None:
        applied_filters.append(_filter_provenance("last_gift_date", ">", last_gift_after))
    if min_email_open_rate is not None:
        applied_filters.append(
            _filter_provenance("email_open_rate", ">=", min_email_open_rate)
        )
    if has_attended_events is True:
        applied_filters.append(
            _filter_provenance(
                "event_attendance_count",
                ">",
                0,
                "event_attendance_count > 0",
            )
        )
    elif has_attended_events is False:
        applied_filters.append(
            _filter_provenance(
                "event_attendance_count",
                "=",
                0,
                "event_attendance_count = 0 or NULL",
            )
        )
    if giving_vehicle is not None:
        applied_filters.append(_filter_provenance("giving_vehicle", "=", giving_vehicle))

    provenance = _build_provenance(
        tool_name="search_donors",
        source_tables=[
            _table_provenance(
                "contacts",
                [
                    "contact_id", "first_name", "last_name", "email",
                    "city", "state", "zip_code", "donor_status",
                    "first_gift_date", "last_gift_date", "total_gifts",
                    "total_number_of_gifts", "average_gift", "giving_vehicle",
                    "subscription_type", "subscription_status",
                    "email_open_rate", "event_attendance_count",
                    "wealth_score",
                ],
            )
        ],
        filters=applied_filters,
        notes=[
            f"Sorted by {sort_by} ({sort_order.lower()}).",
            f"Limited to {limit} row(s).",
        ],
    )

    return {
        "results": results,
        "count": count,
        "summary": summary,
        "provenance": provenance,
    }


def get_donor_detail(contact_id: str) -> dict:
    """Get complete information about a single donor including gift history
    and interactions. Use when the user asks about a specific person.

    Returns the full contact record plus the last 10 gifts and last 5
    interactions so the caller has rich context without an unbounded fetch.
    """
    with get_db_connection() as conn:
        contact_row = conn.execute(
            "SELECT * FROM contacts WHERE contact_id = ?", (contact_id,)
        ).fetchone()

        if contact_row is None:
            provenance = _build_provenance(
                tool_name="get_donor_detail",
                source_tables=[
                    _table_provenance("contacts", ["contact_id"])
                ],
                filters=[_filter_provenance("contact_id", "=", contact_id)],
                notes=["No matching contact row was found."],
            )
            return {
                "results": [],
                "count": 0,
                "summary": f"No contact found with ID '{contact_id}'.",
                "provenance": provenance,
            }

        contact = dict(contact_row)

        gift_rows = conn.execute(
            """
            SELECT gift_id, gift_date, amount, gift_type, campaign
            FROM gifts
            WHERE contact_id = ?
            ORDER BY gift_date DESC
            LIMIT 10
            """,
            (contact_id,),
        ).fetchall()
        contact["gifts"] = _rows_to_dicts(gift_rows)

        interaction_rows = conn.execute(
            """
            SELECT interaction_id, interaction_date, interaction_type, details
            FROM interactions
            WHERE contact_id = ?
            ORDER BY interaction_date DESC
            LIMIT 5
            """,
            (contact_id,),
        ).fetchall()
        contact["interactions"] = _rows_to_dicts(interaction_rows)

    name = f"{contact.get('first_name', '')} {contact.get('last_name', '')}".strip()
    summary = (
        f"Detailed record for {name} (ID: {contact_id}). "
        f"Includes {len(contact['gifts'])} recent gift(s) and "
        f"{len(contact['interactions'])} recent interaction(s)."
    )
    provenance = _build_provenance(
        tool_name="get_donor_detail",
        source_tables=[
            _table_provenance("contacts", list(contact.keys())),
            _table_provenance(
                "gifts",
                ["gift_id", "gift_date", "amount", "gift_type", "campaign"],
            ),
            _table_provenance(
                "interactions",
                ["interaction_id", "interaction_date", "interaction_type", "details"],
            ),
        ],
        filters=[_filter_provenance("contact_id", "=", contact_id)],
        notes=[
            "Gift history limited to the 10 most recent rows.",
            "Interaction history limited to the 5 most recent rows.",
        ],
    )

    return {
        "results": [contact],
        "count": 1,
        "summary": summary,
        "provenance": provenance,
    }


def get_summary_statistics(
    group_by: Optional[str] = None,
    filter_status: Optional[str] = None,
    filter_state: Optional[str] = None,
) -> dict:
    """Get aggregate statistics about the donor base.

    Use for questions about totals, averages, distributions, and comparisons
    across segments.

    Parameters
    ----------
    group_by : group results by this field — one of "state", "donor_status",
               "subscription_type", "giving_vehicle"
    filter_status : only include donors with this donor_status
    filter_state : only include donors from this state
    """
    allowed_group_columns = {"state", "donor_status", "subscription_type", "giving_vehicle"}

    conditions: list[str] = []
    params: list = []

    if filter_status is not None:
        conditions.append("donor_status = ?")
        params.append(filter_status)

    if filter_state is not None:
        conditions.append("state = ?")
        params.append(filter_state.upper())

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    with get_db_connection() as conn:
        if group_by and group_by in allowed_group_columns:
            sql = f"""
                SELECT
                    {group_by} AS group_value,
                    COUNT(*) AS total_contacts,
                    SUM(CASE WHEN donor_status != 'prospect' THEN 1 ELSE 0 END) AS donor_count,
                    ROUND(SUM(COALESCE(total_gifts, 0)), 2) AS total_giving,
                    ROUND(AVG(CASE WHEN total_gifts > 0 THEN total_gifts END), 2) AS avg_lifetime_giving,
                    ROUND(AVG(COALESCE(wealth_score, 0)), 2) AS avg_wealth_score,
                    ROUND(AVG(COALESCE(email_open_rate, 0)), 4) AS avg_email_open_rate
                FROM contacts
                {where_clause}
                GROUP BY {group_by}
                ORDER BY total_giving DESC
            """
            rows = conn.execute(sql, params).fetchall()
            results = _rows_to_dicts(rows)
            count = len(results)
            summary = (
                f"Summary statistics grouped by '{group_by}' — "
                f"{count} group(s) returned."
            )
            provenance_notes = [
                f"Aggregated by {group_by}.",
                "Ordered by total_giving descending.",
            ]
            provenance_fields = [
                group_by,
                "donor_status",
                "total_gifts",
                "wealth_score",
                "email_open_rate",
            ]
        else:
            # Overall aggregate statistics (single-row result)
            sql = f"""
                SELECT
                    COUNT(*) AS total_contacts,
                    SUM(CASE WHEN donor_status != 'prospect' THEN 1 ELSE 0 END) AS total_donors,
                    SUM(CASE WHEN donor_status = 'prospect' THEN 1 ELSE 0 END) AS total_prospects,
                    SUM(CASE WHEN donor_status = 'active' THEN 1 ELSE 0 END) AS active_donors,
                    SUM(CASE WHEN donor_status = 'lapsed' THEN 1 ELSE 0 END) AS lapsed_donors,
                    ROUND(SUM(COALESCE(total_gifts, 0)), 2) AS total_giving,
                    ROUND(AVG(CASE WHEN total_gifts > 0 THEN total_gifts END), 2) AS avg_lifetime_giving,
                    MAX(total_gifts) AS max_lifetime_giving,
                    ROUND(AVG(COALESCE(wealth_score, 0)), 2) AS avg_wealth_score,
                    ROUND(AVG(COALESCE(email_open_rate, 0)), 4) AS avg_email_open_rate
                FROM contacts
                {where_clause}
            """
            row = conn.execute(sql, params).fetchone()
            results = [dict(row)] if row else []
            count = 1 if results else 0
            summary = "Overall summary statistics for the donor database."
            if filter_status or filter_state:
                parts = []
                if filter_status:
                    parts.append(f"status={filter_status}")
                if filter_state:
                    parts.append(f"state={filter_state}")
                summary += f" Filtered by: {', '.join(parts)}."
            provenance_notes = ["Overall aggregate summary across matching contacts."]
            provenance_fields = [
                "donor_status",
                "total_gifts",
                "wealth_score",
                "email_open_rate",
            ]

    applied_filters: list[dict] = []
    if filter_status is not None:
        applied_filters.append(_filter_provenance("donor_status", "=", filter_status))
    if filter_state is not None:
        applied_filters.append(_filter_provenance("state", "=", filter_state.upper()))

    provenance = _build_provenance(
        tool_name="get_summary_statistics",
        source_tables=[_table_provenance("contacts", provenance_fields)],
        filters=applied_filters,
        notes=provenance_notes,
    )

    return {
        "results": results,
        "count": count,
        "summary": summary,
        "provenance": provenance,
    }


def get_geographic_distribution(
    min_total_gifts: Optional[float] = None,
    donor_status: Optional[str] = None,
    top_n: int = 15,
) -> dict:
    """Get donor counts and total giving by state.

    Use for geographic analysis and trip planning questions. Returns the top N
    states by donor count.

    Parameters
    ----------
    min_total_gifts : only count contacts whose lifetime giving exceeds this
    donor_status : filter to one status category before aggregating
    top_n : how many states to return (default 15)
    """
    conditions: list[str] = []
    params: list = []

    if min_total_gifts is not None:
        conditions.append("total_gifts >= ?")
        params.append(min_total_gifts)

    if donor_status is not None:
        conditions.append("donor_status = ?")
        params.append(donor_status)

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(int(top_n))

    sql = f"""
        SELECT
            state,
            COUNT(*) AS donor_count,
            ROUND(SUM(COALESCE(total_gifts, 0)), 2) AS total_giving,
            ROUND(AVG(CASE WHEN total_gifts > 0 THEN total_gifts END), 2) AS avg_giving,
            MAX(total_gifts) AS max_single_donor
        FROM contacts
        {where_clause}
        GROUP BY state
        ORDER BY donor_count DESC
        LIMIT ?
    """

    with get_db_connection() as conn:
        rows = conn.execute(sql, params).fetchall()

    results = _rows_to_dicts(rows)
    count = len(results)

    if count == 0:
        summary = "No geographic data found matching those criteria."
    else:
        summary = (
            f"Geographic distribution across {count} state(s). "
            f"Top state by donor count: {results[0]['state']} "
            f"({results[0]['donor_count']} contact(s))."
        )
    applied_filters: list[dict] = []
    if min_total_gifts is not None:
        applied_filters.append(_filter_provenance("total_gifts", ">=", min_total_gifts))
    if donor_status is not None:
        applied_filters.append(_filter_provenance("donor_status", "=", donor_status))

    provenance = _build_provenance(
        tool_name="get_geographic_distribution",
        source_tables=[
            _table_provenance("contacts", ["state", "donor_status", "total_gifts"])
        ],
        filters=applied_filters,
        notes=[
            "Aggregated by state.",
            "Ordered by donor_count descending.",
            f"Limited to top {int(top_n)} state(s).",
        ],
    )

    return {
        "results": results,
        "count": count,
        "summary": summary,
        "provenance": provenance,
    }


def get_lapsed_donors(
    months_since_last_gift: int = 24,
    min_previous_total: Optional[float] = None,
    state: Optional[str] = None,
    limit: int = 20,
) -> dict:
    """Find donors who haven't given recently but have a giving history.

    Use for re-engagement and lapsed donor questions.

    Parameters
    ----------
    months_since_last_gift : how long since last gift to be considered lapsed
                             (default: 24 months)
    min_previous_total : minimum lifetime giving to include
    state : filter by state
    limit : max results (default 20)
    """
    cutoff_date = (date.today() - timedelta(days=months_since_last_gift * 30)).isoformat()

    conditions: list[str] = [
        "last_gift_date IS NOT NULL",
        "last_gift_date < ?",
        "total_number_of_gifts > 0",
    ]
    params: list = [cutoff_date]

    if min_previous_total is not None:
        conditions.append("total_gifts >= ?")
        params.append(min_previous_total)

    if state is not None:
        conditions.append("state = ?")
        params.append(state.upper())

    params.append(int(limit))

    sql = f"""
        SELECT
            contact_id, first_name, last_name, email,
            city, state, zip_code,
            donor_status, last_gift_date, first_gift_date,
            total_gifts, total_number_of_gifts, average_gift,
            wealth_score, email_open_rate, subscription_status
        FROM contacts
        WHERE {" AND ".join(conditions)}
        ORDER BY total_gifts DESC
        LIMIT ?
    """

    with get_db_connection() as conn:
        rows = conn.execute(sql, params).fetchall()

    results = _rows_to_dicts(rows)
    count = len(results)

    if count == 0:
        summary = (
            f"No lapsed donors found (last gift more than {months_since_last_gift} "
            f"months ago) matching those criteria."
        )
    else:
        summary = (
            f"Found {count} lapsed donor(s) whose last gift was more than "
            f"{months_since_last_gift} months ago, sorted by lifetime giving."
        )
    applied_filters = [
        _filter_provenance("last_gift_date", "<", cutoff_date),
        _filter_provenance("total_number_of_gifts", ">", 0),
    ]
    if min_previous_total is not None:
        applied_filters.append(_filter_provenance("total_gifts", ">=", min_previous_total))
    if state is not None:
        applied_filters.append(_filter_provenance("state", "=", state.upper()))

    provenance = _build_provenance(
        tool_name="get_lapsed_donors",
        source_tables=[
            _table_provenance(
                "contacts",
                [
                    "contact_id", "first_name", "last_name", "email",
                    "city", "state", "zip_code", "donor_status",
                    "last_gift_date", "first_gift_date", "total_gifts",
                    "total_number_of_gifts", "average_gift", "wealth_score",
                    "email_open_rate", "subscription_status",
                ],
            )
        ],
        filters=applied_filters,
        notes=[
            f"Lapsed window set to more than {months_since_last_gift} month(s) since last gift.",
            "Ordered by total_gifts descending.",
            f"Limited to {int(limit)} row(s).",
        ],
    )

    return {
        "results": results,
        "count": count,
        "summary": summary,
        "provenance": provenance,
    }


def get_prospects_by_potential(
    has_subscription: Optional[bool] = None,
    min_wealth_score: Optional[int] = None,
    min_email_open_rate: Optional[float] = None,
    has_attended_events: Optional[bool] = None,
    state: Optional[str] = None,
    limit: int = 20,
) -> dict:
    """Find prospects (non-donors) ranked by engagement signals and wealth.

    Use for prospecting and lead generation questions. Prospects are contacts
    with donor_status = 'prospect' (i.e., they have never donated).

    The composite engagement score used for ranking is computed in SQL as:
        (wealth_score / 10.0) * 0.5 + email_open_rate * 0.5
    This is a lightweight approximation; plan_fundraising_trip uses a richer
    formula when you need a full prioritised call list.

    Parameters
    ----------
    has_subscription : True = subscription_status = 'active'
    min_wealth_score : minimum wealth score (1-10)
    min_email_open_rate : minimum email open rate (0.0-1.0)
    has_attended_events : True = at least one event attended
    state : filter by state
    limit : max results (default 20)
    """
    conditions: list[str] = ["donor_status = 'prospect'"]
    params: list = []

    if has_subscription is True:
        conditions.append("subscription_status = 'active'")
    elif has_subscription is False:
        conditions.append("subscription_status != 'active'")

    if min_wealth_score is not None:
        conditions.append("wealth_score >= ?")
        params.append(min_wealth_score)

    if min_email_open_rate is not None:
        conditions.append("email_open_rate >= ?")
        params.append(min_email_open_rate)

    if has_attended_events is True:
        conditions.append("event_attendance_count > 0")
    elif has_attended_events is False:
        conditions.append("(event_attendance_count = 0 OR event_attendance_count IS NULL)")

    if state is not None:
        conditions.append("state = ?")
        params.append(state.upper())

    params.append(int(limit))

    sql = f"""
        SELECT
            contact_id, first_name, last_name, email,
            city, state, zip_code,
            donor_status, subscription_type, subscription_status,
            email_open_rate, event_attendance_count, wealth_score,
            last_email_click_date
        FROM contacts
        WHERE {" AND ".join(conditions)}
        ORDER BY
            (COALESCE(wealth_score, 5) / 10.0) * 0.5
            + COALESCE(email_open_rate, 0) * 0.5 DESC
        LIMIT ?
    """

    with get_db_connection() as conn:
        rows = conn.execute(sql, params).fetchall()

    results = _rows_to_dicts(rows)
    count = len(results)

    if count == 0:
        summary = "No prospects found matching those criteria."
    else:
        summary = (
            f"Found {count} prospect(s) ranked by composite engagement "
            f"(wealth + email open rate)."
        )
    applied_filters = [_filter_provenance("donor_status", "=", "prospect")]
    if has_subscription is True:
        applied_filters.append(_filter_provenance("subscription_status", "=", "active"))
    elif has_subscription is False:
        applied_filters.append(
            _filter_provenance("subscription_status", "!=", "active")
        )
    if min_wealth_score is not None:
        applied_filters.append(_filter_provenance("wealth_score", ">=", min_wealth_score))
    if min_email_open_rate is not None:
        applied_filters.append(
            _filter_provenance("email_open_rate", ">=", min_email_open_rate)
        )
    if has_attended_events is True:
        applied_filters.append(
            _filter_provenance(
                "event_attendance_count",
                ">",
                0,
                "event_attendance_count > 0",
            )
        )
    elif has_attended_events is False:
        applied_filters.append(
            _filter_provenance(
                "event_attendance_count",
                "=",
                0,
                "event_attendance_count = 0 or NULL",
            )
        )
    if state is not None:
        applied_filters.append(_filter_provenance("state", "=", state.upper()))

    provenance = _build_provenance(
        tool_name="get_prospects_by_potential",
        source_tables=[
            _table_provenance(
                "contacts",
                [
                    "contact_id", "first_name", "last_name", "email",
                    "city", "state", "zip_code", "donor_status",
                    "subscription_type", "subscription_status",
                    "email_open_rate", "event_attendance_count",
                    "wealth_score", "last_email_click_date",
                ],
            )
        ],
        filters=applied_filters,
        notes=[
            "Ranked by a composite engagement score using wealth_score and email_open_rate.",
            f"Limited to {int(limit)} row(s).",
        ],
    )

    return {
        "results": results,
        "count": count,
        "summary": summary,
        "provenance": provenance,
    }


def plan_fundraising_trip(
    target_city: Optional[str] = None,
    target_state: Optional[str] = None,
    target_zip_prefix: Optional[str] = None,
    min_total_gifts: Optional[float] = None,
    include_prospects: bool = True,
    include_lapsed: bool = True,
    limit: int = 10,
) -> dict:
    """Find the best contacts to meet during a fundraising trip to a specific area.

    Ranks contacts by a composite score that weights giving history, wealth,
    recency, engagement, and subscription status. The score is computed in
    Python after fetching candidates from the database so the weighting logic
    is transparent and easy to adjust.

    Composite score formula (all components normalised to 0-1):
        score = 0.30 * normalised_total_gifts
              + 0.20 * normalised_wealth_score
              + 0.20 * recency_score
              + 0.15 * engagement_score
              + 0.15 * subscription_score

    Parameters
    ----------
    target_city : city name for the trip
    target_state : state code for the trip (e.g., "NY")
    target_zip_prefix : narrow to a specific zip prefix (e.g., "100" for Manhattan)
    min_total_gifts : only include contacts above this giving threshold
    include_prospects : include non-donors with strong engagement signals
    include_lapsed : include donors who haven't given recently
    limit : number of contacts to return (default 10)
    """
    if not (target_city or target_state or target_zip_prefix):
        provenance = _build_provenance(
            tool_name="plan_fundraising_trip",
            source_tables=[],
            notes=["No query was run because no geographic filter was provided."],
        )
        return {
            "results": [],
            "count": 0,
            "summary": (
                "Please specify at least one geographic filter: "
                "target_city, target_state, or target_zip_prefix."
            ),
            "provenance": provenance,
        }

    conditions: list[str] = []
    params: list = []

    if target_state is not None:
        conditions.append("state = ?")
        params.append(target_state.upper())

    if target_city is not None:
        conditions.append("city LIKE ?")
        params.append(f"%{target_city}%")

    if target_zip_prefix is not None:
        conditions.append("zip_code LIKE ?")
        params.append(f"{target_zip_prefix}%")

    if min_total_gifts is not None:
        conditions.append("(total_gifts >= ? OR donor_status = 'prospect')")
        params.append(min_total_gifts)

    # Build status filter
    status_filters: list[str] = []
    if include_lapsed:
        status_filters.append("donor_status = 'lapsed'")
    if include_prospects:
        status_filters.append("donor_status = 'prospect'")
    # Always include active donors and new donors
    status_filters.append("donor_status = 'active'")
    status_filters.append("donor_status = 'new_donor'")

    conditions.append(f"({' OR '.join(status_filters)})")

    where_clause = "WHERE " + " AND ".join(conditions)

    sql = f"""
        SELECT
            contact_id, first_name, last_name, email,
            city, state, zip_code,
            donor_status, first_gift_date, last_gift_date,
            total_gifts, total_number_of_gifts, average_gift,
            wealth_score, email_open_rate, event_attendance_count,
            subscription_status, giving_vehicle
        FROM contacts
        {where_clause}
    """

    with get_db_connection() as conn:
        rows = conn.execute(sql, params).fetchall()

    candidates = _rows_to_dicts(rows)

    if not candidates:
        location_desc = " / ".join(
            filter(None, [target_city, target_state, target_zip_prefix])
        )
        applied_filters: list[dict] = []
        if target_state is not None:
            applied_filters.append(_filter_provenance("state", "=", target_state.upper()))
        if target_city is not None:
            applied_filters.append(
                _filter_provenance("city", "contains", target_city, f"city contains '{target_city}'")
            )
        if target_zip_prefix is not None:
            applied_filters.append(
                _filter_provenance(
                    "zip_code",
                    "starts_with",
                    target_zip_prefix,
                    f"zip_code starts with '{target_zip_prefix}'",
                )
            )
        return {
            "results": [],
            "count": 0,
            "summary": f"No contacts found in the target area: {location_desc}.",
            "provenance": _build_provenance(
                tool_name="plan_fundraising_trip",
                source_tables=[
                    _table_provenance(
                        "contacts",
                        [
                            "contact_id", "first_name", "last_name", "email",
                            "city", "state", "zip_code", "donor_status",
                            "first_gift_date", "last_gift_date", "total_gifts",
                            "total_number_of_gifts", "average_gift", "wealth_score",
                            "email_open_rate", "event_attendance_count",
                            "subscription_status", "giving_vehicle",
                        ],
                    )
                ],
                filters=applied_filters,
                notes=["No candidates matched the requested geography."],
            ),
        }

    # ------------------------------------------------------------------
    # Composite score computation
    # ------------------------------------------------------------------
    # We need the global max total_gifts to normalise on a log scale.
    # Compute it across the candidate set (not the whole DB) so the
    # relative ranking reflects the local pool.
    total_gifts_values = [c["total_gifts"] for c in candidates if c["total_gifts"]]
    max_total_gifts = max(total_gifts_values) if total_gifts_values else 1.0

    today = date.today()

    for c in candidates:
        # 1. Normalised total gifts (log scale to compress large outliers)
        tg = c.get("total_gifts") or 0.0
        if tg > 0 and max_total_gifts > 0:
            norm_gifts = math.log(tg + 1) / math.log(max_total_gifts + 1)
        else:
            norm_gifts = 0.0

        # 2. Normalised wealth score (unknown → neutral 0.5)
        ws = c.get("wealth_score")
        norm_wealth = (ws / 10.0) if ws is not None else 0.5

        # 3. Recency score based on last gift date
        last_gift_str = c.get("last_gift_date")
        if last_gift_str:
            try:
                last_gift = date.fromisoformat(last_gift_str)
                days_ago = (today - last_gift).days
                if days_ago <= 365:
                    recency = 1.0
                elif days_ago <= 730:
                    recency = 0.7
                elif days_ago <= 5 * 365:
                    recency = 0.5
                else:
                    recency = 0.2
            except ValueError:
                recency = 0.0
        else:
            # Prospect with no gift history — reward recent email activity
            last_click_str = c.get("last_email_click_date") if "last_email_click_date" in (c or {}) else None
            if last_click_str:
                try:
                    last_click = date.fromisoformat(last_click_str)
                    if (today - last_click).days <= 365:
                        recency = 0.3
                    else:
                        recency = 0.1
                except ValueError:
                    recency = 0.1
            else:
                recency = 0.1

        # 4. Engagement score: blend email open rate and event attendance
        open_rate = c.get("email_open_rate") or 0.0
        events = c.get("event_attendance_count") or 0
        engagement = min(1.0, open_rate * 0.5 + (events / 12.0) * 0.5)

        # 5. Subscription score
        sub_status = c.get("subscription_status") or "never"
        if sub_status == "active":
            sub_score = 1.0
        elif sub_status == "expired":
            sub_score = 0.5
        else:
            sub_score = 0.0

        c["score"] = round(
            0.30 * norm_gifts
            + 0.20 * norm_wealth
            + 0.20 * recency
            + 0.15 * engagement
            + 0.15 * sub_score,
            4,
        )

    # Sort descending by score, then slice to limit
    candidates.sort(key=lambda x: x["score"], reverse=True)
    results = candidates[:limit]
    count = len(results)

    location_desc = " / ".join(
        filter(None, [target_city, target_state, target_zip_prefix])
    )
    summary = (
        f"Top {count} contact(s) to prioritise for a fundraising trip to "
        f"{location_desc}, ranked by composite score (giving history, "
        f"wealth, recency, engagement, subscription)."
    )
    included_statuses: list[str] = []
    if include_lapsed:
        included_statuses.append("lapsed")
    if include_prospects:
        included_statuses.append("prospect")
    included_statuses.extend(["active", "new_donor"])

    applied_filters: list[dict] = []
    if target_state is not None:
        applied_filters.append(_filter_provenance("state", "=", target_state.upper()))
    if target_city is not None:
        applied_filters.append(
            _filter_provenance("city", "contains", target_city, f"city contains '{target_city}'")
        )
    if target_zip_prefix is not None:
        applied_filters.append(
            _filter_provenance(
                "zip_code",
                "starts_with",
                target_zip_prefix,
                f"zip_code starts with '{target_zip_prefix}'",
            )
        )
    if min_total_gifts is not None:
        applied_filters.append(
            _filter_provenance(
                "total_gifts",
                ">=",
                min_total_gifts,
                f"total_gifts >= {min_total_gifts} for donors; prospects allowed through",
            )
        )
    applied_filters.append(
        _filter_provenance(
            "donor_status",
            "IN",
            included_statuses,
            f"donor_status in {', '.join(included_statuses)}",
        )
    )

    provenance = _build_provenance(
        tool_name="plan_fundraising_trip",
        source_tables=[
            _table_provenance(
                "contacts",
                [
                    "contact_id", "first_name", "last_name", "email",
                    "city", "state", "zip_code", "donor_status",
                    "first_gift_date", "last_gift_date", "total_gifts",
                    "total_number_of_gifts", "average_gift", "wealth_score",
                    "email_open_rate", "event_attendance_count",
                    "subscription_status", "giving_vehicle",
                ],
            )
        ],
        filters=applied_filters,
        notes=[
            "Ranked by a composite score using giving history, wealth, recency, engagement, and subscription.",
            f"Limited to top {int(limit)} contact(s).",
        ],
    )

    return {
        "results": results,
        "count": count,
        "summary": summary,
        "provenance": provenance,
    }
