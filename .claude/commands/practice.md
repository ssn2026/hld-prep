---
description: Run a Practice Mode drill session on SQL, Cassandra, Redis, or Kafka concepts
---

Usage: `/practice [sql|cassandra|redis|kafka] [concept name]`

Follow **Practice Mode** as defined in `CLAUDE.md` for the request in
`$ARGUMENTS`. Read `CLAUDE.md` first if it isn't already in context — in
particular "The Four Modes" → "4. Practice Mode".

## Steps

1. **Resolve the technology.** If `$ARGUMENTS` names one of
   sql/cassandra/redis/kafka, use it. Otherwise ask via a proper choice
   prompt (AskUserQuestion) — never assume, never guess from free text.

2. **Load state.** Read `concepts/practice/<tech>-question-bank.md`. If it
   doesn't exist yet, this technology hasn't been built out — say so
   explicitly and stop; don't improvise questions without the persistent
   bank backing them.
   - Scan top-to-bottom for the first `[ ]` (not yet attempted) question —
     that's the resume point.
   - If `$ARGUMENTS` named a specific concept, jump to that concept's
     first unchecked question instead, without marking any skipped
     concepts as done.

3. **Announce the resume point** (concept name, question) and leave the
   door open to redirect in the same message — don't force a
   concept-selection prompt every time if the user didn't ask for one.

4. **Run one question at a time.**
   - Present the scenario and question from the bank. If a concept's bank
     entries are exhausted and more practice is needed, generate a new one
     in the same voice/format and append it to the file before presenting it.
   - Wait for the user's actual attempt — never answer on their behalf.
   - Compare their attempt against the model answer honestly, not just
     encouragingly. Call out what's missing, not only what's right.
   - **If they got the core mechanism:** mark the question
     `[x] solved <today's date>` in the file, confirm/expand on the model
     answer, ask if they want to continue.
   - **If they missed the core mechanism** (not a minor syntax slip), or
     they say they're stuck: do not mark it solved and do not move on.
     Pull up the relevant section of `concepts/practice/<tech>-guide.md`,
     walk through it against their specific miss, then insert 1-2 new
     questions tagged `[remedial]` immediately *before* the struggled-on
     question in the file. Work through those, then return to the
     original question.

5. **Persist as you go.** Every checkbox flip and every remedial question
   added gets written to the file immediately, not batched to the end of
   the session. This file is the only state — there is no separate
   progress tracker to keep in sync.

6. **Session end / doc completion.** If every checkbox in the bank is now
   `[x]`, say so explicitly — that technology's practice is complete. On a
   normal stop before finishing, confirm what got marked done this session
   and where the resume point will be next time.

7. **Run the End-of-Session Pipeline** from `CLAUDE.md`: commit the
   updated question bank file(s) with a clear message, push. This mode
   only touches `docs/TRACKER.md` if a linked Type B concept's freshness
   genuinely changed (e.g. the guide itself was edited, not just the bank).
