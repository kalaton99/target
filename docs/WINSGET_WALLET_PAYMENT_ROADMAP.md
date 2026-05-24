# Winsget Wallet Payment Roadmap

## Purpose

This is a planning-only roadmap for future funding and wallet integrations. It does not add provider SDKs, runtime payment code, crypto wallet code, real-money balances, production ledger storage, or migrations.

Current Winsget behavior remains internal demo credits only.

## Current Mode

Wallet/Ledger currently represents internal demo-credit accounting for local product loops:

- Target table stakes.
- Diceget table stakes.
- Flipget table stakes.
- Jackget demo game activity.
- Tmarget demo-credit positions and settlement/refund paths.

Internal demo credits are not redeemable value and are not deposits, withdrawals, cash-out, or payment balances.

## Future Funding Options

Potential future options, all requiring explicit approval before implementation:

- Credit card top-up through a regulated provider.
- Solana wallet connection.
- Ethereum wallet connection.
- Base L2 wallet connection.
- Telegram connection and Telegram Wallet top-up.

Each option must be separately designed, risk-reviewed, and tested. No provider should be added until legal, compliance, security, and operational requirements are clear.

## Phased Rollout

### Phase 0: Planning

- Keep demo-credit wording in runtime UI.
- Document future wallet options.
- Define compliance questions.
- Define ledger invariants and audit requirements.

### Phase 1: Read-Only Provider Research

- Compare providers and wallet connection approaches.
- Document supported regions, KYC requirements, custody model, fees, chargeback risk, and dispute handling.
- No SDK installation.
- No runtime user flow.

### Phase 2: Internal Funding Abstraction Draft

- Design interfaces for funding providers without wiring real providers.
- Define idempotency keys and provider event mapping.
- Define failure states and reconciliation states.
- Keep implementation inactive behind explicit build/runtime gates.

### Phase 3: Sandbox Integration

- Add one provider in sandbox mode only after approval.
- Use test credentials only.
- Add audit logs and reconciliation reports.
- Keep user-facing terms and risk disclosures visible.

### Phase 4: Production Readiness Review

- Legal/compliance signoff.
- Security review.
- Operational runbooks.
- Support/dispute workflows.
- Monitoring and alerting.
- Explicit launch approval.

## Required Ledger Invariants

Any future funding implementation must preserve:

- Append-only ledger entries.
- Idempotent provider event processing.
- No hidden balance mutation.
- Clear separation between available, reserved, settled, refunded, and failed states.
- Every balance change linked to a reason, source, and audit record.
- Reconciliation against provider records.

## Likely Future Files

Frontend:

- `frontend/src/pages/WalletFundingPage.jsx`
- `frontend/src/pages/WalletProviderStatusPage.jsx`
- `frontend/src/components/wallet/FundingMethodSelector.jsx`

Backend:

- `backend/payments/router.py`
- `backend/payments/service.py`
- `backend/payments/providers/card_provider.py`
- `backend/payments/providers/solana_provider.py`
- `backend/payments/providers/ethereum_provider.py`
- `backend/payments/providers/base_provider.py`
- `backend/payments/providers/telegram_provider.py`
- `backend/ledger/reconciliation.py`

Tests:

- `backend/tests/test_payment_provider_contract.py`
- `backend/tests/test_ledger_idempotency.py`
- `backend/tests/test_wallet_reconciliation.py`
- browser tests for disabled/unavailable funding states

## Safety And Compliance Boundaries

Before any real-money or user-funds behavior:

- Legal/compliance review is mandatory.
- User-facing terms are mandatory.
- KYC/AML requirements must be defined.
- Chargeback, refund, fraud, and sanctions workflows must be defined.
- Custody and private-key responsibilities must be explicit.
- Tax/reporting implications must be reviewed.

## Non-Goals

- No payment runtime behavior now.
- No crypto wallet runtime behavior now.
- No Telegram Wallet runtime behavior now.
- No real-money balance behavior now.
- No provider SDKs now.
- No SQL/Postgres/migration/durable-storage activation now.
- No production trading, deposits, withdrawals, or cash-out now.

## Test Strategy For Future Implementation

Future runtime implementation must include:

- Provider webhook idempotency tests.
- Ledger double-entry or equivalent invariant tests.
- Failed, pending, completed, reversed, and refunded event tests.
- Browser tests proving funding UI is disabled unless configured.
- Security tests for spoofed provider callbacks.
- Reconciliation tests for mismatched provider events.
- Product-boundary tests proving funding code does not alter Target, Diceget, Flipget, Jackget, or Tmarget rules.

