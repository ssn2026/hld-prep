---
service_name: Hotel ReservationSyste
grouping: Booking System
status: Deep Dive Ready
labels: [SQL, Redis]
sections_complete: 10
last_session: 2026-08-12
notion_url: TBD
---

**Diagram:** `systems/diagrams/hotel-reservation-system.drawio` (page 1:
architecture; page 2: booking state)

**Interactive trace:** `systems/implementations/hotel-reservation-system-trace.html`
— a 3-night stay locked as three per-night locks, and an overlapping
request that only conflicts on one of them

## 1. Requirement Gathering

**Functional**
- Search room availability for a hotel across a date range.
- Hold a room for a specific check-in/check-out range while completing
  payment.
- Confirm or cancel a booking.

**Non-functional**
- The same non-negotiable as `movie-ticket-booking.md`: two guests must
  never end up holding the same room for overlapping nights. But the
  resource here is a **range**, not a single discrete unit — this is
  the harder variant flagged as a follow-up when Movie Ticket Booking
  was designed.
- Typically lower peak concurrency than a movie premiere (booking
  windows are usually not "everyone clicks at the same instant"), but
  the correctness bar is identical.

## 2. Queries in Plain English

- Search available rooms for a hotel across a date range.
- Hold a room for a date range.
- Confirm a booking.
- Cancel a booking.

## 3. State Diagram

Same shape as `movie-ticket-booking.md`, since the underlying lock +
durable-record pattern is being reused:
```
Room-night:  AVAILABLE → HELD → BOOKED → (cancelled) → AVAILABLE
Booking:     CREATED → PENDING_PAYMENT → CONFIRMED / EXPIRED
```

## 4. API Endpoints

| Endpoint | Notes |
|---|---|
| `GET /hotels/{hotelId}/availability?checkIn=&checkOut=` | |
| `POST /hotels/{hotelId}/rooms/{roomId}/hold` | body: `{checkIn, checkOut}` |
| `POST /bookings` | body: `{holdId, paymentMethod}` |
| `POST /bookings/{bookingId}/cancel` | |

## 5. Concurrency Requirements

**The key insight: decompose the range into the same primitive already
built.** A single "lock this room for this date range" isn't directly
expressible as one atomic Redis operation the way a single seat is —
but a range *is* just a set of individual nights. So the hold acquires
one lock per night:
```
lock:room:{roomId}:{date}   -- one key per (room, night)
```
A 3-night stay acquires 3 locks with the exact same
"attempt-all-atomically, roll back whatever succeeded if any fails"
pattern already used for multi-seat holds in
`movie-ticket-booking.md` §9 — this is genuinely the same primitive,
just applied to more keys per hold. No new locking mechanism was
needed, only a different decomposition of the resource being locked.

**Why this matters for partial overlaps:** two requests for
overlapping-but-not-identical ranges (e.g. Aug 15-18 vs Aug 17-20) will
only contend on the shared night (Aug 17) — the per-night lock
granularity means a conflict on one night correctly fails the whole
hold (roll back the nights that *did* acquire) without falsely
blocking a request for genuinely non-overlapping dates.

## 6. Database Choice + Justification

Same reasoning as `movie-ticket-booking.md` — Redis for the ephemeral
per-night locks (fast, TTL-bound, exactly mirrors the seat-lock
pattern), SQL for hotels/rooms/bookings (relational, needs joins for
search).

## 7. Database Schema

```sql
CREATE TABLE rooms (room_id BIGINT PRIMARY KEY, hotel_id BIGINT NOT NULL, room_type VARCHAR(30));

CREATE TABLE room_night_holds (
  hold_id    BIGINT PRIMARY KEY,
  room_id    BIGINT NOT NULL,
  night      DATE NOT NULL,
  user_id    BIGINT NOT NULL,
  status     VARCHAR(20) NOT NULL,   -- HELD, CONFIRMED, EXPIRED
  expires_at TIMESTAMP NOT NULL
);
CREATE UNIQUE INDEX idx_room_night_active ON room_night_holds(room_id, night) WHERE status = 'HELD';

CREATE TABLE bookings (
  booking_id BIGINT PRIMARY KEY, user_id BIGINT NOT NULL, room_id BIGINT NOT NULL,
  check_in DATE NOT NULL, check_out DATE NOT NULL, status VARCHAR(20) NOT NULL
);
```

Redis: `lock:room:{roomId}:{date} -> holdId`, TTL = 10 min.

## 8. Detailed Queries

```lua
-- same acquire.lua as movie-ticket-booking.md, run once per night in the range
if redis.call('SET', KEYS[1], ARGV[1], 'NX', 'EX', ARGV[2]) then return 1 end
return 0
```
```sql
INSERT INTO room_night_holds (hold_id, room_id, night, user_id, status, expires_at)
VALUES (?, ?, ?, ?, 'HELD', now() + interval '10 minutes');   -- one row per night
```

## 9. Read/Write Paths

**Hold path:** for each night in `[checkIn, checkOut)`, attempt the
Redis lock acquire → if any night fails, release the ones that
succeeded and report which night conflicted → on full success, insert
one `room_night_holds` row per night.

**Confirm path:** same shape as Movie Ticket Booking — verify all
night-holds are still `HELD` and unexpired, process payment, insert
`bookings` (`CONFIRMED`), mark all night-holds `CONFIRMED`.

**Expiry path:** each night lock's TTL fires independently; a
reconciler sweeps `room_night_holds` past `expires_at`.

## 10. Scale Justification

Booking volume per hotel is orders of magnitude below a movie
premiere's per-seat contention — the interesting scale question here
is search (availability across many rooms/dates), not the hold path,
which is comfortably served by the same lock mechanism proven in
`movie-ticket-booking.md` at higher contention than this system will
realistically see.

## Implementation Notes

_(none yet beyond the interactive trace linked above)_
