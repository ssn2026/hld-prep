# HLD Prep

This repo is for High-Level System Design (HLD) interview prep. It contains:

- `systems/` — per-system design docs (e.g. URL shortener, rate limiter, chat app)
- `concepts/` — per-concept theory notes (e.g. consistent hashing, CAP theorem, load balancing)
- `tool/` — a local tracking tool (`backend/` + `frontend/`) for practice sessions

This repo pairs with a Notion tracker, which serves as the human-readable dashboard.
This repo is the versioned source of truth for the actual content.

## Running the local tracking tool

The tool is a FastAPI + SQLite backend that also serves the static
`tool/frontend/` dashboard directly — one process, one port, same pattern
as the DSA practice tool.

First-time setup:

```
cd tool/backend
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe seed.py   # one-time: populate the DB from docs/TRACKER.md
```

Start it:

```
cd tool/backend
.\venv\Scripts\python.exe app.py
```

This opens **http://localhost:8001** in your browser automatically (port
8001, not 8000, so it can run alongside the DSA tracker). Stop it with
`Ctrl+C` in the terminal it's running in.

The dashboard is read-only — all writes (creating/updating systems and
concepts, logging sessions) happen via the API, driven by Claude Code
sessions through the `/interview`, `/learning`, and `/implementation`
commands per the end-of-session pipeline in `CLAUDE.md`, not from the UI.
