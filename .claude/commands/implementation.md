---
description: Explore a specific slice of a system (or standalone) outside the 10-step framework
---

Usage: `/implementation <system name and/or specific ask>`

Follow **Implementation Mode** as defined in `CLAUDE.md` for the request in
`$ARGUMENTS`. Read `CLAUDE.md` first if it isn't already in context — in
particular "The Three Modes" → "3. Implementation Mode", "File Frontmatter
Schema", and "End-of-Session Pipeline".

## Steps

1. **Check for a parent system.** If the ask names or clearly implies an
   existing system, load `systems/<kebab-case-name>.md` first for context
   (the 10-step design already on file). If no such file exists and the ask
   isn't really standalone, ask before proceeding.

2. **Not bound to the 10-step structure.** Handle whatever the specific ask
   requires — actual runnable code, request/response payloads, data
   structure walkthroughs, key-layout examples, focused explanation. Match
   the output to the ask, not to a template.

3. **If tied to a system**, append the output under a `## Implementation
   Notes` section in that system's `.md` file (create the section if it
   doesn't exist yet). Never overwrite or restructure the existing 10-step
   design to make room for this.

4. **If standalone** (no matching system), still write the output to a
   file rather than leaving it only in the chat:
   - If it's really a theory exploration, put it in `concepts/` (create or
     update the relevant `concepts/<kebab-case-name>.md`, with frontmatter
     per the Type B schema in `CLAUDE.md`).
   - Otherwise, ask the user where it should live before writing it.

5. **Run the End-of-Session Pipeline**, at minimum commit + push:
   1. Write/update the relevant file(s)
   2. Update `docs/TRACKER.md` if a tracked entry's status/notes changed
   3. Commit to git with a clear message
   4. Push to GitHub
   5. Call the local tool's API to update status — **skip and say so
      explicitly if not wired up yet**
   6. Sync to the corresponding Notion page — **skip and say so explicitly
      if not wired up yet**

   Never skip steps 3–4 silently, and call out any of 2, 5, or 6 that don't
   apply or aren't wired up yet.
