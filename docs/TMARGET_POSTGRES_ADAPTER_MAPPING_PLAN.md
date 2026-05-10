# Tmarget Postgres Adapter Mapping Plan

## 1. Purpose

This document maps the existing Tmarget repository contract to a future
Postgres adapter design. It does not implement the adapter, write SQL in code,
add migrations, add database dependencies, or activate durable storage.

## 2. Current State

- `InMemoryTmargetRepository` remains the active runtime/default repository.
- `DurableTmargetRepository` remains inactive and fail-closed.
- Postgres is selected only as the future durable backend direction.
- No database dependency, migration, or runtime activation exists.
- Tmarget remains internal demo-credit only.

> Axwins currently uses internal demo credits. Live deposits, withdrawals, card payments, crypto transfers, Telegram wallet linking, and real-money trading are not enabled.

## 3. Contract Inventory

The public repository contract currently includes the methods below.

### `create_market(market)`

- Current in-memory behavior: stores the `TmargetMarket` in `markets` by
  `market.id` and returns the same market object.
- Future Postgres tables: `tmarget_markets`.
- Lookup keys: primary key `id`, unique `slug`.
- Expected return shape: `TmargetMarket`.
- Idempotency: none today.
- Transaction boundary: single insert; future implementation should insert
  market, rule fields, and pool fields consistently.
- Constraints/indexes: primary key `id`, unique `slug`, indexes on `status`,
  `category`, and `close_time`.

### `get_market(market_id_or_slug)`

- Current in-memory behavior: checks `markets` by id first, then delegates to
  slug lookup.
- Future Postgres tables: `tmarget_markets`.
- Lookup keys: primary key `id`, unique `slug`.
- Expected return shape: `TmargetMarket` or `None`.
- Idempotency: not applicable.
- Transaction boundary: no transaction required.
- Constraints/indexes: primary key `id`, unique `slug`.

### `get_market_by_slug(slug)`

- Current in-memory behavior: scans stored markets and returns the one matching
  slug.
- Future Postgres tables: `tmarget_markets`.
- Lookup keys: unique `slug`.
- Expected return shape: `TmargetMarket` or `None`.
- Idempotency: not applicable.
- Transaction boundary: no transaction required.
- Constraints/indexes: unique `slug`.

### `list_markets(status=None, category=None)`

- Current in-memory behavior: returns all markets, optionally filtered by exact
  `status` and/or `category`.
- Future Postgres tables: `tmarget_markets`.
- Lookup keys: optional `status`, optional `category`.
- Expected return shape: list of `TmargetMarket`.
- Idempotency: not applicable.
- Transaction boundary: no transaction required.
- Constraints/indexes: indexes on `status`, `category`, and optionally
  `updated_at` or `created_at` for deterministic ordering.

### `update_market(market)`

- Current in-memory behavior: replaces the market by `market.id` and returns
  the market.
- Future Postgres tables: `tmarget_markets`, future optional
  `tmarget_market_status_history` when coupled to status changes.
- Lookup keys: primary key `id`.
- Expected return shape: `TmargetMarket`.
- Idempotency: none today.
- Transaction boundary: needed when market update is coupled to status history.
- Constraints/indexes: primary key `id`; status indexes remain useful.

### `create_trade(trade)`

- Current in-memory behavior: appends `TmargetTrade` to `trades` and returns it.
- Future Postgres tables: `tmarget_demo_trades`.
- Lookup keys: primary key `id`; market listing by `market_id, created_at`.
- Expected return shape: `TmargetTrade`.
- Idempotency: trade id should be unique; current trade id generation is service
  local.
- Transaction boundary: future durable buy/sell should group trade insert,
  position update, and pool update.
- Constraints/indexes: primary key `id`, indexes on `market_id, created_at` and
  `user_id, created_at`.

### `list_market_trades(market_id)`

- Current in-memory behavior: filters trades by `market_id` in insertion order.
- Future Postgres tables: `tmarget_demo_trades`.
- Lookup keys: `market_id`.
- Expected return shape: list of `TmargetTrade`.
- Idempotency: not applicable.
- Transaction boundary: no transaction required.
- Constraints/indexes: index `market_id, created_at`.

