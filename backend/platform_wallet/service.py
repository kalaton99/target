from __future__ import annotations

from typing import Any, Optional


SOURCE_LABELS = {
    "target": "Target",
    "diceget": "Diceget",
    "flipget": "Flipget",
    "tmarget": "Tmarget",
    "payment": "Payment / Demo Credit",
    "admin": "Admin",
}

REASON_LABELS = {
    "target_join_lock": "stake locked",
    "diceget_join_lock": "stake locked",
    "flipget_join_lock": "stake locked",
    "target_cancel_unlock": "stake unlocked",
    "diceget_cancel_unlock": "stake unlocked",
    "flipget_cancel_unlock": "stake unlocked",
    "target_win_payout": "win payout",
    "diceget_win_payout": "win payout",
    "flipget_win_payout": "win payout",
    "tmarget_buy_cost": "market buy",
    "tmarget_sell_credit": "market sell",
    "tmarget_settlement_win": "market settlement",
    "tmarget_settlement_loss": "market settlement",
    "tmarget_refund": "market refund",
    "tmarget_fee": "market fee",
    "tmarget_admin_market_create": "demo market create",
    "target_refund": "refund",
    "diceget_refund": "refund",
    "flipget_refund": "refund",
    "SIGNUP_BONUS": "demo credit",
    "sandbox_deposit": "demo credit",
    "admin_credit": "demo credit",
}


def wallet_summary(user_id: str, wallet: Optional[dict[str, Any]]) -> dict[str, Any]:
    balance = int((wallet or {}).get("balance", 0) or 0)
    locked = int((wallet or {}).get("locked_balance", (wallet or {}).get("locked", 0)) or 0)
    return {
        "user_id": user_id,
        "balance": balance,
        "locked": locked,
        "locked_balance": locked,
        "available_balance": max(0, balance),
        "currency_type": "internal_demo_credit",
        "currency_label": "Internal demo credits",
        "sandbox_notice": (
            "This platform currently uses internal demo credits. Live deposits, "
            "withdrawals, card payments, crypto transfers, and Telegram wallet "
            "linking are not enabled."
        ),
    }


def sanitize_ledger_entry(tx: dict[str, Any]) -> dict[str, Any]:
    amount = int(tx.get("amount", 0) or 0)
    balance_after = tx.get("balance_after")
    balance_before = None
    if balance_after is not None:
        balance_after = int(balance_after)
        balance_before = balance_after - amount

    account_type = tx.get("account_type")
    locked_after = None
    locked_before = None
    if account_type == "USER_LOCKED":
        locked_after = tx.get("locked_after")
        if locked_after is not None:
            locked_after = int(locked_after)
            locked_before = locked_after - amount

    source_module = tx.get("source_module") or infer_source_module(tx.get("reason"))
    reason = tx.get("reason") or ""
    return {
        "id": tx.get("id"),
        "source_module": source_module,
        "source_label": SOURCE_LABELS.get(source_module, source_module or "Unknown"),
        "source_id": tx.get("ref_id"),
        "reason": reason,
        "reason_label": REASON_LABELS.get(reason, reason.lower().replace("_", " ") if reason else "unknown"),
        "amount": amount,
        "balance_before": balance_before,
        "balance_after": balance_after,
        "locked_before": locked_before,
        "locked_after": locked_after,
        "created_at": tx.get("created_at"),
        "status": tx.get("status", "POSTED"),
    }


def infer_source_module(reason: Optional[str]) -> str:
    if not reason:
        return "admin"
    lower = reason.lower()
    for module in ("target", "diceget", "flipget", "tmarget", "payment", "admin"):
        if lower.startswith(module):
            return module
    if lower in {"signup_bonus", "admin_credit"}:
        return "admin"
    if lower == "sandbox_deposit":
        return "payment"
    return "admin"


async def get_wallet_summary(db, user_id: str) -> dict[str, Any]:
    wallet = await db.wallets.find_one({"user_id": user_id}, {"_id": 0})
    return wallet_summary(user_id, wallet)


async def list_ledger_entries(db, user_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit or 100), 200))
    cursor = db.transactions.find({"user_id": user_id}, {"_id": 0}).sort("created_at", -1).limit(limit)
    return [sanitize_ledger_entry(doc) async for doc in cursor]
