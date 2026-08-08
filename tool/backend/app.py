"""HLD Tracker backend -- run with: python app.py
Serves the API + static frontend on http://localhost:8001
(port 8001, not 8000, so it can run alongside the DSA tracker)
"""

import datetime
import json
import sqlite3
import threading
import webbrowser
from pathlib import Path
from typing import Dict, List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import db
import logic

BASE_DIR = Path(__file__).parent
FRONTEND_DIR = BASE_DIR.parent / "frontend"

db.init_db()

app = FastAPI(title="HLD Tracker")
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


def today() -> str:
    return datetime.date.today().isoformat()


# --------------------------------------------------------------- schemas

class SystemCreate(BaseModel):
    service_name: str
    grouping: Optional[str] = None
    file_path: Optional[str] = None
    status: Optional[str] = "Not Started"
    labels: Optional[List[str]] = None
    sections_complete: Optional[int] = 0
    section_status: Optional[Dict[str, str]] = None
    last_session: Optional[str] = None
    notion_url: Optional[str] = None


class SystemUpdate(BaseModel):
    status: Optional[str] = None
    sections_complete: Optional[int] = None
    section_status: Optional[Dict[str, str]] = None
    last_session: Optional[str] = None
    notion_url: Optional[str] = None


class ConceptCreate(BaseModel):
    concept_name: str
    file_path: Optional[str] = None
    linked_systems: Optional[List[str]] = None
    last_reviewed: Optional[str] = None
    freshness: Optional[str] = "Check recommended"
    notion_url: Optional[str] = None


class ConceptUpdate(BaseModel):
    last_reviewed: Optional[str] = None
    freshness: Optional[str] = None
    linked_systems: Optional[List[str]] = None
    notion_url: Optional[str] = None


class SessionCreate(BaseModel):
    entry_type: str  # 'system' | 'concept'
    entry_name: str
    mode: str  # 'Interview' | 'Learning' | 'Implementation'
    session_date: Optional[str] = None
    notes: Optional[str] = None
    git_commit_sha: Optional[str] = None


# ---------------------------------------------------------------- systems

@app.get("/api/systems")
def list_systems(status: Optional[str] = None, grouping: Optional[str] = None):
    conn = db.get_conn()
    query = "SELECT * FROM systems WHERE 1=1"
    params = []
    if status is not None:
        query += " AND status=?"
        params.append(status)
    if grouping is not None:
        query += " AND grouping=?"
        params.append(grouping)
    query += " ORDER BY service_name"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [logic.system_row_to_dict(r) for r in rows]


@app.get("/api/systems/{service_name}")
def get_system(service_name: str):
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM systems WHERE service_name=?", (service_name,)).fetchone()
    conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="System not found")
    return logic.system_row_to_dict(row)


@app.post("/api/systems")
def create_system(body: SystemCreate):
    if body.status is not None and body.status not in db.SYSTEM_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {db.SYSTEM_STATUSES}")
    file_path = body.file_path or f"systems/{logic.kebab(body.service_name)}.md"
    section_status = body.section_status or logic.default_section_status()
    conn = db.get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO systems "
            "(service_name, grouping, file_path, status, labels, sections_complete, "
            "section_status, last_session, notion_url) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                body.service_name,
                body.grouping,
                file_path,
                body.status or "Not Started",
                logic.dumps(body.labels or []),
                body.sections_complete or 0,
                json.dumps(section_status),
                body.last_session,
                body.notion_url,
            ),
        )
        conn.commit()
    except sqlite3.IntegrityError as e:
        conn.close()
        raise HTTPException(status_code=409, detail=str(e))
    new_id = cur.lastrowid
    conn.close()
    return {"id": new_id}


