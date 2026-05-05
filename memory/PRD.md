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
- **Table sizes are locked by target tier** (2026-05 v2 rule update — see
  [`GAME_RULES_LOCKED.md`](./GAME_RULES_LOCKED.md) for the single source of truth):
  - Target 30  → **4 seats**
  - Target 50  → **4 seats**
  - Target 75  → **5 seats**
  - Target 100 → **5 seats**
  - Target **250 has been removed** (deprecated in 2026-05 v2; replaced by 75).
- Legacy `MAX_PLAYERS=8` / 6–8 seat assumptions are **deprecated**. Code
  must be migrated to the per-target caps above before the next real-money
  build.
- Phases: ANTE → DEAL → DRAW → BETTING → SHOWDOWN → PAYOUT → ENDED → loop
- Card values: 2–9=face, J=7, Q=8, K=9, A=1|11, Joker=DQ
- Server-authoritative (no client trust, no float math)
- Premium cinematic noir UI (obsidian + gold + cyan + red)
- 15s turn → AUTO_STAND_TIMEOUT (auto-stand only, never fold)
- CPU/bot players are a **dev/testing affordance only** (0–3 per table,
  via a config flag); production multiplayer must be all-human. See
  `GAME_RULES_LOCKED.md §5` for the config contract.

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
   • Dynamic target: 30 / 50 / 75 / 100 (from table config; 250 removed 2026-05 v2)
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
   • `frontend/src/pages/LobbyPage.jsx` — login, create-table form (target 30/50/75/100, stake, min/max), live-refreshing table list, JOIN/ENTER/START controls
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

## 2026-05 — Locked game rules (documentation-only, no code change)
- Added [`GAME_RULES_LOCKED.md`](./GAME_RULES_LOCKED.md) — authoritative
  rule doc overriding older drafts.
- **Table sizes now locked per target tier**: target 30/50 → 4 seats;
  target 100/250 → 5 seats. Legacy `MAX_PLAYERS=8` and 6/7/8-seat paths
  are deprecated pending a migration (see `GAME_RULES_LOCKED.md §7`).
- **Stand-threshold for 5 active players confirmed at 3** — matches
  existing `STAND_THRESHOLD[5]`. No constant change needed.
- **CPU/bot players are dev-only**: 0–3 per table, gated by
  `TARGET_ALLOW_BOTS` + `TARGET_BOT_COUNT_MAX` env vars. Production
  default: 0 bots. Current "auto-spawn one bot if creator is alone"
  behaviour is marked as Phase-11 MVP shortcut to be moved behind the
  dev flag during migration.
- No game code changed in this step — the rules doc is the migration
  source-of-truth; implementation is sequenced in the section below.

## Pending migration (from GAME_RULES_LOCKED.md §7)
Must ship **before** multi-round betting implementation so later work
happens against the real table shape:

1. **Per-target seat cap**: `backend/core/constants.py` (new
   `TABLE_SEATS_BY_TARGET`), `backend/lobby/router.py` +
   `backend/lobby/service.py` (derive seats from target, ignore
   client-supplied `max_players`/`min_players`),
   `frontend/src/pages/LobbyPage.jsx` (drop Min/Max inputs).
2. **Deprecate 6–8 seat code**: trim `MAX_PLAYERS` to 5 and
   `STAND_THRESHOLD` to `{2:1, 3:2, 4:3, 5:3}` (runtime still keys on
   active-in-DRAW, so `3` stays for mid-hand fold cases). Tighten
   Pydantic validators from `le=8` to `le=5`.
3. **Bots configurable & dev-only**: add `TARGET_ALLOW_BOTS` +
   `TARGET_BOT_COUNT_MAX` env vars, add `bot_count` to
   `CreateTableRequest`, move the auto-bot fallback behind
   `ALLOW_BOTS`, guard `realtime_v2/dev_router.spawn_solo_table`,
   surface the control in `LobbyPage.jsx` only when the backend
   advertises `allow_bots=true`.
4. **Test-fixture updates**: lobby tests that rely on the auto-bot
   fallback must pass `bot_count=1` or set `TARGET_ALLOW_BOTS=1` via
   `monkeypatch`.

## 2026-05 — Locked-rules migration shipped
- `backend/core/constants.py`:
  - Added `TABLE_SEATS_BY_TARGET = {30: 4, 50: 4, 100: 5, 250: 5}` and
    `seats_for_target()` helper.
  - `MAX_PLAYERS: 8 → 5`. `STAND_THRESHOLD` trimmed to `{2:1, 3:2, 4:3, 5:3}`.
  - Env-driven bot config: `ALLOW_BOTS` (default off) and `BOT_COUNT_MAX`
    (clamped to `[0, 3]`). Module loads `.env` at import time so
    constants resolve regardless of import order.
- `backend/lobby/service.py::create_table`: ignores client-supplied
  `max_players`/`min_players` (kept as optional kwargs for back-compat,
  silently dropped); derives `max_players` from `target_score`. New
  `bot_count` field stored on the table doc and surfaced through
  `_public_table`.
