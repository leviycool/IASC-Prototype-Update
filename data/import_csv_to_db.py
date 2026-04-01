"""
Import donor CSV exports into the SQLite database used by the prototype.

Default usage:
    python data/import_csv_to_db.py

This script expects the three checked-in CSV files to exist in data/ and
rebuilds data/donors.db so the app can query the latest dataset.
"""

import argparse
import csv
import sqlite3
from pathlib import Path


DATA_DIR = Path(__file__).parent
DEFAULT_CONTACTS_CSV = DATA_DIR / "synthetic_donors_contacts.csv"
DEFAULT_GIFTS_CSV = DATA_DIR / "synthetic_donors_gifts.csv"
DEFAULT_INTERACTIONS_CSV = DATA_DIR / "synthetic_donors_interactions.csv"
DEFAULT_DB_PATH = DATA_DIR / "donors.db"

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

INTEGER_COLUMNS = {
    "gift_id",
    "interaction_id",
    "total_number_of_gifts",
    "event_attendance_count",
    "wealth_score",
    "p2g_score",
    "deceased",
    "do_not_contact",
    "do_not_call",
    "email_opt_out",
    "hedgehog_review_subscriber",
    "best_gift_year",
}

REAL_COLUMNS = {
    "total_gifts",
    "average_gift",
    "estimated_annual_donations",
    "largest_gift",
    "smallest_gift",
    "last_gift_amount",
    "amount",
    "email_open_rate",
}


def _parse_value(column: str, value: str):
    if value == "":
        return None
    if column in INTEGER_COLUMNS:
        return int(float(value))
    if column in REAL_COLUMNS:
        return float(value)
    return value


def _insert_csv(cur: sqlite3.Cursor, table_name: str, csv_path: Path) -> int:
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        columns = reader.fieldnames or []
        placeholders = ", ".join("?" for _ in columns)
        sql = f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({placeholders})"
        cur.executemany(sql, ([ _parse_value(column, row[column]) for column in columns ] for row in reader))
        return reader.line_num - 1


def create_database(
    contacts_csv: Path = DEFAULT_CONTACTS_CSV,
    gifts_csv: Path = DEFAULT_GIFTS_CSV,
    interactions_csv: Path = DEFAULT_INTERACTIONS_CSV,
    output_path: Path = DEFAULT_DB_PATH,
) -> None:
    required_files = [contacts_csv, gifts_csv, interactions_csv]
    missing_files = [str(path) for path in required_files if not path.exists()]
    if missing_files:
        missing = ", ".join(missing_files)
        raise FileNotFoundError(f"Missing required CSV file(s): {missing}")

    if output_path.exists():
        output_path.unlink()

    conn = sqlite3.connect(output_path)
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys = ON;")
    cur.execute(DDL_CONTACTS)
    cur.execute(DDL_GIFTS)
    cur.execute(DDL_INTERACTIONS)

    counts = {
        "contacts": _insert_csv(cur, "contacts", contacts_csv),
        "gifts": _insert_csv(cur, "gifts", gifts_csv),
        "interactions": _insert_csv(cur, "interactions", interactions_csv),
    }

    conn.commit()
    conn.close()

    print(f"Database written to: {output_path}")
    for table_name, count in counts.items():
        print(f"  {table_name}: {count}")



def main() -> None:
    parser = argparse.ArgumentParser(description="Import donor CSV files into SQLite.")
    parser.add_argument("--contacts", type=Path, default=DEFAULT_CONTACTS_CSV)
    parser.add_argument("--gifts", type=Path, default=DEFAULT_GIFTS_CSV)
    parser.add_argument("--interactions", type=Path, default=DEFAULT_INTERACTIONS_CSV)
    parser.add_argument("--output", type=Path, default=DEFAULT_DB_PATH)
    args = parser.parse_args()

    create_database(
        contacts_csv=args.contacts,
        gifts_csv=args.gifts,
        interactions_csv=args.interactions,
        output_path=args.output,
    )


if __name__ == "__main__":
    main()
