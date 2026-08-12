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
sections as `##` headers, plus YAML frontmatter (schema defined below in
"File Frontmatter Schema").

### 2. Learning Mode

Same 10-step framework and same output file structure as Interview Mode,
but fully automated — Claude owns the entire design end-to-end for the
given system, and explains it in an engaging, easy-to-follow way,
referencing why each decision was made before moving to the next step.

**Diagrams are mandatory in Learning Mode.** Every Learning Mode session
must produce or update a draw.io-openable diagram file for the system —
see "Diagrams" below for format and required pages. This is part of the
definition of done for the session, same as the 10 sections.

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
notes, not a fixed template. Include YAML frontmatter (schema defined below
in "File Frontmatter Schema") with a `linked_systems` list (which Type A
systems depend on this concept — derive this from the same labels used in
the Notion tracker: Redis, Cassandra, Kafka, SQL, Database Internals).

Revision to a Type B concept is triggered relationally, not on a timer:
whenever an Interview or Learning session for a Type A system touches a
concept, check that concept's file. If it's missing, stale, or the user
seems unsure, proactively say so — e.g. "Cart's DB section touches SQL
row-locking — you haven't reviewed that concept file, want to do a quick
pass before we continue?" Never force this, just surface it.

## Diagrams

Learning Mode sessions must produce a `.drawio` file (mxGraph XML,
directly openable in draw.io / diagrams.net) at
`systems/diagrams/<kebab-case-name>.drawio` — same kebab-case stem as the
system's `.md` file. Use one multi-page file per system rather than
separate files per diagram:

- **Page 1 — Service/Component Architecture**: the services involved and
  the synchronous calls between them (mirrors the "Service Architecture"
  context in step 1 and the API endpoints in step 4).
- **Page 2 — Async/Event Flow** (only if the system has one): webhook →
  event bus → consumer fan-out, or equivalent — whatever the async half
  of the design actually is.
- **Page 3 — State Diagram**: a visual version of step 3, boxes and
  arrows for every state and transition (including any per-entity
  sub-states, e.g. order vs. line item vs. reservation).

Skip a page if the system genuinely has nothing for it (e.g. no async
flow, or step 3 concluded no state machine applies — say so instead of
drawing an empty page). Reference the diagram file's path from the
relevant section(s) of the system's `.md` file so it's discoverable

**Production-quality bar** (learned the hard way — the first pass at
this was rejected as "not production ready"):

- **Group shared edge infrastructure into one box.** Load Balancer, API
  Gateway, Authentication Service (and similar shared infra that isn't
  owned by the system being designed) go inside a single labeled
  container, not scattered as separate top-level boxes.
- **One edge per relationship, not two.** Never draw a request arrow and
  a response arrow separately between the same two nodes — that's what
  causes labels to stack on top of each other. Use a single
  double-headed arrow (`startArrow=block;endArrow=block`) with one
  concise label instead.
- **Solid = synchronous, dashed = async — and say so.** Every page needs
  a legend cell explicitly stating the convention. If a page mixes sync
  and async, split it into separate pages instead (e.g. sync checkout
  path on one page, async webhook/event-bus fan-out on another) rather
  than cramming both styles onto one crowded page.
- **Generous spacing.** No two boxes or labels should be close enough to
  visually collide. When in doubt, make the page bigger, not the nodes
  smaller.
without a separate index. Interview Mode and Implementation Mode do not
require diagrams unless the user asks.

## File Frontmatter Schema

### systems/*.md (Type A)

```yaml
---
service_name: <matches Notion "Service Name">
grouping: <matches Notion "HLD Grouping", or "ungrouped">
status: Not Started | Concepts | System Flow | Service Flow | Deep Dive Ready | Interview Ready
labels: [list, e.g. Redis, cassandra, SQL]
sections_complete: <0-10>
last_session: <date or "never">
notion_url: <url or "TBD">
---
```

### concepts/*.md (Type B)

```yaml
---
concept_name: <matches Notion "Service Name" for Concepts-status rows>
linked_systems: [list of Type A service_names that depend on this]
last_reviewed: <date or "never">
freshness: Fresh | Check recommended
notion_url: <url or "TBD">
---
```

## End-of-Session Pipeline

At the end of any Interview, Learning, or Implementation session that
produced or updated a file:

1. Write/update the relevant `.md` file(s) in `systems/` or `concepts/`,
   and for Learning Mode, the `.drawio` diagram file in
   `systems/diagrams/` (see "Diagrams")
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
