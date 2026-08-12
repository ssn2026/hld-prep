---
service_name: Google Maps
grouping: Location Based Systems
status: Deep Dive Ready
labels: [SQL]
sections_complete: 10
last_session: 2026-08-12
notion_url: TBD
---

**Diagram:** `systems/diagrams/google-maps.drawio` (single page — tile
serving vs. routing, two entirely different problems)

**Interactive trace:** `systems/implementations/google-maps-trace.html`
— a tile served entirely from cache, and a route query that only
touches a tiny fraction of the road graph

## 1. Requirement Gathering

**Functional**
- Render map tiles for a viewport at a given zoom level.
- Compute directions/a route between two points.
- Search for places.

**Non-functional**
- Two workloads with almost nothing in common share this one product:
  tile serving (read-heavy, highly cacheable, static-ish content) and
  routing (a graph shortest-path computation that has to run in
  real-time per query, over a continent-scale graph). Treating them as
  one problem would be a mistake — this section exists to name that
  they're actually two systems wearing one API.

## 2. Queries in Plain English

- Get the map tile for `(zoom, x, y)`.
- Get a route between two points.
- Search for a place by name/category near a location.

## 3. State Diagram

Doesn't apply — tiles and routes are computed/served, not entities with
a lifecycle.

## 4. API Endpoints

| Endpoint | Notes |
|---|---|
| `GET /tiles/{zoom}/{x}/{y}.png` | pre-rendered, highly cacheable |
| `GET /directions?from=&to=` | real-time graph query |
| `GET /places/search?q=&near=` | |

## 5. Concurrency Requirements

**Tile serving is almost entirely a caching problem**, same shape as
`netfilx.md`'s video segments: tiles are pre-rendered at each zoom
level (a quadtree/tile-pyramid scheme — each tile at zoom Z covers a
fixed geographic area, keyed by `(zoom, x, y)`) and change only when
underlying map data is updated, which is rare relative to how often
they're requested.

**Routing is the genuinely hard problem**, and naive shortest-path
(plain Dijkstra over the full road graph) doesn't work at this scale —
a continent-sized graph has hundreds of millions of edges, far too
many to search per query in real time. Real systems use **Contraction
Hierarchies**: a precomputed hierarchy that identifies "important"
roads (highways) and adds shortcut edges representing "the fastest way
from A to B through this region is via this shortcut," computed once,
offline. At query time, the search only needs to explore a small local
neighborhood around each endpoint before jumping onto precomputed
shortcuts for the long middle stretch — turning what would be a
graph-wide search into one that touches a tiny, roughly constant
fraction of the total graph regardless of total map size.

## 6. Database Choice + Justification

- **Tiles → object storage + CDN**, identical pairing to `netfilx.md`'s
  video renditions — pre-rendered, mostly static, and the CDN is what
  actually carries the read volume.
- **Road graph → a specialized in-memory graph structure, not a
  general-purpose database.** This is deliberately not modeled as SQL
  or Cassandra rows — the contraction-hierarchy structure and its
  precomputed shortcuts are purpose-built for the shortest-path access
  pattern, sharded by geography across routing-service instances that
  hold their region's graph (plus a thin layer of long-range shortcuts)
  in memory for query speed.
- **Place search metadata → SQL**, ordinary relational data (name,
  category, coordinates) with a search index layered on top, same
  reasoning as `netfilx.md`'s catalog.

## 7. Database Schema

```sql
CREATE TABLE places (place_id BIGINT PRIMARY KEY, name VARCHAR(200), category VARCHAR(50), lat DOUBLE, lng DOUBLE);
```
Tiles: object storage, keyed by `{zoom}/{x}/{y}`, no relational schema.
Road graph: in-memory adjacency structure with precomputed shortcut
edges, rebuilt periodically as map data updates, not a live-write store.

## 8. Detailed Queries

```sql
SELECT * FROM places WHERE category = ? AND lat BETWEEN ? AND ? AND lng BETWEEN ? AND ?;
```
Routing has no "query" in the SQL sense — it's an in-memory graph
search using the precomputed hierarchy, described in section 5.

## 9. Read/Write Paths

**Tile path:** client requests `(zoom, x, y)` → CDN cache hit the
overwhelming majority of the time → object storage only on a cold
miss, same pattern as `netfilx.md` §9.

**Route path:** client requests a route → Routing Service instance
holding the relevant geographic partition (plus shared long-range
shortcuts) runs the contraction-hierarchy query → returns the path
without ever touching the full graph.

## 10. Scale Justification

- **Tiles are even more cacheable than video** — low-zoom tiles cover
  huge geographic areas and are requested by nearly everyone who ever
  views that region, concentrating demand onto a small, extremely hot
  set of tiles; the CDN absorbs essentially all of this.
- **Routing scales because contraction hierarchies bound query cost
  independent of total map size** — the whole point of precomputing
  shortcuts is that a route query's search space doesn't grow with the
  size of the underlying graph, only with the local density near each
  endpoint. Geographic sharding of the graph across routing instances
  adds horizontal scale on top of that.

## Implementation Notes

_(none yet beyond the interactive trace linked above)_
