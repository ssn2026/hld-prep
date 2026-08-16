---
concept_name: Cassandra Concepts (Practice Guide)
linked_systems: [Netfilx, Broadcasting System, Youtube, Click Event Aggregator, Notification System, Like and Comment Service, Key Value StoreBa, URL Shortner, Uber find nearby driver, News Feeds, Chat Systems]
last_reviewed: 2026-08-16
freshness: Fresh
notion_url: TBD
---

# Cassandra Concepts — Practice Guide

**Question bank:** `concepts/practice/cassandra-question-bank.md`

The recurring justification across every Cassandra table already built in
this repo: **high write volume + a simple, known-in-advance access
pattern, partitioned by the key the query actually filters on** — never
"model the entities," always "model the query." Sections 1–5 below are
patterns this repo already uses concretely; sections 6–9 cover
concepts **no system here has needed yet** (called out explicitly, the
same way the SQL audit flagged unused concepts) — worth knowing for an
interview even though nothing in this repo demonstrates them.

## 1. Data Modeling Philosophy — One Table Per Query

Cassandra has no joins and (practically) no ad-hoc `WHERE` on
non-key columns, so a table that tries to serve two different access
patterns is a table that serves one of them badly. `chat-systems.md` is
the clearest example: "a conversation's messages" and "my conversations,
most recent first" look like one concept but need two tables —
`messages(conversation_id, message_id, ...)` and a **denormalized
inverted index**, `conversations_by_user(user_id, last_activity_at,
conversation_id, ...)` — because a single partition key can't serve
both. `news-feeds.md` does the identical thing for `followers_index`,
the reverse lookup of `follows`, written to twice on every follow event
rather than derived from `follows` at read time.

## 2. Partition Keys & Clustering Keys

The partition key decides which node(s) own a row (via consistent
hashing over the key, Concept 8); the clustering key decides sort order
*within* that partition — it's a live index, not a search filter.
`netfilx.md`'s `watch_progress` uses `PRIMARY KEY (user_id, title_id)` —
no clustering key ordering matters, it's a pure lookup. `chat-systems.md`'s
`messages` uses `PRIMARY KEY (conversation_id, message_id) WITH
CLUSTERING ORDER BY (message_id DESC)` — the clustering key is doing
real work, guaranteeing "give me this conversation's messages, newest
first" is a single sequential read with zero sorting at query time.

## 3. Wide Partitions & Time-Bucketing

