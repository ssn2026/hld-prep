---
service_name: Google Drive
grouping: (ungrouped)
status: Deep Dive Ready
labels: [SQL]
sections_complete: 10
last_session: 2026-08-12
notion_url: TBD
---

**Diagram:** `systems/diagrams/google-drive.drawio` (single page —
content-addressable chunk dedup on upload)

**Interactive trace:** `systems/implementations/google-drive-trace.html`
— a file upload where most chunks already exist in storage, and a sync
conflict that gets preserved instead of silently resolved

## 1. Requirement Gathering

**Functional**
- Upload/download files, folder hierarchy, sharing with permissions,
  version history, multi-device sync.

**Non-functional**
- Large files need chunked upload, same spirit as `youtube.md`'s
  resumable upload but with a new requirement layered on: **many
  different users upload many identical files** (a popular PDF, a
  common template, a stock photo) — storing every copy separately
  wastes enormous space.
- File metadata (folder structure, permissions, who-owns-what) needs
  strong consistency; the file *bytes* themselves are immutable once
  uploaded — a new version is a new blob, never an in-place edit.

## 2. Queries in Plain English

- Upload a file (or a new version of one).
- Download a file.
- List a folder's contents.
- Share a file/folder with specific permissions.
- Sync: get changes since my last known state.

## 3. State Diagram

```
File version:  UPLOADING → COMMITTED
Sync state:    IN_SYNC → CONFLICTED (until user resolves)
```

## 4. API Endpoints

| Endpoint | Notes |
|---|---|
| `POST /files/upload` | chunked, resumable — same shape as `youtube.md` |
| `GET /files/{id}` | |
| `GET /folders/{id}/children` | |
| `POST /files/{id}/share` | |
| `GET /sync/changes?since=` | |

## 5. Concurrency Requirements

**Content-addressable storage for deduplication — a new technique in
this repo.** Each file is split into chunks, and each chunk is hashed
(e.g. SHA-256). Before storing a chunk, the system checks whether a
chunk with that exact hash already exists anywhere in storage — if so,
the new upload just **references** the existing chunk instead of
storing a duplicate copy of the bytes. A file's full content is
recorded as a manifest: an ordered list of chunk hashes. Two users
uploading the identical PDF end up with two file records pointing at
the *same* underlying chunks, stored once. This is a genuinely
different mechanism from anything else built in this repo — dedup by
content, not by any application-level "have I seen this before" check.

**Sync conflicts are preserved, not silently resolved.** Two devices
editing the same file while offline, then both syncing, is a real and
common case. Unlike `key-value-storeba.md`'s last-write-wins (fine for
data where "newer wins" is the correct semantic) or
`leaderboard.md`'s tolerance for approximation, **silently picking a
winner here means silently discarding a user's work** — unacceptable
for personal files. The correct behavior is to detect the conflict (via
version vectors or a simple "based-on version" check) and create a
**conflicted copy** — both versions preserved, surfaced to the user to
reconcile manually. This is a deliberate divergence from this repo's
general LWW-when-possible lean, made explicit precisely because the
domain doesn't tolerate silent data loss the way scores or locations do.

## 6. Database Choice + Justification

- **File/folder metadata → SQL.** Hierarchical structure (folders
  contain files and folders), permissions, and version pointers need
  real relational integrity and strong consistency — a stale folder
  listing is a visible, confusing bug in a way a stale view count
  never is.
- **File bytes → object storage, content-addressed by chunk hash.**
  Same pairing as `netfilx.md` and `youtube.md`'s object storage +
  CDN, but keyed by content hash instead of a generated ID — this is
  what makes deduplication automatic rather than something to detect
  and handle separately.

## 7. Database Schema

```sql
CREATE TABLE files (file_id BIGINT PRIMARY KEY, folder_id BIGINT, name VARCHAR(255), owner_id BIGINT);
CREATE TABLE file_versions (
  version_id   BIGINT PRIMARY KEY,
  file_id      BIGINT NOT NULL REFERENCES files(file_id),
  manifest     JSONB NOT NULL,   -- ordered list of chunk hashes
  based_on     BIGINT,           -- version this was edited from, for conflict detection
  created_at   TIMESTAMP NOT NULL
);
CREATE TABLE chunks (chunk_hash VARCHAR(64) PRIMARY KEY, storage_url VARCHAR(300), ref_count INT NOT NULL DEFAULT 0);
```

## 8. Detailed Queries

```sql
SELECT chunk_hash FROM chunks WHERE chunk_hash = ANY(?);   -- which of these chunks already exist?

INSERT INTO chunks (chunk_hash, storage_url, ref_count) VALUES (?, ?, 1)
ON CONFLICT (chunk_hash) DO UPDATE SET ref_count = chunks.ref_count + 1;   -- new or referenced-again

INSERT INTO file_versions (version_id, file_id, manifest, based_on, created_at)
VALUES (?, ?, ?, ?, now());
```

## 9. Read/Write Paths

**Upload path:** client chunks the file locally, hashes each chunk →
asks the server which hashes it already has → uploads only the
*missing* chunks → server records the new version's manifest
referencing both the newly-uploaded and already-existing chunks.

**Sync path:** client requests changes since its last known sync
token → server compares the client's `based_on` version against the
file's current version → if they match, it's a clean fast-forward → if
they diverge (the file changed elsewhere since the client last synced
*and* the client also has local changes), a conflicted copy is created
instead of overwriting either side.

## 10. Scale Justification

- **Dedup directly reduces storage scale**, not just as a nice-to-have
  — popular files (templates, common attachments) get stored once
  regardless of upload count, and `ref_count` tracks when a chunk is
  finally safe to garbage-collect (all referencing versions deleted).
- **Metadata queries** (folder listings, permission checks) are
  standard relational access patterns at a scale SQL handles
  comfortably with proper indexing — this isn't a write-throughput
  problem the way live-ingest systems in this repo are.

## Implementation Notes

_(none yet beyond the interactive trace linked above)_
