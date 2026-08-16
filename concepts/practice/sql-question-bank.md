---
concept_name: SQL Question Bank (Practice)
linked_systems: [Amazon Order Managment System, Movie Ticket Booking, Digital Wallet, Rate Limiter, Google Drive]
last_reviewed: 2026-08-16
freshness: Fresh
notion_url: TBD
---

# SQL Question Bank

Engine: **PostgreSQL**. Progress persists as checkboxes below — resuming
`/practice sql` finds the first `[ ]` in document order. Guide:
`concepts/practice/sql-guide.md`.

## Concept 1: Schema Design Methodology
_guide: sql-guide.md#1-schema-design-methodology--keys-follow-queries_

### Q1 [core] — Likes: membership vs. count — [ ] not yet attempted
**Scenario:** A post needs two answers: "did *this* user like it" (must
be exact) and "how many total likes" (displayed to everyone, doesn't
need to be exact). A naive design uses one `likes` table and runs
`COUNT(*)` on every page load.
**Question:** What's wrong with the naive design at scale, and what
schema (tables/structures, not necessarily SQL-only) would you use
instead? Name which query drove each piece of your answer.

<details><summary>Model answer</summary>

`COUNT(*)` over a `likes` table means every single page view that
displays a like count pays for a full scan (or at best an index scan)
over every liker, even though the vast majority of viewers only care
about an approximate number. The membership check ("did I like this")
and the count ("how many") are different queries with different
freshness requirements, so they shouldn't share one code path.

`like-and-comment-service.md`'s actual answer: a membership set (Redis
`SADD`/`SISMEMBER` in that system's case, but the *relational* version
is a `likes(post_id, user_id)` table with a unique constraint on
`(post_id, user_id)` for the exact per-user check) plus a **separate,
cached** `like_count` column on the post row, incremented alongside the
insert rather than derived from `COUNT(*)` on read. The count can drift
slightly under extreme concurrency and gets reconciled periodically —
acceptable because nobody reads it expecting exactness.
</details>

### Q2 [core] — Chat inbox, one table or two? — [ ] not yet attempted
**Scenario:** A junior engineer proposes one table,
`messages(conversation_id, message_id, sender_id, content)`, and plans
to build "my conversation list, most recent activity first" by joining
`messages` against a `conversations` table and sorting in the
application.
**Question:** What breaks about this as message volume grows, and what
schema change fixes it?

<details><summary>Model answer</summary>

`messages` is correctly keyed for "a conversation's messages" (query by
`conversation_id`). But "my conversations, most recent first" is a
completely different access pattern — by `user_id`, sorted by
recency — and no index on `messages` serves that without scanning
every message the user's conversations have ever contained.

`chat-systems.md`'s fix: a **second** table,
`conversations_by_user(user_id, last_activity_at, conversation_id,
last_message_preview)`, denormalized specifically for the inbox query,
updated alongside every new message. Two tables, two queries, two
purposes — trying to serve both from one table means picking a key
that's wrong for one of them.
</details>

## Concept 2: Pessimistic Locking
_guide: sql-guide.md#2-pessimistic-locking_

### Q1 [core] — Last appointment slot — [ ] not yet attempted
**Scenario:** Two receptionists' systems both attempt to book the same
doctor's last open slot within milliseconds of each other.
**Question:** Would a plain `UPDATE slots SET status='BOOKED' WHERE
slot_id=? AND status='AVAILABLE'` be sufficient here, or do you need
`SELECT ... FOR UPDATE`? Justify your answer with the actual mechanism,
not just "to be safe."

<details><summary>Model answer</summary>

The plain atomic `UPDATE ... WHERE status = 'AVAILABLE'` is actually
**sufficient** — this is a single-statement conditional update
(Concept 5), and Postgres takes the row lock internally for the
duration of that one statement, closing the race without any explicit
`FOR UPDATE`. Only the first `UPDATE` to reach the row will see
`status = 'AVAILABLE'`; the second sees `BOOKED` and affects 0 rows.

