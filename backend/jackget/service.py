from __future__ import annotations

import random
import time
import uuid
from typing import Any, Callable, Optional

from local_demo_bootstrap import (
    LOCAL_DEMO_CREATOR_PREFIX,
    LOCAL_TABLE_BOOTSTRAP_COUNT,
    is_local_demo_creator,
    local_table_bootstrap_enabled,
)

from .models import (
    JACKGET_MAX_PLAYERS,
    JACKGET_MIN_PLAYERS,
    JACKGET_REEL_SYMBOLS,
    JACKGET_SPINS_PER_PLAYER,
    JackgetSeat,
    JackgetSpin,
    JackgetTable,
)


class JackgetError(Exception):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


def _now() -> float:
    return time.time()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def score_reels(reels: list[str]) -> int:
    """Score one Jackget 3-reel spin.

    Rules are intentionally deterministic for the local demo:
    three special symbols pay fixed jackpot-style points, three identical
    numbers pay number * 10, two matching reels pay 15, and mixed reels
    score numeric values plus 5 for each symbol.
    """
    if len(reels) != 3:
        raise JackgetError("INVALID_REEL_COUNT", "A Jackget spin must contain exactly 3 reels")
    for reel in reels:
        if reel not in JACKGET_REEL_SYMBOLS:
            raise JackgetError("INVALID_REEL_SYMBOL")
    special_triples = {
        "Seven": 100,
        "Diamond": 90,
        "Crown": 80,
        "Star": 70,
        "Bell": 60,
        "Cherry": 50,
    }
    if len(set(reels)) == 1:
        value = reels[0]
        if value in special_triples:
            return special_triples[value]
        if value.isdigit():
            return int(value) * 10
        return 40
    if any(reels.count(value) == 2 for value in set(reels)):
        return 15
    return sum(int(value) if value.isdigit() else 5 for value in reels)


