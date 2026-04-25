import React, { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { api } from "../lib/api";
import { Logo } from "../components/game/Logo";

export function MenuPage() {
  const { user, logout, refresh } = useAuth();
  const nav = useNavigate();

  useEffect(() => { refresh(); }, [refresh]);

  const onPlay = async () => {
    try {
      const { data } = await api.post("/tables/quick-join", { type: "FREE" });
      nav(`/table/${data.table_id}`);
    } catch (e) {
      alert(e?.response?.data?.detail || "Quick-join failed");
    }
  };

  return (
    <div className="min-h-screen relative">
      {/* top bar */}
      <header className="absolute top-0 left-0 right-0 px-8 py-5 flex items-center justify-between z-10" data-testid="top-bar">
        <Logo size={56} />
        <div className="flex items-center gap-4">
          <div className="panel px-4 py-2 flex items-center gap-2" data-testid="balance-display">
            <span className="text-gold text-lg">●</span>
            <span className="font-num text-gold text-lg">{user?.balance?.toLocaleString() || "0"}</span>
          </div>
          <div className="panel px-4 py-2 flex items-center gap-2">
            <span className="text-cyan">◆</span>
            <span className="font-num text-cyan">0</span>
          </div>
          <button className="btn-ghost" onClick={() => { logout(); nav("/login"); }} data-testid="logout-btn">EXIT</button>
        </div>
      </header>

      {/* central main menu */}
      <main className="min-h-screen flex flex-col items-center justify-center px-4 pt-20">
        <div className="text-center mb-12">
          <div className="font-luxe text-xs tracking-[0.5em] text-gold/80 mb-2">— PREMIUM CARD GAME —</div>
          <h1 className="font-display text-7xl text-gold tracking-[0.18em]" style={{textShadow:"0 0 40px rgba(255,209,102,0.5)"}}>
            TARGET
          </h1>
        </div>
        <div className="w-full max-w-md space-y-3">
          <button className="btn-primary w-full text-2xl py-5" onClick={onPlay} data-testid="play-btn">▶ PLAY</button>
          <button className="btn-secondary w-full" onClick={() => nav("/tables")} data-testid="multiplayer-btn">MULTIPLAYER</button>
          <button className="btn-secondary w-full opacity-60" disabled data-testid="tournament-btn">TOURNAMENT</button>
          <button className="btn-secondary w-full opacity-60" disabled data-testid="collection-btn">COLLECTION</button>
        </div>
        <div className="mt-10 text-center font-luxe text-[10px] tracking-[0.4em] text-neutral-mid">v1.0.0</div>
      </main>
    </div>
  );
}
