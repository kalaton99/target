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
- ✅ Phase 1 — Shared constants/types (rewritten 2026-02 for TARGET v2)
- ✅ Phase 2 — Pure game engine (rewritten 2026-02 for TARGET v2; 31 tests in `test_engine_target.py`)
- ✅ Phase 3 — Turn engine + 15s `AUTO_STAND_TIMEOUT` (DRAW phase only)
- ✅ Phase 4 — Append-only event log + replay (writer unchanged; event-log test fixtures need update for new phase order — backlog)
- ✅ Phase 5 — Wallet/ledger durable WAL state machine [17 tests]
- ✅ Phase 6 — Realtime WebSocket (gateway + bridge + dev UI)
- ✅ TARGET v2 engine alignment (2026-02)
   • Dynamic target: 30 / 50 / 100 / 250 (from table config)
   • New phase order: ANTE → BETTING_R1 → DEAL_INITIAL → DRAW → SHOWDOWN → PAYOUT
   • Initial deal: 1 card per player (NOT 2)
   • 51% rule: ceil(0.51*X) call requirement on raises; max raise capped by lowest active wallet
   • Stand-threshold lookup `{2:1, 3:2, 4:3, 5:3, 6:4, 7:4, 8:5}` + immediate showdown when all stood/busted/DQ/folded
   • Special card 2 (Hearts/Clubs): manual transfer (PLAY_TWO) + auto bust-save (sends highest non-2 to opponent)
   • Special card 10 (Hearts/Clubs): forced attack (PLAY_TEN) — sends chosen card to active opponent; 10 discarded
   • Joker → instant DQ
   • Scoring: 2-9 face value, 10=10, J=7, Q=8, K=9, Ace 1/11 adaptive
   • All "21" branding removed from engine; legacy `TARGET_SCORE=21` shim retained for legacy modules
- ✅ TARGET v2 UI alignment (2026-02 — `PlayPage.jsx`)
   • Removed "21" branding; shows dynamic `TARGET 30` pill
   • Added BETTING_R1 controls: CHECK / CALL (with owed amount) / FOLD
   • HIT/STAND only enabled in DRAW phase
   • Shows 1-card initial deal, opponent face-down + card_count
   • Live verified: BETTING_R1 → CHECK → DEAL_INITIAL → DRAW → STAND → PAYOUT
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
   • Live verified at `https://gracious-raman-3.preview.emergentagent.com/api/v2/realtime/health`
- ⬜ Phase 7  — Telegram link/notify boundary
- ⬜ Phase 8  — Web3 deposit/withdraw boundary
- ⬜ Phase 9  — Reward points ledger
- ⬜ Phase 10 — Future token claim boundary
- ⬜ Phase 11 — Minimal UI (auth, menu, table, bet panel, timer)
- ✅ Phase 11 P2 — Real lobby + multi-user (2026-02 — `lobby/`)
   • `backend/lobby/service.py` — Mongo-backed table CRUD + lightweight guest auth (username only)
   • `backend/lobby/router.py` — `/api/v2/lobby/*` endpoints: `auth`, `me`, `tables`, `tables/{id}/{join,leave,start}`
   • Engine spawn on START: real seats from lobby; if creator is alone, 1 bot is added as fallback so 2-player game runs; bot driver auto-CHECKs in BETTING_R1 and STANDs in DRAW
   • `frontend/src/pages/LobbyPage.jsx` — login, create-table form (target 30/50/100/250, stake, min/max), live-refreshing table list, JOIN/ENTER/START controls
   • `frontend/src/pages/PlayPage.jsx` — dual-mode: `/play` (dev solo via spawn_solo_table) and `/play/:tableId` (lobby mode using persisted token from localStorage)
   • App routes: `/` → `/lobby`, `/play`, `/play/:tableId`
   • 17/17 lobby tests pass against live backend including: 2 real users connect via WS to the same table and both receive `STATE_UPDATE` (`target_score=30`, 2 humans, no bot) + their own `PRIVATE_STATE`; solo START spawns bot fallback with bot user_id starting `u_bot_*`
