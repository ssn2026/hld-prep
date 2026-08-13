---
service_name: Stock Broker
grouping: (ungrouped)
status: Deep Dive Ready
labels: [SQL, Redis]
sections_complete: 10
last_session: 2026-08-12
notion_url: TBD
---

**Diagram:** `systems/diagrams/stock-broker.drawio` (single page — one
matching engine per symbol, market data fan-out)

**Interactive trace:** `systems/implementations/stock-broker-trace.html`
— a buy and a sell order matching in price-time priority, then
settling through a double-entry ledger

## 1. Requirement Gathering

**Functional**
- Place buy/sell orders (market and limit); match against the order
  book; settle matched trades (move shares and cash); stream live
  price updates to connected clients.

**Non-functional**
- Scoped as a **retail brokerage app**, not an HFT exchange — the
  latency bar is "responsive," not microseconds. What still matters
  absolutely: order matching must be **strictly sequential per
  symbol** (processing two orders for the same stock out of order is
  a correctness and fairness bug, not just a performance concern), and
  settlement needs `digital-wallet.md`-grade correctness — this
  literally is money and shares.

## 2. Queries in Plain English

- Place a buy/sell order.
- Get the current order book / best bid-ask for a symbol.
- Subscribe to live price updates for a symbol.
- Get portfolio holdings.

## 3. State Diagram

```
Order:  PLACED → PARTIALLY_FILLED → FILLED
              ↓
          CANCELLED
```

## 4. API Endpoints

| Endpoint | Notes |
|---|---|
| `POST /orders` | body: `{symbol, side, type, quantity, limitPrice?}` |
| `POST /orders/{id}/cancel` | |
| WebSocket `/market-data/{symbol}` | live price ticks |
| `GET /portfolio` | |

## 5. Concurrency Requirements

**A third concurrency strategy, alongside atomic ops and locks.**
`flash-sale-scaling.md` avoids coordination via atomic operations;
`movie-ticket-booking.md` uses an actual distributed lock. Order
matching uses a different technique entirely: **single-writer
ownership per partition.** Each symbol's order book is owned by
exactly one matching-engine instance/thread — no other process ever
touches AAPL's book but the one engine responsible for AAPL. Because
there's structurally only one writer, there's no race to prevent in
the first place; correctness comes from partitioning the *ownership*,
not from coordinating *access*. This is the right tool specifically
because matching genuinely must be sequential — a lock would just
serialize access to something that needed to be sequential anyway, so
skip the lock and assign a sole owner instead.

**Matching itself is price-time priority**: within a symbol's book,
buy orders are sorted by price (highest first), sell orders by price
(lowest first); at equal prices, earlier orders match first. A
matching engine repeatedly pairs the best bid against the best ask
whenever they cross.

**Settlement reuses `digital-wallet.md`'s double-entry ledger
unchanged** — a matched trade debits the buyer's cash and credits the
seller's, credits the buyer's share holding and debits the seller's,
all four legs in one transaction.

**Market data fan-out reuses `chat-systems.md`'s connection registry**
— routing live price ticks to whichever connection server holds each
subscribed client's socket, at potentially very high fan-out for a
popular symbol (same shape `broadcasting-system.md`'s chat flagged as
needing Kafka-routed fan-out past a threshold).

## 6. Database Choice + Justification

- **Order book → in-memory, owned per symbol** by its matching engine
  — not a general-purpose database at all, same reasoning as
  `google-maps.md`'s in-memory road graph: a specialized structure for
  a specialized, latency-sensitive access pattern.
- **Trade/settlement ledger → SQL**, identical double-entry reasoning
  to `digital-wallet.md` — this is money, strict ACID transactions are
  the correct and non-negotiable choice.
- **Market data → ephemeral push, not persisted per-tick.** Only
  periodic OHLC (open/high/low/close) candles get written durably, to
  Cassandra, time-series shaped like `click-event-aggregator.md`'s
  aggregates — persisting every single tick would be enormous write
  volume for data nobody queries at that granularity after the fact.

## 7. Database Schema

```sql
CREATE TABLE orders (order_id BIGINT PRIMARY KEY, symbol VARCHAR(10), side VARCHAR(4), quantity INT, limit_price DECIMAL(10,2), status VARCHAR(20));
CREATE TABLE ledger_entries (entry_id BIGINT PRIMARY KEY, transaction_id BIGINT, account_id BIGINT, asset VARCHAR(10), amount DECIMAL(14,4), entry_type VARCHAR(10));
```
Cassandra: `ohlc_candles(symbol, interval_start, open, high, low, close)`,
partitioned by symbol.

## 8. Detailed Queries

Order matching is in-memory logic, not a SQL query. Settlement, once a
match occurs:
```sql
BEGIN;
INSERT INTO ledger_entries (...) VALUES (?, ?, 'buyer', 'USD', -1500.00, 'DEBIT');
INSERT INTO ledger_entries (...) VALUES (?, ?, 'seller', 'USD', 1500.00, 'CREDIT');
INSERT INTO ledger_entries (...) VALUES (?, ?, 'buyer', 'AAPL', 10, 'CREDIT');
INSERT INTO ledger_entries (...) VALUES (?, ?, 'seller', 'AAPL', -10, 'DEBIT');
COMMIT;
```

## 9. Read/Write Paths

**Order path:** client places an order → routed to the matching engine
that owns that symbol → order enters the book, matched immediately
against any crossing orders or held pending → on a match, settlement
fires the four-leg ledger transaction above → both parties' orders
update to `FILLED`/`PARTIALLY_FILLED`.

**Market data path:** every price-moving event (a match) publishes a
tick → routed via the connection registry to every subscribed client's
live connection, same mechanism as `chat-systems.md`'s message
delivery.

## 10. Scale Justification

- **Matching scales by symbol, not globally** — thousands of symbols
  each get their own single-writer engine; adding capacity means
  adding engine instances for different symbol shards, never
  coordinating across them, because no order ever needs to compare
  against another symbol's book.
- **Settlement volume** is bounded by actual match rate, not order
  volume — the ledger only writes on a fill, not on every order placed.
- **Market data fan-out** for a popular symbol follows the same
  scaling story as `chat-systems.md`/`broadcasting-system.md`'s chat:
  Kafka-routed fan-out once subscriber count crosses the threshold
  where direct server-to-server routing would explode.

## Implementation Notes

_(none yet beyond the interactive trace linked above)_
