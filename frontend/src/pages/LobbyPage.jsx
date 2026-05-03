import React, { useCallback, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

// Phase 11 P2 — Lobby. Real users register with a username, see a list of
// open tables, create a table, join one, and start the hand. After START,
// the page navigates to /play/{tableId} which connects via WebSocket.
//
// localStorage contract:
//   key "target_user" → JSON {user_id, username, token}
//   - written here on /api/v2/lobby/auth success
//   - read by PlayPage in lobby mode
//   - cleared by PlayPage if /me returns 401 (token expired)

const TARGETS = [30, 50, 100, 250];

const REDIRECT_MESSAGES = {
  session_expired: "Your session expired. Please sign in again.",
  signin_required: "Please sign in to continue.",
};

function LS() {
  const get = () => {
    try {
      return JSON.parse(localStorage.getItem("target_user") || "null");
    } catch {
      return null;
    }
  };
  const set = (u) => localStorage.setItem("target_user", JSON.stringify(u));
  const clear = () => localStorage.removeItem("target_user");
  return { get, set, clear };
}

export default function LobbyPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const ls = LS();
  const [user, setUser] = useState(ls.get());
  const [username, setUsername] = useState("");
  const [tables, setTables] = useState([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const redirectMsg = REDIRECT_MESSAGES[searchParams.get("msg")] || "";
  // create-form state
  const [name, setName] = useState("My Table");
  const [target, setTarget] = useState(30);
  const [stake, setStake] = useState(100);
  // 2026-05: max/min are server-derived from target_score (locked-rules
  // migration). The form no longer collects them.
  const [botCount, setBotCount] = useState(0);
  // /api/v2/lobby/config tells us whether to render the dev-only bots
  // input. In production deploys allow_bots=false and the control is
  // hidden entirely so users can't even attempt to spawn one.
  const [config, setConfig] = useState({
    allow_bots: false,
    bot_count_max: 0,
    bot_count_max_by_target: { 30: 0, 50: 0, 100: 0, 250: 0 },
    table_seats_by_target: { 30: 4, 50: 4, 100: 5, 250: 5 },
  });
  useEffect(() => {
    fetch("/api/v2/lobby/config")
      .then((r) => r.json())
      .then((d) => setConfig(d))
      .catch(() => {});
  }, []);
  // Per-target bot cap (seats - 1). 4-seat target → 3 bots; 5-seat → 4.
  // Falls back to the global `bot_count_max` for older backends that
  // don't yet publish `bot_count_max_by_target`.
  const perTargetBotMax =
    config.bot_count_max_by_target?.[Number(target)]
    ?? config.bot_count_max
    ?? 0;
  // If the user switches target downward (e.g. 100 → 30) while bots
  // were set to 4, clamp the input so we don't submit an invalid value.
  useEffect(() => {
    if (Number(botCount) > perTargetBotMax) {
      setBotCount(String(perTargetBotMax));
    }
  }, [perTargetBotMax, botCount]);

  const headers = useCallback(
    () => (user ? { Authorization: `Bearer ${user.token}` } : {}),
    [user],
  );

  const refreshTables = useCallback(async () => {
    setLoading(true);
    setErr("");
    try {
      const r = await fetch("/api/v2/lobby/tables");
      const data = await r.json();
      setTables(Array.isArray(data) ? data : []);
    } catch (e) {
      setErr("Failed to load tables");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refreshTables();
    const id = setInterval(refreshTables, 4000);
    return () => clearInterval(id);
  }, [refreshTables]);

  const doRegister = async () => {
    setErr("");
    if (!username || username.length < 2) {
      setErr("username must be 2–16 chars");
      return;
    }
    try {
      const r = await fetch("/api/v2/lobby/auth", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username }),
      });
      if (!r.ok) {
        setErr("auth failed");
        return;
      }
      const data = await r.json();
      ls.set(data);
      setUser(data);
    } catch (e) {
      setErr(String(e));
    }
  };

  const doLogout = () => {
    ls.clear();
    setUser(null);
  };

  const doCreate = async () => {
    setErr("");
    try {
      const body = {
        name,
        target_score: Number(target),
        stake: Number(stake),
      };
      if (config.allow_bots && Number(botCount) > 0) {
        body.bot_count = Math.max(0, Math.min(Number(botCount), perTargetBotMax));
      }
      const r = await fetch("/api/v2/lobby/tables", {
        method: "POST",
        headers: { ...headers(), "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        const t = await r.text();
        setErr("create failed: " + t);
        return;
      }
      await refreshTables();
    } catch (e) {
      setErr(String(e));
    }
  };

  const doJoin = async (tid) => {
    setErr("");
    try {
      const r = await fetch(`/api/v2/lobby/tables/${tid}/join`, {
        method: "POST",
        headers: headers(),
      });
      if (!r.ok) {
        const t = await r.text();
        setErr("join failed: " + t);
        return;
      }
      await refreshTables();
    } catch (e) {
      setErr(String(e));
    }
  };

  const doStart = async (tid) => {
    setErr("");
    try {
      const r = await fetch(`/api/v2/lobby/tables/${tid}/start`, {
        method: "POST",
        headers: headers(),
      });
      if (!r.ok) {
        const t = await r.text();
        setErr("start failed: " + t);
        return;
      }
      // Jump into the play view with the existing token
      navigate(`/play/${tid}`);
    } catch (e) {
      setErr(String(e));
    }
  };

  const doEnter = (tid) => navigate(`/play/${tid}`);

  // ---------------- render ----------------

  if (!user) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-black text-zinc-100 p-6">
        <div className="max-w-md w-full">
          <div className="text-yellow-400/90 tracking-[0.5em] text-xs uppercase mb-3 text-center">TARGET</div>
          <div className="text-3xl font-bold tracking-widest text-zinc-100 mb-2 text-center">
            <span className="text-yellow-400">▲</span> lobby
          </div>
          <p className="text-zinc-500 text-sm mb-8 text-center">Pick a guest username to enter.</p>
          {redirectMsg && (
            <div
              data-testid="redirect-msg"
              className="mb-4 rounded border border-yellow-700/40 bg-yellow-500/5 text-yellow-300 text-xs px-3 py-2 text-center"
            >
              {redirectMsg}
            </div>
          )}
          <input
            data-testid="username-input"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="username"
            className="w-full mb-3 bg-zinc-900 border border-zinc-700 rounded-md p-3 text-zinc-100"
          />
          <button
            data-testid="login-btn"
            onClick={doRegister}
            className="w-full px-7 py-3 rounded-md border border-yellow-600/60 text-yellow-300 hover:bg-yellow-500/10 tracking-[0.3em] uppercase"
          >
            Enter
          </button>
          {err && <div data-testid="auth-err" className="text-rose-400 mt-3 text-sm">{err}</div>}
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-black text-zinc-100 p-6">
      <div className="max-w-4xl mx-auto">
        {redirectMsg && (
          <div
            data-testid="redirect-msg"
            className="mb-4 rounded border border-yellow-700/40 bg-yellow-500/5 text-yellow-300 text-xs px-3 py-2 text-center"
          >
            {redirectMsg}
          </div>
        )}
        {/* Top bar */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <div className="text-yellow-400/90 tracking-[0.4em] text-[10px] uppercase">TARGET — lobby</div>
            <div className="text-zinc-100 text-lg" data-testid="lobby-username">{user.username}</div>
          </div>
          <button
            data-testid="logout-btn"
            onClick={doLogout}
            className="px-4 py-2 rounded-md border border-zinc-700 text-zinc-400 hover:bg-zinc-800 text-xs uppercase tracking-widest"
          >
            Logout
          </button>
        </div>

        {/* Create table */}
        <div className="rounded-lg border border-zinc-800 p-4 mb-6 bg-zinc-950/40">
          <div className="text-zinc-400 text-xs uppercase tracking-widest mb-3">Create table</div>
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mb-3">
            <input
              data-testid="table-name-input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="name"
              className="bg-zinc-900 border border-zinc-700 rounded p-2 col-span-2"
            />
            <select
              data-testid="target-select"
              value={target}
              onChange={(e) => setTarget(Number(e.target.value))}
              className="bg-zinc-900 border border-zinc-700 rounded p-2"
            >
              {/*
                Hardcoded options (instead of TARGETS.map(...)) to avoid the
                Emergent dev-tool wrapping the dynamic `{t}` expression in a
                <span style={{display:"contents"}} />, which is invalid HTML
                inside <option> and produces a hydration warning. Static
                children = no expression to wrap.
              */}
              <option value={30}>target 30</option>
              <option value={50}>target 50</option>
              <option value={100}>target 100</option>
              <option value={250}>target 250</option>
            </select>
            <input
              data-testid="stake-input"
              type="number"
              min={0}
              value={stake}
              onChange={(e) => setStake(e.target.value)}
              className="bg-zinc-900 border border-zinc-700 rounded p-2"
              placeholder="stake"
            />
            {/* 2026-05: derived seat count is shown read-only beside the
                target select (locked-rules migration). max/min inputs are
                gone — server derives `max_players` from `target_score`. */}
            <div
              data-testid="seats-derived"
              className="bg-zinc-900 border border-zinc-700 rounded p-2 text-zinc-500 text-sm flex items-center"
            >
              {(config.table_seats_by_target?.[Number(target)] ?? "—")} seats
            </div>
            {config.allow_bots && (
              <input
                data-testid="bot-count-input"
                type="number"
                min={0}
                max={perTargetBotMax}
                value={botCount}
                onChange={(e) => setBotCount(e.target.value)}
                className="bg-zinc-900 border border-zinc-700 rounded p-2"
                placeholder="bots"
                title={`Dev: 0–${perTargetBotMax} CPU bots (seats − 1)`}
              />
            )}
          </div>
          <button
            data-testid="create-table-btn"
            onClick={doCreate}
            className="px-5 py-2 rounded-md border border-yellow-600/60 text-yellow-300 hover:bg-yellow-500/10 tracking-[0.3em] uppercase text-sm"
          >
            Create
          </button>
        </div>

        {/* Tables list */}
        <div className="flex items-center justify-between mb-3">
          <div className="text-zinc-400 text-xs uppercase tracking-widest">Open tables</div>
          <button
            data-testid="refresh-tables-btn"
            onClick={refreshTables}
            className="text-xs text-zinc-500 hover:text-zinc-300 uppercase tracking-widest"
          >
            {loading ? "…" : "Refresh"}
          </button>
        </div>
        <div className="space-y-2" data-testid="tables-list">
          {tables.length === 0 && (
            <div className="text-zinc-600 italic" data-testid="tables-empty">No tables yet — create one above.</div>
          )}
          {tables.map((t) => {
            const seated = t.seats.some((s) => s.user_id === user.user_id);
            const isCreator = t.creator_user_id === user.user_id;
            const full = t.seats.length >= t.max_players;
            return (
              <div
                key={t.table_id}
                data-testid={`table-row-${t.table_id}`}
                className="rounded-md border border-zinc-800 bg-zinc-950/60 p-3 flex items-center gap-3 flex-wrap"
              >
                <div className="flex-1 min-w-[180px]">
                  <div className="text-zinc-100 font-semibold">{t.name}</div>
                  <div className="text-zinc-500 text-xs">
                    target {t.target_score} · stake {t.stake} · {t.seats.length}/{t.max_players} seated · status {t.status}
                  </div>
                  <div className="text-zinc-600 text-xs mt-1">
                    {t.seats.map((s) => s.username).join(", ")}
                  </div>
                </div>
                {!seated && !full && (
                  <button
                    data-testid={`join-btn-${t.table_id}`}
                    onClick={() => doJoin(t.table_id)}
                    className="px-4 py-2 rounded border border-yellow-600/60 text-yellow-300 hover:bg-yellow-500/10 text-xs uppercase tracking-widest"
                  >
                    Join
                  </button>
                )}
                {seated && (
                  <button
                    data-testid={`enter-btn-${t.table_id}`}
                    onClick={() => doEnter(t.table_id)}
                    className="px-4 py-2 rounded border border-zinc-600 text-zinc-200 hover:bg-zinc-800 text-xs uppercase tracking-widest"
                  >
                    Enter
                  </button>
                )}
                {seated && isCreator && t.status === "LOBBY" && (
                  <button
                    data-testid={`start-btn-${t.table_id}`}
                    onClick={() => doStart(t.table_id)}
                    className="px-4 py-2 rounded border border-emerald-600/60 text-emerald-300 hover:bg-emerald-500/10 text-xs uppercase tracking-widest"
                  >
                    Start
                  </button>
                )}
              </div>
            );
          })}
        </div>

        {err && <div data-testid="lobby-err" className="text-rose-400 mt-4 text-sm">{err}</div>}
      </div>
    </div>
  );
}
