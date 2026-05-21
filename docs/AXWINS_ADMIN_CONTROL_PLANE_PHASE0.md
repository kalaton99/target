# Axwins Admin Control Plane Phase 0

## Purpose

This is a planning document for a future Axwins admin control plane. It does not
enable runtime admin behavior, add an admin panel, change product rules, or add
payment, crypto, Telegram Wallet, real-money, SQL, Postgres, migration, durable
storage, KYC/AML, oracle, dispute, order book, or production trading behavior.

Winsget remains the future platform name only. Axwins remains the current
code/UI shell name until a separate rebrand task is explicitly opened.

## Product Boundaries

- Target is a game.
- Diceget is a separate dice game.
- Flipget is a separate coin-flip game.
- Tmarget is a separate demo prediction market product, not a game.
- Wallet, Ledger, Transaction History, and Internal Demo Credits are platform
  core services.
- Admin controls must respect these domains and must not merge routes, API
  namespaces, gameplay state, WebSocket behavior, market lifecycle, or wallet
  ledger behavior across products.

## Phase 0 Positioning

Phase 0 is design and governance planning only. Any future implementation must
be separately scoped, reviewed, tested, and audited before it is enabled.

Admin tools should be treated as operational controls for internal demo
environments first. They must not imply production readiness, redeemable value,
real-money trading, payment acceptance, withdrawal capability, or compliance
readiness.

## Proposed Admin Roles

- `viewer`: Read-only access to dashboards, table state, market state, and audit
  records.
- `operator`: Can perform allowed operational actions such as starting, pausing,
  or ending configured demo events.
- `risk_admin`: Can review wallet/ledger audit views, risk flags, and
  operational limits, without hidden balance mutation.
- `super_admin`: Can manage admin configuration and emergency controls, subject
  to mandatory audit logging and separate approval policy.

Role names are planning labels only. They are not implemented runtime roles.

## Planned Admin Actions

Future admin actions may include:

- Create, start, pause, and end demo events.
- Tournament setup for game modules.
- Live match viewing by direct table or market link.
- Bot configuration visibility only to admins.
- Target local/demo bot capacity controls.
- Flipget demo opponent controls.
- Tmarget market lifecycle controls:
  - draft
  - open
  - paused
  - closed
  - resolved
  - cancelled
- Wallet and Ledger read-only audit views.

Admin actions must be explicit, role-gated, and auditable. No hidden product
state changes should be possible.

## Product-Specific Notes

### Target

Target admin controls should preserve the existing engine, reducer, RNG,
fairness, protocol, payout behavior, and hand lifecycle. Local/demo bot controls
may expose the current capacity model:

- Target 30 and Target 50: one human plus up to three demo bots.
- Target 75 and Target 100: one human plus up to four demo bots.

Any production-oriented bot policy must remain separate from local demo
capacity.

### Diceget

Diceget admin controls should stay under Diceget-specific routes and terminology.
Admin views may show score goal, table seats, bot seats, current turn, rolls,
holds, forfeits, and final table state.

### Flipget

Flipget admin controls should respect the two-participant rule. Local demo
controls may show whether the table has one human and one demo opponent. A
second demo opponent must remain blocked.

### Tmarget

Tmarget admin controls should remain market-lifecycle controls for demo
prediction markets, not game controls. Admin tools may expose draft/open/paused/
closed/resolved/cancelled state, direct market links, and demo-credit trade
activity. They must not imply oracle readiness, dispute readiness, order-book
support, production settlement, or real-money trading.

### Wallet / Ledger

Wallet and Ledger admin surfaces should be read-only audit views in Phase 0.
They may show spendable, reserved, and total internal demo credits; transaction
history; source module; reason; timestamps; and related table/market references.
They must not provide hidden balance changes, deposits, withdrawals, cash-out,
buy-credit, card payment, crypto transfer, or Telegram Wallet actions.

## Required Audit Logging

Every future admin action must write an immutable audit record containing:

- actor
- role
- action
- target resource
- timestamp
- reason
- old value
- new value

The audit trail must be append-only from the application perspective. Future
implementation planning should include tamper-evidence, retention policy, and
export/review procedures before any sensitive admin action is enabled.

## Explicit Non-Goals For Now

- No runtime admin panel.
- No payment, crypto, or Telegram Wallet implementation.
- No real-money behavior.
- No KYC/AML implementation.
- No SQL, Postgres, migration, durable storage, or database activation.
- No hidden balance changes.
- No hidden market-result manipulation.
- No changes to Target, Diceget, Flipget, or Tmarget product rules.
- No Axwins to Winsget runtime rebrand.

## Future Wallet / Payment Roadmap Only

The following are roadmap concepts only and must not be implemented as part of
Phase 0:

- credit card top-up
- Solana wallet connection
- Ethereum wallet connection
- Base L2 wallet connection
- Bitcoin wallet connection
- Telegram Wallet
- withdrawal/cash-out
- revenue pool or lottery concept

These items require separate product, security, legal, compliance, and
operational review before any runtime implementation is considered.

## Governance Note

Any future real-money or user-funds behavior requires explicit legal/compliance
review, transparent user-facing rules, immutable audit logs, monitoring,
incident procedures, and user-facing terms. No current Axwins demo behavior
should be interpreted as production financial readiness.
