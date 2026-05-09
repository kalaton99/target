# Tmarget Demo Market MVP

Tmarget is a separate demo prediction market product inside Axwins. It is not a
game module and does not use Target, Diceget, or Flipget game table/round/bot/RNG
logic.

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

## Storage Boundary

The active storage implementation is `InMemoryTmargetRepository` in
`repository.py`. It preserves the current local/demo behavior while making the
next durable phase explicit. The durable schema and repository contract are
documented in `STORAGE_MODEL.md`. Future storage must persist:

- markets and market rules
- liquidity pool state
- user positions
- trades
- settlements
- refunds
- admin actions

The repository boundary is not a database implementation and does not add a
Mongo/Postgres dependency to the normal local test suite.

## Demo Admin Guard

Admin routes require `X-Axwins-Demo-Admin: true`. This is a local/demo-only guard
for internal MVP testing and is not production authorization. Real admin roles,
permissions, audit review, and operational controls remain deferred.

## Deferred Production Requirements

Future production work would need durable DB schema, real auth/admin roles, audit
log hardening, oracle/resolution workflow, dispute workflow, compliance/legal
review, KYC/AML if ever real-money, market risk controls, and production security
review before any real-money operation.
