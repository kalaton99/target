"""Phase 4 — Append-only hand_actions writer.

Schema (per architecture v3.2, MongoDB-adapted):
  hand_actions doc:
    id                    : str    "ha_<uuid>" — primary key
    hand_id               : str    indexed (with seq UNIQUE per hand)
    table_id              : str
    seq                   : int    monotonic per hand_id, starts at 1
    user_id               : str | None  null for server-emitted actions
    seat_index            : int | None
    action_type           : str    e.g. "START_HAND" | "HIT" | "STAND" | "TIMEOUT_AUTOSTAND"
    payload               : dict
    events                : list[dict]   reducer-emitted events for this action
    state_version_before  : int
    state_version_after   : int
    client_action_id      : str | None
    source                : str    "CLIENT" | "SERVER"
    created_at            : str    ISO timestamp

Indexes (created via core.db.ensure_indexes):
  (hand_id, seq) UNIQUE   — guarantees per-hand monotonic seq, blocks dup writes
  (table_id, created_at desc)

This module exposes ONLY append() — there is no update or delete API.
That is the append-only contract.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pymongo import ReturnDocument


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# Action types that are server-only (defense-in-depth at the writer layer too).
SERVER_ONLY_TYPES = {
    "START_HAND",
    "AUTO_STAND_TIMEOUT",
    "TIMEOUT_AUTOSTAND",
    "AUTO_FOLD_SITOUT",
    "AUTO_CHECK_SITOUT",
    "PHASE_TRANSITION",
    "DEAL",
    "SHOWDOWN",
    "PAYOUT",
}


class HandActionWriter:
    """Append-only writer for hand_actions.

    Append-only contract:
      * No public update / delete methods.
      * `(hand_id, seq)` is UNIQUE, so duplicate inserts are DB-rejected.
      * The internal counter is atomic via Mongo `findOneAndUpdate $inc`.

    Args:
        actions_collection: motor collection for hand_actions.
        counters_collection: motor collection for the per-hand seq counter.
    """

    def __init__(self, actions_collection, counters_collection):
        self._actions = actions_collection
        self._counters = counters_collection

    async def _next_seq(self, hand_id: str) -> int:
        doc = await self._counters.find_one_and_update(
            {"_id": hand_id},
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return int(doc["seq"])

    async def append(
        self,
        *,
        hand_id: str,
        table_id: str,
        intent: Dict[str, Any],
        events: List[Dict[str, Any]],
        state_version_before: int,
        state_version_after: int,
    ) -> Dict[str, Any]:
        """Atomically append one action to the per-hand event log.

        Returns the inserted document (without Mongo `_id`).
        """
        if state_version_after != state_version_before + 1:
            # Phase 4 invariant: every mutation increments state_version by exactly 1.
            raise ValueError(
                f"STATE_VERSION_INCREMENT_INVALID: before={state_version_before} "
                f"after={state_version_after}"
            )

        seq = await self._next_seq(hand_id)
        action_type = intent.get("type")
        if not isinstance(action_type, str) or not action_type:
            raise ValueError("MISSING_ACTION_TYPE")

        # Normalize stored action_type for AUTO_STAND_TIMEOUT (per architecture
        # taxonomy in v3.2 §6.5: stored as TIMEOUT_AUTOSTAND).
        stored_type = "TIMEOUT_AUTOSTAND" if action_type == "AUTO_STAND_TIMEOUT" else action_type

        doc = {
            "id": f"ha_{uuid.uuid4().hex[:20]}",
            "hand_id": hand_id,
            "table_id": table_id,
            "seq": seq,
            "user_id": intent.get("user_id"),
            "seat_index": intent.get("seat_index"),
            "action_type": stored_type,
            "payload": dict(intent.get("payload", {})),
            "events": list(events or []),
            "state_version_before": int(state_version_before),
            "state_version_after": int(state_version_after),
            "client_action_id": intent.get("client_action_id"),
            "source": intent.get("source", "CLIENT"),
            "created_at": _now_iso(),
            # Stash the canonical inputs needed to deterministically replay
            # START_HAND (seeds, nonce). For other types these are absent.
            "replay_inputs": _extract_replay_inputs(intent),
        }
        await self._actions.insert_one(doc)
        doc.pop("_id", None)
        return doc

    async def list_for_hand(self, hand_id: str) -> List[Dict[str, Any]]:
        """Read-only fetch — append-only contract is preserved."""
        cursor = self._actions.find({"hand_id": hand_id}, {"_id": 0}).sort("seq", 1)
        return [d async for d in cursor]


def _extract_replay_inputs(intent: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Capture only the deterministic seed-related inputs for replay.

    2026-05 v2 — also records `client_seeds_by_seat` so per-seat
    contributions are reproducible. Both legacy string and v2 dict
    forms are persisted side-by-side; the reducer accepts whichever
    is present.
    """
    if intent.get("type") != "START_HAND":
        return None
    return {
        "hand_id": intent.get("hand_id"),
        "server_seed": intent.get("server_seed"),
        "server_seed_hash": intent.get("server_seed_hash"),
        "client_seeds": intent.get("client_seeds"),
        "client_seeds_by_seat": intent.get("client_seeds_by_seat"),
        "nonce": intent.get("nonce"),
    }
