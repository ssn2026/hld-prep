---
concept_name: Cassandra Question Bank (Practice)
linked_systems: [Chat Systems, News Feeds, Click Event Aggregator, URL Shortner, Key Value StoreBa, Like and Comment Service]
last_reviewed: 2026-08-16
freshness: Fresh
notion_url: TBD
---

# Cassandra Question Bank

Progress persists as checkboxes below — resuming `/practice cassandra`
finds the first `[ ]` in document order. Guide:
`concepts/practice/cassandra-guide.md`.

## Concept 1: Data Modeling Philosophy — One Table Per Query
_guide: cassandra-guide.md#1-data-modeling-philosophy--one-table-per-query_

### Q1 [core] — Two views of the same data — [ ] not yet attempted
**Scenario:** You're designing an inbox: "a conversation's messages" and
"my conversations, most recent first" both need to exist.
**Question:** Why can't one `messages` table serve both queries well,
and what's the actual fix?

<details><summary>Model answer</summary>

A single partition key can only make *one* access pattern a fast,
single-partition read. `messages(conversation_id, message_id, ...)`
partitioned by `conversation_id` serves "this conversation's messages"
perfectly — but "my conversations, most recent first" needs to filter
by `user_id`, a column that isn't the partition key, which Cassandra
either can't do at all or can only do via an expensive cluster-wide
scan. `chat-systems.md`'s fix: a **second, denormalized** table,
`conversations_by_user(user_id, last_activity_at, conversation_id,
...)`, written to alongside every new message specifically to serve the
second query as its own single-partition read. Two tables, two write
paths, one concept — that's the trade Cassandra modeling makes.
</details>

### Q2 [core] — Reverse lookup without a join — [ ] not yet attempted
**Scenario:** `news-feeds.md` stores `follows(follower_id, followee_id,
...)` for "who does X follow." It also needs "who follows X" (to fan
out a new post).
**Question:** Design the table for the second query, and name what this
pattern is called.

<details><summary>Model answer</summary>
```sql
CREATE TABLE followers_index (
  followee_id uuid,
  follower_id uuid,
  PRIMARY KEY (followee_id, follower_id)
);
```
This is a **denormalized inverted index** — the same logical
relationship as `follows`, stored a second time under the opposite
partition key so both directions are single-partition reads. It has to
be written to explicitly on every follow/unfollow event (no join or
secondary index derives it automatically) — the cost of Cassandra's
"one table per query" philosophy is that the application, not the
database, is responsible for keeping denormalized copies in sync.
</details>

## Concept 2: Partition Keys & Clustering Keys
_guide: cassandra-guide.md#2-partition-keys--clustering-keys_

### Q1 [core] — What each key actually controls — [ ] not yet attempted
**Scenario:** `chat-systems.md` defines `messages` with
`PRIMARY KEY (conversation_id, message_id) WITH CLUSTERING ORDER BY
(message_id DESC)`.
**Question:** What does `conversation_id` control versus what
`message_id` controls, and why does that split make "give me this
conversation's messages, newest first" a single sequential read with no
sort step at query time?

<details><summary>Model answer</summary>

`conversation_id` is the **partition key** — it decides which node(s)
physically own the row (via consistent hashing) and groups all of one
conversation's rows together on disk. `message_id` is the **clustering
key** — it decides the sort order of rows *within* that partition,
maintained incrementally as rows are written, not computed at read
time. Because `CLUSTERING ORDER BY (message_id DESC)` was declared
up front, the rows are physically stored newest-first already — reading
"this conversation's messages, newest first" is just reading the
partition off disk in the order it's already in, no `ORDER BY` sort
cost at query time.
</details>

### Q2 [core] — A lookup with no clustering key — [ ] not yet attempted
**Scenario:** `netfilx.md`'s `watch_progress` table uses
`PRIMARY KEY (user_id, title_id)` with no `CLUSTERING ORDER BY`.
**Question:** Why doesn't this table need a clustering key, in contrast
to `messages`?

