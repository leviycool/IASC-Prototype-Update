"""
generate_mock_data.py
=====================
Generates a synthetic donor database for the IASC Donor Analytics prototype.
All records are fictional; no real PII is used.

Default run (5,000 contacts, SQLite output):
    python data/generate_mock_data.py

Examples:
    python data/generate_mock_data.py --num-contacts 500 --seed 99
    python data/generate_mock_data.py --num-contacts 5000 --csv --output data/donors.csv
    python data/generate_mock_data.py --prospect-pct 0.60 --active-pct 0.07

Requires: Python 3.11+ standard library only (no third-party packages).
"""

import argparse
import csv
import math
import random
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Name lists — diverse first and last names, no faker required
# ---------------------------------------------------------------------------
FIRST_NAMES = [
    "James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael",
    "Linda", "David", "Barbara", "William", "Elizabeth", "Richard", "Susan",
    "Joseph", "Jessica", "Thomas", "Sarah", "Charles", "Karen", "Christopher",
    "Lisa", "Daniel", "Nancy", "Matthew", "Betty", "Anthony", "Margaret",
    "Mark", "Sandra", "Donald", "Ashley", "Steven", "Dorothy", "Paul",
    "Kimberly", "Andrew", "Emily", "Kenneth", "Donna", "George", "Michelle",
    "Joshua", "Carol", "Kevin", "Amanda", "Brian", "Melissa", "Edward",
    "Deborah", "Ronald", "Stephanie", "Timothy", "Rebecca", "Jason", "Sharon",
    "Jeffrey", "Laura", "Ryan", "Cynthia", "Jacob", "Kathleen", "Gary", "Amy",
    "Nicholas", "Angela", "Eric", "Shirley", "Jonathan", "Anna", "Stephen",
    "Brenda", "Larry", "Pamela", "Justin", "Emma", "Scott", "Nicole",
    "Brandon", "Helen", "Raymond", "Samantha", "Frank", "Katherine", "Gregory",
    "Christine", "Benjamin", "Debra", "Samuel", "Rachel", "Carolyn", "Patrick",
    "Janet", "Alexander", "Catherine", "Jack", "Frances", "Dennis", "Ann",
    "Jerry", "Joyce", "Tyler", "Diana", "Aaron", "Alice", "Jose", "Julie",
    "Adam", "Heather", "Nathan", "Teresa", "Henry", "Gloria", "Douglas",
    "Evelyn", "Zachary", "Jean", "Peter", "Cheryl", "Kyle", "Mildred",
    "Walter", "Ethan", "Joan", "Jeremy", "Andrea", "Harold", "Keith",
    "Diane", "Christian", "Rose", "Roger", "Janice", "Terry", "Julia", "Sean",
    "Grace", "Austin", "Judy", "Gerald", "Victoria", "Carl", "Kelly",
    "Arthur", "Christina", "Lawrence", "Dylan", "Ruth", "Jesse", "Lauren",
    "Bryan", "Hazel", "Joe", "Amber", "Jordan", "Marilyn", "Billy",
    "Danielle", "Bruce", "Beverly", "Albert", "Theresa", "Willie", "Denise",
    "Gabriel", "Logan", "Roy", "Crystal", "Alan", "Tammy", "Juan", "Irene",
    "Wayne", "Lori", "Eugene", "Tiffany", "Louis", "Hannah", "Randy",
    "Kathryn", "Vincent", "Peggy", "Russell", "Sara", "Bobby", "Bettye",
    "Philip", "Jacqueline", "Johnny", "Wanda", "Bradley", "Norma", "Sophia",
    "Wei", "Priya", "Aisha", "Marco", "Elena", "Yuki", "Rajesh", "Fatima",
    "Lena", "Carlos", "Mei", "Andre", "Nadia", "Ibrahim", "Sofia", "Hiroshi",
    "Amara", "Diego", "Yuna",
]

LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
    "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark",
    "Ramirez", "Lewis", "Robinson", "Walker", "Young", "Allen", "King",
    "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores", "Green",
    "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell", "Mitchell",
    "Carter", "Roberts", "Chen", "Kim", "Patel", "Kumar", "Singh", "Zhang",
    "Wang", "Liu", "Gupta", "Sharma", "Okafor", "Mensah", "Diallo", "Mbeki",
    "Tanaka", "Nakamura", "Yamamoto", "Sato", "Cohen", "Goldstein", "Shapiro",
    "Weinstein", "OBrien", "Murphy", "Walsh", "Kelly", "Sullivan", "McCarthy",
    "Murray", "Fitzgerald", "Burke",
]

# ---------------------------------------------------------------------------
# Professional titles — simulating Salesforce data entry patterns
# ---------------------------------------------------------------------------
TITLES = [
    "Professor", "Associate Professor", "Assistant Professor", "Emeritus Professor",
    "Attorney", "Partner", "Counsel", "Judge", "Dr.", "Physician",
    "VP", "SVP", "EVP", "CEO", "CFO", "COO", "President", "Director", "Executive Director",
    "Retired", "Retired Professor", "Retired Attorney",
    "Board Member", "Trustee", "Pastor", "Reverend", "Dean", "Provost",
]

# ---------------------------------------------------------------------------
# Biographical content pools — staff-entered research notes
# ---------------------------------------------------------------------------
BIOGRAPHIES_POOL = [
    "Professor of English at UVA; longtime supporter of humanities scholarship.",
    "Retired attorney; served on Foundation board 2010-2018.",
    "Emeritus professor of sociology at Georgetown; founding donor to the Institute.",
    "Physician and philanthropist; supports humanities research as a counterweight to STEM focus.",
    "Former partner at Sullivan & Cromwell; active in arts and cultural philanthropy.",
    "Retired federal judge; supporter of institutions that bridge law and culture.",
    "Professor of religious studies; author of three books on American evangelical culture.",
    "Dean emerita of arts and sciences at the University of Virginia.",
    "Investor and arts patron; serves on boards of several cultural institutions.",
    "Retired diplomat; supporter of cultural exchange programs and international scholarship.",
    "Professor of political philosophy; longtime reader of The Hedgehog Review.",
    "Retired hospital administrator; supporter of humanities education in medical training.",
    "Attorney specializing in philanthropy law; advises several family foundations.",
    "Technology entrepreneur; passionate about the role of the humanities in civic life.",
    "Professor of American history; consulting editor for The Hedgehog Review.",
]

BUSINESS_AFFILIATIONS_POOL = [
    "Board of Directors, Charlottesville Symphony Orchestra",
    "Partner, Sullivan & Cromwell LLP",
    "Advisory Board, Virginia Foundation for the Humanities",
    "Board of Trustees, Shenandoah Valley Bach Festival",
    "Managing Director, Cornerstone Capital Advisors",
    "Senior Partner, Bowles Rice LLP",
    "Board of Directors, United Way of Greater Charlottesville",
    "Advisory Council, American Enterprise Institute",
    "Board Member, National Endowment for the Humanities Advisory Board",
    "Director, Monticello Foundation",
    "Board of Trustees, Colonial Williamsburg Foundation",
]

COMMUNITY_AFFILIATIONS_POOL = [
    "Rotary Club of Charlottesville; UVA Alumni Association",
    "Junior League of Richmond; Arts Council of Greater Richmond",
    "Charlottesville Area Community Foundation",
    "Virginia Humanities Council; Albemarle County Historical Society",
    "National Trust for Historic Preservation; Preservation Virginia",
    "St. Anne's Parish, Charlottesville; Piedmont Environmental Council",
    "Harvard Club of Washington DC; Kennedy Center Patron",
    "UVA Darden School Foundation Board; Charlottesville Area Chamber of Commerce",
]

EXPERTISE_POOL = [
    "Cultural criticism, higher education policy",
    "Religious history, Southern literature",
    "Sociology of religion, nonprofit management",
    "American intellectual history, political philosophy",
    "Philanthropy law, estate planning",
    "Medical humanities, bioethics",
    "Environmental history, Appalachian studies",
    "Race and ethnicity in American culture",
    "Higher education administration, faculty governance",
    "Cultural economics, arts philanthropy",
    "Technology ethics, digital humanities",
    "International development, civil society",
]