### `get_user_positions(user_id)`

- Current in-memory behavior: returns positions where `pos.user_id == user_id`.
- Future Postgres tables: `tmarget_demo_positions`.
- Lookup keys: `user_id`.
- Expected return shape: list of `TmargetPosition`.
- Idempotency: not applicable.
- Transaction boundary: no transaction required.
- Constraints/indexes: index `user_id`.

### `list_market_positions(market_id, user_id=None)`

- Current in-memory behavior: returns positions for a market, optionally
  filtered by user.
- Future Postgres tables: `tmarget_demo_positions`.
- Lookup keys: `market_id`, optional `user_id`.
- Expected return shape: list of `TmargetPosition`.
- Idempotency: not applicable.
- Transaction boundary: no transaction required for reads; settlement/refund
  scans need careful coordination in future durable workflows.
- Constraints/indexes: indexes on `market_id`, `market_id, user_id`.

### `get_position(user_id, market_id, outcome)`

- Current in-memory behavior: returns a position by unique
  `user_id, market_id, outcome`.
- Future Postgres tables: `tmarget_demo_positions`.
- Lookup keys: `user_id, market_id, outcome`.
- Expected return shape: `TmargetPosition` or `None`.
- Idempotency: not applicable.
- Transaction boundary: no transaction required for read.
- Constraints/indexes: unique `user_id, market_id, outcome`.

### `upsert_position(position)`

- Current in-memory behavior: writes position by unique
  `user_id, market_id, outcome` and returns it.
- Future Postgres tables: `tmarget_demo_positions`.
- Lookup keys: `user_id, market_id, outcome`.
- Expected return shape: `TmargetPosition`.
- Idempotency: upsert should not duplicate position rows.
- Transaction boundary: required when paired with trade/pool updates or
  settlement/refund state updates.
- Constraints/indexes: unique `user_id, market_id, outcome`.

### `get_pool(market_id)`

- Current in-memory behavior: returns `market.pool` if the market exists.
- Future Postgres tables: `tmarget_markets` in the current draft, because pool
  fields are currently embedded in `TmargetMarket`.
- Lookup keys: market primary key `id`.
- Expected return shape: `TmargetLiquidityPool` or `None`.
- Idempotency: not applicable.
- Transaction boundary: no transaction required for read.
- Constraints/indexes: primary key `id`.

### `update_pool(market_id, pool)`

- Current in-memory behavior: replaces `market.pool` and returns the pool.
- Future Postgres tables: `tmarget_markets`.
- Lookup keys: market primary key `id`.
- Expected return shape: `TmargetLiquidityPool`.
- Idempotency: none today.
- Transaction boundary: required when paired with trade and position updates.
- Constraints/indexes: primary key `id`; future optimistic version field may be
  useful.

### `record_settlement(market_id, user_id, outcome, amount, idempotency_key)`

- Current in-memory behavior: returns an existing settlement with the same
  idempotency key or appends a new posted settlement record.
- Future Postgres tables: `tmarget_settlements`.
- Lookup keys: unique `idempotency_key`.
- Expected return shape: dictionary matching the current settlement record
  fields.
- Idempotency: duplicate key must not create a second settlement record or
  double-credit.
- Transaction boundary: future settlement record and wallet ledger coordination
  must be carefully idempotent.
- Constraints/indexes: unique `idempotency_key`, indexes on `market_id`,
  `user_id`, and `created_at`.

### `has_settlement(idempotency_key)`

- Current in-memory behavior: checks whether a settlement record exists for the
  idempotency key.
- Future Postgres tables: `tmarget_settlements`.
- Lookup keys: unique `idempotency_key`.
- Expected return shape: boolean.
- Idempotency: lookup supports retry safety.
- Transaction boundary: no transaction required for read.
- Constraints/indexes: unique `idempotency_key`.

### `record_refund(market_id, user_id, outcome, amount, idempotency_key)`

- Current in-memory behavior: returns an existing refund with the same
  idempotency key or appends a new posted refund record.
