# Axwins Demo Walkthrough

## Purpose

This document gives presenters a safe, consistent script for showing the current
Axwins demo to internal reviewers or investors. It keeps the product boundaries,
demo-credit limits, and non-production status clear throughout the walkthrough.

## Demo Positioning

Axwins is currently an internal demo-credit environment. It is not production,
not a real-money product, and not a payment or custody system.

> Axwins currently uses internal demo credits only. Deposits, withdrawals, cash-out, crypto, card payments, and real-money trading are not enabled.

Use this framing at the start:

"Axwins is the platform. Target, Diceget, and Flipget are game modules. Tmarget
is a separate demo prediction market product, not a game. Wallet, Ledger,
Transaction History, and Internal Demo Credits are shared platform core
services. Everything shown today uses internal demo credits only."

## Recommended Demo Order

1. Axwins Home / Product Hub.
2. Games section.
3. Diceget quick walkthrough.
4. Flipget quick walkthrough.
5. Target entry point only, without Target gameplay details.
6. Tmarget demo prediction market walkthrough.
7. Wallet / Ledger / Transaction History walkthrough.

## Presenter Talking Points

### Axwins Home / Product Hub

Say:

- "This is the Axwins platform hub."
- "The product structure is intentionally split into Games, Prediction Markets,
  and Platform Core."
- "Target, Diceget, and Flipget are games."
- "Tmarget is separate from games. It is a demo prediction market product."
- "Wallet and Ledger are shared platform services for internal demo credits."

Show:

- Home page product grouping.
- Internal demo-credit disclaimer.
- Games / Prediction Markets / Platform Core sections.

Do not say:

- "Target is the platform."
- "Tmarget is a game."
- "This is production-ready."

### Games Section

Say:

- "The games section contains Target, Diceget, and Flipget."
- "Game-specific behavior is scoped to each game module."
- "The demo-credit wallet is shared across Axwins products, but this does not
  create real-money value."

Show:

- Games page.
- Target, Diceget, and Flipget cards.
- Separate Prediction Markets and Platform Core sections below the games.

### Diceget Quick Walkthrough

Say:

- "Diceget is a four-player dice game inside Axwins."
- "Creating or joining a table reserves internal demo credits."
- "The page explains waiting seats, current turn state, available actions, and
  final results."
- "This is not connected to deposits, withdrawals, or real-money play."

Show:

- Diceget lobby.
- Table create/join controls if the local backend is running.
- Wallet / Transaction History navigation.

Do not change Diceget gameplay during the demo.

### Flipget Quick Walkthrough

Say:

- "Flipget is a two-player coin flip game inside Axwins."
- "Players choose sides, ready up, and the backend returns the demo result."
- "Stake locking and settlement use internal demo credits only."
- "There is no cash-out, card payment, crypto transfer, or real-money behavior."

Show:

- Flipget lobby.
- Table create/join controls if the local backend is running.
- Pre-flip leave visibility and participant-only flip action if relevant.

Do not change Flipget gameplay during the demo.

### Target Entry Point Only

Say:

- "Target is one of the game modules inside Axwins."
- "Target gameplay work is handled separately, so this walkthrough only confirms
  the route and product-card integration."
- "Do not infer Target gameplay bugfix status from this platform walkthrough."

Show:

- Target card or route entry.

Do not discuss unverified Target gameplay details.

### Tmarget Demo Prediction Market Walkthrough

Say:

- "Tmarget is a demo prediction market product, not a game."
- "It uses internal demo credits only."
- "Current runtime storage remains in-memory through `InMemoryTmargetRepository`."
- "Postgres work is planning/test-only. The inactive Postgres skeleton and
  test-only Compose scaffold do not activate durable runtime storage."
- "Admin tooling is demo-only and does not represent production authorization."

Show:

- Tmarget home.
- Markets list.
- A market detail page.
- Portfolio page.
- Demo admin markets page.
- Demo-only resolution/cancellation copy.

Do not say:

- "Postgres persistence is active."
- "Production durable storage is ready."
- "Tmarget has an oracle or dispute workflow."
- "Real-money trading is supported."

