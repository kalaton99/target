# Target Gameplay Integration Plan

## Purpose

This document plans a future, reviewed Target-only integration pass using the
separate external Target reference repo. It does not copy code, change runtime
behavior, rename products, or merge external modules.

## Current Target Implementation Summary

- Target is a card game inside the current Axwins platform shell.
- Future platform naming direction is Winsget, but Winsget is the platform name
  and must not replace the Target game name.
- Current local Target flow uses the platform lobby routes under
  `/api/v2/lobby/*` and the Target realtime route
  `/api/v2/ws/table/{table_id}`.
- Target shares platform-level auth, wallet, ledger, and internal demo-credit
  infrastructure with Diceget, Flipget, and Tmarget.
- Diceget, Flipget, and Tmarget must remain outside Target routes, state,
  WebSockets, and gameplay assumptions.

## External Reference State

The external repo was inspected read-only at:

```text
C:\Users\crims\OneDrive\Belgeler\New project\_external_target_reference
```

Inspected external HEAD: `221f6c2`.

No external files were copied into the active platform repo.

## Useful External Parts

External Target areas that may be useful after review:

- `backend/game_engine/cards.py`
- `backend/game_engine/deck.py`
- `backend/game_engine/reducer.py`
- `backend/game_engine/rng.py`
- `backend/game_engine/scoring.py`
- `backend/game_engine/turn_engine.py`
- `backend/game_engine/types.py`
- `backend/game_engine/view_filter.py`
- `backend/realtime_v2/bridge.py`
- `backend/realtime_v2/gateway.py`
- `backend/realtime_v2/protocol.py`
- Target-focused tests such as phase progression, reconnect, timeout, deck
  refill, fairness, bot stress, and WebSocket wiring tests under
  `backend/tests/`.
- Frontend Target-only components such as `PlayPage.jsx`, `LobbyPage.jsx`, and
  game display components if they are reviewed against the current Axwins UI
  and route model.

## Risky External Parts

These areas must not be copied blindly:

- External hosted OAuth/runtime/auth modules.
- Hosted deployment assumptions, badges, attribution, or tool-specific runtime
  integration.
- Any code that assumes Target is the whole platform.
- Any route wiring that would make Diceget, Flipget, or Tmarget flow through
  Target lobby, Target table state, or Target WebSocket routes.
- Any wallet, payment, compliance, or live-money assumptions.
- Any package or build dependency that is not required by reviewed Target game
  behavior.

## Files Or Modules That Might Be Reusable Later

Future review may compare these external modules against current local Target
files before any port:

- `backend/game_engine/*`
- `backend/realtime_v2/*`
- `backend/lobby/router.py`
- `backend/lobby/service.py`
- `frontend/src/pages/PlayPage.jsx`
- `frontend/src/pages/LobbyPage.jsx`
- `frontend/src/components/game/*`
- External Target regression tests under `backend/tests/test_*target*`,
  `backend/tests/test_*phase*`, `backend/tests/test_*realtime*`, and
  `backend/tests/test_*bot*`.

Reusable code must be ported in small commits with tests, not bulk-copied.

## Files Or Modules That Must Not Be Copied

Do not copy:

- External hosted OAuth/auth runtime folders.
- Hosted deployment files or hosted URL assumptions.
- Attribution, badge, or tool-specific frontend metadata.
- External wallet/payment/compliance code or copy that implies real-money
  readiness.
- External package dependencies unless a focused Target test proves the need.
- Any module that would rename Target, make Target the platform, or conflict
  with Winsget as the future platform name.

## Staged Integration Plan

1. Keep current Axwins product-loop browser tests green.
2. Add Target-specific browser readiness tests for lobby, table create/join,
   WebSocket connection, start, turn progression, reconnect, and leave/back
   navigation.
3. Compare external Target tests against current Target tests and port only
   missing test cases first.
4. Compare `game_engine` behavior file-by-file in a branch.
5. Port one Target gameplay fix at a time with a targeted backend test and a
   browser regression when the UI/realtime flow is affected.
6. Run product-boundary scans after every Target change to ensure Diceget,
   Flipget, and Tmarget do not inherit Target routes or WebSocket paths.
7. Keep wallet/payment behavior internal-demo-credit only.
8. Complete a rollback review before any large Target gameplay replacement.

## Required Tests Before Integration

Before any external Target code is integrated:

- Current backend regression must pass.
- Current browser product-loop smoke tests must pass.
- Target lobby route tests must pass.
- Target WebSocket route tests must pass.
- Target phase progression and reconnect tests must pass.
- Product namespace tests must confirm Diceget, Flipget, and Tmarget do not use
  Target endpoints.
- Wallet/Ledger non-regression tests must pass.
- Wording scans must confirm Target remains a game and Winsget remains the
  future platform name only.

## Rollback Plan

- Port Target changes in small commits.
- Keep the previous clean checkpoint tag available.
- Revert the last Target-specific commit if a regression appears.
- Do not revert unrelated Diceget, Flipget, Tmarget, wallet, or docs changes.
- Re-run backend regression, frontend build, and browser product-loop tests
  after rollback.

## Naming Warning

Target remains a game name. Winsget is the future platform name. Do not rename
Target to Winsget, and do not describe Winsget as a game.

## Decision Summary

The external repo is a Target gameplay reference only. No external code is
integrated in this phase. The current priority remains stable local product
loops for Target, Diceget, Flipget, Tmarget, and Wallet/Ledger without adding
real-money, payment, crypto, SQL, migration, Postgres runtime activation, or
durable-storage behavior.
