# External Target Reference Audit

## Purpose

This document records a read-only audit of the external Target reference repo:

```text
C:\Users\crims\OneDrive\Belgeler\New project\_external_target_reference
https://github.com/kalaton99/target
```

The external repo was not copied into the active platform repo. No external code
was merged.

## Reference State

- External repo HEAD inspected: `221f6c2`.
- Structure includes `backend/`, `frontend/`, `memory/`, `tests/`, and
  `test_reports/`.
- It appears to be a Target-focused codebase with historical OAuth/runtime notes
  that are not suitable for active Axwins/Winsget platform runtime.

## Useful Reference Areas

- Target-specific game engine modules under `backend/game_engine/`.
- Target realtime gateway and bridge modules under `backend/realtime_v2/`.
- Target lobby tests covering WebSocket, phase progression, reconnect, timeout,
  and bot stress scenarios.
- Target locked-rule memory and test reports that can help future Target
  gameplay review.

## What Can Be Safely Reused Later

- Ideas from Target gameplay tests, especially phase progression, WebSocket
  reconnect, timeout, and bot stress coverage.
- Target game-engine regression patterns if they are reviewed against the
  current platform Target implementation.
- Manual browser smoke patterns, rewritten to use current platform boundaries.

## What Must Not Be Copied Blindly

- External hosted OAuth/runtime modules or references.
- Historical hosted URLs, badges, attribution, auth tooling, or deployment
  assumptions.
- Any platform-level naming that conflicts with future Winsget naming.
- Any code that assumes Target is the whole platform.
- Any wallet/payment/compliance roadmap material that implies real-money
  readiness.

## Platform Boundary Conflicts

The active platform repo now contains:

- Target as one game module.
- Diceget as a separate dice game.
- Flipget as a separate coin-flip game.
- Tmarget as a separate demo prediction market product, not a game.
- Wallet/Ledger as platform-level infrastructure.

External Target code should not be allowed to overwrite these boundaries or
pull Diceget, Flipget, or Tmarget into Target routes, state, WebSockets, or API
namespaces.

## Winsget Naming Conflict

Future platform name is Winsget. Target must remain a game name. Do not rename
Target to Winsget and do not treat Winsget as a game module.

## Recommended Integration Plan

1. Finish current Axwins/Winsget platform product-loop stabilization.
2. Keep browser smoke tests green for Target, Diceget, Flipget, Tmarget, and
   Wallet/Ledger.
3. Compare Target gameplay modules file-by-file in a separate branch.
4. Port only reviewed Target gameplay fixes with focused tests.
5. Reject OAuth/runtime/deployment/branding material from the external repo.
6. Run backend Target regressions, browser smoke tests, and product-boundary
   scans before any merge.

## Decision Summary

The external repo is useful as a Target gameplay reference, not as a platform
source of truth. No external code was integrated in this checkpoint.
