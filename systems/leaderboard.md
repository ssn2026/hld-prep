---
service_name: LeaderBoard
grouping: (ungrouped)
status: Deep Dive Ready
labels: [Redis, SQL]
sections_complete: 10
last_session: 2026-08-12
notion_url: TBD
---

**Diagram:** `systems/diagrams/leaderboard.drawio` (single page —
architecture; no async flow, no state diagram, see section 3)

**Interactive trace:** `systems/implementations/leaderboard-trace.html`
— two devices racing to submit a score for the same player, and a rank
query before/after

## 1. Requirement Gathering

**Functional**
- Track scores for players across one or more leaderboards (e.g.
  per-game, per-season, global).
- Submit/update a player's score.
- Get the top N players.
- Get a specific player's current rank + score.
- Get the players ranked immediately around a specific player ("show me
  5 above and below me").

**Non-functional**
- Extremely read-heavy relative to writes — leaderboard views vastly
  outnumber score submissions, but writes can burst (everyone finishing
  a match around the same time).
- Freshness matters but doesn't need to be sub-second globally — a
  rank being a few seconds stale during a burst is acceptable.
- Scale target: a popular global leaderboard, potentially millions of
  players.

## 2. Queries in Plain English

- Get the top N players.
- Get my current rank and score.
- Get the players ranked near me.
- Submit/update my score.

## 3. State Diagram

**Doesn't apply.** A score is just a number that changes — there's no
multi-step lifecycle a leaderboard entry moves through. This is
literally the example CLAUDE.md itself uses for "no state transitions,
which itself signals simpler storage is fine": no state table, no
status column, just a member + a score.

## 4. API Endpoints

| Endpoint | Notes |
|---|---|
| `GET /leaderboards/{lbId}/top?n=10` | |
| `GET /leaderboards/{lbId}/users/{userId}/rank` | |
| `GET /leaderboards/{lbId}/users/{userId}/around?radius=5` | |
| `POST /leaderboards/{lbId}/scores` | body: `{userId, score}` |

## 5. Concurrency Requirements

**User-request-level:** the same player can submit from two devices (or
a retried request) near-simultaneously. Policy decision: keep the
*best* score, not the *latest* one — a worse score submitted after a
better one shouldn't overwrite it. Redis's `ZADD ... GT` option (only
apply the update if the new score is greater) makes this a single
atomic command instead of a read-compare-write race:
```
ZADD leaderboard:{lbId} GT CH {score} {userId}
```
`GT` = conditional on greater, `CH` = report whether the element
changed. No lock needed — same "reach for an atomic primitive instead
of a lock" pattern used in `concepts/flash-sale-scaling.md` and
contrasted with `systems/movie-ticket-booking.md`'s genuine need for
one.

**Resource-level:** the entire leaderboard is one Redis sorted set —
every write and read hits the same key. At extreme scale this key
itself becomes the bottleneck (see section 10) — a different shape of
hot-key problem than a hot SKU or hot seat, because a sorted set's
ranking operations are inherently global and can't be sharded and
summed the way a simple counter can.

## 6. Database Choice + Justification

- **Live leaderboard state → Redis Sorted Set.** This is the
  textbook-correct structure: O(log N) insert/update, O(log N + M)
  range queries. `ZREVRANGE` for top-N, `ZREVRANK` for a player's rank,
  a windowed `ZREVRANGE` around a computed rank for "near me." No other
  general-purpose store matches this access pattern as directly.
- **Score history → SQL, append-only.** Redis holds *current* state,
  not history — an append-only `score_events` log in SQL gives audit
  trail, analytics, and a way to rebuild the Redis sorted set from
  scratch (replay events) if it's ever lost, without making the SQL
  write part of the hot path.

## 7. Database Schema

Redis:
```
ZSET leaderboard:{lbId}   member = userId, score = score
```

SQL:
```sql
CREATE TABLE score_events (
  event_id        BIGINT PRIMARY KEY,
  leaderboard_id  VARCHAR(50) NOT NULL,
  user_id         BIGINT NOT NULL,
  score           BIGINT NOT NULL,
  submitted_at    TIMESTAMP NOT NULL
);
CREATE INDEX idx_score_events_lb_user ON score_events(leaderboard_id, user_id);
```

## 8. Detailed Queries

```
ZADD leaderboard:global GT CH 15420 U-771              -- submit/update
ZREVRANGE leaderboard:global 0 9 WITHSCORES             -- top 10
ZREVRANK leaderboard:global U-771                       -- 0-indexed rank
ZSCORE leaderboard:global U-771                         -- current score
ZREVRANGE leaderboard:global {rank-5} {rank+5} WITHSCORES  -- around me
```
```sql
INSERT INTO score_events (event_id, leaderboard_id, user_id, score, submitted_at)
VALUES (?, 'global', 'U-771', 15420, now());
```

## 9. Read/Write Paths

**Write:** client submits a score → append to `score_events` (SQL,
audit trail, not on the critical path for the read side) → `ZADD ...
GT` against Redis (conditional, atomic, single round trip).

**Read:** top-N, rank, and around-me all go straight to the Redis
sorted set — no SQL involved on the read path at all, which is exactly
why reads can be this cheap despite being the overwhelming majority of
traffic.

## 10. Scale Justification

Target: a global leaderboard with millions of players.

- **Memory:** a sorted-set member costs roughly a few hundred bytes in
  Redis; 10M players is a few GB — comfortable on a well-provisioned
  single node, still fine on a large one at 50-100M.
- **The real limit, and why it's different from other systems in this
  repo:** a Redis Cluster shards by *key*, not by the members inside a
  single key — so one giant sorted set can't be spread across shards
  the way `flash-sale-scaling`'s per-SKU counters or a hashed table can.
  Vertical scaling (a larger single node, or Redis Cluster with this
  key pinned to one shard) works up to real memory limits; beyond that,
  the standard mitigation is sharding into regional/segment
  sub-leaderboards (`leaderboard:region:{r}`) with a periodic merge job
  computing the global view — trading a bit of freshness for
  horizontal scalability once one node's ceiling is reached.
- **Write throughput:** `ZADD` is a single O(log N) operation; even
  bursty submission spikes (everyone finishing a tournament round at
  once) are well within a single Redis node's throughput long before
  the memory ceiling above becomes the actual constraint.

## Implementation Notes

_(none yet beyond the interactive trace linked above)_
