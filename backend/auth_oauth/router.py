"""Emergent-managed Google OAuth — sits side-by-side with the existing
guest/JWT flow.

Endpoints (all under `/api/v2/auth`):
  - POST `/google/session`  — exchange `session_id` for user + cookie.
  - GET  `/me`              — current user (cookie OR bearer).
  - POST `/logout`          — clears cookie + DB session.

The Google path persists user identity in `users` (uniqued by email) and
issues a 7-day cookie session via `user_sessions`. It ALSO mints a
short-lived JWT (compatible with `core.security.create_token`) so the
existing WebSocket gateway and lobby endpoints can authenticate the
same user without any changes — bearer remains the canonical token
for game-time auth, while the cookie buys refresh-resilience for the
top-level page.

REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS,
THIS BREAKS THE AUTH. The frontend computes the redirect target from
`window.location.origin` and the backend never sees it.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel

from core import db as core_db
from core.config import SIGNUP_BONUS
from core.security import create_token, decode_token
from target.wallet_bridge import build_ledger_from_db

logger = logging.getLogger("auth_oauth")

EMERGENT_SESSION_DATA_URL = (
    "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data"
)
SESSION_TTL = timedelta(days=7)

router = APIRouter(prefix="/v2/auth", tags=["auth-oauth"])


# ---------- models ----------

class _SessionRequest(BaseModel):
    session_id: str


class _PublicUser(BaseModel):
    user_id: str
    email: str
    name: str
    picture: str = ""
    auth_provider: str


class _SessionResponse(BaseModel):
    user: _PublicUser
    jwt: str  # Bearer token for WS / lobby endpoints (compat with guest flow).


# ---------- helpers ----------

async def _resolve_user_from_cookie_or_bearer(
    db,
    session_token: Optional[str],
    authorization: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Returns the user document, or None if neither auth method is valid.

    Order: cookie first (DB-backed session, longest lived), then bearer
    (JWT issued by the same backend).
    """
    if session_token:
        sess = await db.user_sessions.find_one(
            {"session_token": session_token}, {"_id": 0},
        )
        if sess:
            expires_at = sess.get("expires_at")
            if isinstance(expires_at, str):
                expires_at = datetime.fromisoformat(expires_at)
            if expires_at and expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at and expires_at >= datetime.now(timezone.utc):
                user = await db.users.find_one(
                    {"user_id": sess["user_id"]}, {"_id": 0},
                )
                if user:
                    return user
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1].strip()
        try:
            uid = decode_token(token)
        except HTTPException:
            return None
        user = await db.users.find_one({"user_id": uid}, {"_id": 0})
        return user
    return None


# ---------- routes ----------

