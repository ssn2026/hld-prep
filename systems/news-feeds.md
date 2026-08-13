---
service_name: News Feeds
grouping: Social Media
status: Deep Dive Ready
labels: [Redis, cassandra]
sections_complete: 10
last_session: 2026-08-12
notion_url: TBD
---

**Diagram:** `systems/diagrams/news-feeds.drawio` (single page —
fan-out-on-write for normal users, fan-out-on-read for celebrities,
merged at read time)

**Interactive trace:** `systems/implementations/news-feeds-trace.html`
— a normal user's post pushes to a handful of feeds instantly; a
celebrity's post doesn't push anywhere, and gets pulled in live
instead

## 1. Requirement Gathering

**Functional**
- A user's feed shows recent posts from people they follow.
- Posting should make a post visible to followers promptly.

**Non-functional — the celebrity problem, the reason this system is
interesting at all.** A normal user posting to a few hundred followers
and a celebrity posting to 50 million followers are not the same
write, even though the API call looks identical. Treating them
identically forces a bad trade-off either direction — precompute every
feed on every post (fine for most users, catastrophic write amplification
for a celebrity) or compute every feed at read time (fine for
celebrities, wastefully expensive for a normal user's fast, cheap case).

## 2. Queries in Plain English

- Get my feed.
- Post (fans out to followers somehow).
- Follow / unfollow a user.

## 3. State Diagram

Doesn't apply — a feed is a computed/merged view, not an entity with a
lifecycle; a post is created and that's it.

## 4. API Endpoints

| Endpoint | Notes |
|---|---|
| `GET /feed` | merges precomputed + live-pulled content |
| `POST /posts` | triggers fan-out (write or read, depending on author) |
| `POST /users/{id}/follow` | |

## 5. Concurrency Requirements

**The hybrid fan-out pattern — the canonical answer to the celebrity
problem, and this system's whole reason for existing:**

- **Fan-out-on-write (push), for normal accounts:** when a user with a
  bounded follower count posts, the post is immediately pushed into
  *each* follower's precomputed feed. Reads are then trivially fast —
  a feed is just a pre-assembled list, no work happens at read time.
  This only works because follower counts stay small enough that the
  per-post write fan-out is cheap.
- **Fan-out-on-read (pull), for high-follower accounts:** a celebrity's
  post is written *once*, to their own post history, and never pushed
  to any follower's feed. Instead, at read time, each requesting
  user's feed generation separately fetches the celebrity's recent
  posts live and merges them in.
- **The merge happens per-request, for every user**, regardless of
  which category their follows fall into: read the user's precomputed
  feed (fast, push-based) → for each celebrity they follow (a small,
  bounded number even for a user who follows many accounts overall) →
  fetch that celebrity's recent posts live → merge everything by
  timestamp → return.

This is the same push-vs-pull trade-off seen elsewhere in this repo in
narrower form — `redis-as-cache.md`'s cache-aside is a pull pattern,
`notification-system.md`'s fan-out is a push pattern — News Feeds is
where the choice between them becomes the central design decision
instead of a settled default.

## 6. Database Choice + Justification

- **Precomputed feeds → Redis**, capped-length lists per user
  (`feed:{userId}`, trimmed to the most recent N entries) — fast reads
  are the entire point of the push path.
- **Posts and the follow graph → Cassandra**, same reasoning as every
  other Cassandra table in this repo: high write volume, simple,
  known-in-advance access patterns (posts by author, followers of a
  user).

## 7. Database Schema

```sql
CREATE TABLE posts (author_id BIGINT, post_id TIMEUUID, content TEXT, PRIMARY KEY (author_id, post_id))
  WITH CLUSTERING ORDER BY (post_id DESC);
CREATE TABLE follows (follower_id BIGINT, followee_id BIGINT, PRIMARY KEY (follower_id, followee_id));
CREATE TABLE followers_index (followee_id BIGINT, follower_id BIGINT, PRIMARY KEY (followee_id, follower_id));
```
Redis: `feed:{userId}` — a capped list of recent post IDs, push-populated.

## 8. Detailed Queries

```sql
-- normal user posts: write + look up (bounded) follower list for fan-out
INSERT INTO posts (author_id, post_id, content) VALUES (?, now(), ?);
SELECT follower_id FROM followers_index WHERE followee_id = ?;
```
```
-- fan-out-on-write, one push per follower
LPUSH feed:{followerId} {postId}
LTRIM feed:{followerId} 0 499
```
```sql
-- celebrity post: write only, no fan-out
INSERT INTO posts (author_id, post_id, content) VALUES (?, now(), ?);

-- feed read: pull a celebrity's recent posts live
SELECT * FROM posts WHERE author_id = ? LIMIT 20;
```

## 9. Read/Write Paths

**Normal user post path:** insert into `posts` → look up follower list
→ push the new post ID onto each follower's Redis feed list, trimming
to a capped length.

**Celebrity post path:** insert into `posts` — nothing else happens at
write time.

**Feed read path (every user, same logic):** read `feed:{userId}` from
Redis (fast, precomputed) → for each celebrity-tier account this user
follows, query their recent posts live from Cassandra → merge both
sources by timestamp → return the combined feed.

## 10. Scale Justification

- **Fan-out-on-write cost is O(followers) per post** — cheap for the
  overwhelming majority of accounts with bounded follower counts,
  which is exactly why it's the default rather than something to avoid
  universally.
- **Fan-out-on-read cost is O(celebrities followed) per feed view** —
  bounded and small even for a user who follows thousands of accounts
  overall, because only the high-follower-count subset ever needs a
  live pull; the rest already arrived via the precomputed feed.
- **The split is what makes both sides of this problem tractable at
  once** — neither pure push nor pure pull alone scales across the
  full range from a new account with ten followers to a celebrity with
  tens of millions, and this system exists specifically because that
  range is real.

## Implementation Notes

_(none yet beyond the interactive trace linked above)_
