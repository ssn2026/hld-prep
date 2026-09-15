---
concept_name: Locking (Optimistic, Pessimistic, Distributed)
linked_systems: [Amazon Order Managment System, Hotel ReservationSyste, Movie Ticket Booking, Digital Wallet, Flight Ticket Booking, Doctor Appointment]
last_reviewed: 2026-09-15
freshness: Fresh
notion_url: TBD
---

# Locking — Optimistic, Pessimistic, and Distributed

## The question this answers

"Two requests race to touch the same piece of state — how do I stop them
from corrupting it, and of the three main mechanisms (optimistic,
pessimistic, distributed), which one fits which scenario?"

This note is a synthesis, not new material invented from scratch — it
pulls together locking content already scattered across
[[sql-guide]] (`concepts/practice/sql-guide.md` §2–5),
[[redis-guide]] (`concepts/practice/redis-guide.md` §1), your own
`My Own System Design/Amazon/01 - Inventory Service` and
`02 - Order Service` files, and this repo's
[[amazon-order-management-system]], [[hotel-reservation-system]], and
`movie-ticket-booking.md`. If a section here feels familiar, that's
intentional — the point is to put all three mechanisms side by side with
a decision framework, which no single existing file does.

**A note on "cart service":** this repo (and your own `My Own System
Design/Amazon/` set) doesn't have a standalone Cart Service file — your
Inventory Service doc and this repo's Order Service both fold cart
checkout into "reserve inventory for these line items," so that's the
scenario used below wherever a cart-shaped example is needed. If you do
have a separate cart design elsewhere, point me at it and I'll fold in
its actual locking choice instead of the constructed example.

---

## The core problem: the read-modify-write gap

Every locking strategy exists to close the same gap:

```
1. READ  current value
2. THINK (decide what the new value should be)
3. WRITE new value
```

If two requests both execute step 1 before either reaches step 3, both
"think" from the same stale snapshot, and the second write silently
clobbers or double-counts against the first. Your own Inventory Service
doc states this precisely (§5, Invariant 1):

> "Imagine `available = 1`. Two requests both read `1`. Both applications
> conclude: 'There is enough inventory.' If they then independently
> subtract one, we could end up at `-1`."

The three mechanisms below are three different answers to *when* and
*how* you close that gap — before the read (pessimistic), at the write
(optimistic), or across a boundary wider than one database transaction
(distributed).

---

## 1. Pessimistic Locking

### Mechanism

Acquire the lock **before** you even read the value, and hold it until
you commit. Nobody else can read-for-update or write the row while you
hold it.

```sql
BEGIN;
SELECT available_qty FROM inventory WHERE product_id = ? FOR UPDATE;
-- row is now locked; every other FOR UPDATE/FOR SHARE on this row blocks
-- ... check quantity, decide, ...
UPDATE inventory SET available_qty = available_qty - ? WHERE product_id = ?;
COMMIT;  -- lock released
```

Postgres actually has four row-lock strengths, not just one blunt
instrument (from [[sql-guide]] §2):

| Mode | Blocks |
|---|---|
| `FOR UPDATE` | any other `FOR UPDATE`/`FOR SHARE` on the same row |
| `FOR NO KEY UPDATE` | same, but permits concurrent `FOR KEY SHARE` (used internally by FK checks) |
| `FOR SHARE` | other `FOR UPDATE`, but not other `FOR SHARE` |
| `FOR KEY SHARE` | only blocks changes to the row's key columns |

### Example — Inventory Service, the alternative you considered and rejected

Your own `01 - Inventory Service - Principal HLD.md` (§9) writes out
pessimistic locking as the *alternative* to the atomic conditional update
it actually picks:

```text
BEGIN
SELECT inventory FOR UPDATE
check quantity
update quantity
COMMIT
```

and names the trade-off correctly:

> "Advantage: The behavior is straightforward to reason about.
> Disadvantage: For a hot product, many transactions may wait for the
> same row."

That's the whole story of pessimistic locking in one sentence: **easy to
reason about, expensive under contention.**

