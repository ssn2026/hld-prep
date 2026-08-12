---
service_name: Nearyby friends
grouping: Location Based Systems
status: Deep Dive Ready
labels: [Redis]
sections_complete: 10
last_session: 2026-08-12
notion_url: TBD
---

**Diagram:** `systems/diagrams/nearyby-friends.drawio` (single page —
geo query + authorization filter)

**Interactive trace:** `systems/implementations/nearyby-friends-trace.html`
— a friend visible during a 1-hour share window, invisible to a
non-friend the entire time, and gone automatically after it expires

## 1. Requirement Gathering

**Functional**
- Opt in to share live location with specific friends, for a bounded
  time window (e.g. "share for the next hour").
- Friends can see your location only while actively shared.

**Non-functional — the defining difference from
`uber-find-nearby-driver.md`:** a driver *wants* to be found by any
nearby rider; that's the default, desired behavior. Here, being found
by anyone other than an explicitly-authorized friend, even briefly, is
a real privacy failure, not a minor bug. The system's entire design has
to treat visibility as opt-in and revocable by default, not
opt-out.

## 2. Queries in Plain English

- Start sharing my location with a specific friend, for a duration.
- Stop sharing (explicit revoke).
- See a friend's location, if they're currently sharing with me.

## 3. State Diagram

```
Share session:  ACTIVE → EXPIRED (TTL) / REVOKED (explicit)
```

## 4. API Endpoints

| Endpoint | Notes |
|---|---|
| `POST /friends/{friendId}/share` | body: `{durationMinutes}` |
| `POST /friends/{friendId}/revoke` | |
| `GET /friends/{friendId}/location` | only succeeds if currently shared |

## 5. Concurrency Requirements

**Same geo mechanism as `uber-find-nearby-driver.md`, plus a mandatory
authorization filter in front of it.** A location read is a two-step
check, in this order:
1. Is there an **active, unexpired share session** from this friend to
   the requesting user? If not, stop — never even run the geo lookup.
2. Only then read the position from the Redis GEO set.

This ordering matters: authorization has to gate the query, not filter
its results after the fact — the same lesson as `uber-find-nearby-driver.md`'s
status filter, but here the failure mode of getting it backwards is a
privacy leak, not a stale search result.

**TTL as the primary revocation mechanism, not just a cleanup job.**
A share session's Redis key carries its own expiry
(`EXPIRE session:{sharer}:{friend} <durationSeconds>`) — when the
window ends, access disappears automatically, with no separate process
required to "remember" to revoke it. Explicit revoke is also supported
(delete the key early), but expiry is the default, always-on backstop.

## 6. Database Choice + Justification

- **Live location → Redis GEO set**, unchanged from
  `uber-find-nearby-driver.md` — same access pattern, same justification.
- **Share sessions/permissions → Redis**, TTL-native, exactly matching
  the "access expires automatically" requirement — a SQL table would
  need a separate expiry sweep; Redis's native TTL makes the desired
  behavior the default rather than something to build.

## 7. Database Schema

```
GEO set:  friends:geo    member = userId
Session:  session:{sharerId}:{friendId} -> "ACTIVE"   TTL = durationSeconds
```

## 8. Detailed Queries

```
SET session:U-A:U-B "ACTIVE" EX 3600      -- share for 1 hour
EXISTS session:U-A:U-B                     -- authorization check
GEOPOS friends:geo U-A                     -- only reached if authorized
```

## 9. Read/Write Paths

**Share path:** user starts sharing → `SET ... EX <duration>` creates
the session key with its own expiry.

**Read path:** friend requests the location → check
`EXISTS session:{sharer}:{requester}` → only on a hit, read the
position from the geo set → on a miss (never shared, revoked, or
expired), return not-authorized, without ever touching location data.

**Expiry path:** nothing to build — Redis's own TTL mechanism handles
it. This is the one system in this repo where "do nothing extra" is
the correct answer to "how does this get cleaned up."

## 10. Scale Justification

Bounded by social graph size, not population — a user shares with a
handful of friends, not the general public, so this system's real load
is orders of magnitude below `uber-find-nearby-driver.md`'s driver
fleet. The interesting property isn't scale, it's that the privacy
guarantee falls out of the data model itself (no session key = no
access) rather than needing separately-audited application logic.

## Implementation Notes

_(none yet beyond the interactive trace linked above)_
