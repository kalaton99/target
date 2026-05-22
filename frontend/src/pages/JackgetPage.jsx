import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { apiFetch } from "@/lib/api";

const STORAGE_KEY = "target_user";
const OFFLINE_COPY = "Backend is unavailable. Start the local backend with .\\scripts\\start-backend-local.ps1, then refresh.";

function readSession() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
  } catch {
    return null;
  }
}

function reelLabel(reel) {
  return String(reel || "-");
}

function statusTone(status) {
  if (status === "settled") return "text-emerald-300 border-emerald-700/60";
  if (status === "in_progress") return "text-yellow-300 border-yellow-700/60";
  return "text-zinc-300 border-zinc-700/60";
}

export default function JackgetPage() {
  const { tableId } = useParams();
  const navigate = useNavigate();
  const [session, setSession] = useState(() => readSession());
  const [tables, setTables] = useState([]);
  const [table, setTable] = useState(null);
  const [maxPlayers, setMaxPlayers] = useState(4);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [exitConfirm, setExitConfirm] = useState(false);

  const authHeaders = useMemo(() => ({
    "Content-Type": "application/json",
    ...(session?.token ? { Authorization: `Bearer ${session.token}` } : {}),
  }), [session]);

  const request = useCallback(async (path, options = {}) => {
    setError("");
    try {
      const res = await apiFetch(path, {
        ...options,
        headers: { ...authHeaders, ...(options.headers || {}) },
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail = payload.detail || {};
        throw new Error(detail.message || detail.code || payload.message || `Request failed (${res.status})`);
      }
      return payload;
    } catch (err) {
      const message = err?.message === "Failed to fetch" ? OFFLINE_COPY : (err?.message || OFFLINE_COPY);
      setError(message);
      throw err;
    }
  }, [authHeaders]);

  const loadTables = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await request("/api/jackget/tables");
      setTables(Array.isArray(payload) ? payload : []);
    } catch {
      setTables([]);
    } finally {
      setLoading(false);
    }
  }, [request]);

  const loadTable = useCallback(async () => {
    if (!tableId) return;
    setLoading(true);
    try {
      setTable(await request(`/api/jackget/tables/${tableId}`));
    } catch {
      setTable(null);
    } finally {
      setLoading(false);
    }
  }, [request, tableId]);

  useEffect(() => {
    const current = readSession();
    setSession(current);
  }, []);

  useEffect(() => {
    if (tableId) loadTable();
    else loadTables();
  }, [tableId, loadTable, loadTables]);

  async function createTable() {
    const created = await request("/api/jackget/tables", {
      method: "POST",
      body: JSON.stringify({ max_players: Number(maxPlayers) }),
    });
    navigate(`/jackget/${created.table_id}`);
  }

  async function action(path, body = null) {
    const updated = await request(path, {
      method: "POST",
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
    setTable(updated);
    return updated;
  }

  function handleBack() {
    if (table?.status === "in_progress") {
      setExitConfirm(true);
      return;
    }
    navigate("/jackget");
  }

  if (!session?.token) {
    return (
      <div className="min-h-screen bg-black text-zinc-100 p-6 flex items-center justify-center">
        <div className="max-w-md rounded-lg border border-zinc-800 bg-zinc-950 p-6 text-center">
          <h1 className="font-display text-4xl tracking-widest">Jackget</h1>
          <p className="mt-3 text-sm text-zinc-500">Register a local demo username in the Target lobby before opening Jackget.</p>
          <Link className="mt-5 inline-flex rounded border border-yellow-700/60 px-4 py-2 text-xs uppercase tracking-widest text-yellow-300" to="/lobby">
            Open Target Lobby
          </Link>
        </div>
      </div>
    );
  }

  if (!tableId) {
    return (
      <div className="min-h-screen bg-black text-zinc-100 p-4 sm:p-6">
        <div className="mx-auto max-w-5xl">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div>
              <div className="font-luxe text-xs uppercase tracking-[0.45em] text-yellow-300">Jackget</div>
              <h1 className="mt-2 font-display text-5xl tracking-widest">Jackpot Spin Game</h1>
              <p className="mt-3 max-w-2xl text-sm leading-6 text-zinc-500">
                Separate local demo game. Each participant spins a 3-reel display exactly three times; highest demo score wins.
              </p>
            </div>
            <Link className="rounded border border-zinc-700 px-4 py-2 text-xs uppercase tracking-widest text-zinc-300 hover:bg-zinc-900" to="/games">
              Back to Games
            </Link>
          </div>
          {error && <div className="mb-4 rounded border border-rose-700/60 bg-rose-500/10 p-3 text-sm text-rose-200">{error}</div>}
          <section className="mb-6 rounded-lg border border-zinc-800 bg-zinc-950/60 p-4">
            <div className="grid gap-3 sm:grid-cols-[1fr_auto] sm:items-end">
              <label className="text-xs uppercase tracking-widest text-zinc-500">
                Table size
                <select
                  value={maxPlayers}
                  onChange={(e) => setMaxPlayers(Number(e.target.value))}
                  className="mt-2 w-full rounded border border-zinc-700 bg-zinc-900 p-2 text-zinc-100"
                >
                  <option value={2}>2 players</option>
                  <option value={3}>3 players</option>
                  <option value={4}>4 players</option>
                </select>
              </label>
              <button
                onClick={createTable}
                className="rounded border border-yellow-700/60 px-5 py-3 text-xs uppercase tracking-widest text-yellow-300 hover:bg-yellow-500/10"
              >
                Create Jackget Table
              </button>
            </div>
          </section>
          <section className="rounded-lg border border-zinc-800 bg-zinc-950/40 p-4">
            <h2 className="mb-3 text-xs uppercase tracking-widest text-zinc-500">Open Tables</h2>
            {loading && <div className="text-sm text-zinc-500">Loading Jackget tables...</div>}
            {!loading && tables.length === 0 && <div className="text-sm text-zinc-500">No Jackget tables yet.</div>}
            <div className="space-y-2">
              {tables.map((item) => (
                <Link
                  key={item.table_id}
                  to={`/jackget/${item.table_id}`}
                  className="flex items-center justify-between rounded border border-zinc-800 bg-black/30 p-3 text-sm hover:border-yellow-700/50"
                >
                  <span>{item.table_id}</span>
                  <span className="text-zinc-500">{item.seats?.length || 0}/{item.max_players} seated / {item.status}</span>
                </Link>
              ))}
            </div>
          </section>
        </div>
      </div>
    );
  }

  const humanSeat = table?.seats?.find((seat) => seat.user_id === session.user_id);
  const isMyTurn = table?.current_turn_user_id === session.user_id;
  const canStart = table && table.creator_user_id === session.user_id && ["waiting", "ready"].includes(table.status) && table.seats.length >= 2;
  const canSpin = table?.status === "in_progress" && isMyTurn && (humanSeat?.spins?.length || 0) < (table.spins_per_player || 3);
  const canAutoplay = table?.status === "in_progress" && table.seats?.some((seat) => seat.is_demo && seat.user_id === table.current_turn_user_id);

  return (
    <div className="min-h-screen bg-black text-zinc-100 p-4 sm:p-6">
      <div className="mx-auto max-w-6xl">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="font-luxe text-xs uppercase tracking-[0.45em] text-yellow-300">Jackget Table</div>
            <h1 className="mt-2 font-display text-4xl tracking-widest">{table?.table_id || "Loading"}</h1>
          </div>
          <button
            onClick={handleBack}
            className="rounded border border-zinc-700 px-4 py-2 text-xs uppercase tracking-widest text-zinc-300 hover:bg-zinc-900"
          >
            Back to Jackget
          </button>
        </div>
        {error && <div className="mb-4 rounded border border-rose-700/60 bg-rose-500/10 p-3 text-sm text-rose-200">{error}</div>}
        {loading && <div className="rounded border border-zinc-800 bg-zinc-950 p-4 text-sm text-zinc-500">Loading table...</div>}
        {table && (
          <>
            <section className="mb-5 rounded-lg border border-zinc-800 bg-zinc-950/60 p-4">
              <div className="flex flex-wrap items-center gap-3 text-sm">
                <span className={`rounded-full border px-3 py-1 uppercase tracking-widest ${statusTone(table.status)}`}>{table.status}</span>
                <span className="text-zinc-500">{table.seats.length}/{table.max_players} participants</span>
                <span className="text-zinc-500">Current turn: {table.seats.find((seat) => seat.user_id === table.current_turn_user_id)?.username || "none"}</span>
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                <button
                  onClick={() => action(`/api/jackget/tables/${table.table_id}/add-demo-opponents`)}
                  disabled={!["waiting", "ready"].includes(table.status) || table.seats.length >= table.max_players}
                  className="rounded border border-yellow-700/60 px-4 py-2 text-xs uppercase tracking-widest text-yellow-300 disabled:opacity-40"
                >
                  Add Demo Opponents
                </button>
                <button
                  onClick={() => action(`/api/jackget/tables/${table.table_id}/start`)}
                  disabled={!canStart}
                  className="rounded border border-emerald-700/60 px-4 py-2 text-xs uppercase tracking-widest text-emerald-300 disabled:opacity-40"
                >
                  Start
                </button>
                <button
                  onClick={() => action(`/api/jackget/tables/${table.table_id}/spin`)}
                  disabled={!canSpin}
                  className="rounded border border-yellow-700/60 px-4 py-2 text-xs uppercase tracking-widest text-yellow-300 disabled:opacity-40"
                >
                  Spin
                </button>
                <button
                  onClick={() => action(`/api/jackget/tables/${table.table_id}/auto-play-demo-spins`)}
                  disabled={!canAutoplay}
                  className="rounded border border-zinc-700 px-4 py-2 text-xs uppercase tracking-widest text-zinc-300 disabled:opacity-40"
                >
                  Auto-play Demo Spins
                </button>
              </div>
              <p className="mt-3 text-xs leading-5 text-zinc-500">
                Internal demo credits only. Jackget is separate from Target, Diceget, Flipget, and Tmarget.
              </p>
            </section>

            <section className="grid gap-4 md:grid-cols-2">
              {table.seats.map((seat) => (
                <div key={seat.user_id} className="rounded-lg border border-zinc-800 bg-zinc-950/50 p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="text-zinc-100">{seat.username}</div>
                      <div className="text-xs uppercase tracking-widest text-zinc-500">{seat.is_demo ? "Demo opponent" : "Player"}</div>
                    </div>
                    <div className="font-display text-3xl text-yellow-300">{seat.total_score}</div>
                  </div>
                  <div className="mt-4 space-y-2">
                    {(seat.spins || []).map((spin) => (
                      <div key={`${seat.user_id}-${spin.spin_number}`} className="rounded border border-zinc-800 bg-black/30 p-3 text-sm">
                        <div className="flex items-center justify-between">
                          <span className="text-zinc-500">Spin {spin.spin_number}</span>
                          <span className="text-yellow-300">+{spin.score}</span>
                        </div>
                        <div className="mt-2 flex gap-2">
                          {spin.reels.map((reel, idx) => (
                            <span key={`${spin.spin_number}-${idx}`} className="rounded border border-yellow-700/40 bg-zinc-900 px-3 py-2 text-zinc-100">
                              {reelLabel(reel)}
                            </span>
                          ))}
                        </div>
                      </div>
                    ))}
                    {(!seat.spins || seat.spins.length === 0) && (
                      <div className="text-sm text-zinc-600">No spins yet.</div>
                    )}
                  </div>
                </div>
              ))}
            </section>

            {table.status === "settled" && (
              <section className="mt-5 rounded-lg border border-emerald-700/50 bg-emerald-500/10 p-4">
                <div className="text-xs uppercase tracking-widest text-emerald-300">Final winner</div>
                <div className="mt-2 text-zinc-100">
                  {table.winners?.length > 1 ? "Tie: " : ""}
                  {(table.winners || []).map((winner) => table.seats.find((seat) => seat.user_id === winner)?.username || winner).join(", ")}
                </div>
              </section>
            )}
          </>
        )}
      </div>
      {exitConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 p-4">
          <div className="max-w-sm rounded-lg border border-rose-700/50 bg-zinc-950 p-5">
            <div className="text-xs uppercase tracking-widest text-rose-300">Leave active Jackget table?</div>
            <p className="mt-3 text-sm leading-6 text-zinc-300">
              Leaving during an active game may count as a loss or forfeit and may lose the reserved internal demo credits/stake.
            </p>
            <div className="mt-5 flex justify-end gap-3">
              <button onClick={() => setExitConfirm(false)} className="rounded border border-zinc-700 px-4 py-2 text-xs uppercase tracking-widest text-zinc-300">
                Stay
              </button>
              <button onClick={() => navigate("/jackget")} className="rounded border border-rose-700/60 px-4 py-2 text-xs uppercase tracking-widest text-rose-200">
                Leave
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
