# TARGET — Admin / Control System Design (v1.0, 2026-05)

**Status:** Design only. No code, no DB migration, no UI yet.
**Goal:** Production-grade, scalable, secure admin layer compatible with
the real-money roadmap. Sits ALONGSIDE the existing player surface; never
touches the locked game engine (`reducer.py`, `turn_engine.py`).

---

## 0. Design Principles

1. **Engine is sacrosanct.** Admin tools dispatch SERVER-source intents
   into the existing `EngineBridge.submit_server_intent` pipeline (same
   one used by `/start`). No new game-state mutation paths. No reducer
   forks.
2. **Append-only audit.** Every admin action is journaled BEFORE the
   mutation it triggers, with a hash chain. No deletes, no edits.
3. **Two-person rule for high-risk ops.** Kill-switch, rake change,
   force-credit > N, and role grants require a second admin's approval
   within a TTL window.
4. **Server-authoritative RBAC.** Permissions are evaluated on every
   request from the user's role document; no client-side gating is
   trusted.
5. **Separate auth surface.** Admins never share a token with players.
   Different JWT audience (`aud=admin`), different cookie name, different
   path scope. MFA mandatory.
6. **Read-replica aware.** Dashboard queries hit a read-only projection
   layer (Mongo aggregation pipelines, cached) — never block the live
   game's primary writes.
7. **Boundaries, not abstractions.** Wire to existing modules
   (`lobby/`, `realtime_v2/`, `core/db.py`). Quarantined modules
   (`auth/`, `tables/`, `wallet/`) stay quarantined; admin uses its
   own service layer.
8. **Compliance-ready, not compliance-complete.** Hooks for KYC, AML,
   sanctions, region-blocking. Real integrations deferred per PRD.

---

## 1. Module Layout (proposed)

```
backend/
├── admin/                       # NEW — fully isolated module
│   ├── __init__.py
│   ├── auth.py                  # Admin login, MFA, session, JWT
│   ├── rbac.py                  # Role/permission matrix + decorators
│   ├── audit.py                 # Append-only audit writer + verifier
│   ├── approvals.py             # Two-person-rule workflow
│   ├── services/
│   │   ├── dashboard.py         # Metric aggregations (read-only)
│   │   ├── users.py             # Player lifecycle ops
│   │   ├── tables.py            # Live table control ops
│   │   ├── finance.py           # Rake / limits / house balance
│   │   ├── events.py            # Campaign / bonus engine
│   │   ├── safety.py            # Kill-switch, flags, risk
│   │   └── replay.py            # Read-only replay of finished hands
│   ├── routes/                  # Thin FastAPI routers, one per service
│   │   ├── auth_router.py
│   │   ├── dashboard_router.py
│   │   ├── users_router.py
│   │   ├── tables_router.py
│   │   ├── finance_router.py
│   │   ├── events_router.py
│   │   ├── safety_router.py
│   │   └── audit_router.py
│   ├── schemas.py               # Pydantic in/out models (admin-only)
│   ├── middleware.py            # Rate-limit, IP allowlist, audit hook
│   └── tests/                   # Pytest suite — admin-only
│
├── realtime_v2/
│   └── admin_channel.py         # NEW — admin pubsub topic + spectate
│
frontend/
└── src/
    └── admin/                   # NEW — separate route tree, separate build chunk
        ├── AdminApp.jsx         # Mounted under /admin
        ├── pages/
        │   ├── LoginPage.jsx
        │   ├── DashboardPage.jsx
        │   ├── UsersPage.jsx
        │   ├── UserDetailPage.jsx
        │   ├── TablesPage.jsx
        │   ├── TableSpectatePage.jsx
        │   ├── FinancePage.jsx
        │   ├── EventsPage.jsx
        │   ├── SafetyPage.jsx
        │   └── AuditLogPage.jsx
        ├── lib/
        │   ├── adminApi.js
        │   └── adminAuth.js
        └── components/          # Reused tables, dialogs, charts
```

The `/admin` URL prefix is enforced at the router; the build serves a
separate JS chunk so the player bundle never contains admin code.

---

## 2. Admin Authentication & Roles

### 2.1 Roles & Permission Matrix

