import React, { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { apiFetch } from "../lib/api";

const DISCLAIMER =
  "Axwins currently uses internal demo credits only. Deposits, withdrawals, cash-out, crypto, card payments, and real-money trading are not enabled.";

const ADMIN_FIELD_HELP = {
  title: "Short public question for the demo market list.",
  description: "Plain-language context shown on the market detail page.",
  category: "Grouping label for filtering and scanning.",
  close_time: "ISO timestamp used by the demo backend lifecycle rules.",
  resolution_criteria: "How a demo resolver should decide YES, NO, cancelled, or invalid.",
  source_url: "Optional reference URL for the demo resolver.",
  initial_liquidity: "Internal demo-credit liquidity seed. This is not real money.",
};

const ADMIN_ACTIONS = [
  ["open", "Open", "Allow demo-credit buying and selling."],
  ["pause", "Pause", "Temporarily stop trading without resolving."],
  ["close", "Close", "Stop trading before resolution."],
  ["cancel", "Cancel", "Trigger demo-credit refund handling."],
  ["resolve", "Resolve", "Set the selected outcome and run demo settlement."],
];

const STATUS_COPY = {
  draft: {
    label: "Draft",
    helper: "Admin-only draft. Open this demo market before buying or selling YES/NO.",
  },
  open: {
    label: "Open",
    helper: "Demo-credit YES/NO buying and selling is enabled.",
  },
  paused: {
    label: "Paused",
    helper: "Demo-credit buying and selling is temporarily paused.",
  },
  closed: {
    label: "Closed",
    helper: "Buying and selling are closed while this market waits for demo resolution.",
  },
  resolved: {
    label: "Resolved",
    helper: "This market has been resolved and demo settlement is complete.",
  },
  cancelled: {
    label: "Cancelled",
    helper: "This market was cancelled and eligible demo-credit refunds are handled by admin controls.",
  },
};
const MARKET_STATUS_RANK = { open: 0, draft: 1, paused: 2, closed: 3, resolved: 4, cancelled: 5 };

function storedUser() {
  try {
    return JSON.parse(localStorage.getItem("target_user") || "null");
  } catch {
    return null;
  }
}

function authHeaders(extra = {}) {
  const user = storedUser();
  return {
    ...(user?.token ? { Authorization: `Bearer ${user.token}` } : {}),
    ...extra,
  };
}

async function apiJson(path, options = {}) {
  let response;
  try {
    response = await apiFetch(path, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(options.headers || {}),
      },
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
    throw new Error(data?.detail?.code || data?.detail || `HTTP_${response.status}`);
  }
  return data;
}

function friendlyTmargetError(message) {
  const raw = String(message || "");
  if (raw.includes("BACKEND_OFFLINE") || raw.toLowerCase().includes("failed to fetch")) {
    return "Backend is offline. Demo markets and trading actions are unavailable. Start the local backend with .\\scripts\\start-backend-local.ps1 and retry Tmarget.";
  }
  if (raw.includes("SESSION_EXPIRED") || raw.includes("INVALID_TOKEN") || raw.includes("MISSING_TOKEN")) {
    return "Session expired. Sign in through the Axwins lobby again to continue Tmarget demo-credit actions.";
  }
  return raw;
}

function formatPrice(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(2) : "--";
}

function formatCredits(value) {
  return Number(value || 0).toLocaleString();
}

function statusLabel(value) {
  return STATUS_COPY[value]?.label || String(value || "unknown").replaceAll("_", " ");
}

function statusHelper(value) {
  return STATUS_COPY[value]?.helper || "Lifecycle state is controlled from Admin Markets.";
}

function tradeDisabledMessage({ user, market }) {
  if (!user?.token) return "Sign in through the lobby to use demo-credit trading.";
  if (!market?.id) return "Trading is unavailable until a backend market is loaded.";
  if (market.status === "draft") return "Open this demo market before buying YES/NO.";
  if (market.status !== "open") return statusHelper(market.status);
  return "";
}

function TmargetShell({ children }) {
  const [howToPlayOpen, setHowToPlayOpen] = useState(false);
  return (
    <div className="min-h-screen bg-black text-zinc-100">
      <header className="border-b border-zinc-800 bg-zinc-950/80">
        <div className="mx-auto flex max-w-6xl flex-col items-start justify-between gap-4 px-4 py-4 sm:flex-row sm:items-center sm:px-6">
          <Link to="/tmarget" className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded border border-yellow-700/60 bg-black font-display text-lg tracking-widest text-yellow-200">
              AX
            </div>
            <div>
              <div className="font-luxe text-xs uppercase tracking-[0.4em] text-yellow-300">
                Tmarget
              </div>
              <div className="text-xs text-zinc-500">Axwins demo prediction market product</div>
            </div>
          </Link>
          <nav className="flex w-full flex-wrap items-center justify-start gap-2 text-xs uppercase tracking-widest text-zinc-400 sm:w-auto sm:justify-end">
            <Link className="rounded border border-zinc-800 px-3 py-2 text-center hover:text-yellow-300" to="/">
              Axwins
            </Link>
            <Link className="rounded border border-zinc-800 px-3 py-2 text-center hover:text-yellow-300" to="/games">
              Games
            </Link>
            <Link className="rounded border border-zinc-800 px-3 py-2 text-center hover:text-yellow-300" to="/tmarget">
              Tmarget
            </Link>
            <Link className="rounded border border-zinc-800 px-3 py-2 text-center hover:text-yellow-300" to="/tmarget/markets">
              Markets
            </Link>
            <Link className="rounded border border-zinc-800 px-3 py-2 text-center hover:text-yellow-300" to="/tmarget/portfolio">
              Portfolio
            </Link>
            <Link className="rounded border border-zinc-800 px-3 py-2 text-center hover:text-yellow-300" to="/tmarget/admin/markets">
              Admin
            </Link>
            <button className="rounded border border-yellow-700/60 px-3 py-2 text-center text-yellow-300 hover:bg-yellow-500/10" type="button" onClick={() => setHowToPlayOpen(true)}>
              How to Play
            </button>
            <Link className="rounded border border-zinc-800 px-3 py-2 text-center hover:text-yellow-300" to="/wallet">
              Wallet / Ledger
            </Link>
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
        <div className="mb-6 rounded-lg border border-yellow-700/40 bg-yellow-500/10 p-4 text-sm leading-6 text-yellow-100">
          {DISCLAIMER}
        </div>
        {children}
      </main>
      {howToPlayOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 px-4">
          <div className="w-full max-w-2xl rounded-lg border border-yellow-700/50 bg-zinc-950 p-6 shadow-2xl">
            <div className="flex items-center justify-between gap-4">
              <div className="font-display text-2xl tracking-widest text-yellow-100">How to Play Tmarget</div>
              <button className="rounded border border-zinc-700 px-4 py-2 text-xs uppercase tracking-widest text-zinc-300" type="button" onClick={() => setHowToPlayOpen(false)}>Close</button>
            </div>
            <TmargetHowToPlay />
          </div>
        </div>
      )}
    </div>
  );
}

