import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { apiFetch } from "../lib/api";

const TARGETS = [30, 50, 75, 100];
const BOT_PROFILES = ["safe", "normal", "aggressive"];
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
  const response = await apiFetch(`/api/diceget${path}`, {
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
  if (raw.includes("DicegetInsufficientFunds") || raw.toLowerCase().includes("insufficient")) {
    return "Not enough available internal demo credits to reserve this stake. Check Wallet / Transaction History and try again.";
  }
  return raw.split("_").join(" ");
}

function dealAgainErrorMessage() {
  return "Could not create the next Diceget table because demo credits could not be locked. Check Wallet / Transaction History and try again.";
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
  const actionHint = useMemo(() => {
    if (!table) return "Loading Diceget table state.";
    if (!mySeat) return "You are viewing this Diceget table as a spectator.";
    if (table.status === "waiting") {
      const needed = Math.max(0, 4 - (table.seats?.length || 0));
      return needed > 0
        ? `Start unlocks when all 4 seats are filled. Add ${needed} more demo participant${needed === 1 ? "" : "s"} or bot seat${needed === 1 ? "" : "s"}.`
        : "All 4 seats are filled. Start Diceget to unlock roll actions.";
    }
    if (table.status !== "active") return "Dice actions are available only while the table is active.";
    if (myTurn) return "Your turn: roll to add to your score, hold to bank it, or forfeit the table.";
    return `Waiting for ${currentSeat?.username || currentSeat?.user_id || "the active seat"} to act.`;
  }, [currentSeat, mySeat, myTurn, table]);

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
          <h1 className="mt-6 font-display text-5xl tracking-widest">Diceget</h1>
          <p className="mt-4 text-zinc-400">4-player dice game inside Axwins.</p>
          <div className="mt-5">
            <Notice>{DEMO_CREDIT_NOTICE}</Notice>
          </div>
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
        <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
            <div>
              <div className="font-luxe text-xs uppercase tracking-[0.45em] text-yellow-300">Axwins Game</div>
              <h1 className="mt-2 font-display text-5xl tracking-widest">Diceget</h1>
              <p className="mt-3 max-w-2xl text-sm leading-6 text-zinc-400">
                4-player dice game inside Axwins. Pick a target, create or join a table, then roll, hold, or forfeit on your turn.
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

          <div className="mt-6 grid gap-3 sm:flex sm:flex-wrap sm:items-end">
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
                Stake is reserved from internal demo credits while the table is active.
              </span>
            </label>
            <button
              className="btn-primary text-center"
              disabled={busy}
              onClick={() => run(async () => {
                const created = await api("/tables", {
                  method: "POST",
                  body: JSON.stringify({ target_score: selectedTarget, stake, max_players: 4 }),
                });
                navigate(`/diceget/${created.table_id}`);
              })}
            >
              Create Diceget Table
            </button>
          </div>
          <div className="mt-4">
            <ErrorNotice error={error} />
          </div>

          <div className="mt-10 grid gap-3">
            {tables.length === 0 && (
              <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-5 text-sm text-zinc-400">
                No active Diceget tables. Create a 4-player table to start.
              </div>
            )}
            {tables.map((item) => (
              <div key={item.table_id} className="flex flex-col items-start justify-between gap-3 rounded-lg border border-zinc-800 bg-zinc-950 p-4 sm:flex-row sm:items-center">
                <div>
                  <div className="font-display text-2xl tracking-widest">Target {item.target_score}</div>
                  <div className="text-sm text-zinc-500">{item.seats.length}/4 seats / {item.status}</div>
                </div>
                <div className="flex w-full flex-wrap gap-2 sm:w-auto">
                  <button className="btn-secondary" disabled={busy || item.status !== "waiting"} onClick={() => run(async () => {
                    await api(`/tables/${item.table_id}/join`, { method: "POST" });
                    navigate(`/diceget/${item.table_id}`);
                  })}>Join Table</button>
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
          <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
          <div>
            <div className="font-luxe text-xs uppercase tracking-[0.45em] text-yellow-300">Diceget Table</div>
            <h1 className="mt-2 font-display text-5xl tracking-widest">
              Target {table?.target_score || "-"}
            </h1>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-zinc-400">
              4-player dice game inside Axwins. Actions unlock only for the current player on their turn.
            </p>
            <div className="mt-2 text-sm uppercase tracking-widest text-zinc-500">
              {table?.status || "loading"} / turn: {currentSeat?.username || currentSeat?.user_id || "-"}
            </div>
          </div>
          <div className="flex w-full flex-wrap gap-2 sm:w-auto sm:justify-end">
            <Link className="btn-ghost" to="/">Axwins</Link>
            <Link className="btn-ghost" to="/games">Games</Link>
            <Link className="btn-ghost" to="/tmarget">Tmarget</Link>
            <Link className="btn-ghost" to="/wallet">Wallet / Ledger</Link>
            <Link className="btn-ghost" to="/diceget">Lobby</Link>
          </div>
        </div>
        <div className="mt-6">
          <Notice>{DEMO_CREDIT_NOTICE}</Notice>
        </div>
        {table?.stake > 0 && (
          <div className="mt-3 text-sm leading-6 text-zinc-500">
            Stake reserved: {table.stake} internal demo credits per human participant.
          </div>
        )}
        <div className="mt-4">
          <ErrorNotice error={error} />
        </div>

        <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {!table && (
            <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-5 text-sm text-zinc-400 lg:col-span-4">
              Loading Diceget table...
            </div>
          )}
          {(table?.seats || []).map((seat) => (
            <SeatCard key={seat.user_id} seat={seat} active={seat.user_id === table.current_turn_user_id} />
          ))}
          {table && table.seats?.length < 4 && (
            <div className="rounded-lg border border-dashed border-zinc-800 bg-zinc-950/40 p-5 text-sm leading-6 text-zinc-500">
              Waiting for {4 - table.seats.length} more player{4 - table.seats.length === 1 ? "" : "s"}.
            </div>
          )}
        </div>

        {table?.status === "waiting" && (
          <div className="mt-6 grid gap-3 sm:flex sm:flex-wrap">
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
            }))}>Add Bot Seat</button>
            <button className="btn-primary" disabled={busy || table.seats.length !== 4} onClick={() => run(() => api(`/tables/${table.table_id}/start`, { method: "POST" }))}>Start Diceget</button>
            <button className="btn-ghost" disabled={busy} onClick={() => run(async () => {
              await api(`/tables/${table.table_id}/leave`, { method: "POST" });
              navigate("/diceget");
            })}>Leave Table</button>
          </div>
        )}
        <div
          data-testid="diceget-action-hint"
          className="mt-4 rounded-lg border border-zinc-800 bg-zinc-950/70 p-4 text-sm leading-6 text-zinc-400"
        >
          {actionHint}
        </div>

        <div className="mt-8 grid gap-6 lg:grid-cols-[0.8fr_1.2fr]">
          <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-5">
            <div className="mb-4 text-xs uppercase tracking-widest text-zinc-500">Dice</div>
            <div className="flex gap-3">
              <Dice value={latestRoll?.dice_1} />
              <Dice value={latestRoll?.dice_2} />
            </div>
            <div className="mt-5 grid gap-3 sm:flex sm:flex-wrap">
              <button className="btn-primary" title={actionHint} disabled={!myTurn || busy} onClick={() => run(() => api(`/tables/${table.table_id}/roll`, { method: "POST" }))}>Roll</button>
              <button className="btn-secondary" title={actionHint} disabled={!myTurn || busy} onClick={() => run(() => api(`/tables/${table.table_id}/hold`, { method: "POST" }))}>Hold</button>
              <button className="btn-ghost" title={actionHint} disabled={!myTurn || busy} onClick={() => run(() => api(`/tables/${table.table_id}/forfeit`, { method: "POST" }))}>Forfeit</button>
            </div>
          </div>
          <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-5">
            <div className="mb-4 text-xs uppercase tracking-widest text-zinc-500">Roll History</div>
            <div className="max-h-72 space-y-2 overflow-auto">
              {(table?.rolls || []).length === 0 && (
                <div className="rounded border border-zinc-800 bg-black/40 p-3 text-sm text-zinc-500">
                  No rolls yet. Roll unlocks once Diceget is active and it is your turn.
                </div>
              )}
              {(table?.rolls || []).slice().reverse().map((roll, index) => (
                <div key={`${roll.user_id}-${index}`} className="rounded border border-zinc-800 bg-black/40 p-3 text-sm text-zinc-300">
                  {roll.user_id}: {roll.dice_1}+{roll.dice_2} = {roll.total}; {roll.score_before} -> {roll.score_after}{roll.is_bust ? " / bust" : ""}
                </div>
              ))}
            </div>
          </div>
        </div>

        {table?.status === "showdown" && (
          <div className="mt-8 rounded-lg border border-yellow-700/40 bg-yellow-500/10 p-5">
            <div className="text-xs uppercase tracking-widest text-yellow-300">Showdown</div>
            <div className="mt-3 text-sm leading-6 text-yellow-100">
              Final rolls are complete and Diceget is finalizing the result. If this does not update shortly, refresh the table.
            </div>
            <div className="mt-4 grid gap-2">
              {(table.seats || []).map((seat) => (
                <div key={seat.user_id} className="rounded border border-yellow-700/30 bg-black/30 p-3 text-sm text-zinc-200">
                  {seat.username || seat.user_id}: {seat.status === "held" ? `held at ${seat.locked_score}` : seat.status}
                </div>
              ))}
            </div>
          </div>
        )}

        {table?.status === "settled" && (
          <div className="mt-8 rounded-lg border border-yellow-700/40 bg-yellow-500/10 p-5">
            <div className="text-xs uppercase tracking-widest text-yellow-300">Result</div>
            <div className="mt-3 font-display text-3xl tracking-widest">
              {table.winners?.length ? `Winner${table.winners.length > 1 ? "s" : ""}: ${table.winners.join(", ")}` : "No winner"}
            </div>
            <button className="btn-primary mt-5" disabled={busy} onClick={() => run(async () => {
              let next;
              try {
                next = await api(`/tables/${table.table_id}/deal-again`, { method: "POST" });
              } catch {
                throw new Error(dealAgainErrorMessage());
              }
              navigate(`/diceget/${next.table_id}`);
            })}>Deal Again</button>
          </div>
        )}
      </div>
    </div>
  );
}
