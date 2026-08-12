---
service_name: URL Shortner
grouping: Simple Cassandra Based Systems
status: Deep Dive Ready
labels: [cassandra, Redis]
sections_complete: 10
last_session: 2026-08-12
notion_url: TBD
---

**Diagram:** `systems/diagrams/url-shortner.drawio` (single page —
architecture; no async flow, and see section 3 for why the state
diagram is nearly trivial)

**Interactive trace:** `systems/implementations/url-shortner-trace.html`
— a batch ID allocation, a create, a cache-miss redirect, then a
cache-hit redirect for the same link

## 1. Requirement Gathering

**Functional**
- Create a short code for a long URL (optionally a custom alias,
  optionally an expiration).
- Resolve a short code back to its long URL via redirect.

**Non-functional**
- Extremely read-heavy: redirects vastly outnumber creates, easily
  100:1 or more in practice.
- Redirect latency has to be very low — this sits directly in a user's
  click path, blocking page load.
- High availability — a broken shortener breaks every link built on it
  across the web, often long after whoever created the link is gone.
- Short codes must be globally unique with no collisions, generated
  without a synchronous bottleneck on every create.

## 2. Queries in Plain English

- Create a short code for a long URL.
- Resolve a short code to its long URL (redirect).

## 3. State Diagram

Mostly doesn't apply — a URL mapping is a static fact, not an entity
with a lifecycle, similar to `leaderboard.md`. The one real transition
is expiration, and it's a single edge, not worth a diagram:

```
ACTIVE → EXPIRED
```

## 4. API Endpoints

| Endpoint | Notes |
|---|---|
| `POST /shorten` | body: `{longUrl, customAlias?, expiresAt?}` → `{shortCode, shortUrl}` |
| `GET /{shortCode}` | 301/302 redirect to the long URL |

## 5. Concurrency Requirements

**The real problem is ID generation, not the redirect path** — reads
are pure lookups with no contention at all.

**Short code minting without a synchronous bottleneck:** a naive
"generate random code, check if taken, retry on collision" approach
degrades as the namespace fills up. The mechanism used here is **batch
ID allocation**: each app server periodically reserves a range of IDs
(e.g. 10,000 at a time) from a central counter via a single atomic
operation, then mints short codes from that local range by base62-encoding
each ID — no coordination needed per individual create, only per batch
exhaustion. This is the same "amortize the coordination cost across
many operations" idea behind Rate Limiter's Lua scripts, applied to ID
minting instead of a counter check.

**Custom alias collisions:** unlike auto-generated codes, a
user-requested alias might already be taken. This needs an actual
uniqueness check — a Cassandra lightweight transaction
(`INSERT ... IF NOT EXISTS`) makes the check-and-insert atomic instead
of a separate read-then-write.

## 6. Database Choice + Justification

- **URL mappings → Cassandra.** The access pattern is about as simple
  as it gets — get-by-`short_code`, nothing else, no joins, no
  secondary queries — and the write pattern (many independent creates,
  each touching one partition) is exactly Cassandra's shape. This
  matches the grouping this system is filed under in the tracker.
- **Redis cache in front, cache-aside.** Given redirects vastly
  outnumber creates and latency is the whole point of this system, the
  hottest links should never round-trip to Cassandra at all — a cache
  hit resolves in microseconds, and only a cold/rare link falls through
  to the database.
- **ID counter/batch allocation** can live in Cassandra too (a small
  lightweight-transaction-guarded counter row), avoiding a separate
  piece of infrastructure just for this.

## 7. Database Schema

**Cassandra**
```sql
CREATE TABLE url_mappings (
  short_code  TEXT PRIMARY KEY,
  long_url    TEXT,
  created_at  TIMESTAMP,
  expires_at  TIMESTAMP,
  status      TEXT           -- ACTIVE, EXPIRED
);

CREATE TABLE id_batches (
  batch_owner TEXT PRIMARY KEY,
  next_id     BIGINT
);
```

**Redis**
```
short:{shortCode} -> longUrl   TTL tuned to popularity (or omitted for permanent links)
```

## 8. Detailed Queries

```sql
-- reserve a batch of 10,000 IDs (lightweight transaction, one per batch, not per create)
UPDATE id_batches SET next_id = next_id + 10000 WHERE batch_owner = 'app-server-1' IF EXISTS;

-- create (auto-generated code — no collision possible, ID space is reserved)
INSERT INTO url_mappings (short_code, long_url, created_at, expires_at, status)
VALUES (?, ?, now(), ?, 'ACTIVE');

-- create (custom alias — needs the atomic uniqueness check)
INSERT INTO url_mappings (short_code, long_url, created_at, expires_at, status)
VALUES (?, ?, now(), ?, 'ACTIVE') IF NOT EXISTS;

-- resolve
SELECT long_url, status, expires_at FROM url_mappings WHERE short_code = ?;
```

## 9. Read/Write Paths

**Write path:** app server mints a short code from its locally-reserved
ID batch (base62-encoded), or validates a custom alias via
`IF NOT EXISTS` → inserts into Cassandra → returns the short URL. No
per-create coordination for the common (auto-generated) case.

**Read path:** request hits `/{shortCode}` → check Redis cache first →
on hit, redirect immediately (Cassandra never touched) → on miss, query
Cassandra, check `status`/`expires_at`, populate the cache, then
redirect. An `EXPIRED` or missing mapping returns 404/410 instead of a
redirect.

## 10. Scale Justification

Target: a link with a burst of viral traffic — tens of thousands of
redirects/sec for a handful of hot codes, alongside a steady background
rate of new-link creation.

- **Read path:** with redirects at 100:1 or higher over creates, a
  Redis cache easily absorbs the overwhelming majority of traffic — the
  hottest handful of links account for a disproportionate share of all
  redirects, and those are exactly the ones guaranteed to be cache-hot.
- **Cassandra read scale (cache misses):** linear with node count, and
  cache-miss volume is a small fraction of total traffic by design.
- **Write path:** batch ID allocation means the vast majority of
  creates involve zero coordination — only a rare batch-exhaustion
  event touches the shared counter, so write throughput scales with the
  number of app servers, not against a shared bottleneck.

## Implementation Notes

_(none yet beyond the interactive trace linked above)_
