# TARGET — MVP threat model (informational)

This note documents the security trade-offs of the **current MVP guest-auth
model** and is referenced from code-review findings. It is **not** a final
production threat model — it's an explicit acknowledgment of what is in
scope for the MVP and what is deferred.

## In-scope today

| # | Asset                  | Where it lives                     | Why this is OK for the MVP                                                                                     |
|---|------------------------|------------------------------------|----------------------------------------------------------------------------------------------------------------|
| 1 | Guest user identity    | Mongo `users` collection           | Username-only registration via `/api/v2/lobby/auth`; no email, password, or PII attached to the guest record. |
| 2 | Session JWT            | Browser `localStorage["target_user"]` | Convenient for SPA, survives refreshes (tested), works with the `?token=` WebSocket auth contract.              |
| 3 | Game state             | Server-authoritative reducer + WAL | Client only sends INTENT messages; cheating client cannot mutate engine state.                                  |
| 4 | RNG                    | Server-side `RNG_ENCRYPTION_KEY`   | Client seeds are advisory only; final shuffle uses server seed (Phase 6 design).                                |

## Why **not** httpOnly cookies right now

The reviewer suggested moving the session JWT from `localStorage` to an
`httpOnly` cookie. That mitigates one class of risk (XSS exfiltration of the
token), but the trade-off for this MVP is unfavourable because:

1. The WebSocket auth contract already in place is
   `/api/v2/ws/table/{id}?token=<jwt>`. Browsers do **not** attach cookies to
   WS handshakes in a way that is portable across all proxies/CDNs (especially
   with the Kubernetes ingress in front of this app), so we'd have to keep a
   second auth path for WS — which actually *increases* attack surface.
2. We have **no real-money** integration yet (Phase 8 is not started). The
   value of a guest token is "play one hand of TARGET as `xyz123`" — there is
   no spendable balance, no PII, no card data. Token theft has minimal blast
   radius.
3. We DO have XSS hardening: React escapes by default, no `dangerouslySetInnerHTML`,
   no `eval`, no untrusted markdown rendering. CSP is the real lever here, not
   storage location.

## Mitigations applied today (cheap, non-breaking)

1. **JWT TTL lowered from 72h → 12h** (`backend/.env`, `JWT_EXPIRES_HOURS`).
   A leaked token expires in half a day; a guest can simply re-register with
   the same username (it's idempotent — see `test_auth_is_idempotent_for_same_username`).
2. **Token validated on every PlayPage mount** via `GET /api/v2/lobby/me`.
   On 401 we *immediately* clear `localStorage` and redirect with a clear
   message (`?msg=session_expired`).
3. **Public endpoints are public** — `GET /api/v2/lobby/tables/{id}` requires
   no auth (the waiting-room polls it), so a stolen token doesn't expose
   anything that wasn't already public.
4. **Server-side rate limits** at the realtime gateway: max 2 connections per
   user, max 8 per IP (`/api/v2/realtime/health` reports the live config).

## What flips this calculation back toward httpOnly cookies

When ANY of these is added, re-evaluate:

- Real-money deposits/withdraws (Phase 8 — Web3 deposit/withdraw boundary).
- PII-bearing fields (email, phone, KYC) on the user model.
- A reward/token-claim endpoint that pays out value (Phase 9–10).
- Cross-origin embedding (an iframe deployment scenario).

At that point cookies + CSRF tokens + a CSP that disallows inline scripts
become worth the rework cost.

## Hardcoded "secrets" findings (closed as false positives)

- `tests/test_realtime_phase6.py`, `tests/test_realtime_phase6_bridge.py`,
  `tests/test_realtime_phase6_private.py` — string literals like
  `token="tok-alice"` are **not** credentials. They are fixture identifiers
  consumed by an in-memory stub gatekeeper that maps the literal back to a
  fake user_id. They never reach a real signing/verifying path.
- `tests/test_websocket.py` — every `is`/`is not` operator in the file
  compares to `None`, which is the **PEP 8-mandated** Python idiom. Replacing
  with `==` would make the code less correct.

---

## Duplicate-audit log

| Date         | Cycle              | Outcome                                                          |
| ------------ | ------------------ | ---------------------------------------------------------------- |
| 2026-04-26   | Initial audit      | Applied low-risk fixes (catches, keys, ternaries, ws.js refactor). |
| 2026-04-27   | Re-run, identical  | No code changes — same decisions still apply. See [`AUDIT_POLICY.md`](./AUDIT_POLICY.md). |

**Why two identical audits in a row?** The external auditor's rule set is
not yet tuned for this repo. The decisions captured in this document and
in [`AUDIT_POLICY.md`](./AUDIT_POLICY.md) (test-fixture allowlist, legacy
directory excludes, `is None` PEP-8 conformance, deferred refactors,
localStorage MVP acceptance) are stable. Until the auditor picks up those
configs, expect identical reports — not new findings.