@router.post("/google/session", response_model=_SessionResponse)
async def google_session(body: _SessionRequest, response: Response):
    """Exchange a one-time `session_id` (from the URL fragment after
    Google OAuth) for a server-side session + JWT.
    """
    if not body.session_id or len(body.session_id) > 512:
        raise HTTPException(status_code=400, detail="INVALID_SESSION_ID")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                EMERGENT_SESSION_DATA_URL,
                headers={"X-Session-ID": body.session_id},
            )
        if r.status_code != 200:
            logger.warning("emergent session-data %s: %s", r.status_code, r.text[:200])
            raise HTTPException(status_code=401, detail="OAUTH_EXCHANGE_FAILED")
        data = r.json()
    except httpx.HTTPError as exc:
        logger.exception("emergent session-data network error")
        raise HTTPException(status_code=502, detail="OAUTH_UPSTREAM_ERROR") from exc

    email = (data.get("email") or "").lower().strip()
    name = (data.get("name") or email or "Player").strip()
    picture = data.get("picture") or ""
    session_token = data.get("session_token")
    if not email or not session_token:
        raise HTTPException(status_code=502, detail="OAUTH_BAD_PAYLOAD")

    db = core_db.db

    # Find-or-create user keyed on email.
    existing = await db.users.find_one({"email": email}, {"_id": 0})
    now = datetime.now(timezone.utc)
    if existing:
        user_id = existing["user_id"]
        await db.users.update_one(
            {"user_id": user_id},
            {"$set": {
                "name": name, "picture": picture,
                "auth_provider": "google",
                "last_login_at": now,
            }},
        )
        user_doc = {**existing, "name": name, "picture": picture,
                    "auth_provider": "google", "last_login_at": now}
    else:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        # `users.username` carries a unique index — set it to a unique
        # derivative (email is already unique) to side-step null-collision.
        username_unique = f"g_{user_id[-10:]}"
        user_doc = {
            "user_id": user_id,
            "email": email,
            "username": username_unique,
            "name": name,
            "picture": picture,
            "auth_provider": "google",
            "created_at": now,
            "last_login_at": now,
        }
        await db.users.insert_one(dict(user_doc))
        user_doc.pop("_id", None)

    # Persist DB-backed session (used by cookie auth + logout). Dedupe
    # on `session_token` so a re-exchange of the same Emergent session
    # rebinds to the latest user/email rather than resurrecting an
    # earlier identity (relevant for tests + repeat sign-ins).
    expires_at = now + SESSION_TTL
    await db.user_sessions.delete_many({"session_token": session_token})
    await db.user_sessions.insert_one({
        "user_id": user_id,
        "session_token": session_token,
        "expires_at": expires_at,
        "created_at": now,
    })

    # 2026-05 v2 — mirror identity into `lobby_users` so the existing
    # `lobby/service.get_user` path (used by `create_table` /
    # `start_table` / `join_table`) finds this user without a rewrite.
    # `username` collisions across OAuth users are vanishingly rare
    # (we suffix with the user_id tail when they happen).
    base_username = (name or email.split("@")[0])[:24] or "Player"
    candidate = base_username
    if await db["lobby_users"].find_one(
        {"username": candidate, "user_id": {"$ne": user_id}}, {"_id": 0},
    ):
        candidate = f"{base_username[:18]}_{user_id[-5:]}"
    await db["lobby_users"].update_one(
        {"user_id": user_id},
        {"$set": {"user_id": user_id, "username": candidate, "auth_provider": "google"}},
        upsert=True,
    )
    await build_ledger_from_db(db, audit_col=db["audit_log"]).open_wallet(
        user_id,
        opening_balance=SIGNUP_BONUS,
    )

    # Cookie — httpOnly, samesite=None+secure for cross-site WS / iframe
    # compatibility (matches playbook). `secure` is gated by env so the
    # ASGI test harness (plain HTTP) can still set + read the cookie.
    cookie_secure = os.environ.get(
        "OAUTH_COOKIE_SECURE", "1",
    ).strip().lower() not in ("0", "false", "no", "off")
    response.set_cookie(
        key="session_token",
        value=session_token,
        max_age=int(SESSION_TTL.total_seconds()),
        path="/",
        httponly=True,
        secure=cookie_secure,
        samesite="none" if cookie_secure else "lax",
    )

    jwt_token = create_token(user_id)

    return _SessionResponse(
        user=_PublicUser(
            user_id=user_id, email=email, name=name, picture=picture,
            auth_provider="google",
        ),
        jwt=jwt_token,
    )


@router.get("/me", response_model=_PublicUser)
async def me(
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    db = core_db.db
    user = await _resolve_user_from_cookie_or_bearer(
        db, session_token, authorization,
    )
    if user is None:
        raise HTTPException(status_code=401, detail="UNAUTHENTICATED")
    return _PublicUser(
        user_id=user["user_id"],
        email=user.get("email", ""),
        name=user.get("name", user.get("username", "")),
        picture=user.get("picture", ""),
        auth_provider=user.get("auth_provider", "guest"),
    )


@router.post("/logout")
async def logout(
    response: Response,
    session_token: Optional[str] = Cookie(default=None),
):
    if session_token:
        try:
            await core_db.db.user_sessions.delete_many(
                {"session_token": session_token},
            )
        except Exception:
            logger.exception("session delete failed")
    response.delete_cookie("session_token", path="/")
    return {"ok": True}


# ---------- guest auth gating ----------

def is_guest_auth_enabled() -> bool:
    """Guest/dev auth (`POST /api/v2/lobby/auth`) is on unless the env
    var is explicitly set to "0" / "false". Default-on keeps the dev
    workflow + the existing test suite unblocked.
    """
    val = os.environ.get("ALLOW_GUEST_AUTH", "1").strip().lower()
    return val not in ("0", "false", "no", "off")
