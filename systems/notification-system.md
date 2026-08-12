---
service_name: Notification System
grouping: Notification System
status: Deep Dive Ready
labels: [Kafka, cassandra, SQL]
sections_complete: 10
last_session: 2026-08-12
notion_url: TBD
---

**Diagram:** `systems/diagrams/notification-system.drawio` (page 1:
event intake + fan-out architecture; page 2: per-notification state
diagram)

**Interactive trace:** `systems/implementations/notification-system-trace.html`
— one event fanning out to two channels, one succeeding immediately and
one retrying after a transient provider failure

## 1. Requirement Gathering

**Functional**
- Send notifications across multiple channels (push, email, SMS,
  in-app) triggered by events from other internal services — e.g.
  Order Service's `OrderConfirmed` should trigger a push + email.
- Per-user, per-notification-type channel preferences (opt-in/opt-out),
  respected before anything is sent.
- Templated, localized content — not raw event data.
- Retries on transient provider failure (a push gateway or email
  provider blipping shouldn't lose the notification).
- Idempotency: the same event must not produce duplicate notifications,
  even under at-least-once delivery from the event source.

**Non-functional**
- Fan-out is the defining characteristic: a single event (e.g. "flash
  sale started") can need to reach millions of users — this must never
  block the service that triggered it.
- Delivery is best-effort per channel, not instant or guaranteed —
  email/push providers have their own latency and failure modes.
- Must not spam a user — rate limiting per user across notification
  types.

## 2. Queries in Plain English

**Internal (producer side)**
- Publish a notification event (any internal service can trigger this).

**User-facing**
- Get / update my notification preferences.
- Get my in-app notification inbox.
- Mark a notification read.

**Internal (worker side)**
- Check a user's preferences and rate limit before sending.
- Render the templated content for a channel + locale.
- Dispatch to the channel-specific provider.
- Record delivery status; retry on transient failure.

## 3. State Diagram

Unlike LeaderBoard, this genuinely has a multi-step lifecycle — a
notification (per user, per event, per channel) moves through:

```
PENDING → RENDERED → QUEUED → SENT → DELIVERED
                                  ↓
                              FAILED → RETRYING → SENT / FAILED (retries exhausted)
```

## 4. API Endpoints

**Internal (producer)**
| Endpoint | Notes |
|---|---|
| `POST /internal/notifications/send` | body: `{eventType, userIds[], templateData}` |

**User-facing**
| Endpoint | Notes |
|---|---|
| `GET /users/{userId}/notification-preferences` | |
| `PUT /users/{userId}/notification-preferences` | |
| `GET /users/{userId}/notifications` | in-app inbox |
| `POST /users/{userId}/notifications/{id}/read` | |

## 5. Concurrency Requirements

**Idempotency:** the event source (Kafka) delivers at-least-once, so
the same event can arrive twice. A unique constraint on
`(event_id, user_id, channel)` makes redelivery a no-op — same pattern
as `amazon-order-management-system.md`'s idempotency-key handling.

**Fan-out, not a hot loop:** one event reaching millions of users means
millions of individual per-user, per-channel notification tasks. This
has to be a Kafka partition/consumer-group fan-out that scales
horizontally by adding worker instances — never a single service
iterating a user list in memory.

**Rate limiting per user:** if several events fire for the same user in
quick succession, they shouldn't all land as separate pushes. Rather
than reinvent this, the notification worker calls this repo's own
**Rate Limiter service** (`systems/rate-limiter.md`) before dispatch —
a genuine example of one designed system depending on another.

**Retry behavior:** transient provider failures (a push gateway
timeout) retry with exponential backoff *and jitter* — without jitter,
a provider outage recovering at time T causes every queued retry to
hit it again at the exact same instant, recreating the outage.

## 6. Database Choice + Justification

- **Event intake → Kafka.** Decouples producers (any internal service)
  from the notification pipeline entirely — a producer publishes and
  moves on, regardless of how slow or backed-up dispatch currently is.
- **Notification log → Cassandra**, not SQL. This is the first system
  in this repo where Cassandra is the right call: write volume is huge
  (every notification, every channel, every user), the access pattern
  is simple and known in advance (fetch by `user_id`, most recent
  first — no joins, no ad-hoc queries), and that's exactly Cassandra's
  sweet spot — a wide, write-optimized table partitioned by the one key
  it's actually queried by. SQL's relational features would be pure
  overhead here.
- **User preferences → SQL.** Small table, genuinely relational
  (admin/support tooling needs ad-hoc queries across it), low write
  volume relative to the notification log — SQL is the right, boring
  choice here specifically because this table *doesn't* have
  Cassandra's access-pattern profile.

## 7. Database Schema

**Cassandra**
```sql
CREATE TABLE notification_log (
  user_id         BIGINT,
  created_at      TIMESTAMP,
  notification_id UUID,
  event_id        TEXT,
  channel         TEXT,
  status          TEXT,        -- PENDING, RENDERED, QUEUED, SENT, DELIVERED, FAILED, RETRYING
  sent_at         TIMESTAMP,
  delivered_at    TIMESTAMP,
  PRIMARY KEY (user_id, created_at, notification_id)
) WITH CLUSTERING ORDER BY (created_at DESC);
```

**SQL**
```sql
CREATE TABLE user_notification_preferences (
  user_id            BIGINT NOT NULL,
  notification_type  VARCHAR(50) NOT NULL,
  channel            VARCHAR(20) NOT NULL,   -- PUSH, EMAIL, SMS, IN_APP
  enabled            BOOLEAN NOT NULL DEFAULT TRUE,
  PRIMARY KEY (user_id, notification_type, channel)
);

CREATE TABLE idempotency_keys (
  event_id   VARCHAR(100) NOT NULL,
  user_id    BIGINT NOT NULL,
  channel    VARCHAR(20) NOT NULL,
  created_at TIMESTAMP NOT NULL,
  PRIMARY KEY (event_id, user_id, channel)
);
```

**Kafka topics**
| Topic | Producer | Consumers |
|---|---|---|
| `notification.events` | any internal service | Notification Worker |
| `notification.dispatch.push` / `.email` / `.sms` | Notification Worker | channel-specific Dispatcher |

## 8. Detailed Queries

```sql
-- idempotency check (Order Service's own pattern, reused here)
INSERT INTO idempotency_keys (event_id, user_id, channel, created_at)
VALUES (?, ?, ?, now());  -- unique-constraint violation = already processed

SELECT enabled FROM user_notification_preferences
WHERE user_id = ? AND notification_type = ? AND channel = ?;
```
```sql
-- Cassandra
INSERT INTO notification_log (user_id, created_at, notification_id, event_id, channel, status)
VALUES (?, ?, ?, ?, ?, 'PENDING');

SELECT * FROM notification_log WHERE user_id = ? ORDER BY created_at DESC LIMIT 20;
```

## 9. Read/Write Paths

**Write (fan-out) path:**
1. Any internal service publishes to `notification.events`.
2. Notification Worker consumes → for each target user: idempotency
   check → preference check (SQL, cached) → rate-limit check (call
   Rate Limiter service) → render template → write `notification_log`
   row (`PENDING`, Cassandra).
3. Publish to the appropriate `notification.dispatch.{channel}` topic.
4. A channel-specific Dispatcher consumes and calls the external
   provider (FCM/APNs, SES, Twilio, etc.).
5. On success: update `notification_log` → `SENT`; a later provider
   webhook may update → `DELIVERED`.
6. On transient failure: → `RETRYING` with backoff + jitter, up to a
   retry limit, then → `FAILED`.

**Read path (in-app inbox):** `SELECT ... WHERE user_id = ? ORDER BY
created_at DESC` against Cassandra — fast, since this is exactly the
partition key it's organized around.

## 10. Scale Justification

Target: a broadcast event (e.g. a flash-sale start) reaching 5M users
across push + email.

- **Kafka fan-out:** `notification.events` carries one message per
  *event*, not per recipient — the Worker expands to per-user tasks.
  With enough partitions and consumer instances, expansion and
  dispatch scale horizontally with no coordination between workers.
- **Cassandra write throughput:** 5M users × 2 channels = 10M log
  writes for this one event. Cassandra's write path (append to a
  commit log + memtable, no read-before-write) is built exactly for
  this — linearly scalable by adding nodes, unlike a single SQL
  primary's row-lock-bound write ceiling.
- **Rate limiter dependency:** calling out to the Rate Limiter service
  adds a hop per notification, but that service was explicitly
  designed for exactly this kind of high-throughput hot-path check
  (see `systems/rate-limiter.md` section 10) — reusing it here instead
  of building a second one is a real architectural win, not just
  convenience.
- **Retry storm avoidance:** jittered backoff keeps a provider recovery
  from being immediately re-flooded by every queued retry firing at
  once.

## Implementation Notes

_(none yet beyond the interactive trace linked above)_
