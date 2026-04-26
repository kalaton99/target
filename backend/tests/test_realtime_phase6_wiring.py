"""Phase 6 — FastAPI wiring tests for realtime_v2.

Two layers:
  1. Self-contained mini-app driving `build_v2_router` directly with
     fake auth/state/handler — proves the router contract over a real
     FastAPI WebSocket transport (TestClient).
  2. Smoke test against the real `server.app` proving:
       - the v2 router is mounted at /api/v2/*
       - the WS route at /api/v2/ws/table/{id} accepts a valid JWT
       - the WS route rejects an invalid JWT with AUTH_FAILED + close

Both layers are required:
  - layer 1 is hermetic and verifies semantics in isolation.
  - layer 2 verifies that `server.py` actually mounts the new router
    alongside the legacy one and that auth uses real JWT decoding.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from realtime_v2.asgi import build_v2_router  # noqa: E402


# ============================================================
# Layer 1 — hermetic mini-app with fake injectables
# ============================================================

VALID = {"good-token": "user-x"}


async def fake_auth(token: str):
    return VALID.get(token)


async def fake_sv(_table_id: str):
    return 7


async def fake_handler(table_id, user_id, action, payload, sv):
    return {"echo": action, "user_id": user_id, "sv": sv}


@pytest.fixture
def mini_app():
    router = build_v2_router(
        authenticate=fake_auth,
        get_state_version=fake_sv,
        handle_action=fake_handler,
    )
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


class TestRouterHealth:

    def test_health_endpoint_responds(self, mini_app):
        client = TestClient(mini_app)
        r = client.get("/api/v2/realtime/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["subsystem"] == "realtime_v2"
        assert body["active_connections"] == 0
        assert body["max_per_user"] >= 1
        assert body["max_per_ip"] >= 1


class TestRouterValidConnection:

    def test_valid_token_receives_welcome(self, mini_app):
        client = TestClient(mini_app)
        with client.websocket_connect(
            "/api/v2/ws/table/t1?token=good-token",
        ) as ws:
            msg = ws.receive_json()
            assert msg["type"] == "WELCOME"
            assert msg["user_id"] == "user-x"
            assert msg["table_id"] == "t1"
            assert msg["state_version"] == 7

    def test_valid_action_round_trip(self, mini_app):
        client = TestClient(mini_app)
        with client.websocket_connect(
            "/api/v2/ws/table/t1?token=good-token",
        ) as ws:
            ws.receive_json()  # WELCOME
            ws.send_json({
                "type": "STAND",
                "state_version": 7,
                "payload": {"hand_id": "h1"},
            })
            ack = ws.receive_json()
            assert ack["type"] == "ACTION_ACK"
            assert ack["action"] == "STAND"
            assert ack["result"]["echo"] == "STAND"
            assert ack["result"]["user_id"] == "user-x"
            assert ack["result"]["sv"] == 7

    def test_stale_state_version_returns_out_of_sync(self, mini_app):
        client = TestClient(mini_app)
        with client.websocket_connect(
            "/api/v2/ws/table/t1?token=good-token",
        ) as ws:
            ws.receive_json()  # WELCOME
            ws.send_json({"type": "HIT", "state_version": 1, "payload": {}})
            err = ws.receive_json()
            assert err["type"] == "OUT_OF_SYNC"
            assert err["received_state_version"] == 1
            assert err["current_state_version"] == 7


class TestRouterInvalidToken:

    def test_invalid_token_receives_auth_failed_and_closes(self, mini_app):
        client = TestClient(mini_app)
        from starlette.websockets import WebSocketDisconnect

        with client.websocket_connect(
            "/api/v2/ws/table/t1?token=bad-token",
        ) as ws:
            msg = ws.receive_json()
            assert msg["type"] == "ERROR"
            assert msg["code"] == "AUTH_FAILED"
            # Server must follow up with a close — next receive raises.
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()

    def test_missing_token_receives_auth_failed_and_closes(self, mini_app):
        client = TestClient(mini_app)
        from starlette.websockets import WebSocketDisconnect

        with client.websocket_connect("/api/v2/ws/table/t1") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "ERROR"
            assert msg["code"] == "AUTH_FAILED"
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()


# ============================================================
# Layer 2 — smoke test against the actual server.app
# ============================================================

class TestServerWiring:
    """Imports `server` to verify the v2 router is mounted on the
    real application graph alongside legacy routes."""

    def _client(self):
        # Lazy import — the module-level imports in server.py must succeed.
        import server  # noqa: WPS433
        return TestClient(server.app)

    def test_realtime_v2_health_is_mounted(self):
        client = self._client()
        r = client.get("/api/v2/realtime/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["subsystem"] == "realtime_v2"

    def test_legacy_health_still_works(self):
        client = self._client()
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}

    def test_real_jwt_valid_token_accepted(self):
        """Mint a real JWT using core.security and use it to connect."""
        from core.security import create_token
        token = create_token("u_phase6_wiring_user")

        client = self._client()
        with client.websocket_connect(
            f"/api/v2/ws/table/t1?token={token}",
        ) as ws:
            msg = ws.receive_json()
            assert msg["type"] == "WELCOME"
            assert msg["user_id"] == "u_phase6_wiring_user"
            assert msg["table_id"] == "t1"
            assert msg["state_version"] == 0  # stub provider

    def test_real_jwt_invalid_token_rejected(self):
        from starlette.websockets import WebSocketDisconnect

        client = self._client()
        with client.websocket_connect(
            "/api/v2/ws/table/t1?token=this-is-not-a-real-jwt",
        ) as ws:
            msg = ws.receive_json()
            assert msg["type"] == "ERROR"
            assert msg["code"] == "AUTH_FAILED"
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()

    def test_real_jwt_missing_token_rejected(self):
        from starlette.websockets import WebSocketDisconnect

        client = self._client()
        with client.websocket_connect("/api/v2/ws/table/t1") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "ERROR"
            assert msg["code"] == "AUTH_FAILED"
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()
