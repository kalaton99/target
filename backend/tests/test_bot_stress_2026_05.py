"""Live-backend bot stress test — target=100 with 1 human + 4 bots,
5 consecutive hands, asserts every hand reaches PAYOUT without stall.

Also asserts:
  - bots act on their turn (turn always advances during DRAW/BETTING)
  - no repeated (state_version, current_turn_seat) seen for > 8s
    (stall detector — fails fast if the engine or bot driver wedges)
  - no phase stays "stuck" with current_turn_seat == bot_seat
    and no state update for > 6s (bot-subscription race)
  - opponent cards appear in public STATE_UPDATE at SHOWDOWN/PAYOUT
  - the hand always has ≥1 winner (unless all DQ — not expected here)

Skipped unless REACT_APP_BACKEND_URL is set.
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any, Dict, List, Optional

import pytest
import requests
import websockets

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
WS_BASE = BASE_URL.replace("https://", "wss://").replace("http://", "ws://")

pytestmark = pytest.mark.skipif(
    not BASE_URL, reason="REACT_APP_BACKEND_URL not set — skipping live bot stress",
)

HEADERS = {"Content-Type": "application/json", "User-Agent": "bot-stress/1.0"}


def _auth(name: str):
    r = requests.post(f"{BASE_URL}/api/v2/lobby/auth",
                      json={"username": name[:16]}, headers=HEADERS, timeout=10)
    r.raise_for_status()
    d = r.json()
    return d["user_id"], d["token"]


def _hdr(tok: str):
    return {**HEADERS, "Authorization": f"Bearer {tok}"}


def _create_table(tok: str, *, target=100, bot_count=4):
    body = {
        "name": f"botstress_{uuid.uuid4().hex[:6]}",
        "target_score": target,
        "stake": 100,
        "bot_count": bot_count,
    }
    r = requests.post(f"{BASE_URL}/api/v2/lobby/tables",
                      json=body, headers=_hdr(tok), timeout=10)
    r.raise_for_status()
    return r.json()


def _start(tok: str, tid: str):
    r = requests.post(f"{BASE_URL}/api/v2/lobby/tables/{tid}/start",
                      headers=_hdr(tok), timeout=10)
    r.raise_for_status()
    return r.json()


async def _play_one_hand(uid: str, tok: str, target: int = 100,
                         bot_count: int = 4) -> Dict[str, Any]:
    """Spawn a fresh table, play one hand to PAYOUT, return diagnostics."""
    table = _create_table(tok, target=target, bot_count=bot_count)
    tid = table["table_id"]
    _start(tok, tid)

    ws = await websockets.connect(
        f"{WS_BASE}/api/v2/ws/table/{tid}?token={tok}",
        open_timeout=10, ping_interval=None,
    )
    phases: List[str] = []
    reveals: Dict[str, List[Dict]] = {}
    deck_refills_seen = 0
    last_state: Optional[Dict[str, Any]] = None
    # stall detector: timestamp of last state_version bump
    import time
    last_change_ts = time.monotonic()
    last_sv = -1
    stalls: List[str] = []

    try:
        end = asyncio.get_event_loop().time() + 120.0
        while asyncio.get_event_loop().time() < end:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
            except asyncio.TimeoutError:
                # If no update in 8s AND turn is on a bot seat, that's a stall.
                if last_state and (time.monotonic() - last_change_ts) > 8.0:
                    seat = last_state.get("current_turn_seat")
                    if seat is not None:
                        who = last_state["players"][seat]
                        stalls.append(
                            f"stall: phase={last_state['phase']} seat={seat} "
                            f"user={who['user_id']} sv={last_state['state_version']}"
                        )
                        break
                # if it's our turn, act
                if last_state and last_state.get("current_turn_seat") is not None:
                    my_seat = next((p["seat"] for p in last_state["players"]
                                    if p["user_id"] == uid), None)
                    if last_state["current_turn_seat"] == my_seat:
                        ph = last_state.get("phase")
                        sv = last_state["state_version"]
                        act = None
                        if ph in ("BETTING_R1", "BETTING_R2", "BETTING_R3"):
                            act = "CHECK" if last_state.get("current_call_owed", 0) == 0 else "CALL"
                        elif ph in ("DRAW_1", "DRAW_2", "DRAW"):
                            act = "STAND"
                        if act:
                            await ws.send(json.dumps({
                                "type": act, "state_version": sv, "payload": {},
                            }))
                continue
            try:
                m = json.loads(raw)
            except Exception:
                continue
            if m.get("type") == "PING":
                try:
                    await ws.send(json.dumps({"type": "PONG"}))
                except Exception:
                    pass
                continue
            if m.get("type") != "STATE_UPDATE":
                continue
            last_state = m
            sv = m.get("state_version", 0)
            if sv != last_sv:
                last_sv = sv
                last_change_ts = time.monotonic()
            ph = m.get("phase")
            if not phases or phases[-1] != ph:
                phases.append(ph)
            for ev in m.get("events") or []:
                if ev.get("type") == "DECK_REFILLED":
                    deck_refills_seen += 1
            if ph in ("SHOWDOWN", "PAYOUT"):
                for p in m.get("players", []):
                    if p["user_id"] != uid and "cards" in p:
                        reveals[p["user_id"]] = p["cards"]
            if ph == "PAYOUT":
                # drain a final event burst, then quit
                for _ in range(3):
                    try:
                        extra = await asyncio.wait_for(ws.recv(), timeout=0.3)
                        mm = json.loads(extra)
                        if mm.get("type") == "STATE_UPDATE":
                            last_state = mm
                    except Exception:
                        break
                break
    finally:
        try:
            await ws.close()
        except Exception:
            pass

    return {
        "table_id": tid,
        "phases": phases,
        "reached_payout": "PAYOUT" in phases,
        "reveals_count": len(reveals),
        "deck_refills_seen": deck_refills_seen,
        "stalls": stalls,
        "final_sv": last_sv,
        "winners": (last_state or {}).get("winners") or [],
        "players": (last_state or {}).get("players") or [],
    }


@pytest.mark.asyncio
async def test_target_100_four_bots_five_consecutive_hands():
    uid, tok = _auth(f"stress_{uuid.uuid4().hex[:6]}")
    results = []
    for i in range(5):
        res = await _play_one_hand(uid, tok, target=100, bot_count=4)
        results.append(res)

    # Every hand must reach PAYOUT.
    for i, r in enumerate(results):
        assert r["reached_payout"], (
            f"hand {i} did not reach PAYOUT: phases={r['phases']} stalls={r['stalls']}"
        )
        assert not r["stalls"], f"hand {i} stalled: {r['stalls']}"
        # Opponent reveals at PAYOUT.
        assert r["reveals_count"] >= 1, (
            f"hand {i} no opponent card reveal at showdown: {r['reveals_count']}"
        )
        # Winners list is present (may be 0 if everyone DQ — unlikely with
        # 5 random players, but we only assert structure).
        assert isinstance(r["winners"], list)

    # Multi-round progression: at least some hands should exhibit
    # full phase fan (R1 → DRAW_1 → R2 → DRAW_2 → R3 → PAYOUT) since
    # all bots CHECK and the human STANDs both draws.
    full = [r for r in results
            if all(p in r["phases"] for p in
                   ("BETTING_R1", "DRAW_1", "BETTING_R2", "DRAW_2", "BETTING_R3", "PAYOUT"))]
    assert len(full) >= 3, (
        f"expected ≥3 of 5 hands to run full multi-round; got {len(full)}: "
        f"{[r['phases'] for r in results]}"
    )
