# Axwins Documentation Index

## Purpose

This index maps the current Axwins documentation set and records the boundaries
that must remain clear during future development. It is intended for developers
and reviewers who need a quick path through the current demo-release material.

## Product Boundaries

- Axwins is the platform.
- Target, Diceget, and Flipget are games inside Axwins.
- Target gameplay work is handled separately and should not be mixed into
  platform documentation or Tmarget work.
- Tmarget is not a game. It is a separate demo prediction market product inside
  Axwins.
- Wallet, Ledger, Transaction History, and Internal Demo Credits are shared
  Axwins platform core services.

## Required Internal Demo-Credit Disclaimer

Use this exact disclaimer wherever user-facing demo-credit/payment boundaries
need to be stated:

> Axwins currently uses internal demo credits. Live deposits, withdrawals, card payments, crypto transfers, Telegram wallet linking, and real-money trading are not enabled.

## Document Map

- `AXWINS_RELEASE_CHECKLIST.md`
  - Release/demo scope, route inventory, demo flow, red flags, and next phase
    options.
- `AXWINS_DEMO_WALKTHROUGH.md`
  - Presenter script for safely walking through the Axwins demo, including
    product boundaries, talking points, known limitations, and stop conditions.
- `AXWINS_LOCAL_DEV_STARTUP.md`
  - Windows PowerShell local startup guide for MongoDB, backend, frontend,
    helper scripts, health checks, and common local troubleshooting.
- `AXWINS_PRODUCT_LOOP_DEBUG_AUDIT.md`
  - Local product-loop audit covering route/API isolation, browser smoke
    coverage, fixed Flipget blocked-state copy, and deferred loop decisions.
- `EXTERNAL_TARGET_REFERENCE_AUDIT.md`
  - Read-only audit of the separate external Target reference repository and
    recommendations for future reviewed Target-only integration.
- `TARGET_GAMEPLAY_INTEGRATION_PLAN.md`
  - Staged plan for future Target gameplay integration review. It keeps Target
    as a game and Winsget as the future platform name.
- `WINSGET_FUTURE_PLATFORM_ROADMAP.md`
  - Future platform naming and wallet/payment/Telegram roadmap. It documents
    Winsget as the future platform name without implementing a runtime rebrand.
- `AXWINS_WALLET_LEDGER_MODEL.md`
  - Shared wallet and ledger model, source modules, reason constants,
    lock/unlock/settlement lifecycle, wallet UI behavior, and idempotency rules.
- `DICEGET_FLIPGET_PLAYTEST_QA.md`
  - Playtest QA audit for Diceget and Flipget, including findings, risk levels,
    and recommended fix order.
- `AXWINS_DEPLOYMENT_PREP.md`
  - Local/demo deployment preparation checklist, verification commands, route
    checklist, storage notes, and release gate.
- `AXWINS_HOSTING_DEPLOYMENT_PLAN.md`
  - Hosting options, recommended staged deployment path, frontend/backend
    deployment considerations, rollback plan, and deployment red flags.
- `AXWINS_INTERNAL_DEMO_DEPLOYMENT.md`
  - Minimal single-origin internal demo deployment shape, including static SPA
    fallback, `/api` and WebSocket proxy notes, env checklist, smoke flow, and
    rollback boundaries.
- `TMARGET_DURABLE_REPOSITORY_PLAN.md`
  - Future durable repository plan for Tmarget, grounded in the current
    repository contract and contract tests. It does not implement durable
    storage.
- `TMARGET_DURABLE_BACKEND_SELECTION.md`
  - Future durable backend evaluation and direction. It recommends Postgres as
    the future backend candidate and SQLite as a local-only fallback option.
- `TMARGET_POSTGRES_SCHEMA_DRAFT.md`
  - Draft Postgres schema planning for future Tmarget durable persistence. It
    does not add migrations or database dependencies.
- `TMARGET_POSTGRES_ADAPTER_MAPPING_PLAN.md`
  - Mapping between the current Tmarget repository contract and a future
    Postgres adapter. It does not implement the adapter.