`FOR UPDATE` earns its place when you need to lock a row **across
multiple statements** in one transaction — e.g. read the slot, check
some other condition in application code, *then* update — because a
bare `UPDATE ... WHERE` can't hold a lock open for logic that happens
in between. `movie-ticket-booking.md`'s actual booking flow doesn't use
`FOR UPDATE` for exactly this reason — it uses a Redis lock instead,
because the "gap" it needs to hold open spans multiple *requests*
(minutes of checkout time), which no SQL transaction should ever do.
</details>

### Q2 [core] — What is FOR SHARE actually for? — [ ] not yet attempted
**Scenario:** Before inserting a `booking_seats` row referencing a
`showtime_id`, you want to guarantee the showtime hasn't been cancelled
by a concurrent admin action — but you don't want to block other
customers who are simultaneously just *reading* that showtime's
details.
**Question:** Which lock mode fits, and why not plain `FOR UPDATE`?

<details><summary>Model answer</summary>

`SELECT status FROM showtimes WHERE showtime_id = ? FOR SHARE` — this
takes a shared lock that prevents the row from being *updated*
(blocking a concurrent cancellation) while still allowing any number of
other `FOR SHARE` or plain reads to proceed unblocked. `FOR UPDATE`
would work too, but it's needlessly exclusive: it would also block
other transactions that only want to check the same thing (another
customer's booking flow doing the identical pre-insert check), which
`FOR SHARE` correctly allows since none of them are trying to *change*
the row.
</details>

## Concept 3: Optimistic Locking
_guide: sql-guide.md#3-optimistic-locking_

### Q1 [core] — Two-tab profile edit — [ ] not yet attempted
**Scenario:** A user has their profile open in two browser tabs, edits
their bio in both, and submits both within a second of each other.
**Question:** Write the optimistic-locking `UPDATE`, and specify
exactly what the client/server should do when the second submission's
`UPDATE` affects 0 rows.

<details><summary>Model answer</summary>
```sql
UPDATE user_profiles SET bio = ?, version = version + 1
WHERE user_id = ? AND version = ?;   -- version = the value the client last read
```
0 rows affected means someone else (in this case, the user's own other
tab) already updated the row since this client last read it — the
`version` it's holding is stale. The correct handling is **not** to
silently retry with a blind overwrite (that would just race again, or
worse, silently discard the other tab's save) — the server should
return a 409 Conflict, the client re-fetches the current row (including
the new `version`), and either auto-merges if possible or shows the
user both versions to reconcile, the same "don't silently pick a
winner" principle `google-drive.md` uses for sync conflicts.
</details>

### Q2 [core] — When optimistic locking is the wrong call — [ ] not yet attempted
**Scenario:** A wallet service uses optimistic locking (`version`
column) instead of `FOR UPDATE` for balance transfers on a heavily
traded account.
**Question:** Describe concretely how this goes worse than pessimistic
locking under high contention.

<details><summary>Model answer</summary>

Under high contention (many concurrent transfers touching the same hot
account), optimistic locking means most attempts read a `version`,
do work, then discover on `UPDATE` that they lost the race — and have
to retry from scratch, re-reading and re-validating. As contention
rises, the retry rate rises too, and you can hit a point where
transactions spend more work retrying than succeeding — effectively
livelock, where throughput on that hot account collapses even though
no single transaction is technically stuck. `FOR UPDATE` avoids this by
serializing contenders into a queue instead of a retry storm — each one
waits its turn and succeeds on the first real attempt, at the cost of
blocking rather than racing. This is exactly why `digital-wallet.md`
picked `FOR UPDATE`, not optimistic locking, for transfers.
</details>

## Concept 4: Deadlock Avoidance & Detection
_guide: sql-guide.md#4-deadlock-avoidance--detection_

### Q1 [core] — Construct the deadlock — [ ] not yet attempted
**Scenario:** Transaction 1 transfers Aisha→Ben and locks Aisha's row
first (as "the sender"). Transaction 2 transfers Ben→Aisha at the same
moment and locks Ben's row first (as *its* "sender").
**Question:** Walk through exactly how this deadlocks, then fix it.

<details><summary>Model answer</summary>

T1 locks Aisha's row, then tries to lock Ben's row — but T2 already
holds it (T2 locked Ben's row first, as its sender). T2 now tries to
lock Aisha's row — held by T1. Both transactions are now waiting on a
lock the other holds; neither can proceed. Postgres's deadlock detector
fires after `deadlock_timeout` and aborts one with `40P01`.

Fix: lock in a fixed order regardless of sender/receiver —
```sql
SELECT * FROM accounts WHERE account_id = LEAST('aisha','ben') FOR UPDATE;
SELECT * FROM accounts WHERE account_id = GREATEST('aisha','ben') FOR UPDATE;
```
Now both T1 and T2 request Aisha's lock first, every time — one simply
waits for the other to finish, no cycle ever forms.
</details>

### Q2 [core] — Handling 40P01 in application code — [ ] not yet attempted
**Scenario:** Even with correct lock ordering elsewhere in the codebase,
a rare deadlock still occurs (perhaps from a code path someone forgot
to order correctly).
**Question:** What should the application layer actually do when a
query returns SQLSTATE `40P01`?

<details><summary>Model answer</summary>

Treat it as a transient, retryable error — the aborted transaction did
*not* commit any of its work (Postgres guarantees this), so it's safe
to retry the entire transaction from the beginning after a short random
backoff (jittered, so two retrying transactions don't immediately
re-collide). This should be caught specifically by SQLSTATE, not by a
generic "any error, retry" handler, since most other errors (a
constraint violation, a syntax error) are not safely retryable — retrying
those would just fail again or, worse, retry something that
partially succeeded for a different reason.
</details>

## Concept 5: Atomic Conditional Updates
_guide: sql-guide.md#5-atomic-conditional-updates-lock-free_

### Q1 [core] — Token bucket in pure Postgres — [ ] not yet attempted
**Scenario:** You need `rate-limiter.md`'s token bucket check, but
without Redis — pure Postgres, one row per identity.
**Question:** Write the atomic decrement, and explain the specific race
a naive `SELECT tokens ...` then `UPDATE ... SET tokens = tokens - 1`
would have under concurrency.

<details><summary>Model answer</summary>
```sql
UPDATE token_buckets SET tokens = tokens - 1
WHERE identity = ? AND tokens >= 1;
-- 0 rows affected = denied
```
The naive two-step version reads `tokens = 1`, decides "allowed," then
writes `tokens - 1` — but if two concurrent requests both read `tokens
= 1` before either writes, both decide "allowed" and both write
`tokens = 0`, letting two requests through against a budget of one.
The single-statement version has no such gap: the `WHERE tokens >= 1`
check and the decrement happen as one atomic operation against
whatever the row's *current* value actually is at that instant, so a
second concurrent request sees the already-decremented value and
correctly gets 0 rows.
</details>

### Q2 [core] — Where atomic UPDATE stops being enough — [ ] not yet attempted
**Scenario:** You try to apply the same atomic-`UPDATE` technique to
`movie-ticket-booking.md`'s "hold this seat while the user enters
payment details" problem.
**Question:** Why doesn't a single atomic `UPDATE` solve this the way
it solves inventory decrement?

<details><summary>Model answer</summary>

Inventory decrement is a single statement, single request, single
moment in time — atomicity within one `UPDATE` is exactly what it
needs. The seat hold problem is different in kind: the "hold" has to
survive across the user's think-time, which spans **multiple separate
HTTP requests** (view seat map → hold → enter payment → confirm),
possibly minutes apart. A SQL statement's atomicity only covers the
instant it executes — there's no SQL mechanism for "keep this row
provisionally reserved across several unrelated future requests"
without holding a transaction open the entire time, which is a
connection-pool-exhausting anti-pattern. That's precisely why
`movie-ticket-booking.md` reaches for an external, TTL-based Redis lock
instead — a fundamentally different tool for a fundamentally different
shape of problem (duration-spanning-requests, not
atomicity-within-one-statement).
</details>

## Concept 6: Unique Constraints & Idempotency
_guide: sql-guide.md#6-unique-constraints--idempotency-upsert_

### Q1 [core] — Retried payment call — [ ] not yet attempted
**Scenario:** A client calls `POST /charges` with `idempotencyKey:
"idk-8f21"`, the network times out before the response arrives, and the
client retries with the same key.
**Question:** Design the `INSERT` and the retry-detection logic so the
second call returns the *original* transaction instead of erroring or
double-charging.

<details><summary>Model answer</summary>
```sql
INSERT INTO transactions (transaction_id, idempotency_key, amount, status)
VALUES (?, 'idk-8f21', 89.00, 'PENDING')
ON CONFLICT (idempotency_key) DO NOTHING
RETURNING transaction_id;
```
If this `RETURNING` clause comes back empty, the insert was skipped —
meaning a row with this key already exists — so the application should
immediately `SELECT * FROM transactions WHERE idempotency_key =
'idk-8f21'` and return *that* row's current status to the caller,
rather than treating the conflict as an error. This is
`payment-gateway.md`'s exact mechanism: the unique constraint is the
detector, and the fallback read is what makes the retry idempotent from
the caller's point of view, not just safe at the database level.
</details>

### Q2 [core] — DO NOTHING vs. DO UPDATE — [ ] not yet attempted
**Scenario:** Compare two real upserts from this repo: idempotency-key
insertion, and chunk reference counting.
**Question:** Explain why one uses `ON CONFLICT DO NOTHING` and the
other uses `ON CONFLICT DO UPDATE`, in terms of what "conflict" means
in each case.

<details><summary>Model answer</summary>

`amazon-order-management-system.md`'s idempotency key insert uses `DO
NOTHING` because a conflict there means "this exact request already
happened" — there's nothing to update, the existing row is already
correct, and the application's job is just to detect the conflict and
short-circuit.

`google-drive.md`'s chunk table uses `DO UPDATE SET ref_count =
chunks.ref_count + 1` because a conflict there means "this chunk's
content already exists, but a *new* file version now also references
it" — the existing row isn't already correct for the new situation, it
needs to change (its reference count needs to reflect one more owner).
The distinguishing question: does a conflict mean "nothing changed, I
can ignore this" or "something changed and the existing row needs to
reflect it"?
</details>

## Concept 7: Isolation Levels
_guide: sql-guide.md#7-isolation-levels_

### Q1 [core] — Read Committed vs. Repeatable Read — [ ] not yet attempted
**Scenario:** Transaction A runs `SELECT balance FROM accounts WHERE
id=1` twice, five seconds apart, with no writes of its own in between.
Transaction B updates that same row and commits in between A's two
reads.
**Question:** Under Read Committed, what does A's second `SELECT`
return? Under Repeatable Read, what does it return? Explain the
difference using what each level actually promises.

<details><summary>Model answer</summary>

**Read Committed** (the default): A's second `SELECT` sees B's
committed change — each statement gets its own fresh snapshot as of
when *that statement* starts, and B committed before A's second
statement began. This is a legitimate non-repeatable read.

**Repeatable Read**: A's second `SELECT` returns the **same** value as
its first — the whole transaction locked onto one snapshot at its
first statement, and B's later commit is simply invisible to A for the
rest of A's transaction, no matter how long A stays open.
</details>

### Q2 [core] — Serializable abort with no shared row — [ ] not yet attempted
**Scenario:** Two Serializable transactions never touch the same row —
one reads `SUM(amount) FROM ledger_entries WHERE account='A'` and
inserts a new entry if the sum exceeds a threshold; the other does the
same independently for a *different* threshold check, but both are
reading overlapping ranges of the same table and both insert.
**Question:** Can Postgres still abort one of them under Serializable,
even with zero row-level conflicts? Why?

<details><summary>Model answer</summary>

Yes — this is exactly what SSI (Serializable Snapshot Isolation)
exists for. Row-level locking wouldn't catch this, because neither
transaction updates a row the other read. But SSI tracks *predicate*
dependencies: both transactions read a range of `ledger_entries` that
the other's insert falls within, forming a read-write dependency in
both directions. If committing both together could never correspond to
some valid serial (one-after-the-other) execution, Postgres detects
the dependency cycle and aborts one with `could not serialize access
due to read/write dependencies among transactions` — a guarantee
regular locking literally cannot provide, since locking only protects
against conflicts on rows actually touched, not rows that logically
should have been considered.
</details>

## Concept 8: MVCC
_guide: sql-guide.md#8-mvcc-multi-version-concurrency-control_

### Q1 [core] — Long transaction, table bloat — [ ] not yet attempted
**Scenario:** A reporting job opens a transaction and holds it open for
two hours while it slowly reads a heavily-updated `orders` table. The
DBA notices the table's on-disk size growing far faster than the row
count.
**Question:** Explain the connection between the long-running read
transaction and the bloat, using `xmin`/`xmax` and `VACUUM`.

<details><summary>Model answer</summary>

Postgres never overwrites a row in place — an `UPDATE` inserts a new
row version (new `xmin`) and marks the old version's `xmax` as
deleted-by-this-transaction. Old versions are only reclaimable by
`VACUUM` once no transaction could possibly still need to see them —
and the long-running reporting transaction's snapshot was taken hours
ago, so *every* row version created or superseded since it began must
be kept around in case that reporting transaction reads it. The bloat
isn't a bug — it's MVCC correctly preserving history that a
still-open, old transaction might still need, and it can't be cleaned
up until that transaction finally commits or aborts.
</details>

### Q2 [core] — "Why don't I see the commit?" — [ ] not yet attempted
**Scenario:** A developer opens a `REPEATABLE READ` transaction, runs
one query, then — confused — runs another `SELECT` on the same table
five minutes later after confirming (in a totally separate psql
session) that a row was updated and committed. Their second `SELECT`
still shows the old value.
**Question:** Is this a bug? Explain what's actually happening.

<details><summary>Model answer</summary>

Not a bug — this is Repeatable Read working exactly as specified. The
transaction's snapshot was fixed at its first statement; every
subsequent `SELECT` within that same transaction sees that same
snapshot, regardless of what commits elsewhere in the meantime and
regardless of how much wall-clock time passes. The developer's
confusion usually resolves once they realize the fix isn't "wait
longer" — it's ending the transaction (`COMMIT`/`ROLLBACK`) and
starting a new one, which takes a fresh snapshot that will include the
now-committed change.
</details>

## Concept 9: Two-Phase Commit
_guide: sql-guide.md#9-two-phase-commit_

### Q1 [core] — Coordinator crash mid-2PC — [ ] not yet attempted
**Scenario:** Three participants all successfully run `PREPARE
TRANSACTION`. The coordinator then crashes before sending `COMMIT
PREPARED` to any of them.
**Question:** What state are the participants in, and what has to
happen to recover?

<details><summary>Model answer</summary>

Each participant's prepared transaction is durable (survives even a
Postgres restart) but **still holds all its locks** and is invisible
to other transactions — it's neither committed nor rolled back, just
frozen in a "ready" state waiting for a decision. This is the literal
meaning of "2PC blocks on coordinator failure": the participants
cannot unilaterally decide to commit or abort, because they don't know
whether the *other* participants also successfully prepared — only the
coordinator knew that. Recovery requires either the coordinator
restarting and consulting its own durable log of what it had decided
(if it logged the decision before crashing), or manual operator
intervention inspecting `pg_prepared_xacts` on each participant and
deciding to `COMMIT PREPARED` or `ROLLBACK PREPARED` based on
out-of-band knowledge of what the other participants did.
</details>

### Q2 [core] — Why this repo avoids 2PC — [ ] not yet attempted
**Scenario:** Postgres genuinely supports 2PC, yet
`amazon-order-management-system.md` deliberately uses a SAGA across
Order/Inventory/Payment instead.
**Question:** Give the concrete failure mode SAGA avoids that 2PC
would suffer from in that architecture.

<details><summary>Model answer</summary>

Order, Inventory, and Payment are **three separate services with three
separate databases** — 2PC would require all three to participate in
one distributed transaction, meaning Inventory's row lock on a
just-reserved item stays held for the entire duration of the Payment
Service's call to an *external* card processor, which can take seconds
and is outside anyone's control. A single slow or hung payment call
would hold Inventory's lock that whole time, blocking every other
customer trying to buy that same item — the coordinator-blocking
problem from Q1, except the "blocking operation" is a third-party
network call, not a crash. SAGA sidesteps this entirely: each service
commits its own local transaction immediately (reserve inventory,
commit; create payment intent, commit), and if a later step fails, a
compensating action (release the reservation) undoes the earlier one —
no lock is ever held across a service boundary or a slow external call.
</details>

## Concept 10: Three-Phase Commit
_guide: sql-guide.md#10-three-phase-commit_

### Q1 [core] — What the extra phase buys you (in theory) — [ ] not yet attempted
**Scenario:** A colleague asks why 3PC exists if 2PC already works "most
of the time."
**Question:** Explain what the added "pre-commit" phase is supposed to
solve, and precisely which assumption makes that guarantee fall apart
in practice.

<details><summary>Model answer</summary>

3PC adds a phase between "prepared" and "commit" specifically so that
if the coordinator dies, a participant can look at whether it received
the pre-commit message and independently infer what the *rest* of the
cluster likely decided, without needing to ask the coordinator — this
is meant to make it non-blocking, unlike 2PC's participants who are
stuck without the coordinator. The catch: this inference is only valid
if the network is synchronous with a known upper bound on message
delay — a participant that hasn't heard from the coordinator needs to
be able to conclude "the coordinator must be dead, not just slow,"
which requires knowing a message *couldn't* still be in flight. Real
networks (the internet, or even a data center under load) can't
guarantee that bound, so a participant genuinely cannot distinguish "the
coordinator is dead" from "the coordinator (or the network) is just
slow" — and proceeding on a wrong guess can violate the very
consistency 3PC was supposed to protect.
</details>

### Q2 [discussion] — Why no mainstream database ships it — [ ] not yet attempted
**Scenario:** Given 3PC "solves" 2PC's blocking problem on paper, ask
yourself why Postgres, MySQL, and every major cloud database still
ship only 2PC (if that) and not 3PC.
**Question:** Argue the actual engineering trade-off.

<details><summary>Model answer</summary>

3PC trades a real, well-understood cost (2PC's blocking window, which
is rare and bounded by coordinator recovery time) for a theoretical
gain that depends on a network assumption nobody can actually
guarantee — and when that assumption is violated, 3PC doesn't just
degrade gracefully back to 2PC's behavior, it can produce genuine
inconsistency (different participants independently — and wrongly —
concluding different outcomes). Given that, most real systems decided
it's better to accept 2PC's known, bounded blocking risk (or better
yet, avoid distributed transactions across service boundaries entirely
via SAGA, per Concept 9 Q2) than to add complexity that provides a
theoretical guarantee real networks can't actually back.
</details>

## Concept 11: Indexing Strategy
_guide: sql-guide.md#11-indexing-strategy_

### Q1 [core] — Index for expiring holds — [ ] not yet attempted
**Scenario:** `hotel-reservation-system.md`'s reconciler needs to find
every `room_night_holds` row that's still `HELD` and past its
`expires_at`, running this query every few seconds against a table
where the overwhelming majority of rows are `CONFIRMED` or `EXPIRED`,
not `HELD`.
**Question:** What index would you create, and why does a **partial**
index specifically help here versus a plain index on `(status,
expires_at)`?

<details><summary>Model answer</summary>
```sql
CREATE INDEX idx_holds_expiring ON room_night_holds (expires_at)
WHERE status = 'HELD';
```
A plain index on `(status, expires_at)` still has to include an entry
for *every* row in the table, including the large majority that are
`CONFIRMED`/`EXPIRED` and will never match this query — wasted index
size and wasted maintenance cost on every write to those rows. A
**partial** index only contains entries for rows where `status =
'HELD'` at index-maintenance time, which is exactly the tiny, actively
relevant subset the reconciler cares about — smaller index, faster
scans, and no wasted upkeep from rows that could never satisfy the
`WHERE` clause anyway.
</details>

### Q2 [core] — Indexing a JSONB field — [ ] not yet attempted
**Scenario:** A `videos` table stores metadata as `jsonb`, and queries
frequently filter on `metadata ->> 'language' = 'en'`.
**Question:** Would a GIN index on the whole `metadata` column be the
right choice, or something else? Justify it against this specific
query pattern.

<details><summary>Model answer</summary>

A GIN index on the whole column is built for containment/existence
queries (`metadata @> '{"language": "en"}'` or `metadata ? 'language'`)
across arbitrary keys — it's powerful but heavier to build and
maintain than needed if you only ever query *one specific* field.
Since the actual pattern is a single, known field compared for
equality, an **expression index** on just that extracted value is the
better fit:
```sql
CREATE INDEX idx_videos_language ON videos ((metadata ->> 'language'));
```
This is a plain B-tree over the extracted text, cheaper to maintain
than a full GIN index, and directly matches the equality predicate
actually being run — reach for GIN when the query pattern genuinely
needs to search across unpredictable keys/containment, not by default
just because the column is JSONB.
</details>

## Concept 12: Advisory Locks
_guide: sql-guide.md#12-advisory-locks_

### Q1 [core] — Singleton cron job — [ ] not yet attempted
**Scenario:** A nightly reconciliation job runs on every instance of a
horizontally-scaled service, but it must only actually execute once
per night.
**Question:** Design this with `pg_try_advisory_lock`, and explain what
happens to the lock if the instance holding it crashes mid-job.

<details><summary>Model answer</summary>
```sql
SELECT pg_try_advisory_lock(hashtext('nightly_reconciliation'));
-- if true: this instance runs the job, then calls pg_advisory_unlock at the end
-- if false: another instance already has it; skip silently
```
Advisory locks are **session-scoped** — tied to the database
connection that acquired them, not to a row or a transaction. If the
holding instance crashes, its database connection drops, and Postgres
automatically releases every advisory lock that session held — no
stuck lock, no manual cleanup needed, unlike a TTL-based lock that
would need to wait out its expiry. This is one of the real advantages
advisory locks have over the Redis-style TTL lock pattern used
elsewhere in this repo: the "owner died" case resolves immediately
instead of after a timeout window.
</details>

### Q2 [core] — Advisory lock vs. registry row — [ ] not yet attempted
**Scenario:** Compare `pg_advisory_lock` against
`unique-id-generator.md`'s `INSERT ... ON CONFLICT DO NOTHING`
worker-ID registry — both solve "only one of these should happen."
**Question:** When would you actually prefer the registry-row approach
over an advisory lock?

<details><summary>Model answer</summary>

Advisory locks are ephemeral and leave no trace once released — great
for "make sure only one runs right now," bad for anything that needs
an **audit trail** (who got worker ID 7, and when) or needs the
assignment to be **queryable** later (`SELECT * FROM
worker_id_registry` to see current allocations, entirely impossible
with an advisory lock, which has no listing/inspection query beyond
`pg_locks`). Prefer the registry row when the *assignment itself* is
meaningful data you'll want to query or audit later, not just a
transient mutual-exclusion signal; prefer the advisory lock when all
you need is "don't let two of these run at once" and the fact that it
ran needs no lasting record.
</details>
