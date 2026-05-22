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
    MAX_DRAWS_PER_TURN,
    SERVER_ONLY_ACTIONS,
    STAND_THRESHOLD,
    TURN_TIMEOUT_MS,
    TURN_TIMEOUT_REASON,
    VALID_TARGET_SCORES,
)
from .deck import build_fresh_deck, compute_shuffle_seed, shuffle
from .rng import combine_client_seeds_by_seat
from .scoring import score_hand
from .types import GameState, PlayerState


def now_ms() -> int:
    return int(time.time() * 1000)


class ReducerError(Exception):
    pass


# ============================================================
# Helpers
# ============================================================

def _refill_deck_if_empty(state: GameState, events: List[Dict[str, Any]]) -> None:
    """2026-02 rule: when the initial 53-card deck (52 + 1 Joker) is
    exhausted mid-hand, continue with a fresh 52-card jokerless deck.

    The discard pile is NOT reshuffled — we build a brand-new 52-card
    deck from scratch and shuffle it deterministically using a seed
    derived from the original hand commit hash + refill counter, so
    replays reproduce the same card order.

    Safe to call before any `state.deck.pop(0)` — it is a no-op when
    the deck still has cards.
    """
    if state.deck:
        return
    state.deck_refills = int(getattr(state, "deck_refills", 0)) + 1
    # Derive a fresh shuffle seed from the hand's RNG commit + refill
    # counter. Using hand_id + nonce + refills keeps the derivation
    # independent of the original (seed,client_seeds,nonce) so a deck
    # refill never exposes or re-uses the initial seed.
    seed_src = (
        f"{state.rng_commit_hash or ''}:"
        f"{state.hand_id or ''}:"
        f"{state.rng_nonce or 0}:"
        f"refill{state.deck_refills}"
    )
    import hashlib as _hashlib
    seed = _hashlib.sha256(seed_src.encode("utf-8")).hexdigest()
    state.deck = [
        c.to_dict()
        for c in shuffle(build_fresh_deck(include_jokers=False), seed)
    ]
    events.append({
        "type": "DECK_REFILLED",
        "refill_number": state.deck_refills,
        "deck_size": len(state.deck),
        "jokers_included": False,
    })


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

def _enter_betting_round(state: GameState, events: List[Dict[str, Any]], round_n: int) -> None:
    """Enter BETTING_R{round_n} (2026-05 multi-round extension).

    Resets per-round betting bookkeeping so the round is independent of
    earlier rounds:
      - `current_call_owed` and `last_raise_amount` go back to 0.
      - `responded_seats` is cleared.
      - Each in-hand player's `current_bet` resets — represents
        commitment for THIS round only. `total_contributed` keeps
        accumulating across rounds for the payout-delta UX math.

    Players who STOOD in an earlier draw round retain `stood = True`
    (sticky stand across rounds) — they can still CHECK / CALL / RAISE
    / FOLD here but cannot HIT once DRAW_2 begins. This matches typical
    card-game intuition: once you lock in your hand, you're committed.

    First turn = lowest-indexed in_hand seat. Mirrors the BETTING_R1
    setup at START_HAND so client UX is identical for R2 / R3.
    """
    in_hand = _in_hand_seats(state)
    if len(in_hand) <= 1:
        _enter_showdown(state, events)
        return
    state.phase = f"BETTING_R{round_n}"
    state.betting_round = round_n
    state.current_call_owed = 0
    state.last_raise_amount = 0
    state.responded_seats = []
    for i in in_hand:
        state.players[i].current_bet = 0
    first = in_hand[0]
    _set_turn(state, first)
    events.append({
        "type": "PHASE",
        "phase": state.phase,
        "betting_round": round_n,
        "first_seat": first,
    })


