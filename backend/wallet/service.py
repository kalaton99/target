"""Wallet service.

Hybrid versioning: each wallet doc has `version` int. Mutations use
findOneAndUpdate with both balance check and version check (atomic single-doc).

Idempotency: enforced via unique index on idempotency_keys collection.
Inserts there fail with DuplicateKeyError on retry; we then return cached.

Double-entry: every mutation writes paired ledger rows (user / pot|house|lottery).
journal_id ties a pair together. Sum across journal_id must always be zero.
"""
import asyncio
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from core import db


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _expires_iso(hours: int = 24) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


class WalletError(Exception):
    pass


class InsufficientFunds(WalletError):
    pass


class StaleVersion(WalletError):
    pass


class DuplicateAction(WalletError):
    pass


async def get_wallet(user_id: str) -> Optional[Dict[str, Any]]:
    return await db.wallets.find_one({"user_id": user_id}, {"_id": 0})


async def _try_mutate(
    user_id: str, delta: int, expected_version: int
) -> Optional[Dict[str, Any]]:
    """Single atomic mutation. Returns updated doc or None on conflict.

    Conditions:
      - version must match expected
      - balance + delta must be >= 0
    """
    filter_ = {
        "user_id": user_id,
        "version": expected_version,
        "balance": {"$gte": -delta if delta < 0 else 0},
    }
    update = {
        "$inc": {"balance": delta, "version": 1},
        "$set": {"updated_at": _now_iso()},
    }
    return await db.wallets.find_one_and_update(
        filter_, update, return_document=ReturnDocument.AFTER, projection={"_id": 0}
    )


async def mutate(
    user_id: str,
    delta: int,
    reason: str,
    ref_type: str,
    ref_id: Optional[str],
    idempotency_key: Optional[str] = None,
    counter_account: str = "POT",
) -> Dict[str, Any]:
    """Atomic balance change with retry on version conflict + double-entry ledger.

    Args:
        delta: signed credits (negative debit, positive credit)
        counter_account: 'POT' | 'HOUSE' | 'LOTTERY' | 'SYSTEM'
    Returns:
        {"balance": int, "version": int, "transaction_id": str}
    """
    if delta == 0:
        raise WalletError("ZERO_DELTA")

    # Idempotency pre-check (DB-enforced via unique index on insert)
    idem_doc_id: Optional[str] = None
    if idempotency_key:
        idem_doc_id = f"ik_{uuid.uuid4().hex[:20]}"
        try:
            await db.idempotency_keys.insert_one({
                "id": idem_doc_id,
                "client_action_id": idempotency_key,
                "user_id": user_id,
                "scope": "WALLET",
                "request_hash": f"{delta}:{reason}:{ref_id}",
                "response_snapshot": None,
                "created_at": _now_iso(),
                "expires_at": _expires_iso(24),
            })
        except DuplicateKeyError:
            existing = await db.idempotency_keys.find_one(
                {"user_id": user_id, "scope": "WALLET", "client_action_id": idempotency_key},
                {"_id": 0},
            )
            if existing and existing.get("response_snapshot"):
                return existing["response_snapshot"]
            raise DuplicateAction("DUPLICATE_ACTION_PENDING")

    # Hybrid optimistic+atomic mutation with retry
    last_err: Optional[Exception] = None
    for attempt in range(3):
        wallet = await get_wallet(user_id)
        if not wallet:
            raise WalletError("WALLET_NOT_FOUND")
        if delta < 0 and wallet["balance"] + delta < 0:
            raise InsufficientFunds("INSUFFICIENT_FUNDS")

        updated = await _try_mutate(user_id, delta, wallet["version"])
        if updated:
            tx_id = f"tx_{uuid.uuid4().hex[:20]}"
            journal_id = f"j_{uuid.uuid4().hex[:20]}"
            now = _now_iso()
            # Double-entry: user side + counter side
            await db.transactions.insert_many([
                {
                    "id": tx_id,
                    "journal_id": journal_id,
                    "user_id": user_id,
                    "account_type": "USER",
                    "amount": delta,
                    "balance_after": updated["balance"],
                    "reason": reason,
                    "ref_type": ref_type,
                    "ref_id": ref_id,
                    "idempotency_key_id": idem_doc_id,
                    "created_at": now,
                },
                {
                    "id": f"tx_{uuid.uuid4().hex[:20]}",
                    "journal_id": journal_id,
                    "user_id": None,
                    "account_type": counter_account,
                    "amount": -delta,
                    "balance_after": None,
                    "reason": reason,
                    "ref_type": ref_type,
                    "ref_id": ref_id,
                    "idempotency_key_id": idem_doc_id,
                    "created_at": now,
                },
            ])

            response = {
                "balance": updated["balance"],
                "version": updated["version"],
                "transaction_id": tx_id,
            }
            if idem_doc_id:
                await db.idempotency_keys.update_one(
                    {"id": idem_doc_id},
                    {"$set": {"response_snapshot": response}},
                )
            return response

        last_err = StaleVersion("WALLET_VERSION_CONFLICT")
        await asyncio.sleep(0.01 * (2 ** attempt))

    raise last_err  # type: ignore[misc]


async def list_transactions(user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    cursor = db.transactions.find(
        {"user_id": user_id}, {"_id": 0}
    ).sort("created_at", -1).limit(limit)
    return [doc async for doc in cursor]
