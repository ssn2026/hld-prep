---
service_name: Youtube
grouping: Video Based Systems
status: Deep Dive Ready
labels: [SQL, cassandra]
sections_complete: 10
last_session: 2026-08-12
notion_url: TBD
---

**Diagram:** `systems/diagrams/youtube.drawio` (single page —
progressive publish, contrasted with `netfilx.md`'s all-or-nothing
model)

**Interactive trace:** `systems/implementations/youtube-trace.html` —
a video becoming watchable at 360p while 1080p and 4K are still
transcoding in the background

## 1. Requirement Gathering

**Functional**
- Any user (not a curator) uploads a video — potentially large,
  potentially over a flaky connection, so upload must be resumable.
- Comments, likes, view counts, channel subscriptions.

**Non-functional — the genuine difference from `netfilx.md`:** a
YouTube uploader expects their video to be watchable *soon* after
upload, not after every quality rendition finishes. Netflix can afford
to wait for a title's full rendition set before publishing anything,
because publishing is scheduled and curated. YouTube's publish model
has to be **progressive** — visible as soon as *any* usable rendition
exists, with more qualities appearing in the manifest as they finish.

## 2. Queries in Plain English

- Upload a video (resumable, chunked).
- Get a video's current manifest (whichever renditions exist *right
  now*).
- Comment, like, subscribe.
- Get view count.

## 3. State Diagram

```
Video:  UPLOADING → PROCESSING → VISIBLE (first rendition ready) → FULLY_AVAILABLE (all ready)
```

This is a genuinely different shape from `netfilx.md`'s
`UPLOADED → TRANSCODING → READY` — there's an extra state
(`VISIBLE`) sitting *inside* what Netflix treats as a single opaque
"transcoding" phase, because that in-between state is user-facing here
and wasn't there.

## 4. API Endpoints

| Endpoint | Notes |
|---|---|
| `POST /videos/upload/init` | starts a resumable upload session |
| `PUT /videos/upload/{sessionId}/chunk` | uploads one chunk, tracks offset |
| `GET /videos/{id}/manifest` | returns whichever renditions currently exist |
| `POST /videos/{id}/comments` | |
| `POST /videos/{id}/like` | |

## 5. Concurrency Requirements

**Resumable upload:** the server tracks the highest contiguous byte
offset received per session; a dropped connection resumes from that
offset instead of restarting — this is an idempotency-adjacent
problem (retried chunk uploads for an offset already received should
no-op), same spirit as the idempotency-key pattern used throughout
this repo, applied to byte ranges instead of whole requests.

**Progressive rendition publish:** unlike `netfilx.md`, where the
title flips to `READY` only once *every* rendition succeeds, here each
rendition independently flips the video to at least `VISIBLE` the
moment the *first* one completes (typically the lowest quality,
fastest to encode), and the manifest simply reflects whatever renditions
exist at read time — no single "publish" event gates visibility.

**View count** is the same deliberately-approximate Redis counter
pattern as `broadcasting-system.md` and `leaderboard.md`'s general
philosophy — exactness isn't worth the coordination cost here either.

## 6. Database Choice + Justification

Reuses `netfilx.md`'s pairing directly: SQL for catalog/rendition
metadata, object storage + CDN for the actual video bytes, Cassandra
for high-write-volume data (view events, comments) — same reasoning,
same shape. The one addition: **upload session state** (byte offset,
chunk tracking) needs a small, fast, short-lived record per in-progress
upload — SQL is fine here too, given the volume (concurrent uploads,
not concurrent views).

## 7. Database Schema

```sql
CREATE TABLE videos (video_id BIGINT PRIMARY KEY, uploader_id BIGINT, status VARCHAR(20));
CREATE TABLE renditions (video_id BIGINT, quality VARCHAR(10), status VARCHAR(20), PRIMARY KEY (video_id, quality));
CREATE TABLE upload_sessions (session_id BIGINT PRIMARY KEY, video_id BIGINT, bytes_received BIGINT, total_bytes BIGINT);
```
Cassandra: `comments(video_id, comment_id, ...)`, partitioned by
`video_id` — same shape as every other Cassandra table in this repo.

## 8. Detailed Queries

```sql
UPDATE upload_sessions SET bytes_received = ? WHERE session_id = ?;

UPDATE renditions SET status = 'READY' WHERE video_id = ? AND quality = '360p';
UPDATE videos SET status = 'VISIBLE' WHERE video_id = ? AND status = 'PROCESSING';   -- first rendition only

SELECT quality FROM renditions WHERE video_id = ? AND status = 'READY';   -- manifest reflects whatever's ready now
```

## 9. Read/Write Paths

**Upload path:** client uploads chunks against a resumable session;
server tracks the offset; on resume, the client asks for the current
offset and continues from there instead of restarting.

**Publish path:** as soon as the *fastest* rendition (lowest quality)
finishes, the video flips to `VISIBLE` and is watchable — higher
qualities continue transcoding independently and simply append to the
manifest as they complete, with no further gate.

**Playback path:** identical to `netfilx.md` §9 — the manifest lists
CDN URLs, the client's player never routes through the app service for
segment bytes.

## 10. Scale Justification

Same core scale argument as `netfilx.md` §10 — CDN carries bytes, not
origin. The one new dimension is **upload throughput**, driven by
concurrent uploader count rather than viewer count, and it scales
independently: more upload-handling capacity doesn't need to track
viewership at all, the two are entirely decoupled workloads sharing
only the eventual object-storage/CDN destination.

## Implementation Notes

_(none yet beyond the interactive trace linked above)_