# ---------------------------------------------------------------------------
# Lead source pool and weights
# ---------------------------------------------------------------------------
LEAD_SOURCES = [
    "Hedgehog Review", "Event", "Board Referral", "Website",
    "Email Campaign", "Direct Mail", "Other", None,
]
LEAD_SOURCE_WEIGHTS = [35, 12, 8, 10, 15, 10, 8, 2]

# ---------------------------------------------------------------------------
# Communication preference pools
# ---------------------------------------------------------------------------
PREFERRED_PHONES = ["Home", "Mobile", "Work", None]
PREFERRED_PHONE_WEIGHTS = [10, 15, 5, 70]

PREFERRED_EMAILS = ["Personal", "Work", None]
PREFERRED_EMAIL_WEIGHTS = [20, 15, 65]

# ---------------------------------------------------------------------------
# Institute status pool and weights (weighted to produce ~0.3% Board, ~1% Fellow, etc.)
# ---------------------------------------------------------------------------
INSTITUTE_STATUSES = ["Board Member", "Fellow", "Affiliate", "Friend", "None"]
INSTITUTE_STATUS_WEIGHTS = [3, 10, 30, 100, 857]

# ---------------------------------------------------------------------------
# Geographic configuration
# State weights → cumulative probability used with random.random()
# ---------------------------------------------------------------------------

# Each entry: (state, weight, zip_prefix)
# Zip prefixes chosen for realism (see CLAUDE.md for rationale).
GEO_CONFIG = [
    # (state, weight, [zip_prefixes])
    ("VA", 20, ["229", "220", "230"]),   # Virginia — IASC home base
    ("NY", 15, ["100", "101", "112"]),   # NYC metro
    ("DC",  7, ["200", "202", "203"]),   # Washington DC
    ("MD",  5, ["207", "208", "209"]),   # Maryland suburbs
    ("MA",  6, ["021", "022", "024"]),   # Boston
    ("IL",  5, ["606", "607", "608"]),   # Chicago
    ("CA",  8, ["900", "941", "945"]),   # LA / SF
    ("TX",  5, ["770", "782", "787"]),   # Houston / Austin
    ("FL",  4, ["331", "332", "337"]),   # Miami / Tampa
    ("PA",  4, ["191", "192", "193"]),   # Philadelphia
    ("OH",  3, ["432", "440", "441"]),   # Columbus / Cleveland
    ("GA",  3, ["303", "304", "305"]),   # Atlanta
    ("NC",  3, ["275", "277", "282"]),   # Raleigh / Charlotte
    ("WA",  3, ["980", "981", "982"]),   # Seattle
    ("CO",  2, ["800", "801", "802"]),   # Denver
    ("MN",  2, ["550", "551", "554"]),   # Minneapolis
    ("MO",  1, ["631", "641", "647"]),   # St. Louis / KC
    ("AZ",  1, ["850", "852", "853"]),   # Phoenix
    ("TN",  1, ["370", "371", "372"]),   # Nashville
    ("NJ",  1, ["070", "071", "080"]),   # New Jersey
]

# Unpack for weighted selection
_GEO_STATES  = [g[0] for g in GEO_CONFIG]
_GEO_WEIGHTS = [g[1] for g in GEO_CONFIG]
_GEO_ZIPS    = [g[2] for g in GEO_CONFIG]
_GEO_TOTAL   = sum(_GEO_WEIGHTS)

# ---------------------------------------------------------------------------
# Donor-status weights — realistic for a small nonprofit
# ---------------------------------------------------------------------------
STATUS_CONFIG = [
    ("prospect",        55),
    ("lapsed",          25),
    ("active",           8),
    ("new_donor",        5),
    ("subscriber_only",  7),
]

# ---------------------------------------------------------------------------
# Notes pool — ~30% of contacts get one
# ---------------------------------------------------------------------------
NOTES_POOL = [
    "Met at conference 2019",
    "Board member referral",
    "Prefers email contact",
    "Longtime subscriber",
    "Interested in planned giving",
    "Responded to Year-End Appeal",
    "Former colleague of board member",
    "Strong interest in cultural sociology",
    "Subscriber since inception",
    "Met at annual gala",
    "Prefers phone contact",
    "Potential major gift prospect",
    "Works in philanthropic advising",
    "Gave stock gift in 2021",
    "Known DAF holder at Fidelity Charitable",
    "Attended homecoming reception",
    "Connected through local arts community",
    "Interested in naming opportunity",
    "Legacy Society prospect",
    "Loyal Annual Fund donor",
]

# Campaign names used in the gifts table
CAMPAIGNS = [
    "Annual Fund 2020",
    "Annual Fund 2021",
    "Annual Fund 2022",
    "Annual Fund 2023",
    "Year-End Appeal 2021",
    "Year-End Appeal 2022",
    "Year-End Appeal 2023",
    "Year-End Appeal 2024",
    "Spring Gala 2022",
    "Spring Gala 2023",
    "Spring Appeal 2022",
    "Spring Appeal 2023",
    "Spring Appeal 2024",
    "Major Gift Initiative 2022",
    "Planned Giving Society",
    None,  # ungifted / unrestricted
]

GIFT_TYPES = ["one_time", "recurring", "planned_giving", "event"]
# Weights for gift_type — most gifts are one_time or recurring
GIFT_TYPE_WEIGHTS = [55, 30, 5, 10]

GIVING_VEHICLES = ["check", "online", "stock", "DAF", "wire"]
GIVING_VEHICLE_WEIGHTS = [30, 45, 10, 10, 5]

INTERACTION_TYPES = [
    "email_open",
    "email_click",
    "event_attended",
    "meeting",
    "phone_call",
    "mail_sent",
]


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def random_date(start: date, end: date) -> date:
    """Return a uniformly random date in [start, end]."""
    delta = (end - start).days
    if delta <= 0:
        return start
    return start + timedelta(days=random.randint(0, delta))


def year_end_biased_date(start: date, end: date) -> date:
    """
    Return a date biased toward November–December (year-end giving season).
    70% of the time pick a month in [10, 12]; otherwise pick any month.
    """
    year = random.randint(start.year, end.year)
    if random.random() < 0.70:
        month = random.choice([10, 11, 12])
    else:
        month = random.randint(1, 9)
    day = random.randint(1, 28)
    candidate = date(year, month, day)
    # Clamp to [start, end]
    if candidate < start:
        candidate = start
    if candidate > end:
        candidate = end
    return candidate


def weighted_choice(population: list, weights: list):
    """Simple weighted choice without numpy."""
    total = sum(weights)
    r = random.random() * total
    cumulative = 0.0
    for item, w in zip(population, weights):
        cumulative += w
        if r <= cumulative:
            return item
    return population[-1]


def pick_geo():
    """Return (state, zip_code) using configured geographic weights."""
    r = random.random() * _GEO_TOTAL
    cumulative = 0.0
    for state, weight, prefixes in GEO_CONFIG:
        cumulative += weight
        if r <= cumulative:
            prefix = random.choice(prefixes)
            suffix = f"{random.randint(0, 99):02d}"
            zip_code = prefix + suffix
            return state, zip_code
    # Fallback (should not happen)
    return "VA", "22901"


def generate_contact_id() -> str:
    """
    Generate a Salesforce-style 18-character contact ID.
    Format: '003XX00000' + 8 random alphanumeric characters.
    """
    chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    suffix = "".join(random.choices(chars, k=8))
    return f"003XX00000{suffix}"


