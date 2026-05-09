import React, { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Logo } from "../components/game/Logo";

const SOURCE_LABELS = {
  target: "Target",
  diceget: "Diceget",
  flipget: "Flipget",
  tmarget: "Tmarget",
  payment: "Payment",
  admin: "Admin",
};

const REASON_LABELS = {
  target_join_lock: "join lock",
  diceget_join_lock: "join lock",
  flipget_join_lock: "join lock",
  target_cancel_unlock: "cancel unlock",
  diceget_cancel_unlock: "cancel unlock",
  flipget_cancel_unlock: "cancel unlock",
  target_win_payout: "win payout",
  diceget_win_payout: "win payout",
  flipget_win_payout: "win payout",
  tmarget_buy_cost: "market buy cost",
  tmarget_sell_credit: "market sell credit",
  tmarget_settlement_win: "market settlement win",
  tmarget_settlement_loss: "market settlement loss",
  tmarget_refund: "tmarget refund",
  tmarget_fee: "market fee",
  tmarget_admin_market_create: "demo market create",
  target_refund: "refund",
  diceget_refund: "refund",
  flipget_refund: "refund",
  SIGNUP_BONUS: "signup bonus",
  sandbox_deposit: "sandbox deposit",
  admin_credit: "admin credit",
};

const DEMO_CREDIT_NOTICE =
  "Axwins currently uses internal demo credits. Live deposits, withdrawals, card payments, crypto transfers, Telegram wallet linking, and real-money trading are not enabled.";

function storedUser() {
  try {
    return JSON.parse(localStorage.getItem("target_user") || "null");
  } catch {
    return null;
  }
}

function authHeaders() {
  const user = storedUser();
  return user?.token ? { Authorization: `Bearer ${user.token}` } : {};
}

async function getJson(path) {
  const response = await fetch(path, { headers: authHeaders() });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(data?.detail?.code || data?.detail || `HTTP_${response.status}`);
  }
  return data;
}

function money(value) {
  const n = Number(value || 0);
  return n.toLocaleString();
}

function labelReason(entry) {
  return entry.reason_label || REASON_LABELS[entry.reason] || String(entry.reason || "unknown").replaceAll("_", " ");
}

function labelSource(entry) {
  return entry.source_label || SOURCE_LABELS[entry.source_module] || entry.source_module || "Unknown";
}

function WalletCard({ title, value, caption }) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-5">
      <div className="text-xs uppercase tracking-[0.35em] text-zinc-500">{title}</div>
      <div className="mt-4 font-display text-4xl tracking-widest text-zinc-100">{money(value)}</div>
      {caption && <div className="mt-2 text-sm text-zinc-500">{caption}</div>}
    </div>
  );
}

