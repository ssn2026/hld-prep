---
service_name: Netfilx
grouping: Video Based Systems
status: Deep Dive Ready
labels: [SQL, cassandra]
sections_complete: 10
last_session: 2026-08-12
notion_url: TBD
---

**Diagram:** `systems/diagrams/netfilx.drawio` (page 1: playback +
CDN architecture; page 2: content publishing state diagram)

**Interactive trace:** `systems/implementations/netfilx-trace.html` —
a title moving through the transcode pipeline to publish, then a
playback session that never touches the origin for video bytes

## 1. Requirement Gathering

**Functional**
- Browse/search a catalog of titles; play a title with adaptive
  bitrate streaming (multiple quality renditions, switching based on
  bandwidth).
- Track and resume watch progress per user, per title, per device.
- Content pipeline: ingest a raw upload, transcode into multiple
  renditions (240p–4K), publish once all renditions are ready.

**Non-functional**
- The defining constraint: **video bytes must never be served from the
  origin at streaming scale** — that's a CDN's job entirely. The app
  service's actual job is small: return a manifest, track progress,
  serve catalog/search. Get this separation wrong and the origin
  collapses under raw bandwidth no application tier is built to carry.
- Low time-to-first-frame, smooth quality switching under changing
  bandwidth.
- High availability for playback — a single CDN edge or segment
  failure shouldn't interrupt a stream (the player retries against a
  different edge).
- Storage at the petabyte scale for encoded video — object storage, not
  a database.

## 2. Queries in Plain English

**User-facing**
- Search/browse the catalog.
- Get a title's playback manifest (available renditions + segment
  locations).
- Save/resume watch progress.

**Internal**
- Ingest an uploaded title.
- Transcode into all target renditions (fan-out, one job per quality
  level).
- Publish once every rendition succeeds; generate the manifest.

## 3. State Diagram

Playback itself doesn't need a rich state machine — it's just a
position that moves forward. The **content publishing pipeline** is
where real state lives:

```
UPLOADED → TRANSCODING → READY (published)
                              ↓
                         TAKEN_DOWN
```

## 4. API Endpoints

**Client-facing**
| Endpoint | Notes |
|---|---|
| `GET /catalog/search?q=` | |
| `GET /titles/{titleId}` | |
| `GET /titles/{titleId}/manifest` | returns an HLS/DASH manifest — segment URLs point at the CDN, not this service |
| `POST /titles/{titleId}/watch-progress` | body: `{userId, positionSeconds}` — fire-and-forget, batched client-side |
| `GET /users/{userId}/watch-progress/{titleId}` | resume point |

**Internal**
| Endpoint | Notes |
|---|---|
| `POST /internal/content/upload` | triggers the transcode pipeline |
| `POST /internal/transcode/{jobId}/complete` | webhook per rendition job |

## 5. Concurrency Requirements

**Watch progress writes:** frequent (every few seconds per active
session), but correctness-wise this is about as low-stakes as writes
get — last-write-wins on position is completely fine, there's no
business invariant to protect the way there is for inventory or a
seat. This is a case where *not* over-engineering the concurrency story
is the right call.

**Transcode fan-out:** rendition jobs (240p, 480p, 720p, 1080p, 4K) run
in parallel as independent jobs against the same source upload — a
job queue, not a loop. Idempotency matters here too: a retried
"transcode this upload" trigger shouldn't kick off duplicate jobs for
a rendition already in flight, same unique-constraint-guard pattern
used across this repo (e.g. `amazon-order-management-system.md`'s
idempotency keys).

**CDN cache stampede:** a hot new release's first moments see every
early viewer requesting the same segments — if the CDN edge caches
happen to be cold simultaneously, that's a thundering herd straight at
origin storage. Mitigated with an **origin shield** layer (a
single-region cache tier CDN edges fall back to before ever reaching
origin) so a stampede collapses into one origin fetch per segment, not
one per edge×viewer.

## 6. Database Choice + Justification

