---
service_name: Chat Systems
grouping: Social Media
status: Deep Dive Ready
labels: [cassandra, Redis]
sections_complete: 10
last_session: 2026-08-12
notion_url: TBD
---

**Diagram:** `systems/diagrams/chat-systems.drawio` (page 1: send +
connection-routing architecture; page 2: message state diagram)

**Interactive trace:** `systems/implementations/chat-systems-trace.html`
— a message sent while the recipient is on a *different* connection
server than the sender, and what happens if they're offline instead

## 1. Requirement Gathering

**Functional**
- One-on-one and group messaging with real-time delivery to online
  recipients.
- Durable history, delivered later if the recipient is offline when a
  message is sent.
- Delivery receipts: `SENT → DELIVERED → READ`.
- A user's inbox: their conversations, ordered by recent activity.

**Non-functional**
- Real-time delivery latency for online users: sub-second.
- Message ordering must be preserved within a conversation, even under
  concurrent sends from multiple participants.
- Durability is non-negotiable — a chat message silently lost is a
  correctness bug, not a degraded experience.
- Massive horizontal scale on two different axes at once: message
  *storage* volume, and *concurrent live connections* — these don't
  scale the same way and need separate answers.
- At-least-once delivery with idempotent apply on the client-generated
  message ID, so a retried send never duplicates.

**Out of scope:** detailed presence/last-seen mechanics and the
connection-registry internals in depth — that's
`systems/whatsapp-user-socket-info.md`'s job (now designed, including
multi-device support this system's simplified version glossed over);
this system gives the essential mechanism it depends on, not the full
treatment.

## 2. Queries in Plain English

- Send a message to a conversation.
- Get message history for a conversation, paginated.
- Acknowledge a message as delivered/read.
- Get a user's conversation list (inbox), most recently active first.
- Connect for real-time delivery (persistent connection).

## 3. State Diagram

```
SENT → DELIVERED → READ
```

Simpler than Notification System's — no retry loop belongs at this
layer, because the underlying connection/reconnect handling already
deals with transient delivery failure; this state machine is purely
about the message's *acknowledgment* progress.

## 4. API Endpoints

| Endpoint | Notes |
|---|---|
| WebSocket connect | persistent connection for real-time push, authenticated at handshake |
| `POST /conversations/{id}/messages` | body: `{clientMessageId, text}` — also usable as a WS frame |
| `GET /conversations/{id}/messages?before=&limit=` | history, paginated |
| `POST /messages/{id}/ack` | body: `{status: DELIVERED \| READ}` |
| `GET /users/{userId}/conversations` | inbox |

## 5. Concurrency Requirements

**Message ordering within a conversation:** a naive shared counter per
conversation would become a hot key for a busy group chat — the same
shape of problem `leaderboard.md` flags for a single sorted-set key.
Instead of a literal shared counter, ordering uses a
**timestamp + sender-node-id composite** (the same idea behind
Snowflake-style IDs): monotonic enough for correct display ordering,
generated locally with no coordination per message.

**Routing a message to the right live connection — the real distributed
problem here:** a recipient can be connected to *any* of many
horizontally-scaled connection-server instances. The sender's server
has no idea which one. The fix is a **connection registry in Redis**
mapping `userId → connectionServerId`, refreshed on connect/heartbeat
and cleared on disconnect. Message delivery becomes: write durably →
look up the recipient's registry entry → if present, route to that
specific server (which owns the live socket) → if absent, the
recipient is offline and the message waits in history. This exact
mechanism is what `systems/whatsapp-user-socket-info.md` will own in
full depth.

**Idempotent apply:** the client generates `clientMessageId`; a unique
constraint on it means a retried send (network blip, client didn't see
the ack) resolves to the same stored message instead of a duplicate —
the same idempotency-key shape used everywhere else in this repo.

## 6. Database Choice + Justification

- **Message storage → Cassandra.** Enormous write volume, a simple and
  known access pattern (fetch by `conversation_id`, most recent first)
  — the same shape as `notification_log` and `watch_progress`
  elsewhere in this repo, and matches how real chat systems at this
  scale are actually built.