- `backend/lobby/router.py`:
  - `CreateTableRequest`: `max_players`/`min_players` are
    `Optional[int]` (server-ignored). New `bot_count: int = Field(0,
    ge=0, le=3)`.
  - `POST /v2/lobby/tables` rejects `bot_count > 0` when
    `ALLOW_BOTS=False` (`400 BOTS_DISABLED`) or `> BOT_COUNT_MAX`
    (`400 BOT_COUNT_EXCEEDED`).
  - New `GET /v2/lobby/config` exposes `{allow_bots, bot_count_max,
    table_seats_by_target}` for frontend feature-gating.
  - `_spawn_engine_for_table` rewritten — legacy "auto-spawn 1 bot if
    creator alone" is gone. Bots are seated only when `ALLOW_BOTS=True`
    and `bot_count > 0`, clamped by `BOT_COUNT_MAX` and free seats.
- `backend/realtime_v2/dev_router.py`:
  - `/v2/dev/spawn_solo_table` returns `404 BOTS_DISABLED` when
    `ALLOW_BOTS=False`.
  - `_BotDriver` strategy upgraded to actually exercise HIT: DRAW
    HITs while score < 60% of target, else STANDs.
- `backend/.env`: added `TARGET_ALLOW_BOTS=1` + `TARGET_BOT_COUNT_MAX=3`
  for the dev/preview environment. **Production deploys must omit these
  or set `TARGET_ALLOW_BOTS=0`.**
- `frontend/src/pages/LobbyPage.jsx`:
  - Removed `minp-input` / `maxp-input` from the create-table form.
  - Added read-only `seats-derived` widget.
  - Added optional `bot-count-input` (rendered only when `/config`
    advertises `allow_bots=true`).
- `backend/tests/test_lobby_phase11_p2.py`: 8 new tests covering
  `/config`, per-target seat-cap derivation, legacy `max_players`
  ignored, bot-count gating, and the removed auto-bot fallback.

**Tests**: canonical pytest suite **170 passed / 2 skipped** (was
162; +8 new). ESLint on `LobbyPage.jsx`: clean. Ruff on backend: clean.

**E2E smoke (live preview)**:
- `/lobby`: target-30 → "4 seats", target-100 → "5 seats",
  `bot-count-input` visible (dev), old min/max gone, created table
  shows `1/4 seated`; full 4/4 table reachable.
- `/play` regression: BETTING_R1 → CHECK → DRAW → STAND → PAYOUT,
  winner + delta render, no console errors.

## 2026-05 — Multi-round betting (interactive HIT/STAND in DRAW_1/DRAW_2)
- New canonical flow: **BETTING_R1 → DEAL_INITIAL → DRAW_1 →
  BETTING_R2 → DRAW_2 → BETTING_R3 → SHOWDOWN → PAYOUT**.
- DRAW_1 and DRAW_2 are **interactive** HIT/STAND/PLAY_TWO/PLAY_TEN
  phases (Option B per user directive). Stand-threshold rule still
  ends each draw round; routing now goes to BETTING_R2 / BETTING_R3
  / SHOWDOWN by phase instead of always SHOWDOWN.
- STAND is **sticky across rounds** — a player who stood in DRAW_1
  cannot HIT in DRAW_2 but can still bet in BETTING_R2/R3.
- `core/constants.py::PHASES`: added DRAW_1 / BETTING_R2 / DRAW_2 /
  BETTING_R3. Legacy DRAW kept reachable for tests.
- `game_engine/types.py::GameState`: added `betting_round: int = 0`
  (1/2/3 in betting; 0 in draw / payout).
- `game_engine/reducer.py`: extension-only changes.
  - New `_enter_betting_round(round_n)` helper (resets call/raise/
    responded for R2/R3, mirrors R1 setup).
  - New `_enter_draw_round(draw_n)` helper (interactive entry,
    recomputes `draw_active_count`, opens turn for first eligible
    drawer; auto-advances if no drawers remain).
  - New `_end_draw_round()` helper called from `_maybe_end_draw`
    instead of `_enter_showdown`. Routes DRAW_1 → BETTING_R2,
    DRAW_2 → BETTING_R3, legacy DRAW → SHOWDOWN.
  - `_end_betting_to_deal` rewritten to dispatch by `state.phase`:
    R1 → DEAL_INITIAL → DRAW_1; R2 → DRAW_2; R3 → SHOWDOWN.
  - HIT/STAND/PLAY_TWO/PLAY_TEN/AUTO_STAND_TIMEOUT phase gate
    extended from `phase == "DRAW"` to `phase in ("DRAW", "DRAW_1",
    "DRAW_2")`.
  - BETTING phase gate extended from `phase == "BETTING_R1"` to
    `phase in ("BETTING_R1", "BETTING_R2", "BETTING_R3")`.
  - `_attempt_bust_save` and `reduce()` dispatch logic untouched.
- `game_engine/turn_engine.py`: `_maybe_arm_timeout` and the timer
  stale-fire guard accept all three draw phases. AUTO_STAND_TIMEOUT
  now fires correctly in DRAW_1/DRAW_2.
- `realtime_v2/bridge.py`: STATE_UPDATE broadcast carries the new
  `betting_round` field so clients can render "Round 2 / 3" badges.
- `realtime_v2/dev_router.py`: `_BotDriver` extended to all three
  betting rounds and all three draw phases (DRAW_1/DRAW_2 use the
  same "HIT below 60% of target, else STAND" strategy as legacy DRAW).
- `frontend/src/pages/PlayPage.jsx`: `myTurn` accepts DRAW_1/DRAW_2;
  `myBettingTurn` accepts BETTING_R2/R3. Phase pill (`phase-pill`)
  renders the new phase strings verbatim — no other UI work needed.
