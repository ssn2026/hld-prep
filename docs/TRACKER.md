# HLD Tracker

## Purpose

Human-readable snapshot of progress, kept in sync with the Notion tracker
and the local tool's database. This file is regenerated/updated at the end
of sessions (per the pipeline in `CLAUDE.md`) — treat it as a report, not
something to hand-edit.

## Schema

### Type A — Service Design Systems

**Columns:** Service Name | Grouping | File | Sections Complete (x/10) | Status | Labels | Last Session | Notion URL

**Status values** (mirrors Notion's HLD Status): Not Started, Concepts,
System Flow, Service Flow, Deep Dive Ready, Interview Ready

**Groupings** (mirrors Notion's HLD Grouping): Booking System, Location
Based Systems, Notification System, Ordering System, Rate Limiter, Simple
Cassandra Based Systems, Social Media, Video Based Systems, (ungrouped)

| Service Name | Grouping | File | Sections Complete (x/10) | Status | Labels | Last Session | Notion URL |
|---|---|---|---|---|---|---|---|
| Netfilx | Video Based Systems | not created | 0/10 | System Flow | - | never | TBD — will add in a follow-up step |
| Broadcasting System | Video Based Systems | not created | 0/10 | Not Started | - | never | TBD — will add in a follow-up step |
| Zoom | Video Based Systems | not created | 0/10 | Not Started | - | never | TBD — will add in a follow-up step |
| Youtube | Video Based Systems | not created | 0/10 | Not Started | - | never | TBD — will add in a follow-up step |
| Movie Ticket Booking | Booking System | not created | 0/10 | Not Started | SQL | never | TBD — will add in a follow-up step |
| Click Event Aggregator | (ungrouped) | not created | 0/10 | Not Started | - | never | TBD — will add in a follow-up step |
| Stock Broker | (ungrouped) | not created | 0/10 | Not Started | - | never | TBD — will add in a follow-up step |
| Notification System | Notification System | not created | 0/10 | Not Started | - | never | TBD — will add in a follow-up step |
| Amazon Order Managment System | Ordering System | systems/amazon-order-management-system.md | 10/10 | Deep Dive Ready | SQL, Kafka | 2026-08-12 | TBD — will add in a follow-up step |
| Hotel ReservationSyste | Booking System | not created | 0/10 | Service Flow | SQL | never | TBD — will add in a follow-up step |
| Rate Limiter | Rate Limiter | not created | 0/10 | Service Flow | Redis | never | TBD — will add in a follow-up step |
| Flight Ticket Booking | Booking System | not created | 0/10 | Not Started | SQL | never | TBD — will add in a follow-up step |
| Doctor Appointment | Booking System | not created | 0/10 | Not Started | SQL | never | TBD — will add in a follow-up step |
| Google Maps | Location Based Systems | not created | 0/10 | Not Started | - | never | TBD — will add in a follow-up step |
| Digital Wallet | (ungrouped) | not created | 0/10 | Not Started | SQL | never | TBD — will add in a follow-up step |
| Payment Gateway | (ungrouped) | not created | 0/10 | Not Started | SQL | never | TBD — will add in a follow-up step |
| Google Drive | (ungrouped) | not created | 0/10 | Not Started | - | never | TBD — will add in a follow-up step |
| Redis As cache | (ungrouped) | not created | 0/10 | System Flow | Redis | never | TBD — will add in a follow-up step |
| LeaderBoard | (ungrouped) | not created | 0/10 | Service Flow | Redis | never | TBD — will add in a follow-up step |
| Like and Comment Service | Social Media | not created | 0/10 | Service Flow | Redis, cassandra | never | TBD — will add in a follow-up step |
| Key Value StoreBa | Simple Cassandra Based Systems | not created | 0/10 | Service Flow | cassandra | never | TBD — will add in a follow-up step |
| Unique Id Generator | Simple Cassandra Based Systems | not created | 0/10 | Service Flow | cassandra | never | TBD — will add in a follow-up step |
| URL Shortner | Simple Cassandra Based Systems | not created | 0/10 | Service Flow | cassandra | never | TBD — will add in a follow-up step |
| Uber find nearby driver | Location Based Systems | not created | 0/10 | System Flow | cassandra | never | TBD — will add in a follow-up step |
| Nearyby friends | Location Based Systems | not created | 0/10 | System Flow | Redis | never | TBD — will add in a follow-up step |
| Proximity ServiceBase | Location Based Systems | not created | 0/10 | System Flow | SQL | never | TBD — will add in a follow-up step |
| News Feeds | Social Media | not created | 0/10 | Service Flow | Redis, cassandra | never | TBD — will add in a follow-up step |
| Chat Systems | Social Media | not created | 0/10 | Service Flow | cassandra, Redis | never | TBD — will add in a follow-up step |
| Whatsapp User Socket info | Social Media | not created | 0/10 | Service Flow | Redis | never | TBD — will add in a follow-up step |

### Type B — Theory / Concept Notes

**Columns:** Concept Name | Linked Systems (labels) | File | Last Reviewed | Freshness | Notion URL

**Freshness** is a flag, not a hard schedule: "Fresh" / "Check recommended"
— set to "Check recommended" when a linked Type A system had a session
more recently than this concept's Last Reviewed date.

| Concept Name | Linked Systems (labels) | File | Last Reviewed | Freshness | Notion URL |
|---|---|---|---|---|---|
| Cassandra Internals | Database Internals, cassandra | not created | never | Check recommended | TBD — will add in a follow-up step |
| Redis Internals | Database Internals, Redis | not created | never | Check recommended | TBD — will add in a follow-up step |
| Kafka Internals | Database Internals, Kafka | not created | never | Check recommended | TBD — will add in a follow-up step |
| Authentication | - | not created | never | Check recommended | TBD — will add in a follow-up step |
| Load Balancing | - | not created | never | Check recommended | TBD — will add in a follow-up step |
| Reverse Proxy | - | not created | never | Check recommended | TBD — will add in a follow-up step |
| Circuit Breaker | - | not created | never | Check recommended | TBD — will add in a follow-up step |
| SAGA | - | not created | never | Check recommended | TBD — will add in a follow-up step |
| 2 phase Commit | SQL | not created | never | Check recommended | TBD — will add in a follow-up step |
| 3 phase Commit | SQL | not created | never | Check recommended | TBD — will add in a follow-up step |
| SQL Data base locking | SQL | not created | never | Check recommended | TBD — will add in a follow-up step |
| Distributed lokcing | Redis | not created | never | Check recommended | TBD — will add in a follow-up step |
| Gossip Protocol | cassandra | not created | never | Check recommended | TBD — will add in a follow-up step |
| Flash Sale Scaling (Peak Load) | Redis, SQL — linked to Amazon Order Managment System | concepts/flash-sale-scaling.md | 2026-08-12 | Fresh | TBD — will add in a follow-up step |

## Planning Notes

Cross-session reminders that don't fit the table schema above — check
before starting a session on the referenced system(s).

- **Movie Ticket Booking**, **Flight Ticket Booking**, **Hotel
  ReservationSyste**: whichever of these gets designed first (Interview
  or Learning Mode), the session must include a full, explicit
  treatment of **Distributed Locking** — not a passing mention or a bare
  link out to `concepts/distributed-locking.md` (not yet created).
  Actually explain the whole concept in-session: the seat/room-hold
  problem (why a plain SQL row lock can't survive the user's think-time
  across multiple requests during checkout), and the TTL-based external
  lock that solves it (Redis `SETNX`+expiry, ZooKeeper ephemeral nodes,
  etc.), including the Redlock/fencing-token failure mode. These three
  systems were picked specifically as this concept's teaching vehicle
  because the resource being locked (a specific seat/room) is
  non-fungible — unlike inventory counters, it can't dodge locking via
  sharded atomic counters the way `concepts/flash-sale-scaling.md`
  does. Decided 2026-08-12; still open which of the three is "the" one.
