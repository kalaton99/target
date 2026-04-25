"""WebSocket gateway: /api/ws/table/{table_id}?token=<jwt>"""
import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from core.security import decode_token
from core import db
from core.constants import SERVER_ONLY_ACTIONS
from .connection_manager import manager
from . import table_worker

logger = logging.getLogger(__name__)

ws_router = APIRouter()

MAX_USER_CONNS = 2
MAX_MSG_BYTES = 4096
ALLOWED_CLIENT_ACTIONS = {"HIT", "STAND", "FOLD", "CHECK", "CALL", "RAISE"}


@ws_router.websocket("/ws/table/{table_id}")
async def ws_endpoint(websocket: WebSocket, table_id: str, token: Optional[str] = Query(None)):
    if not token:
        await websocket.close(code=4401)
        return
    try:
        user_id = decode_token(token)
    except Exception:
        await websocket.close(code=4401)
        return

    # Per-user connection cap
    if manager.user_conn_count(user_id) >= MAX_USER_CONNS:
        await websocket.close(code=4403)
        return

    # Verify seated
    table = await db.tables.find_one({"id": table_id}, {"_id": 0})
    if not table:
        await websocket.close(code=4404)
        return
    seat = next((s for s in table["seats"] if s["user_id"] == user_id), None)
    if seat is None:
        await websocket.close(code=4403)
        return

    await websocket.accept()
    await manager.add(table_id, user_id, websocket)
    worker = await table_worker.get_or_spawn(table_id)
    # Broadcast latest state to this socket
    if worker.state is not None:
        from game_engine.view_filter import public_view
        try:
            await websocket.send_json({
                "type": "STATE_UPDATE",
                "view": public_view(worker.state, user_id),
                "events": [{"type": "STATE_INIT"}],
                "state_version": worker.state.version,
            })
        except Exception:
            pass
    # Tell worker to add this player if not already in state
    await worker.enqueue({
        "type": "PLAYER_JOIN",
        "source": "SERVER",
        "user_id": user_id,
        "seat_index": seat["seat_index"],
        "state_version": worker.state.version if worker.state else 0,
    })

    try:
        while True:
            msg = await asyncio.wait_for(websocket.receive_text(), timeout=120)
            if len(msg) > MAX_MSG_BYTES:
                continue
            try:
                data = json.loads(msg)
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            a_type = data.get("type")
            if a_type == "PING":
                await websocket.send_json({"type": "PONG"})
                continue
            if a_type in SERVER_ONLY_ACTIONS:
                await websocket.send_json({"type": "ACTION_REJECTED", "error": "SERVER_ONLY_ACTION"})
                continue
            if a_type not in ALLOWED_CLIENT_ACTIONS:
                await websocket.send_json({"type": "ACTION_REJECTED", "error": "UNKNOWN_ACTION"})
                continue
            data["user_id"] = user_id
            data["source"] = "CLIENT"
            await worker.enqueue(data)
    except WebSocketDisconnect:
        pass
    except asyncio.TimeoutError:
        try:
            await websocket.close(code=1001)
        except Exception:
            pass
    except Exception as e:
        logger.warning("ws error: %s", e)
    finally:
        await manager.remove(table_id, user_id, websocket)
