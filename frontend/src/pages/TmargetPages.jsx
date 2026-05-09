import React, { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Logo } from "../components/game/Logo";

const DISCLAIMER =
  "Axwins currently uses internal demo credits. Live deposits, withdrawals, card payments, crypto transfers, Telegram wallet linking, and real-money trading are not enabled.";

const SAMPLE_MARKETS = [
  {
    slug: "sample-weather-istanbul",
    title: "Will Istanbul record measurable rain next Friday?",
    category: "Weather",
    yes_price: 0.54,
    no_price: 0.46,
    status: "sample fallback",
    close_time: "Future close time placeholder",
    description: "Sample fallback data shown only when the backend is unavailable.",
    rule: {
      resolution_criteria:
        "Resolution criteria placeholder. Backend demo markets replace this sample data when available.",
      source_url: "",
    },
    volume: 0,
  },
  {
    slug: "sample-product-launch",
    title: "Will a demo product launch before quarter end?",
    category: "Technology",
    yes_price: 0.38,
    no_price: 0.62,
    status: "sample fallback",
    close_time: "Future close time placeholder",
    description: "Sample technology market. Trading and settlement are disabled for fallback data.",
    rule: {
      resolution_criteria: "Resolution criteria placeholder.",
      source_url: "",
    },
    volume: 0,
  },
];

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
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(data?.detail?.code || data?.detail || `HTTP_${response.status}`);
  }
  return data;
}

function formatPrice(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(2) : "--";
}

function formatCredits(value) {
  return Number(value || 0).toLocaleString();
}

function statusLabel(value) {
  return String(value || "unknown").replaceAll("_", " ");
}

function TmargetShell({ children }) {
  return (
    <div className="min-h-screen bg-black text-zinc-100">
      <header className="border-b border-zinc-800 bg-zinc-950/80">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-4 sm:px-6">
          <Link to="/tmarget" className="flex items-center gap-3">
            <Logo size={40} />
            <div>
              <div className="font-luxe text-xs uppercase tracking-[0.4em] text-yellow-300">
                Tmarget
              </div>
              <div className="text-xs text-zinc-500">Axwins demo prediction market product</div>
            </div>
          </Link>
          <nav className="flex flex-wrap items-center justify-end gap-2 text-xs uppercase tracking-widest text-zinc-400">
            <Link className="rounded border border-zinc-800 px-3 py-2 hover:text-yellow-300" to="/">
              Axwins
            </Link>
            <Link className="rounded border border-zinc-800 px-3 py-2 hover:text-yellow-300" to="/games">
              Games
            </Link>
            <Link className="rounded border border-zinc-800 px-3 py-2 hover:text-yellow-300" to="/tmarget/markets">
              Markets
            </Link>
            <Link className="rounded border border-zinc-800 px-3 py-2 hover:text-yellow-300" to="/tmarget/portfolio">
              Portfolio
            </Link>
            <Link className="rounded border border-zinc-800 px-3 py-2 hover:text-yellow-300" to="/tmarget/admin/markets">
              Admin
            </Link>
            <Link className="rounded border border-zinc-800 px-3 py-2 hover:text-yellow-300" to="/wallet">
              Wallet
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
    </div>
  );
}

