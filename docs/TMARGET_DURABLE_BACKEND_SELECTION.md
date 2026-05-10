# Tmarget Durable Backend Selection

## 1. Purpose

This document evaluates candidate durable backends for future Tmarget
persistence and recommends a staged direction. It does not implement durable
storage, activate a durable repository, add database dependencies, or change
Tmarget runtime behavior.

## 2. Current State

Tmarget is a demo prediction market product inside Axwins. It is not a game.

Current persistence state:

- Active runtime storage is still `InMemoryTmargetRepository`.
- `DurableTmargetRepository` exists only as an inactive, fail-closed skeleton.
- No durable backend is active.
- No new database dependency was added by the skeleton.
- Existing `pymongo` and `motor` dependencies are present in
  `backend/requirements.txt`, but they were not added for the inactive Tmarget
  skeleton and should not decide the future durable backend.
- Tmarget uses internal demo credits only.
- Real-money trading is not enabled.

> Axwins currently uses internal demo credits. Live deposits, withdrawals, card payments, crypto transfers, Telegram wallet linking, and real-money trading are not enabled.

## 3. Tmarget Persistence Requirements

Future durable persistence should support the current repository contract and
the safety requirements documented for Tmarget:

- Market lookup by id and slug.
- Filtered market listing by status and category.
- Market status history.
- Admin action and audit trace.
- Settlement records.
- Refund records.
- Deterministic idempotency keys for settlement and refund safety.
- Demo trade records, because `TmargetTrade` is currently represented in code.
- Demo position records, because `TmargetPosition` is currently represented in
  code.
- Liquidity pool state, because `TmargetLiquidityPool` is currently represented
  in code and drives pricing.
- Restart persistence for demo markets, trades, positions, and status.
- Future remote demo safety, including predictable recovery after backend
  restarts.
- Backup and rollback procedures before remote-demo activation.
- Clear documentation that persistence is for internal demo data unless future
  production/legal/payment work explicitly changes that scope.
- No production or real-money claims.

## 4. Candidate Backends

### Postgres

Fit for repository contract:

- Strong fit for markets, rules, pools, trades, positions, settlements, refunds,
  admin actions, and status history.
- Natural representation for relational constraints such as market id, market
  slug, user/market/outcome position uniqueness, and idempotency keys.

Idempotency support:

- Strong. Unique indexes on settlement and refund idempotency keys can prevent
  duplicate payout/refund records.

Transaction and consistency support:

- Strong. Market updates, position updates, settlement/refund records, and audit
  records can be grouped in transactions.

Query and audit suitability:

- Strong. Status/category filtering, market trade listing, portfolio lookup, and
  audit timelines fit indexed relational queries well.

Operational complexity:

- Medium. Requires a managed or self-hosted Postgres instance, migrations,
  backup/restore planning, connection management, and operational monitoring.

Local development complexity:

- Medium. A local database or test container would eventually be needed for
  durable-adapter tests, but this should remain separate from the current
  Mongo-free default test flow until explicitly scoped.

Remote demo suitability:

- Strong once configured. Postgres gives a safer remote demo path than
  in-memory storage because demo state can survive process restarts.

Risks:

- Bad migrations can cause rollback difficulty.
- Transaction boundaries must be designed carefully around LedgerService calls.
- Production-like claims must not be made just because Postgres is introduced.

### MongoDB

Fit for repository contract:

- Possible, especially for market documents and embedded rules/pools.
- Less ideal for the relational shape of positions, trades, settlement records,
  refund records, and audit/status history.

Idempotency support:

- Possible with unique indexes on idempotency keys, but the overall model is
  less naturally relational.

Transaction and consistency support:

- Possible if configured correctly, but settlement/refund safety would require
  careful transaction and unique-index design.

Query and audit suitability:

- Adequate for simple listing and audit records, but relational audit and
  settlement joins are less straightforward.

Operational complexity:

- Medium. Existing `pymongo` and `motor` dependencies are present, but existing
  dependency availability should not decide the durable backend.

Local development complexity:

- Medium. Requires a local or managed MongoDB environment for durable tests.

Remote demo suitability:

- Possible, but not the preferred first choice for Tmarget settlement/audit
  requirements.

Risks:

- Choosing Mongo only because dependencies already exist would couple the
  durable design to convenience rather than the data model.
- Settlement/refund idempotency and audit trace design may be easier to get
  wrong than in Postgres.

### SQLite

Fit for repository contract:

- Good enough for a local-only prototype adapter and contract-test spike.
- Supports tables, indexes, and unique constraints for the core repository
  contract.

Idempotency support:

- Good for local testing through unique indexes on settlement/refund
  idempotency keys.

Transaction and consistency support:

- Good for single-process local development.

Query and audit suitability:

- Adequate for local development and small demo fixtures.

Operational complexity:

- Low locally. No separate database server is needed.

Local development complexity:

- Low. Useful for adapter mapping experiments if the team wants a simple
  durable prototype before Postgres.

Remote demo suitability:

- Limited. File-based storage can be fragile under server restarts, concurrent
  access, backups, and hosted deployment constraints.

Risks:

- Can create false confidence if treated as equivalent to a remote-demo durable
  backend.
- Not recommended as the primary long-term Tmarget backend.

### In-Memory Only

Fit for repository contract:

- Already implemented by `InMemoryTmargetRepository`.
- Excellent for deterministic local tests and demo-only behavior.

Idempotency support:

- Works only while the process is alive.

Transaction and consistency support:

- Limited to in-process state.

Query and audit suitability:

- Adequate for current MVP tests, not durable audit needs.

