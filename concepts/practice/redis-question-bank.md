---
concept_name: Redis Question Bank (Practice)
linked_systems: [Movie Ticket Booking, Rate Limiter, LeaderBoard, Uber find nearby driver, News Feeds, Chat Systems]
last_reviewed: 2026-08-16
freshness: Fresh
notion_url: TBD
---

# Redis Question Bank

Progress persists as checkboxes below — resuming `/practice redis`
finds the first `[ ]` in document order. Guide:
`concepts/practice/redis-guide.md`.

## Concept 1: Distributed Locking — SET NX PX, Fencing Tokens & Redlock
_guide: redis-guide.md#1-distributed-locking--set-nx-px-fencing-tokens--the-redlock-debate_

### Q1 [core] — Safe lock release — [ ] not yet attempted
**Scenario:** `movie-ticket-booking.md`'s seat hold uses `SET
lock:seat:{showtimeId}:{seatId} {holdId} NX PX 600000` to acquire. A
naive release just runs `DEL lock:seat:{showtimeId}:{seatId}`.
**Question:** What's wrong with the naive release, and what's the
correct one?

<details><summary>Model answer</summary>

A bare `DEL` doesn't check *who* it's deleting the lock for. If the
original holder's operation ran slower than the TTL and the lock
already auto-expired, a **second** client may have already acquired
the same lock — the first client's late, naive `DEL` would then delete
the *second* client's legitimate lock, letting a third client acquire
it too, breaking mutual exclusion entirely. The correct release is a
compare-and-delete, run atomically as a Lua script so the check and the
delete can't be interleaved by another client:
```lua
if redis.call("GET", KEYS[1]) == ARGV[1] then
  return redis.call("DEL", KEYS[1])
else
  return 0
