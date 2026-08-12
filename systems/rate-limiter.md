---
service_name: Rate Limiter
grouping: Rate Limiter
status: Deep Dive Ready
labels: [Redis, SQL]
sections_complete: 10
last_session: 2026-08-12
notion_url: TBD
---

## 1. Requirement Gathering

**Functional**
- Multi-tenant: different companies (clients) use this service to
  rate-limit traffic to their own APIs — this is a shared platform
  service, not single-tenant.
- **Standalone service.** Other services call it synchronously via a
  `/check` API to ask "is this request allowed?" — not an embedded
  library. Trade-off accepted: every check is a real network hop added
  to the caller's request path, on top of the Redis round trip the
  limiter itself does (two hops in the latency budget, not one — see
  section 10).
- **Config-driven, per client + API.** For each (client, API) pair, a
  rule specifies: which algorithm to use (Fixed Window, Sliding Window
  Log, Sliding Window Counter, or Token Bucket), the limit, the window
  size or refill rate, and which identity dimension(s) to key on
  (API key, user ID, IP, or a combination).
- **Service-to-service auth.** Every check call carries the calling
  client's own API key so the limiter knows whose config to apply. This
  is a distinct concept from the end-user identity being rate-limited
  *within* that client's traffic — a client authenticates itself with
  one key, then tells the limiter which of its own users/IPs/keys to
  check against the rule.