def _enter_draw_round(state: GameState, events: List[Dict[str, Any]], draw_n: int) -> None:
    """Enter DRAW_{draw_n} as an interactive HIT/STAND/PLAY_TWO/PLAY_TEN
    phase (2026-05 multi-round extension).

    Behaviour identical to the legacy single-DRAW phase:
      - Eligible players (`can_draw`: in_hand AND not stood/busted/DQ)
        take turns acting. Round ends by stand-threshold, all-stood,
        or ≤1 in_hand.
      - Stood players from a prior round stay stood (their `can_draw`
        is False, so they're skipped for turn-rotation but still
        eligible for the per-hand SHOWDOWN with their frozen score).

    `draw_active_count` is recomputed each entry — a 4-seat hand where
    one player folded in BETTING_R2 enters DRAW_2 with active_count=3.
    """
    in_hand = _in_hand_seats(state)
    if len(in_hand) <= 1:
        _enter_showdown(state, events)
        return
    state.phase = f"DRAW_{draw_n}"
    state.betting_round = 0
    state.draw_active_count = sum(
        1 for i in in_hand if state.players[i].in_hand
    )
    for i in in_hand:
        state.players[i].draws_this_turn = 0
    events.append({
        "type": "PHASE",
        "phase": state.phase,
        "draw_round": draw_n,
        "draw_active_count": state.draw_active_count,
    })
    # First turn = lowest in_hand seat that can still draw. If everyone
    # already stood in a prior round, there are no drawers — auto-end
    # the round by routing through `_maybe_end_draw`-like dispatch.
    first = next(
        (i for i in in_hand if state.players[i].can_draw),
        None,
    )
    if first is None:
        # No one can draw — round is vacuously over. Route to next
        # phase without leaving DRAW_n hanging.
        if draw_n == 1:
            _enter_betting_round(state, events, 2)
        elif draw_n == 2:
            _enter_betting_round(state, events, 3)
        else:
            _enter_showdown(state, events)
        return
    _set_turn(state, first)


def _end_betting_to_deal(state: GameState, events: List[Dict[str, Any]]) -> None:
    """End-of-betting transition.

    Single entry-point used by `_maybe_end_betting`. Dispatches by the
    current phase so the same hook drives all three rounds:

      BETTING_R1 → DEAL_INITIAL (1 card each) → DRAW_1 (interactive)
      BETTING_R2 → DRAW_2 (interactive — no extra deal; players keep
                   the cards they already drew in DRAW_1)
      BETTING_R3 → SHOWDOWN

    `≤ 1 in_hand` short-circuits straight to SHOWDOWN regardless of
    round (legacy behaviour preserved).
    """
    in_hand = [i for i in _in_hand_seats(state)]
    if len(in_hand) <= 1:
        _enter_showdown(state, events)
        return

    if state.phase == "BETTING_R1":
        # Deal 1 starting card to each in_hand player (DEAL_INITIAL),
        # then enter the first interactive draw round.
        state.phase = "DEAL_INITIAL"
        events.append({"type": "PHASE", "phase": "DEAL_INITIAL"})
        for i in in_hand:
            _refill_deck_if_empty(state, events)
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
        _enter_draw_round(state, events, 1)
        return

    if state.phase == "BETTING_R2":
        # Players keep their existing hands; open DRAW_2 for any
        # still-eligible drawers.
        _enter_draw_round(state, events, 2)
        return

    if state.phase == "BETTING_R3":
        _enter_showdown(state, events)
        return

    # Defensive: any unexpected phase falls through to showdown so a
    # bug in the state-machine never strands a hand mid-flight.
    _enter_showdown(state, events)


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
    # 2026-05 v2 stabilization: defensive guard. If no next in-hand seat
    # exists (should be unreachable given len(in_hand) >= 2 above, but
    # kept as a belt-and-braces stop against future edits introducing a
    # silent stall), force phase advance instead of leaving the state
    # stuck with current_turn_seat pointing at a seat that already acted.
    _end_betting_to_deal(state, events)
    return True


def _end_draw_round(state: GameState, events: List[Dict[str, Any]]) -> None:
    """End-of-draw transition (2026-05 multi-round extension).

    Called when the current draw round has nothing left to do (≤1
    in_hand, no remaining drawers, or stand-threshold met). Routes to
    the next phase based on the current phase string:

      DRAW_1 → BETTING_R2  (unless ≤1 in_hand → SHOWDOWN)
      DRAW_2 → BETTING_R3  (unless ≤1 in_hand → SHOWDOWN)
      DRAW   → SHOWDOWN    (legacy single-draw flow, unchanged)

    The ≤1 in_hand check is enforced by `_enter_betting_round` itself,
    so callers don't need to repeat it.
    """
    if state.phase == "DRAW_1":
        _enter_betting_round(state, events, 2)
    elif state.phase == "DRAW_2":
        _enter_betting_round(state, events, 3)
    else:
        _enter_showdown(state, events)


