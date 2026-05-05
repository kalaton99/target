# Auth Testing Playbook (Emergent Google OAuth)

## Setup test session in Mongo
```
mongosh --eval "
use('target_db');
var uid = 'test-user-' + Date.now();
var sessionToken = 'test_session_' + Date.now();
db.users.insertOne({user_id: uid, email: 'test.' + Date.now() + '@example.com', name: 'Test User', picture: '', auth_provider: 'google', created_at: new Date()});
db.user_sessions.insertOne({user_id: uid, session_token: sessionToken, expires_at: new Date(Date.now() + 7*24*60*60*1000), created_at: new Date()});
print('user_id: ' + uid);
print('session_token: ' + sessionToken);
"
```

## Backend
- `GET /api/v2/auth/me` — accepts cookie `session_token` OR `Authorization: Bearer <token>`. Returns 200 + user, or 401.
- `POST /api/v2/auth/google/session` — body: `{session_id}`. Calls Emergent, persists user + session, sets cookie, returns `{user, jwt}`.
- `POST /api/v2/auth/logout` — clears cookie + deletes session.
- Guest path `POST /api/v2/lobby/auth` still works (gated by `ALLOW_GUEST_AUTH` env var).

## WebSocket
- `wss://.../api/v2/ws/table/{id}?token=<jwt>` — `<jwt>` is either the legacy guest JWT or the JWT minted alongside the Google session.

## Browser flow
1. Visit `/lobby` → "Continue with Google" → redirected to `https://auth.emergentagent.com/?redirect=...`
2. Land back at `/lobby#session_id=...` — frontend detects synchronously during render.
3. AuthCallback POSTs `/api/v2/auth/google/session` with `{session_id}`. Backend exchanges via X-Session-ID header to Emergent, sets cookie, returns JWT. Frontend stores JWT in localStorage.
4. Refresh — cookie still valid; `/api/v2/auth/me` returns user.
5. Logout — clears cookie + JWT.

## Allowed Google test accounts
None — pre-registered Google identities (any Google-auth email is accepted; users are created on first login).