| Permission                      | super_admin | admin | moderator |
|---------------------------------|:-----------:|:-----:|:---------:|
| `dashboard:read`                | ✅          | ✅    | ✅        |
| `users:read`                    | ✅          | ✅    | ✅        |
| `users:suspend`                 | ✅          | ✅    | ✅        |
| `users:block_permanent`         | ✅          | ✅    | ❌        |
| `users:adjust_balance`          | ✅          | ✅    | ❌        |
| `users:flag_risk`               | ✅          | ✅    | ✅        |
| `tables:read`                   | ✅          | ✅    | ✅        |
| `tables:spectate`               | ✅          | ✅    | ✅        |
| `tables:force_stop`             | ✅          | ✅    | ✅        |
| `tables:remove_player`          | ✅          | ✅    | ✅        |
| `finance:read`                  | ✅          | ✅    | ❌        |
| `finance:configure_rake`        | ✅          | 🔒²   | ❌        |
| `finance:configure_limits`      | ✅          | ✅    | ❌        |
| `events:create`                 | ✅          | ✅    | ❌        |
| `events:toggle`                 | ✅          | ✅    | ✅        |
| `safety:kill_switch`            | ✅          | 🔒²   | ❌        |
| `safety:feature_flags`          | ✅          | ✅    | ❌        |
| `safety:region_block`           | ✅          | ✅    | ❌        |
| `audit:read`                    | ✅          | ✅    | ✅        |
| `admin:grant_role`              | ✅          | ❌    | ❌        |
| `admin:revoke_role`             | ✅          | ❌    | ❌        |
| `admin:read_admins`             | ✅          | ✅    | ❌        |

🔒² = requires second-admin approval (two-person rule).

The matrix lives in `admin/rbac.py` as a pure-Python dict and is the
single source of truth. A `@requires("perm:name")` decorator gates
every admin route. Custom roles can be added later by extending the
dict; a future `roles` collection allows runtime-defined permissions
without code change (out of scope for v1).

### 2.2 Authentication flow

- Admins live in a separate `admin_users` collection — **never the
  player `users` table**. No SSO with player accounts; no shared
  credentials.
- Login: `POST /api/v2/admin/auth/login` with `{email, password}`.
  Backend validates bcrypt, returns `mfa_challenge_id` (always — MFA
  mandatory).
- MFA: `POST /api/v2/admin/auth/mfa` with `{challenge_id, code}` (TOTP
  6-digit). Successful MFA mints a short-lived (15 min) JWT
  `aud=admin` + a long-lived (8 h) refresh token bound to IP + UA hash.
- Session cookie: `admin_session_token`, httpOnly, secure,
  samesite=strict, path=`/api/v2/admin`. Different name + path from
  the player cookie so a compromised player session cannot reach
  admin routes even by accident.
- IP allow-list: optional per-deployment env var
  `ADMIN_IP_ALLOWLIST=1.2.3.4/32,...`. Empty = open.
- Brute-force: per-account exponential lockout after 5 failed logins
  within 10 minutes; per-IP rate-limit at the FastAPI middleware layer
  (existing pattern).
- Audit: every login attempt (success/fail/MFA-fail) is journaled.

### 2.3 `admin_users` schema

```python
{
  "admin_id":         "adm_<uuid>",   # custom id, never expose _id
  "email":            "ops@target.io",
  "password_hash":    "bcrypt(...)",
  "totp_secret_enc":  "<aes-gcm of TOTP secret>",
  "role":             "super_admin" | "admin" | "moderator",
  "active":           True,
  "ip_allowlist":     ["1.2.3.4/32"],  # optional per-admin override
  "created_at":       <utc datetime>,
  "created_by":       "adm_xxxx" | None,   # None for the bootstrap admin
  "last_login_at":    <utc datetime>,
  "last_login_ip":    "1.2.3.4",
  "failed_login_count": 0,
  "locked_until":     <utc datetime> | None,
  "mfa_enrolled_at":  <utc datetime>,
  "rotated_secret_at": <utc datetime>,
}
```

The bootstrap super-admin is provisioned by an out-of-band CLI script
(`backend/admin/bootstrap.py`, run once per environment) — never via
the API. The script hard-fails if any `admin_users` row already exists.

---

## 3. Dashboard

`GET /api/v2/admin/dashboard/summary` — single aggregated read.

Returns a snapshot computed from the existing primary collections plus
new counter-doc updates:

```json
{
  "as_of": "2026-05-05T08:30:00Z",
  "online": {
    "players":   142,                  // distinct user_id over WS in last 60s
    "admins":     3,
    "guests":    18                    // subset of `players`
  },
  "tables": {
    "lobby":     27,
    "running":   14,
    "bots_in_play": 9                  // dev surfaces
  },
  "volume_24h": {
    "ante_total":    1_240_000,
    "bet_total":     8_750_000,
    "rake_total":      262_500,
    "hands_played":     4_812
  },
  "house": {
    "balance":          1_905_000,     // sum of `house_ledger`
    "lottery_pool":       182_000,     // future
    "pending_payouts":     53_000      // unsettled real-money flows
  },
  "alerts": {
    "kill_switch":   false,
    "open_incidents":     2,
    "high_risk_users":    7
  }
}
```

