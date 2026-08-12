---
service_name: Click Event Aggregator
grouping: (ungrouped)
status: Deep Dive Ready
labels: [Kafka, cassandra]
sections_complete: 10
last_session: 2026-08-12
notion_url: TBD
---

**Diagram:** `systems/diagrams/click-event-aggregator.drawio` (single
page — ingest, windowed aggregation, and the watermark for late events)

**Interactive trace:** `systems/implementations/click-event-aggregator-trace.html`
— a 1-minute window accumulating clicks, a late-arriving event still
inside the grace period, and the window finalizing

## 1. Requirement Gathering

**Functional**
- Ingest high-volume click events from web/app clients.
- Aggregate counts per page over time windows (e.g. clicks per minute).
- Serve aggregated metrics to dashboards.

**Non-functional**
- Massive, bursty write throughput — every click from every active
  user, arriving unevenly.
- Aggregates can be **approximate and slightly delayed** — nobody
  needs a real-time dashboard to be correct to the exact millisecond,
  which is what makes windowed/eventual aggregation acceptable here in
  a way it wouldn't be for, say, payment amounts.

## 2. Queries in Plain English

- Record a click event.
- Get aggregated click counts for a page over a time range.
- Get approximate unique visitor count for a page.

## 3. State Diagram

```
Window:  OPEN (accumulating) → CLOSED (watermark passed, flushed to storage)
```

## 4. API Endpoints

| Endpoint | Notes |
|---|---|
| `POST /events/click` | lightweight — validate and publish, nothing else |
| `GET /pages/{pageId}/metrics?from=&to=` | aggregated, from durable storage |

## 5. Concurrency Requirements

**Ingest is decoupled from aggregation via Kafka**, same fan-out
philosophy as `notification-system.md` — the client-facing endpoint
does the absolute minimum (validate, publish) and returns immediately,
regardless of how backed up aggregation currently is.

**Windowed aggregation, with a watermark for late events.** Events are
grouped into fixed time windows (e.g. tumbling 1-minute windows) per
page. Network delays mean events can arrive slightly out of order — a
**watermark** (a grace period, e.g. 30 seconds past the window's
nominal end) keeps a window open a little longer before finalizing it,
so a click that's a few seconds late still counts. Once the watermark
passes, the window closes, its aggregate flushes to durable storage,
and further events for that window are either dropped or routed to a
separate late-data path — a deliberate, bounded trade-off between
completeness and finite memory, not an oversight.

**Approximate cardinality for unique visitors.** Counting *exact*
unique visitors per page would need to track every visitor ID seen —
unbounded memory as traffic grows. A **HyperLogLog** structure
estimates unique counts within a small, known error margin using a
fixed, tiny amount of memory (a few KB) regardless of whether the true
count is a thousand or a billion — a genuinely different technique from
anything else built in this repo, worth calling out specifically
because "approximate but bounded" is the right trade here, not a
compromise.

## 6. Database Choice + Justification

- **Ingest buffer → Kafka.** Absorbs bursts, decouples the cheap
  ingest path from the more expensive aggregation work, and its
  retention window doubles as a practical raw-event log for
  replay/debugging without needing a separate durable store for raw
  events.
- **Aggregated results → Cassandra**, time-series shaped: partitioned
  by `page_id`, clustered by time bucket — the same
  write-heavy/simple-access-pattern reasoning as every other
  Cassandra-labeled system in this repo, applied to aggregates instead
  of raw events.

## 7. Database Schema

```sql
CREATE TABLE page_metrics (
  page_id      TEXT,
  window_start TIMESTAMP,
  click_count  BIGINT,
  unique_visitors_estimate BIGINT,
  PRIMARY KEY (page_id, window_start)
) WITH CLUSTERING ORDER BY (window_start DESC);
```

## 8. Detailed Queries

```sql
SELECT click_count, unique_visitors_estimate FROM page_metrics
WHERE page_id = ? AND window_start >= ? AND window_start < ?;
```

## 9. Read/Write Paths

**Write path:** client click → `POST /events/click` → publish to
`click.events` (Kafka) → stream processor consumes, groups by
`(page_id, tumbling 1-min window)`, increments an in-memory counter and
updates the HyperLogLog sketch for that window → once the watermark
passes for that window, flush the final `click_count` and
`unique_visitors_estimate` to Cassandra, then discard the in-memory
state for that window.

**Read path:** dashboard queries `page_metrics` directly — a normal
Cassandra range read by `page_id` and time window, no stream processing
involved on the read side at all.

## 10. Scale Justification

- **Ingest parallelism** is bounded by Kafka partition count — more
  partitions and more stream-processing instances (one per partition,
  standard consumer-group semantics) scale ingest and aggregation
  together, horizontally.
- **HyperLogLog keeps memory bounded** regardless of actual traffic —
  this is the specific mechanism that keeps a viral page's unique-visitor
  tracking from ever becoming a memory problem, unlike a naive
  set-of-seen-IDs approach.
- **Cassandra write throughput** for the (comparatively low-volume,
  since it's aggregates not raw events) flush-on-window-close writes is
  far below what this repo's other Cassandra-labeled systems already
  handle at raw-event volume.

## Implementation Notes

_(none yet beyond the interactive trace linked above)_