export default function WalletPage() {
  const [summary, setSummary] = useState(null);
  const [entries, setEntries] = useState([]);
  const [sourceFilter, setSourceFilter] = useState("all");
  const [reasonFilter, setReasonFilter] = useState("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const user = storedUser();

  useEffect(() => {
    let alive = true;
    async function load() {
      setLoading(true);
      setError("");
      try {
        const [wallet, ledger] = await Promise.all([
          getJson("/api/platform/wallet/me"),
          getJson("/api/platform/ledger/me?limit=100"),
        ]);
        if (!alive) return;
        setSummary(wallet);
        setEntries(ledger.entries || []);
      } catch (err) {
        if (alive) setError(err.message);
      } finally {
        if (alive) setLoading(false);
      }
    }
    if (user?.token) load();
    else {
      setLoading(false);
      setError("Sign in through the lobby to view your wallet.");
    }
    return () => {
      alive = false;
    };
  }, [user?.token]);

  const sources = useMemo(() => {
    const values = new Set(entries.map((entry) => entry.source_module).filter(Boolean));
    return ["all", ...Array.from(values).sort()];
  }, [entries]);

  const reasons = useMemo(() => {
    const values = new Set(entries.map((entry) => entry.reason).filter(Boolean));
    return ["all", ...Array.from(values).sort()];
  }, [entries]);

  const filtered = entries.filter((entry) => {
    if (sourceFilter !== "all" && entry.source_module !== sourceFilter) return false;
    if (reasonFilter !== "all" && entry.reason !== reasonFilter) return false;
    return true;
  });

  return (
    <div className="min-h-screen bg-black text-zinc-100">
      <header className="border-b border-zinc-800 bg-zinc-950/80">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-4 sm:px-6">
          <Link to="/" className="flex items-center gap-3">
            <Logo size={40} />
            <div>
              <div className="font-luxe text-xs uppercase tracking-[0.4em] text-yellow-300">Axwins Wallet</div>
              <div className="text-xs text-zinc-500">Internal demo-credit core service</div>
            </div>
          </Link>
          <nav className="flex flex-wrap gap-2 text-xs uppercase tracking-widest text-zinc-400">
            <Link className="rounded border border-zinc-800 px-3 py-2 hover:text-yellow-300" to="/">Home</Link>
            <Link className="rounded border border-zinc-800 px-3 py-2 hover:text-yellow-300" to="/games">Games</Link>
            <Link className="rounded border border-zinc-800 px-3 py-2 hover:text-yellow-300" to="/tmarget">Tmarget</Link>
            <Link className="rounded border border-zinc-800 px-3 py-2 hover:text-yellow-300" to="/profile">Profile</Link>
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
        <div className="mb-6">
          <div className="font-luxe text-xs uppercase tracking-[0.45em] text-yellow-300">Platform Core</div>
          <h1 className="mt-2 font-display text-5xl tracking-widest">Wallet and Ledger</h1>
          <p className="mt-4 max-w-3xl text-sm leading-6 text-zinc-400">
            {DEMO_CREDIT_NOTICE}
          </p>
        </div>

        {loading && <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-5 text-zinc-400">Loading wallet...</div>}
        {error && (
          <div className="rounded-lg border border-rose-800 bg-rose-950/30 p-5 text-rose-200">
            {error}
          </div>
        )}

        {!loading && !error && summary && (
          <>
            <div className="grid gap-4 md:grid-cols-3">
              <WalletCard title="Current Balance" value={summary.balance} caption={summary.currency_label} />
              <WalletCard title="Locked Balance" value={summary.locked_balance ?? summary.locked} caption="Reserved by active tables" />
              <WalletCard title="Available Balance" value={summary.available_balance} caption="Available internal demo credits" />
            </div>

            <div className="mt-8 rounded-lg border border-zinc-800 bg-zinc-950 p-5">
              <div className="flex flex-wrap items-end justify-between gap-4">
                <div>
                  <div className="text-xs uppercase tracking-[0.35em] text-zinc-500">Ledger</div>
                  <h2 className="mt-2 font-display text-3xl tracking-widest">Transaction History</h2>
                </div>
                <div className="flex flex-wrap gap-3">
                  <label className="text-xs uppercase tracking-widest text-zinc-500">
                    Source
                    <select
                      className="mt-2 block rounded border border-zinc-700 bg-black px-3 py-2 text-zinc-200"
                      value={sourceFilter}
                      onChange={(event) => setSourceFilter(event.target.value)}
                    >
                      {sources.map((source) => (
                        <option key={source} value={source}>
                          {source === "all" ? "All" : SOURCE_LABELS[source] || source}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="text-xs uppercase tracking-widest text-zinc-500">
                    Reason
                    <select
                      className="mt-2 block rounded border border-zinc-700 bg-black px-3 py-2 text-zinc-200"
                      value={reasonFilter}
                      onChange={(event) => setReasonFilter(event.target.value)}
                    >
                      {reasons.map((reason) => (
                        <option key={reason} value={reason}>
                          {reason === "all" ? "All" : REASON_LABELS[reason] || reason.replaceAll("_", " ")}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
              </div>

              {filtered.length === 0 ? (
                <div className="mt-6 rounded border border-zinc-800 bg-black/40 p-5 text-zinc-500">
                  No wallet activity to show.
                </div>
              ) : (
                <div className="mt-6 overflow-x-auto">
                  <table className="w-full min-w-[760px] text-left text-sm">
                    <thead className="border-b border-zinc-800 text-xs uppercase tracking-widest text-zinc-500">
                      <tr>
                        <th className="py-3 pr-4">Date</th>
                        <th className="py-3 pr-4">Source</th>
                        <th className="py-3 pr-4">Reason</th>
                        <th className="py-3 pr-4 text-right">Amount</th>
                        <th className="py-3 pr-4 text-right">Balance After</th>
                        <th className="py-3 pr-4">Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filtered.map((entry) => (
                        <tr key={entry.id} className="border-b border-zinc-900 text-zinc-300">
                          <td className="py-3 pr-4 text-zinc-500">{entry.created_at ? new Date(entry.created_at).toLocaleString() : "-"}</td>
                          <td className="py-3 pr-4">{labelSource(entry)}</td>
                          <td className="py-3 pr-4">{labelReason(entry)}</td>
                          <td className={`py-3 pr-4 text-right ${Number(entry.amount) >= 0 ? "text-emerald-300" : "text-rose-300"}`}>
                            {Number(entry.amount) >= 0 ? "+" : ""}{money(entry.amount)}
                          </td>
                          <td className="py-3 pr-4 text-right">{entry.balance_after == null ? "-" : money(entry.balance_after)}</td>
                          <td className="py-3 pr-4 text-xs uppercase tracking-widest text-zinc-500">{entry.status || "POSTED"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </>
        )}
      </main>
    </div>
  );
}