function MarketCard({ market }) {
  return (
    <Link
      to={`/tmarget/markets/${market.slug || market.id}`}
      className="rounded-lg border border-zinc-800 bg-zinc-950 p-5 transition hover:border-yellow-600/70"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-xs uppercase tracking-[0.3em] text-zinc-500">{market.category}</div>
          <h2 className="mt-2 font-display text-2xl tracking-widest text-zinc-100">{market.title}</h2>
        </div>
        <span className="rounded-full border border-zinc-700 px-3 py-1 text-[10px] uppercase tracking-widest text-zinc-500">
          {statusLabel(market.status)}
        </span>
      </div>
      <div className="mt-3 text-xs leading-5 text-zinc-500">{statusHelper(market.status)}</div>
      <div className="mt-5 grid grid-cols-2 gap-3">
        <div className="rounded border border-emerald-800/60 bg-emerald-500/5 p-3">
          <div className="text-xs uppercase tracking-widest text-emerald-400">YES</div>
          <div className="mt-1 font-display text-2xl text-emerald-200">{formatPrice(market.yes_price)}</div>
        </div>
        <div className="rounded border border-rose-800/60 bg-rose-500/5 p-3">
          <div className="text-xs uppercase tracking-widest text-rose-400">NO</div>
          <div className="mt-1 font-display text-2xl text-rose-200">{formatPrice(market.no_price)}</div>
        </div>
      </div>
      <div className="mt-4 flex items-center justify-between gap-3 text-sm text-zinc-500">
        <span>{market.close_time}</span>
        <span>Volume {formatCredits(market.volume)}</span>
      </div>
    </Link>
  );
}

function LoadingBox({ text = "Loading..." }) {
  return <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-5 text-zinc-400">{text}</div>;
}

function ErrorBox({ error }) {
  if (!error) return null;
  return <div className="rounded-lg border border-rose-800 bg-rose-950/30 p-5 text-rose-200">{error}</div>;
}

