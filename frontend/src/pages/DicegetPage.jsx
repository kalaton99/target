import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

const TARGETS = [30, 50, 75, 100];
const BOT_PROFILES = ["safe", "normal", "aggressive"];

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
  const response = await fetch(`/api/diceget${path}`, {
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

function Dice({ value }) {
  return (
    <div className="flex h-14 w-14 items-center justify-center rounded-md border border-zinc-700 bg-zinc-950 text-2xl text-yellow-200">
      {value || "-"}
    </div>
  );
}

function SeatCard({ seat, active }) {
  return (
    <div className={`rounded-lg border p-4 ${active ? "border-yellow-500 bg-yellow-500/10" : "border-zinc-800 bg-zinc-950/70"}`}>
      <div className="flex items-center justify-between gap-3">
        <div className="font-display text-xl tracking-widest text-zinc-100">
          {seat.username || seat.user_id}
        </div>
        <div className="text-xs uppercase tracking-widest text-zinc-500">
          Seat {seat.seat_index + 1}
        </div>
      </div>
      <div className="mt-4 text-4xl text-yellow-200">{seat.score}</div>
      <div className="mt-2 text-xs uppercase tracking-widest text-zinc-400">
        {seat.status}{seat.is_bot ? ` / ${seat.bot_profile}` : ""}
      </div>
    </div>
  );
}

export default function DicegetPage() {
  const { tableId } = useParams();
  const navigate = useNavigate();
  const [tables, setTables] = useState([]);
  const [table, setTable] = useState(null);
  const [selectedTarget, setSelectedTarget] = useState(30);
  const [stake, setStake] = useState(100);
  const [botProfile, setBotProfile] = useState("normal");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const user = storedUser();

  const latestRoll = table?.rolls?.[table.rolls.length - 1];
  const currentSeat = useMemo(
    () => table?.seats?.find((seat) => seat.user_id === table.current_turn_user_id),
    [table],
  );
  const mySeat = useMemo(
    () => table?.seats?.find((seat) => seat.user_id === user?.user_id),
    [table, user?.user_id],
  );
  const myTurn = Boolean(
    table?.status === "active"
      && mySeat
      && table.current_turn_user_id === mySeat.user_id
      && !["held", "busted", "forfeited"].includes(mySeat.status),
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
          <h1 className="mt-6 font-display text-5xl tracking-widest">Diceget</h1>
          <p className="mt-4 text-zinc-400">Sign in through the Axwins lobby before playing Diceget.</p>
          <Link className="btn-primary mt-6 inline-flex" to="/lobby">Sign in</Link>
        </div>
      </div>
    );
  }

  if (!tableId) {
    return (
      <div className="min-h-screen bg-black px-4 py-8 text-zinc-100">
        <div className="mx-auto max-w-6xl">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <div className="font-luxe text-xs uppercase tracking-[0.45em] text-yellow-300">Axwins Game</div>
              <h1 className="mt-2 font-display text-5xl tracking-widest">Diceget</h1>
            </div>
            <div className="flex flex-wrap gap-2">
              <Link className="btn-ghost" to="/">Axwins</Link>
              <Link className="btn-ghost" to="/games">Games</Link>
              <Link className="btn-ghost" to="/wallet">Wallet</Link>
            </div>
          </div>

          <div className="mt-8 grid gap-4 sm:grid-cols-4">
            {TARGETS.map((target) => (
              <button
                key={target}
                type="button"
                onClick={() => setSelectedTarget(target)}
                className={`rounded-lg border p-5 text-left ${selectedTarget === target ? "border-yellow-500 bg-yellow-500/10" : "border-zinc-800 bg-zinc-950"}`}
              >
                <div className="font-display text-3xl tracking-widest">Target {target}</div>
                <div className="mt-2 text-sm text-zinc-500">4 players</div>
              </button>
            ))}
          </div>

          <div className="mt-6 flex flex-wrap items-end gap-3">
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
                  body: JSON.stringify({ target_score: selectedTarget, stake, max_players: 4 }),
                });
                navigate(`/diceget/${created.table_id}`);
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
                  <div className="font-display text-2xl tracking-widest">Target {item.target_score}</div>
                  <div className="text-sm text-zinc-500">{item.seats.length}/4 seats / {item.status}</div>
                </div>
                <div className="flex gap-2">
                  <button className="btn-secondary" disabled={busy || item.status !== "waiting"} onClick={() => run(async () => {
                    await api(`/tables/${item.table_id}/join`, { method: "POST" });
                    navigate(`/diceget/${item.table_id}`);
                  })}>Join</button>
                  <Link className="btn-ghost" to={`/diceget/${item.table_id}`}>View</Link>
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
            <div className="font-luxe text-xs uppercase tracking-[0.45em] text-yellow-300">Diceget Table</div>
            <h1 className="mt-2 font-display text-5xl tracking-widest">
              Target {table?.target_score || "-"}
            </h1>
            <div className="mt-2 text-sm uppercase tracking-widest text-zinc-500">
              {table?.status || "loading"} / turn: {currentSeat?.username || currentSeat?.user_id || "-"}
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link className="btn-ghost" to="/">Axwins</Link>
            <Link className="btn-ghost" to="/games">Games</Link>
            <Link className="btn-ghost" to="/wallet">Wallet</Link>
            <Link className="btn-ghost" to="/diceget">Lobby</Link>
          </div>
        </div>
        {error && <div className="mt-4 text-sm text-rose-300">{error}</div>}

        <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {(table?.seats || []).map((seat) => (
            <SeatCard key={seat.user_id} seat={seat} active={seat.user_id === table.current_turn_user_id} />
          ))}
        </div>

        {table?.status === "waiting" && (
          <div className="mt-6 flex flex-wrap gap-3">
            <select
              value={botProfile}
              onChange={(event) => setBotProfile(event.target.value)}
              className="rounded border border-zinc-700 bg-zinc-950 px-3 py-2"
            >
              {BOT_PROFILES.map((profile) => <option key={profile}>{profile}</option>)}
            </select>
            <button className="btn-secondary" disabled={busy || table.seats.length >= 4} onClick={() => run(() => api(`/tables/${table.table_id}/add-bot`, {
              method: "POST",
              body: JSON.stringify({ profile: botProfile }),
            }))}>Add Bot</button>
            <button className="btn-primary" disabled={busy || table.seats.length !== 4} onClick={() => run(() => api(`/tables/${table.table_id}/start`, { method: "POST" }))}>Start</button>
            <button className="btn-ghost" disabled={busy} onClick={() => run(async () => {
              await api(`/tables/${table.table_id}/leave`, { method: "POST" });
              navigate("/diceget");
            })}>Leave</button>
          </div>
        )}

        <div className="mt-8 grid gap-6 lg:grid-cols-[0.8fr_1.2fr]">
          <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-5">
            <div className="mb-4 text-xs uppercase tracking-widest text-zinc-500">Dice</div>
            <div className="flex gap-3">
              <Dice value={latestRoll?.dice_1} />
              <Dice value={latestRoll?.dice_2} />
            </div>
            <div className="mt-5 flex flex-wrap gap-3">
              <button className="btn-primary" disabled={!myTurn || busy} onClick={() => run(() => api(`/tables/${table.table_id}/roll`, { method: "POST" }))}>Roll</button>
              <button className="btn-secondary" disabled={!myTurn || busy} onClick={() => run(() => api(`/tables/${table.table_id}/hold`, { method: "POST" }))}>Hold</button>
              <button className="btn-ghost" disabled={!myTurn || busy} onClick={() => run(() => api(`/tables/${table.table_id}/forfeit`, { method: "POST" }))}>Forfeit</button>
            </div>
          </div>
          <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-5">
            <div className="mb-4 text-xs uppercase tracking-widest text-zinc-500">Roll History</div>
            <div className="max-h-72 space-y-2 overflow-auto">
              {(table?.rolls || []).slice().reverse().map((roll, index) => (
                <div key={`${roll.user_id}-${index}`} className="rounded border border-zinc-800 bg-black/40 p-3 text-sm text-zinc-300">
                  {roll.user_id}: {roll.dice_1}+{roll.dice_2} = {roll.total}; {roll.score_before} -> {roll.score_after}{roll.is_bust ? " / bust" : ""}
                </div>
              ))}
            </div>
          </div>
        </div>

        {table?.status === "settled" && (
          <div className="mt-8 rounded-lg border border-yellow-700/40 bg-yellow-500/10 p-5">
            <div className="text-xs uppercase tracking-widest text-yellow-300">Result</div>
            <div className="mt-3 font-display text-3xl tracking-widest">
              {table.winners?.length ? `Winner${table.winners.length > 1 ? "s" : ""}: ${table.winners.join(", ")}` : "No winner"}
            </div>
            <button className="btn-primary mt-5" disabled={busy} onClick={() => run(async () => {
              const next = await api(`/tables/${table.table_id}/deal-again`, { method: "POST" });
              navigate(`/diceget/${next.table_id}`);
            })}>Deal Again</button>
          </div>
        )}
      </div>
    </div>
  );
}
