---
service_name: Whatsapp User Socket info
grouping: Social Media
status: Deep Dive Ready
labels: [Redis]
sections_complete: 10
last_session: 2026-08-12
notion_url: TBD
---

**Diagram:** `systems/diagrams/whatsapp-user-socket-info.drawio`
(single page — multi-device connection registry and delivery fan-out)

**Interactive trace:** `systems/implementations/whatsapp-user-socket-info-trace.html`
— a user connected from two devices at once, a message delivered to
both, and one device going quiet without an explicit disconnect

**This is the full-depth version** of the connection registry
`chat-systems.md` used but deliberately didn't build out — see that
system's section 5 for the essential mechanism; this is where the real
complexity (multi-device, presence, liveness) lives.

## 1. Requirement Gathering

**Functional**
- Track which connection server(s) hold each user's live socket(s).
- Support **multiple simultaneous connections per user** — phone, web,
  desktop all connected at once is the normal case, not an edge case.
- Track presence (online/offline/last-seen).

**Non-functional**
- Extremely high write frequency — every connect, disconnect, and
  heartbeat, for a huge concurrent user base.
- Has to be fast enough to sit in the critical path of every message
  send, as `chat-systems.md` §9 already established.

## 2. Queries in Plain English

- Register a device connection (which server holds it).
- Get all of a user's active device connections (for delivery fan-out).
- Get a user's presence (online / last-seen).
- Heartbeat a connection to keep it alive.

## 3. State Diagram

```
Connection (per device):  ACTIVE → EXPIRED (missed heartbeats) / CLOSED (explicit disconnect)
Presence (per user):      ONLINE (>=1 active connection) → OFFLINE (0 active connections)
```

## 4. API Endpoints

Mostly internal, called by connection servers themselves:

| Endpoint | Notes |
|---|---|
| `POST /internal/connections/register` | body: `{userId, deviceId, serverId}` |
| `POST /internal/connections/{userId}/{deviceId}/heartbeat` | refreshes TTL |
| `GET /internal/connections/{userId}` | all active devices, for delivery |
| `GET /users/{userId}/presence` | user-facing, online/last-seen |

## 5. Concurrency Requirements

**Multi-device means the registry is one-to-many, not one-to-one.**
`chat-systems.md`'s simplified version implied `userId → serverId`; the
real shape is `userId → {deviceId: serverId}`, because a message has to
reach *every* device a user is currently active on, not just one. This
changes delivery from "look up one server" to "look up N servers,
fan out to each" — a small internal fan-out, same spirit as
`notification-system.md`'s per-channel fan-out but scoped to one
user's own devices.

**TTL-based liveness — no explicit disconnect required.** Each
device's connection entry carries a short TTL (e.g. 60s), refreshed by
a client heartbeat every 20-30s. A crashed app or dropped connection
simply stops heartbeating, and the entry expires on its own — the same
"TTL as the primary revocation mechanism" pattern as
`nearyby-friends.md`'s share sessions, applied to liveness instead of
authorization.

**Presence derives from connection count, not a separate flag.** A
user is `ONLINE` if they have at least one active connection entry,
`OFFLINE` if they have none — this is a computed property, not a
column that could drift out of sync with the actual connections.

## 6. Database Choice + Justification

**Redis, unambiguously** — this is inherently the kind of ephemeral,
extremely-high-write-frequency, TTL-native state Redis is built for.
Each device connection is its own key (`conn:{userId}:{deviceId}`)
rather than one structure per user, specifically so Redis's native
per-key TTL handles expiry automatically — no separate sweep job
needed, unlike patterns elsewhere in this repo that need an explicit
reconciler.

## 7. Database Schema

```
conn:{userId}:{deviceId} -> serverId       TTL = 60s, refreshed by heartbeat
```
No SQL involved at all — this system has no durable state; a
connection registry entry that's gone is correctly gone, not a bug.

## 8. Detailed Queries

```
SET conn:U-14:mobile "conn-server-3" EX 60
SET conn:U-14:web "conn-server-7" EX 60

KEYS conn:U-14:*    -- (in production: SCAN, not KEYS, to avoid blocking)
-> conn:U-14:mobile -> conn-server-3
-> conn:U-14:web    -> conn-server-7
```

## 9. Read/Write Paths

**Connect path:** device establishes a WebSocket to some connection
server → that server registers `conn:{userId}:{deviceId} = serverId`
with a TTL.

**Heartbeat path:** client pings periodically → server refreshes the
same key's TTL — cheap, no new data, just extends liveness.

**Delivery path (used by `chat-systems.md` §9):** sender's server needs
to route a message → scans `conn:{userId}:*` → gets every active
device's owning server → fans out to each in parallel, same message,
multiple destinations.

**Disconnect path:** explicit close deletes the specific device's key
immediately; an unclean disconnect (crash, dropped connection) is
instead caught by the TTL simply expiring — both paths converge on the
same "no connection.entry = not reachable" state, whether the client
told anyone or not.

## 10. Scale Justification

- **Per-key TTL means cleanup is free** — no background reconciler,
  no batch job, no risk of a stale entry lingering because a sweep
  hasn't run yet, unlike systems that mark expiry in a status column.
- **Write volume is bounded by connection churn plus heartbeat
  frequency** — tunable via the heartbeat interval: a longer interval
  means less write load but slower detection of a dead connection, a
  real trade-off to make deliberately, not a default to leave unexamined.
- **Redis Cluster sharding by `userId`** keeps a single user's device
  set together on one shard, so the delivery-path scan never needs to
  fan out across shards for one user's own devices.

## Implementation Notes

_(none yet beyond the interactive trace linked above)_
