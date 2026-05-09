from __future__ import annotations

from ledger.service import (
    LedgerService,
    REASON_TMARKET_REFUND,
    REASON_TMARKET_SETTLEMENT_WIN,
)

from .pricing import PAYOUT_PER_SHARE


async def credit_settlement(
    ledger: LedgerService,
    *,
    user_id: str,
    market_id: str,
    amount: int,
    idempotency_key: str,
) -> dict:
    return await ledger.mutate(
        user_id=user_id,
        delta=amount,
        reason=REASON_TMARKET_SETTLEMENT_WIN,
        ref_type="TMARGET_MARKET",
        ref_id=market_id,
        idempotency_key=idempotency_key,
        counter_account="POT",
        source_module="tmarget",
    )


async def credit_refund(
    ledger: LedgerService,
    *,
    user_id: str,
    market_id: str,
    amount: int,
    idempotency_key: str,
) -> dict:
    return await ledger.mutate(
        user_id=user_id,
        delta=amount,
        reason=REASON_TMARKET_REFUND,
        ref_type="TMARGET_MARKET",
        ref_id=market_id,
        idempotency_key=idempotency_key,
        counter_account="POT",
        source_module="tmarget",
    )


def payout_amount(shares: int) -> int:
    return int(shares) * PAYOUT_PER_SHARE