- Future Postgres tables: `tmarget_refunds`.
- Lookup keys: unique `idempotency_key`.
- Expected return shape: dictionary matching the current refund record fields.
- Idempotency: duplicate key must not create a second refund record or
  double-refund.
- Transaction boundary: future refund record and wallet ledger coordination must
  be carefully idempotent.
- Constraints/indexes: unique `idempotency_key`, indexes on `market_id`,
  `user_id`, and `created_at`.

### `has_refund(idempotency_key)`

- Current in-memory behavior: checks whether a refund record exists for the
  idempotency key.
- Future Postgres tables: `tmarget_refunds`.
- Lookup keys: unique `idempotency_key`.
- Expected return shape: boolean.
- Idempotency: lookup supports retry safety.
- Transaction boundary: no transaction required for read.
- Constraints/indexes: unique `idempotency_key`.

### `record_admin_action(action, market_id, user_id, details=None)`

- Current in-memory behavior: appends an admin action dictionary. It returns
  `None`.
- Future Postgres tables: `tmarget_admin_audit_events`.
- Lookup keys: event primary key generated by the adapter; list indexes by
  `market_id, created_at` and `admin_user_id, created_at`.
- Expected return shape: `None`, matching current behavior.
- Idempotency: none today.
- Transaction boundary: should be in the same transaction as the domain mutation
  when coupled later.
- Constraints/indexes: primary key `id`, indexes on `market_id, created_at`,
  `admin_user_id, created_at`, and `action, created_at`.

### `list_admin_actions()`

- Current in-memory behavior: returns a deep copy of all admin action records.
- Future Postgres tables: `tmarget_admin_audit_events`.
- Lookup keys: `created_at` ordering.
- Expected return shape: list of dictionaries matching current admin action
  fields.
- Idempotency: not applicable.
- Transaction boundary: no transaction required.
- Constraints/indexes: `created_at`; optionally `market_id, created_at`.

### `record_status_history(...)`

- Current in-memory behavior: appends a status history dictionary and returns a
  deep copy.
- Future Postgres tables: `tmarget_market_status_history`.
- Lookup keys: event primary key generated by the adapter; list index by
  `market_id, created_at`.
- Expected return shape: dictionary matching current status history fields.
- Idempotency: none today.
- Transaction boundary: should be coupled with market status update when service
  behavior is hardened later.
- Constraints/indexes: primary key `id`, index `market_id, created_at`.

### `list_status_history(market_id)`

- Current in-memory behavior: returns a deep copy of status history records for
  the market.
- Future Postgres tables: `tmarget_market_status_history`.
- Lookup keys: `market_id`.
- Expected return shape: list of dictionaries matching current status history
  fields.
- Idempotency: not applicable.
- Transaction boundary: no transaction required.
- Constraints/indexes: index `market_id, created_at`.

## 4. Method Mapping Table