<details><summary>Model answer</summary>

The only query this table serves is "get this user's progress on this
specific title" — a direct point lookup by the full primary key, never
"give me all of a user's progress rows in some order." Clustering keys
exist to make *range* reads within a partition fast and pre-sorted; when
every real query pins down the complete key (both `user_id` and
`title_id` known in advance), there's no range to optimize, so adding a
clustering key would add bookkeeping for an access pattern that never
happens. The lesson: don't add a clustering key by habit — add one only
when a real query needs an ordered slice of a partition.
</details>

## Concept 3: Wide Partitions & Time-Bucketing
_guide: cassandra-guide.md#3-wide-partitions--time-bucketing_

### Q1 [core] — Diagnosing the wide partition — [ ] not yet attempted
**Scenario:** A junior engineer designs `page_clicks(page_id,
clicked_at, ...)` with `PRIMARY KEY (page_id, clicked_at)` for a
viral page that gets sustained heavy traffic for years.
**Question:** What goes wrong with this design over time, and how does
`click-event-aggregator.md`'s actual schema avoid it?

<details><summary>Model answer</summary>

Every click for that page lands in the *same* partition (`page_id`
never changes), so the partition grows without bound for as long as the
page keeps getting traffic — years of clicks, all on nodes that own
that one partition, eventually hitting Cassandra's practical
per-partition size and compaction-time limits, and making even a
"recent clicks" read slower as the partition balloons. `click-event-aggregator.md`'s
actual table, `page_metrics(page_id, window_start, click_count, ...)`
with `PRIMARY KEY (page_id, window_start)`, **buckets by time window**
— each partition only ever holds one page's data for one bounded time
span (e.g. one day), so no partition grows past a predictable size no
matter how long the page stays popular.
</details>

### Q2 [core] — Choosing a bucket size — [ ] not yet attempted
**Scenario:** You're bucketing a high-volume sensor-reading table by
day, but a handful of sensors report every second, 24/7 — those daily
partitions are still enormous.
**Question:** What's the actual trade-off in picking a bucket size, and
what would you do differently for these hot sensors?

<details><summary>Model answer</summary>

Smaller buckets (hourly instead of daily) shrink each partition but
multiply the number of partitions the application has to query and
stitch together for any range spanning multiple buckets — e.g. "last 3
days" becomes 72 separate partition reads instead of 3. The right
bucket size is the one where a typical partition stays comfortably
small (low hundreds of MB, not GB) for the *actual* write rate of that
key, which means one fixed bucket size doesn't have to be uniform across
all rows — a common real fix is bucketing by write-volume tier:
standard sensors get daily buckets, but a known set of high-volume
sensors gets hourly (or even per-10-minutes) buckets specifically
because their write rate would otherwise blow past what a daily
partition can hold comfortably.
</details>

## Concept 4: Consistency Levels & the Replication Quorum
_guide: cassandra-guide.md#4-consistency-levels--the-replication-quorum_

### Q1 [core] — Why QUORUM/QUORUM is "consistent enough" — [ ] not yet attempted
**Scenario:** `key-value-storeba.md` uses replication factor N=3, write
quorum W=2, read quorum R=2.
**Question:** Explain, mechanically, why `R + W > N` guarantees a read
sees the most recent acknowledged write, without needing all 3 replicas
to respond to either operation.

<details><summary>Model answer</summary>

