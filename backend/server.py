"""TARGET — FastAPI entry point."""
import logging
import os
import sys
from pathlib import Path

# Ensure /app/backend is on sys.path for absolute imports (uvicorn worker)
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, APIRouter
from fastapi.middleware.cors import CORSMiddleware

from core import db as core_db
from core.security import decode_token
from auth.router import router as auth_router
from wallet.router import router as wallet_router
from tables.router import router as tables_router
from realtime_v2.asgi import RealtimeV2
from realtime_v2.bridge import EngineBridge
from realtime_v2.dev_router import build_dev_router
from realtime_v2.pubsub import PubSub as _V2PubSub
from lobby.router import build_lobby_router
from diceget.router import build_diceget_router
from flipget.router import build_flipget_router
from jackget.router import build_jackget_router
from platform_wallet.router import router as platform_wallet_router
from tmarget.router import build_tmarget_router
from target.wallet_bridge import build_ledger_from_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="TARGET — Premium Card Game")

api_router = APIRouter(prefix="/api")


@api_router.get("/")
async def root():
    return {"name": "TARGET", "version": "1.0.0", "engine": "1.0.0"}


@api_router.get("/health")
async def health():
    return {"status": "ok"}


api_router.include_router(auth_router)
api_router.include_router(wallet_router)
api_router.include_router(tables_router)
# 2026-05 stabilization: legacy /api/ws/table/{id} WS path has been
# removed. The only realtime surface is `/api/v2/ws/table/{id}` via
# realtime_v2 below. The legacy `backend/realtime/` directory was
# fully deleted in 2026-05 v2.


# ----------------------------------------------------------------------
# Phase 6 — realtime_v2 wiring (additive, legacy ws_router untouched).
#
# Engine ↔ Realtime bridge is mounted: `EngineBridge` owns the pubsub-
# bound TurnEngine registry. Authentication reuses the existing JWT
# decoder (we do not write new auth code in this phase).
# ----------------------------------------------------------------------
async def _v2_authenticate(token: str):
    if not token:
        return None
    try:
        return decode_token(token)
    except Exception:
        return None


_v2_pubsub = _V2PubSub()
target_wallet_ledger = build_ledger_from_db(core_db.db, audit_col=core_db.db["audit_log"])
engine_bridge = EngineBridge(_v2_pubsub, target_wallet_ledger=target_wallet_ledger)


_v2_realtime = RealtimeV2(
    authenticate=_v2_authenticate,
    get_state_version=engine_bridge.get_state_version,
    handle_action=engine_bridge.handle_action,
    get_snapshot=engine_bridge.snapshot,
    on_connect=engine_bridge.notify_connect,
    on_disconnect=engine_bridge.notify_disconnect,
)
# Replace the asgi-built pubsub with the bridge's pubsub so the gateway
# and bridge share the same broadcast bus.
_v2_realtime.pubsub = _v2_pubsub
_v2_realtime.gateway._ps = _v2_pubsub  # type: ignore[attr-defined]
v2_router = _v2_realtime.build_router()
v2_router.realtime_v2 = _v2_realtime  # type: ignore[attr-defined]
api_router.include_router(v2_router)
api_router.include_router(build_dev_router(engine_bridge))
api_router.include_router(build_lobby_router(engine_bridge))
api_router.include_router(build_diceget_router())
api_router.include_router(build_flipget_router())
api_router.include_router(build_jackget_router())
api_router.include_router(build_tmarget_router())
api_router.include_router(platform_wallet_router)

# Expose for tests / future engine-spawning code.
app.state.engine_bridge = engine_bridge  # type: ignore[attr-defined]
app.state.v2_pubsub = _v2_pubsub  # type: ignore[attr-defined]

app.include_router(api_router)

# CORS — browsers reject wildcard `Access-Control-Allow-Origin: *`
# paired with `Access-Control-Allow-Credentials: true`. Starlette's
# CORSMiddleware does NOT auto-echo the request origin when
# `allow_origins=["*"]`; it only does so when `allow_origin_regex` is
# used. So we use the regex form here. `CORS_ORIGINS` env var is
# honoured for explicit lockdowns in production (comma-separated
# origins).
_cors_env = (os.environ.get("CORS_ORIGINS") or "*").strip()
if _cors_env in ("", "*"):
    # Permissive but credential-compatible: echo any origin.
    app.add_middleware(
        CORSMiddleware,
        allow_credentials=True,
        allow_origin_regex=".*",
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_credentials=True,
        allow_origins=[o.strip() for o in _cors_env.split(",") if o.strip()],
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.on_event("startup")
async def on_startup():
    await core_db.ensure_indexes()
    logger.info("MongoDB indexes ensured.")


@app.on_event("shutdown")
async def on_shutdown():
    core_db.close_client()
