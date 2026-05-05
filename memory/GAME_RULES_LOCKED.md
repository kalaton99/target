# TARGET — Locked Game Rules (2026-05)

Authoritative source for game rules that diverge from older drafts
(PRD v3.2 and the original Target Game Design Document). Anything here
overrides older text. Future agents/contributors must read this before
touching engine, constants, lobby, or bot code.

---

## 1. No rules outside the Target Game Design Document

All gameplay changes must stay within the Target Game Design rules.
Speculative mechanics (multi-community cards, side pots, split pots,
kicker logic, poker-style showdowns) that are **not** in the design
document are out-of-scope and will not be added — even as "small
extensions". If a rule isn't in the design doc or this file, it isn't
law; ask before writing code.

---

## 2. Table sizes are locked per target tier

Seats per table are determined by the chosen target score. No other
values are valid. Production must reject table creation outside the
table below.

| Target score | Seats | Min seated to start | Notes |
|-------------:|:-----:|:-------------------:|:------|
| 30           | 4     | 2                   | Low-stake fast hand |
| 50           | 4     | 2                   | Low-stake fast hand |
| 75           | 5     | 3                   | Mid-stake |
| 100          | 5     | 3                   | Mid/high-stake |

> **2026-05 v2:** Target **250 has been removed** from the valid target
> set. The authoritative tuple is `VALID_TARGET_SCORES = (30, 50, 75, 100)`
> in `backend/core/constants.py`. Any client-supplied `target_score`
> outside this set must be rejected by `/api/v2/lobby/tables` with
> `422 INVALID_TARGET_SCORE`.

> **2026-05 v3 (wording correction):** The TARGET game does **not**
> support 2-player tables as a *table type*. Throughout this codebase
> the phrase "n_players=2" / "2-player flow" / "2-seat hand" in tests,
> diagnostics, comments, and simulations refers to **a 4-seat table
> with 2 humans seated** (the minimum legal start for the 4-seat
> tier). It is **not** a 2-seat table. There is no 2-seat table type
> in the rules. 5-seat tables (target 75 / 100) require at least 3
> humans seated to start.

The min-seated threshold is per-tier:
- **4-seat tables (target 30 / 50)** start when **seated ≥ 2**.
- **5-seat tables (target 75 / 100)** start when **seated ≥ 3**.

"Seated" includes any player occupying a seat, whether human or bot.
Bots are dev-only (see §5) and production tables must satisfy the
threshold in human seats alone.

---

## 3. Deprecated: 6–8 player tables

The legacy `MAX_PLAYERS = 8` constant, Pydantic `le=8` limits on
`max_players`/`min_players`, and the `STAND_THRESHOLD` entries for
6/7/8 are **deprecated**. Migration plan lives at §7 of this file.
Do NOT create new code paths that assume ≥6 seats.

The engine's internal threshold lookup table must still handle **3
active players at runtime** (e.g. one player folds in BETTING_R1 of a
4-seat table, leaving 3 active for DRAW). So the runtime-active-count
lookup retains entries for {2, 3, 4, 5}. Seat caps (max_players) are
capped at 5; runtime-active counts are ≤ seat cap.

---

## 4. Stand-threshold table (updated)

Indexed by **active-players-entering-DRAW** (`state.draw_active_count`),
not by seat cap:

| Active in DRAW | Stands that trigger SHOWDOWN |
|:--------------:|:----------------------------:|
| 2              | 1                            |
| 3              | 2                            |
| 4              | 3                            |
| 5              | 3                            |

Entries for 6, 7, 8 are **deprecated**. They remain harmless in the
current dict (legacy unused) and will be removed during the migration
in §7. The 5-active value (**3**) matches the current code and the new
rule exactly — no change needed.

---

## 5. CPU/bot players — configurable, dev-only

### Rules

1. CPU bots are a **testing affordance**. Production multiplayer must
   be all-human.
2. The number of bots per table must be **configurable**, not
   hardcoded. Range: **0–3** inclusive.
3. Bots must be **easy to disable**. Production builds default to
   `ALLOW_BOTS=0`; any attempt to spawn a bot in that mode is a hard
   server error.