- ✅ Phase 11 MVP — Browser-playable React `/play` (2026-02 — `frontend/src/pages/PlayPage.jsx`)
   • Landing screen with noir PLAY button; legacy routes untouched
   • Click PLAY → spawn_solo_table → WS connect → render WELCOME, STATE_UPDATE,
     PRIVATE_STATE, ACTION_ACK, OUT_OF_SYNC, PING/PONG
   • Shows own face-up cards, opponent face-down + card_count only, phase pill,
     pot, state_version, WS state, current-turn highlight, countdown timer,
     HIT/STAND buttons (enabled only on own turn in DRAW), "Deal again" after PAYOUT
   • Live verified: `/play` → PLAY → A♠Q♦ score 19 soft → STAND → bot auto-STAND
     → DRAW→BETTING → state_version 1→3
   • Live URL: `https://gracious-raman-3.preview.emergentagent.com/play`
- ⬜ Phase 12 — E2E hardening via testing_agent_v3_fork

## Test totals: 139 passed / 2 skipped (incl. 17 live-backend lobby tests, 2026-02)

Test breakdown:
  - test_engine_target.py (31)
  - test_event_log_phase4.py (11 passed, 1 skipped)
  - test_ledger_phase5.py (17)
  - test_realtime_phase6.py (31)
  - test_realtime_phase6_wiring.py (11)
  - test_realtime_phase6_bridge.py (13)
  - test_realtime_phase6_private.py (6)
  - test_realtime_phase6_dev_ui.py (2 passed, 1 skipped — TestClient WS / async bot loop incompatibility; full play loop covered by gateway E2E and live browser screenshots)

## Legacy directories (out-of-scope, untouched per user directive)
`auth/`, `realtime/`, `tables/`, `wallet/` — leftovers from earlier overshoot.
Will be refactored or removed during Phase 11 (UI wiring). Phase 6 deliberately
lives in `realtime_v2/` to keep the legacy untouched.

## Audit / static-analysis policy
External code-quality audits are governed by [`AUDIT_POLICY.md`](./AUDIT_POLICY.md):
- Legacy dirs above are excluded from quality scans.
- Test fixture identifiers (`token="tok-alice"` etc.) are not credentials.
- `is None` / `is not None` are PEP-8 correct and must not be rewritten.
- Hook-dep findings are validated against current source via ESLint, not stale line numbers.
- Big-refactor flags on `reducer.reduce()`, `ledger.mutate()`, `PlayPage`, `LobbyPage`
  are formally deferred — see policy doc for triggers.
- localStorage auth storage is accepted MVP risk; rationale in [`THREAT_MODEL.md`](./THREAT_MODEL.md).

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

## 2026-02 — UX fixes batch 2 verified
- Defensive null-card filtering added to `PlayPage.jsx` (PRIVATE_STATE
  intake + `me.cards.map` render) so a malformed PRIVATE_STATE payload
  cannot crash the card key expression `${c.rank}-${c.suit}-${i}`.
- E2E re-verified on `/play`: BETTING_R1 → CHECK → DRAW (A♠ rendered,
  score 11 soft) → STAND → PAYOUT.
- Winner banner shows `username` (`You_xxxxxx`), not `user_id`.
- Payout delta `data-testid="my-net-delta"` shows `You won +50` in green.
- LobbyPage CREATE TABLE form (target select + numeric inputs) loads
  with no React hydration warnings in the console.
- AUTO_STAND_TIMEOUT notice path lives in `PlayPage.jsx` STATE_UPDATE
  handler (events[].type==="STAND" && auto), surfaces a transient
  amber banner with `data-testid="event-notice"` for 4s.
- Canonical pytest suite: 149 passed / 2 skipped (legacy
  `test_websocket.py` and `test_rest.py` are excluded per
  `AUDIT_POLICY.md`; their 3 pre-existing failures hit the legacy
  `/api/ws/*` route, not `/api/v2/*`).

## 2026-02 — Phase 11 P1 special-card UI (PLAY_TWO / PLAY_TEN)
- Added `PLAY_TWO` and `PLAY_TEN` to `realtime_v2/protocol.py::CLIENT_ACTIONS`
  whitelist so the gateway forwards them to the engine. Engine handlers
  already existed in `game_engine/reducer.py` (no engine change).
