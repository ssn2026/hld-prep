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
| Netfilx | Video Based Systems | systems/netfilx.md | 10/10 | Deep Dive Ready | SQL, cassandra | 2026-08-12 | TBD — will add in a follow-up step |
| Broadcasting System | Video Based Systems | systems/broadcasting-system.md | 10/10 | Deep Dive Ready | Redis, cassandra | 2026-08-12 | TBD — will add in a follow-up step |
| Zoom | Video Based Systems | systems/zoom.md | 10/10 | Deep Dive Ready | SQL | 2026-08-12 | TBD — will add in a follow-up step |
| Youtube | Video Based Systems | systems/youtube.md | 10/10 | Deep Dive Ready | SQL, cassandra | 2026-08-12 | TBD — will add in a follow-up step |
| Movie Ticket Booking | Booking System | systems/movie-ticket-booking.md | 10/10 | Deep Dive Ready | SQL, Redis | 2026-08-12 | TBD — will add in a follow-up step |
| Click Event Aggregator | (ungrouped) | systems/click-event-aggregator.md | 10/10 | Deep Dive Ready | Kafka, cassandra | 2026-08-12 | TBD — will add in a follow-up step |
| Stock Broker | (ungrouped) | systems/stock-broker.md | 10/10 | Deep Dive Ready | SQL, Redis | 2026-08-12 | TBD — will add in a follow-up step |
| Notification System | Notification System | systems/notification-system.md | 10/10 | Deep Dive Ready | Kafka, cassandra, SQL | 2026-08-12 | TBD — will add in a follow-up step |
| Amazon Order Managment System | Ordering System | systems/amazon-order-management-system.md | 10/10 | Deep Dive Ready | SQL, Kafka | 2026-08-12 | TBD — will add in a follow-up step |
| Hotel ReservationSyste | Booking System | systems/hotel-reservation-system.md | 10/10 | Deep Dive Ready | SQL, Redis | 2026-08-12 | TBD — will add in a follow-up step |
| Rate Limiter | Rate Limiter | systems/rate-limiter.md | 10/10 | Deep Dive Ready | Redis, SQL | 2026-08-12 | TBD — will add in a follow-up step |
| Flight Ticket Booking | Booking System | systems/flight-ticket-booking.md | 10/10 | Deep Dive Ready | SQL, Redis | 2026-08-12 | TBD — will add in a follow-up step |
| Doctor Appointment | Booking System | systems/doctor-appointment.md | 10/10 | Deep Dive Ready | SQL, Redis | 2026-08-12 | TBD — will add in a follow-up step |
| Google Maps | Location Based Systems | systems/google-maps.md | 10/10 | Deep Dive Ready | SQL | 2026-08-12 | TBD — will add in a follow-up step |
| Digital Wallet | (ungrouped) | systems/digital-wallet.md | 10/10 | Deep Dive Ready | SQL | 2026-08-12 | TBD — will add in a follow-up step |
| Payment Gateway | (ungrouped) | systems/payment-gateway.md | 10/10 | Deep Dive Ready | SQL | 2026-08-12 | TBD — will add in a follow-up step |
| Google Drive | (ungrouped) | systems/google-drive.md | 10/10 | Deep Dive Ready | SQL | 2026-08-12 | TBD — will add in a follow-up step |
| Redis As cache | (ungrouped) | systems/redis-as-cache.md | 10/10 | Deep Dive Ready | Redis | 2026-08-12 | TBD — will add in a follow-up step |
| LeaderBoard | (ungrouped) | systems/leaderboard.md | 10/10 | Deep Dive Ready | Redis, SQL | 2026-08-12 | TBD — will add in a follow-up step |
| Like and Comment Service | Social Media | systems/like-and-comment-service.md | 10/10 | Deep Dive Ready | Redis, cassandra | 2026-08-12 | TBD — will add in a follow-up step |
| Key Value StoreBa | Simple Cassandra Based Systems | systems/key-value-storeba.md | 10/10 | Deep Dive Ready | cassandra | 2026-08-12 | TBD — will add in a follow-up step |
| Unique Id Generator | Simple Cassandra Based Systems | systems/unique-id-generator.md | 10/10 | Deep Dive Ready | SQL (see doc — Cassandra deliberately not used) | 2026-08-12 | TBD — will add in a follow-up step |
| URL Shortner | Simple Cassandra Based Systems | systems/url-shortner.md | 10/10 | Deep Dive Ready | cassandra, Redis | 2026-08-12 | TBD — will add in a follow-up step |
| Uber find nearby driver | Location Based Systems | systems/uber-find-nearby-driver.md | 10/10 | Deep Dive Ready | cassandra, Redis | 2026-08-12 | TBD — will add in a follow-up step |
| Nearyby friends | Location Based Systems | systems/nearyby-friends.md | 10/10 | Deep Dive Ready | Redis | 2026-08-12 | TBD — will add in a follow-up step |
| Proximity ServiceBase | Location Based Systems | systems/proximity-servicebase.md | 10/10 | Deep Dive Ready | SQL | 2026-08-12 | TBD — will add in a follow-up step |
| News Feeds | Social Media | systems/news-feeds.md | 10/10 | Deep Dive Ready | Redis, cassandra | 2026-08-12 | TBD — will add in a follow-up step |
| Chat Systems | Social Media | systems/chat-systems.md | 10/10 | Deep Dive Ready | cassandra, Redis | 2026-08-12 | TBD — will add in a follow-up step |
| Whatsapp User Socket info | Social Media | systems/whatsapp-user-socket-info.md | 10/10 | Deep Dive Ready | Redis | 2026-08-12 | TBD — will add in a follow-up step |

