---
concept_name: Kafka Question Bank (Practice)
linked_systems: [Click Event Aggregator, Notification System, Amazon Order Managment System, Chat Systems]
last_reviewed: 2026-08-16
freshness: Fresh
notion_url: TBD
---

# Kafka Question Bank

Progress persists as checkboxes below — resuming `/practice kafka`
finds the first `[ ]` in document order. Guide:
`concepts/practice/kafka-guide.md`.

## Concept 1: Decoupling & Backpressure Isolation
_guide: kafka-guide.md#1-decoupling--backpressure-isolation_

### Q1 [core] — What Kafka buys the payment webhook — [ ] not yet attempted
**Scenario:** `amazon-order-management-system.md`'s Payment Service
receives a webhook from the external card processor and must
acknowledge it quickly, but Order Service and Inventory Service both
need to react to the payment result, and Inventory Service is
occasionally slow.
**Question:** What would go wrong if Payment Service called Order
Service and Inventory Service directly (synchronous HTTP) instead of
publishing to Kafka, and how does Kafka fix it?

<details><summary>Model answer</summary>

A direct synchronous call means Payment Service's webhook handler can't
return until *both* downstream services respond — if Inventory Service
is slow or briefly down, the webhook acknowledgment is delayed or
fails, and most payment providers will retry (or worse, time out and
mark the webhook as failed) if it isn't acknowledged quickly. That
turns an unrelated service's slowness into an outage for the payment
flow itself. Publishing to Kafka instead means Payment Service's job
ends the instant the message is durably written to the topic — Order
Service and Inventory Service each consume independently, at their own
pace, and a slow or temporarily-down consumer just falls behind on its
own offset, replaying once it recovers, with zero impact on Payment
Service's ability to acknowledge the webhook immediately.
</details>

### Q2 [core] — Same pattern, different pair — [ ] not yet attempted
**Scenario:** `click-event-aggregator.md` uses the identical
decoupling shape as Q1, but between different components.
**Question:** Name the two components being decoupled here, and state
the concrete consequence if the aggregation side falls behind.

<details><summary>Model answer</summary>

The click-ingest endpoint (accepts a click, validates, publishes to
`click.events`) is decoupled from the stream processor that aggregates
those events into per-page, per-window metrics. If aggregation falls
behind — a burst of traffic, a slow window computation — the ingest
endpoint is completely unaffected: it keeps validating and publishing
at full speed regardless, because publishing to Kafka doesn't wait for
any consumer to catch up. The consequence of aggregation lag is purely
that metrics become stale by however far behind the consumer has
fallen — a delayed dashboard, never a dropped or blocked click.
</details>

## Concept 2: Partitioning Strategy — Keys & Ordering Guarantees
_guide: kafka-guide.md#2-partitioning-strategy--keys--ordering-guarantees_

### Q1 [core] — Why order_id as the key — [ ] not yet attempted
**Scenario:** `amazon-order-management-system.md` partitions
`payment.completed`/`payment.failed` by `order_id`.
**Question:** What specific bug would be possible if these topics were
partitioned randomly (round-robin) instead, and how does keying by
`order_id` prevent it?

<details><summary>Model answer</summary>

Kafka only guarantees ordering *within* a partition. If messages were
distributed randomly across partitions, two events for the *same*
order — say a `payment.completed` immediately followed by a rare
downstream `payment.failed` correction, or more realistically retried
duplicate events for one order — could land on different partitions
and be consumed in a different relative order than they were produced,
or processed concurrently by different consumer instances entirely. A
consumer could then apply a later event before an earlier one for the
same order, corrupting that order's state. Keying by `order_id` forces
every event for the same order onto the *same* partition, guaranteeing
they're delivered to whichever consumer owns that partition in
publish order — "an order's own events are processed in sequence," as
the file states directly.
</details>

### Q2 [core] — Picking a key for a new topic — [ ] not yet attempted
**Scenario:** You're adding a new topic, `inventory.adjustments`, where
each message represents a stock change for one `product_id`, and it's
critical that adjustments for the same product are never processed out
of order.
**Question:** What should the partition key be, and what trade-off does
that key choice introduce for topic throughput?

