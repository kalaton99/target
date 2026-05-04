"""2026-05 v2 — Per-seat client_seed contribution tests.

Verifies the provably-fair RNG contract:
  1. Same (server_seed, client_seeds, nonce) → identical deck.
  2. Changing any one client_seed → different deck.
  3. Missing all client_seeds → still deterministic.
  4. Per-seat ordering is by seat_index, not submission order.
  5. Client cannot alter seed after START_HAND fires (`SEED_LOCKED`).
  6. Server seed is buffered, hidden during play, revealed at SHOWDOWN.
  7. Replay rebuilds identical state from persisted client_seeds.
"""
from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from event_log.replay import deterministic_dict, reconstruct_intent  # noqa: E402
from game_engine.deck import compute_shuffle_seed  # noqa: E402
from game_engine.reducer import ReducerError, reduce  # noqa: E402
from game_engine.rng import combine_client_seeds_by_seat  # noqa: E402
from game_engine.types import GameState, PlayerState  # noqa: E402
from game_engine.view_filter import public_view  # noqa: E402


# ---------- helpers ----------

def _make_state(n=3, target=30):
    s = GameState(table_id="t1", target_score=target, stake=100)
    s.players = [
        PlayerState(seat_index=i, user_id=f"u{i}", username=f"P{i}",
                    balance_at_start=10000)
        for i in range(n)
    ]
    return s


def _start_hand_action(*, server_seed: str = "a" * 64,
                       server_seed_hash: str = "h" * 64,
                       nonce: int = 1,
                       hand_id: str = "h_test_001",
                       client_seeds_by_seat=None) -> dict:
    a = {
        "type": "START_HAND",
        "source": "SERVER",
        "hand_id": hand_id,
        "nonce": nonce,
        "server_seed": server_seed,
        "server_seed_hash": server_seed_hash,
        "target_score": 30,
    }
    if client_seeds_by_seat is not None:
        a["client_seeds_by_seat"] = client_seeds_by_seat
    return a


# ============================================================
# 1. Same inputs → same deck
# ============================================================

def test_same_inputs_produce_identical_deck():
    s1 = _make_state()
    s2 = _make_state()
    seeds = {0: "alice-seed", 1: "bob-seed", 2: "carol-seed"}
    s1, _ = reduce(s1, _start_hand_action(client_seeds_by_seat=seeds))
    s2, _ = reduce(s2, _start_hand_action(client_seeds_by_seat=seeds))
    assert s1.deck == s2.deck
    # And the locked record is byte-identical too.
    assert s1.client_seeds_used == s2.client_seeds_used == seeds


# ============================================================
# 2. Changing one client_seed → different deck
# ============================================================

def test_changing_one_client_seed_changes_deck():
    base = {0: "alice-seed", 1: "bob-seed", 2: "carol-seed"}
    s1 = _make_state()
    s1, _ = reduce(s1, _start_hand_action(client_seeds_by_seat=base))

    flipped = dict(base)
    flipped[1] = "BOB-DIFFERENT"
    s2 = _make_state()
    s2, _ = reduce(s2, _start_hand_action(client_seeds_by_seat=flipped))

    assert s1.deck != s2.deck, "changing a client seed must change the shuffle"


# ============================================================
# 3. Missing seeds → deterministic & well-defined
# ============================================================

def test_missing_client_seeds_still_deterministic():
    """Two hands that supply no client_seeds at all must produce the
    same deck (nonce + server_seed alone determine the shuffle).
    """
    s1 = _make_state()
    s2 = _make_state()
    s1, _ = reduce(s1, _start_hand_action())  # no client_seeds_by_seat
    s2, _ = reduce(s2, _start_hand_action())
    assert s1.deck == s2.deck
    # Combining empties via the canonical helper gives the same digest.
    assert combine_client_seeds_by_seat({}, [0, 1, 2]) == \
           combine_client_seeds_by_seat({}, [0, 1, 2])


def test_partial_client_seeds_contribute():
    """A single seat contributing changes the shuffle vs. no-one
    contributing. Sibling test of #3 — confirms the canonical
    seat-prefixed scheme actually differentiates the no-contribution
    case from the one-contributor case.
    """
    s_none = _make_state()
    s_partial = _make_state()
    s_none, _ = reduce(s_none, _start_hand_action())
    s_partial, _ = reduce(
        s_partial,
        _start_hand_action(client_seeds_by_seat={1: "bob-only"}),
    )
    assert s_none.deck != s_partial.deck


# ============================================================
# 4. Ordering is by seat-index, not submission order
# ============================================================