A partition keyed by something unbounded and ever-growing (all of a
popular page's clicks, forever) becomes a **wide partition** — slow to
compact, slow to read, and eventually past Cassandra's practical
per-partition size limits. `click-event-aggregator.md`'s
`page_metrics(page_id, window_start, click_count, ...)` with
`PRIMARY KEY (page_id, window_start)` is the repo's explicit fix: bucket
by time window so each partition only ever holds one page's metrics for
a bounded span, not its entire lifetime history in one place.

## 4. Consistency Levels & the Replication Quorum

Cassandra doesn't have one fixed consistency guarantee — each read and
write independently picks a **consistency level** (`ONE`, `QUORUM`,
`LOCAL_QUORUM`, `ALL`, ...) trading latency against how many replicas
must agree. `key-value-storeba.md` walks this mechanism concretely, even
though it's phrased as internals rather than CQL: replication factor
N=3, write quorum W=2, read quorum R=2 — and because `R + W > N`, every
read is guaranteed to overlap with the most recent write's acknowledged
replicas, which is what makes `QUORUM`/`QUORUM` reads "strongly
consistent enough" without needing all N replicas to respond. No other
system in this repo states a consistency level explicitly — in practice
they'd default to `LOCAL_QUORUM` for both reads and writes, the standard
balance for a single-region deployment.

## 5. Lightweight Transactions (LWT)

Normal Cassandra writes are last-write-wins with no atomicity across a
read-then-write — fine for `netfilx.md`'s progress overwrites ("last-write-wins
is fine"), wrong when you need "insert only if this doesn't already
exist." **LWTs** (`IF NOT EXISTS` / `IF EXISTS` / `IF column = value`)
use a Paxos-based protocol to get that guarantee, at a real cost — an
LWT takes multiple round trips versus one, roughly an order of magnitude
slower than a normal write. `url-shortner.md` is the one file that needs
this and uses it twice: `INSERT INTO url_mappings (...) VALUES (...) IF
NOT EXISTS` for custom-alias creation (must atomically reject a
collision), and `UPDATE id_batches SET next_id = next_id + 10000 WHERE
batch_owner = ? IF EXISTS` for the ID-batch reservation. The rule of
thumb this repo follows: reach for an LWT only when the *absence* of
atomicity would be a correctness bug, not a performance nuisance —
everywhere else, plain writes are strictly preferred.

## 6. Secondary Indexes vs. Denormalized Query Tables — Unused Here

**No system in this repo uses a Cassandra secondary index**, and that's
a deliberate pattern, not an oversight. A secondary index on a
non-partition-key column looks like a relational index but isn't one —
it's typically a per-node local index, so satisfying the query still
means fanning out to every node in the cluster and merging results,
which defeats the whole point of a partition key. Every system that
needed "look this up by a different column" instead built a **second,
denormalized table** keyed by that column (Concept 1's
`followers_index`, `conversations_by_user`) — more storage and more
write-time bookkeeping, traded deliberately for a query that stays a
single-partition read.

## 7. Materialized Views — Unused Here

Cassandra MVs promise to auto-maintain a `followers_index`-style
denormalized table *for* you, updated automatically whenever the base
table changes — solving Concept 6's "write to two tables by hand"
tedium. No system here uses one, and the reason generalizes: MV
maintenance happens asynchronously and can silently fall behind or
diverge from the base table under heavy write load or node failure, with
no built-in repair signal — this repo's systems all chose to write to
both denormalized tables explicitly in application code instead, trading
a bit of code duplication for a guarantee they can reason about.

## 8. Token Ring, Consistent Hashing & Gossip Protocol — Unused at the CQL Level

Every partition key hashes to a position on a ring of token ranges, each
range owned by N nodes (replication factor); this is *why* a partition
key choice in Concept 2 also decides physical data placement, not just
logical grouping. Nodes learn the ring's membership and each other's
health via **gossip** — periodic peer-to-peer state exchange, not a
central coordinator — which is how a Cassandra cluster keeps working
through individual node failures without a single point of failure.
`key-value-storeba.md`'s `replica_set: [node_a, node_b, node_c]` is this
mechanism made concrete, though the file doesn't name gossip explicitly;
no system in this repo designs around gossip's failure-detection
behavior directly, since that's cluster-operations territory rather than
an application-level schema decision.

## 9. Hinted Handoff, Read Repair, Tombstones & Compaction — Unused Here

Three related maintenance mechanisms no file in this repo needed to
reason about explicitly: **hinted handoff** (a coordinator temporarily
stores a write meant for a down replica, replaying it once that replica
returns — `key-value-storeba.md` names this one directly); **read
repair** (a read that notices replicas disagree fixes the stale ones in
the background); and **tombstones** (a Cassandra `DELETE` doesn't
actually remove data immediately — it writes a tombstone marker that has
to be read past on every query touching that partition until
`compaction` physically removes it, which is why an accidental
`DELETE`-heavy access pattern degrades a table's read latency over time
in a way no system here has had to design around, since none of them
delete rows on a hot path). Compaction strategy (`SizeTieredCompactionStrategy`
default vs. `LeveledCompactionStrategy` for read-heavy tables vs.
`TimeWindowCompactionStrategy` for the time-bucketed shape
`click-event-aggregator.md` already uses) is a cluster-tuning decision,
not a schema one — worth knowing it exists, not worth designing around
without a real read/write ratio in hand.

## 10. Counter Columns — Unused Here

Cassandra has a special `counter` column type for atomic
increment/decrement without a read-modify-write cycle — the natural fit
for "how many likes does this post have." `like-and-comment-service.md`
explicitly does **not** use one, keeping the approximate like count in a
Redis counter instead — worth noticing *why*: counters can't coexist
with regular columns in the same table, can't have a default value, and
under network partitions can over/under-count on retried writes,
whereas Redis's counter already fit that system's "approximate is fine"
requirement without those constraints.

## 11. Batch Statements — Unused Here

A CQL `BATCH` groups multiple statements into one round trip.
**Logged batches** get atomicity across partitions via a
write-ahead batchlog — but that's expensive and explicitly discouraged
across more than a handful of partitions, since it turns Cassandra's
horizontally-scaled writes into a coordinated multi-node operation.
**Unlogged batches** skip that log and are only a true optimization when
every statement in the batch targets the *same* partition (e.g.
writing to `messages` and touching that same conversation's metadata
row together) — grouped for efficiency, not atomicity. No system in
this repo currently batches writes; `news-feeds.md`'s dual write to
`follows` and `followers_index` (different partition keys) is the one
place a batch might look tempting and is exactly the multi-partition
case where it would be the wrong tool — those two writes are correctly
independent, unordered application-level calls instead.

## 12. Replication Factor & Multi-DC Topology — Unused Here

Every table in this repo implicitly assumes a single-region deployment
with a modest replication factor (3 is standard). None of the 11
Cassandra-labeled systems specify a `NetworkTopologyStrategy` with
per-datacenter RF, because none of them have stated a multi-region
requirement — this is a case where the concept is genuinely orthogonal
to the schema design already done, and would only become relevant if a
future session revisits one of these systems with an explicit
multi-region scale requirement.
