---
service_name: Uber find nearby driver
grouping: Location Based Systems
status: Deep Dive Ready
labels: [cassandra, Redis]
sections_complete: 10
last_session: 2026-08-12
notion_url: TBD
---

**Diagram:** `systems/diagrams/uber-find-nearby-driver.drawio` (page 1:
architecture; page 2: driver status state diagram)

**Interactive trace:** `systems/implementations/uber-find-nearby-driver-trace.html`
— a driver's location pings landing in Redis while a rider searches
nearby, and what a stale/offline driver looks like

## 1. Requirement Gathering

**Functional**
- Drivers report live GPS location on a short interval (every 4-5
  seconds while online).
- Riders query for available drivers within a radius of a point.
- Track driver status: offline / online (available) / on-trip.

**Non-functional**
- Massive write volume: millions of drivers, each pinging every few
  seconds — this is a sustained firehose, not a burst.
- Proximity queries must be low-latency (sub-second) — this is an
  interactive "show me the map" UX, not a batch report.
- Location freshness within a few seconds is entirely acceptable — this
  is squarely a low-stakes-consistency problem, like watch progress in
  `netfilx.md`, not an inventory-count problem.
- Only *current* location matters for this query — location history is
  a separate analytics concern, out of scope here.

## 2. Queries in Plain English

- Update a driver's current location.
- Update a driver's status (online/offline/on-trip).
- Find available drivers within a radius of a point.

## 3. State Diagram

```
OFFLINE → ONLINE (available) ⇄ ON_TRIP
             ↓
          OFFLINE
```

## 4. API Endpoints

| Endpoint | Notes |
|---|---|
| `POST /drivers/{driverId}/location` | body: `{lat, lng}`, called every 4-5s while online |
| `POST /drivers/{driverId}/status` | body: `{status}` |
| `GET /riders/nearby-drivers?lat=&lng=&radiusKm=` | |

## 5. Concurrency Requirements

**Location writes:** overwrite semantics are correct here — a driver's
newest ping simply replaces the old one, no read-then-write race to
worry about, same reasoning as watch progress.

**The actual hard problem is the read side: efficient proximity
search.** A naive "scan every driver, compute distance" doesn't scale
past a trivial fleet size. The real solution is a spatial index —
**geohashing**, which encodes latitude/longitude into a string where
nearby points share prefixes, turning "find things near me" into a
range query instead of a full scan. Redis's `GEOADD`/`GEOSEARCH`
commands implement exactly this (a geohash-encoded sorted set under the
hood), which is why they're the practical choice here. (Uber's actual
production system uses their own H3 hexagonal grid, a more
sophisticated relative of the same idea — geohashing is the
implementable version of the same concept for this design.)

**Hot-region concern:** a single Redis key holding every driver
globally would concentrate all writes and reads on one node — mitigate
by sharding the geo-index per region/city (section 10), not by
over-engineering the query itself.

## 6. Database Choice + Justification

- **Live location index → Redis (`GEOADD`/`GEOSEARCH`).** Ephemeral by
  nature (only the current position matters), needs to support both
  very high write throughput and fast radius queries — Redis's native
  geospatial commands are purpose-built for exactly this.
- **Driver profile + status → Cassandra.** Millions of drivers
  transitioning status, high write volume, a simple, known access
  pattern (by `driver_id`) — the same shape as `notification_log` and
  `watch_progress` elsewhere in this repo. This is the durable record;
  Redis's geo-index is deliberately *not* the source of truth for
  anything beyond "where is this driver right now."

## 7. Database Schema

**Redis**
```
GEO set:  drivers:geo:{regionId}      member = driverId, geo-encoded lat/lng
Hash:     driver:{driverId}:meta      { status, lastSeenAt }
```

**Cassandra**
```sql
CREATE TABLE drivers (
  driver_id      BIGINT PRIMARY KEY,
  status         TEXT,             -- OFFLINE, ONLINE, ON_TRIP
  last_status_at TIMESTAMP,
  region_id      TEXT
);
```

## 8. Detailed Queries

```
GEOADD drivers:geo:sf -122.419 37.774 driver-88
HSET driver:driver-88:meta status ONLINE lastSeenAt 1755000000

GEOSEARCH drivers:geo:sf FROMLONLAT -122.42 37.77 BYRADIUS 3 km ASC COUNT 20
```
```sql
UPDATE drivers SET status = 'ONLINE', last_status_at = now() WHERE driver_id = 'driver-88';
```

## 9. Read/Write Paths

**Write path:** driver app pings location every 4-5s → `GEOADD` upserts
the position in the region's geo-set, and the meta hash's `lastSeenAt`
refreshes. Status changes (going online/offline/on-trip) also write
through to Cassandra — but the high-frequency location pings themselves
never touch Cassandra, only Redis; syncing every single ping to a
durable store would be pure overhead for data that's obsolete within
seconds anyway.

**Read path:** rider requests nearby drivers → `GEOSEARCH` against that
region's geo-set returns candidates sorted by distance → results are
filtered against each candidate's `status` in the meta hash (or a
maintained "currently online" set) so a driver who just went `ON_TRIP`
or stale-offline doesn't show up as available.

## 10. Scale Justification

Target: a major metro area, hundreds of thousands of concurrently
online drivers, each pinging every 4-5 seconds.

- **Write throughput:** `GEOADD` is O(log N); even at tens of thousands
  of writes/sec for one region, a single Redis node handles this
  comfortably — geospatial writes are cheap compared to, say, the
  atomic Lua scripts elsewhere in this repo.
- **Sharding by region, not globally:** a single global geo-set would
  put every write and every query through one key — sharding
  `drivers:geo:{regionId}` per city/region keeps each shard's member
  count bounded and lets regions scale independently, which also
  matches reality: a rider in San Francisco never needs a driver in
  Tokyo considered in their radius search.
- **Staleness handling:** `lastSeenAt` lets the read path exclude
  drivers who've gone quiet (app crashed, phone died) without waiting
  for an explicit offline signal — a driver silent for more than ~30s
  is filtered out even if their status still says `ONLINE`.

## Implementation Notes

_(none yet beyond the interactive trace linked above)_
