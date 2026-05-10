# Tmarget Postgres Test DB Strategy

## 1. Purpose

This document plans a future Postgres test database strategy for Tmarget durable
persistence work. It does not implement a Postgres adapter, create migrations,
add database dependencies, read configuration, or activate durable storage.

## 2. Current State

- Tmarget currently uses `InMemoryTmargetRepository` at runtime.
- `PostgresTmargetRepository` exists only as an inactive/fail-closed skeleton.
- `DurableTmargetRepository` remains inactive.
- No Postgres adapter is implemented.
- No migrations exist.
- No database dependency exists for the Postgres adapter.
- No runtime activation exists.
- Axwins currently uses internal demo credits only.

> Axwins currently uses internal demo credits. Live deposits, withdrawals, card payments, crypto transfers, Telegram wallet linking, and real-money trading are not enabled.

## 3. Test DB Goals

Future Postgres test database work should:

- Prove the Postgres adapter satisfies the existing repository contract.
- Verify settlement and refund idempotency through real unique constraints.
- Verify market lookup, slug uniqueness, filtering, and status history behavior.
- Verify demo trade and position persistence without changing API response
  shapes.
- Catch schema drift before runtime activation.
- Keep test database usage separate from the current default in-memory test
  flow until explicitly scoped.
- Avoid any real-money, payment, or production-readiness implication.

## 4. Local Test DB Strategy

Planning direction:

- Use a disposable local Postgres database only after a future implementation
  pass chooses a driver and test harness.
- Keep `InMemoryTmargetRepository` as the default local repository until the
  Postgres adapter is implemented and intentionally selected for tests.
- Do not require a local Postgres server for normal Axwins development in the
  current phase.
- Keep local Postgres tests opt-in at first, separate from the current
  Mongo-free/default backend regression.
- Use controlled test fixtures rather than migrating in-memory demo data.

Local test DB checks should eventually include:

- Table creation/migration smoke checks.
- Repository contract behavior against Postgres.
- Duplicate idempotency-key conflict behavior.
- Restart persistence checks.
- Cleanup between tests.

## 5. CI Test DB Strategy

Future CI strategy:

- Add a Postgres service only after the adapter and migrations are implemented.
- Keep default CI fast path able to run in-memory tests without Postgres unless
  the project intentionally changes that policy.
- Run Postgres contract tests in a separate job or clearly marked test stage.
- Fail CI if migrations, schema smoke tests, or repository contract tests fail.
- Never require production secrets for CI database tests.

CI should not imply remote-demo or production activation. Passing Postgres tests
is only one gate before any activation decision.

## 6. Migration Rehearsal Strategy

Future migration rehearsals should:

- Apply migrations from an empty database.
- Roll back migrations where supported.
- Reapply migrations after rollback.
- Verify indexes and unique constraints.
- Verify settlement/refund idempotency constraints.
- Verify schema compatibility with repository contract tests.
- Run destructive cleanup only against disposable test databases.

No migration files are created in this pass.

## 7. Test Suite Design

Future Postgres test suites should include:

- Repository contract tests reused against the Postgres adapter.
- Schema smoke tests.
- Market create/get/list/update tests.
- Market slug uniqueness tests.
- Status history append/list tests.
- Demo trade create/list tests.
- Demo position upsert/list tests.
- Settlement idempotency tests.
- Refund idempotency tests.
- Duplicate key tests.
- API response shape regression tests.
- Wallet/ledger non-regression tests.

Tests should clearly distinguish:

- in-memory repository tests
- inactive skeleton tests
- Postgres adapter tests
- API/service behavior tests

## 8. Data Isolation and Cleanup

Future Postgres tests should use strict isolation:

- Use a disposable database or schema per test run where practical.
- Use transactions or truncation only after the adapter test strategy is
  defined.
- Clean tables between tests.
- Avoid shared mutable fixtures across test files.
- Avoid using developer or remote-demo databases for automated tests.
- Never use production-like data or secrets.

Settlement and refund idempotency tests should verify both first-write and
duplicate-write paths without leaving residual state that affects later tests.

## 9. Activation Gate

Postgres runtime activation should remain blocked until all of these are true:

- Postgres adapter is implemented behind the existing repository contract.
- Migrations exist and pass rehearsal.
- Repository contract tests pass against Postgres.
- Idempotency tests prove no double settlement/refund behavior.
- API response shape regressions pass.
- Wallet/ledger non-regression tests pass.
- Backup, rollback, and logging plans are reviewed.
- Activation is explicit and config-gated in a future scoped pass.
- Product/payment disclaimers remain correct.

The current inactive skeleton does not meet this activation gate and must remain
inactive.

## 10. Risks

- Test DB becoming a hidden runtime dependency.
- Flaky CI caused by unmanaged database lifecycle.
- Schema drift between migrations and repository mapping docs.
- Duplicate settlement/refund if unique constraints are missing.
- Cleanup failures causing cross-test contamination.
- Accidentally using real or remote-demo data in tests.
- Accidental runtime activation before contract tests pass.
- Overstating Postgres tests as production readiness.

## 11. Non-Goals

This document does not add:

- Postgres adapter logic.
- SQL queries.
- Migrations.
- Alembic.
- SQLAlchemy.
- psycopg, asyncpg, or any Postgres driver.
- Database dependencies.
- Environment variable reads.
- Runtime activation.
- Payment, deposit, withdrawal, crypto/Web3, Stripe/card, Telegram wallet,
  cash-out, buy-credit, or real-money behavior.
- Order book, oracle, dispute workflow, compliance, or KYC/AML behavior.
- Target, Diceget, or Flipget gameplay changes.

## 12. Future Implementation Sequence

Recommended sequence:

1. Keep `PostgresTmargetRepository` inactive.
2. Draft migration files in a future scoped migration pass.
3. Add a disposable Postgres test database harness.
4. Implement the Postgres adapter behind the existing repository contract.
5. Run repository contract tests against both in-memory and Postgres adapters.
6. Add idempotency and duplicate-key tests.
7. Add API response shape regression tests.
8. Rehearse migration apply/rollback.
9. Consider dev-only activation behind explicit configuration.
10. Consider remote-demo activation only after backup, rollback, logging, and
    operational review.

## 13. Decision Summary

- Test database strategy is planning-only.
- No Postgres adapter was implemented.
- No migrations were added.
- No database dependency was added.
- No runtime activation was added.
- `InMemoryTmargetRepository` remains active.
- `PostgresTmargetRepository` remains inactive/fail-closed.
- `DurableTmargetRepository` remains inactive.
