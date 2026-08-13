---
service_name: Redis As cache
grouping: (ungrouped)
status: Deep Dive Ready
labels: [Redis]
sections_complete: 10
last_session: 2026-08-12
notion_url: TBD
---

**Diagram:** `systems/diagrams/redis-as-cache.drawio` (single page —
cache-aside vs write-through vs write-behind, and the stampede lock)

**Interactive trace:** `systems/implementations/redis-as-cache-trace.html`
— a hot key expiring under load, with and without stampede protection

**This is the pattern-level treatment** of something already used
ad-hoc throughout this repo: `rate-limiter.md`'s config cache and
`url-shortner.md`'s redirect cache are both cache-aside without
naming it as such. This system names the pattern space explicitly and
covers the failure mode none of those systems had to face at their
actual scale: cache stampede.

## 1. Requirement Gathering

**Functional**
- Support the standard caching strategies in front of a primary
  datastore: cache-aside, write-through, write-behind.
- Protect the primary datastore from a stampede when a hot key expires.

**Non-functional**
- The cache must never become the *only* copy of data it wasn't
  designed to be the source of truth for — a cache that silently
  becomes load-bearing is a correctness bug waiting to surface at the
  worst time (a restart, a node failure).

## 2. Queries in Plain English

- Read a value (cache-aside: check cache, fall back to DB on miss).
- Write a value (strategy-dependent: through, behind, or aside).

## 3. State Diagram

Doesn't apply — a cache entry is present or absent, with a TTL, not an
entity with a lifecycle.

## 4. API Endpoints

Not really applicable — this is an internal pattern layered inside a
service (see every other system in this repo's Redis usage), not a
standalone product with its own API.

## 5. Concurrency Requirements

**Three strategies, three trade-offs:**

| Strategy | Read path | Write path | Trade-off |
|---|---|---|---|
| **Cache-aside** (used throughout this repo) | check cache → miss → read DB → populate cache | write DB, then invalidate (or update) cache | Simple, resilient — a cache failure just means more DB reads, never data loss |
| **Write-through** | same as cache-aside | write cache AND DB synchronously, together | Cache is always fresh, but every write pays both costs |
| **Write-behind** | same as cache-aside | write cache immediately, flush to DB asynchronously | Fastest writes, but a cache failure before the flush **loses data that was never actually durable** — a real risk, not a rounding error |

Cache-aside is the default used everywhere else in this repo precisely
because it never risks being the only copy of anything — the trade-off
(occasional extra DB reads on miss) is far cheaper than write-behind's
risk.

**Cache stampede, the failure mode worth naming explicitly.** A single
very popular key expires; the next instant, hundreds of concurrent
requests all miss simultaneously and all try to repopulate it from the
DB at once — a self-inflicted thundering herd the cache was supposed to
prevent. The fix: a short-lived **Redis lock specifically for cache
repopulation** — `SET lock:repop:{key} 1 NX PX 2000`. Only the request
that acquires the lock actually queries the DB and repopulates the
cache; every other concurrent miss either waits briefly and re-checks
the cache, or serves a slightly stale value if one is available. This
is the same `SET NX` primitive as `movie-ticket-booking.md`'s seat
lock, applied to a completely different problem — protecting the
database from load, not protecting a business resource from double
allocation.

## 6. Database Choice + Justification

Redis for the cache layer itself — fast, TTL-native, exactly the role
it plays in every other Redis-labeled system in this repo. The primary
datastore is whatever the wrapped system actually needs (SQL,
Cassandra) — this system is about the *pattern* sitting in front of
it, not a specific pairing.

## 7. Database Schema

Not applicable in the usual sense — cache keys are whatever shape the
wrapped system's access pattern calls for (see
`rate-limiter.md §7`'s `rl:cfg:*` keys, `url-shortner.md §7`'s
`short:{code}` keys, for concrete examples already in this repo).

## 8. Detailed Queries

```
-- cache-aside read
GET cache:{key}
-- on miss:
SELECT ... FROM primary_table WHERE id = ?;
SET cache:{key} <value> EX <ttl>

-- stampede-safe repopulation
SET lock:repop:{key} 1 NX PX 2000
-- only the winner queries the DB and repopulates; others wait/serve stale
```

## 9. Read/Write Paths

**Cache-aside read (the default):** check cache → on hit, return
immediately → on miss, read the primary store, populate the cache, then
return.

**Cache-aside write:** write the primary store → invalidate (or
directly update) the corresponding cache entry so the next read isn't
served stale data.

**Stampede-protected repopulation:** on a miss for a known-hot key,
attempt the repopulation lock before querying the DB → holder queries
and repopulates → everyone else either short-waits and re-reads the
now-warm cache, or serves the previous (slightly stale) value if the
wrapped system tolerates that.

## 10. Scale Justification

- **Cache-aside's resilience is itself the scale argument:** a Redis
  outage degrades to "every read now hits the DB" — painful, but not a
  cascading failure, unlike write-behind's actual data-loss risk under
  the same failure.
- **The stampede lock bounds worst-case DB load** to roughly one query
  per hot key per repopulation, regardless of how many thousands of
  concurrent requests missed at the same instant — this is exactly the
  scale property that matters for a viral/hot-key event, the same
  shape of problem `flash-sale-scaling.md` and `leaderboard.md`'s
  scaling sections both had to reason about, just applied to generic
  cache protection instead of a specific domain.

## Implementation Notes

_(none yet beyond the interactive trace linked above)_
