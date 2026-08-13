---
service_name: Like and Comment Service
grouping: Social Media
status: Deep Dive Ready
labels: [Redis, cassandra]
sections_complete: 10
last_session: 2026-08-12
notion_url: TBD
---

**Diagram:** `systems/diagrams/like-and-comment-service.drawio`
(single page — accurate membership vs. approximate count, deliberately
split)

**Interactive trace:** `systems/implementations/like-and-comment-service-trace.html`
— a user's like toggles idempotently, while the displayed count stays
approximate under a burst

## 1. Requirement Gathering

**Functional**
- Like/unlike a post (a toggle, not an increment button).
- Add a (possibly threaded) comment; list a post's comments, paginated.

**Non-functional**
- **Two genuinely different questions hide behind "likes":** "did *I*
  like this post" (must be exact — showing the wrong toggle state to
  the user who just clicked it is a visible, immediate bug) and "how
  many total likes does this post have" (can be approximate — nobody
  can tell 48,201 from 48,196 at a glance, and it's displayed to
  *everyone*, at far higher read volume than the membership check).
  Treating both as the same problem, solved the same way, is a missed
  opportunity this system deliberately avoids.

## 2. Queries in Plain English

- Like / unlike a post.
- Check whether the current user has liked a post.
- Get a post's (approximate) like count.
- Add a comment (optionally a reply to another comment).
- Get a post's comments, paginated.

## 3. State Diagram

```
Like:  (absent) ⇄ LIKED   -- a toggle, not a lifecycle
```
Comments don't have a state machine either — posted, and that's it
(edits/deletes are just further writes, not transitions).

## 4. API Endpoints

| Endpoint | Notes |
|---|---|
| `POST /posts/{id}/like` | idempotent toggle |
| `GET /posts/{id}/like-status` | for the current user |
| `GET /posts/{id}/likes/count` | approximate |
| `POST /posts/{id}/comments` | body: `{text, parentCommentId?}` |
| `GET /posts/{id}/comments` | paginated |

## 5. Concurrency Requirements

**Like membership is naturally idempotent via a set, not a counter.**
`SADD post:{id}:likers {userId}` — adding a user who's already a
member is simply a no-op, no read-then-write race, no double-count
risk from a double-click. `SISMEMBER` answers "did I like this"
directly and exactly.

**Like *count* is a separate, deliberately looser number.** Rather than
`SCARD` (which would be exact but requires scanning the set — fine at
moderate scale, a real cost on a viral post with millions of likers)
the displayed count is a **cached, periodically-reconciled
approximate counter**, updated via a cheap `INCR`/`DECR` alongside the
`SADD`/`SREM`, with an occasional background reconciliation against
the true set size to correct any drift. This is the same
"approximate-but-bounded beats exact-but-expensive" call as
`leaderboard.md` and `click-event-aggregator.md`'s HyperLogLog,
applied here because the count genuinely doesn't need to be exact for
anyone reading it.

**Comment writes are simple appends** — no concurrency conflict to
resolve, since a new comment never contends with another comment the
way a like toggle contends with itself.

## 6. Database Choice + Justification

- **Like membership → Redis SET.** Exactly the shape `SADD`/`SREM`/`SISMEMBER`
  are built for — fast, idempotent, no other structure fits this access
  pattern as directly.
- **Approximate like count → Redis counter**, cached alongside the set,
  not derived from it on every read.
- **Comments → Cassandra**, partitioned by `post_id` — the same
  write-heavy, simple-partition-key shape as every other Cassandra
  table in this repo, and comments genuinely can arrive at high volume
  on a popular post.

## 7. Database Schema

```
Redis SET:     post:{id}:likers      members = userIds
Redis counter: post:{id}:like_count  approximate, INCR/DECR alongside the set
```
```sql
CREATE TABLE comments (
  post_id           TEXT,
  comment_id        UUID,
  parent_comment_id UUID,
  author_id         BIGINT,
  text              TEXT,
  created_at        TIMESTAMP,
  PRIMARY KEY (post_id, created_at, comment_id)
) WITH CLUSTERING ORDER BY (created_at DESC);
```

## 8. Detailed Queries

```
SADD post:P-9:likers U-14
INCR post:P-9:like_count
SISMEMBER post:P-9:likers U-14
GET post:P-9:like_count
```
```sql
INSERT INTO comments (post_id, comment_id, parent_comment_id, author_id, text, created_at)
VALUES ('P-9', ?, NULL, 'U-14', 'nice shot!', now());

SELECT * FROM comments WHERE post_id = 'P-9' LIMIT 20;
```

## 9. Read/Write Paths

**Like path:** `SADD` (membership) + `INCR`/`DECR` (approximate count)
happen together — the membership set is the source of truth for "did I
like this," the counter is a fast-path cache for "how many," reconciled
periodically rather than derived live.

**Comment path:** straight insert into the `post_id`-partitioned
table; reads are a normal Cassandra range query, newest-first by the
clustering order.

## 10. Scale Justification

- **Like toggles**: `SADD`/`SISMEMBER` are O(1) Redis operations — even
  a viral post's like burst is well within a single Redis node's
  throughput.
- **Approximate count avoids `SCARD`'s scan cost** on a set with
  millions of members, exactly the scenario where the exact/approximate
  split pays off — this is the same "don't pay for precision nobody
  needs" lesson as `proximity-servicebase.md`'s two-phase query, in a
  different domain.
- **Comments** scale the same way `notification-system.md`'s log does —
  Cassandra write throughput linear with node count, unrelated to like
  volume entirely, since the two are independent Redis/Cassandra
  workloads sharing nothing but the `post_id`.

## Implementation Notes

_(none yet beyond the interactive trace linked above)_
