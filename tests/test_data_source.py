"""
Tests for uploaded data-source helpers and per-session database switching.
"""

import shutil
import sqlite3
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from data_source import prepare_uploaded_sqlite_database
from queries import reset_active_db_path, search_donors, set_active_db_path


DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "donors.db"

pytestmark = pytest.mark.skipif(
    not DEFAULT_DB_PATH.exists(),
    reason="Database not found. Run: python data/generate_mock_data.py",
)


def test_prepare_uploaded_sqlite_database_persists_and_validates():
    uploaded = prepare_uploaded_sqlite_database(
        file_name="custom_donors.db",
        file_bytes=DEFAULT_DB_PATH.read_bytes(),
        session_id="test-upload-session",
    )
    assert uploaded["kind"] == "uploaded_db"
    assert uploaded["label"] == "Uploaded database: custom_donors.db"
    assert Path(uploaded["db_path"]).exists()


def test_search_donors_uses_active_database_path(tmp_path):
    custom_db = tmp_path / "empty_copy.db"
    shutil.copyfile(DEFAULT_DB_PATH, custom_db)

    conn = sqlite3.connect(str(custom_db))
    try:
        conn.execute("DELETE FROM interactions")
        conn.execute("DELETE FROM gifts")
        conn.execute("DELETE FROM contacts")
        conn.commit()
    finally:
        conn.close()

    token = set_active_db_path(custom_db)
    try:
        result = search_donors(limit=5)
    finally:
        reset_active_db_path(token)

    assert result["count"] == 0
    assert "No donors found" in result["summary"]
