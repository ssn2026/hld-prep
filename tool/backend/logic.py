"""Business logic: JSON (de)serialization, slugs, dashboard aggregation, and
the concept-freshness auto-flag rule. Pure functions over a sqlite3
connection -- no FastAPI/HTTP concerns here."""

import json
import re

import db


def kebab(name: str) -> str:
    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def dumps(value) -> str:
    return json.dumps(value if value is not None else [])


def loads(value: str):
    return json.loads(value) if value else []


def default_section_status() -> dict:
    return {key: "not_started" for key in db.SECTION_KEYS}


def system_row_to_dict(row) -> dict:
    d = dict(row)
    d["labels"] = loads(d["labels"])
    d["section_status"] = json.loads(d["section_status"]) if d["section_status"] else {}
    return d


def concept_row_to_dict(row) -> dict:
    d = dict(row)
    d["linked_systems"] = loads(d["linked_systems"])
    return d


# ------------------------------------------------------- freshness auto-flag

def flag_concepts_for_system(conn, service_name: str):
    """When a session touches a Type A system, any Type B concept whose
    linked_systems includes that system is now potentially stale --
    flip its freshness to 'Check recommended'. Returns the list of
    concept_names that were flagged."""
    rows = conn.execute("SELECT concept_name, linked_systems FROM concepts").fetchall()
    flagged = []
    for row in rows:
        linked = loads(row["linked_systems"])
        if service_name in linked:
            conn.execute(
                "UPDATE concepts SET freshness='Check recommended', updated_at=datetime('now') "
                "WHERE concept_name=?",
                (row["concept_name"],),
            )
            flagged.append(row["concept_name"])
    if flagged:
        conn.commit()
    return flagged


# ------------------------------------------------------------- dashboard

def dashboard(conn) -> dict:
    systems_by_status = {
        r["status"]: r["c"]
        for r in conn.execute("SELECT status, COUNT(*) AS c FROM systems GROUP BY status").fetchall()
    }
    systems_by_grouping = {
        (r["grouping"] or "(ungrouped)"): r["c"]
        for r in conn.execute("SELECT grouping, COUNT(*) AS c FROM systems GROUP BY grouping").fetchall()
    }
    concepts_by_freshness = {
        r["freshness"]: r["c"]
        for r in conn.execute("SELECT freshness, COUNT(*) AS c FROM concepts GROUP BY freshness").fetchall()
    }
    recent_sessions = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM sessions ORDER BY session_date DESC, id DESC LIMIT 10"
        ).fetchall()
    ]
    return {
        "systems_by_status": systems_by_status,
        "systems_by_grouping": systems_by_grouping,
        "concepts_by_freshness": concepts_by_freshness,
        "recent_sessions": recent_sessions,
    }
