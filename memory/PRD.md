# TARGET — Premium Card Game

## Original Problem Statement
Build a production-ready, real-money-capable multiplayer card game called **TARGET**: 2–8 players, controlled card drawing (Blackjack-like score ≤ 21 target), poker-like betting, special cards (2 = strategic, 10 = attack, Joker = DQ), commission, lottery accumulator. Server-authoritative, deterministic, integer-only money, anti-fraud.

Architecture went through 5 review rounds (v1 → v3.2) with strict requirements:
- PostgreSQL → adapted to MongoDB (per platform constraint, Option A)
- Redis → adapted to in-process state + pub-sub
- Hybrid optimistic+pessimistic wallet versioning
- state_version on every client intent (OUT_OF_SYNC enforced)
- Append-only `hand_actions` event log = source of truth
- Double-entry ledger (`transactions`)
- Idempotency keys (DB-unique)
- Provably-fair RNG (commit-reveal SHA256)
- Engine versioning per-hand
- 15-second turn timer → AUTO_STAND_TIMEOUT (NEVER fold)
- Telegram / Web3 / Rewards / Claims / Compliance — boundaries defined, deferred

## User Personas
- Casual high-stakes player wanting fast, premium card game
- Streamer/competitive player wanting skill expression via betting + special cards
- Future: real-money player (deferred)

## Core Requirements (frozen)
- 2–8 players per single table
- Phases: ANTE → DEAL → DRAW → BETTING → SHOWDOWN → PAYOUT → ENDED → loop
- Card values: 2–9=face, J=7, Q=8, K=9, A=1|11, Joker=DQ
- Server-authoritative (no client trust, no float math)
- Premium cinematic noir UI (obsidian + gold + cyan + red)
- 15s turn → AUTO_STAND_TIMEOUT (auto-stand only, never fold)

## Architecture v3.2 (Option A — MongoDB)
- **Backend**: FastAPI single instance, port 8001, /api prefix
- **Database**: MongoDB (single source of truth)
- **Realtime**: Native WebSocket at /api/ws/table/{id}?token=jwt
- **Auth**: JWT email/password (Google OAuth deferred)
- **State**: in-memory per-table TableWorker + serial FIFO intent queue
- **Persistence**: every action → MongoDB before broadcast

## Phase Progress (strict, sequential)
- ✅ Phase 1 — Shared constants/types
- ✅ Phase 2 — Pure game engine (deck, shuffle, draw, score, hit, stand) [33 tests]
- ✅ Phase 3 — Turn engine + 15s `AUTO_STAND_TIMEOUT` [8 tests]
- ✅ Phase 4 — Append-only event log + replay [12 tests]
- ✅ Phase 5 — Wallet/ledger durable WAL state machine [17 tests]
- ✅ Phase 6 — Realtime WebSocket layer [31 tests] (2026-02 — `realtime_v2/`)
   • Gatekeeper: per-user + per-IP caps (atomic acquire/release)
   • PubSub: topic broadcast with bounded queues + slow-consumer drop policy
   • Gateway: JWT/session bind, WELCOME w/ state_version, server-only rejection,
     state_version OUT_OF_SYNC, ping/pong heartbeat, disconnect cleanup
   • Transport-agnostic (FastAPI WS or test fakes)
- ✅ Phase 6 — FastAPI wiring [11 tests] (2026-02 — `realtime_v2/asgi.py`)
   • `build_v2_router()` mounts `/api/v2/ws/table/{id}?token=<jwt>` + `/api/v2/realtime/health`
   • Wired into `server.py` additively (legacy `/api/ws/table/{id}` untouched)
   • Real JWT decoding via existing `core.security.decode_token` (no new auth code)
   • Engine integration is stubbed: state_version=0, action_handler returns
     `{accepted: false, reason: "ENGINE_NOT_WIRED"}`
   • Live verified at `https://target-poker.preview.emergentagent.com/api/v2/realtime/health`
- ⬜ Phase 7  — Telegram link/notify boundary
- ⬜ Phase 8  — Web3 deposit/withdraw boundary
- ⬜ Phase 9  — Reward points ledger
- ⬜ Phase 10 — Future token claim boundary
- ⬜ Phase 11 — Minimal UI (auth, menu, table, bet panel, timer)
- ⬜ Phase 12 — E2E hardening via testing_agent_v3_fork