def round_to_nice_amount(amount: float) -> float:
    """
    Snap a raw dollar amount to a psychologically realistic gift value.

    Real donors write round-number checks: $25, $50, $100, $500, $1,000.
    The rounding granularity scales with the gift size so that small gifts
    land on $5 increments and large gifts on $1,000 increments.
    """
    if amount < 50:
        # Round to nearest $5 (e.g. $20, $25, $30, $35 ...)
        return max(20.0, round(amount / 5) * 5)
    elif amount < 250:
        # Round to nearest $25 (e.g. $50, $75, $100, $125 ...)
        return round(amount / 25) * 25
    elif amount < 1_000:
        # Round to nearest $50 (e.g. $250, $300, $350 ...)
        return round(amount / 50) * 50
    elif amount < 10_000:
        # Round to nearest $100 (e.g. $1,000, $1,100, $2,500 ...)
        return round(amount / 100) * 100
    elif amount < 100_000:
        # Round to nearest $1,000 (e.g. $10,000, $15,000 ...)
        return round(amount / 1_000) * 1_000
    else:
        # Round to nearest $5,000 (e.g. $100,000, $250,000 ...)
        return round(amount / 5_000) * 5_000


def power_law_total_gifts_v2() -> float:
    """
    Gift distribution calibrated for a small nonprofit.
    For ~5000 contacts targets approximately:
    - ~15 major donors (>$100K)
    - ~25 significant donors ($10K-$100K)
    - ~100 mid-level donors ($1K-$10K)
    - ~400 small donors ($100-$1K)
    - remaining small donors ($20-$100)
    Minimum gift is $20; all totals are snapped to round numbers.
    """
    r = random.random()
    if r < 0.006:
        lo, hi = 100_000, 2_000_000
    elif r < 0.016:
        lo, hi = 10_000, 100_000
    elif r < 0.056:
        lo, hi = 1_000, 10_000
    elif r < 0.216:
        lo, hi = 100, 1_000
    else:
        lo, hi = 20, 100
    log_amount = random.uniform(math.log(lo), math.log(hi))
    return round_to_nice_amount(math.exp(log_amount))


def n_gifts_for_total(total: float) -> int:
    """
    Choose number of gifts roughly correlated with total giving level.
    Larger donors tend to have more gifts (more giving history).
    """
    if total < 500:
        return random.randint(1, 5)
    elif total < 5_000:
        return random.randint(2, 15)
    elif total < 50_000:
        return random.randint(5, 30)
    elif total < 500_000:
        return random.randint(10, 50)
    else:
        return random.randint(20, 60)


def wealth_score_for_total(total: float) -> int | None:
    """
    Return a 1–10 wealth score loosely correlated with total gifts.
    Returns None for ~35% of donors (industry-average WealthEngine no-match rate).
    """
    if random.random() < 0.35:  # industry average no-match rate for small nonprofits
        return None
    if total < 500:
        base = random.randint(1, 4)
    elif total < 5_000:
        base = random.randint(2, 6)
    elif total < 50_000:
        base = random.randint(4, 8)
    elif total < 500_000:
        base = random.randint(6, 10)
    else:
        base = random.randint(8, 10)
    # Add a small random jitter so it's not perfectly correlated
    return max(1, min(10, base + random.randint(-1, 1)))


def derive_p2g_score(total_gifts: float | None, donor_status: str) -> int | None:
    """
    Return a 1–100 propensity-to-give score, loosely correlated with giving.
    NULL for ~60% of contacts (WealthEngine screening not run on every record).
    """
    if random.random() < 0.60:
        return None
    # Active donors and major givers skew high
    if total_gifts is None:
        base = random.randint(1, 40)
    elif total_gifts >= 100_000:
        base = random.randint(70, 99)
    elif total_gifts >= 10_000:
        base = random.randint(50, 85)
    elif total_gifts >= 1_000:
        base = random.randint(30, 70)
    elif total_gifts >= 100:
        base = random.randint(15, 50)
    else:
        base = random.randint(5, 30)
    # Status bonus: active donors get bumped up
    if donor_status == "active":
        base = min(99, base + random.randint(5, 15))
    return max(1, min(99, base + random.randint(-5, 5)))


def derive_gift_capacity_rating(p2g_score: int | None, wealth_score: int | None) -> str | None:
    """
    Categorical gift capacity rating consistent with p2g_score and wealth_score.
    NULL for ~60% of contacts (mirrors WealthEngine coverage).
    """
    if p2g_score is None:
        return None
    # Use combined signal; wealth_score may be NULL (treat as mid-range if so)
    ws = wealth_score if wealth_score is not None else 5
    combined = (p2g_score / 100) * 0.6 + (ws / 10) * 0.4
    if combined >= 0.80:
        return "Major"
    elif combined >= 0.55:
        return "Mid-Level"
    elif combined >= 0.30:
        return "Entry-Level"
    else:
        # Very low scores get NULL — not worth rating
        return None


def derive_estimated_annual_donations(
    total_gifts: float | None,
    total_number_of_gifts: int | None,
    first_gift_date: date | None,
    gift_capacity_rating: str | None,
) -> float | None:
    """
    Estimated annual charitable giving across ALL organizations (not just IASC).
    NULL for ~60%. When present, 2-50x their actual average annual IASC gift.
    """
    if random.random() < 0.60:
        return None
    if total_gifts is None or total_number_of_gifts is None or first_gift_date is None:
        # For prospects/subscriber_only with no giving history, return a rough estimate
        return round(random.uniform(100, 5000), 2)
    # Years of giving history (at least 1)
    today = date(2026, 2, 25)
    years = max(1, (today - first_gift_date).days / 365.25)
    annual_iasc = total_gifts / years
    # People typically give to multiple organizations; multiply by 2-50x
    multiplier = random.uniform(2.0, 50.0)
    estimate = annual_iasc * multiplier
    # Clamp to reasonable range
    return round(max(100.0, min(500_000.0, estimate)), 2)


def derive_foundation_status(total_gifts: float | None, donor_status: str) -> str:
    """
    Foundation status consistent with giving history.
    Prospects and subscriber_only are labeled 'Prospect'; big donors get 'Major Donor'.
    """
    if donor_status in ("prospect", "subscriber_only"):
        return "Prospect"
    if total_gifts is None:
        return "None"
    if total_gifts >= 10_000:
        return "Major Donor"
    if total_gifts >= 100:
        return "Annual Donor"
    return "None"


# ---------------------------------------------------------------------------
# Record generators
# ---------------------------------------------------------------------------

