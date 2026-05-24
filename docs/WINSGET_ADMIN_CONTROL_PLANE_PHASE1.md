# Winsget Admin Control Plane Phase 1

## Purpose

This is a planning-only document for a future Winsget Admin Control Plane. It does not enable admin runtime features, payment flows, production storage, or real-money behavior.

The control plane should let authorized operators manage product tables, events, tournaments, bot seeding, and operational visibility while keeping player-facing game flows simple and product-specific.

## Product Boundaries

- Target is a card game.
- Diceget is a dice score game.
- Flipget is a coin/round game.
- Jackget is a jackpot-style turn game.
- Tmarget is a prediction-market style demo product.
- Wallet/Ledger is the internal demo-credit accounting surface.

Admin tools must not merge these products into one shared gameplay flow. Admin screens may share layout and audit infrastructure, but each product should keep separate routes, APIs, copy, and state models.

## Roles

- viewer: read-only access to product status, active tables, market lists, and wallet audit views.
- operator: create public joinable demo tables, fill seats with demo bots, start/pause event operations where supported.
- risk_admin: review abnormal table/market/wallet activity, pause risky operations, inspect audit logs.
- super_admin: manage admin role assignment and emergency controls.

Player UI must not expose admin-only controls, bot-management internals, role names, or privileged status fields.

## Phase 1 Scope

Phase 1 should be read-heavy and low-risk:

- Admin table index for Target, Diceget, Flipget, and Jackget.
- Direct table detail links for active and waiting tables.
- Read-only match inspection from outside the game UI.
- Bot configuration visibility for admins only.
- Create public joinable tables for each game using existing product APIs.
- Create bot-filled or partially bot-filled local/demo tables where the current product backend already supports it.
- Read-only Wallet/Ledger audit views for internal demo-credit movement.

Phase 1 should not introduce new gameplay rules or settlement behavior.

## Bot And Table Management

Future admin table creation should support:

- Product selector: Target, Diceget, Flipget, Jackget.
- Product-specific mode/tier fields:
  - Target: target tier 31, 41, 51, 61.
  - Diceget: Sprint 40, Classic 70, Marathon 120.
  - Flipget: Single Flip, Best of 3, Best of 5.
  - Jackget: 2-player, 3-player, or 4-player table.
- Demo bot count, capped by the product's rules.
- Public/private visibility flag for joinable demo tables.
- Optional operator reason.

The normal lobby list should continue to be the player-facing table discovery surface. Admin-created tables should appear as normal rows when public and joinable. No separate quick-table panel should be introduced.

## Tournament And Event Management

Future event management should be staged:

1. Read-only event dashboard for manually curated events.
2. Admin-created event records with name, product, schedule, status, and description.
3. Tournament table generation using product-specific table creation APIs.
4. Bracket/leaderboard display after product-specific results are available.
5. Event archive and audit export.

Event states should be simple at first:

- draft
- scheduled
- live
- paused
- completed
- cancelled

Tournament behavior must not change game rules. It should orchestrate tables and results, not alter Target, Diceget, Flipget, or Jackget mechanics.

## Promotional Pools And Campaigns

Promotional pools or lottery-style campaigns may be planned later from platform revenue, but they must remain planning-only until explicitly approved.

Future design must define:

- funding source
- eligibility rules
- campaign duration
- public user terms
- audit records
- abuse controls
- jurisdiction and legal review

No hidden balance changes, undisclosed prize rules, or player-deceptive campaign mechanics should be allowed.

## Audit Logging Requirements

Every future admin action should emit an immutable internal audit record with:

- actor user id
- actor role
- action name
- target product
- target resource type and id
- timestamp
- reason
- old value
- new value
- request id
- source IP or session metadata where available

Audit logs should be append-only from the application perspective. Any future durable implementation should support export and tamper-evident review.

## Likely Future Files

Frontend:

- `frontend/src/pages/AdminControlPlane.jsx`
- `frontend/src/pages/AdminTablesPage.jsx`
- `frontend/src/pages/AdminEventsPage.jsx`
- `frontend/src/pages/AdminWalletAuditPage.jsx`
- `frontend/src/App.js`

Backend:

- `backend/admin/router.py`
- `backend/admin/service.py`
- `backend/admin/models.py`
- `backend/admin/audit.py`
- product routers for narrow admin-safe table creation hooks, if required

Tests:

- `backend/tests/test_admin_control_plane.py`
- `backend/tests/test_admin_table_creation.py`
- `backend/tests/test_admin_audit_log.py`
- browser tests for player/admin separation

## Risks

- Admin controls leaking into player UI.
- Product-specific rules being flattened into a generic table abstraction.
- Bot controls being exposed to normal users.
- Missing audit records for sensitive actions.
- Admin actions creating tables that cannot be joined or started.
- Promotional campaigns being interpreted as redeemable value before legal/compliance approval.

## Non-Goals

- No runtime admin panel in this pass.
- No payment, crypto, Telegram Wallet, or real-money behavior.
- No SQL/Postgres/migration/durable-storage activation.
- No KYC/AML implementation.
- No hidden balance edits.
- No gameplay rule changes.
- No hidden market-result manipulation.

## Test Strategy For Future Implementation

When implementation is approved, tests should cover:

- Role-based access for each admin route.
- Player cannot see or call admin controls.
- Admin-created tables appear in normal lobbies only when public and joinable.
- Bot caps are enforced per product.
- Admin actions produce audit records.
- Event/tournament setup does not change product rules.
- Wallet audit pages are read-only.
- Product namespaces remain separate.

