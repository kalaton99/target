"""Phase 11 P3 — Regression tests for auth persistence (lobby ↔ play).

Codifies the API contract that `LobbyPage` writes to and `PlayPage` reads
from. Frontend-side specifics (localStorage, routing) live in the UI tests
but the data shape, status codes and lifecycle transitions exercised here
are exactly what the UI relies on. If any of these regress, the
"Not signed in" / waiting-room fix breaks.

Hits the live supervisor backend (REACT_APP_BACKEND_URL).
"""
from __future__ import annotations

import os
import uuid

import pytest
import requests

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://gracious-raman-3.preview.emergentagent.com",
).rstrip("/")
API = f"{BASE_URL}/api"

TIMEOUT = 10


def _name(prefix):
    # Username max length is 16 chars — keep prefix+suffix within bounds.
    return f"{prefix}_{uuid.uuid4().hex[:6]}"[:16]


def _auth(username):
    r = requests.post(f"{API}/v2/lobby/auth", json={"username": username}, timeout=TIMEOUT)
    assert r.status_code == 200, r.text
    return r.json()


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def _create_table(token, **overrides):
    body = {
        "name": _name("Room"),
        "target_score": 30,
        "stake": 100,
        "max_players": 2,
        "min_players": 2,
    }
    body.update(overrides)
    r = requests.post(f"{API}/v2/lobby/tables", headers=_h(token), json=body, timeout=TIMEOUT)
    return r


# ============================================================
# Token shape — what LobbyPage writes to localStorage["target_user"]
# ============================================================

class TestAuthResponseShape:
    """LobbyPage stringifies the /auth response straight into
    localStorage["target_user"]; PlayPage destructures user_id, username,
    token. If any field disappears the regression returns."""

    def test_auth_returns_required_fields(self):
        u = _auth(_name("auth_shape"))
        assert "user_id" in u and isinstance(u["user_id"], str)
        assert "username" in u and isinstance(u["username"], str)
        assert "token" in u and isinstance(u["token"], str)
        assert u["user_id"].startswith("u_")
        assert len(u["token"]) > 30

    def test_auth_is_idempotent_for_same_username(self):
        # Refresh of /play/:tableId re-uses the persisted token; if the
        # same username produced different user_ids on each call, the
        # frontend would lose its seat reference after a reconnect.
        name = _name("idem_user")
        a = _auth(name)
        b = _auth(name)
        assert a["user_id"] == b["user_id"]
        # token may differ (new JWT), but BOTH must validate against /me.
        for tok in (a["token"], b["token"]):
            r = requests.get(f"{API}/v2/lobby/me", headers=_h(tok), timeout=TIMEOUT)
            assert r.status_code == 200, r.text


# ============================================================
# /me — token validation gate used by PlayPage on mount
# ============================================================

class TestTokenValidation:
    def test_valid_token_accepted_by_me(self):
        u = _auth(_name("valid_tok"))
        r = requests.get(f"{API}/v2/lobby/me", headers=_h(u["token"]), timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        assert r.json()["user_id"] == u["user_id"]

    def test_missing_token_rejected_by_me(self):
        r = requests.get(f"{API}/v2/lobby/me", timeout=TIMEOUT)
        assert r.status_code == 401

    def test_garbage_token_rejected_by_me(self):
        # PlayPage triggers the redirect-to-/lobby?msg=session_expired
        # branch on this exact 401.
        r = requests.get(
            f"{API}/v2/lobby/me",
            headers=_h("not-a-real-jwt"),
            timeout=TIMEOUT,
        )
        assert r.status_code == 401


# ============================================================
# Waiting-room contract — table doc readable while LOBBY (no auth)
# ============================================================

class TestWaitingRoomContract:
    def test_get_table_public_during_lobby(self):
        u = _auth(_name("wr_lob"))
        t = _create_table(u["token"]).json()
        # PlayPage polls this endpoint without auth.
        r = requests.get(f"{API}/v2/lobby/tables/{t['table_id']}", timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "LOBBY"
        # Fields the waiting-room UI binds to:
        for k in ("table_id", "name", "creator_user_id", "target_score",
                  "stake", "max_players", "min_players", "seats"):
            assert k in body, f"missing field {k}"
        assert any(s["user_id"] == u["user_id"] for s in body["seats"])

    def test_table_status_lobby_then_running_after_start(self):
        # Models the exact transition the waiting-room polls for: LOBBY →
        # RUNNING. PlayPage is forbidden from opening the WS until RUNNING.
        u1 = _auth(_name("trans1"))
        u2 = _auth(_name("trans2"))
        t = _create_table(u1["token"]).json()
        requests.post(
            f"{API}/v2/lobby/tables/{t['table_id']}/join",
            headers=_h(u2["token"]), timeout=TIMEOUT,
        )
        # Pre-start: LOBBY
        pre = requests.get(f"{API}/v2/lobby/tables/{t['table_id']}", timeout=TIMEOUT).json()
        assert pre["status"] == "LOBBY"
        # Creator starts
        r = requests.post(
            f"{API}/v2/lobby/tables/{t['table_id']}/start",
            headers=_h(u1["token"]), timeout=TIMEOUT,
        )
        assert r.status_code == 200, r.text
        # Post-start: RUNNING (the only condition under which PlayPage
        # opens the WebSocket).
        post = requests.get(f"{API}/v2/lobby/tables/{t['table_id']}", timeout=TIMEOUT).json()
        assert post["status"] == "RUNNING"

    def test_unknown_table_returns_404_not_signedin_state(self):
        # Confirms the waiting-room "Table not found" branch can be
        # distinguished from the auth branch.
        r = requests.get(f"{API}/v2/lobby/tables/tbl_does_not_exist", timeout=TIMEOUT)
        assert r.status_code == 404


# ============================================================
# Refresh semantics — same persisted token still works against /me
# ============================================================

class TestRefreshKeepsSession:
    def test_token_still_validates_after_simulated_refresh(self):
        # Simulates: user signs in, navigates to /play/:tableId, refreshes.
        # PlayPage will re-read localStorage and re-call /me. The same
        # token must continue to validate AND the same user must remain
        # in the table's seat list.
        u = _auth(_name("refresh"))
        t = _create_table(u["token"]).json()

        # First /me — initial mount of /play/:tableId
        r1 = requests.get(f"{API}/v2/lobby/me", headers=_h(u["token"]), timeout=TIMEOUT)
        assert r1.status_code == 200

        # Imagine a browser refresh; token persists in localStorage.
        # Re-call /me with the SAME token.
        r2 = requests.get(f"{API}/v2/lobby/me", headers=_h(u["token"]), timeout=TIMEOUT)
        assert r2.status_code == 200
        assert r2.json()["user_id"] == u["user_id"]

        # Table doc still shows the user seated.
        body = requests.get(f"{API}/v2/lobby/tables/{t['table_id']}", timeout=TIMEOUT).json()
        assert any(s["user_id"] == u["user_id"] for s in body["seats"])