- **Catalog metadata → SQL** (titles, genres, cast) — relational,
  moderate size, needs joins for browse/filter UX. A dedicated search
  index (e.g. Elasticsearch) is the natural enhancement for free-text
  search, layered on top rather than replacing SQL as the source of
  truth.
- **Watch progress → Cassandra**, not SQL. Same reasoning as
  `notification-system.md`'s `notification_log`: very high write
  volume, a simple, known-in-advance access pattern (`user_id` +
  `title_id`), no joins needed. This is exactly Cassandra's shape.
- **Video bytes → object storage (S3-class blob store), not a
  database at all.** Encoded renditions are immutable blobs; a
  database has no business holding them. The CDN sits in front of
  object storage, and that pairing — not any DB choice — is what
  actually carries streaming scale.

## 7. Database Schema

**SQL**
```sql
CREATE TABLE titles (
  title_id     BIGINT PRIMARY KEY,
  name         VARCHAR(200) NOT NULL,
  genre        VARCHAR(50),
  release_year INT,
  status       VARCHAR(20) NOT NULL   -- UPLOADED, TRANSCODING, READY, TAKEN_DOWN
);

CREATE TABLE renditions (
  title_id      BIGINT NOT NULL REFERENCES titles(title_id),
  quality       VARCHAR(10) NOT NULL,  -- 240p, 480p, 720p, 1080p, 4K
  status        VARCHAR(20) NOT NULL,  -- PENDING, ENCODING, READY, FAILED
  storage_url   VARCHAR(300),
  PRIMARY KEY (title_id, quality)
);
```

**Cassandra**
```sql
CREATE TABLE watch_progress (
  user_id          BIGINT,
  title_id         BIGINT,
  position_seconds INT,
  updated_at       TIMESTAMP,
  PRIMARY KEY (user_id, title_id)
);
```

## 8. Detailed Queries

```sql
-- watch progress upsert (Cassandra)
INSERT INTO watch_progress (user_id, title_id, position_seconds, updated_at)
VALUES (?, ?, ?, now());   -- overwrite semantics, last-write-wins is fine

-- rendition job completion
UPDATE renditions SET status = 'READY', storage_url = ? WHERE title_id = ? AND quality = ?;

-- publish once every rendition is READY
SELECT COUNT(*) FROM renditions WHERE title_id = ? AND status != 'READY';
-- if 0: UPDATE titles SET status = 'READY' WHERE title_id = ?;
```

## 9. Read/Write Paths

**Playback path:** client requests `/titles/{id}/manifest` → app
service returns an HLS/DASH manifest whose segment URLs point at the
CDN → **the client's player fetches every subsequent segment directly
from the CDN**, never touching the app service again for that stream.
Watch-progress POSTs are the only ongoing traffic back to the origin,
and those are cheap, async, and tolerant of loss.

**Ingest/publish path:** raw upload lands in object storage → triggers
a fan-out of rendition jobs → each job encodes its target quality and
uploads the result to object storage, then calls back to mark that
rendition `READY` → once all renditions for a title are `READY`, the
title flips to `READY` and its manifest is generated (pre-warmed into
the CDN, or left to populate on first request via the origin shield).

## 10. Scale Justification

Target: a title launch with millions of concurrent streams.

- **The core scale argument:** streaming bandwidth is the CDN's
  problem, not the origin's — a well-designed video platform's origin
  only ever handles manifest requests (one per playback *start*, not
  per segment) and watch-progress writes, both orders of magnitude
  smaller than raw video throughput. Sizing the origin for "millions of
  concurrent streams" would be solving the wrong number.
- **Watch-progress write volume:** even at millions of concurrent
  sessions posting every few seconds, this is squarely within
  Cassandra's linear write-scaling story — add nodes, not architecture.
- **Origin shield against stampede:** a hot release's first-moment
  surge collapses to one origin fetch per segment via the shield layer,
  regardless of how many thousands of edge caches are simultaneously
  cold for it.
- **Transcode throughput:** rendition jobs are embarrassingly parallel
  (each quality level is independent), so publishing scales by adding
  encoding workers, not by any architectural ceiling.

## Implementation Notes

_(none yet beyond the interactive trace linked above)_
