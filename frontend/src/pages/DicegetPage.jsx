import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { apiFetch } from "../lib/api";

const SCORE_GOALS = [
  { key: "sprint", label: "Sprint", goal: 40 },
  { key: "classic", label: "Classic", goal: 70 },
  { key: "marathon", label: "Marathon", goal: 120 },
];
const BOT_PROFILES = ["safe", "normal", "aggressive"];
const DEMO_CREDIT_NOTICE =
  "Axwins currently uses internal demo credits only. Deposits, withdrawals, cash-out, crypto, card payments, and real-money trading are not enabled.";
const TABLE_STATUS_RANK = { waiting: 0, active: 1, showdown: 2, settled: 3, cancelled: 4 };

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
  let response;
  try {
    response = await apiFetch(`/api/diceget${path}`, {
      ...options,
      headers: { ...authHeaders(), ...(options.headers || {}) },
    });
  } catch {
    throw new Error("BACKEND_OFFLINE");
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status === 401) {
      localStorage.removeItem("target_user");
      throw new Error("SESSION_EXPIRED");
    }
    const detail = data?.detail;
    throw new Error(detail?.code || detail || `HTTP_${response.status}`);
  }
  return data;
}

function friendlyErrorMessage(message) {
  const raw = String(message || "");
  if (raw.includes("BACKEND_OFFLINE") || raw.toLowerCase().includes("failed to fetch")) {
    return "Backend is offline. Start the local backend with .\\scripts\\start-backend-local.ps1 and retry Diceget.";
  }
  if (raw.includes("DicegetInsufficientFunds") || raw.toLowerCase().includes("insufficient")) {
    return "Not enough available internal demo credits to reserve this stake. Check Wallet / Transaction History and try again.";
  }
  if (raw.includes("SESSION_EXPIRED") || raw.includes("INVALID_TOKEN") || raw.includes("MISSING_TOKEN")) {
    return "Session expired. Sign in through the Axwins lobby again to continue Diceget.";
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
  const [selectedScoreGoal, setSelectedScoreGoal] = useState(70);
  const [stake, setStake] = useState(100);
  const [botProfile, setBotProfile] = useState("normal");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [exitConfirmOpen, setExitConfirmOpen] = useState(false);
  const [showAllTables, setShowAllTables] = useState(false);
  const [howToPlayOpen, setHowToPlayOpen] = useState(false);
  const user = storedUser();
  const backendOffline = error.startsWith("Backend is offline.");

  const latestRoll = table?.rolls?.[table.rolls.length - 1];
  const scoreGoalOf = (item) => item?.score_goal ?? item?.target_score;
  const sortedTables = [...tables].sort((a, b) => (TABLE_STATUS_RANK[a.status] ?? 9) - (TABLE_STATUS_RANK[b.status] ?? 9));
  const visibleTables = showAllTables ? sortedTables : sortedTables.slice(0, 5);
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
  const activeExitRisk = Boolean(
    table
      && mySeat
      && !["waiting", "settled", "cancelled"].includes(table.status),
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
    if (myTurn) return "Your turn: roll to add to your score, hold to bank it, or choose Give Up to surrender the table.";
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
    refresh().catch((err) => setError(friendlyErrorMessage(err.message)));
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

  async function autoFillDemoSeats() {
    await run(async () => {
      let next = table;
      const needed = Math.max(0, 4 - (next?.seats?.length || 0));
      for (let index = 0; index < needed; index += 1) {
        next = await api(`/tables/${next.table_id}/add-bot`, {
          method: "POST",
          body: JSON.stringify({ profile: botProfile }),
        });
      }
      return next;
    });
  }

  function requestExit() {
    if (activeExitRisk) {
      setExitConfirmOpen(true);
      return;
    }
    navigate("/diceget");
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
                4-player dice game inside Axwins. Pick a score goal, create or join a table, then roll, hold, or give up on your turn.
              </p>
            </div>
            <div className="flex w-full flex-wrap gap-2 sm:w-auto sm:justify-end">
              <Link className="btn-ghost" to="/">Axwins</Link>
              <Link className="btn-ghost" to="/games">Games</Link>
              <button className="btn-ghost" type="button" onClick={() => setHowToPlayOpen(true)}>How to Play</button>
              <Link className="btn-ghost" to="/tmarget">Tmarget</Link>
              <Link className="btn-ghost" to="/wallet">Wallet / Ledger</Link>
            </div>
          </div>
          <div className="mt-6">
            <Notice>{DEMO_CREDIT_NOTICE}</Notice>
          </div>

          <div className="mt-8 grid gap-4 sm:grid-cols-4">
            {SCORE_GOALS.map((mode) => (
              <button
                key={mode.key}
                type="button"
                onClick={() => setSelectedScoreGoal(mode.goal)}
                className={`rounded-lg border p-5 text-left ${selectedScoreGoal === mode.goal ? "border-yellow-500 bg-yellow-500/10" : "border-zinc-800 bg-zinc-950"}`}
              >
                <div className="font-display text-3xl tracking-widest">{mode.label} {mode.goal}</div>
                <div className="mt-2 text-sm text-zinc-500">Score Goal / 4 players</div>
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
              disabled={busy || backendOffline}
              onClick={() => run(async () => {
                const created = await api("/tables", {
                  method: "POST",
                  body: JSON.stringify({ score_goal: selectedScoreGoal, stake, max_players: 4 }),
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
            {visibleTables.map((item) => (
              <div key={item.table_id} className="flex flex-col items-start justify-between gap-3 rounded-lg border border-zinc-800 bg-zinc-950 p-4 sm:flex-row sm:items-center">
                <div>
                  <div className="font-display text-2xl tracking-widest">Score Goal {scoreGoalOf(item)}</div>
                  <div className="text-sm text-zinc-500">{item.seats.length}/4 seats / {item.status}</div>
                </div>
                <div className="flex w-full flex-wrap gap-2 sm:w-auto">
                  <button className="btn-secondary" disabled={busy || backendOffline || item.status !== "waiting"} onClick={() => run(async () => {
                    await api(`/tables/${item.table_id}/join`, { method: "POST" });
                    navigate(`/diceget/${item.table_id}`);
                  })}>Join Table</button>
                  <Link className="btn-ghost" to={`/diceget/${item.table_id}`}>View</Link>
                </div>
              </div>
            ))}
            {!showAllTables && tables.length > 5 && (
              <button
                type="button"
                onClick={() => setShowAllTables(true)}
                className="rounded-lg border border-zinc-800 bg-zinc-950 p-4 text-xs uppercase tracking-widest text-zinc-400 hover:text-yellow-300"
              >
                Show all {tables.length} open Diceget tables
              </button>
            )}
          </div>
          {howToPlayOpen && (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 px-4">
              <div className="w-full max-w-2xl rounded-lg border border-yellow-700/50 bg-zinc-950 p-6 shadow-2xl">
                <div className="flex items-center justify-between gap-4">
                  <div className="font-display text-2xl tracking-widest text-yellow-100">How to Play Diceget</div>
                  <button className="btn-ghost" type="button" onClick={() => setHowToPlayOpen(false)}>Close</button>
                </div>
                <ul className="mt-5 space-y-2 text-sm leading-6 text-zinc-300">
                  <li>Choose a score goal mode: Sprint 40, Classic 70, or Marathon 120.</li>
                  <li>Diceget is a 4-player dice table. Bots or demo participants can fill seats for local play.</li>
                  <li>On your turn, roll dice to build score toward the selected score goal.</li>
                  <li>Hold locks your current score and ends your rolling for the round or turn.</li>
                  <li>Going over the score goal can bust that seat.</li>
                  <li>When the table settles, Diceget compares valid locked scores and goal-reaching results using the current backend winner rules.</li>
                  <li>Give Up means surrendering the active game and may lose the reserved demo stake.</li>
                </ul>
              </div>
            </div>
          )}
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
              Score Goal {scoreGoalOf(table) || "-"}
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
            <button className="btn-ghost" type="button" onClick={requestExit}>Back to Diceget</button>
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
              Waiting for {4 - table.seats.length} more demo participant{4 - table.seats.length === 1 ? "" : "s"}. Use Auto-Fill Demo Seats for local play.
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
            <button className="btn-secondary" disabled={busy || backendOffline || table.seats.length >= 4} onClick={() => run(() => api(`/tables/${table.table_id}/add-bot`, {
              method: "POST",
              body: JSON.stringify({ profile: botProfile }),
            }))}>Add Bot Seat</button>
            <button className="btn-secondary" disabled={busy || backendOffline || table.seats.length >= 4} onClick={autoFillDemoSeats}>Auto-Fill Demo Seats</button>
            <button className="btn-primary" disabled={busy || backendOffline || table.seats.length !== 4} onClick={() => run(() => api(`/tables/${table.table_id}/start`, { method: "POST" }))}>Start Diceget</button>
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
              <button className="btn-primary" title={actionHint} disabled={!myTurn || busy || backendOffline} onClick={() => run(() => api(`/tables/${table.table_id}/roll`, { method: "POST" }))}>Roll</button>
              <button className="btn-secondary" title={actionHint} disabled={!myTurn || busy || backendOffline} onClick={() => run(() => api(`/tables/${table.table_id}/hold`, { method: "POST" }))}>Hold</button>
              <button className="btn-ghost" title="Leaving now may count as a loss and your reserved demo stake may be lost." disabled={!myTurn || busy || backendOffline} onClick={() => run(() => api(`/tables/${table.table_id}/forfeit`, { method: "POST" }))}>Give Up</button>
            </div>
            <p className="mt-3 text-xs leading-5 text-zinc-500">
              Leaving now may count as a loss and your reserved demo stake may be lost.
            </p>
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
        {howToPlayOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 px-4">
            <div className="w-full max-w-2xl rounded-lg border border-yellow-700/50 bg-zinc-950 p-6 shadow-2xl">
              <div className="flex items-center justify-between gap-4">
                <div className="font-display text-2xl tracking-widest text-yellow-100">How to Play Diceget</div>
                <button className="btn-ghost" type="button" onClick={() => setHowToPlayOpen(false)}>Close</button>
              </div>
              <ul className="mt-5 space-y-2 text-sm leading-6 text-zinc-300">
                <li>Choose a score goal mode: Sprint 40, Classic 70, or Marathon 120.</li>
                <li>Diceget is a 4-player dice table. Bots or demo participants can fill seats for local play.</li>
                <li>On your turn, roll dice to build score toward the selected score goal.</li>
                <li>Hold locks your current score and ends your rolling for the round or turn.</li>
                <li>Going over the score goal can bust that seat.</li>
                <li>When the table settles, Diceget compares valid locked scores and goal-reaching results using the current backend winner rules.</li>
                <li>Give Up means surrendering the active game and may lose the reserved demo stake.</li>
              </ul>
            </div>
          </div>
        )}
        {exitConfirmOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 px-4">
            <div className="w-full max-w-md rounded-lg border border-yellow-700/50 bg-zinc-950 p-6 shadow-2xl">
              <div className="font-display text-2xl tracking-widest text-yellow-100">Leave Active Diceget?</div>
              <p className="mt-4 text-sm leading-6 text-zinc-300">
                Leaving may cause the current stake or participation to be lost. Diceget will keep running on the backend if you exit this screen.
              </p>
              <div className="mt-6 flex flex-wrap justify-end gap-3">
                <button className="btn-secondary" type="button" onClick={() => setExitConfirmOpen(false)}>Stay</button>
                <button className="btn-primary" type="button" onClick={() => navigate("/diceget")}>Leave Diceget</button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
