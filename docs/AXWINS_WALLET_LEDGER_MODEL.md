# Axwins Wallet / Ledger Model

## 1. Purpose

This document defines the shared Axwins wallet and ledger model for the current
demo/internal-credit platform. It is intended to keep future work aligned across
Axwins, the game modules, Tmarget, and platform core services.

The current model is internal demo credits only. It is not a live-money payment,
deposit, withdrawal, custody, crypto, or card-processing system.

## 2. Product Boundaries

- Axwins is the platform.
- Target, Diceget, and Flipget are games inside Axwins.
- Target gameplay work is handled separately from this platform flow.
- Tmarget is not a game. It is a separate demo prediction market product inside Axwins.
- Wallet and Ledger are shared Axwins platform core services.
- Transaction History is the read-only user-facing view of ledger activity.

## 3. Current Wallet Model

The current wallet model uses internal demo credits only.

- `balance`: spendable internal demo-credit balance.
- `locked_balance`: reserved internal demo credits for pending product actions.
- `locked`: legacy alias exposed alongside `locked_balance`.
- `available_balance`: currently exposed as the user's spendable demo-credit balance.
- Transaction history: read-only ledger entries from `/api/platform/ledger/me`.
- Wallet UI: read-only. It does not expose top-up, cash-out, deposit, withdrawal, card, crypto, or Telegram wallet actions.

Required user-facing disclaimer:

> Axwins currently uses internal demo credits. Live deposits, withdrawals, card payments, crypto transfers, Telegram wallet linking, and real-money trading are not enabled.

## 4. Ledger Source Modules

Current `source_module` values in `backend/ledger/service.py`:

- `target`: Target game wallet activity.
- `diceget`: Diceget game wallet activity.
- `flipget`: Flipget game wallet activity.
- `tmarget`: Tmarget demo prediction market wallet activity.
- `payment`: sandbox/demo-credit intake style entries only. This is not live payment processing.
- `admin`: admin or platform-granted demo-credit entries.

User-facing wallet labels:

- `target` -> Target
- `diceget` -> Diceget
- `flipget` -> Flipget
- `tmarget` -> Tmarget
- `payment` -> Payment / Demo Credit
- `admin` -> Admin

## 5. Ledger Reason Constants

Use only reason constants that exist in `backend/ledger/service.py`.

### Target Reasons

- `target_join_lock`: used when Target locks a table stake at create/join. Affects both balance and locked balance. Must be idempotent.
- `target_cancel_unlock`: used when Target releases a pre-game locked stake. Affects both balance and locked balance. Must be idempotent.
- `target_win_payout`: used when Target settlement consumes locked stake and credits payout. Affects locked balance and may affect balance. Must be idempotent.
- `target_refund`: used for Target refund paths. May affect locked balance and/or balance depending on the operation. Must be idempotent.

### Diceget Reasons

- `diceget_join_lock`: used when Diceget locks a table stake at create/join. Affects both balance and locked balance. Must be idempotent.
- `diceget_cancel_unlock`: used when Diceget releases a pre-game locked stake. Affects both balance and locked balance. Must be idempotent.
- `diceget_win_payout`: used when Diceget final settlement consumes locked stake and credits winners. Affects locked balance and may affect balance. Must be idempotent.
- `diceget_refund`: used for Diceget refund paths. May affect locked balance and/or balance depending on the operation. Must be idempotent.

### Flipget Reasons

- `flipget_join_lock`: used when Flipget locks a table stake at create/join. Affects both balance and locked balance. Must be idempotent.
- `flipget_cancel_unlock`: used when Flipget releases a pre-flip locked stake. Affects both balance and locked balance. Must be idempotent.
- `flipget_win_payout`: used when Flipget final settlement consumes locked stake and credits the winner. Affects locked balance and may affect balance. Must be idempotent.
- `flipget_refund`: used for Flipget refund paths. May affect locked balance and/or balance depending on the operation. Must be idempotent.

### Tmarget Reasons

- `tmarget_buy_cost`: used when buying YES/NO demo shares. Affects balance. Must be idempotent where the trade action can be retried.
- `tmarget_sell_credit`: used when selling YES/NO demo shares. Affects balance. Must be idempotent where the trade action can be retried.
- `tmarget_settlement_win`: used when resolved markets credit winning positions. Affects balance. Must be idempotent.
- `tmarget_settlement_loss`: used to record losing-side settlement facts when applicable. May not credit balance. Must be idempotent when recorded.
- `tmarget_refund`: used when cancelled/invalid markets refund demo credits. Affects balance. Must be idempotent.
- `tmarget_fee`: reserved for demo market fees if applied. Affects balance if used. Must be idempotent.
- `tmarget_admin_market_create`: reserved for demo admin market-creation activity if ledgered. Must be idempotent if it mutates wallet state.

### Payment / Admin Reasons

- `sandbox_deposit`: demo-credit grant/intake entry. Affects balance. Must be idempotent.
- `admin_credit`: admin demo-credit grant. Affects balance. Must be idempotent.
- `SIGNUP_BONUS`: legacy uppercase signup bonus reason accepted by wallet history labeling. Affects balance when present. Should be idempotent.

## 6. Lock / Unlock / Settlement Lifecycle

General lifecycle:

1. Lock balance when joining or creating a paid demo-credit product action.
2. Unlock balance only when cancellation/refund rules allow it.
3. Settle locked funds after a final outcome.
4. Use deterministic idempotency keys so duplicate clicks, retries, and repeated settlement publications do not double-lock, double-unlock, double-refund, or double-pay.

`LedgerService.lock_balance()` moves spendable balance into locked balance.

`LedgerService.unlock_balance()` releases locked balance back to spendable balance.

`LedgerService.settle_locked()` consumes locked stake and optionally credits a payout to spendable balance.

### Target Exposure Model

Target locks the table stake when a player creates or joins a table. Pre-game
leave unlocks that stake. Once Target is running, payout, ended, or otherwise
final, the stake is treated as non-refundable by the wallet bridge.

Target payout mirrors the existing engine payout plan into the ledger. The
wallet layer does not change Target rules, reducer behavior, RNG, or payout
math. In-hand betting beyond the locked table stake remains engine-local.

### Diceget Exposure Model

Diceget locks a table stake when a player creates or joins a table. Pre-game
leave unlocks that stake. Active, showdown, and settled tables are
non-refundable.

Dice scoring is engine-local. Rolls, holds, busts, and forfeits do not move
money. Final settlement mirrors the Diceget showdown result into the ledger.

### Flipget Exposure Model

Flipget locks the table stake when a player creates or joins a table. Pre-flip
leave unlocks that stake. Once a table is flipping or settled, the stake is
non-refundable.

The coin result is backend-authoritative. Final settlement mirrors the stored
result into the ledger.

### Tmarget Demo-Market Exposure Model

Tmarget uses `source_module="tmarget"` with internal demo credits only. Buying
YES/NO debits demo balance. Selling shares credits demo balance. Resolved
winning positions receive demo settlement credits. Cancelled or invalid markets
refund remaining demo cost basis.

Tmarget storage remains `InMemoryTmargetRepository` at runtime. The durable
storage contract exists, but no durable repository is active.

## 7. Wallet UI Behavior

Routes and endpoints:

- Frontend route: `/wallet`
- Wallet summary endpoint: `/api/platform/wallet/me`
- Ledger history endpoint: `/api/platform/ledger/me`

Wallet source labels:

- Target
- Diceget
- Flipget
- Tmarget
- Admin
- Payment / Demo Credit

Wallet reason labels:

- stake locked
- stake unlocked
- win payout
- refund
- demo credit
- market buy
- market sell
- market settlement
- market refund

Wallet filters:

- All
- Games
- Prediction Markets
- Admin / Demo Credit

Transaction detail fields:

- `source_module`
- `source_label`
- `source_id`
- `reason`
- `reason_label`
- `amount`
- `balance_before`
- `balance_after`
- `locked_before`
- `locked_after`
- `created_at`
- `status`

## 8. Idempotency Rules

Deterministic idempotency keys protect wallet operations from retries,
double-clicks, repeated events, and replayed settlement publication.

Examples:

- Table join lock: `target:{table_id}:join:{user_id}`, `diceget:{table_id}:join:{user_id}`, or `flipget:{table_id}:join:{user_id}`.
- Pre-game unlock: product/table/user-specific cancel or refund key.
- Payout settlement: product/table/user/round-specific payout key.
- Market settlement: Tmarget market/user/outcome settlement key.
- Market refund: Tmarget market/user/outcome refund key.

Expected behavior:

- Duplicate lock calls must not double-lock.
- Duplicate unlock calls must not double-unlock.
- Duplicate settlement calls must not double-pay.
- Duplicate refund calls must not double-credit.
- Reusing an idempotency key with different parameters should fail rather than silently mutate wallet state.

## 9. Deferred / Not Implemented

The following are not implemented:

- live deposits
- withdrawals
- cash out
- buy credits
- card payments
- crypto/Web3 transfers
- Telegram wallet linking
- real-money trading
- KYC/AML
- production payment processor
- production custody
- Tmarget order book
- Tmarget oracle
- Tmarget dispute workflow
- compliance layer for real-money operations

## 10. Future Implementation Notes

- If live payments are added, they must be separate from current demo-credit ledger assumptions.
- Payment compliance and security review is required before enabling real funds.
- Real-money flows must not reuse demo assumptions blindly.
- Wallet write endpoints need authorization, audit logging, idempotency, fraud/chargeback controls, reconciliation, and compliance review.
- Tmarget real-money prediction markets require legal/compliance review, oracle/resolution/dispute design, and jurisdiction review.
- Any durable wallet or market repository work must preserve idempotency and avoid changing existing API response shapes without an explicit migration plan.

## 11. Developer Checklist

For any future PR touching wallet or ledger behavior:

- Confirm `source_module` is valid.
- Confirm the reason constant exists in `backend/ledger/service.py`.
- Confirm the transaction is idempotent where needed.
- Confirm locked balance cannot go negative.
- Confirm available/spendable balance cannot go negative.
- Confirm settlement cannot double-pay.
- Confirm refunds cannot double-credit.
- Confirm wallet UI labels are updated if new reasons or modules are added.
- Add or update tests for lock, unlock, settlement, refund, and idempotency behavior.
- Do not expose live-money wording unless the feature is actually implemented and approved.
- Do not add Deposit, Withdraw, Cash Out, Buy Credits, Connect Wallet, Add Card, or Link Telegram Wallet UI actions without production review.
