import React from "react";
import { Link } from "react-router-dom";
import { Logo } from "../components/game/Logo";

const gameProducts = [
  {
    name: "Target",
    status: "Available",
    category: "Game",
    description: "Strategic table game inside Axwins. Target gameplay review stays in the separate Target flow.",
    href: "/games/target",
  },
  {
    name: "Diceget",
    status: "Available",
    category: "Game",
    description: "4-player dice game inside Axwins",
    href: "/games/diceget",
  },
  {
    name: "Flipget",
    status: "Available",
    category: "Game",
    description: "2-player coin flip game inside Axwins",
    href: "/games/flipget",
  },
];

const productModules = [
  {
    name: "Tmarget",
    status: "Demo MVP",
    category: "Prediction Market",
    description: "Demo prediction market product, separate from games and backed only by internal demo credits",
    href: "/tmarget",
  },
];

const coreProducts = [
  {
    name: "Wallet / Ledger",
    status: "Core Service",
    category: "Platform Core",
    description: "Internal demo-credit wallet shared across Axwins products",
    href: "/wallet",
  },
  {
    name: "Transaction History",
    status: "Core Service",
    category: "Platform Core",
    description: "Read-only ledger history for internal demo credits",
    href: "/wallet",
  },
];

const DEMO_CREDIT_NOTICE =
  "Axwins currently uses internal demo credits only. Deposits, withdrawals, cash-out, crypto, card payments, and real-money trading are not enabled.";

const walkthroughSteps = [
  "Start with Axwins as the platform hub.",
  "Show Games: Target, Diceget, and Flipget.",
  "Show Tmarget separately as a demo prediction market product.",
  "Close with Wallet / Ledger as read-only platform core.",
];

function PlatformShell({ children }) {
  return (
    <div className="min-h-screen bg-black text-zinc-100">
      <header className="border-b border-zinc-800 bg-zinc-950/80">
        <div className="mx-auto flex max-w-6xl flex-col items-start justify-between gap-4 px-4 py-4 sm:flex-row sm:items-center sm:px-6">
          <Link to="/" className="flex items-center gap-3">
            <Logo size={40} />
            <div>
              <div className="font-luxe text-xs uppercase tracking-[0.4em] text-yellow-300">
                Axwins
              </div>
              <div className="text-xs text-zinc-500">Multi-product demo platform</div>
            </div>
          </Link>
          <nav className="flex w-full flex-wrap items-center justify-start gap-2 text-xs uppercase tracking-widest text-zinc-400 sm:w-auto sm:justify-end">
            <Link className="rounded border border-zinc-800 px-3 py-2 text-center hover:text-yellow-300" to="/">
              Home
            </Link>
            <Link className="rounded border border-zinc-800 px-3 py-2 text-center hover:text-yellow-300" to="/games">
              Games
            </Link>
            <Link className="rounded border border-zinc-800 px-3 py-2 text-center hover:text-yellow-300" to="/tmarget">
              Tmarget
            </Link>
            <Link className="rounded border border-zinc-800 px-3 py-2 text-center hover:text-yellow-300" to="/wallet">
              Wallet / Ledger
            </Link>
            <Link className="rounded border border-zinc-800 px-3 py-2 text-center hover:text-yellow-300" to="/profile">
              Profile
            </Link>
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6">{children}</main>
    </div>
  );
}

function ProductCard({ product }) {
  const available = product.status === "Available";
  return (
    <Link
      to={product.href}
      data-testid={`product-card-${product.name.toLowerCase()}`}
      className="group flex min-h-[190px] flex-col rounded-lg border border-zinc-800 bg-zinc-950/80 p-5 transition hover:border-yellow-600/70 hover:bg-zinc-900/70"
    >
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-[10px] uppercase tracking-[0.3em] text-zinc-500">{product.category}</div>
          <div className="mt-2 font-display text-2xl tracking-widest text-zinc-100 sm:text-3xl">
            {product.name}
          </div>
        </div>
        <span
          className={`shrink-0 rounded-full border px-3 py-1 text-[10px] uppercase tracking-widest ${
            available
              ? "border-emerald-600/60 text-emerald-300"
              : "border-yellow-700/60 text-yellow-300"
          }`}
        >
          {product.status}
        </span>
      </div>
      <p className="text-sm leading-relaxed text-zinc-400">{product.description}</p>
      <div className="mt-5 text-xs uppercase tracking-[0.3em] text-yellow-300">
        {available ? "Enter" : "Open"}
      </div>
    </Link>
  );
}

