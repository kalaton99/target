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

// Special-card detection — keep in sync with backend/core/constants.py.
// Defense (2H, 2C) → enables PLAY_TWO. Attack (10H, 10C) → enables PLAY_TEN.
function isDefenseTwo(card) {
  return !!card && card.rank === "2" && (card.suit === "H" || card.suit === "C");
}
function isAttackTen(card) {
  return !!card && card.rank === "10" && (card.suit === "H" || card.suit === "C");
}

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
      : tone === "accent"
      ? "border-indigo-600/60 text-indigo-300"
      : "border-zinc-700/60 text-zinc-300";
  return (
    <span data-testid={testid} className={`inline-block text-xs uppercase tracking-wider px-2 py-0.5 rounded-full border bg-black/40 ${cls}`}>
      {children}
    </span>
  );
}

// 2026-05 v2 — PART 3 cosmetic bot personality.
// All bots share the same decision policy; the label is a pure
// stable cosmetic derived from user_id so the same bot shows the
// same flavor across hands. Only applied to `u_bot_*` users.
const BOT_FLAVORS = ["Conservative", "Balanced", "Aggressive"];
function botFlavorFor(userId) {
  if (!userId || !userId.startsWith("u_bot_")) return null;
  let hash = 0;
  for (let i = 0; i < userId.length; i++) {
    hash = ((hash << 5) - hash + userId.charCodeAt(i)) | 0;
  }
  return BOT_FLAVORS[Math.abs(hash) % BOT_FLAVORS.length];
}