def test_seed_ordering_is_deterministic_by_seat():
    """SUBMIT_CLIENT_SEED order does not matter — the canonical
    combiner sorts by seat_index ascending. We submit two seeds in
    different orders across two states and confirm the resulting deck
    is identical.
    """
    a_state = _make_state()
    b_state = _make_state()
    a_state, _ = reduce(a_state, {
        "type": "SUBMIT_CLIENT_SEED",
        "user_id": "u1", "payload": {"client_seed": "bob"},
    })
    a_state, _ = reduce(a_state, {
        "type": "SUBMIT_CLIENT_SEED",
        "user_id": "u0", "payload": {"client_seed": "alice"},
    })
    a_state, _ = reduce(a_state, _start_hand_action())

    b_state, _ = reduce(b_state, {
        "type": "SUBMIT_CLIENT_SEED",
        "user_id": "u0", "payload": {"client_seed": "alice"},
    })
    b_state, _ = reduce(b_state, {
        "type": "SUBMIT_CLIENT_SEED",
        "user_id": "u1", "payload": {"client_seed": "bob"},
    })
    b_state, _ = reduce(b_state, _start_hand_action())

    assert a_state.deck == b_state.deck
    assert a_state.client_seeds_used == b_state.client_seeds_used


# ============================================================
# 5. Client cannot alter seed after START_HAND fires
# ============================================================

def test_seed_locked_during_active_hand():
    """SUBMIT_CLIENT_SEED is rejected with SEED_LOCKED in any
    non-between-hands phase (ANTE / BETTING_R* / DRAW_* / SHOWDOWN).
    """
    state = _make_state()
    state, _ = reduce(state, _start_hand_action())
    # We are now mid-hand (BETTING_R1 or further).
    assert state.phase in ("BETTING_R1", "DEAL_INITIAL", "DRAW", "DRAW_1")
    with pytest.raises(ReducerError) as exc:
        reduce(state, {
            "type": "SUBMIT_CLIENT_SEED",
            "user_id": "u0", "payload": {"client_seed": "late-attempt"},
        })
    assert "SEED_LOCKED" in str(exc.value)


def test_seed_submission_allowed_between_hands():
    """Between hands (WAITING / PAYOUT / ENDED) submissions are
    accepted. Validates the white-list. We exercise PAYOUT directly
    by mutating the phase (running a full hand end-to-end is covered
    by the replay test below).
    """
    state = _make_state()
    state.phase = "PAYOUT"
    state, _ = reduce(state, {
        "type": "SUBMIT_CLIENT_SEED",
        "user_id": "u1", "payload": {"client_seed": "between-hands"},
    })
    assert state.pending_client_seeds.get(1) == "between-hands"


def test_seed_submission_validates_input():
    state = _make_state()
    # Empty seed
    with pytest.raises(ReducerError):
        reduce(state, {
            "type": "SUBMIT_CLIENT_SEED",
            "user_id": "u0", "payload": {"client_seed": ""},
        })
    # Non-string
    with pytest.raises(ReducerError):
        reduce(state, {
            "type": "SUBMIT_CLIENT_SEED",
            "user_id": "u0", "payload": {"client_seed": 1234},
        })
    # Way too long
    with pytest.raises(ReducerError):
        reduce(state, {
            "type": "SUBMIT_CLIENT_SEED",
            "user_id": "u0", "payload": {"client_seed": "x" * 257},
        })
    # Unknown user → NOT_SEATED
    with pytest.raises(ReducerError):
        reduce(state, {
            "type": "SUBMIT_CLIENT_SEED",
            "user_id": "u_nobody", "payload": {"client_seed": "valid"},
        })


# ============================================================
# 6. Server seed: hidden during play, revealed at SHOWDOWN
# ============================================================

def test_server_seed_hidden_during_play_revealed_at_showdown():
    state = _make_state()
    state, _ = reduce(state, _start_hand_action(
        server_seed="deadbeef" * 8,  # 64 hex chars
        client_seeds_by_seat={0: "alice", 1: "bob", 2: "carol"},
    ))
    # Mid-hand: public view must NOT include server_seed_buffer or a
    # revealed seed.
    pv = public_view(state, viewer_user_id="u0")
    assert "server_seed_buffer" not in pv, (
        "public_view must strip server_seed_buffer"
    )
    assert pv.get("rng_revealed_seed") is None
    # Drive the hand to PAYOUT by folding two of three players in
    # BETTING_R1, leaving a sole survivor (auto-showdown).
    for _ in range(2):
        seat = state.current_turn_seat
        assert seat is not None and state.phase == "BETTING_R1"
        uid = state.players[seat].user_id
        state, _ = reduce(state, {
            "type": "FOLD", "source": "CLIENT",
            "user_id": uid, "state_version": state.version, "payload": {},
        })
    # Should have transitioned to SHOWDOWN/PAYOUT (only u0 remains).
    assert state.phase in ("SHOWDOWN", "PAYOUT", "ENDED"), (
        f"expected showdown after sole survivor; phase={state.phase}"
    )
    # Now the plain server seed must be exposed.
    assert state.rng_revealed_seed == "deadbeef" * 8
    assert state.server_seed_buffer is None
    # And the public view must surface it (clients verify with the
    # commit hash they saw at START_HAND).
    pv = public_view(state, viewer_user_id="u0")
    assert pv["rng_revealed_seed"] == "deadbeef" * 8
    # client_seeds_used must also be in the public view for verification.
    assert pv["client_seeds_used"] == {0: "alice", 1: "bob", 2: "carol"}