end
```
called with `KEYS[1] = lock:seat:...` and `ARGV[1] = holdId` — only
deletes if this client's own token is still the one holding the lock.
</details>

### Q2 [core] — The gap even a safe release doesn't close — [ ] not yet attempted
**Scenario:** Even with the correct compare-and-delete release from Q1,
`movie-ticket-booking.md`'s guide names a remaining gap: a lock holder
that pauses (GC pause, slow network) past the TTL.
**Question:** Describe the failure mode, and name the "rigorous fix."
Why did this repo choose not to implement it?

<details><summary>Model answer</summary>

If a holder pauses long enough for its lock's TTL to expire, Redis
releases the lock and a second client can legitimately acquire it and
start its own work — but when the first, paused client resumes, it has
no idea it lost the lock, and may still go on to perform the
seat-booking action believing it's still exclusive, racing the second
client's genuinely-held lock. Neither client did anything wrong in
isolation; the TTL alone can't distinguish "still working" from "dead."
The rigorous fix is a **fencing token**: a monotonically increasing
number handed out with the lock, which the *downstream resource itself*
(not just Redis) checks and rejects if a smaller/older token arrives
after a newer one already applied. This repo doesn't implement it
because the downstream write (the actual seat-confirmation `UPDATE`)
would need to be fencing-token-aware too, adding real complexity for a
failure mode judged rare enough, at this system's stakes, not to
justify it — a deliberate, named trade-off, not an oversight.
</details>

## Concept 2: TTL as a Primary Mechanism
_guide: redis-guide.md#2-ttl-as-a-primary-mechanism-not-just-cache-expiry_

### Q1 [core] — Revocation without a delete — [ ] not yet attempted
**Scenario:** `nearyby-friends.md`'s location-sharing feature needs "if
I stop sharing my location with a friend, their access disappears
automatically" without a background job hunting for expired shares.
**Question:** Design the key/TTL that achieves this, and explain why no
sweep job is needed.

<details><summary>Model answer</summary>
```
SET session:{sharerId}:{friendId} "ACTIVE" EX <shareDurationSeconds>
```
Every location lookup checks `EXISTS session:{sharerId}:{friendId}`
*before* running the geo query — if the sharer never explicitly revokes
access, the TTL alone guarantees the key disappears at the agreed time,
and the very next lookup simply finds no key and denies access. No
sweep job is needed because Redis's own key-expiry mechanism (checked
lazily on access, and actively by a background process) is what removes
the key — the application never has to notice "has this expired?"
itself; it only has to check "does this key currently exist?"
</details>

### Q2 [core] — TTL vs. heartbeat-refresh — [ ] not yet attempted
**Scenario:** `whatsapp-user-socket-info.md` stores `conn:{userId}:{deviceId}
-> serverId` with `EX 60`, refreshed by a heartbeat every 30 seconds
while the connection is alive.
**Question:** Why does a live connection's key need to be refreshed at
all — why not just set a very long TTL once at connect time?

<details><summary>Model answer</summary>

The whole point of the TTL here is to detect **dead** connections
without an explicit disconnect signal (a client can vanish — crash,
network drop — without ever sending a clean "goodbye"). A long TTL set
once would mean a dead connection's routing entry stays valid for that
entire long window, silently misrouting messages to a server the user
is no longer connected to. A short TTL, refreshed on every heartbeat
while the connection is genuinely alive, means the key expires quickly
(within one missed heartbeat interval) specifically when the client
stops proving it's still there — the TTL is being used as a **liveness
signal**, not just an eventual-cleanup mechanism, so it has to be short
and actively renewed to serve that purpose.
</details>

## Concept 3: Caching Patterns
_guide: redis-guide.md#3-caching-patterns--cache-aside-write-through-write-behind_

### Q1 [core] — Why cache-aside is the repo default — [ ] not yet attempted
**Scenario:** `redis-as-cache.md` picks cache-aside over write-through
and write-behind as the default pattern across this repo.
**Question:** Explain what each of the three patterns actually does on
a write, and why cache-aside's specific risk profile makes it the safe
default.

<details><summary>Model answer</summary>

**Cache-aside**: writes go straight to the source of truth; the cache
is only touched on reads (populate on miss, invalidate/update on
write) — Redis can be wiped entirely at any moment and the system
just sees a burst of cache misses, never data loss. **Write-through**:
every write goes to both the cache and the source synchronously — safe,
but pays the cost of writing to Redis on every single write, even for
keys that may never be read again. **Write-behind**: writes go to the
cache first and are flushed to the source asynchronously — fastest
writes, but "a cache failure before the flush loses data that was never
actually durable," meaning Redis briefly *is* the only copy of that
data. Cache-aside is the default specifically because it's the only one
of the three where Redis is never, even momentarily, the sole holder of
data that matters — the worst case is a slower read, never a lost
write.
</details>

### Q2 [core] — When write-through would actually be justified — [ ] not yet attempted
**Scenario:** Argue for a case where write-through's extra write cost
would be worth paying, in contrast to this repo's cache-aside default.
**Question:** What access pattern would justify it?

<details><summary>Model answer</summary>

Write-through earns its cost when a key is written once but read
**very** frequently and immediately after the write — e.g. a
just-published piece of content that a burst of readers hits within
milliseconds of the write. Under cache-aside, that burst would all miss
simultaneously right after the write (nothing populated the cache yet)
and all hit the source at once — exactly the cache-stampede scenario
Concept 4 addresses. Write-through sidesteps it structurally: the cache
is already warm the instant the write completes, because populating it
was part of the write itself, not deferred to the first read. The
trade-off is worth it specifically when "read immediately after write,
by many readers at once" is the expected pattern, not the exception.
</details>

## Concept 4: Cache Stampede Protection
_guide: redis-guide.md#4-cache-stampede-protection_

### Q1 [core] — Designing the stampede lock — [ ] not yet attempted
**Scenario:** A hot key backing a popular product page expires, and
five thousand concurrent requests all miss the cache within the same
50ms window.
**Question:** Design the fix using `redis-as-cache.md`'s stampede
pattern, and explain what the other 4,999 requests should do while one
repopulates.

<details><summary>Model answer</summary>
```
SET lock:repop:{key} 1 NX PX 2000
```
Only the request that successfully sets this lock (gets `true` back)
goes on to query the source and repopulate the real cache key; every
other concurrent miss gets `false` back and should **not** also query
the source. What they do instead depends on the system's staleness
tolerance: either wait a short beat and re-check the cache (the winner
will have populated it by then), or — for a system that can tolerate
brief staleness — serve the value that just expired (if it's still
retrievable, e.g. via a slightly-longer-lived stale copy) while
repopulation happens in the background. Either way, the lock's job is
purely to ensure only one request ever pays the source-query cost, no
matter how many concurrently missed.
</details>

### Q2 [core] — Stampede lock vs. the seat lock — [ ] not yet attempted
**Scenario:** Compare the stampede-protection lock (`lock:repop:{key}`)
to `movie-ticket-booking.md`'s seat lock (Concept 1) — both use `SET
... NX`.
**Question:** What's actually different about their purpose, even
though the primitive is identical?

<details><summary>Model answer</summary>

Same mechanism, different intent. The seat lock enforces **mutual
exclusion for correctness** — only one client may ever hold it at a
time, because letting two clients "win" would double-book a seat, a
real business-logic violation. The stampede lock enforces **mutual
exclusion for efficiency** — letting a second request also repopulate
the cache wouldn't be *wrong*, it would just be redundant work (the
source gets queried twice instead of once, both writes end up
agreeing). Losing the stampede lock's race costs a wasted query; losing
the seat lock's race costs a double-booked seat. Recognizing which kind
of problem you're solving matters because it changes how much
engineering effort (fencing tokens, TTL tuning, retry logic) the lock
actually deserves.
</details>

## Concept 5: Rate Limiting Algorithms
_guide: redis-guide.md#5-rate-limiting-algorithms_

### Q1 [core] — Fixed window's edge burst — [ ] not yet attempted
**Scenario:** `rate-limiter.md`'s Fixed Window algorithm allows 100
requests per minute, keyed by `rl:fw:{clientId}:{apiId}:{identityValue}:{windowStartTs}`.
**Question:** Describe the exact abuse case where fixed window lets
through nearly double the stated limit, and name which of the repo's
other three algorithms fixes it.

<details><summary>Model answer</summary>

A client can send 100 requests in the last second of window N (all
counted against window N's key), then immediately send another 100
requests in the first second of window N+1 (a fresh key, fresh
counter) — 200 requests inside roughly a 2-second span, even though the
stated limit is "100 per minute." The window boundary is fixed and
arbitrary relative to actual request timing, so a burst straddling the
boundary evades the intended smoothing entirely. **Sliding Window Log**
fixes this exactly, since it tracks the actual timestamp of every
request in a ZSET and counts however many fall within the trailing 60
seconds *relative to now*, not relative to a fixed clock boundary — no
boundary to straddle.
</details>

### Q2 [core] — Token bucket vs. sliding window counter — [ ] not yet attempted
**Scenario:** `rate-limiter.md` implements both Token Bucket (HASH with
`tokens`/`lastRefillMs`) and Sliding Window Counter (two STRING
counters).
**Question:** What behavior does token bucket allow that sliding window
counter doesn't, and when would that matter?

<details><summary>Model answer</summary>

Token bucket naturally allows **bursts up to the bucket's capacity**
even after a period of no traffic — tokens accumulate (up to the max)
while unused, so a client that's been quiet for a while can legitimately
fire off a burst all at once, as long as it doesn't exceed the
accumulated tokens. Sliding window counter (and sliding window log)
smooths traffic against a trailing time window regardless of recent
idle time — it doesn't "remember" unused capacity the way a bucket
does. This matters for APIs where legitimate clients naturally burst
(e.g. a batch job that fires 50 requests at once every few minutes) —
token bucket accommodates that pattern gracefully; a strict sliding
window would reject part of every burst even though the client's
*average* rate is well within limits.
</details>

## Concept 6: Sorted Sets — Leaderboards
_guide: redis-guide.md#6-sorted-sets--leaderboards--atomic-conditional-scoring_

### Q1 [core] — Why GT CH instead of a lock — [ ] not yet attempted
**Scenario:** Two near-simultaneous score updates arrive for the same
player in `leaderboard.md`'s `leaderboard:{lbId}` ZSET — one raising
their score to 500, a slightly delayed one (from an older game event)
trying to set it to 480.
**Question:** Write the update, and explain why `GT` makes a lock
unnecessary here.

<details><summary>Model answer</summary>
```
ZADD leaderboard:{lbId} GT CH 500 {userId}
ZADD leaderboard:{lbId} GT CH 480 {userId}
```
`GT` tells Redis to only apply the new score if it's strictly greater
than the member's current score — applied atomically as part of the
single `ZADD` command, with no read-then-compare-then-write gap for a
race to exploit. Regardless of which of the two updates actually
arrives at Redis first, the final state converges correctly: if 500
lands first, the later 480 update is a no-op (480 is not greater than
500); if 480 lands first, the later 500 update correctly overwrites it.
No external lock is needed because the "only if greater" check and the
write are one atomic server-side operation — this is the same
class of fix as the SQL guide's atomic conditional `UPDATE`, just
expressed as a ZSET flag instead of a `WHERE` clause.
</details>

### Q2 [core] — Picking the right query — [ ] not yet attempted
**Scenario:** A leaderboard UI needs three different views: the global
top 10, "where do I rank," and "the 5 players just above and below me."
**Question:** Name the Redis command for each.

<details><summary>Model answer</summary>

- Top 10: `ZREVRANGE leaderboard:{lbId} 0 9 WITHSCORES` — the first 10
  members in descending score order.
- "Where do I rank": `ZREVRANK leaderboard:{lbId} {userId}` — returns
  the member's 0-indexed rank in descending order directly, no need to
  scan or compute it manually.
- "5 above and below me": first get the rank via `ZREVRANK`, then
  `ZREVRANGE leaderboard:{lbId} {rank-5} {rank+5} WITHSCORES` — a
  ranged slice centered on the known rank. All three are O(log N) to
  find the starting point plus O(M) for the M elements returned —
  cheap regardless of how large the overall leaderboard is.
</details>

## Concept 7: Sets & Approximate Counters
_guide: redis-guide.md#7-sets--approximate-counters--membership-vs-exact-count_

### Q1 [core] — Why not just SCARD — [ ] not yet attempted
**Scenario:** `like-and-comment-service.md` maintains both a SET
`post:{id}:likers` and a separate counter `post:{id}:like_count`,
rather than just calling `SCARD post:{id}:likers` whenever the count is
needed.
**Question:** Why maintain a redundant counter instead of computing the
count from the set directly?

<details><summary>Model answer</summary>

`SCARD` is O(1) in Redis actually — but the real issue this repo's
design is guarding against is broader than this one command: keeping a
separately-maintained approximate counter means the like-count read
path never depends on the size or implementation of the underlying
membership structure at all, and can be served from a plain STRING
`GET` — the cheapest possible read, with no dependency on set
internals. It also decouples the two independently: the exact
membership set could later move to a different structure or store
entirely (e.g. sharded across multiple keys under very high scale)
without touching the counter's read path. The two structures serve
genuinely different consumers (auth check vs. public display) with
different consistency needs, and keeping them as separate,
independently-scalable structures is the more robust design even where
`SCARD`'s complexity alone wouldn't force the split.
</details>

### Q2 [core] — Membership check must stay exact — [ ] not yet attempted
**Scenario:** A teammate suggests replacing `post:{id}:likers`'s SET
with an approximate structure (like a Bloom filter) to save memory on
extremely popular posts.
**Question:** Why would this break the system, even though the
`like_count` next to it is already approximate?

<details><summary>Model answer</summary>

The SET answers "did *this specific user* like this post" — a
per-user, binary UI state (show a filled vs. outline heart icon) that
must be exactly right for that user, every time, or the UI lies to
them about their own action. A Bloom filter trades exactness for space
via false positives (it can wrongly say "yes, this is a member" for
something never added, though never a false negative) — acceptable for
the aggregate count, where being off by a handful across millions
means nothing to any individual viewer, but not acceptable for a
membership check where the "someone" being wrong about is the specific
user looking at their own screen. The count and the membership check
have different accuracy requirements because they have different
audiences — one person's exact state vs. everyone's rough total.
</details>

## Concept 8: Geo Commands
_guide: redis-guide.md#8-geo-commands_

### Q1 [core] — Regional sharding for geo data — [ ] not yet attempted
**Scenario:** `uber-find-nearby-driver.md` shards its driver geo-index
into `drivers:geo:{regionId}` rather than one global `drivers:geo` set.
**Question:** Why does a single global geo-set become a problem at
scale, even though `GEOSEARCH` itself is efficient?

<details><summary>Model answer</summary>

Redis Cluster shards *between* keys, never within a single key's
internal data (Concept 11) — a geo set is, under the hood, one sorted
set, so a single global `drivers:geo` key can only ever live on one
shard no matter how large the underlying dataset or how much traffic
hits it. Every driver-location write and every nearby-search read
across the *entire* system would funnel through that one shard,
turning it into a hot key regardless of `GEOSEARCH`'s own algorithmic
efficiency. Splitting by `regionId` turns one unshardable global
structure into many independently-shardable regional ones — a search
in São Paulo never contends with a write in Mumbai, because they're
different keys, likely on different shards.
</details>

### Q2 [core] — Gating geo access with a session TTL — [ ] not yet attempted
**Scenario:** `nearyby-friends.md` checks `EXISTS session:{sharerId}:{friendId}`
before running `GEOSEARCH`, never the reverse order.
**Question:** Why does the order matter here?

<details><summary>Model answer</summary>

Checking the session first means an unauthorized or expired request
never touches the geo data at all — the moment the TTL-backed session
key is gone, the location lookup is refused before any location data is
even read, which is both a correctness guarantee (no stale-authorization
window) and a minor efficiency win (skip the geo query entirely for
denied requests). Checking geo first and then authorization afterward
would mean location data gets fetched and computed on every request
regardless of whether the requester was ever allowed to see it —
functionally the same end result if the check is correct, but it
means the "sensitive" step (retrieving someone's location) always
runs, rather than being gated behind the "is this even allowed"
check — a defense-in-depth ordering choice, not just a performance one.
</details>

## Concept 9: Lists — Fan-out-on-Write Feeds
_guide: redis-guide.md#9-lists--fan-out-on-write-feeds_

### Q1 [core] — Why LTRIM matters — [ ] not yet attempted
**Scenario:** `news-feeds.md`'s `feed:{userId}` LIST grows via `LPUSH
feed:{followerId} {postId}` every time someone they follow posts.
**Question:** What happens if `LTRIM feed:{followerId} 0 499` is
omitted, and why is this the same underlying problem as an unbucketed
Cassandra partition?

<details><summary>Model answer</summary>

Without the trim, the list grows without bound for as long as the
follower keeps following active posters — years of accumulated post
IDs sitting in one Redis key, most of which will never actually be
read (nobody scrolls back years into their feed). This is the exact
same shape as an unbucketed Cassandra partition (Cassandra guide's
Concept 3): a single key/partition that's allowed to grow forever
because nothing bounds it, becoming slower to operate on and wasting
memory holding data nobody queries. `LTRIM` after every push caps the
list at a fixed size (500 most recent), keeping the key's size bounded
regardless of how long the relationship or how prolific the followed
users are — bounding growth is the recurring fix in both worlds, just
expressed as `LTRIM` here instead of a time-bucket partition key.
</details>

### Q2 [core] — Why celebrities skip fan-out — [ ] not yet attempted
**Scenario:** A celebrity account with 50 million followers posts once.
**Question:** Why does `news-feeds.md` skip the `LPUSH`-to-every-follower
fan-out for this case, and what does it do instead?

<details><summary>Model answer</summary>

Fan-out-on-write means one post from this account triggers 50 million
individual `LPUSH` calls — a massive write amplification for a single
event, and most of those followers may never even open their feed
before the post is buried under newer content anyway, making most of
that write work wasted. Instead, celebrity posts are served via a
**pull** path: stored once (in Cassandra, per the Cassandra guide's
`posts` table keyed by `author_id`), and merged into a follower's feed
at *read* time by querying the small number of celebrities they follow
directly and interleaving those posts (by timestamp) with the
regular fan-out-on-write feed already in Redis. This is a hybrid
push/pull design driven by follower count — push for normal accounts
where fan-out cost is small, pull for accounts where it would be
enormous — not a single fixed strategy applied uniformly.
</details>

## Concept 10: Atomicity via Lua Scripting
_guide: redis-guide.md#10-atomicity-via-lua-scripting-eval_

### Q1 [core] — Why Lua instead of separate commands — [ ] not yet attempted
**Scenario:** `rate-limiter.md`'s Token Bucket check needs to: read the
current token count and last-refill time, compute how many tokens to
add based on elapsed time, decide allow/deny, and write the updated
state back — all for one incoming request.
**Question:** Why does this run as one Lua script instead of four
separate Redis commands from the application?

<details><summary>Model answer</summary>

If those four steps were separate round trips from the application
(`HGETALL`, compute in app code, `HSET`), two concurrent requests for
the same client could both read the same starting token count before
either writes back — both might independently compute "yes, a token is
available" and both decide to allow, when only one token actually
existed, exactly the same race Concept 5's atomic-`UPDATE` pattern
(SQL guide) exists to prevent. A Lua script executes as one atomic unit
entirely inside Redis — no other client's commands can interleave
between the script's internal read and write — closing the gap
completely, and as a side benefit it's also faster, since it's one
network round trip instead of several.
</details>

### Q2 [core] — What Lua atomicity does NOT protect — [ ] not yet attempted
**Scenario:** A rate limiter's Lua script correctly enforces the
token-bucket logic atomically inside Redis. The application code that
*calls* the script also needs to log every denied request to a
separate analytics system.
**Question:** Is that logging call automatically covered by the same
atomicity guarantee? Why or why not?

<details><summary>Model answer</summary>

No — Lua script atomicity only covers what happens *inside* the
script, on the Redis server, against Redis's own data. The moment the
script returns and the application does something else (log to an
analytics system, call another service), that's ordinary application
code with no atomicity guarantee tying it to the Redis operation that
preceded it — the script could succeed and the log call could fail (or
vice versa in a differently-ordered design), and nothing rolls
anything back. This is a useful boundary to be explicit about: Lua
scripting solves races *within* Redis state, not coordination between
Redis and any other system — that would need its own mechanism
(retries, an outbox pattern, at-least-once logging with
deduplication) if it mattered enough to guarantee.
</details>

## Concept 11: Redis Cluster — Sharding & Hot-Key Limits
_guide: redis-guide.md#11-redis-cluster--sharding--hot-key-limits_

### Q1 [core] — Diagnosing the leaderboard's shard limit — [ ] not yet attempted
**Scenario:** `leaderboard.md`'s global leaderboard is a single ZSET,
and the system needs to scale past what one Redis node can handle.
**Question:** Why doesn't simply adding more nodes to a Redis Cluster
fix this, and what did the actual design do instead?

<details><summary>Model answer</summary>

Redis Cluster shards data *between different keys* by hashing each
key to a slot — it has no mechanism to split the internal contents of
one key (all the members of one ZSET) across multiple nodes. A single
global `leaderboard:{lbId}` key, no matter how many nodes exist in the
cluster, is always served entirely by whichever one node owns its
slot — adding nodes helps *other* keys spread out, but does nothing
for this one key's own capacity or throughput ceiling. `leaderboard.md`'s
actual fix: split into regional sub-leaderboards
(`leaderboard:region:{r}`), each a separate key (and therefore
independently shardable across different nodes), periodically merged
into a global view — trading perfect real-time global ranking for
horizontal scalability.
</details>

### Q2 [core] — Designing around a hot key before it happens — [ ] not yet attempted
**Scenario:** You're designing a new feature: a single Redis SET
tracking "all users currently online across the entire platform,"
checked on every page load to show online friends.
**Question:** Applying this concept, what's the problem with this
design before it even ships, and how would you restructure it?

<details><summary>Model answer</summary>

Same shape as the leaderboard problem: one global key, checked on
*every* page load across the entire user base, can never be spread
across shards — it's a hot key by construction, not by surprise
growth. The fix follows the same pattern as `whatsapp-user-socket-info.md`'s
per-user connection keys: instead of one global "who's online" set,
key presence per-user (`presence:{userId}`, a simple STRING with TTL,
per Concept 2) or shard the online-set by some partitioning dimension
(e.g. by region or by a hash of user ID into N buckets) so no single
key has to serve platform-wide traffic. The general lesson: any
"global, checked constantly" structure is worth sharding by design
*before* scale forces a redesign, not after.
</details>

## Concept 12: Unused in This Repo — Persistence, Pub/Sub, HyperLogLog
_guide: redis-guide.md#12-unused-in-this-repo--persistence-pubsub-hyperloglog_

### Q1 [core] — Why chat fan-out uses Kafka, not Redis pub/sub — [ ] not yet attempted
**Scenario:** `chat-systems.md` routes large-group message fan-out
through Kafka rather than a Redis pub/sub channel, even though pub/sub
looks like the more obvious tool for "broadcast a message to many
subscribers."
**Question:** What specific limitation of Redis pub/sub makes Kafka the
better choice here?

<details><summary>Model answer</summary>

Redis pub/sub is fire-and-forget with **no persistence or replay**: if
a subscriber (a connected client, or more precisely the server
handling their connection) is briefly disconnected when a message is
published, that message is simply gone for them — there's no log to
catch up from once they reconnect. For a chat system, a dropped message
during a brief reconnect is a real correctness problem (a lost chat
message), not an acceptable trade-off. Kafka's topic-partition log
persists messages and lets a consumer resume from wherever it left off
(via committed offsets), so a briefly-disconnected server can catch up
on everything it missed — the durability guarantee Redis pub/sub
fundamentally doesn't provide.
</details>

### Q2 [core] — Why Redis is never a system of record here — [ ] not yet attempted
**Scenario:** Across all 16 Redis-labeled systems in this repo, none
configure or discuss RDB/AOF persistence tuning.
**Question:** Is this an oversight, or does it follow from how Redis is
actually being used everywhere in this repo? Justify your answer with
at least two concrete examples.

<details><summary>Model answer</summary>

It follows from the usage pattern, not an oversight: every Redis
structure in this repo is either (a) a cache with a durable source of
truth behind it — `url-shortner.md`'s `short:{code}` cache in front of
Cassandra, `rate-limiter.md`'s `rl:cfg:*` rule cache in front of a
config store — where losing the Redis copy just means slower reads
until it's repopulated, or (b) inherently ephemeral state that's
correct to lose on restart — `whatsapp-user-socket-info.md`'s
connection registry (a lost entry just means one extra reconnect;
stale entries expire via TTL anyway), `movie-ticket-booking.md`'s
seat locks (a lock lost to a Redis restart just means the hold is
gone, recoverable by the user re-selecting the seat). In neither
category does Redis ever hold data that would be a genuine, unrecoverable
loss if wiped — which is exactly the condition under which
persistence tuning stops being a real design lever and becomes moot.
</details>
