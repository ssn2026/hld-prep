---
service_name: Doctor Appointment
grouping: Booking System
status: Deep Dive Ready
labels: [SQL, Redis]
sections_complete: 10
last_session: 2026-08-12
notion_url: TBD
---

**Diagram:** `systems/diagrams/doctor-appointment.drawio` (single page
— architecture; state diagram is a simple 3-state chain, not worth a
separate page)

**Interactive trace:** `systems/implementations/doctor-appointment-trace.html`
— booking a slot, then a reminder notification firing the day before

## 1. Requirement Gathering

**Functional**
- Doctors publish available time slots.
- Patients book a slot; can cancel/reschedule.
- A reminder notification fires before the appointment.

**Non-functional**
- The lowest-contention system in this family: unlike a movie premiere
  or a flash sale, it's rare for many patients to fight over the exact
  same doctor-slot at the exact same instant. This is worth stating
  explicitly rather than assuming — it's what justifies *not*
  over-engineering this one.

## 2. Queries in Plain English

- Get a doctor's available slots.
- Book a slot.
- Cancel/reschedule a booking.
- (Internal) send a reminder before the appointment.

## 3. State Diagram

```
Slot:        AVAILABLE → HELD → BOOKED → (cancelled) → AVAILABLE
Appointment: SCHEDULED → COMPLETED / CANCELLED / NO_SHOW
```

## 4. API Endpoints

| Endpoint | Notes |
|---|---|
| `GET /doctors/{doctorId}/slots?date=` | |
| `POST /doctors/{doctorId}/slots/{slotId}/book` | |
| `POST /appointments/{id}/cancel` | |

## 5. Concurrency Requirements

A doctor-slot is a single, discrete, unsplittable unit — same shape as
a movie seat, not a date range like a hotel room. This reuses
`movie-ticket-booking.md`'s exact locking mechanism unchanged
(`SET NX` per slot), just at far lower contention. No new mechanism
was needed; the interesting design decision here is recognizing that
none was needed, rather than inventing a lighter-weight one "because
the scale is smaller" — the correctness requirement (never double-book
a slot) doesn't get relaxed just because contention usually is low.

## 6. Database Choice + Justification

Same as `movie-ticket-booking.md`: SQL for doctors/slots/appointments,
Redis for the per-slot lock. No justification for a different choice
exists here — the access patterns are identical, just less contended.

## 7. Database Schema

```sql
CREATE TABLE slots (slot_id BIGINT PRIMARY KEY, doctor_id BIGINT NOT NULL, start_time TIMESTAMP NOT NULL, status VARCHAR(20));
CREATE TABLE appointments (
  appointment_id BIGINT PRIMARY KEY, patient_id BIGINT NOT NULL, slot_id BIGINT NOT NULL,
  status VARCHAR(20) NOT NULL   -- SCHEDULED, COMPLETED, CANCELLED, NO_SHOW
);
```
Redis: `lock:slot:{slotId} -> holdId`, TTL = 5 min.

## 8. Detailed Queries

```lua
if redis.call('SET', KEYS[1], ARGV[1], 'NX', 'EX', 300) then return 1 end
return 0
```
```sql
INSERT INTO appointments (appointment_id, patient_id, slot_id, status) VALUES (?, ?, ?, 'SCHEDULED');
```

## 9. Read/Write Paths

Identical shape to `movie-ticket-booking.md` §9: acquire the slot lock,
insert the durable hold, confirm, or let the TTL release it. The one
addition: on confirm, publish an event so `notification-system.md`'s
pipeline sends a reminder ahead of the appointment — a second real
example (alongside `notification-system.md`'s own dependency on
`rate-limiter.md`) of these designed systems composing with each other
instead of each reinventing what a sibling system already owns.

## 10. Scale Justification

Deliberately not the interesting part of this design — see section 1.
The mechanism proven under real contention in
`movie-ticket-booking.md` and `hotel-reservation-system.md` carries
over with headroom to spare at this system's actual load.

## Implementation Notes

_(none yet beyond the interactive trace linked above)_
