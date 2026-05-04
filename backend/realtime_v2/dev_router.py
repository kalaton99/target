"""Phase 6 (UI scaffolding) — minimal dev endpoints.

Provides just enough surface to play a full hand from a browser without
implementing the lobby, table CRUD, or any real-money flow:

  POST /api/v2/dev/spawn_solo_table
       Returns: {table_id, token, user_id, username}
       - mints a fresh anonymous user JWT
       - creates a 2-player TurnEngine (you + a bot)
       - registers it in the EngineBridge
       - starts the hand
       - spins up a BotDriver task that auto-acts on the bot's turn

  GET  /api/v2/dev/play
       Returns: a minimal HTML+vanilla-JS page that:
         * spawns a solo table on load
         * connects to /api/v2/ws/table/{id}?token=<jwt>
         * renders own hand, opponent count, current turn, countdown,
           plus HIT / STAND buttons.

This module is dev-only. It must not be relied on by Phase 11 production
UI; it is here purely so a human can validate the engine end-to-end
before lobby/table flows are built.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Dict

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from core.constants import ALLOW_BOTS
from core.security import create_token
from game_engine.turn_engine import TurnEngine
from game_engine.types import GameState, PlayerState

from .bridge import EngineBridge

logger = logging.getLogger("realtime_v2.dev")


# ---------- bot driver ----------

class _BotDriver:
    """Server-side bot that auto-acts on its turn.

    Strategy (intentionally simple, dev-only):
      - DRAW    -> HIT while score < ceil(target_score * 0.6); else STAND
      - BETTING -> CHECK if no current bet, otherwise CALL

    Reacts to STATE_UPDATE broadcasts from the bridge's pubsub. The
    bot's score for the HIT/STAND decision is read from its own row
    in the broadcast `players` array (public score, not private —
    private cards are fine for face-up TARGET, all cards are public).

    Per GAME_RULES_LOCKED.md §5 this driver only runs when the bridge
    explicitly seats a bot via `bot_count`. There is no auto-spawn.
    """

    def __init__(
        self,
        bridge: EngineBridge,
        table_id: str,
        bot_user_id: str,
        bot_seat: int,
    ) -> None:
        self._bridge = bridge
        self._table_id = table_id
        self._bot_user_id = bot_user_id
        self._bot_seat = bot_seat
        self._task: asyncio.Task | None = None
        self._sub: asyncio.Queue | None = None

    async def start(self) -> None:
        # 2026-05 stabilization: subscribe *before* returning so the
        # caller (lobby spawn) can safely submit START_HAND knowing the
        # bot will not miss the resulting STATE_UPDATE. The asyncio.Task
        # is what processes the queue going forward.
        topic = f"table:{self._table_id}"
        self._sub = await self._bridge._pubsub.subscribe(topic)
        self._task = asyncio.create_task(self._run(), name=f"bot:{self._table_id}")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        if self._sub is not None:
            try:
                await self._bridge._pubsub.unsubscribe(
                    f"table:{self._table_id}", self._sub,
                )
            except Exception:
                pass
            self._sub = None

    def _decide_draw_action(self, msg: dict) -> str:
        """2026-05 v2 strategic bot policy (locked).

        Policy (score expressed as fraction of `target_score`):
          - score >= target       → STAND  (bust-safety, should never be reached)
          - score >= target * 0.8 → STAND
          - target*0.5 <= score < target*0.8 → 60% HIT / 40% STAND
          - score <  target * 0.5 → HIT

        Randomness is deterministic per (table_id, bot_user_id,
        state_version) so replays produce the same decisions and the
        stress suite is stable. We use the bottom 16 bits of a SHA-1
        digest mod 100 as a cheap, dependency-free integer RNG.
        """
        target = int(msg.get("target_score") or 30)
        score = 0
        for p in msg.get("players") or []:
            if p.get("user_id") == self._bot_user_id:
                score = int(p.get("score") or 0)
                break

        # Bust-safety: should never be on-turn while score >= target,
        # but if it happens, STAND is the only non-throwaway choice.
        if score >= target:
            return "STAND"
        # Integer comparisons avoid float rounding edge cases.
        upper = (target * 8) // 10   # 0.8 target
        lower = (target * 5) // 10   # 0.5 target
        if score >= upper:
            return "STAND"
        if score < lower:
            return "HIT"

        # Middle band — 60% HIT / 40% STAND via deterministic PRNG.
        import hashlib
        sv = int(msg.get("state_version") or 0)
        seed = f"{self._table_id}:{self._bot_user_id}:{sv}".encode("utf-8")
        # Bottom 16 bits of sha1 → int 0..65535, mod 100 → 0..99.
        roll = int(hashlib.sha1(seed).hexdigest()[-4:], 16) % 100
        return "HIT" if roll < 60 else "STAND"

    async def _run(self) -> None:
        # Subscription is owned by start() so there is no race with the
        # initial STATE_UPDATE emitted on START_HAND.
        assert self._sub is not None, "BotDriver._run called without start()"
        sub = self._sub
        topic = f"table:{self._table_id}"
        # Watchdog: if we do not receive a STATE_UPDATE for `poll_s`
        # seconds we synthesize one from the current engine snapshot
        # (delivered via bridge). This guards against a slow-consumer
        # drop for this bot's queue and against any upstream race that
        # would otherwise leave the bot idle while it's on turn.
        poll_s = 2.0
        try:
            while True:
                msg: dict | None = None
                try:
                    msg = await asyncio.wait_for(sub.get(), timeout=poll_s)
                except asyncio.TimeoutError:
                    # Snapshot-based recovery: if we're on-turn per the
                    # engine's authoritative state, act regardless.
                    eng = self._bridge._engines.get(self._table_id)
                    if eng is None:
                        continue
                    st = eng.state
                    if st.current_turn_seat != self._bot_seat:
                        continue
                    msg = {
                        "type": "STATE_UPDATE",
                        "state_version": st.version,
                        "phase": st.phase,
                        "current_turn_seat": st.current_turn_seat,
                        "current_call_owed": st.current_call_owed,
                        "target_score": st.target_score,
                        "players": [
                            {"user_id": p.user_id, "seat": p.seat_index,
                             "score": p.score}
                            for p in st.players
                        ],
                    }
                if msg is None or msg.get("type") != "STATE_UPDATE":
                    continue
                if msg.get("current_turn_seat") != self._bot_seat:
                    continue
                phase = msg.get("phase")
                sv = int(msg["state_version"])
                # tiny natural pause so a human can see the bot's turn
                await asyncio.sleep(0.5)
                # 2026-05 multi-round: handle DRAW / DRAW_1 / DRAW_2 and
                # BETTING_R1 / R2 / R3 identically — the action set is
                # the same per category.
                if phase in ("DRAW", "DRAW_1", "DRAW_2"):
                    action = self._decide_draw_action(msg)
                elif phase in ("BETTING_R1", "BETTING_R2", "BETTING_R3"):
                    # CHECK if no call owed; otherwise CALL.
                    action = "CHECK" if msg.get("current_call_owed", 0) == 0 else "CALL"
                else:
                    continue
                try:
                    await self._bridge.handle_action(
                        self._table_id, self._bot_user_id, action, {}, sv,
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("bot action failed table=%s", self._table_id)
        finally:
            try:
                await self._bridge._pubsub.unsubscribe(topic, sub)
            except Exception:
                pass


# ---------- factory ----------

def build_dev_router(bridge: EngineBridge) -> APIRouter:
    router = APIRouter(prefix="/v2/dev", tags=["realtime_v2.dev"])
    bots: Dict[str, _BotDriver] = {}

    @router.post("/spawn_solo_table")
    async def spawn_solo_table():
        # 2026-05: solo tables pair the user with a bot. Per
        # GAME_RULES_LOCKED.md §5 this MUST be off in production.
        if not ALLOW_BOTS:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=404,
                detail={"code": "BOTS_DISABLED",
                        "message": "solo/bot tables are disabled on this server"},
            )
        suffix = uuid.uuid4().hex[:6]
        user_id = f"u_anon_{suffix}"
        bot_user_id = f"u_bot_{suffix}"
        username = f"You_{suffix}"
        bot_username = f"Bot_{suffix}"
        table_id = f"tbl_{uuid.uuid4().hex[:12]}"

        state = GameState(table_id=table_id)
        state.players = [
            PlayerState(
                seat_index=0, user_id=user_id, username=username,
                balance_at_start=1000,
            ),
            PlayerState(
                seat_index=1, user_id=bot_user_id, username=bot_username,
                balance_at_start=1000,
            ),
        ]
        engine = TurnEngine(state, turn_timeout_ms=15000)
        bridge.register_engine(table_id, engine)
        await engine.start()

        bot = _BotDriver(bridge, table_id, bot_user_id, bot_seat=1)
        await bot.start()
        bots[table_id] = bot

        # Start the hand (server-driven). Do not await a particular phase here;
        # the gateway's WELCOME → first STATE_UPDATE flow will surface it.
        await engine.submit({
            "type": "START_HAND",
            "source": "SERVER",
            "hand_id": f"h_{uuid.uuid4().hex[:10]}",
            "nonce": 0,
            "server_seed": "0" * 64,
            "server_seed_hash": "h" * 64,
            "client_seeds": "",
            "target_score": 30,
        })

        token = create_token(user_id)
        return {
            "table_id": table_id,
            "token": token,
            "user_id": user_id,
            "username": username,
            "bot_user_id": bot_user_id,
            "bot_username": bot_username,
        }

    @router.get("/play", response_class=HTMLResponse)
    async def play():
        return HTMLResponse(_PLAY_HTML)

    return router


# ---------- minimal UI ----------

_PLAY_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>TARGET — dev play</title>
<style>
  body{font-family:ui-monospace,Menlo,monospace;margin:24px;max-width:860px;color:#eee;background:#111}
  h1{font-size:18px;letter-spacing:.5px;margin:0 0 12px}
  .row{display:flex;gap:16px;flex-wrap:wrap;margin:12px 0}
  .panel{border:1px solid #333;padding:12px;border-radius:6px;flex:1;min-width:260px;background:#181818}
  .pill{display:inline-block;padding:2px 8px;border:1px solid #555;border-radius:999px;margin-right:6px;font-size:12px}
  .turn{color:#ffd54a}
  .me{color:#7ee0a6}
  .opp{color:#9bb6ff}
  .card{display:inline-block;border:1px solid #555;padding:6px 10px;margin:2px 4px 2px 0;border-radius:6px;background:#222}
  button{background:#222;color:#eee;border:1px solid #555;padding:8px 14px;margin-right:8px;border-radius:4px;cursor:pointer}
  button:disabled{opacity:.4;cursor:not-allowed}
  .timer{height:6px;background:#333;border-radius:3px;overflow:hidden}
  .timer > div{height:100%;background:#ffd54a;width:100%;transition:width .1s linear}
  pre{background:#0a0a0a;border:1px solid #222;padding:8px;max-height:180px;overflow:auto;font-size:11px;color:#9aa}
</style>
</head>
<body>
<h1>TARGET — dev play</h1>
<div class="row">
  <div class="panel" id="meta">
    <div>Table: <code id="t">…</code></div>
    <div>You: <code id="u">…</code></div>
    <div>State version: <code id="sv">—</code></div>
    <div>Phase: <code id="ph">—</code></div>
    <div>Pot: <code id="pt">—</code></div>
  </div>
  <div class="panel">
    <div>Turn timer</div>
    <div class="timer"><div id="tm"></div></div>
    <div style="margin-top:6px">Current turn: <span class="turn" id="ct">—</span></div>
  </div>
</div>

<div class="row">
  <div class="panel">
    <div><strong>You</strong> <span class="pill me" id="ms">score: —</span></div>
    <div id="mh"></div>
  </div>
  <div class="panel">
    <div><strong>Opponents</strong></div>
    <div id="op"></div>
  </div>
</div>

<div class="row">
  <div class="panel">
    <button id="hit" disabled data-testid="hit-btn">HIT</button>
    <button id="std" disabled data-testid="stand-btn">STAND</button>
    <span id="status" style="margin-left:12px;color:#9aa"></span>
  </div>
</div>

<div class="panel">
  <div style="margin-bottom:6px">Event log</div>
  <pre id="log"></pre>
</div>

<script>
(async function(){
  const $ = id => document.getElementById(id);
  const log = (m) => { const el=$("log"); el.textContent += m+"\\n"; el.scrollTop = el.scrollHeight; };
  const set = (id, v) => { $(id).textContent = (v===null||v===undefined) ? "—" : v; };

  // 1) spawn solo table
  let info;
  try {
    const r = await fetch("/api/v2/dev/spawn_solo_table",{method:"POST"});
    info = await r.json();
  } catch (e) {
    log("spawn failed: "+e); return;
  }
  set("t", info.table_id);
  set("u", info.username + " (" + info.user_id + ")");
  log("spawned table "+info.table_id);

  // 2) WS connect
  const wsScheme = location.protocol === "https:" ? "wss" : "ws";
  const url = wsScheme+"://"+location.host+"/api/v2/ws/table/"+encodeURIComponent(info.table_id)+"?token="+encodeURIComponent(info.token);
  const ws = new WebSocket(url);
  let state = { sv: 0, phase: null, myTurn: false, deadline: null };
  let me = info.user_id;

  ws.onopen = () => log("ws open");
  ws.onclose = (e) => { log("ws close "+e.code); $("hit").disabled=true; $("std").disabled=true; };
  ws.onerror = (e) => log("ws error");
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.type === "PING") { ws.send(JSON.stringify({type:"PONG"})); return; }
    log("← "+m.type+(m.state_version!==undefined?" v"+m.state_version:""));
    if (m.type === "WELCOME") { state.sv = m.state_version; set("sv", state.sv); return; }
    if (m.type === "STATE_UPDATE") {
      state.sv = m.state_version; set("sv", state.sv);
      set("ph", m.phase); set("pt", m.pot);
      state.deadline = m.turn_deadline_ms;
      const turnPlayer = (m.current_turn_seat===null||m.current_turn_seat===undefined) ? null
                        : (m.players[m.current_turn_seat] && m.players[m.current_turn_seat].username);
      set("ct", turnPlayer || "—");
      const myPlayer = m.players.find(p => p.user_id === me);
      state.myTurn = myPlayer && (m.current_turn_seat === myPlayer.seat) && m.phase === "DRAW";
      $("hit").disabled = !state.myTurn;
      $("std").disabled = !state.myTurn;
      // opponents
      const op = m.players.filter(p => p.user_id !== me).map(p => {
        return "<div class='opp'><strong>"+p.username+"</strong> "
          + "<span class='pill'>seat "+p.seat+"</span>"
          + "<span class='pill'>cards: "+p.card_count+"</span>"
          + "<span class='pill'>score: "+p.score+(p.busted?" BUST":"")+(p.stood?" STOOD":"")+"</span>"
          + "</div>";
      }).join("");
      $("op").innerHTML = op || "<em>none</em>";
      // own score header
      if (myPlayer) $("ms").textContent = "score: "+myPlayer.score+(myPlayer.soft?" soft":"")+(myPlayer.busted?" BUST":"")+(myPlayer.stood?" STOOD":"");
      return;
    }
    if (m.type === "PRIVATE_STATE") {
      const div = document.getElementById("mh");
      div.innerHTML = (m.cards||[]).map(c => "<span class='card'>"+(c.rank||"?")+(c.suit||"")+"</span>").join("");
      $("ms").textContent = "score: "+m.score+(m.soft?" soft":"")+(m.busted?" BUST":"");
      return;
    }
    if (m.type === "ACTION_ACK") { $("status").textContent = "ACK "+m.action; return; }
    if (m.type === "OUT_OF_SYNC") { $("status").textContent = "OUT_OF_SYNC, resync to v"+m.current_state_version; state.sv = m.current_state_version; return; }
    if (m.type === "ERROR") { $("status").textContent = "ERR "+m.code; return; }
  };

  // 3) buttons
  function send(action){
    if (!state.myTurn) return;
    ws.send(JSON.stringify({type: action, state_version: state.sv, payload: {}}));
    $("status").textContent = "→ "+action+" @ v"+state.sv;
    $("hit").disabled = true; $("std").disabled = true;
  }
  $("hit").onclick = () => send("HIT");
  $("std").onclick = () => send("STAND");

  // 4) countdown timer
  setInterval(() => {
    if (!state.deadline) { $("tm").style.width = "100%"; return; }
    const ms = state.deadline - Date.now();
    const pct = Math.max(0, Math.min(100, (ms / 15000) * 100));
    $("tm").style.width = pct + "%";
  }, 100);
})();
</script>
</body>
</html>
"""
