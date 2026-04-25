"""Auth service: register, login. JWT email/password."""
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import HTTPException

from core import db
from core.config import SIGNUP_BONUS
from core.security import hash_password, verify_password, create_token


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def register(email: str, username: str, password: str) -> Dict[str, Any]:
    email = email.strip().lower()
    username = username.strip()
    if len(password) < 6:
        raise HTTPException(400, "PASSWORD_TOO_SHORT")
    if len(username) < 3:
        raise HTTPException(400, "USERNAME_TOO_SHORT")

    # Check uniqueness
    existing = await db.users.find_one({"$or": [{"email": email}, {"username": username}]}, {"_id": 0})
    if existing:
        raise HTTPException(409, "USER_EXISTS")

    user_id = f"u_{uuid.uuid4().hex[:20]}"
    user_doc = {
        "id": user_id,
        "email": email,
        "username": username,
        "password_hash": hash_password(password),
        "google_sub": None,
        "avatar_url": None,
        "level": 1,
        "xp": 0,
        "status": "ACTIVE",
        "created_at": _now_iso(),
        "last_login_at": _now_iso(),
    }
    await db.users.insert_one(user_doc)

    # Create wallet with signup bonus
    wallet_id = f"w_{uuid.uuid4().hex[:20]}"
    wallet_doc = {
        "id": wallet_id,
        "user_id": user_id,
        "balance": SIGNUP_BONUS,
        "gems": 0,
        "locked": 0,
        "version": 0,
        "updated_at": _now_iso(),
    }
    await db.wallets.insert_one(wallet_doc)

    # Signup bonus ledger entry — double-entry: USER credit + HOUSE debit
    journal_id = f"j_{uuid.uuid4().hex[:20]}"
    tx_id = f"tx_{uuid.uuid4().hex[:20]}"
    await db.transactions.insert_many([
        {
            "id": tx_id,
            "journal_id": journal_id,
            "user_id": user_id,
            "account_type": "USER",
            "amount": SIGNUP_BONUS,
            "balance_after": SIGNUP_BONUS,
            "reason": "SIGNUP_BONUS",
            "ref_type": "SYSTEM",
            "ref_id": None,
            "idempotency_key_id": None,
            "created_at": _now_iso(),
        },
        {
            "id": f"tx_{uuid.uuid4().hex[:20]}",
            "journal_id": journal_id,
            "user_id": None,
            "account_type": "HOUSE",
            "amount": -SIGNUP_BONUS,
            "balance_after": None,
            "reason": "SIGNUP_BONUS",
            "ref_type": "SYSTEM",
            "ref_id": None,
            "idempotency_key_id": None,
            "created_at": _now_iso(),
        },
    ])

    token = create_token(user_id)
    return {
        "token": token,
        "user": {
            "id": user_id,
            "email": email,
            "username": username,
            "level": 1,
            "xp": 0,
            "balance": SIGNUP_BONUS,
        },
    }


async def login(email: str, password: str) -> Dict[str, Any]:
    email = email.strip().lower()
    user = await db.users.find_one({"email": email}, {"_id": 0})
    if not user or not user.get("password_hash"):
        raise HTTPException(401, "INVALID_CREDENTIALS")
    if not verify_password(password, user["password_hash"]):
        raise HTTPException(401, "INVALID_CREDENTIALS")
    if user.get("status") != "ACTIVE":
        raise HTTPException(403, "ACCOUNT_BLOCKED")

    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {"last_login_at": _now_iso()}},
    )

    wallet = await db.wallets.find_one({"user_id": user["id"]}, {"_id": 0}) or {"balance": 0}
    token = create_token(user["id"])
    return {
        "token": token,
        "user": {
            "id": user["id"],
            "email": user["email"],
            "username": user["username"],
            "level": user.get("level", 1),
            "xp": user.get("xp", 0),
            "balance": wallet["balance"],
        },
    }


async def get_me(user_id: str) -> Optional[Dict[str, Any]]:
    user = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
    if not user:
        return None
    wallet = await db.wallets.find_one({"user_id": user_id}, {"_id": 0}) or {"balance": 0}
    user["balance"] = wallet["balance"]
    return user
