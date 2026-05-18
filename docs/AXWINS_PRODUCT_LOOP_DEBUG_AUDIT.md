# Axwins Product Loop Debug Audit

## Purpose

This note records the local product-loop debugging pass for the current Axwins
platform shell. It is an audit note only; runtime naming remains Axwins for now.
Future platform naming direction is Winsget, but Target remains a game inside
the platform and must not be renamed to Winsget.

## Current Naming Boundary

- Current code/UI name: Axwins.
- Future platform name: Winsget.
- Winsget is the future platform name, not a game name.
- Target remains a card game.
- Diceget remains a separate dice game.
- Flipget remains a separate coin-flip game.
- Tmarget remains a separate demo prediction market product, not a game.

## Findings

- Target routes intentionally land in Target lobby/play surfaces.
- Diceget uses `/api/diceget/*` and does not call Target lobby or Target
  WebSocket routes.
- Flipget uses `/api/flipget/*` and does not call Target lobby or Target
  WebSocket routes.
- Tmarget uses `/api/tmarget/*` and remains separate from games.
- Wallet/Ledger uses `/api/platform/*`.
- Backend API checks confirmed Diceget roll, Flipget two-user flip, and Tmarget
  YES buy flows work with internal demo credits.

## Fixed Now

- Added a browser smoke test covering route isolation, Diceget roll, Flipget
  controlled blocked state, and Tmarget demo YES buy.
- Clarified Flipget's single-user blocked state and fixed the open second-seat
  label so it renders as Seat 2 instead of another Seat 1.

## Deferred

- Flipget still requires two participants to complete a coin flip. This is the
  current game rule. A single-user demo opponent should be a separate scoped
  change if the product owner wants one.
- Tmarget markets must be open before YES/NO demo-credit buying is enabled.
  This is current lifecycle behavior. The browser smoke test creates and opens a
  market before buying.
- Full Axwins to Winsget rebrand is deferred. Only future naming direction is
  documented here and in the roadmap.

## Safety Result

No real-money, payment, crypto, deposit, withdrawal, SQL, migration, Postgres
runtime activation, durable storage, or external wallet behavior was added.

