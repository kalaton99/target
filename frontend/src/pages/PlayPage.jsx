import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

// Phase 11 P2 — supports two modes:
//   /play           → dev solo mode (POST /api/v2/dev/spawn_solo_table)
//   /play/:tableId  → lobby mode (uses persisted token from /lobby; reuses
//                     existing already-started table; no spawn)
//
// Auth persistence contract:
//   localStorage key "target_user" stores {user_id, username, token}.
//   LobbyPage writes it on /api/v2/lobby/auth success; PlayPage reads it
//   in lobby mode. On 401 from /api/v2/lobby/me we clear it and redirect
//   to /lobby?msg=session_expired. While the user is signed in but the
//   table is still in LOBBY we show a waiting-room (NOT "Not signed in").
//   The WebSocket is opened only once the table flips to RUNNING.

const TURN_TIMEOUT_MS = 15000;

const SUIT_GLYPH = { H: "♥", D: "♦", S: "♠", C: "♣" };
const SUIT_TONE = { H: "text-rose-400", D: "text-rose-400", S: "text-zinc-100", C: "text-zinc-100" };

function rankLabel(rank) {
  if (rank === "JK") return "JOKER";
  return rank;
}

function CardChip({ card }) {
  if (!card) return null;
  const rank = rankLabel(card.rank);
  const suit = SUIT_GLYPH[card.suit] || "";
  const tone = SUIT_TONE[card.suit] || "text-zinc-100";
  return (
    <div
      data-testid="my-card"
      className="inline-flex flex-col items-center justify-between w-16 h-24 rounded-lg border border-yellow-700/40 bg-zinc-900/90 text-zinc-100 shadow-[inset_0_0_20px_rgba(0,0,0,.6)] mr-3"
    >
      <div className={`mt-1 text-lg font-semibold ${tone}`}>{rank}</div>
      <div className={`mb-2 text-3xl ${tone}`}>{suit}</div>
    </div>
  );
}

function FaceDown() {
  return (
    <div className="inline-block w-12 h-16 rounded-md border border-zinc-600 bg-gradient-to-br from-zinc-800 to-zinc-950 mr-2" />
  );
}

function Pill({ children, tone = "default", testid }) {
  const cls =
    tone === "gold"
      ? "border-yellow-600/60 text-yellow-300"
      : tone === "danger"
      ? "border-rose-700/60 text-rose-300"
      : tone === "ok"
      ? "border-emerald-700/60 text-emerald-300"
      : "border-zinc-700/60 text-zinc-300";
  return (
    <span data-testid={testid} className={`inline-block text-xs uppercase tracking-wider px-2 py-0.5 rounded-full border bg-black/40 ${cls}`}>
      {children}
    </span>
  );
}