def generate_contacts(
    n: int = 5000,
    prospect_pct: float = 0.55,
    active_pct: float = 0.08,
    lapsed_pct: float = 0.25,
    new_donor_pct: float = 0.05,
) -> list[dict]:
    """
    Generate n synthetic donor contact records.
    Status percentages must sum to ≤ 1.0; remainder becomes subscriber_only.

    Returns a list of dicts matching the contacts table schema.
    """
    contacts = []
    used_ids: set[str] = set()

    today = date(2026, 2, 25)          # "current date" for the prototype
    lapsed_cutoff = date(2024, 2, 25)  # last_gift_date before this → lapsed

    # Build weighted status pool from the supplied percentages
    subscriber_pct = max(0.0, 1.0 - prospect_pct - active_pct - lapsed_pct - new_donor_pct)
    status_pool = (
        ["prospect"] * int(prospect_pct * 1000) +
        ["active"] * int(active_pct * 1000) +
        ["lapsed"] * int(lapsed_pct * 1000) +
        ["new_donor"] * int(new_donor_pct * 1000) +
        ["subscriber_only"] * int(subscriber_pct * 1000)
    )
    # Fallback if rounding makes pool empty
    if not status_pool:
        status_pool = ["prospect"]

    for i in range(n):
        # --- Identity ---
        first_name = random.choice(FIRST_NAMES)
        last_name  = random.choice(LAST_NAMES)
        email      = f"{first_name.lower()}.{last_name.lower()}{i}@example.com"

        # Guarantee unique contact_id
        contact_id = generate_contact_id()
        while contact_id in used_ids:
            contact_id = generate_contact_id()
        used_ids.add(contact_id)

        # --- Geography ---
        # subscriber_only contacts are sometimes geo-sparse
        if random.random() < 0.70:
            state, zip_code = pick_geo()
            city = _city_for_state(state)
        else:
            state, zip_code, city = None, None, None

        # --- Donor status ---
        donor_status = random.choice(status_pool)

        # --- Contact created date ---
        # Most records 2005-2020; some older/newer
        created_start = date(1993, 1, 1)
        created_end   = date(2024, 12, 31)
        if random.random() < 0.70:
            created_start = date(2005, 1, 1)
            created_end   = date(2020, 12, 31)
        contact_created_date = random_date(created_start, created_end)

        # --- subscriber_only: minimal record —————————————————————————————
        if donor_status == "subscriber_only":
            # Sparse contact: name + maybe email + maybe geo + subscription
            email = email if random.random() < 0.80 else None
            if random.random() >= 0.70:
                state, zip_code, city = None, None, None

            sub_roll = random.random()
            if sub_roll < 0.35:
                subscription_type = "print"
            elif sub_roll < 0.65:
                subscription_type = "digital"
            else:
                subscription_type = "both"
            subscription_status = "active" if random.random() < 0.60 else "expired"
            subscription_start_date = random_date(date(2000, 1, 1), date(2024, 12, 31))

            contacts.append({
                "contact_id":               contact_id,
                "first_name":               first_name,
                "last_name":                last_name,
                "email":                    email,
                "city":                     city,
                "state":                    state,
                "zip_code":                 zip_code,
                "donor_status":             donor_status,
                "contact_created_date":     contact_created_date.isoformat(),
                "first_gift_date":          None,
                "last_gift_date":           None,
                "total_gifts":              None,
                "total_number_of_gifts":    None,
                "average_gift":             None,
                "giving_vehicle":           None,
                "subscription_type":        subscription_type,
                "subscription_status":      subscription_status,
                "subscription_start_date":  subscription_start_date.isoformat(),
                "email_open_rate":          None,
                "last_email_click_date":    None,
                "event_attendance_count":   0,
                "wealth_score":             None,
                "notes":                    None,
                # New fields — all NULL for subscriber_only
                "p2g_score":                None,
                "gift_capacity_rating":     None,
                "estimated_annual_donations": None,
                "title":                    None,
                "deceased":                 0,
                "biography":                None,
                "business_affiliations":    None,
                "community_affiliations":   None,
                "expertise_and_interests":  None,
                "do_not_contact":           0,
                "do_not_call":              0,
                "email_opt_out":            0,
                "preferred_phone":          None,
                "preferred_email":          None,
                "hedgehog_review_subscriber": 1,  # always 1 for subscriber_only
                "institute_status":         "None",
                "foundation_status":        "Prospect",
                "lead_source":              "Hedgehog Review",
                "largest_gift":             None,
                "smallest_gift":            None,
                "best_gift_year":           None,
                "last_gift_amount":         None,
            })
            continue

        # --- Gift data (NULL for prospects) ---
        if donor_status == "prospect":
            first_gift_date       = None
            last_gift_date        = None
            total_gifts           = None
            total_number_of_gifts = None
            average_gift          = None
            giving_vehicle        = None
        else:
            # first_gift_date on or after contact_created_date
            gift_start = max(contact_created_date, date(1993, 1, 1))

            if donor_status == "lapsed":
                # last gift must be before lapsed_cutoff (2024-02-25)
                first_gift_date = random_date(gift_start, date(2022, 12, 31))
                last_gift_date  = random_date(
                    min(first_gift_date + timedelta(days=1), lapsed_cutoff - timedelta(days=1)),
                    lapsed_cutoff - timedelta(days=1),
                )
            elif donor_status == "new_donor":
                # Recent first gift (within ~18 months of today)
                first_gift_date = random_date(date(2024, 9, 1), today)
                last_gift_date  = random_date(first_gift_date, today)
            else:
                # active
                first_gift_date = random_date(gift_start, date(2023, 12, 31))
                last_gift_date  = random_date(first_gift_date, today)

            # Ensure first <= last
            if first_gift_date > last_gift_date:
                first_gift_date, last_gift_date = last_gift_date, first_gift_date

            total_gifts           = power_law_total_gifts_v2()
            total_number_of_gifts = n_gifts_for_total(total_gifts)
            average_gift          = round(total_gifts / total_number_of_gifts, 2)
            giving_vehicle        = weighted_choice(GIVING_VEHICLES, GIVING_VEHICLE_WEIGHTS)

        # --- Subscription ---
        sub_roll = random.random()
        if sub_roll < 0.20:
            subscription_type = "print"
        elif sub_roll < 0.40:
            subscription_type = "digital"
        elif sub_roll < 0.60:
            subscription_type = "both"
        else:
            subscription_type = "none"

        if subscription_type == "none":
            subscription_status     = "never"
            subscription_start_date = None
        else:
            sub_status_roll = random.random()
            subscription_status = "active" if sub_status_roll < 0.65 else "expired"
            subscription_start_date = random_date(date(2000, 1, 1), date(2024, 12, 31))

        # --- Email engagement ---
        if random.random() < 0.12:
            email_open_rate       = None
            last_email_click_date = None
        else:
            # Beta-like distribution centered around 0.25
            email_open_rate = round(random.betavariate(2, 6), 3)
            if email_open_rate > 0.25 and random.random() < 0.60:
                # Clickers exist for engaged subscribers
                last_email_click_date = random_date(date(2022, 1, 1), today)
            else:
                last_email_click_date = None

        # --- Events ---
        event_attendance_count = _draw_event_count()

        # --- Wealth score ---
        wealth_score = (
            wealth_score_for_total(total_gifts) if total_gifts else (
                random.randint(1, 5) if random.random() < 0.30 else None
            )
        )

        # --- Notes (~30%) ---
        notes = random.choice(NOTES_POOL) if random.random() < 0.30 else None

        # ----------------------------------------------------------------
        # New fields
        # ----------------------------------------------------------------

        # Financial scoring (WealthEngine-derived)
        p2g_score = derive_p2g_score(total_gifts, donor_status)
        gift_capacity_rating = derive_gift_capacity_rating(p2g_score, wealth_score)
        estimated_annual_donations = derive_estimated_annual_donations(
            total_gifts, total_number_of_gifts, first_gift_date, gift_capacity_rating
        )

        # Biographical fields — rich for top donors, sparse otherwise
        title = random.choice(TITLES) if random.random() < 0.15 else None
        biography = random.choice(BIOGRAPHIES_POOL) if random.random() < 0.10 else None
        business_affiliations = (
            random.choice(BUSINESS_AFFILIATIONS_POOL) if random.random() < 0.08 else None
        )
        community_affiliations = (
            random.choice(COMMUNITY_AFFILIATIONS_POOL) if random.random() < 0.07 else None
        )
        expertise_and_interests = (
            random.choice(EXPERTISE_POOL) if random.random() < 0.12 else None
        )

        # Deceased flag (~3%); enforce consistency with status/subscriptions
        deceased = 1 if random.random() < 0.03 else 0
        if deceased:
            # Deceased contacts cannot be active or new donors
            if donor_status in ("active", "new_donor"):
                donor_status = "lapsed"
            # Subscription must be expired or never (never if subscription_type is none)
            if subscription_type == "none":
                subscription_status = "never"
            elif subscription_status == "active":
                subscription_status = "expired"
            # No email engagement for deceased
            email_open_rate       = None
            last_email_click_date = None

        # Contact preference flags
        do_not_contact = 1 if random.random() < 0.05 else 0
        do_not_call    = 1 if (do_not_contact or random.random() < 0.03) else 0
        email_opt_out  = 1 if (do_not_contact or random.random() < 0.07) else 0
        # Opt-out consistency: clear email engagement
        if email_opt_out:
            email_open_rate       = None
            last_email_click_date = None

        preferred_phone = weighted_choice(PREFERRED_PHONES, PREFERRED_PHONE_WEIGHTS)
        preferred_email = weighted_choice(PREFERRED_EMAILS, PREFERRED_EMAIL_WEIGHTS)

        # hedgehog_review_subscriber: always 1 when subscription_type != 'none',
        # plus ~40% of the remainder (fragmented subscriber data)
        if subscription_type != "none":
            hedgehog_review_subscriber = 1
        else:
            hedgehog_review_subscriber = 1 if random.random() < 0.40 else 0

        # Institute and foundation status
        institute_status = weighted_choice(INSTITUTE_STATUSES, INSTITUTE_STATUS_WEIGHTS)
        foundation_status = derive_foundation_status(total_gifts, donor_status)

        # Lead source
        lead_source = weighted_choice(LEAD_SOURCES, LEAD_SOURCE_WEIGHTS)

        contacts.append({
            "contact_id":               contact_id,
            "first_name":               first_name,
            "last_name":                last_name,
            "email":                    email,
            "city":                     city,
            "state":                    state,
            "zip_code":                 zip_code,
            "donor_status":             donor_status,
            "contact_created_date":     contact_created_date.isoformat(),
            "first_gift_date":          first_gift_date.isoformat() if first_gift_date else None,
            "last_gift_date":           last_gift_date.isoformat() if last_gift_date else None,
            "total_gifts":              total_gifts,
            "total_number_of_gifts":    total_number_of_gifts,
            "average_gift":             average_gift,
            "giving_vehicle":           giving_vehicle,
            "subscription_type":        subscription_type,
            "subscription_status":      subscription_status,
            "subscription_start_date":  subscription_start_date.isoformat() if subscription_start_date else None,
            "email_open_rate":          email_open_rate,
            "last_email_click_date":    last_email_click_date.isoformat() if last_email_click_date else None,
            "event_attendance_count":   event_attendance_count,
            "wealth_score":             wealth_score,
            "notes":                    notes,
            # New fields
            "p2g_score":                p2g_score,
            "gift_capacity_rating":     gift_capacity_rating,
            "estimated_annual_donations": estimated_annual_donations,
            "title":                    title,
            "deceased":                 deceased,
            "biography":                biography,
            "business_affiliations":    business_affiliations,
            "community_affiliations":   community_affiliations,
            "expertise_and_interests":  expertise_and_interests,
            "do_not_contact":           do_not_contact,
            "do_not_call":              do_not_call,
            "email_opt_out":            email_opt_out,
            "preferred_phone":          preferred_phone,
            "preferred_email":          preferred_email,
            "hedgehog_review_subscriber": hedgehog_review_subscriber,
            "institute_status":         institute_status,
            "foundation_status":        foundation_status,
            "lead_source":              lead_source,
            # Derived gift fields — filled in by compute_derived_gift_fields()
            "largest_gift":             None,
            "smallest_gift":            None,
            "best_gift_year":           None,
            "last_gift_amount":         None,
        })

    return contacts