A write is acknowledged once **2 of 3** replicas confirm it — so after
any acknowledged write, at least 2 of the 3 replicas hold the new
value (possibly all 3, but at least 2 guaranteed). A subsequent read
also only needs **2 of 3** replicas to respond. Since both the write's
"at least 2 have it" set and the read's "ask any 2" set are drawn from
the same pool of 3 replicas, and `2 + 2 = 4 > 3`, those two sets of 2
are mathematically guaranteed to overlap in at least one replica —
meaning the read is guaranteed to hear from at least one replica that
has the latest write, and (using each replica's write timestamp) can
correctly return the newest value, all without ever needing a
response from all 3.
</details>

### Q2 [core] — Picking a level for a real query — [ ] not yet attempted
**Scenario:** `notification_log` (from `notification-system.md`) is
written once per notification and read back as "show me my last 20
notifications" — a UI list where a few-second staleness is
imperceptible to the user, but the write path is extremely
high-volume.
**Question:** What consistency level would you pick for the write, and
for the read, and why not the strongest option (`ALL`) for both?

<details><summary>Model answer</summary>

`LOCAL_QUORUM` for both is the standard choice here — strong enough
that a read reliably sees recent writes (per Q1's overlap guarantee,
assuming both operations use quorum), while only requiring a majority
of replicas rather than every replica to respond. `ALL` would demand
every single replica acknowledge every write and respond to every
read — meaning a single slow or temporarily-down replica stalls or
fails the *entire* operation, which is exactly the kind of
availability trade-off this system's real requirement (extremely
high write volume, tolerant of brief staleness) doesn't need to make.
`ALL` is reserved for cases where every replica being current is
itself the requirement, not the default-safe choice.
</details>

## Concept 5: Lightweight Transactions (LWT)
_guide: cassandra-guide.md#5-lightweight-transactions-lwt_

### Q1 [core] — Custom alias collision — [ ] not yet attempted
**Scenario:** `url-shortner.md` lets users pick a custom short code
(`bit.ly/my-brand`) instead of a generated one — two users could pick
the same alias in the same instant.
**Question:** Write the insert that guarantees only one wins, and name
why a plain `INSERT` isn't enough here (unlike most tables in this
repo).

<details><summary>Model answer</summary>
```sql
INSERT INTO url_mappings (short_code, long_url, created_at, status)
VALUES (?, ?, ?, 'ACTIVE')
IF NOT EXISTS;
```
A plain `INSERT` in Cassandra is last-write-wins by default — if two
users' inserts for the same `short_code` arrive close together, the
second one would just silently overwrite the first with no error and
no signal that a collision happened. `IF NOT EXISTS` triggers
Cassandra's Paxos-based LWT protocol, which coordinates across
replicas to guarantee only the first insert actually applies — the
second gets back `[applied] = false`, which the application uses to
tell that user their chosen alias is taken. This is the one genuine
correctness requirement (uniqueness) that plain writes can't provide.
</details>

### Q2 [core] — When NOT to reach for LWT — [ ] not yet attempted
**Scenario:** A teammate proposes wrapping every write to
`netfilx.md`'s `watch_progress` table in `IF EXISTS` "just to be safe,"
even though progress updates are simple overwrites where the latest
write should always win.
**Question:** Why is this the wrong call?

<details><summary>Model answer</summary>

LWTs cost roughly an order of magnitude more than a plain write — they
require multiple round trips across replicas to run the Paxos
protocol, versus one round trip for a normal write. `watch_progress`
has no correctness requirement an LWT would protect: "last-write-wins
is fine" is explicitly the stated design, meaning any ordering of
concurrent updates producing *a* final value is acceptable — there's
no "only one may succeed" invariant to enforce. Paying LWT's latency
and throughput cost on every write to a high-volume table, for a
guarantee the table doesn't need, would be a pure regression with no
correctness upside — the rule is to reach for LWT only when an
absent atomicity guarantee would be a real bug, not by default.
</details>

## Concept 6: Secondary Indexes vs. Denormalized Query Tables
_guide: cassandra-guide.md#6-secondary-indexes-vs-denormalized-query-tables--unused-here_

