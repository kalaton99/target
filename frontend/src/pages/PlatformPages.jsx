import React from "react";
import { Link } from "react-router-dom";
import { Logo } from "../components/game/Logo";

const gameProducts = [
  {
    name: "Target",
    status: "Available",
    description: "Existing strategic table game",
    href: "/games/target",
  },
  {
    name: "Diceget",
    status: "Available",
    description: "4-player dice target game",
    href: "/games/diceget",
  },
  {
    name: "Flipget",
    status: "Available",
    description: "2-player coin flip duel",
    href: "/games/flipget",
  },
];

const productModules = [
  {
    name: "Tmarget",
    status: "Demo MVP",
    description: "Demo Prediction Market Platform",
    href: "/tmarget",
  },
];

function PlatformShell({ children }) {
  return (
    <div className="min-h-screen bg-black text-zinc-100">
      <header className="border-b border-zinc-800 bg-zinc-950/80">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-4 sm:px-6">
          <Link to="/" className="flex items-center gap-3">
            <Logo size={40} />
            <div>
              <div className="font-luxe text-xs uppercase tracking-[0.4em] text-yellow-300">
                Axwins
              </div>
              <div className="text-xs text-zinc-500">Games and product modules</div>
            </div>
          </Link>
          <nav className="flex flex-wrap items-center justify-end gap-2 text-xs uppercase tracking-widest text-zinc-400">
            <Link className="rounded border border-zinc-800 px-3 py-2 hover:text-yellow-300" to="/games">
              Games
            </Link>
            <Link className="rounded border border-zinc-800 px-3 py-2 hover:text-yellow-300" to="/wallet">
              Wallet
            </Link>
            <Link className="rounded border border-zinc-800 px-3 py-2 hover:text-yellow-300" to="/profile">
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
      className="group rounded-lg border border-zinc-800 bg-zinc-950/70 p-5 transition hover:border-yellow-600/70 hover:bg-zinc-900/70"
    >
      <div className="mb-4 flex items-start justify-between gap-3">
        <div className="font-display text-3xl tracking-widest text-zinc-100">
          {product.name}
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
      <p className="min-h-10 text-sm leading-relaxed text-zinc-400">{product.description}</p>
      <div className="mt-5 text-xs uppercase tracking-[0.3em] text-yellow-300">
        {available ? "Enter" : "Open"}
      </div>
    </Link>
  );
}

export function PlatformHome() {
  return (
    <PlatformShell>
      <section className="grid gap-8 lg:grid-cols-[1.05fr_0.95fr] lg:items-center">
        <div>
          <div className="mb-3 font-luxe text-xs uppercase tracking-[0.45em] text-yellow-300">
            Multi-product shell
          </div>
          <h1 className="font-display text-6xl tracking-widest text-zinc-100 sm:text-7xl">
            AXWINS
          </h1>
          <p className="mt-4 max-w-2xl text-base leading-7 text-zinc-400">
            A platform entry point for Target, Diceget, and Flipget game modules,
            with Tmarget separated as a demo prediction market platform.
            Wallet, ledger, transaction history, and internal demo credits are
            shared Axwins core services.
          </p>
          <div className="mt-7 flex flex-wrap gap-3">
            <Link className="btn-primary" to="/games">
              View Products
            </Link>
            <Link className="btn-secondary" to="/games/target">
              Play Target
            </Link>
          </div>
        </div>
        <div className="rounded-lg border border-yellow-700/30 bg-zinc-950/70 p-5">
          <div className="text-xs uppercase tracking-[0.35em] text-zinc-500">
            Integration scope
          </div>
          <div className="mt-4 grid gap-3 text-sm text-zinc-300">
            <div className="rounded border border-zinc-800 bg-black/40 p-3">
              Target remains the available game module.
            </div>
            <div className="rounded border border-zinc-800 bg-black/40 p-3">
              Diceget and Flipget are available game modules.
            </div>
            <div className="rounded border border-zinc-800 bg-black/40 p-3">
              Tmarget is separated as a demo prediction market product.
            </div>
          </div>
        </div>
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
        </div>
        <Link className="btn-ghost" to="/">
          Home
        </Link>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        {gameProducts.map((product) => (
          <ProductCard key={product.name} product={product} />
        ))}
      </div>
      <div className="mt-10">
        <div className="font-luxe text-xs uppercase tracking-[0.45em] text-yellow-300">
          Separate Product
        </div>
        <h2 className="mt-2 font-display text-4xl tracking-widest text-zinc-100">
          Prediction Market Platform
        </h2>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          {productModules.map((product) => (
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
          Internal wallet and ledger integration point. Live deposits,
          withdrawals, crypto, and card payments are intentionally not enabled in
          this phase.
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