def _maybe_end_draw(state: GameState, events: List[Dict[str, Any]], current_seat: int) -> bool:
    """Check stand-threshold or all-stood/busted-out -> next phase.

    Returns True if the round transitioned (to next betting round, or
    to SHOWDOWN). Same logic as before; only the terminal call is
    routed through `_end_draw_round` so multi-round transitions land
    in BETTING_R2 / BETTING_R3 instead of SHOWDOWN."""
    in_hand = [p for p in state.players if p.in_hand]
    if len(in_hand) <= 1:
        _enter_showdown(state, events)
        return True

    drawers = [p for p in in_hand if p.can_draw]
    if not drawers:
        _end_draw_round(state, events)
        return True

    stands = sum(1 for p in in_hand if p.stood and not p.busted and not p.disqualified)
    threshold = STAND_THRESHOLD.get(state.draw_active_count, state.draw_active_count)
    if stands >= threshold:
        _end_draw_round(state, events)
        return True

    # advance turn
    nxt = _next_drawer(state, current_seat)
    if nxt is None:
        _end_draw_round(state, events)
        return True
    state.players[nxt].draws_this_turn = 0
    _set_turn(state, nxt)
    return False


def _enter_showdown(state: GameState, events: List[Dict[str, Any]]) -> None:
    state.phase = "SHOWDOWN"
    state.current_turn_seat = None
    state.turn_started_at_ms = None
    state.turn_deadline_ms = None
    # 2026-05 v2 — reveal the plain server_seed for verification.
    # Anyone with the original commit-hash + revealed seed +
    # `client_seeds_used` + nonce can reproduce the deck and verify
    # this hand was provably fair.
    if state.server_seed_buffer is not None:
        state.rng_revealed_seed = state.server_seed_buffer
        state.server_seed_buffer = None

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

    # ----- SUBMIT_CLIENT_SEED (client) -----
    # 2026-05 v2 — players may contribute a per-seat seed to the
    # shuffle between hands. Allowed phases: WAITING / PAYOUT / ENDED
    # (i.e. the gaps between hands). Outside those phases the seed is
    # locked and the action is rejected with `SEED_LOCKED`.
    if a_type == "SUBMIT_CLIENT_SEED":
        if state.phase not in ("WAITING", "PAYOUT", "ENDED"):
            raise ReducerError("SEED_LOCKED")
        seed_str = action.get("payload", {}).get("client_seed", action.get("client_seed"))
        if not isinstance(seed_str, str) or not seed_str:
            raise ReducerError("INVALID_SEED")
        # Hard cap so a malicious client can't blow the canonical
        # form / DB record. 256 chars is plenty for hex / base64.
        if len(seed_str) > 256:
            raise ReducerError("INVALID_SEED")
        seat = next(
            (p.seat_index for p in state.players if p.user_id == user_id),
            None,
        )
        if seat is None:
            raise ReducerError("NOT_SEATED")
        state.pending_client_seeds[seat] = seed_str
        state.version += 1
        events.append({
            "type": "CLIENT_SEED_SUBMITTED",
            "seat": seat, "user_id": user_id,
            "version": state.version,
        })
        return state, events

    # ----- START_HAND (server) -----
    if a_type == "START_HAND":
        target = int(action.get("target_score", state.target_score))
        _check_target_score(target)
        state.target_score = target

        nonce = action["nonce"]
        # 2026-05 v2 — per-seat client_seed contribution. Three accepted
        # forms for backwards compatibility & replay:
        #   1. action["client_seeds_by_seat"] (dict[int|str, str])
        #      — canonical new form; takes precedence and is recorded
        #      verbatim in `state.client_seeds_used`.
        #   2. fall back to `state.pending_client_seeds` accumulated
        #      via SUBMIT_CLIENT_SEED actions during WAITING/PAYOUT.
        #   3. legacy `action["client_seeds"]` string form (pre-v2):
        #      used only when neither (1) nor (2) is present.
        seat_order = [p.seat_index for p in state.players]
        # 2026-05 v2 — only fall back to the legacy string path when the
        # action *explicitly* provides `client_seeds` (i.e. the caller
        # is replaying a pre-v2 log). Every other code path — including
        # "no seeds at all" — uses the canonical per-seat combiner so
        # an external verifier can reproduce the deck without knowing
        # whether the hand pre-dated the v2 migration.
        if "client_seeds_by_seat" in action:
            raw = action["client_seeds_by_seat"] or {}
            client_seeds_by_seat = {int(k): v for k, v in raw.items()}
            combined = combine_client_seeds_by_seat(client_seeds_by_seat, seat_order)
        elif state.pending_client_seeds:
            client_seeds_by_seat = dict(state.pending_client_seeds)
            combined = combine_client_seeds_by_seat(client_seeds_by_seat, seat_order)
        elif "client_seeds" in action:
            # Legacy path — string form already-combined by caller.
            client_seeds_by_seat = {}
            combined = action.get("client_seeds", "")
        else:
            # No seeds → still canonical: combiner over an empty map.
            client_seeds_by_seat = {}
            combined = combine_client_seeds_by_seat({}, seat_order)
        seed = compute_shuffle_seed(action["server_seed"], combined, nonce)
        state.deck = [c.to_dict() for c in shuffle(build_fresh_deck(include_jokers=True), seed)]
        state.deck_refills = 0
        state.hand_id = action["hand_id"]
        state.hand_number += 1
        state.rng_nonce = nonce
        state.rng_commit_hash = action["server_seed_hash"]
        state.rng_revealed_seed = None  # locked until SHOWDOWN/PAYOUT
        # Buffer plain server_seed in-state for later reveal. View-filter
        # strips this from broadcasts (see `view_filter.public_view`).
        state.server_seed_buffer = action["server_seed"]
        # Lock the per-seat seeds for replay; clear pending.
        state.client_seeds_used = client_seeds_by_seat
        state.pending_client_seeds = {}
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
        state.betting_round = 1
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
        # 2026-05 multi-round betting: BETTING actions are accepted in
        # any of the three betting rounds. FOLD is also accepted in DRAW
        # (legacy single-draw flow) — preserved unchanged.
        in_betting = state.phase in ("BETTING_R1", "BETTING_R2", "BETTING_R3")
        in_draw = state.phase in ("DRAW", "DRAW_1", "DRAW_2")
        if not in_betting:
            # FOLD is also accepted in any DRAW phase (legacy + multi-round).
            if not (a_type == "FOLD" and in_draw):
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
            if in_betting:
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
        # 2026-05 multi-round: legacy "DRAW" plus new DRAW_1 / DRAW_2.
        if state.phase not in ("DRAW", "DRAW_1", "DRAW_2"):
            raise ReducerError("WRONG_PHASE")
        seat = action.get("seat_index")
        if seat is None:
            seat = _seat_by_user(state, user_id)
        if seat is None or seat != state.current_turn_seat:
            raise ReducerError("NOT_YOUR_TURN")
        p = state.players[seat]

        if a_type == "HIT":
            if len(p.cards) >= MAX_DRAWS_PER_TURN:
                p.stood = True
                events.append({
                    "type": "DRAW_LIMIT_REACHED",
                    "seat": seat,
                    "user_id": p.user_id,
                    "cards_held": len(p.cards),
                    "draw_limit": MAX_DRAWS_PER_TURN,
                })
                state.last_action_summary = {
                    "action": "DRAW_LIMIT_REACHED",
                    "seat": seat,
                    "cards_held": len(p.cards),
                    "draw_limit": MAX_DRAWS_PER_TURN,
                }
                _maybe_end_draw(state, events, seat)
                state.version += 1
                return state, events
            _refill_deck_if_empty(state, events)
            if not state.deck:
                # Refill yields 52 fresh cards, so this should never hit;
                # kept as a defensive guard.
                raise ReducerError("DECK_EMPTY")
            card = state.deck.pop(0)
            p.cards.append(card)
            p.draws_this_turn += 1
            _rescore(p, state.target_score)
            ev = {
                "type": "CARD_DRAWN", "seat": seat, "user_id": p.user_id,
                "card": card, "score": p.score,
                "busted": p.busted, "disqualified": p.disqualified,
                "draws_this_turn": p.draws_this_turn,
                "draw_limit": MAX_DRAWS_PER_TURN,
            }
            events.append(ev)
            if p.busted and not p.disqualified:
                # try bust-save
                _attempt_bust_save(state, seat, events)
            if p.busted or p.disqualified:
                p.stood = True
            draw_limit_reached = len(p.cards) >= MAX_DRAWS_PER_TURN and not (p.busted or p.disqualified)
            if draw_limit_reached:
                p.stood = True
                events.append({
                    "type": "DRAW_LIMIT_REACHED",
                    "seat": seat,
                    "user_id": p.user_id,
                    "cards_held": len(p.cards),
                    "draws_this_turn": p.draws_this_turn,
                    "draw_limit": MAX_DRAWS_PER_TURN,
                })
                state.last_action_summary = {
                    "action": "DRAW_LIMIT_REACHED",
                    "seat": seat,
                    "cards_held": len(p.cards),
                    "draws_this_turn": p.draws_this_turn,
                    "draw_limit": MAX_DRAWS_PER_TURN,
                }
            else:
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