function TmargetHowToPlay({ className = "" }) {
  return (
    <section className={`rounded-lg border border-zinc-800 bg-zinc-950/60 p-4 ${className}`}>
      <div className="text-xs uppercase tracking-widest text-zinc-500">How to Play</div>
      <ul className="mt-3 space-y-2 text-sm leading-6 text-zinc-400">
        <li>Tmarget is a demo prediction-market product, not a game.</li>
        <li>Market lifecycle states are draft, open, paused, closed, resolved, and cancelled.</li>
        <li>Open markets let signed-in users buy or sell YES/NO positions with internal demo credits only.</li>
        <li>Positions show how many demo shares you hold on each outcome.</li>
        <li>Market volume increases when demo-credit buy or sell trades are recorded.</li>
        <li>Public market pages show the market, prices, positions, trades, and disabled reasons. Admin Markets is the demo-only place for create/open/pause/close/resolve/cancel lifecycle controls.</li>
        <li>Draft markets must be opened from Admin Markets before buying or selling is enabled. Paused and closed markets block new trades until lifecycle controls change state.</li>
        <li>Resolved or cancelled markets use the current demo backend settlement/refund rules.</li>
        <li>No real-money trading, oracle, KYC, dispute, order book, deposits, withdrawals, or production market behavior is enabled here.</li>
      </ul>
    </section>
  );
}

export function TmargetHomePage() {
  const links = [
    ["Markets", "/tmarget/markets", "Browse demo prediction markets backed by internal credits."],
    ["Portfolio", "/tmarget/portfolio", "View open and settled demo positions."],
    ["Admin Markets", "/tmarget/admin/markets", "Demo-only market creation and lifecycle controls."],
    ["Wallet", "/wallet", "Shared internal demo-credit wallet and ledger."],
  ];
  return (
    <TmargetShell>
      <section className="grid gap-8 lg:grid-cols-[1fr_0.9fr] lg:items-start">
        <div>
          <div className="font-luxe text-xs uppercase tracking-[0.45em] text-yellow-300">
            Separate product module
          </div>
          <h1 className="mt-2 font-display text-5xl tracking-widest text-zinc-100 sm:text-6xl">Tmarget</h1>
          <p className="mt-5 max-w-2xl text-base leading-7 text-zinc-400">
            Tmarget is a demo prediction market product. It is separate from
            Target, Diceget, and Flipget game modules, while sharing internal
            auth, wallet, ledger, audit, and admin infrastructure.
          </p>
        </div>
        <div className="grid gap-3">
          {links.map(([title, href, description]) => (
            <Link key={href} to={href} className="rounded-lg border border-zinc-800 bg-zinc-950 p-4 hover:border-yellow-600/70">
              <div className="font-display text-2xl tracking-widest">{title}</div>
              <div className="mt-2 text-sm text-zinc-500">{description}</div>
            </Link>
          ))}
        </div>
      </section>
    </TmargetShell>
  );
}

export function TmargetMarketsPage() {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("all");
  const [markets, setMarkets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showAllMarkets, setShowAllMarkets] = useState(false);

  useEffect(() => {
    let alive = true;
    async function load() {
      setLoading(true);
      setError("");
      try {
        const data = await apiJson("/api/tmarget/markets");
        if (!alive) return;
        setMarkets(data?.markets || []);
      } catch (err) {
        if (!alive) return;
        setMarkets([]);
        setError(friendlyTmargetError(err.message));
      } finally {
        if (alive) setLoading(false);
      }
    }
    load();
    return () => {
      alive = false;
    };
  }, []);

  const categories = useMemo(() => {
    return ["all", ...Array.from(new Set(markets.map((m) => m.category).filter(Boolean)))];
  }, [markets]);

  const filtered = markets.filter((market) => {
    const matchesQuery = market.title.toLowerCase().includes(query.toLowerCase());
    const matchesCategory = category === "all" || market.category === category;
    return matchesQuery && matchesCategory;
  });
  const sortedMarkets = [...filtered].sort((a, b) => (MARKET_STATUS_RANK[a.status] ?? 9) - (MARKET_STATUS_RANK[b.status] ?? 9));
  const visibleMarkets = showAllMarkets ? sortedMarkets : sortedMarkets.slice(0, 5);

  return (
    <TmargetShell>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="font-luxe text-xs uppercase tracking-[0.45em] text-yellow-300">Demo Markets</div>
          <h1 className="mt-2 font-display text-5xl tracking-widest">Markets</h1>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-zinc-400">
            Tmarget markets are demo prediction markets, not games. Prices and
            positions use internal demo credits only.
          </p>
        </div>
        <div className="grid w-full gap-3 sm:w-auto sm:grid-cols-2">
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search markets"
            className="w-full rounded border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100"
          />
          <select
            value={category}
            onChange={(event) => setCategory(event.target.value)}
            className="w-full rounded border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100"
          >
            {categories.map((item) => <option key={item}>{item}</option>)}
          </select>
        </div>
      </div>
      {loading && <LoadingBox text="Loading markets..." />}
      <ErrorBox error={error} />
      {!loading && filtered.length === 0 && (
        <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-5 text-zinc-400">
          No demo markets found. Clear the filters or open the demo admin page
          to create an internal-credit market.
        </div>
      )}
      <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {visibleMarkets.map((market) => <MarketCard key={market.id || market.slug} market={market} />)}
      </div>
      {!showAllMarkets && filtered.length > 5 && (
        <button
          type="button"
          onClick={() => setShowAllMarkets(true)}
          className="mt-4 w-full rounded-lg border border-zinc-800 bg-zinc-950 p-4 text-xs uppercase tracking-widest text-zinc-400 hover:text-yellow-300"
        >
          Show all {filtered.length} demo markets
        </button>
      )}
    </TmargetShell>
  );
}