function ProductGroup({ eyebrow, title, description, products, columns = "md:grid-cols-3" }) {
  return (
    <section className="rounded-lg border border-zinc-900 bg-zinc-950/40 p-4 sm:p-5">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div className="font-luxe text-xs uppercase tracking-[0.45em] text-yellow-300">{eyebrow}</div>
          <h2 className="mt-2 font-display text-3xl tracking-widest text-zinc-100 sm:text-4xl">{title}</h2>
        </div>
        <p className="max-w-xl text-sm leading-6 text-zinc-500">{description}</p>
      </div>
      <div className={`mt-5 grid gap-4 ${columns}`}>
        {products.map((product) => <ProductCard key={product.name} product={product} />)}
      </div>
    </section>
  );
}

export function PlatformHome() {
  return (
    <PlatformShell>
      <section className="grid gap-8 py-4 lg:grid-cols-[1.08fr_0.92fr] lg:items-start">
        <div>
          <div className="mb-3 font-luxe text-xs uppercase tracking-[0.45em] text-yellow-300">
            Internal demo platform
          </div>
          <h1 className="font-display text-5xl tracking-widest text-zinc-100 sm:text-7xl lg:text-8xl">
            AXWINS
          </h1>
          <p className="mt-4 max-w-2xl text-lg leading-8 text-zinc-300">
            A multi-product demo platform for games, a separate demo prediction
            market product, and shared wallet / ledger core services.
          </p>
          <p className="mt-4 max-w-2xl text-sm leading-6 text-zinc-500">
            Axwins is the platform. Target, Diceget, and Flipget are games.
            Tmarget is not a game; it is a separate demo prediction market
            product. Wallet, Ledger, Transaction History, and Internal Demo
            Credits are platform core.
          </p>
          <p className="mt-5 rounded-lg border border-yellow-700/40 bg-yellow-500/10 p-4 text-sm leading-6 text-yellow-100">
            {DEMO_CREDIT_NOTICE}
          </p>
          <div className="mt-7 grid gap-3 sm:grid-cols-3">
            <Link className="btn-primary text-center" to="/games">
              Open Games
            </Link>
            <Link className="btn-secondary text-center" to="/tmarget">
              Open Tmarget
            </Link>
            <Link className="btn-secondary text-center" to="/wallet">
              Wallet / Ledger
            </Link>
          </div>
        </div>
        <aside className="rounded-lg border border-yellow-700/30 bg-zinc-950/80 p-5">
          <div className="text-xs uppercase tracking-[0.35em] text-zinc-500">
            Demo walkthrough
          </div>
          <h2 className="mt-2 font-display text-3xl tracking-widest text-zinc-100">
            Safe demo path
          </h2>
          <p className="mt-3 text-sm leading-6 text-zinc-500">
            Use this hub as the first screen for investor and internal-review
            walkthroughs. It mirrors the demo script without claiming production
            readiness.
          </p>
          <div className="mt-5 grid gap-3">
            {walkthroughSteps.map((step, index) => (
              <div key={step} className="flex gap-3 rounded border border-zinc-800 bg-black/40 p-3 text-sm text-zinc-300">
                <span className="font-display text-lg text-yellow-300">{index + 1}</span>
                <span>{step}</span>
              </div>
            ))}
          </div>
        </aside>
      </section>
      <section className="mt-10 grid gap-8">
        <ProductGroup
          eyebrow="Games"
          title="Target, Diceget, Flipget"
          description="Game modules inside Axwins. Gameplay remains owned by each game surface."
          products={gameProducts}
        />
        <ProductGroup
          eyebrow="Prediction Markets"
          title="Tmarget"
          description="A separate demo prediction market product. It is not a game and does not enable real-money trading."
          products={productModules}
          columns="md:grid-cols-2"
        />
        <ProductGroup
          eyebrow="Platform Core"
          title="Wallet and Ledger"
          description="Read-only wallet, ledger, transaction history, and internal demo-credit surfaces shared across Axwins."
          products={coreProducts}
          columns="md:grid-cols-2"
        />
      </section>
    </PlatformShell>
  );
}