- **Inbox view → Cassandra**, partitioned by `user_id` instead of
  `conversation_id` — a second table, not a query against the first,
  because the access pattern ("my conversations, most recent first")
  is genuinely different from "a conversation's messages." Cassandra
  is built around exactly this — model the table after the query, not
  the other way around.
- **Connection registry + presence → Redis.** This state changes
  constantly (every connect, disconnect, heartbeat) and needs to be
  read on every single message send — it has to be fast and it's
  inherently ephemeral, unlike message history.

## 7. Database Schema

**Cassandra**
```sql
CREATE TABLE messages (
  conversation_id  TEXT,
  message_id       TEXT,      -- timestamp + sender-node composite
  sender_id        BIGINT,
  content           TEXT,
  status            TEXT,      -- SENT, DELIVERED, READ
  PRIMARY KEY (conversation_id, message_id)
) WITH CLUSTERING ORDER BY (message_id DESC);

CREATE TABLE conversations_by_user (
  user_id             BIGINT,
  last_activity_at    TIMESTAMP,
  conversation_id     TEXT,
  last_message_preview TEXT,
  PRIMARY KEY (user_id, last_activity_at)
) WITH CLUSTERING ORDER BY (last_activity_at DESC);
```

**Redis**
```
conn:{userId}      -> connectionServerId   (heartbeat-refreshed, short TTL)
presence:{userId}  -> online | last_seen_at
```

## 8. Detailed Queries

```sql
INSERT INTO messages (conversation_id, message_id, sender_id, content, status)
VALUES (?, ?, ?, ?, 'SENT');

SELECT * FROM messages WHERE conversation_id = ? LIMIT 50;   -- clustering order gives newest-first for free

UPDATE messages SET status = 'DELIVERED' WHERE conversation_id = ? AND message_id = ?;
```
```
SET conn:U-501 conn-server-7 EX 60
GET conn:U-501
```

## 9. Read/Write Paths

**Send path:** Client A's WebSocket frame lands on whichever connection
server it's attached to → that server writes the message to Cassandra
(`SENT`) → looks up the recipient's entry in the Redis connection
registry.
- **Registry hit (recipient online):** the message is routed to the
  *specific* connection server holding the recipient's live socket
  (direct RPC between servers for 1:1 and small groups; for very large
  group fan-out, routing through Kafka instead of direct RPC avoids
  one busy conversation creating N×M direct connections between
  servers) → pushed over that socket → client acks → `DELIVERED`, then
  later `READ` when the conversation is opened, with a receipt pushed
  back to sender A.
- **Registry miss (recipient offline):** the message simply stays
  `SENT` in Cassandra. When the recipient reconnects, their client
  fetches recent history and the message becomes visible — no special
  "offline queue" needed, since durable storage already *is* the
  queue.

**Read path (history/inbox):** straight Cassandra reads against the
tables in section 7 — both are shaped exactly around their query, so
neither needs a scan or a join.

## 10. Scale Justification

Target: billions of messages/day, millions of concurrent live
connections.

- **Storage scales independently from connections.** Cassandra write
  throughput scales linearly with nodes, keyed by `conversation_id` —
  this has nothing to do with how many sockets are open right now.
- **Connections scale by adding connection-server instances**, each
  handling a bounded number of concurrent sockets (tens of thousands
  per instance is realistic) — this is a completely separate scaling
  axis from message storage, which is why splitting them was the right
  call rather than one monolithic "chat server."
- **Registry lookups are cheap:** a single Redis `GET` per outgoing
  message, sharded by `userId` across a Redis Cluster — this stays
  fast even as connection count grows, because it's O(1) regardless of
  how many total connections exist.
- **Group fan-out is the one place this gets genuinely harder:** a
  10,000-member group chat means one message potentially needs routing
  to thousands of different connection servers. Direct RPC per
  recipient doesn't scale to that; routing large-group fan-out through
  Kafka (one publish, many connection servers consuming the
  conversation's partition) avoids the direct-connection explosion at
  the cost of a small amount of added latency — worth the trade for
  group sizes past a threshold, not for 1:1 chat.

## Implementation Notes

_(none yet beyond the interactive trace linked above)_
