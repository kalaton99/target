# Tmarget Postgres Schema Draft

## 1. Purpose

This document drafts a future Postgres schema for Tmarget durable persistence
without implementing it. It is planning documentation only: no schema,
migration, database driver, adapter activation, or runtime behavior is added in
this pass.

## 2. Current State

- Active runtime storage remains `InMemoryTmargetRepository`.
- `DurableTmargetRepository` remains inactive and fail-closed.
- Postgres has been selected only as the future durable backend direction.
- No Postgres dependency, migration, or adapter activation exists yet.
- Tmarget remains internal demo-credit only.

> Axwins currently uses internal demo credits. Live deposits, withdrawals, card payments, crypto transfers, Telegram wallet linking, and real-money trading are not enabled.

## 3. Design Principles

- Preserve the current repository contract.
- Preserve existing API response shapes.
- Preserve settlement and refund idempotency.
- Preserve auditability for admin actions and status changes.
- Keep settlement/refund operations safe under retries.
- Keep Tmarget separate from Target, Diceget, and Flipget game modules.
- Do not imply real-money readiness.
- Avoid accidental runtime activation.
- Keep `InMemoryTmargetRepository` available for local demo/tests.

## 4. Repository Contract Mapping

The future Postgres adapter should implement the existing methods from
`backend/tmarget/repository.py`.

| Repository method | Likely table(s) | Key lookup / index | Idempotency / transaction notes |
| --- | --- | --- | --- |
| `create_market(market)` | `tmarget_markets` | primary key `id`, unique `slug` | Insert market fields and embedded rule/pool state atomically. |
| `get_market(market_id_or_slug)` | `tmarget_markets` | primary key `id`, unique `slug` | Query by id first, then slug, matching current behavior. |
| `get_market_by_slug(slug)` | `tmarget_markets` | unique `slug` | Must return one market or none. |
| `list_markets(status=None, category=None)` | `tmarget_markets` | `status`, `category` indexes | Preserve optional filter semantics. |
| `update_market(market)` | `tmarget_markets` | primary key `id` | Market update and any status-history append should be atomic when both occur. |
| `create_trade(trade)` | `tmarget_demo_trades` | primary key `id`, `market_id, created_at` | Insert after trade is accepted. Buy/sell durable adapter work should later coordinate position, pool, and trade updates atomically. |
| `list_market_trades(market_id)` | `tmarget_demo_trades` | `market_id, created_at` | Preserve stable order. |
| `get_user_positions(user_id)` | `tmarget_demo_positions` | `user_id` | Used by portfolio/user-position views. |
| `list_market_positions(market_id, user_id=None)` | `tmarget_demo_positions` | `market_id`, optional `user_id` | Used by market position lookup and settlement/refund scans. |
| `get_position(user_id, market_id, outcome)` | `tmarget_demo_positions` | unique `user_id, market_id, outcome` | Must return one position or none. |
| `upsert_position(position)` | `tmarget_demo_positions` | unique `user_id, market_id, outcome` | Use an upsert pattern that cannot duplicate positions. |
| `get_pool(market_id)` | `tmarget_markets` | primary key `id` | Current code stores pool state on the market object. |
| `update_pool(market_id, pool)` | `tmarget_markets` | primary key `id` | Pool update should be atomic with related trade/position update in a future durable buy/sell implementation. |
| `record_settlement(market_id, user_id, outcome, amount, idempotency_key)` | `tmarget_settlements` | unique `idempotency_key` | Duplicate key must return/observe existing record and must not double-credit. |
| `has_settlement(idempotency_key)` | `tmarget_settlements` | unique `idempotency_key` | Used to detect prior settlement record. |
| `record_refund(market_id, user_id, outcome, amount, idempotency_key)` | `tmarget_refunds` | unique `idempotency_key` | Duplicate key must return/observe existing record and must not double-refund. |
| `has_refund(idempotency_key)` | `tmarget_refunds` | unique `idempotency_key` | Used to detect prior refund record. |
| `record_admin_action(action, market_id, user_id, details=None)` | `tmarget_admin_audit_events` | `market_id, created_at`, `admin_user_id, created_at` | Append-only audit event. |
| `list_admin_actions()` | `tmarget_admin_audit_events` | `created_at` | Preserve deterministic listing order where practical. |
| `record_status_history(...)` | `tmarget_market_status_history` | `market_id, created_at` | Append-only status event. |
| `list_status_history(market_id)` | `tmarget_market_status_history` | `market_id, created_at` | Preserve chronological market timeline. |

## 5. Proposed Tables

The tables below are grounded in current code and repository contract behavior.
No migration files are created in this pass.

### `tmarget_markets`

Purpose: store market identity, lifecycle state, rule fields, pricing/pool
state, resolution fields, and timestamps.

Primary key:

- `id`

Logical references:

- `created_by` references the current user/account identifier shape used by
  Axwins auth helpers. A formal foreign key can be added later only after auth
  schema is stable.

Required unique constraints:

- `slug`

Useful indexes:

- `status`
- `category`
- `close_time`
- `updated_at`

Lifecycle notes:

- Current code creates markets in `draft`.
- Trading is allowed only while status is `open`.
- Resolution currently requires `closed`.
- `resolving` is transient in current service behavior.

### `tmarget_market_status_history`

Purpose: store append-only market status transitions.

Primary key:

- `id`

Logical references:

- `market_id` references `tmarget_markets.id`.

Useful indexes:

- `market_id, created_at`
- `changed_by, created_at`

Lifecycle notes:

- Status history is represented by repository methods today, but current service
  transitions do not require every status update to append history yet.

### `tmarget_demo_trades`

Purpose: store filled demo buy/sell trade records aligned with current
`TmargetTrade` behavior.

Primary key:

- `id`

Logical references:

- `market_id` references `tmarget_markets.id`.
- `user_id` references the current Axwins user/account identifier shape.

Useful indexes:

- `market_id, created_at`
- `user_id, created_at`
- `market_id, user_id`

Lifecycle notes:

- Current service records only filled trades.
- Rejected trades are represented by the model status but are not currently a
  primary runtime behavior.

### `tmarget_demo_positions`

Purpose: store demo user positions aligned with current `TmargetPosition`
behavior.

Primary key:

- Composite logical key: `user_id, market_id, outcome`

Logical references:

- `market_id` references `tmarget_markets.id`.
- `user_id` references the current Axwins user/account identifier shape.

Required unique constraints:

- `user_id, market_id, outcome`

Useful indexes:

- `user_id`
- `market_id`
- `market_id, outcome`

Lifecycle notes:

- `upsert_position` must not duplicate the unique tuple.
- Settlement and refund scans use market positions.

### `tmarget_settlements`

Purpose: store domain settlement records and the deterministic idempotency key
used for demo-credit payouts.

Primary key:

- `id`

Logical references:

- `market_id` references `tmarget_markets.id`.
- `user_id` references the current Axwins user/account identifier shape.

Required unique constraints:

- `idempotency_key`

Useful indexes:

- `market_id`
- `user_id`
- `created_at`

Lifecycle notes:

- Duplicate settlement keys must not create another payout record.
- A future adapter should return or observe the existing record on duplicate
  key.

### `tmarget_refunds`

Purpose: store domain refund records and the deterministic idempotency key used
for cancelled/invalid market demo-credit refunds.

Primary key:

- `id`

Logical references:

- `market_id` references `tmarget_markets.id`.
- `user_id` references the current Axwins user/account identifier shape.

Required unique constraints:

- `idempotency_key`

Useful indexes:

- `market_id`
- `user_id`
- `created_at`

Lifecycle notes:

- Duplicate refund keys must not create another refund record.
- A future adapter should return or observe the existing record on duplicate
  key.

### `tmarget_admin_audit_events`

Purpose: store admin actions such as create, update, open, pause, close,
resolve, and cancel.

Primary key:

- `id`

Logical references:

- `market_id` references `tmarget_markets.id` when present.
- `admin_user_id` references the current Axwins user/account identifier shape
  when present.

Useful indexes:

- `market_id, created_at`
- `admin_user_id, created_at`
- `action, created_at`

Lifecycle notes:

- Events should be append-only.
- The current demo admin guard is local/demo-only and is not production
  authorization.

## 6. `tmarget_markets` Draft

Current-code required fields:

- `id`
- `slug`
- `title`
- `description`
- `category`
- `status`
- `outcome_type`
- `yes_label`
- `no_label`
- `close_time`
- `resolution_time`
- `resolved_outcome`
- `resolver_notes`
- `created_by`
- `created_at`
- `updated_at`
- `volume`
- `source_url`
- `resolution_criteria`
- `invalid_conditions`
- `timezone`
- `yes_pool`
- `no_pool`
- `liquidity_parameter`
- `pool_updated_at`

Current derived fields:

- `yes_price`
- `no_price`

Future hardening fields:

- `opened_at`
- `paused_at`
- `closed_at`
- `resolved_at`
- `cancelled_at`
- `last_status_history_id`
- `version`

Notes:

- `source_url`, `resolution_criteria`, `invalid_conditions`, and `timezone`
  come from `TmargetMarketRule`.
- `yes_pool`, `no_pool`, `liquidity_parameter`, and `pool_updated_at` come from
  `TmargetLiquidityPool`.
- `yes_price` and `no_price` should continue to be derived by pricing logic
  unless a future performance pass explicitly stores snapshots.

## 7. Settlement / Refund Idempotency

Settlement design:

- `tmarget_settlements.idempotency_key` must be unique.
- `market_id` references the market.
- `user_id` stores the user/account identifier represented in current code.
- `amount` and `payout_amount` store the demo-credit amount.
- `outcome` stores the resolved winning outcome.
- `reason` should map to the current Tmarget ledger reason where represented.
- `source_module` should be `tmarget`.
- `source_id` can store the market id or future ledger reference if represented.
- `status` stores whether the domain record posted, replayed, or failed.
- `created_at` stores record creation time.

