import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

const SIDES = ["heads", "tails"];

function storedUser() {
  try {
    return JSON.parse(localStorage.getItem("target_user") || "null");
  } catch {
    return null;
  }
}

function authHeaders() {
  const user = storedUser();
  return {
    "Content-Type": "application/json",
    ...(user?.token ? { Authorization: `Bearer ${user.token}` } : {}),
  };
}

async function api(path, options = {}) {
  const response = await fetch(`/api/flipget${path}`, {
    ...options,
    headers: { ...authHeaders(), ...(options.headers || {}) },
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data?.detail;
    throw new Error(detail?.code || detail || `HTTP_${response.status}`);
  }
  return data;
}

function Coin({ result, status }) {
  const label = status === "flipping" ? "Flipping" : result || "Ready";
  return (
    <div className="flex aspect-square w-40 items-center justify-center rounded-full border border-yellow-500/60 bg-zinc-950 text-center font-display text-3xl uppercase tracking-widest text-yellow-200">
      {label}
    </div>
  );
}

function Seat({ seat }) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-5">
      <div className="flex items-center justify-between gap-3">
        <div className="font-display text-2xl tracking-widest">{seat?.username || seat?.user_id || "Open"}</div>
        <div className="text-xs uppercase tracking-widest text-zinc-500">Seat {(seat?.seat_index ?? 0) + 1}</div>
      </div>
      <div className="mt-4 text-sm uppercase tracking-widest text-zinc-400">
        Side: {seat?.side || "-"}
      </div>
      <div className="mt-2 text-sm uppercase tracking-widest text-zinc-400">
        {seat?.ready ? "Ready" : "Not ready"}
      </div>
    </div>
  );
}

