# Axwins Deployment Preparation

## 1. Purpose

This document prepares the current Axwins demo platform for local/demo
deployment and verification. It is a developer-facing checklist for confirming
that the repo, routes, tests, build, and product boundaries are ready before a
demo or release candidate.

## 2. Current Scope

Current demo scope includes:

- Axwins platform shell
- Games: Target, Diceget, Flipget
- Prediction Markets: Tmarget
- Platform Core: Wallet, Ledger, Transaction History, Internal Demo Credits
- Tmarget demo admin tooling
- Read-only wallet UI
- Internal demo credits only

## 3. Non-Production Boundaries

This Axwins state is not real-money ready.

- Deposits are not enabled.
- Withdrawals are not enabled.
- Card payments are not enabled.
- Crypto/Web3 transfers are not enabled.
- Telegram wallet linking is not enabled.
- Real-money trading is not enabled.
- KYC/AML is not implemented.
- Tmarget has no production oracle or dispute workflow.
- Tmarget active runtime storage remains `InMemoryTmargetRepository` unless the
  code says otherwise.
- A durable repository contract exists for Tmarget, but durable storage is not
  implemented.

Required user-facing disclaimer:

> Axwins currently uses internal demo credits. Live deposits, withdrawals, card payments, crypto transfers, Telegram wallet linking, and real-money trading are not enabled.

## 4. Local Environment Checklist

Before local/demo deployment:

- Confirm repository status is clean with `git status --short`.
- Confirm the intended branch and recent commits.
- Confirm frontend dependencies are installed under `frontend/`.
- Confirm backend dependencies are installed for the Python interpreter used by
  this project.
- Confirm backend can compile.
- Confirm frontend can build.
- Confirm required backend environment configuration is present.
- Confirm no generated files are staged or committed.
- Confirm `node_modules`, build output, caches, logs, local DB files,
  screenshots, and temporary artifacts are not committed.

Environment names visible in the current backend code:

- `MONGO_URL`
- `DB_NAME`
- `CORS_ORIGINS`
- `JWT_SECRET`
- `JWT_ALGORITHM`
- `JWT_EXPIRES_HOURS`
- `ENGINE_VERSION`
- `SIGNUP_BONUS`
- `RNG_ENCRYPTION_KEY`
- `TARGET_ALLOW_BOTS`
- `TARGET_BOT_COUNT_MAX`
- `ALLOW_GUEST_AUTH`
- `TMARGET_DEMO_ADMIN_ENABLED`

Frontend build-time environment visible in current frontend code:

- `REACT_APP_BACKEND_URL`

Most current demo pages use relative `/api` calls. The legacy frontend API
helper still uses `REACT_APP_BACKEND_URL`; for a single-origin internal demo,
configure it deliberately for the public demo origin if that helper is used.

Do not invent secret values. Inspect existing project env examples or the
current local configuration when preparing an environment.

## 5. Backend Verification Commands

Run before a demo/release candidate:

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
```

If default Python lacks `pytest`, use the bundled/project Python that previously
ran the backend tests successfully.

## 6. Frontend Verification Commands

The frontend package currently exposes these scripts in `frontend/package.json`:

```powershell
npm run build
npm run start
npm run test
```

Use `npm run build` as the required build verification. `npm run start` is the
visible local dev server command if an interactive browser smoke pass is needed.

## 7. Demo Smoke Flow

Manual demo flow:

- Open the Axwins hub.
- Confirm the product grouping:
  - Games: Target, Diceget, Flipget
  - Prediction Markets: Tmarget
  - Platform Core: Wallet / Transaction History
- Open Diceget.
- Open Flipget.
- Open Tmarget markets.
- Open Tmarget admin markets.
- Open Wallet.
- Confirm the internal demo-credit disclaimer is visible where relevant.
- Confirm there are no Deposit, Withdraw, Cash Out, Buy Credits, Connect Wallet,
  Add Card, or Link Telegram Wallet actions.
- Confirm Tmarget is not presented as a game.
- Confirm Target is not presented as the platform.

## 8. Route Checklist

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

## 9. Data / Storage Notes

- Tmarget active runtime storage is in-memory unless code says otherwise.
- Tmarget durable storage contract exists.
- A test-only `docker-compose.test.yml` Postgres scaffold may exist for future
  Tmarget adapter testing, but it is not runtime storage and does not activate
  durable persistence.
- Demo state may reset between process restarts when in-memory storage is used.
- Wallet/ledger persistence should be verified from the actual current backend
  configuration before a demo.
- Do not claim production durability unless it has been explicitly verified.

## 10. Deployment Red Flags

Treat these as blockers:

- Backend tests fail.
- Frontend build fails.
- Git status is dirty with unintended generated files.
- Wording implies real-money readiness.
- Internal demo-credit disclaimer is missing.
- Tmarget is presented as a game.
- Target is presented as the platform.
- Wallet UI shows deposit, withdrawal, cash-out, buy-credit, connect-wallet,
  add-card, or Telegram wallet actions.
- Unreviewed changes touch wallet/ledger behavior, gameplay behavior, or Tmarget
  settlement behavior.

## 11. Recommended Release Gate

Minimum gate before demo/release:

- Clean `git status --short`.
- Backend compile passes.
- Backend regression passes.
- `npm run build` passes.
- Manual smoke flow passes.
- Docs are reviewed.
- No forbidden payment/crypto/real-money wording is present.
- No generated files are committed.

## 12. Future Deployment Work

Future work, not implemented in this checkpoint:

- Environment hardening
- Hosting target decision
- CI pipeline
- Durable storage planning
- Production auth/admin roles
- Monitoring/logging
- Security review
- Payment/compliance review if real-money is ever considered
