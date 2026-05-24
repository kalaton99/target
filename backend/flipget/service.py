from __future__ import annotations

import random
import time
import uuid
from typing import Any, Callable, Optional

from ledger.service import LedgerService

from local_demo_bootstrap import (
    LOCAL_DEMO_CREATOR_PREFIX,
    LOCAL_TABLE_BOOTSTRAP_COUNT,
    is_local_demo_creator,
    local_table_bootstrap_enabled,
)

from .models import FLIPGET_MODES, FLIPGET_SEATS, SIDES, FlipgetRound, FlipgetSeat, FlipgetTable, Side
from .wallet_bridge import FlipgetPayoutParticipant, settle_flipget_payout


class FlipgetError(Exception):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


def _now() -> float:
    return time.time()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class FlipgetService:
    def __init__(self, *, coin_rng: Optional[Callable[[], str]] = None):
        self.tables: dict[str, FlipgetTable] = {}
        self._coin_rng = coin_rng or (lambda: random.SystemRandom().choice(["heads", "tails"]))

    def list_tables(self) -> list[dict[str, Any]]:
        if local_table_bootstrap_enabled():
            self.ensure_default_local_tables()
        return [table.to_dict() for table in self.tables.values()]

    def ensure_default_local_tables(self, desired_count: int = LOCAL_TABLE_BOOTSTRAP_COUNT) -> list[FlipgetTable]:
        joinable = [
            table
            for table in self.tables.values()
            if table.status in {"waiting", "ready"}
            and table.mode in FLIPGET_MODES
            and len(table.seats) < FLIPGET_SEATS
        ]
        modes = ["single_flip", "best_of_3", "best_of_5", "single_flip", "best_of_3"]
        missing = max(0, desired_count - len(joinable))
        for index in range(missing):
            mode = modes[(len(joinable) + index) % len(modes)]
            table_id = _new_id("fg_tbl")
            opening_round = FlipgetRound(
                id=_new_id("fg_round"),
                table_id=table_id,
                round_number=1,
                created_at=_now(),
            )
            self.tables[table_id] = FlipgetTable(
                id=table_id,
                creator_user_id=f"{LOCAL_DEMO_CREATOR_PREFIX}_flipget",
                stake_amount=100,
                mode=mode,  # type: ignore[arg-type]
                created_at=_now(),
                round=opening_round,
                rounds=[opening_round],
            )
        return [
            table
            for table in self.tables.values()
            if table.status in {"waiting", "ready"}
            and table.mode in FLIPGET_MODES
            and len(table.seats) < FLIPGET_SEATS
        ]

    def get_table(self, table_id: str) -> FlipgetTable:
        table = self.tables.get(table_id)
        if table is None:
            raise FlipgetError("TABLE_NOT_FOUND")
        return table

    def create_table(
        self,
        *,
        creator_user_id: str,
        username: str = "",
        stake_amount: int = 100,
        max_players: int = FLIPGET_SEATS,
        mode: str = "single_flip",
    ) -> FlipgetTable:
        if max_players != FLIPGET_SEATS:
            raise FlipgetError("INVALID_TABLE_SIZE", "Flipget tables must have exactly 2 seats")
        if stake_amount < 0 or stake_amount > 1_000_000:
            raise FlipgetError("INVALID_STAKE")
        if mode not in FLIPGET_MODES:
            raise FlipgetError("INVALID_MODE")
        table_id = _new_id("fg_tbl")
        opening_round = FlipgetRound(
            id=_new_id("fg_round"),
            table_id=table_id,
            round_number=1,
            created_at=_now(),
        )
        table = FlipgetTable(
            id=table_id,
            creator_user_id=creator_user_id,
            stake_amount=stake_amount,
            mode=mode,  # type: ignore[assignment]
            created_at=_now(),
            round=opening_round,
            rounds=[opening_round],
        )
        table.seats.append(
            FlipgetSeat(
                table_id=table_id,
                user_id=creator_user_id,
                username=username or creator_user_id,
                seat_index=0,
                joined_at=_now(),
            )
        )
        self.tables[table_id] = table
        return table

    def join_table(self, *, table_id: str, user_id: str, username: str = "") -> FlipgetTable:
        table = self.get_table(table_id)
        if table.status not in {"waiting", "ready"}:
            raise FlipgetError("TABLE_NOT_JOINABLE")
        if any(seat.user_id == user_id for seat in table.seats):
            raise FlipgetError("DUPLICATE_USER")
        if len(table.seats) >= FLIPGET_SEATS:
            raise FlipgetError("TABLE_FULL")
        table.seats.append(
            FlipgetSeat(
                table_id=table_id,
                user_id=user_id,
                username=username or user_id,
                seat_index=1,
                joined_at=_now(),
            )
        )
        if is_local_demo_creator(table.creator_user_id) and len(table.seats) == 1:
            table.creator_user_id = user_id
        table.status = self._status_before_flip(table)
        return table

    def choose_side(self, *, table_id: str, user_id: str, side: str) -> FlipgetTable:
        table = self.get_table(table_id)
        if table.status in {"flipping", "settled"}:
            raise FlipgetError("TABLE_ALREADY_STARTED")
        if side not in SIDES:
            raise FlipgetError("INVALID_SIDE")
        seat = self._seat(table, user_id)
        if seat.ready:
            raise FlipgetError("SIDE_LOCKED")
        if any(other.user_id != user_id and other.side == side for other in table.seats):
            raise FlipgetError("SIDE_ALREADY_TAKEN")
        seat.side = side  # type: ignore[assignment]
        table.status = self._status_before_flip(table)
        return table

    def ready(self, *, table_id: str, user_id: str) -> FlipgetTable:
        table = self.get_table(table_id)
        if table.status in {"flipping", "settled"}:
            raise FlipgetError("TABLE_ALREADY_STARTED")
        seat = self._seat(table, user_id)
        if seat.side is None:
            raise FlipgetError("SIDE_REQUIRED")
        seat.ready = True
        table.status = self._status_before_flip(table)
        return table

    async def flip(self, *, table_id: str, user_id: str, ledger: Optional[LedgerService] = None) -> FlipgetTable:
        table = self.get_table(table_id)
        if table.status == "settled":
            raise FlipgetError("TABLE_ALREADY_SETTLED")
        if table.status == "flipping":
            return await self.settle(table_id, ledger)
        self._validate_flip_ready(table)
        if user_id not in {seat.user_id for seat in table.seats}:
            raise FlipgetError("PLAYER_NOT_SEATED")
        assert table.round is not None
        table.status = "flipping"
        table.started_at = table.started_at or _now()
        table.round.status = "flipping"
        result = self._flip_coin()
        table.round.result = result  # type: ignore[assignment]
        table.round.side_by_user = {
            seat.user_id: seat.side
            for seat in table.seats
            if seat.side in SIDES
        }
        winner = next(seat for seat in table.seats if seat.side == result)
        loser = next(seat for seat in table.seats if seat.side != result)
        table.round.winner_user_id = winner.user_id
        table.round.loser_user_id = loser.user_id
        table.score[result] = table.score.get(result, 0) + 1
        now = _now()
        table.round.status = "settled"
        table.round.settled_at = table.round.settled_at or now
        config = self._mode_config(table)
        if table.score[result] >= config["wins_required"]:
            table.winning_side = result  # type: ignore[assignment]
            return await self.settle(table_id, ledger)
        next_round = FlipgetRound(
            id=_new_id("fg_round"),
            table_id=table.id,
            round_number=len(table.rounds) + 1,
            created_at=_now(),
        )
        table.round = next_round
        table.rounds.append(next_round)
        for seat in table.seats:
            seat.side = None
            seat.ready = False
        table.status = "waiting"
        return table

    async def settle(self, table_id: str, ledger: Optional[LedgerService] = None) -> FlipgetTable:
        table = self.get_table(table_id)
        if table.status == "settled":
            return table
        if table.status != "flipping" or table.round is None or table.round.result not in SIDES:
            raise FlipgetError("TABLE_NOT_SETTLEABLE")
        config = self._mode_config(table)
        if table.winning_side not in SIDES or table.score.get(table.winning_side, 0) < config["wins_required"]:
            raise FlipgetError("TABLE_NOT_SETTLEABLE")
        if ledger is not None:
            table.settlement_results = await settle_flipget_payout(
                ledger,
                table_id=table.id,
                round_id=table.round.id,
                participants=self._payout_participants(table),
            )
        now = _now()
        table.status = "settled"
        table.settled_at = table.settled_at or now
        table.round.status = "settled"
        table.round.settled_at = table.round.settled_at or now
        return table

    def leave_table(self, *, table_id: str, user_id: str) -> FlipgetTable | dict[str, Any]:
        table = self.get_table(table_id)
        if table.status in {"flipping", "settled"}:
            raise FlipgetError("TABLE_ALREADY_STARTED")
        table.seats = [seat for seat in table.seats if seat.user_id != user_id]
        for index, seat in enumerate(table.seats):
            seat.seat_index = index
        if not table.seats:
            table.status = "cancelled"
            self.tables.pop(table_id, None)
            return {"deleted": True, "table_id": table_id}
        for seat in table.seats:
            seat.ready = False
        table.status = "waiting"
        return table

    def deal_again(self, *, table_id: str, user_id: str) -> FlipgetTable:
        prior = self.get_table(table_id)
        if prior.status != "settled":
            raise FlipgetError("TABLE_NOT_SETTLED")
        return self.create_table(
            creator_user_id=user_id,
            username=user_id,
            stake_amount=prior.stake_amount,
            max_players=FLIPGET_SEATS,
            mode=prior.mode,
        )

    def _seat(self, table: FlipgetTable, user_id: str) -> FlipgetSeat:
        seat = next((candidate for candidate in table.seats if candidate.user_id == user_id), None)
        if seat is None:
            raise FlipgetError("PLAYER_NOT_SEATED")
        return seat

    def _status_before_flip(self, table: FlipgetTable) -> str:
        if (
            len(table.seats) == FLIPGET_SEATS
            and all(seat.side in SIDES for seat in table.seats)
            and len({seat.side for seat in table.seats}) == FLIPGET_SEATS
            and all(seat.ready for seat in table.seats)
        ):
            return "ready"
        return "waiting"

    def _validate_flip_ready(self, table: FlipgetTable) -> None:
        if len(table.seats) != FLIPGET_SEATS:
            raise FlipgetError("REQUIRES_EXACTLY_2_SEATS")
        if any(seat.side not in SIDES for seat in table.seats):
            raise FlipgetError("SIDE_REQUIRED")
        if len({seat.side for seat in table.seats}) != FLIPGET_SEATS:
            raise FlipgetError("SIDES_MUST_BE_UNIQUE")
        if not all(seat.ready for seat in table.seats):
            raise FlipgetError("PLAYERS_NOT_READY")

    def _flip_coin(self) -> str:
        result = self._coin_rng()
        if result not in SIDES:
            raise FlipgetError("INVALID_RNG_RESULT")
        return result

    def _mode_config(self, table: FlipgetTable) -> dict[str, int | str]:
        return FLIPGET_MODES[table.mode]

    def _payout_participants(self, table: FlipgetTable) -> list[FlipgetPayoutParticipant]:
        assert table.round is not None
        winner_id = next(seat.user_id for seat in table.seats if seat.side == table.winning_side)
        pot = len(table.seats) * table.stake_amount
        return [
            FlipgetPayoutParticipant(
                user_id=seat.user_id,
                locked_stake=table.stake_amount,
                payout=pot if seat.user_id == winner_id else 0,
            )
            for seat in table.seats
        ]