All 24 h volume fields come from a denormalised `dashboard_counters`
collection. The counters are bumped via a fan-out hook off
`event_log/writer.py` whenever the engine writes an `ANTE`, `BET`,
`PAYOUT`, or `RAKE` event. The dashboard read NEVER scans the
`hand_actions` log directly. This keeps the metric query at O(1) and
isolates dashboard load from gameplay.

The hook is additive (no reducer change) and idempotent — it dedupes
on `(hand_id, seq)` so re-publishes do not double-count.

### 3.1 Time-series endpoints (drill-down)

- `GET /api/v2/admin/dashboard/online?bucket=1m&window=24h`
- `GET /api/v2/admin/dashboard/volume?bucket=1h&window=7d`
- `GET /api/v2/admin/dashboard/active_tables?bucket=5m&window=24h`

Returns `[(ts, value), ...]`. Backed by Mongo's `$bucketAuto`
pipeline, capped at 500 points per response.

---

## 4. User Management

### 4.1 Endpoints

| Method | Path                                              | Permission              |
|--------|---------------------------------------------------|-------------------------|
| GET    | `/api/v2/admin/users?q=&risk=&status=&page=`      | `users:read`            |
| GET    | `/api/v2/admin/users/{user_id}`                   | `users:read`            |
| GET    | `/api/v2/admin/users/{user_id}/hands?since=`      | `users:read`            |
| GET    | `/api/v2/admin/users/{user_id}/wallet_history`    | `users:read`            |
| POST   | `/api/v2/admin/users/{user_id}/suspend`           | `users:suspend`         |
| POST   | `/api/v2/admin/users/{user_id}/unsuspend`         | `users:suspend`         |
| POST   | `/api/v2/admin/users/{user_id}/block`             | `users:block_permanent` |
| POST   | `/api/v2/admin/users/{user_id}/risk_flag`         | `users:flag_risk`       |
| POST   | `/api/v2/admin/users/{user_id}/balance_adjust`    | `users:adjust_balance` 🔒² |
| POST   | `/api/v2/admin/users/{user_id}/force_logout`      | `users:suspend`         |

### 4.2 New collection — `user_moderation`

```python
{
  "moderation_id":  "mod_<uuid>",
  "user_id":        "u_xxx",
  "action":         "SUSPEND" | "BLOCK" | "RISK_FLAG" | "UNSUSPEND",
  "reason":         "self-exclusion request",
  "evidence_url":   "s3://...",        # optional
  "expires_at":     <utc> | None,      # null = permanent
  "actor_admin_id": "adm_xxx",
  "approved_by":    "adm_yyy" | None,
  "audit_id":       "aud_zzz",         # foreign-key into audit_log
  "created_at":     <utc>,
}
```

A user is "suspended" when ANY un-expired `SUSPEND` or `BLOCK` row
exists. The lobby/auth path checks this collection on token mint and
on every WS connect (cached per-process for 5 s).

### 4.3 User detail view

- Profile: `user_id`, `email` (OAuth users), `username`, provider,
  created_at, last_seen_at, KYC status (placeholder).
- Wallet snapshot: balance, total deposited, total withdrawn (future).
- Lifetime stats: hands played, hands won, gross win/loss, RTP%,
  longest session, biggest pot.
- Recent hands (paginated): hand_id, table, seat, score, payout, ts,
  link to replay.
- Active sessions: WS connections, IPs, UA fingerprints. Each row has
  a "Force logout" button that publishes a server-only `KICK_USER`
  intent on the admin pubsub channel; the gateway closes the matching
  socket.
- Moderation history: full `user_moderation` rows with actor names.
- Risk flags: ML-driven (future) or manual (`bot_pattern`,
  `multi_account`, `chargeback_risk`, `self_exclusion`).

### 4.4 Force-logout / kick flow

1. Admin clicks "Force logout" → `POST /api/v2/admin/users/{id}/force_logout`.
2. Backend writes audit row.
3. Backend publishes `{type: "KICK_USER", user_id}` to a NEW
   `admin:control` pubsub topic.
4. `realtime_v2/gateway` subscribes additionally to `admin:control`
   on each WS session. On match, sends a `FORCE_LOGOUT` close frame
   with reason and closes the socket.