def _city_for_state(state: str) -> str:
    """Return a plausible city name for a given state abbreviation."""
    city_map = {
        "VA": ["Charlottesville", "Richmond", "Alexandria", "Arlington", "Roanoke"],
        "NY": ["New York", "Brooklyn", "Manhattan", "Bronx", "Buffalo"],
        "DC": ["Washington"],
        "MD": ["Bethesda", "Chevy Chase", "Silver Spring", "Rockville", "Annapolis"],
        "MA": ["Boston", "Cambridge", "Brookline", "Newton", "Somerville"],
        "IL": ["Chicago", "Evanston", "Oak Park", "Naperville", "Wilmette"],
        "CA": ["San Francisco", "Los Angeles", "Berkeley", "Oakland", "Palo Alto"],
        "TX": ["Houston", "Austin", "Dallas", "San Antonio", "Fort Worth"],
        "FL": ["Miami", "Tampa", "Orlando", "Fort Lauderdale", "Boca Raton"],
        "PA": ["Philadelphia", "Pittsburgh", "Ardmore", "Media", "Wayne"],
        "OH": ["Columbus", "Cleveland", "Cincinnati", "Dayton", "Toledo"],
        "GA": ["Atlanta", "Decatur", "Athens", "Savannah", "Marietta"],
        "NC": ["Chapel Hill", "Durham", "Raleigh", "Charlotte", "Asheville"],
        "WA": ["Seattle", "Bellevue", "Redmond", "Kirkland", "Olympia"],
        "CO": ["Denver", "Boulder", "Fort Collins", "Colorado Springs", "Aspen"],
        "MN": ["Minneapolis", "St. Paul", "Edina", "Minnetonka", "Bloomington"],
        "MO": ["St. Louis", "Kansas City", "Clayton", "Ladue", "Columbia"],
        "AZ": ["Phoenix", "Scottsdale", "Tempe", "Tucson", "Mesa"],
        "TN": ["Nashville", "Memphis", "Knoxville", "Chattanooga", "Brentwood"],
        "NJ": ["Princeton", "Hoboken", "Montclair", "Summit", "Morristown"],
    }
    return random.choice(city_map.get(state, ["Unknown"]))


def _draw_event_count() -> int:
    """
    Draw event attendance count.  Most people attend 0 events; a few attend many.
    Rough shape: P(0) ≈ 0.55, P(1-3) ≈ 0.30, P(4-12) ≈ 0.15.
    """
    r = random.random()
    if r < 0.55:
        return 0
    elif r < 0.85:
        return random.randint(1, 3)
    else:
        return random.randint(4, 12)


def generate_gifts(contacts: list[dict]) -> list[dict]:
    """
    Generate individual gift transactions for all non-prospect, non-subscriber_only donors.
    Each donor gets exactly total_number_of_gifts transactions whose amounts
    average close to average_gift and sum close to total_gifts.
    """
    gifts = []
    gift_id = 1

    for contact in contacts:
        if contact["donor_status"] in ("prospect", "subscriber_only"):
            continue  # No gift history for these statuses

        n          = contact["total_number_of_gifts"]
        total      = contact["total_gifts"]
        avg        = contact["average_gift"]
        first_date = date.fromisoformat(contact["first_gift_date"])
        last_date  = date.fromisoformat(contact["last_gift_date"])
        cid        = contact["contact_id"]

        # Generate n amounts that sum to total.
        # Strategy: draw raw proportional amounts from a log-normal, then snap each
        # to a psychologically realistic round number (donors write round checks).
        if n == 1:
            amounts = [round_to_nice_amount(total)]
        else:
            # Draw from log-normal centered at avg; rescale to stay near total.
            raw = [max(20.0, random.lognormvariate(math.log(max(avg, 20)), 0.6))
                   for _ in range(n)]
            raw_sum = sum(raw)
            # Snap each amount to a nice value; accept that the sum won't be
            # exact — this is realistic (each gift is an independent transaction).
            amounts = [round_to_nice_amount(total * v / raw_sum) for v in raw]
            # Ensure no individual gift drops below the minimum.
            amounts = [max(20.0, a) for a in amounts]

        # Distribute dates between first_gift_date and last_gift_date,
        # biased toward year-end giving season.
        gift_dates = sorted([
            year_end_biased_date(first_date, last_date)
            for _ in range(n)
        ])

        for gdate, amount in zip(gift_dates, amounts):
            gift_type = weighted_choice(GIFT_TYPES, GIFT_TYPE_WEIGHTS)
            campaign  = random.choice(CAMPAIGNS) if random.random() < 0.75 else None

            gifts.append({
                "gift_id":    gift_id,
                "contact_id": cid,
                "gift_date":  gdate.isoformat(),
                "amount":     amount,
                "gift_type":  gift_type,
                "campaign":   campaign,
            })
            gift_id += 1

    return gifts


def generate_interactions(contacts: list[dict]) -> list[dict]:
    """
    Generate 0–20 interaction records per contact.
    Contacts with higher email engagement or event attendance get more interactions.
    """
    interactions = []
    interaction_id = 1
    today = date(2026, 2, 25)

    for contact in contacts:
        open_rate    = contact["email_open_rate"] or 0.0
        event_count  = contact["event_attendance_count"]
        donor_status = contact["donor_status"]

        # Base interaction count from engagement signals
        base = int(open_rate * 10) + event_count
        # Active/lapsed donors tend to have more tracked interactions
        if donor_status in ("active", "lapsed"):
            base += random.randint(0, 5)
        n_interactions = max(0, min(20, base + random.randint(-2, 3)))

        for _ in range(n_interactions):
            itype  = random.choice(INTERACTION_TYPES)
            idate  = random_date(date(2020, 1, 1), today)
            details = _interaction_details(itype)

            interactions.append({
                "interaction_id":   interaction_id,
                "contact_id":       contact["contact_id"],
                "interaction_date": idate.isoformat(),
                "interaction_type": itype,
                "details":          details,
            })
            interaction_id += 1

    return interactions


