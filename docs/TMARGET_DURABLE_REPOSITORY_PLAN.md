# Tmarget Durable Repository Plan

## 1. Purpose

This document plans a future durable repository for Tmarget without
implementing it. It is a developer-facing checkpoint for turning the current
in-memory demo repository into a durable adapter later while preserving the
existing Tmarget API behavior, pricing behavior, settlement behavior, and
Axwins product boundaries.

## 2. Current State

Tmarget is a demo prediction market product inside Axwins. It is not a game and
must remain separate from Target, Diceget, and Flipget game modules.

Current state:

- Active runtime storage is `InMemoryTmargetRepository`.
- The durable storage contract exists in `backend/tmarget/STORAGE_MODEL.md`.
- Repository contract tests exist in
  `backend/tests/test_tmarget_repository_contract.py`.
- No durable adapter is active.
- No Mongo/Postgres dependency is active.
- Tmarget demo admin tooling exists.
- Demo admin endpoints use the local/demo-only
  `X-Axwins-Demo-Admin: true` guard.
- Tmarget uses internal demo credits only.
- Real-money trading is not enabled.

> Axwins currently uses internal demo credits. Live deposits, withdrawals, card payments, crypto transfers, Telegram wallet linking, and real-money trading are not enabled.

## 3. Existing Repository Contract

The current repository contract is implemented by
`backend/tmarget/repository.py` and covered by
`backend/tests/test_tmarget_repository_contract.py`.

Existing contract capabilities:

- Create and update markets.
- Retrieve markets by id or slug.
- Retrieve markets by slug through an explicit helper.
- List markets with optional `status` and `category` filters.
- Create demo trade records.
- List market trades in stable insertion order.
- Retrieve user positions.
- Retrieve market positions, optionally filtered by user.
- Retrieve a single user/market/outcome position.
- Upsert positions by unique `user_id + market_id + outcome`.
- Retrieve liquidity pool state by market id.
- Update liquidity pool state.
- Record settlement entries by idempotency key.
- Check whether a settlement idempotency key already exists.
- Record refund entries by idempotency key.
- Check whether a refund idempotency key already exists.
- Record admin actions.
- List admin actions.
- Record market status history events.
- List market status history events by market.

Current concrete methods:

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

Future durable adapters should implement this same behavior before runtime
activation is considered.

## Passive Skeleton Checkpoint

A passive durable adapter skeleton exists at
`backend/tmarget/durable_repository.py`. It is intentionally inactive and fails
closed with `NotImplementedError` for every repository method. Active runtime
storage remains `InMemoryTmargetRepository`; no durable backend is selected,
configured, or imported, and no production persistence is implemented.

## 4. Durable Storage Goals

A future durable repository should:

- Preserve existing API response shapes.
- Preserve existing service behavior.
- Preserve deterministic settlement/refund idempotency.
- Preserve settlement/refund safety under retries.
- Support market lookup by id and slug.
- Support filtered market listing.
- Support market status history.
- Support admin auditability.
- Support operational debugging for trades, positions, settlements, refunds,
  and admin actions.
- Avoid accidental real-money claims.
- Keep Tmarget separate from games and game-specific concepts.

## 5. Entity Model Planning

Entities grounded in current code behavior:

- Market: represented by `TmargetMarket`.
- Market rule: represented by `TmargetMarketRule`.
- Liquidity pool: represented by `TmargetLiquidityPool`.
- Demo trade record: represented by `TmargetTrade`.
- Demo position record: represented by `TmargetPosition`.
- Settlement record: represented by repository settlement records.
- Refund record: represented by repository refund records.
- Admin action or audit event: represented by repository admin action records.
- Market status history event: represented by repository status history records.

Future/optional hardening entities:

- Generic idempotency record shared across operation types.
- Expanded audit metadata for request ids, actor roles, IP/device metadata, and
  ledger result references.

## 6. Suggested Schema Fields

The fields below are planning guidance. "Current required" means the current
code or repository contract already depends on the field or behavior. "Future
hardening" means the field is useful later but should not be treated as
required by the current runtime.

### Market

Current required fields:

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

Future hardening fields:

- `closed_at`
- `resolved_at`
- `cancelled_at`
- `last_status_change_id`
- `archived_at`

### Market Rule

Current required fields:

