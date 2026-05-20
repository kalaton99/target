# Axwins Product Identity Boundary Audit

## Purpose

This audit records product identity and namespace boundaries for the current
Axwins demo after the local reliability pass. It is documentation only and does
not change gameplay, routes, APIs, wallet behavior, storage, pricing,
settlement, or deployment behavior.

## Current Product Boundaries

- Axwins remains the current platform shell and code/UI name.
- Winsget is the future platform name only. No runtime rebrand is performed.
- Target is one game inside the platform, not the platform name.
- Diceget is a separate dice game.
- Flipget is a separate coin-flip game.
- Tmarget is a separate demo prediction market product, not a game.
- Wallet, Ledger, Transaction History, and Internal Demo Credits are platform
  core services shared by Axwins products.

Axwins currently uses internal demo credits only. Deposits, withdrawals,
cash-out, crypto, card payments, and real-money trading are not enabled.

## Diceget Product Decision Note

### Current Diceget Mechanic

Diceget currently implements a 4-player dice table:

- A user creates or joins a Diceget table.
- Supported table goals are 30, 50, 75, and 100.
- Local demo play can auto-fill remaining seats with demo bots.
- When the table is active, the current player can roll, hold, or forfeit.
- Rolls add two dice to the player's score.
- A player can hold to bank the score.
- A player busts when the score goes over the configured goal.
- Settlement uses internal demo credits only through the shared wallet/ledger.

### Current Overlap With Target

The user-facing Diceget UI now says "Score Goal" instead of "Target", but
several internal implementation names still use `target_score`:

- Frontend table creation sends `target_score`.
- Backend request and model fields use `target_score`.
- Backend constants use `SUPPORTED_TARGETS`.
- Bot hold logic compares score against `target_score`.
- Tests assert `target_score` payload behavior.

This is a terminology overlap, not current route or runtime namespace mixing.
Diceget remains under `/api/diceget` and does not use Target lobby, Target play,
or Target WebSocket routes.

### Alternative Diceget Rule Directions

1. **Score Goal Race**
   - Keep the current roll/hold/bust loop.
   - Rename internal and public Diceget vocabulary from `target_score` to
     `score_goal` over a compatibility window.
   - This is the lowest-risk direction because it preserves the current tested
     loop and removes Target-like naming.

2. **Round-Based Dice Duel**
   - Convert Diceget into short rounds where players roll a fixed number of
     times and compare totals.
   - This would reduce overlap with Target naming but requires larger rule,
     UI, service, wallet, and test changes.

3. **Push-Your-Luck Pot Game**
   - Keep roll/hold/bust, but emphasize risk rounds, banked score, and pot
     progress rather than a goal number.
   - This may improve product identity, but it still needs explicit rule and UI
     design before implementation.

### Recommended Direction

Prefer **Score Goal Race** first:

- It preserves current product-loop tests.
- It avoids broad gameplay redesign.
- It directly addresses the confusing Target-like wording.
- It can be staged safely by adding `score_goal` aliases while keeping
  `target_score` compatibility until clients/tests migrate.

### Files That Would Need Changing If Approved Later

- `frontend/src/pages/DicegetPage.jsx`
- `backend/diceget/models.py`
- `backend/diceget/router.py`
- `backend/diceget/service.py`
- `backend/diceget/bots.py`
- `backend/tests/test_diceget.py`
- `backend/tests/test_product_loop_api_contracts.py`
- `tests/browser_smoke_axwins.py`
- Any documentation that describes Diceget table goals.

No such rename or rule change is implemented by this audit.

## Tmarget UI Wording And Lifecycle Audit

Tmarget is consistently presented as a demo prediction market product and not a
game. Current wording separates public market views from demo admin lifecycle
controls:

- Public Tmarget home: describes Tmarget as a separate product module.
- Public market list: describes markets as demo prediction markets using
  internal demo credits.
- Market detail: allows YES/NO demo-credit buy/sell only when a backend market
  is open and the user is signed in.
- Admin Markets: clearly labels demo-only market creation and lifecycle
  controls using `X-Axwins-Demo-Admin: true`.

Lifecycle wording is present for:

- `draft`: buy/sell is disabled with "Open this demo market before buying
  YES/NO." Draft detail also offers "Open Market Now" and links to Admin
  Markets.
- `open`: demo-credit buy/sell controls are enabled for signed-in users.
- `paused`: admin copy says pause temporarily stops trading without resolving;
  public buy/sell is disabled because the market is not open.
- `closed`: admin copy says close stops trading before resolution; public
  buy/sell is disabled because the market is not open.
- `resolved`: admin resolve copy says it sets the selected outcome and runs
  demo settlement.
- `cancelled`: admin cancel copy says it triggers demo-credit refund handling.

No Tmarget wording claims production trading, oracle readiness, dispute
workflow readiness, compliance readiness, real-money support, or durable
runtime storage activation.

## Wallet / Ledger Wording Audit

Wallet and Ledger wording is aligned with internal demo-credit boundaries:

- Wallet page header labels it as "Internal demo-credit core service."
- The main Wallet / Ledger page states the exact internal demo-credit
  disclaimer.
- Wallet and transaction history are described as read-only.
- Game actions and Tmarget demo market actions create ledger entries
  automatically.
- Wallet summary uses "Internal demo credits", "Locked Balance", and
  "Available internal demo credits."

The wallet UI does not expose Deposit, Withdraw, Cash Out, Buy Credits, Connect
Wallet, Add Card, or Telegram Wallet actions.

## Product Namespace Separation

Current namespace separation is intact:

- Target lobby and Target table WebSocket:
  - `/api/v2/lobby`
  - `/api/v2/ws/table`
- Diceget:
  - `/api/diceget`
- Flipget:
  - `/api/flipget`
- Tmarget:
  - `/api/tmarget`
- Wallet / Ledger:
  - `/api/platform/wallet`
  - `/api/platform/ledger`

The local product-loop checker exercises these namespaces separately and fails
if the backend is not reachable. Diceget, Flipget, and Tmarget do not use Target
gameplay routes or Target WebSocket routes.

## Remaining Product Decisions

- Decide whether Diceget should keep the current Score Goal Race mechanic or
  move toward a more distinct dice rule set.
- If Score Goal Race is approved, plan a compatibility-safe `target_score` to
  `score_goal` naming migration.
- Decide whether Tmarget public pages should expose more lifecycle education
  for paused, closed, resolved, and cancelled markets after more markets exist.
- Decide whether Wallet / Ledger should add more explanatory filtering by
  product source after more real demo playtest data exists.

## Explicit No-Change Confirmation

This audit does not:

- Rebrand Axwins to Winsget.
- Rename Target.
- Change Target, Diceget, Flipget, or Tmarget product behavior.
- Change wallet/ledger behavior.
- Add payment, crypto, Telegram Wallet, real-money, SQL, Postgres, migration,
  durable storage, KYC/AML, oracle, dispute, order book, or production trading
  behavior.
