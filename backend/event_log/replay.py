"""Phase 4 — Deterministic replay.

Given an initial GameState (the state immediately BEFORE the first
action of the hand) and the persisted append-only hand_actions log, this
module reconstructs the final GameState by re-applying each action through
the pure reducer in seq order.

Replay is deterministic for the event-sourced parts of state:
    phase, version, players, pot, current_turn_seat, deck, hand_id,
    hand_number, rng_*, winners, last_action_summary.

Two state fields are runtime-engine-derived (not part of event-sourced
truth) and are therefore normalized before comparison:
    turn_started_at_ms, turn_deadline_ms

These are wall-clock-dependent UI hints set by the TurnEngine when arming
the timer; they are intentionally not part of the deterministic state.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List

from game_engine.reducer import reduce as pure_reduce
from game_engine.types import GameState, state_from_dict


def reconstruct_intent(action_doc: Dict[str, Any]) -> Dict[str, Any]:
    """Rebuild the reducer-input intent from a persisted hand_actions doc.

    Notes:
      * For START_HAND we restore server_seed/client_seeds/nonce/hand_id from
        replay_inputs so the deterministic shuffle reproduces.
      * `action_type` stored as TIMEOUT_AUTOSTAND is mapped back to
        AUTO_STAND_TIMEOUT for the reducer.
    """
    a_type = action_doc["action_type"]
    if a_type == "TIMEOUT_AUTOSTAND":
        a_type = "AUTO_STAND_TIMEOUT"

    intent: Dict[str, Any] = {
        "type": a_type,
        "source": action_doc.get("source", "CLIENT"),
        "user_id": action_doc.get("user_id"),
        "seat_index": action_doc.get("seat_index"),
        "state_version": action_doc.get("state_version_before"),
        "client_action_id": action_doc.get("client_action_id"),
        "payload": dict(action_doc.get("payload", {})),
    }

    replay_inputs = action_doc.get("replay_inputs") or {}
    # Lift START_HAND seeds back into the intent (reducer expects them
    # at the top level, not nested in payload).
    for key in ("hand_id", "server_seed", "server_seed_hash", "client_seeds", "nonce"):
        if key in replay_inputs and replay_inputs[key] is not None:
            intent[key] = replay_inputs[key]
    return intent


def replay(initial_state: GameState, action_docs: List[Dict[str, Any]]) -> GameState:
    """Apply every persisted action against the initial state in seq order.

    Asserts strict monotonic seq starting at 1.
    """
    state = deepcopy(initial_state)
    expected_seq = 1
    for doc in action_docs:
        seq = int(doc["seq"])
        if seq != expected_seq:
            raise ValueError(
                f"NON_MONOTONIC_SEQ: expected {expected_seq}, got {seq} "
                f"(action_id={doc.get('id')}, action_type={doc.get('action_type')})"
            )
        expected_seq += 1

        if state.version != int(doc["state_version_before"]):
            raise ValueError(
                f"REPLAY_STATE_VERSION_MISMATCH at seq={seq}: "
                f"current={state.version} expected_before={doc['state_version_before']}"
            )

        intent = reconstruct_intent(doc)
        state, _events = pure_reduce(state, intent)

        if state.version != int(doc["state_version_after"]):
            raise ValueError(
                f"REPLAY_STATE_VERSION_AFTER_MISMATCH at seq={seq}: "
                f"got={state.version} expected_after={doc['state_version_after']}"
            )
    return state


def deterministic_dict(state: GameState) -> Dict[str, Any]:
    """Return a dict view of state with non-deterministic engine fields stripped.

    Use this for replay equivalence comparison.
    """
    d = state.to_dict()
    d.pop("turn_started_at_ms", None)
    d.pop("turn_deadline_ms", None)
    return d
