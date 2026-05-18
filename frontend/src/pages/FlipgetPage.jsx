import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { apiFetch } from "../lib/api";

const SIDES = ["heads", "tails"];
const DEMO_CREDIT_NOTICE =
  "Axwins currently uses internal demo credits only. Deposits, withdrawals, cash-out, crypto, card payments, and real-money trading are not enabled.";

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
  const response = await apiFetch(`/api/flipget${path}`, {
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

function friendlyErrorMessage(message) {
  const raw = String(message || "");
  if (raw.includes("FlipgetInsufficientFunds") || raw.toLowerCase().includes("insufficient")) {
    return "Not enough available internal demo credits to reserve this stake. Check Wallet / Transaction History and try again.";
  }
  return raw.split("_").join(" ");
}

function dealAgainErrorMessage() {
  return "Could not create the next Flipget table because demo credits could not be locked. Check Wallet / Transaction History and try again.";
}

function Coin({ result, status }) {
  const label = status === "flipping" ? "Flipping" : result || "Ready";
  return (
    <div className="flex aspect-square w-40 items-center justify-center rounded-full border border-yellow-500/60 bg-zinc-950 text-center font-display text-3xl uppercase tracking-widest text-yellow-200">
      {label}
    </div>
  );
}

function Seat({ seat, fallbackIndex = 0 }) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-5">
      <div className="flex items-center justify-between gap-3">
        <div className="font-display text-2xl tracking-widest">{seat?.username || seat?.user_id || "Open"}</div>
        <div className="text-xs uppercase tracking-widest text-zinc-500">Seat {(seat?.seat_index ?? fallbackIndex) + 1}</div>
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

function Notice({ children }) {
  return (
    <div className="rounded-lg border border-yellow-700/40 bg-yellow-500/10 p-4 text-sm leading-6 text-yellow-100">
      {children}
    </div>
  );
}

function ErrorNotice({ error }) {
  if (!error) return null;
  return (
    <div className="rounded-lg border border-rose-800 bg-rose-950/30 p-4 text-sm text-rose-200">
      {error}
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
    mySeat
      && table?.status === "ready"
      && table?.seats?.length === 2
      && table.seats.every((seat) => seat.ready && seat.side),
  );
  const canLeavePreFlip = Boolean(
    mySeat
      && table
      && !["flipping", "settled"].includes(table.status),
  );
  const waitingForReady = Boolean(
    table
      && table.status === "waiting"
      && table.seats?.length === 2
      && table.seats.some((seat) => !seat.ready || !seat.side),
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
      setError(friendlyErrorMessage(err.message));
      return null;
    } finally {
      setBusy(false);
    }
  }

  if (!user?.token) {
    return (
      <div className="min-h-screen bg-black px-4 py-10 text-zinc-100">
        <div className="mx-auto max-w-3xl">
          <div className="flex flex-wrap gap-2">
            <Link className="btn-ghost" to="/">Axwins</Link>
            <Link className="btn-ghost" to="/games">Games</Link>
            <Link className="btn-ghost" to="/tmarget">Tmarget</Link>
            <Link className="btn-ghost" to="/wallet">Wallet / Ledger</Link>
          </div>
          <h1 className="mt-6 font-display text-5xl tracking-widest">Flipget</h1>
          <p className="mt-4 text-zinc-400">2-player coin flip game inside Axwins.</p>
          <div className="mt-5">
            <Notice>{DEMO_CREDIT_NOTICE}</Notice>
          </div>
          <p className="mt-4 text-zinc-400">Sign in through the Axwins lobby before playing Flipget.</p>
          <Link className="btn-primary mt-6 inline-flex" to="/lobby">Sign in</Link>
        </div>
      </div>
    );
  }

  if (!tableId) {
    return (
      <div className="min-h-screen bg-black px-4 py-8 text-zinc-100">
        <div className="mx-auto max-w-6xl">
          <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
            <div>
              <div className="font-luxe text-xs uppercase tracking-[0.45em] text-yellow-300">Axwins Game</div>
              <h1 className="mt-2 font-display text-5xl tracking-widest">Flipget</h1>
              <p className="mt-3 max-w-2xl text-sm leading-6 text-zinc-400">
                2-player coin flip game inside Axwins. Choose heads or tails, ready up, then flip when both sides are set.
              </p>
            </div>
            <div className="flex w-full flex-wrap gap-2 sm:w-auto sm:justify-end">
              <Link className="btn-ghost" to="/">Axwins</Link>
              <Link className="btn-ghost" to="/games">Games</Link>
              <Link className="btn-ghost" to="/tmarget">Tmarget</Link>
              <Link className="btn-ghost" to="/wallet">Wallet / Ledger</Link>
            </div>
          </div>
          <div className="mt-6">
            <Notice>{DEMO_CREDIT_NOTICE}</Notice>
          </div>
          <div className="mt-8 grid gap-3 sm:flex sm:flex-wrap sm:items-end">
            <label className="text-xs uppercase tracking-widest text-zinc-500">
              Stake
              <input
                value={stake}
                onChange={(event) => setStake(Number(event.target.value) || 0)}
                className="mt-2 block w-full rounded border border-zinc-700 bg-zinc-950 px-3 py-2 text-zinc-100 sm:w-36"
                type="number"
                min="0"
              />
              <span className="mt-2 block max-w-xs text-[11px] normal-case leading-5 tracking-normal text-zinc-500">
                Stake is reserved from internal demo credits until the pre-flip table is left or the result settles.
              </span>
            </label>
            <button
              className="btn-primary text-center"
              disabled={busy}
              onClick={() => run(async () => {
                const created = await api("/tables", {
                  method: "POST",
                  body: JSON.stringify({ stake_amount: stake, max_players: 2 }),
                });
                navigate(`/flipget/${created.table_id}`);
              })}
            >
              Create Flipget Table
            </button>
          </div>
          <div className="mt-4">
            <ErrorNotice error={error} />
          </div>
          <div className="mt-10 grid gap-3">
            {tables.length === 0 && (
              <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-5 text-sm text-zinc-400">
                No active Flipget tables. Create a 2-player table to start.
              </div>
            )}
            {tables.map((item) => (
              <div key={item.table_id} className="flex flex-col items-start justify-between gap-3 rounded-lg border border-zinc-800 bg-zinc-950 p-4 sm:flex-row sm:items-center">
                <div>
                  <div className="font-display text-2xl tracking-widest">Flipget</div>
                  <div className="text-sm text-zinc-500">{item.seats.length}/2 seats / {item.status}</div>
                </div>
                <div className="flex w-full flex-wrap gap-2 sm:w-auto">
                  <button className="btn-secondary" disabled={busy || item.status !== "waiting"} onClick={() => run(async () => {
                    await api(`/tables/${item.table_id}/join`, { method: "POST" });
                    navigate(`/flipget/${item.table_id}`);
                  })}>Join Table</button>
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
        <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
          <div>
            <div className="font-luxe text-xs uppercase tracking-[0.45em] text-yellow-300">Flipget Table</div>
            <h1 className="mt-2 font-display text-5xl tracking-widest">{table?.status || "Loading"}</h1>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-zinc-400">
              2-player coin flip game inside Axwins. The backend returns the coin result.
            </p>
          </div>
          <div className="flex w-full flex-wrap gap-2 sm:w-auto sm:justify-end">
            <Link className="btn-ghost" to="/">Axwins</Link>
            <Link className="btn-ghost" to="/games">Games</Link>
            <Link className="btn-ghost" to="/tmarget">Tmarget</Link>
            <Link className="btn-ghost" to="/wallet">Wallet / Ledger</Link>
            <Link className="btn-ghost" to="/flipget">Lobby</Link>
          </div>
        </div>
        <div className="mt-6">
          <Notice>{DEMO_CREDIT_NOTICE}</Notice>
        </div>
        {table?.stake_amount > 0 && (
          <div className="mt-3 text-sm leading-6 text-zinc-500">
            Stake reserved: {table.stake_amount} internal demo credits per participant.
          </div>
        )}
        <div className="mt-4">
          <ErrorNotice error={error} />
        </div>
        <div className="mt-8 grid gap-6 lg:grid-cols-[0.8fr_1.2fr]">
          <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-5">
            {!table && (
              <div className="mb-4 rounded border border-zinc-800 bg-black/40 p-3 text-center text-sm text-zinc-500">
                Loading Flipget table...
              </div>
            )}
            <div className="flex justify-center">
              <Coin result={table?.round?.result} status={table?.status} />
            </div>
            <div className="mt-6 grid gap-3 sm:flex sm:flex-wrap sm:justify-center">
              {!mySeat && table && (
                <div className="w-full rounded border border-zinc-800 bg-black/30 p-3 text-center text-sm text-zinc-500">
                  Spectators can view this table. Join a waiting table to choose a side, ready up, or flip.
                </div>
              )}
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
                    Choose {side}
                  </button>
                );
              })}
              <button className="btn-primary" disabled={busy || !mySeat?.side || mySeat.ready || ["flipping", "settled"].includes(table?.status)} onClick={() => run(() => api(`/tables/${table.table_id}/ready`, { method: "POST" }))}>Ready Up</button>
              {mySeat && (
                <button className="btn-secondary" disabled={busy || !canFlip} onClick={() => run(() => api(`/tables/${table.table_id}/flip`, { method: "POST" }))}>Flip Coin</button>
              )}
              {mySeat && !canFlip && table?.status !== "settled" && (
                <div className="w-full rounded border border-zinc-800 bg-black/30 p-3 text-center text-sm leading-6 text-zinc-500">
                  Flip unlocks after two players choose unique sides and both
                  ready up. This local demo does not route Flipget through
                  Target table WebSockets.
                </div>
              )}
            </div>
          </div>
          <div className="grid gap-4">
            <Seat seat={table?.seats?.[0]} fallbackIndex={0} />
            <Seat seat={table?.seats?.[1]} fallbackIndex={1} />
            {table?.status === "waiting" && table.seats?.length < 2 && (
              <div className="rounded-lg border border-dashed border-zinc-800 bg-zinc-950/40 p-4 text-sm text-zinc-500">
                Waiting for one more player.
              </div>
            )}
            {waitingForReady && (
              <div className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-4 text-sm leading-6 text-zinc-500">
                Waiting for both players to choose unique sides and ready up.
              </div>
            )}
            {canLeavePreFlip && (
              <button className="btn-ghost" disabled={busy} onClick={() => run(async () => {
                await api(`/tables/${table.table_id}/leave`, { method: "POST" });
                navigate("/flipget");
              })}>Leave Table</button>
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
              let next;
              try {
                next = await api(`/tables/${table.table_id}/deal-again`, { method: "POST" });
              } catch {
                throw new Error(dealAgainErrorMessage());
              }
              navigate(`/flipget/${next.table_id}`);
            })}>Deal Again</button>
          </div>
        )}
      </div>
    </div>
  );
}