### Wallet / Ledger / Transaction History Walkthrough

Say:

- "Wallet and Ledger are Axwins platform core services."
- "The wallet UI is read-only."
- "Transaction History shows internal demo-credit activity from games, Tmarget,
  admin/demo credit entries, and settlement/refund activity."
- "Internal demo credits are not redeemable value."

Show:

- Balance, locked balance, available balance.
- Ledger filters.
- Transaction detail fields.
- Demo-credit disclaimer.

Do not say:

- "Users can deposit."
- "Users can withdraw."
- "Users can cash out."
- "Users can connect a wallet or card."

## What Not To Say During The Demo

Do not say or imply:

- Axwins is production-ready.
- Target is the platform.
- Tmarget is a game.
- Internal demo credits have redeemable value.
- Deposits, withdrawals, cash-out, buy credits, card payments, crypto/Web3,
  Stripe, Telegram wallet linking, or real-money trading are available.
- KYC/AML, compliance, custody, payment processing, oracle, dispute workflow, or
  order book functionality is implemented.
- Tmarget durable runtime storage is active.
- The test-only Postgres Compose scaffold is deployment infrastructure.

## Manual Smoke Checklist Before Showing The Demo

Run or verify:

- `git status --short` is clean.
- `npm run build` passes.
- Backend compile/regression passes if the demo depends on live backend flows.
- Axwins Home opens.
- Games section shows Target, Diceget, and Flipget.
- Prediction Markets section shows Tmarget.
- Platform Core section shows Wallet / Transaction History.
- Diceget lobby opens.
- Flipget lobby opens.
- Tmarget home opens.
- Tmarget markets list opens.
- Tmarget market detail opens.
- Tmarget portfolio opens.
- Tmarget admin markets opens.
- Wallet opens.
- Internal demo-credit disclaimer is visible.
- No Deposit, Withdraw, Cash Out, Buy Credits, Connect Wallet, Add Card, or Link
  Telegram Wallet action is visible.

## Known Limitations To Disclose Honestly

- This is an internal demo-credit environment.
- It is not production.
- Wallet UI is read-only.
- Tmarget active runtime storage remains `InMemoryTmargetRepository`.
- Tmarget durable repository work is planned but not implemented.
- `PostgresTmargetRepository` is inactive/fail-closed.
- `DurableTmargetRepository` is inactive/fail-closed.
- `docker-compose.test.yml` is test-only infrastructure and does not activate
  runtime storage.
- Tmarget has no production oracle, dispute workflow, compliance/KYC/AML layer,
  or real-money market trading.
- Target gameplay status must be verified separately in the Target gameplay
  flow.

## Safe Investor / Internal-Review Framing

Use this framing:

"This demo shows Axwins as a multi-product platform shell with game modules, a
separate demo prediction market product, and shared platform wallet/ledger
surfaces. The purpose is to review product structure, demo UX, and technical
boundaries. It is not a production launch or real-money readiness demo."

## Red Flags Requiring Demo Stop

Stop the demo and investigate if:

- The app fails to build.
- The backend fails required demo flows.
- Git status shows unintended changes.
- A page describes Tmarget as a game.
- A page describes Target as the platform.
- The demo-credit disclaimer is missing from relevant surfaces.
- Wallet shows Deposit, Withdraw, Cash Out, Buy Credits, Connect Wallet, Add
  Card, or Link Telegram Wallet actions.
- Tmarget claims durable runtime storage is active.
- Payment, crypto, real-money, compliance, oracle, dispute, or KYC/AML
  functionality appears enabled.

## Final Demo Close Script

"That completes the Axwins demo walkthrough. The key points are: Axwins is the
platform; Target, Diceget, and Flipget are games; Tmarget is a separate demo
prediction market product; and Wallet/Ledger are shared platform core services.
Everything shown uses internal demo credits only. Deposits, withdrawals,
cash-out, crypto, card payments, and real-money trading are not enabled. The
current state is appropriate for internal demo review, not production launch."