class JackgetService:
    def __init__(self, *, reel_rng: Optional[Callable[[], str]] = None):
        self.tables: dict[str, JackgetTable] = {}
        self._reel_rng = reel_rng or (lambda: random.SystemRandom().choice(JACKGET_REEL_SYMBOLS))

    def list_tables(self) -> list[dict[str, Any]]:
        if local_table_bootstrap_enabled():
            self.ensure_default_local_tables()
        return [table.to_dict() for table in self.tables.values()]

    def ensure_default_local_tables(self, desired_count: int = LOCAL_TABLE_BOOTSTRAP_COUNT) -> list[JackgetTable]:
        joinable = [
            table
            for table in self.tables.values()
            if table.status in {"waiting", "ready"}
            and JACKGET_MIN_PLAYERS <= table.max_players <= JACKGET_MAX_PLAYERS
            and len(table.seats) < table.max_players
        ]
        sizes = [2, 3, 4, 2, 4]
        missing = max(0, desired_count - len(joinable))
        for index in range(missing):
            max_players = sizes[(len(joinable) + index) % len(sizes)]
            table_id = _new_id("jg_tbl")
            self.tables[table_id] = JackgetTable(
                id=table_id,
                creator_user_id=f"{LOCAL_DEMO_CREATOR_PREFIX}_jackget",
                max_players=max_players,
                created_at=_now(),
            )
        return [
            table
            for table in self.tables.values()
            if table.status in {"waiting", "ready"}
            and JACKGET_MIN_PLAYERS <= table.max_players <= JACKGET_MAX_PLAYERS
            and len(table.seats) < table.max_players
        ]

    def get_table(self, table_id: str) -> JackgetTable:
        table = self.tables.get(table_id)
        if table is None:
            raise JackgetError("TABLE_NOT_FOUND")
        return table

    def create_table(
        self,
        *,
        creator_user_id: str,
        username: str = "",
        max_players: int = JACKGET_MAX_PLAYERS,
    ) -> JackgetTable:
        if max_players < JACKGET_MIN_PLAYERS or max_players > JACKGET_MAX_PLAYERS:
            raise JackgetError("INVALID_TABLE_SIZE", "Jackget tables support 2 to 4 participants")
        table_id = _new_id("jg_tbl")
        table = JackgetTable(
            id=table_id,
            creator_user_id=creator_user_id,
            max_players=max_players,
            created_at=_now(),
        )
        table.seats.append(
            JackgetSeat(
                table_id=table_id,
                user_id=creator_user_id,
                username=username or creator_user_id,
                seat_index=0,
            )
        )
        self.tables[table_id] = table
        return table

    def join_table(self, *, table_id: str, user_id: str, username: str = "") -> JackgetTable:
        table = self.get_table(table_id)
        if table.status not in {"waiting", "ready"}:
            raise JackgetError("TABLE_NOT_JOINABLE")
        if any(seat.user_id == user_id for seat in table.seats):
            raise JackgetError("DUPLICATE_USER")
        if len(table.seats) >= table.max_players:
            raise JackgetError("TABLE_FULL")
        table.seats.append(
            JackgetSeat(
                table_id=table_id,
                user_id=user_id,
                username=username or user_id,
                seat_index=len(table.seats),
            )
        )
        if is_local_demo_creator(table.creator_user_id) and len(table.seats) == 1:
            table.creator_user_id = user_id
        self._refresh_waiting_status(table)
        return table

    def add_demo_opponents(self, *, table_id: str) -> JackgetTable:
        table = self.get_table(table_id)
        if table.status not in {"waiting", "ready"}:
            raise JackgetError("TABLE_NOT_JOINABLE")
        while len(table.seats) < table.max_players:
            idx = len(table.seats)
            table.seats.append(
                JackgetSeat(
                    table_id=table_id,
                    user_id=f"jg_demo_{table_id[-6:]}_{idx}",
                    username=f"Demo Opponent {idx}",
                    seat_index=idx,
                    is_demo=True,
                )
            )
        self._refresh_waiting_status(table)
        return table

    def start_table(self, *, table_id: str, user_id: str) -> JackgetTable:
        table = self.get_table(table_id)
        if table.creator_user_id != user_id:
            raise JackgetError("ONLY_CREATOR_CAN_START")
        if table.status not in {"waiting", "ready"}:
            raise JackgetError("TABLE_NOT_STARTABLE")
        if len(table.seats) < JACKGET_MIN_PLAYERS:
            raise JackgetError("REQUIRES_MINIMUM_2_PLAYERS")
        table.status = "in_progress"
        table.started_at = _now()
        table.current_turn_user_id = table.seats[0].user_id
        return table

    def spin(self, *, table_id: str, user_id: str, reels: Optional[list[str]] = None) -> JackgetTable:
        table = self._spin_once(table_id=table_id, user_id=user_id, reels=reels)
        self._auto_play_current_demo_turns(table)
        return table

    def _spin_once(self, *, table_id: str, user_id: str, reels: Optional[list[str]] = None) -> JackgetTable:
        table = self.get_table(table_id)
        if table.status != "in_progress":
            raise JackgetError("TABLE_NOT_ACTIVE")
        if table.current_turn_user_id != user_id:
            raise JackgetError("NOT_YOUR_TURN")
        seat = self._seat(table, user_id)
        if len(seat.spins) >= JACKGET_SPINS_PER_PLAYER:
            raise JackgetError("SPIN_LIMIT_REACHED")
        result = list(reels) if reels is not None else [self._spin_reel() for _ in range(3)]
        score = score_reels(result)
        spin = JackgetSpin(
            spin_number=len(seat.spins) + 1,
            user_id=user_id,
            reels=result,
            score=score,
        )
        seat.spins.append(spin)
        seat.total_score += score
        self._advance_turn_or_settle(table, from_user_id=user_id)
        return table

    def auto_play_demo_spins(self, *, table_id: str) -> JackgetTable:
        table = self.get_table(table_id)
        self._auto_play_current_demo_turns(table)
        return table

    def _spin_reel(self) -> str:
        value = self._reel_rng()
        if value not in JACKGET_REEL_SYMBOLS:
            raise JackgetError("INVALID_REEL_SYMBOL")
        return value

    def _seat(self, table: JackgetTable, user_id: str) -> JackgetSeat:
        seat = next((candidate for candidate in table.seats if candidate.user_id == user_id), None)
        if seat is None:
            raise JackgetError("PLAYER_NOT_SEATED")
        return seat

    def _refresh_waiting_status(self, table: JackgetTable) -> None:
        table.status = "ready" if len(table.seats) >= JACKGET_MIN_PLAYERS else "waiting"

    def _advance_turn_or_settle(self, table: JackgetTable, *, from_user_id: str) -> None:
        if all(len(seat.spins) >= JACKGET_SPINS_PER_PLAYER for seat in table.seats):
            best = max(seat.total_score for seat in table.seats)
            table.winners = [seat.user_id for seat in table.seats if seat.total_score == best]
            table.status = "settled"
            table.current_turn_user_id = None
            table.settled_at = _now()
            return

        current_index = next(
            (idx for idx, seat in enumerate(table.seats) if seat.user_id == from_user_id),
            -1,
        )
        for offset in range(1, len(table.seats) + 1):
            seat = table.seats[(current_index + offset) % len(table.seats)]
            if len(seat.spins) < JACKGET_SPINS_PER_PLAYER:
                table.current_turn_user_id = seat.user_id
                return

    def _auto_play_current_demo_turns(self, table: JackgetTable) -> None:
        guard = 0
        while table.status == "in_progress" and table.current_turn_user_id:
            guard += 1
            if guard > JACKGET_MAX_PLAYERS * JACKGET_SPINS_PER_PLAYER:
                raise JackgetError("DEMO_AUTOPLAY_GUARD")
            seat = self._seat(table, table.current_turn_user_id)
            if not seat.is_demo:
                return
            self._spin_once(table_id=table.id, user_id=seat.user_id)
