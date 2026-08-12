---
service_name: Key Value StoreBa
grouping: Simple Cassandra Based Systems
status: Deep Dive Ready
labels: [cassandra]
sections_complete: 10
last_session: 2026-08-12
notion_url: TBD
---

**Diagram:** `systems/diagrams/key-value-storeba.drawio` (page 1:
consistent-hash ring + quorum write; page 2: node-local storage
architecture)

**Interactive trace:** `systems/implementations/key-value-storeba-trace.html`
— a quorum write to 3 replicas where one is temporarily down, and how
it catches up

**This is the system underneath the label.** Every other system in
this repo that's labeled `cassandra` (`notification-system.md`,
`netfilx.md`, `uber-find-nearby-driver.md`, `chat-systems.md`,
`url-shortner.md`) has been treating Cassandra as a given. This is
where that label actually gets explained.

## 1. Requirement Gathering

**Functional**
- `PUT(key, value)`, `GET(key)`, `DELETE(key)` — deliberately minimal;
  this is the primitive every other system's "simple partition-key
  access" reasoning has been resting on.

**Non-functional**
- Horizontally scalable across many commodity nodes.
- Highly available and partition-tolerant — this system explicitly
  chooses **AP over strict CP** on the CAP triangle, the same choice
  real Cassandra makes. A node being unreachable should degrade
  gracefully, not block all writes.
- Tunable consistency per operation, not a single fixed guarantee.

## 2. Queries in Plain English

- Put a value for a key.
- Get the value for a key.
- Delete a key.

## 3. State Diagram

Doesn't apply, same as `leaderboard.md` — a key/value pair exists or it
doesn't; there's no lifecycle to a stored value beyond that.

## 4. API Endpoints

| Endpoint | Notes |
|---|---|
| `PUT /kv/{key}` | body: `{value}` |
| `GET /kv/{key}` | |
| `DELETE /kv/{key}` | |

## 5. Concurrency Requirements

This section *is* the system — four mechanisms working together:

**Consistent hashing** places both keys and nodes on a hash ring. A key
belongs to the first N nodes clockwise from its hash position (its
"preference list"). The payoff: when a node joins or leaves, only the
keys adjacent to it on the ring move — not a full remap of the entire
keyspace, which is what a naive `hash(key) % node_count` scheme would
force on every membership change.

**Replication + quorum reads/writes.** Each key is replicated to N
nodes. A write succeeds once **W** replicas acknowledge it; a read
queries **R** replicas and reconciles. `W + R > N` guarantees every
read overlaps at least one replica that saw the most recent write —
tunable per operation: `W=1, R=1` favors latency and availability;
`W=N, R=1` or similar favors stronger consistency at the cost of write
availability during a partition.

**Conflict resolution: last-write-wins by timestamp.** When two writes
to the same key land on different replicas before they've synced
(concurrent updates during a partition, or just normal replication
lag), the value with the later timestamp wins on read reconciliation.
This is simpler than the vector-clock approach the original Dynamo
paper uses (which can detect *genuine* concurrent conflicts and
surface both versions to the application) — LWW is what real Cassandra
actually defaults to, trading perfect conflict detection for
simplicity, and it's the right default for most workloads in this
repo (watch progress, location pings) where "the newer value wins" is
already the desired semantics anyway.

**Gossip protocol for membership and failure detection.** Nodes don't
rely on a central registry of who's alive — each node periodically
exchanges its known cluster state with a few random peers, and that
state propagates through the cluster in O(log N) rounds. This is the
mechanism `concepts/gossip-protocol.md` (not yet created) should own in
full theoretical depth; this system gives the essential shape it plays
in practice.

**Hinted handoff:** if a replica is temporarily unreachable during a
write, another node holds a "hint" (the write, plus who it was really
meant for) and replays it once that replica recovers — this is what
lets a quorum write succeed and still eventually reach every replica
without blocking on a down node.

## 6. Database Choice + Justification

This system *is* the database — there's no separate backing store to
choose. Each node's **local** storage is an LSM-tree (memtable +
immutable SSTables + background compaction), the same structure real
Cassandra uses internally: writes land in an in-memory memtable and an
append-only commit log first (fast, sequential), get flushed to
immutable SSTables on disk, and periodic compaction merges/cleans them
up. This is what makes writes cheap regardless of overall data size —
exactly why every "write-heavy, simple access pattern" system elsewhere
in this repo reaches for Cassandra.

## 7. Database Schema

Not relational — each stored key carries its value plus replication
metadata:
```
key        -> { value, timestamp, replica_set: [node_a, node_b, node_c] }
```

## 8. Detailed Queries

Not SQL — the "query" is the coordination logic:
```
PUT(key, value):
  replicas = consistent_hash_ring.preference_list(key, N=3)
  write(value, timestamp=now()) to all 3 replicas in parallel
  wait for W=2 acks -> return success
  (3rd ack, if it arrives late, still applies -- or a hint is stored if it's down)

GET(key):
  replicas = consistent_hash_ring.preference_list(key, N=3)
  read from R=2 replicas in parallel
  if timestamps differ: return the value with the later timestamp
  (optionally trigger read repair: push the winning value to the stale replica)
```

## 9. Read/Write Paths

**Write path:** client's request lands on any node (the "coordinator"
for this operation, not a fixed role) → coordinator computes the
key's replica set from the hash ring → writes to all N replicas in
parallel → returns success once W acknowledge → if a replica is down,
a hint is stored elsewhere and replayed on recovery (hinted handoff).

**Read path:** coordinator reads from R replicas in parallel →
reconciles by timestamp (LWW) → optionally repairs the stale replica in
the background → returns the winning value.

## 10. Scale Justification

- **Node join/leave cost:** consistent hashing means only the keys
  adjacent to the changed node on the ring need to move — roughly
  `1/N` of the keyspace for an N-node cluster, not a full reshuffle.
- **Membership propagation:** gossip converges cluster-wide state in
  O(log N) rounds regardless of cluster size, avoiding a central
  registry that would itself become a bottleneck/single point of
  failure.
- **Write throughput per node:** bounded by the LSM-tree's sequential
  write path (memtable + commit log), not by disk seek time — this is
  the same property that makes every write-heavy system in this repo
  (`notification-system.md`, `netfilx.md`, `chat-systems.md`) reach for
  this storage engine.

## Implementation Notes

_(none yet beyond the interactive trace linked above)_