- `market_id`
- `source_url`
- `resolution_criteria`
- `invalid_conditions`
- `timezone`

Future hardening fields:

- `rule_version`
- `created_at`
- `updated_at`
- `updated_by`

### Liquidity Pool

Current required fields:

- `market_id`
- `yes_pool`
- `no_pool`
- `liquidity_parameter`
- `updated_at`

Current derived fields:

- `yes_price`
- `no_price`

`yes_price` and `no_price` are currently derived from pool state by
`pricing.py`. They may be stored later as snapshots for query performance, but
pricing logic should remain isolated from repository persistence.

Future hardening fields:

- `version`
- `last_trade_id`

### Demo Trade Record

Current required fields:

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

Future hardening fields:

- `ledger_idempotency_key`
- `ledger_result_ref`
- `rejected_reason`
- `pool_before`
- `pool_after`

### Demo Position Record

Current required fields:

- `user_id`
- `market_id`
- `outcome`
- `shares`
- `avg_price`
- `realized_pnl`
- `cost_basis`
- `settled`
- `refunded`

Future hardening fields:

- `updated_at`
- `version`
- `last_trade_id`
- `last_settlement_id`
- `last_refund_id`

### Settlement Record

Current required fields:

- `id`
- `market_id`
- `user_id`
- `outcome`
- `payout_amount`
- `amount`
- `idempotency_key`
- `status`
- `created_at`

Future hardening fields:

- `shares`
- `source_module`
- `reason`
- `ledger_result_ref`
- `retry_count`
- `error_message`

### Refund Record

Current required fields:

- `id`
- `market_id`
- `user_id`
- `outcome`
- `refund_amount`
- `amount`
- `idempotency_key`
- `status`
- `created_at`

Future hardening fields:

- `source_module`
- `reason`
- `ledger_result_ref`
- `retry_count`
- `error_message`

### Admin Action / Audit Event

Current required fields:

- `id`
- `action`
- `market_id`
- `admin_user_id`
- `user_id`
- `details`
- `created_at`

Future hardening fields:

- `before_status`
- `after_status`
- `request_id`
- `actor_role`
- `notes`
- `ip_address`

### Market Status History Event

Current required fields:

- `id`
- `market_id`
- `from_status`
- `to_status`
- `changed_by`
- `reason`
- `created_at`

Future hardening fields:

- `admin_action_id`
- `request_id`
- `metadata`

### Generic Idempotency Record

This is future/optional. Current code stores settlement and refund idempotency
inside those domain records.

Future hardening fields:

- `key`
- `operation_type`
- `entity_type`
- `entity_id`
- `status`
- `result_ref`
- `created_at`
- `updated_at`

## 7. Idempotency Plan

Settlement and refund idempotency prevents duplicate demo-credit payouts or
refunds when an operation is retried, double-clicked, or replayed after a
partial failure.

Future durable storage should preserve deterministic keys already used by the
service layer:

- Settlement: `tmarget:{market_id}:settlement:{user_id}:{outcome}`
- Refund: `tmarget:{market_id}:refund:{user_id}:{outcome}:{position_outcome}`

Durable constraints:

- Settlement `idempotency_key` must be unique.
- Refund `idempotency_key` must be unique.
- Duplicate settlement attempts must not create a second settlement record.
- Duplicate refund attempts must not create a second refund record.
- Duplicate attempts should return or observe the existing record whenever
  practical.

This domain-level idempotency should complement, not replace, LedgerService
idempotency. Tmarget records should retain the key used for the corresponding
ledger mutation and, later, any ledger result reference that becomes available.

## 8. Status Lifecycle Plan

Actual market statuses in current code:

- `draft`
- `open`
- `paused`
- `closed`
- `resolving`
- `resolved`
- `cancelled`

Current service transitions:

- `create_market` creates `draft`.
- `open_market` allows `draft -> open` and `paused -> open`.
- `pause_market` allows `open -> paused`.
- `close_market` allows `open -> closed` and `paused -> closed`.
- `resolve_market` requires `closed`, briefly sets `resolving`, then stores
  `resolved`.
- `cancel_market` rejects only already `resolved` markets and stores
  `cancelled`.
- `update_market` allows edits only while `draft` or `paused`.
- Trading is allowed only while `open`.

Current transition hardening gaps to consider later:

- The repository has status history methods, but service status transitions do
  not currently require every transition to record status history.