- **On breach: hard reject with HTTP 429**, with `X-RateLimit-Limit`,
  `X-RateLimit-Remaining`, and `Retry-After` information. No
  queueing/throttling — this is a fast allow/deny decision service, not
  a traffic shaper. (Decided without stopping to ask, per this
  session's direction — a real product could add queueing as a
  separate concern layered on top, but it's out of scope here.)
- Admin/config API to create, update, and disable rate limit rules per
  client + API.

**Non-functional**
- Hot-path latency: target single-digit-ms p99 for the limiter's own
  processing (excludes the caller's network hop to reach it).
- High throughput: shared across every onboarded client's combined
  traffic — must scale horizontally, not per-client.
- Consistency on counters: concurrent requests for the same identity
  must not race past the limit (the central concurrency problem here —
  see section 5).
- **Fail-open by default, configurable per rule.** If Redis is
  unavailable, the default is to let traffic through rather than block
  every client's downstream traffic for a cache outage — availability
  of clients' core business traffic outweighs perfect enforcement in
  the general case. Security-sensitive rules (e.g. login-attempt
  throttling) can opt into fail-closed per rule.
- Config changes should propagate within seconds, not real-time-critical
  — this path is far lower-frequency than the check path itself.

**Out of scope:** traffic shaping/queueing, DDoS-specific mitigation,
billing/metering (related but distinct from enforcement).

## 2. Queries in Plain English

**Client-facing (called by other services)**
- Check whether a request is allowed for a given identity under a
  given client + API's rule, and if not, how long until it's allowed
  again.

**Admin / internal**
- Create a rate limit rule for a client + API.
- Update a rule (limit, window, algorithm, etc.).
- Disable/delete a rule.
- List current rules for a client (dashboard/audit).
- (Internal, not client-facing) Refresh a client's cached rules when
  they change.

## 3. State Diagram

A rich state machine doesn't apply to the core operation here — every
`/check` call is a fresh, immediate ALLOW/DENY decision computed from
current counter state, not a multi-step entity lifecycle. The two
places state genuinely exists:

- A **rule** has a simple lifecycle: `ACTIVE ⇄ DISABLED → DELETED`.
- A **token bucket's** tokens/last-refill are continuous numeric state,
  recomputed on every check — not a discrete state transition table.

```
Rule:  ACTIVE ⇄ DISABLED → DELETED
```

Per the framework: this simplicity is itself a signal — a `status`
column on the rule entity is enough, no dedicated state-transition
table needed.

## 4. API Endpoints

**Client-facing** (service-to-service, authenticated via API key header)
| Endpoint | Notes |
|---|---|
| `POST /v1/check` | `X-Service-Api-Key` header; body: `{ apiId, identity: { type, value } }` (or an array of dimensions if the rule uses more than one). Returns 200 `{allowed:true, limit, remaining, resetAt}` or 429 `{allowed:false, limit, remaining:0, retryAfterSeconds}` |

**Admin** (rule management, stronger auth than the check path)
| Endpoint | Notes |
|---|---|
| `POST /v1/admin/clients/{clientId}/rules` | create a rule |
| `PUT /v1/admin/clients/{clientId}/rules/{ruleId}` | update a rule |
| `DELETE /v1/admin/clients/{clientId}/rules/{ruleId}` | disable/delete |
| `GET /v1/admin/clients/{clientId}/rules` | list current rules |

**Internal** (not a public endpoint — Redis pub/sub channel, see
section 9) — cache-invalidation broadcast when a rule changes.

## 5. Concurrency Requirements

**User-request-level serialization:** doesn't map cleanly onto this
system the way "duplicate checkout" does elsewhere — but a burst of
concurrent `/check` calls for the *same* identity is the everyday case,
not an edge case, so it's really the whole ballgame here.

**Resource-level contention — the central problem:**
- Classic race: two concurrent checks for the same identity both read
  "count = 9, limit = 10", both decide ALLOW, both increment — result:
  count = 11, over the limit. Every algorithm here must close this gap
  with a single atomic operation, never read-then-write:
  - **Fixed Window:** `INCR` is atomic by itself; the only subtlety is
    setting the TTL exactly once (on the first increment) — done via a
    tiny Lua script so INCR and the conditional EXPIRE happen as one
    unit, avoiding a crash-between-the-two-calls gap.
  - **Sliding Window Log:** needs evict-expired, count, and
    conditionally-add to happen as one atomic Lua script — otherwise
    two concurrent requests can both observe "under limit" before
    either one adds its entry.
  - **Token Bucket:** needs refill-computation and decrement to happen
    as one atomic Lua script, same reasoning.
  - Same underlying lesson as the Lua reservation script in
    `concepts/flash-sale-scaling.md` — atomic script execution instead
    of a lock, applied to a different resource.
- **Hot identity:** a single very high-traffic API key or IP creates a
  hot Redis key — same shape as the hot-SKU problem in flash sale
  scaling. Worth naming, but not over-solving by default: a single
  Redis key's `INCR`/Lua-script throughput is very high (it's one
  in-memory operation), so sharding the counter is a mitigation to
  reach for only if a specific identity's traffic actually saturates
  one key in practice — not a default for every rule.
- **Config reads** are pure reads shared across many concurrent checks
  — no contention, just cache aggressively (section 6/9).

## 6. Database Choice + Justification

- **Counter/log state → Redis.** Needs sub-millisecond shared state
  across every rate-limiter instance (so the same client's limit is
  enforced consistently no matter which instance handles a given
  request), atomic multi-step operations via Lua, and native TTL so
  window/bucket state self-cleans. No other store combines all of that
  as well for this workload.
- **Rule/client config → PostgreSQL, cached in Redis.** Config changes
  are rare relative to how often they're read (every single check).
  SQL as the durable source of truth gives real persistence and audit
  history without leaning on Redis for "the only copy of a client's
  business-critical config" — Redis's persistence story is tuned for
  hot ephemeral state, not that role. Redis then holds a read-through
  cache of each client's active rules, refreshed on write (section 9),
  so the hot check path never waits on a SQL round trip.
- **Service API keys** live in the same SQL store, hashed at rest, also
  cached in Redis for fast per-request auth lookups.

## 7. Database Schema

**SQL**
```sql
CREATE TABLE clients (
  client_id    BIGINT PRIMARY KEY,
  name         VARCHAR(200) NOT NULL,
  api_key_hash VARCHAR(128) NOT NULL,
  status       VARCHAR(20) NOT NULL,   -- ACTIVE, SUSPENDED
  created_at   TIMESTAMP NOT NULL
);
CREATE UNIQUE INDEX idx_clients_api_key_hash ON clients(api_key_hash);

CREATE TABLE rate_limit_rules (
  rule_id         BIGINT PRIMARY KEY,
  client_id       BIGINT NOT NULL REFERENCES clients(client_id),
  api_id          VARCHAR(100) NOT NULL,
  algorithm       VARCHAR(30) NOT NULL,  -- FIXED_WINDOW, SLIDING_WINDOW_LOG, SLIDING_WINDOW_COUNTER, TOKEN_BUCKET
  limit_count     INT NOT NULL,
  window_seconds  INT,                    -- window-based algorithms
  refill_rate     DECIMAL(10,2),          -- tokens/sec, TOKEN_BUCKET
  bucket_capacity INT,                    -- TOKEN_BUCKET
  identity_dims   JSONB NOT NULL,         -- e.g. ["api_key"], ["ip"], ["api_key","ip"]
  fail_mode       VARCHAR(10) NOT NULL DEFAULT 'OPEN',  -- OPEN or CLOSED
  status          VARCHAR(20) NOT NULL,   -- ACTIVE, DISABLED
  created_at      TIMESTAMP NOT NULL,
  updated_at      TIMESTAMP NOT NULL
);
CREATE INDEX idx_rules_client_api ON rate_limit_rules(client_id, api_id);
```

**Redis** (key naming per algorithm, not a fixed table)
```
Fixed Window:
  key:   rl:fw:{clientId}:{apiId}:{identityValue}:{windowStartTs}
  value: integer counter                      TTL: window_seconds

Sliding Window Log:
  key:   rl:swl:{clientId}:{apiId}:{identityValue}
  type:  sorted set (member = request id, score = timestamp ms)
                                                TTL: window_seconds (refreshed per write)

Sliding Window Counter (approximation):
  key:   rl:swc:{...}:{currentWindow} / {previousWindow}
  value: integer counters; weighted sum computed at read time

Token Bucket:
  key:   rl:tb:{clientId}:{apiId}:{identityValue}
  type:  hash { tokens: float, lastRefillMs: integer }
                                                TTL: a few multiples of refill period (idle cleanup)

Config cache:
  rl:cfg:client:{apiKeyHash}       -> client_id, status   (auth lookup)
  rl:cfg:rules:{clientId}:{apiId}  -> JSON array of active rules
```

## 8. Detailed Queries

**Check — Fixed Window (Lua, atomic):**
```lua
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])  -- window_seconds
end
return current
```

**Check — Sliding Window Log (Lua, atomic):**
```lua
local now, window, limit = tonumber(ARGV[1]), tonumber(ARGV[2]), tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, now - window * 1000)
local count = redis.call('ZCARD', KEYS[1])
if count < limit then
  redis.call('ZADD', KEYS[1], now, ARGV[4])  -- unique request id
  redis.call('EXPIRE', KEYS[1], window)
  return 1
end
return 0
```

**Check — Token Bucket (Lua, atomic):**
```lua
local capacity, now, refillRate, idleTtl = tonumber(ARGV[1]), tonumber(ARGV[2]), tonumber(ARGV[3]), tonumber(ARGV[4])
local tokens = tonumber(redis.call('HGET', KEYS[1], 'tokens') or capacity)
local lastRefill = tonumber(redis.call('HGET', KEYS[1], 'lastRefillMs') or now)
local elapsed = (now - lastRefill) / 1000
tokens = math.min(capacity, tokens + elapsed * refillRate)
local allowed = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
end
redis.call('HSET', KEYS[1], 'tokens', tokens, 'lastRefillMs', now)
redis.call('EXPIRE', KEYS[1], idleTtl)
return allowed
```

**Config lookup (cache-first):**
```
GET rl:cfg:client:{apiKeyHash}          -- who is calling
GET rl:cfg:rules:{clientId}:{apiId}     -- which rule(s) apply
-- on cache miss:
SELECT * FROM clients WHERE api_key_hash = ?;
SELECT * FROM rate_limit_rules WHERE client_id = ? AND api_id = ? AND status = 'ACTIVE';
```

**Admin — create a rule:**
```sql
INSERT INTO rate_limit_rules (rule_id, client_id, api_id, algorithm, limit_count,
  window_seconds, refill_rate, bucket_capacity, identity_dims, fail_mode, status, created_at, updated_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', now(), now());
```

## 9. Read/Write Paths

**Check path (hot path):**
1. Calling service → `POST /v1/check` with its service API key and the
   identity to check.
2. Auth lookup: `GET rl:cfg:client:{apiKeyHash}` — Redis cache hit the
   overwhelming majority of the time; SQL fallback + repopulate on miss.
3. Rule lookup: `GET rl:cfg:rules:{clientId}:{apiId}` — same cache-first
   pattern.
4. Build the Redis key per the rule's algorithm + identity dimension(s),
   run that algorithm's Lua script (section 8) — one atomic round trip.
5. Return ALLOW (200, with remaining/limit/resetAt) or DENY (429, with
   retryAfterSeconds).
6. If Redis is unreachable at step 4: consult the rule's `fail_mode` —
   `OPEN` (default) returns ALLOW without blocking the caller; `CLOSED`
   returns DENY. Either way this is logged/alerted — a silent Redis
   outage should never go unnoticed even though traffic keeps flowing.

**Admin/config write path:**
1. Admin creates/updates a rule → SQL `INSERT`/`UPDATE` on
   `rate_limit_rules` (durable source of truth).
2. On success, publish a cache-invalidation event on a Redis pub/sub
   channel keyed by `{clientId}:{apiId}` so every rate-limiter instance
   drops/refreshes its cached copy within seconds.
3. The next `/check` call either hits the freshly-populated cache or
   falls through to SQL and repopulates it.

**Read path (admin dashboard):** plain `SELECT * FROM rate_limit_rules
WHERE client_id = ?` against a SQL read replica — this is a dashboard,
not the hot path, so it doesn't need Redis-level latency.

## 10. Scale Justification

Target (no scale number was given, so picking a realistic default for
a multi-tenant platform service): 50K checks/sec aggregate across all
onboarded clients.

- **Redis throughput:** each check is one Lua script execution plus
  1-2 cached config `GET`s. A single well-provisioned Redis node
  comfortably clears 100K+ simple ops/sec; a Redis Cluster sharded by
  `hash(clientId)` handles 50K/sec with real headroom, and keeps one
  hot client's traffic from starving another's shard.
- **Latency budget:** ~2 network hops (caller → rate limiter → Redis)
  plus one Lua script execution (sub-millisecond inside Redis). A
  single-digit-ms p99 target for the limiter's own processing is
  realistic — callers should still budget for their own hop to reach
  the limiter, the direct cost of choosing "standalone service" back in
  section 1.
- **Config cache hit ratio:** rules change rarely relative to read
  volume, so 99%+ Redis cache hit ratio on config lookups is realistic,
  keeping SQL load to a trickle (cache-miss repopulation + the admin
  dashboard).
- **High availability:** Redis runs as a cluster with replicas; a
  primary failover on one shard only affects that shard's clients, and
  fail-open (the default) turns a total Redis outage into "rate
  limiting temporarily not enforced" rather than "all downstream
  traffic blocked" — a deliberate trade-off, not an oversight.
- **Horizontal scaling of the service itself:** stateless — all state
  lives in Redis/SQL — so it scales by adding instances behind a load
  balancer with zero coordination between them.

## Implementation Notes

_(none yet — see `/implementation` for focused deep dives, e.g. the
token-bucket Lua script under load, or the config cache-invalidation
pub/sub wiring)_
