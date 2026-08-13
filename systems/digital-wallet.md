---
service_name: Digital Wallet
grouping: (ungrouped)
status: Deep Dive Ready
labels: [SQL]
sections_complete: 10
last_session: 2026-08-12
notion_url: TBD
---

**Diagram:** `systems/diagrams/digital-wallet.drawio` (single page —
double-entry transfer, both legs in one transaction)

**Interactive trace:** `systems/implementations/digital-wallet-trace.html`
— a transfer between two accounts as two ledger entries in one atomic
transaction, and an insufficient-balance attempt that rolls back
cleanly

## 1. Requirement Gathering

**Functional**
- Hold a balance per account; transfer between accounts; deposit/withdraw.

**Non-functional — the reason this system reads differently from most
of this repo:** money has to be **exactly** correct, always. Not
"eventually consistent," not "approximately right," not "stale by a
few seconds is fine" — every other system in this repo has found a
place to relax consistency where the domain allows it
(`leaderboard.md`'s scores, `broadcasting-system.md`'s viewer counts,
`nearyby-friends.md`'s location). A wallet balance has no such
tolerance. This is the system where strict ACID SQL transactions are
the obviously correct choice, not a default to question.

## 2. Queries in Plain English

- Get account balance.
- Transfer between two accounts.
- Deposit / withdraw.

## 3. State Diagram

```
Transaction:  PENDING → COMMITTED / ROLLED_BACK
```

## 4. API Endpoints

| Endpoint | Notes |
|---|---|
| `GET /accounts/{id}/balance` | |
| `POST /transfers` | body: `{fromAccountId, toAccountId, amount}` |

## 5. Concurrency Requirements

**Double-entry bookkeeping, not a mutable balance column.** Every
transfer writes **two** ledger entries in the same transaction — a
debit from the source account and a credit to the destination, for the
same amount, tied together by a shared `transaction_id`. This isn't
just an audit-trail nicety: it makes the system **self-verifying** —
the sum of every ledger entry across the whole system should always be
exactly zero, and any drift is detectable by summing, not something
that has to be trusted blindly the way a bare balance counter would.

**Balance is a cached, derived value, not the source of truth.** The
true balance is the sum of an account's ledger entries; a
`balance_cache` column exists purely so reads don't have to sum a
growing history every time, updated transactionally alongside the
ledger entries that justify it — never mutated independently.

**Concurrent transfers use real row locks, in a fixed order.** A
transfer between accounts A and B locks both rows
(`SELECT ... FOR UPDATE`) — but **always in a consistent order** (e.g.
by `account_id` ascending), regardless of which account is the sender
in this particular transfer. Two concurrent transfers moving money in
opposite directions between the same pair of accounts would deadlock
if each locked its "from" account first; locking by a fixed global
order instead means both transactions request locks in the same
sequence, and one simply waits for the other rather than the two
waiting on each other forever.

## 6. Database Choice + Justification

**SQL, unambiguously — no Redis, no Cassandra, anywhere in the core
ledger.** This is a deliberate departure from this repo's general
leaning toward eventual consistency and lock-free atomic operations:
money needs real ACID transactions (`BEGIN` ... two inserts ... one or
two balance updates ... `COMMIT`, all-or-nothing), foreign key
constraints, and the ability to roll back an entire multi-statement
operation on any failure. None of the mechanisms built elsewhere in
this repo (atomic counters, TTL locks, quorum writes) substitute for
genuine transactional correctness here.

## 7. Database Schema

```sql
CREATE TABLE accounts (
  account_id     BIGINT PRIMARY KEY,
  balance_cache  DECIMAL(14,2) NOT NULL DEFAULT 0
);

CREATE TABLE ledger_entries (
  entry_id        BIGINT PRIMARY KEY,
  transaction_id  BIGINT NOT NULL,
  account_id      BIGINT NOT NULL REFERENCES accounts(account_id),
  amount          DECIMAL(14,2) NOT NULL,   -- positive for credit, negative for debit
  entry_type      VARCHAR(10) NOT NULL,     -- DEBIT, CREDIT
  created_at      TIMESTAMP NOT NULL
);
CREATE INDEX idx_ledger_account ON ledger_entries(account_id, created_at);
```

## 8. Detailed Queries

```sql
BEGIN;

SELECT balance_cache FROM accounts WHERE account_id = ? FOR UPDATE;  -- lower account_id first, always
SELECT balance_cache FROM accounts WHERE account_id = ? FOR UPDATE;  -- higher account_id second

-- application checks sufficient balance here; ROLLBACK if not

INSERT INTO ledger_entries (entry_id, transaction_id, account_id, amount, entry_type, created_at)
VALUES (?, ?, 'A-1', -50.00, 'DEBIT', now());
INSERT INTO ledger_entries (entry_id, transaction_id, account_id, amount, entry_type, created_at)
VALUES (?, ?, 'A-2', 50.00, 'CREDIT', now());

UPDATE accounts SET balance_cache = balance_cache - 50.00 WHERE account_id = 'A-1';
UPDATE accounts SET balance_cache = balance_cache + 50.00 WHERE account_id = 'A-2';

COMMIT;
```

## 9. Read/Write Paths

**Transfer path:** open a transaction → lock both accounts in a fixed
order → verify sufficient balance → insert both ledger entries →
update both balance caches → commit. Any failure at any step rolls
back the *entire* transaction — there is never a state where a debit
exists without its matching credit.

**Read path:** `GET /accounts/{id}/balance` reads `balance_cache`
directly — fast, and correct because it's kept in lockstep with the
ledger by the same transaction that ever changes it.

## 10. Scale Justification

Deliberately not the emphasis here — a wallet system's transaction
volume is bounded by real economic activity, not viral traffic
patterns, and correctness is worth far more than raw throughput in
this domain. If sharding by `account_id` is ever needed, the design
constraint becomes keeping both legs of a transfer on the same shard
when possible; a transfer that must cross shards would need a
saga-style compensating-action approach (same shape as
`amazon-order-management-system.md`'s checkout saga) rather than a
single ACID transaction — an explicit trade-off to make consciously,
not a default to reach for early.

## Implementation Notes

_(none yet beyond the interactive trace linked above)_