- New test file `tests/test_multi_round_betting_phase11.py` (10 tests):
  full R1→D1→R2→D2→R3 flow, phase-event ordering, sticky-stand
  reachability, 4-player flow with R2 fold, fold-to-one short-circuit,
  total_contributed accumulation across rounds, phase guards
  (HIT in BETTING_R2 rejected, CHECK in DRAW_2 rejected, FOLD accepted
  in DRAW_2).
- Updated tests: `test_engine_target.py` (3 phase strings, helper
  `all_check_through_betting` extended to all rounds, stand-threshold
  tests rewritten for round transitions); `test_realtime_phase6_bridge.py`
  (`_start_hand` helper + broadcast envelope phase set);
  `test_realtime_phase6_private.py` (`_start_hand` helper);
  `test_reconnect_grace_phase11_p1.py` (assertion).
- Suite total: **180 passed / 2 skipped** (was 170; +10 net new).
- E2E live (`/play` solo + bot): full canonical flow walked through —
  BETTING_R1 → DRAW_1 (STAND) → BETTING_R2 → BETTING_R3 → PAYOUT.
  Bot exercised HIT path in DRAW_2 (ended on 3 cards, score 22 SOFT).
  Winner banner + delta render, no console errors, WS stable.

## 2026-05 — Per-target bot cap (5-seat tables support 4 bots)
- `backend/core/constants.py`: `BOT_COUNT_MAX` default **3 → 4**
  (global hard ceiling; the largest locked seat table is 5). New helper
  `max_bots_for_target(target_score)` returns `seats - 1`, clamped by
  `BOT_COUNT_MAX`.
- `backend/lobby/router.py`:
  - `CreateTableRequest.bot_count`: Pydantic ceiling `le=3 → le=4`.
  - Create-table route validates `bot_count` against the per-target
    cap (400 `BOT_COUNT_EXCEEDED`, detail includes `bot_count_max`).
  - `GET /v2/lobby/config` now returns
    `bot_count_max_by_target: {30:3, 50:3, 100:4, 250:4}`
    (all zeros when `allow_bots=false`).
- `backend/.env`: `TARGET_BOT_COUNT_MAX` raised from 3 to 4.
- `frontend/src/pages/LobbyPage.jsx`:
  - `<input data-testid="bot-count-input" max>` is now **dynamic**:
    3 for target 30/50, 4 for target 75/100.
  - Effect hook clamps the input value downward when the user switches
    from a 5-seat target to a 4-seat one.
- `backend/tests/test_lobby_phase11_p2.py::TestBotsGated` updated with
  per-target acceptance (30→3, 100→4, 250→4), per-target rejection
  (30→4), and global-ceiling rejection (any target→5). Added
  `test_config_exposes_per_target_bot_cap`.
- Suite total: **185 passed / 2 skipped** (was 180; +5 net new).
- E2E live: created `target=100 bot_count=4` table via REST → START →
  WS STATE_UPDATE shows 5 players (4 bots + 1 human). Frontend
  `<input max>` dynamic (3/4/4) confirmed; downward-clamp confirmed
  (value=4 on target-100 → switch to target-30 → auto-clamped to 3).

## 2026-05 v2 — Target 250 removed + deck-refill + showdown reveal
- **Valid target set locked to `{30, 50, 75, 100}`** — target 250 deprecated.
  - `backend/core/constants.py::VALID_TARGET_SCORES = (30, 50, 75, 100)`
  - `TABLE_SEATS_BY_TARGET = {30:4, 50:4, 75:5, 100:5}`
  - Lobby config endpoint, `LobbyPage.jsx` target options, and all tests
    now reference 75 in place of 250.
- **Deck-exhaustion refill** — when the initial 54-card deck empties
  mid-hand, the engine refills with a fresh **52-card jokerless** deck
  (`backend/game_engine/deck.py::build_fresh_deck(include_jokers=False)`).
  `GameState.deck_refills` counter tracks refills per hand. Unit-test
  coverage in `tests/test_deck_refill_2026_05.py`.
- **Opponent cards reveal at SHOWDOWN / PAYOUT** — `realtime_v2/bridge.py`
  includes `players[*].cards` in public `STATE_UPDATE` broadcasts **only**
  when `state.phase ∈ {SHOWDOWN, PAYOUT}`; pre-showdown privacy preserved
  (F9 card-privacy test still green).
- **Stuck-state fix (5-seat + 4 bots)** — verified live: target=100 with
  4 bots progresses `BETTING_R1 → DRAW_1 → BETTING_R2 → DRAW_2 →
  BETTING_R3 → PAYOUT` without stalling, and all 4 opponent hands reveal
  at payout.
- **Test suite: 224 passed / 2 skipped** against live backend (legacy
  `test_websocket.py` excluded — tests `backend/realtime/` deprecated
  single-DRAW path per PRD legacy directive).
- Docs updated: `memory/GAME_RULES_LOCKED.md` §2 seat table + §8 rule-log;
  `memory/PRD.md` core requirements section.