| Repository method | Current behavior | Future Postgres operation | Tables touched | Required constraints/indexes | Transaction needed? | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `create_market` | Store market by id | Insert market row | `tmarget_markets` | PK `id`, unique `slug` | Yes for full market/rule/pool insert | Preserve embedded rule/pool payload shape. |
| `get_market` | Lookup by id, then slug | Select by id or slug | `tmarget_markets` | PK `id`, unique `slug` | No | Preserve id-first behavior. |
| `get_market_by_slug` | Scan by slug | Select by slug | `tmarget_markets` | unique `slug` | No | Return one or none. |
| `list_markets` | Filter by status/category | Select with optional filters | `tmarget_markets` | `status`, `category` | No | Add deterministic ordering later if needed. |
| `update_market` | Replace by id | Update market row | `tmarget_markets` | PK `id` | Yes if paired with history | Current service records admin action separately. |
| `create_trade` | Append trade | Insert trade row | `tmarget_demo_trades` | PK `id` | Yes when paired with position/pool | Current contract covers demo trades. |
| `list_market_trades` | Filter by market | Select trades by market | `tmarget_demo_trades` | `market_id, created_at` | No | Preserve stable order. |
| `get_user_positions` | Filter by user | Select positions by user | `tmarget_demo_positions` | `user_id` | No | Portfolio lookup. |
| `list_market_positions` | Filter by market/user | Select positions by market/user | `tmarget_demo_positions` | `market_id`, `market_id, user_id` | No for reads | Used by settlement/refund scans. |
| `get_position` | Tuple lookup | Select one position | `tmarget_demo_positions` | unique tuple | No | Return one or none. |
| `upsert_position` | Tuple write | Upsert position row | `tmarget_demo_positions` | unique tuple | Yes when paired | Must not duplicate shares rows. |
| `get_pool` | Return market pool | Select pool fields | `tmarget_markets` | PK `id` | No | Pool currently embedded in market. |
| `update_pool` | Replace market pool | Update pool fields | `tmarget_markets` | PK `id` | Yes when paired | Future versioning may help. |
| `record_settlement` | Insert-or-return by key | Insert with unique key, return existing on conflict | `tmarget_settlements` | unique `idempotency_key` | Yes with ledger coordination | Prevent double credit. |
| `has_settlement` | Key existence check | Exists query | `tmarget_settlements` | unique `idempotency_key` | No | Retry helper. |
| `record_refund` | Insert-or-return by key | Insert with unique key, return existing on conflict | `tmarget_refunds` | unique `idempotency_key` | Yes with ledger coordination | Prevent double refund. |
| `has_refund` | Key existence check | Exists query | `tmarget_refunds` | unique `idempotency_key` | No | Retry helper. |
| `record_admin_action` | Append action | Insert audit event | `tmarget_admin_audit_events` | `market_id, created_at` | Yes when paired | No production auth implied. |
| `list_admin_actions` | Return copied actions | Select audit events | `tmarget_admin_audit_events` | `created_at` | No | Preserve dictionary shape. |
| `record_status_history` | Append status event | Insert history event | `tmarget_market_status_history` | `market_id, created_at` | Yes when paired | Current code records separately. |
| `list_status_history` | List market history | Select history by market | `tmarget_market_status_history` | `market_id, created_at` | No | Preserve chronological listing. |

## 5. Market Lookup / Listing Mapping

Market methods:

- `create_market`
- `get_market`
- `get_market_by_slug`
- `list_markets`
- `update_market`

Future table:

- `tmarget_markets`

Required constraints and indexes:

- Primary key `id`.
- Unique `slug`.
- Index `status`.
- Index `category`.
- Index `close_time`.
- Optional future ordering index on `created_at` or `updated_at`.

The future adapter should preserve current id/slug behavior: `get_market`
checks id semantics first, then slug semantics. List filtering should remain
optional and exact-match for `status` and `category` unless a future behavior
change explicitly expands it.

## 6. Status History Mapping

Current methods:

- `record_status_history`
- `list_status_history`

Future table:

- `tmarget_market_status_history`

Mapping notes:

- Insert events append-only.
- List by `market_id` ordered by `created_at`.
- Use `market_id, created_at` index.
- Preserve current dictionary fields: `id`, `market_id`, `from_status`,
  `to_status`, `changed_by`, `reason`, `created_at`.

Current service behavior records status history separately from status mutation.
Future hardening may couple market status updates and status-history inserts in
a transaction, but that is not implemented now.

## 7. Settlement Mapping

Current methods:

- `has_settlement`
- `record_settlement`

Future table:

- `tmarget_settlements`

Required fields from current records:

- `id`
- `market_id`
- `user_id`
- `outcome`
- `shares`
- `payout_amount`
- `amount`
- `idempotency_key`
- `status`
- `created_at`

Constraints and indexes:

- Unique `idempotency_key`.
- Index `market_id`.
- Index `user_id`.
- Index `created_at`.

Duplicate behavior:

- Duplicate key should return or observe the existing record.
- Duplicate settlement must not double-credit.

Wallet/ledger coordination is future careful design. This mapping plan does not
implement database transaction behavior or change `LedgerService`.

## 8. Refund Mapping

Current methods:

- `has_refund`
- `record_refund`

Future table:

- `tmarget_refunds`

Required fields from current records:

