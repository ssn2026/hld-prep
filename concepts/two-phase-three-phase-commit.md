---
concept_name: Two-Phase Commit & Three-Phase Commit
linked_systems: [Amazon Order Managment System, Movie Ticket Booking, Hotel ReservationSyste, Digital Wallet]
last_reviewed: 2026-09-15
freshness: Fresh
notion_url: TBD
---

# Two-Phase Commit & Three-Phase Commit

## The question this answers

"A single business operation touches multiple databases that each commit
independently — how do I make that all-or-nothing, and why do 2PC and
3PC exist to solve that, in a way I'd actually be able to explain with a
real example, not just the textbook diagram?"

Same treatment as [[locking]]: mechanism deep-dive first, then the same
five systems (Inventory, Cart/Checkout, Movie Ticket Booking, Hotel
Reservation, Digital Wallet) walked through concretely, then a decision
framework and a standalone question checklist. `concepts/practice/sql-guide.md`
§9–10 already has the concise version of 2PC/3PC's mechanics — this note
is the practical, worked-example expansion of that, the same relationship
[[locking]] has to `sql-guide.md` §2–5 and `redis-guide.md` §1.

**In a hurry?** Jump to ["The Decision Framework"](#the-decision-framework)
and ["The Question Checklist"](#the-question-checklist) near the bottom.

---

## The core problem: atomicity stops being free once you cross a database boundary

Inside one database, `BEGIN ... COMMIT` gives you atomicity for free —
there's a single write-ahead log, so either every statement in the
transaction lands or none do, even across a crash.

The moment "reserve inventory" and "debit a wallet" live in **two
separate databases** (exactly the shape of `amazon-order-management-system.md`'s
database-per-service architecture), that guarantee disappears. Each
database has its own independent commit log and no idea the other one
exists. A plain sequence of two independent commits —

```text
Inventory DB: COMMIT (reservation created)
      ↓
   [crash / network failure / process dies here]
      ↓
Wallet DB: never reached — debit never happens
```

— leaves you in a state neither database, on its own, knows is wrong:
inventory says "reserved for order X," but nobody ever paid. **2PC and
3PC are protocols that try to recreate single-database atomicity across
multiple independently-committing databases.** They're not caching
tricks or performance optimizations — they exist purely to answer "how
do I get all-or-nothing when 'all' spans more than one commit log."

---

## 1. Two-Phase Commit (2PC)

### The two phases

**Phase 1 — Prepare (the "voting" phase).** The coordinator asks every
participant "could you commit this, if I asked you to?" Each participant
does everything short of making the change visible: takes the lock,
validates the business rule, writes the pending change to its own
write-ahead log (durable, but not yet committed/visible), and replies
YES or NO.

```text
Coordinator                    Inventory DB                    Wallet DB
    |-- PREPARE ------------------->|                               |
    |-- PREPARE --------------------------------------------------->|
    |                          lock row, check qty>=1                |
    |                          write pending change to WAL           |
    |                          reply: YES                            |
    |<----------- YES --------------|                                |
    |                                                    lock row, check balance
    |                                                    write pending change to WAL
    |                                                    reply: YES
    |<---------------------------------------------------- YES ------|
```

**Once a participant votes YES, it has made a durable promise** — it
must be able to honor "commit" later, even if it crashes and restarts
before hearing the final word. This is what makes Phase 1 expensive: the
lock is taken and held from this point forward, with no guarantee of how
long "forward" is.

**Phase 2 — Commit/Abort (the "decision" phase).** If every participant
voted YES, the coordinator sends COMMIT to all of them; if even one
voted NO (or never answered), it sends ABORT to all of them instead.

```text
    (all voted YES)
    |-- COMMIT --------------------->|
    |-- COMMIT ------------------------------------------------------>|
    |                          make change visible, release lock       |
    |<----------- ACK --------------|                                  |
    |<---------------------------------------------------- ACK -------|
```

Postgres has real, built-in support for exactly this
(`PREPARE TRANSACTION` / `COMMIT PREPARED`), not just a textbook diagram
— see [[sql-guide]] §9 for the actual SQL.

### The blocking problem, worked concretely

Take the exact scenario your own locking questions keep returning to:
**availability = 1**, and now the requirement is "reserve the last unit
AND debit the customer's wallet, atomically" — but Inventory and Wallet
are two separate databases, so you reach for 2PC.

Both participants vote YES in Phase 1. Inventory DB is now holding a row
lock on that SKU. Wallet DB is holding a row lock on that account. Both
are just waiting for the coordinator's final word.

**The coordinator process crashes right after collecting both YES votes,
before it can send COMMIT or ABORT to either participant.**

- Inventory DB cannot unilaterally commit: it has no way to know whether
  Wallet DB also voted YES, or voted NO right as the coordinator died.
- It cannot unilaterally abort either: maybe the coordinator *did* manage
  to send COMMIT to Wallet DB a moment before crashing — aborting now
  would mean the wallet gets charged with no reservation ever created.
- The only safe move is to **do nothing and wait**, holding the lock,
  until the coordinator recovers (or a human forces a decision by
  manually inspecting every participant's prepared state).

**The concrete consequence:** that single SKU's row is locked —
unsellable to any other customer — for as long as the coordinator stays
down. A stateless coordinator that needs a 90-second redeploy means a
90-second total outage on that SKU. A coordinator-hosting datacenter
failure means the SKU is unsellable until someone manually resolves
every in-flight prepared transaction. **This is 2PC's defining
weakness: coordinator failure converts directly into indefinite
participant blocking**, and the damage scales with how hot the locked
resource is — which is exactly backwards, since the highest-value,
highest-traffic SKUs are the ones you can least afford to have stuck.

---

## 2. Three-Phase Commit (3PC)

### The textbook fix, phase by phase

3PC inserts a phase between "vote" and "commit" — called **pre-commit**
— specifically to close 2PC's blocking gap. The idea: don't let a
participant reach an ambiguous "I voted YES, now what?" state at all;
instead, tell it "everyone agreed" *before* asking it to actually commit,
so that even if the coordinator vanishes afterward, the participant
already knows enough to safely finish on its own.

```text
Phase 1 — CanCommit?  (same as 2PC's Prepare/vote)
Coordinator -- CanCommit? --> each participant
each participant -- Yes/No --> Coordinator

Phase 2 — PreCommit  (the new phase)
   (only sent if ALL participants voted Yes)
Coordinator -- PreCommit --> each participant
each participant -- ACK --> Coordinator
   (participant now KNOWS every other participant also voted Yes —
    it can safely self-commit later even with zero further contact
    from the coordinator, because PreCommit itself is proof consensus
    was reached)

Phase 3 — DoCommit
Coordinator -- DoCommit --> each participant
each participant commits, replies ACK
```

The load-bearing design idea: **once a participant has received
PreCommit, it arms a timeout.** If DoCommit never arrives within that
window, the participant assumes the coordinator died (not that the
transaction was aborted — abort could never reach PreCommit at all,
since PreCommit is only sent after unanimous Yes) and **commits on its
own**, without waiting any further. This is what's supposed to make 3PC
non-blocking — a lone participant is never stuck the way 2PC's
Inventory DB was stuck above.

### Why the fix doesn't actually work — a worked split-brain

The self-commit rule is only safe if a timeout reliably means "the
coordinator crashed." On a real network, a timeout could just as easily
mean "the coordinator is alive, but a partition is hiding it from me
right now" — and 3PC cannot tell those two cases apart. Here's the same
Inventory/Wallet scenario, showing exactly how that ambiguity breaks
atomicity:

```text
1. Coordinator sends CanCommit to Inventory DB and Wallet DB. Both reply Yes.

2. Coordinator sends PreCommit to both.
   - Inventory DB receives PreCommit, ACKs successfully.
   - Wallet DB also RECEIVES PreCommit (it is healthy and now armed to
     self-commit on timeout) — but a network partition swallows its ACK
     on the way back to the coordinator.

3. Coordinator, having only seen Inventory DB's ACK, times out waiting
   for Wallet DB and — being conservative about a participant it can't
   confirm — decides to ABORT the whole transaction. It sends Abort to
   Inventory DB. It never reaches Wallet DB (still partitioned).

4. Wallet DB, having already received PreCommit in step 2, hits its own
   timeout waiting for DoCommit and — per the protocol — self-commits,
   because as far as it knows the coordinator simply died after
   PreCommit, and PreCommit is supposed to mean "safe to finish."

RESULT: Inventory DB aborted (no reservation exists). Wallet DB
committed (the customer was charged). Money moved, nothing was
reserved — the exact partial-commit outcome both protocols exist to
prevent, reintroduced by 3PC's own fix for blocking.
```

This is precisely why 3PC's non-blocking guarantee is stated with a
condition attached: it only holds **under a synchronous network with a
known, bounded message delay** — a network where "no response yet"
unambiguously means "still in flight, wait longer" or "definitely dead,"
never "might be either." Real networks — the internet, and in practice
most datacenter networks too — are asynchronous: message delay has no
guaranteed bound, and partition is indistinguishable from slowness or
death from the waiting side. That's the theoretical reason **no
mainstream database implements 3PC**, not "nobody got around to it" —
implementing it would mean shipping a protocol whose central safety
property doesn't hold on the network it would actually run on.

---

## Comparison Table

| | 2PC | 3PC | SAGA (what this repo actually uses) |
|---|---|---|---|
| **Atomicity guarantee** | Strict, if it completes | Strict, if it completes and network is synchronous | None across the whole flow — eventual consistency via compensation |
| **Coordinator crash mid-flight** | Participants block indefinitely, holding locks | Participants self-commit after a timeout — but see the split-brain above | No blocking possible — each step already committed locally before the next begins |
| **Works with an external system** (payment gateway, another company's API) **as a participant?** | No — participant must implement prepare/commit | No, same requirement | Yes — that's the point; each external call is its own committed step with a compensating action (refund, cancel) defined separately |
| **Extra round trips vs. a single local commit** | 2 (prepare, decide) | 3 (can-commit, pre-commit, do-commit) | 0 extra — each step is a normal local commit |
| **Used in production today?** | Yes — XA transactions, and internally inside distributed databases (Spanner, CockroachDB) that make the *coordinator* itself highly available via consensus rather than trying to eliminate 2PC | Essentially never — the safety gap above makes it worse than academically interesting | Yes — this is the default pattern for cross-service business transactions in every system in this repo |
| **Repo examples** | None — deliberately avoided everywhere | None | `amazon-order-management-system.md` checkout; every payment-then-confirm flow below |

---

## Five Worked Problems

### Problem 1 — Inventory reserve + Wallet debit, atomically, across two databases

The scenario worked in full above. **2PC is theoretically correct here**
— both participants are databases you control and could make
XA/2PC-capable — but the blocking failure means a coordinator outage
turns your hottest, most contended SKU into an outage of its own.
**What this repo does instead:** Inventory Service commits the
reservation **immediately and locally** — `status = HELD`, `expires_at`
— the exact "durable state, not a lock" pattern from [[locking]]
Problem 2. If the wallet debit later fails, Order Service doesn't roll
back a still-open distributed transaction (there isn't one) — it issues
a **new, independently-committed compensating transaction**: release the
reservation. The trade: briefly non-atomic (reserved-but-unpaid can
exist for a moment), but never blocked.

### Problem 2 — Full checkout saga: Order DB + Inventory DB + Payment DB

This is `amazon-order-management-system.md`'s literal architecture —
three independently-owned databases, exactly the shape 2PC exists for,
now with **three** participants instead of two (more participants means
more ways for the coordinator to die mid-vote, not fewer). The design
explicitly rejects a distributed transaction: Order Service is named as
the **SAGA orchestrator**, not a 2PC coordinator. Each step — reserve
inventory, create payment intent — commits on its own, synchronously,
inside the checkout request. The async leg (payment webhook → Kafka →
both consumers finalize) is handled with idempotent, individually-
committed consumers, not a held-open cross-service transaction. If Order
Service itself crashes mid-saga, nothing is stuck holding a lock — the
reservation just sits `HELD` until `expires_at`, and the reaper releases
it. Self-healing, not manually-recoverable.

### Problem 3 — Movie Ticket Booking: seat confirmation + payment charge

Here 2PC isn't just undesirable, it's **not applicable at all**: one of
the two participants is an external payment gateway reached over HTTP,
and 2PC requires every participant to implement the prepare/commit
protocol itself. A card processor's API doesn't have a `PREPARE
TRANSACTION` verb to call. Your own Payment Service doc names exactly
this asymmetry (`03 - Payment Service - Principal HLD.md`, §4):

> "There are two kinds of truth: our internal state
> (`PAYMENT_PENDING`/`SUCCESS`)... and provider-side state (`provider
> transaction = captured`). When a network timeout occurs, our service
> may not know the provider state immediately."

**What actually happens instead — order operations so the hard-to-undo
step happens last:** the seat hold (Redis `SET NX PX`, from `movie-ticket-booking.md`
§5) is acquired *first* — cheap to release if anything downstream fails.
Payment is attempted *second*. The durable `booking_seats` row is only
inserted *after* payment succeeds. If payment fails, the compensating
action is trivial — just let the Redis TTL expire, or release it
immediately. If payment *succeeds* but the booking insert somehow fails,
the compensating action is a refund — itself a separate, ordinary
operation, not a protocol rollback. **No commit protocol runs here at
all**, because the design was shaped, from the start, to put the
irreversible step (charging money) last and behind a cheap, freely-
releasable hold.

### Problem 4 — Hotel Reservation: room-night hold + payment

Identical reasoning to Problem 3. The per-room-night distributed locks
(`hotel-reservation-system.md` §5) are acquired first, are cheap to
release, and are held only until payment either succeeds (booking
committed) or fails (locks released, no compensating action needed
beyond that). The payment gateway is external here too — same
"can't be a 2PC participant" reasoning as the movie booking.

### Problem 5 — Wallet transfer: within one bank vs. across institutions

Within a single Wallet DB (both accounts in the same database), 2PC
never even enters the picture — this is [[locking]] Problem 5, plain
pessimistic locking, `FOR UPDATE` on both rows in one local transaction,
done.

The interesting extension is a **cross-institution** transfer — debit a
wallet internally, credit an account at an actual external bank. Now
there genuinely are two independent systems involved, and intuitively
you'd expect the finance industry, of all places, to insist on strict
atomicity. In practice it doesn't use 2PC either, for the same reason as
Problems 3–4: the counterparty bank's system isn't a participant you can
ask to `PREPARE TRANSACTION`. Real settlement rails (ACH, SWIFT, card
networks) instead debit locally, submit the transfer as a message, and
reconcile afterward — with **reversal** (a new, compensating transaction
— a chargeback, a returned ACH entry) as the mechanism for "it didn't
actually go through." That's architecturally a SAGA, just one that
predates the name by decades.

| Problem | Both participants are internal DBs? | 2PC even applicable? | What this repo/real systems actually do |
|---|---|---|---|
| 1. Inventory + Wallet debit | Yes | Yes, but blocks on coordinator failure | Durable `HELD` state + compensating release |
| 2. Order + Inventory + Payment saga | Yes (3 of them) | Yes, worse with more participants | SAGA orchestration, per-step local commits |
| 3. Movie seat + payment gateway | No — gateway is external | **No** | Cheap hold first, irreversible charge last, refund as compensation |
| 4. Hotel room-night + payment gateway | No — gateway is external | **No** | Same as Problem 3 |
| 5. Cross-bank wallet transfer | No — counterparty bank is external | **No** | Reconciliation + reversal (a SAGA, just older than the term) |

---

## The Decision Framework

**Q1 — Are every one of the participants a database/resource manager
you control, capable of implementing prepare/commit** (XA, or Postgres's
`PREPARE TRANSACTION`)?
- **No** (any participant is an external HTTP API — a payment gateway,
  another company's system) → **2PC/3PC are not options, full stop.**
  Use compensating actions: commit each step locally and immediately,
  and define an explicit compensating operation (refund, release,
  cancel) for every step that might need undoing later. This covers
  Problems 3, 4, and 5 above, and is the overwhelming majority of
  real cross-service business transactions.
- **Yes** → go to Q2.

**Q2 — Can the business tolerate a participant blocking — holding
locks — for the duration of a coordinator outage, in exchange for
strict guaranteed atomicity?**
- **Yes, and the coordinator itself can be made highly available**
  (Paxos/Raft-replicated, the way Spanner and CockroachDB avoid "one
  coordinator process = one point of failure" without abandoning 2PC) →
  2PC is a legitimate, real engineering choice — but recognize you're
  now signing up to build or operate that replicated-coordinator
  infrastructure, not just call `PREPARE TRANSACTION`.
- **No** (a single coordinator instance, or the resource at stake is too
  hot/business-critical to tolerate even a brief block — Problem 1's
  last-unit SKU) → SAGA / compensating actions, same as this repo's
  default everywhere.

**Q3 — (only relevant if you're specifically evaluating 3PC) Does the
network connecting every participant provide a bounded, known message-
delay guarantee** — a genuine synchronous-network assumption?
- **No** (true of essentially every real network, including most
  datacenter networks under partition) → do not use 3PC; its
  non-blocking guarantee is unsafe exactly the way the split-brain
  worked example above shows. This is why no mainstream database ships
  it.
- **Yes** (a tightly controlled, bounded-latency network — real-time
  embedded systems, not typical web infrastructure) → 3PC becomes
  theoretically sound, though the extra round-trip cost still makes it
  a hard sell versus other options.

---

## The Question Checklist

Print this part:

1. **Is every participant an internal database you control** (not an
   external API/gateway/other company's system)?
   - No → **compensating actions (SAGA)**, full stop. Done.
   - Yes → Q2.
2. **Can you tolerate a participant blocking during a coordinator
   outage?**
   - No → **compensating actions (SAGA)**. Done.
   - Yes, and you can make the coordinator itself highly available →
     **2PC** is legitimate. Done.
3. **(3PC only) Does the network guarantee bounded message delay?**
   - No (always assume no) → **never use 3PC**.

**The myth to unlearn:** 2PC isn't mainly rejected for being "slow." It's
rejected because (a) most real cross-service transactions include at
least one participant — a payment gateway, another company's system —
that structurally cannot speak the protocol at all, and (b) even when
every participant *could* speak it, a single coordinator turns into a
single point of blocking failure unless you invest in making that
coordinator itself highly available (real distributed databases do this
via consensus; most application teams reasonably don't bother, and reach
for SAGA instead). Problem 3–5 above are the common case in a typical
HLD interview system — 2PC was never actually on the table for them.

---

## Further Reading

- Jim Gray & Leslie Lamport, ["Consensus on Transaction Commit"](https://lamport.azurewebsites.net/pubs/consensus-on-transaction-commit.pdf)
  — the formal treatment of why 2PC blocks and what a non-blocking
  protocol would require.
- The original 3PC proposal is Dale Skeen's 1981 paper; most modern
  write-ups (including this one) explain it via the CanCommit/
  PreCommit/DoCommit framing rather than Skeen's original terms.

## Related

- [[locking]] — same worked-examples format; that note's Problem 2
  (durable `HELD` reservation state, not a lock) is literally the
  mechanism Problem 1/2 above use in place of 2PC.
- [[sql-guide]] §9 (Two-Phase Commit), §10 (Three-Phase Commit) — the
  concise mechanics this note expands on.
- [[amazon-order-management-system]] — the actual SAGA-orchestrated
  checkout referenced throughout.
- `concepts/saga.md` (not yet created) — this note explains what SAGA is
  chosen *instead of*; the SAGA pattern itself (orchestration vs.
  choreography, compensating-transaction design) deserves its own pass.
