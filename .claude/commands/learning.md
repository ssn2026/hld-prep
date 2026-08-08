---
description: Run a Learning Mode HLD session (Claude drives, explains as it goes)
---

Usage: `/learning <system name>`

Follow **Learning Mode** as defined in `CLAUDE.md` for the system named in
`$ARGUMENTS`. Read `CLAUDE.md` first if it isn't already in context —
in particular "The Three Modes" → "2. Learning Mode", "File Frontmatter
Schema", "Type B Concept Notes", and "End-of-Session Pipeline".

## Steps

1. **Resume or create.** Same file handling as `/interview`: resolve the
   system name to `systems/<kebab-case-name>.md`.
   - If it already exists, load it and show current section completion
     status before continuing — resume, don't restart.
   - If it doesn't exist, create it with frontmatter (`status: Concepts` to
     start, `sections_complete: 0`, `last_session: never`,
     `notion_url: TBD`) and empty `##` headers for all 10 sections.

2. **Own the design end-to-end.** Unlike Interview Mode, Claude drives all
   10 sections in order:
   1. Requirement Gathering
   2. Queries in Plain English (User-facing / Internal)
   3. State Diagram (decide first whether a state machine even applies)
   4. API Endpoints (client-facing and internal)
   5. Concurrency Requirements (request-level serialization / resource-level
      contention)
   6. Database Choice + Justification (derived from steps 1–5)
   7. Database Schema
   8. Detailed Queries (for everything scoped in step 2)
   9. Read/Write Paths (for each query in step 8)
   10. Scale Justification (back-of-envelope math)

   For each step, explain the reasoning behind the decision in an engaging,
   easy-to-follow way — why this choice over the alternatives — before
   moving to the next step.

3. **Cross-reference Type B concepts continuously**, same as `/interview`:
   check `concepts/*.md` files against labels touched during the design; if
   one is missing, stale, or worth a look, mention it without forcing a
   detour.

4. **Verify completeness before ending.** All 10 sections must be filled by
   the end of the session — confirm this explicitly.

5. **Update frontmatter.** Set `sections_complete`, `last_session` (today's
   date), and `status` (`Deep Dive Ready` if all 10 sections are complete
   and internally consistent).

6. **Run the End-of-Session Pipeline** from `CLAUDE.md`, identical to
   `/interview`:
   1. Write/update the system's `.md` file
   2. Update `docs/TRACKER.md` for this entry
   3. Commit to git with a clear message
   4. Push to GitHub
   5. Call the local tool's API to update status — **skip and say so
      explicitly if not wired up yet**
   6. Sync to the corresponding Notion page — **skip and say so explicitly
      if not wired up yet**

   Never skip any of steps 3–6 silently.
