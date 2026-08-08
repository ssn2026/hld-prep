# HLD Interview Prep — Operating Rules

## Purpose

This repo tracks High-Level System Design (HLD) interview preparation. There
are two distinct content types:

- **Type A — Service Design systems** (e.g. Cart Service, Hotel Reservation,
  Chat Systems). These go through a structured 10-step design framework
  across three modes (see below).
- **Type B — Theory / Component Internals** (e.g. Redis Internals, Kafka
  Internals, Distributed Locking, SAGA, 2PC, Authentication, Load
  Balancing). These are **not** designed step-by-step — they're living notes
  that get revised over time, and get cross-linked to the Type A systems
  that depend on them.

## The Three Modes

### 1. Interview Mode

Triggered by a prompt like "Implement Cart service for an Amazon-like
system, 10K RPS, must scale."

This is a **collaborative, interactive** session — the user drives their own
thought process out loud, and Claude fills in gaps or missing pieces as it
goes. Claude does **not** take over the design. By the end of the session,
all 10 sections below must be fully complete, even if they weren't visited
in order.

The 10 sections (non-linear — work on a later section can require revising
an earlier one; when that happens, explicitly go back and update the
earlier section rather than leaving it stale):

1. Requirement Gathering
2. Queries in Plain English (split: User-facing / Internal)
3. State Diagram (figure out if a state machine even applies — some
   entities like Leaderboard or Chat messages have no state transitions,
   which itself signals simpler storage is fine)
4. API Endpoints (user/client-facing and internal)
5. Concurrency Requirements (split: User-request-level serialization /
   Resource-level contention)
6. Database Choice + Justification (derived from steps 1–5, not assumed
   upfront)
7. Database Schema
8. Detailed Queries (for everything scoped in step 2)
9. Read/Write Paths (for each query in step 8)
10. Scale Justification (back-of-envelope math proving the design meets the
    stated scale, industry-standard style)

Each system gets a file at `systems/<kebab-case-name>.md` with these 10
sections as `##` headers, plus YAML frontmatter (schema defined in
`docs/TRACKER.md`).

### 2. Learning Mode

Same 10-step framework and same output file structure as Interview Mode,
but fully automated — Claude owns the entire design end-to-end for the
given system, and explains it in an engaging, easy-to-follow way,
referencing why each decision was made before moving to the next step.

### 3. Implementation Mode

Not tied to the 10-step framework. Used to explore a specific slice of an
already-designed system (or occasionally standalone, with no parent
system) — e.g. "show me what the Redis keys look like for Cart",
"implement the WebSocket handler for Chat", "how does Kafka partition this
topic." Output can be actual runnable code, request/response payloads, or
focused explanation — whatever the ask requires. If tied to a system, note
it in that system's file under a `## Implementation Notes` section (append,
don't overwrite the 10-step design).

## Type B Concept Notes

Each concept gets a file at `concepts/<kebab-case-name>.md` — freeform
notes, not a fixed template. Include YAML frontmatter with a
`linked_systems` list (which Type A systems depend on this concept — derive
this from the same labels used in the Notion tracker: Redis, Cassandra,
Kafka, SQL, Database Internals).

Revision to a Type B concept is triggered relationally, not on a timer:
whenever an Interview or Learning session for a Type A system touches a
concept, check that concept's file. If it's missing, stale, or the user
seems unsure, proactively say so — e.g. "Cart's DB section touches SQL
row-locking — you haven't reviewed that concept file, want to do a quick
pass before we continue?" Never force this, just surface it.

## End-of-Session Pipeline

At the end of any Interview, Learning, or Implementation session that
produced or updated a file:

1. Write/update the relevant `.md` file(s) in `systems/` or `concepts/`
2. Update `docs/TRACKER.md` status for that entry
3. Commit to git with a clear message (e.g. "Cart Service: complete
   sections 1-6, DB choice justified")
4. Push to GitHub
5. Call the local tool's API to update status (endpoint details in
   `tool/backend` — added in a later setup step)
6. Sync the doc content + status to the corresponding Notion page (script
   details added in a later setup step)

Do not skip steps 3–6 silently — if any step fails (e.g. Notion sync
unreachable), tell the user explicitly rather than silently continuing.

## File Naming

Kebab-case, matching the Notion tracker's Service Name field as closely as
possible (e.g. "Amazon Order Managment System" → `amazon-order-management-system.md`).
