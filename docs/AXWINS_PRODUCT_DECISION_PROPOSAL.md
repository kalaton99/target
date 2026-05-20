# Axwins Product Decision Proposal

## Purpose

This proposal records product decision options for Diceget, Flipget, Tmarget,
and Wallet/Ledger after the local live product-loop reliability pass. It is
planning only. It does not change runtime code, gameplay rules, routes, APIs,
wallet behavior, storage, pricing, settlement, or deployment.

## Boundaries

- Axwins remains the current platform shell and code/UI name.
- Winsget remains the future platform name only.
- Target remains a separate card game.
- Diceget remains a separate dice game.
- Flipget remains a separate coin-flip game.
- Tmarget remains a separate demo prediction market product, not a game.
- Wallet/Ledger remains platform core infrastructure.

Axwins currently uses internal demo credits only. Deposits, withdrawals,
cash-out, crypto, card payments, Telegram Wallet integration, and real-money
trading are not enabled.

## Diceget Current State

Diceget currently works as a 4-seat dice table with a configurable score goal:

- User creates or joins a Diceget table.
- Local demo user can auto-fill demo bot seats.
- Table starts when all 4 seats are filled.
- Current player can roll, hold, or forfeit.
- Two dice are added to the player's score on each roll.
- Holding banks the current score.
- Going over the configured goal busts the player.
- Settlement writes internal demo-credit wallet/ledger records.

The current local product loop is playable and verified through live API checks.
This proposal does not recommend changing the loop before a dedicated Diceget
rule task is opened.

## Diceget Overlap With Target

Diceget is technically isolated from Target at the route/API level:

- Diceget uses `/api/diceget`.
- Target lobby uses `/api/v2/lobby`.
- Target WebSocket uses `/api/v2/ws/table`.
- Diceget does not use Target WebSocket, Target lobby, or Target play routes.

The remaining overlap is product-language and model-language:

- Diceget backend fields use `target_score`.
- Diceget model constants use `SUPPORTED_TARGETS`.
- Diceget bot logic compares score against `target_score`.
- Some tests still assert `target_score`.
- The gameplay idea of reaching or staying under a configured goal can feel
  close to Target's score-target language even though the input randomness and
  player decisions are different.

User-facing UI has already moved away from "TARGET 30" to "Score Goal 30",
which reduces confusion. A future rule pass should decide whether internal
domain vocabulary should follow that change.

## Diceget Rule Direction Options

### Option 1: Score Goal Race

Keep the current roll/hold/bust game and make product identity clearer through
language and naming.

Expected UI wording:

- "Score Goal" or "Dice Goal" instead of "Target".
- "Roll toward the score goal without busting."
- "Hold to bank your score."
- "Auto-fill demo seats" remains local-demo copy.

Expected backend/domain model changes:

- Introduce `score_goal` as the Diceget domain term.
- Keep `target_score` as a temporary API compatibility alias.
- Rename `SUPPORTED_TARGETS` to a Diceget-specific constant such as
  `SUPPORTED_SCORE_GOALS`.
- Update bot helper names from target-oriented names to score-goal names.
- Update tests to assert both compatibility and preferred new naming during
  migration.

Risks and migration concerns:

- API compatibility must be preserved while frontend and tests migrate.
- Ledger reference data should not be rewritten retroactively.
- Existing stored table payloads may contain `target_score`.
- Browser tests and product-loop scripts may need both old and new field names
  during a transition period.

### Option 2: Round-Based Dice Duel

Move Diceget toward fixed rounds where players roll a limited number of times
and compare totals.

Expected UI wording:

- "Round 1 of N"
- "Roll attempt"
- "Round total"
- "Highest total wins the round"

Expected backend/domain model changes:

- Add round counters and per-round roll caps.
- Replace or reduce hold/bust semantics.
- Add new settlement trigger based on round completion.
- Update bot logic to decide when/how to use limited rolls.
- Add new backend and browser loop tests.

Risks and migration concerns:

- Larger gameplay redesign.
- Current live product-loop tests would no longer represent the intended game.
- More frontend state and backend state transitions need to be defined.
- Wallet/ledger settlement timing changes require careful regression tests.

### Option 3: Push-Your-Luck Pot Game

Keep roll/hold/bust but make the core identity about risk, banked points, and a
shared pot rather than a target-like goal.

Expected UI wording:

- "Risk meter"
- "Bank score"
- "Pot pressure"
- "Bust risk"

Expected backend/domain model changes:

- Add explicit banked score or pot progression fields.
- Potentially separate turn score from banked score.
- Adjust winner selection around banked score or pot thresholds.
- Update bot risk strategy around pot/risk state rather than only score goal.
- Add new tests for bank/pot transitions.

Risks and migration concerns:

- Medium-to-large game redesign.
- Higher risk of confusing wallet pot wording with real-money value unless copy
  stays strict about internal demo credits.
- Requires strong UI explanation to avoid making the product feel opaque.

## Recommended Diceget Direction

Recommend **Option 1: Score Goal Race** as the next scoped Diceget decision.

Reasoning:

- It preserves the currently verified local demo loop.
- It avoids changing gameplay rules before the product identity issue is fully
  agreed.
- It directly removes the remaining Target-like naming from Diceget.
- It can be delivered in a compatibility-safe migration.
- It keeps implementation risk lower than a full rule redesign.

Recommended staged order if approved later:

1. Add backend `score_goal` aliases while accepting existing `target_score`.
2. Update Diceget frontend to send/display `score_goal` while tolerating
   `target_score` in responses.
3. Rename internal constants/helpers in Diceget modules only.
4. Update backend tests and browser/product-loop tests.
5. Remove old terminology only after compatibility is proven.

No Diceget rule or naming migration is implemented by this proposal.

## Flipget Decision

Current Flipget local demo loop is acceptable for now:

- It remains a clear 2-seat coin-flip game.
- It supports choosing heads/tails, readying, adding a demo opponent, flipping,
  and showing a result.
- It uses `/api/flipget` and does not use Target routes or Target WebSockets.
- It writes internal demo-credit ledger records only.

Near-term improvements to consider later:

- Improve display names in result copy so winners are easier to read.
- Keep Leave visibility aligned with backend rules before the flip starts.
- Keep spectator action controls disabled unless the viewer is seated.
- Add clearer explanation when a user is watching rather than playing.

These are UX/test follow-ups, not reasons to redesign Flipget now.

## Tmarget Decision

Current Tmarget lifecycle and buy/sell behavior is acceptable for demo use:

- Markets begin as `draft`.
- `open` markets allow signed-in users to buy/sell YES/NO with internal demo
  credits.
- `paused`, `closed`, `resolved`, and `cancelled` states block public trading.
- Admin Markets clearly owns demo-only create/open/pause/close/resolve/cancel
  actions.
- Public market detail explains disabled trading when the market is not open.
- Tmarget remains a demo prediction market product and is not presented as a
  game.

Missing lifecycle UX to consider later:

- More visible explanation for `paused`, `closed`, `resolved`, and `cancelled`
  states once sample data includes those states.
- A compact lifecycle timeline on market detail.
- Clearer difference between "Close" and "Resolve" for non-technical demo
  viewers.
- Portfolio grouping by open, resolved, and cancelled positions.

These should remain demo/internal-credit wording only and must not imply
production trading, oracle readiness, dispute workflow, compliance readiness,
or durable runtime storage.

## Wallet / Ledger Decision

Current Wallet/Ledger wording is consistent across products:

- Wallet is read-only from the UI.
- Ledger entries are created by product actions.
- Balance labels use internal demo-credit wording.
- Disclaimers state that deposits, withdrawals, cash-out, crypto, card
  payments, Telegram Wallet integration, and real-money trading are not enabled.
- Product source labels separate Target, Diceget, Flipget, Tmarget, and demo
  credit/admin entries.

Near-term improvements to consider later:

- Add a short glossary for locked balance versus available balance.
- Add source-module filter examples after more real playtest data exists.
- Keep "sandbox_deposit" surfaced as "demo credit" only; do not use deposit
  action wording in the UI.

## Implementation Files If Diceget Option 1 Is Approved Later

Likely files:

- `frontend/src/pages/DicegetPage.jsx`
- `backend/diceget/models.py`
- `backend/diceget/router.py`
- `backend/diceget/service.py`
- `backend/diceget/bots.py`
- `backend/tests/test_diceget.py`
- `backend/tests/test_product_loop_api_contracts.py`
- `tests/browser_smoke_axwins.py`
- `scripts/check-product-loops-local.ps1`
- Product docs that mention Diceget score goals.

Files that should not be touched for a Diceget naming/rule decision:

- Target gameplay/realtime reducer files.
- Flipget gameplay files, unless shared test names need product-boundary
  updates.
- Tmarget pricing, settlement, repository, or admin guard files.
- Wallet/ledger implementation, unless a Diceget ledger label is explicitly in
  scope.
- `_external_refs`.

## Final Decision Summary

- Keep current product loops as-is for now.
- Treat Diceget identity as the main near-term decision.
- Prefer a staged Score Goal Race naming migration before any broader Diceget
  redesign.
- Keep Flipget stable and focus later on small UX/test refinements.
- Keep Tmarget lifecycle behavior stable and improve lifecycle explanation
  later.
- Keep Wallet/Ledger read-only and internal-demo-credit only.

No runtime behavior is changed by this proposal.
