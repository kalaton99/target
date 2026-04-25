"""Pure reducer: (state, action) -> (new_state, events).

Actions a client can send:
  ANTE_PAID  (server-driven on phase transition; clients don't send)
  HIT        (draw a card)
  STAND      (lock in score; end your draw turn)
  FOLD       (only in BETTING)
  CHECK      (only in BETTING when no bet to call)
  CALL       (only in BETTING when facing a bet)
  RAISE {amount}  (only in BETTING)

Server-only:
  AUTO_STAND_TIMEOUT  (DRAW phase 15s)
  AUTO_FOLD_SITOUT    (BETTING phase, sitting_out + facing bet)
  AUTO_CHECK_SITOUT   (BETTING phase, sitting_out + no bet)
  PHASE_TRANSITION
  DEAL
  SHOWDOWN
  PAYOUT
"""
import time
from copy import deepcopy
from typing import Any, Dict, List, Tuple

from .types import GameState, PlayerState
from .scoring import score_hand
from .deck import shuffle, build_fresh_deck, compute_shuffle_seed
from core.constants import (
    TURN_TIMEOUT_MS,
    TURN_TIMEOUT_REASON,
    SERVER_ONLY_ACTIONS,
    COMMISSION_PAID_BPS,
    COMMISSION_FREE_BPS,
    LOTTERY_BPS,
    TARGET_SCORE,
)


def now_ms() -> int:
    return int(time.time() * 1000)


class ReducerError(Exception):
    pass


def _next_active_seat_for_draw(state: GameState, from_seat: int) -> int | None:
    """Find next seat that still needs to draw (not stood/busted/dq/folded/sitting)."""
    n = len(state.players)
    for k in range(1, n + 1):
        idx = (from_seat + k) % n
        p = state.players[idx]
        if not (p.busted or p.disqualified or p.folded or p.stood or p.sitting_out):
            return idx
    return None


def _next_active_seat_for_betting(state: GameState, from_seat: int) -> int | None:
    n = len(state.players)
    for k in range(1, n + 1):
        idx = (from_seat + k) % n
        p = state.players[idx]
        if not (p.folded or p.disqualified):
            # Even busted players still must act (call/fold) until showdown? In our MVP
            # busted/dq are out of betting too.
            if p.busted:
                continue
            return idx
    return None


def _set_turn(state: GameState, seat: int | None) -> None:
    state.current_turn_seat = seat
    if seat is None:
        state.turn_started_at_ms = None
        state.turn_deadline_ms = None
    else:
        t = now_ms()
        state.turn_started_at_ms = t
        state.turn_deadline_ms = t + TURN_TIMEOUT_MS


def _enter_draw(state: GameState, events: List[Dict[str, Any]]) -> None:
    state.phase = "DRAW"
    # Find first non-busted/dq seat
    for i, p in enumerate(state.players):
        if not (p.busted or p.disqualified or p.folded or p.stood or p.sitting_out):
            _set_turn(state, i)
            events.append({"type": "PHASE", "phase": "DRAW", "active_seat": i})
            return
    _enter_betting(state, events)


def _enter_betting(state: GameState, events: List[Dict[str, Any]]) -> None:
    state.phase = "BETTING"
    state.current_bet = 0
    state.min_raise = state.stake
    for p in state.players:
        p.current_bet = 0
    # Find first non-folded/busted/dq seat to start betting
    for i, p in enumerate(state.players):
        if not (p.folded or p.busted or p.disqualified):
            _set_turn(state, i)
            events.append({"type": "PHASE", "phase": "BETTING", "active_seat": i})
            return
    _enter_showdown(state, events)


def _enter_showdown(state: GameState, events: List[Dict[str, Any]]) -> None:
    state.phase = "SHOWDOWN"
    state.current_turn_seat = None
    state.turn_started_at_ms = None
    state.turn_deadline_ms = None

    # Eligible: not folded, not busted, not dq
    eligible = [
        p for p in state.players
        if not (p.folded or p.busted or p.disqualified)
    ]

    winners: List[PlayerState] = []
    if eligible:
        best = max(p.score for p in eligible)
        winners = [p for p in eligible if p.score == best]

    if winners:
        # Commission
        bps = COMMISSION_PAID_BPS if state.table_type == "PAID" else COMMISSION_FREE_BPS
        commission = (state.pot * bps) // 10000
        lottery = (commission * LOTTERY_BPS) // 10000
        # commission already includes lottery share for accounting
        net_pot = state.pot - commission

        # Split equally; remainder to first winner clockwise
        share = net_pot // len(winners)
        remainder = net_pot - share * len(winners)
        for i, w in enumerate(winners):
            w.payout = share + (remainder if i == 0 else 0)
        state.winners = [w.user_id for w in winners]
        events.append({
            "type": "SHOWDOWN",
            "winners": [{"user_id": w.user_id, "seat": w.seat_index, "score": w.score, "payout": w.payout} for w in winners],
            "commission": commission,
            "lottery_contribution": lottery,
        })
    else:
        # Everyone busted/folded -> pot voided (returned via abort path elsewhere)
        events.append({"type": "SHOWDOWN", "winners": [], "commission": 0, "lottery_contribution": 0})

    state.phase = "PAYOUT"
    events.append({"type": "PHASE", "phase": "PAYOUT"})