Operational complexity:

- Lowest.

Local development complexity:

- Lowest.

Remote demo suitability:

- Poor if demo state needs to survive restarts.

Risks:

- State resets on backend restart.
- Not suitable for claims of durable persistence.
- Audit history is not durable.

### Redis

Fit for repository contract:

- Weak as the primary durable source of truth for Tmarget.
- Better suited for cache, queues, locks, or short-lived coordination in a later
  architecture.

Idempotency support:

- Possible with key semantics, but less suitable as the primary audit and
  settlement ledger companion.

Transaction and consistency support:

- Limited compared with relational database transactions.

Query and audit suitability:

- Weak for market filtering, audit history, and long-term settlement/refund
  records.

Operational complexity:

- Medium if used remotely, especially when persistence and backup guarantees
  matter.

Local development complexity:

- Medium because it adds another service.

Remote demo suitability:

- Not recommended as the primary durable backend.

Risks:

- Easy to confuse cache persistence with durable business records.
- Poor fit for long-term auditability.

## 5. Recommendation

Recommended future backend: Postgres.

Fallback/local candidate: SQLite, only if useful for local-only adapter testing
or contract-test prototyping.

Keep `InMemoryTmargetRepository` active until implementation and testing are
complete.

Postgres is preferred because:

- Tmarget has relational market, rule, pool, trade, position, settlement,
  refund, and audit/status data.
- Unique constraints can directly enforce idempotency-key safety.
- Transactions can protect settlement/refund and audit record consistency.
- It gives a better long-term auditability model.
- It encourages migration discipline.
- It provides a safer path toward remote demo and production-like persistence
  than in-memory or file-based storage.

MongoDB is not the first choice because:

- It is possible but less ideal for relational settlement, audit, and
  idempotency guarantees.
- Existing `pymongo` and `motor` dependencies should not alone drive the
  architectural choice.
- Tmarget persistence should be selected for the data model and safety
  requirements, not for incidental dependency availability.

## 6. Non-Goals

This document does not implement:

- Durable repository code.
- Database driver additions.
- Migrations.
- Runtime durable repository activation.
- Production deployment.
- Real-money enablement.
- Payment, deposit, withdrawal, cash out, buy-credit, crypto/Web3, Stripe/card,
  or Telegram wallet flows.
- Order book behavior.
- Oracle or dispute workflow.
- Compliance/KYC/AML behavior.
- Target, Diceget, or Flipget gameplay changes.

## 7. Future Implementation Phases

Planning only:

1. Phase 1: Draft a Postgres schema document.
2. Phase 2: Add an inactive Postgres adapter skeleton or interface mapping.
3. Phase 3: Run repository contract tests against a local test database.
4. Phase 4: Enable dev-only activation behind explicit configuration.
5. Phase 5: Consider remote demo activation after backup, rollback, and logging
   review.
6. Phase 6: Consider production hardening only after auth, security,
   compliance, and legal review.

## 8. Schema Direction

No migrations are created in this pass. Likely future tables:

### `tmarget_markets`

Stores market identity, text fields, category, lifecycle status, outcome labels,
close/resolution fields, and timestamps.

Key constraints:

- Unique `id`.
- Unique `slug`.
- Index `status`.
- Index `category`.
- Index `close_time`.

### `tmarget_market_status_history`

Stores market lifecycle transitions and reasons.

Key constraints:

- Unique `id`.
- Index `market_id, created_at`.

### `tmarget_demo_trades`

Stores filled demo buy/sell trade records aligned with current `TmargetTrade`
behavior.

Key constraints:

- Unique `id`.
- Index `market_id, created_at`.
- Index `user_id, created_at`.

### `tmarget_demo_positions`

Stores demo user positions aligned with current `TmargetPosition` behavior.

Key constraints:

- Unique `user_id, market_id, outcome`.
- Index `user_id`.
- Index `market_id`.

### `tmarget_settlements`

Stores domain settlement records and the idempotency key used for demo-credit
payouts.

Key constraints:

- Unique `id`.
- Unique `idempotency_key`.
- Index `market_id`.
- Index `user_id`.

### `tmarget_refunds`

Stores domain refund records and the idempotency key used for cancelled/invalid
market demo-credit refunds.

Key constraints:

- Unique `id`.
- Unique `idempotency_key`.
- Index `market_id`.
- Index `user_id`.

### `tmarget_admin_audit_events`

Stores admin actions such as market create, update, open, pause, close, resolve,
and cancel.

Key constraints:

- Unique `id`.
- Index `market_id, created_at`.
- Index `admin_user_id, created_at`.

## 9. Testing Requirements Before Activation

Before any durable repository activation:

- Repository contract tests.
- Idempotent settlement tests.
- Idempotent refund tests.
- Duplicate key tests.
- Status history tests.
- Market lookup/listing tests.
- Restart persistence tests.
- Rollback tests.
- API response shape regression tests.
- Wallet/ledger non-regression tests.
- Product boundary wording tests, where relevant.

## 10. Risk Register

Key risks:

- Double settlement.
- Duplicate refund.
- Stale market status.
- Status transition ambiguity.
- Admin action audit gaps.
- Database schema drift.
- Bad migration rollback.
- Remote demo data loss.
- Accidental production or real-money claims.
- Confusing Tmarget with games.

## 11. Decision Summary

- Recommended future backend: Postgres.
- Fallback/local candidate: SQLite, if useful for local-only adapter testing.
- Current active runtime: `InMemoryTmargetRepository`.
- Durable adapter: inactive fail-closed skeleton.
- Implementation status: not started.
