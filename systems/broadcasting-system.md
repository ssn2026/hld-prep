---
service_name: Broadcasting System
grouping: Video Based Systems
status: Deep Dive Ready
labels: [Redis, cassandra]
sections_complete: 10
last_session: 2026-08-12
notion_url: TBD
---

**Diagram:** `systems/diagrams/broadcasting-system.drawio` (single page
— live ingest/distribute, contrasted with `netfilx.md`'s batch model)

**Interactive trace:** `systems/implementations/broadcasting-system-trace.html`
— a stream going live, a chat message fanning out, and viewer count
staying approximate on purpose

## 1. Requirement Gathering

**Functional**
- A broadcaster starts a live stream; viewers watch in near-real-time
  with a live chat overlay; the stream ends and optionally archives.

**Non-functional — the defining contrast with `netfilx.md`:** Netflix
optimizes for *quality* with generous buffering; this system optimizes
for **glass-to-glass latency** (a few seconds, not the 30+ seconds
typical of standard HLS). This single requirement changes almost
everything: transcoding has to happen **in real time as bytes arrive**,
not as a batch job against a completed upload, and only a **sliding
window** of recent segments matters for live playback — old segments
either get dropped or archived separately, they don't sit in a
manifest a live viewer will ever request.

## 2. Queries in Plain English

- Start/end a live stream.
- Get the live manifest for an in-progress stream.
- Send/receive live chat messages.
- Get the current (approximate) viewer count.

## 3. State Diagram

```
Stream:  SCHEDULED → LIVE → ENDED → ARCHIVED
```

## 4. API Endpoints

| Endpoint | Notes |
|---|---|
| `POST /streams/{id}/start` | broadcaster begins ingest |
| `GET /streams/{id}/manifest` | live, sliding-window manifest — CDN URLs, same as `netfilx.md` |
| WebSocket `/streams/{id}/chat` | live chat, same connection-registry shape as `chat-systems.md` |
| `GET /streams/{id}/viewers` | approximate count |

## 5. Concurrency Requirements

**Real-time transcoding, not fan-out batch jobs.** `netfilx.md`'s
rendition pipeline runs N parallel jobs against a *complete* uploaded
file. Here, the source is an ongoing RTMP/WebRTC ingest — each
rendition's transcoder consumes the live feed continuously and pushes
out segments as they're ready, a streaming pipeline rather than a
batch fan-out.

**Chat fan-out reuses `chat-systems.md`'s exact mechanism** — a
connection registry routes messages to whichever server holds each
viewer's live connection, at potentially far higher fan-out (a popular
stream's chat can have far more concurrent recipients per message than
a typical 1:1 or small-group chat).

**Viewer count is deliberately approximate**, same philosophy as
`leaderboard.md`'s tolerance for eventual consistency: a Redis counter
incremented/decremented on connect/disconnect, synced periodically —
being off by a handful during a spike is fine, and insisting on exact
counts would mean paying a coordination cost nobody actually needs.

## 6. Database Choice + Justification

- **Live segments → object storage + CDN**, same pairing as
  `netfilx.md`, but only a **sliding window** is retained for live
  playback — segments older than the window either get pruned or moved
  to permanent VOD-style storage for post-stream archival, not kept in
  the live manifest.
- **Live chat → Cassandra**, identical reasoning to `chat-systems.md`.
- **Viewer count → Redis**, a simple counter — this is exactly the
  "don't reach for a heavier mechanism than the consistency
  requirement calls for" lesson from `leaderboard.md`.

## 7. Database Schema

Reuses `netfilx.md`'s and `chat-systems.md`'s schemas directly for
segments and chat messages. The one new piece:
```sql
CREATE TABLE streams (
  stream_id  BIGINT PRIMARY KEY,
  broadcaster_id BIGINT NOT NULL,
  status     VARCHAR(20) NOT NULL   -- SCHEDULED, LIVE, ENDED, ARCHIVED
);
```
Redis: `viewers:{streamId} -> count` (simple INCR/DECR on connect/disconnect).

## 8. Detailed Queries

```
INCR viewers:{streamId}     -- on connect
DECR viewers:{streamId}     -- on disconnect
GET viewers:{streamId}      -- approximate current count
```

## 9. Read/Write Paths

**Ingest/distribute path:** broadcaster's RTMP/WebRTC feed → real-time
transcoder produces each rendition continuously → segments push to
object storage/CDN as they're ready → viewers' manifests reflect only
the sliding window of recent segments.

**Chat path:** identical to `chat-systems.md` §9, at higher fan-out.

**End-of-stream path:** status → `ENDED`; the accumulated segments
either get pruned (ephemeral stream) or handed to `netfilx.md`'s
publish pipeline for permanent VOD archival — the same publish
mechanism, entered from a different starting point.

## 10. Scale Justification

- **Ingest is per-stream, not aggregate** — one broadcaster's feed
  needs one real-time transcode pipeline; this scales by adding
  transcoder capacity per concurrent live stream, independent of
  viewer count.
- **Distribution scales exactly like `netfilx.md`** — the CDN carries
  viewer-facing bandwidth, not the origin.
- **Chat fan-out** for a hugely popular stream is the one place this
  system can exceed `chat-systems.md`'s assumptions — see that
  system's §10 note on routing large-group fan-out through Kafka
  instead of direct server-to-server RPC once fan-out size crosses a
  threshold; a viral live stream's chat is exactly that threshold case.

## Implementation Notes

_(none yet beyond the interactive trace linked above)_
