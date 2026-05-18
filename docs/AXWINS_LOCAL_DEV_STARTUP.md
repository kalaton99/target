# Axwins Local Dev Startup

## Purpose

This guide gives a repeatable Windows PowerShell startup flow for local Axwins
development. It is documentation only: it does not change backend behavior,
frontend routing, gameplay rules, storage, wallet behavior, or deployment
configuration.

## Product Boundaries

- Axwins is the platform shell.
- Target, Diceget, and Flipget are games inside Axwins.
- Tmarget is a separate demo prediction market product, not a game.
- Wallet, Ledger, Transaction History, and Internal Demo Credits are shared
  Axwins platform core services.
- Local MongoDB is expected to run as the Windows service named `MongoDB`.

Axwins currently uses internal demo credits only. Deposits, withdrawals,
cash-out, crypto, card payments, and real-money trading are not enabled.

## 1. Check MongoDB

From PowerShell:

```powershell
Get-Service MongoDB
Test-NetConnection 127.0.0.1 -Port 27017
```

If the service is already `Running`, `Start-Service MongoDB` is unnecessary.
Only start it if the service is installed but stopped:

```powershell
Start-Service MongoDB
```

## 2. Start Backend

Open a PowerShell window from the repository root:

```powershell
cd "C:\Users\crims\OneDrive\Belgeler\New project\target"
.\backend\.venv\Scripts\Activate.ps1

$env:MONGO_URL="mongodb://127.0.0.1:27017"
$env:DB_NAME="axwins_local"
$env:JWT_SECRET="dev-local-jwt-secret-change-later"
$env:RNG_ENCRYPTION_KEY="dev-local-rng-secret-change-later"
$env:CORS_ORIGINS="http://localhost:3000,http://127.0.0.1:3000"
$env:ALLOW_GUEST_AUTH="1"
$env:TARGET_ALLOW_BOTS="1"
$env:TARGET_BOT_COUNT_MAX="2"
$env:TMARGET_DEMO_ADMIN_ENABLED="1"

python -m uvicorn backend.server:app --host 127.0.0.1 --port 8000 --reload
```

Wait until the terminal shows that application startup is complete before
checking health.

In a second PowerShell window:

```powershell
curl.exe http://127.0.0.1:8000/api/health
```

Use `curl.exe` explicitly. In PowerShell, `curl` may resolve to
`Invoke-WebRequest`, which formats output differently.

## 3. Start Frontend

Open another PowerShell window:

```powershell
cd "C:\Users\crims\OneDrive\Belgeler\New project\target\frontend"
$env:REACT_APP_BACKEND_URL="http://127.0.0.1:8000"
npm start
```

The frontend should open at:

```text
http://localhost:3000
```

## 4. Local Smoke Checks

After both servers are running:

- Open `http://localhost:3000`.
- Confirm the Axwins hub loads.
- Open `/games`.
- Open `/lobby` and sign in with a local demo name.
- Confirm the lobby auth request goes to
  `http://127.0.0.1:8000/api/v2/lobby/auth`.
- Open `/diceget`, `/flipget`, `/tmarget`, and `/wallet`.
- Confirm pages render without a blank screen or React crash.

## 5. Build Command

Run the frontend build from the `frontend` folder, not the repository root:

```powershell
cd "C:\Users\crims\OneDrive\Belgeler\New project\target\frontend"
npm run build
```

## Troubleshooting

### MongoDB

If `Test-NetConnection 127.0.0.1 -Port 27017` fails:

- Confirm the `MongoDB` service exists.
- Start it only if it is stopped.
- Re-run the port check before starting the backend.

### Backend Health

If `/api/health` fails:

- Confirm the backend terminal reached application startup complete.
- Confirm the backend is listening on `127.0.0.1:8000`.
- Confirm `MONGO_URL` and `DB_NAME` were set in the same PowerShell session
  that launched Uvicorn.

### Frontend API Calls

If `/api/health` works but the frontend cannot reach the backend:

- Confirm the frontend was started with:

```powershell
$env:REACT_APP_BACKEND_URL="http://127.0.0.1:8000"
```

- Restart `npm start` after changing the env var.
- Use the browser Network tab to confirm API calls go to
  `127.0.0.1:8000`, not `localhost:3000`.

### Lobby Auth

If lobby sign-in fails:

- Check the browser Network tab for `/api/v2/lobby/auth`.
- The request should be sent to:

```text
http://127.0.0.1:8000/api/v2/lobby/auth
```

- If it goes to `http://localhost:3000/api/v2/lobby/auth`, restart the
  frontend with `REACT_APP_BACKEND_URL` set.

### Target Quick Play

The `/play` quick bot flow depends on local dev bots. For this local guide,
`TARGET_ALLOW_BOTS=1` and `TARGET_BOT_COUNT_MAX=2` enable that demo path.
Do not use bot settings to imply production gameplay or real-money behavior.

## Non-Goals

This guide does not:

- Add payment, crypto, deposit, withdrawal, cash-out, or real-money features.
- Add Postgres runtime activation, SQL, migrations, or durable storage.
- Add or change backend API behavior.
- Change Target, Diceget, Flipget, or Tmarget business behavior.
