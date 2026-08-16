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

## The Four Modes

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

### 4. Practice Mode

Triggered by `/practice`. Unlike the other three modes, this isn't about
designing a Type A system or writing a Type B concept note — it's a
self-quiz drill against concepts already established across this repo's
systems and concepts.

Covers four technologies: SQL, Cassandra, Redis, Kafka. Each gets a pair
of files under `concepts/practice/`:

- **`<tech>-guide.md`** — the complete reference guide, concept by
  concept. Doubles as (and gets cross-linked from) the corresponding
  Type B concept row(s) in `docs/TRACKER.md` where they overlap — e.g.
  the SQL guide covers what were separately-tracked "SQL Database
  Locking", "2 Phase Commit", and "3 Phase Commit" rows, plus ground
  those rows never covered (isolation levels, MVCC, schema-design
  methodology).
- **`<tech>-question-bank.md`** — the drill content, organized by
  concept, each concept holding multiple `{scenario, question, model
  answer}` problems.

**Progress is persisted as checkboxes inline in the question bank file
itself** — `[ ] not yet attempted` / `[x] solved <date>` — not a separate
state file. Resuming `/practice <tech>` finds the first unchecked
question in document order and continues there; naming a specific
concept jumps there instead, without marking skipped concepts as done.
When every checkbox in a bank is checked, that technology's practice is
complete — the document's completion state *is* the practice's
completion state.

**Struggling on a question is handled by remediation, not by pushing
forward.** If an attempt misses the core mechanism, don't mark it
solved. Walk through the relevant section of that technology's guide
against the specific miss, insert 1-2 new questions tagged `[remedial]`
immediately before the struggled-on question in the bank file, work
through those, then return to the original. Remedial questions get
written into the file for real — they persist for future sessions too,
growing the bank rather than being thrown away after one conversation.

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
without a separate index. Interview Mode and Implementation Mode do not
require diagrams unless the user asks.

The same convention applies to Type B concept notes when a diagram
genuinely earns its place there (on request, not automatic) — mirror the
path under `concepts/diagrams/<kebab-case-name>.drawio` instead of
`systems/diagrams/`.

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

## Interactive Trace

An **optional, on-request** deliverable — not part of the default
Learning Mode output (that's still just the 10 sections + `.drawio`
diagram). Build one when the user asks for a clickable/interactive
walkthrough, an "explainer UI," or similar — e.g. "give me an
interactive trace for Cart," "make this clickable." It's a
self-contained HTML page that walks one concrete example request hop by
hop through the system's real topology, showing the exact payload each
service receives, the SQL it runs, and live state across every table as
they change.

**File convention:** `systems/implementations/<kebab-case-name>-trace.html`
(same kebab-case stem as the system), linked from that system's
`## Implementation Notes` section. For a Type B concept note, mirror this
under `concepts/implementations/<kebab-case-name>-trace.html` instead,
linked from the concept's own `.md` file.

**Build it cheap — copy, don't regenerate:**

1. Copy `systems/implementations/_template/interactive-trace-template.html`
   to the new path. This template already contains the full working
   engine (CSS design tokens, diagram highlighting, step/branch state
   machine, DB-table renderer, controls) — proven in production on the
   Amazon Order Management System trace. **Never regenerate this engine
   from scratch per system** — that's the token cost this convention
   exists to avoid.
2. Edit ONLY the two blocks marked `SYSTEM DATA — edit this` inside the
   copy:
   - the page-head text + the `<svg class="topology">` diagram (system
     topology genuinely differs per system, so this part is unavoidably
     bespoke — reuse the same node/edge visual vocabulary described in
     the template's comments, which already follows the diagram
     production-quality bar above)
   - the JS data block: `SEED`, `TABLE_KEYS`, `TABLE_LABEL`,
     `STATUS_COLORS`, `STEPS`, and optionally `BRANCH` — the template's
     header comment documents the exact step-object contract
   Everything below `END SYSTEM DATA` in the script is the generic
   engine — leave it untouched.
3. If the engine itself needs a real fix or new capability, fix it once
   in the template (and only backport to already-generated trace files
   if the user asks) rather than patching each system's copy separately.
4. Validate the result renders (structurally check tag balance if unable
   to open a browser), publish via the Artifact tool for an interactive
   preview link, link it from the system's `## Implementation Notes`,
   then run the standard end-of-session pipeline.

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
   `systems/diagrams/` (see "Diagrams"); if an interactive trace was
   built or updated this session, include its `.html` file in
   `systems/implementations/` too (see "Interactive Trace")
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
