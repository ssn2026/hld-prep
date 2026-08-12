---
service_name: Zoom
grouping: Video Based Systems
status: Deep Dive Ready
labels: [SQL]
sections_complete: 10
last_session: 2026-08-12
notion_url: TBD
---

**Diagram:** `systems/diagrams/zoom.drawio` (page 1: SFU vs mesh vs MCU
comparison; page 2: signaling + media plane separation)

**Interactive trace:** `systems/implementations/zoom-trace.html` — a
4-person meeting forming through the SFU, and what changes when a 5th
joins

## 1. Requirement Gathering

**Functional**
- Create/join a meeting; multi-party audio/video; screen share.

**Non-functional**
- **Bidirectional, interactive real-time** — meaningfully stricter than
  `broadcasting-system.md`'s one-way low latency. A broadcast viewer
  tolerates a few seconds of delay; a conversation participant
  perceives even a few hundred milliseconds of added latency as
  awkward. This rules out CDN-style distribution entirely — CDNs are
  built for fan-out from one source, not N-way interactive exchange.

## 2. Queries in Plain English

- Create/join a meeting.
- Send/receive audio and video streams.
- Share a screen.

## 3. State Diagram

```
Meeting:      SCHEDULED → IN_PROGRESS → ENDED
Participant:  JOINING → CONNECTED → LEFT
```

## 4. API Endpoints

| Endpoint | Notes |
|---|---|
| `POST /meetings` | create |
| `POST /meetings/{id}/join` | returns signaling info + SFU assignment |
| WebSocket `/meetings/{id}/signaling` | ICE candidates, offer/answer exchange |

Media itself is **not** an HTTP/WebSocket API — it's a WebRTC (UDP)
media path, established once signaling completes.

## 5. Concurrency Requirements

**The real architectural decision: how does one participant's video
reach N others?** Three options, genuinely different trade-offs:

| Approach | Client upload | Server work | Scales to |
|---|---|---|---|
| **P2P mesh** — every participant sends directly to every other | O(N) streams up | none | ~4-5 participants before mesh connections overwhelm clients |
| **MCU** — server decodes every stream, mixes into one composite | O(1) — one stream up, one down | Very high — full decode + re-encode per participant | Limited by server transcoding CPU, expensive at scale |
| **SFU** (chosen) — server forwards streams without decoding | O(1) up, O(N-1) down (or fewer via active-speaker selection) | Low — packet forwarding only, no transcoding | Scales to large meetings; this is what real Zoom/Meet use |

**SFU is the right default** because it moves the O(N) cost to
*bandwidth* (cheap, horizontally distributable) rather than *CPU*
(expensive, the actual bottleneck in the MCU model) — the server never
needs to understand the content of a stream, only relay packets to the
right set of recipients. Large meetings additionally use **simulcast**
(each sender uploads multiple quality layers; the SFU forwards only
the layer each receiver's bandwidth supports) and **active-speaker
selection** (only forward video for currently-speaking participants at
full res to reduce receiver-side bandwidth) rather than forwarding
every stream to every participant unconditionally.

## 6. Database Choice + Justification

**Media never touches a database at all** — it's a live UDP path
through the SFU, gone the instant it's relayed (unless recording is
explicitly enabled, which writes to object storage, the same pairing
`netfilx.md` uses). The **signaling/control plane** — meeting metadata,
participant list, join tokens — is small, relational, low-volume: SQL
is more than sufficient, the same reasoning as
`unique-id-generator.md`'s worker registry.

## 7. Database Schema

```sql
CREATE TABLE meetings (meeting_id BIGINT PRIMARY KEY, host_id BIGINT NOT NULL, status VARCHAR(20));
CREATE TABLE participants (
  meeting_id BIGINT NOT NULL, user_id BIGINT NOT NULL, sfu_id VARCHAR(50) NOT NULL, status VARCHAR(20),
  PRIMARY KEY (meeting_id, user_id)
);
```

## 8. Detailed Queries

```sql
INSERT INTO participants (meeting_id, user_id, sfu_id, status) VALUES (?, ?, ?, 'CONNECTED');
SELECT user_id, sfu_id FROM participants WHERE meeting_id = ? AND status = 'CONNECTED';
```

## 9. Read/Write Paths

**Join path (signaling, control plane):** participant → Signaling
Service → assigned to an SFU instance (typically the one nearest, or
already hosting the meeting) → exchanges ICE candidates/SDP
offer-answer over the WebSocket → establishes a direct WebRTC media
path to that SFU.

**Media path (data plane, no database involved):** participant's
audio/video → SFU → relayed to every other connected participant's
established WebRTC path, at whatever quality layer (simulcast) their
own connection supports.

## 10. Scale Justification

- **Per-meeting cost is O(N) bandwidth at the SFU, not O(N²)** the way
  mesh would be, and not O(N) *transcoding* CPU the way MCU would be —
  this is the entire justification for the SFU choice in section 5.
- **Horizontal scale is per-meeting, not global:** each meeting gets
  assigned to one SFU instance (or a small cluster for very large
  meetings); adding capacity means adding SFU instances, with no
  cross-meeting coordination needed.
- **Recording**, when enabled, hands off to the exact same
  object-storage + eventual-transcode pipeline as `netfilx.md` — no
  new mechanism needed for that slice.

## Implementation Notes

_(none yet beyond the interactive trace linked above)_
