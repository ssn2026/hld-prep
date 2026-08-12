---
service_name: Unique Id Generator
grouping: Simple Cassandra Based Systems
status: Deep Dive Ready
labels: [SQL]
sections_complete: 10
last_session: 2026-08-12
notion_url: TBD
---

**Diagram:** `systems/diagrams/unique-id-generator.drawio` (single page
— startup coordination vs. runtime generation, deliberately separated)

**Interactive trace:** `systems/implementations/unique-id-generator-trace.html`
— a worker claiming its ID once at boot, then generating a burst of IDs
entirely locally

## 1. Requirement Gathering

**Functional**
- Generate globally unique IDs at high throughput across many
  machines, with no central coordination per ID.
- IDs should be roughly time-sortable — this is what makes them usable
  as Cassandra clustering keys, exactly the role `message_id` plays in
  `chat-systems.md` and the batch-allocated codes in
  `url-shortner.md` both gestured at without building.

**Non-functional**
- **The generator must not be a network service in the way most
  "generate an X" systems are.** Calling out to a shared service for
  every single ID would reintroduce the exact bottleneck this system
  exists to avoid — a network round trip and a central point of
  contention on the hottest possible operation. The correct shape is a
  **library embedded in each app server**, with coordination happening
  once, at startup, not per ID.

## 2. Queries in Plain English

- Generate an ID (this is the *only* real operation, and it's local,
  not a network call).
- (Startup only, once per process) claim a unique worker ID.

## 3. State Diagram

Doesn't apply — same as `leaderboard.md`. An ID has no lifecycle; it's
generated once and is immutable forever after.

## 4. API Endpoints

There isn't a client-facing endpoint for ID generation — that would
defeat the design. The only real "endpoint" is internal and rare:

| Endpoint | Notes |
|---|---|
| `POST /internal/worker-id/claim` | called once at process startup, not per ID |

## 5. Concurrency Requirements

**The actual problem: uniqueness across many machines with zero
runtime coordination.** The solution (Twitter Snowflake's approach) is
a composite ID built from three parts, computed entirely locally:

```
[ 41 bits: timestamp (ms) ][ 10 bits: worker ID ][ 12 bits: sequence ]
```

- **Timestamp** — current time in milliseconds, giving rough
  chronological sortability for free.
- **Worker ID** — unique per machine/process, assigned *once* at
  startup (this is the only coordination that ever happens).
- **Sequence** — a local counter that increments for multiple IDs
  generated within the same millisecond on the same worker, resetting
  every millisecond.

Two different workers can never collide (different worker-ID bits);
the same worker can never collide with itself (the sequence counter is
local and monotonic within a millisecond). No lock, no shared counter,
no network call — this is the "avoid coordination via composite
identity" pattern, one level more radical than the atomic-operation
patterns elsewhere in this repo, since it avoids even a *local* shared
resource across requests.

**Startup coordination, the one exception:** claiming a worker ID does
need a uniqueness guarantee — two processes can't be assigned the same
ID. A single `INSERT ... ON CONFLICT DO NOTHING` (or equivalent) against
a small registry table handles this, and it happens once per process
lifetime, not once per ID — the cost is amortized to nothing.

## 6. Database Choice + Justification

**Almost no database is involved in the actual generation path — that
is the design.** The only persistent state is the worker-ID registry,
a small table touched once per process startup:
```sql
CREATE TABLE worker_id_registry (
  worker_id    SMALLINT PRIMARY KEY,   -- 0-1023 (10 bits)
  assigned_to  VARCHAR(100),
  assigned_at  TIMESTAMP
);
```
SQL is more than sufficient here — this table sees perhaps a few
writes per deploy, not per request. Reaching for anything more
elaborate would be solving a scale problem that doesn't exist at this
layer.

## 7. Database Schema

Already shown above — one small table, no other schema needed. There
is no "IDs" table; generated IDs are never stored by this system,
only used by whichever caller requested one.

## 8. Detailed Queries

```sql
-- claim a worker ID (once, at startup)
INSERT INTO worker_id_registry (worker_id, assigned_to, assigned_at)
VALUES (?, ?, now())
ON CONFLICT (worker_id) DO NOTHING;   -- try IDs in sequence until one succeeds
```

Generation itself has no query — it's arithmetic:
```
id = (now_ms << 22) | (worker_id << 12) | sequence
```

## 9. Read/Write Paths

**Startup path (once):** process attempts to claim worker IDs in
order until an `INSERT ... ON CONFLICT DO NOTHING` actually inserts a
row — that's its assigned worker ID for the rest of its lifetime.

**Generation path (the hot path, and it's entirely local):** read the
current timestamp, bit-shift and OR together with the worker ID and
the local sequence counter, return. No database, no network, no lock
across requests — the entire operation is a few CPU instructions.

## 10. Scale Justification

- **Per-worker throughput:** a 12-bit sequence allows 4,096 IDs per
  millisecond per worker — roughly 4.1M IDs/sec, purely bounded by
  local CPU, before ever needing a second worker.
- **Horizontal scale:** adding a worker means claiming one more
  worker-ID row, once — throughput scales linearly with worker count
  with zero coordination overhead added per worker, unlike systems
  where more workers means more contention on a shared resource.
- **The startup registry table** sees load proportional to deploy
  frequency, not request volume — utterly negligible next to anything
  else in this repo.

## Implementation Notes

_(none yet beyond the interactive trace linked above)_