- `id`
- `market_id`
- `user_id`
- `outcome`
- `refund_amount`
- `amount`
- `idempotency_key`
- `status`
- `created_at`

Constraints and indexes:

- Unique `idempotency_key`.
- Index `market_id`.
- Index `user_id`.
- Index `created_at`.

Duplicate behavior:

- Duplicate key should return or observe the existing record.
- Duplicate refund must not double-refund.

Wallet/ledger coordination is future careful design. This mapping plan does not
implement database transaction behavior or change `LedgerService`.

## 9. Trades and Positions Mapping

Current repository contract includes demo trades and positions:

- `create_trade`
- `list_market_trades`
- `get_user_positions`
- `list_market_positions`
- `get_position`
- `upsert_position`

Current service behavior:

- Buy creates a `TmargetTrade`.
- Sell creates a `TmargetTrade`.
- Buy/sell update `TmargetPosition`.
- Buy/sell update pool state on the market.
- Position settlement/refund flags are updated through `upsert_position`.

Future tables:

- `tmarget_demo_trades`
- `tmarget_demo_positions`
- `tmarget_markets` for embedded pool state

What is currently durable-contract covered:

- Trade creation/listing.
- Position lookup/upsert/listing.
- Pool lookup/update through the market record.

What remains future/optional:

- Durable buy/sell transaction orchestration.
- Trade rejection persistence.
- Optimistic pool versioning.
- Ledger result references on trade rows.

Future integration should not change API response shapes.

## 10. Admin Audit Mapping

Current repository contract includes admin audit methods:

- `record_admin_action`
- `list_admin_actions`

Future table:

- `tmarget_admin_audit_events`

Planned fields:

- `id`
- `action`
- `market_id`
- `admin_user_id`
- `user_id`
- `details`
- `before_summary`
- `after_summary`
- `request_id`
- `created_at`

Current required fields are the existing dictionary fields produced by
`record_admin_action`. Before/after summary and request metadata are future
hardening fields.

The current demo admin guard is local/demo-only and is not production
authorization. This mapping does not imply production admin roles.

## 11. Transaction Design

Future implementation only:

- Single-method reads do not require transactions.
- Market status mutation plus status history append should use a transaction
  when service behavior couples them.
- Settlement record plus wallet ledger coordination requires a transaction or a
  carefully coordinated idempotent workflow.
- Refund record plus wallet ledger coordination requires a transaction or a
  carefully coordinated idempotent workflow.
- Trade, position, and pool mutation should use a transaction if implemented
  durably.

No database transaction behavior is implemented now.

## 12. Adapter Activation Plan

Planning only:

- Keep the adapter inactive initially.
- A passive `PostgresTmargetRepository` skeleton exists at
  `backend/tmarget/postgres_repository.py`.
- The skeleton is inactive and fail-closed. It imports no database packages,
  reads no environment variables, executes no SQL, and opens no database
  connections.
- Implement behind the existing `PostgresTmargetRepository` class later.
- Contract tests must pass against a Postgres test database before activation.
- Dev-only activation must be explicit and config-gated later.
- Never activate in a remote demo until backup, rollback, and logging are
  reviewed.

## 13. Testing Requirements for Future Adapter

Future tests should include:

- Repository contract tests against a Postgres test database.
- Idempotency duplicate-key tests.
- Settlement/refund no-double-credit tests.
- Market listing/filter tests.
- Status history append/list tests.
- Restart persistence tests.
- API response shape regression tests.
- Wallet/ledger non-regression tests.
- Product boundary wording tests, if needed.

## 14. Risk Register

- Mapping drift from repository contract.
- Partial writes.
- Duplicate settlement or refund.
- Stale status history.
- Missing unique constraints.
- Unclear trade/position ownership.
- Accidental runtime activation.
- Accidental production or real-money claims.
- Confusing Tmarget with games.

## 15. Decision Summary

- This is a mapping plan only.
- No adapter was implemented.
- No database dependency was added.
- No migration was created.
- No runtime activation occurred.
- `InMemoryTmargetRepository` remains active.
- `DurableTmargetRepository` remains inactive.
- Postgres remains the future backend direction.
