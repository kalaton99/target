"""Thin Target wallet lifecycle bridge.

Current wallet exposure model:
- Target locks the table stake at create/join time.
- In-hand betting beyond that stake remains engine-local for this MVP pass.
- PAYOUT mirrors the existing engine payout plan into LedgerService using
  deterministic idempotency keys.

The recommended MVP path is a full buy-in lock up front, sized high enough
to cover in-hand betting exposure. Per-bet ledger locking is a later,
higher-risk phase because it would touch reducer/action timing and every
betting transition.

This module translates Target table/hand lifecycle events into durable
LedgerService calls. It deliberately does not know Target game rules, RNG,
WebSocket protocol, or payout math; callers pass the already-authoritative
stake and payout plan produced by existing Target code.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional

from ledger.service import (
    InsufficientFunds,
    LedgerService,
    LockedFundsError,
    REASON_TARGET_CANCEL_UNLOCK,
    REASON_TARGET_JOIN_LOCK,
    REASON_TARGET_REFUND,
    REASON_TARGET_WIN_PAYOUT,
    WalletError,
)

TARGET_SOURCE_MODULE = "target"
NON_REFUNDABLE_TABLE_STATES = {"RUNNING", "SETTLED", "PAYOUT", "ENDED", "FINAL"}


class TargetWalletBridgeError(Exception):
    pass


class TargetWalletRefundNotAllowed(TargetWalletBridgeError):
    pass


class TargetWalletInsufficientFunds(TargetWalletBridgeError):
    pass


@dataclass(frozen=True)
class TargetPayoutParticipant:
    user_id: str
    locked_stake: int
    payout: int = 0


def join_lock_key(table_id: str, user_id: str) -> str:
    return f"target:{table_id}:join:{user_id}"


def cancel_unlock_key(table_id: str, user_id: str) -> str:
    return f"target:{table_id}:cancel:{user_id}"


def payout_key(table_id: str, user_id: str, round_id: str) -> str:
    return f"target:{table_id}:payout:{user_id}:{round_id}"


async def lock_target_stake(
    ledger: LedgerService,
    *,
    table_id: str,
    user_id: str,
    stake: int,
) -> dict[str, Any]:
    """Lock a player's Target stake before they are allowed into a table."""
    if stake <= 0:
        return {
            "user_id": user_id,
            "balance": None,
            "locked": None,
            "locked_balance": None,
            "skipped": True,
            "reason": "ZERO_STAKE",
        }
    try:
        return await ledger.lock_balance(
            user_id=user_id,
            amount=stake,
            ref_type="TARGET_TABLE",
            ref_id=table_id,
            idempotency_key=join_lock_key(table_id, user_id),
            source_module=TARGET_SOURCE_MODULE,
            reason=REASON_TARGET_JOIN_LOCK,
        )
    except InsufficientFunds as exc:
        raise TargetWalletInsufficientFunds(str(exc)) from exc


async def unlock_target_stake(
    ledger: LedgerService,
    *,
    table_id: str,
    user_id: str,
    stake: int,
    table_status: str,
    reason: str = REASON_TARGET_CANCEL_UNLOCK,
) -> dict[str, Any]:
    """Unlock a player's stake only while the table is still pre-game."""
    if table_status in NON_REFUNDABLE_TABLE_STATES:
        raise TargetWalletRefundNotAllowed(f"REFUND_NOT_ALLOWED_IN_STATE:{table_status}")
    if reason not in {REASON_TARGET_CANCEL_UNLOCK, REASON_TARGET_REFUND}:
        raise TargetWalletBridgeError(f"INVALID_TARGET_UNLOCK_REASON:{reason}")
    if stake <= 0:
        return {
            "user_id": user_id,
            "balance": None,
            "locked": None,
            "locked_balance": None,
            "skipped": True,
            "reason": "ZERO_STAKE",
        }
    try:
        return await ledger.unlock_balance(
            user_id=user_id,
            amount=stake,
            ref_type="TARGET_TABLE",
            ref_id=table_id,
            idempotency_key=cancel_unlock_key(table_id, user_id),
            source_module=TARGET_SOURCE_MODULE,
            reason=reason,
        )
    except LockedFundsError as exc:
        raise TargetWalletBridgeError(str(exc)) from exc


async def settle_target_payout(
    ledger: LedgerService,
    *,
    table_id: str,
    round_id: str,
    participants: Iterable[TargetPayoutParticipant],
) -> list[dict[str, Any]]:
    """Consume each participant's locked stake and credit any winner payout.

    The payout amounts must come from Target's existing reducer/engine state.
    This function only mirrors that plan into the durable ledger.
    """
    results: list[dict[str, Any]] = []
    for participant in participants:
        if participant.locked_stake <= 0:
            continue
        results.append(
            await ledger.settle_locked(
                user_id=participant.user_id,
                locked_debit=participant.locked_stake,
                payout_amount=participant.payout,
                ref_type="TARGET_HAND",
                ref_id=round_id,
                idempotency_key=payout_key(table_id, participant.user_id, round_id),
                source_module=TARGET_SOURCE_MODULE,
                reason=REASON_TARGET_WIN_PAYOUT,
                counter_account="POT",
            )
        )
    return results


def participants_from_engine_state(state: Any) -> list[TargetPayoutParticipant]:
    """Build a durable settlement plan from the already-computed engine state."""
    participants: list[TargetPayoutParticipant] = []
    locked_stake = int(getattr(state, "stake", 0) or 0)
    if locked_stake <= 0:
        return participants
    for player in getattr(state, "players", []) or []:
        if getattr(player, "user_id", "").startswith("u_bot_"):
            continue
        participants.append(
            TargetPayoutParticipant(
                user_id=player.user_id,
                locked_stake=locked_stake,
                payout=int(getattr(player, "payout", 0) or 0),
            )
        )
    return participants


async def settle_target_state_if_payout(
    ledger: Optional[LedgerService],
    *,
    state: Any,
) -> list[dict[str, Any]]:
    """Settle a Target engine state if it is at PAYOUT.

    Safe to call repeatedly. Ledger idempotency keys prevent duplicate debits
    or credits for the same table/user/hand.
    """
    if ledger is None or getattr(state, "phase", None) != "PAYOUT":
        return []
    round_id = getattr(state, "hand_id", None) or f"hand-{getattr(state, 'hand_number', 0)}"
    participants = participants_from_engine_state(state)
    if not participants:
        return []
    return await settle_target_payout(
        ledger,
        table_id=state.table_id,
        round_id=round_id,
        participants=participants,
    )


def build_ledger_from_db(db, *, audit_col=None) -> LedgerService:
    """Construct the shared LedgerService from the app DB object."""
    return LedgerService(
        db.wallets,
        db.transactions,
        db.idempotency_keys,
        db["journals"],
        audit_col=audit_col,
    )
