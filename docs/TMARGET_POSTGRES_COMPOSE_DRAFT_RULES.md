# Tmarget Postgres Compose Draft Rules

## 1. Purpose

This document defines strict rules for a future Tmarget Postgres test Compose
file before such a file is added. It is a rules-only checkpoint for a possible
future `docker-compose.test.yml` draft and does not add Docker, database,
runtime, SQL, migration, or adapter behavior.

## 2. Current State

- `InMemoryTmargetRepository` is active.
- `PostgresTmargetRepository` is inactive/fail-closed.
- `DurableTmargetRepository` is inactive.
- No Docker Compose file exists.
- No Postgres test container exists.
- No database dependency exists.
- No migrations exist.
- No SQL exists.
- No runtime activation exists.
- Axwins uses internal demo credits only.

> Axwins currently uses internal demo credits. Live deposits, withdrawals, card payments, crypto transfers, Telegram wallet linking, and real-money trading are not enabled.

## 3. Future Compose File Naming

- The future test Compose file should be named `docker-compose.test.yml`.
- It must be test-only.
- It must not be used for production.
- It must not replace application deployment config.
- It must not imply durable runtime storage is active.

## 4. Future Service Naming

The expected future service name is:

- `tmarget-postgres-test`

Service naming must make the test-only purpose obvious.

## 5. Future Database Naming

Expected future test database naming:

- Database: `axwins_tmarget_test`
- User: `axwins_tmarget_test`
- Password: test-only placeholder, never production

Committed secrets are forbidden. Any placeholder credentials must be disposable,
test-only values that cannot be confused with production credentials.

## 6. Future Port Rules

- Use a local-only port mapping if needed.
- Avoid default production-looking assumptions.
- Document any port clearly.
- No production database host or port should be referenced.

## 7. Future Volume Strategy

Preferred future options:

- Disposable named test volume.
- `tmpfs`.
- Explicit cleanup instructions.

Persistent dirty volumes are a known risk. Cleanup must be documented before any
Compose draft is accepted.

## 8. Future Healthcheck Rules

- The future Compose file should include a Postgres healthcheck.
- Tests should wait for the healthcheck.
- No app runtime should auto-connect just because the container is healthy.

## 9. Future Env Boundaries

- Future test URL variable should be `TMARGET_TEST_DATABASE_URL`.
- Do not use production `DATABASE_URL` for tests.
- Do not commit `.env` files.
- Do not commit secrets.
- Runtime app must not silently consume test DB env vars.
- Explicit config gate is required before any runtime activation.

## 10. Future Migration Boundary

- Migrations are not part of this checkpoint.
- Future migrations must be separate and audited.
- The Compose file must not imply migrations exist.
- Migration rehearsal is future work.

## 11. Future Test Boundary

- The future Compose file is only for repository contract tests.
- Tests must verify idempotency and status history.
- Tests must verify runtime still defaults to `InMemoryTmargetRepository` unless
  explicitly configured.
- No wallet, payment, or live trading test data should be used.

## 12. Future CI Boundary

- CI may use a service container or Compose later.
- CI must use an isolated test database.
- No production secrets should be used.
- Cleanup must run after the job.
- Regular demo build must not activate Postgres storage.

## 13. Forbidden Contents in Future Compose File

The future Compose file must not contain:

- Production credentials.
- Production hostnames.
- Real `DATABASE_URL`.
- Payment secrets.
- Crypto/Web3 secrets.
- Telegram bot tokens.
- Stripe/card keys.
- External network links.
- App service activation that switches runtime to Postgres.
- Migrations that auto-run against unknown databases.

## 14. Activation Gate

Future activation requires:

- Explicit repository factory.
- Explicit config flag.
- Separate test/runtime config.
- Passing repository contract tests.
- Passing migration rehearsal.
- Rollback plan.
- Docs update.
- Activation audit.

## 15. Non-Goals

This document does not:

- Add Compose.
- Add Dockerfile.
- Add database dependencies.
- Add migrations.
- Add SQL.
- Implement adapter.
- Activate storage.
- Enable production persistence.
- Enable payments or real-money trading.

## 16. Decision Summary

- This is rules-only.
- No Docker, database, or runtime change is made.
- `InMemoryTmargetRepository` remains active.
- `PostgresTmargetRepository` remains inactive/fail-closed.
- `DurableTmargetRepository` remains inactive.
