# Axwins Hosting / Deployment Plan

## 1. Purpose

This document compares hosting and deployment options for the current Axwins
demo platform and recommends a conservative, low-risk path for demo
presentation. It is planning documentation only and does not implement
deployment infrastructure.

## 2. Current Application Shape

Based on code inspection, the current application contains:

- A frontend app under `frontend/`.
  - `frontend/package.json` exposes `start`, `build`, and `test` scripts.
  - The build command is `npm run build`, which runs `craco build`.
  - The local frontend dev command is `npm run start`, which runs `craco start`.
- A backend API under `backend/`.
  - `backend/server.py` defines a FastAPI `app`.
  - Routes are mounted under an `APIRouter(prefix="/api")`.
  - CORS behavior is configured in `backend/server.py`.
- Game modules:
  - Target
  - Diceget
  - Flipget
- Tmarget demo prediction market product.
- Platform wallet/ledger routes.
- Internal demo credits.
- Tmarget active runtime storage is currently `InMemoryTmargetRepository`.

Do not infer production readiness from this structure. Several modules are
demo/internal-review oriented.

## 3. Non-Production Warning

> Axwins currently uses internal demo credits. Live deposits, withdrawals, card payments, crypto transfers, Telegram wallet linking, and real-money trading are not enabled.

This deployment plan is for demo/internal review only. It is not a real-money
production launch plan.

- Prediction market/legal/compliance review is required before any real-money
  Tmarget launch.
- Payment, security, and compliance review is required before any deposit,
  withdrawal, card, crypto/Web3, Telegram wallet, or payment feature.
- Do not present the current system as production gambling, payment, custody, or
  real-money prediction-market infrastructure.

## 4. Deployment Goals

Deployment goals for the current demo state:

- Stable demo environment.
- Predictable frontend build.
- Backend API reachable by the frontend.
- Clean route handling for SPA routes and `/api` routes.
- Simple rollback path.
- No accidental generated files in Git.
- No accidental real-money/payment claims.
- No accidental durable-storage claims unless actually implemented and
  verified.

## 5. Deployment Options

### Option A - Local Demo Only

Run the backend and frontend locally.

Pros:

- Lowest operational risk.
- Uses the same local environment used for development checks.
- Avoids public exposure of demo-only admin surfaces.
- Easy to explain as an internal demo.

Cons:

- Not suitable for a remote investor demo unless screen-shared.
- Local machine environment can differ from a future host.
- Requires local backend/frontend processes to stay running.

Risk level: Low.

Best use case: Developer-led screen share, internal review, pre-hosting QA.

Must verify before use:

- Clean Git status.
- Backend compile and regression pass.
- `npm run build` passes.
- Local frontend can reach local backend `/api` routes.
- Manual smoke flow passes.

### Option B - Split Frontend / Backend Hosting

Deploy the frontend to static hosting and the backend to an API hosting service.

Pros:

- Good for basic remote demo deployment.
- Frontend can be cached and served independently.
- Backend can be restarted independently from frontend assets.

Cons:

- Requires CORS and API access review.
- SPA route rewrites must be configured for frontend routes.
- Frontend currently uses relative `/api` calls in inspected pages, so hosting
  topology must preserve or proxy `/api` correctly unless code/config is changed
  in a future pass.
- Tmarget in-memory storage may reset on backend restarts.

Risk level: Medium.

Best use case: Remote demo where a simple public URL is needed and storage reset
is acceptable with clear warning.

Must verify before use:

- Static host rewrites all frontend routes to the frontend entry point.
- `/api` requests reach the backend.
- CORS settings allow the deployed frontend origin.
- Demo admin guard remains demo-only and not presented as production auth.
- Tmarget in-memory reset behavior is disclosed.

### Option C - Single VPS Deployment

Deploy frontend build artifacts and backend API behind one server or reverse
proxy.

Pros:

- More control over routing, headers, logs, and process layout.
- Can serve frontend and backend under the same domain.
- Can preserve relative `/api` calls without frontend code changes if reverse
  proxy routing is configured.

Cons:

- Requires server maintenance.
- Requires process management for backend uptime.
- Requires log rotation, basic host security, and deployment discipline.
- Still does not solve durable Tmarget storage by itself.

Risk level: Medium.

Best use case: Controlled demo environment where one server/domain is preferred.

Must verify before use:

- Backend process restarts cleanly.
- Frontend SPA fallback works.
- Reverse proxy routes `/api` to the backend and frontend paths to static files.
- Logs are visible enough for demo troubleshooting.
- Tmarget in-memory limitations are documented for demo operators.

### Option D - Containerized Deployment Later

Use Docker or another container approach in a future deployment phase.

Pros:

- More repeatable environment.
- Easier to move between hosts once designed.
- Can become a foundation for CI/CD later.

Cons:

- Not recommended to implement in this pass.
- Requires separate design for image builds, env injection, logging, health
  checks, networking, and storage.
- Can create false confidence if durable storage/security are still not solved.

Risk level: Medium until designed, then potentially lower for repeatability.

Best use case: Future hardened demo/staging work after deployment architecture
is agreed.

Must verify before use:

- Explicit container design is reviewed.
- No secrets are baked into images.
- Health checks and logs work.
- Storage limitations are still documented.

## 6. Recommended Path

Recommended staged path:

1. Stage 1: Local demo validation.
   - Run full backend regression and frontend build.
   - Use local/manual smoke flow.
   - Present strictly as internal demo.
2. Stage 2: Simple remote demo environment.
   - Prefer either split frontend/backend hosting with a reliable `/api` proxy,
     or a single VPS with reverse proxy routing.
   - Keep the demo/internal review warning visible.
   - Warn that Tmarget in-memory state may reset.
