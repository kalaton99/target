# Diceget / Flipget Playtest QA Audit

## 1. Summary

This audit reviews the current Diceget and Flipget implementation from a
player-facing and demo-readiness perspective. It is based on source inspection
of frontend pages, backend services/routers, wallet bridges, wallet model docs,
tests, and Axwins platform docs.

No runtime browser playthrough was performed in this pass. Items that require a
running frontend/backend session are marked as needing manual runtime
verification.

Top findings:

- High: Diceget can enter `showdown` from a final roll/bust path without the
  router settling the table, which may leave the UI without result/deal-again
  controls.
- Medium: Diceget and Flipget Deal Again endpoints create a new table before
  wallet locking and do not catch wallet bridge errors the same way create/join
  endpoints do.
- Medium: Flipget frontend hides Leave once the table reaches `ready`, even
  though backend pre-flip leave is still allowed before `flipping`/`settled`.
- Medium: Flipget frontend can enable Flip for a signed-in spectator when the
  table is ready; backend rejects non-seated users, but the UI affordance can be
  confusing.
- Low/Polish: Locked demo-credit behavior is documented and visible in Wallet,
  but game pages do not explain the exact stake-locking lifecycle inline.

## 2. Scope

Reviewed files:

- `frontend/src/pages/DicegetPage.jsx`
- `frontend/src/pages/FlipgetPage.jsx`
- `backend/diceget/models.py`
- `backend/diceget/service.py`
- `backend/diceget/router.py`
- `backend/diceget/wallet_bridge.py`
- `backend/diceget/WALLET_MODEL.md`
- `backend/flipget/models.py`
- `backend/flipget/service.py`
- `backend/flipget/router.py`
- `backend/flipget/wallet_bridge.py`
- `backend/flipget/WALLET_MODEL.md`
- `backend/tests/test_diceget.py`
- `backend/tests/test_flipget.py`
- `docs/AXWINS_RELEASE_CHECKLIST.md`
- `docs/AXWINS_WALLET_LEDGER_MODEL.md`

Out of scope:

- Target gameplay.
- Diceget/Flipget gameplay rule changes.
- Tmarget pricing, settlement, repository, storage, or admin guard behavior.
- Wallet/ledger behavior changes.
- Any live payment, deposit, withdrawal, crypto/Web3, card, Telegram wallet, or real-money behavior.

## 3. Diceget Findings

### Lobby Flow

Status: generally clear.

- The lobby identifies Diceget as a "4-player dice game inside Axwins."
- The target cards show supported targets: 30, 50, 75, 100.
- The required internal demo-credit disclaimer is visible.
- Navigation back to Axwins, Games, Tmarget, and Wallet is visible.
- Empty state says no active Diceget tables exist and prompts table creation.

Polish:

- The stake input is present, but the lobby does not explicitly state that the
  stake is locked from the user's internal demo-credit wallet when creating or
  joining. Wallet docs cover this, but first-time players may not infer it.

### Table Creation / Join Flow

Status: mostly clear, with wallet clarity caveat.

- Creating a table uses `POST /api/diceget/tables`.
- Joining a table uses `POST /api/diceget/tables/{table_id}/join`.
- Backend create/join opens the wallet if needed, then locks stake through
  `lock_diceget_stake()`.
- Join rollback path exists if wallet locking fails after join.
- Waiting seats are shown via seated cards plus a "Waiting for N more players"
  message.

Needs manual runtime verification:

- How insufficient demo-credit errors render from the API in the browser. The
  frontend displays raw error messages/codes, which may be terse but should be
  readable enough for a demo if the backend error is clear.

### Start / Roll / Hold / Forfeit / Leave Flow

Status: action availability is mostly clear.

- Start is disabled until four seats are present.
- Roll/Hold/Forfeit are enabled only for the current user on their active turn.
- Active player is highlighted by border/color.
- Roll history displays dice values, total, score transition, and bust marker.
- Leave is available during `waiting` state.

High finding:

- Diceget service can transition to `showdown` from `_advance_turn()` after a
  final roll/bust. The router settles after `hold` and `forfeit` when status is
  `showdown`, but the `roll` route returns the table directly and does not call
  `settle()` if the final action produces `showdown`.
