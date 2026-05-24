# Tmarget Market Admin Roadmap

## Purpose

This is a planning-only roadmap for future Tmarget market operations and admin lifecycle controls. Tmarget remains a prediction-market style demo product using internal demo credits unless future compliance and payment scope is explicitly approved.

This document does not implement runtime changes.

## Current Product Boundary

Tmarget is separate from Target, Diceget, Flipget, and Jackget. It should not use game terminology or game table mechanics. It may share platform auth, Wallet/Ledger, audit, and future admin infrastructure.

## Planned Market Lifecycle

The future lifecycle should remain explicit:

- draft: market exists but public trading is disabled.
- open: YES/NO demo-credit buying and selling is enabled.
- paused: market is visible but trading is temporarily disabled.
- closed: trading is stopped while awaiting resolution.
- resolved: final outcome is set and demo settlement is complete.
- cancelled: market is voided and eligible demo-credit refunds are handled.

Lifecycle transitions should be role-gated and audit-logged.

## Admin Moderation Controls

Future controls should include:

- create draft market
- open market
- pause market
- close market
- resolve market
- cancel market
- correct metadata
- hide abusive market from public lists
- restore hidden market after review

Metadata correction should be restricted to fields that do not change the economic meaning of active positions unless a visible correction notice is attached.

## Outcome Integrity

Do not design hidden user-deceptive outcome manipulation.

Future resolution must require:

- visible market rules or resolution criteria
- resolver identity
- resolver notes
- timestamp
- audit record
- user-visible outcome state after resolution

If a market needs correction after opening, users should see a public correction note where appropriate.

## Audit Logging

Every future admin market action should record:

- actor user id
- actor role
- action
- market id
- old status
- new status
- changed fields
- reason
- timestamp
- request id

Audit logs should also capture failed admin attempts, permission failures, and invalid lifecycle transitions.

## Operational Safety

Admin operations should be designed fail-closed:

- Trading disabled when backend state is unclear.
- Resolution blocked if required notes are missing.
- Cancellation requires reason.
- Metadata edits on open markets require explicit confirmation.
- Hidden markets remain accessible by direct admin link for review.
- Public lists should not expose hidden abusive markets.

## Phased Rollout

### Phase 0: Documentation

- Keep current demo-credit runtime behavior.
- Document lifecycle states, moderation controls, and audit requirements.
- No runtime admin expansion.

### Phase 1: Read-Only Admin Review

- Admin market list with lifecycle filters.
- Market detail inspection.
- Trade/position summary.
- Audit log viewer if audit infrastructure exists.

### Phase 2: Safer Lifecycle Controls

- Open, pause, close, cancel, resolve.
- Required reason fields.
- Audit log writes.
- Clear public disabled-state copy.

### Phase 3: Metadata Moderation

- Correct typo-level metadata.
- Hide/restore abusive markets.
- Public correction notes.
- Reviewer workflow.

### Phase 4: Production Review

- Legal/compliance review.
- Market rules and user terms.
- Dispute and appeal process.
- Data retention policy.
- Monitoring and alerting.

## Likely Future Files

Frontend:

- `frontend/src/pages/TmargetAdminMarketsPage.jsx`
- `frontend/src/pages/TmargetAdminMarketDetail.jsx`
- `frontend/src/components/tmarget/MarketLifecycleControls.jsx`
- `frontend/src/components/tmarget/MarketAuditLog.jsx`

Backend:

- `backend/tmarget/admin_router.py`
- `backend/tmarget/admin_service.py`
- `backend/tmarget/audit.py`
- `backend/tmarget/moderation.py`
- future repository methods for audit and hidden-market state

Tests:

- `backend/tests/test_tmarget_admin_lifecycle.py`
- `backend/tests/test_tmarget_admin_audit.py`
- `backend/tests/test_tmarget_market_moderation.py`
- browser tests for public/admin separation

## Risks

- Admin controls changing market meaning without user-visible notice.
- Hidden outcome manipulation.
- Missing audit logs.
- Public UI implying real-money trading before approval.
- Tmarget being described as a game.
- Durable repository activation before storage scope is approved.

## Non-Goals

- No runtime admin expansion in this pass.
- No oracle integration.
- No order book.
- No production settlement.
- No dispute flow.
- No payment or real-money behavior.
- No SQL/Postgres/migration/durable-storage activation.
- No hidden market-result manipulation.

## Test Strategy For Future Implementation

Future implementation should test:

- Valid and invalid lifecycle transitions.
- Required admin reasons.
- Audit log creation for every admin action.
- Permission boundaries between viewer, operator, risk_admin, and super_admin.
- Public market pages reflect draft/open/paused/closed/resolved/cancelled states clearly.
- Hidden markets do not appear in public lists.
- Metadata corrections create public notes where needed.
- Product namespace isolation from games.

