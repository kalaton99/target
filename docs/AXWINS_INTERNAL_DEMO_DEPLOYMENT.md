# Axwins Internal Demo Deployment

## Purpose

This document defines the minimal single-origin deployment shape for an Axwins
internal demo. It is deployment preparation only. It does not add runtime
infrastructure, Docker runtime files, database dependencies, migrations, SQL,
Postgres activation, payment features, or production hardening.

## Deployment Boundary

Axwins is the platform. Target, Diceget, and Flipget are games inside Axwins.
Tmarget is a separate demo prediction market product, not a game. Wallet,
Ledger, Transaction History, and Internal Demo Credits are shared Axwins
platform core services.

Axwins currently uses internal demo credits only. Deposits, withdrawals,
cash-out, crypto, card payments, and real-money trading are not enabled.

This deployment path is for internal demo review. It is not production
readiness, real-money trading readiness, payment readiness, compliance
readiness, or durable Tmarget storage readiness.

## Recommended Architecture

Use a single public origin for the internal demo:

- Serve the frontend build as a static SPA.
- Run the backend as the FastAPI app from `backend.server:app`.
- Route `/api/*` requests to the backend.
- Route `/api/v2/ws/table/*` WebSocket requests to the backend with WebSocket
  upgrade headers preserved.
- Route all non-API frontend paths to the SPA `index.html` fallback.

This shape keeps the browser-visible frontend origin and API origin aligned,
which matches the current frontend's relative `/api` calls and avoids adding
new source behavior.

## Current Application Shape

Frontend:

- Source lives under `frontend/`.
- `frontend/package.json` uses `craco build` through `npm run build`.
- The static build output is produced by the frontend build process.
- Most current demo pages call relative `/api` paths.
- `frontend/src/lib/api.js` still uses `REACT_APP_BACKEND_URL` for the legacy
  axios helper. For a single-origin demo, configure that value deliberately for
  the public demo origin if the legacy helper is used. Do not commit `.env`
  files.

Backend:

- `backend/server.py` defines the FastAPI `app`.
- Backend routes are mounted under `/api`.
- Target realtime uses `/api/v2/ws/table/{table_id}`.
- CORS is configured in `backend/server.py`.

Storage:

- Tmarget runtime storage remains `InMemoryTmargetRepository`.
- `PostgresTmargetRepository` remains inactive and fail-closed.
- `DurableTmargetRepository` remains inactive.
- `docker-compose.test.yml` is test-only Postgres scaffolding for future
  Tmarget adapter work. It is not runtime deployment infrastructure and must
  not be required for this internal demo deployment path.

## Required Environment Configuration

Do not commit secrets or local `.env` files. Configure values through the host's
secret/config mechanism.

Backend required variables visible in current code:

- `MONGO_URL`
- `DB_NAME`
- `JWT_SECRET`
- `RNG_ENCRYPTION_KEY`

Backend optional or operational variables visible in current code:

- `CORS_ORIGINS`
- `JWT_ALGORITHM`
- `JWT_EXPIRES_HOURS`
- `ENGINE_VERSION`
- `SIGNUP_BONUS`
- `TARGET_ALLOW_BOTS`
- `TARGET_BOT_COUNT_MAX`
- `ALLOW_GUEST_AUTH`
- `TMARGET_DEMO_ADMIN_ENABLED`

Frontend build-time variable visible in current code:

- `REACT_APP_BACKEND_URL`

For the single-origin internal demo, keep `/api` available on the same public
origin. If `REACT_APP_BACKEND_URL` is needed for legacy frontend helpers, set it
to the same public origin used by the deployed SPA and backend proxy. Do not set
it to a production database URL, do not use it as a secret, and do not commit it
to the repo.

## Frontend Build

From `frontend/`:

```powershell
npm run build
```

The hosting layer should serve the generated static assets and fall back to the
SPA entry point for frontend routes.

## Backend Start

The backend app is `backend.server:app`.

Candidate start command from the repository root:

```powershell
python -m uvicorn backend.server:app --host 0.0.0.0 --port 8000
```

Candidate start command from inside `backend/`:

```powershell
python -m uvicorn server:app --host 0.0.0.0 --port 8000
```

Use the command that matches the host's working directory and Python path. Run
backend compile and regression checks before treating the deployment as a demo
checkpoint.

## Routing Rules

Required routing behavior:

- `/api/*` -> FastAPI backend.
- `/api/v2/ws/table/*` -> FastAPI backend with WebSocket upgrade support.
- `/`, `/games`, `/diceget`, `/flipget`, `/tmarget`, `/wallet`, and other
  frontend deep links -> static SPA fallback to `index.html`.
- Static assets -> served directly by the frontend static host.

Do not route `docker-compose.test.yml` into runtime. It is not a deployment
input.

## SPA Fallback Checklist

The frontend host must return the SPA entry point for direct navigation to:

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
- `/lobby`
- `/play`
- `/play/:tableId`
- `/login`
- `/register`
- `/menu`
- `/tables`

API paths must not fall back to the SPA.

## CORS Guidance

For a single-origin proxy, browser requests should reach `/api` on the same
origin as the SPA. If the backend is exposed on a separate origin during
testing, configure `CORS_ORIGINS` to the exact frontend origin. Do not rely on
permissive CORS as a production security claim.

## WebSocket / Realtime Proxy Note

Target realtime uses `/api/v2/ws/table/{table_id}`. Any reverse proxy or host
router must support WebSocket upgrade for this path. If WebSocket upgrade is not
preserved, Target table play can fail even when normal HTTP `/api` calls work.

Do not change Target gameplay, WebSocket protocol, or routing behavior in this
deployment scaffold.

## Manual Smoke Checklist

Before opening the internal demo:

- Confirm `git status --short` is clean.
- Confirm the intended commit and tag.
- Run `npm run build`.
- Run backend compile checks.
- Run backend regression if the environment supports it.
- Confirm the backend starts and `/api/health` returns ok.
- Confirm direct frontend deep links use the SPA fallback.
- Confirm `/api` routes do not return the SPA.
- Confirm `/api/v2/ws/table/*` supports WebSocket upgrade.
- Open the Axwins hub.
- Open Games.
- Open Diceget.
- Open Flipget.
- Open Target entry without changing Target gameplay.
- Open Tmarget markets, market detail, portfolio, and admin demo pages.
- Open Wallet / Ledger / Transaction History.
- Confirm the internal demo-credit disclaimer is visible where relevant.
- Confirm no Deposit, Withdraw, Cash Out, Buy Credits, Connect Wallet, Add
  Card, Link Telegram Wallet, crypto, or real-money action is present.
- Confirm Tmarget is not presented as a game.
- Confirm Target is not presented as the platform.

## Rollback Plan

Use the last known clean demo checkpoint as the rollback target. The current
internal demo checkpoint is tagged:

- `axwins-demo-ready-2026-05`

Rollback if:

- frontend build fails,
- backend compile or regression fails,
- backend startup fails,
- `/api` proxying fails,
- SPA fallback fails,
- WebSocket upgrade fails,
- real-money/payment wording appears enabled,
- Tmarget storage is described as durable runtime storage, or
- any unintended source/runtime behavior changes are discovered.

## Red Flags

Stop the demo deployment if any of these are true:

- A `.env` file or secret is staged.
- A Docker runtime file is introduced unintentionally.
- A DB dependency, migration, SQL file, or Postgres runtime activation appears.
- `docker-compose.test.yml` is treated as runtime infrastructure.
- Tmarget is described as a game.
- Target is described as the platform.
- Wallet UI includes write actions for deposits, withdrawals, cash-out, buying
  credits, cards, crypto, or Telegram wallet linking.
- Payment, crypto, real-money, KYC/AML, compliance, oracle, order book, or
  dispute readiness is implied.
- Tmarget in-memory state reset behavior is hidden or contradicted.

## Non-Goals

This scaffold does not:

- add a Dockerfile,
- add runtime Docker Compose,
- add `.env` files,
- add database dependencies,
- add migrations,
- add SQL,
- activate Postgres,
- change repository selection,
- change Tmarget runtime/storage/pricing/settlement/admin guard behavior,
- change wallet/ledger behavior,
- change Target/Diceget/Flipget gameplay,
- add payment, crypto, deposits, withdrawals, cash-out, buy-credit,
  connect-wallet, card, Telegram wallet, or real-money features, or
- claim production readiness.

## Decision Summary

The selected minimal internal demo path is a single-origin deployment:

- static SPA frontend,
- FastAPI backend from `backend.server:app`,
- `/api` and `/api/v2/ws/table/*` routed to backend,
- SPA fallback for frontend deep links,
- no runtime Docker,
- no Postgres activation,
- no durable Tmarget runtime storage,
- no payment or real-money functionality.