## 2026-05 v2 — Game-core stabilization (legacy WS out + deadlock guards)
- **Legacy WebSocket path fully removed.**
  - `backend/server.py` no longer imports or mounts
    `backend/realtime/ws_router.py` or `backend/realtime/table_worker`.
    Only `/api/v2/ws/table/{id}` (realtime_v2) serves live traffic.
  - `backend/realtime/` stays on disk as quarantined dead code for one
    more release (nothing imports it).
  - `backend/tests/test_websocket.py` auto-skips via module-level
    `pytestmark = pytest.mark.skip(...)` — 10 tests skipped, 0 fail.
- **Bot-subscription race fixed** — `_BotDriver.start()` now awaits
  `pubsub.subscribe()` before returning, so the lobby's subsequent
  `START_HAND` submit can never race the bot's subscribe. `_run()`
  also has a 2s watchdog poll that re-checks `engine.state` and acts
  if the bot is authoritatively on-turn but no recent STATE_UPDATE
  arrived (guards against slow-consumer drops).
- **Betting-phase turn timer added** — `TurnEngine._maybe_arm_timeout`
  now arms the 15s timer during `BETTING_R1/R2/R3` as well as DRAW.
  On expiry it submits a server-source `CHECK` (no call owed) or
  `FOLD` (call owed) for the stalled seat. Prevents indefinite
  deadlock if a human disconnects or stalls during betting.
  DRAW auto-timeout still fires `AUTO_STAND_TIMEOUT` — "never fold on
  draw timeout" invariant preserved and explicitly re-tested
  (`test_betting_timeout_2026_05.py::test_draw_1_still_auto_stands_never_folds`).
- **New regression tests (all passing):**
  - `test_betting_timeout_2026_05.py` — 3 unit tests for the new guards.
  - `test_bot_stress_2026_05.py` — live E2E that runs **5 consecutive
    hands** at target=100 + 4 bots, asserts every hand reaches PAYOUT,
    no stalls (8s stall-detector), opponent cards revealed at showdown,
    and ≥3/5 hands exercise the full multi-round fan
    (R1 → DRAW_1 → R2 → DRAW_2 → R3 → PAYOUT).
- **Suite total: 222 passed / 12 skipped** (10 legacy-ws skips + 2
  pre-existing TestClient WS incompatibilities). The bot-stress E2E
  test is gated behind `REACT_APP_BACKEND_URL` and takes ~2min.

## 2026-05 v2 — Gameplay-layer lock (strategic bots + balance sim + showdown clarity)
- **Bot policy locked (`dev_router._BotDriver._decide_draw_action`)**:
  - `score < target*0.5` → HIT
  - `0.5*target ≤ score < 0.8*target` → 60% HIT / 40% STAND (deterministic
    PRNG keyed on `table_id + bot_user_id + state_version`, so replays
    reproduce the same decisions)
  - `score ≥ target*0.8` → STAND
  - `score ≥ target` → STAND (bust-safety; reducer rescore prevents this
    path being reached anyway)
- **Deterministic turn progression**: added defensive fallthrough in
  `reducer._maybe_end_betting` — if `_next_in_hand` ever returns `None`
  while `len(in_hand) ≥ 2` (unreachable today; future-proofing), force
  `_end_betting_to_deal` instead of silently leaving the state stuck.
- **Gameplay balance report** (`test_balance_sim_2026_05.py`,
  30 hands per config, 1 human + max bots):
  | Target | Seats | mean_steps | max_steps | bust_rate | distinct winner seats |
  |-------:|:-----:|:----------:|:---------:|:---------:|:---------------------:|
  | 30     | 4     | 21.8       | 25        | 1.7%      | 3                     |
  | 50     | 4     | 25.8       | 32        | 0.0%      | 3                     |
  | 75     | 5     | 36.2       | 44        | 0.0%      | 4                     |
  | 100    | 5     | 41.4       | 49        | 0.0%      | 4                     |
  All hands reached PAYOUT with no sig-loops. Deterministic-replay
  regression added (`test_balance_sim_no_shuffle_determinism_regression`).
- **Showdown clarity (PlayPage.jsx)**:
  - Winner seat ringed gold with `WINNER` pill next to the username
    (new `data-testid="opponent-{seat}-winner"`).
  - Own seat gets a `WINNER` pill (new `data-testid="my-winner-pill"`)
    when local player is in the winners list.
  - Existing winners-panel banner and opponent card reveal at
    SHOWDOWN/PAYOUT unchanged.
- Suite: **227 passed / 2 skipped** (backend); `test_bot_stress_2026_05.py`
  still passes live with the new bot policy.

## 2026-05 v2 — Game-feel & UX clarity polish (PlayPage only)
- **Action feedback banner + log**: every gameplay action now surfaces a
  transient 4-second banner plus an event-log line: `Bot_X checked`,
  `Hero stood`, `Bot_Y called 100`, `Bot_Z auto-fold
  (BETTING_TIMEOUT_15S)`, etc. Self-echo suppressed.
- **Bot personality labels (cosmetic only)**: each bot seat shows
  `· Conservative`, `· Balanced`, or `· Aggressive` next to its
  username. Stable hash of `user_id` — zero impact on reducer.
- **Showdown clarity labels** at `SHOWDOWN` / `PAYOUT`:
  - `CLOSEST TO TARGET` on the highest-scoring non-busted/non-fold seat
  - `BUSTED` / `DISQUALIFIED`
  - `RISK TAKER` when `card_count ≥ 3`
- **Hand summary card**: new panel below the winners banner at hand end.
  Winner name(s), `score vs runner-up (+diff)`, per-seat row
  (`score`, `cards drawn`, up to 2 labels). Winner rows gold-highlighted.