4. The "spawn 1 bot if creator is alone" behaviour that currently runs
   in lobby's `_spawn_engine_for_table` was a Phase 11 MVP shortcut. It
   must become dev-only and disabled by default in production.

### Config contract (to be implemented in §7)

Environment variables (backend):
- `TARGET_ALLOW_BOTS` — `0` (production default) | `1` (dev).
- `TARGET_BOT_COUNT_MAX` — integer, clamped to `[0, 3]`; default `0`
  in production, `1` in dev.

Per-table override (dev-only, ignored in production):
- `CreateTableRequest.bot_count` — optional `int`, defaults to 0;
  clamped to `[0, TARGET_BOT_COUNT_MAX]`; rejected with 400 when
  `TARGET_ALLOW_BOTS=0` and `bot_count > 0`.

Bot user_ids must keep the `u_bot_` prefix so existing lobby tests that
assert `startswith("u_bot_")` continue to work in dev.

---

## 6. Current gameplay stays stable

Until §7's migration is planned and sequenced, the current code runs
unchanged. No reducer refactor, no engine refactor, no lobby schema
break. The new rules are documented here first; code migration is
sequenced in §7.

---

## 7. Code areas that will need changes (migration checklist)

Every item below is a **pending change** — not yet implemented. Each
is scoped to the minimum delta.

### 7.1 Per-target seat cap (Rule 2)

| File | What | Type |
|---|---|---|
| `backend/core/constants.py` | Add `TABLE_SEATS_BY_TARGET = {30: 4, 50: 4, 100: 5, 250: 5}`. Leave `MAX_PLAYERS = 8` in place temporarily (marked `# DEPRECATED — see GAME_RULES_LOCKED.md §7`) so legacy callers don't break mid-migration. | additive |
| `backend/lobby/router.py::CreateTableRequest` | Remove `max_players`/`min_players` as user-supplied fields (or make them optional and ignored). Server derives `max_players` from `target_score` via `TABLE_SEATS_BY_TARGET`. `min_seated_to_start` is per-tier (2 for 4-seat tables, 3 for 5-seat tables) — see §2 of this file. | schema change |
| `backend/lobby/service.py::create_table` | Same derivation: ignore any client-supplied `max_players` and recompute from target. Reject unknown target scores. | server-side constraint |
| `backend/game_engine/types.py::GameState.max_players` | Default stays at 8 in the dataclass for legacy compatibility; call sites already pass it explicitly from the table doc. No change required unless we want to tighten the default (optional). | none required |
| `frontend/src/pages/LobbyPage.jsx` | Drop the Min/Max input fields from the create-table form; server derives them. Display the derived seat cap next to the target-score select. | form simplification |

### 7.2 Deprecate 6–8 player assumptions (Rule 3)

| File | What | Type |
|---|---|---|
| `backend/core/constants.py` | Change `MAX_PLAYERS = 8` → `MAX_PLAYERS = 5`. Remove `STAND_THRESHOLD` entries for 6, 7, 8. Add a comment linking to `GAME_RULES_LOCKED.md`. | constant change |
| `backend/lobby/router.py::CreateTableRequest` | `max_players: int = Field(..., ge=2, le=8)` → `le=5`. (Eliminated entirely if 7.1 removes the field.) | constraint tighten |
| `backend/lobby/service.py::create_table` | Validation uses the new `MAX_PLAYERS = 5`; no literal change needed. | automatic |
| `backend/tests/test_lobby_phase11_p2.py` | Any test that creates an 8-seat table must be updated (none currently do — spot-checked: tests use 2 or 4). | audit-only |
| `backend/tests/test_engine_target.py` | Same — spot-checked: all engine tests use 2 seated players (a 4-seat table partially filled — there is no 2-seat table type). No change needed. | audit-only |

### 7.3 Stand-threshold audit (Rule 4)

| File | What | Type |
|---|---|---|
| `backend/core/constants.py::STAND_THRESHOLD` | After 7.2 trims 6/7/8, the dict becomes `{2: 1, 3: 2, 4: 3, 5: 3}` — **exact match** to the locked rule. No per-entry change needed. | no-op (happens as part of 7.2) |
| `backend/game_engine/reducer.py` line 244 | `threshold = STAND_THRESHOLD.get(state.draw_active_count, state.draw_active_count)` — still correct; fall-back is harmless for impossible counts. | no change |