def _interaction_details(itype: str) -> str | None:
    """Return a plausible detail string for a given interaction type."""
    detail_pool = {
        "email_open": [
            "Year-End Appeal 2023",
            "Journal issue announcement",
            "Spring fundraising newsletter",
            "Annual event invitation",
            "Annual Fund thank-you",
            None,
        ],
        "email_click": [
            "Clicked donate button",
            "Clicked event registration link",
            "Clicked journal article link",
            None,
        ],
        "event_attended": [
            "Spring Gala 2022",
            "Spring Gala 2023",
            "Homecoming Reception 2023",
            "Book Launch event",
            "Virtual Symposium on Culture & Democracy",
        ],
        "meeting": [
            "Introductory meeting with development director",
            "Stewardship call – discussed giving impact",
            "Major gift conversation – preliminary",
            "Cultivation lunch",
            "Phone meeting rescheduled",
        ],
        "phone_call": [
            "Thank-you call after Year-End gift",
            "Outreach about Planned Giving Society",
            "Follow-up on lapsed donor reengagement",
            "Left voicemail",
            None,
        ],
        "mail_sent": [
            "Annual Fund appeal letter",
            "Holiday card",
            "Hedgehog Review print copy",
            "Planned giving brochure",
            "Stewardship impact report",
        ],
    }
    pool = detail_pool.get(itype, [None])
    return random.choice(pool)


# ---------------------------------------------------------------------------
# Post-processing: derived gift fields, near-duplicates, data quality issues
# ---------------------------------------------------------------------------

def compute_derived_gift_fields(contacts: list[dict], gifts: list[dict]) -> None:
    """
    Populate largest_gift, smallest_gift, best_gift_year, and last_gift_amount
    on each contact record from the gifts table.  Mutates contacts in-place.
    """
    # Build per-contact gift index: contact_id → list of (date_str, amount)
    gift_index: dict[str, list[tuple[str, float]]] = {}
    for g in gifts:
        cid = g["contact_id"]
        if cid not in gift_index:
            gift_index[cid] = []
        gift_index[cid].append((g["gift_date"], g["amount"]))

    for contact in contacts:
        cid = contact["contact_id"]
        if cid not in gift_index:
            continue  # prospect or subscriber_only — leave NULL

        cg = gift_index[cid]
        amounts  = [a for _, a in cg]
        contact["largest_gift"]  = max(amounts)
        contact["smallest_gift"] = min(amounts)

        # Most recent gift amount
        sorted_by_date  = sorted(cg, key=lambda x: x[0])
        contact["last_gift_amount"] = sorted_by_date[-1][1]

        # Year with highest total giving
        year_totals: dict[int, float] = {}
        for d, a in cg:
            yr = int(d[:4])
            year_totals[yr] = year_totals.get(yr, 0.0) + a
        contact["best_gift_year"] = max(year_totals, key=lambda yr: year_totals[yr])


def inject_near_duplicates(contacts: list[dict], n_pairs: int = 6) -> list[dict]:
    """
    Create n_pairs near-duplicate contact records to simulate the duplicate problem
    that real nonprofits encounter when merging Salesforce with subscriber data.

    Each duplicate shares first_name + last_name with a real contact but has a
    slightly different email and/or zip code and a new unique contact_id.

    Returns the augmented contacts list.
    """
    # Only duplicate contacts that have gift history (more interesting for data analysis)
    eligible = [c for c in contacts if c["total_gifts"] is not None]
    if len(eligible) < n_pairs:
        eligible = contacts[:n_pairs]

    chosen = random.sample(eligible, min(n_pairs, len(eligible)))

    chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    used_ids = {c["contact_id"] for c in contacts}

    new_records = []
    for original in chosen:
        # New unique contact_id
        new_id = generate_contact_id()
        while new_id in used_ids:
            new_id = generate_contact_id()
        used_ids.add(new_id)

        # Copy the original and apply slight variations
        dup = dict(original)
        dup["contact_id"] = new_id

        # Vary the email slightly (add "2" before @)
        if dup["email"]:
            parts = dup["email"].split("@")
            dup["email"] = parts[0] + "2@" + parts[1]

        # Vary the zip code slightly (increment last two digits by 1)
        if dup["zip_code"] and len(dup["zip_code"]) >= 5:
            prefix   = dup["zip_code"][:3]
            old_suf  = int(dup["zip_code"][3:])
            new_suf  = (old_suf + 1) % 100
            dup["zip_code"] = f"{prefix}{new_suf:02d}"

        # Wipe derived gift fields — they'll be recomputed or left NULL
        # (gifts table references the ORIGINAL contact_id so these won't match)
        dup["largest_gift"]    = None
        dup["smallest_gift"]   = None
        dup["best_gift_year"]  = None
        dup["last_gift_amount"] = None

        new_records.append(dup)

    contacts.extend(new_records)
    return contacts


def inject_data_quality_issues(
    contacts: list[dict],
    gifts: list[dict],
    interactions: list[dict],
) -> dict[str, int]:
    """
    Deliberately introduce realistic data quality issues into the dataset.
    These are intentional and documented in the data dictionary so analysts
    can practise finding them.

    Returns a dict counting how many records were affected per issue type.
    Mutates contacts and gifts in-place.
    """
    counts: dict[str, int] = {
        "missing_email": 0,
        "deceased_active_subscription": 0,
        "date_inversion": 0,
        "wrong_lapsed_status": 0,
    }

    today = date(2026, 2, 25)
    two_years_ago = date(2024, 2, 25)

    # Issue 1: ~3% of contacts — set email to NULL (unreachable contacts)
    n_missing_email = max(1, int(len(contacts) * 0.03))
    candidates = [c for c in contacts if c["email"] is not None]
    for c in random.sample(candidates, min(n_missing_email, len(candidates))):
        c["email"] = None
        counts["missing_email"] += 1

    # Issue 2: ~2% of deceased contacts — active subscription (data not updated after death)
    # Only applies to contacts who have a non-"none" subscription_type, so the
    # inconsistency makes sense (they had a subscription that was not marked expired).
    deceased_with_sub = [
        c for c in contacts
        if c["deceased"] == 1 and c.get("subscription_type", "none") != "none"
    ]
    n_dec_active = max(1, int(len(deceased_with_sub) * 0.10)) if deceased_with_sub else 0
    for c in random.sample(deceased_with_sub, min(n_dec_active, len(deceased_with_sub))):
        c["subscription_status"] = "active"
        counts["deceased_active_subscription"] += 1

    # Issue 3: ~1% of donors — swap first_gift_date and last_gift_date
    donor_contacts = [
        c for c in contacts
        if c["first_gift_date"] and c["last_gift_date"] and
           c["first_gift_date"] != c["last_gift_date"]
    ]
    n_inversion = max(1, int(len(donor_contacts) * 0.01))
    for c in random.sample(donor_contacts, min(n_inversion, len(donor_contacts))):
        c["first_gift_date"], c["last_gift_date"] = c["last_gift_date"], c["first_gift_date"]
        counts["date_inversion"] += 1

    # Issue 4: ~5% of lapsed donors — last_gift_date within 2 years (stale derived field)
    # This means the contact should be "active" but is still marked "lapsed"
    lapsed = [c for c in contacts if c["donor_status"] == "lapsed" and c["last_gift_date"]]
    n_wrong_lapsed = max(1, int(len(lapsed) * 0.05))
    for c in random.sample(lapsed, min(n_wrong_lapsed, len(lapsed))):
        # Set last_gift_date to within the last 2 years
        new_last = random_date(two_years_ago + timedelta(days=1), today)
        c["last_gift_date"] = new_last.isoformat()
        counts["wrong_lapsed_status"] += 1

    return counts


# ---------------------------------------------------------------------------
# Database creation
# ---------------------------------------------------------------------------