<details><summary>Model answer</summary>

`product_id` — the same reasoning as Q1: whatever entity's ordering
must be preserved is the partition key. The trade-off: a small number
of extremely hot products (a flash-sale item with huge adjustment
volume) will all funnel through the same partition regardless of how
many partitions the topic has overall, since Kafka can't split one
key's messages across multiple partitions (the same structural
constraint as the Redis guide's Cluster hot-key limitation, Concept
11) — meaning that one product's throughput ceiling is capped by a
single partition's capacity, even if the topic as a whole has plenty of
headroom across its other partitions.
</details>

## Concept 3: Consumer Groups & Horizontal Parallelism
_guide: kafka-guide.md#3-consumer-groups--horizontal-parallelism_

### Q1 [core] — Scaling the notification worker — [ ] not yet attempted
**Scenario:** `notification-system.md`'s Worker needs to turn one
"order shipped" event into a per-user notification task for up to
millions of recipients (e.g. a mass promotional event).
**Question:** Why must this fan-out happen via Kafka consumer-group
parallelism rather than a single service instance looping over a user
list?

<details><summary>Model answer</summary>

A single instance iterating millions of users in memory is
fundamentally not horizontally scalable — its throughput is capped by
one process's CPU and I/O, and if that instance crashes mid-loop, all
progress tracking has to be reconstructed from scratch with no natural
resume point. Consumer-group fan-out instead lets `notification.events`'s
partitions be split across as many Worker instances as needed — adding
more instances (up to the partition count) directly adds throughput,
each instance only responsible for its owned partitions' share of the
work, and Kafka's own offset-commit mechanism gives a natural resume
point per partition if an instance crashes and its partitions get
reassigned to another instance in the group.
</details>

### Q2 [core] — The partition-count ceiling — [ ] not yet attempted
**Scenario:** A topic has 8 partitions, and the team scales the
consumer group to 12 instances hoping to get more throughput.
**Question:** What actually happens, and what's the real lever to add
more parallelism?

<details><summary>Model answer</summary>

Only 8 of the 12 instances will ever be assigned a partition — Kafka
never assigns more than one consumer per partition within a single
group, so the extra 4 instances sit completely idle, contributing
nothing. Parallelism within a consumer group is bounded by partition
count, full stop — the actual lever to add more throughput is
increasing the topic's partition count (which requires planning, since
increasing partitions on an existing topic can affect the ordering
guarantee for existing keys, per Concept 2), not just adding more
consumer instances past that ceiling. This is exactly why
`click-event-aggregator.md` ties its scaling story to "more partitions
*and* more stream-processing instances" together, not instances alone.
</details>

## Concept 4: At-Least-Once Delivery & Idempotent Consumption
_guide: kafka-guide.md#4-at-least-once-delivery--idempotent-consumption_

### Q1 [core] — Two different dedup mechanisms — [ ] not yet attempted
**Scenario:** Both `notification-system.md` and
`amazon-order-management-system.md` must handle Kafka redelivering the
same event twice, but they use different mechanisms.
**Question:** Describe both mechanisms and explain why the Amazon
system's approach avoids needing a separate table at all.

<details><summary>Model answer</summary>