- `cancel_market` currently allows cancellation from more than one non-resolved
  state.
- `resolving` is a transient service state, not a durable workflow checkpoint
  with retry/recovery semantics.

Future durable implementation should preserve current behavior first, then add
status-history and transition hardening only in a separate behavior-focused
pass.

## 9. Adapter Implementation Strategy

Future implementation strategy:

- Keep `InMemoryTmargetRepository` as the demo/test adapter.
- Add a durable adapter behind the same repository contract later.
- Make adapter selection explicit via configuration in a future pass.
- Keep service layer call sites stable where possible.
- Run the existing repository contract tests against the in-memory adapter.
- Add durable-adapter contract tests before activating durable storage.
- Do not activate durable storage in runtime until tests, rollback, logging, and
  operational expectations are clear.

The durable adapter should be introduced as an implementation detail behind the
repository contract, not as a change to Tmarget market behavior.

## 10. Migration Strategy

Planning only:

1. Phase 1: Finalize schema design from `STORAGE_MODEL.md` and this plan.
2. Phase 2: Implement a durable adapter behind the repository contract.
3. Phase 3: Run repository contract tests against both in-memory and durable
   adapters.
4. Phase 4: Activate durable storage only for local/dev environments.
5. Phase 5: Consider remote demo activation only after backup, rollback,
   logging, and operational review.

No migrations should be added in this pass.

In-memory demo data should not be migrated automatically unless an explicit
export/import path is designed, tested, and reviewed. Production-like durable
environments should start empty or use controlled fixtures.

## 11. Testing Strategy

Current local demo validation checkpoint passed backend regression with 91
tests.

Future durable repository tests should include:

- Repository contract tests.
- Market create, lookup, listing, and update tests.
- Market status transition tests.
- Market status history tests.
- Trade listing order tests.
- Position upsert and lookup tests.
- Liquidity pool update tests.
- Idempotent settlement tests.
- Idempotent refund tests.
- Admin action/audit tests.
- Restart persistence tests.
- Rollback and partial-failure safety tests.

Durable adapter tests should be Mongo/Postgres-specific only after an adapter is
chosen. They should not replace the current Mongo-free local test flow unless a
future phase explicitly changes that policy.

## 12. Operational Risks

Known risks:

- In-memory state resets on backend restart.
- Duplicate settlement if idempotency is broken.
- Duplicate refund if idempotency is broken.
- Stale market status if status transitions are not persisted consistently.
- Admin action audit gaps.
- Remote demo restart risk.
- Overclaiming production durability before implementation.
- Accidental real-money implication in docs or UI.

## 13. Non-Goals

This plan does not implement:

- Durable repository code.
- Mongo/Postgres selection or dependency.
- Redis.
- Migrations.
- Database drivers.
- Runtime repository activation.
- Payment, deposit, withdrawal, cash out, or buy-credit flows.
- Crypto/Web3 transfers.
- Stripe/card payments.
- Telegram wallet linking.
- Real-money trading.
- Oracle or dispute workflow.
- Compliance/KYC/AML behavior.
- Order book behavior.
- Target, Diceget, or Flipget gameplay changes.

## 14. Recommended Next Implementation Checkpoint

The next implementation checkpoint should be narrow:

- Choose a durable backend candidate.
- Add an adapter skeleton only.
- Keep the durable adapter inactive.
- Run repository contract tests against the adapter.
- Keep `InMemoryTmargetRepository` active for runtime until tests and rollback
  plans are ready.
- Do not activate durable storage remotely until operational logging, backup,
  rollback, and admin access expectations are reviewed.

## 15. Developer Checklist Before Implementation

Before any durable repository implementation pass:

- Read `backend/tmarget/STORAGE_MODEL.md`.
- Read `backend/tmarget/repository.py`.
- Read `backend/tests/test_tmarget_repository_contract.py`.
- Verify Git status is clean.
- Run backend regression.
- Confirm Axwins product boundary wording still holds.
- Confirm Tmarget is not presented as a game.
- Confirm no payment, deposit, withdrawal, crypto/Web3, Stripe/card, Telegram
  wallet, or real-money feature is being added.
- Confirm Tmarget service behavior, pricing, settlement, and admin guard
  behavior are intentionally unchanged unless a future task explicitly scopes
  those changes.