@app.patch("/api/systems/{service_name}")
def update_system(service_name: str, body: SystemUpdate):
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM systems WHERE service_name=?", (service_name,)).fetchone()
    if row is None:
        conn.close()
        raise HTTPException(status_code=404, detail="System not found")

    if body.status is not None and body.status not in db.SYSTEM_STATUSES:
        conn.close()
        raise HTTPException(status_code=400, detail=f"status must be one of {db.SYSTEM_STATUSES}")
    if body.sections_complete is not None and not (0 <= body.sections_complete <= 10):
        conn.close()
        raise HTTPException(status_code=400, detail="sections_complete must be 0-10")

    status = body.status if body.status is not None else row["status"]
    sections_complete = body.sections_complete if body.sections_complete is not None else row["sections_complete"]
    section_status = (
        json.dumps(body.section_status) if body.section_status is not None else row["section_status"]
    )
    last_session = body.last_session if body.last_session is not None else row["last_session"]
    notion_url = body.notion_url if body.notion_url is not None else row["notion_url"]

    conn.execute(
        "UPDATE systems SET status=?, sections_complete=?, section_status=?, last_session=?, "
        "notion_url=?, updated_at=datetime('now') WHERE service_name=?",
        (status, sections_complete, section_status, last_session, notion_url, service_name),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


# --------------------------------------------------------------- concepts

@app.get("/api/concepts")
def list_concepts(freshness: Optional[str] = None):
    conn = db.get_conn()
    if freshness is not None:
        rows = conn.execute(
            "SELECT * FROM concepts WHERE freshness=? ORDER BY concept_name", (freshness,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM concepts ORDER BY concept_name").fetchall()
    conn.close()
    return [logic.concept_row_to_dict(r) for r in rows]


@app.get("/api/concepts/{concept_name}")
def get_concept(concept_name: str):
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM concepts WHERE concept_name=?", (concept_name,)).fetchone()
    conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Concept not found")
    return logic.concept_row_to_dict(row)


@app.post("/api/concepts")
def create_concept(body: ConceptCreate):
    if body.freshness is not None and body.freshness not in db.FRESHNESS_VALUES:
        raise HTTPException(status_code=400, detail=f"freshness must be one of {db.FRESHNESS_VALUES}")
    file_path = body.file_path or f"concepts/{logic.kebab(body.concept_name)}.md"
    conn = db.get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO concepts "
            "(concept_name, file_path, linked_systems, last_reviewed, freshness, notion_url) "
            "VALUES (?,?,?,?,?,?)",
            (
                body.concept_name,
                file_path,
                logic.dumps(body.linked_systems or []),
                body.last_reviewed,
                body.freshness or "Check recommended",
                body.notion_url,
            ),
        )
        conn.commit()
    except sqlite3.IntegrityError as e:
        conn.close()
        raise HTTPException(status_code=409, detail=str(e))
    new_id = cur.lastrowid
    conn.close()
    return {"id": new_id}


@app.patch("/api/concepts/{concept_name}")
def update_concept(concept_name: str, body: ConceptUpdate):
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM concepts WHERE concept_name=?", (concept_name,)).fetchone()
    if row is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Concept not found")

    if body.freshness is not None and body.freshness not in db.FRESHNESS_VALUES:
        conn.close()
        raise HTTPException(status_code=400, detail=f"freshness must be one of {db.FRESHNESS_VALUES}")

    last_reviewed = body.last_reviewed if body.last_reviewed is not None else row["last_reviewed"]
    freshness = body.freshness if body.freshness is not None else row["freshness"]
    linked_systems = (
        logic.dumps(body.linked_systems) if body.linked_systems is not None else row["linked_systems"]
    )
    notion_url = body.notion_url if body.notion_url is not None else row["notion_url"]

    conn.execute(
        "UPDATE concepts SET last_reviewed=?, freshness=?, linked_systems=?, notion_url=?, "
        "updated_at=datetime('now') WHERE concept_name=?",
        (last_reviewed, freshness, linked_systems, notion_url, concept_name),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


# --------------------------------------------------------------- sessions

@app.post("/api/sessions")
def create_session(body: SessionCreate):
    if body.entry_type not in db.ENTRY_TYPES:
        raise HTTPException(status_code=400, detail=f"entry_type must be one of {db.ENTRY_TYPES}")
    if body.mode not in db.SESSION_MODES:
        raise HTTPException(status_code=400, detail=f"mode must be one of {db.SESSION_MODES}")

    conn = db.get_conn()
    session_date = body.session_date or today()
    cur = conn.execute(
        "INSERT INTO sessions (entry_type, entry_name, mode, session_date, notes, git_commit_sha) "
        "VALUES (?,?,?,?,?,?)",
        (body.entry_type, body.entry_name, body.mode, session_date, body.notes, body.git_commit_sha),
    )
    conn.commit()

    flagged = []
    if body.entry_type == "system":
        flagged = logic.flag_concepts_for_system(conn, body.entry_name)

    new_id = cur.lastrowid
    conn.close()
    return {"id": new_id, "concepts_flagged": flagged}


# --------------------------------------------------------------- dashboard

@app.get("/api/dashboard")
def get_dashboard():
    conn = db.get_conn()
    data = logic.dashboard(conn)
    conn.close()
    return data


# ----------------------------------------------------------------- main

def _open_browser():
    webbrowser.open("http://localhost:8001")


if __name__ == "__main__":
    threading.Timer(1.0, _open_browser).start()
    uvicorn.run(app, host="127.0.0.1", port=8001, log_level="info")
