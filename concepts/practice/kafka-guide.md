---
concept_name: Kafka Concepts (Practice Guide)
linked_systems: [Click Event Aggregator, Notification System, Amazon Order Managment System, Chat Systems, Broadcasting System]
last_reviewed: 2026-08-16
freshness: Fresh
notion_url: TBD
---

# Kafka Concepts — Practice Guide

**Question bank:** `concepts/practice/kafka-question-bank.md`

Only three systems carry the `Kafka` label in `docs/TRACKER.md` —
`click-event-aggregator.md`, `notification-system.md`,
`amazon-order-management-system.md` — but two unlabeled systems,
`chat-systems.md` and `broadcasting-system.md`, use Kafka conditionally
as a fan-out escape hatch (Concept 10), worth knowing even though it
didn't earn them the label. Sections 1–10 are patterns this repo
already demonstrates concretely; sections 11–12 cover concepts **no
system here has needed yet**, called out explicitly rather than
invented.

## 1. Decoupling & Backpressure Isolation

Kafka's core job across every system that uses it here: let a fast
producer and a slower or independently-scaled consumer never block each
other. `amazon-order-management-system.md` states this directly —
Kafka "decouples [Payment Service and its consumers] so that a slow or
temporarily-down Inventory Service can never block Payment Service from
acknowledging the gateway webhook, and replays are possible if a
consumer needs to catch up after an outage." `click-event-aggregator.md`
uses the identical shape for a different pair: the click-ingest
endpoint "does the absolute minimum (validate, publish) and returns
immediately, regardless of how backed up aggregation currently is" —
same fan-out philosophy, explicitly cross-referenced between the two
files.

## 2. Partitioning Strategy — Keys & Ordering Guarantees

Kafka only guarantees message order **within a partition**, never
across an entire topic — so the partition key choice is really a
choice about what ordering guarantee you need. `amazon-order-management-system.md`
partitions `payment.completed`/`payment.failed`/`order.lifecycle` by
`order_id`, stating exactly why: "per-partition ordering guarantees an
order's own events are processed in sequence" — critical, since a
`payment.failed` processed before its own order's `payment.completed`
(out of order) would be a real correctness bug. This is the same
discipline as choosing a database partition key by query pattern (SQL
guide's Concept 1, Cassandra guide's Concept 2) — pick the key that
matches the one ordering guarantee that actually matters, not an
arbitrary field.

## 3. Consumer Groups & Horizontal Parallelism

A consumer group spreads a topic's partitions across multiple consumer
instances, each partition owned by exactly one consumer within the
group at a time — this is *the* horizontal scaling lever for both
ingest and processing. `notification-system.md` is explicit about why
this has to be the mechanism: "one event reaching millions of users
means millions of individual per-user, per-channel notification tasks.
This has to be a Kafka partition/consumer-group fan-out that scales
horizontally by adding worker instances — never a single service
iterating a user list in memory." `click-event-aggregator.md` ties
partition count directly to scaling: "more partitions and more
stream-processing instances (one per partition, standard consumer-group
semantics) scale ingest and aggregation together."

## 4. At-Least-Once Delivery & Idempotent Consumption

