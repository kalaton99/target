# Axwins Release Checklist and Demo Readiness

This document describes the current Axwins demo platform state and the checks to run before any demo or release candidate.

## 1. Release Scope

This release/demo scope includes:

- Axwins platform shell
- Games navigation for Target, Diceget, and Flipget
- Diceget demo game module
- Flipget demo game module
- Tmarget demo prediction market product
- Read-only Wallet / Ledger / Transaction History
- Internal Demo Credits only

## 2. Product Boundaries

- Axwins is the platform.
- Target, Diceget, and Flipget are games inside Axwins.
- Target gameplay work is handled separately from this platform integration flow.
- Tmarget is not a game. It is a separate demo prediction market product inside Axwins.
- Wallet and Ledger are shared Axwins platform core services.
- Transaction History exposes read-only ledger activity for internal demo credits.

## 3. Current Route Inventory

Frontend routes:

- `/`
- `/games`
- `/games/target`
- `/diceget`
- `/diceget/:tableId`
- `/flipget`
- `/flipget/:tableId`
- `/tmarget`
- `/tmarget/markets`
- `/tmarget/markets/:slug`
- `/tmarget/portfolio`
- `/tmarget/admin/markets`
- `/wallet`

Backend routes mounted through `/api`:

- `/api/diceget`
- `/api/flipget`
- `/api/platform/wallet/me`
- `/api/platform/ledger/me`
- `/api/tmarget`

## 4. Demo-Credit and Wallet Policy

Axwins currently uses internal demo credits.

- Wallet is read-only from the UI.
- Transaction history is visible.
- Live deposits are not enabled.
- Withdrawals are not enabled.
- Card payments are not enabled.
- Crypto/Web3 transfers are not enabled.
- Telegram wallet linking is not enabled.
- Real-money trading is not enabled.

Required user-facing disclaimer:

> Axwins currently uses internal demo credits. Live deposits, withdrawals, card payments, crypto transfers, Telegram wallet linking, and real-money trading are not enabled.

## 5. Tmarget Current Limitations

- Tmarget is demo-only.
- Active runtime storage is `InMemoryTmargetRepository`.
- Durable storage contract exists, but a durable repository is not implemented.
- No Mongo/Postgres dependency is active for Tmarget persistence.
- No real admin role system exists.
- No oracle is implemented.
- No dispute workflow is implemented.
- No order book is implemented.
- No real-money market trading is implemented.
- No compliance/KYC/AML layer is implemented.

## 6. Game Module Current Limitations

- Target gameplay is integrated as a product route/card, but Target gameplay bugfixes are handled separately.
- Diceget is implemented as a separate game module.
- Flipget is implemented as a separate game module.
- Realtime/WebSocket support for Diceget and Flipget may be deferred; verify separately before presenting live multiplayer expectations.
- Live payment behavior is not connected to any game module.
- Do not claim production gambling readiness.

## 7. Release Verification Commands

Run these before any demo/release:

```powershell
git status --short
git log --oneline -8
python -m py_compile backend/ledger/service.py
python -m py_compile backend/server.py
python -m py_compile backend/diceget/*.py
python -m py_compile backend/flipget/*.py
python -m py_compile backend/tmarget/*.py
python -m py_compile backend/platform_wallet/service.py backend/platform_wallet/router.py
python -m pytest backend/tests/test_wallet_locked_lifecycle.py backend/tests/test_target_wallet_bridge.py backend/tests/test_target_wallet_regression.py backend/tests/test_diceget.py backend/tests/test_flipget.py backend/tests/test_platform_wallet.py backend/tests/test_tmarget.py backend/tests/test_tmarget_repository_admin.py backend/tests/test_tmarget_repository_contract.py
npm run build
```

If default Python lacks pytest, use the bundled/project Python that previously ran the backend tests successfully.

## 8. Manual Demo Flow Checklist

- Open Axwins hub.
- Confirm Games section shows Target, Diceget, and Flipget.
- Confirm Prediction Markets section shows Tmarget.
- Confirm Platform Core shows Wallet / Transaction History.
- Open Diceget lobby.
- Create or inspect a Diceget table if the local backend is running.
- Open Flipget lobby.
- Create or inspect a Flipget table if the local backend is running.
- Open Tmarget home.
- Open markets list.
- Open a market detail page.
- Open portfolio page.
- Open demo admin markets page.
- Open wallet.
- Confirm balance, locked balance, available balance, transaction history, filters, and read-only disclaimer.

## 9. Red Flags / Do Not Demo As Production

- Do not present Axwins as real-money ready.
- Do not present Tmarget as legally or commercially production-ready.
- Do not present internal demo credits as redeemable value.
- Do not imply deposits, withdrawals, crypto transfers, Stripe/card processing, Telegram wallet linking, KYC/AML, oracle, or dispute handling exist.
- Do not present Target gameplay bugfix status from this Axwins platform branch unless separately verified in the Target gameplay flow.

## 10. Next Recommended Phases

- Tmarget admin UX polish
- Diceget/Flipget playtest QA
- Axwins deployment preparation
- Wallet/Ledger developer docs
- Tmarget durable repository implementation planning
- Target integration review only, excluding gameplay bugfixes