def _seat_by_user(state: GameState, user_id: str) -> int | None:
    for i, p in enumerate(state.players):
        if p.user_id == user_id:
            return i
    return None


def reduce(state: GameState, action: Dict[str, Any]) -> Tuple[GameState, List[Dict[str, Any]]]:
    """Return (new_state, events). Pure: never mutate input."""
    state = deepcopy(state)
    events: List[Dict[str, Any]] = []
    a_type = action["type"]
    user_id = action.get("user_id")
    source = action.get("source", "CLIENT")

    # --- Server-only actions guard ---
    if a_type in SERVER_ONLY_ACTIONS and source != "SERVER":
        raise ReducerError(f"SERVER_ONLY_ACTION: {a_type}")

    # --- START_HAND (server) ---
    if a_type == "START_HAND":
        nonce = action["nonce"]
        server_seed_plain = action["server_seed"]
        client_seeds = action.get("client_seeds", "")
        seed = compute_shuffle_seed(server_seed_plain, client_seeds, nonce)
        state.deck = [c.to_dict() for c in shuffle(build_fresh_deck(include_jokers=True), seed)]
        state.hand_id = action["hand_id"]
        state.hand_number += 1
        state.rng_nonce = nonce
        state.rng_commit_hash = action["server_seed_hash"]
        state.pot = 0
        state.winners = []
        state.last_action_summary = None
        # Reset per-player hand fields
        for p in state.players:
            p.current_bet = 0
            p.total_contributed = 0
            p.cards = []
            p.score = 0
            p.soft = False
            p.busted = False
            p.disqualified = False
            p.folded = False
            p.stood = False
            p.payout = 0
        state.phase = "ANTE"
        # Auto-collect ante from each player (assumed pre-validated)
        for p in state.players:
            if not p.sitting_out:
                p.total_contributed += state.stake
                state.pot += state.stake
        events.append({"type": "ANTES_COLLECTED", "amount_per_player": state.stake, "pot": state.pot})
        # Move to DEAL
        state.phase = "DEAL"
        # Deal 2 cards to each non-sitting-out player
        for p in state.players:
            if not p.sitting_out:
                p.cards.append(state.deck.pop(0))
                p.cards.append(state.deck.pop(0))
                s = score_hand(p.cards)
                p.score = s["total"]
                p.soft = s["soft"]
                p.busted = s["busted"]
                p.disqualified = s["disqualified"]
        events.append({"type": "DEAL_COMPLETE"})
        _enter_draw(state, events)
        state.version += 1
        return state, events

    # --- HIT (client / DRAW phase) ---
    if a_type == "HIT":
        if state.phase != "DRAW":
            raise ReducerError("WRONG_PHASE")
        seat = _seat_by_user(state, user_id)
        if seat is None or seat != state.current_turn_seat:
            raise ReducerError("NOT_YOUR_TURN")
        p = state.players[seat]
        if not state.deck:
            raise ReducerError("DECK_EMPTY")
        card = state.deck.pop(0)
        p.cards.append(card)
        s = score_hand(p.cards)
        p.score = s["total"]
        p.soft = s["soft"]
        p.busted = s["busted"]
        p.disqualified = s["disqualified"]
        events.append({
            "type": "CARD_DRAWN",
            "seat": seat,
            "user_id": p.user_id,
            "card": card,
            "score": p.score,
            "busted": p.busted,
            "disqualified": p.disqualified,
        })
        # If busted/dq, auto-advance turn. Otherwise player still has option to hit/stand.
        if p.busted or p.disqualified:
            p.stood = True
            nxt = _next_active_seat_for_draw(state, seat)
            if nxt is None:
                _enter_betting(state, events)
            else:
                _set_turn(state, nxt)
        else:
            # Refresh turn deadline (player still acting)
            _set_turn(state, seat)
        state.last_action_summary = {"action": "HIT", "seat": seat}
        state.version += 1
        return state, events

    # --- STAND (client) or AUTO_STAND_TIMEOUT (server) ---
    if a_type in ("STAND", "AUTO_STAND_TIMEOUT"):
        if state.phase != "DRAW":
            raise ReducerError("WRONG_PHASE")
        seat = action.get("seat_index")
        if seat is None:
            seat = _seat_by_user(state, user_id)
        if seat is None or seat != state.current_turn_seat:
            raise ReducerError("NOT_YOUR_TURN")
        p = state.players[seat]
        p.stood = True
        reason = action.get("payload", {}).get("reason") or ("CLIENT_STAND" if a_type == "STAND" else TURN_TIMEOUT_REASON)
        events.append({
            "type": "STAND",
            "seat": seat,
            "user_id": p.user_id,
            "score": p.score,
            "auto": a_type == "AUTO_STAND_TIMEOUT",
            "reason": reason,
        })
        nxt = _next_active_seat_for_draw(state, seat)
        if nxt is None:
            _enter_betting(state, events)
        else:
            _set_turn(state, nxt)
        state.last_action_summary = {
            "action": "AUTO_STAND" if a_type == "AUTO_STAND_TIMEOUT" else "STAND",
            "seat": seat,
        }
        state.version += 1
        return state, events

    # --- BETTING actions ---
    if a_type in ("CHECK", "CALL", "RAISE", "FOLD", "AUTO_FOLD_SITOUT", "AUTO_CHECK_SITOUT"):
        if state.phase != "BETTING":
            raise ReducerError("WRONG_PHASE")
        seat = action.get("seat_index")
        if seat is None:
            seat = _seat_by_user(state, user_id)
        if seat is None or seat != state.current_turn_seat:
            raise ReducerError("NOT_YOUR_TURN")
        p = state.players[seat]
        amount = int(action.get("payload", {}).get("amount", 0))

        if a_type == "FOLD":
            p.folded = True
            events.append({"type": "FOLD", "seat": seat, "user_id": p.user_id})
        elif a_type == "AUTO_FOLD_SITOUT":
            if not p.sitting_out:
                raise ReducerError("AUTO_FOLD_SITOUT requires sitting_out=True")
            facing_unmet = state.current_bet > p.current_bet
            if not facing_unmet:
                raise ReducerError("AUTO_FOLD_SITOUT requires facing an unmet bet")
            p.folded = True
            events.append({"type": "FOLD", "seat": seat, "user_id": p.user_id, "auto": True, "reason": "SITTING_OUT_FACING_BET"})
        elif a_type == "AUTO_CHECK_SITOUT":
            if not p.sitting_out:
                raise ReducerError("AUTO_CHECK_SITOUT requires sitting_out=True")
            facing_unmet = state.current_bet > p.current_bet
            if facing_unmet:
                raise ReducerError("AUTO_CHECK_SITOUT requires no unmet bet")
            events.append({"type": "CHECK", "seat": seat, "user_id": p.user_id, "auto": True})
        elif a_type == "CHECK":
            if state.current_bet > p.current_bet:
                raise ReducerError("CANNOT_CHECK_FACING_BET")
            events.append({"type": "CHECK", "seat": seat, "user_id": p.user_id})
        elif a_type == "CALL":
            owed = state.current_bet - p.current_bet
            if owed <= 0:
                raise ReducerError("NOTHING_TO_CALL")
            # Wallet debit happens out-of-band; reducer assumes pre-validated.
            p.current_bet += owed
            p.total_contributed += owed
            state.pot += owed
            events.append({"type": "CALL", "seat": seat, "user_id": p.user_id, "amount": owed, "pot": state.pot})
        elif a_type == "RAISE":
            if amount <= 0:
                raise ReducerError("INVALID_RAISE")
            new_bet = p.current_bet + amount
            if new_bet < state.current_bet + state.min_raise:
                raise ReducerError("RAISE_TOO_SMALL")
            p.current_bet = new_bet
            p.total_contributed += amount
            state.pot += amount
            state.current_bet = new_bet
            state.min_raise = max(state.min_raise, amount)
            events.append({"type": "RAISE", "seat": seat, "user_id": p.user_id, "amount": amount, "pot": state.pot, "new_current_bet": state.current_bet})

        # Determine if betting round complete
        active = [pp for pp in state.players if not (pp.folded or pp.busted or pp.disqualified)]
        if len(active) <= 1:
            # Only one left -> they win immediately
            _enter_showdown(state, events)
        else:
            all_matched = all(pp.current_bet == state.current_bet for pp in active)
            # Find next seat
            nxt = _next_active_seat_for_betting(state, seat)
            if all_matched and (a_type in ("CHECK", "CALL", "FOLD", "AUTO_FOLD_SITOUT", "AUTO_CHECK_SITOUT")):
                # Round complete -> showdown
                _enter_showdown(state, events)
            else:
                if nxt is None:
                    _enter_showdown(state, events)
                else:
                    _set_turn(state, nxt)
        state.last_action_summary = {"action": a_type, "seat": seat}
        state.version += 1
        return state, events

    raise ReducerError(f"UNKNOWN_ACTION: {a_type}")
