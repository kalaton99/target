"""2026-05 stabilization: betting-phase turn-timeout guard.

Proves the deadlock guard:
  - if a player stalls during BETTING_R1 / R2 / R3, the engine
    auto-fires after 15s (test uses a tiny override) and submits:
      - CHECK when no call is owed, or
      - FOLD when a call IS owed.
  - This is done via the turn-engine's timer + reducer path; no new
    action type. State advances without the stalled player ever acting.

  - DRAW timer still fires AUTO_STAND_TIMEOUT (unchanged; must NEVER fold).
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game_engine.turn_engine import TurnEngine  # noqa: E402
from game_engine.types import GameState, PlayerState  # noqa: E402


def _make_state(n=3):
    s = GameState(table_id="t1", target_score=30, stake=100)
    s.players = [
        PlayerState(seat_index=i, user_id=f"u{i}", username=f"P{i}",
                    balance_at_start=10000)
        for i in range(n)
    ]
    return s


async def _start_hand(engine):
    await engine.submit({
        "type": "START_HAND", "source": "SERVER",
        "hand_id": "h1", "nonce": 0,
        "server_seed": "0" * 64, "server_seed_hash": "h" * 64,
        "client_seeds": "",
    })
    await engine.drain(timeout=1.0)


@pytest.mark.asyncio
async def test_betting_r1_check_auto_fires_on_stall():
    """All seats stall in BETTING_R1 → timer fires CHECK for each in turn
    until the round ends and the engine advances to DEAL_INITIAL + DRAW_1.
    """
    state = _make_state(n=3)
    engine = TurnEngine(state, turn_timeout_ms=60, grace_ms=10)
    await engine.start()
    try:
        await _start_hand(engine)
        assert engine.state.phase == "BETTING_R1"
        assert engine.state.current_turn_seat == 0

        # Wait for all three seats to be auto-CHECKed.
        # 3 seats × (60ms+10ms+scheduling slop) ≲ 500ms.
        for _ in range(40):  # up to ~4s of polling
            if engine.state.phase != "BETTING_R1":
                break
            await asyncio.sleep(0.1)

        # Must have progressed past BETTING_R1 (and past DEAL_INITIAL which
        # is synchronous). We expect DRAW_1 since no one folded.
        assert engine.state.phase == "DRAW_1", (
            f"betting auto-CHECK did not advance to DRAW_1; "
            f"phase={engine.state.phase} version={engine.state.version}"
        )
        assert engine.timeout_fires >= 3, (
            f"expected ≥3 timer fires across 3 CHECKs; got {engine.timeout_fires}"
        )
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_betting_r1_call_owed_auto_folds_on_stall():
    """Seat 0 BETs (real intent), Seat 1 stalls → auto-FOLD. Seat 2 then
    calls to close the round (or also auto-folds). Either way, the round
    progresses; no deadlock.
    """
    state = _make_state(n=3)
    engine = TurnEngine(state, turn_timeout_ms=60, grace_ms=10)
    await engine.start()
    try:
        await _start_hand(engine)
        # Seat 0 bets immediately.
        sv = engine.state.version
        await engine.submit({
            "type": "BET", "source": "CLIENT",
            "user_id": "u0", "seat_index": 0,
            "state_version": sv,
            "payload": {"amount": 100},
        })
        await engine.drain(timeout=1.0)
        # Now seat 1 is on turn, call owed > 0, seat 1 stalls.
        # Let the timer fire for seat 1 and seat 2.
        for _ in range(40):
            if engine.state.phase != "BETTING_R1":
                break
            await asyncio.sleep(0.1)

        # Round should have ended (either DRAW_1 if ≥2 stayed, or
        # SHOWDOWN/PAYOUT if everyone auto-folded).
        assert engine.state.phase in ("DRAW_1", "SHOWDOWN", "PAYOUT"), (
            f"betting stall didn't advance; phase={engine.state.phase}"
        )
        # Seat 1 must have folded (auto).
        assert engine.state.players[1].folded, (
            f"seat 1 should have auto-folded on stall; folded="
            f"{[p.folded for p in engine.state.players]}"
        )
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_draw_1_still_auto_stands_never_folds():
    """Regression: DRAW timer must still fire AUTO_STAND_TIMEOUT, not FOLD."""
    state = _make_state(n=2)
    engine = TurnEngine(state, turn_timeout_ms=60, grace_ms=10)
    await engine.start()
    try:
        await _start_hand(engine)
        # Drive through BETTING_R1 quickly with real CHECKs.
        for seat_user in ("u0", "u1"):
            sv = engine.state.version
            await engine.submit({
                "type": "CHECK", "source": "CLIENT",
                "user_id": seat_user,
                "state_version": sv,
                "payload": {},
            })
            await engine.drain(timeout=1.0)

        assert engine.state.phase == "DRAW_1"
        # Let DRAW_1 auto-stand both seats.
        for _ in range(40):
            if engine.state.phase not in ("DRAW_1",):
                break
            await asyncio.sleep(0.1)

        # Must NOT have produced any FOLD event via auto-stand.
        for p in engine.state.players:
            assert not p.folded, "DRAW auto-timeout must never fold"
        assert engine.state.phase in ("BETTING_R2", "DRAW_2",
                                      "BETTING_R3", "PAYOUT"), (
            f"DRAW_1 stall didn't advance; phase={engine.state.phase}"
        )
    finally:
        await engine.stop()
