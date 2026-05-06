import React, { useCallback, useEffect, useRef, useState } from "react";
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

const TARGETS = [30, 50, 75, 100];

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
  // 2026-05 v2 — Emergent Google OAuth callback. After Google sign-in
  // the user is redirected to `/lobby#session_id=...`. We exchange the
  // session_id with the backend, persist `target_user` (jwt + name) so
  // the rest of this page works unchanged, and strip the fragment.
  //
  // StrictMode-safe: the playbook explicitly calls out that
  // useEffect double-fires under React.StrictMode, which causes the
  // single-use Emergent session_id to be POSTed twice — the second
  // call comes back 401 OAUTH_EXCHANGE_FAILED and races the first
  // (successful) call's setState. We use a `useRef` guard set
  // synchronously at the start of the effect so the second
  // invocation is a no-op, and we read the hash ONCE here (not in
  // render) so the guard's reset between effect-runs doesn't matter.
  const oauthProcessed = useRef(false);
  const initialHash = useRef(typeof window !== "undefined" ? window.location.hash : "");
  const [oauthBusy, setOauthBusy] = useState(
    initialHash.current.startsWith("#session_id="),
  );
  const [oauthErr, setOauthErr] = useState("");
  useEffect(() => {
    if (oauthProcessed.current) return;
    const hash = initialHash.current || "";
    if (!hash.startsWith("#session_id=")) return;
    const sessionId = hash.slice("#session_id=".length);
    if (!sessionId) return;
    oauthProcessed.current = true;
    setOauthBusy(true);
    setOauthErr("");
    // Strip the session_id from the URL immediately so a refresh /
    // back-button never re-submits it (and so a curious user can't
    // copy it from the address bar).
    try {
      window.history.replaceState({}, document.title,
        window.location.pathname + window.location.search);
    } catch (_) { /* noop */ }
    (async () => {
      try {
        const r = await fetch("/api/v2/auth/google/session", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({ session_id: sessionId }),
        });
        if (!r.ok) {
          let detail = "";
          try { detail = (await r.json())?.detail || ""; } catch (_) {}
          // 2026-05 v3 demo polish: show a friendly message; keep the
          // technical detail only if helpful for debugging in dev.
          const friendly =
            "Google sign-in didn't complete. Please try again, or use guest sign-in below.";
          setOauthErr(
            detail && r.status >= 500
              ? `${friendly} (server error: ${detail})`
              : friendly,
          );
          return;
        }
        const data = await r.json();
        // Persist as `target_user` so the rest of LobbyPage + PlayPage
        // work without touching their bearer-JWT plumbing.
        const stored = {
          user_id: data.user.user_id,
          username: data.user.name,
          token: data.jwt,
          email: data.user.email,
          picture: data.user.picture,
          auth_provider: "google",
        };
        ls.set(stored);
        setUser(stored);
      } catch (e) {
        setOauthErr(
          "Google sign-in didn't complete. Please try again, or use guest sign-in below.",
        );
      } finally {
        setOauthBusy(false);
      }
    })();
    // We deliberately don't add `ls` as a dep — `LS()` returns a fresh
    // closure each render and the effect must run exactly once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Refresh-resilience: if `target_user` isn't in localStorage but the
  // server still has a valid cookie session, /me will tell us who we
  // are and we can mint a new bearer in-memory by re-exchanging? No —
  // /me alone doesn't issue a JWT. Instead, on cold load with no
  // localStorage we just call /me to render the username; if the user
  // tries an action that needs a bearer, we'll redirect them to log in.
  //
  // CRITICAL (per Emergent OAuth playbook): skip this check entirely
  // when we're handling an OAuth callback (`#session_id=...` in the
  // URL). Otherwise the /me call races the session exchange — /me
  // returns 401 before the cookie is set, and we can clobber state.
  useEffect(() => {
    if (user) return;
    if (initialHash.current.startsWith("#session_id=")) return;
    let alive = true;
    (async () => {
      try {
        const r = await fetch("/api/v2/auth/me", { credentials: "include" });
        if (!alive || !r.ok) return;
        const me = await r.json();
        // We have a session cookie but no JWT — flag the user so the
        // header shows their name. They'll need to re-sign-in to mint
        // a JWT for table actions (rare; covers the case where
        // localStorage was cleared but the cookie survived).
        setUser({
          user_id: me.user_id,
          username: me.name,
          email: me.email,
          picture: me.picture,
          auth_provider: me.auth_provider,
          token: null,
        });
      } catch (_) {}
    })();
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  // create-form state
  const [name, setName] = useState("My Table");
  const [target, setTarget] = useState(30);
  const [stake, setStake] = useState(100);
  // 2026-05 v3 — How-to-play overlay (X1)
  const [howToPlayOpen, setHowToPlayOpen] = useState(false);
  // 2026-05: max/min are server-derived from target_score (locked-rules
  // migration). The form no longer collects them.
  const [botCount, setBotCount] = useState(0);
  // /api/v2/lobby/config tells us whether to render the dev-only bots
  // input. In production deploys allow_bots=false and the control is
  // hidden entirely so users can't even attempt to spawn one.
  const [config, setConfig] = useState({
    allow_bots: false,
    bot_count_max: 0,
    bot_count_max_by_target: { 30: 0, 50: 0, 75: 0, 100: 0 },
    table_seats_by_target: { 30: 4, 50: 4, 75: 5, 100: 5 },
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

  const doLogout = async () => {
    // 2026-05 v2 — also call backend so the cookie session is invalidated
    // and a refresh after logout doesn't re-auth from a stale cookie.
    try {
      await fetch("/api/v2/auth/logout", { method: "POST", credentials: "include" });
    } catch (_) { /* best effort */ }
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
          <p className="text-zinc-400 text-sm mb-2 text-center">
            A live multi-round card game. Get the closest score to the target without going over.
          </p>
          <p className="text-zinc-600 text-xs mb-8 text-center">
            Sign in to start a hand. Free to play, no download.
          </p>
          {redirectMsg && (
            <div
              data-testid="redirect-msg"
              className="mb-4 rounded border border-yellow-700/40 bg-yellow-500/5 text-yellow-300 text-xs px-3 py-2 text-center"
            >
              {redirectMsg}
            </div>
          )}
          {/* 2026-05 v2 — Emergent-managed Google OAuth.
              Redirect URL is `${window.location.origin}/lobby` so the
              user lands back here with `#session_id=...` and the
              top-level effect handles the exchange. */}
          <button
            data-testid="google-signin-btn"
            disabled={oauthBusy}
            onClick={() => {
              const redirect = `${window.location.origin}/lobby`;
              window.location.href =
                `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirect)}`;
            }}
            className="w-full mb-3 px-7 py-3 rounded-md border border-emerald-600/60 text-emerald-300 hover:bg-emerald-500/10 tracking-[0.3em] uppercase disabled:opacity-30"
          >
            {oauthBusy ? "Signing you in…" : "Continue with Google"}
          </button>
          {oauthErr && <div data-testid="oauth-err" className="text-rose-400 mb-3 text-xs text-center">{oauthErr}</div>}
          <div className="text-zinc-700 text-[10px] tracking-[0.3em] uppercase text-center my-4">— or —</div>
          <p className="text-zinc-600 text-xs mb-2 text-center">
            Quick play — no email needed.
          </p>
          <input
            data-testid="username-input"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="Choose a username (2–16 chars)"
            className="w-full mb-3 bg-zinc-900 border border-zinc-700 rounded-md p-3 text-zinc-100"
          />
          <button
            data-testid="login-btn"
            onClick={doRegister}
            className="w-full px-7 py-3 rounded-md border border-yellow-600/60 text-yellow-300 hover:bg-yellow-500/10 tracking-[0.3em] uppercase"
          >
            Enter as guest
          </button>
          {err && <div data-testid="auth-err" className="text-rose-400 mt-3 text-sm">{err}</div>}
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-black text-zinc-100 p-4 sm:p-6">
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
          <div className="flex items-center gap-2">
            <button
              data-testid="how-to-play-btn"
              onClick={() => setHowToPlayOpen(true)}
              title="How to play"
              className="px-3 py-2 rounded-md border border-yellow-700/60 text-yellow-300 hover:bg-yellow-500/10 text-xs uppercase tracking-widest"
            >
              How to play
            </button>
            <button
              data-testid="logout-btn"
              onClick={doLogout}
              className="px-4 py-2 rounded-md border border-zinc-700 text-zinc-400 hover:bg-zinc-800 text-xs uppercase tracking-widest"
            >
              Logout
            </button>
          </div>
        </div>

        {/* Create table */}
        <div className="rounded-lg border border-zinc-800 p-4 mb-6 bg-zinc-950/40">
          <div className="text-zinc-400 text-xs uppercase tracking-widest mb-3">Create table</div>
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-x-3 gap-y-2 mb-3">
            <div className="col-span-2 flex flex-col">
              <label className="text-zinc-500 text-[10px] uppercase tracking-widest mb-1">Table name</label>
              <input
                data-testid="table-name-input"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Friday night"
                className="bg-zinc-900 border border-zinc-700 rounded p-2"
              />
            </div>
            <div className="flex flex-col">
              <label className="text-zinc-500 text-[10px] uppercase tracking-widest mb-1">Target score</label>
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
                <option value={30}>30 — fast (4 seats)</option>
                <option value={50}>50 — fast (4 seats)</option>
                <option value={75}>75 — long (5 seats)</option>
                <option value={100}>100 — long (5 seats)</option>
              </select>
            </div>
            <div className="flex flex-col">
              <label className="text-zinc-500 text-[10px] uppercase tracking-widest mb-1">Stake (per ante)</label>
              <input
                data-testid="stake-input"
                type="number"
                min={0}
                value={stake}
                onChange={(e) => setStake(e.target.value)}
                className="bg-zinc-900 border border-zinc-700 rounded p-2"
                placeholder="e.g. 100"
              />
            </div>
            {/* 2026-05: derived seat count is shown read-only beside the
                target select (locked-rules migration). max/min inputs are
                gone — server derives `max_players` from `target_score`. */}
            <div className="flex flex-col">
              <label className="text-zinc-500 text-[10px] uppercase tracking-widest mb-1">Seats</label>
              <div
                data-testid="seats-derived"
                className="bg-zinc-900 border border-zinc-700 rounded p-2 text-zinc-500 text-sm flex items-center"
              >
                {(config.table_seats_by_target?.[Number(target)] ?? "—")} seats
              </div>
            </div>
            {config.allow_bots && (
              <div className="flex flex-col">
                <label className="text-zinc-500 text-[10px] uppercase tracking-widest mb-1">CPU bots (dev)</label>
                <input
                  data-testid="bot-count-input"
                  type="number"
                  min={0}
                  max={perTargetBotMax}
                  value={botCount}
                  onChange={(e) => setBotCount(e.target.value)}
                  className="bg-zinc-900 border border-zinc-700 rounded p-2"
                  placeholder={`0–${perTargetBotMax}`}
                  title={`Dev: 0–${perTargetBotMax} CPU bots (seats − 1)`}
                />
              </div>
            )}
          </div>
          <p className="text-zinc-500 text-xs mb-3" data-testid="target-hint">
            {Number(target) <= 50
              ? `Target ${target}: fast 4-seat table. Starts when 2+ players are seated.`
              : `Target ${target}: longer 5-seat table. Starts when 3+ players are seated.`}
          </p>
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

        {/* 2026-05 v3 — How-to-play overlay (X1).
            Three-card explainer: goal, hand flow, fairness. Pure copy,
            no engine ties. */}
        {howToPlayOpen && (
          <div
            data-testid="how-to-play-modal"
            role="dialog"
            aria-modal="true"
            className="fixed inset-0 z-40 flex items-center justify-center p-4 bg-black/80"
            onClick={() => setHowToPlayOpen(false)}
          >
            <div
              className="max-w-3xl w-full rounded-lg border border-yellow-700/40 bg-zinc-950 p-5 max-h-[90vh] overflow-auto"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between mb-4">
                <div className="text-yellow-300 uppercase tracking-widest text-xs">How to play TARGET</div>
                <button
                  data-testid="how-to-play-close"
                  type="button"
                  onClick={() => setHowToPlayOpen(false)}
                  className="text-zinc-500 hover:text-zinc-200 text-xs uppercase tracking-widest"
                >
                  Close
                </button>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div className="rounded border border-zinc-800 bg-black/40 p-4">
                  <div className="text-yellow-400 text-base font-semibold mb-2">1 · Goal</div>
                  <p className="text-zinc-300 text-sm leading-relaxed">
                    Get your card score as close to the table's <span className="text-yellow-300">target</span> as you can — without going over.
                    Closest score wins the pot at the end of the hand.
                  </p>
                </div>
                <div className="rounded border border-zinc-800 bg-black/40 p-4">
                  <div className="text-yellow-400 text-base font-semibold mb-2">2 · One hand</div>
                  <p className="text-zinc-300 text-sm leading-relaxed">
                    Each hand has 5 phases:
                  </p>
                  <ol className="text-zinc-400 text-xs leading-5 mt-2 list-decimal list-inside">
                    <li>Round 1 — bet, call or check</li>
                    <li>Draw 1 — hit (take a card) or stand</li>
                    <li>Round 2 — bet again</li>
                    <li>Draw 2 — last chance to draw</li>
                    <li>Round 3 — final bets, then showdown</li>
                  </ol>
                </div>
                <div className="rounded border border-zinc-800 bg-black/40 p-4">
                  <div className="text-emerald-400 text-base font-semibold mb-2">3 · Provably fair</div>
                  <p className="text-zinc-300 text-sm leading-relaxed">
                    Every shuffle is committed (locked) before the deal and revealed at PAYOUT.
                    Click <span className="text-emerald-300">Verify result</span> on the play
                    screen to recompute the deck yourself with SHA-256 — no trust required.
                  </p>
                </div>
              </div>
              <p className="text-zinc-500 text-xs mt-4 text-center">
                Cards: 2–10 score face value, A=1, J/Q/K=10. Drawing a Joker disqualifies you for the hand.
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
