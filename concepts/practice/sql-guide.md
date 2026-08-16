---
concept_name: SQL Concepts (Practice Guide)
linked_systems: [Amazon Order Managment System, Movie Ticket Booking, Hotel ReservationSyste, Flight Ticket Booking, Doctor Appointment, Digital Wallet, Payment Gateway, Stock Broker, Rate Limiter, LeaderBoard, Google Maps, Proximity ServiceBase, Google Drive, Unique Id Generator]
last_reviewed: 2026-08-16
freshness: Fresh
notion_url: TBD
---

# SQL Concepts — Practice Guide

**Engine: PostgreSQL throughout.** Where behavior is Postgres-specific
(it often is — locking, MVCC, upserts, 2PC), that's called out
explicitly rather than presented as generic SQL.

**Question bank:** `concepts/practice/sql-question-bank.md`

## 1. Schema Design Methodology — Keys Follow Queries

The recurring discipline across every system in this repo: write out
the actual queries first (CLAUDE.md's step 2, before step 7's schema).
A schema is a *consequence* of access patterns, not an upfront guess at
"what entities exist." Two systems that would have the wrong schema if
built the other way around:

- `chat-systems.md` needed *two* tables for what looks like one
  concept — `messages` partitioned by `conversation_id` for "a
  conversation's messages," and a separate `conversations_by_user`
  partitioned by `user_id` for "my conversation list." One table
  can't have two good partition keys.
- `digital-wallet.md` stores `ledger_entries`, not a mutable `balance`
  column, because the real query isn't "what's the balance" — it's
  "prove the books balance," which needs every entry, not just the
  latest total.

## 2. Pessimistic Locking

`SELECT ... FOR UPDATE` acquires a row-level lock that blocks other
transactions from locking (or in some modes, even reading a
locked-for-update version of) the same row until commit/rollback.
Postgres actually has four row-lock strengths, not just one:

| Mode | Blocks |
|---|---|
| `FOR UPDATE` | any other `FOR UPDATE`/`FOR SHARE` on the same row |
| `FOR NO KEY UPDATE` | same, but permits concurrent `FOR KEY SHARE` (used internally by FK checks) |
| `FOR SHARE` | other `FOR UPDATE`, but not other `FOR SHARE` |
| `FOR KEY SHARE` | only blocks changes to the row's key columns |

`digital-wallet.md` uses plain `FOR UPDATE` on both accounts in a
transfer — the strongest mode, appropriate since the whole row is
about to change.

## 3. Optimistic Locking

A `version` integer column, bumped on every update, checked in the
`WHERE` clause:
```sql
UPDATE orders SET status = 'CONFIRMED', version = version + 1
WHERE order_id = ? AND version = ?;
-- 0 rows affected = someone else updated it first; the caller re-reads and retries
```
No lock held across the read-think-write gap — cheap under low
contention, but requires the caller to handle the "0 rows" case with a
retry loop. `amazon-order-management-system.md` names this as the
alternative to `FOR UPDATE` for order state transitions.

**When to pick which:** optimistic wins when conflicts are rare and
retries are cheap (a user rarely edits the same order twice at once);
pessimistic wins when conflicts are expected and a retry loop would
itself thrash (two concurrent transfers touching the same wallet on a
busy day).

## 4. Deadlock Avoidance & Detection

**Avoidance (application-level):** always acquire locks in the same
fixed order, regardless of which "direction" the operation is
logically going. `digital-wallet.md` locks accounts by `account_id`
ascending, never by "sender first" — this is what makes two transfers
moving money in opposite directions between the same pair of accounts
unable to deadlock.

**Detection (Postgres does this automatically):** if avoidance fails
and a real deadlock forms anyway, Postgres doesn't hang forever — after
`deadlock_timeout` (default 1s), it checks the wait-for graph for a
cycle, and if found, aborts one transaction with `ERROR: deadlock
detected` (SQLSTATE `40P01`) so the other can proceed. This is a
backstop, not a substitute for ordering locks correctly — relying on it
means every deadlock becomes a user-visible error and a wasted
transaction.

## 5. Atomic Conditional Updates (Lock-Free)