### 7.4 Bots configurable and dev-only (Rule 5)

| File | What | Type |
|---|---|---|
| `backend/core/constants.py` | Add `ALLOW_BOTS = bool(int(os.environ.get("TARGET_ALLOW_BOTS", "0")))`, `BOT_COUNT_MAX = max(0, min(3, int(os.environ.get("TARGET_BOT_COUNT_MAX", "0"))))`. | additive |
| `backend/lobby/router.py::CreateTableRequest` | Add optional `bot_count: int = Field(default=0, ge=0, le=3)`. | additive |
| `backend/lobby/router.py::_spawn_engine_for_table` | Replace the `spawn_bot_if_alone=True` shortcut (line 69) with a loop that appends up to `bot_count` bot seats. Hard-reject `bot_count > 0` when `ALLOW_BOTS` is false. Make the "creator alone" auto-bot behaviour **opt-in** via dev config, not the default. | behaviour change |
| `backend/realtime_v2/dev_router.py::spawn_solo_table` | Keep this dev-only endpoint; it already creates a bot-paired table and is fine for `/play` solo mode under dev config. Add the `ALLOW_BOTS` guard. | additive |
| `backend/tests/test_lobby_phase11_p2.py` | Tests that rely on the auto-bot fallback must set `TARGET_ALLOW_BOTS=1` via `monkeypatch` or pass `bot_count=1` explicitly. | test-fixture update |
| `backend/server.py` | (Optional) log a startup banner confirming `ALLOW_BOTS` status so ops can't accidentally ship bot-enabled builds. | observability |
| `frontend/src/pages/LobbyPage.jsx` | Add an optional "bots" integer input to the create-table form. Gate the control behind a feature check (e.g. `window.TARGET_ALLOW_BOTS === true` set from a trivial `/api/v2/lobby/config` probe). | additive |

### 7.5 Future multi-round betting (design notes only)

The multi-round design doc (in prior session's handoff summary) assumed
up to 8 seats. With the new 4/5-seat cap:

- The stand-threshold table still bottoms out at 5 active, so the
  multi-round design's edge cases ("all bust" / "one player left"
  shortcuts) get more reachable — a 4-seat table entering DRAW_2 with
  only 2 drawers is now common, not rare.
- Betting round transitions in smaller tables will be **faster**
  (fewer responded_seats to check), which exercises the
  `len(in_hand) <= 1 → _end_betting_to_deal → _enter_showdown`
  short-circuit more. The design already handles this; just
  flagging that 4/5-seat becomes the primary test case, not 8.
- The multi-round `betting_round` field (proposed `0..3`) is
  orthogonal to seat cap — no interaction.

### 7.6 Backlog priority after migration

- P0 (after this migration): resume multi-round betting implementation.
- P0: portrait/mobile layout (now unblocked — fewer seats = easier
  portrait layout math).
- P0: `client_seed` RNG contribution.

---

## 8. Rule-change log

| Date       | Change                                                             | Source             |
|------------|--------------------------------------------------------------------|--------------------|
| 2026-02    | Initial `MAX_PLAYERS=8`, `STAND_THRESHOLD={2:1..8:5}` set in code. | Phase-2 rewrite    |
| 2026-05    | Table sizes locked to `{30:4, 50:4, 100:5, 250:5}`. 6–8 seats deprecated. Bots configurable & dev-only. Stand-threshold for 5 active confirmed at 3. | User rule update (this doc) |
| 2026-05 v2 | Target **250 deprecated**. Valid target set is now `{30, 50, 75, 100}` (75 replaces 250). Seat map: `{30:4, 50:4, 75:5, 100:5}`. Deck-refill rule added: when the initial 54-card deck exhausts mid-hand, the engine refills with a fresh **52-card jokerless** deck (`state.deck_refills` counter tracks refills per hand). Opponents' cards become public in `STATE_UPDATE.players[*].cards` at `SHOWDOWN` / `PAYOUT` phases only. | User rule update |