- Live E2E verified at target=50 + 3 bots: all four features rendered in
  one pass. No engine / backend / balance changes.

## 2026-05 v2 — Responsive layout (mobile + desktop)
- **Pure-CSS responsive migration** via Tailwind `sm:` breakpoints in
  `PlayPage.jsx` and `LobbyPage.jsx`. No component refactor, no new
  libraries, zero backend / reducer / engine churn.
- **Desktop layout preserved exactly** (verified via Playwright:
  viewport 1280×800 → actions-bar inline at y=445, opponent card width
  220px fixed, status-line visible — matches prior behaviour).
- **Mobile adaptations** (verified at 390×844 and 430×932):
  - Top bar stacks vertically; phase/v/target/pot/ws pills wrap.
  - Opponent cards go full-bleed (`w-full sm:min-w-[220px] sm:w-auto`).
  - Card rows wrap on narrow viewports (no horizontal scroll).
  - Action buttons (HIT / STAND / CHECK / CALL / FOLD / PLAY 2 /
    PLAY 10 / DEAL AGAIN) collapse to a **sticky bottom bar**
    (`fixed bottom-0 z-30 bg-black/95 border-t … sm:static sm:bg-transparent`)
    with `pb-24 sm:pb-0` padding on the page root so content is never
    obscured.
  - Action buttons use `px-4 sm:px-7 text-sm sm:text-base` so they fit
    comfortably on 390px while staying thumb-reachable.
  - Secondary "status-line" (`Connected – dealing…`) hidden on mobile
    (`hidden sm:inline-block`).
  - Lobby page padding reduced `p-4 sm:p-6`; form grid already used
    `grid-cols-2 sm:grid-cols-5` so it wraps cleanly.
- **Responsive smoke test** (`backend/tests/manual_responsive_smoke.py`,
  runs under `/opt/plugins-venv/bin/python`): asserts per-viewport
  bounding-box invariants at 1280 / 390 / 430 — all 3 PASS.

## 2026-05 v2 — Provably-fair RNG: per-seat client_seed contribution
- **`game_engine/rng.py`**: new canonical helper
  `combine_client_seeds_by_seat(seeds_by_seat, seat_order) → sha256_hex`.
  Each seat is encoded as `seat_index:client_seed`, joined by `|`,
  hashed. Seat-prefix prevents pipe-injection spoofing; missing seats
  contribute as `seat:` (still alters digest if added later).
- **`game_engine/types.py`**: state gains
  `pending_client_seeds: Dict[int, str]`,
  `client_seeds_used: Dict[int, str]`,
  `server_seed_buffer: Optional[str]`. Dict keys round-trip via
  `state_from_dict` (JSON serialises ints as strings).
- **Reducer**:
  - New `SUBMIT_CLIENT_SEED` action (CLIENT-source). Allowed in
    `WAITING / PAYOUT / ENDED`; otherwise raises `SEED_LOCKED`.
    Validates seed (non-empty string ≤ 256 chars, must be a seated
    user). Stores `pending_client_seeds[seat] = seed`, bumps version,
    emits `CLIENT_SEED_SUBMITTED` event.
  - `START_HAND` consumes seeds in this priority:
    `action.client_seeds_by_seat` → `state.pending_client_seeds` →
    legacy string `action.client_seeds` (unchanged for back-compat).
    Combines via `combine_client_seeds_by_seat` then
    `compute_shuffle_seed(server_seed, combined, nonce)`. Persists
    the locked map in `client_seeds_used`, clears `pending_*`.
    `server_seed_buffer = action.server_seed` (held in state, hidden
    from broadcasts).
  - `_enter_showdown` promotes `server_seed_buffer → rng_revealed_seed`,
    then nulls the buffer. Players can now verify
    `sha256(rng_revealed_seed) == rng_commit_hash` and re-derive the
    deck independently.
- **`view_filter.public_view`**: strips `server_seed_buffer` from every
  client broadcast. `rng_revealed_seed` and `client_seeds_used` are
  public (necessary for verification).
- **`event_log/writer.py`**: `_extract_replay_inputs` now persists both
  `client_seeds` (legacy string) and `client_seeds_by_seat` (v2 dict).
- **`event_log/replay.py`**: `reconstruct_intent` lifts
  `client_seeds_by_seat` back into the START_HAND replay intent.
  Existing replay tests (`test_event_log_phase4.py`) pass unchanged.
- **`lobby/router.py`** + **`realtime_v2/dev_router.py`** (lobby path):
  every `START_HAND` now uses `generate_server_seed()` (32-byte
  cryptographically-random hex), with `nonce = state.hand_number + 1`
  for distinct shuffles across hands at the same table. The dev
  router HTML test page retains its fixed-seed legacy string form
  (used only for the embedded play.html dev UI).
- **Tests**: `tests/test_client_seed_2026_05.py` — **11 cases, all PASS**:
  - same inputs → same deck
  - changing one client_seed → different deck
  - missing seeds still deterministic
  - partial contribution differs from no contribution
  - submission order doesn't matter (sorted by seat)
  - SUBMIT_CLIENT_SEED locked during ANTE/BETTING/DRAW/SHOWDOWN
  - allowed during WAITING/PAYOUT/ENDED
  - input validation (empty, non-string, oversize, unseated)
  - server_seed hidden during play, revealed at SHOWDOWN
  - replay with persisted seeds reconstructs identical state
  - external verifier reproduces the deck via `combine_client_seeds_by_seat`