export default function FlipgetPage() {
  const { tableId } = useParams();
  const navigate = useNavigate();
  const [tables, setTables] = useState([]);
  const [table, setTable] = useState(null);
  const [stake, setStake] = useState(100);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const user = storedUser();

  const mySeat = useMemo(
    () => table?.seats?.find((seat) => seat.user_id === user?.user_id),
    [table, user?.user_id],
  );
  const takenSides = useMemo(
    () => new Set((table?.seats || []).map((seat) => seat.side).filter(Boolean)),
    [table],
  );
  const canFlip = Boolean(
    table?.status === "ready"
      && table?.seats?.length === 2
      && table.seats.every((seat) => seat.ready && seat.side),
  );

  const refresh = useCallback(async () => {
    if (tableId) {
      setTable(await api(`/tables/${tableId}`));
    } else {
      setTables(await api("/tables"));
    }
  }, [tableId]);

  useEffect(() => {
    refresh().catch((err) => setError(err.message));
    const timer = setInterval(() => refresh().catch(() => {}), 2500);
    return () => clearInterval(timer);
  }, [refresh]);

  async function run(action) {
    setBusy(true);
    setError("");
    try {
      const next = await action();
      if (next?.table_id || next?.id) setTable(next);
      return next;
    } catch (err) {
      setError(err.message);
      return null;
    } finally {
      setBusy(false);
    }
  }

  if (!user?.token) {
    return (
      <div className="min-h-screen bg-black px-4 py-10 text-zinc-100">
        <div className="mx-auto max-w-3xl">
          <Link className="btn-ghost" to="/games">Back</Link>
          <h1 className="mt-6 font-display text-5xl tracking-widest">Flipget</h1>
          <p className="mt-4 text-zinc-400">Sign in through the Target lobby before playing Flipget.</p>
          <Link className="btn-primary mt-6 inline-flex" to="/lobby">Sign in</Link>
        </div>
      </div>
    );
  }

  if (!tableId) {
    return (
      <div className="min-h-screen bg-black px-4 py-8 text-zinc-100">
        <div className="mx-auto max-w-6xl">
          <div className="flex items-center justify-between gap-4">
            <div>
              <div className="font-luxe text-xs uppercase tracking-[0.45em] text-yellow-300">Game module</div>
              <h1 className="mt-2 font-display text-5xl tracking-widest">Flipget</h1>
            </div>
            <Link className="btn-ghost" to="/games">Products</Link>
          </div>
          <div className="mt-8 flex flex-wrap items-end gap-3">
            <label className="text-xs uppercase tracking-widest text-zinc-500">
              Stake
              <input
                value={stake}
                onChange={(event) => setStake(Number(event.target.value) || 0)}
                className="mt-2 block rounded border border-zinc-700 bg-zinc-950 px-3 py-2 text-zinc-100"
                type="number"
                min="0"
              />
            </label>
            <button
              className="btn-primary"
              disabled={busy}
              onClick={() => run(async () => {
                const created = await api("/tables", {
                  method: "POST",
                  body: JSON.stringify({ stake_amount: stake, max_players: 2 }),
                });
                navigate(`/flipget/${created.table_id}`);
              })}
            >
              Create Table
            </button>
          </div>
          {error && <div className="mt-4 text-sm text-rose-300">{error}</div>}
          <div className="mt-10 grid gap-3">
            {tables.map((item) => (
              <div key={item.table_id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-zinc-800 bg-zinc-950 p-4">
                <div>
                  <div className="font-display text-2xl tracking-widest">Flipget</div>
                  <div className="text-sm text-zinc-500">{item.seats.length}/2 seats / {item.status}</div>
                </div>
                <div className="flex gap-2">
                  <button className="btn-secondary" disabled={busy || item.status !== "waiting"} onClick={() => run(async () => {
                    await api(`/tables/${item.table_id}/join`, { method: "POST" });
                    navigate(`/flipget/${item.table_id}`);
                  })}>Join</button>
                  <Link className="btn-ghost" to={`/flipget/${item.table_id}`}>View</Link>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-black px-4 py-8 text-zinc-100">
      <div className="mx-auto max-w-6xl">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="font-luxe text-xs uppercase tracking-[0.45em] text-yellow-300">Flipget Table</div>
            <h1 className="mt-2 font-display text-5xl tracking-widest">{table?.status || "Loading"}</h1>
          </div>
          <Link className="btn-ghost" to="/flipget">Lobby</Link>
        </div>
        {error && <div className="mt-4 text-sm text-rose-300">{error}</div>}
        <div className="mt-8 grid gap-6 lg:grid-cols-[0.8fr_1.2fr]">
          <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-5">
            <div className="flex justify-center">
              <Coin result={table?.round?.result} status={table?.status} />
            </div>
            <div className="mt-6 flex flex-wrap justify-center gap-3">
              {SIDES.map((side) => {
                const disabled = busy
                  || !mySeat
                  || mySeat.ready
                  || ["flipping", "settled"].includes(table?.status)
                  || (takenSides.has(side) && mySeat.side !== side);
                return (
                  <button
                    key={side}
                    className={mySeat?.side === side ? "btn-primary" : "btn-secondary"}
                    disabled={disabled}
                    onClick={() => run(() => api(`/tables/${table.table_id}/choose-side`, {
                      method: "POST",
                      body: JSON.stringify({ side }),
                    }))}
                  >
                    {side}
                  </button>
                );
              })}
              <button className="btn-primary" disabled={busy || !mySeat?.side || mySeat.ready || ["flipping", "settled"].includes(table?.status)} onClick={() => run(() => api(`/tables/${table.table_id}/ready`, { method: "POST" }))}>Ready</button>
              <button className="btn-secondary" disabled={busy || !canFlip} onClick={() => run(() => api(`/tables/${table.table_id}/flip`, { method: "POST" }))}>Flip</button>
            </div>
          </div>
          <div className="grid gap-4">
            <Seat seat={table?.seats?.[0]} />
            <Seat seat={table?.seats?.[1]} />
            {table?.status === "waiting" && (
              <button className="btn-ghost" disabled={busy} onClick={() => run(async () => {
                await api(`/tables/${table.table_id}/leave`, { method: "POST" });
                navigate("/flipget");
              })}>Leave</button>
            )}
          </div>
        </div>
        {table?.status === "settled" && (
          <div className="mt-8 rounded-lg border border-yellow-700/40 bg-yellow-500/10 p-5">
            <div className="text-xs uppercase tracking-widest text-yellow-300">Result</div>
            <div className="mt-3 font-display text-3xl tracking-widest">
              {table.round?.result} wins / winner: {table.round?.winner_user_id}
            </div>
            <button className="btn-primary mt-5" disabled={busy} onClick={() => run(async () => {
              const next = await api(`/tables/${table.table_id}/deal-again`, { method: "POST" });
              navigate(`/flipget/${next.table_id}`);
            })}>Deal Again</button>
          </div>
        )}
      </div>
    </div>
  );
}
