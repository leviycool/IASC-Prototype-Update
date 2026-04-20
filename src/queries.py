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
from contextvars import ContextVar
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

# Resolve DB path relative to this file so the module works regardless of cwd
DB_PATH = Path(__file__).parent.parent / "data" / "donors.db"
ACTIVE_DB_PATH: ContextVar[Path] = ContextVar("ACTIVE_DB_PATH", default=DB_PATH)


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------

def get_db_connection() -> sqlite3.Connection:
    """Open a read-only connection to the donor database.

    Using URI mode with mode=ro prevents accidental writes and makes the
    intent explicit to anyone reading the code.
    """
    active_db_path = Path(ACTIVE_DB_PATH.get())
    conn = sqlite3.connect(f"file:{active_db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def set_active_db_path(db_path: str | Path):
    """Set the donor database path for the current execution context."""
    return ACTIVE_DB_PATH.set(Path(db_path))


def reset_active_db_path(token) -> None:
    """Restore the prior donor database path for the current execution context."""
    ACTIVE_DB_PATH.reset(token)


def get_active_db_path() -> Path:
    """Return the donor database path for the current execution context."""
    return Path(ACTIVE_DB_PATH.get())


# ---------------------------------------------------------------------------
# Internal utility
# ---------------------------------------------------------------------------

def _rows_to_dicts(rows: list) -> list[dict]:
    """Convert sqlite3.Row objects to plain dicts for JSON serialisation."""
    return [dict(row) for row in rows]


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
        ORDER BY {sort_by} {sort_order}, last_name ASC, first_name ASC, contact_id ASC
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

    return {"results": results, "count": count, "summary": summary}


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
            return {
                "results": [],
                "count": 0,
                "summary": f"No contact found with ID '{contact_id}'.",
            }

        contact = dict(contact_row)

        gift_rows = conn.execute(
            """
            SELECT gift_id, gift_date, amount, gift_type, campaign
            FROM gifts
            WHERE contact_id = ?
            ORDER BY gift_date DESC, gift_id DESC
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
            ORDER BY interaction_date DESC, interaction_id DESC
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

    return {"results": [contact], "count": 1, "summary": summary}


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
                ORDER BY total_giving DESC, group_value ASC
            """
            rows = conn.execute(sql, params).fetchall()
            results = _rows_to_dicts(rows)
            count = len(results)
            summary = (
                f"Summary statistics grouped by '{group_by}' — "
                f"{count} group(s) returned."
            )
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

    return {"results": results, "count": count, "summary": summary}


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
        ORDER BY donor_count DESC, state ASC
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

    return {"results": results, "count": count, "summary": summary}


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
        ORDER BY total_gifts DESC, last_gift_date DESC, last_name ASC, first_name ASC, contact_id ASC
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

    return {"results": results, "count": count, "summary": summary}


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
            + COALESCE(email_open_rate, 0) * 0.5 DESC,
            last_name ASC,
            first_name ASC,
            contact_id ASC
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

    return {"results": results, "count": count, "summary": summary}


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
        return {
            "results": [],
            "count": 0,
            "summary": (
                "Please specify at least one geographic filter: "
                "target_city, target_state, or target_zip_prefix."
            ),
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
        return {
            "results": [],
            "count": 0,
            "summary": f"No contacts found in the target area: {location_desc}.",
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
    candidates.sort(
        key=lambda x: (
            -(x.get("score") or 0.0),
            x.get("last_name") or "",
            x.get("first_name") or "",
            x.get("contact_id") or "",
        )
    )
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

    return {"results": results, "count": count, "summary": summary}
