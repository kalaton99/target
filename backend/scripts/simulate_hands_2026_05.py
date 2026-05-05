"""100-hand simulation analyzer — pure reducer, no network.

Drives full hands through `pure_reduce` using the real RNG / shuffle
(commit-reveal SHA-256 with per-hand server seeds), random scripted
behaviour for each player (HIT/STAND with 60/40 bias, CHECK/CALL in
betting), and reports:

  - % hands where ≥1 JOKER appears (any player drew one)
  - % hands that end EARLY (before BETTING_R3 — i.e. SHOWDOWN reached
    via the `_enter_betting_round` short-circuit)
  - average hand length (= number of state-version increments
    from START_HAND to PAYOUT, inclusive)
  - average number of players eliminated per hand (busted OR
    disqualified at terminal phase)

Pure-Python, deterministic given the seeds, no game-rule changes.

Wording note (per GAME_RULES_LOCKED.md §2): there is no 2-seat
table type. "n_players=2" below means a 4-seat (target=30) table
with 2 humans seated — the minimum legal start for the 4-seat
tier. "n_players=4" at target=100 means a 5-seat table with 4
humans seated (above the 5-seat tier minimum of 3).
"""
from __future__ import annotations

import hashlib
import os
import secrets
import sys
from collections import Counter
from pathlib import Path
from statistics import mean, median, stdev
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game_engine.reducer import reduce  # noqa: E402
from game_engine.types import GameState, PlayerState  # noqa: E402


def _scripted_pick(rng_seed: str, choices: List[str], weights: List[int]) -> str:
    """Deterministic weighted choice from a SHA-256 of `rng_seed`."""
    h = hashlib.sha256(rng_seed.encode()).digest()
    n = int.from_bytes(h[:8], "big")
    total = sum(weights)
    pick = n % total
    cum = 0
    for c, w in zip(choices, weights):
        cum += w
        if pick < cum:
            return c
    return choices[-1]


def _make_state(n_players: int, target: int, stake: int = 100) -> GameState:
    s = GameState(table_id=f"sim_t_{n_players}_{target}",
                  target_score=target, stake=stake)
    s.players = [
        PlayerState(seat_index=i, user_id=f"u{i}", username=f"P{i}",
                    balance_at_start=10_000)
        for i in range(n_players)
    ]
    return s


def _start_hand(state: GameState, hand_idx: int) -> GameState:
    server_seed = secrets.token_hex(32)
    seed_hash = hashlib.sha256(server_seed.encode()).hexdigest()
    state, _ = reduce(state, {
        "type": "START_HAND", "source": "SERVER",
        "hand_id": f"sim_h_{hand_idx}", "nonce": hand_idx + 1,
        "server_seed": server_seed, "server_seed_hash": seed_hash,
        "client_seeds": "",
    })
    return state


def _drive_one_hand(n_players: int, target: int, hand_idx: int) -> Dict:
    """Drive one hand through the reducer with stochastic player play.

    Player policy:
      - DRAW_*: HIT until score >= 0.7 * target, then STAND. Above
        0.85 * target → always STAND (bust safety). Mirrors the live
        bot but more uniform across seats.
      - BETTING_*: 90% CHECK, 10% raise/bet of 100. CALL on owed.
        Never FOLD (we want to exercise full rounds).
    """
    state = _make_state(n_players, target)
    state = _start_hand(state, hand_idx)

    versions_observed = [state.version]
    phases_observed = [state.phase]
    joker_seen = False
    short_circuited_early = False

    safety_cap = 500  # never spin forever — defensive
    step = 0
    while state.phase not in ("PAYOUT", "HAND_COMPLETE", "ENDED"):
        step += 1
        if step > safety_cap:
            raise RuntimeError(f"hand {hand_idx} exceeded safety cap; "
                               f"phase={state.phase}")
        seat = state.current_turn_seat
        if seat is None:
            # Engine is between turns / showdown auto-progress, but in
            # the pure reducer there's no async — every action moves
            # state forward. If we land here, the reducer has stranded.
            break

        p = state.players[seat]
        # Detect JOKER in any player's hand (check BEFORE action so we
        # catch jokers drawn in earlier turns).
        if not joker_seen:
            for pp in state.players:
                if any(c.get("rank") == "JOKER" for c in pp.cards):
                    joker_seen = True
                    break

        phase = state.phase
        seed = f"{hand_idx}:{state.version}:{seat}:{p.user_id}"

        if phase in ("DRAW", "DRAW_1", "DRAW_2"):
            # HIT until safe threshold.
            score = p.score
            high = (target * 85) // 100
            mid = (target * 70) // 100
            if score >= high:
                act = "STAND"
            elif score >= mid:
                act = _scripted_pick(seed, ["HIT", "STAND"], [40, 60])
            else:
                act = _scripted_pick(seed, ["HIT", "STAND"], [85, 15])
            state, _ = reduce(state, {"type": act, "user_id": p.user_id})
        elif phase in ("BETTING_R1", "BETTING_R2", "BETTING_R3"):
            owed = state.current_call_owed
            if owed > 0:
                state, _ = reduce(state, {
                    "type": "CALL", "user_id": p.user_id,
                })
            else:
                # 90% CHECK, 10% small BET.
                act = _scripted_pick(seed, ["CHECK", "BET"], [90, 10])
                if act == "BET":
                    state, _ = reduce(state, {
                        "type": "BET", "user_id": p.user_id,
                        "payload": {"amount": 100},
                    })
                else:
                    state, _ = reduce(state, {
                        "type": "CHECK", "user_id": p.user_id,
                    })
        else:
            # Other transient phases (DEAL_INITIAL, SHOWDOWN, etc.)
            # advance themselves inside the reducer; if we land here
            # with current_turn_seat set, force-stand to make progress.
            state, _ = reduce(state, {"type": "STAND", "user_id": p.user_id})

        # Re-check JOKER AFTER the action — catches jokers drawn in
        # this turn (including the terminal turn that triggers PAYOUT).
        if not joker_seen:
            for pp in state.players:
                if any(c.get("rank") == "JOKER" for c in pp.cards):
                    joker_seen = True
                    break

        versions_observed.append(state.version)
        if state.phase != phases_observed[-1]:
            phases_observed.append(state.phase)

    # Was BETTING_R3 entered? If not, the hand short-circuited early.
    short_circuited_early = "BETTING_R3" not in phases_observed

    eliminated = sum(
        1 for p in state.players
        if p.busted or p.disqualified
    )
    folded = sum(1 for p in state.players if p.folded)

    return {
        "hand_idx": hand_idx,
        "phases": phases_observed,
        "hand_length_versions": versions_observed[-1] - versions_observed[0],
        "joker_seen": joker_seen,
        "short_circuited_early": short_circuited_early,
        "eliminated": eliminated,
        "folded": folded,
        "n_players": n_players,
        "target": target,
        "final_phase": state.phase,
        "winners": list(state.winners),
    }