DDL_CONTACTS = """
CREATE TABLE IF NOT EXISTS contacts (
    contact_id                  TEXT PRIMARY KEY,
    first_name                  TEXT NOT NULL,
    last_name                   TEXT NOT NULL,
    email                       TEXT,
    city                        TEXT,
    state                       TEXT,
    zip_code                    TEXT,
    donor_status                TEXT NOT NULL,
    contact_created_date        DATE,
    first_gift_date             DATE,
    last_gift_date              DATE,
    total_gifts                 REAL,
    total_number_of_gifts       INTEGER,
    average_gift                REAL,
    giving_vehicle              TEXT,
    subscription_type           TEXT,
    subscription_status         TEXT,
    subscription_start_date     DATE,
    email_open_rate             REAL,
    last_email_click_date       DATE,
    event_attendance_count      INTEGER DEFAULT 0,
    wealth_score                INTEGER,
    notes                       TEXT,
    p2g_score                   INTEGER,
    gift_capacity_rating        TEXT,
    estimated_annual_donations  REAL,
    title                       TEXT,
    deceased                    INTEGER DEFAULT 0,
    biography                   TEXT,
    business_affiliations       TEXT,
    community_affiliations      TEXT,
    expertise_and_interests     TEXT,
    do_not_contact              INTEGER DEFAULT 0,
    do_not_call                 INTEGER DEFAULT 0,
    email_opt_out               INTEGER DEFAULT 0,
    preferred_phone             TEXT,
    preferred_email             TEXT,
    hedgehog_review_subscriber  INTEGER DEFAULT 0,
    institute_status            TEXT,
    foundation_status           TEXT,
    lead_source                 TEXT,
    largest_gift                REAL,
    smallest_gift               REAL,
    best_gift_year              INTEGER,
    last_gift_amount            REAL
);
"""

DDL_GIFTS = """
CREATE TABLE IF NOT EXISTS gifts (
    gift_id     INTEGER PRIMARY KEY,
    contact_id  TEXT NOT NULL REFERENCES contacts(contact_id),
    gift_date   DATE NOT NULL,
    amount      REAL NOT NULL,
    gift_type   TEXT,
    campaign    TEXT
);
"""

DDL_INTERACTIONS = """
CREATE TABLE IF NOT EXISTS interactions (
    interaction_id   INTEGER PRIMARY KEY,
    contact_id       TEXT NOT NULL REFERENCES contacts(contact_id),
    interaction_date DATE NOT NULL,
    interaction_type TEXT NOT NULL,
    details          TEXT
);
"""

# Ordered column list matching DDL_CONTACTS for INSERT statements
_CONTACT_COLUMNS = [
    "contact_id", "first_name", "last_name", "email", "city", "state",
    "zip_code", "donor_status", "contact_created_date", "first_gift_date",
    "last_gift_date", "total_gifts", "total_number_of_gifts", "average_gift",
    "giving_vehicle", "subscription_type", "subscription_status",
    "subscription_start_date", "email_open_rate", "last_email_click_date",
    "event_attendance_count", "wealth_score", "notes",
    "p2g_score", "gift_capacity_rating", "estimated_annual_donations",
    "title", "deceased", "biography", "business_affiliations",
    "community_affiliations", "expertise_and_interests",
    "do_not_contact", "do_not_call", "email_opt_out",
    "preferred_phone", "preferred_email", "hedgehog_review_subscriber",
    "institute_status", "foundation_status", "lead_source",
    "largest_gift", "smallest_gift", "best_gift_year", "last_gift_amount",
]


def create_database(
    db_path: Path,
    contacts: list[dict],
    gifts: list[dict],
    interactions: list[dict],
) -> None:
    """Create SQLite database and populate all three tables."""
    # Remove existing DB so the script is idempotent
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    cur  = conn.cursor()

    # Enable foreign keys
    cur.execute("PRAGMA foreign_keys = ON;")

    # Create tables
    cur.execute(DDL_CONTACTS)
    cur.execute(DDL_GIFTS)
    cur.execute(DDL_INTERACTIONS)

    # Build INSERT placeholder string for contacts
    placeholders = ", ".join(f":{col}" for col in _CONTACT_COLUMNS)
    insert_contact_sql = f"INSERT INTO contacts VALUES ({placeholders})"

    # Insert contacts (use named parameters for safety and readability)
    cur.executemany(insert_contact_sql, contacts)

    # Insert gifts
    cur.executemany(
        "INSERT INTO gifts VALUES (:gift_id, :contact_id, :gift_date, :amount, :gift_type, :campaign)",
        gifts,
    )

    # Insert interactions
    cur.executemany(
        "INSERT INTO interactions VALUES (:interaction_id, :contact_id, :interaction_date, :interaction_type, :details)",
        interactions,
    )

    conn.commit()
    conn.close()
    print(f"Database written to: {db_path}")


