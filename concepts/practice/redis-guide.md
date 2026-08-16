---
concept_name: Redis Concepts (Practice Guide)
linked_systems: [Movie Ticket Booking, Hotel ReservationSyste, Rate Limiter, Flight Ticket Booking, Doctor Appointment, Redis As cache, LeaderBoard, Like and Comment Service, URL Shortner, Uber find nearby driver, Nearyby friends, News Feeds, Chat Systems, Whatsapp User Socket info, Broadcasting System]
last_reviewed: 2026-08-16
freshness: Fresh
notion_url: TBD
---

# Redis Concepts — Practice Guide

**Question bank:** `concepts/practice/redis-question-bank.md`

**Audit note:** `stock-broker.md` carries the `Redis` label in
`docs/TRACKER.md` but has no actual Redis usage in its body — the order
book is in-memory per matching-engine instance, the ledger is SQL,
market data is Cassandra. Worth a revisit if that system is ever
reopened; not treated as a source for this guide.

## 1. Distributed Locking — SET NX PX, Fencing Tokens & the Redlock Debate

The repo's single most-reused Redis pattern: `SET lock:<resource> <token>
NX PX <ttl>` to acquire, a compare-and-delete Lua script (`GET == token
then DEL`) to release safely — never a bare `DEL`, which could delete a
lock someone else acquired after your TTL expired. `movie-ticket-booking.md`
is the canonical writeup: it names the exact gap this leaves open (a
paused holder past its TTL can lose exclusivity without knowing it, and
a "rigorous fix" needs a **fencing token** — a monotonically increasing
number checked by the downstream resource, not just the lock itself),
and explicitly rejects Redlock ("Kleppmann's critique... doesn't
actually guarantee mutual exclusion") and ZooKeeper in favor of plain
Redis for "operational simplicity." `hotel-reservation-system.md`
generalizes the same primitive to a multi-key hold (one lock per
room-night, "attempt-all-atomically, roll back whatever succeeded if any
fails"); `flight-ticket-booking.md` and `doctor-appointment.md` reuse it
unchanged at different scales, reinforcing that the mechanism doesn't
relax just because contention is lower.

## 2. TTL as a Primary Mechanism, Not Just Cache Expiry

Most systems treat TTL as a housekeeping detail; `nearyby-friends.md`
and `whatsapp-user-socket-info.md` use it as the actual **authorization
and liveness mechanism** — `session:{sharerId}:{friendId}` with `EX
<duration>` means "access disappears automatically," no separate
revocation code path or sweep job needed. `whatsapp-user-socket-info.md`
states this directly: "no separate sweep job needed... Redis's native
per-key TTL handles expiry automatically." The pattern requires
heartbeat-refresh (`conn:{userId}:{deviceId}`, refreshed on every
heartbeat) so a live connection's key never actually expires, only a
dead one's does.

## 3. Caching Patterns — Cache-Aside, Write-Through, Write-Behind

`redis-as-cache.md` is this repo's pattern-level treatment: cache-aside
(check cache → miss → read source → populate cache) is the repo default
"precisely because it never risks being the only copy of anything,"
contrasted explicitly with write-through (pays the dual-write cost on
every write, even keys never read again) and write-behind ("a cache
failure before the flush loses data that was never actually durable" —
rejected outright for anything that must not be lost). `url-shortner.md`'s
`short:{code}` cache in front of Cassandra and `rate-limiter.md`'s
`rl:cfg:*` rule cache are both named as concrete cache-aside instances
already built elsewhere in this repo.

## 4. Cache Stampede Protection

When a hot key expires, many concurrent requests can all miss at once
and all hammer the source simultaneously. `redis-as-cache.md`'s fix
reuses Concept 1's exact lock primitive for a different problem:
`SET lock:repop:{key} 1 NX PX 2000` — only the request that wins the
lock repopulates the cache; the rest either wait briefly and re-check,
or (for a system tolerant of brief staleness) serve the just-expired
value while repopulation happens in the background.

## 5. Rate Limiting Algorithms

`rate-limiter.md` implements all four standard algorithms, each with a
different Redis shape: **Fixed Window** — a STRING counter keyed by
`rl:fw:{clientId}:{apiId}:{identityValue}:{windowStartTs}`, incremented
via `INCR`+`EXPIRE` inside one Lua script for atomicity. **Sliding
Window Log** — a ZSET (`ZADD` each request timestamp as score,
`ZREMRANGEBYSCORE` to evict anything outside the window, `ZCARD` to
count what's left). **Sliding Window Counter** — two STRING counters
(current window, previous window), weighted at read time to approximate
a sliding log without storing every timestamp. **Token Bucket** — a
HASH (`tokens`, `lastRefillMs`), refill computed in application logic
and written back via `HSET`. Every check runs as "one Lua script
execution... sub-millisecond inside Redis," and the design states an
explicit **fail-open/fail-closed** policy for when Redis itself is
unreachable: `fail_mode: OPEN` (default) lets traffic through,
`CLOSED` denies it — a deliberate availability-vs-correctness choice
made per API, not a hidden default.

## 6. Sorted Sets — Leaderboards & Atomic Conditional Scoring

`leaderboard.md`'s `ZSET leaderboard:{lbId}` (member = userId, score =
score) solves concurrent score updates without any external lock:
`ZADD leaderboard:{lbId} GT CH {score} {userId}` is atomic and
conditional — `GT` means "only apply if the new score is greater," so a
late, stale update can never overwrite a higher score that landed
first, with zero application-level locking. Queries (`ZREVRANGE` for
top-N or around-me windows, `ZREVRANK`, `ZSCORE`) are all O(log N) or
better, which is what makes sorted sets the right structure for
"ranked, frequently-updated" data generally, not just this one system.

## 7. Sets & Approximate Counters — Membership vs. Exact Count

`like-and-comment-service.md` splits one concept into two structures
for two different accuracy needs: a SET `post:{id}:likers`
(`SADD`/`SREM`/`SISMEMBER`) for the exact "did *this* user like it"
membership check, and a separate STRING counter `post:{id}:like_count`
(`INCR`/`DECR`) kept **approximate**, maintained alongside the set
rather than derived from it — explicitly "to avoid `SCARD`'s scan
cost" (a set's cardinality command isn't O(1) the way a maintained
counter is). The same split-by-accuracy-requirement discipline as the
SQL guide's Concept 1 example, just in Redis's data-structure
vocabulary instead of tables.

## 8. Geo Commands

`uber-find-nearby-driver.md` and `nearyby-friends.md` both use
`GEOADD`/`GEOSEARCH` (a geohash-encoded sorted set under the hood) for
"who's near this point" queries — `drivers:geo:{regionId}` sharded per
region specifically because a single global geo-set becomes a hot key
under load (the same one-key-can't-shard limitation Concept 11
generalizes). `nearyby-friends.md`'s addition: gating the geo lookup
behind Concept 2's TTL-based session check (`EXISTS session:... `
checked *before* `GEOSEARCH`, never the reverse) — location data is
useless without valid, current authorization to see it.

## 9. Lists — Fan-out-on-Write Feeds

`news-feeds.md`'s `feed:{userId}` is a capped LIST: `LPUSH
feed:{followerId} {postId}` on every new post from someone they follow,
immediately followed by `LTRIM feed:{followerId} 0 499` to bound the
list's size regardless of how long the user has followed people —
without the trim, a list keeps growing forever the same way an
unbucketed Cassandra partition would (the Cassandra guide's Concept 3).
Celebrity accounts explicitly skip this fan-out (too many followers to
write to on every post) and are merged in at read time from a pull
path instead — a hybrid push/pull design driven by follower-count, not
a fixed rule.

## 10. Atomicity via Lua Scripting (EVAL)

Nearly every multi-step Redis operation in this repo that needs to be
atomic runs as a Lua script, not as separate commands from the
application: the lock-release compare-and-delete (Concept 1), every
rate-limiter check (Concept 5, "read state, compute decision, write
state" as one script), and the fixed-window `INCR`+`EXPIRE` pairing.
The reason is the same one that motivates a single-statement SQL
`UPDATE ... WHERE` (SQL guide's Concept 5): a script executes as one
atomic unit on the Redis server, with no other client's commands able
to interleave between its steps — the alternative (separate
`GET`/compute-in-app/`SET` calls) reopens exactly the race the atomicity
was needed to close.

## 11. Redis Cluster — Sharding & Hot-Key Limits

Redis Cluster shards by hashing a key across nodes — but that means
**sharding happens between keys, never within one key's data**.
`leaderboard.md` names this limitation explicitly: "a Redis Cluster
shards by key, not by the members inside a single key... one giant
sorted set can't be spread across shards," worked around with regional
sub-leaderboards (`leaderboard:region:{r}`) merged periodically rather
than one global structure. `uber-find-nearby-driver.md`'s per-region
geo-sets and `whatsapp-user-socket-info.md`'s shard-by-`userId` key
design (keeping one user's devices co-located on one shard rather than
scattered) are the same constraint driving two different designs — the
question to always ask is "could this one key become a hot key no
single shard can handle?"

## 12. Unused in This Repo — Persistence, Pub/Sub, HyperLogLog

Three real Redis features no system here has needed: **Persistence**
(RDB snapshots / AOF log) — every Redis use in this repo is
either a cache with a durable source of truth behind it (Concept 3) or
inherently ephemeral state (connection registries, locks, geo pings)
that's fine to lose on a restart, so nothing here has required tuning
`appendonly`/`save` at all — Redis is never this repo's system of
record. **Pub/Sub** — `chat-systems.md` explicitly routes large-group
fan-out through **Kafka** instead of a Redis pub/sub channel once fan-out
gets wide, precisely because Redis pub/sub has no persistence or
replay for a subscriber that was briefly disconnected (a message
published while you're offline is simply gone) — a real limitation
worth knowing even though no system here leans on pub/sub directly.
**HyperLogLog** (`PFADD`/`PFCOUNT`, approximate cardinality in ~12KB
regardless of set size) — the closest this repo gets is
`click-event-aggregator.md`'s unique-visitor estimate, but that's
implemented as a HyperLogLog *inside the Kafka stream processor*, not
via Redis's `PFADD`; the underlying algorithm is the same, the storage
location differs.