## Test totals: 112/112 passing (Phases 2–6 + wiring)

## Legacy directories (out-of-scope, untouched per user directive)
`auth/`, `realtime/`, `tables/`, `wallet/` — leftovers from earlier overshoot.
Will be refactored or removed during Phase 11 (UI wiring). Phase 6 deliberately
lives in `realtime_v2/` to keep the legacy untouched.

## What's Been Implemented (legacy notes — pre-strict-phase build)

### Backend
- ✅ Auth (JWT register/login/me) — bcrypt + pyjwt
- ✅ Wallet with hybrid versioning (optimistic version + atomic balance check + retry)
- ✅ Double-entry ledger (transactions: USER + counter row, journal_id ties pair)
- ✅ Idempotency keys (DB-unique via Mongo unique index)
- ✅ Tables CRUD + quick-join + join/leave (atomic seat claim with array filter)
- ✅ Game engine (pure reducer, deck, scoring with Ace/Joker, provably-fair shuffle)
- ✅ TableWorker per active table with FIFO intent queue, AUTO_STAND_TIMEOUT scheduler, auto-restart hand loop
- ✅ WebSocket gateway with: JWT bind, per-user conn cap (2), state_version validation, OUT_OF_SYNC reject + fresh_state, 4KB msg cap, ping/pong, server-only action guard
- ✅ hand_actions append-only event log with seq counter (replay-able)
- ✅ rng_seeds commit-reveal (committed at start, revealed at payout)

### Frontend (Bebas Neue + Cinzel + Rajdhani — distinctive noir display)
- ✅ Auth pages (login + register) — gold-accent panels, Sample-8 logo
- ✅ Main menu — central PLAY/MULTIPLAYER/TOURNAMENT/COLLECTION stack, top balance badges
- ✅ Tables list + create + quick-join
- ✅ Game table — landscape: opponents row, central pot ring + draw deck + discard, local player at bottom with fanned hand
- ✅ Betting panel — FOLD/CALL/CHECK/BET-RAISE buttons, slider with MIN/x2/1-2POT/MAX, HIT/STAND for DRAW phase
- ✅ Turn timer countdown bar (visual only — backend authoritative)
- ✅ Action callouts (RAISE!/STAND/etc floating)
- ✅ data-testid on every interactive element

## Verified end-to-end flows
- Register → wallet credited 10,000 signup bonus
- Login → token returned
- Quick-join → table created and seat assigned atomically
- Two players connect via WS → ANTE collected → DEAL 2 cards each → DRAW phase rotation → STAND → BETTING → CHECK both → SHOWDOWN → PAYOUT → next hand auto-starts
- state_version OUT_OF_SYNC correctly rejected when stale

## Prioritized backlog (P0 / P1 / P2)

### P0 (next iteration after first user feedback)
- Multi-round betting (FLOP / TURN / RIVER analog) — currently single round
- Special card mechanics (2-PROTECT, 10-ATTACK action handlers)
- Portrait/mobile layout (currently landscape only)
- Replay client_seed contribution to RNG (currently empty client_seeds)
- Reconnect grace timer (20–30s) with sitting_out flag

### P1
- Google OAuth (Emergent-managed)
- Lobby with ready system + match settings (per visual reference Sample 9)
- Avatar uploads / character portraits
- Sound effects + chip-trail animations on bet/raise
- Lottery pool persistence (commission split is computed; pool not yet stored)

### P2 (per architecture v3.2)
- Telegram linking + notifications + wallet bridge
- Web3 deposit / withdrawal pipeline
- Reward points ledger + granter
- Token claim boundary (compliance-gated, disabled by default)
- Compliance flags + admin kill switch
- Anti-collusion logging
- Worker heartbeat + supervisor (single-instance MVP — not strictly needed yet)

## Next Action Items
1. Run testing_agent_v3 to validate full backend + frontend e2e
2. Address any P0 issues uncovered
3. Iterate on UI polish per actual gameplay feel