- `TMARGET_POSTGRES_TEST_DB_STRATEGY.md`
  - Future Postgres test database strategy for adapter, migration, idempotency,
    and activation-gate testing. It does not add a test database dependency.
- `TMARGET_POSTGRES_DOCKER_COMPOSE_PLAN.md`
  - Future Docker Compose planning for local/CI Postgres test database
    infrastructure. It does not add Compose, Docker, env, or database files.
- `TMARGET_POSTGRES_COMPOSE_DRAFT_RULES.md`
  - Rules for a future `docker-compose.test.yml` draft, including naming,
    env, migration, CI, activation, and forbidden-content boundaries.

## Recommended Reading Order

1. `AXWINS_RELEASE_CHECKLIST.md`
2. `AXWINS_DEMO_WALKTHROUGH.md`
3. `AXWINS_LOCAL_DEV_STARTUP.md`
4. `AXWINS_PRODUCT_LOOP_DEBUG_AUDIT.md`
5. `EXTERNAL_TARGET_REFERENCE_AUDIT.md`
6. `TARGET_GAMEPLAY_INTEGRATION_PLAN.md`
7. `WINSGET_FUTURE_PLATFORM_ROADMAP.md`
8. `AXWINS_WALLET_LEDGER_MODEL.md`
9. `DICEGET_FLIPGET_PLAYTEST_QA.md`
10. `AXWINS_DEPLOYMENT_PREP.md`
11. `AXWINS_HOSTING_DEPLOYMENT_PLAN.md`
12. `AXWINS_INTERNAL_DEMO_DEPLOYMENT.md`
13. `TMARGET_DURABLE_REPOSITORY_PLAN.md`
14. `TMARGET_DURABLE_BACKEND_SELECTION.md`
15. `TMARGET_POSTGRES_SCHEMA_DRAFT.md`
16. `TMARGET_POSTGRES_ADAPTER_MAPPING_PLAN.md`
17. `TMARGET_POSTGRES_TEST_DB_STRATEGY.md`
18. `TMARGET_POSTGRES_DOCKER_COMPOSE_PLAN.md`
19. `TMARGET_POSTGRES_COMPOSE_DRAFT_RULES.md`

## Current Release / Demo State

Current demo-ready scope includes:

- Axwins platform shell.
- Games navigation for Target, Diceget, and Flipget.
- Diceget demo game module.
- Flipget demo game module.
- Tmarget demo prediction market product.
- Read-only Wallet / Ledger / Transaction History UI.
- Internal Demo Credits only.
- Tmarget active runtime storage remains `InMemoryTmargetRepository`.
- Tmarget durable storage contract and planning docs exist, but no durable
  repository is active.

The current documentation assumes demo/internal review usage, not production
real-money deployment.

## Do-Not-Change Boundaries

Unless a future task explicitly scopes the work:

- Do not change Target gameplay, reducer, RNG, payout math, special-card logic,
  or WebSocket protocol.
- Do not change Diceget or Flipget gameplay rules.
- Do not change Tmarget pricing, settlement behavior, runtime repository
  activation, storage contract, or demo admin guard behavior.
- Do not change wallet/ledger behavior.
- Do not add deposits, withdrawals, cash out, buy credits, crypto/Web3,
  Stripe/card payments, Telegram wallet linking, or real-money trading.
- Do not present internal demo credits as redeemable value.
- Do not present Tmarget as a game.
- Do not present Target as the platform.

## Future Phases

Potential future phases, each requiring its own explicit scope:

- Axwins deployment preparation and hosted demo validation.
- Wallet/Ledger developer documentation expansion.
- Tmarget durable repository implementation planning and inactive adapter
  scaffolding.
- Tmarget admin UX polish and operational audit improvements.
- Diceget/Flipget playtest QA follow-up.
- Target integration review, excluding gameplay bugfixes unless handled in the
  separate Target gameplay flow.
- CI pipeline and release gate automation.
- Durable storage, production auth/admin roles, monitoring, logging, backups,
  and security review.
- Payment/compliance/legal review only if real-money features are ever
  considered.
