"""Phase 11 multi-round betting validation — live backend tests (F1–F11).

Runs against REACT_APP_BACKEND_URL. No code changes; validation only.
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any, Dict, List, Optional, Tuple

import pytest
import requests
import websockets

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
WS_BASE = BASE_URL.replace("https://", "wss://").replace("http://", "ws://")
HEADERS = {"User-Agent": "TARGET-Test/1.0", "Content-Type": "application/json"}


def _auth(name: str) -> Tuple[str, str]:
    r = requests.post(f"{BASE_URL}/api/v2/lobby/auth",
                      json={"username": name[:16]}, headers=HEADERS, timeout=10)
    r.raise_for_status()
    d = r.json()
    return d["user_id"], d["token"]


def _mk_name(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:6]}"


def _hdr(tok: str) -> Dict[str, str]:
    return {**HEADERS, "Authorization": f"Bearer {tok}"}


def _create_table(tok: str, *, target: int = 30, stake: int = 100,
                  bot_count: int = 0, name: Optional[str] = None,
                  max_players: Optional[int] = None) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "name": name or _mk_name("T_"),
        "target_score": target,
        "stake": stake,
        "bot_count": bot_count,
    }
    if max_players is not None:
        body["max_players"] = max_players
    r = requests.post(f"{BASE_URL}/api/v2/lobby/tables",
                      json=body, headers=_hdr(tok), timeout=10)
    r.raise_for_status()
    return r.json()


def _join(tok: str, tid: str) -> requests.Response:
    return requests.post(f"{BASE_URL}/api/v2/lobby/tables/{tid}/join",
                         headers=_hdr(tok), timeout=10)


def _start(tok: str, tid: str) -> requests.Response:
    return requests.post(f"{BASE_URL}/api/v2/lobby/tables/{tid}/start",
                         headers=_hdr(tok), timeout=10)


async def _ws_connect(tid: str, tok: str):
    return await websockets.connect(
        f"{WS_BASE}/api/v2/ws/table/{tid}?token={tok}",
        additional_headers=[("User-Agent", "TARGET-Test/1.0")],
        open_timeout=10, ping_interval=None,
    )


async def _collect_until(ws, predicate, *, timeout: float = 8.0,
                         all_msgs: Optional[list] = None):
    end = asyncio.get_event_loop().time() + timeout
    while True:
        rem = end - asyncio.get_event_loop().time()
        if rem <= 0:
            return None
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=rem)
        except (asyncio.TimeoutError, Exception):
            return None
        try:
            msg = json.loads(raw)
        except Exception:
            continue
        if all_msgs is not None:
            all_msgs.append(msg)
        if predicate(msg):
            return msg


async def _drain_nonblocking(ws, all_msgs: list, *, for_seconds: float = 0.5):
    end = asyncio.get_event_loop().time() + for_seconds
    while asyncio.get_event_loop().time() < end:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=0.05)
        except (asyncio.TimeoutError, Exception):
            continue
        try:
            all_msgs.append(json.loads(raw))
        except Exception:
            pass


async def _send(ws, typ: str, sv: int, payload: Optional[dict] = None):
    await ws.send(json.dumps({"type": typ, "state_version": sv, "payload": payload or {}}))


def _last_state_version(msgs: list, user_id: Optional[str] = None) -> Optional[int]:
    for m in reversed(msgs):
        if m.get("type") == "STATE_UPDATE":
            return m["state_version"]
    return None


def _phases_seen(msgs: list) -> list:
    out = []
    for m in msgs:
        if m.get("type") == "STATE_UPDATE":
            ph = m.get("phase")
            if not out or out[-1] != ph:
                out.append(ph)
    return out


# =========================================================================
# F1 — Seat cap derivation
# =========================================================================
def test_f1_lobby_config_and_seat_derivation():
    r = requests.get(f"{BASE_URL}/api/v2/lobby/config", headers=HEADERS, timeout=10)
    assert r.status_code == 200
    cfg = r.json()
    assert cfg["allow_bots"] is True
    seats = cfg["table_seats_by_target"]
    # JSON keys are strings — locked targets 2026-05: 30/50/75/100
    assert str(seats.get("30", seats.get(30))) == "4"
    assert str(seats.get("50", seats.get(50))) == "4"
    assert str(seats.get("75", seats.get(75))) == "5"
    assert str(seats.get("100", seats.get(100))) == "5"
    # 250 was deprecated in the 2026-05 locked-rules migration.
    assert seats.get("250", seats.get(250)) is None

    _, tok = _auth(_mk_name("F1a"))
    t30 = _create_table(tok, target=30, max_players=10)  # client value must be ignored
    assert t30["max_players"] == 4, t30
    t100 = _create_table(tok, target=100, max_players=2)
    assert t100["max_players"] == 5, t100


# =========================================================================
# F2 — Two humans create/join/start; both receive BETTING_R1 STATE_UPDATE
# =========================================================================
@pytest.mark.asyncio
async def test_f2_two_humans_betting_r1():
    uid1, tok1 = _auth(_mk_name("F2a"))
    uid2, tok2 = _auth(_mk_name("F2b"))
    t = _create_table(tok1, target=30, bot_count=0)
    tid = t["table_id"]
    jr = _join(tok2, tid)
    assert jr.status_code == 200, jr.text
    sr = _start(tok1, tid)
    assert sr.status_code == 200, sr.text

    ws1 = await _ws_connect(tid, tok1)
    ws2 = await _ws_connect(tid, tok2)
    try:
        m1_all, m2_all = [], []
        m1 = await _collect_until(
            ws1,
            lambda m: m.get("type") == "STATE_UPDATE" and m.get("phase") == "BETTING_R1",
            timeout=6.0, all_msgs=m1_all)
        m2 = await _collect_until(
            ws2,
            lambda m: m.get("type") == "STATE_UPDATE" and m.get("phase") == "BETTING_R1",
            timeout=6.0, all_msgs=m2_all)
        assert m1 is not None, f"ws1 never saw BETTING_R1: {m1_all[-3:]}"
        assert m2 is not None, f"ws2 never saw BETTING_R1: {m2_all[-3:]}"
        assert len(m1["players"]) == 2 and len(m2["players"]) == 2
        uids = {p["user_id"] for p in m1["players"]}
        assert uid1 in uids and uid2 in uids
    finally:
        await ws1.close(); await ws2.close()


# =========================================================================
# F3/F4/F11 — Full canonical flow with bot; verify phase progression
# =========================================================================
@pytest.mark.asyncio
async def test_f3_f4_f11_canonical_flow_with_bot():
    """Verify the multi-round phase progression contract.

    Expected canonical progression with two non-disqualified players:
      BETTING_R1 → DEAL_INITIAL → DRAW_1 → BETTING_R2 → DRAW_2 →
      BETTING_R3 → SHOWDOWN/PAYOUT

    Per reducer rules (`_enter_betting_round` short-circuits when
    `len(in_hand) <= 1`), a JOKER draw legitimately disqualifies a
    player, which on a 4-seat (target=30) table with only 2 humans
    seated collapses `in_hand` to 1 and forces a SHOWDOWN ahead of
    the next betting round. The test must encode this contract —
    assertion is conditional on the final in_hand count seen in the
    SHOWDOWN/PAYOUT snapshot.

    Wording: there is no 2-seat table type per GAME_RULES_LOCKED.md
    §2; this scenario uses bot_count=1 to start a 4-seat table with
    just 2 seats filled (1 human + 1 bot — minimum legal start for
    the 4-seat tier).

    The 2026-05 v2 reproduction showed a ~6% rate of JOKER-driven
    skips at target=30 with bot_count=1 — entirely correct engine
    behaviour, not a flake. The previous version of this test
    asserted a fixed 5-phase order regardless of in_hand count.
    """
    uid, tok = _auth(_mk_name("F3"))
    t = _create_table(tok, target=30, bot_count=1)
    tid = t["table_id"]
    sr = _start(tok, tid); assert sr.status_code == 200, sr.text

    ws = await _ws_connect(tid, tok)
    msgs: list = []
    try:
        # Wait for BETTING_R1 with both seats
        m = await _collect_until(ws,
            lambda x: x.get("type") == "STATE_UPDATE" and x.get("phase") == "BETTING_R1"
                      and len(x.get("players", [])) >= 2,
            timeout=8.0, all_msgs=msgs)
        assert m is not None, f"no BETTING_R1 seen; last={msgs[-2:]}"

        # Find our seat & opponent seat
        def _find_my_seat(st):
            for p in st["players"]:
                if p["user_id"] == uid: return p["seat"]
            return None

        # Step through phases: send CHECK in R1, STAND in DRAW_1, CHECK in R2,
        # STAND in DRAW_2, CHECK in R3. After each, wait for our next turn.
        actions = [
            ("BETTING_R1", "CHECK"),
            ("DRAW_1", "STAND"),
            ("BETTING_R2", "CHECK"),
            ("DRAW_2", "STAND"),
            ("BETTING_R3", "CHECK"),
        ]

        for expected_phase, act in actions:
            # Wait until current_turn_seat == my seat in the expected phase,
            # or phase advanced past it (bot might finish some rounds alone).
            end = asyncio.get_event_loop().time() + 20.0
            acted = False
            while asyncio.get_event_loop().time() < end and not acted:
                # pull any pending messages briefly
                await _drain_nonblocking(ws, msgs, for_seconds=0.3)
                latest = next((x for x in reversed(msgs) if x.get("type") == "STATE_UPDATE"), None)
                if not latest: continue
                ph = latest.get("phase")
                if ph in ("PAYOUT", "HAND_COMPLETE"): break
                if ph == expected_phase:
                    my_seat = _find_my_seat(latest)
                    if latest.get("current_turn_seat") == my_seat:
                        sv = latest["state_version"]
                        try:
                            await _send(ws, act, sv)
                            acted = True
                        except Exception:
                            pass
                        # drain ack
                        await _drain_nonblocking(ws, msgs, for_seconds=0.5)
                        break
                elif ph and ph != expected_phase:
                    # phase moved past, stop trying for this action
                    # (note: engine may skip ahead if both stood)
                    break
            # continue to next expected phase
            await _drain_nonblocking(ws, msgs, for_seconds=0.5)

        # Allow remaining auto-progression
        await _collect_until(ws,
            lambda x: x.get("type") == "STATE_UPDATE" and x.get("phase") in ("PAYOUT", "HAND_COMPLETE"),
            timeout=20.0, all_msgs=msgs)

        phases = _phases_seen(msgs)
        print("PHASES_SEEN:", phases)
        # Mandatory invariants — these must hold regardless of which
        # JOKER-disqualification path the deal took:
        # (i) BETTING_R1 always entered (every hand opens with R1).
        # (ii) PAYOUT always reached (no hand strands).
        assert "BETTING_R1" in phases, f"missing BETTING_R1; saw {phases}"
        assert any(p in ("PAYOUT", "HAND_COMPLETE") for p in phases), \
            f"never reached PAYOUT/HAND_COMPLETE; saw {phases}"

        # Find the terminal STATE_UPDATE (PAYOUT / HAND_COMPLETE / SHOWDOWN
        # if the engine ended there). It carries the authoritative
        # `disqualified` / `folded` flags we use to derive the expected
        # phase contract.
        terminal = next(
            (m for m in reversed(msgs)
             if m.get("type") == "STATE_UPDATE"
             and m.get("phase") in ("PAYOUT", "HAND_COMPLETE")),
            None,
        )
        assert terminal is not None, "no terminal STATE_UPDATE captured"

        def _alive(p) -> bool:
            # Mirrors `Player.in_hand`: not folded / disqualified / sitting_out.
            return not (p.get("folded") or p.get("disqualified")
                        or p.get("sitting_out"))

        alive_at_end = [p for p in terminal["players"] if _alive(p)]
        # Phase-skip contract per reducer `_enter_betting_round`:
        #   len(in_hand) <= 1 at the end of any betting/draw round
        #   collapses the rest of the round structure into SHOWDOWN.
        # We can't reconstruct in_hand at every transition from the
        # public broadcast, but the terminal alive count is a tight
        # lower bound: if 2+ players are still alive at PAYOUT, the
        # full 5-phase canonical progression MUST have occurred.
        # Conversely, if only 1 (or 0) is alive, intermediate betting
        # rounds may be legitimately skipped.
        full_progression_required = len(alive_at_end) >= 2

        if full_progression_required:
            # F3 — full canonical phase progression for a non-degenerate hand.
            expected_order = [
                "BETTING_R1", "DRAW_1", "BETTING_R2", "DRAW_2",
                "BETTING_R3", "PAYOUT",
            ]
            filtered = [p for p in phases if p in expected_order]
            i = 0
            for ph in filtered:
                if ph == expected_order[i]:
                    i += 1
                    if i == len(expected_order):
                        break
            assert i == len(expected_order), (
                f"missing phases in canonical order; alive_at_end="
                f"{[p['user_id'] for p in alive_at_end]} saw {phases}"
            )
            # F4 — DRAW_1 reached & player could attempt HIT/STAND.
            assert "DRAW_1" in phases, f"missing DRAW_1; saw {phases}"
            # F11 — DRAW_2 must have occurred when both players survived.
            assert "DRAW_2" in phases, f"missing DRAW_2; saw {phases}"
            globals()["_F11_DRAW2_SEEN"] = True
        else:
            # Degenerate hand (JOKER disqualification or fold collapsed
            # the table to ≤1 alive). Validate only the invariants that
            # the reducer guarantees in this case:
            #   - BETTING_R1 + PAYOUT (already asserted above).
            #   - The disqualified/folded player carries the flag that
            #     justifies the skip; ensures the test is observing a
            #     legitimate degenerate path, not a bug elsewhere.
            dead_at_end = [p for p in terminal["players"] if not _alive(p)]
            assert dead_at_end, (
                f"phase-skip path taken but no disqualified/folded "
                f"player to justify it; players={terminal['players']}"
            )
            print(
                f"DEGENERATE_HAND: skip justified by "
                f"{[(p['seat'], 'DQ' if p.get('disqualified') else 'FOLD' if p.get('folded') else 'SIT_OUT') for p in dead_at_end]}"
            )
            # Soft-record DRAW_2 occurrence for F11 reporting (degenerate
            # path may legitimately not exercise it).
            globals()["_F11_DRAW2_SEEN"] = "DRAW_2" in phases

        # F11 audit trail (informational): all PHASE events ever seen.
        phase_events = []
        for m in msgs:
            if m.get("type") == "STATE_UPDATE":
                for ev in m.get("events") or []:
                    if ev.get("type") == "PHASE":
                        phase_events.append(ev.get("phase"))
        print("PHASE_EVENTS:", phase_events)
    finally:
        await ws.close()


# =========================================================================
# F6 — PLAY_TEN intent accepted by gateway whitelist
# =========================================================================
@pytest.mark.asyncio
async def test_f6_play_ten_intent_accepted():
    uid, tok = _auth(_mk_name("F6"))
    t = _create_table(tok, target=30, bot_count=1)
    tid = t["table_id"]
    _start(tok, tid)

    ws = await _ws_connect(tid, tok)
    msgs: list = []
    try:
        m = await _collect_until(
            ws,
            lambda x: x.get("type") == "STATE_UPDATE" and x.get("phase") in ("DRAW_1", "BETTING_R1"),
            timeout=8.0, all_msgs=msgs)
        assert m is not None
        sv = m["state_version"]
        # Send PLAY_TEN while current — regardless of turn, gateway must not
        # reject as UNKNOWN_TYPE. It may respond OUT_OF_SYNC / ACTION_ACK with
        # engine-level rejection (e.g. NOT_YOUR_TURN / NO_TRIGGER_CARD).
        await _send(ws, "PLAY_TEN", sv,
                    payload={"target_user_id": "u_bot_xxx", "attack_card_index": 0})
        # Collect response
        got_unknown = False
        got_accept_or_engine_reject = False
        end = asyncio.get_event_loop().time() + 4.0
        while asyncio.get_event_loop().time() < end:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
            except Exception:
                continue
            try: mm = json.loads(raw)
            except Exception: continue
            msgs.append(mm)
            if mm.get("type") == "ERROR" and mm.get("code") == "UNKNOWN_TYPE":
                got_unknown = True; break
            if mm.get("type") in ("ACTION_ACK", "OUT_OF_SYNC"):
                got_accept_or_engine_reject = True; break
        assert not got_unknown, "PLAY_TEN was rejected at gateway as UNKNOWN_TYPE"
        assert got_accept_or_engine_reject, "No ACK / OUT_OF_SYNC for PLAY_TEN"
    finally:
        await ws.close()


# =========================================================================
# F9 — Card privacy: P1 must never receive PRIVATE_STATE for P2
# =========================================================================
@pytest.mark.asyncio
async def test_f9_card_privacy():
    uid1, tok1 = _auth(_mk_name("F9a"))
    uid2, tok2 = _auth(_mk_name("F9b"))
    t = _create_table(tok1, target=30, bot_count=0)
    tid = t["table_id"]
    _join(tok2, tid)
    _start(tok1, tid)

    ws1 = await _ws_connect(tid, tok1)
    ws2 = await _ws_connect(tid, tok2)
    m1_all, m2_all = [], []
    try:
        await _drain_nonblocking(ws1, m1_all, for_seconds=4.0)
        await _drain_nonblocking(ws2, m2_all, for_seconds=4.0)
        # Public STATE_UPDATE must never include 'cards'
        for m in m1_all + m2_all:
            if m.get("type") == "STATE_UPDATE":
                for p in m.get("players", []):
                    assert "cards" not in p, f"LEAK: public STATE_UPDATE has cards! {p}"
                    assert "card_count" in p
        # PRIVATE_STATE received only for your own user_id
        for m in m1_all:
            if m.get("type") == "PRIVATE_STATE":
                assert m.get("user_id") == uid1, f"LEAK: ws1 got PRIVATE_STATE for {m.get('user_id')}"
        for m in m2_all:
            if m.get("type") == "PRIVATE_STATE":
                assert m.get("user_id") == uid2, f"LEAK: ws2 got PRIVATE_STATE for {m.get('user_id')}"
        # Assert we did actually receive at least one PRIVATE_STATE each
        got1 = any(m.get("type") == "PRIVATE_STATE" for m in m1_all)
        got2 = any(m.get("type") == "PRIVATE_STATE" for m in m2_all)
        assert got1 and got2, f"no PRIVATE_STATE received: p1={got1} p2={got2}"
    finally:
        await ws1.close(); await ws2.close()


# =========================================================================
# F10 — target=100 table: 5 seats; 6th join → TABLE_FULL
# =========================================================================
def test_f10_target100_five_seats_and_full():
    creator_id, creator_tok = _auth(_mk_name("F10"))
    t = _create_table(creator_tok, target=100, bot_count=0)
    assert t["max_players"] == 5
    tid = t["table_id"]
    # Creator auto-joined → 1 seat. Need to add 4 more to hit 5/5.
    for i in range(4):
        _, tk = _auth(_mk_name(f"F10j{i}"))
        r = _join(tk, tid)
        assert r.status_code == 200, f"join {i} failed: {r.text}"
    # 6th must be rejected
    _, tk6 = _auth(_mk_name("F10x"))
    r6 = _join(tk6, tid)
    assert r6.status_code == 400, f"expected 400, got {r6.status_code}: {r6.text}"
    body = r6.json()
    code = (body.get("detail") or {}).get("code") if isinstance(body.get("detail"), dict) else body.get("detail")
    assert code == "TABLE_FULL", f"expected TABLE_FULL, got {body}"


# =========================================================================
# F7 — Disconnect/reconnect grace presence events
# =========================================================================
@pytest.mark.asyncio
async def test_f7_disconnect_reconnect_presence():
    uid1, tok1 = _auth(_mk_name("F7a"))
    uid2, tok2 = _auth(_mk_name("F7b"))
    t = _create_table(tok1, target=30, bot_count=0)
    tid = t["table_id"]
    _join(tok2, tid)
    _start(tok1, tid)

    ws1 = await _ws_connect(tid, tok1)
    ws2 = await _ws_connect(tid, tok2)
    m2_all = []
    try:
        # drain initial burst
        await _drain_nonblocking(ws2, m2_all, for_seconds=2.0)
        # abrupt close of ws1
        await ws1.close()
        # wait for PRESENCE event with connected=false for uid1
        got_off = await _collect_until(
            ws2,
            lambda x: x.get("type") == "STATE_UPDATE" and any(
                ev.get("type") == "PRESENCE" and ev.get("user_id") == uid1 and ev.get("connected") is False
                for ev in (x.get("events") or [])),
            timeout=8.0, all_msgs=m2_all)
        assert got_off is not None, "no PRESENCE offline event received"
        # reconnect
        ws1b = await _ws_connect(tid, tok1)
        try:
            got_on = await _collect_until(
                ws2,
                lambda x: x.get("type") == "STATE_UPDATE" and any(
                    ev.get("type") == "PRESENCE" and ev.get("user_id") == uid1 and ev.get("connected") is True
                    for ev in (x.get("events") or [])),
                timeout=8.0, all_msgs=m2_all)
            assert got_on is not None, "no PRESENCE online event received"
        finally:
            await ws1b.close()
    finally:
        try: await ws2.close()
        except Exception: pass


# =========================================================================
# F5 — BET/CALL in R1, then FOLD in R2 short-circuits to PAYOUT
# F8 — PAYOUT contains winners + payout integers
# =========================================================================
@pytest.mark.asyncio
async def test_f5_f8_bet_call_fold_and_payout():
    uid1, tok1 = _auth(_mk_name("F5a"))
    uid2, tok2 = _auth(_mk_name("F5b"))
    t = _create_table(tok1, target=30, bot_count=0)
    tid = t["table_id"]
    _join(tok2, tid)
    _start(tok1, tid)
    ws1 = await _ws_connect(tid, tok1)
    ws2 = await _ws_connect(tid, tok2)
    msgs1: list = []; msgs2: list = []

    async def drain_both(seconds=0.4):
        await _drain_nonblocking(ws1, msgs1, for_seconds=seconds)
        await _drain_nonblocking(ws2, msgs2, for_seconds=seconds)

    def latest(msgs):
        return next((m for m in reversed(msgs) if m.get("type") == "STATE_UPDATE"), None)

    def my_seat(state, uid):
        for p in state["players"]:
            if p["user_id"] == uid: return p["seat"]
        return None

    async def act_when_my_turn(ws, own_msgs, uid, phase_target, action, payload=None, timeout=15.0):
        end = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < end:
            await drain_both(0.3)
            st = latest(own_msgs)
            if not st: continue
            ph = st.get("phase")
            if ph in ("PAYOUT", "HAND_COMPLETE"): return "PAYOUT_REACHED"
            if ph == phase_target and st.get("current_turn_seat") == my_seat(st, uid):
                sv = st["state_version"]
                await _send(ws, action, sv, payload=payload)
                await drain_both(0.5)
                return "ACTED"
            if ph and ph != phase_target:
                # phase advanced; still OK — the action for this phase might
                # have been performed by opponent flow already. Continue.
                pass
        return "TIMEOUT"

    try:
        # Wait for BETTING_R1
        m = await _collect_until(ws1,
            lambda x: x.get("type") == "STATE_UPDATE" and x.get("phase") == "BETTING_R1"
                      and len(x.get("players", [])) >= 2,
            timeout=8.0, all_msgs=msgs1)
        assert m is not None
        await drain_both(0.5)

        # BETTING_R1: whoever is on turn first bets; the other calls.
        # We loop through both players and let each act in turn.
        async def step_betting_round(phase):
            for _ in range(4):
                await drain_both(0.3)
                st1 = latest(msgs1); st2 = latest(msgs2)
                if not (st1 and st2): continue
                if st1.get("phase") != phase: return
                # p1's turn?
                if st1.get("current_turn_seat") == my_seat(st1, uid1):
                    if st1.get("current_call_owed", 0) > 0:
                        await _send(ws1, "CALL", st1["state_version"])
                    else:
                        await _send(ws1, "BET", st1["state_version"], {"amount": 100})
                    await drain_both(0.5)
                elif st2.get("current_turn_seat") == my_seat(st2, uid2):
                    if st2.get("current_call_owed", 0) > 0:
                        await _send(ws2, "CALL", st2["state_version"])
                    else:
                        await _send(ws2, "BET", st2["state_version"], {"amount": 100})
                    await drain_both(0.5)

        await step_betting_round("BETTING_R1")
        # Verify pot grew
        st = latest(msgs1)
        assert st and st["pot"] >= 200, f"pot did not grow: {st and st.get('pot')}"

        # DRAW_1: both STAND through
        for _ in range(8):
            await drain_both(0.3)
            st1 = latest(msgs1); st2 = latest(msgs2)
            if not (st1 and st2): break
            if st1.get("phase") != "DRAW_1": break
            if st1.get("current_turn_seat") == my_seat(st1, uid1):
                await _send(ws1, "STAND", st1["state_version"])
            elif st2.get("current_turn_seat") == my_seat(st2, uid2):
                await _send(ws2, "STAND", st2["state_version"])
            await drain_both(0.3)

        # BETTING_R2: P1 bets, P2 folds → PAYOUT
        await drain_both(0.5)
        for _ in range(6):
            await drain_both(0.3)
            st1 = latest(msgs1); st2 = latest(msgs2)
            if not (st1 and st2): break
            ph = st1.get("phase")
            if ph in ("PAYOUT", "HAND_COMPLETE"): break
            if ph != "BETTING_R2":
                continue
            if st1.get("current_turn_seat") == my_seat(st1, uid1):
                if st1.get("current_call_owed", 0) > 0:
                    await _send(ws1, "CALL", st1["state_version"])
                else:
                    await _send(ws1, "BET", st1["state_version"], {"amount": 50})
            elif st2.get("current_turn_seat") == my_seat(st2, uid2):
                # p2 folds
                await _send(ws2, "FOLD", st2["state_version"])
            await drain_both(0.4)

        # Wait for PAYOUT
        await _collect_until(ws1,
            lambda x: x.get("type") == "STATE_UPDATE" and x.get("phase") in ("PAYOUT", "HAND_COMPLETE"),
            timeout=10.0, all_msgs=msgs1)
        payout_msg = next((m for m in reversed(msgs1)
                           if m.get("type") == "STATE_UPDATE" and m.get("phase") in ("PAYOUT", "HAND_COMPLETE")), None)
        assert payout_msg is not None, "never reached PAYOUT"
        # F8 — winners + per-player payout
        winners = payout_msg.get("winners") or []
        assert isinstance(winners, list)
        for p in payout_msg["players"]:
            assert "payout" in p and isinstance(p["payout"], int), f"no payout int on {p}"
        # F5 — P1 wins (P2 folded)
        assert uid1 in winners, f"P1 should win, winners={winners}"
    finally:
        await ws1.close(); await ws2.close()
