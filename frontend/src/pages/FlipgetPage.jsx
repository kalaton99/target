import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { apiFetch } from "../lib/api";

const SIDES = ["heads", "tails"];
const FLIPGET_MODES = [
  { key: "single_flip", label: "Single Flip", helper: "One flip resolves the table." },
  { key: "best_of_3", label: "Best of 3", helper: "First side to 2 wins resolves the table." },
  { key: "best_of_5", label: "Best of 5", helper: "First side to 3 wins resolves the table." },
];
const DEMO_CREDIT_NOTICE =
  "Axwins currently uses internal demo credits only. Deposits, withdrawals, cash-out, crypto, card payments, and real-money trading are not enabled.";
const TABLE_STATUS_RANK = { waiting: 0, ready: 1, flipping: 2, settled: 3, cancelled: 4 };

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
    response = await apiFetch(`/api/flipget${path}`, {
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
    return "Backend is offline. Start the local backend with .\\scripts\\start-backend-local.ps1 and retry Flipget.";
  }
  if (raw.includes("FlipgetInsufficientFunds") || raw.toLowerCase().includes("insufficient")) {
    return "Not enough available internal demo credits to reserve this stake. Check Wallet / Transaction History and try again.";
  }
  if (raw.includes("SESSION_EXPIRED") || raw.includes("INVALID_TOKEN") || raw.includes("MISSING_TOKEN")) {
    return "Session expired. Sign in through the Axwins lobby again to continue Flipget.";
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
  const [mode, setMode] = useState("single_flip");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [exitConfirmOpen, setExitConfirmOpen] = useState(false);
  const [showAllTables, setShowAllTables] = useState(false);
  const [howToPlayOpen, setHowToPlayOpen] = useState(false);
  const user = storedUser();
  const backendOffline = error.startsWith("Backend is offline.");
  const sortedTables = [...tables].sort((a, b) => (TABLE_STATUS_RANK[a.status] ?? 9) - (TABLE_STATUS_RANK[b.status] ?? 9));
  const visibleTables = showAllTables ? sortedTables : sortedTables.slice(0, 5);

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
  const completedRounds = useMemo(
    () => (table?.rounds || []).filter((round) => SIDES.includes(round.result)),
    [table],
  );
  const lastCompletedRound = completedRounds[completedRounds.length - 1] || null;
  const playerRoundWins = completedRounds.filter((round) => round.winner_user_id === user?.user_id).length;
  const opponentRoundWins = completedRounds.length - playerRoundWins;
  const matchHasStarted = completedRounds.length > 0;
  const participantLabel = useCallback((userId) => {
    if (!userId) return "-";
    if (userId === user?.user_id) return "Player";
    const seat = table?.seats?.find((candidate) => candidate.user_id === userId);
    if (seat?.user_id?.startsWith("fg_demo_opponent_") || seat?.username === "Demo Opponent") {
      return "Demo Opponent";
    }
    return seat?.username || userId;
  }, [table?.seats, user?.user_id]);
  const participantSide = useCallback((round, userId) => {
    const side = round?.side_by_user?.[userId];
    return side ? side.charAt(0).toUpperCase() + side.slice(1) : "-";
  }, []);
  const demoOpponentSeat = useMemo(
    () => table?.seats?.find((seat) => seat.user_id?.startsWith("fg_demo_opponent_") || seat.username === "Demo Opponent"),
    [table?.seats],
  );
  const canLeavePreFlip = Boolean(
    mySeat
      && table
      && !["flipping", "settled"].includes(table.status)
      && !matchHasStarted,
  );
  const activeExitRisk = Boolean(
    table
      && mySeat
      && !["settled", "cancelled"].includes(table.status)
      && (table.status !== "waiting" || matchHasStarted),
  );
  const waitingForReady = Boolean(
    table
      && table.status === "waiting"
      && table.seats?.length === 2
      && table.seats.some((seat) => !seat.ready || !seat.side),
  );
  const canAddDemoOpponent = Boolean(
    mySeat
      && mySeat.side
      && table?.status === "waiting"
      && (table.seats?.length || 0) < 2,
  );
  const actionHint = useMemo(() => {
    if (!table) return "Loading Flipget table state.";
    if (!mySeat) return "Spectators can watch Flipget. Join a waiting table to choose a side and ready up.";
    if (table.status === "settled") return "Flipget settled. Use Deal Again to start another internal demo-credit flip.";
    if (canFlip) return `${table.mode_label || "Flipget"} is ready. Flip Coin is available.`;
    if ((table.seats?.length || 0) < 2) return mySeat?.side
      ? "Flip requires two demo participants with unique sides. Add a demo opponent to complete the local flow."
      : "Flip requires two demo participants with unique sides.";
    if (!mySeat.side) return matchHasStarted
      ? "Choose heads or tails for this round, then ready up."
      : "Choose heads or tails, then ready up.";
    if (!mySeat.ready) return matchHasStarted
      ? "Ready up after choosing your side for this round."
      : "Ready up after choosing your side.";
    return "Flip requires two demo participants with unique sides and both ready.";
  }, [canFlip, matchHasStarted, mySeat, table]);

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

  function requestExit() {
    if (activeExitRisk) {
      setExitConfirmOpen(true);
      return;
    }
    navigate("/flipget");
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
              <button className="btn-ghost" type="button" onClick={() => setHowToPlayOpen(true)}>How to Play</button>
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
            <label className="text-xs uppercase tracking-widest text-zinc-500">
              Mode
              <select
                value={mode}
                onChange={(event) => setMode(event.target.value)}
                className="mt-2 block w-full rounded border border-zinc-700 bg-zinc-950 px-3 py-2 text-zinc-100 sm:w-48"
              >
                {FLIPGET_MODES.map((item) => (
                  <option key={item.key} value={item.key}>{item.label}</option>
                ))}
              </select>
              <span className="mt-2 block max-w-xs text-[11px] normal-case leading-5 tracking-normal text-zinc-500">
                {FLIPGET_MODES.find((item) => item.key === mode)?.helper}
              </span>
            </label>
            <button
              className="btn-primary text-center"
              disabled={busy || backendOffline}
              onClick={() => run(async () => {
                const created = await api("/tables", {
                  method: "POST",
                  body: JSON.stringify({ stake_amount: stake, max_players: 2, mode }),
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
            {visibleTables.map((item) => (
              <div key={item.table_id} className="flex flex-col items-start justify-between gap-3 rounded-lg border border-zinc-800 bg-zinc-950 p-4 sm:flex-row sm:items-center">
                <div>
                  <div className="font-display text-2xl tracking-widest">{item.mode_label || "Flipget"}</div>
                  <div className="text-sm text-zinc-500">{item.seats.length}/2 seats / {item.status} / Round {item.current_round_number || 1}</div>
                </div>
                <div className="flex w-full flex-wrap gap-2 sm:w-auto">
                  <button className="btn-secondary" disabled={busy || backendOffline || item.status !== "waiting"} onClick={() => run(async () => {
                    await api(`/tables/${item.table_id}/join`, { method: "POST" });
                    navigate(`/flipget/${item.table_id}`);
                  })}>Join Table</button>
                  <Link className="btn-ghost" to={`/flipget/${item.table_id}`}>View</Link>
                </div>
              </div>
            ))}
            {!showAllTables && tables.length > 5 && (
              <button
                type="button"
                onClick={() => setShowAllTables(true)}
                className="rounded-lg border border-zinc-800 bg-zinc-950 p-4 text-xs uppercase tracking-widest text-zinc-400 hover:text-yellow-300"
              >
                Show all {tables.length} open Flipget tables
              </button>
            )}
          </div>
          {howToPlayOpen && (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 px-4">
              <div className="w-full max-w-2xl rounded-lg border border-yellow-700/50 bg-zinc-950 p-6 shadow-2xl">
                <div className="flex items-center justify-between gap-4">
                  <div className="font-display text-2xl tracking-widest text-yellow-100">How to Play Flipget</div>
                  <button className="btn-ghost" type="button" onClick={() => setHowToPlayOpen(false)}>Close</button>
                </div>
                <ul className="mt-5 space-y-2 text-sm leading-6 text-zinc-300">
                  <li>Flipget is a 2-player coin-flip game.</li>
                  <li>Choose Single Flip, Best of 3, or Best of 5.</li>
                  <li>Each round requires a fresh Heads/Tails choice, then both participants ready up before the flip.</li>
                  <li>Single Flip settles after one flip. Best of 3 requires 2 round wins; Best of 5 requires 3 round wins.</li>
                  <li>Round History shows the coin result, winning side, winning participant, and each participant choice for every completed round.</li>
                  <li>The local demo helper can add exactly one demo opponent.</li>
                  <li>Leaving during an active match may count as a loss and may lose the reserved demo stake.</li>
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
            <button className="btn-ghost" type="button" onClick={requestExit}>Back to Flipget</button>
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
        {table && (
          <div className="mt-3 text-sm leading-6 text-zinc-500">
            Mode: {table.mode_label || "Single Flip"} / Round {table.current_round_number || 1} / {table.max_rounds || 1}<br />
            Heads {table.score?.heads || 0} - Tails {table.score?.tails || 0}<br />
            Player round wins: {playerRoundWins} / Opponent round wins: {opponentRoundWins}<br />
            Current round result: {lastCompletedRound ? `${lastCompletedRound.result} won round ${lastCompletedRound.round_number}` : "No completed round yet"}<br />
            Match status: {table.status === "settled" ? "settled" : "active"}
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
                  || backendOffline
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
              <button className="btn-primary" disabled={busy || backendOffline || !mySeat?.side || mySeat.ready || ["flipping", "settled"].includes(table?.status)} onClick={() => run(() => api(`/tables/${table.table_id}/ready`, { method: "POST" }))}>Ready Up</button>
              {mySeat && (
                <button className="btn-secondary" title={actionHint} disabled={busy || backendOffline || !canFlip} onClick={() => run(() => api(`/tables/${table.table_id}/flip`, { method: "POST" }))}>Flip Coin</button>
              )}
              {mySeat && table?.status === "waiting" && (table.seats?.length || 0) < 2 && (
                <button
                  className="btn-secondary"
                  title={canAddDemoOpponent ? "Adds a local demo participant on the opposite side and readies that seat." : actionHint}
                  disabled={busy || backendOffline || !canAddDemoOpponent}
                  onClick={() => run(() => api(`/tables/${table.table_id}/add-demo-opponent`, {
                    method: "POST",
                    body: JSON.stringify({ username: "Demo Opponent" }),
                  }))}
                >
                  Add Demo Opponent
                </button>
              )}
              {mySeat && !canFlip && table?.status !== "settled" && (
                <div
                  data-testid="flipget-action-hint"
                  className="w-full rounded border border-zinc-800 bg-black/30 p-3 text-center text-sm leading-6 text-zinc-500"
                >
                  {actionHint} This local demo does not route Flipget through
                  Target table WebSockets.
                </div>
              )}
            </div>
          </div>
          <div className="grid gap-4">
            <Seat seat={table?.seats?.[0]} fallbackIndex={0} />
            <Seat seat={table?.seats?.[1]} fallbackIndex={1} />
            {completedRounds.length > 0 && (
              <div className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-4">
                <div className="text-xs uppercase tracking-widest text-zinc-500">Round History</div>
                <div className="mt-3 grid gap-3">
                  {completedRounds.map((round) => (
                    <div key={round.id} className="rounded border border-zinc-800 bg-black/30 p-3 text-sm leading-6 text-zinc-400">
                      <div className="font-display text-xl tracking-widest text-zinc-100">Round {round.round_number}</div>
                      <div>Coin result: {round.result ? round.result.charAt(0).toUpperCase() + round.result.slice(1) : "-"}</div>
                      <div>Winning side: {round.result ? round.result.charAt(0).toUpperCase() + round.result.slice(1) : "-"}</div>
                      <div>Winning participant: {participantLabel(round.winner_user_id)}</div>
                      <div className="text-xs text-zinc-500">
                        Player chose {participantSide(round, user?.user_id)} / Demo Opponent chose {participantSide(round, demoOpponentSeat?.user_id)}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {table?.status === "waiting" && table.seats?.length < 2 && (
              <div className="rounded-lg border border-dashed border-zinc-800 bg-zinc-950/40 p-4 text-sm text-zinc-500">
                Waiting for one more demo participant. Flip requires two demo participants with unique sides.
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
              {table.winning_side || table.round?.result} wins / winner: {table.round?.winner_user_id}
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
        {howToPlayOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 px-4">
            <div className="w-full max-w-2xl rounded-lg border border-yellow-700/50 bg-zinc-950 p-6 shadow-2xl">
              <div className="flex items-center justify-between gap-4">
                <div className="font-display text-2xl tracking-widest text-yellow-100">How to Play Flipget</div>
                <button className="btn-ghost" type="button" onClick={() => setHowToPlayOpen(false)}>Close</button>
              </div>
              <ul className="mt-5 space-y-2 text-sm leading-6 text-zinc-300">
                <li>Flipget is a 2-player coin-flip game.</li>
                <li>Choose Single Flip, Best of 3, or Best of 5.</li>
                <li>Each round requires a fresh Heads/Tails choice, then both participants ready up before the flip.</li>
                <li>Single Flip settles after one flip. Best of 3 requires 2 round wins; Best of 5 requires 3 round wins.</li>
                <li>Round History shows the coin result, winning side, winning participant, and each participant choice for every completed round.</li>
                <li>The local demo helper can add exactly one demo opponent.</li>
                <li>Leaving during an active match may count as a loss and may lose the reserved demo stake.</li>
              </ul>
            </div>
          </div>
        )}
        {exitConfirmOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 px-4">
            <div className="w-full max-w-md rounded-lg border border-yellow-700/50 bg-zinc-950 p-6 shadow-2xl">
              <div className="font-display text-2xl tracking-widest text-yellow-100">Leave Active Flipget?</div>
              <p className="mt-4 text-sm leading-6 text-zinc-300">
                Leaving may cause the current stake or participation to be lost. Flipget will keep the table state on the backend if you exit this screen.
              </p>
              <div className="mt-6 flex flex-wrap justify-end gap-3">
                <button className="btn-secondary" type="button" onClick={() => setExitConfirmOpen(false)}>Stay</button>
                <button className="btn-primary" type="button" onClick={() => navigate("/flipget")}>Leave Flipget</button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