Kafka's default delivery guarantee is **at-least-once** — a consumer
can see the same message twice (after a rebalance, a retry, a crash
before offset commit) — so every consumer in this repo is written to
treat redelivery as a no-op, using two different mechanisms.
`notification-system.md` uses an explicit **dedup table**: "a unique
constraint on `(event_id, user_id, channel)` makes redelivery a
no-op." `amazon-order-management-system.md` instead makes the **state
transition itself** the dedup mechanism — "the cleanest way is to make
the state transition itself the dedup mechanism rather than maintaining
a separate processed-events table," via a conditional `UPDATE ... WHERE
status = 'PENDING_PAYMENT'` where redelivery affects 0 rows and is
silently harmless (the same atomic-conditional-update primitive as SQL
guide Concept 5, applied to Kafka-consumer idempotency instead of a
locking problem).

## 5. Retry with Backoff & Jitter

`notification-system.md` names a specific failure mode of naive retry:
"without jitter, a provider outage recovering at time T causes every
queued retry to hit it again at the exact same instant, recreating the
outage" — so retries use exponential backoff **with random jitter**
added, spreading the retry storm out in time instead of resynchronizing
it. Its status model moves `RETRYING` → `FAILED` after a retry limit is
exhausted — notably, this repo doesn't route exhausted retries to a
separate dead-letter topic (Concept 12); it just marks the row `FAILED`
in its own store for later inspection.

## 6. SAGA via Kafka — Orchestration + Choreography Hybrid

`amazon-order-management-system.md` runs a **hybrid** SAGA: the
synchronous leg (reserve inventory → create payment intent, with
compensation if the payment call fails) is orchestrated directly by
Order Service calling other services; the asynchronous leg (webhook →
Kafka → both Order Service and Inventory Service independently
consuming `payment.completed`/`payment.failed`) is **choreography** —
no central coordinator for that leg, each service reacts to the event
on its own. This mirrors the same reasoning the SQL guide's 2PC section
covers from the opposite direction: 2PC would need a coordinator
holding locks across the whole distributed transaction; this SAGA
instead lets each local step commit immediately and relies on
Kafka-delivered events plus compensating actions (and a background
reaper releasing holds if an event never arrives at all) to keep the
whole flow eventually consistent.

## 7. Stream Processing — Windowing, Watermarks & Approximate Aggregation

`click-event-aggregator.md`'s consumer isn't a simple one-message
handler — it's a stream processor grouping events by `(page_id, tumbling
1-minute window)`, using a **watermark** (a grace period, e.g. 30
seconds) before finalizing and flushing a window's aggregate to
Cassandra, so a click that arrives slightly late still gets counted
before the window closes. Unique-visitor counts within each window use
a **HyperLogLog** for approximate cardinality rather than an exact
distinct-count — the same accuracy-vs-cost trade-off the Redis guide's
Concept 12 names, just implemented inside the stream processor instead
of via Redis's `PFADD`.

## 8. Topic Retention as a Replay Log

`click-event-aggregator.md`'s raw `click.events` topic isn't only a
transient pipe — its retention window "doubles as a practical raw-event
log for replay/debugging without needing a separate durable store for
raw events." This is a deliberate reuse of Kafka's own storage: since
Kafka already retains messages for a configured window (unlike Redis
pub/sub, Redis guide's Concept 12), a topic can double as a short-term
audit/replay source for free, as long as the retention window is long
enough to cover realistic reprocessing needs — a design choice to make
explicitly (how long is "long enough"), not something to assume by
default.

## 9. Event-Count vs. Recipient-Count Topic Design

`notification-system.md` makes an explicit modeling choice: `notification.events`
carries **one message per event, not per recipient** — "the Worker
expands to per-user tasks. With enough partitions and consumer
instances, expansion and dispatch scale horizontally with no
coordination between workers." Publishing one message per *eventual
recipient* instead (millions of messages for one broadcast event) would
front-load all the fan-out cost onto the producer and bloat the topic
with redundant near-identical messages; keeping the topic
event-shaped and pushing the fan-out into the consumer layer (Concept
3) lets that expansion scale independently and horizontally instead.

## 10. Conditional Kafka Usage — The Fan-out Escape Hatch

Not every system that could use Kafka does, by default. `chat-systems.md`'s
default message path is **direct RPC** between connection servers — it
only routes through Kafka "for very large group fan-out... at the cost
of a small amount of added latency — worth the trade for group sizes
past a threshold, not for 1:1 chat." `broadcasting-system.md` reuses
this unchanged for viral-stream chat, explicitly citing it as "exactly
that threshold case." Neither system carries the `Kafka` label in the
tracker, because Kafka isn't core to their architecture — it's a
conditional escape hatch triggered past a specific fan-out size, a
reminder that "does this system use Kafka" can be a threshold-dependent
answer, not a fixed yes/no per system.

## 11. Unused Here — Producer Acks, Idempotent Producers & Exactly-Once Semantics

No file in this repo states a producer `acks` setting (`0`, `1`, or
`all`), enables the idempotent producer (`enable.idempotence=true`), or
discusses Kafka's transactional/exactly-once processing API. Worth
reasoning through even though nothing here needed it: `acks=all`
(leader + all in-sync replicas confirm before the producer considers
the write done) would be the right choice for `amazon-order-management-system.md`'s
payment events specifically, since losing a `payment.completed` event
outright (not just delaying it) would be a real financial-correctness
bug — a stronger guarantee than the systems' existing at-least-once
*consumer*-side idempotency (Concept 4) protects against, since that
only handles duplicate delivery, not lost delivery. None of the three
Kafka-labeled systems name this setting explicitly, which is a gap
worth flagging on a revisit rather than assuming it's handled.

## 12. Unused Here — Schema Registry, Log Compaction & Multi-DC Replication

Three more real Kafka features absent from every system in this repo.
**Schema Registry** (Avro/Protobuf schemas versioned centrally, with
compatibility rules enforced on publish) — every topic here is
implicitly JSON with no schema evolution strategy discussed, fine for a
design-stage system but a real gap once multiple independently-deployed
services need to agree on a message shape that changes over time.
**Log compaction** (`cleanup.policy=compact`, keeping only the latest
value per key forever instead of expiring by time) — none of this
repo's topics are compacted; `payment.completed`/`order.lifecycle` are
event streams where every event matters (not "latest state per key"),
so retention-based topics are the correct choice here, and compaction
would actually be the wrong tool. **Multi-DC replication** (MirrorMaker
or equivalent, mirroring topics across regions) — like the Cassandra
guide's Concept 12, no system here has stated a multi-region
requirement, so this remains an orthogonal, not-yet-needed concept
rather than a gap in the existing designs.
