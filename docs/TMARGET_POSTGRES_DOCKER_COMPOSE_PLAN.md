# Tmarget Postgres Docker Compose Plan

## 1. Purpose

This document plans a future Docker Compose approach for local and CI Postgres
test database usage during Tmarget durable repository development. It does not
add a Docker Compose file, Dockerfile, database dependency, migration, SQL, or
runtime activation.

## 2. Current State

- Tmarget currently uses `InMemoryTmargetRepository` at runtime.
- `PostgresTmargetRepository` exists only as an inactive/fail-closed skeleton.
- `DurableTmargetRepository` remains inactive.
- No Postgres adapter is implemented.
- No Docker Compose file exists for Tmarget Postgres testing.
- No migrations exist.
- No database dependency exists for the Postgres adapter.
- No runtime activation exists.
- Axwins currently uses internal demo credits only.

> Axwins currently uses internal demo credits. Live deposits, withdrawals, card payments, crypto transfers, Telegram wallet linking, and real-money trading are not enabled.

## 3. Why Docker Compose May Be Useful Later

Docker Compose may be useful in a later implementation phase because it can
provide:

- Reproducible local Postgres test database setup.
- Isolated test environment for durable repository contract tests.
- Easier migration rehearsal from a clean database.
- More consistent local and CI behavior.
- No dependency on a developer's machine-level Postgres installation.

Compose should be treated as test infrastructure only until the durable adapter,
migrations, tests, and activation audit are complete.

## 4. Proposed Future Service Shape

A future Compose file may describe a test-only Postgres service with:

- Explicit test-only service name.
- Isolated database name for Tmarget repository tests.
- Non-production credentials.
- Local-only port mapping.
- Disposable volume or `tmpfs` strategy.
- Healthcheck before running adapter tests.
- Clear naming that prevents confusion with production or remote-demo data.

No Compose file is added now. This section is conceptual and should not be read
as an implemented service definition.

## 5. Environment Variable Boundaries

Future test configuration should follow strict boundaries:

- No production `DATABASE_URL` should be used for tests.
- Future test env vars must be clearly named, for example
  `TMARGET_TEST_DATABASE_URL`.
- Runtime app code should not silently consume test DB variables.
- No secrets should be committed.
- Local `.env` files must remain untracked.
- Test credentials should be disposable and non-production.

This pass does not add environment variables or environment example files.

## 6. Data Isolation Strategy

Future Postgres tests should isolate data by:

- Resetting schema between test runs.
- Truncating tables or recreating schema after the test strategy is selected.
- Using unique IDs and idempotency keys per test.
- Avoiding shared mutable production-like data.
- Avoiding live wallet/payment data.
- Avoiding production credentials.
- Keeping migration rehearsals pointed only at disposable test databases.

## 7. Local Developer Workflow, Future-Only

A future workflow may be:

1. Start a test-only Postgres service.
2. Run migration rehearsal against the test database.
3. Run repository contract tests against the Postgres adapter.
4. Stop and remove the test database.
5. Verify app runtime still defaults to `InMemoryTmargetRepository` unless a
   future scoped pass explicitly configures otherwise.

This workflow is not runnable today because no Compose file, migrations,
Postgres adapter implementation, or database dependency is added in this pass.

## 8. CI Workflow, Future-Only

A future CI workflow may use:

- CI service container or Compose-based Postgres service.
- Isolated database per job.
- Migration rehearsal before tests.
- Repository contract tests after migration.
- Cleanup after the job.
- No production secrets.
- No runtime activation in regular demo build jobs.

CI Postgres service configuration is not implemented in this pass.

## 9. Activation Safety

Future activation requires:

- Explicit repository factory.
- Explicit config flag.
- Separate test and runtime configuration.
- Repository contract tests passing.
- Migration tests passing.
- Rollback tested.
- Docs updated.
- Activation audit completed.

Until then, `InMemoryTmargetRepository` remains active and
`PostgresTmargetRepository` remains inactive/fail-closed.

## 10. Risks

- Accidental production DB connection.
- Committed secrets.
- Test DB variables consumed by runtime.
- Persistent dirty local volumes.
- Migration drift.
- False confidence from tests that do not match runtime.
- Accidental durable storage activation.
- Confusing test infrastructure with production persistence.

## 11. Non-Goals

This document does not:

- Add Docker Compose.
- Add Dockerfile.
- Add database dependency.
- Add Postgres driver.
- Add SQL.
- Add migrations.
- Implement Postgres adapter.
- Activate durable storage.
- Enable payments or real-money trading.
- Add oracle, order book, dispute, compliance, or KYC/AML behavior.
- Change Target, Diceget, or Flipget gameplay.

## 12. Future Sequence

Recommended sequence:

1. Docker Compose planning document.
2. Optional `docker-compose.test.yml` draft in a later checkpoint.
3. Compose draft audit.
4. Migration draft.
5. Migration audit.
6. Adapter implementation against test database.
7. Repository contract tests against test database.
8. Activation factory behind explicit config.
9. Activation audit.
10. Runtime pilot only after all gates pass.

## 13. Decision Summary

- Docker Compose is a future test infrastructure option only.
- No Docker or database runtime change is made now.
- No Docker Compose file is added.
- No Dockerfile is added.
- `InMemoryTmargetRepository` remains active.
- `PostgresTmargetRepository` remains inactive/fail-closed.
- `DurableTmargetRepository` remains inactive.
