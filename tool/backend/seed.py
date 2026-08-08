"""One-time seed script: parses docs/TRACKER.md and populates the systems
and concepts tables, so the tool starts in sync with what's already in the
repo. Run with: python seed.py

Safe to re-run -- if the tables already have rows, it prints a message and
exits without changing anything (delete hld_tracker.db to reseed from
scratch).

Note on Type B "Linked Systems (labels)": TRACKER.md's column of that name
holds *labels* (e.g. "SQL", "Redis"), not actual service names, even though
concepts.linked_systems is defined as a list of service_names. This script
derives the real service-name list by matching each concept's label tokens
against the labels already seeded on the systems rows -- the same
derivation rule CLAUDE.md specifies for Type B frontmatter.
"""

import json
import re
from pathlib import Path

import db
import logic

TRACKER_PATH = Path(__file__).parent.parent.parent / "docs" / "TRACKER.md"


def _parse_table(lines, header_prefix):
    """Find a markdown table whose header row starts with header_prefix and
    return its data rows as lists of cell strings."""
    start = None
    for i, line in enumerate(lines):
        if line.strip().startswith(header_prefix):
            start = i
            break
    if start is None:
        raise ValueError(f"Table with header '{header_prefix}' not found in TRACKER.md")

    rows = []
    # start+1 is the |---|---| separator row; data begins at start+2
    for line in lines[start + 2:]:
        line = line.rstrip("\n")
        if not line.strip().startswith("|"):
            break
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        rows.append(cells)
    return rows


def _labels_from(raw: str):
    if raw == "-" or not raw:
        return []
    return [tok.strip() for tok in raw.split(",") if tok.strip()]


def _grouping_from(raw: str):
    if raw in ("-", "(ungrouped)", ""):
        return None
    return raw


def _date_from(raw: str):
    return None if raw in ("never", "-", "") else raw


def _notion_url_from(raw: str):
    return None if raw.startswith("TBD") or raw in ("-", "") else raw


def seed():
    db.init_db()
    conn = db.get_conn()

    existing_systems = conn.execute("SELECT COUNT(*) AS c FROM systems").fetchone()["c"]
    existing_concepts = conn.execute("SELECT COUNT(*) AS c FROM concepts").fetchone()["c"]
    if existing_systems > 0 or existing_concepts > 0:
        print(
            f"Already seeded ({existing_systems} systems, {existing_concepts} concepts) -- "
            f"skipping. Delete hld_tracker.db to reseed from scratch."
        )
        conn.close()
        return

    text = TRACKER_PATH.read_text(encoding="utf-8")
    lines = text.splitlines()

    type_a_rows = _parse_table(lines, "| Service Name")
    type_b_rows = _parse_table(lines, "| Concept Name")

    # ---- Type A: systems ----
    for cells in type_a_rows:
        service_name, grouping_raw, _file, sections_raw, status_raw, labels_raw, last_session_raw, notion_raw = cells
        grouping = _grouping_from(grouping_raw)
        labels = _labels_from(labels_raw)
        sections_complete = int(re.match(r"(\d+)", sections_raw).group(1))
        file_path = f"systems/{logic.kebab(service_name)}.md"

        conn.execute(
            "INSERT INTO systems "
            "(service_name, grouping, file_path, status, labels, sections_complete, "
            "section_status, last_session, notion_url) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                service_name,
                grouping,
                file_path,
                status_raw,
                json.dumps(labels),
                sections_complete,
                json.dumps(logic.default_section_status()),
                _date_from(last_session_raw),
                _notion_url_from(notion_raw),
            ),
        )
    conn.commit()

    # Build a case-insensitive label -> [service_name, ...] index from what
    # was just inserted, used to derive Type B linked_systems below.
    label_index = {}
    for row in conn.execute("SELECT service_name, labels FROM systems").fetchall():
        for label in json.loads(row["labels"]):
            label_index.setdefault(label.lower(), []).append(row["service_name"])

    # ---- Type B: concepts ----
    for cells in type_b_rows:
        concept_name, linked_labels_raw, _file, last_reviewed_raw, freshness_raw, notion_raw = cells
        label_tokens = _labels_from(linked_labels_raw)

        linked_systems = []
        for token in label_tokens:
            for name in label_index.get(token.lower(), []):
                if name not in linked_systems:
                    linked_systems.append(name)

        file_path = f"concepts/{logic.kebab(concept_name)}.md"

        conn.execute(
            "INSERT INTO concepts "
            "(concept_name, file_path, linked_systems, last_reviewed, freshness, notion_url) "
            "VALUES (?,?,?,?,?,?)",
            (
                concept_name,
                file_path,
                json.dumps(linked_systems),
                _date_from(last_reviewed_raw),
                freshness_raw,
                _notion_url_from(notion_raw),
            ),
        )
    conn.commit()

    n_systems = conn.execute("SELECT COUNT(*) AS c FROM systems").fetchone()["c"]
    n_concepts = conn.execute("SELECT COUNT(*) AS c FROM concepts").fetchone()["c"]
    conn.close()

    print(f"Seeded {n_systems} systems and {n_concepts} concepts from {TRACKER_PATH}")


if __name__ == "__main__":
    seed()
