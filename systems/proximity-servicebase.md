---
service_name: Proximity ServiceBase
grouping: Location Based Systems
status: Deep Dive Ready
labels: [SQL]
sections_complete: 10
last_session: 2026-08-12
notion_url: TBD
---

**Diagram:** `systems/diagrams/proximity-servicebase.drawio` (single
page — geohash-prefix bounding box, then exact-distance refinement)

**Interactive trace:** `systems/implementations/proximity-servicebase-trace.html`
— a bounding-box query narrows millions of stores down to a handful
before a single Haversine calculation runs

## 1. Requirement Gathering

**Functional**
- A reusable "find points near a location" service for **relatively
  static** points of interest — stores, businesses, landmarks — not
  live-moving entities.

**Non-functional — why this isn't just `uber-find-nearby-driver.md`
again:** that system's points update every few seconds and tolerate
staleness; this one's points change rarely (a store doesn't move) but
callers often want to combine proximity with **rich relational
filtering** — category, rating, open-now, price range — the kind of
query a Redis geo set isn't built to answer alongside a distance
constraint. This system deliberately uses **SQL with a geohash column**
instead of Redis GEO, and this section exists to justify that
divergence rather than default to the mechanism already built
elsewhere in this repo.

## 2. Queries in Plain English

- Find points of interest near a location, optionally filtered by
  category/rating/other attributes.

## 3. State Diagram

Doesn't apply — points of interest are relatively static records, not
entities with a lifecycle.

## 4. API Endpoints

| Endpoint | Notes |
|---|---|
| `GET /places/nearby?lat=&lng=&radiusKm=&category=` | |

## 5. Concurrency Requirements

No meaningful write contention — writes (a business updating its
hours, a new store opening) are rare and don't collide. The design
problem here is entirely about **making a geospatial range query fast
in a relational engine**, in two steps:

1. **Geohash-prefix bounding box.** Each point stores a geohash string
   (a base32 encoding of lat/lng where nearby points share string
   prefixes). A B-tree index on that column turns "points roughly near
   this location" into a cheap prefix-range scan — `geohash LIKE
   '9q8yy%'` — instead of scanning the whole table computing distance
   for every row.
2. **Exact-distance refinement.** The bounding box over-includes (a
   geohash cell is a rectangle, not a circle, and points near a cell
   edge can be in an adjacent cell) — so the candidate set from step 1
   gets a precise Haversine distance calculation applied, and only
   points genuinely within the radius are kept.

This two-phase "cheap filter, then precise refine" shape mirrors
`google-maps.md`'s local-search-then-shortcut pattern in spirit: don't
pay the expensive, precise computation until a cheap index has already
thrown away the overwhelming majority of candidates.

## 6. Database Choice + Justification

**SQL, deliberately, not Redis GEO.** The justification is the access
pattern, not habit: this system's callers routinely want proximity
*combined with* relational filters (category, rating, business hours)
in one query — exactly what SQL's `WHERE` clause composes naturally
and a Redis geo set does not. Given writes are rare, SQL's relative
write cost compared to Redis is irrelevant here; what matters is query
expressiveness, and that favors SQL for this specific workload.

## 7. Database Schema

```sql
CREATE TABLE points_of_interest (
  poi_id    BIGINT PRIMARY KEY,
  name      VARCHAR(200),
  category  VARCHAR(50),
  rating    DECIMAL(2,1),
  lat       DOUBLE, lng DOUBLE,
  geohash   VARCHAR(12) NOT NULL
);
CREATE INDEX idx_poi_geohash ON points_of_interest(geohash);
```

## 8. Detailed Queries

```sql
-- step 1: cheap bounding-box filter via geohash prefix
SELECT poi_id, name, lat, lng FROM points_of_interest
WHERE geohash LIKE '9q8yy%' AND category = 'coffee';

-- step 2: exact-distance refine, application-side or via a Haversine expression
-- keep only rows where haversine(lat, lng, queryLat, queryLng) <= radiusKm
```

## 9. Read/Write Paths

**Read path:** compute the query point's geohash prefix at the target
precision → SQL query filters by prefix (and any relational
attributes) → application code (or a SQL Haversine expression) refines
the candidate set to the exact radius → return.

**Write path:** on insert/update, compute and store the geohash string
alongside lat/lng — a pure function of the coordinates, no
coordination needed.

## 10. Scale Justification

- **Index-driven, not full-scan:** the geohash prefix index does the
  heavy lifting — a query touches only the rows in and near the target
  cell, not the whole table, regardless of how many total points exist.
- **Low write volume** means this never needs Cassandra-style
  write-optimized storage — a normal SQL primary with a read replica
  or two comfortably serves this workload, since the actual bottleneck
  (if any) is read fan-out for popular areas, not write throughput.
- **When this stops being the right choice:** if points started
  updating every few seconds instead of rarely, this system should
  become `uber-find-nearby-driver.md` instead — the crossover point is
  entirely about write frequency and staleness tolerance, not query
  pattern.

## Implementation Notes

_(none yet beyond the interactive trace linked above)_