`notification-system.md` uses an explicit **dedup table**: a unique
constraint on `(event_id, user_id, channel)` means a redelivered
event's insert simply conflicts and is treated as a no-op — this
requires maintaining and checking a dedicated table of "have I seen
this before." `amazon-order-management-system.md` instead makes the
**state transition itself** the dedup check: `UPDATE orders SET status
= 'PAID' WHERE order_id = ? AND status = 'PENDING_PAYMENT'` — the first
delivery of `payment.completed` finds the order still `PENDING_PAYMENT`
and transitions it; a redelivered copy finds the order already `PAID`,
matches 0 rows, and is silently harmless. No separate table is needed
because the order row's own current status *is* the record of "has
this event already been processed" — the dedup information was already
going to be stored (the order's state) regardless of the redelivery
concern.
</details>

### Q2 [core] — When state-transition dedup doesn't work — [ ] not yet attempted
**Scenario:** A new consumer needs to process a `click.events`-style
topic where each message should trigger an independent side effect
(e.g. incrementing an analytics counter) with no natural "current
state" column to check against.
**Question:** Would the Amazon system's state-transition dedup approach
work here? If not, what would you use instead?

<details><summary>Model answer</summary>

No — state-transition dedup relies on there being a meaningful "before"
state that only a first delivery can transition out of (`PENDING_PAYMENT`
→ `PAID`); a counter increment has no such state — both the first and a
duplicate delivery would look identical (an increment is an increment)
and there's no natural "already incremented" flag to check. This is
exactly `notification-system.md`'s situation, and its fix is the right
one here too: an explicit dedup table or dedup column keyed by a unique
identifier from the event itself (`event_id`, or `(event_id,
consumer_purpose)` if the same event triggers multiple independent side
effects), checked before applying the side effect. The general rule:
state-transition dedup is a nice free win *when* a natural
before/after state already exists; otherwise, fall back to an explicit
processed-events record.
</details>

## Concept 5: Retry with Backoff & Jitter
_guide: kafka-guide.md#5-retry-with-backoff--jitter_

### Q1 [core] — The thundering-herd retry bug — [ ] not yet attempted
**Scenario:** `notification-system.md`'s Dispatcher retries failed
sends to an external push-notification provider using exponential
backoff, but without jitter — every failed message retries at exactly
2s, 4s, 8s, 16s after its own first failure.
**Question:** Describe the specific failure mode this causes when the
provider has an outage affecting many messages at once.

<details><summary>Model answer</summary>

If the provider goes down and rejects a large batch of sends
simultaneously, every one of those messages' retry schedules is
computed relative to the *same* failure moment — meaning they all
retry again at 2s later, all together; if that retry also fails (the
provider is still down), they all retry again at 4s later, together;
and so on. The moment the provider actually recovers, it gets hit by
the full queued batch landing on it in the same instant (whichever
retry-round happens to align with recovery), potentially overwhelming
it right as it comes back up and recreating the very outage that's
supposed to be resolving — the retries synchronize into a thundering
herd instead of spreading out.
</details>

### Q2 [core] — Fixing it with jitter — [ ] not yet attempted
**Scenario:** Same setup as Q1.
**Question:** What's the fix, and why does it specifically solve the
synchronization problem rather than just reducing overall retry
volume?

<details><summary>Model answer</summary>

Add random jitter to each retry's computed delay — e.g. instead of
retrying at exactly `2^n` seconds, retry at `2^n * random(0.5, 1.5)`
seconds. This doesn't reduce how many retries eventually happen; it
solves the synchronization specifically by spreading those retries
across a *range* of time instead of one shared instant, so that when
the provider recovers, the queued retries arrive as a smoothed trickle
over that jittered window rather than one simultaneous spike large
enough to look like another outage. The fix targets the *timing
correlation* between messages, not the *volume* of retries — volume
stays the same, but it's no longer concentrated at a single moment.
</details>

## Concept 6: SAGA via Kafka — Orchestration + Choreography Hybrid
_guide: kafka-guide.md#6-saga-via-kafka--orchestration--choreography-hybrid_

### Q1 [core] — Naming the two legs — [ ] not yet attempted
**Scenario:** `amazon-order-management-system.md`'s checkout flow has
two distinct legs: (a) Order Service directly calls Inventory Service
to reserve stock, then directly calls Payment Service to create a
payment intent, compensating if either fails; (b) once the payment
gateway's webhook eventually arrives, both Order Service and Inventory
Service independently consume `payment.completed`/`payment.failed` from
Kafka and react on their own.
**Question:** Which leg is orchestration and which is choreography, and
why does the system need both rather than picking one style
throughout?

<details><summary>Model answer</summary>

Leg (a) is **orchestration** — Order Service acts as a central
coordinator, explicitly calling each participant in sequence and
deciding how to compensate on failure; it works here because this leg
is synchronous and fast (within one request's lifetime), so having one
place drive the sequence is straightforward. Leg (b) is
**choreography** — there's no central coordinator once the async
webhook path kicks in; Order Service and Inventory Service each just
react independently to the same Kafka events. This leg has to be
choreography because it's inherently asynchronous and can take an
unpredictable amount of time (waiting on an external payment gateway,
possibly minutes) — an orchestrator would have to hold a synchronous
call open that whole time, exactly the coordinator-blocking problem
the SQL guide's 2PC section names for a different mechanism. Using
choreography for the async leg avoids that entirely: nobody's holding
anything open, waiting.
</details>

### Q2 [core] — What happens if the webhook never arrives — [ ] not yet attempted
**Scenario:** The payment gateway's webhook is lost in transit (network
issue on the gateway's end) and never reaches Payment Service, so
`payment.completed`/`payment.failed` is never published.
**Question:** What in the actual design handles this, and why can't the
choreography leg alone solve it?

<details><summary>Model answer</summary>

Choreography only reacts to events that actually arrive — if no event
is ever published, no consumer ever fires, and the order (and its
inventory reservation) would sit `PENDING_PAYMENT` / `HELD` forever
with nothing to trigger a resolution. `amazon-order-management-system.md`'s
actual fix is a **background reaper**: a separate process that releases
`HELD` inventory reservations once their `expires_at` passes with no
corresponding event ever having arrived — a compensating mechanism
that doesn't depend on Kafka delivering anything at all, specifically
because it exists to handle the case where Kafka delivery (or the
webhook that would have triggered it) never happens in the first
place. This is a good example of why a SAGA needs a timeout/reaper
safety net alongside its event-driven steps, not just event handlers.
</details>

## Concept 7: Stream Processing — Windowing, Watermarks & Approximate Aggregation
_guide: kafka-guide.md#7-stream-processing--windowing-watermarks--approximate-aggregation_

### Q1 [core] — Why a watermark, not a hard cutoff — [ ] not yet attempted
**Scenario:** `click-event-aggregator.md`'s stream processor groups
clicks into 1-minute tumbling windows per `page_id`, and uses a 30-second
watermark before finalizing a window.
**Question:** What would go wrong with finalizing each window exactly
at its 1-minute boundary with no watermark, and what does the
watermark buy instead?

<details><summary>Model answer</summary>

Network delay, client-side buffering, or a brief consumer lag can mean
a click that logically happened within window N's minute doesn't
actually arrive at the stream processor until slightly after that
minute has passed. Finalizing exactly at the boundary would silently
drop or miscount any click that arrives even a moment late, undercounting
that window's true total. The watermark buys a grace period — the
processor waits an extra 30 seconds past the window's nominal end
before treating it as final and flushing to Cassandra — trading a
small amount of latency (results are 30s more delayed) for
meaningfully more accurate counts, since most realistically-late events
land within that grace window.
</details>

### Q2 [core] — Exact vs. approximate unique visitors — [ ] not yet attempted
**Scenario:** The same stream processor tracks unique visitors per
window using a HyperLogLog rather than an exact set of visitor IDs.
**Question:** What would an exact approach cost that HyperLogLog
avoids, and what's actually given up in exchange?

<details><summary>Model answer</summary>

An exact unique count requires keeping a full set of every distinct
visitor ID seen in the window (e.g. a hash set), which grows
proportionally to the actual number of unique visitors — for a viral
page with millions of unique visitors in one window, that's megabytes
of state held in memory per window, per page, multiplied across every
concurrently-open window in the whole system. HyperLogLog gives an
*approximate* count (typically within about 2% error) using a fixed,
tiny amount of memory (~12KB) regardless of how many unique visitors
there actually were — the memory cost stops scaling with cardinality
entirely. What's given up is exactness: acceptable here because a
unique-visitor count is a reporting/dashboard metric, not a value any
downstream system does exact accounting against — the same
accuracy-for-cost trade the Redis guide's Concept 7 makes for
approximate like counts.
</details>

## Concept 8: Topic Retention as a Replay Log
_guide: kafka-guide.md#8-topic-retention-as-a-replay-log_

### Q1 [core] — Reusing retention instead of a separate store — [ ] not yet attempted
**Scenario:** `click-event-aggregator.md`'s raw `click.events` topic
retention window "doubles as a practical raw-event log for
replay/debugging without needing a separate durable store for raw
events."
**Question:** What alternative design would this be replacing, and why
is reusing Kafka's own retention a reasonable simplification here
specifically?

<details><summary>Model answer</summary>

The alternative would be a dedicated raw-event archive — e.g. writing
every click event to a separate durable table or object store purely
so it could be replayed later if the aggregation logic had a bug or
needed reprocessing. Reusing Kafka's own retention avoids building and
operating that second system, as long as the retention window is
genuinely long enough to cover realistic reprocessing needs (catching
a bug within a day or two, say) — this is reasonable specifically
because click events are high-volume and low-value-per-event (nobody
needs to replay a six-month-old click), unlike `amazon-order-management-system.md`'s
payment events, where losing the ability to replay far-past events
would be a real gap, not an acceptable trade.
</details>

### Q2 [core] — When retention-as-replay-log breaks down — [ ] not yet attempted
**Scenario:** A teammate proposes relying on the same "retention window
as replay log" trick for `payment.completed` events, to avoid building
a separate payment-event archive.
**Question:** Why is this a worse trade-off here than it is for
`click.events`?

<details><summary>Model answer</summary>

Payment events are exactly the kind of data where "replay something
from three months ago" is a realistic and important need — a
compliance audit, a disputed charge investigation, a bug that only
gets noticed long after the fact. A Kafka retention window long enough
to cover that (months) means holding a much larger volume of durable
log data inside Kafka itself for a purpose Kafka isn't optimized for
(long-term, queryable archival) — versus click events, where "nobody
needs to replay a click from three months ago" makes a short retention
window (days) genuinely sufficient. The right call depends on how long
"long enough for realistic replay" actually is for that specific
data — for payment events, that argues for a proper archival store,
not stretching Kafka retention to serve a purpose it wasn't designed
for.
</details>

## Concept 9: Event-Count vs. Recipient-Count Topic Design
_guide: kafka-guide.md#9-event-count-vs-recipient-count-topic-design_

### Q1 [core] — Why one message per event — [ ] not yet attempted
**Scenario:** `notification-system.md` publishes one message per
*event* to `notification.events` (e.g. one message for "order #123
shipped"), and expands it to per-user, per-channel tasks only inside
the Worker.
**Question:** What would go wrong if the producing service instead
published one Kafka message per eventual *recipient* directly (e.g. a
promotional blast to 5 million users publishing 5 million messages)?

<details><summary>Model answer</summary>

The producing service would have to already know, at publish time,
every single recipient and materialize a message per recipient before
it could finish publishing — front-loading the entire fan-out cost
onto the producer's request path, and potentially taking a very long
time (or requiring the producer itself to be a distributed job) just
to publish one logical event. It also bloats the topic with millions
of near-identical messages differing only by recipient ID, wasting
storage and network for information (the event itself) that's
genuinely shared across all of them. Keeping the topic event-shaped
and pushing expansion into the consumer (Concept 3's Worker,
horizontally scaled across a consumer group) means the producer's job
stays fast and constant-time regardless of recipient count, and the
actual fan-out work scales independently by adding Worker instances.
</details>

### Q2 [core] — Applying the pattern to a new topic — [ ] not yet attempted
**Scenario:** You're designing a topic for "a new episode of a show was
released" that needs to notify every subscriber of that show, where
some shows have 50 subscribers and others have 50 million.
**Question:** Applying this concept, how should the topic be shaped,
and where should the per-subscriber fan-out happen?

<details><summary>Model answer</summary>

The topic should carry one message per release event (`show_id`,
`episode_id`, released timestamp), not one message per subscriber —
identical reasoning to `notification.events`. A consumer service (its
own consumer group, scaled independently) is responsible for looking
up the current subscriber list for that show and expanding into
per-subscriber notification tasks, published onward to whatever
channel-specific topic handles actual delivery. This keeps the
release-event producer's work constant regardless of whether a show
has 50 or 50 million subscribers, and lets the fan-out step scale
horizontally by adding consumer instances — exactly the two-stage
event-then-expand shape `notification-system.md` already uses.
</details>

## Concept 10: Conditional Kafka Usage — The Fan-out Escape Hatch
_guide: kafka-guide.md#10-conditional-kafka-usage--the-fan-out-escape-hatch_

### Q1 [core] — Why chat's default path skips Kafka — [ ] not yet attempted
**Scenario:** `chat-systems.md`'s default message-delivery path is
direct RPC between connection servers, and it only routes through
Kafka for very large group conversations.
**Question:** Why not just always use Kafka for chat message delivery,
given it's already decoupling and scaling other parts of this repo's
systems?

<details><summary>Model answer</summary>

For a 1:1 or small-group chat, direct RPC between the sender's
connection server and the (few) recipients' connection servers is
already fast and simple — introducing Kafka would add "a small amount
of added latency" (the file's own words) for no real benefit, since
there's no meaningful fan-out problem to solve at that scale: a
handful of direct connections is cheap. Kafka's decoupling/parallelism
benefits (Concepts 1 and 3) only start paying for themselves once the
number of recipients gets large enough that direct RPC would mean one
message triggering connections to many different connection servers
at once (an "N×M direct-connection explosion," per the file) — below
that threshold, Kafka is pure overhead, not a win. This is why the
choice is conditional on group size, not a fixed architectural
decision either way.
</details>

### Q2 [core] — Does this system "use Kafka"? — [ ] not yet attempted
**Scenario:** `chat-systems.md` and `broadcasting-system.md` both
genuinely use Kafka in their design, yet neither carries the `Kafka`
label in `docs/TRACKER.md`.
**Question:** Is this a labeling inconsistency that should be fixed, or
does it make sense given how Kafka is actually used in these two
systems?

<details><summary>Model answer</summary>

It's defensible as-is, though worth being explicit about the
reasoning: the tracker's labels are meant to capture a system's *core*
architecture — the technologies its default, everyday behavior depends
on — and for both `chat-systems.md` and `broadcasting-system.md`,
Kafka is an escape hatch triggered only past a fan-out threshold, not
something the system's normal operation touches. A label audit (the
same spirit as this guide's earlier note on `stock-broker.md`'s
unearned Redis label) should still record *where* the conditional
usage lives — which is exactly what this guide's Concept 10 does — so
the reasoning doesn't get lost even though the tracker's blunt label
column doesn't capture threshold-dependent usage well. The general
principle: a label is a coarse signal, and a design doc's prose is
where the actual nuance belongs.
</details>

## Concept 11: Unused Here — Producer Acks, Idempotent Producers & Exactly-Once Semantics
_guide: kafka-guide.md#11-unused-here--producer-acks-idempotent-producers--exactly-once-semantics_

### Q1 [core] — The gap in payment-event durability — [ ] not yet attempted
**Scenario:** `amazon-order-management-system.md` never states a
producer `acks` setting for `payment.completed`/`payment.failed`.
**Question:** Why does this matter specifically for these two topics,
more than it would for `click.events`, and what setting would you
recommend?

<details><summary>Model answer</summary>

With `acks=1` (the common default), a producer considers a write
successful once the partition's *leader* broker acknowledges it — but
if that leader crashes before replicating the message to its
followers, the message can be lost outright even though the producer
believed the publish succeeded. For `click.events`, losing an
occasional click is a negligible accuracy blip in an already-approximate
metrics pipeline (Concept 7). For `payment.completed`/`payment.failed`,
losing the event outright means Order Service and Inventory Service
never learn a payment succeeded or failed at all — a real
financial-correctness bug, not a rounding error. `acks=all` (leader
plus all in-sync replicas must confirm) is the right call here
specifically because these events represent money moving, and the
existing consumer-side idempotency (Concept 4) only protects against
*duplicate* delivery, not *lost* delivery — a different failure mode
entirely, needing a different fix.
</details>

### Q2 [discussion] — Would exactly-once processing help here? — [ ] not yet attempted
**Scenario:** Kafka's transactional API can provide end-to-end
exactly-once semantics for a consume-transform-produce pipeline (e.g.
consuming `payment.completed` and producing a downstream event
atomically with the consumer offset commit).
**Question:** Would adopting this remove the need for
`amazon-order-management-system.md`'s state-transition dedup (Concept
4)? Argue both sides.

<details><summary>Model answer</summary>

Partially, and only within Kafka's own boundary. Exactly-once
semantics guarantees that a consume-transform-produce step, entirely
within Kafka (reading one topic, writing another, committing the
offset), happens as one atomic unit — no duplicate downstream
publishes from a retried consume. But it does **not** extend to
side effects outside Kafka, like Order Service's `UPDATE orders SET
status = 'PAID' ...` against its own Postgres database — that write
is a separate system from Kafka's transactional guarantee, and Kafka's
exactly-once semantics can't make a Postgres update and a Kafka offset
commit atomic together. So the state-transition dedup would still be
needed for that boundary regardless; exactly-once semantics would only
help if this system had a longer Kafka-to-Kafka pipeline stage where
duplicate *publishes* (not duplicate database writes) were themselves
the concern — which isn't the shape of the problem this system
actually has.
</details>

## Concept 12: Unused Here — Schema Registry, Log Compaction & Multi-DC Replication
_guide: kafka-guide.md#12-unused-here--schema-registry-log-compaction--multi-dc-replication_

### Q1 [core] — Why compaction is the wrong tool for order.lifecycle — [ ] not yet attempted
**Scenario:** A teammate suggests enabling log compaction
(`cleanup.policy=compact`) on `order.lifecycle`, reasoning "we only
care about an order's current status anyway."
**Question:** Why would this be a mistake, given what
`order.lifecycle`'s actual consumers (Notification/Analytics/Search-index)
need?

<details><summary>Model answer</summary>

Log compaction keeps only the *latest* message per key forever,
discarding earlier ones — the right tool when a topic represents
current state (e.g. "the latest known address for this customer,"
where old addresses are truly irrelevant once superseded). But
`order.lifecycle`'s actual consumers need the full sequence of
**events** — Analytics needs every state transition to compute
funnel/conversion metrics, Notification needs each individual
transition to decide what to tell the user at each step ("shipped,"
then later "delivered," not just "delivered" with the "shipped"
message lost). Compacting this topic down to "latest status per
order_id" would silently delete the intermediate events these
consumers depend on — the topic is fundamentally an event log, not a
current-state snapshot, and applies retention-based cleanup (time or
size based), never compaction.
</details>

### Q2 [core] — Where a schema registry would help — [ ] not yet attempted
**Scenario:** Six months after `amazon-order-management-system.md`
ships, the team wants to add a new field to `payment.completed`
messages, and several independently-deployed consumers (Order Service,
Inventory Service, and a newly-added Fraud Detection service) all read
this topic.
**Question:** What problem does the lack of a schema registry create
here, and how would one help?

<details><summary>Model answer</summary>

Without a schema registry, `payment.completed`'s message shape is only
an informal agreement — nothing enforces that all three consumers
agree on the field names, types, or what happens when a new field
appears. If Payment Service starts publishing a new field before every
consumer has been updated to expect it, older consumers might break on
unexpected data, or a producer might accidentally introduce a
breaking change (renaming a field) that silently corrupts a consumer
that hasn't been redeployed yet — with no automated check catching it
before it reaches production. A schema registry versions the message
schema centrally and enforces compatibility rules (e.g. "new fields
must be optional," "no renaming existing fields") at publish time,
catching a breaking change before it's ever published, rather than
after it's already broken a consumer in production — exactly the kind
of safety net that matters once a topic has multiple independently-deployed
consumers, which `payment.completed` already does.
</details>