- New test `test_play_two_and_play_ten_are_accepted_by_gateway` in
  `tests/test_realtime_phase6.py` — verifies both intents reach the action
  handler with their structured payload (`target_user_id` + `transfer_card_index`
  / `attack_card_index`). Suite total: **149 passed / 2 skipped**.
- `frontend/src/pages/PlayPage.jsx`:
  - `isDefenseTwo` / `isAttackTen` helpers (mirrors `core/constants.py`).
  - Conditional `PLAY 2` (`data-testid="play-two-btn"`) and `PLAY 10`
    (`data-testid="play-ten-btn"`) buttons — render only in DRAW + my
    turn + I hold the trigger card; disabled when no active opponents or
    only the trigger card in hand.
  - Inline picker dialog (`data-testid="special-picker-two"`/`-ten`) with
    target selector (`picker-target-{seat}`), card-to-send selector
    (`picker-card-{idx}`, trigger card filtered out), Confirm/Cancel.
  - `sendSpecial(action, payload)` callback dispatches WS intent with
    structured payload — separate from existing `send()`.
  - STATE_UPDATE handler surfaces `PLAY_TWO`/`PLAY_TEN` events in the
    event log and as a transient amber banner.
- E2E verified live: HIT loop surfaced a 10♥, `PLAY 10` button appeared,
  picker opened with default target = bot and card list `A♠, 3♦, A♦`
  (10♥ correctly excluded), Confirm → engine accepted, banner read
  `"You_c73b77 attacked with (10) → Bot_c73b77: AS"`, bot's hand grew
  to 2 cards, phase advanced to PAYOUT, winner + delta still rendered.
  No console errors. HIT/STAND/CHECK/CALL/FOLD regression: clean.

## 2026-02 — Phase 11 P1 reconnect-grace timer
- `realtime_v2/bridge.py`: added `notify_connect`/`notify_disconnect`
  presence hooks on `EngineBridge`. Default grace = 25s, clamped to
  [20, 30] per PRD. On disconnect: `player.connected=False` + start
  cancellable expiry task; on reconnect: cancel task + restore flag;
  on expiry: `player.sitting_out=True`. Engine state-machine
  untouched — `STATE_UPDATE` carries synthetic `PRESENCE` /
  `PRESENCE_GRACE_EXPIRED` events for clients to render.
- `realtime_v2/gateway.py`: optional `on_connect` / `on_disconnect`
  hooks; called after WELCOME / in cleanup `finally`. Errors logged,
  never raised — no impact on existing lifecycle.
- `realtime_v2/asgi.py` + `server.py`: hooks bound to
  `EngineBridge.notify_connect` / `notify_disconnect`.
- `frontend/src/pages/PlayPage.jsx`: opponent panels show
  `RECONNECTING…` or `SITTING OUT` pill (`data-testid="opponent-{seat}-presence"`).
  STATE_UPDATE handler logs `PRESENCE` / `PRESENCE_GRACE_EXPIRED` to
  the event log + transient banner (skipped for self).
- New test file `tests/test_reconnect_grace_phase11_p1.py` (13 tests):
  grace clamp, disconnect/reconnect/expiry lifecycle, engine
  non-interference (AUTO_STAND_TIMEOUT still fires on disconnected
  current-turn seat at the engine's own 15s budget), unregister
  cancels in-flight tasks, safe-no-op for unknown table/user, double
  disconnect idempotent. Suite total: **162 passed / 2 skipped**.
- E2E verified live (`/tmp/e2e_reconnect.py`, 2 real users on a lobby
  table): A disconnects → B receives `PRESENCE(connected=False)` for
  A's seat, A's row reflects `connected=False sitting_out=False`.
  A reconnects 2s later → B receives `PRESENCE(connected=True)`,
  A's row back to `connected=True sitting_out=False`. Solo gameplay
  regression smoke clean.

## Next Action Items
1. P0: Multi-round betting (FLOP / TURN / RIVER analog).
2. ✅ P0: Special-card UI/intent for PLAY_TWO / PLAY_TEN — **DONE 2026-02**.
3. P0: Portrait/mobile layout.
4. P0: Replay client_seed contribution to RNG.
5. ✅ P0: Reconnect grace timer (20–30s) with sitting_out flag — **DONE 2026-02**.
# P2 (per architecture v3.2)
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