function PlayPage() {
  const { tableId: lobbyTableId } = useParams();
  const navigate = useNavigate();
  const lobbyMode = !!lobbyTableId;
  const [session, setSession] = useState(null);
  const [connecting, setConnecting] = useState(false);
  const [wsState, setWsState] = useState("idle"); // idle | connecting | open | closed | error
  const [view, setView] = useState({
    sv: 0,
    phase: null,
    pot: 0,
    currentTurnSeat: null,
    turnDeadlineMs: null,
    players: [],
    winners: [],
    handNumber: 0,
  });
  const [me, setMe] = useState({
    cards: [],
    score: 0,
    soft: false,
    busted: false,
    disqualified: false,
  });
  const [statusLine, setStatusLine] = useState("Ready");
  const [log, setLog] = useState([]);
  const wsRef = useRef(null);
  const myUserIdRef = useRef(null);

  const appendLog = useCallback((s) => {
    setLog((cur) => [...cur.slice(-29), s]);
  }, []);

  // ----- spawn + connect -----
  const startPlay = useCallback(async () => {
    setConnecting(true);
    setStatusLine("Spawning table…");
    try {
      const r = await fetch("/api/v2/dev/spawn_solo_table", { method: "POST" });
      if (!r.ok) throw new Error("spawn failed " + r.status);
      const data = await r.json();
      myUserIdRef.current = data.user_id;
      setSession(data);
      setView((v) => ({
        ...v,
        sv: 0,
        phase: null,
        pot: 0,
        currentTurnSeat: null,
        turnDeadlineMs: null,
        players: [],
        winners: [],
        handNumber: (v.handNumber || 0) + 1,
      }));
      setMe({ cards: [], score: 0, soft: false, busted: false, disqualified: false });
      setLog([`spawned ${data.table_id}`]);
      setStatusLine("Connecting…");
    } catch (e) {
      setStatusLine("ERROR: " + (e?.message || e));
    } finally {
      setConnecting(false);
    }
  }, []);

  // ----- lobby mode: poll table status + auto-connect when RUNNING -----
  const [lobbyTable, setLobbyTable] = useState(null);
  const [lobbyUser, setLobbyUser] = useState(null);
  const [authChecked, setAuthChecked] = useState(false); // becomes true once we know
                                                         // for sure whether user is
                                                         // signed in (avoids flashing
                                                         // "Not signed in" during the
                                                         // /me round-trip).
  const [starting, setStarting] = useState(false);

  // Phase 1: read localStorage user, validate token via /api/v2/lobby/me.
  // - missing user      → leave lobbyUser=null; render will show "Not signed in".
  // - 401 (bad/expired) → clear localStorage and navigate to /lobby with a message.
  // - ok                → set lobbyUser, which unblocks Phase 2 (table polling).
  useEffect(() => {
    if (!lobbyMode) return;
    let user = null;
    try {
      user = JSON.parse(localStorage.getItem("target_user") || "null");
    } catch {
      user = null;
    }
    if (!user || !user.token) {
      setLobbyUser(null);
      setAuthChecked(true);
      setStatusLine("Not signed in — go to /lobby first");
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch("/api/v2/lobby/me", {
          headers: { Authorization: `Bearer ${user.token}` },
        });
        if (cancelled) return;
        if (r.status === 401) {
          // token expired or invalid → clear and bounce to lobby with msg
          try { localStorage.removeItem("target_user"); } catch (_) {}
          setLobbyUser(null);
          setAuthChecked(true);
          navigate("/lobby?msg=session_expired", { replace: true });
          return;
        }
        // 2xx (or transient 5xx) → trust the persisted user; polling will
        // surface any further issues. We do NOT show "Not signed in" here.
        setLobbyUser(user);
        myUserIdRef.current = user.user_id;
        setAuthChecked(true);
      } catch {
        // Network blip — keep the user signed in optimistically.
        if (cancelled) return;
        setLobbyUser(user);
        myUserIdRef.current = user.user_id;
        setAuthChecked(true);
      }
    })();
    return () => { cancelled = true; };
  }, [lobbyMode, navigate]);

  // Phase 2: once we have a confirmed lobbyUser, poll the table doc and
  // open the WebSocket only when the table flips to RUNNING.
  useEffect(() => {
    if (!lobbyMode || !lobbyUser) return;
    let cancelled = false;
    let intervalId = null;

    const poll = async () => {
      try {
        const r = await fetch(`/api/v2/lobby/tables/${encodeURIComponent(lobbyTableId)}`);
        if (!r.ok) {
          setStatusLine("Table not found");
          return;
        }
        const t = await r.json();
        if (cancelled) return;
        setLobbyTable(t);
        if (t.status === "RUNNING" && !session) {
          // Engine is running — open WS now (only once).
          setSession({
            table_id: lobbyTableId,
            token: lobbyUser.token,
            user_id: lobbyUser.user_id,
            username: lobbyUser.username,
          });
          setStatusLine("Connecting…");
          if (intervalId) {
            clearInterval(intervalId);
            intervalId = null;
          }
        } else if (t.status === "LOBBY") {
          setStatusLine("Waiting for players…");
        }
      } catch {
        // network blip — retry on next tick
      }
    };

    poll();
    intervalId = setInterval(poll, 2000);
    return () => {
      cancelled = true;
      if (intervalId) clearInterval(intervalId);
    };
  }, [lobbyMode, lobbyUser, lobbyTableId, session]);

  const startLobbyTable = useCallback(async () => {
    if (!lobbyUser) return;
    setStarting(true);
    setStatusLine("Starting hand…");
    try {
      const r = await fetch(`/api/v2/lobby/tables/${encodeURIComponent(lobbyTableId)}/start`, {
        method: "POST",
        headers: { Authorization: `Bearer ${lobbyUser.token}` },
      });
      if (!r.ok) {
        const t = await r.text();
        setStatusLine("start failed: " + t);
        return;
      }
      // Poll loop will pick up RUNNING and open WS.
    } catch (e) {
      setStatusLine("start error: " + (e?.message || e));
    } finally {
      setStarting(false);
    }
  }, [lobbyTableId, lobbyUser]);

  // open WebSocket once we have a session
  useEffect(() => {
    if (!session) return;
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    const url = `${scheme}://${window.location.host}/api/v2/ws/table/${encodeURIComponent(
      session.table_id,
    )}?token=${encodeURIComponent(session.token)}`;

    setWsState("connecting");
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      setWsState("open");
      setStatusLine("Connected — dealing…");
      appendLog("ws open");
    };
    ws.onclose = (e) => {
      setWsState("closed");
      appendLog(`ws close ${e.code}`);
    };
    ws.onerror = () => {
      setWsState("error");
      appendLog("ws error");
    };
    ws.onmessage = (ev) => {
      let m;
      try {
        m = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (m.type === "PING") {
        try { ws.send(JSON.stringify({ type: "PONG" })); } catch (_) {}
        return;
      }
      appendLog(`← ${m.type}${m.state_version != null ? " v" + m.state_version : ""}`);
      if (m.type === "WELCOME") {
        setView((v) => ({ ...v, sv: m.state_version }));
        return;
      }
      if (m.type === "STATE_UPDATE") {
        setView({
          sv: m.state_version,
          phase: m.phase,
          pot: m.pot,
          targetScore: m.target_score,
          currentTurnSeat: m.current_turn_seat,
          turnDeadlineMs: m.turn_deadline_ms,
          players: m.players || [],
          winners: m.winners || [],
          handNumber: m.hand_number || 0,
          currentCallOwed: m.current_call_owed || 0,
        });
        return;
      }
      if (m.type === "PRIVATE_STATE") {
        setMe({
          cards: m.cards || [],
          score: m.score,
          soft: !!m.soft,
          busted: !!m.busted,
          disqualified: !!m.disqualified,
        });
        return;
      }
      if (m.type === "ACTION_ACK") {
        setStatusLine(`ACK ${m.action}`);
        return;
      }
      if (m.type === "OUT_OF_SYNC") {
        setView((v) => ({ ...v, sv: m.current_state_version }));
        setStatusLine(`OUT_OF_SYNC → resync v${m.current_state_version}`);
        return;
      }
      if (m.type === "ERROR") {
        setStatusLine(`ERROR ${m.code}`);
        return;
      }
    };

    return () => {
      try { ws.close(); } catch (_) {}
    };
  }, [session, appendLog]);

  // ----- send action -----
  const send = useCallback((action) => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({ type: action, state_version: view.sv, payload: {} }));
    setStatusLine(`→ ${action} @ v${view.sv}`);
  }, [view.sv]);

  // ----- derived: it's my turn if I'm at current_turn_seat AND DRAW phase -----
  const myUserId = session?.user_id;
  const myPlayer = useMemo(
    () => view.players.find((p) => p.user_id === myUserId),
    [view.players, myUserId],
  );
  const opponents = useMemo(
    () => view.players.filter((p) => p.user_id !== myUserId),
    [view.players, myUserId],
  );
  const myTurn =
    !!myPlayer &&
    view.currentTurnSeat === myPlayer.seat &&
    view.phase === "DRAW" &&
    !me.busted &&
    !me.disqualified;
  const myBettingTurn =
    !!myPlayer &&
    view.currentTurnSeat === myPlayer.seat &&
    view.phase === "BETTING_R1";

  // ----- countdown -----
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 100);
    return () => clearInterval(id);
  }, []);
  const remainingMs = view.turnDeadlineMs ? Math.max(0, view.turnDeadlineMs - now) : null;
  const timerPct = remainingMs == null ? 0 : Math.max(0, Math.min(100, (remainingMs / TURN_TIMEOUT_MS) * 100));

  const handFinished =
    view.phase === "PAYOUT" || view.phase === "SHOWDOWN" || view.phase === "ENDED";

  // ============ render ============
  if (!session) {
    if (lobbyMode) {
      // Auth check still pending — show neutral spinner instead of flashing
      // "Not signed in" while /api/v2/lobby/me is in flight.
      if (!authChecked) {
        return (
          <div className="min-h-screen flex items-center justify-center bg-black text-zinc-100 p-6">
            <div className="text-zinc-500 text-xs uppercase tracking-widest" data-testid="auth-loading">
              checking session…
            </div>
          </div>
        );
      }

      // Definitely not signed in.
      if (!lobbyUser) {
        return (
          <div className="min-h-screen flex items-center justify-center bg-black text-zinc-100 p-6">
            <div className="text-center max-w-md">
              <div className="text-yellow-400 mb-4" data-testid="not-signed-in">Not signed in</div>
              <p className="text-zinc-500 mb-6 text-sm">You need to register a guest username at the lobby before joining a table.</p>
              <a
                data-testid="go-lobby-link"
                href="/lobby"
                className="inline-block px-7 py-3 rounded-md border border-yellow-600/60 text-yellow-300 hover:bg-yellow-500/10 tracking-[0.3em] uppercase"
              >
                Go to lobby
              </a>
              <div className="mt-4 text-xs text-zinc-600" data-testid="status-line">{statusLine}</div>
            </div>
          </div>
        );
      }

      // Signed in, no WS yet → show waiting room (LOBBY) or "Connecting…" (RUNNING).
      const t = lobbyTable;
      const seats = t?.seats || [];
      const isCreator = !!t && t.creator_user_id === lobbyUser.user_id;
      const isLobby = t?.status === "LOBBY";
      const isRunning = t?.status === "RUNNING";
      return (
        <div className="min-h-screen bg-black text-zinc-100 p-6" data-testid="waiting-room">
          <div className="max-w-2xl mx-auto">
            <div className="flex items-center justify-between mb-6">
              <div>
                <div className="text-yellow-400/90 tracking-[0.4em] text-[10px] uppercase">TARGET — waiting room</div>
                <div className="text-zinc-100 text-lg" data-testid="my-username">{lobbyUser.username}</div>
              </div>
              <a
                data-testid="back-to-lobby-link"
                href="/lobby"
                className="px-4 py-2 rounded-md border border-zinc-700 text-zinc-400 hover:bg-zinc-800 text-xs uppercase tracking-widest"
              >
                Back
              </a>
            </div>

            <div className="rounded-lg border border-zinc-800 bg-zinc-950/40 p-5 mb-5">
              {!t ? (
                <div className="text-zinc-500 italic" data-testid="table-loading">loading table…</div>
              ) : (
                <>
                  <div className="flex items-center justify-between mb-3">
                    <div className="text-zinc-100 text-xl font-semibold" data-testid="wr-table-name">{t.name}</div>
                    <span
                      data-testid="wr-status-pill"
                      className={`text-xs uppercase tracking-widest px-2 py-0.5 rounded-full border ${
                        isRunning
                          ? "border-emerald-700/60 text-emerald-300"
                          : "border-yellow-700/60 text-yellow-300"
                      }`}
                    >
                      {t.status}
                    </span>
                  </div>
                  <div className="text-zinc-500 text-xs mb-4" data-testid="wr-meta">
                    target {t.target_score} · stake {t.stake} · {seats.length}/{t.max_players} seated · min {t.min_players}
                  </div>

                  <div className="text-zinc-400 text-xs uppercase tracking-widest mb-2">Seats</div>
                  <div className="space-y-1 mb-5" data-testid="wr-seats">
                    {seats.map((s, i) => (
                      <div
                        key={s.user_id}
                        data-testid={`wr-seat-${i}`}
                        className="flex items-center gap-3 text-sm bg-zinc-900/60 border border-zinc-800 rounded px-3 py-2"
                      >
                        <span className="text-zinc-500 text-xs w-6">#{i + 1}</span>
                        <span className="text-zinc-100">{s.username}</span>
                        {s.user_id === t.creator_user_id && (
                          <span className="text-yellow-400 text-[10px] uppercase tracking-widest">creator</span>
                        )}
                        {s.user_id === lobbyUser.user_id && (
                          <span className="text-emerald-400 text-[10px] uppercase tracking-widest">you</span>
                        )}
                      </div>
                    ))}
                    {seats.length === 0 && (
                      <div className="text-zinc-600 italic">no seats</div>
                    )}
                  </div>

                  {isLobby && isCreator && (
                    <button
                      data-testid="wr-start-btn"
                      onClick={startLobbyTable}
                      disabled={starting}
                      className="px-7 py-3 rounded-md border border-emerald-600/60 text-emerald-300 hover:bg-emerald-500/10 tracking-[0.3em] uppercase disabled:opacity-40"
                    >
                      {starting ? "Starting…" : "Start hand"}
                    </button>
                  )}
                  {isLobby && !isCreator && (
                    <div className="text-zinc-500 text-sm" data-testid="wr-waiting-creator">
                      Waiting for the creator to start the hand…
                    </div>
                  )}
                  {isRunning && (
                    <div className="text-emerald-400 text-sm" data-testid="wr-connecting">
                      Hand started — connecting…
                    </div>
                  )}
                </>
              )}
            </div>

            <div className="text-xs text-zinc-600" data-testid="status-line">{statusLine}</div>
          </div>
        </div>
      );
    }
    return (
      <div className="min-h-screen flex items-center justify-center bg-black text-zinc-100 p-6">
        <div className="max-w-xl w-full text-center">
          <div className="text-yellow-400/90 tracking-[0.5em] text-xs uppercase mb-3">TARGET</div>
          <div className="text-4xl sm:text-5xl font-bold tracking-widest text-zinc-100 mb-2">
            <span className="text-yellow-400">▲</span> reach the target
          </div>
          <p className="text-zinc-500 text-sm mb-10">
            Server-authoritative card game. Click <span className="text-yellow-400">PLAY</span> for a quick game vs a bot, or visit the <a className="text-yellow-400 underline" href="/lobby">lobby</a> to play with friends.
          </p>
          <button
            data-testid="play-btn"
            onClick={startPlay}
            disabled={connecting}
            className="px-12 py-4 rounded-md border border-yellow-600/60 bg-yellow-500/10 text-yellow-300 tracking-[0.4em] uppercase hover:bg-yellow-500/20 disabled:opacity-40 transition mr-3"
          >
            {connecting ? "…" : "PLAY"}
          </button>
          <a
            data-testid="lobby-link"
            href="/lobby"
            className="inline-block px-12 py-4 rounded-md border border-zinc-600 text-zinc-200 tracking-[0.4em] uppercase hover:bg-zinc-200/10"
          >
            Lobby
          </a>
          <div className="mt-6 text-xs text-zinc-600" data-testid="status-line">{statusLine}</div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-b from-black via-zinc-950 to-black text-zinc-100 p-4 sm:p-8">
      <div className="max-w-5xl mx-auto">
        {/* Top bar */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <div className="text-yellow-400/90 tracking-[0.4em] text-[10px] uppercase">TARGET — phase 11 mvp</div>
            <div className="text-zinc-100 text-lg" data-testid="my-username">{session.username}</div>
          </div>
          <div className="flex items-center gap-2">
            <Pill testid="phase-pill" tone="gold">{view.phase || "—"}</Pill>
            <Pill testid="sv-pill">v{view.sv}</Pill>
            <Pill tone="gold" testid="target-pill">TARGET {view.targetScore || "—"}</Pill>
            <Pill tone="gold" testid="pot-pill">POT {view.pot}</Pill>
            <Pill testid="ws-state-pill" tone={wsState === "open" ? "ok" : wsState === "error" ? "danger" : "default"}>
              WS {wsState}
            </Pill>
          </div>
        </div>

        {/* Opponents */}
        <div className="mb-8" data-testid="opponents">
          <div className="text-zinc-500 text-xs uppercase tracking-widest mb-2">Opponents</div>
          <div className="flex gap-4 flex-wrap">
            {opponents.length === 0 && (
              <div className="text-zinc-600 italic" data-testid="opponents-empty">waiting for opponents…</div>
            )}
            {opponents.map((p) => {
              const isTurn = view.currentTurnSeat === p.seat;
              return (
                <div
                  key={p.seat}
                  data-testid={`opponent-seat-${p.seat}`}
                  className={`min-w-[220px] rounded-lg border p-4 bg-zinc-900/60 ${isTurn ? "border-yellow-500" : "border-zinc-800"}`}
                >
                  <div className="flex items-center justify-between mb-2">
                    <div className="font-semibold">{p.username}</div>
                    {isTurn && <Pill tone="gold">turn</Pill>}
                  </div>
                  <div className="flex items-center mb-2">
                    {Array.from({ length: p.card_count }).map((_, i) => (
                      <FaceDown key={i} />
                    ))}
                    {p.card_count === 0 && <span className="text-zinc-600 text-sm">no cards</span>}
                  </div>
                  <div className="flex gap-1 flex-wrap">
                    <Pill testid={`opponent-${p.seat}-cardcount`}>cards: {p.card_count}</Pill>
                    <Pill>score: {p.score}{p.soft ? " soft" : ""}</Pill>
                    {p.busted && <Pill tone="danger">BUST</Pill>}
                    {p.stood && <Pill tone="ok">STOOD</Pill>}
                    {p.folded && <Pill tone="danger">FOLD</Pill>}
                    {p.disqualified && <Pill tone="danger">DQ</Pill>}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* My hand */}
        <div className="mb-6" data-testid="my-hand">
          <div className="flex items-center justify-between mb-3">
            <div className="text-zinc-500 text-xs uppercase tracking-widest">Your hand</div>
            <div className="flex items-center gap-2">
              <Pill testid="my-score" tone="gold">score {me.score}{me.soft ? " soft" : ""}</Pill>
              {me.busted && <Pill tone="danger">BUST</Pill>}
              {me.disqualified && <Pill tone="danger">DQ</Pill>}
              {myTurn && <Pill testid="your-turn-pill" tone="gold">YOUR TURN</Pill>}
            </div>
          </div>
          <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-5">
            {me.cards.length === 0 ? (
              <div className="text-zinc-600 italic" data-testid="my-cards-empty">no cards yet…</div>
            ) : (
              <div className="flex" data-testid="my-cards">
                {me.cards.map((c, i) => (
                  <CardChip key={i} card={c} />
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Turn timer */}
        <div className="mb-6">
          <div className="flex items-center justify-between mb-1">
            <div className="text-zinc-500 text-xs uppercase tracking-widest">Turn timer</div>
            <div className="text-zinc-400 text-xs" data-testid="timer-text">
              {remainingMs == null ? "—" : `${Math.ceil(remainingMs / 1000)}s`}
            </div>
          </div>
          <div className="h-1.5 rounded-full bg-zinc-900 overflow-hidden">
            <div
              data-testid="timer-bar"
              className="h-full bg-yellow-500 transition-all"
              style={{ width: `${timerPct}%` }}
            />
          </div>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-3 mb-4 flex-wrap">
          <button
            data-testid="hit-btn"
            onClick={() => send("HIT")}
            disabled={!myTurn}
            className="px-7 py-3 rounded-md border border-yellow-600/50 text-yellow-300 hover:bg-yellow-500/10 disabled:opacity-30 disabled:cursor-not-allowed tracking-[0.3em] uppercase"
          >
            HIT
          </button>
          <button
            data-testid="stand-btn"
            onClick={() => send("STAND")}
            disabled={!myTurn}
            className="px-7 py-3 rounded-md border border-zinc-600 text-zinc-200 hover:bg-zinc-200/10 disabled:opacity-30 disabled:cursor-not-allowed tracking-[0.3em] uppercase"
          >
            STAND
          </button>
          <button
            data-testid="check-btn"
            onClick={() => send("CHECK")}
            disabled={!myBettingTurn || view.currentCallOwed > 0}
            className="px-5 py-3 rounded-md border border-zinc-600 text-zinc-200 hover:bg-zinc-200/10 disabled:opacity-30 disabled:cursor-not-allowed tracking-[0.3em] uppercase"
          >
            CHECK
          </button>
          <button
            data-testid="call-btn"
            onClick={() => send("CALL")}
            disabled={!myBettingTurn || view.currentCallOwed === 0}
            className="px-5 py-3 rounded-md border border-zinc-600 text-zinc-200 hover:bg-zinc-200/10 disabled:opacity-30 disabled:cursor-not-allowed tracking-[0.3em] uppercase"
          >
            CALL {view.currentCallOwed > 0 ? `(${view.currentCallOwed})` : ""}
          </button>
          <button
            data-testid="fold-btn"
            onClick={() => send("FOLD")}
            disabled={!myBettingTurn}
            className="px-5 py-3 rounded-md border border-rose-700/60 text-rose-300 hover:bg-rose-500/10 disabled:opacity-30 disabled:cursor-not-allowed tracking-[0.3em] uppercase"
          >
            FOLD
          </button>
          {handFinished && (
            <button
              data-testid="deal-again-btn"
              onClick={startPlay}
              className="px-7 py-3 rounded-md border border-emerald-600/60 text-emerald-300 hover:bg-emerald-500/10 tracking-[0.3em] uppercase"
            >
              Deal again
            </button>
          )}
          <span className="ml-auto text-zinc-500 text-xs" data-testid="status-line">{statusLine}</span>
        </div>

        {/* Winners panel */}
        {view.winners && view.winners.length > 0 && (
          <div className="mb-4 rounded-md border border-yellow-700/40 bg-yellow-500/5 p-4" data-testid="winners">
            <div className="text-yellow-400 uppercase tracking-widest text-sm mb-1">Winner{view.winners.length > 1 ? "s" : ""}</div>
            <div className="text-zinc-100">{view.winners.join(", ")}</div>
          </div>
        )}

        {/* Event log */}
        <div className="rounded-md border border-zinc-800 bg-black/60 p-3">
          <div className="text-zinc-500 text-[10px] uppercase tracking-widest mb-2">event log</div>
          <pre className="text-zinc-400 text-[11px] leading-5 max-h-40 overflow-auto" data-testid="event-log">
{log.join("\n")}
          </pre>
        </div>
      </div>
    </div>
  );
}

export default PlayPage;
