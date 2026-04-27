import React, { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { api } from "../lib/api";
import { createGameSocket } from "../lib/ws";
import { Logo } from "../components/game/Logo";
import { PlayerSeat } from "../components/game/PlayerSeat";
import { PlayingCard } from "../components/game/PlayingCard";
import { PotDisplay } from "../components/game/PotDisplay";
import { BettingPanel } from "../components/game/BettingPanel";

export function GamePage() {
  const { tableId } = useParams();
  const { user, token, refresh } = useAuth();
  const nav = useNavigate();
  const [view, setView] = useState(null);
  const [events, setEvents] = useState([]);
  const [error, setError] = useState(null);
  const [callout, setCallout] = useState(null);
  const sockRef = useRef(null);

  useEffect(() => {
    if (!token) return;
    const sock = createGameSocket({
      tableId,
      token,
      onState: ({ view, events: evs }) => {
        setView(view);
        if (evs && evs.length) {
          setEvents((prev) => [...prev.slice(-30), ...evs]);
          // Show floating callouts for key events
          for (const ev of evs) {
            if (["RAISE", "FOLD", "CALL", "CHECK", "STAND", "CARD_DRAWN", "SHOWDOWN"].includes(ev.type)) {
              const txt = ev.type === "STAND" && ev.auto ? "AUTO STAND" : ev.type;
              setCallout({ text: txt, ts: Date.now() });
              setTimeout(() => setCallout((c) => (c && c.ts === c.ts ? null : c)), 1400);
            }
          }
        }
      },
      onReject: (data) => {
        setError(`${data.error}`);
        setTimeout(() => setError(null), 3000);
      },
      onClose: () => {},
    });
    sockRef.current = sock;
    return () => sock.close();
  }, [tableId, token]);

  useEffect(() => { refresh(); }, [view?.version, refresh]);

  const me = view?.players?.find((p) => p.user_id === user?.id);
  const others = view?.players?.filter((p) => p.user_id !== user?.id) || [];
  const isMyTurn = me && view?.current_turn_seat === me.seat_index;

  const onAction = (type, payload) => {
    if (!sockRef.current) return;
    const ok = sockRef.current.send(type, payload || {});
    if (!ok) setError("Not connected");
  };

  const leave = async () => {
    try {
      await api.post(`/tables/${tableId}/leave`);
    } catch (e) {
      // Best-effort leave; user is navigating away anyway. Surface so we
      // can trace 401/network drops in dev tools.
      console.warn("GamePage: leave-table call failed (proceeding anyway)", e);
    }
    sockRef.current?.close();
    nav("/menu");
  };

  if (!view) {
    return (
      <div className="min-h-screen flex items-center justify-center" data-testid="game-loading">
        <div className="font-luxe text-gold tracking-widest">CONNECTING TO TABLE...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen relative overflow-hidden">
      {/* Top bar */}
      <header className="px-6 py-3 flex items-center justify-between border-b border-gold/10" data-testid="game-top-bar">
        <div className="flex items-center gap-4">
          <button className="btn-ghost" onClick={leave} data-testid="leave-table">← LEAVE</button>
          <Logo size={36} />
        </div>
        <div className="text-center">
          <div className="text-[9px] uppercase tracking-[0.5em] text-neutral-mid font-luxe">Hand</div>
          <div className="font-display text-xl text-gold tracking-widest">{view.hand_number || "—"}</div>
        </div>
        <div className="flex items-center gap-3">
          <div className="panel px-3 py-1.5">
            <span className="text-gold text-sm">●</span>
            <span className="font-num text-gold ml-2" data-testid="header-balance">{(user?.balance ?? 0).toLocaleString()}</span>
          </div>
        </div>
      </header>

      {/* Felt arena */}
      <div className="felt min-h-[calc(100vh-180px)] relative px-4 py-6">
        {/* Opponents row */}
        <div className="flex justify-center items-start gap-4 flex-wrap mb-4" data-testid="opponents-row">
          {others.map((p) => (
            <PlayerSeat
              key={p.seat_index}
              player={p}
              isMe={false}
              isCurrentTurn={view.current_turn_seat === p.seat_index}
              isLocal={false}
            />
          ))}
        </div>

        {/* Center pot + decks */}
        <div className="flex items-center justify-center gap-12 my-8" data-testid="center-area">
          <div className="flex flex-col items-center" data-testid="draw-deck">
            <div className="playing-card-back" />
            <div className="text-[9px] uppercase tracking-[0.4em] text-gold/70 font-luxe mt-2">Draw Deck</div>
          </div>
          <PotDisplay pot={view.pot} phase={view.phase} />
          <div className="flex flex-col items-center" data-testid="discard-pile">
            <div className="playing-card-back red" />
            <div className="text-[9px] uppercase tracking-[0.4em] text-red-target/70 font-luxe mt-2">Discard</div>
          </div>
        </div>

        {/* Action callout */}
        {callout && (
          <div className="absolute left-1/2 top-1/3 -translate-x-1/2 font-display text-5xl text-gold animate-float-up pointer-events-none" style={{textShadow:"0 0 28px rgba(255,209,102,0.6)"}} data-testid="action-callout">
            {callout.text}!
          </div>
        )}

        {/* Local player */}
        {me && (
          <div className="flex flex-col items-center mt-6" data-testid="local-player-area">
            <PlayerSeat player={me} isMe isCurrentTurn={isMyTurn} isLocal />
            {/* Hand */}
            <div className="flex gap-2 mt-4" data-testid="my-hand">
              {(me.cards || []).map((c, i) => (
                // Prefer the engine-provided card code (stable per-card id);
                // fall back to rank+suit+index for older payloads.
                <PlayingCard
                  key={c.code || `${c.rank}-${c.suit}-${i}`}
                  rank={c.rank}
                  suit={c.suit}
                  code={c.code}
                />
              ))}
              {(me.cards?.length || 0) === 0 && (
                <div className="text-neutral-mid font-luxe tracking-widest">NO CARDS</div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Bottom bar — betting/draw panel */}
      <footer className="px-6 py-4 border-t border-gold/10" data-testid="game-bottom-bar">
        <BettingPanel
          phase={view.phase}
          isMyTurn={isMyTurn}
          currentBet={view.current_bet}
          myBet={me?.current_bet || 0}
          balance={user?.balance || 0}
          minRaise={Math.max(view.min_raise || 0, view.stake || 100)}
          turnDeadlineMs={view.turn_deadline_ms}
          onAction={onAction}
        />
      </footer>

      {error && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 panel px-4 py-2 border border-red-500/60 text-red-target font-luxe tracking-widest" data-testid="error-toast">
          {error}
        </div>
      )}
    </div>
  );
}
