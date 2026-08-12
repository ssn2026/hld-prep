---
service_name: Amazon Order Managment System
grouping: Ordering System
status: Deep Dive Ready
labels: [SQL, Kafka]
sections_complete: 10
last_session: 2026-08-12
notion_url: TBD
---

## 1. Requirement Gathering

**Functional**
- Customer checks out a multi-item cart into a single order.
- Order lifecycle is tracked at *two* levels: the order as a whole, and
  each line item independently — Amazon splits shipments across
  warehouses/sellers, so item A can ship today while item B ships in 3
  days.
- Customer can cancel the whole order, or a single line item, before that
  item ships.
- Customer can track shipment status and request a return/refund after
  delivery.
- Order creation integrates with three external systems: Payment,
  Inventory, Fulfillment/Shipping.

**Non-functional**
- Scale target: 10K orders/sec at peak (Prime Day-style surge), ~50K QPS
  reads (status checks, order history — reads dwarf writes).
- Strong consistency required on order state transitions and inventory
  decrement — cannot oversell a SKU.
- Durability is non-negotiable — orders are a financial record, must never
  be silently lost.
- Idempotency is critical — a client retry after a network timeout must
  never double-charge or double-create an order, and every inter-service
  event must be safe to process more than once.
- Availability can be relaxed for order history / search (eventual
  consistency acceptable there).

**Out of scope:** payment processing internals, warehouse routing
logic, catalog/search.

### Service Architecture

