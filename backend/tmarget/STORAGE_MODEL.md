# Tmarget Storage Model

Tmarget is a demo prediction market product inside Axwins. It is not a game and
must remain separate from Target, Diceget, and Flipget game modules.

The active runtime storage remains `InMemoryTmargetRepository`. Future durable
repositories should implement the same repository contract without changing API
response shapes or market behavior.

## Repository Contract

Future durable implementations should provide these methods:

- `create_market(market)`
- `get_market(market_id_or_slug)`
- `get_market_by_slug(slug)`
- `list_markets(status=None, category=None)`
- `update_market(market)`
- `create_trade(trade)`
- `list_market_trades(market_id)`
- `get_user_positions(user_id)`
- `list_market_positions(market_id, user_id=None)`
- `get_position(user_id, market_id, outcome)`
- `upsert_position(position)`
- `get_pool(market_id)`
- `update_pool(market_id, pool)`
- `record_settlement(market_id, user_id, outcome, amount, idempotency_key)`
- `has_settlement(idempotency_key)`
- `record_refund(market_id, user_id, outcome, amount, idempotency_key)`
- `has_refund(idempotency_key)`
- `record_admin_action(action, market_id, user_id, details=None)`
- `list_admin_actions()`
- `record_status_history(market_id, from_status, to_status, changed_by, reason)`
- `list_status_history(market_id)`

## Recommended Collections or Tables

### TmargetMarket

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

### TmargetMarketRule

- `market_id`
- `source_url`
- `resolution_criteria`
- `invalid_conditions`
- `timezone`

### TmargetLiquidityPool

- `market_id`
- `yes_pool`
- `no_pool`
- `liquidity_parameter`
- `yes_price`
- `no_price`
- `updated_at`

`yes_price` and `no_price` may be stored as denormalized snapshots for query
speed, but pricing logic remains in `pricing.py`.

### TmargetTrade

- `id`
- `user_id`
- `market_id`
- `side`
- `outcome`
- `shares`
- `price`
- `cost`
- `fee`
- `status`
- `created_at`

### TmargetPosition

- `user_id`
- `market_id`
- `outcome`
- `shares`
- `avg_price`
- `realized_pnl`
- `updated_at`

### TmargetSettlement

- `id`
- `market_id`
- `user_id`
- `outcome`
- `shares`
- `payout_amount`
- `idempotency_key`
- `status`
- `created_at`

### TmargetRefund

- `id`
- `market_id`
- `user_id`
- `refund_amount`
- `idempotency_key`
- `status`
- `created_at`

### TmargetAdminAction

- `id`
- `market_id`
- `admin_user_id`
- `action`
- `before_status`
- `after_status`
- `notes`
- `created_at`

### MarketStatusHistory

- `id`
- `market_id`
- `from_status`
- `to_status`
- `changed_by`
- `reason`
- `created_at`

### IdempotencyRecord

- `key`
- `operation_type`
- `entity_type`
- `entity_id`
- `status`
- `result_ref`
- `created_at`

## Indexes and Unique Constraints

- `markets.id` unique
- `markets.slug` unique
- `markets.status` for market lists
- `markets.close_time` for close/expiry scans
- `trades.id` unique
- `trades.market_id, trades.created_at` for market trade listing
- `positions.user_id, positions.market_id, positions.outcome` unique
- `positions.user_id` for portfolio lookup
- `positions.market_id` for settlement scans
- `settlements.idempotency_key` unique
- `refunds.idempotency_key` unique
- `admin_actions.id` unique
- `admin_actions.market_id, admin_actions.created_at` for market audit trails
- `status_history.market_id, status_history.created_at` for status timeline listing
- `idempotency.key` unique

## Idempotency Strategy

Tmarget trade debits/credits, settlement wins, and refunds rely on deterministic
LedgerService idempotency keys. Durable Tmarget settlement and refund records
should store the same keys and, when available, references to ledger mutation
results such as journal IDs or transaction IDs.

Duplicate settlement/refund records must be suppressed by unique idempotency
keys. Replays should return or observe the original record rather than creating
another payout/refund record.

## Ledger Relationship

The shared Axwins LedgerService remains the source of wallet balance mutation.
Tmarget records should store domain-level facts:

- what market action happened
- which user/outcome/shares were involved
- which ledger idempotency key was used
- whether the domain record posted, failed, or was replayed

Tmarget durable storage should not replace LedgerService accounting.

## Migration Plan

Current in-memory demo data is non-durable. It should not be migrated
automatically unless an explicit export/import path is reviewed and approved.
Production-like durable environments should start empty or load controlled
fixtures only.

## Deferred Production Requirements

- real admin roles
- durable audit log
- oracle/resolution workflow
- dispute workflow
- market compliance review
- KYC/AML only if real-money is ever introduced
- market risk controls
- production security review

No live deposits, withdrawals, crypto/Web3 transfers, Stripe/card payments,
Telegram wallet linking, order book, oracle integration, dispute workflow, or
real-money trading exists in this phase.