function MarketCard({ market, fallback = false }) {
  return (
    <Link
      to={`/tmarget/markets/${market.slug || market.id}`}
      className="rounded-lg border border-zinc-800 bg-zinc-950 p-5 transition hover:border-yellow-600/70"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-xs uppercase tracking-[0.3em] text-zinc-500">{market.category}</div>
          <h2 className="mt-2 font-display text-2xl tracking-widest text-zinc-100">{market.title}</h2>
        </div>
        <span className="rounded-full border border-zinc-700 px-3 py-1 text-[10px] uppercase tracking-widest text-zinc-500">
          {fallback ? "sample" : statusLabel(market.status)}
        </span>
      </div>
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
          <h1 className="mt-2 font-display text-6xl tracking-widest text-zinc-100">Tmarget</h1>
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
  const [fallback, setFallback] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    async function load() {
      setLoading(true);
      setError("");
      try {
        const data = await apiJson("/api/tmarget/markets");
        if (!alive) return;
        setMarkets(data.markets || []);
        setFallback(false);
      } catch (err) {
        if (!alive) return;
        setMarkets(SAMPLE_MARKETS);
        setFallback(true);
        setError(`Backend unavailable; showing labelled sample fallback data. ${err.message}`);
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

  return (
    <TmargetShell>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="font-luxe text-xs uppercase tracking-[0.45em] text-yellow-300">Demo Markets</div>
          <h1 className="mt-2 font-display text-5xl tracking-widest">Markets</h1>
        </div>
        <div className="flex flex-wrap gap-3">
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search markets"
            className="rounded border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100"
          />
          <select
            value={category}
            onChange={(event) => setCategory(event.target.value)}
            className="rounded border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100"
          >
            {categories.map((item) => <option key={item}>{item}</option>)}
          </select>
        </div>
      </div>
      {loading && <LoadingBox text="Loading markets..." />}
      <ErrorBox error={error} />
      {!loading && filtered.length === 0 && <LoadingBox text="No demo markets found." />}
      <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {filtered.map((market) => <MarketCard key={market.id || market.slug} market={market} fallback={fallback} />)}
      </div>
    </TmargetShell>
  );
}

export function TmargetMarketDetailPlaceholder() {
  const { slug } = useParams();
  const [market, setMarket] = useState(null);
  const [trades, setTrades] = useState([]);
  const [positions, setPositions] = useState([]);
  const [outcome, setOutcome] = useState("yes");
  const [shares, setShares] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const user = storedUser();

  async function load() {
    setLoading(true);
    setError("");
    try {
      const data = await apiJson(`/api/tmarget/markets/${slug}`);
      setMarket(data);
      const tradesData = await apiJson(`/api/tmarget/markets/${data.id}/trades`);
      setTrades(tradesData.trades || []);
      if (user?.token) {
        const posData = await apiJson(`/api/tmarget/markets/${data.id}/positions`, {
          headers: authHeaders(),
        });
        setPositions(posData.positions || []);
      } else {
        setPositions([]);
      }
    } catch (err) {
      const sample = SAMPLE_MARKETS.find((item) => item.slug === slug) || SAMPLE_MARKETS[0];
      setMarket(sample);
      setTrades([]);
      setPositions([]);
      setError(`Backend unavailable or market missing; showing labelled sample fallback data. ${err.message}`);
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
      setError(err.message);
    }
  }

  const canTrade = Boolean(user?.token && market?.id && market.status === "open");
  const yesPosition = positions.find((pos) => pos.outcome === "yes");
  const noPosition = positions.find((pos) => pos.outcome === "no");

  return (
    <TmargetShell>
      {loading && <LoadingBox text="Loading market..." />}
      <ErrorBox error={error} />
      {notice && <div className="mb-4 rounded-lg border border-emerald-800 bg-emerald-950/30 p-4 text-emerald-200">{notice}</div>}
      {market && (
        <div className="grid gap-8 lg:grid-cols-[1fr_360px]">
          <section>
            <div className="text-xs uppercase tracking-[0.35em] text-zinc-500">{market.category}</div>
            <h1 className="mt-2 font-display text-5xl tracking-widest">{market.title}</h1>
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
                    <div key={trade.id} className="flex justify-between border-b border-zinc-900 py-2 text-zinc-400">
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
              Status: {statusLabel(market.status)}<br />
              Volume: {formatCredits(market.volume)} credits<br />
              Your YES: {yesPosition?.shares || 0} shares<br />
              Your NO: {noPosition?.shares || 0} shares
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
                {canTrade ? "Buy Demo Shares" : "Trading Not Enabled"}
              </button>
              <button
                disabled={!canTrade}
                onClick={() => trade("sell")}
                className="rounded border border-rose-700 px-4 py-3 text-sm uppercase tracking-widest text-rose-200 disabled:border-zinc-700 disabled:text-zinc-500"
              >
                {canTrade ? "Sell Demo Shares" : "Trading Not Enabled"}
              </button>
            </div>
          </aside>
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
        setPositions(data.positions || []);
      } catch (err) {
        if (alive) setError(user?.token ? err.message : "Sign in through the lobby to view Tmarget positions.");
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
        <Link to="/wallet" className="btn-secondary mt-6 inline-flex">View Internal Wallet</Link>
        <div className="mt-6">
          {loading && <LoadingBox text="Loading positions..." />}
          <ErrorBox error={error} />
          {!loading && !error && positions.length === 0 && <LoadingBox text="No Tmarget positions yet." />}
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

  async function load() {
    try {
      const data = await apiJson("/api/tmarget/markets");
      setMarkets(data.markets || []);
    } catch (err) {
      setError(err.message);
    }
  }

  useEffect(() => {
    load();
  }, []);

  function update(field, value) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  async function createMarket(event) {
    event.preventDefault();
    setError("");
    setNotice("");
    try {
      await apiJson("/api/tmarget/admin/markets", {
        method: "POST",
        headers: authHeaders({ "X-Axwins-Demo-Admin": "true" }),
        body: JSON.stringify({
          ...form,
          initial_liquidity: Number(form.initial_liquidity),
        }),
      });
      setNotice("Demo market created.");
      setForm((prev) => ({ ...prev, title: "", description: "", resolution_criteria: "", source_url: "" }));
      await load();
    } catch (err) {
      setError(err.message);
    }
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
      await load();
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <TmargetShell>
      <div className="grid gap-8 lg:grid-cols-[420px_1fr]">
        <section>
          <div className="font-luxe text-xs uppercase tracking-[0.45em] text-yellow-300">Demo Admin</div>
          <h1 className="mt-2 font-display text-5xl tracking-widest">Market Setup</h1>
          <p className="mt-4 text-sm leading-6 text-zinc-400">
            Demo-only controls for binary YES/NO markets. This does not create
            real-money markets, payment flows, deposits, withdrawals, or compliance claims.
          </p>
          <p className="mt-3 rounded border border-yellow-700/40 bg-yellow-500/10 p-3 text-sm leading-6 text-yellow-100">
            Demo admin tooling is enabled for local/internal testing only. This is not production authorization.
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
              </label>
            ))}
            <button className="rounded border border-yellow-700 px-4 py-3 text-sm uppercase tracking-widest text-yellow-200">
              Create Demo Market
            </button>
          </form>
        </section>
        <section>
          <ErrorBox error={error} />
          {notice && <div className="mb-4 rounded-lg border border-emerald-800 bg-emerald-950/30 p-4 text-emerald-200">{notice}</div>}
          <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-5">
            <div className="flex flex-wrap items-end justify-between gap-4">
              <div>
                <div className="text-xs uppercase tracking-[0.35em] text-zinc-500">Lifecycle</div>
                <h2 className="mt-2 font-display text-3xl tracking-widest">Markets</h2>
              </div>
              <div className="flex gap-2">
                <select
                  value={resolution.outcome}
                  onChange={(event) => setResolution((prev) => ({ ...prev, outcome: event.target.value }))}
                  className="rounded border border-zinc-700 bg-black px-3 py-2 text-sm text-zinc-100"
                >
                  <option value="yes">YES</option>
                  <option value="no">NO</option>
                  <option value="cancelled">Cancelled</option>
                  <option value="invalid">Invalid</option>
                </select>
                <input
                  value={resolution.resolver_notes}
                  onChange={(event) => setResolution((prev) => ({ ...prev, resolver_notes: event.target.value }))}
                  placeholder="Resolver notes"
                  className="rounded border border-zinc-700 bg-black px-3 py-2 text-sm text-zinc-100"
                />
              </div>
            </div>
            <div className="mt-5 grid gap-3">
              {markets.length === 0 && <div className="text-sm text-zinc-500">No demo markets created yet.</div>}
              {markets.map((market) => (
                <div key={market.id} className="rounded border border-zinc-800 bg-black/40 p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <div className="text-xs uppercase tracking-widest text-zinc-500">{market.category} / {statusLabel(market.status)}</div>
                      <Link to={`/tmarget/markets/${market.slug}`} className="mt-1 block font-display text-2xl tracking-widest text-zinc-100 hover:text-yellow-300">
                        {market.title}
                      </Link>
                    </div>
                    <div className="text-right text-xs uppercase tracking-widest text-zinc-500">
                      YES {formatPrice(market.yes_price)} / NO {formatPrice(market.no_price)}
                    </div>
                  </div>
                  <div className="mt-4 flex flex-wrap gap-2">
                    {["open", "pause", "close", "cancel", "resolve"].map((name) => (
                      <button
                        key={name}
                        onClick={() => action(market.id, name)}
                        className="rounded border border-zinc-700 px-3 py-2 text-xs uppercase tracking-widest text-zinc-300 hover:border-yellow-700 hover:text-yellow-200"
                      >
                        {name}
                      </button>
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