**Diagram:** `systems/diagrams/amazon-order-management-system.drawio`
(page 1: synchronous request path — edge layer through services, each
with its DB; page 2: async payment completion + Kafka fan-out, separated
out so the two don't get tangled together on one page)

**Edge layer** (shared infrastructure, not owned by Order Management):
every client request hits a **Load Balancer** (L7) → **API Gateway**
(routing, rate limiting, request validation), which calls the
**Authentication Service** to validate the caller's token/session before
forwarding anything to Order Service. None of the three domain services
are directly internet-facing.

Behind that edge layer, this is not one monolith — it's three services,
each with its own **PostgreSQL** database, coordinated by a saga:

- **Order Service** — owns `orders` / `order_items` in **Orders DB
  (PostgreSQL)**, sharded by `user_id`. Acts as the **orchestrator** for
  checkout; the client only ever talks to this service (via the gateway).
- **Inventory Service** — owns `inventory` / `inventory_reservations` in
  **Inventory DB (PostgreSQL)**, sharded by `product_id`. Exposes a
  synchronous reserve call, and separately consumes events to finalize or
  release a hold.
- **Payment Service** — owns `payment_intents` in **Payments DB
  (PostgreSQL)**. Talks to an external payment gateway, hands back a
  hosted payment link, receives the gateway's completion webhook, and
  publishes the outcome to Kafka.

Checkout has a **synchronous half** — create order → reserve inventory →
initiate payment, all inside the client's request/response — and an
**asynchronous half** — the client completes payment out-of-band at the
gateway's link; the gateway's webhook lands on Payment Service later,
which publishes a Kafka event that both Order Service and Inventory
Service consume to finalize state. The split exists because payment
completion can't be forced into checkout's request timeout — the
customer might take minutes to enter card details. Kafka also carries
`order.lifecycle` events out to Notification/Analytics/Search-index
consumers, decoupling those from the checkout path entirely.

```
Client → LB → API Gateway ⇄ Auth Service (validate token)
                  │
                  ▼
            Order Service ──(sync)──▶ Inventory Service [Inventory DB]  [reserve, per item]
                            ──(sync)──▶ Payment Service   [Payments DB]  [create payment intent → link]
Client ◀── order_id + payment link ──

Client ──(out of band)──▶ Payment Gateway ──(webhook)──▶ Payment Service
                                                              │
                                                    publishes │ payment.completed / payment.failed
                                                              ▼
                                                          Kafka topic
                                                   ┌──────────┼──────────┐
                                                   ▼          ▼          ▼
                                            Order Service  Inventory   Notification/
                                            [Orders DB]    Service     Analytics/Search
                                          (order→CONFIRMED) [Inv DB]   (order.lifecycle)
```

**Concepts touched but not yet reviewed:** Authentication (API
Gateway → Auth Service hop) and Load Balancing are both live in this
architecture now, and both are still `not created` in
`docs/TRACKER.md` — worth a `concepts/authentication.md` and
`concepts/load-balancing.md` pass before the next system that reuses
this edge layer.

## 2. Queries in Plain English

**User-facing**
- Place an order (checkout: cart items, shipping address, payment method).
- Get order details by order ID.
- List my orders, paginated, filterable by status/date.
- Cancel an order, or cancel a single line item.
- Track order/shipment status.
- Request a return/refund for a delivered order.

**Internal (cross-service)**
- Order Service asks Inventory Service to reserve stock for each item
  (sync, part of checkout).
- Order Service asks Payment Service to create a payment intent and
  return a hosted payment link (sync, part of checkout).
- Payment gateway notifies Payment Service that a payment succeeded or
  failed (webhook, async, out of band).
- Payment Service publishes `payment.completed` / `payment.failed` to
  Kafka (async).
- Order Service consumes that event to move the order to `CONFIRMED` or
  a failed/cancelled state.
- Inventory Service consumes that event to commit the reservation
  (permanently deduct) or release it back to available stock.
- Fulfillment service later calls back (webhook) when an item ships /
  delivers, and Order Service emits lifecycle events for
  notifications/analytics/search.
- A background reaper releases inventory reservations that expire
  because payment was abandoned and no webhook ever arrived.

## 3. State Diagram

**Diagram:** `systems/diagrams/amazon-order-management-system.drawio`
(page 3: order state, item state, and reservation state, all with
transitions)

A state machine clearly applies here, at two levels — order and line item
— because the order's displayed status is *derived* from the aggregate of
its items' states rather than being its own independent transition.

```
Order:  CREATED → PENDING_PAYMENT → CONFIRMED → (PARTIALLY_SHIPPED) → SHIPPED → DELIVERED
                        ↓                ↓
                  PAYMENT_FAILED     CANCELLED
        DELIVERED → RETURN_REQUESTED → RETURNED → REFUNDED

Item:   PENDING → RESERVED → SHIPPED → DELIVERED
                      ↓
                  CANCELLED / RETURNED

Reservation (Inventory Service, per item): HELD → COMMITTED
                                              ↓
                                          RELEASED  (payment failed, or HELD past expires_at)
```

Order status is computed from item statuses (e.g. some items SHIPPED,
others still RESERVED → order shows PARTIALLY_SHIPPED). An order sits in
`PENDING_PAYMENT` for as long as its reservations are `HELD` — it only
reaches `CONFIRMED` once the `payment.completed` event lands. Cancellation
is only legal while an item is `PENDING` or `RESERVED`.

## 4. API Endpoints

All client-facing endpoints below are reached as
`Client → Load Balancer → API Gateway → Order Service`. The gateway
calls Authentication Service to validate the caller before routing;
Order Service itself never sees an unauthenticated request.

**Order Service — client-facing**
| Endpoint | Notes |
|---|---|
| `POST /orders` | requires `Idempotency-Key` header; orchestrates the checkout saga |
| `GET /orders/{orderId}` | |
| `GET /orders?userId=&status=&cursor=&limit=` | cursor-based pagination |
| `POST /orders/{orderId}/cancel` | whole order |
| `POST /orders/{orderId}/items/{itemId}/cancel` | single line item |
| `POST /orders/{orderId}/return` | post-delivery |
| `GET /orders/{orderId}/tracking` | |

**Order Service → Inventory Service (sync, internal)**
| Endpoint | Notes |
|---|---|
| `POST /internal/inventory/reserve` | body: `{orderId, items[]}`; all-or-nothing across items |

**Order Service → Payment Service (sync, internal)**
| Endpoint | Notes |
|---|---|
| `POST /internal/payments/intents` | body: `{orderId, amount, currency}` → returns `{paymentIntentId, paymentLink}` |

**Payment gateway → Payment Service (async webhook)**
| Endpoint | Notes |
|---|---|
| `POST /internal/payments/webhook` | signature-verified gateway callback; drives the Kafka publish |

**Fulfillment → Order Service (async webhook)**
| Endpoint | Notes |
|---|---|
| `POST /internal/orders/{orderId}/items/{itemId}/ship` | |
| `POST /internal/orders/{orderId}/items/{itemId}/deliver` | |

**Kafka topics**
| Topic | Producer | Consumers | Key |
|---|---|---|---|
| `payment.completed` | Payment Service | Order Service, Inventory Service | `order_id` |
| `payment.failed` | Payment Service | Order Service, Inventory Service | `order_id` |
| `order.lifecycle` | Order Service | Notification, Analytics, Search-index | `order_id` |

## 5. Concurrency Requirements

**User-request-level serialization**
- Duplicate checkout (double-click, client retry after timeout) is
  deduped via a client-generated idempotency key stored in Order
  Service's `idempotency_keys` table with a unique constraint on `key`;
  a repeat request resolves to the same order instead of creating a new
  one.
- Order state transitions are serialized per order using a `version`
  column (optimistic concurrency) or `SELECT ... FOR UPDATE` — only one
  writer can move an order `CREATED → CONFIRMED` at a time.

**Resource-level contention**
- The classic hot-row problem: a hyped SKU launch sends thousands of
  concurrent checkouts against the *same* inventory row. A naive
  read-then-write races and oversells. Fix with a single atomic
  conditional UPDATE, no read/write gap:
  ```sql
  UPDATE inventory SET available_qty = available_qty - ?
  WHERE product_id = ? AND available_qty >= ?;
  ```
  Zero rows affected = out of stock. At extreme scale even this hot row
  becomes a bottleneck under lock contention, which is where a
  Redis-backed sharded counter in front of SQL (async-reconciled) comes
  in — see `concepts/distributed-locking.md` (not yet created).

**Cross-service saga concurrency**
- Order creation now genuinely spans three independent databases (Order,
  Inventory, Payment) with no shared transaction. Order Service is the
  saga orchestrator for the synchronous leg: reserve inventory → create
  payment intent; if the payment-intent call fails or times out, it
  compensates by releasing the reservation it just took. See
  `concepts/saga.md` (not yet created).
- Kafka delivers `payment.completed`/`payment.failed` **at least once**,
  so both consumers (Order Service, Inventory Service) must treat
  reprocessing as a no-op. The cleanest way is to make the state
  transition itself the dedup mechanism rather than maintaining a
  separate processed-events table:
  ```sql
  -- Order Service consumer
  UPDATE orders SET status = 'CONFIRMED', updated_at = now()
  WHERE order_id = ? AND status = 'PENDING_PAYMENT';   -- re-delivery: 0 rows, harmless

  -- Inventory Service consumer
  UPDATE inventory_reservations SET status = 'COMMITTED', updated_at = now()
  WHERE order_id = ? AND status = 'HELD';               -- re-delivery: 0 rows, harmless
  ```
- **Abandoned payment** is a real failure mode with no webhook at all —
  the customer just closes the tab. Every reservation carries an
  `expires_at` (e.g. `created_at + 15 min`); a background reaper releases
  any `HELD` reservation past expiry and moves the order to a
  `PAYMENT_FAILED`/timeout state, so inventory never gets stuck reserved
  forever.

## 6. Database Choice + Justification

Database-per-service — each service owns its data outright and is only
ever reached through its API or its Kafka events, never a shared table:

- **Order Service → Orders DB (PostgreSQL).** `orders` + `order_items`
  need multi-row transactional writes (an order and its items commit
  together) and strong consistency on state. Shard by `user_id` or
  `order_id` hash once volume outgrows a single primary.
- **Inventory Service → Inventory DB (PostgreSQL)**, same durability
  rationale, with the conditional atomic-update pattern handling
  hot-row contention. An optional Redis layer can front only the
  hottest SKUs, reconciled back to SQL asynchronously.
- **Payment Service → Payments DB (PostgreSQL).** `payment_intents` is a
  small, high-integrity table (financial record of intent → outcome);
  no different reasoning than the other two.
- **Kafka** is the integration backbone between Payment Service and its
  two consumers. It decouples them so that a slow or temporarily-down
  Inventory Service can never block Payment Service from acknowledging
  the gateway webhook, and replays are possible if a consumer needs to
  catch up after an outage.

## 7. Database Schema

**Orders DB (PostgreSQL) — owned by Order Service**
```sql
CREATE TABLE orders (
  order_id           BIGINT PRIMARY KEY,
  user_id             BIGINT NOT NULL,
  status              VARCHAR(20) NOT NULL,   -- CREATED, PENDING_PAYMENT, CONFIRMED, ...
  total_amount        DECIMAL(10,2) NOT NULL,
  currency            CHAR(3) NOT NULL,
  shipping_address_id BIGINT NOT NULL,
  payment_intent_id   BIGINT,
  idempotency_key     VARCHAR(64) NOT NULL,
  version             INT NOT NULL DEFAULT 0, -- optimistic concurrency
  created_at          TIMESTAMP NOT NULL,
  updated_at          TIMESTAMP NOT NULL,
  UNIQUE (idempotency_key)
);
CREATE INDEX idx_orders_user_created ON orders(user_id, created_at DESC);

CREATE TABLE order_items (
  order_item_id  BIGINT PRIMARY KEY,
  order_id       BIGINT NOT NULL REFERENCES orders(order_id),
  product_id     BIGINT NOT NULL,
  seller_id      BIGINT NOT NULL,
  quantity       INT NOT NULL,
  unit_price     DECIMAL(10,2) NOT NULL,
  status         VARCHAR(20) NOT NULL,   -- PENDING, RESERVED, SHIPPED, DELIVERED, ...
  shipment_id    BIGINT,
  created_at     TIMESTAMP NOT NULL,
  updated_at     TIMESTAMP NOT NULL
);
CREATE INDEX idx_order_items_order ON order_items(order_id);

CREATE TABLE idempotency_keys (
  key         VARCHAR(64) PRIMARY KEY,
  user_id     BIGINT NOT NULL,
  order_id    BIGINT,
  created_at  TIMESTAMP NOT NULL   -- TTL-cleaned periodically
);

CREATE TABLE shipments (
  shipment_id      BIGINT PRIMARY KEY,
  order_id         BIGINT NOT NULL REFERENCES orders(order_id),
  carrier          VARCHAR(50),
  tracking_number  VARCHAR(64),
  status           VARCHAR(20) NOT NULL
);
```

**Inventory DB (PostgreSQL) — owned by Inventory Service**
```sql
CREATE TABLE inventory (
  product_id     BIGINT PRIMARY KEY,
  available_qty  INT NOT NULL   -- stock not currently held by any reservation
);

CREATE TABLE inventory_reservations (
  reservation_id  BIGINT PRIMARY KEY,
  order_id        BIGINT NOT NULL,
  order_item_id   BIGINT NOT NULL,
  product_id      BIGINT NOT NULL,
  quantity        INT NOT NULL,
  status          VARCHAR(20) NOT NULL,   -- HELD, COMMITTED, RELEASED
  expires_at      TIMESTAMP NOT NULL,
  created_at      TIMESTAMP NOT NULL,
  updated_at      TIMESTAMP NOT NULL
);
CREATE INDEX idx_reservations_order ON inventory_reservations(order_id);
CREATE INDEX idx_reservations_expiry ON inventory_reservations(status, expires_at);
```

**Payments DB (PostgreSQL) — owned by Payment Service**
```sql
CREATE TABLE payment_intents (
  payment_intent_id  BIGINT PRIMARY KEY,
  order_id           BIGINT NOT NULL,
  amount             DECIMAL(10,2) NOT NULL,
  currency           CHAR(3) NOT NULL,
  gateway_session_id VARCHAR(128),
  payment_link       VARCHAR(255),
  status             VARCHAR(20) NOT NULL,   -- CREATED, SUCCEEDED, FAILED
  created_at         TIMESTAMP NOT NULL,
  updated_at         TIMESTAMP NOT NULL
);
CREATE UNIQUE INDEX idx_payment_intents_order ON payment_intents(order_id);
```

## 8. Detailed Queries

**Place order (Order Service, within one local transaction):**
```sql
INSERT INTO idempotency_keys (key, user_id, created_at) VALUES (?, ?, now());
-- unique-constraint violation here == duplicate request, fetch and return existing order_id instead

INSERT INTO orders (order_id, user_id, status, total_amount, currency,
                     shipping_address_id, idempotency_key, created_at, updated_at)
VALUES (?, ?, 'CREATED', ?, ?, ?, ?, now(), now());

INSERT INTO order_items (order_item_id, order_id, product_id, seller_id,
                          quantity, unit_price, status, created_at, updated_at)
VALUES (?, ?, ?, ?, ?, ?, 'PENDING', now(), now());  -- one row per item
```

**Reserve inventory (Inventory Service, per item, atomic):**
```sql
UPDATE inventory SET available_qty = available_qty - ?
WHERE product_id = ? AND available_qty >= ?;
-- 0 rows affected => out of stock => Order Service compensates already-reserved items

INSERT INTO inventory_reservations (reservation_id, order_id, order_item_id, product_id,
                                     quantity, status, expires_at, created_at, updated_at)
VALUES (?, ?, ?, ?, ?, 'HELD', now() + interval '15 minutes', now(), now());
```

**Create payment intent (Payment Service):**
```sql
INSERT INTO payment_intents (payment_intent_id, order_id, amount, currency,
                              gateway_session_id, payment_link, status, created_at, updated_at)
VALUES (?, ?, ?, ?, ?, ?, 'CREATED', now(), now());
-- gateway_session_id / payment_link come back from the external gateway's session-create call
```

**Payment webhook received (Payment Service):**
```sql
UPDATE payment_intents SET status = ?, updated_at = now()   -- 'SUCCEEDED' or 'FAILED'
WHERE gateway_session_id = ?;
-- then publish {order_id, payment_intent_id, status} to Kafka topic payment.completed / payment.failed
```

**Consume payment.completed (Order Service):**
```sql
UPDATE orders SET status = 'CONFIRMED', version = version + 1, updated_at = now()
WHERE order_id = ? AND status = 'PENDING_PAYMENT';
UPDATE order_items SET status = 'RESERVED', updated_at = now() WHERE order_id = ?;
```

**Consume payment.completed (Inventory Service) — commit the hold:**
```sql
UPDATE inventory_reservations SET status = 'COMMITTED', updated_at = now()
WHERE order_id = ? AND status = 'HELD';
-- no change to available_qty: it was already decremented at reserve time
```

**Consume payment.failed, or reaper sweep on expiry (Inventory Service) — release the hold:**
```sql
UPDATE inventory_reservations SET status = 'RELEASED', updated_at = now()
WHERE order_id = ? AND status = 'HELD';
UPDATE inventory SET available_qty = available_qty + r.quantity
FROM inventory_reservations r
WHERE inventory.product_id = r.product_id AND r.order_id = ? AND r.status = 'RELEASED';
```

**Get order details:**
```sql
SELECT * FROM orders WHERE order_id = ?;
SELECT * FROM order_items WHERE order_id = ?;
```

**List my orders (paginated):**
```sql
SELECT * FROM orders
WHERE user_id = ? AND created_at < ?   -- cursor
ORDER BY created_at DESC LIMIT ?;
```

**Cancel a line item:**
```sql
UPDATE order_items SET status = 'CANCELLED', updated_at = now()
WHERE order_item_id = ? AND status IN ('PENDING', 'RESERVED');
-- Order Service then calls Inventory Service to release that item's reservation (same
-- release query as above, scoped to order_item_id)
```

**Ship / deliver item (fulfillment webhook, Order Service):**
```sql
UPDATE order_items SET status = 'SHIPPED', shipment_id = ?, updated_at = now()
WHERE order_item_id = ?;
-- order-level status recomputed from item statuses (application logic or a trigger)
```

## 9. Read/Write Paths

**Write path — place order (sync leg, all inside the checkout request):**
1. Client → Order Service, `POST /orders` with `Idempotency-Key`.
2. Order Service inserts idempotency key (unique constraint dedups
   retries) + order (`CREATED`) + order_items, in one local transaction.
3. Order Service calls Inventory Service `POST /internal/inventory/reserve`
   for all items. Inventory Service does the atomic conditional
   decrement per item and inserts `HELD` reservations. Any item failing
   → Inventory Service reports which failed → Order Service compensates
   by asking Inventory Service to release the items that *did* succeed,
   and the order moves to a failed terminal state; client gets an
   out-of-stock error.
4. On full reservation success, order → `PENDING_PAYMENT`. Order Service
   calls Payment Service `POST /internal/payments/intents`, which creates
   a gateway session and returns a `paymentLink`.
5. Order Service returns `{orderId, paymentLink}` to the client. **This
   is where the synchronous request ends** — the client is redirected to
   the gateway to actually pay.

**Write path — payment completion (async leg, out of band):**
6. Customer completes (or abandons) payment at the gateway.
7. If completed: gateway → Payment Service `POST /internal/payments/webhook`
   (signature-verified) → `payment_intents.status = SUCCEEDED` → Payment
   Service publishes `payment.completed` to Kafka, keyed by `order_id`.
8. Order Service consumes the event → order → `CONFIRMED`, items →
   `RESERVED` → emits `order.lifecycle: OrderConfirmed` for
   notification/analytics/search consumers.
9. Inventory Service consumes the *same* event independently → commits
   the reservation (`HELD → COMMITTED`) — this is the "reserved item
   removed from the count" step: the hold is finalized, no longer
   pending, `available_qty` doesn't move again since it was already
   decremented at reserve time.
10. If the gateway instead reports failure, or a reservation sits `HELD`
    past its `expires_at` with no webhook ever arriving (abandoned
    payment, caught by the background reaper): Inventory Service releases
    the hold and restores `available_qty`; Order Service moves the order
    to a `PAYMENT_FAILED`/cancelled state.
11. Fulfillment service ships items independently → webhook per item →
    item → `SHIPPED` → order-level status recomputed → event emitted →
    eventually `DELIVERED`.

**Read path — order details:** check Redis cache keyed by `order_id`
(orders change state infrequently relative to how often they're
polled/viewed) → on miss, read from Order Service's DB read replica,
populate cache.

**Read path — order history:** Order Service DB read replica, indexed on
`(user_id, created_at DESC)`, cursor pagination — not cached by default
since it's a moving list, though the first page can be cached briefly.

## 10. Scale Justification

Target: 10K orders/sec at peak, ~50K QPS reads.

- **Order Service write throughput:** 10K orders/sec, ~2.5 items/order
  average → ~25K `order_items` inserts/sec. A single Postgres primary
  comfortably handles roughly 5–15K simple writes/sec — short of 10K
  order-transactions/sec at peak. Shard `orders` (and co-located
  `order_items`) by `hash(user_id)` across ~16 shards → ~625 orders/sec
  per shard, comfortably within a single primary's capacity.
- **Inventory Service write throughput:** same 10K/sec reserve calls,
  now on an independent DB/cluster from Order Service, so the two no
  longer contend for the same write capacity. Shard by `hash(product_id)`.
- **Inventory hot-key:** a single viral SKU can see all 10K/sec of
  checkout traffic converge on one inventory row. A single-row UPDATE
  under Postgres row-locking realistically tops out around 1–5K TPS on
  that one row — short of worst-case demand. Mitigate with a
  Redis-based atomic counter (`DECRBY` / Lua script) fronting the
  hottest SKUs specifically, capable of 100K+ ops/sec, with async
  write-behind reconciliation to the SQL source of truth.
- **Kafka throughput:** `payment.completed`/`payment.failed` peak at the
  same order rate, ~10K events/sec. Partitioned by `order_id`, a modest
  partition count (e.g. 32–64) comfortably handles this with two
  consumer groups (Order Service, Inventory Service) each scaling
  independently; per-partition ordering guarantees an order's own
  events are processed in sequence.
- **Read throughput:** 50K QPS is highly cacheable — order status doesn't
  change every second, so a Redis cache keyed by `order_id` with a
  90%+ hit ratio drops DB read load to ~5K QPS, spread across read
  replicas per shard.
- **Idempotency table growth:** at 10K orders/sec sustained for a 1-hour
  peak window, ~36M keys accumulate; a TTL-based cleanup job (e.g. purge
  keys older than 24h) keeps this table bounded.

## Implementation Notes

_(none yet — see `/implementation` for focused deep dives, e.g. the
inventory reservation Lua script, the SAGA orchestrator's compensation
logic, or the reservation-expiry reaper job)_