3. Stage 3: Hardened deployment only after durable storage/auth/security
   planning.
   - Do not present as production.
   - Avoid real-money claims.
   - Add durable storage, real admin roles, security review, monitoring, and
     operational controls before production-like claims.

## 7. Frontend Deployment Considerations

Verified frontend scripts from `frontend/package.json`:

```powershell
npm run build
npm run start
npm run test
```

Frontend route handling must support SPA routes:

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

The inspected frontend code uses relative API paths such as `/api/tmarget` and
`/api/platform/wallet/me`. A deployment must either serve backend routes under
the same origin or proxy `/api` to the backend. Do not invent frontend API env
variables unless they are added intentionally in a future source pass.

After deployment, verify every frontend route directly in the browser, including
deep links such as `/diceget/:tableId`, `/flipget/:tableId`, and
`/tmarget/markets/:slug`.

## 8. Backend Deployment Considerations

`backend/server.py` defines the FastAPI `app` and mounts product routers through
`/api`.

Expected backend route families include:

- `/api/diceget`
- `/api/flipget`
- `/api/platform/wallet/me`
- `/api/platform/ledger/me`
- `/api/tmarget`

Backend deployment considerations:

- Confirm the backend entrypoint used by the host imports `backend/server.py`
  and serves its FastAPI `app`.
- Review CORS settings for the deployed frontend origin.
- Confirm `/api` is reachable from the frontend.
- Keep logs visible for request errors and startup failures.
- Understand restart implications: in-memory Tmarget demo data may reset.
- Run backend tests before deployment.
- Avoid claiming production persistence or production auth until implemented and
  verified.

## 9. Storage / Data Considerations

- Tmarget runtime storage is currently in-memory.
- Demo state may reset after backend restart.
- Tmarget durable storage contract exists.
- Durable repository is not active.
- Mongo/Postgres should not be introduced casually.
- Wallet/ledger persistence must be verified from current backend configuration
  before any remote demo.
- Do not claim durable production storage until it has been implemented,
  configured, tested, and reviewed.

## 10. Environment / Configuration Checklist

Before remote deployment:

- Inspect existing env examples or current local configuration.
- Do not commit secrets.
- Verify frontend `/api` routing or proxy behavior.
- Verify backend allowed origins/CORS.
- Verify backend port and process entrypoint.
- Verify static asset routing and SPA fallback.
- Verify error logging is visible.
- Verify no production payment keys exist or are required.

Environment names are documented in `AXWINS_DEPLOYMENT_PREP.md`; do not invent
secret values in docs or source.

## 11. Pre-Deployment Verification Checklist

Run before any demo deployment:

```powershell
git status --short
git log --oneline -10
python -m py_compile backend/ledger/service.py
python -m py_compile backend/server.py
python -m py_compile backend/diceget/*.py
python -m py_compile backend/flipget/*.py
python -m py_compile backend/tmarget/*.py
python -m py_compile backend/platform_wallet/service.py backend/platform_wallet/router.py
python -m pytest backend/tests/test_wallet_locked_lifecycle.py backend/tests/test_target_wallet_bridge.py backend/tests/test_target_wallet_regression.py backend/tests/test_diceget.py backend/tests/test_flipget.py backend/tests/test_platform_wallet.py backend/tests/test_tmarget.py backend/tests/test_tmarget_repository_admin.py backend/tests/test_tmarget_repository_contract.py
npm run build
```

If default Python lacks `pytest`, use the bundled/project Python that previously
ran backend tests successfully.

## 12. Manual Post-Deployment Smoke Test

After deployment:

- Open Axwins hub.
- Verify Games / Prediction Markets / Platform Core grouping.
- Open Target route/card without modifying Target gameplay.
- Open Diceget lobby/table flow.
- Open Flipget lobby/table flow.
- Open Tmarget markets.
- Open a Tmarget market detail page.
- Open Tmarget portfolio.
- Open Tmarget admin markets.
- Open Wallet.
- Verify wallet is read-only.
- Verify internal demo-credit disclaimer.
- Verify no Deposit, Withdraw, Cash Out, Buy Credits, Connect Wallet, Add Card,
  or Link Telegram Wallet buttons.
- Verify Tmarget is not presented as a game.
- Verify Target is not presented as the platform.

## 13. Rollback Plan

Simple rollback plan:

- Know the last clean commit before deployment.
- Keep the previous build artifact or deployment version if the hosting platform
  supports it.
- Roll back if backend tests fail.
- Roll back if frontend build fails.
- Roll back if a critical route fails.
- Roll back if wording/payment boundaries are broken.

Current clean demo-release reference at the time this plan was created:

- `56d5316 docs: add Axwins deployment preparation guide`

## 14. Deployment Red Flags

Do not proceed if any of these are true:

- Git status is dirty.
- Backend regression fails.
- Frontend build fails.
- Internal demo-credit disclaimer is missing.
- Payment or real-money wording appears enabled.
- Wallet write actions are visible.
- Tmarget is described as a game.
- Target is described as the platform.
- Tmarget durable storage is claimed but not implemented.
- Remote demo depends on in-memory state without a clear warning.
- Secrets are committed.

## 15. Future Hardening Work

Future work only:

- CI pipeline
- Docker/container plan
- Durable repository implementation plan
- Production admin roles
- Auth/session hardening
- Monitoring/logging
- Rate limiting
- Error tracking
- Backup/restore planning
- Security review
- Payment/compliance review if real money is ever considered
- Tmarget oracle/dispute/legal review if ever considered for real markets
