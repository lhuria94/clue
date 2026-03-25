"""Dashboard data loading — live queries from SQLite."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

import streamlit as st

from clue.db import init_db
from clue.export import generate_dashboard_data

DB_PATH = os.environ.get("CLUE_DB_PATH", str(Path.home() / ".claude" / "usage.db"))
CLAUDE_DIR = os.environ.get("CLUE_CLAUDE_DIR", str(Path.home() / ".claude"))
SCRUB_MODE = os.environ.get("CLUE_SCRUB", "").lower() in ("1", "true", "yes")


@st.cache_data(ttl=120, show_spinner="Loading data...")
def load_data(_db_path: str, scrub: bool = False) -> dict:
    """Query SQLite and return dashboard data dict."""
    conn, _ = init_db(Path(_db_path))
    data = generate_dashboard_data(conn, git_correlation=True, scrub=scrub, claude_dir=CLAUDE_DIR)
    conn.close()
    return data


def get_data() -> dict:
    """Load data with default settings."""
    return load_data(DB_PATH, scrub=SCRUB_MODE)


def filter_by_range(items: list[dict], days: int | None) -> list[dict]:
    """Filter daily-granularity data by date range."""
    if days is None:
        return items
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    return [item for item in items if item.get("d", "") >= cutoff]