export function TmargetMarketDetailPlaceholder() {
  const { slug } = useParams();
  const navigate = useNavigate();
  const [market, setMarket] = useState(null);
  const [trades, setTrades] = useState([]);
  const [positions, setPositions] = useState([]);
  const [outcome, setOutcome] = useState("yes");
  const [shares, setShares] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [exitConfirmOpen, setExitConfirmOpen] = useState(false);
  const user = storedUser();

  async function load() {
    setLoading(true);
    setError("");
    try {
      const data = await apiJson(`/api/tmarget/markets/${slug}`);
      if (!data?.id) {
        throw new Error("MARKET_NOT_FOUND");
      }
      setMarket(data);
      const tradesData = await apiJson(`/api/tmarget/markets/${data.id}/trades`);
      setTrades(tradesData?.trades || []);
      if (user?.token) {
        const posData = await apiJson(`/api/tmarget/markets/${data.id}/positions`, {
          headers: authHeaders(),
        });
        setPositions(posData?.positions || []);
      } else {
        setPositions([]);
      }
    } catch (err) {
      setMarket(null);
      setTrades([]);
      setPositions([]);
      setError(friendlyTmargetError(err.message));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug, user?.token]);

  async function trade(side) {
    if (!market?.id) return;
    setNotice("");
    setError("");
    try {
      await apiJson(`/api/tmarget/markets/${market.id}/${side}`, {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify({ outcome, shares: Number(shares) }),
      });
      setNotice(`${side === "buy" ? "Bought" : "Sold"} ${shares} ${outcome.toUpperCase()} demo shares.`);
      await load();
    } catch (err) {
      setError(friendlyTmargetError(err.message));
    }
  }

  async function openDraftMarket() {
    if (!market?.id) return;
    setNotice("");
    setError("");
    try {
      await apiJson(`/api/tmarget/admin/markets/${market.id}/open`, {
        method: "POST",
        headers: authHeaders({ "X-Axwins-Demo-Admin": "true" }),
      });
      setNotice("Market opened for demo-credit YES/NO buying.");
      await load();
    } catch (err) {
      setError(friendlyTmargetError(err.message));
    }
  }

  const canTrade = Boolean(user?.token && market?.id && market.status === "open");
  const disabledTradeMessage = tradeDisabledMessage({ user, market });
  const yesPosition = positions.find((pos) => pos.outcome === "yes");
  const noPosition = positions.find((pos) => pos.outcome === "no");
  const hasActiveDemoExposure = positions.some((pos) => Number(pos.shares || 0) > 0);
  const requestMarketExit = () => {
    if (hasActiveDemoExposure) {
      setExitConfirmOpen(true);
      return;
    }
    navigate("/tmarget/markets");
  };

  return (
    <TmargetShell>
      {loading && <LoadingBox text="Loading market..." />}
      <ErrorBox error={error} />
      {notice && <div className="mb-4 rounded-lg border border-emerald-800 bg-emerald-950/30 p-4 text-emerald-200">{notice}</div>}
      {!loading && !market && !error && (
        <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-5 text-zinc-400">
          Market unavailable. Return to Markets or create an open demo market from Admin Markets.
        </div>
      )}
      {market && (
        <div className="grid gap-8 lg:grid-cols-[1fr_360px]">
          <section>
            <div className="text-xs uppercase tracking-[0.35em] text-zinc-500">{market.category}</div>
            <h1 className="mt-2 font-display text-4xl tracking-widest sm:text-5xl">{market.title}</h1>
            <div className="mt-4 flex flex-wrap gap-2 text-xs uppercase tracking-widest">
              <button type="button" onClick={requestMarketExit} className="rounded border border-zinc-800 px-3 py-2 text-zinc-400 hover:text-yellow-300">
                Back to Markets
              </button>
              <Link to="/wallet" className="rounded border border-zinc-800 px-3 py-2 text-zinc-400 hover:text-yellow-300">
                Wallet / Ledger
              </Link>
            </div>
            <p className="mt-5 text-base leading-7 text-zinc-400">{market.description}</p>
            <div className="mt-6 rounded-lg border border-zinc-800 bg-zinc-950 p-5">
              <div className="text-xs uppercase tracking-[0.35em] text-zinc-500">Resolution Criteria</div>
              <p className="mt-3 text-sm leading-6 text-zinc-400">{market.rule?.resolution_criteria}</p>
              {market.rule?.source_url && (
                <div className="mt-3 text-sm text-zinc-500">Source: {market.rule.source_url}</div>
              )}
            </div>
            <div className="mt-6 rounded-lg border border-zinc-800 bg-zinc-950 p-5">
              <div className="text-xs uppercase tracking-[0.35em] text-zinc-500">Recent Trades</div>
              {trades.length === 0 ? (
                <div className="mt-3 text-sm text-zinc-500">No trades yet.</div>
              ) : (
                <div className="mt-3 grid gap-2 text-sm">
                  {trades.slice(-8).reverse().map((trade) => (
                    <div key={trade.id} className="flex flex-wrap justify-between gap-2 border-b border-zinc-900 py-2 text-zinc-400">
                      <span>{trade.side.toUpperCase()} {trade.outcome.toUpperCase()} x{trade.shares}</span>
                      <span>{formatCredits(trade.cost)} credits @ {formatPrice(trade.price)}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </section>
          <aside className="rounded-lg border border-zinc-800 bg-zinc-950 p-5">
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded border border-emerald-800/60 bg-emerald-500/5 p-4">
                <div className="text-xs uppercase tracking-widest text-emerald-400">YES</div>
                <div className="mt-2 font-display text-3xl text-emerald-200">{formatPrice(market.yes_price)}</div>
              </div>
              <div className="rounded border border-rose-800/60 bg-rose-500/5 p-4">
                <div className="text-xs uppercase tracking-widest text-rose-400">NO</div>
                <div className="mt-2 font-display text-3xl text-rose-200">{formatPrice(market.no_price)}</div>
              </div>
            </div>
            <div className="mt-4 rounded border border-zinc-800 bg-black/40 p-3 text-sm text-zinc-500">
              Status: <span className="text-zinc-300">{statusLabel(market.status)}</span><br />
              <span>{statusHelper(market.status)}</span><br />
              Volume: {formatCredits(market.volume)} credits<br />
              Your YES: {yesPosition?.shares || 0} shares<br />
              Your NO: {noPosition?.shares || 0} shares
            </div>
            <div className="mt-4 rounded border border-yellow-700/30 bg-yellow-500/5 p-3 text-xs leading-5 text-yellow-100">
              Demo-credit trading is available only for signed-in users on open
              backend markets. No real funds, deposits, withdrawals, card
              payments, crypto transfers, or live real-money trading are enabled.
            </div>
            <div className="mt-5 grid gap-3">
              <select
                value={outcome}
                onChange={(event) => setOutcome(event.target.value)}
                disabled={!canTrade}
                className="rounded border border-zinc-700 bg-black px-3 py-3 text-sm text-zinc-100 disabled:text-zinc-600"
              >
                <option value="yes">YES</option>
                <option value="no">NO</option>
              </select>
              <input
                type="number"
                min="1"
                value={shares}
                onChange={(event) => setShares(event.target.value)}
                disabled={!canTrade}
                className="rounded border border-zinc-700 bg-black px-3 py-3 text-sm text-zinc-100 disabled:text-zinc-600"
              />
              <button
                disabled={!canTrade}
                onClick={() => trade("buy")}
                className="rounded border border-emerald-700 px-4 py-3 text-sm uppercase tracking-widest text-emerald-200 disabled:border-zinc-700 disabled:text-zinc-500"
              >
                {canTrade ? "Buy Demo Shares" : "Buy Disabled"}
              </button>
              <button
                disabled={!canTrade}
                onClick={() => trade("sell")}
                className="rounded border border-rose-700 px-4 py-3 text-sm uppercase tracking-widest text-rose-200 disabled:border-zinc-700 disabled:text-zinc-500"
              >
                {canTrade ? "Sell Demo Shares" : "Sell Disabled"}
              </button>
              {!canTrade && (
                <div className="rounded border border-zinc-800 bg-black/40 p-3 text-xs leading-5 text-zinc-500">
                  {disabledTradeMessage}
                  {market?.id && market.status === "draft" && (
                    <div className="mt-3 grid gap-2">
                      <button
                        className="rounded border border-yellow-700 px-3 py-2 text-xs uppercase tracking-widest text-yellow-200 hover:bg-yellow-500/10"
                        onClick={openDraftMarket}
                      >
                        Open Market Now
                      </button>
                      <Link to="/tmarget/admin/markets" className="text-yellow-300 hover:text-yellow-200">
                        Or manage lifecycle in Admin Markets.
                      </Link>
                    </div>
                  )}
                </div>
              )}
            </div>
          </aside>
        </div>
      )}
      {exitConfirmOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 px-4">
          <div className="w-full max-w-md rounded-lg border border-yellow-700/50 bg-zinc-950 p-6 shadow-2xl">
            <div className="font-display text-2xl tracking-widest text-yellow-100">Leave Market Detail?</div>
            <p className="mt-4 text-sm leading-6 text-zinc-300">
              Leaving may cause the current demo-credit participation view to be lost. Your Tmarget positions remain on the backend.
            </p>
            <div className="mt-6 flex flex-wrap justify-end gap-3">
              <button className="rounded border border-zinc-700 px-4 py-2 text-sm uppercase tracking-widest text-zinc-300" type="button" onClick={() => setExitConfirmOpen(false)}>Stay</button>
              <button className="rounded border border-yellow-600 bg-yellow-500/10 px-4 py-2 text-sm uppercase tracking-widest text-yellow-100" type="button" onClick={() => navigate("/tmarget/markets")}>Leave Market</button>
            </div>
          </div>
        </div>
      )}
    </TmargetShell>
  );
}

export function TmargetPortfolioPage() {
  const [positions, setPositions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const user = storedUser();

  useEffect(() => {
    let alive = true;
    async function load() {
      setLoading(true);
      setError("");
      try {
        const data = await apiJson("/api/tmarget/me/positions", { headers: authHeaders() });
        if (!alive) return;
        setPositions(data?.positions || []);
      } catch (err) {
        if (alive) setError(user?.token ? friendlyTmargetError(err.message) : "Sign in through the lobby to view Tmarget positions.");
      } finally {
        if (alive) setLoading(false);
      }
    }
    load();
    return () => {
      alive = false;
    };
  }, [user?.token]);

  return (
    <TmargetShell>
      <div className="max-w-4xl">
        <div className="font-luxe text-xs uppercase tracking-[0.45em] text-yellow-300">Portfolio</div>
        <h1 className="mt-2 font-display text-5xl tracking-widest">Positions</h1>
        <p className="mt-5 text-base leading-7 text-zinc-400">
          Tmarget positions use internal demo credits only. Resolved and open
          positions appear here after demo trades.
        </p>
        <Link to="/wallet" className="btn-secondary mt-6 inline-flex">View Wallet / Ledger</Link>
        <div className="mt-6">
          {loading && <LoadingBox text="Loading positions..." />}
          <ErrorBox error={error} />
          {!loading && !error && positions.length === 0 && (
            <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-5 text-sm leading-6 text-zinc-400">
              No Tmarget positions yet. Open demo markets to inspect available
              internal-credit positions, or use Wallet / Ledger to review demo
              credit activity.
              <div className="mt-4 flex flex-wrap gap-2">
                <Link to="/tmarget/markets" className="rounded border border-zinc-700 px-3 py-2 text-xs uppercase tracking-widest text-zinc-300 hover:text-yellow-300">
                  View Markets
                </Link>
                <Link to="/wallet" className="rounded border border-zinc-700 px-3 py-2 text-xs uppercase tracking-widest text-zinc-300 hover:text-yellow-300">
                  Wallet / Ledger
                </Link>
              </div>
            </div>
          )}
          {positions.length > 0 && (
            <div className="overflow-x-auto rounded-lg border border-zinc-800 bg-zinc-950 p-5">
              <table className="w-full min-w-[680px] text-left text-sm">
                <thead className="border-b border-zinc-800 text-xs uppercase tracking-widest text-zinc-500">
                  <tr>
                    <th className="py-3 pr-4">Market</th>
                    <th className="py-3 pr-4">Outcome</th>
                    <th className="py-3 pr-4 text-right">Shares</th>
                    <th className="py-3 pr-4 text-right">Avg Price</th>
                    <th className="py-3 pr-4 text-right">Realized P/L</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.map((pos) => (
                    <tr key={`${pos.market_id}-${pos.outcome}`} className="border-b border-zinc-900 text-zinc-300">
                      <td className="py-3 pr-4">{pos.market_id}</td>
                      <td className="py-3 pr-4 uppercase">{pos.outcome}</td>
                      <td className="py-3 pr-4 text-right">{pos.shares}</td>
                      <td className="py-3 pr-4 text-right">{formatPrice(pos.avg_price)}</td>
                      <td className="py-3 pr-4 text-right">{formatCredits(pos.realized_pnl)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </TmargetShell>
  );
}

export function TmargetAdminMarketsPage() {
  const [markets, setMarkets] = useState([]);
  const [form, setForm] = useState({
    title: "",
    description: "",
    category: "General",
    close_time: "2030-01-01T00:00:00Z",
    resolution_criteria: "",
    source_url: "",
    initial_liquidity: 100,
  });
  const [resolution, setResolution] = useState({ outcome: "yes", resolver_notes: "" });
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [createdMarket, setCreatedMarket] = useState(null);

  async function load() {
    try {
      const data = await apiJson("/api/tmarget/markets");
      setMarkets(data?.markets || []);
    } catch (err) {
      setError(friendlyTmargetError(err.message));
    }
  }

  useEffect(() => {
    load();
  }, []);

  function update(field, value) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  async function submitMarket(openAfterCreate = false) {
    setError("");
    setNotice("");
    setCreatedMarket(null);
    try {
      let created = await apiJson("/api/tmarget/admin/markets", {
        method: "POST",
        headers: authHeaders({ "X-Axwins-Demo-Admin": "true" }),
        body: JSON.stringify({
          ...form,
          initial_liquidity: Number(form.initial_liquidity),
        }),
      });
      if (openAfterCreate) {
        created = await apiJson(`/api/tmarget/admin/markets/${created.id}/open`, {
          method: "POST",
          headers: authHeaders({ "X-Axwins-Demo-Admin": "true" }),
        });
      }
      setCreatedMarket(created);
      setNotice(openAfterCreate ? "Demo market created and opened for YES/NO buying." : "Demo market created as draft. Open it before buying.");
      setForm((prev) => ({ ...prev, title: "", description: "", resolution_criteria: "", source_url: "" }));
      await load();
    } catch (err) {
      setError(friendlyTmargetError(err.message));
    }
  }

  async function createMarket(event) {
    event.preventDefault();
    await submitMarket(false);
  }

  async function action(marketId, name) {
    setError("");
    setNotice("");
    try {
      const body = name === "resolve" ? JSON.stringify(resolution) : undefined;
      await apiJson(`/api/tmarget/admin/markets/${marketId}/${name}`, {
        method: "POST",
        headers: authHeaders({ "X-Axwins-Demo-Admin": "true" }),
        body,
      });
      setNotice(`Market ${name} complete.`);
      setCreatedMarket(null);
      await load();
    } catch (err) {
      setError(friendlyTmargetError(err.message));
    }
  }

  return (
    <TmargetShell>
      <div className="mb-8 grid gap-4 lg:grid-cols-[1fr_360px]">
        <section>
          <div className="font-luxe text-xs uppercase tracking-[0.45em] text-yellow-300">Tmarget Demo Admin</div>
          <h1 className="mt-2 font-display text-5xl tracking-widest">Admin Markets</h1>
          <p className="mt-4 max-w-3xl text-sm leading-6 text-zinc-400">
            Tmarget is a demo prediction market product inside Axwins. It is not
            a game, and this page is only local/internal demo tooling for binary
            YES/NO markets.
          </p>
        </section>
        <aside className="rounded-lg border border-yellow-700/40 bg-yellow-500/10 p-4 text-sm leading-6 text-yellow-100">
          Demo admin requests use <span className="font-mono text-xs">X-Axwins-Demo-Admin: true</span>.
          This header is not production authorization. Resolving or cancelling a
          market affects internal demo-credit settlement/refund records only; no
          real funds are involved.
        </aside>
      </div>
      <div className="grid gap-8 lg:grid-cols-[420px_1fr]">
        <section className="rounded-lg border border-zinc-800 bg-zinc-950 p-5">
          <div className="text-xs uppercase tracking-[0.35em] text-zinc-500">Create Demo Market</div>
          <h2 className="mt-2 font-display text-3xl tracking-widest">Market Details</h2>
          <p className="mt-3 text-sm leading-6 text-zinc-400">
            Create only demo binary markets backed by internal demo credits. No
            payment, compliance, oracle, dispute, or real-money flow is enabled here.
          </p>
          <form onSubmit={createMarket} className="mt-6 grid gap-4">
            {[
              ["title", "Title"],
              ["description", "Description"],
              ["category", "Category"],
              ["close_time", "Close time"],
              ["resolution_criteria", "Resolution criteria"],
              ["source_url", "Source URL"],
              ["initial_liquidity", "Initial liquidity"],
            ].map(([field, label]) => (
              <label key={field} className="text-xs uppercase tracking-widest text-zinc-500">
                {label}
                <input
                  value={form[field]}
                  type={field === "initial_liquidity" ? "number" : "text"}
                  min={field === "initial_liquidity" ? "1" : undefined}
                  onChange={(event) => update(field, event.target.value)}
                  className="mt-2 block w-full rounded border border-zinc-800 bg-zinc-950 px-3 py-3 text-zinc-100"
                />
                <span className="mt-2 block text-[11px] normal-case leading-5 tracking-normal text-zinc-500">
                  {ADMIN_FIELD_HELP[field]}
                </span>
              </label>
            ))}
            <button className="rounded border border-yellow-700 px-4 py-3 text-sm uppercase tracking-widest text-yellow-200 hover:bg-yellow-500/10">
              Create Demo Market
            </button>
            <button
              type="button"
              onClick={() => submitMarket(true)}
              className="rounded border border-emerald-700 px-4 py-3 text-sm uppercase tracking-widest text-emerald-200 hover:bg-emerald-500/10"
            >
              Create and Open Demo Market
            </button>
          </form>
        </section>
        <section>
          <ErrorBox error={error} />
          {notice && <div className="mb-4 rounded-lg border border-emerald-800 bg-emerald-950/30 p-4 text-emerald-200">{notice}</div>}
          {createdMarket && (
            <div className="mb-4 rounded-lg border border-yellow-700/40 bg-yellow-500/10 p-4 text-sm leading-6 text-yellow-100">
              <div className="font-display text-2xl tracking-widest">{createdMarket.title}</div>
              <div className="mt-2">Status: {statusLabel(createdMarket.status)}</div>
              <div className="mt-1 text-xs text-yellow-100/80">{statusHelper(createdMarket.status)}</div>
              <div className="mt-3 flex flex-wrap gap-2">
                {createdMarket.status === "draft" && (
                  <button
                    className="rounded border border-yellow-700 px-3 py-2 text-xs uppercase tracking-widest text-yellow-200"
                    onClick={() => action(createdMarket.id, "open")}
                  >
                    Open Market Now
                  </button>
                )}
                <Link className="rounded border border-zinc-700 px-3 py-2 text-xs uppercase tracking-widest text-zinc-200 hover:text-yellow-300" to={`/tmarget/markets/${createdMarket.slug}`}>
                  View Market
                </Link>
              </div>
            </div>
          )}
          <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-5">
            <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
              <div>
                <div className="text-xs uppercase tracking-[0.35em] text-zinc-500">Demo Lifecycle</div>
                <h2 className="mt-2 font-display text-3xl tracking-widest">Market Controls</h2>
                <p className="mt-3 max-w-2xl text-sm leading-6 text-zinc-400">
                  Use open, pause, close, resolve, and cancel actions only for
                  demo markets. Resolution and cancellation use internal
                  demo-credit settlement/refund behavior.
                </p>
              </div>
              <div className="w-full rounded border border-zinc-800 bg-black/40 p-4 xl:max-w-md">
                <div className="text-xs uppercase tracking-[0.3em] text-zinc-500">Resolution Settings</div>
                <div className="mt-3 grid gap-2 sm:grid-cols-[140px_1fr]">
                  <select
                    value={resolution.outcome}
                    onChange={(event) => setResolution((prev) => ({ ...prev, outcome: event.target.value }))}
                    className="w-full rounded border border-zinc-700 bg-black px-3 py-2 text-sm text-zinc-100"
                  >
                    <option value="yes">YES</option>
                    <option value="no">NO</option>
                    <option value="cancelled">Cancelled</option>
                    <option value="invalid">Invalid</option>
                  </select>
                  <input
                    value={resolution.resolver_notes}
                    onChange={(event) => setResolution((prev) => ({ ...prev, resolver_notes: event.target.value }))}
                    placeholder="Resolver notes required by backend"
                    className="w-full rounded border border-zinc-700 bg-black px-3 py-2 text-sm text-zinc-100"
                  />
                </div>
                <p className="mt-3 text-xs leading-5 text-zinc-500">
                  These fields are sent only when Resolve is clicked. Cancel uses
                  the demo refund path; Resolve uses the selected outcome.
                </p>
              </div>
            </div>
            <div className="mt-5 grid gap-3">
              {markets.length === 0 && (
                <div className="rounded border border-dashed border-zinc-800 bg-black/30 p-4 text-sm leading-6 text-zinc-500">
                  No demo markets created yet. Use the form to create an internal-credit demo market.
                </div>
              )}
              {markets.map((market) => (
                <div key={market.id} className="rounded border border-zinc-800 bg-black/40 p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <div className="text-xs uppercase tracking-widest text-zinc-500">{market.category} / {statusLabel(market.status)}</div>
                      <Link to={`/tmarget/markets/${market.slug}`} className="mt-1 block font-display text-2xl tracking-widest text-zinc-100 hover:text-yellow-300">
                        {market.title}
                      </Link>
                      <div className="mt-2 text-xs leading-5 text-zinc-500">{statusHelper(market.status)}</div>
                    </div>
                    <div className="text-right text-xs uppercase tracking-widest text-zinc-500">
                      YES {formatPrice(market.yes_price)} / NO {formatPrice(market.no_price)}
                    </div>
                  </div>
                  <div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
                    {ADMIN_ACTIONS.map(([name, label, helper]) => (
                      <div key={name} className="rounded border border-zinc-800 bg-zinc-950/70 p-3">
                        <button
                          onClick={() => action(market.id, name)}
                          className="w-full rounded border border-zinc-700 px-3 py-2 text-xs uppercase tracking-widest text-zinc-300 hover:border-yellow-700 hover:text-yellow-200"
                        >
                          {label}
                        </button>
                        <div className="mt-2 text-[11px] leading-5 text-zinc-500">
                          {helper}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>
      </div>
    </TmargetShell>
  );
}