# ============================================================
# 7. Replay reconstructs identical state from persisted seeds
# ============================================================

def test_replay_with_persisted_per_seat_client_seeds():
    """Simulates the writer→replay round-trip:
       1. SUBMIT_CLIENT_SEED for two seats.
       2. START_HAND with auto-collected pending seeds.
       3. Persist the START_HAND `replay_inputs` (writer behaviour).
       4. Reconstruct the intent via `replay.reconstruct_intent` and
          re-apply against an identical initial state.
       5. Final decks must match.
    """
    initial = _make_state(n=3)

    # Live path: submit + start.
    live = deepcopy(initial)
    live, _ = reduce(live, {
        "type": "SUBMIT_CLIENT_SEED", "user_id": "u0",
        "payload": {"client_seed": "alpha"},
    })
    live, _ = reduce(live, {
        "type": "SUBMIT_CLIENT_SEED", "user_id": "u2",
        "payload": {"client_seed": "gamma"},
    })
    # The lobby/dev_router would build START_HAND with no
    # client_seeds_by_seat — the reducer reads pending. The persisted
    # `replay_inputs` should record whatever was on the intent at that
    # moment. To match production, we simulate the writer extracting
    # the *committed* form (`state.client_seeds_used` after the
    # reducer ran). We do this by passing client_seeds_by_seat on the
    # replay intent so reconstruction is deterministic.
    pending = dict(live.pending_client_seeds)
    live, _ = reduce(live, _start_hand_action(
        nonce=42, hand_id="h_replay_01",
        server_seed="cafebabe" * 8,
        client_seeds_by_seat=pending,
    ))

    # Replay path: rebuild from initial + reconstructed intents for
    # both SUBMIT_CLIENT_SEED actions and the START_HAND.
    submit_doc_0 = {
        "action_type": "SUBMIT_CLIENT_SEED", "source": "CLIENT",
        "user_id": "u0", "seat_index": 0,
        "state_version_before": 0, "state_version_after": 1,
        "client_action_id": "cid0", "payload": {"client_seed": "alpha"},
        "replay_inputs": None,
    }
    submit_doc_2 = {
        "action_type": "SUBMIT_CLIENT_SEED", "source": "CLIENT",
        "user_id": "u2", "seat_index": 2,
        "state_version_before": 1, "state_version_after": 2,
        "client_action_id": "cid2", "payload": {"client_seed": "gamma"},
        "replay_inputs": None,
    }
    start_doc = {
        "action_type": "START_HAND",
        "source": "SERVER",
        "user_id": None,
        "seat_index": None,
        "state_version_before": 2,
        "state_version_after": live.version,
        "client_action_id": None,
        "payload": {},
        "replay_inputs": {
            "hand_id": "h_replay_01",
            "server_seed": "cafebabe" * 8,
            "server_seed_hash": "h" * 64,
            "client_seeds": None,
            "client_seeds_by_seat": pending,
            "nonce": 42,
        },
    }
    intent_start = reconstruct_intent(start_doc)
    assert intent_start["client_seeds_by_seat"] == pending

    replayed = deepcopy(initial)
    for d in (submit_doc_0, submit_doc_2, start_doc):
        replayed, _ = reduce(replayed, reconstruct_intent(d))
    # Decks must be byte-identical.
    assert replayed.deck == live.deck
    # And the locked map must round-trip.
    assert replayed.client_seeds_used == live.client_seeds_used
    # And the deterministic projection matches.
    assert deterministic_dict(replayed) == deterministic_dict(live)


# ============================================================
# 8. compute_shuffle_seed integration sanity
# ============================================================

def test_combine_helper_is_canonical():
    """The reducer must use the same canonical combiner that an
    external verifier would. We re-derive the seed and confirm.
    """
    seeds = {2: "carol", 0: "alice", 1: "bob"}
    state = _make_state(n=3)
    state, _ = reduce(state, _start_hand_action(
        nonce=7,
        server_seed="ff" * 32,  # 64 hex
        client_seeds_by_seat=seeds,
    ))
    # External verification: derive the deck independently.
    seat_order = [0, 1, 2]
    combined = combine_client_seeds_by_seat(seeds, seat_order)
    expected_seed = compute_shuffle_seed("ff" * 32, combined, 7)

    # The state's `rng_commit_hash` is just the hash of the server seed,
    # not the shuffle seed; so we verify by re-shuffling.
    from game_engine.deck import build_fresh_deck, shuffle
    expected_deck_objs = shuffle(build_fresh_deck(include_jokers=True), expected_seed)
    expected_deck = [c.to_dict() for c in expected_deck_objs]
    assert state.deck == expected_deck