A single `UPDATE ... WHERE condition` closes the read-then-write race
without ever taking an explicit lock — the row lock Postgres takes
internally for the duration of the statement is enough, because the
condition and the write happen in one atomic step:
```sql
UPDATE inventory SET available_qty = available_qty - 1
WHERE product_id = ? AND available_qty >= 1;
```
Used throughout this repo (`amazon-order-management-system.md`'s
inventory, `flight-ticket-booking.md`'s fare buckets) specifically to
avoid needing `FOR UPDATE` at all for a check-and-decrement that fits
in one statement.

## 6. Unique Constraints & Idempotency (Upsert)

A unique constraint turns "did this already happen" into a database
guarantee instead of an application race:
```sql
INSERT INTO idempotency_keys (key, order_id) VALUES (?, ?)
ON CONFLICT (key) DO NOTHING;   -- Postgres upsert syntax — NOT the same as MySQL's ON DUPLICATE KEY
```
`ON CONFLICT ... DO UPDATE` is the same idea for a real upsert (insert,
or update if it already exists):
```sql
INSERT INTO chunks (chunk_hash, ref_count) VALUES (?, 1)
ON CONFLICT (chunk_hash) DO UPDATE SET ref_count = chunks.ref_count + 1;
```
(from `google-drive.md`'s chunk deduplication.)

## 7. Isolation Levels

Postgres implements three practically-distinct levels (it accepts
`READ UNCOMMITTED` but treats it identically to `READ COMMITTED` —
Postgres never does dirty reads):

- **Read Committed** (the default) — each statement sees a fresh
  snapshot as of when *that statement* began. Two statements in the
  same transaction can see different committed states if another
  transaction commits in between.
- **Repeatable Read** — the whole transaction sees one snapshot, taken
  at its first statement. Prevents non-repeatable reads and phantom
  reads within that transaction.
- **Serializable** — Repeatable Read plus genuine serializability,
  implemented via **SSI (Serializable Snapshot Isolation)**: Postgres
  tracks read/write dependencies between concurrent serializable
  transactions and aborts one with `ERROR: could not serialize access`
  if committing both together could never have happened in *any*
  serial order — even if they never touched the same row. This is
  fundamentally different from locking: nothing blocks, transactions
  just may need to retry after the fact.

## 8. MVCC (Multi-Version Concurrency Control)

Every row in Postgres carries hidden `xmin`/`xmax` columns — the
transaction ID that created it and the one that deleted/superseded it
(if any). An `UPDATE` doesn't overwrite in place; it inserts a new row
version and marks the old one's `xmax`. This is *why* readers never
block writers and writers never block readers in Postgres (they only
ever conflict with each other) — each transaction just sees the row
versions visible as of its own snapshot.

The cost: dead row versions accumulate and need `VACUUM` to reclaim
the space — this is the direct, unavoidable consequence of MVCC, not
an unrelated maintenance chore.

## 9. Two-Phase Commit

Unlike 2PC-as-a-diagram, Postgres has **real, built-in support**:
```sql
BEGIN;
UPDATE accounts SET balance = balance - 100 WHERE id = 'A';
PREPARE TRANSACTION 'transfer_772';   -- phase 1: prepared, durable, not yet visible to others
-- ... coordinator confirms all participants prepared ...
COMMIT PREPARED 'transfer_772';       -- phase 2: actually commits
-- (or ROLLBACK PREPARED 'transfer_772' if any participant failed to prepare)
```
Requires `max_prepared_transactions > 0` in `postgresql.conf` (0 by
default — 2PC is opt-in). This repo's actual systems avoid 2PC in
favor of SAGA (`amazon-order-management-system.md`'s checkout) because
2PC's coordinator is a single point of blocking failure — if it dies
between phases, every participant sits holding locks indefinitely.

## 10. Three-Phase Commit

The textbook fix for 2PC's blocking problem — adds a "pre-commit" phase
so participants can independently decide to commit if the coordinator
disappears. **No mainstream database implements it**, Postgres
included, because 3PC's non-blocking guarantee only holds under a
synchronous network with a known message-delay bound — an assumption
that doesn't hold on the real internet. It's worth knowing why it's
theoretical, not worth expecting to write.

## 11. Indexing Strategy

- **B-tree** (default) — equality and range queries, the right default
  for almost everything, including the `geohash` prefix-range trick in
  `proximity-servicebase.md`.
- **Partial index** — `CREATE INDEX ... WHERE status = 'HELD'`, used in
  `movie-ticket-booking.md` for `seat_holds` — smaller, faster, and
  only indexes the rows actually queried by that predicate.
- **GIN** — inverted index for `jsonb`, arrays, full-text search.
- **GiST** — geometric/range types; the PostGIS extension builds on
  this for real geospatial queries (an alternative to the geohash
  column approach for a system that needs true polygon/radius queries,
  not just bounding-box approximation).

## 12. Advisory Locks

A Postgres-specific mechanism for locking something that **isn't a
row** — coordinating access to a resource with no natural table to
attach a lock to (e.g. "only one instance of this batch job should run
right now"):
```sql
SELECT pg_try_advisory_lock(12345);   -- non-blocking, returns true/false
-- ... do the exclusive work ...
SELECT pg_advisory_unlock(12345);
```
An alternative to `unique-id-generator.md`'s `INSERT ... ON CONFLICT DO
NOTHING` worker-registry approach for the same class of problem —
advisory locks don't need a table at all, but they also don't leave
an audit trail the way a registry row does.
