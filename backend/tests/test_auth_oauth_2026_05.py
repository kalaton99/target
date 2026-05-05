"""2026-05 v2 — Emergent Google OAuth tests.

Two layers:
  1. Live-HTTP against the running supervisor backend (negative cases —
     no upstream call needed).
  2. ASGI-level test using `httpx.AsyncClient + ASGITransport` so the
     mocked Emergent exchange runs in the same event loop as motor.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

import httpx
import pytest
import requests

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
API = f"{BASE_URL}/api" if BASE_URL else None

pytestmark = pytest.mark.skipif(
    not BASE_URL, reason="REACT_APP_BACKEND_URL required",
)


# ============================================================
# Live-HTTP negatives (cheap)
# ============================================================

def test_me_unauthenticated_returns_401():
    r = requests.get(f"{API}/v2/auth/me", timeout=10)
    assert r.status_code == 401


def test_google_session_invalid_session_id():
    r = requests.post(f"{API}/v2/auth/google/session",
                      json={"session_id": "x"}, timeout=10)
    assert r.status_code == 401
    assert r.json()["detail"] == "OAUTH_EXCHANGE_FAILED"


def test_guest_auth_default_on():
    name = f"GuestZ{int(datetime.now().timestamp()) % 100000}"  # ≤ 16 chars
    r = requests.post(f"{API}/v2/lobby/auth", json={"username": name}, timeout=10)
    assert r.status_code == 200, r.text
    assert "token" in r.json()


# ============================================================
# ASGI mocked flow
# ============================================================

class _FakeResp:
    status_code = 200
    text = "ok"
    def __init__(self, payload):
        self._p = payload
    def json(self):
        return self._p


def _patched_async_client(payload):
    """Build a context-manager-friendly mock for `httpx.AsyncClient(...)`.
    Returns the patcher object + the AsyncMock for the GET call.
    """
    instance = MagicMock()
    instance.get = AsyncMock(return_value=_FakeResp(payload))
    cls_mock = MagicMock()
    cls_mock.return_value.__aenter__.return_value = instance
    cls_mock.return_value.__aexit__.return_value = False
    return patch("auth_oauth.router.httpx.AsyncClient", cls_mock), instance


@pytest.mark.asyncio
async def test_google_full_flow_and_lobby_bridge(monkeypatch):
    monkeypatch.setenv("OAUTH_COOKIE_SECURE", "0")
    from server import app
    from core import db as core_db

    email = f"oauth_test_{int(datetime.now().timestamp())}@example.com"
    await core_db.db.users.delete_many({"email": email})

    payload = {
        "email": email,
        "name": "Alice",
        "picture": "https://example.com/p.png",
        "session_token": "t_session_alice_12345",
    }

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver",
    ) as client:
        # Negative — /me with no auth.
        r = await client.get("/api/v2/auth/me")
        assert r.status_code == 401

        # Positive — exchange.
        patcher, _ = _patched_async_client(payload)
        with patcher:
            r = await client.post("/api/v2/auth/google/session",
                                  json={"session_id": "fake"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["user"]["email"] == email
        assert body["user"]["name"] == "Alice"
        assert body["user"]["auth_provider"] == "google"
        jwt = body["jwt"]
        assert isinstance(jwt, str) and len(jwt) > 16

        # Cookie set on the client.
        assert "session_token" in client.cookies, dict(client.cookies)

        # /me via cookie.
        r = await client.get("/api/v2/auth/me")
        assert r.status_code == 200
        assert r.json()["email"] == email

        # /me via Bearer (no cookie).
        client.cookies.clear()
        r = await client.get(
            "/api/v2/auth/me",
            headers={"Authorization": f"Bearer {jwt}"},
        )
        assert r.status_code == 200
        assert r.json()["email"] == email

        # Lobby bridge — OAuth user creates a table with the JWT.
        r = await client.post(
            "/api/v2/lobby/tables",
            headers={"Authorization": f"Bearer {jwt}"},
            json={"name": "oauth_smoke", "target_score": 50,
                  "stake": 100, "bot_count": 1},
        )
        assert r.status_code == 201, r.text
        assert r.json()["target_score"] == 50

        # Logout — re-establish cookie via fresh exchange first.
        patcher, _ = _patched_async_client(payload)
        with patcher:
            await client.post("/api/v2/auth/google/session",
                              json={"session_id": "fake"})
        assert "session_token" in client.cookies
        r = await client.post("/api/v2/auth/logout")
        assert r.status_code == 200
        assert r.json() == {"ok": True}


@pytest.mark.asyncio
async def test_guest_auth_disabled_blocks_lobby_auth(monkeypatch):
    from server import app

    monkeypatch.setenv("ALLOW_GUEST_AUTH", "0")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver",
    ) as client:
        r = await client.post("/api/v2/lobby/auth",
                              json={"username": "blockedGuest"})
        assert r.status_code == 403, r.text
        assert "GUEST_AUTH_DISABLED" in str(r.json()["detail"])