### Q1 [core] — Why not just add an index? — [ ] not yet attempted
**Scenario:** A teammate suggests adding `CREATE INDEX ON messages
(sender_id)` to `chat-systems.md`'s `messages` table so "find all
messages this user sent across all conversations" becomes a simple
query, instead of building a new denormalized table.
**Question:** Why does this repo consistently avoid secondary indexes
in favor of denormalized tables, and what specifically goes wrong with
the index approach at scale?

<details><summary>Model answer</summary>

`messages` is partitioned by `conversation_id`, so `sender_id` isn't
the partition key — a secondary index on it is typically a per-node
local index, meaning satisfying `WHERE sender_id = ?` still requires
fanning the query out to *every* node in the cluster and merging
results, because any node could hold a matching row in some
partition. That's exactly the cost a partition key is supposed to
avoid — the query no longer touches one predictable partition, it
touches the whole cluster. The repo's consistent alternative: build a
real denormalized table, `messages_by_sender(sender_id, message_id,
conversation_id, ...)`, keyed by the column you actually need to query
by — more write-time bookkeeping (write to two tables), but a query
that stays a fast, single-partition read forever, at any scale.
</details>

### Q2 [core] — The narrow case where a secondary index is fine — [ ] not yet attempted
**Scenario:** A support-tooling admin panel needs to occasionally look
up a user by a rarely-changing `internal_flag` column, run maybe a few
times a day by internal staff, never on a user-facing hot path.
**Question:** Is this a reasonable case to use a secondary index rather
than building a whole new denormalized table? Justify it.

<details><summary>Model answer</summary>

Yes — this is close to the one legitimate use case for Cassandra
secondary indexes: low query frequency, no latency requirement, and a
column with low-to-moderate cardinality, run by internal tooling
rather than serving live user traffic. The cluster-wide fan-out cost
that makes secondary indexes wrong for a hot-path query (Q1) is
tolerable here because it happens rarely and nobody is waiting on it
inside a request's critical path. Building a full denormalized table
and its associated write-path bookkeeping for a query that runs a few
times a day would be over-engineering — the secondary index is the
right-sized tool specifically because the query's frequency and
latency requirements are both low.
</details>

## Concept 7: Materialized Views
_guide: cassandra-guide.md#7-materialized-views--unused-here_

### Q1 [core] — MV vs. hand-written denormalization — [ ] not yet attempted
**Scenario:** A teammate suggests replacing `news-feeds.md`'s
hand-maintained `followers_index` table with a Cassandra materialized
view defined over `follows`, since an MV would auto-update itself on
every write to the base table.
**Question:** What's the appeal, and what's the concrete risk that led
this repo to avoid MVs everywhere instead?

<details><summary>Model answer</summary>

The appeal is real: an MV removes the burden of remembering to write to
both `follows` and `followers_index` in application code — the database
maintains the denormalized copy for you. The risk: MV maintenance
happens asynchronously in the background, and under heavy write load or
a node failure, the view can silently fall behind or diverge from the
base table, with no built-in alert or repair signal telling you it
happened — you'd only find out when a read from the view returns stale
or missing data. Hand-maintained denormalization (write to both tables
explicitly, in the same application-level operation) is more code, but
it's code you can reason about and test, versus an asynchronous
consistency guarantee you can't directly observe or control.
</details>

### Q2 [discussion] — Would you ever choose an MV? — [ ] not yet attempted
**Scenario:** Consider a low-write-volume internal admin table where
staleness of a few seconds in a denormalized view genuinely doesn't
matter, and the team is small enough that "someone forgot to update the
second table" is a realistic risk.
**Question:** Argue for or against using a materialized view here,
contrasting it with the production-facing systems in this repo.

<details><summary>Model answer</summary>

This is a more defensible case for an MV than any user-facing table in
this repo: low write volume means the async-lag risk from Q1 is small
in absolute terms, staleness is explicitly tolerable, and the "human
forgets to write to the second table" risk is arguably *worse* than
the MV's consistency risk for a small team without strong review
discipline around dual-write code paths. The contrast: every
production system in this repo (`chat-systems.md`, `news-feeds.md`)
made the opposite trade because they're high-write-volume and
user-facing, where MV lag becomes both more likely (more writes to lag
behind) and more visible (users notice missing recent activity). The
right call depends on the actual write volume and who's harmed by
staleness — it's a real trade-off, not a rule to apply uniformly.
</details>