export function GamesPage() {
  return (
    <PlatformShell>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="font-luxe text-xs uppercase tracking-[0.45em] text-yellow-300">
            Products
          </div>
          <h1 className="mt-2 font-display text-5xl tracking-widest text-zinc-100">Games</h1>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-zinc-400">
            Target, Diceget, and Flipget are Axwins game modules. Tmarget is listed separately below as a prediction market product.
          </p>
        </div>
        <Link className="btn-ghost" to="/">
          Home
        </Link>
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        {gameProducts.map((product) => (
          <ProductCard key={product.name} product={product} />
        ))}
      </div>
      <div className="mt-10">
        <div className="font-luxe text-xs uppercase tracking-[0.45em] text-yellow-300">
          Separate Product
        </div>
        <h2 className="mt-2 font-display text-4xl tracking-widest text-zinc-100">
          Prediction Markets
        </h2>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          {productModules.map((product) => (
            <ProductCard key={product.name} product={product} />
          ))}
        </div>
      </div>
      <div className="mt-10">
        <div className="font-luxe text-xs uppercase tracking-[0.45em] text-yellow-300">
          Platform Core
        </div>
        <h2 className="mt-2 font-display text-4xl tracking-widest text-zinc-100">
          Wallet and Ledger
        </h2>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          {coreProducts.map((product) => (
            <ProductCard key={product.name} product={product} />
          ))}
        </div>
      </div>
    </PlatformShell>
  );
}

export function ComingSoonPage({ name, description, productType = "Product" }) {
  return (
    <PlatformShell>
      <div className="max-w-2xl">
        <div className="font-luxe text-xs uppercase tracking-[0.45em] text-zinc-500">
          {productType}
        </div>
        <h1 className="mt-2 font-display text-5xl tracking-widest text-zinc-100">{name}</h1>
        <p className="mt-4 text-base leading-7 text-zinc-400">{description}</p>
        <div className="mt-5 inline-flex rounded-full border border-zinc-700 px-3 py-1 text-xs uppercase tracking-widest text-zinc-500">
          Coming soon
        </div>
        <div className="mt-8">
          <Link className="btn-secondary" to="/games">
            Back to Games
          </Link>
        </div>
      </div>
    </PlatformShell>
  );
}

export function WalletPlaceholder() {
  return (
    <PlatformShell>
      <div className="max-w-2xl">
        <div className="font-luxe text-xs uppercase tracking-[0.45em] text-yellow-300">
          Core service
        </div>
        <h1 className="mt-2 font-display text-5xl tracking-widest text-zinc-100">Wallet</h1>
        <p className="mt-4 text-base leading-7 text-zinc-400">
          {DEMO_CREDIT_NOTICE}
        </p>
      </div>
    </PlatformShell>
  );
}

export function ProfilePlaceholder() {
  return (
    <PlatformShell>
      <div className="max-w-2xl">
        <div className="font-luxe text-xs uppercase tracking-[0.45em] text-yellow-300">
          Core service
        </div>
        <h1 className="mt-2 font-display text-5xl tracking-widest text-zinc-100">Profile</h1>
        <p className="mt-4 text-base leading-7 text-zinc-400">
          Shared profile surface for future platform identity. Existing Target
          lobby authentication remains unchanged.
        </p>
      </div>
    </PlatformShell>
  );
}
