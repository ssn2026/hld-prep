---
service_name: Movie Ticket Booking
grouping: Booking System
status: Deep Dive Ready
labels: [SQL, Redis]
sections_complete: 10
last_session: 2026-08-12
notion_url: TBD
---

**Diagram:** `systems/diagrams/movie-ticket-booking.drawio` (page 1:
architecture; page 2: seat + booking state diagrams)

**Interactive trace:** `systems/implementations/movie-ticket-booking-trace.html`
— two users racing for the same seat, and what happens if the winner
never completes payment

**This is the system chosen for the Distributed Locking deep-dive**
flagged in `docs/TRACKER.md`'s Planning Notes — see section 5.

## 1. Requirement Gathering

**Functional**
- Browse showtimes for a movie/theater/date; view a showtime's live
  seat map (available / held / booked).
- Select one or more seats and put a temporary hold on them while
  completing payment.
- Confirm the booking (payment) → seats become permanently booked, a
  ticket is issued.
- Cancel a booking before showtime → seats release back to available.
- A held seat that isn't confirmed within a hold window (10 minutes)
  releases automatically — nobody should have to manually "un-stick" a
  seat someone abandoned mid-checkout.

**Non-functional**
- The defining scenario: a popular premiere where thousands of
  concurrent users are competing for the same handful of good seats in
  one theater. Two users must **never** end up holding or booking the
  same seat for the same showtime — this is non-negotiable, unlike a
  fungible inventory count that can tolerate a sharded approximation.
- Hold/confirm latency: sub-second, this is an interactive UI action.
- Moderate scale relative to a platform-wide flash sale — bursty around
  specific premieres, not a sustained flood.

## 2. Queries in Plain English

**User-facing**
- Get showtimes for a movie/theater/date.
- Get the live seat map for a showtime.
- Hold one or more seats.
- Confirm a booking (pay) for a held set of seats.
- Cancel a booking.
- Get my bookings.

**Internal**
- Payment webhook → confirm booking.
- Reconcile expired holds (seats whose Redis lock TTL fired) back to
  `AVAILABLE` in the durable record.

## 3. State Diagram

Two entities, both genuinely stateful:

```
Seat (per showtime):  AVAILABLE → HELD → BOOKED
                            ↑        ↓
                            └── (hold expires or is released)
                       BOOKED → CANCELLED → AVAILABLE   (refund flow)

Booking:  CREATED → PENDING_PAYMENT → CONFIRMED
                          ↓
                       EXPIRED / CANCELLED
```

## 4. API Endpoints

**Client-facing**
| Endpoint | Notes |
|---|---|
| `GET /movies/{movieId}/showtimes` | |
| `GET /showtimes/{showtimeId}/seats` | live seat map |
| `POST /showtimes/{showtimeId}/seats/hold` | body: `{seatIds: [...]}` → returns `{holdId, expiresAt}` |
| `POST /bookings` | body: `{holdId, paymentMethod}` → confirms |
| `POST /bookings/{bookingId}/cancel` | |
| `GET /users/{userId}/bookings` | |

**Internal**
| Endpoint | Notes |
|---|---|
| `POST /internal/payments/webhook` | drives hold → `CONFIRMED` |

## 5. Concurrency Requirements — Distributed Locking

**User-request-level:** a hold request should be idempotent per
checkout session (a double-click shouldn't try to hold the same seats
twice under two different hold IDs).

**Resource-level — the actual problem:** two users click seat 12B for
the same showtime within milliseconds of each other. Whoever's request
is processed second must fail cleanly, before either write touches
durable storage in a way that could conflict.

**Why a plain SQL row lock doesn't solve this on its own:** the hold
has to survive across the user's think-time entering payment details —
that can be minutes, spanning multiple HTTP requests. A `SELECT ... FOR
UPDATE` transaction can't reasonably stay open that long (connection
pool exhaustion, and it'd block every other seat operation on that
row's page). What's needed is a lock that lives *outside* any single
request/transaction, with its own expiry — a genuine **distributed
lock**.