### Example — Digital Wallet's deadlock-avoidance ordering

Pessimistic locking's other cost is deadlock. `digital-wallet.md`'s
transfer locks *two* accounts (sender + receiver) with `FOR UPDATE`, and
if transfer A locks account 1 then 2 while transfer B (moving money the
other direction) locks account 2 then 1, both wait forever. The fix isn't
a smarter lock — it's a fixed acquisition order:

> lock accounts by `account_id` ascending, never by "sender first" — this
> is what makes two transfers moving money in opposite directions between
> the same pair of accounts unable to deadlock.

This is the general pessimistic-locking rule: **whenever you take more
than one lock, always take them in the same global order**, regardless of
which one is "logically first" for that particular request. Postgres's
deadlock detector (`deadlock_timeout`, default 1s, checks the wait-for
graph for a cycle) is a backstop for when ordering fails, not a
substitute for it — every deadlock it catches is still a wasted,
user-visible transaction abort.

### When to pick pessimistic

- **Contention is expected to be high**, not rare — the "hope for the
  best, retry on conflict" cost of optimistic locking would itself
  become the bottleneck (constant retry storms).
- **The critical section is short and entirely inside one database
  transaction.** Digital Wallet's transfer is a handful of statements
  that complete in milliseconds — holding a row lock for that long is
  cheap.
- **You need multiple statements to stay consistent with each other**
  inside the lock (read, branch on business logic, conditionally do one
  of several different writes) — optimistic locking's single
  conditional `UPDATE` can't express that.

### When NOT to — the reason it's not the default in this repo

Every booking system here (Movie Ticket Booking, Hotel Reservation,
Flight Ticket Booking, Doctor Appointment) explicitly **rejects**
`FOR UPDATE` for holds, for the same reason `movie-ticket-booking.md`
states directly:

> "The hold has to survive across the user's think-time entering payment
> details — that can be minutes, spanning multiple HTTP requests. A
> `SELECT ... FOR UPDATE` transaction can't reasonably stay open that
> long (connection pool exhaustion, and it'd block every other seat
> operation on that row's page)."

**Rule of thumb: pessimistic locking is for locks that live inside one
request; anything spanning user think-time needs a different tool**
(distributed lock or durable reservation state — see §3).

---

## 2. Optimistic Locking

### Mechanism

Don't lock anything up front. Read freely, decide what you want to
write, then make the write **conditional** on nothing having changed
since your read. If the condition fails, someone else won the race —
retry or fail cleanly, no blocking.

Two flavors show up across your designs, and it's worth being precise
about the difference:

**2a. Version-column optimistic locking** — an explicit `version` integer,
bumped on every update, checked in the `WHERE`:

```sql
UPDATE orders SET status = 'CONFIRMED', version = version + 1
WHERE order_id = ? AND version = ?;
-- 0 rows affected = someone else updated it first (or the version you
-- read is stale) — caller re-reads and retries
```

**2b. Atomic conditional update** — the check *is* the business invariant
itself, fused into one statement, no separate version column needed at
all:

```sql
UPDATE inventory SET available_qty = available_qty - ?
WHERE product_id = ? AND available_qty >= ?;
-- 0 rows affected = insufficient stock, full stop — the invariant IS the version check
```

2b is the leaner form: when the field you're protecting *is itself* a
sufficient conflict check (does this row still have enough stock?), you
don't need a separate `version` counter — the domain data does that job
for free. You reach for 2a (an explicit version) when the write doesn't
have a natural "still valid?" predicate of its own — e.g. a state
transition where many different old states would make the transition
invalid, not just one numeric threshold.

### Example — your own Inventory Service, both flavors in one file

Your `01 - Inventory Service - Principal HLD.md` (§9) uses exactly the
2b pattern as its **primary decision**, not the alternative:

```sql
UPDATE inventory
SET available_quantity = available_quantity - :quantity,
    reserved_quantity = reserved_quantity + :quantity
WHERE inventory_id = :inventoryId
  AND available_quantity >= :quantity;
```

> "`1 row` → reservation succeeded. `0 rows` → insufficient inventory or
> the record changed... If version-based optimistic concurrency is also
> required, add a version condition." — that last sentence is exactly
> the 2a/2b distinction above: version is an *optional extra*, not
> required, because the quantity check already closes the race.

### Example — your own Order Service, the version-column flavor

Your `02 - Order Service - Principal HLD.md` (§11) reaches for 2a because
order state has no single numeric invariant to check — many different
"wrong" prior states could make a transition invalid:

```sql
UPDATE orders
SET status = :newStatus,
    version = version + 1
WHERE order_id = :orderId
  AND status = :expectedStatus
  AND version = :version;
```

> "If zero rows are updated, another actor already changed the order...
> It prevents a stale event from overwriting a newer state."

This repo's `amazon-order-management-system.md` reuses the identical
shape for the Kafka consumer side, and states the useful reframe that
**the state check doubles as the idempotency check** — no separate
"have I seen this event before" table needed:

```sql
UPDATE orders SET status = 'CONFIRMED', updated_at = now()
WHERE order_id = ? AND status = 'PENDING_PAYMENT';   -- re-delivery: 0 rows, harmless
```

### Example — cart-shaped scenario

Applying the same 2b pattern to the "cart" case your own Inventory
Service folds checkout into: reserving N units for a cart line at
add-to-cart time (rather than waiting until full checkout) is the exact
same one-statement shape —

```sql
UPDATE inventory SET available_qty = available_qty - :qty,
                      reserved_qty  = reserved_qty  + :qty
WHERE product_id = :productId AND available_qty >= :qty;
```

— no cart-specific lock exists or is needed; the cart's "can I add this
many?" question and the inventory's concurrency protection are the same
atomic statement. This is worth noticing as a general principle: **a
"cart" or "hold" concept doesn't need its own locking primitive if it's
just borrowing the underlying resource's own atomic check.**

### The two race conditions your Inventory Service names, resolved by optimistic locking

Your `01 - Inventory Service` file's §6 ("Important Race: Confirm vs
Expire") and this repo's Order Service equivalent both describe races
that *look* like they need a lock, but are actually resolved by 2a's
conditional `WHERE`:

> "Suppose a reservation reaches its expiry time at the same moment that
> an order tries to confirm it. We cannot allow both operations to
> succeed... Only one should win."

No lock is taken anywhere in this flow. Both the confirm path and the
expiry-reaper path issue the same shape of statement:

```sql
-- Confirm:
UPDATE reservations SET status = 'CONFIRMED' WHERE reservation_id = ? AND status = 'RESERVED';
-- Expire (reaper):
UPDATE reservations SET status = 'RELEASED'  WHERE reservation_id = ? AND status = 'RESERVED';
```

Whichever transaction commits first wins the `status = 'RESERVED'`
predicate; the second one affects 0 rows and its caller treats that as
"already handled elsewhere," not an error. **Optimistic locking doesn't
just prevent double-writes — it's also how you resolve races between two
entirely different actors (a user action and a background worker) with
zero coordination between them.**

### When to pick optimistic

- **Contention is low-to-moderate** — most attempts won't actually
  conflict, so paying for a lock up front would be wasted cost on the
  common case.
- **The critical section (the actual conflicting statement) is a single
  atomic operation**, or can be restructured into one — no multi-step
  "read, branch, write" sequence needs to stay consistent under the
  same lock.
- **Retries are cheap and safe to expose to the caller** — a failed
  conditional update just means "re-read and try again" or "return a
  clean business error" (e.g. "out of stock"), not a system failure.

### Trade-off

Optimistic locking's failure mode under **high** contention is the
mirror image of pessimistic's: instead of many transactions queuing
patiently for a lock, you get many transactions racing, one winning and
N-1 immediately retrying — which, at extreme contention (the last unit
of a viral SKU), degenerates into a retry storm that looks like the "many
transactions wait for the same row" problem again, just without the
database doing the queueing for you. This is exactly why
[[flash-sale-scaling]] exists — at genuinely extreme contention, *neither*
optimistic nor pessimistic SQL locking is enough, and the fix is moving
the hot counter off SQL entirely onto a Redis atomic `DECR`.

---

## 3. Distributed Locking

### Mechanism

Pessimistic and optimistic locking both live entirely inside one
database transaction. A distributed lock exists for the case where the
thing you need mutual exclusion over **outlives a single
transaction** — because it spans multiple requests, multiple services,
or minutes of user think-time — so the lock itself has to be a piece of
externally-visible, TTL-bound state, not a row lock held by an open
transaction.

The canonical mechanism (from [[redis-guide]] §1, and worked out in full
in `movie-ticket-booking.md`):

```lua
-- acquire: KEYS[1] = lock:<resource>, ARGV[1] = holderToken, ARGV[2] = ttl
if redis.call('SET', KEYS[1], ARGV[1], 'NX', 'EX', ARGV[2]) then
  return 1   -- acquired
end
return 0     -- someone else already holds it

-- release: compare-and-delete, NEVER a bare DEL
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
```

`NX` (set-if-not-exists) is what makes acquire atomic — no
read-then-write gap for two concurrent requests to both slip through.
The compare-and-delete release matters because a bare `DEL` could delete
a lock someone *else* acquired after your TTL expired — deleting a lock
you no longer own is its own correctness bug.

### The known gap: TTL expiry doesn't mean "the holder stopped working"

`movie-ticket-booking.md` states this precisely, and it's the single
most important thing to understand about distributed locks:

> "If the lock holder pauses past the TTL (GC pause, network blip) and a
> second client acquires the lock and starts writing, then the first
> client resumes and tries to write too, both think they're the
> legitimate holder... The rigorous fix is a **fencing token**: a
> monotonically increasing number handed out with each successful
> acquire, which every downstream write must present and which storage
> rejects if a higher token has already been seen."

Compare-and-delete protects the *lock key itself* from a wrong release.
It does **not** protect the *downstream write* (the actual SQL insert)
from a paused-past-TTL holder completing it late. Only a fencing token,
checked at the point of the real write, closes that gap fully.

### Redlock and ZooKeeper — why they're rejected here, on purpose

Both `movie-ticket-booking.md` and [[redis-guide]] explicitly reject the
"more rigorous" alternatives, and the reasoning is worth internalizing
rather than reflexively reaching for the fanciest option:

- **Redlock** (multi-Redis-node quorum lock) — addresses single-node
  failure, but Martin Kleppmann's widely-cited critique argues it
  doesn't actually guarantee mutual exclusion under realistic
  clock/GC-pause assumptions. Rejected here in favor of a single
  well-replicated Redis primary with sensible failover — judged
  sufficient for this system's stakes.
- **ZooKeeper ephemeral znodes** — genuinely more correct (tied to a
  client *session*, releases automatically on disconnect, no TTL-expiry
  race at all) — but a heavier piece of infrastructure to operate just
  for this. Rejected for operational simplicity.

**The lesson generalizes:** a distributed lock's correctness gap (TTL
expiry racing a paused holder) is a known, named, bounded risk — not a
reason to reach for the most theoretically airtight tool by default.
For a system operating at human-checkout speed (minutes, not
microseconds — seat holds, room holds), the practical risk of the TTL
gap is low, and it's a documented trade-off, not a swept-under-the-rug
one.

