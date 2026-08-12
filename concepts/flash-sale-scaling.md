---
concept_name: Flash Sale Scaling (Peak Load / Big Billion Day)
linked_systems: [Amazon Order Managment System]
last_reviewed: 2026-08-12
freshness: Fresh
notion_url: TBD
---

# Flash Sale Scaling

**Diagram:** `concepts/diagrams/flash-sale-scaling.drawio` (page 1: mode
routing architecture; page 2: sale-window reservation + write-behind +
reconciliation flow; page 3: the per-SKU flag lifecycle state diagram)

**Interactive trace:** `concepts/implementations/flash-sale-scaling-trace.html`
— walks one SKU through scheduling sale mode, warm-up, a live reservation,
write-behind, reconciliation, and the kill-switch escape hatch.

## The question this answers

"During a flash sale (Big Billion Days, Prime Day, ...), keep inventory
in Redis and cut down database calls — is that real, and how do we
actually flip a system into that mode and back?"

Short version: the *principle* is real and well-established — move the
one specific hot, contended value (a SKU's live stock counter) off the
primary relational database and onto a low-latency, horizontally-shardable
store for the duration of the sale, while the database stays the durable
system of record for orders. "Keep *everything* in Redis" is a
simplification of that — see "What's actually true" below.

## The core pattern

1. **The counter moves, the order table doesn't.** During the sale
   window, a SKU's `available_qty` lives in Redis, decremented via a
   single atomic Lua script instead of a SQL `UPDATE`:
   ```lua
   local stock = tonumber(redis.call('GET', KEYS[1]))
   if not stock or stock <= 0 then return -1 end
   if redis.call('SISMEMBER', KEYS[2], ARGV[1]) == 1 then return -2 end
   redis.call('DECR', KEYS[1])
   redis.call('SADD', KEYS[2], ARGV[1])
   return 1
   ```
   One round trip: checks stock, enforces a per-user purchase limit
   (`SISMEMBER`), decrements, and records the buyer — no read-then-write
   gap, same spirit as the conditional `UPDATE ... WHERE available_qty >=
   ?` [[amazon-order-management-system]] already uses, just roughly two
   orders of magnitude faster under contention:

   | Approach | Throughput |
   |---|---|
   | SQL `SELECT ... FOR UPDATE` | ~100s/sec |
   | SQL optimistic `WHERE available_qty >= ?` | ~5–10K/sec |
   | Redis Lua `DECR` | ~100K/sec |

2. **Write-behind, not write-around.** The database still gets every
   order — just asynchronously. Redis confirms the reservation
   immediately; the order intent goes on a queue (Kafka, reusing the
   same backbone as `payment.completed` in the OMS design); a worker
   writes the durable order row after the fact. In a worked example (10M
   users, 10K units, 60-second window), Redis absorbs ~100K ops/sec
   while the database only ever sees ~1,000 writes/sec — that ~100:1
   reduction is the concrete content behind "reduce DB calls."

3. **Hot-key sharding for a single viral SKU.** Even one Redis key can
   bottleneck under enough concurrent `DECR`s. Split that SKU's counter
   into N sub-counters (`inv:P-556:0` … `inv:P-556:15`); a reserve picks
   one at random to decrement, a stock-level read sums across all of
   them. This is what `concepts/distributed-locking.md` (not yet
   created) should own in more depth — flagging it here since it's the
   same underlying idea as the atomic-update contention problem in the
   OMS design's Concurrency Requirements section.

4. **The database is still the safety net, not a spectator.** Redis is
   primarily in-memory — a bare `DECR` with no durability story is a
   real data-loss risk on failover. Production-safe versions of this
   pattern keep AOF persistence + replica sync on the Redis side, *and*
   `UNIQUE(idempotency_key)` / `UNIQUE(user_id, sale_id)` on the SQL
   orders table as the backstop — even if Redis resets mid-sale, the
   database physically cannot record a duplicate order. This is the same
   idempotency-key mechanism the OMS design already has; it just becomes
   the safety net instead of the primary defense.

5. **A reconciler, not blind trust.** A background job periodically
   diffs Redis counters against order rows (and the payment gateway) to
   catch drift. This generalizes the reservation-expiry reaper already
   in the OMS design into a broader sale-mode reconciler.

## How the switch actually happens

This is not a single global boolean, and not an environment variable
(those require a redeploy — too slow to flip minutes before a sale, and
too slow to flip back if something breaks).

- **Flag store:** a fast, shared, watchable store the whole service
  fleet observes — Redis pub/sub, etcd/ZooKeeper watches, or a
  feature-flag service with a streaming SDK. A change propagates to
  every instance in seconds with no deploy and no restart.
- **Scope: per-SKU (or per-category), not global.** Only the handful of
  SKUs actually expected to spike get flagged. In code this is a
  **Strategy pattern**: a `ReservationRouter` looks up the flag for the
  incoming `productId` and dispatches to `SqlReservationStrategy` or
  `RedisReservationStrategy`. A bad flip only affects flagged SKUs — the
  rest of the catalog stays on the ordinary SQL path the whole time.
- **Per-SKU lifecycle, not a boolean:**
  ```
  SQL_PRIMARY → WARMING → REDIS_PRIMARY → DRAINING → SQL_PRIMARY
  ```
  `WARMING`: a job reads the SKU's current `available_qty` from SQL and
  seeds Redis (`SET inv:P-556 500`) *before* the router starts sending
  it traffic. `DRAINING`: after the sale window, Redis's final count
  reconciles back into SQL before the flag clears — never the reverse
  order.
- **It has to be a kill switch.** If Redis misbehaves mid-sale, an
  operator flips the SKU straight back to `SQL_PRIMARY` from a
  dashboard, in seconds, no deploy — the same mechanism as turning it
  on, just the emergency direction. In-flight Redis reservations still
  get reconciled into SQL on the way out; nothing is silently dropped.

## What's actually true (and what isn't)

"Ideally everything in Redis" doesn't hold up against how this is done
at real scale. Amazon's own Prime Day infrastructure leans on
**DynamoDB** — a durable, distributed key-value store — not literally
Redis: 151M requests/sec at peak in 2025, tens of trillions of API calls
across Amazon.com, fulfillment centers, and Alexa. The *principle* your
friend described (get the hot inventory path off a traditional
relational OLTP engine) is exactly what happens at that scale; the
specific technology is an implementation choice — Redis, DynamoDB, or a
purpose-built sharded-counter service all satisfy the same requirement:
low-latency, horizontally-shardable, and *not* the system of record for
orders.

Worth flagging on sourcing: the Redis/Lua specifics and throughput
numbers above come from detailed system-design write-ups (flash-sale
architecture explainers, Flipkart Big Billion Days breakdowns), not
official company engineering blogs — treat the exact figures as
illustrative of the pattern's shape, not as Flipkart's or Amazon's
literal published numbers. The DynamoDB Prime Day figures, by contrast,
are from AWS's own News Blog and are the real, official numbers.

## Sources

- [Flash Sale System Design: Architecture, Scale, and Oversell](https://singhajit.com/flash-sale-system-design/)
- [Flipkart's Big Billion Days: How Backend Systems Fight Cart Wars and Flash Sales](https://blog.codekerdos.in/flipkarts-big-billion-days-how-backend-systems-fight-cart-wars-and-flash-sales/)
- [Flipkart Big Billion Days — System Design Guide](https://medium.com/@bhavesh.vaswani96/flipkart-big-billion-days-system-design-guide-by-mission-compile-https-www-instagram-com-miss-f82c5f386e05)
- [AWS services scale to new heights for Prime Day 2025: key metrics and milestones](https://aws.amazon.com/blogs/aws/aws-services-scale-to-new-heights-for-prime-day-2025-key-metrics-and-milestones/)

## Related

- [[amazon-order-management-system]] — the system this pattern is an
  addendum to; Inventory Service's Concurrency Requirements section
  flags the hot-row problem this concept resolves for peak load.
- `concepts/distributed-locking.md` (not yet created) — owns the
  general hot-key/sharded-counter mechanics in more depth.
- `concepts/saga.md` (not yet created) — the write-behind order flow
  here is another instance of the same compensating-action pattern used
  in the OMS checkout saga.
