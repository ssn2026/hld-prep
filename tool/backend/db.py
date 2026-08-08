"""SQLite schema and connection helper."""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "hld_tracker.db"

SYSTEM_STATUSES = [
    "Not Started",
    "Concepts",
    "System Flow",
    "Service Flow",
    "Deep Dive Ready",
    "Interview Ready",
]

FRESHNESS_VALUES = ["Fresh", "Check recommended"]

SESSION_MODES = ["Interview", "Learning", "Implementation"]

ENTRY_TYPES = ["system", "concept"]

# The 10-step framework from CLAUDE.md, in order. Keys used inside
# systems.section_status (a JSON object mapping each key to
# "not_started" | "draft" | "complete").
SECTION_KEYS = [
    "1_requirements",
    "2_queries",
    "3_state_diagram",
    "4_api_endpoints",
    "5_concurrency",
    "6_db_choice",
    "7_db_schema",
    "8_detailed_queries",
    "9_read_write_paths",
    "10_scale_justification",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS systems (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_name TEXT NOT NULL UNIQUE,
    grouping TEXT,
    file_path TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Not Started' CHECK(status IN (
        'Not Started','Concepts','System Flow','Service Flow',
        'Deep Dive Ready','Interview Ready'
    )),
    labels TEXT NOT NULL DEFAULT '[]',
    sections_complete INTEGER NOT NULL DEFAULT 0 CHECK(sections_complete BETWEEN 0 AND 10),
    section_status TEXT NOT NULL DEFAULT '{}',
    last_session TEXT,
    notion_url TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS concepts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    concept_name TEXT NOT NULL UNIQUE,
    file_path TEXT NOT NULL,
    linked_systems TEXT NOT NULL DEFAULT '[]',
    last_reviewed TEXT,
    freshness TEXT NOT NULL DEFAULT 'Check recommended' CHECK(freshness IN ('Fresh','Check recommended')),
    notion_url TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_type TEXT NOT NULL CHECK(entry_type IN ('system','concept')),
    entry_name TEXT NOT NULL,
    mode TEXT NOT NULL CHECK(mode IN ('Interview','Learning','Implementation')),
    session_date TEXT NOT NULL,
    notes TEXT,
    git_commit_sha TEXT
);
"""


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_conn()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
