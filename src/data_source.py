"""
Helpers for selecting the active donor data source for a Streamlit session.
"""

from __future__ import annotations

import importlib.util
import re
import shutil
import sqlite3
import tempfile
from pathlib import Path

from config import DB_PATH


UPLOAD_ROOT = Path(tempfile.gettempdir()) / "iasc_donor_uploads"
REQUIRED_TABLES = {
    "contacts": {
        "contact_id",
        "first_name",
        "last_name",
        "city",
        "state",
        "donor_status",
        "first_gift_date",
        "last_gift_date",
        "total_gifts",
        "total_number_of_gifts",
        "average_gift",
        "giving_vehicle",
        "subscription_type",
        "subscription_status",
        "email_open_rate",
        "event_attendance_count",
        "wealth_score",
    },
    "gifts": {
        "gift_id",
        "contact_id",
        "gift_date",
        "amount",
        "gift_type",
        "campaign",
    },
    "interactions": {
        "interaction_id",
        "contact_id",
        "interaction_date",
        "interaction_type",
        "details",
    },
}


def get_default_data_source() -> dict[str, str]:
    """Return the built-in demo dataset descriptor."""
    return {
        "kind": "synthetic",
        "label": "Synthetic demo dataset",
        "db_path": str(DB_PATH),
        "source_note": "Built-in synthetic donor database bundled with the app.",
    }


def prepare_uploaded_sqlite_database(
    *,
    file_name: str,
    file_bytes: bytes,
    session_id: str,
) -> dict[str, str]:
    """Persist and validate a user-uploaded SQLite donor database."""
    upload_dir = _session_upload_dir(session_id)
    db_name = _safe_name(file_name or "uploaded_donors.db")
    if not db_name.endswith(".db"):
        db_name = f"{Path(db_name).stem}.db"

    db_path = upload_dir / db_name
    db_path.write_bytes(file_bytes)
    validate_database(db_path)

    return {
        "kind": "uploaded_db",
        "label": f"Uploaded database: {Path(file_name).name}",
        "db_path": str(db_path),
        "source_note": "User-uploaded SQLite donor database.",
    }


def prepare_uploaded_csv_dataset(
    *,
    contacts_name: str,
    contacts_bytes: bytes,
    gifts_name: str,
    gifts_bytes: bytes,
    interactions_name: str,
    interactions_bytes: bytes,
    session_id: str,
) -> dict[str, str]:
    """Persist uploaded CSV exports and build a session-specific SQLite database."""
    upload_dir = _session_upload_dir(session_id)
    contacts_path = upload_dir / _safe_name(contacts_name or "contacts.csv")
    gifts_path = upload_dir / _safe_name(gifts_name or "gifts.csv")
    interactions_path = upload_dir / _safe_name(interactions_name or "interactions.csv")
    output_path = upload_dir / "uploaded_donors.db"

    contacts_path.write_bytes(contacts_bytes)
    gifts_path.write_bytes(gifts_bytes)
    interactions_path.write_bytes(interactions_bytes)

    importer = _load_importer_module()
    importer.create_database(
        contacts_csv=contacts_path,
        gifts_csv=gifts_path,
        interactions_csv=interactions_path,
        output_path=output_path,
    )
    validate_database(output_path)

    return {
        "kind": "uploaded_csv",
        "label": f"Uploaded CSV dataset: {Path(contacts_name).name}",
        "db_path": str(output_path),
        "source_note": "User-uploaded donor CSV exports converted into a session database.",
    }


def reset_uploaded_data_source(session_id: str) -> None:
    """Remove any persisted uploaded data for this session."""
    session_dir = _session_upload_dir(session_id, create=False)
    if session_dir.exists():
        shutil.rmtree(session_dir)


def validate_database(db_path: Path) -> None:
    """Validate that the uploaded database has the tables/columns this app needs."""
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    conn = sqlite3.connect(str(db_path))
    try:
        existing_tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        missing_tables = set(REQUIRED_TABLES) - existing_tables
        if missing_tables:
            missing = ", ".join(sorted(missing_tables))
            raise ValueError(f"Uploaded database is missing required tables: {missing}")

        for table_name, required_columns in REQUIRED_TABLES.items():
            rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
            existing_columns = {row[1] for row in rows}
            missing_columns = required_columns - existing_columns
            if missing_columns:
                missing = ", ".join(sorted(missing_columns))
                raise ValueError(
                    f"Uploaded database table '{table_name}' is missing required columns: {missing}"
                )
    finally:
        conn.close()


def _safe_name(file_name: str) -> str:
    """Sanitize a user-provided filename for local storage."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(file_name).name)
    return cleaned or "uploaded_file"


def _session_upload_dir(session_id: str, create: bool = True) -> Path:
    """Return the folder used for one Streamlit session's uploaded data."""
    session_dir = UPLOAD_ROOT / session_id
    if create:
        session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


def _load_importer_module():
    """Load the CSV-to-SQLite importer without requiring data/ to be a package."""
    importer_path = Path(__file__).parent.parent / "data" / "import_csv_to_db.py"
    spec = importlib.util.spec_from_file_location("iasc_import_csv_to_db", importer_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load importer at {importer_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