### Example — Movie Ticket Booking (the canonical writeup)

```text
lock:seat:{showtimeId}:{seatId} -> holdId   TTL = 600s (10 min hold window)
```

Hold path: for each seat in the request, attempt the Redis `SET NX`
acquire; **if any seat fails, roll back the ones that did succeed**
(release them) and return which seats are unavailable. This
"attempt-all-atomically, roll back on partial failure" shape is the
template every multi-resource distributed lock in this repo reuses.

### Example — Hotel Reservation (the same primitive, decomposed differently)

A "lock this room for this date range" request isn't one atomic Redis
operation — but `hotel-reservation-system.md` (§5) shows it doesn't need
to be a *new* primitive, just a different decomposition of what gets
locked:

```text
lock:room:{roomId}:{date}   -- one key per (room, night)
```

A 3-night stay acquires 3 locks, same attempt-all/roll-back-on-failure
pattern as the seat lock. This also solves partial-overlap correctly for
free: two requests for Aug 15–18 vs Aug 17–20 only contend on the shared
night (Aug 17) — the per-night granularity means a real conflict fails
the *whole* hold without falsely blocking requests for genuinely
non-overlapping dates. **No new locking mechanism was needed — only a
finer-grained resource key.**

Flight Ticket Booking and Doctor Appointment reuse the same `SET NX PX`
primitive unchanged at different scale — the mechanism doesn't relax
just because contention is lower; the invariant it protects
(double-booking a seat/slot) is the same regardless of traffic.