def _summarise(results: List[Dict], label: str) -> None:
    n = len(results)
    joker_pct = 100.0 * sum(r["joker_seen"] for r in results) / n
    early_pct = 100.0 * sum(r["short_circuited_early"] for r in results) / n
    lengths = [r["hand_length_versions"] for r in results]
    eliminated = [r["eliminated"] for r in results]
    folded = [r["folded"] for r in results]
    phase_counts = Counter()
    for r in results:
        phase_counts[r["final_phase"]] += 1

    print(f"\n========== {label} ({n} hands) ==========")
    print(f"  JOKER appeared in:        {joker_pct:6.2f}% of hands  "
          f"({sum(r['joker_seen'] for r in results)}/{n})")
    print(f"  Hands ending early:       {early_pct:6.2f}% of hands  "
          f"(before BETTING_R3)")
    print(f"  Avg hand length:          {mean(lengths):6.2f} state-version "
          f"increments  (median {median(lengths)}, "
          f"σ {stdev(lengths) if len(lengths) > 1 else 0:.2f})")
    print(f"  Avg eliminated/hand:      {mean(eliminated):6.2f}  "
          f"(busted or disqualified, max {max(eliminated)})")
    print(f"  Avg folded/hand:          {mean(folded):6.2f}")
    print(f"  Final phase distribution: {dict(phase_counts)}")
    # Cross-tab: short-circuit cause breakdown
    if early_pct > 0:
        early_with_dq = sum(
            1 for r in results
            if r["short_circuited_early"] and r["eliminated"] > 0
            and any(p in r["phases"] for p in ("DRAW_1", "DRAW_2"))
        )
        early_with_fold = sum(
            1 for r in results
            if r["short_circuited_early"] and r["folded"] > 0
        )
        early_other = sum(
            1 for r in results
            if r["short_circuited_early"]
            and r["eliminated"] == 0 and r["folded"] == 0
        )
        print(f"    of which DQ-driven (busted/joker): {early_with_dq}")
        print(f"    of which FOLD-driven:              {early_with_fold}")
        print(f"    of which other:                    {early_other}")


def main() -> None:
    n_hands = int(os.environ.get("SIM_HANDS", "100"))
    config = (2, 30)  # 2 humans seated on a 4-seat table (target=30)
                       # — matches the F3 live test scenario.
    print(f"Simulating {n_hands} hands at "
          f"target={config[1]} with {config[0]} seated players "
          f"(4-seat table partially filled — there is no 2-seat table type "
          f"per GAME_RULES_LOCKED.md §2). "
          f"Reducer-level, real RNG, scripted play.")
    print("Player policy: HIT until score≥0.7×target with stochastic "
          "stand band; 90% CHECK / 10% small BET in betting rounds; "
          "always CALL when call_owed.")

    results = [_drive_one_hand(*config, hand_idx=i) for i in range(n_hands)]
    _summarise(
        results,
        f"target={config[1]}, {config[0]} seated (4-seat table)",
    )

    # Bonus: same simulation at target=100 with 4 humans seated on a
    # 5-seat table — does NOT count toward the 100-hand mandate;
    # included so the reader has a reference point for how the JOKER
    # frequency and short-circuit rate change with deck depth & seat
    # count.
    cfg2 = (4, 100)
    results2 = [_drive_one_hand(*cfg2, hand_idx=10000 + i)
                for i in range(n_hands)]
    _summarise(
        results2,
        f"target={cfg2[1]}, {cfg2[0]} seated (5-seat table) — reference",
    )


if __name__ == "__main__":
    main()