def write_csv(
    output_path: Path,
    contacts: list[dict],
    gifts: list[dict],
    interactions: list[dict],
) -> None:
    """
    Write data as three CSV files alongside the given base path.
    E.g., output_path='data/donors.csv' writes:
      data/donors_contacts.csv
      data/donors_gifts.csv
      data/donors_interactions.csv
    """
    stem   = output_path.stem
    parent = output_path.parent

    def _write(rows: list[dict], filename: Path) -> None:
        if not rows:
            return
        with open(filename, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print(f"CSV written to: {filename}")

    _write(contacts,     parent / f"{stem}_contacts.csv")
    _write(gifts,        parent / f"{stem}_gifts.csv")
    _write(interactions, parent / f"{stem}_interactions.csv")


# ---------------------------------------------------------------------------
# Summary statistics
# ---------------------------------------------------------------------------

def print_summary(
    contacts: list[dict],
    gifts: list[dict],
    interactions: list[dict],
    dq_counts: dict[str, int] | None = None,
    n_near_dup_pairs: int = 6,
) -> None:
    """Print summary statistics to stdout after generation."""

    print("\n" + "=" * 65)
    print("MOCK DATA GENERATION SUMMARY")
    print("=" * 65)

    n = len(contacts)
    print(f"\nTotal contacts: {n}")

    # --- Donor status breakdown ---
    status_counts: dict[str, int] = {}
    for c in contacts:
        status_counts[c["donor_status"]] = status_counts.get(c["donor_status"], 0) + 1
    print("\nContacts by donor_status:")
    for status, count in sorted(status_counts.items(), key=lambda x: -x[1]):
        print(f"  {status:<18} {count:>5}  ({count/n*100:.1f}%)")

    # --- Deceased and do_not_contact ---
    n_deceased = sum(1 for c in contacts if c.get("deceased") == 1)
    n_dnc      = sum(1 for c in contacts if c.get("do_not_contact") == 1)
    print(f"\nDeceased contacts:    {n_deceased:>5}  ({n_deceased/n*100:.1f}%)")
    print(f"Do-not-contact:       {n_dnc:>5}  ({n_dnc/n*100:.1f}%)")

    # Near-duplicate pairs: the count passed in represents deliberately injected pairs.
    # (Name collisions from random selection also exist but are not deliberate duplicates.)
    print(f"Near-duplicate pairs (injected): {n_near_dup_pairs:>5}")

    # Contacts with no email (unreachable)
    n_no_email = sum(1 for c in contacts if c.get("email") is None)
    print(f"Missing email:        {n_no_email:>5}  ({n_no_email/n*100:.1f}%)")

    # --- Geographic distribution (top 10 states) ---
    state_counts: dict[str, int] = {}
    for c in contacts:
        s = c.get("state") or "(none)"
        state_counts[s] = state_counts.get(s, 0) + 1
    print("\nContacts by state (top 10):")
    for state, count in sorted(state_counts.items(), key=lambda x: -x[1])[:10]:
        print(f"  {state:<6} {count:>5}  ({count/n*100:.1f}%)")

    # --- Gift amount distribution ---
    amounts = [c["total_gifts"] for c in contacts if c["total_gifts"] is not None]
    if amounts:
        sorted_amounts = sorted(amounts)
        na    = len(sorted_amounts)
        total = sum(sorted_amounts)
        median = sorted_amounts[na // 2]
        mean   = total / na
        print(f"\nGift amount distribution (n={na} donors with gift data):")
        print(f"  Min:    ${sorted_amounts[0]:>14,.2f}")
        print(f"  Median: ${median:>14,.2f}")
        print(f"  Mean:   ${mean:>14,.2f}")
        print(f"  Max:    ${sorted_amounts[-1]:>14,.2f}")
        print(f"  Total:  ${total:>14,.2f}")

    # --- Total across all gift transactions ---
    total_gift_txn = sum(g["amount"] for g in gifts)
    print(f"\nTotal across all gift transactions: ${total_gift_txn:>14,.2f}")

    # --- Institute status distribution ---
    inst_counts: dict[str, int] = {}
    for c in contacts:
        v = c.get("institute_status") or "None"
        inst_counts[v] = inst_counts.get(v, 0) + 1
    print("\nInstitute status distribution:")
    for v, count in sorted(inst_counts.items(), key=lambda x: -x[1]):
        print(f"  {v:<20} {count:>5}  ({count/n*100:.1f}%)")

    # --- Foundation status distribution ---
    fnd_counts: dict[str, int] = {}
    for c in contacts:
        v = c.get("foundation_status") or "None"
        fnd_counts[v] = fnd_counts.get(v, 0) + 1
    print("\nFoundation status distribution:")
    for v, count in sorted(fnd_counts.items(), key=lambda x: -x[1]):
        print(f"  {v:<20} {count:>5}  ({count/n*100:.1f}%)")

    # --- Subscription breakdown ---
    sub_counts: dict[str, int] = {}
    for c in contacts:
        key = f"{c['subscription_type']} / {c['subscription_status']}"
        sub_counts[key] = sub_counts.get(key, 0) + 1
    print("\nSubscription breakdown:")
    for key, count in sorted(sub_counts.items(), key=lambda x: -x[1]):
        print(f"  {key:<30} {count:>5}")

    # --- Wealth score coverage ---
    scored = [c for c in contacts if c.get("wealth_score") is not None]
    print(f"\nWealth score coverage: {len(scored)}/{n} ({len(scored)/n*100:.1f}%)")

    # --- Gift and interaction row counts ---
    print(f"\nTotal gift transactions: {len(gifts):>6}")
    print(f"Total interactions:      {len(interactions):>6}")

    # --- Intentional data quality issue counts ---
    if dq_counts:
        print("\nIntentional data quality issues injected:")
        for issue, count in dq_counts.items():
            print(f"  {issue:<35} {count:>5}")
        print(f"  {'near_duplicate_pairs':<35} {n_near_dup_pairs:>5}")

    print("=" * 65 + "\n")


# ---------------------------------------------------------------------------
# Public API: generate_dataset()
# ---------------------------------------------------------------------------

def generate_dataset(
    num_contacts: int = 5000,
    seed: int = 42,
    prospect_pct: float = 0.55,
    active_pct: float = 0.08,
    lapsed_pct: float = 0.25,
    new_donor_pct: float = 0.05,
    major_donor_count: int = 15,
    total_fundraising_target: float = 10_000_000,
) -> tuple[list[dict], list[dict], list[dict]]:
    """
    Generate a complete synthetic donor dataset.  Returns (contacts, gifts, interactions).

    Each element is a list of dicts that can be passed directly to pd.DataFrame():

        import pandas as pd
        contacts, gifts, interactions = generate_dataset()
        df_contacts = pd.DataFrame(contacts)

    Args:
        num_contacts: Number of contact records to generate.
        seed: Random seed for reproducibility.
        prospect_pct: Proportion of contacts who are prospects (no giving history).
        active_pct: Proportion of contacts who are active donors.
        lapsed_pct: Proportion of contacts who are lapsed donors.
        new_donor_pct: Proportion of contacts who are new donors.
        major_donor_count: Approximate number of major donors (>$100K total gifts).
            (Currently informational; gift distribution handles this naturally.)
        total_fundraising_target: Approximate total dollar target across all gifts.
            (Currently informational; used for sanity-checking summary output.)

    Returns:
        Tuple of (contacts, gifts, interactions) as lists of dicts.
    """
    random.seed(seed)

    print(f"Generating {num_contacts:,} synthetic donor contacts...")
    contacts = generate_contacts(
        n=num_contacts,
        prospect_pct=prospect_pct,
        active_pct=active_pct,
        lapsed_pct=lapsed_pct,
        new_donor_pct=new_donor_pct,
    )

    print("Generating gift transactions...")
    gifts = generate_gifts(contacts)

    print("Generating interaction records...")
    interactions = generate_interactions(contacts)

    print("Computing derived gift fields...")
    compute_derived_gift_fields(contacts, gifts)

    print("Injecting near-duplicate records...")
    contacts = inject_near_duplicates(contacts, n_pairs=6)

    print("Injecting intentional data quality issues...")
    # dq_counts stored on the list object so callers can retrieve it
    dq_counts = inject_data_quality_issues(contacts, gifts, interactions)
    # Attach to the returned list as a non-standard attribute is not Pythonic;
    # callers who need counts should use generate_dataset_with_meta() or call
    # inject_data_quality_issues directly.  For the CLI we re-run summary without counts.

    return contacts, gifts, interactions


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate synthetic donor data for the IASC Donor Analytics prototype.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--num-contacts", type=int, default=5000,
        help="Number of contact records to generate.",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for reproducibility.",
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Output path.  Defaults to data/donors.db (or data/donors.csv with --csv).",
    )
    parser.add_argument(
        "--csv", action="store_true",
        help="Write output as CSV files instead of SQLite.  Three files are created: "
             "{stem}_contacts.csv, {stem}_gifts.csv, {stem}_interactions.csv.",
    )
    parser.add_argument(
        "--prospect-pct", type=float, default=0.55,
        help="Proportion of contacts who are prospects (0.0–1.0).",
    )
    parser.add_argument(
        "--active-pct", type=float, default=0.08,
        help="Proportion of contacts who are active donors (0.0–1.0).",
    )
    parser.add_argument(
        "--lapsed-pct", type=float, default=0.25,
        help="Proportion of contacts who are lapsed donors (0.0–1.0).",
    )
    parser.add_argument(
        "--new-donor-pct", type=float, default=0.05,
        help="Proportion of contacts who are new donors (0.0–1.0).",
    )
    parser.add_argument(
        "--major-donor-count", type=int, default=15,
        help="Approximate target number of major donors (>$100K total gifts).",
    )
    parser.add_argument(
        "--total-fundraising-target", type=float, default=10_000_000,
        help="Approximate total dollar target across all gifts (for summary reporting).",
    )
    return parser.parse_args()


def main() -> None:
    """CLI entry point: parse args, generate data, write output, print summary."""
    args = _parse_args()

    # Validate status percentages
    status_sum = args.prospect_pct + args.active_pct + args.lapsed_pct + args.new_donor_pct
    if status_sum > 1.0:
        print(
            f"ERROR: Status percentages sum to {status_sum:.2f}, which exceeds 1.0. "
            "Reduce --prospect-pct, --active-pct, --lapsed-pct, or --new-donor-pct.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Resolve output path relative to this script's location for portability
    script_dir = Path(__file__).parent
    if args.output:
        output_path = Path(args.output)
        if not output_path.is_absolute():
            output_path = script_dir.parent / output_path
    else:
        default_name = "donors.csv" if args.csv else "donors.db"
        output_path = script_dir / default_name

    # Generate — generate_dataset sets the seed internally
    contacts, gifts, interactions = generate_dataset(
        num_contacts=args.num_contacts,
        seed=args.seed,
        prospect_pct=args.prospect_pct,
        active_pct=args.active_pct,
        lapsed_pct=args.lapsed_pct,
        new_donor_pct=args.new_donor_pct,
        major_donor_count=args.major_donor_count,
        total_fundraising_target=args.total_fundraising_target,
    )

    # Write output
    if args.csv:
        print(f"Writing CSV files (base: {output_path})...")
        write_csv(output_path, contacts, gifts, interactions)
    else:
        print(f"Writing SQLite database to {output_path}...")
        create_database(output_path, contacts, gifts, interactions)

    print_summary(contacts, gifts, interactions, n_near_dup_pairs=6)


if __name__ == "__main__":
    main()
