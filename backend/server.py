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
from auth.router import router as auth_router
from wallet.router import router as wallet_router
from tables.router import router as tables_router
from realtime.ws_router import ws_router
from realtime import table_worker

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