5. Player's frontend receives close → clears localStorage → redirects
   to `/lobby?msg=session_terminated`.

No engine intent fires; the player's seat enters reconnect-grace as
usual. This separates session lifecycle from game-state lifecycle.

---

## 5. Game Control

### 5.1 Endpoints

| Method | Path                                            | Permission              |
|--------|-------------------------------------------------|-------------------------|
| GET    | `/api/v2/admin/tables?status=`                  | `tables:read`           |
| GET    | `/api/v2/admin/tables/{table_id}`               | `tables:read`           |
| GET    | `/api/v2/admin/tables/{table_id}/hand/{hand_id}/replay` | `tables:read`   |
| WS     | `/api/v2/admin/ws/spectate/{table_id}?token=`   | `tables:spectate`       |
| POST   | `/api/v2/admin/tables/{table_id}/force_stop`    | `tables:force_stop`     |
| POST   | `/api/v2/admin/tables/{table_id}/remove_player` | `tables:remove_player`  |
| POST   | `/api/v2/admin/tables/{table_id}/freeze`        | `tables:force_stop`     |

### 5.2 Spectate

- A NEW gateway endpoint `/api/v2/admin/ws/spectate/{table_id}`. Auth
  uses the admin JWT. The session subscribes to `table:{id}` AND
  `table:{id}:user:*` (admin-only fan-in topic published by the bridge
  alongside the per-user privates) so the admin sees all face-up
  cards.
- A new bridge method `EngineBridge._publish_admin_view(state)` writes
  to `table:{id}:admin` with a payload that union-merges every
  player's `cards`. Players cannot subscribe (gatekeeper rejects any
  non-admin attempt by topic-prefix check).
- Spectator NEVER receives the bench's `client_action_id` ack stream
  and CANNOT submit intents. Read-only socket.
- Connect/disconnect emits a `SPECTATOR_JOINED` / `SPECTATOR_LEFT`
  event into the public broadcast (privacy-by-design — players see
  when an admin is watching).

### 5.3 Force-stop / freeze

- **Force-stop:** `POST /api/v2/admin/tables/{id}/force_stop` →
  `submit_server_intent({type: "ADMIN_END_HAND", reason})`.
  - Reducer change required (one new action handler in `reducer.py`):
    refund all `total_contributed` to each player's balance, mark
    hand as `ENDED_BY_ADMIN`, clear timers. **This is a deliberate
    reducer extension, not a refactor — it is sequenced AFTER admin
    sign-off and gated behind the kill-switch / two-admin approval
    when `house_balance` is impacted.**
  - Audit row + `ADMIN_END_HAND` event in `hand_actions`.
- **Freeze:** marks the table `LOBBY_FROZEN` so no new hand auto-starts;
  current hand finishes naturally. No reducer change.
- **Remove player:** `submit_server_intent({type: "ADMIN_REMOVE_SEAT",
  user_id, reason})` — refunds the player's `total_contributed` for
  the current hand, removes them from `state.players`, sets
  `sitting_out=True` in `lobby_users`. Hand continues with remaining
  active players (or ends if <2).

### 5.4 Replay

Read-only re-execution of a completed hand from `hand_actions` +
`replay_inputs` (provably-fair RNG). Powered by the existing
`event_log/replay.reconstruct_intent` chain. Admin sees every card,
every action, every state-version transition. Useful for dispute
resolution and collusion review.

---

## 6. Financial Control (design only)

### 6.1 New collection — `house_ledger`

Mirrors the existing double-entry pattern in `wallet/`. Two rows per
house movement (HOUSE + counter), tied by `journal_id`.

```python
{
  "journal_id":   "j_<uuid>",
  "ledger_id":    "lh_<uuid>",
  "kind":         "RAKE_COLLECTED" | "BONUS_PAID" | "JACKPOT_FUNDED"
                | "ADMIN_ADJUSTMENT" | "REFUND_OUT",
  "amount":       int,                  # signed integer cents/credits
  "currency":     "CREDITS",            # placeholder; real-money TBD
  "hand_id":      "h_xxx" | None,
  "user_id":      "u_xxx" | None,
  "actor_admin_id": "adm_xxx" | None,
  "audit_id":     "aud_zzz" | None,
  "created_at":   <utc>,
}
```

### 6.2 New collection — `table_economics`

Per-target-tier (or per-table override) configuration.