- User impact: if the final active player busts by rolling, the table may show
  `showdown` without the settled result panel or Deal Again button.
- Evidence: `DicegetService.roll()` calls `_advance_turn(table)` on bust;
  `_advance_turn()` sets `table.status = "showdown"` when no eligible players
  remain; `backend/diceget/router.py` only auto-settles in `hold` and
  `forfeit` routes.
- Risk level: High.
- Needs manual runtime verification: reproduce a table where the final action is
  a bust roll and confirm whether the UI gets stuck at `showdown`.

### Deal Again Flow

Current behavior from code:

- `DicegetService.deal_again()` requires the prior table to be `settled`.
- It creates a new waiting table with the same target and stake.
- The router then locks the requesting user's stake for the new table.
- Tests verify service-level Deal Again does not duplicate settlement.

Medium finding:

- The Diceget Deal Again router creates the new table before wallet locking and
  does not catch `DicegetWalletError`. Create/join endpoints catch wallet errors
  and rollback or leave as appropriate; Deal Again does not mirror that pattern.
- User impact: if the new stake lock fails, the API may return an unclear error
  and may leave a new table in service memory.
- Risk level: Medium.
- Needs manual runtime verification: attempt Deal Again with insufficient
  available demo credits.

### Wallet / Ledger Exposure

Confirmed from code/docs:

- Create/join locks stake with `source_module="diceget"` and
  `diceget_join_lock`.
- Pre-game leave unlocks with `diceget_cancel_unlock`.
- Active/showdown/settled states are non-refundable.
- Final settlement consumes locked stake and pays winners with
  `diceget_win_payout`.
- Settlement uses deterministic per-user payout keys.
- No live payment behavior exists.

UX note:

- Wallet locking is accurate but not deeply explained on the Diceget page.
  Consider adding concise helper copy later: "Stake is reserved from internal
  demo credits while the table is waiting/active."

## 4. Flipget Findings

### Lobby Flow

Status: generally clear.

- The lobby identifies Flipget as a "2-player coin flip game inside Axwins."
- The required internal demo-credit disclaimer is visible.
- Navigation back to Axwins, Games, Tmarget, and Wallet is visible.
- Empty state says no active Flipget tables exist and prompts creation.

Polish:

- The stake input is present, but the lobby does not explicitly state that the
  stake is locked from internal demo credits when creating or joining.

### Table Creation / Join Flow

Status: mostly clear.

- Creating a table uses `POST /api/flipget/tables`.
- Joining a table uses `POST /api/flipget/tables/{table_id}/join`.
- Backend create/join opens the wallet if needed, then locks stake through
  `lock_flipget_stake()`.
- Duplicate users and third players are rejected by backend service/tests.
- Seat cards show open/occupied seats and ready state.

Needs manual runtime verification:

- How insufficient demo-credit errors render from the API in the browser.

### Choose-Side / Ready / Flip / Leave Flow

Status: side and ready controls are understandable, with two UX gaps.

- Heads/tails choices are visible as "Choose heads" and "Choose tails."
- Ready button is disabled until the current user has selected a side.
- Flip button is disabled until the table is ready.
- Result screen shows result and winner after settlement.

Medium finding:

- Leave is only rendered in the frontend when `table.status === "waiting"`.
  Backend allows leave until `flipping` or `settled`, including `ready` state.
- User impact: once both players are ready but before flip, a player may have no
  visible Leave option even though backend pre-flip leave/refund is allowed.
- Risk level: Medium.
- Needs manual runtime verification: create a ready table and confirm whether
  leaving is needed/expected before flip.

Medium finding:

- `canFlip` checks table readiness but not whether the signed-in user is seated.
  A signed-in spectator viewing a ready table may see an enabled Flip Coin
  button; backend rejects non-seated users with `PLAYER_NOT_SEATED`.
- User impact: confusing action affordance and avoidable error.
- Risk level: Medium.
- Needs manual runtime verification: view a ready Flipget table as a third
  signed-in user.

Polish:

- When both seats are filled but sides/ready are incomplete, the UI relies on
  seat cards and disabled controls. A short "Waiting for side selection/ready"
  state message would make the table easier to read.