## Concept 8: Token Ring, Consistent Hashing & Gossip Protocol
_guide: cassandra-guide.md#8-token-ring-consistent-hashing--gossip-protocol--unused-at-the-cql-level_

### Q1 [core] — What a partition key choice actually decides — [ ] not yet attempted
**Scenario:** You're told "the partition key determines both logical
grouping *and* physical placement" but asked to explain the mechanism,
not just repeat the phrase.
**Question:** Walk through what actually happens, from a partition key
value to which physical node stores that row.

<details><summary>Model answer</summary>

The partition key's value is hashed (Cassandra uses a consistent
hashing function) to produce a **token**, a position on a conceptual
ring covering the full range of possible hash outputs. Each node in the
cluster owns one or more contiguous ranges of that ring. A row's token
determines which range — and therefore which node — is its primary
owner; the next N-1 nodes walking clockwise around the ring from that
point become its replicas (for replication factor N). `key-value-storeba.md`'s
`replica_set: [node_a, node_b, node_c]` is this ring lookup made
concrete — those three nodes are the ones whose owned ranges cover that
particular key's token.
</details>

### Q2 [core] — Gossip and failure detection — [ ] not yet attempted
**Scenario:** A node in a Cassandra cluster silently goes offline. No
central coordinator exists to notice.
**Question:** How does the rest of the cluster find out, and why is
this specifically relevant to `key-value-storeba.md`'s hinted-handoff
mechanism?

<details><summary>Model answer</summary>

Nodes periodically **gossip** — each node exchanges state (which nodes
it believes are alive, their token ranges, load, schema version) with a
few random peers on a fixed interval, and that state propagates through
the cluster exponentially rather than needing a central coordinator to
poll everyone. When a node stops responding to gossip messages for
long enough, its peers mark it as down and that belief spreads the same
way. This is precisely what makes hinted handoff possible: a
coordinator handling a write knows (via gossip) that a target replica
is currently down, so instead of failing the write it stores a
"hint" locally and replays it once gossip reports that replica back
online — the failure detection and the recovery mechanism are directly
linked.
</details>

## Concept 9: Hinted Handoff, Read Repair, Tombstones & Compaction
_guide: cassandra-guide.md#9-hinted-handoff-read-repair-tombstones--compaction--unused-here_

### Q1 [core] — The tombstone read-latency trap — [ ] not yet attempted
**Scenario:** A table is used as a work queue: rows are inserted, then
deleted once processed, at high volume, all within the same partition
key (e.g. `queue_id`).
**Question:** Why does this specific access pattern degrade badly on
Cassandra, and what's the underlying mechanism?

<details><summary>Model answer</summary>

A Cassandra `DELETE` doesn't remove the row immediately — it writes a
**tombstone**, a marker meaning "this data is deleted," which still
physically occupies space and still has to be read past on every query
touching that partition, right up until compaction eventually purges
it for good (after `gc_grace_seconds`). A queue pattern that inserts
and deletes at high volume within one partition accumulates
tombstones faster than compaction clears them, so every read of that
partition has to scan through a growing pile of dead markers before
reaching live data — read latency creeping upward over time even
though the *live* row count stays roughly constant. This is exactly
why Cassandra is a poor fit for queue-shaped workloads; a real queue
(Kafka, SQS) or a bounded, TTL-expiring table is the better tool.
</details>

### Q2 [core] — Read repair vs. hinted handoff — [ ] not yet attempted
**Scenario:** Two different failure scenarios: (a) a replica was down
during a write and comes back later; (b) all replicas were up during
the write, but a subsequent read notices they disagree on the value.
**Question:** Which mechanism resolves each, and why are they different
mechanisms rather than one?