Refund design:

- `tmarget_refunds.idempotency_key` must be unique.
- `market_id` references the market.
- `user_id` stores the user/account identifier represented in current code.
- `amount` and `refund_amount` store the demo-credit amount.
- `outcome` stores the cancellation/invalid reason outcome.
- `reason` should map to the current Tmarget ledger refund reason where
  represented.
- `source_module` should be `tmarget`.
- `source_id` can store the market id or future ledger reference if represented.
- `status` stores whether the domain record posted, replayed, or failed.
- `created_at` stores record creation time.

Expected duplicate behavior:

- Duplicate settlement idempotency key returns or observes the existing record.
- Duplicate settlement does not double-credit.
- Duplicate refund idempotency key returns or observes the existing record.
- Duplicate refund does not double-refund.
- Durable adapter behavior must preserve the current fail-safe behavior from
  `InMemoryTmargetRepository`.

## 8. Status History and Admin Audit

Status history should be immutable and append-only.

Status history fields:

- `id`
- `market_id`
- `previous_status`
- `new_status`
- `actor_id`
- `reason`
- `note`
- `created_at`

Current repository naming:

- `from_status`
- `to_status`
- `changed_by`
- `reason`

Admin audit event fields:

- `id`
- `action`
- `market_id`
- `actor_id`
- `details`
- `before_summary`
- `after_summary`
- `request_id`
- `created_at`

Future request metadata:

- IP/device metadata, request id, actor role, or session reference may be added
  later, but this requires real auth/admin role design.

The current `X-Axwins-Demo-Admin: true` guard is local/demo-only. It is not
production authorization.

## 9. Indexes and Constraints

Proposed indexes and constraints:

- `tmarget_markets.id` primary key.
- `tmarget_markets.slug` unique.
- `tmarget_markets.status` index.
- `tmarget_markets.category` index.
- `tmarget_markets.close_time` index.
- `tmarget_market_status_history.market_id, created_at` index.
- `tmarget_demo_trades.market_id, created_at` index.
- `tmarget_demo_trades.user_id, created_at` index.
- `tmarget_demo_positions.user_id, market_id, outcome` unique.
- `tmarget_demo_positions.user_id` index.
- `tmarget_demo_positions.market_id` index.
- `tmarget_settlements.idempotency_key` unique.
- `tmarget_settlements.market_id` index.
- `tmarget_settlements.user_id` index.
- `tmarget_refunds.idempotency_key` unique.
- `tmarget_refunds.market_id` index.
- `tmarget_refunds.user_id` index.
- `tmarget_admin_audit_events.market_id, created_at` index.
- `tmarget_admin_audit_events.admin_user_id, created_at` index.

## 10. Transaction Boundaries

Future transaction expectations:

- Market status update plus status history append should be atomic.
- Buy/sell trade, position, and pool updates should be atomic if implemented
  durably.
- Settlement record plus wallet ledger effect must be coordinated carefully.
- Refund record plus wallet ledger effect must be coordinated carefully.
- Partial settlement/refund writes must be avoided.
- Unique idempotency constraints should be used to make retry behavior safe.

This pass does not change wallet/ledger behavior. The relationship between
Postgres Tmarget domain records and `LedgerService` mutations must be designed
carefully in a future implementation pass.

## 11. Migration Strategy

Planning only:

- Migration 001 creates the tables.
- Migration 002 adds or refines indexes if needed.
- Rollback must preserve safety for settlement/refund idempotency records.
- Runtime must never be activated until migrations and repository contract tests
  pass.
- A test database should be used before any remote demo activation.

No migration files are created in this pass.

## 12. Adapter Implementation Notes

Future Postgres adapter guidance:

- Implement the existing repository contract exactly.
- Keep `InMemoryTmargetRepository` for demo/tests.
- Keep `DurableTmargetRepository` inactive until implemented.
- Activation should be explicit and config-gated later.
- Contract tests must pass against both in-memory and Postgres adapters before
  activation.
- API response shapes must remain unchanged.

## 13. Testing Plan

Required future tests:

- Schema smoke tests.
- Repository contract tests against a Postgres test database.
- Market lookup/listing tests.
- Status history tests.
- Idempotent settlement tests.
- Idempotent refund tests.
- Duplicate key tests.
- Restart persistence tests.
- Rollback tests.
- API response shape regression tests.
- Wallet/ledger non-regression tests.
- Product boundary wording tests, where relevant.

## 14. Risks

- Schema drift.
- Weak idempotency constraints.
- Partial settlement/refund writes.
- Stale market status.
- Admin audit gaps.
- Accidental production persistence claims.
- Accidental real-money implication.
- Adapter activation before tests.
- Confusing Tmarget with games.

## 15. Decision Summary

- This is a draft only.
- No schema was implemented.
- No database dependency was added.
- No migration was created.
- `InMemoryTmargetRepository` remains active.
- `DurableTmargetRepository` remains inactive.
- Postgres remains the recommended future backend.
