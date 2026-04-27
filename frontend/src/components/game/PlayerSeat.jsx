import React from "react";
import { PlayingCard } from "./PlayingCard";

// --- helpers -------------------------------------------------------------
// Extracted from inline nested-ternaries to keep the JSX readable.

function panelClass(player, isCurrentTurn, isLocal) {
  if (player.folded) return "panel-folded";
  if (!isCurrentTurn) return "panel";
  return isLocal ? "panel-active-self animate-pulse-cyan" : "panel-active-opponent";
}

function PlayerStatusBadge({ player }) {
  if (player.folded) return <span className="text-red-target">FOLDED</span>;
  if (player.busted) return <span className="text-red-target">BUST</span>;
  if (player.disqualified) return <span className="text-red-target">DQ</span>;
  if (player.stood) return <span className="text-cyan">STOOD</span>;
  return <span className="text-green-target">ACTIVE</span>;
}

function shouldShowCardStack(player) {
  // Either the local player has explicit cards, or any player has a non-zero
  // card_count (face-down for opponents).
  return (player.cards && player.cards.length > 0) || (player.card_count || 0) > 0;
}

// --- component -----------------------------------------------------------

export function PlayerSeat({ player, isMe, isCurrentTurn, isLocal }) {
  if (!player) return null;
  const stateClass = panelClass(player, isCurrentTurn, isLocal);

  return (
    <div className={`${stateClass} px-4 py-3 min-w-[180px]`} data-testid={`seat-${player.seat_index}`}>
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-full bg-gradient-to-br from-zinc-700 to-zinc-900 border border-gold/40 flex items-center justify-center font-display text-gold text-sm">
          {player.username?.charAt(0)?.toUpperCase() || "?"}
        </div>
        <div className="flex-1 min-w-0">
          <div className="font-display text-sm text-gold/90 tracking-widest truncate">
            {player.username || `P${player.seat_index + 1}`}{isMe ? " (YOU)" : ""}
          </div>
          <div className="text-xs text-neutral-mid uppercase tracking-widest">
            <PlayerStatusBadge player={player} />
          </div>
        </div>
        {/* Card stack indicator */}
        <div className="relative w-10 h-12 flex items-end justify-end">
          {shouldShowCardStack(player) && (
            <div className="absolute right-0 bottom-0 scale-50 origin-bottom-right">
              <PlayingCard faceDown />
            </div>
          )}
          <span className="absolute -bottom-1 -right-1 bg-black/80 border border-gold/50 text-gold text-[10px] font-num px-1 rounded">
            {(isMe ? player.cards?.length : player.card_count) || 0}
          </span>
        </div>
      </div>
      <div className="mt-2 flex items-center justify-between">
        <div className="text-[10px] text-neutral-mid uppercase tracking-widest">Balance</div>
        <div className="font-num text-sm text-gold">{(player.balance_at_start ?? 0).toLocaleString()}</div>
      </div>
      <div className="flex items-center justify-between">
        <div className="text-[10px] text-neutral-mid uppercase tracking-widest">Bet</div>
        <div className="font-num text-sm text-cyan">{(player.current_bet ?? 0).toLocaleString()}</div>
      </div>
      {isMe && (
        <div className="flex items-center justify-between mt-1 pt-1 border-t border-gold/20">
          <div className="text-[10px] text-neutral-mid uppercase tracking-widest">Score</div>
          <div className="font-num text-base text-gold">{player.score ?? 0}{player.soft ? " (soft)" : ""}</div>
        </div>
      )}
    </div>
  );
}