- Result text uses raw result/user id. It is understandable for engineering QA,
  but a demo could benefit from friendlier display names.

### Deal Again Flow

Current behavior from code:

- `FlipgetService.deal_again()` requires the prior table to be `settled`.
- It creates a new waiting table with the same stake.
- The router then locks the requesting user's stake for the new table.
- Tests verify service-level Deal Again does not duplicate settlement.

Medium finding:

- The Flipget Deal Again router creates the new table before wallet locking and
  does not catch `FlipgetWalletError`. Create/join endpoints catch wallet errors
  and rollback or leave as appropriate; Deal Again does not mirror that pattern.
- User impact: if the new stake lock fails, the API may return an unclear error
  and may leave a new table in service memory.
- Risk level: Medium.
- Needs manual runtime verification: attempt Deal Again with insufficient
  available demo credits.

### Wallet / Ledger Exposure

Confirmed from code/docs:

- Create/join locks stake with `source_module="flipget"` and
  `flipget_join_lock`.
- Pre-flip leave unlocks with `flipget_cancel_unlock`.
- Flipping/settled states are non-refundable.
- Final settlement consumes locked stake and pays the winner with
  `flipget_win_payout`.
- Settlement uses deterministic per-user payout keys.
- No live payment behavior exists.

UX note:

- Wallet locking is accurate but not deeply explained on the Flipget page.

## 5. Cross-Product Findings

Confirmed:

- Tmarget is linked in navigation as a separate top-level product and is not
  mixed into game action panels.
- Target gameplay files were not inspected for changes or modified in this pass.
- Wallet link/copy is consistent with read-only internal demo-credit policy.
- Internal demo-credit disclaimer is present on Diceget and Flipget pages.
- No page inspected exposes Deposit, Withdraw, Cash Out, Buy Credits, Connect
  Wallet, Add Card, or Link Telegram Wallet buttons.
- No live payment, crypto/Web3, Stripe/card, Telegram wallet, or real-money
  feature is implemented by Diceget/Flipget code paths.

Needs manual runtime verification:

- Browser/mobile layout for the live table states after real data loads.
- Exact backend-offline error readability in the game lobbies.
- Wallet transaction entries after a full create/join/leave/settle demo flow.

## 6. Findings by Risk Level

### Critical

- None found from source inspection.

### High

- Diceget may remain in `showdown` without settlement/result UI when the final
  action is a bust roll.

### Medium

- Diceget Deal Again wallet lock failure path may leave a new table and return
  an unclear error.
- Flipget Deal Again wallet lock failure path may leave a new table and return
  an unclear error.
- Flipget frontend hides Leave in `ready` state even though backend allows
  pre-flip leave/refund before `flipping`.
- Flipget frontend can enable Flip Coin for a signed-in spectator on a ready
  table; backend rejects the action.

### Low

- Insufficient demo-credit errors may be terse because frontend displays raw API
  error messages/codes.
- Diceget/Flipget pages do not explain stake locking inline beyond the general
  internal demo-credit disclaimer.

### Polish

- Add clearer waiting guidance for Flipget when two players are seated but sides
  or ready states are incomplete.
- Improve result display names for Flipget.
- Consider a small "reserved stake" helper line near stake inputs for both
  games.

## 7. Recommended Fix Order

1. Diceget final-roll showdown settlement path: ensure roll route settles when
   `_advance_turn()` moves the table to `showdown`.
2. Deal Again wallet error handling: mirror create/join rollback/error behavior
   for Diceget and Flipget.
3. Flipget Leave visibility: allow visible leave before `flipping`/`settled` or
   clarify why `ready` is treated as committed in UI.
4. Flipget spectator Flip affordance: require `mySeat` before enabling Flip
   Coin.
5. Improve demo-credit and locked-stake helper copy near stake inputs.
6. Improve error display for insufficient demo credits and backend failures.
7. Runtime playtest pass with local backend and at least desktop/mobile browser
   checks.

## 8. Explicit No-Change Confirmations

- No gameplay changed in this audit.
- No wallet behavior changed in this audit.
- No Tmarget behavior changed in this audit.
- No payment, crypto, withdrawal, deposit, or real-money behavior was added.
- No source files were changed by this report.
