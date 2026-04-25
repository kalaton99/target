"""Per-table worker: serial intent queue + reducer + persistence + broadcast.

Single asyncio task per active table. Owns the in-process state.
Persists to MongoDB on every action (hand_actions = source of truth).
"""
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core import db
from core.constants import TURN_TIMEOUT_MS, TIMEOUT_GRACE_MS, MIN_PLAYERS
from core.config import ENGINE_VERSION
from game_engine import reducer as reducer_mod
from game_engine.rng import generate_server_seed, combine_client_seeds
from game_engine.types import GameState, PlayerState, state_from_dict
from game_engine.view_filter import public_view
from .connection_manager import manager
from wallet import service as wallet_service

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TableWorker:
    def __init__(self, table_id: str):
        self.table_id = table_id
        self.queue: asyncio.Queue = asyncio.Queue()
        self.state: Optional[GameState] = None
        self.seq: int = 0
        self._timeout_task: Optional[asyncio.Task] = None
        self._task: Optional[asyncio.Task] = None
        self._stop = False

    async def start(self) -> None:
        # Hydrate state from DB
        await self._hydrate()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop = True
        if self._timeout_task:
            self._timeout_task.cancel()
        if self._task:
            self._task.cancel()

    async def enqueue(self, intent: Dict[str, Any]) -> None:
        await self.queue.put(intent)

    # ---- internal ----
    async def _hydrate(self) -> None:
        table = await db.tables.find_one({"id": self.table_id}, {"_id": 0})
        if not table:
            raise RuntimeError("TABLE_NOT_FOUND")
        # Build players from currently-seated users
        players: List[PlayerState] = []
        for s in table["seats"]:
            if s["user_id"]:
                user = await db.users.find_one({"id": s["user_id"]}, {"_id": 0, "password_hash": 0})
                wallet = await wallet_service.get_wallet(s["user_id"]) or {"balance": 0}
                players.append(
                    PlayerState(
                        seat_index=s["seat_index"],
                        user_id=s["user_id"],
                        username=user["username"] if user else "?",
                        balance_at_start=wallet["balance"],
                    )
                )
        self.state = GameState(
            table_id=self.table_id,
            engine_version=ENGINE_VERSION,
            phase="WAITING",
            version=0,
            players=players,
            stake=table["stake"],
            max_players=table["max_players"],
            target_score=table["target_score"],
            table_type=table["type"],
        )

    async def _run(self) -> None:
        # Initial broadcast
        await self._broadcast_state(events=[{"type": "STATE_INIT"}])
        # Maybe auto-start
        await self._maybe_start_hand()

        while not self._stop:
            try:
                intent = await self.queue.get()
            except asyncio.CancelledError:
                return
            try:
                await self._process(intent)
            except Exception as e:
                logger.exception("worker error: %s", e)

    async def _process(self, intent: Dict[str, Any]) -> None:
        if self.state is None:
            return
        # state_version check (client-only)
        if intent.get("source") != "SERVER":
            incoming_v = intent.get("state_version")
            if incoming_v is None:
                await self._send_reject(intent, "MISSING_STATE_VERSION")
                return
            if incoming_v != self.state.version:
                await self._send_reject(
                    intent, "OUT_OF_SYNC",
                    extra={
                        "expected_state_version": self.state.version,
                        "received_state_version": incoming_v,
                    },
                )
                return

        # Special workflow intents
        a_type = intent.get("type")
        if a_type == "PLAYER_JOIN":
            await self._on_player_join(intent)
            return
        if a_type == "PLAYER_LEAVE":
            await self._on_player_leave(intent)
            return

        # Pre-action wallet debit for CALL / RAISE (single-doc atomic)
        if a_type in ("CALL", "RAISE"):
            user_id = intent["user_id"]
            seat = next((p.seat_index for p in self.state.players if p.user_id == user_id), None)
            if seat is None:
                await self._send_reject(intent, "NOT_AT_TABLE")
                return
            p = self.state.players[seat]
            owed = 0
            if a_type == "CALL":
                owed = self.state.current_bet - p.current_bet
            else:
                owed = int(intent.get("payload", {}).get("amount", 0))
            if owed <= 0:
                await self._send_reject(intent, "INVALID_AMOUNT")
                return
            try:
                await wallet_service.mutate(
                    user_id=user_id,
                    delta=-owed,
                    reason=a_type,
                    ref_type="HAND",
                    ref_id=self.state.hand_id,
                    idempotency_key=intent.get("client_action_id"),
                    counter_account="POT",
                )
            except wallet_service.InsufficientFunds:
                await self._send_reject(intent, "INSUFFICIENT_FUNDS")
                return
            except wallet_service.DuplicateAction:
                # already processed - skip
                return
            except wallet_service.WalletError as e:
                await self._send_reject(intent, str(e))
                return

        # Reduce
        try:
            new_state, events = reducer_mod.reduce(self.state, intent)
        except reducer_mod.ReducerError as e:
            await self._send_reject(intent, str(e))
            return

        # Persist hand_action
        if self.state.hand_id:
            self.seq += 1
            stored_action_type = "TIMEOUT_AUTOSTAND" if a_type == "AUTO_STAND_TIMEOUT" else a_type
            await db.hand_actions.insert_one({
                "id": f"ha_{uuid.uuid4().hex[:20]}",
                "hand_id": new_state.hand_id,
                "seq": self.seq,
                "table_id": self.table_id,
                "user_id": intent.get("user_id"),
                "seat_index": intent.get("seat_index"),
                "action_type": stored_action_type,
                "payload": intent.get("payload", {}),
                "state_version_before": self.state.version,
                "state_version_after": new_state.version,
                "client_action_id": intent.get("client_action_id"),
                "created_at": _now_iso(),
            })

        self.state = new_state
        await self._broadcast_state(events)

        # Cancel any prior timeout task
        if self._timeout_task:
            self._timeout_task.cancel()
            self._timeout_task = None

        # Schedule new turn timeout if applicable
        if self.state.current_turn_seat is not None and self.state.phase == "DRAW":
            self._timeout_task = asyncio.create_task(self._schedule_timeout(self.state.version, self.state.current_turn_seat))

        # If in PAYOUT, settle and start next hand prep
        if self.state.phase == "PAYOUT":
            await self._settle_payout()
            self.state.phase = "ENDED"
            self.state.version += 1
            await self._broadcast_state([{"type": "PHASE", "phase": "ENDED"}])
            # Auto-restart after small delay
            await asyncio.sleep(3)
            await self._maybe_start_hand()

    async def _on_player_join(self, intent: Dict[str, Any]) -> None:
        user_id = intent["user_id"]
        seat_index = intent["seat_index"]
        # Avoid duplicate
        if any(p.user_id == user_id for p in self.state.players):
            return
        user = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
        wallet = await wallet_service.get_wallet(user_id) or {"balance": 0}
        self.state.players.append(
            PlayerState(
                seat_index=seat_index,
                user_id=user_id,
                username=user["username"] if user else "?",
                balance_at_start=wallet["balance"],
            )
        )
        # sort by seat_index
        self.state.players.sort(key=lambda p: p.seat_index)
        self.state.version += 1
        await self._broadcast_state([{"type": "PLAYER_JOINED", "user_id": user_id, "seat": seat_index}])
        await self._maybe_start_hand()

    async def _on_player_leave(self, intent: Dict[str, Any]) -> None:
        user_id = intent["user_id"]
        self.state.players = [p for p in self.state.players if p.user_id != user_id]
        self.state.version += 1
        await self._broadcast_state([{"type": "PLAYER_LEFT", "user_id": user_id}])

    async def _maybe_start_hand(self) -> None:
        if self.state.phase not in ("WAITING", "ENDED"):
            return
        if len(self.state.players) < MIN_PLAYERS:
            self.state.phase = "WAITING"
            self.state.version += 1
            await self._broadcast_state([{"type": "WAITING_FOR_PLAYERS"}])
            return
        # Verify each player has enough balance for ante
        for p in self.state.players:
            wallet = await wallet_service.get_wallet(p.user_id) or {"balance": 0}
            p.balance_at_start = wallet["balance"]
        # Debit antes
        hand_id = f"h_{uuid.uuid4().hex[:20]}"
        for p in self.state.players:
            try:
                await wallet_service.mutate(
                    user_id=p.user_id,
                    delta=-self.state.stake,
                    reason="ANTE",
                    ref_type="HAND",
                    ref_id=hand_id,
                    idempotency_key=f"ante:{hand_id}:{p.user_id}",
                    counter_account="POT",
                )
            except Exception as e:
                logger.warning("ante failed for %s: %s", p.user_id, e)
                p.sitting_out = True
        # Generate provably-fair seed
        seed_plain, seed_hash = generate_server_seed()
        nonce = self.state.hand_number + 1
        # Persist hand
        await db.hands.insert_one({
            "id": hand_id,
            "table_id": self.table_id,
            "hand_number": nonce,
            "engine_version": ENGINE_VERSION,
            "pot": 0,
            "commission": 0,
            "lottery_contribution": 0,
            "status": "ACTIVE",
            "started_at": _now_iso(),
            "ended_at": None,
        })
        await db.rng_seeds.insert_one({
            "id": f"rng_{uuid.uuid4().hex[:20]}",
            "hand_id": hand_id,
            "server_seed_hash": seed_hash,
            "server_seed_plain": None,
            "client_seeds_json": {},
            "nonce": nonce,
            "shuffle_algo": "FISHER_YATES_SHA256_V1",
            "status": "COMMITTED",
            "committed_at": _now_iso(),
            "revealed_at": None,
        })
        # Reset seq
        self.seq = 0
        # Run START_HAND through reducer
        client_seeds = combine_client_seeds([])
        await self._process({
            "type": "START_HAND",
            "source": "SERVER",
            "hand_id": hand_id,
            "server_seed": seed_plain,
            "server_seed_hash": seed_hash,
            "client_seeds": client_seeds,
            "nonce": nonce,
        })
        # Reveal stub - in MVP we reveal at showdown
        self._pending_seed_reveal = (hand_id, seed_plain)

    async def _settle_payout(self) -> None:
        # Credit winners
        for p in self.state.players:
            if p.payout > 0:
                try:
                    await wallet_service.mutate(
                        user_id=p.user_id,
                        delta=p.payout,
                        reason="PAYOUT",
                        ref_type="HAND",
                        ref_id=self.state.hand_id,
                        idempotency_key=f"payout:{self.state.hand_id}:{p.user_id}",
                        counter_account="POT",
                    )
                except Exception as e:
                    logger.exception("payout error: %s", e)
        # Update hand record
        if self.state.hand_id:
            await db.hands.update_one(
                {"id": self.state.hand_id},
                {"$set": {
                    "pot": self.state.pot,
                    "status": "SETTLED",
                    "ended_at": _now_iso(),
                }},
            )
            # Reveal seed
            seed_info = getattr(self, "_pending_seed_reveal", None)
            if seed_info:
                hid, plain = seed_info
                await db.rng_seeds.update_one(
                    {"hand_id": hid},
                    {"$set": {
                        "server_seed_plain": plain,
                        "status": "REVEALED",
                        "revealed_at": _now_iso(),
                    }},
                )

    async def _schedule_timeout(self, expected_version: int, expected_seat: int) -> None:
        try:
            await asyncio.sleep((TURN_TIMEOUT_MS + TIMEOUT_GRACE_MS) / 1000.0)
        except asyncio.CancelledError:
            return
        if not self.state:
            return
        # Recheck preconditions
        if self.state.version != expected_version:
            return
        if self.state.current_turn_seat != expected_seat:
            return
        if self.state.phase != "DRAW":
            return
        seat_player = self.state.players[expected_seat]
        # Enqueue AUTO_STAND_TIMEOUT
        await self.queue.put({
            "type": "AUTO_STAND_TIMEOUT",
            "source": "SERVER",
            "user_id": seat_player.user_id,
            "seat_index": expected_seat,
            "state_version": self.state.version,
            "payload": {"reason": "TURN_TIMEOUT_15S", "source": "SERVER"},
        })

    async def _broadcast_state(self, events: List[Dict[str, Any]]) -> None:
        if self.state is None:
            return
        state = self.state

        def factory(uid: str) -> Dict[str, Any]:
            return {
                "type": "STATE_UPDATE",
                "view": public_view(state, uid),
                "events": events,
                "state_version": state.version,
            }
        await manager.broadcast(self.table_id, factory)

    async def _send_reject(self, intent: Dict[str, Any], error: str, extra: Dict[str, Any] | None = None) -> None:
        if self.state is None:
            return
        user_id = intent.get("user_id")
        if not user_id:
            return
        payload = {
            "type": "ACTION_REJECTED",
            "client_action_id": intent.get("client_action_id"),
            "error": error,
            "fresh_state": public_view(self.state, user_id),
            "state_version": self.state.version,
        }
        if extra:
            payload.update(extra)
        await manager.send_to_user(self.table_id, user_id, payload)


# Worker registry
_workers: Dict[str, TableWorker] = {}
_lock = asyncio.Lock()


async def get_or_spawn(table_id: str) -> TableWorker:
    async with _lock:
        w = _workers.get(table_id)
        if w is None:
            w = TableWorker(table_id)
            _workers[table_id] = w
            await w.start()
        return w


async def stop_all() -> None:
    for w in list(_workers.values()):
        await w.stop()
    _workers.clear()