```python
{
  "scope":        "TARGET_30" | "TARGET_50" | ... | "TABLE:<table_id>",
  "rake_percent_bps": 250,             # 2.5% = 250 basis points
  "rake_cap_credits": 5000,            # absolute ceiling per hand
  "min_buyin":    100,
  "max_buyin":    100_000,
  "min_bet":      10,
  "max_bet_factor_pot": 2.0,           # max raise = 2× pot
  "ante":         10,
  "active":       True,
  "effective_at": <utc>,
  "expires_at":   <utc> | None,
  "audit_id":     "aud_zzz",
  "actor_admin_id": "adm_xxx",
  "approved_by":  "adm_yyy",           # two-admin approval required
}
```

Versioning is append-only. The engine resolves the active row by
`scope + effective_at <= now() < expires_at` at the START_HAND
boundary — so changes never disturb a hand mid-flight.

### 6.3 Endpoints

| Method | Path                                              | Permission                 |
|--------|---------------------------------------------------|----------------------------|
| GET    | `/api/v2/admin/finance/house_balance`             | `finance:read`             |
| GET    | `/api/v2/admin/finance/house_ledger?since=&kind=` | `finance:read`             |
| GET    | `/api/v2/admin/finance/economics?scope=`          | `finance:read`             |
| POST   | `/api/v2/admin/finance/economics`                 | `finance:configure_rake` 🔒² |
| GET    | `/api/v2/admin/finance/exposures`                 | `finance:read`             |

`/exposures` returns total at-risk credits per running table (sum of
`total_contributed` across active players) — operational risk view.

### 6.4 Real-money roadmap hook

Wallet currency is `CREDITS` for v1. Schema is currency-aware so a
later real-money pipeline (Stripe / on-ramp) can add `USD_CENTS`,
`INR_PAISE`, etc. without migrations beyond column add. KYC / AML
gate lives in `admin/services/finance.py::_require_kyc()` (NOOP in
v1, raises `KYC_REQUIRED` once integrated).

---

## 7. Events & Campaigns

### 7.1 New collection — `campaigns`

```python
{
  "campaign_id":   "cmp_<uuid>",
  "name":          "Diwali Bonus 2026",
  "kind":          "DEPOSIT_MATCH" | "RAKE_DISCOUNT"
                 | "POT_MULTIPLIER" | "FREE_HAND" | "GAME_MODE_TOGGLE",
  "config":        { ... },              # kind-specific, validated by Pydantic
  "audience":      {
      "include_user_ids": [...],
      "include_segments": ["new_players", "vip"],
      "exclude_user_ids": [...],
      "include_regions":  ["IN", "EU"],
      "exclude_regions":  []
  },
  "starts_at":     <utc>,
  "ends_at":       <utc>,
  "active":        True,
  "max_grants":    1000,                 # global cap
  "max_grants_per_user": 1,
  "created_by":    "adm_xxx",
  "audit_id":      "aud_zzz",
  "created_at":    <utc>,
}
```

### 7.2 Grants & idempotency

`campaign_grants` collection records every (campaign_id, user_id, grant_id)
tuple with a unique index on `(campaign_id, user_id)` when the campaign
is `max_grants_per_user=1`. The grant row also references the
`journal_id` of the bonus credit ledger row so the money trail is
auditable.

### 7.3 Game-mode toggles

A `kind=GAME_MODE_TOGGLE` campaign sets a feature flag (`turbo_mode`,
`6max_only`, etc.) for its audience window. Engine reads the flag from
the resolved table-economics row at START_HAND. No reducer change.

### 7.4 Temporary rule overrides

