from __future__ import annotations

import random
import time
import uuid
from typing import Any, Callable, Optional

from ledger.service import LedgerService

from .bots import should_bot_hold
from .models import (
    DICEGET_SEATS,
    MAX_BOTS,
    SUPPORTED_SCORE_GOALS,
    BotProfile,
    DicegetRoll,
    DicegetSeat,
    DicegetTable,
)
from .wallet_bridge import DicegetPayoutParticipant, settle_diceget_payout


class DicegetError(Exception):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


def _now() -> float:
    return time.time()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class DicegetService:
    def __init__(self, *, dice_rng: Optional[Callable[[], int]] = None):
        self.tables: dict[str, DicegetTable] = {}
        self._dice_rng = dice_rng or (lambda: random.SystemRandom().randint(1, 6))

    def list_tables(self) -> list[dict[str, Any]]:
        return [table.to_dict() for table in self.tables.values()]

    def get_table(self, table_id: str) -> DicegetTable:
        table = self.tables.get(table_id)
        if table is None:
            raise DicegetError("TABLE_NOT_FOUND")
        return table

    def create_table(
        self,
        *,
        creator_user_id: str,
        username: str = "",
        target_score: int | None = None,
        score_goal: int | None = None,
        stake: int = 100,
        max_players: int = DICEGET_SEATS,
    ) -> DicegetTable:
        target_score = self._normalize_score_goal(target_score=target_score, score_goal=score_goal)
        if max_players != DICEGET_SEATS:
            raise DicegetError("INVALID_TABLE_SIZE", "Diceget tables must have exactly 4 seats")
        if stake < 0 or stake > 1_000_000:
            raise DicegetError("INVALID_STAKE")
        table_id = _new_id("dg_tbl")
        table = DicegetTable(
            id=table_id,
            target_score=target_score,
            stake=stake,
            creator_user_id=creator_user_id,
            created_at=_now(),
            round_id=_new_id("dg_round"),
        )
        table.seats.append(
            DicegetSeat(
                table_id=table_id,
                user_id=creator_user_id,
                username=username or creator_user_id,
                seat_index=0,
            )
        )
        self.tables[table_id] = table
        return table

    def join_table(self, *, table_id: str, user_id: str, username: str = "") -> DicegetTable:
        table = self.get_table(table_id)
        if table.status != "waiting":
            raise DicegetError("TABLE_NOT_JOINABLE")
        if any(seat.user_id == user_id for seat in table.seats):
            return table
        if len(table.seats) >= DICEGET_SEATS:
            raise DicegetError("TABLE_FULL")
        table.seats.append(
            DicegetSeat(
                table_id=table_id,
                user_id=user_id,
                username=username or user_id,
                seat_index=len(table.seats),
            )
        )
        return table

    def add_bot(
        self,
        *,
        table_id: str,
        profile: BotProfile = "normal",
    ) -> DicegetTable:
        table = self.get_table(table_id)
        if table.status != "waiting":
            raise DicegetError("TABLE_NOT_JOINABLE")
        bot_count = sum(1 for seat in table.seats if seat.is_bot)
        if bot_count >= MAX_BOTS:
            raise DicegetError("MAX_BOTS_EXCEEDED")
        if len(table.seats) >= DICEGET_SEATS:
            raise DicegetError("TABLE_FULL")
        if profile not in {"safe", "normal", "aggressive"}:
            raise DicegetError("INVALID_BOT_PROFILE")
        bot_id = f"dg_bot_{uuid.uuid4().hex[:8]}"
        table.seats.append(
            DicegetSeat(
                table_id=table_id,
                user_id=bot_id,
                username=f"Bot {profile}",
                seat_index=len(table.seats),
                is_bot=True,
                bot_profile=profile,
            )
        )
        return table

    def leave_table(self, *, table_id: str, user_id: str) -> DicegetTable | dict[str, Any]:
        table = self.get_table(table_id)
        if table.status != "waiting":
            raise DicegetError("TABLE_ALREADY_STARTED")
        table.seats = [seat for seat in table.seats if seat.user_id != user_id]
        for index, seat in enumerate(table.seats):
            seat.seat_index = index
        if not table.seats:
            table.status = "cancelled"
            self.tables.pop(table_id, None)
            return {"deleted": True, "table_id": table_id}
        return table

    def start_table(self, *, table_id: str, user_id: str) -> DicegetTable:
        table = self.get_table(table_id)
        if table.creator_user_id != user_id:
            raise DicegetError("ONLY_CREATOR_CAN_START")
        if table.status != "waiting":
            raise DicegetError("TABLE_NOT_STARTABLE")
        if len(table.seats) != DICEGET_SEATS:
            raise DicegetError("REQUIRES_EXACTLY_4_SEATS")
        table.status = "active"
        table.started_at = _now()
        for seat in table.seats:
            seat.status = "active"
        table.turn_index = 0
        table.current_turn_user_id = table.seats[0].user_id
        self._run_bots(table)
        return table

    def roll(self, *, table_id: str, user_id: str) -> DicegetTable:
        table = self.get_table(table_id)
        seat = self._require_actionable_turn(table, user_id)
        dice_1 = self._roll_die()
        dice_2 = self._roll_die()
        before = seat.score
        after = before + dice_1 + dice_2
        is_bust = after > table.target_score
        seat.score = after
        if is_bust:
            seat.status = "busted"
            seat.locked_score = None
        table.rolls.append(
            DicegetRoll(
                round_id=table.round_id,
                user_id=user_id,
                dice_1=dice_1,
                dice_2=dice_2,
                total=dice_1 + dice_2,
                score_before=before,
                score_after=after,
                is_bust=is_bust,
            )
        )
        if is_bust:
            self._advance_turn(table)
        self._run_bots(table)
        return table

    def hold(self, *, table_id: str, user_id: str) -> DicegetTable:
        table = self.get_table(table_id)
        seat = self._require_actionable_turn(table, user_id)
        seat.status = "held"
        seat.locked_score = seat.score
        self._advance_turn(table)
        self._run_bots(table)
        return table

    def forfeit(self, *, table_id: str, user_id: str) -> DicegetTable:
        table = self.get_table(table_id)
        seat = self._require_actionable_turn(table, user_id)
        seat.status = "forfeited"
        seat.locked_score = None
        self._advance_turn(table)
        self._run_bots(table)
        return table

    async def settle(self, table_id: str, ledger: Optional[LedgerService] = None) -> DicegetTable:
        table = self.get_table(table_id)
        if table.status == "settled":
            return table
        if table.status not in {"showdown", "active"}:
            raise DicegetError("TABLE_NOT_SETTLEABLE")
        if table.status == "active" and self._eligible_seats(table):
            raise DicegetError("TABLE_NOT_SETTLEABLE")
        table.status = "showdown"
        table.winners = self._compute_winners(table)
        if ledger is not None:
            table.settlement_results = await settle_diceget_payout(
                ledger,
                table_id=table.id,
                round_id=table.round_id,
                participants=self._payout_participants(table),
            )
        table.status = "settled"
        table.settled_at = table.settled_at or _now()
        table.current_turn_user_id = None
        return table

    def deal_again(self, *, table_id: str, user_id: str) -> DicegetTable:
        prior = self.get_table(table_id)
        if prior.status != "settled":
            raise DicegetError("TABLE_NOT_SETTLED")
        return self.create_table(
            creator_user_id=user_id,
            username=user_id,
            target_score=prior.target_score,
            stake=prior.stake,
            max_players=DICEGET_SEATS,
        )

    def _roll_die(self) -> int:
        value = int(self._dice_rng())
        if value < 1 or value > 6:
            raise DicegetError("INVALID_RNG_ROLL")
        return value

    def _normalize_score_goal(self, *, target_score: int | None, score_goal: int | None) -> int:
        value = score_goal if score_goal is not None else target_score
        if value not in SUPPORTED_SCORE_GOALS:
            raise DicegetError("INVALID_TARGET_SCORE")
        return int(value)

    def _require_actionable_turn(self, table: DicegetTable, user_id: str) -> DicegetSeat:
        if table.status != "active":
            raise DicegetError("TABLE_NOT_ACTIVE")
        if table.current_turn_user_id != user_id:
            raise DicegetError("NOT_YOUR_TURN")
        seat = next((candidate for candidate in table.seats if candidate.user_id == user_id), None)
        if seat is None:
            raise DicegetError("PLAYER_NOT_SEATED")
        if seat.status in {"held", "busted", "forfeited"}:
            raise DicegetError("PLAYER_INACTIVE")
        return seat

    def _eligible_seats(self, table: DicegetTable) -> list[DicegetSeat]:
        return [seat for seat in table.seats if seat.status == "active"]

    def _advance_turn(self, table: DicegetTable) -> None:
        eligible = self._eligible_seats(table)
        if not eligible:
            table.status = "showdown"
            table.current_turn_user_id = None
            table.winners = self._compute_winners(table)
            return
        for offset in range(1, DICEGET_SEATS + 1):
            index = (table.turn_index + offset) % DICEGET_SEATS
            if table.seats[index].status == "active":
                table.turn_index = index
                table.current_turn_user_id = table.seats[index].user_id
                return

    def _compute_winners(self, table: DicegetTable) -> list[str]:
        valid = [
            seat
            for seat in table.seats
            if seat.status == "held"
            and seat.locked_score is not None
            and seat.locked_score <= table.target_score
        ]
        if not valid:
            return []
        best = max(int(seat.locked_score or 0) for seat in valid)
        return [seat.user_id for seat in valid if seat.locked_score == best]

    def _payout_participants(self, table: DicegetTable) -> list[DicegetPayoutParticipant]:
        human_seats = [seat for seat in table.seats if not seat.is_bot]
        winner_set = {winner for winner in table.winners}
        human_winners = [seat for seat in human_seats if seat.user_id in winner_set]
        pot = len(human_seats) * table.stake
        share = pot // len(human_winners) if human_winners else 0
        remainder = pot - (share * len(human_winners)) if human_winners else 0
        participants = []
        winner_index = 0
        for seat in human_seats:
            payout = 0
            if seat in human_winners:
                payout = share + (remainder if winner_index == 0 else 0)
                winner_index += 1
            participants.append(
                DicegetPayoutParticipant(
                    user_id=seat.user_id,
                    locked_stake=table.stake,
                    payout=payout,
                )
            )
        return participants

    def _run_bots(self, table: DicegetTable) -> None:
        guard = 0
        while table.status == "active" and table.current_turn_user_id:
            guard += 1
            if guard > 100:
                raise DicegetError("BOT_LOOP_GUARD")
            seat = next(
                candidate for candidate in table.seats
                if candidate.user_id == table.current_turn_user_id
            )
            if not seat.is_bot:
                return
            profile = seat.bot_profile or "normal"
            if should_bot_hold(seat.score, table.target_score, profile):
                self.hold(table_id=table.id, user_id=seat.user_id)
            else:
                self.roll(table_id=table.id, user_id=seat.user_id)
