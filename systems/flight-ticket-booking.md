---
service_name: Flight Ticket Booking
grouping: Booking System
status: Deep Dive Ready
labels: [SQL, Redis]
sections_complete: 10
last_session: 2026-08-12
notion_url: TBD
---

**Diagram:** `systems/diagrams/flight-ticket-booking.drawio` (page 1:
architecture — fare-bucket counter + seat lock together)

**Interactive trace:** `systems/implementations/flight-ticket-booking-trace.html`
— booking Economy decrements a fare bucket, not a seat lock; the actual
seat only gets locked at check-in

## 1. Requirement Gathering

**Functional**
- Search flights; view fare classes (Economy/Business) with remaining
  availability and price.
- Book a fare class (not a specific seat, at booking time).
- Assign an actual seat at check-in.
- Cancel a booking.

**Non-functional**
- The genuinely distinctive requirement here, vs. Movie Ticket
  Booking: airlines deliberately **oversell** a flight's fare buckets
  based on predicted no-show rates (yield management) — this is a
  real, intentional business decision, not a bug to design around.
  Economy might sell 155 tickets against 150 physical seats because
  historical no-show rates make that statistically safe.

## 2. Queries in Plain English

- Search flights and fare availability.
- Book a fare class.
- Assign a seat at check-in.
- Cancel a booking.

## 3. State Diagram

```
Booking:  CREATED → CONFIRMED → CHECKED_IN → (flown) / CANCELLED
Seat:     UNASSIGNED → ASSIGNED (only from check-in onward)
```

## 4. API Endpoints

| Endpoint | Notes |
|---|---|
| `GET /flights/search?from=&to=&date=` | |
| `POST /flights/{flightId}/book` | body: `{fareClass}` — books a bucket, not a seat |
| `POST /bookings/{bookingId}/check-in` | assigns an actual seat |
| `POST /bookings/{bookingId}/cancel` | |

## 5. Concurrency Requirements

**Two different concurrency problems, two different mechanisms —
deliberately, not by accident:**

- **Booking a fare class is a *counting* problem**, same shape as
  `concepts/flash-sale-scaling.md`'s inventory counter: an Economy seat
  is fungible at booking time — the buyer doesn't care *which* seat,
  only that one is available. An atomic conditional decrement
  (`UPDATE fare_buckets SET sold = sold + 1 WHERE sold < overbook_limit`)
  handles concurrent bookings with no lock needed, and it's what makes
  deliberate overselling (`overbook_limit > physical_capacity`) a
  simple parameter rather than a special case.
- **Assigning a physical seat at check-in is a *locking* problem**,
  same shape as `movie-ticket-booking.md` — seat 14C is not fungible,
  two passengers can't both get it, so this reuses that system's Redis
  `SET NX` lock unchanged.

The interesting design lesson: **the same flight has both kinds of
concurrency problem at different points in its lifecycle**, and forcing
one mechanism to handle both would be wrong in both directions — a lock
per fare-class booking would be needless overhead for a fungible
resource, and a bare counter for seat assignment would allow two
passengers to get the same physical seat.

## 6. Database Choice + Justification

- **Fare bucket counts → SQL**, with the same atomic conditional-UPDATE
  pattern as inventory in `amazon-order-management-system.md` —
  durable, moderate volume, no need for Redis's raw throughput at this
  system's scale.
- **Seat locks at check-in → Redis**, identical mechanism to
  `movie-ticket-booking.md` §5–6, reused without modification.

## 7. Database Schema

```sql
CREATE TABLE fare_buckets (
  flight_id      BIGINT NOT NULL,
  fare_class     VARCHAR(10) NOT NULL,   -- ECONOMY, BUSINESS
  sold           INT NOT NULL DEFAULT 0,
  overbook_limit INT NOT NULL,           -- > physical seat count for that class, by design
  PRIMARY KEY (flight_id, fare_class)
);

CREATE TABLE bookings (
  booking_id BIGINT PRIMARY KEY, user_id BIGINT NOT NULL, flight_id BIGINT NOT NULL,
  fare_class VARCHAR(10) NOT NULL, seat_id VARCHAR(10), status VARCHAR(20) NOT NULL
);
```
Redis: `lock:seat:{flightId}:{seatId} -> bookingId` (check-in only, same
mechanism as `movie-ticket-booking.md`).

## 8. Detailed Queries

```sql
-- book a fare class (counting problem)
UPDATE fare_buckets SET sold = sold + 1
WHERE flight_id = ? AND fare_class = 'ECONOMY' AND sold < overbook_limit;
```
```lua
-- assign a seat at check-in (locking problem — identical to movie-ticket-booking.md)
if redis.call('SET', KEYS[1], ARGV[1], 'NX', 'EX', ARGV[2]) then return 1 end
return 0
```

## 9. Read/Write Paths

**Booking path:** conditional `UPDATE fare_buckets` — a single atomic
statement, no lock, no seat involved yet.

**Check-in path:** exactly `movie-ticket-booking.md`'s hold flow —
attempt the Redis lock for a specific seat, insert the assignment on
success.

## 10. Scale Justification

Bounded by physical reality (a flight has a few hundred seats across a
few fare classes) — this system will never see anything close to the
per-key contention `movie-ticket-booking.md`'s premiere scenario does.
The interesting scale property is architectural, not throughput: two
right-sized mechanisms instead of one over- or under-powered one.

## Implementation Notes

_(none yet beyond the interactive trace linked above)_
