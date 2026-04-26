"""Pure reducer: (state, action) -> (new_state, events).

TARGET v2 (2026-02 rewrite). Aligned to the canonical TARGET rules:

  Phase order:
    WAITING -> ANTE -> BETTING_R1 -> DEAL_INITIAL -> DRAW -> SHOWDOWN -> PAYOUT -> ENDED

  Target: dynamic 30 / 50 / 100 / 250 (per table config; no fixed "21").

  Initial deal: ONE card per player (private) — NOT two.

  Betting (Phase 1, single round):
    BET / RAISE / CALL / CHECK / FOLD
    51% rule: when a player raises by X, every other staying player must
    contribute >= ceil(0.51 * X) to call. Players who can't / won't pay
    are folded out.
    Max raise capped so all active opponents can pay 51%.

  DRAW:
    HIT / STAND / PLAY_TWO / PLAY_TEN
    Auto-bust-save on Hearts-2 / Clubs-2 (transfer highest non-2 to opponent
    if it makes the score <= target; consumes the 2).
    Manual transfer with PLAY_TWO. Forced attack with PLAY_TEN.
    AUTO_STAND_TIMEOUT (server) on 15s timer.

  Showdown trigger:
    - stands_count >= STAND_THRESHOLD[draw_active_count]  OR
    - every in-hand player is stood / busted / DQ'd / folded  OR
    - only one in-hand player remains (others folded)

  Server-only actions: START_HAND, AUTO_STAND_TIMEOUT, AUTO_FOLD_INSUFFICIENT,
                       DEAL_INITIAL, SHOWDOWN, PAYOUT.
"""
from __future__ import annotations

import time
from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple

from core.constants import (
    ATTACK_RANK,
    ATTACK_SUITS,
    CALL_PERCENT_DEN,
    CALL_PERCENT_NUM,
    COMMISSION_FREE_BPS,
    COMMISSION_PAID_BPS,
    DEFENSE_RANK,
    DEFENSE_SUITS,
    LOTTERY_BPS,
    SERVER_ONLY_ACTIONS,
    STAND_THRESHOLD,
    TURN_TIMEOUT_MS,
    TURN_TIMEOUT_REASON,
    VALID_TARGET_SCORES,
)
from .deck import build_fresh_deck, compute_shuffle_seed, shuffle
from .scoring import score_hand
from .types import GameState, PlayerState


def now_ms() -> int:
    return int(time.time() * 1000)


class ReducerError(Exception):
    pass


# ============================================================
# Helpers
# ============================================================

def _is_defense_card(card: Dict[str, Any]) -> bool:
    return card.get("rank") == DEFENSE_RANK and card.get("suit") in DEFENSE_SUITS


def _is_attack_card(card: Dict[str, Any]) -> bool:
    return card.get("rank") == ATTACK_RANK and card.get("suit") in ATTACK_SUITS


def _seat_by_user(state: GameState, user_id: Optional[str]) -> Optional[int]:
    if user_id is None:
        return None
    for i, p in enumerate(state.players):
        if p.user_id == user_id:
            return i
    return None


