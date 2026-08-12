---
service_name: Amazon Order Managment System
grouping: Ordering System
status: Deep Dive Ready
labels: [SQL]
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
  never double-charge or double-create an order.
- Availability can be relaxed for order history / search (eventual
  consistency acceptable there).

**Out of scope:** payment processing internals, warehouse routing
logic, catalog/search.

## 2. Queries in Plain English

**User-facing**
- Place an order (checkout: cart items, shipping address, payment method).
- Get order details by order ID.
- List my orders, paginated, filterable by status/date.
- Cancel an order, or cancel a single line item.
- Track order/shipment status.
- Request a return/refund for a delivered order.

**Internal**
- Reserve inventory for order items.
- Capture payment via the Payment service.
- Receive fulfillment webhooks (item shipped / item delivered) and update
  order state.
- Emit order lifecycle events (OrderCreated, OrderConfirmed, OrderShipped,
  OrderDelivered, OrderCancelled) for downstream consumers (notifications,
  analytics, search-index).
- Release an inventory reservation on cancellation or payment failure
  (compensating action).

## 3. State Diagram

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
```

Order status is computed from item statuses (e.g. some items SHIPPED,
others still RESERVED → order shows PARTIALLY_SHIPPED). Cancellation is
only legal while an item is PENDING or RESERVED.

## 4. API Endpoints

**Client-facing**
| Endpoint | Notes |
|---|---|
| `POST /orders` | requires `Idempotency-Key` header |
| `GET /orders/{orderId}` | |
| `GET /orders?userId=&status=&cursor=&limit=` | cursor-based pagination |
| `POST /orders/{orderId}/cancel` | whole order |
| `POST /orders/{orderId}/items/{itemId}/cancel` | single line item |
| `POST /orders/{orderId}/return` | post-delivery |
| `GET /orders/{orderId}/tracking` | |

**Internal**
| Endpoint | Notes |
|---|---|
| `POST /internal/orders/{orderId}/reserve-inventory` | called during checkout |
| `POST /internal/payments/webhook` | payment gateway callback → drives CONFIRMED |
| `POST /internal/orders/{orderId}/items/{itemId}/ship` | from Fulfillment service |
| `POST /internal/orders/{orderId}/items/{itemId}/deliver` | from Fulfillment/carrier |
| `POST /internal/orders/{orderId}/release-inventory` | compensating action (SAGA) |

## 5. Concurrency Requirements

**User-request-level serialization**
- Duplicate checkout (double-click, client retry after timeout) is
  deduped via a client-generated idempotency key stored in an
  `idempotency_keys` table with a unique constraint on `key`; a repeat
  request resolves to the same order instead of creating a new one.
- Order state transitions are serialized per order using a `version`
  column (optimistic concurrency) or `SELECT ... FOR UPDATE` — only one
  writer can move an order `CREATED → CONFIRMED` at a time.

**Resource-level contention**
- The classic hot-row problem: a hyped SKU launch sends thousands of
  concurrent checkouts against the *same* inventory row. A naive
  read-then-write races and oversells. Fix with a single atomic
  conditional UPDATE, no read/write gap:
  ```sql
  UPDATE inventory SET available_qty = available_qty - 1
  WHERE product_id = ? AND available_qty >= 1;
  ```
  Zero rows affected = out of stock. At extreme scale even this hot row
  becomes a bottleneck under lock contention, which is where a
  Redis-backed sharded counter in front of SQL (async-reconciled) comes
  in — see `concepts/distributed-locking.md` (not yet created).
- Order creation spans three separate systems (Order DB, Inventory,
  external Payment service) that cannot share one ACID transaction. This
  is a SAGA: reserve inventory → attempt payment → on failure, run a
  compensating release-inventory action rather than a distributed
  rollback. See `concepts/saga.md` (not yet created).

## 6. Database Choice + Justification

- **Orders + order items → SQL (Postgres/MySQL).** Structured, relational,
  needs multi-row transactional writes (order + its items commit
  together) and strong consistency on state. Shard by `user_id` or
  `order_id` hash once volume outgrows a single primary.
- **Inventory → SQL**, same durability rationale, with the conditional
  atomic-update pattern above handling contention. An optional Redis
  layer can front only the hottest SKUs, reconciled back to SQL
  asynchronously.
- **Order lifecycle events → Kafka.** Fans out OrderCreated/Confirmed/
  Shipped/Delivered to notification, analytics, and search-index
  consumers, decoupling the Order Service so a slow downstream consumer
  can never block a checkout.

## 7. Database Schema

```sql
CREATE TABLE orders (
  order_id           BIGINT PRIMARY KEY,
  user_id             BIGINT NOT NULL,
  status              VARCHAR(20) NOT NULL,   -- CREATED, PENDING_PAYMENT, CONFIRMED, ...
  total_amount        DECIMAL(10,2) NOT NULL,
  currency            CHAR(3) NOT NULL,
  shipping_address_id BIGINT NOT NULL,
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

CREATE TABLE inventory (
  product_id     BIGINT PRIMARY KEY,
  available_qty  INT NOT NULL,
  reserved_qty   INT NOT NULL DEFAULT 0
);

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

## 8. Detailed Queries

**Place order (checkout)** — within one transaction:
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

**Reserve inventory (per item, atomic):**
```sql
UPDATE inventory SET available_qty = available_qty - ?, reserved_qty = reserved_qty + ?
WHERE product_id = ? AND available_qty >= ?;
-- 0 rows affected => out of stock => trigger SAGA compensation for already-reserved items
```

**Confirm order (payment webhook success):**
```sql
UPDATE orders SET status = 'CONFIRMED', version = version + 1, updated_at = now()
WHERE order_id = ? AND status = 'PENDING_PAYMENT' AND version = ?;
UPDATE order_items SET status = 'RESERVED', updated_at = now() WHERE order_id = ?;
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
UPDATE inventory SET available_qty = available_qty + ?, reserved_qty = reserved_qty - ?
WHERE product_id = ?;  -- release
```

**Ship / deliver item (fulfillment webhook):**
```sql
UPDATE order_items SET status = 'SHIPPED', shipment_id = ?, updated_at = now()
WHERE order_item_id = ?;
-- order-level status recomputed from item statuses (application logic or a trigger)
```

## 9. Read/Write Paths

**Write path — place order:**
1. Client → Order Service, `POST /orders` with `Idempotency-Key`.
2. Insert idempotency key (unique constraint dedups retries) + order
   (`CREATED`) + order_items, in one DB transaction.
3. For each item, atomic conditional UPDATE against `inventory`. Any
   failure triggers compensating releases for items already reserved
   (SAGA) and the order moves to a failed/cancelled terminal state.
4. On success, order → `PENDING_PAYMENT`; call Payment service.
5. Payment gateway webhook hits `/internal/payments/webhook` →
   order → `CONFIRMED`, items → `RESERVED`.
6. Emit `OrderConfirmed` to Kafka → notification/analytics/search
   consumers react asynchronously.
7. Fulfillment service ships items independently → webhook per item →
   item → `SHIPPED` → order-level status recomputed → event emitted.
8. Delivery webhook → item → `DELIVERED` → once all items delivered,
   order → `DELIVERED`.

**Read path — order details:** check Redis cache keyed by `order_id`
(orders change state infrequently relative to how often they're
polled/viewed) → on miss, read from a DB read replica, populate cache.

**Read path — order history:** DB read replica, indexed on
`(user_id, created_at DESC)`, cursor pagination — not cached by default
since it's a moving list, though the first page can be cached briefly.

## 10. Scale Justification

Target: 10K orders/sec at peak, ~50K QPS reads.

- **Write throughput:** 10K orders/sec, ~2.5 items/order average → ~25K
  `order_items` inserts/sec. A single Postgres primary comfortably
  handles roughly 5–15K simple writes/sec depending on tuning/hardware —
  well short of 10K order-transactions/sec at peak. Shard `orders` (and
  co-located `order_items`) by `hash(user_id)` across ~16 shards →
  ~625 orders/sec per shard, comfortably within a single primary's
  capacity, with room to grow.
- **Read throughput:** 50K QPS is highly cacheable — order status doesn't
  change every second, so a Redis cache keyed by `order_id` with a
  90%+ hit ratio drops DB read load to ~5K QPS, spread across read
  replicas per shard.
- **Inventory hot-key:** a single viral SKU can see all 10K/sec of
  checkout traffic converge on one inventory row. A single-row UPDATE
  under Postgres row-locking realistically tops out around 1–5K TPS on
  that one row — short of worst-case demand. Mitigate with a
  Redis-based atomic counter (`DECRBY` / Lua script) fronting the
  hottest SKUs specifically, capable of 100K+ ops/sec, with async
  write-behind reconciliation to the SQL source of truth.
- **Idempotency table growth:** at 10K orders/sec sustained for a 1-hour
  peak window, ~36M keys accumulate; a TTL-based cleanup job (e.g. purge
  keys older than 24h) keeps this table bounded.

## Implementation Notes

_(none yet — see `/implementation` for focused deep dives, e.g. the
inventory reservation Lua script, or the SAGA orchestrator)_
