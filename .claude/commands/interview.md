---
description: Run an Interview Mode HLD session (user-driven, Claude fills gaps)
---

Usage: `/interview <system name or new problem statement>`

Follow **Interview Mode** as defined in `CLAUDE.md` for the system named in
`$ARGUMENTS`. Read `CLAUDE.md` first if it isn't already in context —
in particular "The Three Modes" → "1. Interview Mode", "File Frontmatter
Schema", "Type B Concept Notes", and "End-of-Session Pipeline".

## Steps

1. **Resume or create.** Resolve the system name to
   `systems/<kebab-case-name>.md`.
   - If the file already exists, load it and show the current section
     completion status (which of the 10 sections are filled vs. empty)
     before continuing. Resume the design — do not restart from scratch.
   - If it doesn't exist, create it with frontmatter (`status: Concepts` to
     start, `sections_complete: 0`, `last_session: never`,
     `notion_url: TBD`) and empty `##` headers for all 10 sections.

2. **Run the session.** The user drives their own thought process out
   loud — fill in gaps or missing pieces as they come up, but do not take
   over the design. Work can jump between sections non-linearly. Whenever
   a later-step decision requires revising an earlier section, say so
   explicitly and go make that revision immediately rather than letting the
   earlier section go stale.

3. **Cross-reference Type B concepts continuously.** As labels come up
   (Redis, Cassandra, Kafka, SQL, Database Internals, etc.), check whether
   the corresponding `concepts/*.md` file exists and whether its
   `linked_systems` already includes this system. If a relevant concept
   file is missing, stale, or the user seems unsure about it, mention it —
   don't force a detour, just surface it, per CLAUDE.md's Type B rules.

4. **Verify completeness before ending.** Before wrapping up, check all 10
   sections are filled. If any are missing, tell the user explicitly which
   ones — do not end the session silently with gaps.

5. **Update frontmatter.** Set `sections_complete`, `last_session` (today's
   date), and `status`. Set `status: Deep Dive Ready` only if all 10
   sections are complete and internally consistent; otherwise reflect the
   furthest stage actually reached.

6. **Run the End-of-Session Pipeline** from `CLAUDE.md`:
   1. Write/update the system's `.md` file
   2. Update `docs/TRACKER.md` for this entry
   3. Commit to git with a clear message
   4. Push to GitHub
   5. Call the local tool's API to update status — **if this endpoint isn't
      wired up yet, skip it and say so explicitly**
   6. Sync to the corresponding Notion page — **if this script isn't wired
      up yet, skip it and say so explicitly**

   Never skip steps 3–4 silently, and never skip 5–6 silently either —
   report which pipeline steps ran and which were skipped and why.