### When to pick distributed locking

- **The exclusive hold must survive across multiple requests / minutes
  of user think-time** — a `FOR UPDATE` transaction genuinely cannot
  stay open that long.
- **Multiple service instances (not just multiple transactions on one
  DB) need mutual exclusion** over a resource that isn't naturally a
  single database row with a single atomic-update predicate.
- **The resource decomposes into fine-grained keys** (one lock per
  seat, per room-night, per slot) so contention stays local to genuinely
  contended items, not global.

### When NOT to — the distinction your Inventory Service design already makes without naming it

This is the most important "when NOT to" in this note, and it's already
implicit in your own Amazon design even though you didn't use the words
"distributed lock" anywhere in it.

Movie Ticket Booking's seat hold and your Inventory Service's
reservation *look* like the same problem — "temporarily hold a resource
across user think-time" — but they're solved with **two different
tools**, and the reason why is worth being explicit about:

| | Movie Ticket Booking (seat hold) | Amazon Inventory Service (reservation) |
|---|---|---|
| Mechanism | Redis `SET NX PX` distributed lock | Durable SQL row: `status = HELD`, `expires_at`, reaper worker |
| What expires it | Redis TTL, automatically | A reconciliation worker that explicitly checks state before acting |
| Survives a Redis/process restart? | No — the lock (and the hold) is gone | Yes — it's a durable row, unaffected by any cache/lock-service outage |
| Needs an audit trail? | No — losing a seat hold just reopens the seat | Yes — it's tied to a real order, feeds a SAGA's compensation logic, and reconciliation needs to query "what's currently HELD" |
| Is the hold itself the business record? | No, `booking_seats` is, once `CONFIRMED` | Yes-ish — the reservation row *is* the record of "this inventory is spoken for," from creation onward |