// 2026-05 v2 — PART 1 labels for the showdown clarity block.
// `isRiskTaker` threshold: 3+ cards means the player drew at least
// twice (initial deal is 1 card). Cheap, intent-readable heuristic.
function computeHandLabels(player, eligibleMaxScore, handFinished) {
  const out = [];
  if (!handFinished) return out;
  if (player.busted) out.push({ key: "busted", tone: "danger", text: "Busted" });
  if (player.disqualified) out.push({ key: "dq", tone: "danger", text: "Disqualified" });
  if (!player.busted && !player.disqualified
      && eligibleMaxScore !== null
      && player.score === eligibleMaxScore) {
    out.push({ key: "closest", tone: "gold", text: "Closest to target" });
  }
  if ((player.card_count || 0) >= 3) {
    out.push({ key: "risk", tone: "accent", text: "Risk taker" });
  }
  return out;
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
  // Transient banner for engine-emitted user-visible notices (currently:
  // AUTO_STAND on turn timeout). Auto-dismisses after 4s.
  const [notice, setNotice] = useState(null); // { kind, text, ts }
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
          try {
            localStorage.removeItem("target_user");
          } catch (e) {
            console.warn("PlayPage: failed to clear target_user from localStorage", e);
          }
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
      } catch (e) {
        // network blip — retry on next tick. Logged at debug level so the
        // console isn't spammed during normal flaky polling.
        console.debug("PlayPage: lobby table poll failed (will retry)", e);
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
      } catch (e) {
        console.warn("PlayPage: malformed WS message dropped", e);
        return;
      }
      if (m.type === "PING") {
        try {
          ws.send(JSON.stringify({ type: "PONG" }));
        } catch (e) {
          console.warn("PlayPage: failed to send PONG", e);
        }
        return;
      }
      appendLog(`← ${m.type}${m.state_version != null ? " v" + m.state_version : ""}`);
      if (m.type === "WELCOME") {
        setView((v) => ({ ...v, sv: m.state_version }));
        return;
      }
      if (m.type === "STATE_UPDATE") {
        const players = m.players || [];
        setView({
          sv: m.state_version,
          phase: m.phase,
          pot: m.pot,
          targetScore: m.target_score,
          currentTurnSeat: m.current_turn_seat,
          turnDeadlineMs: m.turn_deadline_ms,
          players,
          winners: m.winners || [],
          handNumber: m.hand_number || 0,
          currentCallOwed: m.current_call_owed || 0,
        });
        // Surface user-visible engine events (currently: auto-stand on
        // timeout). The events array carries one entry per intent applied
        // since the last broadcast.
        if (Array.isArray(m.events)) {
          for (const ev of m.events) {
            // PART 2 — action feedback: surface ordinary gameplay actions
            // (HIT / STAND / CHECK / BET / CALL / RAISE / FOLD) as a
            // short fade banner so the player can see what just happened.
            // We skip the local player's own actions to avoid self-echo,
            // and we already handle special cases (auto-stand,
            // PLAY_TWO/TEN, presence) below.
            const actionVerbs = {
              HIT: "hit",
              STAND: "stood",
              CHECK: "checked",
              BET: "bet",
              CALL: "called",
              RAISE: "raised",
              FOLD: "folded",
            };
            const verb = actionVerbs[ev.type];
            if (verb && !ev.auto) {
              const owner =
                players.find((p) => p.user_id === ev.user_id) ||
                players.find((p) => p.seat === ev.seat);
              const name = owner?.username || `seat ${ev.seat}`;
              // Amount is meaningful for BET/RAISE/CALL
              const amt = ev.amount || ev.raise_amount;
              const suffix = amt ? ` ${amt}` : "";
              const text = `${name} ${verb}${suffix}`;
              appendLog(text);
              if (ev.user_id !== myUserIdRef.current) {
                setNotice({ kind: `action-${ev.type.toLowerCase()}`, text, ts: Date.now() });
              }
            }
            if (ev.type === "STAND" && ev.auto) {
              const owner =
                players.find((p) => p.user_id === ev.user_id) ||
                players.find((p) => p.seat === ev.seat);
              const name = owner?.username || `seat ${ev.seat}`;
              const text = `${name} auto-stand (timeout)`;
              appendLog(text);
              setNotice({ kind: "auto-stand", text, ts: Date.now() });
            }
            if (ev.type === "FOLD" && ev.auto) {
              const owner =
                players.find((p) => p.user_id === ev.user_id) ||
                players.find((p) => p.seat === ev.seat);
              const name = owner?.username || `seat ${ev.seat}`;
              const text = `${name} auto-fold (${ev.reason || "timeout"})`;
              appendLog(text);
              setNotice({ kind: "auto-fold", text, ts: Date.now() });
            }
            if (ev.type === "PLAY_TWO" || ev.type === "PLAY_TEN") {
              const fromP =
                players.find((p) => p.user_id === ev.user_id) ||
                players.find((p) => p.seat === ev.seat);
              const toP =
                players.find((p) => p.user_id === ev.to_user_id) ||
                players.find((p) => p.seat === ev.to_seat);
              const fromName = fromP?.username || `seat ${ev.seat}`;
              const toName = toP?.username || `seat ${ev.to_seat}`;
              const card = ev.transferred_card || ev.sent_card || {};
              const cardLabel = card.rank ? `${card.rank}${card.suit || ""}` : "card";
              const verb = ev.type === "PLAY_TWO" ? "transferred (2)" : "attacked with (10)";
              const text = `${fromName} ${verb} → ${toName}: ${cardLabel}`;
              appendLog(text);
              setNotice({
                kind: ev.type === "PLAY_TWO" ? "play-two" : "play-ten",
                text,
                ts: Date.now(),
              });
            }
            if (ev.type === "PRESENCE" || ev.type === "PRESENCE_GRACE_EXPIRED") {
              // Presence transitions are best surfaced on opponents
              // (the local user's own connect/disconnect already shows
              // up via wsState). We log every transition but only
              // banner remote events to avoid self-flicker.
              const owner =
                players.find((p) => p.user_id === ev.user_id) ||
                players.find((p) => p.seat === ev.seat);
              const name = owner?.username || `seat ${ev.seat}`;
              let text;
              if (ev.type === "PRESENCE_GRACE_EXPIRED") {
                text = `${name} sitting out (grace expired)`;
              } else if (ev.connected === false) {
                text = `${name} disconnected — reconnecting…`;
              } else {
                text = `${name} reconnected`;
              }
              appendLog(text);
              if (ev.user_id !== myUserIdRef.current) {
                setNotice({ kind: "presence", text, ts: Date.now() });
              }
            }
          }
        }
        return;
      }
      if (m.type === "PRIVATE_STATE") {
        // Defensively drop any null/undefined entries from the cards array
        // before they reach render, so a malformed payload cannot crash
        // the card-loop key expression (`${c.rank}-${c.suit}-${i}`).
        const safeCards = Array.isArray(m.cards)
          ? m.cards.filter((c) => c && typeof c === "object")
          : [];
        setMe({
          cards: safeCards,
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
      try {
        ws.close();
      } catch (e) {
        console.warn("PlayPage: error while closing WS on unmount", e);
      }
    };
  }, [session, appendLog]);

  // ----- send action -----
  const send = useCallback((action) => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({ type: action, state_version: view.sv, payload: {} }));
    setStatusLine(`→ ${action} @ v${view.sv}`);
  }, [view.sv]);

  // Special-card intent: same protocol as `send`, but with a structured
  // payload (target_user_id + transfer_card_index | attack_card_index).
  // Engine path: backend/game_engine/reducer.py PLAY_TWO / PLAY_TEN.
  const sendSpecial = useCallback((action, payload) => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({ type: action, state_version: view.sv, payload }));
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
    // 2026-05 multi-round: HIT/STAND/PLAY_TWO/PLAY_TEN reachable in
    // legacy DRAW and the new DRAW_1 / DRAW_2 phases.
    (view.phase === "DRAW" || view.phase === "DRAW_1" || view.phase === "DRAW_2") &&
    !me.busted &&
    !me.disqualified;
  const myBettingTurn =
    !!myPlayer &&
    view.currentTurnSeat === myPlayer.seat &&
    // 2026-05 multi-round: R2 / R3 use the same betting actions as R1.
    (view.phase === "BETTING_R1"
      || view.phase === "BETTING_R2"
      || view.phase === "BETTING_R3");

  // ----- special-card derived state -----
  // Trigger-card indices in the local player's hand. -1 if not held.
  const defenseTwoIdx = useMemo(
    () => me.cards.findIndex(isDefenseTwo),
    [me.cards],
  );
  const attackTenIdx = useMemo(
    () => me.cards.findIndex(isAttackTen),
    [me.cards],
  );
  // Active opponents are valid targets: still in hand, not folded/busted/DQ.
  const activeOpponents = useMemo(
    () => opponents.filter((p) => !p.folded && !p.busted && !p.disqualified),
    [opponents],
  );
  const canPlayTwo = myTurn && defenseTwoIdx >= 0 && me.cards.length >= 2 && activeOpponents.length > 0;
  const canPlayTen = myTurn && attackTenIdx >= 0 && me.cards.length >= 2 && activeOpponents.length > 0;

  // Special-card picker: when open, the user chooses (target_user_id, send_card_index).
  // `kind` is "PLAY_TWO" or "PLAY_TEN"; null when closed.
  const [picker, setPicker] = useState(null); // { kind, targetUserId, cardIdx }
  const openPicker = useCallback((kind) => {
    const triggerIdx = kind === "PLAY_TWO" ? defenseTwoIdx : attackTenIdx;
    // Default target = first active opponent. Default card = first non-trigger card.
    const defaultTarget = activeOpponents[0]?.user_id || null;
    const defaultCardIdx = me.cards.findIndex((_, i) => i !== triggerIdx);
    setPicker({ kind, targetUserId: defaultTarget, cardIdx: defaultCardIdx });
  }, [defenseTwoIdx, attackTenIdx, activeOpponents, me.cards]);
  const cancelPicker = useCallback(() => setPicker(null), []);
  const confirmPicker = useCallback(() => {
    if (!picker) return;
    const { kind, targetUserId, cardIdx } = picker;
    if (!targetUserId || cardIdx == null || cardIdx < 0) return;
    const payload = kind === "PLAY_TWO"
      ? { target_user_id: targetUserId, transfer_card_index: cardIdx }
      : { target_user_id: targetUserId, attack_card_index: cardIdx };
    sendSpecial(kind, payload);
    setPicker(null);
  }, [picker, sendSpecial]);

  // ----- countdown -----
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 100);
    return () => clearInterval(id);
  }, []);
  const remainingMs = view.turnDeadlineMs ? Math.max(0, view.turnDeadlineMs - now) : null;
  const timerPct = remainingMs == null ? 0 : Math.max(0, Math.min(100, (remainingMs / TURN_TIMEOUT_MS) * 100));

  // ----- notice auto-dismiss -----
  // The transient banner (e.g. "alice auto-stand (timeout)") clears itself
  // after 4 seconds. Re-firing while a notice is visible just resets the
  // timer to the latest event.
  useEffect(() => {
    if (!notice) return;
    const id = setTimeout(() => {
      setNotice((cur) => (cur && cur.ts === notice.ts ? null : cur));
    }, 4000);
    return () => clearTimeout(id);
  }, [notice]);

  const handFinished =
    view.phase === "PAYOUT" || view.phase === "SHOWDOWN" || view.phase === "ENDED";

  // 2026-05 v2 PART 1 — showdown clarity helpers. Compute once so
  // every player row can derive its labels from the same snapshot.
  const eligibleMaxScore = (() => {
    if (!handFinished) return null;
    const eligibles = (view.players || []).filter(
      (p) => !p.busted && !p.disqualified && !p.folded,
    );
    if (eligibles.length === 0) return null;
    return Math.max(...eligibles.map((p) => p.score || 0));
  })();
  // Runner-up score (second-best among eligibles) used to compute
  // the "score difference" line in the hand-summary card below.
  const runnerUpScore = (() => {
    if (eligibleMaxScore === null) return null;
    const scores = (view.players || [])
      .filter((p) => !p.busted && !p.disqualified && !p.folded)
      .map((p) => p.score || 0)
      .sort((a, b) => b - a);
    return scores.length >= 2 ? scores[1] : null;
  })();

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
      <div className="max-w-5xl mx-auto pb-24 sm:pb-0">
        {/* Top bar — stacks on mobile so the pill row can wrap without
            crowding the username. `flex-wrap` on the pills keeps them
            on multiple lines when the viewport narrows (≤ 430px). */}
        <div className="flex flex-col sm:flex-row items-start sm:items-center sm:justify-between gap-3 mb-6">
          <div>
            <div className="text-yellow-400/90 tracking-[0.4em] text-[10px] uppercase">TARGET — phase 11 mvp</div>
            <div className="text-zinc-100 text-lg" data-testid="my-username">{session.username}</div>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <Pill testid="phase-pill" tone="gold">{view.phase || "—"}</Pill>
            <Pill testid="sv-pill">v{view.sv}</Pill>
            <Pill tone="gold" testid="target-pill">TARGET {view.targetScore || "—"}</Pill>
            <Pill tone="gold" testid="pot-pill">POT {view.pot}</Pill>
            <Pill testid="ws-state-pill" tone={wsState === "open" ? "ok" : wsState === "error" ? "danger" : "default"}>
              WS {wsState}
            </Pill>
          </div>
        </div>

        {/* Transient engine-event banner (e.g. AUTO_STAND on timeout). */}
        {notice && (
          <div
            data-testid="event-notice"
            data-notice-kind={notice.kind}
            role="status"
            className="mb-4 rounded-md border border-amber-700/50 bg-amber-500/10 px-4 py-2 text-amber-200 text-sm flex items-center justify-between"
          >
            <span data-testid="event-notice-text">{notice.text}</span>
            <button
              data-testid="event-notice-dismiss"
              onClick={() => setNotice(null)}
              className="text-amber-300/70 hover:text-amber-200 text-xs uppercase tracking-widest ml-4"
            >
              dismiss
            </button>
          </div>
        )}

        {/* Opponents */}
        <div className="mb-8" data-testid="opponents">
          <div className="text-zinc-500 text-xs uppercase tracking-widest mb-2">Opponents</div>
          <div className="flex gap-4 flex-wrap">
            {opponents.length === 0 && (
              <div className="text-zinc-600 italic" data-testid="opponents-empty">waiting for opponents…</div>
            )}
            {opponents.map((p) => {
              const isTurn = view.currentTurnSeat === p.seat;
              const isWinner = handFinished
                && Array.isArray(view.winners)
                && view.winners.includes(p.user_id);
              const flavor = botFlavorFor(p.user_id);
              const labels = computeHandLabels(p, eligibleMaxScore, handFinished);
              // 2026-05 v2 showdown clarity: at PAYOUT/SHOWDOWN,
              // winners are ringed in gold, non-winners in subdued
              // border. During active play the current-turn seat is
              // ringed yellow as before.
              const borderCls = isWinner
                ? "border-yellow-400 shadow-[0_0_0_2px_rgba(250,204,21,0.25)]"
                : isTurn
                  ? "border-yellow-500"
                  : "border-zinc-800";
              return (
                <div
                  key={p.seat}
                  data-testid={`opponent-seat-${p.seat}`}
                  data-winner={isWinner ? "true" : "false"}
                  className={`w-full sm:min-w-[220px] sm:w-auto rounded-lg border p-4 bg-zinc-900/60 ${borderCls}`}
                >
                  <div className="flex items-center justify-between mb-2">
                    <div className="font-semibold">
                      {p.username}
                      {flavor && (
                        <span
                          data-testid={`opponent-${p.seat}-flavor`}
                          className="ml-2 text-[10px] uppercase tracking-widest text-zinc-500"
                        >
                          · {flavor}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-1">
                      {isWinner && <Pill testid={`opponent-${p.seat}-winner`} tone="gold">WINNER</Pill>}
                      {isTurn && !handFinished && <Pill tone="gold">turn</Pill>}
                      {/* Phase 11 P1 — presence pill. SITTING OUT wins
                          over OFFLINE because once the grace expired the
                          player has been formally benched for the engine. */}
                      {p.sitting_out && (
                        <Pill testid={`opponent-${p.seat}-presence`} tone="default">SITTING OUT</Pill>
                      )}
                      {!p.sitting_out && p.connected === false && (
                        <Pill testid={`opponent-${p.seat}-presence`} tone="danger">RECONNECTING…</Pill>
                      )}
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center mb-2">
                    {/* 2026-05 showdown reveal: when the server broadcast
                        includes the opponent's `cards` (SHOWDOWN/PAYOUT),
                        render face-up chips so everyone sees the final
                        hands. Pre-showdown we still only render face-
                        down placeholders keyed by card_count. */}
                    {Array.isArray(p.cards) && p.cards.length > 0 ? (
                      p.cards.map((c, i) => (
                        <CardChip
                          key={`oppcard-${p.seat}-${c.rank}-${c.suit}-${i}`}
                          card={c}
                        />
                      ))
                    ) : (
                      Array.from({ length: p.card_count }).map((_, i) => (
                        <FaceDown key={`facedown-${p.seat}-${i}`} />
                      ))
                    )}
                    {(p.card_count === 0 && !Array.isArray(p.cards)) && (
                      <span className="text-zinc-600 text-sm">no cards</span>
                    )}
                  </div>
                  <div className="flex gap-1 flex-wrap">
                    <Pill testid={`opponent-${p.seat}-cardcount`}>cards: {p.card_count}</Pill>
                    <Pill>score: {p.score}{p.soft ? " soft" : ""}</Pill>
                    {p.busted && <Pill tone="danger">BUST</Pill>}
                    {p.stood && <Pill tone="ok">STOOD</Pill>}
                    {p.folded && <Pill tone="danger">FOLD</Pill>}
                    {p.disqualified && <Pill tone="danger">DQ</Pill>}
                  </div>
                  {labels.length > 0 && (
                    <div
                      className="flex gap-1 flex-wrap mt-2"
                      data-testid={`opponent-${p.seat}-labels`}
                    >
                      {labels.map((l) => (
                        <Pill key={l.key} tone={l.tone}>{l.text}</Pill>
                      ))}
                    </div>
                  )}
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
              {handFinished && Array.isArray(view.winners) && myUserId && view.winners.includes(myUserId) && (
                <Pill testid="my-winner-pill" tone="gold">WINNER</Pill>
              )}
              {myTurn && <Pill testid="your-turn-pill" tone="gold">YOUR TURN</Pill>}
            </div>
          </div>
          {handFinished && (() => {
            const mine = (view.players || []).find((p) => p.user_id === myUserId);
            if (!mine) return null;
            const myLabels = computeHandLabels(mine, eligibleMaxScore, handFinished);
            if (myLabels.length === 0) return null;
            return (
              <div className="flex gap-1 flex-wrap mb-3" data-testid="my-labels">
                {myLabels.map((l) => (
                  <Pill key={l.key} tone={l.tone}>{l.text}</Pill>
                ))}
              </div>
            );
          })()}
          <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-5">
            {me.cards.length === 0 ? (
              <div className="text-zinc-600 italic" data-testid="my-cards-empty">no cards yet…</div>
            ) : (
              <div className="flex flex-wrap" data-testid="my-cards">
                {me.cards.map((c, i) => {
                  // Defensive: skip any null/undefined entry so the key
                  // expression (and CardChip render) cannot crash if the
                  // server ever emits a sparse array. rank+suit is unique
                  // within a single hand (single deck); the index suffix is
                  // a fallback in case of a future multi-deck shoe.
                  if (!c) return null;
                  return <CardChip key={`${c.rank}-${c.suit}-${i}`} card={c} />;
                })}
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

        {/* Actions
            2026-05 responsive: buttons flex-wrap on all sizes; on
            mobile (<sm) the whole row becomes a sticky bottom bar so
            primary actions stay thumb-reachable while the log / hand
            scroll above. On ≥sm the sticky classes neutralize and the
            original inline layout is preserved (desktop untouched). */}
        <div
          data-testid="actions-bar"
          className="flex items-center gap-2 sm:gap-3 mb-4 flex-wrap
                     fixed left-0 right-0 bottom-0 z-30 px-4 py-3 bg-black/95 border-t border-zinc-800
                     sm:static sm:px-0 sm:py-0 sm:bg-transparent sm:border-0 sm:z-auto"
        >
          <button
            data-testid="hit-btn"
            onClick={() => send("HIT")}
            disabled={!myTurn}
            className="px-4 sm:px-7 py-3 rounded-md border border-yellow-600/50 text-yellow-300 hover:bg-yellow-500/10 disabled:opacity-30 disabled:cursor-not-allowed tracking-[0.2em] sm:tracking-[0.3em] uppercase text-sm sm:text-base"
          >
            HIT
          </button>
          <button
            data-testid="stand-btn"
            onClick={() => send("STAND")}
            disabled={!myTurn}
            className="px-4 sm:px-7 py-3 rounded-md border border-zinc-600 text-zinc-200 hover:bg-zinc-200/10 disabled:opacity-30 disabled:cursor-not-allowed tracking-[0.2em] sm:tracking-[0.3em] uppercase text-sm sm:text-base"
          >
            STAND
          </button>
          {/* Special-card actions. Buttons are mounted only when the
              local player is in a state that could plausibly use them
              (DRAW + my turn + I hold the trigger card + at least one
              active opponent). They're explicitly disabled if any of
              those are missing so screen readers can still observe
              their existence in tests. */}
          {(canPlayTwo || (myTurn && defenseTwoIdx >= 0)) && (
            <button
              data-testid="play-two-btn"
              data-special="defense"
              onClick={() => openPicker("PLAY_TWO")}
              disabled={!canPlayTwo}
              title="Send a card from your hand to an opponent (uses your 2)"
              className="px-3 sm:px-5 py-3 rounded-md border border-emerald-600/60 text-emerald-300 hover:bg-emerald-500/10 disabled:opacity-30 disabled:cursor-not-allowed tracking-[0.2em] sm:tracking-[0.3em] uppercase text-sm sm:text-base"
            >
              PLAY 2
            </button>
          )}
          {(canPlayTen || (myTurn && attackTenIdx >= 0)) && (
            <button
              data-testid="play-ten-btn"
              data-special="attack"
              onClick={() => openPicker("PLAY_TEN")}
              disabled={!canPlayTen}
              title="Force an opponent to take a card from your hand (uses your 10)"
              className="px-3 sm:px-5 py-3 rounded-md border border-fuchsia-600/60 text-fuchsia-300 hover:bg-fuchsia-500/10 disabled:opacity-30 disabled:cursor-not-allowed tracking-[0.2em] sm:tracking-[0.3em] uppercase text-sm sm:text-base"
            >
              PLAY 10
            </button>
          )}
          <button
            data-testid="check-btn"
            onClick={() => send("CHECK")}
            disabled={!myBettingTurn || view.currentCallOwed > 0}
            className="px-3 sm:px-5 py-3 rounded-md border border-zinc-600 text-zinc-200 hover:bg-zinc-200/10 disabled:opacity-30 disabled:cursor-not-allowed tracking-[0.2em] sm:tracking-[0.3em] uppercase text-sm sm:text-base"
          >
            CHECK
          </button>
          <button
            data-testid="call-btn"
            onClick={() => send("CALL")}
            disabled={!myBettingTurn || view.currentCallOwed === 0}
            className="px-3 sm:px-5 py-3 rounded-md border border-zinc-600 text-zinc-200 hover:bg-zinc-200/10 disabled:opacity-30 disabled:cursor-not-allowed tracking-[0.2em] sm:tracking-[0.3em] uppercase text-sm sm:text-base"
          >
            CALL {view.currentCallOwed > 0 ? `(${view.currentCallOwed})` : ""}
          </button>
          <button
            data-testid="fold-btn"
            onClick={() => send("FOLD")}
            disabled={!myBettingTurn}
            className="px-3 sm:px-5 py-3 rounded-md border border-rose-700/60 text-rose-300 hover:bg-rose-500/10 disabled:opacity-30 disabled:cursor-not-allowed tracking-[0.2em] sm:tracking-[0.3em] uppercase text-sm sm:text-base"
          >
            FOLD
          </button>
          {handFinished && (
            <button
              data-testid="deal-again-btn"
              onClick={startPlay}
              className="px-4 sm:px-7 py-3 rounded-md border border-emerald-600/60 text-emerald-300 hover:bg-emerald-500/10 tracking-[0.2em] sm:tracking-[0.3em] uppercase text-sm sm:text-base"
            >
              Deal again
            </button>
          )}
          <span className="hidden sm:inline-block ml-auto text-zinc-500 text-xs" data-testid="status-line">{statusLine}</span>
        </div>

        {/* Special-card picker — appears only while the user is choosing
            (target, card-to-send) for PLAY_TWO / PLAY_TEN. The trigger
            card itself is filtered out of the card-to-send list per
            engine rules (PLAY_TWO_CANT_SEND_DEFENSE_ITSELF /
            PLAY_TEN_CANT_SEND_TRIGGER_ITSELF in reducer.py). */}
        {picker && (() => {
          const triggerIdx = picker.kind === "PLAY_TWO" ? defenseTwoIdx : attackTenIdx;
          const triggerCard = me.cards[triggerIdx];
          const isPlayTwo = picker.kind === "PLAY_TWO";
          // Tailwind's JIT only sees static class strings, so we pre-bake
          // the two accent variants here instead of interpolating colors.
          const styles = isPlayTwo
            ? {
                wrap: "border-emerald-700/40 bg-emerald-500/5",
                heading: "text-emerald-300",
                targetSelected: "border-emerald-500 text-emerald-200 bg-emerald-500/15",
                cardSelected: "border-emerald-500 bg-emerald-500/15",
                confirm: "border-emerald-600/60 text-emerald-200 hover:bg-emerald-500/10",
              }
            : {
                wrap: "border-fuchsia-700/40 bg-fuchsia-500/5",
                heading: "text-fuchsia-300",
                targetSelected: "border-fuchsia-500 text-fuchsia-200 bg-fuchsia-500/15",
                cardSelected: "border-fuchsia-500 bg-fuchsia-500/15",
                confirm: "border-fuchsia-600/60 text-fuchsia-200 hover:bg-fuchsia-500/10",
              };
          const sendableCards = me.cards
            .map((c, i) => ({ card: c, idx: i }))
            .filter(({ idx }) => idx !== triggerIdx);
          const canConfirm =
            !!picker.targetUserId &&
            picker.cardIdx != null &&
            picker.cardIdx >= 0 &&
            picker.cardIdx !== triggerIdx;
          return (
            <div
              data-testid={`special-picker-${isPlayTwo ? "two" : "ten"}`}
              className={`mb-4 rounded-md border ${styles.wrap} p-4`}
              role="dialog"
              aria-label={isPlayTwo ? "Play Two — pick target and card" : "Play Ten — pick target and card"}
            >
              <div className={`${styles.heading} uppercase tracking-widest text-xs mb-2`}>
                {isPlayTwo ? "Play 2 — transfer a card" : "Play 10 — force an opponent to take a card"}
              </div>
              <div className="text-zinc-400 text-xs mb-3">
                {isPlayTwo ? "Your 2" : "Your 10"}
                {triggerCard ? ` (${triggerCard.rank}${triggerCard.suit})` : ""} will be discarded.
                Pick an opponent and a card from your hand to send to them.
              </div>

              {/* Target opponent selector */}
              <div className="mb-3" data-testid="picker-targets">
                <div className="text-zinc-500 text-[10px] uppercase tracking-widest mb-1">Target</div>
                <div className="flex gap-2 flex-wrap">
                  {activeOpponents.length === 0 && (
                    <div className="text-zinc-600 text-xs italic" data-testid="picker-targets-empty">no active opponents</div>
                  )}
                  {activeOpponents.map((p) => {
                    const selected = picker.targetUserId === p.user_id;
                    return (
                      <button
                        key={p.user_id}
                        data-testid={`picker-target-${p.seat}`}
                        data-selected={selected ? "1" : "0"}
                        onClick={() => setPicker((cur) => cur && { ...cur, targetUserId: p.user_id })}
                        className={`px-3 py-1.5 rounded-md border text-xs uppercase tracking-widest ${
                          selected
                            ? styles.targetSelected
                            : "border-zinc-700 text-zinc-400 hover:bg-zinc-200/5"
                        }`}
                      >
                        {p.username}
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Card-to-send selector */}
              <div className="mb-3" data-testid="picker-cards">
                <div className="text-zinc-500 text-[10px] uppercase tracking-widest mb-1">Card to send</div>
                <div className="flex gap-2 flex-wrap">
                  {sendableCards.length === 0 && (
                    <div className="text-zinc-600 text-xs italic" data-testid="picker-cards-empty">
                      no other cards in hand — HIT to draw one first
                    </div>
                  )}
                  {sendableCards.map(({ card, idx }) => {
                    const selected = picker.cardIdx === idx;
                    const tone = SUIT_TONE[card.suit] || "text-zinc-100";
                    return (
                      <button
                        key={`pick-${card.rank}-${card.suit}-${idx}`}
                        data-testid={`picker-card-${idx}`}
                        data-selected={selected ? "1" : "0"}
                        onClick={() => setPicker((cur) => cur && { ...cur, cardIdx: idx })}
                        className={`px-3 py-1.5 rounded-md border text-sm font-mono ${
                          selected
                            ? styles.cardSelected
                            : "border-zinc-700 hover:bg-zinc-200/5"
                        } ${tone}`}
                      >
                        {rankLabel(card.rank)}{SUIT_GLYPH[card.suit] || ""}
                      </button>
                    );
                  })}
                </div>
              </div>

              <div className="flex gap-2">
                <button
                  data-testid="picker-confirm-btn"
                  onClick={confirmPicker}
                  disabled={!canConfirm}
                  className={`px-5 py-2 rounded-md border ${styles.confirm} disabled:opacity-30 disabled:cursor-not-allowed text-xs uppercase tracking-widest`}
                >
                  Confirm {picker.kind === "PLAY_TWO" ? "PLAY 2" : "PLAY 10"}
                </button>
                <button
                  data-testid="picker-cancel-btn"
                  onClick={cancelPicker}
                  className="px-5 py-2 rounded-md border border-zinc-700 text-zinc-400 hover:bg-zinc-200/5 text-xs uppercase tracking-widest"
                >
                  Cancel
                </button>
              </div>
            </div>
          );
        })()}

        {/* Winners panel — map winner user_ids → usernames via view.players,
            and show the local player's net delta (payout - total_contributed)
            during PAYOUT/SHOWDOWN. The delta uses public-view fields that
            reach every client; nothing private is leaked. */}
        {view.winners && view.winners.length > 0 && (() => {
          const idToUsername = Object.fromEntries(
            (view.players || []).map((p) => [p.user_id, p.username])
          );
          const winnerNames = view.winners.map((uid) => idToUsername[uid] || uid);
          const meRow = (view.players || []).find((p) => p.user_id === myUserId);
          const myDelta = meRow ? (meRow.payout || 0) - (meRow.total_contributed || 0) : 0;
          const iWon = !!myUserId && view.winners.includes(myUserId);
          let deltaLine = null;
          if (meRow) {
            if (myDelta > 0) {
              deltaLine = (
                <span data-testid="my-net-delta" className="text-emerald-300 font-semibold">
                  You won +{myDelta}
                </span>
              );
            } else if (myDelta < 0) {
              deltaLine = (
                <span data-testid="my-net-delta" className="text-rose-300 font-semibold">
                  You lost {myDelta}
                </span>
              );
            } else {
              deltaLine = (
                <span data-testid="my-net-delta" className="text-zinc-400">
                  Push (no change)
                </span>
              );
            }
          }
          return (
            <div className="mb-4 rounded-md border border-yellow-700/40 bg-yellow-500/5 p-4" data-testid="winners">
              <div className="text-yellow-400 uppercase tracking-widest text-sm mb-1">
                Winner{winnerNames.length > 1 ? "s" : ""}
              </div>
              <div className="text-zinc-100" data-testid="winners-names">
                {winnerNames.join(", ")}
              </div>
              {meRow && (
                <div className="mt-2 text-sm" data-testid={iWon ? "you-won" : "you-lost"}>
                  {deltaLine}
                </div>
              )}
            </div>
          );
        })()}

        {/* 2026-05 v2 PART 4 — Hand summary.
            Compact round-end recap: winner names, score difference to
            runner-up, and per-player (score · cards drawn · labels).
            Renders only at SHOWDOWN/PAYOUT so pre-showdown privacy is
            untouched. */}
        {handFinished && (view.players || []).length > 0 && (() => {
          const idToUsername = Object.fromEntries(
            (view.players || []).map((p) => [p.user_id, p.username])
          );
          const winnerNames = (view.winners || []).map((uid) => idToUsername[uid] || uid);
          const diffLine =
            eligibleMaxScore !== null && runnerUpScore !== null
              ? `${eligibleMaxScore} vs ${runnerUpScore}  (+${eligibleMaxScore - runnerUpScore})`
              : null;
          const rows = [...(view.players || [])].sort((a, b) => a.seat - b.seat);
          return (
            <div
              className="mb-4 rounded-md border border-zinc-800 bg-zinc-950/50 p-4"
              data-testid="hand-summary"
            >
              <div className="text-zinc-400 uppercase tracking-widest text-xs mb-3">
                Hand summary{view.handNumber ? ` · hand ${view.handNumber}` : ""}
              </div>
              <div className="flex flex-wrap gap-6 mb-3 text-sm">
                <div>
                  <div className="text-zinc-500 text-[10px] uppercase tracking-widest">
                    Winner{winnerNames.length > 1 ? "s" : ""}
                  </div>
                  <div className="text-yellow-300" data-testid="summary-winners">
                    {winnerNames.length ? winnerNames.join(", ") : "—"}
                  </div>
                </div>
                {diffLine && (
                  <div>
                    <div className="text-zinc-500 text-[10px] uppercase tracking-widest">
                      Score difference
                    </div>
                    <div className="text-zinc-200" data-testid="summary-score-diff">
                      {diffLine}
                    </div>
                  </div>
                )}
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2" data-testid="summary-rows">
                {rows.map((p) => {
                  const labels = computeHandLabels(p, eligibleMaxScore, handFinished);
                  const isWinner = (view.winners || []).includes(p.user_id);
                  return (
                    <div
                      key={p.seat}
                      data-testid={`summary-row-${p.seat}`}
                      className={`flex items-center justify-between gap-3 rounded border px-3 py-2 text-sm ${
                        isWinner ? "border-yellow-600/60 bg-yellow-500/5" : "border-zinc-800 bg-black/30"
                      }`}
                    >
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="text-zinc-300 truncate">{p.username}</span>
                        {isWinner && <Pill tone="gold">WIN</Pill>}
                      </div>
                      <div className="flex items-center gap-2 text-xs text-zinc-400 shrink-0">
                        <span data-testid={`summary-row-${p.seat}-score`}>score {p.score}</span>
                        <span className="text-zinc-600">·</span>
                        <span data-testid={`summary-row-${p.seat}-cards`}>{p.card_count} card{p.card_count === 1 ? "" : "s"}</span>
                        {labels.slice(0, 2).map((l) => (
                          <Pill key={l.key} tone={l.tone}>{l.text}</Pill>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })()}

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
