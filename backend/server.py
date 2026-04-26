"""TARGET — FastAPI entry point."""
import logging
import sys
from pathlib import Path

# Ensure /app/backend is on sys.path for absolute imports (uvicorn worker)
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, APIRouter
from fastapi.middleware.cors import CORSMiddleware

from core import db as core_db
from core.config import CORS_ORIGINS
from core.security import decode_token
from auth.router import router as auth_router
from wallet.router import router as wallet_router
from tables.router import router as tables_router
from realtime.ws_router import ws_router
from realtime import table_worker
from realtime_v2.asgi import build_v2_router

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
api_router.include_router(ws_router)  # WS endpoint at /api/ws/table/{id}


# ----------------------------------------------------------------------
# Phase 6 — realtime_v2 wiring (additive, legacy ws_router untouched).
#
# The gateway is transport-only. State-version and action-handler are
# stubbed here; engine integration is deferred to a later phase per the
# strict phase plan. Authentication reuses the existing JWT decoder
# (we do not write new auth code in this phase).
# ----------------------------------------------------------------------
async def _v2_authenticate(token: str):
    if not token:
        return None
    try:
        return decode_token(token)
    except Exception:
        return None


async def _v2_get_state_version(table_id: str):
    # Stub: any table appears at version 0 until engine is wired.
    # Returning None would emit TABLE_NOT_FOUND to the client.
    return 0


async def _v2_handle_action(table_id, user_id, action, payload, sv):
    # Stub: engine not yet wired in this phase.
    return {"accepted": False, "reason": "ENGINE_NOT_WIRED"}


v2_router = build_v2_router(
    authenticate=_v2_authenticate,
    get_state_version=_v2_get_state_version,
    handle_action=_v2_handle_action,
)
api_router.include_router(v2_router)

app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def on_startup():
    await core_db.ensure_indexes()
    logger.info("MongoDB indexes ensured.")


@app.on_event("shutdown")
async def on_shutdown():
    await table_worker.stop_all()
    core_db.close_client()