The rule this surfaces: **reach for a distributed lock when the hold
itself doesn't need to be a durable, queryable business record — just
temporary mutual exclusion that's fine to lose on infrastructure
failure. Reach for durable state (a status column + `expires_at` +
reconciler, exactly your Inventory Service's §17) when the hold has to
survive a crash, feed a saga's compensation logic, or be independently
auditable.** Your Inventory Service's design already made the right
call here — it just made it implicitly, by choosing SQL, rather than by
explicitly rejecting a Redis lock the way `movie-ticket-booking.md` does
for Redlock.

Notably, [[flash-sale-scaling]] shows these aren't mutually exclusive —
under extreme contention it layers a Redis counter (fast path) **on top
of** the SQL row as the durable safety net, reconciled asynchronously.
The lock/durable-state choice isn't binary; it's "what's the source of
truth, and what (if anything) sits in front of it for speed."

---

## Comparison Table

| | Pessimistic | Optimistic | Distributed |
|---|---|---|---|
| **When lock is taken** | Before the read | Never — checked only at write time | Before the read, but outside any DB transaction |
| **Scope** | One DB transaction, one row/table | One DB statement | Across requests/services, via an external store (Redis, ZooKeeper, etcd) |
| **Best contention profile** | High — conflicts expected and frequent | Low-to-moderate — conflicts are the exception | Independent of contention; driven by *duration* (minutes, not milliseconds) |
| **Failure mode under high contention** | Queued waiters, possible deadlock | Retry storm | Same TTL-expiry gap regardless of contention level |
| **Survives process/service restart** | N/A (transaction-scoped) | N/A (transaction-scoped) | No, unless paired with durable state |
| **Needs explicit conflict handling in app code** | No (DB blocks for you) | Yes (retry loop on 0-rows) | Yes (TTL, fencing token, rollback-on-partial-failure) |
| **Repo examples** | Digital Wallet transfer; rejected alternative in your Inventory Service | Your Inventory Service (atomic conditional update); your Order Service, `amazon-order-management-system.md` (version column) | Movie Ticket Booking seat hold; Hotel Reservation per-night hold; Flight/Doctor Appointment |

---

## Decision Framework

Walk these questions in order:

1. **Does the exclusive hold need to outlive a single database
   transaction** (spans multiple HTTP requests, minutes of user
   think-time, or multiple service instances)?
   - **Yes** → you need something outside plain SQL locking. Go to 4.
   - **No** → stay inside one transaction, go to 2.

2. **Is contention on this resource expected to be high and frequent**
   (a genuinely hot row — last unit of a viral SKU, a popular seat)?
   - **Yes** → pessimistic (`FOR UPDATE`), *if* the critical section is
     short and single-transaction. If it's still too hot even under
     `FOR UPDATE` (thousands of concurrent holders on one row), you've
     outgrown plain SQL locking entirely — see [[flash-sale-scaling]].
   - **No** → optimistic. Go to 3.

3. **Does a single atomic conditional `UPDATE ... WHERE <invariant>`
   fully express the check you need** (a numeric threshold, an expected
   prior state)?
   - **Yes** → atomic conditional update (2b) — no version column
     needed, this is the leanest option and what your Inventory Service
     correctly reaches for by default.
   - **No** (the valid-transition logic is more complex than one
     predicate) → explicit `version` column (2a), as your Order Service
     uses for its state machine.

4. **Does the hold itself need to be a durable, auditable business
   record** (tied to a real order/booking, needs to survive a crash, or
   feeds a saga's compensation logic)?
   - **Yes** → don't reach for a bare lock. Model it as durable state:
     a `status` column + `expires_at` + a reconciliation worker that
     verifies current state before acting — your Inventory Service's
     `HELD`/reservation design.
   - **No** (losing the hold on infra failure is an acceptable, cheap
     failure — a seat just reopens) → distributed lock, `SET NX PX` +
     compare-and-delete release + fencing token at the downstream write.
     Decompose the resource into fine-grained keys (per-seat, per-night)
     so contention stays local, following Movie Ticket Booking / Hotel
     Reservation.

---

## Further Reading

- Martin Kleppmann, ["How to do distributed locking"](https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html)
  — the critique of Redlock referenced in `movie-ticket-booking.md` and
  [[redis-guide]]; worth reading directly rather than only secondhand,
  since the fencing-token argument is the load-bearing insight this note
  leans on in §3.
- PostgreSQL docs, [Explicit Locking](https://www.postgresql.org/docs/current/explicit-locking.html)
  — the authoritative source for the four row-lock strengths in §1's
  table.

## Related

- [[sql-guide]] §2 (Pessimistic Locking), §3 (Optimistic Locking), §4
  (Deadlock Avoidance & Detection), §5 (Atomic Conditional Updates) —
  the mechanics this note synthesizes.
- [[redis-guide]] §1 (Distributed Locking) — the mechanics behind §3
  here.
- [[flash-sale-scaling]] — what happens when even optimistic SQL locking
  isn't enough under extreme contention; the natural "next chapter"
  after this note.
- [[amazon-order-management-system]] — Order Service's version-column
  transitions and Inventory Service's atomic conditional update, both
  live in this repo's own design, not just your `My Own System Design`
  copy.
- `My Own System Design/Amazon/01 - Inventory Service - Principal HLD.md`
  §9–10 and `02 - Order Service - Principal HLD.md` §11 — your own
  design docs, the primary source of the optimistic/pessimistic
  examples above.
- `systems/hotel-reservation-system.md` §5, `systems/movie-ticket-booking.md`
  §5 (seat hold write-up) — the distributed-locking examples above.
