---
service_name: Payment Gateway
grouping: (ungrouped)
status: Deep Dive Ready
labels: [SQL]
sections_complete: 10
last_session: 2026-08-12
notion_url: TBD
---

**Diagram:** `systems/diagrams/payment-gateway.drawio` (single page —
processor failover, and why it can't be naive)

**Interactive trace:** `systems/implementations/payment-gateway-trace.html`
— a charge that times out against the primary processor, gets checked
before ever touching a backup, and only fails over once that
uncertainty is resolved

## 1. Requirement Gathering

**Functional**
- Accept a charge request (a tokenized payment method, not raw card
  data), route it to a payment processor, return success/failure,
  support refunds.
- This is the actual system behind the "Payment Service" that
  `amazon-order-management-system.md` and `movie-ticket-booking.md`
  both called out to without building.

**Non-functional**
- **PCI compliance**: raw card numbers never touch this system's own
  storage — tokenization happens at a PCI-compliant vault (commonly an
  outsourced provider), and this system only ever handles opaque tokens.
- **Idempotency is critical**: a retried charge request (client
  timeout, network blip) must never double-charge — the same
  requirement `amazon-order-management-system.md` already has, but
  here the stakes are the literal transaction, not an order record.
- **Processor failover without double-charging across processors** —
  the genuinely hard problem this system exists to solve, detailed in
  section 5.

## 2. Queries in Plain English

- Charge a payment method.
- Refund a transaction.
- Get a transaction's status.

## 3. State Diagram

```
Transaction:  PENDING → SUCCEEDED / FAILED
                  ↓
              UNCERTAIN (processor timed out — must resolve before any retry)
```

## 4. API Endpoints

| Endpoint | Notes |
|---|---|
| `POST /charges` | body: `{idempotencyKey, token, amount}` |
| `POST /charges/{id}/refund` | |
| `GET /charges/{id}` | |

## 5. Concurrency Requirements

**Idempotency key, same shape as elsewhere in this repo** — a unique
constraint on `idempotency_key` means a retried charge request
resolves to the already-existing transaction instead of creating a
second one.

**Processor failover — the part that's genuinely tricky.** If the
primary processor (say, Stripe) is unreachable *before* the request is
even sent, failing over to a backup processor is safe and simple. But
if the primary processor was reached and then **timed out** — no
response received — the request may have actually succeeded on their
end; the network failure was on the *response*, not the charge itself.
Blindly retrying against a backup processor in that state risks
charging the customer twice, on two different processors, for the same
purchase. The correct sequence is:
1. On timeout (not outright rejection), **query the primary
   processor's own status endpoint** for that idempotency key before
   doing anything else.
2. If the primary confirms the charge succeeded, record it as
   `SUCCEEDED` — no retry, no failover, nothing further needed.
3. If the primary confirms it genuinely failed (or has no record of
   it), only *then* is it safe to attempt the backup processor.
4. If the primary's status check itself is unreachable, the
   transaction stays `UNCERTAIN` and is retried against status checks
   with backoff — it does **not** fail over while genuinely unresolved.

This is the same "don't act on an assumption when you can check" spirit
as `key-value-storeba.md`'s read-repair, applied to a domain where
guessing wrong costs a customer real money.

## 6. Database Choice + Justification

**SQL**, same reasoning as `digital-wallet.md` — this is money-adjacent
data needing real transactional guarantees, not a candidate for
Redis/Cassandra's eventual-consistency trade-offs. Card tokens
themselves are **not stored here at all** — token vaulting is
delegated to a dedicated PCI-compliant provider specifically to keep
this system (and everything that talks to it) out of the strictest
PCI compliance scope.

## 7. Database Schema

```sql
CREATE TABLE transactions (
  transaction_id    BIGINT PRIMARY KEY,
  idempotency_key   VARCHAR(64) NOT NULL,
  amount            DECIMAL(10,2) NOT NULL,
  status            VARCHAR(20) NOT NULL,   -- PENDING, UNCERTAIN, SUCCEEDED, FAILED
  processor         VARCHAR(20) NOT NULL,   -- which processor ultimately handled it
  processor_ref     VARCHAR(100),
  created_at        TIMESTAMP NOT NULL
);
CREATE UNIQUE INDEX idx_txn_idempotency ON transactions(idempotency_key);
```

## 8. Detailed Queries

```sql
INSERT INTO transactions (transaction_id, idempotency_key, amount, status, processor, created_at)
VALUES (?, ?, ?, 'PENDING', 'stripe', now());
-- unique-constraint violation == duplicate request, return the existing transaction instead

UPDATE transactions SET status = 'UNCERTAIN' WHERE transaction_id = ?;   -- primary timed out
UPDATE transactions SET status = 'SUCCEEDED', processor_ref = ? WHERE transaction_id = ?;   -- status check confirmed it
```

## 9. Read/Write Paths

**Charge path:** idempotency check → insert `PENDING` → call primary
processor with a bounded timeout → on a clean response (success or
explicit decline), record the final status directly → on a *timeout*,
mark `UNCERTAIN` and query the primary's own status endpoint before
any further action → only on a confirmed failure does the request go
to a backup processor.

**Refund path:** same idempotency discipline, against the specific
`processor` and `processor_ref` recorded for the original transaction
— refunds must go back through the processor that actually handled the
charge, not whichever one is currently primary.

## 10. Scale Justification

Bounded by real transaction volume, same as `digital-wallet.md` — this
isn't a viral-traffic system. The design emphasis is entirely on
correctness under partial failure (the timeout/uncertain state
handling in section 5), not raw throughput.

## Implementation Notes

_(none yet beyond the interactive trace linked above)_
