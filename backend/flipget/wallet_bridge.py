from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from ledger.service import (
    InsufficientFunds,
    LedgerService,
    LockedFundsError,
    REASON_FLIPGET_CANCEL_UNLOCK,
    REASON_FLIPGET_JOIN_LOCK,
    REASON_FLIPGET_REFUND,
    REASON_FLIPGET_WIN_PAYOUT,
)


FLIPGET_SOURCE_MODULE = "flipget"
NON_REFUNDABLE_TABLE_STATES = {"flipping", "settled"}


class FlipgetWalletError(Exception):
    pass


class FlipgetRefundNotAllowed(FlipgetWalletError):
    pass


class FlipgetInsufficientFunds(FlipgetWalletError):
    pass


@dataclass(frozen=True)
class FlipgetPayoutParticipant:
    user_id: str
    locked_stake: int
    payout: int = 0


def join_lock_key(table_id: str, user_id: str) -> str:
    return f"flipget:{table_id}:join:{user_id}"


def cancel_unlock_key(table_id: str, user_id: str) -> str:
    return f"flipget:{table_id}:cancel:{user_id}"


def settlement_key(table_id: str, round_id: str) -> str:
    return f"flipget:{table_id}:settlement:{round_id}"


def payout_key(table_id: str, user_id: str, round_id: str) -> str:
    return f"flipget:{table_id}:payout:{user_id}:{round_id}"


async def lock_flipget_stake(
    ledger: LedgerService,
    *,
    table_id: str,
    user_id: str,
    stake: int,
) -> dict[str, Any]:
    if stake <= 0:
        return {"user_id": user_id, "skipped": True, "reason": "ZERO_STAKE"}
    try:
        return await ledger.lock_balance(
            user_id=user_id,
            amount=stake,
            ref_type="FLIPGET_TABLE",
            ref_id=table_id,
            idempotency_key=join_lock_key(table_id, user_id),
            source_module=FLIPGET_SOURCE_MODULE,
            reason=REASON_FLIPGET_JOIN_LOCK,
        )
    except InsufficientFunds as exc:
        raise FlipgetInsufficientFunds(str(exc)) from exc


async def unlock_flipget_stake(
    ledger: LedgerService,
    *,
    table_id: str,
    user_id: str,
    stake: int,
    table_status: str,
    reason: str = REASON_FLIPGET_CANCEL_UNLOCK,
) -> dict[str, Any]:
    if table_status in NON_REFUNDABLE_TABLE_STATES:
        raise FlipgetRefundNotAllowed(f"REFUND_NOT_ALLOWED_IN_STATE:{table_status}")
    if reason not in {REASON_FLIPGET_CANCEL_UNLOCK, REASON_FLIPGET_REFUND}:
        raise FlipgetWalletError(f"INVALID_FLIPGET_UNLOCK_REASON:{reason}")
    if stake <= 0:
        return {"user_id": user_id, "skipped": True, "reason": "ZERO_STAKE"}
    try:
        return await ledger.unlock_balance(
            user_id=user_id,
            amount=stake,
            ref_type="FLIPGET_TABLE",
            ref_id=table_id,
            idempotency_key=cancel_unlock_key(table_id, user_id),
            source_module=FLIPGET_SOURCE_MODULE,
            reason=reason,
        )
    except LockedFundsError as exc:
        raise FlipgetWalletError(str(exc)) from exc


async def settle_flipget_payout(
    ledger: LedgerService,
    *,
    table_id: str,
    round_id: str,
    participants: Iterable[FlipgetPayoutParticipant],
) -> list[dict[str, Any]]:
    results = []
    for participant in participants:
        if participant.locked_stake <= 0:
            continue
        results.append(
            await ledger.settle_locked(
                user_id=participant.user_id,
                locked_debit=participant.locked_stake,
                payout_amount=participant.payout,
                ref_type="FLIPGET_ROUND",
                ref_id=round_id,
                idempotency_key=payout_key(table_id, participant.user_id, round_id),
                source_module=FLIPGET_SOURCE_MODULE,
                reason=REASON_FLIPGET_WIN_PAYOUT,
                counter_account="POT",
            )
        )
    return results


def build_ledger_from_db(db, *, audit_col=None) -> LedgerService:
    return LedgerService(
        db.wallets,
        db.transactions,
        db.idempotency_keys,
        db["journals"],
        audit_col=audit_col,
    )