A super-admin-only override can patch a single table's economics for
a fixed window (e.g. "rake 0% on table X for the next 2 hours during
launch event"). It's a `table_economics` row with
`scope=TABLE:<id>` and `expires_at=now+2h`. Two-admin approval.

### 7.5 Endpoints

| Method | Path                                       | Permission        |
|--------|--------------------------------------------|-------------------|
| GET    | `/api/v2/admin/events`                     | `events:create`   |
| POST   | `/api/v2/admin/events`                     | `events:create`   |
| PATCH  | `/api/v2/admin/events/{id}`                | `events:create`   |
| POST   | `/api/v2/admin/events/{id}/toggle`         | `events:toggle`   |
| GET    | `/api/v2/admin/events/{id}/grants`         | `events:create`   |

---

## 8. Safety / Compliance

### 8.1 Kill-switch

A single document in `platform_state`:

```python
{
  "_id":             "global",
  "kill_switch":     False,
  "reason":          "",
  "actor_admin_id":  "adm_xxx",
  "approved_by":     "adm_yyy",      # two-admin
  "engaged_at":      <utc> | None,
  "audit_id":        "aud_zzz"
}
```

When `kill_switch=true`:
- `lobby/router::create_table` and `start_table` reject `503 KILL_SWITCH`.
- `realtime_v2/gateway` rejects new WS connections with policy-violation
  close.
- Existing WS sessions receive a single broadcast `KILL_SWITCH_ENGAGED`
  event and are gracefully drained: each running hand finishes its
  current betting round and force-stops at the next phase boundary
  (refund-all path, see §5.3).
- Bots are descheduled.

Disengage requires a fresh approval row and an explicit "soft-resume"
flag so admins can confirm before traffic returns.

### 8.2 Region / feature flags

`platform_flags` collection. Strongly-typed Pydantic schema; admins
can only edit keys the schema declares.

```python
{
  "flag_key":     "allow_real_money",
  "value":        false,
  "regions":      ["IN", "EU"],     # null = global
  "rollout_pct":  100,              # 0-100
  "audit_id":     "aud_zzz",
  "actor_admin_id": "adm_xxx",
  "updated_at":   <utc>
}
```

Resolved at gateway connect time (player's IP geo-lookup → region).
The lobby + WS check both `kill_switch` and applicable region flags
on every state-changing request. A 1-second per-process cache is
acceptable given the kill-switch's intentional grace window.

### 8.3 Risk flags on users

User-level flags live in `user_moderation` (§4.2). Risk-scoring
hooks (Phase 9+) populate them automatically; admins can also flag
manually. The lobby + payments path checks active flags on relevant
operations:

| Flag                  | Effect                                                   |
|-----------------------|----------------------------------------------------------|
| `bot_pattern`         | Soft block: capped stake, observation only.              |
| `multi_account`       | Block all real-money flows; gameplay allowed.            |
| `chargeback_risk`     | Block deposits (future).                                 |
| `self_exclusion`      | Hard block: no login, no auth, no WS connect.            |

### 8.4 Endpoints

| Method | Path                                       | Permission             |
|--------|--------------------------------------------|------------------------|
| GET    | `/api/v2/admin/safety/status`              | `dashboard:read`       |
| POST   | `/api/v2/admin/safety/kill_switch/engage`  | `safety:kill_switch` 🔒²|
| POST   | `/api/v2/admin/safety/kill_switch/release` | `safety:kill_switch` 🔒²|
| GET    | `/api/v2/admin/safety/flags`               | `safety:feature_flags` |
| PATCH  | `/api/v2/admin/safety/flags/{key}`         | `safety:feature_flags` |
| GET    | `/api/v2/admin/safety/regions`             | `safety:region_block`  |
| PATCH  | `/api/v2/admin/safety/regions`             | `safety:region_block`  |

---

## 9. Logging & Audit

### 9.1 `audit_log` collection (append-only, hash-chained)

```python
{
  "audit_id":      "aud_<uuid>",
  "seq":            123,                # auto-increment counter
  "prev_hash":      "<sha256-of-previous-row>",
  "row_hash":       "<sha256(prev_hash + canonical(this_row_minus_row_hash))>",
  "ts":             <utc>,
  "actor": {
    "admin_id":     "adm_xxx",
    "email":        "ops@target.io",
    "ip":           "1.2.3.4",
    "ua_hash":      "<sha256 of UA>",
    "session_id":   "as_xxx"
  },
  "action":         "USER_SUSPEND",     # canonical machine-readable
  "object": {
    "kind":         "user" | "table" | "campaign" | "flag" | "admin" | ...,
    "id":           "u_xxx"
  },
  "reason":         "self-exclusion request",
  "before":         {...},              # snapshot, redacted of secrets
  "after":          {...},              # snapshot
  "approval_id":    "ap_yyy" | None,    # two-admin pointer
  "outcome":        "OK" | "REJECTED" | "PARTIAL_FAIL",
  "error":          "..." | None,
}
```

### 9.2 Hash chain integrity

- Unique index on `seq`. Insert is transactional (Mongo session) so
  `seq` and hash chain never collide under concurrency.
- `audit:read` endpoint includes a `verify=true` query that walks the
  chain server-side and returns the broken seq on mismatch.
- A nightly job snapshots `(seq_min, seq_max, row_hash)` to a
  separate `audit_anchors` collection (and, in real-money mode, to an
  external WORM bucket / blockchain anchor — not in v1 scope).

### 9.3 What is logged

EVERY admin route writes an audit row, including read-only ones if
they touch sensitive data (`USER_PII_VIEWED`, `KEY_VIEWED`). Read-only
admin browsing of dashboards is NOT audited (too noisy).

The audit writer lives in `admin/audit.py` and is called via a
FastAPI dependency that wraps every admin route. Failure to write
the audit row aborts the action with `500 AUDIT_WRITE_FAILED` —
audit-first invariant.

### 9.4 Endpoints

| Method | Path                                       | Permission        |
|--------|--------------------------------------------|-------------------|
| GET    | `/api/v2/admin/audit?since=&actor=&action=`| `audit:read`      |
| GET    | `/api/v2/admin/audit/verify?from=&to=`     | `audit:read`      |
| GET    | `/api/v2/admin/audit/{audit_id}`           | `audit:read`      |

---

## 10. Two-Person-Rule Workflow

For 🔒² actions:

1. Admin A submits the action → response `202 PENDING_APPROVAL` with
   `approval_id` and `expires_at` (TTL = 15 min).
2. Approval row written in `admin_approvals` collection. Audit row
   written with `outcome=PENDING`.
3. Admin B fetches `GET /api/v2/admin/approvals?mine=true`, reviews
   diff, and POSTs `/approvals/{id}/approve` or `/reject`.
4. On approve: backend re-validates the original payload, runs the
   action atomically, links both audit rows via `approval_id`.
5. On expiry / reject: action is dropped, both audit rows finalised
   with their outcome.

Admin A cannot self-approve (server-checked). Approvals cannot be
edited or replayed.

---

## 11. Frontend Plan

### 11.1 Routing

```
/admin                → /admin/login (if no session) | /admin/dashboard
/admin/login          → email + password → MFA → dashboard
/admin/dashboard      → metric cards + time-series
/admin/users          → searchable, filterable list
/admin/users/:id      → detail + actions
/admin/tables         → live list (auto-refresh)
/admin/tables/:id     → spectate + control
/admin/finance        → house balance, rake config, ledger
/admin/events         → list + create + grants
/admin/safety         → kill-switch, flags, regions
/admin/audit          → searchable audit log + verify
/admin/approvals      → pending approvals queue
```

Separate React Router tree, mounted by the existing `BrowserRouter`
under `/admin/*`. The admin chunk is code-split (`React.lazy`) so the
player bundle stays small and admin code is never shipped to non-admin
visitors.

### 11.2 State / data layer

- TanStack Query for server state with a 5 s default refetch on the
  dashboard and 1 s on the live tables list.
- A NEW `adminApi.js` axios instance bound to `/api/v2/admin` with the
  admin JWT auto-attached and a 401 → re-login redirect interceptor.
- Spectate WS uses a dedicated `useAdminSpectate(tableId)` hook that
  mirrors `usePlayChannel` from the existing PlayPage.

### 11.3 Component reuse

Tables, dialogs, badges, tooltips → reuse existing shadcn/ui from
`/app/frontend/src/components/ui/`. No new design system. Only the
**colour token** changes for the admin theme: a desaturated slate
palette so admins never confuse the admin surface with the player
table.

### 11.4 Critical UX guards

- Confirm-by-typing on destructive actions (`block_permanent`,
  `kill_switch`, `force_stop`). User must type the resource name.
- Two-admin approval shows a real-time pending-approvals badge in the
  global header (driven by a long-poll or a server-sent events
  channel).
- Every page with PII (`/admin/users/:id`) shows a redaction toggle
  defaulting to redacted; the un-redact action itself is audited.

---

## 12. Security Posture

| Control                              | Implementation                                                                              |
|--------------------------------------|---------------------------------------------------------------------------------------------|
| Separate JWT audience                | `aud=admin`; player tokens rejected by admin routes and vice-versa.                         |
| Mandatory MFA                        | TOTP enforced at login; no opt-out.                                                         |
| Short access-token TTL               | 15 min; refresh token bound to IP + UA hash.                                                |
| IP allow-list                        | Optional global env var + per-admin override.                                               |
| Two-person rule                      | All financial / kill-switch / role-grant actions.                                           |
| Append-only audit                    | Hash-chained, anchored, audit-first invariant.                                              |
| Confirm-by-typing                    | Destructive UI actions.                                                                     |
| Rate limiting                        | Per-admin + per-IP (FastAPI middleware).                                                    |
| Egress redaction                     | PII fields wrapped in `RedactedString` Pydantic type — opt-in unwrap with audit.            |
| Bootstrap path                       | CLI only; refuses to run if any admin row exists.                                           |
| Cookie path scope                    | `path=/api/v2/admin` so a leaked admin cookie cannot reach player routes (and vice-versa).  |
| TLS / HSTS                           | Enforced at the proxy layer (existing).                                                     |
| Player WS isolation                  | Spectate channel served from a separate gateway path with admin-only auth.                  |
| Replay-attack on session_token       | Cookie + DB session check on every request; revoked on logout / role change.                |
| Privilege escalation defense         | `admin:grant_role` is super_admin only AND requires two-admin approval AND IP allow-list.   |

---

## 13. Sequenced Implementation Plan (after this design is approved)

> Order is deliberate — every step is testable in isolation and ships
> behind a feature flag. No step changes the live game until §13.6.

| # | Slice                                              | Touches                                                              | Verifiable by |
|--:|----------------------------------------------------|----------------------------------------------------------------------|---------------|
| 1 | Audit log + hash chain + bootstrap CLI             | `admin/audit.py`, `admin/bootstrap.py`, new collections               | pytest        |
| 2 | Admin auth (login, MFA, JWT, RBAC decorator)       | `admin/auth.py`, `admin/rbac.py`, `admin/routes/auth_router.py`       | pytest + curl |
| 3 | Approvals workflow                                 | `admin/approvals.py` + collection                                    | pytest        |
| 4 | Dashboard read-only (counters fan-out hook)        | `event_log/writer.py` (additive), `admin/services/dashboard.py`      | pytest        |
| 5 | Users list + detail + suspend/block (no balance)   | `admin/services/users.py`, `user_moderation` collection              | pytest + UI   |
| 6 | Force-logout via admin pubsub channel              | `realtime_v2/admin_channel.py`, `realtime_v2/gateway.py` (additive)  | E2E pytest    |
| 7 | Live tables list + spectate                        | `realtime_v2/bridge.py` admin view (additive), `admin/services/tables.py` | E2E pytest |
| 8 | Force-stop / freeze / remove-player (reducer ext.) | `reducer.py` (controlled extension, gated by `safety:kill_switch`)   | pytest + E2E  |
| 9 | Finance: house ledger + economics + rake config    | `admin/services/finance.py`, two new collections                     | pytest        |
| 10| Events / campaigns                                 | `admin/services/events.py`, two new collections                      | pytest        |
| 11| Safety: kill-switch, flags, regions                | `admin/services/safety.py` + `platform_state`, `platform_flags`      | E2E pytest    |
| 12| Frontend `/admin` route tree + login + dashboard   | `frontend/src/admin/` new tree                                       | screenshots   |
| 13| Frontend pages: users, tables, finance, events     | as above                                                             | screenshots   |
| 14| Frontend pages: safety, audit, approvals           | as above                                                             | screenshots   |
| 15| Penetration / role-confusion test pass             | `admin/tests/test_security_*.py`                                     | pytest        |

Each slice ends with a green pytest run AND zero diff to the player
suite. The admin UI is gated behind `ADMIN_ENABLED=1` env var until §15
clears.

---

## 14. What this design DOES NOT do (explicitly out of scope for v1)

- Real-money payment integrations (deposit/withdraw, KYC/AML providers).
- ML risk scoring (we provide hooks, not models).
- Streaming analytics (we provide aggregation pipelines, not Kafka).
- Multi-tenant / white-label support.
- Telegram / Web3 admin surfaces.
- Custom-role builder UI (matrix is code-defined in v1; runtime roles in v2).
- External SIEM / SOC2 integration (audit log is locally hash-chained;
  external WORM bucket is a v1.1 concern).

---

## 15. Open questions for product approval

1. **Bootstrap admin email** — what real human address owns the
   first super_admin row in production?
2. **Rake currency at launch** — credits-only, or a real-money
   currency on day 1? Determines whether `house_ledger` needs a
   currency-aware Pydantic type from v1.
3. **Region blocking enforcement layer** — do we trust the WS gateway's
   IP geo, or hard-block at the Cloudflare edge? (Recommendation:
   both; gateway is failsafe.)
4. **Self-exclusion legal regime** — must a self-excluded user be able
   to log in just to view their wallet/closeout, or is account fully
   inaccessible? (Affects `self_exclusion` flag's effect surface.)
5. **Audit retention** — 1 year? 7 years (gambling regs)? Forever?
   Drives index strategy + cold-storage choice.
6. **Two-person window TTL** — 15 min default proposed. Acceptable?
7. **Emergency single-admin override** — should a super_admin be able
   to engage the kill-switch alone in a P0 incident? (Recommendation:
   yes, but post-hoc audit + immediate Slack page.)

Awaiting answers before §13.1 kicks off.
