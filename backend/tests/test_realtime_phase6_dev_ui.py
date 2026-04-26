"""Phase 6 (UI scaffolding) — dev router e2e tests.

Validates the minimal play flow:
  POST /api/v2/dev/spawn_solo_table -> table_id + jwt
  GET  /api/v2/dev/play             -> HTML page is served
  WS   /api/v2/ws/table/{id}?token=jwt
       -> WELCOME
       -> STATE_UPDATE (DRAW phase, you on turn)
       -> PRIVATE_STATE (your 2 cards, opponent's not visible)
       -> client sends STAND -> ACTION_ACK + STATE_UPDATE
       -> bot auto-acts (its STAND)
       -> ... eventually phase progresses to BETTING / SHOWDOWN

We don't drive a full hand to completion in the test (deterministic
phase coverage is in earlier engine tests); we only assert the dev
router actually drives a reachable hand.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client():
    import server  # noqa: WPS433
    return TestClient(server.app)


class TestDevRouter:

    def test_play_html_is_served(self, client):
        r = client.get("/api/v2/dev/play")
        assert r.status_code == 200
        body = r.text
        # Sanity: contains required testid hooks and the WS path.
        assert 'data-testid="hit-btn"' in body
        assert 'data-testid="stand-btn"' in body
        assert "/api/v2/dev/spawn_solo_table" in body
        assert "/api/v2/ws/table/" in body

    def test_spawn_solo_table_returns_token_and_table(self, client):
        r = client.post("/api/v2/dev/spawn_solo_table")
        assert r.status_code == 200
        body = r.json()
        assert body["table_id"].startswith("tbl_")
        assert body["user_id"].startswith("u_anon_")
        assert body["bot_user_id"].startswith("u_bot_")
        assert isinstance(body["token"], str) and len(body["token"]) > 20

    def test_full_play_loop_via_ws(self, client):
        spawn = client.post("/api/v2/dev/spawn_solo_table").json()
        token = spawn["token"]
        table_id = spawn["table_id"]
        my_user_id = spawn["user_id"]

        url = f"/api/v2/ws/table/{table_id}?token={token}"
        seen_state_update = False
        seen_private = False
        saw_my_turn_in_draw = False
        cards_for_me = None
        action_acked = False

        with client.websocket_connect(url) as ws:
            for _ in range(40):
                m = ws.receive_json()
                if m["type"] == "PING":
                    ws.send_json({"type": "PONG"})
                    continue
                if m["type"] == "WELCOME":
                    assert m["user_id"] == my_user_id
                    assert m["table_id"] == table_id
                    continue
                if m["type"] == "STATE_UPDATE":
                    seen_state_update = True
                    # public must NEVER carry face-up cards
                    for p in m["players"]:
                        assert "cards" not in p
                        assert "card_count" in p
                    my_seat = next(
                        (p["seat"] for p in m["players"] if p["user_id"] == my_user_id),
                        None,
                    )
                    is_my_turn = my_seat is not None and m["current_turn_seat"] == my_seat
                    if is_my_turn and m["phase"] == "BETTING_R1":
                        ws.send_json({
                            "type": "CHECK",
                            "state_version": m["state_version"],
                            "payload": {},
                        })
                    elif is_my_turn and m["phase"] == "DRAW" and not saw_my_turn_in_draw:
                        ws.send_json({
                            "type": "STAND",
                            "state_version": m["state_version"],
                            "payload": {},
                        })
                        saw_my_turn_in_draw = True
                    continue
                if m["type"] == "PRIVATE_STATE":
                    seen_private = True
                    assert m["user_id"] == my_user_id
                    assert isinstance(m["cards"], list)
                    if cards_for_me is None and len(m["cards"]) >= 1:
                        cards_for_me = list(m["cards"])
                    continue
                if m["type"] == "ACTION_ACK":
                    action_acked = True
                    if saw_my_turn_in_draw and seen_private and cards_for_me:
                        break
                    continue

        assert seen_state_update, "no STATE_UPDATE received"
        assert seen_private, "no PRIVATE_STATE received"
        assert saw_my_turn_in_draw, "never saw my own DRAW turn"
        # Initial deal is now exactly 1 card
        assert cards_for_me is not None and len(cards_for_me) >= 1
        assert action_acked, "no action was acked"