**The mechanism — Redis `SET ... NX PX`:**
```lua
-- acquire: KEYS[1] = lock:seat:{showtimeId}:{seatId}, ARGV[1] = holdId, ARGV[2] = ttl seconds
if redis.call('SET', KEYS[1], ARGV[1], 'NX', 'EX', ARGV[2]) then
  return 1   -- acquired
end
return 0     -- someone else already holds it
```
`NX` (only set if not exists) is what makes this atomic — there's no
read-then-write gap for two concurrent requests to both slip through.
Release is a compare-and-delete, not a bare `DEL`, so a request can
never release a lock it doesn't actually own:
```lua
-- release: only delete if the value still matches this holder's token
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
```

**The known gap — why this isn't fully rigorous, and what fixes it:**
if the lock holder pauses past the TTL (GC pause, network blip) and a
*second* client acquires the lock and starts writing, then the first
client resumes and tries to write too, both think they're the
legitimate holder. The compare-and-delete above prevents client 1 from
releasing client 2's lock, but doesn't by itself stop client 1 from
completing a stale confirm. The rigorous fix is a **fencing token**: a
monotonically increasing number handed out with each successful
acquire, which every downstream write (the actual SQL booking insert)
must present and which storage rejects if a higher token has already
been seen. For a booking system operating at human checkout speed
(minutes, not microseconds) the practical risk is low, but it's worth
knowing the gap exists rather than assuming TTL + compare-and-delete is
airtight.

**Alternatives, and why Redis was chosen here:**
- **Redlock** (multi-Redis-node quorum lock) — addresses single-node
  failure, but is genuinely contested: Martin Kleppmann's critique
  argues it doesn't actually guarantee mutual exclusion under
  clock/GC-pause assumptions that are realistic in production. Not
  used here; a single well-replicated Redis primary with sensible
  failover is judged sufficient for this system's stakes.
- **ZooKeeper ephemeral znodes** — ties the lock to a client *session*
  rather than a fixed TTL, so it releases automatically the instant a
  client disconnects, no expiry race at all. More correct semantics,
  but a heavier piece of infrastructure to run just for this. Redis was
  chosen for operational simplicity, consistent with the rest of this
  repo's Redis-heavy designs (Rate Limiter, Flash Sale Scaling).
- **etcd leases** — similar trade-off to ZooKeeper.

## 6. Database Choice + Justification

- **Seat/showtime catalog data (movies, theaters, showtimes, seats) →
  SQL.** Relational, needs joins (seat map by showtime, theater by
  city), moderate write volume, not latency-critical enough to justify
  anything else.
- **Seat lock state → Redis**, `SET NX PX` as above — this is the
  actual mutual-exclusion mechanism, and it has to be fast and support
  a TTL that spans multiple requests.
- **Booking durable record → SQL.** Source of truth for what's actually
  been paid for; the Redis lock's job ends once a booking is
  `CONFIRMED` — from then on, `booking_seats` is what the seat map
  checks, not the lock.
- Worth contrasting with `concepts/flash-sale-scaling.md`: that system
  solved its concurrency problem by *avoiding* a lock entirely (atomic
  counter decrement, because units are fungible). This system needs an
  actual lock because a specific seat is not fungible — no sharding
  trick substitutes for real mutual exclusion here.

## 7. Database Schema

```sql
CREATE TABLE showtimes (
  showtime_id  BIGINT PRIMARY KEY,
  movie_id     BIGINT NOT NULL,
  theater_id   BIGINT NOT NULL,
  screen_id    BIGINT NOT NULL,
  start_time   TIMESTAMP NOT NULL
);

CREATE TABLE seats (
  seat_id    BIGINT PRIMARY KEY,
  screen_id  BIGINT NOT NULL,
  row_label  VARCHAR(5) NOT NULL,
  number     INT NOT NULL,
  seat_type  VARCHAR(20) NOT NULL   -- STANDARD, PREMIUM, ACCESSIBLE
);

CREATE TABLE seat_holds (
  hold_id      BIGINT PRIMARY KEY,
  showtime_id  BIGINT NOT NULL,
  seat_id      BIGINT NOT NULL,
  user_id      BIGINT NOT NULL,
  status       VARCHAR(20) NOT NULL,   -- HELD, CONFIRMED, EXPIRED, RELEASED
  expires_at   TIMESTAMP NOT NULL,
  created_at   TIMESTAMP NOT NULL
);
CREATE UNIQUE INDEX idx_hold_seat_active ON seat_holds(showtime_id, seat_id)
  WHERE status = 'HELD';   -- durable backstop, mirrors the Redis lock

CREATE TABLE bookings (
  booking_id    BIGINT PRIMARY KEY,
  user_id       BIGINT NOT NULL,
  showtime_id   BIGINT NOT NULL,
  status        VARCHAR(20) NOT NULL,  -- PENDING_PAYMENT, CONFIRMED, CANCELLED
  total_amount  DECIMAL(10,2) NOT NULL,
  created_at    TIMESTAMP NOT NULL,
  updated_at    TIMESTAMP NOT NULL
);

CREATE TABLE booking_seats (
  booking_id  BIGINT NOT NULL REFERENCES bookings(booking_id),
  seat_id     BIGINT NOT NULL,
  showtime_id BIGINT NOT NULL,
  price       DECIMAL(10,2) NOT NULL,
  PRIMARY KEY (booking_id, seat_id)
);
```