def _ceil_div(num: int, den: int) -> int:
    return -(-num // den)


def _required_call(last_raise: int) -> int:
    """ceil(0.51 * last_raise) — integer math only."""
    return _ceil_div(last_raise * CALL_PERCENT_NUM, CALL_PERCENT_DEN)


def _set_turn(state: GameState, seat: Optional[int]) -> None:
    state.current_turn_seat = seat
    if seat is None:
        state.turn_started_at_ms = None
        state.turn_deadline_ms = None
    else:
        t = now_ms()
        state.turn_started_at_ms = t
        state.turn_deadline_ms = t + TURN_TIMEOUT_MS


def _next_in_hand(state: GameState, from_seat: int) -> Optional[int]:
    """Next seat that is still in_hand (not folded/dq/sitting_out)."""
    n = len(state.players)
    for k in range(1, n + 1):
        idx = (from_seat + k) % n
        if state.players[idx].in_hand:
            return idx
    return None


def _next_drawer(state: GameState, from_seat: int) -> Optional[int]:
    """Next seat that can still take a DRAW-phase action."""
    n = len(state.players)
    for k in range(1, n + 1):
        idx = (from_seat + k) % n
        if state.players[idx].can_draw:
            return idx
    return None


def _in_hand_seats(state: GameState) -> List[int]:
    return [i for i, p in enumerate(state.players) if p.in_hand]


def _max_raise_cap(state: GameState, raiser_seat: int) -> int:
    """Largest legal raise such that every OTHER in-hand player can still
    pay the ceil(0.51 * X) call out of their available balance.

    Returns 0 if no opponent can pay the smallest possible raise (1).
    """
    others = [
        p.available_balance()
        for i, p in enumerate(state.players)
        if p.in_hand and i != raiser_seat
    ]
    if not others:
        return 0
    min_other = min(others)
    if min_other <= 0:
        return 0
    # ceil(num * X / den) <= min_other
    #   -> num * X <= min_other * den   (since ceil(a/b) <= c <=> a <= b*c when b>0)
    return (min_other * CALL_PERCENT_DEN) // CALL_PERCENT_NUM


def _check_target_score(target: int) -> None:
    if target not in VALID_TARGET_SCORES:
        raise ReducerError(f"INVALID_TARGET_SCORE: {target}")


def _rescore(p: PlayerState, target: int) -> None:
    s = score_hand(p.cards, target)
    p.score = s["total"]
    p.soft = s["soft"]
    p.busted = s["busted"]
    p.disqualified = s["disqualified"]


# ============================================================
# Phase transitions (internal)
# ============================================================

def _end_betting_to_deal(state: GameState, events: List[Dict[str, Any]]) -> None:
    """BETTING_R1 → DEAL_INITIAL → DRAW.

    DEAL_INITIAL deals exactly one card per still-in-hand player.
    Then we transition straight to DRAW (DEAL_INITIAL is a transient phase).
    """
    in_hand = [i for i in _in_hand_seats(state)]
    if len(in_hand) <= 1:
        # Trivial case: everyone except one folded → that one wins
        _enter_showdown(state, events)
        return

    state.phase = "DEAL_INITIAL"
    events.append({"type": "PHASE", "phase": "DEAL_INITIAL"})

    for i in in_hand:
        if not state.deck:
            raise ReducerError("DECK_EXHAUSTED_AT_DEAL")
        p = state.players[i]
        p.cards.append(state.deck.pop(0))
        _rescore(p, state.target_score)
        events.append({
            "type": "INITIAL_CARD",
            "seat": i, "user_id": p.user_id,
            "score": p.score,
            "busted": p.busted,
            "disqualified": p.disqualified,
        })

    state.phase = "DRAW"
    state.draw_active_count = sum(1 for i in in_hand if state.players[i].in_hand)
    events.append({"type": "PHASE", "phase": "DRAW", "draw_active_count": state.draw_active_count})

    # First DRAW seat is the lowest-indexed seat that can still draw
    first = next((i for i in in_hand if state.players[i].can_draw), None)
    if first is None:
        _enter_showdown(state, events)
    else:
        _set_turn(state, first)


def _maybe_end_betting(state: GameState, events: List[Dict[str, Any]], current_seat: int) -> bool:
    """If betting round is complete, transition. Returns True if transitioned."""
    in_hand = _in_hand_seats(state)
    if len(in_hand) <= 1:
        _end_betting_to_deal(state, events)
        return True
    # All in-hand players have responded to the latest raise (or there's no raise and all checked)
    if all(seat in state.responded_seats for seat in in_hand):
        _end_betting_to_deal(state, events)
        return True
    # else move turn to next in-hand player
    nxt = _next_in_hand(state, current_seat)
    if nxt is not None:
        _set_turn(state, nxt)
    return False


def _maybe_end_draw(state: GameState, events: List[Dict[str, Any]], current_seat: int) -> bool:
    """Check stand-threshold or all-stood/busted-out -> SHOWDOWN.
    Returns True if SHOWDOWN was entered."""
    in_hand = [p for p in state.players if p.in_hand]
    if len(in_hand) <= 1:
        _enter_showdown(state, events)
        return True

    drawers = [p for p in in_hand if p.can_draw]
    if not drawers:
        _enter_showdown(state, events)
        return True

    stands = sum(1 for p in in_hand if p.stood and not p.busted and not p.disqualified)
    threshold = STAND_THRESHOLD.get(state.draw_active_count, state.draw_active_count)
    if stands >= threshold:
        _enter_showdown(state, events)
        return True

    # advance turn
    nxt = _next_drawer(state, current_seat)
    if nxt is None:
        _enter_showdown(state, events)
        return True
    _set_turn(state, nxt)
    return False


def _enter_showdown(state: GameState, events: List[Dict[str, Any]]) -> None:
    state.phase = "SHOWDOWN"
    state.current_turn_seat = None
    state.turn_started_at_ms = None
    state.turn_deadline_ms = None

    eligible = [p for p in state.players if p.in_hand and not p.busted]
    winners: List[PlayerState] = []
    if eligible:
        best = max(p.score for p in eligible)
        winners = [p for p in eligible if p.score == best]

    if winners:
        bps = COMMISSION_PAID_BPS if state.table_type == "PAID" else COMMISSION_FREE_BPS
        commission = (state.pot * bps) // 10000
        lottery = (commission * LOTTERY_BPS) // 10000
        net_pot = state.pot - commission
        share = net_pot // len(winners)
        remainder = net_pot - share * len(winners)
        for i, w in enumerate(winners):
            w.payout = share + (remainder if i == 0 else 0)
        state.winners = [w.user_id for w in winners]
        events.append({
            "type": "SHOWDOWN",
            "winners": [
                {"user_id": w.user_id, "seat": w.seat_index, "score": w.score, "payout": w.payout}
                for w in winners
            ],
            "commission": commission,
            "lottery_contribution": lottery,
        })
    else:
        events.append({"type": "SHOWDOWN", "winners": [], "commission": 0, "lottery_contribution": 0})

    state.phase = "PAYOUT"
    events.append({"type": "PHASE", "phase": "PAYOUT"})


# ============================================================
# Auto bust-save (Hearts-2 / Clubs-2) — applied inline on HIT bust
# ============================================================

def _attempt_bust_save(state: GameState, seat: int, events: List[Dict[str, Any]]) -> bool:
    """If `state.players[seat]` just busted and holds a defense 2, try to
    transfer the highest non-2/non-Joker card to an active opponent.
    Returns True if bust was successfully averted.
    """
    p = state.players[seat]
    if p.disqualified:
        return False  # joker overrides
    defense_idx = next(
        (i for i, c in enumerate(p.cards) if _is_defense_card(c)),
        None,
    )
    if defense_idx is None:
        return False

    # Eligible recipient: any in-hand opponent that can still draw or has a hand
    candidates = [
        i for i, q in enumerate(state.players)
        if i != seat and q.in_hand and not q.busted
    ]
    if not candidates:
        return False
    target_seat = candidates[0]
    target = state.players[target_seat]

    # Highest non-defense, non-joker card in seat's hand (excluding the defense itself)
    transferable = [
        i for i, c in enumerate(p.cards)
        if i != defense_idx and c.get("rank") != "JOKER" and not _is_defense_card(c)
    ]
    if not transferable:
        return False

    def _val(idx):
        from .scoring import card_base_value
        return card_base_value(p.cards[idx]["rank"])

    transferable.sort(key=_val, reverse=True)
    src_idx = transferable[0]
    transferred = p.cards[src_idx]

    # Apply transfer + consume defense
    target.cards.append(transferred)
    new_cards = [c for i, c in enumerate(p.cards) if i not in (src_idx, defense_idx)]
    p.cards = new_cards

    _rescore(p, state.target_score)
    _rescore(target, state.target_score)

    if p.busted:
        # bust-save failed (still busting after transfer) — restore? no, defense already consumed.
        # The spec says: "if resulting score <= target": bust prevented. So we attempt; if still
        # busted, we leave the new state (player still busts; defense is consumed).
        events.append({
            "type": "BUST_SAVE_FAILED",
            "seat": seat, "user_id": p.user_id,
            "transferred_card": transferred, "to_seat": target_seat,
        })
        return False

    p.stood = True   # forced stand after a successful bust-save
    events.append({
        "type": "BUST_SAVE",
        "seat": seat, "user_id": p.user_id,
        "transferred_card": transferred, "to_seat": target_seat,
        "to_user_id": target.user_id,
        "saver_score": p.score, "target_score": target.score,
        "target_busted": target.busted, "target_disqualified": target.disqualified,
    })
    return True


# ============================================================
# Main reducer
# ============================================================

def reduce(state: GameState, action: Dict[str, Any]) -> Tuple[GameState, List[Dict[str, Any]]]:
    """Pure: never mutates input."""
    state = deepcopy(state)
    events: List[Dict[str, Any]] = []
    a_type = action["type"]
    user_id = action.get("user_id")
    source = action.get("source", "CLIENT")

    if a_type in SERVER_ONLY_ACTIONS and source != "SERVER":
        raise ReducerError(f"SERVER_ONLY_ACTION: {a_type}")

    # ----- START_HAND (server) -----
    if a_type == "START_HAND":
        target = int(action.get("target_score", state.target_score))
        _check_target_score(target)
        state.target_score = target

        nonce = action["nonce"]
        seed = compute_shuffle_seed(
            action["server_seed"], action.get("client_seeds", ""), nonce,
        )
        state.deck = [c.to_dict() for c in shuffle(build_fresh_deck(include_jokers=True), seed)]
        state.hand_id = action["hand_id"]
        state.hand_number += 1
        state.rng_nonce = nonce
        state.rng_commit_hash = action["server_seed_hash"]
        state.pot = 0
        state.winners = []
        state.last_action_summary = None
        state.current_call_owed = 0
        state.last_raise_amount = 0
        state.responded_seats = []
        state.draw_active_count = 0

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

        # ANTE auto-collect
        state.phase = "ANTE"
        for p in state.players:
            if not p.sitting_out:
                p.total_contributed += state.stake
                state.pot += state.stake
        events.append({
            "type": "ANTES_COLLECTED",
            "amount_per_player": state.stake, "pot": state.pot,
        })

        # → BETTING_R1
        state.phase = "BETTING_R1"
        first = next(
            (i for i, p in enumerate(state.players) if p.in_hand),
            None,
        )
        if first is None:
            _enter_showdown(state, events)
        else:
            _set_turn(state, first)
            events.append({"type": "PHASE", "phase": "BETTING_R1", "first_seat": first})
        state.version += 1
        return state, events

    # ============================================================
    # BETTING actions: BET / CHECK / CALL / RAISE / FOLD
    # ============================================================
    if a_type in ("BET", "CHECK", "CALL", "RAISE", "FOLD"):
        if state.phase != "BETTING_R1":
            # FOLD is also accepted in DRAW (handled below); BETTING actions otherwise are wrong-phase
            if not (a_type == "FOLD" and state.phase == "DRAW"):
                raise ReducerError("WRONG_PHASE")

        seat = action.get("seat_index")
        if seat is None:
            seat = _seat_by_user(state, user_id)
        if seat is None or seat != state.current_turn_seat:
            raise ReducerError("NOT_YOUR_TURN")
        p = state.players[seat]

        if a_type == "FOLD":
            p.folded = True
            events.append({"type": "FOLD", "seat": seat, "user_id": p.user_id})
            if state.phase == "BETTING_R1":
                _maybe_end_betting(state, events, seat)
            else:
                _maybe_end_draw(state, events, seat)
            state.last_action_summary = {"action": "FOLD", "seat": seat}
            state.version += 1
            return state, events

        # BET — only legal as first action when no call is owed
        if a_type == "BET":
            if state.current_call_owed != 0:
                raise ReducerError("BET_WHEN_CALL_OWED")
            amount = int(action.get("payload", {}).get("amount", 0))
            if amount <= 0:
                raise ReducerError("INVALID_BET")
            cap = _max_raise_cap(state, seat)
            if cap == 0:
                raise ReducerError("BET_NOT_PAYABLE")
            if amount > cap:
                raise ReducerError(f"BET_EXCEEDS_CAP: max={cap}")
            if amount > p.available_balance():
                raise ReducerError("INSUFFICIENT_BALANCE")
            p.total_contributed += amount
            p.current_bet += amount
            state.pot += amount
            state.last_raise_amount = amount
            state.current_call_owed = _required_call(amount)
            state.responded_seats = [seat]
            events.append({
                "type": "BET", "seat": seat, "user_id": p.user_id,
                "amount": amount, "pot": state.pot,
                "call_required": state.current_call_owed,
            })
            _maybe_end_betting(state, events, seat)
            state.last_action_summary = {"action": "BET", "seat": seat, "amount": amount}
            state.version += 1
            return state, events

        if a_type == "RAISE":
            if state.current_call_owed == 0:
                raise ReducerError("RAISE_REQUIRES_OPEN_BET")
            raise_amt = int(action.get("payload", {}).get("amount", 0))
            if raise_amt <= 0:
                raise ReducerError("INVALID_RAISE")
            cap = _max_raise_cap(state, seat)
            if raise_amt > cap:
                raise ReducerError(f"RAISE_EXCEEDS_CAP: max={cap}")
            call_part = state.current_call_owed
            total = call_part + raise_amt
            if p.available_balance() < total:
                raise ReducerError("INSUFFICIENT_BALANCE")
            p.total_contributed += total
            p.current_bet += total
            state.pot += total
            state.last_raise_amount = raise_amt
            state.current_call_owed = _required_call(raise_amt)
            state.responded_seats = [seat]
            events.append({
                "type": "RAISE", "seat": seat, "user_id": p.user_id,
                "call_paid": call_part, "raise_amount": raise_amt,
                "pot": state.pot, "call_required": state.current_call_owed,
            })
            _maybe_end_betting(state, events, seat)
            state.last_action_summary = {"action": "RAISE", "seat": seat, "amount": raise_amt}
            state.version += 1
            return state, events

        if a_type == "CALL":
            if state.current_call_owed == 0:
                raise ReducerError("NOTHING_TO_CALL")
            amount = state.current_call_owed
            if p.available_balance() < amount:
                # 51% rule: cannot pay -> auto-fold
                p.folded = True
                events.append({
                    "type": "FOLD", "seat": seat, "user_id": p.user_id,
                    "auto": True, "reason": "INSUFFICIENT_FOR_CALL",
                })
                _maybe_end_betting(state, events, seat)
                state.last_action_summary = {"action": "AUTO_FOLD", "seat": seat}
                state.version += 1
                return state, events
            p.total_contributed += amount
            p.current_bet += amount
            state.pot += amount
            if seat not in state.responded_seats:
                state.responded_seats.append(seat)
            events.append({
                "type": "CALL", "seat": seat, "user_id": p.user_id,
                "amount": amount, "pot": state.pot,
            })
            _maybe_end_betting(state, events, seat)
            state.last_action_summary = {"action": "CALL", "seat": seat}
            state.version += 1
            return state, events

        if a_type == "CHECK":
            if state.current_call_owed != 0:
                raise ReducerError("CANNOT_CHECK_FACING_BET")
            if seat not in state.responded_seats:
                state.responded_seats.append(seat)
            events.append({"type": "CHECK", "seat": seat, "user_id": p.user_id})
            _maybe_end_betting(state, events, seat)
            state.last_action_summary = {"action": "CHECK", "seat": seat}
            state.version += 1
            return state, events

    # ============================================================
    # DRAW actions: HIT / STAND / AUTO_STAND_TIMEOUT / PLAY_TWO / PLAY_TEN
    # ============================================================
    if a_type in ("HIT", "STAND", "AUTO_STAND_TIMEOUT", "PLAY_TWO", "PLAY_TEN"):
        if state.phase != "DRAW":
            raise ReducerError("WRONG_PHASE")
        seat = action.get("seat_index")
        if seat is None:
            seat = _seat_by_user(state, user_id)
        if seat is None or seat != state.current_turn_seat:
            raise ReducerError("NOT_YOUR_TURN")
        p = state.players[seat]

        if a_type == "HIT":
            if not state.deck:
                raise ReducerError("DECK_EMPTY")
            card = state.deck.pop(0)
            p.cards.append(card)
            _rescore(p, state.target_score)
            ev = {
                "type": "CARD_DRAWN", "seat": seat, "user_id": p.user_id,
                "card": card, "score": p.score,
                "busted": p.busted, "disqualified": p.disqualified,
            }
            events.append(ev)
            if p.busted and not p.disqualified:
                # try bust-save
                _attempt_bust_save(state, seat, events)
            if p.busted or p.disqualified:
                p.stood = True
            state.last_action_summary = {"action": "HIT", "seat": seat}
            if p.stood or p.busted or p.disqualified:
                _maybe_end_draw(state, events, seat)
            else:
                _set_turn(state, seat)  # refresh deadline; same player keeps acting
            state.version += 1
            return state, events

        if a_type in ("STAND", "AUTO_STAND_TIMEOUT"):
            p.stood = True
            reason = (
                action.get("payload", {}).get("reason")
                or ("CLIENT_STAND" if a_type == "STAND" else TURN_TIMEOUT_REASON)
            )
            events.append({
                "type": "STAND", "seat": seat, "user_id": p.user_id,
                "score": p.score, "auto": a_type == "AUTO_STAND_TIMEOUT",
                "reason": reason,
            })
            state.last_action_summary = {
                "action": "AUTO_STAND" if a_type == "AUTO_STAND_TIMEOUT" else "STAND",
                "seat": seat,
            }
            _maybe_end_draw(state, events, seat)
            state.version += 1
            return state, events

        if a_type == "PLAY_TWO":
            payload = action.get("payload", {}) or {}
            target_user = payload.get("target_user_id")
            transfer_idx = payload.get("transfer_card_index")
            if target_user is None or transfer_idx is None:
                raise ReducerError("PLAY_TWO_BAD_PAYLOAD")
            target_seat = _seat_by_user(state, target_user)
            if target_seat is None or target_seat == seat:
                raise ReducerError("PLAY_TWO_BAD_TARGET")
            target = state.players[target_seat]
            if not target.in_hand or target.busted:
                raise ReducerError("PLAY_TWO_TARGET_INACTIVE")
            # Find a defense 2 in player's hand
            def_idx = next(
                (i for i, c in enumerate(p.cards) if _is_defense_card(c)),
                None,
            )
            if def_idx is None:
                raise ReducerError("PLAY_TWO_NO_DEFENSE_CARD")
            if not (0 <= int(transfer_idx) < len(p.cards)):
                raise ReducerError("PLAY_TWO_BAD_INDEX")
            transfer_idx = int(transfer_idx)
            if transfer_idx == def_idx:
                raise ReducerError("PLAY_TWO_CANT_SEND_DEFENSE_ITSELF")
            transferred = p.cards[transfer_idx]
            # remove transfer card and the defense card
            p.cards = [c for i, c in enumerate(p.cards) if i not in (transfer_idx, def_idx)]
            target.cards.append(transferred)
            _rescore(p, state.target_score)
            _rescore(target, state.target_score)
            events.append({
                "type": "PLAY_TWO", "seat": seat, "user_id": p.user_id,
                "to_seat": target_seat, "to_user_id": target.user_id,
                "transferred_card": transferred,
                "saver_score": p.score, "target_score": target.score,
                "target_busted": target.busted, "target_disqualified": target.disqualified,
            })
            if target.busted or target.disqualified:
                target.stood = True
            state.last_action_summary = {"action": "PLAY_TWO", "seat": seat}
            _maybe_end_draw(state, events, seat)
            state.version += 1
            return state, events

        if a_type == "PLAY_TEN":
            payload = action.get("payload", {}) or {}
            target_user = payload.get("target_user_id")
            attack_idx = payload.get("attack_card_index")
            if target_user is None or attack_idx is None:
                raise ReducerError("PLAY_TEN_BAD_PAYLOAD")
            target_seat = _seat_by_user(state, target_user)
            if target_seat is None or target_seat == seat:
                raise ReducerError("PLAY_TEN_BAD_TARGET")
            target = state.players[target_seat]
            if not target.in_hand or target.busted:
                raise ReducerError("PLAY_TEN_TARGET_INACTIVE")
            ten_idx = next(
                (i for i, c in enumerate(p.cards) if _is_attack_card(c)),
                None,
            )
            if ten_idx is None:
                raise ReducerError("PLAY_TEN_NO_ATTACK_CARD")
            if not (0 <= int(attack_idx) < len(p.cards)):
                raise ReducerError("PLAY_TEN_BAD_INDEX")
            attack_idx = int(attack_idx)
            if attack_idx == ten_idx:
                raise ReducerError("PLAY_TEN_CANT_SEND_TRIGGER_ITSELF")
            sent = p.cards[attack_idx]
            p.cards = [c for i, c in enumerate(p.cards) if i not in (attack_idx, ten_idx)]
            target.cards.append(sent)
            _rescore(p, state.target_score)
            _rescore(target, state.target_score)
            events.append({
                "type": "PLAY_TEN", "seat": seat, "user_id": p.user_id,
                "to_seat": target_seat, "to_user_id": target.user_id,
                "sent_card": sent,
                "attacker_score": p.score, "target_score": target.score,
                "target_busted": target.busted, "target_disqualified": target.disqualified,
            })
            if target.busted or target.disqualified:
                target.stood = True
            state.last_action_summary = {"action": "PLAY_TEN", "seat": seat}
            _maybe_end_draw(state, events, seat)
            state.version += 1
            return state, events

    raise ReducerError(f"UNKNOWN_ACTION: {a_type}")
