# Target External Reference Comparison

## Purpose

This document compares the current Axwins Target implementation with the
separate external Target reference repo. The comparison is read-only. It does
not copy code, merge branches, rename products, or change runtime behavior by
itself.

## Current Target Architecture Summary

- Target is a card game inside the current Axwins platform shell.
- Winsget is the future platform name only. Target remains the game name.
- Target entry routes currently land in the Target lobby through `/games/target`,
  `/target`, and `/lobby`.
- Target table play uses `/play/:tableId`.
- Target lobby APIs are namespaced under `/api/v2/lobby/*`.
- Target realtime traffic uses `/api/v2/ws/table/{table_id}`.
- Target state and actions are handled by the backend lobby, realtime bridge,
  and game-engine modules.
- Diceget, Flipget, Tmarget, Wallet, and Ledger must not flow through Target
  table state or Target WebSocket routes.

## External Reference Architecture Summary

The external reference repo was inspected read-only at:

```text
C:\Users\crims\OneDrive\Belgeler\New project\target\_external_refs\target-reference
```

External reference HEAD inspected: `221f6c2`.

The external repo contains a Target-focused frontend, backend game engine,
realtime bridge, lobby flow, wallet-adjacent modules, and a broad test suite.
Its useful material is concentrated around Target game rules, reducer behavior,
deck/RNG handling, realtime gateway tests, reconnect behavior, bot flow, and UI
patterns for card-table play.

## Compatible Ideas

- Keep adding Target-specific browser tests that assert `/games/target`,
  `/target`, `/lobby`, and `/play/:tableId` stay inside Target flow.
- Compare external game-engine tests against current local tests before porting
  any gameplay changes.
- Reuse test ideas for value 2, value 10, joker, deck refill, stale action,
  reconnect, timeout, and bot-driven local demo coverage.
- Reuse UI ideas only after adapting them to the current Axwins platform shell
  and route model.
- Keep Target WebSocket coverage explicit so Diceget, Flipget, and Tmarget do
  not accidentally inherit Target realtime paths.

## Incompatible Ideas

- Do not copy external hosted auth/runtime assumptions.
- Do not copy external deployment assumptions into the Axwins platform.
- Do not copy any code that treats Target as the whole platform.
- Do not copy wallet, payment, live-money, or compliance assumptions.
- Do not copy any frontend branding, metadata, badge, or attribution that is
  not Axwins-owned.
- Do not copy route wiring that would send Diceget, Flipget, or Tmarget through
  Target lobby or Target play state.

## High-Risk Differences

- Axwins is now a multi-product platform shell; the external repo is primarily
  Target-focused.
- Current local Target shares platform auth, internal demo-credit ledger, and
  route boundaries with other products.
- Current local Diceget and Flipget have their own API namespaces and must not
  reuse Target WebSocket routing.
- Current local Tmarget is a demo prediction market product, not a game, and
  must stay outside Target gameplay.
- Future Winsget naming is platform-level only and must not rename Target.

## Recommended Integration Order

1. Keep current Axwins product-loop regression green.
2. Add or keep Target-only browser coverage for lobby entry, table creation,
   table start, play-page load, and WebSocket connection.
3. Compare external Target tests against current backend tests and port missing
   tests first.
4. Compare current and external game-engine modules file by file.
5. Port one Target gameplay fix at a time only when a failing test or confirmed
   bug justifies it.
6. Re-run product namespace scans after each Target change.
7. Re-run backend regression, frontend build, and Target browser tests before
   merging any Target integration work.

## Do Not Copy Blindly

The external repo is reference material only. Do not bulk-copy files, do not
merge branches, do not overwrite current Target modules, and do not import
external assumptions that conflict with Axwins product boundaries.

## Naming Boundary

Winsget is the future platform name. Target remains a game name. Do not rename
Target to Winsget, and do not describe Winsget as a game.

## Decision Summary

No external code was copied. The external reference is useful for Target test
ideas, gameplay-review sequencing, and future file-by-file comparison. Current
work should remain Target-specific and must not affect Diceget, Flipget,
Tmarget, Wallet, Ledger, payment, crypto, SQL, migrations, Postgres runtime
activation, or durable storage.