Redis:
```
lock:seat:{showtimeId}:{seatId} -> holdId   TTL = 600s (10 min hold window)
```

## 8. Detailed Queries

**Hold a set of seats (per seat, atomic acquire; roll back all on any
failure):**
```lua
-- acquire.lua, run once per seatId in the requested set
if redis.call('SET', KEYS[1], ARGV[1], 'NX', 'EX', ARGV[2]) then
  return 1
end
return 0
```
```sql
INSERT INTO seat_holds (hold_id, showtime_id, seat_id, user_id, status, expires_at, created_at)
VALUES (?, ?, ?, ?, 'HELD', now() + interval '10 minutes', now());
```

**Confirm a booking:**
```sql
UPDATE seat_holds SET status = 'CONFIRMED'
WHERE hold_id = ? AND status = 'HELD' AND expires_at > now();

INSERT INTO bookings (booking_id, user_id, showtime_id, status, total_amount, created_at, updated_at)
VALUES (?, ?, ?, 'CONFIRMED', ?, now(), now());

INSERT INTO booking_seats (booking_id, seat_id, showtime_id, price)
VALUES (?, ?, ?, ?);   -- one row per seat
```

**Release (compare-and-delete, and the matching durable update):**
```lua
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
```
```sql
UPDATE seat_holds SET status = 'EXPIRED' WHERE hold_id = ? AND status = 'HELD';
```

## 9. Read/Write Paths

**Hold path:** client selects seats → for each seat, the booking
service attempts the Redis `SET NX` acquire → if *any* seat fails, roll
back the ones that *did* succeed (release them) and return which seats
are no longer available → on full success, insert `seat_holds` rows
(`HELD`, `expires_at` = now + 10 min) and return `{holdId, expiresAt}`
to the client for a checkout countdown.

**Confirm path:** client submits payment → verify the hold is still
`HELD` and unexpired → process payment → on success, insert `bookings`
(`CONFIRMED`) + `booking_seats`, and mark `seat_holds` `CONFIRMED`. From
this point the seat map reads `booking_seats`, not the Redis lock — the
lock's job is done.

**Expiry path:** the Redis lock's TTL fires on its own; a periodic
reconciler sweeps `seat_holds` rows still `HELD` past `expires_at` and
marks them `EXPIRED`, so the durable record matches reality even though
nothing explicitly triggered it.

## 10. Scale Justification

Target: a premiere-night burst — 5,000 concurrent users competing for
seats in a 300-seat theater's opening show.

- **Lock throughput:** only ~300 possible lock keys exist for that
  showtime, so real contention concentrates on the handful of
  genuinely popular seats (center rows) — most of the 5,000 users are
  competing for *different* seats and see no contention at all. Redis
  `SET NX` on a single key comfortably clears far more than the peak
  concurrent-attempts-per-seat this scenario produces.
- **Latency:** two hops (client → booking service → Redis) for the hold
  attempt, same shape as Rate Limiter's check path — sub-10ms is
  realistic for the lock acquire itself.
- **Redis durability:** locks are inherently ephemeral (TTL-bound by
  design), so a pure in-memory Redis without aggressive persistence is
  an acceptable trade — worst case on a Redis restart, all in-flight
  holds are lost and those seats simply show as available again. This
  is a much gentler failure mode than losing a payment or order record
  would be, which is why it's fine for this specific piece of state to
  be less durable than `bookings` itself.

## Implementation Notes

_(none yet beyond the interactive trace linked above)_