### Type B — Theory / Concept Notes

**Columns:** Concept Name | Linked Systems (labels) | File | Last Reviewed | Freshness | Notion URL

**Freshness** is a flag, not a hard schedule: "Fresh" / "Check recommended"
— set to "Check recommended" when a linked Type A system had a session
more recently than this concept's Last Reviewed date.

| Concept Name | Linked Systems (labels) | File | Last Reviewed | Freshness | Notion URL |
|---|---|---|---|---|---|
| Cassandra Internals | Database Internals, cassandra | concepts/practice/cassandra-guide.md | 2026-08-16 | Fresh | TBD — will add in a follow-up step |
| Redis Internals | Database Internals, Redis | not created | never | Check recommended | TBD — will add in a follow-up step |
| Kafka Internals | Database Internals, Kafka | not created | never | Check recommended | TBD — will add in a follow-up step |
| Authentication | - | not created | never | Check recommended | TBD — will add in a follow-up step |
| Load Balancing | - | not created | never | Check recommended | TBD — will add in a follow-up step |
| Reverse Proxy | - | not created | never | Check recommended | TBD — will add in a follow-up step |
| Circuit Breaker | - | not created | never | Check recommended | TBD — will add in a follow-up step |
| SAGA | - | not created | never | Check recommended | TBD — will add in a follow-up step |
| 2 phase Commit | SQL | concepts/practice/sql-guide.md#9-two-phase-commit | 2026-08-16 | Fresh | TBD — will add in a follow-up step |
| 3 phase Commit | SQL | concepts/practice/sql-guide.md#10-three-phase-commit | 2026-08-16 | Fresh | TBD — will add in a follow-up step |
| SQL Data base locking | SQL | concepts/practice/sql-guide.md#2-pessimistic-locking | 2026-08-16 | Fresh | TBD — will add in a follow-up step |
| Distributed lokcing | Redis | not created | never | Check recommended | TBD — will add in a follow-up step |
| Gossip Protocol | cassandra | concepts/practice/cassandra-guide.md#8-token-ring-consistent-hashing--gossip-protocol--unused-at-the-cql-level | 2026-08-16 | Fresh | TBD — will add in a follow-up step |
| Flash Sale Scaling (Peak Load) | Redis, SQL — linked to Amazon Order Managment System | concepts/flash-sale-scaling.md | 2026-08-12 | Fresh | TBD — will add in a follow-up step |

## Planning Notes

Cross-session reminders that don't fit the table schema above — check
before starting a session on the referenced system(s).

- ~~**Movie Ticket Booking**, **Flight Ticket Booking**, **Hotel
  ReservationSyste**: distributed locking deep-dive~~ — **done.** Movie
  Ticket Booking was built (2026-08-12) with the full treatment in its
  own section 5: the seat-hold problem, why a plain SQL row lock can't
  survive checkout think-time, the Redis `SET NX PX` mechanism with the
  fencing-token gap called out explicitly, and Redlock/ZooKeeper/etcd
  noted as alternatives with trade-offs. Its interactive trace
  demonstrates the actual race between two users for one seat. Flight
  Ticket Booking / Hotel ReservationSyste no longer need this treatment
  repeated — link back to `systems/movie-ticket-booking.md` §5 instead
  when they're eventually designed, rather than re-deriving it.
