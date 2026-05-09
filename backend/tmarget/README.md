# Tmarget Demo Market MVP

Tmarget is a separate demo prediction market platform. It is not a game module
and does not use Target, Diceget, or Flipget game table/round/bot/RNG logic.

This MVP is demo-only:
- internal demo credits only
- no live deposits or withdrawals
- no crypto/Web3 transfers
- no Stripe/card payments
- no real-money trading
- no external oracle integration
- no legal or regulatory compliance claims

Pricing uses a small deterministic AMM in `pricing.py`, not an order book.
Admin/resolver actions drive market lifecycle and settlement. Settlement and
cancelled/invalid refunds use deterministic wallet idempotency keys.

Future production work would need persistence, admin roles, KYC/AML review,
oracle/dispute process, audit hardening, market risk controls, and compliance
review before any real-money operation.