<details><summary>Model answer</summary>

(a) is **hinted handoff**'s job — the coordinator noticed the replica
was down *at write time* and stored a hint to replay once it returns,
proactively fixing the gap without waiting for a read to notice it. (b)
is **read repair**'s job — this is a case hinted handoff can't cover,
because nothing was ever known to be down; the divergence might come
from a dropped message, a brief partition, or a replica that missed an
update for some other transient reason. Read repair only fires
reactively, when a read at consistency level requiring multiple
replicas notices they disagree, and then pushes the newest value to
the stale ones as a side effect of that read. They're separate
mechanisms because they detect divergence at different times (write
time vs. read time) via different signals (known-down vs.
observed-disagreement) — together they're what keeps replicas
eventually consistent without an operator manually reconciling them.
</details>

## Concept 10: Counter Columns
_guide: cassandra-guide.md#10-counter-columns--unused-here_

### Q1 [core] — Counter vs. Redis for a like count — [ ] not yet attempted
**Scenario:** `like-and-comment-service.md` needs a per-post like count
under heavy concurrent increment/decrement, and chose a Redis counter
over a Cassandra `counter` column.
**Question:** What does a Cassandra counter column actually give you,
and why might Redis still be the better choice here?

<details><summary>Model answer</summary>

A `counter` column type lets Cassandra do atomic increment/decrement
(`UPDATE likes SET count = count + 1 WHERE post_id = ?`) without a
read-modify-write race, which is exactly the primitive an approximate
like counter needs. But counter columns come with real constraints: a
table containing a counter column can contain *only* counter columns
(no mixing with regular data columns in the same table), they have no
default value, and under network partitions a retried write can
over-count (counters aren't idempotent the way a plain overwrite is).
`like-and-comment-service.md` already needed Redis for the *membership*
check (`SISMEMBER`, "did this user like it"), so keeping the
approximate count in Redis too (a simple `INCR`/`DECR`) avoids
introducing a second storage system's semantics for one column, and
Redis's counter doesn't share Cassandra counters' retry over-count
risk in the same way.
</details>

### Q2 [core] — When a counter column is the right call — [ ] not yet attempted
**Scenario:** Describe a scenario, ideally from a system-shape already
in this repo, where a Cassandra counter column genuinely would be the
better choice over a Redis counter.
**Question:** Justify it.

<details><summary>Model answer</summary>

A good fit: `click-event-aggregator.md`'s `page_metrics.click_count` —
*if* the system didn't already have a Kafka stream-processing layer
pre-aggregating counts before the Cassandra write. In a simpler version
of that system with no stream processor, writing directly to a
Cassandra counter column keyed by the same `(page_id, window_start)`
partition/clustering scheme would avoid introducing Redis as a second
system purely for counting, when the data is already living in
Cassandra for the metrics table itself and doesn't need Redis's
sub-millisecond latency (metrics dashboards tolerate more staleness
than a live per-request check). The general rule: prefer a Cassandra
counter over a second system's counter when the data already lives in
Cassandra for other reasons and the read-latency requirement is loose
enough not to need Redis's speed.
</details>

## Concept 11: Batch Statements — Logged vs. Unlogged
_guide: cassandra-guide.md#11-batch-statements--logged-vs-unlogged_

### Q1 [core] — Why NOT to batch the news-feeds dual write — [ ] not yet attempted
**Scenario:** A teammate wants to wrap `news-feeds.md`'s write to
`follows` and `followers_index` (Concept 1 Q2) in a single `BATCH`
statement for "efficiency."
**Question:** Should this be a logged batch, an unlogged batch, or no
batch at all? Justify it.

<details><summary>Model answer</summary>

Neither. `follows` is partitioned by `follower_id`, `followers_index`
by `followee_id` — two different partitions, likely on two different
sets of nodes. An **unlogged** batch across different partitions gives
up its only benefit (it's only a real optimization when every statement
targets the *same* partition, letting the coordinator send one message
instead of several); across different partitions it's strictly worse
than two independent writes, since the coordinator now has to
orchestrate multiple nodes as one unit for no efficiency gain. A
**logged** batch would add atomicity via a write-ahead batchlog, but at
real cost, and "both writes eventually succeed" is not actually a hard
requirement here — this repo's actual design leaves the two writes as
independent, unordered application-level calls, which is the correct
call: batching only pays off for same-partition writes, and full
atomicity here isn't worth the batchlog overhead for two independent
denormalized copies.
</details>

### Q2 [core] — A case where unlogged batching helps — [ ] not yet attempted
**Scenario:** `chat-systems.md`'s `messages` table sometimes needs a new
message row and an updated "last message preview" column written
together, both scoped to the same `conversation_id`.
**Question:** Is this a good candidate for an unlogged batch? Why?

<details><summary>Model answer</summary>

Yes, if both statements share the same partition key
(`conversation_id`) — this is exactly the case unlogged batches exist
for. Since both writes are going to the same partition, and therefore
the same coordinator/replica set, grouping them into one unlogged batch
means one network round trip instead of two, with no meaningful
atomicity cost being given up (they were headed to the same node
anyway). The distinction from Q1 is entirely about whether the
statements share a partition key — same partition, unlogged batch is a
real efficiency win; different partitions, it's a coordination cost
with no benefit.
</details>

## Concept 12: Replication Factor & Multi-DC Topology
_guide: cassandra-guide.md#12-replication-factor--multi-dc-topology--unused-here_

### Q1 [core] — Single-DC RF choice — [ ] not yet attempted
**Scenario:** None of this repo's 11 Cassandra systems specify a
replication strategy explicitly.
**Question:** What would the default, reasonable choice be for a
single-region deployment, and why is RF=3 the conventional floor rather
than RF=1 or RF=2?

<details><summary>Model answer</summary>

`SimpleStrategy` with `replication_factor: 3` (or
`NetworkTopologyStrategy` with `{'datacenter1': 3}`, the
production-recommended form even for a single DC) is the conventional
default. RF=1 means any single node failure loses data outright — no
redundancy at all. RF=2 allows surviving one node failure but makes
quorum reads/writes (`QUORUM` = 2 of 2, i.e. `ALL`) fragile — losing
even one node means quorum operations can no longer complete. RF=3 is
the floor that lets `QUORUM` mean "2 of 3" (Concept 4) — genuinely
tolerating one node being down or slow while still getting the
overlap guarantee that makes reads see recent writes, which is why
it's the standard starting point rather than a number chosen for this
specific workload.
</details>

### Q2 [discussion] — When would this repo's systems need multi-DC? — [ ] not yet attempted
**Scenario:** Picture `notification-system.md` expanding from a single
region to serving users in both the US and EU, with a stated
requirement to keep serving each region's traffic locally even if the
other region's data center goes offline.
**Question:** What changes about the replication strategy, and what new
trade-off does it introduce?

<details><summary>Model answer</summary>

This would move to `NetworkTopologyStrategy` with a per-datacenter RF,
e.g. `{'us-east': 3, 'eu-west': 3}` — each region keeps a full local
replica set, so reads and writes in each region can stay
local-only (`LOCAL_QUORUM`) without crossing the ocean on every
request, and either region can keep serving traffic if the other goes
dark. The new trade-off: writes now have to eventually propagate
cross-DC (asynchronously, since `LOCAL_QUORUM` doesn't wait for the
remote DC to acknowledge), meaning a user who writes in `us-east` and
immediately reads from `eu-west` can briefly see stale data — a real
consistency cost taken on specifically to buy regional availability
and low local latency, not something to add without an actual
multi-region requirement driving it.
</details>
