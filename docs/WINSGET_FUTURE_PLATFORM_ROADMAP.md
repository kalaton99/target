# Winsget Future Platform Roadmap

## Purpose

This roadmap documents future platform direction only. The current runtime may
still use the Axwins name. The future platform name is Winsget.

Winsget is the platform name, not a game name. Target remains a card game inside
the platform.

## Current Mode

- Current platform shell name in code/UI may still be Axwins.
- Future platform name: Winsget.
- Target, Diceget, and Flipget are games.
- Tmarget is a separate demo prediction market product, not a game.
- Wallet/Ledger is platform-level infrastructure.
- Current balances are internal demo credits only.

No deposits, withdrawals, cash-out, credit card processing, crypto transfers,
Telegram Wallet top-up, or real-money trading are implemented.

## Future Wallet Connection Layer

Potential future wallet connection work may include:

- Solana wallet connect.
- Ethereum wallet connect.
- Bitcoin wallet connect.
- Base L2 wallet connect.

These are not implemented. No wallet SDKs are added by this roadmap.

## Future Internal Balance / Top-Up Layer

Potential future balance work may include:

- Internal platform wallet top-up.
- Credit card top-up.
- Telegram Wallet top-up.

These are not implemented. The current wallet remains internal-demo-credit only.

## Future Payment Provider Integration

Any future payment provider work requires a separate design, legal/compliance
review, security review, and explicit implementation scope. This roadmap does
not add Stripe/card processing or any other payment runtime.

## Future Telegram Integration

Potential future Telegram work may include:

- Telegram login/connect.
- Telegram Wallet top-up.

These are not implemented. No Telegram runtime integration is added.

## Future Compliance And Security Requirements

Any future real-money, wallet, or payment work requires:

- KYC/AML and compliance review.
- Custody and funds-flow review.
- Security threat model.
- Abuse/fraud review.
- Audit logging and operational monitoring.
- Clear separation between demo credits and redeemable value.

## Explicit Non-Implementation List

This roadmap does not implement:

- Solana, Ethereum, Bitcoin, or Base wallet runtime integration.
- Telegram login or Telegram Wallet integration.
- Credit card processing.
- Deposits, withdrawals, cash-out, or buy-credit runtime features.
- Real-money trading.
- SQL, migrations, Postgres runtime activation, or durable production storage.
- Oracle, order book, dispute, compliance, or KYC/AML workflows.

## Decision Summary

Winsget is the future platform name. Target remains a game. No runtime rebrand,
wallet/payment/crypto integration, real-money feature, or storage change is
made by this roadmap.