- **Suite**: 240 passed / 2 skipped (canonical, excluding live bot
  stress + legacy WS). Live bot-stress passes (5 hands target=100 +
  4 bots, all reach PAYOUT with the new RNG path).

## 2026-05 v2 — Frontend wiring for SUBMIT_CLIENT_SEED + fairness UX
- **`frontend/src/lib/fairness.js`** (new): pure-browser port of the
  backend RNG (`combineClientSeedsBySeat`, `computeShuffleSeed`,
  `buildFreshDeck`, `shuffleDeck`, `deriveInitialDeck`, `verifyCommit`,
  `randomClientSeed`). Algorithms bit-for-bit identical to backend
  (verified Node ↔ CPython).
- **PlayPage.jsx** — three new UX layers, **no engine / RNG-logic
  change**:
  1. **Seed input panel** (between hands only — gating mirrors the
     reducer's `SEED_LOCKED` rule): text input + Generate-random +
     Submit + Use-default. Sends `SUBMIT_CLIENT_SEED` via WS.
     `✓ Locked in for next hand` confirmation appears once
     `view.pendingClientSeeds[seat]` arrives.
  2. **In-hand indicator**: gold `FAIRNESS ON` pill in the top bar.
  3. **Verify modal at PAYOUT** (`Verify result` button inside
     hand-summary): renders commit hash, revealed seed, nonce, all
     per-seat random seeds. Verify button locally re-derives the deck
     and **suffix-compares** against `deck_remaining`. Shows ✓/✗ +
     plain-language detail.
- **Backend additive changes** (no logic / RNG / gameplay change):
  - `bridge.py` broadcasts the RNG fields (`rng_commit_hash`,
    `rng_revealed_seed`, `rng_nonce`, `client_seeds_used`,
    `pending_client_seeds`, `deck_remaining`, `deck_refills`).
  - `view_filter.public_view` exposes `state.deck` ONLY at
    SHOWDOWN/PAYOUT.
  - `protocol.py` allow-lists `SUBMIT_CLIENT_SEED` in CLIENT_ACTIONS.
  - `reducer.py` no-seeds `START_HAND` path now uses canonical
    `combine_client_seeds_by_seat({}, seat_order)` so external
    verifiers reproduce the deck without prior knowledge of pre-v2
    vs v2 hands.
- **New tests** — `test_fairness_xverify_2026_05.py` (2 cases): drives
  a hand to PAYOUT, derives the deck from the public view, asserts
  `deck_remaining` matches the suffix of the derivation. Catches the
  empty-seed inconsistency that broke the live verify on first run.
- **Suite**: 240 passed / 2 skipped (canonical).
- **Live E2E**: target=50 + 3 bots → seed submission shows
  `Locked in for next hand`; verify modal returns `data-pass="true"`
  (commit + suffix-deck match) on a real game.

## 2026-05 v2 — Quarantined `backend/realtime/` directory deleted
- **Deleted files** (4 backend + 2 frontend):
  - `backend/realtime/` directory: `__init__.py`,
    `connection_manager.py`, `table_worker.py`, `ws_router.py`
  - `backend/tests/test_websocket.py` (all tests targeted the
    deleted legacy WS path; was already module-level skipped)
  - `frontend/src/pages/GamePage.jsx` (legacy `/table/:tableId`
    screen; gameplay moved to `/play/:tableId` long ago)
  - `frontend/src/lib/ws.js` (sole consumer was `GamePage`)
- **Edits** (no functional change):
  - `frontend/src/App.js` — removed `GamePage` import; the route
    `/table/:tableId` now redirects to `/lobby`.
  - `frontend/src/lib/api.js` — removed orphaned `wsUrl` helper that
    pointed at the deleted `/api/ws/table/{id}` URL.
  - `backend/server.py` — comment updated; the legacy router was
    already unmounted in the prior pass.
- **Verification**:
  - `grep -rn "backend/realtime\|/api/ws/table\|from realtime\."`
    now matches only doc-comments across `/app`.
  - Full canonical suite: **240 passed / 2 skipped** (no regression).
  - ESLint clean across `frontend/src`.
  - `realtime_v2`, reducer, RNG, protocol untouched.

## 2026-05 v2 — RNG consistency cleanup
- **`realtime_v2/dev_router.py`** `/spawn_solo_table` now uses
  `generate_server_seed()` (commit-reveal SHA-256) and `nonce=1`,
  matching the production `lobby/router.py` start path. Removed the
  fixed `"0" * 64` / `"h" * 64` / `client_seeds=""` constants.
- Every entry point that submits `START_HAND` (lobby + dev) now goes
  through the same RNG generator — single-source story for auditors
  and future contributors.
- Verified live: `POST /api/v2/dev/spawn_solo_table` → WS broadcast
  carries a fresh `rng_commit_hash` (no longer `"h"*64`).
- Canonical suite: **240 passed / 2 skipped** (zero regression).

## 2026-05 v2 — Emergent-managed Google OAuth (P1)
- **New module `backend/auth_oauth/`** sitting beside the existing
  guest/JWT flow. No legacy auth code touched.
  - `POST /api/v2/auth/google/session` — exchanges a one-time
    `session_id` (from the URL fragment after the Emergent OAuth
    redirect) for `{user, jwt}` + a 7-day `session_token` httpOnly
    cookie.
  - `GET  /api/v2/auth/me` — resolves identity from cookie OR bearer
    (cookie wins; bearer is fallback for WS/lobby compatibility).
  - `POST /api/v2/auth/logout` — clears cookie + DB session.
  - The minted JWT uses `core.security.create_token` so the existing
    WebSocket gateway and lobby endpoints accept the OAuth user
    transparently.
- **Identity persistence**:
  - `users` collection (uniqued by `email`) for OAuth identities.
  - `user_sessions` collection for cookie-backed session lookup.
  - `lobby_users` mirror written on first login so
    `lobby/service.get_user` finds the same user without a rewrite.
- **Guest auth gated by `ALLOW_GUEST_AUTH`** (default ON in dev). When
  set to `0`/`false`, `POST /api/v2/lobby/auth` returns
  `403 GUEST_AUTH_DISABLED`. Lets ops disable the dev login path in
  production without touching code.
- **Frontend wiring** (`LobbyPage.jsx`): added a Google sign-in button
  that redirects to `https://auth.emergentagent.com/?redirect=<origin>`
  and a fragment handler that POSTs the returned `session_id` to the
  backend. Guest login button is preserved for dev / CI use.
- **No user-supplied credentials required** — uses the Emergent-managed
  OAuth proxy (`demobackend.emergentagent.com/auth/v1/env/oauth/session-data`).
  `OAUTH_COOKIE_SECURE` env var defaults to `1`; set to `0` only for
  plain-HTTP test harnesses.
- **New tests** — `tests/test_auth_oauth_2026_05.py` covers
  exchange→cookie→`/me`→logout, bearer fallback, 401/422 error paths,
  guest-auth gating, and the lobby-mirror writeback.
- **Suite**: **244 passed / 2 skipped** (was 240; +4 OAuth tests).
- See [`/app/memory/test_credentials.md`](./test_credentials.md) for
  the full auth-surface contract used by the testing agent.

## 2026-05 v2 — Race-condition fix: deterministic `/start` → `BETTING_R1`
**Issue:** `tests/test_lobby_phase11_p2.py::TestTwoUserE2E::test_two_real_users_both_get_betting_r1_state`
intermittently flaked under load. Root cause: `_spawn_engine_for_table`
in `lobby/router.py` called `engine.submit(START_HAND)` and returned
the HTTP 200 immediately — without awaiting the engine's serial
processor. WebSocket clients connecting in the gap snapshotted the
engine in `WAITING` (state_version=0) instead of `BETTING_R1`.

**Fix (synchronization, no game-rule / reducer change):**
- New public method `EngineBridge.submit_server_intent(table_id, intent,
  *, timeout)` in `realtime_v2/bridge.py`. Uses the same
  `client_action_id` future plumbing as `handle_action` to await
  full engine processing (including the `_on_event` broadcast)
  before returning.
- `lobby/router.py::_spawn_engine_for_table` now awaits
  `bridge.submit_server_intent(...)` for `START_HAND` (timeout=3s)
  instead of fire-and-forget `engine.submit(...)`.
- `realtime_v2/dev_router.py::spawn_solo_table` mirrored to the same
  pattern so `/api/v2/dev/spawn_solo_table` is equally deterministic.
- Test strengthened: now asserts `WELCOME.state_version >= 1` AND
  the first `STATE_UPDATE.phase == "BETTING_R1"` for both users.

**Verification:**
- `test_two_real_users_both_get_betting_r1_state` — **10/10 runs pass**.
- Full canonical suite — **3/3 runs pass at 240 / 240** (excluding
  the slow live `test_bot_stress_2026_05.py` and `test_balance_sim_2026_05.py`,
  which are gated to manual / nightly runs and unaffected).
- No reducer, scoring, betting, or RNG semantics changed. Pre-existing
  flakiness in the unrelated `test_phase11_validation.py::test_f3_f4_f11_canonical_flow_with_bot`
  (interactive multi-round flow with a bot, sensitive to bot timing)
  is **out of scope for this task** and was not introduced by these
  changes.

## 2026-05 v2 — Google OAuth bugfix: CORS-with-credentials + StrictMode race
**User-reported issue:** Google sign-in returned 403 / silent failure;
lobby failed to load tables after auth attempt.

**Root causes:**
1. **CORS-with-credentials misconfiguration (backend):**
   `CORSMiddleware(allow_origins=["*"], allow_credentials=True)` causes
   the backend to send `Access-Control-Allow-Origin: *` paired with
   `Access-Control-Allow-Credentials: true`. Browsers REJECT this
   combination as invalid CORS when the frontend uses `credentials:
   'include'` (which the OAuth `POST /api/v2/auth/google/session` and
   `GET /api/v2/auth/me` calls do for the cookie session). Result: the
   browser silently blocked the OAuth POST. Verified with curl
   against localhost:8001 — response had both headers, breaking CORS.
2. **React StrictMode double-fire (frontend):**
   The OAuth-callback `useEffect` ran twice in dev/StrictMode and
   POSTed the single-use `session_id` to the backend twice. Emergent's
   exchange endpoint is single-use, so the 2nd call returned 401 and
   raced the 1st (successful) call's `setUser`. UI showed an error
   even when auth succeeded, plus a 401 in the network tab.
3. **`/me` race vs OAuth callback (frontend):**
   The refresh-resilience effect called `GET /api/v2/auth/me` BEFORE
   the OAuth callback could set the cookie — burning a request and
   risking state clobber.

**Fixes:**
- **`backend/server.py`**: replaced `CORSMiddleware(allow_origins=["*"])`
  with `allow_origin_regex=".*"` when `CORS_ORIGINS` is unset / `*`.
  Starlette echoes the request `Origin` instead of `*`, producing a
  valid `Access-Control-Allow-Origin: <origin>` +
  `Access-Control-Allow-Credentials: true` pair. When `CORS_ORIGINS`
  is a comma-separated list, that explicit list is used.
  Verified locally: `curl -H "Origin: <preview>" /api/v2/auth/google/session`
  now returns `access-control-allow-origin: <preview>` (was `*`).
- **`frontend/src/pages/LobbyPage.jsx`**:
  - Added `useRef` guard (`oauthProcessed`) set synchronously at the
    start of the OAuth `useEffect` so StrictMode's second run is a
    pure no-op. Now exactly one POST per `#session_id=`.
  - Captured `window.location.hash` in `useRef` at first render so
    StrictMode's mount-then-cleanup-then-mount cycle still sees the
    original hash even after `replaceState` strips it.
  - `replaceState` now happens **immediately** (before the async
    fetch), so a refresh / back-button can never re-submit the
    one-time `session_id`.
  - `/me` refresh-resilience effect now skips when
    `window.location.hash` contains `session_id=` (per Emergent
    Auth playbook §"Global AuthProvider Race Condition").
  - Error message expanded with backend `detail` + actionable
    "use guest sign-in below" hint.
- **No backend logic changes to `auth_oauth/router.py`** — the
  exchange / cookie / DB path was correct already. The bugs were
  in environment plumbing (CORS) and frontend lifecycle.

**Verification:**
- Browser screenshot: `#session_id=<unique>` → 1 POST → URL stripped
  → graceful 401 error w/ guest fallback visible.
- Browser screenshot: cookie-injected OAuth user → lobby loads
  showing the user's name, full table list, logout button, create
  form — all working.
- `tests/test_auth_oauth_2026_05.py` — **5/5 PASS** (full
  exchange + cookie + bearer + lobby-bridge + logout flow).
- Full canonical suite — **240 passed / 2 skipped** (one suite run
  hit a pre-existing live-backend concurrency flake in
  `TestStartLifecycle`, unrelated to OAuth and recovers on retry).
- WebSocket connect via OAuth-issued JWT: confirmed (the test
  `test_google_full_flow_and_lobby_bridge` already creates a table
  and uses the JWT for the lobby-bridge call — the same JWT path
  the WS gateway uses).

**Frontend OAuth flow contract (locked):**
1. User clicks `[data-testid="google-signin-btn"]` →
   `https://auth.emergentagent.com/?redirect=${origin}/lobby`.
2. Emergent OAuth flow → returns to `/lobby#session_id=<one-time>`.
3. Frontend captures hash via `useRef` during render, posts to
   `/api/v2/auth/google/session` exactly once (StrictMode-safe),
   strips the hash, persists `target_user`, and renders authed UI.
4. Cookie session (7-day) is set httpOnly + secure + samesite=none.
5. Refresh → `GET /api/v2/auth/me` (cookie auth) restores name; user
   re-clicks Google sign-in to mint a fresh JWT for table actions.

## Next Action Items
2. ✅ P0: Multi-round betting — **DONE 2026-05**.
3. ✅ P0: Special-card UI/intent for PLAY_TWO / PLAY_TEN — **DONE 2026-02**.
4. ✅ P0: Responsive layout (mobile + desktop safe) — **DONE 2026-05 v2**.
5. ✅ P0: Replay client_seed contribution to RNG — **DONE 2026-05 v2**.
6. ✅ P0: Reconnect grace timer (20–30s) with sitting_out flag — **DONE 2026-02**.
7. ✅ P0: Per-target bot cap (5-seat tables) — **DONE 2026-05**.
8. ✅ P0: Target 250 → 75 migration + deck-exhaustion refill + showdown reveal — **DONE 2026-05 v2**.
9. ✅ P0: Game-core stabilization (legacy WS out, betting-timeout, bot race fix) — **DONE 2026-05 v2**.
10. ✅ P0: Gameplay-layer lock (strategic bot policy, balance sim, showdown clarity) — **DONE 2026-05 v2**.
11. ✅ P0: Game-feel & UX clarity polish (action feedback, bot flavors, hand summary) — **DONE 2026-05 v2**.
12. ✅ P1: Frontend wiring for SUBMIT_CLIENT_SEED + verify-result modal — **DONE 2026-05 v2**.
13. ✅ P1: Quarantined `backend/realtime/` directory deletion — **DONE 2026-05 v2**.
14. ✅ P2: RNG consistency cleanup (dev_router uses generate_server_seed) — **DONE 2026-05 v2**.
15. ✅ P1: Emergent-managed Google OAuth (with guest-auth gating) — **DONE 2026-05 v2**.
16. ✅ P2: Flaky-test fix — deterministic `/start` → `BETTING_R1` synchronization — **DONE 2026-05 v2**.
17. ✅ P0: Google OAuth bugfix — CORS-with-credentials + StrictMode race — **DONE 2026-05 v2**.
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
